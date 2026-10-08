#!/bin/bash
_sync_password() {
  local tries=0
  while ! pg_isready -h /var/run/postgresql -U "${POSTGRES_USER:-postgres}" -q 2>/dev/null; do
    sleep 1
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
      echo "[postgres-entrypoint] Timeout waiting for postgres socket"
      return
    fi
  done
  psql -h /var/run/postgresql -U "${POSTGRES_USER:-postgres}" -d postgres \
    -c "ALTER USER \"${POSTGRES_USER:-postgres}\" WITH PASSWORD '${POSTGRES_PASSWORD}';" \
    > /dev/null 2>&1 \
    && echo "[postgres-entrypoint] Password synced with env." \
    || echo "[postgres-entrypoint] Password sync failed."
}

_sync_password &

exec /usr/local/bin/docker-entrypoint.sh postgres "$@"
