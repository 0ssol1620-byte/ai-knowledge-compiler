"""Identifier determinism, field sensitivity and fail-closed input checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arena.constants import CAMPAIGN_ID, STAGED_PUBLIC_CORE_ROOT
from arena.core.ids import (
    IdError,
    bootstrap_image_digest,
    canonical_json,
    canonical_json_bytes,
    case_key_from_staged,
    inference_job_id,
    recovery_job_id,
    sample_id_from_staged,
    sha256_file,
    sha256_hex,
    sha256_ref,
    shard_id,
    strip_source_extension,
    subscription_image_digest,
    worker_id,
)

SHA_A = "sha256:" + "a1" * 32
SHA_B = "sha256:" + "b2" * 32
SHA_C = "sha256:" + "c3" * 32
IMAGE = "ghcr.io/tavonel/arena@sha256:" + "1b" * 32

JOB_FIELDS: dict[str, str] = {
    "campaign_id": CAMPAIGN_ID,
    "benchmark_revision": "aa1ee96d",
    "sample_id": "omnidoc:images/PPT_1001115_eng_page_003",
    "source_sha256": SHA_A,
    "model_repo": "PaddlePaddle/PaddleOCR-VL-1.6",
    "model_revision": "1234567890abcdef1234567890abcdef12345678",
    "runtime_image_digest": IMAGE,
    "prompt_sha256": SHA_B,
    "inference_config_sha256": SHA_C,
}


# --------------------------------------------------------------------------
# canonical json and digests
# --------------------------------------------------------------------------


def test_canonical_json_sorts_keys_and_escapes_non_ascii() -> None:
    text = canonical_json({"b": 1, "a": "한글"})
    assert text == '{"a":"\\ud55c\\uae00","b":1}'
    assert canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_canonical_json_is_insertion_order_independent() -> None:
    assert canonical_json({"x": 1, "y": [2, 3]}) == canonical_json({"y": [2, 3], "x": 1})


def test_canonical_json_rejects_non_finite_floats() -> None:
    with pytest.raises(IdError):
        canonical_json({"value": float("nan")})


def test_sha256_hex_is_bare_and_sha256_ref_is_prefixed() -> None:
    assert sha256_hex("abc") == sha256_hex(b"abc")
    assert sha256_ref("abc") == f"sha256:{sha256_hex('abc')}"
    assert len(sha256_hex("abc")) == 64


def test_sha256_file_reads_the_bytes_on_disk(tmp_path: Path) -> None:
    target = tmp_path / "page.bin"
    target.write_bytes(b"page bytes")
    assert sha256_file(target) == sha256_ref(b"page bytes")


def test_bootstrap_image_digest_round_trip() -> None:
    assert bootstrap_image_digest(SHA_A) == f"bootstrap:{SHA_A}"
    with pytest.raises(IdError):
        bootstrap_image_digest("not-a-digest")


# --------------------------------------------------------------------------
# sample_id / case_key
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "benchmark", "expected"),
    [
        (
            {
                "source_relative_path": "images/PPT_1001115_eng_page_003.png",
                "media_type": "image",
                "page_index": 3,
            },
            "omnidoc",
            "omnidoc:images/PPT_1001115_eng_page_003",
        ),
        (
            {
                "source_relative_path": (
                    "docs/chart/(Web_version)_E-Government_Survey_2024_1392024_p101.pdf"
                ),
                "media_type": "pdf",
                "page_index": 0,
            },
            "parsebench",
            (
                "parsebench:docs/chart/"
                "(Web_version)_E-Government_Survey_2024_1392024_p101#p0"
            ),
        ),
        (
            {
                "source_relative_path": "bench_data/pdfs/arxiv_math/2502.15977_pg21.pdf",
                "media_type": "pdf",
                "page_index": 0,
            },
            "olmocr",
            "olmocr:bench_data/pdfs/arxiv_math/2502.15977_pg21#p0",
        ),
    ],
)
def test_sample_id_matches_the_contract_examples(
    entry: dict[str, Any], benchmark: str, expected: str
) -> None:
    assert sample_id_from_staged(entry, benchmark) == expected


def test_strip_source_extension_only_removes_the_final_known_suffix() -> None:
    assert strip_source_extension("a/2502.15977_pg21.pdf") == "a/2502.15977_pg21"


@pytest.mark.parametrize(
    "relative_path",
    ["a/b.tar.gz", "a/b", "a/2502.15977_pg21", "/abs/b.png", "..\\b.png", "a/../b.png"],
)
def test_strip_source_extension_refuses_anything_it_would_have_to_guess(
    relative_path: str,
) -> None:
    with pytest.raises(IdError):
        strip_source_extension(relative_path)


def test_sample_id_rejects_an_unknown_benchmark_key() -> None:
    entry = {"source_relative_path": "a/b.png", "media_type": "image", "page_index": 0}
    with pytest.raises(IdError):
        sample_id_from_staged(entry, "omnidocbench")


def test_sample_id_requires_a_page_index_for_pdf_sources() -> None:
    with pytest.raises(IdError):
        sample_id_from_staged(
            {"source_relative_path": "a/b.pdf", "media_type": "pdf"}, "olmocr"
        )


def test_case_key_checks_the_benchmark_prefix_and_filesystem_safety() -> None:
    entry = {"case_id": "omnidocbench-58851882e7b39101a6f5756c"}
    assert case_key_from_staged(entry, "omnidoc") == entry["case_id"]
    with pytest.raises(IdError):
        case_key_from_staged(entry, "parsebench")
    with pytest.raises(IdError):
        case_key_from_staged({"case_id": "omnidocbench-a/b"}, "omnidoc")


@pytest.mark.skipif(
    not (STAGED_PUBLIC_CORE_ROOT / "omnidocbench" / "inference-input-manifest.json").is_file(),
    reason="staged public-core tree is not present on this host",
)
def test_ids_derive_cleanly_from_the_real_staged_manifests() -> None:
    """Every staged row produces an id; nothing needs a special case."""

    for benchmark, staged_dir in (
        ("omnidoc", "omnidocbench"),
        ("parsebench", "parsebench"),
        ("olmocr", "olmocr-bench"),
    ):
        path = STAGED_PUBLIC_CORE_ROOT / staged_dir / "inference-input-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        rows = manifest["inputs"]
        assert rows, f"{staged_dir} manifest is empty"
        sample_ids = {sample_id_from_staged(row, benchmark) for row in rows}
        case_keys = {case_key_from_staged(row, benchmark) for row in rows}
        assert len(sample_ids) == len(rows), f"{benchmark} sample_id collision"
        assert len(case_keys) == len(rows), f"{benchmark} case_key collision"


# --------------------------------------------------------------------------
# job ids
# --------------------------------------------------------------------------


def test_inference_job_id_is_deterministic_and_bare_hex() -> None:
    first = inference_job_id(**JOB_FIELDS)
    second = inference_job_id(**JOB_FIELDS)
    assert first == second
    assert len(first) == 64
    assert first == first.lower()


@pytest.mark.parametrize("field", sorted(JOB_FIELDS))
def test_inference_job_id_changes_when_any_single_field_changes(field: str) -> None:
    baseline = inference_job_id(**JOB_FIELDS)
    mutated = dict(JOB_FIELDS)
    value = mutated[field]
    if value.startswith("sha256:"):
        mutated[field] = "sha256:" + "0" * 64
    elif "@sha256:" in value:
        mutated[field] = "ghcr.io/tavonel/other@sha256:" + "0" * 64
    else:
        mutated[field] = value + "-changed"
    assert inference_job_id(**mutated) != baseline


def test_inference_job_id_accepts_a_bootstrap_digest() -> None:
    fields = dict(JOB_FIELDS, runtime_image_digest=bootstrap_image_digest(SHA_A))
    assert len(inference_job_id(**fields)) == 64


# --------------------------------------------------------------------------
# ARENA_CONTRACT 11.5 D27 - subscription runtime digests
# --------------------------------------------------------------------------


def test_subscription_image_digest_round_trip() -> None:
    label = "claude-code-2.1.228-claude-opus-5"
    assert subscription_image_digest(label) == f"subscription:{label}"


@pytest.mark.parametrize(
    "label",
    ["claude-code-2.1.228-claude-opus-5", "a", "A.b_c-1", "opus-5", "1.0.0"],
)
def test_a_subscription_digest_is_accepted_by_the_job_id(label: str) -> None:
    fields = dict(JOB_FIELDS, runtime_image_digest=subscription_image_digest(label))
    assert len(inference_job_id(**fields)) == 64


@pytest.mark.parametrize(
    "label",
    [
        "claude/code",  # a slash would read as a registry path
        "claude code",  # whitespace
        "claude:code",  # a colon would read as a second scheme
        "claude\tcode",
        "claude\ncode",
        "",
        " opus",
        "opus ",
        "opus5!",
        "opus5#1",
    ],
)
def test_subscription_image_digest_refuses_an_unsafe_label(label: str) -> None:
    with pytest.raises(IdError):
        subscription_image_digest(label)


@pytest.mark.parametrize(
    "digest",
    [
        "subscription:",
        "subscription:claude/code",
        "subscription:claude code",
        "subscription:a:b",
        "subscription",
    ],
)
def test_inference_job_id_refuses_a_malformed_subscription_digest(digest: str) -> None:
    """D27: the grammar widened for one shape only; everything else still fails."""

    fields = dict(JOB_FIELDS, runtime_image_digest=digest)
    with pytest.raises(IdError):
        inference_job_id(**fields)


def test_a_subscription_digest_changes_the_job_id() -> None:
    """Two CLI builds are two runtimes, so they are two jobs."""

    first = inference_job_id(
        **dict(JOB_FIELDS, runtime_image_digest=subscription_image_digest("cc-2.1.228-opus5"))
    )
    second = inference_job_id(
        **dict(JOB_FIELDS, runtime_image_digest=subscription_image_digest("cc-2.1.229-opus5"))
    )
    assert first != second
    assert first != inference_job_id(**JOB_FIELDS)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("source_sha256", "a1" * 32),
        ("prompt_sha256", "sha256:NOTHEX"),
        ("inference_config_sha256", ""),
        ("runtime_image_digest", "latest"),
        ("campaign_id", " leading-space"),
    ],
)
def test_inference_job_id_refuses_malformed_inputs(field: str, bad_value: str) -> None:
    fields = dict(JOB_FIELDS, **{field: bad_value})
    with pytest.raises(IdError):
        inference_job_id(**fields)


def test_recovery_job_id_is_deterministic_and_field_sensitive() -> None:
    base = {
        "campaign_id": CAMPAIGN_ID,
        "inference_job_id_of_base": "e5" * 32,
        "recovery_type": "overlap_tiling",
        "recovery_config_sha256": SHA_A,
        "round": 1,
    }
    first = recovery_job_id(**base)  # type: ignore[arg-type]
    assert first == recovery_job_id(**base)  # type: ignore[arg-type]
    assert recovery_job_id(**{**base, "round": 2}) != first  # type: ignore[arg-type]
    assert recovery_job_id(**{**base, "recovery_type": "crop"}) != first  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("inference_job_id_of_base", "sha256:" + "e5" * 32),
        ("recovery_type", "rerender"),
        ("round", 0),
        ("recovery_config_sha256", "nope"),
    ],
)
def test_recovery_job_id_refuses_malformed_inputs(field: str, bad_value: object) -> None:
    base: dict[str, Any] = {
        "campaign_id": CAMPAIGN_ID,
        "inference_job_id_of_base": "e5" * 32,
        "recovery_type": "overlap_tiling",
        "recovery_config_sha256": SHA_A,
        "round": 1,
    }
    base[field] = bad_value
    with pytest.raises(IdError):
        recovery_job_id(**base)


# --------------------------------------------------------------------------
# shard / worker ids
# --------------------------------------------------------------------------


def test_shard_id_zero_pads_and_sorts_as_a_plain_string() -> None:
    assert shard_id("mineru_vlm", "olmocr", 7) == "mineru_vlm-olmocr-0007"
    ordered = [shard_id("mineru_vlm", "olmocr", index) for index in (0, 9, 10, 100)]
    assert ordered == sorted(ordered)


def test_worker_id_shape() -> None:
    assert worker_id("glm_ocr", 2, "pod-abc123") == "glm_ocr-w2-pod-abc123"


@pytest.mark.parametrize(
    ("model_key", "benchmark", "index"),
    [("not_a_model", "olmocr", 0), ("glm_ocr", "omnidocbench", 0), ("glm_ocr", "olmocr", -1)],
)
def test_shard_id_refuses_unknown_parts(model_key: str, benchmark: str, index: int) -> None:
    with pytest.raises(IdError):
        shard_id(model_key, benchmark, index)


def test_worker_id_refuses_an_unsafe_pod_id() -> None:
    with pytest.raises(IdError):
        worker_id("glm_ocr", 0, "pod/../etc")
