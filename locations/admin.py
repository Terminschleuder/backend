from django.contrib import admin

from .models import City


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "country_code", "population", "default_radius_km", "is_active")
    list_filter = ("country_code", "is_active")
    search_fields = ("name", "country", "slug")
    ordering = ("name",)
    readonly_fields = ("slug",)