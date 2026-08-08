from django.contrib.gis.db import models
from django.utils.text import slugify


class City(models.Model):
    """A gazetteer entry for a populated place.

    Provides a readable catalog of cities (with centroids and a suggested search
    radius) so API clients can offer a "pick a city" UX without knowing lat/lon.
    Seeded from GeoNames via the ``seed_cities`` management command.
    """

    # Stable GeoNames id; idempotency key for re-seeding (update_or_create).
    geoname_id = models.PositiveBigIntegerField(
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Stable GeoNames id; idempotency key for re-seeding.",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    country = models.CharField(max_length=100, blank=True)
    country_code = models.CharField(max_length=2, blank=True, db_index=True)
    # WGS84 centroid. geography=True so ST_DWithin distances are in metres.
    location = models.PointField(geography=True, srid=4326)
    default_radius_km = models.PositiveIntegerField(
        default=15,
        help_text="Suggested search radius (km) for ?near_city=.",
    )
    population = models.PositiveBigIntegerField(null=True, blank=True)
    timezone = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "cities"
        # A GiST spatial index on the geography `location` is created
        # automatically by the PostGIS backend (GeometryField.spatial_index).

    def __str__(self) -> str:
        cc = self.country_code or "?"
        return f"{self.name}, {cc}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.name}-{self.country_code}")
            self.slug = base or slugify(self.name)
        super().save(*args, **kwargs)