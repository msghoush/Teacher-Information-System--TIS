"""Phase D preparation: safe persistent local Talent & Potential test data.

Verifies (a) the dataset builder produces a contract-valid, relationship-sound
seed using only real service-layer calls, (b) the CLI safety gate refuses an
unsafe/non-test target and a production-like environment, (c) create/seed and
reset/reseed are repeatable against an isolated file database, and (d) the
Owner's real tis.db is never touched by any of this.
"""

import hashlib
import importlib
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models
import auth
from database import Base
from talent_local_test_data import LOCAL_TEST_PASSWORD, LOCAL_TEST_USERNAME, build_dataset

manage = importlib.import_module("scripts.manage_local_talent_test_db")


def _memory_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _tis_db_fingerprint():
    path = Path(__file__).resolve().parents[1] / "tis.db"
    if not path.exists():
        return None
    return (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())


def test_build_dataset_produces_a_relationship_valid_seed():
    session = _memory_session()
    try:
        summary = build_dataset(session)

        assert len(summary["student_ids"]) == 6
        assert len(summary["program_ids"]) == 3
        assert len(summary["cycle_ids"]) == 3
        assert summary["identification_id"] is not None

        group_id = summary["school_group_id"]
        programs = session.query(models.TalentProgram).filter_by(school_group_id=group_id).all()
        assert {p.status for p in programs} == {"active"}

        frameworks = session.query(models.TalentProgramFrameworkVersion).filter_by(school_group_id=group_id).all()
        assert {f.status for f in frameworks} == {"active"}

        cycles = session.query(models.TalentAssessmentCycle).filter_by(school_group_id=group_id).order_by(
            models.TalentAssessmentCycle.id).all()
        assert [c.status for c in cycles] == ["closed", "open", "draft"]

        assessments = session.query(models.TalentStudentAssessment).filter_by(school_group_id=group_id).all()
        assert {a.status for a in assessments} >= {"completed", "in_progress", "insufficient_evidence"}

        # Every competency result must resolve to a real Framework Competency and
        # Rubric Level belonging to the exact same Framework as its Assessment.
        results = session.query(models.TalentStudentCompetencyResult).filter_by(school_group_id=group_id).all()
        assert results
        for result in results:
            competency = session.get(models.FrameworkCompetency, result.framework_competency_id)
            level = session.get(models.TalentRubricLevel, result.rubric_level_id)
            assert competency is not None and competency.framework_version_id == result.framework_version_id
            assert level is not None and level.framework_version_id == result.framework_version_id

        candidates = session.query(models.TalentReviewCandidate).filter_by(school_group_id=group_id).all()
        assert candidates
        assert any(c.status == "reviewed" for c in candidates)

        identifications = session.query(models.TalentOfficialIdentification).filter_by(school_group_id=group_id).all()
        assert len(identifications) == 1
        assert identifications[0].decision == "identified"

        inputs = session.query(models.TalentEducatorInput).filter_by(school_group_id=group_id).all()
        assert len(inputs) == 2

        placements = session.query(models.StudentAcademicPlacement).filter_by(school_group_id=group_id).all()
        assert any(p.status == "ended" for p in placements)  # real historical placement

        admin = session.query(models.User).filter_by(username=LOCAL_TEST_USERNAME).one()
        assert admin.is_internal_test_identity is True
        assert admin.access_scope == auth.ACCESS_SCOPE_ORGANIZATION
        assert admin.branch_id is not None  # North Campus remains the visible working Branch.
    finally:
        session.close()


def test_build_dataset_is_not_idempotent_without_reset():
    session = _memory_session()
    try:
        build_dataset(session)
        with pytest.raises(RuntimeError):
            build_dataset(session)
    finally:
        session.close()


def test_safety_gate_rejects_a_target_outside_the_dedicated_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "LOCAL_TEST_DIR", tmp_path / "dedicated")
    outside_path = tmp_path / "elsewhere" / "sneaky.db"
    with pytest.raises(manage.LocalTestDatabaseSafetyError):
        manage._assert_safe_target(outside_path)


def test_safety_gate_rejects_the_real_tracked_repository_database_files(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "LOCAL_TEST_DIR", manage.ROOT)
    with pytest.raises(manage.LocalTestDatabaseSafetyError):
        manage._assert_safe_target(manage.ROOT / "tis.db")


def test_safety_gate_rejects_a_production_like_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "LOCAL_TEST_DIR", tmp_path)
    monkeypatch.setenv("TIS_ENV", "production")
    with pytest.raises(manage.LocalTestDatabaseSafetyError):
        manage._assert_safe_target(tmp_path / "db.sqlite3")


def test_reset_refuses_a_target_database_without_the_sentinel_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "LOCAL_TEST_DIR", tmp_path)
    target = tmp_path / "unmarked.db"
    engine = create_engine(f"sqlite:///{target.as_posix()}")
    Base.metadata.create_all(engine)  # a real schema, but never marked by this tool
    engine.dispose()
    with pytest.raises(manage.LocalTestDatabaseSafetyError):
        manage.cmd_reset(target, confirmed=True)


def test_reset_refuses_without_explicit_confirm_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "LOCAL_TEST_DIR", tmp_path)
    target = tmp_path / "test.db"
    with pytest.raises(manage.LocalTestDatabaseSafetyError):
        manage.cmd_reset(target, confirmed=False)


def test_full_create_seed_status_reset_reseed_cycle_and_tis_db_is_untouched(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(manage, "LOCAL_TEST_DIR", tmp_path)
    target = tmp_path / "talent_local_test.db"
    before = _tis_db_fingerprint()

    manage.cmd_create(target)
    assert target.exists()

    manage.cmd_seed(target)
    engine = manage._engine(target)
    with engine.connect() as connection:
        from sqlalchemy import text
        count = connection.execute(text("SELECT COUNT(*) FROM students")).scalar()
    assert count == 6

    manage.cmd_status(target)
    captured = capsys.readouterr()
    assert "Sentinel marker present: True" in captured.out

    manage.cmd_reset(target, confirmed=True)
    engine = manage._engine(target)
    with engine.connect() as connection:
        from sqlalchemy import text
        count_after_reset = connection.execute(text("SELECT COUNT(*) FROM students")).scalar()
    assert count_after_reset == 0

    manage.cmd_reseed(target, confirmed=True)
    engine = manage._engine(target)
    with engine.connect() as connection:
        from sqlalchemy import text
        count_after_reseed = connection.execute(text("SELECT COUNT(*) FROM students")).scalar()
    assert count_after_reseed == 6

    after = _tis_db_fingerprint()
    assert before == after  # tis.db content and mtime are byte-for-byte unchanged
