from rest_framework import serializers

from .models import City


class CitySerializer(serializers.ModelSerializer):
    """Read-only representation of a city, exposing its centroid as lat/lon."""

    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = City
        fields = (
            "id",
            "geoname_id",
            "name",
            "slug",
            "country",
            "country_code",
            "latitude",
            "longitude",
            "default_radius_km",
            "population",
            "timezone",
        )
        read_only_fields = fields

    def get_latitude(self, obj):
        return obj.location.y if obj.location else None

    def get_longitude(self, obj):
        return obj.location.x if obj.location else None