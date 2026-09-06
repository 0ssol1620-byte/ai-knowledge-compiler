#!/usr/bin/env python3
"""A traversal frontier that lives on disk, so repository size stops being a verdict.

SFIR7 truncated twenty of fifty roots. Not because those repositories were
beyond measurement, and not because the request budget ran out -- because the
frontier was a Python list with a cardinality bound of 256, calibrated on twenty
smaller hand-picked repositories in SFIR4. `babel`, `rails` and `react` exceeded
it and were recorded as measured. They were not measured; the instrument stopped.

**A bound on queue cardinality is not a scientific criterion and is not one
here.** Whether a repository has 200 or 200,000 tree entries says nothing about
whether its capacity can be counted. The only honest reasons to stop are running
out of an external resource -- request budget, wall clock, working storage -- and
those are stated in the units of the resource, not in units of the repository.

**So the frontier goes on disk and the bound becomes bytes.** SQLite gives
durable, ordered, deterministic storage from the standard library. Entries come
out in enqueue order and only in enqueue order, which is what makes a resumed
traversal produce the same sequence as an uninterrupted one. The visited set is a
table with a unique index rather than a set in memory, so it survives the process
that built it.

**The remaining bound is a resource-safety bound, derived from outside.** A
declared working-storage budget divided by the largest an entry can serialize
to, measured on adversarial fixtures -- longest path Git will carry, longest
object name, deepest nesting. Nothing in its derivation reads a repository. When
it binds, the disposition is `WORKING_STORAGE_BUDGET_EXHAUSTED`: an operational
stop, reported as one, never mixed in with roots that finished.

Development instrument. SFIR8 produces no capacity claim.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROTOCOL_ID = "SOURCE_FACT_IR_INSTRUMENT_CALIBRATION_V8"

#: Working storage this study is permitted to consume for frontier state, in
#: bytes. An execution-environment budget: it is a property of the machine the
#: study is allowed to run on, and no repository's size participates in it.
#: Changing it is a change to the execution envelope and is recorded as such.
DECLARED_WORKING_STORAGE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB

#: Git refuses a path longer than this, so no legitimate entry can exceed it.
#: The adversarial fixture in the controls builds exactly this path.
MAX_GIT_PATH_BYTES = 4096

#: A Git object name is 40 hex characters today and 64 under SHA-256. The wider
#: one is used so the bound does not need revisiting when that lands.
MAX_OBJECT_NAME_BYTES = 64

#: Deeper than this cannot be reached without exceeding MAX_GIT_PATH_BYTES,
#: since every level costs at least a separator and one character.
MAX_DEPTH = MAX_GIT_PATH_BYTES // 2


class FrontierRefused(RuntimeError):
    """The frontier cannot proceed without doing something dishonest."""


class WorkingStorageExhausted(RuntimeError):
    """The declared storage envelope is spent. An operational stop, not a result."""


@dataclass(frozen=True, slots=True)
class Entry:
    """One unexpanded tree object, and everything needed to resume from it."""

    root_id: str
    path: str
    tree_sha: str
    depth: int
    parent_path: str | None
    enqueue_sequence: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "root_id": self.root_id,
            "path": self.path,
            "tree_sha": self.tree_sha,
            "depth": self.depth,
            "parent_path": self.parent_path,
            "enqueue_sequence": self.enqueue_sequence,
        }

    def serialized_bytes(self) -> int:
        """Bytes as stored, which is UTF-8 -- not characters, not escaped JSON.

        `json.dumps` escapes non-ASCII by default, so it would count the twelve
        characters of an escape pair where SQLite stores four bytes. That
        overstates storage, and worse, it leaves the encode step with nothing to
        do -- which is why mutation F9, deleting that encode, survived. A number
        no control can distinguish from its own absence is not being checked.
        """
        return len(
            json.dumps(self.as_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8")
        )


def worst_case_entry_bytes() -> int:
    """The largest an entry can serialize to, built rather than estimated.

    Constructed from the protocol's own declared maxima -- Git's path limit, the
    widest object name, the deepest reachable nesting -- so the number is a
    property of the format, not of any repository that happens to have been
    traversed. `test_the_worst_case_is_not_beatable_by_an_adversarial_entry`
    tries to exceed it and must fail.
    """
    return Entry(
        root_id="x" * MAX_GIT_PATH_BYTES,
        path="x" * MAX_GIT_PATH_BYTES,
        tree_sha="f" * MAX_OBJECT_NAME_BYTES,
        depth=MAX_DEPTH,
        parent_path="x" * MAX_GIT_PATH_BYTES,
        enqueue_sequence=2**63 - 1,
    ).serialized_bytes()


def max_frontier_entries(
    *, working_storage_bytes: int = DECLARED_WORKING_STORAGE_BYTES
) -> int:
    """How many entries the declared envelope holds in the worst case.

    Note the direction of the derivation. It starts at a budget the execution
    environment grants and divides by a worst case the format guarantees. It
    never asks how large a repository was, which is what SFIR4's 256 did and
    what made that number untransportable to repositories nobody had looked at.
    """
    return working_storage_bytes // worst_case_entry_bytes()


class Frontier:
    """FIFO by enqueue sequence, on disk, with a persistent visited set."""

    def __init__(
        self,
        database: Path | str,
        *,
        working_storage_bytes: int = DECLARED_WORKING_STORAGE_BYTES,
    ) -> None:
        self.path = Path(database)
        self.working_storage_bytes = working_storage_bytes
        self.capacity = max_frontier_entries(working_storage_bytes=working_storage_bytes)
        self._db = sqlite3.connect(self.path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS frontier (
                   enqueue_sequence INTEGER PRIMARY KEY,
                   root_id TEXT NOT NULL,
                   path TEXT NOT NULL,
                   tree_sha TEXT NOT NULL,
                   depth INTEGER NOT NULL,
                   parent_path TEXT,
                   leased INTEGER NOT NULL DEFAULT 0,
                   completed INTEGER NOT NULL DEFAULT 0
               )"""
        )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS visited (
                   root_id TEXT NOT NULL,
                   tree_sha TEXT NOT NULL,
                   PRIMARY KEY (root_id, tree_sha)
               )"""
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS frontier_pending "
            "ON frontier (completed, leased, enqueue_sequence)"
        )
        # A lease belongs to the process that took it. This one holds none yet,
        # so anything left in flight when the previous segment ended returns to
        # pending -- it was handed out and never finished, which is exactly the
        # state a resumed traversal has to replay.
        self._db.execute("UPDATE frontier SET leased = 0 WHERE completed = 0")
        self._db.commit()

    # -- lifecycle --------------------------------------------------------

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    def __enter__(self) -> Frontier:
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False

    # -- enqueue / dequeue ------------------------------------------------

    def enqueue(
        self,
        *,
        root_id: str,
        path: str,
        tree_sha: str,
        depth: int,
        parent_path: str | None,
    ) -> Entry | None:
        """Add an unvisited tree. Returns None if it was already seen.

        Deduplication is on `(root_id, tree_sha)`: the same tree object reached
        by two paths is one subtree and expanding it twice would double-count
        every candidate beneath it.
        """
        if self.visited(root_id, tree_sha):
            return None
        if self.pending_count() >= self.capacity:
            raise WorkingStorageExhausted(
                f"the frontier holds {self.pending_count()} pending entries and the "
                f"declared working-storage budget of {self.working_storage_bytes} bytes "
                f"admits {self.capacity}. This is an execution-envelope stop and must "
                "be reported as WORKING_STORAGE_BUDGET_EXHAUSTED, never as a completed "
                "traversal."
            )
        cursor = self._db.execute(
            "INSERT INTO frontier (root_id, path, tree_sha, depth, parent_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (root_id, path, tree_sha, depth, parent_path),
        )
        self._db.execute(
            "INSERT INTO visited (root_id, tree_sha) VALUES (?, ?)", (root_id, tree_sha)
        )
        self._db.commit()
        return Entry(
            root_id=root_id,
            path=path,
            tree_sha=tree_sha,
            depth=depth,
            parent_path=parent_path,
            enqueue_sequence=int(cursor.lastrowid),
        )

    def dequeue(self) -> Entry | None:
        """Lease the oldest unfinished entry, and only ever the oldest.

        Strict enqueue order is what makes a segmented traversal reproduce an
        uninterrupted one. Any ordering that consults the entry's *content* --
        depth, path, size -- would make resume order depend on what was in
        memory when the process stopped.

        This is a lease, not a removal. An entry is finished only when
        `complete` says so, so a segment that ends between handing an entry out
        and expanding it leaves that entry pending rather than consumed. The
        earlier version marked it consumed immediately, which meant a storage
        refusal mid-expansion dropped the whole subtree beneath it and no
        resumed segment ever went back for it -- a silent loss of candidates,
        reported as a completed traversal.
        """
        row = self._db.execute(
            "SELECT enqueue_sequence, root_id, path, tree_sha, depth, parent_path "
            "FROM frontier WHERE completed = 0 AND leased = 0 "
            "ORDER BY enqueue_sequence LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        self._db.execute(
            "UPDATE frontier SET leased = 1 WHERE enqueue_sequence = ?", (row[0],)
        )
        self._db.commit()
        return Entry(
            enqueue_sequence=row[0],
            root_id=row[1],
            path=row[2],
            tree_sha=row[3],
            depth=row[4],
            parent_path=row[5],
        )

    def complete(self, entry: Entry) -> None:
        """Mark a leased entry finished. Only expansion may call this."""
        self._db.execute(
            "UPDATE frontier SET completed = 1 WHERE enqueue_sequence = ?",
            (entry.enqueue_sequence,),
        )
        self._db.commit()

    def release(self, entry: Entry) -> None:
        """Return a leased entry to pending, unfinished."""
        self._db.execute(
            "UPDATE frontier SET leased = 0 WHERE enqueue_sequence = ? AND completed = 0",
            (entry.enqueue_sequence,),
        )
        self._db.commit()

    # -- reading ----------------------------------------------------------

    def visited(self, root_id: str, tree_sha: str) -> bool:
        return (
            self._db.execute(
                "SELECT 1 FROM visited WHERE root_id = ? AND tree_sha = ?",
                (root_id, tree_sha),
            ).fetchone()
            is not None
        )

    def pending_count(self) -> int:
        """Entries still held: unfinished, whether or not currently leased."""
        return int(
            self._db.execute(
                "SELECT COUNT(*) FROM frontier WHERE completed = 0"
            ).fetchone()[0]
        )

    def visited_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM visited").fetchone()[0])

    def pending(self) -> Iterator[Entry]:
        """Every pending entry in enqueue order. For digesting, not for driving."""
        for row in self._db.execute(
            "SELECT enqueue_sequence, root_id, path, tree_sha, depth, parent_path "
            "FROM frontier WHERE completed = 0 ORDER BY enqueue_sequence"
        ):
            yield Entry(
                enqueue_sequence=row[0],
                root_id=row[1],
                path=row[2],
                tree_sha=row[3],
                depth=row[4],
                parent_path=row[5],
            )

    def bounds(self) -> dict[str, Any]:
        """What is bounding this traversal, in the units of the thing that binds."""
        return {
            "protocol_id": PROTOCOL_ID,
            "declared_working_storage_bytes": self.working_storage_bytes,
            "worst_case_entry_bytes": worst_case_entry_bytes(),
            "max_frontier_entries": self.capacity,
            "derived_from": (
                "an execution-environment storage budget divided by a worst case "
                "the serialization format guarantees. No repository's observed size "
                "participates in this number."
            ),
            "queue_cardinality_is_a_truncation_criterion": False,
            "why_not": (
                "a repository is not less measurable for being large. SFIR4 bounded "
                "the queue at 256 entries, calibrated on twenty smaller repositories, "
                "and SFIR7 recorded twenty of fifty externally-selected roots as "
                "measured when the instrument had merely stopped."
            ),
        }
