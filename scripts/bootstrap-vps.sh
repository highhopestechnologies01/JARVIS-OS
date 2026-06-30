#!/usr/bin/env bash
# ============================================================
# JARVIS OS — VPS Bootstrap Script (Linux)
# Run once on your Linux VPS to configure the JARVIS Brain.
# Usage: curl -sL <url> | bash  OR  copy and run directly
# ============================================================

set -euo pipefail

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

info()  { echo -e "${GREEN}[JARVIS]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[[ "$(uname -s)" == "Linux" ]] || error "This script must run on Linux (VPS)"

info "Starting JARVIS OS VPS bootstrap..."

# --- System update ---
info "Updating system packages..."
apt-get update -qq && apt-get upgrade -y -qq

# --- Core packages ---
info "Installing system dependencies..."
apt-get install -y -qq \
  curl wget git jq unzip \
  ufw fail2ban \
  ca-certificates gnupg lsb-release

# --- Firewall ---
info "Configuring UFW firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
# Only allow HTTP/HTTPS for Coolify reverse proxy
ufw allow 80/tcp
ufw allow 443/tcp
# Tailscale interface — allow all on tailscale0
ufw allow in on tailscale0
ufw --force enable
info "Firewall: enabled (SSH + 80/443 + Tailscale)"

# --- Fail2ban ---
info "Starting fail2ban..."
systemctl enable --now fail2ban

# --- Docker ---
if ! command -v docker &>/dev/null; then
  info "Installing Docker..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
  info "Docker: installed"
else
  info "Docker: $(docker --version)"
fi

# --- Add current user to docker group ---
if [[ -n "${SUDO_USER:-}" ]]; then
  usermod -aG docker "$SUDO_USER"
  info "Added $SUDO_USER to docker group (re-login required)"
fi

# --- Tailscale ---
if ! command -v tailscale &>/dev/null; then
  info "Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
  warn "Run: tailscale up --advertise-routes=<your-subnet>"
  warn "Then approve at https://login.tailscale.com"
else
  info "Tailscale: $(tailscale --version | head -1)"
fi

# --- Clone repo ---
REPO_DIR="/opt/jarvis-os"
if [[ ! -d "$REPO_DIR" ]]; then
  info "Cloning JARVIS OS repository..."
  warn "You will need to enter your GitHub credentials or SSH key"
  read -rp "  GitHub repo URL (e.g. git@github.com:user/JARVIS-OS.git): " REPO_URL
  git clone "$REPO_URL" "$REPO_DIR"
  cd "$REPO_DIR"
  info "Repository cloned to $REPO_DIR"
else
  info "Repository: already exists at $REPO_DIR"
  cd "$REPO_DIR"
  git pull origin main
fi

# --- .env setup ---
if [[ ! -f "$REPO_DIR/.env" ]]; then
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  warn ".env created — YOU MUST FILL IN CREDENTIALS before running deploy.sh"
  warn "Edit: nano $REPO_DIR/.env"
else
  info ".env: already exists"
fi

# --- Create log directories ---
mkdir -p /opt/jarvis-os/hermes/logs
info "Log directories created"

info ""
info "========================================="
info "VPS bootstrap complete!"
info ""
info "Next steps:"
info "  1. Run: tailscale up"
info "  2. Fill credentials: nano $REPO_DIR/.env"
info "  3. Run: $REPO_DIR/scripts/deploy.sh"
info "========================================="
