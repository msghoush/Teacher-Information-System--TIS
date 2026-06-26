---
title: Platform Owner Knowledge Center
module: platform-knowledge
date: 2026-06-26
---

# 2026-06-26 - Platform Owner Knowledge Center

Module:
Platform Knowledge Center

Related change-history entry:
`docs/CHANGE_HISTORY.md` - 2026-06-26 - Added Platform Owner Knowledge Center

Related ADRs:
`docs/adr/0006-documentation-as-source-knowledge-management-system.md`

Reviewer/approval notes:
Approved for Phase 2C. Regenerate button, public access, SaaS changes, database changes, migrations, landing page changes, commits, and pushes remain out of scope.

## Previous Documented State

TIS had KMS Markdown source files, ADRs, module history, a generated PDF booklet, and a manifest, but there was no protected in-app owner utility for viewing KMS status or accessing the booklet.

## New Documented State

TIS has a read-only Platform Owner Knowledge Center that shows KMS health, manifest metadata, PDF freshness, source document status, recent change-history entries, ADRs, module history areas, and the Knowledge Impact Assessment checklist.

## Reason For Change

Platform owners need a protected internal view of KMS status and a safe way to view/download the generated PDF without linking directly to static public paths.

## User / Business Impact

Platform owners can verify whether the KMS snapshot is current and access the reference booklet from inside the app.

## Technical Impact

Adds read-only KMS service helpers, owner-protected FastAPI routes, one app-shell template, and an owner-only Platform Console card. No SaaS, database, migration, billing, provisioning, or landing page behavior changes.

## Documentation Updated

- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/history/platform-knowledge/README.md`
- `docs/history/platform-knowledge/2026-06-26-platform-owner-knowledge-center.md`

## PDF Regenerated

Yes

## Follow-Up Needed

Consider a future explicit owner-only regenerate action after review. The app must not silently rewrite Markdown source docs.
