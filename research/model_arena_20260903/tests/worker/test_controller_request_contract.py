"""The request the controller builds must be one a real worker accepts.

On 2026-09-03 the GLM-OCR canary reached READY on a rented RTX 4090 and then
answered HTTP 422 to all 13 pages it was sent. The cause was one field name
meaning two different objects: the controller filled
``inference_config_sha256`` from the registry's
``official_inference_config_sha256`` (a hash of the model card's documented
serve command and prompt vocabulary) while the worker computes it from
``runtimes/<key>/runtime.json``'s operational ``inference_config``.

So this test builds the controller's own ``RunRequest`` from the real
``model_registry.json``, ``runtimes/`` and ``prompt_registry/``, and posts it
over HTTP to a real worker started from the same ``runtime.json``. It is
parametrised over every model that has a runtime, so the next registry or
runtime drift costs a test run instead of a pod.

The page bytes are synthetic: the staged PNGs live outside this namespace and
the checksum rule under test is that both sides spell a digest the same way,
which ``sha256_bytes`` and the worker's ``sha256_label`` decide, not the image.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arena.constants import CAMPAIGN_ID, GPU_MODEL_KEYS, MODEL_KEYS
from arena.controller.plan import load_model_registry
from arena.provider.safety import sha256_bytes
from arena.provider.worker_client import RunRequest
from arena.registry.runtimes import OPUS_MODEL_KEY
from arena.worker.synthetic import render_synthetic_page
from harness import IMAGE_DIGEST, worker

NAMESPACE = Path(__file__).resolve().parents[2]


def _runtime_descriptor(model_key: str) -> dict[str, Any]:
    path = NAMESPACE / "runtimes" / model_key / "runtime.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), path
    return document


def _prompt_text(prompt_id: str) -> str:
    # read_bytes().decode(): the harness writes the text back out as UTF-8, and
    # reading in text mode on Windows would turn "\n" into "\r\n" and change the
    # hash the worker computes.
    return (NAMESPACE / "prompt_registry" / f"{prompt_id}.txt").read_bytes().decode("utf-8")


def _first_manifest_row() -> dict[str, Any]:
    with (NAMESPACE / "source_manifest.jsonl").open(encoding="utf-8") as handle:
        row = json.loads(handle.readline())
    assert isinstance(row, dict)
    return row


def test_every_registry_model_is_covered_by_the_contract_test() -> None:
    """A model added to the registry cannot escape the parametrisation."""

    document = json.loads((NAMESPACE / "model_registry.json").read_text(encoding="utf-8"))
    keys = set(document["models"])
    assert keys == set(MODEL_KEYS)
    # The Opus lane is a subscription surface: no runtime.json, no pod, no
    # worker to post to (ARENA_CONTRACT section 7).
    assert keys - {OPUS_MODEL_KEY} == set(GPU_MODEL_KEYS)


@pytest.mark.parametrize("model_key", sorted(GPU_MODEL_KEYS))
def test_controller_run_request_is_accepted_by_the_worker(
    tmp_path: Path, model_key: str
) -> None:
    descriptor = _runtime_descriptor(model_key)
    entry = load_model_registry(
        NAMESPACE / "model_registry.json",
        model_key,
        runtime_image_digest=IMAGE_DIGEST,
    )
    row = _first_manifest_row()
    image = render_synthetic_page(width=480, height=640)

    with worker(
        tmp_path,
        descriptor_overrides=descriptor,
        prompt_text=_prompt_text(str(descriptor["prompt_id"])),
    ) as handle:
        assert handle.core.stage == "READY", handle.core.last_error
        request = RunRequest(
            campaign_id=CAMPAIGN_ID,
            inference_job_id=handle.next_job_id(),
            sample_id=str(row["sample_id"]),
            case_key=str(row["case_key"]),
            benchmark=str(row["benchmark"]),
            source_sha256=sha256_bytes(image),
            image_bytes=image,
            width=480,
            height=640,
            prompt_id=entry.prompt_id,
            prompt_sha256=entry.prompt_sha256,
            inference_config_sha256=entry.inference_config_sha256,
            job_kind="canary",
            metadata={"page_index": 0, "media_type": "pdf"},
        )
        status, body = handle.post("/v1/run", request.to_payload())

    assert status == 200, body
    assert body["status"] == "SUCCESS", body


def test_staged_manifest_digests_use_the_spelling_the_worker_demands() -> None:
    """``input_png_sha256`` is already ``sha256:<64 hex>`` (D14, contract 2).

    The worker rejects any other spelling with ``INVALID_REQUEST`` before it
    ever compares hashes, so this is the cheapest place to prove the two sides
    agree on the shape of a digest.
    """

    from arena.worker.server import SHA_LABEL_RE

    with (NAMESPACE / "source_manifest.jsonl").open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if number > 200:
                break
            row = json.loads(line)
            assert SHA_LABEL_RE.fullmatch(row["input_png_sha256"]), row["case_key"]
