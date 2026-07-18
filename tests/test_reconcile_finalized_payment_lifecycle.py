import json
from pathlib import Path
import subprocess
import sys

from scripts import reconcile_finalized_payment_lifecycle


ROOT = Path(__file__).resolve().parents[1]


class _CommitFailureSession:
    def __init__(self):
        self.rollback_called = False
        self.close_called = False

    def commit(self):
        raise RuntimeError("test commit failure")

    def rollback(self):
        self.rollback_called = True

    def close(self):
        self.close_called = True


def test_apply_logs_original_commit_exception_before_rollback(monkeypatch, capsys):
    session = _CommitFailureSession()
    monkeypatch.setattr(reconcile_finalized_payment_lifecycle, "SessionLocal", lambda: session)
    monkeypatch.setattr(reconcile_finalized_payment_lifecycle, "_require_sandbox", lambda: None)
    monkeypatch.setattr(
        reconcile_finalized_payment_lifecycle.payment_lifecycle_reconciliation_service,
        "reconcile_finalized_lifecycle",
        lambda db, email, apply: {"status": "reconciled"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reconcile_finalized_payment_lifecycle.py",
            "--email",
            "customer@example.com",
            "--apply",
        ],
    )

    assert reconcile_finalized_payment_lifecycle.main() == 1

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["reason_code"] == "unexpected_reconciliation_error"
    assert report["phase"] == "database_commit"
    assert report["exception_type"] == "RuntimeError"
    assert report["exception_message"] == "test commit failure"
    assert report["failing_function"] == "commit"
    assert isinstance(report["failing_line"], int)
    assert "Traceback (most recent call last)" in captured.err
    assert "RuntimeError: test commit failure" in captured.err
    assert session.rollback_called is True
    assert session.close_called is True


def test_standalone_script_registers_operational_and_saas_metadata():
    code = """
import scripts.reconcile_finalized_payment_lifecycle
from database import Base
required = {
    'school_groups',
    'subscription_contracts',
    'tenant_provisioning_links',
    'pending_organizations',
}
missing = required.difference(Base.metadata.tables)
assert not missing, sorted(missing)
contract = Base.metadata.tables['subscription_contracts']
foreign_keys = {foreign_key.target_fullname for foreign_key in contract.c.school_group_id.foreign_keys}
assert foreign_keys == {'school_groups.id'}, foreign_keys
Base.metadata.sorted_tables
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
