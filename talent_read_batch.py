"""Opt-in, request-scoped read memoization for Talent list/aggregate endpoints.

Root cause addressed (Deployment Acceptance Batch 1, loading/performance):
per-row Talent result derivation (``overall_program_result``,
``reassessment_requirement`` and their Framework/rubric/descriptor lookups)
re-read the SAME immutable-per-request configuration once per Assessment row,
so the Student Assessments list issued ~49 SQL statements per row (982 for 20
rows). The configuration those helpers read depends only on (Framework, Grade,
rubric), not on the Student.

Safety contract:

* Inactive by default. ``memo`` is a plain call-through unless a caller has
  entered :func:`read_batch` for that SQLAlchemy Session, so every write path
  (start/complete/reassess/...) and every unrelated read keeps the exact
  pre-existing behavior.
* The cache lives in ``Session.info`` for the duration of one ``with`` block on
  one request-owned Session. It is never process-global, never shared between
  requests or users, and is discarded when the block exits - so it can never
  serve a value that predates a Student deletion, a permission change, or a
  configuration edit made by a later request.
* It memoizes only reads; it performs no authorization and is not an
  authorization boundary.
"""

from __future__ import annotations

from contextlib import contextmanager

_KEY = "tis_talent_read_batch"


@contextmanager
def read_batch(db):
    """Enable read memoization on ``db`` for the duration of the block."""
    if db.info.get(_KEY) is not None:  # nested: reuse the outer batch
        yield db.info[_KEY]
        return
    cache: dict = {}
    db.info[_KEY] = cache
    try:
        yield cache
    finally:
        db.info.pop(_KEY, None)


def active(db) -> bool:
    return db.info.get(_KEY) is not None


def memo(db, key, loader):
    """Return ``loader()``, memoized for the active batch (if any)."""
    cache = db.info.get(_KEY)
    if cache is None:
        return loader()
    if key not in cache:
        cache[key] = loader()
    return cache[key]


def prime(db, key, value) -> None:
    """Seed one known value into the active batch (no-op when inactive)."""
    cache = db.info.get(_KEY)
    if cache is not None:
        cache[key] = value
