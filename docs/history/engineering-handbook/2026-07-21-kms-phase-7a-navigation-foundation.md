---
title: KMS Phase 7A Navigation Foundation
module: engineering-handbook
date: 2026-07-21
---

# 2026-07-21 - KMS Phase 7A Navigation Foundation

## Previous State

The KMS contained comprehensive core, engineering, ADR, history, marketing, and supporting documentation. Root and engineering README files listed those sources, but readers still had to assemble their own task-specific reading sequence. Three supporting documents also lacked standard title front matter.

## New State

`docs/KMS_NAVIGATION.md` is the canonical role-based and task-based reading guide. It directs human developers, AI assistants, owners, and reviewers to focused document sets with explicit guardrails. Root and engineering indexes now use navigable Markdown links and point to the guide instead of duplicating every reading decision. The location roadmap and both landing-page documents have normalized title metadata.

## Scope Boundary

Phase 7A changes reviewed Markdown navigation only. It does not add generated catalog metadata, PDF table-of-contents behavior, PDF bookmarks, Knowledge Center search/filtering, protected document-reader routes, or new KMS enforcement rules.

## Related Files

- `docs/KMS_NAVIGATION.md`
- `docs/README.md`
- `docs/engineering/README.md`
- `docs/location-data-roadmap.md`
- `docs/marketing/landing_page_source_of_truth.md`
- `docs/marketing/tis_landing_page_master_content.md`
