from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.db.models import F
from django.utils.html import format_html
from django.utils import timezone

from .models import (
    Category,
    Event,
    EventObservation,
    EventSource,
    IngestionRun,
    Organization,
    Venue,
)


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


class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "website", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}


class EventSourceAdmin(admin.ModelAdmin):
    list_display = (
        "url", "organization", "platform",
        "is_approved", "is_active", "last_fetched_at", "next_due_at",
    )
    list_filter = ("is_approved", "is_active", "platform")
    search_fields = ("url", "organization__name", "platform")
    autocomplete_fields = ("organization",)
    readonly_fields = ("last_fetched_at", "next_due_at", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Approve (eligible for extraction)")
    def approve(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f"Approved {updated} source(s).")

    @admin.action(description="Disable (pause extraction)")
    def disable(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"Disabled {updated} source(s).")

    @admin.action(description="Revoke approval")
    def revoke(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f"Revoked approval for {updated} source(s).")

    actions = ["approve", "disable", "revoke"]


class IngestionRunAdmin(admin.ModelAdmin):
    """Runs are reported by the extractor, not hand-edited."""

    list_display = (
        "id", "source", "started_at", "finished_at", "status",
        "events_found", "events_promoted",
    )
    list_filter = ("status", "source__organization")
    search_fields = ("source__url", "error_message")
    readonly_fields = (
        "source", "started_at", "finished_at", "status",
        "events_found", "events_promoted", "error_message",
        "reported_by", "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EventObservationAdmin(admin.ModelAdmin):
    list_display = (
        "title", "starts_at", "source", "status",
        "attendance_mode", "event_type", "reviewed_by", "reviewed_at",
    )
    list_filter = (
        "status", "attendance_mode", "event_type", "source__organization",
    )
    search_fields = ("title", "venue_name", "venue_address", "venue_city", "url")
    readonly_fields = ("created_at", "updated_at")
    actions = ["accept", "reject", "promote"]

    @admin.action(description="Accept observation")
    def accept(self, request, queryset):
        updated = queryset.filter(
            status=EventObservation.Status.PENDING
        ).update(
            status=EventObservation.Status.ACCEPTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"Accepted {updated} observation(s).")

    @admin.action(description="Reject observation")
    def reject(self, request, queryset):
        updated = queryset.filter(
            status=EventObservation.Status.PENDING
        ).update(
            status=EventObservation.Status.REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"Rejected {updated} observation(s).")

    @admin.action(description="Promote to canonical event (draft)")
    def promote(self, request, queryset):
        """Promote accepted/pending observations into canonical draft events.

        Each promoted observation becomes a draft ``Event`` with full
        provenance (``source``, ``promoted_from``, copied ``original_url`` /
        ``original_platform`` / location / classification / organization), then
        is marked ``promoted``. Requires ``events.add_event``.
        """
        if not request.user.has_perm("events.add_event"):
            self.message_user(
                request,
                "You need the 'events.add_event' permission to promote observations.",
                level="ERROR",
            )
            return

        promoted = 0
        for obs in queryset.exclude(status=EventObservation.Status.PROMOTED):
            venue = None
            if obs.venue_name:
                venue, _ = Venue.objects.get_or_create(
                    name=obs.venue_name,
                    defaults={"address": obs.venue_address, "city": obs.venue_city},
                )
            Event.objects.create(
                title=obs.title,
                description=obs.description,
                starts_at=obs.starts_at,
                ends_at=obs.ends_at,
                venue=venue,
                organization=obs.source.organization_id and obs.source.organization,
                attendance_mode=obs.attendance_mode,
                event_type=obs.event_type,
                original_url=obs.url,
                original_platform=obs.platform,
                location=obs.location,
                source=obs.source,
                promoted_from=obs,
                status=Event.Status.DRAFT,
                created_by=request.user,
            )
            obs.status = EventObservation.Status.PROMOTED
            obs.reviewed_by = request.user
            obs.reviewed_at = timezone.now()
            obs.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
            if obs.run_id:
                IngestionRun.objects.filter(pk=obs.run_id).update(
                    events_promoted=F("events_promoted") + 1
                )
            promoted += 1
        self.message_user(
            request,
            f"Promoted {promoted} observation(s) to draft event(s).",
        )


class EventAdmin(GISModelAdmin):
    list_display = (
        "hero_image_thumbnail", "title", "starts_at", "venue", "organization", "status",
        "event_type", "attendance_mode", "capacity", "latitude", "longitude",
    )
    list_filter = (
        "categories", "venue", "organization",
        "status", "event_type", "attendance_mode",
    )
    search_fields = ("title", "description", "original_url")
    date_hierarchy = "starts_at"
    autocomplete_fields = ("venue", "organization")
    filter_horizontal = ("categories",)
    # `location` is edited via the PostGIS map widget (GISModelAdmin);
    # latitude/longitude are read-only views of the same point. Provenance and
    # lifecycle timestamps are operator-set via actions, not the change form.
    # `hero_image` is editable here via the admin file widget.
    readonly_fields = (
        "latitude", "longitude",
        "published_at", "cancelled_at", "promoted_from", "source",
    )
    actions = ["publish", "cancel", "archive", "revert_to_draft"]

    @admin.display(description="Hero")
    def hero_image_thumbnail(self, obj):
        if obj.hero_image:
            return format_html(
                '<img src="{}" width="80" height="32" '
                'style="object-fit:cover;border-radius:4px" alt="hero">',
                obj.hero_image.url,
            )
        return "—"

    @admin.display(description="Latitude")
    def latitude(self, obj):
        return round(obj.location.y, 5) if obj.location else None

    @admin.display(description="Longitude")
    def longitude(self, obj):
        return round(obj.location.x, 5) if obj.location else None

    @admin.action(description="Publish")
    def publish(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(
            status=Event.Status.PUBLISHED, published_at=now
        )
        self.message_user(request, f"Published {updated} event(s).")

    @admin.action(description="Cancel")
    def cancel(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(
            status=Event.Status.CANCELLED, cancelled_at=now
        )
        self.message_user(request, f"Cancelled {updated} event(s).")

    @admin.action(description="Archive")
    def archive(self, request, queryset):
        updated = queryset.update(status=Event.Status.ARCHIVED)
        self.message_user(request, f"Archived {updated} event(s).")

    @admin.action(description="Revert to draft")
    def revert_to_draft(self, request, queryset):
        updated = queryset.update(status=Event.Status.DRAFT)
        self.message_user(request, f"Reverted {updated} event(s) to draft.")