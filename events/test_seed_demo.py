"""Tests for the JSON-driven ``seed_demo`` management command.

The heavy count + idempotency assertions run with ``--no-hero`` so the suite
stays fast (Pillow renders 400 banners on a real seed, not in tests). A separate
case exercises the real hero-image path on a single event.
"""

from io import BytesIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from events.models import Event, EventObservation, EventSource, Organization, Venue

from .management.commands.seed_demo import _hero_image


@pytest.mark.django_db
def test_seed_demo_creates_full_dataset_without_hero():
    call_command("seed_demo", "--no-hero")
    assert Organization.objects.count() == 20
    assert Venue.objects.count() == 120
    # 400 JSON events + 1 promoted event with provenance.
    assert Event.objects.count() == 401
    assert EventSource.objects.count() == 20
    assert EventObservation.objects.count() == 6
    # One org is inactive → hidden from the public API.
    assert Organization.objects.filter(is_active=False).count() == 1


@pytest.mark.django_db
def test_seed_demo_each_org_spans_at_least_five_venues():
    call_command("seed_demo", "--no-hero")
    for org in Organization.objects.all():
        venue_count = (
            Event.objects.filter(organization=org)
            .exclude(venue=None)
            .values_list("venue", flat=True)
            .distinct()
            .count()
        )
        # Online events have no venue, but every org still spans >=5 venues.
        assert venue_count >= 5, f"{org.name} spans only {venue_count} venues"


@pytest.mark.django_db
def test_seed_demo_lifecycle_and_classification_coverage():
    call_command("seed_demo", "--no-hero")
    statuses = set(Event.objects.values_list("status", flat=True))
    assert statuses == {"draft", "published", "cancelled", "archived"}
    assert set(Event.objects.values_list("event_type", flat=True)) == {
        "meetup", "conference", "workshop", "social", "other"
    }
    assert set(Event.objects.values_list("attendance_mode", flat=True)) == {
        "physical", "online", "hybrid"
    }
    # The promoted event carries full provenance.
    promoted = Event.objects.get(title="Intro to FastAPI")
    assert promoted.status == "published"
    assert promoted.source_id is not None
    assert promoted.promoted_from_id is not None
    assert promoted.original_url


@pytest.mark.django_db
def test_seed_demo_is_idempotent():
    call_command("seed_demo", "--no-hero")
    counts = {
        Organization: Organization.objects.count(),
        Venue: Venue.objects.count(),
        Event: Event.objects.count(),
        EventSource: EventSource.objects.count(),
        EventObservation: EventObservation.objects.count(),
    }
    call_command("seed_demo", "--no-hero")
    for model, count in counts.items():
        assert model.objects.count() == count, f"{model.__name__} count drifted"


@pytest.mark.django_db
def test_seed_demo_attaches_hero_images():
    """A real (with-hero) seed attaches a hero image to every canonical event."""
    call_command("seed_demo")
    assert Event.objects.exclude(hero_image="").count() == Event.objects.count()
    assert Event.objects.filter(hero_image__isnull=False).exclude(hero_image="").exists()


def test_hero_image_is_a_png_contentfile():
    """The generator returns a non-empty PNG (no Django/DB needed)."""
    img = _hero_image("Berlin Python Meetup #1: Intro to Django", category="Python")
    data = img.read()
    img.seek(0)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG signature
    assert len(data) > 1000


def test_hero_image_varies_by_title():
    a = _hero_image("Alpha event title").read()
    b = _hero_image("Completely different title").read()
    assert a != b  # deterministic but distinct per title