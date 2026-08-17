"""TEMPORARY READ-ONLY PRODUCTION DIAGNOSTIC

This script must not be imported by runtime application code.
"""

from __future__ import annotations

import contextlib
import datetime
import decimal
import io
import json
import os
import re
import sys


TARGET_EMAIL = "mno@as.edu.sa"
TARGET_NAME = "Al-Andalus"
TARGET_DOMAINS = {"as.edu.sa", "www.as.edu.sa"}
TARGET_NAME_KEYS = {"alandalus", "alandalusschools", "andalusschools"}


def _utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime.datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _commercial_source_for_link(link):
    sources = [
        name
        for name, field in (
            ("paid_subscription", "subscription_contract_id"),
            ("demo", "demo_request_id"),
            ("promo", "promo_grant_id"),
        )
        if link.get(field) is not None
    ]
    if not sources:
        return "none"
    if len(sources) != 1:
        return "conflict"
    return sources[0]


def _analyze_commercial_evidence(
    *,
    group_id,
    tenant_links,
    subscription_contracts,
    demo_requests,
    promo_codes,
    promo_redemptions,
    promo_grants,
    workspace_entitlements,
    promo_assignments,
    branch_entitlements,
    branches,
    now=None,
):
    """Resolve sanitized audit evidence without changing application authority."""
    observed_now = _utc(now) or datetime.datetime.now(datetime.timezone.utc)
    result = {
        "authoritative_commercial_source": "none",
        "authoritative_plan_source": "none",
        "source_free_tenant_links": [],
        "source_conflict_tenant_links": [],
        "blocking_invariants": [],
        "promo_commercial_state": {
            "promo_code_id": None,
            "promo_redemption_id": None,
            "promo_grant_id": None,
            "plan_id": None,
            "plan_code": None,
            "plan_name": None,
            "allowed_branches": None,
            "allowed_staff_users": None,
            "allowed_teachers": None,
            "effective_from": None,
            "effective_to": None,
            "status": None,
            "tenant_link_matches_grant": False,
            "workspace_entitlement_matches_grant": False,
            "branch_entitlements_coherent": False,
        },
        "promo_branch_state": [],
    }
    scoped_links = [row for row in tenant_links if row.get("school_group_id") == group_id]
    for link in scoped_links:
        source = _commercial_source_for_link(link)
        if source == "none":
            result["source_free_tenant_links"].append(link)
        elif source == "conflict":
            result["source_conflict_tenant_links"].append(link)
    if not scoped_links:
        return result
    if len(scoped_links) != 1:
        result["authoritative_commercial_source"] = "conflict"
        result["blocking_invariants"].append("multiple_tenant_links_for_existing_workspace")
        return result

    link = scoped_links[0]
    link_source = _commercial_source_for_link(link)
    if link_source == "none":
        result["blocking_invariants"].append("source_free_tenant_link")
        return result
    if link_source == "conflict":
        result["authoritative_commercial_source"] = "conflict"
        result["blocking_invariants"].append("multiple_commercial_sources_on_tenant_link")
        return result
    expected_entitlement_type = {
        "paid_subscription": "paid",
        "demo": "demo",
        "promo": "promo",
    }[link_source]
    active_commercial_entitlements = [
        row
        for row in workspace_entitlements
        if row.get("school_group_id") == group_id and row.get("status") == "active"
    ]
    if len(active_commercial_entitlements) > 1:
        result["authoritative_commercial_source"] = "conflict"
        result["blocking_invariants"].append("multiple_active_commercial_entitlements")
        return result
    incompatible_active_entitlements = [
        row
        for row in workspace_entitlements
        if row.get("school_group_id") == group_id
        and row.get("status") == "active"
        and row.get("entitlement_type") != expected_entitlement_type
    ]
    if incompatible_active_entitlements:
        result["authoritative_commercial_source"] = "conflict"
        result["blocking_invariants"].append("multiple_active_commercial_entitlements")
        return result
    if link_source == "paid_subscription":
        matching_contracts = [
            row
            for row in subscription_contracts
            if row.get("id") == link.get("subscription_contract_id")
            and row.get("school_group_id") in {None, group_id}
        ]
        if len(matching_contracts) != 1:
            result["authoritative_commercial_source"] = "conflict"
            result["authoritative_plan_source"] = "subscription_contract"
            result["blocking_invariants"].append("subscription_contract_link_mismatch")
            return result
        result["authoritative_commercial_source"] = link_source
        result["authoritative_plan_source"] = "subscription_contract"
        return result
    if link_source == "demo":
        matching_demos = [
            row
            for row in demo_requests
            if row.get("id") == link.get("demo_request_id")
            and row.get("school_group_id") in {None, group_id}
        ]
        if len(matching_demos) != 1:
            result["authoritative_commercial_source"] = "conflict"
            result["authoritative_plan_source"] = "demo_request"
            result["blocking_invariants"].append("demo_request_link_mismatch")
            return result
        result["authoritative_commercial_source"] = link_source
        result["authoritative_plan_source"] = "demo_request"
        return result

    grant_id = link.get("promo_grant_id")
    matching_grants = [
        row
        for row in promo_grants
        if row.get("id") == grant_id and row.get("school_group_id") == group_id
    ]
    state = result["promo_commercial_state"]
    state["promo_grant_id"] = grant_id
    state["tenant_link_matches_grant"] = len(matching_grants) == 1
    if len(matching_grants) != 1:
        result["authoritative_commercial_source"] = "conflict"
        result["blocking_invariants"].append("promo_tenant_link_mismatch")
        return result

    grant = matching_grants[0]
    state.update(
        {
            "plan_id": grant.get("plan_id"),
            "plan_code": grant.get("plan_code_snapshot"),
            "plan_name": grant.get("plan_name_snapshot"),
            "allowed_branches": grant.get("allowed_branches"),
            "allowed_staff_users": grant.get("allowed_staff_users"),
            "allowed_teachers": grant.get("allowed_teachers"),
            "effective_from": grant.get("effective_from"),
            "effective_to": grant.get("effective_to"),
            "status": grant.get("status"),
        }
    )
    redemptions = [
        row
        for row in promo_redemptions
        if row.get("id") == grant.get("promo_redemption_id")
        and row.get("school_group_id") == group_id
    ]
    if len(redemptions) == 1:
        redemption = redemptions[0]
        state["promo_redemption_id"] = redemption.get("id")
        definitions = [
            row for row in promo_codes if row.get("id") == redemption.get("promo_code_id")
        ]
        if len(definitions) == 1:
            state["promo_code_id"] = definitions[0].get("id")
        else:
            result["blocking_invariants"].append("promo_definition_mismatch")
        immutable_fields_match = all(
            redemption.get(redemption_field) == grant.get(grant_field)
            for redemption_field, grant_field in (
                ("plan_id", "plan_id"),
                ("plan_code_snapshot", "plan_code_snapshot"),
                ("plan_name_snapshot", "plan_name_snapshot"),
                ("allowed_branches", "allowed_branches"),
                ("allowed_staff_users", "allowed_staff_users"),
                ("allowed_teachers", "allowed_teachers"),
                ("effective_from", "effective_from"),
                ("effective_to", "effective_to"),
            )
        )
        if not immutable_fields_match:
            result["blocking_invariants"].append("promo_redemption_grant_snapshot_mismatch")
    else:
        result["blocking_invariants"].append("promo_redemption_mismatch")

    effective_from = _utc(grant.get("effective_from"))
    effective_to = _utc(grant.get("effective_to"))
    grant_active = bool(
        str(grant.get("status") or "").strip().lower() == "active"
        and effective_from is not None
        and effective_to is not None
        and effective_from <= observed_now < effective_to
    )
    if not grant_active:
        result["authoritative_commercial_source"] = "conflict"
        result["authoritative_plan_source"] = "promo_grant"
        result["blocking_invariants"].append("promo_grant_not_active")
        return result
    simultaneously_active_grants = [
        row
        for row in promo_grants
        if row.get("school_group_id") == group_id
        and str(row.get("status") or "").strip().lower() == "active"
        and (_utc(row.get("effective_from")) or observed_now) <= observed_now
        and (_utc(row.get("effective_to")) or observed_now) > observed_now
    ]
    if len(simultaneously_active_grants) != 1:
        result["authoritative_commercial_source"] = "conflict"
        result["authoritative_plan_source"] = "promo_grant"
        result["blocking_invariants"].append("ambiguous_active_promo_grant")
        return result

    matching_entitlements = [
        row
        for row in workspace_entitlements
        if row.get("school_group_id") == group_id
        and row.get("promo_grant_id") == grant_id
        and row.get("entitlement_type") == "promo"
        and row.get("source") == "promo"
        and row.get("status") == "active"
    ]
    state["workspace_entitlement_matches_grant"] = len(matching_entitlements) == 1
    if len(matching_entitlements) != 1:
        result["blocking_invariants"].append("promo_workspace_entitlement_mismatch")

    entitlement_id = matching_entitlements[0].get("id") if len(matching_entitlements) == 1 else None
    assignments = {
        row.get("branch_id")
        for row in promo_assignments
        if row.get("promo_grant_id") == grant_id and row.get("school_group_id") == group_id
    }
    branch_rows = {row.get("id"): row for row in branches if row.get("id") is not None}
    entitlement_rows = [
        row
        for row in branch_entitlements
        if row.get("school_group_id") == group_id
        and row.get("workspace_entitlement_id") == entitlement_id
    ]
    entitlement_by_branch = {}
    for row in entitlement_rows:
        entitlement_by_branch.setdefault(row.get("branch_id"), []).append(row)
    branch_state = []
    allowed_branches = int(grant.get("allowed_branches") or 0)
    coherent = bool(
        entitlement_id is not None
        and assignments.issubset(branch_rows)
        and len(assignments) <= allowed_branches
    )
    for branch_id in sorted(branch_rows):
        branch = branch_rows[branch_id]
        rows = entitlement_by_branch.get(branch_id, [])
        mode = rows[0].get("entitlement_mode") if len(rows) == 1 else None
        selected = branch_id in assignments
        row_coherent = len(rows) == 1 and ((selected and mode == "active") or (not selected and mode == "inactive"))
        coherent = coherent and row_coherent
        operational_active = bool(branch.get("status") if "status" in branch else branch.get("is_active"))
        branch_state.append(
            {
                "branch_id": branch_id,
                "branch_name": branch.get("name"),
                "operational_status": operational_active,
                "selected_or_granted": selected,
                "entitlement_status": mode,
                "commercially_available": bool(operational_active and selected and mode == "active"),
            }
        )
    if set(entitlement_by_branch) - set(branch_rows):
        coherent = False
    state["branch_entitlements_coherent"] = coherent
    result["promo_branch_state"] = branch_state
    if not coherent:
        result["blocking_invariants"].append("promo_branch_entitlements_incoherent")

    if result["blocking_invariants"]:
        result["authoritative_commercial_source"] = "conflict"
    else:
        result["authoritative_commercial_source"] = "promo"
    result["authoritative_plan_source"] = "promo_grant"
    return result


def _empty_report() -> dict:
    return {
        "organization": {
            "school_group_id": None,
            "workspace_uuid": None,
            "exact_name": None,
            "workspace_lifecycle_status": None,
            "classification": None,
            "created_at": None,
            "updated_at": None,
            "branding_records": [],
            "branch_count": 0,
            "branches": [],
            "duplicate_organizations": [],
        },
        "account": {
            "email": TARGET_EMAIL,
            "saas_account": None,
            "operational_user": None,
            "authentication_identities": [],
            "verified": None,
            "account_status": None,
            "account_user_links": [],
            "owner_role": False,
            "billing_permission": False,
            "duplicate_accounts": [],
        },
        "tenant_and_provisioning": {
            "pending_organizations": [],
            "tenant_provisioning_links": [],
            "provisioning_jobs": [],
            "subscription_contracts": [],
            "demo_records": [],
            "promo_definitions": [],
            "promo_activation_sessions": [],
            "promo_redemptions": [],
            "promo_grants": [],
            "workspace_entitlements": [],
            "promo_branch_assignments": [],
            "branch_entitlements": [],
            "commercial_source": None,
            "partial_or_stale_alignment": [],
        },
        "commercial_state": {
            "classification": None,
            "plan": None,
            "billing_interval": None,
            "paid_quantity": None,
            "subscription_status": None,
            "expiration_or_period_end": None,
            "billing_profile": None,
            "payment_customer_mapping": None,
            "payment_subscription_mapping": None,
        },
        "promo_commercial_state": {
            "promo_code_id": None,
            "promo_redemption_id": None,
            "promo_grant_id": None,
            "plan_id": None,
            "plan_code": None,
            "plan_name": None,
            "allowed_branches": None,
            "allowed_staff_users": None,
            "allowed_teachers": None,
            "effective_from": None,
            "effective_to": None,
            "status": None,
            "tenant_link_matches_grant": False,
            "workspace_entitlement_matches_grant": False,
            "branch_entitlements_coherent": False,
        },
        "promo_branch_state": [],
        "authoritative_commercial_source": "none",
        "authoritative_plan_source": "none",
        "preservation_summary": {
            "branches": 0,
            "operational_users": 0,
            "teachers": 0,
            "academic_years": 0,
            "subjects": 0,
            "classes_or_sections": 0,
            "other_major_records": {},
        },
        "conflicts": {
            "duplicate_school_groups": [],
            "duplicate_accounts_or_users": [],
            "multiple_owner_links": [],
            "stale_pending_organizations": [],
            "wrong_tenant_links": [],
            "wrong_subscriptions_or_demo_records": [],
            "source_free_tenant_links": [],
            "blocking_invariants": [],
        },
        "classification": {"code": None, "label": None, "evidence": []},
        "conversion_inputs": {
            "production_school_group_id": None,
            "workspace_uuid": None,
            "intended_account_email": TARGET_EMAIL,
            "existing_saas_account_id": None,
            "existing_operational_user_id": None,
            "branch_ids": [],
            "required_commercial_source_type": None,
            "required_owner_link_type": None,
            "required_tenant_link_target": None,
            "required_invariants": [],
        },
        "safe_to_design_conversion": False,
        "notes": [],
    }


def _normalize_name(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _json_default(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    return str(value)


def _perform_audit() -> tuple[dict, int]:
    report = _empty_report()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        report["notes"].append("diagnostic_failed:DatabaseUrlMissing")
        return report, 1

    from sqlalchemy import inspect, text
    from database import SessionLocal

    notes_seen = set()
    db = SessionLocal()

    def note(message):
        if message not in notes_seen:
            report["notes"].append(message)
            notes_seen.add(message)

    try:
        connection = db.connection()
        if connection.dialect.name != "postgresql":
            raise RuntimeError("deployed_database_is_not_postgresql")

        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL statement_timeout = '60s'"))

        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        column_cache = {}
        quote = connection.dialect.identifier_preparer.quote

        def columns(table):
            if table not in tables:
                note(f"section_unavailable:missing_table:{table}")
                return set()
            if table not in column_cache:
                try:
                    column_cache[table] = {
                        row["name"] for row in inspector.get_columns(table)
                    }
                except Exception as exc:
                    note(f"section_unavailable:{table}:{type(exc).__name__}")
                    column_cache[table] = set()
            return column_cache[table]

        def fetch(table, requested, where="", params=None):
            available = columns(table)
            selected = [field for field in requested if field in available]
            if not available or not selected:
                return []
            statement = "SELECT " + ", ".join(quote(field) for field in selected)
            statement += " FROM " + quote(table)
            if where:
                statement += " WHERE " + where
            try:
                with db.begin_nested():
                    rows = db.execute(text(statement), params or {}).mappings().all()
                return [dict(row) for row in rows]
            except Exception as exc:
                note(f"section_unavailable:{table}:{type(exc).__name__}")
                return []

        def count_sql(statement, params, label):
            try:
                with db.begin_nested():
                    return int(db.execute(text(statement), params).scalar() or 0)
            except Exception as exc:
                note(f"section_unavailable:{label}:{type(exc).__name__}")
                return 0

        def safe_local_record(row, fields):
            return {field: row.get(field) for field in fields if field in row}

        groups = fetch(
            "school_groups",
            [
                "id",
                "name",
                "status",
                "workspace_uuid",
                "workspace_classification",
                "workspace_lifecycle_status",
                "created_at",
                "updated_at",
            ],
        )
        candidates = [
            row
            for row in groups
            if _normalize_name(row.get("name")) in TARGET_NAME_KEYS
        ]
        exact = [
            row
            for row in candidates
            if _normalize_name(row.get("name")) == _normalize_name(TARGET_NAME)
        ]
        organization = exact[0] if len(exact) == 1 else (
            candidates[0] if len(candidates) == 1 else None
        )
        duplicate_groups = candidates if len(candidates) > 1 else []

        if organization:
            group_id = int(organization["id"])
            report["organization"].update(
                {
                    "school_group_id": group_id,
                    "workspace_uuid": organization.get("workspace_uuid"),
                    "exact_name": organization.get("name"),
                    "workspace_lifecycle_status": organization.get(
                        "workspace_lifecycle_status"
                    ),
                    "classification": organization.get("workspace_classification"),
                    "created_at": organization.get("created_at"),
                    "updated_at": organization.get("updated_at"),
                }
            )
        else:
            group_id = None
            note("organization_not_uniquely_resolved")

        duplicate_summary = [
            safe_local_record(
                row,
                [
                    "id",
                    "name",
                    "workspace_uuid",
                    "workspace_classification",
                    "workspace_lifecycle_status",
                ],
            )
            for row in duplicate_groups
        ]
        report["organization"]["duplicate_organizations"] = duplicate_summary
        report["conflicts"]["duplicate_school_groups"] = duplicate_summary

        branches = []
        if group_id is not None:
            branches = fetch(
                "branches",
                [
                    "id",
                    "name",
                    "status",
                    "is_active",
                    "school_group_id",
                    "workspace_uuid",
                    "created_at",
                    "updated_at",
                ],
                "school_group_id = :group_id",
                {"group_id": group_id},
            )
            report["organization"]["branches"] = [
                safe_local_record(
                    row,
                    [
                        "id",
                        "name",
                        "status",
                        "is_active",
                        "school_group_id",
                        "workspace_uuid",
                    ],
                )
                for row in branches
            ]
            report["organization"]["branch_count"] = len(branches)
            logos = fetch(
                "school_group_logos",
                [
                    "id",
                    "school_group_id",
                    "slot_key",
                    "label",
                    "image_path",
                    "content_type",
                    "sort_order",
                    "created_at",
                    "updated_at",
                ],
                "school_group_id = :group_id",
                {"group_id": group_id},
            )
            report["organization"]["branding_records"] = [
                safe_local_record(
                    row,
                    [
                        "id",
                        "slot_key",
                        "label",
                        "image_path",
                        "content_type",
                        "sort_order",
                    ],
                )
                for row in logos
            ]

        branch_ids = sorted(
            int(row["id"]) for row in branches if row.get("id") is not None
        )

        account_clauses = []
        account_columns = columns("saas_accounts")
        if "email_normalized" in account_columns:
            account_clauses.append("lower(trim(email_normalized)) = :target_email")
        if "email" in account_columns:
            account_clauses.append("lower(trim(email)) = :target_email")
        account_rows = fetch(
            "saas_accounts",
            [
                "id",
                "account_uuid",
                "email_normalized",
                "status",
                "onboarding_status",
                "account_purpose",
                "email_verified_at",
                "created_at",
                "updated_at",
            ],
            " OR ".join(account_clauses) if account_clauses else "1 = 0",
            {"target_email": TARGET_EMAIL},
        )
        account = account_rows[0] if len(account_rows) == 1 else None
        account_ids = [
            int(row["id"]) for row in account_rows if row.get("id") is not None
        ]
        if account:
            report["account"]["saas_account"] = safe_local_record(
                account,
                [
                    "id",
                    "account_uuid",
                    "email_normalized",
                    "status",
                    "onboarding_status",
                    "account_purpose",
                    "email_verified_at",
                    "created_at",
                    "updated_at",
                ],
            )
            report["account"]["verified"] = bool(account.get("email_verified_at"))
            report["account"]["account_status"] = account.get("status")

        user_clauses = []
        user_columns = columns("users")
        if "email_normalized" in user_columns:
            user_clauses.append("lower(trim(email_normalized)) = :target_email")
        if "email" in user_columns:
            user_clauses.append("lower(trim(email)) = :target_email")
        if "username" in user_columns:
            user_clauses.append("lower(trim(username)) = :target_email")
        user_rows = fetch(
            "users",
            [
                "id",
                "user_id",
                "username",
                "email_normalized",
                "role",
                "position",
                "user_type",
                "platform_role",
                "access_scope",
                "school_group_id",
                "branch_id",
                "is_active",
                "is_internal_test_identity",
                "email_verified_at",
                "created_at",
                "updated_at",
            ],
            " OR ".join(user_clauses) if user_clauses else "1 = 0",
            {"target_email": TARGET_EMAIL},
        )
        matching_user = next(
            (
                row
                for row in user_rows
                if group_id is not None and row.get("school_group_id") == group_id
            ),
            user_rows[0] if len(user_rows) == 1 else None,
        )
        user_ids = [int(row["id"]) for row in user_rows if row.get("id") is not None]
        if matching_user:
            report["account"]["operational_user"] = safe_local_record(
                matching_user,
                [
                    "id",
                    "user_id",
                    "username",
                    "email_normalized",
                    "role",
                    "position",
                    "user_type",
                    "platform_role",
                    "access_scope",
                    "school_group_id",
                    "branch_id",
                    "is_active",
                    "is_internal_test_identity",
                    "email_verified_at",
                    "created_at",
                    "updated_at",
                ],
            )

        duplicates = []
        if len(account_rows) > 1:
            duplicates.extend(
                {
                    "record_type": "saas_account",
                    "id": row.get("id"),
                    "status": row.get("status"),
                }
                for row in account_rows
            )
        if len(user_rows) > 1:
            duplicates.extend(
                {
                    "record_type": "operational_user",
                    "id": row.get("id"),
                    "school_group_id": row.get("school_group_id"),
                    "role": row.get("role"),
                    "is_active": row.get("is_active"),
                }
                for row in user_rows
            )
        report["account"]["duplicate_accounts"] = duplicates
        report["conflicts"]["duplicate_accounts_or_users"] = duplicates

        identity_rows = []
        if "saas_auth_identities" in tables:
            clauses = []
            params = {"target_email": TARGET_EMAIL}
            identity_columns = columns("saas_auth_identities")
            if "provider_email_normalized" in identity_columns:
                clauses.append(
                    "lower(trim(provider_email_normalized)) = :target_email"
                )
            if account_ids and "saas_account_id" in identity_columns:
                placeholders = []
                for index, value in enumerate(account_ids):
                    key = f"account_id_{index}"
                    params[key] = value
                    placeholders.append(f":{key}")
                clauses.append("saas_account_id IN (" + ",".join(placeholders) + ")")
            identity_rows = fetch(
                "saas_auth_identities",
                [
                    "id",
                    "saas_account_id",
                    "provider",
                    "provider_email_normalized",
                    "created_at",
                    "updated_at",
                ],
                " OR ".join(clauses) if clauses else "1 = 0",
                params,
            )
        report["account"]["authentication_identities"] = identity_rows

        all_pending = fetch(
            "pending_organizations",
            [
                "id",
                "organization_uuid",
                "owner_saas_account_id",
                "status",
                "onboarding_step",
                "organization_name",
                "legal_name",
                "primary_domain",
                "workspace_intent",
                "billing_status",
                "payment_status",
                "selected_plan_id",
                "selected_billing_interval",
                "submitted_at",
                "created_at",
                "updated_at",
            ],
        )
        pending_rows = [
            row
            for row in all_pending
            if (
                row.get("owner_saas_account_id") in account_ids
                or _normalize_name(row.get("organization_name")) in TARGET_NAME_KEYS
                or _normalize_name(row.get("legal_name")) in TARGET_NAME_KEYS
                or str(row.get("primary_domain") or "").strip().lower()
                in TARGET_DOMAINS
            )
        ]
        pending_ids = [
            int(row["id"]) for row in pending_rows if row.get("id") is not None
        ]
        report["tenant_and_provisioning"]["pending_organizations"] = pending_rows

        all_account_links = fetch(
            "saas_account_user_links",
            [
                "id",
                "saas_account_id",
                "operational_user_id",
                "pending_organization_id",
                "school_group_id",
                "link_type",
                "linked_at",
                "created_at",
                "updated_at",
            ],
        )
        account_links = [
            row
            for row in all_account_links
            if (
                row.get("saas_account_id") in account_ids
                or row.get("operational_user_id") in user_ids
                or (group_id is not None and row.get("school_group_id") == group_id)
            )
        ]
        report["account"]["account_user_links"] = account_links
        owner_links = [
            row
            for row in account_links
            if (
                row.get("link_type") == "tenant_owner"
                and (group_id is None or row.get("school_group_id") == group_id)
            )
        ]
        owner_by_pending = any(
            row.get("owner_saas_account_id") in account_ids for row in pending_rows
        )
        report["account"]["owner_role"] = bool(owner_links or owner_by_pending)
        if len(owner_links) > 1:
            report["conflicts"]["multiple_owner_links"] = owner_links

        all_tenant_links = fetch(
            "tenant_provisioning_links",
            [
                "id",
                "pending_organization_id",
                "subscription_contract_id",
                "demo_request_id",
                "promo_grant_id",
                "school_group_id",
                "owner_operational_user_id",
                "primary_branch_id",
                "primary_academic_year_id",
                "tenant_status",
                "activated_at",
                "created_at",
                "updated_at",
            ],
        )
        tenant_links = [
            row
            for row in all_tenant_links
            if (
                (group_id is not None and row.get("school_group_id") == group_id)
                or row.get("pending_organization_id") in pending_ids
                or row.get("owner_operational_user_id") in user_ids
            )
        ]
        report["tenant_and_provisioning"]["tenant_provisioning_links"] = tenant_links

        all_contracts = fetch(
            "subscription_contracts",
            [
                "id",
                "pending_organization_id",
                "school_group_id",
                "plan_id",
                "billing_interval",
                "contract_status",
                "payment_status",
                "billable_branch_count",
                "base_currency_code",
                "base_amount_minor",
                "paid_at",
                "payment_provider",
                "created_at",
                "updated_at",
            ],
        )
        contracts = [
            row
            for row in all_contracts
            if (
                (group_id is not None and row.get("school_group_id") == group_id)
                or row.get("pending_organization_id") in pending_ids
            )
        ]
        report["tenant_and_provisioning"]["subscription_contracts"] = contracts
        contract_ids = [
            int(row["id"]) for row in contracts if row.get("id") is not None
        ]

        all_demos = fetch(
            "saas_demo_requests",
            [
                "id",
                "request_uuid",
                "requester_saas_account_id",
                "pending_organization_id",
                "school_group_id",
                "workspace_uuid_snapshot",
                "workspace_classification_snapshot",
                "commercial_state_snapshot",
                "status",
                "submitted_at",
                "approved_at",
                "cancelled_at",
                "created_at",
                "updated_at",
            ],
        )
        demos = [
            row
            for row in all_demos
            if (
                (group_id is not None and row.get("school_group_id") == group_id)
                or row.get("pending_organization_id") in pending_ids
                or row.get("requester_saas_account_id") in account_ids
            )
        ]
        report["tenant_and_provisioning"]["demo_records"] = demos

        plans = fetch(
            "subscription_plans",
            ["id", "plan_code", "code", "plan_name", "name", "status", "is_active", "version"],
        )
        plans_by_id = {row.get("id"): row for row in plans}
        all_promo_redemptions = fetch(
            "promo_redemptions",
            [
                "id",
                "activation_session_id",
                "promo_code_id",
                "promo_definition_version",
                "school_group_id",
                "pending_organization_id",
                "redeemed_at",
                "commercial_source",
                "status",
                "masked_promo_reference",
                "plan_id",
                "plan_code_snapshot",
                "plan_name_snapshot",
                "allowed_branches",
                "allowed_staff_users",
                "allowed_teachers",
                "effective_from",
                "effective_to",
                "grace_period_days",
                "created_at",
            ],
        )
        promo_redemptions = sorted(
            (
                row
                for row in all_promo_redemptions
                if (
                    (group_id is not None and row.get("school_group_id") == group_id)
                    or row.get("pending_organization_id") in pending_ids
                )
            ),
            key=lambda row: int(row.get("id") or 0),
        )
        promo_redemption_ids = {
            row.get("id") for row in promo_redemptions if row.get("id") is not None
        }
        promo_code_ids = {
            row.get("promo_code_id")
            for row in promo_redemptions
            if row.get("promo_code_id") is not None
        }
        all_promo_codes = fetch(
            "promo_codes",
            [
                "id",
                "code_display_prefix",
                "code_display_suffix",
                "title",
                "status",
                "definition_version",
                "subscription_plan_id",
                "max_branches",
                "max_system_users",
                "max_teachers",
                "scope_type",
                "valid_from",
                "redemption_deadline",
                "fixed_access_expires_at",
                "access_duration_days",
                "grace_period_days",
                "activated_at",
                "paused_at",
                "revoked_at",
                "created_at",
                "updated_at",
            ],
        )
        promo_codes = sorted(
            (row for row in all_promo_codes if row.get("id") in promo_code_ids),
            key=lambda row: int(row.get("id") or 0),
        )
        promo_definitions = []
        for row in promo_codes:
            plan = plans_by_id.get(row.get("subscription_plan_id"), {})
            promo_definitions.append(
                {
                    "id": row.get("id"),
                    "masked_reference": (
                        str(row.get("code_display_prefix") or "")
                        + "..."
                        + str(row.get("code_display_suffix") or "")
                    ),
                    "title": row.get("title"),
                    "status": row.get("status"),
                    "definition_version": row.get("definition_version"),
                    "subscription_plan_id": row.get("subscription_plan_id"),
                    "plan_code": plan.get("plan_code") or plan.get("code"),
                    "plan_name": plan.get("plan_name") or plan.get("name"),
                    "max_branches": row.get("max_branches"),
                    "max_system_users": row.get("max_system_users"),
                    "max_teachers": row.get("max_teachers"),
                    "scope_type": row.get("scope_type"),
                    "valid_from": row.get("valid_from"),
                    "redemption_deadline": row.get("redemption_deadline"),
                    "fixed_access_expires_at": row.get("fixed_access_expires_at"),
                    "access_duration_days": row.get("access_duration_days"),
                    "grace_period_days": row.get("grace_period_days"),
                    "activated_at": row.get("activated_at"),
                    "paused_at": row.get("paused_at"),
                    "revoked_at": row.get("revoked_at"),
                }
            )
        report["tenant_and_provisioning"]["promo_definitions"] = promo_definitions
        report["tenant_and_provisioning"]["promo_redemptions"] = promo_redemptions

        all_promo_grants = fetch(
            "promo_grants",
            [
                "id",
                "promo_redemption_id",
                "school_group_id",
                "plan_id",
                "plan_code_snapshot",
                "plan_name_snapshot",
                "source",
                "allowed_branches",
                "allowed_staff_users",
                "allowed_teachers",
                "effective_from",
                "effective_to",
                "grace_period_days",
                "status",
                "activated_at",
                "expired_at",
                "revoked_at",
                "supersedes_grant_id",
                "created_at",
            ],
        )
        promo_grants = sorted(
            (
                row
                for row in all_promo_grants
                if (
                    (group_id is not None and row.get("school_group_id") == group_id)
                    or row.get("promo_redemption_id") in promo_redemption_ids
                )
            ),
            key=lambda row: int(row.get("id") or 0),
        )
        report["tenant_and_provisioning"]["promo_grants"] = promo_grants

        activation_session_ids = {
            row.get("activation_session_id")
            for row in promo_redemptions
            if row.get("activation_session_id") is not None
        }
        promo_sessions = sorted(
            (
                row
                for row in fetch(
                "promo_activation_sessions",
                [
                    "id",
                    "activation_uuid",
                    "promo_code_id",
                    "promo_definition_version",
                    "pending_organization_id",
                    "school_group_id",
                    "context_type",
                    "status",
                    "stage",
                    "masked_promo_reference",
                    "observed_branch_count",
                    "observed_staff_users",
                    "observed_teachers",
                    "expires_at",
                    "activated_at",
                    "cancelled_at",
                    "created_at",
                    "updated_at",
                ],
                )
                if row.get("id") in activation_session_ids
            ),
            key=lambda row: int(row.get("id") or 0),
        )
        report["tenant_and_provisioning"]["promo_activation_sessions"] = promo_sessions

        all_jobs = fetch(
            "provisioning_jobs",
            [
                "id",
                "pending_organization_id",
                "subscription_contract_id",
                "job_uuid",
                "job_type",
                "trigger_source",
                "job_status",
                "target_school_group_id",
                "tenant_provisioning_link_id",
                "attempt_count",
                "started_at",
                "completed_at",
                "failed_at",
                "created_at",
                "updated_at",
            ],
        )
        jobs = [
            row
            for row in all_jobs
            if (
                (group_id is not None and row.get("target_school_group_id") == group_id)
                or row.get("pending_organization_id") in pending_ids
                or row.get("subscription_contract_id") in contract_ids
            )
        ]
        report["tenant_and_provisioning"]["provisioning_jobs"] = jobs

        all_customers = fetch(
            "payment_customers",
            [
                "id",
                "pending_organization_id",
                "saas_account_id",
                "provider",
                "provider_customer_id",
                "provider_address_id",
                "provider_business_id",
                "status",
            ],
        )
        customers = [
            row
            for row in all_customers
            if (
                row.get("pending_organization_id") in pending_ids
                or row.get("saas_account_id") in account_ids
            )
        ]
        customer = customers[0] if len(customers) == 1 else None
        if customer:
            report["commercial_state"]["payment_customer_mapping"] = {
                "local_id": customer.get("id"),
                "pending_organization_id": customer.get("pending_organization_id"),
                "saas_account_id": customer.get("saas_account_id"),
                "provider": customer.get("provider"),
                "status": customer.get("status"),
                "provider_customer_id_present": bool(
                    customer.get("provider_customer_id")
                ),
                "provider_address_id_present": bool(
                    customer.get("provider_address_id")
                ),
                "provider_business_id_present": bool(
                    customer.get("provider_business_id")
                ),
            }

        all_subscriptions = fetch(
            "payment_subscriptions",
            [
                "id",
                "pending_organization_id",
                "subscription_contract_id",
                "payment_customer_id",
                "provider",
                "provider_subscription_id",
                "provider_price_id",
                "plan_id",
                "billing_interval",
                "currency_code",
                "quantity",
                "unit_amount_minor",
                "amount_minor",
                "status",
                "current_period_start",
                "current_period_end",
                "next_billed_at",
                "cancel_at_period_end",
                "cancelled_at",
            ],
        )
        subscriptions = [
            row
            for row in all_subscriptions
            if (
                row.get("pending_organization_id") in pending_ids
                or row.get("subscription_contract_id") in contract_ids
            )
        ]
        subscription = next(
            (
                row
                for row in subscriptions
                if str(row.get("status") or "").lower() in {"active", "trialing"}
            ),
            subscriptions[0] if len(subscriptions) == 1 else None,
        )
        if subscription:
            report["commercial_state"]["payment_subscription_mapping"] = {
                "local_id": subscription.get("id"),
                "pending_organization_id": subscription.get(
                    "pending_organization_id"
                ),
                "subscription_contract_id": subscription.get(
                    "subscription_contract_id"
                ),
                "provider": subscription.get("provider"),
                "provider_subscription_id_present": bool(
                    subscription.get("provider_subscription_id")
                ),
                "provider_price_id_present": bool(
                    subscription.get("provider_price_id")
                ),
                "status": subscription.get("status"),
            }
            report["commercial_state"]["billing_interval"] = subscription.get(
                "billing_interval"
            )
            report["commercial_state"]["paid_quantity"] = subscription.get("quantity")
            report["commercial_state"]["subscription_status"] = subscription.get(
                "status"
            )
            report["commercial_state"]["expiration_or_period_end"] = (
                subscription.get("current_period_end")
                or subscription.get("cancelled_at")
            )

        plan_ids = {
            row.get("plan_id")
            for row in contracts + subscriptions
            if row.get("plan_id") is not None
        }
        relevant_plans = [row for row in plans if row.get("id") in plan_ids]
        if len(relevant_plans) == 1:
            report["commercial_state"]["plan"] = relevant_plans[0]
        elif len(relevant_plans) > 1:
            report["commercial_state"]["plan"] = {
                "status": "ambiguous",
                "local_plan_ids": sorted(plan_ids),
            }

        profiles = fetch(
            "organization_billing_profiles",
            [
                "id",
                "pending_organization_id",
                "billing_email_normalized",
                "billing_organization_name",
                "country_code",
                "provider_sync_status",
                "provider_synced_at",
                "confirmed_at",
            ],
        )
        billing_profiles = [
            row
            for row in profiles
            if row.get("pending_organization_id") in pending_ids
        ]
        if len(billing_profiles) == 1:
            profile = billing_profiles[0]
            report["commercial_state"]["billing_profile"] = {
                "id": profile.get("id"),
                "pending_organization_id": profile.get("pending_organization_id"),
                "billing_email_matches_intended_account": (
                    str(profile.get("billing_email_normalized") or "")
                    .strip()
                    .lower()
                    == TARGET_EMAIL
                ),
                "billing_organization_name": profile.get(
                    "billing_organization_name"
                ),
                "country_code": profile.get("country_code"),
                "provider_sync_status": profile.get("provider_sync_status"),
                "provider_synced_at": profile.get("provider_synced_at"),
                "confirmed_at": profile.get("confirmed_at"),
            }

        entitlements = fetch(
            "workspace_entitlements",
            [
                "id",
                "school_group_id",
                "entitlement_type",
                "status",
                "source",
                "payment_subscription_id",
                "promo_grant_id",
                "effective_from",
                "effective_to",
            ],
            "school_group_id = :group_id" if group_id is not None else "1 = 0",
            {"group_id": group_id},
        )
        report["tenant_and_provisioning"]["workspace_entitlements"] = entitlements
        if entitlements:
            note(
                "workspace_entitlements:"
                + json.dumps(entitlements, default=_json_default, separators=(",", ":"))
            )

        promo_assignments = fetch(
            "promo_grant_branch_assignments",
            ["id", "promo_grant_id", "school_group_id", "branch_id", "branch_name_snapshot", "assignment_reason", "assigned_at"],
            "school_group_id = :group_id" if group_id is not None else "1 = 0",
            {"group_id": group_id},
        )
        branch_entitlements = fetch(
            "branch_entitlements",
            ["id", "school_group_id", "branch_id", "workspace_entitlement_id", "entitlement_mode", "reason_code", "created_at", "updated_at"],
            "school_group_id = :group_id" if group_id is not None else "1 = 0",
            {"group_id": group_id},
        )
        report["tenant_and_provisioning"]["promo_branch_assignments"] = promo_assignments
        report["tenant_and_provisioning"]["branch_entitlements"] = branch_entitlements
        commercial_evidence = _analyze_commercial_evidence(
            group_id=group_id,
            tenant_links=tenant_links,
            subscription_contracts=contracts,
            demo_requests=demos,
            promo_codes=promo_codes,
            promo_redemptions=promo_redemptions,
            promo_grants=promo_grants,
            workspace_entitlements=entitlements,
            promo_assignments=promo_assignments,
            branch_entitlements=branch_entitlements,
            branches=branches,
        )
        report["commercial_state"]["classification"] = report["organization"]["classification"]
        report["authoritative_commercial_source"] = commercial_evidence["authoritative_commercial_source"]
        report["authoritative_plan_source"] = commercial_evidence["authoritative_plan_source"]
        report["promo_commercial_state"] = commercial_evidence["promo_commercial_state"]
        report["promo_branch_state"] = commercial_evidence["promo_branch_state"]
        report["tenant_and_provisioning"]["commercial_source"] = report["authoritative_commercial_source"]
        if (
            report["authoritative_plan_source"] == "promo_grant"
            and report["promo_commercial_state"]["plan_id"] is not None
        ):
            promo_plan_id = report["promo_commercial_state"]["plan_id"]
            plan = plans_by_id.get(promo_plan_id, {})
            report["commercial_state"]["plan"] = {
                "id": promo_plan_id,
                "plan_code": report["promo_commercial_state"]["plan_code"],
                "plan_name": report["promo_commercial_state"]["plan_name"],
                "catalog_plan_code": plan.get("plan_code") or plan.get("code"),
                "catalog_plan_name": plan.get("plan_name") or plan.get("name"),
                "authoritative": report["authoritative_commercial_source"] == "promo",
                "source": "promo_grant",
            }
        linked_contract_ids = {
            row.get("subscription_contract_id")
            for row in tenant_links
            if row.get("subscription_contract_id") is not None
        }
        report["tenant_and_provisioning"]["subscription_contracts"] = [
            dict(row, authoritative=row.get("id") in linked_contract_ids)
            for row in contracts
        ]
        report["conflicts"]["blocking_invariants"].extend(
            item
            for item in commercial_evidence["blocking_invariants"]
            if item not in report["conflicts"]["blocking_invariants"]
        )

        billing_permission = bool(report["account"]["owner_role"])
        if matching_user and not billing_permission:
            try:
                import permission_registry

                normalized_role = permission_registry.normalize_managed_role(
                    matching_user.get("role")
                )
                allowed = permission_registry.get_default_permissions_for_role(
                    normalized_role
                )
                permission_rows = fetch(
                    "role_permissions",
                    [
                        "id",
                        "school_group_id",
                        "role",
                        "permission_key",
                        "is_allowed",
                    ],
                )
                relevant_rows = [
                    row
                    for row in permission_rows
                    if (
                        row.get("role") == normalized_role
                        and row.get("school_group_id") in {None, group_id}
                        and row.get("permission_key")
                        == "subscriptions.manage_billing"
                    )
                ]
                for row in sorted(
                    relevant_rows,
                    key=lambda item: item.get("school_group_id") is not None,
                ):
                    if row.get("is_allowed"):
                        allowed.add("subscriptions.manage_billing")
                    else:
                        allowed.discard("subscriptions.manage_billing")
                allowed = permission_registry.constrain_role_permissions(
                    normalized_role, allowed
                )
                billing_permission = "subscriptions.manage_billing" in allowed
            except Exception as exc:
                note(f"permission_resolution_unavailable:{type(exc).__name__}")
        report["account"]["billing_permission"] = billing_permission

        def scoped_count(table):
            available = columns(table)
            if not available or group_id is None:
                return 0
            if "school_group_id" in available:
                return count_sql(
                    f"SELECT count(*) FROM {quote(table)} "
                    "WHERE school_group_id = :group_id",
                    {"group_id": group_id},
                    table,
                )
            if "branch_id" in available and branch_ids:
                return count_sql(
                    f"SELECT count(*) FROM {quote(table)} "
                    "WHERE branch_id = ANY(:branch_ids)",
                    {"branch_ids": branch_ids},
                    table,
                )
            if (
                "teacher_id" in available
                and "teachers" in tables
                and "branch_id" in columns("teachers")
                and branch_ids
            ):
                return count_sql(
                    f"SELECT count(*) FROM {quote(table)} scoped "
                    "JOIN teachers teacher ON teacher.id = scoped.teacher_id "
                    "WHERE teacher.branch_id = ANY(:branch_ids)",
                    {"branch_ids": branch_ids},
                    table,
                )
            if (
                "academic_year_id" in available
                and "academic_years" in tables
                and "school_group_id" in columns("academic_years")
            ):
                return count_sql(
                    f"SELECT count(*) FROM {quote(table)} scoped "
                    "JOIN academic_years ay ON ay.id = scoped.academic_year_id "
                    "WHERE ay.school_group_id = :group_id",
                    {"group_id": group_id},
                    table,
                )
            note(f"tenant_scope_unavailable:{table}")
            return 0

        preservation = report["preservation_summary"]
        preservation["branches"] = len(branches)
        preservation["operational_users"] = scoped_count("users")
        preservation["teachers"] = scoped_count("teachers")
        preservation["academic_years"] = scoped_count("academic_years")
        preservation["subjects"] = scoped_count("subjects")
        section_tables = [
            table
            for table in ("sections", "classes", "planning_sections")
            if table in tables
        ]
        section_counts = {table: scoped_count(table) for table in section_tables}
        preservation["classes_or_sections"] = sum(section_counts.values())
        major_tables = [
            "tenant_profiles",
            "school_group_logos",
            "branch_logos",
            "teacher_subject_allocations",
            "teacher_section_assignments",
            "observations",
            "calendar_events",
            "planning_sections",
            "timetable_entries",
            "hiring_plan_drafts",
            "visual_design_settings",
            "system_notifications",
            "branch_entitlements",
        ]
        preservation["other_major_records"] = {
            table: scoped_count(table) for table in major_tables if table in tables
        }

        correct_links = [
            row
            for row in tenant_links
            if group_id is not None and row.get("school_group_id") == group_id
        ]
        wrong_links = [
            row
            for row in tenant_links
            if group_id is not None and row.get("school_group_id") != group_id
        ]
        report["conflicts"]["wrong_tenant_links"] = wrong_links
        source_free = [
            row
            for row in tenant_links
            if (
                row.get("subscription_contract_id") is None
                and row.get("demo_request_id") is None
                and row.get("promo_grant_id") is None
            )
        ]
        report["conflicts"]["source_free_tenant_links"] = source_free
        linked_pending_ids = {
            row.get("pending_organization_id") for row in correct_links
        }
        stale_pending = [
            row for row in pending_rows if row.get("id") not in linked_pending_ids
        ]
        report["conflicts"]["stale_pending_organizations"] = stale_pending

        wrong_commercial = []
        for row in contracts:
            if group_id is not None and row.get("school_group_id") not in {
                None,
                group_id,
            }:
                wrong_commercial.append(
                    {
                        "record_type": "subscription_contract",
                        "id": row.get("id"),
                        "school_group_id": row.get("school_group_id"),
                    }
                )
        for row in demos:
            if group_id is not None and row.get("school_group_id") not in {
                None,
                group_id,
            }:
                wrong_commercial.append(
                    {
                        "record_type": "demo_request",
                        "id": row.get("id"),
                        "school_group_id": row.get("school_group_id"),
                    }
                )
        report["conflicts"]["wrong_subscriptions_or_demo_records"] = wrong_commercial

        partial = report["tenant_and_provisioning"]["partial_or_stale_alignment"]
        if organization and not pending_rows:
            partial.append("existing_workspace_has_no_pending_organization")
        if account_rows and not user_rows:
            partial.append("saas_account_has_no_operational_user")
        if user_rows and not account_rows:
            partial.append("operational_user_has_no_saas_account")
        if account_rows and not account_links:
            partial.append("saas_account_has_no_account_user_link")
        if organization and not correct_links:
            partial.append("existing_workspace_has_no_tenant_provisioning_link")
        if source_free:
            partial.append("tenant_link_has_no_commercial_source")
        if contracts and not subscriptions:
            partial.append("subscription_contract_has_no_payment_subscription")

        blocking = report["conflicts"]["blocking_invariants"]
        if len(candidates) > 1:
            blocking.append("duplicate_normalized_al_andalus_school_groups")
        if len(account_rows) > 1:
            blocking.append("duplicate_normalized_saas_accounts")
        if len(user_rows) > 1:
            blocking.append("duplicate_normalized_operational_users")
        if len(correct_links) > 1:
            blocking.append("multiple_tenant_links_for_existing_workspace")
        if len(owner_links) > 1:
            blocking.append("multiple_tenant_owner_links")
        if wrong_links:
            blocking.append("tenant_link_points_to_wrong_workspace")
        if wrong_commercial:
            blocking.append("commercial_record_points_to_wrong_workspace")
        if source_free:
            blocking.append("source_free_tenant_link")
        if commercial_evidence["source_conflict_tenant_links"]:
            blocking.append("multiple_commercial_sources_on_tenant_link")
        if organization and not organization.get("workspace_uuid"):
            blocking.append("workspace_uuid_missing")
        if organization and not organization.get("workspace_classification"):
            blocking.append("workspace_classification_missing")
        if organization and not organization.get("workspace_lifecycle_status"):
            blocking.append("workspace_lifecycle_status_missing")

        fully_aligned = bool(
            organization
            and account
            and matching_user
            and correct_links
            and report["account"]["owner_role"]
            and report["tenant_and_provisioning"]["commercial_source"]
            not in {None, "ambiguous"}
            and organization.get("workspace_uuid")
            and organization.get("workspace_classification")
            and organization.get("workspace_lifecycle_status")
        )
        legacy_empty = bool(
            organization
            and not pending_rows
            and not tenant_links
            and not contracts
            and not demos
            and not entitlements
        )
        material_conflict = bool(
            duplicate_groups
            or len(account_rows) > 1
            or len(user_rows) > 1
            or len(correct_links) > 1
            or len(owner_links) > 1
            or wrong_links
            or wrong_commercial
            or source_free
            or commercial_evidence["source_conflict_tenant_links"]
            or commercial_evidence["blocking_invariants"]
        )

        if material_conflict:
            code = "E"
            label = "Conflicting or duplicate records require cleanup"
        elif fully_aligned:
            code = "A"
            label = "Fully aligned already"
        elif organization and not account and legacy_empty:
            code = "F"
            label = "Legacy organization requires controlled conversion"
        elif organization and not account:
            code = "D"
            label = "Organization exists but SaaSAccount does not exist"
        elif account and not correct_links:
            code = "B"
            label = "Account exists but tenant link is missing"
        elif correct_links and (
            not report["account"]["owner_role"]
            or not report["account"]["billing_permission"]
        ):
            code = "C"
            label = "Tenant link exists but ownership/permissions are incomplete"
        else:
            code = "G"
            label = "Another proven state"

        evidence = []
        if organization:
            evidence.append("normalized_existing_school_group_resolved")
        if legacy_empty:
            evidence.append("no_saas_or_commercial_alignment_records_found")
        evidence.append(
            "intended_saas_account_exists"
            if account
            else "intended_saas_account_missing"
        )
        evidence.append(
            "intended_operational_user_exists"
            if matching_user
            else "intended_operational_user_missing"
        )
        evidence.append(
            "tenant_link_targets_existing_school_group"
            if correct_links
            else "tenant_link_to_existing_school_group_missing"
        )
        if material_conflict:
            evidence.append("blocking_conflict_detected")
        report["classification"] = {"code": code, "label": label, "evidence": evidence}

        workspace_classification = (
            organization.get("workspace_classification") if organization else None
        )
        if report["authoritative_commercial_source"] == "promo":
            required_source = "promo_grant"
        elif report["authoritative_commercial_source"] == "paid_subscription":
            required_source = "subscription_contract"
        elif report["authoritative_commercial_source"] == "demo":
            required_source = "demo_request"
        elif workspace_classification == "customer_paid":
            required_source = "subscription_contract_required"
        elif workspace_classification == "customer_demo":
            required_source = "approved_demo_request_required"
        elif workspace_classification == "internal_sandbox":
            required_source = (
                "architecture_decision_required_for_internal_sandbox_tenant_link"
            )
        else:
            required_source = "classification_and_commercial_source_decision_required"

        invariants = [
            "reuse_existing_school_group_without_reprovisioning",
            "preserve_all_existing_tenant_owned_records",
            "normalized_account_email_must_be_unique",
            "operational_owner_user_must_belong_to_target_school_group",
            "owner_link_type_must_be_tenant_owner",
            "exactly_one_tenant_link_may_target_the_school_group",
            "tenant_link_pending_organization_must_match_owner_account",
            "tenant_link_must_satisfy_the_current_commercial_source_constraint",
            "commercial_and_entitlement_records_must_match_workspace_classification",
            "conversion_must_be_atomic_idempotent_and_audited",
        ]
        report["conversion_inputs"].update(
            {
                "production_school_group_id": group_id,
                "workspace_uuid": (
                    organization.get("workspace_uuid") if organization else None
                ),
                "existing_saas_account_id": account.get("id") if account else None,
                "existing_operational_user_id": (
                    matching_user.get("id") if matching_user else None
                ),
                "branch_ids": branch_ids,
                "required_commercial_source_type": required_source,
                "required_owner_link_type": "tenant_owner",
                "required_tenant_link_target": (
                    {
                        "school_group_id": group_id,
                        "must_reuse_existing_school_group": True,
                    }
                    if group_id is not None
                    else None
                ),
                "required_invariants": invariants,
            }
        )
        report["safe_to_design_conversion"] = bool(
            code == "F"
            and organization
            and not material_conflict
            and len(candidates) == 1
            and all(row.get("school_group_id") == group_id for row in branches)
        )
        db.rollback()
        return report, 0
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        report["notes"].append(f"diagnostic_failed:{type(exc).__name__}")
        return report, 1
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


def main() -> int:
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        report, exit_code = _perform_audit()
    sys.stdout.write(json.dumps(report, default=_json_default, indent=2) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
