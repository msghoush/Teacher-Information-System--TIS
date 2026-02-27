from fastapi import FastAPI, Request, Form, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
from datetime import datetime
import io
import math
import os
import re
import time
from typing import Optional
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from database import engine, SessionLocal
import models
import auth
from dependencies import get_db
from routers import subjects, users, teachers, planning
from auth import get_password_hash
from models import User, Branch, AcademicYear
from audit import (
    get_audit_log_path,
    get_audit_logger,
    write_audit_event,
    iter_audit_csv_bytes,
    get_audit_csv_filename,
    build_audit_xlsx_bytes,
    get_audit_xlsx_filename,
)

# ---------------------------------------
# Create Tables
# ---------------------------------------
models.Base.metadata.create_all(bind=engine)

# ---------------------------------------
# App Initialization
# ---------------------------------------
app = FastAPI(title="Teacher Information System")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
ACADEMIC_YEAR_NAME_PATTERN = re.compile(r"^\d{4}-\d{4}$")
REPORT_STANDARD_MAX_HOURS = 24
CROSS_SUBJECT_SUPPORT_RULES = {
    "english": {"social studies english"},
    "arabic": {"social studies ksa"},
    "arbic": {"social studies ksa"},
}
CROSS_SUBJECT_HIRING_ANCHOR_PRIORITY = [
    "english",
    "arabic",
    "arbic",
    "social studies english",
    "social studies ksa",
]
REPORT_EXPORT_SUBJECT_FILL_PALETTE = [
    "E8F1FF",
    "EAF8F4",
    "FFF4E6",
    "FDECF3",
    "EEEAFE",
    "E9F8FF",
    "F2F7E8",
    "FCEBEB",
]
get_audit_logger()


def _resolve_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


def _resolve_audit_actor(request: Request):
    actor_user_id = getattr(request.state, "audit_actor_user_id", None)
    actor_username = getattr(request.state, "audit_actor_username", None)
    actor_role = getattr(request.state, "audit_actor_role", None)
    actor_branch_id = getattr(request.state, "audit_actor_branch_id", None)

    if actor_user_id:
        return {
            "actor_user_id": actor_user_id,
            "actor_username": actor_username or "",
            "actor_role": actor_role or "",
            "actor_branch_id": actor_branch_id,
        }

    cookie_user_id = request.cookies.get("user_id")
    if cookie_user_id:
        return {
            "actor_user_id": cookie_user_id,
            "actor_username": "",
            "actor_role": "Unknown",
            "actor_branch_id": None,
        }

    return {
        "actor_user_id": "anonymous",
        "actor_username": "",
        "actor_role": "Anonymous",
        "actor_branch_id": None,
    }


def _write_request_audit_log(
    request: Request,
    status_code: int,
    duration_ms: float,
    error_name: str = "",
):
    try:
        actor = _resolve_audit_actor(request)
        write_audit_event(
            {
                "event_type": "http_request",
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "status_code": status_code,
                "duration_ms": duration_ms,
                "client_ip": _resolve_client_ip(request),
                "user_agent": request.headers.get("user-agent", ""),
                "scope_branch_id": request.cookies.get("branch_id"),
                "scope_academic_year_id": request.cookies.get("academic_year_id"),
                "error": error_name,
                **actor,
            }
        )
    except Exception:
        # Audit logging must not block business operations.
        pass


def _normalize_grade_label(value) -> str:
    cleaned = str(value).strip().upper()
    if cleaned in {"0", "K", "KG", "KINDERGARTEN"}:
        return "KG"
    try:
        parsed = int(cleaned)
    except (TypeError, ValueError):
        return ""
    if 1 <= parsed <= 12:
        return str(parsed)
    return ""


def _grade_sort_key(grade_label: str) -> int:
    if grade_label == "KG":
        return 0
    try:
        return int(grade_label)
    except (TypeError, ValueError):
        return 99


def _build_subject_identity(subject_name: str, fallback_code: str = ""):
    cleaned_name = " ".join(str(subject_name or "").split())
    if cleaned_name:
        return cleaned_name.lower(), cleaned_name

    cleaned_code = " ".join(str(fallback_code or "").split()).upper()
    if cleaned_code:
        return cleaned_code.lower(), cleaned_code

    return "", ""


def _build_teacher_display_name(teacher) -> str:
    name_parts = [
        str(teacher.first_name or "").strip(),
        str(teacher.middle_name or "").strip(),
        str(teacher.last_name or "").strip(),
    ]
    full_name = " ".join(part for part in name_parts if part).strip()
    if full_name:
        return full_name
    return f"Teacher #{teacher.id}"


def _normalize_subject_family_key(value: str) -> str:
    return " ".join(str(value or "").split()).lower()


def _build_reporting_context(
    db: Session,
    subjects,
    planning_sections,
    teachers,
):
    sections_by_grade = {}
    current_sections_by_grade = {}
    new_sections_by_grade = {}

    for section in planning_sections:
        grade_label = _normalize_grade_label(section.grade_level)
        if not grade_label:
            continue

        sections_by_grade[grade_label] = sections_by_grade.get(grade_label, 0) + 1
        status = str(section.class_status or "").strip().lower()
        if status == "current":
            current_sections_by_grade[grade_label] = (
                current_sections_by_grade.get(grade_label, 0) + 1
            )
        elif status == "new":
            new_sections_by_grade[grade_label] = (
                new_sections_by_grade.get(grade_label, 0) + 1
            )

    scoped_subjects_by_code = {
        subject.subject_code: subject
        for subject in subjects
        if subject.subject_code
    }
    subject_demand_map = {}
    required_hours_by_grade = {}
    required_current_hours_by_grade = {}
    required_new_hours_by_grade = {}

    for subject in subjects:
        grade_label = _normalize_grade_label(subject.grade)
        if not grade_label:
            continue

        weekly_hours = int(subject.weekly_hours or 0)
        if weekly_hours <= 0:
            continue

        sections_count = sections_by_grade.get(grade_label, 0)
        if sections_count <= 0:
            continue

        current_sections_count = current_sections_by_grade.get(grade_label, 0)
        new_sections_count = new_sections_by_grade.get(grade_label, 0)

        subject_key, subject_label = _build_subject_identity(
            subject_name=subject.subject_name,
            fallback_code=subject.subject_code or "",
        )
        if not subject_key:
            continue

        required_hours = weekly_hours * sections_count
        required_current_hours = weekly_hours * current_sections_count
        required_new_hours = weekly_hours * new_sections_count

        required_hours_by_grade[grade_label] = (
            required_hours_by_grade.get(grade_label, 0) + required_hours
        )
        required_current_hours_by_grade[grade_label] = (
            required_current_hours_by_grade.get(grade_label, 0) + required_current_hours
        )
        required_new_hours_by_grade[grade_label] = (
            required_new_hours_by_grade.get(grade_label, 0) + required_new_hours
        )

        if subject_key not in subject_demand_map:
            subject_demand_map[subject_key] = {
                "subject_name": subject_label,
                "required_hours": 0,
                "required_current_hours": 0,
                "required_new_hours": 0,
                "grades": set(),
            }

        entry = subject_demand_map[subject_key]
        entry["required_hours"] += required_hours
        entry["required_current_hours"] += required_current_hours
        entry["required_new_hours"] += required_new_hours
        entry["grades"].add(grade_label)

    teacher_subject_map = {
        teacher.id: set()
        for teacher in teachers
        if getattr(teacher, "id", None)
    }
    teacher_subject_hours_map = {
        teacher.id: {}
        for teacher in teachers
        if getattr(teacher, "id", None)
    }
    teacher_ids = sorted(teacher_subject_map.keys())

    if teacher_ids:
        teacher_allocations = db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids)
        ).all()
    else:
        teacher_allocations = []

    for allocation in teacher_allocations:
        subject_key_set = teacher_subject_map.get(allocation.teacher_id)
        if subject_key_set is None:
            continue

        subject = scoped_subjects_by_code.get(allocation.subject_code)
        if not subject:
            continue

        subject_key, _ = _build_subject_identity(
            subject_name=subject.subject_name,
            fallback_code=subject.subject_code or "",
        )
        if not subject_key or subject_key not in subject_demand_map:
            continue
        subject_key_set.add(subject_key)
        subject_hours = int(subject.weekly_hours or 0)
        subject_hours_map = teacher_subject_hours_map.get(allocation.teacher_id, {})
        subject_hours_map[subject_key] = (
            subject_hours_map.get(subject_key, 0) + max(subject_hours, 0)
        )

    for teacher in teachers:
        subject_key_set = teacher_subject_map.get(getattr(teacher, "id", None))
        if subject_key_set is None or subject_key_set:
            continue

        fallback_code = str(teacher.subject_code or "").strip().upper()
        if not fallback_code:
            continue

        fallback_subject = scoped_subjects_by_code.get(fallback_code)
        if not fallback_subject:
            continue

        subject_key, _ = _build_subject_identity(
            subject_name=fallback_subject.subject_name,
            fallback_code=fallback_subject.subject_code or "",
        )
        if subject_key and subject_key in subject_demand_map:
            subject_key_set.add(subject_key)
            fallback_subject_hours_map = teacher_subject_hours_map.get(
                getattr(teacher, "id", None),
                {},
            )
            fallback_subject_hours_map[subject_key] = max(
                fallback_subject_hours_map.get(subject_key, 0),
                int(fallback_subject.weekly_hours or 0),
            )

    teacher_profiles = []
    for teacher in teachers:
        teacher_id = getattr(teacher, "id", None)
        candidate_subject_keys = sorted(
            teacher_subject_map.get(teacher_id, set()),
            key=lambda key: subject_demand_map[key]["subject_name"],
        )
        subject_hours_map = teacher_subject_hours_map.get(teacher_id, {})
        primary_subject_keys = []
        primary_subject_key = None
        if candidate_subject_keys:
            ranked_subject_keys = sorted(
                candidate_subject_keys,
                key=lambda key: (
                    -subject_hours_map.get(key, 0),
                    -subject_demand_map[key]["required_hours"],
                    subject_demand_map[key]["subject_name"],
                ),
            )
            primary_subject_key = ranked_subject_keys[0]
            primary_subject_keys = [primary_subject_key]

        support_subject_keys = set()
        if primary_subject_key:
            for support_subject_key in CROSS_SUBJECT_SUPPORT_RULES.get(
                primary_subject_key,
                set(),
            ):
                normalized_support_key = _normalize_subject_family_key(
                    support_subject_key
                )
                if (
                    normalized_support_key
                    and normalized_support_key in subject_demand_map
                    and normalized_support_key not in primary_subject_keys
                ):
                    support_subject_keys.add(normalized_support_key)

        sorted_support_subject_keys = sorted(
            support_subject_keys,
            key=lambda key: subject_demand_map[key]["subject_name"],
        )

        teacher_profiles.append(
            {
                "teacher": teacher,
                "name": _build_teacher_display_name(teacher),
                "subject_keys": primary_subject_keys,
                "support_subject_keys": sorted_support_subject_keys,
                "eligible_subject_keys": primary_subject_keys + sorted_support_subject_keys,
                "subject_count": len(primary_subject_keys),
                "primary_subject_basis_hours": (
                    subject_hours_map.get(primary_subject_key, 0)
                    if primary_subject_key
                    else 0
                ),
                "allocated_hours": 0,
                "remaining_capacity_hours": REPORT_STANDARD_MAX_HOURS,
                "allocation_breakdown": {},
            }
        )

    remaining_hours_by_subject = {
        subject_key: data["required_hours"]
        for subject_key, data in subject_demand_map.items()
    }

    allocation_sequence = sorted(
        teacher_profiles,
        key=lambda profile: (
            profile["subject_count"] if profile["subject_count"] else 999,
            profile["name"],
            profile["teacher"].id or 0,
        ),
    )

    for profile in allocation_sequence:
        if not profile["eligible_subject_keys"]:
            continue

        remaining_capacity = REPORT_STANDARD_MAX_HOURS
        allocation_breakdown = {}

        while remaining_capacity > 0:
            primary_candidate_subject_keys = [
                subject_key
                for subject_key in profile["subject_keys"]
                if remaining_hours_by_subject.get(subject_key, 0) > 0
            ]

            if primary_candidate_subject_keys:
                candidate_subject_keys = primary_candidate_subject_keys
            else:
                candidate_subject_keys = [
                    subject_key
                    for subject_key in profile["support_subject_keys"]
                    if remaining_hours_by_subject.get(subject_key, 0) > 0
                ]

            if not candidate_subject_keys:
                break

            candidate_subject_keys.sort(
                key=lambda subject_key: (
                    -remaining_hours_by_subject.get(subject_key, 0),
                    subject_demand_map[subject_key]["subject_name"],
                )
            )
            selected_subject_key = candidate_subject_keys[0]
            subject_remaining_hours = remaining_hours_by_subject.get(
                selected_subject_key, 0
            )
            allocated_hours = min(remaining_capacity, subject_remaining_hours)
            if allocated_hours <= 0:
                break

            allocation_breakdown[selected_subject_key] = (
                allocation_breakdown.get(selected_subject_key, 0) + allocated_hours
            )
            remaining_hours_by_subject[selected_subject_key] = (
                subject_remaining_hours - allocated_hours
            )
            remaining_capacity -= allocated_hours

        allocated_hours_total = sum(allocation_breakdown.values())
        if allocated_hours_total > REPORT_STANDARD_MAX_HOURS:
            overflow_hours = allocated_hours_total - REPORT_STANDARD_MAX_HOURS
            reduction_order = (
                list(profile["support_subject_keys"]) + list(profile["subject_keys"])
            )
            for subject_key in reduction_order:
                if overflow_hours <= 0:
                    break
                current_hours = allocation_breakdown.get(subject_key, 0)
                if current_hours <= 0:
                    continue
                reduce_hours = min(current_hours, overflow_hours)
                updated_hours = current_hours - reduce_hours
                if updated_hours > 0:
                    allocation_breakdown[subject_key] = updated_hours
                else:
                    allocation_breakdown.pop(subject_key, None)
                remaining_hours_by_subject[subject_key] = (
                    remaining_hours_by_subject.get(subject_key, 0) + reduce_hours
                )
                overflow_hours -= reduce_hours

        primary_allocated_hours = sum(
            allocation_breakdown.get(subject_key, 0)
            for subject_key in profile["subject_keys"]
        )
        support_allocated_hours = sum(
            allocation_breakdown.get(subject_key, 0)
            for subject_key in profile["support_subject_keys"]
        )
        total_allocated_hours = min(
            sum(allocation_breakdown.values()),
            REPORT_STANDARD_MAX_HOURS,
        )
        profile["allocation_breakdown"] = allocation_breakdown
        profile["allocated_hours"] = total_allocated_hours
        profile["primary_allocated_hours"] = primary_allocated_hours
        profile["support_allocated_hours"] = support_allocated_hours
        profile["remaining_capacity_hours"] = (
            REPORT_STANDARD_MAX_HOURS - total_allocated_hours
        )

    teachers_per_subject = {}
    for profile in teacher_profiles:
        for subject_key in profile["eligible_subject_keys"]:
            teachers_per_subject[subject_key] = (
                teachers_per_subject.get(subject_key, 0) + 1
            )

    rule_subject_graph = {}
    for primary_subject_key, support_subject_keys in CROSS_SUBJECT_SUPPORT_RULES.items():
        normalized_primary_subject_key = _normalize_subject_family_key(primary_subject_key)
        if normalized_primary_subject_key not in subject_demand_map:
            continue

        rule_subject_graph.setdefault(normalized_primary_subject_key, set())
        for support_subject_key in support_subject_keys:
            normalized_support_subject_key = _normalize_subject_family_key(
                support_subject_key
            )
            if normalized_support_subject_key not in subject_demand_map:
                continue
            rule_subject_graph.setdefault(normalized_support_subject_key, set())
            rule_subject_graph[normalized_primary_subject_key].add(
                normalized_support_subject_key
            )
            rule_subject_graph[normalized_support_subject_key].add(
                normalized_primary_subject_key
            )

    subject_additional_teachers_map = {}
    subject_additional_teachers_note_map = {}
    pooled_subject_keys = set()
    total_additional_teachers_needed = 0
    visited_rule_subjects = set()

    for subject_key in sorted(rule_subject_graph.keys()):
        if subject_key in visited_rule_subjects:
            continue

        stack = [subject_key]
        component_subject_keys = set()
        while stack:
            current_subject_key = stack.pop()
            if current_subject_key in visited_rule_subjects:
                continue
            visited_rule_subjects.add(current_subject_key)
            component_subject_keys.add(current_subject_key)
            for neighbor_subject_key in rule_subject_graph.get(current_subject_key, set()):
                if neighbor_subject_key not in visited_rule_subjects:
                    stack.append(neighbor_subject_key)

        component_with_remaining = [
            item_key
            for item_key in component_subject_keys
            if remaining_hours_by_subject.get(item_key, 0) > 0
        ]
        if not component_with_remaining:
            continue

        component_remaining_hours = sum(
            remaining_hours_by_subject.get(item_key, 0)
            for item_key in component_with_remaining
        )
        component_teachers_needed = math.ceil(
            component_remaining_hours / REPORT_STANDARD_MAX_HOURS
        )
        total_additional_teachers_needed += component_teachers_needed
        pooled_subject_keys.update(component_with_remaining)

        anchor_subject_key = next(
            (
                candidate_key
                for candidate_key in CROSS_SUBJECT_HIRING_ANCHOR_PRIORITY
                if candidate_key in component_with_remaining
            ),
            None,
        )
        if not anchor_subject_key:
            anchor_subject_key = sorted(
                component_with_remaining,
                key=lambda item_key: (
                    -remaining_hours_by_subject.get(item_key, 0),
                    subject_demand_map[item_key]["subject_name"],
                ),
            )[0]

        component_subject_names = sorted(
            subject_demand_map[item_key]["subject_name"]
            for item_key in component_with_remaining
        )
        for item_key in component_with_remaining:
            if item_key == anchor_subject_key:
                subject_additional_teachers_map[item_key] = component_teachers_needed
                if len(component_with_remaining) > 1:
                    subject_additional_teachers_note_map[item_key] = (
                        "Combined hiring pool: "
                        + ", ".join(component_subject_names)
                    )
            else:
                subject_additional_teachers_map[item_key] = 0
                subject_additional_teachers_note_map[item_key] = (
                    "Counted in "
                    + subject_demand_map[anchor_subject_key]["subject_name"]
                    + " combined pool."
                )

    for subject_key, remaining_hours in remaining_hours_by_subject.items():
        if remaining_hours <= 0 or subject_key in pooled_subject_keys:
            continue

        subject_teachers_needed = math.ceil(
            remaining_hours / REPORT_STANDARD_MAX_HOURS
        )
        subject_additional_teachers_map[subject_key] = subject_teachers_needed
        total_additional_teachers_needed += subject_teachers_needed

    report_subject_rows = []
    for subject_key, demand in subject_demand_map.items():
        required_hours = demand["required_hours"]
        remaining_hours = remaining_hours_by_subject.get(subject_key, 0)
        allocated_hours = max(required_hours - remaining_hours, 0)
        additional_teachers_needed = subject_additional_teachers_map.get(subject_key, 0)
        additional_teachers_note = subject_additional_teachers_note_map.get(
            subject_key,
            "",
        )
        grades = sorted(demand["grades"], key=_grade_sort_key)
        coverage_percentage = (
            round((allocated_hours / required_hours) * 100)
            if required_hours > 0
            else 0
        )

        report_subject_rows.append(
            {
                "subject_key": subject_key,
                "subject_name": demand["subject_name"],
                "grades": grades,
                "required_hours": required_hours,
                "required_current_hours": demand["required_current_hours"],
                "required_new_hours": demand["required_new_hours"],
                "allocated_hours": allocated_hours,
                "remaining_hours": remaining_hours,
                "coverage_percentage": coverage_percentage,
                "teachers_with_subject": teachers_per_subject.get(subject_key, 0),
                "additional_teachers_needed": additional_teachers_needed,
                "additional_teachers_note": additional_teachers_note,
            }
        )

    report_subject_rows.sort(
        key=lambda row: (
            -row["remaining_hours"],
            row["subject_name"],
        )
    )

    report_gap_rows = [
        dict(row)
        for row in report_subject_rows
        if row["remaining_hours"] > 0
    ]
    max_remaining_hours = max(
        (row["remaining_hours"] for row in report_gap_rows),
        default=0,
    )
    for row in report_gap_rows:
        row["gap_chart_pct"] = (
            round((row["remaining_hours"] / max_remaining_hours) * 100, 1)
            if max_remaining_hours > 0
            else 0
        )
    report_gap_rows = report_gap_rows[:8]

    report_teacher_rows = []
    for profile in teacher_profiles:
        subject_labels = [
            subject_demand_map[subject_key]["subject_name"]
            for subject_key in profile["subject_keys"]
        ]
        support_subject_labels = [
            subject_demand_map[subject_key]["subject_name"]
            for subject_key in profile["support_subject_keys"]
        ]
        allocation_labels = [
            f"{subject_demand_map[subject_key]['subject_name']} ({hours}h)"
            for subject_key, hours in sorted(
                profile["allocation_breakdown"].items(),
                key=lambda item: (-item[1], subject_demand_map[item[0]]["subject_name"]),
            )
        ]

        teacher = profile["teacher"]
        report_teacher_rows.append(
            {
                "teacher_id": teacher.teacher_id or "-",
                "teacher_name": profile["name"],
                "subject_labels": subject_labels,
                "support_subject_labels": support_subject_labels,
                "allocation_labels": allocation_labels,
                "expected_allocated_hours": profile["allocated_hours"],
                "primary_allocated_hours": profile.get("primary_allocated_hours", 0),
                "support_allocated_hours": profile.get("support_allocated_hours", 0),
                "primary_subject_basis_hours": profile.get(
                    "primary_subject_basis_hours",
                    0,
                ),
                "remaining_capacity_hours": profile["remaining_capacity_hours"],
            }
        )

    report_teacher_rows.sort(
        key=lambda row: (
            -row["expected_allocated_hours"],
            row["teacher_name"],
        )
    )

    report_grade_rows = []
    for grade_label, total_sections in sections_by_grade.items():
        report_grade_rows.append(
            {
                "grade_label": grade_label,
                "sections_total": total_sections,
                "sections_current": current_sections_by_grade.get(grade_label, 0),
                "sections_new": new_sections_by_grade.get(grade_label, 0),
                "required_hours_total": required_hours_by_grade.get(grade_label, 0),
                "required_hours_current": required_current_hours_by_grade.get(
                    grade_label, 0
                ),
                "required_hours_new": required_new_hours_by_grade.get(grade_label, 0),
            }
        )
    report_grade_rows.sort(
        key=lambda row: _grade_sort_key(row["grade_label"])
    )

    total_required_hours = sum(
        row["required_hours"] for row in report_subject_rows
    )
    total_remaining_hours = sum(
        row["remaining_hours"] for row in report_subject_rows
    )
    total_allocated_hours = total_required_hours - total_remaining_hours
    total_existing_teachers = len(teachers)
    total_existing_capacity_hours = total_existing_teachers * REPORT_STANDARD_MAX_HOURS
    coverage_percentage = (
        round((total_allocated_hours / total_required_hours) * 100)
        if total_required_hours > 0
        else 0
    )
    teachers_with_subject_alignment = sum(
        1 for profile in teacher_profiles if profile["subject_count"] > 0
    )
    teachers_utilized = sum(
        1 for profile in teacher_profiles if profile["allocated_hours"] > 0
    )
    teachers_full_load = sum(
        1
        for profile in teacher_profiles
        if profile["allocated_hours"] >= REPORT_STANDARD_MAX_HOURS
    )
    unused_existing_capacity_hours = max(
        total_existing_capacity_hours - total_allocated_hours,
        0,
    )
    total_required_current_hours = sum(
        required_current_hours_by_grade.values()
    )
    total_required_new_hours = sum(
        required_new_hours_by_grade.values()
    )
    total_new_sections_planned = sum(new_sections_by_grade.values())
    total_new_teachers_required = total_additional_teachers_needed
    total_teachers_needed_branch = (
        total_existing_teachers + total_new_teachers_required
    )

    report_summary = {
        "total_required_hours": total_required_hours,
        "total_required_current_hours": total_required_current_hours,
        "total_required_new_hours": total_required_new_hours,
        "total_allocated_hours": total_allocated_hours,
        "total_remaining_hours": total_remaining_hours,
        "coverage_percentage": coverage_percentage,
        "total_additional_teachers_needed": total_additional_teachers_needed,
        "total_existing_teachers": total_existing_teachers,
        "total_existing_capacity_hours": total_existing_capacity_hours,
        "unused_existing_capacity_hours": unused_existing_capacity_hours,
        "teachers_with_subject_alignment": teachers_with_subject_alignment,
        "teachers_utilized": teachers_utilized,
        "teachers_full_load": teachers_full_load,
        "teachers_idle": max(total_existing_teachers - teachers_utilized, 0),
        "total_new_sections_planned": total_new_sections_planned,
        "total_new_teachers_required": total_new_teachers_required,
        "total_teachers_needed_branch": total_teachers_needed_branch,
    }

    teacher_profiles_export = []
    for profile in teacher_profiles:
        teacher = profile["teacher"]
        teacher_profiles_export.append(
            {
                "teacher_pk": teacher.id,
                "teacher_id": teacher.teacher_id or "-",
                "teacher_name": profile["name"],
                "subject_keys": list(profile["subject_keys"]),
                "support_subject_keys": list(profile["support_subject_keys"]),
                "allocation_breakdown": dict(profile["allocation_breakdown"]),
                "allocated_hours": int(profile["allocated_hours"]),
                "remaining_capacity_hours": int(profile["remaining_capacity_hours"]),
                "primary_allocated_hours": int(profile.get("primary_allocated_hours", 0)),
                "support_allocated_hours": int(profile.get("support_allocated_hours", 0)),
                "primary_subject_basis_hours": int(
                    profile.get("primary_subject_basis_hours", 0)
                ),
            }
        )

    return {
        "summary": report_summary,
        "subject_rows": report_subject_rows,
        "gap_rows": report_gap_rows,
        "teacher_rows": report_teacher_rows,
        "grade_rows": report_grade_rows,
        "teacher_profiles": teacher_profiles_export,
    }


def _build_report_class_rows(planning_sections):
    class_rows = []
    seen_class_keys = set()

    for section in planning_sections:
        grade_label = _normalize_grade_label(section.grade_level)
        if not grade_label:
            continue

        section_name = str(section.section_name or "").strip().upper()
        if not section_name:
            continue

        class_key = f"{grade_label}-{section_name}"
        if class_key in seen_class_keys:
            continue
        seen_class_keys.add(class_key)

        raw_status = str(section.class_status or "").strip().lower()
        class_status = "New" if raw_status == "new" else "Current"
        display_grade = "KG" if grade_label == "KG" else f"G{grade_label}"

        class_rows.append(
            {
                "class_key": class_key,
                "class_label": f"{display_grade}-{section_name}",
                "grade_label": grade_label,
                "section_name": section_name,
                "class_status": class_status,
            }
        )

    class_rows.sort(
        key=lambda row: (
            _grade_sort_key(row["grade_label"]),
            row["section_name"],
            0 if row["class_status"] == "Current" else 1,
        )
    )
    return class_rows


def _build_report_subject_catalog(subjects):
    subjects_by_grade = {}
    subject_name_by_key = {}

    for subject in subjects:
        grade_label = _normalize_grade_label(subject.grade)
        if not grade_label:
            continue

        weekly_hours = int(subject.weekly_hours or 0)
        if weekly_hours <= 0:
            continue

        subject_code = str(subject.subject_code or "").strip().upper()
        subject_key, subject_name = _build_subject_identity(
            subject_name=subject.subject_name,
            fallback_code=subject_code,
        )
        if not subject_key:
            continue

        if subject_key not in subject_name_by_key:
            subject_name_by_key[subject_key] = subject_name

        subjects_by_grade.setdefault(grade_label, []).append(
            {
                "subject_key": subject_key,
                "subject_code": subject_code or subject_name,
                "subject_name": subject_name,
                "weekly_hours": weekly_hours,
            }
        )

    for grade_label in subjects_by_grade:
        subjects_by_grade[grade_label].sort(
            key=lambda item: (item["subject_name"], item["subject_code"])
        )

    return subjects_by_grade, subject_name_by_key


def _build_report_class_allocation_data(subjects, planning_sections, reporting_context):
    class_rows = _build_report_class_rows(planning_sections)
    subjects_by_grade, subject_name_by_key = _build_report_subject_catalog(subjects)
    teacher_profiles = reporting_context.get("teacher_profiles", [])

    demand_items_by_subject = {}
    for class_row in class_rows:
        grade_subjects = subjects_by_grade.get(class_row["grade_label"], [])
        for subject_item in grade_subjects:
            demand_items_by_subject.setdefault(subject_item["subject_key"], []).append(
                {
                    "class_key": class_row["class_key"],
                    "class_label": class_row["class_label"],
                    "class_status": class_row["class_status"],
                    "grade_label": class_row["grade_label"],
                    "section_name": class_row["section_name"],
                    "subject_key": subject_item["subject_key"],
                    "subject_code": subject_item["subject_code"],
                    "subject_name": subject_item["subject_name"],
                    "required_hours": subject_item["weekly_hours"],
                    "remaining_hours": subject_item["weekly_hours"],
                }
            )

    for subject_key in demand_items_by_subject:
        demand_items_by_subject[subject_key].sort(
            key=lambda item: (
                0 if item["class_status"] == "Current" else 1,
                _grade_sort_key(item["grade_label"]),
                item["section_name"],
                item["class_label"],
            )
        )

    sorted_profiles = sorted(
        teacher_profiles,
        key=lambda profile: (
            -int(profile.get("allocated_hours", 0)),
            profile.get("teacher_name", ""),
            str(profile.get("teacher_id", "")),
        ),
    )

    teacher_matrix_rows = []
    assignment_rows = []

    for profile in sorted_profiles:
        allocation_breakdown = profile.get("allocation_breakdown", {}) or {}
        primary_subject_keys = list(profile.get("subject_keys", []))
        support_subject_keys = list(profile.get("support_subject_keys", []))

        ordered_subject_keys = []
        for subject_key in primary_subject_keys + support_subject_keys:
            if subject_key not in ordered_subject_keys:
                ordered_subject_keys.append(subject_key)
        for subject_key in sorted(allocation_breakdown.keys()):
            if subject_key not in ordered_subject_keys:
                ordered_subject_keys.append(subject_key)

        class_allocations = {}

        for subject_key in ordered_subject_keys:
            subject_hours_quota = int(allocation_breakdown.get(subject_key, 0))
            if subject_hours_quota <= 0:
                continue

            for demand_item in demand_items_by_subject.get(subject_key, []):
                if subject_hours_quota <= 0:
                    break

                subject_hours_remaining = int(demand_item["remaining_hours"])
                if subject_hours_remaining <= 0:
                    continue

                allocated_hours = min(subject_hours_quota, subject_hours_remaining)
                demand_item["remaining_hours"] = subject_hours_remaining - allocated_hours
                subject_hours_quota -= allocated_hours

                class_key = demand_item["class_key"]
                class_allocations.setdefault(class_key, []).append(
                    {
                        "subject_key": subject_key,
                        "subject_code": demand_item["subject_code"],
                        "subject_name": demand_item["subject_name"],
                        "allocated_hours": allocated_hours,
                        "class_status": demand_item["class_status"],
                    }
                )

                assignment_rows.append(
                    {
                        "teacher_id": profile.get("teacher_id", "-"),
                        "teacher_name": profile.get("teacher_name", "-"),
                        "class_label": demand_item["class_label"],
                        "class_status": demand_item["class_status"],
                        "subject_code": demand_item["subject_code"],
                        "subject_name": demand_item["subject_name"],
                        "allocated_hours": allocated_hours,
                        "coverage_type": (
                            "Support"
                            if subject_key in support_subject_keys
                            else "Primary"
                        ),
                    }
                )

        class_cells = {}
        class_fill_subject_keys = {}
        for class_key, allocation_items in class_allocations.items():
            allocation_items.sort(
                key=lambda item: (-item["allocated_hours"], item["subject_code"])
            )
            class_cells[class_key] = "\n".join(
                f"{item['subject_code']} ({item['allocated_hours']}h)"
                for item in allocation_items
            )
            class_fill_subject_keys[class_key] = allocation_items[0]["subject_key"]

        teacher_matrix_rows.append(
            {
                "teacher_id": profile.get("teacher_id", "-"),
                "teacher_name": profile.get("teacher_name", "-"),
                "expected_allocated_hours": int(profile.get("allocated_hours", 0)),
                "remaining_capacity_hours": int(
                    profile.get("remaining_capacity_hours", REPORT_STANDARD_MAX_HOURS)
                ),
                "primary_subject_label": ", ".join(
                    subject_name_by_key.get(subject_key, subject_key.title())
                    for subject_key in primary_subject_keys
                )
                or "-",
                "support_subject_label": ", ".join(
                    subject_name_by_key.get(subject_key, subject_key.title())
                    for subject_key in support_subject_keys
                )
                or "-",
                "class_cells": class_cells,
                "class_fill_subject_keys": class_fill_subject_keys,
            }
        )

    assignment_rows.sort(
        key=lambda row: (
            row["teacher_name"],
            row["class_label"],
            row["subject_code"],
        )
    )

    unassigned_rows = []
    for subject_items in demand_items_by_subject.values():
        for demand_item in subject_items:
            if int(demand_item["remaining_hours"]) <= 0:
                continue
            unassigned_rows.append(
                {
                    "class_label": demand_item["class_label"],
                    "class_status": demand_item["class_status"],
                    "subject_code": demand_item["subject_code"],
                    "subject_name": demand_item["subject_name"],
                    "remaining_hours": int(demand_item["remaining_hours"]),
                }
            )

    unassigned_rows.sort(
        key=lambda row: (
            row["class_label"],
            row["subject_code"],
        )
    )

    return {
        "class_rows": class_rows,
        "teacher_matrix_rows": teacher_matrix_rows,
        "assignment_rows": assignment_rows,
        "unassigned_rows": unassigned_rows,
    }


def _apply_excel_header_style(sheet, header_row: int, total_columns: int):
    header_fill = PatternFill(start_color="0A4EA3", end_color="0A4EA3", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for column_index in range(1, total_columns + 1):
        cell = sheet.cell(row=header_row, column=column_index)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _subject_fill_for_key(subject_key: str):
    if not subject_key:
        return None
    palette_index = sum(ord(char) for char in subject_key) % len(
        REPORT_EXPORT_SUBJECT_FILL_PALETTE
    )
    color_code = REPORT_EXPORT_SUBJECT_FILL_PALETTE[palette_index]
    return PatternFill(start_color=color_code, end_color=color_code, fill_type="solid")


def _build_report_allocation_filename(branch_name: str, academic_year_name: str) -> str:
    def _sanitize(text_value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]+", "-", str(text_value or "").strip())
        return normalized.strip("-").lower() or "scope"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_branch = _sanitize(branch_name)
    safe_year = _sanitize(academic_year_name)
    return f"teacher_allocation_plan_{safe_branch}_{safe_year}_{timestamp}.xlsx"


def _build_report_allocation_xlsx_bytes(
    branch_name: str,
    academic_year_name: str,
    subjects,
    planning_sections,
    reporting_context,
) -> bytes:
    allocation_data = _build_report_class_allocation_data(
        subjects=subjects,
        planning_sections=planning_sections,
        reporting_context=reporting_context,
    )

    class_rows = allocation_data["class_rows"]
    teacher_matrix_rows = allocation_data["teacher_matrix_rows"]
    assignment_rows = allocation_data["assignment_rows"]
    unassigned_rows = allocation_data["unassigned_rows"]

    report_summary = reporting_context.get("summary", {})
    report_subject_rows = reporting_context.get("subject_rows", [])
    report_teacher_rows = reporting_context.get("teacher_rows", [])

    workbook = Workbook()
    matrix_sheet = workbook.active
    matrix_sheet.title = "Teacher_Class_Matrix"

    matrix_headers = [
        "Teacher ID",
        "Teacher Name",
        "Expected Hours (24h)",
        "Remaining Capacity",
        "Primary Subject",
        "Support Subject",
    ] + [class_row["class_label"] for class_row in class_rows]
    matrix_sheet.append(matrix_headers)
    _apply_excel_header_style(
        sheet=matrix_sheet,
        header_row=1,
        total_columns=len(matrix_headers),
    )
    matrix_sheet.freeze_panes = "A2"
    matrix_sheet.auto_filter.ref = f"A1:{get_column_letter(len(matrix_headers))}1"

    full_load_fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    under_load_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    neutral_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    class_column_start = 7
    class_order = [class_row["class_key"] for class_row in class_rows]

    for row_data in teacher_matrix_rows:
        matrix_row = [
            row_data["teacher_id"],
            row_data["teacher_name"],
            row_data["expected_allocated_hours"],
            row_data["remaining_capacity_hours"],
            row_data["primary_subject_label"],
            row_data["support_subject_label"],
        ]
        matrix_row.extend(
            row_data["class_cells"].get(class_key, "")
            for class_key in class_order
        )
        matrix_sheet.append(matrix_row)
        excel_row_index = matrix_sheet.max_row

        expected_hours_cell = matrix_sheet.cell(row=excel_row_index, column=3)
        remaining_capacity_cell = matrix_sheet.cell(row=excel_row_index, column=4)
        if int(row_data["expected_allocated_hours"]) >= REPORT_STANDARD_MAX_HOURS:
            expected_hours_cell.fill = full_load_fill
            remaining_capacity_cell.fill = full_load_fill
        else:
            expected_hours_cell.fill = under_load_fill
            remaining_capacity_cell.fill = under_load_fill

        for class_offset, class_key in enumerate(class_order):
            column_index = class_column_start + class_offset
            class_cell = matrix_sheet.cell(row=excel_row_index, column=column_index)
            if not class_cell.value:
                continue
            fill_subject_key = row_data["class_fill_subject_keys"].get(class_key, "")
            class_fill = _subject_fill_for_key(fill_subject_key)
            if class_fill:
                class_cell.fill = class_fill
            class_cell.alignment = Alignment(
                horizontal="left",
                vertical="top",
                wrap_text=True,
            )

    matrix_sheet.column_dimensions["A"].width = 14
    matrix_sheet.column_dimensions["B"].width = 24
    matrix_sheet.column_dimensions["C"].width = 18
    matrix_sheet.column_dimensions["D"].width = 18
    matrix_sheet.column_dimensions["E"].width = 24
    matrix_sheet.column_dimensions["F"].width = 24
    for column_index in range(class_column_start, len(matrix_headers) + 1):
        matrix_sheet.column_dimensions[get_column_letter(column_index)].width = 18
    for row_index in range(2, matrix_sheet.max_row + 1):
        for col_index in range(1, 7):
            matrix_sheet.cell(row=row_index, column=col_index).alignment = Alignment(
                horizontal="left" if col_index in {2, 5, 6} else "center",
                vertical="top",
                wrap_text=True,
            )
        if matrix_sheet.max_column >= 7:
            matrix_sheet.row_dimensions[row_index].height = 38

    details_sheet = workbook.create_sheet("Teacher_Details")
    detail_headers = [
        "Teacher ID",
        "Teacher Name",
        "Class",
        "Class Status",
        "Subject Code",
        "Subject Name",
        "Allocated Hours",
        "Coverage Type",
    ]
    details_sheet.append(detail_headers)
    _apply_excel_header_style(
        sheet=details_sheet,
        header_row=1,
        total_columns=len(detail_headers),
    )
    details_sheet.freeze_panes = "A2"
    details_sheet.auto_filter.ref = f"A1:{get_column_letter(len(detail_headers))}1"

    support_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    new_class_fill = PatternFill(start_color="E0F2FE", end_color="E0F2FE", fill_type="solid")

    for item in assignment_rows:
        details_sheet.append(
            [
                item["teacher_id"],
                item["teacher_name"],
                item["class_label"],
                item["class_status"],
                item["subject_code"],
                item["subject_name"],
                item["allocated_hours"],
                item["coverage_type"],
            ]
        )
        row_index = details_sheet.max_row
        if item["coverage_type"] == "Support":
            details_sheet.cell(row=row_index, column=8).fill = support_fill
        if item["class_status"] == "New":
            details_sheet.cell(row=row_index, column=4).fill = new_class_fill
        details_sheet.cell(row=row_index, column=7).alignment = Alignment(
            horizontal="center",
            vertical="center",
        )

    details_sheet.column_dimensions["A"].width = 14
    details_sheet.column_dimensions["B"].width = 24
    details_sheet.column_dimensions["C"].width = 14
    details_sheet.column_dimensions["D"].width = 12
    details_sheet.column_dimensions["E"].width = 14
    details_sheet.column_dimensions["F"].width = 26
    details_sheet.column_dimensions["G"].width = 15
    details_sheet.column_dimensions["H"].width = 14

    summary_sheet = workbook.create_sheet("Summary")
    summary_sheet["A1"] = "Teacher Allocation Planning Summary"
    summary_sheet["A1"].font = Font(bold=True, size=14, color="0A4EA3")
    summary_sheet["A2"] = f"Branch: {branch_name}"
    summary_sheet["A3"] = f"Academic Year: {academic_year_name}"
    summary_sheet["A4"] = f"Generated At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    summary_metrics = [
        ("Total Required Hours", report_summary.get("total_required_hours", 0)),
        ("Expected Covered Hours", report_summary.get("total_allocated_hours", 0)),
        ("Uncovered Hours", report_summary.get("total_remaining_hours", 0)),
        ("Coverage %", f"{report_summary.get('coverage_percentage', 0)}%"),
        ("New Teachers Required", report_summary.get("total_new_teachers_required", 0)),
        (
            "Total Teachers Needed (Branch)",
            report_summary.get("total_teachers_needed_branch", 0),
        ),
    ]
    summary_sheet.append([])
    summary_sheet.append(["Metric", "Value"])
    metric_header_row = summary_sheet.max_row
    _apply_excel_header_style(summary_sheet, metric_header_row, 2)
    for metric_label, metric_value in summary_metrics:
        summary_sheet.append([metric_label, metric_value])

    subject_table_row = summary_sheet.max_row + 2
    summary_sheet.cell(row=subject_table_row, column=1, value="Subject Summary")
    summary_sheet.cell(row=subject_table_row, column=1).font = Font(
        bold=True,
        color="0A4EA3",
    )
    subject_headers = [
        "Subject",
        "Current Hours",
        "New Hours",
        "Total Required",
        "Covered",
        "Uncovered",
        "Extra Teachers Needed",
    ]
    summary_sheet.append(subject_headers)
    _apply_excel_header_style(summary_sheet, subject_table_row + 1, len(subject_headers))
    for row in report_subject_rows:
        summary_sheet.append(
            [
                row["subject_name"],
                row["required_current_hours"],
                row["required_new_hours"],
                row["required_hours"],
                row["allocated_hours"],
                row["remaining_hours"],
                row["additional_teachers_needed"],
            ]
        )
        row_index = summary_sheet.max_row
        uncovered_cell = summary_sheet.cell(row=row_index, column=6)
        extra_teachers_cell = summary_sheet.cell(row=row_index, column=7)
        if int(row["remaining_hours"]) > 0:
            uncovered_cell.fill = under_load_fill
        else:
            uncovered_cell.fill = full_load_fill
        if int(row["additional_teachers_needed"]) > 0:
            extra_teachers_cell.fill = under_load_fill
        else:
            extra_teachers_cell.fill = full_load_fill

    teacher_table_row = summary_sheet.max_row + 2
    summary_sheet.cell(row=teacher_table_row, column=1, value="Teacher Load Summary")
    summary_sheet.cell(row=teacher_table_row, column=1).font = Font(
        bold=True,
        color="0A4EA3",
    )
    teacher_headers = [
        "Teacher ID",
        "Teacher Name",
        "Expected Hours",
        "Primary Allocated",
        "Support Allocated",
        "Remaining Capacity",
    ]
    summary_sheet.append(teacher_headers)
    _apply_excel_header_style(summary_sheet, teacher_table_row + 1, len(teacher_headers))
    for row in report_teacher_rows:
        summary_sheet.append(
            [
                row["teacher_id"],
                row["teacher_name"],
                row["expected_allocated_hours"],
                row["primary_allocated_hours"],
                row["support_allocated_hours"],
                row["remaining_capacity_hours"],
            ]
        )
        row_index = summary_sheet.max_row
        expected_cell = summary_sheet.cell(row=row_index, column=3)
        remaining_cell = summary_sheet.cell(row=row_index, column=6)
        if int(row["expected_allocated_hours"]) >= REPORT_STANDARD_MAX_HOURS:
            expected_cell.fill = full_load_fill
            remaining_cell.fill = full_load_fill
        else:
            expected_cell.fill = under_load_fill
            remaining_cell.fill = under_load_fill

    unassigned_table_row = summary_sheet.max_row + 2
    summary_sheet.cell(
        row=unassigned_table_row,
        column=1,
        value="Unassigned Class Demand",
    )
    summary_sheet.cell(row=unassigned_table_row, column=1).font = Font(
        bold=True,
        color="0A4EA3",
    )
    unassigned_headers = [
        "Class",
        "Class Status",
        "Subject Code",
        "Subject Name",
        "Unassigned Hours",
    ]
    summary_sheet.append(unassigned_headers)
    _apply_excel_header_style(summary_sheet, unassigned_table_row + 1, len(unassigned_headers))
    if unassigned_rows:
        for row in unassigned_rows:
            summary_sheet.append(
                [
                    row["class_label"],
                    row["class_status"],
                    row["subject_code"],
                    row["subject_name"],
                    row["remaining_hours"],
                ]
            )
            row_index = summary_sheet.max_row
            summary_sheet.cell(row=row_index, column=5).fill = under_load_fill
    else:
        summary_sheet.append(
            [
                "All classes are fully covered by existing allocations.",
                "",
                "",
                "",
                0,
            ]
        )
        row_index = summary_sheet.max_row
        summary_sheet.cell(row=row_index, column=1).fill = full_load_fill
        summary_sheet.cell(row=row_index, column=5).fill = full_load_fill

    for column_key, width in {
        "A": 34,
        "B": 22,
        "C": 20,
        "D": 20,
        "E": 18,
        "F": 18,
        "G": 20,
    }.items():
        summary_sheet.column_dimensions[column_key].width = width

    for row_index in range(1, summary_sheet.max_row + 1):
        for col_index in range(1, 8):
            cell = summary_sheet.cell(row=row_index, column=col_index)
            if cell.value is None:
                continue
            if row_index <= 4:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
                if col_index in {2, 3, 4, 5, 6, 7}:
                    if not getattr(cell.fill, "fill_type", None):
                        cell.fill = neutral_fill

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


@app.middleware("http")
async def audit_logging_middleware(request: Request, call_next):
    started_at = time.perf_counter()
    status_code = 500
    error_name = ""

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception as exc:
        error_name = exc.__class__.__name__
        raise
    finally:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        _write_request_audit_log(
            request=request,
            status_code=status_code,
            duration_ms=duration_ms,
            error_name=error_name,
        )


def _build_login_context(
    db: Session,
    username: str = "",
    error: Optional[str] = None,
):
    active_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.is_active == True
    ).first()

    return {
        "username": username,
        "active_year_name": active_year.year_name if active_year else "Not configured",
        "error": error,
    }


def _render_login_page(
    request: Request,
    db: Session,
    username: str = "",
    error: Optional[str] = None,
    status_code: int = 200,
):
    context = _build_login_context(
        db=db,
        username=username,
        error=error,
    )
    context["request"] = request
    return templates.TemplateResponse(
        "index.html",
        context,
        status_code=status_code,
    )

# ---------------------------------------
# Include Routers
# ---------------------------------------
app.include_router(subjects.router)
app.include_router(users.router)
app.include_router(teachers.router)
app.include_router(planning.router)

# ---------------------------------------
# ROOT (Login Page)
# ---------------------------------------
@app.get("/", response_class=HTMLResponse)
def read_root(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = auth.get_current_user(request, db)
    if current_user:
        return RedirectResponse(
            url="/dashboard?info=already-logged-in",
            status_code=302
        )

    return _render_login_page(
        request=request,
        db=db,
    )

# ---------------------------------------
# LOGIN
# ---------------------------------------
@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    username = username.strip()
    request.state.audit_actor_user_id = username or "anonymous"
    request.state.audit_actor_username = username
    request.state.audit_actor_role = "Unauthenticated"
    request.state.audit_actor_branch_id = None
    user = auth.authenticate_user(db, username, password)

    if not user:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            error="Invalid User ID or password.",
            status_code=401
        )

    if not user.is_active:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            error="Your account is inactive. Please contact Admin.",
            status_code=403
        )

    can_all_branch_scope = auth.can_access_all_branches(user)
    active_branches = db.query(models.Branch).filter(
        models.Branch.status == True
    ).order_by(models.Branch.name.asc()).all()
    active_branch_map = {
        branch.id: branch for branch in active_branches
    }
    assigned_branch = active_branch_map.get(user.branch_id)

    if not assigned_branch and not can_all_branch_scope:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            error="Your assigned branch is inactive or not configured.",
            status_code=400
        )

    if not assigned_branch and can_all_branch_scope and not active_branches:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            error="No active branch is available in the system.",
            status_code=400
        )

    branch_scope_id = assigned_branch.id if assigned_branch else active_branches[0].id

    active_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.is_active == True
    ).first()
    if not active_year:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            error="No active academic year set by administrator.",
            status_code=400
        )

    response = RedirectResponse(url="/dashboard", status_code=302)
    request.state.audit_actor_user_id = user.user_id
    request.state.audit_actor_username = user.username or ""
    request.state.audit_actor_role = auth.normalize_role(user.role)
    request.state.audit_actor_branch_id = user.branch_id
    response.set_cookie(
        key="user_id",
        value=user.user_id,
        httponly=True,
        samesite="lax"
    )
    response.set_cookie(
        key="branch_id",
        value=str(branch_scope_id),
        httponly=True,
        samesite="lax"
    )
    response.set_cookie(
        key="academic_year_id",
        value=str(active_year.id),
        httponly=True,
        samesite="lax"
    )
    return response


# ---------------------------------------
# LOGOUT
# ---------------------------------------
@app.get("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("user_id")
    response.delete_cookie("branch_id")
    response.delete_cookie("academic_year_id")
    return response


# ---------------------------------------
# DEVELOPER: DOWNLOAD AUDIT LOG
# ---------------------------------------
@app.get("/admin/audit-log")
def download_audit_log(
    request: Request,
    format: str = Query(default="xlsx"),
    db: Session = Depends(get_db),
):
    current_user = auth.get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/", status_code=302)

    if not auth.can_manage_system_settings(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    audit_log_path = get_audit_log_path()
    if not audit_log_path.exists():
        return PlainTextResponse(
            "Audit log file has not been created yet.",
            status_code=404
        )

    download_format = str(format).strip().lower()
    if download_format not in {"xlsx", "csv", "raw"}:
        return PlainTextResponse(
            "Unsupported format. Use ?format=xlsx or ?format=csv or ?format=raw.",
            status_code=400
        )

    if download_format == "xlsx":
        try:
            payload = build_audit_xlsx_bytes(audit_log_path)
        except OSError:
            return PlainTextResponse(
                "Audit log file is temporarily unavailable. Please retry in a moment.",
                status_code=503
            )

        response = StreamingResponse(
            iter([payload]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response.headers["Content-Disposition"] = (
            f"attachment; filename={get_audit_xlsx_filename()}"
        )
        return response

    if download_format == "csv":
        response = StreamingResponse(
            iter_audit_csv_bytes(audit_log_path),
            media_type="text/csv",
        )
        response.headers["Content-Disposition"] = (
            f"attachment; filename={get_audit_csv_filename()}"
        )
        return response

    try:
        file_handle = open(audit_log_path, "rb")
    except OSError:
        return PlainTextResponse(
            "Audit log file is temporarily unavailable. Please retry in a moment.",
            status_code=503
        )

    def _iter_audit_file():
        with file_handle:
            while True:
                chunk = file_handle.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    response = StreamingResponse(
        _iter_audit_file(),
        media_type="text/plain",
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename={audit_log_path.name}"
    )
    return response


# ---------------------------------------
# ADMIN: SET CURRENT YEAR
# ---------------------------------------
@app.post("/admin/current-year")
def set_current_year(
    request: Request,
    academic_year_id: int = Form(...),
    db: Session = Depends(get_db)
):
    current_user = auth.get_current_user(request, db)

    if not current_user or not auth.can_manage_system_settings(current_user):
        return RedirectResponse(url="/", status_code=302)

    target_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == academic_year_id
    ).first()

    if not target_year:
        return RedirectResponse(url="/dashboard", status_code=302)

    db.query(models.AcademicYear).update(
        {models.AcademicYear.is_active: False},
        synchronize_session=False
    )
    target_year.is_active = True
    db.commit()

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="academic_year_id",
        value=str(target_year.id),
        httponly=True,
        samesite="lax"
    )
    return response


# ---------------------------------------
# DEVELOPER: OPEN NEW ACADEMIC YEAR
# ---------------------------------------
@app.post("/developer/open-academic-year")
def open_new_academic_year(
    request: Request,
    year_name: str = Form(...),
    db: Session = Depends(get_db)
):
    current_user = auth.get_current_user(request, db)
    if not current_user or not auth.can_manage_system_settings(current_user):
        return RedirectResponse(url="/", status_code=302)

    cleaned_year_name = year_name.strip()
    if not ACADEMIC_YEAR_NAME_PATTERN.match(cleaned_year_name):
        return RedirectResponse(url="/dashboard", status_code=302)

    existing_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.year_name == cleaned_year_name
    ).first()
    if existing_year:
        target_year = existing_year
        db.query(models.AcademicYear).update(
            {models.AcademicYear.is_active: False},
            synchronize_session=False
        )
        target_year.is_active = True
        db.commit()
    else:
        db.query(models.AcademicYear).update(
            {models.AcademicYear.is_active: False},
            synchronize_session=False
        )
        target_year = models.AcademicYear(
            year_name=cleaned_year_name,
            is_active=True
        )
        db.add(target_year)
        db.commit()
        db.refresh(target_year)

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="academic_year_id",
        value=str(target_year.id),
        httponly=True,
        samesite="lax"
    )
    return response


# ---------------------------------------
# SCOPE: SET CURRENT ACADEMIC YEAR
# ---------------------------------------
@app.post("/scope/academic-year")
def set_scope_academic_year(
    request: Request,
    academic_year_id: int = Form(...),
    db: Session = Depends(get_db)
):
    current_user = auth.get_current_user(request, db)

    if not current_user:
        return RedirectResponse(url="/", status_code=302)

    if not auth.can_manage_system_settings(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    target_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == academic_year_id
    ).first()
    if not target_year:
        return RedirectResponse(url="/dashboard", status_code=302)

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="academic_year_id",
        value=str(target_year.id),
        httponly=True,
        samesite="lax"
    )
    return response


# ---------------------------------------
# SCOPE: SET CURRENT BRANCH
# ---------------------------------------
@app.post("/scope/branch")
def set_scope_branch(
    request: Request,
    branch_id: int = Form(...),
    db: Session = Depends(get_db)
):
    current_user = auth.get_current_user(request, db)

    if not current_user:
        return RedirectResponse(url="/", status_code=302)

    if not auth.can_manage_system_settings(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    target_branch = db.query(models.Branch).filter(
        models.Branch.id == branch_id,
        models.Branch.status == True
    ).first()
    if not target_branch:
        return RedirectResponse(url="/dashboard", status_code=302)

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="branch_id",
        value=str(target_branch.id),
        httponly=True,
        samesite="lax"
    )
    return response


# ---------------------------------------
# DASHBOARD
# ---------------------------------------
@app.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db)
):
    user = auth.get_current_user(request, db)

    if not user:
        return RedirectResponse(url="/")

    scoped_branch_id = getattr(user, "scope_branch_id", user.branch_id)
    scoped_academic_year_id = getattr(
        user,
        "scope_academic_year_id",
        user.academic_year_id
    )

    branch = db.query(models.Branch).filter(
        models.Branch.id == scoped_branch_id
    ).first()

    academic_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == scoped_academic_year_id
    ).first()

    branch_name = branch.name if branch else "Not assigned"
    academic_year_name = (
        academic_year.year_name if academic_year else "Not assigned"
    )
    subjects_query = db.query(models.Subject).filter(
        models.Subject.branch_id == scoped_branch_id,
        models.Subject.academic_year_id == scoped_academic_year_id
    )
    teachers_query = db.query(models.Teacher).filter(
        models.Teacher.branch_id == scoped_branch_id,
        models.Teacher.academic_year_id == scoped_academic_year_id
    )
    users_query = db.query(models.User).filter(
        models.User.branch_id == scoped_branch_id,
        models.User.academic_year_id == scoped_academic_year_id
    )
    planning_sections_query = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == scoped_branch_id,
        models.PlanningSection.academic_year_id == scoped_academic_year_id,
    )
    subject_count = subjects_query.count()
    teacher_count = teachers_query.count()
    users_count = users_query.count()
    planning_sections = planning_sections_query.all()
    planning_total_sections = len(planning_sections)
    planning_current_sections_count = sum(
        1
        for section in planning_sections
        if str(section.class_status).strip().lower() == "current"
    )
    planning_new_sections_count = sum(
        1
        for section in planning_sections
        if str(section.class_status).strip().lower() == "new"
    )
    subjects_dashboard_rows = subjects_query.order_by(
        models.Subject.grade.asc(),
        models.Subject.subject_code.asc(),
    ).all()
    teachers_for_reporting = teachers_query.order_by(
        models.Teacher.id.asc()
    ).all()
    teachers_preview = teachers_query.order_by(
        models.Teacher.id.desc()
    ).limit(8).all()
    users_preview = users_query.order_by(
        models.User.id.desc()
    ).limit(8).all()
    subject_hours_by_grade = {}
    for subject in subjects_dashboard_rows:
        if subject.grade is None:
            continue
        grade_label = "KG" if int(subject.grade) == 0 else str(int(subject.grade))
        subject_hours_by_grade[grade_label] = (
            subject_hours_by_grade.get(grade_label, 0)
            + int(subject.weekly_hours or 0)
        )
    planning_total_allocated_hours = sum(
        subject_hours_by_grade.get(section.grade_level, 0)
        for section in planning_sections
    )
    reporting_context = _build_reporting_context(
        db=db,
        subjects=subjects_dashboard_rows,
        planning_sections=planning_sections,
        teachers=teachers_for_reporting,
    )
    all_years = db.query(models.AcademicYear).order_by(
        models.AcademicYear.year_name.desc()
    ).all()
    year_map = {
        year.id: year.year_name for year in all_years
    }
    branch_map = {
        branch_item.id: branch_item.name
        for branch_item in db.query(models.Branch).all()
    }
    available_scope_branches = db.query(models.Branch).filter(
        models.Branch.status == True
    ).order_by(models.Branch.name.asc()).all()
    can_manage_system_settings = auth.can_manage_system_settings(user)
    info_message = ""
    if request.query_params.get("info") == "already-logged-in":
        info_message = "You are already logged in."
    active_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.is_active == True
    ).first()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "branch_name": branch_name,
            "academic_year_name": academic_year_name,
            "subject_count": subject_count,
            "teacher_count": teacher_count,
            "users_count": users_count,
            "planning_total_sections": planning_total_sections,
            "planning_current_sections_count": planning_current_sections_count,
            "planning_new_sections_count": planning_new_sections_count,
            "planning_total_allocated_hours": planning_total_allocated_hours,
            "subjects_dashboard_rows": subjects_dashboard_rows,
            "teachers_preview": teachers_preview,
            "users_preview": users_preview,
            "report_summary": reporting_context["summary"],
            "report_subject_rows": reporting_context["subject_rows"],
            "report_gap_rows": reporting_context["gap_rows"],
            "report_teacher_rows": reporting_context["teacher_rows"],
            "report_grade_rows": reporting_context["grade_rows"],
            "all_years": all_years,
            "year_map": year_map,
            "branch_map": branch_map,
            "can_manage_system_settings": can_manage_system_settings,
            "info_message": info_message,
            "scoped_academic_year_id": scoped_academic_year_id,
            "available_scope_branches": available_scope_branches,
            "scoped_branch_id": scoped_branch_id,
            "active_year_id": active_year.id if active_year else None,
            "is_admin": auth.can_manage_users(user),
        }
    )


# ---------------------------------------
# REPORT EXPORT
# ---------------------------------------
@app.get("/reports/allocation-plan.xlsx")
def download_report_allocation_plan(
    request: Request,
    db: Session = Depends(get_db),
):
    user = auth.get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/")

    scoped_branch_id = getattr(user, "scope_branch_id", user.branch_id)
    scoped_academic_year_id = getattr(
        user,
        "scope_academic_year_id",
        user.academic_year_id,
    )

    branch = db.query(models.Branch).filter(
        models.Branch.id == scoped_branch_id
    ).first()
    academic_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == scoped_academic_year_id
    ).first()

    subjects_rows = db.query(models.Subject).filter(
        models.Subject.branch_id == scoped_branch_id,
        models.Subject.academic_year_id == scoped_academic_year_id,
    ).order_by(
        models.Subject.grade.asc(),
        models.Subject.subject_code.asc(),
    ).all()
    teachers_rows = db.query(models.Teacher).filter(
        models.Teacher.branch_id == scoped_branch_id,
        models.Teacher.academic_year_id == scoped_academic_year_id,
    ).order_by(models.Teacher.id.asc()).all()
    planning_sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == scoped_branch_id,
        models.PlanningSection.academic_year_id == scoped_academic_year_id,
    ).all()

    reporting_context = _build_reporting_context(
        db=db,
        subjects=subjects_rows,
        planning_sections=planning_sections,
        teachers=teachers_rows,
    )
    branch_name = branch.name if branch else "Not assigned"
    academic_year_name = (
        academic_year.year_name if academic_year else "Not assigned"
    )
    payload = _build_report_allocation_xlsx_bytes(
        branch_name=branch_name,
        academic_year_name=academic_year_name,
        subjects=subjects_rows,
        planning_sections=planning_sections,
        reporting_context=reporting_context,
    )
    file_name = _build_report_allocation_filename(
        branch_name=branch_name,
        academic_year_name=academic_year_name,
    )

    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


# ---------------------------------------
# Startup Schema Compatibility
# ---------------------------------------
def _ensure_users_table_columns():
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {
        col["name"] for col in inspector.get_columns("users")
    }

    with engine.begin() as connection:
        if "username" not in existing_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN username VARCHAR(50)")
            )
        if "position" not in existing_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN position VARCHAR(50)")
            )


def _ensure_teachers_table_columns():
    inspector = inspect(engine)
    if "teachers" not in inspector.get_table_names():
        return

    teacher_columns = inspector.get_columns("teachers")
    existing_columns = {
        col["name"] for col in teacher_columns
    }
    teacher_id_column = next(
        (col for col in teacher_columns if col.get("name") == "teacher_id"),
        None
    )
    teacher_id_length = (
        getattr(teacher_id_column.get("type"), "length", None)
        if teacher_id_column
        else None
    )
    db_dialect = engine.dialect.name

    with engine.begin() as connection:
        if "middle_name" not in existing_columns:
            connection.execute(
                text("ALTER TABLE teachers ADD COLUMN middle_name VARCHAR(100)")
            )
        if "extra_hours_allowed" not in existing_columns:
            connection.execute(
                text("ALTER TABLE teachers ADD COLUMN extra_hours_allowed BOOLEAN DEFAULT FALSE")
            )
        if "extra_hours_count" not in existing_columns:
            connection.execute(
                text("ALTER TABLE teachers ADD COLUMN extra_hours_count INTEGER DEFAULT 0")
            )
        if teacher_id_column and teacher_id_length and teacher_id_length < 10:
            if db_dialect == "postgresql":
                connection.execute(
                    text("ALTER TABLE teachers ALTER COLUMN teacher_id TYPE VARCHAR(10)")
                )
            elif db_dialect in {"mysql", "mariadb"}:
                connection.execute(
                    text("ALTER TABLE teachers MODIFY teacher_id VARCHAR(10)")
                )

        connection.execute(
            text("UPDATE teachers SET extra_hours_allowed = FALSE WHERE extra_hours_allowed IS NULL")
        )
        connection.execute(
            text("UPDATE teachers SET extra_hours_count = 0 WHERE extra_hours_count IS NULL")
        )


def _seed_teacher_subject_allocations():
    inspector = inspect(engine)
    if (
        "teachers" not in inspector.get_table_names()
        or "teacher_subject_allocations" not in inspector.get_table_names()
    ):
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO teacher_subject_allocations (teacher_id, subject_code)
                SELECT t.id, t.subject_code
                FROM teachers t
                WHERE t.subject_code IS NOT NULL
                  AND t.subject_code <> ''
                  AND NOT EXISTS (
                      SELECT 1
                      FROM teacher_subject_allocations a
                      WHERE a.teacher_id = t.id
                        AND a.subject_code = t.subject_code
                  )
                """
            )
        )


# ---------------------------------------
# Startup Initialization
# ---------------------------------------
@app.on_event("startup")
def setup_initial_data():

    _ensure_users_table_columns()
    _ensure_teachers_table_columns()
    _seed_teacher_subject_allocations()
    db = SessionLocal()
    admin_user_id = os.getenv("ADMIN_USER_ID", "2623252018")
    admin_username = os.getenv("ADMIN_USERNAME", "developer")
    admin_password = os.getenv("ADMIN_PASSWORD", "UnderProcess1984")
    admin_position = os.getenv("ADMIN_POSITION", "Developer")

    required_branch_names = [
        "Hamadania",
        "Manar",
        "Obhor",
        "Alshaati",
        "Fayha",
        "Najran",
        "Zahra",
        "Khamis Msheit",
        "Abha",
        "Rawda",
    ]
    existing_branches = db.query(Branch).all()
    branches_by_name = {
        str(item.name).strip().lower(): item
        for item in existing_branches
        if item.name
    }
    default_branch = None
    branch_changes = False

    for branch_name in required_branch_names:
        key = branch_name.lower()
        branch_row = branches_by_name.get(key)
        if not branch_row:
            branch_row = Branch(
                name=branch_name,
                location="Main Campus",
                status=True
            )
            db.add(branch_row)
            db.flush()
            branches_by_name[key] = branch_row
            branch_changes = True
        else:
            if not branch_row.status:
                branch_row.status = True
                branch_changes = True

        if branch_name == "Hamadania":
            default_branch = branch_row

    if branch_changes:
        db.commit()

    if not default_branch:
        default_branch = db.query(Branch).filter(
            Branch.name == "Hamadania"
        ).first()

    legacy_position_users = db.query(User).filter(
        User.position == "Education Excelency"
    ).all()
    if legacy_position_users:
        for user_row in legacy_position_users:
            user_row.position = "Education Excellence"
        db.commit()

    # Create Academic Year if not exists
    academic_year = db.query(AcademicYear).filter(
        AcademicYear.year_name == "2025-2026"
    ).first()

    if not academic_year:
        academic_year = AcademicYear(
            year_name="2025-2026",
            is_active=True
        )
        db.add(academic_year)
        db.commit()
        db.refresh(academic_year)
    else:
        active_year = db.query(AcademicYear).filter(
            AcademicYear.is_active == True
        ).first()
        if not active_year:
            academic_year.is_active = True
            db.commit()

    # Create Admin User if not exists
    existing_user = db.query(User).filter(
        User.user_id == admin_user_id
    ).first()

    if not existing_user:
        admin_user = User(
            user_id=admin_user_id,
            username=admin_username,
            first_name="mohamad",
            last_name="El Ghoche",
            position=admin_position,
            password=get_password_hash(admin_password),
            role=auth.ROLE_DEVELOPER,
            branch_id=default_branch.id if default_branch else None,
            academic_year_id=academic_year.id,
            is_active=True
        )
        db.add(admin_user)
        db.commit()
    else:
        updated = False

        if not auth.verify_password(admin_password, existing_user.password):
            existing_user.password = get_password_hash(admin_password)
            updated = True

        if not existing_user.username:
            existing_user.username = admin_username
            updated = True

        if not existing_user.position:
            existing_user.position = admin_position
            updated = True

        if not existing_user.role:
            existing_user.role = auth.ROLE_DEVELOPER
            updated = True

        if not existing_user.branch_id and default_branch:
            existing_user.branch_id = default_branch.id
            updated = True

        if not existing_user.academic_year_id:
            existing_user.academic_year_id = academic_year.id
            updated = True

        if not existing_user.is_active:
            existing_user.is_active = True
            updated = True

        if updated:
            db.commit()

    db.close()
