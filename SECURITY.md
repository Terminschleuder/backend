# Security policy

## Reporting a vulnerability

Please report privately via GitHub's **private vulnerability reporting**:
Security tab → *Report a vulnerability*. Please do not open a public issue
for a suspected vulnerability.

Include reproduction steps and the affected version/commit where possible.
The production deployment is pinned by release images (`ghcr.io/terminschleuder/backend:<release-version>`), so including the running version
(from `/api/schema/` or the image tag) helps triage.

## Scope

This repo covers the Django + DRF + PostGIS backend: the public API, auth
(JWT/API keys/sessions), the ingestion surface, and the bootstrap/entrypoint
machinery. Secrets belong in the hoster's env panel — `SECRET_KEY`,
`DJANGO_SUPERUSER_PASSWORD`, and database credentials are never committed.

## Dependencies

Third-party dependency alerts come via **Dependabot alerts**; proactive
weekly update PRs are configured in [`.github/dependabot.yml`](.github/dependabot.yml). Code scanning (CodeQL) runs on `main` and pull
requests.