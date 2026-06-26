from __future__ import annotations

import hashlib
import json
import re
import subprocess
import textwrap
from datetime import datetime
from html import escape
from pathlib import Path

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


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTATION_VERSION = "3.0"
OUTPUT_PATH = ROOT / "static" / "docs" / "TIS_Project_Reference_Booklet.pdf"
MANIFEST_PATH = ROOT / "static" / "docs" / "docs_manifest.json"

CORE_SOURCE_DOCS = [
    ROOT / "docs" / "README.md",
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
]

ADR_DOCS = sorted((ROOT / "docs" / "adr").glob("*.md"))

HISTORY_DOCS = sorted((ROOT / "docs" / "history").glob("**/*.md"))

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


def _source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 64), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_metadata(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        "size_bytes": stat.st_size,
        "sha256": _source_hash(path),
    }


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


def _markdown_to_flowables(path: Path, styles: dict) -> list:
    story: list = []
    pending_paragraph: list[str] = []
    pending_list: list[str] = []
    pending_ordered_list: list[str] = []
    code_lines: list[str] = []
    in_code = False

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
            style_name = "h1" if level == 1 else "h2" if level == 2 else "h3"
            story.append(Paragraph(_inline_markup(heading.group(2)), styles[style_name]))
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
) -> None:
    manifest = {
        "pdf_path": OUTPUT_PATH.relative_to(ROOT).as_posix(),
        "manifest_path": MANIFEST_PATH.relative_to(ROOT).as_posix(),
        "generated_at": generated_at_iso,
        "documentation_version": DOCUMENTATION_VERSION,
        "branch": branch,
        "commit_sha": commit_sha,
        "source_of_truth": "Markdown files under docs/ are authoritative. This PDF is a generated snapshot.",
        "included_source_files": [_source_metadata(path) for path in included_docs],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def build_pdf() -> Path:
    styles = _styles()
    included_docs = [path for path in SOURCE_DOCS if path.exists()]
    generated_at_dt = datetime.now().astimezone()
    generated_at_display = generated_at_dt.strftime("%Y-%m-%d %H:%M %Z")
    generated_at_iso = generated_at_dt.isoformat()
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    commit_sha = _run_git(["rev-parse", "--short", "HEAD"])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
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
        Spacer(1, 12),
        Paragraph("Source Documents Included", styles["h2"]),
    ]

    for path in included_docs:
        relative = path.relative_to(ROOT).as_posix()
        story.append(Paragraph(_inline_markup(f"- {relative}"), styles["body"]))

    story.append(PageBreak())

    for index, source_path in enumerate(included_docs):
        if index:
            story.append(PageBreak())
        story.append(Paragraph(_inline_markup(source_path.relative_to(ROOT).as_posix()), styles["h1"]))
        story.extend(_markdown_to_flowables(source_path, styles))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    _write_manifest(
        generated_at_iso=generated_at_iso,
        branch=branch,
        commit_sha=commit_sha,
        included_docs=included_docs,
    )
    return OUTPUT_PATH


if __name__ == "__main__":
    output = build_pdf()
    print(f"Generated {output.relative_to(ROOT).as_posix()}")
    print(f"Generated {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
