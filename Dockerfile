# Backend image for terminschleuder.
#
# Bundles GDAL/GEOS/PROJ system libraries so django.contrib.gis works without
# any host GIS installs — the image is self-contained (prod just pulls it).
FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

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

EXPOSE 8000

# Production default. docker-compose overrides this to runserver for dev.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]