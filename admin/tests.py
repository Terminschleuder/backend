import hashlib

import pytest
from django.contrib.gis.admin import GISModelAdmin
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.urls import reverse

from accounts.models import APIKey, User
from admin.admin import (
    APIKeyAdmin,
    CityAdminEnhanced,
    EventAdminEnhanced,
    ServiceAccountAdmin,
)
from admin.models import ServiceAccount
from events.admin import VenueAdmin
from events.models import Event, Venue
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


@pytest.mark.django_db
def test_city_admin_uses_gis_model_admin_for_map_widget():
    # GISModelAdmin provides the PostGIS map widget for the `location` PointField.
    assert issubclass(CityAdminEnhanced, GISModelAdmin)


@pytest.mark.django_db
def test_city_admin_list_and_readonly_expose_lat_lon():
    assert "latitude" in CityAdminEnhanced.list_display
    assert "longitude" in CityAdminEnhanced.list_display
    assert "latitude" in CityAdminEnhanced.readonly_fields
    assert "longitude" in CityAdminEnhanced.readonly_fields


@pytest.mark.django_db
def test_city_admin_lat_lon_methods_read_location_point():
    city = City.objects.create(
        name="Berlin", country_code="DE", location="POINT(13.405 52.52)",
        slug="berlin-de",
    )
    admin_instance = CityAdminEnhanced(City, None)
    # location.x = longitude, location.y = latitude; rounded to 5 decimals.
    assert admin_instance.latitude(city) == round(52.52, 5)
    assert admin_instance.longitude(city) == round(13.405, 5)


@pytest.mark.django_db
def test_city_admin_lat_lon_methods_handle_missing_location():
    # `location` is NOT NULL at the DB, so an unsaved in-memory instance is the
    # only way to exercise the None guard (which mirrors the serializer's).
    city = City(name="Nowhere", country_code="DE", slug="nowhere-de")
    admin_instance = CityAdminEnhanced(City, None)
    assert admin_instance.latitude(city) is None
    assert admin_instance.longitude(city) is None


# --- Venues & events: same GIS map widget + lat/lon columns -----------------


@pytest.mark.django_db
def test_venue_admin_uses_gis_model_admin_and_exposes_lat_lon():
    assert issubclass(VenueAdmin, GISModelAdmin)
    for col in ("latitude", "longitude"):
        assert col in VenueAdmin.list_display
        assert col in VenueAdmin.readonly_fields


@pytest.mark.django_db
def test_venue_admin_lat_lon_methods_read_location_point():
    venue = Venue.objects.create(name="Hacklab", city="Berlin", location="POINT(13.405 52.52)")
    admin_instance = VenueAdmin(Venue, None)
    assert admin_instance.latitude(venue) == round(52.52, 5)
    assert admin_instance.longitude(venue) == round(13.405, 5)


@pytest.mark.django_db
def test_venue_admin_lat_lon_methods_handle_null_location():
    # Venue.location is nullable, so a saved row with no point exercises the guard.
    venue = Venue.objects.create(name="Nowhere Hall")
    admin_instance = VenueAdmin(Venue, None)
    assert admin_instance.latitude(venue) is None
    assert admin_instance.longitude(venue) is None


@pytest.mark.django_db
def test_event_admin_uses_gis_model_admin_and_exposes_lat_lon():
    # EventAdminEnhanced is the registered class; it inherits EventAdmin's
    # GISModelAdmin base and lat/lon columns, and must keep lat/lon in
    # readonly_fields (it extends rather than shadows the parent).
    assert issubclass(EventAdminEnhanced, GISModelAdmin)
    for col in ("latitude", "longitude"):
        assert col in EventAdminEnhanced.list_display
        assert col in EventAdminEnhanced.readonly_fields


@pytest.mark.django_db
def test_event_admin_lat_lon_methods_read_location_point():
    from django.utils import timezone

    event = Event.objects.create(
        title="Berlin Meetup", starts_at=timezone.now(), location="POINT(13.405 52.52)"
    )
    admin_instance = EventAdminEnhanced(Event, None)
    assert admin_instance.latitude(event) == round(52.52, 5)
    assert admin_instance.longitude(event) == round(13.405, 5)


@pytest.mark.django_db
def test_event_admin_lat_lon_methods_handle_null_location():
    from django.utils import timezone

    event = Event.objects.create(title="Unlocated", starts_at=timezone.now())
    admin_instance = EventAdminEnhanced(Event, None)
    assert admin_instance.latitude(event) is None
    assert admin_instance.longitude(event) is None