# Kubernetes manifests for Rik's Context Engine (#111)
#
# Image source: ghcr.io/vopsiton/riks-context-engine (built by .github/workflows/cd.yml).
# Apply order: namespace.yaml → configmap.yaml → secret (create separately, see
# secret.example.yaml) → service.yaml → deployment.yaml → hpa.yaml
#
# Secrets are NOT committed. secret.example.yaml is a TEMPLATE with CHANGE_ME
# placeholders only. Create the real Secret out-of-band:
#   kubectl create secret generic riks-context-engine \
#     --from-literal=RIKS_API_KEY=<value> \
#     [--from-literal=RIKS_DEFAULT_TENANT_ID=<value>] \
#     -n riks-context-engine
#
# Health endpoints (liveness + readiness + startup probes all use these):
#   GET /health → 200 {"status": "ok"}
