---
title: TIS User And System Flows
documentation_version: 3.1
last_updated: 2026-07-29
source_of_truth: true
---

# TIS User And System Flows

## Combined Subscription Capacity And Custom Contact

1. Each active onboarding branch supplies required non-negative system-user and
   teacher estimates; TIS sums them across the organization.
2. Before payment, system-user and teacher authority is independently the
   greater of the estimate total and actual same-workspace active data. After
   activation, actual active data is authoritative. Teacher login accounts are
   excluded from system users while their teacher records still count.
3. A self-service plan is eligible only when all three counts fit: Starter is
   1 branch/5 system users/25 teachers, Professional 5/20/100, and Enterprise AI
   25/100/500.
4. The lowest eligible plan is recommended; higher eligible plans remain
   selectable. Ineligible cards explain every failed dimension. Exceeding
   twenty-five branches, 100 system users, or 500 teachers emphasizes the
   always-visible Custom contact action.
5. Selection and every quote, checkout, Paddle, and payment-validation boundary
   repeats the same server-side decision.
6. A pre-payment branch estimate change retains an eligible higher
   plan, but clears an undersized selection and supersedes its checkout and
   attempt so stale payment cannot activate the workspace.
7. On a paid workspace, non-teacher system-user creation/reactivation and
   teacher creation/year-copy preflight require remaining capacity. Blocked
   operations create no partial user or teacher data.
8. A downgrade is blocked separately by current branches, system users, or
   teachers. Existing data is preserved.

The separate Next.js landing page presents the same four-plan structure and
organization-wide limits. The hero Subscribe Now action scrolls to pricing.
Starter, Professional, and Enterprise AI retain their published monthly and
annual per-active-branch prices and enter the configured public signup route
with an allowlisted preferred-plan code. That code is a presentation
preference only: signup creates no plan selection, checkout, payment attempt,
or Paddle object. After organization setup, TIS applies it only when the live
plan remains active and eligible across branches, system users, and teachers;
otherwise TIS clears it and asks the customer to review eligible plans. Custom
has no fixed public price, uses only the Contact the TIS Team mail action, and
never starts signup or Paddle checkout.

## Initial Subscription Plan Capacity

1. TIS counts the current organization's authoritative active billable
   branches.
2. Starter is eligible for one branch, Professional for up to five, and
   Enterprise AI for up to twenty-five. Higher-capacity plans remain available
   below their limits.
3. Plan cards retain per-branch pricing and explain their branch and staff
   limits. Ineligible plans are disabled; above twenty-five branches the
   customer is directed to contact the TIS team for a custom plan.
4. The server repeats the capacity decision during selection, quote creation,
   checkout preparation and launch, and payment validation.
5. If pre-payment editing makes the selected plan too small, TIS clears that
   selection, supersedes its quote and checkout lineage, and requires a new
   eligible plan. An eligible higher plan remains selected.
6. After activation, branch-capacity changes continue through Subscription
   Management.

## Fixed-Quantity Initial Checkout

1. Before confirmed payment, customers may add, edit, remove, reorder, or
   reprioritize onboarding branches while keeping at least one active branch.
   A demo SchoolGroup, tenant link, customer, or prepared checkout does not
   close editing.
2. If branches change after checkout preparation, TIS supersedes the local
   checkout and attempt, clears the old quote lineage, and recalculates from the
   new active count. A late old transaction event cannot activate that quote.
3. TIS resolves the selected plan, billing interval, active billable branches,
   unit price, and total for the current organization.
4. The customer reviews those values in TIS.
5. TIS creates one Paddle transaction item using the mapped provider price and
   the exact authoritative branch quantity; quantity is never defaulted to one.
6. The resolved customer address makes the automatically collected transaction
   ready. Returned item quantity, price, subtotal, and quote fingerprint must
   agree with TIS before the transaction is marked billed.
7. The payment launcher passes only the billed transaction ID to Paddle inline
   checkout after verifying the local attempt, organization, customer, quote,
   and remote billed status. Billed transaction items and quantities are
   immutable; draft, ready, canceled, past-due, unrelated, or mismatched
   transactions are not launched.
8. Paddle completion remains the recurring-subscription authority. Later branch
   changes use the established TIS subscription-quantity workflow.

## Returning Customer Login And Expired Demo Subscription

1. SaaS login authenticates and resolves authoritative onboarding, demo,
   workspace-link, lifecycle, and subscription state.
2. Incomplete setup resumes; pending demos open request status; unpaid completed
   setup opens subscription selection; active demo or paid customers continue
   to operational login.
3. Expired demos or paid subscriptions open branded recovery guidance.
4. Operational login runs the commercial guard before branch and academic-year
   setup. Protected requests run it before page services. Authentication,
   sign-out, SaaS account, subscription/checkout/payment-return, support, and
   expiry routes remain safe and cannot recursively redirect.
5. Expired-demo Subscribe Now resolves the existing organization, SchoolGroup,
   and active operational branches, offers public plans and monthly/annual
   intervals, then launches existing Paddle checkout.
6. Only confirmed provider payment converts the same workspace UUID, tenant
   link, users, permissions, branches, and data.

## Platform Owner Demo Operations

1. A Platform Owner opens an existing Customer Demo operational detail.
2. The owner supplies required reason/date/configuration and an operation key.
3. The service validates and locks the same workspace and tenant scope.
4. Lifecycle work reuses M8B7 rules; feature policy uses controlled registries.
5. Material changes create durable customer email/Notification Center records,
   and every attempt records before/after/result references.
6. Profile changes retain usage and never convert the Customer Demo to paid.

## M8B8 AI Entitlement And Consumption Flow

1. Resolve the operational SchoolGroup and reject cross-tenant scope.
2. Require the registered feature's underlying `ai.use` permission.
3. Resolve existing commercial state; demo expiry/restriction takes precedence.
4. Resolve the controlled feature definition.
5. Internal Sandbox is unlimited; Customer Demo checks two successful uses per
   feature; Customer Paid checks eligible plan plus `module.ai`.
6. Reserve an operation key under the locked successful-plus-reserved limit.
7. If reserved, execute the real AI operation outside the entitlement service.
8. Finalize a usable result as successful consumption; finalize failure without
   consumption and release the reservation.

There are currently no executable AI routes, so steps 6-8 are a reusable
contract rather than a fabricated customer feature.

## M8B7 Demo Customer Journey

Submission creates pending status, a request-received email intent, and owner Notification Center events. Normal approval records review evidence then invokes the retryable provisioning service; activation communication exists only after success. Day 6 and expiry create lifecycle events, customer notices, owner notifications, and email intents atomically. Provider delivery occurs outside locks. A coherent expired demo may subscribe and, after authoritative confirmed payment, reactivate and convert the same workspace.

This document describes the major end-to-end flows a developer must understand before changing TIS.

## Public Customer Flow

Flow:

1. Public visitor opens `https://tisplatform.com`.
2. Visitor chooses Request a Demo or Subscribe Now.
3. Visitor reaches SaaS signup at `/saas/signup?intent=demo` or `/saas/signup?intent=subscribe`.
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
9. The final commercial-choice page emphasizes the saved intent, while the user may still choose Request Demo or Subscribe Now.
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
3. Request Demo revalidates account ownership, verification, onboarding completeness, branch configuration, absence of conflicting payment/provisioning state, and normalized organization-domain eligibility.
4. TIS creates one Pending Review SaaS demo request plus a transactionally unique customer-demo eligibility reservation for the normalized organization domain.
5. The customer can view status and withdraw only while Pending Review.
6. A Platform Owner searches, filters, and sorts the review queue.
7. Approval creates a review record only; rejection requires a reason; owner cancellation is allowed only while pending.
8. A Platform Owner separately starts provisioning for an Approved request.
9. TIS revalidates review evidence, customer-demo intent, commercial/entitlement snapshots, organization completeness, and duplicate absence.
10. One atomic transaction creates the operational workspace through the shared provisioning builder, creates the demo entitlement and demo-sourced tenant link, activates both, and links the request.
11. Failure rolls back workspace records, leaves the request Approved and unprovisioned, and records a retryable failure outcome.
12. Each review, provisioning, and activation action creates durable audit and internal-notification events.

Guardrails:

- Request and approval alone create no SchoolGroup or entitlement.
- Demo provisioning creates no checkout, payment, paid subscription, subscription contract, or Paddle record.
- A prior customer demo request, activation, expiry, rejection, cancellation, or demo-to-paid conversion for the same normalized organization domain blocks a new customer demo. Platform Owners extend/reactivate where separately allowed, or the customer subscribes using the existing workspace.
- Public email providers require an official organization website or domain before a demo request. Internal Sandbox workspaces do not consume customer demo eligibility.
- Non-owner platform users and tenant/customer identities cannot access review actions.
- Duplicate, rejected, cancelled, incoherent, or already provisioned requests fail closed.
- M8B-4 sends no email and does not implement expiration, scheduling, login blocking, or conversion.

## Historical Demo Eligibility Maintenance Flow

1. A Platform Owner opens `/saas-admin/demo-eligibility-maintenance`.
2. TIS scans the demo-domain eligibility ledger and resolves matching organization, account, request, tenant-profile workspace, provisioning, subscription, conversion, and manual-review evidence.
3. Linked or ambiguous reservations remain protected and display their exact blockers.
4. A safely detached row exposes a review action for its exact eligibility ID.
5. The owner types the same ID and confirms permanent removal.
6. TIS locks and re-analyzes that exact row before deletion.
7. Any new blocker aborts and rolls back the action.
8. TIS deletes only the selected primary key, flushes, verifies no row remains for that ID, and commits.
9. A durable audit event records the Platform Owner, eligibility ID, normalized domain, previous status, timestamp, and historical-cleanup reason.

Guardrails:

- Never delete by normalized domain.
- Never expose the workflow to customers, tenant users, or Platform Developers.
- Never use this workflow to override a linked, historical, converted, subscribed, provisioned, or manual-review Customer Demo reservation.
- Do not change the normal one-demo-per-domain rule or the organization-scoped clean-room reset.

## Customer Demo Lifecycle Flow

1. Successful M8B-4 activation records the authoritative demo start.
2. TIS derives reminder due at start plus six days and expiration at start plus seven days.
3. Before Day 6, the resolver returns Active and operational access continues.
4. At Day 6, the resolver returns Reminder Due; the processor creates one customer notification and one per active Platform Owner.
5. At Day 7, access fails closed immediately even if scheduled processing has not run.
6. Apply-mode processing atomically ends the demo entitlement, suspends the SchoolGroup, marks the demo tenant link expired, and records lifecycle events.
7. Web requests redirect to the preserved-data and subscription page; API/download requests receive a safe 403.
8. Existing sessions are rechecked on every protected request. Platform users remain able to inspect the workspace.

Guardrails:

- Use `activated_at`, never request submission or approval, for lifecycle calculations.
- Store and calculate in UTC; convert only customer/owner display values to the organization timezone.
- Expiration never deletes, archives, deactivates branches, or mutates operational tenant data.
- Reminder and expiration actions are idempotent and failure-audited.
- No email, Paddle change, conversion, extension, or read-only expired mode is included.

## Demo-To-Paid Conversion Flow

1. An active, coherently provisioned Customer Demo chooses Subscribe Now.
2. TIS records a requested conversion and continues through the existing M7 plan selection and Paddle checkout.
3. No new operational workspace, tenant link, branch, user, permission, or academic record is created.
4. `transaction.completed` remains the payment authority and establishes the confirmed `SubscriptionContract` and active `PaymentSubscription`.
5. If the existing tenant link is demo-sourced, webhook reconciliation invokes the dedicated conversion service instead of paid provisioning.
6. The service locks and revalidates the request, provisioning aggregate, SchoolGroup, demo entitlement, tenant link, contract, subscription, price, interval, quantity, and tenant ownership.
7. One atomic workspace transaction ends the demo entitlement, creates the subscription-backed paid entitlement, relinks branch entitlements, changes the SchoolGroup to Customer Paid Active, and moves the same tenant link to the confirmed contract.
8. Existing M7 entitlement, workspace-entitlement, and commercial-state resolvers validate the resulting Customer Paid Active state before commit.
9. Success records completion and lets the customer continue into the same operational workspace. Completed conversions no longer enter demo lifecycle processing.
10. Failure rolls back workspace mutations, preserves provider-confirmed payment records, records a safe retryable failure, and may be retried from a later subscription webhook.

Guardrails:

- Never infer conversion from checkout return navigation, onboarding selection, or an unconfirmed payment attempt.
- Never run paid tenant provisioning for a valid existing demo tenant.
- Expired, suspended, ambiguous, cross-tenant, internal-sandbox, already-paid, and incoherent workspaces fail closed.
- Conversion does not change Paddle pricing, subscription mutation, webhook authority, tenant isolation, or operational permissions.

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
