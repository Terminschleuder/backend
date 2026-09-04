#!/bin/sh
# Container entrypoint — makes a fresh deployment self-bootstrapping.
#
# On every container start: wait for the database, apply migrations, run the
# idempotent `bootstrap` (operator superuser from env, ingestion group + its
# permissions, city gazetteer — never demo data), then hand off to the command
# (gunicorn in prod, runserver via the dev compose override).
#
# One-off jobs (e.g. `docker run --rm <image> python manage.py shell`) can
# skip the tasks with ENTRYPOINT_SKIP_TASKS=1 so they don't touch the DB.
set -e

if [ "${ENTRYPOINT_SKIP_TASKS:-0}" = "1" ]; then
    echo "[entrypoint] ENTRYPOINT_SKIP_TASKS=1 — skipping tasks, starting: $*"
    exec "$@"
fi

# Fresh hosts race the database container's startup; retry bounded instead of
# crash-looping (some hosters give up on a container after N failed starts).
echo "[entrypoint] Applying database migrations..."
attempt=0
until python manage.py migrate --noinput; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "[entrypoint] Database not reachable after 30 attempts; giving up." >&2
        exit 1
    fi
    echo "[entrypoint] Database not ready yet; retrying in 2s..."
    sleep 2
done

echo "[entrypoint] Running bootstrap (idempotent: superuser, ingestion group, cities)..."
python manage.py bootstrap

echo "[entrypoint] Bootstrap complete. Starting: $*"
exec "$@"