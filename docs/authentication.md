# Authentication & authorization

terminschleuder supports three authentication mechanisms, layered so that **humans,
browsers, and external/service clients all funnel into the same Django user** — and thus
the same group & permission machinery.

## Authentication mechanisms

### 1. JWT (short-lived tokens) — for external clients

[django-rest-framework-simplejwt]. Obtain an access + refresh pair with username/password,
then send the access token as a Bearer header.

```bash
# Obtain
curl -X POST http://localhost:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"my-bot","password":"<secret>"}'
# → {"refresh":"…", "access":"…"}

# Use
curl -H "Authorization: Bearer <access>" http://localhost:8000/api/events/
```

| Token | Lifetime | Notes |
| --- | --- | --- |
| access | 15 min | sent on every request as `Bearer` |
| refresh | 7 days | used with `POST /api/auth/token/refresh/` to get a new access token |

Both are signed with `SECRET_KEY`. **Rotate `SECRET_KEY` to invalidate all outstanding tokens.**

### 2. API keys ("app secrets") — long-lived

A long-lived key tied to a user, for clients that can't (or don't want to) deal with token
refresh. The **raw key is shown only once**, at creation; only a sha256 **hash** is stored.
Lookups hash the incoming key and compare in constant time (`hmac.compare_digest`).

```bash
# Create (authenticated, e.g. with a JWT)
curl -X POST http://localhost:8000/api/auth/api-keys/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"outer-client"}'
# → {…, "raw_key":"AbC123Def456…"}   ← store this; it won't be shown again

# Use
curl -H "Authorization: Api-Key <raw-key>" http://localhost:8000/api/events/
```

- Header: `Authorization: Api-Key <raw-key>`
- A key has a public `prefix` (first 12 chars) to narrow lookups, plus the stored hash.
- Keys can be **revoked** (`DELETE /api/auth/api-keys/<id>/` → sets `revoked=true`) and/or
  **expire** (`expires_at`). Revoked/expired keys fail authentication.
- `GET /api/auth/api-keys/` lists a user's keys but **never** returns the raw key.

### 3. Session — for the admin / browser

`POST /api/auth/login/` (username/password) starts a Django session and sets the cookie;
`POST /api/auth/logout/` ends it. This is what the Django admin and the browsable API use.

### Ordering and the 401-vs-403 detail

Authenticators are tried **in order: JWT → Session → API key**. JWT is first on purpose:
DRF 3.18 coerces an auth failure to **403** when no authenticator returns a
`WWW-Authenticate` value, but `JWTAuthentication` returns `"Bearer"`, so failed/missing
auth yields a proper **401** with the header. Sessions/API keys then continue to work
transparently.

## Users & service accounts

`accounts.User` extends `AbstractUser` with one flag:

- `is_service_account` — marks a **non-interactive system client**.

A service account is otherwise a **normal Django user**: it has a (generated) password
(its "app secret" for obtaining a JWT), belongs to **groups**, carries **permissions**, and
can hold **API keys**. The flag just signals "not a human logging in via a form."

### Provisioning a service account

```bash
docker compose exec web python manage.py create_service_account my-bot --group editors
```

The command prints a **one-time generated password**. Use it to obtain a JWT, or create an
API key from the resulting session/JWT. Put the account in a **group** that carries the
permissions it needs (see below).

## Permissions & groups

Authorization uses standard Django model permissions plus a custom object permission class.

### Event object permissions — `IsOwnerOrGroupOrReadOnly`

Applies to `/api/events/`:

| Action | Rule |
| --- | --- |
| `GET` (list / detail) | **Public** — the catalog. |
| `POST` (create) | Authenticated. **Human users** may create freely. **Service accounts** require `events.add_event`. The creator becomes `created_by` (owner). |
| `PATCH` / `PUT` | The **owner** (`created_by`), a member of the event's **`owner_group`**, **or** any holder of `events.change_event`. |
| `DELETE` | The **owner**, an **`owner_group`** member, **or** any holder of `events.delete_event`. |

### Granting permissions to a service account

Service accounts get permissions **via groups** (the recommended pattern) so they're
manageable in the admin:

| Want | Grant the group |
| --- | --- |
| create events | `events.add_event` |
| update any event | `events.change_event` |
| delete any event | `events.delete_event` |

```bash
# Example: give the "editors" group add+change on events (run in container, or via admin)
docker compose exec web python manage.py shell -c "
from django.contrib.auth.models import Group, Permission
g = Group.objects.get(name='editors')
g.permissions.add(*Permission.objects.filter(codename__in=['add_event','change_event']))
"
```

> **Django permission cache gotcha:** `user.has_perm()` caches results on the user instance.
> If you grant a permission to a user's group mid-process, **refetch the user** from the DB
> (`User.objects.get(pk=user.pk)`) before re-checking `has_perm`, or the cached negative
> result will persist.

### Venues / organizers / categories

These use DRF's default `IsAuthenticatedOrReadOnly` plus standard model permissions for
writes: a service account needs `events.add_venue` / `events.change_venue` / etc. to mutate
them; authenticated human users may create freely.

## Backoffice access (the `admin` app)

The human backoffice is a custom Django `AdminSite` (`terminschleuder_admin`, in the `admin`
app) mounted at `/`. It is **not** a fourth auth mechanism — it authenticates with the same
**session auth + custom `User`** described above, gated by `is_staff` (superusers qualify).

- Log in at `/login/` with a staff user (create one via `manage.py createsuperuser`).
  Anonymous `/` redirects to `/login/`. The old `/admin/` path redirects to `/`.
- The backoffice is where operators **create service accounts** (the app secret is generated
  and shown **once**, just like an API key) and **issue API keys** (the raw key shown **once**).
- Group & permission maintenance (which drives service-account powers and event
  `owner_group`) is done here, so the `has_perm`/group wiring above is configured through the
  backoffice, not just the shell.
- See [Admin backoffice](admin.md) for the per-task guide.

## Ownership model

```
Event.created_by   → User        (the owner)
Event.owner_group  → auth.Group  (optional co-owners)
```

- On `POST`, `created_by` is set to the authenticated user (read-only field).
- `owner_group_id` is an optional write field: members of that group gain edit/delete rights
  on the event without holding the global model permission.
- The owner and group membership are checked at the **object** level in
  `IsOwnerOrGroupOrReadOnly.has_object_permission`.

## Security notes

- API keys: **hashed at rest** (sha256), constant-time compared, revocable, expirable. The
  raw key is returned exactly once.
- JWT: signed with `SECRET_KEY`; keep it strong and secret in production. Rotating it
  invalidates all outstanding tokens.
- Never commit `.env` (gitignored); set `SECRET_KEY`, `DEBUG=False`, and real
  `ALLOWED_HOSTS` for production.
- `register/`, `token/`, `token/refresh/`, and `login/` are public; everything else that
  mutates state requires authentication.