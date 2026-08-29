#!/usr/bin/env python3
"""Freeze the complete SFIR10R3 executable instrument before opening partition three."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir10r3-instrument-freeze.json"
R2_ROSTER = NS / "receipts/sfir10r2-cohort-roster.json"
R2_TERMINAL = NS / "receipts/sfir10r2-terminal-unproven.json"
R2_FREEZE = NS / "receipts/sfir10r2-instrument-freeze.json"
R2_INPUT_BINDING = NS / "receipts/sfir10r2-cohort-input-binding.json"
MUTATION_RECEIPT = NS / "receipts/sfir10r3-mutation-baselines.json"

sys.path.insert(0, str(NS / "tools"))
import sfir10r3_protocol as protocol  # noqa: E402

SCHEMA = "tavonel.sfir10r3.instrument_freeze.v1"

COMPONENTS = (
    "research/tavonel_eval_v2/tools/sfir10r3_protocol.py",
    "research/tavonel_eval_v2/tools/sfir10r3_transport.py",
    "research/tavonel_eval_v2/tools/sfir10r3_runner.py",
    "research/tavonel_eval_v2/tools/sfir10r3_bind_input.py",
    "research/tavonel_eval_v2/tools/sfir10r3_mutation.py",
    "research/tavonel_eval_v2/tools/sfir10r3_freeze.py",
    "research/tavonel_eval_v2/tools/sfir8_frontier.py",
    "research/tavonel_eval_v2/tools/sfir9_selection.py",
    "research/tavonel_eval_v2/tools/sfir9_cohort_input.py",
    "research/tavonel_eval_v2/tools/sfir9_protocol.py",
    "research/tavonel_eval_v2/tools/sfir7_catalog_parser.py",
    "research/tavonel_eval_v2/tools/sfir7_projection.py",
    "research/tavonel_eval_v2/tools/sfir7_frame.py",
    "research/tavonel_eval_v2/tools/sfir7_roots.py",
    "research/tavonel_eval_v2/tools/sfir9_execution_authority_gap.py",
)

CONTROLS = (
    "research/tavonel_eval_v2/tests/test_sfir10r3_protocol.py",
    "research/tavonel_eval_v2/tests/test_sfir10r3_transport.py",
    "research/tavonel_eval_v2/tests/test_sfir10r3_runner.py",
)

FORBIDDEN_BEFORE_FREEZE = (
    "receipts/sfir10r3-cohort-input-binding.json",
    "receipts/sfir10r3-cohort-roster.json",
    "receipts/sfir10r3-capacity-census.json",
    "receipts/sfir10r3-capacity-score.json",
    "receipts/sfir10r3-capacity-acceptance.json",
    "receipts/sfir10r3-terminal-unproven.json",
    "runtime/sfir10r3",
    "receipts/sfir10r3-segments",
)


class FreezeRefused(RuntimeError):
    pass


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(  # noqa: S603 - argv is constructed internally
        ["git", *args],  # noqa: S607 - repository follows the existing git-from-PATH convention
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise FreezeRefused(result.stderr.decode(errors="replace").strip())
    return result


def _git_text(*args: str) -> str:
    return _git(*args).stdout.decode(errors="replace").strip()


def _bind(relative_path: str) -> dict[str, Any]:
    path = REPO / relative_path
    if not path.is_file():
        raise FreezeRefused(f"missing component {relative_path}")
    working = path.read_bytes()
    committed = _git("show", f"HEAD:{relative_path}")
    if committed.returncode != 0:
        raise FreezeRefused(f"{relative_path} is not committed at HEAD")
    if committed.stdout != working:
        raise FreezeRefused(f"{relative_path} differs between HEAD and working bytes")
    blob = _git_text("rev-parse", f"HEAD:{relative_path}")
    return {
        "relative_path": relative_path,
        "sha256": "sha256:" + hashlib.sha256(working).hexdigest(),
        "git_blob_id": blob,
        "bytes": len(working),
    }


def _namespace_clean() -> None:
    status = _git_text("status", "--porcelain", "--", "research/tavonel_eval_v2")
    if status:
        raise FreezeRefused(
            "research/tavonel_eval_v2 is dirty; freeze requires exact committed bytes: "
            + status.splitlines()[0]
        )


def _cohort_still_shut() -> None:
    for relative in FORBIDDEN_BEFORE_FREEZE:
        if (NS / relative).exists():
            raise FreezeRefused(f"{relative} exists before the SFIR10R3 freeze")
    historical = (
        _git(
            "log",
            "--all",
            "--diff-filter=A",
            "--format=%H",
            "--",
            "research/tavonel_eval_v2/receipts/sfir10r3-cohort-roster.json",
        )
        .stdout.decode()
        .strip()
    )
    if historical:
        raise FreezeRefused("an SFIR10R3 cohort roster already existed in repository history")


def _predecessor() -> dict[str, Any]:
    required = (R2_ROSTER, R2_TERMINAL, R2_FREEZE, R2_INPUT_BINDING)
    if not all(path.is_file() for path in required):
        raise FreezeRefused("the sealed SFIR10R2 predecessor evidence is incomplete")

    roster_raw = R2_ROSTER.read_bytes()
    roster = json.loads(roster_raw.decode("utf-8"))
    roster_body = {key: value for key, value in roster.items() if key != "roster_seal"}
    if _digest(roster_body) != roster.get("roster_seal"):
        raise FreezeRefused("R2 roster seal does not recompute")
    partition = roster.get("partition", {}).get("index")
    if partition != 2:
        raise FreezeRefused("R2 predecessor is not spent partition two")
    if roster.get("entry_count") != protocol.derive_n():
        raise FreezeRefused("R2 predecessor does not bind the prospectively required full roster")
    if protocol.PREDECESSOR_PARTITION_INDEX != 2 or protocol.PARTITION_INDEX != 3:
        raise FreezeRefused("R3 successor partition is not the mechanical next partition")

    terminal_raw = R2_TERMINAL.read_bytes()
    terminal = json.loads(terminal_raw.decode("utf-8"))
    terminal_body = {key: value for key, value in terminal.items() if key != "terminal_digest"}
    if _digest(terminal_body) != terminal.get("terminal_digest"):
        raise FreezeRefused("R2 terminal-unproven digest does not recompute")
    if terminal.get("schema") != "tavonel.sfir10r2.terminal_unproven.v1":
        raise FreezeRefused("R2 predecessor is not the frozen terminal-unproven study")
    if terminal.get("roster_seal") != roster.get("roster_seal"):
        raise FreezeRefused("R2 terminal receipt belongs to a different roster")
    if terminal.get("windows_used") != 0:
        raise FreezeRefused("R2 predecessor sealed a scientific window; R3 assumptions are invalid")
    if terminal.get("reason") != (
        "per-response provider delta is 2; exclusive attribution is not established"
    ):
        raise FreezeRefused(
            "R2 terminal reason differs from the shared-counter defect R3 separates"
        )
    if terminal.get("what_this_means") != "no PASS or FAIL may be sealed from this cohort":
        raise FreezeRefused("R2 terminal receipt does not preserve the no-score ruling")

    r2_freeze = json.loads(R2_FREEZE.read_text(encoding="utf-8"))
    r2_input = json.loads(R2_INPUT_BINDING.read_text(encoding="utf-8"))
    if terminal.get("freeze_digest") != r2_freeze.get("freeze_digest"):
        raise FreezeRefused("R2 terminal receipt is not linked to the R2 instrument freeze")
    if roster.get("input_binding_digest") != r2_input.get("successor_binding_digest"):
        raise FreezeRefused("R2 roster is not linked to the R2 external input binding")

    return {
        "r2_roster_relative_path": "receipts/sfir10r2-cohort-roster.json",
        "r2_roster_file_sha256": "sha256:" + hashlib.sha256(roster_raw).hexdigest(),
        "r2_roster_seal": roster["roster_seal"],
        "r2_partition_index": 2,
        "r2_entry_count": roster["entry_count"],
        "r2_terminal_relative_path": "receipts/sfir10r2-terminal-unproven.json",
        "r2_terminal_file_sha256": "sha256:" + hashlib.sha256(terminal_raw).hexdigest(),
        "r2_terminal_digest": terminal["terminal_digest"],
        "r2_terminal_reason": terminal["reason"],
        "r2_windows_used": 0,
        "r2_no_pass_or_fail": True,
        "r2_freeze_digest": r2_freeze["freeze_digest"],
        "r2_input_binding_digest": r2_input["successor_binding_digest"],
        "r3_partition_index": 3,
        "what_is_inherited": "criterion, envelope, salt, partition count, catalogue frame",
        "what_is_not_reused": (
            "R2 root identities, candidate yields, and partial traversal outcomes do not enter R3 "
            "selection; only sealed predecessor metadata establishes that partition two is spent"
        ),
    }


def _run_controls() -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *CONTROLS,
        "-q",
    ]
    result = subprocess.run(  # noqa: S603 - sys.executable and fixed pytest paths only
        cmd, cwd=REPO, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise FreezeRefused(
            "SFIR10 controls are red:\n" + result.stdout[-4000:] + result.stderr[-2000:]
        )
    tail = [line for line in result.stdout.splitlines() if line.strip()][-3:]
    return {"command": cmd[1:], "returncode": 0, "summary_tail": tail}


def _mutation_baseline() -> dict[str, Any]:
    if not MUTATION_RECEIPT.is_file():
        raise FreezeRefused(
            "SFIR10 mutation-baseline receipt is absent; freeze requires a green "
            "post-commit mutation audit"
        )
    report = json.loads(MUTATION_RECEIPT.read_text(encoding="utf-8"))
    body = {key: value for key, value in report.items() if key != "mutation_digest"}
    if _digest(body) != report.get("mutation_digest"):
        raise FreezeRefused("SFIR10 mutation receipt digest does not recompute")
    if not report.get("all_baselines_green") or not report.get("all_mutations_killed"):
        raise FreezeRefused(
            f"SFIR10 mutation audit is not clean: survivors={report.get('survivors_or_invalid')}"
        )
    return {
        "relative_path": "research/tavonel_eval_v2/receipts/sfir10r3-mutation-baselines.json",
        "file_sha256": "sha256:" + hashlib.sha256(MUTATION_RECEIPT.read_bytes()).hexdigest(),
        "mutation_digest": report["mutation_digest"],
        "mutations_declared": report["mutations_declared"],
        "mutations_killed": report["mutations_killed"],
    }


def freeze() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FreezeRefused("SFIR10 freeze already exists; it cannot be retaken")
    _namespace_clean()
    _cohort_still_shut()
    frozen = protocol.Protocol().freeze()
    terms = frozen.terms()
    if terms["rate_window_execution"]["poll_during_segment"] is not False:
        raise FreezeRefused("unexpected adaptive rate polling")
    if terms["rate_window_execution"]["segment_start_observations"] != 1:
        raise FreezeRefused("segment-start observation schedule is not singular and fixed")
    execution = terms["rate_window_execution"]
    preflight = execution["accounting_sanity_preflight"]
    if preflight["requests"] != 10 or preflight["minimum_delta_each_response"] != 1:
        raise FreezeRefused("accounting sanity preflight is not the frozen ten-request proof")
    if preflight["wait_seconds"] != 0 or preflight["cohort_contact_before_success"] is not False:
        raise FreezeRefused("accounting sanity preflight permits adaptive wait or cohort contact")
    if preflight["external_extra_permitted"] is not True:
        raise FreezeRefused("R3 preflight unexpectedly requires credential exclusivity")
    if execution["capacity_claim_depends_on_exact_provider_cost"] is not False:
        raise FreezeRefused("R3 incorrectly couples capacity to exact provider cost")
    if execution["provider_cost_claim_policy"] != "WITHHOLD_UNLESS_ZERO_UNATTRIBUTED_EXTRA":
        raise FreezeRefused("R3 provider-cost withholding policy drifted")
    if execution["unattributed_extra_policy"] != (
        "RECORD_AS_EXTERNAL_INTERFERENCE_NEVER_CREDIT_TO_YIELD"
    ):
        raise FreezeRefused("R3 interference policy drifted")
    controls = _run_controls()
    body = {
        "schema": SCHEMA,
        "state": "INSTRUMENT_FROZEN",
        "study_id": protocol.PROTOCOL_ID,
        "instrument_commit": _git_text("rev-parse", "HEAD"),
        "protocol_digest": frozen.digest(),
        "protocol_terms": terms,
        "components": [_bind(path) for path in COMPONENTS],
        "controls": [_bind(path) for path in CONTROLS],
        "control_run": controls,
        "mutation_baseline": _mutation_baseline(),
        "predecessor": _predecessor(),
        "cohort_state_at_freeze": "NO_SFIR10_ROSTER_ARTIFACT_IN_WORKTREE_OR_HISTORY",
        "authorises": (
            "bind the external catalogue input, then generate exactly one SFIR10R3 roster under "
            "partition three; after that roster is sealed, execute only this frozen census runner"
        ),
        "why_this_is_not_an_r2_repair": (
            "R2 remains terminal MEASUREMENT_UNPROVEN with no PASS or FAIL. R3 uses the next "
            "untouched partition and prospectively separates capacity evidence from exact provider "
            "cost attribution before selecting it."
        ),
    }
    report = {**body, "freeze_digest": _digest(body)}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return report


def verify(report: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in report.items() if k != "freeze_digest"}
    problems = []
    if _digest(body) != report.get("freeze_digest"):
        problems.append("freeze digest does not recompute")
    if report.get("protocol_digest") != protocol.Protocol().freeze().digest():
        problems.append("protocol digest differs from live protocol")
    return {"verified": not problems, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="freeze complete SFIR10 instrument").parse_args(argv)
    try:
        report = freeze()
    except FreezeRefused as exc:
        print(f"REFUSED {exc}")
        return 1
    print(
        json.dumps(
            {
                "state": report["state"],
                "instrument_commit": report["instrument_commit"],
                "protocol_digest": report["protocol_digest"],
                "freeze_digest": report["freeze_digest"],
                "components": len(report["components"]),
                "controls": len(report["controls"]),
                "verify": verify(report),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
