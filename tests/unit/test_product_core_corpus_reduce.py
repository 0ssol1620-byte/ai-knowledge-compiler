"""corpus_reduce: split compile + reduce == whole compile, and every refusal (ADR-008)."""

from __future__ import annotations

import copy
import random
from dataclasses import replace
from typing import Any

import pytest
from akc_cir.base import canonical_json, sha256_digest
from akc_product_core.compiler import ProductCoreCompiler
from akc_product_core.contracts import ProductCoreDocument
from akc_product_core.corpus_reduce import (
    CorpusReduceError,
    ReducePart,
    canonical_form_of_corpus_world,
    corpus_reduce,
)

from benchmark.product_core_corpus_reduce import (
    RELEASE,
    _document,
    compare_forms,
    compile_parts,
    naive_concat_form,
    run_benchmark,
    split_strategies,
    synthetic_corpora,
    whole_form_of,
)

COMPILER = ProductCoreCompiler(core_release_digest=RELEASE)


def _docs(*sentences: tuple[str, ...]) -> list[ProductCoreDocument]:
    rng = random.Random(7)
    return [_document(rng, 50, i, sentences=row) for i, row in enumerate(sentences)]


SEAM = _docs(
    ("Acme Holdings reported revenue of 100 million in 2025.",),
    ("ACME HOLDINGS reported revenue of 120 million in 2025.",),
    ("Globex-Corp International has signed the supply contract in 2024.",),
    ("Globex Corp International has signed the supply contract in 2024.",),
)


def _parts(documents: list[ProductCoreDocument], split: list[list[int]]) -> list[ReducePart]:
    return compile_parts(COMPILER, documents, split, corpus_id="corpus-test")


def _resign(part: ReducePart, response: dict[str, Any]) -> ReducePart:
    """A part whose receipt is valid for an edited World: what a future compiler would send."""
    response["receipt"]["outputSha256"] = sha256_digest(
        canonical_json(response["candidate"]).encode("utf-8")
    )
    return replace(part, response=response)


def test_synthetic_benchmark_is_100_percent_and_detects_the_negative_control() -> None:
    receipt = run_benchmark(synthetic_corpora(), "synthetic")
    summary = receipt["summary"]
    failed = [(case["corpus"], case["strategy"]) for case in receipt["cases"] if not case["pass"]]
    assert failed == []
    assert summary["corpora"] >= 20
    assert summary["passed"] == summary["cases"] >= 200
    assert summary["negativeControlDetected"] is True
    assert summary["gatePassed"] is True
    # The fixtures exercise what the reduce exists for, not only the easy path.
    cases = receipt["cases"]
    assert sum(1 for case in cases if case["reduce"]["crossPartEntityCount"]) >= 50
    assert sum(1 for case in cases if case["reduce"]["crossPartContradictionCount"]) >= 50
    assert sum(1 for case in cases if case["reduce"]["reviewCandidateCount"]) >= 20


def test_comparator_names_the_divergence_of_a_naive_reduce() -> None:
    parts = _parts(SEAM, [[0, 2], [1, 3]])
    diff = compare_forms(whole_form_of(COMPILER, "seam", SEAM), naive_concat_form(parts))
    assert diff["equal"] is False
    assert "objects" in diff["sections"]
    assert any(item.startswith("contradiction_") for item in diff["objects"]["missingFromReduce"])


def test_comparator_detects_one_dropped_object_in_an_otherwise_correct_world() -> None:
    world, _ = corpus_reduce(_parts(SEAM, [[0, 1], [2, 3]]))
    whole = whole_form_of(COMPILER, "seam", SEAM)
    assert compare_forms(whole, canonical_form_of_corpus_world(world))["equal"] is True
    broken = copy.deepcopy(world)
    objects = broken["canonicalKnowledgeModel"]["objects"]
    dropped = next(item for item in objects if item["kind"] == "validation_record")
    objects.remove(dropped)
    diff = compare_forms(whole, canonical_form_of_corpus_world(broken))
    assert diff["equal"] is False
    assert diff["objects"]["missingFromReduce"] == [dropped["stableId"]]


def test_exact_key_entities_merge_across_parts_and_lookalikes_are_only_candidates() -> None:
    world, receipt = corpus_reduce(_parts(SEAM, [[0, 2], [1, 3]]))
    entities = {
        item["payload"]["canonicalName"]: item
        for item in world["canonicalKnowledgeModel"]["objects"]
        if item["kind"] == "entity"
    }
    acme = [name for name in entities if name.casefold() == "acme holdings"]
    assert len(acme) == 1  # one object for "Acme Holdings" and "ACME HOLDINGS"
    assert len(entities[acme[0]]["payload"]["claimIds"]) == 2
    assert {"Globex-Corp International", "Globex Corp International"} <= set(entities)
    globex = {entities[name]["stableId"] for name in entities if name.startswith("Globex")}
    assert len(globex) == 2  # never merged
    assert [set(item["entityIds"]) for item in world["reviewCandidates"]] == [globex]
    assert world["reviewCandidates"][0]["decision"] == "human_review_required"
    assert receipt["crossPartEntityCount"] >= 1
    assert receipt["crossPartContradictionCount"] == 1  # 100 vs 120, in different parts
    assert world["lifecycle"] == "review_required"
    assert world["candidatePromotion"] is False


def test_reduce_is_deterministic_and_independent_of_part_input_order() -> None:
    parts = _parts(SEAM, [[0], [1, 2], [3]])
    first = corpus_reduce(parts)
    assert corpus_reduce(list(reversed(parts))) == first
    assert corpus_reduce(parts) == first


def test_provenance_is_kept_per_part() -> None:
    parts = _parts(SEAM, [[0, 1], [2, 3]])
    world, receipt = corpus_reduce(parts)
    assert [row["partIndex"] for row in world["parts"]] == [0, 1]
    assert [row["documentIds"] for row in world["parts"]] == [
        [item["documentId"] for item in part.response["candidate"]["canonicalDocuments"]]
        for part in parts
    ]
    part_activities = {
        item["createdByActivity"]
        for part in parts
        for item in part.response["candidate"]["canonicalKnowledgeModel"]["objects"]
    }
    claim_activities = {
        item["createdByActivity"]
        for item in world["canonicalKnowledgeModel"]["objects"]
        if item["kind"] == "claim"
    }
    assert claim_activities <= part_activities  # copied objects keep the part that made them
    assert receipt["inputs"] == [
        {
            "partIndex": part.part_index,
            "requestId": part.request_id,
            "inputSha256": part.input_sha256,
            "outputSha256": part.response["receipt"]["outputSha256"],
        }
        for part in parts
    ]
    assert receipt["outputSha256"] == sha256_digest(canonical_json(world).encode("utf-8"))


def test_a_corpus_without_claims_reduces_and_says_so() -> None:
    documents = _docs(("lowercase ocr fragment without predicate",), ("another fragment line",))
    world, _ = corpus_reduce(_parts(documents, [[0], [1]]))
    assert "SEMANTIC_CLAIMS_EMPTY" in world["reviewReasons"]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda parts: [], "REDUCE_NO_PARTS"),
        (lambda parts: parts[:1], "REDUCE_PART_MISSING"),
        (lambda parts: [parts[0], parts[0]], "REDUCE_PART_DUPLICATED"),
    ],
)
def test_incomplete_part_sets_are_refused(mutate: Any, code: str) -> None:
    with pytest.raises(CorpusReduceError) as caught:
        corpus_reduce(mutate(_parts(SEAM, [[0, 1], [2, 3]])))
    assert caught.value.code == code


def test_parts_that_disagree_on_the_count_are_refused() -> None:
    parts = _parts(SEAM, [[0, 1], [2, 3]])
    lying = replace(parts[1], part_count=3)
    with pytest.raises(CorpusReduceError) as caught:
        corpus_reduce([parts[0], lying])
    assert caught.value.code == "REDUCE_PART_COUNT_MISMATCH"


def test_a_forged_part_world_fails_its_receipt() -> None:
    parts = _parts(SEAM, [[0, 1], [2, 3]])
    response = copy.deepcopy(dict(parts[1].response))
    response["candidate"]["units"][0]["text"] = "Acme Holdings reported revenue of 999 million."
    forged = replace(parts[1], response=response)
    with pytest.raises(CorpusReduceError) as caught:
        corpus_reduce([parts[0], forged])
    assert caught.value.code == "REDUCE_RECEIPT_INVALID"
    wrong_input = replace(parts[1], input_sha256="sha256:" + "0" * 64)
    with pytest.raises(CorpusReduceError) as caught:
        corpus_reduce([parts[0], wrong_input])
    assert caught.value.code == "REDUCE_RECEIPT_INVALID"


def test_the_same_document_with_different_content_in_two_parts_is_an_id_collision() -> None:
    changed = SEAM[1].model_copy(
        update={
            "regions": (
                SEAM[1]
                .regions[0]
                .model_copy(
                    update={"text": "ACME HOLDINGS reported revenue of 777 million in 2025."}
                ),
            )
        }
    )
    first = compile_parts(COMPILER, [SEAM[0], SEAM[1]], [[0, 1]], corpus_id="corpus-test")[0]
    second = compile_parts(COMPILER, [changed, SEAM[2]], [[0, 1]], corpus_id="corpus-test")[0]
    second = replace(second, part_index=1)
    first = replace(first, part_count=2)
    second = replace(second, part_count=2)
    with pytest.raises(CorpusReduceError) as caught:
        corpus_reduce([first, second])
    assert caught.value.code == "REDUCE_ID_COLLISION"


def test_an_identical_overlap_is_a_union_not_a_collision() -> None:
    whole = whole_form_of(COMPILER, "seam", SEAM)
    world, _ = corpus_reduce(_parts(SEAM, [[0, 1, 2], [2, 3]]))
    assert compare_forms(whole, canonical_form_of_corpus_world(world))["equal"] is True


def test_scope_and_operation_mismatches_are_refused() -> None:
    parts = _parts(SEAM, [[0, 1], [2, 3]])
    for change, code in (
        ({"collection_id": "collection-other"}, "REDUCE_PART_SCOPE_MISMATCH"),
        ({"corpus_id": "corpus-other"}, "REDUCE_PART_SCOPE_MISMATCH"),
        ({"operation_class": "incremental_recompile"}, "REDUCE_PART_NOT_INITIAL"),
    ):
        with pytest.raises(CorpusReduceError) as caught:
            corpus_reduce([parts[0], replace(parts[1], **change)])
        assert caught.value.code == code


def test_a_rejected_part_or_an_unknown_review_reason_is_refused_not_dropped() -> None:
    parts = _parts(SEAM, [[0, 1], [2, 3]])
    rejected = copy.deepcopy(dict(parts[1].response))
    rejected["status"] = "rejected"
    with pytest.raises(CorpusReduceError) as caught:
        corpus_reduce([parts[0], _resign(parts[1], rejected)])
    assert caught.value.code == "REDUCE_PART_REJECTED"
    unknown = copy.deepcopy(dict(parts[1].response))
    unknown["candidate"]["reviewReasons"] = ["SOMETHING_NEW:x"]
    with pytest.raises(CorpusReduceError) as caught:
        corpus_reduce([parts[0], _resign(parts[1], unknown)])
    assert caught.value.code == "REDUCE_REVIEW_REASON_UNKNOWN"


def test_a_part_world_with_a_dangling_object_is_refused() -> None:
    parts = _parts(SEAM, [[0, 1], [2, 3]])
    response = copy.deepcopy(dict(parts[1].response))
    objects = response["candidate"]["canonicalKnowledgeModel"]["objects"]
    objects.remove(next(item for item in objects if item["kind"] == "evidence"))
    with pytest.raises(CorpusReduceError) as caught:
        corpus_reduce([parts[0], _resign(parts[1], response)])
    assert caught.value.code == "REDUCE_GRAPH_INVALID"


def test_split_strategies_cover_every_document_exactly_once_except_overlap() -> None:
    for n in (3, 7, 12, 30):
        for name, (split, _) in split_strategies(n).items():
            members = sorted(i for part in split for i in part)
            if name == "overlap-k3":
                assert set(members) == set(range(n))
            else:
                assert members == list(range(n)), name
            assert all(split), name
