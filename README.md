# terminschleuder

A **Django + Django REST Framework** backend for local events and meetups, featuring
**PostGIS geospatial search** (events within *N* km of a point) and **JWT + API-key
authentication** for external and service clients.

> **Status:** early preview — APIs and data models may change without notice.
> **License:** Apache-2.0 (see [LICENSE](LICENSE)).

---

## Table of contents

- [Overview](#overview)
- [Tech stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Local development & testing](#local-development--testing)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Admin backoffice](#admin-backoffice)
- [Documentation](#documentation)
- [Production notes](#production-notes)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)

## Overview

terminschleuder is the **system of record** for a catalog of **events, venues,
organizations, and categories** with geospatial locations, exposed through a REST API. An
**external extraction pipeline** feeds it: organizations own event-source URLs; an
extractor crawls approved sources, reports ingestion runs, and submits **untrusted** event
observations; operators review and **promote** accepted ones into canonical, published
events with full provenance.

Highlights:

- **Proximity search** — `GET /api/events/?lat=&lon=&radius_km=` returns events within the
  radius, each annotated with a `distance` (km), ordered nearest-first. Built on PostGIS
  `geography` columns + `ST_DWithin`. **Online events are excluded** from proximity.
- **City catalog** — `GET /api/cities/` (search/filter/order) plus
  `GET /api/events/?near_city=<slug>` lets users find events by city without knowing
  coordinates. Seeded with all European cities ≥ 50 000 population.
- **Ingestion & provenance** — `/api/ingestion/` lets an external extractor discover due
  sources, report runs, and submit untrusted observations; operators promote accepted
  observations into canonical events linked back to their source and run.
- **Event lifecycle** — `draft` / `published` / `cancelled` / `archived`, driven from the
  API or backoffice; the public catalog shows only `published` events.
- **Two auth mechanisms for external clients:**
  - **JWT** (simplejwt) — short-lived access + refresh tokens.
  - **Long-lived API keys** ("app secrets") — sha256-hashed, revocable, expirable.
- **Service / system users** — non-interactive accounts flagged `is_service_account` that
  carry Django groups & permissions and obtain JWTs / API keys like any user.
- **Ownership & permissions** — events have an owner (`created_by`) and an optional
  `owner_group`; writes are gated by owner / group membership / model permissions. Reads
  stay public (published events).
- **`create_service_account` management command** to provision a system client.

## Tech stack

| Concern    | Choice                                              |
| ---------- | --------------------------------------------------- |
| Framework  | Django 6.1 + Django REST Framework 3.18             |
| Database   | PostgreSQL 18 + **PostGIS** (geospatial)            |
| Auth       | simplejwt (JWT) + custom hashed API keys            |
| GIS libs   | GDAL / GEOS / PROJ — **bundled in the app image**   |
| Config     | `django-environ` (`DATABASE_URL`), `django-filter` |
| Tests      | `pytest` + `pytest-django`                          |
| Runtime    | Docker + Docker Compose                            |

> **Why Docker only?** `django.contrib.gis` requires GDAL/GEOS/PROJ on the host. To keep
> the host clean and make production a single `docker pull`, the app image bundles the GIS
> libraries and runs against a PostGIS database container. **You cannot run the app
> directly on the host** (no GIS libs) — all dev and testing happens inside the containers.

## Prerequisites

- **Docker** with the **Compose plugin** (`docker compose version` should print a version).
- That's it. No Python, Postgres, or GIS libraries need to be installed on the host — the
  images provide everything.

## Local development & testing

The dev stack runs **PostGIS** (`db`) and **Django's runserver** (`web`) in containers. The
web service runs migrations automatically and hot-reloads source changes via a bind mount.

### 1. Start the stack

```bash
./start.sh            # = docker compose up --build; stops cleanly on Ctrl-C
# …or, equivalently:
docker compose up --build
```

First run builds both images (the app image installs GDAL/GEOS/PROJ via apt, so expect a
couple of minutes). Subsequent starts are fast.

### 2. Open the app

The server listens on **http://localhost:8000**.

| URL                                  | What it is                              |
| ------------------------------------ | --------------------------------------- |
| `http://localhost:8000/`             | **Public landing page** (marketing, no auth) |
| `http://localhost:8000/admin/`       | **Backoffice** (admin login) — anon redirects to `/admin/login/` |
| `http://localhost:8000/api/`         | API root — lists all event endpoints    |
| `http://localhost:8000/api/auth/`    | auth endpoints (register/login/me/token) |

`/api/` and the individual collections render DRF's **browsable API** in a browser. The
backoffice at `/admin/` is a custom Django `AdminSite` (see [Admin backoffice](#admin-backoffice)).

### 3. Create an admin user / seed sample data

In a separate terminal while the stack is running:

```bash
# Backoffice login for /admin/
docker compose exec web python manage.py createsuperuser

# City gazetteer (all European cities >= 50k population) — powers ?near_city=
docker compose exec web python manage.py seed_cities

# Optional: a few sample venues, organizations, categories and events
docker compose exec web python manage.py seed

# Optional: a rich, JSON-driven demo dataset across every area — 20 organizations,
# 120 venues across 15 European cities, 8 categories, 20 sources, ingestion runs,
# observations, and 400 canonical events (full lifecycle + classification
# matrix), each carrying a generated hero image — plus a `demo`/`demo12345`
# staff user and the `ingestion` group. Idempotent and non-destructive. The data
# lives in events/data/seed/*.json (regenerate with
# `python3 scripts/build_demo_fixture.py`); `--no-hero` skips banner generation.
docker compose exec web python manage.py seed_demo
```

### 4. Run the tests

Tests run inside the container against real PostGIS and real auth:

```bash
docker compose run --rm web python -m pytest -q
```

(You can also run an individual file: `docker compose run --rm web python -m pytest events/tests.py -q`.)

### 5. Stop the stack

```bash
docker compose down            # stops & removes containers; the pgdata + media volumes are kept
```

> Use `down` **without** `-v`. `docker compose down -v` wipes the `pgdata` volume — and
> with it the seeded 2131-city gazetteer — as well as the `media` volume (event hero
> images). Only run `down -v` for a deliberate full reset; the entrypoint's bootstrap
> re-seeds the cities automatically on the next start. If you only need the `pgdata`
> volume gone (e.g. after a Postgres major bump), `down` plus
> `docker volume rm backend_pgdata` is the targeted form — see
> [PostgreSQL major upgrades](#postgresql-major-upgrades).

`start.sh` also runs `docker compose down` on exit, so Ctrl-C cleans up automatically.

## Configuration

Settings are read from the environment (via `django-environ`). For local dev,
`docker-compose.yml` sets everything for you — no `.env` required.

Copy `.env.example` to `.env` only if you want to override defaults for a host-based or
custom setup (`.env` is gitignored and never committed).

| Variable        | Default                                              | Notes                                            |
| --------------- | ---------------------------------------------------- | ------------------------------------------------ |
| `SECRET_KEY`    | `django-insecure-change-me`                          | **Set a strong random value in production.**     |
| `DEBUG`         | `False`                                              | Compose sets `True` for dev.                     |
| `ALLOWED_HOSTS` | `[]`                                                 | Compose sets `*` for dev.                        |
| `DATABASE_URL`  | `postgis://terminschleuder:terminschleuder@127.0.0.1:5432/terminschleuder` | Compose overrides to the `db` host. |
| `CORS_ALLOW_ALL_ORIGINS` | `True` | Read-only GET/HEAD/OPTIONS from any origin (so the demo client can call the API from a browser). Set `False` + `CORS_ALLOWED_ORIGINS` in prod. |
| `CORS_ALLOWED_ORIGINS`  | `[]`   | Allowed origins when `CORS_ALLOW_ALL_ORIGINS=False` (comma-separated, with scheme). |
| `SERVE_MEDIA`   | `True`   | Serve `/media/` (hero images) through Django. Default on — the pure-container deployment has no reverse proxy. Set `False` when a proxy/CDN serves `/media/`. |
| `DJANGO_SUPERUSER_USERNAME` / `_PASSWORD` / `_EMAIL` | unset | Read by `bootstrap` on every container start: creates the operator superuser on a **fresh** DB; never overwrites an existing one. |
| `ENTRYPOINT_SKIP_TASKS` | `0` | Set `1` for one-off jobs (`docker run --rm <image> python manage.py shell`) so the entrypoint skips migrate + bootstrap. |

JWT access tokens live **15 min**, refresh tokens **7 days**, signed with `SECRET_KEY`.

Media: `MEDIA_URL = /media/`, `MEDIA_ROOT = /app/media` (the `media` volume). Events may
carry an optional **hero image** (uploaded in the backoffice, generated by `seed_demo`); the
API exposes its URL read-only. Served by Django when `SERVE_MEDIA=True` (the default —
no reverse proxy needed); set `SERVE_MEDIA=False` when a proxy or CDN takes over.

## API reference

### Base URLs

All API routes live under `/api/`; auth routes under `/api/auth/`. The public read API is
**CORS-enabled** for `GET/HEAD/OPTIONS` (no credentials) so a browser on another origin —
the read-only demo client — can call it directly. The API is **self-describing** via an
OpenAPI 3 schema at `/api/schema/` (Swagger UI at `/api/schema/swagger-ui/`, ReDoc at
`/api/schema/redoc/`); export it with
`docker compose exec web python manage.py spectacular --file openapi.yaml --validate`.

| Method        | Endpoint                              | Auth            | Purpose                          |
| ------------- | ------------------------------------- | --------------- | -------------------------------- |
| GET           | `/api/cities/`                        | public          | city catalog (search/filter/order; `?page_size=`) |
| GET           | `/api/cities/all/`                    | public          | full catalog, unpaginated (one response) |
| GET           | `/api/cities/<id>/`                   | public          | city detail (with lat/lon)       |
| GET           | `/api/events/?near_city=<slug>`       | public          | events near a city (with distance) |
| GET           | `/api/events/?lat=&lon=&radius_km=`   | public          | proximity search (with distance; online excluded) |
| GET / POST    | `/api/events/`                        | public / auth   | list (published only) / create events |
| GET / PATCH / DELETE | `/api/events/<id>/`             | public / owner  | retrieve / update / delete       |
| POST          | `/api/events/<id>/publish/` `cancel/` `archive/` `revert_to_draft/` | owner / `change_event` | event lifecycle |
| GET           | `/api/organizations/` , `/<slug>/` , `/<slug>/events/` | public | organization catalog (active; by slug) + its published events |
| GET / POST    | `/api/venues/`, `/api/categories/`    | mixed           | catalog + CRUD        |
| GET           | `/api/schema/` , `/swagger-ui/` , `/redoc/` | public    | OpenAPI 3 schema + interactive docs (self-describing API; the demo client codegens types from `/api/schema/`) |
| GET           | `/api/ingestion/sources/due/`         | ingestion       | extractor work queue (due sources) |
| POST          | `/api/ingestion/runs/` , `/<id>/success/` `failure/` `reconcile/` | ingestion | report / finish a run; `success/` triggers run-over-run reconciliation |
| POST          | `/api/ingestion/observations/` , `/bulk/` | ingestion    | submit untrusted observations (with a stable `event_key`) |
| GET           | `/api/ingestion/observations/` , `/api/ingestion/runs/` | ingestion | list submitted (filter by `?lifecycle=`, `?event_key=`) |
| POST          | `/api/auth/register/`                 | public          | register a user                  |
| POST          | `/api/auth/token/`                    | public          | obtain JWT (access + refresh)    |
| POST          | `/api/auth/token/refresh/`            | public          | refresh JWT                      |
| GET           | `/api/auth/me/`                       | auth            | current user + groups + perms    |
| GET / POST    | `/api/auth/api-keys/`                 | auth            | list / create API keys           |
| DELETE        | `/api/auth/api-keys/<id>/`            | auth            | revoke an API key                |

> **ingestion** auth = a service account in the `ingestion` group (carrying
> `view_eventsource` / `add_ingestionrun` / `change_ingestionrun` / `view_ingestionrun` /
> `add_eventobservation` / `view_eventobservation`), authenticating with an API key. See
> [Authentication](docs/authentication.md).

### City catalog & proximity by city

End users typically don't know lat/lon. The **city catalog** lets a client build a pick-list
and then query events "near a city" in one call.

```bash
# 1. Let the user pick a city (prefix search; filter by country; order by population)
curl 'http://localhost:8000/api/cities/?search=berlin'
# → [{"name":"Berlin","slug":"berlin-de","latitude":52.52,"longitude":13.41,
#     "default_radius_km":45,"population":3426354,…}, …]

# 2. Events near that city — uses the city's centroid + default radius,
#    each result annotated with "distance" (km), nearest first:
curl 'http://localhost:8000/api/events/?near_city=berlin-de'

# Override the default radius (km):
curl 'http://localhost:8000/api/events/?near_city=berlin-de&radius_km=10'
```

Fetching the whole catalog (e.g. to cache an offline pick-list / autocomplete):

```bash
curl 'http://localhost:8000/api/cities/all/'            # → 2131 cities, one unpaginated list
curl 'http://localhost:8000/api/cities/all/?country_code=DE'   # filters apply to /all/ too
curl 'http://localhost:8000/api/cities/?page_size=1000'  # paginated, capped at 1000/page
```

Each city exposes `latitude`, `longitude`, `default_radius_km`, `population`, `country`,
`country_code`, and a unique `slug` (used as `near_city`). Seeded with all European cities
≥ 50 000 population (**2131 cities**) via `python manage.py seed_cities`. Re-generate the
dataset (offline) with `python3 scripts/build_european_cities_fixture.py`.

### Proximity search (raw coordinates)

```bash
curl 'http://localhost:8000/api/events/?lat=52.52&lon=13.405&radius_km=10'
# → events within 10 km of the point, each with a "distance" (km), nearest first
```

All three of `lat`, `lon`, `radius_km` must be supplied together (otherwise HTTP 400).
Use either `near_city` **or** `lat`/`lon`, not both. Events without a location are excluded
from proximity results.

> **`?near_city=` vs `?city=`:** `near_city` matches a **gazetteer city slug** and filters
> events by **distance from its centroid**; `city` (on `/api/events/`) matches a venue's
> **city text field exactly**. They are independent filters.

### Authentication

**JWT** — obtain, then send as a Bearer token:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"my-bot","password":"<secret>"}' | jq -r .access)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/auth/me/
```

**API key** ("app secret") — the raw key is returned **only once**, at creation:

```bash
# Create a key (requires an authenticated request, e.g. with the JWT above)
curl -X POST http://localhost:8000/api/auth/api-keys/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"outer-client"}'

# Use it
curl -H "Authorization: Api-Key <raw-key>" http://localhost:8000/api/events/
```

Revoking: `DELETE /api/auth/api-keys/<id>/`. Listing never exposes the raw key.

### Service accounts & permissions

```bash
# Provision a system client (prints a one-time secret); add it to a group for perms
docker compose exec web python manage.py create_service_account my-bot --group editors
```

A service account is a normal Django user (so it obtains JWTs / API keys and carries groups
& permissions), flagged non-interactive. To let it **create events**, grant the group
`events.add_event`; for update/delete, grant `events.change_event` / `events.delete_event`.

**The extractor** is a service account in an `ingestion` group (it may read due sources,
report runs, and submit observations, but cannot promote or publish — those are operator
actions):

```bash
docker compose exec web python manage.py shell -c "
from django.contrib.auth.models import Group, Permission
g, _ = Group.objects.get_or_create(name='ingestion')
g.permissions.add(*Permission.objects.filter(content_type__app_label='events', codename__in=[
    'view_eventsource','add_ingestionrun','change_ingestionrun','view_ingestionrun',
    'add_eventobservation','view_eventobservation']))
"
docker compose exec web python manage.py create_service_account extractor --group ingestion \
  --description "External extraction system"
# then issue the extractor an API key (via /api/auth/api-keys/ as an admin, or the backoffice)
```

### Ownership model

- `GET` (all collections) — **public** (the catalog).
- `POST /api/events/` — authenticated. Human users may create freely; service accounts
  require `events.add_event`.
- `PATCH` / `DELETE /api/events/<id>/` — allowed for the **owner** (`created_by`), a member
  of the event's **`owner_group`**, or any holder of the matching model permission.

## Admin backoffice

The human backoffice is a custom Django `AdminSite` (the `admin` app, app label `backoffice`)
mounted at **`/admin/`**. It reuses the project's Django auth — log in with a **staff** user
(e.g. the superuser from `createsuperuser`). Anonymous visitors are redirected to
`/admin/login/`. The site root (`/`) is a public marketing landing page (no auth).

It covers all the operator tasks:

- **Users** — create/manage human users (set `is_staff` to grant backoffice access; assign
  groups). Passwords are hashed via Django's forms.
- **Service / system accounts** — a dedicated, pre-filtered list (proxy of `User`). Creating
  one generates a random **app secret** and shows it **once** (use it to obtain a JWT or as
  the API-key owner). `is_service_account` is forced on, `is_staff` off. A "Regenerate app
  secret" action re-rolls it for existing accounts.
- **Groups** — maintain Django groups & permissions; groups drive event `owner_group` and
  service-account powers.
- **API keys** — issue a long-lived key; the **raw key is shown once** (only the prefix/hash
  are stored). Revoke by editing `revoked`. Raw keys are never listed.
- **Cities** — maintain the gazetteer (add/edit, toggle `is_active`). The list shows read-only
  `latitude`/`longitude` columns and `location` is edited via the PostGIS map widget. Bulk
  re-seed stays the `seed_cities` command.
- **Organizations** — the entities that own event sources and the events extracted from them
  (renamed from *organizers*). Toggle `is_active` (inactive orgs are hidden from the public
  API and their sources stop being due).
- **Event sources** — add a source URL per organization; **approve** / **disable** / **revoke**
  to control extraction eligibility. `last_fetched_at`/`next_due_at` are stamped by the
  extractor (read-only here).
- **Ingestion runs** — read-only inspection of runs reported by the extractor.
- **Event observations** — review untrusted extracted events: **accept** / **reject** /
  **promote** (promote creates a draft canonical event with full provenance — see below).
- **Events / venues / categories** — full CRUD + event **lifecycle** (publish / cancel /
  archive / revert to draft). Events and venues show read-only `latitude`/`longitude` and
  edit `location` via the PostGIS map widget. New events default `created_by` to the operator
  and protect `created_at`/`updated_at`.

> **Promotion flow:** the extractor submits `pending` observations; an operator **promotes**
> an accepted one into a **draft** event (copying `original_url`/`original_platform`/location,
> linking `source` + `promoted_from`), then **publishes** it. The extractor can never
> promote or publish — only report and submit.

> The backoffice uses **session auth + `is_staff`** on the same custom `User` the API uses —
> no separate auth system. See [docs/admin.md](docs/admin.md) for the full guide.

## Documentation

This README is the quickstart. For the full functional documentation — architecture, data
model, complete API reference, authentication, and geospatial/cities — see the
**[docs/](docs/)** folder (GitHub-renderable Markdown + Mermaid diagrams):

| Document | Scope |
| -------- | ----- |
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/user-manual.md](docs/user-manual.md) | Use-case-driven guide for operators & extractor integrators (start here if you work with the app) |
| [docs/architecture.md](docs/architecture.md) | High-level design, container layout, request lifecycle |
| [docs/data-model.md](docs/data-model.md) | Entities, fields, relationships (ER diagram) |
| [docs/api-reference.md](docs/api-reference.md) | Every endpoint: params, examples, status codes, errors |
| [docs/authentication.md](docs/authentication.md) | JWT, API keys, service accounts, permissions, ownership |
| [docs/geospatial.md](docs/geospatial.md) | PostGIS storage, proximity, `?near_city=`, city catalog & seeding |
| [docs/admin.md](docs/admin.md) | The backoffice `AdminSite`: service-account & API-key issuance, group/city/event maintenance |

## Production notes

The app image is production-shaped: its default `CMD` runs **gunicorn** (`config.wsgi`).
The compose override only swaps in `runserver` for dev. For production:

- Set a strong `SECRET_KEY`, `DEBUG=False`, real `ALLOWED_HOSTS`, and a production
  `DATABASE_URL`.
- Pull the image rather than building on the host (the constraint this project was built
  around). The image runs as a **non-root** user (`terminschleuder`, uid 1001); if you
  bind-mount `media/`, `chown -R 1001:1001` it so uploads can write.

The container is **self-bootstrapping**: its entrypoint (`docker-entrypoint.sh`) waits for
the database, runs migrations, then the idempotent `bootstrap` management command on every
start. There is deliberately **no reverse proxy** requirement — **WhiteNoise** serves the
collected static files (admin CSS/JS, collected at image build time) straight from
gunicorn, and Django serves `/media/` (hero images) when `SERVE_MEDIA=True` (the default).

### Fresh-host runbook

A fresh DB volume gets schema from `migrate` but **zero users and zero cities** — you
couldn't even log in. Bootstrap closes that gap: it provisions the operator superuser
from `DJANGO_SUPERUSER_*` env vars, the `ingestion` group with exactly its permission set,
and the 2131-city gazetteer (`seed_cities`, an idempotent upsert). It **never** seeds the
demo data (`seed`, `seed_demo`) and **never overwrites** an existing superuser (rotate the
password via the backoffice instead).

```bash
# 1. Database (pin by release version — `latest` floats with a Postgres major bump)
docker run -d --name ts-db -v ts-pgdata:/var/lib/postgresql/data \
  -e POSTGRES_USER=… -e POSTGRES_PASSWORD=… -e POSTGRES_DB=… \
  ghcr.io/terminschleuder/backend-db:<release-version>

# 2. Backend: entrypoint waits for the DB, migrates, bootstraps (superuser from env,
#    ingestion group, cities), then starts gunicorn. Re-runs are safe/idempotent.
docker run -d --name ts-web -p 8000:8000 -v ts-media:/app/media \
  -e SECRET_KEY=… -e DEBUG=False -e ALLOWED_HOSTS=www.terminschleuder.online \
  -e DATABASE_URL=postgis://…@ts-db:5432/… \
  -e DJANGO_SUPERUSER_USERNAME=admin -e DJANGO_SUPERUSER_PASSWORD=… \
  ghcr.io/terminschleuder/backend:<release-version>

# 3. Extractor onboarding (one-time; secrets are shown once by design, so bootstrap
#    deliberately does NOT create it from env). On a hoster without exec:
docker run --rm -e SECRET_KEY=… -e DEBUG=False -e ALLOWED_HOSTS=… -e DATABASE_URL=… \
  ghcr.io/terminschleuder/backend:<release-version> \
  sh -c "ENTRYPOINT_SKIP_TASKS=1 python manage.py create_service_account extractor --group ingestion"
# Then log into /admin/ as the bootstrapped superuser and mint the extractor an API key
# (shown once) — that key becomes the extractor container's EXTRACTOR_API_KEY.
```

The first container start against a fresh volume takes a little longer (migrate +
bootstrap); watch the `[entrypoint]` log lines. If the database isn't reachable the
entrypoint retries for ~1 minute, then exits rather than serving against an unverifiable
schema. Restarting the backend container later re-runs bootstrap harmlessly — no
duplicate superusers, no duplicate cities.

> **Caveats:** `DJANGO_SUPERUSER_PASSWORD` lives in the hoster's env/secret panel, and
> bootstrap never rotates it (change it in the backoffice after first login). Bootstrap's
> get-or-creates assume a **single** backend replica — run replicas only behind a shared
> volume-aware plan, or bootstrap once and scale afterwards.

### Container images & releases

CI (`.github/workflows/ci.yml`) builds and tests every push to `main`/`develop`, every
tag, and every PR. Every commit that lands on `main` cuts a **CalVer release**
(`YYYY.MINOR.0`, git tag `vYYYY.MINOR.0`): the release job versions, builds & pushes both
images (app + PostGIS db) to the **GitHub Container Registry**, scans them with Trivy, and
creates the git tag + GitHub Release last — images are tagged `<release-version>`, `latest`,
and `sha-<short>`. PRs and `develop` pushes never publish. For deployment you don't clone
this repo — **pull the images** and run the app with a PostGIS database and your `.env`
(see the Production section above):

```bash
docker pull ghcr.io/terminschleuder/backend:latest            # from main
docker pull ghcr.io/terminschleuder/backend:<release-version>  # a CalVer release tag
```

Pin the **db** image by its release version
(`ghcr.io/terminschleuder/backend-db:<release-version>`) rather than `latest` — `latest`
floats with a Postgres major bump, which requires the dump/restore migration described in
[PostgreSQL major upgrades](#postgresql-major-upgrades) below.

### PostgreSQL major upgrades

`Dockerfile.db` is deliberately pinned to a Postgres **major** (`FROM postgres:18`). The
pin is manual: Dependabot's docker ecosystem only watches `Dockerfile`, never
`Dockerfile.db`, so a major bump never arrives as a routine dependency update — it is a
**breaking data change** by design. Bumping it (e.g. to `postgres:19`) must follow this
runbook, and the new image must not reach `main` before the plan to migrate its data
does.

**Local dev** — the `pgdata` volume is disposable. After a major bump (or any
`database files are incompatible with server` error) simply recreate it:

```bash
docker compose down                 # no -v; the media volume is never touched
docker volume rm backend_pgdata     # recreate from scratch…
./start.sh                          # …entrypoint re-runs migrate + bootstrap
```

The 2131-city gazetteer re-seeds automatically; local demo data and users are lost (fine
for dev — recreate them with `seed_demo` / `createsuperuser` as needed).

**Prod** — real data, so a dump/restore is mandatory:

1. **Dump** from the running old-version container (or `docker exec` into it if the
   hoster allows `exec`):
   ```bash
   docker run --rm --network <prod-network> \
     -v <prod-pgdata>:/var/lib/postgresql/data \
     ghcr.io/terminschleuder/backend-db:<old-release-version> \
     pg_dump -U terminschleuder -Fc terminschleuder > dump.pg
   ```
2. Stop the stack, keep the **old** volume until the restore is verified.
3. Start the new `backend-db:<new-release-version>` against a **fresh** volume (the
   entrypoint creates the cluster; `POSTGRES_USER/PASSWORD/DB` env as before).
4. **Restore** the dump (`pg_restore -U terminschleuder -d terminschleuder dump.pg`),
   then start the backend — its entrypoint runs `migrate` for any outstanding
   migrations.
5. **Verify** (city count, app boots, healthcheck green), then remove the old volume.

Development follows a `develop` → `main` cycle: work lands on `develop`, PRs to `main`
build and publish. Direct pushes to `main` are blocked by branch protection.

## Project structure

```
.
├── manage.py
├── docker-compose.yml        # db (PostGIS) + web (Django dev server)
├── Dockerfile                # app image: GDAL/GEOS/PROJ + gunicorn
├── Dockerfile.db             # postgres:18 + postgis (arm64-friendly build)
├── requirements.txt
├── start.sh                  # thin `docker compose up` wrapper
├── config/                   # Django project: settings, urls, wsgi, asgi
├── admin/                    # backoffice (custom AdminSite at /admin/, service-account & API-key flows)
├── events/                   # events, venues, organizations, categories + proximity;
│                             #   ingestion & provenance (sources/runs/observations);
│                             #   event lifecycle; extractor API (/api/ingestion/)
│                             #   demo seed data: events/data/seed/*.json
├── accounts/                 # users, service accounts, API keys, JWT views
├── locations/                # city gazetteer (City model, /api/cities/, seed_cities)
├── scripts/                  # offline tools (build_european_cities_fixture.py, build_demo_fixture.py)
├── conftest.py               # shared pytest fixtures
└── pytest.ini
```

## Troubleshooting

- **`/admin/` redirects to `/admin/login/`** — expected. The backoffice is a custom admin
  site mounted at `/admin/`; log in with a staff/superuser. The root (`/`) is a public
  landing page. See [Open the app](#2-open-the-app) and [Admin backoffice](#admin-backoffice).
- **Admin shows a login page but I can't log in** — create a superuser first:
  `docker compose exec web python manage.py createsuperuser` (or set
  `DJANGO_SUPERUSER_USERNAME`/`DJANGO_SUPERUSER_PASSWORD` and let the entrypoint's
  `bootstrap` create it on the next start).
- **`docker compose` commands fail with a DB connection error** — make sure the `db`
  container is healthy: `docker compose ps`. The `web` service waits for it via a
  healthcheck; if `db` won't start, check `docker compose logs db`.
- **Host can't run `manage.py` / `pytest` directly** — by design (no GIS libs on the host).
  Always run them inside the container: `docker compose exec web …` / `docker compose run --rm web …`.
- **Port 5432 / 8000 already in use** — another local Postgres/server is bound. Stop it or
  remap the port in `docker-compose.yml`.

## License

Apache License 2.0 — see [LICENSE](LICENSE). Third-party libraries and their
licenses are inventoried in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).