"""M18b-1 Results & Analytics backend contract.

Bounded backend authority for the final Results & Analytics experience
(frontend rebuild is the separate, still-pending M18b-2). This module adds
ONLY the analytics families that did not already have a governed aggregate
backend before this task:

- ``learning_style``  - thin reuse of ``student_learning_style_analytics.py``
  (M14), never a new Learning Style computation.
- ``classification``  - current M17 classification distribution (Needs
  Improvement / Developing / Meets Expectations / Advanced / Exceptional)
  over the exact same "current, applicable result" grain M18a already
  established: ``TalentStudentAssessment.status == 'completed' AND
  is_current == True``, reusing ``talent_classification_service`` for every
  band decision (never a duplicated band table).
- ``talented``        - current Talented (Exceptional-only) count, applicable
  denominator, and rate, derived from the same classification computation.

Contract decision (documented, not silently implied): ``talent_org_intelligence_contract.MetricCode``
is a frozen enum (ADR 0044) whose existing Candidate/Identification-adjacent
codes (``CANDIDATE_COUNT``/``CANDIDATE_OF_ELIGIBLE``/``IDENTIFIED_COUNT``/
``IDENTIFIED_OF_ELIGIBLE``) are grounded in the legacy Review/Identification
membership grain, not the M17 classification grain - so this module
deliberately does NOT extend or repurpose that enum. It instead reuses the
existing M9 ``talent_analytics_service`` Program+AcademicYear context/filter
architecture (``resolve_context``/``resolve_filters``/``population_query``),
the same generic ``Cell``/``Group``/``apply_primary_privacy``/
``run_complementary_suppression`` privacy primitives every M9 breakdown
already uses (never the M10 CellIdentity/MetricCode vocabulary), and adds one
new opaque privacy class (``"P4"``) for this new grain - exactly the
extension mechanism ``talent_analytics_privacy.py`` already documents
privacy classes are designed for ("a future governed setting ... can be
introduced with no metric-code change").

``competency`` (Program-bound competency analytics) and ``progress``
(Evaluation Period/Overall Result analytics) are DELIBERATELY NOT
reimplemented here: ``routers/talent_analytics.py``'s existing
``/rubric-distribution`` route (Section N/P) and
``routers/talent_evaluation_progress.py``'s existing branch/organization/
branch-comparison routes already provide governed, privacy-safe, Program-
bound/Evaluation-Period-bound backend analytics for those two families with
correct semantics (canonical framework/competency identity, ACTIVE/OPENED
weighting). Duplicating them behind this new contract would either
re-implement working logic (risking silent divergence) or thin-wrap it for
no behavioral gain; M18b-2's frontend calls those existing routes directly
for those two families and this new family-1/2/3 route for the rest.

Aggregation authority (the CRITICAL invariant): every Organization-level
count in this module is the raw SQL sum of individual current+completed
Assessment rows across every authorized Branch - never an average of each
Branch's own percentage. ``raw_bucket_counts_by_branch`` groups rows by
Branch; ``sum_raw_counts_across_branches`` (a pure function, independent of
any DB/privacy call) sums each bucket across Branches. There is no code path
anywhere in this module that averages a percentage.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import models
import talent_analytics_service as svc
from talent_analytics_privacy import (
    NO_DATA,
    RESTRICTED,
    VISIBLE,
    apply_primary_privacy,
    run_complementary_suppression,
)
from talent_classification_service import CLASSIFICATION_LABELS, TALENTED_CLASSIFICATION, assessment_classification

CLASSIFICATION_PRIVACY_CLASS = "P4"
TALENTED_NOT_TALENTED = ("talented", "not_talented")

RESULTS_ANALYTICS_FAMILIES = ("learning_style", "classification", "talented")


class ResultsAnalyticsError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Shared "applicable current result" row resolution (Families 2 and 3)
# ---------------------------------------------------------------------------


def applicable_assessment_rows(db, pop_query):
    """The exact M18a-governed current-result grain, scoped to one already-
    filtered population query: ``status == 'completed' AND is_current ==
    True``. Returns ``(branch_id, TalentStudentAssessment)`` pairs. A
    draft/in-progress/incomplete/non-current Assessment is never included -
    this is the ONLY membership predicate this module uses, matching
    ``talent_org_student_drill.py``'s and the M17 authority exactly, never a
    "latest"/"highest" invention.
    """
    base = pop_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"),
        models.TalentAssessmentCyclePopulationMember.branch_id.label("branch_id"),
    ).subquery()
    rows = db.query(base.c.branch_id, models.TalentStudentAssessment).select_from(base).join(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).filter(
        models.TalentStudentAssessment.status == "completed",
        models.TalentStudentAssessment.is_current.is_(True),
    ).all()
    return tuple((int(branch_id), assessment) for branch_id, assessment in rows)


def classify_rows(db, rows):
    """Classify every applicable row exactly once via
    ``talent_classification_service.assessment_classification`` (never a
    duplicated band table). Returns ``(by_branch, unavailable_by_branch)``:
    ``by_branch`` maps ``branch_id -> {classification_label: count}`` for
    every row whose classification is currently available; a row whose
    Program rubric scale is incompatible (``available: False``) is counted
    in ``unavailable_by_branch`` instead of becoming a fabricated
    classification row - it is not part of any classification/Talented
    percentage denominator (the "applicable" population excludes it by
    construction).
    """
    by_branch: dict = defaultdict(lambda: {label: 0 for label in CLASSIFICATION_LABELS})
    unavailable_by_branch: dict = defaultdict(int)
    for branch_id, assessment in rows:
        result = assessment_classification(db, assessment)
        if result and result.get("available"):
            by_branch[branch_id][result["classification"]] += 1
        else:
            unavailable_by_branch[branch_id] += 1
    return dict(by_branch), dict(unavailable_by_branch)


def sum_raw_counts_across_branches(by_branch: dict) -> dict:
    """Pure, DB-independent Organization rollup: sum each bucket across every
    Branch's own raw counts. This is the ONLY Organization aggregation rule
    used anywhere in this module - it is never a mean of Branch percentages.

    Proof case (regression-tested exactly): Branch A talented=1/applicable=2
    (50%), Branch B talented=9/applicable=90 (10%) -> Organization
    talented=10/applicable=92 (~10.87%), NOT the naive average of the two
    Branch rates (30%).
    """
    totals: dict = defaultdict(int)
    for counts in by_branch.values():
        for key, value in counts.items():
            totals[key] += value
    return dict(totals)


def talented_counts_by_branch(by_branch_classification: dict) -> dict:
    """Project the 5-band classification counts down to the 2-bucket
    Talented/not-Talented grain (Exceptional only is Talented) per Branch,
    without re-deriving classification."""
    result = {}
    for branch_id, counts in by_branch_classification.items():
        talented = counts.get(TALENTED_CLASSIFICATION, 0)
        applicable = sum(counts.values())
        result[branch_id] = {"talented": talented, "not_talented": applicable - talented}
    return result


# ---------------------------------------------------------------------------
# Privacy-safe Group projection shared by classification/Talented
# ---------------------------------------------------------------------------


def _percentage(numerator: int, denominator: int) -> Optional[Decimal]:
    if not denominator:
        return None
    return (Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_bucket_projection(*, name: str, raw_counts: dict, policy) -> dict:
    """One privacy-closed categorical distribution (count + backend-derived
    percentage per bucket, denominator explicit), reusing exactly the same
    ``build_breakdown_group``/``apply_primary_privacy``/
    ``run_complementary_suppression`` machinery every other M9 breakdown
    (rubric distribution, Learning Style distribution) already uses. A
    non-visible bucket always carries ``count``/``percentage`` as ``None``.
    """
    total_raw = sum(raw_counts.values())
    group = svc.build_breakdown_group(
        name=name, privacy_class=CLASSIFICATION_PRIVACY_CLASS, total_raw=total_raw, children_raw=raw_counts,
    )
    apply_primary_privacy(group.all_cells(), policy)
    converged = run_complementary_suppression([group], policy)
    if not converged:
        return {"state": RESTRICTED, "total": {"state": RESTRICTED, "value": None}, "buckets": []}
    # ``build_breakdown_group`` sorts children alphabetically by key (correct
    # for the generic rubric-level-id/branch-id breakdowns it also serves,
    # but meaningless for classification bands). Re-order this family's
    # buckets into the owner-approved band order (and the fixed Talented/
    # not-Talented order) rather than publishing an alphabetically-shuffled
    # display order.
    display_order = {label: index for index, label in enumerate((*CLASSIFICATION_LABELS, *TALENTED_NOT_TALENTED))}
    buckets = []
    for cell in group.children:
        key = cell.key[2]
        is_visible = cell.state == VISIBLE and group.total.state == VISIBLE and total_raw
        buckets.append({
            "label": key,
            "state": cell.state,
            "count": cell.value,
            "percentage": float(_percentage(cell.value, total_raw)) if is_visible else None,
        })
    buckets.sort(key=lambda item: display_order.get(item["label"], len(display_order)))
    return {
        "state": group.total.state,
        "total": {"state": group.total.state, "value": group.total.value},
        "buckets": buckets,
    }


def classification_family(db, ctx, filters, visible_branch_ids, policy, *, classification_filter: Optional[str] = None) -> dict:
    """Family 2: current M17 classification distribution for the requested
    Program+AcademicYear+filter scope. ``classification_filter`` (one of
    ``CLASSIFICATION_LABELS``) narrows the returned buckets to a single band
    without changing the shared total/percentage denominator.
    """
    if classification_filter is not None and classification_filter not in CLASSIFICATION_LABELS:
        raise ResultsAnalyticsError("invalid_filter", "classification is not a recognized band.")
    pop_query = svc.population_query(db, ctx, filters, visible_branch_ids)
    rows = applicable_assessment_rows(db, pop_query)
    by_branch, unavailable_by_branch = classify_rows(db, rows)
    org_raw = sum_raw_counts_across_branches(by_branch)
    org_raw = {label: org_raw.get(label, 0) for label in CLASSIFICATION_LABELS}
    projection = build_bucket_projection(name="talent_classification", raw_counts=org_raw, policy=policy)
    if classification_filter is not None:
        projection = {**projection, "buckets": [item for item in projection["buckets"] if item["label"] == classification_filter]}
    return {
        "family": "classification",
        "distribution": projection,
        "not_currently_classifiable_count": sum(unavailable_by_branch.values()),
    }


def talented_family(db, ctx, filters, visible_branch_ids, policy) -> dict:
    """Family 3: current Talented (Exceptional-only) count, applicable
    denominator, and rate. Organization/Branch totals are always the raw sum
    of individual current+completed Assessment rows (see
    ``sum_raw_counts_across_branches``), never an average of Branch rates.
    """
    pop_query = svc.population_query(db, ctx, filters, visible_branch_ids)
    rows = applicable_assessment_rows(db, pop_query)
    by_branch_classification, unavailable_by_branch = classify_rows(db, rows)
    by_branch = talented_counts_by_branch(by_branch_classification)
    org_raw = sum_raw_counts_across_branches(by_branch)
    org_raw = {key: org_raw.get(key, 0) for key in TALENTED_NOT_TALENTED}
    organization = build_bucket_projection(name="talent_talented", raw_counts=org_raw, policy=policy)

    branch_breakdown = []
    if filters.branch_id is None:
        for branch_id in sorted(by_branch):
            branch_raw = {key: by_branch[branch_id].get(key, 0) for key in TALENTED_NOT_TALENTED}
            branch_breakdown.append({
                "branch_id": branch_id,
                "distribution": build_bucket_projection(name=f"talent_talented:{branch_id}", raw_counts=branch_raw, policy=policy),
            })

    def _summary(projection):
        total_visible = projection["total"]["state"] == VISIBLE
        talented_bucket = next((item for item in projection["buckets"] if item["label"] == "talented"), None)
        talented_count = talented_bucket["count"] if talented_bucket and talented_bucket["state"] == VISIBLE else None
        applicable = projection["total"]["value"] if total_visible else None
        rate = float(_percentage(talented_count, applicable)) if (talented_count is not None and applicable) else None
        return {"talented_count": talented_count, "applicable_denominator": applicable, "talented_rate_percentage": rate}

    return {
        "family": "talented",
        "scope": "branch" if filters.branch_id is not None else "organization",
        "organization": {"distribution": organization, "summary": _summary(organization)},
        "branch_breakdown": branch_breakdown,
        "not_currently_classifiable_count": sum(unavailable_by_branch.values()),
    }
