import hashlib

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.urls import reverse

from accounts.models import APIKey, User
from admin.admin import APIKeyAdmin, CityAdminEnhanced, ServiceAccountAdmin
from admin.models import ServiceAccount
from locations.models import City


def _post_request(user):
    """A RequestFactory POST with a user and a messages store attached."""
    request = RequestFactory().post("/")
    request.user = user
    setattr(request, "session", {})
    setattr(request, "_messages", FallbackStorage(request))
    return request


@pytest.mark.django_db
def test_service_account_proxy_queryset_filters_to_service_accounts():
    User.objects.create_user(username="alice", password="x")
    bot = User.objects.create_user(username="bot", password="x")
    bot.is_service_account = True
    bot.save(update_fields=["is_service_account"])
    assert list(ServiceAccount.objects.values_list("username", flat=True)) == ["bot"]


@pytest.mark.django_db
def test_service_account_admin_save_generates_secret(admin_user):
    request = RequestFactory().get("/backoffice/serviceaccount/add/")
    request.user = admin_user
    sa = ServiceAccount(username="new-bot", is_active=True)

    ServiceAccountAdmin(ServiceAccount, None).save_model(request, sa, form=None, change=False)

    sa.refresh_from_db()
    assert sa.is_service_account is True
    assert sa.is_staff is False
    assert sa.has_usable_password()
    assert getattr(request, "_generated_secret", None)


@pytest.mark.django_db
def test_apikey_admin_save_generates_raw_key_once(admin_user):
    request = _post_request(admin_user)
    key = APIKey(user=admin_user, name="outer")

    APIKeyAdmin(APIKey, None).save_model(request, key, form=None, change=False)

    key.refresh_from_db()
    raw = getattr(request, "_generated_secret", None)
    assert raw
    assert key.prefix
    assert raw.startswith(key.prefix)
    assert key.hashed_key == hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.mark.django_db
def test_apikey_list_never_exposes_raw_key(admin_client, admin_user):
    _, raw = APIKey.create(admin_user, name="outer-client")

    resp = admin_client.get(reverse("admin:accounts_apikey_changelist"))

    assert resp.status_code == 200
    assert raw not in resp.content.decode()


@pytest.mark.django_db
def test_root_redirects_anon_to_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login/" in resp.url


@pytest.mark.django_db
def test_root_is_admin_index_for_staff(admin_client):
    resp = admin_client.get("/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_api_routes_not_shadowed_by_root_admin(client):
    assert client.get("/api/events/").status_code == 200


@pytest.mark.django_db
def test_city_toggle_active_action_flips(admin_user):
    city = City.objects.create(
        name="Testville", country_code="DE", location="POINT(13 52)", slug="testville-de"
    )
    assert city.is_active is True

    CityAdminEnhanced(City, None).toggle_active(
        _post_request(admin_user), City.objects.filter(pk=city.pk)
    )

    city.refresh_from_db()
    assert city.is_active is False