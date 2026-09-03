#!/usr/bin/env python3
"""The eleven integrity gates that stand between a completed acquisition and the endpoint.

The v7 acquisition returned 0 and reported `ELIGIBLE_FOR_QUESTION_SET`. That is
the acquisition's own summary of its own run, and this programme has a standing
rule against treating a self-report as verification.

Nothing here evaluates the endpoint. The question set, the retrieval comparison
and any same-intelligence claim are downstream of these gates and are deliberately
not touched: an acquisition that completes is an acquisition that completed.

Gates, in order:

     1. process exit status
     2. completion sidecar exists and records a return code
     3. frozen manifest unchanged since the launch provenance recorded it
     4. title accounting against the frozen 6,987-title manifest
     5. eligible / excluded counts reconcile with the manifest slice
     6. incomplete directory count
     7. duplicate detection (directory names and manifest indices)
     8. metadata-last semantics -- every directory has all three files
     9. per-pair hashes recompute against what the receipt recorded
    10. corpus root hash, computed and pinned here for the first time
    11. acquisition receipt self-hash recomputes

A gate that cannot be evaluated is recorded UNKNOWN, never PASS.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
CORPUS = EXP / "corpus-v7"
RECEIPTS = EXP / "receipts"
ACQ = RECEIPTS / "acquisition-v7-2026-08-19.json"
SIDECAR = RECEIPTS / "acquisition-v7-completion-2026-08-19.json"
PROVENANCE = RECEIPTS / "v7-launch-provenance-2026-08-19.json"
MANIFEST = RECEIPTS / "title-manifest-v3-2026-08-19.json"

COHORT_SIZE = 750
MAX_COHORTS = 6


def sha256_file(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def gate(name: str, state: str, detail: Any) -> dict[str, Any]:
    return {"gate": name, "state": state, "detail": detail}


def main() -> int:
    gates: list[dict[str, Any]] = []

    # 1 -- process exit status
    sidecar = json.loads(SIDECAR.read_text(encoding="utf-8")) if SIDECAR.exists() else None
    rc = sidecar.get("return_code") if sidecar else None
    gates.append(gate(
        "1_process_exit_status",
        "PASS" if rc == 0 else ("UNKNOWN" if rc is None else "FAIL"),
        {"return_code": rc,
         "source": "completion sidecar, not the console -- a console line is not an artifact"},
    ))

    # 2 -- completion sidecar
    gates.append(gate(
        "2_completion_sidecar",
        "PASS" if sidecar and "return_code" in sidecar else "FAIL",
        {"exists": SIDECAR.exists(),
         "records_return_code": bool(sidecar and "return_code" in sidecar),
         "scientific_rules_changed": sidecar.get("scientific_rules_changed") if sidecar else None},
    ))

    # 3 -- frozen manifest unchanged since launch
    prov = json.loads(PROVENANCE.read_text(encoding="utf-8")) if PROVENANCE.exists() else {}
    pinned = (prov.get("frozen_input_hashes") or {}).get("title_manifest_file")
    now = sha256_file(MANIFEST)
    gates.append(gate(
        "3_manifest_unchanged_since_launch",
        "PASS" if pinned and pinned == now else ("UNKNOWN" if not pinned else "FAIL"),
        {"pinned_at_launch": pinned, "now": now},
    ))

    acq = json.loads(ACQ.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    titles = manifest.get("titles", [])
    records = acq.get("records", [])
    exclusions = acq.get("exclusions", [])

    # 4 -- title accounting against the frozen manifest
    considered = min(len(titles), COHORT_SIZE * MAX_COHORTS)
    cohorts_done = acq.get("cohorts_completed", 0)
    slice_size = min(considered, cohorts_done * COHORT_SIZE)
    accounted = len(records) + len(exclusions)
    gates.append(gate(
        "4_title_accounting",
        "PASS" if accounted == slice_size else "FAIL",
        {"titles_in_manifest": len(titles), "manifest_slice_considered": considered,
         "cohorts_completed": cohorts_done, "titles_in_completed_cohorts": slice_size,
         "eligible_plus_excluded": accounted,
         "note": ("the acquisition stops at the first cohort that satisfies the availability "
                  "rule, so unreached cohorts are not missing data -- they were never due")},
    ))

    # 5 -- eligible / excluded reconcile with the receipt's own counters
    gates.append(gate(
        "5_counts_reconcile",
        "PASS" if (acq.get("eligible_records") == len(records)
                   and acq.get("excluded_records") == len(exclusions)) else "FAIL",
        {"receipt_eligible": acq.get("eligible_records"), "records_on_file": len(records),
         "receipt_excluded": acq.get("excluded_records"), "exclusions_on_file": len(exclusions),
         "exclusion_reasons": dict(Counter(e.get("reason") for e in exclusions))},
    ))

    # 6 + 8 -- directory completeness, metadata written last
    dirs = sorted(p for p in CORPUS.iterdir() if p.is_dir()) if CORPUS.is_dir() else []
    complete, incomplete = [], []
    for d in dirs:
        have = {f.name for f in d.iterdir() if f.is_file()}
        (complete if {"before.wikitext", "after.wikitext", "metadata.json"} <= have
         else incomplete).append(d.name)
    gates.append(gate(
        "6_incomplete_directories",
        "PASS" if not incomplete else "FAIL",
        {"directories": len(dirs), "complete": len(complete),
         "incomplete": len(incomplete), "incomplete_names": incomplete[:20]},
    ))
    gates.append(gate(
        "8_metadata_last_semantics",
        "PASS" if len(complete) == len(records) else "FAIL",
        {"complete_directories": len(complete), "eligible_records": len(records),
         "why": ("metadata.json is written after both wikitext files, so a directory "
                 "carrying all three is a completed pair. v5 and v6 each left one "
                 "directory with two files and no metadata -- the signature of the "
                 "defect that killed both")},
    ))

    # 7 -- duplicates
    dup_dirs = [n for n, c in Counter(d.name for d in dirs).items() if c > 1]
    dup_idx = [i for i, c in Counter(r["manifest_index"] for r in records).items() if c > 1]
    dup_titles = [t for t, c in Counter(r["title"] for r in records).items() if c > 1]
    gates.append(gate(
        "7_duplicate_detection",
        "PASS" if not (dup_dirs or dup_idx or dup_titles) else "FAIL",
        {"duplicate_directories": dup_dirs, "duplicate_manifest_indices": dup_idx[:20],
         "duplicate_titles": dup_titles[:20]},
    ))

    # 9 -- per-pair hashes recompute
    mismatched, missing = [], []
    for r in records:
        for side in ("before", "after"):
            rel = r.get(f"relative_{side}_path")
            if not rel:
                missing.append((r["title"], side))
                continue
            path = EXP / rel
            if not path.exists():
                missing.append((r["title"], side))
                continue
            if sha256_file(path) != r.get(f"{side}_sha256"):
                mismatched.append({"title": r["title"], "side": side})
    gates.append(gate(
        "9_per_pair_hashes",
        "PASS" if not mismatched and not missing else "FAIL",
        {"pairs_checked": len(records), "mismatched": mismatched[:10],
         "missing_files": missing[:10]},
    ))

    # 10 -- corpus root hash, pinned here for the first time
    leaves = []
    for d in dirs:
        for f in sorted(d.iterdir()):
            if f.is_file():
                leaves.append(f"{d.name}/{f.name}:{sha256_file(f)}")
    root_hash = "sha256:" + hashlib.sha256("\n".join(sorted(leaves)).encode("utf-8")).hexdigest()
    gates.append(gate(
        "10_corpus_root_hash",
        "PASS" if leaves else "UNKNOWN",
        {"files_hashed": len(leaves), "corpus_root_sha256": root_hash,
         "definition": ("sha256 over the sorted list of 'dir/file:sha256' lines; recomputable "
                        "by any third party from the corpus alone")},
    ))

    # 11 -- acquisition receipt self-hash
    body = {k: v for k, v in acq.items() if k != "receipt_sha256"}
    recomputed = canonical_sha256(body)
    gates.append(gate(
        "11_acquisition_receipt_self_hash",
        "PASS" if recomputed == acq.get("receipt_sha256") else "FAIL",
        {"recorded": acq.get("receipt_sha256"), "recomputed": recomputed},
    ))

    states = [g["state"] for g in gates]
    all_pass = all(s == "PASS" for s in states)

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v7-corpus-integrity.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "The eleven gates between a completed acquisition and any endpoint evaluation. "
            "The acquisition's own ELIGIBLE_FOR_QUESTION_SET is a self-report; this is the "
            "check."
        ),
        "gates": gates,
        "gates_passed": states.count("PASS"),
        "gates_failed": states.count("FAIL"),
        "gates_unknown": states.count("UNKNOWN"),
        "all_gates_pass": all_pass,
        "endpoint_status": "NOT_RUN",
        "endpoint_note": (
            "Passing these gates says the corpus is what the acquisition says it is. It says "
            "nothing about whether the frozen question set finds moved facts. That endpoint "
            "was declared NOT RUN once rather than weakened, and that declaration stands "
            "until it is executed under its own frozen protocol."
        ),
        "corpus_root_sha256": root_hash,
        "acquisition_receipt_sha256": acq.get("receipt_sha256"),
        "availability_reached": acq.get("availability_reached"),
        "primary_endpoint_status_reported_by_acquisition": acq.get("primary_endpoint_status"),
        "eligible_pages": acq.get("eligible_records"),
        "primary_retained": acq.get("primary_revision_sensitive_retained"),
        "articles_with_primary": acq.get("articles_with_primary"),
        "unchanged_controls": acq.get("unchanged_controls"),
        "corpus_v5_modified": False,
        "corpus_v6_modified": False,
        "identity_module_modified": False,
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out = RECEIPTS / "v7-corpus-integrity-2026-08-19.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for g in gates:
        print(f"  {g['state']:<8} {g['gate']}")
    print(f"passed={states.count('PASS')} failed={states.count('FAIL')} "
          f"unknown={states.count('UNKNOWN')}")
    print(f"corpus root: {root_hash}")
    print(f"endpoint: {receipt['endpoint_status']}")
    print(f"wrote {out}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
