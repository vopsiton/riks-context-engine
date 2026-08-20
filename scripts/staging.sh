#!/usr/bin/env bash
# =============================================================================
# riks-context-engine — Staging Environment Manager
# =============================================================================
# Quick staging environment for testing CI/CD pipeline changes.
#
# Staging runs as an OVERLAY on the base docker-compose.yml:
#   docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d
# (docker-compose.staging.yml alone is NOT a standalone stack.)
#
# Compose resolution: `docker compose` plugin first, legacy `docker-compose`
# binary as fallback (detected via `command -v`).
#
# STAGING_API_URL is read from .env.staging (default http://localhost:8001).
# =============================================================================

set -euo pipefail

STAGING_CONTAINER="riks-context-engine-staging"
ENV_FILE=".env.staging"
ENV_EXAMPLE=".env.staging.example"

# ── Compose resolver (plugin first, legacy fallback) ─────────────────────────

resolve_compose() {
    if docker compose version >/dev/null 2>&1; then
        COMPOSE="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE="docker-compose"
    else
        echo "ERROR: neither 'docker compose' plugin nor 'docker-compose' binary found." >&2
        exit 1
    fi
}

# Shell-quoted env var lookup from a .env file (no `source` — keeps
# surrounding shell state intact).
env_file_get() {
    local key="$1" file="$2"
    sed -n "s/^${key}=//p" "$file" 2>/dev/null | tail -n1
}

# Read STAGING_API_URL from .env.staging (created from the example if missing).
resolve_staging_api_url() {
    if [ ! -f "$ENV_FILE" ]; then
        if [ -f "$ENV_EXAMPLE" ]; then
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            echo "==> Created ${ENV_FILE} from ${ENV_EXAMPLE}."
        else
            echo "WARNING: neither ${ENV_FILE} nor ${ENV_EXAMPLE} found." >&2
        fi
    fi
    STAGING_API_URL="$(env_file_get STAGING_API_URL "$ENV_FILE")"
    STAGING_API_URL="${STAGING_API_URL:-http://localhost:8001}"
    export STAGING_API_URL
}

compose_up() {
    # --profile staging: only start the staging service (the overlay adds
    # a profile to isolate it from dev/prod in the base file). Without the
    # profile, `up -d` also (re)creates dev and prod containers — noisy and
    # can fail on name conflicts with existing local containers.
    $COMPOSE -f docker-compose.yml -f docker-compose.staging.yml --env-file "$ENV_FILE" --profile staging up -d
}

# ── Commands ─────────────────────────────────────────────────────────────────

start_staging() {
    resolve_compose
    resolve_staging_api_url

    echo "==> Starting staging environment (API: ${STAGING_API_URL})..."

    if docker ps --format '{{.Names}}' | grep -q "^${STAGING_CONTAINER}$"; then
        echo "Staging container already running. Skipping up."
    else
        # The image is built per-architecture by the CI/CD pipeline (#156:
        # amd64 for CI, arm64 for arm64 hosts) and published to GHCR.
        # A local `compose up` with `build:` would re-build for the host
        # arch; on a host whose local images are a different arch this
        # fails with 'exec format error'. Pull the host-arch image
        # explicitly instead (the compose file's build: is only a fallback
        # for local dev).
        local host_arch
        host_arch="$(uname -m)"
        case "$host_arch" in
            aarch64 | arm64) host_arch="arm64" ;;
            x86_64) host_arch="amd64" ;;
        esac
        local ghcr_image="ghcr.io/vopsiton/riks-context-engine:staging"
        echo "==> Pulling ${ghcr_image} (${host_arch})..."
        if ! docker pull --platform "linux/${host_arch}" "$ghcr_image" 2>/dev/null; then
            echo "WARNING: GHCR pull failed (network/permissions?). Falling back to local build."
            echo "  Local build on arm64 hosts needs the arm64 Dockerfile variant:
    python3 scripts/gen_dockerfile_arm64.py > Dockerfile.arm64
    docker build --platform linux/arm64 -f Dockerfile.arm64 -t riks-context-engine:staging ."
            if [ "$host_arch" = "arm64" ] && [ ! -f Dockerfile.arm64 ]; then
                python3 scripts/gen_dockerfile_arm64.py > Dockerfile.arm64
                docker build --platform linux/arm64 -f Dockerfile.arm64 -t riks-context-engine:staging .
            else
                $COMPOSE -f docker-compose.yml -f docker-compose.staging.yml --env-file "$ENV_FILE" build staging || true
            fi
        fi
        compose_up
    fi

    echo "==> Waiting for staging to be healthy..."
    local max_attempts=20
    local attempt=1
    local deadline=$(( $(date +%s) + 60 ))

    while [ $attempt -le $max_attempts ] && [ $(date +%s) -lt $deadline ]; do
        if curl -sf "${STAGING_API_URL}/health" > /dev/null 2>&1; then
            echo "✓ Staging is healthy at ${STAGING_API_URL}"
            return 0
        fi
        echo "  Attempt $attempt/$max_attempts..."
        sleep 3
        attempt=$((attempt + 1))
    done

    echo "ERROR: Staging failed to become healthy within 60s."
    $COMPOSE -f docker-compose.yml -f docker-compose.staging.yml --env-file "$ENV_FILE" --profile staging logs --tail=50
    exit 1
}

stop_staging() {
    resolve_compose
    echo "==> Stopping staging environment..."
    # Note: --volumes would destroy the staging-data volume (persistence
    # lifecycle is handled by #159, not here).
    # Without --profile staging, `down` only removes profile-less services
    # (dev/prod) and leaves the staged container running — always pass the
    # profile so the staged container is actually stopped.
    $COMPOSE -f docker-compose.yml -f docker-compose.staging.yml --env-file "$ENV_FILE" --profile staging down 2>/dev/null || true
    echo "✓ Staging stopped."
}

restart_staging() {
    stop_staging
    start_staging
}

status_staging() {
    resolve_staging_api_url
    echo "=== Staging Status ==="
    if docker ps --format '{{.Names}}' | grep -q "^${STAGING_CONTAINER}$"; then
        echo "Container: RUNNING"
        docker ps --filter "name=${STAGING_CONTAINER}" --format "  Image: {{.Image}}
  Ports: {{.Ports}}
  Status: {{.Status}}"
    else
        echo "Container: STOPPED"
    fi
    echo ""
    echo "API Health: $(curl -sf "${STAGING_API_URL}/health" 2>/dev/null || echo 'unavailable')"
}

logs_staging() {
    resolve_compose
    $COMPOSE -f docker-compose.yml -f docker-compose.staging.yml logs -f --tail=100
}

test_staging() {
    resolve_staging_api_url
    echo "==> Running tests against staging..."
    local max_attempts=20
    local attempt=1

    # Wait for API
    while [ $attempt -le $max_attempts ]; do
        if curl -sf "${STAGING_API_URL}/health" > /dev/null 2>&1; then
            break
        fi
        echo "  Waiting for API... $attempt/$max_attempts"
        sleep 2
        attempt=$((attempt + 1))
    done

    if [ $attempt -gt $max_attempts ]; then
        echo "ERROR: Staging API not available."
        exit 1
    fi

    # Run integration tests
    pip install -e ".[dev]" 2>/dev/null || true
    pytest tests/ -v --base-url="${STAGING_API_URL}" -x
}

# ── CLI ───────────────────────────────────────────────────────────────────────

show_help() {
    cat << EOF
Usage: ./scripts/staging.sh <command>

Commands:
  start     Start staging environment (overlay: base + staging compose)
  stop      Stop staging environment (data volume preserved)
  restart   Restart staging environment
  status    Show staging status + health
  logs      Tail staging logs
  test      Run tests against staging
  help      Show this help

Env: STAGING_API_URL is read from .env.staging (default http://localhost:8001).

Examples:
  ./scripts/staging.sh start
  ./scripts/staging.sh status
  ./scripts/staging.sh logs
  ./scripts/staging.sh test
EOF
}

# ── Main ───────────────────────────────────────────────────────────────────────

COMMAND="${1:-help}"

case "$COMMAND" in
    start)      start_staging ;;
    stop)       stop_staging ;;
    restart)    restart_staging ;;
    status)     status_staging ;;
    logs)       logs_staging ;;
    test)       test_staging ;;
    help)       show_help ;;
    *)          show_help; exit 1 ;;
esac
