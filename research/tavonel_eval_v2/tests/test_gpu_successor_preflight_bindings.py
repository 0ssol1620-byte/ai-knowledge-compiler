"""CPU-only binding tests for GPU successor protocol and model-pin preflight."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import freeze_gpu_successor_protocols as freeze  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402
import resolve_gpu_successor_pin as resolver  # noqa: E402
from common import canonical_sha, sha_file  # noqa: E402


def _protocol(path: Path, *, schema: str, protocol_id: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"schema: {schema}",
                f"protocol_id: {protocol_id}",
                f"study_id: {freeze.STUDY_ID}",
                "status: DRAFT_NOT_FROZEN",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _land_freeze(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    study = tmp_path / "study.yaml"
    runtime = tmp_path / "runtime.yaml"
    _protocol(
        study,
        schema="tavonel.v2.protocol.gpu_successor_study.v1",
        protocol_id="GPU_SUCCESSOR_STUDY_V1",
    )
    _protocol(
        runtime,
        schema="tavonel.v2.protocol.gpu_successor_runtime.v1",
        protocol_id="GPU_SUCCESSOR_RUNTIME_V1",
    )
    body = freeze.build_freeze(study, runtime)
    body["provenance"] = {
        "schema": freeze.IMMUTABLE_ENVELOPE_SCHEMA,
        "immutable": True,
        "receipt_stem": freeze.STEM,
    }
    body["receipt_sha256"] = canonical_sha(body)
    receipt = tmp_path / "freeze.json"
    receipt.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return study, runtime, receipt, sha_file(receipt)


def test_bundle_freeze_binds_both_exact_specifications(tmp_path: Path) -> None:
    study, runtime, receipt, digest = _land_freeze(tmp_path)
    result = freeze.verify_freeze(
        receipt,
        digest,
        study_path=study,
        runtime_path=runtime,
    )
    assert result["passed"] is True
    assert result["checks"]["study_sha256"] is True
    assert result["checks"]["runtime_sha256"] is True


def test_bundle_freeze_refuses_receipt_digest_drift(tmp_path: Path) -> None:
    study, runtime, receipt, _digest = _land_freeze(tmp_path)
    result = freeze.verify_freeze(
        receipt,
        "sha256:" + "0" * 64,
        study_path=study,
        runtime_path=runtime,
    )
    assert result["passed"] is False
    assert "drift" in result["why"]


@pytest.mark.parametrize("which", ["study", "runtime"])
def test_bundle_freeze_refuses_either_specification_drifting(
    tmp_path: Path, which: str
) -> None:
    study, runtime, receipt, digest = _land_freeze(tmp_path)
    target = study if which == "study" else runtime
    target.write_text(target.read_text(encoding="utf-8") + "changed: true\n", encoding="utf-8")
    result = freeze.verify_freeze(
        receipt,
        digest,
        study_path=study,
        runtime_path=runtime,
    )
    assert result["passed"] is False
    assert result["checks"][f"{which}_sha256"] is False


def test_model_pin_loader_reads_nested_resolver_receipt() -> None:
    receipt = (
        NS
        / "receipts"
        / "gpu-successor-pin--20260823T082423Z-6902ef5f7efa.json"
    )
    result = gsp.load_model_pin_artifact(receipt, sha_file(receipt))
    assert result["passed"] is True
    assert result["kind"] == "resolver_receipt"
    assert result["resolved_pin"]["revision"] != "latest"


def test_model_pin_loader_refuses_nested_receipt_without_immutable_envelope(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forged.json"
    path.write_text(json.dumps({"resolved_pin": {"repository": "x"}}), encoding="utf-8")
    result = gsp.load_model_pin_artifact(path, sha_file(path))
    assert result["passed"] is False
    assert result["kind"] == "resolver_receipt"


def test_model_pin_loader_accepts_exact_flat_sealed_export(tmp_path: Path) -> None:
    path = tmp_path / "pin.json"
    resolved = {
        "repository": "Qwen/Qwen3.6-27B",
        "revision": "6a9e13bd6fc8f0983b9b99948120bc37f49c13e9",
        "tokenizer_file_sha256": "sha256:" + "a" * 64,
        "capability_evidence": "attestation.json#config.json",
    }
    written = resolver.write_sealed_export(path, resolved)
    result = gsp.load_model_pin_artifact(path, written["sealed_export_file_sha256"])
    assert result["passed"] is True
    assert result["kind"] == "sealed_flat_export"
    assert result["resolved_pin"] == resolved


def test_model_pin_loader_refuses_flat_export_digest_drift(tmp_path: Path) -> None:
    path = tmp_path / "pin.json"
    resolver.write_sealed_export(
        path,
        {
            "repository": "repo",
            "revision": "1" * 40,
            "tokenizer_file_sha256": "sha256:" + "2" * 64,
        },
    )
    result = gsp.load_model_pin_artifact(path, "sha256:" + "0" * 64)
    assert result["passed"] is False
    assert "drift" in result["why"]


def test_flat_export_cannot_make_a_short_revision_exactly_pinned(tmp_path: Path) -> None:
    path = tmp_path / "pin.json"
    written = resolver.write_sealed_export(
        path,
        {
            "repository": "repo",
            "revision": "1234",
            "tokenizer_file_sha256": "sha256:" + "2" * 64,
        },
    )
    loaded = gsp.load_model_pin_artifact(path, written["sealed_export_file_sha256"])
    assert loaded["passed"] is True
    assert gsp.model_identity_pin(loaded["resolved_pin"])["pinned_by_exact_revision"] is False


def test_preflight_blocks_without_exact_freeze_and_model_pin_bindings(tmp_path: Path) -> None:
    body = gsp.run(
        manifest=tmp_path / "missing.json",
        model_pin={},
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
    )
    assert "G_GSP_PROTOCOL_BUNDLE_FROZEN" in body["blocking_gates"]
    assert "G_GSP_MODEL_PIN_SOURCE_SEALED" in body["blocking_gates"]


# ---------------------------------------------------------------------------
# INC-V2-036 class: three gates that were true for every input
# ---------------------------------------------------------------------------
#
# Each of the three below was a mutation SURVIVOR before this block existed:
# the thing the gate claims to protect was changed and neither the gate nor any
# test went red. The controls are paired on purpose -- a gate that refuses
# everything proves as little as one that accepts everything -- so each pair
# holds a green route and the specific mutation that must redden it.

REAL_PIN = NS / "receipts" / "gpu-successor-pin--20260823T082423Z-6902ef5f7efa.json"


def _sealed_attestation() -> dict:
    loaded = gsp.load_model_pin_artifact(REAL_PIN, sha_file(REAL_PIN))
    assert loaded["passed"] is True
    return loaded["tokenizer_parity_attestation"]


def test_the_probe_battery_is_bound_to_the_sealed_pins_attestation() -> None:
    """Green: the live battery still hashes to what the sealed pin recorded."""
    parity = gsp.tokenizer_parity_available(_sealed_attestation())
    assert parity["matches_sealed_attestation"] is True
    assert parity["probe_classes_match_sealed_attestation"] is True
    assert parity["attested_battery_digest"] == parity["battery_digest"]


def test_a_battery_that_no_longer_matches_the_sealed_pin_is_refused() -> None:
    """Red: the mutation that used to survive. Change the frozen battery and
    the gate must stop agreeing with the pin it was resolved on."""
    attestation = dict(_sealed_attestation())
    attestation["battery_digest"] = "sha256:" + "0" * 64
    parity = gsp.tokenizer_parity_available(attestation)
    assert parity["deterministic"] is True  # still pure, still useless alone
    assert parity["matches_sealed_attestation"] is False


def test_a_probe_class_dropped_from_the_battery_is_refused() -> None:
    attestation = dict(_sealed_attestation())
    attestation["probe_classes"] = list(attestation["probe_classes"])[:-1]
    parity = gsp.tokenizer_parity_available(attestation)
    assert parity["probe_classes_match_sealed_attestation"] is False


def test_an_unattested_battery_is_a_block_not_a_pass() -> None:
    """Two calls to a pure function agreeing is not a frozen contract."""
    parity = gsp.tokenizer_parity_available(None)
    assert parity["deterministic"] is True
    assert parity["matches_sealed_attestation"] is False
    assert "not a frozen contract" in parity["why"]


def test_the_context_budget_is_bound_to_the_materializers_own_declaration() -> None:
    budget = gsp.context_budget_feasible()
    assert budget["budget_matches_materializer"] is True
    assert budget["materializer_budget_tokens"] == gsp.CONTEXT_BUDGET_TOKENS
    assert budget["feasible"] is True


def test_a_materializer_budget_that_drifts_reddens_the_budget_gate(monkeypatch) -> None:
    """Red: the mutation that used to survive. The preflight restates
    `context_builder.TOTAL_PROMPT_TOKENS`; a restatement nobody compares is a
    constant compared with itself."""
    import context_builder

    monkeypatch.setattr(context_builder, "TOTAL_PROMPT_TOKENS", 1024)
    budget = gsp.context_budget_feasible()
    assert budget["materializer_budget_tokens"] == 1024
    assert budget["budget_matches_materializer"] is False
    assert budget["feasible"] is False


def test_the_preflight_imports_nothing_that_could_spend() -> None:
    """Green: the real module, read from its own AST."""
    scan = gsp.no_gpu_and_no_network()
    assert scan["parsed"] is True
    assert scan["offending_imports"] == []
    assert scan["clean"] is True
    assert scan["gpu_seconds"] == 0
    assert scan["estimated_cost_usd"] == 0.0


def test_a_preflight_that_grew_a_network_client_is_refused(tmp_path: Path) -> None:
    """Red: the mutation that used to survive. `G_GSP_NO_GPU_YET` was a
    hardcoded True, so `import urllib.request` in this module changed nothing
    anywhere -- while INC-V2-104 B's decision to move the live-cohort guard off
    `run()` rests entirely on that import not being there."""
    grown = tmp_path / "grown.py"
    grown.write_text(
        "import json\nimport urllib.request\nfrom socket import socket\n",
        encoding="utf-8",
    )
    scan = gsp.no_gpu_and_no_network(grown)
    assert scan["clean"] is False
    assert scan["offending_imports"] == ["socket", "urllib.request"]
    assert "CPU-only" in scan["why"]


def test_the_docstrings_words_are_not_mistaken_for_imports(tmp_path: Path) -> None:
    """AST, not grep. The real module's docstring discusses sockets and HTTP
    clients in prose; a textual check would be red for the wrong reason, and a
    guard that is red for the wrong reason stops being read."""
    prose_only = tmp_path / "prose.py"
    prose_only.write_text(
        '"""This module opens no socket and imports no HTTP client, not requests."""\n'
        "import json\n",
        encoding="utf-8",
    )
    assert gsp.no_gpu_and_no_network(prose_only)["clean"] is True
