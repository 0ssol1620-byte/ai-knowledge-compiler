"""corpus_reduce on a part whose document repeats a text (WO-D12-9, reviewer finding on ae4edbb).

Two regions of one version with the same text, page and no box share an evidence id; the compiler
emits one evidence object naming both regions. The reduce must place that object once (it was
taken once per unit and refused as REDUCE_GRAPH_INVALID, naming the wrong cause) and cite each
claim's own region (refs were looked up by evidence id, so entities and contradictions cited
both regions).
"""

from __future__ import annotations

import random
from typing import Any

from akc_product_core.compiler import ProductCoreCompiler
from akc_product_core.contracts import ProductCoreDocument
from akc_product_core.corpus_reduce import canonical_form_of_corpus_world, corpus_reduce

from benchmark.product_core_corpus_reduce import (
    RELEASE,
    _document,
    compare_forms,
    compile_parts,
    whole_form_of,
)

COMPILER = ProductCoreCompiler(core_release_digest=RELEASE)
REPEATED = "Acme Holdings reported revenue of 100 million in 2025."
RIVAL = "Acme Holdings reported revenue of 120 million in 2025."


def _documents() -> list[ProductCoreDocument]:
    rng = random.Random(7)
    repeating = _document(rng, 50, 0, sentences=(REPEATED, REPEATED))
    repeating = repeating.model_copy(
        update={
            "regions": tuple(
                region.model_copy(update={"bbox1000": None, "page_number1": 1, "page_index0": 0})
                for region in repeating.regions
            )
        }
    )
    return [repeating, _document(rng, 50, 1, sentences=(RIVAL,))]


def _anchors(item: dict[str, Any]) -> list[str]:
    return [ref["nativeObjectId"] for ref in item["sourceRefs"]]


def test_a_part_that_repeats_a_text_reduces_and_every_object_cites_its_own_region() -> None:
    documents = _documents()
    world, _ = corpus_reduce(compile_parts(COMPILER, documents, [[0], [1]], corpus_id="repeat"))

    units = world["units"]
    repeated = [unit for unit in units if unit["text"] == REPEATED]
    assert len(repeated) == 2
    assert repeated[0]["evidenceId"] == repeated[1]["evidenceId"]
    objects = world["canonicalKnowledgeModel"]["objects"]
    shared = [
        o
        for o in objects
        if o["kind"] == "evidence" and o["payload"]["evidenceId"] == repeated[0]["evidenceId"]
    ]
    assert len(shared) == 1
    assert _anchors(shared[0]) == [repeated[0]["anchor"], repeated[1]["anchor"]]

    anchor_by_logical = {unit["logicalId"]: unit["anchor"] for unit in units}
    claims = {o["stableId"]: o for o in objects if o["kind"] == "claim"}
    assert len(claims) == 3
    for claim in claims.values():
        assert _anchors(claim) == [anchor_by_logical[claim["payload"]["logicalId"]]]
    entities = [o for o in objects if o["kind"] == "entity"]
    assert entities
    for entity in entities:
        assert _anchors(entity) == _anchors(claims[entity["payload"]["claimIds"][0]])
    contradictions = [o for o in objects if o["kind"] == "validation_record"]
    assert len(contradictions) == 2
    for record in contradictions:
        left, right = (claims[claim_id] for claim_id in record["links"])
        assert _anchors(record) == [*_anchors(left), *_anchors(right)]


def test_the_reduced_world_equals_the_whole_compile_of_the_same_documents() -> None:
    documents = _documents()
    world, _ = corpus_reduce(compile_parts(COMPILER, documents, [[0], [1]], corpus_id="repeat"))

    diff = compare_forms(
        whole_form_of(COMPILER, "repeat", documents), canonical_form_of_corpus_world(world)
    )
    assert diff["equal"] is True, diff
