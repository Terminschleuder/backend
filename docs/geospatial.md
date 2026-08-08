# Geospatial & cities

How terminschleuder stores, queries, and exposes geographic location, and how the **city
gazetteer** lets end users discover events without knowing coordinates.

## Storage

Both `Event` and `Venue` have a `location` field, and the `City` gazetteer has a centroid:

```python
location = models.PointField(geography=True, srid=4326)
```

- **`geography=True`** — stores the point on the geodetic sphere, so distance/area
  calculations account for Earth's curvature and return **meters** (not degrees). This is
  what makes "within N km" correct globally.
- **`srid=4326`** — WGS 84 (lon/lat), the standard GPS coordinate system.
- **Point order is `(longitude, latitude)`** — the GEOS/PostGIS convention (x=lon, y=lat),
  the opposite of the common "lat, lon" shorthand. `Point(13.405, 52.52)` is Berlin.

The PostGIS backend automatically creates a **GiST spatial index** on each `PointField`,
which `ST_DWithin` proximity queries use for fast bounding-box pre-filtering.

> The PostGIS extension is created by the `events` app's initial migration; the `locations`
> migration only adds the `City` table.

## Coordinate I/O on the API

`location` is not exposed directly. Serializers translate to/from `latitude` + `longitude`:

- **Output** (`GET`): `latitude` = `location.y`, `longitude` = `location.x` (via
  `SerializerMethodField` / `to_representation`).
- **Input** (`POST`/`PATCH`): `latitude` + `longitude` are **write-only** float fields. The
  serializer builds `Point(float(lon), float(lat), srid=4326)` and stores it as `location`.

For events, location resolves in this priority: **explicit `latitude`/`longitude`** → else
the **venue's location** (if a `venue_id` with a location is supplied) → else `null`.

## Proximity search (raw coordinates)

```bash
curl 'http://localhost:8000/api/events/?lat=52.52&lon=13.405&radius_km=10'
```

Implementation (`events/views.py` `EventViewSet.get_queryset`):

```python
point = Point(float(lon), float(lat), srid=4326)
qs = qs.filter(location__distance_lte=(point, D(km=radius)))
qs = qs.annotate(distance=Distance("location", point))
qs = qs.order_by("distance")
```

- `location__distance_lte=(point, D(km=r))` — `ST_DWithin` on the geography column; events
  within `r` km of the point.
- `Distance("location", point)` — annotates each row with its distance (a
  `django.contrib.gis.measure.Distance` in **meters** for geography).
- `order_by("distance")` — nearest first.
- The serializer exposes `distance` in **km**, rounded to 2 decimals (`round(km, 2)`).

Rules:

- `lat`, `lon`, and `radius_km` must **all** be supplied together (else `400`).
- `radius_km` must be a non-negative number (else `400`).
- Events with no `location` are **excluded** from proximity results.
- When a proximity filter is active, `?ordering=` is ignored — results are always
  distance-ordered. (Non-proximity listings fall back to the model's default ordering.)
- The GiST index makes `ST_DWithin` efficient even over the full events table.

## `?near_city=<slug>` — proximity by city

End users don't know lat/lon. The gazetteer lets a client fetch a **pick-list of cities**,
then ask for events "near a city" in one call:

```bash
# 1. user picks a city
curl 'http://localhost:8000/api/cities/?search=berlin'
# → {"slug":"berlin-de", "latitude":52.52, "longitude":13.405, "default_radius_km":45, …}

# 2. events near it (centroid + default radius), distance-annotated, nearest first
curl 'http://localhost:8000/api/events/?near_city=berlin-de'

# 3. override the default radius
curl 'http://localhost:8000/api/events/?near_city=berlin-de&radius_km=10'
```

Resolution (`EventViewSet._resolve_proximity`):

1. If `near_city` is set together with `lat`/`lon` → `400`
   `"Use either near_city or lat/lon, not both."`.
2. Look up `City.objects.filter(is_active=True, slug=near_city).first()`; missing or no
   location → `400` `"Unknown city slug."`.
3. Use the city's `location` as the query point; radius = `radius_km` if supplied, else the
   city's `default_radius_km`.
4. Apply the same `distance_lte` / `Distance` annotate / `order_by("distance")` as the raw
   path.

### `?near_city=` vs `?city=`

Two distinct, independent filters on `/api/events/`:

| Param | Matches | Mechanism |
| --- | --- | --- |
| `near_city=<slug>` | a **gazetteer city slug** | filters events by **distance from the city centroid** |
| `city=<text>` | a venue's **`city` text field** | exact, case-insensitive scalar match (`venue__city` iexact) |

They can't meaningfully be combined; `near_city` is the location-aware one.

## City catalog API

`/api/cities/` (read-only `ReadOnlyModelViewSet`, public):

- `?search=<q>` — partial match on `name`.
- `?country_code=<2-letter>` — exact filter.
- `?ordering=name` / `-population`.
- `?page=` / `?page_size=` (default 25, max 1000).

`/api/cities/all/` — a custom `@action` returning the **entire active catalog as a bare
list** (no pagination envelope); filters still apply. Intended for clients that want to
cache an offline pick-list / autocomplete.

Each city exposes `id`, `geoname_id`, `name`, `slug`, `country`, `country_code`,
`latitude`, `longitude`, `default_radius_km`, `population`, `timezone` (all read-only).

## City data & seeding

### Seeding

```bash
docker compose exec web python manage.py seed_cities          # idempotent load
docker compose exec web python manage.py seed_cities --reset  # clear & reload
```

`seed_cities` reads the committed dataset `locations/data/european_cities_50k.json` and
upserts each row by `geoname_id` (`update_or_create`), building
`Point(float(lon), float(lat), srid=4326)`. **No network at runtime** — the JSON is the
source of truth, committed to the repo, so seeding works offline and CI needs no network.

### Dataset

`locations/data/european_cities_50k.json` — an array of objects:

```json
{ "geoname_id": 2950159, "name": "Berlin", "country": "Germany", "country_code": "DE",
  "lat": 52.52, "lon": 13.405, "population": 3426354, "timezone": "Europe/Berlin",
  "default_radius_km": 45, "slug": "berlin-de" }
```

- **2131 European cities with population ≥ 50 000.**
- `default_radius_km` is tiered by population: ≥ 1 M → 45, ≥ 500 k → 35, ≥ 100 k → 25,
  else 15.
- Russia is filtered to its **European part** (longitude < 60°) to avoid including
  Siberian/Far-East cities.
- Duplicate slugs (same name + country code) are disambiguated with a `-<geoname_id % 100000>` suffix.

### Regenerating the dataset (offline, not run by the app)

`scripts/build_european_cities_fixture.py` rebuilds the JSON from GeoNames sources — run it
**once, with network**, to refresh the committed file. It uses only the Python stdlib
(`urllib`, `zipfile`, `json`, `re`, `unicodedata`):

- Fetches GeoNames `cities15000.zip` (all cities ≥ 15 k) and `countryInfo.txt`.
- Keeps feature class `P` (populated place), country in a European set, population ≥ 50 000.
- Applies the RU-longitude filter, computes the radius tier, disambiguates slugs.
- Writes `locations/data/european_cities_50k.json`.

The running app and CI never execute this script; it is a reproducibility/maintenance tool.

## Why PostGIS (and the no-host-GIS constraint)

`django.contrib.gis` loads GDAL/GEOS/PROJ from the system. The deployment target does not
allow installing system packages — production "can only pull the image of this app." So:

- the **app image bundles** GDAL/GEOS/PROJ (apt-installed in `Dockerfile`);
- the **database is PostGIS** (`Dockerfile.db`);
- the host never runs the app — dev, tests, and prod all run inside containers.

See [Architecture](architecture.md) for the full container layout.