---
title: Landing CTA Consolidation And Demo Domain Policy
module: landing-page
date: 2026-07-25
---

# Landing CTA Consolidation And Demo Domain Policy

The public landing website now uses two clear customer conversion paths:

- Request a Demo: configured SaaS signup URL with `intent=demo`.
- Subscribe Now: configured SaaS signup URL with `intent=subscribe`.

Both URLs are built from `NEXT_PUBLIC_TIS_APP_BASE_URL`; the public site continues to deploy independently from the FastAPI application. The landing page no longer exposes overlapping Open Account, Book a Demo, Request Early Access, or Request Pricing conversion labels.

The selected intent is persisted by the SaaS application through account creation, email verification, School Workspace Setup, and review. At commercial choice, the selected path receives visual emphasis but the customer can choose either available path.

Customer Demo eligibility is enforced by the SaaS application, not by the landing site. It uses a normalized organization domain and a database unique reservation so a second customer demo cannot be created for the same organization after any prior demo request or lifecycle outcome. Internal Sandbox history is excluded. Historical duplicate domains are retained for Platform Owner manual review without deleting, merging, or recreating customer workspaces.
