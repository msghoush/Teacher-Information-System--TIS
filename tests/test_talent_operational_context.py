from datetime import datetime

from student_academic_service import transition_placement
from talent_operational_context import authorized_contexts
from talent_program_service import _m3_semantic_payload, get_framework_configuration
from talent_student_assessment_service import start_assessment
from test_talent_student_assessment_competency_results import db, foundation


def test_context_uses_frozen_membership_and_tenant_bound_labels(db):
    _, session = db
    program, framework, cycle, member, student, placement, _, _ = foundation(session)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id,
                                  cycle_population_member_id=member.id)
    transition_placement(session, school_group_id=1, student_id=student.id, placement_id=placement.id,
                         transition_at=datetime(2026, 12, 1), academic_year_id=100, branch_id=11,
                         planning_section_id=1001)
    session.flush()
    context = authorized_contexts(session, 1, [assessment])[assessment.id]
    assert context == {
        "student_name": "Student One", "program_name": program.name,
        "academic_year_name": "2026-2027", "cycle_title": "Cycle",
        "cycle_status": "open", "framework_title": "Framework",
        "framework_version_number": framework.version_number,
        "branch_name": "One A", "grade_level": "1", "section_name": "A",
    }
    assert authorized_contexts(session, 1, []) == {}
    wrong_tenant = authorized_contexts(session, 2, [assessment])[assessment.id]
    assert all(value is None for value in wrong_tenant.values())


def test_public_write_ids_stay_outside_framework_semantic_projection(db):
    _, session = db
    program, framework, _, _, _, _, _, _ = foundation(session)
    semantic = _m3_semantic_payload(session, framework.id)
    public = get_framework_configuration(
        session, school_group_id=1, program_id=program.id, framework_id=framework.id,
    )
    assert semantic["levels"] and "id" not in semantic["levels"][0]
    assert semantic["descriptors"] and "id" not in semantic["descriptors"][0]
    assert all(item["id"] for item in public["levels"])
    assert all(item["id"] for item in public["descriptors"])
