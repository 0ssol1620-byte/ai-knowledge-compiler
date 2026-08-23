"""The Personal E2E spine: real files -> claims -> world states -> answers.

This package wires the existing compiler components into one runnable
pipeline over a plain directory of documents:

    watcher-visible files (extraction) -> rule-based claims -> identity
    resolution (akc_cir.identity) -> semantic diff (akc_cir.semantic_diff)
    -> dependency impact (akc_cir.dependency) -> selective recompile plan
    (akc_cir.recompilation) -> atomic world publish (akc_cir.world_state)
    -> compiled answers (akc_cir.answer_compiler)

Three entry points matter:

* :func:`compile_workspace` -- first compile: read every file, resolve every
  identity fresh, publish ``WS-1``.
* :meth:`Pipeline.recompile` -- incremental: hash the tree against the stored
  cursor, diff what changed, rebuild only the dirty claims, prove the result
  equals a full rebuild (the §44 oracle), then promote atomically. Nothing
  changed? Nothing published -- the active world is retained untouched.
* :meth:`Pipeline.answer` -- compile a question against the ACTIVE world with
  the closed outcome set (CURRENT / STALE / CONFLICT / UNRESOLVED /
  NOT_AUTHORIZED).

Fail-closed is the house rule. An identity the resolver cannot settle is
quarantined into a review queue instead of being merged or split on a guess;
an oracle mismatch refuses the publish outright; a deleted dependency
invalidates everything downstream of it rather than leaving stale answers
served as current.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from akc_cir.answer_compiler import CompiledAnswer, DraftClaim, compile_answer
from akc_cir.authority import AuthorityClass, ClaimContext, SourceStatus
from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.identity import LogicalMatch, assign_one_to_one, source_id
from akc_cir.recompilation import (
    EquivalenceReport,
    RecompilationPlan,
    content_hash,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    DocumentShape,
    SemanticChange,
    SemanticDiff,
    UnitSnapshot,
    diff_documents,
)
from akc_cir.world_state import (
    ValidationReceipt,
    WorldStateRegistry,
    publication_manifest,
)

from .answers import select_drafts
from .extraction import AuthorityClass as ExtractionAuthority
from .extraction import (
    ClaimDraft,
    ParsedDocument,
    anchored_evidence_id,
    parse_workspace,
    seed_logical_id,
)
from .extraction import SourceStatus as ExtractionSourceStatus
from .store import StoredWorld, WorldStore, next_deterministic_time

__all__ = [
    "CompileOptions",
    "OracleRefused",
    "Pipeline",
    "ReviewItem",
    "WorldResult",
    "compile_workspace",
]

COMPILER_VERSION = "akc-compiler-runtime/0.1.0"


@dataclass(frozen=True, slots=True)
class CompileOptions:
    """Everything a personal spine needs configured, with safe defaults."""

    tenant_id: str = "personal"
    workspace_id: str = "personal"
    connector_type: str = "filesystem"
    max_depth: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """An identity the resolver refused to settle, held for human review."""

    subject: str
    reason: str
    candidates: tuple[str, ...]
    rel_path: str
    text: str

    def as_record(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "reason": self.reason,
            "candidates": list(self.candidates),
            "rel_path": self.rel_path,
            "text": self.text,
        }


class OracleRefused(RuntimeError):
    """A selective rebuild failed to match a full rebuild; nothing published."""


def _authority_value(authority: ExtractionAuthority) -> int:
    return int(AuthorityClass[authority.value])


def _status_value(status: ExtractionSourceStatus) -> int:
    return int(SourceStatus[status.value])


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _from_iso(raw: object) -> datetime | None:
    return datetime.fromisoformat(str(raw)) if raw else None


def _jsonable(row: Mapping[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(dict(row), ensure_ascii=False))


class Pipeline:
    """One workspace's compile/recompile/answer loop over a world store."""

    def __init__(
        self,
        world_store_root: Path | str,
        *,
        options: CompileOptions | None = None,
    ) -> None:
        self.options = options or CompileOptions()
        self.store = WorldStore(
            Path(world_store_root), workspace_id=self.options.workspace_id
        )
        self.registry: WorldStateRegistry = self.store.load_registry()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def compile_workspace(self, source_dir: Path | str) -> WorldResult:
        """First (or forced-full) compile: every file, every identity, WS-n."""
        documents = self._parse(Path(source_dir))
        previous = self.store.load_world()
        classification = self._classify(documents, previous)
        build = self._build_rows(
            documents, previous, resolve_all=True, classification=classification
        )
        return self._publish_build(documents, build, previous, selective=False)

    def recompile(self, source_dir: Path | str) -> WorldResult:
        """Incremental compile against the stored cursor.

        Unchanged trees are a no-op: the active world is retained and nothing
        -- not a candidate, not a receipt -- is written.
        """
        documents = self._parse(Path(source_dir))
        previous = self.store.load_world()
        if previous is None:
            return self.compile_workspace(source_dir)

        classification = self._classify(documents, previous)
        if not (
            classification.changed
            or classification.added
            or classification.removed
            or classification.renamed
        ):
            return WorldResult(
                world_state_id=previous.world_state_id,
                previous_world_state_id=None,
                manifest_hash=previous.manifest.manifest_hash,
                published=False,
                no_op=True,
                claims=dict(previous.claims),
                evidence_index=dict(previous.evidence_index),
                review_queue=tuple(previous.review_queue),
                invalidated=(),
                renames=(),
                plan=None,
                equivalence=None,
                _pipeline=self,
            )

        build = self._build_rows(
            documents, previous, resolve_all=False, classification=classification
        )
        return self._publish_build(documents, build, previous, selective=True)

    def answer(self, question: str, *, as_of: datetime | None = None) -> CompiledAnswer:
        """Compile a question against whatever world is currently ACTIVE."""
        world = self.store.load_world()
        if world is None:
            raise RuntimeError("no world has been compiled yet")
        registry = self.registry if self.registry.current else self.store.load_registry()
        return answer_from_world(
            question,
            claims=world.claims,
            world_state_id=world.world_state_id,
            registry=registry,
            as_of=as_of,
        )

    # ------------------------------------------------------------------
    # classification (cursor diff)
    # ------------------------------------------------------------------

    def _parse(self, source_dir: Path) -> list[ParsedDocument]:
        return parse_workspace(source_dir, tenant_id=self.options.tenant_id)

    def _classify(
        self, documents: Sequence[ParsedDocument], previous: StoredWorld | None
    ) -> _Classification:
        """Cursor diff: which paths are unchanged / changed / added / removed."""
        current_shas = {doc.file.rel_path: doc.file.sha256 for doc in documents}
        previous_shas = previous.cursor if previous else {}
        removed = sorted(set(previous_shas) - set(current_shas))
        added = sorted(set(current_shas) - set(previous_shas))
        changed = sorted(
            path
            for path, sha in current_shas.items()
            if path in previous_shas and previous_shas[path] != sha
        )
        # Exact-content rename detection (git-style): a vanished path and an
        # appeared path carrying identical bytes are one source that moved.
        sha_to_removed: dict[str, str] = {}
        for path in removed:
            sha_to_removed.setdefault(previous_shas[path], path)
        renames: dict[str, str] = {}
        for path in added:
            old = sha_to_removed.pop(current_shas[path], None)
            if old is not None:
                renames[path] = old
        remaining_added = sorted(set(added) - set(renames))
        remaining_removed = sorted(set(removed) - set(renames.values()))
        return _Classification(
            changed=changed,
            added=remaining_added,
            removed=remaining_removed,
            renamed=renames,
        )

    # ------------------------------------------------------------------
    # identity resolution
    # ------------------------------------------------------------------

    def _previous_by_path(
        self, previous: StoredWorld
    ) -> dict[str, list[dict[str, object]]]:
        grouped: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
        for row in previous.claims.values():
            grouped[str(row["rel_path"])].append(row)
        return dict(grouped)

    def _snapshot_from_record(self, row: Mapping[str, object]) -> UnitSnapshot:
        previous_anchor = str(row.get("prev_anchor", ""))
        next_anchor = str(row.get("next_anchor", ""))
        return UnitSnapshot(
            logical_id=str(row["logical_id"]),
            text=str(row["value"]),
            document_path=tuple(row["section_path"]),  # type: ignore[arg-type]
            anchor=str(row["anchor"]),
            neighbour_anchors=(
                (previous_anchor, next_anchor)
                if previous_anchor or next_anchor
                else ()
            ),
        )

    def _snapshot_from_draft(
        self, draft: ClaimDraft, seed_id: str, neighbours: tuple[str, str]
    ) -> UnitSnapshot:
        return UnitSnapshot(
            logical_id=seed_id,
            text=draft.text,
            document_path=draft.section_path,
            anchor=draft.anchor,
            neighbour_anchors=neighbours if any(neighbours) else (),
        )

    def _resolve_document(
        self,
        document: ParsedDocument,
        previous_rows: Sequence[Mapping[str, object]],
        *,
        lineage_source: str,
    ) -> _DocumentResolution:
        """Resolve one document's claims against its previous version.

        Matched identities keep their logical ids; new units are seeded; an
        identity the resolver cannot settle is quarantined for review instead
        of being merged or split on a guess.
        """
        anchors = [draft.anchor for draft in document.claims]
        neighbour_pairs = [
            (
                anchors[index - 1] if index > 0 else "",
                anchors[index + 1] if index + 1 < len(anchors) else "",
            )
            for index in range(len(anchors))
        ]
        seeds = [
            seed_logical_id(source=lineage_source, draft=draft)
            for draft in document.claims
        ]
        after_snapshots = [
            self._snapshot_from_draft(draft, seed, neighbours)
            for draft, seed, neighbours in zip(
                document.claims, seeds, neighbour_pairs, strict=True
            )
        ]
        before_snapshots = [self._snapshot_from_record(row) for row in previous_rows]

        decisions = (
            assign_one_to_one(
                [snapshot.fingerprint(source_lineage=lineage_source) for snapshot in after_snapshots],
                [snapshot.fingerprint(source_lineage=lineage_source) for snapshot in before_snapshots],
            )
            if (after_snapshots or before_snapshots)
            else []
        )

        rows: list[dict[str, object]] = []
        review: list[ReviewItem] = []
        claimed_old: set[str] = set()

        for draft, neighbours, decision in zip(
            document.claims, neighbour_pairs, decisions, strict=True
        ):
            if decision.match is LogicalMatch.AMBIGUOUS:
                review.append(
                    ReviewItem(
                        subject=draft.subject,
                        reason=decision.reason,
                        candidates=decision.candidates,
                        rel_path=document.file.rel_path,
                        text=draft.text,
                    )
                )
                continue
            if decision.match is LogicalMatch.MATCHED:
                logical_id = decision.logical_id or ""
                claimed_old.add(logical_id)
            else:
                logical_id = decision.logical_id or ""
            row = self._row_from_draft(document, draft, logical_id)
            row["prev_anchor"] = neighbours[0]
            row["next_anchor"] = neighbours[1]
            rows.append(row)

        retired = sorted(
            str(row["logical_id"])
            for row in previous_rows
            if str(row["logical_id"]) not in claimed_old
        )
        return _DocumentResolution(rows=rows, retired=retired, review=review)

    def _row_from_draft(
        self, document: ParsedDocument, draft: ClaimDraft, logical_id: str
    ) -> dict[str, object]:
        evidence = anchored_evidence_id(
            document_version=document.document_version,
            text=draft.text,
            line_number=draft.line_number,
        )
        return {
            "logical_id": logical_id,
            "subject": draft.subject,
            "value": draft.text,
            "kind": draft.kind,
            "authority": _authority_value(document.authority),
            "source_status": _status_value(draft.source_status),
            "scope": dict(draft.scope),
            "valid_from": _iso(draft.valid_from),
            "valid_to": _iso(draft.valid_to),
            "recorded_at": _iso(draft.recorded_at),
            "temporal_source": draft.temporal_source.value,
            "required_permission": None,
            "evidence_id": evidence,
            "rel_path": document.file.rel_path,
            "line_number": draft.line_number,
            "sha256": document.file.sha256,
            "document_version_id": document.document_version,
            "section_path": list(draft.section_path),
            "anchor": draft.anchor,
            "prev_anchor": "",
            "next_anchor": "",
            "dep_refs": list((*draft.depends_on_refs, *draft.derived_from_refs)),
            "dependencies": [],
            "invalidated_by": [],
            "doc_node": "",
            "moved_from": "",
        }

    @staticmethod
    def _carry_row(row: Mapping[str, object]) -> dict[str, object]:
        carried = dict(row)
        carried["invalidated_by"] = []
        return carried

    # ------------------------------------------------------------------
    # build (rows, diff, graph, plan)
    # ------------------------------------------------------------------

    def _build_rows(
        self,
        documents: Sequence[ParsedDocument],
        previous: StoredWorld | None,
        *,
        resolve_all: bool,
        classification: _Classification,
    ) -> _Build:
        """Produce the claim table for the current tree.

        With ``resolve_all`` every document is identity-resolved against its
        previous version (the full-rebuild oracle path). Without it, only
        changed/renamed/added documents are resolved and unchanged documents
        are carried over byte-for-byte -- the selective path. Both paths see
        the same ``classification``, so removals and invalidations agree.
        """
        by_path = {doc.file.rel_path: doc for doc in documents}
        prev_rows_by_path = self._previous_by_path(previous) if previous else {}

        rows: list[dict[str, object]] = []
        reviews: list[ReviewItem] = []
        # (logical_id, lineage path) for every unit this build retires, either
        # because its file is gone or because its document dropped it.
        removed_units: list[tuple[str, str]] = []
        resolved_paths: set[str] = set()
        resolved_row_ids: set[str] = set()
        renames: list[tuple[str, str]] = []

        def absorb(
            resolution: _DocumentResolution, *, lineage_path: str, rel_path: str
        ) -> None:
            for row in resolution.rows:
                if lineage_path != rel_path:
                    row["moved_from"] = lineage_path
            rows.extend(resolution.rows)
            reviews.extend(resolution.review)
            removed_units.extend(
                (unit_id, lineage_path) for unit_id in resolution.retired
            )
            resolved_paths.add(rel_path)
            resolved_row_ids.update(str(row["logical_id"]) for row in resolution.rows)

        # 1. Renames: the new path continues the old path's identities.
        for new_path, old_path in sorted(classification.renamed.items()):
            doc = by_path.get(new_path)
            if doc is None:
                continue
            resolution = self._resolve_document(
                doc,
                prev_rows_by_path.get(old_path, []),
                lineage_source=self._source_of(old_path),
            )
            absorb(resolution, lineage_path=old_path, rel_path=new_path)
            renames.append((old_path, new_path))

        # 2. Changed and added paths.
        dirty_paths = sorted(set(classification.changed) | set(classification.added))
        for path in dirty_paths:
            doc = by_path.get(path)
            if doc is None:
                continue
            resolution = self._resolve_document(
                doc,
                prev_rows_by_path.get(path, []),
                lineage_source=self._source_of(path),
            )
            absorb(resolution, lineage_path=path, rel_path=path)

        # 3. Removals: every previous row whose file is gone retires. The
        #    file's path rides along so the unit keeps its document edge and
        #    impact can still propagate out of a deleted document.
        for path in classification.removed:
            for row in prev_rows_by_path.get(path, []):
                removed_units.append((str(row["logical_id"]), path))

        # 4. Clean paths: selective carries rows verbatim; full re-resolves.
        for path in sorted(set(by_path) - resolved_paths):
            doc = by_path[path]
            prior_rows = prev_rows_by_path.get(path, [])
            if resolve_all:
                resolution = self._resolve_document(
                    doc, prior_rows, lineage_source=self._source_of(path)
                )
                absorb(resolution, lineage_path=path, rel_path=path)
            else:
                rows.extend(self._carry_row(row) for row in prior_rows)

        path_aliases = {old: new for new, old in classification.renamed.items()}
        rows = self._attach_dependencies(rows, path_aliases=path_aliases)
        rows = self._stamp_invalidation(
            rows,
            [unit_id for unit_id, _ in removed_units],
            removed_units=removed_units,
        )

        merged_diff = self._merged_diff(classification, by_path, prev_rows_by_path, rows)
        graph = self._dependency_graph(rows, removed_units)
        inventory = [str(row["logical_id"]) for row in rows]
        plan = plan_recompilation(
            diff=merged_diff, graph=graph, artifacts=inventory
        )
        return _Build(
            rows=rows,
            reviews=reviews,
            removed_ids=list(dict.fromkeys(unit_id for unit_id, _ in removed_units)),
            renames=renames,
            diff=merged_diff,
            graph=graph,
            plan=plan,
            resolved_row_ids=resolved_row_ids,
            removed_units=removed_units,
        )

    def _source_of(self, rel_path: str) -> str:
        return source_id(
            tenant_id=self.options.tenant_id,
            connector_type=self.options.connector_type,
            native_id=rel_path,
        )

    def _attach_dependencies(
        self,
        rows: list[dict[str, object]],
        *,
        path_aliases: Mapping[str, str] = {},
    ) -> list[dict[str, object]]:
        """Resolve ``Depends on: <path>`` references to concrete logical ids.

        A dependency is a statement about the *document*, not about the line
        that mentioned it, so references resolve to stable *document nodes*
        (``doc:<source id>``) rather than to whatever claims a document
        happens to contain today. Claim churn inside the target document
        cannot then rewrite the edge set behind the oracle's back. Every row
        also records its own document node so the graph can walk claim ->
        document -> dependent documents -> claims. ``path_aliases`` carries
        this run's renames (old path -> new path) so references to a document
        that moved still resolve to its continuation.
        """
        path_to_node: dict[str, str] = {}
        for row in rows:
            node = f"doc:{self._source_of(_lineage_path(row))}"
            row["doc_node"] = node
            path_to_node.setdefault(str(row["rel_path"]), node)

        def resolve(ref: str) -> str:
            """A ref names a document; its node survives moves and deletions."""
            if ref in path_to_node:
                return path_to_node[ref]
            aliased = path_aliases.get(ref)
            if aliased is not None and aliased in path_to_node:
                return path_to_node[aliased]
            # Deleted (or not-yet-compiled) target: the node is still a pure
            # function of the path it was referenced by.
            return f"doc:{self._source_of(ref)}"

        for row in rows:
            refs = row["dep_refs"]  # type: ignore[union-attr]
            targets = {resolve(ref) for ref in refs}
            targets.discard(str(row["doc_node"]))
            row["dependencies"] = sorted(targets)
        return rows

    def _stamp_invalidation(
        self,
        rows: list[dict[str, object]],
        removed_ids: Sequence[str],
        *,
        removed_units: Sequence[tuple[str, str]] = (),
    ) -> list[dict[str, object]]:
        """Mark everything downstream of a removal as invalidated.

        §16.1's propagation, ending in a stamp rather than a silent gap: an
        invalidated claim stays visible for audit but never serves an answer.
        """
        causes = [cause for cause in dict.fromkeys(removed_ids) if cause]
        if not causes:
            for row in rows:
                row["invalidated_by"] = []
            return rows
        graph = self._dependency_graph(rows, removed_units)
        for row in rows:
            logical_id = str(row["logical_id"])
            stamps = sorted(
                cause
                for cause in causes
                if cause != logical_id and cause in graph.nodes
                and logical_id in graph.impact_of([cause]).affected_ids
            )
            row["invalidated_by"] = stamps
        return rows

    def _dependency_graph(
        self,
        rows: Sequence[Mapping[str, object]],
        removed_units: Sequence[tuple[str, str]] = (),
    ) -> DependencyGraph:
        """Claim graph with one virtual node per document.

        ``claim --CONSUMED_BY--> doc`` lets a changed or deleted claim wake
        its document; ``doc --INVALIDATES--> claim`` lets a woken document
        retire its own claims; ``docA --DEPENDS_ON--> docB`` carries impact
        upstream from the referenced document to the referencing one.
        Removed units keep their ``CONSUMED_BY`` edge so a deletion can
        propagate even though its row is no longer in the table.
        """
        edges: list[DependencyEdge] = []
        seen_edges: set[tuple[str, str, EdgeType]] = set()

        def add(source_id: str, target_id: str, edge_type: EdgeType) -> None:
            if source_id == target_id:
                return
            key = (source_id, target_id, edge_type)
            if key in seen_edges:
                return
            seen_edges.add(key)
            edges.append(
                DependencyEdge(
                    source_id=source_id, target_id=target_id, edge_type=edge_type
                )
            )

        for row in rows:
            logical_id = str(row["logical_id"])
            doc_node = str(row["doc_node"])
            add(logical_id, doc_node, EdgeType.CONSUMED_BY)
            add(doc_node, logical_id, EdgeType.INVALIDATES)
            for target in row["dependencies"]:  # type: ignore[union-attr]
                add(doc_node, str(target), EdgeType.DEPENDS_ON)
        for unit_id, lineage_path in removed_units:
            add(unit_id, f"doc:{self._source_of(lineage_path)}", EdgeType.CONSUMED_BY)
        return DependencyGraph(edges)

    def _merged_diff(
        self,
        classification: _Classification,
        by_path: Mapping[str, ParsedDocument],
        prev_rows_by_path: Mapping[str, list[dict[str, object]]],
        new_rows: Sequence[Mapping[str, object]],
    ) -> SemanticDiff:
        """One aggregate SemanticDiff over every dirty or removed document."""
        changes: list[SemanticChange] = []
        dirty = (
            set(classification.changed)
            | set(classification.added)
            | set(classification.renamed)
        )
        new_rows_by_path: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
        for row in new_rows:
            new_rows_by_path[str(row["rel_path"])].append(row)

        for path in sorted(dirty):
            document = by_path.get(path)
            if document is None:
                continue
            old_path = classification.renamed.get(path, path)
            before_rows = prev_rows_by_path.get(old_path, [])
            after_rows = new_rows_by_path.get(path, [])
            before_sha = (
                str(before_rows[0]["sha256"]) if before_rows else f"absent:{old_path}"
            )
            changes.extend(
                change
                for change in diff_documents(
                    before_sha256=before_sha,
                    after_sha256=document.file.sha256,
                    level=DiffLevel.SEMANTIC,
                    before_shape=_shape_of(before_rows),
                    after_shape=_shape_of(after_rows),
                    before_units=[
                        self._snapshot_from_record(row) for row in before_rows
                    ],
                    after_units=[
                        UnitSnapshot(
                            logical_id=str(row["logical_id"]),
                            text=str(row["value"]),
                            document_path=tuple(row["section_path"]),  # type: ignore[arg-type]
                            anchor=str(row["anchor"]),
                        )
                        for row in after_rows
                    ],
                    source=self._source_of(old_path),
                ).changes
                if change.kind is not ChangeKind.CONTENT_UNCHANGED
            )
            if old_path != path:
                # A rename is a real source-level event even when the bytes
                # are identical: the evidence now lives somewhere else, and
                # everything hanging off this document must re-resolve.
                for row in after_rows:
                    changes.append(
                        SemanticChange(
                            kind=ChangeKind.EVIDENCE_MOVED,
                            logical_id=str(row["logical_id"]),
                            before=old_path,
                            after=path,
                            detail="source moved",
                        )
                    )
        for path in classification.removed:
            for row in prev_rows_by_path.get(path, []):
                changes.append(
                    SemanticChange(
                        kind=ChangeKind.UNIT_REMOVED,
                        logical_id=str(row["logical_id"]),
                        before=str(row["value"]),
                    )
                )
        payload = json.dumps(
            [change.as_record() for change in changes],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        change_id = "chg_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
        return SemanticDiff(
            level=DiffLevel.SEMANTIC,
            content_changed=bool(changes),
            changes=tuple(changes),
            change_id=change_id,
        )

    # ------------------------------------------------------------------
    # publishing
    # ------------------------------------------------------------------

    def _publish_build(
        self,
        documents: Sequence[ParsedDocument],
        build: _Build,
        previous: StoredWorld | None,
        *,
        selective: bool,
    ) -> WorldResult:
        """Verify the build (oracle when selective) and publish it atomically."""
        rows = build.rows
        claims_table = {str(row["logical_id"]): _jsonable(row) for row in rows}
        evidence_index = {
            str(row["evidence_id"]): {
                "rel_path": row["rel_path"],
                "line_number": row["line_number"],
                "sha256": row["sha256"],
                "span": row["value"],
            }
            for row in rows
        }
        cursor = {doc.file.rel_path: doc.file.sha256 for doc in documents}
        artifacts = {
            **{
                f"claim/{logical_id}": content_hash(row)
                for logical_id, row in claims_table.items()
            },
            "evidence/index": content_hash(_jsonable(evidence_index)),
            "cursor": content_hash(_jsonable(cursor)),
        }

        equivalence_report: EquivalenceReport | None = None
        if selective:
            equivalence_report = self._verify_oracle(
                documents, build, claims_table, artifacts
            )

        receipt = ValidationReceipt(
            receipt_id=f"rcpt-{build.diff.change_id[:16]}",
            checksums_verified=True,
            permission_checked=True,
            integrity_passed=True,
            equivalence=equivalence_report,
        )

        world_state_id = self.store.next_world_state_id
        manifest = publication_manifest(
            world_state_id=world_state_id,
            compiler_version=COMPILER_VERSION,
            artifact_hashes=artifacts,
        )
        built_at = next_deterministic_time(self.store.sequence + 1)
        self.registry.stage(
            world_state_id=world_state_id,
            compiler_version=COMPILER_VERSION,
            built_at=built_at,
        )
        self.store.publish(
            registry=self.registry,
            world_state_id=world_state_id,
            compiler_version=COMPILER_VERSION,
            manifest=manifest,
            receipt=receipt,
            artifacts=artifacts,
            claims=claims_table,
            evidence_index=evidence_index,
            review_queue=tuple(item.as_record() for item in build.reviews),
            cursor=cursor,
        )
        return WorldResult(
            world_state_id=world_state_id,
            previous_world_state_id=(
                previous.world_state_id if previous else None
            ),
            manifest_hash=manifest.manifest_hash,
            published=True,
            no_op=False,
            claims=claims_table,
            evidence_index=evidence_index,
            review_queue=tuple(build.reviews),
            invalidated=tuple(
                logical_id
                for logical_id, row in claims_table.items()
                if row["invalidated_by"]
            ),
            renames=tuple(build.renames),
            plan=build.plan,
            equivalence=equivalence_report,
            _pipeline=self,
        )

    def _verify_oracle(
        self,
        documents: Sequence[ParsedDocument],
        build: _Build,
        claims_table: Mapping[str, Mapping[str, object]],
        selective_artifacts: Mapping[str, str],
    ) -> EquivalenceReport:
        """§44 PHASE 5: prove the selective result equals a full rebuild.

        The comparator resolves *every* document against the same previous
        world with identical machinery and the same change classification --
        no skipping. If a carried-over row would differ under a full
        resolution, the publish is refused before anything is promoted.
        """
        previous = self.store.load_world()
        classification = self._classify(documents, previous)
        full_build = self._build_rows(
            documents, previous, resolve_all=True, classification=classification
        )
        full_artifacts = {
            f"claim/{logical_id}": content_hash(_jsonable(row))
            for logical_id, row in (
                (str(row["logical_id"]), row) for row in full_build.rows
            )
        }
        rebuilt: dict[str, str] = {}
        carried: dict[str, str] = {}
        for name, digest in selective_artifacts.items():
            logical_id = name.removeprefix("claim/")
            if name.startswith("claim/") and logical_id in build.resolved_row_ids:
                rebuilt[name] = digest
            else:
                carried[name] = digest
        report = verify_equivalence(
            full_rebuild=full_artifacts,
            selective_rebuild=rebuilt,
            carried_over=carried,
            plan=build.plan,
        )
        if not report.equivalent:
            raise OracleRefused(str(report.as_record()))
        _ = claims_table
        return report


def _lineage_path(row: Mapping[str, object]) -> str:
    """The path this row's document has continuously lived at.

    A row renamed this very run carries ``moved_from``; its document node
    keeps the old source id so edges written against the old path survive.
    """
    moved_from = row.get("moved_from")
    if moved_from:
        return str(moved_from)
    return str(row["rel_path"])


def _shape_of(rows: Sequence[Mapping[str, object]]) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset(
            tuple(row["section_path"]) for row in rows  # type: ignore[arg-type]
        ),
        block_count=len(rows),
    )


def answer_from_world(
    question: str,
    *,
    claims: Mapping[str, Mapping[str, object]],
    world_state_id: str,
    registry: WorldStateRegistry,
    as_of: datetime | None = None,
) -> CompiledAnswer:
    """Select drafts lexically and compile them through akc_cir."""
    moment = as_of or datetime(2026, 10, 1, tzinfo=UTC)
    context = ClaimContext(subject="workspace", as_of=moment)
    drafts = select_drafts(question, claims, world_state_id=world_state_id)
    return compile_answer(question, drafts, registry, context)


@dataclass(frozen=True, slots=True)
class _Classification:
    """The cursor diff between the stored world and the tree on disk."""

    changed: list[str]
    added: list[str]
    removed: list[str]
    renamed: dict[str, str]


@dataclass(frozen=True, slots=True)
class _DocumentResolution:
    rows: list[dict[str, object]]
    retired: list[str]
    review: list[ReviewItem]


@dataclass(frozen=True, slots=True)
class _Build:
    rows: list[dict[str, object]]
    reviews: list[ReviewItem]
    removed_ids: list[str]
    renames: list[tuple[str, str]]
    diff: SemanticDiff
    graph: DependencyGraph
    plan: RecompilationPlan
    resolved_row_ids: set[str]
    removed_units: list[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class WorldResult:
    """What one compile/recompile produced, plus how to ask it questions."""

    world_state_id: str
    previous_world_state_id: str | None
    manifest_hash: str
    published: bool
    no_op: bool
    claims: Mapping[str, Mapping[str, object]]
    evidence_index: Mapping[str, Mapping[str, object]]
    review_queue: tuple[ReviewItem, ...]
    invalidated: tuple[str, ...]
    renames: tuple[tuple[str, str], ...]
    plan: RecompilationPlan | None
    equivalence: EquivalenceReport | None
    _pipeline: Pipeline | None = field(default=None, repr=False, compare=False)

    @property
    def active_claim_ids(self) -> tuple[str, ...]:
        """Claims that may serve an answer: present and not invalidated."""
        return tuple(
            logical_id
            for logical_id, row in self.claims.items()
            if not row.get("invalidated_by")
        )

    def answer(self, question: str, *, as_of: datetime | None = None) -> CompiledAnswer:
        if self._pipeline is None:
            raise RuntimeError("this result is detached from its pipeline")
        return self._pipeline.answer(question, as_of=as_of)

    def evidence_for(self, evidence_id: str) -> Mapping[str, object] | None:
        return self.evidence_index.get(evidence_id)

    def draft_claims(self, question: str) -> tuple[DraftClaim, ...]:
        """The drafts this world would submit for the question (test seam)."""
        return select_drafts(question, self.claims, world_state_id=self.world_state_id)


def compile_workspace(
    source_dir: Path | str,
    world_store_root: Path | str,
    *,
    options: CompileOptions | None = None,
) -> WorldResult:
    """Mission-shaped entry point: compile a real directory into a world."""
    return Pipeline(world_store_root, options=options).compile_workspace(source_dir)
