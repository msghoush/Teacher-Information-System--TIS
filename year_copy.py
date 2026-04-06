from sqlalchemy.orm import Session

import models


def get_copy_year_choices(db: Session, current_year_id: int):
    return (
        db.query(models.AcademicYear)
        .filter(models.AcademicYear.id != current_year_id)
        .order_by(models.AcademicYear.year_name.desc())
        .all()
    )


def get_academic_year(db: Session, academic_year_id: int):
    if academic_year_id is None:
        return None
    return (
        db.query(models.AcademicYear)
        .filter(models.AcademicYear.id == academic_year_id)
        .first()
    )
