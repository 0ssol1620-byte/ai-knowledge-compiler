#!/usr/bin/env python3
"""Freeze the complete SFIR10R1 executable instrument before opening partition one."""

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
OUTPUT = NS / "receipts/sfir10r1-instrument-freeze.json"
SFIR9_ROSTER = NS / "receipts/sfir9-cohort-roster.json"
MUTATION_RECEIPT = NS / "receipts/sfir10r1-mutation-baselines.json"
V10_CLOSURE = NS / "receipts/sfir10-precohort-closure.json"

sys.path.insert(0, str(NS / "tools"))
import sfir10r1_protocol as protocol  # noqa: E402

SCHEMA = "tavonel.sfir10r1.instrument_freeze.v1"

COMPONENTS = (
    "research/tavonel_eval_v2/tools/sfir10r1_protocol.py",
    "research/tavonel_eval_v2/tools/sfir10r1_transport.py",
    "research/tavonel_eval_v2/tools/sfir10r1_runner.py",
    "research/tavonel_eval_v2/tools/sfir10r1_bind_input.py",
    "research/tavonel_eval_v2/tools/sfir10r1_mutation.py",
    "research/tavonel_eval_v2/tools/sfir10r1_freeze.py",
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
    "research/tavonel_eval_v2/tests/test_sfir10r1_protocol.py",
    "research/tavonel_eval_v2/tests/test_sfir10r1_transport.py",
    "research/tavonel_eval_v2/tests/test_sfir10r1_runner.py",
)

FORBIDDEN_BEFORE_FREEZE = (
    "receipts/sfir10r1-cohort-input-binding.json",
    "receipts/sfir10r1-cohort-roster.json",
    "receipts/sfir10r1-capacity-census.json",
    "receipts/sfir10r1-capacity-score.json",
    "receipts/sfir10r1-capacity-acceptance.json",
    "receipts/sfir10r1-terminal-unproven.json",
    "runtime/sfir10r1",
    "receipts/sfir10r1-segments",
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
            raise FreezeRefused(f"{relative} exists before the SFIR10R1 freeze")
    historical = (
        _git(
            "log",
            "--all",
            "--diff-filter=A",
            "--format=%H",
            "--",
            "research/tavonel_eval_v2/receipts/sfir10r1-cohort-roster.json",
        )
        .stdout.decode()
        .strip()
    )
    if historical:
        raise FreezeRefused("an SFIR10R1 cohort roster already existed in repository history")


def _predecessor() -> dict[str, Any]:
    if not SFIR9_ROSTER.is_file():
        raise FreezeRefused("the sealed SFIR9 roster is absent")
    roster = json.loads(SFIR9_ROSTER.read_text(encoding="utf-8"))
    partition = roster.get("partition", {}).get(
        "index", roster.get("selection", {}).get("partition", {}).get("partition_index")
    )
    if partition != 0:
        raise FreezeRefused("SFIR9 predecessor is not partition zero")
    if protocol.PARTITION_INDEX != 1:
        raise FreezeRefused("successor partition is not the mechanical next partition")

    gap = NS / "tools/sfir9_execution_authority_gap.py"
    if not V10_CLOSURE.is_file():
        raise FreezeRefused("V10 pre-cohort closure is absent")
    closure_raw = V10_CLOSURE.read_bytes()
    closure = json.loads(closure_raw.decode("utf-8"))
    closure_body = {key: value for key, value in closure.items() if key != "closure_digest"}
    if _digest(closure_body) != closure.get("closure_digest"):
        raise FreezeRefused("V10 pre-cohort closure digest does not recompute")
    if closure.get("state") != "PRECOHORT_INSTRUMENT_INVALID_NO_COHORT_SPENT":
        raise FreezeRefused(f"unexpected V10 closure state: {closure.get('state')!r}")
    if closure.get("cohort", {}).get("never_opened") is not True:
        raise FreezeRefused("V10 closure does not establish that partition one remained unopened")
    if closure.get("invalidating_defect", {}).get("id") != "V10-COMPLETENESS-ALL-REFUSED":
        raise FreezeRefused("V10 closure does not name the all-refused completeness defect")
    if closure.get("hostile_hypothesis_falsified", {}).get("verdict") != "FALSIFIED":
        raise FreezeRefused("V10 closure does not preserve the falsified reseed hypothesis")

    return {
        "sfir9_roster_relative_path": "receipts/sfir9-cohort-roster.json",
        "sfir9_roster_file_sha256": "sha256:"
        + hashlib.sha256(SFIR9_ROSTER.read_bytes()).hexdigest(),
        "sfir9_roster_seal": roster.get("roster_seal"),
        "sfir9_gap_proof_sha256": "sha256:" + hashlib.sha256(gap.read_bytes()).hexdigest(),
        "sfir9_terminal_commit": _git_text(
            "log",
            "--all",
            "-1",
            "--format=%H",
            "--grep=STOP -- no frozen rate-window orchestration",
        ),
        "v10_precohort_closure_relative_path": "receipts/sfir10-precohort-closure.json",
        "v10_precohort_closure_file_sha256": "sha256:" + hashlib.sha256(closure_raw).hexdigest(),
        "v10_precohort_closure_digest": closure["closure_digest"],
        "v10_state": closure["state"],
        "v10_partition_one_never_opened": True,
        "v10_invalidating_defect": closure["invalidating_defect"]["id"],
        "v10_reseed_hypothesis": closure["hostile_hypothesis_falsified"]["verdict"],
        "v10_freeze_digest": closure["instrument_freeze_digest"],
        "v10_input_binding_digest": closure["cohort_input_binding_digest"],
        "what_is_inherited": "criterion, envelope, salt, partition count, catalogue frame",
        "what_is_not_reused": (
            "SFIR9's visible fifty-root cohort and V10's invalid frozen runner; partition one "
            "remains unopened and is selected only after this R1 instrument freezes"
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
        "relative_path": "research/tavonel_eval_v2/receipts/sfir10r1-mutation-baselines.json",
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
            "bind the external catalogue input, then generate exactly one SFIR10 roster under "
            "partition one; after that roster is sealed, execute only this frozen census runner"
        ),
        "why_this_is_not_an_sfir9_repair": (
            "SFIR9 remains terminal non-sealable. SFIR10 uses a fresh, previously unopened "
            "partition and freezes the missing rate-window control flow before selecting it."
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
