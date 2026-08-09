"""CORS: the public read API must be callable from a browser on another origin
(support for the read-only demo client). Only GET/HEAD/OPTIONS, no credentials.
"""

import pytest

pytestmark = pytest.mark.django_db


def test_public_get_sends_cors_allow_origin(api_client):
    response = api_client.get(
        "/api/cities/", format="json", HTTP_ORIGIN="http://example.com"
    )
    assert response.status_code == 200
    # Default CORS_ALLOW_ALL_ORIGINS=True → either '*' or the echoed origin.
    allow_origin = response.headers.get("Access-Control-Allow-Origin")
    assert allow_origin in ("*", "http://example.com")


def test_cors_does_not_allow_credentials(api_client):
    response = api_client.get(
        "/api/cities/", format="json", HTTP_ORIGIN="http://example.com"
    )
    assert response.headers.get("Access-Control-Allow-Credentials") in (None, "false", "False")


def test_cors_options_preflight_returns_allowed_methods(api_client):
    response = api_client.options(
        "/api/cities/", HTTP_ORIGIN="http://example.com",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
    )
    assert response.status_code in (200, 204)
    allow_methods = response.headers.get("Access-Control-Allow-Methods", "")
    # Read-only: no POST/PUT/PATCH/DELETE.
    assert "GET" in allow_methods
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert verb not in allow_methods