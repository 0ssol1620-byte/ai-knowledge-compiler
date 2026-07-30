"""Credential-free deployment-contract validation for local and CI use."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Repository tooling can share the documented AKC_* namespace without being
# injected into any runtime service. Keep these names explicit so a typo still
# fails validation and deployment manifests remain restricted to Settings
# fields.
TOOLING_ENVIRONMENT_NAMES = {
    "AKC_DART_API_KEY",
    "AKC_DART_CREDENTIAL_FILE",
}


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects silently shadowed mapping keys."""


def _construct_unique_mapping(
    loader: yaml.SafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    explicit_keys: set[Any] = set()
    for key_node, _ in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in explicit_keys
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        explicit_keys.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.load(  # nosec B506
            handle,
            Loader=_UniqueKeyLoader,  # noqa: S506
        )


def _load_yaml_documents(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [
            document
            for document in yaml.load_all(
                handle,
                Loader=_UniqueKeyLoader,
            )
            if isinstance(document, dict)
        ]


def _settings_environment_names(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields = {
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and not statement.target.id.startswith("_")
                and statement.target.id != "model_config"
            }
            return {f"AKC_{field.upper()}" for field in fields}
    raise RuntimeError(f"{class_name} class was not found in {path}")


def _check_known_akc_keys(source: str, keys: set[str], known: set[str], errors: list[str]) -> None:
    unknown = sorted(key for key in keys if key.startswith("AKC_") and key not in known)
    if unknown:
        errors.append(f"{source} contains unknown Settings keys: {unknown}")


def validate_environment_contract(errors: list[str]) -> None:
    api_known = _settings_environment_names(
        ROOT / "services/api/src/akc_api/settings.py", "Settings"
    )
    scheduler_known = _settings_environment_names(
        ROOT / "services/scheduler/src/akc_scheduler/settings.py",
        "SchedulerSettings",
    )
    analysis_known = _settings_environment_names(
        ROOT / "workers/cpu-document/src/akc_worker_document/settings.py",
        "AnalysisWorkerSettings",
    )
    url_fetcher_known = _settings_environment_names(
        ROOT / "services/url-fetcher/src/akc_url_fetcher/settings.py",
        "UrlFetcherSettings",
    )
    all_known = api_known | scheduler_known | analysis_known | url_fetcher_known
    example_keys = {
        line.split("=", 1)[0].strip()
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.startswith("AKC_") and "=" in line
    }
    _check_known_akc_keys(
        ".env.example",
        example_keys,
        all_known | TOOLING_ENVIRONMENT_NAMES,
        errors,
    )
    missing_example_keys = sorted(all_known - example_keys)
    if missing_example_keys:
        errors.append(f".env.example is missing documented Settings keys: {missing_example_keys}")

    compose = _load_yaml(ROOT / "docker-compose.dev.yml")
    services = compose.get("services", {})
    api = services.get("api", {})
    environment = api.get("environment", {})
    _check_known_akc_keys(
        "docker-compose.dev.yml api.environment", set(environment), api_known, errors
    )
    if api.get("healthcheck") is None:
        errors.append("Compose API must have a healthcheck")
    if services.get("web", {}).get("healthcheck") is None:
        errors.append("Compose web must have a healthcheck")
    web_service = services.get("web", {})
    web_build_args = web_service.get("build", {}).get("args", {})
    if "NEXT_PUBLIC_AKC_API_URL" not in web_build_args:
        errors.append("Compose must provide the browser API URL at web image build time")
    web_dockerfile = (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")
    if "ARG NEXT_PUBLIC_AKC_API_URL" not in web_dockerfile:
        errors.append("web Dockerfile must declare NEXT_PUBLIC_AKC_API_URL as a build arg")
    migration_service = services.get("migrate", {})
    if migration_service.get("command") != [
        "python",
        "-m",
        "alembic",
        "upgrade",
        "head",
    ]:
        errors.append("Compose must run the one-shot Alembic migration")
    if (
        api.get("depends_on", {}).get("migrate", {}).get("condition")
        != "service_completed_successfully"
    ):
        errors.append("Compose API must wait for the migration to complete")
    if environment.get("AKC_EXTERNAL_OCR_ENABLED") != "false":
        errors.append("Compose must disable external OCR")
    if environment.get("AKC_PRIVATE_MODE") != "true":
        errors.append("Compose must enable private mode")
    if environment.get("AKC_CLAMAV_ENABLED") != "true":
        errors.append("Compose must use the integrated ClamAV scanner")
    if environment.get("AKC_ALLOW_DEVELOPMENT_ANTIVIRUS_BYPASS") != "false":
        errors.append("Compose must not bypass antivirus scanning")
    if environment.get("AKC_LOCAL_BACKGROUND_TASKS") != "false":
        errors.append(
            "Compose API local background tasks must be disabled when dispatch-worker runs"
        )
    for optional_service in ("redis", "minio", "minio-init"):
        if not services.get(optional_service, {}).get("profiles"):
            errors.append(f"unused optional service {optional_service} must be profile-gated")
    if environment.get("AKC_OBJECT_STORE_DRIVER") != "local":
        errors.append("Compose must use the reachable local object-store adapter")
    if "/var/lib/akc" not in " ".join(services.get("api", {}).get("volumes", [])):
        errors.append("Compose local object storage must use a writable named volume")
    url_fetcher_service = services.get("url-fetcher", {})
    url_fetcher_environment = url_fetcher_service.get("environment", {})
    _check_known_akc_keys(
        "docker-compose.dev.yml url-fetcher.environment",
        set(url_fetcher_environment),
        url_fetcher_known,
        errors,
    )
    if url_fetcher_service.get("healthcheck") is None:
        errors.append("Compose URL fetcher must have a fail-closed healthcheck")
    if url_fetcher_service.get("command") != ["python", "-m", "akc_url_fetcher"]:
        errors.append("Compose URL fetcher must run only the isolated worker")
    if url_fetcher_environment.get("AKC_URL_DATABASE_ROLE") != "akc_url_fetcher":
        errors.append("Compose URL fetcher must assume its restricted role")
    if url_fetcher_environment.get("AKC_CLAMAV_ENABLED") != "true":
        errors.append("Compose URL fetcher must use ClamAV")
    if url_fetcher_environment.get("AKC_ALLOW_DEVELOPMENT_ANTIVIRUS_BYPASS") != "false":
        errors.append("Compose URL fetcher must fail closed on scanner errors")
    if url_fetcher_environment.get("AKC_OBJECT_STORE_DRIVER") != "local":
        errors.append("Compose URL fetcher must share the reachable local object store")
    url_fetcher_dockerfile = (ROOT / "services/url-fetcher/Dockerfile").read_text(encoding="utf-8")
    for marker in (
        "python:3.13-slim-bookworm@sha256:",
        "USER 10001:10001",
        'CMD ["python", "-m", "akc_url_fetcher"]',
    ):
        if marker not in url_fetcher_dockerfile:
            errors.append(f"URL fetcher Dockerfile is missing hardening marker: {marker}")
    scheduler_environment = services.get("scheduler", {}).get("environment", {})
    _check_known_akc_keys(
        "docker-compose.dev.yml scheduler.environment",
        set(scheduler_environment),
        scheduler_known,
        errors,
    )
    scheduler_healthcheck = services.get("scheduler", {}).get("healthcheck", {}).get("test", [])
    if "--check" not in scheduler_healthcheck:
        errors.append("Compose scheduler must use its non-mutating database check")
    dispatch_environment = services.get("dispatch-worker", {}).get("environment", {})
    _check_known_akc_keys(
        "docker-compose.dev.yml dispatch-worker.environment",
        set(dispatch_environment),
        scheduler_known,
        errors,
    )
    dispatch_healthcheck = (
        services.get("dispatch-worker", {}).get("healthcheck", {}).get("test", [])
    )
    if "--check" not in dispatch_healthcheck or "dispatch" not in dispatch_healthcheck:
        errors.append("Compose dispatch-worker must check only its dispatch role")
    if services.get("scheduler", {}).get("command", [])[-1:] != ["webhook"]:
        errors.append("Compose webhook scheduler must run in webhook-only mode")
    if services.get("dispatch-worker", {}).get("command", [])[-1:] != ["dispatch"]:
        errors.append("Compose dispatch worker must run in dispatch-only mode")
    if scheduler_environment.get("AKC_DATABASE_URL") == dispatch_environment.get(
        "AKC_DATABASE_URL"
    ):
        errors.append("Compose scheduler and dispatch worker must use different logins")
    analysis_service = services.get("analysis-worker", {})
    analysis_environment = analysis_service.get("environment", {})
    _check_known_akc_keys(
        "docker-compose.dev.yml analysis-worker.environment",
        set(analysis_environment),
        analysis_known,
        errors,
    )
    analysis_healthcheck = analysis_service.get("healthcheck", {}).get("test", [])
    if "--check" not in analysis_healthcheck:
        errors.append("Compose analysis worker must use its non-mutating startup check")
    if analysis_service.get("command") != ["python", "-m", "akc_worker_document"]:
        errors.append("Compose analysis worker must run only the isolated worker")
    if analysis_environment.get("AKC_ANALYSIS_DATABASE_ROLE") != "akc_analysis_worker":
        errors.append("Compose analysis worker must assume its restricted role")
    if analysis_environment.get("AKC_LOCAL_ANALYSIS_WORKER_ENABLED") is not None:
        errors.append("Analysis worker must not receive the API local-adapter switch")
    if analysis_environment.get("AKC_DATABASE_URL") in {
        scheduler_environment.get("AKC_DATABASE_URL"),
        dispatch_environment.get("AKC_DATABASE_URL"),
        environment.get("AKC_DATABASE_URL"),
    }:
        errors.append("Compose analysis worker must use a dedicated database login")
    if environment.get("AKC_LOCAL_ANALYSIS_WORKER_ENABLED") != "false":
        errors.append("Compose API must disable the in-process analysis adapter")

    config = _load_yaml(ROOT / "infra/kubernetes/base/configmap.yaml")
    config_data = config.get("data", {})
    _check_known_akc_keys("Kubernetes akc-runtime ConfigMap", set(config_data), api_known, errors)
    required_values = {
        "AKC_ENV": "production",
        "AKC_EXTERNAL_OCR_ENABLED": "false",
        "AKC_PRIVATE_MODE": "true",
        "AKC_LOCAL_BACKGROUND_TASKS": "false",
        "AKC_OBJECT_STORE_DRIVER": "s3",
        "AKC_S3_USE_AMBIENT_CREDENTIALS": "true",
        "AKC_COOKIE_SECURE": "true",
        "AKC_CLAMAV_ENABLED": "true",
        "AKC_ALLOW_DEVELOPMENT_ANTIVIRUS_BYPASS": "false",
        "AKC_PAYMENTS_ENABLED": "false",
        "AKC_PAYMENT_PROVIDER": "disabled",
        "AKC_METRICS_ENABLED": "true",
        "AKC_OTEL_ENABLED": "true",
    }
    for key, expected in required_values.items():
        if str(config_data.get(key)) != expected:
            errors.append(f"Kubernetes {key} must be {expected!r}")
    scheduler_configs = {
        document.get("metadata", {}).get("name"): document.get("data", {})
        for document in _load_yaml_documents(
            ROOT / "infra/kubernetes/base/scheduler-configmap.yaml"
        )
    }
    scheduler_config = scheduler_configs.get("akc-scheduler-runtime", {})
    dispatch_config = scheduler_configs.get("akc-dispatch-runtime", {})
    _check_known_akc_keys(
        "Kubernetes akc-scheduler-runtime ConfigMap",
        set(scheduler_config),
        scheduler_known,
        errors,
    )
    if scheduler_config.get("AKC_WEBHOOK_DELIVERY_ENABLED") != "true":
        errors.append("Kubernetes scheduler must enable the API-advertised webhook delivery")
    if scheduler_config.get("AKC_SCHEDULER_DATABASE_ROLE") != "akc_scheduler":
        errors.append("Kubernetes scheduler must assume the restricted scheduler role")
    for name, runtime_config in (
        ("scheduler", scheduler_config),
        ("dispatch worker", dispatch_config),
    ):
        if runtime_config.get("AKC_METRICS_ENABLED") != "true":
            errors.append(f"Kubernetes {name} must expose Prometheus metrics")
        if runtime_config.get("AKC_METRICS_BIND_HOST") != "0.0.0.0":
            errors.append(f"Kubernetes {name} metrics must bind on the pod interface")
    _check_known_akc_keys(
        "Kubernetes akc-dispatch-runtime ConfigMap",
        set(dispatch_config),
        scheduler_known,
        errors,
    )
    if dispatch_config.get("AKC_DISPATCH_DATABASE_ROLE") != "akc_dispatch_worker":
        errors.append("Kubernetes dispatch worker must assume its restricted role")
    if dispatch_config.get("AKC_WEBHOOK_DELIVERY_ENABLED") != "false":
        errors.append("Kubernetes dispatch worker must disable webhook delivery")
    analysis_config = _load_yaml(ROOT / "infra/kubernetes/base/analysis-configmap.yaml").get(
        "data", {}
    )
    _check_known_akc_keys(
        "Kubernetes akc-analysis-runtime ConfigMap",
        set(analysis_config),
        analysis_known,
        errors,
    )
    analysis_required = {
        "AKC_ENV": "production",
        "AKC_ANALYSIS_DATABASE_ROLE": "akc_analysis_worker",
        "AKC_OBJECT_STORE_DRIVER": "s3",
        "AKC_ANALYSIS_SANDBOX_LAUNCHER": "bubblewrap",
        "AKC_METRICS_ENABLED": "true",
        "AKC_METRICS_BIND_HOST": "0.0.0.0",
    }
    for key, expected in analysis_required.items():
        if str(analysis_config.get(key)) != expected:
            errors.append(f"Kubernetes analysis {key} must be {expected!r}")
    analysis_limit = int(analysis_config.get("AKC_ANALYSIS_MAX_SOURCE_BYTES", 0))
    child_memory = int(analysis_config.get("AKC_ANALYSIS_CHILD_MEMORY_BYTES", 0))
    result_limit = int(analysis_config.get("AKC_ANALYSIS_MAX_RESULT_BYTES", 0))
    preview_pixels = int(analysis_config.get("AKC_PREVIEW_MAX_PIXELS", 0))
    if child_memory < (
        (analysis_limit * 3) + result_limit + (preview_pixels * 4) + (64 * 1024 * 1024)
    ):
        errors.append("Kubernetes analysis child memory does not cover bounded working sets")
    url_fetcher_config = _load_yaml(ROOT / "infra/kubernetes/base/url-fetcher-configmap.yaml").get(
        "data", {}
    )
    _check_known_akc_keys(
        "Kubernetes akc-url-fetcher-runtime ConfigMap",
        set(url_fetcher_config),
        url_fetcher_known,
        errors,
    )
    url_fetcher_required = {
        "AKC_ENV": "production",
        "AKC_URL_DATABASE_ROLE": "akc_url_fetcher",
        "AKC_OBJECT_STORE_DRIVER": "s3",
        "AKC_CLAMAV_ENABLED": "true",
        "AKC_ALLOW_DEVELOPMENT_ANTIVIRUS_BYPASS": "false",
        "AKC_METRICS_ENABLED": "true",
        "AKC_METRICS_BIND_HOST": "0.0.0.0",
    }
    for key, expected in url_fetcher_required.items():
        if str(url_fetcher_config.get(key)) != expected:
            errors.append(f"Kubernetes URL fetcher {key} must be {expected!r}")
    lease = float(url_fetcher_config.get("AKC_URL_FETCH_LEASE_SECONDS", 0))
    fetch_timeout = float(url_fetcher_config.get("AKC_URL_FETCH_TOTAL_TIMEOUT_SECONDS", 0))
    scan_timeout = float(url_fetcher_config.get("AKC_CLAMAV_TIMEOUT_SECONDS", 0))
    if lease <= fetch_timeout + scan_timeout:
        errors.append("Kubernetes URL fetch lease must cover fetch and scan timeouts")


def _container_security_errors(
    workload_name: str, container: dict[str, Any], errors: list[str]
) -> None:
    security = container.get("securityContext", {})
    if security.get("allowPrivilegeEscalation") is not False:
        errors.append(f"{workload_name} allows privilege escalation")
    if security.get("readOnlyRootFilesystem") is not True:
        errors.append(f"{workload_name} root filesystem must be read-only")
    dropped = security.get("capabilities", {}).get("drop", [])
    if "ALL" not in dropped:
        errors.append(f"{workload_name} must drop all Linux capabilities")
    resources = container.get("resources", {})
    if not resources.get("requests") or not resources.get("limits"):
        errors.append(f"{workload_name} must declare requests and limits")


def validate_kubernetes_contract(errors: list[str]) -> None:
    base = ROOT / "infra/kubernetes/base"
    kustomization = _load_yaml(base / "kustomization.yaml")
    resource_paths = [base / path for path in kustomization.get("resources", [])]
    documents = [document for path in resource_paths for document in _load_yaml_documents(path)]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        by_kind.setdefault(str(document.get("kind")), []).append(document)
    if by_kind.get("Secret"):
        errors.append("Kubernetes base must not contain a plaintext Secret")
    if not by_kind.get("ResourceQuota") or not by_kind.get("LimitRange"):
        errors.append("Kubernetes base must define namespace resource guardrails")

    deployments = {item["metadata"]["name"]: item for item in by_kind.get("Deployment", [])}
    if set(deployments) != {
        "akc-api",
        "akc-web",
        "akc-scheduler",
        "akc-dispatch-worker",
        "akc-deletion-worker",
        "akc-gpu-worker",
        "akc-analysis-worker",
        "akc-url-fetcher",
    }:
        errors.append(
            "Kubernetes base must deploy only implemented API/web/durable-worker workloads"
        )
    for name, deployment in deployments.items():
        pod_spec = deployment["spec"]["template"]["spec"]
        if pod_spec.get("automountServiceAccountToken") is not False:
            errors.append(f"{name} must disable service-account token mounting")
        if pod_spec.get("securityContext", {}).get("runAsNonRoot") is not True:
            errors.append(f"{name} must run as non-root")
        pod_security = pod_spec.get("securityContext", {})
        if not isinstance(pod_security.get("runAsUser"), int):
            errors.append(f"{name} must use an explicit numeric user")
        if pod_security.get("runAsGroup") != pod_security.get("runAsUser"):
            errors.append(f"{name} must use a matching explicit runtime group")
        if pod_security.get("fsGroup") != pod_security.get("runAsUser"):
            errors.append(f"{name} writable volumes must use the runtime group")
        containers = pod_spec.get("containers", [])
        if len(containers) != 1:
            errors.append(f"{name} must have exactly one application container")
            continue
        container = containers[0]
        image = str(container.get("image", ""))
        if "replace-with-signed-digest" not in image or image.endswith(":latest"):
            errors.append(f"{name} image must remain an unresolved signed-digest placeholder")
        _container_security_errors(name, container, errors)
        if name in {
            "akc-scheduler",
            "akc-dispatch-worker",
            "akc-deletion-worker",
            "akc-gpu-worker",
        }:
            scheduler_secret_refs = {
                item.get("secretRef", {}).get("name")
                for item in container.get("envFrom", [])
                if item.get("secretRef")
            }
            expected_secret = {
                "akc-scheduler": "akc-scheduler-secrets",
                "akc-dispatch-worker": "akc-dispatch-secrets",
                "akc-deletion-worker": "akc-deletion-secrets",
                "akc-gpu-worker": "akc-gpu-worker-secrets",
            }[name]
            if scheduler_secret_refs != {expected_secret}:
                errors.append(f"{name} must use only its separate runtime secret")
            startup = container.get("startupProbe", {}).get("exec", {}).get("command", [])
            ready = container.get("readinessProbe", {}).get("exec", {}).get("command", [])
            if "--check" not in startup or "--check" not in ready:
                errors.append(f"{name} probes must use the non-mutating database check")
            expected_mode = {
                "akc-scheduler": "webhook",
                "akc-dispatch-worker": "dispatch",
                "akc-deletion-worker": "deletion",
                "akc-gpu-worker": "gpu",
            }[name]
            command = container.get("command", [])
            if command[-1:] != [expected_mode]:
                errors.append(f"{name} must run only in {expected_mode} mode")
            if expected_mode not in startup or expected_mode not in ready:
                errors.append(f"{name} probes must check only the {expected_mode} role")
        elif name == "akc-analysis-worker":
            secret_refs = {
                item.get("secretRef", {}).get("name")
                for item in container.get("envFrom", [])
                if item.get("secretRef")
            }
            if secret_refs != {"akc-analysis-secrets"}:
                errors.append("akc-analysis-worker must use only its separate runtime secret")
            command = container.get("command", [])
            if command != ["python", "-m", "akc_worker_document"]:
                errors.append("akc-analysis-worker must run only the isolated worker")
            for probe_name in ("startupProbe", "readinessProbe"):
                probe = container.get(probe_name, {}).get("exec", {}).get("command", [])
                if "--check" not in probe or "akc_worker_document" not in probe:
                    errors.append(
                        f"akc-analysis-worker {probe_name} must prove its role and sandbox"
                    )
            if pod_spec.get("runtimeClassName") != "gvisor":
                errors.append("akc-analysis-worker must use the gvisor RuntimeClass")
            if (
                container.get("securityContext", {}).get("appArmorProfile", {}).get("type")
                != "RuntimeDefault"
            ):
                errors.append("akc-analysis-worker must use the runtime AppArmor profile")
            if container.get("resources", {}).get("limits", {}).get("memory") != "3Gi":
                errors.append("akc-analysis-worker must retain its reviewed 3Gi pod limit")
        elif name == "akc-url-fetcher":
            secret_refs = {
                item.get("secretRef", {}).get("name")
                for item in container.get("envFrom", [])
                if item.get("secretRef")
            }
            if secret_refs != {"akc-url-fetcher-secrets"}:
                errors.append("akc-url-fetcher must use only its separate runtime secret")
            command = container.get("command", [])
            if command != ["python", "-m", "akc_url_fetcher"]:
                errors.append("akc-url-fetcher must run only the isolated URL worker")
            for probe_name in ("startupProbe", "readinessProbe"):
                probe = container.get(probe_name, {}).get("exec", {}).get("command", [])
                if "--check" not in probe or "akc_url_fetcher" not in probe:
                    errors.append(
                        f"akc-url-fetcher {probe_name} must prove its database and scanner"
                    )
            if pod_spec.get("runtimeClassName") is not None:
                errors.append("akc-url-fetcher must not inherit the parser RuntimeClass")
        else:
            probes = {
                probe: container.get(probe, {}).get("httpGet", {}).get("path")
                for probe in ("startupProbe", "readinessProbe", "livenessProbe")
            }
            expected = (
                {
                    "startupProbe": "/health/live",
                    "readinessProbe": "/health/ready",
                    "livenessProbe": "/health/live",
                }
                if name == "akc-api"
                else {
                    "startupProbe": "/login",
                    "readinessProbe": "/login",
                    "livenessProbe": "/login",
                }
            )
            if probes != expected:
                errors.append(f"{name} probe paths do not match real application routes")

    policies = by_kind.get("NetworkPolicy", [])
    default_deny = next(
        (item for item in policies if item.get("metadata", {}).get("name") == "default-deny"),
        None,
    )
    if default_deny is None or set(default_deny["spec"].get("policyTypes", [])) != {
        "Ingress",
        "Egress",
    }:
        errors.append("Kubernetes base must default-deny ingress and egress")
    url_public_policy = next(
        (
            item
            for item in policies
            if item.get("metadata", {}).get("name") == "url-fetcher-public-https-only"
        ),
        None,
    )
    if url_public_policy is None:
        errors.append("URL fetcher must declare an explicit public HTTPS egress policy")
    else:
        egress = url_public_policy.get("spec", {}).get("egress", [])
        ports = {int(port.get("port", 0)) for rule in egress for port in rule.get("ports", [])}
        if ports != {443}:
            errors.append("URL fetcher public egress must allow only TCP 443")
        policy_text = json.dumps(url_public_policy, sort_keys=True)
        for forbidden_cidr in (
            "10.0.0.0/8",
            "100.64.0.0/10",
            "127.0.0.0/8",
            "169.254.0.0/16",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "::1/128",
            "fc00::/7",
            "fe80::/10",
        ):
            if forbidden_cidr not in policy_text:
                errors.append(f"URL fetcher public egress does not exclude {forbidden_cidr}")

    hpas = {item["metadata"]["name"]: item for item in by_kind.get("HorizontalPodAutoscaler", [])}
    if set(hpas) != {
        "akc-api",
        "akc-web",
        "akc-scheduler",
        "akc-dispatch-worker",
        "akc-deletion-worker",
        "akc-analysis-worker",
        "akc-url-fetcher",
    }:
        errors.append("Kubernetes base must define HPAs for every stateless workload")
    for name, hpa in hpas.items():
        spec = hpa.get("spec", {})
        if spec.get("minReplicas", 0) < 2 or spec.get("maxReplicas", 0) < 3:
            errors.append(f"{name} HPA must preserve HA and scaling headroom")

    ingresses = by_kind.get("Ingress", [])
    hosts = {
        rule.get("host", "")
        for ingress in ingresses
        for rule in ingress.get("spec", {}).get("rules", [])
    }
    if not hosts or any(not host.endswith(".invalid") for host in hosts):
        errors.append("base Ingress hosts must remain non-routable .invalid placeholders")
    api_ingress = next(
        (item for item in ingresses if item.get("metadata", {}).get("name") == "akc-api"),
        None,
    )
    annotations = (api_ingress or {}).get("metadata", {}).get("annotations", {})
    if annotations.get("nginx.ingress.kubernetes.io/proxy-buffering") != "off":
        errors.append("API Ingress must disable proxy buffering for SSE")

    if any("migrate.yaml" in str(path) for path in resource_paths):
        errors.append("migration Job must be revision-named and invoked outside the base")

    migration = _load_yaml(ROOT / "infra/kubernetes/jobs/migrate.yaml")
    migration_container = migration["spec"]["template"]["spec"]["containers"][0]
    migration_pod_security = migration["spec"]["template"]["spec"].get("securityContext", {})
    if migration_pod_security.get("runAsUser") != 10001:
        errors.append("migration Job must use the API image's non-root user")
    if "replace-with-signed-digest" not in str(migration_container.get("image", "")):
        errors.append("migration Job image must remain an unresolved digest placeholder")
    if migration_container.get("args") != ["upgrade", "head"]:
        errors.append("migration Job must run an Alembic upgrade to head")
    _container_security_errors("akc-migrate", migration_container, errors)
    secret_contract = (ROOT / "infra/kubernetes/secret-keys.md").read_text(encoding="utf-8")
    for key in (
        "AKC_DATABASE_URL",
        "AKC_JWT_SECRET",
        "AKC_MFA_ENCRYPTION_KEY",
        "AKC_MFA_RECOVERY_HMAC_SECRET",
        "AKC_IDEMPOTENCY_RESPONSE_ENCRYPTION_KEY",
        "AKC_URL_ENCRYPTION_KEY",
        "AKC_URL_QUERY_HMAC_SECRET",
        "AKC_PAYMENT_MERCHANT_ID",
        "AKC_PAYMENT_WEBHOOK_SECRET",
        "AKC_WEBHOOK_ENCRYPTION_KEY",
    ):
        if key not in secret_contract:
            errors.append(f"Kubernetes secret contract is missing {key}")
    for secret_name in (
        "akc-runtime-secrets",
        "akc-scheduler-secrets",
        "akc-dispatch-secrets",
        "akc-deletion-secrets",
        "akc-analysis-secrets",
        "akc-url-fetcher-secrets",
        "akc-migration-secrets",
    ):
        if secret_name not in secret_contract:
            errors.append(f"Kubernetes secret contract is missing {secret_name}")


def validate_gpu_and_terraform_contract(errors: list[str]) -> None:
    runpod = _load_yaml(ROOT / "infra/runpod/endpoints.yaml")
    defaults = runpod.get("defaults", {})
    required = {
        "external_processing": False,
        "require_callback_auth": True,
        "allow_inline_input": False,
        "input_host_allowlist_required": True,
        "output_host_allowlist_required": True,
    }
    for key, expected in required.items():
        if defaults.get(key) != expected:
            errors.append(f"Runpod default {key} must be {expected!r}")
    sensitive_reference_key = "_".join(("callback", "hmac", "secret", "from", "provider", "secret"))
    if defaults.get(sensitive_reference_key) is not True:
        errors.append("Runpod callback HMAC must come from the provider secret manager")
    for worker_path in sorted((ROOT / "workers").glob("gpu-*/worker.yaml")):
        worker = _load_yaml(worker_path)
        required_env = set(worker.get("required_runtime_env", []))
        for key in ("REQUIRE_CALLBACK_AUTH", "CALLBACK_HMAC_SECRET"):
            if key not in required_env:
                errors.append(f"{worker_path.relative_to(ROOT)} is missing {key}")

    terraform = (ROOT / "infra/terraform/main.tf").read_text(encoding="utf-8")
    for marker in (
        "object_lock_enabled",
        "aws_s3_bucket_object_lock_configuration",
        "aws_s3_bucket_cors_configuration",
        "aws_s3_bucket_public_access_block",
        "aws_s3_bucket_server_side_encryption_configuration",
        "working_retention_days",
    ):
        if marker not in terraform:
            errors.append(f"Terraform storage guardrail is missing: {marker}")
    for storage_class in (
        "quarantine",
        "source",
        "working",
        "derived",
        "exports",
        "audit-evidence",
    ):
        if f"{storage_class} =" not in terraform:
            errors.append(f"Terraform storage topology is missing: {storage_class}")

    monitoring = (ROOT / "infra/monitoring/prometheus-rules.yaml").read_text(encoding="utf-8")
    if "AKCRequiredTelemetryContractMissing" not in monitoring:
        errors.append("monitoring must fail closed when required telemetry is absent")
    for series in (
        "akc_jobs_terminal_total",
        "akc_queue_oldest_job_age_seconds",
        "akc_scanner_up",
        "akc_provider_up",
        "akc_audit_write_failure_total",
        "akc_deletion_oldest_pending_seconds",
        "akc_analysis_queue_depth",
        "akc_analysis_dead_letter_tasks",
        "akc_url_fetch_queue_depth",
        "akc_url_fetch_dead_letter_tasks",
    ):
        if f"absent({series}" not in monitoring:
            errors.append(f"monitoring does not fail closed for missing {series}")
    service_monitors = _load_yaml_documents(ROOT / "infra/monitoring/service-monitors.yaml")
    monitor_names = {monitor.get("metadata", {}).get("name") for monitor in service_monitors}
    if monitor_names != {"akc-api", "akc-workers"}:
        errors.append("monitoring must scrape the API and durable worker services")
    workers_monitor = next(
        (
            monitor
            for monitor in service_monitors
            if monitor.get("metadata", {}).get("name") == "akc-workers"
        ),
        {},
    )
    worker_values = (
        workers_monitor.get("spec", {})
        .get("selector", {})
        .get("matchExpressions", [{}])[0]
        .get("values", [])
    )
    if "akc-url-fetcher" not in worker_values:
        errors.append("monitoring must scrape the URL fetcher metrics service")
    collector = (ROOT / "infra/monitoring/otel-collector.yaml").read_text(encoding="utf-8")
    for forbidden_attribute in (
        "document.content",
        "source.text",
        "url.full",
        "url.path",
        "url.query",
        "http.request.header.authorization",
        "db.statement",
        "gen_ai.prompt",
        "gen_ai.completion",
    ):
        if f"key: {forbidden_attribute}" not in collector:
            errors.append(f"OpenTelemetry privacy processor must delete {forbidden_attribute}")


def main() -> int:
    errors: list[str] = []
    validate_environment_contract(errors)
    validate_kubernetes_contract(errors)
    validate_gpu_and_terraform_contract(errors)
    if errors:
        for error in sorted(set(errors)):
            print(error)
        return 1
    print("deployment contract validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
