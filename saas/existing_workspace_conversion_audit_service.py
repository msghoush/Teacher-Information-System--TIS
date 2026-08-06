"""Read-only evidence collection for a future existing-workspace conversion.

This module deliberately contains no conversion or mutation operation. Callers
own the transaction and must execute it as read-only when auditing production.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

from sqlalchemy import MetaData, Table, func, inspect, or_, select
from sqlalchemy.orm import Session

from database import Base


AUDIT_VERSION = "m4a-1"
MAX_TRAVERSED_ROWS = 10_000
MAX_TRAVERSAL_DEPTH = 8
PROVIDER_FIELD_NAMES = {
    "provider_customer_id",
    "provider_address_id",
    "provider_business_id",
    "provider_subscription_id",
    "provider_transaction_id",
    "provider_price_id",
}


def _normalize_email(value: str) -> str:
    return str(value or "").strip().casefold()


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _safe_row(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    result: dict[str, Any] = {}
    for field in fields:
        if field not in mapping:
            continue
        value = mapping[field]
        if field in PROVIDER_FIELD_NAMES:
            result[f"{field}_present"] = bool(value)
        else:
            result[field] = _serialize(value)
    return result


def _table(metadata: MetaData, name: str) -> Table | None:
    return metadata.tables.get(name)


def _column(table: Table | None, name: str):
    return table.c.get(name) if table is not None else None


def _rows(
    db: Session,
    table: Table | None,
    fields: tuple[str, ...],
    condition=None,
) -> list[dict[str, Any]]:
    if table is None:
        return []
    selected = [table.c[name] for name in fields if name in table.c]
    if not selected:
        return []
    statement = select(*selected)
    if condition is not None:
        statement = statement.where(condition)
    primary_keys = list(table.primary_key.columns)
    if primary_keys:
        statement = statement.order_by(*primary_keys)
    else:
        statement = statement.order_by(*selected)
    return [_safe_row(row, fields) for row in db.execute(statement).all()]


def _count(db: Session, table: Table | None, condition=None) -> int:
    if table is None:
        return 0
    statement = select(func.count()).select_from(table)
    if condition is not None:
        statement = statement.where(condition)
    return int(db.execute(statement).scalar_one())


def _in_condition(column, values: set[Any]):
    if not values:
        return None
    return column.in_(sorted(values, key=str))


def _matching_email_condition(table: Table | None, email: str):
    if table is None:
        return None
    clauses = []
    for name in ("email_normalized", "email", "username", "provider_email_normalized"):
        column = _column(table, name)
        if column is not None:
            clauses.append(func.lower(func.trim(column)) == email)
    return or_(*clauses) if clauses else None


def _foreign_key_children(metadata: MetaData) -> dict[str, list[tuple[Table, Any]]]:
    children: dict[str, list[tuple[Table, Any]]] = defaultdict(list)
    for child in metadata.tables.values():
        for foreign_key in child.foreign_keys:
            children[foreign_key.column.table.name].append((child, foreign_key))
    for entries in children.values():
        entries.sort(key=lambda item: (item[0].name, item[1].parent.name))
    return children


def _soft_deleted_condition(table: Table):
    clauses = []
    for name in ("deleted_at", "archived_at", "removed_at"):
        column = table.c.get(name)
        if column is not None:
            clauses.append(column.is_not(None))
    for name in ("is_deleted", "deleted"):
        column = table.c.get(name)
        if column is not None:
            clauses.append(column.is_(True))
    return or_(*clauses) if clauses else None


def _unknown_branch_foreign_keys(metadata: MetaData) -> list[dict[str, str | None]]:
    modeled = {
        (
            foreign_key.parent.table.name,
            foreign_key.parent.name,
            foreign_key.column.table.name,
            foreign_key.column.name,
        )
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name == "branches"
    }
    unknown = []
    for table in metadata.tables.values():
        for foreign_key in table.foreign_keys:
            if foreign_key.column.table.name != "branches":
                continue
            key = (
                table.name,
                foreign_key.parent.name,
                foreign_key.column.table.name,
                foreign_key.column.name,
            )
            if key not in modeled:
                unknown.append(
                    {
                        "table": table.name,
                        "column": foreign_key.parent.name,
                        "target": "branches.id",
                        "on_delete": foreign_key.ondelete,
                    }
                )
    return sorted(unknown, key=lambda item: (item["table"], item["column"]))


def _branch_dependencies(
    db: Session,
    metadata: MetaData,
    branch_id: int,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Traverse declared FK descendants of one branch without returning row data."""

    children = _foreign_key_children(metadata)
    dependencies: list[dict[str, Any]] = []
    warnings: list[str] = []
    unique_records: set[tuple[str, tuple[Any, ...]]] = set()

    def walk(
        parent: Table,
        parent_key: str,
        parent_values: set[Any],
        path: tuple[str, ...],
        depth: int,
    ) -> None:
        if depth > MAX_TRAVERSAL_DEPTH:
            warnings.append("foreign_key_traversal_depth_exceeded")
            return
        for child, foreign_key in children.get(parent.name, []):
            if child.name in path:
                warnings.append(f"foreign_key_cycle:{'->'.join(path + (child.name,))}")
                continue
            parent_column = foreign_key.column
            child_column = foreign_key.parent
            if parent_column.table.name != parent.name or parent_column.name != parent_key:
                continue
            condition = _in_condition(child_column, parent_values)
            if condition is None:
                continue
            count = _count(db, child, condition)
            if count == 0:
                continue
            child_path = path + (child.name,)
            dependency = {
                "table": child.name,
                "via_column": child_column.name,
                "path": " -> ".join(child_path),
                "direct": depth == 1,
                "record_count": count,
                "on_delete": foreign_key.ondelete,
            }
            soft_deleted_condition = _soft_deleted_condition(child)
            soft_deleted_count = (
                _count(db, child, condition & soft_deleted_condition)
                if soft_deleted_condition is not None
                else 0
            )
            dependency["soft_deleted_record_count"] = soft_deleted_count
            dependency["active_record_count"] = count - soft_deleted_count
            dependencies.append(dependency)
            if count > MAX_TRAVERSED_ROWS:
                warnings.append(f"row_limit_exceeded:{dependency['path']}")
                continue

            primary_keys = list(child.primary_key.columns)
            descendant_targets = {
                fk.column.name
                for candidate, fk in children.get(child.name, [])
                if candidate.name not in child_path
            }
            required_names = {column.name for column in primary_keys} | descendant_targets
            required_columns = [child.c[name] for name in required_names if name in child.c]
            if not required_columns:
                warnings.append(f"unkeyed_dependency:{dependency['path']}")
                continue
            matched_statement = select(*required_columns).where(condition)
            if primary_keys:
                matched_statement = matched_statement.order_by(*primary_keys)
            matched = db.execute(matched_statement).all()
            if primary_keys:
                for row in matched:
                    mapping = row._mapping
                    unique_records.add(
                        (child.name, tuple(mapping[column.name] for column in primary_keys))
                    )
            else:
                warnings.append(f"unkeyed_dependency:{dependency['path']}")

            for target_name in sorted(descendant_targets):
                values = {
                    row._mapping[target_name]
                    for row in matched
                    if row._mapping.get(target_name) is not None
                }
                if values:
                    walk(child, target_name, values, child_path, depth + 1)

    branches = _table(metadata, "branches")
    if branches is None or "id" not in branches.c:
        return [], ["branches_table_or_primary_key_unavailable"], 0
    walk(branches, "id", {branch_id}, ("branches",), 1)
    dependencies.sort(key=lambda item: (item["path"], item["via_column"]))
    return dependencies, sorted(set(warnings)), len(unique_records)


def _logical_branch_references(
    db: Session,
    metadata: MetaData,
    branch_id: int,
) -> list[dict[str, Any]]:
    """Find branch-like columns that are not protected by an FK to branches."""

    result: list[dict[str, Any]] = []
    candidates = {"branch_id", "primary_branch_id", "branch_id_snapshot"}
    for table in metadata.tables.values():
        for name in sorted(candidates.intersection(table.c.keys())):
            column = table.c[name]
            declared = any(fk.column.table.name == "branches" for fk in column.foreign_keys)
            if declared:
                continue
            try:
                count = _count(db, table, column == branch_id)
            except Exception as exc:  # reflected types can be provider-specific
                result.append(
                    {
                        "table": table.name,
                        "column": name,
                        "record_count": None,
                        "status": "unavailable",
                        "reason": type(exc).__name__,
                    }
                )
                continue
            if count:
                result.append(
                    {
                        "table": table.name,
                        "column": name,
                        "record_count": count,
                        "status": "unconstrained_reference",
                    }
                )
    return result


def _workspace_records(db: Session, metadata: MetaData, group_id: int) -> dict[str, Any]:
    inventories: dict[str, Any] = {}
    table_fields = {
        "tenant_profiles": (
            "id", "school_group_id", "website", "timezone",
            "educational_program", "school_type", "estimated_staff_users",
            "created_at", "updated_at",
        ),
        "school_group_logos": ("id", "slot_key", "label", "content_type", "created_at"),
        "role_permissions": ("id", "role", "permission_key", "is_allowed"),
        "workspace_entitlements": (
            "id", "entitlement_uuid", "entitlement_type", "status", "source",
            "payment_subscription_id", "promo_grant_id", "effective_from", "effective_to",
        ),
        "saas_demo_requests": (
            "id", "request_uuid", "pending_organization_id", "status",
            "workspace_classification_snapshot", "commercial_state_snapshot",
            "submitted_at", "approved_at", "cancelled_at",
        ),
        "demo_access_policies": (
            "id", "demo_request_id", "branch_id", "status", "starts_at", "expires_at",
        ),
        "promo_activation_sessions": (
            "id", "session_uuid", "status", "pending_organization_id",
            "saas_account_id", "created_at", "updated_at",
        ),
        "subscription_contracts": (
            "id", "pending_organization_id", "plan_id", "billing_interval",
            "contract_status", "payment_status", "billable_branch_count", "paid_at",
        ),
        "subscription_change_requests": (
            "id", "change_type", "status", "requested_quantity", "billing_interval",
            "requested_at", "effective_at", "provider_subscription_id",
        ),
        "promo_grants": (
            "id", "grant_uuid", "status", "plan_code_snapshot", "allowed_branches",
            "allowed_staff_users", "allowed_teachers", "effective_from", "effective_to",
        ),
        "promo_redemptions": (
            "id", "redemption_uuid", "status", "commercial_source", "redeemed_at",
        ),
    }
    for table_name, fields in table_fields.items():
        table = _table(metadata, table_name)
        group_column = _column(table, "school_group_id")
        inventories[table_name] = {
            "available": table is not None,
            "records": _rows(db, table, fields, group_column == group_id) if group_column is not None else [],
        }
    return inventories


def _school_group_scoped_counts(
    db: Session, metadata: MetaData, group_id: int
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in metadata.tables.values():
        column = table.c.get("school_group_id")
        if column is None:
            column = table.c.get("target_school_group_id")
        if column is None:
            continue
        count = _count(db, table, column == group_id)
        if count:
            counts[table.name] = count
    return dict(sorted(counts.items()))


def _teacher_identity_collisions(
    db: Session,
    metadata: MetaData,
    branch_ids: set[int],
) -> list[dict[str, Any]]:
    teachers = _table(metadata, "teachers")
    if teachers is None or not branch_ids or "teacher_id" not in teachers.c:
        return []
    normalized = func.lower(func.trim(teachers.c.teacher_id))
    rows = db.execute(
        select(
            normalized.label("teacher_identity"),
            func.count().label("record_count"),
        )
        .where(
            teachers.c.branch_id.in_(sorted(branch_ids)),
            teachers.c.teacher_id.is_not(None),
            func.length(func.trim(teachers.c.teacher_id)) > 0,
        )
        .group_by(normalized)
        .having(func.count() > 1)
        .order_by(normalized)
    ).all()
    return [
        {
            "teacher_identity": row.teacher_identity,
            "record_count": int(row.record_count),
        }
        for row in rows
    ]


def _setup_field_resolution(
    group: dict[str, Any] | None,
    tenant_profiles: list[dict[str, Any]],
    pending_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    group = group or {}
    tenant = tenant_profiles[0] if len(tenant_profiles) == 1 else {}
    pending = pending_rows[0] if len(pending_rows) == 1 else {}
    definitions = (
        ("display_name", True, ((group, "name", "school_groups"),)),
        ("legal_name", True, ((pending, "legal_name", "pending_organizations"),)),
        ("country_code", True, ((group, "country_code", "school_groups"), (pending, "country_code", "pending_organizations"))),
        ("country_name", False, ((group, "country_name", "school_groups"), (pending, "country_name", "pending_organizations"))),
        ("region_name", False, ((group, "region_name", "school_groups"), (pending, "region_name", "pending_organizations"))),
        ("city_name", False, ((group, "city_name", "school_groups"), (pending, "city_name", "pending_organizations"))),
        ("website", False, ((tenant, "website", "tenant_profiles"), (pending, "website", "pending_organizations"))),
        ("timezone", True, ((tenant, "timezone", "tenant_profiles"), (pending, "timezone", "pending_organizations"))),
        ("educational_program", True, ((tenant, "educational_program", "tenant_profiles"), (pending, "educational_program", "pending_organizations"))),
        ("school_type", False, ((tenant, "school_type", "tenant_profiles"), (pending, "school_type", "pending_organizations"))),
        ("phone", False, ((pending, "phone", "pending_organizations"),)),
    )
    resolved = []
    for field, required, candidates in definitions:
        value = None
        source = None
        for record, column, candidate_source in candidates:
            candidate = record.get(column)
            if candidate is not None and str(candidate).strip():
                value = candidate
                source = candidate_source
                break
        resolved.append(
            {
                "field": field,
                "value": _serialize(value),
                "source": source or "missing",
                "required_before_activation": required,
                "valid": value is not None and bool(str(value).strip()),
                "owner_confirmation_required": value is None or source == "pending_organizations",
            }
        )
    return resolved


def _snapshot_hash(report: dict[str, Any]) -> str:
    payload = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def audit_existing_workspace_conversion(
    db: Session,
    *,
    school_group_id: int,
    workspace_uuid: str,
    expected_name: str,
    owner_email: str,
) -> dict[str, Any]:
    """Return sanitized conversion evidence without changing database state."""

    normalized_email = _normalize_email(owner_email)
    expected_uuid = str(workspace_uuid or "").strip()
    expected_name = str(expected_name or "").strip()
    if school_group_id <= 0 or not expected_uuid or not expected_name or not normalized_email:
        raise ValueError("all audit identity inputs are required")

    bind = db.get_bind()
    inspector = inspect(bind)
    metadata = MetaData()
    metadata.reflect(bind=bind)
    tables = set(inspector.get_table_names())
    unknown_branch_foreign_keys = _unknown_branch_foreign_keys(metadata)
    blockers: list[str] = []
    warnings: list[str] = []

    groups = _table(metadata, "school_groups")
    group_rows = _rows(
        db,
        groups,
        (
            "id", "name", "workspace_uuid", "workspace_classification",
            "workspace_lifecycle_status", "status", "country_code", "country_name",
            "region_name", "city_name", "district_name", "neighborhood_name",
            "created_at", "updated_at",
        ),
        _column(groups, "id") == school_group_id if _column(groups, "id") is not None else None,
    )
    group = group_rows[0] if len(group_rows) == 1 else None
    if group is None:
        blockers.append("school_group_not_found")
    else:
        if str(group.get("workspace_uuid") or "") != expected_uuid:
            blockers.append("workspace_uuid_mismatch")
        if str(group.get("name") or "").strip() != expected_name:
            blockers.append("workspace_name_mismatch")

    duplicate_groups: list[dict[str, Any]] = []
    if groups is not None and "name" in groups.c:
        all_group_identities = _rows(
            db,
            groups,
            ("id", "name", "workspace_uuid", "workspace_classification", "workspace_lifecycle_status"),
        )
        expected_name_key = _normalize_name(expected_name)
        duplicate_groups = [
            row for row in all_group_identities
            if row.get("id") != school_group_id
            and _normalize_name(row.get("name")) == expected_name_key
        ]
    if duplicate_groups:
        blockers.append("duplicate_normalized_workspace_name")

    branches_table = _table(metadata, "branches")
    branches = []
    if group is not None and branches_table is not None:
        branches = _rows(
            db,
            branches_table,
            ("id", "name", "status", "school_group_id"),
            branches_table.c.school_group_id == school_group_id,
        )
    branch_reports = []
    for branch in branches:
        dependencies, traversal_warnings, unique_count = _branch_dependencies(
            db, metadata, int(branch["id"])
        )
        logical = _logical_branch_references(db, metadata, int(branch["id"]))
        branch_reports.append(
            {
                **branch,
                "dependency_record_count": unique_count,
                "soft_deleted_dependency_record_count": sum(
                    int(item["soft_deleted_record_count"])
                    for item in dependencies
                ),
                "dependencies": dependencies,
                "logical_references": logical,
                "traversal_warnings": traversal_warnings,
                "safe_for_hard_delete": not dependencies and not logical and not traversal_warnings,
            }
        )
        warnings.extend(f"branch_{branch['id']}:{item}" for item in traversal_warnings)
        if logical:
            warnings.append(f"branch_{branch['id']}:logical_references_require_review")
    if unknown_branch_foreign_keys:
        warnings.extend(
            f"unknown_branch_foreign_key:{item['table']}.{item['column']}"
            for item in unknown_branch_foreign_keys
        )

    accounts = _table(metadata, "saas_accounts")
    account_condition = _matching_email_condition(accounts, normalized_email)
    account_rows = _rows(
        db,
        accounts,
        (
            "id", "account_uuid", "email_normalized", "status", "onboarding_status",
            "account_purpose", "email_verified_at", "created_at", "updated_at",
        ),
        account_condition,
    ) if account_condition is not None else []
    if len(account_rows) > 1:
        blockers.append("duplicate_owner_saas_accounts")

    users = _table(metadata, "users")
    user_condition = _matching_email_condition(users, normalized_email)
    user_rows = _rows(
        db,
        users,
        (
            "id", "user_id", "email_normalized", "role", "position", "user_type",
            "platform_role", "access_scope", "school_group_id", "branch_id", "is_active",
            "is_internal_test_identity", "created_at", "updated_at",
        ),
        user_condition,
    ) if user_condition is not None else []
    matching_users = [row for row in user_rows if row.get("school_group_id") == school_group_id]
    foreign_users = [row for row in user_rows if row.get("school_group_id") != school_group_id]
    if len(matching_users) > 1 or foreign_users:
        blockers.append("owner_operational_identity_conflict")

    account_ids = {row["id"] for row in account_rows if row.get("id") is not None}
    user_ids = {row["id"] for row in user_rows if row.get("id") is not None}
    account_links_table = _table(metadata, "saas_account_user_links")
    link_clauses = []
    if account_links_table is not None:
        if account_ids and "saas_account_id" in account_links_table.c:
            link_clauses.append(account_links_table.c.saas_account_id.in_(account_ids))
        if user_ids and "operational_user_id" in account_links_table.c:
            link_clauses.append(account_links_table.c.operational_user_id.in_(user_ids))
        if "school_group_id" in account_links_table.c:
            link_clauses.append(account_links_table.c.school_group_id == school_group_id)
    account_links = _rows(
        db,
        account_links_table,
        (
            "id", "saas_account_id", "operational_user_id", "pending_organization_id",
            "school_group_id", "link_type", "linked_at",
        ),
        or_(*link_clauses) if link_clauses else None,
    ) if account_links_table is not None else []
    target_owner_links = [
        row for row in account_links
        if row.get("school_group_id") == school_group_id and row.get("link_type") == "tenant_owner"
    ]
    intended_owner_links = [
        row for row in target_owner_links
        if row.get("saas_account_id") in account_ids
        and row.get("operational_user_id") in user_ids
    ]
    different_owner_links = [row for row in target_owner_links if row not in intended_owner_links]
    if len(target_owner_links) > 1:
        blockers.append("multiple_tenant_owner_links")
    if different_owner_links:
        blockers.append("different_existing_tenant_owner")
    wrong_links = [row for row in account_links if row.get("school_group_id") != school_group_id]
    if wrong_links:
        blockers.append("owner_link_targets_another_workspace")
    account = account_rows[0] if len(account_rows) == 1 else None
    matching_user = matching_users[0] if len(matching_users) == 1 else None
    if account is None:
        warnings.append("owner_saas_account_absent")
        owner_resolution = "owner_absent"
    elif not account.get("email_verified_at"):
        blockers.append("owner_saas_account_unverified")
        owner_resolution = "owner_unverified"
    elif account.get("status") != "active":
        blockers.append("owner_saas_account_not_active")
        owner_resolution = "owner_restricted"
    elif wrong_links:
        owner_resolution = "owner_linked_to_another_tenant"
    elif intended_owner_links:
        owner_resolution = "owner_linked_to_same_tenant"
    elif matching_user:
        warnings.append("owner_account_link_missing")
        owner_resolution = "owner_verified_unlinked"
    else:
        warnings.append("owner_operational_user_missing")
        owner_resolution = "owner_verified_without_operational_user"

    identities_table = _table(metadata, "saas_auth_identities")
    identity_clauses = []
    identity_email_condition = _matching_email_condition(identities_table, normalized_email)
    if identity_email_condition is not None:
        identity_clauses.append(identity_email_condition)
    if identities_table is not None and account_ids and "saas_account_id" in identities_table.c:
        identity_clauses.append(identities_table.c.saas_account_id.in_(account_ids))
    identities = _rows(
        db,
        identities_table,
        ("id", "saas_account_id", "provider", "provider_email_normalized", "created_at", "updated_at"),
        or_(*identity_clauses) if identity_clauses else None,
    ) if identities_table is not None else []

    tenant_links_table = _table(metadata, "tenant_provisioning_links")
    tenant_links = _rows(
        db,
        tenant_links_table,
        (
            "id", "pending_organization_id", "subscription_contract_id", "demo_request_id",
            "promo_grant_id", "school_group_id", "owner_operational_user_id",
            "primary_branch_id", "tenant_status", "activated_at", "created_at", "updated_at",
        ),
        tenant_links_table.c.school_group_id == school_group_id
        if tenant_links_table is not None and "school_group_id" in tenant_links_table.c else None,
    )
    for link in tenant_links:
        sources = sum(
            bool(link.get(name))
            for name in ("subscription_contract_id", "demo_request_id", "promo_grant_id")
        )
        if sources != 1:
            blockers.append("tenant_link_commercial_source_is_not_exactly_one")
    if len(tenant_links) > 1:
        blockers.append("multiple_tenant_provisioning_links")

    workspace_inventory = _workspace_records(db, metadata, school_group_id)
    pending_ids = {
        row.get("pending_organization_id")
        for row in tenant_links + account_links
        if row.get("pending_organization_id") is not None
    }
    pending_table = _table(metadata, "pending_organizations")
    pending_clauses = []
    if pending_table is not None and pending_ids:
        pending_clauses.append(pending_table.c.id.in_(pending_ids))
    if (
        pending_table is not None
        and account_ids
        and "owner_saas_account_id" in pending_table.c
    ):
        pending_clauses.append(pending_table.c.owner_saas_account_id.in_(account_ids))
    pending_rows = _rows(
        db,
        pending_table,
        (
            "id", "organization_uuid", "owner_saas_account_id", "organization_name",
            "legal_name", "website", "phone", "country_code", "country_name",
            "region_name", "city_name", "district_name", "neighborhood_name",
            "timezone", "educational_program", "school_type", "status",
            "billing_status", "payment_status", "workspace_intent",
            "selected_billing_interval", "created_at", "updated_at",
        ),
        or_(*pending_clauses) if pending_clauses else None,
    ) if pending_clauses else []
    pending_ids.update(row["id"] for row in pending_rows if row.get("id") is not None)

    payment_subscriptions_table = _table(metadata, "payment_subscriptions")
    contract_ids = {
        row["id"]
        for row in workspace_inventory["subscription_contracts"]["records"]
        if row.get("id") is not None
    }
    payment_subscriptions = _rows(
        db,
        payment_subscriptions_table,
        (
            "id", "subscription_contract_id", "plan_id", "billing_interval", "currency_code",
            "quantity", "unit_amount_minor", "amount_minor", "status", "current_period_end",
            "next_billed_at", "cancel_at_period_end", "provider_subscription_id", "provider_price_id",
        ),
        payment_subscriptions_table.c.subscription_contract_id.in_(contract_ids)
        if payment_subscriptions_table is not None and contract_ids else None,
    ) if contract_ids else []

    provisioning_table = _table(metadata, "provisioning_jobs")
    provisioning_clauses = []
    if provisioning_table is not None and "target_school_group_id" in provisioning_table.c:
        provisioning_clauses.append(provisioning_table.c.target_school_group_id == school_group_id)
    if provisioning_table is not None and pending_ids and "pending_organization_id" in provisioning_table.c:
        provisioning_clauses.append(provisioning_table.c.pending_organization_id.in_(pending_ids))
    provisioning_jobs = _rows(
        db,
        provisioning_table,
        (
            "id", "pending_organization_id", "subscription_contract_id", "job_uuid",
            "job_type", "trigger_source", "job_status", "target_school_group_id",
            "tenant_provisioning_link_id", "attempt_count", "started_at", "completed_at",
            "failed_at", "created_at", "updated_at",
        ),
        or_(*provisioning_clauses) if provisioning_clauses else None,
    ) if provisioning_clauses else []

    billing_profiles_table = _table(metadata, "organization_billing_profiles")
    billing_profiles = _rows(
        db,
        billing_profiles_table,
        (
            "id", "pending_organization_id", "billing_email_normalized",
            "billing_organization_name", "country_code", "provider_sync_status",
            "provider_synced_at", "created_at", "updated_at",
        ),
        billing_profiles_table.c.pending_organization_id.in_(pending_ids)
        if billing_profiles_table is not None and pending_ids else None,
    ) if pending_ids else []
    payment_customers_table = _table(metadata, "payment_customers")
    customer_clauses = []
    if payment_customers_table is not None and pending_ids:
        customer_clauses.append(payment_customers_table.c.pending_organization_id.in_(pending_ids))
    if payment_customers_table is not None and account_ids:
        customer_clauses.append(payment_customers_table.c.saas_account_id.in_(account_ids))
    payment_customers = _rows(
        db,
        payment_customers_table,
        (
            "id", "pending_organization_id", "saas_account_id", "provider", "status",
            "provider_customer_id", "provider_address_id", "provider_business_id",
            "created_at", "updated_at",
        ),
        or_(*customer_clauses) if customer_clauses else None,
    ) if customer_clauses else []

    commercial_sources = []
    for link in tenant_links:
        if link.get("subscription_contract_id"):
            commercial_sources.append("subscription_contract")
        if link.get("demo_request_id"):
            commercial_sources.append("demo_request")
        if link.get("promo_grant_id"):
            commercial_sources.append("promo_grant")
    active_entitlements = [
        row for row in workspace_inventory["workspace_entitlements"]["records"]
        if row.get("status") == "active"
    ]
    if len(active_entitlements) > 1:
        blockers.append("multiple_active_workspace_entitlements")
    incompatible_active_entitlements = [
        row for row in active_entitlements
        if row.get("entitlement_type") != "internal_sandbox"
    ]
    active_internal_entitlements = [
        row for row in active_entitlements
        if row.get("entitlement_type") == "internal_sandbox"
    ]
    commercial_record_sets = {
        "subscription_contract": workspace_inventory["subscription_contracts"]["records"],
        "demo_request": workspace_inventory["saas_demo_requests"]["records"],
        "promo_grant": workspace_inventory["promo_grants"]["records"],
        "promo_redemption": workspace_inventory["promo_redemptions"]["records"],
    }
    unlinked_commercial_records = {
        name: len(records) for name, records in commercial_record_sets.items() if records
    }

    schema_warnings = []
    if "branches" not in tables:
        blockers.append("branches_table_unavailable")
    if not metadata.tables:
        blockers.append("database_schema_unavailable")
    for table_name in (
        "school_groups",
        "branches",
        "users",
        "saas_accounts",
        "saas_account_user_links",
        "pending_organizations",
        "tenant_provisioning_links",
        "workspace_entitlements",
        "subscription_contracts",
        "payment_subscriptions",
        "saas_demo_requests",
        "promo_grants",
        "promo_redemptions",
        "provisioning_jobs",
    ):
        if table_name not in tables:
            schema_warnings.append(f"missing_expected_table:{table_name}")
    if schema_warnings:
        blockers.append("required_schema_sections_unavailable")

    classification = group.get("workspace_classification") if group else None
    lifecycle = group.get("workspace_lifecycle_status") if group else None
    if classification != "internal_sandbox":
        blockers.append("workspace_is_not_internal_sandbox")
    elif len(active_internal_entitlements) != 1:
        blockers.append("internal_sandbox_entitlement_is_not_exactly_one")
    if lifecycle not in {"active", "suspended"}:
        blockers.append("workspace_lifecycle_not_conversion_reviewable")
    if commercial_sources:
        blockers.append("workspace_already_has_commercial_tenant_source")
    if incompatible_active_entitlements:
        blockers.append("workspace_has_non_sandbox_active_entitlement")
    if unlinked_commercial_records:
        blockers.append("workspace_has_existing_commercial_records")
    if pending_rows:
        blockers.append("existing_pending_organization_requires_review")
    if provisioning_jobs:
        blockers.append("existing_provisioning_history_requires_review")
    if payment_customers:
        warnings.append("existing_provider_customer_mapping_requires_review")

    branch_ids = {
        int(branch["id"]) for branch in branches if branch.get("id") is not None
    }
    teacher_identity_collisions = _teacher_identity_collisions(
        db, metadata, branch_ids
    )
    if teacher_identity_collisions:
        blockers.append("teacher_identity_collision")

    setup_fields = _setup_field_resolution(
        group,
        workspace_inventory["tenant_profiles"]["records"],
        pending_rows,
    )
    missing_required_setup_fields = [
        item["field"]
        for item in setup_fields
        if item["required_before_activation"] and not item["valid"]
    ]

    blockers = sorted(set(blockers))
    warnings = sorted(set(warnings + schema_warnings))
    readiness = "ready_for_conversion_design" if not blockers and not warnings else "manual_review_required"
    branch_coverage_warnings = [
        warning
        for warning in warnings
        if warning.startswith("branch_")
        or warning.startswith("unknown_branch_foreign_key:")
    ]

    recommended_archival_branch_ids = []
    if not unknown_branch_foreign_keys:
        recommended_archival_branch_ids = sorted(
            int(branch["id"])
            for branch in branch_reports
            if branch["safe_for_hard_delete"]
            and branch.get("status") is not False
        )

    report = {
        "audit_version": AUDIT_VERSION,
        "mode": "read_only",
        "target": {
            "school_group_id": school_group_id,
            "workspace_uuid": expected_uuid,
            "expected_name": expected_name,
            "owner_email_normalized": normalized_email,
        },
        "identity_validation": {
            "school_group_resolved": group is not None,
            "workspace_uuid_matches": bool(group and group.get("workspace_uuid") == expected_uuid),
            "exact_name_matches": bool(group and group.get("name") == expected_name),
            "duplicate_normalized_names": duplicate_groups,
        },
        "workspace": {
            "school_group": group,
            "branches": branch_reports,
            "branch_count": len(branch_reports),
            "records": workspace_inventory,
            "teacher_identity_collisions": teacher_identity_collisions,
            "school_group_scoped_counts": _school_group_scoped_counts(
                db, metadata, school_group_id
            ),
        },
        "owner_identity": {
            "saas_accounts": account_rows,
            "operational_users": user_rows,
            "authentication_identities": identities,
            "account_user_links": account_links,
            "tenant_owner_links": target_owner_links,
            "intended_owner_links": intended_owner_links,
            "different_owner_links": different_owner_links,
            "resolution": owner_resolution,
        },
        "tenant_and_provisioning": {
            "pending_organizations": pending_rows,
            "tenant_provisioning_links": tenant_links,
            "provisioning_jobs": provisioning_jobs,
            "commercial_sources": sorted(set(commercial_sources)),
        },
        "commercial_state": {
            "workspace_entitlements": workspace_inventory["workspace_entitlements"]["records"],
            "subscription_contracts": workspace_inventory["subscription_contracts"]["records"],
            "payment_subscriptions": payment_subscriptions,
            "promo_grants": workspace_inventory["promo_grants"]["records"],
            "promo_redemptions": workspace_inventory["promo_redemptions"]["records"],
            "billing_profiles": billing_profiles,
            "payment_customers": payment_customers,
            "existing_commercial_record_counts": unlinked_commercial_records,
        },
        "schema_coverage": {
            "reflected_table_count": len(metadata.tables),
            "branch_foreign_key_traversal": "complete" if not branch_coverage_warnings else "manual_review",
            "unknown_branch_foreign_keys": unknown_branch_foreign_keys,
            "warnings": warnings,
        },
        "setup_field_resolution": {
            "fields": setup_fields,
            "missing_required_fields": missing_required_setup_fields,
        },
        "conversion_readiness": {
            "status": readiness,
            "blockers": blockers,
            "warnings": warnings,
            "hard_delete_approved": False,
            "write_conversion_approved": False,
            "recommended_archival_branch_ids": recommended_archival_branch_ids,
        },
        "assurances": {
            "data_changed": False,
            "paddle_called": False,
            "email_sent": False,
            "conversion_performed": False,
        },
    }
    report["snapshot_hash_algorithm"] = "sha256"
    report["snapshot_hash"] = _snapshot_hash(report)
    return report
