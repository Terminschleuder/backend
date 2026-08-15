"""Tests for the extractor-facing ingestion API (``/api/ingestion/``).

Covers: due-sources auth + content, run reporting + source schedule stamping,
observation submission (status forced pending, lat/lon → location), bulk
submit, the success/failure thin actions, and permission gating. Promotion and
canonical-event lifecycle are exercised in ``admin/tests.py``.
"""

from datetime import timedelta

from django.utils import timezone

from .models import EventObservation, EventSource, IngestionRun


def _observation_payload(source, **overrides):
    base = {
        "source": source.id,
        "title": "Rust Meetup",
        "starts_at": (timezone.now() + timedelta(days=3)).isoformat(),
        "url": "https://example.com/rust",
        "platform": "meetup",
        "event_key": "k-rust",
        "latitude": 52.52,
        "longitude": 13.405,
    }
    base.update(overrides)
    return base


# --- Due sources ------------------------------------------------------------


def test_due_sources_requires_auth(db, api_client):
    # Anonymous access is forbidden (not part of the public catalog).
    assert api_client.get("/api/ingestion/sources/due/").status_code == 401


def test_due_sources_returns_approved_active_due(
    db, ingestion_api_client, organization
):
    approved_due = EventSource.objects.create(
        organization=organization, url="https://1", is_approved=True
    )
    EventSource.objects.create(
        organization=organization, url="https://2", is_approved=True,
        next_due_at=timezone.now() + timedelta(hours=1),  # not due yet
    )
    EventSource.objects.create(
        organization=organization, url="https://3", is_approved=False
    )

    response = ingestion_api_client.get("/api/ingestion/sources/due/")
    assert response.status_code == 200
    results = response.data["results"] if "results" in response.data else response.data
    ids = {i["id"] for i in results}
    assert approved_due.id in ids
    # The due list carries the nested organization (extractor needs the owner).
    item = next(i for i in results if i["id"] == approved_due.id)
    assert item["organization"]["slug"] == organization.slug
    assert set(item.keys()) == {
        "id", "organization", "url", "platform",
        "fetch_interval_minutes", "last_fetched_at", "next_due_at",
    }


# --- Runs -------------------------------------------------------------------


def test_report_run_creates_running_and_stamps_source(
    db, ingestion_api_client, event_source_approved, ingestion_user
):
    payload = {"source": event_source_approved.id}
    response = ingestion_api_client.post("/api/ingestion/runs/", payload, format="json")
    assert response.status_code == 201
    run = IngestionRun.objects.get(id=response.data["id"])
    assert run.status == IngestionRun.Status.RUNNING
    assert run.reported_by_id == ingestion_user.id
    assert run.started_at is not None


def test_finish_run_success_updates_source_schedule(
    db, ingestion_api_client, event_source_approved
):
    run = IngestionRun.objects.create(
        source=event_source_approved, started_at=timezone.now(),
        status=IngestionRun.Status.RUNNING,
    )
    response = ingestion_api_client.post(
        f"/api/ingestion/runs/{run.id}/success/",
        {"events_found": 5}, format="json",
    )
    assert response.status_code == 200
    run.refresh_from_db()
    assert run.status == IngestionRun.Status.SUCCEEDED
    assert run.events_found == 5
    assert run.finished_at is not None

    event_source_approved.refresh_from_db()
    assert event_source_approved.last_fetched_at is not None
    assert event_source_approved.next_due_at is not None
    # next_due_at ≈ now + fetch_interval_minutes (default 60).
    delta = event_source_approved.next_due_at - event_source_approved.last_fetched_at
    assert timedelta(minutes=59) < delta < timedelta(minutes=61)


def test_finish_run_failure_records_error(
    db, ingestion_api_client, event_source_approved
):
    run = IngestionRun.objects.create(
        source=event_source_approved, started_at=timezone.now(),
        status=IngestionRun.Status.RUNNING,
    )
    response = ingestion_api_client.post(
        f"/api/ingestion/runs/{run.id}/failure/",
        {"error_message": "boom"}, format="json",
    )
    assert response.status_code == 200
    run.refresh_from_db()
    assert run.status == IngestionRun.Status.FAILED
    assert run.error_message == "boom"


# --- Observations -----------------------------------------------------------


def test_submit_observation_creates_pending_and_stores_location(
    db, ingestion_api_client, event_source_approved
):
    response = ingestion_api_client.post(
        "/api/ingestion/observations/",
        _observation_payload(event_source_approved, status="accepted"),
        format="json",
    )
    assert response.status_code == 201
    obs = EventObservation.objects.get(id=response.data["id"])
    # The extractor can never self-promote: status is forced to pending.
    assert obs.status == EventObservation.Status.PENDING
    assert obs.source_id == event_source_approved.id
    assert obs.url == "https://example.com/rust"
    assert obs.platform == "meetup"
    # lat/lon written into the geography `location`.
    assert obs.location is not None
    assert round(obs.location.y, 3) == 52.52  # latitude
    assert round(obs.location.x, 3) == 13.405  # longitude


def test_submit_observation_without_coords_has_null_location(
    db, ingestion_api_client, event_source_approved
):
    payload = _observation_payload(event_source_approved)
    del payload["latitude"]
    del payload["longitude"]
    response = ingestion_api_client.post(
        "/api/ingestion/observations/", payload, format="json"
    )
    assert response.status_code == 201
    assert EventObservation.objects.get(id=response.data["id"]).location is None


def test_submit_observations_bulk_creates_all_pending(
    db, ingestion_api_client, event_source_approved
):
    payload = {
        "observations": [
            _observation_payload(event_source_approved, title="A"),
            _observation_payload(event_source_approved, title="B",
                                 latitude=None, longitude=None),
        ]
    }
    response = ingestion_api_client.post(
        "/api/ingestion/observations/bulk/", payload, format="json"
    )
    assert response.status_code == 201
    created = EventObservation.objects.filter(source=event_source_approved)
    assert created.count() == 2
    assert {o.status for o in created} == {EventObservation.Status.PENDING}


def test_submit_observation_stores_event_key(
    db, ingestion_api_client, event_source_approved
):
    """The extractor sends a stable ``event_key`` for run-over-run reconciliation;
    it is stored as-is (not force-cleared like ``status``)."""
    response = ingestion_api_client.post(
        "/api/ingestion/observations/",
        _observation_payload(event_source_approved, event_key="ical-uid-42"),
        format="json",
    )
    assert response.status_code == 201
    obs = EventObservation.objects.get(id=response.data["id"])
    assert obs.event_key == "ical-uid-42"
    # The read serializer surfaces the new lifecycle/identity fields.
    assert response.data["event_key"] == "ical-uid-42"
    assert response.data["lifecycle"] == EventObservation.Lifecycle.NEW


def test_submit_observation_without_event_key_defaults_blank(
    db, ingestion_api_client, event_source_approved
):
    """A partial deploy may omit ``event_key``; it defaults to blank and the
    observation is still accepted (but never reconciled)."""
    payload = _observation_payload(event_source_approved)
    del payload["event_key"]
    response = ingestion_api_client.post(
        "/api/ingestion/observations/", payload, format="json"
    )
    assert response.status_code == 201
    assert EventObservation.objects.get(id=response.data["id"]).event_key == ""


# --- Permission gating ------------------------------------------------------


def test_ingestion_user_without_perms_is_forbidden(db, user, api_client):
    # A plain authenticated user (no ingestion perms) gets 403.
    api_client.force_authenticate(user=user)
    assert api_client.get("/api/ingestion/sources/due/").status_code == 403
    assert api_client.post(
        "/api/ingestion/runs/", {"source": 1}, format="json"
    ).status_code == 403