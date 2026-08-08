#!/usr/bin/env bash
#
# start.sh — build and run the backend + PostGIS database with Docker Compose.
#
# Usage:
#   ./start.sh           build (if needed) and run db + web
#   ./start.sh --build    force a rebuild
#
# On Ctrl-C / kill the stack is stopped with `docker compose down`. The
# database data volume (pgdata) is kept across runs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

log()  { printf '\033[1;34m[start.sh]\033[0m %s\n' "$*"; }

BUILD_FLAG=""
if [[ "${1:-}" == "--build" ]]; then
  BUILD_FLAG="--build"
fi

cleanup() {
  log "Stopping the stack (docker compose down)..."
  docker compose down
  log "Stopped. The pgdata volume is kept."
}
trap cleanup EXIT INT TERM

log "Starting terminschleuder with Docker Compose..."
log "API:    http://127.0.0.1:8000/api/   Admin: http://127.0.0.1:8000/admin/"
log "Press Ctrl-C to stop (data volume is retained)."

# Run in the foreground. Ctrl-C stops compose; the trap ensures `down` runs.
docker compose up ${BUILD_FLAG}