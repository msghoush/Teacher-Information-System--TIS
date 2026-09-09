"""M10 B9 privacy-closed identifiable Student Drill.

Read-only. Enumerates only Students with authoritative frozen Talent
evidence (`TalentAssessmentCyclePopulationMember`) inside the requested
authorized tenant/Academic-Year/historical-Branch/Program context - never
current `StudentAcademicPlacement`, never every Student in current
enrollment or the SchoolGroup. Every identifiable Student row is P7
regardless of narrow scope or a Candidate/Identification field's own
secondary permission (P5/P6). This module builds only ONE gate-level P7
Cell (mirroring M9's `analytics_students` eligibility-gate pattern) through
the same B2 closure machinery every other M10 route uses
(`talent_analytics_relationship_graph`/`talent_analytics_privacy_closure`
via `talent_org_intelligence_service.PrivacyClosedProjectionSet`) - there is
no per-Student additive relationship graph (B9 has no authoritative
cross-Student equation), and no ranking/Talent Score/AI field anywhere.

The strict closed wrapper (`StudentDrillClosedProjection`) is the only
accepted serialization input, mirroring B8's
`ParticipationOverlapClosedProjection`/`serialize_projection` discipline: it
rejects raw SQL rows, raw ORM objects, and any object that is not the
correct closed-wrapper type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import models
from talent_analytics_privacy import Cell, VISIBLE
from talent_analytics_privacy_closure import apply_primary_privacy_and_close
from talent_analytics_relationship_graph import PrivacyRelationshipGraph
from sqlalchemy import func

from talent_org_intelligence_contract import (
    STUDENT_DRILL_POPULATION_PRIVACY_CLASS, CellIdentity, MeasureComponent,
    MembershipGrain, MetricCode,
)
from talent_org_intelligence_service import PrivacyClosedProjectionSet


STUDENT_DRILL_PRIVACY_CLASS = STUDENT_DRILL_POPULATION_PRIVACY_CLASS


def gate_identity(context) -> CellIdentity:
    """Canonical B9 eligibility-gate Cell identity.

    Uses the governed distinct-Student P7 gate metric. It deliberately does
    not reuse the frozen-membership identity because the values have different
    grains.
    """

    return CellIdentity(
        school_group_id=context.school_group_id,
        academic_year_id=context.academic_year_id,
        metric=MetricCode.STUDENT_DRILL_POPULATION,
        measure_component=MeasureComponent.COUNT,
        membership_grain=MembershipGrain.DISTINCT_STUDENT,
    )


def build_gate_closure(*, context, eligible_count: Optional[int], policy):
    """Run the B9 gate Cell through the canonical B2 pipeline.

    A single Cell with no relationships still passes through the identical
    `apply_primary_privacy_and_close` order every other M10 route uses -
    primary privacy is applied first, then (trivial, since there is no
    additive equation to solve) graph closure.
    """

    identity = gate_identity(context)
    cell = Cell(
        key=identity.canonical_key(),
        privacy_class=STUDENT_DRILL_PRIVACY_CLASS,
        raw_value=(int(eligible_count) if eligible_count else None),
        context={"metric": MetricCode.STUDENT_DRILL_POPULATION.value},
    )
    cells = {identity: cell}
    graph = PrivacyRelationshipGraph.from_contract(
        school_group_id=context.school_group_id, cells=cells, relationships=(),
    )
    closed = PrivacyClosedProjectionSet(apply_primary_privacy_and_close(graph, cells, policy))
    return closed, identity


def gate_visible(closed: PrivacyClosedProjectionSet, identity: CellIdentity) -> bool:
    return closed.projection(identity).state == VISIBLE


@dataclass(frozen=True)
class StudentDrillContext:
    program_id: int
    cycle_id: int
    branch_id: int
    grade_level: str
    section_name: str
    assessment_state: str
    kpi_result: Optional[int] = None
    has_kpi_result: bool = False
    candidate_state: Optional[str] = None
    has_candidate_field: bool = False
    identification_state: Optional[str] = None
    has_identification_field: bool = False

    def to_payload(self) -> dict:
        payload = {
            "program_id": self.program_id, "cycle_id": self.cycle_id,
            "branch_id": self.branch_id, "grade_level": self.grade_level,
            "section_name": self.section_name,
            "assessment_state": self.assessment_state,
        }
        if self.has_kpi_result:
            payload["kpi_result"] = self.kpi_result
        if self.has_candidate_field:
            payload["candidate_state"] = self.candidate_state
        if self.has_identification_field:
            payload["identification_state"] = self.identification_state
        return payload


@dataclass(frozen=True)
class StudentDrillRow:
    """One minimized distinct Student with frozen evidence contexts.

    Only frozen historical context (never current Placement) and the
    minimum approved identity fields, matching M9's `analytics_students`
    field set exactly. Optional fields use an explicit `has_*` presence flag
    so an unpermitted Candidate/Identification/Learner-Profile field is
    genuinely ABSENT from the serialized payload, never `null`/`false`.
    """

    student_id: int
    display_name: str
    contexts: tuple[StudentDrillContext, ...]
    can_view_learner_profile: Optional[bool] = None
    has_learner_profile_field: bool = False

    def to_payload(self) -> dict:
        payload = {
            "student_id": self.student_id,
            "display_name": self.display_name,
            "contexts": [context.to_payload() for context in self.contexts],
        }
        if self.has_learner_profile_field:
            payload["can_view_learner_profile"] = bool(self.can_view_learner_profile)
        return payload


@dataclass(frozen=True)
class StudentDrillClosedProjection:
    """The only accepted B9 serialization input.

    Construction itself is the closure boundary: it raises ``TypeError`` for
    anything but a real B2 `PrivacyClosedProjectionSet` and real
    `StudentDrillRow` instances, so a raw SQL row/ORM object/Candidate row
    can never reach the serializer even if a caller tried to smuggle one in.
    """

    closed: PrivacyClosedProjectionSet
    gate_identity: CellIdentity
    rows: tuple
    has_more: bool

    def __post_init__(self):
        if not isinstance(self.closed, PrivacyClosedProjectionSet):
            raise TypeError("a B2 PrivacyClosedProjectionSet is required")
        if not isinstance(self.gate_identity, CellIdentity):
            raise TypeError("a canonical CellIdentity gate is required")
        if not all(
            isinstance(row, StudentDrillRow)
            and all(isinstance(context, StudentDrillContext) for context in row.contexts)
            for row in self.rows
        ):
            raise TypeError("only closed StudentDrillRow projections may serialize")


def _display_name(student) -> str:
    parts = [student.first_name, student.father_name, student.last_name]
    return " ".join(part for part in parts if part)


def count_distinct_students(population_query) -> int:
    """Count the authorized filtered Student grain without identity loading."""

    return int(population_query.with_entities(
        func.count(func.distinct(models.TalentAssessmentCyclePopulationMember.student_id))
    ).scalar() or 0)


def fetch_student_rows(
    db, population_query, *, limit: int, offset: int,
    has_candidate: bool, has_identification: bool, has_learner_profile: bool,
) -> tuple[tuple[StudentDrillRow, ...], bool]:
    """Set-based, page-bounded identifiable Student fetch.

    Only the already-authorized frozen membership subquery (historical
    Branch/Program/tenant/AY scope already applied in SQL) drives the outer
    join; Candidate/Identification are fetched with exactly one additional
    query EACH, bounded to the returned page's assessment/candidate ids -
    never per-Student, never for an un-permitted resource.
    """

    authorized_student_ids = population_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.student_id.label("student_id")
    ).distinct().subquery()
    students = db.query(models.Student).join(
        authorized_student_ids, authorized_student_ids.c.student_id == models.Student.id,
    ).order_by(
        models.Student.first_name, models.Student.father_name,
        models.Student.last_name, models.Student.id,
    ).offset(offset).limit(limit + 1).all()
    has_more = len(students) > limit
    students = students[:limit]
    page_student_ids = [student.id for student in students]
    if not page_student_ids:
        return (), has_more

    context_rows = db.query(
        models.TalentAssessmentCyclePopulationMember, models.TalentStudentAssessment,
    ).select_from(models.TalentAssessmentCyclePopulationMember).outerjoin(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == models.TalentAssessmentCyclePopulationMember.id,
    ).filter(
        models.TalentAssessmentCyclePopulationMember.id.in_(
            population_query.with_entities(models.TalentAssessmentCyclePopulationMember.id)
        ),
        models.TalentAssessmentCyclePopulationMember.student_id.in_(page_student_ids),
    ).order_by(
        models.TalentAssessmentCyclePopulationMember.student_id,
        models.TalentAssessmentCyclePopulationMember.program_id,
        models.TalentAssessmentCyclePopulationMember.cycle_id,
        models.TalentAssessmentCyclePopulationMember.id,
    ).all()

    member_ids = [member.id for member, _ in context_rows]
    candidates_by_member = {}
    if has_candidate and member_ids:
        candidates_by_member = {
            row.cycle_population_member_id: row
            for row in db.query(models.TalentReviewCandidate).filter(
                models.TalentReviewCandidate.cycle_population_member_id.in_(member_ids)
            ).all()
        }
    identifications_by_member = {}
    if has_identification and member_ids:
        identifications_by_member = {
            row.cycle_population_member_id: row
            for row in db.query(models.TalentOfficialIdentification).filter(
                models.TalentOfficialIdentification.cycle_population_member_id.in_(member_ids)
            ).all()
        }

    contexts_by_student = {student.id: [] for student in students}
    seen_contexts = {student.id: set() for student in students}
    for member, assessment in context_rows:
        kpi_present = assessment is not None and assessment.status == "completed" and assessment.kpi_result is not None
        candidate = candidates_by_member.get(member.id) if has_candidate else None
        identification = identifications_by_member.get(member.id) if has_identification else None
        context = StudentDrillContext(
            program_id=member.program_id, cycle_id=member.cycle_id,
            branch_id=member.branch_id, grade_level=member.grade_level,
            section_name=member.section_name,
            assessment_state=assessment.status if assessment is not None else "unassessed",
            kpi_result=assessment.kpi_result if kpi_present else None,
            has_kpi_result=kpi_present,
            candidate_state=candidate.status if candidate is not None else None,
            has_candidate_field=has_candidate,
            identification_state=identification.decision if identification is not None else None,
            has_identification_field=has_identification,
        )
        key = tuple(sorted(context.to_payload().items()))
        if key not in seen_contexts[member.student_id]:
            seen_contexts[member.student_id].add(key)
            contexts_by_student[member.student_id].append(context)

    built = []
    for student in students:
        built.append(StudentDrillRow(
            student_id=student.id,
            display_name=_display_name(student),
            contexts=tuple(contexts_by_student[student.id]),
            can_view_learner_profile=(True if has_learner_profile else None), has_learner_profile_field=has_learner_profile,
        ))
    return tuple(built), has_more


def serialize_projection(result: StudentDrillClosedProjection, *, context_payload: dict) -> dict:
    """Serialize only a closed, gate-visible B9 projection.

    Raises ``TypeError`` for anything but the correct closed-wrapper type or
    a non-visible gate - the router must never reach this function unless
    the gate has already been confirmed visible, but the check is repeated
    here defensively so no future caller can bypass it.
    """

    if not isinstance(result, StudentDrillClosedProjection):
        raise TypeError("a B9 privacy-closed Student Drill projection is required")
    if not gate_visible(result.closed, result.gate_identity):
        raise TypeError("Student Drill projection must be gate-visible before serialization")
    return {
        **context_payload,
        "items": [row.to_payload() for row in result.rows],
    }
