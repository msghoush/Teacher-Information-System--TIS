from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
import permission_registry
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_assessment_cycles import router
from student_academic_service import create_placement, create_student, transition_placement, update_student
from talent_assessment_cycle_service import (
    TalentAssessmentCycleError, close_cycle, create_cycle, frozen_population,
    open_cycle, population_fingerprint, preview_population,
    reconcile_open_cycle_population, synchronize_placement_to_open_cycles,
    update_cycle,
)
from talent_student_assessment_service import start_assessment
from talent_program_service import (
    activate_framework, create_framework_draft, create_program, retire_framework,
    transition_program, upsert_annual_configuration,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")])
    session.commit()
    session.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=11, school_group_id=1, name="One B"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ])
    session.commit()
    session.add_all([
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=1001, branch_id=11, academic_year_id=100, grade_level="1", section_name="B", class_status="Current"),
        models.PlanningSection(id=1002, branch_id=10, academic_year_id=100, grade_level="4", section_name="D", class_status="Current"),
        # Grade "2" is real Planning-configured data (not just a Program eligible-Grade
        # fixture default) so upsert_annual_configuration's Planning-scoped Grade
        # validation accepts the existing foundation() default of ("1", "2").
        models.PlanningSection(id=1003, branch_id=10, academic_year_id=100, grade_level="2", section_name="C", class_status="Current"),
    ])
    session.commit()
    yield engine, session
    session.close()


def foundation(db, *, group=1, year=100, name="Potential", grades=("1", "2")):
    program = create_program(db, school_group_id=group, name=name)
    transition_program(db, school_group_id=group, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=group, program_id=program.id, title=f"{name} Framework")
    activate_framework(db, school_group_id=group, program_id=program.id, framework_id=framework.id,
                       expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                       organization_authorized=True)
    config = upsert_annual_configuration(db, school_group_id=group, program_id=program.id,
                                         academic_year_id=year, is_enabled=True,
                                         eligible_grade_levels=list(grades))
    db.commit()
    return program, framework, config


def student_placement(db, *, first, branch=10, section=1000, grade=None,
                      start=datetime(2026, 9, 1), end=None):
    student = create_student(db, school_group_id=1, first_name=first, last_name="Learner")
    placement = create_placement(
        db, school_group_id=1, student_id=student.id, academic_year_id=100,
        branch_id=branch, planning_section_id=section,
        grade_level=grade, section_name="Direct" if section is None else None,
        effective_from=start, effective_to=end,
    )
    db.commit()
    return student, placement


def draft_cycle(db, program, framework, *, effective=datetime(2026, 10, 1)):
    row = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                       framework_version_id=framework.id, title="Autumn Review",
                       population_effective_at=effective)
    db.commit()
    return row


def test_draft_cycle_context_alignment_and_stale_metadata_edits(db):
    _, session = db
    program, framework, _ = foundation(session)
    cycle = draft_cycle(session, program, framework)
    assert cycle.status == "draft" and cycle.population_effective_at == datetime(2026, 10, 1)
    updated = update_cycle(session, school_group_id=1, cycle_id=cycle.id,
                           expected_revision=1, title="Updated", population_effective_at=datetime(2026, 11, 1))
    assert updated.revision == 2
    with pytest.raises(TalentAssessmentCycleError) as stale:
        update_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1, title="Lost")
    assert stale.value.code == "stale_cycle"
    with pytest.raises(TalentAssessmentCycleError) as foreign:
        create_cycle(session, school_group_id=2, program_id=program.id, academic_year_id=200,
                     framework_version_id=framework.id, title="Forged")
    assert foreign.value.code == "invalid_scope"


def test_effective_time_grade_eligibility_and_dynamic_draft_preview(db):
    _, session = db
    program, framework, config = foundation(session, grades=("1",))
    eligible, placement = student_placement(session, first="Eligible", start=datetime(2026, 9, 1))
    student_placement(session, first="Late", start=datetime(2026, 11, 1))
    student_placement(session, first="Ended", start=datetime(2026, 8, 1), end=datetime(2026, 10, 1))
    student_placement(session, first="Grade Four", section=1002)
    create_student(session, school_group_id=1, first_name="No Placement", last_name="Learner")
    session.commit()
    cycle = draft_cycle(session, program, framework)
    _, preview = preview_population(
        session, school_group_id=1, cycle_id=cycle.id,
        effective_at=datetime(2026, 10, 1),
    )
    assert [(row["student_id"], row["academic_placement_id"]) for row in preview] == [(eligible.id, placement.id)]
    config.eligible_grade_levels_csv = "1,4"
    session.commit()
    _, changed = preview_population(
        session, school_group_id=1, cycle_id=cycle.id,
        effective_at=datetime(2026, 10, 1),
    )
    assert len(changed) == 2


def test_current_student_status_never_reinterprets_historical_eligibility(db):
    # Student.status is only current mutable state with no effective-dated
    # history (see models.py Student / student_academic_service.py). A
    # present-day status change must never retroactively alter eligibility
    # for an already-defined historical population_effective_at instant.
    _, session = db
    program, framework, _ = foundation(session, grades=("1",))
    student, placement = student_placement(session, first="LaterInactive", start=datetime(2026, 9, 1))
    session.commit()
    cycle = draft_cycle(session, program, framework, effective=datetime(2026, 10, 1))
    _, preview_before = preview_population(
        session, school_group_id=1, cycle_id=cycle.id,
        effective_at=datetime(2026, 10, 1),
    )
    assert [row["student_id"] for row in preview_before] == [student.id]
    update_student(session, school_group_id=1, student_id=student.id, status="inactive")
    session.commit()
    _, preview_after = preview_population(
        session, school_group_id=1, cycle_id=cycle.id,
        effective_at=datetime(2026, 10, 1),
    )
    assert [row["student_id"] for row in preview_after] == [student.id]
    opened = open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision,
                        organization_authorized=True)
    session.commit()
    assert opened.population_count == 1
    _, members = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    assert [member.student_id for member in members] == [student.id]


def test_live_preview_and_open_reconciliation_include_students_placed_after_configured_population_date(db):
    """Owner-reproduced regression: the Cycle's configured Student list date
    must not become a permanent cutoff for a Draft live preview or for ADR 0033
    additive reconciliation while the Cycle is Open.
    """
    _, session = db
    program, framework, _ = foundation(session, name="Mental Math", grades=("1",))
    initial_student, _ = student_placement(
        session, first="Initial", start=datetime(2026, 8, 1)
    )
    cycle = draft_cycle(
        session, program, framework, effective=datetime(2026, 8, 30, 22, 4)
    )

    later_student, later_placement = student_placement(
        session, first="Later", start=datetime(2026, 9, 5)
    )

    _, preview = preview_population(
        session, school_group_id=1, cycle_id=cycle.id,
        effective_at=datetime(2026, 9, 11),
    )
    assert {row["student_id"] for row in preview} == {initial_student.id, later_student.id}

    opened = open_cycle(
        session, school_group_id=1, cycle_id=cycle.id,
        expected_revision=cycle.revision, organization_authorized=True,
    )
    session.commit()
    _, initially_frozen = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    assert {row.student_id for row in initially_frozen} == {initial_student.id}

    reconciled, additions = reconcile_open_cycle_population(
        session, school_group_id=1, cycle_id=cycle.id,
        expected_revision=opened.revision, organization_authorized=True,
        effective_at=datetime(2026, 9, 11),
    )
    session.commit()

    assert [row.student_id for row in additions] == [later_student.id]
    assert additions[0].academic_placement_id == later_placement.id
    assert additions[0].population_effective_at == datetime(2026, 9, 11)
    assert reconciled.population_count == 2


def test_missing_disabled_config_and_unusable_framework_block_atomic_open(db):
    _, session = db
    program, framework, config = foundation(session)
    cycle = draft_cycle(session, program, framework)
    config.is_enabled = False
    session.commit()
    with pytest.raises(TalentAssessmentCycleError) as disabled:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                   organization_authorized=True)
    assert disabled.value.code == "annual_configuration_unavailable"
    assert cycle.status == "draft" and session.query(models.TalentAssessmentCyclePopulationMember).count() == 0
    session.delete(config)
    session.commit()
    with pytest.raises(TalentAssessmentCycleError) as missing:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                   organization_authorized=True)
    assert missing.value.code == "annual_configuration_unavailable"
    upsert_annual_configuration(session, school_group_id=1, program_id=program.id,
                                academic_year_id=100, is_enabled=True,
                                eligible_grade_levels=["1", "2"])
    framework.status = "retired"
    session.commit()
    with pytest.raises(TalentAssessmentCycleError) as unusable:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                   organization_authorized=True)
    assert unusable.value.code == "unusable_framework"
    assert session.query(models.TalentAssessmentCyclePopulationMember).count() == 0


def test_open_freezes_exact_context_and_fingerprint_then_close_is_final(db):
    _, session = db
    program, framework, _ = foundation(session, grades=("1",))
    student, placement = student_placement(session, first="Maya")
    cycle = draft_cycle(session, program, framework)
    opened = open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                        organization_authorized=True)
    session.commit()
    _, members = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    assert opened.status == "open" and opened.population_count == 1
    member = members[0]
    assert (member.student_id, member.academic_placement_id, member.branch_id, member.grade_level, member.section_name) == (student.id, placement.id, 10, "1", "A")
    canonical = [dict(student_id=member.student_id, academic_placement_id=member.academic_placement_id,
                      academic_year_id=member.academic_year_id, branch_id=member.branch_id,
                      grade_level=member.grade_level, section_name=member.section_name)]
    assert population_fingerprint(cycle, canonical) == opened.population_fingerprint
    assert population_fingerprint(cycle, list(reversed(canonical))) == opened.population_fingerprint
    closed = close_cycle(session, school_group_id=1, cycle_id=cycle.id,
                         expected_revision=opened.revision, organization_authorized=True)
    session.commit()
    assert closed.status == "closed"
    with pytest.raises(TalentAssessmentCycleError):
        open_cycle(session, school_group_id=1, cycle_id=cycle.id,
                   expected_revision=closed.revision, organization_authorized=True)
    with pytest.raises(TalentAssessmentCycleError) as immutable:
        update_cycle(session, school_group_id=1, cycle_id=cycle.id,
                     expected_revision=closed.revision, title="Rewrite")
    assert immutable.value.code == "immutable_cycle"


def test_open_cycle_additively_synchronizes_newly_eligible_student_without_rewriting_evidence(db):
    _, session = db
    program, framework, _ = foundation(session, name="Mental Math", grades=("1",))
    existing_student, _ = student_placement(session, first="Existing")
    cycle = draft_cycle(session, program, framework)
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
               organization_authorized=True)
    session.commit()
    _, original_members = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    original_member = original_members[0]
    existing_assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id,
        cycle_population_member_id=original_member.id,
    )
    session.commit()
    original_fingerprint = cycle.population_fingerprint

    new_student, placement = student_placement(
        session, first="Newly Eligible", start=datetime(2026, 11, 1)
    )
    synchronized = synchronize_placement_to_open_cycles(
        session, school_group_id=1, student_id=new_student.id,
        academic_placement_id=placement.id, effective_at=datetime(2026, 11, 2),
    )
    session.commit()

    assert [row.id for row in synchronized] == [cycle.id]
    _, members = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    assert [row.student_id for row in members] == [existing_student.id, new_student.id]
    added = next(row for row in members if row.student_id == new_student.id)
    assert (added.academic_placement_id, added.branch_id, added.grade_level, added.section_name) == (
        placement.id, 10, "1", "A"
    )
    assert added.population_effective_at == datetime(2026, 11, 2)
    assert cycle.population_count == 2
    assert cycle.population_fingerprint != original_fingerprint
    assert session.get(models.TalentStudentAssessment, existing_assessment.id).revision == 1
    assert session.query(models.TalentStudentAssessment).filter_by(cycle_id=cycle.id).count() == 1
    assert session.query(models.TalentAssessmentAudit).filter_by(
        cycle_id=cycle.id, action="population_sync"
    ).count() == 1

    # The new member is Not Started until the existing assessment service is used.
    new_assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id,
        cycle_population_member_id=added.id,
    )
    assert new_assessment.status == "in_progress"

    close_cycle(session, school_group_id=1, cycle_id=cycle.id,
                expected_revision=cycle.revision, organization_authorized=True)
    session.commit()
    another_student, another_placement = student_placement(
        session, first="After Close", start=datetime(2026, 11, 3)
    )
    assert synchronize_placement_to_open_cycles(
        session, school_group_id=1, student_id=another_student.id,
        academic_placement_id=another_placement.id, effective_at=datetime(2026, 11, 4),
    ) == []
    assert cycle.population_count == 2


def test_post_open_sources_cannot_reinterpret_frozen_population(db):
    _, session = db
    program, framework, config = foundation(session, grades=("1",))
    student, placement = student_placement(session, first="Historical")
    cycle = draft_cycle(session, program, framework)
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
               organization_authorized=True)
    session.commit()
    section = session.get(models.PlanningSection, 1000)
    section.section_name = "RENAMED"
    section.grade_level = "4"
    config.eligible_grade_levels_csv = "4"
    _, later = transition_placement(
        session, school_group_id=1, student_id=student.id, placement_id=placement.id,
        transition_at=datetime(2026, 12, 1), academic_year_id=100, branch_id=11,
        planning_section_id=1001,
    )
    retire_framework(session, school_group_id=1, program_id=program.id,
                     framework_id=framework.id, organization_authorized=True)
    session.commit()
    cycle, members = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    assert cycle.framework_version_id == framework.id and framework.status == "retired"
    assert later.branch_id == 11
    assert [(row.branch_id, row.grade_level, row.section_name, row.planning_section_id) for row in members] == [(10, "1", "A", 1000)]


def test_open_requires_organization_scope_and_cannot_duplicate_members(db):
    _, session = db
    program, framework, _ = foundation(session)
    student_placement(session, first="One")
    cycle = draft_cycle(session, program, framework)
    with pytest.raises(TalentAssessmentCycleError) as denied:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                   organization_authorized=False)
    assert denied.value.code == "organization_authority_required"
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
               organization_authorized=True)
    session.commit()
    with pytest.raises(TalentAssessmentCycleError) as reopened:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=2,
                   organization_authorized=True)
    assert reopened.value.code == "invalid_lifecycle"
    assert session.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id).count() == 1


def _user(user_id, *, branch, scope, role="Administrator", group=1):
    return models.User(user_id=user_id, username=f"user{user_id}", role=role, user_type="TENANT",
                       access_scope=scope, school_group_id=group, branch_id=branch,
                       academic_year_id=100 if group == 1 else 200, is_active=True)


def _client(db, user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_branch_manage_can_author_draft_but_never_open(db):
    _, session = db
    program, framework, _ = foundation(session)
    branch_admin = _user("1000000001", branch=10, scope="BRANCH")
    session.add(branch_admin)
    session.commit()
    with _client(session, branch_admin) as client:
        created = client.post("/api/talent/assessment-cycles", json={
            "program_id": program.id, "academic_year_id": 100,
            "framework_version_id": framework.id, "title": "Branch Authored",
            "population_effective_at": "2026-10-01T00:00:00Z",
        })
        assert created.status_code == 201
        cycle_id = created.json()["id"]
        assert client.patch(f"/api/talent/assessment-cycles/{cycle_id}", json={"expected_revision": 1, "title": "Edited"}).status_code == 200
        denied = client.post(f"/api/talent/assessment-cycles/{cycle_id}/open", json={"expected_revision": 2})
        assert denied.status_code == 403 and denied.json()["code"] == "organization_authority_required"


def test_population_permission_and_branch_filtered_preview_do_not_leak_totals(db):
    _, session = db
    program, framework, _ = foundation(session, grades=("1",))
    student_placement(session, first="Branch A", branch=10, section=1000)
    student_placement(session, first="Branch B", branch=11, section=1001)
    cycle = draft_cycle(session, program, framework)
    branch_admin = _user("1000000001", branch=10, scope="BRANCH")
    view_only = _user("1000000002", branch=10, scope="BRANCH", role="Editor")
    session.add_all([branch_admin, view_only, models.RolePermission(
        school_group_id=1, role="Editor", permission_key="talent_assessment_cycles.view", is_allowed=True
    )])
    session.commit()
    with _client(session, view_only) as client:
        assert client.get(f"/api/talent/assessment-cycles/{cycle.id}").status_code == 200
        assert client.get(f"/api/talent/assessment-cycles/{cycle.id}/population/preview").status_code == 403
    with _client(session, branch_admin) as client:
        result = client.get(f"/api/talent/assessment-cycles/{cycle.id}/population/preview")
        assert result.status_code == 200
        body = result.json()
        assert body["scope"] == "authorized_branches" and body["is_filtered"] is True
        assert body["count"] == 1 and body["members"][0]["branch_id"] == 10
        assert "population_fingerprint" not in body and "population_count" not in body


def test_frozen_read_uses_historical_branch_while_organization_sees_integrity(db):
    _, session = db
    program, framework, _ = foundation(session, grades=("1",))
    student, placement = student_placement(session, first="Transfer", branch=10, section=1000)
    student_placement(session, first="Other", branch=11, section=1001)
    cycle = draft_cycle(session, program, framework)
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
               organization_authorized=True)
    _, current = transition_placement(session, school_group_id=1, student_id=student.id,
                                      placement_id=placement.id, transition_at=datetime(2026, 12, 1),
                                      academic_year_id=100, branch_id=11, planning_section_id=1001)
    branch_admin = _user("1000000001", branch=10, scope="BRANCH")
    org_admin = _user("1000000002", branch=10, scope="ORGANIZATION")
    session.add_all([branch_admin, org_admin])
    session.commit()
    assert current.branch_id == 11
    with _client(session, branch_admin) as client:
        body = client.get(f"/api/talent/assessment-cycles/{cycle.id}/population").json()
        assert body["count"] == 1 and body["members"][0]["student_id"] == student.id
        assert body["members"][0]["branch_id"] == 10
        assert "population_count" not in body and "population_fingerprint" not in body
    with _client(session, org_admin) as client:
        body = client.get(f"/api/talent/assessment-cycles/{cycle.id}/population").json()
        assert body["count"] == body["population_count"] == 2
        assert body["population_fingerprint"] == cycle.population_fingerprint


def test_viewing_open_cycle_population_auto_reconciles_missed_eligible_student(db):
    """Regression for the P0 gap: a Student who became eligible without ever
    triggering ``synchronize_placement_to_open_cycles`` (e.g. placed before
    this reconciliation existed, or any other synchronization gap) must still
    surface as "Not Started" the next time an organization-authorized viewer
    opens the Cycle's population, per ADR 0033's "opening an existing Open
    assessment invokes ... before reading its members" resolved condition -
    without requiring an explicit call to the population/synchronize route.
    """
    _, session = db
    program, framework, _ = foundation(session, grades=("1",))
    student_placement(session, first="Already Open", branch=10, section=1000)
    cycle = draft_cycle(session, program, framework)
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
               organization_authorized=True)
    assert cycle.population_count == 1
    # Simulate a Student who became eligible without going through the
    # placement-save synchronization path (the real-world gap this guards).
    late_student, _ = student_placement(session, first="Missed", branch=10, section=1000)
    org_admin = _user("1000000003", branch=10, scope="ORGANIZATION")
    session.add(org_admin)
    session.commit()
    with _client(session, org_admin) as client:
        body = client.get(f"/api/talent/assessment-cycles/{cycle.id}/population").json()
        assert body["count"] == 2
        assert late_student.id in {m["student_id"] for m in body["members"]}
    session.refresh(cycle)
    assert cycle.population_count == 2


def test_dedicated_permissions_and_cross_tenant_ids_are_non_enumerating(db):
    _, session = db
    program, framework, _ = foundation(session)
    cycle = draft_cycle(session, program, framework)
    editor = _user("1000000001", branch=10, scope="ORGANIZATION", role="Editor")
    foreign_admin = _user("1000000002", branch=20, scope="ORGANIZATION", group=2)
    session.add_all([editor, foreign_admin])
    session.add_all([
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_programs.manage", is_allowed=True),
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_programs.govern", is_allowed=True),
    ])
    session.commit()
    with _client(session, editor) as client:
        assert client.post("/api/talent/assessment-cycles", json={}).status_code == 403
        assert client.post(f"/api/talent/assessment-cycles/{cycle.id}/open", json={"expected_revision": 1}).status_code == 403
    with _client(session, foreign_admin) as client:
        assert client.get(f"/api/talent/assessment-cycles/{cycle.id}").status_code == 404
        assert client.get(f"/api/talent/assessment-cycles/{cycle.id}/population/preview").status_code == 404
    defaults = permission_registry.get_default_permissions_for_role("Administrator")
    editor_defaults = permission_registry.get_default_permissions_for_role("Editor")
    assert all(key in defaults for key in {
        "talent_assessment_cycles.view", "talent_assessment_cycles.manage",
        "talent_assessment_cycles.view_population", "talent_assessment_cycles.govern",
    })
    assert not any(key.startswith("talent_assessment_cycles.") for key in editor_defaults)


def test_cycle_audit_is_append_only_and_open_records_population_provenance(db):
    _, session = db
    program, framework, _ = foundation(session)
    student_placement(session, first="Audited")
    cycle = draft_cycle(session, program, framework)
    update_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1, title="Audited Cycle")
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=2,
               organization_authorized=True)
    close_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=3,
                organization_authorized=True)
    session.commit()
    audits = session.query(models.TalentAssessmentAudit).filter_by(cycle_id=cycle.id).order_by(models.TalentAssessmentAudit.id).all()
    assert [row.action for row in audits] == ["create", "update", "open", "close"]
    assert cycle.population_fingerprint in audits[2].after_json
    assert "effective_at" in audits[2].after_json and '"count":1' in audits[2].after_json


def test_m4_migration_is_additive_and_idempotent(db):
    engine, session = db
    session.close()
    with engine.begin() as connection:
        models.TalentAssessmentAudit.__table__.drop(connection)
        models.TalentAssessmentCyclePopulationMember.__table__.drop(connection)
        models.TalentAssessmentCycle.__table__.drop(connection)
        db_migrations._talent_assessment_cycle_frozen_population_foundation(engine, connection)
        db_migrations._talent_assessment_cycle_frozen_population_foundation(engine, connection)
    expected = {"talent_assessment_cycles", "talent_assessment_cycle_population_members", "talent_assessment_audits"}
    assert expected.issubset(inspect(engine).get_table_names())
    assert any(row.migration_id == "20260904_004_talent_assessment_cycle_frozen_population" for row in db_migrations.MIGRATIONS)


def test_forged_cross_tenant_population_relationship_is_rejected(db):
    _, session = db
    program, framework, _ = foundation(session)
    student, placement = student_placement(session, first="Scoped")
    cycle = draft_cycle(session, program, framework)
    session.add(models.TalentAssessmentCyclePopulationMember(
        school_group_id=2, cycle_id=cycle.id, program_id=program.id,
        academic_year_id=100, framework_version_id=framework.id,
        student_id=student.id, academic_placement_id=placement.id, branch_id=10,
        grade_level="1", section_name="A", population_effective_at=datetime(2026, 10, 1),
    ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_reconcile_open_cycle_population_is_additive_idempotent_and_governed(db):
    _, session = db
    program, framework, _ = foundation(session, name="Reconcile", grades=("1",))
    existing_student, _ = student_placement(session, first="Existing")
    cycle = draft_cycle(session, program, framework)
    opened = open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                        organization_authorized=True)
    session.commit()
    _, original_members = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    original_member = original_members[0]
    existing_assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id,
        cycle_population_member_id=original_member.id,
    )
    session.commit()

    # Draft/Closed Cycles must reject synchronization.
    draft = draft_cycle(session, program, framework)
    with pytest.raises(TalentAssessmentCycleError) as invalid:
        reconcile_open_cycle_population(session, school_group_id=1, cycle_id=draft.id,
                                        expected_revision=1, organization_authorized=True)
    assert invalid.value.code == "invalid_lifecycle"

    # Organization authority is required.
    with pytest.raises(TalentAssessmentCycleError) as denied:
        reconcile_open_cycle_population(session, school_group_id=1, cycle_id=opened.id,
                                        expected_revision=opened.revision, organization_authorized=False)
    assert denied.value.code == "organization_authority_required"

    # Stale expected_revision is rejected.
    with pytest.raises(TalentAssessmentCycleError) as stale:
        reconcile_open_cycle_population(session, school_group_id=1, cycle_id=opened.id,
                                        expected_revision=opened.revision + 1, organization_authorized=True)
    assert stale.value.code == "stale_cycle"

    # No newly eligible Student yet: idempotent no-op.
    unchanged_cycle, no_additions = reconcile_open_cycle_population(
        session, school_group_id=1, cycle_id=opened.id,
        expected_revision=opened.revision, organization_authorized=True,
    )
    session.commit()
    assert no_additions == []
    assert unchanged_cycle.revision == opened.revision
    assert unchanged_cycle.population_count == 1
    revision_before_addition = unchanged_cycle.revision

    # Backdated Placement (effective before the Cycle's fixed population_effective_at)
    # created after Open: derive_eligible_population would already include this
    # Student at the historical instant, but the row was never frozen because the
    # Placement did not exist yet when the Cycle opened. Reconciliation must
    # additively catch this Student up.
    new_student, placement = student_placement(session, first="NewlyEligible", start=datetime(2026, 9, 15))
    reconciled_cycle, additions = reconcile_open_cycle_population(
        session, school_group_id=1, cycle_id=opened.id,
        expected_revision=revision_before_addition, organization_authorized=True,
    )
    session.commit()
    assert len(additions) == 1
    assert reconciled_cycle.revision == revision_before_addition + 1
    assert reconciled_cycle.population_count == 2
    revision_after_addition = reconciled_cycle.revision
    _, members = frozen_population(session, school_group_id=1, cycle_id=opened.id)
    assert {row.student_id for row in members} == {existing_student.id, new_student.id}
    added = next(row for row in members if row.student_id == new_student.id)
    assert added.academic_placement_id == placement.id
    # Existing member and its assessment evidence are untouched.
    assert session.get(models.TalentStudentAssessment, existing_assessment.id).revision == 1
    assert session.query(models.TalentAssessmentAudit).filter_by(
        cycle_id=opened.id, action="population_sync"
    ).count() == 1

    # Calling again with nothing new is a safe no-op.
    final_cycle, second_additions = reconcile_open_cycle_population(
        session, school_group_id=1, cycle_id=opened.id,
        expected_revision=revision_after_addition, organization_authorized=True,
    )
    session.commit()
    assert second_additions == []
    assert final_cycle.revision == revision_after_addition
    assert final_cycle.population_count == 2
