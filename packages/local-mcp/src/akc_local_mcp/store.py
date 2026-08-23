"""Reading published world states from local JSON files.

This store is the entire data plane of `akc-local-mcp`: an offline desktop
scenario where no `services/api` process is running, and the only thing that
exists on disk is whatever the compiler published into a world-state
directory. Layout:

    <world-state-dir>/
      <world_id>/manifest.json   the published manifest (the citable pointer)
      <world_id>/state.json      the compiled truth: topics, claims, evidence

Two properties carry over from the publishing side (`akc_cir.world_state`,
masterplan invariant 13: *새 world state는 원자적으로 publish한다*):

- **The manifest is a pointer, not a promise.** Every answer this package
  produces names the manifest hash it was computed against, so the answer is
  checkable: the files behind it either hash to that manifest or they do not.
- **Reads go to disk on every call.** Nothing is cached across requests. A
  republished world is visible on the next question without restarting the
  server, and a deleted one stops answering.

Everything here is read-only. There is no mutating method on `LocalWorldStore`,
and none may be added: see `akc_local_mcp.server` for the forbidden-tool list.
Malformed input fails closed — a file that does not parse, or declares a schema
version this code does not know, raises instead of being partially interpreted.

Beyond topics and claims, a state file may carry three optional sections that
the wider read surface reads when present and reports as absent otherwise
(never guessed): `entities`, `changes`, and `dependencies`. The disk convention
stays exactly `<root>/<world_id>/{manifest,state}.json`; world history is simply
every world directory under `<root>`, read through `list_history()` and diffed
through `diff_worlds()`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from akc_cir.dependency import EdgeType

__all__ = [
    "ChangeRecord",
    "ChangeSummary",
    "ClaimDiff",
    "ClaimFieldChange",
    "ClaimRecord",
    "DependencyEdgeRecord",
    "EntityRecord",
    "EvidenceRecord",
    "LocalWorldStore",
    "StoreError",
    "TopicRecord",
    "UnknownWorldError",
    "WorldDiff",
    "WorldDocumentError",
    "WorldManifest",
    "WorldSnapshot",
]

MANIFEST_SCHEMA = "akc.local-world-manifest/1"
STATE_SCHEMA = "akc.local-world-state/1"
MANIFEST_FILENAME = "manifest.json"
STATE_FILENAME = "state.json"


class StoreError(RuntimeError):
    """A world-state file cannot be answered from. Never silently degraded."""


class UnknownWorldError(StoreError):
    """No directory of that name exists under the world-state dir."""


class WorldDocumentError(StoreError):
    """A world file exists but cannot be trusted (unreadable or wrong shape)."""


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One evidence link behind a claim.

    Mirrors the repository invariant that AI-derived factual content requires
    valid source block evidence: `source_block_ids` may not be empty. A claim
    whose evidence cannot satisfy that is refused at parse time, not served
    with the gap papered over.
    """

    source_block_ids: tuple[str, ...]
    document_version_id: str | None = None
    quote: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_block_ids": list(self.source_block_ids),
        }
        if self.document_version_id is not None:
            payload["document_version_id"] = self.document_version_id
        if self.quote is not None:
            payload["quote"] = self.quote
        return payload


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    claim_id: str
    text: str
    status: str
    topic_ids: tuple[str, ...]
    evidence: tuple[EvidenceRecord, ...]
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "claim_id": self.claim_id,
            "text": self.text,
            "status": self.status,
            "topic_ids": list(self.topic_ids),
            "evidence": [item.to_dict() for item in self.evidence],
        }
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        return payload


@dataclass(frozen=True, slots=True)
class TopicRecord:
    topic_id: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    claim_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "title": self.title,
            "summary": self.summary,
            "keywords": list(self.keywords),
            "claim_ids": list(self.claim_ids),
        }


@dataclass(frozen=True, slots=True)
class EntityRecord:
    """One resolved entity as compiled into the world (`entity_id` is stable).

    Optional section: a world without entities simply answers UNRESOLVED for
    entity lookups rather than inventing one from claim text.
    """

    entity_id: str
    name: str
    entity_type: str | None = None
    aliases: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "entity_id": self.entity_id,
            "name": self.name,
            "aliases": list(self.aliases),
            "claim_ids": list(self.claim_ids),
        }
        if self.entity_type is not None:
            payload["type"] = self.entity_type
        return payload


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    """One recorded source change behind the world's current truth."""

    change_id: str
    source_path: str
    kind: str | None = None
    summary: str | None = None
    changed_at: str | None = None
    claim_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "change_id": self.change_id,
            "source_path": self.source_path,
            "claim_ids": list(self.claim_ids),
        }
        if self.kind is not None:
            payload["kind"] = self.kind
        if self.summary is not None:
            payload["summary"] = self.summary
        if self.changed_at is not None:
            payload["changed_at"] = self.changed_at
        return payload


@dataclass(frozen=True, slots=True)
class DependencyEdgeRecord:
    """One declared dependency edge, edge type validated against §15's vocabulary."""

    source_id: str
    target_id: str
    edge_type: EdgeType

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
        }


@dataclass(frozen=True, slots=True)
class WorldManifest:
    """What `manifest.json` recorded, verbatim.

    `status` is kept as written by the publisher (`ACTIVE`, `CANDIDATE`,
    `SUPERSEDED`, ...) — this package never guesses a world into being active.
    """

    world_id: str
    workspace_id: str
    status: str
    compiler_version: str
    built_at: str
    manifest_hash: str
    artifact_hashes: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "world_id": self.world_id,
            "workspace_id": self.workspace_id,
            "status": self.status,
            "compiler_version": self.compiler_version,
            "built_at": self.built_at,
            "manifest_hash": self.manifest_hash,
            "artifact_hashes": dict(sorted(self.artifact_hashes.items())),
        }


@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    """A manifest joined with its compiled state."""

    manifest: WorldManifest
    topics: tuple[TopicRecord, ...]
    claims: tuple[ClaimRecord, ...]
    entities: tuple[EntityRecord, ...] = ()
    changes: tuple[ChangeRecord, ...] = ()
    dependencies: tuple[DependencyEdgeRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ClaimFieldChange:
    """One claim field whose value moved between two worlds."""

    field: str
    before: Any
    after: Any

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "before": self.before, "after": self.after}


@dataclass(frozen=True, slots=True)
class ClaimDiff:
    """One claim's fate between world A and world B (B is the newer side)."""

    claim_id: str
    kind: str  # "added" | "removed" | "changed"
    changes: tuple[ClaimFieldChange, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"claim_id": self.claim_id, "kind": self.kind}
        if self.changes:
            payload["changes"] = [change.to_dict() for change in self.changes]
        return payload


@dataclass(frozen=True, slots=True)
class ChangeSummary:
    """Counts that let a caller see the shape of a diff without walking it."""

    added: int
    removed: int
    changed: int
    unchanged: int

    def to_dict(self) -> dict[str, int]:
        return {
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "unchanged": self.unchanged,
        }


@dataclass(frozen=True, slots=True)
class WorldDiff:
    """The claim-level difference between two worlds: added/removed/changed.

    Value changes are reported field by field (`before` → `after`) so a reviewer
    sees *what* moved, not just that something did.
    """

    world_a: str
    world_b: str
    added: tuple[ClaimDiff, ...]
    removed: tuple[ClaimDiff, ...]
    changed: tuple[ClaimDiff, ...]
    summary: ChangeSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_a": self.world_a,
            "world_b": self.world_b,
            "added_in_b": [entry.to_dict() for entry in self.added],
            "removed_from_a": [entry.to_dict() for entry in self.removed],
            "value_changed": [entry.to_dict() for entry in self.changed],
            "summary": self.summary.to_dict(),
        }


def _read_json(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorldDocumentError(f"{path}: cannot be read ({exc})") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorldDocumentError(f"{path}: invalid JSON ({exc})") from exc


def _require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorldDocumentError(f"{context}: expected a JSON object")
    return value


def _require_schema(document: Mapping[str, Any], expected: str, path: Path) -> None:
    found = document.get("schema")
    if found != expected:
        raise WorldDocumentError(
            f"{path}: schema {found!r} is not supported (expected {expected!r})"
        )


def _require_str(document: Mapping[str, Any], key: str, context: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WorldDocumentError(f"{context}: {key!r} must be a non-empty string")
    return value


def _optional_str(document: Mapping[str, Any], key: str, context: str) -> str | None:
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorldDocumentError(f"{context}: {key!r} must be a string when present")
    return value


def _require_str_tuple(
    document: Mapping[str, Any], key: str, context: str, *, allow_empty: bool = True
) -> tuple[str, ...]:
    value = document.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise WorldDocumentError(f"{context}: {key!r} must be a list of strings")
    if not allow_empty and not value:
        raise WorldDocumentError(f"{context}: {key!r} must not be empty")
    return tuple(value)


def _parse_manifest(path: Path) -> WorldManifest:
    document = _require_object(_read_json(path), str(path))
    _require_schema(document, MANIFEST_SCHEMA, path)
    context = str(path)
    artifact_hashes_raw = document.get("artifact_hashes", {})
    if not isinstance(artifact_hashes_raw, dict) or any(
        not isinstance(key, str) or not isinstance(val, str)
        for key, val in artifact_hashes_raw.items()
    ):
        raise WorldDocumentError(
            f"{context}: 'artifact_hashes' must map artifact names to hash strings"
        )
    manifest = WorldManifest(
        world_id=_require_str(document, "world_id", context),
        workspace_id=_require_str(document, "workspace_id", context),
        status=_require_str(document, "status", context),
        compiler_version=_require_str(document, "compiler_version", context),
        built_at=_require_str(document, "built_at", context),
        manifest_hash=_require_str(document, "manifest_hash", context),
        artifact_hashes=dict(artifact_hashes_raw),
    )
    if manifest.world_id != path.parent.name:
        raise WorldDocumentError(
            f"{context}: world_id {manifest.world_id!r} does not match its "
            f"directory {path.parent.name!r}"
        )
    return manifest


def _parse_evidence(raw: Sequence[Any], context: str) -> tuple[EvidenceRecord, ...]:
    records: list[EvidenceRecord] = []
    for index, item in enumerate(raw):
        item_context = f"{context}: evidence[{index}]"
        entry = _require_object(item, item_context)
        records.append(
            EvidenceRecord(
                source_block_ids=(
                    _require_str_tuple(entry, "source_block_ids", item_context, allow_empty=False)
                ),
                document_version_id=_optional_str(entry, "document_version_id", item_context),
                quote=_optional_str(entry, "quote", item_context),
            )
        )
    return tuple(records)


def parse_timestamp(value: str, context: str) -> datetime:
    """Parse an ISO-8601 timestamp; `Z` suffix included. Fail closed otherwise."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise WorldDocumentError(f"{context}: timestamp {value!r} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise WorldDocumentError(f"{context}: timestamp {value!r} must carry a UTC offset")
    return parsed


def _parse_entities(document: Mapping[str, Any], context: str) -> tuple[EntityRecord, ...]:
    records: list[EntityRecord] = []
    seen: set[str] = set()
    for index, raw_entity in enumerate(document.get("entities", [])):
        entity_context = f"{context}: entities[{index}]"
        entry = _require_object(raw_entity, entity_context)
        entity = EntityRecord(
            entity_id=_require_str(entry, "entity_id", entity_context),
            name=_require_str(entry, "name", entity_context),
            entity_type=_optional_str(entry, "type", entity_context),
            aliases=_require_str_tuple(entry, "aliases", entity_context),
            claim_ids=_require_str_tuple(entry, "claim_ids", entity_context),
        )
        if entity.entity_id in seen:
            raise WorldDocumentError(f"{entity_context}: duplicate entity_id {entity.entity_id!r}")
        seen.add(entity.entity_id)
        records.append(entity)
    return tuple(records)


def _parse_changes(document: Mapping[str, Any], context: str) -> tuple[ChangeRecord, ...]:
    records: list[ChangeRecord] = []
    seen: set[str] = set()
    for index, raw_change in enumerate(document.get("changes", [])):
        change_context = f"{context}: changes[{index}]"
        entry = _require_object(raw_change, change_context)
        change = ChangeRecord(
            change_id=_require_str(entry, "change_id", change_context),
            source_path=_require_str(entry, "source_path", change_context),
            kind=_optional_str(entry, "kind", change_context),
            summary=_optional_str(entry, "summary", change_context),
            changed_at=_optional_str(entry, "changed_at", change_context),
            claim_ids=_require_str_tuple(entry, "claim_ids", change_context),
        )
        if change.change_id in seen:
            raise WorldDocumentError(f"{change_context}: duplicate change_id {change.change_id!r}")
        seen.add(change.change_id)
        records.append(change)
    return tuple(records)


def _parse_dependencies(
    document: Mapping[str, Any], context: str
) -> tuple[DependencyEdgeRecord, ...]:
    records: list[DependencyEdgeRecord] = []
    for index, raw_edge in enumerate(document.get("dependencies", [])):
        edge_context = f"{context}: dependencies[{index}]"
        entry = _require_object(raw_edge, edge_context)
        raw_type = entry.get("edge_type")
        if not isinstance(raw_type, str):
            raise WorldDocumentError(f"{edge_context}: 'edge_type' must be a string")
        try:
            edge_type = EdgeType(raw_type)
        except ValueError as exc:
            known = ", ".join(sorted(member.value for member in EdgeType))
            raise WorldDocumentError(
                f"{edge_context}: edge_type {raw_type!r} is not part of the "
                f"dependency vocabulary ({known})"
            ) from exc
        source = _require_str(entry, "source_id", edge_context)
        target = _require_str(entry, "target_id", edge_context)
        if source == target:
            raise WorldDocumentError(f"{edge_context}: a node cannot depend on itself: {source}")
        records.append(
            DependencyEdgeRecord(source_id=source, target_id=target, edge_type=edge_type)
        )
    return tuple(records)


def _parse_state(
    path: Path,
) -> tuple[
    tuple[TopicRecord, ...],
    tuple[ClaimRecord, ...],
    tuple[EntityRecord, ...],
    tuple[ChangeRecord, ...],
    tuple[DependencyEdgeRecord, ...],
]:
    document = _require_object(_read_json(path), str(path))
    _require_schema(document, STATE_SCHEMA, path)
    context = str(path)

    topics: list[TopicRecord] = []
    seen_topic_ids: set[str] = set()
    for index, raw_topic in enumerate(document.get("topics", [])):
        topic_context = f"{context}: topics[{index}]"
        entry = _require_object(raw_topic, topic_context)
        topic = TopicRecord(
            topic_id=_require_str(entry, "topic_id", topic_context),
            title=_require_str(entry, "title", topic_context),
            summary=_optional_str(entry, "summary", topic_context) or "",
            keywords=_require_str_tuple(entry, "keywords", topic_context),
            claim_ids=_require_str_tuple(entry, "claim_ids", topic_context),
        )
        if topic.topic_id in seen_topic_ids:
            raise WorldDocumentError(f"{topic_context}: duplicate topic_id {topic.topic_id!r}")
        seen_topic_ids.add(topic.topic_id)
        topics.append(topic)

    claims: list[ClaimRecord] = []
    seen_claim_ids: set[str] = set()
    for index, raw_claim in enumerate(document.get("claims", [])):
        claim_context = f"{context}: claims[{index}]"
        entry = _require_object(raw_claim, claim_context)
        confidence_raw = entry.get("confidence")
        if confidence_raw is not None and (
            not isinstance(confidence_raw, (int, float)) or isinstance(confidence_raw, bool)
        ):
            raise WorldDocumentError(f"{claim_context}: 'confidence' must be a number")
        confidence = float(confidence_raw) if confidence_raw is not None else None
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise WorldDocumentError(f"{claim_context}: 'confidence' must be within [0.0, 1.0]")
        claim = ClaimRecord(
            claim_id=_require_str(entry, "claim_id", claim_context),
            text=_require_str(entry, "text", claim_context),
            status=_require_str(entry, "status", claim_context),
            topic_ids=_require_str_tuple(entry, "topic_ids", claim_context),
            evidence=_parse_evidence(entry.get("evidence", []), claim_context),
            confidence=confidence,
        )
        if claim.claim_id in seen_claim_ids:
            raise WorldDocumentError(f"{claim_context}: duplicate claim_id {claim.claim_id!r}")
        seen_claim_ids.add(claim.claim_id)
        claims.append(claim)

    known_claim_ids = seen_claim_ids
    for topic in topics:
        dangling = [cid for cid in topic.claim_ids if cid not in known_claim_ids]
        if dangling:
            raise WorldDocumentError(
                f"{context}: topic {topic.topic_id!r} references unknown claim(s) "
                f"{', '.join(sorted(dangling))}"
            )

    entities = _parse_entities(document, context)
    for entity in entities:
        dangling = [cid for cid in entity.claim_ids if cid not in known_claim_ids]
        if dangling:
            raise WorldDocumentError(
                f"{context}: entity {entity.entity_id!r} references unknown claim(s) "
                f"{', '.join(sorted(dangling))}"
            )
    changes = _parse_changes(document, context)
    dependencies = _parse_dependencies(document, context)

    return tuple(topics), tuple(claims), entities, changes, dependencies


class LocalWorldStore:
    """Read-only access to one world-state directory. Disk is the only source."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def world_dir(self, world_id: str) -> Path:
        if not world_id or "/" in world_id or "\\" in world_id or world_id in {".", ".."}:
            raise UnknownWorldError(f"invalid world id: {world_id!r}")
        return self._root / world_id

    def list_worlds(self) -> tuple[WorldManifest, ...]:
        """Every world directory that declares a readable manifest, sorted."""
        if not self._root.is_dir():
            return ()
        manifests = [
            _parse_manifest(directory / MANIFEST_FILENAME)
            for directory in sorted(self._root.iterdir())
            if (directory / MANIFEST_FILENAME).is_file()
        ]
        return tuple(manifests)

    def has_world(self, world_id: str) -> bool:
        return (self.world_dir(world_id) / MANIFEST_FILENAME).is_file()

    def load_manifest(self, world_id: str) -> WorldManifest:
        path = self.world_dir(world_id) / MANIFEST_FILENAME
        if not path.is_file():
            raise UnknownWorldError(f"no manifest for world {world_id!r} at {path}")
        return _parse_manifest(path)

    def load_snapshot(self, world_id: str) -> WorldSnapshot:
        manifest = self.load_manifest(world_id)
        state_path = self.world_dir(world_id) / STATE_FILENAME
        if not state_path.is_file():
            raise WorldDocumentError(
                f"{state_path}: world {world_id!r} has a manifest but no state file"
            )
        topics, claims, entities, changes, dependencies = _parse_state(state_path)
        return WorldSnapshot(
            manifest=manifest,
            topics=topics,
            claims=claims,
            entities=entities,
            changes=changes,
            dependencies=dependencies,
        )

    def list_history(self) -> tuple[WorldManifest, ...]:
        """Every readable world manifest, oldest first (`built_at` ascending).

        This is the disk's own record of what was published when: the same
        `<root>/<world_id>/{manifest,state}.json` convention, read as a
        timeline. A `built_at` that does not parse as an offset-aware ISO-8601
        timestamp fails closed — an unorderable history would make every
        as-of answer a guess.
        """
        ordered = sorted(
            self.list_worlds(), key=lambda manifest: (manifest.world_id, manifest.built_at)
        )
        stamped: list[tuple[datetime, str, WorldManifest]] = []
        for manifest in ordered:
            moment = parse_timestamp(manifest.built_at, f"world {manifest.world_id!r} built_at")
            stamped.append((moment, manifest.world_id, manifest))
        stamped.sort(key=lambda entry: (entry[0], entry[1]))
        return tuple(manifest for _, _, manifest in stamped)

    @staticmethod
    def diff_claims(snapshot_a: WorldSnapshot, snapshot_b: WorldSnapshot) -> WorldDiff:
        """Claim-level diff of two snapshots; B is the newer side of the comparison.

        A claim is *changed* only when a value actually moved: text, status,
        confidence, topic membership, or its evidence chain. Field changes are
        reported as before/after pairs so the reviewer sees what moved.
        """
        by_id_a = {claim.claim_id: claim for claim in snapshot_a.claims}
        by_id_b = {claim.claim_id: claim for claim in snapshot_b.claims}

        added_ids = sorted(by_id_b.keys() - by_id_a.keys())
        removed_ids = sorted(by_id_a.keys() - by_id_b.keys())
        changed_entries: list[ClaimDiff] = []
        unchanged = 0
        for claim_id in sorted(by_id_a.keys() & by_id_b.keys()):
            left, right = by_id_a[claim_id], by_id_b[claim_id]
            field_changes: list[ClaimFieldChange] = []
            if left.text != right.text:
                field_changes.append(ClaimFieldChange("text", left.text, right.text))
            if left.status != right.status:
                field_changes.append(ClaimFieldChange("status", left.status, right.status))
            if left.confidence != right.confidence:
                field_changes.append(
                    ClaimFieldChange("confidence", left.confidence, right.confidence)
                )
            if left.topic_ids != right.topic_ids:
                field_changes.append(
                    ClaimFieldChange("topic_ids", list(left.topic_ids), list(right.topic_ids))
                )
            evidence_a = [item.to_dict() for item in left.evidence]
            evidence_b = [item.to_dict() for item in right.evidence]
            if evidence_a != evidence_b:
                field_changes.append(ClaimFieldChange("evidence", evidence_a, evidence_b))
            if field_changes:
                changed_entries.append(
                    ClaimDiff(claim_id=claim_id, kind="changed", changes=tuple(field_changes))
                )
            else:
                unchanged += 1

        summary = ChangeSummary(
            added=len(added_ids),
            removed=len(removed_ids),
            changed=len(changed_entries),
            unchanged=unchanged,
        )
        return WorldDiff(
            world_a=snapshot_a.manifest.world_id,
            world_b=snapshot_b.manifest.world_id,
            added=tuple(ClaimDiff(claim_id=cid, kind="added") for cid in added_ids),
            removed=tuple(ClaimDiff(claim_id=cid, kind="removed") for cid in removed_ids),
            changed=tuple(changed_entries),
            summary=summary,
        )

    def diff_worlds(self, world_a: str, world_b: str) -> WorldDiff:
        """Load both worlds from disk and diff their claims (B newer)."""
        return self.diff_claims(self.load_snapshot(world_a), self.load_snapshot(world_b))
