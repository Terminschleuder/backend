from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from locations.models import City

from .filters import EventFilter
from .models import Category, Event, Organization, Venue
from .permissions import IsOwnerOrGroupOrReadOnly
from .serializers import (
    CategorySerializer,
    EventSerializer,
    OrganizationPublicSerializer,
    VenueSerializer,
)


def resolve_proximity(near_city, lat, lon, radius_km):
    """Resolve proximity query params to ``(point, radius_km)``.

    Accepts either ``near_city=<slug>`` (resolved via the City gazetteer to its
    centroid + default radius) **or** ``lat``/``lon``/``radius_km`` (all three
    together). ``radius_km`` overrides a city's default radius when used with
    ``near_city``. Returns ``(None, None)`` when no proximity params are given.
    Raises ``ValidationError`` on bad input.
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


def visible_events(user):
    """The events a user is allowed to see in the catalog.

    - Anonymous: published events only.
    - Operators (``events.change_event`` or staff): everything.
    - Other authenticated users: published events, plus their own drafts and
      drafts co-owned by one of their groups (so an owner can retrieve a draft
      they created).
    """
    qs = Event.objects.all()
    if not (user and user.is_authenticated):
        qs = qs.filter(status=Event.Status.PUBLISHED)
    elif user.has_perm("events.change_event") or user.is_staff:
        pass  # operators see the full lifecycle
    else:
        groups = user.groups.all()
        qs = qs.filter(
            Q(status=Event.Status.PUBLISHED)
            | Q(created_by=user)
            | Q(owner_group__in=groups)
        )
    return qs


def apply_proximity(qs, params):
    """Apply the proximity filter/annotation to ``qs`` from ``params`` (a
    ``QueryDict``-like mapping). Returns the (possibly unchanged) queryset.

    Online events are excluded from proximity results even if they carry a
    location (they're not "near" anywhere in the physical sense); hybrid events
    keep a physical presence and stay in.
    """
    point, radius = resolve_proximity(
        params.get("near_city"),
        params.get("lat"),
        params.get("lon"),
        params.get("radius_km"),
    )
    if point is not None:
        qs = qs.exclude(attendance_mode=Event.AttendanceMode.ONLINE)
        qs = qs.filter(location__distance_lte=(point, D(km=radius)))
        qs = qs.annotate(distance=Distance("location", point))
        qs = qs.order_by("distance")
    return qs


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    search_fields = ["name"]


class VenueViewSet(viewsets.ModelViewSet):
    queryset = Venue.objects.all()
    serializer_class = VenueSerializer
    search_fields = ["name", "city"]
    filterset_fields = ["city"]


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """Public, read-only organization catalog.

    Only active organizations are listed. An organization's events are available
    via the ``/events/`` detail action (published only, with proximity support).
    """

    queryset = Organization.objects.filter(is_active=True)
    serializer_class = OrganizationPublicSerializer
    lookup_field = "slug"
    search_fields = ["name", "description"]
    ordering = ["name"]

    @action(detail=True, url_path="events", methods=["get"])
    def events(self, request, slug=None):
        organization = self.get_object()
        qs = visible_events(request.user).filter(organization=organization)
        qs = qs.select_related("venue", "organization", "source", "promoted_from", "owner_group")
        qs = qs.prefetch_related("categories")
        qs = apply_proximity(qs, request.query_params)

        # Paginate manually (the @action bypasses the viewset's list pipeline).
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = EventSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        serializer = EventSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)


class EventViewSet(viewsets.ModelViewSet):
    """List, create, retrieve, update and destroy events.

    - Filter: ``?category=<id>&category__slug=<slug>&city=<city>&organization=<id>&
      organization_slug=<slug>&event_type=<…>&attendance_mode=<…>&status=<…>&
      starts_at_after=&starts_at_before=``
    - Search: ``?search=<text>`` matches title and description.
    - Order:  ``?ordering=starts_at`` (or ``-starts_at``).
    - Proximity: ``?lat=<lat>&lon=<lon>&radius_km=<km>`` (or ``?near_city=<slug>``)
      returns events within the radius, each annotated with a ``distance`` (km),
      ordered nearest-first. **Online events are excluded** from proximity.
    - Lifecycle actions: ``POST /api/events/<id>/publish/``,
      ``/cancel/``, ``/archive/``, ``/revert_to_draft/`` (owner / ``owner_group``
      member / holder of ``events.change_event``).
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
    ordering_fields = [
        "starts_at", "created_at", "distance",
        "status", "event_type", "attendance_mode", "published_at",
    ]

    def get_queryset(self):
        qs = visible_events(self.request.user)
        qs = qs.select_related("venue", "organization", "source", "promoted_from", "owner_group")
        qs = qs.prefetch_related("categories")
        qs = apply_proximity(qs, self.request.query_params)
        return qs

    # --- Lifecycle actions --------------------------------------------------

    def _set_lifecycle(self, request, status, timestamp_field=None):
        """Shared helper for the lifecycle actions.

        ``get_object`` runs the object-level permission check (owner /
        ``owner_group`` / ``events.change_event``), so only authorized callers
        proceed.
        """
        event = self.get_object()
        event.status = status
        if timestamp_field is not None:
            setattr(event, timestamp_field, timezone.now())
        event.save(update_fields=self._lifecycle_update_fields(timestamp_field))
        serializer = self.get_serializer(event)
        return Response(serializer.data)

    @staticmethod
    def _lifecycle_update_fields(timestamp_field):
        fields = ["status", "updated_at"]
        if timestamp_field is not None:
            fields.append(timestamp_field)
        return fields

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        return self._set_lifecycle(request, Event.Status.PUBLISHED, "published_at")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._set_lifecycle(request, Event.Status.CANCELLED, "cancelled_at")

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        return self._set_lifecycle(request, Event.Status.ARCHIVED)

    @action(detail=True, methods=["post"])
    def revert_to_draft(self, request, pk=None):
        return self._set_lifecycle(request, Event.Status.DRAFT)