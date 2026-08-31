from __future__ import annotations

import hashlib
import html
import json
import re
import statistics
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL_PATH = EXPERIMENT / "protocol.json"
RECEIPTS = EXPERIMENT / "receipts"
RESULT_PATH = RECEIPTS / "development-calibration-result.json"
REPORT_PATH = EXPERIMENT / "DEVELOPMENT_CALIBRATION_REPORT.md"
CIR = ROOT / "packages" / "cir-python" / "src"
sys.path.insert(0, str(CIR))

from akc_cir.semantic_risk import SemanticRiskFeatures, assess_semantic_risk  # noqa: E402

SEMANTIC_CATEGORIES = {
    "title",
    "text_block",
    "table_caption",
    "table",
    "equation_isolated",
    "equation_caption",
    "page_footnote",
    "figure_caption",
    "table_footnote",
    "figure_footnote",
}

TOKEN_RE = re.compile(r"\w+(?:[.\-]\w+)*|[^\w\s]", re.UNICODE)
DATE_RE = re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b")
VERSION_RE = re.compile(r"\b[vV]?\d+(?:\.\d+){2,}\b")
CURRENCY_RE = re.compile(r"(?:[$€£¥₩]\s*[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)")
PERCENT_RE = re.compile(r"(?<!\w)[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*%")
DECIMAL_RE = re.compile(r"(?<![\w.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d+(?!\w)")
SIGNED_INT_RE = re.compile(r"(?<!\w)[+-]\d+(?![\w.])")
MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
HTML_TAG_RE = re.compile(r"<[^>]+>")
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
DISPLAY_MATH_RE = re.compile(r"\$\$(.*?)\$\$|\\\[(.*?)\\\]|\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}", re.DOTALL)
INLINE_MATH_RE = re.compile(r"(?<!\$)\$([^$\n]+)\$(?!\$)|\\\((.*?)\\\)", re.DOTALL)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def strip_html(value: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(value or "")
    return " ".join(parser.parts)


def normalize_space(value: str) -> str:
    return " ".join(html.unescape(value).casefold().split())


def markdown_to_plain(value: str) -> str:
    value = CODE_FENCE_RE.sub(" ", value)
    value = MD_LINK_RE.sub(lambda match: match.group(1), value)
    value = HTML_TAG_RE.sub(" ", value)
    value = re.sub(r"(^|\s)[#>*_`~]+", " ", value)
    value = re.sub(r"\|(?:\s*:?-+:?\s*\|)+", " ", value)
    return normalize_space(value)


def content_tokens(value: str) -> tuple[str, ...]:
    return tuple(TOKEN_RE.findall(normalize_space(value)))


def sequence_error(expected: str, actual: str) -> float:
    a = content_tokens(expected)
    b = content_tokens(actual)
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    return 1.0 - SequenceMatcher(None, a, b, autojunk=False).ratio()


def multiset_recall_error(expected: str, actual: str) -> float:
    a = Counter(content_tokens(expected))
    if not a:
        return 0.0
    b = Counter(content_tokens(actual))
    matched = sum(min(count, b[token]) for token, count in a.items())
    return 1.0 - matched / sum(a.values())


def extract_critical_tokens(value: str) -> tuple[str, ...]:
    found: set[str] = set()
    occupied: list[tuple[int, int]] = []
    for regex in (DATE_RE, VERSION_RE, CURRENCY_RE, PERCENT_RE, DECIMAL_RE, SIGNED_INT_RE):
        for match in regex.finditer(value):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            token = normalize_space(match.group(0)).replace(" ", "")
            if token:
                found.add(token)
                occupied.append((match.start(), match.end()))
    return tuple(sorted(found))


def critical_token_error(expected: str, actual: str) -> float:
    expected_tokens = set(extract_critical_tokens(expected))
    if not expected_tokens:
        return 0.0
    actual_tokens = set(extract_critical_tokens(actual))
    return 1.0 - len(expected_tokens & actual_tokens) / len(expected_tokens)


def set_instability(values: Iterable[tuple[str, ...]]) -> float:
    sets = [set(value) for value in values]
    union = set().union(*sets) if sets else set()
    if not union:
        return 0.0
    intersection = set.intersection(*sets) if sets else set()
    return 1.0 - len(intersection) / len(union)


def pairwise_sequence_instability(values: tuple[str, str, str]) -> float:
    return statistics.fmean(
        (
            sequence_error(values[0], values[1]),
            sequence_error(values[0], values[2]),
            sequence_error(values[1], values[2]),
        )
    )


def extract_formula_text(markdown: str) -> str:
    parts: list[str] = []
    for match in DISPLAY_MATH_RE.finditer(markdown):
        parts.append(next((group for group in match.groups() if group is not None), ""))
    for match in INLINE_MATH_RE.finditer(markdown):
        parts.append(next((group for group in match.groups() if group is not None), ""))
    return normalize_space(" ".join(parts))


def primary_structural_criticality(markdown: str) -> tuple[float, dict[str, bool]]:
    lines = markdown.splitlines()
    table_detected = "<table" in markdown.casefold() or any(
        line.count("|") >= 2 for line in lines
    )
    formula_detected = bool(DISPLAY_MATH_RE.search(markdown) or INLINE_MATH_RE.search(markdown))
    headings = sum(1 for line in lines if line.lstrip().startswith("#"))
    lists = sum(1 for line in lines if re.match(r"\s*(?:[-*+] |\d+[.)] )", line))
    layout_complex = headings + lists >= 4
    values = []
    if table_detected:
        values.append(0.85)
    if formula_detected:
        values.append(0.65)
    if layout_complex:
        values.append(0.30)
    if not values:
        values.append(0.10)
    remainder = 1.0
    for value in values:
        remainder *= 1.0 - value
    return 1.0 - remainder, {
        "table_detected": table_detected,
        "formula_detected": formula_detected,
        "layout_complex": layout_complex,
    }


def _det_text(item: dict[str, Any]) -> str:
    category = str(item.get("category_type", ""))
    if category == "table":
        return strip_html(str(item.get("html") or ""))
    if category == "equation_isolated":
        return str(item.get("latex") or item.get("text") or "")
    return str(item.get("text") or item.get("latex") or "")


def gt_page_view(item: dict[str, Any]) -> dict[str, Any]:
    dets = [
        det
        for det in item.get("layout_dets", [])
        if str(det.get("category_type", "")) in SEMANTIC_CATEGORIES and not det.get("ignore")
    ]
    ordered = sorted(
        enumerate(dets),
        key=lambda pair: (
            pair[1].get("order") is None,
            pair[1].get("order") if isinstance(pair[1].get("order"), int) else 10**9,
            pair[0],
        ),
    )
    semantic_chunks = [_det_text(det) for _, det in ordered if _det_text(det).strip()]
    tables = [strip_html(str(det.get("html") or "")) for det in dets if det.get("category_type") == "table"]
    formulas = [str(det.get("latex") or "") for det in dets if det.get("category_type") == "equation_isolated"]
    image_path = Path(str(item["page_info"]["image_path"]))
    return {
        "page_key": image_path.stem,
        "semantic_text": normalize_space("\n".join(semantic_chunks)),
        "ordered_text": normalize_space("\n".join(semantic_chunks)),
        "table_text": normalize_space("\n".join(tables)),
        "formula_text": normalize_space("\n".join(formulas)),
        "has_table": bool(tables),
        "has_formula": bool(formulas),
    }


def page_damage(gt: dict[str, Any], prediction_markdown: str) -> dict[str, float | int]:
    plain = markdown_to_plain(prediction_markdown)
    content_error = sequence_error(gt["semantic_text"], plain)
    ordered_error = sequence_error(gt["ordered_text"], plain)
    critical_error = critical_token_error(gt["semantic_text"], plain)
    table_error = multiset_recall_error(gt["table_text"], plain) if gt["has_table"] else 0.0
    predicted_formula = extract_formula_text(prediction_markdown)
    formula_error = sequence_error(gt["formula_text"], predicted_formula) if gt["has_formula"] else 0.0
    components: list[tuple[float, float]] = [
        (0.30, content_error),
        (0.20, ordered_error),
    ]
    critical_count = len(extract_critical_tokens(gt["semantic_text"]))
    if critical_count:
        components.append((0.30, critical_error))
    if gt["has_table"]:
        components.append((0.35, table_error))
    if gt["has_formula"]:
        components.append((0.25, formula_error))
    weight_total = sum(weight for weight, _ in components)
    damage = sum(weight * value for weight, value in components) / weight_total
    return {
        "damage": min(1.0, max(0.0, damage)),
        "content_sequence_error": content_error,
        "ordered_content_error": ordered_error,
        "critical_token_error": critical_error,
        "critical_token_count": critical_count,
        "table_semantic_error": table_error,
        "formula_semantic_error": formula_error,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def manifest_entry(path: Path) -> dict[str, Any]:
    return {"path": path.as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)}


def locate_inputs(protocol: dict[str, Any]) -> dict[str, Any]:
    inputs = protocol["inputs"]
    gt = Path(inputs["ground_truth"])
    evidence_root = Path(inputs["evidence_root"])
    if not gt.is_file() or not evidence_root.is_dir():
        raise RuntimeError("required preserved development evidence is missing")
    paddle_dirs = [
        item
        for item in evidence_root.glob(str(inputs["primary_family_prefix"]) + "*")
        if item.is_dir() and (item / "markdown-repeat-1").is_dir()
    ]
    mineru_dirs = [
        item / str(inputs["strong_subdir"])
        for item in evidence_root.glob(str(inputs["strong_family_prefix"]) + "*")
        if item.is_dir() and (item / str(inputs["strong_subdir"])).is_dir()
    ]
    if len(paddle_dirs) != 1 or len(mineru_dirs) != 1:
        raise RuntimeError(f"expected one primary and one strong evidence directory, got {len(paddle_dirs)} / {len(mineru_dirs)}")
    return {"gt": gt, "paddle": paddle_dirs[0], "mineru": mineru_dirs[0]}


def _markdown_map(model_dir: Path, repeat: int) -> dict[str, Path]:
    directory = model_dir / f"markdown-repeat-{repeat}"
    return {path.stem: path for path in directory.glob("*.md")}


def verify_page_alignment(gt_items: list[dict[str, Any]], paddle: Path, mineru: Path, required_pages: int) -> tuple[str, ...]:
    gt_keys = tuple(sorted(gt_page_view(item)["page_key"] for item in gt_items))
    if len(gt_keys) != required_pages or len(set(gt_keys)) != required_pages:
        raise RuntimeError("ground-truth page set is not the required unique 18-page cohort")
    expected = set(gt_keys)
    for model_name, directory in (("primary", paddle), ("strong", mineru)):
        for repeat in (1, 2, 3):
            actual = set(_markdown_map(directory, repeat))
            if actual != expected:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                raise RuntimeError(f"{model_name} repeat {repeat} page mismatch; missing={missing}, extra={extra}")
    return gt_keys


def build_input_manifest(located: dict[str, Any]) -> list[dict[str, Any]]:
    paths: list[Path] = [located["gt"], CIR / "akc_cir" / "semantic_risk.py"]
    for model in (located["paddle"], located["mineru"]):
        for repeat in (1, 2, 3):
            paths.extend(sorted((model / f"markdown-repeat-{repeat}").glob("*.md")))
            metric = model / "official-partial-evaluation" / f"repeat-{repeat}" / "metric-result.json"
            if metric.is_file():
                paths.append(metric)
        summary = model / "run-summary.json"
        if summary.is_file():
            paths.append(summary)
    unique = sorted(set(paths), key=lambda path: path.as_posix())
    return [manifest_entry(path) for path in unique]


def routing_observables(primary: tuple[str, str, str], strong: tuple[str, str, str]) -> dict[str, Any]:
    """Build routing signals from parser outputs only; ground truth is forbidden here."""
    instability = pairwise_sequence_instability(primary)
    critical_instability = set_instability(
        tuple(extract_critical_tokens(markdown_to_plain(value)) for value in primary)
    )
    structural_criticality, structure_flags = primary_structural_criticality(primary[0])
    strong_disagreement_proxy = statistics.fmean(
        sequence_error(primary[index], strong[index]) for index in range(3)
    )
    features = SemanticRiskFeatures(
        parser_error_probability=instability,
        parsing_uncertainty=instability,
        cross_model_disagreement=0.0,
        critical_token_sensitivity=critical_instability,
        semantic_role_criticality=structural_criticality,
        entity_criticality=0.0,
        temporal_significance=0.0,
        authority_significance=0.0,
        dependency_blast_radius=0.0,
        downstream_consumer_risk=0.0,
    )
    risk = assess_semantic_risk(features)
    risk_with_strong_proxy = assess_semantic_risk(
        SemanticRiskFeatures(
            parser_error_probability=instability,
            parsing_uncertainty=instability,
            cross_model_disagreement=strong_disagreement_proxy,
            critical_token_sensitivity=critical_instability,
            semantic_role_criticality=structural_criticality,
        )
    )
    return {
        "primary_repeat_instability": instability,
        "primary_critical_token_repeat_instability": critical_instability,
        "primary_detected_structural_criticality": structural_criticality,
        "primary_structure_flags": structure_flags,
        "strong_disagreement_proxy": strong_disagreement_proxy,
        "current_semantic_risk": risk.expected_semantic_damage,
        "current_semantic_risk_band": risk.band.value,
        "current_semantic_risk_dominant_signals": list(risk.dominant_signals),
        "semantic_risk_with_strong_disagreement_counterfactual": risk_with_strong_proxy.expected_semantic_damage,
    }


def page_records(protocol: dict[str, Any], located: dict[str, Any]) -> list[dict[str, Any]]:
    gt_items = json.loads(located["gt"].read_text(encoding="utf-8"))
    page_keys = verify_page_alignment(
        gt_items,
        located["paddle"],
        located["mineru"],
        int(protocol["inputs"]["required_pages"]),
    )
    gt_by_key = {gt_page_view(item)["page_key"]: gt_page_view(item) for item in gt_items}
    paddle_maps = [_markdown_map(located["paddle"], repeat) for repeat in (1, 2, 3)]
    mineru_maps = [_markdown_map(located["mineru"], repeat) for repeat in (1, 2, 3)]
    records: list[dict[str, Any]] = []
    for key in page_keys:
        gt = gt_by_key[key]
        primary = tuple(mapping[key].read_text(encoding="utf-8") for mapping in paddle_maps)
        strong = tuple(mapping[key].read_text(encoding="utf-8") for mapping in mineru_maps)
        primary_damage_parts = [page_damage(gt, output) for output in primary]
        strong_damage_parts = [page_damage(gt, output) for output in strong]
        primary_damage = statistics.fmean(float(item["damage"]) for item in primary_damage_parts)
        strong_damage = statistics.fmean(float(item["damage"]) for item in strong_damage_parts)
        primary_critical = statistics.fmean(float(item["critical_token_error"]) for item in primary_damage_parts)
        strong_critical = statistics.fmean(float(item["critical_token_error"]) for item in strong_damage_parts)
        observables = routing_observables(primary, strong)
        records.append(
            {
                "page_key": key,
                "gt_has_table": gt["has_table"],
                "gt_has_formula": gt["has_formula"],
                "gt_critical_token_count": len(extract_critical_tokens(gt["semantic_text"])),
                "primary_damage": primary_damage,
                "strong_damage": strong_damage,
                "strong_parser_benefit": primary_damage - strong_damage,
                "primary_critical_token_damage": primary_critical,
                "strong_critical_token_damage": strong_critical,
                **observables,
                "primary_damage_components_mean": {
                    name: statistics.fmean(float(item[name]) for item in primary_damage_parts)
                    for name in (
                        "content_sequence_error",
                        "ordered_content_error",
                        "critical_token_error",
                        "table_semantic_error",
                        "formula_semantic_error",
                    )
                },
                "strong_damage_components_mean": {
                    name: statistics.fmean(float(item[name]) for item in strong_damage_parts)
                    for name in (
                        "content_sequence_error",
                        "ordered_content_error",
                        "critical_token_error",
                        "table_semantic_error",
                        "formula_semantic_error",
                    )
                },
            }
        )
    return records


def _policy_row(
    name: str,
    records: list[dict[str, Any]],
    select_strong: list[bool],
    economics: dict[str, float],
    *,
    observation_requires_strong_all_pages: bool = False,
) -> dict[str, Any]:
    page_count = len(records)
    escalations = sum(select_strong)
    selected_damage = [
        float(record["strong_damage"] if strong else record["primary_damage"])
        for record, strong in zip(records, select_strong, strict=True)
    ]
    critical_pages = [
        (record, strong)
        for record, strong in zip(records, select_strong, strict=True)
        if int(record["gt_critical_token_count"]) > 0
    ]
    selected_critical = [
        float(record["strong_critical_token_damage"] if strong else record["primary_critical_token_damage"])
        for record, strong in critical_pages
    ]
    primary_mean = statistics.fmean(float(record["primary_damage"]) for record in records)
    oracle_mean = statistics.fmean(min(float(record["primary_damage"]), float(record["strong_damage"])) for record in records)
    primary_cost = economics["primary_cost_usd_per_page"] * page_count
    primary_latency = economics["primary_latency_seconds_per_page"] * page_count
    if name == "always_primary":
        cost = primary_cost
        latency = primary_latency
    elif name == "always_strong":
        cost = economics["strong_cost_usd_per_page"] * page_count
        latency = economics["strong_latency_seconds_per_page"] * page_count
    elif observation_requires_strong_all_pages:
        cost = primary_cost + economics["strong_cost_usd_per_page"] * page_count
        latency = primary_latency + economics["strong_latency_seconds_per_page"] * page_count
    else:
        cost = primary_cost + economics["strong_cost_usd_per_page"] * escalations
        latency = primary_latency + economics["strong_latency_seconds_per_page"] * escalations
    mean_damage = statistics.fmean(selected_damage)
    return {
        "policy": name,
        "page_count": page_count,
        "escalated_pages": escalations,
        "escalation_ratio": escalations / page_count,
        "mean_selected_parser_damage": mean_damage,
        "critical_token_pages": len(critical_pages),
        "mean_critical_token_damage_on_critical_pages": statistics.fmean(selected_critical) if selected_critical else 0.0,
        "estimated_parser_cost_usd": cost,
        "estimated_parser_latency_seconds_sequential": latency,
        "damage_reduction_vs_always_primary": primary_mean - mean_damage,
        "extra_cost_vs_always_primary": cost - primary_cost,
        "extra_latency_vs_always_primary": latency - primary_latency,
        "regret_vs_page_oracle": mean_damage - oracle_mean,
        "observation_requires_strong_all_pages": observation_requires_strong_all_pages,
    }


def evaluate_policies(protocol: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    economics = {key: float(value) for key, value in protocol["measured_role_economics"].items()}
    rows: list[dict[str, Any]] = []
    rows.append(_policy_row("always_primary", records, [False] * len(records), economics))
    rows.append(_policy_row("always_strong", records, [True] * len(records), economics))
    for threshold in protocol["predeclared_thresholds"]["semantic_risk"]:
        selected = [float(record["current_semantic_risk"]) >= float(threshold) for record in records]
        row = _policy_row(f"semantic_risk>={threshold}", records, selected, economics)
        row["threshold"] = float(threshold)
        row["signal"] = "current_semantic_risk"
        rows.append(row)
    for threshold in protocol["predeclared_thresholds"]["strong_disagreement_proxy"]:
        selected = [float(record["strong_disagreement_proxy"]) >= float(threshold) for record in records]
        row = _policy_row(
            f"strong_disagreement_proxy>={threshold}",
            records,
            selected,
            economics,
            observation_requires_strong_all_pages=True,
        )
        row["threshold"] = float(threshold)
        row["signal"] = "strong_disagreement_proxy"
        row["counterfactual_cost_if_same_signal_were_available_from_negligible_cost_peer_usd"] = (
            economics["primary_cost_usd_per_page"] * len(records)
            + economics["strong_cost_usd_per_page"] * sum(selected)
        )
        rows.append(row)
    return rows


def official_aggregate_snapshot(located: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, model in (("primary", located["paddle"]), ("strong", located["mineru"])):
        repeats = []
        for repeat in (1, 2, 3):
            path = model / "official-partial-evaluation" / f"repeat-{repeat}" / "metric-result.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            repeats.append(
                {
                    "text_edit": payload["text_block"]["all"]["Edit_dist"]["ALL_page_avg"],
                    "formula_edit": payload["display_formula"]["all"]["Edit_dist"]["ALL_page_avg"],
                    "table_teds": payload["table"]["all"]["TEDS"]["all"],
                    "table_structure_teds": payload["table"]["all"]["TEDS_structure_only"]["all"],
                    "table_edit": payload["table"]["all"]["Edit_dist"]["ALL_page_avg"],
                    "reading_order_edit": payload["reading_order"]["all"]["Edit_dist"]["ALL_page_avg"],
                }
            )
        result[label] = {
            key: statistics.fmean(float(repeat[key]) for repeat in repeats)
            for key in repeats[0]
        }
    return result


def _candidate_region(rows: list[dict[str, Any]]) -> dict[str, Any]:
    semantic = [row for row in rows if row.get("signal") == "current_semantic_risk"]
    beneficial = [
        row
        for row in semantic
        if float(row["damage_reduction_vs_always_primary"]) > 0.0
        and float(row["estimated_parser_cost_usd"]) < next(
            float(candidate["estimated_parser_cost_usd"])
            for candidate in rows
            if candidate["policy"] == "always_strong"
        )
    ]
    return {
        "semantic_risk_thresholds_with_positive_damage_reduction_and_cost_below_always_strong": [
            float(row["threshold"]) for row in beneficial
        ],
        "production_threshold_selected": False,
    }


def make_report(receipt: dict[str, Any]) -> str:
    rows = receipt["policy_results"]
    primary = next(row for row in rows if row["policy"] == "always_primary")
    strong = next(row for row in rows if row["policy"] == "always_strong")
    default = next(row for row in rows if row["policy"] == "semantic_risk>=0.55")
    diagnostics = receipt["development_diagnostics"]
    lines = [
        "# Semantic Risk Development Calibration — SEM-RISK-DEV-CAL-01",
        "",
        "**Classification:** retrospective development calibration only. This is not a production threshold study or fresh confirmatory evidence.",
        "",
        "## What was reused",
        "",
        "The study reuses the already-spent 18-page × 3-repeat OmniDocBench demo evidence for PaddleOCR-VL 1.6 FastDeploy and MinerU 3.4.4 VLM, plus the exact local OmniDocBench demo ground truth. No OCR/VLM inference, network access, or GPU spend was performed.",
        "",
        "## Important metric separation",
        "",
        "`official_aggregate_snapshot` in the machine receipt is read directly from the preserved official OmniDocBench evaluator outputs. The page-level `damage` used below is a TAVONEL custom development metric and MUST NOT be described as an official OmniDocBench score.",
        "",
        "## Development result",
        "",
        f"Always-primary mean custom damage: **{primary['mean_selected_parser_damage']:.4f}** at ${primary['estimated_parser_cost_usd']:.5f} simulated parser cost for the 18 pages.",
        f"Always-strong mean custom damage: **{strong['mean_selected_parser_damage']:.4f}** at ${strong['estimated_parser_cost_usd']:.5f}.",
        f"Current Semantic Risk at threshold 0.55 escalated **{default['escalated_pages']}/18** pages and produced mean damage **{default['mean_selected_parser_damage']:.4f}**.",
        f"The current risk score range was only **{diagnostics['current_semantic_risk_min']:.6f}–{diagnostics['current_semantic_risk_max']:.6f}**. Because the predeclared grid starts at 0.25, every current-engine threshold route collapsed to always-primary on this cohort.",
        f"Yet the page oracle shows non-trivial selective opportunity: MinerU had lower custom damage on **{diagnostics['strong_better_pages']}** pages, higher damage on **{diagnostics['strong_worse_pages']}**, and tied on **{diagnostics['equal_damage_pages']}**. Oracle mean damage is **{diagnostics['page_oracle_mean_damage']:.4f}**, versus **{diagnostics['always_primary_mean_damage']:.4f}** for always-primary.",
        "",
        "### Predeclared policy grid",
        "",
        "| Policy | Escalation | Mean damage | Damage Δ vs primary | Cost USD | Regret vs oracle |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['policy']} | {100*row['escalation_ratio']:.1f}% | {row['mean_selected_parser_damage']:.4f} | {row['damage_reduction_vs_always_primary']:+.4f} | {row['estimated_parser_cost_usd']:.5f} | {row['regret_vs_page_oracle']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The current engine was intentionally evaluated *as sealed*, with unavailable production dimensions set to zero rather than inferred from ground truth. In this historical cohort we do not have the cheap source-native peer disagreement, downstream dependency blast radius, authority/temporal role, or consumer-risk annotations that the full TAVONEL design expects. Primary repeat instability is used only as a development proxy for parser uncertainty; producing three repeats is not assumed to be a free production feature.",
            "",
            "**Development diagnosis:** the current score is under-sensitive under the *available feature proxies*, not proven globally under-sensitive. The maximum score stayed below 0.01 even though the lower-damage parser varies by page. This is evidence that the next experiment must supply/measure the missing independent error signal and semantic consequence dimensions; it is not a justification to simply lower the production threshold after seeing these 18 pages.",
            "",
            "Paddle-vs-MinerU disagreement is reported as a counterfactual signal, but it is not cost-free routing evidence here: observing it already requires the strong parser on all pages. The receipt therefore charges the operational observation cost accordingly and separately reports the counterfactual cost if an equivalent signal later comes from a negligible-cost independent peer.",
            "",
            "No production threshold is selected from 18 already-observed pages. The next confirmatory study must freeze a new heterogeneous corpus before parser outputs are opened, include a cheap independent peer or model-native uncertainty signal, label downstream semantic roles and dependency impact, and evaluate date/quantity/table/authority preservation together with cost/latency.",
            "",
            "## Candidate region only",
            "",
            f"Predeclared Semantic Risk thresholds that reduced this custom development damage while remaining cheaper than always-strong: **{receipt['candidate_region']['semantic_risk_thresholds_with_positive_damage_reduction_and_cost_below_always_strong']}**. This is a calibration region, not a chosen product threshold.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    located = locate_inputs(protocol)
    gt_items = json.loads(located["gt"].read_text(encoding="utf-8"))
    verify_page_alignment(
        gt_items,
        located["paddle"],
        located["mineru"],
        int(protocol["inputs"]["required_pages"]),
    )
    records = page_records(protocol, located)
    policies = evaluate_policies(protocol, records)
    primary_row = next(row for row in policies if row["policy"] == "always_primary")
    oracle_mean = statistics.fmean(
        min(float(record["primary_damage"]), float(record["strong_damage"])) for record in records
    )
    strong_better = sum(float(record["strong_parser_benefit"]) > 1e-12 for record in records)
    strong_worse = sum(float(record["strong_parser_benefit"]) < -1e-12 for record in records)
    equal_damage = len(records) - strong_better - strong_worse
    diagnostics = {
        "current_semantic_risk_min": min(float(record["current_semantic_risk"]) for record in records),
        "current_semantic_risk_max": max(float(record["current_semantic_risk"]) for record in records),
        "strong_better_pages": strong_better,
        "strong_worse_pages": strong_worse,
        "equal_damage_pages": equal_damage,
        "critical_token_pages": sum(int(record["gt_critical_token_count"]) > 0 for record in records),
        "table_pages": sum(bool(record["gt_has_table"]) for record in records),
        "formula_pages": sum(bool(record["gt_has_formula"]) for record in records),
        "always_primary_mean_damage": float(primary_row["mean_selected_parser_damage"]),
        "page_oracle_mean_damage": oracle_mean,
        "oracle_damage_reduction_vs_always_primary": float(primary_row["mean_selected_parser_damage"]) - oracle_mean,
        "default_threshold_0_55_assessment": "UNDER_SENSITIVE_UNDER_AVAILABLE_DEVELOPMENT_FEATURE_PROXIES",
    }
    receipt: dict[str, Any] = {
        "schema": "tavonel.semantic-risk.development-calibration.result.v1",
        "experiment_id": protocol["experiment_id"],
        "classification": protocol["classification"],
        "claim_boundary": protocol["claim_boundary"],
        "external_gpu_cost_usd": 0.0,
        "new_inference_performed": False,
        "page_count": len(records),
        "input_manifest": build_input_manifest(located),
        "official_aggregate_snapshot": official_aggregate_snapshot(located),
        "custom_metric_is_official_omnidocbench": False,
        "page_records": records,
        "policy_results": policies,
        "candidate_region": _candidate_region(policies),
        "development_diagnostics": diagnostics,
        "limitations": [
            "18-page demo cohort was already observed before this calibration study.",
            "Custom page damage is deterministic TAVONEL development instrumentation, not an official OmniDocBench metric.",
            "Primary repeat instability is a development proxy and would require replacement by a deployment-available uncertainty signal.",
            "Paddle-vs-MinerU disagreement already incurs strong-parser observation cost on this cohort.",
            "Entity, temporal, authority, dependency-blast-radius, and downstream-consumer risk dimensions are unavailable and therefore zero, not inferred from ground truth.",
            "No production threshold or field SLO is established.",
        ],
    }
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(make_report(receipt), encoding="utf-8")
    return receipt


def main() -> int:
    receipt = run()
    summary = {
        "classification": receipt["classification"],
        "page_count": receipt["page_count"],
        "gpu": receipt["external_gpu_cost_usd"],
        "candidate_region": receipt["candidate_region"],
        "policy_results": [
            {
                "policy": row["policy"],
                "escalation_ratio": row["escalation_ratio"],
                "mean_damage": row["mean_selected_parser_damage"],
                "damage_reduction_vs_primary": row["damage_reduction_vs_always_primary"],
                "cost_usd": row["estimated_parser_cost_usd"],
                "regret_vs_oracle": row["regret_vs_page_oracle"],
            }
            for row in receipt["policy_results"]
        ],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
