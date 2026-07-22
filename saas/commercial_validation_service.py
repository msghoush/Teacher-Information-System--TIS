from decimal import Decimal, InvalidOperation

from commercial_entitlements import (
    BranchEntitlementMode,
    CommercialState,
    WorkspaceEntitlementSource,
    WorkspaceEntitlementStatus,
    WorkspaceEntitlementType,
)


class CommercialValidationError(ValueError):
    pass


def _coerce(enum_type, value, field_name: str):
    normalized = str(getattr(value, "value", value) or "").strip().lower()
    try:
        return enum_type(normalized)
    except ValueError as exc:
        raise CommercialValidationError(
            f"Invalid {field_name}: {normalized or 'blank'}."
        ) from exc


def validate_commercial_state(value) -> CommercialState:
    return _coerce(CommercialState, value, "commercial state")


def validate_entitlement_type(value) -> WorkspaceEntitlementType:
    return _coerce(WorkspaceEntitlementType, value, "workspace entitlement type")


def validate_entitlement_status(value) -> WorkspaceEntitlementStatus:
    return _coerce(WorkspaceEntitlementStatus, value, "workspace entitlement status")


def validate_entitlement_source(value) -> WorkspaceEntitlementSource:
    return _coerce(WorkspaceEntitlementSource, value, "workspace entitlement source")


def validate_branch_entitlement_mode(value) -> BranchEntitlementMode:
    return _coerce(BranchEntitlementMode, value, "branch entitlement mode")


def parse_entitlement_value(raw_value, value_type: str):
    normalized_type = str(value_type or "").strip().lower()
    normalized = str(raw_value or "").strip()
    if normalized_type == "boolean":
        lowered = normalized.lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
        raise CommercialValidationError("Invalid boolean entitlement value.")
    if normalized_type == "integer":
        try:
            value = int(normalized)
        except (TypeError, ValueError) as exc:
            raise CommercialValidationError("Invalid integer entitlement value.") from exc
        if value < 0:
            raise CommercialValidationError("Entitlement limits cannot be negative.")
        return value
    if normalized_type == "decimal":
        try:
            value = Decimal(normalized)
        except (InvalidOperation, ValueError) as exc:
            raise CommercialValidationError("Invalid decimal entitlement value.") from exc
        if not value.is_finite() or value < 0:
            raise CommercialValidationError("Entitlement limits must be finite and non-negative.")
        return value
    if normalized_type == "text":
        if not normalized:
            raise CommercialValidationError("Text entitlement values cannot be blank.")
        return normalized
    raise CommercialValidationError("Unsupported entitlement value type.")
