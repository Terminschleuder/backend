"""Tests for run-over-run observation reconciliation (``events/reconciliation.py``).

Each test builds two runs for one source — a previous SUCCEEDED run and the run
being reconciled — and asserts the lifecycle classification, review-state
carry-forward, and canonical-Event auto-propagation. The extractor submits
observations *before* the run is finalized, so in production ``reconcile_run`` is
called from ``runs/<id>/success/``; here we call it directly for determinism.
"""

from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.db import IntegrityError
from django.utils import timezone

from .models import Event, EventObservation, EventSource, IngestionRun, Organization
from .reconciliation import reconcile_run


# --- helpers ----------------------------------------------------------------


def _make_source():
    org = Organization.objects.create(name="Berlin Tech Meetups")
    return EventSource.objects.create(
        organization=org, url="https://example.com/events.ics",
        platform="homepage", is_approved=True,
    )


def _make_run(source, *, status=IngestionRun.Status.SUCCEEDED, events_found=0, started=None):
    return IngestionRun.objects.create(
        source=source,
        started_at=started or timezone.now(),
        status=status,
        events_found=events_found,
    )


def _make_obs(source, run, *, title, starts_at, event_key, url="", status=EventObservation.Status.PENDING,
              ends_at=None, venue_name="", venue_city="", venue_address="",
              reviewed_by=None, reviewed_at=None, review_note="",
              consecutive_misses=0):
    return EventObservation.objects.create(
        source=source, run=run, status=status, event_key=event_key,
        title=title, starts_at=starts_at, ends_at=ends_at, url=url,
        venue_name=venue_name, venue_city=venue_city, venue_address=venue_address,
        reviewed_by=reviewed_by, reviewed_at=reviewed_at, review_note=review_note,
        consecutive_misses=consecutive_misses,
    )


@pytest.fixture
def source(db):
    return _make_source()


# --- 1. first run: all NEW --------------------------------------------------


@pytest.mark.django_db
def test_first_run_marks_all_new(source):
    run = _make_run(source)
    _make_obs(source, run, title="A", starts_at=timezone.now() + timedelta(days=5), event_key="k-a")
    _make_obs(source, run, title="B", starts_at=timezone.now() + timedelta(days=6), event_key="k-b")

    summary = reconcile_run(run)

    assert summary["prev_run_id"] is None
    assert summary["new"] == 2
    for obs in run.observations.all():
        assert obs.lifecycle == EventObservation.Lifecycle.NEW
        assert obs.last_observed_run_id == run.id


# --- 2. unchanged -> OBSERVED + carries review state ------------------------


@pytest.mark.django_db
def test_unchanged_match_observed_and_carries_review_state(source):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    reviewer = User.objects.create_user(username="rev", email="r@e.com", password="x")

    start = timezone.now() + timedelta(days=10)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
        url="https://example.com/rust", status=EventObservation.Status.ACCEPTED,
        reviewed_by=reviewer, reviewed_at=timezone.now(), review_note="ok",
    )

    cur_run = _make_run(source)
    cur = _make_obs(
        source, cur_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
        url="https://example.com/rust",
    )

    summary = reconcile_run(cur_run)

    assert summary["observed"] == 1
    cur.refresh_from_db()
    prev.refresh_from_db()
    # The new observation inherits the prior review state — not re-queued.
    assert cur.lifecycle == EventObservation.Lifecycle.OBSERVED
    assert cur.status == EventObservation.Status.ACCEPTED
    assert cur.reviewed_by_id == reviewer.id
    assert cur.review_note == "ok"
    # The old observation is superseded and marked observed.
    assert prev.lifecycle == EventObservation.Lifecycle.OBSERVED
    assert prev.superseded_by_id == cur.id
    assert cur.last_observed_run_id == cur_run.id


# --- 3a. UPDATED propagates to canonical Event ------------------------------


@pytest.mark.django_db
def test_updated_propagates_to_canonical_event(source):
    start = timezone.now() + timedelta(days=10)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
        url="https://example.com/rust", status=EventObservation.Status.PROMOTED,
        venue_name="Factory Berlin", venue_city="Berlin",
    )
    event = Event.objects.create(
        title="Rust Meetup", starts_at=start, status=Event.Status.DRAFT,
        promoted_from=prev, source=source, organization=source.organization,
    )

    cur_run = _make_run(source)
    cur = _make_obs(
        source, cur_run, title="Rust Meetup (rebranded)", starts_at=start, event_key="k-rust",
        url="https://example.com/rust", venue_name="New Space", venue_city="Berlin",
    )

    summary = reconcile_run(cur_run)
    assert summary["updated"] == 1

    cur.refresh_from_db()
    prev.refresh_from_db()
    event.refresh_from_db()
    assert cur.lifecycle == EventObservation.Lifecycle.UPDATED
    assert prev.lifecycle == EventObservation.Lifecycle.UPDATED
    # Canonical Event updated + provenance repointed to the new observation.
    assert event.title == "Rust Meetup (rebranded)"
    assert event.promoted_from_id == cur.id
    assert cur.status == EventObservation.Status.PROMOTED


# --- 3b. POSTPONED propagates moved date to canonical Event -----------------


@pytest.mark.django_db
def test_postponed_propagates_moved_date(source):
    start = timezone.now() + timedelta(days=10)
    moved = start + timedelta(days=3)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
        url="https://example.com/rust", status=EventObservation.Status.PROMOTED,
    )
    event = Event.objects.create(
        title="Rust Meetup", starts_at=start, status=Event.Status.PUBLISHED,
        promoted_from=prev, source=source, organization=source.organization,
    )

    cur_run = _make_run(source)
    cur = _make_obs(
        source, cur_run, title="Rust Meetup", starts_at=moved, event_key="k-rust",
        url="https://example.com/rust",
    )

    summary = reconcile_run(cur_run)
    assert summary["postponed"] == 1

    cur.refresh_from_db()
    event.refresh_from_db()
    assert cur.lifecycle == EventObservation.Lifecycle.POSTPONED
    assert event.starts_at == moved
    assert event.promoted_from_id == cur.id
    assert cur.status == EventObservation.Status.PROMOTED


# --- 4. one miss stays OBSERVED (Event not cancelled) -----------------------


@pytest.mark.django_db
def test_one_miss_keeps_observed_event_alive(source):
    start = timezone.now() + timedelta(days=10)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
        status=EventObservation.Status.PROMOTED,
    )
    event = Event.objects.create(
        title="Rust Meetup", starts_at=start, status=Event.Status.PUBLISHED,
        promoted_from=prev, source=source, organization=source.organization,
    )

    # Current run sees nothing.
    cur_run = _make_run(source, events_found=1)
    summary = reconcile_run(cur_run)
    assert summary["no_longer_observed"] == 0

    prev.refresh_from_db()
    event.refresh_from_db()
    # One miss is below the stale threshold: lifecycle unchanged, Event stays.
    assert prev.lifecycle != EventObservation.Lifecycle.NO_LONGER_OBSERVED
    assert prev.consecutive_misses == 1
    assert event.status == Event.Status.PUBLISHED


# --- 5. two misses -> NO_LONGER_OBSERVED + Event CANCELLED ------------------


@pytest.mark.django_db
def test_two_misses_cancels_promoted_event(source):
    start = timezone.now() + timedelta(days=10)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
        status=EventObservation.Status.PROMOTED, consecutive_misses=1,
    )
    event = Event.objects.create(
        title="Rust Meetup", starts_at=start, status=Event.Status.PUBLISHED,
        promoted_from=prev, source=source, organization=source.organization,
    )

    cur_run = _make_run(source, events_found=1)
    summary = reconcile_run(cur_run)
    assert summary["no_longer_observed"] == 1

    prev.refresh_from_db()
    event.refresh_from_db()
    assert prev.lifecycle == EventObservation.Lifecycle.NO_LONGER_OBSERVED
    assert prev.consecutive_misses == 2
    assert "auto-cancelled" in prev.lifecycle_note
    assert event.status == Event.Status.CANCELLED
    assert event.cancelled_at is not None


# --- 6. past unmatched -> COMPLETED (Event not cancelled) ------------------


@pytest.mark.django_db
def test_past_unmatched_completed(source):
    # An event whose start time just passed (within the grace window) but is
    # now missing: natural completion, NOT a cancellation.
    past = timezone.now() - timedelta(hours=2)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Old Meetup", starts_at=past, event_key="k-old",
        status=EventObservation.Status.PROMOTED,
    )
    event = Event.objects.create(
        title="Old Meetup", starts_at=past, status=Event.Status.PUBLISHED,
        promoted_from=prev, source=source, organization=source.organization,
    )

    cur_run = _make_run(source, events_found=0)
    summary = reconcile_run(cur_run)
    assert summary["completed"] == 1
    assert summary["no_longer_observed"] == 0

    prev.refresh_from_db()
    event.refresh_from_db()
    assert prev.lifecycle == EventObservation.Lifecycle.COMPLETED
    # A completed (past) event is NOT cancelled.
    assert event.status == Event.Status.PUBLISHED


# --- 7. new unmatched -> stays PENDING --------------------------------------


@pytest.mark.django_db
def test_new_unmatched_stays_pending(source):
    start = timezone.now() + timedelta(days=10)
    prev_run = _make_run(source)
    _make_obs(source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust")

    cur_run = _make_run(source)
    cur = _make_obs(
        source, cur_run, title="Go Meetup", starts_at=start + timedelta(days=1),
        event_key="k-go",
    )

    summary = reconcile_run(cur_run)
    assert summary["new"] == 1
    cur.refresh_from_db()
    assert cur.lifecycle == EventObservation.Lifecycle.NEW
    # Genuinely new events still need operator review.
    assert cur.status == EventObservation.Status.PENDING


# --- 8. updated-PENDING stays PENDING (no Event touch) ---------------------


@pytest.mark.django_db
def test_updated_pending_does_not_touch_canonical_event(source):
    """An update to an observation that was never promoted stays PENDING; no
    canonical Event is created or modified."""
    start = timezone.now() + timedelta(days=10)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
        status=EventObservation.Status.PENDING,
    )

    cur_run = _make_run(source)
    cur = _make_obs(
        source, cur_run, title="Rust Meetup (v2)", starts_at=start, event_key="k-rust",
    )

    summary = reconcile_run(cur_run)
    assert summary["updated"] == 1
    cur.refresh_from_db()
    assert cur.lifecycle == EventObservation.Lifecycle.UPDATED
    # Never promoted -> the new observation stays pending for review.
    assert cur.status == EventObservation.Status.PENDING
    assert Event.objects.filter(source=source).count() == 0


# --- 9. match priority: key > url > fuzzy -----------------------------------


@pytest.mark.django_db
def test_match_priority_key_over_url_and_fuzzy(source):
    start = timezone.now() + timedelta(days=10)
    prev_run = _make_run(source)
    # prev has key=k-rust and url=u-rust.
    _make_obs(
        source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
        url="https://example.com/rust",
    )

    cur_run = _make_run(source)
    # current A: same key (should win), different url/title.
    a = _make_obs(
        source, cur_run, title="Rust Meetup Renamed", starts_at=start, event_key="k-rust",
        url="https://example.com/different",
    )
    # current B: same url as prev but different key — should NOT steal the match.
    _make_obs(
        source, cur_run, title="Decoy", starts_at=start + timedelta(days=1),
        event_key="k-decoy", url="https://example.com/rust",
    )

    summary = reconcile_run(cur_run)
    assert summary["observed"] + summary["updated"] == 1
    a.refresh_from_db()
    # Key match wins: prev's key matched A (the title changed -> UPDATED).
    assert a.lifecycle == EventObservation.Lifecycle.UPDATED


# --- 10. fuzzy detects postponed with changed key ---------------------------


@pytest.mark.django_db
def test_fuzzy_detects_postponed_with_changed_key(source):
    """No uid/url authoritative key (both use t: fallbacks that include the
    date), so the keys diverge on a move — the fuzzy matcher (same title, date
    within tolerance) catches the postponement."""
    start = timezone.now() + timedelta(days=10)
    moved = start + timedelta(days=5)
    prev_run = _make_run(source)
    _make_obs(
        source, prev_run, title="Stammtisch", starts_at=start,
        event_key="t:aaaa1111", url="",
    )

    cur_run = _make_run(source)
    cur = _make_obs(
        source, cur_run, title="Stammtisch", starts_at=moved,
        event_key="t:bbbb2222", url="",
    )

    summary = reconcile_run(cur_run)
    assert summary["postponed"] == 1
    cur.refresh_from_db()
    assert cur.lifecycle == EventObservation.Lifecycle.POSTPONED


# --- 11. feed-cap run skips NO_LONGER_OBSERVED ------------------------------


@pytest.mark.django_db
def test_feed_cap_run_skips_miss_marking(source):
    """A run that hit the feed cap (events_found >= cap) must not advance miss
    counting or mark anything no-longer-observed — absence is unreliable."""
    start = timezone.now() + timedelta(days=10)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
    )

    # Current run found >= EVENTS_FEED_CAP (default 100) events but omits the prev.
    cur_run = _make_run(source, events_found=100)
    summary = reconcile_run(cur_run)
    assert summary["no_longer_observed"] == 0

    prev.refresh_from_db()
    assert prev.consecutive_misses == 0
    assert prev.lifecycle != EventObservation.Lifecycle.NO_LONGER_OBSERVED


# --- 12. already-CANCELLED Event not resurrected ---------------------------


@pytest.mark.django_db
def test_cancelled_event_not_resurrected_on_update(source):
    """If the canonical Event was already cancelled (by hand), a later UPDATE
    on its observation must NOT resurrect it."""
    start = timezone.now() + timedelta(days=10)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Rust Meetup", starts_at=start, event_key="k-rust",
        status=EventObservation.Status.PROMOTED,
    )
    event = Event.objects.create(
        title="Rust Meetup", starts_at=start, status=Event.Status.CANCELLED,
        promoted_from=prev, source=source, organization=source.organization,
    )

    cur_run = _make_run(source)
    cur = _make_obs(
        source, cur_run, title="Rust Meetup (v2)", starts_at=start, event_key="k-rust",
    )

    reconcile_run(cur_run)
    cur.refresh_from_db()
    event.refresh_from_db()
    # The observation is classified UPDATED, but the cancelled Event is untouched.
    assert cur.lifecycle == EventObservation.Lifecycle.UPDATED
    assert cur.status == EventObservation.Status.PENDING
    assert event.status == Event.Status.CANCELLED
    assert event.promoted_from_id == prev.id  # not repointed to cur


# --- 13. reconciliation failure keeps run SUCCEEDED -------------------------


@pytest.mark.django_db
def test_reconciliation_failure_keeps_run_succeeded(source, ingestion_api_client):
    """The success endpoint wraps reconciliation in try/except; a failure is
    logged but never flips the run back to FAILED."""
    run = IngestionRun.objects.create(
        source=source, started_at=timezone.now(),
        status=IngestionRun.Status.RUNNING,
    )
    # Sabotage reconciliation by monkeypatching it to raise.
    from events import ingestion_views
    original = ingestion_views.reconcile_run
    ingestion_views.reconcile_run = lambda _run: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        response = ingestion_api_client.post(
            f"/api/ingestion/runs/{run.id}/success/", {"events_found": 0}, format="json"
        )
    finally:
        ingestion_views.reconcile_run = original

    assert response.status_code == 200
    run.refresh_from_db()
    assert run.status == IngestionRun.Status.SUCCEEDED


# --- 14. horizon bounds expected set ----------------------------------------


@pytest.mark.django_db
def test_horizon_excludes_far_future_from_expected_set(source):
    """An event starting beyond the upcoming horizon (>365d) is not in the
    "expected still-observed" set, so its absence is never a miss."""
    far = timezone.now() + timedelta(days=400)
    prev_run = _make_run(source)
    prev = _make_obs(
        source, prev_run, title="Far Future", starts_at=far, event_key="k-far",
    )

    cur_run = _make_run(source, events_found=0)
    summary = reconcile_run(cur_run)
    # Not counted as no-longer-observed (outside horizon) nor completed (not past).
    assert summary["no_longer_observed"] == 0
    assert summary["completed"] == 0
    prev.refresh_from_db()
    assert prev.consecutive_misses == 0


# --- 15. per-run unique event_key constraint --------------------------------


@pytest.mark.django_db
def test_unique_event_key_per_run(source):
    run = _make_run(source)
    _make_obs(source, run, title="A", starts_at=timezone.now() + timedelta(days=5), event_key="dup")
    with pytest.raises(IntegrityError):
        _make_obs(
            source, run, title="B", starts_at=timezone.now() + timedelta(days=6),
            event_key="dup",
        )