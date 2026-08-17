# ===== Base ===== #
# Pinned by digest (2026-08-17, #117): the floating 3.12-slim tag moved to
# Debian 13.6 on 2026-08-16 and introduced new HIGH findings that the
# pinned digest predates. Re-pin deliberately (record old+new digest here)
# instead of drifting silently. Current digest = python:3.12-slim as of
# 2026-08-17 (Docker Hub last_updated 2026-08-16T20:07Z, amd64).
FROM python:3.12-slim@sha256:876416ecde9aca2bcc90e1fb0c7a9500bbf749f5788b70f82d4c5a5c2357f8b4

LABEL maintainer="vopsiton <vahit@opsiton.com>"
LABEL description="Rik's Context Engine - AI memory and context management"

WORKDIR /app

# ===== Dependencies ===== #
# Upgrade all OS packages to the latest available (security backports).
# Combined with the digest pin above this keeps the OS surface as small
# as the base image allows; remaining unfixed CVEs are documented in
# .github/trivy-exceptions.yaml with review dates.
RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy app source (needed for editable install)
COPY src/ ./src/
COPY tests/ ./tests/
COPY ui/ ./ui/

# Copy and install
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# ===== Data directory ===== #
RUN mkdir -p /app/data && chmod 755 /app/data

ENV PYTHONPATH=/app/src
ENV DATA_DIR=/app/data
ENV UI_PATH=/app/ui/index.html

# Default port
EXPOSE 8000

# Default command - run uvicorn server
CMD ["python", "-m", "uvicorn", "riks_context_engine.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
