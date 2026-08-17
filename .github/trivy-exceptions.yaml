# Trivy ignore file — documented exceptions ONLY (see #117 follow-up)
#
# Policy: every entry requires (a) CVE id, (b) justification, (c) a review
# date. Exceptions are time-boxed: re-scan on the review date and remove
# the entry once a fixed version is available in the base image.
#
# Context (2026-08-17): the `docker build` step of the CD Pipeline builds
# the image with BuildKit `push: false`, so the image is never pushed to
# ghcr.io. The Trivy action then tried to pull
# `ghcr.io/vopsiton/riks-context-engine:master` (the multi-tag output of
# docker/metadata-action, comma-joined) and failed with
# "could not parse reference" — exit 1 — on EVERY run since #116.
#
# Permanent fix (this PR): scan the locally built image by digest
# (trivy image scan-ref: . + @sha256:...) so nothing needs to be pushed.
# The ignorefile below covers the residual base-image findings that remain
# on python:3.12-slim (Debian 13.6) as of 2026-08-17.
#
# Base image pinning: the Dockerfile pins python:3.12-slim by digest
# (python:3.12.11-slim@sha256:...) so floating-tag CVE surprise is removed;
# the pinned base is re-scanned at each review date.

# ── perl-base 5.40.1-6 (Debian 13.6) — no fix published ─────────────────────
# CRITICAL x4 + HIGH x4 in the base image. perl-base is a mandatory
# dependency of the Debian base (dpkg); it cannot be removed from
# python:3.12-slim. App does not ship or execute any Perl code, and the
# container exposes only port 8000 (Python/uvicorn) — none of the affected
# Perl components are reachable from the app surface.
# Review: 2026-11-17 (re-scan; drop entries once Debian ships a fixed
# perl-base or the pinned base image is updated).
CVE-2026-13221
CVE-2026-42496
CVE-2026-42497
CVE-2026-48962
CVE-2026-57432
CVE-2026-57433
CVE-2026-8376
CVE-2026-9538

# ── ncurses (libncursesw6 / libtinfo6 / ncurses-*) 6.5+20250216-2 — no fix ─
# HIGH. Terminal-UI library pulled in by build-essential toolchain deps.
# No TTY interaction in the container (headless uvicorn); exploit surface
# requires interactive terminal access, which the image does not provide.
# Review: 2026-11-17.
CVE-2025-69720

# ── util-linux 2.41-5 — fixed in 2.41.5-0+deb13u1 (backport pending in base) ─
# HIGH. util-linux is upgradable via apt; the Dockerfile already runs
# `apt-get upgrade` at build time, so these entries are belt-and-braces
# for the small window before the base image digest is re-pinned.
# Review: 2026-11-17 (expected to be removable at re-pin).
CVE-2026-53615

# ── gzip 1.13-1 — no fix published ──────────────────────────────────────────
# HIGH. Compressor library; container only decompresses build artifacts at
# image-build time (pip), not at runtime. Review: 2026-11-17.
CVE-2026-41992

# ── libacl1 2.3.2-2+b1 — no fix published ───────────────────────────────────
# HIGH. Access-control-list libc helper; no ACL features are used by the app.
# Review: 2026-11-17.
CVE-2026-54369
