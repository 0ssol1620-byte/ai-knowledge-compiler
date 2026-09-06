"""SOURCE_FACT_IR_HELDOUT_ACCEPTANCE_V1 — the one artifact that says SFI3 passed.

WHY THIS EXISTS. `gpu_successor_preflight.HELD_OUT_STUDY_STEM` was
`"sfi2-native-provenance"`, and SFI2 is frozen, FAIL, spent and permanently
non-rescorable. An SFI2 PASS requirement is structurally impossible, so it was
never the intended live authorization path -- it is a stale implementation
binding that outlived the study it named.

WHY A STRING REPLACEMENT WOULD NOT HAVE DONE. The launcher assumed SFI2's
acceptance semantics: seven endpoints, every one `MET`. SFI3 does not work that
way and squeezing it into that shape would corrupt the verdict:

    nine endpoints are declared
    E1-E7 and E9 are the PASS-contributing primaries
    E8 is a MANDATORY SAFETY VETO and is never `MET`

E8's clean state is `VETO_CLEAR_NO_POSITIVE_CREDIT`. Requiring `MET` of it would
fail every honest SFI3 run; treating its clean zero as positive evidence would
manufacture credit from an instrument that could not have fired. Its seam is
structurally closed, so it has no natural gate power on any natural cohort -- and
a violation vetoes the study outright regardless of the other eight.

WHAT THIS MODULE IS. The single implementation of "did SFI3 pass". The GPU
preflight and the GPU launcher both consume THIS, by explicit path and digest,
and neither re-derives endpoint arithmetic of its own. Two implementations of an
acceptance rule are two rules.

WHAT IT REFUSES TO DO. It never searches. There is no stem glob, no `latest`, no
newest-wins, and no implicit predecessor selection: the acceptance names its
measurement by path, run id and sha256, and every one of those is re-checked
against disk. Replacing one ambiguous stem lookup with another would have moved
the defect rather than closed it.
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
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    _path = str(NS / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
if str(NS) not in sys.path:
    sys.path.insert(0, str(NS))

import score_sfi3  # noqa: E402
from common import canonical_sha, now, sha_file  # noqa: E402
from evidence import SCHEMA as IMMUTABLE_ENVELOPE_SCHEMA  # noqa: E402

SCHEMA = "tavonel.v2.source_fact_ir_heldout_acceptance.v1"
STEM = "sfi3-acceptance"
AUTHORITY_NAME = "sfi3-acceptance-authority.json"
AUTHORITY_PATH = NS / "receipts" / AUTHORITY_NAME

ACCEPTED_PROTOCOL_ID = "SOURCE_FACT_IR_HELDOUT_V3"
#: Imported, never restated. A literal here and a literal in the scorer are two
#: schema ids, and the one that is not emitted is the one that drifts.
MEASUREMENT_SCHEMA = score_sfi3.RESULT_SCHEMA
REQUIRED_SPLIT = "held_out"

#: Every field the acceptance must carry before a single clause is evaluated.
#: Listed rather than checked ad hoc so an acceptance that simply omits a binding
#: is refused for the omission instead of passing the clauses it did carry.
REQUIRED_BINDINGS = (
    "protocol_id",
    "protocol",
    "protocol_sha256",
    "protocol_freeze_receipt",
    "protocol_freeze_run_id",
    "protocol_freeze_sha256",
    "measurement_receipt",
    "measurement_run_id",
    "measurement_sha256",
    "acquisition",
    "acquisition_sha256",
)

#: Taken from the scorer, never restated. `PRIMARY_ENDPOINTS` is E1-E7 + E9;
#: `SAFETY_VETO_ENDPOINT` is E8; `MAY_NOT_BE_SKIPPED` is E5, E6, E9. A copy of
#: any of these here would be a second acceptance rule that could drift from the
#: one the study was actually scored under.
PRIMARY_ENDPOINTS = score_sfi3.PRIMARY_ENDPOINTS
VETO_ENDPOINT = score_sfi3.SAFETY_VETO_ENDPOINT
VETO_CLEAR = score_sfi3.VETO_CLEAR
MUST_BE_EXERCISED = score_sfi3.MAY_NOT_BE_SKIPPED
STAGES_REQUIRED = score_sfi3.STAGES_REQUIRED
COHORT_FLOOR_PAIRS = score_sfi3.COHORT_FLOOR_PAIRS
FAMILIES_REQUIRED = score_sfi3.FAMILIES_REQUIRED
MET = score_sfi3.MET
FAILED = score_sfi3.FAILED
SKIPPED = score_sfi3.SKIPPED


class AcceptanceRefused(RuntimeError):
    """SFI3 did not pass, or the acceptance does not describe a study that did."""


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


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


# ---------------------------------------------------------------------------
# the endpoint domain


def _require_endpoint_domain(receipt_endpoints: dict[str, Any]) -> dict[str, Any]:
    """declared == graded == receipt, as SET EQUALITY on full identifiers.

    Not a count. INC-V2-067 spent a 300-pair corpus on a study whose frozen rule
    named eight objects and whose instrument graded one, and the SFI3 freezer's
    own version of the mistake was `len(body["endpoints"])`. Two sets of nine can
    disagree on every member.
    """
    #: declared == graded is the scorer's own check, called rather than copied.
    #: Two implementations of a domain equality are two domains, and this module
    #: would be the one that agreed with a stale copy. It raises
    #: `score_sfi3.ContractBroken` on disagreement, which is re-raised here as a
    #: refusal so a caller sees one exception type from this module.
    try:
        declared = set(score_sfi3.require_declared_endpoints())
    except score_sfi3.ContractBroken as error:
        raise AcceptanceRefused(f"the endpoint domains are not the same set: {error}") from error
    graded = set(score_sfi3.ENDPOINTS)
    present = set(receipt_endpoints)
    problems = []
    if declared != present:
        problems.append(
            f"the measurement omits {sorted(declared - present)} and reports "
            f"{sorted(present - declared)} that nothing declares"
        )
    if problems:
        raise AcceptanceRefused("the endpoint domains are not the same set: " + "; ".join(problems))
    return {
        "declared": sorted(declared),
        "graded": sorted(graded),
        "in_receipt": sorted(present),
        "equal": True,
        "compared": "set equality on full identifiers, never a count",
    }


def _require_primaries(endpoints: dict[str, Any]) -> dict[str, Any]:
    """E1-E7 and E9: every one MET, and every one actually exercised.

    `MET` alone is not enough. An endpoint that could not have fired has not been
    satisfied, it has been avoided -- which is why the scorer reports
    `SKIPPED_NEVER_EXERCISED` as a distinct state and why E5, E6 and E9 may never
    reach it. E5 and E6 are the two SFI2 failed outright; E9 is the one no
    predecessor asked at all.
    """
    problems: list[str] = []
    exercised: dict[str, int] = {}
    for endpoint in PRIMARY_ENDPOINTS:
        block = endpoints.get(endpoint)
        if not isinstance(block, dict):
            problems.append(f"{endpoint} is absent from the measurement")
            continue
        verdict = block.get("verdict")
        power = int(block.get("pairs_exercising") or 0)
        exercised[endpoint] = power
        if verdict == FAILED:
            problems.append(f"{endpoint} is {FAILED} with {block.get('violations')} violation(s)")
        elif verdict == SKIPPED:
            problems.append(
                f"{endpoint} is {SKIPPED}: nothing in the cohort could have violated it"
            )
        elif verdict != MET:
            problems.append(f"{endpoint} reports {verdict!r}, which is not {MET}")
        elif not power:
            problems.append(
                f"{endpoint} reads {MET} over zero exercising pairs, which is a "
                "verdict about a question the cohort never posed"
            )
    for endpoint in MUST_BE_EXERCISED:
        if endpoint in PRIMARY_ENDPOINTS and not exercised.get(endpoint):
            problems.append(
                f"{endpoint} may never be unexercised: a predecessor study either "
                "failed it outright or never asked it"
            )
    if problems:
        raise AcceptanceRefused("the primary endpoints do not carry a PASS: " + "; ".join(problems))
    return {
        "primary_endpoints": sorted(PRIMARY_ENDPOINTS),
        "pairs_exercising": exercised,
        "must_be_exercised": sorted(MUST_BE_EXERCISED),
        "all_met_and_exercised": True,
    }


def _require_veto(endpoints: dict[str, Any]) -> dict[str, Any]:
    """E8: present, clean, fully staged -- and credited with nothing.

    Deliberately NOT required to be `MET`, and deliberately NOT required to have
    natural gate power. Requiring `MET` would fail every honest SFI3 run, since
    the scorer never emits it for the veto; requiring power would fail the study
    for a property of the seam rather than of the system. What IS required is
    that it was watched at every declared stage: an endpoint checked after
    execution but not again at activation reports a clean number while leaving
    the path it exists to guard unobserved.
    """
    block = endpoints.get(VETO_ENDPOINT)
    if not isinstance(block, dict):
        raise AcceptanceRefused(f"{VETO_ENDPOINT} is absent; the safety veto was not evaluated")
    violations = int(block.get("violations") or 0)
    if violations:
        raise AcceptanceRefused(
            f"{VETO_ENDPOINT} reports {violations} violation(s). A rebuild-required "
            "artifact carried without its rebuild having executed is not tradeable "
            "against any number of met endpoints."
        )
    verdict = block.get("verdict")
    if verdict != VETO_CLEAR:
        raise AcceptanceRefused(
            f"{VETO_ENDPOINT} reports {verdict!r}, not {VETO_CLEAR!r}. The veto's "
            "clean state is its own; it is never MET and never credits a PASS."
        )
    checked = tuple(block.get("stages_checked") or ())
    missing = [stage for stage in STAGES_REQUIRED if stage not in checked]
    if missing or block.get("stages_missing"):
        raise AcceptanceRefused(
            f"{VETO_ENDPOINT} was not observed at every required stage; missing "
            f"{missing or block.get('stages_missing')}. An unwatched stage is a "
            "failure of the instrument, not an absence of violations."
        )
    return {
        "endpoint": VETO_ENDPOINT,
        "verdict": verdict,
        "violations": 0,
        "stages_checked": list(checked),
        "stages_required": list(STAGES_REQUIRED),
        "natural_gate_power": bool(block.get("natural_gate_power")),
        "contributes_positive_evidence": False,
        "why_not_met": (
            "E8 is a mandatory safety veto. Zero violations credit nothing, because "
            "its seam is structurally closed and it could not have fired; a "
            "violation fails the study outright."
        ),
    }


def _require_cohort(body: dict[str, Any]) -> dict[str, Any]:
    gates = body.get("cohort_gates") or {}
    pairs = gates.get("pairs_scored")
    families = list(gates.get("families") or [])
    if not isinstance(pairs, int) or pairs < COHORT_FLOOR_PAIRS:
        raise AcceptanceRefused(
            f"the study scored {pairs} pairs against a floor of {COHORT_FLOOR_PAIRS}. "
            "The floor is never lowered to reach feasibility."
        )
    if len(families) < FAMILIES_REQUIRED:
        raise AcceptanceRefused(
            f"the study spans {len(families)} families against a required "
            f"{FAMILIES_REQUIRED}: {sorted(families)}"
        )
    return {
        "pairs_scored": pairs,
        "pairs_required": COHORT_FLOOR_PAIRS,
        "families": sorted(families),
        "families_required": FAMILIES_REQUIRED,
    }


# ---------------------------------------------------------------------------
# the contract


def verify(acceptance: dict[str, Any]) -> dict[str, Any]:
    """Re-check every binding and every clause against disk. Raises otherwise."""
    provenance = acceptance.get("provenance")
    embedded_digest = acceptance.get("receipt_sha256")
    if provenance is not None or embedded_digest is not None:
        if not isinstance(provenance, dict) or not isinstance(embedded_digest, str):
            raise AcceptanceRefused(
                "an immutable acceptance envelope must carry both provenance and receipt_sha256"
            )
        bare = {key: value for key, value in acceptance.items() if key != "receipt_sha256"}
        if canonical_sha(bare) != embedded_digest:
            raise AcceptanceRefused("the immutable acceptance envelope digest does not match")
        if provenance.get("immutable") is not True or provenance.get("receipt_stem") != STEM:
            raise AcceptanceRefused("the acceptance envelope is not immutable SFI3 authority")
    if acceptance.get("schema") != SCHEMA:
        raise AcceptanceRefused(
            f"schema is {acceptance.get('schema')!r}, not {SCHEMA!r}; this is not an "
            "SFI3 acceptance"
        )
    missing = [field for field in REQUIRED_BINDINGS if not acceptance.get(field)]
    if missing:
        raise AcceptanceRefused(f"the acceptance carries no {missing}")
    if acceptance["protocol_id"] != ACCEPTED_PROTOCOL_ID:
        raise AcceptanceRefused(
            f"this acceptance is for {acceptance['protocol_id']!r}. The GPU study "
            f"gates on {ACCEPTED_PROTOCOL_ID!r}, and SFI2 -- frozen, FAIL, spent and "
            "permanently non-rescorable -- can never stand in for it."
        )

    for field, digest_field in (
        ("protocol", "protocol_sha256"),
        ("protocol_freeze_receipt", "protocol_freeze_sha256"),
        ("measurement_receipt", "measurement_sha256"),
        ("acquisition", "acquisition_sha256"),
    ):
        path = _resolve(str(acceptance[field]))
        actual = _sha_file(path)
        if actual != acceptance[digest_field]:
            raise AcceptanceRefused(
                f"{path.name} has changed since it was accepted.\n"
                f"  accepted: {acceptance[digest_field]}\n  current:  {actual}"
            )

    measurement = _resolve(str(acceptance["measurement_receipt"]))
    body = json.loads(measurement.read_text(encoding="utf-8"))

    if body.get("schema") != MEASUREMENT_SCHEMA:
        raise AcceptanceRefused(
            f"the named measurement is {body.get('schema')!r}, not an SFI3 score. An "
            "SFI2-shaped receipt does not become an SFI3 PASS by being pointed at."
        )
    if body.get("split") != REQUIRED_SPLIT:
        raise AcceptanceRefused(
            f"the measurement's split is {body.get('split')!r}, not {REQUIRED_SPLIT!r}. "
            "Development material cannot authorize GPU spend."
        )
    if body.get("protocol_sha256") != acceptance["protocol_sha256"]:
        raise AcceptanceRefused(
            "the acceptance and the measurement disagree about the protocol digest"
        )
    if body.get("acquisition_sha256") != acceptance["acquisition_sha256"]:
        raise AcceptanceRefused(
            "the acceptance and the measurement disagree about the acquisition digest"
        )

    endpoints = body.get("endpoints")
    if not isinstance(endpoints, dict) or not endpoints:
        raise AcceptanceRefused("the measurement carries no endpoint block")

    domain = _require_endpoint_domain(endpoints)
    primaries = _require_primaries(endpoints)
    veto = _require_veto(endpoints)
    cohort = _require_cohort(body)

    if body.get("verdict") != "PASS":
        raise AcceptanceRefused(
            f"the measurement's own verdict is {body.get('verdict')!r}, not PASS. "
            "Every clause above may hold and the study still not have passed; the "
            "scorer's verdict is read, never re-derived here."
        )

    return {
        "schema": SCHEMA,
        "held": True,
        "protocol_id": acceptance["protocol_id"],
        "protocol": acceptance["protocol"],
        "protocol_sha256": acceptance["protocol_sha256"],
        "protocol_freeze_receipt": acceptance["protocol_freeze_receipt"],
        "protocol_freeze_run_id": acceptance["protocol_freeze_run_id"],
        "measurement_receipt": acceptance["measurement_receipt"],
        "measurement_run_id": acceptance["measurement_run_id"],
        "measurement_sha256": acceptance["measurement_sha256"],
        "acquisition": acceptance["acquisition"],
        "acquisition_sha256": acceptance["acquisition_sha256"],
        "split": REQUIRED_SPLIT,
        "verdict": "PASS",
        "endpoint_domain": domain,
        "primaries": primaries,
        "safety_veto": veto,
        "cohort": cohort,
        "single_implementation": (
            "the endpoint arithmetic lives in score_sfi3 and is imported, never "
            "restated. The GPU preflight and launcher consume this acceptance and "
            "re-derive nothing of their own."
        ),
        "no_glob": (
            "the study is named by protocol id, freeze run id, measurement run id "
            "and four digests. No stem glob, no 'latest', no newest-wins."
        ),
    }


def build(measurement_receipt: Path) -> dict[str, Any]:
    """Draft an acceptance from a measurement, then verify it before returning.

    Never returns an unverified draft. This module exists because a claim was
    standing in for a check, and a draft that has not passed its own contract is
    a claim.
    """
    body = json.loads(measurement_receipt.read_text(encoding="utf-8"))

    def relative(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            return str(path)

    freeze_rel = str(body.get("protocol_freeze_receipt") or "")
    freeze_path = _resolve(freeze_rel) if freeze_rel else None
    freeze_body = json.loads(freeze_path.read_text(encoding="utf-8")) if freeze_path else {}
    acquisition_rel = str(body.get("acquisition") or "")

    draft = {
        "schema": SCHEMA,
        "protocol_id": ACCEPTED_PROTOCOL_ID,
        "protocol": str(body.get("protocol") or ""),
        "protocol_sha256": body.get("protocol_sha256"),
        "protocol_freeze_receipt": freeze_rel,
        "protocol_freeze_run_id": (freeze_body.get("provenance") or {}).get("run_id")
        or freeze_body.get("run_id"),
        "protocol_freeze_sha256": _sha_file(freeze_path) if freeze_path else None,
        "measurement_receipt": relative(measurement_receipt),
        "measurement_run_id": (body.get("provenance") or {}).get("run_id") or body.get("run_id"),
        "measurement_sha256": _sha_file(measurement_receipt),
        "acquisition": acquisition_rel,
        "acquisition_sha256": body.get("acquisition_sha256"),
    }
    verify(draft)
    return draft


def verify_authority(
    acceptance_receipt: Path,
    *,
    authority_path: Path | None = None,
) -> dict[str, Any]:
    """Verify the one fixed acceptance authority path; alternate receipts refuse."""
    expected = (authority_path or AUTHORITY_PATH).resolve()
    actual = acceptance_receipt.resolve()
    if actual != expected:
        raise AcceptanceRefused(
            f"{actual} is not the single SFI3 acceptance authority {expected}. "
            "No alternate or newest-wins acceptance is recognized."
        )
    if not actual.is_file():
        raise AcceptanceRefused(f"the single SFI3 acceptance authority is absent: {actual}")
    body = json.loads(actual.read_text(encoding="utf-8"))
    authority = body.get("authority")
    if not isinstance(authority, dict) or authority.get("single_immutable_authority") is not True:
        raise AcceptanceRefused("the fixed acceptance file does not declare single authority")
    if authority.get("path") != _relative(actual):
        raise AcceptanceRefused("the acceptance authority does not bind its own exact path")
    return verify(body)


def seal(
    measurement_receipt: Path,
    *,
    authority_path: Path | None = None,
) -> dict[str, Any]:
    """Build, verify, and exclusively seal the sole immutable SFI3 acceptance."""
    target = (authority_path or AUTHORITY_PATH).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    alternate = sorted(target.parent.glob(f"{STEM}--*.json"))
    if alternate:
        raise AcceptanceRefused(
            "alternate SFI3 acceptance receipts already exist; refusing to choose one: "
            + ", ".join(str(path) for path in alternate)
        )
    if target.exists():
        raise AcceptanceRefused(
            f"the single SFI3 acceptance authority already exists at {target}; "
            "it is immutable and cannot be resealed"
        )

    draft = build(measurement_receipt)
    measurement_run_id = draft["measurement_run_id"]
    envelope = {
        **draft,
        "authority": {
            "single_immutable_authority": True,
            "path": _relative(target),
            "alternate_receipts_accepted": False,
            "newest_wins": False,
        },
        "provenance": {
            "schema": IMMUTABLE_ENVELOPE_SCHEMA,
            "run_id": f"sfi3-acceptance-{measurement_run_id}",
            "generated_at": now(),
            "tool": _relative(Path(__file__).resolve()),
            "tool_sha256": sha_file(Path(__file__).resolve()),
            "protocol": draft["protocol"],
            "protocol_sha256": draft["protocol_sha256"],
            "receipt_stem": STEM,
            "immutable": True,
            "overwrite_refused_by": _relative(Path(__file__).resolve()),
        },
    }
    envelope["receipt_sha256"] = canonical_sha(envelope)
    verify(envelope)
    try:
        with open(target, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False))
            handle.write("\n")
    except FileExistsError as error:
        raise AcceptanceRefused(
            f"the single SFI3 acceptance authority was sealed concurrently at {target}"
        ) from error
    held = verify_authority(target, authority_path=target)
    return {
        **held,
        "authority_receipt": _relative(target),
        "authority_sha256": sha_file(target),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurement", type=Path, default=None)
    parser.add_argument("--acceptance", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.measurement is not None:
            print(json.dumps(seal(args.measurement), indent=1, sort_keys=True))
            return 0
        if args.acceptance is None or not args.acceptance.is_file():
            print(
                json.dumps(
                    {
                        "state": "REFUSED",
                        "why": (
                            "name an acceptance explicitly with --acceptance. There is "
                            "no default and no search: GPU authority is one immutable "
                            "path and one digest."
                        ),
                    },
                    indent=1,
                )
            )
            return 4
        body = verify_authority(args.acceptance)
        print(json.dumps({**body, "receipt": args.acceptance.name}, indent=1, sort_keys=True))
        return 0
    except AcceptanceRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
