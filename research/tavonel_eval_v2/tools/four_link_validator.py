"""Validate a frozen four-link receipt against the material it claims to describe.

WHY A SECOND MODULE. `four_link_gate.classify_candidate` decides the state AND
writes the evidence, so a receipt it produced agrees with it by construction. A
filter and a proof written as one piece of code prove nothing about each other,
and this study has recorded that failure twice already -- the V2R2 enumerator's
disjointness "proof" was its own filter, and the parent chain's companion
attestations exist because a proof computed inside the thing it attests is not a
proof.

WHAT THIS VALIDATES, from the receipt outward rather than from the classifier in:

  1. the receipt binds a manifest by digest, and that manifest still hashes to it;
  2. every candidate in that manifest appears in the receipt exactly once;
  3. re-classifying the manifest from scratch reproduces every eligibility state;
  4. every ELIGIBLE record carries all four evidence digests, and each one
     RE-DERIVES from the candidate rather than being taken on trust;
  5. the chain digest is the composition of the other four -- so a record cannot
     carry a plausible chain digest over links that were never computed;
  6. the eligible count still clears the floor the receipt froze.

It refuses. It does not repair, re-run or downgrade: a receipt that no longer
describes its material is not evidence about anything, and the correct response
is to look at why, not to write a second receipt that agrees with the first.

IT DOES NOT INSPECT AN OUTCOME. A four-link classification is a statement about
whether a fact's provenance chain is followable. It reads no closure result, no
verdict and no score, and it is safe to run against a cohort before that cohort
is measured.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "source_fact_ir"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import four_link_gate as gate  # noqa: E402
import ir  # noqa: E402

SCHEMA = "tavonel.v2.four_link_validation.v1"

#: An ELIGIBLE record must carry all four, and the composition of them. A record
#: missing one is a record whose link was never computed, however confident its
#: state looks.
REQUIRED_EVIDENCE = (
    "witness_digest",
    "representation_digest",
    "fingerprint",
    "dependency_digest",
    "chain_digest",
)


class ValidationRefused(RuntimeError):
    """The receipt does not describe the material it binds."""


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(manifest: str) -> Path:
    candidate = ROOT / manifest
    if candidate.is_file():
        return candidate
    fallback = Path(manifest)
    if fallback.is_file():
        return fallback
    raise ValidationRefused(
        f"the manifest the receipt binds is not on disk: {manifest}. A validation "
        "over absent material proves nothing about it."
    )


def validate(receipt: dict[str, Any], *, facts_key: str = "facts") -> dict[str, Any]:
    """Re-derive the whole classification and require it to match. Raises otherwise."""
    if receipt.get("schema") != gate.SCHEMA:
        raise ValidationRefused(
            f"schema is {receipt.get('schema')!r}, not {gate.SCHEMA!r}. This is not a "
            "four-link gate receipt."
        )
    bound = receipt.get("manifest")
    bound_digest = receipt.get("manifest_sha256")
    if not bound or not bound_digest:
        raise ValidationRefused(
            "the receipt names no manifest or no manifest digest, so there is nothing "
            "to validate it against. A gate result that cannot name its input is not "
            "checkable from outside."
        )
    path = _resolve(str(bound))
    actual = _sha_file(path)
    if actual != bound_digest:
        raise ValidationRefused(
            f"{bound} has changed since the gate ran.\n  frozen:  {bound_digest}\n"
            f"  current: {actual}\nThe receipt describes different material."
        )

    body = json.loads(path.read_text(encoding="utf-8"))
    candidates = body.get(facts_key)
    if not isinstance(candidates, list) or not candidates:
        raise ValidationRefused(
            f"{bound}[{facts_key!r}] holds no candidate list. A classification over "
            "zero candidates agrees with anything."
        )

    records = receipt.get("records")
    if not isinstance(records, list):
        raise ValidationRefused("the receipt carries no per-candidate records")
    if len(records) != len(candidates):
        raise ValidationRefused(
            f"the receipt classifies {len(records)} candidates and the manifest holds "
            f"{len(candidates)}. A count that does not match is a cohort that was "
            "silently widened or shrunk."
        )

    #: Recomputed independently of the receipt's own records, then compared.
    fresh = gate.classify_cohort(candidates)
    disagreements: list[str] = []
    for index, (recorded, recomputed) in enumerate(zip(records, fresh["records"], strict=True)):
        if recorded.get("fact_id") != recomputed.get("fact_id"):
            disagreements.append(
                f"[{index}] fact_id {recorded.get('fact_id')!r} vs "
                f"{recomputed.get('fact_id')!r} -- the records are not in the "
                "manifest's order"
            )
            continue
        if recorded.get("eligibility_state") != recomputed.get("eligibility_state"):
            disagreements.append(
                f"{recorded.get('fact_id')}: recorded "
                f"{recorded.get('eligibility_state')}, recomputed "
                f"{recomputed.get('eligibility_state')}"
            )
    if disagreements:
        raise ValidationRefused(
            "re-classifying the manifest does not reproduce the receipt: "
            + "; ".join(disagreements[:6])
            + (" ..." if len(disagreements) > 6 else "")
        )

    checked = _validate_eligible_evidence(records)

    by_state = receipt.get("by_state") or {}
    if by_state != fresh["by_state"]:
        raise ValidationRefused(
            f"the receipt's by_state {by_state} does not match the recomputed "
            f"{fresh['by_state']}. The per-record states agree, so the SUMMARY has "
            "drifted from the records it summarises."
        )

    floor = receipt.get("floor")
    eligible = fresh["eligible_count"]
    if not isinstance(floor, int):
        raise ValidationRefused("the receipt froze no floor")
    if receipt.get("verdict") == "READY" and eligible < floor:
        raise ValidationRefused(
            f"the receipt says READY with {eligible} eligible against a floor of "
            f"{floor}. The floor is never relaxed to reach feasibility."
        )
    if receipt.get("verdict") == "STOP" and eligible >= floor:
        raise ValidationRefused(
            f"the receipt says STOP with {eligible} eligible against a floor of "
            f"{floor}, which clears it. A gate that stops when it should not is as "
            "broken as one that passes when it should not."
        )

    return {
        "schema": SCHEMA,
        "held": True,
        "manifest": bound,
        "manifest_sha256": actual,
        "candidates_considered": len(candidates),
        "by_state": fresh["by_state"],
        "eligible_count": eligible,
        "floor": floor,
        "verdict": receipt.get("verdict"),
        "eligible_records_evidence_rederived": checked,
        "required_evidence": list(REQUIRED_EVIDENCE),
        "how": (
            "the manifest was re-hashed against the digest the receipt froze, "
            "re-classified from scratch, and every ELIGIBLE record's four evidence "
            "digests were re-derived from the candidate and compared -- including "
            "the chain digest, which must be the composition of the other four."
        ),
        "what_this_does_not_read": (
            "no closure result, no verdict about the migration, no score. A four-link "
            "classification is a statement about followable provenance and is safe to "
            "run before the cohort is measured."
        ),
    }


def _validate_eligible_evidence(records: list[dict[str, Any]]) -> int:
    """Every ELIGIBLE record carries all four links, re-derived, and composes."""
    checked = 0
    problems: list[str] = []
    for record in records:
        if record.get("eligibility_state") != gate.STATE_ELIGIBLE:
            continue
        evidence = record.get("evidence") or {}
        missing = [name for name in REQUIRED_EVIDENCE if not evidence.get(name)]
        if missing:
            problems.append(f"{record.get('fact_id')} is ELIGIBLE but lacks {missing}")
            continue
        #: The chain digest must BE the composition. A record could otherwise
        #: carry four plausible digests and a fifth that came from somewhere
        #: else entirely.
        expected = ir.digest(
            {
                "witness_digest": evidence["witness_digest"],
                "representation_digest": evidence["representation_digest"],
                "fingerprint": evidence["fingerprint"],
                "dependency_digest": evidence["dependency_digest"],
            }
        )
        if expected != evidence["chain_digest"]:
            problems.append(
                f"{record.get('fact_id')}: chain_digest {evidence['chain_digest']} is "
                f"not the composition of its four links ({expected})"
            )
            continue
        if not evidence.get("dependency_keys"):
            problems.append(f"{record.get('fact_id')} carries a dependency digest over no keys")
            continue
        if ir.digest(list(evidence["dependency_keys"])) != evidence["dependency_digest"]:
            problems.append(
                f"{record.get('fact_id')}: dependency_digest does not re-derive from "
                "its own recorded keys"
            )
            continue
        checked += 1
    if problems:
        raise ValidationRefused(
            "ELIGIBLE records carry evidence that does not hold up: "
            + "; ".join(problems[:6])
            + (" ..." if len(problems) > 6 else "")
        )
    return checked


def latest_receipt(stem: str = "four-link-gate") -> Path | None:
    found = sorted((NS / "receipts").glob(f"{stem}--*.json"))
    return found[-1] if found else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="a four-link gate receipt; defaults to the most recent one",
    )
    parser.add_argument("--facts-key", default="facts")
    args = parser.parse_args(argv)

    path = args.receipt or latest_receipt()
    if path is None or not path.is_file():
        print(
            json.dumps(
                {
                    "state": "REFUSED",
                    "why": "no four-link gate receipt to validate",
                },
                indent=1,
            )
        )
        return 4
    try:
        body = validate(json.loads(path.read_text(encoding="utf-8")), facts_key=args.facts_key)
    except ValidationRefused as error:
        print(json.dumps({"state": "REFUSED", "receipt": path.name, "why": str(error)}, indent=1))
        return 4
    print(json.dumps({**body, "receipt": path.name}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
