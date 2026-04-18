#!/usr/bin/env bash
# =============================================================================
# riks-context-engine — Staging Environment Manager
# =============================================================================
# Quick staging environment for testing CI/CD pipeline changes
# =============================================================================

set -euo pipefail

COMPOSE_FILE="docker-compose.staging.yml"
STAGING_CONTAINER="riks-context-engine-staging"
STAGING_PORT="8001"

# ── Functions ────────────────────────────────────────────────────────────────

start_staging() {
    echo "==> Starting staging environment..."

    if docker ps --format '{{.Names}}' | grep -q "^${STAGING_CONTAINER}$"; then
        echo "Staging container already running. Skipping."
        return 0
    fi

    if [ ! -f docker-compose.staging.yml ]; then
        echo "ERROR: docker-compose.staging.yml not found."
        exit 1
    fi

    docker-compose -f docker-compose.staging.yml up -d

    echo "==> Waiting for staging to be healthy..."
    local max_attempts=20
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if curl -sf "http://localhost:${STAGING_PORT}/health" > /dev/null 2>&1; then
            echo "✓ Staging is healthy!"
            return 0
        fi
        echo "  Attempt $attempt/$max_attempts..."
        sleep 3
        attempt=$((attempt + 1))
    done

    echo "ERROR: Staging failed to become healthy."
    docker-compose -f docker-compose.staging.yml logs
    exit 1
}

stop_staging() {
    echo "==> Stopping staging environment..."
    docker-compose -f docker-compose.staging.yml down --volumes 2>/dev/null || true
    echo "✓ Staging stopped."
}

restart_staging() {
    stop_staging
    start_staging
}

status_staging() {
    echo "=== Staging Status ==="
    if docker ps --format '{{.Names}}' | grep -q "^${STAGING_CONTAINER}$"; then
        echo "Container: RUNNING"
        docker ps --filter "name=${STAGING_CONTAINER}" --format "  Image: {{.Image}}\n  Ports: {{.Ports}}\n  Status: {{.Status}}"
    else
        echo "Container: STOPPED"
    fi

    echo ""
    echo "API Health: $(curl -sf "http://localhost:${STAGING_PORT}/health" 2>/dev/null || echo 'unavailable')"
}

logs_staging() {
    docker-compose -f docker-compose.staging.yml logs -f --tail=100
}

test_staging() {
    echo "==> Running tests against staging..."
    local api_url="http://localhost:${STAGING_PORT}"
    local max_attempts=20
    local attempt=1

    # Wait for API
    while [ $attempt -le $max_attempts ]; do
        if curl -sf "${api_url}/health" > /dev/null 2>&1; then
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
    pytest tests/ -v --base-url="${api_url}" -x
}

# ── CLI ───────────────────────────────────────────────────────────────────────

show_help() {
    cat << EOF
Usage: ./scripts/staging.sh <command>

Commands:
  start     Start staging environment
  stop      Stop staging environment
  restart   Restart staging environment
  status    Show staging status
  logs      Tail staging logs
  test      Run tests against staging
  help      Show this help

Examples:
  ./scripts/staging.sh start
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
