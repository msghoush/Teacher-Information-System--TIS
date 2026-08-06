---
title: TIS User And System Flows
documentation_version: 3.1
last_updated: 2026-08-06
source_of_truth: true
---

# TIS User And System Flows

## Existing Workspace Owner Alignment And Conversion

1. A Platform Owner runs the M4B CLI in dry-run mode with the exact workspace
   tuple, intended-owner email, current M4A hash, operation UUID, and idempotency
   key. No row is changed.
2. Write preparation requires PostgreSQL, Platform Owner approval/execution
   identities, and `PREPARE <operation UUID>`. It locks the workspace, reruns
   M4A, rejects stale or conflicting evidence, and records an ownership claim.
   It does not create an account or send email.
3. The intended owner registers normally, establishes a password or approved
   external identity, and verifies the exact email. Login continuation opens
   the existing-workspace setup review.
4. The verified owner explicitly claims the workspace. TIS rejects unverified,
   suspended, duplicate, cross-tenant, or platform identities, safely reuses or
   creates the operational owner identity, and creates a `tenant_owner` account
   link with no pending organization. A different current owner requires prior
   transfer approval.
5. The owner confirms existing organization identity and supplies only legal
   name, official IANA timezone, and educational program. Branches and all
   existing operational records remain unchanged.
6. Final CLI execution requires `CONVERT <operation UUID>`. It locks the
   operation and SchoolGroup, performs a fresh M4A audit, and requires unchanged
   identity, branch/dependency evidence, one active internal entitlement, no
   commercial source, complete setup, and unique verified ownership.
7. One commit ends the internal entitlement and sets `customer / provisioning`.
   It creates no replacement entitlement or tenant link. Any failure rolls back
   all conversion changes and records only redacted failure evidence.
8. M1 resolves `activation_required`. Organization Account remains accessible,
   normal operations remain blocked, and M3 promo activation is offered. The
   existing-workspace Paddle path remains hidden until its separate milestone;
   new onboarding checkout is unaffected.

## Existing Workspace Conversion Audit

1. An operator supplies the exact SchoolGroup ID, workspace UUID, expected
   organization name, and intended owner email to the standalone M4A CLI.
2. The CLI requires deployed PostgreSQL and begins a repeatable-read, read-only
   transaction before the first application query.
3. The service validates the exact workspace tuple, resolves normalized owner
   identities and links, and inventories tenant, provisioning, entitlement,
   paid, demo, and promo evidence.
4. For every target branch, the service follows reflected direct and indirect
   foreign-key descendants and separately reports branch-like columns without
   a foreign key. Soft-deleted rows remain blocking. Foreign keys absent from
   ORM metadata force manual review. It returns counts and paths, not private
   row payloads.
5. Identity mismatch, duplicate ownership, existing non-sandbox commercial
   authority, unavailable schema evidence, or uncertain traversal produces
   Manual Review Required. An active internal-sandbox entitlement is expected
   and is not treated as customer authority.
6. The CLI writes deterministic sanitized JSON or text with the observed
   transaction mode and a stable SHA-256 evidence hash. Exit `0` is coherent,
   `1` is execution/configuration failure, `2` is manual review, and `3` is
   identity mismatch. Archival candidates include only active dependency-free
   branches; hard deletion and write conversion remain unapproved.
7. The CLI rolls back and closes. It never archives, deletes, aligns, converts,
   calls Paddle, or sends email.

## Customer Promo Activation

1. A verified organization owner chooses Use Promo Code after setup review or
   from an eligible existing Organization Account.
2. TIS HMAC-normalizes the submitted code, validates approval, lifecycle,
   dates, replacement, target scope, owner relationship, redemption policy,
   source compatibility, and setup readiness, then creates a short-lived
   resumable activation session. The raw code is never stored.
3. TIS shows authoritative branch, system-user, and teacher usage. If eligible
   branches exceed the grant, the owner selects exactly the grant count. If
   fewer exist, all are selected and the remainder stays available for future
   branch creation.
4. Excess staff or teachers blocks activation and identifies each exceeded
   dimension. TIS does not disable, select, delete, or change those records.
5. Final activation locks session, promo, and workspace, then repeats every
   validation and recount. It rejects internal sandboxes and every conflicting
   commercial source.
6. One transaction creates immutable redemption/grant snapshots, explicit
   branch assignments and entitlement states, a promo workspace entitlement,
   the promo-sourced tenant link, customer/active lifecycle, and redacted audit.
7. A pending session grants nothing. Active access resolves through M1 and only
   selected branches are queryable. Expiry or inconsistent evidence fails
   closed. No Paddle call or payment object is involved.

## Platform Promo Definition

1. A Platform Owner or permission-authorized Developer opens Promo Codes.
2. Create validates one active Starter, Professional, or Enterprise AI tier,
   exact positive capacity through the shared plan-capacity service, coherent
   scope anchors, dates, expiry XOR, and redemption policy.
3. TIS generates at least 100 bits of secure random code material, normalizes
   with NFKC/uppercase/separator removal, and derives an HMAC-SHA256 lookup hash
   with `TIS_PROMO_CODE_HMAC_SECRET`. Missing configuration fails closed.
4. The draft and allowlisted audit commit. The raw code appears once in a
   no-store/no-referrer response; subsequent pages show only its mask.
5. A Developer may edit Draft, pause Active, duplicate, or create a linked
   replacement definition when authorized. Active material edits first require
   pause, clear approval, increment version, and return to Draft.
6. Only a Platform Owner may approve/activate or terminally revoke with a
   reason. Lifecycle transitions lock the row through validation, mutation,
   audit insertion, and commit.
7. No Platform definition step grants access or calls Paddle. Customer M3
   activation is a separate owner-authorized transaction.

## Organization Profile Save

1. The customer opens the owned pending organization's Organization Profile.
2. The browser submits the existing multipart POST with a required controlled
   educational-program value and an optional logo.
3. TIS normalizes National, International, or Both and validates all profile
   fields. Customer-correctable input returns the same page with preserved
   text/select values.
4. When a logo is supplied, TIS reads no more than the 4 MB boundary, decodes
   the actual image as PNG/JPG/WEBP, checks dimensions, and ignores the
   customer filename when creating the opaque stored filename.
5. TIS writes the new image to a temporary sibling and atomically promotes it.
6. Organization changes, progress, activity, and events commit together.
   Only after commit is an obsolete prior pending logo removed.
7. If logo storage or a later database step fails, TIS rolls back the
   transaction, removes the newly written file, retains the prior logo
   reference, logs the traceback, and renders a customer-safe error.
8. The successful response redirects to Branch Setup. No duplicate pending
   organization or operational workspace is created.

Pending logo files currently live on the application-local filesystem. Durable
Render operation requires a separately approved persistent disk or object
storage architecture. The owner-only workspace deletion workflow currently
removes database records but does not yet perform transactional cleanup of
pending or promoted organization-logo files on the filesystem.

## Organization Logo Activation

1. Successful Organization Profile save stores a safe relative pending-logo
   path; setup and checkout pages render only its public static URL.
2. Organization Profile and the shared setup identity header show the customer
   logo and organization name while the official TIS mark remains platform
   branding.
3. Checkout does not move or remove the pending image.
4. Paid and demo activation both call `create_workspace_records()`.
5. Provisioning resolves the pending path only inside the pending-logo
   directory, requires the file to exist, decodes it again, and writes a new
   organization-owned branding file.
6. A primary `SchoolGroupLogo` row stores the final relative path and an
   organization-name label. `SchoolGroup` has no direct logo field.
7. The operational shell resolves that row through the protected
   organization-asset route, renders it with contain sizing, and keeps the
   official TIS logo separately visible.
8. Missing pending source data blocks activation for correction instead of
   producing an active workspace with silently lost branding.

## Branch Estimate Rendering And Save

1. The service loads active branch rows and computes capacity totals in Python.
2. Null, missing, or malformed display values contribute zero; mixed valid
   integer values continue to total normally.
3. The template receives normalized totals and renders null row fields as zero,
   avoiding Jinja `int + None` failures.
4. Every customer save still requires explicit non-negative whole-number
   values for estimated system users and teachers.
5. Newly created pending branches receive explicit zero defaults before their
   submitted values are applied.

## Combined Subscription Capacity And Custom Contact

1. Each active onboarding branch supplies required non-negative system-user and
   teacher estimates; TIS sums them across the organization.
2. Before payment, system-user and teacher authority is independently the
   greater of the estimate total and actual same-workspace active data. After
   activation, actual active data is authoritative. Every active tenant
   operational User counts as staff regardless of position, so an operational
   teacher-user with a Teacher record consumes one staff slot and one teacher
   slot.
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
7. On a paid workspace, every tenant operational-user creation/reactivation and
   teacher creation/year-copy preflight requires remaining capacity. Blocked
   operations create no partial user or teacher data.
8. A downgrade is blocked separately by current branches, system users, or
   teachers. Existing data is preserved.

## M1 Operational Commercial-Capacity Enforcement

1. The route first validates the existing permission and tenant scope.
2. TIS locks the owning SchoolGroup with `SELECT ... FOR UPDATE`; internal
   multi-tenant operations acquire locks in ascending SchoolGroup ID order.
3. The commercial authority facade composes classification/lifecycle,
   workspace entitlement, tenant link, contract, confirmed subscription,
   commercial access, demo lifecycle, and plan capacity.
4. The service recounts active branches, distinct active tenant operational
   users, and active teacher people. Known teacher IDs are normalized and
   deduplicated; blank legacy identities each count independently.
5. Paid limits use confirmed branch quantity capped by plan maximum plus the
   plan staff and teacher limits. Pending subscription changes do not increase
   capacity. Demo and Internal Sandbox are unmetered only when their existing
   authority resolves coherently.
6. TIS evaluates deltas or proposed absolute totals across one or several
   dimensions and returns a structured safe decision.
7. Allowed branch, user, teacher, year-switch, or provisioning mutation occurs
   before the same transaction commits. A denial rolls back and exposes no
   provider or internal identifiers.
8. Existing over-capacity data remains accessible and may be reduced; only a
   further increase in an already exceeded dimension is blocked.

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
2. A legacy `ready_for_checkout` pre-checkout billing state is eligible for
   safe preparation. The original incident was a local rejection in
   `_ensure_checkout_launchable()` before TIS called Paddle.
3. If the plan, interval, branches, capacity estimates, or authoritative quote
   change after checkout preparation, TIS supersedes the local checkout and
   unfinished attempt, clears the old quote lineage, and recalculates from the
   current selection and active count. A late old transaction event cannot
   activate that quote.
4. TIS resolves the selected plan, billing interval, active billable branches,
   unit price, and total for the current organization.
5. The customer reviews those values in TIS. For Professional Annual, the
   active mapping is USD 790 per branch, so two branches produce quantity 2
   and USD 1,580 annually.
6. TIS creates one Paddle transaction item using the mapped provider price and
   the exact authoritative branch quantity; quantity is never defaulted to one.
7. TIS reuses an active same-country Paddle address for the same customer, or
   creates one when no compatible address exists. The resolved address makes
   the automatically collected transaction ready. Returned item quantity,
   price, subtotal, and quote fingerprint must agree with TIS before the
   transaction is marked billed.
8. The payment launcher passes only the billed transaction ID to Paddle inline
   checkout after verifying the local attempt, organization, customer, quote,
   and remote billed status. Billed transaction items and quantities are
   immutable; draft, ready, canceled, past-due, unrelated, or mismatched
   transactions are not launched.
9. Paddle completion remains the recurring-subscription authority. Later branch
   changes use the established TIS subscription-quantity workflow.
10. Retry revalidates unpaid checkout eligibility and may replace an incomplete
   or non-launchable session. A reusable started transaction must still be
   billed, automatic, customer-matched, and current-quote matched at Paddle.

## Returning Customer Login And Organization Account

1. SaaS login authenticates and resolves authoritative onboarding, demo,
   workspace-link, lifecycle, and subscription state.
2. Incomplete setup resumes; pending demos open request status; and unpaid
   completed setup opens subscription selection.
3. An activated owner or linked user with account-management permission lands
   on `/saas/account`, the Organization Account Overview. Multiple managed
   organizations require selection before the overview is shown. The HTTP-only
   selected UUID is revalidated against the account's current tenant links and
   permissions on every request before entitlement or billing resolution.
4. The overview exposes Organization Profile, Branches, Billing & Subscription,
   and Account & Security only when ownership or existing permissions allow.
   Restricted or suspended account managers retain permitted billing/recovery
   access, but no active Enter TIS Platform action.
5. Enter TIS Platform is the only Organization Account action into `/login`.
   Linked users without account-management permission retain their approved
   role-based destination and cannot see owner or billing controls.
6. Operational login runs the commercial guard before branch and academic-year
   setup. Protected requests run it before page services. Authentication,
   sign-out, SaaS account, subscription/checkout/payment-return, support, and
   expiry routes remain safe and cannot recursively redirect.
7. Expired-demo Subscribe Now resolves the existing organization, SchoolGroup,
   and active operational branches, offers public plans and monthly/annual
   intervals, then launches existing Paddle checkout.
8. Only confirmed provider payment converts the same workspace UUID, tenant
   link, users, permissions, branches, and data.

Password login, social login, already-authenticated sign-in, post-verification
sign-in, and SaaS root/session restoration use the same destination resolver.

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
6. Email verification redirects by HTTP 302 to the GET `/saas/login` page.
   Its form submits credentials by POST to `/saas/auth/login`.
7. A fresh verified account with no organization enters the GET
   `/saas/account` dashboard. A supplied continuation is used only when it is a
   known customer GET destination; POST-only, malformed, traversal, and
   external values fall back to Account Setup.
8. The user invokes the existing POST start action and completes organization onboarding:
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
2. TIS resolves one confirmed active subscription, entitlements, lifecycle state, allowed actions, and one operational capacity snapshot covering active branches, tenant operational staff users, and teachers. Paid branch quantity is displayed separately from the current plan's maximum branch ceiling; unused ceiling is not prepaid branch capacity.
3. Review Capacity accepts proposed totals for all three dimensions. It shows confirmed paid branches, required active branches, additional billed branches, the plan ceiling, and the resulting minimum eligible plan. Branch growth may create a combined plan-and-quantity upgrade, while system-user and teacher growth affects eligibility without changing Paddle quantity.
4. Quantity or plan changes are previewed through Paddle; TIS displays provider-returned totals and never recalculates proration.
5. Immediate increases/upgrades use provider payment-failure prevention and remain locally pending until authoritative confirmation. The current confirmed plan and workspace access remain authoritative while the plan change is pending, failed, incomplete, expired, canceled, or abandoned. Thus an active Professional subscription remains accessible while an Enterprise AI upgrade is `payment_pending`.
6. Reductions/downgrades are scheduled for the next billing boundary and retain current local access until verified effective evidence. Live branch, system-user, and teacher counts are revalidated at that boundary; a mismatch enters manual review without applying the lower local entitlement.
7. Scheduled plan or quantity changes may be canceled or replaced before their effective boundary when provider state agrees.
8. Cancellation is scheduled at period end; reversal removes the provider-scheduled cancellation after reauthorization and validation.
9. The centralized lifecycle resolver exposes only actions valid for current provider/local state.
10. Billing Contact is explicit organization-owned state. Initial checkout requires a confirmed billing email, legal/billing organization or school name, and supported country/address data. The active portal view is read-only until an authorized owner or `subscriptions.manage_billing` user selects Edit; validation remains in edit mode, Cancel discards unsaved form values, and login identity is unaffected.
11. TIS saves valid local billing changes before attempting provider synchronization. It reuses the mapped Paddle customer, synchronizes its explicit billing email, creates or reuses one attributable active Paddle Business, persists address/business mappings, updates the active subscription identity, and includes `business_id` on future initial transactions. Provider failure leaves the local profile saved with retry-needed status. The dedicated retry revalidates permission and tenant scope, uses the stored profile and mappings, avoids duplicates, and makes no provider call after successful synchronization. Historical billing documents are not silently revised.
12. Billing history is read from Paddle transactions. `paid` displays Payment received - processing; only `completed` displays Paid and satisfies the existing final processing signal. Invoice download reauthorizes the user and requests a fresh provider URL.
13. Operational login, protected requests, and returning-customer routing use the same contract-linked commercial access projection. The specialized plan-change webhook synchronizes provider subscription status, but the target plan becomes authoritative only after the existing required provider signals are both confirmed.
14. If production provider state is confirmed but local commercial status is stale, an operator replays the attributable stored, signature-verified Paddle webhook through the existing reconciliation path. Operators do not edit subscription or lifecycle status fields manually. Replay may synchronize the current `PaymentSubscription.status`, but it cannot bypass the separate provider payment signal required to activate a target plan.

Guardrails:

- provider and local ownership must match,
- active branch usage cannot exceed a requested reduced capacity,
- target-plan eligibility is evaluated across branches, system users, and teachers before submission and again when a scheduled downgrade becomes effective,
- Paddle quantity contains branches only; system-user and teacher counts never become provider quantity units,
- webhook processing is idempotent,
- ambiguous outcomes enter manual review,
- return pages and local requests are not payment confirmation.
- organization billing identity is tenant-scoped and provider mappings are revalidated before synchronization,
- a saved billing profile in pending or failed provider synchronization blocks new plan and quantity mutations until retry succeeds; cancellation and legacy active subscriptions with no saved profile retain their established behavior,
- provider synchronization logs the safe failed step, provider error code, and HTTP status server-side; provider identifiers and raw diagnostics are never rendered to the customer,
- user login email is never an implicit permanent billing-email authority,
- stale or unrelated organization-level subscription rows cannot supersede the TenantProvisioningLink and SubscriptionContract-linked subscription,
- canceled subscriptions retain access only until the confirmed paid period ends; ambiguous evidence fails closed without being mislabeled as expired,
- renewal guidance is shown only for genuine expiration, not payment processing, past due, paused, suspended, archived, or inconsistent commercial evidence.

## Operational Billing Entry Flow

1. System Configuration includes Billing & Subscription only for a linked
   operational organization owner or user with
   `subscriptions.manage_billing` in the selected tenant.
2. The bridge revalidates the operational session, SchoolGroup scope,
   SaaSAccountUserLink, organization/workspace UUID, and billing authority.
3. The bridge opens `/saas/subscription` for that organization; it never
   duplicates billing UI inside operations.
4. If SaaS authentication is missing, password and social sign-in preserve the
   allowlisted internal subscription continuation and revalidate it against the
   signed-in account before rendering billing.
5. Unknown organizations, cross-account links, unauthorized users, duplicate
   continuation parameters, and external return URLs fail closed. A user with
   multiple managed organizations must resolve an organization before billing.
6. The landing-page Organization Sign In action enters `/saas/login` without an
   operational destination. Activated account managers therefore land in
   Organization Account unless they arrived through the validated billing
   continuation. Enter TIS Platform remains the only explicit operational entry.

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
