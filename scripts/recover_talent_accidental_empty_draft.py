"""Recover a Talent Program from the Start Editing "optional clone" defect.

An empty Draft Framework can exist because the old UI let the Owner leave
"Copy the current rubric structure" unchecked when clicking Start Editing
(that checkbox has since been removed - Start Editing now always clones
automatically). This never reconstructs any Competency/KPI/Level/descriptor
by hand and never touches the source Framework or historical completed
Assessment evidence: it re-runs the existing governed clone mechanism
(`create_framework_draft(clone_from_id=...)`) against the correct source
Framework, producing a new, independent, fully populated Draft.

Usage (dry run - inspects and reports only):
    python scripts/recover_talent_accidental_empty_draft.py \
        --school-group-id 1 --program-id 11 --empty-draft-id 32

Usage (apply the recovery):
    python scripts/recover_talent_accidental_empty_draft.py \
        --school-group-id 1 --program-id 11 --empty-draft-id 32 --apply

If the accidental empty Draft's own `supersedes_framework_version_id` does
not already identify the correct source Framework, pass
`--source-framework-id` explicitly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import models  # noqa: F401 - register ORM metadata
from database import SessionLocal
from talent_program_service import (
    TalentProgramError,
    framework_payload,
    recover_accidental_empty_draft,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recover the existing Competencies/KPI/Levels/descriptors "
        "into a new Draft after an accidental empty Draft was created by "
        "Start Editing's old optional-clone checkbox."
    )
    parser.add_argument("--school-group-id", type=int, required=True)
    parser.add_argument("--program-id", type=int, required=True)
    parser.add_argument("--empty-draft-id", type=int, required=True, help="The accidental empty Draft Framework Version id.")
    parser.add_argument(
        "--source-framework-id", type=int, default=None,
        help="Override the source Framework to clone from. Defaults to the "
        "empty Draft's own supersedes_framework_version_id.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply the recovery (create the properly cloned Draft). Default is dry-run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        if not args.apply:
            # Dry run: identify without mutating anything.
            from talent_program_service import _framework  # local import: internal helper, read-only use

            empty_draft = _framework(db, args.school_group_id, args.program_id, args.empty_draft_id)
            if empty_draft is None:
                print(json.dumps({"status": "failed", "reason_code": "not_found", "detail": "empty draft not found"}, sort_keys=True))
                return 1
            source_id = args.source_framework_id or empty_draft.supersedes_framework_version_id
            source = _framework(db, args.school_group_id, args.program_id, source_id) if source_id else None
            member_count = (
                db.query(models.FrameworkCompetency)
                .filter_by(framework_version_id=empty_draft.id)
                .count()
            )
            source_member_count = (
                db.query(models.FrameworkCompetency)
                .filter_by(framework_version_id=source.id)
                .count()
                if source is not None
                else None
            )
            print(json.dumps({
                "status": "dry_run",
                "empty_draft": framework_payload(empty_draft),
                "empty_draft_competency_count": member_count,
                "resolved_source_framework": framework_payload(source) if source else None,
                "source_competency_count": source_member_count,
            }, sort_keys=True, default=str))
            return 0

        source, empty_draft, recovered = recover_accidental_empty_draft(
            db,
            school_group_id=args.school_group_id,
            program_id=args.program_id,
            empty_draft_id=args.empty_draft_id,
            source_framework_id=args.source_framework_id,
        )
        recovered_member_count = (
            db.query(models.FrameworkCompetency)
            .filter_by(framework_version_id=recovered.id)
            .count()
        )
        db.commit()
        print(json.dumps({
            "status": "recovered",
            "source_framework": framework_payload(source),
            "accidental_empty_draft": framework_payload(empty_draft),
            "recovered_draft": framework_payload(recovered),
            "recovered_competency_count": recovered_member_count,
        }, sort_keys=True, default=str))
        return 0
    except TalentProgramError as exc:
        db.rollback()
        print(json.dumps({"status": "failed", "reason_code": exc.code, "detail": exc.message}, sort_keys=True))
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
