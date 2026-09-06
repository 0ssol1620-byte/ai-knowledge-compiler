"""The post-open instrumentation receipt must be able to refuse.

Two properties matter. The receipt is immutable, so the disclosure it carries
cannot be edited later. And its influence scan is real: it must fire on the
modules that genuinely decide numbers, or the classification
`POST_OPEN_PRE_OBSERVATION_NON_ANALYTIC_INSTRUMENTATION` is a label rather than
a finding.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "research" / "experiments" / "H1-W6-SAME-INTELLIGENCE-01"
SCRIPTS = EXP / "scripts"
SEALER = SCRIPTS / "seal_instrumentation_v8.py"
RECEIPT = EXP / "receipts" / "v8-post-open-instrumentation.json"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("w6_instrumentation", SEALER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["w6_instrumentation"] = module
    spec.loader.exec_module(module)
    return module


sealer = _load()


def test_scan_ignores_prose_but_reads_code() -> None:
    """A docstring saying "holds no threshold" is not a violation; a call to the
    scorer is."""
    identifiers = sealer.code_identifiers(SCRIPTS / "verify_holdout_corpus_v8.py")
    assert "threshold" not in identifiers
    assert "canonical_sha256" in identifiers


@pytest.mark.parametrize(("module", "expected"), [
    ("scoring_v8.py", {"score_answer", "paired_comparison", "holm"}),
    ("arms_v8.py", {"bm25", "top_k"}),
    ("vllm_model_v8.py", {"temperature", "max_tokens"}),
    ("run_arms_holdout_v8.py", {"score_answer", "top_k"}),
])
def test_scan_fires_on_the_modules_that_decide_numbers(module: str,
                                                       expected: set[str]) -> None:
    # Folded to lower case, matching the scan itself. The first version of this
    # test compared case-sensitively and passed `vllm_model_v8.py` as clean --- it
    # spells its decoding contract `TEMPERATURE` and `MAX_TOKENS` --- which is the
    # exact blind spot the scan was strengthened to close.
    identifiers = {token.lower() for token in sealer.code_identifiers(SCRIPTS / module)}
    hits = {token.lower() for token in sealer.FORBIDDEN_INFLUENCE} & identifiers
    assert expected <= hits, f"{module}: expected {expected}, scan found {hits}"


def test_the_pinned_scripts_are_clean() -> None:
    scan = sealer.influence_scan()
    assert scan["clean"], scan["hits"]


def test_build_refuses_when_a_pinned_script_becomes_analytic(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sealer, "PINNED", ("scoring_v8.py",))
    with pytest.raises(SystemExit) as excinfo:
        sealer.build(acquisition_started_utc="2026-08-20T00:00:00Z")
    assert "non-analytic instrumentation" in str(excinfo.value)


def test_existing_receipt_is_verified_not_overwritten(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    body = {"classification": "POST_OPEN_PRE_OBSERVATION_NON_ANALYTIC_INSTRUMENTATION",
            "generated_at": "2026-08-20T00:00:00+00:00", "pinned_sources": {}}
    body["receipt_sha256"] = sealer.canonical_sha256(body)
    target.write_text(json.dumps(body), encoding="utf-8")
    before = target.read_bytes()
    monkeypatch.setattr(sys, "argv", ["seal", "--output", str(target),
                                      "--acquisition-started-utc", "2026-01-01T00:00:00Z"])
    assert sealer.main() == 0
    assert target.read_bytes() == before


def test_pinned_source_drift_is_reported_broken(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sealer, "HERE", tmp_path)
    target = tmp_path / "tool.py"
    target.write_text("x = 1\n", encoding="utf-8")
    body: dict[str, Any] = {"pinned_sources": {"tool.py": sealer.file_sha256(target)}}
    body["receipt_sha256"] = sealer.canonical_sha256(body)
    assert sealer.verify(body) == 0
    target.write_text("x = 2\n", encoding="utf-8")
    assert sealer.verify(body) == 1


def test_the_live_receipt_records_zero_holdout_observation() -> None:
    if not RECEIPT.exists():
        pytest.skip("the instrumentation receipt has not been written")
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    state = receipt["holdout_state_at_creation"]
    assert receipt["classification"] == "POST_OPEN_PRE_OBSERVATION_NON_ANALYTIC_INSTRUMENTATION"
    assert state["holdout_corpus"]["files"] == 0
    assert state["holdout_corpus"]["directories"] == 0
    assert state["holdout_questions_observed"] == 0
    assert state["holdout_arm_results_observed"] == 0
    assert "written after the v8 holdout was opened" in receipt["disclosure"]
