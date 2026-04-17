#!/usr/bin/env bash
# =============================================================================
# riks-context-engine — Deploy Script
# =============================================================================
# Usage:
#   ./scripts/deploy.sh [--image-tag <tag>] [--skip-healthcheck] [--env <file>]
#
# Environment variables (can be set in .env or inherited from CI secrets):
#   REGISTRY          — Docker registry (default: ghcr.io)
#   IMAGE_NAME         — Image name (default: vopsiton/riks-context-engine)
#   SERVER_HOST        — VPS host (required for VPS deploy)
#   DEPLOY_TARGET      — "vps" or "cloudflare" (default: vps)
#   HEALTHCHECK_URL    — URL to health check endpoint
#   HEALTHCHECK_RETRIES— Number of retries (default: 10)
#   HEALTHCHECK_DELAY  — Delay between retries in seconds (default: 5)
#   DOCKER_COMPOSE_FILE— Path to docker-compose file (default: docker-compose.yml)
#
# Required secrets (set in GitHub repo → Settings → Secrets):
#   SERVER_HOST   — IP or hostname of your VPS
#   SSH_KEY       — Private SSH key for server access
#   DEPLOY_TARGET — Set to "vps" (default)
# =============================================================================

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
REGISTRY="${REGISTRY:-ghcr.io}"
IMAGE_NAME="${IMAGE_NAME:-vopsiton/riks-context-engine}"
DEPLOY_TARGET="${DEPLOY_TARGET:-vps}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://localhost:8000/health}"
HEALTHCHECK_RETRIES="${HEALTHCHECK_RETRIES:-10}"
HEALTHCHECK_DELAY="${HEALTHCHECK_DELAY:-5}"
DOCKER_COMPOSE_FILE="${DOCKER_COMPOSE_FILE:-docker-compose.yml}"
DEPLOY_LOG="/tmp/riks-deploy-$(date +%Y%m%d-%H%M%S).log"

# ── CLI args ─────────────────────────────────────────────────────────────────
SKIP_HEALTHCHECK=false
ENV_FILE=".env"
IMAGE_TAG=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --image-tag)
      IMAGE_TAG="$2"
      shift 2
      ;;
    --skip-healthcheck)
      SKIP_HEALTHCHECK=true
      shift
      ;;
    --env)
      ENV_FILE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--image-tag <tag>] [--skip-healthcheck] [--env <file>]"
      exit 1
      ;;
  esac
done

# Derive image tag from git sha if not provided
if [[ -z "$IMAGE_TAG" ]]; then
  IMAGE_TAG="sha-$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
fi

FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

# ── Logging ──────────────────────────────────────────────────────────────────
log() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[$ts] $*"
  echo "[$ts] $*" >> "$DEPLOY_LOG"
}

log_section() {
  log "============================================================================="
  log "$*"
  log "============================================================================="
}

# ── Pre-flight checks ────────────────────────────────────────────────────────
log_section "PRE-FLIGHT CHECKS"

if [[ ! -f "$DOCKER_COMPOSE_FILE" ]]; then
  log "ERROR: docker-compose.yml not found at '$DOCKER_COMPOSE_FILE'"
  exit 1
fi

# Load env file if it exists
if [[ -f "$ENV_FILE" ]]; then
  log "Loading environment from: $ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  log "WARNING: $ENV_FILE not found — using environment variables only"
fi

log "Deploy target : $DEPLOY_TARGET"
log "Image tag     : $IMAGE_TAG"
log "Full image    : $FULL_IMAGE"
log "Deploy log    : $DEPLOY_LOG"

# ── VPS Deployment Path ───────────────────────────────────────────────────────
if [[ "$DEPLOY_TARGET" == "vps" ]]; then
  log_section "VPS DEPLOYMENT"

  if [[ -z "${SERVER_HOST:-}" ]]; then
    log "ERROR: SERVER_HOST is not set. Configure it in GitHub Secrets."
    exit 1
  fi

  # Ensure the deploy directory exists on the server
  DEPLOY_DIR="${DEPLOY_DIR:-/opt/riks-context-engine}"

  log "Connecting to server: $SERVER_HOST"
  log "Deploy directory: $DEPLOY_DIR"

  # ── Remote server operations ─────────────────────────────────────────────
  ssh_cmd() {
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
      "${SERVER_USER:-ubuntu}@${SERVER_HOST}" "$@"
  }

  # Test connectivity
  ssh_cmd "echo 'SSH connection OK'"

  # Stop existing containers
  log "Stopping existing containers..."
  ssh_cmd "cd '$DEPLOY_DIR' && docker compose down --remove-orphans 2>/dev/null || true"

  # Pull latest image
  log "Pulling image: $FULL_IMAGE"
  ssh_cmd "docker pull '$FULL_IMAGE'"

  # Update docker-compose image reference
  log "Updating image reference in docker-compose..."
  ssh_cmd "cd '$DEPLOY_DIR' && \
    docker compose pull && \
    IMAGE_TAG='$IMAGE_TAG' docker compose up -d --no-deps app"

  # Prune old images to save disk space
  log "Pruning unused Docker images..."
  ssh_cmd "docker image prune -f" || true

  # ── Health check ─────────────────────────────────────────────────────────
  if [[ "$SKIP_HEALTHCHECK" == "true" ]]; then
    log "Skipping health check (--skip-healthcheck)"
  else
    log_section "HEALTH CHECK"
    health_check
  fi

  log_section "DEPLOY COMPLETE"
  log "Image   : $FULL_IMAGE"
  log "Log file: $DEPLOY_LOG"

# ── Cloudflare Deployment Path ────────────────────────────────────────────────
elif [[ "$DEPLOY_TARGET" == "cloudflare" ]]; then
  log_section "CLOUDFLARE DEPLOYMENT"

  if [[ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
    log "ERROR: CLOUDFLARE_ACCOUNT_ID is not set."
    exit 1
  fi
  if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    log "ERROR: CLOUDFLARE_API_TOKEN is not set."
    exit 1
  fi

  log "Account ID: $CLOUDFLARE_ACCOUNT_ID"
  log "Building OCI image locally for Cloudflare Workers/Pages upload..."

  # Cloudflare Workers/Pages typically need a built artifact
  # Build the image (used for containerized Workers preview)
  docker build -t "$FULL_IMAGE" .

  log "Cloudflare deployment configured."
  log "Set up Cloudflare Pages action in your GitHub Actions workflow."
  log "See: https://developers.cloudflare.com/pages/platform/github-integration/"

  log_section "CLOUDFLARE DEPLOY CONFIGURATION COMPLETE"

else
  log "ERROR: Unknown DEPLOY_TARGET='$DEPLOY_TARGET'. Use 'vps' or 'cloudflare'."
  exit 1
fi

# ── Health Check Function ─────────────────────────────────────────────────────
health_check() {
  local attempt=1
  local max_attempts="$HEALTHCHECK_RETRIES"
  local url="$HEALTHCHECK_URL"

  log "Health check URL: $url"
  log "Retries: $max_attempts, Delay: ${HEALTHCHECK_DELAY}s"

  while [[ $attempt -le $max_attempts ]]; do
    log "[$attempt/$max_attempts] Checking $url ..."

    if curl -sf --max-time 10 "$url" > /dev/null 2>&1; then
      log "[$attempt/$max_attempts] ✓ Health check PASSED"
      return 0
    fi

    log "[$attempt/$max_attempts] ✗ Health check FAILED — retrying in ${HEALTHCHECK_DELAY}s ..."
    sleep "$HEALTHCHECK_DELAY"
    attempt=$((attempt + 1))
  done

  log "ERROR: Health check FAILED after $max_attempts attempts"
  log "Deploy log: $DEPLOY_LOG"
  return 1
}
