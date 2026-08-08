from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import City
from .serializers import CitySerializer


class CityViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only city catalog.

    - Search: ``?search=<text>`` matches the city name (prefix/contains).
    - Filter: ``?country_code=DE``.
    - Order:  ``?ordering=name`` (default) or ``?ordering=-population``.
    - Page size: ``?page_size=<n>`` (capped at 1000).
    - Full list (no pagination): ``/api/cities/all/`` — returns every active
      city in one response, for clients that want to cache the whole catalog
      (e.g. an offline pick-list / autocomplete).
    """

    queryset = City.objects.filter(is_active=True)
    serializer_class = CitySerializer
    search_fields = ["name"]
    filterset_fields = ["country_code"]
    ordering_fields = ["name", "population"]
    ordering = ["name"]

    @action(detail=False, methods=["get"], url_path="all")
    def all(self, request):
        """Return every active city in a single unpaginated response."""
        qs = self.filter_queryset(self.get_queryset())
        return Response(CitySerializer(qs, many=True, context={"request": request}).data)