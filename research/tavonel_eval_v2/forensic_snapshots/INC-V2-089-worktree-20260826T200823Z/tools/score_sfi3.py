#!/usr/bin/env python3
"""Score SFI3 against all eight endpoints. One writer, one receipt, no acquisition.

SFI3 adds one endpoint to SFI2's seven and changes nothing else about how the
first seven are read. That restraint is the point: E1-E4 and E7 are still
computed by `score_sfi1.endpoint_rows`, imported rather than restated, so three
studies remain comparable across two rewrites of the system under test.

E8 is new and exists because of what SFI2 found. E5 and E6 detect a stale
artifact in the FINAL STATE — they are consequence detectors, and a consequence
detector cannot distinguish an executor that is correct from one that happened
not to be caught. SFI2 could not tell which it had. E8 is read from the
executor's own invariant observations at the moment a carry-forward decision is
made, at both stages the founder named.

Two refusals inherited from the correction that INC-V2-035 forced:

* every key this scorer reads from an executor summary is declared in a table at
  module level and is ASSERTED TO EXIST. A missing key raises. It is never
  reported as an unexercised endpoint, because a scorer that describes its own
  bug as a property of the cohort is worse than one that crashes — the crash is
  visible and the false SKIPPED is not.
* an endpoint measured at fewer stages than the protocol requires is not met.
  E8 checked only after execution, and not again at activation, would leave
  exactly the gap the founder asked to close, while reporting a clean number.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import verify_sfi3_reservation_binding as reservation_binding  # noqa: E402

#: Imported, not restated, for the same reason V2 imported them: a
#: re-implementation that drifted by a line would make the studies incomparable
#: while looking like a repeat.
from common import canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from score_sfi1 import FAILED, MET, SKIPPED, endpoint_rows, summary  # noqa: E402

ACQUISITION = NS / "artifacts" / "development" / "sfi3" / "sfi3_acquisition.json"
PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V3.yaml"

FACT_ENDPOINTS: tuple[str, ...] = (
    "E1_no_unclassified_changed_regions",
    "E2_no_recognized_but_unrepresented",
    "E3_no_silent_loss_in_a_complete_scope",
    "E4_no_reference_or_locator_only_clean_miss",
    "E7_unresolved_fails_closed",
)
EXECUTOR_ENDPOINTS: tuple[str, ...] = (
    "E5_no_confirmed_selective_stale_escape",
    "E6_exact_selective_vs_clean_equivalence",
    "E8_no_rebuild_required_artifact_carried_without_execution",
    "E9_every_detected_typed_change_creates_a_rebuild_request",
)
ENDPOINTS: tuple[str, ...] = (
    "E1_no_unclassified_changed_regions",
    "E2_no_recognized_but_unrepresented",
    "E3_no_silent_loss_in_a_complete_scope",
    "E4_no_reference_or_locator_only_clean_miss",
    "E5_no_confirmed_selective_stale_escape",
    "E6_exact_selective_vs_clean_equivalence",
    "E7_unresolved_fails_closed",
    "E8_no_rebuild_required_artifact_carried_without_execution",
    "E9_every_detected_typed_change_creates_a_rebuild_request",
)

#: The founder's ruling of 2026-08-23, option (b). E8 is a MANDATORY SAFETY VETO,
#: not a PASS-contributing endpoint.
#:
#: The distinction is the substance of the ruling. E8's seam is structurally
#: closed, so on any natural cohort it reports zero violations AND zero power.
#: Under the ordinary rule that is SKIPPED, and a SKIPPED endpoint fails a study —
#: which would make SFI3 unpassable for a reason that says nothing about the
#: system. The opposite error is worse: counting a zero-power zero as a met
#: endpoint manufactures positive evidence from an instrument that could not have
#: fired.
#:
#: So E8 does neither. It can only ever VETO:
#:     violations > 0  -> the study FAILS
#:     violations == 0 -> nothing is credited, and the zero power is reported
SAFETY_VETO_ENDPOINT = "E8_no_rebuild_required_artifact_carried_without_execution"

#: Everything that must be exercised AND met for a PASS. E8 is deliberately absent.
PRIMARY_ENDPOINTS: tuple[str, ...] = tuple(
    endpoint for endpoint in ENDPOINTS if endpoint != SAFETY_VETO_ENDPOINT
)

#: E5, E6 and E9 may never be SKIPPED — each is an endpoint a predecessor study
#: either failed outright or never asked at all.
MAY_NOT_BE_SKIPPED: tuple[str, ...] = (
    "E5_no_confirmed_selective_stale_escape",
    "E6_exact_selective_vs_clean_equivalence",
    "E9_every_detected_typed_change_creates_a_rebuild_request",
)

#: (endpoint id, key in the executor summary, violation count key, named cases key).
#:
#: The endpoint id and the summary key are DIFFERENT STRINGS for E5 and E8, and
#: the difference is not cosmetic: the protocol names an endpoint for the
#: PROPERTY it asserts ("no confirmed escape"), while the executor names its
#: block for what it MEASURED ("confirmed escape"). E6's two names coincide by
#: accident. Assuming all three coincided is what made SFI2's first scored run
#: report E5 as never exercised while 14 confirmed escapes sat in the receipt
#: beside it — see INC-V2-035.
#:
#: This table is module level so the integration gate can assert every key in it
#: exists in what the executor actually writes, before a lineage is ever read.
EXECUTOR_BLOCKS: tuple[tuple[str, str, str, str], ...] = (
    (
        "E5_no_confirmed_selective_stale_escape",
        "E5_confirmed_selective_stale_escape",
        "pairs_with_confirmed_escape",
        "confirmed",
    ),
    (
        "E6_exact_selective_vs_clean_equivalence",
        "E6_exact_selective_vs_clean_equivalence",
        "pairs_divergent",
        "divergent",
    ),
    (
        "E8_no_rebuild_required_artifact_carried_without_execution",
        "E8_rebuild_required_carried_without_execution",
        "pairs_with_unexecuted_carry",
        "carried",
    ),
    (
        "E9_every_detected_typed_change_creates_a_rebuild_request",
        "E9_detected_change_without_rebuild_request",
        "pairs_with_silent_disappearance",
        "silent",
    ),
)

#: E8 must be observed at BOTH stages. The founder's wording is explicit that the
#: check runs again at candidate activation "so one scheduler defect cannot
#: silently reach ACTIVE state", and an E8 measured only after execution would
#: report zero violations while leaving that path unwatched.
STAGES_REQUIRED: tuple[str, ...] = ("post_execution", "pre_activation")
STAGED_ENDPOINT = "E8_no_rebuild_required_artifact_carried_without_execution"

#: Fixed before any count existed, carried forward from SFI2 unchanged. Restated
#: here so lowering one is a visible edit to a scoring tool rather than an
#: argument in a shell.
COHORT_FLOOR_PAIRS = 200
FAMILIES_REQUIRED = 3


#: E8's own outcome vocabulary. Deliberately not MET — MET is a claim that an
#: endpoint was put at risk and survived, and E8 was not put at risk.
VETO_CLEAR = "VETO_CLEAR_NO_POSITIVE_CREDIT"


class NotFrozen(RuntimeError):
    """Scoring an unfrozen protocol is scoring nothing."""


class ContractBroken(RuntimeError):
    """The scorer and the executor disagree about what the summary contains."""


class AlreadyScored(RuntimeError):
    """An authoritative SFI3 score already exists; the held-out cohort is spent."""


def require_no_authoritative_score(receipts: Path | None = None) -> None:
    """Refuse before reading the acquisition if any prior score receipt exists.

    The glob is used only to detect ambiguity and fail closed.  No matching file
    is ever selected or accepted as "latest".  A malformed or partial file under
    the authoritative stem is still a prior authority claim and therefore blocks.
    """
    directory = receipts or (NS / "receipts")
    found = sorted(directory.glob("sfi3-execution-correctness--*.json"))
    if found:
        raise AlreadyScored(
            "SFI3 has already been scored or an authoritative score claim exists: "
            + ", ".join(str(path) for path in found)
            + ". The held-out acquisition is scored exactly once; no receipt is "
            "chosen by newest-wins and no rescore is permitted."
        )


def require_acquisition_binding(
    acquired: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    """The worker and scorer must name the identical exact reservation binding."""
    recorded = acquired.get("reservation_binding")
    if not isinstance(recorded, dict):
        raise ContractBroken(
            "the acquisition carries no verified reservation_binding; scoring it "
            "would trust that the worker ran the pre-payload root gate"
        )
    if recorded != expected:
        raise ContractBroken(
            "the acquisition's reservation binding differs from the exact binding "
            "verified by this scoring invocation"
        )
    return recorded


def authoritative_score_run_id(acquisition_sha256: str) -> str:
    """One deterministic authority slot for the one immutable acquisition."""
    prefix = "sha256:"
    digest = acquisition_sha256[len(prefix) :] if acquisition_sha256.startswith(prefix) else ""
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ContractBroken("the acquisition sha256 cannot name the single score authority")
    return "sfi3-score-" + digest[:24]


#: What this scorer borrows from SFI1, and what each borrowed name must still
#: mean. Imported rather than restated so the studies stay comparable -- but an
#: import is a promise about a module that is no longer maintained for us, and a
#: label that quietly changed there would relabel this study's verdicts without
#: touching a line of this file.
#:
#: `SKIPPED` is spelled `SKIPPED_NEVER_EXERCISED` on purpose and the long form is
#: pinned here rather than the short one: SFI1 was failed by two endpoints that
#: were never put at risk, and the label says which of the two things happened.
BORROWED_VOCABULARY = {
    "MET": "MET",
    "FAILED": "FAILED",
    "SKIPPED": "SKIPPED_NEVER_EXERCISED",
}


def require_shared_verdict_vocabulary() -> dict[str, str]:
    """The verdict labels borrowed from SFI1 still say what SFI3 thinks.

    Not decoration. SFI1 is a spent study; nothing stops its constants moving,
    and this scorer writes those exact strings into a frozen receipt. A borrowed
    label that changed upstream would be inherited silently, which is the
    failure this check exists to convert into a refusal.
    """
    actual = {"MET": MET, "FAILED": FAILED, "SKIPPED": SKIPPED}
    if actual != BORROWED_VOCABULARY:
        raise ContractBroken(
            f"the verdict labels imported from score_sfi1 are {actual}, not "
            f"{BORROWED_VOCABULARY}. SFI3 writes these strings into a frozen "
            "receipt; a label that moved upstream would relabel this study's "
            "verdicts without any change here."
        )
    return actual


def declared_endpoints() -> tuple[str, ...]:
    """The endpoint ids the protocol declares, read from the protocol itself."""
    import yaml

    body = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    return tuple(sorted((body or {}).get("endpoints") or {}))


#: The schema every SFI3 measurement receipt carries. Named here, where the
#: receipt is built, so anything downstream that must recognise one imports it
#: rather than restating the literal -- a second copy is the one that drifts.
RESULT_SCHEMA = "tavonel.v2.sfi3_score.v1"


def require_declared_endpoints() -> tuple[str, ...]:
    """The endpoints this scorer grades are exactly the endpoints the protocol declares.

    INC-V2-067 in its SFI3 form. The V2R3R1 chain froze a pass rule naming eight
    invariants and shipped an instrument that graded one; the receipt looked
    complete because nothing compared the rule to the instrument. The freezer
    here counts `len(endpoints)`, and a count is not a correspondence -- two
    lists of nine can disagree on every member.

    So the identity of the set is checked, not its size, and a disagreement in
    either direction refuses:

      * an endpoint the protocol declares and this scorer cannot grade would be
        reported as absent from a study that promised it;
      * an endpoint this scorer grades and the protocol does not declare is a
        number with no rule behind it.
    """
    declared = declared_endpoints()
    graded = tuple(sorted(ENDPOINTS))
    if declared != graded:
        missing = [name for name in declared if name not in graded]
        extra = [name for name in graded if name not in declared]
        raise ContractBroken(
            "the protocol and the scorer do not name the same endpoints.\n"
            f"  declared but not graded: {missing}\n"
            f"  graded but not declared: {extra}\n"
            "A pass rule the instrument cannot answer is the defect that ended "
            "the V2R3 chain (INC-V2-067); it is refused here before the study "
            "runs rather than discovered in its receipt."
        )
    return declared


def frozen_protocol() -> dict[str, Any]:
    """The freeze receipt, or a refusal.

    A scorer that runs against a draft produces a number whose rules could still
    move to fit it.
    """
    #: Before the receipt is even located: the rule and the instrument must name
    #: the same endpoints, and the borrowed verdict labels must still be the
    #: ones this study means. Both are cheap, and both are shapes that have
    #: already cost this study a frozen chain.
    require_shared_verdict_vocabulary()
    require_declared_endpoints()
    freezes = sorted((NS / "receipts").glob("sfi3-protocol-freeze--*.json"))
    if not freezes:
        raise NotFrozen(
            "no sfi3-protocol-freeze receipt exists. The protocol must be frozen "
            "before a single fresh lineage is read."
        )
    body = json.loads(freezes[-1].read_text(encoding="utf-8"))
    actual = sha_file(PROTOCOL)
    if body.get("protocol_sha256") != actual:
        raise NotFrozen(
            f"the protocol has moved since it was frozen: {actual} is not "
            f"{body.get('protocol_sha256')}"
        )
    #: the freeze receipt carries no top-level run_id, and a scored result whose
    #: provenance pointer is null cannot be followed back to the freeze it claims.
    body["receipt_path"] = rel(freezes[-1])
    return body


def _stage_coverage(block: dict[str, Any]) -> dict[str, Any]:
    """Which of the required stages actually observed anything."""
    checked = tuple(block.get("stages_checked") or ())
    missing = [stage for stage in STAGES_REQUIRED if stage not in checked]
    return {"stages_checked": list(checked), "stages_missing": missing}


def score_executor(executor: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """E5, E6 and E8, from the executor summary and from nothing else.

    `pairs_that_could_have_exhibited` is the denominator that decides whether an
    endpoint may be called met at all. Zero means the cohort never put it at
    risk. The protocol forbids SKIPPED here, which is a requirement on the
    COHORT — it must contain pairs where the failure could have occurred — not a
    licence for the scorer to call an unexercised endpoint met.
    """
    verdicts: dict[str, dict[str, Any]] = {}
    if not executor:
        for endpoint in EXECUTOR_ENDPOINTS:
            verdicts[endpoint] = {
                "verdict": SKIPPED,
                "why": (
                    "no executor summary in the acquisition artifact. Nothing in this "
                    "run rebuilt an artifact, so the endpoint was not measured"
                ),
                "violations": None,
                "pairs_exercising": 0,
            }
        return verdicts

    for endpoint, summary_key, violated_key, names_key in EXECUTOR_BLOCKS:
        if summary_key not in executor:
            raise ContractBroken(
                f"the executor summary has no block {summary_key!r}; the scorer and "
                f"the executor disagree about the contract, and {endpoint} cannot be "
                "read from it. This is not an unexercised endpoint and is not "
                "reported as one."
            )
        block = executor[summary_key]
        for required in ("pairs_that_could_have_exhibited", violated_key, "gate_power"):
            if required not in block:
                raise ContractBroken(
                    f"block {summary_key!r} has no key {required!r}; {endpoint} cannot "
                    "be read without defaulting, and defaulting is what produced the "
                    "false SKIPPED in SFI2"
                )
        exercising = int(block["pairs_that_could_have_exhibited"])
        violations = int(block[violated_key])

        row: dict[str, Any] = {
            "violations": violations,
            "pairs_exercising": exercising if block["gate_power"] else 0,
            #: named cases, never counts alone. A count cannot be checked against
            #: a rebuild, and every ruling in this programme is about named
            #: artifacts.
            "cases": block.get(names_key, []),
        }
        if endpoint == STAGED_ENDPOINT:
            row.update(_stage_coverage(block))

        if endpoint == SAFETY_VETO_ENDPOINT:
            #: The veto never reports SKIPPED, because SKIPPED means "this study
            #: could not answer the question" and would fail the run. E8's question
            #: IS answered on every cohort — the answer is simply that nothing
            #: violated it and nothing could have. Both halves are reported, and
            #: neither is credited towards a PASS.
            row["natural_gate_power"] = bool(exercising and block["gate_power"])
            if endpoint == STAGED_ENDPOINT and row["stages_missing"]:
                verdicts[endpoint] = {
                    **row,
                    "verdict": FAILED,
                    "why": (
                        "the invariant was not observed at every required stage: "
                        f"{', '.join(row['stages_missing'])} missing. An unwatched "
                        "stage is a failure of the instrument, not an absence of "
                        "violations"
                    ),
                }
                continue
            verdicts[endpoint] = {
                **row,
                "verdict": FAILED if violations else VETO_CLEAR,
                "why": (
                    None
                    if violations
                    else (
                        "zero violations. This is NOT positive evidence: the seam is "
                        "structurally closed, so the endpoint had no natural gate "
                        "power and could not have fired on this cohort. It vetoes a "
                        "PASS if violated and credits nothing when clean"
                    )
                ),
            }
            continue

        if not exercising or not block["gate_power"]:
            verdicts[endpoint] = {
                **row,
                "verdict": SKIPPED,
                "why": (
                    "no judged supported pair in this cohort could have exhibited it. "
                    "The rebuild ran; the cohort did not put the endpoint at risk"
                ),
            }
            continue
        if endpoint == STAGED_ENDPOINT and row["stages_missing"]:
            #: Not MET and not SKIPPED. The endpoint was exercised at one stage and
            #: unwatched at another, which is a partial instrument rather than an
            #: absent one, and reporting it as met would certify a path nothing
            #: looked at.
            verdicts[endpoint] = {
                **row,
                "verdict": FAILED,
                "why": (
                    "the invariant was not observed at every required stage: "
                    f"{', '.join(row['stages_missing'])} missing. One scheduler defect "
                    "reaching ACTIVE state is exactly what the second stage exists to "
                    "prevent, so an unwatched stage is a failure, not an absence"
                ),
            }
            continue
        verdicts[endpoint] = {
            **row,
            "verdict": MET if violations == 0 else FAILED,
            "why": None,
        }
    return verdicts


def score(rows: list[dict[str, Any]], executor: dict[str, Any] | None) -> dict[str, Any]:
    """Endpoint verdicts, each with the power that earned it."""
    verdicts: dict[str, Any] = {}
    for endpoint in FACT_ENDPOINTS:
        violations = sum(row[endpoint][0] for row in rows)
        exercising = sum(1 for row in rows if row[endpoint][1])
        if not exercising:
            verdicts[endpoint] = {
                "verdict": SKIPPED,
                "why": "no pair in this cohort could have violated it",
                "violations": 0,
                "pairs_exercising": 0,
            }
            continue
        verdicts[endpoint] = {
            "verdict": MET if violations == 0 else FAILED,
            "why": None,
            "violations": violations,
            "pairs_exercising": exercising,
        }
    verdicts.update(score_executor(executor))
    return {endpoint: verdicts[endpoint] for endpoint in ENDPOINTS}


VERDICT_RULE = (
    "PASS requires E1-E7 and E9 all exercised AND met, plus the cohort floor of 200 "
    "pairs across 3 families, plus zero held-out E8 violations, plus proven "
    "pre-freeze E8 fault-injection instrumentation power. A FAILED endpoint fails "
    "the study; a SKIPPED one fails it too, because an endpoint that was never "
    "exercised has not been satisfied, it has been avoided. E5, E6 and E9 may not "
    "be SKIPPED. E8 is a mandatory safety veto and contributes nothing positive: a "
    "violation fails the study, and zero violations credit nothing, because E8's "
    "seam is structurally closed and it has no natural gate power."
)


def verdict_for(
    failed: list[str],
    skipped: list[str],
    cohort_short: list[str],
    *,
    veto_violations: int,
    instrumentation_power_proven: bool,
) -> str:
    """The whole rule, in one place, so a test can drive it instead of restating it.

    Inlining this in `main` is how a test ends up asserting its own copy of the rule
    and passing while the shipped rule says something else.

    The two keyword arguments are required rather than defaulted on purpose. A
    default would let a caller that knows nothing about E8 obtain a PASS by
    omission, which is precisely the shape of failure this scorer exists to refuse:
    the cheapest way to pass a gate should never be to forget it exists.
    """
    if veto_violations:
        #: E8 vetoes regardless of everything else. A rebuild-required artifact
        #: reused without its rebuild having been executed is not tradeable against
        #: any number of met endpoints.
        return "FAIL"
    if not instrumentation_power_proven:
        #: An unvalidated instrument reporting zero is indistinguishable from a
        #: broken one reporting zero, and the whole point of E8 is that its clean
        #: readings carry no power of their own.
        return "FAIL"
    return "PASS" if not failed and not skipped and not cohort_short else "FAIL"


def cohort_gates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The two composition requirements, checked as gates rather than as prose."""
    families = sorted({row["family"] for row in rows})
    return {
        "pairs_scored": len(rows),
        "pairs_required": COHORT_FLOOR_PAIRS,
        "pairs_met": len(rows) >= COHORT_FLOOR_PAIRS,
        "families": families,
        "families_required": FAMILIES_REQUIRED,
        "families_met": len(families) >= FAMILIES_REQUIRED,
    }


#: Fault-injection evidence that E8's instrument can actually fire. DEVELOPMENT
#: evidence, produced before the freeze, and never mixed into a held-out
#: denominator — it says the detector works, not that the cohort exercised it.
POWER_RECEIPT_STEM = "e8-instrumentation-power"


def instrumentation_power() -> dict[str, Any]:
    """Whether E8's instrument was proven able to fire, before the freeze.

    Required because E8's clean readings carry no power of their own. Without this,
    "zero violations" from a detector nobody ever made fire is not a safety result;
    it is an untested detector reporting its default.
    """
    found = sorted((NS / "receipts").glob(f"{POWER_RECEIPT_STEM}--*.json"))
    if not found:
        return {
            "proven": False,
            "why": (
                f"no {POWER_RECEIPT_STEM} receipt exists. E8's instrument has not "
                "been shown to raise InvariantViolation on an injected defect, so a "
                "clean held-out reading cannot be distinguished from a dead check"
            ),
            "receipt": None,
        }
    body = json.loads(found[-1].read_text(encoding="utf-8"))
    return {
        "proven": bool(body.get("injections_raised"))
        and int(body.get("injections_not_raised", 1)) == 0,
        "receipt": rel(found[-1]),
        "injections_raised": body.get("injections_raised"),
        "injections_not_raised": body.get("injections_not_raised"),
        "split": "development",
        "never_mixed_into_held_out_denominator": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acquisition", default=str(ACQUISITION))
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--handoff-sha256", required=True)
    arguments = parser.parse_args(argv)

    freeze = frozen_protocol()

    binding = reservation_binding.verify_binding(
        handoff_receipt=arguments.handoff,
        handoff_sha256=arguments.handoff_sha256,
    )
    require_no_authoritative_score()

    path = Path(arguments.acquisition)
    if not path.exists():
        print(f"no acquisition artifact at {rel(path)}; nothing to score", file=sys.stderr)
        return 3
    acquired = json.loads(path.read_text(encoding="utf-8"))
    require_acquisition_binding(acquired, binding)

    rows = [endpoint_rows(pair) for pair in acquired["admitted"]]
    executor = acquired.get("executor") or acquired.get("rebuild")
    verdicts = score(rows, executor)
    gates = cohort_gates(rows)

    #: Only PRIMARY endpoints contribute to the pass arithmetic. E8's rows are read
    #: separately below; folding it in here is exactly the mistake the founder's
    #: option (b) ruling exists to prevent.
    failed = [name for name in PRIMARY_ENDPOINTS if verdicts[name]["verdict"] == FAILED]
    skipped = [name for name in PRIMARY_ENDPOINTS if verdicts[name]["verdict"] == SKIPPED]
    veto = verdicts[SAFETY_VETO_ENDPOINT]
    veto_violations = int(veto.get("violations") or 0)
    if veto["verdict"] == FAILED and not veto_violations:
        #: E8 failed for a reason other than a violation count — an unwatched stage.
        #: That is an instrument failure and must still veto.
        veto_violations = -1
    power = instrumentation_power()
    short = [
        name
        for name, met in (("pairs", gates["pairs_met"]), ("families", gates["families_met"]))
        if not met
    ]

    body: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "protocol_freeze_receipt": freeze["receipt_path"],
        "split": "held_out",
        "reservation_binding": binding,
        "predecessor": {
            "study": "SOURCE_FACT_IR_HELDOUT_V2",
            "verdict": "FAIL",
            "standing": "frozen, never rescored; its corpus is development material",
            "failed_endpoints": [
                "E2_no_recognized_but_unrepresented",
                "E5_no_confirmed_selective_stale_escape",
                "E6_exact_selective_vs_clean_equivalence",
            ],
        },
        "acquisition": rel(path),
        "acquisition_sha256": sha_file(path),
        "reduction_digest": acquired.get("reduction_digest"),
        "generated_at": now(),
        "summary": summary(rows),
        "cohort_gates": gates,
        "endpoints": verdicts,
        "endpoints_failed": failed,
        "endpoints_skipped": skipped,
        "cohort_gates_short": short,
        "executor_summary_present": bool(executor),
        "verdict": verdict_for(
            failed,
            skipped,
            short,
            veto_violations=veto_violations,
            instrumentation_power_proven=power["proven"],
        ),
        "verdict_rule": VERDICT_RULE,
        "safety_veto": {
            "endpoint": SAFETY_VETO_ENDPOINT,
            "verdict": veto["verdict"],
            "held_out_violations": veto.get("violations"),
            "natural_gate_power": veto.get("natural_gate_power"),
            "contributes_to_pass": False,
            "reading": (
                "E8 is a mandatory safety veto under the founder ruling of "
                "2026-08-23, option (b). A violation fails the study. Zero "
                "violations is NOT positive held-out evidence and is never "
                "reported as gate power."
            ),
        },
        "e8_instrumentation_power": power,
        "reading_e3": (
            "E3 MET means no silent loss was found among the constructs this "
            "instrument can see. Loss occurring inside the reader, before any fact "
            "exists, remains outside this endpoint. See the protocol's declared "
            "blind spot."
        ),
        "rows": rows,
        "executor": executor,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["result_digest"] = canonical_sha(
        {
            "endpoints": {name: row["verdict"] for name, row in verdicts.items()},
            "summary": body["summary"],
            "cohort_gates": {
                "pairs_scored": gates["pairs_scored"],
                "families": gates["families"],
            },
        }
    )

    written = write_immutable(
        "sfi3-execution-correctness",
        body,
        tool=Path(__file__).resolve(),
        protocol=PROTOCOL,
        run_id=authoritative_score_run_id(body["acquisition_sha256"]),
        pointer=False,
    )
    print(
        json.dumps(
            {
                **written,
                "verdict": body["verdict"],
                "failed": failed,
                "skipped": skipped,
                "cohort_short": short,
            },
            indent=2,
        )
    )
    return 0 if body["verdict"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
