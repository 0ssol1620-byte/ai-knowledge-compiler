#!/usr/bin/env python3
"""Close SFIR10 as a pre-cohort invalid instrument without spending partition one.

SFIR10 was fully frozen and its external input was bound before any successor
roster existed. A hostile read then found one real completeness defect in the
frozen runner: ``complete = stopped == 0`` treats an all-identity-refused cohort
as an exact census of zero. This closure preserves that defect instead of
repairing the frozen instrument.

A second hostile hypothesis -- that a root seeded immediately before a segment
boundary could be reseeded because ``visited_count`` was still zero -- is
recorded as falsified, not silently promoted into a defect. The frozen frontier
writes the root tree to ``visited`` in the same transaction that enqueues it.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir10-precohort-closure.json"
FREEZE = NS / "receipts/sfir10-instrument-freeze.json"
INPUT = NS / "receipts/sfir10-cohort-input-binding.json"
V10_ROSTER_REL = "research/tavonel_eval_v2/receipts/sfir10-cohort-roster.json"
V10_RUNNER_REL = "research/tavonel_eval_v2/tools/sfir10_runner.py"

sys.path.insert(0, str(NS / "tools"))
import sfir10_runner as v10_runner  # noqa: E402


class ClosureRefused(RuntimeError):
    pass


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(  # noqa: S603 - fixed git argv plus declared repository paths
        ["git", *args],  # noqa: S607 - repository follows existing git-from-PATH convention
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise ClosureRefused(result.stderr.decode(errors="replace").strip())
    return result


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ClosureRefused(f"required predecessor artifact absent: {path.relative_to(NS)}")
    return json.loads(path.read_text(encoding="utf-8"))


def _roster_never_opened() -> dict[str, Any]:
    working = (REPO / V10_ROSTER_REL).exists()
    history = (
        _git(
            "log",
            "--all",
            "--diff-filter=A",
            "--format=%H",
            "--",
            V10_ROSTER_REL,
            check=False,
        )
        .stdout.decode()
        .split()
    )
    return {
        "working_tree_exists": working,
        "history_add_commits": history,
        "never_opened": not working and not history,
        "basis": "OBSERVED_REPOSITORY_ARTIFACT_ABSENCE",
        "scope": (
            "establishes that no SFIR10 roster artifact exists in this repository's "
            "working tree or Git history; it does not prove the absence of every "
            "possible unrecorded external action"
        ),
    }


def _frozen_bytes_still_match(freeze: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for component in freeze["components"]:
        relative = component["relative_path"]
        raw = (REPO / relative).read_bytes()
        observed = "sha256:" + hashlib.sha256(raw).hexdigest()
        if observed != component["sha256"]:
            raise ClosureRefused(f"frozen V10 component moved: {relative}")
        records.append(
            {
                "relative_path": relative,
                "sha256_at_freeze": component["sha256"],
                "sha256_at_closure": observed,
            }
        )
    return records


def _find_complete_expression(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    matches = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "complete" for target in node.targets
        ):
            matches.append(ast.get_source_segment(source, node.value))
    if "stopped == 0" not in matches:
        raise ClosureRefused(f"expected frozen completeness expression not found: {matches}")
    return {
        "assignments_named_complete": matches,
        "frozen_expression": "stopped == 0",
        "missing_counted_nonzero_guard": True,
    }


def _all_refused_counterexample() -> dict[str, Any]:
    stopped = 0
    exhausted = 0
    refused = 50
    lower_bound = 0
    complete_under_v10 = stopped == 0
    exact_under_v10 = lower_bound if complete_under_v10 else None
    if not complete_under_v10 or exact_under_v10 != 0:
        raise ClosureRefused("the declared all-refused counterexample no longer demonstrates V10")
    return {
        "synthetic_dispositions": {
            "exhausted": exhausted,
            "stopped": stopped,
            "refused": refused,
        },
        "candidate_lower_bound": lower_bound,
        "v10_complete": complete_under_v10,
        "v10_exact_count": exact_under_v10,
        "why_invalid": (
            "no root was counted as measured or stopped, yet the frozen expression declares "
            "the census complete and exact; zero then becomes a population claim about an "
            "unmeasured cohort"
        ),
    }


class _FakeTransport:
    def resolve_canonical_address(self, _address: str, expected_uuid: str) -> dict[str, Any]:
        return {
            "canonical_address": "fixture/repository",
            "observed_repository_id": str(expected_uuid),
            "default_branch": "main",
        }

    class _Response:
        def __init__(self) -> None:
            self.body = {"sha": "d" * 40, "commit": {"tree": {"sha": "a" * 40}}}

    def get(self, _url: str) -> _Response:
        return self._Response()


def _falsify_reseed_hypothesis() -> dict[str, Any]:
    root = {"host_uuid": "7", "catalogue_address": "fixture/repository"}
    with tempfile.TemporaryDirectory() as temp:
        database = Path(temp) / "root.sqlite"
        with v10_runner.RootStore(database) as store:
            v10_runner._seed_or_attest(store=store, client=_FakeTransport(), root=root)
            visited = store.frontier.visited_count()
            pending = store.frontier.pending_count()
    if visited != 1 or pending != 1:
        raise ClosureRefused(
            "frontier did not atomically record the seed as expected: "
            f"visited={visited} pending={pending}"
        )
    return {
        "hypothesis": (
            "a seeded-but-unexpanded V10 root could have visited_count zero and "
            "therefore be reseeded"
        ),
        "verdict": "FALSIFIED",
        "synthetic_after_seed": {"visited_count": visited, "pending_count": pending},
        "mechanism": (
            "sfir8_frontier.enqueue inserts the frontier row and visited identity before commit; "
            "V10's visited_count guard therefore already sees the seed before expansion"
        ),
        "scientific_consequence": (
            "not a reason to invalidate V10; preserved as a hostile hypothesis that failed"
        ),
    }


def close() -> dict[str, Any]:
    if OUTPUT.exists():
        raise ClosureRefused("V10 pre-cohort closure already exists; it is immutable")
    freeze = _read(FREEZE)
    binding = _read(INPUT)
    roster = _roster_never_opened()
    if not roster["never_opened"]:
        raise ClosureRefused("V10 roster exists; this is not a pre-cohort closure")
    instrument_commit = freeze["instrument_commit"]
    source_result = _git("show", f"{instrument_commit}:{V10_RUNNER_REL}")
    source = source_result.stdout.decode("utf-8")
    defect = _find_complete_expression(source)
    body = {
        "schema": "tavonel.sfir10.precohort_closure.v1",
        "study_id": freeze["study_id"],
        "state": "PRECOHORT_INSTRUMENT_INVALID_NO_COHORT_SPENT",
        "instrument_commit": instrument_commit,
        "instrument_freeze_digest": freeze["freeze_digest"],
        "cohort_input_binding_digest": binding["successor_binding_digest"],
        "frozen_components_rechecked": _frozen_bytes_still_match(freeze),
        "cohort": roster,
        "invalidating_defect": {
            "id": "V10-COMPLETENESS-ALL-REFUSED",
            "source": defect,
            "counterexample": _all_refused_counterexample(),
            "found_before_roster_generation": True,
        },
        "hostile_hypothesis_falsified": _falsify_reseed_hypothesis(),
        "what_is_spent": "the V10 instrument design and its immutable freeze/input receipts",
        "what_is_not_spent": (
            "partition one: no V10 cohort roster artifact exists, so a new prospectively frozen "
            "successor may use the still-unseen partition under an independently fixed instrument"
        ),
        "what_must_not_happen": (
            "do not modify or refreeze V10, do not call V10 a failed capacity result, and do not "
            "treat the falsified reseed hypothesis as a defect"
        ),
    }
    report = {**body, "closure_digest": _digest(body)}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return report


def main() -> int:
    try:
        report = close()
    except ClosureRefused as exc:
        print(f"REFUSED {exc}")
        return 1
    print(
        json.dumps(
            {
                "state": report["state"],
                "closure_digest": report["closure_digest"],
                "v10_roster_never_opened": report["cohort"]["never_opened"],
                "invalidating_defect": report["invalidating_defect"]["id"],
                "reseed_hypothesis": report["hostile_hypothesis_falsified"]["verdict"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
