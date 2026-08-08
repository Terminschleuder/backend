"""Add PostGIS location fields, owner_group, and the postgis extension."""

import django.contrib.gis.db.models.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("events", "0001_initial"),
    ]

    operations = [
        # The PostGIS extension must exist before geometry/geography columns.
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS postgis;",
            reverse_sql="DROP EXTENSION IF EXISTS postgis;",
        ),
        migrations.AddField(
            model_name="event",
            name="location",
            field=django.contrib.gis.db.models.fields.PointField(
                blank=True, geography=True, null=True, srid=4326
            ),
        ),
        migrations.AddField(
            model_name="venue",
            name="location",
            field=django.contrib.gis.db.models.fields.PointField(
                blank=True, geography=True, null=True, srid=4326
            ),
        ),
        migrations.RemoveField(
            model_name="venue",
            name="latitude",
        ),
        migrations.RemoveField(
            model_name="venue",
            name="longitude",
        ),
        migrations.AddField(
            model_name="event",
            name="owner_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="events",
                to="auth.group",
            ),
        ),
    ]