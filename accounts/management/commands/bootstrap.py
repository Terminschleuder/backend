"""Idempotent first-boot provisioning for a fresh deployment.

Usage:
    python manage.py bootstrap

Runs on every container start (see ``docker-entrypoint.sh``) and makes a
fresh database volume usable: it ensures the operator superuser, the
``ingestion`` group with its permission set, and the city gazetteer —
everything you cannot run a deployment without, and nothing you wouldn't
want in production.

What it does:

1. **Superuser** — provisioned from the standard Django environment variables
   ``DJANGO_SUPERUSER_USERNAME`` / ``DJANGO_SUPERUSER_PASSWORD`` (and optional
   ``DJANGO_SUPERUSER_EMAIL``). Never overwrites: if the user already exists
   it is left untouched (rotate the password via the backoffice). Missing
   environment variables are a warning, never an error — the app is worth
   more running than not.
2. **``ingestion`` group** — created with exactly the permission set the
   extractor's service account needs (see ``events.provisioning``).
3. **City gazetteer** — ``seed_cities``, an idempotent upsert keyed on
   ``geoname_id``.

What it deliberately does NOT do:

- It does **not** run ``seed`` or ``seed_demo`` — no sample events, venues,
  organizations, demo operator, or demo observations. Production starts clean.
- It does **not** create the extractor's service account — secrets are shown
  once by design, so that stays an operator action (one-shot
  ``create_service_account`` or the backoffice), documented in the README.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

from events.provisioning import INGESTION_GROUP_NAME, ensure_ingestion_group

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Idempotent production bootstrap: operator superuser (from "
        "DJANGO_SUPERUSER_* env), the ingestion group, and the city gazetteer. "
        "Never seeds demo data; safe on every container start."
    )

    def _ensure_superuser(self):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        if not username:
            self.stdout.write(self.style.WARNING(
                "DJANGO_SUPERUSER_USERNAME not set — skipping superuser "
                "provisioning (set DJANGO_SUPERUSER_USERNAME/"
                "DJANGO_SUPERUSER_PASSWORD to auto-provision the operator)."
            ))
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(
                f"Superuser {username!r} exists; leaving untouched."
            )
            return

        if not os.environ.get("DJANGO_SUPERUSER_PASSWORD"):
            self.stdout.write(self.style.WARNING(
                f"DJANGO_SUPERUSER_PASSWORD not set — cannot create superuser "
                f"{username!r} non-interactively; skipping."
            ))
            return

        # Stock createsuperuser is not idempotent; the existence check above
        # makes the pair safe to re-run on every start. Under --noinput it
        # reads username/password/email from DJANGO_SUPERUSER_* env vars.
        call_command("createsuperuser", interactive=False, verbosity=0)
        self.stdout.write(self.style.SUCCESS(
            f"Created superuser {username!r}. Rotate the password via the "
            f"backoffice — bootstrap never touches it again."
        ))

    def handle(self, *args, **options):
        self._ensure_superuser()

        ensure_ingestion_group()
        self.stdout.write(
            f"Provisioned {INGESTION_GROUP_NAME!r} group with its permission set."
        )

        call_command("seed_cities", verbosity=0)

        self.stdout.write(self.style.SUCCESS(
            "Bootstrap complete: superuser ensured, ingestion group "
            "provisioned, city gazetteer upserted."
        ))