"""Tests for the KB1 harness and Korean key-token extractor.

Every page here is SYNTHETIC test data (page ids carry the label). No number in
this file is a measured result.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from akc_quality.numeric import compare_numeric_tokens, extract_numeric_tokens

from research.kb1_korean_bench import harness
from research.kb1_korean_bench.harness import (
    EVALUATOR_BLOCKED,
    GOLD_SCHEMA,
    MEASURED,
    NOT_MEASURED,
    RUN_SCHEMA,
    UNSUPPORTED,
    GoldContractError,
    RunContractError,
    align,
    family_cluster_bootstrap,
    score,
)
from research.kb1_korean_bench.ko_tokens import Token, extract


# --------------------------------------------------------------- §2.3 receipts
# The "naive pattern" is the shipped checker: akc_quality.numeric in its default
# "legacy" mode, which KB-A6 kept byte-identical. The defect is reproduced against
# that code, not against a copy of its regex. KO-NUMERIC-PROBE.py (sha256
# e8ee7e1c99f9b100634eb59db9e59f8616ce241cbc4a46e3e4a4496a4a7b2e68) ran the same
# pattern, copied verbatim, to produce the receipt below.
def _naive(text: str) -> tuple[str, ...]:
    return extract_numeric_tokens(text, mode="legacy")


# Naive output exactly as KO-NUMERIC-PROBE.out.txt recorded it
# (sha256 cdd7e95ee39f9928936293601c06742ad016034062cc27f12d499f94912d1073).
RECEIPT: dict[str, tuple[str, ...]] = {
    "계정 001, 증감 -2.50%, 총액 ₩1,000": ("001", "-2.50%", "₩1,000"),
    "계약 종료 후 30일": (),
    "1,000원": ("1",),
    "제7조 제1항": (),
    "2026. 10. 17.": ("2026", "10", "17"),
    "2026.10.17": ("2026.10.17",),
    "매출은 10% 증가했다.": ("10%",),
    "매출은 10%가 증가": ("10",),
    "금 1,234,000원정": ("1,234",),
    "3억 5천만원": (),
}

EXPECTED: dict[str, list[Token]] = {
    "계정 001, 증감 -2.50%, 총액 ₩1,000": [
        Token("number", "001", "001"),
        Token("percent", "-2.50%", "-2.50%"),
        Token("amount", "₩1,000", "₩1,000"),
    ],
    "계약 종료 후 30일": [Token("number_unit", "30일", "30일")],
    "1,000원": [Token("amount", "1,000원", "1,000원")],
    "제7조 제1항": [Token("article", "제7조제1항", "제7조제1항")],
    "2026. 10. 17.": [Token("date", "2026-10-17", "2026.10.17.")],
    "2026.10.17": [Token("date", "2026-10-17", "2026.10.17")],
    "매출은 10% 증가했다.": [Token("percent", "10%", "10%")],
    "매출은 10%가 증가": [Token("percent", "10%", "10%")],
    "금 1,234,000원정": [Token("amount", "1,234,000원", "1,234,000원")],
    "3억 5천만원": [Token("amount", "3억5천만원", "3억5천만원")],
}

# The receipt itself shows the naive pattern already reads these three correctly;
# they stay as no-regression controls rather than being reported as failures.
CONTROLS = {"계정 001, 증감 -2.50%, 총액 ₩1,000", "2026.10.17", "매출은 10% 증가했다."}
DEFECTS = sorted(set(RECEIPT) - CONTROLS)


@pytest.mark.parametrize("case", list(RECEIPT))
def test_naive_pattern_reproduces_the_receipt(case: str) -> None:
    # A caller that passes no mode gets the same defect.
    assert extract_numeric_tokens(case) == _naive(case) == RECEIPT[case]


@pytest.mark.parametrize("case", list(RECEIPT))
def test_ko_tokens_reads_every_receipt_case(case: str) -> None:
    assert extract(case) == EXPECTED[case]


@pytest.mark.parametrize("case", DEFECTS)
def test_naive_pattern_fails_the_defect_case(case: str) -> None:
    assert _naive(case) != tuple(token.surface for token in EXPECTED[case])


@pytest.mark.parametrize("case", sorted(CONTROLS))
def test_naive_pattern_agrees_on_the_control_case(case: str) -> None:
    assert _naive(case) == tuple(token.surface for token in EXPECTED[case])


def test_seven_of_the_ten_receipt_cases_are_defects() -> None:
    assert len(RECEIPT) == 10
    misread = sorted(c for c in RECEIPT if _naive(c) != tuple(t.surface for t in EXPECTED[c]))
    assert misread == DEFECTS
    assert len(misread) == 7


def test_ko_tokens_never_truncates_and_reads_more_korean_forms() -> None:
    text = "제3자에게 2026년 10월 17일까지 02-123-4567 123-45-67890 1분기 2.5%p 12,3456"
    assert [(t.kind, t.value) for t in extract(text)] == [
        ("number", "3"),
        ("date", "2026-10-17"),
        ("phone", "02-123-4567"),
        ("business_id", "123-45-67890"),
        ("number_unit", "1분기"),
        ("percent", "2.5%p"),
    ]  # the malformed "12,3456" yields nothing rather than a shorter number


# ------------------------------------------------------------------- fixtures

CAPS_NONE = {name: False for name in harness.CAPABILITIES}
CAPS_ALL = {name: True for name in harness.CAPABILITIES}


def _gold_page(pid: str, text: str, **extra: Any) -> dict[str, Any]:
    page = {
        "page_id": f"SYNTHETIC-{pid}",
        "family_id": "SYNTHETIC-family-1",
        "category": "KS",
        "synthetic": True,
        "text": text,
    }
    page.update(extra)
    return page


def _gold(*pages: dict[str, Any]) -> dict[str, Any]:
    return {"schema": GOLD_SCHEMA, "dataset_revision": "SYNTHETIC-test", "pages": list(pages)}


def _row(
    pid: str, text: str | None = None, status: str = "SUCCESS", **extra: Any
) -> dict[str, Any]:
    row: dict[str, Any] = {"page_id": f"SYNTHETIC-{pid}", "status": status}
    if text is not None:
        row["text"] = text
    row.update(extra)
    return row


def _run(*rows: dict[str, Any], caps: dict[str, bool] | None = None) -> dict[str, Any]:
    capabilities = CAPS_NONE if caps is None else caps
    return {
        "schema": RUN_SCHEMA,
        "arm": {"arm_id": "SYNTHETIC-arm", "capabilities": capabilities},
        "pages": list(rows),
    }


def _ks(report: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = report["categories"]["KS"]["metrics"]
    return metrics


def _score(gold: dict[str, Any], run: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("resamples", 200)
    return score(gold, run, **kwargs)


# ------------------------------------------------------------------- alignment


def test_alignment_prefers_substitution_over_indels_at_equal_distance() -> None:
    result = align("ab", "ba")
    assert (result.distance, result.gold_ops, result.inserted) == (2, "SS", ())


def test_alignment_counts_insertions_and_deletions() -> None:
    result = align("가나다라", "가다라마")
    assert result.distance == 2
    assert result.gold_ops == "MDMM"
    assert result.inserted == (3,)


# ----------------------------------------------------------- report contract

RICH_GOLD = _gold(
    _gold_page(
        "rich",
        "견본 기관 제7조 ① 大韓 1,000원 본문",
        blocks=["견본 기관", "제7조 ① 大韓", "1,000원 본문"],
        lines=[{"text": "견본 기관", "bbox": [0, 0, 100, 10]}],
        table_count=1,
        table_text_spans=[[15, 21]],
        seal={"text": "견본인", "occluded_spans": [[22, 24]]},
        approval_box=True,
    )
)
RICH_RUN = _run(
    _row(
        "rich",
        "견본 기관 제7조 ① 大韓 1,000원 본문",
        blocks=["견본 기관", "제7조 ① 大韓", "1,000원 본문"],
        regions=[{"text": "견본 기관", "bbox": [0, 0, 100, 10]}],
        approval_box_detected=True,
        latency_ms=1200,
    ),
    caps=CAPS_ALL,
)
TEDS = {
    "evaluator": {"repository": "SYNTHETIC-omnidoc", "main_pin": "193627ae"},
    "pages": {"SYNTHETIC-rich": {"teds": 0.5, "teds_struct": 0.75}},
}


def test_perfect_output_measures_every_metric_with_prereg_keys() -> None:
    report = _score(RICH_GOLD, RICH_RUN, evaluator_scores=TEDS)
    metrics = _ks(report)
    # KB1-PREREG.json (sha256 cb51fd44…) metrics.primary.id + metrics.secondary[].id
    assert set(metrics) == {"M1", "M1-s", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"}
    assert all(metrics[m]["status"] == MEASURED for m in metrics)
    assert set(report["categories"]["KS"]["operational"]) == {"completion", "latency", "cost"}
    assert set(report["normalization"]) >= {
        "unicode",
        "whitespace",
        "allowlist_revision",
        "compat_ideograph",
        "nfkc_secondary_report",
    }
    assert report["statistics"]["seed"] == "tavonel-kb1-bootstrap-2026-10-17"
    assert metrics["M1"]["micro_cer"]["value"] == 0
    assert metrics["M2"]["f1"]["value"] == 1
    assert metrics["M3"]["amount"]["recall"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert metrics["M4"]["teds"]["value"] == 0.5
    assert metrics["M5"]["kendall_tau_distance"]["value"] == 0
    assert metrics["M6"]["recall"]["value"] == 1
    assert metrics["M7"]["occluded_cer"]["value"] == 0
    assert metrics["M7"]["approval_box"]["detected"]["value"] == 1
    assert metrics["M8"]["insertion_rate"]["value"] == 0
    assert metrics["M9"]["lines_located"]["value"] == 1
    assert report["categories"]["KS"]["operational"]["latency"]["p50_ms"] == 1200


def _walk(node: Any) -> list[dict[str, Any]]:
    found = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk(value))
    return found


def test_every_ratio_carries_numerator_and_denominator() -> None:
    report = _score(RICH_GOLD, RICH_RUN, evaluator_scores=TEDS)
    ratios = [d for d in _walk(report) if {"value", "numerator", "denominator"} & set(d)]
    assert len(ratios) > 30
    for ratio in ratios:
        assert {"numerator", "denominator", "value"} <= set(ratio), ratio


def test_report_is_deterministic() -> None:
    first = _score(RICH_GOLD, RICH_RUN, evaluator_scores=TEDS)
    second = _score(RICH_GOLD, RICH_RUN, evaluator_scores=TEDS)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_thresholds_are_the_preregistered_proposals() -> None:
    assert harness.PAGE_CER_THRESHOLD == 0.10
    assert harness.M9_IOU_THRESHOLD == 0.5
    assert (harness.MIN_CONFIRM_PAGES, harness.MIN_FAMILIES, harness.MAX_PAGES_PER_FAMILY) == (
        50,
        10,
        5,
    )
    assert harness.BOOTSTRAP_RESAMPLES == 10_000
    assert "not calibrated" in (harness.__doc__ or "")


# --------------------------------------------------------------- failure paths


def test_empty_output_stays_in_the_denominator_at_cer_one() -> None:
    report = _score(_gold(_gold_page("p1", "한국어 문서 1,000원")), _run(_row("p1", "")))
    metrics = _ks(report)
    assert metrics["M1"]["micro_cer"] == {"numerator": 11, "denominator": 11, "value": 1.0}
    assert metrics["M3"]["amount"]["recall"]["value"] == 0
    completion = report["categories"]["KS"]["operational"]["completion"]["pages_with_output"]
    assert completion == {"numerator": 0, "denominator": 1, "value": 0.0}


@pytest.mark.parametrize("status", ["FAILED", "TIMEOUT", "LIMIT_REJECTED"])
def test_failed_rows_stay_in_the_denominator(status: str) -> None:
    gold = _gold(_gold_page("ok", "가나다라"), _gold_page("bad", "마바사"))
    run = _run(_row("ok", "가나다라"), _row("bad", status=status))
    micro = _ks(_score(gold, run))["M1"]["micro_cer"]
    assert micro == {"numerator": 3, "denominator": 7, "value": 3 / 7}


def test_failed_row_carrying_text_is_rejected() -> None:
    with pytest.raises(RunContractError, match="must not carry output text"):
        _score(_gold(_gold_page("p1", "가나")), _run(_row("p1", "가나", status="FAILED")))


def test_nfd_input_scores_as_nfc() -> None:
    text = "한국어 문서 1,000원 제7조"
    nfd = unicodedata.normalize("NFD", text)
    assert nfd != text
    for gold_text, out_text in ((text, nfd), (nfd, text)):
        metrics = _ks(_score(_gold(_gold_page("p1", gold_text)), _run(_row("p1", out_text))))
        assert metrics["M1"]["micro_cer"]["value"] == 0
        assert metrics["M3"]["amount"]["recall"]["value"] == 1
        assert metrics["M3"]["article"]["recall"]["value"] == 1
    assert extract(nfd) == extract(text)


def test_gold_with_private_use_glyphs_is_rejected() -> None:
    gold = _gold(_gold_page("p1", "본문" + chr(0xE000) + "글자"))
    with pytest.raises(GoldContractError, match="Private Use Area"):
        _score(gold, _run(_row("p1", "본문글자")))


def test_output_private_use_glyphs_count_as_errors_and_are_reported() -> None:
    gold = _gold(_gold_page("p1", "본문글자"))
    metrics = _ks(_score(gold, _run(_row("p1", "본문" + chr(0xE000) + "자"))))
    assert metrics["M1"]["micro_cer"]["numerator"] == 1
    assert metrics["M8"]["output_pua_chars"] == {"numerator": 1, "denominator": 4, "value": 0.25}


def test_repetition_runaway_is_capped_at_one_and_insertions_reported() -> None:
    gold_text = "반복 폭주 검사"
    metrics = _ks(_score(_gold(_gold_page("p1", gold_text)), _run(_row("p1", gold_text * 30))))
    assert metrics["M1"]["micro_cer"] == {"numerator": 6, "denominator": 6, "value": 1.0}
    assert metrics["M1"]["runaway_capped_pages"]["value"] == 1
    assert metrics["M8"]["insertion_rate"]["numerator"] == 29 * 6


def test_runaway_beyond_alignment_budget_still_scores_m1_and_blocks_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harness, "MAX_ALIGNMENT_CELLS", 10)
    metrics = _ks(_score(_gold(_gold_page("p1", "가나다")), _run(_row("p1", "라마바사아자차"))))
    assert metrics["M1"]["micro_cer"]["value"] == 1.0
    for metric in ("M1-s", "M2", "M6", "M8"):
        assert metrics[metric]["status"] == EVALUATOR_BLOCKED
        keys = set(metrics[metric]) - {"raw_codepoint_secondary"}
        assert keys == {"status", "blocked_pages", "page_ids", "reasons"}
    assert metrics["M6"]["raw_codepoint_secondary"]["status"] == EVALUATOR_BLOCKED


def test_evaluator_failure_is_blocked_never_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness, "MAX_ALIGNMENT_CELLS", 3)
    metrics = _ks(_score(_gold(_gold_page("p1", "가나다라")), _run(_row("p1", "마바사"))))
    m1 = metrics["M1"]
    assert m1["status"] == EVALUATOR_BLOCKED
    assert m1["blocked_pages"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert "micro_cer" not in m1 and "ci95" not in m1


def test_missing_m4_scores_block_and_capability_gates_m4() -> None:
    blocked = _ks(_score(RICH_GOLD, RICH_RUN))["M4"]
    assert blocked["status"] == EVALUATOR_BLOCKED
    assert blocked["reasons"] == ["no OmniDocBench TEDS scores supplied (KB-A4 adapter)"]
    no_record = {"pages": TEDS["pages"]}
    assert _ks(_score(RICH_GOLD, RICH_RUN, evaluator_scores=no_record))["M4"]["status"] == (
        EVALUATOR_BLOCKED
    )
    failed = _run(_row("rich", status="TIMEOUT"), caps=CAPS_ALL)
    m4 = _ks(_score(RICH_GOLD, failed))["M4"]
    assert m4["teds"] == {"numerator": 0.0, "denominator": 1, "value": 0.0}
    unsupported = _run(_row("rich", "견본 기관"))
    metrics = _ks(_score(RICH_GOLD, unsupported))
    for metric, capability in (("M4", "table_structure"), ("M5", "blocks"), ("M9", "region_bbox")):
        assert metrics[metric]["status"] == UNSUPPORTED
        assert metrics[metric]["capability"] == [capability]
    assert metrics["M7"]["approval_box"]["status"] == UNSUPPORTED
    # Without table structure the table-region text is still scored (design §5.3 M4).
    table_text = metrics["M4"]["table_text_cer"]["cer_on_gold_table_characters"]
    assert table_text == {"numerator": 6, "denominator": 6, "value": 1.0}


def test_missing_unknown_and_duplicate_rows_are_rejected() -> None:
    gold = _gold(_gold_page("p1", "가"), _gold_page("p2", "나"))
    with pytest.raises(RunContractError, match="missing 1"):
        _score(gold, _run(_row("p1", "가")))
    with pytest.raises(RunContractError, match="unknown 1"):
        _score(gold, _run(_row("p1", "가"), _row("p2", "나"), _row("p3", "다")))
    with pytest.raises(RunContractError, match="duplicate"):
        _score(gold, _run(_row("p1", "가"), _row("p1", "가"), _row("p2", "나")))


def test_capability_fields_must_agree_with_the_declaration() -> None:
    gold = _gold(_gold_page("p1", "가"))
    with pytest.raises(RunContractError, match="declares blocks: false"):
        _score(gold, _run(_row("p1", "가", blocks=["가"])))
    with pytest.raises(RunContractError, match="has no 'regions'"):
        _score(gold, _run(_row("p1", "가", blocks=[], approval_box_detected=False), caps=CAPS_ALL))
    with pytest.raises(RunContractError, match="capabilities"):
        _score(gold, {"schema": RUN_SCHEMA, "arm": {"arm_id": "SYNTHETIC-arm"}, "pages": []})


def test_gold_contract_is_enforced() -> None:
    with pytest.raises(GoldContractError, match="synthetic: true"):
        _score(_gold(_gold_page("p1", "가", synthetic=False)), _run(_row("p1", "가")))
    with pytest.raises(GoldContractError, match="no non-whitespace"):
        _score(_gold(_gold_page("p1", "   ")), _run(_row("p1", "")))
    with pytest.raises(GoldContractError, match="table_count > 0"):
        _score(_gold(_gold_page("p1", "가나", table_text_spans=[[0, 1]])), _run(_row("p1", "가")))
    with pytest.raises(GoldContractError, match="span"):
        bad_seal = {"text": "인", "occluded_spans": [[0, 9]]}
        _score(_gold(_gold_page("p1", "가나", seal=bad_seal)), _run(_row("p1", "가")))
    with pytest.raises(GoldContractError, match="bbox"):
        bad_line = [{"text": "가", "bbox": [10, 0, 5, 10]}]
        _score(_gold(_gold_page("p1", "가", lines=bad_line)), _run(_row("p1", "가")))


# -------------------------------------------------------------------- metrics


def test_m1_s_attributes_errors_to_scripts() -> None:
    metrics = _ks(_score(_gold(_gold_page("p1", "가A1")), _run(_row("p1", "가B1"))))
    scripts = metrics["M1-s"]
    assert scripts["latin"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert scripts["hangul"]["value"] == 0 and scripts["digit"]["value"] == 0
    assert scripts["hanja"] == {"numerator": 0, "denominator": 0, "value": None}


def test_m2_spacing_f1() -> None:
    gold = _gold(_gold_page("p1", "삼성 전자 주가"))
    metrics = _ks(_score(gold, _run(_row("p1", "삼성전자 주가"))))
    assert metrics["M1"]["micro_cer"]["value"] == 0  # M1 ignores spacing
    assert metrics["M2"]["precision"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert metrics["M2"]["recall"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert metrics["M2"]["f1"] == {"numerator": 2, "denominator": 3, "value": 2 / 3}


def test_m3_catches_a_wrong_amount_the_naive_pattern_accepts() -> None:
    assert _naive("1,000원") == _naive("1,999원") == ("1",)
    assert compare_numeric_tokens("1,000원", "1,999원").score == 1.0  # legacy calls it exact
    metrics = _ks(_score(_gold(_gold_page("p1", "1,000원")), _run(_row("p1", "1,999원"))))
    assert metrics["M3"]["amount"]["recall"] == {"numerator": 0, "denominator": 1, "value": 0.0}


def test_m8_counts_foreign_script_excess_separately() -> None:
    kana = chr(0x30A2)  # KATAKANA LETTER A
    metrics = _ks(_score(_gold(_gold_page("p1", "가나")), _run(_row("p1", "가" + kana + "나"))))
    assert metrics["M8"]["insertion_rate"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert metrics["M8"]["foreign_script_excess_rate"]["numerator"] == 1


def test_m5_reading_order() -> None:
    gold = _gold(_gold_page("p1", "첫째 둘째 셋째", blocks=["첫째", "둘째", "셋째"]))
    caps = {**CAPS_NONE, "blocks": True}
    reversed_run = _run(_row("p1", "셋째 둘째 첫째", blocks=["셋째", "둘째", "첫째"]), caps=caps)
    m5 = _ks(_score(gold, reversed_run))["M5"]
    assert m5["kendall_tau_distance"] == {"numerator": 3, "denominator": 3, "value": 1.0}
    missing_run = _run(_row("p1", "첫째 둘째", blocks=["첫째", "둘째"]), caps=caps)
    m5 = _ks(_score(gold, missing_run))["M5"]
    assert m5["kendall_tau_distance"]["numerator"] == 2
    assert m5["matched_blocks"] == {"numerator": 2, "denominator": 3, "value": 2 / 3}


def test_m6_counts_a_hanja_reading_as_a_miss_and_reports_raw_code_points() -> None:
    metrics = _ks(_score(_gold(_gold_page("p1", "大韓民國 ①")), _run(_row("p1", "대한민국 ①"))))
    assert metrics["M6"]["recall"] == {"numerator": 1, "denominator": 5, "value": 0.2}
    compat = chr(0xF900)  # CJK compatibility ideograph; NFC folds it to U+8C48
    unified = unicodedata.normalize("NFC", compat)
    assert unified != compat
    metrics = _ks(_score(_gold(_gold_page("p1", compat + "가")), _run(_row("p1", unified + "가"))))
    assert metrics["M6"]["recall"]["value"] == 1
    assert metrics["M6"]["raw_codepoint_secondary"]["recall"]["value"] == 0


def test_m7_seal_occlusion_and_leak() -> None:
    gold = _gold(
        _gold_page("p1", "견본 공문 본문", seal={"text": "견본인", "occluded_spans": [[6, 8]]})
    )
    metrics = _ks(_score(gold, _run(_row("p1", "견본 공문 본묻인"))))
    assert metrics["M7"]["occluded_cer"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert metrics["M7"]["seal_leak"] == {"numerator": 1, "denominator": 3, "value": 1 / 3}
    assert metrics["M7"]["approval_box"]["status"] == NOT_MEASURED


def test_m9_requires_text_and_overlap() -> None:
    lines = [{"text": "근거 줄", "bbox": [0, 0, 100, 10]}]
    gold = _gold(_gold_page("p1", "근거 줄", lines=lines))
    caps = {**CAPS_NONE, "region_bbox": True}

    def located(region_text: str, bbox: list[int]) -> Any:
        regions = [{"text": region_text, "bbox": bbox}]
        report = _score(gold, _run(_row("p1", "근거 줄", regions=regions), caps=caps))
        return _ks(report)["M9"]["lines_located"]["value"]

    assert located("근거 줄", [0, 0, 100, 10]) == 1
    assert located("근거 줄", [60, 0, 160, 10]) == 0  # IoU 0.25
    assert located("다른 줄", [0, 0, 100, 10]) == 0


# ------------------------------------------------------- categories and stats


def test_categories_fail_closed() -> None:
    report = _score(_gold(_gold_page("p1", "가")), _run(_row("p1", "가")))
    for category in ("K1", "K2", "K3", "K4", "K5", "K6"):
        assert report["categories"][category]["publication_status"] == NOT_MEASURED
    assert report["categories"]["KS"]["publication_status"] == "SYNTHETIC_NOT_PUBLISHABLE"


def _k1_pages(count: int, families: int) -> tuple[dict[str, Any], dict[str, Any]]:
    # SYNTHETIC test data deliberately marked synthetic: false to exercise the
    # real-data sample floor; nothing here is a KB1 page.
    pages = [
        _gold_page(
            f"k1-{i}",
            "가나다",
            category="K1",
            synthetic=False,
            family_id=f"SYNTHETIC-f{i % families}",
        )
        for i in range(count)
    ]
    return _gold(*pages), _run(*(_row(f"k1-{i}", "가나다") for i in range(count)))


def test_sample_floor() -> None:
    gold, run = _k1_pages(12, 3)
    k1 = _score(gold, run)["categories"]["K1"]
    assert k1["publication_status"] == "INSUFFICIENT_SAMPLE"
    assert k1["sample_floor"]["met"] is False
    gold, run = _k1_pages(50, 10)
    k1 = _score(gold, run)["categories"]["K1"]
    assert k1["publication_status"] == "SAMPLE_FLOOR_MET_PROPOSED"
    assert k1["sample_floor"]["families"] == 10


def test_bootstrap_is_seed_deterministic() -> None:
    clusters = [(1.0, 10.0), (5.0, 10.0), (0.0, 12.0), (9.0, 10.0), (2.0, 8.0)]
    first = family_cluster_bootstrap(clusters, seed="s1", resamples=2000)
    assert first == family_cluster_bootstrap(clusters, seed="s1", resamples=2000)
    assert first != family_cluster_bootstrap(clusters, seed="s2", resamples=2000)
    assert 0 <= first["low"] <= 17 / 50 <= first["high"] <= 1
    with pytest.raises(ValueError, match="at least one cluster"):
        family_cluster_bootstrap([], seed="s1", resamples=10)


def test_m1_ci_uses_families_and_the_category_seed() -> None:
    gold = _gold(
        _gold_page("a", "가나다라", family_id="SYNTHETIC-fa"),
        _gold_page("b", "마바사아", family_id="SYNTHETIC-fb"),
    )
    report = _score(gold, _run(_row("a", "가나다라"), _row("b", "마바사")))
    ci = _ks(report)["M1"]["ci95"]
    assert ci["clusters"] == 2
    assert ci["seed"] == "tavonel-kb1-bootstrap-2026-10-17:KS"
    assert ci["low"] == 0 and ci["high"] == 0.25


def test_cli_writes_the_report(tmp_path: Path) -> None:
    gold_path = tmp_path / "SYNTHETIC-gold.json"
    run_path = tmp_path / "SYNTHETIC-run.json"
    out_path = tmp_path / "SYNTHETIC-report.json"
    gold_path.write_text(json.dumps(_gold(_gold_page("p1", "가나"))), encoding="utf-8")
    run_path.write_text(json.dumps(_run(_row("p1", "가나"))), encoding="utf-8")
    argv = ["--gold", str(gold_path), "--run", str(run_path), "--out", str(out_path)]
    assert harness.main(argv) == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["schema"] == "tavonel.kb1.report.v1"
    assert report["inputs"]["gold_sha256"].startswith("sha256:")
