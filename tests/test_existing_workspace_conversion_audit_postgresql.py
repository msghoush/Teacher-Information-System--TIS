import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import models
import saas.models


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_existing_workspace_conversion.py"


def _database_state_hash(engine, schema):
    payload = {}
    with engine.connect() as connection:
        inspector = inspect(connection)
        quote = connection.dialect.identifier_preparer.quote
        for table_name in sorted(inspector.get_table_names()):
            rows = connection.execute(
                text(f"SELECT * FROM {quote(table_name)} ORDER BY 1")
            ).all()
            payload[f"table:{table_name}"] = [
                tuple(str(value) for value in row) for row in rows
            ]
        payload["sequences"] = [
            tuple(str(value) for value in row)
            for row in connection.execute(
                text(
                    "SELECT sequencename, last_value FROM pg_sequences "
                    "WHERE schemaname = :schema ORDER BY sequencename"
                ),
                {"schema": schema},
            ).all()
        ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _run_cli(database_url, group, output_format="json", **overrides):
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--school-group-id",
        str(overrides.get("school_group_id", group.id)),
        "--workspace-uuid",
        overrides.get("workspace_uuid", group.workspace_uuid),
        "--expected-name",
        overrides.get("expected_name", group.name),
        "--owner-email",
        overrides.get("owner_email", "owner@postgres.example"),
        "--format",
        output_format,
    ]
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(
    not os.getenv("TIS_TEST_POSTGRESQL_URL"),
    reason="TIS_TEST_POSTGRESQL_URL is required for PostgreSQL validation",
)
def test_real_cli_is_deterministic_read_only_and_uses_documented_exit_codes():
    base_url = os.environ["TIS_TEST_POSTGRESQL_URL"]
    schema = f"m4a_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    separator = "&" if "?" in base_url else "?"
    schema_url = f"{base_url}{separator}options=-csearch_path%3D{schema}"
    engine = create_engine(schema_url)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    db = Session()
    try:
        group = models.SchoolGroup(
            name="PostgreSQL Audit Academy",
            workspace_uuid=str(uuid.uuid4()),
            workspace_classification="internal_sandbox",
            workspace_lifecycle_status="active",
            country_code="LB",
        )
        unrelated = models.SchoolGroup(
            name="Unrelated PostgreSQL Academy",
            workspace_uuid=str(uuid.uuid4()),
            workspace_classification="internal_sandbox",
            workspace_lifecycle_status="active",
        )
        db.add_all([group, unrelated])
        db.flush()
        empty = models.Branch(
            school_group_id=group.id, name="Empty Campus", status=True
        )
        occupied = models.Branch(
            school_group_id=group.id, name="Occupied Campus", status=True
        )
        db.add_all([empty, occupied])
        db.flush()
        year = models.AcademicYear(
            school_group_id=group.id, year_name="2026-2027", is_active=True
        )
        db.add(year)
        db.flush()
        teacher = models.Teacher(
            teacher_id="PG0001",
            first_name="PostgreSQL",
            last_name="Teacher",
            branch_id=occupied.id,
            academic_year_id=year.id,
        )
        db.add(teacher)
        db.flush()
        db.add(
            models.TeacherSubjectAllocation(
                teacher_id=teacher.id,
                subject_code="MATH",
                compatibility_override=False,
            )
        )
        account = saas.models.SaaSAccount(
            account_uuid=str(uuid.uuid4()),
            email="owner@postgres.example",
            email_normalized="owner@postgres.example",
            password_hash="DO_NOT_RENDER_PASSWORD_HASH",
            status="active",
            onboarding_status="tenant_active",
            account_purpose="internal_test",
            email_verified_at=datetime.utcnow(),
        )
        user = models.User(
            user_id="9700000001",
            username="postgres.owner",
            email="owner@postgres.example",
            email_normalized="owner@postgres.example",
            role="Admin",
            user_type="TENANT",
            access_scope="GROUP",
            school_group_id=group.id,
            branch_id=occupied.id,
            is_active=True,
        )
        db.add_all([account, user])
        db.flush()
        entitlement = saas.models.WorkspaceEntitlement(
            entitlement_uuid=str(uuid.uuid4()),
            school_group_id=group.id,
            entitlement_type="internal_sandbox",
            status="active",
            source="system",
        )
        db.add(entitlement)
        db.add(
            saas.models.SaaSAccountUserLink(
                saas_account_id=account.id,
                operational_user_id=user.id,
                school_group_id=group.id,
                link_type="tenant_owner",
            )
        )
        db.commit()

        before = _database_state_hash(engine, schema)
        first = _run_cli(schema_url, group)
        second = _run_cli(schema_url, group)
        after = _database_state_hash(engine, schema)

        assert first.returncode == 0, first.stderr or first.stdout
        assert second.returncode == 0, second.stderr or second.stdout
        assert first.stdout == second.stdout
        report = json.loads(first.stdout)
        assert report["transaction"] == {
            "isolation": "repeatable read",
            "read_only": "on",
            "rollback_on_exit": True,
        }
        assert report["conversion_readiness"]["recommended_archival_branch_ids"] == [
            empty.id
        ]
        assert report["conversion_readiness"]["hard_delete_approved"] is False
        assert before == after
        assert "DO_NOT_RENDER_PASSWORD_HASH" not in first.stdout
        assert base_url not in first.stdout

        mismatch = _run_cli(schema_url, group, workspace_uuid=str(uuid.uuid4()))
        assert mismatch.returncode == 3
        assert json.loads(mismatch.stdout)["reason_code"] == "workspace_identity_mismatch"

        db.execute(
            text(
                "CREATE TABLE m4a_unmodeled_branch_link ("
                "id BIGSERIAL PRIMARY KEY, "
                "branch_id INTEGER NOT NULL REFERENCES branches(id))"
            )
        )
        db.execute(
            text("INSERT INTO m4a_unmodeled_branch_link(branch_id) VALUES (:branch_id)"),
            {"branch_id": empty.id},
        )
        db.commit()
        manual_before = _database_state_hash(engine, schema)
        manual = _run_cli(schema_url, group)
        manual_after = _database_state_hash(engine, schema)
        assert manual.returncode == 2
        manual_report = json.loads(manual.stdout)
        assert manual_report["reason_code"] == "manual_review_required"
        assert manual_report["conversion_readiness"]["recommended_archival_branch_ids"] == []
        assert manual_before == manual_after

        text_result = _run_cli(schema_url, group, output_format="text")
        assert text_result.returncode == 2
        assert "Transaction isolation: repeatable read" in text_result.stdout
        assert "Transaction read only: on" in text_result.stdout
        assert "Hard deletion approved: false" in text_result.stdout
    finally:
        db.close()
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
