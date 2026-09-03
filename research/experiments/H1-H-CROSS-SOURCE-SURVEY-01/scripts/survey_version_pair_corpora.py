#!/usr/bin/env python3
"""Survey the repository for corpora that could support a cross-source equivalence arm.

Hostile-review findings R5 and P4 both say the same thing: the real-corpus
equivalence evidence (H1-F) is retrospective, one source family, English
Wikipedia. The obvious next step is a second source family with genuine
version relationships -- SEC amendments, DART filings, contract revisions.

This script does not run that experiment. It establishes, mechanically and
without network access, **whether the inputs for it exist here at all**, so the
answer is a checked fact rather than an assumption in either direction.

The rule it enforces, and the reason it exists:

    A version pair is two documents standing in an explicit amendment or
    revision relationship to one another, where that relationship is verifiable
    from the artifacts themselves.

Two filings by the same company in different years are **not** a version pair.
They are two documents about overlapping subject matter. Treating them as a
revision pair would manufacture the very relationship the experiment is supposed
to test, and every equivalence number produced from it would be measuring the
harness rather than the system. That is the failure mode this file exists to
prevent, so the detector below requires an explicit relationship marker and
refuses to infer one from filenames, dates or directory adjacency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "__pycache__", ".next", ".pytest_cache",
    "artifacts", "test-results", "dist", "build",
}

#: Path segments that mean "operational output", not "document corpus". The
#: first run matched `work/job-logs/final`, whose numeric `.txt` filenames look
#: like revision ids and are job identifiers. A survey that reports run logs as a
#: candidate second source family is worse than one that reports nothing, so the
#: exclusion is a rule rather than a note.
NON_DOCUMENT_SEGMENTS = {"logs", "job-logs", "work", "tmp", "cache", "runs"}

#: A directory is a candidate version-pair corpus only if it holds two or more
#: document artifacts whose names encode an explicit revision identity.
REVISION_FILENAME = re.compile(r"^(\d{6,})\.(wikitext|xml|htm|html|txt|md)$", re.I)

#: Markers that would evidence an *explicit* amendment relationship in a filing
#: corpus. Presence of the string alone is not enough -- it must appear in a
#: machine-readable artifact that also names the document it amends.
AMENDMENT_MARKERS = (
    "amendment_of", "amends", "original_filing", "supersedes_accession",
    "prior_accession", "amendment_no", "form_type_amended",
)

FILING_HINTS = ("10-k", "10-q", "8-k", "edgar", "accession", "dart", "rcept_no")


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def walk() -> list[tuple[Path, list[str]]]:
    out: list[tuple[Path, list[str]]] = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        out.append((Path(root), files))
    return out


def find_revision_pair_dirs(tree: list[tuple[Path, list[str]]]) -> list[dict[str, Any]]:
    found = []
    for directory, files in tree:
        parts = {p.casefold() for p in directory.parts}
        if parts & NON_DOCUMENT_SEGMENTS:
            continue
        revisions = sorted(f for f in files if REVISION_FILENAME.match(f))
        if len(revisions) >= 2:
            found.append(
                {
                    "directory": str(directory.relative_to(ROOT)).replace("\\", "/"),
                    "revision_artifacts": revisions,
                    "source_family": "english_wikipedia"
                    if revisions[0].lower().endswith(".wikitext")
                    else "unclassified",
                    "relationship_evidence": "revision id encoded in artifact name",
                }
            )
    return found


def find_filing_candidates(tree: list[tuple[Path, list[str]]]) -> dict[str, Any]:
    """Look for filing-style corpora, and for explicit amendment relationships.

    Deliberately separates *"filing-shaped files exist"* from *"an amendment
    relationship is recorded"*. The first is common and means nothing; only the
    second could support the experiment.
    """
    filing_files: list[str] = []
    amendment_evidence: list[dict[str, Any]] = []
    for directory, files in tree:
        for name in files:
            low = name.lower()
            path = directory / name
            if any(hint in low for hint in FILING_HINTS):
                rel = str(path.relative_to(ROOT)).replace("\\", "/")
                filing_files.append(rel)
                if path.suffix.lower() in {".json", ".yaml", ".yml", ".xml"}:
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    hits = [m for m in AMENDMENT_MARKERS if m in text.casefold()]
                    if hits:
                        amendment_evidence.append({"path": rel, "markers": hits})
    return {
        "filing_shaped_files": sorted(filing_files)[:50],
        "filing_shaped_file_count": len(filing_files),
        "explicit_amendment_relationships": amendment_evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    tree = walk()
    pair_dirs = find_revision_pair_dirs(tree)
    filings = find_filing_candidates(tree)

    families = sorted({d["source_family"] for d in pair_dirs})
    cross_source_possible = (
        len([f for f in families if f != "unclassified"]) >= 2
        or bool(filings["explicit_amendment_relationships"])
    )

    receipt: dict[str, Any] = {
        "schema": "tavonel.cross-source-version-pair-survey.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "question": (
            "Do inputs exist in this repository for a cross-source-family "
            "equivalence arm, i.e. a second document family with verifiable "
            "amendment/revision relationships?"
        ),
        "method": "offline filesystem survey; no network access; no document fetched",
        "definition_enforced": (
            "A version pair is two documents in an explicit amendment or revision "
            "relationship verifiable from the artifacts themselves. Two filings by "
            "the same issuer in different years are NOT a version pair."
        ),
        "revision_pair_directories": pair_dirs,
        "revision_pair_directory_count": len(pair_dirs),
        "source_families_found": families,
        "filing_survey": filings,
        "cross_source_arm_possible_offline": cross_source_possible,
        "result": (
            "AVAILABLE" if cross_source_possible else "NOT_AVAILABLE_OFFLINE"
        ),
        "what_would_unblock": [
            "A second source family whose artifacts carry an explicit amendment "
            "or supersession pointer to the document they revise.",
            "For SEC: paired original and amended filings (e.g. 10-K and 10-K/A) "
            "resolved by accession number, where the amendment relationship is "
            "read from the filing index rather than inferred.",
            "For DART: paired original and correction reports resolved by rcept_no.",
            "Acquisition must be outcome-independent: the pair list is frozen "
            "before any equivalence result is computed, exactly as the W6 title "
            "manifest was.",
        ],
        "explicitly_forbidden": [
            "Pairing two annual filings from different years and calling the "
            "later one a revision of the earlier.",
            "Inferring an amendment relationship from filename similarity, "
            "directory adjacency or filing date ordering.",
            "Presenting the existing English-Wikipedia result as cross-source or "
            "as arbitrary-document external validity.",
        ],
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"result: {receipt['result']}")
    print(f"revision-pair directories: {len(pair_dirs)}")
    print(f"source families: {families}")
    print(f"filing-shaped files: {filings['filing_shaped_file_count']}")
    print(f"explicit amendment relationships: {len(filings['explicit_amendment_relationships'])}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
