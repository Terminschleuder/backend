"""Serializers for the extractor-facing ingestion API.

These back ``/api/ingestion/`` — the surface an external extraction system uses
to discover due sources, report ingestion runs, and submit untrusted event
observations. They are deliberately narrower than the admin serializers: the
extractor may report what it found, but it can never set lifecycle/provenance
fields on a canonical ``Event`` directly.
"""

from django.contrib.gis.geos import Point
from rest_framework import serializers

from .models import Event, EventObservation, EventSource, IngestionRun, Organization


class _OrganizationMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name", "slug")
        read_only_fields = fields


class DueSourceSerializer(serializers.ModelSerializer):
    """A source eligible for extraction (approved + active + due).

    Read-only; this is the extractor's work queue.
    """

    organization = _OrganizationMiniSerializer(read_only=True)

    class Meta:
        model = EventSource
        fields = (
            "id",
            "organization",
            "url",
            "platform",
            "fetch_interval_minutes",
            "last_fetched_at",
            "next_due_at",
        )
        read_only_fields = fields


class IngestionRunSerializer(serializers.ModelSerializer):
    """Report an ingestion run.

    On create, ``status`` defaults to ``running`` and ``reported_by`` is set by
    the view to the calling service account. The extractor later PATCHes the run
    to ``succeeded`` / ``failed`` with ``finished_at`` / ``events_found`` /
    ``error_message``.
    """

    class Meta:
        model = IngestionRun
        fields = (
            "id",
            "source",
            "started_at",
            "finished_at",
            "status",
            "events_found",
            "events_promoted",
            "error_message",
            "created_at",
        )
        read_only_fields = ("id", "events_promoted", "created_at")
        # ``started_at`` has no model default (it's NOT NULL), but the view's
        # ``perform_create`` stamps ``now`` when the extractor omits it — so the
        # serializer must treat it as optional or validation rejects the call.
        extra_kwargs = {"started_at": {"required": False}}


class EventObservationSerializer(serializers.ModelSerializer):
    """Full read of an observation (listing / admin / retrieval)."""

    class Meta:
        model = EventObservation
        fields = (
            "id",
            "source",
            "run",
            "status",
            "title",
            "description",
            "starts_at",
            "ends_at",
            "url",
            "platform",
            "attendance_mode",
            "event_type",
            "venue_name",
            "venue_address",
            "venue_city",
            "latitude",
            "longitude",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None


class EventObservationSubmitSerializer(serializers.ModelSerializer):
    """The extractor's submit payload for a single observation.

    ``source`` is required (which source the observation came from); ``run`` is
    optional (set when reporting inside a run). ``status`` is forced to
    ``pending`` — the extractor can never self-promote. ``latitude`` /
    ``longitude`` are write-only and stored as ``location``.
    """

    latitude = serializers.FloatField(write_only=True, required=False, allow_null=True)
    longitude = serializers.FloatField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = EventObservation
        fields = (
            "id",
            "source",
            "run",
            "status",
            "raw_payload",
            "title",
            "description",
            "starts_at",
            "ends_at",
            "url",
            "platform",
            "attendance_mode",
            "event_type",
            "venue_name",
            "venue_address",
            "venue_city",
            "latitude",
            "longitude",
        )
        read_only_fields = ("id",)

    def create(self, validated_data):
        # Observations always enter as pending; ignore any body status.
        validated_data["status"] = EventObservation.Status.PENDING
        lat = self.initial_data.get("latitude")
        lon = self.initial_data.get("longitude")
        if lat not in (None, "") and lon not in (None, ""):
            validated_data["location"] = Point(float(lon), float(lat), srid=4326)
        validated_data.pop("latitude", None)
        validated_data.pop("longitude", None)
        return super().create(validated_data)


class EventObservationBulkSubmitSerializer(serializers.Serializer):
    """Bulk submit: a list of observation payloads (created transactionally)."""

    observations = EventObservationSubmitSerializer(many=True)

    def create(self, validated_data):
        from django.db import transaction

        created = []
        # Each item is an EventObservationSubmitSerializer child's validated_data:
        # ``source`` / ``run`` are already resolved to model instances, and
        # ``latitude`` / ``longitude`` are floats. Create directly, reusing the
        # same lat/lon → location and status=pending rules as the single submit.
        with transaction.atomic():
            for payload in validated_data["observations"]:
                lat = payload.pop("latitude", None)
                lon = payload.pop("longitude", None)
                payload["status"] = EventObservation.Status.PENDING
                if lat not in (None, "") and lon not in (None, ""):
                    payload["location"] = Point(float(lon), float(lat), srid=4326)
                created.append(EventObservation.objects.create(**payload))
        return created