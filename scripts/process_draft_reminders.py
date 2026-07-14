import argparse
import json

import saas.models  # noqa: F401 - register SaaS metadata
from database import SessionLocal
from saas import draft_reminder_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send due TIS SaaS draft-onboarding reminders."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report due reminders without sending email or writing reminder state.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Maximum number of inactive accounts to scan (default: 100).",
    )
    parser.add_argument(
        "--stage",
        choices=draft_reminder_service.REMINDER_STAGES,
        help="Optionally process only the first, second, or final due stage.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = draft_reminder_service.process_due_draft_reminders(
        SessionLocal,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        stage_filter=args.stage,
    )
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
