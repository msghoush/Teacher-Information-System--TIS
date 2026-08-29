from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy.orm import Session

import models
from homeroom_defaults import is_default_homeroom_subject
from planning_subject_demand_service import resolve_scope_subject_demands
from subject_distribution_rules import resolve_subject_distribution_rule


SNAPSHOT_SCHEMA_VERSION = 4


@dataclass(frozen=True)
class TimetableSnapshotData:
    canonical_json: str
    planning_fingerprint: str
    period_configuration_fingerprint: str
    constraint_fingerprint: str
    lock_fingerprint: str
    full_input_fingerprint: str
    authority_fingerprint: str


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _grade_label(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"K", "KG", "KINDERGARTEN"}:
        return "KG"
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        return text
    return "KG" if parsed == 0 else str(parsed)


def _build_planning_component(
    db: Session,
    *,
    branch_id: int,
    academic_year_id: int,
) -> dict:
    sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).order_by(models.PlanningSection.id.asc()).all()
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.id.asc()).all()
    teacher_ids = [
        int(row[0])
        for row in db.query(models.Teacher.id).filter(
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == academic_year_id,
        ).order_by(models.Teacher.id.asc()).all()
    ]
    section_ids = [int(section.id) for section in sections]
    resolved_demands = resolve_scope_subject_demands(
        db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        planning_section_ids=section_ids,
    )
    assignments = (
        db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.planning_section_id.in_(section_ids)
        ).order_by(models.TeacherSectionAssignment.id.asc()).all()
        if section_ids
        else []
    )
    explicit_teacher = {
        (
            int(assignment.planning_section_id),
            str(assignment.subject_code or "").strip().upper(),
        ): int(assignment.teacher_id)
        for assignment in assignments
        if assignment.planning_section_id is not None
        and assignment.teacher_id is not None
        and str(assignment.subject_code or "").strip()
    }
    subjects_by_code = {
        str(subject.subject_code or "").strip().upper(): subject
        for subject in subjects if str(subject.subject_code or "").strip()
    }

    section_payloads = []
    demand_payloads = []
    for section in sections:
        grade_label = _grade_label(section.grade_level)
        section_payloads.append(
            {
                "id": int(section.id),
                "grade": grade_label,
                "section_name": str(section.section_name or "").strip().upper(),
                "class_status": str(section.class_status or "").strip(),
                "homeroom_teacher_id": (
                    int(section.homeroom_teacher_id)
                    if section.homeroom_teacher_id is not None
                    else None
                ),
            }
        )
        for demand in resolved_demands.get(int(section.id), []):
            if not demand.is_active or int(demand.weekly_periods or 0) <= 0:
                continue
            subject_code = demand.subject_code
            subject = subjects_by_code.get(subject_code)
            if subject is None:
                continue
            teacher_id = explicit_teacher.get((int(section.id), subject_code))
            assignment_source = "planning"
            if (
                teacher_id is None
                and section.homeroom_teacher_id is not None
                and is_default_homeroom_subject(
                    grade_label,
                    subject_name=str(subject.subject_name or ""),
                    subject_code=subject_code,
                )
            ):
                teacher_id = int(section.homeroom_teacher_id)
                assignment_source = "homeroom_default"
            # Resolved once, at snapshot time, so a later rule change never
            # alters an already-created generation snapshot.
            distribution_rule = resolve_subject_distribution_rule(
                db,
                branch_id=branch_id,
                academic_year_id=academic_year_id,
                grade_level=grade_label,
                subject_code=subject_code,
                section_id=int(section.id),
            )
            demand_payloads.append(
                {
                    "section_id": int(section.id),
                    "subject_id": int(subject.id),
                    "subject_code": subject_code,
                    "required_weekly_periods": int(demand.weekly_periods),
                    "assigned_teacher_id": teacher_id,
                    "assignment_source": assignment_source,
                    # None means legacy fallback: no normalized rule is
                    # configured, so quality_rules_json authority applies.
                    "distribution_rule": distribution_rule,
                }
            )

    return {
        "valid_teacher_ids": teacher_ids,
        "sections": section_payloads,
        "demands": sorted(
            demand_payloads,
            key=lambda item: (
                item["section_id"],
                item["subject_code"],
                item["subject_id"],
            ),
        ),
    }


def _build_period_configuration_component(
    db: Session,
    *,
    branch_id: int,
    academic_year_id: int,
) -> dict:
    from timetable_logic import get_timetable_settings_payload

    payload = get_timetable_settings_payload(db, branch_id, academic_year_id)
    return {
        "saved": bool(payload["is_saved"]),
        "settings": {
            "working_days": payload["working_day_keys"],
            "periods_per_day": int(payload["periods_per_day"] or 0),
            "period_duration_minutes": int(payload["period_duration_minutes"] or 0),
            "school_start_time": str(payload["school_start_time"] or ""),
            "school_end_time": str(payload["school_end_time"] or ""),
            "quality_rules": payload.get("quality_rules") or {},
        },
        "blocks": payload["blocks"],
        "canonical_slot_projection": json.loads(
            payload["slot_projection"]["canonical_json"]
        ),
    }


def _normalize_locks(locks: Iterable[dict] | None) -> list[dict]:
    normalized = []
    for lock in locks or []:
        normalized.append(
            {
                "section_id": int(lock.get("section_id") or 0),
                "subject_code": str(lock.get("subject_code") or "").strip().upper(),
                "teacher_id": int(lock.get("teacher_id") or 0),
                "day_key": str(lock.get("day_key") or "").strip().lower(),
                "period_index": int(lock.get("period_index") or 0),
            }
        )
    return sorted(
        normalized,
        key=lambda item: (
            item["section_id"],
            item["day_key"],
            item["period_index"],
            item["subject_code"],
            item["teacher_id"],
        ),
    )


def _authority_constraints(constraints: dict) -> dict:
    authority = dict(constraints or {})
    authority.pop("generation", None)
    return authority


def build_current_snapshot_data(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    locks: Iterable[dict] | None = None,
    constraint_configuration: dict | None = None,
) -> TimetableSnapshotData:
    planning = _build_planning_component(
        db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    period_configuration = _build_period_configuration_component(
        db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    constraints = dict(constraint_configuration or {"stage": 2, "rules": []})
    from teacher_scheduling_rules import canonical_rules
    projection = period_configuration.get("canonical_slot_projection") or {}
    canonical_slots = [
        {"day_key": item.get("day_key") or timeline.get("day_key"),
         "period_index": item.get("period_index")}
        for timeline in projection.get("timelines") or []
        for item in timeline.get("items") or []
        if item.get("type") == "teaching" and item.get("schedulable", True)
    ]
    constraints["teacher_scheduling_rules"] = canonical_rules(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
        working_days=list(projection.get("working_day_keys") or []), slots=canonical_slots,
    )
    normalized_locks = _normalize_locks(locks)
    scope = {
        "school_group_id": int(school_group_id),
        "branch_id": int(branch_id),
        "academic_year_id": int(academic_year_id),
    }
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "scope": scope,
        "planning": planning,
        "period_configuration": period_configuration,
        "constraints": constraints,
        "locks": normalized_locks,
        "future_extensions": {
            "teacher_availability": [],
            "rooms_resources": [],
        },
    }
    planning_hash = fingerprint(planning)
    period_hash = fingerprint(period_configuration)
    constraint_hash = fingerprint(_authority_constraints(constraints))
    lock_hash = fingerprint(normalized_locks)
    authority_hash = fingerprint(
        {
            "scope": scope,
            "planning_fingerprint": planning_hash,
            "period_configuration_fingerprint": period_hash,
            "constraint_fingerprint": constraint_hash,
            "lock_fingerprint": lock_hash,
        }
    )
    return TimetableSnapshotData(
        canonical_json=canonical_json(snapshot),
        planning_fingerprint=planning_hash,
        period_configuration_fingerprint=period_hash,
        constraint_fingerprint=constraint_hash,
        lock_fingerprint=lock_hash,
        full_input_fingerprint=fingerprint({
            **snapshot,
            "constraints": _authority_constraints(constraints),
        }),
        authority_fingerprint=authority_hash,
    )


def create_current_input_snapshot(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    created_by_user_id: str | None = None,
    provenance: str = "manual",
    locks: Iterable[dict] | None = None,
    constraint_configuration: dict | None = None,
) -> models.TimetableInputSnapshot:
    data = build_current_snapshot_data(
        db,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        locks=locks,
        constraint_configuration=constraint_configuration,
    )
    snapshot = models.TimetableInputSnapshot(
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
        canonical_snapshot_json=data.canonical_json,
        planning_fingerprint=data.planning_fingerprint,
        period_configuration_fingerprint=data.period_configuration_fingerprint,
        constraint_fingerprint=data.constraint_fingerprint,
        lock_fingerprint=data.lock_fingerprint,
        full_input_fingerprint=data.full_input_fingerprint,
        created_by_user_id=created_by_user_id,
        provenance=provenance,
    )
    db.add(snapshot)
    db.flush()
    return snapshot
