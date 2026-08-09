#!/usr/bin/env python
"""Refuse a migration history with more than one head.

Written for a specific failure that git cannot see. Alembic revisions form a
linear chain through ``down_revision``. When two branches each add a revision
off the same parent, git merges both files without a conflict — they are
different files, and neither touches the other's lines. The break only appears
later, when something runs ``alembic upgrade head`` and Alembic refuses because
"head" is ambiguous.

That is the worst shape a defect can have: silent at merge, loud at deploy, and
in a component where the recovery is a hand-written merge revision rather than a
revert. So this check runs in CI on every branch, and the moment two sessions
diverge one of them fails immediately with the parent they both claimed.

No database is needed. ScriptDirectory reads the files.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    if len(heads) == 1:
        revisions = list(script.walk_revisions())
        print(
            f"migration chain: single head {heads[0]} "
            f"over {len(revisions)} revisions"
        )
        return 0

    if not heads:
        print("migration chain: no revisions found — is the versions path right?")
        return 2

    print(f"migration chain: {len(heads)} heads, expected 1\n")
    for head in heads:
        revision = script.get_revision(head)
        print(f"  head {revision.revision}  <- {revision.down_revision}")
        print(f"       {Path(revision.path).name}")

    # The parent two branches both claimed is the useful part of the report:
    # it names the point where the histories diverged.
    parents: dict[str | None, list[str]] = defaultdict(list)
    for revision in script.walk_revisions():
        down = revision.down_revision
        parents[down if isinstance(down, str) or down is None else down[0]].append(
            revision.revision
        )
    for parent, children in parents.items():
        if len(children) > 1:
            print(f"\n  diverged at {parent}: {', '.join(sorted(children))}")

    # ASCII only. This runs on Windows consoles too, where a stray em-dash
    # raises UnicodeEncodeError under cp949 and turns a clear report into a
    # traceback.
    print(
        "\nFix by rebasing one branch and repointing its down_revision at the\n"
        "other's head. Not by adding a merge revision: that keeps both\n"
        "histories and makes the next divergence harder to read."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
