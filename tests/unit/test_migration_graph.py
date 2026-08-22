"""Guard the Alembic revision graph against silent merge damage.

Two branches each added a revision numbered 0023 and each pointed it at
0022_cdr_derivative_lineage. Neither branch was broken on its own; the fork only
exists once they meet, and by then the person merging is looking at a file list,
not a graph. `alembic upgrade head` then fails with a multiple-heads error at
deploy time, which is the worst moment to discover it.

Nothing in the suite read these files, so nothing could have caught it. This
does: it parses every revision, follows the parent pointers, and fails when the
graph stops being a single chain.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
VERSIONS = REPOSITORY / "migrations" / "versions"

REVISION = re.compile(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", re.M)
DOWN_REVISION = re.compile(
    r"^down_revision(?::\s*[^=]+?)?\s*=\s*(?:None|[\"']([^\"']+)[\"'])", re.M
)


def _graph() -> tuple[dict[str, str], dict[str, str | None]]:
    """revision id -> filename, and revision id -> parent revision id."""
    files: dict[str, str] = {}
    parents: dict[str, str | None] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision = REVISION.search(text)
        assert revision, f"{path.name} declares no revision id"
        identifier = revision.group(1)
        assert identifier not in files, (
            f"revision id {identifier!r} is declared by both {files[identifier]} "
            f"and {path.name}"
        )
        files[identifier] = path.name
        down = DOWN_REVISION.search(text)
        assert down, f"{path.name} declares no down_revision"
        parents[identifier] = down.group(1)
    return files, parents


def test_the_versions_directory_is_present() -> None:
    assert VERSIONS.is_dir(), f"expected migrations at {VERSIONS}"
    assert list(VERSIONS.glob("*.py")), "no migrations found"


def test_every_parent_pointer_resolves() -> None:
    files, parents = _graph()
    dangling = {
        files[revision]: parent
        for revision, parent in parents.items()
        if parent is not None and parent not in files
    }
    assert dangling == {}, f"down_revision points at a revision that does not exist: {dangling}"


def test_no_two_revisions_claim_the_same_parent() -> None:
    """A fork is what a duplicate 0023 looks like from the graph's side."""
    files, parents = _graph()
    children: dict[str | None, list[str]] = {}
    for revision, parent in parents.items():
        children.setdefault(parent, []).append(revision)
    forks = {
        parent: sorted(files[child] for child in siblings)
        for parent, siblings in children.items()
        if parent is not None and len(siblings) > 1
    }
    assert forks == {}, (
        "two migrations share a parent, so `alembic upgrade head` will report "
        f"multiple heads: {forks}"
    )


def test_there_is_exactly_one_head() -> None:
    files, parents = _graph()
    parented = {parent for parent in parents.values() if parent is not None}
    heads = sorted(files[revision] for revision in files if revision not in parented)
    assert len(heads) == 1, f"expected a single head, found {heads}"


def test_there_is_exactly_one_base() -> None:
    files, parents = _graph()
    bases = sorted(files[revision] for revision, parent in parents.items() if parent is None)
    assert len(bases) == 1, f"expected a single base revision, found {bases}"


def test_the_chain_reaches_every_revision_from_the_head() -> None:
    """A cycle or an orphaned island passes the checks above but not this one."""
    files, parents = _graph()
    parented = {parent for parent in parents.values() if parent is not None}
    head = next(revision for revision in files if revision not in parented)

    walked: list[str] = []
    seen: set[str] = set()
    cursor: str | None = head
    while cursor is not None:
        assert cursor not in seen, f"revision cycle through {files[cursor]}"
        seen.add(cursor)
        walked.append(cursor)
        cursor = parents[cursor]

    unreachable = sorted(files[revision] for revision in set(files) - seen)
    assert unreachable == [], f"revisions not reachable from the head: {unreachable}"
    assert len(walked) == len(files)
