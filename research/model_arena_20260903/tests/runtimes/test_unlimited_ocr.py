"""Unlimited-OCR runtime tests.

Two things this runtime must never do quietly: run the long-horizon sidecar
prompt in the page lane, and pretend the Transformers path can see truncation.
Both are tested here.

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

MODEL_KEY = "unlimited_ocr"
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
            usage={},
            peak_vram_mb=8192,
        )

    def provenance(self) -> dict[str, Any]:
        return {"runtime": "fake", "image_mode": "gundam"}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def weights_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "weights"
    directory.mkdir()
    (directory / adapter.LARGEST_WEIGHT_FILE).write_bytes(b"not-real-weights")
    (directory / "config.json").write_text('{"model_type": "unlimited-ocr"}', encoding="utf-8")
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
        "prompt_id": "unlimited_ocr_document_parsing_v1",
        "prompt_text": adapter.OFFICIAL_PROMPT,
        "inference_config": {"base_size": 1024, "image_size": 640, "crop_mode": True},
        "inference_config_sha256": "sha256:" + "0" * 64,
    }
    values.update(overrides)
    return AdapterConfig(**values)


def loaded_adapter(weights_dir: Path, backend: FakeBackend) -> Any:
    instance = adapter.UnlimitedOCRAdapter(backend_factory=lambda cfg, path: backend)
    instance.load(make_config(weights_dir))
    return instance


def make_page(tmp_path: Path) -> tuple[PageInput, Path]:
    image = tmp_path / "page.png"
    write_synthetic_png(image)
    return (
        PageInput(
            inference_job_id="c" * 64,
            sample_id="olmocr:bench_data/pdfs/arxiv_math/2502.15977_pg21#p0",
            case_key="olmocr-bench-2502-15977-pg21",
            benchmark="olmocr",
            image_path=image,
            source_sha256=adapter._sha256_file(image),
            width=64,
            height=96,
            metadata={"page_index": 0, "media_type": "pdf"},
        ),
        image,
    )


# ------------------------------------------------------- page vs sidecar ----


def test_the_page_prompt_and_the_sidecar_prompt_are_distinct_and_pinned() -> None:
    assert adapter.OFFICIAL_PROMPT == "<image>document parsing."
    assert adapter.SIDECAR_MULTIPAGE_PROMPT == "<image>Multi page parsing."
    assert adapter._sha256_text(adapter.OFFICIAL_PROMPT) == adapter.PINNED_PROMPT_SHA256
    assert (
        adapter._sha256_text(adapter.SIDECAR_MULTIPAGE_PROMPT)
        == adapter.SIDECAR_MULTIPAGE_PROMPT_SHA256
    )
    assert adapter.PINNED_PROMPT_SHA256 != adapter.SIDECAR_MULTIPAGE_PROMPT_SHA256


def test_load_refuses_the_long_horizon_sidecar_prompt(weights_dir: Path) -> None:
    instance = adapter.UnlimitedOCRAdapter(backend_factory=lambda cfg, path: FakeBackend())
    with pytest.raises(AdapterError) as excinfo:
        instance.load(make_config(weights_dir, prompt_text=adapter.SIDECAR_MULTIPAGE_PROMPT))
    assert excinfo.value.error_class == "MODEL_LOAD"
    assert "long-horizon" in str(excinfo.value)


def test_load_refuses_any_other_prompt(weights_dir: Path) -> None:
    instance = adapter.UnlimitedOCRAdapter(backend_factory=lambda cfg, path: FakeBackend())
    with pytest.raises(AdapterError) as excinfo:
        instance.load(make_config(weights_dir, prompt_text="document parsing."))
    assert excinfo.value.error_class == "MODEL_LOAD"


# ----------------------------------------------------------- runtime.json ---


def test_runtime_json_matches_the_adapter_pins() -> None:
    spec = load_runtime_json(MODEL_KEY)
    assert spec["model_key"] == MODEL_KEY
    assert spec["model_key"] in GPU_MODEL_KEYS
    assert spec["model_repo"] == adapter.MODEL_REPO
    assert spec["model_revision"] == adapter.MODEL_REVISION
    weights = spec["weights"]
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
    assert spec["official_runtime"] == "transformers"
    assert "@sha256:" in spec["base_image"]
    assert spec["license"]["id"] == "MIT"
    assert all(url.startswith("https://") for url in spec["official_source_urls"])


def test_runtime_json_records_the_gundam_single_image_configuration() -> None:
    config = load_runtime_json(MODEL_KEY)["inference_config"]
    assert config["image_mode"] == "gundam"
    assert config["base_size"] == 1024
    assert config["image_size"] == 640
    assert config["crop_mode"] is True
    assert config["max_length"] == 32768
    assert config["no_repeat_ngram_size"] == 35
    assert config["ngram_window"] == 128
    assert config["temperature"] == 0.0


def test_runtime_json_is_valid_utf8_json_with_no_secret_shaped_strings() -> None:
    text = (runtime_dir(MODEL_KEY) / "runtime.json").read_text(encoding="utf-8")
    json.loads(text)
    for marker in ("rpa_", "sk-", "ghp_", "AKIA"):
        assert marker not in text


# --------------------------------------------------------- module hygiene ---


def test_module_imports_without_torch_or_transformers() -> None:
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules
    assert adapter.UnlimitedOCRAdapter.model_key == MODEL_KEY


# ---------------------------------------------------------------- weights ---


def test_weights_receipt_round_trips(weights_dir: Path) -> None:
    revision, manifest = adapter.verify_weights(
        weights_dir, expected_revision=adapter.MODEL_REVISION
    )
    assert revision == adapter.MODEL_REVISION
    assert manifest.startswith("sha256:")


def test_verify_weights_detects_a_tampered_file(weights_dir: Path) -> None:
    (weights_dir / adapter.LARGEST_WEIGHT_FILE).write_bytes(b"tampered")
    with pytest.raises(AdapterError) as excinfo:
        adapter.verify_weights(weights_dir, expected_revision=adapter.MODEL_REVISION)
    assert excinfo.value.error_class == "CHECKSUM"


def test_verify_weights_without_a_receipt_fails_model_load(tmp_path: Path) -> None:
    directory = tmp_path / "bare"
    directory.mkdir()
    with pytest.raises(AdapterError) as excinfo:
        adapter.verify_weights(directory, expected_revision=adapter.MODEL_REVISION)
    assert excinfo.value.error_class == "MODEL_LOAD"


# -------------------------------------------------------------- lifecycle ---


def test_load_returns_a_verified_receipt(weights_dir: Path) -> None:
    instance = adapter.UnlimitedOCRAdapter(backend_factory=lambda cfg, path: FakeBackend())
    receipt = instance.load(make_config(weights_dir))
    assert receipt.model_revision == adapter.MODEL_REVISION
    assert receipt.runtime_provenance["image_mode"] == "gundam"


def test_using_the_adapter_before_load_fails_closed(tmp_path: Path) -> None:
    instance = adapter.UnlimitedOCRAdapter(backend_factory=lambda cfg, path: FakeBackend())
    page, _ = make_page(tmp_path)
    with pytest.raises(AdapterError) as excinfo:
        instance.infer(page)
    assert excinfo.value.error_class == "MODEL_LOAD"


def test_infer_returns_the_raw_text_verbatim(weights_dir: Path, tmp_path: Path) -> None:
    raw_text = "<|det|>title [1, 2, 3, 4]<|/det|>Annual Report\n"
    backend = FakeBackend(text=raw_text)
    instance = loaded_adapter(weights_dir, backend)
    page, image = make_page(tmp_path)
    output = instance.infer(page)
    assert output.raw_text == raw_text
    assert output.output_format == "unlimited-ocr-det-markdown"
    assert output.peak_vram_mb == 8192
    assert backend.calls == [(image, adapter.OFFICIAL_PROMPT)]


def test_infer_does_not_claim_to_know_about_truncation(
    weights_dir: Path, tmp_path: Path
) -> None:
    # The Transformers path exposes no finish reason. Truncation must be absent,
    # not reported as "not truncated".
    instance = loaded_adapter(weights_dir, FakeBackend(text="a long page", finish_reason=None))
    page, _ = make_page(tmp_path)
    output = instance.infer(page)
    assert not any(warning.startswith("OUTPUT_TRUNCATED") for warning in output.warnings)
    assert output.semantic_error_class is None


def test_infer_flags_truncated_output_with_semantic_error_class(
    weights_dir: Path, tmp_path: Path
) -> None:
    instance = loaded_adapter(weights_dir, FakeBackend(text="partial", finish_reason="length"))
    page, _ = make_page(tmp_path)
    output = instance.infer(page)
    assert any(warning.startswith("OUTPUT_TRUNCATED") for warning in output.warnings)
    assert output.semantic_error_class == "OUTPUT_TRUNCATED"


def test_infer_flags_empty_output_without_raising(weights_dir: Path, tmp_path: Path) -> None:
    instance = loaded_adapter(weights_dir, FakeBackend(text="\n\n"))
    page, _ = make_page(tmp_path)
    output = instance.infer(page)
    assert any(warning.startswith("OUTPUT_EMPTY") for warning in output.warnings)
    assert output.semantic_error_class == "OUTPUT_EMPTY"


def test_infer_rejects_a_page_whose_bytes_do_not_match_the_job(
    weights_dir: Path, tmp_path: Path
) -> None:
    instance = loaded_adapter(weights_dir, FakeBackend())
    page, image = make_page(tmp_path)
    image.write_bytes(b"different bytes")
    with pytest.raises(AdapterError) as excinfo:
        instance.infer(page)
    assert excinfo.value.error_class == "CHECKSUM"


def test_infer_maps_an_oom_onto_the_taxonomy(weights_dir: Path, tmp_path: Path) -> None:
    instance = loaded_adapter(
        weights_dir, FakeBackend(raises=RuntimeError("CUDA out of memory. Tried to allocate"))
    )
    page, _ = make_page(tmp_path)
    with pytest.raises(AdapterError) as excinfo:
        instance.infer(page)
    assert excinfo.value.error_class == "CUDA_OOM"
    assert excinfo.value.error_class in ERROR_CLASSES


def test_an_unrecognised_failure_is_unknown_not_a_guess() -> None:
    assert adapter.classify_exception(ValueError("nothing anticipated this")) == "UNKNOWN"


def test_a_non_string_response_is_output_malformed(weights_dir: Path, tmp_path: Path) -> None:
    class BadBackend(FakeBackend):
        def generate(self, image_path: Path, prompt: str) -> Any:
            raise AdapterError("OUTPUT_MALFORMED", "infer returned NoneType, not str")

    instance = loaded_adapter(weights_dir, BadBackend())
    page, _ = make_page(tmp_path)
    with pytest.raises(AdapterError) as excinfo:
        instance.infer(page)
    assert excinfo.value.error_class == "OUTPUT_MALFORMED"


def test_warmup_and_close(weights_dir: Path, tmp_path: Path) -> None:
    backend = FakeBackend(text="warm")
    instance = loaded_adapter(weights_dir, backend)
    synthetic = tmp_path / "synthetic.png"
    write_synthetic_png(synthetic)
    receipt = instance.warmup(synthetic)
    assert receipt.output_chars == 4
    instance.close()
    assert backend.closed is True
    instance.close()


# -------------------------------------------------------- canonicalization ---


def _raw(text: str, *, warnings: tuple[str, ...] = ()) -> RawOutput:
    return RawOutput(
        raw_text=text,
        output_format="unlimited-ocr-det-markdown",
        native_json=None,
        usage={},
        timings_ms={"preprocess_ms": 0, "inference_ms": 0, "postprocess_ms": 0},
        warnings=warnings,
    )


RAW_HEADING_TABLE_FORMULA = (
    "<|det|>title [10, 20, 300, 60]<|/det|># Quarterly Report\n"
    "<|det|>table [10, 80, 500, 300]<|/det|><table><tr><td>A</td><td>B</td></tr></table>\n"
    "<|det|>equation [10, 320, 400, 360]<|/det|>$$E = mc^2$$\n"
)


def test_canonicalize_strips_det_markers_and_keeps_the_content() -> None:
    result = canonical.canonicalize(_raw(RAW_HEADING_TABLE_FORMULA))
    assert "# Quarterly Report" in result.markdown
    assert "<table><tr><td>A</td><td>B</td></tr></table>" in result.markdown
    assert "$$E = mc^2$$" in result.markdown
    assert "<|det|>" not in result.markdown
    assert result.elements is not None
    assert [element["category"] for element in result.elements] == ["title", "table", "equation"]
    assert result.elements[0]["det_raw"] == "[10, 20, 300, 60]"
    assert result.lossy is True


def test_canonicalize_drops_image_blocks_the_way_the_official_function_does() -> None:
    raw = (
        "<|det|>text [0, 0, 1, 1]<|/det|>before\n"
        "<|det|>image [2, 2, 3, 3]<|/det|>\n"
        "after\n"
    )
    result = canonical.canonicalize(_raw(raw))
    # The official remove_det skips an image marker without flushing the block it
    # is building, so "after" joins the "before" block instead of starting a new
    # one. Reproduced on purpose.
    assert result.markdown == "before\nafter"
    assert result.elements is not None
    assert result.elements[1]["category"] == "image"
    assert result.elements[1]["dropped_from_markdown"] is True
    assert any("does not flush" in note for note in result.conversion_notes)


def test_canonicalize_of_empty_output_is_empty_not_invented() -> None:
    result = canonical.canonicalize(_raw("\n \n"))
    assert result.markdown == ""
    assert result.elements == ()
    assert result.lossy is False
    assert result.conversion_notes == ("empty model output preserved as empty markdown",)


def test_canonicalize_preserves_a_truncated_page() -> None:
    truncated = "<|det|>table [0, 0, 1, 1]<|/det|><table><tr><td>A</td><td>B</td></tr><tr><td>C"
    result = canonical.canonicalize(_raw(truncated, warnings=("OUTPUT_EMPTY: none",)))
    assert result.markdown.endswith("<tr><td>C")
    assert any("adapter warning: OUTPUT_EMPTY" in note for note in result.conversion_notes)


def test_the_official_regex_does_not_match_a_nested_bbox() -> None:
    # DET_RE's [^\]]* stops at the first "]", so the card's function only handles
    # the single-bracket shape it documents. A nested bbox survives into the
    # markdown. This is upstream behaviour, reproduced, and the canary has to
    # check which shape this model actually emits.
    nested = "<|det|>title [[1, 2, 3, 4]]<|/det|>Heading\n"
    assert canonical.remove_det(nested) == nested.strip()
    assert canonical.det_elements(nested) == ()


def test_remove_det_on_a_page_without_markers_only_reflows_blank_lines() -> None:
    raw = "line one\n\nline two\n"
    assert canonical.remove_det(raw) == "line one\nline two"
    result = canonical.canonicalize(_raw(raw))
    assert result.lossy is True
    assert any("paragraph breaks" in note for note in result.conversion_notes)


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
    spec = load_runtime_json(MODEL_KEY)
    catalog = json.loads(CATALOG_SNAPSHOT.read_text(encoding="utf-8"))
    rows_by_id = {row["gpu_type_id"]: row for row in catalog["rows"]}
    pool = spec["gpu_pool_priority"]
    assert pool[0] == "NVIDIA GeForce RTX 4090"
    assert rows_by_id[pool[0]]["community_available"] is True


def test_per_page_timeout_seconds_is_a_sane_ceiling() -> None:
    spec = load_runtime_json(MODEL_KEY)
    # No TAVONEL speed measurement exists for this model; 900s is a conservative
    # canary ceiling the canary itself is expected to tighten.
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
    assert "COPY runtimes/unlimited_ocr/ /opt/arena/runtime/" in text


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
    instance = adapter.UnlimitedOCRAdapter(backend_factory=lambda cfg, path: FakeBackend())
    with pytest.raises(AdapterError) as excinfo:
        instance.load(make_config(weights_dir, prompt_text=""))
    assert excinfo.value.error_class == "MODEL_LOAD"


def test_dockerfile_copies_prompt_registry() -> None:
    """D17/D33: baked images must bundle the prompt registry directory so the
    worker can resolve ARENA_PROMPT_FILE without a bootstrap download."""
    text = (runtime_dir(MODEL_KEY) / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY prompt_registry/ /opt/arena/prompt_registry/" in text


def test_entrypoint_stays_in_process_no_server_to_poll() -> None:
    """D19: Unlimited-OCR is served in-process (Transformers AutoModel.infer),
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


def test_bootstrap_carries_an_architecture_preflight_unlimited_ocr() -> None:
    from incident_checks import assert_architecture_preflight

    assert_architecture_preflight("unlimited_ocr")


def test_the_preflight_names_this_checkpoints_architecture_unlimited_ocr() -> None:
    """A preflight that does not name what it expects would pass on any checkpoint."""
    from incident_checks import read_runtime_script

    text = read_runtime_script("unlimited_ocr", "bootstrap.sh")
    assert 'EXPECTED_MODEL_TYPE = "unlimited-ocr"' in text
    assert 'EXPECTED_ARCH = "UnlimitedOCRForCausalLM"' in text
    assert "CONFIG_MAPPING_NAMES" in text
    assert "trust_remote_code=True" in text


def test_the_framework_floor_audit_is_recorded_unlimited_ocr() -> None:
    """D: the audit result lives in provenance.json, and runtime.json's notes say so.

    It is not a top-level runtime.json field because runtime.schema.json is
    ``additionalProperties: false`` and belongs to another lane; loosening that
    schema to hold an audit record would be the wrong fix.
    """
    import json

    from incident_checks import load_runtime_json, runtime_dir

    provenance = json.loads(
        (runtime_dir("unlimited_ocr") / "provenance.json").read_text(encoding="utf-8")
    )
    audit = provenance["framework_floor_audit"]
    for field in ("required", "image_ships", "action", "evidence"):
        assert audit[field], f"framework_floor_audit.{field} is empty"
    assert all(url.startswith("https://") for url in audit["evidence"])
    notes = load_runtime_json("unlimited_ocr")["notes"]
    joined = " ".join(notes) if isinstance(notes, list) else notes
    assert "framework_floor_audit" in joined


def test_this_runtime_has_no_model_server_to_hold_unlimited_ocr() -> None:
    """In-process inference: there is no separate server, so C is the preflight only."""
    from incident_checks import assert_no_model_server_to_hold

    assert_no_model_server_to_hold("unlimited_ocr")
