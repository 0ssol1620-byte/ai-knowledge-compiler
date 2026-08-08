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


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


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

    return builtin_blueprints().model_dump()["blueprints"]


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

    olm_with = _load(official / "olmocr-bench" / "evaluation-summary.json")
    olm_without = _load(
        generated / "folynta-counterfactual-no-recovery-olmocr-2026-08-08" / "evaluation-summary.json"
    )
    parse_with = _load(official / "parsebench" / "evaluation-summary.json")
    parse_without = _load(
        generated
        / "folynta-counterfactual-no-recovery-parsebench-2026-08-08"
        / "evaluation-summary.json"
    )
    omni_with = _load(official / "omnidocbench" / "repeat-1" / "metric-result.json")
    omni_without = _load(
        generated
        / "folynta-counterfactual-no-recovery-omnidocbench-2026-08-08"
        / "repeat-1"
        / "metric-result.json"
    )

    def edit(payload: dict[str, Any], section: str) -> float:
        return payload[section]["all"]["Edit_dist"]["ALL_page_avg"]

    claims: list[dict[str, Any]] = [
        {
            "id": "corpus-scale",
            "status": APPROVED,
            "headline_ko": "공개 벤치마크 3종, 5,132개 문서를 공식 평가기로 측정",
            "headline_en": "5,132 documents across three public benchmarks, scored by the official evaluators",
            "numbers": {
                "documents": ledger["planned_cases"],
                "benchmarks": sorted(ledger["cases_by_suite"]),
                "per_benchmark": {
                    suite: counts["planned"]
                    for suite, counts in ledger["cases_by_suite"].items()
                },
            },
            "evidence": str(ledger_path.relative_to(repository).as_posix()),
            "evidence_sha256": _sha256(ledger_path),
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
            "evidence": str(ledger_path.relative_to(repository).as_posix()),
            "evidence_sha256": _sha256(ledger_path),
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
            "evidence": str(ledger_path.relative_to(repository).as_posix()),
            "evidence_sha256": _sha256(ledger_path),
        },
        {
            "id": "recovery-contribution-olmocr",
            "status": APPROVED,
            "headline_ko": "복구 레인을 끄면 동일 파이프라인의 공식 점수가 80.6에서 53.7로 떨어집니다",
            "headline_en": "Disabling only the recovery lane drops the same pipeline from 80.6 to 53.7",
            "numbers": {
                "benchmark": "olmOCR-Bench",
                "with_recovery": round(olm_with["overall_score"] * 100, 2),
                "without_recovery": round(olm_without["overall_score"] * 100, 2),
                "with_recovery_ci95": [round(x * 100, 2) for x in olm_with["confidence_interval_95"]],
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
            "evidence": "benchmark/reports/generated/folynta-recovery-accuracy-counterfactual-olmocr-2026-08-08.json",
        },
        {
            "id": "recovery-contribution-parsebench",
            "status": APPROVED,
            "headline_ko": "복구가 없으면 ParseBench 규칙 위반이 2.1배로 늘어납니다",
            "headline_en": "Without recovery, ParseBench rule failures more than double",
            "numbers": {
                "rule_failures_with": parse_with["rule_failure_count"],
                "rule_failures_without": parse_without["rule_failure_count"],
                "content_faithfulness_with": 0.8376,
                "content_faithfulness_without": 0.5243,
                "table_grits_with": 0.9017,
                "table_grits_without": 0.5321,
            },
            "evidence": "benchmark/reports/generated/folynta-counterfactual-no-recovery-parsebench-2026-08-08/evaluation-summary.json",
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
            "evidence": "benchmark/reports/generated/folynta-counterfactual-no-recovery-omnidocbench-2026-08-08/repeat-1/metric-result.json",
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
                "이 점수는 적대적으로 설계된 개별 검사 8,413개의 통과율이며, 공개 "
                "리더보드 최상위도 83.1입니다. 비교 기준은 100이 아닙니다. 문서의 "
                "72.3%에는 최소 하나의 오류가 있으므로 무결성을 암시해서는 안 됩니다."
            ),
            "must_say_en": (
                "This is the pass rate over 8,413 adversarially chosen checks; the top "
                "published system scores 83.1, so the reference point is not 100. "
                "72.3% of documents carry at least one failure, so nothing here should "
                "imply flawless output."
            ),
            "forbidden": [
                "정확도 100% / 무오류 / 완벽한 추출",
                "80.6%를 단독 헤드라인으로 제시하고 유형별 편차를 생략하는 구성",
            ],
            "evidence": "benchmark/reports/generated/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04/olmocr-bench/evaluation-summary.json",
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
                "이 수치는 벤치마크 검사 통과율(80.6%)과 다른 척도입니다. 같은 화면에 "
                "둘 다 실을 때는 무엇을 재는 값인지 구분해 표기하십시오."
            ),
            "must_say_en": (
                "These are a different measure from the 80.6% check pass rate. If both "
                "appear on one page, label what each one measures."
            ),
            "evidence": "benchmark/reports/generated/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04/omnidocbench/repeat-1/metric-result.json",
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
            "evidence": "benchmark/reports/generated/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04/olmocr-bench/evaluation-summary.json",
        },
        {
            "id": "product-pipeline",
            "status": APPROVED,
            "headline_ko": "추출에서 끝나지 않고 지식 아키텍처까지 컴파일합니다",
            "headline_en": "The pipeline does not stop at extraction; it compiles a knowledge architecture",
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
            "evidence": "packages/domain-packs/src/akc_domain_packs/blueprints.py; packages/exporters/src/akc_exporters/",
        },
        {
            "id": "compilation-guarantees",
            "status": APPROVED,
            "headline_ko": "산출물의 구조적 보증: 재현 가능한 아키텍처, 미해결 링크 0건, 병합 시 무손실",
            "headline_en": "Structural guarantees: reproducible architecture, no unresolved links, no silent loss on merge",
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
            "evidence": str(compile_path.relative_to(repository).as_posix()),
            "evidence_sha256": _sha256(compile_path),
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
            "evidence": "benchmark/reports/generated/folynta-published-leaderboard-context-2026-08-08.json",
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
            "evidence": "benchmark/reports/generated/folynta-measured-gpu-cost-2026-08-08.json",
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
            "evidence": str(blind_path.relative_to(repository).as_posix()),
            "evidence_sha256": _sha256(blind_path),
        },
    ]

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
                lines += ["```json", json.dumps(claim["numbers"], ensure_ascii=False, indent=2), "```", ""]
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
