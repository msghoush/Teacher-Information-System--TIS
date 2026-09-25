"""Read-only duplicate Talent Program audit (final-closure Part B, B3).

Runs the owner-facing script against a temporary SQLite fixture. Proves the output
shape, that duplicate/branch-suffix/history/overlap findings are produced, that
grants of configuration authority are reported as aggregates only, and that the
audit never modifies the database (byte-identical file, write attempts rejected).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import models
from database import Base

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_talent_program_duplicates_readonly.py"


def load_script():
    spec = importlib.util.spec_from_file_location("audit_talent_program_duplicates_readonly_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def fixture_db(tmp_path):
    path = tmp_path / "audit_fixture.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([models.SchoolGroup(id=1, name="Audit One"), models.SchoolGroup(id=2, name="Audit Two")])
    session.commit()
    session.add_all([
        models.Branch(id=10, school_group_id=1, name="North Campus"),
        models.Branch(id=11, school_group_id=1, name="South Campus"),
        models.Branch(id=20, school_group_id=2, name="Elsewhere"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ])
    programs = [
        (1, 1, "Leadership Program"), (2, 1, "Leadership Program - North Campus"),   # branch-name variant
        (3, 1, "Robotics"), (4, 1, "robotics  "),                                    # case/whitespace
        (5, 1, "Chess"), (6, 2, "Leadership Program"),                                # other tenant, unrelated
        (7, 1, "Art-Studio"), (8, 1, "Art Studio"),                                   # hyphenation
    ]
    for pid, group, name in programs:
        session.add(models.TalentProgram(id=pid, school_group_id=group, name=name, status="active"))
    session.commit()
    # Same Academic Year configuration on both Robotics duplicates (overlap) plus history on both.
    for pid in (3, 4):
        session.add(models.TalentProgramAcademicYearConfiguration(
            school_group_id=1, program_id=pid, academic_year_id=100, is_enabled=True, eligible_grade_levels_csv="1,2"))
        session.add(models.TalentProgramFrameworkVersion(
            school_group_id=1, program_id=pid, version_number=1, status="active", title="Robotics setup",
            semantic_fingerprint="f" * 64))
        session.add(models.TalentAssessmentCycle(
            school_group_id=1, program_id=pid, academic_year_id=100, framework_version_id=pid,
            title="Cycle", status="open", revision=1))
    # History on only ONE Leadership member.
    session.add(models.TalentAssessmentCycle(
        school_group_id=1, program_id=1, academic_year_id=100, framework_version_id=1,
        title="Cycle", status="open", revision=1))
    # Stored non-Administrator grants of configuration authority.
    session.add(models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_programs.manage", is_allowed=True))
    session.add(models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_programs.view", is_allowed=True))
    session.add(models.RolePermission(school_group_id=1, role="Administrator", permission_key="talent_programs.manage", is_allowed=True))
    session.commit()
    session.close()
    engine.dispose()
    return path


def test_report_shape_findings_and_exit_code(fixture_db):
    script = load_script()
    report, code = script.perform_audit(f"sqlite:///{fixture_db}")
    assert code == 2
    assert report["read_only"] is True and report["audit"] == "talent_program_duplicates_readonly"
    assert report["summary"]["programs"] == 8
    group_one = next(item for item in report["school_groups"] if item["school_group_id"] == 1)
    group_two = next(item for item in report["school_groups"] if item["school_group_id"] == 2)
    # A same-named Program in another SchoolGroup is never clustered across tenants.
    assert group_two["suspected_duplicate_clusters"] == []
    clusters = {tuple(item["program_ids"]): item for item in group_one["suspected_duplicate_clusters"]}
    assert set(clusters) == {(1, 2), (3, 4), (7, 8)}
    assert "branch_name_variant" in clusters[(1, 2)]["reasons"]
    assert clusters[(1, 2)]["merge_risk"] == "requires_manual_review" and clusters[(1, 2)]["members_with_history"] == [1]
    assert clusters[(3, 4)]["merge_risk"] == "destructive" and clusters[(3, 4)]["overlapping_academic_year_ids"] == [100]
    assert clusters[(7, 8)]["merge_risk"] == "no_history_references"
    # Per-Program metadata columns the owner asked for.
    robotics = next(item for item in group_one["programs"] if item["program_id"] == 3)
    for field in ("name", "status", "framework_versions", "active_framework_versions", "competencies",
                  "annual_configurations", "annual_configuration_academic_year_ids", "evaluation_plans",
                  "evaluation_periods", "history_references", "history_reference_total", "structure_signature"):
        assert field in robotics
    assert robotics["history_references"]["assessment_cycles"] == 1 and robotics["annual_configurations"] == 1
    # Grants: only the non-Administrator ALLOW on a configuration key, as an aggregate count.
    assert report["configuration_grants"]["role_grants"] == [
        {"school_group_id": 1, "role": "Editor", "permission_key": "talent_programs.manage", "stored_allow_rows": 1}]
    assert report["summary"]["non_administrator_configuration_grants"] == 1


def test_output_contains_no_student_user_or_secret_fields(fixture_db):
    script = load_script()
    report, _ = script.perform_audit(f"sqlite:///{fixture_db}")
    rendered = json.dumps(report).lower()
    for forbidden in ("student", "password", "email", "user_id", "token", "secret", "sqlite:///"):
        assert forbidden not in rendered, forbidden


def test_audit_never_modifies_the_database(fixture_db):
    script = load_script()
    before = digest(fixture_db)
    script.perform_audit(f"sqlite:///{fixture_db}")
    script.main(["--database-url", f"sqlite:///{fixture_db}"])
    assert digest(fixture_db) == before
    # The session the audit uses rejects writes outright.
    session, connection = script.open_read_only_session(f"sqlite:///{fixture_db}")
    try:
        with pytest.raises(OperationalError):
            session.execute(text("DELETE FROM talent_programs"))
    finally:
        session.rollback()
        session.close()
        connection.close()
    assert digest(fixture_db) == before


def test_cli_prints_json_and_uses_exit_codes(fixture_db, capsys, monkeypatch):
    script = load_script()
    assert script.main(["--database-url", f"sqlite:///{fixture_db}"]) == 2
    printed = json.loads(capsys.readouterr().out)
    assert printed["summary"]["suspected_duplicate_clusters"] == 3
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert script.main([]) == 1
    assert "DatabaseUrlMissing" in capsys.readouterr().out


def test_clean_database_exits_zero(tmp_path):
    script = load_script()
    path = tmp_path / "clean.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(models.SchoolGroup(id=1, name="Clean"))
    session.commit()
    session.add_all([models.TalentProgram(id=1, school_group_id=1, name="Alpha", status="active"),
                     models.TalentProgram(id=2, school_group_id=1, name="Beta", status="draft")])
    session.commit()
    session.close()
    engine.dispose()
    report, code = script.perform_audit(f"sqlite:///{path}")
    assert code == 0 and report["summary"]["suspected_duplicate_clusters"] == 0
