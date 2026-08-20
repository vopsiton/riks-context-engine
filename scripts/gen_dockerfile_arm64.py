#!/usr/bin/env python3
"""Generate the arm64 variant of the (amd64-checked-in) Dockerfile (#156).

The repo keeps ONE checked-in Dockerfile (the amd64 variant — CI/CD is
unchanged, digest-pinned per #117). This script derives the arm64 variant
by rewriting the pinned FROM digest to the arm64 one and updating the
GENERATED-FOR-ARCH marker. A digest re-pin (#117) updates BOTH digests
below.

Usage:
    scripts/gen_dockerfile_arm64.py [dockerfile_path] > Dockerfile.arm64

The cd.yml arm64-build job (push'suz bonus check) uses this script and
fails if the generated digest drifted from the one pinned below (keeps
the two in sync without checking in a second Dockerfile).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Per-arch pinned base digests (python:3.12-slim, Docker Hub manifest
# list last_updated 2026-08-16T20:07Z — same image, two architectures).
# Re-pin here (and in Dockerfile) together; record old+new in the
# Dockerfile comment block, as #117 requires.
DIGESTS = {
    "amd64": "sha256:876416ecde9aca2bcc90e1fb0c7a9500bbf749f5788b70f82d4c5a5c2357f8b4",
    "arm64": "sha256:0568e6111802e74c03e8dda76565cdf4b88881d77de0d9b769846e9dfcb8d80a",
}

MARKER = "GENERATED-FOR-ARCH:"


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "Dockerfile").read_text()
    # The checked-in file must be the amd64 variant and carry the marker.
    if f"{MARKER}amd64" not in src:
        sys.exit(f"error: {MARKER}amd64 marker missing — is this the checked-in Dockerfile?")
    lines = src.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("FROM ") and "@sha256:" in ln:
            # Fail fast if the checked-in digest drifted from DIGESTS["amd64"].
            checked = ln.split("@", 1)[1]
            if checked != DIGESTS["amd64"]:
                sys.exit(
                    f"error: checked-in digest {checked} != pinned amd64 digest "
                    f"{DIGESTS['amd64']} — re-pin both (see Dockerfile comment, #117/#156)"
                )
            lines[i] = f"FROM python:3.12-slim@{DIGESTS['arm64']}"
            break
    else:
        sys.exit("error: no pinned FROM line found")
    out = "\n".join(lines).replace(f"{MARKER}amd64", f"{MARKER}arm64")
    out = out.replace(
        'LABEL org.opencontainers.image.created.arch="amd64"',
        'LABEL org.opencontainers.image.created.arch="arm64"',
    )
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
