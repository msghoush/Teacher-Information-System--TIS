---
title: TIS Documentation Dependency Map
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Documentation Dependency Map

This document explains how KMS documents relate to each other and how changes propagate.

## Dependency Model

```text
Master Context
  -> Project State
  -> Engineering Handbook
  -> AI Project Context
  -> ADR
  -> History
  -> Knowledge Center
  -> Manifest
  -> PDF
```

The arrows show common reading and propagation flow. They are not strict ownership hierarchy.

## Master Context

Purpose:
Durable product, architecture, workflow, roadmap, and critical-rule truth.

Update when:

- long-term architecture changes,
- product vision changes,
- major workflow changes,
- critical rules change,
- KMS structure changes.

## Project State

Purpose:
Current branch, priority, milestone, known issue, and next-work truth.

Update when:

- active priority changes,
- phase status changes,
- known issues change,
- next planned work changes.

## Engineering Handbook

Purpose:
Developer-facing deep knowledge: modules, repository, flows, database, standards, design, roadmap, governance, AI guidance, rejected decisions.

Update when:

- developer understanding changes,
- module maps change,
- architecture or data ownership changes,
- standards/governance changes,
- future onboarding would be incomplete.

## AI Project Context

Purpose:
Compact first-read file for future AI coding conversations.

Update when:

- first-read onboarding changes,
- major docs are added,
- current priority changes,
- critical boundaries change.

## ADR

Purpose:
Accepted major decision record.

Update when:

- a major architectural/product decision is made,
- a prior decision is superseded,
- a decision needs formal traceability.

## Rejected Decisions

Purpose:
Record important alternatives that were declined.

Update when:

- future teams are likely to reconsider a rejected path,
- a rejected alternative explains the chosen architecture.

## History

Purpose:
Chronological and module-specific evolution.

Update when:

- meaningful change occurs,
- module before/after state matters,
- project knowledge changes.

## Knowledge Center

Purpose:
Owner-facing app view of KMS health, freshness, and protected PDF access.

Update when:

- KMS metadata behavior changes,
- Knowledge Center UI/status behavior changes,
- protected documentation access changes.

## Manifest

Purpose:
Generated metadata for PDF and source freshness.

Update when:

- PDF is regenerated.

Do not edit manually.

## PDF

Purpose:
Generated handbook snapshot.

Update when:

- included Markdown docs change.

Do not edit manually.

## Propagation Examples

Feature changes workflow:

```text
Implementation -> CHANGE_HISTORY -> module history -> master/project state if needed -> PDF/manifest
```

Architecture decision workflow:

```text
Decision -> ADR -> rejected decision if relevant -> master context -> engineering handbook -> change history -> PDF/manifest
```

Roadmap change workflow:

```text
Roadmap -> PRODUCT_ROADMAP -> PROJECT_STATE -> AI_PROJECT_CONTEXT if first-read truth changed -> PDF/manifest
```

KMS structure change workflow:

```text
KMS docs -> README -> MASTER_CONTEXT -> AI_PROJECT_CONTEXT -> CHANGE_HISTORY -> PDF/manifest
```
