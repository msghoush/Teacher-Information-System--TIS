import ast
import importlib.util
import re
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "audit_existing_workspace_conversion.py"
)
SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "saas"
    / "existing_workspace_conversion_audit_service.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location("audit_existing_workspace_conversion", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cli_accepts_only_parameterized_workspace_identity():
    module = _load_script()
    args = module._parser().parse_args(
        [
            "--school-group-id", "7",
            "--workspace-uuid", "00000000-0000-0000-0000-000000000007",
            "--expected-name", "Example Academy",
            "--owner-email", "owner@example.edu",
            "--format", "json",
        ]
    )

    assert args.school_group_id == 7
    assert args.expected_name == "Example Academy"
    assert args.owner_email == "owner@example.edu"

    text_args = module._parser().parse_args(
        [
            "--school-group-id", "7",
            "--workspace-uuid", "00000000-0000-0000-0000-000000000007",
            "--expected-name", "Example Academy",
            "--owner-email", "owner@example.edu",
            "--format", "text",
        ]
    )
    assert text_args.format == "text"


def test_cli_is_explicitly_read_only_and_contains_no_customer_identity():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    service_source = SERVICE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "M4A READ-ONLY EXISTING WORKSPACE CONVERSION AUDIT" in source
    assert "This script must not be imported by runtime application code." in source
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in source
    assert 'os.getenv("DATABASE_URL"' in source
    assert 'connection.dialect.name != "postgresql"' in source
    assert "Al-Andalus" not in source
    assert "mno@as.edu.sa" not in source
    assert "Al-Andalus" not in service_source
    assert "mno@as.edu.sa" not in service_source

    forbidden_statement = re.compile(
        r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE|ALTER|DROP)\b",
        re.IGNORECASE,
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not forbidden_statement.search(node.value)

    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not any("paddle" in module.lower() for module in imported_modules)
    assert not any("migration" in module.lower() for module in imported_modules)

    service_tree = ast.parse(service_source)
    mutation_methods = {"add", "add_all", "delete", "flush", "commit", "merge"}
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in mutation_methods
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "db"
        for node in ast.walk(service_tree)
    )
    service_imports = {
        alias.name
        for node in ast.walk(service_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    service_imports.update(
        node.module
        for node in ast.walk(service_tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not any("paddle" in module.lower() for module in service_imports)

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(
        isinstance(call.func, ast.Name) and call.func.id == "print"
        for call in calls
    )
    assert source.count("db.rollback()") == 1
    assert "db.close()" in source


def test_cli_requires_database_url(monkeypatch):
    module = _load_script()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    args = module._parser().parse_args(
        [
            "--school-group-id", "7",
            "--workspace-uuid", "00000000-0000-0000-0000-000000000007",
            "--expected-name", "Example Academy",
            "--owner-email", "owner@example.edu",
        ]
    )

    report, exit_code = module._run(args)

    assert exit_code == 1
    assert report["reason_code"] == "database_url_missing"
    assert report["exit_code"] == module.EXIT_EXECUTION_FAILURE
    assert report["assurances"]["data_changed"] is False


def test_cli_documents_and_classifies_all_exit_codes():
    module = _load_script()
    ready = {"conversion_readiness": {"status": "ready_for_conversion_design", "blockers": []}}
    manual = {"conversion_readiness": {"status": "manual_review_required", "blockers": ["owner_saas_account_absent"]}}
    mismatch = {"conversion_readiness": {"status": "manual_review_required", "blockers": ["workspace_uuid_mismatch"]}}

    assert module._classify_report_exit(ready) == module.EXIT_SUCCESS == 0
    assert ready["reason_code"] == "audit_complete"
    assert module._classify_report_exit(manual) == module.EXIT_MANUAL_REVIEW == 2
    assert manual["reason_code"] == "manual_review_required"
    assert module._classify_report_exit(mismatch) == module.EXIT_IDENTITY_MISMATCH == 3
    assert mismatch["reason_code"] == "workspace_identity_mismatch"
    assert module.EXIT_EXECUTION_FAILURE == 1


def test_cli_text_format_is_deterministic_and_safe():
    module = _load_script()
    report = {
        "status": "manual_review_required",
        "reason_code": "manual_review_required",
        "exit_code": 2,
        "snapshot_hash": "a" * 64,
        "transaction": {
            "isolation": "repeatable read",
            "read_only": "on",
            "rollback_on_exit": True,
        },
        "conversion_readiness": {
            "status": "manual_review_required",
            "blockers": ["commercial_conflict"],
            "warnings": [],
            "recommended_archival_branch_ids": [4, 9],
            "hard_delete_approved": False,
            "write_conversion_approved": False,
        },
    }

    first = module._render_text(report)
    second = module._render_text(report)

    assert first == second
    assert "Transaction isolation: repeatable read" in first
    assert "Transaction read only: on" in first
    assert "Recommended archival branch IDs: 4, 9" in first
    assert "Hard deletion approved: false" in first
    assert "DATABASE_URL" not in first
