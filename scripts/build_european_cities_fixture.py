#!/usr/bin/env python3
"""Offline generator for the European cities seed dataset.

Fetches GeoNames `cities15000` (all populated places with population >= 15000) plus
`countryInfo`, keeps European cities with population >= 50000, computes a suggested
`default_radius_km` from a population tier, and writes a plain-JSON dataset that the
`seed_cities` management command loads.

This is a **reproducibility tool**, not part of the running app. It is run once
(with network) to (re)generate `locations/data/european_cities_50k.json`; the
committed file is the source of truth and the app/CI never need network access.

Usage:
    python3 scripts/build_european_cities_fixture.py

GeoNames columns (cities15000.txt, tab-delimited):
    0 geonameid  1 name  2 asciiname  3 alternatenames  4 latitude  5 longitude
    6 feature class  7 feature code  8 country code  9 cc2  10 admin1  11 admin2
    12 admin3  13 admin4  14 population  15 elevation  16 dem  17 timezone  18 moddate

GeoNames columns (countryInfo.txt, tab-delimited, '#' comments):
    0 ISO  1 ISO3  2 ISO-Numeric  3 fips  4 Country  5 Capital  6 Area  7 Population
    8 Continent  ...
"""

import json
import re
import unicodedata
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

CITIES_URL = "http://download.geonames.org/export/dump/cities15000.zip"
COUNTRY_INFO_URL = "http://download.geonames.org/export/dump/countryInfo.txt"
OUTPUT = Path(__file__).resolve().parent.parent / "locations" / "data" / "european_cities_50k.json"

MIN_POPULATION = 50_000

# Geographical Europe (broad: EU + EFTA + UK + Balkans + Eastern Europe incl. Russia).
# Turkey and the Caucasus are excluded as they are predominantly in Asia.
EUROPE_CODES = {
    "AD", "AL", "AT", "AX", "BA", "BE", "BG", "BY", "CH", "CY", "CZ", "DE", "DK",
    "EE", "ES", "FI", "FO", "FR", "GB", "GG", "GI", "GR", "HR", "HU", "IE", "IM",
    "IS", "IT", "JE", "LI", "LT", "LU", "LV", "MC", "MD", "ME", "MK", "MT", "NL",
    "NO", "PL", "PT", "RO", "RS", "RU", "SE", "SI", "SK", "SM", "SJ", "UA", "VA",
}


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def default_radius_km(pop: int) -> int:
    if pop >= 1_000_000:
        return 45
    if pop >= 500_000:
        return 35
    if pop >= 100_000:
        return 25
    return 15


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - fixed GeoNames URL
        return r.read()


def build_country_names() -> dict:
    raw = fetch(COUNTRY_INFO_URL).decode("utf-8", "replace")
    names = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) > 4:
            names[cols[0]] = cols[4]
    return names


def main() -> None:
    print(f"Fetching {COUNTRY_INFO_URL} ...")
    country_names = build_country_names()

    print(f"Fetching {CITIES_URL} ...")
    data = fetch(CITIES_URL)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        txt = zf.read("cities15000.txt").decode("utf-8", "replace")

    records = []
    for line in txt.splitlines():
        if not line:
            continue
        cols = line.split("\t")
        if len(cols) < 18:
            continue
        feature_class = cols[6]
        country_code = cols[8]
        pop_str = cols[14]
        if feature_class != "P" or country_code not in EUROPE_CODES:
            continue
        try:
            pop = int(pop_str)
        except ValueError:
            continue
        if pop < MIN_POPULATION:
            continue
        try:
            lat = float(cols[4])
            lon = float(cols[5])
        except ValueError:
            continue
        # Russia is transcontinental: keep only its European part (west of the Urals).
        if country_code == "RU" and lon >= 60.0:
            continue
        geoname_id = int(cols[0])
        records.append({
            "geoname_id": geoname_id,
            "name": cols[1],
            "country": country_names.get(country_code, ""),
            "country_code": country_code,
            "lat": lat,
            "lon": lon,
            "population": pop,
            "timezone": cols[17],
            "default_radius_km": default_radius_km(pop),
        })

    # Disambiguate duplicate slugs (same name + country) by appending part of the id.
    slug_counts: dict[str, int] = {}
    raw_slugs = [slugify(f"{r['name']}-{r['country_code']}") or slugify(r["name"]) for r in records]
    for s in raw_slugs:
        slug_counts[s] = slug_counts.get(s, 0) + 1
    for r, s in zip(records, raw_slugs):
        if slug_counts[s] > 1:
            r["slug"] = f"{s}-{r['geoname_id'] % 100000}"
        else:
            r["slug"] = s

    records.sort(key=lambda r: (r["country_code"], r["name"]))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(records, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} cities to {OUTPUT}")


if __name__ == "__main__":
    main()