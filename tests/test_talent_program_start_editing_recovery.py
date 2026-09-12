"""Owner recovery: Start Editing's old optional "Copy the current rubric
structure" checkbox let an accidental empty Draft be created, hiding an
existing Program's real Competencies (e.g. "Qaaidah Nouraniah" with 9
configured Competencies) behind a blank editable build. That checkbox has
been removed - Start Editing now always clones automatically - and
`recover_accidental_empty_draft` is the governed, tested recovery path for
any Program already caught by the old defect.
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from talent_program_service import (
    TalentProgramError, add_framework_competency, add_rubric_level, create_competency,
    create_framework_draft, create_program, get_framework_configuration,
    recover_accidental_empty_draft, transition_program, update_framework_competency,
    upsert_descriptor, upsert_rubric,
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
    yield session
    session.close()


def foundation(db, *, group=1, name="Qaaidah Nouraniah", competency_count=9):
    """Build a source Framework with `competency_count` fully-configured
    Competencies (each with its own KPI, two Levels, and a generic plus
    Grade-specific descriptor) and activate it - mirroring the Owner's real
    Program state before the accidental Start Editing."""
    program = create_program(db, school_group_id=group, name=name)
    transition_program(db, school_group_id=group, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=group, program_id=program.id, title=f"{name} Framework")
    members = []
    for index in range(1, competency_count + 1):
        lineage = create_competency(db, school_group_id=group, program_id=program.id, code=f"C{index}", name=f"Competency {index}", description=f"Description {index}")
        member, framework = add_framework_competency(
            db, school_group_id=group, program_id=program.id, framework_id=framework.id,
            competency_id=lineage.id, expected_revision=framework.revision, grade_level="1" if index % 2 else "2",
        )
        rubric, framework = upsert_rubric(
            db, school_group_id=group, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, framework_competency_id=member.id, name=f"Competency {index} KPI",
        )
        level_rows = []
        for level_code, level_label in (("L1", "Beginning"), ("L2", "Advanced")):
            level, framework = add_rubric_level(
                db, school_group_id=group, program_id=program.id, framework_id=framework.id,
                expected_revision=framework.revision, framework_competency_id=member.id, code=level_code, label=level_label,
            )
            level_rows.append(level)
            _, framework = upsert_descriptor(
                db, school_group_id=group, program_id=program.id, framework_id=framework.id,
                framework_competency_id=member.id, rubric_level_id=level.id, expected_revision=framework.revision,
                descriptor=f"{level_label} descriptor for Competency {index}",
            )
            _, framework = upsert_descriptor(
                db, school_group_id=group, program_id=program.id, framework_id=framework.id,
                framework_competency_id=member.id, rubric_level_id=level.id, expected_revision=framework.revision,
                descriptor=f"{level_label} Grade-specific descriptor for Competency {index}", grade_level=member.grade_level,
            )
        members.append((lineage, member, rubric, level_rows))
    from talent_program_service import activate_framework
    activate_framework(
        db, school_group_id=group, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
        organization_authorized=True,
    )
    return program, framework, members


def simulate_accidental_empty_draft(db, *, program, active_framework):
    """Mirrors exactly what the old UI did when "Copy the current rubric
    structure" was left unchecked: create_framework_draft with no
    clone_from_id at all."""
    return create_framework_draft(
        db, school_group_id=program.school_group_id, program_id=program.id,
        title=f"{program.name} updated rubric", summary=None,
        supersedes_framework_version_id=active_framework.id,
        clone_from_id=None,
    )


def test_source_framework_has_the_owners_nine_competencies(db):
    program, active_framework, members = foundation(db)
    stored = db.query(models.FrameworkCompetency).filter_by(framework_version_id=active_framework.id).all()
    assert len(stored) == 9
    assert len(members) == 9


def test_start_editing_without_clone_produces_the_accidental_empty_draft(db):
    program, active_framework, _members = foundation(db)
    empty_draft = simulate_accidental_empty_draft(db, program=program, active_framework=active_framework)
    assert empty_draft.status == "draft"
    assert db.query(models.FrameworkCompetency).filter_by(framework_version_id=empty_draft.id).count() == 0
    assert empty_draft.supersedes_framework_version_id == active_framework.id


def test_recovery_restores_all_nine_competencies_into_a_new_independent_draft(db):
    program, active_framework, _members = foundation(db)
    empty_draft = simulate_accidental_empty_draft(db, program=program, active_framework=active_framework)

    source, recovered_from_empty, recovered = recover_accidental_empty_draft(
        db, school_group_id=1, program_id=program.id, empty_draft_id=empty_draft.id,
    )

    assert source.id == active_framework.id
    assert recovered_from_empty.id == empty_draft.id
    assert recovered.id not in (active_framework.id, empty_draft.id)
    assert recovered.status == "draft"
    recovered_members = db.query(models.FrameworkCompetency).filter_by(framework_version_id=recovered.id).all()
    assert len(recovered_members) == 9
    # Grade assignments and ordering are preserved from the source.
    source_members = sorted(
        db.query(models.FrameworkCompetency).filter_by(framework_version_id=active_framework.id).all(),
        key=lambda m: m.display_order,
    )
    recovered_sorted = sorted(recovered_members, key=lambda m: m.display_order)
    assert [m.grade_level for m in recovered_sorted] == [m.grade_level for m in source_members]
    assert [m.label for m in recovered_sorted] == [m.label for m in source_members]
    assert [m.display_order for m in recovered_sorted] == [m.display_order for m in source_members]
    # Independent identities - never shared rows with the source.
    assert {m.id for m in recovered_members}.isdisjoint({m.id for m in source_members})
    assert {m.talent_competency_id for m in recovered_members} == {m.talent_competency_id for m in source_members}


def test_recovery_preserves_kpi_levels_and_descriptors_for_every_competency(db):
    program, active_framework, _members = foundation(db)
    empty_draft = simulate_accidental_empty_draft(db, program=program, active_framework=active_framework)
    _source, _empty, recovered = recover_accidental_empty_draft(
        db, school_group_id=1, program_id=program.id, empty_draft_id=empty_draft.id,
    )

    config = get_framework_configuration(db, school_group_id=1, program_id=program.id, framework_id=recovered.id)
    assert len(config["rubrics"]) == 9
    for rubric in config["rubrics"]:
        assert len(rubric["levels"]) == 2
    generic = [d for d in config["descriptors"] if d["descriptor_scope"] == "general"]
    grade_specific = [d for d in config["descriptors"] if d["descriptor_scope"] == "grade"]
    assert len(generic) == 18  # 9 competencies x 2 levels, generic descriptors
    assert len(grade_specific) == 18  # 9 competencies x 2 levels, Grade-specific descriptors
    grade_descriptor_rows = db.query(models.TalentGradeCompetencyRubricDescriptor).filter_by(framework_version_id=recovered.id).all()
    assert len(grade_descriptor_rows) == 18


def test_recovery_never_modifies_the_source_framework_or_its_historical_content(db):
    program, active_framework, members = foundation(db)
    before_revision = active_framework.revision
    before_fingerprint = active_framework.semantic_fingerprint
    before_member_count = db.query(models.FrameworkCompetency).filter_by(framework_version_id=active_framework.id).count()
    empty_draft = simulate_accidental_empty_draft(db, program=program, active_framework=active_framework)

    _source, _empty, recovered = recover_accidental_empty_draft(
        db, school_group_id=1, program_id=program.id, empty_draft_id=empty_draft.id,
    )

    db.refresh(active_framework)
    assert active_framework.status == "active"
    assert active_framework.revision == before_revision
    assert active_framework.semantic_fingerprint == before_fingerprint
    assert db.query(models.FrameworkCompetency).filter_by(framework_version_id=active_framework.id).count() == before_member_count

    # Editing the recovered Draft afterward must never touch the source.
    recovered_member = db.query(models.FrameworkCompetency).filter_by(framework_version_id=recovered.id).first()
    update_framework_competency(
        db, school_group_id=1, program_id=program.id, framework_id=recovered.id,
        competency_id=recovered_member.talent_competency_id, expected_revision=recovered.revision, label="Renamed after recovery",
    )
    source_labels_after = {m.label for m in db.query(models.FrameworkCompetency).filter_by(framework_version_id=active_framework.id).all()}
    assert "Renamed after recovery" not in source_labels_after
    assert len(members) == 9  # sanity: the original foundation still has all 9


def test_recovery_rejects_a_draft_that_already_has_competencies(db):
    program, active_framework, _members = foundation(db)
    lineage = create_competency(db, school_group_id=1, program_id=program.id, code="EXTRA", name="Extra")
    not_empty_draft = create_framework_draft(
        db, school_group_id=1, program_id=program.id, title="Not actually empty",
        supersedes_framework_version_id=active_framework.id,
    )
    add_framework_competency(
        db, school_group_id=1, program_id=program.id, framework_id=not_empty_draft.id,
        competency_id=lineage.id, expected_revision=not_empty_draft.revision,
    )
    with pytest.raises(TalentProgramError) as exc:
        recover_accidental_empty_draft(db, school_group_id=1, program_id=program.id, empty_draft_id=not_empty_draft.id)
    assert exc.value.code == "draft_not_empty"


def test_recovery_requires_an_explicit_source_when_supersedes_is_missing(db):
    program, active_framework, _members = foundation(db)
    empty_draft = create_framework_draft(
        db, school_group_id=1, program_id=program.id, title="Orphan empty draft",
    )
    with pytest.raises(TalentProgramError) as exc:
        recover_accidental_empty_draft(db, school_group_id=1, program_id=program.id, empty_draft_id=empty_draft.id)
    assert exc.value.code == "source_required"

    source, recovered_from_empty, recovered = recover_accidental_empty_draft(
        db, school_group_id=1, program_id=program.id, empty_draft_id=empty_draft.id,
        source_framework_id=active_framework.id,
    )
    assert source.id == active_framework.id
    assert recovered_from_empty.id == empty_draft.id
    assert db.query(models.FrameworkCompetency).filter_by(framework_version_id=recovered.id).count() == 9


def test_recovery_cannot_cross_tenant_or_program_boundaries(db):
    program1, active_framework1, _m1 = foundation(db, group=1, name="Program One")
    program2, _active_framework2, _m2 = foundation(db, group=2, name="Program Two")
    empty_draft = simulate_accidental_empty_draft(db, program=program1, active_framework=active_framework1)

    with pytest.raises(TalentProgramError) as exc:
        recover_accidental_empty_draft(db, school_group_id=2, program_id=program1.id, empty_draft_id=empty_draft.id)
    assert exc.value.code == "not_found"

    with pytest.raises(TalentProgramError) as exc2:
        recover_accidental_empty_draft(db, school_group_id=2, program_id=program2.id, empty_draft_id=empty_draft.id)
    assert exc2.value.code == "not_found"
