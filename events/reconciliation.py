"""Run-over-run observation reconciliation.

When an extraction run finishes (``POST /api/ingestion/runs/<id>/success/``), the
backend compares that run's observations to the **previous successful run's**
observations for the same source and classifies each previously-seen event:

* ``OBSERVED``      — matched, unchanged (carries review state; not re-queued)
* ``UPDATED``       — matched, "hard" facts changed (venue / title / url / location)
* ``POSTPONED``     — matched, ``starts_at`` (and/or ``ends_at``) changed
* ``NO_LONGER_OBSERVED`` — missing, but its start time is still upcoming
* ``COMPLETED``     — missing and its start time has passed (natural end, not a
  cancellation)
* ``NEW``           — no prior match (stays ``pending`` for operator review)

Matching priority: ``event_key`` (the iCal/jcal ``uid`` or detail-page ``url`` the
extractor sends) → ``url`` → fuzzy (normalized title + ``starts_at`` within a
tolerance window, used only when the keys diverged — e.g. a no-uid event moved).

For observations that were already ``PROMOTED`` to a canonical ``Event``, the
change is auto-applied to that Event (updated/postponed → copy the new facts;
no-longer-observed → ``CANCELLED``). Observations that were never promoted only get
their ``lifecycle`` marked; the matched new observation carries the prior review
state forward. This implements the "auto-manage promoted events" policy: once an
event is in the canonical system, routine changes and cancellations flow through
without re-review, while genuinely new events still need an operator.

All knobs are in ``config/settings.py`` (``EVENTS_*``). The whole reconcile is
best-effort: it runs after the run is already ``SUCCEEDED``, and a failure here
must never flip the run to ``FAILED`` (the caller wraps it in a try/except).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Event, EventObservation, IngestionRun, Venue

logger = logging.getLogger(__name__)

# Guard defaults (overridable via settings.EVENTS_*). See config/settings.py.
_DEFAULTS = {
    "EVENTS_STALE_AFTER_RUNS": 2,        # consecutive misses before NO_LONGER_OBSERVED
    "EVENTS_POSTPONED_DAY_TOLERANCE": 14,  # fuzzy-match window for postponed detection
    "EVENTS_UPCOMING_HORIZON_DAYS": 365,  # upper bound of "expected still-observed"
    "EVENTS_GRACE_PAST_DAYS": 1,         # lower bound (just-past events still expected)
    "EVENTS_FEED_CAP": 100,              # extractor max_feed_events; cap-hit disables miss-marking
}


def _setting(name: str) -> Any:
    return getattr(settings, name, _DEFAULTS[name])


# --- title normalization ---


def _norm_title(value: str | None) -> str:
    """Lowercase + collapse whitespace, for stable title comparison/matching."""
    if not value:
        return ""
    return " ".join(str(value).split()).lower()


# --- diff helpers ---


# Fields whose change indicates a genuine UPDATE. Description and the
# LLM-inferred enums (event_type, attendance_mode) are deliberately excluded:
# the extractor rephrases description run-to-run and re-guesses the enums, so
# including them would flag nearly every event as "updated". Venue / title / url
# / location are facts stated on the page and are reliable update signals.
_NONDATE_DIFF_FIELDS = (
    "title",        # compared normalized
    "venue_name",
    "venue_address",
    "venue_city",
    "url",
    # location compared as a Point
)


def _nondate_differs(cur: EventObservation, prev: EventObservation) -> bool:
    """True if any non-date "hard" fact differs between two matched observations."""
    if _norm_title(cur.title) != _norm_title(prev.title):
        return True
    for f in ("venue_name", "venue_address", "venue_city", "url"):
        if (getattr(cur, f) or "") != (getattr(prev, f) or ""):
            return True
    if bool(cur.location) != bool(prev.location):
        return True
    if cur.location and prev.location and cur.location != prev.location:
        return True
    return False


def _date_differs(cur: EventObservation, prev: EventObservation) -> bool:
    return cur.starts_at != prev.starts_at or cur.ends_at != prev.ends_at


# --- review-state carry-forward ---


def _carry_review_state(prev: EventObservation, cur: EventObservation) -> None:
    """Carry the prior review state onto the new observation.

    An unchanged or matched event that was already reviewed must not re-enter the
    operator's pending queue: the new observation inherits the old review status,
    reviewer, timestamp, and note — **except** ``PROMOTED``. A promoted
    observation's status is re-established by ``_propagate`` only if its canonical
    ``Event`` is still live (DRAFT/PUBLISHED). If that Event has since been
    CANCELLED/ARCHIVED, the propagation is a no-op and ``cur`` stays ``PENDING`` —
    so a reappearance of a previously-cancelled event is treated as a fresh
    candidate that needs operator review (no silent resurrection).
    """
    if prev.status == EventObservation.Status.PROMOTED:
        return
    cur.status = prev.status
    cur.reviewed_by = prev.reviewed_by
    cur.reviewed_at = prev.reviewed_at
    cur.review_note = prev.review_note


# --- matching ---


def _fuzzy_match(
    prev: EventObservation, candidates: list[EventObservation], tol_days: int
) -> EventObservation | None:
    """Same normalized title AND starts_at within ``tol_days`` of the previous."""
    prev_title = _norm_title(prev.title)
    if not prev_title:
        return None
    tol = timedelta(days=tol_days)
    for c in candidates:
        if _norm_title(c.title) != prev_title:
            continue
        if c.starts_at and prev.starts_at and abs(c.starts_at - prev.starts_at) <= tol:
            return c
    return None


# --- canonical-Event propagation ---


def _resolve_venue(obs: EventObservation) -> Venue | None:
    """Mirror the admin promote's venue handling: get_or_create by name."""
    if not obs.venue_name:
        return None
    venue, _created = Venue.objects.get_or_create(
        name=obs.venue_name,
        defaults={"address": obs.venue_address or "", "city": obs.venue_city or ""},
    )
    return venue


def _propagate(prev: EventObservation, cur: EventObservation | None, lifecycle: str) -> None:
    """Auto-apply the change to the canonical Event, if ``prev`` was promoted.

    Only acts when ``prev.status == PROMOTED`` and a DRAFT/PUBLISHED Event exists
    via ``prev.canonical_events``. Already-CANCELLED/ARCHIVED events are never
    resurrected. If ``prev`` was never promoted, this is a no-op (the matched
    ``cur`` carries the pending review state forward instead).
    """
    if prev.status != EventObservation.Status.PROMOTED:
        return
    event = (
        prev.canonical_events.filter(status__in=[Event.Status.DRAFT, Event.Status.PUBLISHED])
        .first()
    )
    if event is None:
        return

    now = timezone.now()
    if lifecycle == EventObservation.Lifecycle.NO_LONGER_OBSERVED:
        event.status = Event.Status.CANCELLED
        event.cancelled_at = now
        event.save(update_fields=["status", "cancelled_at", "updated_at"])
        prev.lifecycle_note = f"auto-cancelled: missing {prev.consecutive_misses} run(s)"
        return

    if lifecycle in (EventObservation.Lifecycle.UPDATED, EventObservation.Lifecycle.POSTPONED) and cur is not None:
        event.title = cur.title
        event.starts_at = cur.starts_at          # postponed: the moved date
        event.ends_at = cur.ends_at
        event.attendance_mode = cur.attendance_mode
        event.event_type = cur.event_type
        event.location = cur.location
        event.venue = _resolve_venue(cur)
        # Provenance: keep the first-seen original_url/platform (only fill if empty).
        if not event.original_url:
            event.original_url = cur.url or ""
        if not event.original_platform:
            event.original_platform = cur.platform or ""
        # Description is operator-curated; not overwritten from the (volatile) observation.
        event.promoted_from = cur
        event.save()
        # The new observation is now the promoted one (chain head stays current).
        cur.status = EventObservation.Status.PROMOTED
        cur.reviewed_at = now
        cur.lifecycle_note = f"auto-{lifecycle}: canonical event updated"
    elif lifecycle == EventObservation.Lifecycle.OBSERVED and cur is not None:
        # Unchanged match: keep the canonical Event pointing at the newest obs.
        event.promoted_from = cur
        event.save(update_fields=["promoted_from", "updated_at"])
        cur.status = EventObservation.Status.PROMOTED


# --- main entry point ---


def reconcile_run(run: IngestionRun) -> dict[str, Any]:
    """Reconcile ``run`` against the previous successful run for its source.

    Returns a summary dict (for logging). All mutations are wrapped in a single
    transaction by the caller. Safe to call on the first ever run (no previous).
    """
    now = timezone.now()
    source = run.source
    stale_after = int(_setting("EVENTS_STALE_AFTER_RUNS"))
    tol_days = int(_setting("EVENTS_POSTPONED_DAY_TOLERANCE"))
    horizon_start = now - timedelta(days=int(_setting("EVENTS_GRACE_PAST_DAYS")))
    horizon_end = now + timedelta(days=int(_setting("EVENTS_UPCOMING_HORIZON_DAYS")))
    feed_cap = int(_setting("EVENTS_FEED_CAP"))

    current_obs = list(run.observations.select_related("source"))
    by_key: dict[str, EventObservation] = {o.event_key: o for o in current_obs if o.event_key}
    by_url: dict[str, EventObservation] = {o.url: o for o in current_obs if o.url}

    prev_run = (
        IngestionRun.objects.filter(source=source, status=IngestionRun.Status.SUCCEEDED)
        .exclude(pk=run.pk)
        .order_by("-started_at")
        .first()
    )

    summary: dict[str, Any] = {
        "run_id": run.pk,
        "source_id": source.pk,
        "current": len(current_obs),
        "prev_run_id": prev_run.pk if prev_run else None,
        "observed": 0,
        "updated": 0,
        "postponed": 0,
        "no_longer_observed": 0,
        "completed": 0,
        "new": 0,
    }

    # First ever successful run: nothing to compare against -> all NEW.
    if prev_run is None:
        run.observations.update(
            lifecycle=EventObservation.Lifecycle.NEW,
            last_observed_run=run,
            consecutive_misses=0,
        )
        summary["new"] = len(current_obs)
        return summary

    # The expected-still-observed set: the previous run's observations that are
    # (a) within the upcoming horizon, (b) not already terminal, and (c) carry a
    # usable event_key. Empty-key observations (e.g. submitted before this feature
    # existed) are skipped — they can't be reliably matched and must never be
    # marked missing.
    prev_obs = list(
        EventObservation.objects.filter(run=prev_run)
        .filter(starts_at__gte=horizon_start, starts_at__lte=horizon_end)
        .exclude(lifecycle__in=[
            EventObservation.Lifecycle.NO_LONGER_OBSERVED,
            EventObservation.Lifecycle.COMPLETED,
        ])
        .exclude(event_key="")
        .select_related("source")
    )

    matched_current_ids: set[int] = set()

    for prev in prev_obs:
        cur: EventObservation | None = None
        # Priority 1: event_key.
        if prev.event_key:
            cur = by_key.get(prev.event_key)
        # Priority 2: url (e.g. uid changed but the page url stayed put).
        if cur is None and prev.url:
            cur = by_url.get(prev.url)
        # Priority 3: fuzzy (normalized title + date within tolerance).
        if cur is None:
            remaining = [o for o in current_obs if o.pk not in matched_current_ids]
            cur = _fuzzy_match(prev, remaining, tol_days)

        if cur is not None and cur.pk not in matched_current_ids:
            matched_current_ids.add(cur.pk)
            date_changed = _date_differs(cur, prev)
            nondate_changed = _nondate_differs(cur, prev)

            _carry_review_state(prev, cur)
            cur.last_observed_run = run
            cur.consecutive_misses = 0
            prev.last_observed_run = run
            prev.consecutive_misses = 0

            if not date_changed and not nondate_changed:
                cur.lifecycle = EventObservation.Lifecycle.OBSERVED
                prev.lifecycle = EventObservation.Lifecycle.OBSERVED
                summary["observed"] += 1
                _propagate(prev, cur, EventObservation.Lifecycle.OBSERVED)
            elif date_changed and not nondate_changed:
                cur.lifecycle = EventObservation.Lifecycle.POSTPONED
                prev.lifecycle = EventObservation.Lifecycle.POSTPONED
                summary["postponed"] += 1
                _propagate(prev, cur, EventObservation.Lifecycle.POSTPONED)
            else:
                # non-date facts changed (date may also have changed -> still UPDATED)
                cur.lifecycle = EventObservation.Lifecycle.UPDATED
                prev.lifecycle = EventObservation.Lifecycle.UPDATED
                summary["updated"] += 1
                _propagate(prev, cur, EventObservation.Lifecycle.UPDATED)

            prev.superseded_by = cur
            cur.save()
            prev.save()
        else:
            # Unmatched previous observation.
            _handle_unmatched(prev, run, now, stale_after, feed_cap, summary)

    # Unmatched current observations = genuinely new events.
    new_count = 0
    for cur in current_obs:
        if cur.pk in matched_current_ids:
            continue
        cur.lifecycle = EventObservation.Lifecycle.NEW
        cur.last_observed_run = run
        cur.consecutive_misses = 0
        cur.save(update_fields=["lifecycle", "last_observed_run", "consecutive_misses"])
        new_count += 1
    summary["new"] = new_count

    logger.info("reconcile_run %s summary=%s", run.pk, summary)
    return summary


def _handle_unmatched(
    prev: EventObservation,
    run: IngestionRun,
    now: Any,
    stale_after: int,
    feed_cap: int,
    summary: dict[str, Any],
) -> None:
    """Classify a previous observation that has no match in the current run."""
    # Past event -> natural completion (NOT a cancellation).
    if prev.starts_at <= now:
        prev.lifecycle = EventObservation.Lifecycle.COMPLETED
        prev.lifecycle_set_at = now
        prev.lifecycle_note = "completed: event start time passed"
        prev.save(update_fields=["lifecycle", "lifecycle_set_at", "lifecycle_note", "updated_at"])
        summary["completed"] += 1
        return

    # Upcoming + missing. If this run hit the feed cap, absence is unreliable —
    # don't advance miss counting or mark no-longer-observed this run.
    if run.events_found and run.events_found >= feed_cap:
        prev.save(update_fields=["updated_at"])
        return

    prev.consecutive_misses = (prev.consecutive_misses or 0) + 1
    if prev.consecutive_misses >= stale_after:
        prev.lifecycle = EventObservation.Lifecycle.NO_LONGER_OBSERVED
        prev.lifecycle_set_at = now
        # _propagate cancels the canonical Event (if promoted) and sets
        # prev.lifecycle_note in memory; persist it together with the fields below.
        summary["no_longer_observed"] += 1
        _propagate(prev, None, EventObservation.Lifecycle.NO_LONGER_OBSERVED)
        if not prev.lifecycle_note:
            prev.lifecycle_note = f"auto-marked missing after {prev.consecutive_misses} run(s)"
        prev.save(update_fields=[
            "consecutive_misses", "lifecycle", "lifecycle_set_at", "lifecycle_note", "updated_at"
        ])
    else:
        # Still observed; just record the miss, lifecycle unchanged.
        prev.save(update_fields=["consecutive_misses", "updated_at"])