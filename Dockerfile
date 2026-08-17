# Backend image for terminschleuder.
#
# Bundles GDAL/GEOS/PROJ system libraries so django.contrib.gis works without
# any host GIS installs — the image is self-contained (prod just pulls it).
# Runs as a non-root user; the writable /app/media is pre-created with the
# right ownership so uploads work under a named volume (and under a bind mount
# the operator chowns to uid 1001).
FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Keep compiled bytecode out of the bind-mounted source tree (dev) and
    # let non-root write pyc to a tmp prefix instead of the read-only /app.
    PYTHONPYCACHEPREFIX=/tmp/pyc

# GIS runtime libs (Django loads libgdal via ctypes — no pip GDAL package),
# plus libpq-dev/build-essential in case any wheel needs building.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gdal-bin \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
        libpq-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the application code.
COPY . .

# Non-root runtime user. uid/gid 1001 are fixed so operators can chown
# mounted volumes (e.g. media) to match. MEDIA_ROOT is /app/media; pre-create
# it owned by the app user so a fresh named volume inherits the ownership.
RUN groupadd --system --gid 1001 terminschleuder \
    && useradd --system --uid 1001 --gid 1001 --home-dir /app --shell /sbin/nologin terminschleuder \
    && mkdir -p /app/media \
    && chown -R 1001:1001 /app

# OCI image metadata. CI (docker/metadata-action) appends source/revision/version.
LABEL org.opencontainers.image.title="terminschleuder-backend" \
      org.opencontainers.image.description="Django + DRF + PostGIS backend for the terminschleuder event directory" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="docker.io/library/python:3.14-slim-bookworm"

USER 1001:1001

EXPOSE 8000

# Production default. docker-compose overrides this to runserver for dev.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]