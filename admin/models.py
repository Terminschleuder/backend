from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class ServiceAccountManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_service_account=True)


class ServiceAccount(User):
    """Proxy over ``accounts.User`` exposing only service/system accounts.

    A proxy model shares the ``accounts_user`` table but gives the backoffice a
    dedicated, pre-filtered list and a tailored admin (no password fields — the
    app secret is generated and shown once).
    """

    class Meta:
        proxy = True
        verbose_name = "service account"
        verbose_name_plural = "service accounts"

    objects = ServiceAccountManager()