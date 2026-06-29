import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

import saas.models  # noqa: F401 - register SaaS metadata
from database import SessionLocal
from saas import models


EXPECTED_PRICE_KEYS = (
    ("starter", "monthly"),
    ("starter", "annual"),
    ("professional", "monthly"),
    ("professional", "annual"),
    ("enterprise_ai", "monthly"),
    ("enterprise_ai", "annual"),
)
EXPECTED_PLANS = {plan_code for plan_code, _interval in EXPECTED_PRICE_KEYS}
EXPECTED_INTERVALS = {interval for _plan_code, interval in EXPECTED_PRICE_KEYS}


class PaddlePriceSyncError(ValueError):
    pass


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _redact_price_id(value: str) -> str:
    cleaned = _clean_text(value)
    if len(cleaned) <= 8:
        return f"{cleaned[:4]}..."
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def load_mapping(mapping_path: str | Path) -> dict:
    path = Path(mapping_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PaddlePriceSyncError(f"Mapping file was not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PaddlePriceSyncError(f"Mapping file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise PaddlePriceSyncError("Mapping file must contain a JSON object.")
    return payload


def validate_mapping(payload: dict) -> dict[tuple[str, str], str]:
    provider = _clean_text(payload.get("provider")).lower()
    if provider != "paddle":
        raise PaddlePriceSyncError("Mapping provider must be 'paddle'.")
    environment = _clean_text(payload.get("environment"))
    if not environment:
        raise PaddlePriceSyncError("Mapping environment is required.")
    currency_code = _clean_text(payload.get("currency_code")).upper()
    if currency_code != "USD":
        raise PaddlePriceSyncError("Mapping currency_code must be USD.")

    prices = payload.get("prices")
    if not isinstance(prices, dict):
        raise PaddlePriceSyncError("Mapping prices must be an object.")

    unknown_plans = sorted(set(prices) - EXPECTED_PLANS)
    if unknown_plans:
        raise PaddlePriceSyncError(f"Unknown plan code in mapping: {', '.join(unknown_plans)}.")

    mapping: dict[tuple[str, str], str] = {}
    for plan_code, interval in EXPECTED_PRICE_KEYS:
        plan_prices = prices.get(plan_code)
        if not isinstance(plan_prices, dict):
            raise PaddlePriceSyncError(f"Missing Paddle price mappings for plan '{plan_code}'.")
        unknown_intervals = sorted(set(plan_prices) - EXPECTED_INTERVALS)
        if unknown_intervals:
            raise PaddlePriceSyncError(
                f"Unknown billing interval for plan '{plan_code}': {', '.join(unknown_intervals)}."
            )
        price_id = _clean_text(plan_prices.get(interval))
        if not price_id:
            raise PaddlePriceSyncError(f"Missing Paddle price ID for {plan_code} {interval}.")
        if not price_id.startswith("pri_"):
            raise PaddlePriceSyncError(f"Paddle price ID for {plan_code} {interval} must start with 'pri_'.")
        mapping[(plan_code, interval)] = price_id
    return mapping


def sync_paddle_price_ids(db: Session, payload: dict, *, dry_run: bool = False) -> list[dict]:
    mapping = validate_mapping(payload)
    rows = []
    for plan_code, interval in EXPECTED_PRICE_KEYS:
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.plan_code == plan_code
        ).first()
        if not plan:
            raise PaddlePriceSyncError(f"Expected subscription plan is missing: {plan_code}.")
        price_row = db.query(models.SubscriptionPlanPrice).filter(
            models.SubscriptionPlanPrice.plan_id == plan.id,
            models.SubscriptionPlanPrice.billing_interval == interval,
            models.SubscriptionPlanPrice.currency_code == "USD",
            models.SubscriptionPlanPrice.is_active == True,
        ).order_by(
            models.SubscriptionPlanPrice.plan_version.desc(),
            models.SubscriptionPlanPrice.id.desc(),
        ).first()
        if not price_row:
            raise PaddlePriceSyncError(f"Expected active USD price row is missing: {plan_code} {interval}.")
        rows.append(
            {
                "plan_code": plan_code,
                "plan_name": plan.plan_name,
                "billing_interval": interval,
                "price_row": price_row,
                "old_provider_price_id": _clean_text(price_row.provider_price_id),
                "new_provider_price_id": mapping[(plan_code, interval)],
            }
        )

    if not dry_run:
        for row in rows:
            row["price_row"].provider_price_id = row["new_provider_price_id"]
        db.commit()

    return [
        {
            "plan_code": row["plan_code"],
            "plan_name": row["plan_name"],
            "billing_interval": row["billing_interval"],
            "old_provider_price_id": row["old_provider_price_id"],
            "new_provider_price_id": row["new_provider_price_id"],
        }
        for row in rows
    ]


def print_summary(summary: list[dict], *, dry_run: bool) -> None:
    action = "Would update" if dry_run else "Updated"
    print(f"{action} {len(summary)} Paddle price mappings:")
    for row in summary:
        print(
            f"- {row['plan_code']} {row['billing_interval']} -> "
            f"{_redact_price_id(row['new_provider_price_id'])}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync TIS subscription plan prices to Paddle price IDs.")
    parser.add_argument("--mapping", required=True, help="Path to the Paddle price mapping JSON file.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview changes without updating the DB.")
    args = parser.parse_args()

    payload = load_mapping(args.mapping)
    db = SessionLocal()
    try:
        summary = sync_paddle_price_ids(db, payload, dry_run=args.dry_run)
        print_summary(summary, dry_run=args.dry_run)
        return 0
    except PaddlePriceSyncError as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
