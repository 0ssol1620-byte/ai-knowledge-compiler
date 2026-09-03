"""Evidence-bounded metrics for the TAVONEL P1 quality launch gate.

The evaluator accepts frozen gold and independently produced candidate JSON. It
does not run OCR, an LLM, or RunPod, so execution provenance cannot be confused
with output quality. Every aggregate retains its denominator and critical gates
fail closed when evidence is absent.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EvaluationError(ValueError):
    """The suite or candidate violates the qualification contract."""


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvaluationError(f"{path}: root must be an object")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 1.0


def _levenshtein(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for row, left_item in enumerate(left, 1):
        current = [row]
        for column, right_item in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def _f1(expected: set[object], actual: set[object]) -> dict[str, float | int]:
    tp = len(expected & actual)
    fp = len(actual - expected)
    fn = len(expected - actual)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * precision * recall, precision + recall),
    }


def _bbox_iou(left: list[int], right: list[int]) -> float:
    ix = max(0, min(left[2], right[2]) - max(left[0], right[0]))
    iy = max(0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = ix * iy
    left_area = max(0, left[2] - left[0]) * max(0, left[3] - left[1])
    right_area = max(0, right[2] - right[0]) * max(0, right[3] - right[1])
    return _ratio(intersection, left_area + right_area - intersection)


def _pairs(clusters: list[list[str]]) -> set[tuple[str, str]]:
    return {
        tuple(sorted((left, right)))
        for cluster in clusters
        for index, left in enumerate(cluster)
        for right in cluster[index + 1 :]
    }


def _dcg(relevances: list[int]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(relevances))


def _classification(gold: dict[str, str], predicted: dict[str, str]) -> dict[str, Any]:
    labels = sorted(set(gold.values()))
    correct = sum(predicted.get(key) == value for key, value in gold.items())
    per_label: dict[str, float] = {}
    for label in labels:
        expected = {key for key, value in gold.items() if value == label}
        actual = {key for key, value in predicted.items() if value == label}
        per_label[label] = float(_f1(expected, actual)["f1"])
    return {
        "correct": correct,
        "total": len(gold),
        "accuracy": _ratio(correct, len(gold)),
        "macro_f1": _ratio(sum(per_label.values()), len(per_label)),
        "per_label_f1": per_label,
    }


def _metric_ocr_text(gold: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    expected = gold["documents"]
    actual = {row["id"]: row["text"] for row in candidate["documents"]}
    char_errors = word_errors = char_total = word_total = 0
    for row in expected:
        predicted = actual.get(row["id"], "")
        char_errors += _levenshtein(list(row["text"]), list(predicted))
        word_errors += _levenshtein(row["text"].split(), predicted.split())
        char_total += len(row["text"])
        word_total += len(row["text"].split())
    return {
        "documents": len(expected),
        "characters": char_total,
        "words": word_total,
        "character_accuracy": max(0.0, 1 - _ratio(char_errors, char_total)),
        "word_accuracy": max(0.0, 1 - _ratio(word_errors, word_total)),
    }


def _metric_layout(gold: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    expected = {row["id"]: row for row in gold["blocks"]}
    actual = {row["id"]: row for row in candidate["blocks"]}
    typed_gold = {(key, row["type"]) for key, row in expected.items()}
    typed_actual = {(key, row["type"]) for key, row in actual.items()}
    shared = expected.keys() & actual.keys()
    order_hits = sum(expected[key]["order"] == actual[key]["order"] for key in shared)
    ious = [_bbox_iou(expected[key]["bbox1000"], actual[key]["bbox1000"]) for key in shared]
    return {
        "expected_blocks": len(expected),
        "matched_blocks": len(shared),
        "type_f1": _f1(typed_gold, typed_actual)["f1"],
        "reading_order_accuracy": _ratio(order_hits, len(expected)),
        "mean_bbox_iou": _ratio(sum(ious), len(expected)),
    }


def _metric_citations(gold: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    expected = {row["id"]: row for row in gold["citations"]}
    actual = {row["id"]: row for row in candidate["citations"]}
    page_hits = region_hits = 0
    for key, row in expected.items():
        found = actual.get(key)
        if found and found["page_index0"] == row["page_index0"]:
            page_hits += 1
            if _bbox_iou(row["bbox1000"], found["bbox1000"]) >= gold["region_iou_threshold"]:
                region_hits += 1
    return {
        "citations": len(expected),
        "region_iou_threshold": gold["region_iou_threshold"],
        "page_accuracy": _ratio(page_hits, len(expected)),
        "region_accuracy": _ratio(region_hits, len(expected)),
    }


def _metric_entities(gold: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    score = _f1(_pairs(gold["clusters"]), _pairs(candidate["clusters"]))
    score["mentions"] = len({item for cluster in gold["clusters"] for item in cluster})
    return score


def _metric_temporal(gold: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    expected_facts = {row["id"]: row for row in gold["facts"]}
    actual_facts = {row["id"]: row for row in candidate["facts"]}
    fields = ("valid_from", "valid_to", "recorded_at", "superseded_at", "temporal_source")
    field_hits = sum(
        actual_facts.get(key, {}).get(field) == row.get(field)
        for key, row in expected_facts.items()
        for field in fields
    )
    expected_queries = {row["id"]: set(row["fact_ids"]) for row in gold["as_of"]}
    actual_queries = {row["id"]: set(row["fact_ids"]) for row in candidate["as_of"]}
    query_hits = sum(actual_queries.get(key) == value for key, value in expected_queries.items())
    return {
        "facts": len(expected_facts),
        "as_of_queries": len(expected_queries),
        "field_accuracy": _ratio(field_hits, len(expected_facts) * len(fields)),
        "as_of_accuracy": _ratio(query_hits, len(expected_queries)),
    }


def _metric_graph(gold: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    gold_nodes = {(row["id"], row["type"]) for row in gold["nodes"]}
    actual_nodes = {(row["id"], row["type"]) for row in candidate["nodes"]}
    gold_edges = {(row["source"], row["relation"], row["target"]) for row in gold["edges"]}
    actual_edges = {(row["source"], row["relation"], row["target"]) for row in candidate["edges"]}
    ids = {row["id"] for row in candidate["nodes"]}
    valid_types = set(gold["allowed_node_types"])
    valid_relations = set(gold["allowed_relations"])
    violations = []
    if len(ids) != len(candidate["nodes"]):
        violations.append("duplicate_node_id")
    for edge in candidate["edges"]:
        if edge["source"] not in ids or edge["target"] not in ids:
            violations.append("dangling_edge")
        if edge["source"] == edge["target"]:
            violations.append("self_edge")
        if edge["relation"] not in valid_relations:
            violations.append("unknown_relation")
        if not edge.get("source_ref"):
            violations.append("missing_edge_source_ref")
    if any(row["type"] not in valid_types for row in candidate["nodes"]):
        violations.append("unknown_node_type")
    return {
        "node": _f1(gold_nodes, actual_nodes),
        "edge": _f1(gold_edges, actual_edges),
        "valid": not violations,
        "violations": sorted(set(violations)),
    }


def _metric_chunking(gold: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    required_units = set(gold["source_units"])
    chunks = candidate["chunks"]
    covered = {item for chunk in chunks for item in chunk["source_units"]}
    cited = {item for chunk in chunks for item in chunk["citation_units"]}
    limits = sum(chunk["token_count"] <= gold["max_tokens"] for chunk in chunks)
    boundaries = sum(not chunk.get("breaks_protected_boundary", False) for chunk in chunks)
    return {
        "chunks": len(chunks),
        "source_coverage": _ratio(len(required_units & covered), len(required_units)),
        "citation_coverage": _ratio(len(required_units & cited), len(required_units)),
        "token_limit_rate": _ratio(limits, len(chunks)),
        "boundary_preservation_rate": _ratio(boundaries, len(chunks)),
    }


def _metric_retrieval(gold: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    actual = {row["id"]: row["retrieved"] for row in candidate["queries"]}
    reciprocal = recall = ndcg = 0.0
    k = gold["k"]
    for query in gold["queries"]:
        relevant = set(query["relevant"])
        retrieved = actual.get(query["id"], [])[:k]
        ranks = [index + 1 for index, item in enumerate(retrieved) if item in relevant]
        reciprocal += 1 / min(ranks) if ranks else 0
        recall += _ratio(len(relevant & set(retrieved)), len(relevant))
        gains = [int(item in relevant) for item in retrieved]
        ideal = [1] * min(len(relevant), k)
        ndcg += _ratio(_dcg(gains), _dcg(ideal))
    total = len(gold["queries"])
    return {
        "queries": total,
        "k": k,
        "mrr": reciprocal / total,
        "recall_at_k": recall / total,
        "ndcg_at_k": ndcg / total,
    }


def _metric_downstream(gold: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    expected = {row["id"]: row["answer"] for row in gold["tasks"]}
    raw = {row["id"]: row["answer"] for row in candidate["raw"]}
    compiled = {row["id"]: row["answer"] for row in candidate["compiled"]}
    raw_hits = sum(raw.get(key) == value for key, value in expected.items())
    compiled_hits = sum(compiled.get(key) == value for key, value in expected.items())
    non_regressions = sum(
        int(compiled.get(key) == value) >= int(raw.get(key) == value)
        for key, value in expected.items()
    )
    total = len(expected)
    raw_score = _ratio(raw_hits, total)
    compiled_score = _ratio(compiled_hits, total)
    return {
        "tasks": total,
        "raw_exact_accuracy": raw_score,
        "compiled_exact_accuracy": compiled_score,
        "absolute_improvement": compiled_score - raw_score,
        "non_regression_rate": _ratio(non_regressions, total),
    }


_METRICS = {
    "ocr_text": _metric_ocr_text,
    "ocr_layout": _metric_layout,
    "citations": _metric_citations,
    "entity_resolution": _metric_entities,
    "claims": lambda gold, candidate: _classification(gold["labels"], candidate["labels"]),
    "temporal_authority": _metric_temporal,
    "ontology_graph": _metric_graph,
    "adaptive_chunking": _metric_chunking,
    "retrieval": _metric_retrieval,
    "downstream_ai": _metric_downstream,
}


def _value_at(metrics: dict[str, Any], path: str) -> float | bool:
    value: Any = metrics
    for part in path.split("."):
        value = value[part]
    if not isinstance(value, (int, float, bool)):
        raise EvaluationError(f"threshold path {path!r} is not scalar")
    return value


def evaluate_suite(
    suite: dict[str, Any], candidate: dict[str, Any], *, repo_root: Path
) -> dict[str, Any]:
    if suite.get("schema_version") != "quality-golden-suite-1.0.0":
        raise EvaluationError("unsupported golden suite schema")
    if candidate.get("schema_version") != "quality-candidate-1.0.0":
        raise EvaluationError("unsupported candidate schema")
    if candidate.get("suite_id") != suite.get("suite_id"):
        raise EvaluationError("candidate suite_id does not match gold")

    sources = []
    for source in suite["sources"]:
        path = repo_root / source["path"]
        if not path.is_file():
            raise EvaluationError(f"missing source fixture: {source['path']}")
        digest = _sha256(path.read_bytes())
        if digest != source["sha256"]:
            raise EvaluationError(f"source fixture drift: {source['path']}")
        sources.append({**source, "observed_sha256": digest, "verified": True})

    dimensions = []
    candidate_dimensions = candidate.get("dimensions", {})
    for name, evaluator in _METRICS.items():
        if name not in suite["gold"] or name not in candidate_dimensions:
            raise EvaluationError(f"missing required dimension: {name}")
        metrics = evaluator(suite["gold"][name], candidate_dimensions[name])
        checks = []
        for threshold in suite["acceptance"][name]:
            actual = _value_at(metrics, threshold["metric"])
            passed = (
                actual == threshold["value"]
                if "value" in threshold
                else actual >= threshold["minimum"]
            )
            checks.append({**threshold, "actual": actual, "passed": passed})
        dimensions.append(
            {
                "name": name,
                "passed": all(row["passed"] for row in checks),
                "metrics": metrics,
                "checks": checks,
            }
        )

    passed = sum(row["passed"] for row in dimensions)
    report = {
        "schema_version": "quality-acceptance-report-1.0.0",
        "report_id": f"{suite['suite_id']}:{candidate['candidate_id']}",
        "generated_at": datetime.now(UTC).isoformat(),
        "suite_id": suite["suite_id"],
        "suite_sha256": _sha256(_canonical(suite)),
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": _sha256(_canonical(candidate)),
        "evidence_boundary": {
            "grade": suite["evidence_boundary"]["grade"],
            "uses_only_pinned_local_or_public_fixtures": True,
            "runpod_execution": "not_observed",
            "production_runtime_claim": False,
            "limitations": suite["evidence_boundary"]["limitations"],
        },
        "sources": sources,
        "dimensions": dimensions,
        "passed_dimensions": passed,
        "total_dimensions": len(dimensions),
        "verdict": "qualified" if passed == len(dimensions) else "not_qualified",
    }
    report["report_sha256"] = _sha256(_canonical(report))
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
