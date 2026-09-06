"""Tests for `protocols/GPU_SUCCESSOR_MODEL_PIN_V1.yaml` and
`tools/resolve_gpu_successor_pin.py`.

No network, no GPU, no model load. Covers:

1. a "latest" revision is refused
2. a short/malformed revision is refused
3. a mismatched tokenizer sha against MODEL_ENDPOINT_V1 is refused
4. a floating image tag is refused
5. `capability_evidence` equal to the repository name yields
   `capability_claimed: False` (via the preflight's own
   `capability_from_registry`, not a copy of its logic)
6. the resolved dict makes `model_identity_pin(...)["pinned_by_exact_revision"]`
   true
7. the parity battery digest is deterministic across two calls
8. the real pin file on disk resolves cleanly end to end
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS / "endpoint"))

import gpu_successor_preflight as gsp  # noqa: E402
import resolve_gpu_successor_pin as rgp  # noqa: E402

PIN_PATH = NS / "protocols" / "GPU_SUCCESSOR_MODEL_PIN_V1.yaml"
MODEL_ENDPOINT_PATH = NS / "protocols" / "MODEL_ENDPOINT_V1.yaml"


def _load_real_pin() -> dict[str, Any]:
    return yaml.safe_load(PIN_PATH.read_text(encoding="utf-8"))


def _load_real_model_endpoint() -> dict[str, Any]:
    return yaml.safe_load(MODEL_ENDPOINT_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 0. fixtures live entirely in memory — the frozen protocol files are read,
#    never written to
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_pin() -> dict[str, Any]:
    return copy.deepcopy(_load_real_pin())


@pytest.fixture
def model_endpoint() -> dict[str, Any]:
    return copy.deepcopy(_load_real_model_endpoint())


# ---------------------------------------------------------------------------
# 1. files exist and parse
# ---------------------------------------------------------------------------


def test_pin_file_exists_and_parses() -> None:
    assert PIN_PATH.exists()
    body = _load_real_pin()
    assert isinstance(body, dict)
    assert body["protocol_id"] == "GPU_SUCCESSOR_MODEL_PIN_V1"


# ---------------------------------------------------------------------------
# 2. revision refusals
# ---------------------------------------------------------------------------


def test_latest_revision_is_refused(valid_pin: dict[str, Any]) -> None:
    valid_pin["model"]["revision"] = "latest"
    with pytest.raises(rgp.PinValidationError, match="latest"):
        rgp.validate_shapes(valid_pin)


def test_short_malformed_revision_is_refused(valid_pin: dict[str, Any]) -> None:
    valid_pin["model"]["revision"] = "6a9e13b"  # short, not 40 hex
    with pytest.raises(rgp.PinValidationError, match="40 hex"):
        rgp.validate_shapes(valid_pin)


def test_non_hex_revision_is_refused(valid_pin: dict[str, Any]) -> None:
    valid_pin["model"]["revision"] = "z" * 40  # right length, not hex
    with pytest.raises(rgp.PinValidationError, match="40 hex"):
        rgp.validate_shapes(valid_pin)


def test_valid_revision_passes_shape_check(valid_pin: dict[str, Any]) -> None:
    shapes = rgp.validate_shapes(valid_pin)
    assert shapes["revision_is_40_hex"] is True
    assert shapes["revision_not_latest"] is True


# ---------------------------------------------------------------------------
# 3. tokenizer sha shape and cross-check refusals
# ---------------------------------------------------------------------------


def test_malformed_tokenizer_sha_is_refused(valid_pin: dict[str, Any]) -> None:
    valid_pin["model"]["tokenizer_file_sha256"] = "not-a-sha"
    with pytest.raises(rgp.PinValidationError, match="sha256"):
        rgp.validate_shapes(valid_pin)


def test_mismatched_tokenizer_sha_against_model_endpoint_is_refused(
    valid_pin: dict[str, Any], model_endpoint: dict[str, Any]
) -> None:
    # well-formed shape, but a different value than MODEL_ENDPOINT_V1 attests
    valid_pin["model"]["tokenizer_file_sha256"] = "sha256:" + "0" * 64
    rgp.validate_shapes(valid_pin)  # shape is fine on its own
    with pytest.raises(rgp.PinValidationError, match="tokenizer_file_sha256"):
        rgp.cross_check_against_model_endpoint(valid_pin, model_endpoint)


def test_mismatched_revision_against_model_endpoint_is_refused(
    valid_pin: dict[str, Any], model_endpoint: dict[str, Any]
) -> None:
    valid_pin["model"]["revision"] = "1" * 40
    rgp.validate_shapes(valid_pin)
    with pytest.raises(rgp.PinValidationError, match="revision"):
        rgp.cross_check_against_model_endpoint(valid_pin, model_endpoint)


# ---------------------------------------------------------------------------
# 4. runtime image digest
# ---------------------------------------------------------------------------


def test_floating_image_tag_is_refused(valid_pin: dict[str, Any]) -> None:
    valid_pin["runtime_image_digest"] = "runpod/pytorch:latest"
    with pytest.raises(rgp.PinValidationError, match="runtime_image_digest"):
        rgp.validate_shapes(valid_pin)


def test_valid_image_digest_matches_preflight_pattern(valid_pin: dict[str, Any]) -> None:
    digest = valid_pin["runtime_image_digest"]
    assert gsp.RUNTIME_IMAGE_DIGEST_PATTERN.match(digest)


def test_mismatched_image_digest_against_model_endpoint_is_refused(
    valid_pin: dict[str, Any], model_endpoint: dict[str, Any]
) -> None:
    valid_pin["runtime_image_digest"] = "runpod/pytorch@sha256:" + "9" * 64
    rgp.validate_shapes(valid_pin)
    with pytest.raises(rgp.PinValidationError, match="runtime_image_digest"):
        rgp.cross_check_against_model_endpoint(valid_pin, model_endpoint)


# ---------------------------------------------------------------------------
# 5. capability evidence — a name is not a capability
# ---------------------------------------------------------------------------


def test_capability_evidence_equal_to_repository_name_is_not_claimed() -> None:
    pin = {"repository": "Qwen/Qwen3.6-27B", "capability_evidence": "Qwen/Qwen3.6-27B"}
    result = gsp.capability_from_registry(pin)
    assert result["capability_claimed"] is False


def test_capability_evidence_absent_is_not_claimed() -> None:
    pin = {"repository": "Qwen/Qwen3.6-27B", "capability_evidence": None}
    result = gsp.capability_from_registry(pin)
    assert result["capability_claimed"] is False


def test_real_pin_capability_evidence_is_distinct_from_repository_name(
    valid_pin: dict[str, Any],
) -> None:
    resolved = rgp.resolved_pin_dict(valid_pin)
    assert resolved["capability_evidence"] != resolved["repository"]
    result = gsp.capability_from_registry(resolved)
    # the real pin declares genuine evidence (a config.json digest + field),
    # so this is expected to be claimed, unlike the two refusal cases above
    assert result["capability_claimed"] is True
    assert result["inferred_from_name"] is False


# ---------------------------------------------------------------------------
# 5b. G_GSP_CAPABILITY_NOT_INFERRED_FROM_NAME must have a reachable red state
#
# INC-V2-036 class. The gate was
#     not capability_claimed or capability.get("inferred_from_name") is False
# and `capability_from_registry` sets `inferred_from_name: False` on every path
# that can reach the second disjunct -- so the gate re-stated the branch that
# had just been taken and could not go red for ANY input. A probe of eleven
# pins, including `capability_evidence: "trust me"`, produced eleven greens.
#
# These are controls, not coverage: each one fails if the fix is reverted.
# ---------------------------------------------------------------------------

#: Pointers that differ from the repository string -- so the old gate passed
#: them -- but assert a capability instead of grounding it in an artifact.
UNGROUNDED_CAPABILITY_POINTERS = (
    "trust me",
    "Qwen3.6 supports vision",
    "it is obviously a VLM",
    "see the model card",
    # a digest of the wrong length is not a content address either
    "config.json#sha256=69db4eb7196bc8190813231b3018ca05",
)


@pytest.mark.parametrize("pointer", UNGROUNDED_CAPABILITY_POINTERS)
def test_capability_gate_is_red_for_an_ungrounded_claim(pointer: str) -> None:
    """The red state the old gate did not have."""
    capability = gsp.capability_from_registry(
        {"repository": "Qwen/Qwen3.6-27B", "capability_evidence": pointer}
    )
    assert capability["capability_claimed"] is True
    assert capability["evidence_is_content_addressed"] is False
    assert gsp.capability_not_inferred_from_name(capability) is False


def test_capability_gate_is_green_when_no_capability_is_claimed() -> None:
    """Absence of a claim stays legal -- the fix must not turn "no capability"
    into a block, or it would have moved the defect rather than closed it."""
    capability = gsp.capability_from_registry(
        {"repository": "Qwen/Qwen3.6-27B", "capability_evidence": None}
    )
    assert capability["capability_claimed"] is False
    assert gsp.capability_not_inferred_from_name(capability) is True


def test_capability_gate_is_green_for_the_real_content_addressed_pin(
    valid_pin: dict[str, Any],
) -> None:
    """The live pin must still pass -- a gate that reddens the real path is a
    regression, not a hardening."""
    resolved = rgp.resolved_pin_dict(valid_pin)
    capability = gsp.capability_from_registry(resolved)
    assert capability["evidence_is_content_addressed"] is True
    assert len(capability["evidence_digest"]) == 64
    assert gsp.capability_not_inferred_from_name(capability) is True


def test_capability_gate_predicate_is_not_a_tautology() -> None:
    """Directly asserts what the defect was: over a spread of pins the gate
    must produce BOTH verdicts. If it ever yields one value for every input,
    it is watching nothing again."""
    pins = [
        {"repository": "Qwen/Qwen3.6-27B"},
        {"repository": "Qwen/Qwen3.6-27B", "capability_evidence": "Qwen/Qwen3.6-27B"},
        {"repository": "Qwen/Qwen3.6-27B", "capability_evidence": "trust me"},
        {"repository": "Qwen/Qwen3.6-27B", "capability_evidence": {"claim": "vision"}},
        {"repository": "Qwen/Qwen3.6-27B", "capability_evidence": "attest.json#" + "a1" * 32},
    ]
    verdicts = {
        gsp.capability_not_inferred_from_name(gsp.capability_from_registry(pin)) for pin in pins
    }
    assert verdicts == {True, False}


# ---------------------------------------------------------------------------
# 6. resolved dict shape matches what model_identity_pin expects
# ---------------------------------------------------------------------------


def test_resolved_pin_makes_model_identity_pin_pinned_by_exact_revision(
    valid_pin: dict[str, Any],
) -> None:
    resolved = rgp.resolved_pin_dict(valid_pin)
    identity = gsp.model_identity_pin(resolved)
    assert identity["pinned_by_exact_revision"] is True
    assert identity["not_resolved_to_latest"] is True


def test_resolved_pin_with_latest_revision_is_not_pinned() -> None:
    resolved = {
        "repository": "Qwen/Qwen3.6-27B",
        "revision": "latest",
        "tokenizer_file_sha256": "sha256:" + "a" * 64,
        "capability_evidence": None,
    }
    identity = gsp.model_identity_pin(resolved)
    assert identity["pinned_by_exact_revision"] is False


# ---------------------------------------------------------------------------
# 7. tokenizer parity battery digest — deterministic, CPU only
# ---------------------------------------------------------------------------


def test_parity_battery_digest_is_deterministic_across_two_calls() -> None:
    report = rgp.tokenizer_parity_report()
    assert report["deterministic"] is True
    again = rgp.tokenizer_parity_report()
    assert report["battery_digest"] == again["battery_digest"]
    assert report["live_tokenizer_parity"] != "PASS"


# ---------------------------------------------------------------------------
# 8. the real pin resolves end to end without raising
# ---------------------------------------------------------------------------


def test_real_pin_resolves_end_to_end() -> None:
    body = rgp.resolve(PIN_PATH, MODEL_ENDPOINT_PATH)
    assert body["cross_check_against_model_endpoint"]["all_match"] is True
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0
    resolved = body["resolved_pin"]
    identity = gsp.model_identity_pin(resolved)
    assert identity["pinned_by_exact_revision"] is True


def test_closed_endpoint_not_revived() -> None:
    """The pin's own closed-endpoint-relationship section must say this is not
    a revival, and the preflight's structural gate must independently agree —
    two different mechanisms checking the same fact."""
    body = _load_real_pin()
    relationship = body["closed_endpoint_relationship"]
    assert relationship["closed_by"] == "STOP-V2-005"
    assert "arms" in relationship["not_reused_from_closed_endpoint"]
    assert "scorer_classes" in relationship["not_reused_from_closed_endpoint"]

    exclusion = gsp.design_excludes_closed_endpoint()
    assert exclusion["clean"] is True


# --- INC-V2-104 B: the guard sits where the harm is --------------------------


def test_main_still_refuses_under_a_test_runner():
    """`main()` seals an immutable receipt and moves a `receipts/latest`
    pointer. A stray call from a test runner writes real evidence, which is the
    harm INC-V2-100 is about, so the guard must still fire here."""
    import live_cohort_guard

    with pytest.raises(
        live_cohort_guard.LiveCohortRefused, match=re.escape("gpu_successor_preflight.main")
    ):
        gsp.main()


def test_run_is_reachable_from_a_test_and_causes_nothing(tmp_path):
    """The other half, and the reason the guard moved. `run()` opens no socket,
    imports no HTTP client and writes nothing -- guarding it protected against
    nothing while making the gate-assembly block untestable, which is how a gate
    that was true for every input survived review."""
    receipts_before = sorted((NS / "receipts").glob("gpu-successor-preflight--*.json"))
    result = gsp.run(
        manifest=tmp_path / "absent.json",
        model_pin={},
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
    )
    assert result["verdict"] == "BLOCKED"
    assert sorted((NS / "receipts").glob("gpu-successor-preflight--*.json")) == receipts_before
