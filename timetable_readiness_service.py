from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

import models
from homeroom_defaults import is_default_homeroom_subject
from subject_distribution_rules import resolve_subject_distribution_rule
from subject_distribution_validator import validate_subject_distribution_rule
from teacher_capacity import get_teacher_international_capacity_hours
from timetable_logic import build_teacher_display_name, format_section_label, get_timetable_settings_payload
from timetable_snapshot_service import build_current_snapshot_data
from timetable_problem_builder import TimetableProblemBuilder, TimetableProblemError
from timetable_conflicts import conflict_from_legacy, safe_entity_reference
from timetable_requirement_projection import project_timetable_lesson_requirements
from timetable_version_service import resolve_operational_version


CONFIGURATION_CODES = {
    "missing_scope", "scope_mismatch", "settings_missing", "working_days_missing",
    "periods_missing", "period_structure_invalid", "invalid_non_teaching_block",
    "no_schedulable_slots", "constraint_configuration_invalid",
}
STALE_CODES = {"input_changed"}


class TimetableReadinessService:
    """Read-only, tenant-scoped structural readiness evaluation.

    Configuration readiness means inputs are coherent enough for a separate
    solver-backed feasibility verification; it is not itself a feasibility claim.
    """

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _finding(code, message, entity_type="timetable", label="Timetable", corrective_area="Timetable Configuration", count=1, requirement_id=None):
        conflict = conflict_from_legacy(
            code, message,
            severity="SOFT" if code == "stale_planning_assignment" else "HARD",
            evidence_class="RECALCULABLE",
            entities=[safe_entity_reference(kind=entity_type, label=label)],
            remediation=corrective_area,
            provenance="readiness",
            requirement_id=requirement_id,
        ).to_public_dict()
        return {
            "code": code,
            "severity": "blocker",
            "message": message,
            "affected_entity_type": entity_type,
            "display_label": label,
            "count": count,
            "corrective_area": corrective_area,
            "conflict": conflict,
        }

    def evaluate(self, school_group_id, branch_id, academic_year_id) -> dict:
        blockers, warnings = [], []
        scope = {
            "school_group_id": school_group_id,
            "branch_id": branch_id,
            "academic_year_id": academic_year_id,
        }
        counts = {
            "eligible_sections": 0, "eligible_demands": 0, "required_periods": 0,
            "covered_periods": 0, "uncovered_periods": 0, "assigned_teachers": 0,
            "available_teaching_slots_per_section": 0, "configured_working_days": 0,
            "configured_teaching_periods": 0, "blocked_slots": 0,
            "stale_placements": 0, "blockers": 0, "warnings": 0,
        }
        authority_fingerprint = ""

        if not all((school_group_id, branch_id, academic_year_id)):
            blockers.append(self._finding("missing_scope", "Select an organization, branch, and academic year to evaluate timetable readiness.", corrective_area="Scope Selection"))
            return self._result(scope, blockers, warnings, counts, authority_fingerprint)

        branch = self.db.query(models.Branch).filter(models.Branch.id == branch_id).first()
        year = self.db.query(models.AcademicYear).filter(models.AcademicYear.id == academic_year_id).first()
        if not branch or not year or int(branch.school_group_id or 0) != int(school_group_id) or int(year.school_group_id or 0) != int(school_group_id):
            blockers.append(self._finding("scope_mismatch", "The selected branch and academic year do not belong to the selected organization.", corrective_area="Scope Selection"))
            return self._result(scope, blockers, warnings, counts, authority_fingerprint)

        settings = get_timetable_settings_payload(self.db, branch_id, academic_year_id)
        projection = settings["slot_projection"]
        pc = projection["counts"]
        counts.update(
            available_teaching_slots_per_section=pc["teaching_slots"],
            configured_working_days=pc["configured_working_days"],
            configured_teaching_periods=pc["configured_periods_per_day"],
            blocked_slots=pc["blocked_slots"] + pc["invalid_slots"],
        )
        if not settings["is_saved"]:
            blockers.append(self._finding("settings_missing", "Save the official timetable configuration for this branch and academic year."))
        if not settings["working_day_keys"]:
            blockers.append(self._finding("working_days_missing", "Select at least one working day in Timetable Configuration."))
        if int(settings["periods_per_day"] or 0) <= 0:
            blockers.append(self._finding("periods_missing", "Configure at least one teaching period per day."))
        for issue in projection["issues"]:
            blockers.append(self._finding(
                issue["code"], issue["message"], "configuration",
                issue.get("display_label") or "Timetable configuration",
            ))
        if pc["teaching_slots"] <= 0:
            blockers.append(self._finding("no_schedulable_slots", "No schedulable teaching slots remain in the configured week."))

        sections = self.db.query(models.PlanningSection).filter(
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == academic_year_id,
            models.PlanningSection.class_status.in_(["Current", "New"]),
        ).order_by(models.PlanningSection.id.asc()).all()
        subjects = self.db.query(models.Subject).filter(
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
        ).order_by(models.Subject.id.asc()).all()
        teachers = self.db.query(models.Teacher).filter(
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == academic_year_id,
        ).all()
        teacher_map = {int(t.id): t for t in teachers}
        subject_by_code = {
            str(subject.subject_code or "").strip().upper(): subject
            for subject in subjects if subject.subject_code
        }
        section_ids = [int(s.id) for s in sections]
        projected_requirements = project_timetable_lesson_requirements(
            self.db, school_group_id=school_group_id,
            branch_id=branch_id, academic_year_id=academic_year_id,
            planning_section_ids=section_ids,
        )
        requirements_by_section = {}
        for requirement in projected_requirements:
            requirements_by_section.setdefault(
                requirement.planning_section_id, []
            ).append(requirement)

        counts["eligible_sections"] = len(sections)
        if not sections:
            blockers.append(self._finding("sections_missing", "No eligible Current or New Planning sections exist in this scope.", "section", "Planning sections", "Planning"))
        if sections and not any(
            requirement.is_schedulable for requirement in projected_requirements
        ):
            blockers.append(self._finding("subjects_missing", "No subjects with positive weekly periods exist for this scope.", "subject", "Subjects", "Planning"))

        teacher_demand = defaultdict(int)
        assigned_teacher_ids = set()
        core_codes = {
            str(code).upper()
            for values in (settings.get("quality_rules", {}).get("core_subject_codes") or {}).values()
            for code in values or []
        }
        teaching_day_count = len(settings.get("working_day_keys") or [])
        for section in sections:
            grade = str(section.grade_level or "").strip().upper()
            if grade in {"K", "KINDERGARTEN", "0"}:
                grade = "KG"
            label = format_section_label(section)
            demands = [
                requirement
                for requirement in requirements_by_section.get(int(section.id), [])
                if requirement.is_schedulable
            ]
            if not demands:
                blockers.append(self._finding("demand_missing", f"{label} has no positive timetable demand.", "section", label, "Planning"))
                continue
            section_demand = 0
            for demand in demands:
                periods = int(demand.required_weekly_periods)
                section_demand += periods
                counts["eligible_demands"] += 1
                counts["required_periods"] += periods
                code = demand.subject_code
                subject = subject_by_code.get(code)
                if subject is None:
                    continue
                subject_label = str(subject.subject_name or code or "Subject").strip()
                distribution_rule = resolve_subject_distribution_rule(
                    self.db, branch_id=branch_id, academic_year_id=academic_year_id,
                    grade_level=grade, subject_code=code, section_id=int(section.id),
                )
                if distribution_rule is not None:
                    for error in validate_subject_distribution_rule(
                        distribution_rule, planning_weekly_periods=periods,
                        available_teaching_days=teaching_day_count,
                    ):
                        blockers.append(self._finding(
                            f"distribution_rule_{error['code']}",
                            f"{label} {subject_label}: {error['message']}",
                            "section_subject", f"{label} {subject_label}", "Timetable Configuration",
                            requirement_id=demand.requirement_id,
                        ))
                elif code in core_codes and periods < teaching_day_count:
                    warnings.append({
                        **self._finding(
                            "core_daily_coverage_impossible",
                            f"{label} {subject_label} has {periods} weekly periods across {teaching_day_count} teaching days; TIS will maximize distinct-day spread instead of requiring daily coverage.",
                            "section_subject", f"{label} {subject_label}", "Timetable Configuration",
                            requirement_id=demand.requirement_id,
                        ),
                        "severity": "warning",
                    })
                teacher_id = demand.assigned_teacher_id
                source = demand.assignment_source
                teacher = teacher_map.get(int(teacher_id or 0))
                if teacher is None:
                    blocker_code = "hrt_assignment_invalid" if source == "homeroom_default" or (source != "planning_invalid" and teacher_id is None and grade in {"1", "2"} and is_default_homeroom_subject(grade, subject_name=subject_label, subject_code=code)) else ("teacher_missing" if source == "planning_invalid" else "allocation_incomplete")
                    blockers.append(self._finding(
                        blocker_code,
                        f"{label} {subject_label} has no valid assigned teacher.",
                        "section_subject", f"{label} {subject_label}", "Planning",
                        requirement_id=demand.requirement_id,
                    ))
                    continue
                counts["covered_periods"] += periods
                assigned_teacher_ids.add(int(teacher.id))
                teacher_demand[int(teacher.id)] += periods
            if section_demand > pc["teaching_slots"]:
                blockers.append(self._finding("section_capacity_insufficient", f"{label} requires {section_demand} periods but only {pc['teaching_slots']} teaching slots are available.", "section", label, "Timetable Configuration"))

        counts["uncovered_periods"] = max(counts["required_periods"] - counts["covered_periods"], 0)
        counts["assigned_teachers"] = len(assigned_teacher_ids)
        for teacher_id, demand in sorted(teacher_demand.items()):
            teacher = teacher_map[teacher_id]
            label = build_teacher_display_name(teacher)
            if demand > pc["teaching_slots"]:
                blockers.append(self._finding("teacher_slot_capacity_insufficient", f"{label} requires {demand} periods but only {pc['teaching_slots']} weekly teaching slots are available.", "teacher", label, "Planning"))
            capacity = get_teacher_international_capacity_hours(teacher)
            if demand > capacity:
                blockers.append(self._finding("teacher_over_capacity", f"{label} is assigned {demand} periods, above the authoritative capacity of {capacity}.", "teacher", label, "Teachers"))

        operational = resolve_operational_version(self.db, school_group_id=school_group_id, branch_id=branch_id, academic_year_id=academic_year_id)
        locks = []
        entries = []
        if operational is not None:
            entries = self.db.query(models.TimetableEntry).filter(models.TimetableEntry.timetable_version_id == operational.id).all()
            locks = [{"section_id": e.planning_section_id, "subject_code": e.subject_code, "teacher_id": e.teacher_id, "day_key": e.day_key, "period_index": e.period_index} for e in entries if e.is_locked]
            occupied = set()
            for lock in locks:
                slot_key = (str(lock["day_key"] or "").lower(), int(lock["period_index"] or 0))
                entity_key = (int(lock["section_id"] or 0), *slot_key)
                teacher_key = (int(lock["teacher_id"] or 0), *slot_key)
                if slot_key not in projection["slot_map"] or not projection["slot_map"][slot_key]["schedulable"]:
                    blockers.append(self._finding("locked_lesson_invalid", "A locked lesson uses an unavailable timetable slot.", "locked_lesson", "Locked lesson", "Timetable"))
                if entity_key in occupied or teacher_key in occupied:
                    blockers.append(self._finding("locked_lesson_conflict", "Two locked lessons collide in the same timetable slot.", "locked_lesson", "Locked lessons", "Timetable"))
                occupied.update({entity_key, teacher_key})

        snapshot = build_current_snapshot_data(self.db, school_group_id=school_group_id, branch_id=branch_id, academic_year_id=academic_year_id, locks=locks)
        authority_fingerprint = snapshot.authority_fingerprint
        try:
            TimetableProblemBuilder().build(snapshot.canonical_json)
        except TimetableProblemError as exc:
            if exc.code.startswith("teacher_rule"):
                details = exc.details or {}
                teacher = teacher_map.get(int(details.get("teacher_id") or 0))
                section = next((
                    item for item in sections
                    if int(item.id) == int(details.get("section_id") or 0)
                ), None)
                labels = []
                if teacher is not None:
                    labels.append(build_teacher_display_name(teacher))
                if section is not None:
                    labels.append(format_section_label(section))
                subject = subject_by_code.get(str(details.get("subject_code") or "").upper())
                if subject is not None:
                    labels.append(str(subject.subject_name or subject.subject_code))
                blockers.append(self._finding(
                    exc.code, exc.message, "teacher_rule",
                    " · ".join(labels) or "Teacher scheduling rule",
                    "Timetable Configuration",
                ))
        if operational is not None and str(operational.authority_fingerprint or "") != authority_fingerprint:
            blockers.append(self._finding("input_changed", "Planning assignments, timetable configuration, or locked lessons changed after the current draft was created.", corrective_area="Timetable"))

        stale = 0
        for entry in entries:
            slot = projection["slot_map"].get((str(entry.day_key or "").lower(), int(entry.period_index or 0)))
            if not slot or not slot["schedulable"]:
                stale += 1
        if stale:
            warnings.append({**self._finding("stale_planning_assignment", f"{stale} existing timetable placement(s) need review after Planning or configuration changes.", "placement", "Existing placements", "Timetable", stale), "severity": "warning"})
        counts["stale_placements"] = stale

        active_runs = self.db.query(models.TimetableGenerationRun).filter(
            models.TimetableGenerationRun.school_group_id == school_group_id,
            models.TimetableGenerationRun.branch_id == branch_id,
            models.TimetableGenerationRun.academic_year_id == academic_year_id,
            models.TimetableGenerationRun.status.in_(["queued", "running", "validating", "cancel_requested"]),
        ).count()
        if active_runs:
            blockers.append(self._finding("active_generation_exists", "An automatic timetable generation run is already active for this scope.", "generation_run", "Generation run", "Timetable"))
        return self._result(scope, blockers, warnings, counts, authority_fingerprint)

    @staticmethod
    def _result(scope, blockers, warnings, counts, authority_fingerprint):
        codes = {item["code"] for item in blockers}
        non_stale_codes = codes - STALE_CODES
        if codes & CONFIGURATION_CODES:
            status = "configuration_incomplete"
        elif non_stale_codes:
            status = "structurally_ready" if non_stale_codes == {"active_generation_exists"} else "allocation_incomplete"
        elif codes & STALE_CODES:
            status = "stale_input"
        else:
            status = "configuration_complete"
        configuration_complete = status in {"configuration_complete", "stale_input"}
        verification_eligible = configuration_complete and not non_stale_codes
        counts["blockers"] = len(blockers)
        counts["warnings"] = len(warnings)
        required = counts["required_periods"]
        counts["coverage_percent"] = round((counts["covered_periods"] / required) * 100) if required else 0
        return {
            "scope": scope, "status": status,
            "ready": status == "configuration_complete",
            "configuration_complete": configuration_complete,
            "verification_eligible": verification_eligible,
            "inputs_stale": bool(codes & STALE_CODES),
            "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "authority_fingerprint": authority_fingerprint,
            "blockers": blockers, "warnings": warnings, "counts": counts,
            "conflicts": [item["conflict"] for item in blockers + warnings],
            "affected_entities": [item["display_label"] for item in blockers],
            "feasibility_notice": "Configuration is complete. Timetable feasibility still needs verification.",
        }
