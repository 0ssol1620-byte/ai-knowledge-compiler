#!/usr/bin/env python3
"""Check that every claim amendment's direction on scope is stated correctly.

E4: three B1 amendments were recorded as changes that "shorten or weaken the
independent claim". Two of them removed limitations. **Removing a limitation from
a claim broadens it** -- it becomes easier to infringe and harder to allow over
prior art. The reasons behind those amendments were sound; the accounting was
backwards, and backwards accounting hides where a claim now needs support.

Direction is not a matter of judgement, so it is not left to one. It is derived
from the mechanical operation by the fixed table below, and a register entry that
asserts a different direction is a finding.

Two checks:

1. **Derived direction.** Every amendment's direction comes from its operation.
   The register may not assert one.
2. **Prose direction.** Sentences in the claim set and specification that
   describe a removal while using narrowing vocabulary -- the literal E4 defect,
   caught in text rather than in a table.

`--self-test` runs the positive control.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "ip" / "CLAIM_AMENDMENTS.yaml"

DOCS = {
    "claim_set": ROOT / "docs" / "ip" / "PATENT_CLAIM_SET_v1_2026-08-19.md",
    "specification": ROOT / "docs" / "ip" / "PATENT_SPECIFICATION_v1_2026-08-19.md",
    "examiner_red_team": ROOT / "docs" / "ip" / "EXAMINER_RED_TEAM_2026-08-19.md",
}

#: The fixed table. This is the whole point of the tool: direction is derived,
#: never asserted.
DIRECTION = {
    "ADDED_LIMITATION": "NARROWED",
    "REMOVED_LIMITATION": "BROADENED",
    "REPLACED_NARROWER": "NARROWED",
    "REPLACED_BROADER": "BROADENED",
    "REPHRASED_EQUIVALENT": "UNCHANGED",
    "DEPENDENCY_CHANGED": "SCOPE_UNCERTAIN",
    "CLAIM_ADDED": "NO_EFFECT_ON_EXISTING_SCOPE",
    "CLAIM_WITHDRAWN": "NO_EFFECT_ON_REMAINING_SCOPE",
}

REMOVAL = re.compile(
    r"\b(struck|removed|dropped|deleted|moved (?:out of|to)|no longer requires?|"
    r"withdrawn from)\b",
    re.I,
)
#: "restrict" is deliberately absent. In this portfolio it names a *thing* -- the
#: restricted candidate set -- rather than a direction of scope, so it matched the
#: very sentence recording that the restriction was struck. A direction word must
#: describe the amendment, not the subject matter the amendment acts on.
NARROWING = re.compile(
    r"\b(narrow(?:s|ed|ing)?|shorten(?:s|ed|ing)?|weaken(?:s|ed|ing)?|"
    r"tighten(?:s|ed|ing)?)\b",
    re.I,
)
#: Passages that discuss the error itself, or the tool re-reports E4 forever.
META = re.compile(
    r"(E4\b|broaden|correction|corrected|was wrong|backwards|"
    r"removing a limitation|direction on scope)",
    re.I,
)

SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*`\"'])")


def load_register() -> list[dict[str, Any]]:
    if not REGISTER.exists():
        return []
    return (yaml.safe_load(REGISTER.read_text(encoding="utf-8")) or {}).get("amendments") or []


def check_register(amendments) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings, resolved = [], []
    for a in amendments:
        op = a.get("operation")
        if op not in DIRECTION:
            findings.append(
                {"kind": "UNKNOWN_OPERATION", "amendment": a.get("id"), "operation": op,
                 "why": "operation is not in the fixed table, so no direction can be derived"}
            )
            continue
        derived = DIRECTION[op]
        if "direction" in a and a["direction"] != derived:
            findings.append(
                {"kind": "ASSERTED_DIRECTION_CONTRADICTS_OPERATION",
                 "amendment": a.get("id"), "operation": op,
                 "asserted": a["direction"], "derived": derived,
                 "why": "direction is derived from the operation and may not be asserted"}
            )
        resolved.append(
            {"id": a.get("id"), "claim": a.get("claim"), "element": a.get("element"),
             "operation": op, "direction": derived,
             "counsel_flag": bool(a.get("counsel_flag")),
             "counsel_question": a.get("counsel_question")}
        )
    return findings, resolved


def scan_prose(name: str, text: str) -> list[dict[str, Any]]:
    findings = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "|", "```")):
            continue
        for sentence in SENTENCE.split(line):
            s = sentence.strip()
            if not s or META.search(s):
                continue
            rem, nar = REMOVAL.search(s), NARROWING.search(s)
            if rem and nar:
                findings.append(
                    {"kind": "REMOVAL_DESCRIBED_AS_NARROWING", "document": name,
                     "line": lineno, "removal_term": rem.group(0),
                     "narrowing_term": nar.group(0), "sentence": s[:300],
                     "why": ("removing a limitation broadens a claim. If this sentence "
                             "means something else, say which limitation was added.")}
                )
    return findings


def self_test() -> dict[str, Any]:
    bad = scan_prose("__control__", 'The word was struck, which narrows the claim.')
    good = scan_prose("__control__", "A limitation was added, which narrows the claim.")
    reg_bad, _ = check_register(
        [{"id": "__control__", "operation": "REMOVED_LIMITATION", "direction": "NARROWED"}]
    )
    reg_good, _ = check_register([{"id": "__control__", "operation": "REMOVED_LIMITATION"}])
    return {
        "prose_defect_detected": bool(bad),
        "prose_clean_passes": not good,
        "register_contradiction_detected": any(
            f["kind"] == "ASSERTED_DIRECTION_CONTRADICTS_OPERATION" for f in reg_bad
        ),
        "register_clean_passes": not reg_good,
        "separates": bool(bad) and not good and bool(reg_bad) and not reg_good,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    control = self_test()
    amendments = load_register()
    findings, resolved = check_register(amendments)
    if not args.self_test:
        for name, path in DOCS.items():
            if path.exists():
                findings += scan_prose(name, path.read_text(encoding="utf-8"))

    counts: dict[str, int] = {}
    for r in resolved:
        counts[r["direction"]] = counts.get(r["direction"], 0) + 1

    receipt: dict[str, Any] = {
        "schema": "tavonel.claim-amendment-direction-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "closes": (
            "E4 -- two of three B1 amendments removed limitations and were recorded as "
            "narrowings. Direction is now derived from the operation, never asserted."
        ),
        "direction_table": DIRECTION,
        "amendments_registered": len(amendments),
        "resolved_directions": resolved,
        "direction_counts": counts,
        "counsel_flagged": [r["id"] for r in resolved if r["counsel_flag"]],
        "positive_control": control,
        "detector_is_live": control["separates"],
        "findings": findings,
        "finding_count": len(findings),
        "clean": not findings,
        "scope_limitation": (
            "Direction only. Whether an amendment was strategically correct is prosecution "
            "strategy and is not decided here; entries needing that judgement carry a "
            "counsel_flag."
        ),
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    out = ROOT / "docs" / "ip" / "receipts" / "claim-amendment-direction-2026-08-19.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"detector live: {control['separates']}")
    print(f"amendments registered: {len(amendments)}")
    for direction, n in sorted(counts.items()):
        print(f"  {direction:<32} {n}")
    print(f"counsel-flagged: {len(receipt['counsel_flagged'])} "
          f"({', '.join(receipt['counsel_flagged'])})")
    print(f"findings: {len(findings)}")
    for f in findings[:15]:
        print(f"  ! {f['kind']} {f.get('amendment') or f.get('document')}:{f.get('line', '')}")
        print(f"      {f.get('sentence', f.get('why'))[:150]}")
    return 0 if control["separates"] else 1


if __name__ == "__main__":
    sys.exit(main())
