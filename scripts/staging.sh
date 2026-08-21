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
#
# Shared helpers (GHCR staging-<sha> resolution, host-arch detection,
# drift-guarded local-build fallback) live in scripts/lib/staging-common.sh
# and are shared with scripts/test-staging.sh (#159).
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

STAGING_CONTAINER="riks-context-engine-staging"
ENV_FILE=".env.staging"
ENV_EXAMPLE=".env.staging.example"
STAGING_DATA_VOLUME="staging-data"

# shellcheck source=scripts/lib/staging-common.sh
. "$SCRIPT_DIR/lib/staging-common.sh"

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

compose_down() {
    # --profile staging: `down` without the profile only removes profile-less
    # services (dev/prod) and leaves the staged container running.
    $COMPOSE -f docker-compose.yml -f docker-compose.staging.yml --env-file "$ENV_FILE" --profile staging down 2>/dev/null || true
}

# ── Commands ─────────────────────────────────────────────────────────────────

start_staging() {
    local rebuild=0
    for arg in "$@"; do
        case "$arg" in
            --rebuild)
                rebuild=1
                ;;
            *)
                echo "ERROR: unknown start option '${arg}' (usage: staging.sh start [--rebuild])" >&2
                exit 1
                ;;
        esac
    done

    resolve_compose
    resolve_staging_api_url

    echo "==> Starting staging environment (API: ${STAGING_API_URL})..."

    if [ "$rebuild" -eq 1 ]; then
        # --rebuild: skip the CI pull entirely; build locally for the host
        # arch (arm64 hosts: Dockerfile.arm64 with drift guard — AC5).
        ensure_staging_image_force_rebuild
    fi

    if docker ps --format '{{.Names}}' | grep -q "^${STAGING_CONTAINER}$"; then
        echo "Staging container already running. Skipping up."
    else
        # The image is built per-architecture by the CI/CD pipeline (#156)
        # and published to GHCR as `staging-<sha>` (cd.yml deploy-staging).
        # Resolution order (#159): STAGING_SHA env → git HEAD short sha →
        # floating `staging` tag (warning). Never let compose re-build from
        # the checked-in amd64 Dockerfile on an arm64 host (exec format
        # error): the compose file no longer has a build: section, and the
        # fallback path here builds with the arch-correct Dockerfile.
        ensure_staging_image
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
    local purge=0
    for arg in "$@"; do
        case "$arg" in
            --purge)
                purge=1
                ;;
            *)
                echo "ERROR: unknown stop option '${arg}' (usage: staging.sh stop [--purge])" >&2
                exit 1
                ;;
        esac
    done

    resolve_compose
    echo "==> Stopping staging environment..."
    # Plain stop keeps the staging-data volume (persistence, #159);
    # --purge also removes it (explicit, user-initiated data loss).
    compose_down
    if [ "$purge" -eq 1 ]; then
        echo "==> Purging staging data volume '${STAGING_DATA_VOLUME}'..."
        docker volume rm "$STAGING_DATA_VOLUME" 2>/dev/null || \
            docker volume rm "riks-context-engine_${STAGING_DATA_VOLUME}" 2>/dev/null || true
        echo "✓ Staging stopped and data volume purged."
    else
        echo "✓ Staging stopped (data volume preserved)."
    fi
}

restart_staging() {
    stop_staging
    start_staging "$@"
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

smoke_staging() {
    resolve_staging_api_url
    echo "==> Smoke testing ${STAGING_API_URL}..."

    # 1) Health endpoint must answer 200 (unauthenticated).
    local health_code
    health_code="$(curl -s -o /dev/null -w '%{http_code}' "${STAGING_API_URL}/health")"
    if [ "$health_code" != "200" ]; then
        echo "FAIL: /health returned ${health_code} (expected 200)." >&2
        exit 1
    fi
    echo "✓ /health → 200"

    # 2) Fail-closed auth (#166): a protected endpoint without an API key
    #    must be rejected (401/403). With a key from .env.staging it must
    #    be served (200) — proves the key actually works.
    local protected_code
    protected_code="$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Tenant-Id: smoke-test' "${STAGING_API_URL}/api/v1/memory/export?format=json")"
    case "$protected_code" in
        401 | 403)
            echo "✓ /api/v1/memory/export without key → ${protected_code} (fail-closed auth OK)"
            ;;
        *)
            echo "FAIL: /api/v1/memory/export without key returned ${protected_code} (expected 401/403 — auth NOT fail-closed)." >&2
            exit 1
            ;;
    esac

    local api_key=""
    if [ -f "$ENV_FILE" ]; then
        api_key="$(sed -n 's/^STAGING_API_KEY=//p' "$ENV_FILE" 2>/dev/null | tail -n1)"
    fi
    if [ -n "$api_key" ]; then
        local authed_code
        authed_code="$(curl -s -o /dev/null -w '%{http_code}' -H "X-API-Key: ${api_key}" -H 'X-Tenant-Id: smoke-test' "${STAGING_API_URL}/api/v1/memory/export?format=json")"
        if [ "$authed_code" != "200" ]; then
            echo "FAIL: /api/v1/memory/export with STAGING_API_KEY returned ${authed_code} (expected 200)." >&2
            exit 1
        fi
        echo "✓ /api/v1/memory/export with key → 200 (authed path OK)"
    else
        echo "NOTE: no STAGING_API_KEY in ${ENV_FILE}; authed path not checked."
    fi

    echo "✓ Smoke test passed."
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
  start [--rebuild]  Start staging (idempotent; --rebuild: local build,
                     skipping the CI image pull — arm64 hosts build with
                     the drift-guarded Dockerfile.arm64)
  stop [--purge]     Stop staging (data volume preserved; --purge deletes
                     the staging-data volume)
  restart [--rebuild]  Restart staging (passes flags through)
  status    Show staging status + health
  smoke     Smoke test: /health 200 + fail-closed auth (401 without key,
            200 with STAGING_API_KEY)
  logs      Tail staging logs
  test      Run tests against staging
  help      Show this help

Env: STAGING_API_URL is read from .env.staging (default http://localhost:8001).
     STAGING_SHA selects the CI image tag staging-<sha> (default: git HEAD
     short sha; fallback: floating `staging` tag with a warning).

Examples:
  ./scripts/staging.sh start
  ./scripts/staging.sh start --rebuild
  ./scripts/staging.sh stop --purge
  ./scripts/staging.sh status
  ./scripts/staging.sh smoke
  ./scripts/staging.sh logs
  ./scripts/staging.sh test
EOF
}

# ── Main ───────────────────────────────────────────────────────────────────────

COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    start)      start_staging "$@" ;;
    stop)       stop_staging "$@" ;;
    restart)    restart_staging "$@" ;;
    status)     status_staging ;;
    smoke)      smoke_staging ;;
    logs)       logs_staging ;;
    test)       test_staging ;;
    help)       show_help ;;
    *)          show_help; exit 1 ;;
esac
