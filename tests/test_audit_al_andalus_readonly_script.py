import ast
import re
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "audit_al_andalus_readonly.py"
)


def test_al_andalus_production_diagnostic_is_static_and_read_only():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "TEMPORARY READ-ONLY PRODUCTION DIAGNOSTIC" in source
    assert "This script must not be imported by runtime application code." in source
    assert 'TARGET_EMAIL = "mno@as.edu.sa"' in source
    assert 'TARGET_NAME = "Al-Andalus"' in source
    assert '"alandalus"' in source
    assert 'os.getenv("DATABASE_URL"' in source
    assert 'text("SET TRANSACTION READ ONLY")' in source
    assert 'connection.dialect.name != "postgresql"' in source

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

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(
        isinstance(call.func, ast.Name) and call.func.id == "print"
        for call in calls
    )
    stdout_writes = [
        call
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and call.func.attr == "write"
        and isinstance(call.func.value, ast.Attribute)
        and isinstance(call.func.value.value, ast.Name)
        and call.func.value.value.id == "sys"
        and call.func.value.attr == "stdout"
    ]
    assert len(stdout_writes) == 1
    rendered_write = ast.get_source_segment(source, stdout_writes[0]) or ""
    assert "json.dumps(report" in rendered_write
    assert "DATABASE_URL" not in rendered_write

    assert "password" not in source.lower()
    assert "token_hash" not in source.lower()
    assert "session_token" not in source.lower()
    assert "provider_subscription_id_present" in source
    assert "provider_customer_id_present" in source
    assert source.count("db.rollback()") >= 3
    assert "db.close()" in source
