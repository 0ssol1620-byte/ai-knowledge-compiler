from __future__ import annotations

from copy import deepcopy

import pytest

from infra.security.validate_deployment import (
    ROOT,
    _load_yaml_documents,
    _validate_collection_finalizer_network_policies,
    _validate_collection_runtime_activation,
)


def _base_api_config() -> dict[str, str]:
    return {
        "AKC_COLLECTION_METADATA_ENCRYPTION_ENABLED": "false",
        "AKC_COLLECTION_SEMANTIC_RETRIEVAL_ENABLED": "false",
    }


def _base_dispatch_config() -> dict[str, str]:
    return {
        "AKC_COLLECTION_FINALIZER_ENABLED": "false",
        "AKC_COLLECTION_FINALIZER_API_URL": (
            "http://akc-api:8000/v1/internal/collections/finalize"
        ),
        "AKC_COLLECTION_FINALIZER_TIMEOUT_SECONDS": "300",
    }


def _base_network_policies() -> list[dict[str, object]]:
    return _load_yaml_documents(ROOT / "infra/kubernetes/base/network-policies.yaml")


def test_base_collection_runtime_is_atomically_disabled_with_exact_policies() -> None:
    errors: list[str] = []

    _validate_collection_runtime_activation(
        _base_api_config(),
        _base_dispatch_config(),
        errors,
    )
    _validate_collection_finalizer_network_policies(_base_network_policies(), errors)

    assert errors == []


@pytest.mark.parametrize(
    ("retrieval_enabled", "finalizer_enabled"),
    [("true", "false"), ("false", "true")],
)
def test_collection_runtime_rejects_mixed_activation(
    retrieval_enabled: str,
    finalizer_enabled: str,
) -> None:
    api_config = _base_api_config()
    dispatch_config = _base_dispatch_config()
    api_config["AKC_COLLECTION_SEMANTIC_RETRIEVAL_ENABLED"] = retrieval_enabled
    if retrieval_enabled == "true":
        api_config["AKC_COLLECTION_METADATA_ENCRYPTION_ENABLED"] = "true"
    dispatch_config["AKC_COLLECTION_FINALIZER_ENABLED"] = finalizer_enabled
    errors: list[str] = []

    _validate_collection_runtime_activation(api_config, dispatch_config, errors)

    assert errors == [
        "Kubernetes collection finalizer and semantic retrieval must be enabled atomically"
    ]


def test_semantic_retrieval_rejects_plaintext_collection_metadata() -> None:
    api_config = _base_api_config()
    dispatch_config = _base_dispatch_config()
    api_config["AKC_COLLECTION_SEMANTIC_RETRIEVAL_ENABLED"] = "true"
    dispatch_config["AKC_COLLECTION_FINALIZER_ENABLED"] = "true"
    errors: list[str] = []

    _validate_collection_runtime_activation(api_config, dispatch_config, errors)

    assert errors == ["Kubernetes semantic retrieval requires encrypted collection metadata"]


@pytest.mark.parametrize(
    "missing_policy",
    ["dispatch-worker-to-api-finalizer", "api-from-dispatch-finalizer"],
)
def test_collection_finalizer_network_policy_requires_both_directions(
    missing_policy: str,
) -> None:
    policies = [
        policy
        for policy in _base_network_policies()
        if policy.get("metadata", {}).get("name") != missing_policy
    ]
    errors: list[str] = []

    _validate_collection_finalizer_network_policies(policies, errors)

    assert errors == [
        f"Kubernetes finalizer policy {missing_policy} must allow only its TCP 8000 peer"
    ]


def test_collection_finalizer_network_policy_rejects_broader_egress_port() -> None:
    policies = deepcopy(_base_network_policies())
    policy = next(
        item
        for item in policies
        if item.get("metadata", {}).get("name") == "dispatch-worker-to-api-finalizer"
    )
    policy["spec"]["egress"][0]["ports"].append({"protocol": "TCP", "port": 443})
    errors: list[str] = []

    _validate_collection_finalizer_network_policies(policies, errors)

    assert errors == [
        "Kubernetes finalizer policy dispatch-worker-to-api-finalizer "
        "must allow only its TCP 8000 peer"
    ]


def test_collection_finalizer_network_policy_rejects_unscoped_ingress_peer() -> None:
    policies = deepcopy(_base_network_policies())
    policy = next(
        item
        for item in policies
        if item.get("metadata", {}).get("name") == "api-from-dispatch-finalizer"
    )
    policy["spec"]["ingress"][0]["from"] = [{}]
    errors: list[str] = []

    _validate_collection_finalizer_network_policies(policies, errors)

    assert errors == [
        "Kubernetes finalizer policy api-from-dispatch-finalizer must allow only its TCP 8000 peer"
    ]
