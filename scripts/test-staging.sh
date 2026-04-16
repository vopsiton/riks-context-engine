#!/usr/bin/env bash
set -euo pipefail

# Test runner for staging environment
# Usage: ./scripts/test-staging.sh [--wait] [--report-issue N]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

ENV_FILE=".env.staging"
RESULTS_DIR="test-results"

start_staging() {
    echo "==> Starting staging environment..."
    if [ ! -f "$ENV_FILE" ]; then
        echo "ERROR: $ENV_FILE not found. Copy from .env.staging.example first."
        exit 1
    fi
    docker-compose -f docker-compose.yml --env-file "$ENV_FILE" up --build -d
    echo "==> Waiting for staging to be healthy..."
    wait_health
}

wait_health() {
    local max_attempts=30
    local attempt=1
    local api_url="${STAGING_API_URL:-http://localhost:8000}"

    while [ $attempt -le $max_attempts ]; do
        if curl -sf "$api_url/health" > /dev/null 2>&1 || curl -sf "$api_url/" > /dev/null 2>&1; then
            echo "==> Staging is healthy (attempt $attempt/$max_attempts)"
            return 0
        fi
        echo "    Waiting for health... (attempt $attempt/$max_attempts)"
        sleep 2
        attempt=$((attempt + 1))
    done

    echo "ERROR: Staging failed to become healthy after $max_attempts attempts"
    docker-compose -f docker-compose.yml logs --tail=20
    exit 1
}

run_tests() {
    echo "==> Running test suite against staging..."
    mkdir -p "$RESULTS_DIR"
    pytest tests/ -v --base-url="${STAGING_API_URL:-http://localhost:8000}" \
        --junitxml="$RESULTS_DIR/staging-results.xml" \
        --html="$RESULTS_DIR/staging-report.html" --self-contained-html \
        || true
    echo "==> Results saved to $RESULTS_DIR/"
}

teardown() {
    echo "==> Tearing down staging environment..."
    docker-compose -f docker-compose.yml --env-file "$ENV_FILE" down || true
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
    echo "  --report-issue N  Report results to issue N"
    echo "  --help          Show this help"
}

main() {
    case "${1:-}" in
        --wait)
            wait_health
            ;;
        --report-issue)
            teardown
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
