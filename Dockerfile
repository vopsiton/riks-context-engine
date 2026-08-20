# ===== Base ===== #
# Pinned by digest (2026-08-17, #117): the floating 3.12-slim tag moved to
# Debian 13.6 on 2026-08-16 and introduced new HIGH findings that the
# pinned digest predates. Re-pin deliberately (record old+new digest here)
# instead of drifting silently.
#
# Multi-arch pin (2026-08-20, #156): #117 pinned the *amd64* digest only,
# which broke `docker build` on arm64 hosts with "exec format error"
# (QEMU/binfmt not registered). The base is now pinned PER ARCHITECTURE
# (same digest-pinning discipline, both arches of the same 3.12-slim
# image, Docker Hub manifest list last_updated 2026-08-16T20:07Z):
#
#   linux/amd64  sha256:876416ecde9aca2bcc90e1fb0c7a9500bbf749f5788b70f82d4c5a5c2357f8b4  (unchanged from #117 — CI amd64 build stays byte-identical)
#   linux/arm64  sha256:0568e6111802e74c03e8dda76565cdf4b88881d77de0d9b769846e9dfcb8d80a  (added for arm64 hosts)
#
# Why per-arch pins (option a, not buildx manifest publish): the CI/CD
# amd64 path is unchanged — the amd64 digest is the exact one from #117 —
# and arm64 hosts build natively, no QEMU. A future re-pin (#117) must
# update BOTH digests — the one in the FROM line below AND the one in
# scripts/gen_dockerfile_arm64.py (used by the cd.yml arm64-build job) —
# and record old+new here.
#
# This checked-in file is the amd64 variant (CI/CD builds it as-is).
# GENERATED-FOR-ARCH:amd64
# arm64 hosts / CI arm64 check: generate the arm64 variant with
# `scripts/gen_dockerfile_arm64.py` (rewrites the pinned digest) and build
# that; cd.yml's arm64-build job (buildx, push=false) proves the arm64
# image builds.
FROM python:3.12-slim@sha256:876416ecde9aca2bcc90e1fb0c7a9500bbf749f5788b70f82d4c5a5c2357f8b4

LABEL maintainer="vopsiton <vahit@opsiton.com>"
LABEL description="Rik's Context Engine - AI memory and context management"
LABEL org.opencontainers.image.base.name="python:3.12-slim (digest-pinned per architecture, #117 + #156)"
LABEL org.opencontainers.image.created.arch="amd64"

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
