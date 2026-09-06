"""Does the Protected Core that will actually load implement SFIR4's algorithm?

Two questions this answers that a green test run does not, and that a revision
pin does not either:

**Which akc_cir is going to load?**
    The shared virtualenv installs the repository editable, and its ``.pth``
    hard-codes ``D:\\CodexProjects\\ai-knowledge-compiler\\packages\\cir-python\\src``
    -- an absolute path into the SHARED working tree. Running a study from an
    isolated checkout pinned to an exact revision therefore imports the shared
    tree's Protected Core anyway, unless something forces otherwise. Every
    receipt would say ``isolated_git_checkout`` and every digest would name the
    pinned revision, and the code that ran would be whatever a developer had
    open at the time. That is a false PASS generator, and it is the precise
    shape of failure this study keeps rediscovering.

**Does that akc_cir have the semantics the paper claims?**
    A revision can be clean, committed, byte-identical and recoverable and still
    not implement the algorithm under study. ``79dd3b7`` is exactly that: it
    satisfies every recoverability property and is missing
    ``DependencyChannel``, ``FacetVerdict``, ``StructuralPolicy`` and
    ``ChangeChannel``, so SFIR4 cannot import it, let alone measure with it.
    Freezing a coherent-but-wrong revision produces a reproducible measurement
    of the wrong instrument.

``REQUIRED_SYMBOLS`` is the paper's claim chain expressed as an import list. It
is not a convenience re-export of what SFIR4 happens to import today: each entry
carries the claim it carries, so that a symbol disappearing is reported as the
claim it breaks rather than as an ImportError three layers down.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, ROOT, now, rel, sha_file, write_hashed

SCHEMA = "tavonel.sfir4.core_conformance.v1"
STEM = "sfir4-core-conformance"

#: The Protected Core modules SFIR4 executes.
CORE_MODULES: tuple[str, ...] = (
    "akc_cir.dependency",
    "akc_cir.recompilation",
    "akc_cir.semantic_diff",
)

#: (module, symbol) -> the paper claim that symbol carries.
#:
#: Written from the claim chain, not from the import statements, so that this
#: gate answers "is the algorithm present" rather than "does today's code
#: happen to link".
REQUIRED_SYMBOLS: dict[tuple[str, str], str] = {
    ("akc_cir.semantic_diff", "UnitSnapshot"): (
        "stable logical identity is separate from physical evidence occurrence"
    ),
    ("akc_cir.semantic_diff", "ChangeChannel"): (
        "identity and change are decided independently, by typed comparators"
    ),
    ("akc_cir.semantic_diff", "content_facet_verdict"): (
        "the change decision is taken on CONTENT, derived without consulting identity"
    ),
    ("akc_cir.semantic_diff", "QUARANTINE_UNSETTLED_IDENTITY_DEFAULT"): (
        "an identity the resolver could not settle is quarantined, fail-closed"
    ),
    ("akc_cir.semantic_diff", "SemanticDiff"): "the diff is a typed, inspectable result",
    ("akc_cir.semantic_diff", "diff_documents"): "documents are diffed at a declared level",
    ("akc_cir.semantic_diff", "DiffLevel"): "the diff level is explicit, never implied",
    ("akc_cir.dependency", "DependencyChannel"): (
        "dependency propagation is typed: an edge is sensitive to named channels"
    ),
    ("akc_cir.dependency", "ALL_DEPENDENCY_CHANNELS"): (
        "the channel set is closed and enumerable, so a traversal cannot silently omit one"
    ),
    ("akc_cir.dependency", "DependencyGraph"): "the dependency graph is the propagation substrate",
    ("akc_cir.recompilation", "plan_recompilation"): (
        "recompilation is planned selectively from a seed set, not by full rebuild"
    ),
    ("akc_cir.recompilation", "FacetVerdict"): (
        "every facet's outcome is recorded, including UNRESOLVED -- a change that "
        "resolved to nothing must leave a trace of having been seen"
    ),
    ("akc_cir.recompilation", "StructuralPolicy"): (
        "structural participation in the traversal is a declared policy, not a constant"
    ),
}


class ConformanceRefused(RuntimeError):
    """The Protected Core that would load is not the one the study claims."""


def resolve_core() -> dict[str, Any]:
    """Where akc_cir actually resolves from, in this interpreter, right now."""
    try:
        package = importlib.import_module("akc_cir")
    except ImportError as error:
        raise ConformanceRefused(f"akc_cir cannot be imported at all: {error}") from error
    origin = getattr(package, "__file__", None)
    if not origin:
        raise ConformanceRefused("akc_cir has no file origin; it may be a namespace shim")
    path = Path(origin).resolve()
    return {"package_root": str(path.parent), "origin": str(path)}


def check_symbols() -> dict[str, Any]:
    """Which required symbols are present in the akc_cir that would load."""
    present: list[str] = []
    absent: list[dict[str, str]] = []
    unimportable: list[dict[str, str]] = []

    for module_name in CORE_MODULES:
        try:
            importlib.import_module(module_name)
        except ImportError as error:
            unimportable.append({"module": module_name, "error": str(error)})

    for (module_name, symbol), claim in sorted(REQUIRED_SYMBOLS.items()):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            absent.append({"module": module_name, "symbol": symbol, "claim_broken": claim})
            continue
        if hasattr(module, symbol):
            present.append(f"{module_name}.{symbol}")
        else:
            absent.append({"module": module_name, "symbol": symbol, "claim_broken": claim})

    return {"present": present, "absent": absent, "unimportable": unimportable}


def conformance(expected_root: Path | None = None) -> dict[str, Any]:
    """The full conformance statement.

    ``expected_root`` is the ``src`` directory the study intends to execute. When
    given, akc_cir resolving from anywhere else is a refusal -- that is the check
    that keeps ``execution_environment: isolated_git_checkout`` from being a
    claim about a directory nothing actually imported.
    """
    where = resolve_core()
    symbols = check_symbols()

    reasons: list[str] = []
    if symbols["absent"]:
        broken = sorted({row["claim_broken"] for row in symbols["absent"]})
        reasons.append(
            f"{len(symbols['absent'])} required Protected Core symbols are absent; "
            f"{len(broken)} paper claims are unimplemented by the core that would load"
        )
    if symbols["unimportable"]:
        reasons.append(f"{len(symbols['unimportable'])} Protected Core modules cannot be imported")
    if expected_root is not None:
        wanted = expected_root.resolve()
        actual = Path(where["package_root"]).resolve()
        if wanted != actual.parent and wanted != actual:
            reasons.append(
                f"akc_cir resolves from {actual}, not from the intended {wanted}; "
                "the interpreter would execute a different Protected Core than the "
                "one this study pins"
            )

    core_files = {}
    for name in CORE_MODULES:
        candidate = Path(where["package_root"]) / (name.split(".")[-1] + ".py")
        if candidate.is_file():
            core_files[rel(candidate) if candidate.is_relative_to(ROOT) else str(candidate)] = (
                sha_file(candidate)
            )

    return {
        "schema": SCHEMA,
        "generated_at": now(),
        "read_only": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "resolved_from": where,
        "expected_root": str(expected_root) if expected_root else None,
        "core_file_digests": core_files,
        "totals": {
            "required_symbols": len(REQUIRED_SYMBOLS),
            "present": len(symbols["present"]),
            "absent": len(symbols["absent"]),
            "unimportable_modules": len(symbols["unimportable"]),
        },
        "present": symbols["present"],
        "absent": symbols["absent"],
        "unimportable": symbols["unimportable"],
        "why": reasons,
        "what_a_pass_means": (
            "the akc_cir that this interpreter would actually import comes from "
            "the intended root and exposes every symbol the paper's claim chain "
            "depends on. It is not a statement that those symbols are correct -- "
            "the SFIR4 suite and the hostile audit speak to that -- only that the "
            "algorithm under study is the algorithm that would run."
        ),
        "verdict": "REFUSE" if reasons else "PASS",
    }


def require_conformant(expected_root: Path | None = None) -> dict[str, Any]:
    """Fail closed before a freeze."""
    body = conformance(expected_root)
    if body["verdict"] != "PASS":
        raise ConformanceRefused(
            "SFIR4 refused -- Protected Core conformance: " + "; ".join(body["why"])
        )
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SFIR4 Protected Core conformance gate.")
    parser.add_argument(
        "--expected-root",
        type=Path,
        help="the src directory akc_cir must resolve from",
    )
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args(argv)

    try:
        body = conformance(args.expected_root)
    except ConformanceRefused as exc:
        print(json.dumps({"verdict": "UNKNOWN", "why": str(exc)}, indent=1))
        return 2

    if args.write_receipt:
        path = NS / "receipts" / f"{STEM}.json"
        write_hashed(path, body)
        summary = {"receipt": rel(path), "verdict": body["verdict"], "totals": body["totals"]}
    else:
        summary = {
            "verdict": body["verdict"],
            "resolved_from": body["resolved_from"]["package_root"],
            "totals": body["totals"],
            "absent": body["absent"],
            "why": body["why"],
        }
    print(json.dumps(summary, indent=1))
    return 0 if body["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
