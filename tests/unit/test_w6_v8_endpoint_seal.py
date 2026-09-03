"""The W6 v8 endpoint seal must refuse to be rewritten, and must refuse to guess.

Two properties are worth a test each, because both are ways a confirmatory result
quietly stops being one: a seal that can be overwritten after the numbers are read
is not a lock, and a seal that infers its own outcome class from the numbers has
made a judgement nobody signed.

A third is checked here because it is the failure this experiment has already had
once: a gate-failure seal must not be indistinguishable from a seal whose arm
receipts merely went missing.
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
EXP = ROOT / "research" / "experiments" / "H1-W6-SAME-INTELLIGENCE-01"
SEALER = EXP / "scripts" / "seal_w6_endpoint_v8.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("w6_endpoint_seal", SEALER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["w6_endpoint_seal"] = module
    spec.loader.exec_module(module)
    return module


sealer = _load()


def test_outcome_class_is_not_inferred() -> None:
    """Naming the outcome is a decision, not a computation over the numbers."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SEALER), "--output", str(EXP / "receipts" / "__absent__.json")],
        capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "--outcome-class is required" in (result.stderr + result.stdout)


def test_every_valid_outcome_is_sealable() -> None:
    """Including the ones nobody hopes for."""
    assert "TAVONEL_WORSE" in sealer.OUTCOME_CLASSES
    assert "NO_MEASURABLE_DIFFERENCE" in sealer.OUTCOME_CLASSES
    assert "CONFIRMATORY_PRE_ARM_GATE_FAILURE_ENDPOINT_NOT_RUN" in sealer.OUTCOME_CLASSES
    assert "TAVONEL_BETTER_ON_PRIMARY" in sealer.OUTCOME_CLASSES


def test_missing_required_receipt_refuses(monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path) -> None:
    monkeypatch.setattr(sealer, "RECEIPTS", tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        sealer.build(outcome_class="NO_MEASURABLE_DIFFERENCE", arms_ran=False,
                     pod={}, note="")
    assert "missing required receipts" in str(excinfo.value)


def test_claiming_arms_ran_without_arm_receipts_refuses(monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:
    """A gate-failure seal and a seal that lost its arm receipts must not look
    the same."""
    monkeypatch.setattr(sealer, "RECEIPTS", tmp_path)
    for filename in sealer.BOUND_RECEIPTS.values():
        (tmp_path / filename).write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        sealer.build(outcome_class="TAVONEL_BETTER_ON_PRIMARY", arms_ran=True,
                     pod={}, note="")
    assert "missing" in str(excinfo.value)


def test_existing_seal_is_verified_not_overwritten(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sealer, "RECEIPTS", tmp_path)
    seal_path = tmp_path / "seal.json"
    body = {"schema": "tavonel.w6-v8-endpoint-seal.v1", "outcome_class": "TAVONEL_WORSE",
            "sealed_at": "2026-08-20T00:00:00+00:00", "receipts": {}, "arm_receipts": {}}
    body["receipt_sha256"] = sealer.canonical_sha256(body)
    seal_path.write_text(json.dumps(body), encoding="utf-8")
    before = seal_path.read_bytes()

    monkeypatch.setattr(sys, "argv", ["seal", "--output", str(seal_path),
                                      "--outcome-class", "TAVONEL_BETTER_ON_PRIMARY"])
    assert sealer.main() == 0
    assert seal_path.read_bytes() == before, "an existing seal was rewritten"


def test_tampered_seal_is_reported_broken(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sealer, "RECEIPTS", tmp_path)
    body = {"schema": "tavonel.w6-v8-endpoint-seal.v1", "outcome_class": "TAVONEL_WORSE",
            "receipts": {}, "arm_receipts": {}}
    body["receipt_sha256"] = sealer.canonical_sha256(body)
    body["outcome_class"] = "TAVONEL_BETTER_ON_PRIMARY"
    assert sealer.verify(body) == 1


def test_bound_receipt_drift_is_reported_broken(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sealer, "RECEIPTS", tmp_path)
    target = tmp_path / "bound.json"
    target.write_text("original", encoding="utf-8")
    body = {"schema": "tavonel.w6-v8-endpoint-seal.v1", "outcome_class": "TAVONEL_WORSE",
            "receipts": {"x": {"file": "bound.json", "present": True,
                               "sha256": sealer.file_sha256(target)}},
            "arm_receipts": {}}
    body["receipt_sha256"] = sealer.canonical_sha256(body)
    assert sealer.verify(body) == 0
    target.write_text("changed", encoding="utf-8")
    assert sealer.verify(body) == 1
