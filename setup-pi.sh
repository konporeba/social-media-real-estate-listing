#!/usr/bin/env bash
# Bootstrap script for deploying social-agent on Raspberry Pi 5
# Tested on: Raspberry Pi OS Bookworm (64-bit), Raspberry Pi 5
#
# Usage (run from the project root on the Pi):
#   chmod +x setup-pi.sh && ./setup-pi.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }

echo ""
echo "  Social Agent — Raspberry Pi 5 deployment"
echo "  Project: $REPO_DIR"
echo ""

# ── 1. Architecture check ──────────────────────────────────────────────────────
ARCH=$(uname -m)
if [[ "$ARCH" != "aarch64" ]]; then
    warn "Expected aarch64, got $ARCH. System Chromium path may differ — check CHROMIUM_PATH."
fi

# ── 2. Docker ──────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    info "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    warn "Added $USER to the docker group. Log out and back in, then re-run this script."
    exit 0
fi

if ! docker compose version &>/dev/null 2>&1; then
    info "Installing Docker Compose plugin..."
    sudo apt-get update -qq
    sudo apt-get install -y docker-compose-plugin
fi

info "Docker $(docker --version | awk '{print $3}' | tr -d ',') ready."

# ── 3. cloudflared ────────────────────────────────────────────────────────────
if ! command -v cloudflared &>/dev/null; then
    info "Installing cloudflared (ARM64)..."
    sudo mkdir -p /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
        | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
    echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared bookworm main' \
        | sudo tee /etc/apt/sources.list.d/cloudflared.list
    sudo apt-get update -qq && sudo apt-get install -y cloudflared
fi

info "cloudflared $(cloudflared --version | head -1) ready."

# ── 4. npm lock file (needed for docker build's npm ci) ───────────────────────
if [[ ! -f "$REPO_DIR/frontend/package-lock.json" ]]; then
    if command -v npm &>/dev/null; then
        info "Generating frontend/package-lock.json..."
        (cd "$REPO_DIR/frontend" && npm install --package-lock-only)
    else
        warn "npm not found on the Pi. Install Node.js 20 and re-run, or generate"
        warn "frontend/package-lock.json on your dev machine and copy it here."
        warn "  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -"
        warn "  sudo apt-get install -y nodejs"
        exit 1
    fi
fi

# ── 5. .env file ──────────────────────────────────────────────────────────────
if [[ ! -f "$REPO_DIR/.env" ]]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo ""
    warn "Created .env from .env.example. Fill in ALL required values before continuing:"
    echo ""
    echo "  Required now (pipeline won't start without these):"
    echo "    ANTHROPIC_API_KEY"
    echo "    SUPABASE_URL"
    echo "    SUPABASE_SERVICE_ROLE_KEY"
    echo ""
    echo "  Required for live publishing (can use PUBLISH_MODE=shadow to test first):"
    echo "    META_ACCESS_TOKEN, META_FACEBOOK_PAGE_ID, META_INSTAGRAM_ACCOUNT_ID"
    echo "    LINKEDIN_ACCESS_TOKEN, LINKEDIN_ORGANIZATION_ID"
    echo ""
    echo "  Required for email alerts (optional but recommended):"
    echo "    GMAIL_ADDRESS, GMAIL_APP_PASSWORD"
    echo ""
    echo "  Required after Cloudflare Access is configured (step 7):"
    echo "    CLOUDFLARE_ACCESS_TEAM_DOMAIN"
    echo "    CLOUDFLARE_ACCESS_AUD"
    echo ""
    read -r -p "Press Enter once .env is saved, or Ctrl-C to exit and fill it first..."
fi

# ── 6. Build images ────────────────────────────────────────────────────────────
info "Building Docker images (first build ~10 min on Pi — Chromium apt + npm ci)..."
docker compose -f "$REPO_DIR/docker-compose.yml" build

# ── 7. Start containers ────────────────────────────────────────────────────────
info "Starting containers..."
docker compose -f "$REPO_DIR/docker-compose.yml" up -d

info "Waiting 45 s for containers to initialise..."
sleep 45
docker compose -f "$REPO_DIR/docker-compose.yml" ps

echo ""
info "Health check:"
if curl -sf http://localhost:8000/health | python3 -m json.tool; then
    info "Backend is healthy."
else
    warn "Backend not yet healthy — check logs: docker compose logs backend"
fi

# ── 8. Cloudflare Tunnel ──────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════"
echo "  Cloudflare Tunnel setup (one-time, interactive)"
echo "══════════════════════════════════════════════════════"
echo ""
echo "Step 1 — Log in to Cloudflare (opens a browser or prints a URL):"
echo "  cloudflared tunnel login"
echo ""
echo "Step 2 — Create the tunnel:"
echo "  cloudflared tunnel create social-agent"
echo ""
echo "Step 3 — Route your domain to the tunnel:"
echo "  cloudflared tunnel route dns social-agent agent.yourdomain.com"
echo ""
echo "Step 4 — Update cloudflare-tunnel.yml:"
echo "  Replace <TUNNEL-ID> with the UUID from step 2."
echo "  Replace agent.yourdomain.com with your actual hostname."
echo ""
echo "Step 5 — Install as a system service (auto-starts on boot):"
echo "  sudo cloudflared --config $REPO_DIR/cloudflare-tunnel.yml service install"
echo "  sudo systemctl start cloudflared"
echo ""
echo "Step 6 — Configure Cloudflare Access in Zero Trust dashboard:"
echo "  https://one.dash.cloudflare.com → Access → Applications"
echo "  Add an application for agent.yourdomain.com."
echo "  Note the Audience tag, add to .env as CLOUDFLARE_ACCESS_AUD."
echo "  Set AUTH_DISABLED=false in .env, then: docker compose restart backend"
echo ""
echo "══════════════════════════════════════════════════════"
echo ""
info "Setup complete. Dashboard (shadow mode): http://localhost:8000"
info "After tunnel is live: https://agent.yourdomain.com"
