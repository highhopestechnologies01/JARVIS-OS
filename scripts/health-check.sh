#!/usr/bin/env bash
# ============================================================
# JARVIS OS — Health Check
# Checks all services and prints a status summary.
# ============================================================

set -euo pipefail

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[1;33m"
NC="\033[0m"

PASS=0
FAIL=0

check() {
  local name="$1"
  local url="$2"
  local expected="${3:-200}"

  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")

  if [[ "$code" == "$expected" ]]; then
    echo -e "  ${GREEN}✓${NC}  $name ($code)"
    ((PASS++))
  else
    echo -e "  ${RED}✗${NC}  $name (got $code, expected $expected)"
    ((FAIL++))
  fi
}

container_running() {
  local name="$1"
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${name}$"; then
    echo -e "  ${GREEN}✓${NC}  Container: $name"
    ((PASS++))
  else
    echo -e "  ${RED}✗${NC}  Container: $name (not running)"
    ((FAIL++))
  fi
}

echo ""
echo "═══════════════════════════════════════"
echo "  JARVIS OS — Health Check"
echo "═══════════════════════════════════════"
echo ""

# --- Docker containers ---
echo "Containers:"
for container in jarvis-postgres jarvis-redis jarvis-hermes jarvis-dashboard jarvis-n8n jarvis-prometheus jarvis-grafana; do
  container_running "$container"
done

echo ""
echo "HTTP endpoints:"
check "Hermes health"    "http://localhost:8000/health"
check "Hermes ready"     "http://localhost:8000/health/ready"
check "Dashboard"        "http://localhost:3000"
check "n8n"              "http://localhost:5678/healthz"
check "Prometheus"       "http://localhost:9090/-/healthy"
check "Grafana"          "http://localhost:3001/api/health"

echo ""
echo "═══════════════════════════════════════"
TOTAL=$((PASS + FAIL))
if [[ $FAIL -eq 0 ]]; then
  echo -e "  ${GREEN}ALL SYSTEMS GO${NC} — $PASS/$TOTAL checks passed"
else
  echo -e "  ${YELLOW}DEGRADED${NC} — $PASS/$TOTAL passed, ${RED}$FAIL failed${NC}"
fi
echo "═══════════════════════════════════════"
echo ""

exit $FAIL
