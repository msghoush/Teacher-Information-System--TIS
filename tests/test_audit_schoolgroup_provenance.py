import ast
import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "audit_schoolgroup_provenance.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "audit_schoolgroup_provenance",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_audit_is_read_only_and_sanitizes_workspace_identity():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in source
    assert "db.rollback()" in source
    assert "db.commit()" not in source
    assert "Paddle" not in source
    assert "school_group_name" not in source
    assert "email" not in source.lower()
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"add", "add_all", "delete", "flush", "merge"}
        for node in ast.walk(tree)
    )


def test_audit_requires_database_url(monkeypatch):
    module = _load_script()
    monkeypatch.delenv("DATABASE_URL", raising=False)

    report, exit_code = module._run()

    assert exit_code == module.EXIT_FAILURE
    assert report["reason_code"] == "database_url_missing"
    assert report["assurances"]["data_changed"] is False


def test_workspace_reference_is_stable_and_not_raw_identity():
    module = _load_script()
    raw_uuid = "00000000-0000-0000-0000-000000000007"

    first = module._workspace_ref(raw_uuid)
    second = module._workspace_ref(raw_uuid)

    assert first == second
    assert raw_uuid not in first
    assert len(first) == 16
