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