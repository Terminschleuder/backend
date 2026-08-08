from .models import City


def _results(response):
    data = response.data
    return data["results"] if "results" in data else data


def _make_cities():
    City.objects.create(
        geoname_id=1, name="Berlin", country="Germany", country_code="DE",
        location="POINT(13.405 52.52)", population=3_400_000,
        default_radius_km=45, timezone="Europe/Berlin", slug="berlin-de",
    )
    City.objects.create(
        geoname_id=2, name="Hamburg", country="Germany", country_code="DE",
        location="POINT(9.99 53.55)", population=1_900_000,
        default_radius_km=35, timezone="Europe/Berlin", slug="hamburg-de",
    )
    City.objects.create(
        geoname_id=3, name="Vienna", country="Austria", country_code="AT",
        location="POINT(16.37 48.21)", population=1_800_000,
        default_radius_km=35, timezone="Europe/Vienna", slug="vienna-at",
    )


def test_city_list_exposes_lat_lon_and_slug(db, api_client):
    _make_cities()
    response = api_client.get("/api/cities/", format="json")
    assert response.status_code == 200
    items = {c["name"]: c for c in _results(response)}
    assert set(items) == {"Berlin", "Hamburg", "Vienna"}
    berlin = items["Berlin"]
    assert berlin["slug"] == "berlin-de"
    assert abs(berlin["latitude"] - 52.52) < 0.01
    assert abs(berlin["longitude"] - 13.405) < 0.01
    assert berlin["country_code"] == "DE"
    assert berlin["default_radius_km"] == 45


def test_city_search(db, api_client):
    _make_cities()
    response = api_client.get("/api/cities/?search=berl", format="json")
    assert response.status_code == 200
    assert {c["name"] for c in _results(response)} == {"Berlin"}


def test_city_filter_by_country_code(db, api_client):
    _make_cities()
    response = api_client.get("/api/cities/?country_code=DE", format="json")
    assert response.status_code == 200
    assert {c["name"] for c in _results(response)} == {"Berlin", "Hamburg"}


def test_city_ordering_by_population(db, api_client):
    _make_cities()
    response = api_client.get("/api/cities/?ordering=-population", format="json")
    assert response.status_code == 200
    assert [c["name"] for c in _results(response)] == ["Berlin", "Hamburg", "Vienna"]


def test_city_all_returns_unpaginated_list(db, api_client):
    _make_cities()
    response = api_client.get("/api/cities/all/", format="json")
    assert response.status_code == 200
    # Unpaginated: the body is a bare list, not the {count, results} envelope.
    assert isinstance(response.data, list)
    assert {c["name"] for c in response.data} == {"Berlin", "Hamburg", "Vienna"}
    assert response.data[0]["slug"]


def test_city_page_size_param(db, api_client):
    _make_cities()
    response = api_client.get("/api/cities/?page_size=2", format="json")
    assert response.status_code == 200
    assert response.data["count"] == 3
    assert len(response.data["results"]) == 2
    assert response.data["next"] is not None