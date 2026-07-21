from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parent
PDF_PATH = ROOT / "static" / "docs" / "TIS_Project_Reference_Booklet.pdf"
MANIFEST_PATH = ROOT / "static" / "docs" / "docs_manifest.json"

REQUIRED_DOCUMENTS = {
    "TIS Master Context": ROOT / "docs" / "TIS_MASTER_CONTEXT.md",
    "Project State": ROOT / "docs" / "PROJECT_STATE.md",
    "AI Project Context": ROOT / "docs" / "AI_PROJECT_CONTEXT.md",
    "Documentation Update Policy": ROOT / "docs" / "DOCUMENTATION_UPDATE_POLICY.md",
    "Change History": ROOT / "docs" / "CHANGE_HISTORY.md",
    "ADR folder": ROOT / "docs" / "adr",
    "Module History folder": ROOT / "docs" / "history",
    "PDF snapshot": PDF_PATH,
    "Manifest": MANIFEST_PATH,
}

DOCUMENT_CATEGORIES = (
    ("core", "Core"),
    ("engineering", "Engineering"),
    ("decisions", "Decisions"),
    ("history", "History"),
    ("marketing", "Marketing"),
    ("supporting", "Supporting"),
)
CATEGORY_LABELS = dict(DOCUMENT_CATEGORIES)
CORE_DOCUMENTS = {
    "docs/README.md",
    "docs/KMS_NAVIGATION.md",
    "docs/AI_PROJECT_CONTEXT.md",
    "docs/DOCUMENTATION_UPDATE_POLICY.md",
    "docs/TIS_MASTER_CONTEXT.md",
    "docs/PROJECT_STATE.md",
    "docs/CHANGE_HISTORY.md",
}
ADR_MODULES = {
    "0001": "landing-page",
    "0002": "identity-access",
    "0003": "subscriptions",
    "0004": "subscriptions",
    "0005": "provisioning",
    "0006": "platform-knowledge",
    "0007": "landing-page",
}
ENGINEERING_MODULES = {
    "README": "engineering-handbook",
    "TIS_MODULE_MAP": "architecture",
    "REPOSITORY_ARCHITECTURE": "architecture",
    "USER_AND_SYSTEM_FLOWS": "architecture",
    "DATABASE_ARCHITECTURE_OVERVIEW": "database",
    "DEVELOPMENT_STANDARDS": "engineering-governance",
    "UI_UX_DESIGN_PHILOSOPHY": "design",
    "PRODUCT_ROADMAP": "product-roadmap",
    "REJECTED_DECISIONS": "architecture",
    "VISUAL_DOCUMENTATION_GUIDE": "design",
    "AI_OPTIMIZATION_GUIDE": "ai-workflow",
    "PROJECT_GOVERNANCE": "engineering-governance",
    "KNOWLEDGE_LIFECYCLE": "platform-knowledge",
    "DOCUMENTATION_AUTOMATION": "platform-knowledge",
    "KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD": "platform-knowledge",
    "SELF_EVOLVING_WORKFLOW": "platform-knowledge",
    "DOCUMENTATION_DEPENDENCY_MAP": "platform-knowledge",
    "AI_CODING_WORKFLOW": "ai-workflow",
    "FUTURE_AUTOMATION_ROADMAP": "platform-knowledge",
}
MODULE_LABELS = {
    "academic-calendar": "Academic Calendar",
    "ai-workflow": "AI Workflow",
    "architecture": "Architecture",
    "database": "Database",
    "design": "Design",
    "engineering-governance": "Engineering Governance",
    "engineering-handbook": "Engineering Handbook",
    "identity-access": "Identity And Access",
    "kms-core": "KMS Core",
    "landing-page": "Landing Page",
    "location-data": "Location Data",
    "module-history": "Module History",
    "platform-knowledge": "Platform Knowledge",
    "product-roadmap": "Product Roadmap",
    "provisioning": "Provisioning",
    "saas-onboarding": "SaaS Onboarding",
    "subscriptions": "Subscriptions",
    "workforce-planning": "Workforce Planning",
}


def _relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _safe_repo_path(relative_path: str) -> Path | None:
    cleaned = str(relative_path or "").replace("\\", "/").lstrip("/")
    if not cleaned:
        return None
    candidate = (ROOT / cleaned).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError:
        return None
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.suffix.lower() == ".md":
        with path.open("r", encoding="utf-8", newline=None) as handle:
            text = handle.read()
        digest.update(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))
    else:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 64), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


def _load_manifest() -> tuple[dict[str, Any] | None, str | None]:
    if not MANIFEST_PATH.exists():
        return None, "missing_manifest"
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8")), None
    except Exception:
        return None, "malformed_manifest"


def _parse_markdown_headings(path: Path, *, limit: int = 5) -> list[dict[str, str]]:
    if not path.exists():
        return []
    entries: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("## "):
            continue
        title = stripped.lstrip("#").strip()
        if title.lower() == "entry template":
            continue
        entries.append({"title": title, "path": _relative(path)})
        if len(entries) >= limit:
            break
    return entries


def _read_front_matter_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
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


def _plain_markdown(value: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[`*_~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _truncate(value: str, *, limit: int = 220) -> str:
    if len(value) <= limit:
        return value
    shortened = value[: limit + 1].rsplit(" ", 1)[0].rstrip(" .,;:")
    return shortened + "..."


def _read_document_identity(path: Path) -> tuple[str, str, dict[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return "", "", {}

    metadata: dict[str, str] = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            stripped = line.strip()
            if stripped == "---":
                body_start = index + 1
                break
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                metadata[key.strip().lower()] = value.strip().strip('"')

    body = lines[body_start:]
    title = metadata.get("title", "")
    if not title:
        for line in body:
            if line.startswith("# "):
                title = _plain_markdown(line[2:])
                break

    summary = _plain_markdown(metadata.get("summary", ""))
    if not summary:
        paragraph: list[str] = []
        in_code = False
        for line in body:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            if not stripped:
                if paragraph:
                    break
                continue
            if re.match(
                r"^(status|date|last updated|documentation version|module|related .+|reviewer/approval notes):",
                stripped,
                re.IGNORECASE,
            ):
                if paragraph:
                    break
                continue
            if stripped.startswith(("#", "- ", "* ", ">", "|")) or re.match(r"^\d+\.\s", stripped):
                if paragraph:
                    break
                continue
            paragraph.append(stripped)
        summary = _plain_markdown(" ".join(paragraph))

    return title, _truncate(summary), metadata


def _document_category(source_path: str) -> str:
    normalized = source_path.replace("\\", "/")
    if normalized in CORE_DOCUMENTS:
        return "core"
    if normalized.startswith("docs/engineering/"):
        return "engineering"
    if normalized.startswith("docs/adr/"):
        return "decisions"
    if normalized.startswith("docs/history/"):
        return "history"
    if normalized.startswith("docs/marketing/"):
        return "marketing"
    return "supporting"


def _document_module(source_path: str, category: str, metadata: dict[str, str]) -> str:
    normalized = source_path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    declared_module = metadata.get("module", "").strip().lower().replace(" ", "-")
    if declared_module:
        return declared_module
    if category == "core":
        return "kms-core"
    if category == "engineering":
        return ENGINEERING_MODULES.get(Path(normalized).stem, "engineering-handbook")
    if category == "decisions":
        return ADR_MODULES.get(Path(normalized).name[:4], "architecture")
    if category == "history" and len(parts) > 2:
        if normalized == "docs/history/README.md":
            return "module-history"
        return parts[2]
    if category == "marketing":
        return "landing-page"
    if normalized == "docs/location-data-roadmap.md":
        return "location-data"
    return "supporting"


def _module_label(module: str) -> str:
    return MODULE_LABELS.get(module, module.replace("-", " ").title())


def _document_details(path: Path | None, source_path: str) -> dict[str, str]:
    title, summary, metadata = _read_document_identity(path) if path is not None else ("", "", {})
    category = _document_category(source_path)
    module = _document_module(source_path, category, metadata)
    fallback_title = Path(source_path).stem.replace("_", " ").replace("-", " ").title()
    return {
        "title": title or fallback_title,
        "summary": summary or "Authoritative TIS knowledge source included in the generated handbook.",
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "module": module,
        "module_label": _module_label(module),
    }


def list_adrs(limit: int = 8) -> list[dict[str, Any]]:
    adr_dir = ROOT / "docs" / "adr"
    rows = []
    for path in adr_dir.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        title = _read_front_matter_value(path, "title") or path.stem.replace("-", " ").title()
        status = _read_front_matter_value(path, "status") or "Unknown"
        date = _read_front_matter_value(path, "date") or ""
        rows.append(
            {
                "title": title,
                "status": status,
                "date": date,
                "path": _relative(path),
            }
        )
    rows.sort(key=lambda row: row["path"], reverse=True)
    rows.sort(key=lambda row: row["date"], reverse=True)
    return rows[:limit]


def list_module_history_areas() -> list[dict[str, Any]]:
    history_dir = ROOT / "docs" / "history"
    rows = []
    for path in history_dir.glob("*/README.md"):
        title = _read_front_matter_value(path, "title") or path.parent.name.replace("-", " ").title()
        entries = [entry for entry in path.parent.glob("*.md") if entry.name.lower() != "readme.md"]
        entry_dates = []
        for entry in entries:
            date = _read_front_matter_value(entry, "date")
            if not date and re.match(r"^\d{4}-\d{2}-\d{2}", entry.name):
                date = entry.name[:10]
            if date:
                entry_dates.append(date)
        rows.append(
            {
                "title": title,
                "module": path.parent.name,
                "path": _relative(path.parent),
                "source_path": _relative(path),
                "entry_count": len(entries),
                "latest_date": max(entry_dates, default=""),
            }
        )
    rows.sort(key=lambda row: row["title"].casefold())
    rows.sort(key=lambda row: row["latest_date"], reverse=True)
    return rows


def get_knowledge_center_payload() -> dict[str, Any]:
    manifest, manifest_error = _load_manifest()
    pdf_exists = PDF_PATH.exists()
    pdf_size = PDF_PATH.stat().st_size if pdf_exists else 0
    pdf_modified_at = _iso_mtime(PDF_PATH) if pdf_exists else ""
    source_rows = []
    stale_count = 0
    warning_count = 0

    included_sources = []
    if isinstance(manifest, dict):
        included_sources = manifest.get("included_source_files") or []
        if not isinstance(included_sources, list):
            included_sources = []
            manifest_error = manifest_error or "malformed_sources"

    for item in included_sources:
        if not isinstance(item, dict):
            warning_count += 1
            continue
        source_path = str(item.get("path") or "")
        expected_hash = str(item.get("sha256") or "").strip()
        expected_modified = str(item.get("modified_at") or "").strip()
        manifest_pdf_page = item.get("pdf_page")
        pdf_page = (
            manifest_pdf_page
            if isinstance(manifest_pdf_page, int) and not isinstance(manifest_pdf_page, bool) and manifest_pdf_page > 0
            else None
        )
        resolved = _safe_repo_path(source_path)
        status = "current"
        current_hash = ""
        current_modified = ""
        if resolved is None:
            status = "warning"
            warning_count += 1
        elif not resolved.exists() or not resolved.is_file():
            status = "missing"
            stale_count += 1
        else:
            current_modified = _iso_mtime(resolved)
            try:
                current_hash = _sha256(resolved)
            except Exception:
                current_hash = ""
                status = "warning"
                warning_count += 1
            if current_hash and expected_hash:
                if current_hash != expected_hash:
                    status = "stale"
                    stale_count += 1
            elif expected_modified and current_modified and expected_modified != current_modified:
                status = "stale"
                stale_count += 1
        source_rows.append(
            {
                "path": source_path,
                "status": status,
                "manifest_hash": expected_hash,
                "current_hash": current_hash,
                "short_hash": (current_hash or expected_hash)[:12],
                "manifest_modified_at": expected_modified,
                "current_modified_at": current_modified,
                "pdf_page": pdf_page,
                **(
                    _document_details(resolved, source_path)
                    if resolved is not None and resolved.exists() and resolved.is_file()
                    else _document_details(None, source_path)
                ),
            }
        )

    if not pdf_exists:
        pdf_status = "missing_pdf"
    elif manifest_error:
        pdf_status = "missing_manifest" if manifest_error == "missing_manifest" else "warning"
    elif stale_count:
        pdf_status = "stale"
    elif warning_count:
        pdf_status = "warning"
    else:
        pdf_status = "current"

    coverage = []
    for label, path in REQUIRED_DOCUMENTS.items():
        exists = path.exists()
        coverage.append(
            {
                "label": label,
                "path": _relative(path),
                "exists": exists,
                "kind": "folder" if path.is_dir() else "file",
            }
        )

    health_score, health_label = _calculate_health_score(
        pdf_exists=pdf_exists,
        manifest=manifest,
        manifest_error=manifest_error,
        coverage=coverage,
        stale_count=stale_count,
        warning_count=warning_count,
    )

    source_groups = []
    for key, label in DOCUMENT_CATEGORIES:
        documents = [row for row in source_rows if row["category"] == key]
        if documents:
            source_groups.append(
                {
                    "key": key,
                    "label": label,
                    "documents": documents,
                    "count": len(documents),
                }
            )

    page_by_path = {
        row["path"]: row["pdf_page"]
        for row in source_rows
        if row.get("pdf_page")
    }
    change_entries = _parse_markdown_headings(ROOT / "docs" / "CHANGE_HISTORY.md", limit=5)
    for entry in change_entries:
        entry["pdf_page"] = page_by_path.get(entry["path"])
    adrs = list_adrs(limit=10)
    for adr in adrs:
        adr["pdf_page"] = page_by_path.get(adr["path"])
    module_history_areas = list_module_history_areas()
    for area in module_history_areas:
        area["pdf_page"] = page_by_path.get(area["source_path"])

    status_options = [
        {"key": key, "label": label}
        for key, label in (
            ("current", "Current"),
            ("stale", "Stale"),
            ("missing", "Missing"),
            ("warning", "Warning"),
        )
    ]
    module_options = [
        {"key": module, "label": _module_label(module)}
        for module in sorted({row["module"] for row in source_rows}, key=_module_label)
    ]

    return {
        "manifest": manifest or {},
        "manifest_error": manifest_error,
        "documentation_version": (manifest or {}).get("documentation_version", "unknown"),
        "generated_at": (manifest or {}).get("generated_at", ""),
        "branch": (manifest or {}).get("branch", "unknown"),
        "commit_sha": (manifest or {}).get("commit_sha", "unknown"),
        "source_of_truth": (manifest or {}).get(
            "source_of_truth",
            "Markdown files under docs/ are authoritative. The PDF is a generated snapshot.",
        ),
        "pdf": {
            "exists": pdf_exists,
            "status": pdf_status,
            "size_bytes": pdf_size,
            "size_label": _format_bytes(pdf_size),
            "modified_at": pdf_modified_at,
            "path": _relative(PDF_PATH),
        },
        "health": {
            "score": health_score,
            "label": health_label,
        },
        "coverage": coverage,
        "sources": source_rows,
        "source_groups": source_groups,
        "category_options": [
            {"key": key, "label": label}
            for key, label in DOCUMENT_CATEGORIES
            if any(group["key"] == key for group in source_groups)
        ],
        "module_options": module_options,
        "status_options": status_options,
        "source_counts": {
            "total": len(source_rows),
            "stale": stale_count,
            "warnings": warning_count,
        },
        "change_entries": change_entries,
        "adrs": adrs,
        "module_history_areas": module_history_areas,
        "kia_items": [
            "Knowledge impact",
            "Docs updated",
            "Change history updated",
            "ADR needed",
            "Module history updated",
            "PDF regenerated",
            "AI project context updated",
            "Reason if not updated",
        ],
    }


def _calculate_health_score(
    *,
    pdf_exists: bool,
    manifest: dict[str, Any] | None,
    manifest_error: str | None,
    coverage: list[dict[str, Any]],
    stale_count: int,
    warning_count: int,
) -> tuple[int, str]:
    score = 100
    if not pdf_exists:
        score -= 30
    if manifest_error:
        score -= 25
    if not manifest:
        score -= 15
    missing_required = sum(1 for item in coverage if not item.get("exists"))
    score -= min(missing_required * 8, 40)
    score -= min(stale_count * 4, 30)
    score -= min(warning_count * 3, 20)
    score = max(0, min(100, score))
    if score >= 90:
        label = "Healthy"
    elif score >= 60:
        label = "Needs Attention"
    else:
        label = "Critical"
    return score, label


def _format_bytes(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB"):
        if value < 1024 or unit == "MB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} MB"
