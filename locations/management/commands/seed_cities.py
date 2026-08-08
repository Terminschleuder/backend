"""Seed the City gazetteer from the committed GeoNames-derived dataset.

Usage:
    python manage.py seed_cities            # upsert (idempotent)
    python manage.py seed_cities --reset    # delete all cities first, then load

The dataset lives at ``locations/data/european_cities_50k.json`` (all European
cities with population >= 50000). Regenerate it with
``scripts/build_european_cities_fixture.py``.
"""

import json
from pathlib import Path

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from locations.models import City

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "european_cities_50k.json"


class Command(BaseCommand):
    help = "Seed the City gazetteer from the committed European cities dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing cities before loading (operator use only).",
        )

    def handle(self, *args, **options):
        if not DATA_FILE.exists():
            self.stderr.write(self.style.ERROR(f"Dataset not found: {DATA_FILE}"))
            return

        if options["reset"]:
            deleted, _ = City.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing cities."))

        records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        created = updated = 0
        for row in records:
            _, created_flag = City.objects.update_or_create(
                geoname_id=row["geoname_id"],
                defaults={
                    "name": row["name"],
                    "slug": row["slug"],
                    "country": row["country"],
                    "country_code": row["country_code"],
                    "location": Point(float(row["lon"]), float(row["lat"]), srid=4326),
                    "default_radius_km": row["default_radius_km"],
                    "population": row["population"],
                    "timezone": row["timezone"],
                    "is_active": True,
                },
            )
            if created_flag:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(records)} cities: {created} created, {updated} updated."
        ))