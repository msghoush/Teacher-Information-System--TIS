from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


ConflictSeverity = Literal["HARD", "SOFT"]
EvidenceClass = Literal["DURABLE", "RECALCULABLE", "TRANSIENT"]


_CODE_MAP = {
    "teacher_collision": "TEACHER_COLLISION",
    "section_collision": "SECTION_COLLISION",
    "grouped_activity_incomplete": "GROUPED_ACTIVITY_VIOLATION",
    "grouped_resource_collision": "GROUPED_ACTIVITY_VIOLATION",
    "grouped_activity_invalid": "GROUPED_ACTIVITY_VIOLATION",
    "grouped_activity_authority_invalid": "GROUPED_ACTIVITY_VIOLATION",
    "teacher_unavailable_violated": "TEACHER_SCHEDULING_RULE_VIOLATION",
    "teacher_schedule_window_violated": "TEACHER_SCHEDULING_RULE_VIOLATION",
    "teacher_must_teach_missing": "TEACHER_SCHEDULING_RULE_VIOLATION",
    "demand_mismatch": "LESSON_REQUIREMENT_COUNT_VIOLATION",
    "total_demand_mismatch": "LESSON_REQUIREMENT_COUNT_VIOLATION",
    "extra_lesson": "LESSON_REQUIREMENT_COUNT_VIOLATION",
    "distribution_rule_invalid": "SUBJECT_DISTRIBUTION_VIOLATION",
    "distribution_rule_violated": "SUBJECT_DISTRIBUTION_VIOLATION",
    "invalid_slot": "NON_TEACHING_BLOCK_CONFLICT",
    "invalid_non_teaching_block": "NON_TEACHING_BLOCK_CONFLICT",
    "locked_lesson_invalid": "REGENERATION_LOCK_CONFLICT",
    "locked_lesson_conflict": "REGENERATION_LOCK_CONFLICT",
    "lock_missing": "REGENERATION_LOCK_CONFLICT",
    "lock_conflict": "REGENERATION_LOCK_CONFLICT",
    "locked_count_exceeds_demand": "REGENERATION_LOCK_CONFLICT",
    "scope_mismatch": "INVALID_SCOPE_REFERENCE",
    "scope_invalid": "INVALID_SCOPE_REFERENCE",
    "teacher_authority_invalid": "INVALID_SCOPE_REFERENCE",
    "stale_input": "STALE_GENERATION_AUTHORITY",
    "stale_source": "STALE_GENERATION_AUTHORITY",
    "validator_rejected": "INDEPENDENT_VALIDATION_FAILURE",
    "infeasible": "INFEASIBLE",
    "solver_timeout": "TIMEOUT",
    "verification_timeout": "TIMEOUT",
    "cancelled": "CANCELLATION",
    "cancel_requested": "CANCELLATION",
    "worker_error": "SOLVER_EXECUTION_FAILURE",
    "solver_model_invalid": "SOLVER_EXECUTION_FAILURE",
    "internal_error": "SOLVER_EXECUTION_FAILURE",
    "dispatch_failed": "SOLVER_EXECUTION_FAILURE",
}


def canonical_conflict_code(source_code: str) -> str:
    normalized = str(source_code or "unknown").strip().lower()
    if normalized.startswith("distribution_rule_"):
        return "SUBJECT_DISTRIBUTION_VIOLATION"
    if normalized.startswith("teacher_rule_"):
        return "TEACHER_SCHEDULING_RULE_VIOLATION"
    if normalized.startswith("solver_infeasible_locks"):
        return "REGENERATION_LOCK_CONFLICT"
    if normalized.startswith("solver_infeasible_grouped"):
        return "GROUPED_ACTIVITY_VIOLATION"
    if normalized.startswith("solver_infeasible_subject_distribution"):
        return "SUBJECT_DISTRIBUTION_VIOLATION"
    if normalized.startswith("solver_infeasible_teacher_scheduling"):
        return "TEACHER_SCHEDULING_RULE_VIOLATION"
    if normalized.startswith("solver_infeasible_") or normalized in {
        "base", "combined_hard_constraints", "subject_teacher_interaction",
        "diagnostic_inconclusive",
    }:
        return "INFEASIBLE"
    return _CODE_MAP.get(normalized, normalized.upper())


def safe_entity_reference(
    *, kind: str, label: str | None = None, entity_id: int | str | None = None,
    authorized: bool = True,
) -> dict:
    if not authorized:
        return {"kind": str(kind or "entity"), "redacted": True}
    reference = {"kind": str(kind or "entity"), "redacted": False}
    if entity_id is not None:
        reference["id"] = entity_id
    if label:
        reference["label"] = str(label)
    return reference


@dataclass(frozen=True)
class TimetableConflict:
    code: str
    source_code: str
    severity: ConflictSeverity
    evidence_class: EvidenceClass
    message: str
    message_key: str
    entities: tuple[dict, ...] = field(default_factory=tuple)
    slots: tuple[dict, ...] = field(default_factory=tuple)
    remediation: str | None = None
    provenance: str = "timetable_domain"
    requirement_id: str | None = None
    allocation_id: str | int | None = None
    constraint_id: str | int | None = None
    detected_at: str | None = None

    def to_public_dict(self) -> dict:
        payload = {
            "code": self.code,
            "source_code": self.source_code,
            "severity": self.severity,
            "evidence_class": self.evidence_class,
            "message": self.message,
            "message_key": self.message_key,
            "entities": list(self.entities),
            "slots": list(self.slots),
            "provenance": self.provenance,
            "correlation": {
                "requirement": bool(self.requirement_id),
                "allocation": self.allocation_id is not None,
                "constraint": self.constraint_id is not None,
            },
        }
        if self.remediation:
            payload["remediation"] = self.remediation
        if self.detected_at:
            payload["detected_at"] = self.detected_at
        return payload


def conflict_from_legacy(
    source_code: str,
    message: str,
    *,
    severity: ConflictSeverity = "HARD",
    evidence_class: EvidenceClass = "RECALCULABLE",
    entities: list[dict] | None = None,
    slots: list[dict] | None = None,
    remediation: str | None = None,
    provenance: str = "timetable_domain",
    requirement_id: str | None = None,
    allocation_id: str | int | None = None,
    constraint_id: str | int | None = None,
    detected_at: str | None = None,
) -> TimetableConflict:
    source = str(source_code or "unknown").strip().lower()
    return TimetableConflict(
        code=canonical_conflict_code(source),
        source_code=source,
        severity=severity,
        evidence_class=evidence_class,
        message=str(message),
        message_key=f"timetable.conflict.{source}",
        entities=tuple(entities or ()),
        slots=tuple(slots or ()),
        remediation=remediation,
        provenance=provenance,
        requirement_id=requirement_id,
        allocation_id=allocation_id,
        constraint_id=constraint_id,
        detected_at=detected_at,
    )


def durable_terminal_conflict(
    *, status: str, failure_category: str | None, message: str,
    detected_at: datetime | None,
) -> dict | None:
    if status not in {"infeasible", "timed_out", "stale_input", "cancelled", "internal_error"}:
        return None
    source_code = failure_category or status
    timestamp = None
    if detected_at is not None:
        value = detected_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        timestamp = value.isoformat().replace("+00:00", "Z")
    return conflict_from_legacy(
        source_code,
        message or "The timetable operation did not complete.",
        evidence_class="DURABLE",
        provenance="generation_run",
        detected_at=timestamp,
    ).to_public_dict()
