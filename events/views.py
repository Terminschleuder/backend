from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from rest_framework import permissions, viewsets
from rest_framework.exceptions import ValidationError

from locations.models import City

from .filters import EventFilter
from .models import Category, Event, Organizer, Venue
from .permissions import IsOwnerOrGroupOrReadOnly
from .serializers import (
    CategorySerializer,
    EventSerializer,
    OrganizerSerializer,
    VenueSerializer,
)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    search_fields = ["name"]


class VenueViewSet(viewsets.ModelViewSet):
    queryset = Venue.objects.all()
    serializer_class = VenueSerializer
    search_fields = ["name", "city"]
    filterset_fields = ["city"]


class OrganizerViewSet(viewsets.ModelViewSet):
    queryset = Organizer.objects.all()
    serializer_class = OrganizerSerializer
    search_fields = ["name"]


class EventViewSet(viewsets.ModelViewSet):
    """List, create, retrieve, update and destroy events.

    - Filter: ``?category=<id>&category__slug=<slug>&city=<city>&starts_at_after=&starts_at_before=``
    - Search: ``?search=<text>`` matches title and description.
    - Order:  ``?ordering=starts_at`` (or ``-starts_at``).
    - Proximity: ``?lat=<lat>&lon=<lon>&radius_km=<km>`` returns events whose
      location is within ``radius_km`` of the point, each annotated with a
      ``distance`` (km), ordered nearest-first.
    """

    # Class-level queryset lets the router derive the basename; get_queryset
    # below is what actually runs per request.
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [IsOwnerOrGroupOrReadOnly]
    filterset_class = EventFilter
    search_fields = ["title", "description"]
    # ``ordering`` is intentionally unset: DRF's OrderingFilter would otherwise
    # re-apply a default order (e.g. ``-starts_at``) and clobber the proximity
    # ``order_by("distance")``. Without a default the filter is a no-op unless
    # the client passes ``?ordering=``, and non-proximity requests use the
    # model's Meta.ordering (``-starts_at``).
    ordering_fields = ["starts_at", "created_at", "distance"]

    def get_queryset(self):
        qs = Event.objects.select_related("venue", "organizer", "owner_group")
        qs = qs.prefetch_related("categories")

        params = self.request.query_params
        lat = params.get("lat")
        lon = params.get("lon")
        radius_km = params.get("radius_km")
        near_city = params.get("near_city")

        point, radius = self._resolve_proximity(near_city, lat, lon, radius_km)
        if point is not None:
            qs = qs.filter(location__distance_lte=(point, D(km=radius)))
            qs = qs.annotate(distance=Distance("location", point))
            qs = qs.order_by("distance")
        return qs

    @staticmethod
    def _resolve_proximity(near_city, lat, lon, radius_km):
        """Resolve proximity query params to (point, radius_km).

        Accepts either ``near_city=<slug>`` (resolved via the City gazetteer to its
        centroid + default radius) **or** ``lat``/``lon``/``radius_km`` (all three
        together). ``radius_km`` overrides a city's default radius when used with
        ``near_city``. Returns ``(None, None)`` when no proximity params are given.
        """
        if near_city is not None:
            if lat is not None or lon is not None:
                raise ValidationError(
                    {"detail": "Use either near_city or lat/lon, not both."}
                )
            city = City.objects.filter(is_active=True, slug=near_city).first()
            if city is None or city.location is None:
                raise ValidationError({"detail": "Unknown city slug."})
            radius = float(city.default_radius_km)
            if radius_km is not None:
                try:
                    radius = float(radius_km)
                except (TypeError, ValueError):
                    raise ValidationError({"detail": "radius_km must be a number."})
            if radius < 0:
                raise ValidationError({"detail": "radius_km must be >= 0."})
            return city.location, radius

        if lat is not None or lon is not None or radius_km is not None:
            if lat is None or lon is None or radius_km is None:
                raise ValidationError(
                    {"detail": "lat, lon and radius_km must be provided together."}
                )
            try:
                point = Point(float(lon), float(lat), srid=4326)
                radius = float(radius_km)
            except (TypeError, ValueError):
                raise ValidationError({"detail": "lat, lon and radius_km must be numbers."})
            if radius < 0:
                raise ValidationError({"detail": "radius_km must be >= 0."})
            return point, radius

        return None, None