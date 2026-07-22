from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_kms_impact  # noqa: E402
import kms  # noqa: E402

generate_docs_pdf = check_kms_impact.generate_docs_pdf


def _declaration(**overrides):
    values = {
        "knowledge_impact": "yes",
        "summary": "Update subscription lifecycle behavior.",
        "affected_areas": ("subscriptions",),
        "kms_files_updated": ("docs/CHANGE_HISTORY.md",),
        "no_impact_reason": "",
        "major_change_override": "no",
    }
    values.update(overrides)
    return check_kms_impact.ImpactDeclaration(**values)


def _validation_result(*, errors=()):
    return check_kms_impact.ValidationResult(
        declaration=_declaration(),
        changed_files=(".kms-impact.yml", "docs/CHANGE_HISTORY.md"),
        major_changes=(),
        errors=tuple(errors),
    )


def _command_args():
    return kms.build_parser().parse_args(["check"])


def _write_markdown(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def test_parse_declaration_supports_the_repository_schema():
    declaration = check_kms_impact.parse_declaration_text(
        """
knowledge_impact: yes
summary: Update subscription lifecycle behavior.
affected_areas:
  - subscriptions
kms_files_updated:
  - docs/CHANGE_HISTORY.md
no_impact_reason:
major_change_override: no
"""
    )

    assert declaration.knowledge_impact == "yes"
    assert declaration.affected_areas == ("subscriptions",)
    assert declaration.kms_files_updated == ("docs/CHANGE_HISTORY.md",)


def test_major_change_classification_covers_core_behavior_paths():
    assert check_kms_impact.is_major_change("main.py")
    assert check_kms_impact.is_major_change("saas/subscription_lifecycle_service.py")
    assert check_kms_impact.is_major_change("routers/academic_calendar.py")
    assert check_kms_impact.is_major_change(".github/workflows/deploy-on-master.yml")
    assert check_kms_impact.is_major_change("tis-landing-website/src/app/page.tsx")
    assert not check_kms_impact.is_major_change("docs/README.md")
    assert not check_kms_impact.is_major_change("tis-landing-website/src/app/globals.css")


def test_impact_yes_requires_changed_declared_markdown():
    errors = check_kms_impact.validate_declaration(
        _declaration(),
        [".kms-impact.yml", "main.py"],
    )

    assert any("Declared KMS file did not change" in error for error in errors)


def test_major_change_no_impact_requires_explicit_override_and_reason():
    declaration = _declaration(
        knowledge_impact="no",
        kms_files_updated=(),
        no_impact_reason="Internal rename only; behavior and public contracts are unchanged.",
    )
    changed = [".kms-impact.yml", "saas/service.py"]

    errors = check_kms_impact.validate_declaration(declaration, changed)
    assert any("major_change_override" in error for error in errors)

    overridden = _declaration(
        knowledge_impact="no",
        kms_files_updated=(),
        no_impact_reason="Internal rename only; behavior and public contracts are unchanged.",
        major_change_override="yes",
    )
    assert check_kms_impact.validate_declaration(overridden, changed) == []


def test_changed_kms_markdown_must_be_declared():
    errors = check_kms_impact.validate_declaration(
        _declaration(),
        [".kms-impact.yml", "docs/CHANGE_HISTORY.md", "docs/PROJECT_STATE.md"],
    )

    assert any("docs/PROJECT_STATE.md" in error for error in errors)


def test_markdown_hash_is_identical_for_lf_and_crlf(tmp_path):
    lf_source = tmp_path / "lf.md"
    crlf_source = tmp_path / "crlf.md"
    lf_source.write_bytes(b"# Heading\n\n- one\n- two\n")
    crlf_source.write_bytes(b"# Heading\r\n\r\n- one\r\n- two\r\n")

    assert generate_docs_pdf._source_hash(lf_source) == generate_docs_pdf._source_hash(crlf_source)


def test_markdown_hash_changes_when_text_changes(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Current state\n", encoding="utf-8", newline="\n")
    original_hash = generate_docs_pdf._source_hash(source)

    source.write_text("# Changed state\n", encoding="utf-8", newline="\n")

    assert generate_docs_pdf._source_hash(source) != original_hash


def test_source_catalog_accepts_front_matter_and_h1_titles(tmp_path, monkeypatch):
    front_matter = _write_markdown(
        tmp_path / "docs" / "engineering" / "guide.md",
        "---\ntitle: Engineering Guide\n---\n\nBody.\n",
    )
    h1_only = _write_markdown(
        tmp_path / "docs" / "supporting.md",
        "# Supporting Guide\n\nBody.\n",
    )
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)

    assert generate_docs_pdf._validate_source_catalog([front_matter, h1_only]) == []


@pytest.mark.parametrize("title", ["", "TBD", "Untitled", "!"])
def test_source_catalog_rejects_missing_or_unusable_titles(tmp_path, monkeypatch, title):
    heading = f"# {title}\n" if title else "Body without a title.\n"
    source = _write_markdown(tmp_path / "docs" / "source.md", heading)
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)

    assert generate_docs_pdf._validate_source_catalog([source]) == [
        "Included Markdown source has no usable title: docs/source.md"
    ]


def test_source_catalog_rejects_unapproved_or_mismatched_taxonomy(tmp_path, monkeypatch):
    source = _write_markdown(
        tmp_path / "docs" / "engineering" / "guide.md",
        "---\n"
        "title: Engineering Guide\n"
        "category: core\n"
        "module: unknown-module\n"
        "---\n\n"
        "Body.\n",
    )
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)

    errors = generate_docs_pdf._validate_source_catalog([source])

    assert "Source category 'core' does not match path category 'engineering': docs/engineering/guide.md" in errors
    assert "Source declares an unapproved module 'unknown-module': docs/engineering/guide.md" in errors
    assert "Source uses an unapproved module 'unknown-module': docs/engineering/guide.md" in errors

    source.write_text(
        source.read_text(encoding="utf-8").replace("category: core", "category: forbidden"),
        encoding="utf-8",
    )
    errors = generate_docs_pdf._validate_source_catalog([source])
    assert "Source declares an unapproved category 'forbidden': docs/engineering/guide.md" in errors


def test_navigation_validation_accepts_listed_relative_docs_links(tmp_path, monkeypatch):
    navigation = _write_markdown(
        tmp_path / "docs" / "KMS_NAVIGATION.md",
        "# Navigation\n\n[Guide](engineering/guide.md#overview)\n",
    )
    guide = _write_markdown(
        tmp_path / "docs" / "engineering" / "guide.md",
        "# Guide\n\n## Overview\n",
    )
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)

    assert generate_docs_pdf._validate_navigation_links(
        navigation,
        ["docs/KMS_NAVIGATION.md", "docs/engineering/guide.md"],
    ) == []


@pytest.mark.parametrize(
    ("destination", "create_target", "listed_target", "expected"),
    [
        ("https://example.com/guide.md", False, False, "must be a relative docs path"),
        ("../AGENTS.md", True, False, "leaves docs/"),
        ("missing.md", False, False, "points to a missing document"),
        ("unlisted.md", True, False, "points to an unlisted authoritative document"),
        ("asset.txt", True, True, "is not a Markdown document"),
    ],
)
def test_navigation_validation_rejects_invalid_targets(
    tmp_path,
    monkeypatch,
    destination,
    create_target,
    listed_target,
    expected,
):
    navigation = _write_markdown(
        tmp_path / "docs" / "KMS_NAVIGATION.md",
        f"# Navigation\n\n[Target]({destination})\n",
    )
    target_path = tmp_path / "docs" / destination
    if destination == "../AGENTS.md":
        target_path = tmp_path / "AGENTS.md"
    if create_target:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text("# Target\n", encoding="utf-8")
    listed = ["docs/KMS_NAVIGATION.md"]
    if listed_target:
        listed.append(target_path.relative_to(tmp_path).as_posix())
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)

    errors = generate_docs_pdf._validate_navigation_links(navigation, listed)

    assert any(expected in error for error in errors)


def test_changed_markdown_fails_generated_artifact_freshness_check(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    source = docs_dir / "source.md"
    source.write_text("# Approved state\n", encoding="utf-8", newline="\n")
    pdf = tmp_path / "booklet.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documentation_version": generate_docs_pdf.DOCUMENTATION_VERSION,
                "included_source_files": [
                    {
                        "path": "docs/source.md",
                        "sha256": generate_docs_pdf._source_hash(source),
                        "pdf_page": 1,
                    }
                ],
                "pdf_sha256": generate_docs_pdf._source_hash(pdf),
                "pdf_size_bytes": pdf.stat().st_size,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)
    monkeypatch.setattr(generate_docs_pdf, "SOURCE_DOCS", [source])
    monkeypatch.setattr(generate_docs_pdf, "OUTPUT_PATH", pdf)
    monkeypatch.setattr(generate_docs_pdf, "MANIFEST_PATH", manifest)

    assert generate_docs_pdf.check_generated_artifacts() == []

    source.write_text("# Changed state\n", encoding="utf-8", newline="\n")

    assert "Booklet source is stale: docs/source.md" in (
        generate_docs_pdf.check_generated_artifacts()
    )


def test_source_path_normalization_matches_windows_and_posix_styles():
    windows_path = r"docs\marketing\landing_page_source_of_truth.md"
    posix_path = "./docs/marketing/landing_page_source_of_truth.md"

    assert generate_docs_pdf._normalize_source_path(windows_path) == (
        generate_docs_pdf._normalize_source_path(posix_path)
    )


def test_source_list_comparison_is_cross_platform_and_order_strict():
    expected = [
        "docs/README.md",
        "docs/history/README.md",
        "docs/history/subscriptions/README.md",
    ]
    windows_manifest = [
        r"docs\README.md",
        r"docs\history\README.md",
        r"docs\history\subscriptions\README.md",
    ]

    assert generate_docs_pdf._compare_source_paths(expected, windows_manifest) == []

    reordered = [windows_manifest[0], windows_manifest[2], windows_manifest[1]]
    errors = generate_docs_pdf._compare_source_paths(expected, reordered)
    assert errors == ["Manifest source order does not match the deterministic generator source order."]


def test_source_list_comparison_rejects_missing_and_unexpected_sources():
    expected = ["docs/README.md", "docs/PROJECT_STATE.md"]
    actual = ["docs/README.md", "docs/UNEXPECTED.md"]

    errors = generate_docs_pdf._compare_source_paths(expected, actual)

    assert "Manifest is missing an expected source: docs/PROJECT_STATE.md" in errors
    assert "Manifest contains an unexpected source: docs/UNEXPECTED.md" in errors


def test_pdf_navigation_keys_are_stable_and_path_specific():
    first = generate_docs_pdf._bookmark_key("source", "docs/README.md")
    repeated = generate_docs_pdf._bookmark_key("source", "docs/README.md")
    second = generate_docs_pdf._bookmark_key("source", "docs/PROJECT_STATE.md")

    assert first == repeated
    assert first != second
    assert first.startswith("source-")


def test_pdf_build_records_strict_source_pages_and_outline_catalog(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    first = docs_dir / "first.md"
    second = docs_dir / "second.md"
    first.write_text(
        "---\ntitle: First Document\n---\n\n# First Document\n\n## First Topic\n\nBody.\n",
        encoding="utf-8",
    )
    second.write_text(
        "---\ntitle: Second Document\n---\n\n# Second Document\n\n## Second Topic\n\nBody.\n",
        encoding="utf-8",
    )
    output = tmp_path / "static" / "docs" / "booklet.pdf"
    manifest_path = tmp_path / "static" / "docs" / "manifest.json"
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)
    monkeypatch.setattr(generate_docs_pdf, "SOURCE_DOCS", [first, second])
    monkeypatch.setattr(generate_docs_pdf, "OUTPUT_PATH", output)
    monkeypatch.setattr(generate_docs_pdf, "MANIFEST_PATH", manifest_path)

    assert generate_docs_pdf.build_pdf() == output

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = [item["pdf_page"] for item in manifest["included_source_files"]]
    assert pages[0] >= 4
    assert pages == sorted(set(pages))
    assert b"/Outlines" in output.read_bytes()
    assert generate_docs_pdf.check_generated_artifacts() == []


@pytest.mark.parametrize("pdf_page", [None, 0, -1, True, "1"])
def test_freshness_check_rejects_invalid_pdf_page_metadata(tmp_path, monkeypatch, pdf_page):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    source = docs_dir / "source.md"
    source.write_text("# Source\n", encoding="utf-8")
    pdf = tmp_path / "booklet.pdf"
    pdf.write_bytes(b"pdf")
    manifest = tmp_path / "manifest.json"
    source_metadata = {
        "path": "docs/source.md",
        "sha256": generate_docs_pdf._source_hash(source),
    }
    if pdf_page is not None:
        source_metadata["pdf_page"] = pdf_page
    manifest.write_text(
        json.dumps(
            {
                "documentation_version": generate_docs_pdf.DOCUMENTATION_VERSION,
                "included_source_files": [source_metadata],
                "pdf_sha256": generate_docs_pdf._source_hash(pdf),
                "pdf_size_bytes": pdf.stat().st_size,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)
    monkeypatch.setattr(generate_docs_pdf, "SOURCE_DOCS", [source])
    monkeypatch.setattr(generate_docs_pdf, "OUTPUT_PATH", pdf)
    monkeypatch.setattr(generate_docs_pdf, "MANIFEST_PATH", manifest)

    assert "Manifest source has an invalid pdf_page: docs/source.md" in (
        generate_docs_pdf.check_generated_artifacts()
    )


def test_freshness_check_rejects_pdf_page_beyond_generated_page_count(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    source = docs_dir / "source.md"
    source.write_text("# Source\n\nBody.\n", encoding="utf-8")
    output = tmp_path / "static" / "docs" / "booklet.pdf"
    manifest_path = tmp_path / "static" / "docs" / "manifest.json"
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)
    monkeypatch.setattr(generate_docs_pdf, "SOURCE_DOCS", [source])
    monkeypatch.setattr(generate_docs_pdf, "OUTPUT_PATH", output)
    monkeypatch.setattr(generate_docs_pdf, "MANIFEST_PATH", manifest_path)
    generate_docs_pdf.build_pdf()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["included_source_files"][0]["pdf_page"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert "Manifest source pdf_page exceeds the generated PDF page count: docs/source.md" in (
        generate_docs_pdf.check_generated_artifacts()
    )


def test_changed_files_includes_deletions(monkeypatch):
    calls: list[list[str]] = []

    def fake_git_lines(args):
        calls.append(args)
        return ["docs/removed.md"]

    monkeypatch.setattr(check_kms_impact, "_git_lines", fake_git_lines)

    assert check_kms_impact.changed_files("base", "head") == ["docs/removed.md"]
    assert "--diff-filter=ACDMRTUXB" in calls[0]


def test_pull_request_event_uses_pr_base_and_head_without_re_resolving(monkeypatch):
    def unexpected_git_call(args):
        raise AssertionError(f"Unexpected Git call: {args}")

    monkeypatch.setattr(check_kms_impact, "_git_lines", unexpected_git_call)

    assert check_kms_impact.resolve_validation_range(
        "pull_request",
        base="pr-base",
        head="feature-head",
        target_ref=None,
    ) == ("pr-base", "feature-head")


def test_push_event_uses_target_merge_base_instead_of_previous_commit(monkeypatch):
    calls: list[list[str]] = []

    def fake_git_lines(args):
        calls.append(args)
        return ["task-merge-base"]

    monkeypatch.setattr(check_kms_impact, "_git_lines", fake_git_lines)

    assert check_kms_impact.resolve_validation_range(
        "push",
        base=None,
        head="follow-up-head",
        target_ref="origin/master",
    ) == ("task-merge-base", "follow-up-head")
    assert calls == [["merge-base", "origin/master", "follow-up-head"]]

    with pytest.raises(ValueError, match="previous commit"):
        check_kms_impact.resolve_validation_range(
            "push",
            base="event-before",
            head="follow-up-head",
            target_ref="origin/master",
        )


def test_github_workflow_wires_pull_request_and_push_task_ranges():
    workflow = (ROOT / ".github" / "workflows" / "kms-enforcement.yml").read_text(
        encoding="utf-8"
    )

    assert "github.event.before" not in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "github.event.repository.default_branch" in workflow
    assert "--event-name pull_request" in workflow
    assert "--event-name push" in workflow
    assert "--target-ref \"origin/${DEFAULT_BRANCH}\"" in workflow
    assert workflow.count("python scripts/kms.py check") == 2
    assert "python scripts/check_kms_impact.py" not in workflow

    deployment_workflow = (
        ROOT / ".github" / "workflows" / "deploy-on-master.yml"
    ).read_text(encoding="utf-8")
    assert "python scripts/kms.py check" in deployment_workflow


def test_multi_commit_feature_branch_push_checks_the_complete_task(monkeypatch):
    calls: list[list[str]] = []

    def fake_git_lines(args):
        calls.append(args)
        if args[0] == "merge-base":
            return ["task-base"]
        return [
            ".kms-impact.yml",
            "docs/CHANGE_HISTORY.md",
            "docs/PROJECT_STATE.md",
            "scripts/check_kms_impact.py",
        ]

    monkeypatch.setattr(check_kms_impact, "_git_lines", fake_git_lines)
    base, head = check_kms_impact.resolve_validation_range(
        "push",
        base=None,
        head="third-commit",
        target_ref="origin/master",
    )

    changed = check_kms_impact.changed_files(base, head)

    assert changed == [
        ".kms-impact.yml",
        "docs/CHANGE_HISTORY.md",
        "docs/PROJECT_STATE.md",
        "scripts/check_kms_impact.py",
    ]
    assert calls[1][-1] == "task-base...third-commit"


def test_follow_up_fix_validates_cumulative_declaration_not_last_commit_only():
    declaration = _declaration(
        kms_files_updated=("docs/CHANGE_HISTORY.md", "docs/PROJECT_STATE.md")
    )
    complete_task = [
        ".kms-impact.yml",
        "docs/CHANGE_HISTORY.md",
        "docs/PROJECT_STATE.md",
        "scripts/check_kms_impact.py",
    ]
    follow_up_commit_only = [
        ".kms-impact.yml",
        "docs/CHANGE_HISTORY.md",
        "scripts/check_kms_impact.py",
    ]

    assert check_kms_impact.validate_declaration(declaration, complete_task) == []
    assert any(
        "Declared KMS file did not change" in error
        for error in check_kms_impact.validate_declaration(declaration, follow_up_commit_only)
    )


def test_kms_check_delegates_to_complete_read_only_validation(monkeypatch):
    captured = {}

    def fake_run_validation(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(check_kms_impact, "run_validation", fake_run_validation)

    assert kms.run_check(_command_args()) == 0
    assert captured == {
        "event_name": None,
        "base": None,
        "head": None,
        "target_ref": None,
    }


def test_kms_sync_blocks_generation_when_kia_preflight_fails(monkeypatch):
    args = kms.build_parser().parse_args(["sync"])
    monkeypatch.setattr(
        check_kms_impact,
        "evaluate_kms",
        lambda **kwargs: _validation_result(errors=("KIA mismatch",)),
    )

    def unexpected_build():
        raise AssertionError("Artifact generation must not run after a failed preflight.")

    monkeypatch.setattr(generate_docs_pdf, "build_pdf", unexpected_build)

    assert kms.run_sync(args) == 1


def test_kms_sync_generates_then_runs_complete_freshness_validation(tmp_path, monkeypatch):
    args = kms.build_parser().parse_args(["sync"])
    include_artifact_checks: list[bool] = []

    def fake_evaluate(**kwargs):
        include_artifact_checks.append(kwargs.get("include_generated_artifacts", True))
        return _validation_result()

    pdf = tmp_path / "static" / "docs" / "booklet.pdf"
    manifest = tmp_path / "static" / "docs" / "manifest.json"

    def fake_build():
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b"pdf")
        manifest.write_text("{}", encoding="utf-8")
        return pdf

    monkeypatch.setattr(check_kms_impact, "evaluate_kms", fake_evaluate)
    monkeypatch.setattr(generate_docs_pdf, "build_pdf", fake_build)
    monkeypatch.setattr(generate_docs_pdf, "ROOT", tmp_path)
    monkeypatch.setattr(generate_docs_pdf, "MANIFEST_PATH", manifest)

    assert kms.run_sync(args) == 0
    assert include_artifact_checks == [False, True]
