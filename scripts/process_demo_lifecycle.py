import argparse
import json

import models  # noqa: F401 - register operational metadata
import saas.models  # noqa: F401 - register SaaS metadata
from database import SessionLocal
from saas import demo_lifecycle_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process TIS customer-demo reminders and expiration."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report due lifecycle actions without writing any state.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Create due reminders and atomically expire due demos.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Maximum number of demo workspaces to scan (default: 100).",
    )
    parser.add_argument(
        "--request-uuid",
        help="Optionally process one SaaS demo request UUID.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = demo_lifecycle_service.process_due_demo_lifecycles(
        SessionLocal,
        dry_run=not args.apply,
        batch_size=args.batch_size,
        request_uuid=args.request_uuid,
    )
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
