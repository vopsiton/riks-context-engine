# Deployment Guide 🗿

## Local Sandbox (Docker)

```bash
# Build image
docker build -t riks-context-engine:dev .

# Run dev environment
docker-compose up dev

# Stop
docker-compose down
```

## CI/CD Pipeline

### GitHub Actions Workflows

#### 1. Test Stage (Every PR)

Triggered on: `pull_request` to `main`/`master`

```yaml
jobs:
  test:
    - Python setup
    - pip install -e ".[dev]"
    - pytest --cov=src/
    - ruff check
    - mypy type check
```

#### 2. Build + Deploy Stage (Main Branch)

Triggered on: `push` to `main`/`master`

Steps:
1. Run tests
2. Build Docker image
3. Push to registry
4. Deploy to server

### Deployment Targets

Currently supported:
- [ ] Cloudflare Workers/Pages
- [ ] Supabase
- [ ] VPS with Docker ← **Recommended for MVP**
- [ ] Railway
- [ ] Render

### Secrets Required

```bash
# GitHub Actions Secrets
DOCKER_HUB_TOKEN=     # Docker registry token
DOCKER_HUB_USER=       # Docker Hub username
SERVER_HOST=           # Production server IP
SERVER_USER=           # SSH username
SERVER_SSH_KEY=        # SSH private key (base64)
```

## Server Deployment (VPS)

### Prerequisites

- Docker installed on server
- SSH access configured
- Domain pointing to server (optional)

### Deploy Script

```bash
# On server
docker-compose -f docker-compose.prod.yml up -d
```

### Health Checks

```bash
curl http://localhost:8000/health
```

---

_For questions, open an issue on GitHub._
