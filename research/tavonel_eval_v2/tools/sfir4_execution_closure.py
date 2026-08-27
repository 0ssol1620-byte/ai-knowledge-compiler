"""Pre-freeze gate: is the instrument SFIR4 would freeze actually recoverable?

INC-V2-089's root cause was not a bad edit. It was that
``research/tavonel_eval_v2/`` held 0 git-tracked files while 20 freeze and
attestation receipts pinned 29 of its source files by sha-256. When those files
changed there was no second copy of the previous bytes anywhere, so the frozen
instrument became unreproducible and no honest procedure recovers it. The
receipts were correct the whole time; there was simply nothing behind them.

A pin is a *statement* that bytes were what they were. Recoverability is the
*ability to produce those bytes again*. The study had the first and not the
second, and nothing in it could tell the difference -- which is why this gate
exists and why it runs BEFORE a freeze rather than after.

What it computes:

1. the closure -- every first-party source file reachable from the declared
   SFIR4 entry points, by static import analysis. Both the EXECUTION entry
   points (what runs during a study) and the VERIFICATION entry points (the
   controls and audits that establish the instrument has its claimed
   properties) are walked; see ``VERIFICATION_ENTRY_POINTS`` for why leaving
   the second out was wrong;
2. a sha-256 manifest over that closure;
3. for each file, whether it is committed AT HEAD and whether the committed
   blob is byte-identical to the working tree. Both are required: a staged but
   uncommitted file is as unrecoverable as an untracked one, and a file whose
   blob was altered on check-in (an end-of-line conversion, say) has a manifest
   digest naming bytes git will not return;
4. PASS only if every file is committed and byte-identical, REFUSE otherwise.

Imports are resolved by parsing, never by importing. ``sources_sfir4`` runs
``assert_static_disjointness()`` at module scope and the probes open network
transports, so an import-based closure would execute the instrument in order to
describe it. ``ast`` reads the same information without running anything.

The closure is over-inclusive by design: an unresolved import is reported rather
than dropped. A file wrongly included makes the gate stricter; a file wrongly
excluded is exactly the failure this gate exists to prevent, and it would not be
visible.

This module NEVER writes to git and never modifies a historical receipt. It
reports which files need to be committed. Placing them under version control is
a separate, explicitly authorised act.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, ROOT, now, rel, sha_file, write_hashed

SCHEMA = "tavonel.sfir4.execution_closure.v1"
STEM = "sfir4-execution-closure"

#: The modules that constitute an SFIR4 run, entered by path so that the
#: closure is computed from what executes rather than from what a manifest
#: happens to list.
ENTRY_POINTS: tuple[str, ...] = (
    "tools/sfir4_protocol.py",
    "tools/sfir4_execution.py",
    "tools/sfir4_worker.py",
    "tools/sfir4_acceptance.py",
    "tools/sfir4_spent_authority.py",
    "tools/sfir4_locator.py",
    "tools/sfir4_identity_domain.py",
    "tools/sfir4_response_evidence.py",
    "tools/probe_sfir4_capacity.py",
    "tools/verify_sfir4_frame.py",
    "tools/freeze_sfir4_protocol.py",
    "tools/sfir4_core_conformance.py",
    "acquisition/sources_sfir4.py",
)

#: The files that establish the instrument HAS the properties its receipts
#: assert. These do not execute during a run, and an earlier draft of this gate
#: excluded them for that reason. That was wrong, and this study's own history
#: is the proof: ``tests/test_v2r3_contract_consistency.py`` is pinned by two
#: frozen protocol attestations and is one of the 29 files INC-V2-089 lost. A
#: recoverability gate that covered only execution would have permitted exactly
#: the failure it exists to prevent, and would have reported PASS while doing so.
#:
#: Reproducing a measurement needs the code that ran. Reproducing the *audit* --
#: the claim that the locator grammar refuses a mutable ref, that a synthesised
#: census cannot be sealed, that the identity proof is domain-separated -- needs
#: the controls that bind those properties. A reviewer who can re-derive the
#: number but cannot re-run the controls has to take the instrument's word for
#: what it is.
#:
#: ``anti_blocker_audit`` and ``verify_frozen_instrument_integrity`` are here for
#: the same reason: their verdicts are pre-freeze conditions, so a verdict from
#: a tool that has since drifted is not evidence.
VERIFICATION_ENTRY_POINTS: tuple[str, ...] = (
    "tests/test_sfir4_locator.py",
    "tests/test_sfir4_identity_domain.py",
    "tests/test_sfir4_response_evidence.py",
    "tests/test_sfir4_execution_closure.py",
    "tests/test_sfir4_protocol_capacity.py",
    "tests/test_sfir4_execution.py",
    "tests/test_freeze_sfir4_protocol.py",
    "tools/anti_blocker_audit.py",
    "tools/verify_frozen_instrument_integrity.py",
    "tools/sfir4_core_revision_comparison.py",
    "tests/test_sfir4_core_conformance.py",
)

#: Non-Python files the instrument is equally bound by. A protocol YAML that is
#: unrecoverable is exactly as damaging as an unrecoverable scorer.
DECLARED_DATA: tuple[str, ...] = (
    "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4.yaml",
    "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4_DESIGN_CHARTER.yaml",
    # SFIR3 predecessor evidence. SFIR4 does not produce these; it READS them --
    # its spent-authority binds the exact SFIR3 capacity failure and its charter
    # freeze binds SFIR3's charter. Leaving them out of the closure made the gate
    # PASS in a working tree that happened to hold them and let the same study
    # fail in an isolated checkout, which is the inversion this gate exists to
    # prevent: a declared input that only one machine can produce is not
    # recoverable, whatever the code says.
    "receipts/sfir3-spent-identity-authority.json",
    "receipts/sfir3-design-charter-freeze.json",
    "receipts/sfir3-capacity-failure-authority.json",
)

#: Directories searched when resolving a first-party import, in order.
#:
#: These mirror the ``sys.path.insert`` calls the modules make at runtime. The
#: study's packages are siblings under the research tree and are imported by
#: bare module name once that insertion has happened, so a resolver that only
#: looked in ``tools/`` would silently drop most of the closure -- and an
#: under-inclusive closure is precisely the failure this gate exists to catch.
SEARCH_ROOTS: tuple[Path, ...] = (
    NS / "tools",
    NS / "acquisition",
    NS / "canonicalization",
    NS / "endpoint",
    NS / "source_fact_ir",
    NS / "compiler",
    NS,
    #: ``akc_cir`` is the Protected Core package the study executes. It is
    #: installed from the repository, so its bytes are the repository's bytes
    #: and this gate must see them.
    ROOT / "packages" / "cir-python" / "src",
    ROOT,
)

#: Distributions installed from an external index. Their bytes are pinned by the
#: environment lockfile, not by this repository, so this gate does not carry
#: them -- but it will not silently ignore an unresolved name either: anything
#: unresolved and not listed here makes the gate REFUSE.
THIRD_PARTY: frozenset[str] = frozenset({"yaml", "pytest", "requests", "certifi"})


class ClosureRefused(RuntimeError):
    """The closure cannot be computed, as distinct from computing a REFUSE."""


def _module_candidates(name: str) -> tuple[str, ...]:
    """Filesystem-relative spellings a dotted module name could resolve to."""
    parts = name.split(".")
    joined = "/".join(parts)
    return (f"{joined}.py", f"{joined}/__init__.py")


def resolve_module(name: str) -> Path | None:
    """Resolve one dotted module name to a first-party file, or None."""
    for root in SEARCH_ROOTS:
        for candidate in _module_candidates(name):
            path = root / candidate
            if path.is_file():
                return path.resolve()
    return None


def imported_names(source: str, path: Path) -> list[tuple[str, tuple[str, ...]]]:
    """Every import a file makes, read without executing it.

    Each entry is ``(module, submodule_candidates)``. ``from X import n`` is
    ambiguous in the grammar -- ``n`` may be a submodule or an attribute -- so
    both spellings are returned and the resolver decides. Treating every
    ``X.n`` as a module produced dozens of phantom unresolved names
    (``common.NS``, ``payload_cache.PayloadCache``) and buried the handful of
    genuinely unresolved ones.
    """
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        raise ClosureRefused(f"{rel(path)} does not parse: {error}") from error
    entries: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            entries.extend((alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                # A relative import, or ``from . import x`` inside a package
                # this gate does not own.
                continue
            entries.append((node.module, tuple(f"{node.module}.{a.name}" for a in node.names)))
    return entries


def closure(
    entry_points: tuple[str, ...] = ENTRY_POINTS,
    verification_entry_points: tuple[str, ...] = VERIFICATION_ENTRY_POINTS,
) -> dict[str, Any]:
    """Every first-party file reachable from the entry points.

    Execution and verification are walked together and reported as one set.
    Both must be recoverable for the same reason, and separating them in the
    manifest would invite one of the two being gated and the other not.
    """
    pending: list[Path] = []
    for relative in (*entry_points, *verification_entry_points):
        path = NS / relative
        if not path.is_file():
            raise ClosureRefused(f"declared entry point is absent: {relative}")
        pending.append(path.resolve())

    reached: set[Path] = set()
    unresolved: set[str] = set()
    while pending:
        path = pending.pop()
        if path in reached:
            continue
        reached.add(path)
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ClosureRefused(f"{rel(path)} is unreadable: {error}") from error
        for name, submodules in imported_names(source, path):
            target = resolve_module(name)
            # ``from pkg import mod`` where pkg is a namespace directory: the
            # package itself has no bytes, so the submodule is the real edge.
            resolved_any = target is not None
            for submodule in submodules:
                found_sub = resolve_module(submodule)
                if found_sub is not None:
                    resolved_any = True
                    if found_sub not in reached:
                        pending.append(found_sub)
            if target is not None:
                if target not in reached:
                    pending.append(target)
                continue
            if resolved_any:
                continue
            top = name.split(".")[0]
            if top in sys.stdlib_module_names or top in THIRD_PARTY:
                continue
            if (NS / name.replace(".", "/")).is_dir():
                # A namespace package with no ``__init__.py``. It contributes no
                # bytes of its own; its submodules were resolved above.
                continue
            unresolved.add(name)

    for relative in DECLARED_DATA:
        path = NS / relative
        if not path.is_file():
            raise ClosureRefused(f"declared data file is absent: {relative}")
        reached.add(path.resolve())

    return {"files": sorted(reached), "unresolved_imports": sorted(unresolved)}


def _git(*args: str) -> bytes:
    """One batched git invocation with fixed argv and no shell.

    Returns raw bytes because one caller reads blob contents, where any decoding
    would defeat the byte-for-byte comparison this gate exists to perform.
    """
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ClosureRefused(f"git could not be consulted: {error}") from error
    return completed.stdout


def committed_blobs(paths: list[Path]) -> dict[str, str]:
    """Path -> the blob object id **committed at HEAD**, for each path git has.

    Deliberately ``ls-tree HEAD`` and not ``ls-files``. ``ls-files`` reports the
    INDEX, so merely staging a file makes it look tracked -- and a staged,
    uncommitted file is exactly as unrecoverable as an untracked one. A gate
    that accepted the index would report PASS at the moment before the commit
    that makes the claim true, which is the same shape of error as a pin over
    bytes nothing can return.
    """
    if not paths:
        return {}
    out = _git("ls-tree", "-r", "-z", "--format=%(objectname) %(path)", "HEAD")
    wanted = {rel(path) for path in paths}
    found: dict[str, str] = {}
    for entry in out.split(b"\0"):
        if not entry:
            continue
        line = entry.decode("utf-8")
        oid, _, name = line.partition(" ")
        name = name.replace("\\", "/")
        if name in wanted:
            found[name] = oid
    return found


def blob_bytes(oid: str) -> bytes:
    """The exact bytes git stored for one object."""
    return _git("cat-file", "blob", oid)


def gate(
    entry_points: tuple[str, ...] = ENTRY_POINTS,
    verification_entry_points: tuple[str, ...] = VERIFICATION_ENTRY_POINTS,
) -> dict[str, Any]:
    """Compute the closure, its manifest, and whether a freeze may proceed."""
    found = closure(entry_points, verification_entry_points)
    files: list[Path] = found["files"]
    committed = committed_blobs(files)

    manifest: dict[str, str] = {}
    untracked: list[str] = []
    divergent: list[dict[str, str]] = []
    for path in files:
        relative = rel(path)
        manifest[relative] = sha_file(path)
        oid = committed.get(relative)
        if oid is None:
            untracked.append(relative)
            continue
        # Committed is not the same as recoverable. If the blob differs from the
        # working tree -- an uncommitted edit, or an end-of-line conversion
        # applied on check-in -- then the manifest digest names bytes git will
        # not return, and a fresh clone reproduces a different instrument.
        if blob_bytes(oid) != path.read_bytes():
            divergent.append({"path": relative, "committed_blob": oid})

    reasons: list[str] = []
    if untracked:
        reasons.append(
            f"{len(untracked)} of {len(files)} files in the closure are not "
            "committed at HEAD, so their current bytes are unrecoverable once changed"
        )
    if divergent:
        reasons.append(
            f"{len(divergent)} of {len(files)} files in the closure differ from the "
            "bytes committed at HEAD, so the manifest pins bytes git cannot return"
        )
    if found["unresolved_imports"]:
        reasons.append(
            f"{len(found['unresolved_imports'])} imports could not be resolved to a "
            "first-party file or the standard library; the closure may be incomplete"
        )

    return {
        "schema": SCHEMA,
        "generated_at": now(),
        "read_only": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "entry_points": list(entry_points),
        "verification_entry_points": list(verification_entry_points),
        "declared_data": list(DECLARED_DATA),
        "totals": {
            "closure_files": len(files),
            "committed_at_head": len(files) - len(untracked),
            "uncommitted": len(untracked),
            "byte_identical_to_head": len(files) - len(untracked) - len(divergent),
            "divergent_from_head": len(divergent),
            "unresolved_imports": len(found["unresolved_imports"]),
        },
        "manifest": manifest,
        "head_commit": _git("rev-parse", "HEAD").decode("ascii").strip(),
        "untracked": untracked,
        "divergent_from_head": divergent,
        "unresolved_imports": found["unresolved_imports"],
        "why": reasons,
        "what_a_pass_means": (
            "every file the SFIR4 execution AND verification entry points reach "
            "is committed at HEAD and its committed bytes are byte-identical to "
            "the working tree, so the digests in this manifest name bytes git "
            "will return. It is not a statement that the code is correct, and it "
            "says nothing about the historical instruments INC-V2-089 already "
            "lost -- those bytes are gone and no commit returns them."
        ),
        "why_head_and_not_the_index": (
            "A staged but uncommitted file is exactly as unrecoverable as an "
            "untracked one, and `git ls-files` cannot tell them apart. This gate "
            "reads `git ls-tree HEAD` and then compares the blob byte for byte."
        ),
        "never_repairs_history": (
            "This gate is prospective. It does not touch a historical receipt "
            "and does not put anything under version control; it reports what "
            "must be tracked before SFIR4 may freeze."
        ),
        "verdict": "REFUSE" if reasons else "PASS",
    }


def require_recoverable() -> dict[str, Any]:
    """Fail closed. Called by the freeze path before anything is sealed."""
    body = gate()
    if body["verdict"] != "PASS":
        raise ClosureRefused(
            "SFIR4 freeze refused -- the execution closure is not recoverable: "
            + "; ".join(body["why"])
        )
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SFIR4 pre-freeze recoverability gate.")
    parser.add_argument("--write-receipt", action="store_true")
    parser.add_argument(
        "--list-untracked",
        action="store_true",
        help="print exactly the paths that must be tracked, one per line",
    )
    args = parser.parse_args(argv)

    try:
        body = gate()
    except ClosureRefused as exc:
        print(json.dumps({"verdict": "UNKNOWN", "why": str(exc)}))
        return 2

    if args.list_untracked:
        for relative in body["untracked"]:
            print(relative)
        return 0 if body["verdict"] == "PASS" else 1

    if args.write_receipt:
        path = NS / "receipts" / f"{STEM}.json"
        write_hashed(path, body)
        print(
            json.dumps(
                {"receipt": rel(path), "verdict": body["verdict"], "totals": body["totals"]},
                indent=1,
            )
        )
    else:
        print(
            json.dumps(
                {"verdict": body["verdict"], "totals": body["totals"], "why": body["why"]}, indent=1
            )
        )
    return 0 if body["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
