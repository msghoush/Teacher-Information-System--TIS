from pydantic import BaseModel


class SubjectCreate(BaseModel):
    subject_code: str
    subject_name: str
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
    branch_id: int
    academic_year_id: int
