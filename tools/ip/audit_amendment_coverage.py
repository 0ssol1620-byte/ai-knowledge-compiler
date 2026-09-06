#!/usr/bin/env python3
"""Is the amendment register complete, and does every entry land on a real claim?

`audit_claim_amendments.py` answers a different question: given the amendments on
file, is each one's recorded direction consistent with its operation? It found
four broadenings recorded as narrowings and is clean now. But it can only be as
complete as the register, and a register is a record someone chose to write.

Two gaps it cannot see:

**An amendment against a claim that does not exist.** `B-SPECIFICITY-WITHDRAWN`
is registered against claim `B-ranking`. No claim in the set carries that
identifier -- the ranking elements are recited inside a numbered claim. A
withdrawal that cannot be located to a claim cannot be checked against the claim
text, and its direction verdict is about nothing.

**A claim amended with no entry at all.** The claim set is git-ignored, so there
is no prior revision to diff against.

That exclusion is a control, not an oversight. `docs/ip/.gitignore` is a
fail-closed allowlist under a founder instruction of 2026-08-11: everything in
the directory is ignored unless named, because the risk being managed is the
claim chart nobody thought to add. Tracking the claim set to make this audit
easier would put privileged claim-level material into version control, which is
the wrong trade and is not this tool's call to make.

So the register is checked against a **hash chain** instead. Each amendment
records the claim set's sha256 before and after it. If the file on disk does not
match the last recorded `after`, the file changed outside the register, and this
audit says so -- without any claim text leaving the ignored directory, since a
digest is not content.

The chain detects change from its baseline forward. It reconstructs nothing
before that, and claims without a determination are reported UNDETERMINED, never
"unamended" -- absence of a record is not evidence of absence.

The honest output is a coverage figure with its denominator, not a clean flag.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLAIM_SET = ROOT / "docs" / "ip" / "PATENT_CLAIM_SET_v1_2026-08-19.md"
AMENDMENTS = ROOT / "docs" / "ip" / "CLAIM_AMENDMENTS.yaml"
MATRIX = ROOT / "docs" / "ip" / "claim-evidence-matrix.yaml"
OUTPUT = ROOT / "docs" / "ip" / "receipts" / "amendment-coverage-2026-08-19.json"

HEADING = re.compile(r"^#{2,4}\s+Claim\s+([AB]\d+)\b(.*)$", re.M)


def claim_inventory(text: str) -> list[dict[str, Any]]:
    out = []
    for m in HEADING.finditer(text):
        tail = m.group(2)
        out.append({
            "id": m.group(1),
            "kind": "independent" if "independent" in tail else (
                "dependent" if "dependent" in tail else "unspecified"),
            "reserved": "RESERVED" in tail or "NOT SUPPORTED" in tail,
            "heading": (m.group(0)).strip("# ").strip(),
        })
    return out


def chain_state(last: str | None, current: str) -> str:
    if not last:
        return "NO_BASELINE"
    return "INTACT" if last == current else "BROKEN"


def chain_control(current: str) -> dict[str, Any]:
    """Run the real state function over the three inputs it must separate.

    Asserting `current == current` would be a control that cannot fail, which is
    the defect this programme keeps finding in its own detectors. This calls the
    same function the audit calls.
    """
    altered = "sha256:" + "0" * 64
    results = {
        "matching_digest": chain_state(current, current),
        "altered_digest": chain_state(altered, current),
        "absent_baseline": chain_state(None, current),
    }
    return {
        "separates": results == {
            "matching_digest": "INTACT",
            "altered_digest": "BROKEN",
            "absent_baseline": "NO_BASELINE",
        },
        "results": results,
        "what_it_proves": (
            "the same state function the audit uses returns three distinct states for a "
            "matching digest, a differing digest and no baseline at all"
        ),
        "what_it_does_not_prove": (
            "nothing about edits made before the baseline was pinned, which is the larger "
            "and permanently unrecoverable gap"
        ),
    }


def main() -> int:
    claim_text = CLAIM_SET.read_text(encoding="utf-8")
    claims = claim_inventory(claim_text)
    known = {c["id"] for c in claims}

    reg = yaml.safe_load(AMENDMENTS.read_text(encoding="utf-8")) or {}
    amendments = reg.get("amendments") or []
    aliases: dict[str, str] = reg.get("claim_aliases") or {}

    findings: list[dict[str, Any]] = []
    per_claim: dict[str, list[str]] = {c["id"]: [] for c in claims}
    unresolvable: list[dict[str, Any]] = []

    for a in amendments:
        aid, raw = a.get("id"), str(a.get("claim"))
        target = aliases.get(raw, raw)
        if target in known:
            per_claim[target].append(aid)
            continue
        unresolvable.append({"amendment": aid, "recorded_claim": raw,
                             "resolved_to": target if target != raw else None})
        findings.append({
            "kind": "AMENDMENT_TARGETS_UNKNOWN_CLAIM",
            "amendment": aid, "recorded_claim": raw,
            "why": (
                f"no claim in the set carries the identifier {raw!r}. Its direction verdict "
                "cannot be checked against claim text, and a reader cannot find what was "
                "amended. Either the claim id is wrong or the amendment names an element "
                "inside a numbered claim, which needs a claim_aliases entry saying which."
            ),
            "known_claims": sorted(known),
        })

    determinations = []
    for c in claims:
        entries = per_claim[c["id"]]
        if entries:
            state = "AMENDED_AND_REGISTERED"
        elif c["reserved"]:
            state = "RESERVED_NOT_PROSECUTED"
        else:
            state = "UNDETERMINED"
        determinations.append({**c, "amendments": entries, "coverage": state})
        if state == "UNDETERMINED":
            findings.append({
                "kind": "CLAIM_AMENDMENT_HISTORY_UNDETERMINED",
                "claim": c["id"],
                "why": (
                    "no amendment is registered against this claim, and the claim set is "
                    "untracked in git, so there is no prior revision to diff. Whether it was "
                    "never amended or amended without a record cannot be distinguished from "
                    "the repository as it stands."
                ),
                "severity": "MAJOR_FOR_COMPLETENESS_CLAIMS_ONLY",
                "what_it_does_not_mean": (
                    "not an assertion that the claim was amended, and not a defect in the "
                    "claim. It bounds what may be said about coverage."
                ),
            })

    covered = sum(1 for d in determinations if d["coverage"] == "AMENDED_AND_REGISTERED")
    reserved = sum(1 for d in determinations if d["coverage"] == "RESERVED_NOT_PROSECUTED")
    undetermined = sum(1 for d in determinations if d["coverage"] == "UNDETERMINED")

    matrix = yaml.safe_load(MATRIX.read_text(encoding="utf-8")) or {}
    evidence_claims = matrix.get("claims") or []

    control = self_control(known, aliases)

    # Hash chain: the register's last recorded post-amendment digest must equal
    # the file on disk. A mismatch means the claim set changed outside the
    # register -- the only detection available while the file is deliberately
    # git-ignored.
    current = "sha256:" + hashlib.sha256(CLAIM_SET.read_bytes()).hexdigest()
    baseline = reg.get("claim_set_baseline") or {}
    with_hashes = [a for a in amendments if a.get("claim_set_sha256_after")]
    last = with_hashes[-1].get("claim_set_sha256_after") if with_hashes else (
        baseline.get("sha256"))
    chain = {
        "current_claim_set_sha256": current,
        "last_recorded_sha256": last,
        "baseline": baseline or None,
        "amendments_carrying_hashes": len(with_hashes),
        "state": chain_state(last, current),
        "what_broken_would_mean": (
            "the claim set changed without an amendment entry, or an entry was written "
            "without updating the digest. Both are register defects and neither is "
            "distinguishable from the other by this check alone."
        ),
        "control": chain_control(current),
    }
    if chain["state"] == "BROKEN":
        findings.append({
            "kind": "CLAIM_SET_CHANGED_OUTSIDE_REGISTER",
            "recorded": last, "on_disk": current,
            "why": chain["what_broken_would_mean"],
        })
    elif chain["state"] == "NO_BASELINE":
        findings.append({
            "kind": "CLAIM_SET_HASH_CHAIN_NOT_ESTABLISHED",
            "why": (
                "no baseline digest and no amendment carries one, so an edit made outside "
                "the register is undetectable. This is the state the chain exists to end."
            ),
        })

    receipt: dict[str, Any] = {
        "schema": "tavonel.amendment-coverage.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "claim_set": CLAIM_SET.relative_to(ROOT).as_posix(),
        "claim_set_sha256": "sha256:" + hashlib.sha256(CLAIM_SET.read_bytes()).hexdigest(),
        "claim_set_tracked_in_git": False,
        "why_untracked": (
            "docs/ip/.gitignore is a fail-closed allowlist under a founder instruction of "
            "2026-08-11. The claim set is privileged claim-level material and is excluded "
            "deliberately. This is a control being honoured, not a gap to close."
        ),
        "hash_chain": chain,
        "namespaces": {
            "patent_claims": len(claims),
            "evidence_claims": len(evidence_claims),
            "note": (
                "These are two inventories, not one. The claim set recites "
                f"{len(claims)} numbered patent claims (A1-A3, B1-B10). The "
                f"claim-evidence matrix carries {len(evidence_claims)} evidence claims with "
                "their own identifiers. 'All 21 claims' refers to the evidence namespace; "
                "amendment direction is a property of the patent namespace. Reporting one "
                "count as coverage of the other would overstate both."
            ),
        },
        "claims": determinations,
        "amendments_registered": len(amendments),
        "amendments_unresolvable": unresolvable,
        "coverage": {
            "amended_and_registered": covered,
            "reserved_not_prosecuted": reserved,
            "undetermined": undetermined,
            "denominator": len(claims),
        },
        "coverage_is_complete": undetermined == 0,
        "why_completeness_is_not_claimable_today": (
            "Coverage over the patent namespace is bounded by the register's own "
            "completeness. The hash chain makes a future unregistered edit detectable; it "
            "says nothing about edits made before the baseline was pinned."
        ),
        "remedy": (
            "Record claim_set_sha256_before and _after on every amendment, so an edit made "
            "outside the register breaks the chain. This keeps the claim set inside the "
            "fail-closed ignore allowlist -- a digest is not claim text -- and does not "
            "weaken a privilege control to make an audit greener. It cannot reconstruct "
            "history before the baseline, and does not claim it will."
        ),
        "detector_control": control,
        "detector_is_live": control["separates"],
        "findings": findings,
        "finding_count": len(findings),
        "state": (
            "NOT_RUN" if not control["separates"]
            else ("CLEAN" if not findings else "FINDINGS")
        ),
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"patent claims: {len(claims)}   evidence claims: {len(evidence_claims)}")
    print(f"coverage: registered={covered} reserved={reserved} undetermined={undetermined} "
          f"of {len(claims)}")
    print(f"control separates: {control['separates']}")
    for f in findings[:30]:
        print(f"  {f['kind']:<40} {f.get('claim') or f.get('amendment')}")
    print(f"findings: {len(findings)}  state: {receipt['state']}")
    print(f"wrote {OUTPUT.relative_to(ROOT).as_posix()}")
    return 0 if receipt["state"] == "CLEAN" else 1


def self_control(known: set[str], aliases: dict[str, str]) -> dict[str, Any]:
    """An unresolvable target must be caught; a resolvable one must not be.

    Without this, an empty `amendments_unresolvable` list means either that every
    entry lands on a real claim or that the resolver silently accepted anything.
    """
    probe = [
        {"id": "CONTROL-BAD", "claim": "Z99-DOES-NOT-EXIST"},
        {"id": "CONTROL-GOOD", "claim": next(iter(sorted(known)))},
    ]
    caught = [a for a in probe if aliases.get(str(a["claim"]), str(a["claim"])) not in known]
    return {
        "separates": len(caught) == 1 and caught[0]["id"] == "CONTROL-BAD",
        "unknown_target_caught": any(a["id"] == "CONTROL-BAD" for a in caught),
        "known_target_passed": not any(a["id"] == "CONTROL-GOOD" for a in caught),
        "what_it_proves": (
            "the resolver rejects an amendment whose claim identifier is absent from the "
            "claim set and accepts one that is present"
        ),
        "what_it_does_not_prove": (
            "nothing about amendments that were never written down, which is the larger gap "
            "and is not detectable while the claim set is untracked"
        ),
    }


if __name__ == "__main__":
    sys.exit(main())
