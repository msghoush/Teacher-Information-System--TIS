"""Display-only enrichment for rows already authorized by operational routes.

This is not an authorization resolver. Call only after tenant and frozen Branch
scope filtering. Placement context always comes from frozen membership.
"""

import models


def authorized_contexts(db, school_group_id, rows):
    rows = list(rows)
    if not rows:
        return {}

    def lookup(model, ids):
        return {row.id: row for row in db.query(model).filter(
            model.school_group_id == school_group_id, model.id.in_(ids),
        ).all()} if ids else {}

    members = lookup(models.TalentAssessmentCyclePopulationMember,
                     {row.cycle_population_member_id for row in rows})
    students = lookup(models.Student, {row.student_id for row in rows})
    programs = lookup(models.TalentProgram, {row.program_id for row in rows})
    years = lookup(models.AcademicYear, {row.academic_year_id for row in rows})
    cycles = lookup(models.TalentAssessmentCycle, {row.cycle_id for row in rows})
    frameworks = lookup(models.TalentProgramFrameworkVersion, {row.framework_version_id for row in rows})
    branches = lookup(models.Branch, {row.branch_id for row in members.values()})
    result = {}
    for row in rows:
        student, program, year = students.get(row.student_id), programs.get(row.program_id), years.get(row.academic_year_id)
        cycle, framework = cycles.get(row.cycle_id), frameworks.get(row.framework_version_id)
        member = members.get(row.cycle_population_member_id)
        branch = branches.get(member.branch_id) if member else None
        result[row.id] = {
            "student_name": " ".join(filter(None, (student.first_name, student.father_name, student.last_name))) if student else None,
            "program_name": program.name if program else None,
            "academic_year_name": year.year_name if year else None,
            "cycle_title": cycle.title if cycle else None,
            "cycle_status": cycle.status if cycle else None,
            "framework_title": framework.title if framework else None,
            "framework_version_number": framework.version_number if framework else None,
            "branch_name": branch.name if branch else None,
            "grade_level": member.grade_level if member else None,
            "section_name": member.section_name if member else None,
        }
    return result


def authorized_payload(db, row, serializer):
    return {**serializer(row), "context": authorized_contexts(db, row.school_group_id, [row])[row.id]}
