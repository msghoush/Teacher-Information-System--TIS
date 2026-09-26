"""Deployment Acceptance Batch 1: data correctness, scope integrity, Student deletion, loading cost.

End-to-end against the sanctioned realistic local Talent dataset
(``talent_local_test_data.build_dataset``: 10 Students in 2 Branches, 3 Programs,
open/closed Cycles, completed and in-progress Assessments) using the real
routers, real service-layer writes and (for deletion) real foreign-key
enforcement. No production data, no ``tis.db``.

Owner-observed defects covered:

* "Students participating = 63 while only 9 Students exist": the headline was the
  FROZEN MEMBERSHIP row count (one row per Student per Cycle/Program), never a
  distinct Student count.
* Student deletion must remove everything the Student owns in Talent & Potential
  and no orphan row may ever contaminate a current figure.
* The global Branch scope must bound Talent data (Branch A never returns Branch B).
* Talent list endpoints must not scale per Assessment row (loading root cause).
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import talent_org_intelligence_service as osvc
from auth import get_current_user, get_current_user_via_m10_analytics_db
from database import Base
from dependencies import get_db, get_m10_organization_analytics_db
from routers import (
    students as students_router,
    talent_analytics, talent_assessment_cycles, talent_assessments, talent_evaluation_plans,
    talent_evaluation_progress, talent_organization_analytics, talent_programs, talent_results_analytics,
)
from student_academic_service import create_placement, create_student
from talent_analytics_privacy import AllowAllTestPolicy, resolve_privacy_policy_provider
from talent_assessment_cycle_service import open_cycle
from talent_local_test_data import build_dataset
from talent_student_assessment_service import (
    complete_assessment, set_competency_result, start_assessment,
)
from test_talent_org_intelligence_queries import AllowAvailability, AllowBreadth

ORG = "/api/talent/organization-analytics"


class World:
    def __init__(self, *, foreign_keys: bool):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        if foreign_keys:
            @event.listens_for(self.engine, "connect")
            def _fk(connection, _record):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.summary = build_dataset(self.db)
        self.group_id = self.summary["school_group_id"]
        self.north, self.south = self.summary["branch_ids"]
        self.year = self.summary["academic_year_id"]
        self.program_a, self.program_b, self.program_c = self.summary["program_ids"]
        self.cycle_a, self.cycle_b, self.cycle_c = self.summary["cycle_ids"]
        self.student_ids = self.summary["student_ids"]
        self.admin_user_id = self.summary["local_test_user_id"]
        # Batch 1 closure: the global Branch is a hard Talent ceiling for an
        # organization actor, so the default World actor has the explicit global
        # "All Branches" scope (scope_all_branches). Use as_admin(branch) for a
        # single-Branch global scope.
        self.current = {"user_id": self.admin_user_id, "scope_all": True}
        self.statements: list[str] = []

        @event.listens_for(self.engine, "before_cursor_execute")
        def _count(_c, _cur, statement, _p, _ctx, _many):
            self.statements.append(statement)

        app = FastAPI()
        for module in (
            talent_organization_analytics, talent_results_analytics, talent_analytics,
            talent_assessment_cycles, talent_assessments, talent_programs,
            talent_evaluation_plans, talent_evaluation_progress, students_router,
        ):
            app.include_router(module.router)

        def request_db():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        def request_user():
            session = self.Session()
            user = session.query(models.User).filter_by(user_id=self.current["user_id"]).one()
            user.scope_school_group_id = self.group_id
            user.scope_branch_id = self.current.get("scope_branch_id", self.north)
            user.scope_all_branches = bool(self.current.get("scope_all", False))
            user.scope_academic_year_id = self.year
            user.effective_role = "Administrator"
            return user

        app.dependency_overrides[get_db] = request_db
        app.dependency_overrides[get_m10_organization_analytics_db] = request_db
        app.dependency_overrides[get_current_user] = request_user
        # M10 analytics routes resolve current-user through the M10-bound
        # dependency (production incident fix: shares the request's single
        # M10 session instead of opening a second, independent get_db() one).
        app.dependency_overrides[get_current_user_via_m10_analytics_db] = request_user
        app.dependency_overrides[resolve_privacy_policy_provider] = lambda: AllowAllTestPolicy()
        app.dependency_overrides[osvc.resolve_organization_analytics_availability_provider] = lambda: AllowAvailability()
        app.dependency_overrides[osvc.resolve_organization_analytics_breadth_policy] = lambda: AllowBreadth()
        self.client = TestClient(app, raise_server_exceptions=False)

    # -- actors --------------------------------------------------------------
    def branch_limited_user(self, branch_id):
        user = models.User(
            user_id="LTB0001", username="branch_limited", email="branch@example.test",
            email_normalized="branch@example.test", first_name="Branch", last_name="Limited",
            password="x", role="Administrator", user_type="TENANT", access_scope="BRANCH",
            school_group_id=self.group_id, branch_id=branch_id, academic_year_id=self.year, is_active=True,
        )
        existing = self.db.query(models.User).filter_by(user_id=user.user_id).first()
        if existing is None:
            self.db.add(user)
            self.db.commit()
        else:
            existing.branch_id = branch_id
            self.db.commit()
        self.current = {"user_id": user.user_id, "scope_branch_id": branch_id}

    def as_admin(self, scope_branch_id=None):
        if scope_branch_id:
            self.current = {"user_id": self.admin_user_id, "scope_branch_id": scope_branch_id, "scope_all": False}
        else:
            self.current = {"user_id": self.admin_user_id, "scope_branch_id": self.north, "scope_all": True}

    def get(self, path):
        return self.client.get(path)

    def count_statements(self, path):
        self.statements.clear()
        started = time.perf_counter()
        response = self.client.get(path)
        elapsed = time.perf_counter() - started
        assert response.status_code == 200, (path, response.status_code, response.text[:200])
        return len(self.statements), elapsed

    def close(self):
        self.db.close()


@pytest.fixture()
def world():
    instance = World(foreign_keys=True)
    yield instance
    instance.close()


@pytest.fixture()
def world_no_fk():
    """Foreign keys OFF so genuine orphan rows can be inserted (SQLite default)."""
    instance = World(foreign_keys=False)
    yield instance
    instance.close()


def metrics(world, query=""):
    response = world.get(f"{ORG}/overview?academic_year_id={world.year}{query}")
    assert response.status_code == 200, response.text
    return response.json()["metrics"]


def value(cell):
    assert cell["state"] == "visible", cell
    return cell["value"]


def north_students(world):
    return {row.student_id for row in world.db.query(models.TalentAssessmentCyclePopulationMember).filter_by(branch_id=world.north)}


# ---------------------------------------------------------------------------
# 1 / 2. "Students" is DISTINCT current Students, never memberships
# ---------------------------------------------------------------------------


def test_students_participating_is_distinct_students_not_frozen_memberships(world):
    m = metrics(world)
    students = len(world.student_ids)
    memberships = world.db.query(models.TalentAssessmentCyclePopulationMember).count()
    assert students == 10 and memberships == 20  # 10 Students x 2 open/closed Cycles
    assert value(m["distinct_students"]) == 10
    assert value(m["frozen_eligible_memberships"]) == 20
    # completion coverage keeps its own (membership) denominator: it is a rate of
    # assessments over participations, NOT a Student count, and is left unchanged.
    assert m["completion_coverage"]["denominator"] == 20


def test_more_cycles_and_periods_multiply_memberships_but_never_students(world):
    """Reproduces "9 Students -> 63": opening more Cycles adds membership rows only."""
    cycle = world.db.get(models.TalentAssessmentCycle, world.cycle_c)
    admin = world.db.query(models.User).filter_by(user_id=world.admin_user_id).one()
    open_cycle(world.db, school_group_id=world.group_id, cycle_id=world.cycle_c,
               expected_revision=cycle.revision, organization_authorized=True, actor=admin)
    world.db.commit()
    m = metrics(world)
    assert value(m["frozen_eligible_memberships"]) == 30      # 10 Students x 3 Cycles
    assert value(m["distinct_students"]) == 10                # still ten Students
    assert value(m["distinct_students"]) < value(m["frozen_eligible_memberships"])


def test_a_student_in_many_contexts_is_one_student_in_the_drill_and_overlap(world):
    body = world.get(f"{ORG}/students?academic_year_id={world.year}&limit=100&offset=0").json()
    assert len(body["items"]) == 10
    assert len({item["student_id"] for item in body["items"]}) == 10
    assert all(len(item["contexts"]) >= 2 for item in body["items"])  # many contexts, one Student each
    overlap = world.get(f"{ORG}/participation-overlap?academic_year_id={world.year}").json()
    diagonal = {tuple(p["program_ids"]): p for p in overlap["canonical_pairs"] if p["program_ids"][0] == p["program_ids"][1]}
    assert diagonal[(world.program_a, world.program_a)]["value"] == 10  # distinct participants, not rows


def test_overview_branch_scope_counts_only_that_branchs_distinct_students(world):
    north = metrics(world, f"&branch_id={world.north}")
    south = metrics(world, f"&branch_id={world.south}")
    assert value(north["distinct_students"]) == 5
    assert value(south["distinct_students"]) == 5
    assert value(north["frozen_eligible_memberships"]) == 10 and value(south["frozen_eligible_memberships"]) == 10


# ---------------------------------------------------------------------------
# 3 / 4. Student deletion removes every Student-owned Talent contribution and
#        every aggregate recomputes from the remaining population
# ---------------------------------------------------------------------------


def _snapshot(world):
    m = metrics(world)
    classification = world.get(
        f"/api/talent/results-analytics/programs/{world.program_a}/academic-years/{world.year}/classification").json()
    talented = world.get(
        f"/api/talent/results-analytics/programs/{world.program_a}/academic-years/{world.year}/talented").json()
    learning = world.get(f"/api/talent/results-analytics/academic-years/{world.year}/learning-style").json()
    drill = world.get(f"{ORG}/students?academic_year_id={world.year}&limit=100&offset=0").json()
    roster = world.get(f"/api/talent/assessment-cycles/{world.cycle_b}/eligible-students").json()
    assessments = world.get(f"/api/talent/assessments?academic_year_id={world.year}").json()
    branch = world.get(f"{ORG}/talent-map?academic_year_id={world.year}&metric=frozen_eligible&dimension=program_branch").json()
    grade = world.get(f"{ORG}/talent-map?academic_year_id={world.year}&metric=frozen_eligible&dimension=program_grade").json()
    return {
        "distinct": value(m["distinct_students"]), "memberships": value(m["frozen_eligible_memberships"]),
        "classification_total": classification["distribution"]["total"]["value"],
        "classification_sum": sum(b["count"] for b in classification["distribution"]["buckets"]),
        "talented_applicable": talented["organization"]["summary"]["applicable_denominator"],
        "learning_total": learning["distribution"]["total_population"],
        "drill_students": {item["student_id"] for item in drill["items"]},
        "roster": {row["student_id"] for row in roster["members"]},
        "assessment_students": {row["student_id"] for row in assessments},
        "assessments": len(assessments),
        "branch_cells": branch, "grade_cells": grade,
    }


def _talent_rows_for(world, student_id):
    return {
        model.__name__: world.db.query(model).filter_by(school_group_id=world.group_id, student_id=student_id).count()
        for model in (
            models.TalentAssessmentCyclePopulationMember, models.TalentStudentAssessment,
            models.TalentStudentCompetencyResult, models.TalentReviewCandidate,
            models.TalentOfficialIdentification, models.TalentEducatorInput,
            models.TalentAssessmentAudit, models.StudentAcademicPlacement,
        )
    }


def test_deleting_two_of_ten_students_recomputes_every_aggregate_from_the_rest(world):
    before = _snapshot(world)
    assert before["distinct"] == 10 and len(before["drill_students"]) == 10
    doomed = [world.student_ids[0], world.student_ids[5]]  # one per Branch
    assert all(sum(_talent_rows_for(world, s).values()) > 0 for s in doomed)

    for student_id in doomed:
        response = world.client.delete(f"/api/students/{student_id}?force_history=true")
        assert response.status_code == 200, response.text
        assert response.json()["history_deleted"] is True

    world.db.expire_all()
    after = _snapshot(world)
    assert after["distinct"] == 8
    assert after["memberships"] == before["memberships"] - 2 * 2          # 2 Students x 2 Cycles
    assert after["classification_total"] == before["classification_total"] - 2
    assert after["classification_sum"] == after["classification_total"]
    assert after["talented_applicable"] == before["talented_applicable"] - 2
    assert after["learning_total"] == before["learning_total"] - 2
    assert after["drill_students"] == before["drill_students"] - set(doomed)
    assert after["roster"] == before["roster"] - set(doomed)
    assert not (after["assessment_students"] & set(doomed))
    assert after["assessments"] < before["assessments"]
    # Branch and Grade projections recompute from the remaining population too.
    assert after["branch_cells"] != before["branch_cells"]
    assert after["grade_cells"] != before["grade_cells"]
    # Nothing Student-owned survives in any table.
    for student_id in doomed:
        assert world.db.get(models.Student, student_id) is None
        assert sum(_talent_rows_for(world, student_id).values()) == 0
        assert world.db.query(models.StudentExternalIdentifier).filter_by(student_id=student_id).count() == 0
        assert world.db.query(models.StudentAudit).filter_by(student_id=student_id).count() == 0


def test_normal_delete_stays_blocked_by_talent_history_and_removes_nothing(world):
    """The permission/blocker model is unchanged: only force-delete removes Talent history."""
    student_id = world.student_ids[1]
    before = _talent_rows_for(world, student_id)
    response = world.client.delete(f"/api/students/{student_id}")
    assert response.status_code == 409
    world.db.expire_all()
    assert world.db.get(models.Student, student_id) is not None
    assert _talent_rows_for(world, student_id) == before


# ---------------------------------------------------------------------------
# 5. No orphan / historical Talent row can inflate a current figure
# ---------------------------------------------------------------------------


def _clone_as_orphan(world, source_member_id, orphan_student_id):
    """A realistic orphan: a full completed Assessment chain for a Student that does not exist."""
    db = world.db
    member = db.get(models.TalentAssessmentCyclePopulationMember, source_member_id)
    assessment = db.query(models.TalentStudentAssessment).filter_by(cycle_population_member_id=member.id).one()
    new_member = models.TalentAssessmentCyclePopulationMember(
        school_group_id=member.school_group_id, cycle_id=member.cycle_id, program_id=member.program_id,
        academic_year_id=member.academic_year_id, framework_version_id=member.framework_version_id,
        student_id=orphan_student_id, academic_placement_id=member.academic_placement_id,
        branch_id=member.branch_id, planning_section_id=member.planning_section_id,
        grade_level=member.grade_level, section_name=member.section_name,
        population_effective_at=member.population_effective_at,
    )
    db.add(new_member)
    db.flush()
    new_assessment = models.TalentStudentAssessment(
        school_group_id=assessment.school_group_id, cycle_id=assessment.cycle_id,
        cycle_population_member_id=new_member.id, student_id=orphan_student_id,
        program_id=assessment.program_id, academic_year_id=assessment.academic_year_id,
        framework_version_id=assessment.framework_version_id, status="completed",
        is_current=True, completed_at=assessment.completed_at,
    )
    db.add(new_assessment)
    db.flush()
    for result in db.query(models.TalentStudentCompetencyResult).filter_by(assessment_id=assessment.id).all():
        db.add(models.TalentStudentCompetencyResult(
            school_group_id=result.school_group_id, assessment_id=new_assessment.id, cycle_id=result.cycle_id,
            student_id=orphan_student_id, program_id=result.program_id, academic_year_id=result.academic_year_id,
            framework_version_id=result.framework_version_id, framework_competency_id=result.framework_competency_id,
            rubric_id=result.rubric_id, rubric_level_id=result.rubric_level_id,
        ))
    db.commit()


def test_orphan_talent_rows_never_contaminate_any_current_analytics(world_no_fk):
    world = world_no_fk
    before = _snapshot(world)
    members = world.db.query(models.TalentAssessmentCyclePopulationMember).filter(
        models.TalentAssessmentCyclePopulationMember.cycle_id.in_((world.cycle_a, world.cycle_b))).all()
    for offset, member in enumerate(members[:6]):
        _clone_as_orphan(world, member.id, 90000 + offset)  # no Student row exists for these ids
    assert world.db.query(models.TalentAssessmentCyclePopulationMember).count() == 26  # rows really exist
    assert world.db.query(models.Student).filter(models.Student.id >= 90000).count() == 0

    world.db.expire_all()
    after = _snapshot(world)
    assert after == before, "an orphan Talent row changed a current figure"
    # Endpoints not covered by the snapshot helper.
    program_results = world.get(f"{ORG}/program-portfolio?academic_year_id={world.year}").json()
    branch_progress = world.get(
        f"/api/talent/evaluation-progress/programs/{world.program_a}/academic-years/{world.year}/branch-comparison?metric=assessment_completion")
    rubric = world.get(f"/api/talent/analytics/programs/{world.program_a}/academic-years/{world.year}/rubric-distribution?assessment_state=completed")
    assert program_results and branch_progress.status_code == 200 and rubric.status_code == 200
    assert branch_progress.json()["rows"], "branch comparison must return real rows for the equality check to mean anything"
    clean = World(foreign_keys=False)
    try:
        assert clean.get(f"{ORG}/program-portfolio?academic_year_id={clean.year}").json() == program_results
        clean_progress = clean.get(
            f"/api/talent/evaluation-progress/programs/{clean.program_a}/academic-years/{clean.year}/branch-comparison?metric=assessment_completion")
        assert clean_progress.json() == branch_progress.json()
        clean_rubric = clean.get(f"/api/talent/analytics/programs/{clean.program_a}/academic-years/{clean.year}/rubric-distribution?assessment_state=completed")
        assert clean_rubric.json() == rubric.json()
    finally:
        clean.close()


# ---------------------------------------------------------------------------
# 6 / 7 / 8. Branch scope
# ---------------------------------------------------------------------------


def test_branch_a_then_branch_b_never_leaves_branch_a_data(world):
    north_ids = {r.student_id for r in world.db.query(models.TalentAssessmentCyclePopulationMember).filter_by(branch_id=world.north)}
    south_ids = {r.student_id for r in world.db.query(models.TalentAssessmentCyclePopulationMember).filter_by(branch_id=world.south)}
    assert north_ids and south_ids and not (north_ids & south_ids)

    def scoped(branch_id):
        drill = world.get(f"{ORG}/students?academic_year_id={world.year}&branch_id={branch_id}&limit=100&offset=0").json()
        roster = world.get(f"/api/talent/assessment-cycles/{world.cycle_b}/eligible-students?branch_id={branch_id}").json()
        overview = metrics(world, f"&branch_id={branch_id}")
        learning = world.get(f"/api/talent/results-analytics/academic-years/{world.year}/learning-style?branch_id={branch_id}").json()
        return (
            {i["student_id"] for i in drill["items"]}, {m["student_id"] for m in roster["members"]},
            value(overview["distinct_students"]), learning["distribution"]["total_population"],
        )

    a_drill, a_roster, a_count, a_learning = scoped(world.north)
    b_drill, b_roster, b_count, b_learning = scoped(world.south)
    assert a_drill == north_ids and a_roster == north_ids and a_count == 5 and a_learning == 5
    assert b_drill == south_ids and b_roster == south_ids and b_count == 5 and b_learning == 5
    assert not (a_drill & b_drill) and not (a_roster & b_roster)


def test_program_results_honor_the_selected_branch_like_branch_results(world):
    scoped = world.get(f"{ORG}/program-portfolio?academic_year_id={world.year}&branch_id={world.north}")
    direct = world.get(f"{ORG}/branches/{world.north}?academic_year_id={world.year}")
    organization = world.get(f"{ORG}/program-portfolio?academic_year_id={world.year}")
    assert scoped.status_code == 200 and scoped.json() == direct.json()
    assert scoped.json() != organization.json()  # the parameter is no longer silently ignored


def test_branch_limited_actor_can_never_widen_scope(world):
    world.branch_limited_user(world.north)
    north = north_students(world)
    # Without any Branch filter the backend still bounds every read to the actor's Branch.
    assert value(metrics(world)["distinct_students"]) == 5
    drill = world.get(f"{ORG}/students?academic_year_id={world.year}&limit=100&offset=0").json()
    assert {i["student_id"] for i in drill["items"]} == north
    roster = world.get(f"/api/talent/assessment-cycles/{world.cycle_b}/eligible-students").json()
    assert {m["student_id"] for m in roster["members"]} == north
    # Selecting another Branch is rejected, never honored.
    assert world.get(f"{ORG}/overview?academic_year_id={world.year}&branch_id={world.south}").status_code == 400
    assert world.get(f"{ORG}/students?academic_year_id={world.year}&branch_id={world.south}").status_code == 400
    assert world.get(f"{ORG}/program-portfolio?academic_year_id={world.year}&branch_id={world.south}").status_code == 404
    assert world.get(f"/api/talent/assessment-cycles/{world.cycle_b}/eligible-students?branch_id={world.south}").status_code == 403
    assert world.get(
        f"/api/talent/results-analytics/programs/{world.program_a}/academic-years/{world.year}/classification?branch_id={world.south}"
    ).status_code == 400


def test_a_foreign_tenant_branch_is_never_accepted(world):
    other = models.SchoolGroup(name="Other Tenant")
    world.db.add(other)
    world.db.flush()
    foreign_branch = models.Branch(school_group_id=other.id, name="Foreign Campus", status=True)
    world.db.add(foreign_branch)
    world.db.commit()
    assert world.get(f"{ORG}/overview?academic_year_id={world.year}&branch_id={foreign_branch.id}").status_code == 400
    assert world.get(f"{ORG}/program-portfolio?academic_year_id={world.year}&branch_id={foreign_branch.id}").status_code == 404
    assert world.get(f"/api/talent/assessment-cycles/{world.cycle_b}/eligible-students?branch_id={foreign_branch.id}").status_code == 403


# ---------------------------------------------------------------------------
# 9. Loading root cause: list endpoints are bounded and not row-proportional
# ---------------------------------------------------------------------------


def _add_completed_students(world, count):
    """Extra Students with completed Assessments in Cycle B (same Framework/Grade family)."""
    admin = world.db.query(models.User).filter_by(user_id=world.admin_user_id).one()
    cycle = world.db.get(models.TalentAssessmentCycle, world.cycle_b)
    competencies = world.db.query(models.FrameworkCompetency).filter_by(
        framework_version_id=cycle.framework_version_id).all()
    for index in range(count):
        student = create_student(world.db, school_group_id=world.group_id, first_name=f"Extra{index}",
                                 last_name="Learner", gender="female", actor=admin)
        placement = create_placement(world.db, school_group_id=world.group_id, student_id=student.id,
                                     academic_year_id=world.year, branch_id=world.north,
                                     effective_from=datetime(2026, 9, 1), grade_level="3", section_name="A", actor=admin)
        world.db.flush()
        member = models.TalentAssessmentCyclePopulationMember(
            school_group_id=world.group_id, cycle_id=cycle.id, program_id=cycle.program_id,
            academic_year_id=world.year, framework_version_id=cycle.framework_version_id,
            student_id=student.id, academic_placement_id=placement.id, branch_id=world.north,
            grade_level="3", section_name="A", population_effective_at=datetime(2026, 9, 15),
        )
        world.db.add(member)
        world.db.flush()
        assessment = start_assessment(
            world.db, school_group_id=world.group_id, cycle_id=cycle.id,
            cycle_population_member_id=member.id, actor=admin)
        for competency in competencies:
            level = world.db.query(models.TalentRubricLevel).filter_by(
                framework_version_id=cycle.framework_version_id).order_by(models.TalentRubricLevel.display_order).first()
            _, assessment = set_competency_result(
                world.db, school_group_id=world.group_id, assessment_id=assessment.id,
                framework_competency_id=competency.id, rubric_level_id=level.id,
                expected_revision=assessment.revision, evidence="seed", actor=admin)
        complete_assessment(world.db, school_group_id=world.group_id, assessment_id=assessment.id,
                            expected_revision=assessment.revision, actor=admin)
    world.db.commit()


LOADING_PATHS = (
    lambda w: f"/api/talent/assessments?academic_year_id={w.year}&program_id={w.program_b}",
    lambda w: f"{ORG}/students?academic_year_id={w.year}&limit=100&offset=0",
    lambda w: f"/api/talent/results-analytics/programs/{w.program_b}/academic-years/{w.year}/classification",
    lambda w: f"/api/talent/results-analytics/programs/{w.program_b}/academic-years/{w.year}/talented",
    lambda w: f"/api/talent/evaluation-progress/programs/{w.program_b}/academic-years/{w.year}/branch-comparison?metric=current_overall_progress",
    lambda w: f"{ORG}/overview?academic_year_id={w.year}",
    lambda w: f"/api/talent/evaluation-plans?program_id={w.program_a}&academic_year_id={w.year}",
)


def test_talent_list_endpoints_do_not_scale_with_the_number_of_assessment_rows(world):
    baseline = {}
    for index, build in enumerate(LOADING_PATHS):
        baseline[index] = world.count_statements(build(world))[0]
    _add_completed_students(world, 6)  # +6 Students and +6 completed Assessments
    for index, build in enumerate(LOADING_PATHS):
        statements, _elapsed = world.count_statements(build(world))
        assert statements == baseline[index], (build(world), baseline[index], statements)


def test_talent_endpoint_statement_and_time_budgets_on_the_realistic_dataset(world):
    budgets = {
        # measured after the fix on the 10-Student / 20-Assessment dataset (before: 982 / 136 / 74 / 74 / 84 / 33 / 140)
        "assessments": (LOADING_PATHS[0], 130),
        "student_drill": (LOADING_PATHS[1], 30),
        "classification": (LOADING_PATHS[2], 30),
        "talented": (LOADING_PATHS[3], 30),
        "branch_comparison": (LOADING_PATHS[4], 40),
        "overview": (LOADING_PATHS[5], 16),
        "evaluation_plans": (LOADING_PATHS[6], 30),
    }
    for name, (build, ceiling) in budgets.items():
        statements, elapsed = world.count_statements(build(world))
        assert statements <= ceiling, (name, statements, ceiling)
        assert elapsed < 5.0, (name, elapsed)  # bounded wall clock (in-memory DB; generous ceiling)


def test_programs_summaries_no_longer_fails_when_an_annual_configuration_exists(world):
    """Regression: /programs/summaries raised AttributeError (HTTP 500) for any Program with a
    configuration in the selected Academic Year (it read a non-existent ``eligible_grade_levels``)."""
    response = world.get(f"/api/talent/programs/summaries?academic_year_id={world.year}")
    assert response.status_code == 200, response.text
    annual = [row["annual"] for row in response.json() if row["annual"]]
    assert annual and all(isinstance(item["eligible_grade_levels"], list) and item["eligible_grade_levels"] for item in annual)


def test_read_batch_is_request_scoped_and_never_leaks_between_reads(world):
    """Memoization is opt-in and discarded on exit: it cannot serve stale data afterwards."""
    from talent_read_batch import active, memo, read_batch

    session = world.Session()
    try:
        assert not active(session)
        calls = []
        assert memo(session, "k", lambda: calls.append(1) or 1) == 1
        assert memo(session, "k", lambda: calls.append(1) or 2) == 2  # inactive: always calls through
        with read_batch(session):
            assert memo(session, "k", lambda: 10) == 10
            assert memo(session, "k", lambda: 20) == 10  # memoized only inside the batch
        assert not active(session)
        assert memo(session, "k", lambda: 30) == 30      # discarded on exit
    finally:
        session.close()


def test_request_permission_checker_matches_auth_has_permission_for_every_key(world):
    """The per-request checker resolves the permission set once; every decision must equal
    ``auth.has_permission`` (including inactive users, empty keys and unknown keys)."""
    import auth
    from talent_request_permissions import request_permission_checker

    session = world.Session()
    try:
        admin = session.query(models.User).filter_by(user_id=world.admin_user_id).one()
        world.branch_limited_user(world.north)
        limited = session.query(models.User).filter_by(user_id="LTB0001").one()
        inactive = session.query(models.User).filter_by(user_id="LTB0001").one()
        inactive_copy = models.User(
            user_id="LTB0002", username="inactive_user", role="Administrator", user_type="TENANT",
            access_scope="ORGANIZATION", school_group_id=world.group_id, is_active=False,
        )
        keys = (
            "talent_analytics.view", "talent_assessments.delete", "students.force_delete_history",
            "talent_programs.view", "no.such.permission", "", "  ",
        )
        for user in (admin, limited, inactive_copy, None):
            checker = request_permission_checker(session, user, world.group_id)
            for key in keys:
                assert checker(key) == auth.has_permission(session, user, key, school_group_id=world.group_id), (
                    getattr(user, "user_id", None), key)
    finally:
        session.close()
