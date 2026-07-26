---
title: Demo-To-Paid Workspace Conversion
documentation_version: 3.1
last_updated: 2026-07-23
status: accepted
---

# ADR 0013: Demo-To-Paid Workspace Conversion

## Context

A provisioned Customer Demo already owns the customer's operational SchoolGroup, branches, users, permissions, academic data, and audit history. Running the paid provisioning engine after subscription payment would either skip the existing demo tenant without establishing paid commercial ownership or risk creating a duplicate tenant.

## Decision

Convert only an active, coherently provisioned Customer Demo after TIS receives a provider-confirmed active M7 subscription for the same pending organization. A durable conversion ledger records Requested, Processing, Completed, and Failed states plus audit and internal-notification events.

The conversion runs in one nested database transaction. It preserves the SchoolGroup, workspace UUID, tenant link row, organization, branches, users, permissions, academic records, and history. It ends the demo entitlement, creates a subscription-backed paid entitlement, moves existing branch entitlement rows to that envelope, changes the workspace classification to Customer Paid, and relinks the existing tenant link to the confirmed subscription contract.

The transaction validates its result through the existing M7 subscription entitlement resolver, workspace entitlement resolver, and commercial-state resolver. It succeeds only when the same workspace resolves as Customer Paid Active with the confirmed subscription and sufficient purchased branch capacity. A failure rolls back every workspace conversion mutation while retaining provider-confirmed payment records and a retryable failed conversion audit.

## Consequences

- No tenant, workspace, organization, user, branch, permission, or academic record is recreated.
- Demo request, provisioning, lifecycle, reminder, and expiration history remains available.
- Completed conversions are excluded from demo reminder and expiration processing.
- Existing paid provisioning remains unchanged for organizations without a demo tenant link.
- Ambiguous, cross-tenant, internal-sandbox, or already-paid workspaces fail closed.
- Manual conversion overrides, demo extensions, workspace deletion, and unrelated billing changes remain out of scope.

## M8B7 Amendment

A coherent expired/suspended Customer Demo may now convert after authoritative confirmed payment. Conversion reactivates the same SchoolGroup, replaces the ended demo entitlement with the paid entitlement, and relinks the same tenant relationship. Checkout return, sandbox evidence, and unverified payment remain non-authoritative.
