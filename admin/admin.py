"""Single registry for the terminschleuder backoffice.

All models are registered onto the custom ``terminschleuder_admin`` site
(declared in ``admin_site.py``). The ``ModelAdmin`` *classes* live next to
their models in each app's ``admin.py`` (idiomatic Django); here we only import
them and register. New, operator-facing capabilities that don't exist in the
per-app admins live here: the service-account flow (generate + show the app
secret once), API-key issuance (generate + show the raw key once), event
defaults, and the city active-toggle action.
"""

import hashlib
import secrets

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin
from django.contrib.auth.models import Group
from django.shortcuts import render

from accounts.admin import APIKeyAdmin as APIKeyAdminBase
from accounts.admin import CustomUserAdmin
from accounts.models import APIKey, User
from events.admin import CategoryAdmin, EventAdmin, OrganizerAdmin, VenueAdmin
from events.models import Category, Event, Organizer, Venue
from locations.admin import CityAdmin
from locations.models import City

from .admin_site import terminschleuder_admin
from .models import ServiceAccount


# ---------------------------------------------------------------------------
# Service / system accounts — generate an app secret and show it once.
# ---------------------------------------------------------------------------


class ServiceAccountForm(forms.ModelForm):
    """Add form for a service account — no password fields.

    The password (the "app secret") is generated in ``ServiceAccountAdmin.save_model``
    and shown once on the response page, mirroring ``APIKey.create``.
    """

    class Meta:
        model = ServiceAccount
        fields = ("username", "groups", "description", "is_active")


class ServiceAccountAdmin(admin.ModelAdmin):
    form = ServiceAccountForm
    list_display = ("username", "is_active", "description", "date_joined")
    list_filter = ("is_active", "groups")
    search_fields = ("username", "description")
    filter_horizontal = ("groups",)
    readonly_fields = ("is_service_account", "last_login", "date_joined")

    def get_queryset(self, request):
        # Belt-and-braces: the proxy manager already filters, but keep the
        # guarantee explicit in case the manager is swapped out.
        return super().get_queryset(request).filter(is_service_account=True)

    def save_model(self, request, obj, form, change):
        if not change:
            raw_secret = secrets.token_urlsafe(32)
            obj.set_password(raw_secret)
            obj.is_service_account = True
            obj.is_staff = False  # service accounts never log into the backoffice
            super().save_model(request, obj, form, change)
            request._generated_secret = raw_secret
        else:
            super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        secret = getattr(request, "_generated_secret", None)
        if secret:
            return render(
                request,
                "admin/accounts/serviceaccount/generated.html",
                {
                    "obj": obj,
                    "secret": secret,
                    "kind": "service account",
                    "opts": self.model._meta,
                },
            )
        return super().response_add(request, obj, post_url_continue)

    @admin.action(description="Regenerate app secret")
    def regenerate_secret(self, request, queryset):
        items = []
        for sa in queryset:
            raw = secrets.token_urlsafe(32)
            sa.set_password(raw)
            sa.save(update_fields=["password"])
            items.append((sa, raw))
        return render(
            request,
            "admin/accounts/serviceaccount/generated.html",
            {"items": items, "kind": "service account", "opts": queryset.model._meta},
        )

    actions = ["regenerate_secret"]


# ---------------------------------------------------------------------------
# API keys — issue a raw key and show it once.
# ---------------------------------------------------------------------------


class APIKeyForm(forms.ModelForm):
    class Meta:
        model = APIKey
        fields = ("name", "user", "expires_at", "revoked")


class APIKeyAdmin(APIKeyAdminBase):
    form = APIKeyForm
    readonly_fields = ("prefix", "hashed_key", "created")

    def save_model(self, request, obj, form, change):
        if not change:
            raw_key = secrets.token_urlsafe(32)
            obj.prefix = raw_key[:12]
            obj.hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
            super().save_model(request, obj, form, change)
            request._generated_secret = raw_key
        else:
            super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        secret = getattr(request, "_generated_secret", None)
        if secret:
            return render(
                request,
                "admin/accounts/serviceaccount/generated.html",
                {"obj": obj, "secret": secret, "kind": "API key", "opts": self.model._meta},
            )
        return super().response_add(request, obj, post_url_continue)


# ---------------------------------------------------------------------------
# Events — default the owner to the operator; protect auto timestamps.
# ---------------------------------------------------------------------------


class EventAdminEnhanced(EventAdmin):
    list_filter = tuple(EventAdmin.list_filter) + ("owner_group", "created_by")
    readonly_fields = ("created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# Cities — a quick active toggle.
# ---------------------------------------------------------------------------


class CityAdminEnhanced(CityAdmin):
    @admin.action(description="Toggle active")
    def toggle_active(self, request, queryset):
        updated = 0
        for city in queryset:
            city.is_active = not city.is_active
            city.save(update_fields=["is_active"])
            updated += 1
        self.message_user(request, f"Toggled active for {updated} city/cities.")

    actions = ["toggle_active"]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

terminschleuder_admin.register(User, CustomUserAdmin)
terminschleuder_admin.register(ServiceAccount, ServiceAccountAdmin)
terminschleuder_admin.register(Group, GroupAdmin)
terminschleuder_admin.register(APIKey, APIKeyAdmin)
terminschleuder_admin.register(City, CityAdminEnhanced)
terminschleuder_admin.register(Event, EventAdminEnhanced)
terminschleuder_admin.register(Venue, VenueAdmin)
terminschleuder_admin.register(Organizer, OrganizerAdmin)
terminschleuder_admin.register(Category, CategoryAdmin)