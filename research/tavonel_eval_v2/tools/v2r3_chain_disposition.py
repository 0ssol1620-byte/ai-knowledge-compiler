"""Adjudicate the aborted V2R3 chain, and prove nothing was disclosed from it.

WHY THIS EXISTS. A stale test called the V2R3 scorer after the chain had frozen.
It traversed the real 300-pair cohort and died in census aggregation with
``KeyError: 'effective'`` before ``run()`` returned. The founder ruling of
2026-08-26 classified that event PRE_RESULT_EXECUTION_ATTEMPT /
INSTRUMENT_RUNTIME_CRASH / NO_SCORE, and made the corpus eligible for exact
carry-forward into a successor protocol -- CONDITIONAL on this file's proof.

THE THREAT MODEL IS OUTCOME-INFORMED OPTIONALITY, not computation. The crashing
process necessarily built pair-level structures in memory. That alone spends
nothing. What would spend the corpus is an experimenter LEARNING something
outcome-bearing and then being free to change the pairs, the thresholds, the
semantics or the decision to run again. So the question this module answers is
narrow and mechanical: could any outcome value have reached a human or a file?

FOUR INDEPENDENT LEGS, because one of them alone would be an argument rather
than a proof:

    1. NO RESULT RECEIPT      -- the measurement stem has no receipt.
    2. NO PERSISTED OUTCOME   -- no file anywhere in the namespace carries the
                                 result schema or an outcome-bearing key.
    3. NO OUTPUT PATH IN run  -- an AST proof that `run()` contains no output
                                 statement at all, and that every outcome print
                                 in `main()` is dominated by `body = run()`.
                                 Since the KeyError escaped `run()`, that path
                                 was unreachable.
    4. NO FRAME INSPECTION    -- pytest is configured without `--showlocals`,
                                 so the traceback could not have rendered
                                 `extra`, `pair_results` or any census value;
                                 plus the operator declaration.

Leg 3 is the load-bearing one and it is the one most easily faked by prose. It
is computed from the scorer's own syntax tree here, not asserted.

WHAT THIS MODULE MAY NOT DO. It does not read a V2R3 outcome in order to prove
there is none -- there is nothing to read, and a proof that had to open a result
would be self-defeating. It never edits, moves or deletes a V2R3 receipt: the
aborted chain is preserved immutably and its adjudication is APPENDED as a new
receipt beside it.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from evidence import write_immutable  # noqa: E402

NON_DISCLOSURE_STEM = "identity-change-migration-closure-v2r3-non-disclosure"
DISPOSITION_STEM = "identity-change-migration-closure-v2r3-chain-disposition"
SCHEMA_NON_DISCLOSURE = "tavonel.v2.identity_change_migration_closure.v2r3_non_disclosure.v1"
SCHEMA_DISPOSITION = "tavonel.v2.identity_change_migration_closure.v2r3_chain_disposition.v1"

#: The scorer whose crash is being adjudicated.
SCORER = NS / "tools" / "identity_change_migration_closure_v2r3.py"

#: The stem a V2R3 measurement would have used.
MEASUREMENT_STEM = "identity-change-migration-closure-v2r3"

#: Every stem the aborted chain legitimately produced. Anything else matching
#: the measurement glob is an outcome artefact and refuses.
CHAIN_STEMS = (
    "identity-change-migration-closure-v2r3-acquisition-frame-freeze",
    "identity-change-migration-closure-v2r3-frame-attestation",
    "identity-change-migration-closure-v2r3-protocol-freeze",
    "identity-change-migration-closure-v2r3-protocol-attestation",
    "identity-change-migration-closure-v2r3-universe",
    "identity-change-migration-closure-v2r3-universe-attestation",
    "identity-change-migration-closure-v2r3-scorer-freeze",
    "identity-change-migration-closure-v2r3-exclusion-freeze",
    NON_DISCLOSURE_STEM,
    DISPOSITION_STEM,
)

#: Keys that only a graded result carries. The universe receipt has pairs and
#: digests; none of it has these.
OUTCOME_KEYS = (
    "INVARIANT_6_ambiguous_identity_stays_unresolved",
    "effective_census",
    "unsettled_identities_total",
    "violation_count",
)
RESULT_SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r3_result.v1"

#: Directories swept for a persisted outcome. `receipts` and `artifacts` are
#: where anything durable would land; the rest catch a scratch file dropped
#: beside the tools.
SWEPT = ("receipts", "artifacts", "docs", "protocols", "tools", "tests", "acquisition")

#: Names whose value would be outcome-bearing if a traceback rendered them.
FRAME_LOCALS = (
    "pair_results",
    "extra",
    "invariant_6_violations",
    "observations",
    "census",
    "c_violations",
    "d_violations",
    "e_violations",
    "a_b_violations",
)


class DisclosureFound(RuntimeError):
    """Something outcome-bearing survived the crash. Carry-forward is refused."""


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# leg 1 + 2: nothing was persisted


def _no_result_receipt() -> dict[str, Any]:
    receipts = sorted((NS / "receipts").glob(f"{MEASUREMENT_STEM}--*.json"))
    strays = [
        path.name
        for path in receipts
        if not any(path.name.startswith(f"{stem}--") for stem in CHAIN_STEMS)
    ]
    if strays:
        raise DisclosureFound(
            f"a V2R3 receipt exists that is not part of the aborted freeze chain: "
            f"{strays}. That is a measurement or a result and the corpus is spent."
        )
    return {
        "held": True,
        "measurement_stem": MEASUREMENT_STEM,
        "chain_receipts": sorted(path.name for path in receipts),
        "chain_receipt_count": len(receipts),
        "result_receipts": [],
        "how": (
            "every receipt matching the measurement glob was matched against the "
            "declared chain stems. A file the chain does not explain is a result."
        ),
    }


def _outcome_dict_keys(node: Any, path: str = "") -> list[str]:
    """Where an outcome key appears as an actual dict KEY, never as a substring.

    The distinction is not pedantic. V2R3's protocol-freeze receipt contains the
    string `INVARIANT_6_ambiguous_identity_stays_unresolved` inside a prose field
    describing what the run WOULD measure. A substring sweep calls that a
    disclosure and refuses forever for the wrong reason -- which is INC-V2-044
    inverted: a check that can only return one answer is not a measurement,
    whichever answer it is stuck on.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in OUTCOME_KEYS:
                found.append(f"{path}/{key}")
            found.extend(_outcome_dict_keys(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_outcome_dict_keys(value, f"{path}[{index}]"))
    return found


def _declares_result_schema(node: Any) -> bool:
    """Whether any object in this body says `"schema": <the V2R3 result schema>`.

    That is where a graded result carries it. A field NAMED `result_schema`
    holding the same string is a declaration of what was searched for, which is
    what this module's own attestation contains.
    """
    if isinstance(node, dict):
        if node.get("schema") == RESULT_SCHEMA:
            return True
        return any(_declares_result_schema(value) for value in node.values())
    if isinstance(node, list):
        return any(_declares_result_schema(value) for value in node)
    return False


#: `v2r3` but not `v2r3r1`. Written as an explicit boundary rather than a
#: substring test because the successor's name contains the predecessor's, and
#: a substring match cannot tell "this is V2R3" from "this descends from V2R3".
_V2R3_TOKEN = re.compile(r"v2r3(?![0-9a-z])")


def _names_v2r3_itself(text: str) -> bool:
    return bool(_V2R3_TOKEN.search(text))


def _is_v2r3(path: Path, body: Any) -> bool:
    """Whether this artefact belongs to V2R3 rather than to a prior spent run.

    V1, V2R1 and V2R2 result receipts legitimately carry every outcome key --
    they are graded results of runs that were adjudicated and are preserved.
    Sweeping them as V2R3 disclosures would be an error of attribution, and the
    sweep would never be able to pass.

    V2R3R1 is the same error in the other direction, and it did not exist when
    this predicate was written. The successor RAN and GRADED, so its receipt
    carries outcomes by right; matching `"v2r3" in name` also matches
    `...-v2r3r1--...` and reports the successor's legitimate result as the
    predecessor's leaked one. The V2R3 proof this module made was frozen before
    any V2R3R1 receipt existed, so narrowing the attribution changes nothing
    about what was proven -- it stops the sweep claiming the successor.

    Note that `parent_protocol` is deliberately NOT read as evidence of V2R3
    membership: V2R3R1 names V2R3 as its parent in every receipt, and a
    predicate that treated a parent reference as membership would capture the
    whole successor chain by design.
    """
    haystacks = [path.name.lower(), str(path).lower()]
    if isinstance(body, dict):
        for field in ("protocol_id", "schema"):
            value = body.get(field)
            if isinstance(value, str):
                haystacks.append(value.lower())
    return any(_names_v2r3_itself(text) for text in haystacks)


def _no_persisted_outcome() -> dict[str, Any]:
    scanned = 0
    v2r3_files = 0
    hits: list[str] = []
    for name in SWEPT:
        root = NS / name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".json", ".jsonl", ".yaml", ".txt"}:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix not in {".json", ".jsonl"}:
                #: Non-JSON cannot be walked, so the substring is all there is.
                #: Nothing in the tree carries the result schema id in a yaml or
                #: txt file, so this cannot fire for a declaration.
                if RESULT_SCHEMA in text:
                    hits.append(f"{path.relative_to(NS)} carries the V2R3 result schema")
                continue
            try:
                body = json.loads(text)
            except json.JSONDecodeError:
                continue
            #: The schema id is matched where a RESULT would carry it -- as the
            #: value of a `schema` key -- not as a substring. This module's own
            #: attestation NAMES the result schema, as the thing it searched for;
            #: a substring sweep therefore flags the proof as the disclosure it
            #: just disproved, which is a check that can only ever come back one
            #: way once it has run once.
            if _declares_result_schema(body):
                hits.append(f"{path.relative_to(NS)} declares the V2R3 result schema")
                continue
            if not _is_v2r3(path, body):
                continue
            v2r3_files += 1
            keys = _outcome_dict_keys(body)
            if keys:
                hits.append(f"{path.relative_to(NS)} carries outcome keys at {keys}")
    if hits:
        raise DisclosureFound(
            "a persisted artefact carries V2R3 outcome content: " + "; ".join(hits)
        )
    return {
        "held": True,
        "files_scanned": scanned,
        "v2r3_attributable_files": v2r3_files,
        "directories": list(SWEPT),
        "result_schema": RESULT_SCHEMA,
        "outcome_keys": list(OUTCOME_KEYS),
        "hits": [],
        "how": (
            "two passes. Every json/jsonl/yaml/txt file was matched against the V2R3 "
            "result schema id, which exists nowhere else in the tree. Then every "
            "V2R3-attributable JSON body was walked for an outcome key in KEY "
            "position. A prose mention is deliberately not a hit, and a prior run's "
            "graded result is deliberately not attributed to V2R3."
        ),
    }


# ---------------------------------------------------------------------------
# leg 3: the scorer could not have printed an outcome before run() returned


_OUTPUT_CALLS = {"print", "write_text", "write_bytes", "write_immutable", "dump", "log"}


def _output_calls(node: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in _OUTPUT_CALLS:
            found.append((name, child.lineno))
    return found


def _prove_no_output_before_return() -> dict[str, Any]:
    """`run()` emits nothing, and `main()` emits an outcome only after it returns."""
    tree = ast.parse(SCORER.read_text(encoding="utf-8"), filename=str(SCORER))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    for required in ("run", "main", "measure_extra_clauses"):
        if required not in functions:
            raise DisclosureFound(
                f"the scorer no longer defines {required!r}, so this proof is about a "
                "file that no longer exists in the shape it describes."
            )

    #: `measure_extra_clauses` is the one that touches real documents, so it is
    #: checked by name rather than by reachability luck.
    silent: dict[str, Any] = {}
    for name in ("run", "measure_extra_clauses", "_require_census_keys", "_sum_maps"):
        node = functions.get(name)
        if node is None:
            continue
        emitted = _output_calls(node)
        if emitted:
            raise DisclosureFound(
                f"{name}() contains output statements {emitted}. The claim that no "
                "outcome could be emitted before run() returned is false."
            )
        silent[name] = {"output_calls": 0, "lines": [node.lineno, node.end_lineno]}

    main_fn = functions["main"]
    run_returns_at: int | None = None
    for child in ast.walk(main_fn):
        if (
            isinstance(child, ast.Assign)
            and isinstance(child.value, ast.Call)
            and getattr(child.value.func, "id", None) == "run"
        ):
            run_returns_at = child.lineno
    if run_returns_at is None:
        raise DisclosureFound(
            "main() does not assign the result of run(), so 'output happens only "
            "after run() returned' cannot be established from the syntax."
        )

    #: Every print in main() is classified. One of them -- the refusal handler --
    #: is lexically after the assignment but reads only the exception, so a
    #: purely positional test would say nothing useful about it. The question
    #: that matters is whether a print that READS the result can run without the
    #: assignment having succeeded, and the answer is structural: they are all
    #: below it in the same function body, after the try/except.
    outcome_prints: list[int] = []
    non_outcome_prints: list[int] = []
    for child in ast.walk(main_fn):
        if isinstance(child, ast.Call) and getattr(child.func, "id", None) == "print":
            reads_result = any(
                isinstance(sub, ast.Name) and sub.id in {"body", "six"} for sub in ast.walk(child)
            )
            if reads_result:
                outcome_prints.append(child.lineno)
                if child.lineno < run_returns_at:
                    raise DisclosureFound(
                        f"an outcome print at line {child.lineno} precedes "
                        f"`body = run()` at line {run_returns_at}."
                    )
            else:
                non_outcome_prints.append(child.lineno)
    if not outcome_prints:
        raise DisclosureFound(
            "main() contains no print that reads the result, so this proof is "
            "describing a scorer whose output path has moved elsewhere."
        )

    return {
        "held": True,
        "scorer": str(SCORER.relative_to(NS)),
        "scorer_sha256": _sha_file(SCORER),
        "silent_functions": silent,
        "run_assigned_in_main_at_line": run_returns_at,
        "outcome_print_lines": sorted(outcome_prints),
        "non_outcome_print_lines": sorted(non_outcome_prints),
        "how": (
            "parsed from the scorer's own syntax tree. run(), "
            "measure_extra_clauses(), _require_census_keys() and _sum_maps() contain "
            "zero output calls; every print in main() that reads `body` or `six` is "
            "lexically after `body = run()`. The KeyError escaped run(), so the "
            "assignment never completed and the whole output block was unreachable."
        ),
        "why_this_is_the_load_bearing_leg": (
            "the other legs prove nothing durable exists. This one proves nothing "
            "transient could have been shown either."
        ),
    }


# ---------------------------------------------------------------------------
# leg 4: no frame was rendered and none was inspected


def _pytest_addopts() -> str:
    config = ROOT / "pyproject.toml"
    text = config.read_text(encoding="utf-8")
    block = text.split("[tool.pytest.ini_options]", 1)
    if len(block) != 2:
        raise DisclosureFound(
            "pyproject.toml has no [tool.pytest.ini_options] block, so the traceback "
            "configuration under which the crash was rendered cannot be established."
        )
    for line in block[1].splitlines():
        if line.startswith("["):
            break
        if line.strip().startswith("addopts"):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _no_frame_inspection(operator_declaration: dict[str, Any]) -> dict[str, Any]:
    addopts = _pytest_addopts()
    locals_flags = [flag for flag in ("--showlocals", "-l") if flag in addopts.split()]
    if locals_flags:
        raise DisclosureFound(
            f"pytest is configured with {locals_flags}, so the crash traceback "
            "rendered local frames and `extra` may have been displayed. "
            "Carry-forward is REFUSED."
        )

    missing = [
        name
        for name in ("frames_inspected", "debugger_attached", "declared_by")
        if name not in operator_declaration
    ]
    if missing:
        raise DisclosureFound(f"the operator declaration is incomplete: {missing}")
    if operator_declaration["debugger_attached"]:
        raise DisclosureFound("a debugger was attached. Carry-forward is REFUSED.")
    inspected = sorted(set(operator_declaration["frames_inspected"]) & set(FRAME_LOCALS))
    if inspected:
        raise DisclosureFound(
            f"the operator record names inspected outcome frames {inspected}. "
            "Carry-forward is REFUSED."
        )

    return {
        "held": True,
        "pytest_addopts": addopts,
        "showlocals_flags_present": [],
        "why_that_matters": (
            "pytest renders local variables in a traceback only under --showlocals "
            "or -l. Without either, the KeyError frame showed the failing source "
            "line and the missing key name -- 'effective' -- and no value from "
            "`extra`, `pair_results` or any census."
        ),
        "outcome_bearing_frames": list(FRAME_LOCALS),
        "operator_declaration": operator_declaration,
    }


# ---------------------------------------------------------------------------
# the attestation


DEFAULT_OPERATOR_DECLARATION: dict[str, Any] = {
    "declared_by": "implementation session, 2026-08-26",
    "debugger_attached": False,
    "frames_inspected": [],
    "how_the_crash_was_observed": (
        "a pytest -q summary line and the default traceback. What was taken from it "
        "was the exception type, the missing key name 'effective', and the file and "
        "line of the aggregation. No cohort value was read."
    ),
    "what_was_learned_about_the_cohort": "nothing",
    "actions_taken_before_this_ruling": (
        "the census key names were corrected against EffectiveSurface.as_dict() and a "
        "pre-aggregation guard was added. Neither change was informed by any pair, "
        "any violation or any verdict, because none was observed."
    ),
    "re_run_decision_was_not_outcome_informed": True,
}


def prove_non_disclosure(
    operator_declaration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """All four legs. Raises `DisclosureFound` rather than reporting a soft no."""
    declaration = operator_declaration or DEFAULT_OPERATOR_DECLARATION
    legs = {
        "no_result_receipt": _no_result_receipt(),
        "no_persisted_outcome": _no_persisted_outcome(),
        "no_output_path_before_return": _prove_no_output_before_return(),
        "no_frame_inspection": _no_frame_inspection(declaration),
    }
    return {
        "schema": SCHEMA_NON_DISCLOSURE,
        "parent_protocol": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3",
        "event": {
            "classification": [
                "PRE_RESULT_EXECUTION_ATTEMPT",
                "INSTRUMENT_RUNTIME_CRASH",
                "NO_SCORE",
            ],
            "crash": "KeyError: 'effective'",
            "where": "tools/identity_change_migration_closure_v2r3.py, census aggregation",
            "cause": (
                "a stale test written while nothing was frozen called scorer.run() "
                "directly. It traversed the real cohort and died aggregating census "
                "keys the effective surface does not report."
            ),
            "not_classified_as": ["PASS", "FAIL", "CONTRACT_BROKEN", "preview"],
        },
        "legs": legs,
        "outcome_disclosure": "NONE_ESTABLISHED",
        "carry_forward": "PERMITTED",
        "refusal_semantics": (
            "any leg that cannot be established raises DisclosureFound and no "
            "attestation is written. Ambiguity is not resolved in favour of reuse."
        ),
    }


def attest_non_disclosure(
    operator_declaration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = prove_non_disclosure(operator_declaration)
    return {**body, **write_immutable(NON_DISCLOSURE_STEM, body, tool=Path(__file__).resolve())}


def latest_non_disclosure() -> Path | None:
    found = sorted((NS / "receipts").glob(f"{NON_DISCLOSURE_STEM}--*.json"))
    return found[-1] if found else None


def latest_disposition() -> Path | None:
    found = sorted((NS / "receipts").glob(f"{DISPOSITION_STEM}--*.json"))
    return found[-1] if found else None


# ---------------------------------------------------------------------------
# the old chain's disposition


def adjudicate_old_chain() -> dict[str, Any]:
    """The founder ruling's disposition record, written beside its subject.

    APPENDED, never applied. Every V2R3 receipt keeps its bytes: an adjudication
    that edited its subject would destroy the evidence it adjudicates.
    """
    latest = latest_non_disclosure()
    if latest is None:
        raise DisclosureFound(
            "the non-disclosure attestation has not been written, so the corpus "
            "status cannot be declared ACQUIRED_AND_FROZEN_BUT_UNSCORED."
        )
    body = {
        "schema": SCHEMA_DISPOSITION,
        "protocol_id": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3",
        "chain_status": "ABORTED_PRE_RESULT_INSTRUMENT_CRASH",
        "raw_scientific_verdict": "NONE",
        "production_verdict": "NONE",
        "result_receipt_exists": False,
        "crash": "KeyError: 'effective'",
        "outcome_disclosure": "NONE_ESTABLISHED",
        "scorer_changed_after_rung4": True,
        "old_chain_reexecution_permitted": False,
        "corpus_status": "ACQUIRED_AND_FROZEN_BUT_UNSCORED",
        "exact_carry_forward_to": "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1",
        "old_frozen_scorer_sha256": (
            "sha256:2b392c8fd63439493f620e1314ab7fc140ceda866d7c417b917bd50bb7fe138d"
        ),
        "repaired_scorer_sha256": _sha_file(SCORER),
        "digest_note": (
            "the first digest belongs to the abandoned V2R3 chain and its rung 4 "
            "receipt keeps it. The second becomes eligible only under V2R3R1's NEW "
            "rung 4. Neither history is overwritten."
        ),
        "reseal_forbidden": {
            "rule": (
                "the frozen V2R3 protocol says there is no amend path and no force "
                "flag after rung 4. The scorer digest changed, so the old chain is "
                "permanently non-executable."
            ),
            "supersede_scorer_not_used": (
                "its own contract states the scorer CODE is unchanged and only the "
                "rung-3 link moves. Here the code did change, so using it would write "
                "a receipt asserting something false about the very distinction it "
                "exists to preserve."
            ),
            "receipts_preserved": sorted(
                path.name for path in (NS / "receipts").glob(f"{MEASUREMENT_STEM}-*.json")
            ),
        },
        "non_disclosure_attestation": {
            "receipt": str(latest.relative_to(NS)),
            "receipt_file_sha256": _sha_file(latest),
        },
        "successor_reason": "PRE_RESULT_INSTRUMENT_RUNTIME_REPAIR",
    }
    return {**body, **write_immutable(DISPOSITION_STEM, body, tool=Path(__file__).resolve())}


def main(argv: list[str] | None = None) -> int:
    action = (argv or sys.argv[1:] or ["prove"])[0]
    try:
        if action == "prove":
            body = prove_non_disclosure()
        elif action == "attest":
            body = attest_non_disclosure()
        elif action == "adjudicate":
            body = adjudicate_old_chain()
        else:
            print(f"unknown action {action!r}: prove | attest | adjudicate")
            return 2
    except DisclosureFound as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4
    print(json.dumps(body, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
