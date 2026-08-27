import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import freeze_gpu_successor_v2_protocols as freeze  # noqa: E402


def test_real_result_blind_protocols_are_authored_frozen_but_receipt_needs_authorities(tmp_path):
    dummy = tmp_path / "dummy.json"
    dummy.write_text("{}", encoding="utf-8")
    with pytest.raises(freeze.V2FreezeRefused, match="not the V2"):
        freeze.build_freeze(
            study_protocol=freeze.STUDY_PROTOCOL,
            runtime_protocol=freeze.RUNTIME_PROTOCOL,
            worker_bundle=dummy,
            tokenizer_manifest=dummy,
            model_pin=dummy,
            sfir4_acceptance=dummy,
            four_link_acceptance=dummy,
            materialized_input=dummy,
            runtime_image_digest="repo/image@sha256:" + "a" * 64,
        )


def test_missing_or_non_v2_worker_bundle_cannot_freeze(tmp_path):
    study = tmp_path / "study.yaml"
    runtime = tmp_path / "runtime.yaml"
    study.write_text(
        "schema: tavonel.v2.protocol.gpu_successor_study.v2\n"
        "protocol_id: GPU_SUCCESSOR_STUDY_V2\n"
        "study_id: SOURCE_FACT_PROPAGATION_MODEL_V2\nstatus: FROZEN\n",
        encoding="utf-8",
    )
    runtime.write_text(
        "schema: tavonel.v2.protocol.gpu_successor_runtime.v2\n"
        "protocol_id: GPU_SUCCESSOR_RUNTIME_V2\n"
        "study_id: SOURCE_FACT_PROPAGATION_MODEL_V2\nstatus: FROZEN\n",
        encoding="utf-8",
    )
    wrong = tmp_path / "worker.json"
    wrong.write_text(json.dumps({"schema": "v1"}), encoding="utf-8")
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_text(
        json.dumps({"schema": "tavonel.v2.tokenizer_artifact_manifest.v1"}),
        encoding="utf-8",
    )
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    with pytest.raises(freeze.V2FreezeRefused, match="not the V2"):
        freeze.build_freeze(
            study_protocol=study,
            runtime_protocol=runtime,
            worker_bundle=wrong,
            tokenizer_manifest=tokenizer,
            model_pin=model,
            sfir4_acceptance=wrong,
            four_link_acceptance=wrong,
            materialized_input=wrong,
            runtime_image_digest="repo/image@sha256:" + "a" * 64,
        )
