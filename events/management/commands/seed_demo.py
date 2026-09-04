"""Seed a rich, coherent demo dataset across every area of the app.

The bulk of the data (organizations, venues, categories, event sources, and
400 canonical events) is **data-driven**: it is loaded from JSON files under
``events/data/seed/`` (regenerate them with ``scripts/build_demo_fixture.py``).
That keeps the seed declarative and easy to edit, while the small provenance
demonstration (a couple of ingestion runs, a handful of observations, and one
promoted canonical event) stays inline so the ingestion → review → promotion
lifecycle stays readable in code.

Populates 20 organizations (one inactive, hidden from the public API), 120
venues across 15 European cities, 8 categories, 20 event sources, ingestion
runs (succeeded / failed / running), event observations (pending / accepted /
rejected / promoted), and 400 canonical events covering the full lifecycle and
classification matrix. Each canonical event is given a generated placeholder
**hero image** (a deterministic Pillow banner) so the catalog looks rich in the
demo client. Also provisions a demo operator user and the ``ingestion`` Group.

Usage:
    python manage.py seed_demo

Idempotent and non-destructive: every object is created by a stable natural
key (slug / name+city / org+url / title) with deterministic datetimes, so
re-running never produces duplicates and never overwrites anything you've
since edited. Hero images are only generated+attached on create, so re-running
won't clobber an image an operator chose afterwards. It is purely additive and
never deletes, so it won't disturb your own data.

Run inside the container:
    docker compose exec web python manage.py seed_demo
"""

import json
from datetime import datetime, timedelta, timezone as dt_tz
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.gis.geos import Point
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils.text import slugify

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

# JSON seed data (regenerate with scripts/build_demo_fixture.py).
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"
# URL of the Berlin Python Meetup source that the inline provenance relies on
# (kept in sync with scripts/build_demo_fixture.py::PROMOTED_SOURCE_URL).
PROMOTED_SOURCE_URL = "https://www.berlin-python.org/events.ics"


def _dt(**kwargs):
    return BASE + timedelta(**kwargs)


def _point(lon, lat):
    return Point(float(lon), float(lat), srid=4326)


def _load(name):
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        raise RuntimeError(
            f"Demo seed data not found: {path}. Generate it with "
            "`python scripts/build_demo_fixture.py`."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _hero_image(title: str, *, category: str | None = None):
    """Generate a deterministic 1200×400 placeholder banner PNG for ``title``.

    One of three background styles (diagonal gradient / horizontal bands /
    concentric arcs) over one of four palettes, both picked from a hash of the
    title so 400 banners look varied rather than identical. An optional
    ``category`` tints the accent colour. The title is word-wrapped onto a
    translucent dark band for legibility. The gradient uses a tiny upscaled
    image (no per-pixel Python loop) so seeding 400 banners stays fast.

    Returns a ``ContentFile`` ready for ``FieldFile.save``. Pillow is required
    (see requirements.txt); a missing Pillow raises a clear error rather than
    corrupting the seed.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RuntimeError(
            "Pillow is required to generate demo hero images but isn't "
            "installed. Add Pillow to requirements and rebuild the image."
        ) from exc

    import colorsys
    import hashlib
    from io import BytesIO

    W, H = 1200, 400
    n = int.from_bytes(hashlib.md5(title.encode("utf-8")).digest()[:4], "big")
    style = n % 3
    c1, c2 = [
        ((28, 56, 110), (78, 150, 230)),   # deep blue
        ((24, 100, 96), (86, 200, 178)),   # cool teal
        ((120, 38, 78), (232, 110, 150)),  # warm magenta
        ((42, 42, 58), (150, 150, 172)),   # mono slate
    ][(n >> 3) % 4]

    if category:
        cat_hue = sum(ord(ch) for ch in category) % 360
        r, g, b = colorsys.hsv_to_rgb(cat_hue / 360.0, 0.5, 0.85)
        c2 = (
            int(c2[0] * 0.5 + r * 255 * 0.5),
            int(c2[1] * 0.5 + g * 255 * 0.5),
            int(c2[2] * 0.5 + b * 255 * 0.5),
        )

    img = Image.new("RGB", (W, H), c1)
    if style == 0:
        # Diagonal gradient via a 2×2 image scaled up — smooth and fast.
        grad = Image.new("RGB", (2, 2), c1)
        grad.putpixel((1, 0), c2)
        grad.putpixel((0, 1), c2)
        grad.putpixel((1, 1), c1)
        img = grad.resize((W, H), Image.BILINEAR)
    else:
        draw = ImageDraw.Draw(img)
        if style == 1:
            bands = 6
            for b in range(bands):
                t = b / (bands - 1)
                fill = tuple(int(c1[k] * (1 - t) + c2[k] * t) for k in range(3))
                draw.rectangle([0, H * b // bands, W, H * (b + 1) // bands], fill=fill)
        else:
            for r in range(80, 1000, 90):
                shade = tuple(min(255, c2[k] + r // 6) for k in range(3))
                draw.ellipse(
                    [W - r, H // 2 - r, W + r, H // 2 + r], outline=shade, width=6
                )

    # Translucent dark band for legible text.
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([0, H - 120, W, H], fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    font = None
    for name in ("DejaVuSans-Bold.ttf",):
        try:
            font = ImageFont.truetype(name, 44)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    def wrap(text, max_chars=46):
        if len(text) <= max_chars:
            return [text]
        cut = text.rfind(" ", 0, max_chars) or max_chars
        return [text[:cut].rstrip(), text[cut:].strip()[:max_chars]]

    y = H - 92
    for line in wrap(title):
        draw.text((24, y), line, font=font, fill=(255, 255, 255))
        y += 56

    buf = BytesIO()
    img.save(buf, format="PNG")
    return ContentFile(buf.getvalue())


def _attach_hero(event: Event, title: str, *, category: str | None = None) -> None:
    """Save a generated hero image to ``event`` (call only on create)."""
    filename = f"{slugify(title)}-{event.starts_at:%Y%m%d}.png"
    event.hero_image.save(filename, _hero_image(title, category=category), save=False)
    event.save(update_fields=["hero_image"])


class Command(BaseCommand):
    help = "Seed a rich, coherent demo dataset (JSON-driven: orgs, venues, categories, sources, 400 events, hero images)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-hero",
            action="store_true",
            help="Skip hero-image generation (faster; for tests / quick re-seeds).",
        )

    def handle(self, *args, **options):
        generate_hero = not options["no_hero"]
        operator = self._operator()
        self._ensure_ingestion_group()

        orgs = self._organizations(operator)
        venues = self._venues()
        categories = self._categories()
        sources = self._event_sources(orgs)
        self._canonical_events(orgs, venues, categories, operator, generate_hero)

        # Inline provenance demonstration (small, fixed set).
        runs = self._ingestion_runs(sources, operator)
        self._event_observations(sources, runs, operator, venues)
        self._promoted_event(sources, operator, venues, generate_hero)

        self.stdout.write(self.style.SUCCESS(
            "Seeded demo dataset: 20 organizations, 120 venues, 8 categories, "
            "20 event sources, 400 canonical events (lifecycle + classification "
            "matrix) with generated hero images, plus ingestion runs, "
            "observations, and a promoted event for provenance."
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
        # Delegates to the shared provisioning helper (single source of truth
        # for the group + its permission set).
        from events.provisioning import ensure_ingestion_group

        ensure_ingestion_group()

    # --- JSON-driven domain data -------------------------------------------

    def _organizations(self, owner):
        """20 orgs from JSON, keyed by slug (unique natural key)."""
        orgs = {}
        for row in _load("organizations"):
            defaults = {
                "name": row["name"],
                "description": row["description"],
                "website": row["website"],
                "is_active": row["is_active"],
            }
            if row.get("is_owner"):
                defaults["owner"] = owner
            org, _ = Organization.objects.get_or_create(slug=row["slug"], defaults=defaults)
            orgs[row["slug"]] = org
        return orgs

    def _venues(self):
        """120 venues from JSON, keyed by (name, city) natural key."""
        venues = {}
        for row in _load("venues"):
            venue, _ = Venue.objects.get_or_create(
                name=row["name"], city=row["city"],
                defaults={
                    "address": row["address"],
                    "location": _point(row["longitude"], row["latitude"]),
                    "capacity": row["capacity"],
                },
            )
            venues[(row["name"], row["city"])] = venue
        return venues

    def _categories(self):
        """8 categories from JSON, keyed by name (unique natural key)."""
        cats = {}
        for row in _load("categories"):
            cat, _ = Category.objects.get_or_create(name=row["name"])
            cats[row["name"]] = cat
        return cats

    def _event_sources(self, orgs):
        """20 event sources from JSON, keyed by (org_slug, url) natural key."""
        sources = {}
        for row in _load("sources"):
            src, _ = EventSource.objects.get_or_create(
                organization=orgs[row["organization_slug"]], url=row["url"],
                defaults={
                    "platform": row["platform"],
                    "is_approved": row["is_approved"],
                    "is_active": row["is_active"],
                    "fetch_interval_minutes": row["fetch_interval_minutes"],
                },
            )
            sources[(row["organization_slug"], row["url"])] = src
        return sources

    def _canonical_events(self, orgs, venues, categories, operator, generate_hero=True):
        """400 events from JSON — full lifecycle + classification matrix."""
        for row in _load("events"):
            venue = None
            if row["venue_name"]:
                venue = venues[(row["venue_name"], row["venue_city"])]

            defaults = {
                "description": row["description"],
                "organization": orgs[row["organization_slug"]],
                "ends_at": (
                    datetime.fromisoformat(row["ends_at"].replace("Z", "+00:00"))
                    if row["ends_at"] else None
                ),
                "event_type": row["event_type"],
                "attendance_mode": row["attendance_mode"],
                "status": row["status"],
                "capacity": row["capacity"],
                "created_by": operator,
            }
            if venue is not None and venue.location is not None:
                defaults["location"] = venue.location
                defaults["venue"] = venue
            if row["published_at"]:
                defaults["published_at"] = datetime.fromisoformat(
                    row["published_at"].replace("Z", "+00:00")
                )
            if row["cancelled_at"]:
                defaults["cancelled_at"] = datetime.fromisoformat(
                    row["cancelled_at"].replace("Z", "+00:00")
                )

            event, created = Event.objects.get_or_create(
                title=row["title"],
                starts_at=datetime.fromisoformat(row["starts_at"].replace("Z", "+00:00")),
                defaults=defaults,
            )
            if created:
                event.categories.set([categories[n] for n in row["category_names"]])
                if generate_hero:
                    category = row["category_names"][0] if row["category_names"] else None
                    _attach_hero(event, row["title"], category=category)

    # --- Inline provenance demonstration -----------------------------------

    def _ingestion_runs(self, sources, operator):
        """A succeeded (with a promoted obs), failed, and running run."""
        python_home = sources[("berlin-python-meetup", PROMOTED_SOURCE_URL)]

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
            source=python_home, started_at=_dt(days=-15),
            defaults={
                "status": IngestionRun.Status.FAILED,
                "finished_at": _dt(days=-15, minutes=5),
                "events_found": 0,
                "error_message": "Upstream returned HTTP 503; source unreachable.",
                "reported_by": operator,
            },
        )
        running, _ = IngestionRun.objects.get_or_create(
            source=python_home, started_at=_dt(minutes=-12),
            defaults={"status": IngestionRun.Status.RUNNING, "reported_by": operator},
        )
        return {"succeeded": succeeded, "failed": failed, "running": running}

    def _event_observations(self, sources, runs, operator, venues):
        """Pending / accepted / rejected / promoted observations for review."""
        python_home = sources[("berlin-python-meetup", PROMOTED_SOURCE_URL)]
        hub = venues[("Berlin Hub", "Berlin")]

        specs = [
            # (title, starts_at, status, run, venue_or_None)
            # PROMOTED: the observation that became a canonical event.
            ("Intro to FastAPI", _dt(days=14), EventObservation.Status.PROMOTED,
             runs["succeeded"], hub),
            # ACCEPTED: kept for later promotion.
            ("Async Python patterns", _dt(days=21), EventObservation.Status.ACCEPTED,
             runs["succeeded"], hub),
            # REJECTED: a duplicate / junk entry.
            ("Spammy listing (test)", _dt(days=18), EventObservation.Status.REJECTED,
             runs["succeeded"], None),
            # PENDING: fresh, awaiting review (run still running).
            ("React Server Components workshop", _dt(days=10), EventObservation.Status.PENDING,
             runs["running"], hub),
            ("TypeScript tips & tricks", _dt(days=28), EventObservation.Status.PENDING,
             runs["running"], hub),
            # PENDING: orphan (no run) — a direct-submit shape.
            ("PyPy in production", _dt(days=35), EventObservation.Status.PENDING,
             None, hub),
        ]
        for title, starts_at, status, run, venue in specs:
            defaults = {
                "run": run,
                "status": status,
                "description": f"Extracted observation for {title}.",
                "url": f"https://example.com/{slugify(title)}",
                "platform": python_home.platform,
                "attendance_mode": Event.AttendanceMode.PHYSICAL,
                "event_type": Event.EventType.MEETUP,
                "venue_name": venue.name if venue else "",
                "venue_city": venue.city if venue else "",
            }
            if venue is not None and venue.location is not None:
                defaults["location"] = venue.location
            if status != EventObservation.Status.PENDING:
                defaults["reviewed_by"] = operator
                defaults["reviewed_at"] = _dt(days=-29)
            EventObservation.objects.get_or_create(
                source=python_home, title=title, starts_at=starts_at, defaults=defaults,
            )

    def _promoted_event(self, sources, operator, venues, generate_hero=True):
        """A canonical event promoted from an observation — published, with provenance."""
        source = sources[("berlin-python-meetup", PROMOTED_SOURCE_URL)]
        obs = EventObservation.objects.get(
            source=source, title="Intro to FastAPI", starts_at=_dt(days=14),
        )
        venue = venues[("Berlin Hub", "Berlin")]
        starts_at = obs.starts_at
        event, created = Event.objects.get_or_create(
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
                "location": venue.location,
                "source": source,
                "promoted_from": obs,
                "created_by": operator,
            },
        )
        if created and generate_hero:
            _attach_hero(event, "Intro to FastAPI", category="Python")