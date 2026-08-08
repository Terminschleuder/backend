import django_filters

from .models import Event


class EventFilter(django_filters.FilterSet):
    """Filter events by category, venue, city, organization, classification,
    lifecycle, and a date range.

    Examples:
        ?category=2               # by category id
        ?category__slug=tech      # by category slug
        ?city=Berlin
        ?organization=3          # by organization id
        ?organization_slug=berlin-tech-meetups
        ?event_type=meetup
        ?attendance_mode=physical
        ?status=published         # operator-only (anon still sees published)
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
    organization = django_filters.NumberFilter(field_name="organization_id")
    organization_slug = django_filters.CharFilter(
        field_name="organization__slug", lookup_expr="iexact"
    )
    event_type = django_filters.ChoiceFilter(choices=Event.EventType.choices)
    attendance_mode = django_filters.ChoiceFilter(choices=Event.AttendanceMode.choices)
    status = django_filters.ChoiceFilter(choices=Event.Status.choices)

    class Meta:
        model = Event
        fields = [
            "category", "category__slug", "venue", "city",
            "organization", "organization_slug",
            "event_type", "attendance_mode", "status",
        ]