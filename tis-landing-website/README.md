# TIS Platform Landing Website

Standalone public marketing website for `tisplatform.com`.

This project is intentionally separate from the existing FastAPI application used at `app.tisplatform.com`.

## Stack

- Next.js
- TypeScript
- Tailwind CSS
- Lucide React icons

## Local Development

Install Node.js 20 LTS or newer, then run:

```bash
cd tis-landing-website
npm install
npm run dev
```

Open:

```text
http://localhost:3000
```

## Production Build

```bash
npm run build
npm run start
```

## Separate Deployment

Deploy this folder as its own web project, separate from the FastAPI application.

Recommended options:

- Vercel: import `tis-landing-website` as the project root and deploy as a Next.js app.
- Netlify: set the base directory to `tis-landing-website`, build command to `npm run build`, and publish through the Next.js runtime.
- VPS/container: build the app with `npm run build`, run `npm run start`, and proxy `tisplatform.com` to the Next.js service.

## Domain Setup

Keep the application portal on:

```text
app.tisplatform.com
```

Point the public marketing domain to this landing website:

```text
tisplatform.com
www.tisplatform.com
```

At the DNS provider, configure the records required by the hosting platform. Usually this means an apex `A`/`ALIAS`/`ANAME` record for `tisplatform.com` and a `CNAME` record for `www`.

## Demo Form

The request demo form is currently UI-only. Connect it later to an email service, CRM, database endpoint, or serverless form handler.

## Product Visuals and Privacy

Official assets live in:

```text
public/logo
public/screenshots
```

The public landing page uses sanitized screenshot copies from:

```text
public/screenshots/sanitized
```

Do not reference the original screenshots directly from public pages if they contain names, IDs, branch names, school-specific planning details, or other private information.
