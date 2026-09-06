from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "research" / "experiments" / "H1-B-REAL-REVISION-01"
PROTOCOL = EXP / "extension-protocol-v1.json"
BASE_RECEIPT = EXP / "receipts" / "wikipedia-real-revision-holdout-v2.json"
V2 = EXP / "scripts" / "run_public_real_revision_holdout_v2.py"
CORPUS = EXP / "corpus-extension-v1"
OUTPUT = EXP / "receipts" / "wikipedia-real-revision-holdout-extended-v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("real_revision_v2_extension", V2)
    if spec is None or spec.loader is None:
        raise RuntimeError("real-revision v2 adapter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def main() -> int:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_EXTENSION_FETCH":
        raise RuntimeError("extension protocol is not frozen")
    titles = protocol.get("titles")
    if not isinstance(titles, list) or len(titles) != 12 or len(set(titles)) != 12:
        raise RuntimeError("extension protocol title set drifted")
    base = json.loads(BASE_RECEIPT.read_text(encoding="utf-8"))
    if (
        base.get("all_pairs_equivalent") is not True
        or int(base.get("stale_left_behind_total", -1)) != 0
    ):
        raise RuntimeError("base real-revision receipt is not PASS")

    module = load_module()
    CORPUS.mkdir(parents=True, exist_ok=True)
    extension_records: list[dict[str, Any]] = []
    for title in titles:
        before, after = module.fetch_pair(str(title))
        title_dir = CORPUS / module.slug(str(title))
        title_dir.mkdir(parents=True, exist_ok=True)
        (title_dir / f"{before.revid}.wikitext").write_text(before.text, encoding="utf-8")
        (title_dir / f"{after.revid}.wikitext").write_text(after.text, encoding="utf-8")
        record = module.run_pair(before, after)
        extension_records.append(record)
        print(
            json.dumps(
                {
                    "title": title,
                    "equivalent": record["equivalent"],
                    "changed_logical_ids": record["changed_logical_ids"],
                    "rebuild_fraction": record["rebuild_fraction"],
                },
                sort_keys=True,
            )
        )
        time.sleep(2.0)

    base_records = base.get("records")
    if not isinstance(base_records, list) or len(base_records) != int(base.get("pair_count", -1)):
        raise RuntimeError("base receipt record coverage drifted")
    combined = [dict(item) for item in base_records] + extension_records
    changed = [item for item in combined if int(item.get("changed_logical_ids", 0)) > 0]
    stale_total = sum(int(item.get("stale_left_behind", 0)) for item in combined)
    all_equivalent = all(item.get("equivalent") is True for item in combined)
    total_artifacts = sum(int(item.get("artifact_count", 0)) for item in combined)
    total_rebuilt = sum(int(item.get("rebuild_count", 0)) for item in combined)
    mean_rebuild = (
        sum(float(item.get("rebuild_fraction", 0.0)) for item in combined) / len(combined)
        if combined
        else 0.0
    )
    receipt: dict[str, Any] = {
        "schema": "tavonel.real-public-revision-holdout-extended.v1",
        "generated_at": now(),
        "protocol_sha256": canonical_sha256(protocol),
        "base_receipt_sha256": str(base.get("receipt_sha256", "")),
        "adapter_version": 2,
        "cutoff": protocol["cutoff"],
        "base_pair_count": len(base_records),
        "extension_pair_count": len(extension_records),
        "combined_pair_count": len(combined),
        "combined_changed_pair_count": len(changed),
        "all_pairs_equivalent": all_equivalent,
        "stale_left_behind_total": stale_total,
        "total_artifacts": total_artifacts,
        "total_rebuilt": total_rebuilt,
        "mean_rebuild_fraction": mean_rebuild,
        "extension_records": extension_records,
        "success_gate": {
            "all_pairs_equivalent": all_equivalent,
            "zero_stale_left_behind": stale_total == 0,
            "changed_pair_count_ge_8": len(changed) >= 8,
            "all_extension_pairs_retained": len(extension_records) == len(titles),
        },
        "external_gpu_cost_usd": 0.0,
        "claim_boundary": protocol["claim_boundary"],
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "receipt": OUTPUT.relative_to(ROOT).as_posix(),
                "combined_pair_count": len(combined),
                "combined_changed_pair_count": len(changed),
                "all_pairs_equivalent": all_equivalent,
                "stale_left_behind_total": stale_total,
                "mean_rebuild_fraction": mean_rebuild,
                "gates": receipt["success_gate"],
            },
            sort_keys=True,
        )
    )
    return 0 if all(receipt["success_gate"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
