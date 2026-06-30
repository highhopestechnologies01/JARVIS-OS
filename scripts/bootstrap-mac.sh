#!/usr/bin/env bash
# ============================================================
# JARVIS OS — Mac Bootstrap Script
# Run once on your MacBook to configure the control station.
# Usage: chmod +x scripts/bootstrap-mac.sh && ./scripts/bootstrap-mac.sh
# ============================================================

set -euo pipefail

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

info()    { echo -e "${GREEN}[JARVIS]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

info "Starting JARVIS OS Mac bootstrap..."

# --- Homebrew ---
if ! command -v brew &>/dev/null; then
  info "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
  info "Homebrew: already installed"
fi

# --- Core tools ---
info "Installing core tools..."
brew install git curl wget jq

# --- SSH key ---
if [[ ! -f "$HOME/.ssh/id_ed25519" ]]; then
  info "Generating SSH key..."
  read -rp "  Enter your email: " SSH_EMAIL
  ssh-keygen -t ed25519 -C "$SSH_EMAIL" -f "$HOME/.ssh/id_ed25519" -N ""
  info "SSH public key:"
  cat "$HOME/.ssh/id_ed25519.pub"
  warn "Copy this key to your VPS: authorized_keys"
else
  info "SSH key: already exists"
fi

# --- Git config ---
if [[ -z "$(git config --global user.name)" ]]; then
  read -rp "  Enter your name for Git: " GIT_NAME
  read -rp "  Enter your email for Git: " GIT_EMAIL
  git config --global user.name "$GIT_NAME"
  git config --global user.email "$GIT_EMAIL"
  git config --global init.defaultBranch main
  git config --global pull.rebase false
  info "Git configured"
else
  info "Git: already configured"
fi

# --- Tailscale ---
if ! command -v tailscale &>/dev/null; then
  info "Installing Tailscale..."
  brew install tailscale
  warn "Run: sudo tailscale up"
  warn "Then approve the device at https://login.tailscale.com"
else
  info "Tailscale: already installed"
fi

# --- Node.js (for Dashboard dev) ---
if ! command -v node &>/dev/null; then
  info "Installing Node.js 20..."
  brew install node@20
  echo 'export PATH="/opt/homebrew/opt/node@20/bin:$PATH"' >> ~/.zprofile
else
  info "Node.js: $(node --version)"
fi

# --- Python 3.12 ---
if ! python3 --version 2>/dev/null | grep -q "3.12"; then
  info "Installing Python 3.12..."
  brew install python@3.12
else
  info "Python: $(python3 --version)"
fi

# --- Claude Code ---
if ! command -v claude &>/dev/null; then
  info "Installing Claude Code..."
  npm install -g @anthropic-ai/claude-code
else
  info "Claude Code: $(claude --version 2>/dev/null || echo 'installed')"
fi

# --- .env setup ---
if [[ ! -f ".env" ]]; then
  cp .env.example .env
  warn ".env created from .env.example — fill in your credentials!"
else
  info ".env: already exists"
fi

info ""
info "========================================="
info "Mac bootstrap complete!"
info ""
info "Next steps:"
info "  1. Add SSH public key to your VPS"
info "  2. Fill in .env with credentials"
info "  3. Run: sudo tailscale up (if not done)"
info "  4. Run: ./scripts/bootstrap-vps.sh on VPS"
info "========================================="
