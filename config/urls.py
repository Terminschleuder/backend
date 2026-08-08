"""
URL configuration for the terminschleuder backend.

Routes:
    /                  — backoffice (custom AdminSite; anon -> /login/)
    /api/auth/         — register / login / logout / me  (accounts)
    /api/              — events, venues, organizers, categories  (events)
    /api/              — cities  (locations)
    /admin/            — redirect to / (kept for old bookmarks)
"""

from django.urls import include, path
from django.views.generic import RedirectView

from admin.admin_site import terminschleuder_admin

urlpatterns = [
    # API first — the admin site at "/" has a permissive catch-all, so these
    # more specific includes must come above it.
    path("api/auth/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("api/", include(("events.urls", "events"), namespace="events")),
    path("api/", include(("locations.urls", "locations"), namespace="locations")),
    # Old /admin/ bookmark -> root backoffice.
    path("admin/", RedirectView.as_view(url="/", permanent=False)),
    # Backoffice at the root.
    path("", terminschleuder_admin.urls),
]