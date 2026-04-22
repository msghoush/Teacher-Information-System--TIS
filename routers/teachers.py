from collections import defaultdict
import re
from types import SimpleNamespace

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import models
from dependencies import get_db
from auth import get_current_user
from homeroom_defaults import (
    get_homeroom_bundle_subject_labels,
    is_default_homeroom_subject,
    is_homeroom_bundle_subject,
)
from teacher_capacity import (
    build_capacity_breakdown,
    get_teacher_international_capacity_hours,
    get_teacher_national_section_hours,
    get_teacher_total_capacity_hours,
)
from teacher_qualifications import (
    build_legacy_qualification_snapshot,
    build_qualification_summary,
    get_qualification_labels,
    get_qualification_option_groups,
    get_qualification_options_for_json,
    get_qualification_lookup,
    get_subject_alignment_keyword_groups_for_json,
    get_subject_qualification_alignment,
    has_specialization_qualification,
    infer_qualification_keys_from_legacy_text,
    normalize_qualification_keys,
)
from ui_shell import build_shell_context
from year_copy import get_copy_year_choices, get_academic_year
from subject_colors import build_subject_theme, resolve_subject_color

router = APIRouter(prefix="/teachers", tags=["Teachers"])
templates = Jinja2Templates(directory="templates")

TEACHER_ID_PATTERN = re.compile(r"^\d{1,10}$")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z\s'\-]*$")
STANDARD_MAX_HOURS = 24
SECTION_ASSIGNMENT_SEPARATOR = "::"


def _get_scope_ids(current_user):
    branch_id = getattr(current_user, "scope_branch_id", current_user.branch_id)
    academic_year_id = getattr(
        current_user,
        "scope_academic_year_id",
        current_user.academic_year_id
    )
    return branch_id, academic_year_id


def _normalize_spaces(value: str) -> str:
    return " ".join(str(value).split())


def _normalize_teacher_id(value: str) -> str:
    return _normalize_spaces(value).strip()


def _normalize_name(value: str) -> str:
    cleaned = _normalize_spaces(value).strip()
    if not cleaned:
        return ""
    return " ".join(part.capitalize() for part in cleaned.split(" "))


def _normalize_subject_codes(values):
    cleaned_codes = []
    seen_codes = set()
    for raw_value in values or []:
        code = _normalize_spaces(raw_value).strip().upper()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        cleaned_codes.append(code)
    return cleaned_codes


def _collect_subject_qualification_alignment_issues(
    normalized_subject_codes,
    subject_map,
    qualification_keys,
    qualification_lookup=None,
):
    issues = {
        "errors": [],
        "incompatible_codes": set(),
        "incompatible_details": [],
    }

    if not qualification_keys:
        issues["errors"].append(
            "Select at least one saved qualification for this teacher."
        )
        return issues

    if not has_specialization_qualification(
        qualification_keys,
        qualification_lookup=qualification_lookup,
    ):
        issues["errors"].append(
            "Select at least one major or teaching specialization so subject compatibility can be validated."
        )
        return issues

    for subject_code in normalized_subject_codes:
        subject = subject_map.get(subject_code)
        if not subject:
            continue

        alignment = get_subject_qualification_alignment(
            subject_name=subject.subject_name or "",
            fallback_code=subject.subject_code or subject_code,
            qualification_keys=qualification_keys,
            qualification_lookup=qualification_lookup,
        )
        if alignment["recognized_subject"] and alignment["status"] != "match":
            issues["incompatible_codes"].add(subject_code)
            issues["incompatible_details"].append(
                f"{subject_code} ({subject.subject_name or 'Unnamed Subject'})"
            )

    return issues


def _parse_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _is_extra_hours_allowed(value) -> bool:
    cleaned = str(value).strip().lower()
    return cleaned in {"1", "true", "yes", "on"}


def _teaches_national_section(value) -> bool:
    return _is_extra_hours_allowed(value)


def _get_teacher_subject_override_map(db: Session, teacher_ids):
    teacher_ids = [teacher_id for teacher_id in teacher_ids if teacher_id]
    override_map = defaultdict(list)
    if not teacher_ids:
        return override_map

    rows = (
        db.query(models.TeacherSubjectAllocation)
        .filter(models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids))
        .order_by(
            models.TeacherSubjectAllocation.teacher_id.asc(),
            models.TeacherSubjectAllocation.subject_code.asc(),
        )
        .all()
    )
    for row in rows:
        if row.compatibility_override and row.subject_code:
            override_map[row.teacher_id].append(row.subject_code)
    return override_map


def _get_subject_choices(db: Session, branch_id: int, academic_year_id: int):
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.subject_code.asc()).all()
    choices = []
    for subject in subjects:
        if not subject.subject_code:
            continue
        subject_color = resolve_subject_color(
            subject.subject_code,
            getattr(subject, "color", ""),
            subject_name=subject.subject_name,
        )
        theme = build_subject_theme(subject_color)
        choices.append(
            {
                "subject_code": subject.subject_code,
                "subject_name": subject.subject_name or "",
                "weekly_hours": subject.weekly_hours or 0,
                "grade": subject.grade,
                "color": subject_color,
                "color_soft": theme["soft"],
                "color_text": theme["text"],
                "color_border": theme["border"],
            }
        )
    return choices


def _build_teacher_display_name(teacher) -> str:
    name_parts = [teacher.first_name]
    if teacher.middle_name:
        name_parts.append(teacher.middle_name)
    name_parts.append(teacher.last_name)
    full_name = " ".join(part for part in name_parts if part).strip()
    return full_name if full_name else f"Teacher #{teacher.id}"


def _subject_grade_label(subject_grade) -> str:
    parsed_grade = _parse_int(subject_grade)
    if parsed_grade is None:
        return ""
    return "KG" if parsed_grade == 0 else str(parsed_grade)


def _format_section_label(section) -> str:
    if not section:
        return "-"
    grade_value = str(section.grade_level or "").strip().upper()
    if grade_value == "KG":
        return f"KG-{section.section_name}"
    return f"Grade {grade_value}-{section.section_name}"


def _normalize_grade_label(value) -> str:
    grade_value = str(value or "").strip().upper()
    if grade_value in {"K", "KG"}:
        return "KG"
    parsed_grade = _parse_int(grade_value)
    if parsed_grade is None:
        return grade_value
    return "KG" if parsed_grade == 0 else str(parsed_grade)


def _build_subject_theme_payload(
    subject_code: str,
    subject_name: str = "",
    stored_color: str | None = None,
):
    subject_color = resolve_subject_color(
        subject_code,
        stored_color,
        subject_name=subject_name,
    )
    theme = build_subject_theme(subject_color)
    return {
        "subject_color": subject_color,
        "subject_color_soft": theme["soft"],
        "subject_color_border": theme["border"],
        "subject_color_text": theme["text"],
    }


def _build_teacher_subject_display_entries(
    subject_code: str,
    subject_name: str,
    subject_grade: str,
    subject_hours: int,
    compatibility_override: bool = False,
    stored_color: str | None = None,
):
    subject_theme = _build_subject_theme_payload(
        subject_code,
        subject_name=subject_name,
        stored_color=stored_color,
    )
    bundle_subject_labels = get_homeroom_bundle_subject_labels(
        subject_code=subject_code,
        subject_name=subject_name,
        weekly_hours=subject_hours,
        grade_label=subject_grade,
    )
    override_suffix = " [Admin Override]" if compatibility_override else ""
    if bundle_subject_labels:
        return [
            {
                **subject_theme,
                "detail_label": (
                    f"{subject_code} - {bundle_subject} "
                    f"(included in {subject_name}, Grade {subject_grade}, "
                    f"{subject_hours}h homeroom bundle){override_suffix}"
                ),
                "preview_label": bundle_subject,
            }
            for bundle_subject in bundle_subject_labels
        ]

    return [
        {
            **subject_theme,
            "detail_label": (
                f"{subject_code} - {subject_name} "
                f"(Grade {subject_grade}, {subject_hours}h){override_suffix}"
            ),
            "preview_label": subject_code,
        }
    ]


def _format_section_assignment_value(subject_code: str, planning_section_id: int) -> str:
    return f"{subject_code}{SECTION_ASSIGNMENT_SEPARATOR}{planning_section_id}"


def _parse_section_assignment_values(values):
    assignment_map = {}
    normalized_values = []
    invalid_values = []
    seen_values = set()

    for raw_value in values or []:
        text = str(raw_value or "").strip()
        if not text:
            continue
        if SECTION_ASSIGNMENT_SEPARATOR not in text:
            invalid_values.append(text)
            continue

        subject_code_raw, section_id_raw = text.split(SECTION_ASSIGNMENT_SEPARATOR, 1)
        subject_code = _normalize_spaces(subject_code_raw).strip().upper()
        planning_section_id = _parse_int(section_id_raw)
        if not subject_code or planning_section_id is None:
            invalid_values.append(text)
            continue

        normalized_value = _format_section_assignment_value(
            subject_code,
            planning_section_id,
        )
        if normalized_value in seen_values:
            continue
        seen_values.add(normalized_value)
        normalized_values.append(normalized_value)
        assignment_map.setdefault(subject_code, set()).add(planning_section_id)

    return assignment_map, normalized_values, invalid_values


def _get_section_options_by_subject(
    db: Session,
    branch_id: int,
    academic_year_id: int,
    current_teacher_id: int | None = None,
):
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.subject_code.asc()).all()
    planning_sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).order_by(
        models.PlanningSection.grade_level.asc(),
        models.PlanningSection.section_name.asc(),
        models.PlanningSection.id.asc(),
    ).all()

    planning_sections_by_id = {
        section.id: section
        for section in planning_sections
        if getattr(section, "id", None)
    }
    planning_sections_by_grade = {}
    for section in planning_sections:
        grade_label = str(section.grade_level or "").strip().upper()
        if not grade_label:
            continue
        planning_sections_by_grade.setdefault(grade_label, []).append(section)

    scoped_teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).all()
    teacher_names_by_id = {
        teacher.id: _build_teacher_display_name(teacher)
        for teacher in scoped_teachers
        if getattr(teacher, "id", None)
    }

    planning_section_ids = list(planning_sections_by_id.keys())
    if planning_section_ids:
        section_assignments = db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.planning_section_id.in_(planning_section_ids)
        ).all()
    else:
        section_assignments = []

    occupied_assignments = {}
    for assignment in section_assignments:
        occupied_assignments[
            (assignment.subject_code, assignment.planning_section_id)
        ] = assignment.teacher_id

    section_options_by_subject = {}
    for subject in subjects:
        if not subject.subject_code:
            continue
        grade_label = _subject_grade_label(subject.grade)
        subject_options = []
        for section in planning_sections_by_grade.get(grade_label, []):
            occupying_teacher_id = occupied_assignments.get(
                (subject.subject_code, section.id)
            )
            assigned_to_other = (
                occupying_teacher_id is not None
                and occupying_teacher_id != current_teacher_id
            )
            subject_options.append(
                {
                    "section_id": section.id,
                    "label": (
                        f"{_format_section_label(section)}"
                        f" ({section.class_status})"
                    ),
                    "teacher_id": occupying_teacher_id,
                    "teacher_name": teacher_names_by_id.get(occupying_teacher_id, ""),
                    "is_available": not assigned_to_other,
                }
            )
        section_options_by_subject[subject.subject_code] = subject_options

    return {
        "section_options_by_subject": section_options_by_subject,
        "planning_sections_by_id": planning_sections_by_id,
        "occupied_assignments": occupied_assignments,
    }


def _get_teacher_section_assignment_values(db: Session, teacher_id: int):
    rows = db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.teacher_id == teacher_id
    ).order_by(
        models.TeacherSectionAssignment.subject_code.asc(),
        models.TeacherSectionAssignment.planning_section_id.asc(),
    ).all()
    return [
        _format_section_assignment_value(
            row.subject_code,
            row.planning_section_id,
        )
        for row in rows
        if row.subject_code and row.planning_section_id is not None
    ]


def _build_teacher_qualification_payload(
    teacher,
    qualification_keys,
    qualification_lookup=None,
):
    normalized_keys = normalize_qualification_keys(
        qualification_keys,
        qualification_lookup=qualification_lookup,
    )
    if not normalized_keys:
        normalized_keys = infer_qualification_keys_from_legacy_text(
            getattr(teacher, "degree_major", "") or "",
            qualification_lookup=qualification_lookup,
        )

    return {
        "keys": normalized_keys,
        "labels": get_qualification_labels(
            normalized_keys,
            qualification_lookup=qualification_lookup,
        ),
        "summary": build_qualification_summary(
            normalized_keys,
            fallback_text=getattr(teacher, "degree_major", "") or "",
            max_items=3,
            qualification_lookup=qualification_lookup,
        ),
        "snapshot": build_legacy_qualification_snapshot(
            normalized_keys,
            qualification_lookup=qualification_lookup,
        ),
    }


def _get_teacher_qualification_map(db: Session, teachers):
    teacher_ids = [
        teacher.id
        for teacher in teachers
        if getattr(teacher, "id", None)
    ]
    qualification_keys_by_teacher = defaultdict(list)

    if teacher_ids:
        rows = (
            db.query(models.TeacherQualificationSelection)
            .filter(models.TeacherQualificationSelection.teacher_id.in_(teacher_ids))
            .order_by(
                models.TeacherQualificationSelection.teacher_id.asc(),
                models.TeacherQualificationSelection.qualification_key.asc(),
            )
            .all()
        )
    else:
        rows = []

    for row in rows:
        if row.qualification_key:
            qualification_keys_by_teacher[row.teacher_id].append(
                row.qualification_key
            )

    qualification_lookup = get_qualification_lookup(db)
    return {
        teacher.id: _build_teacher_qualification_payload(
            teacher,
            qualification_keys_by_teacher.get(teacher.id, []),
            qualification_lookup=qualification_lookup,
        )
        for teacher in teachers
        if getattr(teacher, "id", None)
    }


def _validate_subject_qualification_alignment(
    normalized_subject_codes,
    subject_map,
    qualification_keys,
    override_subject_codes=None,
    qualification_lookup=None,
):
    override_subject_code_set = set(
        _normalize_subject_codes(override_subject_codes or [])
    )
    issues = _collect_subject_qualification_alignment_issues(
        normalized_subject_codes=normalized_subject_codes,
        subject_map=subject_map,
        qualification_keys=qualification_keys,
        qualification_lookup=qualification_lookup,
    )
    errors = list(issues["errors"])
    incompatible_codes = set(issues["incompatible_codes"])
    incompatible_details_by_code = {
        detail.split(" ", 1)[0]: detail
        for detail in issues["incompatible_details"]
    }
    unresolved_details = [
        incompatible_details_by_code[subject_code]
        for subject_code in sorted(incompatible_codes)
        if subject_code not in override_subject_code_set
    ]

    if unresolved_details:
        errors.append(
            "The selected qualifications do not match these subjects: "
            + ", ".join(unresolved_details)
            + ". Add matching majors/specializations, enable Admin Override for those subjects, or remove them."
        )

    effective_override_subject_codes = sorted(
        incompatible_codes & override_subject_code_set
    )
    return errors, effective_override_subject_codes


def _get_teacher_allocation_map(db: Session, teachers, branch_id: int, academic_year_id: int):
    teacher_ids = [teacher.id for teacher in teachers if getattr(teacher, "id", None)]
    if not teacher_ids:
        return {}

    allocations = db.query(models.TeacherSubjectAllocation).filter(
        models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids)
    ).order_by(
        models.TeacherSubjectAllocation.teacher_id.asc(),
        models.TeacherSubjectAllocation.subject_code.asc(),
    ).all()

    section_assignments = db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.teacher_id.in_(teacher_ids)
    ).order_by(
        models.TeacherSectionAssignment.teacher_id.asc(),
        models.TeacherSectionAssignment.subject_code.asc(),
        models.TeacherSectionAssignment.planning_section_id.asc(),
    ).all()

    scoped_subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).all()
    subjects_by_code = {
        subject.subject_code: subject
        for subject in scoped_subjects
        if subject.subject_code
    }
    subjects_by_grade = defaultdict(list)
    for subject in scoped_subjects:
        grade_label = _subject_grade_label(subject.grade)
        if not grade_label:
            continue
        subjects_by_grade[grade_label].append(subject)

    allocation_map = {
        teacher.id: {
            "subject_codes": [],
            "override_subject_codes": [],
            "subject_items": [],
            "subject_preview_items": [],
            "subject_count": 0,
            "subject_hidden_count": 0,
            "allocated_hours": 0,
            "teaching_load_labels": [],
            "teaching_load_preview_labels": [],
            "teaching_load_count": 0,
            "teaching_load_hidden_count": 0,
            "section_assignment_count": 0,
            "homeroom_coverage_labels": [],
            "homeroom_preview_labels": [],
            "homeroom_sections_count": 0,
            "homeroom_subject_count": 0,
            "homeroom_hidden_count": 0,
            "required_hours": get_teacher_international_capacity_hours(
                teacher,
                default_max_hours=STANDARD_MAX_HOURS,
            ),
            "total_capacity_hours": get_teacher_total_capacity_hours(
                teacher,
                default_max_hours=STANDARD_MAX_HOURS,
            ),
            "national_section_hours": get_teacher_national_section_hours(
                teacher,
                default_max_hours=STANDARD_MAX_HOURS,
            ),
            "international_capacity_hours": get_teacher_international_capacity_hours(
                teacher,
                default_max_hours=STANDARD_MAX_HOURS,
            ),
            "matches_max_hours": False,
            "within_capacity": False,
        }
        for teacher in teachers
    }

    for allocation in allocations:
        teacher_data = allocation_map.get(allocation.teacher_id)
        if not teacher_data:
            continue
        subject = subjects_by_code.get(allocation.subject_code)
        subject_name = "Unnamed Subject"
        subject_hours = 0
        subject_grade = "-"
        if subject and subject.weekly_hours is not None:
            subject_hours = int(subject.weekly_hours)
        if subject and subject.subject_name:
            subject_name = subject.subject_name
        if subject and subject.grade is not None:
            subject_grade = str(subject.grade)
        teacher_data["subject_codes"].append(allocation.subject_code)
        subject_entries = _build_teacher_subject_display_entries(
            subject_code=allocation.subject_code,
            subject_name=subject_name,
            subject_grade=subject_grade,
            subject_hours=subject_hours,
            compatibility_override=getattr(
                allocation,
                "compatibility_override",
                False,
            ),
            stored_color=getattr(subject, "color", ""),
        )
        if allocation.compatibility_override:
            teacher_data["override_subject_codes"].append(allocation.subject_code)
        teacher_data["subject_items"].extend(subject_entries)
        teacher_data["subject_preview_items"].extend(subject_entries)

    planning_section_ids = sorted(
        {
            assignment.planning_section_id
            for assignment in section_assignments
            if assignment.planning_section_id
        }
        | {
            section.id
            for section in db.query(models.PlanningSection).filter(
                models.PlanningSection.branch_id == branch_id,
                models.PlanningSection.academic_year_id == academic_year_id,
                models.PlanningSection.homeroom_teacher_id.in_(teacher_ids),
            ).all()
            if getattr(section, "id", None)
        }
    )
    planning_sections_by_id = {}
    if planning_section_ids:
        planning_sections_by_id = {
            section.id: section
            for section in db.query(models.PlanningSection).filter(
                models.PlanningSection.id.in_(planning_section_ids),
                models.PlanningSection.branch_id == branch_id,
                models.PlanningSection.academic_year_id == academic_year_id,
            ).all()
        }

    teaching_load_map = {}
    for assignment in section_assignments:
        teacher_data = allocation_map.get(assignment.teacher_id)
        if not teacher_data:
            continue
        subject = subjects_by_code.get(assignment.subject_code)
        if not subject:
            continue
        subject_hours = int(subject.weekly_hours or 0)
        section = planning_sections_by_id.get(assignment.planning_section_id)
        section_label = _format_section_label(section)
        subject_key = (assignment.teacher_id, assignment.subject_code)
        subject_entry = teaching_load_map.setdefault(
            subject_key,
            {
                "subject_code": assignment.subject_code,
                "subject_name": subject.subject_name or "Unnamed Subject",
                "grade_label": _subject_grade_label(subject.grade),
                "hours": 0,
                "sections": [],
            },
        )
        subject_entry["hours"] += subject_hours
        subject_entry["sections"].append(section_label)
        teacher_data["allocated_hours"] += subject_hours

    explicit_assignment_map = {
        (
            assignment.planning_section_id,
            str(assignment.subject_code or "").strip().upper(),
        ): assignment.teacher_id
        for assignment in section_assignments
        if assignment.planning_section_id and assignment.subject_code
    }
    homeroom_sections_seen_by_teacher = defaultdict(set)

    for section in planning_sections_by_id.values():
        homeroom_teacher_id = getattr(section, "homeroom_teacher_id", None)
        teacher_data = allocation_map.get(homeroom_teacher_id)
        if not teacher_data:
            continue

        grade_label = _normalize_grade_label(section.grade_level)
        if not grade_label:
            continue

        bundle_subjects = []
        default_subjects = []
        for subject in subjects_by_grade.get(grade_label, []):
            subject_code = str(subject.subject_code or "").strip().upper()
            if not subject_code:
                continue

            explicit_teacher_id = explicit_assignment_map.get((section.id, subject_code))
            if explicit_teacher_id not in {None, homeroom_teacher_id}:
                continue

            subject_item = {
                "subject": subject,
                "subject_code": subject_code,
                "subject_name": subject.subject_name or "Unnamed Subject",
                "weekly_hours": int(subject.weekly_hours or 0),
                "is_explicit_assignment": explicit_teacher_id == homeroom_teacher_id,
            }

            if is_homeroom_bundle_subject(
                subject_code=subject_code,
                subject_name=subject_item["subject_name"],
                weekly_hours=subject_item["weekly_hours"],
                grade_label=grade_label,
            ):
                bundle_subjects.append(subject_item)
                continue

            if is_default_homeroom_subject(
                grade_label,
                subject_name=subject_item["subject_name"],
                subject_code=subject_code,
            ):
                default_subjects.append(subject_item)

        coverage_subjects = bundle_subjects or default_subjects
        if not coverage_subjects:
            continue

        section_label = _format_section_label(section)
        if section_label not in homeroom_sections_seen_by_teacher[homeroom_teacher_id]:
            homeroom_sections_seen_by_teacher[homeroom_teacher_id].add(section_label)
            teacher_data["homeroom_sections_count"] += 1
            teacher_data["homeroom_preview_labels"].append(section_label)

        if bundle_subjects:
            bundle_subject = bundle_subjects[0]
            included_subject_labels = list(
                get_homeroom_bundle_subject_labels(
                    subject_code=bundle_subject["subject_code"],
                    subject_name=bundle_subject["subject_name"],
                    weekly_hours=bundle_subject["weekly_hours"],
                    grade_label=grade_label,
                )
            )
            teacher_data["homeroom_subject_count"] += len(included_subject_labels)
            teacher_data["homeroom_coverage_labels"].append(
                f"{section_label}: {bundle_subject['subject_code']} - "
                f"{bundle_subject['subject_name']} ({bundle_subject['weekly_hours']}h) "
                f"| Includes {', '.join(included_subject_labels)}"
            )
            if not bundle_subject["is_explicit_assignment"]:
                teacher_data["allocated_hours"] += bundle_subject["weekly_hours"]
            continue

        homeroom_subject_names = []
        default_subject_hours = 0
        for subject_item in coverage_subjects:
            homeroom_subject_names.append(subject_item["subject_name"])
            teacher_data["homeroom_subject_count"] += 1
            default_subject_hours += subject_item["weekly_hours"]
            if not subject_item["is_explicit_assignment"]:
                teacher_data["allocated_hours"] += subject_item["weekly_hours"]

        teacher_data["homeroom_coverage_labels"].append(
            f"{section_label}: Homeroom default covers "
            f"{', '.join(homeroom_subject_names)} ({default_subject_hours}h)"
        )

    for teacher in teachers:
        teacher_data = allocation_map.get(teacher.id)
        if not teacher_data:
            continue
        teacher_data["subject_count"] = len(teacher_data["subject_items"])
        teacher_data["subject_preview_items"] = teacher_data["subject_preview_items"][:2]
        teacher_data["subject_hidden_count"] = max(
            teacher_data["subject_count"] - len(teacher_data["subject_preview_items"]),
            0,
        )
        teacher_entries = [
            data
            for (teacher_id, _), data in teaching_load_map.items()
            if teacher_id == teacher.id
        ]
        teacher_entries.sort(
            key=lambda item: (item["subject_code"], item["subject_name"])
        )
        teacher_data["teaching_load_labels"] = []
        for entry in teacher_entries:
            bundle_subject_labels = list(
                get_homeroom_bundle_subject_labels(
                    entry["subject_code"],
                    entry["subject_name"],
                    entry["hours"],
                    entry.get("grade_label"),
                )
            )
            bundle_prefix = (
                f"Includes {', '.join(bundle_subject_labels)} | "
                if bundle_subject_labels
                else ""
            )
            teacher_data["teaching_load_labels"].append(
                f"{entry['subject_code']} - {entry['subject_name']} | "
                f"{bundle_prefix}Sections: {', '.join(entry['sections'])} | "
                f"{entry['hours']}h"
            )
        teacher_data["teaching_load_preview_labels"] = [
            f"{entry['subject_code']} x{len(entry['sections'])}"
            for entry in teacher_entries[:2]
        ]
        teacher_data["teaching_load_count"] = len(teacher_entries)
        teacher_data["teaching_load_hidden_count"] = max(
            teacher_data["teaching_load_count"]
            - len(teacher_data["teaching_load_preview_labels"]),
            0,
        )
        teacher_data["section_assignment_count"] = sum(
            len(entry["sections"]) for entry in teacher_entries
        )
        teacher_data["homeroom_preview_labels"] = teacher_data["homeroom_preview_labels"][:2]
        teacher_data["homeroom_hidden_count"] = max(
            teacher_data["homeroom_sections_count"]
            - len(teacher_data["homeroom_preview_labels"]),
            0,
        )

    for teacher in teachers:
        teacher_data = allocation_map.get(teacher.id, {})
        allocated_hours = teacher_data.get("allocated_hours", 0)
        required_hours = teacher_data.get("required_hours", 0)
        is_within_capacity = allocated_hours <= required_hours
        teacher_data["within_capacity"] = is_within_capacity
        # Keep legacy key name for template compatibility.
        teacher_data["matches_max_hours"] = is_within_capacity

    return allocation_map


def _render_teachers_page(
    request: Request,
    db: Session,
    current_user,
    error: str = "",
    success: str = "",
    detail_errors=None,
    form_data=None,
    selected_subject_codes=None,
    selected_section_assignment_values=None,
    selected_qualification_keys=None,
    selected_override_subject_codes=None,
):
    branch_id, academic_year_id = _get_scope_ids(current_user)
    can_modify = auth.can_modify_data(current_user)
    can_edit = auth.can_edit_data(current_user)
    can_delete = auth.can_delete_data(current_user)
    can_copy_year_data = auth.is_developer(current_user)
    copy_year_choices = (
        get_copy_year_choices(db, academic_year_id)
        if can_copy_year_data
        else []
    )

    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id
    ).order_by(models.Teacher.id.desc()).all()
    teacher_qualification_map = _get_teacher_qualification_map(db, teachers)
    teacher_allocations = _get_teacher_allocation_map(
        db,
        teachers,
        branch_id,
        academic_year_id,
    )
    section_assignment_support = _get_section_options_by_subject(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    normalized_form_data = {
        "teacher_id": "",
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "qualification_keys": [],
        "max_hours": "24",
        "extra_hours_allowed": False,
        "extra_hours_count": "",
        "teaches_national_section": False,
        "national_section_hours": "1",
    }
    if form_data:
        normalized_form_data.update(form_data)

    qualification_options = get_qualification_options_for_json(db)
    qualification_option_groups = get_qualification_option_groups(db)

    return templates.TemplateResponse(
        request,
        "teachers.html",
        {
            "request": request,
            "teachers": teachers,
            "teacher_qualification_map": teacher_qualification_map,
            "subject_choices": _get_subject_choices(db, branch_id, academic_year_id),
            "qualification_option_groups": qualification_option_groups,
            "qualification_options": qualification_options,
            "subject_alignment_keyword_groups": get_subject_alignment_keyword_groups_for_json(),
            "section_options_by_subject": section_assignment_support["section_options_by_subject"],
            "teacher_allocations": teacher_allocations,
            "can_modify": can_modify,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "can_copy_year_data": can_copy_year_data,
            "error": error,
            "success": success,
            "detail_errors": detail_errors or [],
            "form_data": normalized_form_data,
            "selected_subject_codes": selected_subject_codes or [],
            "selected_section_assignment_values": selected_section_assignment_values or [],
            "selected_qualification_keys": selected_qualification_keys
            if selected_qualification_keys is not None
            else normalized_form_data.get("qualification_keys", []),
            "selected_override_subject_codes": selected_override_subject_codes
            if selected_override_subject_codes is not None
            else normalized_form_data.get("override_subject_codes", []),
            "copy_year_choices": copy_year_choices,
            "user": current_user,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="teachers",
            ),
        },
    )


def _render_edit_teacher_page(
    request: Request,
    db: Session,
    current_user,
    teacher,
    error: str = "",
    assigned_subject_codes=None,
    selected_section_assignment_values=None,
    selected_qualification_keys=None,
    selected_override_subject_codes=None,
    status_code: int = 200,
):
    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher_qualification_map = _get_teacher_qualification_map(db, [teacher])
    section_assignment_support = _get_section_options_by_subject(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        current_teacher_id=teacher.id,
    )

    if assigned_subject_codes is None:
        assigned_subject_codes = [
            row.subject_code
            for row in db.query(models.TeacherSubjectAllocation).filter(
                models.TeacherSubjectAllocation.teacher_id == teacher.id
            ).order_by(models.TeacherSubjectAllocation.subject_code.asc()).all()
            if row.subject_code
        ]

    if selected_section_assignment_values is None:
        selected_section_assignment_values = _get_teacher_section_assignment_values(
            db,
            teacher.id,
        )

    if selected_qualification_keys is None:
        selected_qualification_keys = (
            teacher_qualification_map.get(getattr(teacher, "id", None), {}).get("keys", [])
        )
    if selected_override_subject_codes is None:
        selected_override_subject_codes = _get_teacher_subject_override_map(
            db,
            [getattr(teacher, "id", None)],
        ).get(getattr(teacher, "id", None), [])

    qualification_options = get_qualification_options_for_json(db)
    qualification_option_groups = get_qualification_option_groups(db)

    return templates.TemplateResponse(
        request,
        "edit_teacher.html",
        {
            "request": request,
            "teacher": teacher,
            "teacher_qualification_map": teacher_qualification_map,
            "subject_choices": _get_subject_choices(db, branch_id, academic_year_id),
            "qualification_option_groups": qualification_option_groups,
            "qualification_options": qualification_options,
            "subject_alignment_keyword_groups": get_subject_alignment_keyword_groups_for_json(),
            "section_options_by_subject": section_assignment_support["section_options_by_subject"],
            "assigned_subject_codes": assigned_subject_codes,
            "selected_section_assignment_values": selected_section_assignment_values,
            "selected_qualification_keys": selected_qualification_keys,
            "selected_override_subject_codes": selected_override_subject_codes,
            "error": error,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="teachers",
                title="Edit Teacher",
                eyebrow="Staffing Desk",
                intro="Adjust eligible subjects, section teaching load, workload limits, and extra-hours settings without leaving the unified layout.",
                icon="teachers",
            ),
        },
        status_code=status_code,
    )


def _validate_section_assignments(
    subject_assignment_map,
    normalized_subject_codes,
    subject_map,
    section_assignment_support,
    current_teacher_id: int | None = None,
):
    errors = []
    total_assigned_hours = 0
    planning_sections_by_id = section_assignment_support["planning_sections_by_id"]
    occupied_assignments = section_assignment_support["occupied_assignments"]

    for subject_code, planning_section_ids in subject_assignment_map.items():
        if subject_code not in normalized_subject_codes:
            errors.append(
                f"Section assignments were provided for {subject_code}, but that subject is not selected for this teacher."
            )
            continue

        subject = subject_map.get(subject_code)
        if not subject:
            errors.append(
                f"Section assignments were provided for {subject_code}, but the subject is not available in the current scope."
            )
            continue

        expected_grade_label = _subject_grade_label(subject.grade)
        for planning_section_id in sorted(planning_section_ids):
            planning_section = planning_sections_by_id.get(planning_section_id)
            if not planning_section:
                errors.append(
                    f"Selected section #{planning_section_id} for {subject_code} was not found in the current branch and academic year."
                )
                continue

            actual_grade_label = str(planning_section.grade_level or "").strip().upper()
            if expected_grade_label != actual_grade_label:
                errors.append(
                    f"{subject_code} belongs to Grade {expected_grade_label}, so it cannot be assigned to {_format_section_label(planning_section)}."
                )
                continue

            occupied_teacher_id = occupied_assignments.get(
                (subject_code, planning_section_id)
            )
            if (
                occupied_teacher_id is not None
                and occupied_teacher_id != current_teacher_id
            ):
                errors.append(
                    f"{subject_code} is already assigned in {_format_section_label(planning_section)} to another teacher."
                )
                continue

            total_assigned_hours += int(subject.weekly_hours or 0)

    return errors, total_assigned_hours


@router.get("/")
def teachers_page(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    return _render_teachers_page(
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/copy-from-year")
def copy_teachers_from_year(
    request: Request,
    source_academic_year_id: int = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.is_developer(current_user):
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Only the developer user can copy teachers between academic years.",
        )

    branch_id, target_academic_year_id = _get_scope_ids(current_user)
    if source_academic_year_id == target_academic_year_id:
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Select a different academic year to copy teachers from.",
        )

    source_year = get_academic_year(db, source_academic_year_id)
    target_year = get_academic_year(db, target_academic_year_id)
    if not source_year or not target_year:
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="The selected academic year was not found.",
        )

    source_teachers = (
        db.query(models.Teacher)
        .filter(
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == source_academic_year_id,
        )
        .order_by(
            models.Teacher.first_name.asc(),
            models.Teacher.last_name.asc(),
            models.Teacher.id.asc(),
        )
        .all()
    )
    if not source_teachers:
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error=f"No teachers were found in {source_year.year_name} for the current branch.",
        )

    source_teacher_ids = [
        teacher.id for teacher in source_teachers if getattr(teacher, "id", None)
    ]
    source_subject_codes_by_teacher = {
        teacher_id: set() for teacher_id in source_teacher_ids
    }
    source_subject_override_map_by_teacher = defaultdict(dict)
    if source_teacher_ids:
        source_allocations = (
            db.query(models.TeacherSubjectAllocation)
            .filter(models.TeacherSubjectAllocation.teacher_id.in_(source_teacher_ids))
            .all()
        )
    else:
        source_allocations = []

    for allocation in source_allocations:
        if allocation.subject_code:
            source_subject_codes_by_teacher.setdefault(allocation.teacher_id, set()).add(
                allocation.subject_code
            )
            source_subject_override_map_by_teacher[allocation.teacher_id][
                allocation.subject_code
            ] = bool(allocation.compatibility_override)

    source_qualification_keys_by_teacher = defaultdict(list)
    if source_teacher_ids:
        source_qualification_rows = (
            db.query(models.TeacherQualificationSelection)
            .filter(models.TeacherQualificationSelection.teacher_id.in_(source_teacher_ids))
            .all()
        )
    else:
        source_qualification_rows = []

    for qualification_row in source_qualification_rows:
        if qualification_row.qualification_key:
            source_qualification_keys_by_teacher[qualification_row.teacher_id].append(
                qualification_row.qualification_key
            )

    source_assignments_by_teacher = defaultdict(list)
    source_section_ids = set()
    if source_teacher_ids:
        source_section_assignments = (
            db.query(models.TeacherSectionAssignment)
            .filter(models.TeacherSectionAssignment.teacher_id.in_(source_teacher_ids))
            .all()
        )
    else:
        source_section_assignments = []

    for assignment in source_section_assignments:
        source_assignments_by_teacher[assignment.teacher_id].append(assignment)
        source_section_ids.add(assignment.planning_section_id)

    source_sections_by_id = {}
    if source_section_ids:
        source_sections_by_id = {
            section.id: section
            for section in db.query(models.PlanningSection).filter(
                models.PlanningSection.id.in_(source_section_ids),
                models.PlanningSection.branch_id == branch_id,
                models.PlanningSection.academic_year_id == source_academic_year_id,
            ).all()
        }

    target_subject_codes = {
        subject_code
        for (subject_code,) in (
            db.query(models.Subject.subject_code)
            .filter(
                models.Subject.branch_id == branch_id,
                models.Subject.academic_year_id == target_academic_year_id,
            )
            .all()
        )
        if subject_code
    }

    target_teachers = (
        db.query(models.Teacher)
        .filter(
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == target_academic_year_id,
        )
        .all()
    )
    target_teachers_by_teacher_id = {
        teacher.teacher_id: teacher
        for teacher in target_teachers
        if teacher.teacher_id
    }

    target_teacher_ids = [
        teacher.id for teacher in target_teachers if getattr(teacher, "id", None)
    ]
    existing_target_allocation_keys = set()
    existing_target_qualification_keys = set()
    if target_teacher_ids:
        for allocation in db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id.in_(target_teacher_ids)
        ).all():
            existing_target_allocation_keys.add(
                (allocation.teacher_id, allocation.subject_code)
            )
        for qualification_row in db.query(models.TeacherQualificationSelection).filter(
            models.TeacherQualificationSelection.teacher_id.in_(target_teacher_ids)
        ).all():
            existing_target_qualification_keys.add(
                (qualification_row.teacher_id, qualification_row.qualification_key)
            )

    target_sections = (
        db.query(models.PlanningSection)
        .filter(
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == target_academic_year_id,
        )
        .all()
    )
    target_sections_by_key = {
        (section.grade_level, section.section_name): section
        for section in target_sections
    }
    target_section_ids = [
        section.id for section in target_sections if getattr(section, "id", None)
    ]
    existing_target_assignment_keys = set()
    if target_section_ids:
        for assignment in db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.planning_section_id.in_(target_section_ids)
        ).all():
            existing_target_assignment_keys.add(
                (assignment.planning_section_id, assignment.subject_code)
            )

    created_teacher_count = 0
    reused_teacher_count = 0
    copied_subject_link_count = 0
    copied_section_assignment_count = 0
    skipped_missing_teacher_id_count = 0
    skipped_missing_subject_count = 0
    skipped_missing_section_count = 0
    skipped_occupied_section_count = 0
    qualification_lookup = get_qualification_lookup(db)

    for source_teacher in source_teachers:
        normalized_teacher_id = _normalize_teacher_id(source_teacher.teacher_id or "")
        if not normalized_teacher_id:
            skipped_missing_teacher_id_count += 1
            continue

        source_qualification_keys = normalize_qualification_keys(
            source_qualification_keys_by_teacher.get(source_teacher.id, []),
            qualification_lookup=qualification_lookup,
        )
        if not source_qualification_keys:
            source_qualification_keys = infer_qualification_keys_from_legacy_text(
                source_teacher.degree_major or "",
                qualification_lookup=qualification_lookup,
            )
        qualification_snapshot = build_legacy_qualification_snapshot(
            source_qualification_keys,
            qualification_lookup=qualification_lookup,
        )

        target_teacher = target_teachers_by_teacher_id.get(normalized_teacher_id)
        if target_teacher is None:
            target_teacher = models.Teacher(
                teacher_id=normalized_teacher_id,
                first_name=source_teacher.first_name,
                middle_name=source_teacher.middle_name,
                last_name=source_teacher.last_name,
                degree_major=qualification_snapshot or source_teacher.degree_major,
                subject_code=None,
                level=source_teacher.level,
                max_hours=source_teacher.max_hours or STANDARD_MAX_HOURS,
                extra_hours_allowed=bool(source_teacher.extra_hours_allowed),
                extra_hours_count=source_teacher.extra_hours_count or 0,
                teaches_national_section=bool(
                    source_teacher.teaches_national_section
                ),
                national_section_hours=source_teacher.national_section_hours or 0,
                branch_id=branch_id,
                academic_year_id=target_academic_year_id,
            )
            db.add(target_teacher)
            db.flush()
            target_teachers_by_teacher_id[normalized_teacher_id] = target_teacher
            created_teacher_count += 1
        else:
            if not (target_teacher.degree_major or "").strip() and qualification_snapshot:
                target_teacher.degree_major = qualification_snapshot
            reused_teacher_count += 1

        for qualification_key in source_qualification_keys:
            qualification_row_key = (target_teacher.id, qualification_key)
            if qualification_row_key in existing_target_qualification_keys:
                continue

            db.add(
                models.TeacherQualificationSelection(
                    teacher_id=target_teacher.id,
                    qualification_key=qualification_key,
                )
            )
            existing_target_qualification_keys.add(qualification_row_key)

        source_subject_codes = set(source_subject_codes_by_teacher.get(source_teacher.id, set()))
        fallback_subject_code = str(source_teacher.subject_code or "").strip().upper()
        if fallback_subject_code:
            source_subject_codes.add(fallback_subject_code)

        valid_subject_codes = []
        for subject_code in sorted(source_subject_codes):
            if subject_code not in target_subject_codes:
                skipped_missing_subject_count += 1
                continue

            valid_subject_codes.append(subject_code)
            allocation_key = (target_teacher.id, subject_code)
            if allocation_key in existing_target_allocation_keys:
                continue

            db.add(
                models.TeacherSubjectAllocation(
                    teacher_id=target_teacher.id,
                    subject_code=subject_code,
                    compatibility_override=bool(
                        source_subject_override_map_by_teacher.get(source_teacher.id, {}).get(
                            subject_code,
                            False,
                        )
                    ),
                )
            )
            existing_target_allocation_keys.add(allocation_key)
            copied_subject_link_count += 1

        if not target_teacher.subject_code and valid_subject_codes:
            target_teacher.subject_code = valid_subject_codes[0]

        for source_assignment in source_assignments_by_teacher.get(source_teacher.id, []):
            subject_code = str(source_assignment.subject_code or "").strip().upper()
            if not subject_code:
                continue
            if subject_code not in target_subject_codes:
                skipped_missing_subject_count += 1
                continue

            source_section = source_sections_by_id.get(source_assignment.planning_section_id)
            if not source_section:
                skipped_missing_section_count += 1
                continue

            target_section = target_sections_by_key.get(
                (source_section.grade_level, source_section.section_name)
            )
            if not target_section:
                skipped_missing_section_count += 1
                continue

            allocation_key = (target_teacher.id, subject_code)
            if allocation_key not in existing_target_allocation_keys:
                db.add(
                    models.TeacherSubjectAllocation(
                        teacher_id=target_teacher.id,
                        subject_code=subject_code,
                        compatibility_override=bool(
                            source_subject_override_map_by_teacher.get(source_teacher.id, {}).get(
                                subject_code,
                                False,
                            )
                        ),
                    )
                )
                existing_target_allocation_keys.add(allocation_key)
                copied_subject_link_count += 1

            assignment_key = (target_section.id, subject_code)
            if assignment_key in existing_target_assignment_keys:
                skipped_occupied_section_count += 1
                continue

            db.add(
                models.TeacherSectionAssignment(
                    teacher_id=target_teacher.id,
                    planning_section_id=target_section.id,
                    subject_code=subject_code,
                )
            )
            existing_target_assignment_keys.add(assignment_key)
            copied_section_assignment_count += 1

    db.commit()

    success_parts = [
        (
            f"Teachers copied from {source_year.year_name} to {target_year.year_name}: "
            f"{created_teacher_count} profiles added"
        ),
        f"{copied_subject_link_count} subject links added",
        f"{copied_section_assignment_count} section-teaching links added.",
    ]
    if reused_teacher_count:
        success_parts.append(f"{reused_teacher_count} existing teacher profiles were reused.")
    if skipped_missing_teacher_id_count:
        success_parts.append(
            f"{skipped_missing_teacher_id_count} source teachers without an ID were skipped."
        )
    if skipped_missing_subject_count:
        success_parts.append(
            f"{skipped_missing_subject_count} subject links were skipped because the subject does not exist in the target year."
        )
    if skipped_missing_section_count:
        success_parts.append(
            f"{skipped_missing_section_count} section links were skipped because the matching planning section does not exist in the target year."
        )
    if skipped_occupied_section_count:
        success_parts.append(
            f"{skipped_occupied_section_count} section links were skipped because that section already has a teacher for the subject."
        )

    return _render_teachers_page(
        request=request,
        db=db,
        current_user=current_user,
        success=" ".join(success_parts),
    )


@router.post("/")
def create_teacher(
    request: Request,
    teacher_id: str = Form(...),
    first_name: str = Form(...),
    middle_name: str = Form(""),
    last_name: str = Form(...),
    qualification_keys: list[str] = Form([]),
    qualification_override_subject_codes: list[str] = Form([]),
    subject_codes: list[str] = Form([]),
    section_assignment_values: list[str] = Form([]),
    max_hours: str = Form("24"),
    extra_hours_allowed: str = Form(""),
    extra_hours_count: str = Form("0"),
    teaches_national_section: str = Form(""),
    national_section_hours: str = Form("0"),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_modify_data(current_user):
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Your role has read-only access and cannot create teachers.",
        )

    teacher_id = _normalize_teacher_id(teacher_id)
    first_name = _normalize_name(first_name)
    middle_name = _normalize_name(middle_name)
    last_name = _normalize_name(last_name)
    raw_extra_hours_count = str(extra_hours_count or "").strip()
    raw_qualification_keys = [
        str(value or "").strip()
        for value in qualification_keys
        if str(value or "").strip()
    ]
    qualification_lookup = get_qualification_lookup(db)
    normalized_qualification_keys = normalize_qualification_keys(
        raw_qualification_keys,
        qualification_lookup=qualification_lookup,
    )
    invalid_qualification_keys = sorted({
        key for key in raw_qualification_keys if key not in qualification_lookup
    })
    normalized_subject_codes = _normalize_subject_codes(subject_codes)
    normalized_override_subject_codes = _normalize_subject_codes(
        qualification_override_subject_codes
    )
    (
        section_assignment_map,
        normalized_section_assignment_values,
        invalid_section_assignment_values,
    ) = _parse_section_assignment_values(section_assignment_values)
    parsed_max_hours = _parse_int(max_hours)
    allowed_extra = _is_extra_hours_allowed(extra_hours_allowed)
    parsed_extra_hours_count = _parse_int(extra_hours_count)
    is_national_section_enabled = _teaches_national_section(
        teaches_national_section
    )
    parsed_national_section_hours = _parse_int(national_section_hours)
    branch_id, academic_year_id = _get_scope_ids(current_user)

    errors = []
    if not TEACHER_ID_PATTERN.match(teacher_id):
        errors.append("Teacher ID (Iqama/National ID) must be numeric and up to 10 digits.")

    if not first_name:
        errors.append("First name is required.")
    elif not NAME_PATTERN.match(first_name):
        errors.append("First name must contain letters only.")

    if middle_name and not NAME_PATTERN.match(middle_name):
        errors.append("Middle name must contain letters only.")

    if not last_name:
        errors.append("Last name is required.")
    elif not NAME_PATTERN.match(last_name):
        errors.append("Last name must contain letters only.")

    if invalid_qualification_keys:
        errors.append(
            "One or more selected qualifications were invalid. Please reselect them from the predefined list."
        )
    if not normalized_qualification_keys:
        errors.append(
            "Select at least one degree or specialization for this teacher."
        )

    if invalid_section_assignment_values:
        errors.append("One or more section assignments were invalid. Please reselect the sections.")
    invalid_override_subject_codes = sorted(
        set(normalized_override_subject_codes) - set(normalized_subject_codes)
    )
    if invalid_override_subject_codes:
        errors.append(
            "Admin override can only be used for currently selected subjects: "
            + ", ".join(invalid_override_subject_codes)
        )

    subject_map = {}
    effective_override_subject_codes = sorted(
        set(normalized_override_subject_codes) & set(normalized_subject_codes)
    )
    if not normalized_subject_codes:
        errors.append("Select at least one subject for this teacher.")
    else:
        scoped_subjects = db.query(models.Subject).filter(
            models.Subject.subject_code.in_(normalized_subject_codes),
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
        ).all()
        subject_map = {
            subject.subject_code: subject
            for subject in scoped_subjects
            if subject.subject_code
        }
        missing_subject_codes = [
            code for code in normalized_subject_codes
            if code not in subject_map
        ]
        if missing_subject_codes:
            errors.append(
                "Selected subject codes do not exist in the current branch/academic year: "
                + ", ".join(missing_subject_codes)
            )
        (
            subject_alignment_errors,
            effective_override_subject_codes,
        ) = _validate_subject_qualification_alignment(
            normalized_subject_codes=normalized_subject_codes,
            subject_map=subject_map,
            qualification_keys=normalized_qualification_keys,
            override_subject_codes=normalized_override_subject_codes,
            qualification_lookup=qualification_lookup,
        )
        errors.extend(subject_alignment_errors)

    if parsed_max_hours is None or parsed_max_hours <= 0:
        errors.append("Max hours must be a positive whole number.")
    elif parsed_max_hours > STANDARD_MAX_HOURS and not allowed_extra:
        errors.append("To set max hours above 24, enable Extra Hours Allowed first.")

    if allowed_extra:
        if parsed_extra_hours_count is None or parsed_extra_hours_count <= 0:
            errors.append("Extra hours count must be a positive whole number when extra hours are allowed.")
    else:
        parsed_extra_hours_count = 0

    if is_national_section_enabled:
        if (
            parsed_national_section_hours is None
            or parsed_national_section_hours <= 0
        ):
            errors.append(
                "National section hours must be a positive whole number when National Section is enabled."
            )
    else:
        parsed_national_section_hours = 0

    capacity_breakdown = build_capacity_breakdown(
        parsed_max_hours,
        extra_hours_allowed=allowed_extra,
        extra_hours_count=parsed_extra_hours_count or 0,
        teaches_national_section=is_national_section_enabled,
        national_section_hours=parsed_national_section_hours or 0,
        default_max_hours=STANDARD_MAX_HOURS,
    )
    if (
        parsed_max_hours is not None
        and parsed_max_hours > 0
        and is_national_section_enabled
        and capacity_breakdown["national_section_hours"]
        > capacity_breakdown["total_capacity_hours"]
    ):
        errors.append(
            "National section hours cannot exceed the teacher total capacity "
            f"({capacity_breakdown['total_capacity_hours']}h)."
        )

    section_assignment_support = _get_section_options_by_subject(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    section_assignment_errors, total_assigned_hours = _validate_section_assignments(
        subject_assignment_map=section_assignment_map,
        normalized_subject_codes=normalized_subject_codes,
        subject_map=subject_map,
        section_assignment_support=section_assignment_support,
    )
    errors.extend(section_assignment_errors)

    if parsed_max_hours is not None and parsed_max_hours > 0:
        available_international_hours = capacity_breakdown[
            "international_capacity_hours"
        ]
        if total_assigned_hours > available_international_hours:
            errors.append(
                "Assigned section hours "
                f"({total_assigned_hours}) exceed allowed capacity "
                f"({available_international_hours}) based on Max Hours ({capacity_breakdown['max_hours']}) "
                f"+ Extra Hours ({capacity_breakdown['extra_hours']}) "
                f"- National Section Hours ({capacity_breakdown['national_section_hours']}). "
                "Reduce the selected sections, reduce national section hours, or increase allowed extra hours."
            )

    duplicate_teacher = db.query(models.Teacher).filter(
        models.Teacher.teacher_id == teacher_id,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).first()
    if duplicate_teacher:
        errors.append("Teacher ID already exists in the current branch and academic year.")

    if errors:
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Unable to create teacher. Please fix the highlighted issues.",
            detail_errors=errors,
            form_data={
                "teacher_id": teacher_id,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "qualification_keys": normalized_qualification_keys,
                "override_subject_codes": effective_override_subject_codes,
                "max_hours": str(parsed_max_hours or 24),
                "extra_hours_allowed": allowed_extra,
                "extra_hours_count": raw_extra_hours_count,
                "teaches_national_section": is_national_section_enabled,
                "national_section_hours": str(
                    parsed_national_section_hours
                    if parsed_national_section_hours is not None
                    else 1
                ),
            },
            selected_subject_codes=normalized_subject_codes,
            selected_section_assignment_values=normalized_section_assignment_values,
            selected_qualification_keys=normalized_qualification_keys,
            selected_override_subject_codes=effective_override_subject_codes,
        )

    teacher = models.Teacher(
        teacher_id=teacher_id,
        first_name=first_name,
        middle_name=middle_name if middle_name else None,
        last_name=last_name,
        degree_major=build_legacy_qualification_snapshot(
            normalized_qualification_keys,
            qualification_lookup=qualification_lookup,
        ),
        subject_code=normalized_subject_codes[0] if normalized_subject_codes else None,
        level=None,
        max_hours=parsed_max_hours if parsed_max_hours is not None else STANDARD_MAX_HOURS,
        extra_hours_allowed=allowed_extra,
        extra_hours_count=parsed_extra_hours_count if parsed_extra_hours_count is not None else 0,
        teaches_national_section=is_national_section_enabled,
        national_section_hours=(
            parsed_national_section_hours
            if parsed_national_section_hours is not None
            else 0
        ),
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )

    try:
        db.add(teacher)
        db.flush()
        for qualification_key in normalized_qualification_keys:
            db.add(
                models.TeacherQualificationSelection(
                    teacher_id=teacher.id,
                    qualification_key=qualification_key,
                )
            )
        for subject_code in normalized_subject_codes:
            db.add(
                models.TeacherSubjectAllocation(
                    teacher_id=teacher.id,
                    subject_code=subject_code,
                    compatibility_override=subject_code in effective_override_subject_codes,
                )
            )
        for subject_code, planning_section_ids in section_assignment_map.items():
            for planning_section_id in sorted(planning_section_ids):
                db.add(
                    models.TeacherSectionAssignment(
                        teacher_id=teacher.id,
                        planning_section_id=planning_section_id,
                        subject_code=subject_code,
                    )
                )
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Teacher creation failed due to duplicate or invalid data.",
            form_data={
                "teacher_id": teacher_id,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "qualification_keys": normalized_qualification_keys,
                "override_subject_codes": effective_override_subject_codes,
                "max_hours": str(parsed_max_hours or 24),
                "extra_hours_allowed": allowed_extra,
                "extra_hours_count": raw_extra_hours_count,
                "teaches_national_section": is_national_section_enabled,
                "national_section_hours": str(
                    parsed_national_section_hours
                    if parsed_national_section_hours is not None
                    else 1
                ),
            },
            selected_subject_codes=normalized_subject_codes,
            selected_section_assignment_values=normalized_section_assignment_values,
            selected_qualification_keys=normalized_qualification_keys,
            selected_override_subject_codes=effective_override_subject_codes,
        )

    return _render_teachers_page(
        request=request,
        db=db,
        current_user=current_user,
        success=f"Teacher created successfully: {first_name} {last_name}",
    )


@router.get("/edit/{teacher_pk}")
def edit_teacher_page(
    request: Request,
    teacher_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_edit_data(current_user):
        return RedirectResponse(url="/teachers", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_pk,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id
    ).first()
    if not teacher:
        return RedirectResponse(url="/teachers", status_code=302)

    return _render_edit_teacher_page(
        request=request,
        db=db,
        current_user=current_user,
        teacher=teacher,
    )


@router.post("/edit/{teacher_pk}")
def update_teacher(
    request: Request,
    teacher_pk: int,
    teacher_id: str = Form(...),
    first_name: str = Form(...),
    middle_name: str = Form(""),
    last_name: str = Form(...),
    qualification_keys: list[str] = Form([]),
    qualification_override_subject_codes: list[str] = Form([]),
    subject_codes: list[str] = Form([]),
    section_assignment_values: list[str] = Form([]),
    max_hours: str = Form("24"),
    extra_hours_allowed: str = Form(""),
    extra_hours_count: str = Form("0"),
    teaches_national_section: str = Form(""),
    national_section_hours: str = Form("0"),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_edit_data(current_user):
        return RedirectResponse(url="/teachers", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_pk,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id
    ).first()
    if not teacher:
        return RedirectResponse(url="/teachers", status_code=302)

    teacher_id = _normalize_teacher_id(teacher_id)
    first_name = _normalize_name(first_name)
    middle_name = _normalize_name(middle_name)
    last_name = _normalize_name(last_name)
    raw_extra_hours_count = str(extra_hours_count or "").strip()
    raw_qualification_keys = [
        str(value or "").strip()
        for value in qualification_keys
        if str(value or "").strip()
    ]
    qualification_lookup = get_qualification_lookup(db)
    normalized_qualification_keys = normalize_qualification_keys(
        raw_qualification_keys,
        qualification_lookup=qualification_lookup,
    )
    invalid_qualification_keys = sorted({
        key for key in raw_qualification_keys if key not in qualification_lookup
    })
    normalized_subject_codes = _normalize_subject_codes(subject_codes)
    normalized_override_subject_codes = _normalize_subject_codes(
        qualification_override_subject_codes
    )
    (
        section_assignment_map,
        normalized_section_assignment_values,
        invalid_section_assignment_values,
    ) = _parse_section_assignment_values(section_assignment_values)
    parsed_max_hours = _parse_int(max_hours)
    allowed_extra = _is_extra_hours_allowed(extra_hours_allowed)
    parsed_extra_hours_count = _parse_int(extra_hours_count)
    is_national_section_enabled = _teaches_national_section(
        teaches_national_section
    )
    parsed_national_section_hours = _parse_int(national_section_hours)

    errors = []
    if not TEACHER_ID_PATTERN.match(teacher_id):
        errors.append("Teacher ID (Iqama/National ID) must be numeric and up to 10 digits.")

    if not first_name:
        errors.append("First name is required.")
    elif not NAME_PATTERN.match(first_name):
        errors.append("First name must contain letters only.")

    if middle_name and not NAME_PATTERN.match(middle_name):
        errors.append("Middle name must contain letters only.")

    if not last_name:
        errors.append("Last name is required.")
    elif not NAME_PATTERN.match(last_name):
        errors.append("Last name must contain letters only.")

    if invalid_qualification_keys:
        errors.append(
            "One or more selected qualifications were invalid. Please reselect them from the predefined list."
        )
    if not normalized_qualification_keys:
        errors.append(
            "Select at least one degree or specialization for this teacher."
        )

    if invalid_section_assignment_values:
        errors.append("One or more section assignments were invalid. Please reselect the sections.")
    invalid_override_subject_codes = sorted(
        set(normalized_override_subject_codes) - set(normalized_subject_codes)
    )
    if invalid_override_subject_codes:
        errors.append(
            "Admin override can only be used for currently selected subjects: "
            + ", ".join(invalid_override_subject_codes)
        )

    subject_map = {}
    effective_override_subject_codes = sorted(
        set(normalized_override_subject_codes) & set(normalized_subject_codes)
    )
    if not normalized_subject_codes:
        errors.append("Select at least one subject for this teacher.")
    else:
        scoped_subjects = db.query(models.Subject).filter(
            models.Subject.subject_code.in_(normalized_subject_codes),
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
        ).all()
        subject_map = {
            subject.subject_code: subject
            for subject in scoped_subjects
            if subject.subject_code
        }
        missing_subject_codes = [
            code for code in normalized_subject_codes
            if code not in subject_map
        ]
        if missing_subject_codes:
            errors.append(
                "Selected subject codes do not exist in the current branch/academic year: "
                + ", ".join(missing_subject_codes)
            )
        (
            subject_alignment_errors,
            effective_override_subject_codes,
        ) = _validate_subject_qualification_alignment(
            normalized_subject_codes=normalized_subject_codes,
            subject_map=subject_map,
            qualification_keys=normalized_qualification_keys,
            override_subject_codes=normalized_override_subject_codes,
            qualification_lookup=qualification_lookup,
        )
        errors.extend(subject_alignment_errors)

    if parsed_max_hours is None or parsed_max_hours <= 0:
        errors.append("Max hours must be a positive whole number.")
    elif parsed_max_hours > STANDARD_MAX_HOURS and not allowed_extra:
        errors.append("To set max hours above 24, enable Extra Hours Allowed first.")

    if allowed_extra:
        if parsed_extra_hours_count is None or parsed_extra_hours_count <= 0:
            errors.append("Extra hours count must be a positive whole number when extra hours are allowed.")
    else:
        parsed_extra_hours_count = 0

    if is_national_section_enabled:
        if (
            parsed_national_section_hours is None
            or parsed_national_section_hours <= 0
        ):
            errors.append(
                "National section hours must be a positive whole number when National Section is enabled."
            )
    else:
        parsed_national_section_hours = 0

    capacity_breakdown = build_capacity_breakdown(
        parsed_max_hours,
        extra_hours_allowed=allowed_extra,
        extra_hours_count=parsed_extra_hours_count or 0,
        teaches_national_section=is_national_section_enabled,
        national_section_hours=parsed_national_section_hours or 0,
        default_max_hours=STANDARD_MAX_HOURS,
    )
    if (
        parsed_max_hours is not None
        and parsed_max_hours > 0
        and is_national_section_enabled
        and capacity_breakdown["national_section_hours"]
        > capacity_breakdown["total_capacity_hours"]
    ):
        errors.append(
            "National section hours cannot exceed the teacher total capacity "
            f"({capacity_breakdown['total_capacity_hours']}h)."
        )

    section_assignment_support = _get_section_options_by_subject(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        current_teacher_id=teacher.id,
    )
    section_assignment_errors, total_assigned_hours = _validate_section_assignments(
        subject_assignment_map=section_assignment_map,
        normalized_subject_codes=normalized_subject_codes,
        subject_map=subject_map,
        section_assignment_support=section_assignment_support,
        current_teacher_id=teacher.id,
    )
    errors.extend(section_assignment_errors)

    if parsed_max_hours is not None and parsed_max_hours > 0:
        available_international_hours = capacity_breakdown[
            "international_capacity_hours"
        ]
        if total_assigned_hours > available_international_hours:
            errors.append(
                "Assigned section hours "
                f"({total_assigned_hours}) exceed allowed capacity "
                f"({available_international_hours}) based on Max Hours ({capacity_breakdown['max_hours']}) "
                f"+ Extra Hours ({capacity_breakdown['extra_hours']}) "
                f"- National Section Hours ({capacity_breakdown['national_section_hours']}). "
                "Reduce the selected sections, reduce national section hours, or increase allowed extra hours."
            )

    duplicate_teacher = db.query(models.Teacher).filter(
        models.Teacher.teacher_id == teacher_id,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
        models.Teacher.id != teacher.id
    ).first()
    if duplicate_teacher:
        errors.append("Teacher ID already exists in the current branch and academic year.")

    if errors:
        teacher_preview = SimpleNamespace(
            id=teacher.id,
            teacher_id=teacher_id,
            first_name=first_name,
            middle_name=middle_name if middle_name else None,
            last_name=last_name,
            degree_major=build_legacy_qualification_snapshot(
                normalized_qualification_keys,
                qualification_lookup=qualification_lookup,
            ),
            max_hours=(
                parsed_max_hours
                if parsed_max_hours is not None
                else STANDARD_MAX_HOURS
            ),
            extra_hours_allowed=allowed_extra,
            extra_hours_count=(
                parsed_extra_hours_count
                if parsed_extra_hours_count is not None
                else 0
            ),
            teaches_national_section=is_national_section_enabled,
            national_section_hours=(
                parsed_national_section_hours
                if parsed_national_section_hours is not None
                else 0
            ),
        )
        return _render_edit_teacher_page(
            request=request,
            db=db,
            current_user=current_user,
            teacher=teacher_preview,
            error=" ".join(errors),
            assigned_subject_codes=list(normalized_subject_codes),
            selected_section_assignment_values=normalized_section_assignment_values,
            selected_qualification_keys=normalized_qualification_keys,
            selected_override_subject_codes=effective_override_subject_codes,
            status_code=400,
        )

    teacher.teacher_id = teacher_id
    teacher.first_name = first_name
    teacher.middle_name = middle_name if middle_name else None
    teacher.last_name = last_name
    teacher.degree_major = build_legacy_qualification_snapshot(
        normalized_qualification_keys,
        qualification_lookup=qualification_lookup,
    )
    teacher.subject_code = normalized_subject_codes[0] if normalized_subject_codes else None
    teacher.level = None
    teacher.max_hours = parsed_max_hours if parsed_max_hours is not None else STANDARD_MAX_HOURS
    teacher.extra_hours_allowed = allowed_extra
    teacher.extra_hours_count = parsed_extra_hours_count if parsed_extra_hours_count is not None else 0
    teacher.teaches_national_section = is_national_section_enabled
    teacher.national_section_hours = (
        parsed_national_section_hours
        if parsed_national_section_hours is not None
        else 0
    )

    try:
        db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        db.query(models.TeacherQualificationSelection).filter(
            models.TeacherQualificationSelection.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        for qualification_key in normalized_qualification_keys:
            db.add(
                models.TeacherQualificationSelection(
                    teacher_id=teacher.id,
                    qualification_key=qualification_key,
                )
            )
        for subject_code in normalized_subject_codes:
            db.add(
                models.TeacherSubjectAllocation(
                    teacher_id=teacher.id,
                    subject_code=subject_code,
                    compatibility_override=subject_code in effective_override_subject_codes,
                )
            )
        for subject_code, planning_section_ids in section_assignment_map.items():
            for planning_section_id in sorted(planning_section_ids):
                db.add(
                    models.TeacherSectionAssignment(
                        teacher_id=teacher.id,
                        planning_section_id=planning_section_id,
                        subject_code=subject_code,
                    )
                )
        db.commit()
    except IntegrityError:
        db.rollback()
        teacher_preview = SimpleNamespace(
            id=teacher.id,
            teacher_id=teacher_id,
            first_name=first_name,
            middle_name=middle_name if middle_name else None,
            last_name=last_name,
            degree_major=build_legacy_qualification_snapshot(
                normalized_qualification_keys,
                qualification_lookup=qualification_lookup,
            ),
            max_hours=(
                parsed_max_hours
                if parsed_max_hours is not None
                else STANDARD_MAX_HOURS
            ),
            extra_hours_allowed=allowed_extra,
            extra_hours_count=(
                parsed_extra_hours_count
                if parsed_extra_hours_count is not None
                else 0
            ),
            teaches_national_section=is_national_section_enabled,
            national_section_hours=(
                parsed_national_section_hours
                if parsed_national_section_hours is not None
                else 0
            ),
        )
        return _render_edit_teacher_page(
            request=request,
            db=db,
            current_user=current_user,
            teacher=teacher_preview,
            error="Unable to update teacher due to duplicate or invalid data.",
            assigned_subject_codes=list(normalized_subject_codes),
            selected_section_assignment_values=normalized_section_assignment_values,
            selected_qualification_keys=normalized_qualification_keys,
            selected_override_subject_codes=effective_override_subject_codes,
            status_code=400,
        )

    return RedirectResponse(url="/teachers", status_code=302)


@router.get("/delete/{teacher_pk}")
def delete_teacher(
    request: Request,
    teacher_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_delete_data(current_user):
        return RedirectResponse(url="/teachers", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_pk,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id
    ).first()
    if teacher:
        db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        db.query(models.TeacherQualificationSelection).filter(
            models.TeacherQualificationSelection.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        db.delete(teacher)
        db.commit()

    return RedirectResponse(url="/teachers", status_code=302)


@router.post("/delete-bulk")
def delete_teachers_bulk(
    request: Request,
    selected_teacher_ids: list[int] = Form([]),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_delete_data(current_user):
        return RedirectResponse(url="/teachers", status_code=302)

    unique_teacher_ids = sorted({
        int(teacher_id)
        for teacher_id in selected_teacher_ids
        if teacher_id
    })
    if not unique_teacher_ids:
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Select at least one teacher to delete.",
        )

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher_rows = db.query(models.Teacher).filter(
        models.Teacher.id.in_(unique_teacher_ids),
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).all()
    teacher_map = {teacher.id: teacher for teacher in teacher_rows}
    missing_ids = [
        teacher_id for teacher_id in unique_teacher_ids
        if teacher_id not in teacher_map
    ]
    if missing_ids:
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="One or more selected teachers were not found in your current scope.",
        )

    teacher_ids_to_delete = list(teacher_map.keys())
    db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.teacher_id.in_(teacher_ids_to_delete)
    ).delete(synchronize_session=False)
    db.query(models.TeacherQualificationSelection).filter(
        models.TeacherQualificationSelection.teacher_id.in_(teacher_ids_to_delete)
    ).delete(synchronize_session=False)
    db.query(models.TeacherSubjectAllocation).filter(
        models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids_to_delete)
    ).delete(synchronize_session=False)
    db.query(models.Teacher).filter(
        models.Teacher.id.in_(teacher_ids_to_delete)
    ).delete(synchronize_session=False)
    db.commit()

    deleted_count = len(teacher_ids_to_delete)
    success_message = (
        "Teacher deleted successfully."
        if deleted_count == 1
        else f"{deleted_count} teachers deleted successfully."
    )

    return _render_teachers_page(
        request=request,
        db=db,
        current_user=current_user,
        success=success_message,
    )
