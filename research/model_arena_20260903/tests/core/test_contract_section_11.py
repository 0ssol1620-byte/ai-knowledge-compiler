"""The integration-pass decisions of ARENA_CONTRACT section 11.

D3 semantic error classes, D4 extension-open records, D5 runtime and registry
widening, D8 byte-exact hashing. Each test states the decision it defends so a
later reader can tell a deliberate contract from an accident.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from arena.constants import WORKER_STATES
from arena.core.ids import sha256_file, sha256_hex, sha256_ref
from arena.core.receipts import (
    SEMANTIC_ERROR_CLASSES,
    BundlePublishReceipt,
    CanaryReceipt,
    HeartbeatReport,
    ModelRegistryRecord,
    PageReceipt,
    ProvisionGateReceipt,
    RuntimeSpec,
    SchemaValidationError,
    WorkerRunResponse,
    load_schema,
    record_sha256,
    validate,
    write_atomic_json,
)
from examples import example

# --------------------------------------------------------------------------
# D3 - semantic error class
# --------------------------------------------------------------------------


def test_the_semantic_error_classes_are_the_four_the_contract_names() -> None:
    assert SEMANTIC_ERROR_CLASSES == (
        "OUTPUT_EMPTY",
        "OUTPUT_TRUNCATED",
        "OUTPUT_REPETITION",
        "OUTPUT_MALFORMED",
    )


@pytest.mark.parametrize("value", SEMANTIC_ERROR_CLASSES)
def test_a_success_page_receipt_may_carry_a_semantic_error_class(value: str) -> None:
    """D3/masterplan 41: an empty output is SUCCESS plus OUTPUT_EMPTY.

    The model was wrong; the run was not. Turning that into FAILED would hide
    a produced output behind an operational failure.
    """

    record = dict(example("page-receipt"), semantic_error_class=value)
    validate(record, "page-receipt")
    parsed = PageReceipt.model_validate(record)
    assert parsed.status == "SUCCESS"
    assert parsed.error_class is None
    assert parsed.semantic_error_class == value


@pytest.mark.parametrize("value", SEMANTIC_ERROR_CLASSES)
def test_a_run_response_carries_the_same_semantic_error_class(value: str) -> None:
    record = dict(example("worker-run-response"), semantic_error_class=value)
    validate(record, "worker-run-response")
    assert WorkerRunResponse.model_validate(record).semantic_error_class == value


@pytest.mark.parametrize(
    ("name", "model"),
    [("page-receipt", PageReceipt), ("worker-run-response", WorkerRunResponse)],
)
def test_an_unknown_semantic_error_class_is_refused(name: str, model: type[Any]) -> None:
    record = dict(example(name), semantic_error_class="OUTPUT_UGLY")
    with pytest.raises(SchemaValidationError):
        validate(record, name)
    with pytest.raises(ValueError, match="semantic_error_class"):
        model.model_validate(record)


def test_semantic_error_class_defaults_to_null_not_absent() -> None:
    parsed = PageReceipt.model_validate(example("page-receipt"))
    assert parsed.semantic_error_class is None
    assert parsed.recovery_job_id is None
    assert parsed.to_record()["semantic_error_class"] is None
    assert parsed.to_record()["recovery_job_id"] is None


def test_a_recovery_receipt_names_the_recovery_job_it_came_from() -> None:
    recovery_id = "0a" * 32
    record = dict(example("page-receipt"), job_kind="recovery", recovery_job_id=recovery_id)
    validate(record, "page-receipt")
    assert PageReceipt.model_validate(record).recovery_job_id == recovery_id


# --------------------------------------------------------------------------
# D4 - extension-open records
# --------------------------------------------------------------------------

EXTENSION_OPEN = ("page-receipt", "heartbeat", "model-registry-record", "evaluator-registry-record")


@pytest.mark.parametrize("name", EXTENSION_OPEN)
def test_the_schema_file_is_extension_open(name: str) -> None:
    assert load_schema(name)["additionalProperties"] is True


def test_an_opus_shaped_page_receipt_round_trips() -> None:
    """Lane D's real columns must survive a load/dump cycle unchanged."""

    record = dict(
        example("page-receipt"),
        runtime_mode="subscription",
        gpu_type=None,
        gpu_id=None,
        pod_id=None,
        peak_vram_mb=None,
        actual_marginal_api_cost="N/A",
        subscription_included_usage=True,
        api_equivalent_list_price_usd=0.00647,
        claude_session_id="9be6d701-cee8-4b36-bfb6-4208e78079a0",
    )
    validate(record, "page-receipt")
    assert PageReceipt.model_validate(record).to_record() == record


def test_a_heartbeat_state_is_a_worker_state() -> None:
    """D4: 'state' is WORKER_STATES, not a second coarse vocabulary."""

    assert set(load_schema("heartbeat")["properties"]["state"]["enum"]) == set(WORKER_STATES)
    for state in WORKER_STATES:
        record = dict(example("heartbeat"), state=state, stage=state)
        validate(record, "heartbeat")
        assert HeartbeatReport.model_validate(record).state == state


def test_the_old_coarse_heartbeat_state_is_gone() -> None:
    with pytest.raises(SchemaValidationError):
        validate(dict(example("heartbeat"), state="LOADING"), "heartbeat")


def test_a_heartbeat_without_gpu_metrics_must_say_why() -> None:
    """No silent zero: an unread gauge is null with a reason, never 0."""

    blind = dict(
        example("heartbeat"),
        gpu_util=None,
        vram_used=None,
        gpu_metrics_unavailable_reason="nvidia-smi is not present in this image",
    )
    validate(blind, "heartbeat")
    assert HeartbeatReport.model_validate(blind).gpu_util is None

    silent = dict(example("heartbeat"), gpu_util=None, vram_used=None)
    silent["gpu_metrics_unavailable_reason"] = None
    with pytest.raises(SchemaValidationError):
        validate(silent, "heartbeat")
    with pytest.raises(ValueError, match="gpu_metrics_unavailable_reason"):
        HeartbeatReport.model_validate(silent)


def test_a_heartbeat_may_carry_its_own_timestamp() -> None:
    record = dict(example("heartbeat"))
    record["ts"] = "2026-09-03T12:00:05.500Z"
    validate(record, "heartbeat")
    assert HeartbeatReport.model_validate(record).ts == "2026-09-03T12:00:05.500Z"
    with pytest.raises(SchemaValidationError):
        validate(dict(record, ts="2026-09-03 12:00:05"), "heartbeat")


# --------------------------------------------------------------------------
# D5 - runtime.json and the model registry
# --------------------------------------------------------------------------


def test_a_runtime_base_image_must_be_digest_pinned() -> None:
    floating = dict(example("runtime"), base_image="vllm/vllm-openai:v0.21.0")
    with pytest.raises(SchemaValidationError):
        validate(floating, "runtime")
    with pytest.raises(ValueError, match="base_image"):
        RuntimeSpec.model_validate(floating)


def test_a_name_tag_digest_base_image_is_accepted() -> None:
    pinned = dict(
        example("runtime"),
        base_image="vllm/vllm-openai:v0.21.0@sha256:" + "a2" * 32,
    )
    validate(pinned, "runtime")
    assert RuntimeSpec.model_validate(pinned).base_image.endswith("a2" * 32)


def test_runtime_notes_may_be_a_string_or_a_list() -> None:
    as_list = dict(example("runtime"), notes=["first note", "second note"])
    validate(as_list, "runtime")
    assert RuntimeSpec.model_validate(as_list).notes == ["first note", "second note"]
    as_string = dict(example("runtime"), notes="one note")
    validate(as_string, "runtime")
    assert RuntimeSpec.model_validate(as_string).notes == "one note"


def test_gpu_count_min_defaults_to_one_and_refuses_zero() -> None:
    absent = dict(example("runtime"))
    absent.pop("gpu_count_min")
    validate(absent, "runtime")
    assert RuntimeSpec.model_validate(absent).gpu_count_min == 1
    two = dict(example("runtime"), gpu_count_min=2)
    validate(two, "runtime")
    assert RuntimeSpec.model_validate(two).gpu_count_min == 2
    with pytest.raises(SchemaValidationError):
        validate(dict(example("runtime"), gpu_count_min=0), "runtime")


@pytest.mark.parametrize(
    "status",
    [
        "verified",
        "approved",
        "unverified",
        "review_required",
        "blocked",
        "none_found",
        "not_reusable",
    ],
)
def test_every_license_status_in_use_is_accepted(status: str) -> None:
    record = example("runtime")
    record["license"] = dict(record["license"], status=status)
    validate(record, "runtime")
    assert RuntimeSpec.model_validate(record).license.status == status


def test_an_invented_license_status_is_refused() -> None:
    record = example("runtime")
    record["license"] = dict(record["license"], status="probably_fine")
    with pytest.raises(SchemaValidationError):
        validate(record, "runtime")


@pytest.mark.parametrize("field", ["repo", "runtime_version", "gpu_min_vram_gb"])
def test_a_registry_record_may_report_a_field_as_null(field: str) -> None:
    """D5: the subscription lane has no weights repo; null, never a placeholder."""

    record = dict(example("model-registry-record"))
    record[field] = None
    validate(record, "model-registry-record")
    assert getattr(ModelRegistryRecord.model_validate(record), field) is None


@pytest.mark.parametrize("field", ["repo", "runtime_version", "gpu_min_vram_gb"])
def test_a_nullable_registry_field_is_still_required_to_be_present(field: str) -> None:
    record = dict(example("model-registry-record"))
    record.pop(field)
    with pytest.raises(SchemaValidationError):
        validate(record, "model-registry-record")


@pytest.mark.parametrize("runtime_type", ["paddle", "pipeline", "mineru_cli", "custom"])
def test_the_registry_runtime_types_cover_the_non_vllm_runtimes(runtime_type: str) -> None:
    record = dict(example("model-registry-record"), runtime_type=runtime_type)
    validate(record, "model-registry-record")
    assert ModelRegistryRecord.model_validate(record).runtime_type == runtime_type


def test_a_registry_record_may_pin_a_multi_gpu_minimum() -> None:
    record = dict(example("model-registry-record"), gpu_count_min=2)
    validate(record, "model-registry-record")
    assert ModelRegistryRecord.model_validate(record).gpu_count_min == 2


# --------------------------------------------------------------------------
# D8 - byte-exact hashing
# --------------------------------------------------------------------------

# A page whose markdown carries non-ASCII and ends with a newline: the two
# things that make a "hash of the text" and a "hash of the file" disagree.
MARKDOWN = "# 표 1 — Résumé\n\n| 항목 | 값 |\n| --- | --- |\n| Δt | 12,50 € |\n"


def test_canonical_markdown_hashes_identically_to_its_written_bytes(tmp_path: Path) -> None:
    """D8: canonical_output_sha256 == sha256(markdown.encode('utf-8')).

    The frozen file holds exactly those bytes: UTF-8, no BOM, nothing added.
    E1 and E2 hash the file and compare, so the two must never diverge.
    """

    expected = sha256_ref(MARKDOWN.encode("utf-8"))
    path = tmp_path / "case.md"
    path.write_bytes(MARKDOWN.encode("utf-8"))

    assert sha256_file(path) == expected
    assert sha256_ref(MARKDOWN) == expected
    assert sha256_hex(MARKDOWN) == hashlib.sha256(MARKDOWN.encode("utf-8")).hexdigest()

    on_disk = path.read_bytes()
    assert not on_disk.startswith(b"\xef\xbb\xbf"), "no BOM"
    assert on_disk.endswith(b"\n") and not on_disk.endswith(b"\r\n"), "no CRLF translation"
    assert len(on_disk) > len(MARKDOWN), "non-ASCII really is multi-byte here"


def test_raw_text_hashes_the_same_way(tmp_path: Path) -> None:
    raw = "Ω raw model output, verbatim, trailing newline kept\n"
    path = tmp_path / "case.raw.txt"
    path.write_bytes(raw.encode("utf-8"))
    assert sha256_file(path) == sha256_ref(raw.encode("utf-8")) == sha256_ref(raw)


def test_a_written_record_hash_matches_the_precomputed_one(tmp_path: Path) -> None:
    record = dict(example("page-receipt"), semantic_error_class="OUTPUT_TRUNCATED")
    target = tmp_path / "receipt.json"
    written = write_atomic_json(target, record)
    assert written == record_sha256(record)
    assert written == sha256_file(target)


# --------------------------------------------------------------------------
# 11.5 D26 - the canary receipt records who ran, on what, under whose
# authorization; and 11.5 D21 - the bundle publication receipt
# --------------------------------------------------------------------------


def test_the_canary_receipt_is_extension_open() -> None:
    """D26: lane B1 adds driver detail without a schema round-trip."""

    assert load_schema("canary-receipt")["additionalProperties"] is True
    record = dict(example("canary-receipt"), readiness_wait_seconds=412.5)
    validate(record, "canary-receipt")
    assert CanaryReceipt.model_validate(record).to_record() == record


@pytest.mark.parametrize(
    "field",
    [
        "base_image",
        "gpu_compute_capability",
        "pod_id",
        "authorization_receipt_path",
        "authorization_receipt_sha256",
        "pod_ledger_path",
    ],
)
def test_the_canary_receipt_carries_the_provenance_of_the_run(field: str) -> None:
    """D26/D28: a canary that ran on a pod says which pod, and under what."""

    record = example("canary-receipt")
    assert field in load_schema("canary-receipt")["properties"]
    assert record[field] is not None
    parsed = CanaryReceipt.model_validate(record)
    assert getattr(parsed, field) == record[field]


def test_the_canary_receipt_keeps_the_core_keys_required() -> None:
    """Extension-open widens what may be added, never what may be dropped."""

    required = set(load_schema("canary-receipt")["required"])
    assert {"campaign_id", "model_key", "criteria", "status", "started_at"} <= required
    for name in sorted(required):
        broken = example("canary-receipt")
        broken.pop(name, None)
        with pytest.raises(SchemaValidationError):
            validate(broken, "canary-receipt")


def test_a_subscription_canary_has_no_pod_and_says_so() -> None:
    """A null here means "there was none", never "not recorded"."""

    record = dict(
        example("canary-receipt"),
        runtime_mode="subscription",
        runtime_image_digest="subscription:claude-code-2.1.228-claude-opus-5",
        base_image=None,
        gpu_compute_capability=None,
        pod_id=None,
        pod_ledger_path=None,
    )
    validate(record, "canary-receipt")
    assert CanaryReceipt.model_validate(record).to_record() == record


def test_an_empty_provenance_string_is_refused() -> None:
    """A blank pod id is not "no pod"; it is an unrecorded one."""

    with pytest.raises(SchemaValidationError):
        validate(dict(example("canary-receipt"), pod_id=""), "canary-receipt")
    with pytest.raises(SchemaValidationError):
        validate(
            dict(example("canary-receipt"), authorization_receipt_sha256="not-a-digest"),
            "canary-receipt",
        )


def test_the_provision_gate_receipt_the_controller_wrote_validates() -> None:
    """The real file on disk, not a fixture: D20's gate must be readable."""

    path = Path(__file__).resolve().parents[2] / "receipts" / "canary-provision-glm_ocr.json"
    if not path.is_file():  # pragma: no cover - the controller lane owns the file
        pytest.skip(f"{path} has not been written yet")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["schema"] == "tavonel.arena.provision_gate.v1"
    validate(record)
    parsed = ProvisionGateReceipt.model_validate(record)
    assert parsed.model_key == "glm_ocr"
    if parsed.phase != "phase1_canary":  # pragma: no cover - D85 incident
        pytest.skip(
            "this file was overwritten by a Full Run provisioning before D85 gave "
            "each phase its own path; the canary proof itself is in "
            "receipts/canary-glm_ocr.json, which was never on this path"
        )


def test_the_provision_gate_receipt_is_extension_open() -> None:
    record = dict(example("provision_gate"), watchdog={"lifetime_hours": 2})
    validate(record, "provision_gate")
    assert ProvisionGateReceipt.model_validate(record).to_record() == record


@pytest.mark.parametrize(
    "field",
    [
        "schema",
        "campaign_id",
        "model_key",
        "phase",
        "evaluated_at",
        "authorization",
        "provisioning",
    ],
)
def test_the_provision_gate_receipt_requires_its_core_blocks(field: str) -> None:
    record = example("provision_gate")
    record.pop(field, None)
    with pytest.raises(SchemaValidationError):
        validate(record, "provision_gate")


def test_the_bundle_publish_receipt_records_what_was_uploaded() -> None:
    """D21: sha256, size, file count, manifest sha256, bucket and key."""

    record = example("bundle-publish")
    validate(record)
    parsed = BundlePublishReceipt.model_validate(record)
    assert parsed.r2_bucket and parsed.r2_key
    assert parsed.bundle_size_bytes > 0
    assert parsed.bundle_file_count > 0
    assert parsed.to_record() == record


def test_the_bundle_publish_receipt_takes_either_sha256_spelling() -> None:
    """The on-pod 'sha256sum -c' line is bare hex; section 2 prefixes it."""

    bare = "9e" * 32
    for value in (bare, f"sha256:{bare}"):
        record = dict(example("bundle-publish"), bundle_sha256=value)
        validate(record, "bundle-publish")
        assert BundlePublishReceipt.model_validate(record).bundle_sha256 == value
    with pytest.raises(SchemaValidationError):
        validate(dict(example("bundle-publish"), bundle_sha256="9E" * 32), "bundle-publish")


def test_the_bundle_publish_receipt_carries_a_bucket_and_key_not_a_url() -> None:
    """D21: bundle URLs in receipts are reduced to bucket/key."""

    properties = set(load_schema("bundle-publish")["properties"])
    assert "r2_bucket" in properties and "r2_key" in properties
    assert not any("url" in name for name in properties)


@pytest.mark.parametrize("field", sorted(BundlePublishReceipt.model_fields))
def test_every_bundle_publish_field_is_required(field: str) -> None:
    """Nothing about a published bundle is optional: it was verified or it was not."""

    name = "schema" if field == "record_schema" else field
    assert name in load_schema("bundle-publish")["required"]
    record = example("bundle-publish")
    record.pop(name, None)
    with pytest.raises(SchemaValidationError):
        validate(record, "bundle-publish")


# --------------------------------------------------------------------------
# 11.5 D16 / D34 - runtime.json owns the runtime revision and the prompt kind
# --------------------------------------------------------------------------


def test_runtime_json_may_declare_its_own_repository_and_revision() -> None:
    """D16: runtime.json owns them; the model registry is the derived copy."""

    record = example("runtime")
    validate(record, "runtime")
    parsed = RuntimeSpec.model_validate(record)
    assert parsed.runtime_repository == "PaddlePaddle/PaddleOCR"
    assert parsed.runtime_revision == "b03f46425e8ff4442b268ce449e3eef758146cd4"

    without = dict(record)
    without.pop("runtime_repository")
    without.pop("runtime_revision")
    validate(without, "runtime")
    assert RuntimeSpec.model_validate(without).runtime_repository is None


@pytest.mark.parametrize("kind", ["text", "toolkit", "none"])
def test_runtime_json_declares_one_of_the_three_prompt_kinds(kind: str) -> None:
    record = dict(example("runtime"), prompt_kind=kind)
    validate(record, "runtime")
    assert RuntimeSpec.model_validate(record).prompt_kind == kind


def test_an_unknown_prompt_kind_is_refused() -> None:
    """D34 names three kinds; a fourth would be a rule the worker cannot enforce."""

    with pytest.raises(SchemaValidationError):
        validate(dict(example("runtime"), prompt_kind="official"), "runtime")


def test_a_runtime_without_a_prompt_kind_says_nothing_rather_than_defaulting() -> None:
    """Null is 'this runtime has not declared it', never a kind to act on."""

    record = dict(example("runtime"))
    record.pop("prompt_kind")
    validate(record, "runtime")
    assert RuntimeSpec.model_validate(record).prompt_kind is None
    assert "prompt_kind" not in load_schema("runtime")["required"]
