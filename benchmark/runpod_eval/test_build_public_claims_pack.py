"""The generator that decides what may go on a public page had no tests.

Nine of its fifteen claims shipped a path to an evidence file with no hash
beside it, and four ParseBench numbers were transcribed by hand rather than read
from the summary they cited. Both are the kind of defect that stays invisible
until someone regenerates an evaluation and the website quietly keeps the old
figure next to a citation that still looks legitimate.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from build_public_claims_pack import (
    _BARE_RATE_PENDING,
    APPROVED,
    CONDITIONAL,
    WITHHELD,
    _canonical_hash,
    _check_evidence_is_bound,
    _check_must_say_numbers_are_cited,
    _check_pending_ids_exist,
    _check_rates_carry_denominators,
    _count_rate,
    _declared_denominator,
    _evidence,
    _group_metric,
    _olmocr_score_definition,
    _publish,
    render_markdown,
)

REPOSITORY = Path(__file__).resolve().parents[2]
SHIPPED_PACKS = (
    "docs/evidence/folynta-public-claims-pack.json",
    "apps/web/src/data/claims/public-claims-pack.json",
)

OLMOCR_SUMMARY = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evidence"
    / "artifacts"
    / "folynta-mineru344-public-core-official-evaluations-r1-2026-08-04"
    "__olmocr-bench__evaluation-summary.json"
)


def _shipped_pack() -> tuple[Path, dict[str, Any]]:
    repository = Path(__file__).resolve().parents[2]
    pack_path = repository / "docs" / "evidence" / "folynta-public-claims-pack.json"
    if not pack_path.is_file():
        pytest.skip("claims pack has not been generated in this checkout")
    pack: dict[str, Any] = json.loads(pack_path.read_text(encoding="utf-8"))
    return repository, pack


def _summary() -> dict[str, object]:
    return {
        "groups": [
            {
                "group": "text_content",
                "aggregate_metrics": {"avg_content_faithfulness": 0.83761234},
            },
            {"group": "table", "aggregate_metrics": {"avg_grits_con": 0.90174}},
        ]
    }


def test_a_metric_is_read_from_the_summary_not_transcribed() -> None:
    assert _group_metric(_summary(), "text_content", "avg_content_faithfulness") == 0.8376
    assert _group_metric(_summary(), "table", "avg_grits_con") == 0.9017


def test_a_renamed_group_fails_loudly_instead_of_reporting_a_stale_number() -> None:
    with pytest.raises(KeyError):
        _group_metric(_summary(), "tables", "avg_grits_con")


def test_a_missing_metric_is_not_silently_defaulted() -> None:
    with pytest.raises(KeyError):
        _group_metric(_summary(), "table", "avg_teds")


def test_evidence_binds_the_path_and_the_hash_together(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "summary.json"
    target.parent.mkdir()
    target.write_text('{"score": 1}', encoding="utf-8")

    bound = _evidence(tmp_path, target)

    assert bound["evidence"] == "reports/summary.json"
    assert bound["evidence_sha256"].startswith("sha256:")


def test_several_files_produce_parallel_lists(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text("1", encoding="utf-8")
    second.write_text("2", encoding="utf-8")

    bound = _evidence(tmp_path, first, second)

    assert bound["evidence"] == ["a.json", "b.json"]
    assert len(bound["evidence_sha256"]) == 2
    assert bound["evidence_sha256"][0] != bound["evidence_sha256"][1]


def test_a_citation_to_a_file_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    # The product-pipeline claim shipped "packages/.../blueprints.py; packages/..."
    # as one string. It resolved to nothing, and nothing checked.
    with pytest.raises(FileNotFoundError):
        _evidence(tmp_path, tmp_path / "never-written.json")


def test_a_path_without_a_hash_is_rejected() -> None:
    with pytest.raises(ValueError, match="inconsistently"):
        _check_evidence_is_bound(
            [{"id": "x", "status": APPROVED, "evidence": "some/file.json"}]
        )


def test_a_hash_without_a_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="inconsistently"):
        _check_evidence_is_bound(
            [{"id": "x", "status": APPROVED, "evidence_sha256": "sha256:00"}]
        )


def test_a_publishable_claim_must_cite_something() -> None:
    with pytest.raises(ValueError, match="cites no evidence"):
        _check_evidence_is_bound([{"id": "x", "status": CONDITIONAL}])


def test_a_withheld_claim_may_cite_nothing() -> None:
    # Withheld claims exist precisely because the measurement has not been made.
    _check_evidence_is_bound([{"id": "x", "status": WITHHELD}])


def test_bound_claims_pass_the_check() -> None:
    _check_evidence_is_bound(
        [
            {
                "id": "x",
                "status": APPROVED,
                "evidence": "a.json",
                "evidence_sha256": "sha256:00",
            }
        ]
    )


def test_the_markdown_carries_the_constraint_in_both_languages() -> None:
    pack = {
        "how_to_use": ["a"],
        "global_rules": ["b"],
        "claims": [
            {
                "id": "completion-rate",
                "status": APPROVED,
                "headline_ko": "완주율",
                "headline_en": "Completion rate",
                "numbers": {"rate": 0.9998},
                "must_say": "정확도가 아닙니다.",
                "must_say_en": "This is not accuracy.",
                "evidence": "ledger.json",
            }
        ],
    }

    rendered = render_markdown(pack)

    assert "정확도가 아닙니다." in rendered
    assert "This is not accuracy." in rendered
    assert "ledger.json" in rendered


def test_a_must_say_rate_without_a_denominator_is_refused() -> None:
    # The sentence benchmark-accuracy shipped: a rate whose whole was wrong.
    with pytest.raises(ValueError, match="without a denominator"):
        _check_rates_carry_denominators(
            [
                {
                    "id": "x",
                    "status": APPROVED,
                    "must_say_en": "84.8% of the 8,413 checks pass.",
                }
            ]
        )


def test_a_korean_must_say_rate_is_checked_too() -> None:
    with pytest.raises(ValueError, match="without a denominator"):
        _check_rates_carry_denominators(
            [{"id": "x", "status": APPROVED, "must_say": "문서의 72.3%에 오류가 있습니다."}]
        )


def test_a_rate_written_with_its_denominator_passes() -> None:
    assert _count_rate(7137, 8413) == "7,137/8,413 (84.8%)"
    _check_rates_carry_denominators(
        [
            {
                "id": "x",
                "status": APPROVED,
                "must_say": f"검사 기준으로는 {_count_rate(7137, 8413)}가 통과했습니다.",
                "must_say_en": f"{_count_rate(7137, 8413)} of the checks pass.",
            }
        ]
    )


@pytest.mark.parametrize(("part", "whole"), [(1, 0), (9, 8), (-1, 8)])
def test_an_impossible_rate_is_refused(part: int, whole: int) -> None:
    with pytest.raises(ValueError, match="is not a rate"):
        _count_rate(part, whole)


def test_a_declared_denominator_is_read_from_its_artifact_and_bound_by_hash(
    tmp_path: Path,
) -> None:
    # verify-claims allows a withheld claim's number only as a denominator the
    # pack declares, and only from the artifact with this digest. It names the
    # fields it read so verify-claims can read them again from those bytes.
    study = tmp_path / "study.json"
    study.write_bytes(b'{"failed": 3, "cases": 8}\r\n')

    declared = _declared_denominator(tmp_path, study, "failed", "cases")

    assert declared == {
        "numerator": 3,
        "numerator_field": "failed",
        "denominator": 8,
        "denominator_field": "cases",
        "evidence": "study.json",
        "evidence_sha256": "sha256:" + hashlib.sha256(study.read_bytes()).hexdigest(),
        "evidence_source": "study.json",
    }


def test_a_declared_denominator_that_is_not_a_rate_is_refused(tmp_path: Path) -> None:
    study = tmp_path / "study.json"
    study.write_text('{"failed": 9, "cases": 8}', encoding="utf-8")
    with pytest.raises(ValueError, match="is not a rate"):
        _declared_denominator(tmp_path, study, "failed", "cases")


def test_a_pending_claim_that_no_longer_needs_the_exemption_fails() -> None:
    with pytest.raises(ValueError, match="remove it from _BARE_RATE_PENDING"):
        _check_rates_carry_denominators(
            [{"id": "accuracy-by-document-type", "status": APPROVED, "must_say_en": "x"}]
        )


def test_a_pending_id_that_names_no_claim_fails() -> None:
    # An exemption left behind for a renamed or deleted claim would never be noticed.
    with pytest.raises(ValueError, match="names no claim"):
        _check_pending_ids_exist([{"id": "x", "status": APPROVED}])


def test_pending_ids_that_name_claims_pass() -> None:
    _check_pending_ids_exist([{"id": claim_id} for claim_id in _BARE_RATE_PENDING])


@pytest.mark.parametrize(
    "spelled",
    ["84.8 %", "84.8\u00a0%", "84.8\u2009%", "84.8\uff05", "84.8 퍼센트", "84.8 percent"],
)
def test_a_spaced_or_spelled_out_percent_is_still_a_bare_rate(spelled: str) -> None:
    with pytest.raises(ValueError, match="without a denominator"):
        _check_rates_carry_denominators(
            [{"id": "x", "status": APPROVED, "must_say_en": f"{spelled} of the checks pass."}]
        )


@pytest.mark.parametrize(
    "stated",
    [
        "7,137/8,413 (90.0%)",
        "7,137/8,413 (84.9%)",
        "7,137/8,413 (8.5%)",
        "9/8 (112.5%)",
        "1/0 (0%)",
    ],
)
def test_a_counted_rate_whose_percent_does_not_follow_is_refused(stated: str) -> None:
    with pytest.raises(ValueError, match="does not equal"):
        _check_rates_carry_denominators(
            [
                {
                    "id": "x",
                    "status": APPROVED,
                    "must_say": f"검사 기준으로는 {stated}가 통과했습니다.",
                }
            ]
        )


@pytest.mark.parametrize(
    "stated", ["7,137/8,413 (84.8%)", "7,137/8,413 (85%)", "3,698/5,116 (72.28%)"]
)
def test_a_counted_rate_within_rounding_passes(stated: str) -> None:
    _check_rates_carry_denominators([{"id": "x", "status": APPROVED, "must_say_en": stated}])


def test_a_must_say_number_no_cited_artifact_states_is_refused(tmp_path: Path) -> None:
    # benchmark-accuracy typed 83.1 into a sentence whose citations never held it.
    (tmp_path / "a.json").write_text(json.dumps({"overall_score": 0.806}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"\['83\.1'\]"):
        _check_must_say_numbers_are_cited(
            tmp_path,
            [
                {
                    "id": "x",
                    "status": APPROVED,
                    "evidence": "a.json",
                    "must_say_en": "80.6, against a top published score of 83.1.",
                }
            ],
        )


def test_must_say_numbers_read_from_the_cited_artifacts_pass(tmp_path: Path) -> None:
    summary = {
        "overall_score": 0.806,
        "per_type": {"a": {"passed": 3, "total": 4}, "b": {"passed": 4, "total": 6}},
    }
    (tmp_path / "a.json").write_text(json.dumps(summary), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"rows": [{"overall": 83.1}]}), encoding="utf-8")
    _check_must_say_numbers_are_cited(
        tmp_path,
        [
            {
                "id": "x",
                "status": APPROVED,
                "evidence": ["a.json", "b.json"],
                # 2 is the number of types, 7/10 the column totals; neither is
                # a leaf, and both are what the sentence is about.
                "must_say": "80.6은 유형 2개의 평균이고, 검사 기준으로는 7/10 (70.0%)입니다. "
                "최상위 인용값은 83.1입니다.",
            }
        ],
    )


def test_no_shipped_must_say_states_a_number_its_citations_do_not() -> None:
    repository, pack = _shipped_pack()
    _check_must_say_numbers_are_cited(repository, pack["claims"])
    _check_pending_ids_exist(pack["claims"])


_CHECK_PASS_RATE = re.compile(r"check pass rate|pass rate over|검사\s*통과율|검사의 통과율", re.I)


def test_no_shipped_must_say_calls_the_olmocr_score_a_check_pass_rate() -> None:
    # 80.6 is the mean of eight per-type pass rates; by check it is 7,137/8,413 (84.8%).
    _, pack = _shipped_pack()
    accuracy = next(c for c in pack["claims"] if c["id"] == "benchmark-accuracy")
    score = f"{accuracy['numbers']['overall_percent']:.1f}"
    offending = [
        (claim["id"], sentence)
        for claim in pack["claims"]
        for field in ("must_say", "must_say_en")
        for sentence in re.split(r"(?<=\.)\s+", claim.get(field, ""))
        if score in sentence and _CHECK_PASS_RATE.search(sentence)
    ]
    assert offending == []


def _synthetic_olmocr_summary(overall: float) -> dict[str, object]:
    return {
        "label": "SYNTHETIC",
        "overall_score": overall,
        "test_count": 10,
        "rule_failure_count": 3,
        "per_jsonl": {
            "a.jsonl": {"pass_rate": 0.5, "passed": 1, "total": 2},
            "b.jsonl": {"pass_rate": 0.75, "passed": 6, "total": 8},
        },
    }


def test_the_overall_score_is_confirmed_to_be_the_type_average() -> None:
    assert _olmocr_score_definition(_synthetic_olmocr_summary(0.625)) == {
        "types": 2,
        "checks_passed": 7,
        "checks_total": 10,
    }


def test_a_check_level_overall_score_is_refused() -> None:
    # 7/10 is the micro rate; a sentence calling the score a type average would be false.
    with pytest.raises(ValueError, match="mean of the per-type pass rates"):
        _olmocr_score_definition(_synthetic_olmocr_summary(0.7))


def test_per_type_counts_that_do_not_add_up_are_refused() -> None:
    summary = _synthetic_olmocr_summary(0.625)
    summary["rule_failure_count"] = 4
    with pytest.raises(ValueError, match="do not add up"):
        _olmocr_score_definition(summary)


def test_the_cited_olmocr_artifact_is_a_type_average_of_eight() -> None:
    if not OLMOCR_SUMMARY.is_file():
        pytest.skip("olmOCR-Bench summary artifact is not in this checkout")
    summary = json.loads(OLMOCR_SUMMARY.read_text(encoding="utf-8-sig"))
    assert _olmocr_score_definition(summary) == {
        "types": 8,
        "checks_passed": 7137,
        "checks_total": 8413,
    }
    assert round(summary["overall_score"] * 100, 1) == 80.6


def test_the_shipped_pack_has_a_constraint_on_every_publishable_number() -> None:
    """A number on a public page without a stated constraint is the failure mode
    the pack exists to prevent, so it is checked against the shipped artifact."""
    repository = Path(__file__).resolve().parents[2]
    pack_path = repository / "docs" / "evidence" / "folynta-public-claims-pack.json"
    if not pack_path.is_file():
        pytest.skip("claims pack has not been generated in this checkout")

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    unconstrained = [
        claim["id"]
        for claim in pack["claims"]
        if claim["status"] in (APPROVED, CONDITIONAL)
        and claim.get("numbers")
        and not (
            claim.get("must_say") or claim.get("conditions")
        )
    ]
    assert unconstrained == []

    unbound = [
        claim["id"]
        for claim in pack["claims"]
        if bool(claim.get("evidence")) != bool(claim.get("evidence_sha256"))
    ]
    assert unbound == []

    _check_rates_carry_denominators(pack["claims"])
    accuracy = next(c for c in pack["claims"] if c["id"] == "benchmark-accuracy")
    checks = _count_rate(accuracy["numbers"]["checks_passed"], accuracy["numbers"]["checks_total"])
    assert checks in accuracy["must_say"]
    assert checks in accuracy["must_say_en"]
    assert "unweighted mean" in accuracy["must_say_en"]


def test_every_shipped_digest_is_the_sha256_of_the_file_bytes() -> None:
    """The exact check a reader of the pack runs: sha256sum the cited file.

    Eight campaign receipt files were hashed as the CRLF bytes they were written
    with, then stored by git as LF under `* text=auto eol=lf`, so `sha256sum`
    in a clone disagreed with the published digest for twelve of nineteen
    citations. The bytes are read with no line-ending normalisation on purpose:
    "equal up to line endings" is not a hash match.

    A declared denominator cites a file too, and it is the one citation that
    lets a withheld number onto the page, so it is hashed the same way.
    """
    mismatched = []
    for pack_path in SHIPPED_PACKS:
        pack = json.loads((REPOSITORY / pack_path).read_bytes())
        mismatched += [(pack_path, *found) for found in _digest_mismatches(REPOSITORY, pack)]
    assert mismatched == []


def _digest_mismatches(repository: Path, pack: dict[str, Any]) -> list[tuple[str, ...]]:
    mismatched: list[tuple[str, ...]] = []
    for claim in pack["claims"]:
        cited = [(claim.get("evidence"), claim.get("evidence_sha256"))] + [
            (declared["evidence"], declared["evidence_sha256"])
            for declared in claim.get("declared_denominators", [])
        ]
        for paths, digests in cited:
            if not paths:
                continue
            paths = paths if isinstance(paths, list) else [paths]
            digests = digests if isinstance(digests, list) else [digests]
            for path, digest in zip(paths, digests, strict=True):
                actual = "sha256:" + hashlib.sha256((repository / path).read_bytes()).hexdigest()
                if actual != digest:
                    mismatched.append((claim["id"], path, digest, actual))
    return mismatched


def test_a_declared_denominator_whose_file_does_not_hash_to_its_digest_is_found(
    tmp_path: Path,
) -> None:
    (tmp_path / "study.json").write_bytes(b'{"failed": 3, "cases": 8}\n')
    stale = "sha256:" + hashlib.sha256(b'{"failed": 3, "cases": 9}\n').hexdigest()
    pack = {
        "claims": [
            {
                "id": "x",
                "declared_denominators": [
                    {"evidence": "study.json", "evidence_sha256": stale},
                ],
            }
        ]
    }

    assert [found[:3] for found in _digest_mismatches(tmp_path, pack)] == [
        ("x", "study.json", stale)
    ]


def _sealed(pack: dict[str, Any]) -> bool:
    """Whether receipt_sha256 is the hash main() would write over the rest."""
    body = {key: value for key, value in pack.items() if key != "receipt_sha256"}
    return bool(pack.get("receipt_sha256")) and pack["receipt_sha256"] == _canonical_hash(body)


def test_every_shipped_pack_carries_the_receipt_hash_of_its_own_content() -> None:
    # A hand-edit to either copy -- a must_say, a declared numerator, a status --
    # leaves the receipt the generator wrote, so it no longer matches. This
    # catches the edit without the generator's gitignored inputs.
    unsealed = [
        pack_path
        for pack_path in SHIPPED_PACKS
        if not _sealed(json.loads((REPOSITORY / pack_path).read_bytes()))
    ]
    assert unsealed == []


def test_a_pack_edited_after_its_receipt_was_written_is_unsealed() -> None:
    _, pack = _shipped_pack()
    assert _sealed(pack)
    claim = next(c for c in pack["claims"] if c.get("declared_denominators"))
    claim["declared_denominators"][0]["numerator"] = 1

    assert not _sealed(pack)
    assert not _sealed({key: value for key, value in pack.items() if key != "receipt_sha256"})


def _generated_receipt(repository: Path, payload: bytes) -> Path:
    source = repository / "benchmark" / "reports" / "generated" / "receipt.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    return source


def test_a_new_artifact_is_published_with_the_source_bytes_unchanged(tmp_path: Path) -> None:
    source = _generated_receipt(tmp_path, b'{\r\n  "rate": 0.9998\r\n}\r\n')

    published = _publish(tmp_path, source)

    assert published == tmp_path / "docs" / "evidence" / "artifacts" / "receipt.json"
    assert published.read_bytes() == source.read_bytes()


def test_a_published_artifact_that_differs_from_its_source_is_not_rewritten(
    tmp_path: Path,
) -> None:
    # This is how the digests drifted: the generator rewrote an LF checkout back
    # to the CRLF receipt, hashed that, and git stored LF again. Published
    # evidence is immutable, so a difference is refused, not overwritten.
    source = _generated_receipt(tmp_path, b'{\r\n  "rate": 0.9998\r\n}\r\n')
    published = tmp_path / "docs" / "evidence" / "artifacts" / "receipt.json"
    published.parent.mkdir(parents=True)
    published.write_bytes(b'{\n  "rate": 0.9998\n}\n')

    with pytest.raises(ValueError, match="immutable"):
        _publish(tmp_path, source)

    assert published.read_bytes() == b'{\n  "rate": 0.9998\n}\n'


def test_a_published_artifact_equal_to_its_source_is_reused(tmp_path: Path) -> None:
    payload = b'{\r\n  "rate": 0.9998\r\n}\r\n'
    source = _generated_receipt(tmp_path, payload)
    published = tmp_path / "docs" / "evidence" / "artifacts" / "receipt.json"
    published.parent.mkdir(parents=True)
    published.write_bytes(payload)

    assert _publish(tmp_path, source) == published
    assert published.read_bytes() == payload
