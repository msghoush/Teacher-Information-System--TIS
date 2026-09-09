"""M7 read-only longitudinal Learner Profile over canonical historical records."""

from __future__ import annotations

from collections import defaultdict

import models
from student_academic_service import placement_payload
from talent_educator_input_service import input_payload
from talent_official_identification_service import identification_payload
from talent_review_candidate_service import candidate_payload
from talent_student_assessment_service import assessment_payload, competency_result_payload


class TalentLearnerProfileError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _student_payload(row):
    return {
        "id": row.id, "school_group_id": row.school_group_id, "first_name": row.first_name,
        "father_name": row.father_name, "last_name": row.last_name, "gender": row.gender,
        "status": row.status,
    }


def _branch_filter(rows, visible_branch_ids, branch_getter):
    return rows if visible_branch_ids is None else [row for row in rows if branch_getter(row) in visible_branch_ids]


def _event(event_type, occurred_at, stable_id, **context):
    return {"event_type": event_type, "occurred_at": occurred_at.isoformat() if occurred_at else None,
            "id": stable_id, **context}


def build_learner_profile(db, *, school_group_id, student_id, visible_branch_ids=None,
                          include_competencies=True, include_timeline=True,
                          include_review_candidates=True, include_identifications=True,
                          include_educator_inputs=False):
    student = db.query(models.Student).filter_by(id=student_id, school_group_id=school_group_id).one_or_none()
    if student is None:
        raise TalentLearnerProfileError("not_found", "Student was not found.")
    placements = _branch_filter(
        db.query(models.StudentAcademicPlacement).filter_by(school_group_id=school_group_id, student_id=student.id)
        .order_by(models.StudentAcademicPlacement.effective_from, models.StudentAcademicPlacement.id).all(),
        visible_branch_ids, lambda row: row.branch_id,
    )
    members = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        school_group_id=school_group_id, student_id=student.id,
    ).all()
    members_by_id = {row.id: row for row in members}
    assessments = _branch_filter(
        db.query(models.TalentStudentAssessment).filter_by(school_group_id=school_group_id, student_id=student.id)
        .order_by(models.TalentStudentAssessment.id).all(), visible_branch_ids,
        lambda row: members_by_id.get(row.cycle_population_member_id).branch_id if row.cycle_population_member_id in members_by_id else None,
    )
    assessment_ids = [row.id for row in assessments]
    candidates = []
    if include_review_candidates or include_identifications:
        candidates = db.query(models.TalentReviewCandidate).filter(
            models.TalentReviewCandidate.school_group_id == school_group_id,
            models.TalentReviewCandidate.assessment_id.in_(assessment_ids or [-1]),
        ).all()
    candidate_by_assessment = {row.assessment_id: row for row in candidates}
    identifications = []
    if include_identifications:
        identifications = db.query(models.TalentOfficialIdentification).filter(
            models.TalentOfficialIdentification.school_group_id == school_group_id,
            models.TalentOfficialIdentification.review_candidate_id.in_([row.id for row in candidates] or [-1]),
        ).all()
    identification_by_candidate = {row.review_candidate_id: row for row in identifications}
    results_by_assessment = defaultdict(list)
    if include_competencies:
        results = db.query(models.TalentStudentCompetencyResult).filter(
            models.TalentStudentCompetencyResult.school_group_id == school_group_id,
            models.TalentStudentCompetencyResult.assessment_id.in_(assessment_ids or [-1]),
        ).order_by(models.TalentStudentCompetencyResult.assessment_id, models.TalentStudentCompetencyResult.framework_competency_id).all()
        for row in results:
            results_by_assessment[row.assessment_id].append(competency_result_payload(row))
    program_ids = {row.program_id for row in assessments}
    programs = {row.id: row for row in db.query(models.TalentProgram).filter(
        models.TalentProgram.school_group_id == school_group_id, models.TalentProgram.id.in_(program_ids or [-1]),
    ).all()}
    cycles = {row.id: row for row in db.query(models.TalentAssessmentCycle).filter(
        models.TalentAssessmentCycle.school_group_id == school_group_id,
        models.TalentAssessmentCycle.id.in_([row.cycle_id for row in assessments] or [-1]),
    ).all()}
    frameworks = {row.id: row for row in db.query(models.TalentProgramFrameworkVersion).filter(
        models.TalentProgramFrameworkVersion.school_group_id == school_group_id,
        models.TalentProgramFrameworkVersion.id.in_([row.framework_version_id for row in assessments] or [-1]),
    ).all()}
    years = {row.id: row for row in db.query(models.AcademicYear).filter(
        models.AcademicYear.school_group_id == school_group_id,
        models.AcademicYear.id.in_({row.academic_year_id for row in assessments} or {-1}),
    ).all()}

    educator_inputs = []
    if include_educator_inputs:
        educator_inputs = _branch_filter(
            db.query(models.TalentEducatorInput).filter_by(school_group_id=school_group_id, student_id=student.id)
            .filter(~models.TalentEducatorInput.id.in_(db.query(models.TalentEducatorInput.supersedes_educator_input_id).filter(
                models.TalentEducatorInput.school_group_id == school_group_id,
                models.TalentEducatorInput.supersedes_educator_input_id.isnot(None),
            ))).order_by(models.TalentEducatorInput.observed_at, models.TalentEducatorInput.id).all(),
            visible_branch_ids, lambda row: row.branch_id,
        )

    # A Branch profile exists only where at least one independently authorized historical record is visible.
    if visible_branch_ids is not None and not (placements or assessments or educator_inputs):
        raise TalentLearnerProfileError("not_found", "Student was not found.")

    grouped = defaultdict(lambda: {"program": None, "academic_years": defaultdict(lambda: {"academic_year": None, "cycles": []})})
    for assessment in assessments:
        program = programs.get(assessment.program_id)
        cycle = cycles.get(assessment.cycle_id)
        framework = frameworks.get(assessment.framework_version_id)
        year = years.get(assessment.academic_year_id)
        member = members_by_id.get(assessment.cycle_population_member_id)
        group = grouped[assessment.program_id]
        group["program"] = {"id": assessment.program_id, "name": program.name if program else None}
        year_group = group["academic_years"][assessment.academic_year_id]
        year_group["academic_year"] = {"id": assessment.academic_year_id, "year_name": year.year_name if year else None}
        item = {
            "cycle": {"id": assessment.cycle_id, "title": cycle.title if cycle else None, "status": cycle.status if cycle else None,
                      "population_effective_at": cycle.population_effective_at.isoformat() if cycle and cycle.population_effective_at else None},
            "frozen_context": None if member is None else {"branch_id": member.branch_id, "grade_level": member.grade_level,
                                                             "section_name": member.section_name, "academic_placement_id": member.academic_placement_id},
            "framework_version": {"id": assessment.framework_version_id, "version_number": framework.version_number if framework else None,
                                  "title": framework.title if framework else None},
            "assessment": assessment_payload(assessment),
        }
        if include_review_candidates:
            item["review_candidate"] = candidate_payload(candidate_by_assessment[assessment.id]) if assessment.id in candidate_by_assessment else None
        if include_identifications:
            candidate = candidate_by_assessment.get(assessment.id)
            item["official_identification"] = identification_payload(identification_by_candidate[candidate.id]) if candidate and candidate.id in identification_by_candidate else None
        if include_competencies:
            item["competency_results"] = results_by_assessment[assessment.id]
        year_group["cycles"].append(item)
    programs_payload = []
    for program_id, group in sorted(grouped.items(), key=lambda item: (item[1]["program"]["name"] or "", item[0])):
        years_payload = []
        for year_id, year_group in sorted(group["academic_years"].items(), key=lambda item: item[0]):
            year_group["cycles"].sort(key=lambda item: (item["cycle"]["population_effective_at"] or "", item["cycle"]["id"]))
            years_payload.append({"academic_year": year_group["academic_year"], "cycles": year_group["cycles"]})
        programs_payload.append({"program": group["program"], "academic_years": years_payload})

    profile = {"student": _student_payload(student), "placements": [placement_payload(row) for row in placements],
               "programs": programs_payload}
    if include_educator_inputs:
        profile["educator_inputs"] = [input_payload(row) for row in educator_inputs]
    if include_timeline:
        timeline = []
        for row in placements:
            timeline.append(_event("placement_started", row.effective_from, row.id, branch_id=row.branch_id, academic_year_id=row.academic_year_id))
            if row.effective_to:
                timeline.append(_event("placement_ended", row.effective_to, row.id, branch_id=row.branch_id, academic_year_id=row.academic_year_id))
        for row in assessments:
            if row.status != "in_progress":
                timeline.append(_event(f"assessment_{row.status}", row.completed_at or row.updated_at, row.id, program_id=row.program_id, cycle_id=row.cycle_id))
        if include_review_candidates:
            for row in candidates:
                timeline.append(_event("review_candidate_created", row.evaluated_at, row.id, program_id=row.program_id, cycle_id=row.cycle_id))
                if row.reviewed_at:
                    timeline.append(_event("review_candidate_reviewed", row.reviewed_at, row.id, program_id=row.program_id, cycle_id=row.cycle_id))
        if include_identifications:
            for row in identifications:
                timeline.append(_event("official_identification_recorded", row.decided_at, row.id, program_id=row.program_id, cycle_id=row.cycle_id, decision=row.decision))
        if include_educator_inputs:
            for row in educator_inputs:
                timeline.append(_event("educator_input_amended" if row.supersedes_educator_input_id else "educator_input_added", row.created_at, row.id, program_id=row.program_id, branch_id=row.branch_id))
        profile["timeline"] = sorted(timeline, key=lambda item: (item["occurred_at"] or "", item["event_type"], item["id"]))
    return profile