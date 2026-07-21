from __future__ import annotations

import json
from pathlib import Path

import knowledge_service
from jinja2 import Environment, FileSystemLoader


def _write_doc(path: Path, *, title: str, body: str, **metadata: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    front_matter = ["---", f"title: {title}"]
    front_matter.extend(f"{key}: {value}" for key, value in metadata.items())
    front_matter.extend(["---", "", f"# {title}", "", body, ""])
    path.write_text("\n".join(front_matter), encoding="utf-8")


def test_document_details_extract_title_summary_category_and_module(tmp_path):
    path = tmp_path / "landing_page_source_of_truth.md"
    _write_doc(
        path,
        title="Landing Page Source Of Truth",
        body="Defines the approved public website boundary and content ownership.",
    )

    details = knowledge_service._document_details(
        path,
        r"docs\marketing\landing_page_source_of_truth.md",
    )

    assert details == {
        "title": "Landing Page Source Of Truth",
        "summary": "Defines the approved public website boundary and content ownership.",
        "category": "marketing",
        "category_label": "Marketing",
        "module": "landing-page",
        "module_label": "Landing Page",
    }


def test_document_categories_cover_the_knowledge_library_sections():
    cases = {
        "docs/README.md": "core",
        "docs/engineering/TIS_MODULE_MAP.md": "engineering",
        "docs/adr/0001-decision.md": "decisions",
        "docs/history/subscriptions/README.md": "history",
        "docs/marketing/landing_page_source_of_truth.md": "marketing",
        "docs/location-data-roadmap.md": "supporting",
    }

    assert {
        path: knowledge_service._document_category(path)
        for path in cases
    } == cases


def test_adrs_are_ordered_by_latest_date_then_identifier(tmp_path, monkeypatch):
    adr_dir = tmp_path / "docs" / "adr"
    _write_doc(
        adr_dir / "0001-first.md",
        title="First Decision",
        body="First decision context.",
        status="Accepted",
        date="2026-07-20",
    )
    _write_doc(
        adr_dir / "0007-later-number.md",
        title="Later Number",
        body="Later numbered decision context.",
        status="Accepted",
        date="2026-07-20",
    )
    _write_doc(
        adr_dir / "0004-newest-date.md",
        title="Newest Date",
        body="Newest dated decision context.",
        status="Accepted",
        date="2026-07-22",
    )
    monkeypatch.setattr(knowledge_service, "ROOT", tmp_path)

    assert [row["title"] for row in knowledge_service.list_adrs()] == [
        "Newest Date",
        "Later Number",
        "First Decision",
    ]


def test_module_history_areas_are_ordered_by_latest_entry(tmp_path, monkeypatch):
    older = tmp_path / "docs" / "history" / "older"
    newer = tmp_path / "docs" / "history" / "newer"
    _write_doc(older / "README.md", title="Older History", body="Older module history.", module="older")
    _write_doc(
        older / "2026-07-19-change.md",
        title="Older Change",
        body="An older module change.",
        module="older",
        date="2026-07-19",
    )
    _write_doc(newer / "README.md", title="Newer History", body="Newer module history.", module="newer")
    _write_doc(
        newer / "2026-07-22-change.md",
        title="Newer Change",
        body="A newer module change.",
        module="newer",
        date="2026-07-22",
    )
    monkeypatch.setattr(knowledge_service, "ROOT", tmp_path)

    rows = knowledge_service.list_module_history_areas()

    assert [row["module"] for row in rows] == ["newer", "older"]
    assert rows[0]["entry_count"] == 1
    assert rows[0]["latest_date"] == "2026-07-22"


def test_payload_groups_manifest_sources_and_preserves_pdf_pages(tmp_path, monkeypatch):
    core = tmp_path / "docs" / "README.md"
    adr = tmp_path / "docs" / "adr" / "0006-kms.md"
    history = tmp_path / "docs" / "history" / "platform-knowledge" / "README.md"
    _write_doc(core, title="Documentation Index", body="Indexes the authoritative TIS documentation.")
    _write_doc(
        adr,
        title="Documentation As Source",
        body="Keeps reviewed Markdown authoritative.",
        status="Accepted",
        date="2026-07-20",
    )
    _write_doc(
        history,
        title="Platform Knowledge History",
        body="Tracks the owner Knowledge Center.",
        module="platform-knowledge",
    )

    pdf_path = tmp_path / "static" / "docs" / "booklet.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-test")
    manifest_path = pdf_path.parent / "docs_manifest.json"
    included = []
    for page, path in ((6, core), (20, adr), (30, history)):
        included.append(
            {
                "path": path.relative_to(tmp_path).as_posix(),
                "modified_at": knowledge_service._iso_mtime(path),
                "sha256": knowledge_service._sha256(path),
                "pdf_page": page,
            }
        )
    manifest_path.write_text(
        json.dumps(
            {
                "documentation_version": "3.1",
                "included_source_files": included,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(knowledge_service, "ROOT", tmp_path)
    monkeypatch.setattr(knowledge_service, "PDF_PATH", pdf_path)
    monkeypatch.setattr(knowledge_service, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(knowledge_service, "REQUIRED_DOCUMENTS", {})

    payload = knowledge_service.get_knowledge_center_payload()

    assert [group["label"] for group in payload["source_groups"]] == ["Core", "Decisions", "History"]
    assert [source["pdf_page"] for source in payload["sources"]] == [6, 20, 30]
    assert payload["sources"][0]["title"] == "Documentation Index"
    assert payload["sources"][0]["summary"] == "Indexes the authoritative TIS documentation."
    assert next(source for source in payload["sources"] if source["path"].startswith("docs/adr/"))["summary"] == (
        "Keeps reviewed Markdown authoritative."
    )
    assert payload["adrs"][0]["pdf_page"] == 20
    assert payload["module_history_areas"][0]["pdf_page"] == 30


def test_knowledge_center_template_uses_protected_page_links_and_local_filters():
    templates = Path(__file__).resolve().parents[1] / "templates"
    template = (templates / "platform_knowledge_center.html").read_text(encoding="utf-8")
    Environment(loader=FileSystemLoader(templates)).get_template("platform_knowledge_center.html")

    assert 'id="knowledgeSearch"' in template
    assert 'id="knowledgeCategory"' in template
    assert 'id="knowledgeModule"' in template
    assert 'id="knowledgeFreshness"' in template
    assert 'href="/platform/knowledge/booklet#page={{ source.pdf_page }}"' in template
    assert "/static/docs/TIS_Project_Reference_Booklet.pdf" not in template
