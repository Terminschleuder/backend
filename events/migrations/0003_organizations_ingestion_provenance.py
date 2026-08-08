"""Organizations, ingestion, provenance & event lifecycle.

Renames ``Organizer`` → ``Organization`` (preserving the ``organizer_id`` FK
column via ``RenameModel`` + ``RenameField`` — never drop/recreate), extends it
with ``is_active`` / ``slug``, and adds the ingestion/provenance models
(``EventSource``, ``IngestionRun``, ``EventObservation``) plus the event
lifecycle / classification / provenance fields on ``Event``.

Defaults are chosen so every pre-existing row keeps working:
    status=published, event_type=other, attendance_mode=physical,
    original_url="", original_platform="", all new FKs nullable.
"""

import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils.text import slugify


def slugify_existing_orgs(apps, schema_editor):
    Organization = apps.get_model("events", "Organization")
    for org in Organization.objects.all():
        if not org.slug:
            org.slug = slugify(org.name)
            org.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("events", "0002_postgis_location"),
    ]

    operations = [
        # --- Organizer → Organization (rename table + repoint inbound FKs) ---
        migrations.RenameModel(
            old_name="Organizer",
            new_name="Organization",
        ),
        # Rename the Event FK field/column organizer(_id) → organization(_id).
        # RenameModel above already repointed its `to` to events.organization;
        # this preserves the column rather than drop+recreate the FK.
        migrations.RenameField(
            model_name="event",
            old_name="organizer",
            new_name="organization",
        ),
        # --- Organization extensions ---
        migrations.AddField(
            model_name="organization",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="organization",
            name="slug",
            # db_index=False here so this intermediate add creates no indexes;
            # the AlterField below (unique=True → db_index=True) creates the
            # slug's btree + ``_like`` indexes exactly once. Adding with
            # db_index=True would make both steps create the ``_like`` index
            # and collide ("relation ..._like already exists").
            field=models.SlugField(blank=True, default="", db_index=False, max_length=220),
        ),
        migrations.RunPython(
            slugify_existing_orgs,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="organization",
            name="slug",
            field=models.SlugField(blank=True, max_length=220, unique=True),
        ),
        # The renamed Organizer.owner kept its old related_name ('organizers');
        # align it with the new Organization model ('organizations').
        migrations.AlterField(
            model_name="organization",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="organizations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # --- Ingestion / provenance models ---
        migrations.CreateModel(
            name="EventSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("url", models.URLField()),
                ("platform", models.CharField(blank=True, default="", help_text="Where the source lives, e.g. 'meetup', 'eventbrite', 'homepage'.", max_length=80)),
                ("is_approved", models.BooleanField(default=False, help_text="Admin must approve before the source is eligible for extraction.")),
                ("is_active", models.BooleanField(default=True, help_text="Soft pause: an approved source can be temporarily disabled.")),
                ("fetch_interval_minutes", models.PositiveIntegerField(default=60, help_text="How often the extractor should revisit this source.")),
                ("last_fetched_at", models.DateTimeField(blank=True, null=True)),
                ("next_due_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sources", to="events.organization")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sources", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["organization__name", "url"],
                "indexes": [models.Index(fields=["is_approved", "is_active", "next_due_at"], name="events_source_due_idx")],
                "constraints": [models.UniqueConstraint(fields=("organization", "url"), name="unique_org_source_url")],
            },
        ),
        migrations.CreateModel(
            name="IngestionRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed")], db_index=True, default="pending", max_length=20)),
                ("events_found", models.PositiveIntegerField(default=0)),
                ("events_promoted", models.PositiveIntegerField(default=0)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="runs", to="events.eventsource")),
                ("reported_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ingestion_runs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-started_at"],
                "indexes": [models.Index(fields=["source", "status"], name="events_run_src_status_idx")],
            },
        ),
        migrations.CreateModel(
            name="EventObservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected"), ("promoted", "Promoted")], db_index=True, default="pending", max_length=20)),
                ("raw_payload", models.JSONField(blank=True, default=dict)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, default="")),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("url", models.URLField(blank=True, default="", help_text="Observed original URL.")),
                ("platform", models.CharField(blank=True, default="", help_text="Observed original platform.", max_length=80)),
                ("attendance_mode", models.CharField(choices=[("physical", "Physical"), ("online", "Online"), ("hybrid", "Hybrid")], default="physical", max_length=20)),
                ("event_type", models.CharField(choices=[("meetup", "Meetup"), ("conference", "Conference"), ("workshop", "Workshop"), ("social", "Social"), ("other", "Other")], default="other", max_length=20)),
                ("venue_name", models.CharField(blank=True, default="", max_length=200)),
                ("venue_address", models.CharField(blank=True, default="", max_length=255)),
                ("venue_city", models.CharField(blank=True, default="", max_length=100)),
                ("location", django.contrib.gis.db.models.fields.PointField(blank=True, geography=True, null=True, srid=4326)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("review_note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="observations", to="events.eventsource")),
                ("run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="observations", to="events.ingestionrun")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_observations", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["source", "status"], name="events_obs_src_status_idx")],
            },
        ),
        # --- Event lifecycle / classification / provenance fields ---
        migrations.AddField(
            model_name="event",
            name="status",
            field=models.CharField(choices=[("draft", "Draft"), ("published", "Published"), ("cancelled", "Cancelled"), ("archived", "Archived")], db_index=True, default="published", max_length=20),
        ),
        migrations.AddField(
            model_name="event",
            name="event_type",
            field=models.CharField(choices=[("meetup", "Meetup"), ("conference", "Conference"), ("workshop", "Workshop"), ("social", "Social"), ("other", "Other")], db_index=True, default="other", max_length=20),
        ),
        migrations.AddField(
            model_name="event",
            name="attendance_mode",
            field=models.CharField(choices=[("physical", "Physical"), ("online", "Online"), ("hybrid", "Hybrid")], db_index=True, default="physical", max_length=20),
        ),
        migrations.AddField(
            model_name="event",
            name="original_url",
            field=models.URLField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="event",
            name="original_platform",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="event",
            name="published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="event",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="event",
            name="source",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to="events.eventsource"),
        ),
        migrations.AddField(
            model_name="event",
            name="promoted_from",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="canonical_events", to="events.eventobservation"),
        ),
        migrations.AddIndex(
            model_name="event",
            index=models.Index(fields=["status", "starts_at"], name="events_status_starts_idx"),
        ),
    ]