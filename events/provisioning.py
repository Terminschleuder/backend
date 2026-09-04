"""Group provisioning for the ingestion surface.

Single source of truth for the ``ingestion`` group and its permission set,
shared by the ``bootstrap`` and ``create_service_account`` management
commands, ``seed_demo``, and the test fixtures. See
``events.permissions.IsIngestionService`` for what each permission is for.
"""

from django.contrib.auth.models import Group, Permission

INGESTION_GROUP_NAME = "ingestion"

# Codenames within the ``events`` app the ``ingestion`` group must carry so a
# service account in it can drive the whole /api/ingestion/ surface.
INGESTION_CODENAMES = [
    "view_eventsource",
    "add_ingestionrun", "change_ingestionrun", "view_ingestionrun",
    "add_eventobservation", "view_eventobservation",
]


def ensure_ingestion_group() -> Group:
    """Get or create the ``ingestion`` group carrying its permission set.

    Idempotent and additive: permissions are only ever added, never removed —
    a re-run (e.g. every container start via ``bootstrap``) never strips an
    extra permission an operator granted on purpose.
    """
    group, _ = Group.objects.get_or_create(name=INGESTION_GROUP_NAME)
    group.permissions.add(*Permission.objects.filter(
        content_type__app_label="events",
        codename__in=INGESTION_CODENAMES,
    ))
    return group