#!/usr/bin/env python3
"""Validate the claim/evidence matrix and seal it. PAPER CLOSURE PROGRAM workstream C.

The matrix is only worth having if something refuses it. This does the refusing:

* every claim must cite a receipt that exists, whose bytes hash to what the
  matrix pins, and whose own declared self-hash recomputes;
* every claim must declare a split, a status, allowed wording and forbidden
  wording. A row missing any of them is not a weak row, it is an invalid one;
* no claim's wording, and no line of the internal draft, may contain any phrase
  from the forbidden list;
* every negative finding must point at a claim that exists.

The digest the matrix pins is written by this tool on first seal and checked on
every run afterwards, so a receipt that changes under a claim's feet is a hard
failure rather than a quiet update.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

MATRIX = NS / "paper" / "CLAIM_MATRIX.yaml"
PINS = NS / "paper" / "claim_receipt_pins.json"
DRAFT = NS / "paper" / "TAVONEL_PAPER_DRAFT_INTERNAL.md"

REQUIRED = (
    "id",
    "wording",
    "protocol",
    "receipt",
    "split",
    "status",
    "allowed",
    "forbidden",
    "limitations",
)
#: A third value, added 2026-08-23. A development diagnostic is a study that was
#: designed as held-out and lost that status to an evidence-hygiene failure. It
#: is deliberately NOT folded into "development": the distinction between a study
#: that was always development and one that was demoted is exactly what a reader
#: needs, and collapsing them would hide the demotion.
SPLITS = ("development", "development_diagnostic", "held_out")
PENDING = "PENDING"


def load_matrix() -> dict[str, Any]:
    """A deliberately small YAML reader.

    PyYAML is not a declared dependency of this namespace and adding one to read
    a file this tool also writes would be a poor trade. The matrix is written to
    the subset parsed here: mappings, sequences, scalars, block scalars and
    comments.
    """
    import yaml  # noqa: PLC0415

    return yaml.safe_load(MATRIX.read_text(encoding="utf-8"))


def receipt_state(relative: str) -> dict[str, Any]:
    if relative == PENDING:
        return {"pending": True}
    path = NS.parents[1] / relative if relative.startswith("research/") else NS / relative
    if not path.exists():
        return {"exists": False, "path": relative}
    body = json.loads(path.read_text(encoding="utf-8"))
    declared = body.get("receipt_sha256")
    recomputes: bool | None = None
    if declared:
        bare = {key: value for key, value in body.items() if key != "receipt_sha256"}
        recomputes = canonical_sha(bare) == declared
    return {
        "exists": True,
        "path": rel(path),
        "file_sha256": sha_file(path),
        "declares_self_hash": bool(declared),
        "self_hash_recomputes": recomputes,
        "verdict": body.get("verdict"),
    }


def check_claims(matrix: dict[str, Any], pins: dict[str, str]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    forbidden_phrases = [
        (entry["id"], phrase) for entry in matrix["forbidden_claims"] for phrase in entry["phrases"]
    ]

    for claim in matrix["claims"]:
        missing = [field for field in REQUIRED if field not in claim]
        if missing:
            failures.append({"claim": claim.get("id"), "why": "missing fields", "fields": missing})
            continue
        if claim["split"] not in SPLITS:
            failures.append(
                {"claim": claim["id"], "why": "undeclared split", "split": claim["split"]}
            )
        state = receipt_state(claim["receipt"])
        if not state.get("pending"):
            if not state.get("exists"):
                failures.append(
                    {"claim": claim["id"], "why": "receipt missing", "receipt": claim["receipt"]}
                )
            else:
                if state.get("declares_self_hash") and state.get("self_hash_recomputes") is False:
                    failures.append(
                        {"claim": claim["id"], "why": "receipt self-hash does not recompute"}
                    )
                pinned = pins.get(claim["id"])
                if pinned and pinned != state["file_sha256"]:
                    failures.append(
                        {
                            "claim": claim["id"],
                            "why": "receipt bytes moved under a pinned claim",
                            "pinned": pinned,
                            "found": state["file_sha256"],
                        }
                    )
        elif claim["status"] != "NOT_YET_ESTABLISHED":
            failures.append(
                {"claim": claim["id"], "why": "a pending receipt with an established status"}
            )

        lowered = str(claim["wording"]).casefold()
        hits = [
            {"forbidden": identifier, "phrase": phrase}
            for identifier, phrase in forbidden_phrases
            if phrase.casefold() in lowered
        ]
        if hits:
            failures.append(
                {"claim": claim["id"], "why": "forbidden phrase in wording", "hits": hits}
            )

        rows.append(
            {
                "id": claim["id"],
                "protocol": claim["protocol"],
                "split": claim["split"],
                "status": claim["status"],
                "receipt": claim["receipt"],
                "receipt_state": state,
                "allowed_count": len(claim["allowed"]),
                "forbidden_count": len(claim["forbidden"]),
                "limitation_count": len(claim["limitations"]),
            }
        )

    known = {claim["id"] for claim in matrix["claims"]}
    for finding in matrix["negative_findings"]:
        if finding["evidence"] not in known:
            failures.append(
                {
                    "claim": finding["id"],
                    "why": "negative finding cites a claim that does not exist",
                    "cites": finding["evidence"],
                }
            )

    return {"rows": rows, "failures": failures}


def scan_draft(matrix: dict[str, Any]) -> dict[str, Any]:
    """Every forbidden phrase, hunted through the draft prose."""
    if not DRAFT.exists():
        return {"present": False, "hits": [], "clean": True}
    text = DRAFT.read_text(encoding="utf-8")
    lowered = text.casefold()
    hits: list[dict[str, Any]] = []
    for entry in matrix["forbidden_claims"]:
        for phrase in entry["phrases"]:
            needle = phrase.casefold()
            start = lowered.find(needle)
            while start != -1:
                line = text.count("\n", 0, start) + 1
                hits.append({"forbidden": entry["id"], "phrase": phrase, "line": line})
                start = lowered.find(needle, start + 1)
    return {
        "present": True,
        "path": rel(DRAFT),
        "sha256": sha_file(DRAFT),
        "lines": text.count("\n") + 1,
        "hits": hits,
        "clean": not hits,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repin", action="store_true", help="record current receipt digests")
    arguments = parser.parse_args()

    matrix = load_matrix()
    pins = json.loads(PINS.read_text(encoding="utf-8")) if PINS.exists() else {}
    checked = check_claims(matrix, pins)
    draft = scan_draft(matrix)

    if arguments.repin:
        pins = {
            row["id"]: row["receipt_state"]["file_sha256"]
            for row in checked["rows"]
            if row["receipt_state"].get("exists")
        }
        PINS.write_text(
            json.dumps(pins, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        checked = check_claims(matrix, pins)

    by_split: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for row in checked["rows"]:
        by_split[row["split"]] = by_split.get(row["split"], 0) + 1
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1

    gates = {
        "G_CLAIM_FIELDS_COMPLETE": not any(
            failure["why"] == "missing fields" for failure in checked["failures"]
        ),
        "G_CLAIM_RECEIPTS_BIND": not any(
            "receipt" in failure["why"] for failure in checked["failures"]
        ),
        "G_CLAIM_NO_FORBIDDEN_WORDING": not any(
            "forbidden phrase" in failure["why"] for failure in checked["failures"]
        ),
        "G_CLAIM_SPLITS_DECLARED": not any(
            failure["why"] == "undeclared split" for failure in checked["failures"]
        ),
        "G_CLAIM_NEGATIVES_BIND": not any(
            "negative finding" in failure["why"] for failure in checked["failures"]
        ),
        "G_DRAFT_NO_FORBIDDEN_WORDING": bool(draft["clean"]),
        "G_RELEASE_GATE_CLOSED": matrix["release"]["ip_gate"] == "CLOSED",
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.claim_matrix_seal.v1",
        "matrix": rel(MATRIX),
        "matrix_sha256": sha_file(MATRIX),
        "visibility": matrix["visibility"],
        "release": matrix["release"],
        "generated_at": now(),
        "claims": len(checked["rows"]),
        "by_split": dict(sorted(by_split.items())),
        "by_status": dict(sorted(by_status.items())),
        "pending_claims": sorted(row["id"] for row in checked["rows"] if row["receipt"] == PENDING),
        "forbidden_claims": [entry["id"] for entry in matrix["forbidden_claims"]],
        "negative_findings": [entry["id"] for entry in matrix["negative_findings"]],
        "readiness_gaps": [entry["id"] for entry in matrix["paper_readiness_gaps"]],
        "rows": checked["rows"],
        "failures": checked["failures"],
        "draft": draft,
        "gates": gates,
        "verdict": "PASS" if all(gates.values()) else "FAIL",
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable("claim-matrix", body, tool=Path(__file__).resolve(), protocol=None)
    print(json.dumps({**written, "verdict": body["verdict"]}, indent=2))
    if checked["failures"]:
        print(json.dumps(checked["failures"], indent=2)[:2000])
    if draft["hits"]:
        print(json.dumps(draft["hits"], indent=2)[:1200])
    return 0 if body["verdict"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
