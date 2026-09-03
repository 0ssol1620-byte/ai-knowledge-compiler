#!/usr/bin/env python3
"""Acquisition integrity gate for the v8 holdout corpus.

Runs **after** acquisition and **before** the question set. It verifies what was
actually written to disk against what the acquisition receipt claims, and against
the two frozen documents that define what "untouched" means: the holdout title
manifest and the v7 development seal.

This file is not part of the frozen experiment machinery. It decides no
threshold, generates no question, scores nothing and cannot change an arm. It
only answers whether the corpus the endpoint is about to be computed from is the
corpus the receipt describes. A failure here is an acquisition failure, not a
result, and it must be found before a question set exists, because after that
point a corpus defect and an endpoint are entangled.

Nine checks, each fail-closed:

1. `process_exit_status`       the completion sidecar exists and records rc 0
2. `acquisition_receipt`       schema, protocol and script digests, manifest binding
3. `accounting_reconciles`     eligible + excluded == titles consumed
4. `no_incomplete_directories` every page directory carries all three files
5. `no_duplicates`             no repeated manifest index, title or directory
6. `metadata_written_last`     metadata.json is not older than the wikitext beside it
7. `per_pair_hashes_match`     every before/after file rehashes to the recorded digest
8. `corpus_root_hash`          one order-independent digest over the whole corpus
9. `untouched_disjointness`    zero overlap with the sealed development titles, and
                               every acquired title is in the holdout manifest

`--output` writes a receipt. Exit is non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
RECEIPTS = EXP / "receipts"
SEAL = RECEIPTS / "v7-development-seal-2026-08-19.json"
V3_PROTOCOL = EXP / "PROTOCOL_V3_ACQUISITION_2026-08-19.md"
V3_SCRIPT = HERE / "acquire_w6_v3.py"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_title(title: str) -> str:
    return title.replace("_", " ").strip()


def evaluate(*, acquisition: Path, sidecar: Path, corpus: Path,
             manifest: Path) -> dict[str, Any]:
    conditions: dict[str, dict[str, Any]] = {}

    def check(name: str, ok: bool, why: str, detail: Any = None) -> None:
        conditions[name] = {"passes": bool(ok), "why": why, "detail": detail}

    side = read_json(sidecar) if sidecar.exists() else None
    check("process_exit_status",
          side is not None and side.get("return_code") == 0,
          "an acquisition that exited non-zero produced a partial corpus, and a partial "
          "corpus that is silently accepted becomes an endpoint computed over whatever "
          "happened to finish",
          None if side is None else side.get("return_code"))

    receipt = read_json(acquisition) if acquisition.exists() else None
    manifest_data = read_json(manifest)
    receipt_ok = (
        receipt is not None
        and receipt.get("schema") == "tavonel.w6-v3-acquisition.v1"
        and receipt.get("protocol_sha256") == file_sha256(V3_PROTOCOL)
        and receipt.get("acquisition_script_sha256") == file_sha256(V3_SCRIPT)
        and receipt.get("title_manifest_receipt_sha256") == manifest_data.get("receipt_sha256")
        and receipt.get("title_manifest_file_sha256") == file_sha256(manifest)
    )
    check("acquisition_receipt", receipt_ok,
          "the receipt must bind to the protocol bytes, the acquisition script bytes and "
          "the exact holdout title manifest. A receipt that floats free of them describes "
          "some other run",
          None if receipt is None else {
              "schema": receipt.get("schema"),
              "manifest_receipt_matches":
                  receipt.get("title_manifest_receipt_sha256")
                  == manifest_data.get("receipt_sha256")})

    records = (receipt or {}).get("records") or []
    exclusions = (receipt or {}).get("exclusions") or []
    cohorts = (receipt or {}).get("cohorts_completed") or 0
    cohort_size = (receipt or {}).get("cohort_size") or 0
    manifest_titles = [row["title"] for row in manifest_data.get("titles", [])]
    consumed = min(cohorts * cohort_size, len(manifest_titles))
    accounting_ok = (
        receipt is not None
        and len(records) + len(exclusions) == consumed
        and receipt.get("eligible_records") == len(records)
        and receipt.get("excluded_records") == len(exclusions)
    )
    check("accounting_reconciles", accounting_ok,
          "every title the run consumed is either an eligible record or a named exclusion. "
          "A title that is neither has disappeared without a reason, and a corpus with "
          "silent disappearances cannot support a denominator",
          {"records": len(records), "exclusions": len(exclusions),
           "titles_consumed": consumed})

    directories = sorted(p for p in corpus.iterdir() if p.is_dir()) if corpus.exists() else []
    incomplete = [
        d.name for d in directories
        if not ((d / "metadata.json").exists()
                and (d / "before.wikitext").exists()
                and (d / "after.wikitext").exists())
    ]
    check("no_incomplete_directories", not incomplete and bool(directories),
          "metadata.json is written last, so a directory without it is a pair that was "
          "interrupted. corpus-v5 held exactly this defect and reported 0 complete pairs",
          {"directories": len(directories), "incomplete": incomplete[:20],
           "incomplete_count": len(incomplete)})

    indices = [r["manifest_index"] for r in records]
    titles = [normalize_title(r["title"]) for r in records]
    dup_index = sorted({i for i in indices if indices.count(i) > 1})
    dup_title = sorted({t for t in titles if titles.count(t) > 1})
    dup_dir = len(directories) != len({d.name for d in directories})
    check("no_duplicates", not dup_index and not dup_title and not dup_dir,
          "a duplicated pair would be counted twice in the denominator and would let one "
          "article carry two votes in a paired comparison",
          {"duplicate_indices": dup_index[:10], "duplicate_titles": dup_title[:10]})

    late: list[str] = []
    for d in directories:
        meta = d / "metadata.json"
        payloads = [d / "before.wikitext", d / "after.wikitext"]
        # A directory missing any of the three files is already a refusal above.
        # Skipping it here keeps this check about ordering rather than raising,
        # because a crash is not a refusal --- it produces no receipt at all.
        if not meta.exists() or not all(p.exists() for p in payloads):
            continue
        newest_payload = max(p.stat().st_mtime for p in payloads)
        if meta.stat().st_mtime + 1e-6 < newest_payload:
            late.append(d.name)
    check("metadata_written_last", not late,
          "the completeness marker is metadata.json being newer than the wikitext beside "
          "it. If it is older, the pair was rewritten after it was declared complete",
          {"violations": late[:20], "violation_count": len(late)})

    mismatches: list[dict[str, Any]] = []
    missing_files: list[str] = []
    pair_digests: list[str] = []
    for record in records:
        before = EXP / record["relative_before_path"]
        after = EXP / record["relative_after_path"]
        if not before.exists() or not after.exists():
            missing_files.append(record["title"])
            continue
        b, a = file_sha256(before), file_sha256(after)
        if b != record["before_sha256"] or a != record["after_sha256"]:
            mismatches.append({"title": record["title"],
                               "before_matches": b == record["before_sha256"],
                               "after_matches": a == record["after_sha256"]})
        pair_digests.append(canonical_sha256({
            "index": record["manifest_index"],
            "title": normalize_title(record["title"]),
            "before": b, "after": a,
            "before_revision_id": record["before_revision_id"],
            "after_revision_id": record["after_revision_id"]}))
    check("per_pair_hashes_match", not mismatches and not missing_files and bool(records),
          "the bytes the endpoint will read must be the bytes the receipt hashed. Anything "
          "else means the corpus changed after it was recorded",
          {"pairs_verified": len(pair_digests), "mismatches": mismatches[:10],
           "missing_files": missing_files[:10]})

    corpus_root = canonical_sha256(sorted(pair_digests))
    check("corpus_root_hash", bool(pair_digests),
          "one order-independent digest over every verified pair, so the sealed endpoint "
          "can name the corpus it was computed from in a single value",
          corpus_root)

    seal = read_json(SEAL)
    development = {normalize_title(t) for t in
                   (seal.get("development_titles_excluded_from_v8") or {}).get("titles", [])}
    manifest_set = {normalize_title(t) for t in manifest_titles}
    overlap = sorted(set(titles) & development)
    outside = sorted(set(titles) - manifest_set)
    check("untouched_disjointness",
          bool(development) and not overlap and not outside,
          "the holdout is only untouched if no acquired title was seen in development and "
          "no acquired title came from outside the frozen manifest. An empty development "
          "list would make this check inert, so it is itself a failure",
          {"sealed_development_titles": len(development),
           "overlap_with_development": overlap[:20],
           "outside_manifest": outside[:20]})

    failed = [n for n, c in conditions.items() if not c["passes"]]
    return {"conditions": conditions, "failed": failed, "passes": not failed,
            "corpus_root_hash": corpus_root, "pairs_verified": len(pair_digests),
            "eligible_records": len(records), "excluded_records": len(exclusions)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition", type=Path,
                        default=RECEIPTS / "acquisition-v8-holdout.json")
    parser.add_argument("--sidecar", type=Path,
                        default=RECEIPTS / "acquisition-v8-holdout-completion.json")
    parser.add_argument("--corpus", type=Path, default=EXP / "corpus-v8-holdout")
    parser.add_argument("--manifest", type=Path,
                        default=RECEIPTS / "holdout-manifest-v8.json")
    parser.add_argument("--output", type=Path,
                        default=RECEIPTS / "v8-holdout-acquisition-integrity.json")
    args = parser.parse_args()

    result = evaluate(acquisition=args.acquisition, sidecar=args.sidecar,
                      corpus=args.corpus, manifest=args.manifest)
    receipt = {
        "schema": "tavonel.w6-v8-holdout-acquisition-integrity.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "run_class": "HOLDOUT_CONFIRMATORY",
        "acquisition_receipt_sha256":
            file_sha256(args.acquisition) if args.acquisition.exists() else None,
        "holdout_manifest_sha256": file_sha256(args.manifest),
        "external_gpu_cost_usd": 0.0,
        **result,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    def display(value: Any) -> str:
        # Titles are arbitrary Unicode and this console is not. Failure detail
        # must survive the terminal, so it is escaped here rather than lost to a
        # UnicodeEncodeError that would hide which check refused.
        return json.dumps(value, sort_keys=True, ensure_ascii=True)

    for name, condition in result["conditions"].items():
        print(f"  {'PASS' if condition['passes'] else 'FAIL'}  {name}")
        if not condition["passes"]:
            print(f"        {display(condition['detail'])}")
    print(f"pairs verified: {result['pairs_verified']}   "
          f"eligible: {result['eligible_records']}   excluded: {result['excluded_records']}")
    print(f"corpus root: {result['corpus_root_hash']}")
    print(f"integrity gate: {'PASS' if result['passes'] else 'FAIL'}")
    print(f"wrote {args.output}")
    return 0 if result["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
