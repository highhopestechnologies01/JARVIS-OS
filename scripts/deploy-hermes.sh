#!/usr/bin/env bash
# ============================================================
# JARVIS OS — Deploy Hermes (hot-patch)
# Pulls latest code from GitHub and redeploys Hermes without downtime.
# Run from VPS: bash scripts/deploy-hermes.sh
# ============================================================

set -euo pipefail

REPO="/opt/jarvis-repo"
CONTAINER="jarvis-hermes"
HEALTH_URL="http://localhost:8001/api/v1/health/ready"

echo "🚀 Deploying Hermes..."

cd "$REPO"

echo "  → Pulling latest code..."
git pull origin main

echo "  → Copying source into container..."
find hermes/src -name "*.py" | while read f; do
  dest="/app/${f#hermes/}"
  dir=$(dirname "$dest")
  docker exec "$CONTAINER" mkdir -p "$dir" 2>/dev/null || true
  docker cp "$f" "$CONTAINER:$dest"
done

echo "  → Restarting container..."
docker restart "$CONTAINER"
sleep 4

echo "  → Verifying health..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL")
if [ "$STATUS" = "200" ]; then
  echo "  ✅ Hermes healthy (HTTP $STATUS)"
else
  echo "  ❌ Hermes health check failed (HTTP $STATUS)"
  docker logs "$CONTAINER" --tail 20
  exit 1
fi
