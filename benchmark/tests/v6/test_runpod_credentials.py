from __future__ import annotations

import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.credentials import RunPodCredentialSet


def test_two_process_local_keys_are_loaded_without_repr_disclosure(monkeypatch) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", "primary-secret")
    monkeypatch.setenv("RUNPOD_API_KEY_FALLBACK", "fallback-secret")
    credentials = RunPodCredentialSet.from_environment()
    assert credentials.count == 2
    assert credentials.primary == "primary-secret"
    assert credentials.fallback == "fallback-secret"
    rendered = repr(credentials)
    assert "primary-secret" not in rendered
    assert "fallback-secret" not in rendered


def test_duplicate_fallback_is_deduplicated(monkeypatch) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", "same-secret")
    monkeypatch.setenv("RUNPOD_API_KEY_FALLBACK", "same-secret")
    assert RunPodCredentialSet.from_environment().count == 1


def test_missing_credentials_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("RUNPOD_API_KEY_FALLBACK", raising=False)
    with pytest.raises(ContractError, match="RUNPOD_API_KEY"):
        RunPodCredentialSet.from_environment()