import django_filters

from .models import Event


class EventFilter(django_filters.FilterSet):
    """Filter events by category, venue, city, and a date range.

    Examples:
        ?category=2          # by category id
        ?category__slug=tech # by category slug
        ?city=Berlin
        ?starts_at_after=2026-01-01
        ?starts_at_before=2026-12-31
    """

    starts_at_after = django_filters.DateTimeFilter(
        field_name="starts_at", lookup_expr="gte"
    )
    starts_at_before = django_filters.DateTimeFilter(
        field_name="starts_at", lookup_expr="lte"
    )
    city = django_filters.CharFilter(field_name="venue__city", lookup_expr="iexact")
    category = django_filters.NumberFilter(field_name="categories__id")
    category__slug = django_filters.CharFilter(field_name="categories__slug")

    class Meta:
        model = Event
        fields = ["category", "category__slug", "venue", "city"]