"""The two prose deliverables: the Korean executive summary and methodology.md.

``executive_summary_ko.md`` follows the masterplan section 48 template
verbatim; every ``[RESULT]`` slot is filled only when the underlying table
actually names a winner, and is left as the literal string ``[RESULT]``
otherwise — the instruction the masterplan gives for a campaign whose results
are not in yet. ``methodology.md`` states the single-run caveat (section 2.3)
in the words the masterplan itself forbids overstating: never
"deterministic", never "reproduced", never a confirmed champion.
"""

from __future__ import annotations

from typing import Any

from arena.constants import CAMPAIGN_ID, OPUS_DISPLAY_NAME
from arena.reports.common import Cell, TableSpec

__all__ = ["build_executive_summary_ko", "build_methodology"]

_BENCHMARK_COLUMNS = ("ParseBench", "OmniDoc", "olmOCR")


def _best_by_column(table: TableSpec, column: str, *, lower_is_better: bool = False) -> str | None:
    """The System name with the best (numeric) value in ``column``, or ``None``."""

    best_system: str | None = None
    best_value: float | None = None
    for row in table.rows:
        cell = row.get(column)
        system_cell = row.get("System") or row.get("model_key")
        if not isinstance(cell, Cell) or cell.value is None:
            continue
        if not isinstance(system_cell, Cell) or system_cell.value is None:
            continue
        value = float(cell.value)
        if best_value is None or (value < best_value if lower_is_better else value > best_value):
            best_value = value
            best_system = str(system_cell.value)
    return best_system


def _best_document_type(breakdown: TableSpec, family: str) -> str | None:
    best_model: str | None = None
    best_value: float | None = None
    for row in breakdown.rows:
        doc_type = row.get("document_type")
        metric = row.get("mean_metric")
        model = row.get("model_key")
        if not isinstance(doc_type, Cell) or doc_type.value != family:
            continue
        if not isinstance(metric, Cell) or metric.value is None:
            continue
        if not isinstance(model, Cell) or model.value is None:
            continue
        value = float(metric.value)
        if best_value is None or value > best_value:
            best_value = value
            best_model = str(model.value)
    return best_model


def build_executive_summary_ko(
    *,
    leaderboard: TableSpec,
    document_type_breakdown: TableSpec,
    tavonel_routes: TableSpec,
) -> str:
    fastest = _best_by_column(leaderboard, "sec_per_page", lower_is_better=True)
    best_table = _best_document_type(document_type_breakdown, "tables")
    best_hard_scan = _best_document_type(document_type_breakdown, "old_scan")
    best_per_benchmark = {
        column: _best_by_column(leaderboard, column) for column in _BENCHMARK_COLUMNS
    }

    best_variant_quality: str | None = None
    for row in tavonel_routes.rows:
        variant = row.get("variant")
        oracle = row.get("is_oracle")
        if not isinstance(variant, Cell) or not isinstance(oracle, Cell):
            continue
        if oracle.value is True:
            continue
        opus_pct = row.get("opus_usage_pct")
        if isinstance(opus_pct, Cell) and opus_pct.value is not None:
            best_variant_quality = str(variant.value)
            break

    def _slot(value: str | None) -> str:
        return value if value is not None else "[RESULT]"

    overall_lines = "\n".join(
        f"{name}: {_slot(best_per_benchmark[name])}" for name in _BENCHMARK_COLUMNS
    )

    return f"""# {CAMPAIGN_ID} — 결과 요약 (초안)

세 종류의 공개 문서 벤치마크 총 5,132개를 대상으로
최신 문서 OCR/VLM과 {OPUS_DISPLAY_NAME}를 동일 Golden Set으로 비교했다.

가장 빠른 모델:
{_slot(fastest)}

표/레이아웃:
{_slot(best_table)}

텍스트:
[RESULT]

어려운 스캔:
{_slot(best_hard_scan)}

전체 (benchmark별, 하나의 blended 숫자로 뭉개지 않음):
{overall_lines}

또한 단일 최고 모델과 TAVONEL의 복구/적응형 라우팅을 비교한 결과:
{_slot(best_variant_quality)}

## Negative results (항상 포함)

이 초안은 자동 생성되었고, 아래 표들에 실제 값이 채워지기 전까지는
위 [RESULT] 자리가 그대로 남는다. 결과가 나쁘게 나온 항목도 그대로 보고한다:
강한 모델의 category별 약점, Opus가 특화 OCR 모델보다 낮은 경우, Adaptive가
single-best보다 나쁜 경우, Recovery가 일부 페이지를 악화시킨 경우 등은 삭제하거나
숨기지 않는다 (masterplan section 46).

모든 비율에는 분모가 함께 표기된다 (leaderboard.csv, reliability_report.csv 참조).
"""


def build_methodology(*, evaluator_registry: dict[str, Any] | None) -> str:
    evaluator_lines: list[str] = []
    if isinstance(evaluator_registry, dict):
        evaluators = evaluator_registry.get("evaluators")
        if isinstance(evaluators, dict):
            for benchmark, record in sorted(evaluators.items()):
                if not isinstance(record, dict):
                    continue
                pin = record.get("main_pin") or record.get("historical_pin") or "unknown"
                evaluator_lines.append(f"- {benchmark}: evaluator pinned at `{pin}`")
    evaluator_block = (
        "\n".join(evaluator_lines)
        if evaluator_lines
        else "- evaluator_registry.json was not found; evaluator pins are not listed here."
    )

    return f"""# Methodology — {CAMPAIGN_ID}

## Experiment naming

Every result from the Claude lane is labelled exactly:

> {OPUS_DISPLAY_NAME}

never "Claude Opus 5 API benchmark" (masterplan section 21.1) — nothing here
went through the API; it ran through the Claude Code subscription surface,
and its image handling goes through the Claude Code Read tool rather than a
raw-image API call (masterplan section 21.10). Its per-page receipt records
the original image dimensions, bytes and sha256 alongside that caveat.

## What this campaign supports, and what it does not (masterplan 2.3, 2.4)

This is a **full public benchmark, single run**. It supports:

- engineering comparison across the eleven open candidates and Claude Opus 5
- model selection for this campaign's cost/latency/quality trade-off
- system ablation between the TAVONEL variants (A-E)
- the company presentation in ``executive_summary_ko.md``

It does **not** support, from this run alone:

- a claim that any result is "fully deterministic"
- a claim that "reproducibility has been verified"
- a champion "confirmed at 95% CI"
- a claim that one system "always wins" across every run

A frontier model's exposure to a public benchmark during training cannot be
ruled out, so a strong public-benchmark score is evidence for engineering
comparison and model selection, not for unseen real-world generalization —
that claim would need a fresh, private held-out set (masterplan section 2.4).

Repeatability, if it is wanted for the finalists, is a separate follow-up
experiment; it is not something this single pass can retroactively claim.

## Evaluator pins

{evaluator_block}

## Tables kept apart on purpose

ParseBench, OmniDocBench and olmOCR-Bench measure different things
(masterplan section 28). ``LEADERBOARD.md`` and ``leaderboard.csv`` report
them as three separate columns; no run in this campaign computes a blended
"overall" score across benchmarks.

## Every rate carries its denominator

``reliability_report.csv`` and ``leaderboard.csv`` report every percentage
alongside the count it was computed from. A cell that could not be computed
from these inputs is the literal string ``n/a``, never ``0``.
"""
