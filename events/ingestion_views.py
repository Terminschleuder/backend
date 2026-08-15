"""Extractor-facing ingestion API (mounted at ``/api/ingestion/``).

This is the surface an external extraction system uses to:

  * discover due sources        — ``GET /api/ingestion/sources/due/``
  * report ingestion runs       — ``POST /api/ingestion/runs/`` (+ ``PATCH``,
    and the ``/success/`` / ``/failure/`` thin actions)
  * submit event observations   — ``POST /api/ingestion/observations/``
    (+ ``POST /api/ingestion/observations/bulk/``)

Everything here is authenticated and gated by ``IsIngestionService`` (the
extractor is a service account in an ``ingestion`` group). Observations are
untrusted and always enter as ``pending``; promotion to a canonical event is an
operator action (admin), never done by the extractor.
"""

from datetime import timedelta
import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from .models import EventObservation, EventSource, IngestionRun
from .permissions import IsIngestionService
from .ingestion_serializers import (
    DueSourceSerializer,
    EventObservationBulkSubmitSerializer,
    EventObservationSerializer,
    EventObservationSubmitSerializer,
    IngestionRunSerializer,
)
from .reconciliation import reconcile_run

logger = logging.getLogger(__name__)


class DueSourceListView(ListAPIView):
    """``GET /api/ingestion/sources/due/`` — the extractor's work queue.

    Approved, active sources due for a fetch, ordered so never-fetched sources
    (``next_due_at`` is null) come first, then by soonest due time.
    """

    serializer_class = DueSourceSerializer
    permission_classes = [permissions.IsAuthenticated, IsIngestionService]
    ingestion_perms = {"GET": ["events.view_eventsource"]}

    def get_queryset(self):
        return (
            EventSource.due()
            .select_related("organization")
            .order_by(F("next_due_at").asc(nulls_first=True))
        )


class IngestionRunViewSet(viewsets.ModelViewSet):
    """Report ingestion runs.

    ``POST`` creates a run (defaults to ``running``, ``reported_by`` = caller);
    ``PATCH`` (or the ``/success/`` / ``/failure/`` actions) finishes it. Finishing
    a run also stamps its source's ``last_fetched_at`` / ``next_due_at`` schedule.
    """

    serializer_class = IngestionRunSerializer
    permission_classes = [permissions.IsAuthenticated, IsIngestionService]
    ingestion_perms = {
        "GET": ["events.view_ingestionrun"],
        "POST": ["events.add_ingestionrun"],
        "PATCH": ["events.change_ingestionrun"],
        "PUT": ["events.change_ingestionrun"],
        "success": ["events.change_ingestionrun"],
        "failure": ["events.change_ingestionrun"],
        "reconcile": ["events.change_ingestionrun"],
    }

    def get_queryset(self):
        return IngestionRun.objects.select_related("source", "reported_by")

    def perform_create(self, serializer):
        validated = serializer.validated_data
        validated.setdefault("status", IngestionRun.Status.RUNNING)
        if not validated.get("started_at"):
            validated["started_at"] = timezone.now()
        serializer.save(reported_by=self.request.user)

    def perform_update(self, serializer):
        run = serializer.save()
        if run.status in (IngestionRun.Status.SUCCEEDED, IngestionRun.Status.FAILED):
            if run.finished_at is None:
                run.finished_at = timezone.now()
                run.save(update_fields=["finished_at"])
            self._touch_source_schedule(run)

    @action(detail=True, methods=["post"])
    def success(self, request, pk=None):
        """``POST /api/ingestion/runs/<id>/success/`` — mark the run succeeded.

        After the run is SUCCEEDED and the source schedule is stamped, run
        run-over-run reconciliation (the observations were submitted — and
        committed — in a prior request, so they exist now). Reconciliation is
        best-effort: a failure here is logged but never flips the run back to
        FAILED (the run already succeeded).
        """
        run = self.get_object()
        run.status = IngestionRun.Status.SUCCEEDED
        run.finished_at = timezone.now()
        run.events_found = int(request.data.get("events_found", run.events_found))
        run.save(update_fields=["status", "finished_at", "events_found"])
        self._touch_source_schedule(run)

        try:
            with transaction.atomic():
                reconcile_run(run)
        except Exception:  # noqa: BLE001 — reconciliation must never fail the run
            logger.exception("Reconciliation failed for run %s", run.pk)

        return Response(IngestionRunSerializer(run).data)

    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        """``POST /api/ingestion/runs/<id>/reconcile/`` — re-run reconciliation.

        Idempotent-ish: re-classifies against the same previous run. Useful to
        re-run after a reconciliation bug fix. The run status is not changed.
        """
        run = self.get_object()
        try:
            with transaction.atomic():
                reconcile_run(run)
        except Exception:  # noqa: BLE001
            logger.exception("Manual reconcile failed for run %s", run.pk)
            return Response({"error": "reconciliation failed"}, status=500)
        return Response(IngestionRunSerializer(run).data)

    @action(detail=True, methods=["post"])
    def failure(self, request, pk=None):
        """``POST /api/ingestion/runs/<id>/failure/`` — mark the run failed."""
        run = self.get_object()
        run.status = IngestionRun.Status.FAILED
        run.finished_at = timezone.now()
        run.error_message = request.data.get("error_message", run.error_message or "")
        run.save(update_fields=["status", "finished_at", "error_message"])
        self._touch_source_schedule(run)
        return Response(IngestionRunSerializer(run).data)

    @staticmethod
    def _touch_source_schedule(run):
        source = run.source
        source.last_fetched_at = timezone.now()
        source.next_due_at = timezone.now() + timedelta(
            minutes=source.fetch_interval_minutes
        )
        source.save(update_fields=["last_fetched_at", "next_due_at", "updated_at"])


class EventObservationViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Submit and read untrusted event observations.

    ``POST`` submits one observation (forced ``status=pending``); ``bulk/``
    submits a list transactionally. List/retrieve let the extractor confirm what
    it submitted. Reviewing/promoting is an operator action in the admin.
    """

    serializer_class = EventObservationSerializer
    permission_classes = [permissions.IsAuthenticated, IsIngestionService]
    ingestion_perms = {
        "GET": ["events.view_eventobservation"],
        "POST": ["events.add_eventobservation"],
        "bulk": ["events.add_eventobservation"],
    }
    filterset_fields = ["source", "run", "status", "lifecycle", "event_key"]

    def get_queryset(self):
        return EventObservation.objects.select_related("source", "run", "reviewed_by")

    def get_serializer_class(self):
        if self.action == "create":
            return EventObservationSubmitSerializer
        return EventObservationSerializer

    def create(self, request, *args, **kwargs):
        # Submit via the narrow submit serializer; respond with the full read
        # serializer so the caller sees the resolved location / status.
        serializer = EventObservationSubmitSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        observation = serializer.save()
        out = EventObservationSerializer(observation, context={"request": request})
        return Response(out.data, status=201)

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk(self, request):
        serializer = EventObservationBulkSubmitSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        created = serializer.save()
        out = EventObservationSerializer(created, many=True, context={"request": request})
        return Response(out.data, status=201)