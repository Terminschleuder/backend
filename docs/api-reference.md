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

Applies to list endpoints that declare them (`events`, `cities`, `venues`, `organizers`,
`categories`):

- `?search=<q>` — case-insensitive partial match on the endpoint's search fields
  (`events` on title/description, `cities` on name, …).
- `?ordering=<field>` / `?ordering=-<field>` — sort. Available fields: events
  `starts_at`, `created_at`, `distance`; cities `name`, `population`.
- `?page_size=<n>` — page size (see Pagination).

> **Note on proximity ordering:** when a proximity filter (`lat`/`lon` or `near_city`) is
> active, results are ordered by **distance, nearest-first**, and `?ordering=` is ignored
> for the ordering itself. Non-proximity listings fall back to the model's default ordering.

---

## Events

### `GET /api/events/` — list events

Public. Supports proximity filters, plus search/filter/ordering/pagination.

| Param | Type | Notes |
| --- | --- | --- |
| `lat`, `lon`, `radius_km` | float | **All three together.** Events within `radius_km` of the point. Results annotated with `distance` (km), nearest-first. |
| `near_city` | string (slug) | Resolve to a city centroid + `default_radius_km`. Annotated with `distance`, nearest-first. **Mutually exclusive** with `lat`/`lon`. |
| `radius_km` | float | With `near_city`, overrides the city's default radius. |
| `city` | string | Exact, case-insensitive match on `venue.city` (free text). Independent of `near_city`. |
| `search` | string | Partial match on title/description. |
| `ordering` | string | `starts_at`, `created_at`, `distance` (ignored when proximity active). |
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
      "organizer": null,
      "categories": [ { "id": 1, "name": "Tech", "slug": "tech" } ],
      "capacity": null,
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

Validation:

- `lat`/`lon`/`radius_km` must all be present together, or all absent → else `400`.
- `near_city` + (`lat` or `lon`) together → `400` `"Use either near_city or lat/lon, not both."`.
- Unknown `near_city` slug (or inactive city) → `400` `"Unknown city slug."`.
- Non-numeric `lat`/`lon`/`radius_km`, or negative `radius_km` → `400`.

### `POST /api/events/` — create an event

Authenticated. Human users may create freely; service accounts require `events.add_event`.
The creator becomes `created_by` (the owner).

```bash
curl -X POST http://localhost:8000/api/events/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "title": "Berlin Python Meetup",
    "starts_at": "2026-09-03T19:00:00+02:00",
    "venue_id": 7,
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
| `organizer_id` | int | optional |
| `category_ids` | int[] | optional |
| `capacity` | int | optional |
| `owner_group_id` | int | optional; co-owners who may edit/delete |
| `latitude`, `longitude` | float | optional, write-only; stored as `location` |

`created_by`, `created_at`, `updated_at` are read-only. Returns `201` with the created
event (same shape as the list item). Validation errors → `400`.

### `GET /api/events/<id>/` — retrieve

Public. Returns a single event (same shape as a list item, without `distance` unless a
proximity filter is applied to the collection).

### `PATCH /api/events/<id>/` — update

Allowed for the **owner** (`created_by`), members of the event's **`owner_group`**, or any
holder of `events.change_event`. Same write fields as `POST` (all optional on patch).
Returns `200` with the updated event; `403` if not allowed; `400` on validation error.

### `DELETE /api/events/<id>/`

Allowed for the **owner**, **`owner_group`** members, or any holder of
`events.delete_event`. Returns `204`; `403` if not allowed.

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

## Venues, organizers, categories

Standard CRUD viewsets. Reads are public; writes are authenticated (service accounts need
the relevant `add`/`change`/`delete` permission).

| Collection | Endpoint | Search field |
| --- | --- | --- |
| Venues | `/api/venues/` | `name` |
| Organizers | `/api/organizers/` | `name` |
| Categories | `/api/categories/` | `name` |

### Venue

```json
{ "id": 7, "name": "Hacklab", "address": "Karl-Marx-Allee 1", "city": "Berlin",
  "latitude": 52.52, "longitude": 13.40, "capacity": 120 }
```

Write fields: `name`, `address`, `city`, `capacity`, `latitude`, `longitude` (coords stored
as `location`).

### Organizer

```json
{ "id": 3, "name": "Python Berlin e.V.", "description": "...",
  "website": "https://example.org", "owner": 1 }
```

Write fields: `name`, `description`, `website`, `owner` (user id).

### Category

```json
{ "id": 1, "name": "Tech", "slug": "tech" }
```

Write fields: `name` (`slug` is auto-generated and read-only).

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
| `python manage.py seed` | sample venues/organizers/categories/events |
| `python manage.py create_service_account <name> --group <group>` | provision a system client (prints a one-time secret) |

Run inside the container: `docker compose exec web python manage.py <command>`.