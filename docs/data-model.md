# Data model

The core domain is **canonical events** that happen at **venues**, are owned by
**organizations**, and are tagged with **categories**. Events and venues carry a
**geographic location** (PostGIS `Point`). An **ingestion pipeline** lets external
extractors submit **untrusted event observations** against an organization's **event
sources** (URLs); operators review observations and **promote** accepted ones into canonical
events with full **provenance**. A **city** gazetteer supports location-based discovery, and
**users** / **API keys** handle authentication and ownership.

The trust boundary is central: `Event` is the trusted, published record; `EventObservation`
is untrusted and never mutates an `Event` directly — an operator promotes an accepted
observation into a draft event (linked back via `Event.promoted_from`), which is then
published.

## Entity-relationship diagram

```mermaid
erDiagram
  USER ||--o{ EVENT : "created_by"
  USER ||--o{ ORGANIZATION : "owner"
  USER ||--o{ APIKEY : "owns"
  USER }o--o{ GROUP : "groups"
  GROUP ||--o{ EVENT : "owner_group"
  EVENT }o--o| VENUE : "venue"
  EVENT }o--o| ORGANIZATION : "organization"
  EVENT }o--o{ CATEGORY : "categories"
  EVENT }o--o| EVENTSOURCE : "source"
  EVENT }o--o| EVENTOBSERVATION : "promoted_from"
  ORGANIZATION ||--o{ EVENTSOURCE : "sources"
  EVENTSOURCE ||--o{ INGESTIONRUN : "runs"
  EVENTSOURCE ||--o{ EVENTOBSERVATION : "observations"
  INGESTIONRUN ||--o{ EVENTOBSERVATION : "run"
  USER ||--o{ EVENTSOURCE : "created_by"
  USER ||--o{ INGESTIONRUN : "reported_by"
  USER ||--o{ EVENTOBSERVATION : "reviewed_by"
  CITY {
    bigint geoname_id
    string name
    string slug
    string country
    string country_code
    point  location
    int    default_radius_km
    bigint population
    string timezone
    bool   is_active
  }
```

> `City` is independent of the event graph — it is a gazetteer used to resolve
> `?near_city=<slug>` to a centroid + radius (see [Geospatial & cities](geospatial.md)).

## Event

A canonical event — the trusted, published record exposed to consumers.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | BigAutoField | PK |
| `title` | CharField(200) | |
| `description` | TextField | blank allowed |
| `starts_at` | DateTimeField | indexed (asc + desc) |
| `ends_at` | DateTimeField | nullable |
| `venue` | FK → Venue | nullable (SET_NULL) |
| `organization` | FK → Organization | nullable (SET_NULL); replaces the former `organizer` |
| `categories` | M2M → Category | blank allowed |
| `capacity` | PositiveIntegerField | nullable |
| `location` | PointField (geography, SRID 4326) | nullable; centroid for proximity |
| `status` | CharField(20) | lifecycle: `draft` / `published` / `cancelled` / `archived`; default `published`; indexed |
| `event_type` | CharField(20) | `meetup` / `conference` / `workshop` / `social` / `other`; default `other`; indexed |
| `attendance_mode` | CharField(20) | `physical` / `online` / `hybrid`; default `physical`; indexed. **Online excluded from proximity.** |
| `published_at` | DateTimeField | nullable; stamped by the publish action |
| `cancelled_at` | DateTimeField | nullable; stamped by the cancel action |
| `original_url` | URLField | blank; the URL the event was first seen at (provenance) |
| `original_platform` | CharField(80) | blank; the platform it came from (e.g. `meetup`) |
| `source` | FK → EventSource | nullable (SET_NULL); where this event was extracted from |
| `promoted_from` | FK → EventObservation | nullable (SET_NULL); the observation this event was promoted from |
| `created_by` | FK → User | nullable (SET_NULL); the owner |
| `owner_group` | FK → auth.Group | nullable (SET_NULL); co-owners |
| `created_at` | DateTimeField | auto |
| `updated_at` | DateTimeField | auto |

New events default to **published / physical / other** with null provenance, so the existing
hand-curated catalog stays public and every pre-existing row keeps working. The API accepts
`latitude`/`longitude` (write-only) and stores them as `location`; if a `venue` with a
location is set and no coords are given, the event copies the venue's location. A GiST
spatial index on `location` is created automatically by the PostGIS backend. An index on
`(status, starts_at)` backs the public "published events, soonest first" listing.

## Venue

A physical place where events happen.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | BigAutoField | PK |
| `name` | CharField(200) | |
| `address` | CharField(255) | blank |
| `city` | CharField(100) | free text (used by `?city=` exact filter) |
| `location` | PointField (geography, SRID 4326) | nullable |
| `capacity` | PositiveIntegerField | nullable |

## Organization

An entity that owns event sources and the canonical events extracted from them. (Renamed
from `Organizer`; the FK column on `Event` was renamed `organizer` → `organization`, not
dropped/recreated.)

| Field | Type | Notes |
| --- | --- | --- |
| `id` | BigAutoField | PK |
| `name` | CharField(200) | |
| `slug` | SlugField(220) | unique; auto-generated from `name` in `save()` (mirrors `Category`) |
| `description` | TextField | blank |
| `website` | URLField | blank |
| `owner` | FK → User | nullable (SET_NULL); related name `organizations` |
| `is_active` | BooleanField | default true; inactive orgs are hidden from the public API and their sources stop being due |

## Category

A tag/group for events (e.g. "Music", "Tech").

| Field | Type | Notes |
| --- | --- | --- |
| `id` | BigAutoField | PK |
| `name` | CharField(80) | unique |
| `slug` | SlugField(80) | unique; auto-generated from `name` |

## EventSource

A URL owned by an organization that the external extractor crawls. Only approved, active
sources are eligible for extraction ("due").

| Field | Type | Notes |
| --- | --- | --- |
| `id` | BigAutoField | PK |
| `organization` | FK → Organization | CASCADE; related name `sources` |
| `url` | URLField | unique per organization (`UniqueConstraint(fields=["organization","url"])`) |
| `platform` | CharField(80) | blank; e.g. `meetup` / `eventbrite` / `homepage` (free text) |
| `is_approved` | BooleanField | default false; an admin must approve before extraction |
| `is_active` | BooleanField | default true; soft pause for an approved source |
| `fetch_interval_minutes` | PositiveIntegerField | default 60; how often to revisit |
| `last_fetched_at` | DateTimeField | nullable; stamped when a run reports |
| `next_due_at` | DateTimeField | nullable; stamped when a run reports (`last_fetched_at + fetch_interval_minutes`) |
| `created_by` | FK → User | nullable (SET_NULL) |
| `created_at` | DateTimeField | auto |
| `updated_at` | DateTimeField | auto |

A source is **due** when `is_approved AND is_active AND (next_due_at IS NULL OR next_due_at
<= now)` — exposed via `EventSource.due()` and the `GET /api/ingestion/sources/due/` work
queue. An index on `(is_approved, is_active, next_due_at)` backs that query.

## IngestionRun

One extraction pass over a source, reported by the external extractor.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | BigAutoField | PK |
| `source` | FK → EventSource | CASCADE; related name `runs` |
| `started_at` | DateTimeField | when the run began (defaults to now on report) |
| `finished_at` | DateTimeField | nullable; set when the run succeeds/fails |
| `status` | CharField(20) | `pending` / `running` / `succeeded` / `failed`; default `pending`; indexed |
| `events_found` | PositiveIntegerField | default 0; reported by the extractor |
| `events_promoted` | PositiveIntegerField | default 0; bumped by the admin promote action |
| `error_message` | TextField | blank; set on failure |
| `reported_by` | FK → User | nullable (SET_NULL); the calling service account |
| `created_at` | DateTimeField | auto |

An index on `(source, status)` backs run listings. Finishing a run (succeeded/failed) also
stamps its source's `last_fetched_at` / `next_due_at` schedule.

## EventObservation

An **untrusted** extracted event observation. Observations never mutate a canonical `Event`
directly; an operator reviews, optionally corrects, and **promotes** an accepted observation
into a canonical event (linked back here only via `Event.promoted_from` — the single source
of truth for the link).

| Field | Type | Notes |
| --- | --- | --- |
| `id` | BigAutoField | PK |
| `source` | FK → EventSource | CASCADE; related name `observations` |
| `run` | FK → IngestionRun | nullable (SET_NULL); set when reported inside a run |
| `status` | CharField(20) | `pending` / `accepted` / `rejected` / `promoted`; default `pending`; indexed |
| `raw_payload` | JSONField | default `{}`; the full extractor payload, kept for provenance/debug |
| `title` | CharField(200) | |
| `description` | TextField | blank |
| `starts_at` | DateTimeField | |
| `ends_at` | DateTimeField | nullable |
| `url` | URLField | blank; observed `original_url` |
| `platform` | CharField(80) | blank; observed `original_platform` |
| `attendance_mode` | CharField(20) | same choices as `Event.attendance_mode` |
| `event_type` | CharField(20) | same choices as `Event.event_type` |
| `venue_name` / `venue_address` / `venue_city` | CharField | blank; the operator chooses the venue at promotion |
| `location` | PointField (geography, SRID 4326) | nullable; extractor-supplied lat/lon |
| `reviewed_by` | FK → User | nullable (SET_NULL) |
| `reviewed_at` | DateTimeField | nullable |
| `review_note` | TextField | blank |
| `created_at` | DateTimeField | auto |
| `updated_at` | DateTimeField | auto |

An index on `(source, status)` backs observation listings. There is **no forward FK to
`Event`** — promotion creates the `Event` and sets `Event.promoted_from`, then marks the
observation `promoted`.

## City (gazetteer)

A readable catalog of populated places for location-based discovery.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | BigAutoField | PK |
| `geoname_id` | PositiveBigIntegerField | unique, nullable; idempotency key for re-seeding |
| `name` | CharField(200) | proper name (may include accents) |
| `slug` | SlugField(220) | unique; used as `?near_city=` |
| `country` | CharField(100) | full name |
| `country_code` | CharField(2) | ISO 3166-1 alpha-2; indexed |
| `location` | PointField (geography, SRID 4326) | centroid |
| `default_radius_km` | PositiveIntegerField | default 15; suggested search radius |
| `population` | PositiveBigIntegerField | nullable; for ordering |
| `timezone` | CharField(50) | |
| `is_active` | BooleanField | default true; inactive cities are hidden |

Seeded with **2131 European cities ≥ 50 000 population** via `python manage.py
seed_cities`. See [Geospatial & cities](geospatial.md).

## User

Custom user (`accounts.User`, extends `AbstractUser`).

| Field | Type | Notes |
| --- | --- | --- |
| (AbstractUser fields) | — | username, password (hashed), email, is_staff, … |
| `is_service_account` | BooleanField | marks a non-interactive system client |
| `description` | TextField | blank |

Users carry Django **groups** and **permissions** uniformly, whether they are humans or
service accounts. See [Authentication](authentication.md).

## APIKey

A long-lived API key ("app secret") tied to a user.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | BigAutoField | PK |
| `user` | FK → User | CASCADE; related name `api_keys` |
| `name` | CharField(120) | label |
| `prefix` | CharField(16) | public, indexed; identifies the key |
| `hashed_key` | CharField(64) | sha256 hex; compared in constant time |
| `created` | DateTimeField | auto |
| `revoked` | BooleanField | revocation flag |
| `expires_at` | DateTimeField | nullable |

The raw key is shown **only once** at creation; only the sha256 hash is stored.