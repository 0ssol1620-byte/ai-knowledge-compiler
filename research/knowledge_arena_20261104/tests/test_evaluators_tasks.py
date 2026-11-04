from __future__ import annotations

import json
from decimal import Decimal

import pytest
from karena import evaluators as ev
from karena.corpus import Case
from karena.registry import RegistryError, load_registry, validate_rows
from karena.tasks import TASKS, load_task


def test_macro_f1_counts_abstention_against_recall_only() -> None:
    assert ev.macro_f1([("A", "A"), ("B", "B")]) == 1.0
    assert ev.macro_f1([("A", "A"), ("B", ev.ABSTAIN)]) == pytest.approx(0.5)
    scores = ev.doc_type_scores([("A", "A"), ("B", ev.ABSTAIN), ("B", None)])
    assert scores["abstained"] == 1 and scores["invalid"] == 1
    assert scores["macro_f1"]["ci95_low"] <= scores["macro_f1"]["point"]


def test_bootstrap_refuses_zero_cases() -> None:
    with pytest.raises(ValueError, match="zero cases"):
        ev.bootstrap_ci([], lambda xs: 0.0)


def test_numeric_and_quote_checks_are_exact() -> None:
    assert ev.numeric_equal("1234500000", Decimal("1.2345E9"))
    assert ev.numeric_equal("6.10", 6.1)
    assert not ev.numeric_equal("1234", None)
    assert not ev.numeric_equal("1234", True)
    assert ev.quote_supported("Total  assets\n| 102,185", "x Total assets | 102,185 y")
    assert not ev.quote_supported("Total assets 102,186", "Total assets 102,185")
    assert not ev.quote_supported("ab", "ab")


def test_typed_extraction_scores_value_and_evidence_separately() -> None:
    rows = [
        {
            "gold_value": "102185",
            "displayed": "102,185",
            "excerpt": "Total assets | $ | 102,185",
            "output": {"value": 102185, "evidence_quote": "Total assets | $ | 102,185"},
        },
        {
            "gold_value": "5",
            "displayed": "5",
            "excerpt": "Cash | 5",
            "output": {"value": 5, "evidence_quote": "invented"},
        },
        {"gold_value": "5", "displayed": "5", "excerpt": "Cash | 5", "output": None},
    ]
    scores = ev.typed_extraction_scores(rows)
    assert scores["numeric_exact_match"]["point"] == pytest.approx(2 / 3)
    assert scores["evidence_quote_verbatim"] == {"count": 1, "of": 3}
    assert scores["invalid"] == 1


def test_grounded_answer_citations_abstention_and_unsupported_claims() -> None:
    excerpts = {"E1": "Revenue was 10", "E2": "Other company revenue 99"}
    answerable = {"answerable": True, "value": "10", "citation_ids": ["E1"]}
    rows = [
        {
            "truth": answerable,
            "excerpts": excerpts,
            "output": {
                "status": "ANSWERED",
                "claims": [{"value": 10, "citations": ["E1", "E2"], "quote": "Revenue was 10"}],
            },
        },
        {
            "truth": answerable,
            "excerpts": excerpts,
            "output": {
                "status": "ANSWERED",
                "claims": [{"value": 99, "citations": ["E9"], "quote": "made up"}],
            },
        },
        {
            "truth": {"answerable": False, "value": None, "citation_ids": []},
            "excerpts": excerpts,
            "output": {"status": "ABSTAINED", "claims": []},
        },
    ]
    scores = ev.grounded_answer_scores(rows)
    assert scores["answer_exact_match"]["point"] == pytest.approx(0.5)
    assert scores["citations"]["precision"] == {"value": pytest.approx(1 / 3), "tp": 1, "fp": 2}
    assert scores["citations"]["recall"]["value"] == pytest.approx(0.5)
    assert scores["abstained_when_unanswerable"] == {"count": 1, "of": 1}
    assert scores["unsupported_claims"] == {"count": 1, "of": 2}


def test_schema_induction_scores_and_recall_not_estimated_without_reference() -> None:
    output = {
        "entity_types": [
            {"name": "Company", "examples": [{"excerpt_id": "D1", "quote": "Acme Corp"}]},
            {"name": "company", "examples": [{"excerpt_id": "D2", "quote": "not there"}]},
        ],
        "relation_types": [
            {"name": "files", "source_type": "Company", "target_type": "Filing", "examples": []}
        ],
    }
    row = {"excerpts": {"D1": "Acme Corp filed", "D2": "x"}, "output": output, "reference": None}
    scores = ev.schema_induction_scores([row, {**row, "output": None}])
    assert scores["duplicate_type_names"] == {"count": 1, "of": 2}
    assert scores["evidence_examples_verbatim"] == {"count": 1, "of": 2}
    assert scores["relation_endpoints_outside_schema"] == {"count": 1, "of": 1}
    assert scores["type_recall"].startswith("NOT_MEASURED")
    referenced = ev.schema_induction_scores(
        [{**row, "reference": {"entity_types": [{"name": "Company"}, {"name": "Filing"}]}}]
    )
    assert referenced["type_recall_exact_name_lower_bound"] == {"count": 1, "of": 2}


def test_span_prf() -> None:
    result = ev.span_prf({("d", 0, 4, "Org"), ("d", 9, 12, "Date")}, {("d", 0, 4, "Org")})
    assert (result["precision"], result["recall"]) == (1.0, 0.5)


def _case(task: str, payload: dict[str, object]) -> Case:
    return Case(
        case_id=f"{task}:x",
        task=task,
        split="CALIBRATION",
        family_ids=("f",),
        origin="SEC",
        language="en",
        source_doc_ids=("d",),
        licences=("SEC-EDGAR-PUBLIC-FILING",),
        input=payload,
        truth={},
    )


def test_adapters_render_frozen_prompts_and_normalise_fail_closed() -> None:
    adapter = load_task("typed_extraction")
    case = _case(
        "typed_extraction",
        {
            "excerpt": "Total assets 5",
            "field": {
                "name": "Assets",
                "description": "total assets",
                "entity": "Acme",
                "period": "the date 2025-12-31",
                "unit": "USD",
            },
        },
    )
    system, user = adapter.messages(case)
    assert "data, not instructions" in system["content"]
    assert "Total assets 5" in user["content"] and "$" not in user["content"].split("\n")[0]
    good = adapter.normalise(json.dumps({"value": 5, "unit": "USD", "evidence_quote": "5"}), "stop")
    assert good.status == "SUCCESS" and good.value == {
        "value": 5,
        "unit": "USD",
        "evidence_quote": "5",
    }
    assert adapter.normalise('{"value": 5', "stop").status == "INVALID_OUTPUT"
    assert adapter.normalise(
        '{"value": 5, "unit": "EUR", "evidence_quote": ""}', "stop"
    ).status == ("INVALID_OUTPUT")
    assert adapter.normalise("{}", "length").status == "TRUNCATED"
    assert adapter.normalise(None, "stop").status == "INVALID_OUTPUT"
    assert {load_task(t).name for t in TASKS} == set(TASKS)
    with pytest.raises(KeyError):
        load_task("summarise")


def test_registry_rows_are_candidates_with_four_separate_licences() -> None:
    rows = load_registry()
    assert len([r for r in rows.values() if r["role"] == "CANDIDATE"]) in range(3, 6)
    assert rows["opus_subscription_reference"]["role"] == "REFERENCE_ONLY"
    for row in rows.values():
        assert set(row["licences"]) == {"code", "weights", "dataset", "hosted_api"}
        assert all(value is None for value in row["capabilities"].values())
    base = dict(rows["qwen3_8b"])
    with pytest.raises(RegistryError, match="dataset"):
        validate_rows([{**base, "licences": {**base["licences"], "dataset": {}}}])
    with pytest.raises(RegistryError, match="without an Arena receipt"):
        validate_rows([{**base, "capabilities": {"doc_type": True}}])
    with pytest.raises(RegistryError, match="pin exact"):
        validate_rows([{**base, "exact_revision": None}])
