#!/usr/bin/env python3
"""PHASE 5 -- check every load-bearing number in the paper against a live receipt.

A number that was right when it was written and is wrong now is the commonest
form of stale narrative, and it is invisible to the claim-evidence matrix: the
matrix verifies the *registry* against receipts, not the *prose*.

Method. A table of expected values is declared here, each bound to a receipt
path and a JSON pointer (or to a computed quantity). The tool resolves each from
disk, then checks the manuscript, abstract, figures and claim set actually
contain the resolved value where they discuss it. A mismatch is a finding.

Deliberate scope limit: this checks the numbers named below, not every digit in
the document. Claiming otherwise would be the same overclaim this programme
keeps catching, so the receipt records exactly which quantities were audited.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DOCS = {
    "manuscript": ROOT / "docs" / "paper" / "MANUSCRIPT_v1_2026-08-19.md",
    "figures": ROOT / "docs" / "paper" / "FIGURES_2026-08-19.md",
    "tables": ROOT / "docs" / "paper" / "TABLES_2026-08-19.md",
    "claim_set": ROOT / "docs" / "ip" / "PATENT_CLAIM_SET_v1_2026-08-19.md",
    "specification": ROOT / "docs" / "ip" / "PATENT_SPECIFICATION_v1_2026-08-19.md",
}

E = "research/experiments"
H1L = f"{E}/H1-L-CERTIFIED-SPARSE-MATCHER-01/receipts"
H1J = f"{E}/H1-J-GOVERNANCE-FILTER-ABLATION-01/receipts"

#: (label, receipt path, json pointer or None, transform) -> expected value.
#: `None` pointer means the value is computed by `COMPUTED` below.
BINDINGS: list[dict[str, Any]] = [
    {
        "label": "H1-I total evaluations",
        "receipt": f"{E}/H1-I-GATE-ORDERING-01/receipts/gate-ordering-permutation-2026-08-19.json",
        "pointer": "/total_evaluations",
        "expect_in": ["manuscript", "claim_set"],
    },
    {
        "label": "H1-I verdict divergences",
        "receipt": f"{E}/H1-I-GATE-ORDERING-01/receipts/gate-ordering-permutation-2026-08-19.json",
        "pointer": "/E1_verdict_divergence_count",
        "expect_in": [],
    },
    {
        "label": "H1-I positive control divergent orders",
        "receipt": f"{E}/H1-I-GATE-ORDERING-01/receipts/gate-ordering-permutation-2026-08-19.json",
        "pointer": "/positive_control/divergence_count",
        "expect_in": ["manuscript", "claim_set"],
    },
    {
        "label": "H1-L comparisons",
        "receipt": f"{E}/H1-L-CERTIFIED-SPARSE-MATCHER-01/receipts/exactness-2026-08-19.json",
        "pointer": "/comparisons",
        "expect_in": [],
    },
    {
        "label": "H1-L primary divergences",
        "receipt": f"{E}/H1-L-CERTIFIED-SPARSE-MATCHER-01/receipts/exactness-2026-08-19.json",
        "pointer": "/primary_divergences",
        "expect_in": [],
    },
    {
        "label": "H1-L h1e-topology comparisons",
        "receipt": f"{H1L}/h1e-topology-exactness-2026-08-19.json",
        "pointer": "/total_comparisons",
        "expect_in": ["tables"],
    },
    {
        "label": "H1-L h1e-topology divergences",
        "receipt": f"{H1L}/h1e-topology-exactness-2026-08-19.json",
        "pointer": "/total_divergences",
        "expect_in": [],
    },
    {
        "label": "H1-J filters evaluated",
        "receipt": f"{H1J}/governance-filter-ablation-2026-08-19.json",
        "pointer": "/filters_evaluated",
        "transform": "len",
        "expect_in": ["tables"],
    },
    {
        "label": "H1-J uncitable filters",
        "receipt": f"{H1J}/governance-filter-ablation-2026-08-19.json",
        "pointer": "/uncitable_filters",
        "transform": "len",
        "expect_in": [],
    },
]

#: Quantities computed from the package rather than read from one receipt.
COMPUTED = {
    "experiment count": lambda: _manifest()["experiment_count"],
    "receipt count": lambda: _manifest()["receipt_count"],
}

#: Computed quantities the manuscript states explicitly and must keep in sync.
#: These drift every time a receipt is added, which is exactly why they are
#: enforced rather than trusted.
COMPUTED_REQUIRED_IN = {
    "experiment count": ["manuscript"],
    "receipt count": ["manuscript"],
}


MANIFEST_PATH = ROOT / "docs" / "repro" / "EXPERIMENT_MANIFEST.json"


def _manifest() -> dict[str, Any]:
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    exps = m.get("experiments", [])
    n_exp = len(exps) if isinstance(exps, list) else m.get("experiment_count", 0)
    n_rec = sum(len(e.get("receipts", [])) for e in exps) if isinstance(exps, list) else 0
    return {"experiment_count": n_exp, "receipt_count": n_rec}


def manifest_staleness() -> dict[str, Any]:
    """Is the manifest older than the receipts it claims to inventory?

    The computed quantities above are read from the manifest, not from disk, so a
    manifest that has not been rebuilt makes this audit agree with the prose while
    both are wrong. That is not hypothetical: adding two receipts left the audit
    green on a count of 133 when disk held 135, and it went green again only
    because the manifest happened to be rebuilt by hand.

    A cheap and correctly-directed check: any receipt file newer than the manifest
    means the manifest cannot be trusted. It can report a false alarm after a
    touch that changed nothing, which is the safe direction to be wrong in.
    """
    if not MANIFEST_PATH.exists():
        return {"stale": True, "why": "manifest missing", "newer_receipts": []}
    manifest_mtime = MANIFEST_PATH.stat().st_mtime
    newer = [
        str(r.relative_to(ROOT)).replace("\\", "/")
        for r in (ROOT / "research" / "experiments").glob("*/receipts/*")
        if r.is_file() and r.stat().st_mtime > manifest_mtime
    ]
    return {
        "stale": bool(newer),
        "why": "receipt files are newer than the manifest" if newer else "up to date",
        "newer_receipts": sorted(newer)[:20],
        "newer_receipt_count": len(newer),
    }


def resolve(document: Any, pointer: str) -> Any:
    node = document
    for raw in pointer.lstrip("/").split("/"):
        if raw == "":
            continue
        token = raw.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def contains_number(text: str, value: Any) -> bool:
    """Is this value present as a standalone number (comma grouping allowed)?"""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    s = str(value)
    plain = re.escape(s)
    grouped = re.escape(f"{int(s):,}") if s.isdigit() else plain
    return bool(re.search(rf"(?<![\d.]){plain}(?![\d])", text)) or bool(
        re.search(rf"(?<![\d.]){grouped}(?![\d])", text)
    )


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    texts = {k: (p.read_text(encoding="utf-8") if p.exists() else "") for k, p in DOCS.items()}
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    stale = manifest_staleness()
    if stale["stale"]:
        findings.append(
            {
                "label": "experiment manifest",
                "problem": (
                    "manifest is stale -- computed counts are read from it, so this audit "
                    "cannot vouch for them. Run tools/repro/build_experiment_manifest.py first."
                ),
                "detail": stale,
            }
        )

    for b in BINDINGS:
        path = ROOT / b["receipt"]
        if not path.exists():
            findings.append({"label": b["label"], "problem": "receipt missing",
                             "receipt": b["receipt"]})
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        val = resolve(doc, b["pointer"])
        if b.get("transform") == "len":
            val = len(val)
        row = {"label": b["label"], "receipt": b["receipt"], "pointer": b["pointer"],
               "value": val, "present_in": {}}
        for name, text in texts.items():
            row["present_in"][name] = contains_number(text, val)
        for required in b.get("expect_in", []):
            if not row["present_in"].get(required):
                findings.append(
                    {"label": b["label"], "problem": f"value {val} not found in {required}",
                     "receipt": b["receipt"]}
                )
        rows.append(row)

    computed_rows = []
    for label, fn in COMPUTED.items():
        try:
            val = fn()
        except Exception as exc:
            findings.append({"label": label, "problem": f"could not compute: {exc!r}"})
            continue
        present = {n: contains_number(t, val) for n, t in texts.items()}
        for required in COMPUTED_REQUIRED_IN.get(label, []):
            if not present.get(required):
                findings.append(
                    {"label": label,
                     "problem": f"computed value {val} not found in {required}"}
                )
        computed_rows.append({"label": label, "value": val, "present_in": present})

    receipt: dict[str, Any] = {
        "schema": "tavonel.manuscript-number-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Bind load-bearing numbers in the paper and patent prose to live "
            "receipts. The claim-evidence matrix verifies the registry against "
            "receipts; it does not verify the prose."
        ),
        "documents": {k: str(v.relative_to(ROOT)).replace("\\", "/") for k, v in DOCS.items()},
        "bound_quantities": rows,
        "computed_quantities": computed_rows,
        "manifest_staleness": stale,
        "findings": findings,
        "finding_count": len(findings),
        "clean": not findings,
        "scope_limit": (
            "Only the quantities listed in this tool are audited. It does not "
            "check every digit in the documents, and does not claim to."
        ),
        "quantities_audited": len(rows) + len(computed_rows),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out = ROOT / "docs" / "ip" / "receipts" / "manuscript-number-audit-2026-08-19.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for r in rows + computed_rows:
        where = ",".join(k for k, v in r["present_in"].items() if v) or "-"
        print(f"  {r['label']:<40} = {r['value']!s:<8} in: {where}")
    print(f"findings: {len(findings)}")
    for f in findings:
        print(f"  ! {f['label']}: {f['problem']}")
    print(f"wrote {out}")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
