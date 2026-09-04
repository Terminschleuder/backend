# Third-party notices

This project is licensed under the Apache License 2.0 — see [LICENSE](LICENSE).
This file is the inventory of third-party software it builds on: the Python
dependencies declared in `requirements.txt` (pinned), the transitive packages
those pull into the shipped image, the system libraries bundled into the Docker
image, and the base images. Versions below reflect the current pin state;
licenses are taken from the respective package registries.

## Runtime dependencies (declared in `requirements.txt`, shipped in the image)

| Library | Version | License | Upstream |
| --- | --- | --- | --- |
| Django | 6.1 | BSD-3-Clause | https://github.com/django/django |
| django-cors-headers | 4.9.0 | MIT | https://github.com/adamchainz/django-cors-headers |
| django-environ | 0.14.0 | MIT | https://django-environ.readthedocs.org |
| django-filter | 26.1 | BSD-3-Clause | https://github.com/carltongibson/django-filter |
| djangorestframework | 3.18.0 | BSD-3-Clause | https://github.com/encode/django-rest-framework |
| djangorestframework-simplejwt | 5.5.1 | MIT | https://github.com/jazzband/djangorestframework-simplejwt |
| drf-spectacular | 0.30.0 | BSD-3-Clause | https://github.com/tfranzel/drf-spectacular |
| gunicorn | 26.0.0 | MIT | https://gunicorn.org |
| Pillow | 12.3.0 | MIT-CMU | https://github.com/python-pillow/Pillow |
| psycopg | 3.3.4 | LGPL-3.0-only | https://psycopg.org/ |
| psycopg-binary | 3.3.4 | LGPL-3.0-only | https://psycopg.org/ |
| PyJWT | 2.13.0 | MIT | https://github.com/jpadilla/pyjwt |
| sqlparse | 0.6.0 | BSD-3-Clause | https://github.com/andialbrecht/sqlparse |
| whitenoise | 6.12.0 | MIT | https://github.com/evansd/whitenoise |

## Test/dev-only dependencies (declared in `requirements.txt`, not imported at runtime)

| Library | Version | License | Upstream |
| --- | --- | --- | --- |
| pytest | 9.1.1 | MIT | https://github.com/pytest-dev/pytest |
| pytest-django | 4.14.0 | BSD-3-Clause | https://github.com/pytest-dev/pytest-django |
| iniconfig | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| pluggy | 1.6.0 | MIT | https://github.com/pytest-dev/pluggy |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |

## Transitive dependencies (installed in the image via the above)

| Library | Version | License | Upstream |
| --- | --- | --- | --- |
| asgiref | 3.12.1 | BSD-3-Clause | https://github.com/django/asgiref/ |
| attrs | 26.1.0 | MIT | https://github.com/python-attrs/attrs |
| inflection | 0.5.1 | MIT | https://github.com/jpvanhal/inflection |
| jsonschema | 4.26.0 | MIT | https://github.com/python-jsonschema/jsonschema |
| jsonschema-specifications | 2025.9.1 | MIT | https://github.com/python-jsonschema/jsonschema-specifications |
| Pygments | 2.20.0 | BSD-2-Clause | https://github.com/pygments/pygments |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| referencing | 0.37.0 | MIT | https://github.com/python-jsonschema/referencing |
| rpds-py | 2026.6.3 | MIT | https://github.com/crate-py/rpds |
| uritemplate | 4.2.0 | BSD-3-Clause OR Apache-2.0 | https://uritemplate.readthedocs.org |

## System libraries bundled into the app image (apt packages in `Dockerfile`)

| Library | License | Upstream |
| --- | --- | --- |
| GDAL | MIT (X11 style) | https://gdal.org |
| GEOS | LGPL-2.1-or-later | https://libgeos.org |
| PROJ | MIT | https://proj.org |
| libpq | PostgreSQL License | https://www.postgresql.org |

## Base images

| Image | Contents license | Upstream |
| --- | --- | --- |
| `python:3.14-slim-bookworm` (app image) | CPython: PSF License Version 2; Debian base: DFSG-free | https://www.python.org / https://www.debian.org |
| `postgres:18` (db image, `Dockerfile.db`) | PostgreSQL: PostgreSQL License (BSD-style); Debian base: DFSG-free | https://www.postgresql.org |
| PostGIS extension (installed in the db image) | GPL-2.0-or-later | https://postgis.net |

## Notes

- Version pins live in `requirements.txt`; regenerate this table when they
  change (licenses via the PyPI JSON API, e.g.
  `https://pypi.org/pypi/<name>/<version>/json`).
- The db image (`ghcr.io/terminschleuder/backend-db`) is built from this repo's
  `Dockerfile.db`, so its third-party set (PostgreSQL, PostGIS) is listed here
  rather than anywhere else.