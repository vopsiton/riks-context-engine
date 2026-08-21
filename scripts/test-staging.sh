#!/usr/bin/env bash
set -euo pipefail

# Test runner for the STAGING environment (overlay: base + staging compose,
# API on 8001). STAGING_API_URL is read from .env.staging — the default
# fallback is http://localhost:8001 (staging port), NOT the dev port 8000.
#
# Usage: ./scripts/test-staging.sh [--wait] [--report-issue N]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

ENV_FILE=".env.staging"
ENV_EXAMPLE=".env.staging.example"
RESULTS_DIR="test-results"

# Shared helpers (#159): GHCR staging-<sha> resolution + drift-guarded
# local-build fallback, shared with scripts/staging.sh.
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

# Read STAGING_API_URL from .env.staging (created from example if missing).
# Falls back to the staging port (8001) — the previous default (8000, dev)
# silently tested the wrong service.
resolve_staging_api_url() {
    if [ ! -f "$ENV_FILE" ]; then
        if [ -f "$ENV_EXAMPLE" ]; then
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            echo "==> Created ${ENV_FILE} from ${ENV_EXAMPLE}."
        else
            echo "WARNING: neither ${ENV_FILE} nor ${ENV_EXAMPLE} found." >&2
        fi
    fi
    local from_file
    from_file="$(sed -n 's/^STAGING_API_URL=//p' "$ENV_FILE" 2>/dev/null | tail -n1 || true)"
    STAGING_API_URL="${STAGING_API_URL:-${from_file:-http://localhost:8001}}"
    export STAGING_API_URL
}

compose_up() {
    $COMPOSE -f docker-compose.yml -f docker-compose.staging.yml --env-file "$ENV_FILE" --profile staging up -d
}

compose_down() {
    # --profile staging: `down` without the profile only removes profile-less
    # services (dev/prod) and leaves the staged container running.
    $COMPOSE -f docker-compose.yml -f docker-compose.staging.yml --env-file "$ENV_FILE" --profile staging down || true
}

start_staging() {
    resolve_compose
    resolve_staging_api_url
    echo "==> Starting STAGING environment (API: ${STAGING_API_URL})..."
    # Overlay stack: base + staging (staging service, port 8001).
    # Image (#159): CI image `staging-<sha>` (STAGING_SHA env → git HEAD →
    # floating tag) preferred, no `--build` on the default path: local
    # CI image → pull → pre-existing local image → drift-guarded local
    # build (same behavior as scripts/staging.sh start).
    if ! docker ps --format '{{.Names}}' | grep -q "^riks-context-engine-staging$"; then
        ensure_staging_image
    fi
    compose_up
    echo "==> Waiting for staging to be healthy..."
    wait_health
}

wait_health() {
    resolve_staging_api_url
    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if curl -sf "$STAGING_API_URL/health" > /dev/null 2>&1 || curl -sf "$STAGING_API_URL/" > /dev/null 2>&1; then
            echo "==> Staging is healthy at ${STAGING_API_URL} (attempt $attempt/$max_attempts)"
            return 0
        fi
        echo "    Waiting for health... (attempt $attempt/$max_attempts)"
        sleep 2
        attempt=$((attempt + 1))
    done

    echo "ERROR: Staging failed to become healthy after $max_attempts attempts"
    $COMPOSE -f docker-compose.yml -f docker-compose.staging.yml --env-file "$ENV_FILE" --profile staging logs --tail=20
    exit 1
}

run_tests() {
    resolve_staging_api_url
    echo "==> Running test suite against ${STAGING_API_URL}..."
    mkdir -p "$RESULTS_DIR"
    pytest tests/ -v --base-url="$STAGING_API_URL" \
        --junitxml="$RESULTS_DIR/staging-results.xml" \
        --html="$RESULTS_DIR/staging-report.html" --self-contained-html \
        || true
    echo "==> Results saved to $RESULTS_DIR/"
}

teardown() {
    resolve_compose
    echo "==> Tearing down staging environment..."
    compose_down
}

report_issue() {
    local issue_num="$1"
    echo "==> Reporting results to issue #$issue_num..."
    if [ -f "$RESULTS_DIR/staging-results.xml" ]; then
        gh issue comment "$issue_num" --body "## Test Results

Staging tests completed. Results: $RESULTS_DIR/staging-results.xml

To view HTML report: \`cat $RESULTS_DIR/staging-report.html\`" || true
    else
        echo "WARNING: No results file found at $RESULTS_DIR/staging-results.xml"
    fi
}

show_help() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --wait          Wait for health check only"
    echo "  --report-issue N  Start staging, run tests, report to issue N"
    echo "  --help          Show this help"
    echo ""
    echo "STAGING_API_URL is read from $ENV_FILE (default http://localhost:8001)."
}

main() {
    case "${1:-}" in
        --wait)
            wait_health
            ;;
        --report-issue)
            # No teardown before start: start is idempotent (compose up -d
            # against the running overlay is a no-op for healthy services).
            start_staging
            run_tests
            report_issue "${2:-}"
            ;;
        --help)
            show_help
            ;;
        *)
            start_staging
            run_tests
            teardown
            ;;
    esac
}

main "$@"
