"""Add an optional ``hero_image`` (ImageField) to ``Event``.

The file is stored under ``MEDIA_ROOT/events/hero/`` (a persistent Docker volume);
only the path is in the DB. Nullable so every pre-existing event keeps working.
Requires ``Pillow`` (added to requirements) for Django's ``ImageField``.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0003_organizations_ingestion_provenance"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="hero_image",
            field=models.ImageField(
                blank=True,
                help_text="Optional hero/banner image for the event.",
                null=True,
                upload_to="events/hero/",
            ),
        ),
    ]