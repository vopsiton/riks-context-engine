#!/usr/bin/env bash
# =============================================================================
# riks-context-engine — Staging shared helpers (source, do not execute)
# =============================================================================
# Shared by scripts/staging.sh and scripts/test-staging.sh (#159).
#
# Provides:
#   - GHCR image resolution: staging-<sha> tag from STAGING_SHA env (priority),
#     then `git rev-parse --short HEAD`, then the `staging` floating tag
#     (with a warning) — so local pulls match what CI (cd.yml deploy-staging)
#     actually pushes (ghcr.io/vopsiton/riks-context-engine:staging-<sha>).
#   - host-arch detection (linux/amd64 | linux/arm64)
#   - local-build fallback with a digest-drift guard (AC5): regenerate
#     Dockerfile.arm64 from scripts/gen_dockerfile_arm64.py, diff it against
#     the committed file, and FAIL on drift (same guard as cd.yml
#     arm64-build job) — never build on an arm64 host with the amd64
#     (checked-in) Dockerfile.
#
# Sourced functions read: nothing global. They write (export when called):
#   RESOLVED_IMAGE, RESOLVED_TAG, STAGING_SHA_SOURCE, HOST_ARCH, GHCR_REPO
# =============================================================================

STAGING_GHCR_REPO="ghcr.io/vopsiton/riks-context-engine"
STAGING_LOCAL_IMAGE="riks-context-engine:staging"

# Detect the host architecture as a linux/<arch> docker platform.
detect_host_arch() {
    local uname_m
    uname_m="$(uname -m)"
    case "$uname_m" in
        aarch64 | arm64) HOST_ARCH="linux/arm64" ;;
        x86_64)          HOST_ARCH="linux/amd64" ;;
        *)
            echo "ERROR: unsupported host architecture '${uname_m}'." >&2
            return 1
            ;;
    esac
}

# Resolve the staging image tag CI would have published (#159).
# Source order:
#   (a) $STAGING_SHA env var (explicit, priority)
#   (b) git rev-parse --short HEAD (when inside a git work tree)
#   (c) floating `staging` tag (fallback, with warning)
# Sets: RESOLVED_IMAGE, RESOLVED_TAG, STAGING_SHA_SOURCE.
resolve_staging_image() {
    local sha="" source=""
    if [ -n "${STAGING_SHA:-}" ]; then
        sha="$STAGING_SHA"
        source="STAGING_SHA env"
    elif sha="$(git rev-parse --short HEAD 2>/dev/null)" && [ -n "$sha" ]; then
        source="git rev-parse --short HEAD"
    fi

    if [ -n "$sha" ]; then
        RESOLVED_TAG="staging-${sha}"
        RESOLVED_IMAGE="${STAGING_GHCR_REPO}:${RESOLVED_TAG}"
        STAGING_SHA_SOURCE="$source"
    else
        RESOLVED_TAG="staging"
        RESOLVED_IMAGE="${STAGING_GHCR_REPO}:${RESOLVED_TAG}"
        STAGING_SHA_SOURCE="fallback"
        echo "WARNING: no SHA source (STAGING_SHA unset, not a git work tree)." >&2
        echo "  Falling back to the floating '${RESOLVED_TAG}' tag — it may not" >&2
        echo "  match the commit CI last deployed. Set STAGING_SHA to be exact." >&2
    fi
}

# Ensure Dockerfile.arm64 matches what scripts/gen_dockerfile_arm64.py
# generates from the checked-in (amd64) Dockerfile. Exits non-zero on
# drift or generation failure (same guard as the cd.yml arm64-build job).
# Keeps the working-tree file untouched (compares against a temp file).
check_arm64_dockerfile_sync() {
    local gen
    gen="$(mktemp)" || return 1
    if ! python3 scripts/gen_dockerfile_arm64.py Dockerfile > "$gen" 2>/dev/null; then
        rm -f "$gen"
        echo "ERROR: scripts/gen_dockerfile_arm64.py failed to generate the" >&2
        echo "  arm64 variant (digest drift between Dockerfile and the pinned" >&2
        echo "  digests?). Re-pin per #117 and regenerate before building." >&2
        return 1
    fi
    if ! diff -u Dockerfile.arm64 "$gen" >/dev/null; then
        rm -f "$gen"
        echo "ERROR: Dockerfile.arm64 has drifted from scripts/gen_dockerfile_arm64.py" >&2
        echo "  (digest-sync guard, AC5). Regenerate and commit:" >&2
        echo "    python3 scripts/gen_dockerfile_arm64.py Dockerfile > Dockerfile.arm64" >&2
        return 1
    fi
    rm -f "$gen"
    return 0
}

# Local-build fallback for when the GHCR pull fails (AC5):
#   - NEVER build with the checked-in amd64 Dockerfile on an arm64 host
#     (that is the root cause of 'exec format error').
#   - arm64 host: drift-guard Dockerfile.arm64, then native build.
#   - amd64 host: build with the checked-in Dockerfile.
# Tags the result with $STAGING_LOCAL_IMAGE so compose uses it.
local_build_fallback() {
    if [ "$HOST_ARCH" = "linux/arm64" ]; then
        if [ ! -f Dockerfile.arm64 ]; then
            echo "ERROR: Dockerfile.arm64 not found (expected committed in #159)." >&2
            return 1
        fi
        if ! check_arm64_dockerfile_sync; then
            return 1
        fi
        echo "==> Local build (arm64, native, -f Dockerfile.arm64):"
        docker build --platform linux/arm64 -f Dockerfile.arm64 -t "$STAGING_LOCAL_IMAGE" .
    else
        echo "==> Local build (amd64, -f Dockerfile):"
        docker build --platform linux/amd64 -f Dockerfile -t "$STAGING_LOCAL_IMAGE" .
    fi
}

# --rebuild path (#159): force a local build for the host arch, skipping
# the CI image entirely (drift-guarded on arm64 hosts — AC5).
ensure_staging_image_force_rebuild() {
    detect_host_arch
    echo "==> --rebuild: building ${STAGING_LOCAL_IMAGE} locally for ${HOST_ARCH} (skipping CI pull)."
    local_build_fallback
}

# Ensure the staging image is available locally, preferring the CI image:
#   1. CI image present locally ($RESOLVED_IMAGE) → retag to
#      $STAGING_LOCAL_IMAGE for compose.
#   2. otherwise docker pull --platform (CI image) → retag.
#   3. otherwise $STAGING_LOCAL_IMAGE present locally → use it (warning).
#   4. otherwise local build fallback (drift-guarded, arch-correct).
ensure_staging_image() {
    detect_host_arch
    resolve_staging_image
    echo "==> Resolved staging image: ${RESOLVED_IMAGE} (${STAGING_SHA_SOURCE}, ${HOST_ARCH})"

    if docker image inspect "$RESOLVED_IMAGE" >/dev/null 2>&1; then
        echo "==> Using local CI image ${RESOLVED_IMAGE}."
        docker tag "$RESOLVED_IMAGE" "$STAGING_LOCAL_IMAGE"
        return 0
    fi

    echo "==> Pulling ${RESOLVED_IMAGE} (${HOST_ARCH})..."
    if docker pull --platform "$HOST_ARCH" "$RESOLVED_IMAGE" 2>/dev/null; then
        docker tag "$RESOLVED_IMAGE" "$STAGING_LOCAL_IMAGE"
        return 0
    fi
    echo "WARNING: GHCR pull failed for ${RESOLVED_IMAGE} (network/permissions/tag not published?)." >&2

    if docker image inspect "$STAGING_LOCAL_IMAGE" >/dev/null 2>&1; then
        echo "WARNING: using pre-existing local image ${STAGING_LOCAL_IMAGE} (not the CI tag)." >&2
        return 0
    fi

    echo "==> No local image available — falling back to local build." >&2
    local_build_fallback
}
