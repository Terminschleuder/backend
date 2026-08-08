# Architecture

## Purpose

terminschleuder is a backend that serves a catalog of **local events and meetups** and lets
clients discover them by **location** (proximity to a point or to a city). It also provides
**authentication for external/service clients** (JWT and long-lived API keys) with
group-based permissions and event ownership.

## Design constraint: no GIS on the host

`django.contrib.gis` loads GDAL/GEOS/PROJ from the system. The deployment target does
**not** allow installing system packages — in production the machine "can only pull the
image of this app". This constraint drives the whole runtime shape:

- The **app image bundles** GDAL/GEOS/PROJ (installed via apt in `Dockerfile`).
- The **database runs PostGIS** (a custom `postgres:17` + postgis image, `Dockerfile.db`).
- The host never runs the app directly — all dev, tests, and prod run inside containers.
- Production deploys by pulling the image; no host provisioning of GIS libraries.

## Container architecture

```mermaid
flowchart LR
    Client["Client / browser"] -->|HTTP :8000| Web

    subgraph compose["docker compose"]
        Web["web (Django + DRF)\nGDAL/GEOS/PROJ bundled\nrunserver (dev) / gunicorn (prod)"]
        DB[("db (PostgreSQL 17 + PostGIS)\npgdata volume")]
        Web -->|postgis:// :5432| DB
    end
```

- **db** — PostgreSQL 17 with the PostGIS extension. Healthchecked with `pg_isready`; the
  `pgdata` named volume persists data across restarts.
- **web** — the Django app. In dev it runs `migrate` then `runserver` with the source
  bind-mounted for hot reload; the image's default `CMD` is `gunicorn` for production.

## Apps

| App | Responsibility |
| --- | -------------- |
| `config` | Django project: settings, root URL conf, WSGI/ASGI, pagination class. |
| `events` | Events, venues, organizers, categories; proximity search; ownership permissions. |
| `accounts` | Users, service/system accounts, API keys, JWT views, registration. |
| `locations` | City gazetteer (catalog + `?near_city=` resolution); seeded from GeoNames. |

## Request lifecycle

```mermaid
sequenceDiagram
    participant C as Client
    participant W as DRF view
    participant A as Auth classes
    participant P as Permission
    participant DB as PostGIS DB

    C->>W: HTTP request
    W->>A: authenticate (JWT → Session → API key)
    A-->>W: user (+ auth) or 401
    W->>P: check_permissions (IsOwnerOrGroupOrReadOnly / IsAuthenticatedOrReadOnly)
    P-->>W: allow / 403
    W->>W: get_queryset (filter / search / proximity / near_city)
    W->>DB: spatial + scalar queries
    DB-->>W: rows (+ distance annotation)
    W-->>C: JSON (paginated or list)
```

Authentication classes are tried in order: **JWT**, **Session**, **API key**. JWT is first
so DRF emits a `WWW-Authenticate` header and auth failures return **401** (not 403).

## Tech stack

| Concern | Choice |
| --- | --- |
| Framework | Django 6.1 + Django REST Framework 3.18 |
| Database | PostgreSQL 17 + PostGIS |
| Auth | djangorestframework-simplejwt (JWT) + custom hashed API keys |
| GIS | GDAL / GEOS / PROJ (bundled in the image) |
| Config | django-environ (`DATABASE_URL`), django-filter |
| Tests | pytest + pytest-django |
| Runtime | Docker + Docker Compose |

## Configuration

Settings come from the environment via `django-environ`. Local dev is self-contained in
`docker-compose.yml` (no `.env` required).

| Variable | Default | Notes |
| --- | --- | --- |
| `SECRET_KEY` | `django-insecure-change-me` | Set a strong value in production. |
| `DEBUG` | `False` | Compose sets `True` for dev. |
| `ALLOWED_HOSTS` | `[]` | Compose sets `*` for dev. |
| `DATABASE_URL` | `postgis://terminschleuder:terminschleuder@127.0.0.1:5432/terminschleuder` | Compose overrides to the `db` host. |

JWT access tokens live 15 min, refresh tokens 7 days, signed with `SECRET_KEY`.

## Testing & CI

- Tests run inside the container against real PostGIS and real auth:
  `docker compose run --rm web python -m pytest -q`.
- CI (`.github/workflows/ci.yml`) builds the compose stack and runs `check` → `migrate` →
  `pytest` on every push/PR and on `alpha-*`/`v*` tags.

## Project layout

```
.
├── manage.py
├── docker-compose.yml        # db (PostGIS) + web (Django dev server)
├── Dockerfile                # app image: GDAL/GEOS/PROJ + gunicorn
├── Dockerfile.db             # postgres:17 + postgis (arm64-friendly build)
├── requirements.txt
├── start.sh                  # thin `docker compose up` wrapper
├── config/                   # Django project: settings, urls, wsgi, asgi, pagination
├── events/                   # events, venues, organizers, categories + proximity
├── accounts/                 # users, service accounts, API keys, JWT views
├── locations/                # city gazetteer (City model, /api/cities/, seed_cities)
├── scripts/                  # offline tools (build_european_cities_fixture.py)
├── docs/                     # this documentation
├── conftest.py               # shared pytest fixtures
└── pytest.ini
```