"""M9 deterministic Talent analytics privacy policy foundation.

This module implements ONLY the provider/interface boundary and the
result-set-level complementary suppression engine (Section G/J of the M9
brief). No production privacy threshold is approved in this milestone: there
is no constant cohort threshold, no fallback 5/10, and no permissive
"AllowAll" default active outside explicit test injection anywhere in this
module. ``resolve_privacy_policy_provider`` intentionally returns ``None`` in
production so an unconfigured runtime fails closed
(``analytics_query_failed``) rather than emitting analytics under an implicit
fallback; see ``routers/talent_analytics.py`` for the fail-closed wiring.

Privacy classes P1-P7 are opaque strings threaded through every policy call
(never hardcoded per-metric logic) so a future governed setting for P5
(Candidate), P6 (Identification), or P7 (Student-identifiable rows) can be
introduced with no metric-code change.

Privacy states are preserved exactly and never collapsed:
``visible`` / ``suppressed`` / ``coarsened`` / ``restricted`` / ``no_data``.
A suppressed/restricted/coarsened cell's ``value`` is always ``None`` -
nothing hidden ever survives into a serialized numeric field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


PRIVACY_CLASSES = ("P1", "P2", "P3", "P4", "P5", "P6", "P7")

VISIBLE = "visible"
SUPPRESSED = "suppressed"
COARSENED = "coarsened"
RESTRICTED = "restricted"
NO_DATA = "no_data"

_HIDDEN_STATES = (SUPPRESSED, COARSENED, RESTRICTED)

# Structural-only ordering of privacy classes for the Section J tie-break
# (priority 1: sensitivity class). This is an identity ordering, never a
# magnitude/value-based decision. P7 (Student-identifiable) sorts as most
# sensitive, P1 (planning/execution) as least.
_CLASS_ORDER = {klass: index for index, klass in enumerate(PRIVACY_CLASSES)}


@dataclass(frozen=True)
class PrivacyDecision:
    """One policy decision for a single cell.

    ``value`` serves two distinct, mutually-exclusive purposes depending on
    ``state``:

    - ``visible``: the raw value, published as-is.
    - ``coarsened``: an explicit safe replacement aggregate supplied by the
      policy itself (never computed by this module). This is the ONLY way a
      ``coarsened`` decision can carry a publishable value - M9 implements no
      generic bucket-merge/coarsening algorithm. A policy that requests
      ``coarsened`` without a usable replacement here is treated as a fail-
      closed authoring error by ``apply_primary_privacy``, which downgrades
      the decision to ``suppressed`` rather than publishing a fake
      "coarsened" cell with a null value.
    - every other state (``suppressed``/``restricted``/``no_data``): ``value``
      is ignored and always serialized as ``None``.
    """

    state: str
    value: Optional[int] = None
    reason_code: Optional[str] = None


class TalentAnalyticsPrivacyPolicy:
    """Abstract provider interface. No concrete production implementation
    exists in this codebase yet - see module docstring."""

    privacy_policy_version: str = "unversioned"

    def evaluate_cell(
        self,
        *,
        privacy_class: str,
        raw_value: Optional[int],
        denominator: Optional[int] = None,
        context: Optional[dict] = None,
    ) -> PrivacyDecision:
        raise NotImplementedError

    def prefers_coarsening(self, *, privacy_class: str) -> bool:
        """Structural, class-level strategy preference only (Section J
        tie-break priority 3) - never a value-based decision."""
        return False


class AllowAllTestPolicy(TalentAnalyticsPrivacyPolicy):
    """Test-only policy that never suppresses. For tests that exercise
    metric/derivation correctness without suppression mechanics."""

    def __init__(self, *, version: str = "test-allow-all-v1"):
        self.privacy_policy_version = version

    def evaluate_cell(self, *, privacy_class, raw_value, denominator=None, context=None):
        if raw_value is None:
            return PrivacyDecision(NO_DATA)
        return PrivacyDecision(VISIBLE, value=int(raw_value))


class DeterministicSuppressionTestPolicy(TalentAnalyticsPrivacyPolicy):
    """Test-only policy with an explicit, hand-calculable threshold.

    This threshold exists ONLY as a test fixture for suppression-mechanics
    tests; it is not, and must never become, a production default. A
    ``None`` raw value is ``no_data``; a raw value strictly below
    ``minimum_cohort`` is ``suppressed``; everything else is ``visible``.
    """

    def __init__(
        self,
        *,
        minimum_cohort: int,
        version: str = "test-deterministic-v1",
        prefer_coarsen_classes: frozenset = frozenset(),
    ):
        self.minimum_cohort = minimum_cohort
        self.privacy_policy_version = version
        self._prefer_coarsen_classes = prefer_coarsen_classes

    def evaluate_cell(self, *, privacy_class, raw_value, denominator=None, context=None):
        if raw_value is None:
            return PrivacyDecision(NO_DATA)
        if raw_value < self.minimum_cohort:
            return PrivacyDecision(SUPPRESSED, reason_code="below_minimum_cohort")
        return PrivacyDecision(VISIBLE, value=int(raw_value))

    def prefers_coarsening(self, *, privacy_class):
        return privacy_class in self._prefer_coarsen_classes


class CoarsenWithReplacementTestPolicy(TalentAnalyticsPrivacyPolicy):
    """Test-only policy that requests ``coarsened`` with an explicit safe
    replacement value whenever ``raw_value`` is below ``minimum_cohort``,
    instead of fully suppressing it.

    This exists ONLY to exercise the real-replacement ``coarsened`` plumbing
    (Section G of the M9 remediation brief); it is not a production
    coarsening/bucket-merge algorithm. The replacement is a fixed,
    provider-supplied sentinel (``replacement_value``) that is never derived
    from ``raw_value`` - a real production policy would supply its own
    governed safe aggregate the same way.
    """

    def __init__(
        self,
        *,
        minimum_cohort: int,
        replacement_value: int = 0,
        version: str = "test-coarsen-with-replacement-v1",
    ):
        self.minimum_cohort = minimum_cohort
        self.replacement_value = replacement_value
        self.privacy_policy_version = version

    def evaluate_cell(self, *, privacy_class, raw_value, denominator=None, context=None):
        if raw_value is None:
            return PrivacyDecision(NO_DATA)
        if raw_value < self.minimum_cohort:
            return PrivacyDecision(COARSENED, value=self.replacement_value, reason_code="below_minimum_cohort_coarsened")
        return PrivacyDecision(VISIBLE, value=int(raw_value))


class CoarsenWithoutReplacementTestPolicy(TalentAnalyticsPrivacyPolicy):
    """Test-only policy that requests ``coarsened`` with NO safe replacement.

    Exists ONLY to prove ``apply_primary_privacy`` fails closed to
    ``suppressed`` rather than ever publishing a fake ``coarsened`` state
    alongside a null value, per the Section G Product Owner decision.
    """

    def __init__(self, *, minimum_cohort: int, version: str = "test-coarsen-without-replacement-v1"):
        self.minimum_cohort = minimum_cohort
        self.privacy_policy_version = version

    def evaluate_cell(self, *, privacy_class, raw_value, denominator=None, context=None):
        if raw_value is None:
            return PrivacyDecision(NO_DATA)
        if raw_value < self.minimum_cohort:
            return PrivacyDecision(COARSENED, reason_code="below_minimum_cohort_no_replacement")
        return PrivacyDecision(VISIBLE, value=int(raw_value))


def resolve_privacy_policy_provider():
    """Production FastAPI dependency hook.

    No production privacy policy is approved for M9 - this intentionally
    returns ``None`` so request handling fails closed. Tests override this
    dependency (``app.dependency_overrides``) to inject an explicit policy;
    nothing overrides it in production.
    """
    return None


def apply_primary_privacy(cells, policy):
    """Apply the policy's primary per-cell decision in place (Section J step 2).

    ``coarsened`` is only ever published when the policy's own decision
    supplies an explicit safe replacement value (``PrivacyDecision.value``).
    A policy requesting ``coarsened`` with no replacement fails closed to
    ``suppressed`` - this module never fabricates a coarsened aggregate and
    never serializes a ``coarsened`` state alongside a null value as if
    coarsening had actually happened.
    """
    for cell in cells:
        decision = policy.evaluate_cell(
            privacy_class=cell.privacy_class,
            raw_value=cell.raw_value,
            context=cell.context,
        )
        state = decision.state
        value = None
        reason_code = decision.reason_code
        if state == VISIBLE:
            value = decision.value
        elif state == COARSENED:
            if decision.value is not None:
                value = decision.value
            else:
                # Fail closed: no usable safe replacement was supplied.
                state = SUPPRESSED
                reason_code = decision.reason_code or "coarsening_replacement_unavailable"
        cell.state = state
        cell.value = value
        cell.reason_code = reason_code
    return cells


def derive_from_visible_cells(cells, derive):
    """Return a derived value only when every source cell is publishable.

    Derivations must consume the privacy-filtered ``value`` fields, never
    ``raw_value``.  Coarsened values are deliberately excluded because a
    provider-supplied replacement aggregate is not automatically a compatible
    basis for an exact derived percentage.
    """
    if not cells or any(cell.state != VISIBLE or cell.value is None for cell in cells):
        return None
    return derive(*(cell.value for cell in cells))


@dataclass
class Cell:
    """One publishable analytical value participating in zero or more
    parent-total = sum(children) reconstruction relationships.

    ``key`` must be a stable, sortable, identity-only tuple (dimension type
    plus dimension id/label) - it is never derived from the cell's own
    numeric value, so the Section J tie-break stays value-independent.
    """

    key: tuple
    privacy_class: str
    raw_value: Optional[int]
    depth: int = 1
    context: Optional[dict] = None
    state: str = VISIBLE
    value: Optional[int] = None
    reason_code: Optional[str] = None


@dataclass
class Group:
    """One parent-total = sum(children) reconstruction relationship instance."""

    name: str
    total: Cell
    children: list

    def all_cells(self):
        return [self.total, *self.children]


def _tie_break_key(cell: Cell, policy: TalentAnalyticsPrivacyPolicy):
    # Priority 2 (dimension depth) prefers hiding the deeper/more granular
    # cell (a child) over the shallower parent/total when both are otherwise
    # tied, so a headline total stays visible whenever a child alone can
    # break the reconstruction instead. This is a structural property of the
    # cell's position in the hierarchy, never its numeric value.
    return (
        _CLASS_ORDER.get(cell.privacy_class, len(_CLASS_ORDER)),
        -cell.depth,
        0 if policy.prefers_coarsening(privacy_class=cell.privacy_class) else 1,
        cell.key[0] if cell.key else "",
        cell.key,
    )


def _resolve_group(group: Group, policy: TalentAnalyticsPrivacyPolicy) -> bool:
    """Apply one complementary-suppression pass to a single group.

    Returns True if this pass changed any cell's state (used to drive the
    caller's fixed-point loop). Suppression is monotonic: this function only
    ever moves a cell from ``visible`` to a hidden state, never the reverse.

    The tie-broken victim always becomes ``suppressed``, never ``coarsened``:
    this reconstruction-breaking step has no channel to obtain a policy-
    supplied safe replacement aggregate for an arbitrary victim cell (Section
    G), so it must never fabricate one. ``prefers_coarsening`` still
    participates in ``_tie_break_key`` as a structural, identity-based
    ordering signal only - it never changes the resulting state here.
    """
    active = [c for c in group.all_cells() if c.state != NO_DATA]
    hidden = [c for c in active if c.state in _HIDDEN_STATES]
    visible = [c for c in active if c.state == VISIBLE]
    if len(hidden) != 1 or not visible:
        return False
    victim = sorted(visible, key=lambda c: _tie_break_key(c, policy))[0]
    victim.state = SUPPRESSED
    victim.value = None
    victim.reason_code = "complementary_suppression"
    return True


def run_complementary_suppression(groups, policy, *, max_passes: int = 8) -> bool:
    """Repeat complementary-suppression passes across every group until a
    fixed point is reached (Section J step 6) or ``max_passes`` is exhausted.

    Returns ``True`` if a safe fixed point was reached, ``False`` otherwise -
    callers MUST fail closed (``restricted``/``no_data``, never a best-effort
    guess) for any projection touched by a group set that did not converge.
    """
    for _ in range(max_passes):
        changed_any = False
        for group in groups:
            if _resolve_group(group, policy):
                changed_any = True
        if not changed_any:
            return True
    return False
