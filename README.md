# terminschleuder

A **Django + Django REST Framework** backend for local events and meetups, featuring
**PostGIS geospatial search** (events within *N* km of a point) and **JWT + API-key
authentication** for external and service clients.

> **Status:** `alpha-0.01` — early preview. APIs and data models may change before `1.0`.
> **License:** Apache-2.0 (see [LICENSE](LICENSE)).

---

## Table of contents

- [Overview](#overview)
- [Tech stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Local development & testing](#local-development--testing)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Documentation](#documentation)
- [Production notes](#production-notes)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)

## Overview

terminschleuder serves a catalog of **events, venues, organizers, and categories** with
geospatial locations, and exposes it through a REST API.

Highlights:

- **Proximity search** — `GET /api/events/?lat=&lon=&radius_km=` returns events within the
  radius, each annotated with a `distance` (km), ordered nearest-first. Built on PostGIS
  `geography` columns + `ST_DWithin`.
- **City catalog** — `GET /api/cities/` (search/filter/order) plus
  `GET /api/events/?near_city=<slug>` lets users find events by city without knowing
  coordinates. Seeded with all European cities ≥ 50 000 population.
- **Two auth mechanisms for external clients:**
  - **JWT** (simplejwt) — short-lived access + refresh tokens.
  - **Long-lived API keys** ("app secrets") — sha256-hashed, revocable, expirable.
- **Service / system users** — non-interactive accounts flagged `is_service_account` that
  carry Django groups & permissions and obtain JWTs / API keys like any user.
- **Ownership & permissions** — events have an owner (`created_by`) and an optional
  `owner_group`; writes are gated by owner / group membership / model permissions. Reads
  stay public.
- **`create_service_account` management command** to provision a system client.

## Tech stack

| Concern    | Choice                                              |
| ---------- | --------------------------------------------------- |
| Framework  | Django 6.1 + Django REST Framework 3.18             |
| Database   | PostgreSQL 17 + **PostGIS** (geospatial)            |
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

> **Heads-up:** the bare root path `/` returns **404 by design** — there is no route there.
> Use one of the mounted prefixes below.

| URL                                  | What it is                              |
| ------------------------------------ | --------------------------------------- |
| `http://localhost:8000/admin/`       | Django admin (backoffice)               |
| `http://localhost:8000/api/`         | API root — lists all event endpoints    |
| `http://localhost:8000/api/auth/`    | auth endpoints (register/login/me/token) |

`/api/` and the individual collections render DRF's **browsable API** in a browser.

### 3. Create an admin user / seed sample data

In a separate terminal while the stack is running:

```bash
# Admin login for /admin/
docker compose exec web python manage.py createsuperuser

# City gazetteer (all European cities >= 50k population) — powers ?near_city=
docker compose exec web python manage.py seed_cities

# Optional: a few sample venues, organizers, categories and events
docker compose exec web python manage.py seed
```

### 4. Run the tests

Tests run inside the container against real PostGIS and real auth:

```bash
docker compose run --rm web python -m pytest -q
```

(You can also run an individual file: `docker compose run --rm web python -m pytest events/tests.py -q`.)

### 5. Stop the stack

```bash
docker compose down            # stops & removes containers; the pgdata volume is kept
docker compose down -v         # also deletes the database volume (full reset)
```

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

JWT access tokens live **15 min**, refresh tokens **7 days**, signed with `SECRET_KEY`.

## API reference

### Base URLs

All API routes live under `/api/`; auth routes under `/api/auth/`.

| Method        | Endpoint                              | Auth            | Purpose                          |
| ------------- | ------------------------------------- | --------------- | -------------------------------- |
| GET           | `/api/cities/`                        | public          | city catalog (search/filter/order; `?page_size=`) |
| GET           | `/api/cities/all/`                    | public          | full catalog, unpaginated (one response) |
| GET           | `/api/cities/<id>/`                   | public          | city detail (with lat/lon)       |
| GET           | `/api/events/?near_city=<slug>`       | public          | events near a city (with distance) |
| GET           | `/api/events/?lat=&lon=&radius_km=`   | public          | proximity search (with distance) |
| GET / POST    | `/api/events/`                        | public / auth   | list / create events             |
| GET / PATCH / DELETE | `/api/events/<id>/`             | public / owner  | retrieve / update / delete       |
| GET / POST    | `/api/venues/`, `/api/organizers/`, `/api/categories/` | mixed | catalog + CRUD        |
| POST          | `/api/auth/register/`                 | public          | register a user                  |
| POST          | `/api/auth/token/`                    | public          | obtain JWT (access + refresh)    |
| POST          | `/api/auth/token/refresh/`            | public          | refresh JWT                      |
| GET           | `/api/auth/me/`                       | auth            | current user + groups + perms    |
| GET / POST    | `/api/auth/api-keys/`                 | auth            | list / create API keys           |
| DELETE        | `/api/auth/api-keys/<id>/`            | auth            | revoke an API key                |

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

### Ownership model

- `GET` (all collections) — **public** (the catalog).
- `POST /api/events/` — authenticated. Human users may create freely; service accounts
  require `events.add_event`.
- `PATCH` / `DELETE /api/events/<id>/` — allowed for the **owner** (`created_by`), a member
  of the event's **`owner_group`**, or any holder of the matching model permission.

## Documentation

This README is the quickstart. For the full functional documentation — architecture, data
model, complete API reference, authentication, and geospatial/cities — see the
**[docs/](docs/)** folder (GitHub-renderable Markdown + Mermaid diagrams):

| Document | Scope |
| -------- | ----- |
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/architecture.md](docs/architecture.md) | High-level design, container layout, request lifecycle |
| [docs/data-model.md](docs/data-model.md) | Entities, fields, relationships (ER diagram) |
| [docs/api-reference.md](docs/api-reference.md) | Every endpoint: params, examples, status codes, errors |
| [docs/authentication.md](docs/authentication.md) | JWT, API keys, service accounts, permissions, ownership |
| [docs/geospatial.md](docs/geospatial.md) | PostGIS storage, proximity, `?near_city=`, city catalog & seeding |

## Production notes

The app image is production-shaped: its default `CMD` runs **gunicorn** (`config.wsgi`).
The compose override only swaps in `runserver` for dev. For production:

- Set a strong `SECRET_KEY`, `DEBUG=False`, real `ALLOWED_HOSTS`, and a production
  `DATABASE_URL`.
- Serve behind a reverse proxy (TLS, static files, etc.) — out of scope here.
- Pull the image rather than building on the host (the constraint this project was built
  around).

## Project structure

```
.
├── manage.py
├── docker-compose.yml        # db (PostGIS) + web (Django dev server)
├── Dockerfile                # app image: GDAL/GEOS/PROJ + gunicorn
├── Dockerfile.db             # postgres:17 + postgis (arm64-friendly build)
├── requirements.txt
├── start.sh                  # thin `docker compose up` wrapper
├── config/                   # Django project: settings, urls, wsgi, asgi
├── events/                   # events, venues, organizers, categories + proximity
├── accounts/                 # users, service accounts, API keys, JWT views
├── locations/                # city gazetteer (City model, /api/cities/, seed_cities)
├── scripts/                  # offline tools (build_european_cities_fixture.py)
├── conftest.py               # shared pytest fixtures
└── pytest.ini
```

## Troubleshooting

- **`/` returns 404** — expected. The app is mounted at `/admin/` and `/api/`; there is no
  root route. See [Open the app](#2-open-the-app).
- **Admin shows a login page but I can't log in** — create a superuser first:
  `docker compose exec web python manage.py createsuperuser`.
- **`docker compose` commands fail with a DB connection error** — make sure the `db`
  container is healthy: `docker compose ps`. The `web` service waits for it via a
  healthcheck; if `db` won't start, check `docker compose logs db`.
- **Host can't run `manage.py` / `pytest` directly** — by design (no GIS libs on the host).
  Always run them inside the container: `docker compose exec web …` / `docker compose run --rm web …`.
- **Port 5432 / 8000 already in use** — another local Postgres/server is bound. Stop it or
  remap the port in `docker-compose.yml`.

## License

Apache License 2.0 — see [LICENSE](LICENSE).