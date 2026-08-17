import ast
import datetime
import importlib.util
import re
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "audit_al_andalus_readonly.py"
)


def _load_diagnostic_module():
    spec = importlib.util.spec_from_file_location(
        "audit_al_andalus_readonly_test_module", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _promo_evidence(*, status="active", link_changes=None):
    now = datetime.datetime(2026, 8, 17, tzinfo=datetime.timezone.utc)
    link = {
        "id": 10,
        "school_group_id": 1,
        "subscription_contract_id": None,
        "demo_request_id": None,
        "promo_grant_id": 30,
    }
    link.update(link_changes or {})
    return {
        "group_id": 1,
        "tenant_links": [link],
        "subscription_contracts": [
            {"id": 99, "school_group_id": 1, "plan_id": 2, "payment_status": "pending"}
        ],
        "demo_requests": [],
        "promo_codes": [{"id": 11, "subscription_plan_id": 3}],
        "promo_redemptions": [
            {
                "id": 20,
                "promo_code_id": 11,
                "school_group_id": 1,
                "plan_id": 3,
                "plan_code_snapshot": "enterprise_ai",
                "plan_name_snapshot": "Enterprise AI",
                "allowed_branches": 5,
                "allowed_staff_users": 20,
                "allowed_teachers": 100,
                "effective_from": now - datetime.timedelta(days=1),
                "effective_to": now + datetime.timedelta(days=30),
            }
        ],
        "promo_grants": [
            {
                "id": 30,
                "promo_redemption_id": 20,
                "school_group_id": 1,
                "plan_id": 3,
                "plan_code_snapshot": "enterprise_ai",
                "plan_name_snapshot": "Enterprise AI",
                "allowed_branches": 5,
                "allowed_staff_users": 20,
                "allowed_teachers": 100,
                "effective_from": now - datetime.timedelta(days=1),
                "effective_to": now + datetime.timedelta(days=30),
                "status": status,
            }
        ],
        "workspace_entitlements": [
            {
                "id": 40,
                "school_group_id": 1,
                "entitlement_type": "promo",
                "status": "active",
                "source": "promo",
                "promo_grant_id": 30,
            }
        ],
        "promo_assignments": [
            {"promo_grant_id": 30, "school_group_id": 1, "branch_id": 1}
        ],
        "branch_entitlements": [
            {
                "school_group_id": 1,
                "branch_id": 1,
                "workspace_entitlement_id": 40,
                "entitlement_mode": "active",
            },
            {
                "school_group_id": 1,
                "branch_id": 2,
                "workspace_entitlement_id": 40,
                "entitlement_mode": "inactive",
            },
        ],
        "branches": [
            {"id": 1, "name": "Main", "status": True},
            {"id": 2, "name": "Archive", "status": False},
        ],
        "now": now,
    }


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


def test_valid_promo_source_and_enterprise_snapshot_override_historical_contract():
    module = _load_diagnostic_module()
    result = module._analyze_commercial_evidence(**_promo_evidence())

    assert result["authoritative_commercial_source"] == "promo"
    assert result["authoritative_plan_source"] == "promo_grant"
    assert result["source_free_tenant_links"] == []
    assert result["promo_commercial_state"] == {
        "promo_code_id": 11,
        "promo_redemption_id": 20,
        "promo_grant_id": 30,
        "plan_id": 3,
        "plan_code": "enterprise_ai",
        "plan_name": "Enterprise AI",
        "allowed_branches": 5,
        "allowed_staff_users": 20,
        "allowed_teachers": 100,
        "effective_from": _promo_evidence()["promo_grants"][0]["effective_from"],
        "effective_to": _promo_evidence()["promo_grants"][0]["effective_to"],
        "status": "active",
        "tenant_link_matches_grant": True,
        "workspace_entitlement_matches_grant": True,
        "branch_entitlements_coherent": True,
    }
    assert result["promo_branch_state"][0]["commercially_available"] is True
    assert result["promo_branch_state"][1]["commercially_available"] is False


def test_mismatched_and_multiple_promo_sources_fail_closed():
    module = _load_diagnostic_module()
    mismatch = _promo_evidence(link_changes={"promo_grant_id": 31})
    mismatch_result = module._analyze_commercial_evidence(**mismatch)
    assert mismatch_result["authoritative_commercial_source"] == "conflict"
    assert "promo_tenant_link_mismatch" in mismatch_result["blocking_invariants"]

    multiple = _promo_evidence(link_changes={"subscription_contract_id": 99})
    multiple_result = module._analyze_commercial_evidence(**multiple)
    assert multiple_result["authoritative_commercial_source"] == "conflict"
    assert "multiple_commercial_sources_on_tenant_link" in multiple_result["blocking_invariants"]


def test_expired_promo_grant_does_not_resolve_active():
    module = _load_diagnostic_module()
    evidence = _promo_evidence(status="expired")
    evidence["promo_grants"][0]["effective_to"] = evidence["now"] - datetime.timedelta(seconds=1)
    result = module._analyze_commercial_evidence(**evidence)

    assert result["authoritative_commercial_source"] == "conflict"
    assert result["authoritative_plan_source"] == "promo_grant"
    assert "promo_grant_not_active" in result["blocking_invariants"]


def test_paid_and_demo_sources_remain_supported():
    module = _load_diagnostic_module()
    empty = {
        "group_id": 1,
        "subscription_contracts": [{"id": 8, "school_group_id": 1}],
        "demo_requests": [{"id": 9, "school_group_id": 1}],
        "promo_codes": [],
        "promo_redemptions": [],
        "promo_grants": [],
        "workspace_entitlements": [],
        "promo_assignments": [],
        "branch_entitlements": [],
        "branches": [],
    }
    paid = module._analyze_commercial_evidence(
        tenant_links=[{
            "school_group_id": 1,
            "subscription_contract_id": 8,
            "demo_request_id": None,
            "promo_grant_id": None,
        }],
        **empty,
    )
    demo = module._analyze_commercial_evidence(
        tenant_links=[{
            "school_group_id": 1,
            "subscription_contract_id": None,
            "demo_request_id": 9,
            "promo_grant_id": None,
        }],
        **empty,
    )

    assert (paid["authoritative_commercial_source"], paid["authoritative_plan_source"]) == (
        "paid_subscription",
        "subscription_contract",
    )
    assert (demo["authoritative_commercial_source"], demo["authoritative_plan_source"]) == (
        "demo",
        "demo_request",
    )
