from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import APIKey, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Admin for our custom user, reusing Django's full UserAdmin."""

    list_display = UserAdmin.list_display + ("is_service_account",)
    list_filter = UserAdmin.list_filter + ("is_service_account",)
    fieldsets = UserAdmin.fieldsets + (
        ("Service account", {"fields": ("is_service_account", "description")}),
    )


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "prefix", "user", "created", "revoked", "expires_at")
    list_filter = ("revoked",)
    search_fields = ("name", "prefix", "user__username")
    readonly_fields = ("prefix", "hashed_key", "created")