import argparse
import json

import saas.models  # noqa: F401 - register SaaS metadata
from database import SessionLocal
from saas import draft_cleanup_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete eligible abandoned TIS SaaS draft accounts."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report eligible drafts without deleting data or writing cleanup audits.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Maximum number of inactive accounts to scan (default: 100).",
    )
    parser.add_argument(
        "--account-email",
        help="Process one normalized SaaS account email for controlled testing.",
    )
    parser.add_argument(
        "--max-inactivity-days",
        type=int,
        help="Override the deletion threshold only outside production-like environments.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = draft_cleanup_service.process_abandoned_draft_cleanup(
        SessionLocal,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        account_email=args.account_email,
        max_inactivity_days=args.max_inactivity_days,
    )
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
