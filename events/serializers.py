from django.contrib.auth.models import Group
from django.contrib.gis.geos import Point
from rest_framework import serializers

from .models import Category, Event, Organizer, Venue


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug")
        read_only_fields = ("id", "slug")


class VenueSerializer(serializers.ModelSerializer):
    # Output the location as latitude/longitude.
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = Venue
        fields = ("id", "name", "address", "city", "latitude", "longitude", "capacity")
        read_only_fields = ("id",)

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None

    def create(self, validated_data):
        lat = self.initial_data.get("latitude")
        lon = self.initial_data.get("longitude")
        venue = super().create(validated_data)
        self._apply_location(venue, lat, lon)
        return venue

    def update(self, instance, validated_data):
        lat = self.initial_data.get("latitude")
        lon = self.initial_data.get("longitude")
        instance = super().update(instance, validated_data)
        self._apply_location(instance, lat, lon)
        return instance

    @staticmethod
    def _apply_location(venue, lat, lon):
        if lat not in (None, "") and lon not in (None, ""):
            venue.location = Point(float(lon), float(lat), srid=4326)
            venue.save(update_fields=["location"])


class OrganizerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organizer
        fields = ("id", "name", "description", "website", "owner")
        read_only_fields = ("id",)


class EventSerializer(serializers.ModelSerializer):
    # Nested read representations.
    categories = CategorySerializer(many=True, read_only=True)
    venue = VenueSerializer(read_only=True)
    organizer = OrganizerSerializer(read_only=True)

    # Write-only handles for create/update by id.
    category_ids = serializers.PrimaryKeyRelatedField(
        source="categories",
        many=True,
        queryset=Category.objects.all(),
        write_only=True,
        required=False,
    )
    venue_id = serializers.PrimaryKeyRelatedField(
        source="venue",
        queryset=Venue.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    organizer_id = serializers.PrimaryKeyRelatedField(
        source="organizer",
        queryset=Organizer.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    owner_group_id = serializers.PrimaryKeyRelatedField(
        source="owner_group",
        queryset=Group.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    # Location input (write-only); output added in to_representation.
    latitude = serializers.FloatField(write_only=True, required=False, allow_null=True)
    longitude = serializers.FloatField(write_only=True, required=False, allow_null=True)

    # Distance from the proximity query point (km), when annotated.
    distance = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = (
            "id",
            "title",
            "description",
            "starts_at",
            "ends_at",
            "venue",
            "organizer",
            "categories",
            "capacity",
            "created_by",
            "created_at",
            "updated_at",
            "owner_group_id",
            "distance",
            # write-only
            "category_ids",
            "venue_id",
            "organizer_id",
            "latitude",
            "longitude",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    def get_distance(self, obj):
        distance = getattr(obj, "distance", None)
        if distance is None:
            return None
        # ``distance`` is a django.contrib.gis.measure.Distance (metres for geography).
        return round(float(distance.km), 2)

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep["latitude"] = instance.location.y if instance.location else None
        rep["longitude"] = instance.location.x if instance.location else None
        return rep

    def _location_from_data(self, validated_data, venue):
        """Resolve the event location from explicit coords or the venue."""
        lat = self.initial_data.get("latitude")
        lon = self.initial_data.get("longitude")
        if lat not in (None, "") and lon not in (None, ""):
            return Point(float(lon), float(lat), srid=4326)
        if venue is not None and venue.location is not None:
            return venue.location
        return None

    def create(self, validated_data):
        request = self.context.get("request")
        venue = validated_data.get("venue")
        validated_data["location"] = self._location_from_data(validated_data, venue)
        # ``latitude``/``longitude`` are serializer-only inputs (no model field);
        # remove them so super().create doesn't pass them to Event(**…).
        validated_data.pop("latitude", None)
        validated_data.pop("longitude", None)
        event = super().create(validated_data)
        if request and getattr(request, "user", None) and request.user.is_authenticated:
            event.created_by = request.user
            event.save(update_fields=["created_by"])
        return event

    def update(self, instance, validated_data):
        venue = validated_data.get("venue", instance.venue)
        # Only overwrite location if explicit coords were supplied.
        lat = self.initial_data.get("latitude")
        lon = self.initial_data.get("longitude")
        if lat not in (None, "") and lon not in (None, ""):
            validated_data["location"] = Point(float(lon), float(lat), srid=4326)
        elif "venue" in validated_data and venue is not None and venue.location is not None:
            validated_data.setdefault("location", venue.location)
        validated_data.pop("latitude", None)
        validated_data.pop("longitude", None)
        return super().update(instance, validated_data)