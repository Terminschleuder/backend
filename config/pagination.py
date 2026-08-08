from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Page-number pagination with an optional, capped client page size.

    Defaults to 25 per page. Clients may request a larger page with
    ``?page_size=<n>`` (capped at ``max_page_size``), useful for fetching a
    large batch of a lightweight catalog like cities in fewer round-trips.
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 1000