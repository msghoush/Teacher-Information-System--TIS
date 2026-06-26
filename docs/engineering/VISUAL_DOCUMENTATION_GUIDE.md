---
title: TIS Visual Documentation Guide
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Visual Documentation Guide

This guide defines how visual documentation should evolve. No screenshots are required yet, but future screenshots and diagrams should follow this structure.

## Purpose

Visual documentation should help developers, reviewers, owners, and future AI assistants understand TIS screens, workflows, data relationships, and design expectations.

Visual docs should not replace Markdown source docs. They should support them.

## Future Storage Location

Recommended future location:

```text
docs/visuals/
  screenshots/
  diagrams/
  flows/
```

Recommended generated/reference output:

```text
static/docs/visuals/
```

Do not store sensitive production data in screenshots.

## Screenshot Standards

Screenshots should:

- use clean test/demo data,
- avoid private student/teacher/customer information,
- show the full relevant viewport or focused workflow area,
- include enough context to identify branch/year/page state,
- avoid browser chrome unless needed,
- be updated when UI behavior or layout meaningfully changes.

Preferred formats:

- PNG for UI screenshots,
- SVG or PNG for diagrams,
- PDF only for exported documentation snapshots.

## Naming Convention

Use stable, descriptive names:

```text
YYYY-MM-DD_module_screen_state.png
YYYY-MM-DD_flow_name_step_number.png
YYYY-MM-DD_architecture_diagram_name.svg
```

Examples:

```text
2026-06-26_platform-console_owner-view.png
2026-06-26_knowledge-center_current-status.png
2026-06-26_saas-onboarding_step-organization.png
```

## Update Policy

Update visual docs when:

- a screen layout meaningfully changes,
- workflow steps change,
- a module gains a new major view,
- navigation or role visibility changes,
- a diagram no longer reflects architecture.

Visual doc updates should be mentioned in the Knowledge Impact Assessment.

## Future Diagram Strategy

Future diagrams should cover:

- identity separation,
- SaaS onboarding to provisioning,
- payment webhook confirmation,
- tenant isolation,
- operational data model,
- KMS source-to-PDF-to-Knowledge-Center flow,
- landing-to-signup customer journey.

Diagrams should be simple and versioned through Markdown references.

## Planned Visual Areas

### Platform Console

Future visuals:

- owner account controls,
- developer management,
- organization/branch context switching.

### Knowledge Center

Future visuals:

- healthy status,
- stale status,
- source document table,
- KIA panel.

### Dashboard

Future visuals:

- operational dashboard overview,
- staffing/report widgets,
- scope context display.

### Teachers

Future visuals:

- teacher list,
- teacher edit/profile,
- qualification/capacity views.

### Workforce Planning

Future visuals:

- planning table,
- section ownership,
- workload/capacity states.

### Academic Calendar

Future visuals:

- calendar view,
- event editing,
- exports or responsibility states.

### SaaS Onboarding

Future visuals:

- signup,
- organization step,
- contacts,
- branches,
- academic setup,
- review.

### Billing

Future visuals:

- plan selection,
- checkout summary,
- billing status,
- payment pending/verified states.

### Landing Page

Future visuals:

- hero,
- problem/solution section,
- product capability section,
- signup/demo conversion paths.

### Reports

Future visuals:

- allocation report,
- dashboards,
- export states.

## Guardrails

- Do not include sensitive real data.
- Do not let visual docs become the only source of truth.
- Do not update landing visuals during backend tasks unless explicitly approved.
- Keep visual docs aligned with KMS change history.
