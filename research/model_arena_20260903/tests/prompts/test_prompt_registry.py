"""Tests for prompt_registry/ (lane R, was A4).

Covers: sha256.json matches the on-disk files exactly; the Opus prompt
equals the masterplan §21.5 text byte-for-byte; every GPU-runtime model key
has a model_specific_prompts.json entry; every JSON file is well-formed and
internally consistent.

Updated for ARENA_CONTRACT.md §11.5 **D17/D34**: the registry is keyed by the
``prompt_id`` that ``runtimes/<model_key>/runtime.json`` declares, not by
``<model_key>_official_v1``, and ``prompt_kind`` is the D34 vocabulary
(text | toolkit | none). A ``none`` model now carries an EMPTY prompt, not a null
one, because the worker resolves a real file and hashes its bytes. The
run-time-versus-registry agreement itself is tested in tests/registry/test_runtimes.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from arena.constants import GPU_MODEL_KEYS

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "prompt_registry"
OPUS_PROMPT_PATH = REGISTRY_DIR / "opus5_transcription_v1.txt"
MODEL_PROMPTS_PATH = REGISTRY_DIR / "model_specific_prompts.json"
SHA256_PATH = REGISTRY_DIR / "sha256.json"

MASTERPLAN_PATH = Path(
    r"D:\TAVONEL_PUBLIC_DOC_PARSING_MODEL_ARENA_EXECUTION_MASTERPLAN_2026-09-03.md"
)

#: ARENA_CONTRACT.md §11.5 D34.
VALID_PROMPT_KINDS = {"text", "toolkit", "none"}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def runtime_prompt_ids() -> dict[str, str]:
    """``{model_key: prompt_id}`` straight out of the runtime lane's own files."""
    runtimes = Path(__file__).resolve().parents[2] / "runtimes"
    return {
        model_key: _load_json(runtimes / model_key / "runtime.json")["prompt_id"]
        for model_key in GPU_MODEL_KEYS
    }


def test_registry_files_exist() -> None:
    assert OPUS_PROMPT_PATH.is_file(), OPUS_PROMPT_PATH
    assert MODEL_PROMPTS_PATH.is_file(), MODEL_PROMPTS_PATH
    assert SHA256_PATH.is_file(), SHA256_PATH
    assert (REGISTRY_DIR / "README.md").is_file()


def test_model_specific_prompts_is_well_formed_json() -> None:
    data = _load_json(MODEL_PROMPTS_PATH)
    assert isinstance(data, dict)
    assert data, "model_specific_prompts.json must not be empty"
    for prompt_id, entry in data.items():
        assert isinstance(prompt_id, str) and prompt_id
        assert isinstance(entry, dict), prompt_id


def test_sha256_json_is_well_formed_json() -> None:
    data = _load_json(SHA256_PATH)
    assert isinstance(data, dict)
    assert data


def test_every_gpu_model_key_has_a_prompt_entry() -> None:
    """Every model key in arena.constants.GPU_MODEL_KEYS must appear."""
    prompts = _load_json(MODEL_PROMPTS_PATH)
    covered_model_keys = {entry["model_key"] for entry in prompts.values()}
    missing = set(GPU_MODEL_KEYS) - covered_model_keys
    assert not missing, f"model_specific_prompts.json is missing keys: {sorted(missing)}"


def test_prompt_ids_are_the_runtime_json_ids(runtime_prompt_ids: dict[str, str]) -> None:
    """D17: the key is whatever runtime.json declares, and it must be that exactly."""
    prompts = _load_json(MODEL_PROMPTS_PATH)
    for prompt_id, entry in prompts.items():
        model_key = entry["model_key"]
        if model_key == "opus5_subscription":
            # ARENA_CONTRACT.md section 7 names this id directly; there is no runtime.json.
            assert prompt_id == "opus5_transcription_v1"
            continue
        assert model_key in GPU_MODEL_KEYS, model_key
        assert prompt_id == runtime_prompt_ids[model_key], (prompt_id, model_key)


def test_every_runtime_json_prompt_id_has_an_entry(runtime_prompt_ids: dict[str, str]) -> None:
    prompts = _load_json(MODEL_PROMPTS_PATH)
    missing = sorted(set(runtime_prompt_ids.values()) - set(prompts))
    assert not missing, f"runtime.json prompt ids with no registry entry: {missing}"


@pytest.mark.parametrize(
    "required_field",
    ["model_key", "prompt_kind", "text", "source_url", "source_revision", "retrieved_at", "notes"],
)
def test_every_entry_has_the_required_fields(required_field: str) -> None:
    prompts = _load_json(MODEL_PROMPTS_PATH)
    for prompt_id, entry in prompts.items():
        assert required_field in entry, f"{prompt_id} missing field {required_field!r}"


def test_prompt_kind_is_one_of_the_allowed_values() -> None:
    prompts = _load_json(MODEL_PROMPTS_PATH)
    for prompt_id, entry in prompts.items():
        assert entry["prompt_kind"] in VALID_PROMPT_KINDS, (prompt_id, entry["prompt_kind"])


def test_none_prompt_kind_is_empty_and_every_other_kind_is_not() -> None:
    """D17/D34: a prompt id always resolves to a real file, so `none` is "" not null.

    The worker reads prompt_registry/<prompt_id>.txt and fails closed when it is
    missing. A null would have meant "no file", which is exactly the failure D17
    exists to remove; an empty file whose sha256 is the hash of the empty string is
    a resolvable, checkable value.
    """
    prompts = _load_json(MODEL_PROMPTS_PATH)
    for prompt_id, entry in prompts.items():
        text = entry["text"]
        assert isinstance(text, str), f"{prompt_id}: text must be a string, never null"
        if entry["prompt_kind"] == "none":
            assert text == "", f"{prompt_id}: prompt_kind none must have empty text"
        else:
            assert text, (
                f"{prompt_id}: prompt_kind {entry['prompt_kind']} must have non-empty text"
            )


def test_no_prompt_text_looks_like_a_secret() -> None:
    """Mirrors ARENA_CONTRACT.md §9 secret-free receipt rule for this registry."""
    secret_like = re.compile(r"\b(rpa_|hf_|sk-|ghp_|AKIA)[A-Za-z0-9]", re.ASCII)
    prompts = _load_json(MODEL_PROMPTS_PATH)
    all_text_blobs = [OPUS_PROMPT_PATH.read_text(encoding="utf-8")]
    for entry in prompts.values():
        text = entry.get("text")
        if isinstance(text, str):
            all_text_blobs.append(text)
    for blob in all_text_blobs:
        assert not secret_like.search(blob), blob


def test_sha256_matches_opus_prompt_file_bytes() -> None:
    sha_map = _load_json(SHA256_PATH)
    expected = "sha256:" + _sha256_hex(OPUS_PROMPT_PATH.read_bytes())
    assert sha_map["opus5_transcription_v1"] == expected


def test_sha256_matches_every_model_specific_prompt_text() -> None:
    sha_map = _load_json(SHA256_PATH)
    prompts = _load_json(MODEL_PROMPTS_PATH)
    for prompt_id, entry in prompts.items():
        assert prompt_id in sha_map, f"sha256.json is missing an entry for {prompt_id}"
        expected = "sha256:" + _sha256_hex(entry["text"].encode("utf-8"))
        assert sha_map[prompt_id] == expected, f"{prompt_id}: sha256 mismatch"
        # And the bytes on disk are what the worker will hash.
        on_disk = (REGISTRY_DIR / f"{prompt_id}.txt").read_bytes()
        assert "sha256:" + _sha256_hex(on_disk) == expected, f"{prompt_id}: file bytes differ"


def test_no_sha256_entry_is_null() -> None:
    """D17 leaves nothing unresolved; a null here would break the worker's check."""
    for prompt_id, digest in _load_json(SHA256_PATH).items():
        assert isinstance(digest, str) and digest.startswith("sha256:"), prompt_id


def test_sha256_json_has_no_stray_entries() -> None:
    """Every key in sha256.json must correspond to a real prompt id."""
    sha_map = _load_json(SHA256_PATH)
    prompts = _load_json(MODEL_PROMPTS_PATH)
    known_ids = set(prompts.keys()) | {"opus5_transcription_v1"}
    stray = set(sha_map.keys()) - known_ids
    assert not stray, f"sha256.json has entries with no matching prompt: {sorted(stray)}"


def test_retired_a4_prompt_ids_are_gone_but_mapped_in_the_readme() -> None:
    """Nothing was deleted silently (D17): the README carries retired -> current."""
    sha_map = _load_json(SHA256_PATH)
    readme = (REGISTRY_DIR / "README.md").read_text(encoding="utf-8")
    for model_key in GPU_MODEL_KEYS:
        retired = f"{model_key}_official_v1"
        assert retired not in sha_map
        assert retired in readme, f"{retired} was dropped with no README mapping row"


def _extract_masterplan_opus_prompt() -> str:
    """Parse the MP §21.5 fenced ```text block verbatim.

    Locates the "## 21.5 Opus prompt" heading, then the first fenced
    ```text ... ``` block after it, and returns its body unchanged.
    """
    content = MASTERPLAN_PATH.read_text(encoding="utf-8")
    heading_match = re.search(r"^## 21\.5 .*$", content, re.MULTILINE)
    assert heading_match is not None, "could not find MP section 21.5 heading"
    remainder = content[heading_match.end() :]
    fence_match = re.search(r"```text\n(.*?)\n```", remainder, re.DOTALL)
    assert fence_match is not None, "could not find the fenced prompt block under MP §21.5"
    body = fence_match.group(1)
    return body + "\n"


@pytest.mark.skipif(
    not MASTERPLAN_PATH.is_file(),
    reason="masterplan file not present on this host outside the D: drive checkout",
)
def test_opus_prompt_equals_masterplan_section_21_5_verbatim() -> None:
    expected = _extract_masterplan_opus_prompt()
    actual = OPUS_PROMPT_PATH.read_text(encoding="utf-8")
    assert actual == expected


@pytest.mark.skipif(
    not MASTERPLAN_PATH.is_file(),
    reason="masterplan file not present on this host outside the D: drive checkout",
)
def test_opus_prompt_matches_masterplan_line_count() -> None:
    expected_lines = _extract_masterplan_opus_prompt().splitlines()
    actual_lines = OPUS_PROMPT_PATH.read_text(encoding="utf-8").splitlines()
    assert actual_lines == expected_lines


def test_opus_prompt_file_has_no_crlf_and_exactly_one_trailing_newline() -> None:
    raw = OPUS_PROMPT_PATH.read_bytes()
    assert b"\r" not in raw, "opus prompt file must use LF line endings only"
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n"), (
        "opus prompt file must end with exactly one trailing newline"
    )
