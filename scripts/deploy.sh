#!/usr/bin/env bash
# ============================================================
# JARVIS OS — Deploy Script
# Pulls latest code and restarts services on VPS.
# Run from: VPS at /opt/jarvis-os
# ============================================================

set -euo pipefail

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

info()  { echo -e "${GREEN}[DEPLOY]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}   $*"; }
error() { echo -e "${RED}[ERROR]${NC}  $*"; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -f $REPO_DIR/infrastructure/docker-compose.yml --env-file $REPO_DIR/.env"

# --- Pre-flight checks ---
[[ -f "$REPO_DIR/.env" ]] || error ".env not found at $REPO_DIR/.env — run bootstrap-vps.sh first"
command -v docker &>/dev/null || error "Docker not installed"

# Check critical secrets are set
source "$REPO_DIR/.env"
[[ "${POSTGRES_PASSWORD:-}" != "change_me_strong_password" ]] || \
  warn "POSTGRES_PASSWORD is still default! Update .env before going to production."

# --- Pull latest code ---
info "Pulling latest code from git..."
cd "$REPO_DIR"
git pull origin main

# --- Build images ---
info "Building Docker images..."
$COMPOSE build --no-cache hermes dashboard

# --- Start / update services ---
info "Starting services..."
$COMPOSE up -d

# --- Wait for health ---
info "Waiting for services to be healthy..."
sleep 10

# --- Health check ---
info "Running health check..."
bash "$REPO_DIR/scripts/health-check.sh"

info ""
info "========================================="
info "Deployment complete!"
info ""
info "Services:"
info "  Dashboard:  http://localhost:3000 (or VPS Tailscale IP)"
info "  Hermes API: http://localhost:8000/docs"
info "  n8n:        http://localhost:5678"
info "  Grafana:    http://localhost:3001"
info "========================================="
