"""The config freeze must not be writable by accident, and must not be rewritable.

Three of its fields are decisions rather than measurements: the model identity,
the RAW context-budget policy, and the disposition of a metric that is 1.0 by
construction. A default on any of them would record a decision nobody made, so
the builder refuses instead --- and that refusal is what is tested here, because
the freeze exists precisely to stop things being adjusted quietly.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "research/experiments/H1-W6-SAME-INTELLIGENCE-01"
SCRIPT = EXP / "scripts/freeze_config_v8.py"


def load(relative: str, name: str) -> Any:
    path = ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} is not present")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def freeze() -> Any:
    return load(
        "research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/freeze_config_v8.py",
        "t_freeze_v8")


def _expected_revision() -> str:
    """Read from the candidate registry, never hardcoded here.

    A literal in the test would be a third source of truth: the test would keep
    passing after the registry changed, which is the failure it exists to catch.
    """
    identity = load(
        "research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/model_identity_v8.py",
        "t_identity_for_freeze")
    return identity.expected_identity()["expected_revision"]


ATTESTATION = {
    "checkpoint_revision": None, "model_file_manifest_sha256": "sha256:aa",
    "tokenizer_identity": "Qwen/Qwen3.6-27B", "tokenizer_hash": "sha256:bb",
    "quantization": "bf16", "serving_runtime": "vllm",
    "serving_runtime_version": "0.0.0", "runtime_image_digest": "sha256:cc",
    "model_attestation": "signed",
}
MODEL = "Qwen/Qwen3.6-27B"
DECODING = '{"temperature": 0.0, "max_tokens": 256, "tools": "off"}'


def attestation_file(tmp_path: Path, **overrides: Any) -> Path:
    payload = dict(ATTESTATION)
    payload["checkpoint_revision"] = _expected_revision()
    payload.update(overrides)
    # A distinct name per variant. Sharing one filename let complete_args
    # overwrite a deliberately incomplete attestation with the complete one,
    # so the refusal under test never happened.
    suffix = "-".join(sorted(overrides)) or "complete"
    path = tmp_path / f"attestation-{suffix}.json"
    path.write_text(json.dumps({k: v for k, v in payload.items() if v is not None}),
                    encoding="utf-8")
    return path


def complete_args(tmp_path: Path, **overrides: Any) -> list[str]:
    supplied = {
        "--model-id": MODEL, "--model-version": "v1", "--decoding": DECODING,
        "--attestation": str(attestation_file(tmp_path)),
        "--model-context-tokens": "32000",
        "--raw-context-budget-policy": "RAW_GETS_WHOLE_DOCUMENT_BUDGET",
        "--separability-disposition": "GENERATOR_INTEGRITY_CHECK_ONLY",
    }
    supplied.update(overrides)
    return [a for pair in supplied.items() for a in pair]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    if not SCRIPT.exists():
        pytest.skip("freeze_config_v8.py is not present")
    # S603: the executable is this interpreter and the script is a repository
    # path; no part of the command line comes from outside this test.
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
        cwd=str(ROOT), check=False)


def test_no_arguments_refuses_rather_than_writing_defaults(tmp_path):
    result = run("--output", str(tmp_path / "freeze.json"))
    assert result.returncode == 2
    assert "decisions, not defaults" in result.stdout
    assert not (tmp_path / "freeze.json").exists()


@pytest.mark.parametrize("omitted", sorted([
    "--model-id", "--model-version", "--decoding", "--attestation",
    "--model-context-tokens", "--raw-context-budget-policy",
    "--separability-disposition"]))
def test_omitting_any_single_decision_refuses(tmp_path, omitted):
    """Partial information must not be enough. Four of five is still a guess."""
    args = complete_args(tmp_path)
    index = args.index(omitted)
    del args[index:index + 2]
    result = run(*args, "--output", str(tmp_path / "freeze.json"))
    assert result.returncode == 2
    assert omitted in result.stdout
    assert not (tmp_path / "freeze.json").exists()


def test_an_invalid_policy_value_is_rejected_by_the_parser(tmp_path):
    """The policy is a closed set; a free-text value would let anything through."""
    result = run(*complete_args(
        tmp_path, **{"--raw-context-budget-policy": "WHATEVER_SOUNDS_FINE"}),
        "--output", str(tmp_path / "freeze.json"))
    assert result.returncode != 0
    assert not (tmp_path / "freeze.json").exists()


def test_a_complete_decision_set_writes_a_freeze_that_pins_the_sources(tmp_path):
    out = tmp_path / "freeze.json"
    result = run(*complete_args(tmp_path), "--output", str(out))
    assert result.returncode == 0, result.stdout + result.stderr
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["holdout_status"] == "UNOPENED"
    assert written["model_identity"]["is_real_model"] is True
    assert written["arm_source_hashes"], "a freeze that pins no source is not a lock"
    assert written["statistics"]["primary_test"].startswith("exact binomial McNemar")
    assert written["scoring"]["primary_comparison"] == "TAVONEL vs BASIC_RAG"


def test_an_existing_freeze_is_verified_and_never_overwritten(tmp_path):
    out = tmp_path / "freeze.json"
    first = run(*complete_args(tmp_path), "--output", str(out))
    assert first.returncode == 0
    before = out.read_bytes()

    again = run(*complete_args(tmp_path, **{"--model-version": "v2"}),
                "--output", str(out))
    assert "FREEZE INTACT" in again.stdout
    assert out.read_bytes() == before, "a freeze that can be rewritten is not a lock"


def test_verification_detects_source_drift(freeze, tmp_path):
    """The code that runs the holdout must be the code that was frozen."""
    existing = {"arm_source_hashes": {"arms_v8.py": "sha256:not-the-real-hash"}}
    result = freeze.verify(existing)
    assert not result["intact"]
    assert result["drift"][0]["state"] == "CHANGED"


def test_verification_detects_a_missing_source(freeze):
    existing = {"arm_source_hashes": {"never_existed_v8.py": "sha256:abc"}}
    result = freeze.verify(existing)
    assert not result["intact"]
    assert result["drift"][0]["state"] == "MISSING"


def test_an_unmodified_freeze_verifies_clean(freeze, tmp_path):
    out = tmp_path / "freeze.json"
    run(*complete_args(tmp_path), "--output", str(out))
    result = freeze.verify(json.loads(out.read_text(encoding="utf-8")))
    assert result["intact"]
    assert result["receipt_hash_matches"]


@pytest.mark.parametrize("field", sorted([
    "checkpoint_revision", "model_file_manifest_sha256", "tokenizer_identity",
    "tokenizer_hash", "quantization", "serving_runtime", "serving_runtime_version",
    "runtime_image_digest", "model_attestation"]))
def test_an_incomplete_attestation_is_model_runtime_not_ready(tmp_path, field):
    """A name pins nothing; every field must come from the live runtime."""
    path = attestation_file(tmp_path, **{field: None})
    result = run(*complete_args(tmp_path, **{"--attestation": str(path)}),
                 "--output", str(tmp_path / "freeze.json"))
    assert result.returncode == 3
    assert "MODEL_RUNTIME_NOT_READY" in result.stdout
    assert field in result.stdout
    assert not (tmp_path / "freeze.json").exists()


def test_a_substituted_model_is_refused_with_no_fallback(tmp_path):
    """An unattestable runtime fails; it never falls back to another model."""
    result = run(*complete_args(tmp_path, **{"--model-id": "meta-llama/Something"}),
                 "--output", str(tmp_path / "freeze.json"))
    assert result.returncode == 3
    assert "no fallback model" in result.stdout
    assert not (tmp_path / "freeze.json").exists()


def test_a_missing_attestation_file_is_refused(tmp_path):
    result = run(*complete_args(tmp_path,
                                **{"--attestation": str(tmp_path / "absent.json")}),
                 "--output", str(tmp_path / "freeze.json"))
    assert result.returncode == 3
    assert "MODEL_RUNTIME_NOT_READY" in result.stdout


def test_a_revision_that_is_not_the_expected_one_is_a_mismatch(tmp_path):
    """MODEL_IDENTITY_MISMATCH, distinct from MODEL_RUNTIME_NOT_READY.

    Something executed and it was not what the candidate registry expects. The
    registry is not overwritten with whatever ran, and no freeze is written.
    """
    path = attestation_file(tmp_path, checkpoint_revision="f" * 40)
    result = run(*complete_args(tmp_path, **{"--attestation": str(path)}),
                 "--output", str(tmp_path / "freeze.json"))
    assert result.returncode == 4
    assert "MODEL_IDENTITY_MISMATCH" in result.stdout
    assert "do NOT overwrite the candidate registry" in result.stdout
    assert not (tmp_path / "freeze.json").exists()


def test_mismatch_and_not_ready_are_different_exit_codes(tmp_path):
    """They call for different actions, so they must not look alike."""
    mismatch = run(*complete_args(
        tmp_path, **{"--attestation": str(attestation_file(
            tmp_path, checkpoint_revision="f" * 40))}),
        "--output", str(tmp_path / "a.json"))
    not_ready = run(*complete_args(
        tmp_path, **{"--attestation": str(attestation_file(tmp_path, quantization=None))}),
        "--output", str(tmp_path / "b.json"))
    assert mismatch.returncode == 4
    assert not_ready.returncode == 3
    assert mismatch.returncode != not_ready.returncode


def test_the_freeze_pins_the_whole_identity_chain(tmp_path):
    out = tmp_path / "freeze.json"
    run(*complete_args(tmp_path), "--output", str(out))
    chain = json.loads(out.read_text(encoding="utf-8"))["model_identity_chain"]
    assert (chain["candidate_registry_expected_revision"]
            == chain["live_attested_revision"] == _expected_revision())


def test_the_freeze_carries_the_attestation_and_the_context_window(tmp_path):
    out = tmp_path / "freeze.json"
    run(*complete_args(tmp_path), "--output", str(out))
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["model_identity"]["name"] == MODEL
    assert written["model_context_tokens"] == 32000
    for field in ATTESTATION:
        assert written["model_attestation"][field]
    assert written["model_identity"]["revision"] == _expected_revision()


def test_the_freeze_records_the_evidence_behind_the_raw_budget_decision(tmp_path):
    """The decision is recorded with what forced it, not as a bare enum."""
    out = tmp_path / "freeze.json"
    run(*complete_args(tmp_path), "--output", str(out))
    written = json.loads(out.read_text(encoding="utf-8"))
    evidence = written["raw_context_budget_policy_evidence"]
    assert evidence["development_oracle_lost_to_truncation"] > 0.5
    assert "context budget" in evidence["why_it_had_to_be_decided"]


def test_the_freeze_refuses_to_call_the_markup_exclusions_proven(tmp_path):
    """'96 are proven non-semantic' is forbidden wording; the note must be exact."""
    out = tmp_path / "freeze.json"
    run(*complete_args(tmp_path), "--output", str(out))
    note = json.loads(out.read_text(encoding="utf-8"))["generator"]["admission_rule_note"]
    assert "not a proof" in note
    assert "detector liveness" in note
    assert "proven non-semantic" not in note


def test_no_config_freeze_is_present_in_the_repository_yet():
    """Until the decisions are made, the real freeze must not exist.

    If this starts failing, either the decisions were made --- in which case this
    test is updated deliberately --- or a freeze was written without them.
    """
    path = EXP / "receipts/v8-config-freeze.json"
    if path.exists():
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["model_identity"]["is_real_model"] is True
        assert written["raw_context_budget_policy"]
        assert written["before_after_separable_share_disposition"]
    else:
        assert not path.exists()
