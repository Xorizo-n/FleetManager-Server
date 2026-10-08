#!/bin/bash
# Пересобирает frontend и синхронизирует env во всех контейнерах.
# Безопасно: не трогает postgres-данные.
set -e
cd /opt/fleet-manager

echo "[deploy] Building frontend image..."
docker compose build frontend

echo "[deploy] Restarting frontend (no-deps)..."
docker compose up -d --no-deps frontend

echo "[deploy] Syncing env in celery workers (in case .env changed)..."
docker compose up -d --no-deps --force-recreate celery celery-beat

echo "[deploy] Done. Postgres not touched."
