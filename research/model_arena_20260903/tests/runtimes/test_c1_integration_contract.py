"""Lane C1 integration-pass contract (ARENA_CONTRACT.md section 11).

One file for the four C1 runtimes so the section-11 rules are stated once and
every runtime is held to the same text: D5 (gpu_count_min, digest-pinned base
image), D9 (gpu_pool_priority against the provider catalog snapshot), D13
(per-page ceiling), and section 11.3 (bootstrap never fetches the bundle,
entrypoint.sh is the single start path in both modes).

Every check here reads files. Nothing starts a pod, spends money, or touches a
runtime outside this lane. Each rule that could silently pass is paired with a
failure-path test proving the check actually rejects the broken case.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

NAMESPACE_ROOT: Final = Path(__file__).resolve().parents[2]
RUNTIMES_ROOT: Final = NAMESPACE_ROOT / "runtimes"
CATALOG_SNAPSHOT: Final = (
    NAMESPACE_ROOT / "receipts" / "provider_receipts" / "catalog-20260903T063539Z.json"
)
RUNTIME_SCHEMA: Final = NAMESPACE_ROOT / "arena" / "core" / "schemas" / "runtime.schema.json"

C1_MODEL_KEYS: Final = ("paddleocr_vl_1_6", "hpd_parsing", "mineru_pipeline", "mineru_vlm")

DIGEST_PINNED: Final = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
# ARENA_CONTRACT section 9: reject strings that look like a live credential.
# Prefix alone is not enough - real paths and package names contain "hf_".
SECRET_LITERALS: Final = (
    re.compile(r"rpa_[A-Za-z0-9]{16,}"),
    re.compile(r"hf_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
SEMANTIC_ERROR_CLASSES: Final = frozenset(
    {"OUTPUT_EMPTY", "OUTPUT_TRUNCATED", "OUTPUT_REPETITION", "OUTPUT_MALFORMED"}
)
# D13: a per-page ceiling, not a shard budget. One minute is the floor below
# which a slow first page would be killed; half an hour is a page, not a run.
PER_PAGE_TIMEOUT_BOUNDS: Final = (60, 1800)

# D34: which of the three prompt disciplines each C1 runtime follows. The
# adapter is the authority; runtime.json must agree with it and lane R's
# prompt_registry file is written from it.
EXPECTED_PROMPT_KIND: Final = {
    "paddleocr_vl_1_6": "none",
    "hpd_parsing": "text",
    "mineru_pipeline": "none",
    "mineru_vlm": "none",
}
VALID_PROMPT_KINDS: Final = frozenset({"text", "toolkit", "none"})

# D19: which C1 runtimes start a model server. paddleocr genai_server and the
# customized vLLM of HPD-Parsing are model servers; both MinerU backends run
# in-process through do_parse and start nothing.
SERVER_RUNTIMES: Final = ("paddleocr_vl_1_6", "hpd_parsing")
IN_PROCESS_RUNTIMES: Final = ("mineru_pipeline", "mineru_vlm")
# D19 readiness floor: twenty minutes.
READY_DEADLINE_FLOOR_SECONDS: Final = 1200


def resolve_bash() -> str | None:
    """D30: resolve bash by absolute path, not by whatever PATH holds.

    On this host a broken WSL ``bash.exe`` shadows Git-for-Windows on the PATH
    a subprocess inherits, so ``shutil.which`` alone is not enough. The Git
    locations are checked as well, and a candidate has to actually run.
    """
    candidates = [shutil.which("bash")]
    candidates += [
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
        "/usr/bin/bash",
        "/bin/bash",
    ]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "exit 0"], capture_output=True, check=False, timeout=30
            )
        except OSError:
            continue
        if probe.returncode == 0:
            return candidate
    return None


BASH: Final = resolve_bash()
# D30: a missing bash is an xfail, never a silent skip - a skipped shell-syntax
# gate reads as "checked" in a summary line when nothing was checked.
NO_BASH_XFAIL: Final = pytest.mark.xfail(
    BASH is None,
    reason="D30: no usable bash on this host, so the shell-syntax gate could not run",
    strict=False,
    run=False,
)


def runtime_dir(model_key: str) -> Path:
    return RUNTIMES_ROOT / model_key


def load_runtime_module(model_key: str, module_name: str) -> ModuleType:
    """Import ``runtimes/<model_key>/<module_name>.py`` under a collision-free name.

    Same ``sys.modules`` key convention as tests/runtimes/conftest.py, so a
    module already loaded by a per-runtime test is reused rather than executed
    a second time under a different name.
    """
    qualified = f"arena_runtime_{model_key}_{module_name}"
    cached = sys.modules.get(qualified)
    if cached is not None:
        return cached
    path = runtime_dir(model_key) / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(qualified, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(qualified, None)
        raise
    return module


def read_runtime_json(model_key: str) -> dict[str, Any]:
    loaded: Any = json.loads((runtime_dir(model_key) / "runtime.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def read_text(model_key: str, name: str) -> str:
    return (runtime_dir(model_key) / name).read_text(encoding="utf-8")


def executable_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def catalog_gpu_ids() -> frozenset[str]:
    """Exact provider ids from the B1 catalog snapshot (D9)."""
    snapshot: Any = json.loads(CATALOG_SNAPSHOT.read_text(encoding="utf-8"))
    rows = snapshot["rows"]
    assert isinstance(rows, list) and rows
    return frozenset(str(row["gpu_type_id"]) for row in rows)


def bash_syntax_check(path: Path) -> subprocess.CompletedProcess[str]:
    assert BASH is not None, "bash is required for this test"
    return subprocess.run(
        [BASH, "-n", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# --------------------------------------------------------------------------- #
# D5 - runtime.json
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_gpu_count_min_is_present_and_at_least_one(model_key: str) -> None:
    value = read_runtime_json(model_key).get("gpu_count_min")
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{model_key}: gpu_count_min must be an integer, got {value!r}"
    )
    assert value >= 1


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_gpu_count_min_is_one_for_every_single_device_runtime(model_key: str) -> None:
    # No C1 runtime uses tensor parallelism; the multi-device case in this
    # campaign is infinity_parser2_pro, which is lane C3's.
    assert read_runtime_json(model_key)["gpu_count_min"] == 1


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_base_image_is_digest_pinned(model_key: str) -> None:
    base_image = read_runtime_json(model_key)["base_image"]
    assert DIGEST_PINNED.fullmatch(base_image), (
        f"{model_key}: base_image is not digest-pinned: {base_image!r}"
    )


def test_the_digest_pattern_rejects_a_floating_tag() -> None:
    """Failure-path proof that the check above is not vacuous."""
    assert not DIGEST_PINNED.fullmatch("registry.example/repo:latest")
    assert not DIGEST_PINNED.fullmatch("registry.example/repo@sha256:abc")
    assert DIGEST_PINNED.fullmatch("registry.example/repo:tag@sha256:" + "a" * 64)


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_runtime_json_validates_against_the_frozen_schema(model_key: str) -> None:
    import jsonschema

    schema = json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8"))
    properties = schema.get("properties", {})
    missing = [
        field
        for field in ("prompt_kind", "runtime_repository", "runtime_revision")
        if field not in properties
    ]
    if missing and schema.get("additionalProperties") is False:
        # D34 and D16 add these fields to runtime.json; the schema is lane A1's
        # file and this lane must not edit it. Until A1 lands them the closed
        # schema rejects a correct runtime.json, so this is an expected failure
        # with the reason named - not a skip, and not a weakened assertion.
        pytest.xfail(
            "arena/core/schemas/runtime.schema.json (lane A1) does not yet declare "
            f"{missing} required by ARENA_CONTRACT D34/D16"
        )
    validator = jsonschema.Draft202012Validator(schema)
    failures = [error.json_path for error in validator.iter_errors(read_runtime_json(model_key))]
    assert failures == [], f"{model_key}: schema failures {failures}"


# --------------------------------------------------------------------------- #
# D34 - prompt_kind, and D16 - runtime repository vs weights repository
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_runtime_json_declares_a_valid_prompt_kind(model_key: str) -> None:
    document = read_runtime_json(model_key)
    assert "prompt_kind" in document, f"{model_key}: runtime.json has no prompt_kind (D34)"
    assert document["prompt_kind"] in VALID_PROMPT_KINDS
    assert document["prompt_kind"] == EXPECTED_PROMPT_KIND[model_key]


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_prompt_kind_matches_what_the_adapter_actually_does(model_key: str) -> None:
    """runtime.json's prompt_kind is checked against the adapter, not trusted.

    The adapter carries the same value as a module-level constant and the two
    have to agree, so a runtime.json edit alone can never silently re-label how
    a model is prompted.
    """
    module = load_runtime_module(model_key, "adapter")
    declared = read_runtime_json(model_key)["prompt_kind"]
    assert getattr(module, "PROMPT_KIND", None) == declared, (
        f"{model_key}: adapter.PROMPT_KIND disagrees with runtime.json prompt_kind"
    )
    source = read_text(model_key, "adapter.py")
    if declared == "none":
        # The adapter must refuse a non-empty prompt outright.
        assert "if cfg.prompt_text:" in source, (
            f"{model_key}: prompt_kind 'none' but the adapter does not refuse a prompt"
        )
        assert module.OFFICIAL_PROMPT == ""
    elif declared == "text":
        # The adapter sends AdapterConfig.prompt_text and refuses an empty one.
        assert "cfg.prompt_text" in source
        assert isinstance(module.OFFICIAL_PROMPT, str) and module.OFFICIAL_PROMPT
    else:  # toolkit
        assert "prompt_sha256" in source


@pytest.mark.parametrize(
    "model_key", [key for key, kind in EXPECTED_PROMPT_KIND.items() if kind == "none"]
)
def test_a_none_prompt_adapter_refuses_a_non_empty_prompt_text(model_key: str) -> None:
    """Failure path: the refusal is real, not a comment."""
    module = load_runtime_module(model_key, "adapter")
    document = read_runtime_json(model_key)
    from arena.worker.adapter_api import AdapterConfig, AdapterError

    cfg = AdapterConfig(
        model_key=model_key,
        model_repo=str(document["model_repo"]),
        model_revision=str(document["model_revision"]),
        weights_dir=Path("/nonexistent/weights"),
        prompt_id=str(document["prompt_id"]),
        prompt_text="convert this page to markdown",
        inference_config=document["inference_config"],
        inference_config_sha256="sha256:" + "0" * 64,
        max_concurrency=1,
    )
    with pytest.raises(AdapterError) as raised:
        module.create_adapter().load(cfg)
    assert raised.value.error_class == "MODEL_LOAD"


def test_hpd_parsing_sends_the_prompt_text_it_was_configured_with() -> None:
    """D34 prompt_kind 'text': the request body carries AdapterConfig.prompt_text."""
    module = load_runtime_module("hpd_parsing", "adapter")
    config = read_runtime_json("hpd_parsing")["inference_config"]
    body = module.build_request_body("QUJD", config, module.OFFICIAL_PROMPT)
    parts = body["messages"][0]["content"]
    texts = [part["text"] for part in parts if part.get("type") == "text"]
    assert texts == [module.OFFICIAL_PROMPT]
    # An empty prompt is refused rather than sent.
    from arena.worker.adapter_api import AdapterError

    with pytest.raises(AdapterError):
        module.build_request_body("QUJD", config, "")


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_prompt_id_is_unchanged_and_is_a_single_filesystem_safe_name(model_key: str) -> None:
    """Lane R writes prompt_registry/<prompt_id>.txt; the id must resolve to a file."""
    expected = {
        "paddleocr_vl_1_6": "paddleocr_vl_1_6_pipeline_internal",
        "hpd_parsing": "hpd_parsing_document_parsing_with_fork_v1",
        "mineru_pipeline": "mineru_pipeline_no_prompt",
        "mineru_vlm": "mineru_vlm_no_prompt",
    }
    prompt_id = read_runtime_json(model_key)["prompt_id"]
    assert prompt_id == expected[model_key], f"{model_key}: prompt_id changed"
    assert re.fullmatch(r"[a-z0-9_]+", prompt_id)


@pytest.mark.parametrize("model_key", ("paddleocr_vl_1_6", "mineru_pipeline", "mineru_vlm"))
def test_runtime_json_names_the_runtime_code_repository(model_key: str) -> None:
    """D16: model_repo is the weights; runtime_repository is the code."""
    document = read_runtime_json(model_key)
    provenance = json.loads(read_text(model_key, "provenance.json"))
    assert document["runtime_repository"] == provenance["runtime_source_repository"]
    assert document["runtime_revision"] == provenance["runtime_source_revision"]
    assert document["runtime_repository"] != document["model_repo"]
    assert re.fullmatch(r"[0-9a-f]{40}", str(document["runtime_revision"]))


def test_mineru_pipeline_separates_the_weights_repo_from_the_runtime_repo() -> None:
    """The exact disagreement D16 names: registry said MinerU, runtime.json said PDF-Extract-Kit.

    Both are right about different things. The weights are PDF-Extract-Kit-1.0;
    the runtime code is MinerU. runtime.json now carries both, so the registry
    can copy each into the field it belongs in instead of choosing one.
    """
    document = read_runtime_json("mineru_pipeline")
    assert document["model_repo"] == "opendatalab/PDF-Extract-Kit-1.0"
    assert document["model_revision"] == "ed6b654c018d742e65a17671e379c5e6ecc87ec9"
    assert document["runtime_repository"] == "opendatalab/MinerU"
    assert document["runtime_revision"] == "fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883"
    assert document["weights"]["repo"] == document["model_repo"]


def test_hpd_parsing_has_no_invented_runtime_repository() -> None:
    """The customized vLLM fork is published only as an image; no source repo exists."""
    document = read_runtime_json("hpd_parsing")
    assert "runtime_repository" not in document
    provenance = json.loads(read_text("hpd_parsing", "provenance.json"))
    assert provenance.get("runtime_source_repository") is None
    assert "customized vLLM fork" in document["notes"]


# --------------------------------------------------------------------------- #
# D9 - gpu_pool_priority against the provider catalog snapshot
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_every_gpu_pool_entry_is_an_exact_catalog_id(model_key: str) -> None:
    known = catalog_gpu_ids()
    pools = read_runtime_json(model_key)["gpu_pool_priority"]
    assert isinstance(pools, list) and pools
    unknown = [name for name in pools if name not in known]
    assert unknown == [], (
        f"{model_key}: gpu_pool_priority names {unknown} which are not exact ids in "
        f"{CATALOG_SNAPSHOT.name}"
    )


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_no_gpu_pool_entry_is_duplicated(model_key: str) -> None:
    pools = read_runtime_json(model_key)["gpu_pool_priority"]
    assert len(pools) == len(set(pools)), f"{model_key}: duplicate pool entries in {pools}"


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_every_gpu_pool_entry_meets_the_declared_vram_floor(model_key: str) -> None:
    snapshot: Any = json.loads(CATALOG_SNAPSHOT.read_text(encoding="utf-8"))
    memory_by_id = {str(row["gpu_type_id"]): int(row["memory_gb"]) for row in snapshot["rows"]}
    document = read_runtime_json(model_key)
    floor = document["gpu_min_vram_gb"]
    too_small = [
        name for name in document["gpu_pool_priority"] if memory_by_id.get(name, 0) < floor
    ]
    assert too_small == [], (
        f"{model_key}: {too_small} are below gpu_min_vram_gb={floor} in the catalog snapshot"
    )


def test_the_catalog_check_rejects_a_name_that_is_not_in_the_snapshot() -> None:
    """Failure-path proof: a plausible-looking wrong name must not pass."""
    known = catalog_gpu_ids()
    assert "NVIDIA GeForce RTX 4090" in known
    for invented in ("RTX 4090", "NVIDIA RTX 4090", "A40", "nvidia a40", "H100"):
        assert invented not in known


# --------------------------------------------------------------------------- #
# D13 - per-page ceiling
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_per_page_timeout_is_a_sane_per_page_ceiling(model_key: str) -> None:
    low, high = PER_PAGE_TIMEOUT_BOUNDS
    value = read_runtime_json(model_key)["per_page_timeout_seconds"]
    assert isinstance(value, int) and low <= value <= high, (
        f"{model_key}: per_page_timeout_seconds={value} is outside [{low}, {high}]"
    )


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_a_slower_runtime_does_not_get_a_shorter_page_budget(model_key: str) -> None:
    # The two MinerU lanes run a whole document pipeline per page and carry the
    # larger ceiling; the two server-backed lanes answer one request per page.
    document = read_runtime_json(model_key)
    expected = 900 if model_key.startswith("mineru_") else 600
    assert document["per_page_timeout_seconds"] == expected


# --------------------------------------------------------------------------- #
# Section 11.3 - bootstrap hand-off
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_bootstrap_never_fetches_the_bundle(model_key: str) -> None:
    text = read_text(model_key, "bootstrap.sh")
    assert "ARENA_BUNDLE_URL" not in text, f"{model_key}: bootstrap.sh still names ARENA_BUNDLE_URL"
    assert "arena-bundle" not in text, f"{model_key}: bootstrap.sh still handles the bundle archive"
    for line in executable_lines(text):
        assert "curl" not in line, (
            f"{model_key}: bootstrap.sh still curls something: {line.strip()}"
        )
        assert "tar -xzf" not in line, f"{model_key}: bootstrap.sh still extracts an archive"


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_bootstrap_writes_the_receipt_the_contract_names(model_key: str) -> None:
    text = read_text(model_key, "bootstrap.sh")
    assert "/opt/arena/bootstrap-pip-freeze.txt" in text.replace(
        '"${ARENA_ROOT}/bootstrap-pip-freeze.txt"', "/opt/arena/bootstrap-pip-freeze.txt"
    ) or "bootstrap-pip-freeze.txt" in text
    for field in ("campaign_id=", "model_key=", "base_image=", "base_image_digest=",
                  "pip_freeze_sha256="):
        assert field in text, f"{model_key}: bootstrap receipt is missing {field!r}"
    assert 'RECEIPT="${ARENA_ROOT}/bootstrap-receipt.txt"' in text


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_bootstrap_pins_weights_by_revision_and_sha256_without_a_token(model_key: str) -> None:
    text = read_text(model_key, "bootstrap.sh")
    # D59: mineru_pipeline fetches weights through huggingface_hub.snapshot_download
    # (revision=os.environ[...]) rather than the `hf download --revision` CLI, after
    # the CLI's repeated --include flags (argparse nargs="*", not action="append")
    # silently dropped every pattern but the last one on a real canary.
    assert "--revision" in text or 'revision=os.environ["ARENA_MODEL_REVISION"]' in text
    assert "sha256sum -c" in text
    assert "HF_HUB_DISABLE_IMPLICIT_TOKEN=1" in text, (
        f"{model_key}: weights must be fetched from the public repository with no token"
    )
    for marker in ("HF_TOKEN", "hf auth login"):
        assert marker not in text, f"{model_key}: bootstrap.sh names {marker!r}"
    # Secret-shaped literals, not merely the prefixes: a weights path such as
    # models/MFR/unimernet_hf_small_2503 legitimately contains "hf_".
    for pattern in SECRET_LITERALS:
        assert not pattern.search(text), f"{model_key}: bootstrap.sh carries {pattern.pattern}"


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_bootstrap_never_upgrades_a_pinned_package(model_key: str) -> None:
    for line in executable_lines(read_text(model_key, "bootstrap.sh")):
        assert "pip install -U" not in line
        assert "--upgrade" not in line


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_bootstrap_hands_over_to_the_runtime_entrypoint(model_key: str) -> None:
    text = read_text(model_key, "bootstrap.sh")
    assert 'exec "${RUNTIME_DIR}/entrypoint.sh"' in text
    assert 'RUNTIME_DIR="${ARENA_RUNTIME_DIR:-${ARENA_ROOT}/runtime}"' in text
    # Fail closed: a bundle laid out the old way must not limp along.
    assert 'if [ ! -f "${RUNTIME_DIR}/entrypoint.sh" ]; then' in text
    # The worker server is started by entrypoint.sh, never twice.
    assert "arena.worker.server" not in text


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_entrypoint_starts_the_worker_server(model_key: str) -> None:
    text = read_text(model_key, "entrypoint.sh")
    assert '"${PYTHON_BIN}" -m arena.worker.server' in text
    assert 'export ARENA_RUNTIME_DIR="${ARENA_RUNTIME_DIR:-/opt/arena/runtime}"' in text
    assert 'export PYTHONPATH="${PYTHONPATH:-/opt/arena}"' in text
    # Every runtime-internal path goes through /opt/arena/runtime/..., so the
    # baked image and the bootstrap path share one lookup rule.
    assert "${ARENA_RUNTIME_DIR}/${required}" in text


@pytest.mark.parametrize("model_key", IN_PROCESS_RUNTIMES)
def test_an_in_process_runtime_still_execs_the_worker(model_key: str) -> None:
    """D19 keeps `exec` where there is no server process to trap."""
    text = read_text(model_key, "entrypoint.sh")
    assert 'exec "${PYTHON_BIN}" -m arena.worker.server' in text
    for forbidden in ("vllm serve", "genai_server", "--print-server-plan"):
        assert forbidden not in text, f"{model_key}: entrypoint starts a server it does not have"


# --------------------------------------------------------------------------- #
# D19 - model-server readiness and process ownership
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model_key", SERVER_RUNTIMES)
def test_server_entrypoint_renders_its_launch_plan_from_the_adapter(model_key: str) -> None:
    text = read_text(model_key, "entrypoint.sh")
    assert '"${ARENA_RUNTIME_DIR}/adapter.py" --print-server-plan' in text, (
        f"{model_key}: entrypoint.sh does not render the server command from adapter.py"
    )
    # A plan that came back empty must stop the container, not start a worker
    # that will fail one page at a time.
    assert "produced no model-server plan" in text
    assert 'if [ "${#SERVER_ARGV[@]}" -eq 0 ]' in text


@pytest.mark.parametrize("model_key", SERVER_RUNTIMES)
def test_server_entrypoint_polls_readiness_with_a_deadline_and_fails_hard(
    model_key: str,
) -> None:
    text = read_text(model_key, "entrypoint.sh")
    assert "until probe_once; do" in text, f"{model_key}: no readiness poll"
    assert "READY_DEADLINE" in text
    assert f"READY_DEADLINE_FLOOR_SECONDS={READY_DEADLINE_FLOOR_SECONDS}" in text, (
        f"{model_key}: the D19 twenty-minute floor is not in entrypoint.sh"
    )
    # Timeout and an early server death are both hard failures.
    assert "model server not ready within" in text
    assert "exited before it became ready" in text
    assert text.count("exit 1") >= 3


@pytest.mark.parametrize("model_key", SERVER_RUNTIMES)
def test_server_entrypoint_owns_the_process_and_propagates_the_worker_status(
    model_key: str,
) -> None:
    text = read_text(model_key, "entrypoint.sh")
    # D19: never exec the worker - that discards the trap and orphans the server.
    assert 'exec "${PYTHON_BIN}" -m arena.worker.server' not in text
    assert "trap stop_server EXIT INT TERM" in text
    assert 'wait "${WORKER_PID}" || WORKER_STATUS=$?' in text
    assert 'exit "${WORKER_STATUS}"' in text
    assert 'export ARENA_MODEL_SERVER_MANAGED_BY="entrypoint"' in text


@pytest.mark.parametrize("model_key", SERVER_RUNTIMES)
def test_the_declared_ready_deadline_is_at_least_twenty_minutes(model_key: str) -> None:
    config = read_runtime_json(model_key)["inference_config"]
    server = config.get("server") or config.get("genai_server")
    assert server is not None, f"{model_key}: runtime.json declares no model server"
    assert int(server["ready_timeout_seconds"]) >= READY_DEADLINE_FLOOR_SECONDS
    assert str(server["ready_probe"]).startswith("http://127.0.0.1:")
    assert server["managed_by"] == "entrypoint"


@pytest.mark.parametrize("model_key", SERVER_RUNTIMES)
def test_the_adapter_attaches_instead_of_starting_a_second_server(model_key: str) -> None:
    """The adapter must not spawn its own engine when the entrypoint owns one."""
    module = load_runtime_module(model_key, "adapter")
    assert module.SERVER_MANAGED_BY_ENV == "ARENA_MODEL_SERVER_MANAGED_BY"
    assert module.READY_DEADLINE_FLOOR_SECONDS >= READY_DEADLINE_FLOOR_SECONDS
    source = read_text(model_key, "adapter.py")
    assert "entrypoint_owns_the_server()" in source
    # One builder for both callers, so they cannot launch different engines.
    assert "def build_server_plan(" in source
    assert "def render_server_plan(" in source


@pytest.mark.parametrize("model_key", SERVER_RUNTIMES)
def test_the_rendered_server_plan_is_shell_safe_and_matches_runtime_json(
    model_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_runtime_module(model_key, "adapter")
    monkeypatch.setenv("ARENA_WEIGHTS_DIR", f"/opt/arena/weights/{model_key}")
    rendered = module.render_server_plan()
    fields: dict[str, list[str]] = {}
    for line in rendered.splitlines():
        field, _, value = line.partition("\t")
        assert value, f"{model_key}: plan line has no value: {line!r}"
        fields.setdefault(field, []).append(value)
    assert set(fields) <= {"probe", "timeout", "env", "argv"}
    config = read_runtime_json(model_key)["inference_config"]
    server = config.get("server") or config.get("genai_server")
    assert fields["probe"] == [str(server["ready_probe"])]
    assert int(fields["timeout"][0]) >= READY_DEADLINE_FLOOR_SECONDS
    assert len(fields["argv"]) >= 4


@pytest.mark.parametrize("model_key", SERVER_RUNTIMES)
def test_the_plan_renderer_refuses_a_value_the_shell_would_mis_split(model_key: str) -> None:
    """Failure path: the shell-safety check is a real gate, not a comment."""
    module = load_runtime_module(model_key, "adapter")
    from arena.worker.adapter_api import AdapterError

    with pytest.raises(AdapterError):
        module.render_server_plan(Path("/opt/weights/with\ttab"))


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_entrypoint_refuses_to_start_without_its_runtime_files(model_key: str) -> None:
    text = read_text(model_key, "entrypoint.sh")
    for required in ("runtime.json", "adapter.py", "canonical.py"):
        assert required in text, f"{model_key}: entrypoint.sh does not check for {required}"
    assert "exit 1" in text


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
@pytest.mark.parametrize("script", ("bootstrap.sh", "entrypoint.sh"))
@NO_BASH_XFAIL
def test_shell_scripts_pass_bash_syntax_check(model_key: str, script: str) -> None:
    result = bash_syntax_check(runtime_dir(model_key) / script)
    assert result.returncode == 0, f"{model_key}/{script}: {result.stderr.strip()}"


@NO_BASH_XFAIL
def test_the_bash_syntax_check_actually_rejects_a_broken_script(tmp_path: Path) -> None:
    """Failure-path proof: `bash -n` above is a real gate, not a no-op."""
    good = tmp_path / "good.sh"
    good.write_text("#!/usr/bin/env bash\nset -euo pipefail\necho ok\n", encoding="utf-8")
    assert bash_syntax_check(good).returncode == 0

    broken = tmp_path / "broken.sh"
    broken.write_text("#!/usr/bin/env bash\nif [ -f x ]; then\necho missing fi\n", encoding="utf-8")
    assert bash_syntax_check(broken).returncode != 0


# --------------------------------------------------------------------------- #
# Section 11.3 item 6 - baked image layout
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_dockerfile_entrypoint_is_the_shared_runtime_entrypoint(model_key: str) -> None:
    text = read_text(model_key, "Dockerfile")
    assert 'ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]' in text
    # The old convention started the worker module directly; it must be gone or
    # baked and bootstrap modes would diverge again.
    assert "ENTRYPOINT [\"python" not in text


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_dockerfile_copies_the_runtime_and_the_arena_package(model_key: str) -> None:
    text = read_text(model_key, "Dockerfile")
    assert "COPY arena/ /opt/arena/arena/" in text
    assert f"COPY runtimes/{model_key}/ /opt/arena/runtime/" in text
    assert "chmod +x /opt/arena/runtime/entrypoint.sh" in text


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_dockerfile_copies_the_prompt_registry(model_key: str) -> None:
    """D17: the prompt registry travels with the image, not just with the bundle."""
    text = read_text(model_key, "Dockerfile")
    assert "COPY prompt_registry/ /opt/arena/prompt_registry/" in text, (
        f"{model_key}: Dockerfile does not copy prompt_registry/ (D17)"
    )


def test_the_dockerignore_does_not_exclude_the_prompt_registry() -> None:
    """A COPY that the build context strips would be a silent no-op."""
    rules = (NAMESPACE_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for line in rules.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            assert "prompt_registry" not in stripped, f".dockerignore excludes it: {stripped!r}"


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_dockerfile_from_line_matches_runtime_json_base_image(model_key: str) -> None:
    text = read_text(model_key, "Dockerfile")
    base_image = read_runtime_json(model_key)["base_image"]
    reference, _, digest = base_image.partition("@")
    assert f"ARG BASE_IMAGE={reference}" in text, (
        f"{model_key}: Dockerfile BASE_IMAGE disagrees with runtime.json"
    )
    assert f"ARG BASE_IMAGE_DIGEST={digest}" in text, (
        f"{model_key}: Dockerfile digest disagrees with runtime.json"
    )
    assert "FROM ${BASE_IMAGE}@${BASE_IMAGE_DIGEST}" in text


# --------------------------------------------------------------------------- #
# D3 - semantic error class
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_adapter_sets_the_semantic_error_class_field(model_key: str) -> None:
    source = read_text(model_key, "adapter.py")
    assert "semantic_error_class=semantic_error_class" in source, (
        f"{model_key}: adapter.py never passes semantic_error_class to RawOutput"
    )
    used = {name for name in SEMANTIC_ERROR_CLASSES if f'"{name}"' in source}
    assert used, f"{model_key}: adapter.py names no semantic error class"
    assert used <= SEMANTIC_ERROR_CLASSES


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_adapter_never_invents_a_class_outside_the_frozen_enum(model_key: str) -> None:
    source = read_text(model_key, "adapter.py")
    for invented in ("OUTPUT_BAD", "OUTPUT_UNKNOWN", "OUTPUT_ERROR", "OUTPUT_INVALID"):
        assert invented not in source


# --------------------------------------------------------------------------- #
# Masterplan section 14 - MinerU VLM concurrency
# --------------------------------------------------------------------------- #


def test_mineru_vlm_concurrency_stays_one_after_this_pass() -> None:
    document = read_runtime_json("mineru_vlm")
    assert document["max_concurrency_per_worker"] == 1
    assert document["gpu_count_min"] == 1
    assert document["inference_config"]["concurrency_policy"] == {
        "per_worker": 1,
        "scale": "replicas_only",
    }
    assert "MINERU_API_MAX_CONCURRENT_REQUESTS" in read_text("mineru_vlm", "entrypoint.sh")


# --------------------------------------------------------------------------- #
# Files this lane owns
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_every_runtime_ships_the_files_both_modes_need(model_key: str) -> None:
    for name in ("runtime.json", "provenance.json", "adapter.py", "canonical.py",
                 "Dockerfile", "bootstrap.sh", "entrypoint.sh", "README.md"):
        assert (runtime_dir(model_key) / name).is_file(), f"{model_key}: {name} is missing"


@pytest.mark.parametrize("model_key", C1_MODEL_KEYS)
def test_no_runtime_file_carries_a_secret_marker(model_key: str) -> None:
    for name in ("runtime.json", "provenance.json", "Dockerfile", "bootstrap.sh",
                 "entrypoint.sh", "README.md"):
        text = read_text(model_key, name)
        for marker in ("rpa_", "sk-", "ghp_", "AKIA"):
            assert marker not in text, f"{model_key}/{name}: possible secret marker {marker!r}"
