import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_programs import router
from talent_program_service import (
    TalentProgramError, activate_framework, add_framework_competency, add_rubric_level,
    configure_kpi, configure_review_candidate_policy, create_competency,
    create_framework_draft, create_program, get_framework_configuration,
    remove_descriptor, remove_framework_competency, remove_kpi, remove_review_candidate_policy,
    remove_rubric_level, reorder_rubric_levels, retire_framework, transition_program,
    update_rubric_level, upsert_descriptor, upsert_rubric,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine); session = sessionmaker(bind=engine)()
    session.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")]); session.commit()
    session.add_all([
        models.Branch(id=10, school_group_id=1, name="One"), models.Branch(id=20, school_group_id=2, name="Two"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"), models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ]); session.commit(); yield session; session.close()


def foundation(db, *, group=1, name="Performing Arts"):
    program = create_program(db, school_group_id=group, name=name)
    transition_program(db, school_group_id=group, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=group, program_id=program.id, title=f"{name} Framework")
    competency = create_competency(db, school_group_id=group, program_id=program.id, code="CORE", name="Core Practice")
    member, framework = add_framework_competency(db, school_group_id=group, program_id=program.id, framework_id=framework.id, competency_id=competency.id, expected_revision=1)
    rubric, framework = upsert_rubric(db, school_group_id=group, program_id=program.id, framework_id=framework.id, expected_revision=2, name=f"{name} Rubric")
    return program, framework, competency, member, rubric


def level(db, program, framework, *, code, label, numeric=None):
    row, framework = add_rubric_level(db, school_group_id=program.school_group_id, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, code=code, label=label, numeric_value=numeric)
    return row, framework


def test_program_specific_levels_are_configurable_and_not_global(db):
    p1, f1, _, _, _ = foundation(db, name="Performing Arts")
    _, f1 = level(db, p1, f1, code="DISCOVER", label="Discovering")
    _, f1 = level(db, p1, f1, code="PRESENT", label="Performance Ready")
    p2, f2, _, _, _ = foundation(db, name="Leadership")
    _, f2 = level(db, p2, f2, code="FOUND", label="Foundation")
    _, f2 = level(db, p2, f2, code="LEAD", label="Leads Others")
    _, f2 = level(db, p2, f2, code="MULTIPLY", label="Multiplies Leadership")
    assert [r.code for r in db.query(models.TalentRubricLevel).filter_by(framework_version_id=f1.id).order_by(models.TalentRubricLevel.display_order)] == ["DISCOVER", "PRESENT"]
    assert [r.code for r in db.query(models.TalentRubricLevel).filter_by(framework_version_id=f2.id).order_by(models.TalentRubricLevel.display_order)] == ["FOUND", "LEAD", "MULTIPLY"]
    assert db.query(models.TalentKpiConfiguration).count() == 0


def test_qualitative_program_activates_without_kpi_and_uses_rubric_policy(db):
    program, framework, _, member, _ = foundation(db)
    emerging, framework = level(db, program, framework, code="EXPLORING", label="Exploring")
    ready, framework = level(db, program, framework, code="READY", label="Stage Ready")
    _, framework = upsert_descriptor(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        framework_competency_id=member.id, rubric_level_id=ready.id, expected_revision=framework.revision, descriptor="Performs expressively and consistently.")
    policy, framework = configure_review_candidate_policy(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, is_enabled=True, match_mode="all", description="Human review threshold",
        rules=[{"rule_type": "rubric_level_at_or_above", "framework_competency_id": member.id, "rubric_level_id": ready.id}])
    assert policy.is_enabled and db.query(models.TalentKpiConfiguration).count() == 0
    activate_framework(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
        expected_fingerprint=framework.semantic_fingerprint, organization_authorized=True); db.commit()
    assert framework.status == "active" and emerging.numeric_value is None


def test_kpi_is_optional_bounded_and_rejects_executable_or_invalid_semantics(db):
    program, framework, _, member, _ = foundation(db, name="Academic Talent")
    _, framework = level(db, program, framework, code="ONE", label="One", numeric=1)
    _, framework = level(db, program, framework, code="TWO", label="Two", numeric=2)
    with pytest.raises(TalentProgramError) as executable:
        configure_kpi(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
            is_enabled=True, calculation_method="python_expression", result_scale_min=1, result_scale_max=4, interpretation="Unsafe",
            components=[{"framework_competency_id": member.id, "weight_basis_points": 10000}])
    assert executable.value.code == "invalid_kpi"
    with pytest.raises(TalentProgramError) as weight:
        configure_kpi(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
            is_enabled=True, result_scale_min=1, result_scale_max=4, interpretation="Scale",
            components=[{"framework_competency_id": member.id, "weight_basis_points": 9000}])
    assert weight.value.code == "invalid_kpi"
    kpi, framework = configure_kpi(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
        is_enabled=True, result_scale_min=1, result_scale_max=4, interpretation="Weighted rubric-level mean",
        components=[{"framework_competency_id": member.id, "weight_basis_points": 10000}])
    assert kpi.calculation_method == "weighted_level_average"


def test_kpi_component_requires_exact_framework_competency(db):
    program, framework, _, member, _ = foundation(db, name="Academic Talent")
    _, framework = level(db, program, framework, code="ONE", label="One", numeric=1)
    foreign_program, foreign_framework, _, foreign_member, _ = foundation(db, name="Other Program")
    with pytest.raises(TalentProgramError) as invalid:
        configure_kpi(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
            is_enabled=True, result_scale_min=1, result_scale_max=4, interpretation="Scale",
            components=[{"framework_competency_id": foreign_member.id, "weight_basis_points": 10000}])
    assert invalid.value.code == "invalid_kpi"


def test_enabled_kpi_numeric_scale_invariant_holds_across_later_level_mutations(db):
    program, framework, _, member, _ = foundation(db, name="Academic Talent")
    lvl1, framework = level(db, program, framework, code="ONE", label="One", numeric=1)
    _, framework = configure_kpi(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
        is_enabled=True, result_scale_min=1, result_scale_max=2, interpretation="Weighted rubric-level mean",
        components=[{"framework_competency_id": member.id, "weight_basis_points": 10000}])
    with pytest.raises(TalentProgramError) as missing_numeric:
        add_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, code="TWO", label="Two")
    assert missing_numeric.value.code == "invalid_kpi"
    with pytest.raises(TalentProgramError) as out_of_scale:
        add_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, code="TWO", label="Two", numeric_value=99)
    assert out_of_scale.value.code == "invalid_kpi"
    with pytest.raises(TalentProgramError) as nulled:
        update_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id, level_id=lvl1.id, expected_revision=framework.revision, numeric_value=None)
    assert nulled.value.code == "invalid_kpi"


def test_review_candidate_policy_rejects_duplicate_and_contradictory_rules(db):
    program, framework, _, member, _ = foundation(db, name="Leadership")
    level1, framework = level(db, program, framework, code="ONE", label="One", numeric=1)
    level2, framework = level(db, program, framework, code="TWO", label="Two", numeric=2)
    with pytest.raises(TalentProgramError) as duplicate_competency:
        configure_review_candidate_policy(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, is_enabled=True, match_mode="any", description=None,
            rules=[{"rule_type": "rubric_level_at_or_above", "framework_competency_id": member.id, "rubric_level_id": level1.id},
                   {"rule_type": "rubric_level_at_or_above", "framework_competency_id": member.id, "rubric_level_id": level2.id}])
    assert duplicate_competency.value.code == "duplicate_rule"
    kpi, framework = configure_kpi(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
        is_enabled=True, result_scale_min=1, result_scale_max=2, interpretation="Scale",
        components=[{"framework_competency_id": member.id, "weight_basis_points": 10000}])
    with pytest.raises(TalentProgramError) as duplicate_kpi:
        configure_review_candidate_policy(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, is_enabled=True, match_mode="any", description=None,
            rules=[{"rule_type": "kpi_at_or_above", "threshold_value": 1}, {"rule_type": "kpi_at_or_above", "threshold_value": 2}])
    assert duplicate_kpi.value.code == "duplicate_rule"


def test_descriptor_requires_exact_framework_competency_and_level(db):
    p1, f1, _, member1, _ = foundation(db, name="One Program")
    level1, f1 = level(db, p1, f1, code="A", label="A")
    p2, f2, _, member2, _ = foundation(db, name="Two Program")
    level2, f2 = level(db, p2, f2, code="B", label="B")
    for foreign_member, foreign_level in ((member2, level1), (member1, level2)):
        with pytest.raises(TalentProgramError) as invalid:
            upsert_descriptor(db, school_group_id=1, program_id=p1.id, framework_id=f1.id, framework_competency_id=foreign_member.id,
                rubric_level_id=foreign_level.id, expected_revision=f1.revision, descriptor="Forged")
        assert invalid.value.code == "invalid_descriptor_scope"
    db.add(models.TalentCompetencyRubricDescriptor(school_group_id=1, program_id=p1.id, framework_version_id=f1.id,
        rubric_id=db.query(models.TalentRubric).filter_by(framework_version_id=f1.id).one().id,
        framework_competency_id=member2.id, rubric_level_id=level1.id, descriptor="Forged"))
    with pytest.raises(IntegrityError): db.commit()
    db.rollback()


def test_level_order_uniqueness_stale_writes_and_fingerprint_changes(db):
    program, framework, _, _, _ = foundation(db)
    initial = framework.semantic_fingerprint
    first, framework = level(db, program, framework, code="A", label="A")
    assert framework.semantic_fingerprint != initial
    with pytest.raises(TalentProgramError) as stale:
        add_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision - 1, code="B", label="B")
    assert stale.value.code == "stale_framework"
    with pytest.raises(TalentProgramError) as duplicate:
        add_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, code="B", label="B", display_order=first.display_order)
    assert duplicate.value.code == "duplicate_order"


def test_active_and_retired_framework_configuration_is_immutable(db):
    program, framework, _, _, _ = foundation(db); rubric_level, framework = level(db, program, framework, code="A", label="A")
    activate_framework(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint, organization_authorized=True)
    with pytest.raises(TalentProgramError) as active:
        update_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id, level_id=rubric_level.id, expected_revision=framework.revision, label="Changed")
    assert active.value.code == "immutable_framework"
    retire_framework(db, school_group_id=1, program_id=program.id, framework_id=framework.id, organization_authorized=True)
    with pytest.raises(TalentProgramError) as retired:
        upsert_rubric(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, name="Changed")
    assert retired.value.code == "immutable_framework"


def test_activation_fingerprint_covers_m3_configuration(db):
    program, framework, _, _, _ = foundation(db); reviewed = framework.semantic_fingerprint
    _, framework = level(db, program, framework, code="A", label="A")
    with pytest.raises(TalentProgramError) as stale:
        activate_framework(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
            expected_fingerprint=reviewed, organization_authorized=True)
    assert stale.value.code == "stale_framework"


def test_clone_copies_independent_complete_m3_configuration(db):
    program, source, _, member, _ = foundation(db); rubric_level, source = level(db, program, source, code="READY", label="Ready")
    descriptor, source = upsert_descriptor(db, school_group_id=1, program_id=program.id, framework_id=source.id, framework_competency_id=member.id, rubric_level_id=rubric_level.id, expected_revision=source.revision, descriptor="Original")
    _, source = configure_review_candidate_policy(db, school_group_id=1, program_id=program.id, framework_id=source.id, expected_revision=source.revision, is_enabled=True, match_mode="all", description=None, rules=[{"rule_type": "rubric_level_at_or_above", "framework_competency_id": member.id, "rubric_level_id": rubric_level.id}])
    clone = create_framework_draft(db, school_group_id=1, program_id=program.id, title="Clone", clone_from_id=source.id, supersedes_framework_version_id=source.id)
    cloned = get_framework_configuration(db, school_group_id=1, program_id=program.id, framework_id=clone.id)
    assert cloned["rubric"]["name"] == "Performing Arts Rubric" and cloned["descriptors"][0]["descriptor"] == "Original"
    cloned_descriptor = db.query(models.TalentCompetencyRubricDescriptor).filter_by(framework_version_id=clone.id).one()
    remove_descriptor(db, school_group_id=1, program_id=program.id, framework_id=clone.id, descriptor_id=cloned_descriptor.id, expected_revision=clone.revision)
    assert db.query(models.TalentCompetencyRubricDescriptor).filter_by(id=descriptor.id).one().descriptor == "Original"


def test_removing_referenced_framework_competency_is_a_clean_business_rule_rejection(db):
    program, framework, competency, member, _ = foundation(db)
    rubric_level, framework = level(db, program, framework, code="A", label="A")
    _, framework = upsert_descriptor(db, school_group_id=1, program_id=program.id, framework_id=framework.id, framework_competency_id=member.id,
        rubric_level_id=rubric_level.id, expected_revision=framework.revision, descriptor="desc")
    with pytest.raises(TalentProgramError) as in_use:
        remove_framework_competency(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
            competency_id=competency.id, expected_revision=framework.revision)
    assert in_use.value.code == "competency_in_use"


def test_m3_mutations_extend_existing_bounded_audit(db):
    program, framework, _, _, _ = foundation(db); row, framework = level(db, program, framework, code="A", label="A")
    audit = db.query(models.TalentConfigurationAudit).filter_by(program_id=program.id, action="rubric_level_add").one()
    assert audit.resource_type == "rubric_level" and audit.resource_id == row.id
    assert '"revision"' in audit.after_json and '"semantic_fingerprint"' in audit.after_json


def _audits(db, program_id, action, resource_type):
    return db.query(models.TalentConfigurationAudit).filter_by(program_id=program_id, action=action, resource_type=resource_type).all()


def test_m3_audit_uses_specific_child_resource_identity_not_only_framework_version(db):
    program, framework, _, member, rubric = foundation(db, name="Governance Closure")
    rubric_audits = _audits(db, program.id, "rubric_upsert", "rubric")
    assert len(rubric_audits) == 1 and rubric_audits[0].resource_id == rubric.id

    level_one, framework = level(db, program, framework, code="ONE", label="One", numeric=1)
    add_audits = _audits(db, program.id, "rubric_level_add", "rubric_level")
    assert len(add_audits) == 1 and add_audits[0].resource_id == level_one.id

    level_two, framework = level(db, program, framework, code="TWO", label="Two", numeric=2)
    _, framework = update_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        level_id=level_one.id, expected_revision=framework.revision, label="One Updated")
    update_audits = _audits(db, program.id, "rubric_level_update", "rubric_level")
    assert len(update_audits) == 1 and update_audits[0].resource_id == level_one.id

    fingerprint_before_reorder = framework.semantic_fingerprint
    framework = reorder_rubric_levels(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        level_ids=[level_two.id, level_one.id], expected_revision=framework.revision)
    assert framework.semantic_fingerprint != fingerprint_before_reorder
    reorder_audits = _audits(db, program.id, "rubric_levels_reorder", "rubric_level")
    assert {a.resource_id for a in reorder_audits} == {level_one.id, level_two.id}

    descriptor, framework = upsert_descriptor(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        framework_competency_id=member.id, rubric_level_id=level_one.id, expected_revision=framework.revision, descriptor="Descriptor text")
    descriptor_audits = _audits(db, program.id, "rubric_descriptor_upsert", "rubric_descriptor")
    assert len(descriptor_audits) == 1 and descriptor_audits[0].resource_id == descriptor.id

    kpi, framework = configure_kpi(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
        is_enabled=True, result_scale_min=1, result_scale_max=2, interpretation="Weighted rubric-level mean",
        components=[{"framework_competency_id": member.id, "weight_basis_points": 10000}])
    kpi_config_audits = _audits(db, program.id, "kpi_configure", "kpi_configuration")
    assert len(kpi_config_audits) == 1 and kpi_config_audits[0].resource_id == kpi.id
    kpi_component_audits = _audits(db, program.id, "kpi_configure", "kpi_component")
    component = db.query(models.TalentKpiComponent).filter_by(kpi_configuration_id=kpi.id).one()
    assert len(kpi_component_audits) == 1 and kpi_component_audits[0].resource_id == component.id

    policy, framework = configure_review_candidate_policy(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, is_enabled=True, match_mode="all", description=None,
        rules=[{"rule_type": "rubric_level_at_or_above", "framework_competency_id": member.id, "rubric_level_id": level_two.id}])
    policy_audits = _audits(db, program.id, "review_candidate_policy_configure", "review_candidate_policy")
    assert len(policy_audits) == 1 and policy_audits[0].resource_id == policy.id
    rule_audits = _audits(db, program.id, "review_candidate_policy_configure", "review_candidate_rule")
    rule = db.query(models.TalentReviewCandidateRule).filter_by(policy_id=policy.id).one()
    assert len(rule_audits) == 1 and rule_audits[0].resource_id == rule.id

    # Every audit row keeps the additive before/after configuration shape - only
    # resource identity is more specific, not a rewrite of the audit shape.
    all_new_audits = (rubric_audits + add_audits + update_audits + reorder_audits
        + descriptor_audits + kpi_config_audits + kpi_component_audits + policy_audits + rule_audits)
    assert all('"configuration"' in a.before_json for a in all_new_audits)
    assert all('"semantic_fingerprint"' in a.after_json for a in all_new_audits)


def test_m3_removal_mutations_audit_the_removed_child_resource(db):
    program, framework, _, member, _ = foundation(db, name="Removal Audit")
    rubric_level, framework = level(db, program, framework, code="A", label="A", numeric=1)
    descriptor, framework = upsert_descriptor(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        framework_competency_id=member.id, rubric_level_id=rubric_level.id, expected_revision=framework.revision, descriptor="Text")
    kpi, framework = configure_kpi(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
        is_enabled=True, result_scale_min=1, result_scale_max=2, interpretation="Scale",
        components=[{"framework_competency_id": member.id, "weight_basis_points": 10000}])
    policy, framework = configure_review_candidate_policy(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, is_enabled=True, match_mode="all", description=None,
        rules=[{"rule_type": "kpi_at_or_above", "threshold_value": 1}])

    policy_id, kpi_id, descriptor_id = policy.id, kpi.id, descriptor.id
    framework = remove_review_candidate_policy(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision)
    assert _audits(db, program.id, "review_candidate_policy_remove", "review_candidate_policy")[0].resource_id == policy_id

    framework = remove_kpi(db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision)
    assert _audits(db, program.id, "kpi_remove", "kpi_configuration")[0].resource_id == kpi_id

    framework = remove_descriptor(db, school_group_id=1, program_id=program.id, framework_id=framework.id, descriptor_id=descriptor_id, expected_revision=framework.revision)
    assert _audits(db, program.id, "rubric_descriptor_remove", "rubric_descriptor")[0].resource_id == descriptor_id

    level_id = rubric_level.id
    framework = remove_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id, level_id=level_id, expected_revision=framework.revision)
    assert _audits(db, program.id, "rubric_level_remove", "rubric_level")[0].resource_id == level_id


def test_rubric_level_order_is_the_semantic_rank_independent_of_numeric_value(db):
    program, framework, _, member, _ = foundation(db, name="Qualitative Order")
    emerging, framework = level(db, program, framework, code="EXPLORING", label="Exploring")
    ready, framework = level(db, program, framework, code="READY", label="Stage Ready")
    assert emerging.numeric_value is None and ready.numeric_value is None
    # display_order (not numeric_value, which is absent here) is the documented
    # "at or above" semantic rank: READY was added after EXPLORING and must sort higher.
    assert ready.display_order > emerging.display_order
    payload = get_framework_configuration(db, school_group_id=1, program_id=program.id, framework_id=framework.id)
    ordered = sorted(payload["levels"], key=lambda item: item["order"])
    assert [item["code"] for item in ordered] == ["EXPLORING", "READY"]
    assert all(item["numeric_value"] is None for item in ordered)
    policy, framework = configure_review_candidate_policy(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, is_enabled=True, match_mode="all", description=None,
        rules=[{"rule_type": "rubric_level_at_or_above", "framework_competency_id": member.id, "rubric_level_id": ready.id}])
    assert policy.is_enabled and db.query(models.TalentKpiConfiguration).filter_by(framework_version_id=framework.id).count() == 0


def test_m3_api_reuses_view_manage_permissions(db):
    admin = models.User(user_id="1000000001", username="admin", role="Administrator", user_type="TENANT", access_scope="BRANCH", school_group_id=1, branch_id=10, academic_year_id=100, is_active=True)
    db.add(admin); db.commit(); admin.scope_school_group_id = 1; admin.scope_branch_id = 10
    program, framework, _, _, _ = foundation(db)
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_db] = lambda: db; app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        response = client.put(f"/api/talent/programs/{program.id}/frameworks/{framework.id}/rubric", json={"expected_revision": framework.revision, "name": "API Rubric"})
        assert response.status_code == 200
        assert client.get(f"/api/talent/programs/{program.id}/frameworks/{framework.id}/configuration").status_code == 200
        foreign, _, _, _, _ = foundation(db, group=2, name="Foreign")
        assert client.get(f"/api/talent/programs/{foreign.id}/frameworks/999/configuration").status_code == 404


def test_m3_migration_clean_idempotent_and_registered():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[models.SchoolGroup.__table__, models.Branch.__table__, models.AcademicYear.__table__, models.User.__table__, models.TalentProgram.__table__, models.TalentProgramFrameworkVersion.__table__, models.TalentCompetency.__table__, models.FrameworkCompetency.__table__, models.TalentConfigurationAudit.__table__])
    with engine.begin() as connection:
        db_migrations._talent_rubric_kpi_candidate_policy_foundation(engine, connection)
        db_migrations._talent_rubric_kpi_candidate_policy_foundation(engine, connection)
    expected = {"talent_rubrics", "talent_rubric_levels", "talent_competency_rubric_descriptors", "talent_kpi_configurations", "talent_kpi_components", "talent_review_candidate_policies", "talent_review_candidate_rules"}
    assert expected.issubset(inspect(engine).get_table_names())
    assert any(m.migration_id == "20260904_003_talent_rubric_kpi_candidate_policy_foundation" for m in db_migrations.MIGRATIONS)


def test_m3_migration_widens_narrow_m2_audit_resource_type_check_in_place():
    """Simulates a database where talent_configuration_audits was already created by
    the separate, already-applied M2 migration with the original narrow CHECK
    constraint. The M3 migration must widen it in place (SQLite table rebuild) so
    M3 child-resource audit rows are accepted, while preserving existing rows and
    staying idempotent."""
    from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, MetaData, String, Table, Text, text

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        models.SchoolGroup.__table__, models.Branch.__table__, models.AcademicYear.__table__, models.User.__table__,
        models.TalentProgram.__table__, models.TalentProgramFrameworkVersion.__table__, models.TalentCompetency.__table__,
        models.FrameworkCompetency.__table__,
    ])
    # Plain columns (no ForeignKey objects) intentionally: this Table lives in its
    # own MetaData to simulate the exact pre-M3 narrow CHECK independent of the
    # current model definition; FK enforcement is not what this test verifies.
    legacy_metadata = MetaData()
    Table(
        "talent_configuration_audits", legacy_metadata,
        Column("id", Integer, primary_key=True),
        Column("public_id", String(36), nullable=False, unique=True),
        Column("school_group_id", Integer, nullable=False),
        Column("program_id", Integer, nullable=False),
        Column("actor_user_id", String(10), nullable=True),
        Column("actor_branch_id", Integer, nullable=True),
        Column("resource_type", String(40), nullable=False),
        Column("resource_id", Integer, nullable=False),
        Column("action", String(40), nullable=False),
        Column("before_json", Text, nullable=True),
        Column("after_json", Text, nullable=True),
        Column("correlation_id", String(64), nullable=False),
        Column("created_at", DateTime, nullable=False),
        CheckConstraint(
            "resource_type IN ('program','annual_configuration','framework_version','competency','framework_competency')",
            name="ck_talent_configuration_audits_resource_type",
        ),
        Index("ix_talent_configuration_audits_scope_resource", "school_group_id", "program_id", "created_at"),
    )
    legacy_metadata.create_all(engine)

    insert_sql = (
        "INSERT INTO talent_configuration_audits (public_id, school_group_id, program_id, resource_type, "
        "resource_id, action, correlation_id, created_at) VALUES (:public_id, 1, 1, :resource_type, 1, 'create', 'corr', '2026-09-04 00:00:00')"
    )
    with engine.begin() as connection:
        connection.execute(text(insert_sql), {"public_id": "11111111-1111-1111-1111-111111111111", "resource_type": "framework_version"})
        with pytest.raises(IntegrityError):
            connection.execute(text(insert_sql), {"public_id": "22222222-2222-2222-2222-222222222222", "resource_type": "rubric_level"})

    with engine.begin() as connection:
        db_migrations._talent_rubric_kpi_candidate_policy_foundation(engine, connection)
    with engine.begin() as connection:
        db_migrations._talent_rubric_kpi_candidate_policy_foundation(engine, connection)  # idempotent rerun

    constraints = {c["name"]: str(c.get("sqltext") or "") for c in inspect(engine).get_check_constraints("talent_configuration_audits")}
    assert "rubric_level" in constraints.get("ck_talent_configuration_audits_resource_type", "")

    with engine.begin() as connection:
        connection.execute(text(insert_sql), {"public_id": "33333333-3333-3333-3333-333333333333", "resource_type": "rubric_level"})
        with pytest.raises(IntegrityError):
            connection.execute(text(insert_sql), {"public_id": "44444444-4444-4444-4444-444444444444", "resource_type": "not_a_real_type"})

    with engine.connect() as connection:
        preserved = connection.execute(text(
            "SELECT resource_type FROM talent_configuration_audits WHERE public_id = '11111111-1111-1111-1111-111111111111'"
        )).scalar()
    assert preserved == "framework_version"
