#!/usr/bin/env python3
"""The traversal itself: disk-backed, resumable mid-root, and order-preserving.

This is where sections C through F stop being separate parts. The frontier is on
disk, the transport follows its own redirects and counts three layers apart, and
the checkpoint chain lets a run cross a rate window without waiting and without
being quietly steered between segments.

**The property section J has to establish is narrower than "the runs are
identical".** Segmenting a traversal legitimately changes the *transport trace*:
a segment that stops mid-root will re-issue the tree request it was in the
middle of, so hop counts and charge sums differ between an uninterrupted run and
a resumed one. What must not differ is the *scientific result* -- which
candidates were found, in what order, which roots reached exhaustion, which tree
objects were visited. Conflating those two is how a segmented run could be made
to look wrong when it is right, or right when it is wrong.

So the traversal keeps them separate by construction. Candidates, dispositions
and the visited set live in the durable store and are digested for comparison.
Request counters live in the transport and are reported alongside, never as part
of the equivalence.

**Everything durable goes in one SQLite file** -- frontier, visited set,
candidates, dispositions -- so a resumed segment inherits all of it or none of
it. State split across two stores can be half-inherited, and a half-inherited
traversal is one that silently loses candidates.

Development instrument. SFIR8 produces no capacity claim.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sfir8_checkpoint as checkpoint_module
import sfir8_frontier as frontier_module

PROTOCOL_ID = "SOURCE_FACT_IR_INSTRUMENT_CALIBRATION_V8"

#: A root reached the end of its own tree. The only disposition that means the
#: traversal, rather than a resource, decided when to stop.
COMPLETE = "FRONTIER_EXHAUSTED"

#: The provider's window ended the work. Not a completion, and never counted as
#: one -- SFIR7's census recorded truncated roots among the measured and that is
#: the mistake this vocabulary exists to make impossible.
RATE_WINDOW = "SEGMENT_COMPLETE_RATE_WINDOW"

#: The declared working-storage envelope was spent. An execution-environment
#: stop, stated in the units of the resource that ran out.
STORAGE = "WORKING_STORAGE_BUDGET_EXHAUSTED"

#: Identity could not be established, so nothing was traversed. A root that was
#: never measured, recorded as never measured.
IDENTITY_REFUSED = "REPOSITORY_IDENTITY_REFUSED"

#: Progress is guaranteed by the budget pre-check rather than watched for at
#: runtime. A segment that passes the pre-check can always afford its overhead
#: plus one expansion, so a no-progress segment cannot occur -- and a guard
#: placed where its failure is impossible is not a guard (INC-V2-036). The
#: pre-check below is the whole of the protection, and it is reachable.
#:
#: Opening a root costs two logical requests -- metadata for the identity
#: attestation, then the head commit for the tree it starts from -- and resuming
#: into one costs one, to re-attest that the address still serves the repository
#: the checkpoint was taken against. A segment budget that cannot cover its own
#: overhead plus one expansion makes no progress, and a chain of no-progress
#: segments never converges. Refused rather than spun on.
OPEN_ROOT_REQUEST_COST = 2
RESUME_ROOT_REQUEST_COST = 1
MINIMUM_SEGMENT_REQUEST_BUDGET = OPEN_ROOT_REQUEST_COST + 1


class TraversalRefused(RuntimeError):
    """The traversal cannot continue without producing a dishonest result."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """One file the traversal is willing to count, and where it came from."""

    root_id: str
    repository_numeric_id: str
    path: str
    blob_sha: str
    discovery_sequence: int

    def identity(self) -> tuple[str, str, str]:
        """What makes two candidates the same candidate.

        The numeric repository id rather than the address: the whole point of
        the identity gate is that `facebook/react` and `react/react` are one
        repository, so a candidate found through either address is one candidate.
        """
        return (self.repository_numeric_id, self.path, self.blob_sha)

    def as_dict(self) -> dict[str, Any]:
        return {
            "root_id": self.root_id,
            "repository_numeric_id": self.repository_numeric_id,
            "path": self.path,
            "blob_sha": self.blob_sha,
            "discovery_sequence": self.discovery_sequence,
        }


class TraversalStore:
    """Candidates and dispositions, in the same file as the frontier."""

    def __init__(self, database: Path | str) -> None:
        self._db = sqlite3.connect(Path(database))
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS candidates (
                   discovery_sequence INTEGER PRIMARY KEY,
                   root_id TEXT NOT NULL,
                   repository_numeric_id TEXT NOT NULL,
                   path TEXT NOT NULL,
                   blob_sha TEXT NOT NULL,
                   UNIQUE (repository_numeric_id, path, blob_sha)
               )"""
        )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS dispositions (
                   root_id TEXT PRIMARY KEY,
                   state TEXT NOT NULL,
                   repository_numeric_id TEXT,
                   canonical_address TEXT
               )"""
        )
        self._db.commit()

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    def record_candidate(
        self, *, root_id, repository_numeric_id, path, blob_sha
    ) -> Candidate | None:
        """Store a candidate, or return None if this identity is already held.

        The uniqueness constraint is on identity, not on insertion. A resumed
        segment that re-expands the tree it was interrupted inside will offer
        candidates it already found; those must not be counted twice, and they
        must not be treated as new discoveries either.
        """
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO candidates "
            "(root_id, repository_numeric_id, path, blob_sha) VALUES (?, ?, ?, ?)",
            (root_id, repository_numeric_id, path, blob_sha),
        )
        self._db.commit()
        if cursor.rowcount == 0:
            return None
        return Candidate(
            root_id=root_id,
            repository_numeric_id=repository_numeric_id,
            path=path,
            blob_sha=blob_sha,
            discovery_sequence=int(cursor.lastrowid),
        )

    def candidates(self) -> list[Candidate]:
        return [
            Candidate(
                discovery_sequence=row[0],
                root_id=row[1],
                repository_numeric_id=row[2],
                path=row[3],
                blob_sha=row[4],
            )
            for row in self._db.execute(
                "SELECT discovery_sequence, root_id, repository_numeric_id, path, "
                "blob_sha FROM candidates ORDER BY discovery_sequence"
            )
        ]

    def set_disposition(
        self, root_id, state, *, repository_numeric_id=None, canonical_address=None
    ) -> None:
        self._db.execute(
            "INSERT INTO dispositions (root_id, state, repository_numeric_id, "
            "canonical_address) VALUES (?, ?, ?, ?) ON CONFLICT(root_id) DO UPDATE "
            "SET state = excluded.state, "
            "repository_numeric_id = COALESCE(excluded.repository_numeric_id, "
            "dispositions.repository_numeric_id), "
            "canonical_address = COALESCE(excluded.canonical_address, "
            "dispositions.canonical_address)",
            (root_id, state, repository_numeric_id, canonical_address),
        )
        self._db.commit()

    def dispositions(self) -> dict[str, str]:
        return {
            row[0]: row[1]
            for row in self._db.execute(
                "SELECT root_id, state FROM dispositions ORDER BY root_id"
            )
        }

    def visited_rows(self) -> list[tuple[str, str]]:
        return [
            (row[0], row[1])
            for row in self._db.execute("SELECT root_id, tree_sha FROM visited")
        ]


@dataclass
class Result:
    """What a traversal segment produced, with the two layers kept apart."""

    candidates: list[Candidate]
    dispositions: dict[str, str]
    visited: list[tuple[str, str]]
    frontier_exhausted: bool
    roots_completed: list[str]
    #: Transport counters. Reported, never compared for scientific equivalence:
    #: a resumed segment re-issues the request it was interrupted inside, so
    #: these legitimately differ between an uninterrupted and a segmented run.
    transport_totals: dict[str, Any]

    def scientific_identity(self) -> dict[str, Any]:
        """Exactly the things segmentation must not change.

        Candidate identities *and their order*, root dispositions, the visited
        identity set, and whether the frontier was exhausted. Nothing here reads
        a request count.
        """
        return {
            "candidate_identities": [list(c.identity()) for c in self.candidates],
            "candidate_order": [c.discovery_sequence for c in self.candidates],
            "root_dispositions": dict(self.dispositions),
            "visited_identity_set": sorted(list(row) for row in self.visited),
            "frontier_exhausted": self.frontier_exhausted,
        }

    def scientific_digest(self) -> str:
        return checkpoint_module.digest(self.scientific_identity())


class Traversal:
    """Breadth-first over tree objects, one logical request per step."""

    def __init__(
        self,
        *,
        database: Path | str,
        transport: Any,
        roots: list[dict[str, str]],
        extensions: tuple[str, ...],
        study_id: str = "SFIR8-DEV",
        roster_digest: str = checkpoint_module.GENESIS,
        working_storage_bytes: int = frontier_module.DECLARED_WORKING_STORAGE_BYTES,
    ) -> None:
        self.database = Path(database)
        self.transport = transport
        self.roots = roots
        self.extensions = extensions
        self.study_id = study_id
        self.roster_digest = roster_digest
        self.frontier = frontier_module.Frontier(
            self.database, working_storage_bytes=working_storage_bytes
        )
        self.store = TraversalStore(self.database)
        self.root_index = 0
        self.current_root: dict[str, str] | None = None
        self.current_numeric_id: str | None = None
        self.current_address: str | None = None

    def close(self) -> None:
        self.store.close()
        self.frontier.close()

    def __enter__(self) -> Traversal:
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False

    # -- running ----------------------------------------------------------

    def run(self, *, request_budget: int | None = None) -> Result:
        """Traverse until the roster is done or the budget is spent.

        `request_budget` counts *logical* requests, which is what a traversal
        can govern. It is deliberately not a charge budget: charges are the
        provider's to decide and are observed, not predicted.
        """
        if (
            request_budget is not None
            and request_budget < MINIMUM_SEGMENT_REQUEST_BUDGET
        ):
            raise TraversalRefused(
                f"a segment budget of {request_budget} logical requests cannot cover "
                f"the {OPEN_ROOT_REQUEST_COST}-request cost of opening a root plus one "
                "expansion, so the segment would spend its whole budget and expand "
                "nothing. A chain of segments that each make no progress never "
                f"converges. The minimum is {MINIMUM_SEGMENT_REQUEST_BUDGET}."
            )
        start = self.transport.totals()["logical_requests"]

        def spent() -> int:
            return self.transport.totals()["logical_requests"] - start

        while self.root_index < len(self.roots):
            if request_budget is not None and spent() >= request_budget:
                return self._result(frontier_exhausted=False)
            if self.current_root is None:
                if not self._open_root(self.roots[self.root_index]):
                    self.root_index += 1
                continue
            entry = self.frontier.dequeue()
            if entry is None:
                self.store.set_disposition(self.current_root["root_id"], COMPLETE)
                self.current_root = None
                self.root_index += 1
                continue
            try:
                self._expand(entry)
            except frontier_module.WorkingStorageExhausted:
                # The entry is released rather than consumed. It was handed out
                # and not finished, so a later segment with a wider envelope
                # must find it waiting -- otherwise the subtree beneath it is
                # lost and the loss is invisible.
                self.frontier.release(entry)
                self.store.set_disposition(self.current_root["root_id"], STORAGE)
                return self._result(frontier_exhausted=False)
            self.frontier.complete(entry)
        return self._result(frontier_exhausted=True)

    def resume(self, checkpoint: Any) -> None:
        """Restore the root a checkpoint was taken inside, re-attesting identity.

        Without this the root context -- which root, which canonical address,
        which numeric id -- exists only in memory, so every segment re-opens the
        root it was already inside. That wastes the attestation requests, and at
        a small segment budget it consumes the whole budget and the traversal
        never advances. The equivalence controls found it at a budget of one.

        Identity is re-attested rather than trusted across the boundary: a
        window can be an hour wide and a repository can move inside it. If the
        address now serves a different numeric id the root is refused, not
        continued, because continuing would append a second repository's files
        to the first one's candidate set.
        """
        self.root_index = checkpoint.root_index
        if checkpoint.current_root_id is None:
            self.current_root = None
            return
        root = next(
            (r for r in self.roots if r["root_id"] == checkpoint.current_root_id), None
        )
        if root is None:
            raise TraversalRefused(
                f"the checkpoint was taken inside root {checkpoint.current_root_id!r}, "
                "which is not on this roster. Resuming would traverse a repository "
                "this study did not select."
            )
        try:
            resolution = self.transport.resolve_canonical_address(
                root["address"], root["host_uuid"]
            )
        except Exception as error:
            raise TraversalRefused(
                f"identity could not be re-attested on resume, so the traversal is "
                f"not resumed: {error}"
            ) from error
        if resolution["observed_repository_id"] != checkpoint.current_repository_numeric_id:
            raise TraversalRefused(
                f"the checkpoint was taken against repository "
                f"{checkpoint.current_repository_numeric_id} and the address now serves "
                f"{resolution['observed_repository_id']}. The traversal is not resumed."
            )
        self.current_root = root
        self.current_numeric_id = resolution["observed_repository_id"]
        self.current_address = resolution["canonical_address"]

    def _open_root(self, root: dict[str, str]) -> bool:
        """Attest identity, then seed the frontier with the root tree."""
        try:
            resolution = self.transport.resolve_canonical_address(
                root["address"], root["host_uuid"]
            )
        except Exception:  # any refusal at all means the root is not measured
            self.store.set_disposition(root["root_id"], IDENTITY_REFUSED)
            return False
        self.current_root = root
        self.current_numeric_id = resolution["observed_repository_id"]
        self.current_address = resolution["canonical_address"]
        self.store.set_disposition(
            root["root_id"],
            RATE_WINDOW,
            repository_numeric_id=self.current_numeric_id,
            canonical_address=self.current_address,
        )
        tree_sha = self._root_tree_sha(resolution)
        if tree_sha is None:
            self.store.set_disposition(root["root_id"], IDENTITY_REFUSED)
            self.current_root = None
            return False
        self.frontier.enqueue(
            root_id=root["root_id"],
            path="",
            tree_sha=tree_sha,
            depth=0,
            parent_path=None,
        )
        return True

    def _root_tree_sha(self, resolution: dict[str, Any]) -> str | None:
        """The tree the default branch's head points at.

        A separate request on purpose. Folding it into identity resolution would
        make one method answer two different questions -- is this the repository
        the roster chose, and where does its content begin -- and a failure of
        either would then be indistinguishable in the disposition.
        """
        branch = resolution.get("default_branch")
        if not isinstance(branch, str) or not branch:
            return None
        record = self.transport.get(
            f"https://api.github.com/repos/{resolution['canonical_address']}"
            f"/commits/{branch}"
        )
        body = record.body if isinstance(record.body, dict) else {}
        sha = ((body.get("commit") or {}).get("tree") or {}).get("sha")
        return sha if isinstance(sha, str) and sha else None

    def _expand(self, entry: frontier_module.Entry) -> None:
        """One tree object: record its blobs, enqueue its subtrees."""
        assert self.current_root is not None
        record = self.transport.get(
            f"https://api.github.com/repos/{self.current_address}"
            f"/git/trees/{entry.tree_sha}"
        )
        body = record.body if isinstance(record.body, dict) else {}
        for item in body.get("tree", []):
            path = f"{entry.path}/{item['path']}" if entry.path else item["path"]
            if item.get("type") == "tree":
                self.frontier.enqueue(
                    root_id=entry.root_id,
                    path=path,
                    tree_sha=item["sha"],
                    depth=entry.depth + 1,
                    parent_path=entry.path or None,
                )
            elif item.get("type") == "blob" and path.endswith(self.extensions):
                self.store.record_candidate(
                    root_id=entry.root_id,
                    repository_numeric_id=self.current_numeric_id,
                    path=path,
                    blob_sha=item["sha"],
                )

    # -- reporting --------------------------------------------------------

    def _result(self, *, frontier_exhausted: bool) -> Result:
        dispositions = self.store.dispositions()
        return Result(
            candidates=self.store.candidates(),
            dispositions=dispositions,
            visited=self.store.visited_rows(),
            frontier_exhausted=frontier_exhausted,
            roots_completed=[r for r, s in dispositions.items() if s == COMPLETE],
            transport_totals=self.transport.totals(),
        )

    def checkpoint(self, segment_index: int, previous_digest: str) -> Any:
        """Freeze exactly what the next window needs to continue this traversal."""
        totals = self.transport.totals()
        result = self._result(frontier_exhausted=False)
        return checkpoint_module.Checkpoint(
            study_id=self.study_id,
            segment_index=segment_index,
            roster_digest=self.roster_digest,
            root_index=self.root_index,
            current_root_id=self.current_root["root_id"] if self.current_root else None,
            current_canonical_address=self.current_address,
            current_repository_numeric_id=self.current_numeric_id,
            frontier_digest=checkpoint_module.frontier_digest(
                list(self.frontier.pending())
            ),
            visited_digest=checkpoint_module.visited_digest(self.store.visited_rows()),
            candidate_digest=checkpoint_module.digest(
                [c.as_dict() for c in result.candidates]
            ),
            completed_roots_digest=checkpoint_module.digest(
                sorted(result.roots_completed)
            ),
            logical_request_count=totals["logical_requests"],
            network_hop_count=totals["network_hops"],
            provider_charged_count=totals["provider_charged"],
            provider_remaining=None,
            provider_reset_epoch=None,
            previous_segment_digest=previous_digest,
            next_action="CONTINUE_ROOT" if self.current_root else "OPEN_NEXT_ROOT",
            disposition=RATE_WINDOW,
        )
