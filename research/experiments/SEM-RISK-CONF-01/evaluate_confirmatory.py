from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import random
import re
import statistics
import sys
import urllib.parse
import urllib.request
from collections import Counter
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL_PATH = EXPERIMENT / "protocol.json"
FREEZE_PATH = EXPERIMENT / "receipts" / "protocol-freeze.json"
SELECTION_PATH = EXPERIMENT / "selection-manifest.json"
SELECTION_SEAL = EXPERIMENT / "receipts" / "selection-seal.json"
ACQUISITION = EXPERIMENT / "receipts" / "acquisition-receipt.json"
NATIVE_DIR = EXPERIMENT / "outputs" / "lane-a-native"
INFERENCE_SEAL = EXPERIMENT / "receipts" / "inference-output-seal.json"
RESULT = EXPERIMENT / "receipts" / "confirmatory-result.json"
REPORT = EXPERIMENT / "CONFIRMATORY_REPORT.md"
DATASET_ID = "opendatalab/OmniDocBench"

for source_root in (
    ROOT / "packages" / "cir-python" / "src",
    ROOT / "packages" / "quality" / "src",
):
    sys.path.insert(0, str(source_root))

from akc_quality.semantic_signals import derive_peer_semantic_risk  # noqa: E402

SEMANTIC_CATEGORIES = {
    "title", "text_block", "table_caption", "table", "equation_isolated",
    "equation_caption", "page_footnote", "figure_caption", "table_footnote", "figure_footnote",
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


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
    a, b = content_tokens(expected), content_tokens(actual)
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


def pairwise_instability(values: tuple[str, str, str]) -> float:
    return statistics.fmean((
        sequence_error(values[0], values[1]),
        sequence_error(values[0], values[2]),
        sequence_error(values[1], values[2]),
    ))


def extract_formula_text(markdown: str) -> str:
    parts: list[str] = []
    for match in DISPLAY_MATH_RE.finditer(markdown):
        parts.append(next((group for group in match.groups() if group is not None), ""))
    for match in INLINE_MATH_RE.finditer(markdown):
        parts.append(next((group for group in match.groups() if group is not None), ""))
    return normalize_space(" ".join(parts))


def structural_flags(markdown: str) -> dict[str, bool]:
    lines = markdown.splitlines()
    table_detected = "<table" in markdown.casefold() or any(line.count("|") >= 2 for line in lines)
    formula_detected = bool(DISPLAY_MATH_RE.search(markdown) or INLINE_MATH_RE.search(markdown))
    headings = sum(1 for line in lines if line.lstrip().startswith("#"))
    lists = sum(1 for line in lines if re.match(r"\s*(?:[-*+] |\d+[.)] )", line))
    layout_complex = headings + lists >= 4
    return {
        "table_detected": table_detected,
        "formula_detected": formula_detected,
        "layout_complex": layout_complex,
    }


def structural_criticality(flags: dict[str, bool]) -> float:
    values: list[float] = []
    if flags["table_detected"]:
        values.append(0.85)
    if flags["formula_detected"]:
        values.append(0.65)
    if flags["layout_complex"]:
        values.append(0.30)
    if not values:
        return 0.10
    remainder = 1.0
    for value in values:
        remainder *= 1.0 - value
    return 1.0 - remainder


def specialist_eligible(flags: dict[str, bool]) -> bool:
    structural = flags["table_detected"] or flags["layout_complex"]
    formula_only = flags["formula_detected"] and not structural
    return structural and not formula_only


def _det_text(item: dict[str, Any]) -> str:
    category = str(item.get("category_type", ""))
    if category == "table":
        return strip_html(str(item.get("html") or ""))
    if category == "equation_isolated":
        return str(item.get("latex") or item.get("text") or "")
    return str(item.get("text") or item.get("latex") or "")


def gt_page_view(item: dict[str, Any]) -> dict[str, Any]:
    dets = [
        det for det in item.get("layout_dets", [])
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
    chunks = [_det_text(det) for _, det in ordered if _det_text(det).strip()]
    tables = [strip_html(str(det.get("html") or "")) for det in dets if det.get("category_type") == "table"]
    formulas = [str(det.get("latex") or "") for det in dets if det.get("category_type") == "equation_isolated"]
    image_path = Path(str(item["page_info"]["image_path"]))
    return {
        "page_key": image_path.stem,
        "semantic_text": normalize_space("\n".join(chunks)),
        "ordered_text": normalize_space("\n".join(chunks)),
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
    formula_error = sequence_error(gt["formula_text"], extract_formula_text(prediction_markdown)) if gt["has_formula"] else 0.0
    components: list[tuple[float, float]] = [(0.30, content_error), (0.20, ordered_error)]
    critical_count = len(extract_critical_tokens(gt["semantic_text"]))
    if critical_count:
        components.append((0.30, critical_error))
    if gt["has_table"]:
        components.append((0.35, table_error))
    if gt["has_formula"]:
        components.append((0.25, formula_error))
    total = sum(weight for weight, _ in components)
    damage = sum(weight * value for weight, value in components) / total
    return {
        "damage": min(1.0, max(0.0, damage)),
        "content_sequence_error": content_error,
        "ordered_content_error": ordered_error,
        "critical_token_error": critical_error,
        "critical_token_count": critical_count,
        "table_semantic_error": table_error,
        "formula_semantic_error": formula_error,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paddle-lane-a", type=Path, required=True)
    parser.add_argument("--paddle-lane-b", type=Path, required=True)
    parser.add_argument("--specialist-lane-a", type=Path, required=True)
    parser.add_argument("--specialist-lane-b", type=Path, required=True)
    return parser.parse_args()


def output_manifest(root: Path, *, repeats: tuple[int, ...], expected: set[str]) -> dict[str, Any]:
    if not root.is_dir():
        raise RuntimeError(f"model output directory missing: {root}")
    files: list[dict[str, Any]] = []
    for repeat in repeats:
        directory = root / f"markdown-repeat-{repeat}"
        if not directory.is_dir():
            raise RuntimeError(f"markdown repeat missing: {directory}")
        mapping = {path.stem: path for path in directory.glob("*.md")}
        if set(mapping) != expected:
            raise RuntimeError(f"output page mismatch for {directory}")
        for key in sorted(mapping):
            path = mapping[key]
            files.append({"case_id": key, "repeat": repeat, "path": str(path.resolve()), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    summary = root / "run-summary.json"
    if not summary.is_file():
        raise RuntimeError(f"run summary missing: {root}")
    summary_payload = json.loads(summary.read_text(encoding="utf-8"))
    if summary_payload.get("ground_truth_mounted") is not False:
        raise RuntimeError(f"ground truth isolation failed for {root}")
    files.append({"kind": "run_summary", "path": str(summary.resolve()), "sha256": sha256_file(summary), "bytes": summary.stat().st_size})
    return {"root": str(root.resolve()), "files": files}


def native_map(expected: set[str]) -> dict[str, str]:
    if not NATIVE_DIR.is_dir():
        raise RuntimeError("lane A native outputs missing")
    mapping: dict[str, str] = {}
    for key in sorted(expected):
        path = NATIVE_DIR / f"{key}.json"
        if not path.is_file():
            raise RuntimeError(f"native output missing: {key}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "completed":
            continue
        mapping[key] = str(payload.get("text") or "")
    return mapping


def fetch_gt(revision: str) -> list[dict[str, Any]]:
    revision_q = urllib.parse.quote(revision, safe="")
    url = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{revision_q}/OmniDocBench.json?download=true"
    request = urllib.request.Request(url, headers={"User-Agent": "tavonel-research-evaluator/1"})
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read()
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("ground-truth payload malformed")
    return payload


def markdown_map(root: Path, repeat: int) -> dict[str, str]:
    return {path.stem: path.read_text(encoding="utf-8") for path in (root / f"markdown-repeat-{repeat}").glob("*.md")}


def auroc(labels: list[bool], scores: list[float]) -> float | None:
    positives = [score for label, score in zip(labels, scores, strict=True) if label]
    negatives = [score for label, score in zip(labels, scores, strict=True) if not label]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            wins += 1.0 if positive > negative else (0.5 if positive == negative else 0.0)
    return wins / (len(positives) * len(negatives))


def average_precision(labels: list[bool], scores: list[float]) -> float | None:
    total_positive = sum(labels)
    if total_positive == 0:
        return None
    ranked = sorted(zip(scores, labels, strict=True), key=lambda pair: pair[0], reverse=True)
    hit = 0
    precisions: list[float] = []
    for rank_index, (_, label) in enumerate(ranked, 1):
        if label:
            hit += 1
            precisions.append(hit / rank_index)
    return sum(precisions) / total_positive


def bootstrap_ci(values: list[float], *, seed: int, resamples: int) -> dict[str, float | int]:
    if not values:
        return {"n": 0, "mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(resamples):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(statistics.fmean(sample))
    means.sort()
    lower = means[max(0, math.floor(0.025 * resamples))]
    upper = means[min(resamples - 1, math.ceil(0.975 * resamples) - 1)]
    return {"n": len(values), "mean": statistics.fmean(values), "ci95_low": lower, "ci95_high": upper}


def evaluate_lane(
    *,
    lane: str,
    keys: list[str],
    gt_by_key: dict[str, dict[str, Any]],
    primary_maps: tuple[dict[str, str], ...],
    specialist: dict[str, str],
    native: dict[str, str] | None,
    risk_threshold: float,
    peer_threshold: float,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for key in keys:
        gt = gt_by_key[key]
        primary_outputs = tuple(mapping[key] for mapping in primary_maps)
        primary = primary_outputs[0]
        specialist_output = specialist[key]
        primary_damage = page_damage(gt, primary)
        specialist_damage = page_damage(gt, specialist_output)
        flags = structural_flags(primary)
        eligible = specialist_eligible(flags)
        if lane == "a":
            peer_text = (native or {}).get(key)
            if peer_text is None:
                risk = derive_peer_semantic_risk(
                    primary,
                    None,
                    semantic_role_criticality=structural_criticality(flags),
                    downstream_consumer_risk=0.35,
                )
            else:
                risk = derive_peer_semantic_risk(
                    primary,
                    peer_text,
                    semantic_role_criticality=structural_criticality(flags),
                    downstream_consumer_risk=0.35,
                )
            cheap_peer_escalate = bool(peer_text) and risk.cross_model_disagreement >= peer_threshold and eligible
            risk_escalate = risk.assessment.expected_semantic_damage >= risk_threshold and eligible
            uncertainty = None
        else:
            if len(primary_outputs) != 3:
                raise RuntimeError("lane B requires exactly 3 primary repeats")
            pairwise = pairwise_instability(primary_outputs)  # type: ignore[arg-type]
            critical_instability = set_instability(
                tuple(extract_critical_tokens(markdown_to_plain(value)) for value in primary_outputs)
            )
            uncertainty = max(pairwise, critical_instability)
            risk = derive_peer_semantic_risk(
                primary,
                None,
                parsing_uncertainty=uncertainty,
                semantic_role_criticality=structural_criticality(flags),
                downstream_consumer_risk=0.35,
            )
            cheap_peer_escalate = False
            risk_escalate = risk.assessment.expected_semantic_damage >= risk_threshold and eligible

        primary_value = float(primary_damage["damage"])
        specialist_value = float(specialist_damage["damage"])
        critical_primary = float(primary_damage["critical_token_error"])
        critical_specialist = float(specialist_damage["critical_token_error"])
        material_benefit = eligible and (
            primary_value - specialist_value >= 0.05
            or critical_primary - critical_specialist >= 0.25
        )
        selected = specialist_damage if risk_escalate else primary_damage
        false_safe = material_benefit and not risk_escalate
        false_escalation = risk_escalate and specialist_value - primary_value > 0.02
        records.append({
            "page_key": key,
            "gt_has_table": gt["has_table"],
            "gt_has_formula": gt["has_formula"],
            "gt_critical_token_count": len(extract_critical_tokens(gt["semantic_text"])),
            "structure_flags": flags,
            "specialist_eligible": eligible,
            "primary_damage": primary_damage,
            "specialist_damage": specialist_damage,
            "risk": risk.as_dict(),
            "repeat_instability": uncertainty,
            "cheap_peer_escalate": cheap_peer_escalate,
            "semantic_risk_escalate": risk_escalate,
            "selected_damage": selected,
            "material_specialist_benefit": material_benefit,
            "false_safe": false_safe,
            "false_escalation": false_escalation,
        })

    def mean_component(which: str, component: str) -> float:
        values = [float(record[which][component]) for record in records]
        return statistics.fmean(values) if values else 0.0

    result: dict[str, Any] = {
        "lane": lane,
        "page_count": len(records),
        "primary_mean_damage": mean_component("primary_damage", "damage"),
        "always_specialist_mean_damage": mean_component("specialist_damage", "damage"),
        "semantic_risk_mean_damage": mean_component("selected_damage", "damage"),
        "primary_mean_critical_token_error": mean_component("primary_damage", "critical_token_error"),
        "semantic_risk_mean_critical_token_error": mean_component("selected_damage", "critical_token_error"),
        "primary_mean_table_error": mean_component("primary_damage", "table_semantic_error"),
        "semantic_risk_mean_table_error": mean_component("selected_damage", "table_semantic_error"),
        "primary_mean_formula_error": mean_component("primary_damage", "formula_semantic_error"),
        "semantic_risk_mean_formula_error": mean_component("selected_damage", "formula_semantic_error"),
        "semantic_risk_escalation_rate": sum(record["semantic_risk_escalate"] for record in records) / len(records),
        "false_safe_rate": sum(record["false_safe"] for record in records) / len(records),
        "false_escalation_rate": sum(record["false_escalation"] for record in records) / len(records),
        "material_specialist_benefit_rate": sum(record["material_specialist_benefit"] for record in records) / len(records),
        "damage_reduction_bootstrap": bootstrap_ci(
            [float(record["primary_damage"]["damage"]) - float(record["selected_damage"]["damage"]) for record in records],
            seed=260831,
            resamples=10000,
        ),
        "records": records,
    }
    if lane == "a":
        labels = [
            float(record["primary_damage"]["damage"]) >= 0.20
            or float(record["primary_damage"]["critical_token_error"]) > 0
            for record in records
        ]
        scores = [float(record["risk"]["features"]["cross_model_disagreement"]) for record in records]
        critical_error_cases = [record for record in records if float(record["primary_damage"]["critical_token_error"]) > 0]
        detected = sum(
            float(record["risk"]["features"]["cross_model_disagreement"]) >= peer_threshold
            for record in critical_error_cases
        )
        result["peer_signal"] = {
            "evaluable_native_pages": sum(bool((native or {}).get(key)) for key in keys),
            "high_primary_damage_count": sum(labels),
            "auroc": auroc(labels, scores),
            "average_precision": average_precision(labels, scores),
            "critical_token_error_case_count": len(critical_error_cases),
            "critical_token_error_detection_recall": (
                detected / len(critical_error_cases) if critical_error_cases else None
            ),
            "cheap_peer_escalation_rate": sum(record["cheap_peer_escalate"] for record in records) / len(records),
        }
    return result


def main() -> int:
    args = parse_args()
    if RESULT.exists() or REPORT.exists():
        raise SystemExit("confirmatory result already exists; refusing rerun")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    selection_seal = json.loads(SELECTION_SEAL.read_text(encoding="utf-8"))
    if sha256_file(PROTOCOL_PATH) != freeze.get("protocol_sha256"):
        raise RuntimeError("protocol changed after freeze")
    if sha256_file(SELECTION_PATH) != selection_seal.get("selection_sha256"):
        raise RuntimeError("selection changed after seal")

    lane_a_keys = [str(item["page_stem"]) for item in selection["lane_a"]]
    lane_b_keys = [str(item["page_stem"]) for item in selection["lane_b"]]
    manifests = {
        "paddle_lane_a": output_manifest(args.paddle_lane_a, repeats=(1,), expected=set(lane_a_keys)),
        "paddle_lane_b": output_manifest(args.paddle_lane_b, repeats=(1, 2, 3), expected=set(lane_b_keys)),
        "specialist_lane_a": output_manifest(args.specialist_lane_a, repeats=(1,), expected=set(lane_a_keys)),
        "specialist_lane_b": output_manifest(args.specialist_lane_b, repeats=(1,), expected=set(lane_b_keys)),
    }
    native = native_map(set(lane_a_keys))

    # Seal ALL inference outputs before the first annotation-content fetch.
    if INFERENCE_SEAL.exists():
        raise RuntimeError("inference output seal already exists without final result; refusing ambiguous re-entry")
    inference_seal = {
        "experiment_id": protocol["experiment_id"],
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "selection_sha256": sha256_file(SELECTION_PATH),
        "model_outputs": manifests,
        "native_output_summary_sha256": sha256_file(NATIVE_DIR / "run-summary.json"),
        "native_evaluable_count": len(native),
        "ground_truth_consumed_before_this_seal": False,
    }
    INFERENCE_SEAL.parent.mkdir(parents=True, exist_ok=True)
    INFERENCE_SEAL.write_text(json.dumps(inference_seal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    old_gt_items = fetch_gt(str(protocol["dataset"]["source_native_pre_deletion_revision"]))
    current_gt_items = fetch_gt(str(protocol["dataset"]["current_v1_6_revision"]))
    old_gt = {view["page_key"]: view for view in map(gt_page_view, old_gt_items) if view["page_key"] in set(lane_a_keys)}
    current_gt = {view["page_key"]: view for view in map(gt_page_view, current_gt_items) if view["page_key"] in set(lane_b_keys)}
    if set(old_gt) != set(lane_a_keys) or set(current_gt) != set(lane_b_keys):
        raise RuntimeError("selected pages do not align with exact-revision annotations")

    primary_a = (markdown_map(args.paddle_lane_a, 1),)
    primary_b = tuple(markdown_map(args.paddle_lane_b, repeat) for repeat in (1, 2, 3))
    specialist_a = markdown_map(args.specialist_lane_a, 1)
    specialist_b = markdown_map(args.specialist_lane_b, 1)
    risk_threshold = float(protocol["routing_policy"]["semantic_risk_escalation_threshold"])
    peer_threshold = float(protocol["routing_policy"]["cheap_peer_disagreement_threshold"])
    lane_a = evaluate_lane(
        lane="a", keys=lane_a_keys, gt_by_key=old_gt, primary_maps=primary_a,
        specialist=specialist_a, native=native, risk_threshold=risk_threshold, peer_threshold=peer_threshold,
    )
    lane_b = evaluate_lane(
        lane="b", keys=lane_b_keys, gt_by_key=current_gt, primary_maps=primary_b,
        specialist=specialist_b, native=None, risk_threshold=risk_threshold, peer_threshold=peer_threshold,
    )

    acceptance = protocol["acceptance"]
    lane_a_signal = lane_a["peer_signal"]
    lane_a_pass = (
        int(lane_a_signal["evaluable_native_pages"]) >= int(acceptance["lane_a"]["minimum_evaluable_pages"])
        and lane_a_signal["auroc"] is not None
        and float(lane_a_signal["auroc"]) >= float(acceptance["lane_a"]["peer_signal_auroc_min"])
        and lane_a_signal["critical_token_error_detection_recall"] is not None
        and float(lane_a_signal["critical_token_error_detection_recall"]) >= float(acceptance["lane_a"]["critical_token_error_detection_recall_min"])
    )

    def routing_pass(lane: dict[str, Any]) -> bool:
        route = acceptance["routing"]
        return (
            lane["semantic_risk_mean_damage"] <= lane["primary_mean_damage"] + 1e-12
            and lane["semantic_risk_mean_critical_token_error"] <= lane["primary_mean_critical_token_error"] + 1e-12
            and lane["semantic_risk_mean_table_error"] <= lane["primary_mean_table_error"] + 1e-12
            and lane["semantic_risk_escalation_rate"] <= float(route["semantic_risk_escalation_rate_max"])
            and lane["damage_reduction_bootstrap"]["mean"] > 0.0
        )

    result = {
        "experiment_id": protocol["experiment_id"],
        "classification": protocol["classification"],
        "claim_boundary": protocol["claim_boundary"],
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "selection_sha256": sha256_file(SELECTION_PATH),
        "inference_output_seal_sha256": sha256_file(INFERENCE_SEAL),
        "ground_truth_persisted": False,
        "ground_truth_consumed_only_after_inference_seal": True,
        "lane_a": lane_a,
        "lane_b": lane_b,
        "acceptance": {
            "lane_a_peer_signal_pass": lane_a_pass,
            "lane_a_routing_pass": routing_pass(lane_a),
            "lane_b_routing_pass": routing_pass(lane_b),
            "overall_pass": lane_a_pass and routing_pass(lane_a) and routing_pass(lane_b),
        },
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = f"""# SEM-RISK-CONF-01 Confirmatory Report

- Classification: `{result['classification']}`
- Overall pass: **{result['acceptance']['overall_pass']}**
- Lane A native-peer signal pass: **{lane_a_pass}**
- Lane A peer AUROC: `{lane_a_signal['auroc']}`
- Lane A critical-token error detection recall: `{lane_a_signal['critical_token_error_detection_recall']}`
- Lane A semantic-risk mean damage: `{lane_a['semantic_risk_mean_damage']:.6f}` vs primary `{lane_a['primary_mean_damage']:.6f}`
- Lane B semantic-risk mean damage: `{lane_b['semantic_risk_mean_damage']:.6f}` vs primary `{lane_b['primary_mean_damage']:.6f}`
- Lane A escalation: `{lane_a['semantic_risk_escalation_rate']:.2%}`
- Lane B escalation: `{lane_b['semantic_risk_escalation_rate']:.2%}`
- Ground truth was consumed only after all inference outputs were hash-sealed and was not persisted by the evaluator.

## Claim boundary

{protocol['claim_boundary']}
"""
    REPORT.write_text(report, encoding="utf-8")
    print(json.dumps({"overall_pass": result["acceptance"]["overall_pass"], "lane_a_peer_auroc": lane_a_signal["auroc"], "lane_a_routing_pass": result["acceptance"]["lane_a_routing_pass"], "lane_b_routing_pass": result["acceptance"]["lane_b_routing_pass"]}, sort_keys=True))
    return 0 if result["acceptance"]["overall_pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
