from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import akc_cir.entity
import akc_product_core.semantics
import akc_retrieval.entity_resolution
import pytest

from benchmark.entity_resolution import compare_resolvers as cr

FIXTURE = Path(cr.__file__).parent / "fixtures" / "entity_pairs_synthetic_v1.jsonl"


def _side(pid: str, text: str) -> dict[str, Any]:
    return {
        "text": text,
        "type": "organization",
        "attributes": {},
        "external_ids": {},
        "context_ids": [],
        "evidence_id": f"ev-{pid}-{text}",
    }


def _row(pid: str, left: str, right: str, gold: str) -> dict[str, Any]:
    return {
        "pair_id": pid,
        "stratum": "t",
        "provenance": "synthetic",
        "left": _side(pid, left),
        "right": _side(pid, right),
        "gold": gold,
    }


def test_every_stratum_has_at_least_ten_pairs() -> None:
    rows = cr.load_fixture(FIXTURE)
    counts = Counter(row["stratum"] for row in rows)
    assert len(rows) >= 120
    assert len(counts) == 10
    assert min(counts.values()) >= 10


def test_adapters_call_the_real_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_row("p1", "Acme Corp", "Acme Corp", "same")]

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("resolver down")

    for module, attr, name in (
        (akc_cir.entity, "resolve_mention", "akc_cir.entity"),
        (akc_retrieval.entity_resolution, "resolve_entities", "akc_retrieval.entity_resolution"),
        (akc_product_core.semantics, "compile_semantics", "product_core.label_hash"),
    ):
        with monkeypatch.context() as m:
            m.setattr(module, attr, boom)
            result = cr.evaluate(rows)
        assert "RuntimeError" in result[name]["error"]
        assert "strata" not in result[name]
        assert all("strata" in result[n] for n in result if n != name)


def test_report_counts_a_false_merge() -> None:
    rows = [
        _row("a", "Acme Corp", "Acme Corp", "different"),
        _row("b", "Acme Corp", "Acme Corp", "same"),
    ]
    cell = cr.evaluate(rows, {"x": lambda r: cr.MERGE})["x"]["strata"]["ALL"]
    assert (cell["false_merges"], cell["true_merges"], cell["merge_precision"]) == (1, 1, 0.5)


def test_product_core_rule_merges_same_label() -> None:
    # Documents the shipped behaviour as a measured row, not as expected-correct.
    row = _row("pc", "Mercury Systems", "Mercury Systems", "different")
    assert cr.product_core_adapter(row) == cr.MERGE
    cell = cr.evaluate([row], {"pc": cr.product_core_adapter})["pc"]["strata"]["ALL"]
    assert cell["false_merges"] == 1


def test_report_refuses_a_fixture_row_without_provenance(tmp_path: Path) -> None:
    row = _row("np", "A B", "A B", "same")
    del row["provenance"]
    path = tmp_path / "f.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        cr.load_fixture(path)
    row["provenance"] = "real"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="synthetic"):
        cr.load_fixture(path)
