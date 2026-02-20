from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
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
    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))
    is_active = Column(Boolean, default=True)


class Subject(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True)
    subject_code = Column(String, unique=True, index=True)
    subject_name = Column(String)
    weekly_hours = Column(Integer)
    grade = Column(Integer)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))


class Teacher(Base):
    __tablename__ = "teachers"
    id = Column(Integer, primary_key=True)
    teacher_id = Column(String(10), unique=True)
    first_name = Column(String)
    middle_name = Column(String)
    last_name = Column(String)
    subject_code = Column(String, ForeignKey("subjects.subject_code"))
    level = Column(String)
    max_hours = Column(Integer, default=24)
    extra_hours_allowed = Column(Boolean, default=False)
    extra_hours_count = Column(Integer, default=0)
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
    subject_code = Column(String, ForeignKey("subjects.subject_code"), nullable=False)
