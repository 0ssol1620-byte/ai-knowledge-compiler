from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V01 = ROOT / "research" / "experiments" / "SEM-RISK-CONF-01"
V02 = ROOT / "research" / "experiments" / "SEM-RISK-CONF-02"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v02_transport_scripts_are_syntax_valid() -> None:
    for name in ("freeze_transport_amendment.py", "acquire_selected_inputs.py"):
        ast.parse((V02 / name).read_text(encoding="utf-8"), filename=name)


def test_v02_keeps_frozen_protocol_and_selection_byte_identical() -> None:
    for rel in (
        "protocol.json",
        "selection-manifest.json",
        "receipts/protocol-freeze.json",
        "receipts/selection-seal.json",
    ):
        assert digest(V02 / rel) == digest(V01 / rel)


def test_v02_keeps_science_execution_and_evaluation_code_byte_identical() -> None:
    for rel in (
        "run_lane_a_native.py",
        "build_inference_manifests.py",
        "evaluate_confirmatory.py",
    ):
        assert digest(V02 / rel) == digest(V01 / rel)


def test_v02_transport_rule_is_resolution_only_and_fail_closed() -> None:
    source = (V02 / "acquire_selected_inputs.py").read_text(encoding="utf-8")
    assert "complete_tree(current_rev, \"images\")" in source
    assert "len(matches) != 1" in source
    assert "selected_cases_changed" in source
    assert '"ground_truth_acquired": False' in source
    assert "OmniDocBench.json" not in source


def test_v02_frozen_selection_still_has_64_plus_64_and_18_dev_exclusions() -> None:
    selection = json.loads((V02 / "selection-manifest.json").read_text(encoding="utf-8"))
    assert selection["counts"] == {
        "development_exclusions": 18,
        "lane_a": 64,
        "lane_b": 64,
        "total": 128,
    }
