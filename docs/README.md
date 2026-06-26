# TIS Documentation

This folder is the permanent documentation source of truth for TIS.

## How To Use These Docs

Start with this index, then read the master context and project state before making project changes.

Recommended reading order:

1. `docs/README.md`
2. `docs/TIS_MASTER_CONTEXT.md`
3. `docs/PROJECT_STATE.md`
4. Relevant feature, marketing, or roadmap docs under `docs/`

The generated PDF reference booklet is built from these Markdown sources:

- `static/docs/TIS_Project_Reference_Booklet.pdf`

The PDF is an output artifact. The Markdown files are the source of truth.

## Required Reading For New Codex Conversations

For any new Codex conversation involving implementation, architecture, deployment, SaaS, platform owner flows, landing page work, or product direction, read:

- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- Any specific docs related to the requested task

If the task touches the public website, also read:

- `docs/marketing/landing_page_source_of_truth.md`
- `docs/marketing/tis_landing_page_master_content.md`

## Documentation Files

Primary docs:

- `docs/TIS_MASTER_CONTEXT.md`: full project reference covering product identity, vision, architecture, SaaS milestones, billing, provisioning, landing strategy, workflow, roadmap, and critical rules.
- `docs/PROJECT_STATE.md`: living project status file covering branch assumptions, current priority, completed milestones, known issues, next work, landing baseline, and update policy.
- `docs/README.md`: documentation index and usage guide.

Existing supporting docs:

- `docs/location-data-roadmap.md`: location data roadmap and related implementation notes.
- `docs/marketing/landing_page_source_of_truth.md`: official boundary between the public Next.js landing website and the FastAPI application portal.
- `docs/marketing/tis_landing_page_master_content.md`: approved marketing foundation and landing page content direction.

Generated docs:

- `static/docs/TIS_Project_Reference_Booklet.pdf`: generated PDF booklet created from the Markdown documentation source files.

## PDF Generation

Generate the PDF booklet with:

```powershell
python scripts/generate_docs_pdf.py
```

The generator uses `reportlab`, which is already part of the Python requirements. It intentionally avoids LaTeX, Playwright, Chromium, external network calls, and system font dependencies.

## Documentation Update Rule

Every approved implementation must:

1. Check whether documentation is affected.
2. Update relevant Markdown docs.
3. Regenerate the PDF booklet if docs changed.
4. Mention documentation changes in the final report.

A task is not complete until relevant documentation is updated.

## Phase Boundaries

Phase 1 documentation foundation includes Markdown source docs, PDF generator, and generated PDF output.

Phase 2 is separate and requires explicit approval before implementation. Phase 2 may add a protected Platform Owner documentation center inside the app, but Phase 1 must not add app routes, platform navigation, or route permission changes.
