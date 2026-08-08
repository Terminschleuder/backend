from django.contrib import admin


class TerminschleuderAdminSite(admin.AdminSite):
    """The human backoffice for the terminschleuder API.

    Mounted at the root URL (``/``). Reuses the project's custom ``User`` and
    Django session auth. The site ``name`` stays the default ``"admin"`` so the
    built-in admin templates (which hardcode the ``admin:`` URL namespace) keep
    working.
    """

    site_header = "terminschleuder backoffice"
    site_title = "terminschleuder admin"
    index_title = "Operations"


# ``name`` defaults to "admin" intentionally — see the class docstring.
terminschleuder_admin = TerminschleuderAdminSite()