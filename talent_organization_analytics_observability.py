"""M10 B11-B safe operational observability for Organization Analytics.

Read-only, request-scoped instrumentation around the 7 existing
`routers/talent_organization_analytics.py` routes. This module NEVER carries
protected Talent data - it is a bounded, allowlisted structural/operational
signal only (what class of request happened, how much structural work
occurred, whether a governed policy provider allowed/rejected/failed, how
long the request took, and what failure category occurred).

Kept deliberately separate from `audit.get_audit_logger()` / the immutable
business audit trail (`logs/system_audit.log`, exported through the
Administrator "Download Audit Log" CSV/XLSX pipeline). That trail already
records one generic `http_request` line per request (method/path/status/
duration/actor) through the existing `audit_logging_middleware` in
`main.py`, so route-level latency/outcome already exists at the HTTP layer;
this module adds the M10-specific structural/provider signal the generic
middleware cannot see, on a dedicated, non-exported logger.

A telemetry failure must never affect the HTTP response or weaken a
fail-closed decision already made by the route: every public method here
swallows its own internal exceptions.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional


logger = logging.getLogger("tis.talent.organization_analytics.observability")

# Bounded, low-cardinality allowlist. Never add a Student identifier, raw
# analytical value, privacy threshold, or Candidate/Identification decision
# here - see `.claude/skills` / AGENTS.md boundaries and the B11-B task scope.
SAFE_STRUCTURAL_FIELDS = frozenset({
    "program_count", "row_count", "column_count", "prospective_cell_count",
    "prospective_pair_count", "emitted_pair_count", "relationship_estimate",
    "period_count", "authoritative_cycle_count", "component_count",
    "comparison_count", "page_limit", "page_returned_count", "has_more",
    "field_count", "academic_year_scope_present",
})

SAFE_PROVIDER_FIELDS = frozenset({
    "privacy_outcome", "availability_outcome", "breadth_outcome",
})

_ALLOWED_FIELDS = SAFE_STRUCTURAL_FIELDS | SAFE_PROVIDER_FIELDS

_OUTCOME_LEVEL = {
    "success": logging.INFO,
    "rejected": logging.WARNING,
    "unavailable": logging.WARNING,
    "failed": logging.ERROR,
}


class OrganizationAnalyticsObservation:
    """One-request accumulator of safe structural/provider telemetry.

    Structural signals are merged only from the bounded allowlist above;
    unknown keys are silently dropped rather than raising, so a future
    caller mistake fails safe (no telemetry field) instead of breaking the
    request. `emit` is idempotent (only the first call is recorded) and
    never raises.
    """

    __slots__ = ("_projection_family", "_started", "_fields", "_emitted")

    def __init__(self, projection_family: str):
        self._projection_family = str(projection_family)
        self._started = time.monotonic()
        self._fields: dict[str, object] = {}
        self._emitted = False

    def record(self, **fields) -> None:
        try:
            for key, value in fields.items():
                if key in _ALLOWED_FIELDS:
                    self._fields[key] = value
        except Exception:
            self._safe_log_failure("record")

    def emit(self, outcome: str, *, error_category: Optional[str] = None, **fields) -> None:
        """Emit exactly once. Never raises and never blocks the caller."""
        if self._emitted:
            return
        self._emitted = True
        try:
            self.record(**fields)
            latency_ms = round((time.monotonic() - self._started) * 1000, 2)
            payload = {
                "event_type": "organization_analytics_request",
                "projection_family": self._projection_family,
                "outcome": outcome,
                "latency_ms": latency_ms,
            }
            if error_category:
                payload["error_category"] = error_category
            payload.update(self._fields)
            level = _OUTCOME_LEVEL.get(outcome, logging.INFO)
            logger.log(level, json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str))
        except Exception:
            self._safe_log_failure("emit")

    @staticmethod
    def _safe_log_failure(where: str) -> None:
        try:
            logger.debug("organization_analytics_observability_%s_failed", where)
        except Exception:
            pass
