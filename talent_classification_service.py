"""M17 automatic Assessment classification (ADR 0037, 2026-09-23 amendment).

Governed, backend-authoritative projection of the ADR 0037 raw Overall
Program Result (an arithmetic mean of ordered rubric ranks on a Talent
Program's own 1..N rubric scale, where N is that Program's configured
rubric level count) onto one owner-approved fixed 1.00-5.00 classification
scale, and the deterministic classification of that projected score into
exactly one of five owner-approved bands:

    1.00-1.99 Needs Improvement
    2.00-2.99 Developing
    3.00-3.74 Meets Expectations
    3.75-4.49 Advanced
    4.50-5.00 Exceptional

Only "Exceptional" is Talented. This module never converts the bands to a
percentage, never reuses ``normalized_percent`` as the classification input,
never lets a rubric with an incompatible scale silently classify, and never
lets AI or the frontend decide a Student's classification - the backend is
the single classification authority.

Architecture decision (Part 1 of the M17 task): Real configured Talent
Programs in this repository do not universally use a five-level rubric
scale (see ``talent_local_test_data.py``'s realistic seed dataset, which
configures 4-level, 3-level, and 4-level Program rubrics side by side, all
built through the real ``talent_program_service`` contracts). ADR 0037 also
frames "a five-level Program" as one worked example only and expresses its
own ``normalized_percent`` presentation projection with ``scale_max`` as a
variable, not a constant. Mandating a system-wide five-level rubric
(Option A) would therefore be a breaking change to existing, real Program
configurations, not a small formalization. This module instead implements
Option B: it preserves each Program's own configured rubric-level count for
the educational raw result (ADR 0037's arithmetic-mean rubric rank is
unchanged) and adds one additional, separately governed deterministic
linear projection from that raw 1..N average onto the fixed 1.00-5.00
classification scale, reusing the same linear-rescale technique ADR 0037
already approves for ``normalized_percent`` (``average / scale_max * 100``)
but targeting the classification range instead of a percentage.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from talent_student_assessment_service import overall_program_result

CLASSIFICATION_SCALE_MIN = Decimal("1.00")
CLASSIFICATION_SCALE_MAX = Decimal("5.00")

TALENTED_CLASSIFICATION = "Exceptional"

PROJECTION_METHOD = "linear_scale_projection_1_5"

# Exact, non-overlapping, gap-free owner-approved bands. Ordered low to high.
_BANDS = (
    (Decimal("1.00"), Decimal("1.99"), "Needs Improvement"),
    (Decimal("2.00"), Decimal("2.99"), "Developing"),
    (Decimal("3.00"), Decimal("3.74"), "Meets Expectations"),
    (Decimal("3.75"), Decimal("4.49"), "Advanced"),
    (Decimal("4.50"), Decimal("5.00"), "Exceptional"),
)

# M18b-1: the exact ordered canonical label set, exposed read-only so a
# caller (e.g. ``talent_results_analytics_service.py``'s classification/
# Talented aggregation) can build an aggregation bucket set without
# hardcoding/duplicating the owner-approved band labels above.
CLASSIFICATION_LABELS = tuple(label for _, _, label in _BANDS)


class TalentClassificationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def classify_score(score) -> str:
    """Classify a 1.00-5.00 Decimal score into its owner-approved fixed band.

    Never a percentage conversion. Fails closed (raises) for any value below
    1.00 or above 5.00 rather than guessing or clamping into a band.
    """
    if not isinstance(score, Decimal):
        score = Decimal(str(score))
    if score < CLASSIFICATION_SCALE_MIN or score > CLASSIFICATION_SCALE_MAX:
        raise TalentClassificationError(
            "score_out_of_range",
            "Classification score must be between 1.00 and 5.00.",
        )
    for low, high, label in _BANDS:
        if low <= score <= high:
            return label
    raise TalentClassificationError(
        "unclassifiable_score", "Classification score did not match any governed band."
    )


def is_talented(classification) -> bool:
    return classification == TALENTED_CLASSIFICATION


def project_to_classification_scale(average_tenths: int, scale_min: int, scale_max: int):
    """Deterministic linear projection of the ADR 0037 raw 1..N rubric-rank
    average onto the governed 1.00-5.00 classification scale.

    Computed with exact ``Decimal`` arithmetic directly from the integer
    ``average_tenths`` value already produced by ``overall_program_result``
    (never a second float division of the already-rounded ``average``), and
    rounded deterministically half-up to two decimal places.

    Returns ``None`` when the Program's rubric scale cannot be projected
    deterministically - currently only a degenerate single-level rubric
    (``scale_max <= scale_min``, no discriminating range). The caller must
    treat ``None`` as "this Program's rubric scale is not compatible with
    automatic classification" and fail closed rather than guess.
    """
    if scale_min is None or scale_max is None or scale_max <= scale_min:
        return None
    average = Decimal(average_tenths) / Decimal(10)
    span = Decimal(scale_max - scale_min)
    projected = Decimal(1) + (average - Decimal(scale_min)) * Decimal(4) / span
    quantized = projected.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Defensive boundary clamp only: the affine map is monotonic and bounded
    # by construction for average in [scale_min, scale_max]; this guards the
    # exact 2-decimal rounding at the extremes deterministically.
    if quantized < CLASSIFICATION_SCALE_MIN:
        quantized = CLASSIFICATION_SCALE_MIN
    if quantized > CLASSIFICATION_SCALE_MAX:
        quantized = CLASSIFICATION_SCALE_MAX
    return quantized


_OVERALL_NOT_SUPPLIED = object()


def assessment_classification(db, assessment, *, overall=_OVERALL_NOT_SUPPLIED):
    """Backend-authoritative classification for one Student Assessment.

    ``overall`` may carry the ``overall_program_result(db, assessment)`` value
    the caller has already computed for this exact Assessment (M18b-3: the
    Student Drill row loop), so it is not recomputed a second time per row.
    Omitting it keeps the original behavior of computing it here.

    Returns ``None`` when the Assessment is not Completed - a draft/in
    progress Assessment never carries a final automatic classification.
    Returns a bounded dict for a Completed Assessment; check ``available``
    for whether this Program's rubric scale currently supports automatic
    classification (an inconsistent-scale or single-level rubric does not).
    """
    if assessment is None or assessment.status != "completed":
        return None
    if overall is _OVERALL_NOT_SUPPLIED:
        overall = overall_program_result(db, assessment)
    if not overall or overall.get("available") is False:
        return {
            "available": False,
            "reason": (overall or {}).get("reason", "overall_result_unavailable"),
            "classification": None,
            "classification_score": None,
            "is_talented": False,
        }
    scale_min = overall["scale_min"]
    scale_max = overall["scale_max"]
    projected = project_to_classification_scale(overall["average_tenths"], scale_min, scale_max)
    if projected is None:
        return {
            "available": False,
            "reason": "incompatible_rubric_scale",
            "classification": None,
            "classification_score": None,
            "is_talented": False,
            "scale_min": scale_min,
            "scale_max": scale_max,
        }
    classification = classify_score(projected)
    return {
        "available": True,
        "classification_score": str(projected),
        "classification": classification,
        "is_talented": is_talented(classification),
        "scale_min": scale_min,
        "scale_max": scale_max,
        "projection_method": PROJECTION_METHOD,
    }
