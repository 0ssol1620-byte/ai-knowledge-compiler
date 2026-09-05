"""DeepSeek-OCR-2 runtime tests: adapter contract, failure paths, canonicalization.

No GPU, no network, no torch. The backend is injected.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from arena.constants import ERROR_CLASSES, GPU_MODEL_KEYS
from arena.worker.adapter_api import AdapterConfig, AdapterError, PageInput, RawOutput
from conftest import load_runtime_json, load_runtime_module, runtime_dir, write_synthetic_png

NAMESPACE_ROOT = Path(__file__).resolve().parents[2]
CATALOG_SNAPSHOT = (
    NAMESPACE_ROOT / "receipts" / "provider_receipts" / "catalog-20260903T063539Z.json"
)

MODEL_KEY = "deepseek_ocr2"
adapter = load_runtime_module(MODEL_KEY, "adapter")
canonical = load_runtime_module(MODEL_KEY, "canonical")


# --------------------------------------------------------------- fixtures ---


class FakeBackend:
    """Stands in for TransformersBackend. Records calls; never touches a GPU."""

    def __init__(
        self,
        *,
        text: str = "# hello\n",
        raises: BaseException | None = None,
        finish_reason: str | None = None,
    ) -> None:
        self.text = text
        self.raises = raises
        self.finish_reason = finish_reason
        self.calls: list[tuple[Path, str]] = []
        self.closed = False

    def generate(self, image_path: Path, prompt: str) -> Any:
        self.calls.append((image_path, prompt))
        if self.raises is not None:
            raise self.raises
        return adapter.BackendResult(
            text=self.text,
            finish_reason=self.finish_reason,
            usage={"output_tokens": 11},
            peak_vram_mb=4096,
        )

    def provenance(self) -> dict[str, Any]:
        return {"runtime": "fake", "versions": {"torch": None}}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def weights_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "weights"
    directory.mkdir()
    (directory / adapter.LARGEST_WEIGHT_FILE).write_bytes(b"not-real-weights")
    (directory / "config.json").write_text('{"model_type": "deepseek_vl_v2"}', encoding="utf-8")
    (directory / "nested").mkdir()
    (directory / "nested" / "extra.txt").write_text("x", encoding="utf-8")
    adapter.write_weights_receipt(
        directory, repo=adapter.MODEL_REPO, revision=adapter.MODEL_REVISION
    )
    return directory


def make_config(weights_dir: Path, **overrides: Any) -> AdapterConfig:
    values: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "model_repo": adapter.MODEL_REPO,
        "model_revision": adapter.MODEL_REVISION,
        "weights_dir": weights_dir,
        "prompt_id": "deepseek_ocr2_grounding_markdown_v1",
        "prompt_text": adapter.OFFICIAL_PROMPT,
        "inference_config": {"base_size": 1024, "image_size": 768, "crop_mode": True},
        "inference_config_sha256": "sha256:" + "0" * 64,
    }
    values.update(overrides)
    return AdapterConfig(**values)


def loaded_adapter(weights_dir: Path, backend: FakeBackend) -> Any:
    instance = adapter.DeepSeekOCR2Adapter(backend_factory=lambda cfg, path: backend)
    instance.load(make_config(weights_dir))
    return instance


def make_page(tmp_path: Path) -> tuple[PageInput, Path]:
    image = tmp_path / "page.png"
    write_synthetic_png(image)
    return (
        PageInput(
            inference_job_id="a" * 64,
            sample_id="omnidoc:images/PPT_1001115_eng_page_003",
            case_key="omnidocbench-58851882e7b39101a6f5756c",
            benchmark="omnidoc",
            image_path=image,
            source_sha256=adapter._sha256_file(image),
            width=64,
            height=96,
            metadata={"page_index": 0, "media_type": "image"},
        ),
        image,
    )


# ----------------------------------------------------------- runtime.json ---


def test_runtime_json_matches_the_adapter_pins() -> None:
    spec = load_runtime_json(MODEL_KEY)
    assert spec["model_key"] == MODEL_KEY
    assert spec["model_key"] in GPU_MODEL_KEYS
    assert spec["model_repo"] == adapter.MODEL_REPO
    assert spec["model_revision"] == adapter.MODEL_REVISION
    weights = spec["weights"]
    assert weights["repo"] == adapter.MODEL_REPO
    assert weights["revision"] == adapter.MODEL_REVISION
    assert weights["largest_file"] == adapter.LARGEST_WEIGHT_FILE
    assert weights["largest_file_sha256"] == adapter.LARGEST_WEIGHT_SHA256


def test_runtime_json_carries_every_contract_field() -> None:
    spec = load_runtime_json(MODEL_KEY)
    required = {
        "model_key",
        "display_name",
        "model_repo",
        "model_revision",
        "official_runtime",
        "runtime_version",
        "base_image",
        "gpu_min_vram_gb",
        "gpu_pool_priority",
        "max_concurrency_per_worker",
        "shard_size_hint",
        "per_page_timeout_seconds",
        "prompt_id",
        "inference_config",
        "weights_strategy",
        "runtime_mode_allowed",
        "weights",
        "official_source_urls",
        "license",
        "notes",
    }
    assert required <= set(spec)
    assert spec["official_runtime"] in {"vllm", "transformers", "paddle", "mineru_cli", "custom"}
    assert "@sha256:" in spec["base_image"]
    assert spec["weights_strategy"] in {"baked", "volume_cache", "boot_download"}
    assert set(spec["runtime_mode_allowed"]) <= {"baked", "bootstrap"}
    assert spec["gpu_pool_priority"]
    assert spec["max_concurrency_per_worker"] >= 1
    assert spec["per_page_timeout_seconds"] > 0
    assert spec["shard_size_hint"] > 0
    assert spec["license"]["id"] == "Apache-2.0"
    assert spec["license"]["url"].startswith("https://")
    assert all(url.startswith("https://") for url in spec["official_source_urls"])
    assert spec["weights"]["largest_file_sha256"].startswith("sha256:")


def test_runtime_json_is_valid_utf8_json_with_no_secret_shaped_strings() -> None:
    text = (runtime_dir(MODEL_KEY) / "runtime.json").read_text(encoding="utf-8")
    json.loads(text)
    for marker in ("rpa_", "hf_", "sk-", "ghp_", "AKIA"):
        assert marker not in text


# --------------------------------------------------------- module hygiene ---


def test_module_imports_without_torch_or_transformers() -> None:
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules
    assert adapter.DeepSeekOCR2Adapter.model_key == MODEL_KEY


def test_official_prompt_hashes_to_the_batch_script_spelling() -> None:
    assert adapter.OFFICIAL_PROMPT == "<image>\n<|grounding|>Convert the document to markdown."
    assert adapter._sha256_text(adapter.OFFICIAL_PROMPT) == adapter.PINNED_PROMPT_SHA256


# ---------------------------------------------------------------- weights ---


def test_weights_receipt_round_trips(weights_dir: Path) -> None:
    revision, manifest = adapter.verify_weights(
        weights_dir, expected_revision=adapter.MODEL_REVISION
    )
    assert revision == adapter.MODEL_REVISION
    assert manifest.startswith("sha256:")
    receipt = json.loads(
        (weights_dir / adapter.WEIGHTS_RECEIPT_NAME).read_text(encoding="utf-8")
    )
    assert receipt["weights_sha256_manifest"] == manifest
    assert receipt["file_count"] == 3


def test_write_weights_receipt_refuses_a_directory_without_the_checkpoint(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AdapterError) as excinfo:
        adapter.write_weights_receipt(empty, repo=adapter.MODEL_REPO, revision="x")
    assert excinfo.value.error_class == "MODEL_DOWNLOAD"


def test_verify_weights_without_a_receipt_fails_model_load(tmp_path: Path) -> None:
    directory = tmp_path / "bare"
    directory.mkdir()
    with pytest.raises(AdapterError) as excinfo:
        adapter.verify_weights(directory, expected_revision=adapter.MODEL_REVISION)
    assert excinfo.value.error_class == "MODEL_LOAD"


def test_verify_weights_rejects_a_different_revision(weights_dir: Path) -> None:
    with pytest.raises(AdapterError) as excinfo:
        adapter.verify_weights(weights_dir, expected_revision="0" * 40)
    assert excinfo.value.error_class == "MODEL_LOAD"


def test_verify_weights_detects_a_tampered_file(weights_dir: Path) -> None:
    (weights_dir / adapter.LARGEST_WEIGHT_FILE).write_bytes(b"tampered")
    with pytest.raises(AdapterError) as excinfo:
        adapter.verify_weights(weights_dir, expected_revision=adapter.MODEL_REVISION)
    assert excinfo.value.error_class == "CHECKSUM"


def test_verify_weights_rejects_a_corrupt_receipt(weights_dir: Path) -> None:
    (weights_dir / adapter.WEIGHTS_RECEIPT_NAME).write_text("[]", encoding="utf-8")
    with pytest.raises(AdapterError) as excinfo:
        adapter.verify_weights(weights_dir, expected_revision=adapter.MODEL_REVISION)
    assert excinfo.value.error_class == "MODEL_LOAD"


# ------------------------------------------------------------------- load ---


def test_load_returns_a_verified_receipt(weights_dir: Path) -> None:
    backend = FakeBackend()
    instance = adapter.DeepSeekOCR2Adapter(backend_factory=lambda cfg, path: backend)
    receipt = instance.load(make_config(weights_dir))
    assert receipt.model_key == MODEL_KEY
    assert receipt.model_revision == adapter.MODEL_REVISION
    assert receipt.weights_sha256_manifest.startswith("sha256:")
    assert receipt.load_ms >= 0
    assert receipt.runtime_provenance["runtime"] == "fake"


def test_load_refuses_a_prompt_that_is_not_the_official_one(weights_dir: Path) -> None:
    instance = adapter.DeepSeekOCR2Adapter(backend_factory=lambda cfg, path: FakeBackend())
    # The HF model card spelling: identical apart from one trailing space.
    with pytest.raises(AdapterError) as excinfo:
        instance.load(make_config(weights_dir, prompt_text=adapter.OFFICIAL_PROMPT + " "))
    assert excinfo.value.error_class == "MODEL_LOAD"
    assert adapter.PINNED_PROMPT_SHA256 in str(excinfo.value)


def test_load_refuses_a_configuration_for_another_model(weights_dir: Path) -> None:
    instance = adapter.DeepSeekOCR2Adapter(backend_factory=lambda cfg, path: FakeBackend())
    with pytest.raises(AdapterError) as excinfo:
        instance.load(make_config(weights_dir, model_key="ovisocr2"))
    assert excinfo.value.error_class == "MODEL_LOAD"


def test_load_refuses_a_missing_weights_directory(tmp_path: Path) -> None:
    instance = adapter.DeepSeekOCR2Adapter(backend_factory=lambda cfg, path: FakeBackend())
    with pytest.raises(AdapterError) as excinfo:
        instance.load(make_config(tmp_path / "nope"))
    assert excinfo.value.error_class == "MODEL_LOAD"


def test_load_classifies_a_backend_construction_failure(weights_dir: Path) -> None:
    def explode(cfg: AdapterConfig, path: Path) -> Any:
        raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")

    instance = adapter.DeepSeekOCR2Adapter(backend_factory=explode)
    with pytest.raises(AdapterError) as excinfo:
        instance.load(make_config(weights_dir))
    assert excinfo.value.error_class == "CUDA_OOM"


def test_using_the_adapter_before_load_fails_closed(tmp_path: Path) -> None:
    instance = adapter.DeepSeekOCR2Adapter(backend_factory=lambda cfg, path: FakeBackend())
    page, _ = make_page(tmp_path)
    with pytest.raises(AdapterError) as excinfo:
        instance.infer(page)
    assert excinfo.value.error_class == "MODEL_LOAD"


# ------------------------------------------------------------------ infer ---


def test_infer_returns_the_raw_text_verbatim(weights_dir: Path, tmp_path: Path) -> None:
    raw_text = "<|ref|>title<|/ref|><|det|>[[1, 2, 3, 4]]<|/det|>\n# Title  \n"
    backend = FakeBackend(text=raw_text)
    instance = loaded_adapter(weights_dir, backend)
    page, image = make_page(tmp_path)
    output = instance.infer(page)
    assert output.raw_text == raw_text
    assert output.output_format == "deepseek-ocr2-grounded-markdown"
    assert output.warnings == ()
    assert set(output.timings_ms) >= {"preprocess_ms", "inference_ms", "postprocess_ms"}
    assert output.peak_vram_mb == 4096
    assert backend.calls == [(image, adapter.OFFICIAL_PROMPT)]


def test_infer_rejects_a_page_whose_bytes_do_not_match_the_job(
    weights_dir: Path, tmp_path: Path
) -> None:
    instance = loaded_adapter(weights_dir, FakeBackend())
    page, image = make_page(tmp_path)
    image.write_bytes(b"different bytes")
    with pytest.raises(AdapterError) as excinfo:
        instance.infer(page)
    assert excinfo.value.error_class == "CHECKSUM"


def test_infer_rejects_a_missing_page(weights_dir: Path, tmp_path: Path) -> None:
    instance = loaded_adapter(weights_dir, FakeBackend())
    page, image = make_page(tmp_path)
    image.unlink()
    with pytest.raises(AdapterError) as excinfo:
        instance.infer(page)
    assert excinfo.value.error_class == "INPUT_DECODE"


def test_infer_flags_empty_output_without_raising(weights_dir: Path, tmp_path: Path) -> None:
    instance = loaded_adapter(weights_dir, FakeBackend(text="   \n"))
    page, _ = make_page(tmp_path)
    output = instance.infer(page)
    assert output.raw_text == "   \n"
    assert any(warning.startswith("OUTPUT_EMPTY") for warning in output.warnings)
    assert output.semantic_error_class == "OUTPUT_EMPTY"


def test_infer_flags_truncated_output_with_semantic_error_class(
    weights_dir: Path, tmp_path: Path
) -> None:
    instance = loaded_adapter(weights_dir, FakeBackend(text="partial", finish_reason="length"))
    page, _ = make_page(tmp_path)
    output = instance.infer(page)
    assert any(warning.startswith("OUTPUT_TRUNCATED") for warning in output.warnings)
    assert output.semantic_error_class == "OUTPUT_TRUNCATED"


def test_infer_leaves_semantic_error_class_null_on_a_clean_page(
    weights_dir: Path, tmp_path: Path
) -> None:
    instance = loaded_adapter(weights_dir, FakeBackend(text="# clean\n"))
    page, _ = make_page(tmp_path)
    output = instance.infer(page)
    assert output.warnings == ()
    assert output.semantic_error_class is None


def test_infer_maps_a_backend_failure_onto_the_taxonomy(
    weights_dir: Path, tmp_path: Path
) -> None:
    instance = loaded_adapter(
        weights_dir, FakeBackend(raises=RuntimeError("CUDA error: device-side assert triggered"))
    )
    page, _ = make_page(tmp_path)
    with pytest.raises(AdapterError) as excinfo:
        instance.infer(page)
    assert excinfo.value.error_class in ERROR_CLASSES
    assert excinfo.value.error_class == "GPU_KERNEL"


def test_an_unrecognised_failure_is_unknown_not_a_guess() -> None:
    assert adapter.classify_exception(ValueError("something nobody anticipated")) == "UNKNOWN"


def test_warmup_and_close(weights_dir: Path, tmp_path: Path) -> None:
    backend = FakeBackend(text="warm")
    instance = loaded_adapter(weights_dir, backend)
    synthetic = tmp_path / "synthetic.png"
    write_synthetic_png(synthetic)
    receipt = instance.warmup(synthetic)
    assert receipt.output_chars == 4
    assert receipt.schema_valid is True
    provenance = instance.runtime_provenance()
    assert provenance["model_revision"] == adapter.MODEL_REVISION
    instance.close()
    assert backend.closed is True
    instance.close()  # idempotent


# --------------------------------------------------------- canonicalization ---

RAW_HEADING_TABLE_FORMULA = (
    "<|ref|>title<|/ref|><|det|>[[10, 20, 300, 60]]<|/det|>\n"
    "# Quarterly Report\n"
    "\n"
    "<|ref|>table<|/ref|><|det|>[[10, 80, 500, 300]]<|/det|>\n"
    "<table><tr><td>A</td><td>B</td></tr></table>\n"
    "\n"
    "<|ref|>formula<|/ref|><|det|>[[10, 320, 400, 360]]<|/det|>\n"
    r"\[ E = mc^2 \quad (1) \]"
    "\n"
)


def _raw(text: str, *, warnings: tuple[str, ...] = ()) -> RawOutput:
    return RawOutput(
        raw_text=text,
        output_format="deepseek-ocr2-grounded-markdown",
        native_json=None,
        usage={},
        timings_ms={"preprocess_ms": 0, "inference_ms": 0, "postprocess_ms": 0},
        warnings=warnings,
    )


def test_canonicalize_strips_grounding_and_keeps_the_content() -> None:
    result = canonical.canonicalize(_raw(RAW_HEADING_TABLE_FORMULA))
    assert "# Quarterly Report" in result.markdown
    assert "<table><tr><td>A</td><td>B</td></tr></table>" in result.markdown
    assert "<|ref|>" not in result.markdown
    assert "<|det|>" not in result.markdown
    assert result.elements is not None
    assert [element["category"] for element in result.elements] == ["title", "table", "formula"]
    assert result.elements[0]["det_raw"] == "[[10, 20, 300, 60]]"
    assert result.lossy is True


def test_canonicalize_applies_the_official_formula_cleaner() -> None:
    result = canonical.canonicalize(_raw(RAW_HEADING_TABLE_FORMULA))
    assert r"\[E = mc^2\]" in result.markdown
    assert r"\quad" not in result.markdown
    assert any("clean_formula" in note for note in result.conversion_notes)


def test_canonicalize_of_empty_output_is_empty_not_invented() -> None:
    result = canonical.canonicalize(_raw("   \n"))
    assert result.markdown == ""
    assert result.elements == ()
    assert result.lossy is False
    assert result.conversion_notes == ("empty model output preserved as empty markdown",)


def test_canonicalize_preserves_a_truncated_page() -> None:
    truncated = (
        "<|ref|>table<|/ref|><|det|>[[0, 0, 10, 10]]<|/det|>\n"
        "<table><tr><td>A</td><td>B</td></tr><tr><td>C"
    )
    result = canonical.canonicalize(_raw(truncated, warnings=("OUTPUT_TRUNCATED: cap",)))
    assert result.markdown.rstrip().endswith("<tr><td>C")
    assert any("adapter warning: OUTPUT_TRUNCATED" in note for note in result.conversion_notes)


def test_canonicalize_leaves_a_page_without_grounding_untouched() -> None:
    plain = "# Heading\n\n\n\nbody text\n"
    result = canonical.canonicalize(_raw(plain))
    # The official script only collapses newlines inside the grounding loop, so a
    # page with no markers keeps its blank lines. This quirk is reproduced on
    # purpose; see canonical.py.
    assert result.markdown == plain
    assert result.lossy is False
    assert result.elements == ()


# --------------------------------------------------- integration pass D5/D9 ---


def test_runtime_json_declares_gpu_count_min() -> None:
    spec = load_runtime_json(MODEL_KEY)
    assert isinstance(spec["gpu_count_min"], int)
    assert spec["gpu_count_min"] >= 1


def test_gpu_pool_priority_matches_the_provider_catalog_exactly() -> None:
    spec = load_runtime_json(MODEL_KEY)
    catalog = json.loads(CATALOG_SNAPSHOT.read_text(encoding="utf-8"))
    known_ids = {row["gpu_type_id"] for row in catalog["rows"]}
    unknown = [name for name in spec["gpu_pool_priority"] if name not in known_ids]
    assert unknown == [], f"gpu_pool_priority entries not in the catalog snapshot: {unknown}"


def test_gpu_pool_priority_puts_the_cheapest_available_pool_first() -> None:
    """RTX 4090 is community-available at $0.34/h; A40 is not community-available at
    all (catalog community_available=False), so on the default COMMUNITY cloud tier
    (arena/provider/runpod_pods.py PodSpec.cloud_type default) RTX 4090 is both the
    only one actually schedulable there and the cheaper of the two."""

    spec = load_runtime_json(MODEL_KEY)
    catalog = json.loads(CATALOG_SNAPSHOT.read_text(encoding="utf-8"))
    rows_by_id = {row["gpu_type_id"]: row for row in catalog["rows"]}
    pool = spec["gpu_pool_priority"]
    assert pool[0] == "NVIDIA GeForce RTX 4090"
    assert rows_by_id[pool[0]]["community_available"] is True


def test_per_page_timeout_seconds_is_a_sane_ceiling() -> None:
    spec = load_runtime_json(MODEL_KEY)
    # DeepSeek-OCR-2 has no TAVONEL speed measurement (masterplan section 5.1
    # covers OvisOCR2 only); 900s is a conservative canary ceiling, not a timing
    # claim, and stays far below the pod lifetime cap (D10: 2h canary / 6h full run).
    assert 1 <= spec["per_page_timeout_seconds"] <= 3600


# ---------------------------------------------- integration pass 11.3 hand-off ---


def _find_bash() -> str | None:
    """A real POSIX bash to run `bash -n` with.

    On Windows, ``shutil.which("bash")`` can resolve to the WSL launcher stub at
    C:\\Windows\\System32\\bash.exe, which fails with POSIX_PATH_NOT_FOUND when no
    WSL distribution is installed -- that is an environment gap, not a syntax
    verdict, so it must not be mistaken for one. Prefer actual Git Bash.
    """

    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("bash")
    if found and "System32" not in found:
        return found
    return None


_BASH = _find_bash()


def _read_script(name: str) -> str:
    return (runtime_dir(MODEL_KEY) / name).read_text(encoding="utf-8")


def test_bootstrap_never_downloads_the_bundle() -> None:
    # Explanatory comments are allowed to name ARENA_BUNDLE_URL (every fixed
    # runtimes/*/bootstrap.sh in this campaign does); what must be absent is the
    # script actually reading it or fetching/verifying/extracting a bundle archive.
    text = _read_script("bootstrap.sh")
    assert "${ARENA_BUNDLE_URL" not in text
    assert "${ARENA_BUNDLE_SHA256" not in text
    assert "arena-bundle.tar.gz" not in text
    assert "tar -xzf" not in text


def test_bootstrap_hands_off_to_entrypoint() -> None:
    text = _read_script("bootstrap.sh")
    assert text.rstrip().endswith('exec bash "${ARENA_ROOT}/runtime/entrypoint.sh"')


def test_entrypoint_execs_the_worker_server() -> None:
    text = _read_script("entrypoint.sh")
    assert "exec python" in text
    assert "arena.worker.server" in text


@pytest.mark.xfail(_BASH is None, reason="no usable bash on PATH to run bash -n with", run=False)
@pytest.mark.parametrize("script_name", ["bootstrap.sh", "entrypoint.sh"])
def test_shell_scripts_pass_bash_syntax_check(script_name: str) -> None:
    path = runtime_dir(MODEL_KEY) / script_name
    result = subprocess.run(
        [_BASH, "-n", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.xfail(_BASH is None, reason="no usable bash on PATH to run bash -n with", run=False)
def test_bash_syntax_check_actually_catches_a_broken_script(tmp_path: Path) -> None:
    """Failure-path proof for the two tests above: bash -n is not a no-op check."""

    broken = tmp_path / "broken.sh"
    broken.write_text(
        "#!/usr/bin/env bash\nif [[ true ]]; then\necho missing fi\n", encoding="utf-8"
    )
    result = subprocess.run(
        [_BASH, "-n", str(broken)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode != 0
    assert result.stderr.strip() != ""


def test_dockerfile_entrypoint_is_the_runtime_entrypoint_script() -> None:
    text = (runtime_dir(MODEL_KEY) / "Dockerfile").read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]' in text
    assert "COPY runtimes/deepseek_ocr2/ /opt/arena/runtime/" in text


def test_dockerfile_makes_the_hand_off_scripts_executable() -> None:
    text = (runtime_dir(MODEL_KEY) / "Dockerfile").read_text(encoding="utf-8")
    assert "chmod +x /opt/arena/runtime/entrypoint.sh" in text


# ---------------------------------------------- 11.5 second integration pass ---


def test_runtime_json_declares_prompt_kind_text() -> None:
    """D34: this adapter sends AdapterConfig.prompt_text and refuses an empty
    or incorrect one (test_load_refuses_a_prompt_that_is_not_the_official_one,
    test_load_refuses_an_empty_prompt below), so prompt_kind must be "text".
    """
    runtime_json = load_runtime_json(MODEL_KEY)
    assert runtime_json["prompt_kind"] == "text"


def test_load_refuses_an_empty_prompt(weights_dir: Path) -> None:
    """D34: prompt_kind "text" must refuse an empty prompt_text."""
    instance = adapter.DeepSeekOCR2Adapter(backend_factory=lambda cfg, path: FakeBackend())
    with pytest.raises(AdapterError) as excinfo:
        instance.load(make_config(weights_dir, prompt_text=""))
    assert excinfo.value.error_class == "MODEL_LOAD"


def test_dockerfile_copies_prompt_registry() -> None:
    """D17/D33: baked images must bundle the prompt registry directory so the
    worker can resolve ARENA_PROMPT_FILE without a bootstrap download."""
    text = (runtime_dir(MODEL_KEY) / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY prompt_registry/ /opt/arena/prompt_registry/" in text


def test_entrypoint_stays_in_process_no_server_to_poll() -> None:
    """D19: DeepSeek-OCR-2 is served in-process (Transformers AutoModel.infer),
    so there is no model server for entrypoint.sh to poll readiness on and
    `exec` (not a child-process wait/trap) is the correct hand-off."""
    text = _read_script("entrypoint.sh")
    assert "exec python" in text
    for marker in ("vllm serve", "paddlex serve", "wait $", "trap "):
        assert marker not in text


# =========================================================================
# 2026-09-03 GLM-OCR canary incident: fail fast and visibly, before a GPU
#
# The GLM-OCR canary reached the model-server start and died on a model_type its
# image's Transformers did not know; RunPod restarted the exited start command and
# the pod crash-looped while billing. These checks are string-level facts about the
# shipped scripts - no GPU, no network, no container runtime.
# =========================================================================


def test_bootstrap_carries_an_architecture_preflight_deepseek_ocr2() -> None:
    from incident_checks import assert_architecture_preflight

    assert_architecture_preflight("deepseek_ocr2")


def test_the_preflight_names_this_checkpoints_architecture_deepseek_ocr2() -> None:
    """A preflight that does not name what it expects would pass on any checkpoint."""
    from incident_checks import read_runtime_script

    text = read_runtime_script("deepseek_ocr2", "bootstrap.sh")
    assert 'EXPECTED_MODEL_TYPE = "deepseek_vl_v2"' in text
    assert 'EXPECTED_ARCH = "DeepseekOCR2ForCausalLM"' in text
    # model_type deepseek_vl_v2 is not transformers-native: it loads from auto_map
    assert "CONFIG_MAPPING_NAMES" in text
    assert "trust_remote_code=True" in text


def test_the_framework_floor_audit_is_recorded_deepseek_ocr2() -> None:
    """D: the audit result lives in provenance.json, and runtime.json's notes say so.

    It is not a top-level runtime.json field because runtime.schema.json is
    ``additionalProperties: false`` and belongs to another lane; loosening that
    schema to hold an audit record would be the wrong fix.
    """
    import json

    from incident_checks import load_runtime_json, runtime_dir

    provenance = json.loads(
        (runtime_dir("deepseek_ocr2") / "provenance.json").read_text(encoding="utf-8")
    )
    audit = provenance["framework_floor_audit"]
    for field in ("required", "image_ships", "action", "evidence"):
        assert audit[field], f"framework_floor_audit.{field} is empty"
    assert all(url.startswith("https://") for url in audit["evidence"])
    notes = load_runtime_json("deepseek_ocr2")["notes"]
    joined = " ".join(notes) if isinstance(notes, list) else notes
    assert "framework_floor_audit" in joined


def test_this_runtime_has_no_model_server_to_hold_deepseek_ocr2() -> None:
    """In-process inference: there is no separate server, so C is the preflight only."""
    from incident_checks import assert_no_model_server_to_hold

    assert_no_model_server_to_hold("deepseek_ocr2")
