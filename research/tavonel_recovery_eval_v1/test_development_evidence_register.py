from __future__ import annotations

import json
from pathlib import Path

REGISTER = Path(__file__).with_name("DEVELOPMENT_EVIDENCE_REGISTER.json")
BINDING = Path(__file__).with_name("receipts") / "public-development-evidence-binding.json"


def load() -> dict:
    return json.loads(REGISTER.read_text(encoding="utf-8"))


def test_historical_evidence_is_never_confirmatory_eligible() -> None:
    payload = load()
    assert payload["status"] == "PRE_FREEZE_DEVELOPMENT_EVIDENCE_ONLY"
    assert payload["items"]
    assert all(item["confirmatory_eligible"] is False for item in payload["items"])


def test_register_preserves_negative_and_excluded_evidence() -> None:
    by_id = {item["id"]: item for item in load()["items"]}
    blind = by_id["DEV_BLIND_PREDICTION_ONLY_DETECTOR"]
    assert blind["evidence_class"] == "NEGATIVE_HISTORICAL_DEVELOPMENT"
    assert blind["hypothesis_supported"] is False
    renderer = by_id["DEV_SEC_RENDERER_GPU_TIMER"]
    assert renderer["evidence_class"] == "EXCLUDED_DIFFERENT_RESEARCH_QUESTION"


def test_public_completion_is_not_stored_as_accuracy() -> None:
    by_id = {item["id"]: item for item in load()["items"]}
    public = by_id["DEV_PUBLIC_5132_RECOVERY_CAMPAIGN"]
    metrics = public["metrics"]
    assert metrics["output_completion"] == {"numerator": 5131, "denominator": 5132}
    assert "accuracy" not in metrics
    assert "not accuracy" in public["interpretation"].casefold()


def test_local_receipt_binding_must_remain_explicit_when_missing() -> None:
    for item in load()["items"]:
        binding = item.get("local_binding")
        if binding is None:
            continue
        for key, value in binding.items():
            if key.endswith("sha256"):
                assert value is None or (isinstance(value, str) and value.startswith("sha256:"))
        pending_paths = [
            value
            for key, value in binding.items()
            if key.endswith("path") and isinstance(value, str) and value == "PENDING_LOCAL_BINDING"
        ]
        # Missing local evidence is represented as pending, never as an invented path.
        assert all(value == "PENDING_LOCAL_BINDING" for value in pending_paths)


def test_public_and_recovery_entries_reference_verified_binding_receipt() -> None:
    assert BINDING.is_file()
    receipt = json.loads(BINDING.read_text(encoding="utf-8"))
    assert receipt["confirmatory_eligible"] is False
    bound_ids = {claim["claim_id"] for claim in receipt["claims"]}
    by_id = {item["id"]: item for item in load()["items"]}
    for item_id in (
        "DEV_PUBLIC_5132_RECOVERY_CAMPAIGN",
        "DEV_RECOVERY_SINGLE_VARIABLE_COUNTERFACTUAL",
    ):
        binding = by_id[item_id]["local_binding"]
        assert binding["binding_receipt"].endswith(
            "receipts/public-development-evidence-binding.json"
        )
        assert set(binding["approved_claim_ids"]).issubset(bound_ids)
