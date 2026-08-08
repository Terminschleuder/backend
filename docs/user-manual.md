# User manual

A use-case-driven guide for the people who **work with** terminschleuder day to day:

- the **operator** — a staff user who runs the backoffice, curates the catalog, and reviews
  what the extractor brings in; and
- the **extractor integrator** — the person wiring up the external extraction system that
  crawls sources and submits events.

It describes *how to get a job done*, not the field-by-field reference (that's in
[API reference](api-reference.md) and [Data model](data-model.md)). Read the
[Architecture](architecture.md) overview first if you want the big picture.

> **The one idea to hold onto:** there are two ways an event enters the system.
>
> 1. **Hand-curated** — an operator creates it directly in the backoffice (or via the
>    events API). It starts life **published**.
> 2. **Ingested** — the extractor submits an **untrusted observation**; an operator reviews
>    it and **promotes** the good ones into a **draft** canonical event, then **publishes**
>    it.
>
> Observations can never touch a canonical event directly. That trust boundary is the whole
> point of the ingestion pipeline.

---

## Before you begin

You need a running stack and a way in.

```bash
./start.sh                                       # or: docker compose up --build
docker compose exec web python manage.py createsuperuser   # first staff login
docker compose exec web python manage.py seed_cities      # powers ?near_city= (one-time)
```

**Want a fully populated catalog to explore?** One command seeds coherent demo data across
every area — organizations, venues, categories, event sources (approved/disabled/unapproved),
ingestion runs (succeeded/failed/running), observations (pending/accepted/rejected/promoted),
and events with lifecycle + provenance variety, plus a `demo` / `demo12345` staff user and
the `ingestion` group:

```bash
docker compose exec web python manage.py seed_demo   # idempotent & non-destructive
```

Re-running it never duplicates or overwrites anything you've since edited, so it's safe to
run alongside your own data.

Then open **http://localhost:8000/** in a browser. Anonymous visitors are sent to `/login/`;
sign in with the superuser you just made (or the `demo` user from `seed_demo`). Everything
operator-facing happens in this backoffice (a custom Django admin mounted at the root). The
old `/admin/` path redirects to `/` for bookmarks.

All `manage.py` and `pytest` commands run **inside the container** — never on the host (no
GIS libraries there). See [Architecture → no host GIS](architecture.md).

---

## Use case 1 — Hand-curate an event into the public catalog

You already know the event and want it listed. No extractor involved.

1. **Create the organization** (if it doesn't exist yet) — *Organizations → Add*:
   fill in `name` (the `slug` fills itself), `description`, `website`, and `owner`.
   Leave `is_active` on. An event needs an organization to belong to.
2. **Create a venue** (optional) — *Venues → Add*: `name`, `address`, `city`, `capacity`.
   Drop the pin on the PostGIS map widget, or type `latitude`/`longitude`. A venue with a
   location means its events can be found by proximity search.
3. **Create categories** (optional) — *Categories → Add*: just a `name` (e.g. "Tech",
   "Music"); the `slug` is generated.
4. **Create the event** — *Events → Add*: `title`, `starts_at`, pick `venue` and
   `organization` (both autocomplete), tick `categories`. Set `attendance_mode`
   (`physical` / `online` / `hybrid`) and `event_type` (`meetup` / `conference` / …).
   Drop the pin for `location` (or it copies the venue's). `created_by` defaults to you.

That's it — the event is **published by default**, so it's immediately visible on the public
API:

```bash
curl http://localhost:8000/api/events/?organization_slug=<the-slug>
```

The public list shows **only `published`** events. (You, as a logged-in operator, see the
full lifecycle in the backoffice regardless.)

> Tip: if you'd rather drive this from a script, the same fields work on
> `POST /api/events/` — see [API reference](api-reference.md). Hand-curated events have
> `source` and `promoted_from` = `null`; that's how you tell them apart from promoted ones.

---

## Use case 2 — Set up the extraction pipeline (one-time)

You want the external extractor to start feeding events. Three things to provision, once.

### 2a. Create the `ingestion` group

The extractor is a service account whose powers come entirely from a Django group. Make the
group once and give it exactly the ingestion permissions (nothing more — the extractor must
not be able to promote or publish):

```bash
docker compose exec web python manage.py shell -c "
from django.contrib.auth.models import Group, Permission
g, _ = Group.objects.get_or_create(name='ingestion')
g.permissions.add(*Permission.objects.filter(
    content_type__app_label='events',
    codename__in=['view_eventsource','add_ingestionrun','change_ingestionrun',
                  'view_ingestionrun','add_eventobservation','view_eventobservation']))
print('ingestion group ready')
"
```

(You can do the same in the backoffice under *Groups* if you prefer.)

### 2b. Provision the extractor account + API key

```bash
docker compose exec web python manage.py create_service_account extractor \
  --group ingestion --description "External extraction system"
```

The command prints a **one-time app secret** — but for a long-lived extractor you'll want an
**API key** instead. In the backoffice:

1. *Service accounts →* open the new `extractor` account (it's a proxy list of service
   users). You can regenerate its secret here later if needed.
2. Issue it an API key: sign in as an admin and `POST /api/auth/api-keys/` with the
   extractor as the owning user, **or** use the *API keys* backoffice section. The **raw key
   is shown once** — copy it; only a sha256 hash is stored.

Hand that raw key to the extractor integrator. They'll send it as
`Authorization: Api-Key <raw-key>`. See [Authentication → the ingestion group](authentication.md#the-ingestion-group).

### 2c. Register an organization's source and approve it

Nothing is extracted until an operator approves a source.

1. Make sure the organization exists (Use case 1, step 1).
2. *Event sources → Add*: pick the `organization`, paste the `url` to crawl, set
   `platform` (free text: `meetup`, `eventbrite`, `homepage`, …) and
   `fetch_interval_minutes` (default 60). `created_by` defaults to you.
3. Select the new source and run the **Approve** action. It's now eligible for extraction
   ("due").

A source is **due** when `is_approved AND is_active AND (next_due_at is null OR next_due_at
<= now)`. The first fetch happens as soon as the extractor polls. You can **Disable** a
source (pause without withdrawing approval) or **Revoke** approval at any time.

---

## Use case 3 — What the extractor does (and how to watch it)

This is the integrator's loop, plus how the operator observes it. All of these require the
extractor's API key (Use case 2).

**The loop, in curl:**

```bash
KEY=...   # the raw API key issued to the extractor account

# 1. Discover due work (approved + active + due; never-fetched first)
curl -s -H "Authorization: Api-Key $KEY" \
  http://localhost:8000/api/ingestion/sources/due/ | jq '.results[] | {id,url,platform}'

# 2. Report a run for a due source
RUN=$(curl -s -X POST http://localhost:8000/api/ingestion/runs/ \
  -H "Authorization: Api-Key $KEY" -H 'Content-Type: application/json' \
  -d '{"source": 5}' | jq -r .id)

# 3. Submit the events you found as untrusted observations (each → pending)
curl -s -X POST http://localhost:8000/api/ingestion/observations/ \
  -H "Authorization: Api-Key $KEY" -H 'Content-Type: application/json' \
  -d '{
    "source": 5, "run": '"$RUN"',
    "title": "Rust Meetup", "starts_at": "2026-09-10T19:00:00+02:00",
    "url": "https://example.com/rust", "platform": "meetup",
    "attendance_mode": "physical", "event_type": "meetup",
    "venue_name": "Factory Berlin", "venue_city": "Berlin",
    "latitude": 52.52, "longitude": 13.405,
    "raw_payload": {}
  }'

# 4. Finish the run — success stamps the source's next-due schedule
curl -s -X POST http://localhost:8000/api/ingestion/runs/$RUN/success/ \
  -H "Authorization: Api-Key $KEY" -H 'Content-Type: application/json' \
  -d '{"events_found": 3}'
```

**Rules the extractor must live by:**

- Every observation enters as `pending`. A `status` in the body is **ignored** — the
  extractor can never self-promote.
- Submit one at a time, or `POST /api/ingestion/observations/bulk/` with
  `{"observations": [...]}` (transactional, all-or-nothing).
- `latitude`/`longitude` are write-only and stored as the geography `location`.
- Finishing a run (`/success/` or `/failure/`) stamps the source's `last_fetched_at` and
  `next_due_at` (= now + `fetch_interval_minutes`), which is how it drops off the due list
  until the next interval.

**As the operator, you watch — you don't run — this loop**:

- *Ingestion runs* is **read-only**: inspect status, `events_found`, `events_promoted`, and
  `error_message`; filter by status or organization.
- *Event observations* is where submitted events pile up as `pending`, awaiting review (Use
  case 4).

---

## Use case 4 — Review observations and promote an event

The extractor has dropped off some `pending` observations. This is the operator's core
review job.

1. Open *Event observations*. Filter by `status=pending` (or by organization/source). The
   list shows `title`, `starts_at`, `source`, `attendance_mode`, `event_type`.
2. Open one to inspect the extracted fields, the `raw_payload` (the full extractor dump, kept
   for provenance/debugging), and the lat/lon.
3. Decide:
   - **Accept** — it's worth keeping but not ready to publish (e.g. you'll batch-promote
     later). Sets `accepted`, stamps you as `reviewed_by`.
   - **Reject** — junk or a duplicate. Sets `rejected`. (Only `pending` observations can be
     accepted/rejected.)
   - **Promote** — it's good; turn it into a real event. This is the key action.

### What "promote" does

For each selected non-promoted observation, it creates a **draft** `Event`:

- copies `title`, `description`, `starts_at`, `ends_at`, `attendance_mode`, `event_type`,
  and `location`;
- sets `organization` = the source's organization, `source` = the observation's
  `EventSource`, `promoted_from` = the observation, and copies `original_url` /
  `original_platform` from it;
- auto-creates (or reuses) a `Venue` from `venue_name` / `venue_address` / `venue_city` if
  present;
- marks the observation `promoted` (stamps `reviewed_by` / `reviewed_at`) and bumps its
  run's `events_promoted` counter;
- sets `status = draft` and `created_by` = you.

> Promote requires the `events.add_event` permission (a superuser has it). The extractor
> **cannot** promote — its `ingestion` group deliberately lacks `add_event`.

The new event is a **draft** — not yet public. Promote it in the next step.

---

## Use case 5 — Publish, cancel, archive (the event lifecycle)

A canonical event moves through `draft → published → (cancelled | archived)`, reversible to
`draft`. Drive it from the backoffice *or* the API.

**In the backoffice** — select events on the *Events* list and run an action:

| Action | Effect |
| --- | --- |
| **Publish** | `status=published`, stamps `published_at` → **now visible to the public** |
| **Cancel** | `status=cancelled`, stamps `cancelled_at` (drops out of the public list; signals "called off") |
| **Archive** | `status=archived` (drops out of the public list; retire it without deleting) |
| **Revert to draft** | `status=draft` (hides it from the public again) |

Only `published` events appear on the public API; `cancelled` and `archived` both leave the
public list (use cancel to flag a called-off event, archive to quietly retire one).

**From the API** (owner, `owner_group` member, or anyone with `events.change_event`):

```bash
curl -X POST http://localhost:8000/api/events/42/publish/   -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/api/events/42/cancel/
curl -X POST http://localhost:8000/api/events/42/archive/
curl -X POST http://localhost:8000/api/events/42/revert_to_draft/
```

So the **full ingested lifecycle** is: extractor submits `pending` observation → operator
**promotes** (draft event with provenance) → operator **publishes** (public). Verify a
promoted-and-published event is public and carries its provenance:

```bash
curl -s http://localhost:8000/api/events/42/ | jq '{status, original_url, original_platform,
  source: .source.url, promoted_from: .promoted_from}'
```

---

## Use case 6 — Take an organization or source offline

**Pause an organization** — *Organizations →* tick `is_active` off and save. Inactive orgs
vanish from the public `/api/organizations/` list **and** their sources stop being due, so
the extractor leaves them alone. Re-enable by ticking it back on.

**Pause one source** — *Event sources →* run **Disable** (keeps approval, but the source is
no longer due). Use **Revoke** to withdraw approval entirely (it won't be due even if
re-enabled). **Approve** re-enables an approved-and-disabled source.

**Kill an event quietly** — don't delete it (you'd lose provenance). **Archive** it instead:
it drops out of the default public list but stays in the backoffice with full history.

---

## Use case 7 — Manage users, groups, and API keys

- **Human users** (*Users*) — create staff users here; set `is_staff` to grant backoffice
  access and assign groups. Passwords are hashed via Django's forms.
- **Service / system accounts** (*Service accounts*, a pre-filtered list) — non-interactive
  clients like the extractor. Creating one generates an **app secret shown once**
  (`is_service_account` forced on, `is_staff` off). "Regenerate app secret" re-rolls it.
- **Groups** (*Groups*) — maintain Django groups & permissions. Groups drive event
  `owner_group` (co-ownership), service-account powers, and the `ingestion` group.
- **API keys** (*API keys*) — issue long-lived keys; the **raw key is shown once** (only the
  prefix + sha256 hash are stored). Revoke by setting `revoked` on. Raw keys are never
  listed.

> **Permission-cache gotcha:** if you grant a group permission *mid-session* and re-check
> `has_perm` on an already-loaded user, you'll see the stale negative result. Refetch the
> user (`User.objects.get(pk=…)`) — or just log in again — before re-checking.

---

## Use case 8 — Verify the public catalog

The public API is what your consumers see. Sanity-check it anon (no auth header):

```bash
# Only published events appear:
curl -s http://localhost:8000/api/events/ | jq '.results[] | {title, status}'

# Only active organizations appear (by slug):
curl -s http://localhost:8000/api/organizations/ | jq '.results[] | .name'

# An org's published events:
curl -s http://localhost:8000/api/organizations/<slug>/events/ | jq '.results[] | .title'

# Proximity search (online events are excluded even if they have a location):
curl -s 'http://localhost:8000/api/events/?lat=52.52&lon=13.405&radius_km=10' | jq '.results[] | .title'
```

Operators see the full lifecycle in the backoffice; an event owner can additionally
retrieve their own draft over the API (`GET /api/events/<id>/`) even though it's `404` for
anon.

---

## Common questions

**"I promoted an observation but it's not on the public API."**
Promote creates a **draft**. You still need to **Publish** it (Use case 5).

**"The extractor isn't picking up my source."**
Check the three due conditions: `is_approved` (run the *Approve* action), `is_active` (not
*Disabled*), and the organization's `is_active`. A newly approved source is due immediately
(`next_due_at` is null). After a run reports, it's due again at `next_due_at`.

**"A submitted observation has the wrong venue/coords."**
The observation is just a draft of the facts; you correct them at **promotion time** — the
operator chooses the venue and can fix the event afterward. The observation itself is kept
verbatim (including `raw_payload`) for provenance.

**"Should I delete a duplicate or bad event?"**
Prefer **archive** over delete — delete loses the provenance links (`source`,
`promoted_from`).

**"Can the extractor publish events directly?"**
No, by design. It can read due sources, report runs, and submit `pending` observations
only. Promotion and publishing are operator decisions. If you ever want an automated
promote-and-publish path, that's a deliberate policy change to grant `add_event` /
`change_event` to a service account — do it consciously, not by accident.

---

## Where to go next

- [API reference](api-reference.md) — every endpoint, param, and status code.
- [Data model](data-model.md) — fields, relationships, the ER diagram.
- [Authentication](authentication.md) — JWT, API keys, the `ingestion` group, ownership.
- [Admin backoffice](admin.md) — the backoffice's wiring for maintainers.
- [Geospatial & cities](geospatial.md) — proximity, `?near_city=`, the city gazetteer.
- [Architecture](architecture.md) — the system-of-record design and request lifecycles.