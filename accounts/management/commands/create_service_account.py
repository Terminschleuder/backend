"""Create a service/system account with a random secret.

Usage:
    python manage.py create_service_account <username> [--group GROUPNAME] \\
        [--description "..."]

The generated secret is printed once. Use it (as the password) to obtain a JWT
at /api/auth/token/, or create a long-lived API key for the account.
"""

import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Create a non-interactive service/system account with a random secret."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Username for the service account.")
        parser.add_argument("--group", help="Group name to add the account to.")
        parser.add_argument("--description", default="", help="Free-form description.")

    def handle(self, *args, **options):
        username = options["username"]
        group_name = options.get("group")
        description = options.get("description", "")

        if User.objects.filter(username=username).exists():
            raise CommandError(f"A user named {username!r} already exists.")

        secret = secrets.token_urlsafe(32)
        user = User(
            username=username,
            is_service_account=True,
            description=description,
        )
        user.set_password(secret)
        # Service accounts are non-interactive; keep them out of the staff UI.
        user.is_staff = False
        user.save()

        if group_name:
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
            self.stdout.write(f"Added to group: {group_name}")

        self.stdout.write(
            self.style.SUCCESS(f"Created service account {username!r}.")
        )
        self.stdout.write("Secret (shown once — store it securely):")
        self.stdout.write(secret)