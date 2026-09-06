"""Compare the Protected Core at two revisions, semantically, read-only.

Written because a diff size is not a finding. ``982 insertions`` says nothing
about whether the newer code fixes a bug, refactors, or implements the algorithm
a paper claims to evaluate, and those three have completely different
consequences for which revision may be frozen.

The comparison is over the module API surface -- classes, their members,
functions and module constants -- extracted with ``ast`` from each revision's
bytes. It never imports either revision: importing the shared working tree while
describing a pinned one is how a comparison ends up describing neither.

Each API addition is classified against ``sfir4_core_conformance.REQUIRED_SYMBOLS``.
A symbol that carries a paper claim is CLAIM_BEARING; anything else is reported
as OTHER and left for a human to read. The tool deliberately does not guess
"refactor" versus "bug fix": it reports what moved and which claims depend on it,
and a person decides.

Neither revision is modified and no file is written except this tool's receipt.
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

from common import NS, ROOT, now, write_hashed
from sfir4_core_conformance import CORE_MODULES, REQUIRED_SYMBOLS

SCHEMA = "tavonel.sfir4.core_revision_comparison.v1"
STEM = "sfir4-core-revision-comparison"

CORE_FILES: tuple[str, ...] = tuple(
    f"packages/cir-python/src/akc_cir/{name.split('.')[-1]}.py" for name in CORE_MODULES
)


class ComparisonRefused(RuntimeError):
    """The comparison cannot be made, as distinct from finding a difference."""


def _at_revision(revision: str, path: str) -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "show", f"{revision}:{path}"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ComparisonRefused(f"{path} is unreadable at {revision}: {error}") from error
    return out.stdout.decode("utf-8")


def api_surface(source: str, path: str) -> dict[str, list[str]]:
    """Top-level API of one module: classes with members, functions, constants."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        raise ComparisonRefused(f"{path} does not parse: {error}") from error

    surface: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            members: list[str] = []
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                    members.append(sub.name)
                elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                    members.append(sub.target.id)
                elif isinstance(sub, ast.Assign):
                    members.extend(
                        target.id for target in sub.targets if isinstance(target, ast.Name)
                    )
            surface[node.name] = sorted(set(members))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            surface[node.name] = sorted(argument.arg for argument in node.args.args)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    surface.setdefault(target.id, [])
    return surface


def _claims_for(module: str, symbol: str) -> str | None:
    return REQUIRED_SYMBOLS.get((module, symbol))


def compare(left: str, right: str | None = None) -> dict[str, Any]:
    """Compare ``left`` (a revision) against ``right`` (a revision, or the worktree)."""
    files: dict[str, Any] = {}
    claim_bearing_only_on_right: list[dict[str, str]] = []
    other_additions: list[dict[str, str]] = []
    removals: list[dict[str, str]] = []

    for module, path in zip(CORE_MODULES, CORE_FILES, strict=True):
        old_source = _at_revision(left, path)
        if right is None:
            new_source = (ROOT / path).read_text(encoding="utf-8")
        else:
            new_source = _at_revision(right, path)

        old, new = api_surface(old_source, path), api_surface(new_source, path)
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        member_changes = {
            name: {
                "added": sorted(set(new[name]) - set(old[name])),
                "removed": sorted(set(old[name]) - set(new[name])),
            }
            for name in sorted(set(old) & set(new))
            if set(old[name]) != set(new[name])
        }

        for symbol in added:
            claim = _claims_for(module, symbol)
            row = {"module": module, "symbol": symbol}
            if claim:
                claim_bearing_only_on_right.append({**row, "claim": claim})
            else:
                other_additions.append(row)
        for symbol in removed:
            removals.append({"module": module, "symbol": symbol})

        files[path] = {
            "left_bytes": len(old_source.encode("utf-8")),
            "right_bytes": len(new_source.encode("utf-8")),
            "api_added": added,
            "api_removed": removed,
            "member_changes": member_changes,
        }

    return {
        "schema": SCHEMA,
        "generated_at": now(),
        "read_only": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "left_revision": left,
        "right_revision": right or "WORKING_TREE",
        "files": files,
        "totals": {
            "claim_bearing_symbols_absent_from_left": len(claim_bearing_only_on_right),
            "other_api_additions": len(other_additions),
            "api_removals": len(removals),
        },
        "claim_bearing_absent_from_left": claim_bearing_only_on_right,
        "other_api_additions": other_additions,
        "api_removals": removals,
        "how_to_read_this": (
            "A symbol under claim_bearing_absent_from_left is one the paper's "
            "claim chain depends on that exists only on the right-hand side. If "
            "the right-hand side is the working tree, that claim is implemented "
            "only in uncommitted state and no revision can be frozen against it."
        ),
        "does_not_classify_intent": (
            "This tool does not label a change a refactor or a bug fix. It "
            "reports what moved and which claims depend on it; the judgement is "
            "a person's."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare Protected Core revisions.")
    parser.add_argument("--left", required=True, help="baseline revision")
    parser.add_argument("--right", help="revision to compare (default: the working tree)")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args(argv)

    try:
        body = compare(args.left, args.right)
    except ComparisonRefused as exc:
        print(json.dumps({"verdict": "UNKNOWN", "why": str(exc)}, indent=1))
        return 2

    if args.write_receipt:
        path = NS / "receipts" / f"{STEM}.json"
        write_hashed(path, body)
        print(json.dumps({"receipt": str(path.name), "totals": body["totals"]}, indent=1))
    else:
        print(
            json.dumps(
                {
                    "totals": body["totals"],
                    "claim_bearing_absent_from_left": body["claim_bearing_absent_from_left"],
                },
                indent=1,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
