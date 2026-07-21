from __future__ import annotations

import argparse
import subprocess

import check_kms_impact


def _range_kwargs(args: argparse.Namespace) -> dict[str, str | None]:
    return {
        "event_name": args.event_name,
        "base": args.base,
        "head": args.head,
        "target_ref": args.target_ref,
    }


def run_check(args: argparse.Namespace) -> int:
    return check_kms_impact.run_validation(**_range_kwargs(args))


def run_sync(args: argparse.Namespace) -> int:
    try:
        preflight = check_kms_impact.evaluate_kms(
            **_range_kwargs(args),
            include_generated_artifacts=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"KMS synchronization preflight failed: {exc}")
        return 1

    if preflight.errors:
        check_kms_impact.print_validation_errors(
            preflight.errors,
            heading="KMS synchronization blocked before artifact generation:",
        )
        return 1

    try:
        output = check_kms_impact.generate_docs_pdf.build_pdf()
    except Exception as exc:
        print(f"KMS artifact generation failed: {exc}")
        return 1

    try:
        result = check_kms_impact.evaluate_kms(**_range_kwargs(args))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"KMS post-generation validation failed: {exc}")
        return 1

    if result.errors:
        check_kms_impact.print_validation_errors(
            result.errors,
            heading="KMS synchronization generated artifacts but validation failed:",
        )
        return 1

    generator = check_kms_impact.generate_docs_pdf
    print("KMS synchronization completed.")
    print(f"- Knowledge impact: {result.declaration.knowledge_impact}")
    print(f"- Affected areas: {', '.join(result.declaration.affected_areas)}")
    print(f"- Changed files checked: {len(result.changed_files)}")
    print(f"- Major-change candidates: {len(result.major_changes)}")
    print(f"- Generated PDF: {output.relative_to(generator.ROOT).as_posix()}")
    print(f"- Generated manifest: {generator.MANIFEST_PATH.relative_to(generator.ROOT).as_posix()}")
    print("- Freshness validation: passed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize or validate the TIS KMS.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser(
        "sync",
        help="Validate KIA, regenerate derived artifacts, and verify freshness.",
    )
    check_kms_impact.add_range_arguments(sync_parser)
    sync_parser.set_defaults(handler=run_sync)

    check_parser = subparsers.add_parser(
        "check",
        help="Run complete read-only KMS validation.",
    )
    check_kms_impact.add_range_arguments(check_parser)
    check_parser.set_defaults(handler=run_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
