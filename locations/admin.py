from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import City


class CityAdmin(GISModelAdmin):
    list_display = (
        "name",
        "country_code",
        "latitude",
        "longitude",
        "population",
        "default_radius_km",
        "is_active",
    )
    list_filter = ("country_code", "is_active")
    search_fields = ("name", "country", "slug")
    ordering = ("name",)
    # `location` is edited via the GIS map widget (provided by GISModelAdmin);
    # latitude/longitude are surfaced as read-only views of the same point.
    readonly_fields = ("slug", "latitude", "longitude")

    # Not sortable: a geography point has no meaningful ordering, and clicking
    # the column would ORDER BY location and error in PostGIS.
    @admin.display(description="Latitude")
    def latitude(self, obj):
        return round(obj.location.y, 5) if obj.location else None

    @admin.display(description="Longitude")
    def longitude(self, obj):
        return round(obj.location.x, 5) if obj.location else None