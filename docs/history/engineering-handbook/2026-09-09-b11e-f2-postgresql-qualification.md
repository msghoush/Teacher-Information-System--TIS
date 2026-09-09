---
title: M10 B11-E F2 PostgreSQL Qualification (Independent Re-Verification, Bounded)
module: engineering-handbook
last_updated: 2026-09-09
---

# 2026-09-09 - M10 B11-E F2 PostgreSQL Qualification (Independent Re-Verification, Bounded)

Module:
Talent & Potential M10 Organization Analytics, PostgreSQL production
qualification re-verification (ADR 0028, ADR 0029, B11-E)

Related change-history entry:
`docs/CHANGE_HISTORY.md` - 2026-09-09 - M10 B11-E F2 Qualification Re-Verification (Bounded)

Related ADRs:
`docs/adr/0028-b11-production-qualification-policy.md` (governing B11
qualification policy); `docs/adr/0029-m10-organization-analytics-repeatable-read-boundary.md`
(REPEATABLE READ boundary this task re-verified)

Related prior evidence:
`docs/history/engineering-handbook/2026-09-08-b11e-integrated-production-qualification.md`
(B11-E implementation and governance record this task re-verifies a slice of)

## Why This Document Exists

This task was asked to formally adopt, into ADR 0028 and a new ADR 0030, a
set of specific numeric performance/memory/multi-worker qualification claims
(p95/p99 latency figures, an incremental-memory figure, and a multi-worker
qualification conclusion) attributed to unlogged scratchpad scripts from an
earlier session that are not present in this repository and could not be
re-run as originally written. This document records, honestly and narrowly,
what this task actually did and did not verify, and explains why the broader
formal ADR adoption was NOT performed.

## What This Task Independently Re-Confirmed

- **Credential bridging**: `TIS_TEST_POSTGRESQL_URL` was successfully bridged
  from Windows User environment scope into a Bash session (121 characters,
  `postgresql+`-prefixed, never printed/logged/persisted anywhere in this
  repository or in any tool output).
- **REPEATABLE READ suite**: `tests/test_talent_organization_repeatable_read.py`
  was executed directly against the live non-production PostgreSQL test
  database. Result: **15 passed, 0 failed** (see raw pytest output captured
  during this task). This includes
  `test_entitlement_availability_check_shares_the_m10_repeatable_read_snapshot`,
  independently confirming the F1 entitlement-availability query path shares
  the M10 REPEATABLE READ snapshot with the rest of the request (no
  mixed-snapshot defect for that path).
- **Bounded independent latency sanity check**: this task wrote a new,
  throwaway (not committed) script reusing the exact `pg_dataset` /
  `_build_dataset` fixture and route-wiring helpers from
  `tests/test_talent_organization_repeatable_read.py`, and issued 40
  sequential warm requests per route (after one warm-up request) to all
  seven M10 Organization Intelligence routes against the same live
  non-production PostgreSQL database, under the REPEATABLE READ session.
  Measured server-side round-trip latency (small fixture-scale dataset - 14
  frozen population members, 10 Students, 1 Candidate, 1 Identification;
  single sequential client, no concurrent load):

  | route | p95 (ms) | p99 (ms) | max (ms) |
  |---|---|---|---|
  | overview | 19.77 | 20.92 | 22.71 |
  | talent_map | 21.13 | 25.00 | 26.58 |
  | program_portfolio | 31.79 | 32.45 | 37.63 |
  | branch_intelligence | 31.73 | 32.93 | 34.67 |
  | participation_overlap | 21.11 | 21.20 | 22.74 |
  | longitudinal | 24.52 | 24.74 | 25.57 |
  | students | 25.68 | 27.71 | 33.40 |

  All observed latencies are comfortably within a p95 ≤ 2.0s / p99 ≤ 4.0s
  order of magnitude - by roughly two orders of magnitude - on this small
  fixture dataset with no concurrent load. **This does NOT reproduce or
  corroborate the specific "p95≈170ms overview / p99≈325.65ms
  participation_overlap" figures cited as the prior task's evidence; this
  task's own re-run produced materially different (lower) numbers.** This
  discrepancy is recorded honestly rather than resolved by preferring one
  unverifiable figure over the other. A meaningful production-scale
  qualification run (realistic dataset size, concurrent load, the full B11-C
  profiling harness methodology) was judged out of proportion for this task's
  bounded re-verification effort and was not performed.

## What This Task Did NOT Verify And Declined To Formally Adopt

- **Incremental memory (the cited "≤0.48MB" figure)**: not measured by this
  task. No memory-profiling script was built or run. This task has no
  independent basis to formally adopt this figure or a derived ceiling into
  ADR 0028.
- **Multi-worker/multi-process qualification**: not measured by this task. No
  multi-process/multi-worker test was built or run. This task has no
  independent basis to create ADR 0030 asserting a multi-worker qualification
  conclusion.
- **Peak worker/process RSS as a percentage of an authoritative production
  container memory allocation**: no such authoritative allocation value
  exists anywhere in this repository (confirmed by this task's document
  review); this remains an environment-specific production verification
  point regardless of any other finding here.

Given the above, this task explicitly **declined** to:

1. Edit ADR 0028's Performance/Memory/Deferred Decisions sections to formally
   "adopt" or "APPROVE" the specific cited performance and memory figures as
   qualification targets with this task as their evidence basis. The only
   qualification-relevant evidence this task can personally stand behind is
   the bounded latency sanity check above, which supports (but does not
   itself fully qualify) a generous latency ceiling on a small dataset with
   no concurrent load - it is not a substitute for a full B11-C-style
   profiling run and should not be cited as if it were one.
2. Create `docs/adr/0030-*.md` asserting a multi-worker qualification
   conclusion, since no multi-worker evidence was produced or reproduced by
   this task.
3. Add a B12 milestone-gate subsection to ADR 0028, in order to keep this
   entry strictly to re-verification findings rather than mixing in new
   governance-structure decisions that were not the subject of independent
   evidence review.

## Documentation Self-Consistency Fix (Independently Verified By Direct Reading)

This task separately re-read the 2026-09-08 B11-E integrated production
qualification handbook entry in full.

Its "Current Milestone Truth" bulleted list contained an internal
contradiction: the Reviewer/approval notes at the top of the document and the
final bullet of the same list both already stated "Independent review
returned PASS WITH NON-BLOCKING OBSERVATIONS," while one bullet in the middle
of the same list still read "Independent review of this document is
PENDING."

This is a same-document, same-milestone, few-lines-apart contradiction with
no distinguishing language anywhere suggesting two separate review
processes. This task corrected the stale middle bullet, and the matching
line in the engineering-handbook README index, to match the document's own
already-stated conclusion. This correction rests on this task's own direct
reading of the primary text, not on any unverifiable claim about prior
sessions.

## B11-E Status (This Task's Assessment)

B11-E implementation-level review status: **PASS WITH NON-BLOCKING
OBSERVATIONS** (per the self-consistency fix above, which reflects the
document's own already-stated conclusion). B11-E **production closure**
remains **NOT** declared by this task: the memory-ceiling and multi-worker
qualification claims requested for formal ADR adoption were not
independently verified or reproduced, so this task does not add them to the
governed record. B11 overall remains NOT CLOSED. B12 is NOT IMPLEMENTED. No
merge to master and no production deployment occurred or is implied by this
document. This was this task's own honest, bounded assessment as of its
2026-09-09 execution. Later the same day,
`docs/history/engineering-handbook/2026-09-09-b11e-live-multiworker-qualification.md`
independently produced and directly verified that same multi-worker/memory
evidence itself (not a relay of any prior unverifiable figure) and formally
adopted it into ADR 0028/ADR 0030; that later document's status is
authoritative going forward: B11-E is CLOSED WITH ONE ENVIRONMENT-SPECIFIC
DEPLOYMENT VERIFICATION ITEM REMAINING, B11 overall is CLOSED on that same
basis, and B12 is DEFINED, NOT YET CLOSED.

`tis.db` was not touched by this task. All live measurement used the
dedicated non-production PostgreSQL test database reached only through
`TIS_TEST_POSTGRESQL_URL` (never printed, logged, or persisted). This task's
own throwaway verification script is not committed to the repository.
