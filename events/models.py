from django.conf import settings
from django.contrib.gis.db import models
from django.utils.text import slugify


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


class Organizer(models.Model):
    """A person or group that hosts events."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="organizers",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Event(models.Model):
    """A meetup or local event."""

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)

    venue = models.ForeignKey(
        Venue, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    organizer = models.ForeignKey(
        Organizer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    categories = models.ManyToManyField(Category, blank=True, related_name="events")

    capacity = models.PositiveIntegerField(null=True, blank=True)

    # Geographic location (WGS84). geography=True so ST_DWithin uses meters.
    location = models.PointField(geography=True, srid=4326, null=True, blank=True)

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
            # A GiST spatial index on the geography `location` is created
            # automatically by the PostGIS backend (GeometryField.spatial_index).
        ]

    def __str__(self) -> str:
        return f"{self.title} @ {self.starts_at:%Y-%m-%d %H:%M}"