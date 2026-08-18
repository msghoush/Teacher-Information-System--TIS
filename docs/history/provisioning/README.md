---
title: Provisioning History
module: provisioning
last_updated: 2026-08-18
---

# Provisioning History

This folder tracks meaningful changes to pending organizations, provisioning jobs, verified-payment readiness, retry behavior, and platform owner provisioning oversight.

Related docs:

- `docs/adr/0005-delayed-tenant-provisioning-after-verified-payment.md`
- `docs/TIS_MASTER_CONTEXT.md`

Related files:

- `saas/provisioning_service.py`
- `saas/service.py`
- `saas/router.py`
- `templates/saas/admin_provisioning.html`

## 2026-08-18 - SchoolGroup Operational Creation Boundary

Direct operational SchoolGroup creation and deletion now require Platform identity
and explicit global SchoolGroup-management capability. Tenant role defaults no
longer include these actions, stale permissions cannot cross the handler boundary,
and tenant updates accept only the linked SchoolGroup. Approved paid, demo, promo,
and conversion provisioning paths are unchanged. A separate PostgreSQL-only
read-only provenance audit reports active internal sandboxes missing tenant-link and
explicit entitlement evidence for later Platform Owner review; it performs no
remediation.

## 2026-07-22 - Lifecycle-Aware Platform Owner Queue

Platform Owner pending counts and lists now share one query boundary. A record remains pending only while its onboarding status is draft, in progress, changes requested, under review, or ready for checkout and no tenant link, completed provisioning job, or final tenant billing state exists. Active tenants are resolved from coherent payment, active subscription, contract, tenant-link, and active SchoolGroup evidence. Completed provisioning with incomplete or conflicting commercial evidence is retained as Lifecycle Review Required rather than shown as ordinary pending work. No lifecycle rows are rewritten by this owner-facing projection.
