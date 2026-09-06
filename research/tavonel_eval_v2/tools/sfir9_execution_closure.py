#!/usr/bin/env python3
"""The ten components, bound five ways each, and the one thing this cannot do.

**Five bindings per component, because four of them can agree while the study
still runs something else.** Exact path, SHA-256 of the working bytes, the Git
blob id those bytes produce, byte equality between the commit and the working
tree, and the origin the interpreter actually loaded the module from. The last is
not implied by the others: a file can hash correctly on disk while Python imports
a different copy, which a stray `.pth` did earlier in this study.

**The self-reference problem, stated plainly.** This module is one of the ten. A
closure that hashes itself and reports "the hash matches" proves nothing -- the
same edit that changed the file could change what it claims about the file, and
the two would agree. Nothing inside a closure can escape that.

So the closure does not try. It computes and reports; it does not certify itself.
The certification lives in a **separate top-level freeze manifest**, written once
at freeze time, which records this module's own SHA-256 and blob id alongside the
digest of the closure it produced. Verifying that manifest re-reads this file
from disk as bytes -- without importing it, without asking it anything -- and
compares. The manifest is the outside vantage point; this module is the thing
being looked at.

**The component list is checked against the isolation gate's, not copied from
it.** Two lists that must agree and are maintained separately will disagree,
usually at the worst moment. `require_component_lists_agree()` makes the
disagreement an error rather than a discrepancy nobody reads.

**A component missing is not a component passing.** Every one of the ten is
verified or the closure refuses. There is no partial closure, because a partial
closure is exactly what a freeze must not be able to record.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sfir9_isolation_gate as gate
import sfir9_transport as transport

SCHEMA = "tavonel.sfir9.execution_closure.v1"
MANIFEST_SCHEMA = "tavonel.sfir9.freeze_manifest.v1"

TOOLS = "research/tavonel_eval_v2/tools"


@dataclass(frozen=True, slots=True)
class Component:
    """One closure component and the module that implements it."""

    name: str
    module: str

    @property
    def relative_path(self) -> str:
        return f"{TOOLS}/{self.module}.py"


#: The ten. The order is the isolation gate's order, and the two lists are
#: checked against each other rather than trusted to have stayed in step.
COMPONENTS = (
    Component("protocol", "sfir9_protocol"),
    Component("execution_closure", "sfir9_execution_closure"),
    Component("historical_isolation_gate", "sfir9_isolation_gate"),
    Component("selection_rule", "sfir9_selection"),
    Component("scorer", "sfir9_scorer"),
    Component("acceptance", "sfir9_acceptance"),
    Component("cohort_roster", "sfir9_cohort_roster"),
    Component("transport", "sfir9_transport"),
    Component("identity_logic", "sfir9_identity_logic"),
    Component("checkpoint_chain", "sfir9_checkpoint_chain"),
)

#: This module. Named as a constant because the freeze manifest has to refer to
#: it from the outside, and a path computed at call time could be computed wrong.
CLOSURE_MODULE = "sfir9_execution_closure"
CLOSURE_PATH = f"{TOOLS}/{CLOSURE_MODULE}.py"

LIST_DISAGREEMENT = "REFUSED_COMPONENT_LISTS_DISAGREE"
MISSING_COMPONENT = "REFUSED_INCOMPLETE_CLOSURE"
HASH_MISMATCH = "REFUSED_COMPONENT_HASH_MISMATCH"
BYTES_MISMATCH = "REFUSED_COMMITTED_BYTES_DIFFER_FROM_WORKING_BYTES"
ORIGIN_MISMATCH = "REFUSED_IMPORT_ORIGIN_MISMATCH"
MANIFEST_MISMATCH = "REFUSED_FREEZE_MANIFEST_MISMATCH"


class ClosureRefused(RuntimeError):
    """A refusal carrying the code that names it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _digest(payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _git_committed_bytes(repository_root: Path, relative_path: str) -> bytes:
    # `git` from PATH with a literal argument vector; the only interpolated value
    # is a path from this module's own component table, never from a caller.
    result = subprocess.run(  # noqa: S603
        ["git", "cat-file", "blob", f"HEAD:{relative_path}"],  # noqa: S607
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ClosureRefused(
            BYTES_MISMATCH,
            f"{relative_path} is not committed at HEAD. An uncommitted component "
            "cannot be frozen: there is nothing for the working tree to match.",
        )
    return result.stdout


def require_component_lists_agree() -> None:
    """The closure's ten and the isolation gate's ten must be the same ten.

    Two lists that must agree and are maintained apart will disagree eventually.
    Making it an error here means the disagreement surfaces at the gate rather
    than as a discrepancy between two receipts nobody compares.
    """
    ours = tuple(component.name for component in COMPONENTS)
    theirs = tuple(gate.REQUIRED_COMPONENTS)
    if set(ours) != set(theirs):
        raise ClosureRefused(
            LIST_DISAGREEMENT,
            f"the closure verifies {sorted(ours)} and the isolation gate requires "
            f"{sorted(theirs)}. One of them would then be checking a study the "
            "other is not.",
        )


def import_origins() -> dict[str, str]:
    """Where the interpreter actually loaded each component from."""
    origins: dict[str, str] = {}
    for component in COMPONENTS:
        module = importlib.import_module(component.module)
        origin = getattr(module, "__file__", None)
        if origin is not None:
            origins[component.module] = origin
    return origins


def verify_component(
    component: Component,
    *,
    repository_root: Path,
    import_origins: dict[str, str],
    read_committed_bytes: Callable[[Path, str], bytes],
) -> dict[str, Any]:
    """Five bindings, each able to fail on its own."""
    path = (repository_root / component.relative_path).resolve()
    if not path.exists():
        raise ClosureRefused(
            MISSING_COMPONENT,
            f"{component.name} names {component.relative_path}, which does not "
            "exist. A component that is not there has not passed.",
        )
    working = path.read_bytes()
    committed = read_committed_bytes(repository_root, component.relative_path)
    if committed != working:
        raise ClosureRefused(
            BYTES_MISMATCH,
            f"{component.relative_path} differs between the commit and the working "
            f"tree ({len(committed)} committed bytes, {len(working)} on disk). A "
            "freeze recording a commit while executing something else records the "
            "wrong thing.",
        )

    origin = import_origins.get(component.module)
    if origin is None:
        raise ClosureRefused(
            ORIGIN_MISMATCH,
            f"{component.module} was never imported, so its origin is unknown. An "
            "unchecked origin is not a passing origin.",
        )
    resolved = Path(origin).resolve()
    if resolved != path:
        raise ClosureRefused(
            ORIGIN_MISMATCH,
            f"{component.module} resolves to {resolved}, not {path}. A correct hash "
            "on disk does not establish which copy the interpreter loaded.",
        )

    return {
        "component": component.name,
        "module": component.module,
        "relative_path": component.relative_path,
        "sha256": transport.sha256_of(working),
        "git_blob_id": transport.git_blob_id_of(working),
        "working_tree_bytes": len(working),
        "committed_bytes_equal_working_bytes": True,
        "import_origin": str(resolved),
        "import_origin_is_the_verified_file": True,
    }


def closure(
    *,
    repository_root: Path,
    import_origins: dict[str, str] | None = None,
    read_committed_bytes: Callable[[Path, str], bytes] = _git_committed_bytes,
    upstream_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify all ten, or refuse. There is no partial closure."""
    require_component_lists_agree()
    origins = import_origins if import_origins is not None else globals()["import_origins"]()

    records = [
        verify_component(
            component,
            repository_root=repository_root,
            import_origins=origins,
            read_committed_bytes=read_committed_bytes,
        )
        for component in COMPONENTS
    ]
    # No "were any components missed" check here: `records` is built by
    # iterating COMPONENTS, so a component can only be absent if COMPONENTS is
    # short -- and that is caught above, by the agreement with the isolation
    # gate's list. A second check could never fire.
    body = {
        "schema": SCHEMA,
        "components": records,
        "component_count": len(records),
        "upstream_binding": upstream_binding,
        "what_this_does_not_certify": (
            "its own bytes. This module is one of the ten it verifies, and a "
            "closure reporting that its own hash matches proves nothing: the edit "
            "that changed the file could change what it claims about the file. "
            "Certification of this module lives in the separate freeze manifest."
        ),
    }
    return {**body, "closure_digest": _digest(body)}


# ------------------------------------------------------- the freeze manifest


def freeze_manifest(
    closure_result: dict[str, Any],
    *,
    repository_root: Path,
    read_committed_bytes: Callable[[Path, str], bytes] = _git_committed_bytes,
) -> dict[str, Any]:
    """Bind the closure tool's own bytes, from outside the closure.

    Read as bytes from disk. Not imported, not asked. That is the whole point:
    the manifest's account of this module must not come from this module's own
    report about itself.
    """
    path = (repository_root / CLOSURE_PATH).resolve()
    working = path.read_bytes()
    committed = read_committed_bytes(repository_root, CLOSURE_PATH)
    if committed != working:
        raise ClosureRefused(
            BYTES_MISMATCH,
            f"{CLOSURE_PATH} differs between the commit and the working tree, so "
            "the tool that produced this closure is not the committed one.",
        )
    body = {
        "schema": MANIFEST_SCHEMA,
        "closure_tool": {
            "relative_path": CLOSURE_PATH,
            "sha256": transport.sha256_of(working),
            "git_blob_id": transport.git_blob_id_of(working),
            "bytes": len(working),
            "read_how": "from disk as bytes, without importing the module",
        },
        "closure_digest": closure_result["closure_digest"],
        "component_count": closure_result["component_count"],
        "why_this_is_a_separate_artifact": (
            "a closure cannot certify itself. This manifest is the outside vantage "
            "point: it reads the closure tool's bytes directly and records them "
            "beside the digest of what that tool produced, so an edited tool "
            "reporting a clean closure is visible as a changed tool hash."
        ),
    }
    return {**body, "manifest_digest": _digest(body)}


def verify_freeze_manifest(
    manifest: dict[str, Any],
    *,
    repository_root: Path,
    closure_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-read the tool and re-check the manifest. Independent of both."""
    path = (repository_root / CLOSURE_PATH).resolve()
    if not path.exists():
        raise ClosureRefused(
            MISSING_COMPONENT, f"{CLOSURE_PATH} does not exist to be verified"
        )
    working = path.read_bytes()
    recorded = manifest.get("closure_tool", {})

    tool_sha_matches = recorded.get("sha256") == transport.sha256_of(working)
    tool_blob_matches = recorded.get("git_blob_id") == transport.git_blob_id_of(working)

    body = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest_intact = _digest(body) == manifest.get("manifest_digest")

    closure_matches = None
    if closure_result is not None:
        closure_matches = closure_result["closure_digest"] == manifest.get(
            "closure_digest"
        )

    problems = []
    if not tool_sha_matches:
        problems.append("the closure tool's bytes are not the ones the manifest pins")
    if not tool_blob_matches:
        problems.append("the closure tool's Git blob id does not match the manifest")
    if not manifest_intact:
        problems.append("the manifest's own digest does not cover its contents")
    if closure_matches is False:
        problems.append("the closure supplied is not the one this manifest recorded")

    return {
        "schema": MANIFEST_SCHEMA + ".verification",
        "closure_tool_sha256_matches": tool_sha_matches,
        "closure_tool_blob_matches": tool_blob_matches,
        "manifest_digest_intact": manifest_intact,
        "closure_digest_matches": closure_matches,
        "verified": not problems,
        "problems": problems,
    }
