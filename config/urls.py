"""
URL configuration for the terminschleuder backend.

Routes:
    /admin/            — Django admin (backoffice)
    /api/auth/         — register / login / logout / me  (accounts)
    /api/              — events, venues, organizers, categories  (events)
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("api/", include(("events.urls", "events"), namespace="events")),
    path("api/", include(("locations.urls", "locations"), namespace="locations")),
]