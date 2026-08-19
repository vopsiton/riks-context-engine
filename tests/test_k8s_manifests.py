"""Tests for Kubernetes manifests (#111).

Validates the k8s/ manifests against the cluster-less kubeconform binary
(if installed) and, in every case, against a structural Python check that
asserts the required resource kinds, labels, resource limits, probes, and
HPA targets are present. The structural check runs even when kubeconform is
not installed (CI fallback); the kubeconform check is the authoritative
schema validation when available.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

K8S_DIR = Path(__file__).resolve().parents[1] / "k8s"

EXPECTED_KINDS = {
    "Namespace",
    "ConfigMap",
    "Secret",  # secret.example.yaml (template only — values are CHANGE_ME)
    "Service",
    "Deployment",
    "HorizontalPodAutoscaler",
}
NAMESPACE = "riks-context-engine"
LABEL_PART_OF = "riks"
HPA_CPU_TARGET = 70
HPA_MIN_REPLICAS = 2
HPA_MAX_REPLICAS = 6


def _load_all() -> list[dict]:
    """Load every YAML doc in k8s/ (all files, multi-doc safe)."""
    docs: list[dict] = []
    for f in sorted(K8S_DIR.glob("*.yaml")):
        with f.open() as fh:
            for doc in yaml.safe_load_all(fh):
                if doc:
                    docs.append(doc)
    return docs


def _by_kind(docs: list[dict]) -> dict[str, dict]:
    return {d["kind"]: d for d in docs}


class TestManifestsPresent:
    def test_all_expected_kinds(self):
        docs = _load_all()
        kinds = {d["kind"] for d in docs}
        missing = EXPECTED_KINDS - kinds
        assert not missing, f"missing kinds: {missing}"

    def test_namespace_present(self):
        docs = _by_kind(_load_all())
        assert docs["Namespace"]["metadata"]["name"] == NAMESPACE

    def test_all_resources_in_namespace(self):
        for d in _load_all():
            if d["kind"] == "Namespace":
                continue
            assert d["metadata"].get("namespace") == NAMESPACE, (
                f"{d['kind']} missing namespace or wrong namespace"
            )

    def test_labels_consistent(self):
        for d in _load_all():
            labels = d["metadata"].get("labels", {})
            if d["kind"] == "Secret":
                continue  # template — labels optional
            assert labels.get("app.kubernetes.io/part-of") == LABEL_PART_OF, (
                f"{d['kind']} missing part-of label"
            )


class TestConfigMap:
    def test_required_env_keys(self):
        cm = _by_kind(_load_all())["ConfigMap"]
        data = cm["data"]
        for key in ("RIKS_DATA_DIR", "UI_PATH"):
            assert key in data, f"ConfigMap missing {key}"
        # RIKS_API_KEY must NOT be in the ConfigMap (it is a Secret).
        assert "RIKS_API_KEY" not in data, "RIKS_API_KEY must not be in ConfigMap"


class TestSecretTemplate:
    def test_secret_is_template_only(self):
        secret = _by_kind(_load_all())["Secret"]
        assert secret["type"] == "Opaque"
        assert "stringData" in secret
        # Every value must be a CHANGE_ME placeholder (no real secrets in git).
        for value in secret["stringData"].values():
            assert "CHANGE_ME" in value or value == "CHANGE_ME", (
                "secret.example.yaml contains a value that is not a CHANGE_ME placeholder"
            )

    def test_secret_has_required_key(self):
        secret = _by_kind(_load_all())["Secret"]
        assert "RIKS_API_KEY" in secret["stringData"]


class TestService:
    def test_service_ports(self):
        svc = _by_kind(_load_all())["Service"]
        ports = svc["spec"]["ports"]
        assert len(ports) == 1
        assert ports[0]["port"] == 8000
        assert ports[0]["name"] == "http"
        assert svc["spec"]["selector"].get("app.kubernetes.io/component") == "api"


class TestDeployment:
    def _container(self) -> dict:
        dep = _by_kind(_load_all())["Deployment"]
        spec = dep["spec"]["template"]["spec"]
        containers = spec["containers"]
        assert isinstance(containers, list) and containers
        container = containers[0]
        assert isinstance(container, dict)
        return container

    def test_image_uses_ghcr(self):
        assert self._container()["image"].startswith("ghcr.io/vopsiton/riks-context-engine")

    def test_resource_limits_and_requests(self):
        res = self._container()["resources"]
        assert res["requests"]["cpu"] == "250m"
        assert res["requests"]["memory"] == "512Mi"
        assert res["limits"]["cpu"] == "1000m"
        assert res["limits"]["memory"] == "1Gi"

    def test_liveness_probe(self):
        probe = self._container()["livenessProbe"]
        assert probe["httpGet"]["path"] == "/health"
        assert probe["httpGet"]["port"] == "http"

    def test_readiness_probe(self):
        probe = self._container()["readinessProbe"]
        assert probe["httpGet"]["path"] == "/health"
        assert probe["httpGet"]["port"] == "http"

    def test_startup_probe(self):
        assert "startupProbe" in self._container()

    def test_envfrom_configmap_and_secret(self):
        envfrom = self._container()["envFrom"]
        names = [e.get("configMapRef", {}).get("name") for e in envfrom if "configMapRef" in e]
        secret_names = [e.get("secretRef", {}).get("name") for e in envfrom if "secretRef" in e]
        assert "riks-context-engine-config" in names
        assert "riks-context-engine" in secret_names

    def test_data_volume_mounted(self):
        dep = _by_kind(_load_all())["Deployment"]
        spec = dep["spec"]["template"]["spec"]
        volumes = {v["name"] for v in spec["volumes"]}
        mounts = {m["name"] for m in self._container()["volumeMounts"]}
        assert "data" in volumes
        assert "data" in mounts


class TestHPA:
    def test_hpa_targets(self):
        hpa = _by_kind(_load_all())["HorizontalPodAutoscaler"]
        assert hpa["spec"]["minReplicas"] == HPA_MIN_REPLICAS
        assert hpa["spec"]["maxReplicas"] == HPA_MAX_REPLICAS
        assert hpa["spec"]["scaleTargetRef"]["kind"] == "Deployment"
        metrics = hpa["spec"]["metrics"]
        assert len(metrics) == 1
        assert metrics[0]["type"] == "Resource"
        assert metrics[0]["resource"]["name"] == "cpu"
        assert metrics[0]["resource"]["target"]["type"] == "Utilization"
        assert metrics[0]["resource"]["target"]["averageUtilization"] == HPA_CPU_TARGET


@pytest.mark.skipif(
    shutil.which("kubeconform") is None,
    reason="kubeconform not installed — structural checks above cover the contract",
)
class TestKubeconform:
    def test_all_manifests_conform(self):
        """Authoritative schema validation (kubeconform)."""
        files = [str(f) for f in sorted(K8S_DIR.glob("*.yaml"))]
        result = subprocess.run(
            ["kubeconform", "-strict", "-summary", *files],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"kubeconform failed:\n{result.stdout}\n{result.stderr}"

    def test_manifests_are_valid_yaml(self):
        """Every YAML doc parses (already covered by _load_all, but this is
        the integration-test contract: spec JSON parse + endpoint list)."""
        docs = _load_all()
        assert docs, "no YAML docs found in k8s/"
        # Every doc has a kind and apiVersion (OpenAPI-style validation).
        for d in docs:
            assert "kind" in d
            assert "apiVersion" in d
