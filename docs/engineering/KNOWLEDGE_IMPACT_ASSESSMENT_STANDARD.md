---
title: TIS Knowledge Impact Assessment Standard
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS Knowledge Impact Assessment Standard

The Knowledge Impact Assessment (KIA) is a required engineering standard. It confirms whether a task changed project knowledge and whether the KMS was kept current.

## Required KIA Fields

```md
Knowledge impact: Yes/No
Docs updated:
Change history updated: Yes/No
ADR needed: Yes/No
Module history updated: Yes/No
PDF regenerated: Yes/No
AI project context updated: Yes/No
Reason if not updated:
```

The same decision must be recorded in `.kms-impact.yml` for machine validation. The repository declaration adds `summary`, `affected_areas`, `kms_files_updated`, `no_impact_reason`, and `major_change_override`.

## Decision Tree

Ask:

1. Did behavior change?
2. Did architecture change?
3. Did a workflow change?
4. Did a module boundary change?
5. Did data ownership or tenant scope change?
6. Did SaaS/payment/provisioning change?
7. Did UI/UX or customer language change?
8. Did roadmap or current state change?
9. Did development standards/governance change?
10. Would a future developer or AI assistant need to know this?

If any answer is yes, knowledge impact is probably yes.

## Checklist

For knowledge-impacting work:

- update relevant source docs,
- update `docs/CHANGE_HISTORY.md`,
- update module history if module state changed,
- update ADRs if major decisions changed,
- update rejected decisions if an important alternative was declined,
- update AI project context if first-read truth changed,
- regenerate PDF/manifest,
- report validation.
- update `.kms-impact.yml` and run `scripts/check_kms_impact.py`.

## Examples

### Example: Docs Updated

```md
Knowledge impact: Yes
Docs updated:
- docs/TIS_MASTER_CONTEXT.md
- docs/CHANGE_HISTORY.md
- docs/history/provisioning/...
Change history updated: Yes
ADR needed: No
Module history updated: Yes
PDF regenerated: Yes
AI project context updated: No
Reason if not updated: AI onboarding truth did not change.
```

### Example: No Docs Needed

```md
Knowledge impact: No
Docs updated: None
Change history updated: No
ADR needed: No
Module history updated: No
PDF regenerated: No
AI project context updated: No
Reason if not updated: Change was limited to a typo in an internal variable name and did not affect behavior, architecture, workflow, roadmap, or developer knowledge.
```

## Approval Expectations

Reviewers should reject final reports that omit KIA.

If docs were skipped, the reason must be specific. "Not needed" is not enough.

## Failure Cases

KIA fails when:

- final report omits it,
- meaningful behavior changed but docs did not,
- docs changed but PDF/manifest were not regenerated,
- ADR-worthy decisions were hidden in code changes,
- module state changed without module history,
- AI context became stale after major onboarding truth changed.
- `.kms-impact.yml` is missing, stale, inconsistent with the Git diff, or uses an unexplained override.
- generated-artifact validation fails.

## Developer Responsibilities

Developers must:

- assess KIA honestly,
- update docs in the same task,
- keep generated artifacts current,
- avoid unrelated documentation churn,
- preserve historical truth.

## AI Responsibilities

AI assistants must:

- read relevant docs before coding,
- identify likely KMS impact,
- not invent history,
- not silently skip docs,
- not commit or push unless requested,
- include KIA in every implementation final report.
