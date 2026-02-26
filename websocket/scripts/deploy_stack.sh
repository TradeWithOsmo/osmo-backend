#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

on_exit() {
  rc=$?
  if [ "$rc" -ne 0 ]; then
    log "[deploy] FAILED (exit=$rc)"
  fi
}
trap on_exit EXIT

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
    return
  fi

  log "[deploy] ERROR: neither 'docker compose' nor 'docker-compose' is available"
  exit 127
}

if docker compose version >/dev/null 2>&1; then
  log "[deploy] using docker compose (v2)"
else
  log "[deploy] using docker-compose (v1)"
fi

log "[deploy] starting full stack build/up..."
compose up -d --build

log "[deploy] forcing idempotent Uptime Kuma bootstrap..."
compose run --rm uptime-kuma-bootstrap

log "[deploy] stack status:"
compose ps

log "[deploy] SUCCESS"
