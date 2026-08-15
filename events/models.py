from django.conf import settings
from django.contrib.gis.db import models
from django.utils.text import slugify
from django.utils import timezone


class Organization(models.Model):
    """An organization that owns event sources and the canonical events
    extracted from them.

    (Renamed from ``Organizer``; an organization is the entity the extraction
    pipeline attributes sources and observations to, and that the public API
    exposes as the owner of a set of events.)
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="organizations",
    )
    # Inactive organizations are hidden from the public API and their sources
    # stop being due for extraction.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Category(models.Model):
    """A tag/category an event can be grouped under (e.g. 'Music', 'Tech')."""

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True, blank=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Venue(models.Model):
    """A physical place where events happen."""

    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    # Geographic location (WGS84). geography=True so distances are in meters.
    location = models.PointField(geography=True, srid=4326, null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        if self.city:
            return f"{self.name} ({self.city})"
        return self.name


class EventSource(models.Model):
    """A URL owned by an organization that the external extractor crawls.

    Only approved, active sources are eligible for extraction ("due"). The
    extractor reports runs that update ``last_fetched_at`` / ``next_due_at``.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="sources"
    )
    url = models.URLField()
    platform = models.CharField(
        max_length=80, blank=True, default="",
        help_text="Where the source lives, e.g. 'meetup', 'eventbrite', 'homepage'.",
    )
    is_approved = models.BooleanField(
        default=False, help_text="Admin must approve before the source is eligible for extraction."
    )
    is_active = models.BooleanField(
        default=True, help_text="Soft pause: an approved source can be temporarily disabled."
    )
    fetch_interval_minutes = models.PositiveIntegerField(
        default=60, help_text="How often the extractor should revisit this source."
    )
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    next_due_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sources",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__name", "url"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "url"], name="unique_org_source_url"
            ),
        ]
        indexes = [
            models.Index(
                fields=["is_approved", "is_active", "next_due_at"],
                name="events_source_due_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.url} ({self.organization})"

    @classmethod
    def due(cls):
        """Approved, active sources that are due for processing.

        A source is due when it has never been fetched (``next_due_at`` is null)
        or its scheduled next fetch has passed.
        """
        return cls.objects.filter(
            is_approved=True,
            is_active=True,
        ).filter(
            models.Q(next_due_at__isnull=True) | models.Q(next_due_at__lte=timezone.now())
        )


class IngestionRun(models.Model):
    """One extraction pass over a source, reported by the external extractor."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(
        EventSource, on_delete=models.CASCADE, related_name="runs"
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    events_found = models.PositiveIntegerField(default=0)
    events_promoted = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ingestion_runs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["source", "status"], name="events_run_src_status_idx"),
        ]

    def __str__(self) -> str:
        return f"run {self.id} on {self.source}"


class Event(models.Model):
    """A canonical event — the trusted representation exposed to consumers.

    Extracted events enter as ``EventObservation`` (untrusted); an operator
    promotes an accepted observation into a canonical event, copying its
    ``original_url`` / ``original_platform`` and linking provenance via
    ``source`` and ``promoted_from``. New events default to ``published`` so
    the existing hand-curated catalog stays public; ingestion-promoted events
    go ``draft`` → ``published``.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CANCELLED = "cancelled", "Cancelled"
        ARCHIVED = "archived", "Archived"

    class EventType(models.TextChoices):
        MEETUP = "meetup", "Meetup"
        CONFERENCE = "conference", "Conference"
        WORKSHOP = "workshop", "Workshop"
        SOCIAL = "social", "Social"
        OTHER = "other", "Other"

    class AttendanceMode(models.TextChoices):
        PHYSICAL = "physical", "Physical"
        ONLINE = "online", "Online"
        HYBRID = "hybrid", "Hybrid"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)

    # Optional hero/banner image. The file is stored under MEDIA_ROOT/events/hero/
    # (a persistent Docker volume); only the path is held in the DB. The API exposes
    # its absolute URL (read-only); uploads happen in the backoffice.
    hero_image = models.ImageField(
        upload_to="events/hero/", null=True, blank=True,
        help_text="Optional hero/banner image for the event.",
    )

    venue = models.ForeignKey(
        Venue, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    categories = models.ManyToManyField(Category, blank=True, related_name="events")

    capacity = models.PositiveIntegerField(null=True, blank=True)

    # Geographic location (WGS84). geography=True so ST_DWithin uses meters.
    location = models.PointField(geography=True, srid=4326, null=True, blank=True)

    # Lifecycle + classification.
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PUBLISHED, db_index=True
    )
    event_type = models.CharField(
        max_length=20, choices=EventType.choices, default=EventType.OTHER, db_index=True
    )
    attendance_mode = models.CharField(
        max_length=20, choices=AttendanceMode.choices,
        default=AttendanceMode.PHYSICAL, db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    # Provenance: where this canonical event came from.
    original_url = models.URLField(blank=True, default="")
    original_platform = models.CharField(max_length=80, blank=True, default="")
    source = models.ForeignKey(
        EventSource, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="events",
    )
    promoted_from = models.ForeignKey(
        # Defined below; string ref avoids an ordering dependency.
        "EventObservation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="canonical_events",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    # Group that co-owns this event; members may edit/delete it.
    owner_group = models.ForeignKey(
        "auth.Group",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["starts_at"]),
            models.Index(fields=["-starts_at"]),
            models.Index(fields=["status", "starts_at"], name="events_status_starts_idx"),
            # A GiST spatial index on the geography `location` is created
            # automatically by the PostGIS backend (GeometryField.spatial_index).
        ]

    def __str__(self) -> str:
        return f"{self.title} @ {self.starts_at:%Y-%m-%d %H:%M}"


class EventObservation(models.Model):
    """An UNTRUSTED extracted event observation.

    Observations never mutate a canonical ``Event`` directly. An operator
    reviews, optionally corrects, and promotes an accepted observation into a
    canonical event (linked back here via ``Event.promoted_from``).

    Run-over-run lifecycle: ``events/reconciliation.py`` compares each run's
    observations to the previous successful run's for the same source and sets
    ``lifecycle`` (NEW/OBSERVED/UPDATED/POSTPONED/NO_LONGER_OBSERVED/COMPLETED),
    linking superseded observations via ``superseded_by``. The "current active
    observation per event per source" is::

        EventObservation.objects.filter(
            source=s, superseded_by__isnull=True,
            lifecycle__in=[NEW, OBSERVED, UPDATED, POSTPONED],
        )
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        PROMOTED = "promoted", "Promoted"

    class Lifecycle(models.TextChoices):
        # Run-over-run classification, orthogonal to the review ``Status`` above.
        # ``Status`` tracks operator review; ``Lifecycle`` tracks whether the event
        # is still being seen across extraction runs. See ``events/reconciliation.py``.
        NEW = "new", "New"  # no prior match this run (still needs review)
        OBSERVED = "observed", "Observed"  # matched the previous run, unchanged
        UPDATED = "updated", "Updated"  # matched, non-date fields changed
        POSTPONED = "postponed", "Postponed"  # matched, starts_at changed
        NO_LONGER_OBSERVED = "no_longer_observed", "No longer observed"  # missing + upcoming
        COMPLETED = "completed", "Completed"  # missing but start time already passed

    source = models.ForeignKey(
        EventSource, on_delete=models.CASCADE, related_name="observations"
    )
    run = models.ForeignKey(
        IngestionRun, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="observations",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    raw_payload = models.JSONField(default=dict, blank=True)

    # --- Run-over-run identity + lifecycle (see events/reconciliation.py) ---
    # Stable per-event identity supplied by the extractor: the iCal/jcal ``uid``
    # for feed-sourced events, the detail-page ``url`` for listing/detail events,
    # or a ``t:<hash>`` fallback. Never includes the date for authoritative ids, so
    # a postponed event still matches; the ``t:`` fallback includes the date so
    # recurring instances without a uid/url stay distinct.
    event_key = models.CharField(
        max_length=255, db_index=True, blank=True, default="",
        help_text="Stable per-event identity for run-over-run matching.",
    )
    lifecycle = models.CharField(
        max_length=25, choices=Lifecycle.choices, default=Lifecycle.NEW, db_index=True,
        help_text="Run-over-run classification (orthogonal to review status).",
    )
    # Points from the OLD observation to the NEWER one that replaced it.
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="supersedes",
        help_text="Newer observation that replaced this one (if matched/updated).",
    )
    # The most recent SUCCEEDED run in which this event_key was seen.
    last_observed_run = models.ForeignKey(
        IngestionRun, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="last_seen_observations",
        help_text="Most recent succeeded run that observed this event.",
    )
    consecutive_misses = models.PositiveIntegerField(
        default=0,
        help_text="Consecutive runs this event was expected but not seen.",
    )
    lifecycle_set_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When lifecycle was last set to a terminal state.",
    )
    lifecycle_note = models.TextField(
        blank=True, default="",
        help_text="Provenance for an auto-applied lifecycle change.",
    )

    # Extracted fields (mirror the canonical Event set; the operator chooses
    # venue/organization at promotion).
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    url = models.URLField(blank=True, default="", help_text="Observed original URL.")
    platform = models.CharField(
        max_length=80, blank=True, default="", help_text="Observed original platform."
    )
    attendance_mode = models.CharField(
        max_length=20, choices=Event.AttendanceMode.choices, default=Event.AttendanceMode.PHYSICAL
    )
    event_type = models.CharField(
        max_length=20, choices=Event.EventType.choices, default=Event.EventType.OTHER
    )
    venue_name = models.CharField(max_length=200, blank=True, default="")
    venue_address = models.CharField(max_length=255, blank=True, default="")
    venue_city = models.CharField(max_length=100, blank=True, default="")
    # Geographic location (WGS84). geography=True so distances are in meters.
    location = models.PointField(geography=True, srid=4326, null=True, blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_observations",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source", "status"], name="events_obs_src_status_idx"),
            models.Index(fields=["source", "lifecycle"], name="events_obs_src_life_idx"),
            models.Index(
                fields=["source", "event_key", "lifecycle"], name="events_obs_key_life_idx"
            ),
            models.Index(fields=["source", "last_observed_run"], name="events_obs_last_run_idx"),
        ]
        constraints = [
            # The extractor must not submit the same event_key twice in one run.
            # Condition uses ``event_key__gt=""`` as a portable "non-empty" guard.
            models.UniqueConstraint(
                fields=["source", "event_key", "run"],
                name="unique_obs_per_run_per_key",
                condition=models.Q(event_key__gt="") & models.Q(run__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} @ {self.starts_at:%Y-%m-%d %H:%M}"