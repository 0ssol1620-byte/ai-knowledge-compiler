"""Report-only semantic funnel: opt-in counters that cannot change any other byte."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from akc_cir.base import canonical_json, sha256_digest
from akc_product_core import ProductCoreCompiler, semantics
from akc_product_core.api import semantic_funnel_enabled
from akc_product_core.semantics import (
    FUNNEL_MENTION_SCAN_BUDGET_CHARS,
    FUNNEL_MENTION_SCAN_MAX_CHARS,
    SemanticSource,
    compile_semantics,
)

from .test_product_core_bridge import RELEASE, _document, _request

# sha256 of {package path: file sha256}, computed on the code BEFORE the funnel existed
# (K1 release source 28b6b65c) for the fixture below. Flag off must still reproduce it.
BASELINE_PACKAGE_DIGEST = "sha256:f465c901c77cde38a9669c384c406460424f69d53a4f04d13a086824a55ba740"
BASELINE_OUTPUT_SHA256 = "sha256:f6fe220e001d4f27956923877d8e31ab62ecc3e4990773846654df561103d5df"

_DOCS = (
    ("filing-a", "Revenue is 100 million won. TAVONEL Research Institute reported the result."),
    ("policy-b", "The board approved the policy.\nSee page 3\nWhat is the policy?"),
)


def _source(logical_id: str, text: str) -> SemanticSource:
    return SemanticSource(
        logical_id=logical_id,
        source_id=f"source-{logical_id}",
        source_version_id=f"version-{logical_id}",
        evidence_id=f"evidence-{logical_id}",
        text=text,
        authority="regulatory_filing",
    )


def _compile(*, funnel: bool) -> Any:
    compiler = ProductCoreCompiler(core_release_digest=RELEASE, semantic_funnel=funnel)
    request = _request(tuple(_document(name, text) for name, text in _DOCS), request_id="funnel-1")
    return compiler.compile(request, input_sha256="sha256:" + "b" * 64)


def _package(response: Any) -> dict[str, str]:
    return {file.path: file.content for file in response.candidate.package.files}


def test_flag_off_is_byte_identical_to_the_code_before_the_funnel() -> None:
    response = _compile(funnel=False)
    hashes = {file.path: file.sha256 for file in response.candidate.package.files}
    assert sha256_digest(canonical_json(hashes)) == BASELINE_PACKAGE_DIGEST
    assert response.receipt.output_sha256 == BASELINE_OUTPUT_SHA256
    assert "semanticFunnel" not in json.loads(_package(response)["validation/report.json"])


def test_flag_on_changes_only_the_report_and_only_by_the_funnel_key() -> None:
    off = _compile(funnel=False)
    on = _compile(funnel=True)
    package_off, package_on = _package(off), _package(on)
    assert package_off.keys() == package_on.keys()
    changed = {path for path in package_off if package_off[path] != package_on[path]}
    assert changed == {"validation/report.json"}
    report_on = json.loads(package_on["validation/report.json"])
    funnel = report_on.pop("semanticFunnel")
    assert report_on == json.loads(package_off["validation/report.json"])
    assert off.candidate.artifact_hashes == on.candidate.artifact_hashes
    assert off.candidate.units == on.candidate.units
    assert funnel["final"]["claims"] == report_on["claimCount"]
    assert funnel["final"]["entities"] == report_on["entityCount"]


def test_a_known_entity_lost_at_the_claim_filter_is_counted_by_reason() -> None:
    result = compile_semantics(
        (
            _source(
                "doc",
                "Acme Holdings Group is the supplier.\n"
                "Prepared by Zeta Partners Limited\n"
                "Prepared by Acme Holdings Group\n"
                "Who is Acme Holdings Group?\n"
                ".4",
            ),
        ),
        funnel=True,
    )
    funnel = result.funnel
    assert funnel is not None
    assert funnel["enabled"] is True
    assert [entity.canonical_name for entity in result.entities] == ["Acme Holdings Group"]
    assert funnel["sources"] == {"total": 1, "emptyText": 0}
    assert funnel["sentences"] == {
        "segments": 5,
        "droppedShortOrNonAlnum": 1,
        "wholeTextFallback": 0,
        "kept": 4,
    }
    assert funnel["claimFilter"] == {
        "allowed": 1,
        "excluded": 3,
        "excludedByReason": {"no_predicate": 2, "question": 1},
    }
    # The dependency made visible: entities are read only from claim-passing sentences.
    assert funnel["mentionsInClaimExcludedSentences"] == {
        "mentionScanMaxChars": FUNNEL_MENTION_SCAN_MAX_CHARS,
        "mentionScanBudgetChars": FUNNEL_MENTION_SCAN_BUDGET_CHARS,
        "scannedSentences": 3,
        "skippedByReason": {},
        "complete": True,
        "mentions": 3,
        "byReason": {"no_predicate": 2, "question": 1},
        "distinctEntities": 2,
        "distinctEntitiesOnlyInExcluded": 1,
    }
    assert funnel["mentions"] == {
        "rawByPattern": {"named_entity": 1},
        "droppedTooShort": 0,
        "mergedWithinSentence": 0,
        "emitted": 1,
    }
    assert funnel["grounding"] == {"entitiesWithEvidence": 1, "entitiesWithoutEvidence": 0}
    assert funnel["dedup"] == {
        "mentionRows": 1,
        "distinctEntities": 1,
        "mergedAcrossClaims": 0,
        "held": None,
    }
    assert funnel["final"]["claims"] == 1
    assert funnel["final"]["entities"] == 1


def test_funnel_holds_counts_and_enums_never_source_text() -> None:
    result = compile_semantics(
        (
            _source(
                "doc", "Acme Holdings Group is the supplier.\nPrepared by Zeta Partners Limited"
            ),
        ),
        funnel=True,
    )
    serialized = json.dumps(result.funnel, ensure_ascii=False)
    assert "Acme" not in serialized
    assert "Zeta" not in serialized
    assert "supplier" not in serialized


def test_funnel_does_not_change_claims_entities_or_relations() -> None:
    sources = tuple(_source(name, text) for name, text in _DOCS)
    off = compile_semantics(sources)
    on = compile_semantics(sources, funnel=True)
    assert off.funnel is None
    assert (off.claims, off.entities, off.relations, off.contradictions) == (
        on.claims,
        on.entities,
        on.relations,
        on.contradictions,
    )
    assert off.profile_record() == on.profile_record()


def _assert_identity(funnel: dict[str, Any]) -> None:
    lost = funnel["mentionsInClaimExcludedSentences"]
    skipped = sum(lost["skippedByReason"].values())
    assert funnel["claimFilter"]["excluded"] == lost["scannedSentences"] + skipped
    assert lost["complete"] is (skipped == 0)


def test_a_long_unbroken_excluded_line_is_skipped_counted_and_fast_with_the_flag_on() -> None:
    # `_KOREAN_ORGANIZATION` is O(n^2) on an unbroken alphanumeric/Hangul run: measured 14 s for
    # 40k chars when the funnel scanned it. The funnel must skip it, and say so.
    for line in ("7" * 200_000, "가" * 200_000, "a" * 200_000):
        started = time.perf_counter()
        on = compile_semantics((_source("hostile", line),), funnel=True)
        elapsed = time.perf_counter() - started
        assert elapsed < 5.0, elapsed
        funnel = on.funnel
        assert funnel is not None
        lost = funnel["mentionsInClaimExcludedSentences"]
        assert lost["skippedByReason"] == {"over_length": 1}
        assert lost["scannedSentences"] == 0
        assert lost["complete"] is False
        # Nothing could be scanned: not measured, never a zero.
        assert lost["mentions"] is None
        assert lost["byReason"] is None
        assert lost["distinctEntities"] is None
        assert lost["distinctEntitiesOnlyInExcluded"] is None
        _assert_identity(funnel)


def test_many_excluded_lines_at_the_cap_stay_bounded() -> None:
    line = "7" * FUNNEL_MENTION_SCAN_MAX_CHARS
    text = "\n".join([line] * 200)
    started = time.perf_counter()
    on = compile_semantics((_source("many", text),), funnel=True)
    assert time.perf_counter() - started < 10.0
    assert on.funnel is not None
    lost = on.funnel["mentionsInClaimExcludedSentences"]
    assert lost["skippedByReason"] == {}
    assert lost["complete"] is True
    assert lost["scannedSentences"] == 200
    _assert_identity(on.funnel)


def test_long_line_with_the_flag_off_is_unchanged_by_the_cap() -> None:
    text = "7" * 200_000 + "\nAcme Holdings Group is the supplier."
    off = compile_semantics((_source("hostile", text),))
    on = compile_semantics((_source("hostile", text),), funnel=True)
    assert off.funnel is None
    assert (off.claims, off.entities, off.relations) == (on.claims, on.entities, on.relations)


def test_only_the_exact_value_on_enables_the_funnel_and_a_typo_never_raises() -> None:
    assert semantic_funnel_enabled("on") is True
    for raw in (None, "", "off", "ON", "true", "1", " on", "shadow", "yes"):
        assert semantic_funnel_enabled(raw) is False


_LINES = "Prepared by Zeta Partners Limited\n" + "\n".join(["7" * 1000] * 4)


def test_scan_budget_some_skipped_marks_the_counts_as_lower_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Budget for the first (34 chars) and two 1,000-char lines; the last two run out.
    monkeypatch.setattr(semantics, "FUNNEL_MENTION_SCAN_BUDGET_CHARS", 2_100)
    funnel = compile_semantics((_source("b", _LINES),), funnel=True).funnel
    assert funnel is not None
    lost = funnel["mentionsInClaimExcludedSentences"]
    assert lost["scannedSentences"] == 3
    assert lost["skippedByReason"] == {"budget_exhausted": 2}
    assert lost["complete"] is False
    assert lost["mentions"] == 1  # a lower bound: the one scanned mention
    assert lost["distinctEntitiesOnlyInExcluded"] == 1
    assert lost["mentionScanBudgetChars"] == 2_100
    _assert_identity(funnel)


def test_scan_budget_all_skipped_reports_null_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(semantics, "FUNNEL_MENTION_SCAN_BUDGET_CHARS", 10)
    funnel = compile_semantics((_source("b", _LINES),), funnel=True).funnel
    assert funnel is not None
    lost = funnel["mentionsInClaimExcludedSentences"]
    assert lost["scannedSentences"] == 0
    assert lost["skippedByReason"] == {"budget_exhausted": 5}
    assert lost["complete"] is False
    assert lost["mentions"] is None
    assert lost["byReason"] is None
    assert funnel["claimFilter"]["excluded"] == 5
    _assert_identity(funnel)


def test_scan_none_skipped_and_nothing_excluded_is_complete_and_zero() -> None:
    funnel = compile_semantics(
        (_source("c", "Acme Holdings Group is the supplier."),), funnel=True
    ).funnel
    assert funnel is not None
    lost = funnel["mentionsInClaimExcludedSentences"]
    assert funnel["claimFilter"]["excluded"] == 0
    assert lost["complete"] is True
    assert lost["mentions"] == 0
    assert lost["byReason"] == {}
    _assert_identity(funnel)


def test_both_skip_reasons_are_counted_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(semantics, "FUNNEL_MENTION_SCAN_BUDGET_CHARS", 1_100)
    text = "7" * 5_000 + "\n" + _LINES
    funnel = compile_semantics((_source("d", text),), funnel=True).funnel
    assert funnel is not None
    lost = funnel["mentionsInClaimExcludedSentences"]
    assert lost["skippedByReason"] == {"budget_exhausted": 3, "over_length": 1}
    assert lost["scannedSentences"] == 2
    _assert_identity(funnel)
