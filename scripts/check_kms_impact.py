from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import generate_docs_pdf


ROOT = Path(__file__).resolve().parents[1]
DECLARATION_PATH = ROOT / ".kms-impact.yml"
REQUIRED_KEYS = {
    "knowledge_impact",
    "summary",
    "affected_areas",
    "kms_files_updated",
    "no_impact_reason",
    "major_change_override",
}
LIST_KEYS = {"affected_areas", "kms_files_updated"}

ROOT_MAJOR_FILES = {
    "auth.py",
    "authorization.py",
    "database.py",
    "db_migrations.py",
    "dependencies.py",
    "main.py",
    "models.py",
    "permission_registry.py",
    "role_permission_service.py",
    "tenant_integrity.py",
    "ui_shell.py",
    "requirements.txt",
}
MAJOR_PREFIXES = (
    "routers/",
    "saas/",
    "config/",
    ".github/workflows/",
)
MAJOR_TEMPLATE_PREFIXES = (
    "templates/saas/",
    "templates/system_configuration_",
    "templates/platform_",
)


@dataclass(frozen=True)
class ImpactDeclaration:
    knowledge_impact: str
    summary: str
    affected_areas: tuple[str, ...]
    kms_files_updated: tuple[str, ...]
    no_impact_reason: str
    major_change_override: str


@dataclass(frozen=True)
class ValidationResult:
    declaration: ImpactDeclaration
    changed_files: tuple[str, ...]
    major_changes: tuple[str, ...]
    errors: tuple[str, ...]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_declaration_text(text: str) -> ImpactDeclaration:
    values: dict[str, object] = {}
    active_list: str | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("-"):
            if active_list is None:
                raise ValueError(f"Line {line_number}: list item has no list field.")
            item = _unquote(stripped[1:].strip())
            if not item:
                raise ValueError(f"Line {line_number}: list items cannot be empty.")
            cast_list = values.setdefault(active_list, [])
            if not isinstance(cast_list, list):
                raise ValueError(f"Line {line_number}: invalid list structure.")
            cast_list.append(item)
            continue

        match = re.fullmatch(r"([a-z_]+)\s*:\s*(.*)", stripped)
        if not match:
            raise ValueError(f"Line {line_number}: expected 'field: value'.")
        key, raw_value = match.groups()
        if key not in REQUIRED_KEYS:
            raise ValueError(f"Line {line_number}: unknown field {key!r}.")
        if key in values:
            raise ValueError(f"Line {line_number}: duplicate field {key!r}.")
        if key in LIST_KEYS:
            if raw_value:
                raise ValueError(f"Line {line_number}: {key} must use indented list items.")
            values[key] = []
            active_list = key
        else:
            values[key] = _unquote(raw_value)
            active_list = None

    missing = REQUIRED_KEYS - values.keys()
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(sorted(missing)))
    return ImpactDeclaration(
        knowledge_impact=str(values["knowledge_impact"]).strip().lower(),
        summary=str(values["summary"]).strip(),
        affected_areas=tuple(str(item).strip() for item in values["affected_areas"]),
        kms_files_updated=tuple(str(item).strip() for item in values["kms_files_updated"]),
        no_impact_reason=str(values["no_impact_reason"]).strip(),
        major_change_override=str(values["major_change_override"]).strip().lower(),
    )


def load_declaration(path: Path = DECLARATION_PATH) -> ImpactDeclaration:
    if not path.exists():
        raise ValueError(f"KIA declaration is missing: {path.relative_to(ROOT).as_posix()}")
    return parse_declaration_text(path.read_text(encoding="utf-8"))


def is_major_change(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized in ROOT_MAJOR_FILES:
        return True
    if normalized.startswith(MAJOR_PREFIXES):
        return True
    if normalized.startswith(MAJOR_TEMPLATE_PREFIXES):
        return True
    if normalized.startswith("scripts/") and normalized not in {
        "scripts/generate_docs_pdf.py",
        "scripts/check_kms_impact.py",
    }:
        return normalized.endswith(".py")
    if normalized.startswith("tis-landing-website/src/"):
        return Path(normalized).suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}
    return False


def _git_lines(args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def changed_files(base: str | None, head: str | None) -> list[str]:
    if bool(base) != bool(head):
        raise ValueError("Both --base and --head are required when checking a Git range.")
    if base and head:
        return sorted(set(_git_lines(["diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base}...{head}"])))

    tracked = _git_lines(["diff", "--name-only", "--diff-filter=ACDMRTUXB", "HEAD"])
    staged = _git_lines(["diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB"])
    untracked = _git_lines(["ls-files", "--others", "--exclude-standard"])
    return sorted(set([*tracked, *staged, *untracked]))


def resolve_validation_range(
    event_name: str | None,
    *,
    base: str | None,
    head: str | None,
    target_ref: str | None,
) -> tuple[str | None, str | None]:
    if event_name is None:
        if target_ref:
            raise ValueError("--target-ref requires --event-name push.")
        return base, head

    event = event_name.strip().lower()
    if event == "pull_request":
        if not base or not head:
            raise ValueError("Pull-request validation requires --base and --head.")
        if target_ref:
            raise ValueError("Pull-request validation does not accept --target-ref.")
        return base, head

    if event == "push":
        if base:
            raise ValueError(
                "Push validation must use --target-ref, not the previous commit as --base."
            )
        if not target_ref or not head:
            raise ValueError("Push validation requires --target-ref and --head.")
        merge_bases = _git_lines(["merge-base", target_ref, head])
        if len(merge_bases) != 1:
            raise ValueError(
                f"Expected one merge base for {target_ref} and {head}; found {len(merge_bases)}."
            )
        return merge_bases[0], head

    raise ValueError(f"Unsupported event name: {event_name!r}.")


def validate_declaration(declaration: ImpactDeclaration, changed: list[str]) -> list[str]:
    errors: list[str] = []
    changed_set = set(changed)
    major = sorted(path for path in changed if is_major_change(path))
    changed_kms = sorted(
        path for path in changed
        if path.startswith("docs/") and path.endswith(".md")
    )

    if declaration.knowledge_impact not in {"yes", "no"}:
        errors.append("knowledge_impact must be 'yes' or 'no'.")
    if len(declaration.summary) < 12:
        errors.append("summary must describe the task in at least 12 characters.")
    if not declaration.affected_areas:
        errors.append("affected_areas must contain at least one area.")
    if declaration.major_change_override not in {"yes", "no"}:
        errors.append("major_change_override must be 'yes' or 'no'.")
    if changed and ".kms-impact.yml" not in changed_set:
        errors.append("Update .kms-impact.yml for this task; the declaration was not changed in the checked diff.")

    declared_kms = sorted(set(declaration.kms_files_updated))
    invalid_kms = [path for path in declared_kms if not (path.startswith("docs/") and path.endswith(".md"))]
    for path in invalid_kms:
        errors.append(f"kms_files_updated must contain authoritative docs/*.md paths only: {path}")
    for path in declared_kms:
        if path not in changed_set:
            errors.append(f"Declared KMS file did not change in the checked diff: {path}")
    undeclared_kms = sorted(set(changed_kms) - set(declared_kms))
    for path in undeclared_kms:
        errors.append(f"Changed KMS Markdown is missing from kms_files_updated: {path}")

    if declaration.knowledge_impact == "yes":
        if not declared_kms:
            errors.append("knowledge_impact: yes requires at least one changed authoritative KMS Markdown file.")
        if declaration.no_impact_reason:
            errors.append("no_impact_reason must be empty when knowledge_impact is yes.")
        if declaration.major_change_override == "yes":
            errors.append("major_change_override is only valid with knowledge_impact: no.")
    elif declaration.knowledge_impact == "no":
        if declared_kms:
            errors.append("knowledge_impact: no must not declare KMS Markdown updates.")
        if len(declaration.no_impact_reason) < 20:
            errors.append("knowledge_impact: no requires a specific no_impact_reason of at least 20 characters.")
        if major and declaration.major_change_override != "yes":
            errors.append(
                "Major-change paths were detected but knowledge_impact is no. "
                "Set major_change_override: yes and provide a specific explanation, or update the KMS. "
                f"Detected: {', '.join(major)}"
            )
        if not major and declaration.major_change_override == "yes":
            errors.append("major_change_override must be no when no major-change path was detected.")

    return errors


def add_range_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--event-name",
        choices=("pull_request", "push"),
        help="GitHub event type used to resolve the implementation-task boundary.",
    )
    parser.add_argument("--base", help="Base Git revision for a three-dot comparison.")
    parser.add_argument("--head", help="Head Git revision for a three-dot comparison.")
    parser.add_argument(
        "--target-ref",
        help="Target branch ref used to find the task merge base for push validation.",
    )


def evaluate_kms(
    *,
    event_name: str | None = None,
    base: str | None = None,
    head: str | None = None,
    target_ref: str | None = None,
    include_generated_artifacts: bool = True,
) -> ValidationResult:
    resolved_base, resolved_head = resolve_validation_range(
        event_name,
        base=base,
        head=head,
        target_ref=target_ref,
    )
    changed = changed_files(resolved_base, resolved_head)
    declaration = load_declaration()
    errors = validate_declaration(declaration, changed)
    if include_generated_artifacts:
        errors.extend(generate_docs_pdf.check_generated_artifacts())
    major = sorted(path for path in changed if is_major_change(path))
    return ValidationResult(
        declaration=declaration,
        changed_files=tuple(changed),
        major_changes=tuple(major),
        errors=tuple(errors),
    )


def print_validation_errors(errors: tuple[str, ...] | list[str], *, heading: str) -> None:
    print(heading)
    for error in errors:
        print(f"- {error}")
    print("Correct .kms-impact.yml, update relevant docs, regenerate the PDF/manifest, and rerun this check.")


def print_validation_summary(result: ValidationResult, *, heading: str = "KMS enforcement passed") -> None:
    print(
        f"{heading}: {len(result.changed_files)} changed file(s), "
        f"{len(result.major_changes)} major-change candidate(s), "
        f"knowledge impact={result.declaration.knowledge_impact}."
    )


def run_validation(**kwargs) -> int:
    try:
        result = evaluate_kms(**kwargs)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"KMS impact check failed: {exc}")
        return 1
    if result.errors:
        print_validation_errors(result.errors, heading="KMS enforcement failed:")
        return 1
    print_validation_summary(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate TIS KMS impact and generated artifacts.")
    add_range_arguments(parser)
    args = parser.parse_args()
    return run_validation(
        event_name=args.event_name,
        base=args.base,
        head=args.head,
        target_ref=args.target_ref,
    )


if __name__ == "__main__":
    raise SystemExit(main())
