# API reference

All routes are JSON over HTTP. API routes live under `/api/`; authentication routes under
`/api/auth/`. In a browser, `/api/` and the collection roots render DRF's **browsable API**.

## Conventions

### Authentication

Requests are authenticated, in order, by **JWT**, **Session**, then **API key**. Public
(`GET`) endpoints require no auth; writes require auth and (for service accounts) the
relevant model permission. See [Authentication](authentication.md).

| Scheme | Header |
| --- | --- |
| JWT | `Authorization: Bearer <access-token>` |
| API key | `Authorization: Api-Key <raw-key>` |
| Session | Django session cookie (admin / browser) |

### Pagination

List endpoints (except `/api/cities/all/`) are **paginated**:

```json
{
  "count": 2131,
  "next": "http://localhost:8000/api/cities/?page=2&page_size=25",
  "previous": null,
  "results": [ /* …page of items… */ ]
}
```

`?page=<n>` selects the page; `?page_size=<n>` sets the page size (capped at **1000**).
Default page size is **25**.

### Errors

Errors use DRF's default envelope. Validation errors return `400` with a field-keyed object
(or `{"detail": "…"}` for non-field errors); auth failures return `401` (with a
`WWW-Authenticate` header, because JWT is the first authenticator); permission failures
return `403`; missing objects return `404`.

```json
{ "detail": "Unknown city slug." }
```

### Filtering, search & ordering

Applies to list endpoints that declare them (`events`, `cities`, `venues`, `organizations`,
`categories`):

- `?search=<q>` — case-insensitive partial match on the endpoint's search fields
  (`events` on title/description, `cities` on name, …).
- `?ordering=<field>` / `?ordering=-<field>` — sort. Available fields: events
  `starts_at`, `created_at`, `distance`, `status`, `event_type`, `attendance_mode`,
  `published_at`; cities `name`, `population`.
- `?page_size=<n>` — page size (see Pagination).

> **Public visibility:** the public events list shows only `status=published` events.
> Operators (holders of `events.change_event`, or staff) see the full lifecycle; an owner
> can also retrieve their own drafts. See [Event lifecycle](#event-lifecycle) below.

> **Note on proximity ordering:** when a proximity filter (`lat`/`lon` or `near_city`) is
> active, results are ordered by **distance, nearest-first**, and `?ordering=` is ignored
> for the ordering itself. **Online events are excluded** from proximity results even if
> they carry a location (hybrid events keep their physical presence and stay in).
> Non-proximity listings fall back to the model's default ordering.

---

## Events

### `GET /api/events/` — list events

Public. Supports proximity filters, plus search/filter/ordering/pagination.

| Param | Type | Notes |
| --- | --- | --- |
| `lat`, `lon`, `radius_km` | float | **All three together.** Events within `radius_km` of the point. Results annotated with `distance` (km), nearest-first. **Online events excluded.** |
| `near_city` | string (slug) | Resolve to a city centroid + `default_radius_km`. Annotated with `distance`, nearest-first. **Mutually exclusive** with `lat`/`lon`. |
| `radius_km` | float | With `near_city`, overrides the city's default radius. |
| `city` | string | Exact, case-insensitive match on `venue.city` (free text). Independent of `near_city`. |
| `organization` | int | Filter by `organization_id`. |
| `organization_slug` | string | Filter by `organization.slug` (case-insensitive). |
| `event_type` | string | One of `meetup` / `conference` / `workshop` / `social` / `other`. |
| `attendance_mode` | string | One of `physical` / `online` / `hybrid`. |
| `status` | string | One of `draft` / `published` / `cancelled` / `archived` (operator-only — the queryset still enforces published for anon). |
| `starts_at_after`, `starts_at_before` | datetime | Date-range filter on `starts_at`. |
| `search` | string | Partial match on title/description. |
| `ordering` | string | `starts_at`, `created_at`, `distance`, `status`, `event_type`, `attendance_mode`, `published_at` (ignored when proximity active). |
| `page`, `page_size` | int | Pagination. |

```bash
curl 'http://localhost:8000/api/events/?near_city=berlin-de&radius_km=10'
```

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 42,
      "title": "Berlin Python Meetup",
      "description": "...",
      "starts_at": "2026-09-03T19:00:00+02:00",
      "ends_at": null,
      "venue": { "id": 7, "name": "Hacklab", "city": "Berlin", "latitude": 52.52, "longitude": 13.40, "capacity": 120 },
      "organization": { "id": 3, "name": "Python Berlin e.V.", "slug": "python-berlin-ev", "description": "...", "website": "https://example.org" },
      "categories": [ { "id": 1, "name": "Tech", "slug": "tech" } ],
      "capacity": null,
      "status": "published",
      "event_type": "meetup",
      "attendance_mode": "physical",
      "published_at": "2026-08-08T10:00:00+02:00",
      "cancelled_at": null,
      "original_url": "https://example.com/rust-meetup",
      "original_platform": "meetup",
      "source": { "id": 5, "url": "https://example.com/meetups.ics", "platform": "homepage" },
      "promoted_from": { "id": 88, "title": "Rust Meetup", "starts_at": "2026-09-03T19:00:00+02:00", "url": "https://example.com/rust-meetup", "platform": "meetup", "status": "promoted" },
      "created_by": 1,
      "created_at": "2026-08-08T10:00:00+02:00",
      "updated_at": "2026-08-08T10:00:00+02:00",
      "owner_group_id": null,
      "distance": 1.23,
      "latitude": 52.52,
      "longitude": 13.40
    }
  ]
}
```

`source` and `promoted_from` are `null` for hand-curated events; they're populated only for
events promoted from an observation (read-only — set by the promote action, never the public
payload).

Validation:

- `lat`/`lon`/`radius_km` must all be present together, or all absent → else `400`.
- `near_city` + (`lat` or `lon`) together → `400` `"Use either near_city or lat/lon, not both."`.
- Unknown `near_city` slug (or inactive city) → `400` `"Unknown city slug."`.
- Non-numeric `lat`/`lon`/`radius_km`, or negative `radius_km` → `400`.

### `POST /api/events/` — create an event

Authenticated. Human users may create freely; service accounts require `events.add_event`.
The creator becomes `created_by` (the owner). New events default to `status=published`.

```bash
curl -X POST http://localhost:8000/api/events/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "title": "Berlin Python Meetup",
    "starts_at": "2026-09-03T19:00:00+02:00",
    "venue_id": 7,
    "organization_id": 3,
    "category_ids": [1],
    "latitude": 52.52,
    "longitude": 13.40,
    "owner_group_id": 3
  }'
```

| Write field | Type | Notes |
| --- | --- | --- |
| `title` | string | required |
| `description` | string | optional |
| `starts_at` | datetime | required |
| `ends_at` | datetime | optional |
| `venue_id` | int | optional; if set and has a location, event copies it when no coords given |
| `organization_id` | int | optional |
| `category_ids` | int[] | optional |
| `capacity` | int | optional |
| `owner_group_id` | int | optional; co-owners who may edit/delete |
| `latitude`, `longitude` | float | optional, write-only; stored as `location` |

`created_by`, `created_at`, `updated_at`, `status`, `published_at`, `cancelled_at`,
`source`, and `promoted_from` are read-only (lifecycle/provenance are driven by dedicated
actions, not the public payload). Returns `201` with the created event (same shape as the
list item). Validation errors → `400`.

### `GET /api/events/<id>/` — retrieve

Public for `published` events. An owner may retrieve their own draft (`404` for anon).
Returns a single event (same shape as a list item, without `distance` unless a proximity
filter is applied to the collection).

### `PATCH /api/events/<id>/` — update

Allowed for the **owner** (`created_by`), members of the event's **`owner_group`**, or any
holder of `events.change_event`. Same write fields as `POST` (all optional on patch).
Returns `200` with the updated event; `403` if not allowed; `400` on validation error.

### `DELETE /api/events/<id>/`

Allowed for the **owner**, **`owner_group`** members, or any holder of
`events.delete_event`. Returns `204`; `403` if not allowed.

### Event lifecycle

Operators drive the event lifecycle from the API. Each action is a `POST` to a detail
sub-resource, gated by `events.change_event` (object-level: owner / `owner_group` member /
model-permission holder).

| Action | Endpoint | Effect |
| --- | --- | --- |
| Publish | `POST /api/events/<id>/publish/` | `status=published`, stamps `published_at` |
| Cancel | `POST /api/events/<id>/cancel/` | `status=cancelled`, stamps `cancelled_at` |
| Archive | `POST /api/events/<id>/archive/` | `status=archived` |
| Revert to draft | `POST /api/events/<id>/revert_to_draft/` | `status=draft` |

Returns `200` with the updated event; `403` if not allowed. (The same actions exist in the
backoffice — see [Admin backoffice](admin.md).)

---

## Cities (gazetteer)

Read-only catalog for location-based discovery. Public.

### `GET /api/cities/` — list/search/filter

| Param | Type | Notes |
| --- | --- | --- |
| `search` | string | partial match on `name` |
| `country_code` | string (2) | exact match, e.g. `DE` |
| `ordering` | string | `name`, `population` (`-population` for desc) |
| `page`, `page_size` | int | pagination (default 25, max 1000) |

```bash
curl 'http://localhost:8000/api/cities/?search=berlin'
```

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 104,
      "geoname_id": 2950159,
      "name": "Berlin",
      "slug": "berlin-de",
      "country": "Germany",
      "country_code": "DE",
      "latitude": 52.52,
      "longitude": 13.405,
      "default_radius_km": 45,
      "population": 3426354,
      "timezone": "Europe/Berlin"
    }
  ]
}
```

### `GET /api/cities/all/` — full catalog, unpaginated

Returns the **entire active catalog as a bare list** (no `{count, results}` envelope).
Filters (`search`, `country_code`, `ordering`) still apply. Useful for clients that want to
cache an offline pick-list / autocomplete. ~2131 cities.

```bash
curl 'http://localhost:8000/api/cities/all/?country_code=DE'
```

### `GET /api/cities/<id>/` — detail

Returns one city (same field shape as a list item).

---

## Venues, organizations, categories

| Collection | Endpoint | Search field | Notes |
| --- | --- | --- | --- |
| Venues | `/api/venues/` | `name` | Standard CRUD; reads public, writes authenticated. |
| Organizations | `/api/organizations/` | `name`, `description` | **Read-only** public catalog; lookup by `slug`. |
| Categories | `/api/categories/` | `name` | Standard CRUD; reads public, writes authenticated. |

### Venue

```json
{ "id": 7, "name": "Hacklab", "address": "Karl-Marx-Allee 1", "city": "Berlin",
  "latitude": 52.52, "longitude": 13.40, "capacity": 120 }
```

Write fields: `name`, `address`, `city`, `capacity`, `latitude`, `longitude` (coords stored
as `location`).

### Organization

Public, **read-only** (`ReadOnlyModelViewSet`); only active organizations are listed.
Detail lookups use the **`slug`**: `GET /api/organizations/<slug>/`.

```json
{ "id": 3, "name": "Python Berlin e.V.", "slug": "python-berlin-ev",
  "description": "...", "website": "https://example.org" }
```

`GET /api/organizations/<slug>/events/` — a detail action returning the organization's
**published** events (reuses the events queryset: published-only for anon, proximity
support, online excluded from proximity). Paginated like `/api/events/`.

### Category

```json
{ "id": 1, "name": "Tech", "slug": "tech" }
```

Write fields: `name` (`slug` is auto-generated and read-only).

---

## Ingestion (`/api/ingestion/`)

The extractor-facing surface: an external extraction system discovers due sources, reports
ingestion runs, and submits untrusted event observations. **Everything here is
authenticated** (JWT / Session / API key) and gated by the `IsIngestionService` permission —
the caller is a service account in an `ingestion` group carrying the relevant model perms
(see [Authentication](authentication.md#the-ingestion-group)). Anonymous → `401`; a
caller missing the required perm → `403`. Observations always enter as `pending` — the
extractor can never self-promote.

### `GET /api/ingestion/sources/due/` — the work queue

Requires `events.view_eventsource`. Returns approved, active sources due for a fetch
(`next_due_at` is null or in the past), never-fetched first. Each item carries the nested
owning organization.

```bash
curl -H "Authorization: Api-Key $KEY" \
  http://localhost:8000/api/ingestion/sources/due/
```

```json
{
  "count": 1, "next": null, "previous": null,
  "results": [
    { "id": 5,
      "organization": { "id": 3, "name": "Python Berlin e.V.", "slug": "python-berlin-ev" },
      "url": "https://example.com/meetups.ics", "platform": "homepage",
      "fetch_interval_minutes": 60, "last_fetched_at": null, "next_due_at": null }
  ]
}
```

### `POST /api/ingestion/runs/` — report a run

Requires `events.add_ingestionrun`. Creates a run (defaults to `status=running`,
`reported_by` = the caller, `started_at` = now if omitted). `source` (id) is required.

```bash
curl -X POST http://localhost:8000/api/ingestion/runs/ \
  -H "Authorization: Api-Key $KEY" -H 'Content-Type: application/json' \
  -d '{"source": 5}'
# → 201 { "id": 12, "source": 5, "status": "running", "started_at": "...", ... }
```

### `POST /api/ingestion/runs/<id>/success/` — finish (succeeded)

Requires `events.change_ingestionrun`. Sets `status=succeeded`, `finished_at=now`, takes
optional `events_found`. Also stamps the source's `last_fetched_at` and
`next_due_at` (= now + `fetch_interval_minutes`).

### `POST /api/ingestion/runs/<id>/failure/` — finish (failed)

Requires `events.change_ingestionrun`. Sets `status=failed`, `finished_at=now`, takes
optional `error_message`. Also stamps the source schedule.

> `PATCH /api/ingestion/runs/<id>/` (requires `events.change_ingestionrun`) finishes a run
> the same way when its `status` moves to `succeeded`/`failed`.

### `POST /api/ingestion/observations/` — submit an observation

Requires `events.add_eventobservation`. Creates one observation forced to `status=pending`.
`source` (id) is required; `run` (id) is optional. `latitude`/`longitude` are write-only
and stored as `location`. A body `status` is **ignored** (always pending).

```bash
curl -X POST http://localhost:8000/api/ingestion/observations/ \
  -H "Authorization: Api-Key $KEY" -H 'Content-Type: application/json' \
  -d '{
    "source": 5, "run": 12,
    "title": "Rust Meetup",
    "starts_at": "2026-09-10T19:00:00+02:00",
    "url": "https://example.com/rust", "platform": "meetup",
    "attendance_mode": "physical", "event_type": "meetup",
    "venue_name": "Factory Berlin", "venue_city": "Berlin",
    "latitude": 52.52, "longitude": 13.405,
    "raw_payload": { "…full extractor payload…": true }
  }'
# → 201 { "id": 88, "status": "pending", "latitude": 52.52, "longitude": 13.405, ... }
```

### `POST /api/ingestion/observations/bulk/` — submit many

Requires `events.add_eventobservation`. Body: `{"observations": [ <observation>, … ]}`.
Created transactionally (all-or-nothing); each forced to `status=pending`.

### `GET /api/ingestion/observations/` — list submitted

Requires `events.view_eventobservation`. Filter by `?source=`, `?run=`, `?status=`.
(`GET /api/ingestion/runs/` lists runs, requires `events.view_ingestionrun`.) Reviewing and
promoting observations is an **operator action in the backoffice**, never done by the
extractor — see [Admin backoffice](admin.md#event-observations--promotion).

---

## Authentication (`/api/auth/`)

### `POST /api/auth/register/` — register a user

Public.

```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"secret123","email":"alice@example.com"}'
```

Returns `201` with the new user. Validation errors → `400`.

### `POST /api/auth/login/` — session login

Public. Authenticates with username/password and starts a **Django session** (sets the
session cookie). Use for the admin / browser. Returns `200` on success, `400`/`401` on bad
credentials.

### `POST /api/auth/logout/` — session logout

Authenticated (session). Destroys the session. Returns `200` (or `204`).

### `POST /api/auth/token/` — obtain JWT

Public. Username + password → access + refresh tokens.

```bash
curl -X POST http://localhost:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"my-bot","password":"<secret>"}'
```

```json
{ "refresh": "<refresh-token>", "access": "<access-token>" }
```

Access tokens live **15 min**, refresh tokens **7 days**. Bad credentials → `401`.

### `POST /api/auth/token/refresh/` — refresh JWT

Public.

```bash
curl -X POST http://localhost:8000/api/auth/token/refresh/ \
  -H 'Content-Type: application/json' -d '{"refresh":"<refresh-token>"}'
```

```json
{ "access": "<new-access-token>" }
```

### `GET /api/auth/me/` — current user

Authenticated. Returns the calling user with their groups and permissions.

```json
{
  "id": 1,
  "username": "alice",
  "is_service_account": false,
  "groups": ["editors"],
  "permissions": ["events.add_event", "events.change_event"]
}
```

### `GET /api/auth/api-keys/` — list API keys

Authenticated. Returns the caller's keys (never the raw key — only `prefix`, `name`,
`created`, `revoked`, `expires_at`).

### `POST /api/auth/api-keys/` — create an API key

Authenticated. The **raw key is returned only this once**.

```bash
curl -X POST http://localhost:8000/api/auth/api-keys/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"outer-client"}'
```

```json
{ "id": 12, "name": "outer-client", "prefix": "AbC123Def456",
  "key": "AbC123Def456…<full-key>", "created": "2026-08-08T10:00:00Z",
  "expires_at": null }
```

Use the raw key as `Authorization: Api-Key <raw-key>`.

### `DELETE /api/auth/api-keys/<id>/` — revoke an API key

Authenticated (owner). Sets `revoked=true`; subsequent requests using that key fail auth.
Returns `204`.

---

## Management commands (not HTTP)

| Command | Purpose |
| --- | --- |
| `python manage.py createsuperuser` | Django admin login |
| `python manage.py seed_cities` | load the European city gazetteer (idempotent) |
| `python manage.py seed` | a few sample venues/organizations/categories/events |
| `python manage.py seed_demo` | rich demo dataset across all areas (orgs, sources, runs, observations, events + lifecycle/provenance) plus a `demo` staff user and the `ingestion` group; idempotent & non-destructive |
| `python manage.py create_service_account <name> --group <group>` | provision a system client (prints a one-time secret) |

Provision the extractor once (create the `ingestion` group + a service account in it, then
issue the account an API key) — see
[Authentication § The ingestion group](authentication.md#the-ingestion-group).

Run inside the container: `docker compose exec web python manage.py <command>`.