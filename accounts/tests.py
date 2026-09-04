import io

from django.contrib.auth import get_user_model
from django.core.management import call_command

User = get_user_model()


def test_register_creates_user_with_hashed_password(db, api_client):
    payload = {
        "username": "bob",
        "email": "bob@example.com",
        "password": "supersecret123",
    }
    response = api_client.post("/api/auth/register/", payload, format="json")
    assert response.status_code == 201
    assert response.data["username"] == "bob"
    user = User.objects.get(username="bob")
    assert user.check_password("supersecret123")
    assert user.email == "bob@example.com"
    assert user.is_service_account is False


def test_me_requires_authentication(db, api_client):
    response = api_client.get("/api/auth/me/")
    assert response.status_code in (401, 403)


def test_me_returns_current_user(db, authed_client):
    response = authed_client.get("/api/auth/me/")
    assert response.status_code == 200
    assert response.data["username"] == "alice"


# --- JWT ----------------------------------------------------------------------


def test_jwt_token_endpoint_issues_access_and_refresh(db, api_client, user):
    response = api_client.post(
        "/api/auth/token/",
        {"username": "alice", "password": "password123"},
        format="json",
    )
    assert response.status_code == 200
    assert "access" in response.data
    assert "refresh" in response.data

    # The access token authenticates a request.
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    me = api_client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data["username"] == "alice"
    # User serializer exposes authorization scope.
    assert "groups" in me.data
    assert "permissions" in me.data


def test_jwt_with_invalid_credentials_fails(db, api_client, user):
    response = api_client.post(
        "/api/auth/token/",
        {"username": "alice", "password": "wrong"},
        format="json",
    )
    assert response.status_code == 401


# --- API keys -----------------------------------------------------------------


def test_create_api_key_returns_raw_once(db, authed_client):
    response = authed_client.post(
        "/api/auth/api-keys/", {"name": "ci-key"}, format="json"
    )
    assert response.status_code == 201
    assert "key" in response.data
    raw_key = response.data["key"]
    assert raw_key  # non-empty

    # Listing never exposes the raw key.
    listed = authed_client.get("/api/auth/api-keys/", format="json")
    assert listed.status_code == 200
    items = listed.data["results"] if "results" in listed.data else listed.data
    assert len(items) == 1
    assert "key" not in items[0]
    assert items[0]["prefix"]


def test_api_key_authenticates_requests(db, api_client, authed_client):
    created = authed_client.post(
        "/api/auth/api-keys/", {"name": "outer-client"}, format="json"
    )
    raw_key = created.data["key"]

    # A fresh, otherwise-unauthenticated client using the API key is alice.
    api_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw_key}")
    me = api_client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data["username"] == "alice"


def test_revoked_api_key_is_rejected(db, api_client, authed_client):
    created = authed_client.post(
        "/api/auth/api-keys/", {"name": "to-revoke"}, format="json"
    )
    key_id = created.data["id"]
    raw_key = created.data["key"]

    authed_client.delete(f"/api/auth/api-keys/{key_id}/")
    api_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw_key}")
    assert api_client.get("/api/auth/me/").status_code == 401


def test_invalid_api_key_rejected(db, api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Api-Key not-a-real-key")
    assert api_client.get("/api/auth/me/").status_code == 401


# --- Service accounts ---------------------------------------------------------


def test_create_service_account_command(db):
    out = {}
    call_command("create_service_account", "ci-bot", group="editors", stdout=io.StringIO())
    bot = User.objects.get(username="ci-bot")
    assert bot.is_service_account is True
    assert bot.groups.filter(name="editors").exists()


def test_service_account_can_obtain_jwt(db, api_client):
    buf = io.StringIO()
    call_command("create_service_account", "svc1", stdout=buf)
    secret = buf.getvalue().strip().splitlines()[-1]
    response = api_client.post(
        "/api/auth/token/",
        {"username": "svc1", "password": secret},
        format="json",
    )
    assert response.status_code == 200
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    me = api_client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data["is_service_account"] is True


# --- Bootstrap (fresh-volume production provisioning) -------------------------


def _set_bootstrap_env(monkeypatch, *, password="first-boot-operator-2026"):
    """Set the DJANGO_SUPERUSER_* env vars bootstrap reads (clearing any
    leftovers so tests are independent of the host environment)."""
    for var in (
        "DJANGO_SUPERUSER_USERNAME",
        "DJANGO_SUPERUSER_PASSWORD",
        "DJANGO_SUPERUSER_EMAIL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DJANGO_SUPERUSER_USERNAME", "admin")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", password)
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "admin@example.com")


def _clear_bootstrap_env(monkeypatch):
    for var in (
        "DJANGO_SUPERUSER_USERNAME",
        "DJANGO_SUPERUSER_PASSWORD",
        "DJANGO_SUPERUSER_EMAIL",
    ):
        monkeypatch.delenv(var, raising=False)


def _ingestion_codenames():
    from django.contrib.auth.models import Group
    from events.provisioning import INGESTION_CODENAMES, INGESTION_GROUP_NAME

    group = Group.objects.get(name=INGESTION_GROUP_NAME)
    return set(group.permissions.values_list("codename", flat=True)), set(INGESTION_CODENAMES)


def test_bootstrap_creates_superuser_group_and_cities(db, monkeypatch):
    from locations.models import City

    _set_bootstrap_env(monkeypatch)
    call_command("bootstrap", stdout=io.StringIO())

    admin = User.objects.get(username="admin")
    assert admin.is_superuser is True
    assert admin.is_staff is True
    assert admin.check_password("first-boot-operator-2026")

    codenames, expected = _ingestion_codenames()
    assert codenames == expected

    assert City.objects.count() > 0


def test_bootstrap_is_idempotent(db, monkeypatch):
    from locations.models import City

    _set_bootstrap_env(monkeypatch)
    call_command("bootstrap", stdout=io.StringIO())
    call_command("bootstrap", stdout=io.StringIO())

    assert User.objects.filter(username="admin").count() == 1
    assert User.objects.get(username="admin").check_password("first-boot-operator-2026")

    codenames, expected = _ingestion_codenames()
    assert codenames == expected
    city_count = City.objects.count()
    assert city_count > 0
    # seed_cities is an upsert keyed on geoname_id: re-running adds nothing.
    call_command("bootstrap", stdout=io.StringIO())
    assert City.objects.count() == city_count


def test_bootstrap_never_overwrites_existing_superuser(db, monkeypatch):
    _set_bootstrap_env(monkeypatch)
    User.objects.create_superuser(
        "admin", "admin@example.com", "original-password-2026"
    )
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "env-says-something-else-2026")

    call_command("bootstrap", stdout=io.StringIO())

    admin = User.objects.get(username="admin")
    assert admin.check_password("original-password-2026")
    assert not admin.check_password("env-says-something-else-2026")


def test_bootstrap_without_env_skips_superuser_but_provisions_rest(db, monkeypatch):
    from django.contrib.auth.models import Group
    from locations.models import City

    from events.provisioning import INGESTION_GROUP_NAME

    _clear_bootstrap_env(monkeypatch)
    out = io.StringIO()
    call_command("bootstrap", stdout=out)

    assert User.objects.filter(is_superuser=True).count() == 0
    assert "DJANGO_SUPERUSER_USERNAME not set" in out.getvalue()
    assert Group.objects.filter(name=INGESTION_GROUP_NAME).exists()
    assert City.objects.count() > 0


def test_bootstrap_seeds_no_demo_data(db, monkeypatch):
    from events.models import Event

    _set_bootstrap_env(monkeypatch)
    call_command("bootstrap", stdout=io.StringIO())

    assert Event.objects.count() == 0
    assert not User.objects.filter(username="demo").exists()


def test_create_service_account_ingestion_group_carries_permissions(db):
    from events.provisioning import INGESTION_CODENAMES

    call_command("create_service_account", "extractor", group="ingestion", stdout=io.StringIO())
    bot = User.objects.get(username="extractor")
    assert bot.is_service_account is True
    assert set(
        bot.groups.get(name="ingestion").permissions.values_list("codename", flat=True)
    ) == set(INGESTION_CODENAMES)