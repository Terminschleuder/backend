from django.apps import AppConfig


class AdminConfig(AppConfig):
    """The backoffice admin app.

    Custom ``AdminSite`` instances are NOT auto-discovered by Django (only the
    default ``admin.site`` is). We import the registry module in ``ready()`` so
    the models register onto ``terminschleuder_admin``.

    The label is overridden because the package is named ``admin`` and would
    otherwise clash with ``django.contrib.admin``'s app label ("admin").
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "admin"
    label = "backoffice"

    def ready(self):
        from . import admin  # noqa: F401  (runs the registrations)