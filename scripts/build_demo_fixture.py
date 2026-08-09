#!/usr/bin/env python3
"""Offline generator for the demo seed dataset.

A **reproducibility tool**, not part of the running app. It is run once (no
network needed) to (re)generate the JSON files under ``events/data/seed/`` that
the ``seed_demo`` management command loads. The committed files are the source
of truth; the app/CI never need to run this.

The generator is fully deterministic: a fixed RNG seed and a fixed ``BASE``
anchor, so re-running produces byte-identical JSON and ``seed_demo`` stays
idempotent. Venue ``city`` values are taken verbatim from the committed city
gazetteer (``locations/data/european_cities_50k.json``) so the frontend's exact
``city`` filter and the city combobox match real cities exactly.

Scale: 20 organizations, 120 venues (8 per home city × 15 cities), 8 categories,
20 event sources, and 400 events (20 per org) — each org's events span ≥5 venues.

Usage:
    python3 scripts/build_demo_fixture.py
"""

import json
import random
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "events" / "data" / "seed"
CITIES_FILE = (
    Path(__file__).resolve().parent.parent
    / "locations"
    / "data"
    / "european_cities_50k.json"
)

# Fixed anchor — matches seed_demo.BASE so dates line up across regenerations.
BASE = datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc)
SEED = 20260901

# ASCII names that exist verbatim in the gazetteer (the frontend `city` exact
# filter and the combobox match on these names, so no umlauts/spaces here).
HOME_CITIES = [
    "Berlin", "Hamburg", "Munich", "Dresden",
    "Vienna", "Prague",
    "Amsterdam", "Brussels", "Paris",
    "Copenhagen", "Stockholm",
    "Lisbon", "Barcelona", "Madrid",
    "Dublin",
]

# (name, home_city, is_active, is_owner)
ORG_SPECS = [
    ("Berlin Python Meetup", "Berlin", True, True),
    ("Frontend Berlin", "Berlin", True, False),
    ("Data Science Berlin", "Berlin", True, False),
    ("Hamburg.js", "Hamburg", True, False),
    ("Hamburg Data", "Hamburg", True, False),
    ("Munich AI Lab", "Munich", True, False),
    ("Munich Mobile Devs", "Munich", True, False),
    ("Vienna DevOps Days", "Vienna", True, False),
    ("Prague Pyvo", "Prague", True, False),
    ("Amsterdam JS", "Amsterdam", True, False),
    ("Brussels Bytes", "Brussels", True, False),
    ("Paris JUG", "Paris", True, False),
    ("Copenhagen Code", "Copenhagen", True, False),
    ("Stockholm Swift", "Stockholm", True, False),
    ("Lisbon Data", "Lisbon", True, False),
    ("Barcelona Backend", "Barcelona", True, False),
    ("Madrid Machine Learning", "Madrid", True, False),
    ("Dublin Devs", "Dublin", True, False),
    ("Dresden Robotics", "Dresden", True, False),
    ("Legacy Events Org", "Berlin", False, False),  # inactive → hidden from public API
]

CATEGORIES = ["Tech", "Python", "Frontend", "Data", "Music", "Social", "Design", "DevOps"]
VENUE_SUFFIXES = ["Hub", "Lab", "Loft", "Forge", "Works", "Studio", "Atrium", "Commons"]
EVENT_TYPES = ["meetup", "conference", "workshop", "social", "other"]
ATTENDANCE_MODES = ["physical", "online", "hybrid"]
# 24 topics cycled across each org's 20 events (titles stay unique via the
# "<org> #<i>:" prefix). "Intro to FastAPI" is intentionally absent — it is
# reserved for the inline promoted-event provenance in seed_demo.
TOPICS = [
    "Intro to Django", "Async Python patterns", "TypeScript tips", "React roundtable",
    "Data engineering basics", "LLM agents hands-on", "RAG over your docs",
    "Kubernetes security", "Platform engineering", "SwiftUI workshop",
    "GraphQL deep dive", "Edge computing", "Observability night", "Rust in production",
    "Frontend performance", "Microservices talk", "DevOps roundtable",
    "ML model serving", "Mobile testing", "Crypto & ZK proofs", "Design systems",
    "Serverless patterns", "Database internals", "Code review social",
]
PLATFORMS = ["meetup", "eventbrite", "ics", "homepage"]

EVENTS_PER_ORG = 20
DAYS_SPAN = 240  # from BASE-60d to BASE+180d
PUBLISHED_AT = BASE - timedelta(days=10)
CANCELLED_AT = BASE - timedelta(days=1)

# URL the inline provenance in seed_demo looks up (must stay stable here).
PROMOTED_SOURCE_URL = "https://www.berlin-python.org/events.ics"


def slugify(value: str) -> str:
    """Match Django's default ``slugify`` for ASCII input."""
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).lower().strip()
    return re.sub(r"[-\s]+", "-", value)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_home_cities() -> dict:
    records = json.loads(CITIES_FILE.read_text(encoding="utf-8"))
    by_name = {r["name"]: r for r in records}
    out = {}
    for name in HOME_CITIES:
        rec = by_name.get(name)
        if rec is None:
            raise SystemExit(f"Home city {name!r} not found in gazetteer {CITIES_FILE}")
        out[name] = {"lat": float(rec["lat"]), "lon": float(rec["lon"])}
    return out


def build_organizations(rng: random.Random) -> list:
    orgs = []
    for name, home_city, is_active, is_owner in ORG_SPECS:
        slug = slugify(name)
        orgs.append({
            "name": name,
            "slug": slug,
            "description": f"{name} — a community organizing events in {home_city}.",
            "website": f"https://{slug}.example",
            "is_active": is_active,
            "is_owner": is_owner,
            "home_city": home_city,
        })
    return orgs


def build_venues(rng: random.Random, cities: dict) -> list:
    venues = []
    for city in HOME_CITIES:
        c = cities[city]
        for i, suffix in enumerate(VENUE_SUFFIXES):
            # Small deterministic jitter so venues are distinct on the map.
            dlat = rng.uniform(-0.02, 0.02)
            dlon = rng.uniform(-0.02, 0.02)
            venues.append({
                "name": f"{city} {suffix}",
                "address": f"{(i + 1) * 12} Example Street",
                "city": city,
                "latitude": round(c["lat"] + dlat, 5),
                "longitude": round(c["lon"] + dlon, 5),
                "capacity": 60 + (i * 30) % 240,
            })
    return venues


def build_sources(orgs: list) -> list:
    sources = []
    for idx, org in enumerate(orgs):
        slug = org["slug"]
        if slug == "berlin-python-meetup":
            sources.append({
                "organization_slug": slug,
                "url": PROMOTED_SOURCE_URL,
                "platform": "homepage",
                "is_approved": True,
                "is_active": True,
                "fetch_interval_minutes": 60,
            })
            continue
        platform = PLATFORMS[idx % len(PLATFORMS)]
        ext = {"ics": "ics", "meetup": "", "homepage": "xml", "eventbrite": ""}[platform]
        url = f"https://{slug}.example/events.{ext}" if ext else f"https://{slug}.example/events"
        sources.append({
            "organization_slug": slug,
            "url": url,
            "platform": platform,
            "is_approved": org["is_active"],  # inactive org → unapproved source
            "is_active": True,
            "fetch_interval_minutes": 60,
        })
    return sources


def build_events(rng: random.Random, orgs: list) -> list:
    events = []
    step = DAYS_SPAN / (EVENTS_PER_ORG - 1)  # ~12.63 days
    for org_idx, org in enumerate(orgs):
        home_city = org["home_city"]
        for i in range(EVENTS_PER_ORG):
            starts_at = BASE + timedelta(days=-60 + step * i)
            event_type = EVENT_TYPES[i % len(EVENT_TYPES)]
            attendance = ATTENDANCE_MODES[i % len(ATTENDANCE_MODES)]
            # ~85% published, one each of draft/cancelled/archived per org.
            if i == 17:
                status = "draft"
            elif i == 18:
                status = "cancelled"
            elif i == 19:
                status = "archived"
            else:
                status = "published"

            online = attendance == "online"
            if online:
                venue_name, venue_city = "", ""
            else:
                suffix = VENUE_SUFFIXES[i % len(VENUE_SUFFIXES)]
                venue_name = f"{home_city} {suffix}"
                venue_city = home_city

            ends_at = iso(starts_at + timedelta(hours=2)) if i % 4 == 0 else None
            title = f"{org['name']} #{i + 1}: {TOPICS[(org_idx * 3 + i) % len(TOPICS)]}"
            # Two distinct categories per event, deterministic by org + index.
            cat_a = CATEGORIES[(org_idx + i) % len(CATEGORIES)]
            cat_b = CATEGORIES[(org_idx + i + 4) % len(CATEGORIES)]
            cat_names = sorted({cat_a, cat_b})

            events.append({
                "title": title,
                "starts_at": iso(starts_at),
                "ends_at": ends_at,
                "event_type": event_type,
                "attendance_mode": attendance,
                "status": status,
                "organization_slug": org["slug"],
                "venue_name": venue_name,
                "venue_city": venue_city,
                "capacity": 40 + (i * 7 + org_idx) % 260,
                "category_names": cat_names,
                "published_at": iso(PUBLISHED_AT) if status == "published" else None,
                "cancelled_at": iso(CANCELLED_AT) if status == "cancelled" else None,
                "description": (
                    f"{title} — a {event_type} ({attendance}) event hosted by "
                    f"{org['name']} in {home_city}."
                ),
            })
    return events


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    cities = load_home_cities()
    orgs = build_organizations(rng)
    venues = build_venues(rng, cities)
    sources = build_sources(orgs)
    events = build_events(rng, orgs)

    payloads = {
        "organizations.json": orgs,
        "venues.json": venues,
        "categories.json": [{"name": n} for n in CATEGORIES],
        "sources.json": sources,
        "events.json": events,
    }
    for name, data in payloads.items():
        path = DATA_DIR / name
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path} ({len(data)} entries)")


if __name__ == "__main__":
    main()