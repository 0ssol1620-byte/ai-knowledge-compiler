"""Rules and committed-artifact invariants for the Router Oracle Dataset (ROD-v1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from rules import family_of, page_class, script_family, split_of  # noqa: E402


def test_family_groups_pages_of_one_source_document() -> None:
    assert family_of("PPT_1001115_eng_page_003.png") == "PPT_1001115_eng"
    assert family_of("docstructbench_x-60368448.pdf_343.jpg") == "docstructbench_x-60368448"
    assert family_of("page-d1561665-5359-42fe-920c-d6e3bff81953.png") == (
        "page-d1561665-5359-42fe-920c-d6e3bff81953"
    )


def test_split_is_deterministic_and_family_level() -> None:
    assert split_of("PPT_1001115_eng") == split_of("PPT_1001115_eng")
    assert split_of("PPT_1001115_eng") in {"ROUTER_TRAIN", "ROUTER_CALIBRATION", "ROUTER_HOLDOUT"}
    # a different seed is a different split, so a re-split is a new policy version by construction
    families = [f"family-{i}" for i in range(500)]
    assert [split_of(f) for f in families] != [split_of(f, seed="other") for f in families]


def test_page_class_priority_and_script_family() -> None:
    assert (
        page_class({"special_issue": ["fuzzy_scan", "table_full_line"], "subset": "table_hard"})
        == "DEGRADED"
    )
    assert page_class({"special_issue": ["table_full_line"], "layout": "double_column"}) == "TABLE"
    assert page_class({"subset": "equation_hard", "layout": "double_column"}) == "FORMULA"
    assert page_class({"layout": "three_column"}) == "MULTI_COLUMN"
    assert page_class({"layout": "single_column", "special_issue": []}) == "SIMPLE"
    assert script_family("simplified_chinese") == "han"
    assert script_family(None) == "other"


@pytest.fixture(scope="module")
def artifacts() -> tuple[dict, dict]:
    manifest = HERE / "SPLIT_MANIFEST.json"
    results = HERE / "RESULTS.json"
    if not manifest.exists() or not results.exists():
        pytest.skip("committed ROD-v1 artifacts absent")
    return json.loads(manifest.read_text(encoding="utf-8")), json.loads(
        results.read_text(encoding="utf-8")
    )


def test_committed_split_has_no_family_leakage(artifacts: tuple[dict, dict]) -> None:
    manifest, _ = artifacts
    groups = {name: set(ids) for name, ids in manifest["family_ids_per_split"].items()}
    names = sorted(groups)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            assert not (groups[a] & groups[b]), f"{a} and {b} share families"
    assert sum(manifest["pages_per_split"].values()) == manifest["pages_in_dataset"]
    assert (
        manifest["pages_in_dataset"] + manifest["pages_excluded_no_text_ground_truth"]
        == manifest["pages_total_gt"]
    )
    for family in groups["ROUTER_HOLDOUT"]:
        assert split_of(family) == "ROUTER_HOLDOUT"


def test_committed_results_respect_permission_and_oracle_invariants(
    artifacts: tuple[dict, dict],
) -> None:
    _, results = artifacts
    assert results["freeze"]["trusted_tau"] == 0.05
    assert results["cost_imputed_pages_by_model"] == {}, (
        "every path outcome must carry a measured cost"
    )
    for name, block in results["permitted_sets"].items():
        permitted = set(block["permitted"])
        assert set(block["policy"]["table"].values()) <= permitted, name
        assert block["policy"]["default"] in permitted
        arms = block["holdout_arms"]
        assert arms["ORACLE_DIAGNOSTIC"]["mean_oracle_regret_utility"] == 0.0
        n = {arm["n_pages"] for arm in arms.values()}
        assert len(n) == 1, "every arm is scored on the same holdout denominator"
        for arm in arms.values():
            assert set(arm["route_mix"]) <= permitted, arm["arm"]
            assert abs(arm["trusted_rate"] + arm["trust_violation_rate"] - 1.0) < 1e-9
