"""Fixtures for the controller tests: a fake campaign root with real files."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from arena.constants import CAMPAIGN_ID
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry, SourceSample

BENCHMARK_REVISION = "aa1ee96d00000000000000000000000000000000"
MODEL_KEY = "paddleocr_vl_1_6"
# D16 makes runtime.json the owner of the prompt id; D17 keys the registry by it.
PROMPT_ID = "paddleocr_vl_1_6_pipeline_internal"


def make_sample(index: int, benchmark: str = "omnidoc") -> SourceSample:
    payload = f"fake page bytes {benchmark} {index}".encode()
    return SourceSample(
        sample_id=f"{benchmark}:images/page_{index:04d}",
        case_key=f"{benchmark}bench-{index:06d}",
        benchmark=benchmark,
        source_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        benchmark_revision=BENCHMARK_REVISION,
        image_path=f"inputs/{benchmark}/page_{index:04d}.png",
        width=1654,
        height=2339,
        media_type="pdf",
        page_index=0,
    )


def sample_bytes(sample: SourceSample) -> bytes:
    index = int(sample.case_key.rsplit("-", 1)[1])
    return f"fake page bytes {sample.benchmark} {index}".encode()


@pytest.fixture
def samples() -> tuple[SourceSample, ...]:
    return tuple(make_sample(index) for index in range(6))


@pytest.fixture
def entry() -> ModelPlanEntry:
    return ModelPlanEntry(
        model_key=MODEL_KEY,
        model_repo="PaddlePaddle/PaddleOCR-VL-1.6",
        model_revision="a" * 40,
        runtime_image_digest="sha256:" + "b" * 64,
        prompt_id="paddleocr_vl_official_v1",
        prompt_sha256="sha256:" + "c" * 64,
        inference_config_sha256="sha256:" + "d" * 64,
        shard_size=10,
        per_worker_concurrency=2,
        predicted_seconds_per_page=3.525,
        predicted_seconds_source="masterplan section 19 historical measurement",
        canary_status="PASS",
        full_run_eligible=True,
        runtime_mode_allowed=("baked",),
        gpu_pool_priority=("NVIDIA GeForce RTX 4090", "NVIDIA A40"),
    )


@pytest.fixture
def paths(tmp_path: Path) -> CampaignPaths:
    campaign = CampaignPaths(root=tmp_path)
    campaign.ensure()
    return campaign


@pytest.fixture
def credential_file(tmp_path: Path) -> Path:
    """A stand-in for the credential file. Nothing here is a real credential."""

    path = tmp_path / "fake_credentials.txt"
    path.write_text(
        "\n".join(
            [
                "Runpod_B: runpodfake000000000000000000000000000000000000000",
                "Cloudflare R2:",
                "Account API Token: {",
                "Access Key ID: r2fakeaccess00000000000000000000",
                "Secret Access Key: r2fakesecret" + "0" * 52,
                "Use jurisdiction-specific endpoints for S3 clients: "
                "https://fakeaccount.eu.r2.cloudflarestorage.com",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_source_manifest(path: Path, samples: Sequence[SourceSample]) -> None:
    """Lane A2's field names, which are the only ones the reader accepts (D14)."""

    lines = [
        json.dumps(
            {
                "sample_id": sample.sample_id,
                "case_key": sample.case_key,
                "benchmark": sample.benchmark,
                # D14: the controller maps these three, with no aliases.
                "input_png_sha256": sample.source_sha256,
                "dataset_revision": sample.benchmark_revision,
                "input_relative_path": sample.image_path,
                # Provenance only; never an input to an inference_job_id.
                "original_source_sha256": "sha256:" + "9" * 64,
                "width": sample.width,
                "height": sample.height,
                "media_type": sample.media_type,
                "page_index": sample.page_index,
            },
            sort_keys=True,
        )
        for sample in samples
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_prompt_registry(
    paths: CampaignPaths,
    *,
    prompt_id: str = PROMPT_ID,
    text: str = "Convert this page to markdown.\n",
    sha256: str | None = None,
) -> Path:
    """``prompt_registry/`` keyed by the runtime.json prompt_id (D17)."""

    directory = paths.prompt_registry_dir
    directory.mkdir(parents=True, exist_ok=True)
    # write_bytes, not write_text: on Windows text mode turns "\n" into "\r\n",
    # so the file would hash to something other than the digest recorded beside
    # it -- and the worker, which hashes the bytes, would answer PROMPT_MISMATCH
    # to every page. The same note is on the worker harness for the same reason.
    (directory / f"{prompt_id}.txt").write_bytes(text.encode("utf-8"))
    digest = sha256 or ("sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest())
    index = directory / "sha256.json"
    existing: dict[str, object] = {}
    if index.is_file():
        existing = json.loads(index.read_text(encoding="utf-8"))
    existing[prompt_id] = digest
    index.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
    return index


def write_bundle_receipt(
    paths: CampaignPaths,
    *,
    model_key: str = MODEL_KEY,
    bundle_sha256: str = "f" * 64,
    uploaded: bool = True,
) -> Path:
    """The D21 publish receipt a bootstrap canary reads its digest from.

    D35: the receipt stores bare 64-hex, because that is the spelling the
    on-pod ``sha256sum -c`` line needs. Callers that want an image digest
    prepend ``sha256:`` themselves.
    """

    paths.bundle_receipts_dir.mkdir(parents=True, exist_ok=True)
    path = paths.bundle_receipt(model_key)
    key = f"bundles/{CAMPAIGN_ID}/{model_key}/arena-bundle.tar.gz"
    path.write_text(
        json.dumps(
            {
                "schema": "tavonel.arena.bundle-publish.v1",
                "campaign_id": CAMPAIGN_ID,
                "model_key": model_key,
                "bundle_sha256": bundle_sha256,
                "bundle_size_bytes": 4096,
                "bundle_file_count": 12,
                "bundle_manifest_sha256": "sha256:" + "a" * 64,
                "r2_bucket": "tavonel-arena-20260903",
                "r2_key": key,
                "bundle_reference": f"tavonel-arena-20260903/{key}",
                "mode": "live" if uploaded else "dry_run",
                "uploaded": uploaded,
                "object_digest_verified_against": "HEAD ChecksumSHA256 header",
                "uploaded_at": "2026-09-03T12:00:00Z",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def write_runtime_json(
    paths: CampaignPaths,
    model_key: str = MODEL_KEY,
    **overrides: object,
) -> Path:
    """A ``runtimes/<model_key>/runtime.json`` with the D5/D7/D13 fields."""

    record: dict[str, object] = {
        "model_key": model_key,
        "display_name": "PaddleOCR-VL 1.6",
        "model_repo": "PaddlePaddle/PaddleOCR-VL-1.6",
        "model_revision": "a" * 40,
        "prompt_id": PROMPT_ID,
        "prompt_kind": "none",
        # The provisioning gate refuses a GPU pod whose runtime declares no
        # CUDA floor, so the default fixture carries one; the tests that check
        # the refusal override it with None.
        "min_cuda_version": "12.8",
        "base_image": "vllm/vllm-openai:v0.11.0@sha256:" + "e" * 64,
        "gpu_count_min": 1,
        "gpu_min_vram_gb": 24,
        "gpu_pool_priority": ["NVIDIA GeForce RTX 4090", "NVIDIA A40"],
        "per_page_timeout_seconds": 600,
        "runtime_mode_allowed": ["baked", "bootstrap"],
        "license": {"id": "Apache-2.0", "url": "https://example.invalid", "status": "verified"},
    }
    record.update(overrides)
    path = paths.runtime_json(model_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def write_catalog_snapshot(
    paths: CampaignPaths,
    *,
    rows: Sequence[dict[str, object]] | None = None,
    stamp: str = "20260903T120000Z",
    captured_at: str | None = None,
) -> Path:
    """A persisted price snapshot, exactly as ``catalog_gpus`` writes one.

    ``captured_at`` defaults to *now* because D23 refuses to price a dry run
    from a snapshot older than six hours; a fixture frozen at a wall-clock
    time would start failing the moment the clock moved past it.
    """

    default_rows: list[dict[str, object]] = [
        {
            "gpu_type_id": "NVIDIA GeForce RTX 4090",
            "display_name": "RTX 4090",
            "memory_gb": 24,
            "secure_available": True,
            "community_available": True,
            "price_secure_usd_per_hour": 0.69,
            "price_community_usd_per_hour": 0.34,
        },
        {
            "gpu_type_id": "NVIDIA A40",
            "display_name": "A40",
            "memory_gb": 48,
            "secure_available": True,
            "community_available": True,
            "price_secure_usd_per_hour": 0.44,
            "price_community_usd_per_hour": 0.39,
        },
    ]
    document = {
        "schema": "tavonel.arena.price_snapshot.v1",
        "campaign_id": CAMPAIGN_ID,
        "captured_at": captured_at
        or datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "https://api.runpod.io/v2/catalog/gpus",
        "row_count": len(rows or default_rows),
        "rows": list(rows or default_rows),
    }
    paths.provider_receipts_dir.mkdir(parents=True, exist_ok=True)
    path = paths.provider_receipts_dir / f"catalog-{stamp}.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def write_authorization(
    paths: CampaignPaths,
    *,
    name: str = "phase1-canary.json",
    phase: str = "phase1_canary",
    max_usd: float = 25.0,
    model_keys: object = "*",
    authorized_at: str = "2026-09-03T00:00:00Z",
    expires_at: str | None = "2036-09-03T00:00:00Z",
    campaign_id: str = CAMPAIGN_ID,
) -> Path:
    """One founder authorization receipt (ARENA_CONTRACT section 11 D6)."""

    paths.authorizations_dir.mkdir(parents=True, exist_ok=True)
    path = paths.authorizations_dir / name
    path.write_text(
        json.dumps(
            {
                "schema": "tavonel.arena.authorization-receipt.v1",
                "campaign_id": campaign_id,
                "phase": phase,
                "authorized_by": "founder",
                "authorized_at": authorized_at,
                "expires_at": expires_at,
                "max_usd": max_usd,
                "model_keys": model_keys,
                "statement": "test fixture; not a real founder decision",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def write_model_registry(path: Path, entry: ModelPlanEntry, **overrides: object) -> None:
    record: dict[str, object] = {
        "model_key": entry.model_key,
        "display_name": "PaddleOCR-VL 1.6",
        "model_repo": entry.model_repo,
        "model_revision": entry.model_revision,
        "runtime_image_digest": entry.runtime_image_digest,
        "official_prompt_id": entry.prompt_id,
        "prompt_sha256": entry.prompt_sha256,
        # D16: the hash of runtime.json's operational inference_config, which
        # is what the worker recomputes on the pod. Distinct from
        # official_inference_config_sha256, which hashes the model card's
        # documented serve command -- the two were conflated once and the
        # GLM-OCR canary answered HTTP 422 to every page it was sent.
        "inference_config_sha256": entry.inference_config_sha256,
        "shard_size_hint": entry.shard_size,
        "concurrency_policy": {"per_worker": entry.per_worker_concurrency},
        "historical_sec_per_page": entry.predicted_seconds_per_page,
        "canary_status": entry.canary_status,
        "full_run_eligible": entry.full_run_eligible,
        "runtime_mode_allowed": list(entry.runtime_mode_allowed),
        "gpu_pool_priority": list(entry.gpu_pool_priority),
    }
    record.update(overrides)
    path.write_text(
        json.dumps({"campaign_id": CAMPAIGN_ID, "models": {entry.model_key: record}}, indent=2),
        encoding="utf-8",
    )
