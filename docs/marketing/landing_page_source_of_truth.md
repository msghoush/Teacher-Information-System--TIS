# Landing Page Source of Truth

The official source of truth for the public TIS landing website is:

```text
tis-landing-website/
```

## Public Website

- **Domain:** https://tisplatform.com
- **Runtime:** Next.js / Node
- **Local testing URL:** http://localhost:3000

All future marketing landing page changes must be made inside `tis-landing-website/`.

## Application Portal

The TIS application portal remains separate from the public landing website:

- **Domain:** https://app.tisplatform.com
- **Runtime:** FastAPI / Python with PostgreSQL

## Legacy Landing Page Files

The former FastAPI/Jinja landing page files are now legacy:

- `templates/landing.html`
- `static/landing/landing.css`

Codex and other developers must not modify these legacy files unless explicitly instructed.
