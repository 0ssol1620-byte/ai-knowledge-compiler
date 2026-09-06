"""The confirmatory half of W6 v8: the runtime attestation, the client, the
holdout selector and the runner that produces the endpoint.

These four are what stand between "the pipeline works on development data" and
"a number that may be published". Each of them has a way of failing quietly, and
each of those ways is tested here rather than assumed:

- an attestation whose digests *nearly* match the hub is a different checkpoint;
- a client that turns an HTTP timeout into an abstention reports an outage as a
  finding;
- a holdout selector whose exclusion list came back empty removes nothing and
  says it succeeded --- which has actually happened in this programme;
- a runner that accepts a development question set produces a development number
  wearing a confirmatory label.
"""

from __future__ import annotations

import base64
import gzip
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "research" / "experiments" / "H1-W6-SAME-INTELLIGENCE-01"
SCRIPTS = EXP / "scripts"


def load(name: str):
    path = SCRIPTS / name
    if not path.exists():
        pytest.skip(f"{name} is not present")
    spec = importlib.util.spec_from_file_location(f"w6test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- the client -------------------------------------------------------------


@pytest.fixture
def client():
    vllm = load("vllm_model_v8.py")
    return vllm, vllm.VLLMChatModel(
        base_url="http://127.0.0.1:9", model_name="Qwen/Qwen3.6-27B",
        attestation={"checkpoint_revision": "a" * 40, "serving_runtime": "vllm"})


def test_arms_differ_only_in_the_context_they_supply(client):
    _vllm, model = client
    one = model.messages("what is the population?", "CONTEXT A")
    two = model.messages("what is the population?", "CONTEXT B")
    assert one[0] == two[0], "the system contract is not arm-specific"
    assert one[1]["content"] != two[1]["content"]
    assert one[1]["content"].replace("CONTEXT A", "") == \
        two[1]["content"].replace("CONTEXT B", "")


def test_the_decoding_is_the_founder_decision(client):
    _vllm, model = client
    assert model.decoding["temperature"] == 0.0
    assert model.decoding["max_tokens"] == 256
    assert model.decoding["tools"] == "off"


def test_the_reasoning_preamble_is_disabled_for_every_arm_identically(client):
    """Measured before the freeze: the preamble does not finish inside 256 tokens.

    Leaving it on under the frozen budget would have scored every arm as an
    abstention, which measures the preamble rather than the representations.
    """
    vllm, model = client
    assert vllm.CHAT_TEMPLATE_KWARGS == {"enable_thinking": False}
    assert model.decoding["chat_template_kwargs"] == {"enable_thinking": False}
    sent = {}
    model._post = lambda payload: sent.update(payload) or {
        "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
        "usage": {}}
    model.answer("q", "c")
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent["temperature"] == 0.0
    assert sent["max_tokens"] == 256
    assert "tools" not in sent


def test_the_identity_reports_the_attested_revision_not_the_name(client):
    _vllm, model = client
    assert model.identity["is_real_model"] is True
    assert model.identity["revision"] == "a" * 40


def _reply(model, text, *, usage=None):
    model._post = lambda payload: {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 2},
    }


def test_the_abstention_token_is_an_abstention_and_a_value_is_not(client):
    _vllm, model = client
    _reply(model, "INSUFFICIENT_EVIDENCE")
    assert model.answer("q", "c")["abstained"] is True
    _reply(model, "  1,450  ")
    answered = model.answer("q", "c")
    assert answered["abstained"] is False
    assert answered["answer"] == "1,450"


def test_a_transport_failure_is_raised_and_never_scored_as_an_abstention(client):
    vllm, model = client
    def boom(_payload):
        raise vllm.ModelTransportError("no route to host")
    model._post = boom
    with pytest.raises(vllm.ModelTransportError):
        model.answer("q", "c")


def test_an_unparseable_completion_is_a_transport_error(client):
    vllm, model = client
    model._post = lambda _payload: {"choices": []}
    with pytest.raises(vllm.ModelTransportError):
        model.answer("q", "c")


def test_a_null_completion_is_a_transport_error(client):
    vllm, model = client
    _reply(model, None)
    with pytest.raises(vllm.ModelTransportError):
        model.answer("q", "c")


def test_usage_accumulates_so_cost_can_be_reported(client):
    _vllm, model = client
    _reply(model, "x", usage={"prompt_tokens": 100, "completion_tokens": 5})
    model.answer("q", "c")
    model.answer("q", "c")
    assert model.usage_summary() == {"calls": 2, "prompt_tokens": 200,
                                     "completion_tokens": 10}


# --- the attestation --------------------------------------------------------


DECLARED = {
    "config.json": {"sha256": None, "git_blob_sha1": "aa" * 20, "size": 10},
    "model-00001.safetensors": {"sha256": "bb" * 32, "git_blob_sha1": None, "size": 99},
    "tokenizer.json": {"sha256": "cc" * 32, "git_blob_sha1": None, "size": 5},
}
OBSERVED = {
    "config.json": {"sha256": "zz" * 32, "git_blob_sha1": "aa" * 20},
    "model-00001.safetensors": {"sha256": "bb" * 32, "git_blob_sha1": "ignored"},
    "tokenizer.json": {"sha256": "cc" * 32, "git_blob_sha1": "ignored"},
}


def test_a_matching_manifest_verifies_by_both_digest_kinds():
    attest = load("attest_runtime_v8.py")
    verdict = attest.verify_manifest(OBSERVED, DECLARED)
    assert verdict["matches"] is True
    assert verdict["verified_by_lfs_sha256"] == 2
    assert verdict["verified_by_git_blob_sha1"] == 1


@pytest.mark.parametrize("mutate,expected_key", [
    (lambda o: o.__setitem__("tokenizer.json", {"sha256": "dd" * 32}), "digest_mismatches"),
    (lambda o: o.pop("model-00001.safetensors"), "missing_from_runtime"),
    (lambda o: o.__setitem__("surprise.bin", {"sha256": "ee" * 32}),
     "present_but_not_declared"),
])
def test_any_departure_from_the_declared_checkpoint_is_a_refusal(mutate, expected_key):
    attest = load("attest_runtime_v8.py")
    observed = {k: dict(v) for k, v in OBSERVED.items()}
    mutate(observed)
    verdict = attest.verify_manifest(observed, DECLARED)
    assert verdict["matches"] is False
    assert verdict[expected_key]


def test_a_file_the_hub_declares_no_digest_for_cannot_be_called_verified():
    attest = load("attest_runtime_v8.py")
    declared = dict(DECLARED, mystery={"sha256": None, "git_blob_sha1": None})
    observed = dict(OBSERVED, mystery={"sha256": "ff" * 32})
    verdict = attest.verify_manifest(observed, declared)
    assert verdict["matches"] is False
    assert verdict["unverifiable"] == ["mystery"]


def test_the_pod_program_is_transferred_byte_identically():
    attest = load("attest_runtime_v8.py")
    command = attest.capture_command(repository="Qwen/Qwen3.6-27B", revision="a" * 40,
                                     image_digest="sha256:" + "b" * 64)
    encoded = command.split("printf %s '")[1].split("'")[0]
    expected = (SCRIPTS / "pod_attest_qwen3_6.py").read_bytes()
    assert gzip.decompress(base64.b64decode(encoded)) == expected
    assert "a" * 40 in command


def test_the_serve_args_pin_the_tokenizer_revision_as_well_as_the_weights():
    """A pinned checkpoint served through an unpinned tokenizer is not pinned."""
    attest = load("attest_runtime_v8.py")
    args = attest.serve_args(repository="Qwen/Qwen3.6-27B", revision="a" * 40,
                             max_model_len=262144)
    assert args[0] == "Qwen/Qwen3.6-27B"
    assert args[args.index("--revision") + 1] == "a" * 40
    assert args[args.index("--tokenizer-revision") + 1] == "a" * 40
    assert args[args.index("--max-model-len") + 1] == "262144"
    assert "--quantization" not in args


def test_capture_command_refuses_without_an_image_digest():
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "attest_runtime_v8.py"),
         "--mode", "capture-command"],
        capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "image-digest" in result.stdout


def test_a_file_the_serving_stack_never_downloaded_is_not_a_missing_file():
    """README and LICENSE are not what executed; weights and tokenizer are."""
    attest = load("attest_runtime_v8.py")
    declared = dict(DECLARED, **{"README.md": {"sha256": None,
                                               "git_blob_sha1": "dd" * 20}})
    verdict = attest.verify_manifest(OBSERVED, declared)
    assert verdict["matches"] is True
    assert verdict["declared_but_not_downloaded"] == ["README.md"]


def test_an_absent_weight_file_is_still_a_refusal():
    attest = load("attest_runtime_v8.py")
    observed = {k: dict(v) for k, v in OBSERVED.items()}
    observed.pop("model-00001.safetensors")
    verdict = attest.verify_manifest(observed, DECLARED)
    assert verdict["matches"] is False
    assert verdict["missing_from_runtime"] == ["model-00001.safetensors"]


def test_a_pod_that_reported_a_failure_is_model_runtime_not_ready(tmp_path):
    failure = tmp_path / "attestation.json"
    failure.write_text(json.dumps({"ok": False, "failure_reason": "model_download_failed"}),
                       encoding="utf-8")
    out = tmp_path / "receipt.json"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "attest_runtime_v8.py"), "--mode", "capture",
         "--attestation-file", str(failure), "--output", str(out)],
        capture_output=True, text=True, check=False)
    assert result.returncode == 3
    assert "MODEL_RUNTIME_NOT_READY" in result.stdout
    assert json.loads(out.read_text(encoding="utf-8"))["qualified"] is False


# --- the holdout selector ---------------------------------------------------


def _source(titles):
    return {
        "api": "https://en.wikipedia.org/w/api.php", "normalization": "n",
        "ordering": "o", "selection_rule": "s", "source_category": "c",
        "source_counts_observed_until_selection": {}, "protocol_sha256": "sha256:p",
        "acquisition_script_sha256": "sha256:a", "max_candidates_consumable": 4500,
        "candidate_count": len(titles),
        "titles": [{"index": i, "order_key": f"{i:064d}", "title": t}
                   for i, t in enumerate(titles)],
    }


def test_an_empty_sealed_title_list_refuses_rather_than_filtering_nothing():
    """The guard that failed open once. An inert filter reports success."""
    manifest = load("build_holdout_manifest_v8.py")
    with pytest.raises(SystemExit):
        manifest.development_titles({"development_titles_excluded_from_v8": {"titles": []}})


def test_a_seal_whose_count_disagrees_with_its_list_refuses():
    manifest = load("build_holdout_manifest_v8.py")
    with pytest.raises(SystemExit):
        manifest.development_titles(
            {"development_titles_excluded_from_v8": {"count": 3, "titles": ["A"]}})


def test_development_titles_are_removed_and_the_frozen_order_is_kept():
    manifest = load("build_holdout_manifest_v8.py")
    source = _source(["Alpha", "Beta", "Gamma", "Delta"])
    kept, removed = manifest.select(source, {"Beta", "Delta"})
    assert [row["title"] for row in kept] == ["Alpha", "Gamma"]
    assert removed == ["Beta", "Delta"]
    assert [row["order_key"] for row in kept] == [f"{0:064d}", f"{2:064d}"]


def test_the_exclusion_comparison_survives_underscores_and_normalization():
    manifest = load("build_holdout_manifest_v8.py")
    source = _source(["Stone_Mountain  Memorial", "Other"])
    kept, removed = manifest.select(
        source, {manifest.normalize_title("Stone Mountain Memorial")})
    assert removed == ["Stone_Mountain  Memorial"]
    assert [row["title"] for row in kept] == ["Other"]


def test_selection_refuses_before_the_config_freeze_exists(tmp_path):
    if (EXP / "receipts" / "v8-config-freeze.json").exists():
        pytest.skip("the freeze exists; this refusal is no longer reachable")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "build_holdout_manifest_v8.py"),
         "--output", str(tmp_path / "m.json")],
        capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "config freeze" in result.stdout
    assert not (tmp_path / "m.json").exists()


# --- the confirmatory runner ------------------------------------------------


def test_the_runner_refuses_a_development_question_set(tmp_path):
    """A confirmatory label over development questions is the failure to prevent."""
    freeze = tmp_path / "freeze.json"
    freeze.write_text(json.dumps({"arm_source_hashes": {}}), encoding="utf-8")
    qs = tmp_path / "qs.json"
    qs.write_text(json.dumps({"run_class": "DEVELOPMENT_ONLY", "questions": []}),
                  encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "run_arms_holdout_v8.py"),
         "--question-set", str(qs), "--output", str(tmp_path / "o.json"),
         "--freeze", str(freeze), "--base-url", "http://127.0.0.1:9"],
        capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "HOLDOUT_CONFIRMATORY" in result.stdout


def test_the_runner_refuses_without_a_freeze(tmp_path):
    qs = tmp_path / "qs.json"
    qs.write_text(json.dumps({"run_class": "HOLDOUT_CONFIRMATORY", "questions": []}),
                  encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "run_arms_holdout_v8.py"),
         "--question-set", str(qs), "--output", str(tmp_path / "o.json"),
         "--freeze", str(tmp_path / "absent.json"), "--base-url", "http://127.0.0.1:9"],
        capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "no config freeze" in result.stdout


def test_the_runner_refuses_when_a_pinned_source_has_drifted(tmp_path):
    freeze = tmp_path / "freeze.json"
    freeze.write_text(json.dumps({"arm_source_hashes": {"arms_v8.py": "sha256:stale"}}),
                      encoding="utf-8")
    qs = tmp_path / "qs.json"
    qs.write_text(json.dumps({"run_class": "HOLDOUT_CONFIRMATORY", "questions": []}),
                  encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "run_arms_holdout_v8.py"),
         "--question-set", str(qs), "--output", str(tmp_path / "o.json"),
         "--freeze", str(freeze), "--base-url", "http://127.0.0.1:9"],
        capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "drifted" in result.stdout


def test_the_runner_refuses_without_a_base_url_rather_than_falling_back(tmp_path):
    freeze = tmp_path / "freeze.json"
    freeze.write_text(json.dumps({"arm_source_hashes": {}}), encoding="utf-8")
    qs = tmp_path / "qs.json"
    qs.write_text(json.dumps({"run_class": "HOLDOUT_CONFIRMATORY", "questions": []}),
                  encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "run_arms_holdout_v8.py"),
         "--question-set", str(qs), "--output", str(tmp_path / "o.json"),
         "--freeze", str(freeze)],
        capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "no fallback model" in result.stdout


def test_the_dry_run_exercises_the_confirmatory_harness_on_development_data(tmp_path):
    """§7: a harness defect is paid for with development titles, not holdout ones."""
    question_set = EXP / "receipts" / "question-set-v8-dev-2026-08-19.json"
    if not question_set.exists():
        pytest.skip("the development question set is not present")
    out = tmp_path / "dryrun.json"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS / "run_arms_holdout_v8.py"),
         "--question-set", str(question_set), "--output", str(out),
         "--development-dry-run", "--primary-limit", "6", "--control-limit", "4"],
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["run_class"] == "DEVELOPMENT_ONLY"
    assert receipt["shared_configuration"]["model_identity"]["is_real_model"] is False
    assert receipt["controls"]["all_separate"] is True
    assert receipt["control_cohort"]["evaluated"] > 0


def test_the_freeze_pins_every_source_that_can_change_the_endpoint():
    freeze_module = load("freeze_config_v8.py")
    preflight = load("preflight_holdout_v8.py")
    for name in ("run_arms_holdout_v8.py", "vllm_model_v8.py",
                 "build_holdout_manifest_v8.py"):
        assert name in freeze_module.PINNED_SOURCES
        assert name in preflight.REQUIRED_ARM_SOURCES
