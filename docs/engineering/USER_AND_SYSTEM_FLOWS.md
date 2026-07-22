---
title: TIS User And System Flows
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS User And System Flows

This document describes the major end-to-end flows a developer must understand before changing TIS.

## Public Customer Flow

Flow:

1. Public visitor opens `https://tisplatform.com`.
2. Visitor clicks a signup/get-started path.
3. Visitor reaches SaaS signup at `/saas/signup`.
4. SaaS account is created.
5. Email verification is completed when required.
6. User signs into SaaS account through `/saas/login`.
7. User enters `/saas/account`.
8. User completes organization onboarding:
   - organization details,
   - contacts,
   - branches,
   - academic setup,
   - review.
9. User chooses Request Demo or Subscribe Now.
10. Subscribe Now continues to plan selection and the existing Paddle checkout path.
11. Paddle handles payment.
12. Return/cancel page informs the user of checkout navigation result.
13. Paddle webhook confirms payment.
14. Local payment/billing state is updated.
15. Pending organization becomes ready for provisioning.
16. Platform owner reviews/runs provisioning.
17. Operational tenant structures are created.
18. Operational login becomes available through `/login`.

Guardrails:

- Checkout return is not authoritative payment confirmation.
- Public signup must not directly create operational tenant data.
- Provisioning should occur only through the approved flow.

## Demo Request Flow

1. A verified customer completes organization, contact, branch, academic, and review onboarding.
2. TIS presents Request Demo and Subscribe Now.
3. Request Demo revalidates account ownership, verification, onboarding completeness, branch configuration, and absence of conflicting payment/provisioning state.
4. TIS creates one Pending Review SaaS demo request with classification, commercial-state, and entitlement snapshots.
5. The customer can view status and withdraw only while Pending Review.
6. A Platform Owner searches, filters, and sorts the review queue.
7. Approval creates a review record only; rejection requires a reason; owner cancellation is allowed only while pending.
8. Each action creates durable audit and internal-notification events.

Guardrails:

- No request or approval creates a SchoolGroup, workspace entitlement, checkout, payment, or Paddle record.
- Duplicate pending requests and invalid terminal transitions fail closed.
- Non-owner platform users and tenant/customer identities cannot access review actions.
- M8B-3 does not send email or provision/activate demos.

## SaaS Identity Flow

Flow:

1. User signs up through `/saas/signup`.
2. SaaS account/session records are created.
3. User signs in through `/saas/login`.
4. Account dashboard is available at `/saas/account`.
5. User can access profile, sessions, security, billing status, and onboarding state.

Important distinction:

- SaaS account identity is not the same as operational tenant user identity.
- Platform identity is also separate.

Guardrails:

- Do not merge SaaS accounts with operational users unless an approved provisioning flow creates the needed operational records.
- Keep SaaS authentication and operational authentication boundaries clear.

## Payment Flow

Flow:

1. User selects a plan.
2. App creates or references a checkout session.
3. User goes to Paddle checkout.
4. User returns through checkout return or cancel pages.
5. Paddle sends webhook events.
6. Webhook-confirmed payment updates local payment/billing state.
7. Verified payment can make a pending organization ready for provisioning.

Guardrails:

- Webhook confirmation is authoritative.
- Do not use return-page navigation as proof of payment.
- Keep Paddle-specific details inside `saas/` payment/client service boundaries.

## Active Subscription Management Flow

1. Authorized billing administrator opens `/saas/subscription`.
2. TIS resolves one confirmed active subscription, entitlements, lifecycle state, paid/active branch capacity, and allowed actions.
3. Quantity or plan changes are previewed through Paddle; TIS displays provider-returned totals and never recalculates proration.
4. Immediate increases/upgrades use provider payment-failure prevention and remain locally pending until authoritative confirmation.
5. Reductions/downgrades are scheduled for the next billing boundary and retain current local access until verified effective evidence.
6. Scheduled plan or quantity changes may be canceled or replaced before their effective boundary when provider state agrees.
7. Cancellation is scheduled at period end; reversal removes the provider-scheduled cancellation after reauthorization and validation.
8. The centralized lifecycle resolver exposes only actions valid for current provider/local state.
9. Billing history is read from Paddle transactions. Invoice download reauthorizes the user and requests a fresh provider URL.

Guardrails:

- provider and local ownership must match,
- active branch usage cannot exceed a requested reduced capacity,
- webhook processing is idempotent,
- ambiguous outcomes enter manual review,
- return pages and local requests are not payment confirmation.

## Provisioning Flow

Flow:

1. Pending organization has completed required onboarding.
2. Payment is verified or owner-approved readiness is satisfied.
3. Provisioning job is queued or run.
4. Operational records are created or connected:
   - school group,
   - branch,
   - academic year,
   - initial operational user,
   - permissions/role context,
   - required setup defaults.
5. Provisioning status is updated.
6. Activation/access email may be sent.
7. User enters operational portal through `/login`.

Guardrails:

- Keep provisioning idempotent where possible.
- Do not mix school groups.
- Do not skip platform owner visibility.

## Operational Login Flow

Flow:

1. User opens `/login`.
2. Credentials are verified.
3. Active-user status is checked.
4. Platform users route toward platform context.
5. Tenant users receive branch/year scope.
6. Session and scope cookies are set.
7. User lands on `/platform` or `/dashboard`.
8. Middleware enforces route permissions.

Guardrails:

- Preserve platform vs tenant branching.
- Preserve idle timeout behavior for tenant users.
- Do not bypass permission middleware.

## Platform Owner Flow

Flow:

1. Platform owner logs in through `/login`.
2. Owner lands in platform context.
3. Owner uses `/platform` for organization context and owner/developer controls.
4. Platform Console pending counts include only organizations still requiring setup, review, payment, or incomplete/recoverable activation work.
5. Owner opens Pending Queue for current work or Organization Records for active, completed, rejected, and lifecycle-review history.
6. Owner uses SaaS admin pages for payments and provisioning.
7. Owner can inspect Workspace UUID, Classification, and Lifecycle as read-only metadata on `/platform`.
8. Owner uses `/platform/knowledge` to review KMS health.
9. Owner views/downloads the PDF through protected routes:
   - `/platform/knowledge/booklet`
   - `/platform/knowledge/booklet/download`

Guardrails:

- Platform developers are not owners.
- Owner-only pages must use existing owner access helpers.
- Active tenant evidence takes precedence over stale onboarding status; conflicting completed evidence is labeled Lifecycle Review Required and excluded from the normal pending queue.
- Do not expose KMS PDF through direct static links.
- Workspace classification metadata does not authorize access or change commercial state in M8B-1.

## Workspace Classification Diagnostic And Backfill Flow

1. Operator runs `scripts/diagnose_workspace_classification.py` to inspect every SchoolGroup and its tenant, onboarding, and Paddle relationship presence.
2. Operator runs `scripts/backfill_workspace_classification.py` without `--apply` for a read-only plan.
3. After review, operator reruns with `--apply`.
4. One transaction classifies all pre-M8B-1 records as internal sandbox/test data and records an idempotency marker.
5. A repeated apply reports `already_applied` and changes nothing.

Guardrails:
- The diagnostic and dry run do not change rows.
- Apply does not call Paddle, migrate Al-Andalus, convert workspaces, or change payment/provisioning state.
- Failures roll back the full backfill transaction.

## Commercial State Resolution Flow

1. Resolve the SchoolGroup workspace classification and lifecycle.
2. Resolve exactly one effective workspace entitlement, or use the compatibility-only implicit entitlement for an internal sandbox created outside migration.
3. Validate entitlement type against workspace classification and parse explicit values through the shared entitlement catalog.
4. For customer-paid workspaces, resolve the existing M7 confirmed subscription entitlement and require the linked local `PaymentSubscription` to match.
5. Resolve each branch as inherited, explicitly active, or commercially inactive while independently respecting operational branch status.
6. Return a read-only effective commercial state or fail closed to Manual Review Required.

Guardrails:
- No resolver writes rows or calls Paddle.
- No resolver changes current tenant access, feature checks, branch mutations, onboarding, or provisioning.
- Demo expiration and commercial-state mutation remain later work.
- Cross-tenant and orphan branch entitlement relationships fail closed.

## Knowledge Management Flow

Flow:

1. Developer or Codex reads `docs/AI_PROJECT_CONTEXT.md`.
2. Developer reads master context, project state, engineering docs, relevant ADRs, and module history.
3. Approved change is implemented.
4. `.kms-impact.yml` and the human-readable Knowledge Impact Assessment are completed.
5. Relevant docs are updated:
   - master context,
   - project state,
   - change history,
   - ADRs if needed,
   - module history if needed,
   - AI project context if needed,
   - engineering docs if architecture/module/flow understanding changed.
6. PDF generator runs.
7. PDF snapshot and manifest are regenerated.
8. Knowledge Center checks manifest freshness and health.
9. CI compares the declaration with changed files and blocks stale pull requests, `dev` integration, or `master` deployment.

Guardrails:

- Markdown remains source of truth.
- PDF is generated and must not be edited manually.
- App must not silently rewrite source docs.
- Regenerate button is not implemented yet.

## Human / AI Developer Onboarding Flow

Flow:

1. Read `docs/AI_PROJECT_CONTEXT.md`.
2. Read `docs/README.md`.
3. Read `docs/TIS_MASTER_CONTEXT.md`.
4. Read `docs/PROJECT_STATE.md`.
5. Read `docs/engineering/TIS_MODULE_MAP.md`.
6. Read `docs/engineering/REPOSITORY_ARCHITECTURE.md`.
7. Read `docs/engineering/USER_AND_SYSTEM_FLOWS.md`.
8. Read relevant ADRs and module history.
9. Inspect code with `rg` before editing.
10. Make scoped changes only.
11. Update KMS docs and regenerate the PDF if needed.
12. Report the KIA.

Before coding, inspect:

- affected routes,
- models and scope fields,
- permission rules,
- templates/forms,
- tests for the touched module,
- related docs/ADRs/history.

After coding, update:

- `docs/CHANGE_HISTORY.md` for meaningful changes,
- module history for area-specific changes,
- ADRs for major decisions,
- engineering docs when module maps, architecture, or flows change,
- AI context when onboarding truth changes,
- project state when priority/status changes.
