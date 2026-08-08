"""Add service-account fields to User and create the APIKey model."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_service_account",
            field=models.BooleanField(
                default=False,
                help_text="Designates this as a non-interactive service/system account.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.CreateModel(
            name="APIKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(help_text="Label for this key.", max_length=120)),
                (
                    "prefix",
                    models.CharField(
                        db_index=True,
                        help_text="Public prefix to identify the key.",
                        max_length=16,
                    ),
                ),
                ("hashed_key", models.CharField(max_length=64, unique=True)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("revoked", models.BooleanField(default=False)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="api_keys",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "db_table": "accounts_apikey",
                "ordering": ["-created"],
            },
        ),
    ]