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
PROTOCOL = EXP / "confirmatory-protocol-v1.json"
BASE_RECEIPT = EXP / "receipts" / "wikipedia-real-revision-holdout-v2.json"
ADAPTER = EXP / "scripts" / "run_public_real_revision_holdout_v3.py"
CORPUS = EXP / "corpus-confirmatory-v1"
OUTPUT = EXP / "receipts" / "wikipedia-real-revision-confirmatory-v1.json"


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def load_adapter():
    spec = importlib.util.spec_from_file_location("real_revision_v3_confirmatory", ADAPTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("real-revision v3 adapter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_CONFIRMATORY_FETCH":
        raise RuntimeError("confirmatory protocol is not frozen")
    if int(protocol.get("adapter_version", -1)) != 3:
        raise RuntimeError("confirmatory adapter version drifted")
    titles = protocol.get("titles")
    if not isinstance(titles, list) or len(titles) != 12 or len(set(titles)) != 12:
        raise RuntimeError("confirmatory title set drifted")
    base = json.loads(BASE_RECEIPT.read_text(encoding="utf-8"))
    if base.get("all_pairs_equivalent") is not True:
        raise RuntimeError("base real-revision receipt lost equivalence")
    if int(base.get("stale_left_behind_total", -1)) != 0:
        raise RuntimeError("base real-revision receipt contains stale-left-behind")

    adapter = load_adapter()
    CORPUS.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    acquisition_errors: list[dict[str, str]] = []
    for title in titles:
        try:
            before, after = adapter.fetch_pair(str(title))
            title_dir = CORPUS / adapter.slug(str(title))
            title_dir.mkdir(parents=True, exist_ok=True)
            (title_dir / f"{before.revid}.wikitext").write_text(before.text, encoding="utf-8")
            (title_dir / f"{after.revid}.wikitext").write_text(after.text, encoding="utf-8")
            record = adapter.run_pair(before, after)
            records.append(record)
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
        except Exception as exc:
            acquisition_errors.append(
                {
                    "title": str(title),
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:500],
                }
            )
            print(
                json.dumps(
                    {
                        "title": title,
                        "acquisition_error": type(exc).__name__,
                    },
                    sort_keys=True,
                )
            )
        time.sleep(2.0)

    base_changed = int(base.get("changed_pair_count", -1))
    changed = [row for row in records if int(row.get("changed_logical_ids", 0)) > 0]
    stale_total = sum(int(row.get("stale_left_behind", 0)) for row in records)
    all_equivalent = len(records) == len(titles) and all(
        row.get("equivalent") is True for row in records
    )
    mean_rebuild = (
        sum(float(row.get("rebuild_fraction", 0.0)) for row in records) / len(records)
        if records
        else 0.0
    )
    gates = {
        "all_confirmatory_pairs_acquired": len(records) == len(titles),
        "zero_acquisition_errors": not acquisition_errors,
        "all_confirmatory_pairs_equivalent": all_equivalent,
        "confirmatory_zero_stale_left_behind": stale_total == 0,
        "base_plus_confirmatory_changed_pair_count_ge_8": base_changed + len(changed) >= 8,
    }
    receipt: dict[str, Any] = {
        "schema": "tavonel.real-public-revision-confirmatory.v1",
        "generated_at": now(),
        "protocol_sha256": canonical_sha256(protocol),
        "base_receipt_sha256": str(base.get("receipt_sha256", "")),
        "adapter_version": 3,
        "cutoff": protocol["cutoff"],
        "confirmatory_pair_count": len(records),
        "confirmatory_changed_pair_count": len(changed),
        "base_changed_pair_count": base_changed,
        "base_plus_confirmatory_changed_pair_count": base_changed + len(changed),
        "confirmatory_all_equivalent": all_equivalent,
        "confirmatory_stale_left_behind_total": stale_total,
        "confirmatory_mean_rebuild_fraction": mean_rebuild,
        "acquisition_errors": acquisition_errors,
        "records": records,
        "success_gate": gates,
        "external_gpu_cost_usd": 0.0,
        "diagnostic_extension_outcomes_excluded": True,
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
                "gates": gates,
                "confirmatory_changed_pair_count": len(changed),
                "base_plus_confirmatory_changed_pair_count": base_changed + len(changed),
                "mean_rebuild_fraction": mean_rebuild,
            },
            sort_keys=True,
        )
    )
    return 0 if all(gates.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
