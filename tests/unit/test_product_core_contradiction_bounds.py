"""Contradiction candidate bounds (D0 2026-11-09): quadratic pairing fails closed, visibly.

Below the bounds nothing changes (every existing fixture's output is byte-identical; see the PR).
Past them a topic group emits no pair and is named in a review reason with its counts.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import replace
from itertools import combinations

import pytest
from akc_cir.base import canonical_json
from akc_cir.models import BBox1000, BlockType
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.compiler import (
    OUTPUT_BUDGET_BYTES,
    CoreOutputTooLargeError,
    wire_payload,
)
from akc_product_core.contracts import ProductCoreRegion
from akc_product_core.corpus_reduce import canonical_form_of_corpus_world, corpus_reduce
from akc_product_core.semantics import (
    MAX_CONTRADICTION_PAIRS_PER_COMPILE,
    MAX_CONTRADICTION_PAIRS_PER_GROUP,
    SemanticClaim,
    SemanticSource,
    _candidate_pair_count,
    compile_semantics,
)

from benchmark.product_core_corpus_reduce import _document as _bench_document
from benchmark.product_core_corpus_reduce import compare_forms, compile_parts, whole_form_of

from .test_product_core_bridge import RELEASE, _document, _request, _sha

COMPILER = ProductCoreCompiler(core_release_digest=RELEASE)
OVERFLOW_PREFIXES = ("CONTRADICTION_GROUP_TOO_LARGE:", "CONTRADICTION_PAIR_BUDGET_EXCEEDED:")


def _scan_lines() -> list[tuple[int, str]]:
    """The text of the D0 proof scan (tavonel-scan-test-12p-20261104.pdf, sha256:b4251c93...).

    Exactly what its generator drew: per page a title, a subtitle, 18 numbered lines and a table
    row. The 216 numbered lines are one sentence that differs only in its numbers, so they form
    one topic group: 216 claims and C(216, 2) = 23,220 candidate pairs.
    """
    rows: list[tuple[int, str]] = []
    for page in range(1, 13):
        rows.append((page, f"TAVONEL page-range scan test, page {page} of 12"))
        rows.append((page, "Operator-written document for the OCR range-mode check, 2026-11-04."))
        rows.extend(
            (
                page,
                f"Line {line:02d} on page {page}: the reader must return this line inside "
                f"range {(page - 1) // 8 + 1}.",
            )
            for line in range(1, 19)
        )
        rows.append((page, f"Table cell A{page}  |  value {page * 37}  |  unit mm"))
    return rows


def _scan_request() -> ProductCoreCompileRequest:
    regions = []
    for order, (page, text) in enumerate(_scan_lines()):
        row = order % 21
        regions.append(
            ProductCoreRegion(
                region_id=f"ocr-p{page}-r{row}",
                page_index0=page - 1,
                page_number1=page,
                order=order,
                block_type=BlockType.PARAGRAPH,
                text=text,
                bbox1000=BBox1000((89, 57 + row * 40, 887, 74 + row * 40)),
                confidence=0.98,
                authority="unclassified",
            )
        )
    document = _document("d0-scan", "\n".join(text for _, text in _scan_lines()), page=12)
    return _request((document.model_copy(update={"regions": tuple(regions)}),), request_id="d0")


def _ledger(word: str, numbers: range) -> tuple[SemanticSource, ...]:
    """One topic group: the same sentence with a different number per claim."""
    return tuple(
        SemanticSource(
            logical_id=f"{word}-{number}",
            source_id=f"source-{word}",
            source_version_id=f"version-{word}",
            evidence_id=f"evidence-{word}-{number}",
            text=f"{word} ledger entry {number} must hold the stated balance.",
            authority="unclassified",
        )
        for number in numbers
    )


def test_the_scan_fixture_is_the_d0_input() -> None:
    texts = [text for _, text in _scan_lines()]
    assert len(texts) == 252
    assert hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest() == (
        "7951956560a8684536458ee4c07e6ec78546c02ce8039f8e65a10c17f3c6dfbd"
    )


def test_d0_scan_compiles_under_the_budget_with_its_group_named() -> None:
    response = COMPILER.compile(_scan_request(), input_sha256=_sha("d0-scan"))
    candidate = response.candidate
    objects = candidate.canonical_knowledge_model["objects"]

    # Before the bound: 23,220 validation records and a 168.8 MB response, refused at 32 MiB.
    assert sum(1 for item in objects if item["kind"] == "claim") == 216
    assert [item for item in objects if item["kind"] == "validation_record"] == []
    assert not any(r.startswith("CONTRADICTION_CANDIDATE:") for r in candidate.review_reasons)
    [named] = [r for r in candidate.review_reasons if r.startswith(OVERFLOW_PREFIXES)]
    assert named.startswith("CONTRADICTION_GROUP_TOO_LARGE:contradiction_group_")
    assert named.endswith(":claims=216:pairs=23220")
    assert candidate.lifecycle == "review_required"
    report = next(f for f in candidate.package.files if f.path == "validation/report.json")
    assert named in json.loads(report.content)["reviewReasons"]

    package_bytes = sum(file.size_bytes for file in candidate.package.files)
    response_bytes = len(canonical_json(wire_payload(response)).encode("utf-8"))
    assert package_bytes < OUTPUT_BUDGET_BYTES // 8
    assert response_bytes < OUTPUT_BUDGET_BYTES // 4


def test_the_bound_does_not_bypass_the_output_budget() -> None:
    # Failure path: an output still over the budget is refused, never truncated; the counts
    # say the contradiction path is no longer what made it large.
    with pytest.raises(CoreOutputTooLargeError) as refused:
        ProductCoreCompiler(core_release_digest=RELEASE, output_budget_bytes=1_000_000).compile(
            _scan_request(), input_sha256=_sha("d0-scan")
        )
    counts = refused.value.detail["counts"]
    assert isinstance(counts, dict)
    assert counts["claims"] == 216
    assert counts["contradictionPairs"] == 0


def test_a_group_at_the_bound_pairs_and_one_past_it_is_named() -> None:
    at_bound = compile_semantics(_ledger("Alpha", range(1, 33)))
    assert len(at_bound.contradictions) == MAX_CONTRADICTION_PAIRS_PER_GROUP == 496
    assert at_bound.contradiction_overflow == ()

    past = compile_semantics(_ledger("Alpha", range(1, 34)))
    assert past.contradictions == ()
    assert past.profile_record()["contradictionCandidateCount"] == 0
    [group] = past.contradiction_overflow
    assert (group.cause, group.claim_count, group.candidate_pairs) == ("group", 33, 528)
    assert group.topic_key == "alpha ledger entry must hold stated balance."
    assert group.review_reason() == (
        f"CONTRADICTION_GROUP_TOO_LARGE:{group.group_id}:claims=33:pairs=528"
    )


def test_the_compile_bound_admits_the_smallest_groups_first() -> None:
    sources = (
        *_ledger("Alpha", range(1, 33)),  # 496 pairs
        *_ledger("Bravo", range(1, 33)),  # 496 pairs
        *_ledger("Charlie", range(1, 10)),  # 36 pairs
    )
    result = compile_semantics(sources)

    assert len(result.contradictions) == 36 + 496 <= MAX_CONTRADICTION_PAIRS_PER_COMPILE
    topics = {item.topic_key.split()[0] for item in result.contradictions}
    assert topics == {"charlie", "alpha"}
    [group] = result.contradiction_overflow
    assert (group.cause, group.claim_count, group.candidate_pairs) == ("compile", 32, 496)
    assert group.review_reason().startswith("CONTRADICTION_PAIR_BUDGET_EXCEEDED:")
    assert group.topic_key.startswith("bravo ")


def _enumerated(group: list[SemanticClaim]) -> int:
    """The pairing rule itself, pair by pair: the oracle for the O(n) count."""
    return sum(
        1
        for left, right in combinations(group, 2)
        if (
            left.numeric_values
            and right.numeric_values
            and left.numeric_values != right.numeric_values
        )
        or left.polarity != right.polarity
    )


def test_the_pair_count_equals_the_pairwise_rule() -> None:
    [base] = compile_semantics(_ledger("Delta", range(1, 2))).claims
    rng = random.Random(20261109)
    values: tuple[tuple[str, ...], ...] = ((), ("1",), ("2",), ("1", "2"), ("2", "1"))
    for _ in range(300):
        group = [
            replace(
                base,
                claim_id=f"claim-{index}",
                polarity=rng.choice(("positive", "negative")),
                numeric_values=rng.choice(values),
            )
            for index in range(rng.randint(0, 24))
        ]
        assert _candidate_pair_count(group) == _enumerated(group)


def test_reduce_recomputes_the_bound_over_the_union_and_accepts_a_named_part() -> None:
    rng = random.Random(9)
    documents = [
        _bench_document(
            rng,
            60,
            index,
            sentences=[
                f"Echo ledger entry {number} must hold the stated balance." for number in numbers
            ],
        )
        for index, numbers in enumerate((range(1, 19), range(19, 37), range(37, 54)))
    ]
    parts = compile_parts(COMPILER, documents, [[0, 1], [2]], corpus_id="corpus-bounds")
    part_reasons = [
        [r for r in part.response["candidate"]["reviewReasons"] if r.startswith(OVERFLOW_PREFIXES)]
        for part in parts
    ]
    # Two documents (35-36 claims) are past the bound on their own; one (17-18) is not.
    assert sorted(len(reasons) for reasons in part_reasons) == [0, 1]

    world, _ = corpus_reduce(parts)

    named = [r for r in world["reviewReasons"] if r.startswith(OVERFLOW_PREFIXES)]
    assert len(named) == 1
    assert named[0].endswith(":claims=53:pairs=1378")
    whole = whole_form_of(COMPILER, "bounds", documents)
    assert compare_forms(whole, canonical_form_of_corpus_world(world))["equal"] is True
