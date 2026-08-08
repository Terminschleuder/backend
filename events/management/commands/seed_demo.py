"""Seed a rich, coherent demo dataset across every area of the app.

Populates organizations, venues, categories, event sources (approved /
disabled / unapproved), ingestion runs (succeeded / failed / running),
event observations (pending / accepted / rejected / promoted), and
canonical events with full lifecycle and provenance variety — enough for a
newcomer to open the backoffice or hit the public API and see real, usable
content. Also provisions a demo operator user and the ``ingestion`` group.

Usage:
    python manage.py seed_demo

Idempotent and non-destructive: every object is created by a stable natural
key (name / url / title+starts_at) with deterministic datetimes, so re-running
never produces duplicates and never overwrites anything you've since edited.
It is purely additive and never deletes, so it won't disturb your own data.

Run inside the container:
    docker compose exec web python manage.py seed_demo
"""

from datetime import datetime, timedelta, timezone as dt_tz

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import (
    Category,
    Event,
    EventObservation,
    EventSource,
    IngestionRun,
    Organization,
    Venue,
)

User = get_user_model()

# Demo operator credentials (dev convenience only — never use in prod).
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo12345"

# Fixed UTC datetimes so re-runs are deterministic (idempotent creates).
UTC = dt_tz.utc
BASE = datetime(2026, 9, 1, 17, 0, tzinfo=UTC)  # a stable reference instant


def _dt(**kwargs):
    return BASE + timedelta(**kwargs)


def _point(lon, lat):
    return Point(float(lon), float(lat), srid=4326)


def _slugify_title(title):
    """Minimal slugify for demo observation URLs (keeps the command stdlib-only)."""
    return title.lower().replace(" ", "-").replace(":", "")


class Command(BaseCommand):
    help = "Seed a rich, coherent demo dataset (organizations, sources, runs, observations, events)."

    def handle(self, *args, **options):
        operator = self._operator()
        self._ensure_ingestion_group()

        orgs = self._organizations(operator)
        venues = self._venues()
        categories = self._categories()
        sources = self._event_sources(orgs)
        runs = self._ingestion_runs(sources, operator)
        self._event_observations(sources, runs, operator)
        self._canonical_events(orgs, venues, categories, operator)
        self._promoted_event(sources, operator)

        self.stdout.write(self.style.SUCCESS(
            "Seeded demo dataset: organizations, venues, categories, event "
            "sources, ingestion runs, observations, and events (lifecycle + "
            "provenance)."
        ))
        self.stdout.write(self.style.WARNING(
            f"Demo operator: username={DEMO_USERNAME!r} password={DEMO_PASSWORD!r} "
            "(staff; dev-only — change or remove before any non-local use)."
        ))

    # --- Setup helpers ------------------------------------------------------

    def _operator(self):
        """A demo staff user (with change_event) to own events / review work."""
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={"email": "demo@terminschleuder.example", "is_staff": True},
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label="events", codename="change_event"
        ))
        return user

    def _ensure_ingestion_group(self):
        group, _ = Group.objects.get_or_create(name="ingestion")
        group.permissions.add(*Permission.objects.filter(
            content_type__app_label="events",
            codename__in=[
                "view_eventsource",
                "add_ingestionrun", "change_ingestionrun", "view_ingestionrun",
                "add_eventobservation", "view_eventobservation",
            ],
        ))

    # --- Domain data --------------------------------------------------------

    def _organizations(self, owner):
        specs = [
            ("Berlin Python Meetup", "Monthly Python talks and hacks in Berlin.",
             "https://www.berlin-python.org", True),
            ("Frontend Berlin", "Frontend engineering meetup community.",
             "https://frontend.berlin", True),
            ("Data Science Berlin", "Data, ML and analytics talks.",
             "https://datascience.berlin", True),
            ("Legacy Events Org", "A dormant org kept for history.",
             "https://legacy.example", False),  # inactive → hidden from public API
        ]
        orgs = {}
        for name, desc, website, is_active in specs:
            defaults = {"description": desc, "website": website, "is_active": is_active}
            if name == "Berlin Python Meetup":
                defaults["owner"] = owner
            org, _ = Organization.objects.get_or_create(name=name, defaults=defaults)
            orgs[name] = org
        return orgs

    def _venues(self):
        specs = [
            ("Factory Berlin", "Rheinsberger Str. 76", "Berlin", 52.531, 13.386, 120),
            ("c-base", "Rungestraße 20", "Berlin", 52.513, 13.415, 80),
            ("Metalworx", "Harzer Str. 98", "Berlin", 52.483, 13.446, 60),
            ("Microsoft Atrium", "Unter den Linden 17", "Berlin", 52.517, 13.393, 200),
        ]
        venues = {}
        for name, address, city, lat, lon, cap in specs:
            venue, _ = Venue.objects.get_or_create(
                name=name,
                defaults={
                    "address": address,
                    "city": city,
                    "location": _point(lon, lat),
                    "capacity": cap,
                },
            )
            venues[name] = venue
        return venues

    def _categories(self):
        names = ["Tech", "Python", "Frontend", "Data", "Music", "Social"]
        cats = {}
        for name in names:
            cat, _ = Category.objects.get_or_create(name=name)
            cats[name] = cat
        return cats

    def _event_sources(self, orgs):
        """Sources in varied states: approved+active, approved+disabled, unapproved."""
        specs = [
            # (org_name, url, platform, is_approved, is_active, fetch_interval)
            ("Berlin Python Meetup", "https://www.berlin-python.org/events.ics",
             "homepage", True, True, 60),
            ("Berlin Python Meetup", "https://www.meetup.com/berlin-python/events/",
             "meetup", True, True, 1440),
            ("Frontend Berlin", "https://www.meetup.com/frontend-berlin/",
             "meetup", True, True, 60),
            ("Data Science Berlin", "https://www.meetup.com/data-science-berlin/",
             "meetup", True, False, 60),  # approved but paused (disabled)
            ("Legacy Events Org", "https://legacy.example/feed.xml",
             "homepage", False, True, 60),  # not approved → never due
        ]
        sources = {}
        for org_name, url, platform, approved, active, interval in specs:
            src, _ = EventSource.objects.get_or_create(
                organization=orgs[org_name], url=url,
                defaults={
                    "platform": platform,
                    "is_approved": approved,
                    "is_active": active,
                    "fetch_interval_minutes": interval,
                },
            )
            sources[(org_name, url)] = src
        return sources

    def _ingestion_runs(self, sources, operator):
        """A succeeded run (with a promoted obs), a failed run, and a running run."""
        python_home = sources[("Berlin Python Meetup", "https://www.berlin-python.org/events.ics")]
        python_meetup = sources[("Berlin Python Meetup", "https://www.meetup.com/berlin-python/events/")]
        frontend = sources[("Frontend Berlin", "https://www.meetup.com/frontend-berlin/")]

        succeeded, _ = IngestionRun.objects.get_or_create(
            source=python_home, started_at=_dt(days=-30),
            defaults={
                "status": IngestionRun.Status.SUCCEEDED,
                "finished_at": _dt(days=-30, minutes=20),
                "events_found": 3,
                "events_promoted": 1,
                "reported_by": operator,
            },
        )
        failed, _ = IngestionRun.objects.get_or_create(
            source=python_meetup, started_at=_dt(days=-15),
            defaults={
                "status": IngestionRun.Status.FAILED,
                "finished_at": _dt(days=-15, minutes=5),
                "events_found": 0,
                "error_message": "Upstream returned HTTP 503; source unreachable.",
                "reported_by": operator,
            },
        )
        running, _ = IngestionRun.objects.get_or_create(
            source=frontend, started_at=_dt(minutes=-12),
            defaults={"status": IngestionRun.Status.RUNNING, "reported_by": operator},
        )
        return {"succeeded": succeeded, "failed": failed, "running": running}

    def _event_observations(self, sources, runs, operator):
        """Pending / accepted / rejected / promoted observations for review."""
        python_home = sources[("Berlin Python Meetup", "https://www.berlin-python.org/events.ics")]
        frontend = sources[("Frontend Berlin", "https://www.meetup.com/frontend-berlin/")]
        python_meetup = sources[("Berlin Python Meetup", "https://www.meetup.com/berlin-python/events/")]

        specs = [
            # (source, run, title, starts_at, status, venue_name, lat, lon)
            # PROMOTED: the observation that became a canonical event (see _promoted_event).
            (python_home, runs["succeeded"], "Intro to FastAPI", _dt(days=14),
             EventObservation.Status.PROMOTED, "Factory Berlin", 52.531, 13.386),
            # ACCEPTED: kept for later promotion.
            (python_home, runs["succeeded"], "Async Python patterns", _dt(days=21),
             EventObservation.Status.ACCEPTED, "c-base", 52.513, 13.415),
            # REJECTED: a duplicate / junk entry.
            (python_home, runs["succeeded"], "Spammy listing (test)", _dt(days=18),
             EventObservation.Status.REJECTED, "", None, None),
            # PENDING: fresh, awaiting review (frontend run still running).
            (frontend, runs["running"], "React Server Components workshop", _dt(days=10),
             EventObservation.Status.PENDING, "Microsoft Atrium", 52.517, 13.393),
            (frontend, runs["running"], "TypeScript tips & tricks", _dt(days=28),
             EventObservation.Status.PENDING, "Metalworx", 52.483, 13.446),
            # PENDING: orphan (no run) — a direct-submit shape.
            (python_meetup, None, "PyPy in production", _dt(days=35),
             EventObservation.Status.PENDING, "", 52.520, 13.405),
        ]
        for source, run, title, starts_at, status, venue_name, lat, lon in specs:
            defaults = {
                "run": run,
                "status": status,
                "description": f"Extracted observation for {title}.",
                "url": f"https://example.com/{_slugify_title(title)}",
                "platform": source.platform,
                "attendance_mode": Event.AttendanceMode.PHYSICAL,
                "event_type": Event.EventType.MEETUP,
                "venue_name": venue_name,
                "venue_city": "Berlin" if venue_name else "",
            }
            if lat is not None and lon is not None:
                defaults["location"] = _point(lon, lat)
            if status != EventObservation.Status.PENDING:
                defaults["reviewed_by"] = operator
                defaults["reviewed_at"] = _dt(days=-29)
            EventObservation.objects.get_or_create(
                source=source, title=title, starts_at=starts_at, defaults=defaults,
            )

    def _canonical_events(self, orgs, venues, categories, operator):
        """Hand-curated events with lifecycle + classification variety."""
        factory = venues["Factory Berlin"]
        cbase = venues["c-base"]
        metalworx = venues["Metalworx"]
        atrium = venues["Microsoft Atrium"]

        specs = [
            # (title, starts_at, venue, org, type, attendance, status, cats, cap)
            ("Berlin Python Meetup #42", _dt(days=7), factory,
             orgs["Berlin Python Meetup"], Event.EventType.MEETUP,
             Event.AttendanceMode.PHYSICAL, Event.Status.PUBLISHED,
             ["Tech", "Python"], 100),
            ("React Berlin: Server Components Deep Dive", _dt(days=12), atrium,
             orgs["Frontend Berlin"], Event.EventType.WORKSHOP,
             Event.AttendanceMode.PHYSICAL, Event.Status.PUBLISHED,
             ["Tech", "Frontend"], 150),
            ("Data Science Stammtisch", _dt(days=9), cbase,
             orgs["Data Science Berlin"], Event.EventType.SOCIAL,
             Event.AttendanceMode.PHYSICAL, Event.Status.PUBLISHED,
             ["Data", "Social"], 60),
            ("Indie Acoustic Sessions", _dt(days=20), metalworx,
             orgs["Berlin Python Meetup"], Event.EventType.SOCIAL,
             Event.AttendanceMode.PHYSICAL, Event.Status.PUBLISHED,
             ["Music", "Social"], 50),
            ("Remote DevOps Office Hours", _dt(days=5), None,
             orgs["Frontend Berlin"], Event.EventType.MEETUP,
             Event.AttendanceMode.ONLINE, Event.Status.PUBLISHED,
             ["Tech"], 200),  # online → excluded from proximity
            ("Hybrid Kubernetes Meetup", _dt(days=16), factory,
             orgs["Berlin Python Meetup"], Event.EventType.MEETUP,
             Event.AttendanceMode.HYBRID, Event.Status.PUBLISHED,
             ["Tech"], 120),  # hybrid → included in proximity
            ("Unlisted Tech Talk (draft)", _dt(days=25), atrium,
             orgs["Frontend Berlin"], Event.EventType.WORKSHOP,
             Event.AttendanceMode.PHYSICAL, Event.Status.DRAFT,
             ["Tech"], 80),  # draft → not public
            ("Cancelled: GraphQL Berlin", _dt(days=3), cbase,
             orgs["Data Science Berlin"], Event.EventType.MEETUP,
             Event.AttendanceMode.PHYSICAL, Event.Status.CANCELLED,
             ["Tech", "Frontend"], 60),  # cancelled → not public
            ("Archived: 2025 Kickoff", _dt(days=-120), metalworx,
             orgs["Berlin Python Meetup"], Event.EventType.SOCIAL,
             Event.AttendanceMode.PHYSICAL, Event.Status.ARCHIVED,
             ["Social"], 40),  # archived → not public
        ]
        for title, starts_at, venue, org, etype, attend, status, cat_names, cap in specs:
            defaults = {
                "venue": venue,
                "organization": org,
                "event_type": etype,
                "attendance_mode": attend,
                "status": status,
                "capacity": cap,
                "created_by": operator,
            }
            if venue is not None and venue.location is not None:
                defaults["location"] = venue.location
            if status == Event.Status.PUBLISHED:
                defaults["published_at"] = _dt(days=-10)
            elif status == Event.Status.CANCELLED:
                defaults["cancelled_at"] = _dt(days=-1)
            event, created = Event.objects.get_or_create(
                title=title, starts_at=starts_at, defaults=defaults,
            )
            if created:
                event.categories.set([categories[n] for n in cat_names])

    def _promoted_event(self, sources, operator):
        """A canonical event promoted from an observation — published, with provenance."""
        source = sources[("Berlin Python Meetup", "https://www.berlin-python.org/events.ics")]
        obs = EventObservation.objects.get(
            source=source, title="Intro to FastAPI", starts_at=_dt(days=14),
        )
        venue, _ = Venue.objects.get_or_create(
            name=obs.venue_name,
            defaults={"city": obs.venue_city or "Berlin", "location": obs.location},
        )
        starts_at = obs.starts_at
        Event.objects.get_or_create(
            title="Intro to FastAPI", starts_at=starts_at,
            defaults={
                "description": obs.description,
                "ends_at": starts_at + timedelta(hours=2),
                "venue": venue,
                "organization": source.organization,
                "event_type": Event.EventType.WORKSHOP,
                "attendance_mode": obs.attendance_mode,
                "status": Event.Status.PUBLISHED,
                "published_at": _dt(days=-9),
                "original_url": obs.url,
                "original_platform": obs.platform,
                "location": obs.location,
                "source": source,
                "promoted_from": obs,
                "created_by": operator,
            },
        )