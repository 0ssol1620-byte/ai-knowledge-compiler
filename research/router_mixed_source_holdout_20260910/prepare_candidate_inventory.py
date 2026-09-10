"""Build the frozen, truth-free official-source candidate inventory.

This stage reads curator-supplied metadata only. It does not fetch source bytes,
inspect document content, read annotations or call a model. Selection is the
protocol's deterministic URL-hash order, with an exact denominator per class.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .preflight_mixed_holdout import (
    ALLOWED_RIGHTS,
    _nonempty,
    _strict_https_url,
    _utc_timestamp,
    digest,
    load_json,
    load_jsonl,
)

EXPECTED_FIELDS = frozenset(
    {
        "candidate_id",
        "source_class",
        "source_url",
        "source_family_id",
        "publisher",
        "language",
        "rights_status",
        "rights_evidence_url",
        "rights_checked_at_utc",
        "allowed_use_scope",
        "target_locator_rule",
    }
)
LOCATOR_RULES = frozenset(
    {"whole_source", "first_native_object", "first_page_full_bbox1000", "geometry_anomaly_v1"}
)


class CandidateInventoryError(ValueError):
    """The candidate metadata cannot be frozen without selection discretion."""


def prepare_inventory(*, protocol_path: Path, seeds_path: Path) -> dict[str, Any]:
    protocol_bytes = protocol_path.read_bytes()
    protocol = load_json(protocol_path)
    seeds = load_jsonl(seeds_path)
    required_classes = tuple(protocol.get("required_classes") or ())
    source_selection = protocol.get("source_selection")
    selection = source_selection if isinstance(source_selection, Mapping) else {}
    target = selection.get("selected_units_per_class")
    if not isinstance(target, int) or isinstance(target, bool) or target < 1:
        raise CandidateInventoryError("PROTOCOL_TARGET_SIZE_INVALID")

    blockers: list[str] = []
    candidate_ids: set[str] = set()
    source_urls: set[str] = set()
    family_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, seed in enumerate(seeds):
        prefix = f"ROW_{index:04d}"
        if set(seed) != EXPECTED_FIELDS:
            blockers.append(f"{prefix}_SCHEMA_INVALID")
        candidate_id = seed.get("candidate_id")
        source_class = seed.get("source_class")
        source_url = seed.get("source_url")
        family_id = seed.get("source_family_id")
        if not _nonempty(candidate_id) or candidate_id in candidate_ids:
            blockers.append(f"{prefix}_CANDIDATE_ID_INVALID_OR_DUPLICATE")
        else:
            candidate_ids.add(str(candidate_id))
        if source_class not in required_classes:
            blockers.append(f"{prefix}_SOURCE_CLASS_INVALID")
        if not _strict_https_url(source_url) or source_url in source_urls:
            blockers.append(f"{prefix}_SOURCE_URL_INVALID_OR_DUPLICATE")
        else:
            source_urls.add(str(source_url))
        if not _nonempty(family_id) or family_id in family_ids:
            blockers.append(f"{prefix}_SOURCE_FAMILY_INVALID_OR_DUPLICATE")
        else:
            family_ids.add(str(family_id))
        if seed.get("rights_status") not in ALLOWED_RIGHTS:
            blockers.append(f"{prefix}_RIGHTS_UNQUALIFIED")
        if not _strict_https_url(seed.get("rights_evidence_url")):
            blockers.append(f"{prefix}_RIGHTS_EVIDENCE_URL_INVALID")
        if not _utc_timestamp(seed.get("rights_checked_at_utc")):
            blockers.append(f"{prefix}_RIGHTS_TIMESTAMP_INVALID")
        if seed.get("allowed_use_scope") != "local_research_evaluation_no_redistribution":
            blockers.append(f"{prefix}_USE_SCOPE_INVALID")
        if seed.get("target_locator_rule") not in LOCATOR_RULES:
            blockers.append(f"{prefix}_LOCATOR_RULE_INVALID")
        for field in ("publisher", "language"):
            if not _nonempty(seed.get(field)):
                blockers.append(f"{prefix}_{field.upper()}_REQUIRED")
        row = dict(seed)
        row["selection_url_sha256"] = (
            digest(str(source_url).encode("utf-8")) if _strict_https_url(source_url) else None
        )
        normalized.append(row)

    counts = Counter(str(row.get("source_class")) for row in normalized)
    for source_class in required_classes:
        if counts[source_class] < target:
            blockers.append(f"CLASS_{source_class}_INSUFFICIENT_CANDIDATES")
    if blockers:
        raise CandidateInventoryError(";".join(dict.fromkeys(blockers)))

    class_order = {source_class: index for index, source_class in enumerate(required_classes)}
    normalized.sort(
        key=lambda row: (class_order[str(row["source_class"])], row["selection_url_sha256"])
    )
    selected_counts: Counter[str] = Counter()
    for row in normalized:
        source_class = str(row["source_class"])
        row["selection_state"] = (
            "SELECTED" if selected_counts[source_class] < target else "FROZEN_STANDBY_UNUSED"
        )
        if row["selection_state"] == "SELECTED":
            selected_counts[source_class] += 1
    return {
        "schema": "tavonel.router_mixed_source_candidate_inventory.v1",
        "benchmark_id": protocol.get("benchmark_id"),
        "protocol_sha256": digest(protocol_bytes),
        "selection": "required class order then SHA256(canonical source URL) ascending",
        "selected_units_per_class": target,
        "selected_units": sum(selected_counts.values()),
        "candidate_units": len(normalized),
        "source_content_accessed": False,
        "truth_accessed": False,
        "model_calls": 0,
        "candidates": normalized,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--seeds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inventory = prepare_inventory(protocol_path=args.protocol, seeds_path=args.seeds)
    except (CandidateInventoryError, OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
