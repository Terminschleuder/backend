"""Shared pytest fixtures for the terminschleuder backend.

Lives at the project root so fixtures apply to all test files (pytest only
applies a conftest.py to tests within its own subtree).
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="password123",
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        username="bob",
        email="bob@example.com",
        password="password456",
    )


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def authed_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def jwt_client(user):
    """APIClient authenticated with a Bearer JWT for ``user``."""
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


@pytest.fixture
def api_key_client(user):
    """APIClient authenticated with a long-lived API key for ``user``."""
    from accounts.models import APIKey

    _, raw_key = APIKey.create(user, name="test-key")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw_key}")
    return client


@pytest.fixture
def editors_group(db):
    group, _ = Group.objects.get_or_create(name="editors")
    return group


# --- Ingestion / provenance fixtures ----------------------------------------


@pytest.fixture
def ingestion_group(db):
    """The ``ingestion`` group carrying the perms the extractor service account
    needs to read due sources, report runs, and submit observations."""
    from django.contrib.auth.models import Permission

    group, _ = Group.objects.get_or_create(name="ingestion")
    codenames = [
        "view_eventsource",
        "add_ingestionrun", "change_ingestionrun", "view_ingestionrun",
        "add_eventobservation", "view_eventobservation",
    ]
    for codename in codenames:
        group.permissions.add(
            Permission.objects.get(
                content_type__app_label="events", codename=codename
            )
        )
    return group


@pytest.fixture
def ingestion_user(db, ingestion_group):
    """An extractor service account in the ``ingestion`` group."""
    user = User.objects.create_user(
        username="extractor",
        email="extractor@example.com",
        password="password123",
    )
    user.is_service_account = True
    user.save(update_fields=["is_service_account"])
    user.groups.add(ingestion_group)
    return user


@pytest.fixture
def ingestion_api_client(ingestion_user):
    """An API client authenticated with a long-lived API key for the extractor
    service account (JWT → Session → ``Api-Key`` header, per the auth chain)."""
    from accounts.models import APIKey

    _, raw_key = APIKey.create(ingestion_user, name="extractor-key")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw_key}")
    return client


@pytest.fixture
def organization(db):
    from events.models import Organization

    return Organization.objects.create(
        name="Berlin Tech Meetups", description="Local tech meetups."
    )


@pytest.fixture
def event_source_approved(db, organization):
    """An approved, active source due for extraction (never fetched)."""
    from events.models import EventSource

    return EventSource.objects.create(
        organization=organization,
        url="https://example.com/meetups.ics",
        platform="homepage",
        is_approved=True,
        is_active=True,
    )