"""
URL configuration for the terminschleuder backend.

Routes:
    /                  — public marketing landing page (no auth)
    /admin/             — backoffice (custom AdminSite; anon -> /admin/login/)
    /api/auth/          — register / login / logout / me  (accounts)
    /api/              — events, venues, organizations, categories  (events)
    /api/              — cities  (locations)
    /api/ingestion/    — extractor surface: due sources, runs, observations
    /api/schema/       — OpenAPI 3 schema (drf-spectacular) + Swagger UI / ReDoc
    /media/            — uploaded media (served by Django when SERVE_MEDIA, default on)

The backoffice is mounted at ``/admin/`` (not ``/``) so the admin's built-in
catch-all view is confined to ``/admin/...`` and never swallows ``/media/...``
(which previously made anon hero-image requests redirect to the login page).
The public landing page at ``/`` is a plain ``TemplateView`` with no catch-all,
so unknown paths 404 instead of redirecting to login.
"""

from django.conf import settings
from django.urls import include, path
from django.views.generic import TemplateView
from django.views.static import serve
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from admin.admin_site import terminschleuder_admin

urlpatterns = [
    # Public API (read-only + auth + ingestion) + OpenAPI docs.
    path("api/auth/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("api/ingestion/", include(("events.ingestion_urls", "events"), namespace="ingestion")),
    path("api/", include(("events.urls", "events"), namespace="events")),
    path("api/", include(("locations.urls", "locations"), namespace="locations")),
    # OpenAPI 3 schema + docs UI (read-only GET; demo client codegens types from this).
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(), name="swagger"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(), name="redoc"),
]

# Serve uploaded media (event hero images). Controlled by SERVE_MEDIA (default:
# on) — the pure-container deployment has no reverse proxy, so Django serves
# the media volume itself; set SERVE_MEDIA=False when a proxy/CDN takes over.
# Listed before the admin and landing routes so /media/... is matched here, not
# by a catch-all.
#
# NOTE: this wires django.views.static.serve directly instead of the
# django.conf.urls.static.static() helper — that helper silently returns no
# patterns unless DEBUG=True, which would 404 every hero image in production.
if settings.SERVE_MEDIA:
    urlpatterns += [
        path("media/<path:path>", serve, {"document_root": settings.MEDIA_ROOT}),
    ]

urlpatterns += [
    # Backoffice (custom AdminSite). Its built-in catch-all is now confined to
    # /admin/... and cannot shadow /media/ or the API.
    path("admin/", terminschleuder_admin.urls),
    # Public marketing landing page (no auth, no catch-all).
    path("", TemplateView.as_view(template_name="landing.html"), name="landing"),
]