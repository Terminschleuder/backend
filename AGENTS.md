# AGENTS.md — instructions for AI agents working on this repo

> Read this **before** making any change to this codebase. It captures the rules that are
> easy to forget and the invariants that must not silently break.

## The one rule that matters most

**Every code change must keep the tests, the README, and the docs in sync.**

A change is not "done" when the code compiles. It is done only when **all four** are true:

1. **Code** — the change is implemented.
2. **Tests** — existing tests still pass, and new behavior is covered by new tests.
3. **README** — the quickstart / API table / config table reflect the change.
4. **`docs/`** — the functional documentation reflects the change.

If you touch a model, endpoint, query param, auth rule, serializer field, management
command, env var, or the container/CI setup, ask yourself for each of the four: *"Does this
need to change? Does this need a new test?"* If you're not sure, assume yes.

### What lives where

- `README.md` — the **quickstart** (run it, test it, configure it) + a concise API table.
  Keep it scannable; push depth into `docs/`.
- `docs/` — the **functional documentation** (architecture, data model, full API reference,
  authentication, geospatial & cities). See `docs/README.md` for the index.
- `*/tests.py` + `conftest.py` — the **behavioral spec**. Tests run against real PostGIS and
  real auth, in the container.

### Sync checklist (run through it before declaring a task complete)

- [ ] Model/field/serializer change → updated `docs/data-model.md`?
- [ ] Endpoint/param/status-code/serializer-field change → updated `docs/api-reference.md` **and** the README API table?
- [ ] Auth/permission/ownership/key/JWT change → updated `docs/authentication.md`?
- [ ] Proximity / `near_city` / city catalog / seeding change → updated `docs/geospatial.md`?
- [ ] Container / CI / env / project-layout change → updated `docs/architecture.md` **and** README?
- [ ] New behavior → **new test(s)** added and passing?
- [ ] README quickstart steps still accurate (commands, ports, paths)?

## Hard constraint: no GIS on the host

> "make sure, to not install stuff like GIS on this machine except via pip/uv or
> docker/container. the prod machine will not allow to install stuff, on prod we can only
> pull the image of this app."

- The **app image bundles** GDAL/GEOS/PROJ (apt in `Dockerfile`); the **db is PostGIS**
  (`Dockerfile.db`).
- **Never** install GDAL/GEOS/PROJ/PostGIS on the host. **Never** run `manage.py` or
  `pytest` on the host — there are no GIS libs there and it will fail.
- All dev, tests, migrations, and prod run **inside containers**. Production deploys by
  pulling the image; no host provisioning.

## How to run things (always inside the container)

```bash
# Start the dev stack (db + web), hot-reload, auto-migrate
./start.sh            # or: docker compose up --build

# Run the full test suite against real PostGIS + real auth
docker compose run --rm web python -m pytest -q

# Run one file / one test
docker compose run --rm web python -m pytest events/tests.py -q

# System check + migration consistency
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run

# Seed / admin / service account
docker compose exec web python manage.py seed_cities
docker compose exec web python manage.py seed
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py create_service_account <name> --group <group>

# Tear down
docker compose down        # keep the pgdata volume
docker compose down -v     # also wipe the DB volume (full reset)
```

## Verification gate (do this before committing)

```bash
docker compose run --rm web python -m pytest -q          # all green
docker compose exec web python manage.py check           # clean
docker compose exec web python manage.py makemigrations --check --dry-run   # "No changes"
```

If any of these fails, the change is not complete — fix it before committing. Do not commit
a generated migration without `--check --dry-run` reporting "No changes detected".

## Known gotchas (don't re-learn these the hard way)

- **DRF 3.18 auth-failure 403 vs 401:** `handle_exception` coerces to 403 when
  `get_authenticate_header` returns `None`. Keep `JWTAuthentication` **first** in
  `DEFAULT_AUTHENTICATION_CLASSES` so auth failures return 401 with a `WWW-Authenticate`
  header.
- **Django permission cache:** `user.has_perm()` caches on the instance. After granting a
  group permission mid-process, **refetch the user** (`User.objects.get(pk=user.pk)`)
  before re-checking, or the cached negative result persists.
- **OrderingFilter clobbering proximity order:** do **not** set a default `ordering` attr
  on a viewset that also does `order_by("distance")` for proximity — the filter re-applies
  and clobbers it. Leave `ordering` unset there; rely on the model `Meta.ordering` for the
  non-proximity case.
- **Write-only serializer fields without `source`** (e.g. `latitude`/`longitude`) land in
  `validated_data` and crash `Model(**validated_data)`. **Pop them** before
  `super().create/update`.
- **PostGIS Point order is `(longitude, latitude)`** — `Point(13.405, 52.52)` is Berlin.
- **`?near_city=<slug>` (gazetteer centroid, distance filter) is distinct from
  `?city=<text>` (exact venue-city match).** Don't conflate them.
- **Backoffice is a custom `AdminSite` at `/admin/`.** Registration lives in
  **`admin/admin.py`** on `terminschleuder_admin` — the per-app `admin.py` files define
  `ModelAdmin` classes but do **not** `@admin.register(...)` (that would register on the
  unused default site). Add a new model → register it in `admin/admin.py`. The app package
  is `admin` but its `AppConfig.label` is `"backoffice"` (avoids clashing with
  `django.contrib.admin`'s label), so makemigrations/tests reference label `backoffice`.
  In `config/urls.py` the admin is mounted at `path("admin/", terminschleuder_admin.urls)`,
  so its built-in catch-all is **confined to `/admin/...`** and cannot shadow `/api/...` or
  `/media/...` (served under DEBUG). The site root (`/`) is a public `TemplateView` landing
  page. The `AdminSite.name` stays `"admin"` (default) so built-in admin templates reverse
  correctly.

## Commit conventions

- Keep commits focused; describe *what and why*.
- End commit messages with:
  `Co-Authored-By: Claude <noreply@anthropic.com>`
- Only push when the user asks. The default branch is `main`.

## Project layout (cheat sheet)

```
config/      Django project (settings, urls, pagination)
admin/       backoffice: custom AdminSite at /admin/ (label "backoffice"); registry in admin/admin.py
events/      events, venues, organizers, categories + proximity + ownership
accounts/    users, service accounts, API keys, JWT/session views
locations/   city gazetteer (City model, /api/cities/, seed_cities)
scripts/     offline tools (build_european_cities_fixture.py)
docs/        functional documentation
conftest.py  shared pytest fixtures
```

When in doubt: run the tests, read `docs/`, and keep all four (code / tests / README / docs)
in step.