import io
import subprocess
import sys

import jwt
from django.conf import settings
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


def test_jwt_signing_key_defaults_to_secret_key(settings):
    """Without DJANGO_JWT_SIGNING_KEY the tokens are signed with SECRET_KEY."""
    assert settings.SIMPLE_JWT["SIGNING_KEY"] == settings.SECRET_KEY


def test_jwt_signing_key_env_var_overrides_secret_key():
    """DJANGO_JWT_SIGNING_KEY, when set, replaces SECRET_KEY for JWT signing.

    Settings are read once at import time (simplejwt caches its config at
    first use), so the override is exercised in a fresh interpreter: with the
    env var set, importing config.settings must yield it as the signing key.
    """
    separate_key = "separate-jwt-signing-key"
    code = (
        "import os; "
        f"os.environ['DJANGO_JWT_SIGNING_KEY'] = {separate_key!r}; "
        "from config import settings as project_settings; "
        "assert project_settings.SIMPLE_JWT['SIGNING_KEY'] == "
        f"{separate_key!r}, project_settings.SIMPLE_JWT['SIGNING_KEY']; "
        "assert project_settings.SIMPLE_JWT['SIGNING_KEY'] != "
        "project_settings.SECRET_KEY"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=settings.BASE_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_jwt_access_token_is_signed_with_configured_signing_key(db, api_client, user):
    """The endpoint actually signs tokens with settings.SIMPLE_JWT['SIGNING_KEY']."""
    response = api_client.post(
        "/api/auth/token/",
        {"username": "alice", "password": "password123"},
        format="json",
    )
    assert response.status_code == 200

    claims = jwt.decode(
        response.data["access"],
        settings.SIMPLE_JWT["SIGNING_KEY"],
        algorithms=["HS256"],
    )
    assert int(claims["user_id"]) == user.pk


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