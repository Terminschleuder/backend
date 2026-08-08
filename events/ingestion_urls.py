"""URL routes for the extractor-facing ingestion API (``/api/ingestion/``)."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .ingestion_views import (
    DueSourceListView,
    EventObservationViewSet,
    IngestionRunViewSet,
)

app_name = "events"

router = DefaultRouter()
router.register("runs", IngestionRunViewSet, basename="ingestionruns")
router.register("observations", EventObservationViewSet, basename="eventobservations")

urlpatterns = [
    # The due-sources work queue (list only) — a plain APIView, not a viewset.
    path("sources/due/", DueSourceListView.as_view(), name="due-sources"),
    path("", include(router.urls)),
]