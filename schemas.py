from pydantic import BaseModel


class SubjectCreate(BaseModel):
    subject_code: str
    subject_name: str
    color: str | None = None
    weekly_hours: int
    grade: int
    branch_id: int
    academic_year_id: int


class TeacherCreate(BaseModel):
    teacher_id: str
    first_name: str
    last_name: str
    subject_codes: list[str]
    max_hours: int = 24
    extra_hours_allowed: bool = False
    extra_hours_count: int = 0
    teaches_national_section: bool = False
    national_section_hours: int = 0
    is_new_teacher: bool = False
    branch_id: int
    academic_year_id: int
