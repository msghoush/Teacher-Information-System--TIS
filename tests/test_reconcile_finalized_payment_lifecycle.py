import json
import sys

from scripts import reconcile_finalized_payment_lifecycle


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
