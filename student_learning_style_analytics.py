"""Student Learning Style aggregate distribution (ADR 0031, Acceptance C amendment).

Learning Style is Student-domain learner-profile context: ONE categorical
value per Student (eight approved values) or ``Unassigned``. It is never a
Talent score, and this module never participates in any Talent scoring,
Program Criteria, Review, or Official Identification computation. There is no
per-Student Learning Style percentage; the four ``learning_style_*_percentage``
columns are deprecated and are never read here.

The aggregate distribution is authorized Student-domain profile aggregation,
NOT sensitive Talent scoring/classification output. Deployment Acceptance
Correction C therefore removed the Talent small-cell privacy pipeline
(``talent_analytics_privacy``: primary/complementary suppression) from THIS
distribution only. That pipeline is untouched and remains fully active for
every Classification, Talented, competency, result and organization Talent
metric. What still bounds this distribution is the caller's authorization:
SchoolGroup, Branch and Grade scope and Student visibility are resolved by
``resolve_population`` before anything is counted, and only aggregate counts and
percentages (never Student identity) are returned.

Denominator: every authorized Student in the selected population, INCLUDING
``Unassigned``. A valid category with zero Students is ``0`` / ``0%``.

This lives as a lightweight Students-domain module, not a Talent analytics
route, because its population is "Students in the actor's authorized scope"
and is never filtered by Talent Program/Cycle participation.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import auth
import models
from student_academic_service import list_students

LEARNING_STYLES = (
    "Visual", "Auditory", "Read/Write", "Kinesthetic",
    "Verbal", "Non-verbal", "Quantitative", "Spatial",
)
NOT_SPECIFIED = "not_specified"

# The aggregate distribution's ninth "no value assigned" bucket is labeled
# "Unassigned" and is always part of the denominator, never silently
# excluded, alongside the eight categorical values above.
_LABELS = {**{style: style for style in LEARNING_STYLES}, NOT_SPECIFIED: "Unassigned"}
_ORDER = {key: index for index, key in enumerate((*LEARNING_STYLES, NOT_SPECIFIED))}


def resolve_population(db, *, school_group_id, user, branch_id=None, grade_level=None, section_name=None):
    """The exact authorized Student population for one distribution request.

    Reuses ``student_academic_service.list_students`` - the same query the
    Students list page itself already uses - rather than a parallel query.
    Also enforces Branch scope as defense-in-depth: an explicit ``branch_id``
    must be within the actor's authorized scope (``None`` is returned, never
    raised, so callers can render a 403 the same way sibling placement routes
    already do), and an "Organization"-wide request with no ``branch_id`` is
    restricted to the actor's authorized Branches rather than every Branch in
    the SchoolGroup.
    """
    if branch_id is not None:
        if not auth.can_access_branch(db, user, branch_id):
            return None
        return list_students(
            db, school_group_id=school_group_id, status="active", branch_id=branch_id,
            grade_level=grade_level, section_name=section_name,
        )
    if auth.can_access_all_branches(user):
        return list_students(
            db, school_group_id=school_group_id, status="active",
            grade_level=grade_level, section_name=section_name,
        )
    accessible_ids = [
        row[0] for row in auth.get_accessible_branch_query(db, user)
        .filter(models.Branch.school_group_id == school_group_id).with_entities(models.Branch.id).all()
    ]
    rows = []
    for accessible_branch_id in accessible_ids:
        rows.extend(list_students(
            db, school_group_id=school_group_id, status="active", branch_id=accessible_branch_id,
            grade_level=grade_level, section_name=section_name,
        ))
    return rows


def raw_learning_style_counts(students):
    """Counts keyed by the eight approved values plus ``not_specified``, from an already-authorized/filtered Student iterable.

    Accepts ORM ``Student`` rows or plain dicts exposing ``learning_style``.
    Never itself applies any authorization/branch-scope filtering - callers
    must only pass an already-authorized population.
    """
    counts = {key: 0 for key in (*LEARNING_STYLES, NOT_SPECIFIED)}
    for student in students:
        value = student.get("learning_style") if isinstance(student, dict) else getattr(student, "learning_style", None)
        counts[value if value in LEARNING_STYLES else NOT_SPECIFIED] += 1
    return counts


def _percentage(count, total):
    if not total:
        return None
    return float((Decimal(count) * Decimal(100) / Decimal(total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_distribution(students):
    """Learning Style distribution for one already-authorized Student population.

    Returns ``{"state", "total_population", "total": {"state", "value"},
    "levels": [...]}``. ``levels`` always lists all nine categories in the
    fixed governed order (the eight approved values, then ``Unassigned``);
    each entry is ``{"key", "label", "display_order", "state", "count",
    "percentage"}``. Every percentage uses the same denominator - the whole
    authorized population including Unassigned. ``state`` is ``"visible"``
    for a populated selection and ``"empty"`` when the authorized population
    is 0 (no divide-by-zero; percentages are then ``None``, never a
    misleading ``0%``). No Talent privacy suppression is applied.
    """
    counts = raw_learning_style_counts(students)
    total = sum(counts.values())
    levels = [
        {
            "key": key,
            "label": _LABELS[key],
            "display_order": _ORDER[key],
            "state": "visible",
            "count": counts[key],
            "percentage": _percentage(counts[key], total),
        }
        for key in sorted(counts, key=_ORDER.__getitem__)
    ]
    return {
        "state": "visible" if total else "empty",
        "total_population": total,
        "total": {"state": "visible", "value": total},
        "levels": levels,
    }
