"""Student Learning Style V1 aggregate distribution (ADR 0031).

Learning Style is Student-domain learner-profile context, never a Talent
score, and this module never participates in any Talent scoring, Program
Criteria, Review, or Official Identification computation. Its aggregate
distribution nonetheless carries the same "a visible total plus all-but-one
visible sibling reconstructs the suppressed sibling" risk any small-cohort
categorical breakdown does, so this module reuses the exact governed privacy
primitives Talent analytics already uses - ``talent_analytics_privacy.py``'s
``Cell``/``Group``/``apply_primary_privacy``/``run_complementary_suppression``,
plus ``talent_analytics_service.build_breakdown_group``/``percentage`` - the
same way ``routers/talent_analytics.py``'s rubric-distribution route already
does for a structurally identical "one Group, total = sum(children)"
breakdown. There is no separate or weaker suppression rule here.

This lives as a lightweight Students-domain module, not a Talent analytics
route, because its population is "Students with a current effective academic
placement in the actor's authorized scope" and is never filtered by Talent
Program/Cycle participation - unlike every existing Talent analytics metric,
which is Program/Cycle-scoped by construction.
"""

from __future__ import annotations

import auth
import models
from student_academic_service import list_students
from talent_analytics_privacy import apply_primary_privacy, run_complementary_suppression
from talent_analytics_service import build_breakdown_group, percentage

LEARNING_STYLES = ("Visual", "Auditory", "Read/Write", "Kinesthetic")
NOT_SPECIFIED = "not_specified"

_LABELS = {**{style: style for style in LEARNING_STYLES}, NOT_SPECIFIED: "Not specified"}
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
    """Raw (pre-privacy) counts keyed by the four approved values plus
    ``not_specified``, from an already-authorized/filtered Student iterable.

    Accepts ORM ``Student`` rows or plain dicts exposing ``learning_style``.
    Never itself applies any authorization/branch-scope filtering - callers
    must only pass an already-authorized population.
    """
    counts = {key: 0 for key in (*LEARNING_STYLES, NOT_SPECIFIED)}
    for student in students:
        value = student.get("learning_style") if isinstance(student, dict) else getattr(student, "learning_style", None)
        counts[value if value in LEARNING_STYLES else NOT_SPECIFIED] += 1
    return counts


def build_distribution(students, policy):
    """Privacy-safe Learning Style distribution for one already-authorized
    Student population.

    Returns ``{"state", "total": {"state", "value"}, "levels": [...]}``.
    ``levels`` entries are ``{"label", "display_order", "state", "count",
    "percentage"}`` - a non-``visible`` entry always carries ``count`` and
    ``percentage`` as ``None`` (never a hidden magnitude behind a visible
    percentage/tooltip/ordering). When complementary suppression does not
    converge to a safe fixed point, this fails closed to ``state:
    "restricted"`` with no per-level data at all, exactly like the existing
    rubric-distribution route.
    """
    counts = raw_learning_style_counts(students)
    total_raw = sum(counts.values())
    group = build_breakdown_group(
        name="student_learning_style", privacy_class="P3", total_raw=total_raw, children_raw=counts,
    )
    apply_primary_privacy(group.all_cells(), policy)
    converged = run_complementary_suppression([group], policy)
    if not converged:
        return {"state": "restricted", "total": None, "levels": []}
    levels = []
    for cell in group.children:
        key = cell.key[2]
        is_visible = cell.state == "visible" and group.total.state == "visible" and total_raw
        levels.append({
            "label": _LABELS[key],
            "display_order": _ORDER[key],
            "state": cell.state,
            "count": cell.value,
            "percentage": float(percentage(cell.value, total_raw)) if is_visible else None,
        })
    levels.sort(key=lambda item: item["display_order"])
    return {
        "state": group.total.state,
        "total": {"state": group.total.state, "value": group.total.value},
        "levels": levels,
    }
