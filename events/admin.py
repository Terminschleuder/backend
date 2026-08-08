from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import Category, Event, Organizer, Venue


class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


class VenueAdmin(GISModelAdmin):
    list_display = ("name", "city", "latitude", "longitude", "capacity")
    search_fields = ("name", "city")
    list_filter = ("city",)
    # `location` is edited via the PostGIS map widget (GISModelAdmin);
    # latitude/longitude are read-only views of the same point.
    readonly_fields = ("latitude", "longitude")

    # Not sortable: a geography point has no meaningful ordering.
    @admin.display(description="Latitude")
    def latitude(self, obj):
        return round(obj.location.y, 5) if obj.location else None

    @admin.display(description="Longitude")
    def longitude(self, obj):
        return round(obj.location.x, 5) if obj.location else None


class OrganizerAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "website")
    search_fields = ("name",)


class EventAdmin(GISModelAdmin):
    list_display = ("title", "starts_at", "venue", "organizer", "capacity",
                    "latitude", "longitude")
    list_filter = ("categories", "venue", "organizer")
    search_fields = ("title", "description")
    date_hierarchy = "starts_at"
    autocomplete_fields = ("venue", "organizer")
    filter_horizontal = ("categories",)
    # `location` is edited via the PostGIS map widget (GISModelAdmin);
    # latitude/longitude are read-only views of the same point.
    readonly_fields = ("latitude", "longitude")

    @admin.display(description="Latitude")
    def latitude(self, obj):
        return round(obj.location.y, 5) if obj.location else None

    @admin.display(description="Longitude")
    def longitude(self, obj):
        return round(obj.location.x, 5) if obj.location else None