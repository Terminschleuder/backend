# terminschleuder

A Django + Django REST Framework backend for serving **local events and meetups**, with
**PostGIS**-powered geospatial search (find events within *N* km of a location) and
**service-account / API-key + JWT** authentication for external clients.

> **Status:** `alpha-0.01` — early preview. APIs and data models may change before `1.0`.

---

## Features

- **Events, venues, organizers, categories** — the core catalog.
- **Geospatial proximity search** — `?lat=&lon=&radius_km=` returns events within the
  radius, each annotated with a `distance` (km), ordered nearest-first. Powered by
  PostGIS `geography` columns + `ST_DWithin`.
- **Authentication for external clients** — both:
  - **JWT** (`djangorestframework-simplejwt`) — short-lived access + refresh tokens,
  - **long-lived API keys** ("app secrets") — sha256-hashed, revocable, expirable.
- **Service / system users** — non-interactive accounts (flagged `is_service_account`)
  that carry Django groups & permissions and obtain JWTs / API keys like any user.
- **Ownership & permissions** — events support an owner (`created_by`) and an
  `owner_group`; writes are gated by owner / group membership / model permissions.
  Reads stay public (the catalog).
- **Management command** — `create_service_account` to provision a system client.

## Tech stack

| Concern        | Choice                                              |
| -------------- | --------------------------------------------------- |
| Framework      | Django 6.1 + Django REST Framework 3.18             |
| Database       | PostgreSQL 17 + **PostGIS** (geospatial)            |
| Auth           | simplejwt (JWT) + custom hashed API keys            |
| GIS libs       | GDAL / GEOS / PROJ (bundled in the app image)       |
| Packaging      | `django-environ` (`DATABASE_URL`), `django-filter` |
| Tests          | `pytest` + `pytest-django`                          |
| Runtime        | Docker + Docker Compose                            |

> **Why a container?** `django.contrib.gis` needs GDAL/GEOS/PROJ on the host. To keep
> the host clean and make production a single `docker pull`, the app image bundles the
> GIS libraries and runs against a PostGIS database container. No host GIS installs.

## Quick start (Docker)

```bash
# 1. Build and run db (PostGIS) + web (Django dev server)
./start.sh            # = docker compose up --build; stops cleanly on Ctrl-C

# 2. The web service runs migrations automatically, then serves on :8000.
curl http://127.0.0.1:8000/api/events/
```

Configuration is self-contained in `docker-compose.yml` for local dev. For production,
override the env (`SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, `DEBUG=False`) — see
`.env.example`.

### Useful commands (run inside the container)

```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py create_service_account my-bot --group editors
docker compose exec web python manage.py test          # or: python -m pytest -q
```

## API overview

| Method | Endpoint                              | Auth            | Purpose                          |
| ------ | ------------------------------------- | --------------- | -------------------------------- |
| GET    | `/api/events/?lat=&lon=&radius_km=`   | public          | proximity search (with distance) |
| GET    | `/api/events/`                        | public          | list / filter / search events     |
| POST   | `/api/events/`                         | auth (perm)     | create an event                  |
| GET/…  | `/api/venues/`, `/api/organizers/`, `/api/categories/` | mixed | catalog + CRUD |
| POST   | `/api/auth/register/`                 | public          | register a user                  |
| POST   | `/api/auth/token/`                    | public          | obtain JWT (access + refresh)    |
| POST   | `/api/auth/token/refresh/`            | public          | refresh JWT                      |
| GET    | `/api/auth/me/`                        | auth            | current user + groups + perms    |
| GET/POST | `/api/auth/api-keys/`               | auth            | list / create API keys           |
| DELETE | `/api/auth/api-keys/<id>/`            | auth            | revoke an API key                |

### Proximity example

```bash
curl 'http://127.0.0.1:8000/api/events/?lat=52.52&lon=13.405&radius_km=10'
# → events within 10 km of Berlin, each with a "distance" (km), nearest first
```

### Auth example

```bash
# JWT
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"my-bot","password":"<secret>"}' | jq -r .access)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/auth/me/

# API key ("app secret") — raw key returned once on creation
curl -X POST http://127.0.0.1:8000/api/auth/api-keys/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"outer-client"}'
curl -H "Authorization: Api-Key <raw-key>" http://127.0.0.1:8000/api/events/
```

## Project structure

```
.
├── manage.py
├── docker-compose.yml        # db (PostGIS) + web (Django)
├── Dockerfile                # app image: bundles GDAL/GEOS/PROJ + gunicorn
├── Dockerfile.db             # postgres:17 + postgis (arm64-friendly build)
├── requirements.txt
├── config/                   # Django project settings/urls/wsgi
├── events/                   # events, venues, organizers, categories + proximity
├── accounts/                 # users, service accounts, API keys, JWT views
├── conftest.py               # shared pytest fixtures
└── start.sh                  # thin `docker compose up` wrapper
```

## Testing

Tests run inside the container (real PostGIS + real auth):

```bash
docker compose run --rm web python -m pytest -q
```

The CI workflow (`.github/workflows/ci.yml`) builds the images and runs the same
command on every push and pull request.

## License

Apache License 2.0 — see [LICENSE](LICENSE).