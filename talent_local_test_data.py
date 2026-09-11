"""LOCAL-ONLY realistic Talent & Potential test dataset (Phase D preparation).

This module is pure ORM/service-layer orchestration: it never opens a database
connection, never reads DATABASE_URL, and never touches tis.db by itself. It is
only ever invoked against a session bound to an explicitly isolated local test
database by scripts/manage_local_talent_test_db.py, which owns every safety
check. Every record below is created through the real TIS service-layer
functions (student_academic_service, talent_program_service,
talent_evaluation_plan_service, talent_assessment_cycle_service,
talent_student_assessment_service, talent_review_candidate_service,
talent_official_identification_service, talent_educator_input_service) so the
seeded state is contract-valid end-to-end and the real deterministic Talent
analytics can compute results over it - no metric is manufactured here.
"""

from __future__ import annotations

from datetime import datetime

import models
import role_permission_service
from auth import ROLE_ADMINISTRATOR, get_password_hash
from student_academic_service import create_placement, create_student
from talent_assessment_cycle_service import close_cycle, create_cycle, open_cycle
from talent_educator_input_service import add_input
from talent_evaluation_plan_service import (
    activate_plan, add_period, cancel_period, create_plan, validate_cycle_period_link,
)
from talent_official_identification_service import record_decision
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, compute_framework_fingerprint,
    configure_kpi, configure_review_candidate_policy, create_competency, create_framework_draft,
    create_program, transition_program, upsert_annual_configuration, upsert_descriptor, upsert_rubric,
)
from talent_review_candidate_service import evaluate_review_candidate, mark_reviewed
from talent_student_assessment_service import (
    complete_assessment, mark_non_complete, set_competency_result, start_assessment,
)

LOCAL_TEST_USER_ID = "LTU0001"
LOCAL_TEST_USERNAME = "local_test_admin"
LOCAL_TEST_PASSWORD = "LocalTest!2026"
LOCAL_TEST_EMAIL = "local-test-admin@example.invalid"


def _build_program(db, admin, *, group_id, name, description, competencies, levels,
                    kpi=None, review_policy=None):
    """Build one fully-configured, activated Program + Framework using only real
    talent_program_service contracts. ``competencies`` is a list of
    (code, name, description) tuples; ``levels`` is a list of
    (code, label, description, numeric_value) tuples in lowest-proficiency-first
    order. ``kpi``, when given, is {"weights": [...], "scale_min", "scale_max",
    "interpretation"}. ``review_policy``, when given, is {"match_mode",
    "description", "top_level_code"}."""
    program = create_program(db, school_group_id=group_id, name=name, description=description, actor=admin)
    transition_program(db, school_group_id=group_id, program_id=program.id, target_status="active", actor=admin)
    framework = create_framework_draft(db, school_group_id=group_id, program_id=program.id,
                                        title=f"{name} Framework v1", summary=description, actor=admin)

    fw_competencies = []
    for code, comp_name, comp_desc in competencies:
        competency = create_competency(db, school_group_id=group_id, program_id=program.id,
                                        code=code, name=comp_name, description=comp_desc, actor=admin)
        fw_competency, framework = add_framework_competency(
            db, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            competency_id=competency.id, expected_revision=framework.revision, actor=admin)
        fw_competencies.append(fw_competency)

    _, framework = upsert_rubric(db, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                                  expected_revision=framework.revision, name=f"{name} Rubric",
                                  description="Ordered proficiency rubric (seed data).", actor=admin)

    fw_levels = []
    for code, label, level_desc, numeric_value in levels:
        level, framework = add_rubric_level(
            db, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, code=code, label=label, description=level_desc,
            numeric_value=numeric_value, actor=admin)
        fw_levels.append(level)

    for fw_competency in fw_competencies:
        for level in fw_levels:
            _, framework = upsert_descriptor(
                db, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                framework_competency_id=fw_competency.id, rubric_level_id=level.id,
                expected_revision=framework.revision,
                descriptor=f"{level.label} evidence for {fw_competency.label} (seed data).", actor=admin)

    if kpi is not None:
        components = [{"framework_competency_id": c.id, "weight_basis_points": w}
                      for c, w in zip(fw_competencies, kpi["weights"])]
        _, framework = configure_kpi(
            db, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, is_enabled=True, result_scale_min=kpi["scale_min"],
            result_scale_max=kpi["scale_max"], interpretation=kpi["interpretation"],
            components=components, actor=admin)

    if review_policy is not None:
        top_level = next(level for level in fw_levels if level.code == review_policy["top_level_code"])
        rules = [{"rule_type": "rubric_level_at_or_above", "framework_competency_id": fw_competencies[0].id,
                  "rubric_level_id": top_level.id}]
        _, framework = configure_review_candidate_policy(
            db, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, is_enabled=True, match_mode=review_policy["match_mode"],
            description=review_policy["description"], rules=rules, actor=admin)

    fingerprint = compute_framework_fingerprint(db, framework)
    framework = activate_framework(
        db, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, expected_fingerprint=fingerprint,
        organization_authorized=True, actor=admin)
    return program, framework, fw_competencies, fw_levels


def build_dataset(db):
    """Seed one realistic, internally-consistent Talent & Potential dataset.

    Raises RuntimeError if a SchoolGroup already exists (reset before reseeding).
    Returns a summary dict of created identifiers for assertions/reporting.
    """
    if db.query(models.SchoolGroup).first() is not None:
        raise RuntimeError("Local test dataset already exists. Reset before reseeding.")

    group = models.SchoolGroup(name="Local Test Academy Group")
    db.add(group)
    db.flush()

    branch_north = models.Branch(school_group_id=group.id, name="North Campus", status=True)
    branch_south = models.Branch(school_group_id=group.id, name="South Campus", status=True)
    db.add_all([branch_north, branch_south])
    db.flush()

    year = models.AcademicYear(school_group_id=group.id, year_name="2026-2027", is_active=True)
    db.add(year)
    db.flush()

    role_permission_service.seed_tenant_role_permissions(db, school_group_id=group.id)

    admin = models.User(
        user_id=LOCAL_TEST_USER_ID, username=LOCAL_TEST_USERNAME, email=LOCAL_TEST_EMAIL,
        email_normalized=LOCAL_TEST_EMAIL, first_name="Local", last_name="Test Admin",
        password=get_password_hash(LOCAL_TEST_PASSWORD), role=ROLE_ADMINISTRATOR, user_type="TENANT",
        access_scope="ORGANIZATION", school_group_id=group.id, branch_id=branch_north.id,
        academic_year_id=year.id, is_active=True, is_internal_test_identity=True,
    )
    db.add(admin)
    db.flush()

    student_specs = [
        ("ليان", "خليل", "female", "active", branch_north.id, "3", "A"),
        ("آدم", "ناصر", "male", "active", branch_north.id, "3", "A"),
        ("نور", "حسن", "female", "active", branch_north.id, "3", "B"),
        ("كريم", "منصور", "male", "active", branch_north.id, "4", "A"),
        ("تالا", "حداد", "female", "active", branch_north.id, "4", "A"),
        ("يوسف", "صالح", "male", "active", branch_south.id, "4", "B"),
        ("ريم", "عزيز", "female", "active", branch_south.id, "5", "A"),
        ("عمر", "نصار", "male", "active", branch_south.id, "5", "A"),
        ("سارة", "حمدان", "female", "active", branch_south.id, "5", "B"),
        ("جاد", "مراد", "male", "active", branch_south.id, "5", "B"),
    ]
    # Talent Program Grade configuration is bounded by operational Planning.
    # Keep the sanctioned local dataset on the same supported contract as the
    # browser instead of relying on direct-write seed privileges.
    db.add_all([
        models.PlanningSection(
            branch_id=branch_id,
            academic_year_id=year.id,
            grade_level=grade,
            section_name=section,
            class_status="Current",
        )
        for branch_id, grade, section in sorted({
            (branch_id, grade, section)
            for _, _, _, _, branch_id, grade, section in student_specs
        })
    ])
    db.flush()
    students = []
    for first, last, gender, status, branch_id, grade, section in student_specs:
        student = create_student(db, school_group_id=group.id, first_name=first, last_name=last,
                                  gender=gender, actor=admin)
        if status == "inactive":
            student.status = "inactive"
        create_placement(db, school_group_id=group.id, student_id=student.id, academic_year_id=year.id,
                          branch_id=branch_id, effective_from=datetime(2026, 9, 1),
                          grade_level=grade, section_name=section, actor=admin)
        students.append(student)
    db.flush()

    # Real historical (ended) placement for one Student, preceding their current
    # placement, so Learner Profile / Student Drill can show real placement history.
    create_placement(db, school_group_id=group.id, student_id=students[0].id, academic_year_id=year.id,
                      branch_id=branch_south.id, effective_from=datetime(2025, 9, 1),
                      effective_to=datetime(2026, 8, 31), grade_level="8", section_name="A",
                      reason="Prior-year historical placement (seed data).", actor=admin)

    grades = ["3", "4", "5"]

    # Program A: numeric/KPI-oriented ("STEM Excellence").
    program_a, framework_a, competencies_a, levels_a = _build_program(
        db, admin, group_id=group.id, name="STEM Excellence",
        description="Numeric KPI-oriented Program covering analytical and design competencies (seed data).",
        competencies=[
            ("MATH", "Mathematical Reasoning", "Applies mathematical reasoning to novel problems."),
            ("SCI", "Scientific Inquiry", "Designs and interprets scientific investigations."),
            ("ENG", "Engineering Design", "Iterates on constrained engineering design challenges."),
        ],
        levels=[
            ("D1", "Emerging", "Beginning to demonstrate the competency.", 1),
            ("D2", "Developing", "Demonstrates the competency with support.", 2),
            ("D3", "Proficient", "Demonstrates the competency independently.", 3),
            ("D4", "Advanced", "Demonstrates the competency with exceptional depth.", 4),
        ],
        kpi={"weights": [4000, 3000, 3000], "scale_min": 1, "scale_max": 4,
             "interpretation": "Weighted average maps directly onto the 1-4 KPI band."},
        review_policy={"match_mode": "any", "top_level_code": "D4",
                        "description": "Any Advanced-level competency triggers Review Candidate evaluation."},
    )
    upsert_annual_configuration(db, school_group_id=group.id, program_id=program_a.id,
                                 academic_year_id=year.id, is_enabled=True,
                                 eligible_grade_levels=grades, actor=admin)

    # Program B: rubric-only qualitative Program ("Visual Arts Talent"), no KPI, no policy.
    program_b, framework_b, competencies_b, levels_b = _build_program(
        db, admin, group_id=group.id, name="Visual Arts Talent",
        description="Rubric-only qualitative Program with no numeric KPI (seed data).",
        competencies=[
            ("COMP", "Composition", "Organizes visual elements into a coherent composition."),
            ("TECH", "Technique", "Applies medium-specific technique with control."),
            ("CREA", "Creativity", "Generates original, personally meaningful visual ideas."),
        ],
        levels=[
            ("V1", "Developing", "Foundational visual arts proficiency.", None),
            ("V2", "Accomplished", "Confident, consistent visual arts proficiency.", None),
            ("V3", "Exceptional", "Exceptional, portfolio-ready visual arts proficiency.", None),
        ],
    )
    upsert_annual_configuration(db, school_group_id=group.id, program_id=program_b.id,
                                 academic_year_id=year.id, is_enabled=True,
                                 eligible_grade_levels=grades, actor=admin)

    # Program C: Performing-Arts-style qualitative Program, configured but never opened.
    program_c, framework_c, competencies_c, levels_c = _build_program(
        db, admin, group_id=group.id, name="Performing Arts Talent",
        description="Performing-Arts-style qualitative Program (seed data).",
        competencies=[
            ("STAGE", "Stage Presence", "Commands attention and connects with an audience."),
            ("EXPR", "Expressive Range", "Conveys a wide emotional and expressive range."),
            ("ENSM", "Ensemble Collaboration", "Collaborates effectively within an ensemble."),
        ],
        levels=[
            ("P1", "Novice", "Beginning performing arts proficiency.", None),
            ("P2", "Emerging", "Emerging performing arts proficiency.", None),
            ("P3", "Skilled", "Skilled, reliable performing arts proficiency.", None),
            ("P4", "Masterful", "Masterful, audition-ready performing arts proficiency.", None),
        ],
        review_policy={"match_mode": "all", "top_level_code": "P4",
                        "description": "Masterful-level proficiency triggers Review Candidate evaluation."},
    )
    upsert_annual_configuration(db, school_group_id=group.id, program_id=program_c.id,
                                 academic_year_id=year.id, is_enabled=True,
                                 eligible_grade_levels=grades, actor=admin)

    # Annual Evaluation Plan A: 3 ordered Periods (required/cancelled/optional).
    config_a = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        program_id=program_a.id, academic_year_id=year.id).one()
    plan_a = create_plan(db, school_group_id=group.id, configuration_id=config_a.id, actor=admin)
    plan_a, period_a1 = add_period(db, school_group_id=group.id, plan_id=plan_a.id,
                                    expected_plan_revision=plan_a.revision, label="Fall Assessment Window",
                                    is_required=True, actor=admin)
    plan_a, period_a2 = add_period(db, school_group_id=group.id, plan_id=plan_a.id,
                                    expected_plan_revision=plan_a.revision, label="Spring Assessment Window",
                                    is_required=True, actor=admin)
    plan_a, period_a3 = add_period(db, school_group_id=group.id, plan_id=plan_a.id,
                                    expected_plan_revision=plan_a.revision, label="Optional Enrichment Check",
                                    is_required=False, actor=admin)
    plan_a = activate_plan(db, school_group_id=group.id, plan_id=plan_a.id,
                            expected_plan_revision=plan_a.revision, actor=admin)
    plan_a, period_a2 = cancel_period(db, school_group_id=group.id, period_id=period_a2.id,
                                       expected_plan_revision=plan_a.revision,
                                       cancellation_reason="Schedule conflict with exams (seed data).", actor=admin)

    # Annual Evaluation Plan B: 2 ordered Periods (required/optional).
    config_b = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        program_id=program_b.id, academic_year_id=year.id).one()
    plan_b = create_plan(db, school_group_id=group.id, configuration_id=config_b.id, actor=admin)
    plan_b, period_b1 = add_period(db, school_group_id=group.id, plan_id=plan_b.id,
                                    expected_plan_revision=plan_b.revision, label="Portfolio Review Window",
                                    is_required=True, actor=admin)
    plan_b, period_b2 = add_period(db, school_group_id=group.id, plan_id=plan_b.id,
                                    expected_plan_revision=plan_b.revision, label="Optional Studio Check-In",
                                    is_required=False, actor=admin)
    plan_b = activate_plan(db, school_group_id=group.id, plan_id=plan_b.id,
                            expected_plan_revision=plan_b.revision, actor=admin)

    # Annual Evaluation Plan C: 1 required Period, activated but never executed.
    config_c = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        program_id=program_c.id, academic_year_id=year.id).one()
    plan_c = create_plan(db, school_group_id=group.id, configuration_id=config_c.id, actor=admin)
    plan_c, period_c1 = add_period(db, school_group_id=group.id, plan_id=plan_c.id,
                                    expected_plan_revision=plan_c.revision, label="Audition Window",
                                    is_required=True, actor=admin)
    plan_c = activate_plan(db, school_group_id=group.id, plan_id=plan_c.id,
                            expected_plan_revision=plan_c.revision, actor=admin)

    # Cycle A: opened, executed, then closed (historical, completed Program).
    cycle_a = create_cycle(db, school_group_id=group.id, program_id=program_a.id,
                            academic_year_id=year.id, framework_version_id=framework_a.id,
                            title="STEM Excellence - Fall Cycle", population_effective_at=datetime(2026, 9, 15),
                            actor=admin)
    plan_a, period_a1, cycle_a = validate_cycle_period_link(
        db, school_group_id=group.id, cycle_id=cycle_a.id, period_id=period_a1.id,
        expected_plan_revision=plan_a.revision, expected_cycle_revision=cycle_a.revision, actor=admin)
    cycle_a = open_cycle(db, school_group_id=group.id, cycle_id=cycle_a.id,
                          expected_revision=cycle_a.revision, organization_authorized=True, actor=admin)

    # Cycle B: opened, partially executed, left open (in-progress Program).
    cycle_b = create_cycle(db, school_group_id=group.id, program_id=program_b.id,
                            academic_year_id=year.id, framework_version_id=framework_b.id,
                            title="Visual Arts Talent - Portfolio Cycle", population_effective_at=datetime(2026, 9, 15),
                            actor=admin)
    plan_b, period_b1, cycle_b = validate_cycle_period_link(
        db, school_group_id=group.id, cycle_id=cycle_b.id, period_id=period_b1.id,
        expected_plan_revision=plan_b.revision, expected_cycle_revision=cycle_b.revision, actor=admin)
    cycle_b = open_cycle(db, school_group_id=group.id, cycle_id=cycle_b.id,
                          expected_revision=cycle_b.revision, organization_authorized=True, actor=admin)

    # Cycle C: created and linked, left Draft (Program configured, never executed).
    cycle_c = create_cycle(db, school_group_id=group.id, program_id=program_c.id,
                            academic_year_id=year.id, framework_version_id=framework_c.id,
                            title="Performing Arts Talent - Audition Cycle",
                            population_effective_at=datetime(2026, 9, 15), actor=admin)
    plan_c, period_c1, cycle_c = validate_cycle_period_link(
        db, school_group_id=group.id, cycle_id=cycle_c.id, period_id=period_c1.id,
        expected_plan_revision=plan_c.revision, expected_cycle_revision=cycle_c.revision, actor=admin)

    members_a = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle_a.id).order_by(
        models.TalentAssessmentCyclePopulationMember.student_id).all()
    members_b = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle_b.id).order_by(
        models.TalentAssessmentCyclePopulationMember.student_id).all()

    # Cycle A assessments: all 10 completed so Release 1 aggregate analytics
    # are visibly above the minimum cohort. Five D3 and five D4 outcomes keep
    # the rubric distribution itself visible rather than splitting into tiny buckets.
    level_pattern_a = ["D3", "D4"]
    levels_by_code_a = {level.code: level for level in levels_a}
    reviewed_candidate_ids = []
    for index, member in enumerate(members_a):
        assessment = start_assessment(db, school_group_id=group.id, cycle_id=cycle_a.id,
                                       cycle_population_member_id=member.id, actor=admin)
        level_code = level_pattern_a[index % len(level_pattern_a)]
        for competency in competencies_a:
            _, assessment = set_competency_result(
                db, school_group_id=group.id, assessment_id=assessment.id,
                framework_competency_id=competency.id, rubric_level_id=levels_by_code_a[level_code].id,
                expected_revision=assessment.revision,
                evidence=f"Observed {level_code} performance on {competency.label} (seed data).", actor=admin)
        assessment = complete_assessment(db, school_group_id=group.id, assessment_id=assessment.id,
                                          expected_revision=assessment.revision, actor=admin)
        candidate, outcome = evaluate_review_candidate(db, school_group_id=group.id, assessment_id=assessment.id, actor=admin)
        if candidate is not None:
            reviewed_candidate_ids.append(candidate.id)

    # Mark the first qualifying Review Candidate Reviewed, then Officially Identified;
    # leave a second Reviewed Candidate without a decision (non-identified candidate).
    identification = None
    if reviewed_candidate_ids:
        first = mark_reviewed(db, school_group_id=group.id, candidate_id=reviewed_candidate_ids[0], actor=admin)
        identification = record_decision(db, school_group_id=group.id, review_candidate_id=first.id,
                                          decision="identified", rationale="Consistent Advanced-level evidence (seed data).",
                                          organization_authorized=True, actor=admin)
    if len(reviewed_candidate_ids) > 1:
        mark_reviewed(db, school_group_id=group.id, candidate_id=reviewed_candidate_ids[1], actor=admin)

    cycle_a = close_cycle(db, school_group_id=group.id, cycle_id=cycle_a.id,
                           expected_revision=cycle_a.revision, organization_authorized=True, actor=admin)

    # Cycle B assessments: 7 completed, 2 in-progress, 1 not started.
    # This gives the analytics UI a clearly visible completed cohort while also
    # preserving started-vs-completed contrast for operational cards.
    levels_by_code_b = {level.code: level for level in levels_b}
    level_pattern_b = ["V2", "V3"]
    for index, member in enumerate(members_b[:9]):
        assessment = start_assessment(db, school_group_id=group.id, cycle_id=cycle_b.id,
                                       cycle_population_member_id=member.id, actor=admin)
        if index >= 7:
            _, assessment = set_competency_result(
                db, school_group_id=group.id, assessment_id=assessment.id,
                framework_competency_id=competencies_b[0].id, rubric_level_id=levels_by_code_b["V1"].id,
                expected_revision=assessment.revision, evidence="Assessment still in progress (seed data).", actor=admin)
            continue
        level_code = level_pattern_b[index % len(level_pattern_b)]
        for competency in competencies_b:
            _, assessment = set_competency_result(
                db, school_group_id=group.id, assessment_id=assessment.id,
                framework_competency_id=competency.id, rubric_level_id=levels_by_code_b[level_code].id,
                expected_revision=assessment.revision,
                evidence=f"Observed {level_code} performance on {competency.label} (seed data).", actor=admin)
        complete_assessment(db, school_group_id=group.id, assessment_id=assessment.id,
                             expected_revision=assessment.revision, actor=admin)

    # Educator Input under Program A for two Students.
    add_input(db, school_group_id=group.id, student_id=students[0].id, program_id=program_a.id,
              academic_year_id=year.id, observed_at=datetime(2026, 10, 1), category="observation",
              content="Demonstrated strong analytical reasoning during a group STEM challenge (seed data).",
              actor=admin)
    add_input(db, school_group_id=group.id, student_id=students[1].id, program_id=program_a.id,
              academic_year_id=year.id, observed_at=datetime(2026, 10, 3), category="context",
              content="Recently transferred from another school's accelerated STEM track (seed data).",
              actor=admin)

    db.commit()
    return {
        "school_group_id": group.id,
        "branch_ids": [branch_north.id, branch_south.id],
        "academic_year_id": year.id,
        "student_ids": [student.id for student in students],
        "program_ids": [program_a.id, program_b.id, program_c.id],
        "cycle_ids": [cycle_a.id, cycle_b.id, cycle_c.id],
        "identification_id": identification.id if identification is not None else None,
        "local_test_user_id": LOCAL_TEST_USER_ID,
        "local_test_username": LOCAL_TEST_USERNAME,
        "local_test_password": LOCAL_TEST_PASSWORD,
    }
