"""Secret-free guard, atomic writes, jsonl round trips and cross-field rules."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from arena.core.ids import sha256_ref
from arena.core.receipts import (
    CANARY_CRITERIA,
    CanaryReceipt,
    Event,
    ModelRegistryRecord,
    PageReceipt,
    ReceiptError,
    RuntimeSpec,
    SchemaValidationError,
    SecretMaterialError,
    WorkerRunResponse,
    append_jsonl,
    assert_secret_free,
    read_jsonl,
    record_sha256,
    utc_timestamp,
    validate,
    write_atomic_json,
)
from examples import example

# Obviously synthetic stand-ins. No real credential appears anywhere in this
# tree; these exist only to prove the guard fires on the right shapes.
FAKE_RUNPOD = "rpa_" + "A1" * 20
FAKE_HF = "hf_" + "B2" * 20
FAKE_OPENAI = "sk-proj-" + "C3" * 20
FAKE_GITHUB = "ghp_" + "D4" * 20
FAKE_SLACK = "xoxb-" + "1234567890" * 3
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"


# --------------------------------------------------------------------------
# secret-free guard
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"note": FAKE_RUNPOD},
        {"note": FAKE_HF},
        {"note": FAKE_OPENAI},
        {"note": FAKE_GITHUB},
        {"note": FAKE_SLACK},
        {"note": FAKE_AWS},
        {"headers": {"Authorization": "Bearer abc.def.ghi"}},
        {"note": "curl -H 'authorization: bearer abc123'"},
        {"bundle_url": "https://r2.example.com/o/b.tar?X-Amz-Signature=deadbeef"},
        {"env": {"ARENA_WORKER_TOKEN": "whatever"}},
        {"provider": {"api_key": "whatever"}},
        {"db": {"password": "whatever"}},
        {"nested": [{"secret_value": "whatever"}]},
        {FAKE_RUNPOD: "value in the key position"},
    ],
)
def test_assert_secret_free_rejects_credential_shaped_material(payload: dict[str, Any]) -> None:
    with pytest.raises(SecretMaterialError):
        assert_secret_free(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"source_sha256": "sha256:" + "a1" * 32},
        {"inference_job_id": "e5" * 32},
        {"usage": {"input_tokens": 1200, "output_tokens": 800}},
        {"provenance": {"tokenizer": "Qwen2TokenizerFast"}},
        {"weights_dir": "/workspace/arena/weights/hf_hub_cache_dir"},
        {"image_b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgAB"},
        {"bundle_url": "https://r2.example.com/tavonel-arena-20260903/worker-bundle.tar.gz"},
        {"task": "task-list rebuilt"},
        {"note": "risk-assessment completed"},
        {"max_tokens": 4096, "tokens": 10},
    ],
)
def test_assert_secret_free_does_not_reject_legitimate_campaign_values(
    payload: dict[str, Any],
) -> None:
    assert_secret_free(payload)


def test_assert_secret_free_walks_lists_and_nested_maps() -> None:
    assert_secret_free({"a": [{"b": [{"c": "clean"}]}]})
    with pytest.raises(SecretMaterialError):
        assert_secret_free({"a": [{"b": [{"c": FAKE_HF}]}]})


def test_assert_secret_free_refuses_a_non_json_value() -> None:
    with pytest.raises(ReceiptError):
        assert_secret_free({"when": object()})


def test_every_writer_runs_the_guard_before_touching_the_disk(tmp_path: Path) -> None:
    target = tmp_path / "leak.json"
    with pytest.raises(SecretMaterialError):
        write_atomic_json(target, {"note": FAKE_RUNPOD})
    assert not target.exists()
    assert not (tmp_path / "leak.json.tmp").exists()

    lines = tmp_path / "leak.jsonl"
    with pytest.raises(SecretMaterialError):
        append_jsonl(lines, {"note": FAKE_RUNPOD})
    assert not lines.exists()


# --------------------------------------------------------------------------
# atomic write
# --------------------------------------------------------------------------


def test_write_atomic_json_returns_the_digest_of_the_bytes_on_disk(tmp_path: Path) -> None:
    target = tmp_path / "runs" / "paddleocr_vl_1_6" / "receipts" / "case.json"
    digest = write_atomic_json(target, example("page-receipt"))
    assert digest == sha256_ref(target.read_bytes())
    assert not target.with_name(target.name + ".tmp").exists()
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "SUCCESS"


def test_write_atomic_json_is_canonical_and_stable(tmp_path: Path) -> None:
    record = example("frozen")
    first = write_atomic_json(tmp_path / "a.json", record)
    shuffled = dict(reversed(list(record.items())))
    second = write_atomic_json(tmp_path / "b.json", shuffled)
    assert first == second
    assert record_sha256(record) == first


def test_a_leftover_tmp_from_a_crash_is_ignored_and_then_replaced(tmp_path: Path) -> None:
    """A crash between write and rename leaves .tmp; the final file is untouched."""

    target = tmp_path / "receipt.json"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(b'{"half-written": ')

    digest = write_atomic_json(target, example("frozen"))
    assert target.is_file()
    assert not tmp.exists()
    assert json.loads(target.read_text(encoding="utf-8"))["sample_count"] == 5132
    assert digest.startswith("sha256:")


def test_write_atomic_json_overwrites_in_place(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    write_atomic_json(target, example("frozen"))
    updated = dict(example("frozen"), success_count=5000, failed_count=132)
    write_atomic_json(target, updated)
    assert json.loads(target.read_text(encoding="utf-8"))["success_count"] == 5000
    assert len(list(tmp_path.iterdir())) == 1


def test_write_atomic_json_validates_a_record_that_declares_a_schema(tmp_path: Path) -> None:
    broken = dict(example("frozen"))
    del broken["manifest_sha256"]
    with pytest.raises(SchemaValidationError):
        write_atomic_json(tmp_path / "bad.json", broken)
    assert not (tmp_path / "bad.json").exists()


def test_write_atomic_json_accepts_a_pydantic_model(tmp_path: Path) -> None:
    receipt = PageReceipt.model_validate(example("page-receipt"))
    digest = write_atomic_json(tmp_path / "r.json", receipt)
    assert digest == record_sha256(receipt)


# --------------------------------------------------------------------------
# jsonl
# --------------------------------------------------------------------------


def test_append_jsonl_round_trips_and_keeps_order(tmp_path: Path) -> None:
    target = tmp_path / "events.jsonl"
    first = Event.model_validate(example("event"))
    second = Event.model_validate(dict(example("event"), to_state="QUEUED"))
    append_jsonl(target, first)
    append_jsonl(target, second)
    rows = read_jsonl(target)
    assert [row["to_state"] for row in rows] == ["QUALIFIED", "QUEUED"]
    assert target.read_bytes().endswith(b"\n")
    assert b"\r\n" not in target.read_bytes()


def test_read_jsonl_skips_blank_lines_and_refuses_garbage(tmp_path: Path) -> None:
    target = tmp_path / "events.jsonl"
    append_jsonl(target, example("event"))
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n")
    assert len(read_jsonl(target)) == 1

    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("not json\n")
    with pytest.raises(ReceiptError):
        read_jsonl(target)


def test_read_jsonl_refuses_a_non_object_line(tmp_path: Path) -> None:
    target = tmp_path / "rows.jsonl"
    target.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ReceiptError):
        read_jsonl(target)


# --------------------------------------------------------------------------
# validate()
# --------------------------------------------------------------------------


def test_validate_refuses_a_record_that_declares_no_schema() -> None:
    with pytest.raises(ReceiptError, match="declares no 'schema'"):
        validate({"anything": 1})


def test_validate_refuses_an_unknown_schema_id() -> None:
    with pytest.raises(ReceiptError, match="unknown schema id"):
        validate({"schema": "tavonel.arena.not-a-record.v1"})


def test_validate_accepts_an_explicit_schema_name_for_a_config_file() -> None:
    spec = dict(example("runtime"))
    del spec["schema"]
    validate(spec, "runtime")


# --------------------------------------------------------------------------
# cross-field rules that keep a record honest
# --------------------------------------------------------------------------


def test_a_success_page_receipt_must_carry_both_output_hashes() -> None:
    broken = dict(example("page-receipt"), raw_output_sha256=None)
    with pytest.raises(ValueError, match="both output hashes"):
        PageReceipt.model_validate(broken)
    with pytest.raises(SchemaValidationError):
        validate(broken)


def test_a_failed_page_receipt_must_name_an_error_class() -> None:
    broken = dict(
        example("page-receipt"),
        status="FAILED",
        error_class=None,
        raw_output_sha256=None,
        canonical_output_sha256=None,
        raw_output_path=None,
        canonical_output_path=None,
    )
    with pytest.raises(ValueError, match="must carry an error_class"):
        PageReceipt.model_validate(broken)


def test_a_gpu_page_receipt_must_name_its_pod_and_gpu() -> None:
    broken = dict(example("page-receipt"), pod_id=None)
    with pytest.raises(ValueError, match="pod_id"):
        PageReceipt.model_validate(broken)


def test_a_subscription_page_receipt_needs_no_pod() -> None:
    receipt = PageReceipt.model_validate(
        dict(
            example("page-receipt"),
            model_key="opus5_subscription",
            runtime_mode="subscription",
            runtime_image_digest="claude-code-2.1.252",
            pod_id=None,
            gpu_type=None,
            gpu_id=None,
            peak_vram_mb=None,
        )
    )
    assert receipt.peak_vram_mb is None
    validate(receipt.to_record())


def test_unknown_fields_are_rejected_rather_than_ignored() -> None:
    """A closed record still refuses what it does not know.

    The page receipt itself is extension-open since ARENA_CONTRACT 11.1 D4
    (the Opus lane adds subscription columns), so the closed case is shown by
    a record that no other lane extends.
    """

    with pytest.raises(ValueError, match="extra_field"):
        Event.model_validate(dict(example("event"), extra_field=1))
    with pytest.raises(SchemaValidationError):
        validate(dict(example("event"), extra_field=1))


def test_an_extension_open_page_receipt_keeps_the_extra_column() -> None:
    record = dict(example("page-receipt"), subscription_included_usage=True)
    parsed = PageReceipt.model_validate(record)
    validate(record)
    assert parsed.to_record()["subscription_included_usage"] is True


def test_the_schema_field_is_injected_but_still_required_on_disk() -> None:
    payload = dict(example("event"))
    del payload["schema"]
    assert Event.model_validate(payload).to_record()["schema"] == "tavonel.arena.event.v1"
    with pytest.raises(SchemaValidationError):
        validate(payload, "event")


def test_a_pass_canary_cannot_hide_a_missing_projection() -> None:
    broken = dict(example("canary-receipt"), gpu_hours_projected=None)
    with pytest.raises(ValueError, match="section 18 projection"):
        CanaryReceipt.model_validate(broken)
    with pytest.raises(SchemaValidationError):
        validate(broken)


def test_a_pass_canary_cannot_carry_a_failed_criterion() -> None:
    criteria = [
        {"criterion": name, "passed": name != "vram_headroom", "detail": "measured"}
        for name in CANARY_CRITERIA
    ]
    broken = dict(example("canary-receipt"), criteria=criteria)
    with pytest.raises(ValueError, match="failed criteria"):
        CanaryReceipt.model_validate(broken)


def test_a_fail_canary_must_state_a_reason() -> None:
    broken = dict(example("canary-receipt"), status="FAIL", fail_reasons=[])
    with pytest.raises(ValueError, match="at least one reason"):
        CanaryReceipt.model_validate(broken)
    with pytest.raises(SchemaValidationError):
        validate(broken)


def test_a_canary_receipt_must_carry_every_masterplan_17_criterion() -> None:
    broken = dict(example("canary-receipt"), criteria=[])
    with pytest.raises(ValueError, match="missing criteria"):
        CanaryReceipt.model_validate(broken)


def test_a_subscription_canary_may_omit_gpu_and_pod() -> None:
    """11.6 D37: the hosted lane has no GPU and no pod, and says so with null."""

    receipt = CanaryReceipt.model_validate(
        dict(
            example("canary-receipt"),
            model_key="opus5_subscription",
            runtime_mode="subscription",
            runtime_image_digest="subscription:claude-code-2.1.252-claude-opus-5",
            gpu_type=None,
            pod_id=None,
        )
    )
    assert receipt.gpu_type is None
    validate(receipt.to_record())


def test_a_gpu_canary_must_name_its_gpu_and_pod() -> None:
    """11.6 D37: nullable only for subscription - a GPU canary states both."""

    for field in ("gpu_type", "pod_id"):
        broken = dict(example("canary-receipt"), **{field: None})
        with pytest.raises(ValueError, match="pod_id and gpu_type"):
            CanaryReceipt.model_validate(broken)
        with pytest.raises(SchemaValidationError):
            validate(broken)


def test_a_canary_criterion_id_must_be_a_masterplan_17_name() -> None:
    criteria = [
        {"criterion": name, "passed": True, "detail": "measured"}
        for name in CANARY_CRITERIA
    ] + [{"criterion": "output_quality", "passed": True, "detail": "no"}]
    broken = dict(example("canary-receipt"), criteria=criteria)
    with pytest.raises(ValueError):
        CanaryReceipt.model_validate(broken)
    with pytest.raises(SchemaValidationError):
        validate(broken)


def test_the_canary_schema_names_every_criterion_it_requires() -> None:
    """The file enumerates the ids; a bare count would accept ten duplicates."""

    payload = dict(
        example("canary-receipt"),
        criteria=[
            {"criterion": "process_start", "passed": True, "detail": "n"}
            for _ in CANARY_CRITERIA
        ],
    )
    with pytest.raises(SchemaValidationError):
        validate(payload)


def test_a_failed_page_receipt_may_have_no_image_dimensions() -> None:
    """11.6 D38: an image that could not be read is null, never a made-up size."""

    receipt = PageReceipt.model_validate(
        dict(
            example("page-receipt"),
            status="FAILED",
            error_class="INPUT_DECODE",
            image_width=None,
            image_height=None,
            raw_output_sha256=None,
            canonical_output_sha256=None,
            raw_output_path=None,
            canonical_output_path=None,
        )
    )
    assert receipt.image_width is None
    validate(receipt.to_record())


def test_a_success_page_receipt_still_requires_image_dimensions() -> None:
    broken = dict(example("page-receipt"), image_width=None)
    with pytest.raises(ValueError, match="image_width and image_height"):
        PageReceipt.model_validate(broken)
    with pytest.raises(SchemaValidationError):
        validate(broken)


def test_the_registry_record_names_its_promoted_prompt_columns() -> None:
    """11.6: named optional properties, not extension keys the model drops."""

    record = ModelRegistryRecord.model_validate(example("model-registry-record"))
    assert record.prompt_kind == "none"
    assert record.runtime_revision == "v3.2.0"
    assert record.prompt_sha256 is not None
    assert "prompt_sha256" in record.to_record()


def test_full_run_eligibility_requires_a_passed_canary() -> None:
    broken = dict(example("model-registry-record"), full_run_eligible=True)
    with pytest.raises(ValueError, match="canary_status"):
        ModelRegistryRecord.model_validate(broken)
    with pytest.raises(SchemaValidationError):
        validate(broken)


def test_mineru_vlm_is_hard_limited_to_concurrency_one() -> None:
    """Masterplan section 14: the incident this rule exists to prevent."""

    broken = dict(
        example("model-registry-record"),
        model_key="mineru_vlm",
        display_name="MinerU2.5-Pro VLM",
        repo="opendatalab/MinerU2.5-Pro-2605",
        max_concurrency_per_worker=2,
        concurrency_policy={"per_worker": 2, "scale": "replicas_and_concurrency"},
    )
    with pytest.raises(ValueError, match="concurrency 1"):
        ModelRegistryRecord.model_validate(broken)
    with pytest.raises(SchemaValidationError):
        validate(broken)


def test_a_runtime_spec_weights_block_must_match_the_pinned_model() -> None:
    broken = dict(example("runtime"))
    broken["weights"] = dict(broken["weights"], revision="0" * 40)
    with pytest.raises(ValueError, match=r"weights\.revision"):
        RuntimeSpec.model_validate(broken)


def test_a_success_run_response_must_carry_its_output() -> None:
    broken = dict(example("worker-run-response"), canonical=None)
    with pytest.raises(ValueError, match="missing"):
        WorkerRunResponse.model_validate(broken)
    with pytest.raises(SchemaValidationError):
        validate(broken)


def test_an_evaluator_registry_record_cannot_move_the_historical_pin() -> None:
    from arena.core.receipts import EvaluatorRegistryRecord

    broken = dict(example("evaluator-registry-record"), historical_pin="0" * 40)
    with pytest.raises(ValueError, match="FOLYNTA campaign pin"):
        EvaluatorRegistryRecord.model_validate(broken)
    with pytest.raises(SchemaValidationError):
        validate(broken)


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------


def test_utc_timestamp_matches_the_shape_every_record_requires() -> None:
    stamp = utc_timestamp()
    record = dict(example("event"), ts=stamp)
    validate(record)
    assert stamp.endswith("Z")


def test_a_timestamp_without_the_utc_marker_is_refused() -> None:
    with pytest.raises(ValueError, match="ts"):
        Event.model_validate(dict(example("event"), ts="2026-09-03 12:00:00"))


def test_fsync_is_actually_called_on_the_written_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        seen.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    write_atomic_json(tmp_path / "r.json", example("frozen"))
    append_jsonl(tmp_path / "r.jsonl", example("event"))
    assert len(seen) == 2


def test_a_runtime_spec_round_trips_with_and_without_a_cuda_floor() -> None:
    """``min_cuda_version`` is optional in the schema and in the model.

    Optional, not defaulted: a runtime that has not declared a floor reads back
    as ``None``, and the provisioning gate refuses it rather than picking one.
    """

    with_floor = dict(example("runtime"), min_cuda_version="12.9")
    validate(with_floor)
    parsed = RuntimeSpec.model_validate(with_floor)
    assert parsed.min_cuda_version == "12.9"
    assert parsed.to_record()["min_cuda_version"] == "12.9"
    validate(parsed.to_record())

    without = {
        key: value for key, value in example("runtime").items() if key != "min_cuda_version"
    }
    validate(without)
    absent = RuntimeSpec.model_validate(without)
    assert absent.min_cuda_version is None
    validate(absent.to_record())

    explicit_null = dict(example("runtime"), min_cuda_version=None)
    validate(explicit_null)
    assert RuntimeSpec.model_validate(explicit_null).min_cuda_version is None


def test_a_cuda_floor_that_is_not_major_minor_is_refused() -> None:
    """RunPod filters on ``major.minor``; a patch level matches no host."""

    for value in ("12.9.1", "12", "cuda12.9"):
        broken = dict(example("runtime"), min_cuda_version=value)
        with pytest.raises(ValueError):
            RuntimeSpec.model_validate(broken)
        with pytest.raises(SchemaValidationError):
            validate(broken)
