"""Current-Student authority for Talent & Potential population reads.

Owner data-integrity rule (Deployment Acceptance Batch 1): Talent & Potential
operates from the Students that CURRENTLY EXIST in TIS. A Talent row whose
Student no longer exists (an orphan or historical remnant) must never
contribute to current analytics: Student counts, participation, assessment
completion, Classification, Talented, distributions, denominators or trends.

Student deletion (``student_academic_service.force_delete_student_history``)
removes every Student-owned Talent row in the same transaction. This module is
the independent defensive half of that guarantee: every governed Talent
population query composes :func:`current_student_exists` so a stale row can
never inflate a figure even if one ever survives.

"Current" here means the Student row exists inside the SAME SchoolGroup as the
Talent row (tenant boundary). Student ``status`` (active/inactive) is not a
Talent population filter: ADR 0039 keeps eligibility independent of it.
"""

from __future__ import annotations

from sqlalchemy import and_, exists

import models


def current_student_exists(member_model=models.TalentAssessmentCyclePopulationMember):
    """Correlated EXISTS proving the row's Student still exists in its tenant."""
    return exists().where(and_(
        models.Student.id == member_model.student_id,
        models.Student.school_group_id == member_model.school_group_id,
    ))


def restrict_to_current_students(query, member_model=models.TalentAssessmentCyclePopulationMember):
    return query.filter(current_student_exists(member_model))
