---
title: KMS Phase 7B Professional PDF Navigation
module: engineering-handbook
date: 2026-07-21
---

# 2026-07-21 - KMS Phase 7B Professional PDF Navigation

## Previous State

The generated booklet preserved all approved Markdown sources in fixed order and provided page footers, but readers had to move through a long linear document. The manifest tracked source freshness without recording where each source began in the PDF.

## New State

The existing ReportLab generator now provides:

- a dedicated "How to Use This Handbook" page,
- a multi-pass table of contents with source-document page numbers,
- stable named destinations and outline entries for every source document,
- child outline entries for H2 major headings,
- each source document's starting `pdf_page` in the generated manifest,
- strict validation for missing, invalid, or non-increasing source pages.

Bookmark identifiers are derived deterministically from repository-relative source paths and heading context. Existing source ordering, normalized Markdown hashing, source-list comparison, PDF identity checks, and freshness validation remain in force.

## Scope Boundary

Phase 7B does not change the Platform Owner Knowledge Center UI, add routes, add dependencies, alter Markdown authority, modify application behavior, or introduce database changes. Phase 7C remains separate.

## Related Files

- `scripts/generate_docs_pdf.py`
- `tests/test_kms_automation.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`
