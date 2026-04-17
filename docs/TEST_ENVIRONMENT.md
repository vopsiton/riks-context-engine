# Test Environment — Staging Setup

This document describes the staging/test environment for QA testers.

## Overview

The staging environment is a Docker-based deployment of the riks-context-engine API,
identical to production in structure but isolated for testing purposes.

**Key differences from development:**
- `ENVIRONMENT=staging`
- `TEST_MODE=true`
- Debug logging enabled

## Starting the Staging Environment

```bash
# Copy the staging env file
cp .env.staging.example .env.staging

# Start the staging environment
docker-compose -f docker-compose.yml --env-file .env.staging up --build -d

# Verify it's running
docker-compose -f docker-compose.yml ps
```

## API Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/` | GET | API health check | None |
| `/health` | GET | Detailed health status | None |
| `/context` | POST | Submit a context object | None (local) |
| `/context/<id>` | GET | Retrieve context by ID | None (local) |
| `/memory/search` | POST | Semantic memory search | None (local) |
| `/memory/history` | GET | Episodic memory history | None (local) |

**Base URL:** `http://localhost:8000`

## Test User Credentials

> **Note:** These are local/staging test credentials. No real user data is used.

| Username | Password | Role |
|----------|----------|------|
| `test_user` | `test_pass_123` | Read/Write |
| `test_admin` | `test_admin_456` | Admin |

## Running the Test Suite

```bash
# Ensure staging is running first
docker-compose -f docker-compose.yml --env-file .env.staging up --build -d

# Wait for health check
./scripts/test-staging.sh --wait

# Run the test suite against staging
pytest tests/ -v --base-url=http://localhost:8000

# Or use the test runner script
./scripts/test-staging.sh
```

## Reporting Test Results

After running tests, results are saved to `test-results/`:

```
test-results/
├── staging-results.xml   # JUnit XML (CI/CD compatible)
└── staging-report.html   # HTML report
```

To attach results to a GitHub issue, use the test runner:

```bash
./scripts/test-staging.sh --report-issue 16
```

## Environment Variables

Required variables for staging (see `.env.staging.example`):

| Variable | Description | Example |
|----------|-------------|---------|
| `ENVIRONMENT` | Must be `staging` | `staging` |
| `TEST_MODE` | Enables test endpoints | `true` |
| `STAGING_API_URL` | API base URL | `http://localhost:8000` |
| `OLLAMA_HOST` | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Model to use | `gemma4-31b-it` |
| `LOG_LEVEL` | Logging level | `DEBUG` |

## Troubleshooting

**Container won't start:**
```bash
docker-compose logs app
docker-compose exec app python -c "import src; print('OK')"
```

**Health check fails:**
```bash
curl http://localhost:8000/health
docker-compose exec app curl http://localhost:8000/health
```

**Tests timing out:**
```bash
# Increase timeout in pytest.ini or run with:
pytest tests/ -v --timeout=60
```
