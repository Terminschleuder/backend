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
from events.admin import EventObservationAdmin, VenueAdmin
from events.models import (
    Event,
    EventObservation,
    EventSource,
    IngestionRun,
    Organization,
    Venue,
)
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


# --- Ingestion: observation promotion & event lifecycle ---------------------


def _org_source_run():
    """A provenance triple: org owning an approved source with one run."""
    from django.utils import timezone

    org = Organization.objects.create(name="Berlin Tech Meetups")
    source = EventSource.objects.create(
        organization=org, url="https://example.com/m.ics",
        platform="homepage", is_approved=True,
    )
    run = IngestionRun.objects.create(
        source=source, started_at=timezone.now(), status=IngestionRun.Status.RUNNING
    )
    return org, source, run


def _pending_observation(source, run):
    from datetime import timedelta

    from django.utils import timezone

    return EventObservation.objects.create(
        source=source, run=run,
        title="Rust Meetup",
        starts_at=timezone.now() + timedelta(days=3),
        url="https://example.com/rust", platform="meetup",
        attendance_mode=Event.AttendanceMode.PHYSICAL,
        event_type=Event.EventType.MEETUP,
        venue_name="Factory Berlin", venue_address="Rheinsberger Str. 76",
        venue_city="Berlin", location="POINT(13.405 52.52)",
    )


@pytest.mark.django_db
def test_promote_observation_creates_draft_event_with_provenance(admin_user):
    org, source, run = _org_source_run()
    obs = _pending_observation(source, run)

    EventObservationAdmin(EventObservation, None).promote(
        _post_request(admin_user), EventObservation.objects.filter(pk=obs.pk)
    )

    obs.refresh_from_db()
    assert obs.status == EventObservation.Status.PROMOTED
    assert obs.reviewed_by_id == admin_user.id
    assert obs.reviewed_at is not None

    event = Event.objects.get(title="Rust Meetup")
    # Promoted events enter as draft (decision #3: draft → publish).
    assert event.status == Event.Status.DRAFT
    # Provenance is fully linked.
    assert event.promoted_from_id == obs.id
    assert event.source_id == source.id
    assert event.organization_id == org.id
    # original_url / original_platform copied from the observation.
    assert event.original_url == "https://example.com/rust"
    assert event.original_platform == "meetup"
    assert event.event_type == Event.EventType.MEETUP
    assert event.created_by_id == admin_user.id
    # Venue auto-created from the observation's venue_name/address/city.
    assert event.venue.name == "Factory Berlin"
    assert event.venue.city == "Berlin"

    # The run's promoted counter is bumped.
    run.refresh_from_db()
    assert run.events_promoted == 1


@pytest.mark.django_db
def test_promote_requires_add_event_perm(admin_user):
    """Without add_event, the promote action is a no-op with an error message."""
    from django.contrib.auth.models import Permission

    admin_user.is_superuser = False
    admin_user.is_staff = True
    admin_user.save()
    # Strip add_event by ensuring it's not granted (staff without it).
    admin_user.user_permissions.remove(
        Permission.objects.filter(content_type__app_label="events", codename="add_event").first()
    )

    org, source, run = _org_source_run()
    obs = _pending_observation(source, run)
    EventObservationAdmin(EventObservation, None).promote(
        _post_request(admin_user), EventObservation.objects.filter(pk=obs.pk)
    )
    assert not Event.objects.filter(title="Rust Meetup").exists()
    assert EventObservation.objects.get(pk=obs.pk).status == EventObservation.Status.PENDING


@pytest.mark.django_db
def test_publish_action_sets_published_and_published_at(admin_user):
    from django.utils import timezone

    org, source, run = _org_source_run()
    obs = _pending_observation(source, run)
    EventObservationAdmin(EventObservation, None).promote(
        _post_request(admin_user), EventObservation.objects.filter(pk=obs.pk)
    )
    event = Event.objects.get(title="Rust Meetup")

    EventAdminEnhanced(Event, None).publish(
        _post_request(admin_user), Event.objects.filter(pk=event.pk)
    )
    event.refresh_from_db()
    assert event.status == Event.Status.PUBLISHED
    assert event.published_at is not None


@pytest.mark.django_db
def test_promoted_then_published_event_visible_with_nested_provenance(
    admin_user, client
):
    """End-to-end: promote → publish → the public API exposes the event with its
    nested provenance (source + promoted_from)."""
    org, source, run = _org_source_run()
    obs = _pending_observation(source, run)
    EventObservationAdmin(EventObservation, None).promote(
        _post_request(admin_user), EventObservation.objects.filter(pk=obs.pk)
    )
    event = Event.objects.get(title="Rust Meetup")
    EventAdminEnhanced(Event, None).publish(
        _post_request(admin_user), Event.objects.filter(pk=event.pk)
    )

    # Anon can now retrieve the (published) promoted event.
    response = client.get(f"/api/events/{event.id}/", format="json")
    assert response.status_code == 200
    assert response.data["status"] == Event.Status.PUBLISHED
    assert response.data["original_url"] == "https://example.com/rust"
    # Provenance is nested and read-only.
    assert response.data["source"]["url"] == source.url
    assert response.data["promoted_from"]["title"] == "Rust Meetup"
    assert response.data["promoted_from"]["status"] == EventObservation.Status.PROMOTED


@pytest.mark.django_db
def test_event_admin_lifecycle_actions():
    from django.utils import timezone

    event = Event.objects.create(title="E", starts_at=timezone.now())
    qs = Event.objects.filter(pk=event.pk)
    req = _post_request(_staff_user())

    EventAdminEnhanced(Event, None).cancel(req, qs)
    event.refresh_from_db()
    assert event.status == Event.Status.CANCELLED
    assert event.cancelled_at is not None

    EventAdminEnhanced(Event, None).archive(req, qs)
    event.refresh_from_db()
    assert event.status == Event.Status.ARCHIVED

    EventAdminEnhanced(Event, None).revert_to_draft(req, qs)
    event.refresh_from_db()
    assert event.status == Event.Status.DRAFT


def _staff_user():
    """A minimal staff user (with change_event) for the admin actions."""
    from django.contrib.auth.models import Permission

    user = User.objects.create_user(username="operator", password="x")
    user.is_staff = True
    user.save()
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="events", codename="change_event")
    )
    return User.objects.get(pk=user.pk)  # refetch (perm cache gotcha)