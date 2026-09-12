import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from talent_program_service import (
    TalentProgramError, add_framework_competency, add_rubric_level, copy_grade_criteria,
    create_competency, create_framework_draft, create_program, get_framework_configuration,
    transition_program, upsert_descriptor, upsert_rubric,
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


def foundation(db, *, group=1, name="Performing Arts"):
    program = create_program(db, school_group_id=group, name=name)
    transition_program(db, school_group_id=group, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=group, program_id=program.id, title=f"{name} Framework")
    return program, framework


def add_grade_competency(db, *, program, framework, grade, code, name, description=None):
    lineage = create_competency(db, school_group_id=program.school_group_id, program_id=program.id, code=code, name=name, description=description)
    member, framework = add_framework_competency(
        db, school_group_id=program.school_group_id, program_id=program.id, framework_id=framework.id,
        competency_id=lineage.id, expected_revision=framework.revision, grade_level=grade,
    )
    return lineage, member, framework


def add_full_criteria(db, *, program, framework, grade, code, name, levels=(("L1", "Beginning"), ("L2", "Advanced"))):
    lineage, member, framework = add_grade_competency(db, program=program, framework=framework, grade=grade, code=code, name=name, description=f"{name} description")
    rubric, framework = upsert_rubric(db, school_group_id=program.school_group_id, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, framework_competency_id=member.id, name=f"{name} KPI", description="KPI description")
    level_rows = []
    for code_, label in levels:
        level, framework = add_rubric_level(db, school_group_id=program.school_group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, framework_competency_id=member.id, code=code_, label=label, description=f"{label} description")
        level_rows.append(level)
        _, framework = upsert_descriptor(db, school_group_id=program.school_group_id, program_id=program.id, framework_id=framework.id,
            framework_competency_id=member.id, rubric_level_id=level.id, expected_revision=framework.revision, descriptor=f"{label} descriptor")
        _, framework = upsert_descriptor(db, school_group_id=program.school_group_id, program_id=program.id, framework_id=framework.id,
            framework_competency_id=member.id, rubric_level_id=level.id, expected_revision=framework.revision,
            descriptor=f"{label} Grade-specific descriptor", grade_level=grade)
    return lineage, member, rubric, level_rows, framework


def test_full_structure_copies_independently_with_order_preserved(db):
    program, framework = foundation(db)
    _, member_a, rubric_a, levels_a, framework = add_full_criteria(db, program=program, framework=framework, grade="1", code="ONE", name="Mental Calculation")
    _, member_b, rubric_b, levels_b, framework = add_full_criteria(db, program=program, framework=framework, grade="1", code="TWO", name="Number Sense",
        levels=(("L1", "Beginning"),))
    framework = copy_grade_criteria(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        source_grade_level="1", target_grade_level="2", expected_revision=framework.revision)
    config = get_framework_configuration(db, school_group_id=1, program_id=program.id, framework_id=framework.id)
    members = db.query(models.FrameworkCompetency).filter_by(framework_version_id=framework.id).order_by(models.FrameworkCompetency.display_order).all()
    grade1 = [m for m in members if m.grade_level == "1"]
    grade2 = [m for m in members if m.grade_level == "2"]
    assert len(grade1) == 2 and len(grade2) == 2
    # Order preserved: Grade 2 members follow the same relative order as Grade 1.
    assert [m.label for m in grade1] == [m.label for m in grade2]
    assert grade2[0].label == "Mental Calculation" and grade2[1].label == "Number Sense"
    # Independent identities, not shared/linked rows.
    assert grade2[0].id != member_a.id and grade2[0].talent_competency_id != member_a.talent_competency_id
    assert grade2[1].id != member_b.id and grade2[1].talent_competency_id != member_b.talent_competency_id

    rubric_2a = db.query(models.TalentRubric).filter_by(framework_competency_id=grade2[0].id).one()
    assert rubric_2a.id != rubric_a.id and rubric_2a.name == rubric_a.name
    levels_2a = db.query(models.TalentRubricLevel).filter_by(rubric_id=rubric_2a.id).order_by(models.TalentRubricLevel.display_order).all()
    assert [l.code for l in levels_2a] == [l.code for l in levels_a]
    assert {l.id for l in levels_2a}.isdisjoint({l.id for l in levels_a})

    rubric_2b = db.query(models.TalentRubric).filter_by(framework_competency_id=grade2[1].id).one()
    levels_2b = db.query(models.TalentRubricLevel).filter_by(rubric_id=rubric_2b.id).all()
    assert len(levels_2b) == 1


def test_descriptors_including_grade_specific_copy_with_new_ids(db):
    program, framework = foundation(db)
    _, member, _, levels, framework = add_full_criteria(db, program=program, framework=framework, grade="1", code="ONE", name="Mental Calculation")
    framework = copy_grade_criteria(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        source_grade_level="1", target_grade_level="2", expected_revision=framework.revision)
    new_member = db.query(models.FrameworkCompetency).filter_by(framework_version_id=framework.id, grade_level="2").one()
    generic = db.query(models.TalentCompetencyRubricDescriptor).filter_by(framework_competency_id=new_member.id).all()
    grade_specific = db.query(models.TalentGradeCompetencyRubricDescriptor).filter_by(framework_competency_id=new_member.id).all()
    assert len(generic) == 2 and {d.descriptor for d in generic} == {"Beginning descriptor", "Advanced descriptor"}
    assert len(grade_specific) == 2
    # Grade-specific descriptors are remapped to the destination Grade, not left pointing at Grade 1.
    assert {d.grade_level for d in grade_specific} == {"2"}
    original_generic = db.query(models.TalentCompetencyRubricDescriptor).filter_by(framework_competency_id=member.id).all()
    assert {d.id for d in generic}.isdisjoint({d.id for d in original_generic})


def test_editing_copied_grade_does_not_alter_source_grade(db):
    program, framework = foundation(db)
    lineage, member, rubric, levels, framework = add_full_criteria(db, program=program, framework=framework, grade="1", code="ONE", name="Mental Calculation")
    framework = copy_grade_criteria(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        source_grade_level="1", target_grade_level="2", expected_revision=framework.revision)
    new_member = db.query(models.FrameworkCompetency).filter_by(framework_version_id=framework.id, grade_level="2").one()
    from talent_program_service import update_framework_competency, update_rubric_level
    _, framework = update_framework_competency(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        competency_id=new_member.talent_competency_id, expected_revision=framework.revision, label="Renamed for Grade 2")
    new_rubric = db.query(models.TalentRubric).filter_by(framework_competency_id=new_member.id).one()
    new_level = db.query(models.TalentRubricLevel).filter_by(rubric_id=new_rubric.id, code="L1").one()
    _, framework = update_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        level_id=new_level.id, expected_revision=framework.revision, label="Renamed Level for Grade 2")
    db.refresh(member); db.refresh(rubric)
    source_level = db.query(models.TalentRubricLevel).filter_by(id=levels[0].id).one()
    assert member.label == "Mental Calculation"
    assert rubric.name == "Mental Calculation KPI"
    assert source_level.label == "Beginning"


def test_same_grade_is_rejected(db):
    program, framework = foundation(db)
    _, _, _, _, framework = add_full_criteria(db, program=program, framework=framework, grade="1", code="ONE", name="Mental Calculation")
    with pytest.raises(TalentProgramError) as exc:
        copy_grade_criteria(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
            source_grade_level="1", target_grade_level="1", expected_revision=framework.revision)
    assert exc.value.code == "same_grade"


def test_empty_source_grade_is_rejected(db):
    program, framework = foundation(db)
    with pytest.raises(TalentProgramError) as exc:
        copy_grade_criteria(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
            source_grade_level="1", target_grade_level="2", expected_revision=framework.revision)
    assert exc.value.code == "source_grade_empty"


def test_already_populated_destination_is_never_silently_overwritten_or_merged(db):
    program, framework = foundation(db)
    _, _, _, _, framework = add_full_criteria(db, program=program, framework=framework, grade="1", code="ONE", name="Mental Calculation")
    _, _, _, _, framework = add_full_criteria(db, program=program, framework=framework, grade="2", code="TWO", name="Existing Grade 2 Competency")
    before_count = db.query(models.FrameworkCompetency).filter_by(framework_version_id=framework.id, grade_level="2").count()
    with pytest.raises(TalentProgramError) as exc:
        copy_grade_criteria(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
            source_grade_level="1", target_grade_level="2", expected_revision=framework.revision)
    assert exc.value.code == "target_grade_occupied"
    after_count = db.query(models.FrameworkCompetency).filter_by(framework_version_id=framework.id, grade_level="2").count()
    assert after_count == before_count == 1


def test_tenant_and_framework_boundary_cannot_be_crossed(db):
    program1, framework1 = foundation(db, group=1, name="Program One")
    program2, framework2 = foundation(db, group=2, name="Program Two")
    _, _, _, _, framework1 = add_full_criteria(db, program=program1, framework=framework1, grade="1", code="ONE", name="Mental Calculation")
    # A caller scoped to group 2 cannot reach group 1's Framework at all.
    with pytest.raises(TalentProgramError) as exc:
        copy_grade_criteria(db, school_group_id=2, program_id=program1.id, framework_id=framework1.id,
            source_grade_level="1", target_grade_level="2", expected_revision=framework1.revision)
    assert exc.value.code == "not_found"
    # Nor can group 2 reach it by guessing a different Program id under its own group id.
    with pytest.raises(TalentProgramError) as exc2:
        copy_grade_criteria(db, school_group_id=2, program_id=program2.id, framework_id=framework1.id,
            source_grade_level="1", target_grade_level="2", expected_revision=framework1.revision)
    assert exc2.value.code == "not_found"


def test_copied_items_retain_full_edit_delete_capability(db):
    """Copied records are ordinary rows produced through the same creation
    functions manual entry uses, so the existing update/remove functions
    (already regression-tested for the identical CRUD flow) apply to them
    unchanged - there is no separate read-only path for copied content."""
    program, framework = foundation(db)
    _, _, _, _, framework = add_full_criteria(db, program=program, framework=framework, grade="1", code="ONE", name="Mental Calculation")
    framework = copy_grade_criteria(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        source_grade_level="1", target_grade_level="2", expected_revision=framework.revision)
    new_member = db.query(models.FrameworkCompetency).filter_by(framework_version_id=framework.id, grade_level="2").one()
    from talent_program_service import remove_framework_competency
    framework = remove_framework_competency(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        competency_id=new_member.talent_competency_id, expected_revision=framework.revision)
    assert db.query(models.FrameworkCompetency).filter_by(id=new_member.id).one_or_none() is None
