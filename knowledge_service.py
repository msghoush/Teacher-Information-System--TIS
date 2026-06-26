from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
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


def list_adrs(limit: int = 8) -> list[dict[str, str]]:
    adr_dir = ROOT / "docs" / "adr"
    rows = []
    for path in sorted(adr_dir.glob("*.md")):
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
    return rows[:limit]


def list_module_history_areas() -> list[dict[str, str]]:
    history_dir = ROOT / "docs" / "history"
    rows = []
    for path in sorted(history_dir.glob("*/README.md")):
        title = _read_front_matter_value(path, "title") or path.parent.name.replace("-", " ").title()
        rows.append(
            {
                "title": title,
                "module": path.parent.name,
                "path": _relative(path.parent),
            }
        )
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
        "source_counts": {
            "total": len(source_rows),
            "stale": stale_count,
            "warnings": warning_count,
        },
        "change_entries": _parse_markdown_headings(ROOT / "docs" / "CHANGE_HISTORY.md", limit=5),
        "adrs": list_adrs(limit=10),
        "module_history_areas": list_module_history_areas(),
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
