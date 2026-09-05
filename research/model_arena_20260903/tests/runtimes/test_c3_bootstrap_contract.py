"""ARENA_CONTRACT section 11 cross-cutting checks for lane C3's four runtimes.

Section 11.2/11.3 (binding addendum, 2026-09-03 integration pass) changed three
things every C3 runtime must satisfy:

  * D5 -- runtime.json gains ``gpu_count_min`` (integer >= 1).
  * 11.3 item 4 -- ``bootstrap.sh`` never downloads the worker bundle and never
    requires ``ARENA_BUNDLE_URL``; the B2 bundle template has already extracted
    it to ``/opt/arena`` before calling bootstrap.sh.
  * 11.3 item 6 -- each Dockerfile's ``ENTRYPOINT`` points at ``entrypoint.sh``.

Section 11.5 (second integration pass) added four more, and they override 11.3(5):

  * D17 -- every Dockerfile copies ``prompt_registry/`` into the image.
  * D19 -- ``entrypoint.sh`` polls the model server's ``/v1/models`` until it
    answers with a deadline no shorter than 20 minutes, then runs the worker as a
    CHILD (never ``exec``) and propagates its exit code, with a trap that stops the
    server on any exit.
  * D33 -- ``bootstrap.sh`` refuses a pod asking for a revision runtime.json does
    not pin.
  * D34 -- ``runtime.json.prompt_kind`` matches the adapter's ``PROMPT_KIND``.

These are static/structural checks: no GPU, no network, no container runtime.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
from conftest import NAMESPACE_ROOT, load_runtime_json, load_runtime_module, runtime_dir
from incident_checks import (
    FATAL_LOG_PREFIX,
    FATAL_LOG_TAIL_LINES,
    assert_architecture_preflight,
    assert_sticky_model_server_failure,
    read_runtime_script,
)

MODEL_KEYS = ("infinity_parser2_pro", "monkeyocrv2_b", "olmocr2", "glm_ocr")

RUNTIME_SCHEMA = NAMESPACE_ROOT / "arena" / "core" / "schemas" / "runtime.schema.json"
PROMPT_REGISTRY = NAMESPACE_ROOT / "prompt_registry"

#: parsing/core_runner.py::ALL_PROMPT at runtime_revision d46699fb, verbatim. The
#: commented-out "Footnote" key in the source is not in the dict and is not here.
MONKEY_OFFICIAL_MAPPING = {
    "Caption": "Please output the text content from the image.",
    "END2END": (
        "List the document elements in reading order, including their categories, "
        "coordinates, and the content of each element."
    ),
    "Formula": "Please write out the expression of the formula in the image using LaTeX format.",
    "LAYOUT": (
        "Please output the categories and coordinates of the document elements "
        "in reading order."
    ),
    "List-item": "Please output the text content from the image.",
    "Page-footer": "Please output the text content from the image.",
    "Page-header": "Please output the text content from the image.",
    "Section-header": "Please output the text content from the image.",
    "Table": "Please extract the table from the image and represent it in OTSL format.",
    "Text": "Please output the text content from the image.",
    "Title": "Please output the text content from the image.",
}

#: D30: resolve bash by absolute path. ``bash`` on PATH under Windows is often the
#: WSL stub, which cannot read a D:\ path and reports a syntax error that is really a
#: missing file. Git for Windows ships a real bash at a known location.
BASH_FALLBACKS = (
    r"C:/Program Files/Git/usr/bin/bash.exe",
    r"C:/Program Files/Git/bin/bash.exe",
    r"C:/Program Files (x86)/Git/usr/bin/bash.exe",
)


def _resolve_bash() -> str | None:
    """Return an absolute bash that can actually parse a file, or None."""

    candidates = [shutil.which("bash"), *BASH_FALLBACKS]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "exit 0"],
                capture_output=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


BASH = _resolve_bash()
#: D30: xfail, never skip. A skip reads as "nothing to check here"; these checks are
#: required and an environment without bash has not run them.
requires_bash = pytest.mark.xfail(
    BASH is None,
    reason="D30: no usable bash found (PATH or Git for Windows); shell syntax unverified",
    raises=RuntimeError,
    strict=True,
)


def _bash_dash_n(path: Path) -> subprocess.CompletedProcess[str]:
    """Run ``bash -n <path>`` and return the completed process."""

    if BASH is None:
        raise RuntimeError("D30: no usable bash on this machine")
    return subprocess.run(
        [BASH, "-n", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )


# --------------------------------------------------------------- D5 runtime.json


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_gpu_count_min_is_a_positive_integer(model_key: str) -> None:
    spec = load_runtime_json(model_key)
    assert "gpu_count_min" in spec, f"{model_key}: D5 requires gpu_count_min"
    value = spec["gpu_count_min"]
    assert isinstance(value, int) and not isinstance(value, bool)
    assert value >= 1


def test_infinity_parser2_pro_gpu_count_min_is_two_for_tensor_parallel() -> None:
    """The model card's own --tensor-parallel-size 2 is why this is 2, not 1."""
    spec = load_runtime_json("infinity_parser2_pro")
    assert spec["gpu_count_min"] == 2
    assert spec["inference_config"]["tensor_parallel_size"] == 2


@pytest.mark.parametrize("model_key", ("monkeyocrv2_b", "olmocr2", "glm_ocr"))
def test_single_gpu_runtimes_have_gpu_count_min_one(model_key: str) -> None:
    spec = load_runtime_json(model_key)
    assert spec["gpu_count_min"] == 1
    assert spec["inference_config"]["tensor_parallel_size"] == 1


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_base_image_is_digest_pinned(model_key: str) -> None:
    spec = load_runtime_json(model_key)
    base_image = spec["base_image"]
    assert "@sha256:" in base_image
    digest = base_image.split("@sha256:", 1)[1]
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


# ---------------------------------------------------- 11.3 bootstrap hand-off


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_bootstrap_never_requires_arena_bundle_url(model_key: str) -> None:
    text = (runtime_dir(model_key) / "bootstrap.sh").read_text(encoding="utf-8")
    # The variable must not be referenced as shell syntax (${ARENA_BUNDLE_URL...).
    # A prose mention in a comment explaining that it is NOT required is fine.
    assert "${ARENA_BUNDLE_URL" not in text, (
        f"{model_key}: bootstrap.sh must not reference ARENA_BUNDLE_URL as a "
        "shell variable (11.3 item 4)"
    )


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_bootstrap_never_downloads_the_bundle(model_key: str) -> None:
    text = (runtime_dir(model_key) / "bootstrap.sh").read_text(encoding="utf-8")
    assert "arena-bundle.tar.gz" not in text
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "curl" not in stripped or "bundle" not in stripped.lower(), (
            f"{model_key}: bootstrap.sh line looks like a bundle download: {line!r}"
        )


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_bootstrap_execs_the_runtime_entrypoint(model_key: str) -> None:
    text = (runtime_dir(model_key) / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'exec "${RUNTIME_DIR}/entrypoint.sh"' in text or (
        "exec /opt/arena/runtime/entrypoint.sh" in text
    )


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_bootstrap_writes_the_bootstrap_receipt_and_pip_freeze(model_key: str) -> None:
    text = (runtime_dir(model_key) / "bootstrap.sh").read_text(encoding="utf-8")
    assert "/opt/arena/bootstrap-receipt.txt" in text
    assert "/opt/arena/bootstrap-pip-freeze.txt" in text


@pytest.mark.parametrize("model_key", MODEL_KEYS)
@requires_bash
def test_bootstrap_sh_is_syntactically_valid(model_key: str) -> None:
    path = runtime_dir(model_key) / "bootstrap.sh"
    result = _bash_dash_n(path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("model_key", MODEL_KEYS)
@requires_bash
def test_entrypoint_sh_is_syntactically_valid(model_key: str) -> None:
    path = runtime_dir(model_key) / "entrypoint.sh"
    result = _bash_dash_n(path)
    assert result.returncode == 0, result.stderr


# ----------------------------------- D19 readiness and process ownership


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_entrypoint_polls_the_model_server_before_the_worker(model_key: str) -> None:
    """All four C3 runtimes background a vLLM-family server, so all four poll it."""
    text = (runtime_dir(model_key) / "entrypoint.sh").read_text(encoding="utf-8")
    assert "wait_for_model_server()" in text, f"{model_key}: D19 needs a readiness poll"
    assert "READINESS_URL=" in text
    assert "/v1/models" in text
    assert 'if ! wait_for_model_server \\' in text, (
        f"{model_key}: the poll's failure must stop the pod"
    )


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_readiness_deadline_is_at_least_twenty_minutes(model_key: str) -> None:
    text = (runtime_dir(model_key) / "entrypoint.sh").read_text(encoding="utf-8")
    assert "READY_TIMEOUT_FLOOR_S=1200" in text, f"{model_key}: D19 floor is 20 minutes"
    match = re.search(r'READY_TIMEOUT_S="\$\{ARENA_MODEL_SERVER_READY_TIMEOUT_S:-(\d+)\}"', text)
    assert match is not None, f"{model_key}: no readiness deadline default"
    assert int(match.group(1)) >= 1200


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_entrypoint_runs_the_worker_as_a_child_and_propagates_its_exit_code(
    model_key: str,
) -> None:
    """D19: exec would discard the trap and orphan the model server."""
    text = (runtime_dir(model_key) / "entrypoint.sh").read_text(encoding="utf-8")
    assert "exec python3 -m arena.worker.server" not in text
    assert "python3 -m arena.worker.server &" in text
    assert "WORKER_PID=$!" in text
    assert 'wait "${WORKER_PID}"' in text
    assert "WORKER_STATUS=$?" in text
    assert 'exit "${WORKER_STATUS}"' in text
    assert "trap terminate EXIT INT TERM" in text


# -------------------------------------------------- D33 revision guard


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_bootstrap_refuses_a_pod_asking_for_another_revision(model_key: str) -> None:
    text = (runtime_dir(model_key) / "bootstrap.sh").read_text(encoding="utf-8")
    assert ': "${ARENA_MODEL_REVISION:?ARENA_MODEL_REVISION is required}"' in text
    assert '"${RUNTIME_DIR}/runtime.json"' in text, (
        f"{model_key}: D16 -- the pinned revision comes from runtime.json, not a literal"
    )
    assert "exit 64" in text


# ------------------------------------------------------- D17 / D34 prompts


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_dockerfile_copies_the_prompt_registry(model_key: str) -> None:
    text = (runtime_dir(model_key) / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY prompt_registry/ /opt/arena/prompt_registry/" in text


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_runtime_json_declares_a_prompt_kind(model_key: str) -> None:
    spec = load_runtime_json(model_key)
    assert spec["prompt_kind"] in {"text", "toolkit", "none"}
    assert spec["prompt_id"], "a prompt_kind without a prompt_id resolves to nothing"


@pytest.mark.parametrize(
    ("model_key", "expected"),
    (
        ("infinity_parser2_pro", "text"),
        ("monkeyocrv2_b", "toolkit"),
        ("olmocr2", "toolkit"),
        ("glm_ocr", "toolkit"),
    ),
)
def test_prompt_kind_matches_what_the_adapter_does(model_key: str, expected: str) -> None:
    """The declared kind and the adapter's own PROMPT_KIND constant must agree."""
    assert load_runtime_json(model_key)["prompt_kind"] == expected
    adapter = load_runtime_module(model_key, "adapter")
    assert expected == adapter.PROMPT_KIND


@pytest.mark.parametrize("model_key", ("monkeyocrv2_b", "olmocr2", "glm_ocr"))
def test_toolkit_runtimes_name_the_builder_they_hash(model_key: str) -> None:
    """D34: a toolkit runtime must point at the one call that produces the bytes."""
    adapter = load_runtime_module(model_key, "adapter")
    names = set(getattr(adapter, "__all__", ()))
    assert names & {
        "TOOLKIT_PROMPT_BUILDER",
        "TOOLKIT_PROMPT_SYMBOL",
        "build_official_prompt_text",
    }, f"{model_key}: nothing in __all__ names the prompt builder for lane R"


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_dockerfile_entrypoint_matches_11_3_item_6(model_key: str) -> None:
    text = (runtime_dir(model_key) / "Dockerfile").read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]' in text
    assert "COPY arena/ /opt/arena/arena/" in text
    assert f"COPY runtimes/{model_key}/ /opt/arena/runtime/" in text


# ----------------------------------------------------------- failure paths


def test_bundle_url_detector_actually_fires_on_the_old_pattern() -> None:
    """Prove the detector in test_bootstrap_never_requires_arena_bundle_url is not
    a tautology: it must reject the exact pattern the pre-11.3 scripts used."""
    old_pattern = 'BUNDLE_URL="${ARENA_BUNDLE_URL:?ARENA_BUNDLE_URL is required}"'
    assert "${ARENA_BUNDLE_URL" in old_pattern


def test_bundle_download_detector_actually_fires_on_the_old_pattern() -> None:
    old_line = (
        'curl --fail --silent --show-error --location --max-time 900 '
        '--output /tmp/arena-bundle.tar.gz "${BUNDLE_URL}"'
    )
    assert "curl" in old_line and "bundle" in old_line.lower()


@requires_bash
def test_bash_n_actually_rejects_broken_syntax(tmp_path: Path) -> None:
    broken = tmp_path / "broken.sh"
    broken.write_text(
        "#!/usr/bin/env bash\nif [ 1 -eq 1 ]; then\necho missing fi\n", encoding="utf-8"
    )
    result = _bash_dash_n(broken)
    assert result.returncode != 0


# =========================================================================
# Third pass (ARENA_CONTRACT 11.6, 2026-09-03)
# =========================================================================


# ------------------------------------------- runtime.json against its own schema


def test_runtime_schema_rejects_a_bad_prompt_kind() -> None:
    """Prove the schema check below is not a tautology before trusting it."""
    schema = json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8"))
    document = load_runtime_json("olmocr2")
    document["prompt_kind"] = "freeform"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_runtime_json_validates_against_the_runtime_schema(model_key: str) -> None:
    schema = json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(load_runtime_json(model_key), schema)


# ------------------------------------------------ D36 Infinity-Parser2-Pro


def test_infinity_parser2_pro_allows_bootstrap_via_a_volume_cache() -> None:
    """Founder decision 2026-09-03 supersedes D36's baked-only reversal.

    Baked-only was an operational choice about the 70.21 GB stall risk (masterplan
    15.1), not a licence one. The founder chose to keep bootstrap available behind a
    persistent RunPod network volume instead of forbidding it outright.
    """
    spec = load_runtime_json("infinity_parser2_pro")
    assert spec["weights_strategy"] == "volume_cache"
    assert spec["runtime_mode_allowed"] == ["baked", "bootstrap"]
    notes = " ".join(spec["notes"])
    assert "D36" in notes, "the reason for the mode change belongs in runtime.json"
    assert "70.21 GB" in notes and "15.1" in notes, (
        "D36's reason was the stall risk; the note must still name the size and the rule"
    )
    assert "--volume-gb" in notes, (
        "a bootstrap canary must pass the controller's --volume-gb flag so weights "
        "are cached on the volume rather than re-downloaded on every pod start"
    )


def test_infinity_parser2_pro_bakes_its_weights_into_the_image() -> None:
    """weights_strategy=baked is a claim about the Dockerfile, not only a label."""
    text = (runtime_dir("infinity_parser2_pro") / "Dockerfile").read_text(encoding="utf-8")
    assert "fetch_weights.py" in text, "a baked runtime fetches its weights at build time"
    assert "--weights-dir /opt/arena/weights/infinity_parser2_pro" in text
    assert "ARENA_WEIGHTS_DIR=/opt/arena/weights/infinity_parser2_pro" in text
    assert "ARENA_WEIGHTS_DIR=/workspace" not in text, (
        "D36: the checkpoint no longer lives on a network volume"
    )


def test_infinity_parser2_pro_bootstrap_refuses_a_mode_runtime_json_forbids() -> None:
    text = (runtime_dir("infinity_parser2_pro") / "bootstrap.sh").read_text(encoding="utf-8")
    assert "runtime_mode_allowed" in text, "the guard reads the file that owns the decision"
    assert "*,bootstrap,*" in text
    assert "D36" in text


@pytest.mark.parametrize("model_key", ("monkeyocrv2_b", "olmocr2", "glm_ocr"))
def test_the_other_three_still_allow_the_canary_bootstrap(model_key: str) -> None:
    """D36 is about one 70 GB checkpoint, not a blanket ban on bootstrap mode."""
    assert "bootstrap" in load_runtime_json(model_key)["runtime_mode_allowed"]


# --------------------------------- D34 toolkit mapping canonicalisation (section 2)


def _canonical(mapping: dict[str, str]) -> str:
    """ARENA_CONTRACT section 2 / 11.6 canonical JSON, no trailing newline."""
    return json.dumps(mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


#: A mapping no vendor ships: non-ASCII, out of key order, and carrying characters
#: that ensure_ascii=False would leave as raw UTF-8. The two renderings differ here,
#: which is the point of pinning the rule rather than inheriting today's ASCII luck.
FAKE_TOOLKIT_MAPPING = {
    "Text": "Please output the text content from the image.",
    "Formula": "Recognise the formula \u2014 \uc218\uc2dd\uc744 \uc77d\uc73c\uc2ed\uc2dc\uc624.",
    "Caption": "\u30ad\u30e3\u30d7\u30b7\u30e7\u30f3",
}


def test_the_fake_mapping_actually_separates_the_two_ensure_ascii_rules() -> None:
    """Without this, a pure-ASCII fixture would satisfy either rule and prove nothing."""
    loose = json.dumps(
        FAKE_TOOLKIT_MAPPING, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert loose != _canonical(FAKE_TOOLKIT_MAPPING)


def test_monkeyocrv2_b_renders_a_fake_toolkit_mapping_canonically() -> None:
    adapter = load_runtime_module("monkeyocrv2_b", "adapter")
    rendered = adapter.render_prompt_mapping(dict(FAKE_TOOLKIT_MAPPING))
    assert rendered == _canonical(FAKE_TOOLKIT_MAPPING)
    assert not rendered.endswith("\n")
    assert json.loads(rendered) == FAKE_TOOLKIT_MAPPING


@pytest.mark.parametrize("broken", ({}, {"Text": ""}, {"Text": None}))
def test_monkeyocrv2_b_refuses_a_toolkit_mapping_that_is_not_prompts(broken: object) -> None:
    """A toolkit that no longer carries the prompts is a dependency failure, never a
    reason to fall back to a prompt this adapter made up."""
    adapter = load_runtime_module("monkeyocrv2_b", "adapter")
    with pytest.raises(Exception) as caught:  # AdapterError from the worker package
        adapter.render_prompt_mapping(broken)
    assert "core_runner.ALL_PROMPT" in str(caught.value)


@pytest.mark.parametrize("model_key", ("monkeyocrv2_b", "glm_ocr"))
def test_registry_file_is_byte_identical_to_the_adapters_canonical_rendering(
    model_key: str,
) -> None:
    """D34 for a per-region mapping: the file lane R wrote and the bytes this adapter
    hashes at load must be the same bytes, or the check verifies nothing."""
    spec = load_runtime_json(model_key)
    adapter = load_runtime_module(model_key, "adapter")
    if model_key == "glm_ocr":
        mapping = dict(adapter.OFFICIAL_TASK_PROMPTS)
        built = adapter.build_official_prompt_text()
    else:
        mapping = dict(MONKEY_OFFICIAL_MAPPING)
        built = adapter.render_prompt_mapping(mapping)
    assert built == _canonical(mapping)
    registry_file = PROMPT_REGISTRY / f"{spec['prompt_id']}.txt"
    assert registry_file.read_bytes() == built.encode("utf-8")
    recorded = json.loads((PROMPT_REGISTRY / "sha256.json").read_text(encoding="utf-8"))
    assert recorded[spec["prompt_id"]] == "sha256:" + hashlib.sha256(
        built.encode("utf-8")
    ).hexdigest()


# --------------------------- D34: the declared prompt_sha256 is what is compared


@pytest.mark.parametrize("model_key", ("monkeyocrv2_b", "olmocr2", "glm_ocr"))
@pytest.mark.parametrize("spelling", ("sha256:{}", "{}", "SHA256:{}"))
def test_toolkit_adapters_read_adapter_config_prompt_sha256(
    model_key: str, spelling: str
) -> None:
    """D35: the field exists now, and both sha256 spellings normalise to one value."""
    adapter = load_runtime_module(model_key, "adapter")
    digest = "b" * 64
    cfg = SimpleNamespace(
        prompt_sha256=spelling.format(digest), prompt_text="", prompt_id="whatever"
    )
    assert adapter.registered_prompt_sha256(cfg) == digest


@pytest.mark.parametrize("model_key", ("monkeyocrv2_b", "olmocr2", "glm_ocr"))
def test_toolkit_adapters_refuse_when_nothing_pins_the_prompt(model_key: str) -> None:
    adapter = load_runtime_module(model_key, "adapter")
    cfg = SimpleNamespace(prompt_sha256=None, prompt_text="", prompt_id="whatever")
    with pytest.raises(Exception) as caught:
        adapter.registered_prompt_sha256(cfg)
    assert "neither prompt_sha256 nor prompt_text" in str(caught.value)


@pytest.mark.parametrize("model_key", ("monkeyocrv2_b", "olmocr2", "glm_ocr"))
def test_toolkit_adapters_hash_the_registry_text_when_the_field_is_unset(
    model_key: str,
) -> None:
    """AdapterConfig.prompt_sha256 is str | None. When the worker leaves it unset the
    only other pinned value is the registry file's own bytes -- the same number by
    construction, never the toolkit's own word for it."""
    adapter = load_runtime_module(model_key, "adapter")
    text = "the registry bytes"
    cfg = SimpleNamespace(prompt_sha256=None, prompt_text=text, prompt_id="whatever")
    assert adapter.registered_prompt_sha256(cfg) == hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


# =========================================================================
# 2026-09-03 GLM-OCR canary incident: fail fast and visibly, before a GPU
# =========================================================================

#: The C3 keys this pass owns. ``glm_ocr`` is excluded here on purpose: another
#: lane is editing that runtime in the same window, and a shared parametrisation
#: would turn its in-flight state into a failure of this file.
INCIDENT_KEYS = ("infinity_parser2_pro", "monkeyocrv2_b", "olmocr2")


@pytest.mark.parametrize("model_key", INCIDENT_KEYS)
def test_bootstrap_carries_an_architecture_preflight(model_key: str) -> None:
    assert_architecture_preflight(model_key)


@pytest.mark.parametrize("model_key", INCIDENT_KEYS)
def test_the_preflight_asks_the_vllm_registry_for_the_declared_architecture(
    model_key: str,
) -> None:
    """All three C3 runtimes are served by a vLLM-family engine, so the registry -
    not a version number - is what decides whether the checkpoint can be served."""
    text = read_runtime_script(model_key, "bootstrap.sh")
    assert "ModelRegistry.get_supported_archs()" in text
    assert "does not register" in text, (
        f"{model_key}: the failure message must name what the registry is missing"
    )


@pytest.mark.parametrize("model_key", INCIDENT_KEYS)
def test_the_preflight_runs_after_the_weights_it_reads(model_key: str) -> None:
    text = read_runtime_script(model_key, "bootstrap.sh")
    assert text.index("fetch_weights.py") < text.index('ARCH_PREFLIGHT="$(')


@pytest.mark.parametrize("model_key", INCIDENT_KEYS)
def test_entrypoint_makes_a_model_server_failure_sticky(model_key: str) -> None:
    assert_sticky_model_server_failure(model_key)


@pytest.mark.parametrize("model_key", INCIDENT_KEYS)
def test_the_readiness_failure_path_holds_instead_of_exiting(model_key: str) -> None:
    text = read_runtime_script(model_key, "entrypoint.sh")
    failure = text[text.index("if ! wait_for_model_server") :]
    branch = failure.split("fi", 1)[0]
    assert "fatal_and_hold" in branch, (
        f"{model_key}: the readiness failure still returns the pod to RunPod"
    )


def test_the_fatal_prefixes_are_the_ones_the_controller_condemns_on() -> None:
    """Not a literal copied by hand: read the contract out of the controller."""
    from arena.controller.run import FATAL_LOG_SIGNATURES, LOG_TAIL_LINES

    markers = {marker: error_class for marker, error_class in FATAL_LOG_SIGNATURES}
    assert markers[FATAL_LOG_PREFIX] == "MODEL_LOAD"
    assert LOG_TAIL_LINES == FATAL_LOG_TAIL_LINES
    for model_key in INCIDENT_KEYS:
        assert FATAL_LOG_PREFIX in read_runtime_script(model_key, "entrypoint.sh")
        # A preflight failure is a model-load failure too, and must be condemned
        # the same way rather than dying quietly inside bootstrap.sh.
        assert FATAL_LOG_PREFIX in read_runtime_script(model_key, "bootstrap.sh")


def test_the_preflight_detector_actually_fires_on_a_script_without_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure-path proof: assert_architecture_preflight is not a tautology.

    Point the helper's directory lookup at a runtime whose bootstrap.sh is the
    pre-incident script - installs, weights, hand-off, no preflight - and it must
    reject it."""
    import incident_checks

    fake = tmp_path / "fake_runtime"
    fake.mkdir()
    (fake / "bootstrap.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'python3 -m pip install --no-cache-dir "transformers==4.57.3"\n'
        'exec "${RUNTIME_DIR}/entrypoint.sh"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(incident_checks, "RUNTIMES_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="no architecture preflight block"):
        assert_architecture_preflight("fake_runtime")


def test_the_sticky_failure_detector_actually_fires_on_the_old_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-incident entrypoint exited 70, which is what RunPod restarted."""
    import incident_checks

    fake = tmp_path / "fake_runtime"
    fake.mkdir()
    (fake / "entrypoint.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nvllm serve /weights &\nVLLM_PID=$!\n"
        'if ! wait_for_model_server "${READINESS_URL}"; then\n    exit 70\nfi\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(incident_checks, "RUNTIMES_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="exiting is exactly what RunPod restarts"):
        assert_sticky_model_server_failure("fake_runtime")
