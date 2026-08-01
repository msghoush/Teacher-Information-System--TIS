import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import auth
import audit
from sqlalchemy.orm import Session

from saas import models, paddle_client, service


logger = logging.getLogger(__name__)
PROVIDER = "paddle"
CUSTOMER_SAFE_SYNC_ERROR = (
    "Your billing details were saved, but Paddle could not be updated right now. "
    "Please try again before making another subscription change."
)


class BillingIdentityError(ValueError):
    pass


class BillingIdentitySyncError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        *,
        provider_step: str = "billing_identity_sync",
        provider_status_code: int | None = None,
        provider_detail: str = "",
    ):
        self.reason_code = str(reason_code or "billing_identity_sync_failed").strip()
        self.provider_step = str(provider_step or "billing_identity_sync").strip()
        self.provider_status_code = provider_status_code
        self.provider_detail = str(provider_detail or "").strip()
        super().__init__(CUSTOMER_SAFE_SYNC_ERROR)


@dataclass(frozen=True)
class BillingIdentityForm:
    billing_email: str
    billing_organization_name: str
    billing_contact_name: str
    company_number: str
    tax_identifier: str
    country_code: str
    country_name: str
    region_name: str
    city_name: str
    district_name: str
    neighborhood_name: str
    confirmed: bool
    sync_status: str


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def get_billing_profile(db: Session, organization):
    return db.query(models.OrganizationBillingProfile).filter(
        models.OrganizationBillingProfile.pending_organization_id == organization.id
    ).one_or_none()


def _primary_contact(db: Session, organization):
    return db.query(models.PendingOrganizationContact).filter(
        models.PendingOrganizationContact.pending_organization_id == organization.id,
        models.PendingOrganizationContact.is_primary.is_(True),
    ).order_by(models.PendingOrganizationContact.id.asc()).first()


def billing_identity_form(db: Session, organization, account) -> BillingIdentityForm:
    profile = get_billing_profile(db, organization)
    contact = _primary_contact(db, organization)
    contact_name = " ".join(
        part
        for part in (
            _clean(getattr(contact, "first_name", ""), 120),
            _clean(getattr(contact, "last_name", ""), 120),
        )
        if part
    )
    return BillingIdentityForm(
        billing_email=_clean(
            getattr(profile, "billing_email", "")
            or getattr(contact, "email", ""),
            180,
        ),
        billing_organization_name=_clean(
            getattr(profile, "billing_organization_name", "")
            or getattr(organization, "legal_name", "")
            or getattr(organization, "organization_name", ""),
            180,
        ),
        billing_contact_name=_clean(
            getattr(profile, "billing_contact_name", "") or contact_name,
            180,
        ),
        company_number=_clean(getattr(profile, "company_number", ""), 180),
        tax_identifier=_clean(getattr(profile, "tax_identifier", ""), 180),
        country_code=_clean(
            getattr(profile, "country_code", "")
            or getattr(organization, "country_code", ""),
            2,
        ).upper(),
        country_name=_clean(
            getattr(profile, "country_name", "")
            or getattr(organization, "country_name", ""),
            120,
        ),
        region_name=_clean(
            getattr(profile, "region_name", "")
            or getattr(organization, "region_name", ""),
            160,
        ),
        city_name=_clean(
            getattr(profile, "city_name", "")
            or getattr(organization, "city_name", ""),
            160,
        ),
        district_name=_clean(
            getattr(profile, "district_name", "")
            or getattr(organization, "district_name", ""),
            160,
        ),
        neighborhood_name=_clean(
            getattr(profile, "neighborhood_name", "")
            or getattr(organization, "neighborhood_name", ""),
            160,
        ),
        confirmed=bool(profile and profile.confirmed_at),
        sync_status=_clean(
            getattr(profile, "provider_sync_status", "not_started"), 20
        ) or "not_started",
    )


def save_billing_profile(
    db: Session,
    organization,
    *,
    billing_email: str,
    billing_organization_name: str,
    billing_contact_name: str = "",
    company_number: str = "",
    tax_identifier: str = "",
    country_code: str,
    country_name: str = "",
    region_name: str = "",
    city_name: str = "",
    district_name: str = "",
    neighborhood_name: str = "",
):
    normalized_email = auth.normalize_email(billing_email)
    if not normalized_email or not auth.is_valid_email(normalized_email):
        raise BillingIdentityError("Enter a valid billing email address.")
    organization_name = _clean(billing_organization_name, 180)
    if not organization_name:
        raise BillingIdentityError(
            "Enter the legal or billing organization or school name."
        )
    normalized_country = _clean(country_code, 2).upper()
    if len(normalized_country) != 2 or not normalized_country.isalpha():
        raise BillingIdentityError("Select a valid two-letter billing country code.")
    profile = get_billing_profile(db, organization)
    values = {
        "billing_email": _clean(billing_email, 180),
        "billing_email_normalized": normalized_email,
        "billing_organization_name": organization_name,
        "billing_contact_name": _clean(billing_contact_name, 180) or None,
        "company_number": _clean(company_number, 180) or None,
        "tax_identifier": _clean(tax_identifier, 180) or None,
        "country_code": normalized_country,
        "country_name": _clean(country_name, 120) or None,
        "region_name": _clean(region_name, 160) or None,
        "city_name": _clean(city_name, 160) or None,
        "district_name": _clean(district_name, 160) or None,
        "neighborhood_name": _clean(neighborhood_name, 160) or None,
    }
    changed = profile is None or any(
        getattr(profile, field_name, None) != value
        for field_name, value in values.items()
    )
    if profile is None:
        profile = models.OrganizationBillingProfile(
            pending_organization_id=organization.id
        )
        db.add(profile)
    for field_name, value in values.items():
        setattr(profile, field_name, value)
    profile.confirmed_at = _utcnow()
    if changed:
        profile.provider_sync_status = "pending"
        profile.provider_synced_at = None
    db.flush()
    return profile


def require_confirmed_billing_profile(db: Session, organization):
    profile = get_billing_profile(db, organization)
    if profile is None or not profile.confirmed_at:
        raise BillingIdentityError(
            "Confirm the organization billing contact before opening Secure Payment."
        )
    return profile


def require_no_unsynchronized_billing_profile(db: Session, organization):
    """Block mutations only when saved billing details are awaiting provider sync."""
    profile = get_billing_profile(db, organization)
    if profile is None:
        return None
    if str(profile.provider_sync_status or "").strip().lower() != "synced":
        raise BillingIdentityError(
            "Synchronize Billing Contact with Paddle before starting another subscription change."
        )
    return profile


def _address_details(profile) -> dict:
    return {
        "country_code": profile.country_code,
        "region": profile.region_name,
        "city": profile.city_name,
        "first_line": profile.district_name,
        "second_line": profile.neighborhood_name,
    }


def _business_details(profile, organization) -> dict:
    return {
        "name": profile.billing_organization_name,
        "company_number": profile.company_number,
        "tax_identifier": profile.tax_identifier,
        "contact_name": profile.billing_contact_name,
        "contact_email": profile.billing_email,
        "custom_data": {
            "pending_organization_uuid": str(organization.organization_uuid),
        },
    }


def _select_existing_business(rows: list[dict], profile, organization) -> dict | None:
    organization_uuid = str(organization.organization_uuid or "").strip()
    contextual = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("status") or "active").strip().lower() == "active"
        and str((row.get("custom_data") or {}).get("pending_organization_uuid") or "").strip()
        == organization_uuid
    ]
    if len(contextual) > 1:
        raise BillingIdentitySyncError("ambiguous_provider_business_mapping")
    if contextual:
        return contextual[0]
    exact = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("status") or "active").strip().lower() == "active"
        and str(row.get("name") or "").strip().casefold()
        == str(profile.billing_organization_name or "").strip().casefold()
        and any(
            str(contact.get("email") or "").strip().casefold()
            == str(profile.billing_email or "").strip().casefold()
            for contact in (row.get("contacts") or [])
            if isinstance(contact, dict)
        )
    ]
    if len(exact) > 1:
        raise BillingIdentitySyncError("ambiguous_provider_business_identity")
    return exact[0] if exact else None


def ensure_provider_billing_identity(
    db: Session, organization, payment_customer
) -> tuple[str, str]:
    profile = require_confirmed_billing_profile(db, organization)
    customer_id = str(payment_customer.provider_customer_id or "").strip()
    if not customer_id.startswith("ctm_"):
        raise BillingIdentitySyncError(
            "invalid_provider_customer_mapping",
            provider_step="customer_validation",
        )
    provider_step = "customer_update"
    try:
        if (
            str(payment_customer.email or "").strip().casefold()
            != str(profile.billing_email or "").strip().casefold()
            or str(payment_customer.name or "").strip()
            != str(profile.billing_contact_name or profile.billing_organization_name).strip()
        ):
            updated_customer = paddle_client.update_customer(
                customer_id=customer_id,
                email=profile.billing_email,
                name=profile.billing_contact_name
                or profile.billing_organization_name,
            )
            if str(updated_customer.get("id") or "").strip() != customer_id:
                raise BillingIdentitySyncError(
                    "provider_customer_update_mismatch",
                    provider_step=provider_step,
                )
            payment_customer.email = profile.billing_email_normalized
            payment_customer.name = (
                profile.billing_contact_name or profile.billing_organization_name
            )

        address_details = _address_details(profile)
        address_id = str(payment_customer.provider_address_id or "").strip()
        if address_id:
            provider_step = "address_update"
            address = paddle_client.update_customer_address(
                customer_id=customer_id,
                address_id=address_id,
                **address_details,
            )
        else:
            provider_step = "address_lookup_or_create"
            address = paddle_client.find_or_create_customer_address(
                customer_id=customer_id,
                **address_details,
            )
            address_id = str(address.get("id") or "").strip()
        if (
            not address_id.startswith("add_")
            or str(address.get("id") or "").strip() != address_id
            or str(address.get("customer_id") or customer_id).strip() != customer_id
        ):
            raise BillingIdentitySyncError(
                "provider_address_mapping_mismatch",
                provider_step=provider_step,
            )
        payment_customer.provider_address_id = address_id
        payment_customer.country_code = profile.country_code

        business_details = _business_details(profile, organization)
        business_id = str(payment_customer.provider_business_id or "").strip()
        if business_id:
            provider_step = "business_update"
            business = paddle_client.update_customer_business(
                customer_id=customer_id,
                business_id=business_id,
                **business_details,
            )
        else:
            provider_step = "business_lookup"
            existing = _select_existing_business(
                paddle_client.list_customer_businesses(customer_id=customer_id),
                profile,
                organization,
            )
            if existing:
                business_id = str(existing.get("id") or "").strip()
                provider_step = "business_update"
                business = paddle_client.update_customer_business(
                    customer_id=customer_id,
                    business_id=business_id,
                    **business_details,
                )
            else:
                provider_step = "business_create"
                business = paddle_client.create_customer_business(
                    customer_id=customer_id,
                    **business_details,
                )
                business_id = str(business.get("id") or "").strip()
        if (
            not business_id.startswith("biz_")
            or str(business.get("id") or "").strip() != business_id
            or str(business.get("customer_id") or customer_id).strip() != customer_id
        ):
            raise BillingIdentitySyncError(
                "provider_business_mapping_mismatch",
                provider_step=provider_step,
            )
        payment_customer.provider_business_id = business_id
        profile.provider_sync_status = "synced"
        profile.provider_synced_at = _utcnow()
        db.flush()
        return address_id, business_id
    except BillingIdentitySyncError as exc:
        if exc.provider_step == "billing_identity_sync":
            exc.provider_step = provider_step
        profile.provider_sync_status = "failed"
        profile.provider_synced_at = None
        raise
    except (paddle_client.PaddleAPIError, ValueError) as exc:
        profile.provider_sync_status = "failed"
        profile.provider_synced_at = None
        logger.error(
            "paddle_billing_identity_sync_failed organization_uuid=%s "
            "provider_step=%s error_code=%s status_code=%s error_type=%s detail=%s",
            str(organization.organization_uuid or ""),
            provider_step,
            str(getattr(exc, "error_code", "") or "provider_request_failed"),
            str(getattr(exc, "status_code", "") or "unavailable"),
            exc.__class__.__name__,
            str(getattr(exc, "detail", "") or "provider request failed")[:500],
            exc_info=True,
        )
        raise BillingIdentitySyncError(
            str(getattr(exc, "error_code", "") or "provider_request_failed"),
            provider_step=provider_step,
            provider_status_code=getattr(exc, "status_code", None),
            provider_detail=str(getattr(exc, "detail", "") or "")[:500],
        ) from exc


def sync_active_subscription_billing_identity(
    db: Session,
    *,
    account,
    organization,
    subscription,
    payment_customer,
) -> None:
    if (
        int(subscription.pending_organization_id) != int(organization.id)
        or int(payment_customer.pending_organization_id or 0) != int(organization.id)
        or int(payment_customer.saas_account_id) != int(account.id)
        or int(subscription.payment_customer_id or 0) != int(payment_customer.id)
    ):
        raise BillingIdentityError("Billing identity does not match this organization.")
    try:
        address_id, business_id = ensure_provider_billing_identity(
            db, organization, payment_customer
        )
        provider = paddle_client.update_subscription_billing_identity(
            subscription_id=subscription.provider_subscription_id,
            customer_id=payment_customer.provider_customer_id,
            address_id=address_id,
            business_id=business_id,
        )
        if (
            str(provider.get("id") or "").strip()
            != str(subscription.provider_subscription_id or "").strip()
            or str(provider.get("customer_id") or "").strip()
            != str(payment_customer.provider_customer_id or "").strip()
            or str(provider.get("address_id") or "").strip() != address_id
            or str(provider.get("business_id") or "").strip() != business_id
        ):
            raise BillingIdentitySyncError(
                "provider_subscription_identity_mismatch",
                provider_step="subscription_identity_update",
            )
        audit.write_audit_event(
            {
                "event_type": "organization_billing_identity_synced",
                "actor_saas_account_id": int(account.id),
                "pending_organization_id": int(organization.id),
                "payment_subscription_id": int(subscription.id),
                "result": "success",
            }
        )
    except BillingIdentitySyncError as exc:
        profile = get_billing_profile(db, organization)
        if profile is not None:
            profile.provider_sync_status = "failed"
            profile.provider_synced_at = None
        logger.warning(
            "organization_billing_identity_sync_result organization_uuid=%s "
            "result=failed provider_step=%s reason=%s status_code=%s",
            str(organization.organization_uuid or ""),
            exc.provider_step,
            exc.reason_code,
            str(exc.provider_status_code or "unavailable"),
        )
        audit.write_audit_event(
            {
                "event_type": "organization_billing_identity_sync_failed",
                "actor_saas_account_id": int(account.id),
                "pending_organization_id": int(organization.id),
                "payment_subscription_id": int(subscription.id),
                "result": "failed",
                "reason_code": exc.reason_code,
            }
        )
        raise
    except (paddle_client.PaddleAPIError, ValueError) as exc:
        profile = get_billing_profile(db, organization)
        if profile is not None:
            profile.provider_sync_status = "failed"
            profile.provider_synced_at = None
        reason_code = str(
            getattr(exc, "error_code", "") or "provider_subscription_sync_failed"
        )
        logger.error(
            "organization_billing_identity_sync_result organization_uuid=%s "
            "result=failed provider_step=subscription_identity_update reason=%s "
            "status_code=%s error_type=%s detail=%s",
            str(organization.organization_uuid or ""),
            reason_code,
            str(getattr(exc, "status_code", "") or "unavailable"),
            exc.__class__.__name__,
            str(getattr(exc, "detail", "") or "provider request failed")[:500],
            exc_info=True,
        )
        audit.write_audit_event(
            {
                "event_type": "organization_billing_identity_sync_failed",
                "actor_saas_account_id": int(account.id),
                "pending_organization_id": int(organization.id),
                "payment_subscription_id": int(subscription.id),
                "result": "failed",
                "reason_code": reason_code,
            }
        )
        raise BillingIdentitySyncError(
            reason_code,
            provider_step="subscription_identity_update",
            provider_status_code=getattr(exc, "status_code", None),
            provider_detail=str(getattr(exc, "detail", "") or "")[:500],
        ) from exc
