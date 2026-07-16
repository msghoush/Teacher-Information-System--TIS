import argparse
import json

import saas.models  # noqa: F401 - register SaaS metadata
from database import SessionLocal
from saas import subscription_diagnostic_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Diagnose local TIS subscription-to-workspace relationships without calling Paddle."
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--email", help="Exact SaaS account email.")
    selector.add_argument("--organization-uuid", help="Exact pending organization UUID.")
    parser.add_argument(
        "--repair-contract-school-group",
        action="store_true",
        help="Backfill only a null contract school_group_id when every ownership and commercial relationship is exact.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        if args.repair_contract_school_group:
            result = subscription_diagnostic_service.repair_contract_school_group_link(
                db,
                email=args.email,
                organization_uuid=args.organization_uuid,
            )
            db.commit()
            result = {**result, "repair_status": "completed"}
        else:
            result = subscription_diagnostic_service.diagnose_subscription_relationships(
                db,
                email=args.email,
                organization_uuid=args.organization_uuid,
            )
            db.rollback()
            result = {**result, "repair_status": "not_requested"}
        print(json.dumps(result, sort_keys=True, default=str))
        return 0
    except subscription_diagnostic_service.SubscriptionDiagnosticError as exc:
        db.rollback()
        print(json.dumps({"status": "blocked", "reason_code": exc.code, "message": str(exc)}, sort_keys=True))
        return 2
    except Exception:
        db.rollback()
        print(json.dumps({"status": "failed", "reason_code": "unexpected_local_diagnostic_error"}, sort_keys=True))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
