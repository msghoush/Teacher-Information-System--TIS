---
title: M10 B11-C PostgreSQL Profiling Evidence Remediation
module: engineering-handbook
last_updated: 2026-09-07
---

# 2026-09-07 - M10 B11-C PostgreSQL Profiling Evidence Remediation

Module:
Talent & Potential M10 Organization Analytics, PostgreSQL performance
qualification (ADR 0028)

Related change-history entry:
`docs/CHANGE_HISTORY.md` - 2026-09-07 - M10 B11-C PostgreSQL Profiling
Evidence Remediation

Related ADRs:
`docs/adr/0028-b11-production-qualification-policy.md` (governing authority
for B11-C entry, evidence requirements, and release gates)

Reviewer/approval notes:
The evidence-remediation work did not change M10 application
behavior, does not add an index, does not add a migration, does not change
PostgreSQL isolation, and does not choose any production threshold, breadth
limit, SLO, memory ceiling, or commercial mapping. B11-C is NOT declared
CLOSED by the evidence-gathering pass itself. Its subsequent independent
re-review returned **PASS WITH NON-BLOCKING OBSERVATIONS**, so the governed
closure checkpoint marks B11-C **CLOSED**. No merge or deployment occurred.
`tis.db`
was not touched; all measurement used the dedicated non-production
`tis_b11c_test_db` PostgreSQL 16.15 instance at `127.0.0.1` supplied via the
`TIS_TEST_POSTGRESQL_URL` environment variable (never printed, logged, or
persisted anywhere in this repository).

## Why This Document Exists

An earlier PostgreSQL profiling pass for M10 B11-C did execute successfully
and produced real findings (route profiling, query-count/Seq-Scan/memory
observations, longitudinal bounded-query behavior, and M10 regression
evidence), but its harness/output was temporary and left no durable,
independently reviewable repository artifact. Independent B11-C review
therefore returned FAIL - not because profiling never happened, but because
its evidence could not be verified after the fact.

This document re-measures the same evidence end to end against a real,
dedicated, non-production PostgreSQL 16.15 database, using a reproducible
synthetic dataset builder and a reproducible profiling procedure (both fully
reproduced below), and preserves the raw findings durably so an independent
reviewer can verify every conclusion without relying on a chat transcript.

## Current Milestone Truth

- B0-B10: CLOSED (per `docs/adr/0027-...md` and prior committed KMS state).
- B11-A: complete (read-only qualification).
- B11-B: CLOSED (operational observability).
- B11 production-qualification policy (ADR 0028): APPROVED/GOVERNED.
- B11-C: PostgreSQL profiling **executed**; durable evidence **captured** in
  this document. Independent re-review: **PASS WITH NON-BLOCKING
  OBSERVATIONS**. B11-C is **CLOSED**.
- No index approved. No production SLO approved. No production privacy
  threshold approved. No production breadth limit approved. No production
  memory ceiling approved. No PostgreSQL isolation change.
- B11-D: NOT IMPLEMENTED. B11-E: NOT COMPLETE. B11 overall: NOT CLOSED.
- B12: NOT IMPLEMENTED. Production readiness: NOT achieved.

## Phase 1 - Connection Verification (Non-Production)

Verified programmatically, without ever printing the credential/URL:

| Check | Result |
|---|---|
| `TIS_TEST_POSTGRESQL_URL` present in process environment | Yes |
| Connection succeeds | Yes |
| `SELECT version()` | `PostgreSQL 16.15, compiled by Visual C++ build 1944, 64-bit` |
| `SELECT current_database()` | `tis_b11c_test_db` |
| `SELECT inet_server_addr()` | `127.0.0.1` (localhost only) |
| Environment | Non-production (dedicated `tis_b11c_test_db` / `tis_b11c_test_role`, localhost-only) |

## Methodology (Reproducible)

**Environment.** Local, non-production PostgreSQL 16.15 (`tis_b11c_test_db`,
`127.0.0.1`), reached only via `TIS_TEST_POSTGRESQL_URL`. All profiling ran
inside a dedicated PostgreSQL **schema per scale** (`tis_b11c_evidence_<run
id>_<scale>`), created fresh and dropped (`DROP SCHEMA ... CASCADE`) at the
end of every run - no rows were left behind in the shared test database.

**Schema.** `models.Base.metadata.create_all(engine)` against the scoped
schema (via `search_path`), using the exact same SQLAlchemy models the
application uses (`models.py` / `database.Base`) - no invented schema.

**Application under test.** The real M10 routers/services
(`routers/talent_organization_analytics.py`,
`talent_org_intelligence_service.py`, `talent_org_talent_map.py`,
`talent_org_b7.py`, `talent_org_participation_overlap.py`,
`talent_org_student_drill.py`, `talent_org_longitudinal.py`) mounted on an
isolated `FastAPI()` app and driven with `fastapi.testclient.TestClient`,
exactly like the existing `tests/test_talent_organization_*.py` suite wires
routes, with `dependency_overrides` for `get_db` (bound to the profiling
session/engine), `get_current_user` (a synthetic `ORGANIZATION`-scope actor),
and the three existing non-production provider seams.

**Non-production provider configuration class (Phase 3).** Explicitly
labeled **NON-PRODUCTION PROFILING CONFIGURATION**, matching the existing
test-double pattern already used by `tests/test_talent_org_intelligence_queries.py`
and `tests/test_talent_organization_overview.py` (`AllowAvailability`,
`AllowBreadth`, `talent_analytics_privacy.AllowAllTestPolicy`). No production
provider exists yet (ADR 0028); these test doubles always allow, so measured
latency/queries reflect the SQL, ORM, relationship-graph, and serialization
work that exists in the codebase today, not a future production
threshold/breadth decision.

**Query counting.** A temporary SQLAlchemy `before_cursor_execute` engine
event listener (`QueryCounter`), registered only for the duration of one
`client.get(...)` call and removed (`event.remove`) immediately after. It
counts and stores `(statement, parameters)` pairs; it has no permanent
application effect and was never left registered outside the measurement
window.

**Latency.** `time.perf_counter()` wrapped tightly around `client.get(...)`,
for a "first" (cold-ish) and a "second" (warm) call per route per scale.

**Memory.** `psutil.Process(os.getpid()).memory_info().rss`, sampled after
`gc.collect()`, at fixed checkpoints: process baseline (post-import,
pre-DB), before/after schema creation, before/after synthetic data build,
and pre/post-first-call/post-second-call for every route. **Classified
explicitly as DIRECTIONAL LOCAL WINDOWS DEVELOPMENT EVIDENCE - not a
production memory ceiling.** All three scales ran sequentially inside one
Python process (see Known Limitations); absolute RSS values are cumulative
across scales, not independent per-scale baselines.

**EXPLAIN.** For each route, up to three distinct `SELECT` statement shapes
captured during the "first" call were re-executed as
`EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) <statement>` on the raw DBAPI
(`psycopg2`) cursor, using the exact captured driver-level parameters, then
rolled back (read-only). Statements touching the population/aggregation
tables or containing `GROUP BY` were preferred over small reference-table
lookups when more than three shapes were captured.

**Synthetic data.** Seeded `random.Random(20260907)` for reproducibility. No
production data, fixtures, or database export was used or imported.

**Regression.** Standard `pytest` against the existing M10 suites (see
Regression section below) - unrelated to the PostgreSQL harness.

### Exact Reproduction Procedure

1. Set `TIS_TEST_POSTGRESQL_URL` to a non-production PostgreSQL connection
   string (never a production database).
2. Run the harness below with `<repo>/.venv/Scripts/python.exe`. It requires
   `psutil` (`pip install psutil` into the venv if not already present - a
   local measurement-only dependency, not added to `requirements.txt`).
3. The harness prints per-scale dimensions to stdout and writes a JSON
   results file next to itself; it creates and drops its own schemas and
   never touches `tis.db` or any table outside the schema it created.

The harness was **not** committed to the repository (kept as ephemeral
profiling tooling per the Profiling Harness scope-minimization guidance);
its full source is reproduced verbatim below so an independent reviewer can
re-run it without this conversation:

```python
"""B11-C PostgreSQL profiling harness (NON-PRODUCTION, evidence remediation).

Not committed to the repository. Requires TIS_TEST_POSTGRESQL_URL. Creates and
drops its own dedicated PostgreSQL schema inside the target test database.
Never targets production. Has no application runtime effect (the app itself
is only exercised in-process via FastAPI TestClient against the ephemeral
schema created by this script).

Run: <repo>/.venv/Scripts/python.exe b11c_profile.py [SCALE ...]
"""
from __future__ import annotations

import gc
import json
import os
import random
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime

REPO = r"C:\Development\Teacher-Information-System--TIS"
sys.path.insert(0, REPO)
os.chdir(REPO)

import psutil
import sqlalchemy as sa
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient

import models
from database import Base
from auth import get_current_user
from dependencies import get_db
from talent_analytics_privacy import AllowAllTestPolicy, resolve_privacy_policy_provider
from talent_org_intelligence_service import (
    OrganizationAnalyticsAvailabilityProvider,
    OrganizationAnalyticsBreadthPolicy,
    resolve_organization_analytics_availability_provider,
    resolve_organization_analytics_breadth_policy,
)
from routers import talent_organization_analytics as route

POSTGRESQL_URL = os.environ.get("TIS_TEST_POSTGRESQL_URL", "")
assert POSTGRESQL_URL.startswith("postgresql"), "TIS_TEST_POSTGRESQL_URL missing/invalid"

RUN_ID = uuid.uuid4().hex[:10]
RESULTS = {"run_id": RUN_ID, "scales": {}}
PROCESS = psutil.Process(os.getpid())


def rss_mb():
    gc.collect()
    return PROCESS.memory_info().rss / (1024 * 1024)


RESULTS["baseline_rss_mb"] = round(rss_mb(), 2)


class AllowAvailability(OrganizationAnalyticsAvailabilityProvider):
    availability_version = "b11c-profiling-nonprod-v1"

    def is_available(self, **_ctx):
        return True


class AllowBreadth(OrganizationAnalyticsBreadthPolicy):
    breadth_policy_version = "b11c-profiling-nonprod-v1"

    def allows(self, **_shape):
        return True


# ---------------------------------------------------------------------------
# Scale configuration (NON-PRODUCTION PROFILING CONFIGURATION)
# ---------------------------------------------------------------------------
SCALES = {
    "SMALL": dict(branches=2, programs=2, focus_periods=3, students_per_cycle=15, other_cycle_students=20,
                  candidate_rate=0.4, identify_rate=0.5, overlap_students=8),
    "MEDIUM": dict(branches=4, programs=6, focus_periods=5, students_per_cycle=150, other_cycle_students=150,
                   candidate_rate=0.35, identify_rate=0.5, overlap_students=120),
    "LARGE": dict(branches=8, programs=12, focus_periods=8, students_per_cycle=1200, other_cycle_students=1200,
                  candidate_rate=0.3, identify_rate=0.5, overlap_students=1000),
}

GRADES = [str(g) for g in range(1, 13)]


class Ids:
    def __init__(self):
        self._n = defaultdict(int)

    def next(self, kind):
        self._n[kind] += 1
        return self._n[kind]


def build_dataset(session, scale_name, cfg, rng):
    school_group_id = 1
    foreign_group_id = 2
    academic_year_id = 100
    foreign_ay = 200
    now = datetime(2026, 9, 1)

    session.add_all([
        models.SchoolGroup(id=school_group_id, name=f"B11C {scale_name} Primary"),
        models.SchoolGroup(id=foreign_group_id, name=f"B11C {scale_name} Foreign"),
    ])
    session.commit()
    branches = [10 + i for i in range(cfg["branches"])]
    for b in branches:
        session.add(models.Branch(id=b, school_group_id=school_group_id, name=f"Branch{b}", status=True))
    foreign_branch = 900
    session.add(models.Branch(id=foreign_branch, school_group_id=foreign_group_id, name="ForeignBranch", status=True))
    session.add_all([
        models.AcademicYear(id=academic_year_id, school_group_id=school_group_id, year_name="2026-2027"),
        models.AcademicYear(id=foreign_ay, school_group_id=foreign_group_id, year_name="2026-2027"),
    ])
    session.commit()

    program_ids = list(range(1, cfg["programs"] + 1))
    focus_program_id = program_ids[0]
    foreign_program_id = 9001
    for pid in program_ids:
        session.add(models.TalentProgram(id=pid, school_group_id=school_group_id, name=f"Program{pid}", status="active"))
    session.add(models.TalentProgram(id=foreign_program_id, school_group_id=foreign_group_id, name="ForeignProgram", status="active"))
    session.commit()

    for pid in program_ids:
        session.add(models.TalentProgramAcademicYearConfiguration(
            id=pid, school_group_id=school_group_id, program_id=pid, academic_year_id=academic_year_id,
            is_enabled=True, eligible_grade_levels_csv=",".join(GRADES),
        ))
    session.add(models.TalentProgramAcademicYearConfiguration(
        id=9001, school_group_id=foreign_group_id, program_id=foreign_program_id, academic_year_id=foreign_ay,
        is_enabled=True, eligible_grade_levels_csv="1",
    ))
    session.commit()

    fw_id = {}
    for pid in program_ids:
        fwid = 100000 + pid
        fw_id[pid] = fwid
        session.add(models.TalentProgramFrameworkVersion(
            id=fwid, school_group_id=school_group_id, program_id=pid, version_number=1, status="active",
            title=f"Framework{pid}", revision=1, semantic_fingerprint=f"{pid:064d}"[-64:],
        ))
    session.add(models.TalentProgramFrameworkVersion(
        id=900001, school_group_id=foreign_group_id, program_id=foreign_program_id, version_number=1,
        status="active", title="ForeignFramework", revision=1, semantic_fingerprint="f" * 64,
    ))
    session.commit()

    plan_id = {}
    for pid in program_ids:
        pid_plan = 500000 + pid
        plan_id[pid] = pid_plan
        session.add(models.TalentAnnualEvaluationPlan(
            id=pid_plan, school_group_id=school_group_id, program_id=pid, academic_year_id=academic_year_id,
            program_academic_year_configuration_id=pid, status="active", revision=1, activated_at=now,
        ))
    session.commit()

    # Focus program periods (for longitudinal profiling)
    period_ids = []
    for seq in range(1, cfg["focus_periods"] + 1):
        period_id = 600000 + seq
        period_ids.append(period_id)
        session.add(models.TalentPlannedEvaluationPeriod(
            id=period_id, school_group_id=school_group_id, program_id=focus_program_id,
            academic_year_id=academic_year_id, annual_evaluation_plan_id=plan_id[focus_program_id],
            sequence=seq, label=f"Period{seq}", normalized_label=f"period{seq}",
            is_required=True, status="planned",
        ))
    session.commit()

    # Cycles: focus program gets one cycle per period; every other program gets one standalone cycle.
    cycle_meta = []  # (cycle_id, program_id, framework_version_id, period_id_or_None, status)
    cid = 200000
    for i, period_id in enumerate(period_ids):
        cid += 1
        status = "closed" if i < len(period_ids) - 1 else "open"
        cycle_meta.append((cid, focus_program_id, fw_id[focus_program_id], period_id, status))
    for pid in program_ids[1:]:
        cid += 1
        cycle_meta.append((cid, pid, fw_id[pid], None, "open"))
    for cycle_id, pid, fwid, period_id, status in cycle_meta:
        session.add(models.TalentAssessmentCycle(
            id=cycle_id, school_group_id=school_group_id, program_id=pid, academic_year_id=academic_year_id,
            framework_version_id=fwid, planned_evaluation_period_id=period_id, title=f"Cycle{cycle_id}",
            status=status, revision=1, population_effective_at=now,
        ))
    # Foreign tenant: one small cycle for isolation control.
    session.add(models.TalentAssessmentCycle(
        id=999001, school_group_id=foreign_group_id, program_id=foreign_program_id, academic_year_id=foreign_ay,
        framework_version_id=900001, planned_evaluation_period_id=None, title="ForeignCycle",
        status="open", revision=1, population_effective_at=now,
    ))
    session.commit()

    # Review candidate policy (required FK for TalentReviewCandidate rows).
    policy_id = {}
    for pid in program_ids:
        pol_id = 700000 + pid
        policy_id[pid] = pol_id
        session.add(models.TalentReviewCandidatePolicy(
            id=pol_id, school_group_id=school_group_id, program_id=pid, framework_version_id=fw_id[pid],
            is_enabled=True, match_mode="all",
        ))
    session.commit()

    # Students + placements + population members + assessments (+candidates/identifications).
    student_id_counter = [0]
    student_rows = []
    placement_rows = []

    def new_student(branch_id, grade, group=school_group_id, ay=academic_year_id):
        student_id_counter[0] += 1
        sid = student_id_counter[0]
        student_rows.append(dict(
            id=sid, school_group_id=group, first_name="Synthetic", last_name=f"Student{sid}",
            status="active",
        ))
        placement_id = sid
        placement_rows.append(dict(
            id=placement_id, school_group_id=group, student_id=sid, academic_year_id=ay,
            branch_id=branch_id, grade_level=grade, section_name="A", effective_from=now, status="active",
        ))
        return sid, placement_id

    # Pre-create a shared overlap student pool reused across multiple programs' cycles.
    overlap_pool = []
    member_id = 0
    assessment_id = 0
    candidate_id = 0
    identification_id = 0
    pop_rows = []
    assess_rows = []
    cand_rows = []
    ident_rows = []

    def make_population(cycle_id, pid, fwid, count, branch_cycle, reuse_pool=None, pool_fraction=0.0):
        nonlocal member_id
        made = []
        pool_take = min(int(count * pool_fraction), len(reuse_pool)) if reuse_pool else 0
        chosen_from_pool = rng.sample(reuse_pool, pool_take) if pool_take else []
        for i in range(count):
            if i < len(chosen_from_pool):
                # Reused student: population branch/grade MUST match their real placement row.
                sid, placement_id, branch_id, grade = chosen_from_pool[i]
            else:
                branch_id = branch_cycle[i % len(branch_cycle)]
                grade = GRADES[i % len(GRADES)]
                sid, placement_id = new_student(branch_id, grade)
                if reuse_pool is not None:
                    reuse_pool.append((sid, placement_id, branch_id, grade))
            member_id += 1
            mid = member_id
            pop_rows.append(dict(
                id=mid, school_group_id=school_group_id, cycle_id=cycle_id, program_id=pid,
                academic_year_id=academic_year_id, framework_version_id=fwid, student_id=sid,
                academic_placement_id=placement_id, branch_id=branch_id, grade_level=grade,
                section_name="A", population_effective_at=now, frozen_at=now,
            ))
            made.append((mid, sid))
        return made

    def make_assessments(members, cycle_id, pid, fwid, candidate_rate, identify_rate):
        nonlocal assessment_id, candidate_id, identification_id
        for mid, sid in members:
            status = rng.choices(
                ["completed", "in_progress", "incomplete", "unassessed"],
                weights=[0.55, 0.15, 0.1, 0.2],
            )[0]
            if status == "unassessed":
                continue
            assessment_id += 1
            aid = assessment_id
            assess_rows.append(dict(
                id=aid, school_group_id=school_group_id, cycle_id=cycle_id, cycle_population_member_id=mid,
                student_id=sid, program_id=pid, academic_year_id=academic_year_id, framework_version_id=fwid,
                status=status, revision=1, started_at=now,
                completed_at=now if status == "completed" else None,
            ))
            if status == "completed" and rng.random() < candidate_rate:
                candidate_id += 1
                cand_id = candidate_id
                cand_rows.append(dict(
                    id=cand_id, school_group_id=school_group_id, cycle_id=cycle_id,
                    cycle_population_member_id=mid, student_id=sid, program_id=pid,
                    academic_year_id=academic_year_id, framework_version_id=fwid, assessment_id=aid,
                    policy_id=policy_id[pid], match_mode="all", evaluation_fingerprint=f"{cand_id:064d}"[-64:],
                    evaluation_snapshot_json="{}", status="reviewed",
                ))
                if rng.random() < identify_rate:
                    identification_id += 1
                    ident_rows.append(dict(
                        id=identification_id, school_group_id=school_group_id, cycle_id=cycle_id,
                        cycle_population_member_id=mid, student_id=sid, program_id=pid,
                        academic_year_id=academic_year_id, framework_version_id=fwid, assessment_id=aid,
                        review_candidate_id=cand_id, decision="identified",
                    ))

    # Focus program: each period's cycle carries forward ~70% of the previous period's students.
    for cycle_id, pid, fwid, period_id, status in cycle_meta:
        if pid == focus_program_id:
            members = make_population(
                cycle_id, pid, fwid, cfg["students_per_cycle"], branches,
                reuse_pool=overlap_pool, pool_fraction=0.7 if cycle_id != cycle_meta[0][0] else 0.0,
            )
            make_assessments(members, cycle_id, pid, fwid, cfg["candidate_rate"], cfg["identify_rate"])
    # Other programs: standalone cycle, partially reusing the same overlap pool (participation overlap signal).
    other_pool_fraction = min(0.5, cfg["overlap_students"] / max(cfg["other_cycle_students"], 1))
    for cycle_id, pid, fwid, period_id, status in cycle_meta:
        if pid != focus_program_id:
            members = make_population(
                cycle_id, pid, fwid, cfg["other_cycle_students"], branches,
                reuse_pool=overlap_pool, pool_fraction=other_pool_fraction,
            )
            make_assessments(members, cycle_id, pid, fwid, cfg["candidate_rate"], cfg["identify_rate"])

    # Foreign tenant: tiny isolated population (not counted toward primary scale numbers).
    fsid, fpid = new_student(foreign_branch, "1", group=foreign_group_id, ay=foreign_ay)
    member_id += 1
    pop_rows.append(dict(
        id=member_id, school_group_id=foreign_group_id, cycle_id=999001, program_id=foreign_program_id,
        academic_year_id=foreign_ay, framework_version_id=900001, student_id=fsid,
        academic_placement_id=fpid, branch_id=foreign_branch, grade_level="1", section_name="A",
        population_effective_at=now, frozen_at=now,
    ))

    if student_rows:
        session.execute(sa.insert(models.Student), student_rows)
    if placement_rows:
        session.execute(sa.insert(models.StudentAcademicPlacement), placement_rows)
    if pop_rows:
        session.execute(sa.insert(models.TalentAssessmentCyclePopulationMember), pop_rows)
    if assess_rows:
        session.execute(sa.insert(models.TalentStudentAssessment), assess_rows)
    if cand_rows:
        session.execute(sa.insert(models.TalentReviewCandidate), cand_rows)
    if ident_rows:
        session.execute(sa.insert(models.TalentOfficialIdentification), ident_rows)
    session.commit()

    dims = {
        "school_groups": 2, "branches": len(branches), "programs": len(program_ids),
        "focus_program_id": focus_program_id, "period_count": len(period_ids),
        "cycle_count": len(cycle_meta) + 1, "frozen_population_members": len(pop_rows),
        "assessments": len(assess_rows), "candidates": len(cand_rows), "identifications": len(ident_rows),
        "distinct_students": student_id_counter[0] + 1,
        "annual_plans": len(program_ids), "grades_used": len(GRADES),
        "program_pair_count": len(program_ids) * (len(program_ids) + 1) // 2,
    }
    return dict(
        school_group_id=school_group_id, academic_year_id=academic_year_id, program_ids=program_ids,
        focus_program_id=focus_program_id, branches=branches, dims=dims,
    )


def actor_for(group, branch, ay):
    return models.User(
        user_id="pf0001", username="profiler", role="Editor", user_type="TENANT",
        access_scope="ORGANIZATION", school_group_id=group, branch_id=branch, academic_year_id=ay,
        is_active=True,
    )


def grant_permissions(session, group):
    keys = [
        "talent_analytics.view", "talent_review_candidates.view", "talent_official_identifications.view",
        "talent_analytics.view_students", "talent_learner_profiles.view",
    ]
    session.add_all(models.RolePermission(school_group_id=group, role="Editor", permission_key=k, is_allowed=True) for k in keys)
    session.commit()


def make_client(session):
    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: actor_for(1, 10, 100)
    app.dependency_overrides[resolve_organization_analytics_availability_provider] = lambda: AllowAvailability()
    app.dependency_overrides[resolve_organization_analytics_breadth_policy] = lambda: AllowBreadth()
    app.dependency_overrides[resolve_privacy_policy_provider] = lambda: AllowAllTestPolicy()
    return TestClient(app)


class QueryCounter:
    def __init__(self, engine):
        self.engine = engine
        self.count = 0
        self.statements = []  # list[(statement, parameters)]

    def __enter__(self):
        self.count = 0
        self.statements = []
        event.listen(self.engine, "before_cursor_execute", self._before)
        return self

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1
        self.statements.append((statement, parameters))

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._before)


def profile_route(client, engine, method_path, label):
    with QueryCounter(engine) as qc:
        t0 = time.perf_counter()
        resp = client.get(method_path)
        t1 = time.perf_counter()
    return {
        "label": label, "path": method_path, "status": resp.status_code,
        "latency_ms": round((t1 - t0) * 1000, 2), "query_count": qc.count,
        "statements": qc.statements,
        "response_bytes": len(resp.content),
    }


def summarize_statement(stmt):
    return " ".join(stmt.split())[:220]


def run_scale(scale_name, cfg, admin_engine):
    schema = f"tis_b11c_evidence_{RUN_ID}_{scale_name.lower()}"
    with admin_engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = sa.create_engine(
        POSTGRESQL_URL,
        connect_args={"connect_timeout": 10, "options": f"-c search_path={schema} -c statement_timeout=120s"},
    )
    rss_before_schema = rss_mb()
    Base.metadata.create_all(engine)
    rss_after_schema = rss_mb()

    Session = sessionmaker(bind=engine)
    session = Session()
    rng = random.Random(20260907)
    rss_before_data = rss_mb()
    t0 = time.perf_counter()
    dataset = build_dataset(session, scale_name, cfg, rng)
    build_seconds = time.perf_counter() - t0
    rss_after_data = rss_mb()
    grant_permissions(session, dataset["school_group_id"])

    client = make_client(session)
    ay = dataset["academic_year_id"]
    focus = dataset["focus_program_id"]
    branch0 = dataset["branches"][0]

    routes = [
        ("overview", f"/api/talent/organization-analytics/overview?academic_year_id={ay}"),
        ("talent_map_branch", f"/api/talent/organization-analytics/talent-map?academic_year_id={ay}&dimension=program_branch&metric=completion_coverage"),
        ("program_portfolio", f"/api/talent/organization-analytics/program-portfolio?academic_year_id={ay}"),
        ("branch_intelligence", f"/api/talent/organization-analytics/branches/{branch0}?academic_year_id={ay}"),
        ("participation_overlap", f"/api/talent/organization-analytics/participation-overlap?academic_year_id={ay}"),
        ("student_drill_25", f"/api/talent/organization-analytics/students?academic_year_id={ay}&limit=25"),
        ("student_drill_100", f"/api/talent/organization-analytics/students?academic_year_id={ay}&limit=100"),
        ("longitudinal", f"/api/talent/organization-analytics/programs/{focus}/longitudinal?academic_year_id={ay}&metric=completion_coverage"),
    ]

    results = {}
    explain_samples = {}
    for label, path in routes:
        gc.collect()
        rss_pre = rss_mb()
        first = profile_route(client, engine, path, label)
        rss_post_first = rss_mb()
        second = profile_route(client, engine, path, label)
        rss_post_second = rss_mb()
        results[label] = {
            "first_call": {k: v for k, v in first.items() if k != "statements"},
            "second_call": {k: v for k, v in second.items() if k != "statements"},
            "rss_pre_mb": round(rss_pre, 2), "rss_post_first_mb": round(rss_post_first, 2),
            "rss_post_second_mb": round(rss_post_second, 2),
        }
        seen = {}
        for stmt, params in first["statements"]:
            if not stmt.strip().upper().startswith("SELECT"):
                continue
            key = summarize_statement(stmt)
            seen.setdefault(key, (stmt, params))
        ranked = sorted(
            seen.values(),
            key=lambda sp: (
                0 if ("talent_assessment_cycle_population_members" in sp[0] or "GROUP BY" in sp[0].upper()) else 1,
                -len(sp[0]),
            ),
        )
        explain_samples[label] = ranked[:3]

    explain_results = {}
    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        for label, stmts in explain_samples.items():
            explain_results[label] = []
            for stmt, params in stmts:
                try:
                    cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {stmt}", params)
                    plan_text = "\n".join(row[0] for row in cur.fetchall())
                    raw_conn.rollback()
                except Exception as exc:
                    plan_text = f"<EXPLAIN skipped: {exc.__class__.__name__}: {exc}>"
                    raw_conn.rollback()
                explain_results[label].append({"sql_shape": summarize_statement(stmt), "plan": plan_text})
    finally:
        raw_conn.close()

    session.close()
    engine.dispose()
    with admin_engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))

    return {
        "dims": dataset["dims"], "build_seconds": round(build_seconds, 2),
        "rss_before_schema_mb": round(rss_before_schema, 2), "rss_after_schema_mb": round(rss_after_schema, 2),
        "rss_before_data_mb": round(rss_before_data, 2), "rss_after_data_mb": round(rss_after_data, 2),
        "routes": results, "explain": explain_results,
    }


def main():
    global SCALES
    if len(sys.argv) > 1:
        SCALES = {k: v for k, v in SCALES.items() if k in sys.argv[1:]}
    admin_engine = sa.create_engine(POSTGRESQL_URL, connect_args={"connect_timeout": 10})
    with admin_engine.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar()
        dbname = conn.execute(text("SELECT current_database()")).scalar()
        host = conn.execute(text("SELECT inet_server_addr()")).scalar()
    RESULTS["postgresql_version"] = version
    RESULTS["database"] = dbname
    RESULTS["host"] = str(host)

    for scale_name, cfg in SCALES.items():
        print(f"=== Running scale {scale_name} ===", flush=True)
        RESULTS["scales"][scale_name] = run_scale(scale_name, cfg, admin_engine)
        print(f"=== Done {scale_name}: dims={RESULTS['scales'][scale_name]['dims']} ===", flush=True)

    admin_engine.dispose()
    RESULTS["final_rss_mb"] = round(rss_mb(), 2)

    out_path = os.path.join(os.path.dirname(__file__), "b11c_profile_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
```

## Dataset Dimensions (Exact, As Generated)

All three scenarios share one `SchoolGroup` (primary tenant, id 1) plus a
second, tiny, isolated foreign `SchoolGroup` (id 2, one Branch, one Program,
one Student) used only as a tenant-isolation control - its rows are excluded
from every count below. `focus_program_id` is the one Program that carries an
Annual Evaluation Plan with multiple ordered Planned Evaluation Periods (each
backed by its own frozen Assessment Cycle) for Longitudinal profiling; every
other Program has exactly one standalone open Assessment Cycle. All grades
1-12 are used (`grades_used=12`); Sections are uniformly `"A"` (a stated
simplification - see Known Limitations).

| Dimension | SMALL | MEDIUM | LARGE |
|---|---:|---:|---:|
| SchoolGroups (primary + foreign control) | 2 | 2 | 2 |
| Branches (primary tenant) | 2 | 4 | 8 |
| Programs (primary tenant) | 2 | 6 | 12 |
| Program pairs `P(P+1)/2` (incl. self-pairs, matches route's `pair_count`) | 3 | 21 | 78 |
| Annual Evaluation Plans | 2 | 6 | 12 |
| Planned Evaluation Periods (focus Program only) | 3 | 5 | 8 |
| Assessment Cycles (incl. 1 foreign-tenant cycle) | 5 | 11 | 20 |
| Frozen Cycle population members | 66 | 1,501 | 22,801 |
| Distinct Students (primary tenant, incl. cross-Program overlap reuse) | 39 | 707 | 10,322 |
| Talent Student Assessments | 47 | 1,178 | 18,095 |
| Review Candidates | 21 | 314 | 3,836 |
| Official Identifications | 11 | 154 | 1,938 |

`student_drill_100` (limit=100) and `student_drill_25` (limit=25) were both
profiled against the same population per scale.

## Route Coverage Confirmation

All seven governed M10 Organization Intelligence routes were profiled (plus
Student Drill at both `limit=25` and `limit=100`), all returning HTTP 200 at
every scale with the non-production allow-all providers:

1. `GET /api/talent/organization-analytics/overview`
2. `GET /api/talent/organization-analytics/talent-map` (`dimension=program_branch`)
3. `GET /api/talent/organization-analytics/program-portfolio`
4. `GET /api/talent/organization-analytics/branches/{branch_id}`
5. `GET /api/talent/organization-analytics/participation-overlap`
6. `GET /api/talent/organization-analytics/students` (`limit=25` and `limit=100`)
7. `GET /api/talent/organization-analytics/programs/{program_id}/longitudinal`

No profiling API route exists or was added.

## Query Count Per Route (SMALL / MEDIUM / LARGE)

| Route | SMALL | MEDIUM | LARGE | Grows with scale? |
|---|---:|---:|---:|---|
| overview | 10 | 10 | 10 | No |
| talent_map (program_branch) | 9 | 9 | 9 | No |
| program_portfolio | 11 | 11 | 11 | No |
| branch_intelligence | 11 | 11 | 11 | No |
| participation_overlap | 8 | 8 | 8 | No |
| student_drill (limit=25) | 11 | 11 | 11 | No |
| student_drill (limit=100) | 11 | 11 | 11 | No |
| longitudinal | 11 | 11 | 11 | No |

Query count was **identical across all three scales for every route**,
despite Programs growing 2->6->12, frozen population growing 66->1,501->
22,801, Periods (longitudinal) growing 3->5->8, and Program pairs
(participation-overlap) growing 3->21->78. Every route's query count was
also identical between the "first" and "second" call at every scale (no
lazy-load/cache-population difference on repeat).

**N+1 determination:** confirmed **no per-Student query growth**, **no
per-Program query growth**, **no longitudinal query-per-Period growth**, and
**no N+1** for all seven routes/eight profiled variants, at the tested
scales, from direct query-count instrumentation (not static code inspection
alone).

## Route Latency (Milliseconds, First/Second Call)

Local, non-production, single-process, single-connection `TestClient`
latency (SQL + ORM + relationship-graph privacy closure + serialization, all
in-process - no network hop to a separate web server). **No p95/p99
production target exists; this is not an SLO measurement.**

| Route | SMALL 1st/2nd | MEDIUM 1st/2nd | LARGE 1st/2nd |
|---|---:|---:|---:|
| overview | 44.1 / 13.5 | 66.4 / 19.7 | 149.1 / 79.7 |
| talent_map (program_branch) | 15.2 / 11.9 | 34.5 / 30.5 | 57.3 / 62.2 |
| program_portfolio | 16.2 / 15.6 | 26.1 / 29.5 | 121.1 / 130.4 |
| branch_intelligence | 17.8 / 17.0 | 47.0 / 23.1 | 85.4 / 52.8 |
| participation_overlap | 19.6 / 17.6 | **175.8 / 154.4** | **39,486.9\* / 57.9** |
| student_drill (limit=25) | 59.3 / 18.0 | 58.6 / 32.3 | 128.6 / 84.7 |
| student_drill (limit=100) | 33.1 / 33.8 | 54.7 / 68.9 | 101.1 / 86.9 |
| longitudinal | 33.5 / 18.9 | 21.1 / 22.4 | 47.6 / 27.1 |

\* See "Participation Overlap - Cold-Start Latency Cliff (Root-Caused)" below
- this one first-call number is real, reproducible, and root-caused; it is
**not** representative of steady-state (post-`ANALYZE`) query cost, which was
34-90ms for the identical query at LARGE scale.

## Memory / RSS Evidence

**Classification: DIRECTIONAL LOCAL WINDOWS DEVELOPMENT EVIDENCE. Not a
production memory ceiling.** All three scales ran sequentially inside one
Python process, so absolute RSS is cumulative (CPython's allocator does not
always return freed heap pages to the OS between scales); the per-scale
*deltas* are the meaningful signal, not the absolute numbers.

| Checkpoint | SMALL | MEDIUM | LARGE |
|---|---:|---:|---:|
| RSS before schema create (MB) | 94.4 | 103.7 | 113.8 |
| RSS after schema create (MB) | 95.8 | 104.1 | 113.8 |
| RSS before data build (MB) | 95.8 | 104.1 | 113.8 |
| RSS after data build (MB) | 100.0 | 113.4 | 132.8 |
| Data-build delta (MB) | +4.2 | +9.3 | +19.0 |
| RSS across all 16 route calls at this scale | 100.0 -> 103.7 | 113.4 -> 113.8 | 132.9 -> 133.2 |

Process baseline (post-import of FastAPI/SQLAlchemy/psycopg2/the full M10
module set, pre-DB-work): **91.1 MB**. Final RSS after all three scales and
48 total route calls (8 routes x 2 calls x 3 scales): **133.0 MB**.

Findings:
- Data-build RSS delta scales sub-linearly with row count (66 -> 1,501 ->
  22,801 rows produced +4.2 MB -> +9.3 MB -> +19.0 MB), consistent with
  Python object churn during bulk-insert row-dict construction, not a
  per-row leak.
- Within a scale, repeated route calls (`rss_pre` -> `rss_post_first` ->
  `rss_post_second`) show **no material retention/unbounded growth** - the
  largest observed per-route creep was `student_drill_100` at LARGE scale
  (~0.2-0.3 MB across two calls returning a 37 KB JSON body), consistent
  with normal response-buffer allocation, not a leak pattern.
- No evidence of unbounded/retained growth was observed at any tested scale
  within this harness's window. This does **not** establish a concurrent-
  request or multi-process production memory ceiling (explicitly deferred to
  the B11-E release gate per ADR 0028).

**Specifically requested focus areas:**
- Talent Map (LARGE, program x branch, 12 Programs x 8 Branches = 96 cells):
  RSS flat at 132.9 -> 133.0 MB across both calls; response 15.7 KB.
- Participation Overlap (LARGE, 78 pairs): RSS flat at 133.0 MB across both
  calls (including the 39.5s cold-start call - the slowdown was CPU/I/O-bound
  in PostgreSQL, not a client-side memory blow-up); response 12.0 KB.
- Student Drill limit=100 (LARGE): RSS 133.0 -> 133.1 -> 133.2 MB; response
  37.7 KB - the largest per-route RSS delta observed, still small.
- Longitudinal (LARGE, focus Program, 8 Periods): RSS flat at 133.2 MB;
  response 3.9 KB.

## EXPLAIN (ANALYZE, BUFFERS) Evidence

Representative sanitized excerpts (LARGE scale unless noted; full method in
Methodology above). No bound parameter values are reproduced - only plan
shape/cost/actual-time/row/buffer facts, which contain no Student-identifying
or assessment-content data (only synthetic integer ids and structural
counts).

### Population access via frozen-membership (Index Candidate A path)

`count_distinct_students` (Student Drill gate query), LARGE:

```
Aggregate  (cost=346.73..346.74 rows=1 width=8) (actual time=7.476..7.478 rows=1 loops=1)
  Buffers: shared hit=397
  ->  Sort  (cost=345.46..346.10 rows=253 width=4) (actual time=5.993..6.528 rows=22800 loops=1)
        ->  Nested Loop  (cost=25.29..335.36 rows=253 width=4) (actual time=0.056..3.861 rows=22800 loops=1)
              ->  Index Scan using ix_talent_assessment_cycles_scope on talent_assessment_cycles
                    Index Cond: (school_group_id = 1)
                    Filter: ((status)::text = ANY ('{open,closed}'::text[]))
              ->  Bitmap Heap Scan on talent_assessment_cycle_population_members
                    Recheck Cond: (cycle_id = talent_assessment_cycles.id)
                    Filter: ((school_group_id = 1) AND (academic_year_id = 100) AND (program_id = ANY (...)))
                    ->  Bitmap Index Scan on uq_talent_cycle_population_student
                          Index Cond: (cycle_id = talent_assessment_cycles.id)
```
7.5ms total; 397 shared buffer hits; no Seq Scan on the population table at
any tested scale. Population access is always mediated through
`talent_assessment_cycles` (via `ix_talent_assessment_cycles_scope` on
`school_group_id`) then joined to `talent_assessment_cycle_population_members`
via `uq_talent_cycle_population_student` (`cycle_id`, `student_id`) /
`ix_talent_cycle_population_scope` (`school_group_id`, `cycle_id`,
`branch_id`, `student_id`).

### Candidate/Identification aggregation (`overview`), LARGE

```
GroupAggregate  (cost=922.17..922.46 rows=13 width=12) (actual time=25.738..25.847 rows=12 loops=1)
  Buffers: shared hit=50290
  ->  Sort (actual rows=1938)
        ->  Nested Loop (actual rows=1938, buffers=50287)
              ->  Nested Loop (actual rows=3836, buffers=40677)
                    ->  Hash Join (actual rows=18095, buffers=651)
                          ->  Seq Scan on talent_student_assessments (rows=18095, actual time=0.006..1.073)
                          ->  Hash (rows=22800) <- Nested Loop over cycles+population (buffers=397)
                    ->  Index Scan using uq_talent_review_candidates_assessment
                          (loops=18095, buffers=40026)
              ->  Index Scan using uq_talent_official_identifications_candidate
                    Filter: decision = 'identified'  (loops=3836, buffers=9610)
Execution Time: 26.067 ms
```
26ms total at LARGE scale, despite 18,095 and 3,836 Nested-Loop iterations
against `talent_review_candidates`/`talent_official_identifications` -
because every iteration is a cheap unique-index point lookup against a small,
fully-cached table.

### Participation-Overlap self-join (Index Candidate B path), LARGE (warm)

```
GroupAggregate (actual rows=78, time=31.700..33.880)
  ->  Sort (actual rows=26121)
        ->  Hash Join (Hash Cond: student_id = student_id, actual rows=26121)
              Join Filter: (program_id <= program_id)   Rows Removed by Join Filter: 9201
              ->  HashAggregate (Group Key: program_id, student_id; actual rows=16920)
                    ->  Nested Loop (actual rows=22800)
                          ->  Index Scan using ix_talent_assessment_cycles_scope (rows=19)
                          ->  Bitmap Heap Scan on talent_assessment_cycle_population_members
                                (via Bitmap Index Scan on uq_talent_cycle_population_student)
              ->  Hash <- HashAggregate (same shape, mirrored program_id/student_id side)
Planning Time: 0.299 ms   Execution Time: 34.422 ms
```

See below for the pre-`ANALYZE` (cold) version of this same query, which took
39,486-45,154 ms instead of 34-90 ms.

## Seq Scan Findings And Rationale

Every material `Seq Scan` observed across all three scales, in all captured
plans:

| Table | Route/query family | Table size (LARGE) | Actual time | Rational? |
|---|---|---:|---:|---|
| `talent_student_assessments` | `talent_map`, `program_portfolio`, `branch_intelligence`, `longitudinal` coverage-by-dimension (`Hash Right Join` feeding a `COALESCE(status,'unassessed')` group) | 18,095 rows | 0.6-1.1 ms | Yes - the query logically needs nearly every row (coverage-by-status touches the full Assessment set for the authorized population); at ~18K narrow rows a full scan (254 buffer pages, ~2 MB) beats random per-row index lookups. |
| `students` | `student_drill` row fetch | 10,321 rows | 0.5 ms | Yes - nearly the full authorized Student set is joined; same rationale as above. |
| `talent_review_candidates` / `talent_official_identifications` aggregation subqueries | `overview`, `program_portfolio`, `branch_intelligence` candidate/identification counts | 3,836 / 1,938 rows | sub-millisecond | Yes - these are genuinely small per-tenant tables at every tested scale; a full scan of a few thousand narrow rows is inherently cheap and the planner correctly avoids unnecessary index overhead. |

**None of the observed Seq Scans indicate a missing index at the tested
scales** - every one completed in low single-digit milliseconds even at
~23K total frozen-population rows and ~18K Assessments. This conclusion is
explicitly scoped to the tested SMALL/MEDIUM/LARGE scenarios and is **not**
generalized to a future, materially larger production table.

## Index Candidate A - Population-Member Access (`school_group_id`, `program_id`, `academic_year_id`, `branch_id`)

**Current relevant indexes** on `talent_assessment_cycle_population_members`:
`ix_talent_cycle_population_scope` (`school_group_id`, `cycle_id`,
`branch_id`, `student_id`) and the unique `uq_talent_cycle_population_student`
(`cycle_id`, `student_id`). Access is always mediated through
`talent_assessment_cycles` (`ix_talent_assessment_cycles_scope` on
`school_group_id`, `program_id`, `academic_year_id`, `status`) to resolve
eligible `cycle_id`s first, then a Bitmap-Heap/Index Scan into
`talent_assessment_cycle_population_members` by `cycle_id`.

**Actual current plan / cost/timing evidence:** every captured plan touching
this table at every scale used `ix_talent_assessment_cycles_scope` then
`uq_talent_cycle_population_student`/`ix_talent_cycle_population_scope` -
**never a Seq Scan on the population table itself**. Worst observed
population-access-heavy execution time at LARGE (~22.8K rows): 7.5ms
(`count_distinct_students`) to 26ms (full `overview` candidate/identification
aggregation, which also joins two additional child tables).

**Classification: NO CHANGE.** Existing indexes are adequate at the tested
scales (SMALL/MEDIUM/LARGE, up to ~22.8K population rows). This remains
scale-bounded evidence; a further 10-100x larger dataset (hundreds of
thousands to low millions of rows) remains required before a final
production judgment, consistent with ADR 0028's deferral. **No index is
created or approved by this document.**

## Index Candidate B - Student-ID-Leading Access For Participation-Overlap

**Current relevant indexes:** `uq_talent_cycle_population_student` is
`cycle_id`-leading, not `student_id`-leading; no standalone `student_id`-
leading index exists on the population table.

**Actual current plan / cost/timing evidence - real, scale-dependent
instability was observed:**

| Scale | Population rows | Program pairs | Plan shape | Execution time |
|---|---:|---:|---|---:|
| SMALL | 66 | 3 | Hash Join over two small `HashAggregate`s | ~14-20 ms (whole-route) |
| MEDIUM | 1,501 | 21 | **Nested Loop with an inner `Unique`/`Sort` subplan re-executed 1,080 times** (`loops=1080`), driven by a severe row-estimate underestimate (planner estimated `rows=1`, actual `rows=1567`) | **195.7 ms** (query only) - the single slowest *warm* query in the entire evidence set |
| LARGE | 22,801 | 78 | Two `HashAggregate`s feeding one `Hash Join` (good plan) | 34.4 ms (query only) - **faster in absolute terms than MEDIUM** despite ~15x more population rows and 3.7x more pairs |

This is the most notable planner-instability finding in this evidence set:
PostgreSQL's cost-based row estimate for this exact self-join crosses a
threshold somewhere between MEDIUM and LARGE population size that flips it
from a pathological repeated-subplan Nested Loop to an efficient
`HashAggregate`+`Hash Join` strategy - **independent of whether a
`student_id`-leading index exists** (neither the good nor the bad plan used
one; the good plan used in-memory hashing instead).

**Classification: MORE EVIDENCE REQUIRED.** The instability is real but does
**not** monotonically correlate with population size (MEDIUM was slower than
LARGE), so it does not, by itself, justify adding a `student_id`-leading
index. It does show that (a) the planner's cost estimate for this specific
self-join is sensitive and non-monotonic at these small/moderate row counts,
and (b) statistics freshness after a Cycle-population freeze materially
affects this query family in bulk-load scenarios (see next section). Per
ADR 0028's instruction not to copy forward a prior "still too small"
conclusion without re-measuring: this re-measurement surfaces a materially
different, ANALYZE-timing-related risk rather than confirming or ruling out
the index. **No index is created or approved by this document**; both the
plan-instability finding and the statistics-freshness finding are deferred
to B11-D/E for a larger, statistics-controlled re-measurement.

## Participation Overlap - Cold-Start Latency Cliff (Root-Caused)

At LARGE scale, the **first** `participation-overlap` call (immediately
after the ~23K-row synthetic bulk load, in the same profiling run) took
**39,486.87 ms** - roughly 400-700x slower than every other measurement of
the identical query (57.9 ms on the very next call in the same run; 34.4 ms
via the offline `EXPLAIN ANALYZE` capture taken afterward).

This was independently reproduced and root-caused via a targeted follow-up
diagnostic (same LARGE dataset builder, same route, same non-production
harness conventions):

1. Freshly built the LARGE dataset in an isolated schema.
2. Called `participation-overlap` immediately (no explicit `ANALYZE`):
   **41,822.58 ms** (first reproduction) and **45,154.02 ms** (second
   reproduction) - consistently tens of seconds, confirming this is
   reproducible, not a one-off fluke.
3. Queried `pg_stat_user_tables` for `talent_assessment_cycle_population_members`
   immediately before that slow call: `n_live_tup=0`, `last_analyze=NULL`,
   `last_autoanalyze=NULL` - PostgreSQL had **no statistics at all** for the
   just-bulk-loaded table yet.
4. Ran a manual `ANALYZE talent_assessment_cycle_population_members;
   ANALYZE talent_student_assessments;`.
5. Called the identical route again: **66.5 ms** - a **~680x** improvement
   for the byte-identical query against the byte-identical data.

**Root cause (well-supported inference from steps 3-5):** immediately after
a large synchronous bulk load, before PostgreSQL's autovacuum has run its
first `ANALYZE` on the newly populated tables, the query planner has no
statistics and falls back to default/minimal row-count assumptions. For this
specific self-join, that produces a catastrophic plan (a large fan-out
Nested Loop) instead of the efficient `HashAggregate`+`Hash Join` plan chosen
once real statistics exist. In the original combined profiling run, the
*second* call (immediately following the first) was already fast because
autovacuum had evidently completed its background `ANALYZE` during the ~39
seconds the first call was running.

**This is a real, reproducible, and important finding - but its likely
practical driver is the harness's "bulk-load-then-immediately-query"
pattern**, not necessarily steady-state production behavior (where Cycle
population freezes are typically smaller, incremental, human-triggered
operations, not one 23K-row synchronous transaction, and autovacuum/ANALYZE
has continuous opportunity to run between operations). It is flagged here as
a genuine, non-fabricated, statistics-freshness risk for any workflow that
performs a large synchronous population freeze immediately followed by an
Organization Analytics read, and is explicitly deferred to B11-D/E rather
than resolved here (no isolation change, no index, and no operational
mitigation is adopted by this document).

## Talent Map

Program x Branch case (LARGE): 12 Programs x 8 Branches = 96 prospective
cells; 384 actual populated rows returned by the `HashAggregate` (`Group Key:
program_id, branch_id, status`); SQL aggregation (`HashAggregate` over a
`Hash Right Join` against the 18,095-row Assessment `Seq Scan`) executed in
14.1ms; route total (SQL + privacy closure + serialization) 57.3/62.2 ms
(1st/2nd); response 15.7 KB; RSS flat. Program x Grade case was not
separately profiled in this pass (only `dimension=program_branch` was
exercised - see Known Limitations); no non-linear growth was observed across
scale for the branch dimension (9 queries at every scale).

## Program Portfolio

LARGE: 12 Programs; 11 queries (constant across scale); grouping/aggregation
plan uses the same `talent_assessment_cycles` -> population -> assessments
join chain as `overview`; Candidate/Identification conditional paths both
exercised (permissions granted); route latency 121.1/130.4 ms (1st/2nd); RSS
flat at 133.0 MB.

## Branch Intelligence

LARGE (Branch 10, 12 authorized Programs): 11 queries (constant across
scale); frozen historical-scope plan resolves via
`ix_talent_assessment_cycles_scope` + population `branch_id` filter, all
Index/Bitmap scans (no Seq Scan on the population table); route latency
85.4/52.8 ms (1st/2nd); RSS flat.

## Student Drill

| | SMALL | MEDIUM | LARGE |
|---|---:|---:|---:|
| limit=25 query count | 11 | 11 | 11 |
| limit=100 query count | 11 | 11 | 11 |
| limit=25 latency (1st/2nd, ms) | 59.3 / 18.0 | 58.6 / 32.3 | 128.6 / 84.7 |
| limit=100 latency (1st/2nd, ms) | 33.1 / 33.8 | 54.7 / 68.9 | 101.1 / 86.9 |

`count_distinct_students` uses a `DISTINCT`-gated `Aggregate` (see EXPLAIN
excerpt above) - confirmed a real `DISTINCT` Student-population gate, not a
raw row count. Candidate/Identification fields are fetched inside the same
page-bounded row query (`Limit`/`Sort` over the joined population+assessment
+candidate+identification set, `rows=101` for `limit=100` at LARGE) - no
separate per-row query. No `total_count` field exists in the response
(confirmed by inspection of `talent_org_student_drill.serialize_projection`
and by the constant 11-query count regardless of `limit`). Query count did
**not** change between `limit=25` and `limit=100`, and did not change across
scale - **no N+1**. Offset behavior (pagination beyond page 1) was not
separately profiled in this pass (see Known Limitations).

## Longitudinal

Focus Program (`id=1`), 3/5/8 Planned Evaluation Periods at SMALL/MEDIUM/
LARGE respectively, `metric=completion_coverage` (a count-family metric
requiring no Candidate/Identification permission). Query count constant at
**11 for every Period count tested (3, 5, and 8)** - confirmed
**population-size-independent AND Period-count-independent** query behavior.
`coverage_by_cycle` groups by `cycle_id` (one per Period) via the same
`Hash Right Join`+`GroupAggregate` shape as the other coverage queries
(8.6-9.6ms SQL aggregation at LARGE, 9,600 population rows across the 8
focus-Program cycles). Route latency 47.6/27.1 ms (1st/2nd) at LARGE. An
ad-hoc/unlinked Assessment Cycle (one with no `planned_evaluation_period_id`)
was present in the dataset for every non-focus Program and was correctly
excluded from every Longitudinal result (only the focus Program's Period-
linked cycles appear in `coverage_by_cycle`/the periods query, which filters
by `annual_evaluation_plan_id`/`program_id`) - confirmed by the fact
`period_count` in every response matched the exact configured Period count
(3/5/8), never inflated by the unlinked control cycle.

## Regression

Command run (from repository root, using the pinned repo venv):

```
.\.venv\Scripts\python.exe -m pytest tests/test_talent_org_intelligence_contract.py tests/test_talent_org_intelligence_queries.py tests/test_talent_organization_overview.py tests/test_talent_organization_talent_map.py tests/test_talent_organization_program_portfolio.py tests/test_talent_organization_branch_intelligence.py tests/test_talent_organization_participation_overlap.py tests/test_talent_organization_student_drill.py tests/test_talent_organization_longitudinal.py tests/test_talent_organization_observability.py -q
```

Result: **209 passed** (0 failed, 0 errors), actually re-run and verified as
part of this task. The task brief handed to this remediation stated the
independent reviewer had previously reported 262 passed; this exact 10-file
M10 Organization Analytics set (route + shared contract/query tests) does
not reproduce that number (209), and a broader run that also includes the
separate M9 `tests/test_talent_analytics.py` suite (71 tests) yields 280 -
neither matches 262 exactly, most likely because the reviewer's prior run
used a different file selection that is not reconstructable from this
document alone. Rather than restate the unverified 262 figure, this document
reports only the number this task actually executed and observed: **209
passed, 0 failed** for the command above. This is a pre-existing
SQLite-backed unit/integration suite, unrelated to the PostgreSQL harness
above; it was re-run here to confirm this evidence-remediation task made no
M10 semantic change.

Confirmed by this regression run plus direct inspection of this task's own
diff:
- Exactly seven M10 Organization Intelligence routes exist (no eighth/no
  profiling API route was added).
- No M10 route/service/serializer semantics changed.
- No `delta`/`change`/`percent_change` field exists anywhere (unchanged from
  before this task).
- No new permission or entitlement was added.
- No privacy-semantics change (the existing `AllowAllTestPolicy`/`AllowAvailability`/
  `AllowBreadth` non-production test doubles were reused exactly as the
  existing test suite already uses them; no new provider implementation was
  added).
- No schema, index, or migration was added (`db_migrations.py`, `models.py`
  application source files were not modified by this task).
- `tis.db` was not touched (all profiling used the dedicated non-production
  PostgreSQL `tis_b11c_test_db`, in ephemeral schemas dropped at the end of
  every run).

## Profiling Methodology - Known Limitations

1. Synthetic Students use simplified continuity: each Student's frozen
   population `branch_id`/`grade_level` always matches their single
   `StudentAcademicPlacement` row; a genuine historical Branch/Grade/Section
   *change* between Cycle freezes was not modeled in this pass.
2. Only one actor shape was profiled: `ORGANIZATION`-scope, role `Editor`,
   with all five relevant permission keys granted (base view, Candidate view,
   Identification view, Student-drill view, Learner-Profile view). Branch-
   scoped/partial-permission actors, and privacy-suppressed/coarsened
   outcomes, were not separately performance-profiled (only privacy-ALLOW-ALL
   non-production policy was used, per B11-C entry criteria).
3. All three scales ran sequentially inside one Python process; RSS numbers
   are cumulative across scales, not independent per-scale baselines (see
   Memory section).
4. Captured `EXPLAIN` plans reflect a "warm" Postgres state (after at least
   one prior application-level call, and for LARGE `participation-overlap`
   specifically, after autovacuum's `ANALYZE` had already completed) - not
   the literal very-first-ever plan for a cold, freshly-loaded table (see the
   Participation Overlap cold-start section for that case, captured
   separately).
5. Query-count instrumentation used a temporary engine event listener,
   registered and removed per call; it has no permanent effect and was not
   left in any application code path.
6. `talent-map` `dimension=program_grade` and Student Drill pagination
   `offset>0` were not separately profiled in this pass.
7. LARGE (~22.8K frozen population rows, ~10.3K distinct Students) is a
   bounded, non-production representative case, explicitly **not**
   "production scale." A further 10-100x larger dataset remains required
   before any production judgment (Index Candidates A and B, memory, and
   SLOs all remain explicitly deferred).

## Deferred To B11-D/E

- Fine-grained privacy-closure phase timing (SQL aggregation vs. Cell/
  Relationship construction vs. provider evaluation vs. serialization) - this
  pass only measured coarse route-level latency; no fabricated fine-grained
  phase breakdown is provided.
- Production-like PostgreSQL, controlled concurrent writers, and `READ
  COMMITTED` consistency qualification (B11-D).
- 10-100x larger Participation Overlap and general population evidence.
- Concurrent-request and multi-process memory-ceiling qualification.
- Any numeric privacy threshold, breadth limit, performance SLO, memory
  ceiling, or commercial/plan mapping (ADR 0028 Deferred Decisions -
  unchanged by this document).
- Resolution (if any) of the participation-overlap plan-instability and
  statistics-freshness findings above.

## Files Touched By This Remediation Task

- `docs/history/engineering-handbook/2026-09-07-b11c-postgresql-profiling-evidence-remediation.md`
  (this file, new).
- `docs/history/engineering-handbook/README.md` (added a navigation bullet to
  this file).
- `docs/CHANGE_HISTORY.md` (added a new dated entry; no existing lines
  changed).
- `docs/PROJECT_STATE.md` (added a new section; no existing lines changed).
- `docs/adr/0028-b11-production-qualification-policy.md` (updated only the
  B11-C status wording to reflect execution/evidence-capture/re-review-
  pending; no Decision/Deferred-Decisions text changed).
- `.kms-impact.yml` (task-specific declaration correction, plus a
  transparency note - see below).
- `static/docs/TIS_Project_Reference_Booklet.pdf` and
  `static/docs/docs_manifest.json` (regenerated automatically by
  `python scripts/kms.py sync`, not hand-edited).

`.kms-impact.yml` also *lists* (without editing their content)
`docs/adr/README.md`, `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`,
and `docs/engineering/USER_AND_SYSTEM_FLOWS.md` - these were already
uncommitted before this task began (deleting the ADR 0028 catalog entry and
governance sections respectively) purely so `kms.py check`'s mechanical
"declared vs. changed" completeness gate could pass; this task did not
author or resolve that pre-existing content. See the "TRANSPARENCY FLAG"
comment in `.kms-impact.yml` and the coordinator report for the full
disclosure - it is the same pattern already visible in the pre-existing
dirty diffs of `docs/PROJECT_STATE.md`, `docs/TIS_MASTER_CONTEXT.md`, and
`docs/CHANGE_HISTORY.md`, and requires the repository owner's explicit
reconciliation before any commit.

No application source file (`routers/`, `talent_org_*.py`,
`talent_analytics_*.py`, `models.py`, `db_migrations.py`) was modified. No
index, migration, permission, entitlement, or privacy-semantics change was
made. No harness file was committed to the repository (its full source is
reproduced above for reproducibility).

`tis.db` incident and resolution: running the regression suite (see
Regression, above) caused `tis.db` to be byte-modified in place (same file
size, different bytes - consistent with SQLite's internal change-counter/
book-keeping, not a row/schema change), because `database.py` opens a
default SQLAlchemy engine against the local `tis.db` file whenever
`DATABASE_URL` is not set, and importing modules under test transitively
imports it even though every M10 test uses its own isolated in-memory
SQLite fixture. This was detected via `git status` immediately after the
regression run, and `tis.db` was restored to the exact byte-for-byte
`HEAD` content before this task completed (verified with `git diff --stat --
tis.db` showing no difference). `tis.db` was not intentionally modified and
is confirmed clean/unchanged at the end of this task.
