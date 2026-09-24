"""Shared test helper: make the Talent fixtures' Students real Students.

Batch 1 data-integrity rule: current Talent analytics only count Students that
currently exist. Older fixtures referenced bare integer Student ids; this helper
adds a minimal real ``Student`` row for every id the Talent tables reference.
"""

import models


def ensure_talent_students(session):
    """Add a Student for each (school_group_id, student_id) referenced by Talent rows."""
    wanted = set()
    for model in (
        models.TalentAssessmentCyclePopulationMember, models.TalentStudentAssessment,
        models.TalentStudentCompetencyResult, models.TalentReviewCandidate,
        models.TalentOfficialIdentification, models.TalentEducatorInput,
    ):
        for group_id, student_id in session.query(model.school_group_id, model.student_id).distinct().all():
            wanted.add((int(group_id), int(student_id)))
    existing = {int(row[0]) for row in session.query(models.Student.id).all()}
    for group_id, student_id in sorted(wanted):
        if student_id in existing:
            continue
        session.add(models.Student(
            id=student_id, school_group_id=group_id, first_name="Test",
            last_name=f"Student{student_id}", status="active",
        ))
        existing.add(student_id)
    session.commit()


TALENT_STUDENT_OWNED = (
    models.TalentAssessmentCyclePopulationMember, models.TalentStudentAssessment,
    models.TalentStudentCompetencyResult, models.TalentReviewCandidate,
    models.TalentOfficialIdentification, models.TalentEducatorInput,
)


def install_auto_students(session):
    """Make Talent rows added by a test's own seed code reference real Students.

    A ``before_flush`` hook adds a minimal placeholder ``Student`` for any newly
    added Talent row whose Student does not exist, and lets a test that later adds
    its own real ``Student`` with the same id replace that placeholder. Fixture
    plumbing only: production code and the dedicated orphan tests
    (``tests/test_talent_batch1_data_scope.py``) never use it.
    """
    from sqlalchemy import event

    def is_placeholder(row):
        return row.first_name == "Test" and str(row.last_name or "").startswith("Student")

    @event.listens_for(session, "before_flush")
    def _ensure(sess, _context, _instances):
        with sess.no_autoflush:
            incoming = {obj.id: obj for obj in sess.new if isinstance(obj, models.Student) and obj.id is not None}
            for student_id, replacement in list(incoming.items()):
                existing = sess.get(models.Student, student_id)
                if existing is not None and existing is not replacement and is_placeholder(existing):
                    # The test seeds its own real Student with a placeholder's id: the
                    # placeholder row simply takes over the real Student's values.
                    for column in models.Student.__table__.columns:
                        if column.key != "id" and column.key in replacement.__dict__:
                            setattr(existing, column.key, getattr(replacement, column.key))
                    sess.expunge(replacement)
            needed = {}
            for obj in list(sess.new):
                if isinstance(obj, TALENT_STUDENT_OWNED) and getattr(obj, "student_id", None):
                    needed[int(obj.student_id)] = int(obj.school_group_id)
            for student_id, group_id in needed.items():
                if student_id in incoming or sess.get(models.Student, student_id) is not None:
                    continue
                sess.add(models.Student(
                    id=student_id, school_group_id=group_id, first_name="Test",
                    last_name=f"Student{student_id}", status="active",
                ))
