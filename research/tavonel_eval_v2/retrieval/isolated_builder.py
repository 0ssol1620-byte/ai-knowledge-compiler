#!/usr/bin/env python3
"""Query builder as an isolated subprocess. Confirmatory-only hardening.

P4e's in-process ``IntentView`` result stands and is not revised. That contract
is enforced by the object: a forbidden field is refused at construction, the
class has ``__slots__``, and the builder takes one argument. It is strong, and
it is enforced by code running in the same interpreter as everything else.

For a **confirmatory** experiment that is not enough, because the argument
"nothing else was reachable" rests on the discipline of every module sharing the
process. This harness removes that dependency: the builder runs in a separate
interpreter started with ``-I -S``, receives a serialised ``IntentView`` on
stdin, and returns a query on stdout.

* ``-I`` — isolated: no ``PYTHONPATH``, no user site directory, no ``.pth``
  processing, ``sys.path[0]`` not set from the script's directory.
* ``-S`` — no ``site``: the standard site-packages machinery does not run, so an
  installed package cannot be imported by accident.
* stdin carries **only** the five permitted fields. No body, no oracle, no
  revision identifier, no retrieval result, and no path to any of them.
* the child imports nothing from this repository and touches no file. Its whole
  world is one JSON object.

Run this module directly and it behaves as the child. Call
:func:`build_query_isolated` and it behaves as the parent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

#: The five permitted intent sources, restated here rather than imported.
#: The child must not import from this repository — importing the list from
#: ``intent_view`` would put that module, and everything it can reach, on the
#: child's path, which is the thing this harness exists to prevent.
PERMITTED = (
    "document_title",
    "document_identity",
    "document_type",
    "anchor_heading",
    "parent_heading",
)


# --- child -------------------------------------------------------------------


def _child() -> int:
    """Read one serialised view, write one query. Nothing else."""
    payload = json.loads(sys.stdin.read())
    unexpected = sorted(set(payload) - set(PERMITTED))
    if unexpected:
        sys.stdout.write(
            json.dumps({"error": "FORBIDDEN_FIELD", "fields": unexpected})
        )
        return 2

    anchor = payload.get("anchor_heading")
    parent = payload.get("parent_heading")
    identity = payload.get("document_identity")
    doc_type = payload.get("document_type")
    where = "in the " + str(doc_type) + " for " + str(identity)
    if parent:
        query = (
            "what does the section on " + str(anchor) + " under " + str(parent)
            + " say " + where + "?"
        )
    else:
        query = "what does the section on " + str(anchor) + " say " + where + "?"

    sys.stdout.write(
        json.dumps(
            {
                "query": query,
                "provenance": [
                    {"field": name, "provenance": name, "permitted": True}
                    for name in PERMITTED
                    if payload.get(name) is not None
                ],
                "isolation": {
                    "flags": ["-I", "-S"],
                    "site_imported": "site" in sys.modules,
                    "sys_path_entries": len(sys.path),
                    "repository_modules_imported": sorted(
                        name
                        for name in sys.modules
                        if name in {"intent_view", "envelope", "source_spans", "common"}
                    ),
                },
            }
        )
    )
    return 0


# --- parent ------------------------------------------------------------------


class IsolationFailed(Exception):
    """The child refused, crashed, or returned something unusable."""


def build_query_isolated(fields: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
    """Run the builder in a fresh isolated interpreter.

    ``fields`` is filtered to the permitted five **before** it is serialised, so
    a forbidden value is never written to the child's stdin at all. The child
    also refuses it independently; neither check is load-bearing alone, which is
    the point of having both.
    """
    payload = {name: fields.get(name) for name in PERMITTED if name in fields}
    forbidden = sorted(set(fields) - set(PERMITTED))
    if forbidden:
        raise IsolationFailed("refused to serialise forbidden fields: " + ", ".join(forbidden))

    done = subprocess.run(
        [sys.executable, "-I", "-S", str(Path(__file__).resolve())],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(Path(__file__).resolve().parent),
    )
    if done.returncode != 0:
        raise IsolationFailed(
            "child exited " + str(done.returncode) + ": " + (done.stdout or done.stderr)[:400]
        )
    try:
        result = json.loads(done.stdout)
    except json.JSONDecodeError as error:
        raise IsolationFailed("child produced no usable output") from error
    if "error" in result:
        raise IsolationFailed(result["error"])
    return result


def isolation_evidence() -> dict[str, Any]:
    """Demonstrate the contract, including the refusals, in one call.

    Three probes: a normal build, a forbidden field refused by the parent before
    serialisation, and a forbidden field forced past the parent to prove the
    child refuses on its own.
    """
    ok = build_query_isolated(
        {
            "document_title": "uv documentation",
            "document_identity": "astral-sh/uv",
            "document_type": "documentation",
            "anchor_heading": "Dependency fields",
            "parent_heading": "Managing dependencies",
        }
    )

    parent_refused = False
    try:
        build_query_isolated(
            {
                "document_title": "t",
                "document_identity": "i",
                "document_type": "d",
                "anchor_heading": "a",
                "parent_heading": None,
                "atom_body": "the resolver reads dependency-groups",
            }
        )
    except IsolationFailed:
        parent_refused = True

    forced = subprocess.run(
        [sys.executable, "-I", "-S", str(Path(__file__).resolve())],
        input=json.dumps(
            {
                "document_title": "t",
                "document_identity": "i",
                "document_type": "d",
                "anchor_heading": "a",
                "atom_body": "the resolver reads dependency-groups",
            }
        ),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).resolve().parent),
    )
    child_refused = forced.returncode != 0 and "FORBIDDEN_FIELD" in forced.stdout

    return {
        "query_built": ok["query"],
        "provenance": ok["provenance"],
        "child_isolation": ok["isolation"],
        "parent_refuses_before_serialising": parent_refused,
        "child_refuses_independently": child_refused,
        "no_repository_module_in_child": ok["isolation"]["repository_modules_imported"] == [],
        "passed": bool(
            parent_refused
            and child_refused
            and ok["isolation"]["repository_modules_imported"] == []
        ),
    }


if __name__ == "__main__":
    raise SystemExit(_child())
