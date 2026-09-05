# Architecture

## Purpose

terminschleuder is a backend that is the **system of record** for a catalog of **local
events and meetups**, lets clients discover them by **location** (proximity to a point or to
a city), and ingests events from an **external extraction pipeline**. Organizations own
event-source URLs; an extractor crawls approved sources, reports ingestion runs, and
submits **untrusted** event observations; operators review and **promote** accepted
observations into **canonical (published) events** with full provenance. It also provides
**authentication for external/service clients** (JWT and long-lived API keys) with
group-based permissions and event ownership.

## Design constraint: no GIS on the host

`django.contrib.gis` loads GDAL/GEOS/PROJ from the system. The deployment target does
**not** allow installing system packages — in production the machine "can only pull the
image of this app". This constraint drives the whole runtime shape:

- The **app image bundles** GDAL/GEOS/PROJ (installed via apt in `Dockerfile`).
- The **database runs PostGIS** (a custom `postgres:18` + postgis image, `Dockerfile.db`).
- The host never runs the app directly — all dev, tests, and prod run inside containers.
- Production deploys by pulling the image; no host provisioning of GIS libraries.

## Container architecture

```mermaid
flowchart LR
    Client["Client / browser"] -->|HTTP :8000| Web

    subgraph compose["docker compose"]
        Web["web (Django + DRF)\nGDAL/GEOS/PROJ bundled\nrunserver (dev) / gunicorn (prod)"]
        DB[("db (PostgreSQL 18 + PostGIS)\npgdata volume")]
        Media[("media volume\n(event hero images)")]
        Web -->|postgis:// :5432| DB
        Web -.->|/app/media| Media
    end
```

- **db** — PostgreSQL 18 with the PostGIS extension. Healthchecked with `pg_isready`; the
  `pgdata` named volume persists data across restarts. The image (`Dockerfile.db`) is
  deliberately pinned to a Postgres **major** and is not auto-updated by Dependabot — a
  major bump is a breaking data change; local dev recreates the disposable `pgdata`
  volume, production runs the dump/restore runbook in `README.md` → "PostgreSQL major
  upgrades".
- **web** — the Django app. The image's `ENTRYPOINT` (`docker-entrypoint.sh`) waits for the
  database, runs migrations, then the idempotent `bootstrap` command (operator superuser
  from `DJANGO_SUPERUSER_*` env, `ingestion` group, city gazetteer — never demo data)
  before handing off to the command: `runserver` with the source bind-mounted for hot
  reload in dev, the default `CMD` `gunicorn` in production. One-off jobs pass
  `ENTRYPOINT_SKIP_TASKS=1` to skip migrate + bootstrap.
- **media volume** — persists uploaded/generated event hero images at `/app/media` (mounted
  over the source bind mount so uploads survive restarts). Served by Django at `/media/`
  when `SERVE_MEDIA=True` (the default — the pure-container deployment has no reverse
  proxy); set `SERVE_MEDIA=False` when a proxy/CDN serves the volume instead. As with
  `pgdata`, `docker compose down -v` would wipe it — use `down` (no `-v`).

**Static files** are collected at image build time (`collectstatic` → `STATIC_ROOT`) and
served in production by **WhiteNoise** directly from gunicorn — admin CSS/JS included, no
reverse proxy needed.

## Apps

| App | Responsibility |
| --- | -------------- |
| `config` | Django project: settings, root URL conf, WSGI/ASGI, pagination class. |
| `events` | Canonical events, venues, organizations, categories; **ingestion & provenance** (event sources, ingestion runs, event observations); event lifecycle; proximity search; ownership permissions. The extractor-facing API surface (`ingestion_views.py` / `ingestion_urls.py` / `ingestion_serializers.py`) lives here too — not in a separate app — to avoid a cross-app migration cycle on `Event.source`/`Event.promoted_from`. |
| `accounts` | Users, service/system accounts, API keys, JWT views, registration. |
| `locations` | City gazetteer (catalog + `?near_city=` resolution); seeded from GeoNames. |
| `admin` | Human backoffice: a custom `AdminSite` (`terminschleuder_admin`) mounted at `/admin/`, reusing Django session auth. Owns service-account & API-key issuance, group/city/organization/source/observation/event maintenance, observation promotion, and event lifecycle. App label `backoffice` (the package is `admin` but the label is overridden to avoid clashing with `django.contrib.admin`). |

## URL routing

```mermaid
flowchart LR
    R["Request"] --> P{"path prefix?"}
    P -->|"/api/auth/"| Auth["accounts (register/login/token/me/api-keys)"]
    P -->|"/api/ingestion/"| Ing["events.ingestion_urls (due sources / runs / observations)"]
    P -->|"/api/"| API["events + locations (DRF routers)"]
    P -->|"/api/schema/"| Schema["OpenAPI 3 schema + Swagger/ReDoc"]
    P -->|"/media/"| Media["uploaded media (when SERVE_MEDIA=True, the default)"]
    P -->|"/admin/"| Back["terminschleuder_admin (backoffice; anon -> /admin/login/)"]
    P -->|"/"| Landing["public marketing page (TemplateView, no auth)"]
    P -->|"/anything else"| Nf["404"]
```

The admin is mounted at `path("admin/", terminschleuder_admin.urls)` so its built-in
catch-all is confined to `/admin/...` and cannot shadow `/api/...` or `/media/...`
(`/api/ingestion/` is listed above `/api/` so its router wins). The site root (`/`) is a
public `TemplateView` landing page (no auth, no catch-all), so unknown paths 404 instead
of redirecting to login. The backoffice uses Django session auth + `is_staff`; anonymous
`/admin/` redirects to `/admin/login/`. See [Authentication](authentication.md) and
[Admin backoffice](admin.md).

## Request lifecycle

### Public catalog & event API

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
    W->>W: get_queryset (visible_events: published-only for anon; filter / proximity; online excluded)
    W->>DB: spatial + scalar queries
    DB-->>W: rows (+ distance annotation)
    W-->>C: JSON (paginated or list)
```

### Extractor ingestion path

```mermaid
sequenceDiagram
    participant X as Extractor (service account)
    participant V as ingestion view
    participant A as Auth + IsIngestionService
    participant DB as PostGIS DB
    participant O as Operator (backoffice)

    X->>V: GET /api/ingestion/sources/due/  (Api-Key)
    V->>A: authenticate + check ingestion_perms (view_eventsource)
    A-->>V: user / 403
    V->>DB: EventSource.due() (approved + active + due)
    DB-->>X: due sources (work queue)
    X->>V: POST /api/ingestion/runs/  →  POST /api/ingestion/observations/
    V->>DB: create run (running) + pending observations
    X->>V: POST /api/ingestion/runs/<id>/success/
    V->>DB: run succeeded; stamp source last_fetched_at / next_due_at
    O->>DB: review observation → promote (draft Event + provenance) → publish
    DB-->>X: canonical published event visible on the public API
```

The extractor never writes a canonical `Event`; it only reports runs and submits `pending`
observations. Promotion (observation → draft event) and the publish/cancel/archive lifecycle
are operator actions in the backoffice.

Authentication classes are tried in order: **JWT**, **Session**, **API key**. JWT is first
so DRF emits a `WWW-Authenticate` header and auth failures return **401** (not 403).

## Tech stack

| Concern | Choice |
| --- | --- |
| Framework | Django 6.1 + Django REST Framework 3.18 |
| Database | PostgreSQL 18 + PostGIS |
| Auth | djangorestframework-simplejwt (JWT) + custom hashed API keys |
| GIS | GDAL / GEOS / PROJ (bundled in the image) |
| Config | django-environ (`DATABASE_URL`), django-filter |
| CORS | django-cors-headers (read-only GET/HEAD/OPTIONS for the demo client; no credentials) |
| API docs | drf-spectacular (OpenAPI 3 schema at `/api/schema/` + Swagger UI / ReDoc) |
| Imaging | Pillow (`ImageField` validation + generated hero banners in `seed_demo`) |
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
| `CORS_ALLOW_ALL_ORIGINS` | `True` | Read-only GET/HEAD/OPTIONS from any origin (demo-friendly). Set `False` in prod. |
| `CORS_ALLOWED_ORIGINS` | `[]` | Allowed origins when `CORS_ALLOW_ALL_ORIGINS=False`. |
| `SERVE_MEDIA` | `True` | Serve `/media/` through Django (no reverse proxy in the pure-container deployment). |
| `DJANGO_SUPERUSER_USERNAME` / `_PASSWORD` / `_EMAIL` | unset | Read by the entrypoint's `bootstrap`: creates the operator superuser on a fresh DB; never overwrites. |
| `ENTRYPOINT_SKIP_TASKS` | `0` | `1` = entrypoint skips migrate + bootstrap (one-off jobs against the image). |

JWT access tokens live 15 min, refresh tokens 7 days, signed with `SECRET_KEY`.

Media: `MEDIA_URL = /media/`, `MEDIA_ROOT = /app/media` (the `media` volume). Event hero
images are stored under `events/hero/`; the API exposes their absolute URL read-only.

## Testing & CI

- Tests run inside the container against real PostGIS and real auth:
  `docker compose run --rm web python -m pytest -q`.
- CI (`.github/workflows/ci.yml`) builds the compose stack and runs `check` → `migrate` →
  `pytest` on every push/PR. Every commit that lands on `main` cuts a **CalVer release**
  (`YYYY.MINOR.0`, git tag `vYYYY.MINOR.0`): the release job versions, builds & pushes both
  images (app + PostGIS db) to ghcr.io tagged `<release-version>`/`latest`/`sha-<short>`,
  scans them with Trivy (app blocks, db is report-only), then creates the git tag +
  GitHub Release last — idempotent on re-run. PRs and `develop` pushes never publish.

## Project layout

```
.
├── manage.py
├── docker-compose.yml        # db (PostGIS) + web (Django dev server)
├── Dockerfile                # app image: GDAL/GEOS/PROJ + gunicorn
├── Dockerfile.db             # postgres:18 + postgis (arm64-friendly build)
├── requirements.txt
├── start.sh                  # thin `docker compose up` wrapper
├── config/                   # Django project: settings, urls, wsgi, asgi, pagination
├── admin/                    # backoffice: custom AdminSite at /admin/ (label "backoffice")
├── events/                   # events, venues, organizations, categories + proximity;
│   │                          ingestion & provenance (EventSource, IngestionRun,
│   │                          EventObservation); event lifecycle; extractor API
│   ├── ingestion_views.py    #   /api/ingestion/ views (due sources, runs, observations)
│   ├── ingestion_urls.py     #   /api/ingestion/ routes
│   ├── ingestion_serializers.py  # extractor-facing serializers
│   └── data/seed/*.json      #   demo seed data (regenerate via build_demo_fixture.py)
├── accounts/                 # users, service accounts, API keys, JWT views
├── locations/                # city gazetteer (City model, /api/cities/, seed_cities)
├── scripts/                  # offline tools (build_european_cities_fixture.py, build_demo_fixture.py)
├── docs/                     # this documentation
├── conftest.py               # shared pytest fixtures
└── pytest.ini
```