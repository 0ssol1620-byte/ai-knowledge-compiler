#!/usr/bin/env python3
"""Freeze the instrument, once, and record what was frozen.

A 9/9 pre-freeze gate says the instrument boundary holds. It is not permission
to generate a roster. This module produces the separate authority that roster
generation requires, and it is deliberately harder to satisfy than the gate:

**The gate is re-derived here, not read.** A receipt on disk says the gate was
open when someone ran it. The freeze asks again, now, against these bytes. A
freeze that trusted a stored verdict would be frozen against a tree it never
looked at.

**The working tree must equal the commit.** Every component is bound by its
committed blob, but a freeze taken in a dirty namespace records an instrument
that only exists on one machine. `git status` over the namespace has to be
empty, and the commit that HEAD names is written into the receipt.

**It happens once.** A second freeze is refused, not overwritten. The value of
a freeze is that everything downstream can point at one artifact; a freeze that
can be retaken after seeing a result is a freeze in name only.

**The cohort must still be shut.** Checked last and checked again here, because
a freeze taken after the roster was opened proves nothing about whether the
selection rule saw the cohort first.

Run it inside an isolated checkout of the instrument commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir9-instrument-freeze.json"
SCHEMA = "tavonel.sfir9.instrument_freeze.v1"

FROZEN = "INSTRUMENT_FROZEN"

GATE_NOT_OPEN = "REFUSED_FREEZE_GATE_NOT_OPEN"
DIRTY_TREE = "REFUSED_WORKING_TREE_NOT_COMMITTED"
ALREADY_FROZEN = "REFUSED_ALREADY_FROZEN"
COHORT_OPENED = "REFUSED_COHORT_ALREADY_OPENED"
NO_COMMIT = "REFUSED_NO_INSTRUMENT_COMMIT"

#: Receipts the freeze binds by digest. It does not re-derive these -- the gate
#: already did, and re-running them here would make the freeze a second gate
#: rather than a record of one.
BOUND_RECEIPTS = (
    ("freeze_gate", "sfir9-freeze-gate.json", "gate_digest"),
    ("hostile_audit", "sfir9-hostile-audit.json", "audit_digest"),
    ("legacy_failure_taxonomy", "sfir9-legacy-failure-taxonomy.json", "taxonomy_digest"),
    ("mutation_baselines", "sfir9-mutation-baselines.json", "baselines_digest"),
    ("historical_isolation", "sfir9-historical-isolation.json", None),
)


class FreezeRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Commit:
    sha: str
    namespace_is_clean: bool
    dirty_paths: tuple[str, ...]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *args],  # noqa: S607 - git resolved from PATH, as everywhere else here
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FreezeRefused(NO_COMMIT, f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def instrument_commit(repository_root: Path, namespace: str) -> Commit:
    """The commit the instrument is being frozen at, and whether it is the tree."""
    sha = _git(repository_root, "rev-parse", "HEAD").strip()
    status = _git(repository_root, "status", "--porcelain", "--", namespace)
    dirty = tuple(line[3:].strip() for line in status.splitlines() if line.strip())
    return Commit(sha=sha, namespace_is_clean=not dirty, dirty_paths=dirty)


def _digest(payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def bound_receipts(namespace: Path) -> dict[str, dict[str, Any]]:
    """Each supporting receipt, by its own digest and by the bytes on disk.

    Two hashes, because they answer different questions. The receipt's own
    digest says its body is internally consistent; the file hash says these are
    the bytes that were on disk at freeze time. A receipt regenerated later with
    the same verdict has the same self-digest and different bytes.
    """
    records: dict[str, dict[str, Any]] = {}
    for name, filename, digest_key in BOUND_RECEIPTS:
        path = namespace / "receipts" / filename
        if not path.is_file():
            raise FreezeRefused(
                GATE_NOT_OPEN, f"{filename} is not present, so the freeze has nothing to bind"
            )
        raw = path.read_bytes()
        report = json.loads(raw.decode("utf-8"))
        records[name] = {
            "relative_path": f"receipts/{filename}",
            "file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "self_digest": report.get(digest_key) if digest_key else None,
            "bytes": len(raw),
        }
    return records


def freeze(
    *,
    namespace: Path = NS,
    repository_root: Path | None = None,
    output: Path | None = None,
    allow_refreeze: bool = False,
) -> dict[str, Any]:
    """Re-derive the gate, bind everything, and write the authority. Once."""
    repository_root = repository_root or namespace.resolve().parents[1]
    target = output or (namespace / "receipts/sfir9-instrument-freeze.json")
    namespace_rel = namespace.resolve().relative_to(repository_root.resolve()).as_posix()

    if target.is_file() and not allow_refreeze:
        raise FreezeRefused(
            ALREADY_FROZEN,
            f"{target.name} already exists. A freeze that can be retaken after "
            "seeing a result is not a freeze.",
        )

    sys.path.insert(0, str(namespace / "tools"))
    import sfir9_execution_closure as closure_module
    import sfir9_freeze_gate as gate_module
    import sfir9_protocol as protocol_module
    import sfir9_transport as transport

    commit = instrument_commit(repository_root, namespace_rel)
    if not commit.namespace_is_clean:
        raise FreezeRefused(
            DIRTY_TREE,
            f"{namespace_rel} has uncommitted changes: {list(commit.dirty_paths)[:5]}. "
            "An instrument frozen from a dirty tree exists only on this machine.",
        )

    # Re-derived, not read. The receipt says it was open once; this asks now.
    gate_report = gate_module.gate(namespace)
    if not gate_report["gate_opens"]:
        closed = [row["condition"] for row in gate_report["conditions"] if row["state"] != "PASS"]
        raise FreezeRefused(GATE_NOT_OPEN, f"conditions not passing: {closed}")

    cohort = gate_module.check_roster_unopened(namespace)
    if cohort.state != gate_module.PASS:
        raise FreezeRefused(COHORT_OPENED, cohort.detail)

    origins = closure_module.import_origins()
    closure_result = closure_module.closure(
        repository_root=repository_root, import_origins=origins
    )
    manifest = closure_module.freeze_manifest(closure_result, repository_root=repository_root)
    upstream = transport.verify_upstream_binding(
        repository_root=repository_root,
        import_origins={
            pinned.module: str(namespace / "tools" / f"{pinned.module}.py")
            for pinned in transport.UPSTREAM_MODULES
        },
    )

    frozen_protocol = protocol_module.Protocol().freeze()
    body = {
        "schema": SCHEMA,
        "study_id": protocol_module.PROTOCOL_ID,
        "state": FROZEN,
        "instrument_commit": commit.sha,
        "namespace": namespace_rel,
        # No field here for "the tree was clean". The freeze raises before it
        # gets this far when the tree is dirty, so any value recorded could only
        # ever be the clean one -- the refusal is the evidence, and a field
        # restating it could never have been contradicted.
        "protocol": {
            "digest": frozen_protocol.digest(),
            "freeze_state": frozen_protocol.freeze_state,
            "terms": frozen_protocol.terms(),
        },
        "execution_closure": closure_result,
        "freeze_manifest": manifest,
        "upstream_binding": upstream,
        "supporting_receipts": bound_receipts(namespace),
        "gate_at_freeze_time": {
            "conditions_checked": gate_report["conditions_checked"],
            "conditions_passed": gate_report["conditions_passed"],
            "gate_digest": gate_report["gate_digest"],
            "re_derived_here": True,
        },
        "cohort_state_at_freeze": cohort.detail,
        "what_this_authorises": (
            "roster generation, exactly once, under the frozen selection rule. "
            "Nothing else."
        ),
        "what_this_does_not_establish": (
            "that the criterion is calibrated, that the cohort will meet it, or "
            "that the instrument measures what the protocol says it measures. A "
            "freeze fixes what will run; it says nothing about what will be found."
        ),
        # Whether the roster refuses a draft protocol is proved by the roster's
        # own controls and by the hostile audit, which mounts it as an attack.
        # A boolean here restating it would be this module's opinion of another
        # module, and could not fail.
        "roster_refusal_is_established_by": (
            "sfir9_cohort_roster controls and the hostile audit's "
            "roster_generated_before_the_protocol_freeze attack"
        ),
    }
    report = {**body, "freeze_digest": _digest(body)}
    target.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return report


def verify(report: dict[str, Any]) -> dict[str, Any]:
    """Recompute the freeze digest from the body it claims to cover."""
    body = {key: value for key, value in report.items() if key != "freeze_digest"}
    recomputed = _digest(body)
    problems = []
    if recomputed != report.get("freeze_digest"):
        problems.append("freeze_digest does not recompute; the receipt was edited")
    if report.get("state") != FROZEN:
        problems.append(f"state is {report.get('state')!r}, not {FROZEN}")
    if report.get("protocol", {}).get("freeze_state") != "PROTOCOL_FROZEN":
        problems.append("the protocol recorded here is not frozen")
    return {
        "schema": "tavonel.sfir9.instrument_freeze.v1.verification",
        "verified": not problems,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="freeze the SFIR9 instrument, once")
    parser.add_argument("--namespace", type=Path, default=NS)
    args = parser.parse_args(argv)
    try:
        report = freeze(namespace=args.namespace)
    except FreezeRefused as error:
        print(f"REFUSED  {error}")
        return 1
    print(f"study            {report['study_id']}")
    print(f"commit           {report['instrument_commit']}")
    print(f"protocol         {report['protocol']['freeze_state']} {report['protocol']['digest']}")
    print(f"components       {report['execution_closure']['component_count']} bound")
    print(f"gate             {report['gate_at_freeze_time']['conditions_passed']}"
          f"/{report['gate_at_freeze_time']['conditions_checked']} re-derived at freeze time")
    print(f"cohort           {report['cohort_state_at_freeze']}")
    print(f"freeze digest    {report['freeze_digest']}")
    print(f"verify           {verify(report)}")
    print(f"written to       {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
