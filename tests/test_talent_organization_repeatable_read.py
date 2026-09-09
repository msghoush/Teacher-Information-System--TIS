"""M10 B11-E: dedicated REPEATABLE READ transaction boundary (ADR 0029).

Backend-conditional wiring tests (top of file) always run and require no
PostgreSQL - they prove the new `dependencies.get_m10_organization_analytics_db`
dependency is distinct from the default `get_db`, does not alter the default
`SessionLocal`/`engine` used by every other route, and does not raise on a
non-PostgreSQL backend (the SQLite fallback this whole suite otherwise runs
on, since `REPEATABLE READ` is a PostgreSQL-only isolation string).

The live PostgreSQL tests below (skipped unless `TIS_TEST_POSTGRESQL_URL` is
set, matching the existing `tests/test_postgresql_migration_transactions.py`
convention) re-test the exact same-request mixed-snapshot inconsistencies
B11-D proved live under `READ COMMITTED`
(`docs/history/engineering-handbook/2026-09-07-b11d-postgresql-concurrency-consistency-qualification.md`)
under the permanent B11-E implementation, using the identical deterministic
"commit a real domain-valid write between two of the route's own statements"
technique B11-D used (chosen there, and here, over a non-deterministic
thread-timing race, because it is fully reproducible). Each live test also
reproduces the ORIGINAL vulnerability, live, against the exact same dataset
and interleave point, via a plain `READ COMMITTED` session (no isolation
override) - so this file proves both that the vulnerability is real for this
dataset/harness and that the ADR 0029 fix resolves it, in one place.

No index, migration, schema, permission, or entitlement change is exercised
or implied by this file. Every schema created here is a dedicated, ephemeral,
per-test PostgreSQL schema (`tis_b11e_<uuid>`), created and dropped by the
test itself - no rows are left behind in the shared non-production database.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import database
import models
import talent_org_intelligence_service as svc
import talent_org_student_drill as student_drill
from dependencies import get_db, get_m10_organization_analytics_db
from routers import talent_organization_analytics as route
from saas import entitlement_service as saas_entitlement_service
from saas.models import EntitlementDefinition
from talent_organization_analytics_providers import ORGANIZATION_INTELLIGENCE_FEATURE_KEY
from talent_analytics_privacy import (
    AllowAllTestPolicy,
    DeterministicSuppressionTestPolicy,
    resolve_privacy_policy_provider,
)
from talent_org_intelligence_service import (
    resolve_organization_analytics_availability_provider,
    resolve_organization_analytics_breadth_policy,
)
from test_talent_org_intelligence_queries import AllowAvailability, AllowBreadth, actor


POSTGRESQL_URL = os.getenv("TIS_TEST_POSTGRESQL_URL", "")
requires_postgresql = pytest.mark.skipif(
    not POSTGRESQL_URL.startswith("postgresql"),
    reason="TIS_TEST_POSTGRESQL_URL is required for live PostgreSQL B11-E REPEATABLE READ qualification",
)

PRIMARY_GROUP = 1
FOREIGN_GROUP = 2
PRIMARY_AY = 100
FOREIGN_AY = 200
PRIMARY_BRANCH = 10
FOREIGN_BRANCH = 900
PROGRAM_ALPHA = 1
PROGRAM_BETA = 2
FOREIGN_PROGRAM = 90
CYCLE_ALPHA_1 = 201  # closed, period 1
CYCLE_ALPHA_2 = 202  # open, period 2
CYCLE_BETA = 203  # open, standalone
FOREIGN_CYCLE = 900
NOW = datetime(2026, 9, 1)


# ---------------------------------------------------------------------------
# Backend-conditional wiring safety - always run, no PostgreSQL required.
# ---------------------------------------------------------------------------

def test_m10_dependency_is_a_distinct_callable_from_get_db():
    assert get_m10_organization_analytics_db is not get_db


def test_m10_sessionmaker_shares_the_plain_engine_on_non_postgresql_backends():
    # ADR 0029 requires the REPEATABLE READ override to be strictly
    # backend-conditional. This test process is expected to run against the
    # SQLite fallback (as the rest of this suite does); if it is ever run
    # against a PostgreSQL `DATABASE_URL` instead, the wrapped-bind assertion
    # does not apply, so this test is skipped rather than failing.
    if database.DATABASE_URL.startswith("postgresql"):
        pytest.skip("process DATABASE_URL is PostgreSQL; the SQLite-sharing guarantee does not apply here")
    assert database._m10_organization_analytics_bind is database.engine


def test_m10_dependency_does_not_raise_on_the_configured_backend():
    gen = get_m10_organization_analytics_db()
    session = next(gen)
    try:
        assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        gen.close()


def test_default_get_db_dependency_is_unaffected():
    gen = get_db()
    session = next(gen)
    try:
        assert session.bind is database.engine
    finally:
        gen.close()


# ---------------------------------------------------------------------------
# Live PostgreSQL dataset builder and writer helpers.
# ---------------------------------------------------------------------------

def _engine_for_schema(schema: str):
    return create_engine(
        POSTGRESQL_URL,
        connect_args={
            "connect_timeout": 10,
            "options": f"-c search_path={schema} -c lock_timeout=5s -c statement_timeout=30s",
        },
    )


def _build_dataset(engine) -> None:
    """A small, real M10 dataset: two primary Programs sharing overlap, one
    tiny isolated foreign tenant, and several already-frozen 'unassessed'
    members left as live writer targets. 14 frozen population members, 10
    distinct Students, 1 Candidate, 1 Identification."""

    Session = sessionmaker(bind=engine)
    session = Session()
    # Each layer is committed before the next is added - PostgreSQL enforces
    # FK constraints per-statement (unlike this suite's other SQLite
    # fixtures), and SQLAlchemy's bulk "insertmany" batching does not
    # reliably topologically re-order rows added across separate `add_all`
    # calls within one flush. Matches the proven B11-C/B11-D harness pattern.
    session.add_all((
        models.SchoolGroup(id=PRIMARY_GROUP, name="B11E Primary"),
        models.SchoolGroup(id=FOREIGN_GROUP, name="B11E Foreign"),
    ))
    session.commit()
    session.add_all((
        models.Branch(id=PRIMARY_BRANCH, school_group_id=PRIMARY_GROUP, name="Main", status=True),
        models.Branch(id=FOREIGN_BRANCH, school_group_id=FOREIGN_GROUP, name="ForeignBranch", status=True),
        models.AcademicYear(id=PRIMARY_AY, school_group_id=PRIMARY_GROUP, year_name="2026-2027"),
        models.AcademicYear(id=FOREIGN_AY, school_group_id=FOREIGN_GROUP, year_name="2026-2027"),
    ))
    session.commit()
    session.add_all((
        models.TalentProgram(id=PROGRAM_ALPHA, school_group_id=PRIMARY_GROUP, name="Alpha", status="active"),
        models.TalentProgram(id=PROGRAM_BETA, school_group_id=PRIMARY_GROUP, name="Beta", status="active"),
        models.TalentProgram(id=FOREIGN_PROGRAM, school_group_id=FOREIGN_GROUP, name="ForeignProgram", status="active"),
    ))
    session.commit()
    session.add_all((
        models.TalentProgramAcademicYearConfiguration(id=PROGRAM_ALPHA, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_ALPHA, academic_year_id=PRIMARY_AY, is_enabled=True, eligible_grade_levels_csv="1,2"),
        models.TalentProgramAcademicYearConfiguration(id=PROGRAM_BETA, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_BETA, academic_year_id=PRIMARY_AY, is_enabled=True, eligible_grade_levels_csv="1,2"),
        models.TalentProgramAcademicYearConfiguration(id=FOREIGN_PROGRAM, school_group_id=FOREIGN_GROUP, program_id=FOREIGN_PROGRAM, academic_year_id=FOREIGN_AY, is_enabled=True, eligible_grade_levels_csv="1"),
    ))
    session.commit()
    session.add_all((
        models.TalentProgramFrameworkVersion(id=101, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_ALPHA, version_number=1, status="active", title="Alpha", revision=1, semantic_fingerprint="a" * 64),
        models.TalentProgramFrameworkVersion(id=102, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_BETA, version_number=1, status="active", title="Beta", revision=1, semantic_fingerprint="b" * 64),
        models.TalentProgramFrameworkVersion(id=190, school_group_id=FOREIGN_GROUP, program_id=FOREIGN_PROGRAM, version_number=1, status="active", title="Foreign", revision=1, semantic_fingerprint="c" * 64),
    ))
    session.commit()
    session.add(models.TalentAnnualEvaluationPlan(
        id=501, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_ALPHA, academic_year_id=PRIMARY_AY,
        program_academic_year_configuration_id=PROGRAM_ALPHA, status="active", revision=1, activated_at=NOW,
    ))
    session.commit()
    session.add_all((
        models.TalentPlannedEvaluationPeriod(id=601, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_ALPHA, academic_year_id=PRIMARY_AY, annual_evaluation_plan_id=501, sequence=1, label="P1", normalized_label="p1", is_required=True, status="planned"),
        models.TalentPlannedEvaluationPeriod(id=602, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_ALPHA, academic_year_id=PRIMARY_AY, annual_evaluation_plan_id=501, sequence=2, label="P2", normalized_label="p2", is_required=True, status="planned"),
    ))
    session.commit()
    session.add_all((
        models.TalentAssessmentCycle(id=CYCLE_ALPHA_1, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_ALPHA, academic_year_id=PRIMARY_AY, framework_version_id=101, planned_evaluation_period_id=601, title="Alpha Cycle 1", status="closed", revision=1, population_effective_at=NOW),
        models.TalentAssessmentCycle(id=CYCLE_ALPHA_2, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_ALPHA, academic_year_id=PRIMARY_AY, framework_version_id=101, planned_evaluation_period_id=602, title="Alpha Cycle 2", status="open", revision=1, population_effective_at=NOW),
        models.TalentAssessmentCycle(id=CYCLE_BETA, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_BETA, academic_year_id=PRIMARY_AY, framework_version_id=102, title="Beta Cycle", status="open", revision=1, population_effective_at=NOW),
        models.TalentAssessmentCycle(id=FOREIGN_CYCLE, school_group_id=FOREIGN_GROUP, program_id=FOREIGN_PROGRAM, academic_year_id=FOREIGN_AY, framework_version_id=190, title="Foreign Cycle", status="open", revision=1, population_effective_at=NOW),
    ))
    session.commit()
    session.add_all((
        models.TalentReviewCandidatePolicy(id=PROGRAM_ALPHA, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_ALPHA, framework_version_id=101, is_enabled=True, match_mode="all"),
        models.TalentReviewCandidatePolicy(id=PROGRAM_BETA, school_group_id=PRIMARY_GROUP, program_id=PROGRAM_BETA, framework_version_id=102, is_enabled=True, match_mode="all"),
    ))
    session.commit()

    students: list = []
    placements: list = []
    population: list = []
    assessments: list = []
    member_id = 0

    def add_student(student_id: int, grade: str, first_name: str) -> None:
        students.append(models.Student(id=student_id, school_group_id=PRIMARY_GROUP, first_name=first_name, last_name=f"S{student_id}", status="active"))
        placements.append(models.StudentAcademicPlacement(
            id=student_id, school_group_id=PRIMARY_GROUP, student_id=student_id, academic_year_id=PRIMARY_AY,
            branch_id=PRIMARY_BRANCH, grade_level=grade, section_name="A", effective_from=NOW, status="active",
        ))

    def add_member(cycle_id: int, program_id: int, framework_id: int, student_id: int, grade: str) -> int:
        nonlocal member_id
        member_id += 1
        population.append(models.TalentAssessmentCyclePopulationMember(
            id=member_id, school_group_id=PRIMARY_GROUP, cycle_id=cycle_id, program_id=program_id,
            academic_year_id=PRIMARY_AY, framework_version_id=framework_id, student_id=student_id,
            academic_placement_id=student_id, branch_id=PRIMARY_BRANCH, grade_level=grade,
            section_name="A", population_effective_at=NOW,
        ))
        return member_id

    # Alpha cycle 1 (period 1, closed): 6 members/students; members 1-2
    # already completed (member 1 also has the dataset's one Candidate +
    # Identification); members 3-6 are frozen but `unassessed` - live
    # writer targets for the tests below.
    for i in range(1, 7):
        sid = 1000 + i
        add_student(sid, "1", f"Alpha1-{i}")
        mid = add_member(CYCLE_ALPHA_1, PROGRAM_ALPHA, 101, sid, "1")
        if i <= 2:
            assessments.append(models.TalentStudentAssessment(
                id=700 + i, school_group_id=PRIMARY_GROUP, cycle_id=CYCLE_ALPHA_1, cycle_population_member_id=mid,
                student_id=sid, program_id=PROGRAM_ALPHA, academic_year_id=PRIMARY_AY, framework_version_id=101,
                status="completed",
            ))
    candidate = models.TalentReviewCandidate(
        id=801, school_group_id=PRIMARY_GROUP, cycle_id=CYCLE_ALPHA_1, cycle_population_member_id=1,
        student_id=1001, program_id=PROGRAM_ALPHA, academic_year_id=PRIMARY_AY, framework_version_id=101,
        assessment_id=701, policy_id=PROGRAM_ALPHA, match_mode="all", evaluation_fingerprint="d" * 64,
        evaluation_snapshot_json="{}", status="reviewed",
    )
    identification = models.TalentOfficialIdentification(
        id=901, school_group_id=PRIMARY_GROUP, cycle_id=CYCLE_ALPHA_1, cycle_population_member_id=1,
        student_id=1001, program_id=PROGRAM_ALPHA, academic_year_id=PRIMARY_AY, framework_version_id=101,
        assessment_id=701, review_candidate_id=801, decision="identified",
    )

    # Alpha cycle 2 (period 2, open): reuse students 1-2 across periods, add 2 new.
    for i in range(1, 3):
        add_member(CYCLE_ALPHA_2, PROGRAM_ALPHA, 101, 1000 + i, "1")
    for i in (7, 8):
        sid = 1000 + i
        add_student(sid, "2", f"Alpha2-{i}")
        add_member(CYCLE_ALPHA_2, PROGRAM_ALPHA, 101, sid, "2")

    # Beta cycle (open, standalone): reuse students 1-2 (participation
    # overlap with Alpha), add 2 new.
    for i in range(1, 3):
        add_member(CYCLE_BETA, PROGRAM_BETA, 102, 1000 + i, "1")
    for i in (9, 10):
        sid = 1000 + i
        add_student(sid, "1", f"Beta-{i}")
        add_member(CYCLE_BETA, PROGRAM_BETA, 102, sid, "1")

    # Foreign tenant: one tiny isolated population (tenant-isolation control).
    students.append(models.Student(id=9001, school_group_id=FOREIGN_GROUP, first_name="Foreign", last_name="Student", status="active"))
    placements.append(models.StudentAcademicPlacement(
        id=9001, school_group_id=FOREIGN_GROUP, student_id=9001, academic_year_id=FOREIGN_AY,
        branch_id=FOREIGN_BRANCH, grade_level="1", section_name="A", effective_from=NOW, status="active",
    ))
    population.append(models.TalentAssessmentCyclePopulationMember(
        id=9001, school_group_id=FOREIGN_GROUP, cycle_id=FOREIGN_CYCLE, program_id=FOREIGN_PROGRAM,
        academic_year_id=FOREIGN_AY, framework_version_id=190, student_id=9001, academic_placement_id=9001,
        branch_id=FOREIGN_BRANCH, grade_level="1", section_name="A", population_effective_at=NOW,
    ))

    session.add_all(students)
    session.commit()
    session.add_all(placements)
    session.commit()
    session.add_all(population)
    session.commit()
    session.add_all(assessments)
    session.commit()
    session.add(candidate)
    session.commit()
    session.add(identification)
    session.commit()
    session.add_all(
        models.RolePermission(school_group_id=PRIMARY_GROUP, role="Editor", permission_key=key, is_allowed=True)
        for key in (
            "talent_analytics.view", "talent_review_candidates.view",
            "talent_official_identifications.view", "talent_analytics.view_students",
            "talent_learner_profiles.view",
        )
    )
    session.commit()
    session.close()


def _writer_complete_assessment(engine, *, member_id: int, student_id: int, cycle_id: int, program_id: int, framework_version_id: int, assessment_id: int, with_candidate: bool, candidate_id: int = 0, policy_id: int = 0) -> None:
    """A separate, already-committed writer Session performing one real
    domain-valid write (matching B11-D's own writer shape): completing an
    already-frozen `unassessed` Assessment, optionally with a Candidate."""

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        session.add(models.TalentStudentAssessment(
            id=assessment_id, school_group_id=PRIMARY_GROUP, cycle_id=cycle_id, cycle_population_member_id=member_id,
            student_id=student_id, program_id=program_id, academic_year_id=PRIMARY_AY, framework_version_id=framework_version_id,
            status="completed",
        ))
        session.commit()
        if with_candidate:
            session.add(models.TalentReviewCandidate(
                id=candidate_id, school_group_id=PRIMARY_GROUP, cycle_id=cycle_id, cycle_population_member_id=member_id,
                student_id=student_id, program_id=program_id, academic_year_id=PRIMARY_AY, framework_version_id=framework_version_id,
                assessment_id=assessment_id, policy_id=policy_id, match_mode="all", evaluation_fingerprint="e" * 64,
                evaluation_snapshot_json="{}", status="reviewed",
            ))
            session.commit()
    finally:
        session.close()


def _writer_add_new_frozen_member(engine, *, member_id: int, student_id: int, cycle_id: int, program_id: int, framework_version_id: int, grade: str = "1") -> None:
    """A separate, already-committed writer Session adding one brand-new
    frozen population member for a brand-new Student - a valid
    population-freeze-style write, matching B11-D's Student Drill write."""

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        session.add(models.Student(id=student_id, school_group_id=PRIMARY_GROUP, first_name="New", last_name=f"S{student_id}", status="active"))
        session.add(models.StudentAcademicPlacement(
            id=student_id, school_group_id=PRIMARY_GROUP, student_id=student_id, academic_year_id=PRIMARY_AY,
            branch_id=PRIMARY_BRANCH, grade_level=grade, section_name="A", effective_from=NOW, status="active",
        ))
        session.add(models.TalentAssessmentCyclePopulationMember(
            id=member_id, school_group_id=PRIMARY_GROUP, cycle_id=cycle_id, program_id=program_id,
            academic_year_id=PRIMARY_AY, framework_version_id=framework_version_id, student_id=student_id,
            academic_placement_id=student_id, branch_id=PRIMARY_BRANCH, grade_level=grade, section_name="A",
            population_effective_at=NOW,
        ))
        session.commit()
    finally:
        session.close()


@pytest.fixture()
def pg_dataset():
    schema = f"tis_b11e_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(POSTGRESQL_URL, connect_args={"connect_timeout": 10})
    with admin_engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = _engine_for_schema(schema)
    try:
        database.Base.metadata.create_all(engine)
        _build_dataset(engine)
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _session_factory(engine, isolation: str):
    bind = engine.execution_options(isolation_level="REPEATABLE READ") if isolation == "repeatable_read" else engine
    Session = sessionmaker(bind=bind)

    def factory():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    return factory


def _client(db_factory, *, policy):
    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[get_m10_organization_analytics_db] = db_factory
    app.dependency_overrides[route.get_current_user] = lambda: actor(scope="ORGANIZATION", branch=PRIMARY_BRANCH, group=PRIMARY_GROUP)
    app.dependency_overrides[resolve_organization_analytics_availability_provider] = lambda: AllowAvailability()
    app.dependency_overrides[resolve_organization_analytics_breadth_policy] = lambda: AllowBreadth()
    app.dependency_overrides[resolve_privacy_policy_provider] = lambda: policy
    return TestClient(app)


def _client_with_real_availability(db_factory, *, policy):
    """Like `_client`, but leaves the real F1
    `EntitlementOrganizationAnalyticsAvailabilityProvider` wired (via
    `svc.resolve_organization_analytics_availability_provider`) instead of
    overriding it with the test-only `AllowAvailability()` stub. Used only by
    the new entitlement-snapshot test below, which specifically qualifies
    that provider's SQL path."""

    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[get_m10_organization_analytics_db] = db_factory
    app.dependency_overrides[route.get_current_user] = lambda: actor(scope="ORGANIZATION", branch=PRIMARY_BRANCH, group=PRIMARY_GROUP)
    app.dependency_overrides[resolve_organization_analytics_breadth_policy] = lambda: AllowBreadth()
    app.dependency_overrides[resolve_privacy_policy_provider] = lambda: policy
    return TestClient(app)


def _sum_values(node):
    """Recursively sum every JSON `"value"` leaf in a response body - a
    backend-agnostic way to detect ANY population-derived drift anywhere in
    a route's response, without hardcoding each route's exact field paths."""

    total = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "value" and isinstance(value, (int, float)) and not isinstance(value, bool):
                total += value
            else:
                total += _sum_values(value)
    elif isinstance(node, list):
        for item in node:
            total += _sum_values(item)
    return total


# ---------------------------------------------------------------------------
# Phase 4A/4B - live re-test of the two B11-D empirically proven cases.
# ---------------------------------------------------------------------------

@requires_postgresql
def test_overview_repeatable_read_resolves_candidate_snapshot_mismatch(monkeypatch, pg_dataset):
    """Re-test of B11-D's proven Overview 314->315 Candidate mismatch.

    Interleaves a writer (complete an existing frozen `unassessed` member's
    Assessment + create its Candidate) between `coverage_organization_total`
    (SQL#1) and `candidate_membership_counts` (SQL#2) - the exact statement
    pair B11-D proved diverges under `READ COMMITTED`.
    """

    engine = pg_dataset
    # Members 3-6 are already-frozen `unassessed` write targets (see
    # `_build_dataset`); the RR and RC legs below each independently
    # interleave a write, so each leg must target a DIFFERENT member/student
    # (PostgreSQL's real `uq_talent_student_assessments_cycle_student`
    # constraint - `(cycle_id, student_id)` - forbids completing the same
    # member's Assessment twice, exactly as production would).
    targets = iter(((3, 1003, 799, 899), (4, 1004, 798, 898)))
    write_state = {"done": False}
    original = svc.coverage_organization_total

    def patched(db, population_query):
        result = original(db, population_query)
        if not write_state["done"]:
            write_state["done"] = True
            member_id, student_id, assessment_id, candidate_id = next(targets)
            _writer_complete_assessment(
                engine, member_id=member_id, student_id=student_id, cycle_id=CYCLE_ALPHA_1, program_id=PROGRAM_ALPHA,
                framework_version_id=101, assessment_id=assessment_id, with_candidate=True, candidate_id=candidate_id, policy_id=PROGRAM_ALPHA,
            )
        return result

    monkeypatch.setattr(svc, "coverage_organization_total", patched)

    rr_client = _client(_session_factory(engine, "repeatable_read"), policy=AllowAllTestPolicy())
    rr_response = rr_client.get(f"/api/talent/organization-analytics/overview?academic_year_id={PRIMARY_AY}")
    assert rr_response.status_code == 200
    rr_body = rr_response.json()
    assert rr_body["metrics"]["candidate_membership_count"]["value"] == 1, (
        "REPEATABLE READ must not observe the Candidate committed after SQL#1 executed"
    )

    # Contrast: identical interleave (against a DIFFERENT already-unassessed
    # member, per the constraint note above), but a plain default (READ
    # COMMITTED) session - reproduces the original vulnerability live,
    # against this exact dataset/harness, confirming the fix is necessary
    # and not merely asserted from the earlier B11-D document. Expected
    # value is 3, not 2: the RR leg's writer commit above is a REAL,
    # permanent commit (matching a real concurrent request), so by the time
    # this second leg runs, the dataset already has 1 (original) + 1 (the RR
    # leg's own committed write) Candidates BEFORE this request even starts;
    # this leg's own interleaved write then adds the 3rd, and READ COMMITTED
    # observes it within the same request.
    write_state["done"] = False
    rc_client = _client(_session_factory(engine, "read_committed"), policy=AllowAllTestPolicy())
    rc_response = rc_client.get(f"/api/talent/organization-analytics/overview?academic_year_id={PRIMARY_AY}")
    assert rc_response.status_code == 200
    rc_body = rc_response.json()
    assert rc_body["metrics"]["candidate_membership_count"]["value"] == 3, (
        "READ COMMITTED is expected to observe the interleaved write - confirms the reproduced vulnerability"
    )


@requires_postgresql
def test_student_drill_repeatable_read_resolves_gate_page_mismatch(monkeypatch, pg_dataset):
    """Re-test of B11-D's proven Student Drill 705->706 gate/page mismatch.

    Interleaves a writer (one brand-new frozen population member for a
    brand-new Student) between `count_distinct_students` (the P7 gate, SQL#1)
    and `fetch_student_rows` (the page fetch, SQL#2) - the exact statement
    pair B11-D proved diverges under `READ COMMITTED`.
    """

    engine = pg_dataset
    # The RR and RC legs below each independently commit a brand-new Student
    # (a real distinct primary key), so each leg must use a different id.
    new_student_ids = iter((1011, 1012))
    write_state = {"done": False}
    original = student_drill.count_distinct_students

    def patched(population_query):
        result = original(population_query)
        if not write_state["done"]:
            write_state["done"] = True
            new_id = next(new_student_ids)
            _writer_add_new_frozen_member(
                engine, member_id=new_id, student_id=new_id, cycle_id=CYCLE_ALPHA_1, program_id=PROGRAM_ALPHA,
                framework_version_id=101, grade="1",
            )
        return result

    monkeypatch.setattr(student_drill, "count_distinct_students", patched)

    rr_client = _client(_session_factory(engine, "repeatable_read"), policy=AllowAllTestPolicy())
    rr_response = rr_client.get(f"/api/talent/organization-analytics/students?academic_year_id={PRIMARY_AY}&limit=100")
    assert rr_response.status_code == 200
    rr_body = rr_response.json()
    assert len(rr_body["items"]) == 10, "the page must match the gate's own 10-Student snapshot"
    assert not any(item["student_id"] == 1011 for item in rr_body["items"]), (
        "REPEATABLE READ must not observe the Student committed after the gate query executed"
    )

    write_state["done"] = False
    rc_client = _client(_session_factory(engine, "read_committed"), policy=AllowAllTestPolicy())
    rc_response = rc_client.get(f"/api/talent/organization-analytics/students?academic_year_id={PRIMARY_AY}&limit=100")
    assert rc_response.status_code == 200
    rc_body = rc_response.json()
    assert any(item["student_id"] == 1012 for item in rc_body["items"]), (
        "READ COMMITTED is expected to observe the interleaved write - confirms the reproduced gate/page mismatch"
    )


# ---------------------------------------------------------------------------
# Phase 4C - live consistency check for the five remaining routes.
# ---------------------------------------------------------------------------

_OTHER_ROUTE_CASES = (
    ("talent_map", lambda ay: f"/api/talent/organization-analytics/talent-map?academic_year_id={ay}&dimension=program_branch&metric=frozen_eligible"),
    ("program_portfolio", lambda ay: f"/api/talent/organization-analytics/program-portfolio?academic_year_id={ay}"),
    ("branch_intelligence", lambda ay: f"/api/talent/organization-analytics/branches/{PRIMARY_BRANCH}?academic_year_id={ay}"),
    ("participation_overlap", lambda ay: f"/api/talent/organization-analytics/participation-overlap?academic_year_id={ay}"),
    ("longitudinal", lambda ay: f"/api/talent/organization-analytics/programs/{PROGRAM_ALPHA}/longitudinal?academic_year_id={ay}&metric=frozen_eligible"),
)


@requires_postgresql
@pytest.mark.parametrize("label,path_fn", _OTHER_ROUTE_CASES, ids=[case[0] for case in _OTHER_ROUTE_CASES])
def test_other_routes_repeatable_read_scope_begins_before_first_statement(monkeypatch, pg_dataset, label, path_fn):
    """Live consistency check for talent-map, program-portfolio, branch
    intelligence, participation-overlap, and longitudinal (Phase 4 of the
    B11-E task; these were structurally-inferred, not independently
    reproduced live, in B11-D).

    Interleaves a writer (one brand-new frozen population member) immediately
    after `frozen_membership_query` builds its lazy Query object - BEFORE any
    of that route's own downstream SQL has executed. This proves the required
    scope genuinely begins before the first statement of the request (fixed
    during earlier context/access resolution), not merely between two
    already-identified calls.
    """

    engine = pg_dataset
    write_state = {"done": False, "member_id": 2000}
    original = svc.frozen_membership_query

    def patched(db, context, filters, *, authorized_program_ids):
        query = original(db, context, filters, authorized_program_ids=authorized_program_ids)
        if not write_state["done"]:
            write_state["done"] = True
            write_state["member_id"] += 1
            member_id = write_state["member_id"]
            _writer_add_new_frozen_member(
                engine, member_id=member_id, student_id=member_id, cycle_id=CYCLE_ALPHA_1,
                program_id=PROGRAM_ALPHA, framework_version_id=101, grade="1",
            )
        return query

    monkeypatch.setattr(svc, "frozen_membership_query", patched)

    rr_client = _client(_session_factory(engine, "repeatable_read"), policy=AllowAllTestPolicy())
    rr_response = rr_client.get(path_fn(PRIMARY_AY))
    assert rr_response.status_code == 200, rr_response.text
    rr_total = _sum_values(rr_response.json())

    write_state["done"] = False
    rc_client = _client(_session_factory(engine, "read_committed"), policy=AllowAllTestPolicy())
    rc_response = rc_client.get(path_fn(PRIMARY_AY))
    assert rc_response.status_code == 200, rc_response.text
    rc_total = _sum_values(rc_response.json())

    assert rc_total > rr_total, (
        f"{label}: expected READ COMMITTED to observe the interleaved write (drift) while "
        "REPEATABLE READ's already-fixed snapshot does not"
    )


# ---------------------------------------------------------------------------
# Phase 5 - suppression/reconstruction concurrency (a real, deterministic,
# non-production suppressing policy - never AllowAllTestPolicy).
# ---------------------------------------------------------------------------

@requires_postgresql
def test_primary_suppression_is_immune_to_a_concurrent_write_crossing_the_threshold(monkeypatch, pg_dataset):
    """A concurrent write that would, if visible, cross a real suppression
    threshold and flip a SUPPRESSED Cell to VISIBLE (a genuine
    reconstruction-relevant state change - not just a numeric drift) must not
    be observable within the same request.

    `DeterministicSuppressionTestPolicy(minimum_cohort=2)` suppresses the
    Candidate Cell (raw value 1, below threshold). The interleaved writer
    commits ONE new Candidate - exactly enough to reach the threshold (2) if
    it were visible.
    """

    engine = pg_dataset
    write_state = {"done": False}
    original = svc.coverage_organization_total

    def patched(db, population_query):
        result = original(db, population_query)
        if not write_state["done"]:
            write_state["done"] = True
            _writer_complete_assessment(
                engine, member_id=3, student_id=1003, cycle_id=CYCLE_ALPHA_1, program_id=PROGRAM_ALPHA,
                framework_version_id=101, assessment_id=798, with_candidate=True, candidate_id=898, policy_id=PROGRAM_ALPHA,
            )
        return result

    monkeypatch.setattr(svc, "coverage_organization_total", patched)

    policy = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    client = _client(_session_factory(engine, "repeatable_read"), policy=policy)
    response = client.get(f"/api/talent/organization-analytics/overview?academic_year_id={PRIMARY_AY}")
    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["candidate_membership_count"] == {"state": "suppressed"}, (
        "the suppression decision must reflect the fixed snapshot (candidate=1, below threshold), "
        "not the concurrently-committed candidate=2 that would cross it"
    )
    serialized = str(body).replace(":", " ").replace(",", " ").replace('"', " ")
    assert not ({"raw_value", "privacy_threshold", "minimum_cohort"} & set(serialized.split())), (
        "no raw value or threshold detail may leak regardless of concurrency"
    )


@requires_postgresql
def test_complementary_suppression_relationship_is_immune_to_a_concurrent_write(monkeypatch, pg_dataset):
    """A concurrent write to a RELATIONSHIP-LINKED component (`completed`,
    tied to `coverage_n` by the `overview` route's own equality Relationship)
    that would, if visible, cross the threshold and make the relationship's
    derived rate visible, must not desynchronize the pair or leak a partial
    result: `completion_coverage` must remain fully suppressed (both the
    primary Cell and its complementary relationship partner), exactly as
    B11-D's privacy analysis concluded for relationship-linked Cells sourced
    from one statement - now proven under an actual concurrent write, too.
    """

    engine = pg_dataset
    # Members 3-6 are already-frozen `unassessed` write targets; the RR and
    # RC legs below each independently complete one member's Assessment, so
    # each leg must target a DIFFERENT member/student (real
    # `uq_talent_student_assessments_cycle_student` constraint).
    targets = iter(((4, 1004, 797), (5, 1005, 796)))
    write_state = {"done": False}
    original = svc.coverage_organization_total

    def patched(db, population_query):
        result = original(db, population_query)
        if not write_state["done"]:
            write_state["done"] = True
            member_id, student_id, assessment_id = next(targets)
            # Completes ONE more Assessment (no Candidate) - raises
            # `completed` from 2 to 3, crossing the minimum_cohort=3
            # threshold used below, if it were visible.
            _writer_complete_assessment(
                engine, member_id=member_id, student_id=student_id, cycle_id=CYCLE_ALPHA_1, program_id=PROGRAM_ALPHA,
                framework_version_id=101, assessment_id=assessment_id, with_candidate=False,
            )
        return result

    monkeypatch.setattr(svc, "coverage_organization_total", patched)

    policy = DeterministicSuppressionTestPolicy(minimum_cohort=3)
    rr_client = _client(_session_factory(engine, "repeatable_read"), policy=policy)
    rr_response = rr_client.get(f"/api/talent/organization-analytics/overview?academic_year_id={PRIMARY_AY}")
    assert rr_response.status_code == 200
    rr_body = rr_response.json()
    assert rr_body["metrics"]["completion_coverage"] == {"state": "suppressed"}
    assert "percentage" not in rr_body["metrics"]["completion_coverage"]

    # Contrast: the same interleave under plain READ COMMITTED does flip the
    # relationship to visible - proving this is a real, reconstruction-shaped
    # risk this route is structurally exposed to without the ADR 0029 fix,
    # not a hypothetical one.
    write_state["done"] = False
    rc_client = _client(_session_factory(engine, "read_committed"), policy=policy)
    rc_response = rc_client.get(f"/api/talent/organization-analytics/overview?academic_year_id={PRIMARY_AY}")
    assert rc_response.status_code == 200
    rc_body = rc_response.json()
    assert rc_body["metrics"]["completion_coverage"]["state"] == "visible"


# ---------------------------------------------------------------------------
# Tenant isolation under the new session type.
# ---------------------------------------------------------------------------

@requires_postgresql
def test_tenant_isolation_holds_under_the_new_session_with_a_foreign_tenant_write(pg_dataset):
    """Every M10 query filters by `context.school_group_id` (confirmed by
    code reading in B11-D). This proves it live, under the new
    REPEATABLE READ session specifically, with a foreign-tenant write
    committed immediately before the primary tenant's read."""

    engine = pg_dataset
    session = sessionmaker(bind=engine)()
    session.add(models.Student(id=9002, school_group_id=FOREIGN_GROUP, first_name="Foreign2", last_name="Two", status="active"))
    session.add(models.StudentAcademicPlacement(
        id=9002, school_group_id=FOREIGN_GROUP, student_id=9002, academic_year_id=FOREIGN_AY,
        branch_id=FOREIGN_BRANCH, grade_level="1", section_name="A", effective_from=NOW, status="active",
    ))
    session.add(models.TalentAssessmentCyclePopulationMember(
        id=9002, school_group_id=FOREIGN_GROUP, cycle_id=FOREIGN_CYCLE, program_id=FOREIGN_PROGRAM,
        academic_year_id=FOREIGN_AY, framework_version_id=190, student_id=9002, academic_placement_id=9002,
        branch_id=FOREIGN_BRANCH, grade_level="1", section_name="A", population_effective_at=NOW,
    ))
    session.commit()
    session.close()

    client = _client(_session_factory(engine, "repeatable_read"), policy=AllowAllTestPolicy())
    response = client.get(f"/api/talent/organization-analytics/overview?academic_year_id={PRIMARY_AY}")
    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["frozen_eligible_memberships"]["value"] == 14
    serialized = str(body)
    assert "9002" not in serialized and "Foreign2" not in serialized


# ---------------------------------------------------------------------------
# F1 entitlement path (`EntitlementOrganizationAnalyticsAvailabilityProvider`)
# in the M10 REPEATABLE READ snapshot. Added for B11-E F2 qualification: the
# tests above all override `resolve_organization_analytics_availability_provider`
# with the test-only `AllowAvailability()` stub, so none of them exercise the
# real F1 provider's SQL (`saas.entitlement_service.organization_feature_available`,
# which itself issues several statements: `EntitlementDefinition`,
# `SchoolGroup`, and `WorkspaceEntitlement`/promo/subscription reads via
# `commercial_state_service.resolve_commercial_state` /
# `workspace_entitlement_service.resolve_workspace_entitlement`). This test
# uses `_client_with_real_availability` to leave that real provider wired.
# ---------------------------------------------------------------------------

def _writer_toggle_entitlement_and_add_member(engine, *, feature_key: str, member_id: int, student_id: int) -> None:
    """A separate, already-committed writer Session that (1) deactivates the
    commercial entitlement definition the F1 availability provider already
    read as active, and (2) adds one brand-new frozen population member -
    both in the same real, domain-valid commit, matching the "concurrent
    writer commits a change to the underlying entitlement/commercial-state
    table" scenario this test qualifies."""

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        definition = session.query(EntitlementDefinition).filter(
            EntitlementDefinition.key == feature_key
        ).one()
        definition.active = False
        session.add(models.Student(id=student_id, school_group_id=PRIMARY_GROUP, first_name="Late", last_name=f"S{student_id}", status="active"))
        session.add(models.StudentAcademicPlacement(
            id=student_id, school_group_id=PRIMARY_GROUP, student_id=student_id, academic_year_id=PRIMARY_AY,
            branch_id=PRIMARY_BRANCH, grade_level="1", section_name="A", effective_from=NOW, status="active",
        ))
        session.add(models.TalentAssessmentCyclePopulationMember(
            id=member_id, school_group_id=PRIMARY_GROUP, cycle_id=CYCLE_ALPHA_1, program_id=PROGRAM_ALPHA,
            academic_year_id=PRIMARY_AY, framework_version_id=101, student_id=student_id,
            academic_placement_id=student_id, branch_id=PRIMARY_BRANCH, grade_level="1", section_name="A",
            population_effective_at=NOW,
        ))
        session.commit()
    finally:
        session.close()


@requires_postgresql
def test_entitlement_availability_check_shares_the_m10_repeatable_read_snapshot(monkeypatch, pg_dataset):
    """The F1 `EntitlementOrganizationAnalyticsAvailabilityProvider.is_available()`
    check is the request's very first database statement (context/access
    resolution, per ADR 0029) - even earlier than the two originally-proven
    B11-D statement pairs. This interleaves a writer immediately after that
    check returns (but before any later M10 population statement executes)
    that both flips the entitlement definition the check just read AND adds a
    new frozen population member, proving:

    1. The already-computed availability decision (True) is honored for the
       rest of this request - it is not re-evaluated (matches the existing,
       unchanged `resolve_access_context` contract: `is_available` is called
       exactly once per request).
    2. The later population read (`coverage_organization_total` /
       `frozen_eligible_memberships`) does NOT observe the writer's new
       member under REPEATABLE READ - proving the entitlement check and every
       later M10 statement share ONE fixed snapshot, not two independent
       connections/transactions.

    Contrast: an identical interleave under plain READ COMMITTED DOES observe
    the new member - reproducing the general mixed-snapshot risk for this
    specific interleave point and confirming REPEATABLE READ is what closes
    it here, not an unrelated property of the dataset.
    """

    engine = pg_dataset
    admin_session = sessionmaker(bind=engine)()
    admin_session.add(EntitlementDefinition(
        key=ORGANIZATION_INTELLIGENCE_FEATURE_KEY, display_name="Organization Intelligence",
        category="organization_analytics", active=True,
    ))
    admin_session.commit()
    admin_session.close()

    new_member_ids = iter(((5001, 5001), (5002, 5002)))
    write_state = {"done": False}
    original = saas_entitlement_service.organization_feature_available

    def patched(db, school_group_id, feature_key):
        result = original(db, school_group_id, feature_key)
        if not write_state["done"]:
            write_state["done"] = True
            member_id, student_id = next(new_member_ids)
            _writer_toggle_entitlement_and_add_member(
                engine, feature_key=feature_key, member_id=member_id, student_id=student_id,
            )
        return result

    monkeypatch.setattr(saas_entitlement_service, "organization_feature_available", patched)

    rr_client = _client_with_real_availability(_session_factory(engine, "repeatable_read"), policy=AllowAllTestPolicy())
    rr_response = rr_client.get(f"/api/talent/organization-analytics/overview?academic_year_id={PRIMARY_AY}")
    assert rr_response.status_code == 200, (
        "the availability decision computed before the writer's commit must still be honored"
    )
    rr_body = rr_response.json()
    assert rr_body["metrics"]["frozen_eligible_memberships"]["value"] == 14, (
        "REPEATABLE READ must not observe the population member committed after the "
        "entitlement-availability check but before this statement, in the same request"
    )
    assert "5001" not in str(rr_body)

    write_state["done"] = False
    # Restore the definition for the READ COMMITTED contrast leg (the RR
    # leg's writer already deactivated it as a real, permanent commit).
    admin_session = sessionmaker(bind=engine)()
    admin_session.query(EntitlementDefinition).filter(
        EntitlementDefinition.key == ORGANIZATION_INTELLIGENCE_FEATURE_KEY
    ).update({"active": True})
    admin_session.commit()
    admin_session.close()

    rc_client = _client_with_real_availability(_session_factory(engine, "read_committed"), policy=AllowAllTestPolicy())
    rc_response = rc_client.get(f"/api/talent/organization-analytics/overview?academic_year_id={PRIMARY_AY}")
    assert rc_response.status_code == 200
    rc_body = rc_response.json()
    # Expected value is 16, not 15: the RR leg's writer commit above is a
    # REAL, permanent commit (matching a real concurrent request), so by the
    # time this second leg runs the dataset already has 14 (original) + 1
    # (the RR leg's own committed member 5001) BEFORE this request even
    # starts; this leg's own interleaved write then adds member 5002 as the
    # 16th, and READ COMMITTED observes it within the same request (matching
    # the identical reasoning already used above for the Candidate re-test).
    assert rc_body["metrics"]["frozen_eligible_memberships"]["value"] == 16, (
        "READ COMMITTED is expected to observe the interleaved write - confirms this interleave "
        "point is a real mixed-snapshot risk this specific fix (not dataset shape) resolves"
    )
