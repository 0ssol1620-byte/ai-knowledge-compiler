#!/usr/bin/env python3
"""Freeze SFI3 — but only if every pre-freeze condition actually holds.

INC-V2-034 is a clause in a protocol with no gate behind it, and it sat unresolved
for weeks because prose cannot refuse. The founder's nineteen pre-freeze conditions
are the same shape and would decay the same way, so this tool exists to make them
executable: the freeze receipt cannot be written unless the conditions that justify
it are checked here and pass.

Three rules this tool follows, each from a defect already in the ledger.

**A condition with no check is not a condition.** Every entry below is either
machine-verified or explicitly marked `ATTESTED`, and an attested entry must name
an evidence artifact — a lane's word is not an artifact. Entries that can be
neither are `UNVERIFIABLE`, which blocks the freeze exactly as a failure does; the
correct response is to build the check, not to lower the bar.

**A gate that accepts every outcome is not a gate** (INC-V2-036). `--dry-run` must
be able to come back red, and the test suite proves it does.

**A green result reported without its scope is not a result** (INC-V2-039,
INC-V2-040). Every command this tool runs is recorded in the receipt verbatim,
including the interpreter, so a later reader can rerun exactly what was run.

Freezing is irreversible in the sense that matters: after it, the first fresh
lineage may be read, and a corpus once looked at is spent. This tool is therefore
fail-closed everywhere, and defaults to refusing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("tools", "acquisition", "compiler"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import preflight_checks as pf  # noqa: E402
from common import now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V3.yaml"
STEM = "sfi3-protocol-freeze"

CONDITION_MET = "PASS"
CONDITION_FAILED = "FAIL"
UNVERIFIABLE = "UNVERIFIABLE"

#: The interpreter the project actually uses. Hardcoded rather than inherited from
#: `sys.executable` because INC-V2-039 was precisely a green produced by whichever
#: python happened to be on PATH, and a freeze gate that could be satisfied from
#: the wrong environment would repeat it at the worst possible moment.
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
SUITE_COMMAND: tuple[str, ...] = (
    "-m",
    "pytest",
    "research/tavonel_eval_v2/tests",
    "-q",
    "-p",
    "no:cacheprovider",
)


class Check:
    """One pre-freeze condition, its verdict, and the evidence for it."""

    def __init__(self, key: str, describe: str, run: Callable[[], dict[str, Any]]):
        self.key = key
        self.describe = describe
        self.run = run

    def evaluate(self) -> dict[str, Any]:
        try:
            outcome = self.run()
        except Exception as error:
            #: A check that raised did not establish its condition. Reporting that
            #: as anything but a block would let an exception become a licence.
            outcome = {
                "verdict": CONDITION_FAILED,
                "detail": f"the check itself raised: {type(error).__name__}: {error}",
            }
        return {"condition": self.key, "describe": self.describe, **outcome}


# ---------------------------------------------------------------------------
# individual checks


def _e8_option_b_applied() -> dict[str, Any]:
    import score_sfi3
    import yaml

    body = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    endpoint = body["endpoints"].get(score_sfi3.SAFETY_VETO_ENDPOINT, {})
    declared = endpoint.get("contributes_to_pass_arithmetic")
    implemented = score_sfi3.SAFETY_VETO_ENDPOINT not in score_sfi3.PRIMARY_ENDPOINTS
    agree = declared is False and implemented
    return {
        "verdict": CONDITION_MET if agree else CONDITION_FAILED,
        "detail": (
            f"protocol declares contributes_to_pass_arithmetic={declared!r}; "
            f"scorer excludes it from PRIMARY_ENDPOINTS={implemented}"
        ),
    }


def _protocol_is_a_draft() -> dict[str, Any]:
    import yaml

    body = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    status = body.get("status")
    return {
        "verdict": CONDITION_MET if status == "DRAFT_NOT_FROZEN" else CONDITION_FAILED,
        "detail": f"status is {status!r}",
        "endpoints": len(body.get("endpoints", {})),
    }


def _no_prior_freeze() -> dict[str, Any]:
    """A second freeze receipt would make the first one ambiguous."""
    found = sorted((NS / "receipts").glob(f"{STEM}--*.json"))
    return {
        "verdict": CONDITION_MET if not found else CONDITION_FAILED,
        "detail": (
            "no prior freeze receipt"
            if not found
            else f"already frozen by {rel(found[-1])}; refusing to freeze twice"
        ),
    }


def _no_fresh_lineage_was_opened() -> dict[str, Any]:
    """The corpus must still be untouched at the moment of the freeze.

    If a lineage expansion or acquisition artifact already exists, something read
    the corpus before the rules were fixed, and freezing now would be theatre.
    """
    forbidden = [
        NS / "artifacts" / "development" / "sfi3_lineages.json",
        NS / "artifacts" / "development" / "sfi3" / "sfi3_acquisition.json",
    ]
    present = [rel(path) for path in forbidden if path.exists()]
    return {
        "verdict": CONDITION_MET if not present else CONDITION_FAILED,
        "detail": (
            "no SFI3 lineage expansion or acquisition artifact exists"
            if not present
            else f"fresh corpus artifacts already present: {present}"
        ),
    }


def _e8_instrumentation_power() -> dict[str, Any]:
    import score_sfi3

    power = score_sfi3.instrumentation_power()
    return {
        "verdict": CONDITION_MET if power["proven"] else CONDITION_FAILED,
        "detail": power.get("why") or "fault injection raised at every stage",
        "receipt": power.get("receipt"),
        "split": "development",
    }


#: The preflight's own field names, reconciled to what it actually writes rather
#: than to what this gate first assumed. Two lanes independently naming the same
#: field is INC-V2-035, which cost this programme a scored run; the rule that came
#: out of it is that the seam reconciles in ONE declared place, and the producer's
#: names win.
#: Written by `tools/identity_change_migration_closure.py`.
CLOSURE_STEM = "identity-change-migration-closure"

#: Written by `tools/rehearse_sfi3_execution.py`.
REHEARSAL_STEM = "sfi3-execution-rehearsal"
ROOT_PREFLIGHT_STEM = "sfi3-root-preflight"
ROOT_VALID_COUNTS_KEY = "valid_root_count_per_family"
ROOT_WIPED_FAMILIES_KEY = "zero_valid_families"


def _root_availability_preflight() -> dict[str, Any]:
    """Roots were checked for existence, and no family was wiped out.

    Deliberately NOT a check that the 200-pair floor is reachable. The preflight
    declined to emit such a verdict, and it was right to: deciding whether a
    partially-depleted family can still yield 200 pairs requires estimating yield,
    which means looking at revision content — the one thing a pre-freeze step may
    never do. A family reduced to zero is the only floor-impossibility this
    instrument can honestly prove, so it is the only one gated here, and the
    shortfall is surfaced rather than silently accepted.
    """
    found = sorted((NS / "receipts").glob(f"{ROOT_PREFLIGHT_STEM}--*.json"))
    if not found:
        return {
            "verdict": CONDITION_FAILED,
            "detail": (
                f"no {ROOT_PREFLIGHT_STEM} receipt. The declared roots have not been "
                "checked for existence, so a family could fail wholesale and only be "
                "discovered after the corpus was already spent"
            ),
        }
    body = json.loads(found[-1].read_text(encoding="utf-8"))
    for required in (ROOT_VALID_COUNTS_KEY, ROOT_WIPED_FAMILIES_KEY):
        if required not in body:
            #: A key the producer does not write is a contract break, not a met
            #: condition. INC-V2-035 again: never default, never infer.
            return {
                "verdict": CONDITION_FAILED,
                "detail": f"receipt has no {required!r}; this gate cannot read it",
                "receipt": rel(found[-1]),
            }
    valid = body[ROOT_VALID_COUNTS_KEY]
    declared = body.get("declared_totals", {})
    wiped = body[ROOT_WIPED_FAMILIES_KEY]
    shortfall = {
        family: {"valid": count, "declared": declared.get(family)}
        for family, count in sorted(valid.items())
        if declared.get(family) is not None and count < declared[family]
    }
    return {
        "verdict": CONDITION_FAILED if wiped else CONDITION_MET,
        "detail": f"valid roots per family: {valid}; families wiped out: {wiped}",
        "receipt": rel(found[-1]),
        "root_shortfall": shortfall,
        "floor_reachability": (
            "NOT ESTABLISHED by this check. Only a wiped-out family is provable "
            "pre-freeze; anything finer needs yield estimation, which would require "
            "reading revision content"
        ),
    }


#: Set on the child process while the suite runs. The suite contains this tool's
#: own tests, and an unguarded check would spawn a suite that spawns a suite: the
#: gate would hang rather than answer. A nested invocation cannot verify anything
#: anyway — it is already inside the run it would be measuring — so it refuses
#: rather than recursing, and refusing blocks the freeze exactly as a failure does.
REENTRY_FLAG = "TAVONEL_SFI3_FREEZE_GATE_RUNNING"


def _suite_is_green() -> dict[str, Any]:
    """Verify one exact, completed external suite receipt pinned by protocol.

    The freeze gate never starts pytest.  Apart from causing the fivefold launch
    in INC-V2-084's predecessor incident, a run inside the gate would be trying
    to certify the suite that contains the gate itself.  The external recorder
    instead gives every test file a fresh process and seals all raw output before
    this function is allowed to report green.
    """
    if os.environ.get(REENTRY_FLAG):
        return {
            "verdict": UNVERIFIABLE,
            "detail": (
                "nested invocation: this check is running inside the suite it would "
                "run. It cannot verify the run it is part of, so it refuses"
            ),
        }
    import record_sfi3_suite_evidence as suite_evidence
    import yaml

    protocol = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    named = protocol.get("suite_evidence") or {}
    if set(named) != {"schema", "receipt", "sha256"}:
        return {
            "verdict": CONDITION_FAILED,
            "detail": "protocol suite_evidence must contain exactly schema, receipt, sha256",
        }
    if named.get("schema") != suite_evidence.SCHEMA:
        return {"verdict": CONDITION_FAILED, "detail": "wrong suite-evidence schema pin"}

    relative = Path(str(named.get("receipt", "")))
    if relative.is_absolute() or ".." in relative.parts:
        return {
            "verdict": CONDITION_FAILED,
            "detail": "suite receipt path is not repository-relative",
        }
    receipt = (ROOT / relative).resolve()
    try:
        receipt.relative_to(ROOT.resolve())
    except ValueError:
        return {"verdict": CONDITION_FAILED, "detail": "suite receipt escapes repository"}
    if not receipt.is_file():
        return {"verdict": CONDITION_FAILED, "detail": f"suite receipt is absent: {relative}"}
    if sha_file(receipt) != named.get("sha256"):
        return {"verdict": CONDITION_FAILED, "detail": "suite receipt file digest mismatch"}

    try:
        body = json.loads(receipt.read_text(encoding="utf-8"))
        bare = {key: value for key, value in body.items() if key != "receipt_sha256"}
        from common import canonical_sha

        if body.get("receipt_sha256") != canonical_sha(bare):
            raise ValueError("suite receipt envelope digest mismatch")
        if body.get("schema") != suite_evidence.SCHEMA:
            raise ValueError("suite receipt schema mismatch")
        if body.get("completed") is not True or body.get("exit_code") != 0:
            raise ValueError("suite did not complete successfully")
        if body.get("failure_count") != 0 or body.get("error_count") != 0:
            raise ValueError("suite receipt records failures or errors")
        if not isinstance(body.get("test_count"), int) or body["test_count"] <= 0:
            raise ValueError("suite receipt has no executed tests")
        if not isinstance(body.get("skip_count"), int) or body["skip_count"] < 0:
            raise ValueError("suite receipt has an invalid skip count")

        current_suite = suite_evidence.suite_manifest()
        current_tooling = suite_evidence.tooling_manifest()
        if body.get("suite_manifest") != current_suite:
            raise ValueError("suite manifest drifted after the external run")
        if body.get("suite_manifest_sha256") != current_suite["digest"]:
            raise ValueError("suite manifest digest mismatch")
        if body.get("tooling_manifest") != current_tooling:
            raise ValueError("tooling manifest drifted after the external run")
        if body.get("tooling_manifest_sha256") != current_tooling["digest"]:
            raise ValueError("tooling manifest digest mismatch")

        expected_files = [row["path"] for row in current_suite["files"]]
        shards = body.get("shards")
        if not isinstance(shards, list):
            raise ValueError("suite receipt has no shard list")
        actual_files = [row.get("test_file") for row in shards if isinstance(row, dict)]
        if actual_files != expected_files or len(set(actual_files)) != len(expected_files):
            raise ValueError("suite shards are missing, duplicated, or reordered")
        if body.get("test_file_count") != len(expected_files) or body.get("shard_count") != len(
            shards
        ):
            raise ValueError("suite shard counts do not cover the manifest")
        if any(
            row.get("exit_code") != 0
            or row.get("junit_error") is not None
            or row.get("failures") != 0
            or row.get("errors") != 0
            for row in shards
        ):
            raise ValueError("one or more suite shards are not green")
        if sum(row["tests"] for row in shards) != body["test_count"]:
            raise ValueError("suite test count does not equal shard evidence")
        if sum(row["skipped"] for row in shards) != body["skip_count"]:
            raise ValueError("suite skip count does not equal shard evidence")

        output_relative = Path(str(body.get("output_file", "")))
        if output_relative.is_absolute() or ".." in output_relative.parts:
            raise ValueError("suite output path is not repository-relative")
        output = (ROOT / output_relative).resolve()
        output.relative_to(ROOT.resolve())
        if not output.is_file() or sha_file(output) != body.get("output_file_sha256"):
            raise ValueError("suite raw output is missing or drifted")
        if body.get("reentry_guard_set_in_every_shard") != REENTRY_FLAG:
            raise ValueError("suite did not set the re-entry guard")
        if body.get("latest_pointer_is_evidence") is not False:
            raise ValueError("a mutable latest pointer cannot be suite evidence")
        if datetime.fromisoformat(body["started_at"]) >= datetime.fromisoformat(
            body["completed_at"]
        ):
            raise ValueError("suite timestamps are not strictly ordered")
        provenance = body.get("provenance") or {}
        if provenance.get("tool") != rel(suite_evidence.THIS_TOOL):
            raise ValueError("suite evidence was written by the wrong tool")
        if provenance.get("tool_sha256") != sha_file(suite_evidence.THIS_TOOL):
            raise ValueError("suite evidence tool drifted")
        if provenance.get("immutable") is not True or provenance.get("protocol") is not None:
            raise ValueError("suite evidence provenance is not the external immutable form")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {"verdict": CONDITION_FAILED, "detail": f"suite evidence refused: {error}"}

    return {
        "verdict": CONDITION_MET,
        "detail": f"external suite completed: {body['test_count']} tests, {body['skip_count']} skipped",
        "receipt": rel(receipt),
        "receipt_file_sha256": named["sha256"],
        "command": body["command"],
        "returncode": body["exit_code"],
        "peak_rss_bytes": body.get("peak_rss_bytes"),
    }


def _claim_pins_match() -> dict[str, Any]:
    verifier = NS / "tools" / "verify_claim_pins.py"
    if not verifier.exists():
        return {
            "verdict": UNVERIFIABLE,
            "detail": "tools/verify_claim_pins.py does not exist yet",
        }
    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(verifier)],
        cwd=str(NS),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "verdict": CONDITION_MET if completed.returncode == 0 else CONDITION_FAILED,
        "detail": (completed.stdout.strip().splitlines() or [""])[-1],
        "returncode": completed.returncode,
    }


def _four_link_gate_exists() -> dict[str, Any]:
    """INC-V2-034 must be an executable gate, or explicitly sealed as a blocker."""
    gate = NS / "tools" / "four_link_gate.py"
    if not gate.exists():
        return {
            "verdict": CONDITION_FAILED,
            "detail": (
                "tools/four_link_gate.py does not exist. INC-V2-034's four-link clause "
                "is still prose, and a clause with no gate behind it is what INC-V2-034 "
                "IS"
            ),
        }
    return {
        "verdict": CONDITION_MET,
        "detail": f"{rel(gate)} exists; it gates GPU entry, not the SFI3 result",
        "note": "separate hard gate, deliberately not mixed into the held-out arithmetic",
    }


#: Development shadows that MEASURE a defect are not repairs of it. Both lanes
#: were explicitly scoped to build a contract and a shadow without touching
#: Protected Core, and both did exactly that and said so. The production path is
#: unchanged, so freezing now would spend a held-out corpus to rediscover a defect
#: already measured in development.
def _resolve_receipt(relative: str) -> Path | None:
    """A repo-relative receipt path from an acceptance, or None if it is gone."""
    candidate = ROOT / relative
    return candidate if candidate.is_file() else None


def _latest_receipt(stem: str) -> Path | None:
    """The newest immutable receipt with this stem, or None.

    Receipt names carry a UTC timestamp, so lexical order is chronological.
    """
    found = sorted((NS / "receipts").glob(stem + "--*.json"))
    return found[-1] if found else None


def _case_only_probe() -> dict[str, Any]:
    """Does production, right now, fold a case-only edit identity-equal AND
    still emit a change for it?

    Both halves are the condition, and either alone is satisfiable by a broken
    system. If the fold had been made content-sensitive the change would be
    caught and identity continuity silently destroyed; if the fold were intact
    but the predicate still rode on it, the change would vanish. So both are
    measured against live production rather than read out of a receipt.
    """
    sys.path.insert(0, str(NS / "compiler"))
    import selective_build as engine
    from akc_cir.identity import normalize_text_for_identity

    before_text = "we know the contents at compile time, so the text is hard coded"
    after_text = "We know the contents at compile time, so the text is hard coded"
    folds_equal = normalize_text_for_identity(before_text) == normalize_text_for_identity(
        after_text
    )

    def _doc(text: str) -> dict[str, Any]:
        bodies = [
            (["Intro"], text),
            (["Body"], "a second section that does not change at all in this revision"),
        ]
        records = [
            {
                "explicit_path": path,
                "heading": path[-1],
                "ordinal": index,
                "text": body,
                "text_sha256": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
            }
            for index, (path, body) in enumerate(bodies)
        ]
        return {
            "schema": "tavonel.v2.canonical_document.v1",
            "source_family": "git_docs",
            "source_id": "freeze-gate:case-only-probe",
            "version_id": "v",
            "version_time": {"valid_from": None, "known_at": None},
            #: Derived from the records, so the two revisions differ here exactly
            #: when their text differs. `hash()` would be salted per process and
            #: would make this probe non-reproducible across runs.
            "source_digest": "sha256:"
            + hashlib.sha256(json.dumps(records, sort_keys=True).encode("utf-8")).hexdigest(),
            "license": "test",
            "units": records,
            "structure": {
                "order": ["/".join(record["explicit_path"]) for record in records],
                "block_count": len(records),
            },
        }

    result = engine.run_pair(_doc(before_text), _doc(after_text))
    full = engine.build_all(_doc(after_text))
    stale = [
        artifact
        for artifact in result["carried_forward_set"]
        if result["state"][artifact] != full[artifact]
    ]
    return {
        "identity_folds_equal": folds_equal,
        "stale_artifacts": sorted(stale),
        "carried_forward_count": len(result["carried_forward_set"]),
    }


def _identity_change_separation_complete() -> dict[str, Any]:
    """The INC-V2-037 migration, measured rather than attested.

    This check used to return a fixed CONDITION_FAILED carrying a sentence that
    said the ladder stopped at the differential. That was true when it was
    written and became false without the check noticing -- the same defect class
    the protocol exists to catch, pointed the other way: a check that can only
    say one thing has not checked anything. It now reads the ladder's own
    receipts and then asks production directly.
    """
    shadow = NS / "source_fact_ir" / "change_facets.py"
    contract = NS / "docs" / "COMPAT_IDENTITY_CHANGE_SEPARATION.md"
    if not (shadow.exists() and contract.exists()):
        return {"verdict": CONDITION_FAILED, "detail": "no shadow or no compatibility contract"}

    benchmark = _latest_receipt("identity-change-benchmark")
    canary = _latest_receipt("identity-change-canary")
    if benchmark is None or canary is None:
        missing = [
            name for name, path in (("benchmark", benchmark), ("canary", canary)) if path is None
        ]
        return {
            "verdict": CONDITION_FAILED,
            "detail": (
                "the Protected Core ladder requires a corpus-scale benchmark and a canary "
                "before the production switch; no receipt for: " + ", ".join(missing)
            ),
        }

    bench_body = json.loads(benchmark.read_text(encoding="utf-8"))
    canary_body = json.loads(canary.read_text(encoding="utf-8"))
    overall = bench_body.get("overall", {})
    faults: list[str] = []

    #: Under-fire is the number that must be zero: anything the old predicate
    #: caught and the new one misses is a regression, and this migration exists
    #: to stop misses. Over-fire is a cost, reported below and deliberately NOT
    #: gated -- no threshold in this repository is calibrated, and inventing a
    #: rate bar here would present an uncalibrated number as a measured one.
    if overall.get("under_fire_rate_over_matched_pairs") != 0.0:
        faults.append("under-fire is " + str(overall.get("under_fire_rate_over_matched_pairs")))
    if overall.get("pairs_with_any_under_fire") != 0:
        faults.append(str(overall.get("pairs_with_any_under_fire")) + " pair(s) under-fire")

    #: Identity continuity: which units MATCH must be untouched by a change
    #: predicate. Non-zero here means the fold was made content-sensitive.
    if overall.get("identity_records_disagree_pairs") != 0:
        faults.append(
            str(overall.get("identity_records_disagree_pairs"))
            + " pair(s) disagree on identity records"
        )
    if overall.get("pairs_unresolved"):
        faults.append(str(overall.get("pairs_unresolved")) + " benchmark pair(s) unresolved")
    if not overall.get("pairs_resolved"):
        faults.append("the benchmark resolved no pairs, so it measured nothing")

    if canary_body.get("verdict") != "PASS":
        faults.append("canary verdict is " + str(canary_body.get("verdict")))
    passed = canary_body.get("non_tautological_checks_passed")
    total = canary_body.get("non_tautological_checks_total")
    if not total or passed != total:
        faults.append("canary non-tautological checks " + str(passed) + "/" + str(total))

    #: The prospective closure, which outranks everything above it.
    #:
    #: The two receipts read above are RETROSPECTIVE: measured after the
    #: production switch had already shipped, by the agent that wrote the check
    #: grading them (INC-V2-042). The founder's ruling reclassified them as a
    #: migration safety regression and required a prospectively frozen closure
    #: with outcome-independent, threshold-free criteria. That closure is the
    #: evidence this condition actually turns on; a green reading from the
    #: retrospective pair alone would be this gate reporting the more
    #: comfortable of two measurements.
    #: NOT a glob. `_latest_receipt(CLOSURE_STEM)` matched only V1's closure --
    #: V2R1, V2R2, V2R3 and V2R3R1 all write different stems, so four successors
    #: in a row were invisible to this gate and it could not say so
    #: (INC-V2-069). "Whatever sorted last under a name that looks about right"
    #: is not a binding, and repointing the glob at a newer stem would break the
    #: same way at the next successor.
    #:
    #: The closure is now named by an explicit acceptance receipt that carries
    #: its protocol id, run id and digests, and `mca.verify` re-checks every one
    #: of them against disk -- including that the measurement carries all eight
    #: invariant blocks as SET EQUALITY, which is the clause INC-V2-067's
    #: receipt could not have satisfied.
    import migration_closure_acceptance as mca

    acceptance_path = mca.latest_acceptance(NS / "receipts")
    closure = None
    closure_body: dict[str, Any] = {}
    acceptance: dict[str, Any] | None = None
    if acceptance_path is None:
        faults.append(
            f"no {mca.STEM} receipt for {mca.ACCEPTED_PROTOCOL_ID}: the migration "
            "has a retrospective safety regression and no accepted prospective "
            "closure, which is the state INC-V2-042 records rather than a state "
            "that satisfies it"
        )
    else:
        try:
            acceptance = mca.verify(json.loads(acceptance_path.read_text(encoding="utf-8")))
            closure = _resolve_receipt(acceptance["measurement_receipt"])
            closure_body = {
                "overall": acceptance["overall"],
                "invariants": acceptance["invariants"],
            }
        except mca.AcceptanceRefused as error:
            faults.append(
                f"the migration closure acceptance does not hold: {error}. A "
                "closure that does not close is not closed by the age of the "
                "receipts beside it"
            )

    probe = _case_only_probe()
    if not probe["identity_folds_equal"]:
        faults.append(
            "normalize_text_for_identity no longer folds a case-only pair equal: identity "
            "continuity has been broken by the migration"
        )
    if probe["stale_artifacts"]:
        faults.append("case-only edit still leaves stale: " + str(probe["stale_artifacts"]))
    if not probe["carried_forward_count"]:
        faults.append("the probe carried nothing forward, so it could not have shown a stale one")

    return {
        "verdict": CONDITION_FAILED if faults else CONDITION_MET,
        "detail": (
            "; ".join(faults)
            if faults
            else (
                "ladder complete: "
                + str(overall.get("pairs_resolved"))
                + " real revision pairs, "
                + str(overall.get("matched_pairs_total"))
                + " matched units, under-fire 0, identity records unchanged, canary "
                + str(passed)
                + "/"
                + str(total)
                + "; production probe folds identity-equal and still catches the change"
            )
        ),
        "benchmark_receipt": rel(benchmark),
        "canary_receipt": rel(canary),
        "retrospective_receipts_classification": (
            "RETROSPECTIVE MIGRATION SAFETY REGRESSION, not prospective ladder "
            "qualification (founder ruling on INC-V2-042). They are necessary and "
            "not sufficient"
        ),
        "prospective_closure_receipt": rel(closure) if closure else None,
        "prospective_closure_overall": closure_body.get("overall"),
        "closure_acceptance_receipt": rel(acceptance_path) if acceptance_path else None,
        "closure_acceptance": acceptance,
        "closure_bound_by": (
            "an explicit MIGRATION_CLOSURE_ACCEPTANCE_V1 receipt naming protocol "
            "id, run id and digests -- never a stem glob or a 'latest' pointer"
        ),
        "production_probe": probe,
        "over_fire_reported_not_gated": {
            "rate_over_matched_pairs": overall.get("over_fire_rate_over_matched_pairs"),
            "on_confirmed_defect_lineages": overall.get("over_fires_on_confirmed_defect_lineages"),
            "why_not_gated": (
                "over-fire is the stated price of the fix, not a threshold to tune against; "
                "no bar in this repository is calibrated"
            ),
        },
    }


def _five_channel_contract_complete() -> dict[str, Any]:
    """Every declared typed change resolves to a seed set, measured by running
    the E9 oracle against the production planner.

    Also a fixed CONDITION_FAILED until now, for the same reason and with the
    same problem. The expected side comes from the declarative dependency
    contract, never from the planner, so this compares an independent
    expectation against production rather than production against itself.
    """
    contract = NS / "compiler" / "dependency_contract.py"
    if not contract.exists():
        return {"verdict": CONDITION_FAILED, "detail": "no dependency contract module"}

    sys.path.insert(0, str(NS / "compiler"))
    import e9_oracle as e9

    results = e9.run_all()
    measured = [r.channel_name for r in results]
    faults: list[str] = []

    #: Non-vacuity first. A run that produced two channels instead of five would
    #: otherwise report "every channel passed" while three went unexamined.
    if len(measured) != 5:
        faults.append("expected 5 channels, measured " + str(len(measured)) + ": " + str(measured))
    for result in results:
        if result.verdict != "PASS":
            faults.append(result.channel_name + "=" + str(result.verdict))
        if result.silent_disappearance:
            faults.append(
                result.channel_name
                + " silent disappearance: "
                + str(sorted(result.silent_disappearance))
            )
        if result.decision.verdict.value == "seed_set" and not result.decision.dependents:
            faults.append(result.channel_name + " resolved to an empty seed set")

    return {
        "verdict": CONDITION_FAILED if faults else CONDITION_MET,
        "detail": (
            "; ".join(faults)
            if faults
            else "all " + str(len(measured)) + " declared channels resolve to a seed set, 0 silent"
        ),
        "channels": {r.channel_name: r.verdict for r in results},
        "expected_side_source": (
            "declarative dependency contract (declared facet sensitivity), not the planner"
        ),
    }


def _post_freeze_pipeline_exists() -> dict[str, Any]:
    """Can the protocol this gate is about to seal actually be executed?

    Not one of the founder's nineteen conditions, and it belongs here anyway.
    Every one of those nineteen asks whether the SCIENCE is ready; none asks
    whether the machinery that would carry it out exists. A freeze is a
    one-way door -- `_no_prior_freeze` blocks a second one -- and the step
    immediately after it in the declared order is fresh acquisition, which
    spends the corpus. Sealing the rules and then discovering there is no
    worker to run them, or no aggregation block for an endpoint the scorer
    demands, would leave the study holding a spent corpus and a protocol it
    cannot execute or re-freeze.

    So this asks the mechanical question the others assume: worker, scorer,
    frame, and one aggregation block per endpoint the scorer refuses to
    default. `score_sfi3` raises `ContractBroken` rather than recording
    SKIPPED when a block is missing, which is the right behaviour and is why
    a missing block must be caught before the freeze rather than after the
    corpus is gone.
    """
    import rehearse_sfi3_execution

    required_files = {
        "acquisition worker": NS / "tools" / "sfi3_worker.py",
        "scorer": NS / "tools" / "score_sfi3.py",
        "frame": NS / "acquisition" / "sources_sfi3.py",
        "equivalence summariser": NS / "compiler" / "rebuild_equivalence.py",
    }
    missing = sorted(name for name, path in required_files.items() if not path.exists())

    #: The blocks the scorer reads out of the summariser, taken from the scorer
    #: itself rather than restated -- a list maintained alongside it would drift,
    #: and drift here is invisible until the corpus is already spent.
    absent_blocks: list[str] = []
    summariser = required_files["equivalence summariser"]
    if summariser.exists():
        sys.path.insert(0, str(NS / "tools"))
        import score_sfi3

        text = summariser.read_text(encoding="utf-8")
        for _endpoint, block, _count_key, _list_key in score_sfi3.EXECUTOR_BLOCKS:
            if block not in text:
                absent_blocks.append(block)

    faults: list[str] = []
    if missing:
        faults.append("missing: " + ", ".join(missing))
    if absent_blocks:
        faults.append(
            "the summariser emits no block for: "
            + ", ".join(absent_blocks)
            + " -- the scorer raises ContractBroken on an absent block, so this "
            "would fail only after the corpus had been spent"
        )

    #: Existence is not readiness. The founder's ruling on INC-V2-043 is explicit
    #: that a freeze gate must not pass merely because files exist, so the
    #: rehearsal receipt is what this condition actually turns on: a development
    #: cohort carried end to end through worker, reduction, summariser and
    #: scorer, WITH negative controls proving the path comes back red when an
    #: E8/E9 violation or a schema defect is injected. A green rehearsal with no
    #: negative controls would be the always-PASS check of INC-V2-044.
    rehearsal = _latest_receipt(REHEARSAL_STEM)
    rehearsal_body: dict[str, Any] = {}
    if rehearsal is None:
        faults.append(
            f"no {REHEARSAL_STEM} receipt: the execution path has never been carried "
            "end to end on development fixtures, and file existence is not readiness"
        )
    else:
        rehearsal_body = json.loads(rehearsal.read_text(encoding="utf-8"))
        if rehearsal_body.get("verdict") != "PASS":
            faults.append(f"rehearsal verdict is {rehearsal_body.get('verdict')}")
        if rehearsal_body.get("opened_fresh_payload"):
            faults.append(
                "the rehearsal opened fresh SFI3 payload, which spends the corpus it "
                "was supposed to be rehearsing for"
            )
        controls = int(rehearsal_body.get("negative_controls_passed") or 0)
        if not controls:
            faults.append(
                "the rehearsal ran no negative controls, so it proved the path can "
                "succeed and nothing about whether it can fail"
            )
        positive = rehearsal_body.get("positive_path") or {}
        readable = set(positive.get("endpoints_readable") or ())
        #: EXECUTOR_BLOCKS is keyed by endpoint first, so compare on that.
        unreadable = [
            endpoint
            for endpoint, _block, _count, _names in score_sfi3.EXECUTOR_BLOCKS
            if endpoint not in readable
        ]
        if unreadable:
            faults.append("the rehearsal could not read: " + ", ".join(unreadable))
        if not positive.get(rehearse_sfi3_execution.E9_GATE_POWER_KEY):
            faults.append(
                "no rehearsal fixture put E9 at risk, so the rehearsal would not "
                "have noticed a silent disappearance"
            )

    return {
        "verdict": CONDITION_FAILED if faults else CONDITION_MET,
        "detail": (
            "; ".join(faults)
            if faults
            else (
                "worker, scorer, frame and every scored aggregation block are present, "
                f"and the execution path was carried end to end on development fixtures "
                f"with {rehearsal_body.get('negative_controls_passed')} negative control(s)"
            )
        ),
        "files_checked": {name: path.exists() for name, path in required_files.items()},
        "absent_summariser_blocks": absent_blocks,
        "rehearsal_receipt": rel(rehearsal) if rehearsal else None,
    }


def _sfi3_root_reservation_honoured() -> dict[str, Any]:
    """Verify the exact administrative predecessor handoff pinned by protocol.

    INC-V2-084 established that the historical V2R4 attestation never carried
    the successor-facing fields an earlier version of this gate assumed.  The
    additive handoff is therefore the authority here.  It binds the historical
    artifacts without changing them and is resolved only by the exact path and
    file digest in the still-draft SFI3 protocol.
    """
    import v2r4_sfi3_reservation_handoff as handoff
    import yaml

    protocol = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    named = protocol.get("predecessor_handoff") or {}
    if set(named) != {"schema", "receipt", "sha256"}:
        return {
            "verdict": CONDITION_FAILED,
            "detail": "protocol predecessor_handoff must contain exactly schema, receipt, sha256",
        }
    if named.get("schema") != handoff.SCHEMA:
        return {
            "verdict": CONDITION_FAILED,
            "detail": f"wrong predecessor handoff schema: {named.get('schema')!r}",
        }

    relative = Path(str(named.get("receipt", "")))
    if relative.is_absolute() or ".." in relative.parts:
        return {
            "verdict": CONDITION_FAILED,
            "detail": "predecessor handoff path must be an exact repository-relative path",
        }
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        return {"verdict": CONDITION_FAILED, "detail": "predecessor handoff escapes repository"}
    if not path.is_file():
        return {"verdict": CONDITION_FAILED, "detail": f"missing predecessor handoff: {relative}"}
    if sha_file(path) != named.get("sha256"):
        return {"verdict": CONDITION_FAILED, "detail": "predecessor handoff file digest mismatch"}

    try:
        verified = handoff.verify(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError, handoff.HandoffRefused) as error:
        return {"verdict": CONDITION_FAILED, "detail": f"handoff refused: {error}"}

    return {
        "verdict": CONDITION_MET,
        "detail": (
            "the exact protocol-pinned administrative V2R4/SFI3 handoff verifies; "
            "chronology, equivalence and identity-only separation hold"
        ),
        "handoff_receipt": rel(path),
        "handoff_file_sha256": named["sha256"],
        "handoff_schema": verified["schema"],
        "declared_containers_sha256": verified["declared_containers_sha256"],
        "collision_count": verified["collision_count"],
        "actual_frozen_roots_checked_at_sfi3_rung_0": True,
        "no_v2r4_outcome_was_read": True,
    }


def _attested(detail: str) -> Callable[[], dict[str, Any]]:
    """A condition a lane reported but this gate cannot itself verify."""
    return lambda: {"verdict": UNVERIFIABLE, "detail": detail}


#: Every condition the protocol declares, mapped to a check. The mapping is keyed
#: by the protocol's own wording so that adding a condition there without adding a
#: check here leaves it UNVERIFIABLE, which blocks. A gate whose checklist is
#: shorter than the list it claims to enforce is the same defect as a gate placed
#: where failure is impossible: it reports green about things it never looked at.
CONDITION_CHECKS: dict[str, Callable[[], dict[str, Any]]] = {
    "Windows stale-lock resolved": _suite_is_green,
    "suite stable": _suite_is_green,
    "causal wording corrected": pf.causal_wording_consistency,
    "incident cross-refs coherent": pf.incident_cross_reference_coherence,
    "identity/change separation complete": _identity_change_separation_complete,
    "five-channel contract complete": _five_channel_contract_complete,
    "E9 independent oracle and gate-power tests complete": _suite_is_green,
    "E8 option (b) applied": _e8_option_b_applied,
    "E8 fault-injection power proven": _e8_instrumentation_power,
    "dynamic include-target fail-closed complete": pf.dynamic_include_target_closure,
    "artifact facet/fingerprint propagation verified": pf.artifact_facet_fingerprint_propagation,
    "claim pins byte-match": _claim_pins_match,
    "scorer/executor seam tests green": _suite_is_green,
    "spent-set streaming preserved": _suite_is_green,
    "78-root availability-only preflight complete": _root_availability_preflight,
    "fresh frame disjointness complete": pf.fresh_frame_disjointness,
    "SFI2 14 forensic cases excluded": pf.sfi2_forensic_lineages_excluded,
    "no fresh SFI3 payload read": _no_fresh_lineage_was_opened,
    "INC-V2-034 four-link gate implemented and tested, or sealed as a separate hard blocker": (
        _four_link_gate_exists
    ),
    "execution readiness rehearsed end to end on development fixtures, with negative "
    "controls, and no fresh SFI3 payload opened": _post_freeze_pipeline_exists,
    "SFI3 roots inside SFI3_ROOT_RESERVATION_V1 and disjoint from V2R4's frozen "
    "containers": _sfi3_root_reservation_honoured,
}

#: Structural conditions this gate adds on its own behalf.
STRUCTURAL_CHECKS: tuple[Check, ...] = (
    Check("protocol_is_a_draft", "the protocol has not already been frozen", _protocol_is_a_draft),
    Check("no_prior_freeze", "no earlier freeze receipt exists", _no_prior_freeze),
    Check(
        "post_freeze_pipeline_exists",
        "the sealed protocol can actually be executed",
        _post_freeze_pipeline_exists,
    ),
)


def _protocol_conditions() -> list[str]:
    import yaml

    body = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    return [str(item) for item in body.get("pre_freeze_conditions", [])]


def build_checks() -> tuple[Check, ...]:
    """One check per declared condition, plus this gate's own structural ones.

    Derived from the protocol rather than hardcoded, so the checklist cannot fall
    silently behind the list it enforces.
    """
    checks = list(STRUCTURAL_CHECKS)
    for condition in _protocol_conditions():
        run = CONDITION_CHECKS.get(condition)
        if run is None:
            run = _attested(
                "this condition is declared in the protocol but no check is mapped to "
                "it here, so nothing has verified it"
            )
        checks.append(Check(condition, condition, run))
    return tuple(checks)


CHECKS: tuple[Check, ...] = build_checks()


def evaluate_all() -> dict[str, Any]:
    results = [check.evaluate() for check in CHECKS]
    blocking = [row for row in results if row["verdict"] != CONDITION_MET]
    return {
        "checks": results,
        "blocking": [row["condition"] for row in blocking],
        "may_freeze": not blocking,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="evaluate the conditions and report, without writing a freeze receipt",
    )
    arguments = parser.parse_args(argv)

    report = evaluate_all()
    body: dict[str, Any] = {
        "schema": "tavonel.v2.sfi3_protocol_freeze.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "generated_at": now(),
        "interpreter_for_suite": rel(VENV_PYTHON),
        **report,
        "meaning": (
            "the rules of SFI3 are fixed as of this digest. After this receipt exists "
            "the first fresh lineage may be read, and a corpus once looked at is spent"
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    if not report["may_freeze"]:
        print(
            json.dumps(
                {"may_freeze": False, "blocking": report["blocking"], "checks": report["checks"]},
                indent=2,
                ensure_ascii=False,
            )
        )
        print(
            f"REFUSING TO FREEZE: {len(report['blocking'])} condition(s) not met",
            file=sys.stderr,
        )
        return 4

    if arguments.dry_run:
        print(json.dumps({"may_freeze": True, "checks": report["checks"]}, indent=2))
        return 0

    written = write_immutable(STEM, body, tool=Path(__file__).resolve(), protocol=PROTOCOL)
    print(json.dumps({**written, "may_freeze": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
