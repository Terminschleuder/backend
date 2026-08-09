"""OpenAPI 3 schema (drf-spectacular): the API is self-describing, and the
demo client generates its TypeScript types from this schema (single source of
truth). Served read-only alongside the API.
"""

import pytest

pytestmark = pytest.mark.django_db


def test_openapi_schema_endpoint_returns_schema(api_client):
    response = api_client.get("/api/schema/?format=json")
    assert response.status_code == 200
    body = response.content.decode()
    # Core public components are described.
    assert "Event" in body
    assert "City" in body
    # The hero image field is part of the contract (the demo renders it).
    assert "hero_image" in body


def test_swagger_ui_renders(api_client):
    response = api_client.get("/api/schema/swagger-ui/")
    assert response.status_code == 200
    assert b"swagger" in response.content.lower()


def test_redoc_renders(api_client):
    response = api_client.get("/api/schema/redoc/")
    assert response.status_code == 200
    assert b"redoc" in response.content.lower()