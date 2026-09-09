---
title: Engineering Handbook History
module: engineering-handbook
last_updated: 2026-09-09
---

# Engineering Handbook History

This folder tracks meaningful changes to the TIS Engineering Handbook, including module maps, repository architecture, user/system flows, and onboarding guidance for humans and AI coding conversations.

Cline integration:
- [2026-09-05 Cline KMS configuration](2026-09-05-cline-kms-configuration.md):
  project rules, reusable skill, and flexible three-agent orchestration.

Latest change:

- `2026-09-09-b11e-live-multiworker-qualification.md`: direct live execution
  of the remaining B11-E release-gate evidence - two genuinely independent
  `uvicorn` worker processes against the same live PostgreSQL qualification
  database, real production-configured F1 providers engaged (not test
  doubles), performance sampling (5 of 7 routes, 20 samples each), and a
  self-measured memory profile. On this directly-observed evidence, formally
  adopted the p95<=2.0s/p99<=4.0s performance target and the <=128MB
  incremental-memory target into ADR 0028 (both PASS with substantial
  margin), created ADR 0030 (the >=2-worker qualification minimum and
  no-worker-local-state correctness requirement), and added a B12 (M10
  closeout only) definition to ADR 0028. Classified B11-E as CLOSED WITH ONE
  ENVIRONMENT-SPECIFIC DEPLOYMENT VERIFICATION ITEM REMAINING and B12 as
  DEFINED, NOT YET CLOSED.

- `2026-09-09-b11e-f2-postgresql-qualification.md`: bounded, independent
  re-verification performed earlier the same day - re-ran the
  REPEATABLE READ suite live (15/15 passing) and a bounded single-process
  latency sanity check, and fixed a same-document self-consistency defect in
  the 2026-09-08 entry below. It explicitly declined to formally adopt
  memory-ceiling or multi-worker qualification figures into ADR 0028/ADR 0030
  for lack of independently reproduced evidence - that evidence was supplied
  later the same day by the live-multiworker entry above.

- `2026-09-08-b11e-integrated-production-qualification.md`: governed
  (ADR 0029) and implemented the M10-only REPEATABLE READ transaction
  boundary; live-re-tested all seven Organization Intelligence routes;
  tested suppression/reconstruction concurrency with a real non-production
  deterministic suppressing policy; finalized Index Candidate B (NO CHANGE)
  and statistics-freshness disposition. B11-E independent review returned
  PASS WITH NON-BLOCKING OBSERVATIONS.

- `2026-09-07-b11d-postgresql-concurrency-consistency-qualification.md`:
  durable PostgreSQL 16.15 READ COMMITTED consistency evidence; independent
  review passed with non-blocking observations and B11-D is CLOSED.

- `2026-09-07-b11c-postgresql-profiling-evidence-remediation.md`: durable,
  sanitized PostgreSQL 16.15 evidence for all seven M10 routes; independent
  re-review passed with non-blocking observations and B11-C is CLOSED.

- `2026-09-03-claude-code-kms-configuration.md`: repository-native Claude Code
  entry point, reusable TIS KMS skill, and bounded specialized subagent.
- `2026-07-22-kms-phase-7d-navigation-catalog-enforcement.md`: strict source-title, catalog, navigation-link, source-inventory, and PDF page-bound validation.

Related files:

- `docs/engineering/README.md`
- `docs/engineering/TIS_MODULE_MAP.md`
- `docs/engineering/REPOSITORY_ARCHITECTURE.md`
- `docs/engineering/USER_AND_SYSTEM_FLOWS.md`
