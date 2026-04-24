from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint, Index, LargeBinary, DateTime, Text
from sqlalchemy.orm import relationship
from database import Base


class Branch(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    location = Column(String)
    status = Column(Boolean, default=True)


class AcademicYear(Base):
    __tablename__ = "academic_years"
    id = Column(Integer, primary_key=True, index=True)
    year_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(10), unique=True, index=True)
    username = Column(String(50), unique=True, index=True)
    first_name = Column(String)
    last_name = Column(String)
    position = Column(String(50))
    password = Column(String)
    role = Column(String)
    profile_image_path = Column(String(255))
    profile_image_content_type = Column(String(50))
    profile_image_data = Column(LargeBinary)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))
    is_active = Column(Boolean, default=True)


class SystemNotification(Base):
    __tablename__ = "system_notifications"
    __table_args__ = (
        Index("ix_system_notifications_recipient_status", "recipient_user_id", "status"),
        Index("ix_system_notifications_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    recipient_user_id = Column(String(10), index=True, nullable=False)
    requesting_user_id = Column(String(10), index=True)
    request_type = Column(String(80), nullable=False)
    title = Column(String(160), nullable=False)
    message = Column(Text)
    details = Column(Text)
    status = Column(String(20), nullable=False, default="New")
    recipient_scope = Column(String(10), nullable=False, default="User")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    seen_at = Column(DateTime)
    resolved_at = Column(DateTime)
    resolved_by_user_id = Column(String(10))


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        Index(
            "uq_subjects_scope_code",
            "branch_id",
            "academic_year_id",
            "subject_code",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    subject_code = Column(String, index=True)
    subject_name = Column(String)
    color = Column(String(7))
    weekly_hours = Column(Integer)
    grade = Column(Integer)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))


class Teacher(Base):
    __tablename__ = "teachers"
    __table_args__ = (
        Index(
            "uq_teachers_scope_teacher_id",
            "branch_id",
            "academic_year_id",
            "teacher_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(String(10))
    first_name = Column(String)
    middle_name = Column(String)
    last_name = Column(String)
    degree_major = Column(String(120))
    # Stored as a scoped legacy value; validation is enforced in the app layer.
    subject_code = Column(String)
    level = Column(String)
    max_hours = Column(Integer, default=24)
    extra_hours_allowed = Column(Boolean, default=False)
    extra_hours_count = Column(Integer, default=0)
    teaches_national_section = Column(Boolean, default=False)
    national_section_hours = Column(Integer, default=0)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))


class TeacherSubjectAllocation(Base):
    __tablename__ = "teacher_subject_allocations"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id",
            "subject_code",
            name="uq_teacher_subject_allocations_teacher_subject",
        ),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False, index=True)
    # Subject codes are branch/year scoped, so allocations store the selected code
    # and resolve it through the teacher's current scope.
    subject_code = Column(String, nullable=False)
    compatibility_override = Column(Boolean, default=False, nullable=False)


class TeacherQualificationSelection(Base):
    __tablename__ = "teacher_qualification_selections"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id",
            "qualification_key",
            name="uq_teacher_qualification_selections_teacher_qualification",
        ),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False, index=True)
    qualification_key = Column(String(80), nullable=False)


class QualificationOption(Base):
    __tablename__ = "qualification_options"
    __table_args__ = (
        UniqueConstraint(
            "qualification_key",
            name="uq_qualification_options_key",
        ),
    )

    id = Column(Integer, primary_key=True)
    qualification_key = Column(String(80), nullable=False, index=True)
    label = Column(String(120), nullable=False)
    kind = Column(String(32), nullable=False)
    alignment_keys = Column(String(255), nullable=False, default="")
    legacy_aliases = Column(String(500), nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)


class TeacherSectionAssignment(Base):
    __tablename__ = "teacher_section_assignments"
    __table_args__ = (
        UniqueConstraint(
            "planning_section_id",
            "subject_code",
            name="uq_teacher_section_assignments_section_subject",
        ),
        Index(
            "ix_teacher_section_assignments_teacher_id",
            "teacher_id",
        ),
        Index(
            "ix_teacher_section_assignments_planning_section_id",
            "planning_section_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    planning_section_id = Column(
        Integer,
        ForeignKey("planning_sections.id"),
        nullable=False,
    )
    subject_code = Column(String, nullable=False)


class PlanningSection(Base):
    __tablename__ = "planning_sections"
    __table_args__ = (
        UniqueConstraint(
            "grade_level",
            "section_name",
            "branch_id",
            "academic_year_id",
            name="uq_planning_sections_scope_grade_section",
        ),
    )

    id = Column(Integer, primary_key=True)
    grade_level = Column(String(8), nullable=False)
    section_name = Column(String(20), nullable=False)
    class_status = Column(String(20), nullable=False)
    homeroom_teacher_id = Column(Integer, nullable=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"), nullable=False)


class TimetableSetting(Base):
    __tablename__ = "timetable_settings"
    __table_args__ = (
        UniqueConstraint(
            "branch_id",
            "academic_year_id",
            name="uq_timetable_settings_scope",
        ),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    academic_year_id = Column(
        Integer,
        ForeignKey("academic_years.id"),
        nullable=False,
        index=True,
    )
    working_days_csv = Column(String(120), nullable=False, default="")
    periods_per_day = Column(Integer, nullable=False, default=8)
    period_duration_minutes = Column(Integer, nullable=False, default=45)
    school_start_time = Column(String(5), nullable=False, default="07:00")
    school_end_time = Column(String(5), nullable=False, default="13:00")


class TimetableNonTeachingBlock(Base):
    __tablename__ = "timetable_non_teaching_blocks"
    __table_args__ = (
        Index(
            "ix_timetable_non_teaching_blocks_setting_id",
            "timetable_setting_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    timetable_setting_id = Column(
        Integer,
        ForeignKey("timetable_settings.id"),
        nullable=False,
    )
    block_type = Column(String(32), nullable=False)
    label = Column(String(80), nullable=False)
    day_key = Column(String(16), nullable=False, default="all")
    start_period = Column(Integer, nullable=False)
    end_period = Column(Integer, nullable=False)


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"
    __table_args__ = (
        UniqueConstraint(
            "branch_id",
            "academic_year_id",
            "planning_section_id",
            "day_key",
            "period_index",
            name="uq_timetable_entries_section_slot",
        ),
        UniqueConstraint(
            "branch_id",
            "academic_year_id",
            "teacher_id",
            "day_key",
            "period_index",
            name="uq_timetable_entries_teacher_slot",
        ),
        Index(
            "ix_timetable_entries_scope_section",
            "branch_id",
            "academic_year_id",
            "planning_section_id",
        ),
        Index(
            "ix_timetable_entries_scope_teacher",
            "branch_id",
            "academic_year_id",
            "teacher_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    academic_year_id = Column(
        Integer,
        ForeignKey("academic_years.id"),
        nullable=False,
    )
    planning_section_id = Column(
        Integer,
        ForeignKey("planning_sections.id"),
        nullable=False,
    )
    subject_code = Column(String, nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    day_key = Column(String(16), nullable=False)
    period_index = Column(Integer, nullable=False)
