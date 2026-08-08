from rest_framework import viewsets

from .models import City
from .serializers import CitySerializer


class CityViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only city catalog.

    - Search: ``?search=<text>`` matches the city name (prefix/contains).
    - Filter: ``?country_code=DE``.
    - Order:  ``?ordering=name`` (default) or ``?ordering=-population``.
    """

    queryset = City.objects.filter(is_active=True)
    serializer_class = CitySerializer
    search_fields = ["name"]
    filterset_fields = ["country_code"]
    ordering_fields = ["name", "population"]
    ordering = ["name"]