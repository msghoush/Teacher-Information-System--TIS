"""Loopback-only operational acceptance server with real Talent API writes.

Run from the repository: .venv/Scripts/python.exe tests/talent_operational_preview.py
Open http://127.0.0.1:8766/talent/programs. Restart resets all synthetic data.
The SQLite database lives in a temporary directory; tis.db is never opened.
Authentication alone is injected. Canonical role permissions and real route,
service, revision, audit, tenant, and frozen-population checks remain active.
This is a local acceptance fixture, never an application startup module.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
TEMP_DATABASE = TemporaryDirectory(prefix="tis-talent-operational-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(TEMP_DATABASE.name) / "acceptance.sqlite").as_posix()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

import models
from auth import get_current_user
from database import Base, SessionLocal, engine
from dependencies import get_db
from permission_registry import ALL_PERMISSION_KEYS
from routers import (
    talent_ui, talent_programs, talent_evaluation_plans, talent_assessment_cycles,
    talent_assessments, talent_review_candidates, talent_official_identifications,
    talent_educator_inputs, talent_learner_profiles,
)
from student_academic_service import create_placement, create_student


def actor():
    return models.User(
        user_id="synthetic-operator", username="Synthetic operator", role="Editor",
        user_type="TENANT", access_scope="ORGANIZATION", school_group_id=1,
        branch_id=10, academic_year_id=100, is_active=True,
    )


def seed():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(models.SchoolGroup(id=1, name="Synthetic Academy"))
        db.commit()
        db.add_all([
            models.Branch(id=10, school_group_id=1, name="Learning Campus", status=True),
            models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        ])
        db.commit()
        db.add(models.PlanningSection(id=1000, branch_id=10, academic_year_id=100,
                                     grade_level="1", section_name="A", class_status="Current"))
        db.add(actor())
        db.add_all(models.RolePermission(school_group_id=1, role="Editor", permission_key=key,
                                        is_allowed=True)
                   for key in ALL_PERMISSION_KEYS if key.startswith("talent_"))
        db.commit()
        for name in ("Alex", "Morgan"):
            student = create_student(db, school_group_id=1, first_name=name, last_name="Sample")
            create_placement(db, school_group_id=1, student_id=student.id, academic_year_id=100,
                             branch_id=10, planning_section_id=1000,
                             effective_from=datetime(2026, 9, 1))
        db.commit()


def local_db():
    with SessionLocal() as db:
        yield db


seed()
app = FastAPI(title="Synthetic Talent operational acceptance")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
for module in (
    talent_ui, talent_programs, talent_evaluation_plans, talent_assessment_cycles,
    talent_assessments, talent_review_candidates, talent_official_identifications,
    talent_educator_inputs, talent_learner_profiles,
):
    app.include_router(module.router)
app.dependency_overrides[get_db] = local_db
app.dependency_overrides[get_current_user] = actor


@app.middleware("http")
async def no_store(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    import uvicorn
    try:
        uvicorn.run(app, host="127.0.0.1", port=8766, workers=1)
    finally:
        engine.dispose()
        TEMP_DATABASE.cleanup()
