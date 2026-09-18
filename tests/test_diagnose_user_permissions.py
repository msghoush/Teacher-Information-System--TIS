import os

os.environ["TIS_SESSION_SECRET"] = "diagnose-user-permissions-test-secret-that-is-long-enough"

import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
import models
import permission_registry
import user_permission_service as ups
from scripts.diagnose_user_permissions import diagnose

REPO_ROOT = Path(__file__).resolve().parents[1]

ADMIN = auth.ROLE_ADMINISTRATOR


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_not_found_returns_safe_minimal_result():
    db = _make_db()
    result = diagnose(db, email="nobody@example.com", permission_key="subjects.view")

    assert result["status"] == "not_found"
    assert set(result.keys()) == {"status", "email", "message"}
    db.close()


def test_unknown_permission_key_does_not_include_trace():
    db = _make_db()
    school = models.SchoolGroup(name="School", status=True)
    db.add(school)
    db.flush()
    user = models.User(
        user_id="1001", username="admin_a", first_name="Admin", last_name="A",
        role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
        school_group_id=school.id, email="admin_a@example.com",
        email_normalized=auth.normalize_email("admin_a@example.com"), is_active=True,
    )
    db.add(user)
    db.commit()

    result = diagnose(db, email="admin_a@example.com", permission_key="not.a.real.key")

    assert result["status"] == "unknown_permission_key"
    assert "permission_trace" not in result
    db.close()


def test_found_user_trace_reflects_user_override():
    db = _make_db()
    school = models.SchoolGroup(name="School", status=True)
    db.add(school)
    db.flush()
    user = models.User(
        user_id="1001", username="user_a", first_name="User", last_name="A",
        role=auth.ROLE_USER, position="Teacher", password=auth.get_password_hash("password123"),
        school_group_id=school.id, email="user_a@example.com",
        email_normalized=auth.normalize_email("user_a@example.com"), is_active=True,
    )
    db.add(user)
    db.commit()

    key = "subjects.view"
    ups.apply_user_override(
        db,
        target_user=user,
        permission_key=key,
        decision="allow",
        school_group_id=school.id,
    )
    db.commit()

    result = diagnose(db, email="user_a@example.com", permission_key=key)

    assert result["status"] == "found"
    assert result["permission_trace"]["user_override"]["decision"] == "allow"
    assert result["permission_trace"]["final_effective_after_user_override"] is True
    assert result["get_allowed_permission_keys_contains_requested_key"] is True
    db.close()


def test_result_never_contains_password_hash_or_database_url():
    db = _make_db()
    school = models.SchoolGroup(name="School", status=True)
    db.add(school)
    db.flush()
    user = models.User(
        user_id="1001", username="admin_a", first_name="Admin", last_name="A",
        role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
        school_group_id=school.id, email="admin_a@example.com",
        email_normalized=auth.normalize_email("admin_a@example.com"), is_active=True,
    )
    db.add(user)
    db.commit()

    result = diagnose(db, email="admin_a@example.com", permission_key="subjects.view")
    blob = json.dumps(result, default=str)

    assert "password123" not in blob
    assert user.password not in blob
    assert "DATABASE_URL" not in blob
    db.close()


def test_identity_resolution_matches_login_case_insensitive_email():
    """The diagnostic must resolve identity the same way login does
    (auth.resolve_login_user / normalized email), not via a raw
    case-sensitive models.User.email equality lookup."""
    db = _make_db()
    school = models.SchoolGroup(name="School", status=True)
    db.add(school)
    db.flush()
    user = models.User(
        user_id="1001", username="admin_a", first_name="Admin", last_name="A",
        role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
        school_group_id=school.id, email="Admin_A@Example.com",
        email_normalized=auth.normalize_email("Admin_A@Example.com"), is_active=True,
    )
    db.add(user)
    db.commit()

    # Login would resolve this identifier via email_normalized regardless
    # of case; the diagnostic must resolve the same account.
    result = diagnose(db, email="admin_a@example.com", permission_key="subjects.view")

    assert result["status"] == "found"
    assert result["user_id"] == user.id
    db.close()


def test_direct_invocation_works_without_pythonpath():
    """python scripts/diagnose_user_permissions.py ... must work as a
    direct invocation from the repository root without requiring
    PYTHONPATH=. to import repo-root modules."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["TIS_SESSION_SECRET"] = "diagnose-user-permissions-test-secret-that-is-long-enough"
    env["DATABASE_URL"] = "sqlite:///:memory:"

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "diagnose_user_permissions.py"),
            "--email", "nobody@example.com",
            "--permission-key", "subjects.view",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode in (0, 1, 2), completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr
    assert "ImportError" not in completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] in ("not_found", "database_unavailable")
