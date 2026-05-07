"""
Auto-match logic for assigning sections to teachers based on their major specialization.

This module implements the strict major-to-pool-to-priority rules for auto-matching
sections to newly added teachers based on their qualifications/degree major.
"""
import logging
from typing import Optional, Dict, List, Set, Tuple
from sqlalchemy.orm import Session

import models
from main import (
    _resolve_teacher_major_priority_rule,
    _normalize_alignment_text,
    _detect_hiring_subject_family,
    HIRING_POOL_FAMILY_ORDER,
    HIRING_COMPATIBILITY_GROUPS,
    HIRING_NAMED_POOL_KEYS,
    _build_teacher_display_name,
)
from teacher_capacity import (
    build_capacity_breakdown,
    STANDARD_MAX_HOURS,
)
from teacher_qualifications import get_qualification_lookup

logger = logging.getLogger("uvicorn.error")


def _get_uncovered_planning_sections(
    db: Session,
    branch_id: int,
    academic_year_id: int,
    subject_code: str,
) -> List[Dict]:
    """
    Find all planning sections that don't have a teacher assigned for a specific subject.
    
    Returns list of dicts with: planning_section_id, grade_level, section_name, class_label
    """
    from sqlalchemy import and_, func
    
    # Get all planning sections
    all_sections = (
        db.query(models.PlanningSection)
        .filter(
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == academic_year_id,
        )
        .all()
    )
    
    # Get planning sections that have timetable entries for this subject with a teacher
    covered_section_ids = (
        db.query(models.TimetableEntry.planning_section_id)
        .filter(
            models.TimetableEntry.branch_id == branch_id,
            models.TimetableEntry.academic_year_id == academic_year_id,
            models.TimetableEntry.subject_code == subject_code.upper(),
            models.TimetableEntry.teacher_id.isnot(None),
        )
        .distinct()
        .all()
    )
    covered_ids = {row[0] for row in covered_section_ids}
    
    # Build list of uncovered sections
    uncovered = []
    for section in all_sections:
        if section.id not in covered_ids:
            uncovered.append({
                "planning_section_id": section.id,
                "grade_level": section.grade_level,
                "section_name": section.section_name,
                "class_label": f"{section.grade_level}-{section.section_name}",
                "class_status": section.class_status,
            })
    
    return uncovered


def _get_subject_info(
    db: Session,
    branch_id: int,
    academic_year_id: int,
    subject_code: str,
) -> Optional[Dict]:
    """Get subject information including weekly hours."""
    subject = (
        db.query(models.Subject)
        .filter(
            models.Subject.subject_code == subject_code,
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
        )
        .first()
    )
    
    if not subject:
        return None
    
    return {
        "subject_code": subject_code,
        "subject_name": subject.subject_name or subject_code,
        "weekly_hours": int(getattr(subject, "weekly_hours", 0) or 1),
    }


def generate_auto_match_suggestions(
    db: Session,
    branch_id: int,
    academic_year_id: int,
    qualification_keys: List[str],
    max_hours: int = STANDARD_MAX_HOURS,
    extra_hours_allowed: bool = False,
    extra_hours_count: int = 0,
    national_section_hours: int = 0,
    teachers_national_section: bool = False,
) -> Dict:
    """
    Generate auto-match section assignment suggestions for a new teacher based on their qualifications.
    
    This implements the strict major-to-pool-to-priority rules from the requirements:
    - Determines which pool based on teacher major
    - Assigns from primary subject first, only moving to secondary when primary is consumed
    - Returns real planning_section_ids that should be assigned
    
    Args:
        db: Database session
        branch_id: Current branch
        academic_year_id: Current academic year
        qualification_keys: List of qualification keys selected for teacher
        max_hours: Teacher's max capacity
        extra_hours_allowed: Whether extra hours are enabled
        extra_hours_count: Extra hours allowed
        national_section_hours: Hours for national section
        teachers_national_section: Whether teacher teaches national section
    
    Returns:
        Dict with:
        - ok: bool (success indicator)
        - major_text: str (resolved major from qualifications)
        - rule_key: str (major priority rule key)
        - pool_key: str (matched pool)
        - primary_family: str (priority subject family)
        - family_priority: List[str] (priority order within pool)
        - suggestions: List[Dict] with section assignments and details
        - total_hours: int (total hours of suggestions)
        - remaining_capacity: int (remaining hours after suggestions)
        - debug_log: List[str] (debug information)
    """
    debug_log = []
    suggestions = []
    
    try:
        # Build teacher major text from qualifications
        qualification_lookup = get_qualification_lookup(db)
        major_texts = []
        for qual_key in qualification_keys:
            qual = qualification_lookup.get(qual_key, {})
            if qual and qual.get("specialization"):
                major_texts.append(qual["specialization"])
        
        teacher_major_text = " ".join(major_texts) if major_texts else ""
        debug_log.append(f"Resolved major from {len(qualification_keys)} qualifications: '{teacher_major_text}'")
        
        # Resolve major priority rule
        major_priority_rule = _resolve_teacher_major_priority_rule(teacher_major_text)
        rule_key = major_priority_rule.get("rule_key", "generic_major_match")
        pool_key = major_priority_rule.get("pool_key", "")
        family_priority = major_priority_rule.get("family_priority", [])
        
        debug_log.append(f"Applied rule: {rule_key}")
        if pool_key:
            debug_log.append(f"Matched pool: {pool_key}")
        if family_priority:
            debug_log.append(f"Family priority order: {' → '.join(family_priority)}")
        
        # Calculate available capacity
        capacity_breakdown = build_capacity_breakdown(
            max_hours,
            extra_hours_allowed=extra_hours_allowed,
            extra_hours_count=extra_hours_count or 0,
            teaches_national_section=teachers_national_section,
            national_section_hours=national_section_hours or 0,
            default_max_hours=STANDARD_MAX_HOURS,
        )
        available_capacity_hours = capacity_breakdown["international_capacity_hours"]
        debug_log.append(f"Teacher capacity: {available_capacity_hours}h (max: {max_hours}h)")
        
        # If no pool matched, return empty suggestions
        if not pool_key:
            debug_log.append("No specific pool matched - generic major alignment")
            return {
                "ok": True,
                "major_text": teacher_major_text,
                "rule_key": rule_key,
                "pool_key": "",
                "primary_family": "",
                "family_priority": [],
                "suggestions": [],
                "total_hours": 0,
                "remaining_capacity": available_capacity_hours,
                "debug_log": debug_log,
            }
        
        # Get subjects for this pool, in priority order
        pool_subjects = HIRING_POOL_FAMILY_ORDER.get(pool_key, [])
        if not pool_subjects:
            debug_log.append(f"Pool {pool_key} has no subjects defined")
            return {
                "ok": True,
                "major_text": teacher_major_text,
                "rule_key": rule_key,
                "pool_key": pool_key,
                "primary_family": family_priority[0] if family_priority else "",
                "family_priority": family_priority,
                "suggestions": [],
                "total_hours": 0,
                "remaining_capacity": available_capacity_hours,
                "debug_log": debug_log,
            }
        
        # Query all subjects for this branch/year to map families to codes
        subjects = (
            db.query(models.Subject)
            .filter(
                models.Subject.branch_id == branch_id,
                models.Subject.academic_year_id == academic_year_id,
            )
            .all()
        )
        
        family_to_subject_codes: Dict[str, List[str]] = {}
        for subject in subjects:
            family = _detect_hiring_subject_family({
                "subject_name": subject.subject_name,
                "subject_code": subject.subject_code,
            })
            if family in pool_subjects:
                family_to_subject_codes.setdefault(family, []).append(subject.subject_code)
        
        debug_log.append(f"Found {len(subjects)} subjects in branch/year")
        debug_log.append(f"Subject families in pool: {dict(family_to_subject_codes)}")
        
        # Apply strict priority: assign from primary family first
        remaining_hours = available_capacity_hours
        processed_families = set()
        
        for priority_index, family in enumerate(family_priority):
            if remaining_hours <= 0:
                debug_log.append("Capacity reached, stopping section assignment")
                break
            
            if family not in family_to_subject_codes:
                debug_log.append(f"Priority {priority_index + 1}: {family} - no subjects found")
                continue
            
            is_primary = priority_index == 0
            debug_log.append(
                f"Priority {priority_index + 1}: {family} {'(PRIMARY)' if is_primary else '(secondary)'}"
            )
            
            # For primary family, assign ALL uncovered sections before moving to secondary
            # For secondary families, fill remaining capacity
            subject_codes_for_family = family_to_subject_codes[family]
            
            for subject_code in sorted(subject_codes_for_family):
                if remaining_hours <= 0:
                    break
                
                # Get uncovered sections for this subject
                uncovered_sections = _get_uncovered_planning_sections(
                    db, branch_id, academic_year_id, subject_code
                )
                
                if not uncovered_sections:
                    debug_log.append(f"  {subject_code}: no uncovered sections")
                    continue
                
                subject_info = _get_subject_info(
                    db, branch_id, academic_year_id, subject_code
                )
                if not subject_info:
                    debug_log.append(f"  {subject_code}: subject not found")
                    continue
                
                weekly_hours = subject_info["weekly_hours"]
                max_sections = int(remaining_hours // weekly_hours)
                
                if max_sections <= 0:
                    debug_log.append(
                        f"  {subject_code}: {len(uncovered_sections)} uncovered, "
                        f"but remaining capacity ({remaining_hours}h) < weekly hours ({weekly_hours}h)"
                    )
                    continue
                
                # Assign sections
                sections_to_assign = uncovered_sections[:max_sections]
                assigned_hours = len(sections_to_assign) * weekly_hours
                
                debug_log.append(
                    f"  {subject_code}: assigning {len(sections_to_assign)}/{len(uncovered_sections)} "
                    f"uncovered sections = {assigned_hours}h"
                )
                
                for section in sections_to_assign:
                    suggestions.append({
                        "planning_section_id": section["planning_section_id"],
                        "subject_code": subject_code,
                        "subject_name": subject_info["subject_name"],
                        "class_label": section["class_label"],
                        "family": family,
                        "is_primary": is_primary,
                        "weekly_hours": weekly_hours,
                    })
                
                remaining_hours -= assigned_hours
            
            processed_families.add(family)
        
        total_hours = available_capacity_hours - remaining_hours
        debug_log.append(f"Auto-match complete: {total_hours}h assigned, {remaining_hours}h remaining")
        
        return {
            "ok": True,
            "major_text": teacher_major_text,
            "rule_key": rule_key,
            "pool_key": pool_key,
            "primary_family": family_priority[0] if family_priority else "",
            "family_priority": family_priority,
            "suggestions": suggestions,
            "total_hours": total_hours,
            "remaining_capacity": remaining_hours,
            "debug_log": debug_log,
        }
    
    except Exception as e:
        logger.exception("Error generating auto-match suggestions")
        return {
            "ok": False,
            "error": str(e),
            "debug_log": debug_log,
        }
