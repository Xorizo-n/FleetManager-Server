#!/bin/bash
# Пересобирает и перезапускает только frontend-контейнер.
# --no-deps гарантирует что postgres/backend/redis не трогаются.
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$COMPOSE_DIR"

echo "[deploy-frontend] Building..."
docker compose build frontend

echo "[deploy-frontend] Restarting (no-deps)..."
docker compose up -d --no-deps frontend

echo "[deploy-frontend] Done."
docker compose ps frontend
