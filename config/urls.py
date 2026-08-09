"""
URL configuration for the terminschleuder backend.

Routes:
    /                  — backoffice (custom AdminSite; anon -> /login/)
    /api/auth/         — register / login / logout / me  (accounts)
    /api/              — events, venues, organizations, categories  (events)
    /api/              — cities  (locations)
    /api/ingestion/    — extractor surface: due sources, runs, observations
    /api/schema/       — OpenAPI 3 schema (drf-spectacular) + Swagger UI / ReDoc
    /media/            — uploaded media (dev only; prod via reverse proxy)
    /admin/            — redirect to / (kept for old bookmarks)
"""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from admin.admin_site import terminschleuder_admin

urlpatterns = [
    # API first — the admin site at "/" has a permissive catch-all, so these
    # more specific includes must come above it.
    path("api/auth/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("api/ingestion/", include(("events.ingestion_urls", "events"), namespace="ingestion")),
    path("api/", include(("events.urls", "events"), namespace="events")),
    path("api/", include(("locations.urls", "locations"), namespace="locations")),
    # OpenAPI 3 schema + docs UI (read-only GET; demo client codegens types from this).
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(), name="swagger"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(), name="redoc"),
    # Old /admin/ bookmark -> root backoffice.
    path("admin/", RedirectView.as_view(url="/", permanent=False)),
    # Backoffice at the root.
    path("", terminschleuder_admin.urls),
]

# Serve uploaded media (event hero images) in development. In production the
# reverse proxy serves /media/ from the media volume.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)