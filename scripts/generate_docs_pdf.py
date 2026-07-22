from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import textwrap
from datetime import datetime
from html import escape
from pathlib import Path, PurePosixPath
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kms_catalog import (  # noqa: E402
    APPROVED_CATEGORIES,
    APPROVED_MODULES,
    document_category,
    document_module,
    normalize_taxonomy_value,
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents

DOCUMENTATION_VERSION = "3.1"
OUTPUT_PATH = ROOT / "static" / "docs" / "TIS_Project_Reference_Booklet.pdf"
MANIFEST_PATH = ROOT / "static" / "docs" / "docs_manifest.json"

CORE_SOURCE_DOCS = [
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "KMS_NAVIGATION.md",
    ROOT / "docs" / "AI_PROJECT_CONTEXT.md",
    ROOT / "docs" / "DOCUMENTATION_UPDATE_POLICY.md",
    ROOT / "docs" / "TIS_MASTER_CONTEXT.md",
    ROOT / "docs" / "PROJECT_STATE.md",
    ROOT / "docs" / "CHANGE_HISTORY.md",
    ROOT / "docs" / "adr" / "README.md",
]

ENGINEERING_DOCS = [
    ROOT / "docs" / "engineering" / "README.md",
    ROOT / "docs" / "engineering" / "TIS_MODULE_MAP.md",
    ROOT / "docs" / "engineering" / "REPOSITORY_ARCHITECTURE.md",
    ROOT / "docs" / "engineering" / "USER_AND_SYSTEM_FLOWS.md",
    ROOT / "docs" / "engineering" / "DATABASE_ARCHITECTURE_OVERVIEW.md",
    ROOT / "docs" / "engineering" / "DEVELOPMENT_STANDARDS.md",
    ROOT / "docs" / "engineering" / "UI_UX_DESIGN_PHILOSOPHY.md",
    ROOT / "docs" / "engineering" / "PRODUCT_ROADMAP.md",
    ROOT / "docs" / "engineering" / "REJECTED_DECISIONS.md",
    ROOT / "docs" / "engineering" / "VISUAL_DOCUMENTATION_GUIDE.md",
    ROOT / "docs" / "engineering" / "AI_OPTIMIZATION_GUIDE.md",
    ROOT / "docs" / "engineering" / "PROJECT_GOVERNANCE.md",
    ROOT / "docs" / "engineering" / "KNOWLEDGE_LIFECYCLE.md",
    ROOT / "docs" / "engineering" / "DOCUMENTATION_AUTOMATION.md",
    ROOT / "docs" / "engineering" / "KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md",
    ROOT / "docs" / "engineering" / "SELF_EVOLVING_WORKFLOW.md",
    ROOT / "docs" / "engineering" / "DOCUMENTATION_DEPENDENCY_MAP.md",
    ROOT / "docs" / "engineering" / "AI_CODING_WORKFLOW.md",
    ROOT / "docs" / "engineering" / "FUTURE_AUTOMATION_ROADMAP.md",
]

def _normalize_source_path(value: str | Path) -> str:
    raw = str(value).replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or raw == ".":
        raise ValueError("Source path cannot be empty.")
    normalized = PurePosixPath(raw)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"Source path must be repository-relative: {value}")
    return normalized.as_posix()


def _relative_source_path(path: Path) -> str:
    return _normalize_source_path(path.relative_to(ROOT).as_posix())


def _source_sort_key(path: Path) -> tuple[str, str]:
    relative = _relative_source_path(path)
    return relative.casefold(), relative


ADR_DOCS = sorted((ROOT / "docs" / "adr").glob("*.md"), key=_source_sort_key)

HISTORY_DOCS = sorted((ROOT / "docs" / "history").glob("**/*.md"), key=_source_sort_key)

SUPPORTING_DOCS = [
    ROOT / "docs" / "marketing" / "landing_page_source_of_truth.md",
    ROOT / "docs" / "marketing" / "tis_landing_page_master_content.md",
    ROOT / "docs" / "location-data-roadmap.md",
]

SOURCE_DOCS = []
for source in [*CORE_SOURCE_DOCS, *ENGINEERING_DOCS, *ADR_DOCS, *HISTORY_DOCS, *SUPPORTING_DOCS]:
    if source not in SOURCE_DOCS:
        SOURCE_DOCS.append(source)


def _run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return "unknown"
    value = result.stdout.strip()
    return value or "unknown"


def _source_bytes(path: Path) -> bytes:
    if path.suffix.lower() != ".md":
        return path.read_bytes()
    with path.open("r", encoding="utf-8", newline=None) as handle:
        text = handle.read()
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.encode("utf-8")


def _source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(_source_bytes(path))
    return digest.hexdigest()


def _source_metadata(path: Path, *, pdf_page: int) -> dict:
    stat = path.stat()
    source_bytes = _source_bytes(path)
    return {
        "path": _relative_source_path(path),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        "size_bytes": len(source_bytes),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "pdf_page": pdf_page,
    }


def _compare_source_paths(expected_paths: list[str], manifest_paths: list[str]) -> list[str]:
    errors: list[str] = []
    try:
        expected = [_normalize_source_path(path) for path in expected_paths]
        actual = [_normalize_source_path(path) for path in manifest_paths]
    except ValueError as exc:
        return [str(exc)]

    duplicate_paths = sorted({path for path in actual if actual.count(path) > 1})
    for path in duplicate_paths:
        errors.append(f"Manifest contains a duplicate source path: {path}")

    expected_set = set(expected)
    actual_set = set(actual)
    for path in sorted(expected_set - actual_set, key=lambda item: (item.casefold(), item)):
        errors.append(f"Manifest is missing an expected source: {path}")
    for path in sorted(actual_set - expected_set, key=lambda item: (item.casefold(), item)):
        errors.append(f"Manifest contains an unexpected source: {path}")
    if not errors and actual != expected:
        errors.append("Manifest source order does not match the deterministic generator source order.")
    return errors


def _clean_text(value: str) -> str:
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u00a0": " ",
    }
    cleaned = str(value or "")
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned.encode("latin-1", "replace").decode("latin-1")


def _inline_markup(value: str) -> str:
    text = escape(_clean_text(value).strip())
    text = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_]+)__", r"<b>\1</b>", text)
    return text


def _strip_front_matter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[index + 1 :])
    return text


def _front_matter_value(path: Path, key: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    prefix = f"{key}:"
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.lower().startswith(prefix.lower()):
            return stripped[len(prefix) :].strip().strip('"')
    return ""


def _declared_document_title(path: Path) -> str:
    front_matter_title = _front_matter_value(path, "title")
    if front_matter_title:
        return _clean_text(front_matter_title)
    text = _strip_front_matter(path.read_text(encoding="utf-8"))
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            return _clean_text(match.group(1))
    return ""


def _document_title(path: Path) -> str:
    declared_title = _declared_document_title(path)
    if declared_title:
        return declared_title
    return path.stem.replace("-", " ").replace("_", " ").title()


def _is_usable_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", _clean_text(title)).strip()
    if len(normalized) < 2 or len(normalized) > 160:
        return False
    if normalized.casefold() in {"document", "todo", "tbd", "title", "untitled"}:
        return False
    return bool(re.search(r"[A-Za-z0-9]", normalized))


def _validate_source_catalog(source_docs: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in source_docs:
        if not path.exists() or not path.is_file():
            continue
        relative = _relative_source_path(path)
        title = _declared_document_title(path)
        if not _is_usable_title(title):
            errors.append(f"Included Markdown source has no usable title: {relative}")

        category = document_category(relative)
        declared_category = _front_matter_value(path, "category").strip()
        if category not in APPROVED_CATEGORIES:
            errors.append(f"Source uses an unapproved category {category!r}: {relative}")
        if declared_category:
            if declared_category not in APPROVED_CATEGORIES:
                errors.append(
                    f"Source declares an unapproved category {declared_category!r}: {relative}"
                )
            elif declared_category != category:
                errors.append(
                    f"Source category {declared_category!r} does not match path category "
                    f"{category!r}: {relative}"
                )

        declared_module = _front_matter_value(path, "module").strip()
        normalized_declared_module = normalize_taxonomy_value(declared_module)
        if declared_module and (
            declared_module != normalized_declared_module
            or declared_module not in APPROVED_MODULES
        ):
            errors.append(f"Source declares an unapproved module {declared_module!r}: {relative}")
        module = document_module(relative, category, declared_module)
        if module not in APPROVED_MODULES:
            errors.append(f"Source uses an unapproved module {module!r}: {relative}")
    return errors


def _markdown_links(path: Path) -> list[tuple[int, str]]:
    links: list[tuple[int, str]] = []
    in_code_block = False
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", line):
            links.append((line_number, match.group(1).strip()))
    return links


def _validate_navigation_links(
    navigation_path: Path,
    listed_source_paths: list[str],
) -> list[str]:
    if not navigation_path.exists():
        return ["KMS navigation document is missing: docs/KMS_NAVIGATION.md"]

    errors: list[str] = []
    docs_root = (ROOT / "docs").resolve()
    listed = {_normalize_source_path(path) for path in listed_source_paths}
    for line_number, raw_destination in _markdown_links(navigation_path):
        destination = raw_destination
        if destination.startswith("<") and destination.endswith(">"):
            destination = destination[1:-1].strip()
        prefix = f"docs/KMS_NAVIGATION.md:{line_number}"
        if not destination or "\\" in destination or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", destination):
            errors.append(f"Navigation link must be a relative docs path at {prefix}: {raw_destination}")
            continue
        if destination.startswith(("/", "//")) or "?" in destination:
            errors.append(f"Navigation link must be a relative docs path at {prefix}: {raw_destination}")
            continue

        path_part = unquote(destination.split("#", 1)[0]).strip()
        candidate = navigation_path if not path_part else navigation_path.parent / path_part
        try:
            resolved = candidate.resolve()
            resolved.relative_to(docs_root)
        except (OSError, ValueError):
            errors.append(f"Navigation link leaves docs/ at {prefix}: {raw_destination}")
            continue
        if resolved.suffix.lower() != ".md":
            errors.append(f"Navigation link is not a Markdown document at {prefix}: {raw_destination}")
            continue
        if not resolved.exists() or not resolved.is_file():
            errors.append(f"Navigation link points to a missing document at {prefix}: {raw_destination}")
            continue

        relative = _relative_source_path(resolved)
        if relative not in listed:
            errors.append(
                f"Navigation link points to an unlisted authoritative document at {prefix}: {relative}"
            )
    return errors


def _validate_authoritative_sources(source_docs: list[Path]) -> list[str]:
    errors = _validate_source_catalog(source_docs)
    expected_paths = [_relative_source_path(path) for path in source_docs]
    navigation_path = ROOT / "docs" / "KMS_NAVIGATION.md"
    if _relative_source_path(navigation_path) in expected_paths:
        errors.extend(_validate_navigation_links(navigation_path, expected_paths))
    return errors


def _pdf_page_count(path: Path) -> int:
    try:
        return len(re.findall(rb"/Type\s*/Page\b", path.read_bytes()))
    except OSError:
        return 0


def _bookmark_key(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


class HandbookDocTemplate(SimpleDocTemplate):
    def __init__(self, *args, source_pages: dict[str, int], **kwargs):
        super().__init__(*args, **kwargs)
        self.source_pages = source_pages

    def afterFlowable(self, flowable) -> None:
        bookmark_key = getattr(flowable, "_kms_bookmark_key", "")
        bookmark_title = getattr(flowable, "_kms_bookmark_title", "")
        bookmark_level = getattr(flowable, "_kms_bookmark_level", None)
        source_path = getattr(flowable, "_kms_source_path", "")
        if not bookmark_key or not bookmark_title or bookmark_level is None:
            return

        self.canv.bookmarkPage(bookmark_key)
        self.canv.addOutlineEntry(
            _clean_text(bookmark_title),
            bookmark_key,
            level=bookmark_level,
            closed=bookmark_level == 0,
        )
        if source_path:
            self.source_pages[source_path] = self.page
            self.notify(
                "TOCEntry",
                (0, _clean_text(bookmark_title), self.page, bookmark_key),
            )


def _styles():
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "BookletTitle",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=30,
            textColor=colors.HexColor("#1F4F82"),
            spaceAfter=18,
        ),
        "subtitle": ParagraphStyle(
            "BookletSubtitle",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=14.5,
            textColor=colors.HexColor("#475569"),
            spaceAfter=7,
        ),
        "h1": ParagraphStyle(
            "Heading1",
            parent=sample["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=23,
            textColor=colors.HexColor("#1F4F82"),
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "Heading2",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#193B63"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "Heading3",
            parent=sample["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#334155"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=9.4,
            leading=13.2,
            textColor=colors.HexColor("#111827"),
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=9.1,
            leading=12.6,
            leftIndent=14,
            firstLineIndent=0,
            spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=sample["Code"],
            fontName="Courier",
            fontSize=7.4,
            leading=9.4,
            backColor=colors.HexColor("#F1F5F9"),
            borderColor=colors.HexColor("#CBD5E1"),
            borderWidth=0.25,
            borderPadding=6,
            leftIndent=0,
            rightIndent=0,
            spaceBefore=5,
            spaceAfter=7,
        ),
        "toc": ParagraphStyle(
            "TableOfContentsEntry",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=13,
            textColor=colors.HexColor("#1E293B"),
            leftIndent=8,
            firstLineIndent=0,
            rightIndent=24,
            spaceBefore=2,
            spaceAfter=2,
        ),
    }


def _add_pending_paragraph(story: list, pending: list[str], styles: dict) -> None:
    if not pending:
        return
    text = " ".join(part.strip() for part in pending if part.strip())
    if text:
        story.append(Paragraph(_inline_markup(text), styles["body"]))
    pending.clear()


def _add_pending_list(story: list, pending_items: list[str], styles: dict, *, ordered: bool) -> None:
    if not pending_items:
        return
    flowable_items = [
        ListItem(Paragraph(_inline_markup(item), styles["bullet"]), leftIndent=8)
        for item in pending_items
    ]
    story.append(
        ListFlowable(
            flowable_items,
            bulletType="1" if ordered else "bullet",
            start="1",
            leftIndent=18,
            bulletFontName="Helvetica",
            bulletFontSize=8,
        )
    )
    story.append(Spacer(1, 4))
    pending_items.clear()


def _add_code_block(story: list, lines: list[str], styles: dict) -> None:
    wrapped_lines: list[str] = []
    for line in lines:
        cleaned = _clean_text(line.rstrip())
        if not cleaned:
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(textwrap.wrap(cleaned, width=86, replace_whitespace=False) or [""])
    story.append(Preformatted("\n".join(wrapped_lines), styles["code"]))


def _markdown_to_flowables(
    path: Path,
    styles: dict,
    *,
    document_title: str,
    source_bookmark_key: str,
) -> list:
    story: list = []
    pending_paragraph: list[str] = []
    pending_list: list[str] = []
    pending_ordered_list: list[str] = []
    code_lines: list[str] = []
    in_code = False
    major_heading_index = 0

    text = _strip_front_matter(path.read_text(encoding="utf-8"))
    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if line.strip().startswith("```"):
            if in_code:
                _add_code_block(story, code_lines, styles)
                code_lines.clear()
                in_code = False
            else:
                _add_pending_paragraph(story, pending_paragraph, styles)
                _add_pending_list(story, pending_list, styles, ordered=False)
                _add_pending_list(story, pending_ordered_list, styles, ordered=True)
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            _add_pending_paragraph(story, pending_paragraph, styles)
            _add_pending_list(story, pending_list, styles, ordered=False)
            _add_pending_list(story, pending_ordered_list, styles, ordered=True)
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            _add_pending_paragraph(story, pending_paragraph, styles)
            _add_pending_list(story, pending_list, styles, ordered=False)
            _add_pending_list(story, pending_ordered_list, styles, ordered=True)
            level = len(heading.group(1))
            heading_title = _clean_text(heading.group(2))
            if level == 1 and heading_title.casefold() == document_title.casefold():
                continue
            style_name = "h1" if level == 1 else "h2" if level == 2 else "h3"
            heading_flowable = Paragraph(_inline_markup(heading.group(2)), styles[style_name])
            if level == 2:
                major_heading_index += 1
                heading_flowable._kms_bookmark_key = _bookmark_key(
                    "heading",
                    f"{source_bookmark_key}:{major_heading_index}:{heading_title}",
                )
                heading_flowable._kms_bookmark_title = heading_title
                heading_flowable._kms_bookmark_level = 1
            story.append(heading_flowable)
            continue

        unordered = re.match(r"^[-*]\s+(.+)$", stripped)
        if unordered:
            _add_pending_paragraph(story, pending_paragraph, styles)
            _add_pending_list(story, pending_ordered_list, styles, ordered=True)
            pending_list.append(unordered.group(1))
            continue

        ordered = re.match(r"^\d+\.\s+(.+)$", stripped)
        if ordered:
            _add_pending_paragraph(story, pending_paragraph, styles)
            _add_pending_list(story, pending_list, styles, ordered=False)
            pending_ordered_list.append(ordered.group(1))
            continue

        if re.match(r"^_{3,}$", stripped) or re.match(r"^-{3,}$", stripped):
            _add_pending_paragraph(story, pending_paragraph, styles)
            _add_pending_list(story, pending_list, styles, ordered=False)
            _add_pending_list(story, pending_ordered_list, styles, ordered=True)
            story.append(Spacer(1, 8))
            continue

        _add_pending_list(story, pending_list, styles, ordered=False)
        _add_pending_list(story, pending_ordered_list, styles, ordered=True)
        pending_paragraph.append(stripped)

    if in_code and code_lines:
        _add_code_block(story, code_lines, styles)
    _add_pending_paragraph(story, pending_paragraph, styles)
    _add_pending_list(story, pending_list, styles, ordered=False)
    _add_pending_list(story, pending_ordered_list, styles, ordered=True)
    return story


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(0.72 * inch, 0.45 * inch, "TIS Project Reference Booklet")
    canvas.drawRightString(7.78 * inch, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _write_manifest(
    *,
    generated_at_iso: str,
    branch: str,
    commit_sha: str,
    included_docs: list[Path],
    source_pages: dict[str, int],
) -> None:
    manifest = {
        "pdf_path": _relative_source_path(OUTPUT_PATH),
        "manifest_path": _relative_source_path(MANIFEST_PATH),
        "generated_at": generated_at_iso,
        "documentation_version": DOCUMENTATION_VERSION,
        "branch": branch,
        "commit_sha": commit_sha,
        "source_of_truth": "Markdown files under docs/ are authoritative. This PDF is a generated snapshot.",
        "pdf_sha256": _source_hash(OUTPUT_PATH),
        "pdf_size_bytes": OUTPUT_PATH.stat().st_size,
        "included_source_files": [
            _source_metadata(
                path,
                pdf_page=source_pages[_relative_source_path(path)],
            )
            for path in included_docs
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def build_pdf() -> Path:
    styles = _styles()
    included_docs = [path for path in SOURCE_DOCS if path.exists()]
    source_errors = _validate_authoritative_sources(SOURCE_DOCS)
    if source_errors:
        raise RuntimeError("KMS source validation failed:\n- " + "\n- ".join(source_errors))
    generated_at_dt = datetime.now().astimezone()
    generated_at_display = generated_at_dt.strftime("%Y-%m-%d %H:%M %Z")
    generated_at_iso = generated_at_dt.isoformat()
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    commit_sha = _run_git(["rev-parse", "--short", "HEAD"])
    source_pages: dict[str, int] = {}

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    doc = HandbookDocTemplate(
        str(OUTPUT_PATH),
        source_pages=source_pages,
        pagesize=letter,
        rightMargin=0.72 * inch,
        leftMargin=0.72 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.72 * inch,
        title="TIS Project Reference Booklet",
        author="TIS",
    )

    story: list = [
        Paragraph("TIS Project Reference Booklet", styles["title"]),
        Paragraph("Documentation version: " + escape(DOCUMENTATION_VERSION), styles["subtitle"]),
        Paragraph(f"Generated: {escape(generated_at_display)}", styles["subtitle"]),
        Paragraph(f"Branch: {escape(branch)}", styles["subtitle"]),
        Paragraph(f"Git commit SHA: {escape(commit_sha)}", styles["subtitle"]),
        Paragraph(
            "Source of truth: Markdown files under docs/ are authoritative. This PDF is a generated snapshot and must not be edited manually.",
            styles["subtitle"],
        ),
        Spacer(1, 20),
        Paragraph(
            "Use the table of contents and PDF bookmarks to move directly to each source document. Major document headings are available as child bookmarks.",
            styles["subtitle"],
        ),
    ]

    story.append(PageBreak())
    story.extend(
        [
            Paragraph("How to Use This Handbook", styles["h1"]),
            Paragraph(
                "Start with the TIS KMS Navigation Guide to choose the smallest useful reading path for your role or task. Use this booklet when a portable, reviewable snapshot is more convenient than browsing the Markdown sources.",
                styles["body"],
            ),
            Paragraph("Navigate", styles["h2"]),
            Paragraph(
                "Use the table of contents for document-level page numbers. In PDF viewers that support outlines, open the bookmarks panel to browse every source document and its major headings.",
                styles["body"],
            ),
            Paragraph("Verify", styles["h2"]),
            Paragraph(
                "The title page records the documentation version, generated timestamp, branch, and Git commit SHA. The generated manifest records source hashes and each document's starting PDF page.",
                styles["body"],
            ),
            Paragraph("Source Of Truth", styles["h2"]),
            Paragraph(
                "Markdown files under docs/ remain authoritative. This PDF is generated and must never be edited manually. When source documents change, run the approved KMS synchronization command to regenerate this snapshot and its manifest.",
                styles["body"],
            ),
        ]
    )

    story.append(PageBreak())
    story.append(Paragraph("Table of Contents", styles["h1"]))
    table_of_contents = TableOfContents()
    table_of_contents.levelStyles = [styles["toc"]]
    table_of_contents.dotsMinLevel = 0
    story.append(table_of_contents)

    story.append(PageBreak())

    for index, source_path in enumerate(included_docs):
        if index:
            story.append(PageBreak())
        relative = _relative_source_path(source_path)
        document_title = _document_title(source_path)
        source_bookmark_key = _bookmark_key("source", relative)
        source_heading = Paragraph(_inline_markup(document_title), styles["h1"])
        source_heading._kms_bookmark_key = source_bookmark_key
        source_heading._kms_bookmark_title = document_title
        source_heading._kms_bookmark_level = 0
        source_heading._kms_source_path = relative
        story.append(source_heading)
        story.append(Paragraph(_inline_markup(relative), styles["subtitle"]))
        story.extend(
            _markdown_to_flowables(
                source_path,
                styles,
                document_title=document_title,
                source_bookmark_key=source_bookmark_key,
            )
        )

    doc.multiBuild(story, onFirstPage=_footer, onLaterPages=_footer)
    missing_source_pages = [
        _relative_source_path(path)
        for path in included_docs
        if _relative_source_path(path) not in source_pages
    ]
    if missing_source_pages:
        raise RuntimeError(
            "PDF navigation did not capture source pages: " + ", ".join(missing_source_pages)
        )
    _write_manifest(
        generated_at_iso=generated_at_iso,
        branch=branch,
        commit_sha=commit_sha,
        included_docs=included_docs,
        source_pages=source_pages,
    )
    return OUTPUT_PATH


def check_generated_artifacts() -> list[str]:
    errors: list[str] = []
    included_docs = [path for path in SOURCE_DOCS if path.exists()]
    errors.extend(_validate_authoritative_sources(SOURCE_DOCS))
    missing_sources = [path for path in SOURCE_DOCS if not path.exists()]
    for path in missing_sources:
        errors.append(f"Required PDF source is missing: {_relative_source_path(path)}")

    all_markdown = set((ROOT / "docs").glob("**/*.md"))
    unlisted_markdown = sorted(all_markdown - set(included_docs), key=_source_sort_key)
    for path in unlisted_markdown:
        errors.append(
            "Authoritative Markdown is not included in the booklet source list: "
            f"{_relative_source_path(path)}"
        )

    if not OUTPUT_PATH.exists() or OUTPUT_PATH.stat().st_size <= 0:
        errors.append(f"Generated PDF is missing or empty: {OUTPUT_PATH.relative_to(ROOT).as_posix()}")
    if not MANIFEST_PATH.exists():
        errors.append(f"Generated manifest is missing: {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
        return errors

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Generated manifest is unreadable: {exc}")
        return errors

    if manifest.get("documentation_version") != DOCUMENTATION_VERSION:
        errors.append(
            "Manifest documentation version does not match the generator: "
            f"expected {DOCUMENTATION_VERSION!r}, found {manifest.get('documentation_version')!r}."
        )

    expected_paths = [_relative_source_path(path) for path in SOURCE_DOCS]
    manifest_sources = manifest.get("included_source_files")
    if not isinstance(manifest_sources, list):
        errors.append("Manifest included_source_files must be a list.")
        manifest_sources = []
    manifest_paths = [str(item.get("path") or "") for item in manifest_sources if isinstance(item, dict)]
    errors.extend(_compare_source_paths(expected_paths, manifest_paths))

    metadata_by_path: dict[str, dict] = {}
    for item in manifest_sources:
        if not isinstance(item, dict):
            continue
        try:
            normalized_path = _normalize_source_path(str(item.get("path") or ""))
        except ValueError:
            continue
        metadata_by_path[normalized_path] = item
    pdf_page_count = _pdf_page_count(OUTPUT_PATH) if OUTPUT_PATH.exists() else 0
    if OUTPUT_PATH.exists() and OUTPUT_PATH.stat().st_size > 0 and pdf_page_count < 1:
        errors.append("Generated PDF page count could not be determined.")
    previous_pdf_page = 0
    for path in included_docs:
        relative = _relative_source_path(path)
        metadata = metadata_by_path.get(relative)
        if metadata is None:
            continue
        expected_hash = str(metadata.get("sha256") or "")
        current_hash = _source_hash(path)
        if expected_hash != current_hash:
            errors.append(f"Booklet source is stale: {relative}")
        pdf_page = metadata.get("pdf_page")
        if isinstance(pdf_page, bool) or not isinstance(pdf_page, int) or pdf_page < 1:
            errors.append(f"Manifest source has an invalid pdf_page: {relative}")
        elif pdf_page_count and pdf_page > pdf_page_count:
            errors.append(
                f"Manifest source pdf_page exceeds the generated PDF page count: {relative}"
            )
        elif pdf_page <= previous_pdf_page:
            errors.append(f"Manifest source pages are not strictly increasing: {relative}")
        else:
            previous_pdf_page = pdf_page

    if OUTPUT_PATH.exists() and OUTPUT_PATH.stat().st_size > 0:
        expected_pdf_hash = str(manifest.get("pdf_sha256") or "")
        expected_pdf_size = manifest.get("pdf_size_bytes")
        if not expected_pdf_hash:
            errors.append("Manifest does not contain pdf_sha256. Regenerate generated artifacts.")
        elif expected_pdf_hash != _source_hash(OUTPUT_PATH):
            errors.append("Generated PDF hash does not match the manifest.")
        if expected_pdf_size != OUTPUT_PATH.stat().st_size:
            errors.append("Generated PDF size does not match the manifest.")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or validate the TIS KMS PDF snapshot.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the PDF, manifest, source coverage, and source hashes without writing files.",
    )
    args = parser.parse_args()

    if args.check:
        errors = check_generated_artifacts()
        if errors:
            print("KMS generated artifacts are not current:")
            for error in errors:
                print(f"- {error}")
            print("Run: python scripts/generate_docs_pdf.py")
            return 1
        print("KMS generated artifacts are current.")
        return 0

    output = build_pdf()
    print(f"Generated {output.relative_to(ROOT).as_posix()}")
    print(f"Generated {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
