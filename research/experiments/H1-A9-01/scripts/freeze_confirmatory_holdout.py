#!/usr/bin/env python3
"""Freeze the 800-page confirmatory holdout, and prove it does not leak.

Selection is at the **document** level, not the page level. A page-level random
split would put page 3 and page 4 of the same newspaper on opposite sides, and
those two pages share layout, typography, scan conditions and often content --
a gate tuned on one has seen most of what makes the other hard. Sampling whole
documents removes that channel.

Everything is deterministic: documents are sorted by identity, shuffled with a
fixed seed, and taken in order until the page target is reached. Re-running this
file reproduces the same 800 pages, which is what makes the freeze a freeze.

Four leakage checks run before anything is written, and any failure refuses the
freeze rather than reporting it:

  * page identity overlap with the discovery set;
  * document identity overlap;
  * exact content duplicates, by sha256 of the source image;
  * near duplicates, by difference hash -- a cropped, rescaled or re-scanned
    copy of a discovery page has a different sha256 and would otherwise pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # scanned broadsheets legitimately exceed the default

SEED = 20260818
TARGET_PAGES = 800

# The near-duplicate hash and its threshold are set from measurement, not taste.
#
# A 64-bit (8x8) difference hash was tried first and refused the freeze on 19
# pairs. Diagnosis showed the hash, not the corpus: across 1,770 pairs of
# definitely-unrelated discovery pages the minimum distance was 3 bits and five
# pairs fell within 5, and one holdout page "matched" six mutually unrelated
# discovery pages at once. 64 bits does not separate dense scanned text.
#
# At 256 bits (16x16) the same 19,900 discovery pairs have a minimum distance of
# 25 and nothing at all below 25, while a rescaled copy of a page hashes to
# distance 0 from its original. A threshold of 20 therefore sits strictly
# between "unrelated on this corpus" and "the same image, rescaled", and was
# fixed before the freeze was re-run rather than after seeing whether it passed.
#
# What this does NOT detect: a heavy crop. A 2%-margin crop already lands at 31,
# above the unrelated minimum, so cropped derivatives are not separable by this
# instrument at any threshold. Document-level exclusion is what covers that
# case, since a crop of a discovery page comes from a discovery document.
DIFFERENCE_HASH_SIDE = 16
DIFFERENCE_HASH_BITS = DIFFERENCE_HASH_SIDE**2
NEAR_DUPLICATE_MAX_DISTANCE = 20
MEASURED_UNRELATED_MINIMUM = 25


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def difference_hash(path: Path, side: int = DIFFERENCE_HASH_SIDE) -> int:
    """dHash of `side`x`side`: robust to rescaling and mild recompression."""
    with Image.open(path) as image:
        small = image.convert("L").resize((side + 1, side), Image.LANCZOS)
        pixels = list(small.getdata())
    bits = 0
    for row in range(side):
        offset = row * (side + 1)
        for column in range(side):
            bits <<= 1
            if pixels[offset + column] > pixels[offset + column + 1]:
                bits |= 1
    return bits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--staged-manifest", type=Path, required=True)
    parser.add_argument("--staged-root", type=Path, required=True)
    parser.add_argument("--discovery-inputs", type=Path, required=True)
    parser.add_argument("--discovery-seal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-pages", type=int, default=TARGET_PAGES)
    args = parser.parse_args()

    audit = json.loads(args.audit.resolve().read_text(encoding="utf-8"))
    manifest = json.loads(args.staged_manifest.resolve().read_text(encoding="utf-8"))
    seal = json.loads(args.discovery_seal.resolve().read_text(encoding="utf-8"))

    entry_by_page = {
        Path(entry["source_relative_path"]).name: entry for entry in manifest["inputs"]
    }
    eligible = list(audit["eligible"])
    if len(eligible) < args.target_pages:
        raise SystemExit(
            f"only {len(eligible)} eligible pages, need {args.target_pages}"
        )

    def document_of(page: str) -> str:
        return str(entry_by_page[page]["source_relative_path"]).rsplit("_page_", 1)[0]

    by_document: dict[str, list[str]] = {}
    for page in eligible:
        by_document.setdefault(document_of(page), []).append(page)
    for pages in by_document.values():
        pages.sort()

    documents = sorted(by_document)
    random.Random(SEED).shuffle(documents)  # noqa: S311 - a reproducible split

    selected: list[str] = []
    selected_documents: list[str] = []
    for document in documents:
        if len(selected) >= args.target_pages:
            break
        pages = by_document[document]
        # Taking a whole document keeps the split at document granularity. The
        # last one may overshoot the target; truncating it would reintroduce a
        # page-level cut, so the target is a floor rather than an exact count.
        selected.extend(pages)
        selected_documents.append(document)

    discovery_pages = {str(p["image_path"]) for p in seal["pages"]}
    discovery_pages |= set(seal.get("excluded_without_an_official_page_score", []))
    discovery_documents = {
        document_of(p) for p in discovery_pages if p in entry_by_page
    }

    staged_root = args.staged_root.resolve()
    discovery_root = args.discovery_inputs.resolve()

    # --- leakage checks --------------------------------------------------
    page_overlap = sorted(set(selected) & discovery_pages)
    document_overlap = sorted(set(selected_documents) & discovery_documents)

    discovery_sha = {}
    discovery_dhash = {}
    for path in sorted(discovery_root.glob("*.png")):
        discovery_sha[sha256_file(path)] = path.name
        discovery_dhash[path.name] = difference_hash(path)

    holdout_records: list[dict[str, Any]] = []
    exact_duplicates: list[dict[str, str]] = []
    near_duplicates: list[dict[str, Any]] = []
    for page in selected:
        entry = entry_by_page[page]
        path = staged_root / str(entry["input_relative_path"])
        digest = sha256_file(path)
        bits = difference_hash(path)
        if digest in discovery_sha:
            exact_duplicates.append(
                {"holdout_page": page, "discovery_input": discovery_sha[digest]}
            )
        for name, other in discovery_dhash.items():
            distance = bin(bits ^ other).count("1")
            if distance <= NEAR_DUPLICATE_MAX_DISTANCE:
                near_duplicates.append(
                    {
                        "holdout_page": page,
                        "discovery_input": name,
                        "hamming_distance": distance,
                    }
                )
        holdout_records.append(
            {
                "image_path": page,
                "case_id": entry["case_id"],
                "document_id": document_of(page),
                "input_relative_path": entry["input_relative_path"],
                "input_sha256": digest,
                "difference_hash": f"{bits:016x}",
            }
        )

    refusals = []
    if page_overlap:
        refusals.append(f"{len(page_overlap)} pages overlap the discovery set")
    if document_overlap:
        refusals.append(f"{len(document_overlap)} documents overlap the discovery set")
    if exact_duplicates:
        refusals.append(f"{len(exact_duplicates)} exact content duplicates")
    if near_duplicates:
        refusals.append(f"{len(near_duplicates)} near duplicates")

    receipt = {
        "schema": "tavonel.a9-confirmatory-holdout.v1",
        "status": "REFUSED" if refusals else "FROZEN",
        "frozen_on": "2026-08-18",
        "seed": SEED,
        "selection": (
            "documents sorted by identity, shuffled with the fixed seed, taken "
            "whole and in order until the page target is reached"
        ),
        "target_pages": args.target_pages,
        "page_count": len(holdout_records),
        "document_count": len(selected_documents),
        "eligible_pool_pages": len(eligible),
        "eligible_pool_documents": len(by_document),
        "leakage_checks": {
            "page_identity_overlap": len(page_overlap),
            "document_identity_overlap": len(document_overlap),
            "exact_content_duplicates": len(exact_duplicates),
            "near_duplicates_within_threshold": len(near_duplicates),
            "near_duplicate_examples": near_duplicates[:10],
            "difference_hash_bits": DIFFERENCE_HASH_BITS,
            "near_duplicate_threshold": NEAR_DUPLICATE_MAX_DISTANCE,
            "measured_minimum_distance_between_unrelated_discovery_pages": (
                MEASURED_UNRELATED_MINIMUM
            ),
            "threshold_basis": (
                "set below the measured minimum over all 19,900 discovery pairs "
                "and above the distance of 0 for a rescaled copy; a heavy crop "
                "is not detectable by this instrument and is covered by the "
                "document-level exclusion instead"
            ),
        },
        "refusals": refusals,
        "documents": sorted(selected_documents),
        "pages": sorted(holdout_records, key=lambda r: r["image_path"]),
    }
    body = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(body, encoding="utf-8")

    print(f"status: {receipt['status']}")
    print(f"pages: {len(holdout_records)} across {len(selected_documents)} documents")
    print(f"eligible pool: {len(eligible)} pages / {len(by_document)} documents")
    for key, value in receipt["leakage_checks"].items():
        if isinstance(value, int):
            print(f"  {key}: {value}")
    for refusal in refusals:
        print(f"  REFUSED: {refusal}")
    print(f"manifest sha256: {hashlib.sha256(body.encode('utf-8')).hexdigest()}")
    print(f"receipt: {args.output.resolve()}")
    return 1 if refusals else 0


if __name__ == "__main__":
    raise SystemExit(main())
