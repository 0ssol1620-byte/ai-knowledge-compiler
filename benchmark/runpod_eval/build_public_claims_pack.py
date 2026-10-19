#!/usr/bin/env python3
"""Turn the campaign's evidence into claims a website may or may not publish.

A marketing page is where measured results are most likely to drift: a number
gets rounded, a denominator gets dropped, and a completion rate starts being
described as accuracy. So the pack is generated from the receipts rather than
written by hand, and every claim carries the file and hash it came from.

Each claim also carries a verdict. Some results are ready to publish as they
stand, some are only publishable with a stated condition, and some must not go
on a public page at all -- either because the measurement does not support the
reading a visitor would take, or because the work that would support it has not
finished. The withheld claims are included deliberately: a frontend agent that
cannot see why a number is missing will eventually put it back.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

APPROVED = "approved"
CONDITIONAL = "conditional"
WITHHELD = "withheld"

# olmOCR-Bench names its slices after the jsonl files it ships. Those names are
# fine in a paper and wrong on a pricing page, so each one is given the label a
# customer would recognise before it can reach a template.
DOCUMENT_TYPE_LABELS = {
    "baseline": ("표준 디지털 문서", "Standard digital documents"),
    "headers_footers.jsonl": ("머리말·꼬리말이 있는 문서", "Documents with headers and footers"),
    "table_tests.jsonl": ("표 중심 문서", "Table-heavy documents"),
    "arxiv_math.jsonl": ("학술 논문 (수식 포함)", "Academic papers with equations"),
    "multi_column.jsonl": ("다단 레이아웃", "Multi-column layouts"),
    "long_tiny_text.jsonl": ("작은 글씨의 장문 문서", "Long documents in small type"),
    "old_scans_math.jsonl": ("오래된 스캔본 (수식 포함)", "Old scans containing equations"),
    "old_scans.jsonl": ("저품질 스캔본", "Low-quality scans"),
}


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


ARTIFACT_DIRECTORY = Path("docs") / "evidence" / "artifacts"
GENERATED_PREFIX = ("benchmark", "reports", "generated")


def _publish(repository: Path, source: Path) -> Path:
    """Copy a cited artifact into the repository so a clone can verify it.

    benchmark/reports/generated is gitignored, and eleven of the fourteen files
    the pack cited lived there. Every hash verified on this machine and nowhere
    else: anyone who cloned the repository -- the frontend agent on the other
    machine, a patent examiner, a reviewer -- would find each citation pointing
    at a file that does not exist. The summaries are small; the multi-megabyte
    failure dumps they derive from stay out.

    An artifact that already exists is never rewritten. This function used to
    overwrite any copy whose bytes differed from the receipt, and that is how
    the published digests drifted: the receipts were written on Windows as CRLF,
    the copy and its digest kept CRLF, and git stored LF under
    `* text=auto eol=lf`. Every later run on the generating machine rewrote the
    LF checkout back to CRLF, so the hashes verified there and in no clone.
    `.gitattributes` now stores docs/evidence/artifacts byte-exact; a copy that
    still differs from its receipt is a broken chain of custody, and it fails.
    """
    relative = source.relative_to(repository)
    if relative.parts[: len(GENERATED_PREFIX)] != GENERATED_PREFIX:
        return source
    flattened = "__".join(relative.parts[len(GENERATED_PREFIX) :])
    destination = repository / ARTIFACT_DIRECTORY / flattened
    payload = source.read_bytes()
    if destination.is_file():
        if destination.read_bytes() != payload:
            raise ValueError(
                f"{destination.relative_to(repository).as_posix()} differs from its "
                f"receipt {relative.as_posix()}; published evidence is immutable, so "
                "it is not overwritten"
            )
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination


def _evidence(repository: Path, *paths: Path) -> dict[str, Any]:
    """Bind a claim to the files it came from, path and hash together.

    Writing the two as separate keys let nine of fifteen claims ship a path with
    no hash, which is the same as shipping no evidence at all: the file can be
    regenerated with different numbers and nothing notices. One helper that
    always emits both, and a check below that refuses to build a pack without
    them, is the difference between a chain of custody and a footnote.
    """
    resolved = [repository / path if not path.is_absolute() else path for path in paths]
    missing = [str(path) for path in resolved if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"claim evidence does not exist: {', '.join(missing)}")
    published = [_publish(repository, path) for path in resolved]
    relative = [path.relative_to(repository).as_posix() for path in published]
    sources = [path.relative_to(repository).as_posix() for path in resolved]
    if len(published) == 1:
        return {
            "evidence": relative[0],
            "evidence_sha256": _sha256(published[0]),
            "evidence_source": sources[0],
        }
    return {
        "evidence": relative,
        "evidence_sha256": [_sha256(path) for path in published],
        "evidence_source": sources,
    }


def _group_metric(payload: dict[str, Any], group: str, metric: str) -> float:
    """Read a ParseBench metric from the summary instead of transcribing it.

    The four ParseBench numbers on the site were typed in by hand. They happened
    to be right, but a re-run of the evaluation would have left them silently
    stale next to a hash that still verified.
    """
    for entry in payload["groups"]:
        if entry["group"] == group:
            value: float = entry["aggregate_metrics"][metric]
            return round(value, 4)
    raise KeyError(f"ParseBench group {group!r} not present in the summary")


def _check_evidence_is_bound(claims: list[dict[str, Any]]) -> None:
    """Refuse to emit a claim that points at a file without hashing it."""
    for claim in claims:
        has_path = bool(claim.get("evidence"))
        has_hash = bool(claim.get("evidence_sha256"))
        if has_path != has_hash:
            raise ValueError(
                f"claim {claim['id']!r} carries evidence and hash inconsistently; "
                "use _evidence() so the two cannot separate"
            )
        if claim["status"] in (APPROVED, CONDITIONAL) and not has_path:
            raise ValueError(
                f"claim {claim['id']!r} is publishable but cites no evidence"
            )


def _count_rate(part: int, whole: int) -> str:
    """A rate written with its denominator: the one form a must_say may use."""
    if whole <= 0 or not 0 <= part <= whole:
        raise ValueError(f"{part}/{whole} is not a rate")
    return f"{part:,}/{whole:,} ({part / whole:.1%})"


def _declared_denominator(
    repository: Path, source: Path, part_field: str, whole_field: str
) -> dict[str, Any]:
    """A rate's counts, read from one artifact and bound to it by hash.

    Every rate carries its denominator, and sometimes the denominator is a
    number a withheld claim also states: benchmark-accuracy writes its
    failure-study rate over the corpus that blind-quality-detection counts.
    verify-claims refuses a withheld claim's numbers anywhere on the site, so
    the pack declares where this one may appear -- as this denominator, in the
    counted-rate form, from the artifact with this hash -- instead of the
    script keeping an allowlist. The declaration names the two fields it read,
    and verify-claims reads them again from the hashed bytes, so a numerator
    edited by hand together with its must_say fails there.
    """
    payload = _load(source)
    part, whole = payload[part_field], payload[whole_field]
    _count_rate(part, whole)
    return {
        "numerator": part,
        "numerator_field": part_field,
        "denominator": whole,
        "denominator_field": whole_field,
        **_evidence(repository, source),
    }


# \uff05 is the fullwidth percent sign a Korean IME types.
_RATE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|\uff05|퍼센트|percent\b)", re.IGNORECASE)
_COUNTED_RATE = re.compile(r"(\d[\d,]*)/(\d[\d,]*) \((\d+(?:\.\d+)?)%\)")
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")

# Claims whose must_say still states a bare rate. accuracy-by-document-type
# quotes the spread of its own per-type rows, each of which carries passed and
# total in numbers. The set may only shrink: a claim that no longer needs it
# fails, and so does an id that names no claim.
_BARE_RATE_PENDING = frozenset({"accuracy-by-document-type"})


def _check_rates_carry_denominators(claims: list[dict[str, Any]]) -> None:
    """Refuse a must_say that states a percentage without the count behind it.

    benchmark-accuracy shipped "the pass rate over 8,413 checks" beside 80.6,
    which is a mean of eight per-type rates; the check-level rate is 84.8%. A
    rate that has to be written as part/whole cannot pick up the wrong whole.
    """
    for claim in claims:
        texts = [claim.get(field, "") for field in ("must_say", "must_say_en")]
        for part_text, whole_text, stated in (m for t in texts for m in _COUNTED_RATE.findall(t)):
            part, whole = int(part_text.replace(",", "")), int(whole_text.replace(",", ""))
            # Within the rounding of the digits written: 84.8% and 85% both fit 7,137/8,413.
            tolerance = 0.5 * 10 ** -len(stated.partition(".")[2]) + 1e-9
            if (
                not 0 <= part <= whole
                or whole == 0
                or abs(part / whole * 100 - float(stated)) > tolerance
            ):
                raise ValueError(
                    f"claim {claim['id']!r} writes {part_text}/{whole_text} as {stated}%, which "
                    "does not equal the ratio; write the rate with _count_rate()"
                )
        bare = [rate for t in texts for rate in _RATE.findall(_COUNTED_RATE.sub("", t))]
        if claim["id"] in _BARE_RATE_PENDING:
            if not bare:
                raise ValueError(
                    f"claim {claim['id']!r} now states its denominators; "
                    "remove it from _BARE_RATE_PENDING"
                )
            continue
        if bare:
            raise ValueError(
                f"claim {claim['id']!r} states {bare} in its must_say without a "
                "denominator; write the rate with _count_rate()"
            )


def _check_pending_ids_exist(claims: list[dict[str, Any]]) -> None:
    """Refuse an exemption for a claim the pack no longer has."""
    unknown = sorted(_BARE_RATE_PENDING - {claim["id"] for claim in claims})
    if unknown:
        raise ValueError(f"_BARE_RATE_PENDING names no claim: {unknown}")


def _stated_values(node: Any) -> list[float]:
    """Every number an artifact states, with its container sizes and column totals.

    Sizes and totals are included because a sentence says "8 document types" or
    "7,137 of 8,413 checks" about a table whose leaves are per-row. Numbers
    inside prose strings are not: an artifact's own sentence is not a measurement.
    """

    def number(value: Any) -> bool:
        return isinstance(value, int | float) and not isinstance(value, bool)

    if number(node):
        return [float(node)]
    if not isinstance(node, dict | list):
        return []
    children = list(node.values()) if isinstance(node, dict) else node
    rows = [child for child in children if isinstance(child, dict)]
    columns = {key for row in rows for key, value in row.items() if number(value)}
    values = [float(len(children))]
    values += [float(sum(r[k] for r in rows if number(r.get(k)))) for k in columns]
    for child in children:
        values += _stated_values(child)
    return values


def _check_must_say_numbers_are_cited(repository: Path, claims: list[dict[str, Any]]) -> None:
    """Refuse a must_say number that none of the claim's cited artifacts states.

    benchmark-accuracy said the top published system scores 83.1 while citing
    two files that never mention it. A number is supported when a cited JSON
    artifact holds it, as written or as a percentage, at the precision written;
    the percent of a counted rate is derived and checked against its counts.
    """
    for claim in claims:
        cited = claim.get("evidence") or []
        values: list[float] = []
        for entry in cited if isinstance(cited, list) else [cited]:
            if entry.endswith(".json"):
                values += _stated_values(_load(repository / entry))
        unsupported = []
        for field in ("must_say", "must_say_en"):
            text = _COUNTED_RATE.sub(r"\1 \2", claim.get(field, ""))
            for token in _NUMBER.findall(text):
                number = float(token.replace(",", ""))
                digits = len(token.partition(".")[2])
                # ponytail: integers match loosely (a "2" may be any 0.02 or 2.0
                # an artifact holds); decimals are where hand-typed figures hide.
                if not any(
                    abs(round(value * scale, digits) - number) < 1e-9
                    for value in values
                    for scale in (1, 100)
                ):
                    unsupported.append(token)
        if unsupported:
            raise ValueError(
                f"claim {claim['id']!r} states {unsupported} in its must_say, which no "
                "cited artifact holds; cite the artifact or read the number from it"
            )


def _olmocr_score_definition(summary: dict[str, Any]) -> dict[str, int]:
    """Confirm what olmOCR-Bench's overall_score is before a sentence names it.

    It is the unweighted mean of the per-type pass rates, not passed/total over
    every check. Both readings are recomputed here, so a summary that does not
    fit the sentence stops the build instead of publishing it.
    """
    types = list(summary["per_jsonl"].values())
    mean = sum(t["pass_rate"] for t in types) / len(types)
    if not math.isclose(mean, summary["overall_score"], rel_tol=0, abs_tol=1e-9):
        raise ValueError("olmOCR-Bench overall_score is not the mean of the per-type pass rates")
    passed = sum(t["passed"] for t in types)
    total = sum(t["total"] for t in types)
    if total != summary["test_count"] or passed != total - summary["rule_failure_count"]:
        raise ValueError("olmOCR-Bench per-type check counts do not add up to test_count")
    return {"types": len(types), "checks_passed": passed, "checks_total": total}


def _check_evidence_is_readable(repository: Path, claims: list[dict[str, Any]]) -> None:
    """Refuse to emit a citation a clone of this repository cannot open.

    A path that only resolves on the machine that generated it is not evidence.
    """
    import subprocess

    for claim in claims:
        cited = claim.get("evidence")
        if not cited:
            continue
        for entry in cited if isinstance(cited, list) else [cited]:
            path = repository / entry
            if not path.is_file():
                raise FileNotFoundError(f"claim {claim['id']!r} cites missing {entry}")
            # Resolved through PATH on purpose: this runs on a developer
            # machine and in CI, where git lives at different absolute paths.
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", entry],  # noqa: S607
                cwd=repository,
                capture_output=True,
                check=False,
            )
            if ignored.returncode == 0:
                raise ValueError(
                    f"claim {claim['id']!r} cites {entry}, which git ignores; "
                    "publish it into docs/evidence/artifacts instead"
                )


def _load(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _blueprint_summary(repository: Path) -> list[dict[str, Any]]:
    """The knowledge architectures the product ships, read from the code."""
    import sys

    source = repository / "packages" / "domain-packs" / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from akc_domain_packs.blueprints import builtin_blueprints

    blueprints: list[dict[str, Any]] = builtin_blueprints().model_dump()["blueprints"]
    return blueprints


def build_claims(repository: Path) -> dict[str, Any]:
    generated = repository / "benchmark" / "reports" / "generated"
    official = generated / "folynta-mineru344-public-core-official-evaluations-r1-2026-08-04"

    ledger_path = generated / "folynta-campaign-completion-ledger-2026-08-08.json"
    compile_path = generated / "folynta-knowledge-compilation-properties-2026-08-08.json"
    blind_path = generated / "folynta-blind-quality-detection-2026-08-08.json"

    ledger = _load(ledger_path)
    compilation = _load(compile_path)
    blind = _load(blind_path)
    recovery = ledger["recovery_outcome"]

    olm_with_path = official / "olmocr-bench" / "evaluation-summary.json"
    # The roll-up carries both sides of the comparison and the caveats that go
    # with it, so it is what the claim cites; the raw summary is what the
    # numbers are read from, and the two agree.
    olm_counterfactual_path = (
        generated / "folynta-recovery-accuracy-counterfactual-olmocr-2026-08-08.json"
    )
    parse_with_path = official / "parsebench" / "evaluation-summary.json"
    parse_without_path = (
        generated
        / "folynta-counterfactual-no-recovery-parsebench-2026-08-08"
        / "evaluation-summary.json"
    )
    omni_with_path = official / "omnidocbench" / "repeat-1" / "metric-result.json"
    omni_without_path = (
        generated
        / "folynta-counterfactual-no-recovery-omnidocbench-2026-08-08"
        / "repeat-1"
        / "metric-result.json"
    )
    leaderboard_path = generated / "folynta-published-leaderboard-context-2026-08-08.json"
    cost_path = generated / "folynta-measured-gpu-cost-2026-08-08.json"

    olm_with = _load(olm_with_path)
    olm_without = _load(
        generated
        / "folynta-counterfactual-no-recovery-olmocr-2026-08-08"
        / "evaluation-summary.json"
    )
    parse_with = _load(parse_with_path)
    parse_without = _load(parse_without_path)
    omni_with = _load(omni_with_path)
    omni_without = _load(omni_without_path)

    olm_score = _olmocr_score_definition(olm_with)
    olm_overall = f"{olm_with['overall_score'] * 100:.1f}"
    olm_checks = _count_rate(olm_score["checks_passed"], olm_score["checks_total"])
    failure_study = _declared_denominator(
        repository, blind_path, "cases_with_official_failures", "corpus_cases"
    )
    failing_documents = _count_rate(failure_study["numerator"], failure_study["denominator"])
    # A quoted leaderboard row, not a result we reproduced; the sentence says so.
    published_top = max(
        row["overall"] for row in _load(leaderboard_path)["published_leaderboard"]["rows"]
    )

    def edit(payload: dict[str, Any], section: str) -> float:
        value: float = payload[section]["all"]["Edit_dist"]["ALL_page_avg"]
        return value

    group_metric = _group_metric

    claims: list[dict[str, Any]] = [
        {
            "id": "corpus-scale",
            "status": APPROVED,
            "headline_ko": "공개 벤치마크 3종, 5,132개 문서를 공식 평가기로 측정",
            "headline_en": (
                "5,132 documents across three public benchmarks, scored by the "
                "official evaluators"
            ),
            "numbers": {
                "documents": ledger["planned_cases"],
                "benchmarks": sorted(ledger["cases_by_suite"]),
                "per_benchmark": {
                    suite: counts["planned"]
                    for suite, counts in ledger["cases_by_suite"].items()
                },
            },
            "must_say": (
                "5,132은 평가한 문서 수이며 처리 용량이나 고객 처리량이 아닙니다. "
                "세 벤치마크는 공개 데이터셋이고 각 벤치마크의 문서 수를 함께 표기하십시오."
            ),
            "must_say_en": (
                "5,132 is the number of documents evaluated, not a capacity or a "
                "customer throughput figure. Name the three public benchmarks and "
                "their individual counts alongside the total."
            ),
            "forbidden": [
                "5,132개 문서를 처리할 수 있습니다 (규모를 처리 용량으로 환언하는 표현)",
                "고객 문서 5,132건 (공개 벤치마크를 고객 실적으로 제시하는 표현)",
            ],
            **_evidence(repository, ledger_path),
        },
        {
            "id": "completion-rate",
            "status": APPROVED,
            "headline_ko": "처리 완주율 99.98%",
            "headline_en": "99.98% of documents produced output",
            "numbers": {
                "resolved": ledger["resolved_cases"],
                "planned": ledger["planned_cases"],
                "unresolved": ledger["unresolved_cases"],
                "completion_fraction": ledger["completion_fraction"],
            },
            "must_say": (
                "완주율은 출력이 생성된 비율이며 정확도가 아닙니다. 두 수치를 같은 문장에 "
                "쓸 때는 반드시 구분해 표기하십시오."
            ),
            "must_say_en": (
                "This is the share of documents that produced output. It is not accuracy. "
                "Where both figures appear, label which is which."
            ),
            "forbidden": [
                "정확도 99.98%",
                "정확도 100%에 가까움",
                "완주율을 정확도로 환언하는 모든 표현",
            ],
            **_evidence(repository, ledger_path),
        },
        {
            "id": "recovery-rate",
            "status": APPROVED,
            "headline_ko": "실제로 실패한 문서 중 99.94%를 복구",
            "headline_en": "99.94% of documents that actually failed were recovered",
            "numbers": {
                "needed_recovery": recovery["cases_that_needed_recovery"],
                "recovered": recovery["cases_recovered"],
                "rate": recovery["recovery_rate_on_cases_that_needed_it"],
                "attempted_but_never_recovered": recovery[
                    "cases_attempted_but_never_recovered"
                ],
                "unresolved_and_never_attempted": recovery[
                    "cases_unresolved_and_never_attempted"
                ],
                "required_more_than_one_round": recovery[
                    "cases_requiring_more_than_one_round"
                ],
            },
            "must_say": (
                "분모는 전체 코퍼스가 아니라 실제로 실패한 문서 수입니다. 분모를 밝히지 "
                "않으면 완주율과 혼동됩니다."
            ),
            "must_say_en": (
                "The denominator is the documents that actually failed, not the whole "
                "corpus. Without the denominator this reads as the completion rate."
            ),
            **_evidence(repository, ledger_path),
        },
        {
            "id": "recovery-contribution-olmocr",
            "status": APPROVED,
            "headline_ko": (
                "복구 레인을 끄면 동일 파이프라인의 공식 점수가 80.6에서 53.7로 "
                "떨어집니다"
            ),
            "headline_en": (
                "Disabling only the recovery lane drops the same pipeline from "
                "80.6 to 53.7"
            ),
            "numbers": {
                "benchmark": "olmOCR-Bench",
                "with_recovery": round(olm_with["overall_score"] * 100, 2),
                "without_recovery": round(olm_without["overall_score"] * 100, 2),
                "with_recovery_ci95": [
                    round(x * 100, 2) for x in olm_with["confidence_interval_95"]
                ],
                "without_recovery_ci95": [
                    round(x * 100, 2) for x in olm_without["confidence_interval_95"]
                ],
                "rule_failures_with": olm_with["rule_failure_count"],
                "rule_failures_without": olm_without["rule_failure_count"],
            },
            "must_say": (
                "모델, 평가기 리비전, 코퍼스, 설정을 고정하고 복구 산출물만 제거한 "
                "단일 변수 비교입니다."
            ),
            "must_say_en": (
                "A single-variable comparison: model, evaluator revision, corpus and "
                "settings are identical, and only the recovery output was removed."
            ),
            **_evidence(repository, olm_counterfactual_path),
        },
        {
            "id": "recovery-contribution-parsebench",
            "status": APPROVED,
            "headline_ko": "복구가 없으면 ParseBench 규칙 위반이 2.1배로 늘어납니다",
            "headline_en": "Without recovery, ParseBench rule failures more than double",
            "numbers": {
                "rule_failures_with": parse_with["rule_failure_count"],
                "rule_failures_without": parse_without["rule_failure_count"],
                "content_faithfulness_with": group_metric(
                    parse_with, "text_content", "avg_content_faithfulness"
                ),
                "content_faithfulness_without": group_metric(
                    parse_without, "text_content", "avg_content_faithfulness"
                ),
                "table_grits_with": group_metric(parse_with, "table", "avg_grits_con"),
                "table_grits_without": group_metric(
                    parse_without, "table", "avg_grits_con"
                ),
                # Carried deliberately: this is the one group where removing
                # recovery does not look worse, and the reason has to travel
                # with the claim.
                "layout_micro_rule_pass_rate_with": group_metric(
                    parse_with, "layout", "micro_layout_rule_pass_rate"
                ),
                "layout_micro_rule_pass_rate_without": group_metric(
                    parse_without, "layout", "micro_layout_rule_pass_rate"
                ),
                "layout_rules_evaluated_with": group_metric(
                    parse_with, "layout", "total_layout_rule_pass_rate_evaluated"
                ),
                "layout_rules_evaluated_without": group_metric(
                    parse_without, "layout", "total_layout_rule_pass_rate_evaluated"
                ),
            },
            "must_say": (
                "절대 위반 건수로 표기하십시오. 레이아웃 그룹의 통과율은 복구를 끄면 "
                "오히려 올라가는데(0.757 → 0.770), 내용이 없는 문서는 채점할 요소 자체가 "
                "없어 분모가 40,287에서 23,025로 줄기 때문입니다. 비율만 인용하면 "
                "복구를 끄는 편이 나아 보입니다."
            ),
            "must_say_en": (
                "Quote the absolute failure counts. The layout group's pass rate "
                "actually rises when recovery is removed (0.757 to 0.770) because an "
                "empty document has no elements to score, shrinking the denominator "
                "from 40,287 to 23,025. A rate quoted alone makes no-recovery look "
                "better."
            ),
            "forbidden": [
                "레이아웃 통과율을 복구 효과의 근거로 인용하는 표현",
                "규칙 위반 감소를 비율로만 제시하고 분모 변화를 생략하는 표현",
            ],
            **_evidence(repository, parse_with_path, parse_without_path),
        },
        {
            "id": "recovery-contribution-omnidocbench",
            "status": APPROVED,
            "headline_ko": "복구가 없으면 OmniDocBench 본문 편집거리가 4.5배로 악화됩니다",
            "headline_en": "Without recovery, OmniDocBench text edit distance degrades 4.5x",
            "numbers": {
                "text_edit_distance_with": round(edit(omni_with, "text_block"), 4),
                "text_edit_distance_without": round(edit(omni_without, "text_block"), 4),
                "reading_order_with": round(edit(omni_with, "reading_order"), 4),
                "reading_order_without": round(edit(omni_without, "reading_order"), 4),
                "table_teds_with": round(omni_with["table"]["all"]["TEDS"]["all"], 4),
                "table_teds_without": round(omni_without["table"]["all"]["TEDS"]["all"], 4),
            },
            "must_say": "편집거리는 낮을수록 좋고, TEDS는 높을수록 좋습니다.",
            "must_say_en": (
                "Lower edit distance is better; higher TEDS is better."
            ),
            **_evidence(repository, omni_with_path, omni_without_path),
        },
        {
            "id": "benchmark-accuracy",
            "status": APPROVED,
            "headline_ko": "공식 벤치마크 정확도 80.6%",
            "headline_en": "80.6% on the official benchmark",
            "numbers": {
                "benchmark": "olmOCR-Bench",
                "overall_percent": round(olm_with["overall_score"] * 100, 2),
                "confidence_interval_95": [
                    round(x * 100, 2) for x in olm_with["confidence_interval_95"]
                ],
                "checks_passed": olm_with["test_count"] - olm_with["rule_failure_count"],
                "checks_total": olm_with["test_count"],
                "documents_with_at_least_one_failure_percent": round(
                    blind["cases_with_official_failures"] / blind["corpus_cases"] * 100, 1
                ),
            },
            "must_say": (
                f"{olm_overall}은 문서 유형 {olm_score['types']}개의 통과율을 단순 "
                "평균한 값입니다. 적대적으로 설계된 개별 검사 기준으로는 "
                f"{olm_checks}가 통과했습니다. 공개 리더보드 최상위 시스템의 점수도 "
                f"{published_top}(재현하지 않은 공개 자료 인용값)이므로 비교 기준은 "
                "만점이 아닙니다. 캠페인 실패 분석에서 채점한 문서 "
                f"{failing_documents}에 최소 하나의 오류가 있으며, 이는 olmOCR-Bench "
                "문서만의 비율이 아닙니다. 무결성을 암시해서는 안 됩니다."
            ),
            "must_say_en": (
                f"{olm_overall} is the unweighted mean of the pass rates of the "
                f"{olm_score['types']} document types. Counted check by check, "
                f"{olm_checks} of the adversarially chosen checks pass. The top "
                f"published system scores {published_top}, a figure quoted from the public "
                "leaderboard and not reproduced by us, so the reference point is not a "
                "perfect score. "
                f"{failing_documents} of the documents scored in the campaign's "
                "failure study carry at least one failure, a rate over the whole "
                "campaign rather than olmOCR-Bench alone, so nothing here should "
                "imply flawless output."
            ),
            "declared_denominators": [failure_study],
            "forbidden": [
                "정확도 100% / 무오류 / 완벽한 추출",
                "80.6%를 단독 헤드라인으로 제시하고 유형별 편차를 생략하는 구성",
                "80.6을 8,413개 검사의 통과율로 표기하는 표현 (검사 기준 통과율은 별도 수치)",
            ],
            **_evidence(repository, olm_with_path, blind_path, leaderboard_path),
        },
        {
            "id": "customer-facing-fidelity",
            "status": APPROVED,
            "headline_ko": "본문 문자 일치율 94.2%, 표 구조 정확도 95.5%",
            "headline_en": "94.2% character-level text fidelity, 95.5% table structure accuracy",
            "numbers": {
                "text_character_match_percent": round(
                    (1 - edit(omni_with, "text_block")) * 100, 1
                ),
                "reading_order_match_percent": round(
                    (1 - edit(omni_with, "reading_order")) * 100, 1
                ),
                "table_structure_percent": round(
                    omni_with["table"]["all"]["TEDS_structure_only"]["all"] * 100, 1
                ),
                "table_full_percent": round(
                    omni_with["table"]["all"]["TEDS"]["all"] * 100, 1
                ),
            },
            "must_say": (
                f"이 수치는 olmOCR-Bench 점수 {olm_overall}(문서 유형 {olm_score['types']}개 "
                "통과율의 단순 평균)과 다른 척도입니다. 같은 화면에 둘 다 실을 때는 무엇을 "
                "재는 값인지 구분해 표기하십시오."
            ),
            "must_say_en": (
                f"These are a different measure from the olmOCR-Bench score of {olm_overall}, "
                f"the unweighted mean of the pass rates of the {olm_score['types']} document "
                "types. If both appear on one page, label what each one measures."
            ),
            **_evidence(repository, omni_with_path, olm_with_path),
        },
        {
            "id": "accuracy-by-document-type",
            "status": APPROVED,
            "headline_ko": "문서 유형별 정확도를 공개합니다",
            "headline_en": "Accuracy published per document type, not as one blended average",
            "numbers": [
                {
                    "label_ko": DOCUMENT_TYPE_LABELS.get(suite, (suite, suite))[0],
                    "label_en": DOCUMENT_TYPE_LABELS.get(suite, (suite, suite))[1],
                    "accuracy_percent": round(values["pass_rate"] * 100, 1),
                    "checks_passed": values["passed"],
                    "checks_total": values["total"],
                    "benchmark_slice": suite,
                }
                for suite, values in sorted(
                    olm_with["per_jsonl"].items(),
                    key=lambda item: -item[1]["pass_rate"],
                )
            ],
            "must_say": (
                "유형별 편차가 99.0%에서 36.9%까지 벌어집니다. 단일 평균만 제시하면 "
                "저품질 스캔본 고객에게 잘못된 기대를 심습니다. 저품질 스캔 구간은 "
                "반드시 함께 표기하십시오."
            ),
            "must_say_en": (
                "The spread runs from 99.0% to 36.9%. Publishing only the average sets "
                "the wrong expectation for anyone processing degraded scans, so the "
                "low-quality scan row must always be shown."
            ),
            "forbidden": [
                "benchmark_slice 값(old_scans.jsonl 등)을 화면에 그대로 노출",
                "저품질 스캔 행을 뺀 부분 표",
            ],
            **_evidence(repository, olm_with_path),
        },
        {
            "id": "product-pipeline",
            "status": APPROVED,
            "headline_ko": "추출에서 끝나지 않고 지식 아키텍처까지 컴파일합니다",
            "headline_en": (
                "The pipeline does not stop at extraction; it compiles a "
                "knowledge architecture"
            ),
            "numbers": {
                "stages": [
                    "사전 분류·난이도 판정",
                    "경로 선택",
                    "추출",
                    "정규 중간표현",
                    "아키텍처 설계",
                    "내보내기",
                ],
                "stages_en": [
                    "preflight classification",
                    "route selection",
                    "extraction",
                    "canonical intermediate representation",
                    "architecture planning",
                    "export",
                ],
                "builtin_blueprints": [
                    b["id"] for b in _blueprint_summary(repository)
                ],
                "export_targets": ["obsidian", "ontology", "neo4j", "rag"],
            },
            "must_say": (
                "이 단계들은 코드로 구현돼 있으나, 추출 단계와 달리 공개 벤치마크 "
                "점수가 존재하지 않습니다. 정확도 수치를 이 단계에 붙이지 마십시오. "
                "제시 가능한 근거는 compilation-guarantees의 구조적 보증입니다."
            ),
            "must_say_en": (
                "These stages are implemented, but unlike extraction they have no public "
                "benchmark score. Do not attach an accuracy figure to them; the "
                "supportable evidence is the structural guarantees claim."
            ),
            "forbidden": ["이 단계들에 대한 정확도·품질 백분율 표기"],
            **_evidence(
                repository,
                repository / "packages/domain-packs/src/akc_domain_packs/blueprints.py",
                repository / "packages/exporters/src/akc_exporters/vault.py",
                repository / "packages/exporters/src/akc_exporters/knowledge_package.py",
                compile_path,
            ),
        },
        {
            "id": "compilation-guarantees",
            "status": APPROVED,
            "headline_ko": (
                "산출물의 구조적 보증: 재현 가능한 아키텍처, 미해결 링크 0건, "
                "병합 시 무손실"
            ),
            "headline_en": (
                "Structural guarantees: reproducible architecture, no unresolved "
                "links, no silent loss on merge"
            ),
            "numbers": {
                "documents_exercised": compilation["vault_compilation"]["documents_offered"],
                "blueprints": compilation["architecture_determinism"]["blueprints_measured"],
                "architecture_repeats": compilation["architecture_determinism"][
                    "repeats_per_blueprint"
                ],
                "broken_links_in_output": compilation["vault_compilation"][
                    "broken_internal_links_in_emitted_vault"
                ],
                "merge_policies_tested": len(compilation["merge_safety"]["per_policy"]),
                "files_lost_silently": 0,
            },
            "must_say": (
                "이 보증은 산출물의 구조에 관한 것이며 추출된 텍스트의 정확성과는 "
                "별개 지표입니다."
            ),
            "must_say_en": (
                "These guarantees describe the structure of the compiled output. They "
                "are a separate measure from whether the extracted text is correct."
            ),
            **_evidence(repository, compile_path),
        },
        {
            "id": "leaderboard-position",
            "status": CONDITIONAL,
            "headline_ko": "공개 리더보드 상위권",
            "headline_en": "Competitive on the public leaderboard",
            "numbers": {
                "our_score": round(olm_with["overall_score"] * 100, 2),
                "published_top": 83.1,
                "published_reference_rows": {
                    "Chandra OCR 0.1.0": 83.1,
                    "olmOCR v0.4.0": 82.4,
                    "PaddleOCR-VL": 80.0,
                    "Mistral OCR API": 72.0,
                },
            },
            "conditions": [
                "리더보드 행은 공개 자료 인용이며 우리가 재현 검증한 값이 아닙니다.",
                "우리가 실행한 기반 모델의 버전이 리더보드에 실린 행과 다릅니다. "
                "특정 경쟁 제품을 몇 점 이겼다는 문장은 사용할 수 없습니다.",
                "평가기 체크아웃이 공식 저장소의 포크이며 Windows 경로 정규화 패치가 "
                "적용돼 있습니다. 채점 로직은 변경되지 않았습니다.",
            ],
            "forbidden": [
                "우리가 <경쟁사>보다 N점 높습니다",
                "업계 1위 / 최고 정확도",
            ],
            **_evidence(repository, leaderboard_path),
        },
        {
            "id": "cost-per-page",
            "status": CONDITIONAL,
            "headline_ko": "1,000페이지당 GPU 원가 $1.23",
            "headline_en": "$1.23 of GPU cost per 1,000 pages",
            "numbers": {
                "gpu_cost_per_1000_pages_healthy": 1.23,
                "gpu_cost_per_1000_pages_including_failures": 5.92,
                "throughput_pages_per_pod_hour": 600,
            },
            "conditions": [
                "이것은 GPU 원가이며 판매 가격이 아닙니다. 엔지니어링, 오케스트레이션, "
                "스토리지, 전송, 지원, 마진이 포함돼 있지 않습니다.",
                "경쟁사의 소매가와 나란히 놓으면 성립하지 않는 비교가 됩니다.",
            ],
            "forbidden": ["경쟁사 대비 N배 저렴 (원가와 소매가를 비교하는 모든 표현)"],
            **_evidence(repository, cost_path),
        },
        {
            "id": "quality-retry-improvement",
            "status": WITHHELD,
            "headline_ko": "(측정 미완료) 대상 지정 품질 재시도의 정확도 개선폭",
            "headline_en": "(not yet measured) accuracy gain from the targeted quality retry",
            "why_withheld": (
                "재시도와 무회귀 수용 게이트가 아직 실행되지 않았습니다. 측정 전에는 "
                "어떤 개선 수치도 웹사이트에 실을 수 없습니다."
            ),
            "unblocks_when": "quality retry + official re-evaluation + no-regression gate complete",
        },
        {
            "id": "blind-quality-detection",
            "status": WITHHELD,
            "headline_ko": "(기각됨) 정답지 없이 저품질 문서를 자동 선별",
            "headline_en": "(rejected) selecting low-quality documents without ground truth",
            "why_withheld": (
                "구현하고 같은 코퍼스에서 측정한 결과, 무작위 선택보다 낮은 실패 질량을 "
                "회수했고 예측 길이만으로 정렬하는 무탐지 기준선보다도 낮았습니다. "
                "제품 기능으로 광고할 근거가 없습니다."
            ),
            "numbers": {
                "hypothesis_supported": blind["outcome"]["supported"],
                "corpus_cases": blind["corpus_cases"],
            },
            **_evidence(repository, blind_path),
        },
    ]

    _check_evidence_is_bound(claims)
    _check_evidence_is_readable(repository, claims)
    _check_rates_carry_denominators(claims)
    _check_pending_ids_exist(claims)
    _check_must_say_numbers_are_cited(repository, claims)

    return {
        "schema": "folynta.public-claims-pack.v1",
        "purpose": (
            "웹사이트에 게시할 수 있는 주장과 게시할 수 없는 주장을 증거와 함께 구분합니다. "
            "수치는 영수증에서 생성되며 손으로 수정해서는 안 됩니다."
        ),
        "how_to_use": [
            "status가 approved인 항목은 numbers를 그대로 사용합니다.",
            "conditional 항목은 conditions를 함께 표기할 때만 사용합니다.",
            "withheld 항목은 게시하지 않습니다. why_withheld가 이유입니다.",
            "must_say와 forbidden은 문구 검토 기준입니다.",
            "수치를 바꾸려면 이 파일이 아니라 근거 영수증을 다시 생성하십시오.",
        ],
        "global_rules": [
            "완주율과 정확도를 같은 지표처럼 제시하지 않습니다.",
            "모든 비율에는 분모를 함께 표기합니다.",
            "우리가 실행하지 않은 경쟁 제품의 수치는 인용임을 명시합니다.",
            "원가와 판매 가격을 혼용하지 않습니다.",
        ],
        "claim_count": len(claims),
        "counts_by_status": {
            status: sum(1 for c in claims if c["status"] == status)
            for status in (APPROVED, CONDITIONAL, WITHHELD)
        },
        "claims": claims,
    }


def render_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# 웹사이트 게시용 클레임 팩",
        "",
        "이 문서는 캠페인 증거 영수증에서 자동 생성됩니다. 수치를 여기서 직접 고치지 마십시오.",
        "",
        "## 사용법",
        "",
    ]
    lines += [f"- {rule}" for rule in pack["how_to_use"]]
    lines += ["", "## 공통 규칙", ""]
    lines += [f"- {rule}" for rule in pack["global_rules"]]

    for status, title in (
        (APPROVED, "게시 가능"),
        (CONDITIONAL, "조건부 게시"),
        (WITHHELD, "게시 불가"),
    ):
        selected = [c for c in pack["claims"] if c["status"] == status]
        if not selected:
            continue
        lines += ["", f"## {title} ({len(selected)}건)", ""]
        for claim in selected:
            lines += [f"### {claim['headline_ko']}", ""]
            lines += [f"`{claim['id']}` — {claim.get('headline_en','')}", ""]
            if claim.get("numbers"):
                rendered = json.dumps(claim["numbers"], ensure_ascii=False, indent=2)
                lines += ["```json", rendered, "```", ""]
            if claim.get("must_say"):
                lines += [f"**반드시 함께 표기**: {claim['must_say']}", ""]
            if claim.get("must_say_en"):
                lines += [f"**Must accompany the number**: {claim['must_say_en']}", ""]
            for condition in claim.get("conditions", []):
                lines += [f"- 조건: {condition}"]
            for forbidden in claim.get("forbidden", []):
                lines += [f"- 금지 표현: {forbidden}"]
            if claim.get("why_withheld"):
                lines += [f"**게시 불가 사유**: {claim['why_withheld']}", ""]
            if claim.get("unblocks_when"):
                lines += [f"**해제 조건**: {claim['unblocks_when']}", ""]
            if claim.get("evidence"):
                lines += ["", f"근거: `{claim['evidence']}`", ""]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pack = build_claims(args.repository_root)
    pack["receipt_sha256"] = _canonical_hash(pack)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(render_markdown(pack), encoding="utf-8")
    print(
        json.dumps(
            {
                "claim_count": pack["claim_count"],
                "counts_by_status": pack["counts_by_status"],
                "receipt_sha256": pack["receipt_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
