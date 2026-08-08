"""Seed the database with a few sample venues, organizations, categories and events.

Usage:
    python manage.py seed
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Category, Event, Organization, Venue

User = get_user_model()


class Command(BaseCommand):
    help = "Seed the database with sample events data."

    def handle(self, *args, **options):
        organization, _ = Organization.objects.get_or_create(
            name="Berlin Tech Meetups",
            defaults={"description": "Local tech meetups in Berlin.", "website": ""},
        )
        venue, _ = Venue.objects.get_or_create(
            name="Factory Berlin",
            defaults={"address": "Rheinsberger Str. 76", "city": "Berlin", "capacity": 120},
        )
        music, _ = Category.objects.get_or_create(name="Music")
        tech, _ = Category.objects.get_or_create(name="Tech")

        now = timezone.now()
        if not Event.objects.filter(title="Django Meetup Night").exists():
            Event.objects.create(
                title="Django Meetup Night",
                description="Talks and drinks about Django.",
                starts_at=now + timedelta(days=7),
                venue=venue,
                organization=organization,
                capacity=80,
            ).categories.add(tech)

        if not Event.objects.filter(title="Indie Acoustic Sessions").exists():
            Event.objects.create(
                title="Indie Acoustic Sessions",
                description="Local acoustic acts.",
                starts_at=now + timedelta(days=14),
                venue=venue,
                organization=organization,
                capacity=60,
            ).categories.add(music)

        self.stdout.write(self.style.SUCCESS("Seeded sample events, venues and organizations."))