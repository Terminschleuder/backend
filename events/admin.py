from django.contrib import admin

from .models import Category, Event, Organizer, Venue


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "capacity")
    search_fields = ("name", "city")
    list_filter = ("city",)


@admin.register(Organizer)
class OrganizerAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "website")
    search_fields = ("name",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "starts_at", "venue", "organizer", "capacity")
    list_filter = ("categories", "venue", "organizer")
    search_fields = ("title", "description")
    date_hierarchy = "starts_at"
    autocomplete_fields = ("venue", "organizer")
    filter_horizontal = ("categories",)