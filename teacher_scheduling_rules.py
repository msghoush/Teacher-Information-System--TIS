from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

import models
from timetable_logic import build_teacher_display_name, format_section_label, get_timetable_settings_payload
from timetable_version_service import clear_draft_approval


RULE_TYPES = {
    "must_teach": ("Must teach", "hard"),
    "unavailable": ("Unavailable", "hard"),
    "prefer_teaching": ("Prefer teaching", "soft"),
    "prefer_free": ("Prefer free", "soft"),
}
TARGET_SCOPES = {"any_assigned", "selected_grades", "selected_sections"}


class TeacherSchedulingRuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _scope(db: Session, school_group_id: int, branch_id: int, academic_year_id: int) -> None:
    branch = db.query(models.Branch).filter_by(id=branch_id, school_group_id=school_group_id).first()
    year = db.query(models.AcademicYear).filter_by(id=academic_year_id, school_group_id=school_group_id).first()
    if branch is None or year is None:
        raise TeacherSchedulingRuleError("scope_mismatch", "The selected timetable scope is invalid.")


def _serialize_rule(db: Session, rule: models.TeacherSchedulingRule) -> dict:
    slots = db.query(models.TeacherSchedulingRuleSlot).filter_by(rule_id=rule.id).order_by(
        models.TeacherSchedulingRuleSlot.day_key.asc(),
        models.TeacherSchedulingRuleSlot.period_selector.asc(),
        models.TeacherSchedulingRuleSlot.period_index.asc(),
    ).all()
    targets = db.query(models.TeacherSchedulingRuleTarget).filter_by(rule_id=rule.id).order_by(
        models.TeacherSchedulingRuleTarget.target_type.asc(),
        models.TeacherSchedulingRuleTarget.grade_level.asc(),
        models.TeacherSchedulingRuleTarget.planning_section_id.asc(),
    ).all()
    return {
        "id": int(rule.id), "teacher_id": int(rule.teacher_id),
        "rule_type": rule.rule_type, "strictness": rule.strictness,
        "target_scope": rule.target_scope,
        "slots": [{
            "day_key": slot.day_key,
            "period_selector": slot.period_selector,
            "period_index": slot.period_index,
        } for slot in slots],
        "targets": [{
            "target_type": target.target_type,
            "grade_level": target.grade_level,
            "planning_section_id": target.planning_section_id,
        } for target in targets],
    }


def list_rules(db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int) -> list[dict]:
    _scope(db, school_group_id, branch_id, academic_year_id)
    rows = db.query(models.TeacherSchedulingRule).filter_by(
        school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id, is_active=True,
    ).order_by(models.TeacherSchedulingRule.teacher_id, models.TeacherSchedulingRule.id).all()
    return [_serialize_rule(db, row) for row in rows]


def _resolved_slots(rule: dict, working_days: list[str], slots: list[dict]) -> list[tuple[str, int]]:
    by_day = defaultdict(list)
    for slot in slots:
        by_day[str(slot["day_key"]).lower()].append(int(slot["period_index"]))
    resolved = set()
    for item in rule.get("slots") or []:
        days = working_days if item.get("day_key") is None else [str(item["day_key"]).lower()]
        for day in days:
            periods = sorted(by_day.get(day) or [])
            selector = item.get("period_selector")
            if selector == "first" and periods:
                resolved.add((day, periods[0]))
            elif selector == "last" and periods:
                resolved.add((day, periods[-1]))
            elif selector == "period" and int(item.get("period_index") or 0) in periods:
                resolved.add((day, int(item["period_index"])))
    return sorted(resolved, key=lambda value: (working_days.index(value[0]), value[1]))


def canonical_rules(db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int,
                    working_days: list[str], slots: list[dict]) -> list[dict]:
    result = []
    for rule in list_rules(db, school_group_id=school_group_id, branch_id=branch_id,
                           academic_year_id=academic_year_id):
        result.append({**rule, "resolved_slots": [
            {"day_key": day, "period_index": period}
            for day, period in _resolved_slots(rule, working_days, slots)
        ]})
    return result


def save_rule(db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int,
              teacher_id: int, rule_type: str, all_working_days: bool,
              days: list[str], period_selector: str, periods: list[int],
              target_scope: str, grades: list[str], section_ids: list[int],
              actor_user_id: str | None, rule_id: int | None = None) -> models.TeacherSchedulingRule:
    _scope(db, school_group_id, branch_id, academic_year_id)
    if rule_type not in RULE_TYPES:
        raise TeacherSchedulingRuleError("rule_type_invalid", "Choose a valid teacher scheduling rule.")
    if target_scope not in TARGET_SCOPES:
        raise TeacherSchedulingRuleError("target_scope_invalid", "Choose a valid class scope.")
    teacher = db.query(models.Teacher).filter_by(
        id=teacher_id, branch_id=branch_id, academic_year_id=academic_year_id,
    ).first()
    if teacher is None:
        raise TeacherSchedulingRuleError("teacher_scope_mismatch", "The selected teacher is outside this timetable scope.")
    settings = get_timetable_settings_payload(db, branch_id, academic_year_id)
    working_days = list(settings.get("working_day_keys") or [])
    chosen_days = working_days if all_working_days else sorted({str(day).lower() for day in days})
    if not chosen_days or any(day not in working_days for day in chosen_days):
        raise TeacherSchedulingRuleError("days_invalid", "Choose valid working days.")
    if period_selector not in {"period", "first", "last"}:
        raise TeacherSchedulingRuleError("period_selector_invalid", "Choose selected, first, or last periods.")
    valid_periods = {int(slot["period_index"]) for slot in settings["slot_projection"]["slot_map"].values() if slot.get("schedulable")}
    chosen_periods = sorted({int(value) for value in periods if int(value) > 0})
    if period_selector == "period" and (not chosen_periods or any(value not in valid_periods for value in chosen_periods)):
        raise TeacherSchedulingRuleError("periods_invalid", "Choose valid teaching periods.")
    if rule_type == "unavailable" and target_scope != "any_assigned":
        raise TeacherSchedulingRuleError("unavailable_scope_invalid", "Unavailable rules apply to all assigned classes.")
    targets = []
    if target_scope == "selected_grades":
        available = {str(row[0]).strip().upper() for row in db.query(models.PlanningSection.grade_level).filter(
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == academic_year_id,
            models.PlanningSection.class_status.in_(["Current", "New"]),
        ).all()}
        normalized = sorted({str(value).strip().upper() for value in grades if str(value).strip()})
        if not normalized or any(value not in available for value in normalized):
            raise TeacherSchedulingRuleError("grade_scope_invalid", "Choose planned grades in this timetable scope.")
        targets = [("grade", value, None) for value in normalized]
    elif target_scope == "selected_sections":
        selected = sorted({int(value) for value in section_ids})
        rows = db.query(models.PlanningSection).filter(
            models.PlanningSection.id.in_(selected), models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == academic_year_id,
            models.PlanningSection.class_status.in_(["Current", "New"]),
        ).all() if selected else []
        if not selected or {int(row.id) for row in rows} != set(selected):
            raise TeacherSchedulingRuleError("section_scope_invalid", "Choose active Planning sections in this timetable scope.")
        targets = [("section", None, value) for value in selected]

    rule = None
    if rule_id:
        rule = db.query(models.TeacherSchedulingRule).filter_by(
            id=rule_id, school_group_id=school_group_id, branch_id=branch_id,
            academic_year_id=academic_year_id,
        ).first()
        if rule is None:
            raise TeacherSchedulingRuleError("rule_scope_mismatch", "The selected rule was not found in this timetable scope.")
        db.query(models.TeacherSchedulingRuleSlot).filter_by(rule_id=rule.id).delete(synchronize_session=False)
        db.query(models.TeacherSchedulingRuleTarget).filter_by(rule_id=rule.id).delete(synchronize_session=False)
        rule.teacher_id = teacher_id; rule.rule_type = rule_type
        rule.target_scope = target_scope; rule.strictness = RULE_TYPES[rule_type][1]
        rule.updated_by_user_id = actor_user_id; rule.updated_at = datetime.utcnow()
    else:
        rule = models.TeacherSchedulingRule(
            school_group_id=school_group_id, branch_id=branch_id,
            academic_year_id=academic_year_id, teacher_id=teacher_id,
            rule_type=rule_type, target_scope=target_scope,
            strictness=RULE_TYPES[rule_type][1], created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        db.add(rule)
    db.flush()
    day_values = [None] if all_working_days else chosen_days
    selector_periods = chosen_periods if period_selector == "period" else [None]
    for day in day_values:
        for period in selector_periods:
            db.add(models.TeacherSchedulingRuleSlot(
                rule_id=rule.id, day_key=day, period_selector=period_selector,
                period_index=period,
            ))
    for target_type, grade, section_id in targets:
        db.add(models.TeacherSchedulingRuleTarget(
            rule_id=rule.id, branch_id=branch_id, academic_year_id=academic_year_id,
            target_type=target_type, grade_level=grade, planning_section_id=section_id,
        ))
    db.flush()
    _validate_hard_conflicts(db, school_group_id, branch_id, academic_year_id)
    _mark_drafts_stale(db, school_group_id, branch_id, academic_year_id)
    db.commit()
    return rule


def delete_rule(db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int,
                rule_id: int) -> None:
    rule = db.query(models.TeacherSchedulingRule).filter_by(
        id=rule_id, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
    ).first()
    if rule is None:
        raise TeacherSchedulingRuleError("rule_scope_mismatch", "The selected rule was not found in this timetable scope.")
    db.query(models.TeacherSchedulingRuleSlot).filter_by(rule_id=rule.id).delete(synchronize_session=False)
    db.query(models.TeacherSchedulingRuleTarget).filter_by(rule_id=rule.id).delete(synchronize_session=False)
    db.delete(rule)
    _mark_drafts_stale(db, school_group_id, branch_id, academic_year_id)
    db.commit()


def _validate_hard_conflicts(db: Session, school_group_id: int, branch_id: int, academic_year_id: int) -> None:
    settings = get_timetable_settings_payload(db, branch_id, academic_year_id)
    projection = settings["slot_projection"]
    slots = [{"day_key": key[0], "period_index": key[1]} for key, value in projection["slot_map"].items() if value.get("schedulable")]
    rules = canonical_rules(db, school_group_id=school_group_id, branch_id=branch_id,
                            academic_year_id=academic_year_id,
                            working_days=settings.get("working_day_keys") or [], slots=slots)
    by_teacher_slot = defaultdict(list)
    for rule in rules:
        if rule["strictness"] == "hard":
            for slot in rule["resolved_slots"]:
                by_teacher_slot[(rule["teacher_id"], slot["day_key"], slot["period_index"])].append(rule)
    for grouped in by_teacher_slot.values():
        types = {item["rule_type"] for item in grouped}
        must = [item for item in grouped if item["rule_type"] == "must_teach"]
        if "must_teach" in types and "unavailable" in types:
            raise TeacherSchedulingRuleError("hard_rule_conflict", "A teacher cannot be both required and unavailable in the same period.")
        section_sets = [{target["planning_section_id"] for target in item["targets"] if target["target_type"] == "section"} for item in must if item["target_scope"] == "selected_sections"]
        if len(section_sets) > 1 and not set.intersection(*section_sets):
            raise TeacherSchedulingRuleError("hard_rule_conflict", "A teacher cannot be required in different sections in the same period.")


def _mark_drafts_stale(db: Session, school_group_id: int, branch_id: int, academic_year_id: int) -> None:
    drafts = db.query(models.TimetableVersion).filter_by(
        school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
    ).filter(
        models.TimetableVersion.lifecycle_status.in_(["draft", "publication_ready"]),
        models.TimetableVersion.published_at.is_(None),
    ).all()
    for draft in drafts:
        draft.is_stale = True
        draft.stale_reason_json = '["teacher_scheduling_rules_changed"]'
        clear_draft_approval(draft)
        draft.updated_at = datetime.utcnow()


def ui_context(db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int) -> dict:
    teachers = db.query(models.Teacher).filter_by(branch_id=branch_id, academic_year_id=academic_year_id).order_by(
        models.Teacher.first_name, models.Teacher.last_name,
    ).all()
    sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
        models.PlanningSection.class_status.in_(["Current", "New"]),
    ).order_by(models.PlanningSection.grade_level, models.PlanningSection.section_name).all()
    rules = list_rules(db, school_group_id=school_group_id, branch_id=branch_id,
                       academic_year_id=academic_year_id)
    teacher_map = {int(row.id): build_teacher_display_name(row) for row in teachers}
    section_map = {int(row.id): format_section_label(row) for row in sections}
    for rule in rules:
        rule["edit_payload"] = {
            key: rule[key] for key in (
                "id", "teacher_id", "rule_type", "target_scope", "slots", "targets"
            )
        }
        rule["teacher_name"] = teacher_map.get(rule["teacher_id"], "Teacher")
        rule["type_label"] = RULE_TYPES[rule["rule_type"]][0]
        rule["scope_label"] = {
            "any_assigned": "Any assigned class", "selected_grades": "Selected grades",
            "selected_sections": "Selected sections",
        }[rule["target_scope"]]
        rule["target_labels"] = [
            (f"Grade {target['grade_level']}" if target["target_type"] == "grade" else section_map.get(int(target["planning_section_id"]), "Section"))
            for target in rule["targets"]
        ]
    return {
        "teacher_scheduling_rules": rules,
        "teacher_rule_teachers": [{"id": int(row.id), "name": teacher_map[int(row.id)]} for row in teachers],
        "teacher_rule_sections": [{"id": int(row.id), "label": section_map[int(row.id)], "grade": str(row.grade_level)} for row in sections],
        "teacher_rule_grades": sorted({str(row.grade_level) for row in sections}),
    }
