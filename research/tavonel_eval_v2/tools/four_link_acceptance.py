"""FOUR_LINK_ACCEPTANCE_V1 — INC-V2-034 authorization for one exact cohort.

WHY A HISTORICAL GATE RECEIPT IS NOT AUTHORIZATION. `four_link_gate` has a green
receipt over 20,018 eligible records, and `four_link_validator` independently
re-derived every one of their four link digests and held. That is good evidence
and it is preserved. It is not permission to spend GPU time, because it answers a
question about *a* manifest and the question that matters is:

    is the manifest that receipt binds EXACTLY the manifest
    GPU_SUCCESSOR_STUDY_V1 is about to run?

Nothing about a receipt being green makes it about the right cohort. So the
acceptance binds the successor manifest by digest, re-checks that digest against
disk, and -- when the launcher supplies the manifest it is actually about to run
-- requires the two to be byte-identical. A green receipt over a different
manifest is refused, not reused.

WHAT IT CHECKS, none of it inherited from the gate's own opinion of itself:

    the manifest still hashes to what was accepted;
    the gate receipt still hashes to what was accepted, and binds that manifest;
    the gate's verdict is READY;
    the INDEPENDENT validator, re-run now, reproduces the gate's classification
      and re-derives every ELIGIBLE record's four link digests;
    every candidate carries exactly one of the six eligibility states;
    the eligible count clears the floor, and the floor is the declared GPU
      successor floor rather than whatever the receipt happened to record.

NO RESULT-BASED FILTERING. The classification is over every candidate in the
manifest. There is no path here that drops a candidate because of how it
classified, and `_require_total_classification` refuses a receipt whose record
count does not match the manifest's -- which is what a silent drop would look
like from outside.
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
for _sub in ("tools", "source_fact_ir"):
    _path = str(NS / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
if str(NS) not in sys.path:
    sys.path.insert(0, str(NS))

import four_link_gate as gate  # noqa: E402
import four_link_validator as validator  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402
import build_successor_cohort as successor  # noqa: E402
from evidence import ReceiptExists, write_immutable  # noqa: E402

SCHEMA = "tavonel.v2.four_link_acceptance.v1"
STEM = "four-link-acceptance"
AUTHORITY_RUN_ID = "FOUR_LINK_ACCEPTANCE_V1"

#: The floor comes from the GPU study's own declaration, not from the gate
#: receipt. A receipt that recorded its own floor could record a lower one, and
#: the acceptance would then be checking the cohort against a bar the cohort
#: brought with it.
ACCEPTED_FLOOR = gsp.COHORT_FLOOR

#: Exactly these six, and every candidate lands in exactly one. Imported from the
#: gate so a state added there is a change here rather than a silent widening.
ELIGIBILITY_STATES = gate.ELIGIBILITY_STATES

REQUIRED_BINDINGS = (
    "manifest",
    "manifest_sha256",
    "gate_receipt",
    "gate_receipt_sha256",
    "facts_key",
    "eligible_count",
    "floor",
)


class AcceptanceRefused(RuntimeError):
    """The four-link chain does not authorize this cohort."""


def _require_successor_universe(manifest: dict[str, Any]) -> None:
    provenance = manifest.get("provenance") or {}
    if manifest.get("schema") != successor.MANIFEST_SCHEMA:
        raise AcceptanceRefused("the manifest is not a successor candidate universe")
    if provenance.get("receipt_stem") != successor.RECEIPT_STEM:
        raise AcceptanceRefused(
            "the manifest is not the immutable SFI3 successor-universe authority"
        )
    if provenance.get("run_id") != successor.AUTHORITY_RUN_ID or not provenance.get("immutable"):
        raise AcceptanceRefused("the successor universe is not the single immutable authority")
    source = manifest.get("source_sfi3_acceptance") or {}
    if source.get("protocol_id") != "SOURCE_FACT_IR_HELDOUT_V3" or source.get("verdict") != "PASS":
        raise AcceptanceRefused("the successor universe is not bound to an SFI3 PASS")


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(relative: str) -> Path:
    candidate = ROOT / relative
    if candidate.is_file():
        return candidate
    plain = Path(relative)
    if plain.is_file():
        return plain
    raise AcceptanceRefused(
        f"the acceptance names {relative!r}, which is not on disk. An acceptance "
        "over absent material proves nothing about it."
    )


def _require_total_classification(
    records: list[dict[str, Any]], candidates: list[Any]
) -> dict[str, int]:
    """Every candidate classified, into exactly one of the six states.

    A count that does not match the manifest is what a silently dropped
    candidate looks like from outside, and dropping the ones that classified
    badly is the exact shape of result-based filtering this gate exists to
    forbid.
    """
    if len(records) != len(candidates):
        raise AcceptanceRefused(
            f"the gate classified {len(records)} candidates and the manifest holds "
            f"{len(candidates)}. A cohort that was silently widened or narrowed is "
            "not the cohort that was gated."
        )
    counts = dict.fromkeys(ELIGIBILITY_STATES, 0)
    for index, record in enumerate(records):
        state = record.get("eligibility_state")
        if state not in counts:
            raise AcceptanceRefused(
                f"record {index} ({record.get('fact_id')!r}) reports "
                f"{state!r}, which is not one of the six eligibility states"
            )
        counts[state] += 1
    if sum(counts.values()) != len(records):
        raise AcceptanceRefused("a record was counted into more than one state")
    return counts


def verify(
    acceptance: dict[str, Any],
    *,
    launch_manifest_sha256: str | None = None,
    require_authority: bool = True,
) -> dict[str, Any]:
    """Re-check every binding, and re-run the independent validator now.

    `launch_manifest_sha256` is the digest of the manifest the caller is about to
    run. When supplied it MUST equal the accepted manifest's digest -- that is
    the whole question a historical green receipt cannot answer.
    """
    if acceptance.get("schema") != SCHEMA:
        raise AcceptanceRefused(
            f"schema is {acceptance.get('schema')!r}, not {SCHEMA!r}; this is not a "
            "four-link acceptance"
        )
    if require_authority:
        provenance = acceptance.get("provenance") or {}
        if (
            provenance.get("receipt_stem") != STEM
            or provenance.get("run_id") != AUTHORITY_RUN_ID
            or not provenance.get("immutable")
        ):
            raise AcceptanceRefused(
                "the named acceptance is not the single immutable four-link authority"
            )
    missing = [field for field in REQUIRED_BINDINGS if acceptance.get(field) in (None, "")]
    if missing:
        raise AcceptanceRefused(f"the acceptance carries no {missing}")

    manifest_path = _resolve(str(acceptance["manifest"]))
    manifest_digest = _sha_file(manifest_path)
    if manifest_digest != acceptance["manifest_sha256"]:
        raise AcceptanceRefused(
            f"{manifest_path.name} has changed since it was accepted.\n"
            f"  accepted: {acceptance['manifest_sha256']}\n  current:  {manifest_digest}"
        )
    if launch_manifest_sha256 is not None and launch_manifest_sha256 != manifest_digest:
        raise AcceptanceRefused(
            "the accepted cohort is not the cohort about to run.\n"
            f"  accepted: {manifest_digest}\n  launching: {launch_manifest_sha256}\n"
            "A green four-link receipt over a different manifest authorizes nothing "
            "about this one."
        )
    manifest_body = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require_successor_universe(manifest_body)

    gate_path = _resolve(str(acceptance["gate_receipt"]))
    gate_digest = _sha_file(gate_path)
    if gate_digest != acceptance["gate_receipt_sha256"]:
        raise AcceptanceRefused(
            f"{gate_path.name} has changed since it was accepted.\n"
            f"  accepted: {acceptance['gate_receipt_sha256']}\n  current:  {gate_digest}"
        )
    receipt = json.loads(gate_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != gate.SCHEMA:
        raise AcceptanceRefused(
            f"the named receipt is {receipt.get('schema')!r}, not a four-link gate result"
        )
    if receipt.get("manifest_sha256") != manifest_digest:
        raise AcceptanceRefused(
            "the gate receipt was produced over a different manifest than this "
            f"acceptance names.\n  receipt:   {receipt.get('manifest_sha256')}\n"
            f"  accepted:  {manifest_digest}"
        )
    if receipt.get("verdict") != "READY":
        raise AcceptanceRefused(f"the gate verdict is {receipt.get('verdict')!r}, not READY")

    #: Re-run NOW, not read from a stored validator result. A validator output
    #: recorded beside the gate is a claim about a check; running it is the
    #: check. This is also the classifier/validator agreement clause: `validate`
    #: re-classifies the manifest from scratch and refuses on any disagreement.
    try:
        validation = validator.validate(receipt, facts_key=str(acceptance["facts_key"]))
    except validator.ValidationRefused as error:
        raise AcceptanceRefused(
            f"the independent validator does not confirm the gate: {error}"
        ) from error

    candidates = gate._load_candidates(manifest_path, str(acceptance["facts_key"]))
    if not candidates:
        raise AcceptanceRefused(
            f"{manifest_path.name}[{acceptance['facts_key']!r}] holds no candidates. A "
            "classification over zero agrees with anything."
        )
    counts = _require_total_classification(receipt.get("records") or [], candidates)

    eligible = counts[gate.STATE_ELIGIBLE]
    if eligible != validation["eligible_count"]:
        raise AcceptanceRefused(
            f"the gate counts {eligible} eligible and the validator {validation['eligible_count']}"
        )
    if acceptance["eligible_count"] != eligible:
        raise AcceptanceRefused(
            f"the acceptance records {acceptance['eligible_count']} eligible and the "
            f"gate reports {eligible}"
        )
    if acceptance["floor"] != ACCEPTED_FLOOR or receipt.get("floor") != ACCEPTED_FLOOR:
        raise AcceptanceRefused(
            f"the floor is {acceptance['floor']} in the acceptance and "
            f"{receipt.get('floor')} in the gate receipt, against the declared GPU "
            f"successor floor of {ACCEPTED_FLOOR}. The floor is never relaxed to "
            "reach feasibility, and it is never taken from the artifact being gated."
        )
    if eligible < ACCEPTED_FLOOR:
        raise AcceptanceRefused(f"{eligible} eligible against a floor of {ACCEPTED_FLOOR}")

    return {
        "schema": SCHEMA,
        "held": True,
        "manifest": acceptance["manifest"],
        "manifest_sha256": manifest_digest,
        "gate_receipt": acceptance["gate_receipt"],
        "gate_receipt_sha256": gate_digest,
        "facts_key": acceptance["facts_key"],
        "verdict": "READY",
        "candidates_considered": len(candidates),
        "by_state": counts,
        "eligible_count": eligible,
        "floor": ACCEPTED_FLOOR,
        "floor_source": "gpu_successor_preflight.COHORT_FLOOR",
        "validator": {
            "schema": validation["schema"],
            "eligible_records_evidence_rederived": validation[
                "eligible_records_evidence_rederived"
            ],
            "required_evidence": validation["required_evidence"],
            "agrees_with_classifier": True,
        },
        "eligibility_states": list(ELIGIBILITY_STATES),
        "every_candidate_classified_once": True,
        "no_result_based_filtering": (
            "the classification covers every candidate in the manifest; a record "
            "count that did not match would be refused, which is what a candidate "
            "dropped for how it classified would look like from outside"
        ),
        "why_a_historical_receipt_is_not_enough": (
            "a green gate receipt answers a question about the manifest it was run "
            "over. The launcher supplies the digest of the manifest it is about to "
            "run, and the two must be byte-identical."
        ),
    }


def build(manifest: Path, gate_receipt: Path, *, facts_key: str = "facts") -> dict[str, Any]:
    """Draft an acceptance and verify it before returning. Never returns a claim."""
    receipt = json.loads(gate_receipt.read_text(encoding="utf-8"))

    def relative(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            return str(path)

    draft = {
        "schema": SCHEMA,
        "manifest": relative(manifest),
        "manifest_sha256": _sha_file(manifest),
        "gate_receipt": relative(gate_receipt),
        "gate_receipt_sha256": _sha_file(gate_receipt),
        "facts_key": facts_key,
        "eligible_count": (receipt.get("by_state") or {}).get(gate.STATE_ELIGIBLE),
        "floor": receipt.get("floor"),
    }
    verify(draft, require_authority=False)
    return draft


def seal(manifest: Path, gate_receipt: Path, *, facts_key: str = "facts") -> dict[str, str]:
    """Seal the sole four-link authority for the sole SFI3 successor universe."""
    body = build(manifest, gate_receipt, facts_key=facts_key)
    try:
        return write_immutable(
            STEM,
            body,
            tool=Path(__file__).resolve(),
            protocol=None,
            run_id=AUTHORITY_RUN_ID,
            pointer=False,
        )
    except ReceiptExists as error:
        raise AcceptanceRefused(
            "the four-link acceptance authority already exists; a second is forbidden"
        ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--gate-receipt", type=Path, default=None)
    parser.add_argument("--acceptance", type=Path, default=None)
    parser.add_argument("--facts-key", default="facts")
    parser.add_argument(
        "--launch-manifest-sha256",
        default=None,
        help="the digest of the manifest about to run; must equal the accepted one",
    )
    args = parser.parse_args(argv)
    try:
        if args.manifest is not None and args.gate_receipt is not None:
            print(
                json.dumps(
                    seal(args.manifest, args.gate_receipt, facts_key=args.facts_key),
                    indent=1,
                    sort_keys=True,
                )
            )
            return 0
        if args.acceptance is None or not args.acceptance.is_file():
            print(
                json.dumps(
                    {
                        "state": "REFUSED",
                        "why": (
                            "name an acceptance explicitly with --acceptance, or build "
                            "one with --manifest and --gate-receipt. There is no "
                            "default and no search."
                        ),
                    },
                    indent=1,
                )
            )
            return 4
        body = verify(
            json.loads(args.acceptance.read_text(encoding="utf-8")),
            launch_manifest_sha256=args.launch_manifest_sha256,
        )
        print(json.dumps({**body, "receipt": args.acceptance.name}, indent=1, sort_keys=True))
        return 0
    except AcceptanceRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
