from __future__ import annotations

import pytest
from run_stratified_audit_campaign import _eligible_audit_workers


def test_expansion_workers_fill_audit_capacity_after_primary_quarantine() -> None:
    config = {
        "workers": [
            {"worker_index": index, "host": "host", "port": 10000 + index}
            for index in range(7)
        ]
    }
    health = {
        "eligible_retry_workers": [0, 3],
        "quarantined_worker_indices": [1, 2],
    }
    assert _eligible_audit_workers(config, health) == (0, 3, 4, 5, 6)


def test_audit_capacity_fails_closed_without_three_eligible_pods() -> None:
    config = {
        "workers": [
            {"worker_index": index, "host": "host", "port": 10000 + index}
            for index in range(4)
        ]
    }
    health = {
        "eligible_retry_workers": [0, 3],
        "quarantined_worker_indices": [1, 2],
    }
    with pytest.raises(ValueError, match="three eligible"):
        _eligible_audit_workers(config, health)


def test_revalidated_expansion_only_pool_is_sufficient_after_primary_cleanup() -> None:
    config = {
        "workers": [
            {"worker_index": index, "host": "host", "port": 10000 + index}
            for index in (4, 5, 6)
        ]
    }
    health = {
        "eligible_retry_workers": [0, 3],
        "quarantined_worker_indices": [1, 2],
    }
    assert _eligible_audit_workers(config, health) == (4, 5, 6)
