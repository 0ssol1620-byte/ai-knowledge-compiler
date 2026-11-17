"""Identity by connector-declared fact key, decided per key pair (ADR-010). Benchmark-only.

Where a declaration says a connector's regions carry a source-assigned fact key, a document of
that connector takes the keyed path: each current unit is offered to the unchanged matcher in a
1x1 call against the previous unit with the same key (or none), and the semantic diff runs the
same 1x1 call per key. Keyed units never reach the document-wide matching, so no unit is paired
across keys. Same-key identity stays bounded by the matcher's band, text AND path (D12-D12a).

Nothing here is reachable from the served app: a declaration is explicit data passed to the
`ProductCoreCompiler` constructor, never derived from a connector's name or a request field.
Errors carry ids only, never document text.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from akc_cir.identity import (
    LogicalIdentityDecision,
    LogicalMatch,
    LogicalUnitFingerprint,
    assign_one_to_one,
    normalize_text_for_identity,
)
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    DocumentShape,
    SemanticChange,
    UnitSnapshot,
    diff_documents,
)

# The SEC FSDS benchmark adapter's key (benchmark/local_public/sec_pairs.py:129-131), as Step 0
# ran it (receipts/WO-D12-12/step0/keyed.json `key_pattern`, `collision_suffix`), with the last
# group tightened (D12-D12b) so the U06 fault suffix "-dup" cannot pass as a declared key.
# A pinned pattern, not a declaration: nothing is keyed until a FactKeyDeclaration names it.
SEC_FSDS_KEY_PATTERN = r"[A-Za-z0-9._:-]+-\d{8}m-\d+-[A-Za-z0-9._:-]+(?<!-dup)"
SEC_FSDS_COLLISION_SUFFIX = r"-l\d+$"

# Shapes of the native parsers' positional ids (design PART A7), written so each passes the
# contract's Identifier. A declaration whose pattern takes any of them is refused. This is a lint
# against an over-broad pattern, not evidence that a key is source-assigned: a positional scheme
# that is not listed here (say `row-12`) passes it.
_POSITIONAL_PROBES = (
    "docx-body-p-000001",
    "docx-body-table-3-r-1-c-2",
    "html-body-1-p-3",
    "pdf-page-0-text-0123456789abcdef0123",
    "xlsx-sheet-0000-cell-A1",
    "pptx-slide-0001",
    "srt-cue-000001",
    "1.1_p0",
)
# contracts.Identifier: a previous unit's anchor is unbounded `str` on the wire; a keyed anchor is
# an id and is held to the same shape before it decides identity or appears in a review reason.
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _compiled(name: str, pattern: object) -> re.Pattern[str]:
    if not isinstance(pattern, str) or not pattern:
        raise ValueError(f"fact key declaration: {name} must be a non-empty regex")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"fact key declaration: {name} is not a valid regex") from exc


@dataclass(frozen=True)
class FactKeyDeclaration:
    """A connector whose regions carry a source-assigned fact key in `native_object_id`.

    `evidence_ref` / `evidence_sha256` pin what the key's definition and stability rest on.
    """

    connector_type: str
    key_pattern: str
    collision_suffix: str | None
    evidence_ref: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.connector_type, str) or not _IDENTIFIER.fullmatch(
            self.connector_type
        ):
            raise ValueError("fact key declaration: connector_type must be an Identifier")
        key = _compiled("key_pattern", self.key_pattern)
        if self.collision_suffix is not None:
            _compiled("collision_suffix", self.collision_suffix)
        if not isinstance(self.evidence_ref, str) or not self.evidence_ref.strip():
            raise ValueError("fact key declaration: evidence_ref is required")
        if not isinstance(self.evidence_sha256, str) or not _SHA256_HEX.fullmatch(
            self.evidence_sha256
        ):
            raise ValueError("fact key declaration: evidence_sha256 must be 64 lowercase hex")
        positional = [probe for probe in _POSITIONAL_PROBES if key.fullmatch(probe)]
        if positional:
            raise ValueError(
                f"fact key declaration for {self.connector_type}: key_pattern accepts "
                f"positional ids {positional}"
            )

    def is_key(self, value: str | None) -> bool:
        return (
            value is not None
            and _IDENTIFIER.fullmatch(value) is not None
            and re.fullmatch(self.key_pattern, value) is not None
        )

    def base(self, key: str) -> str:
        """The key without its collision suffix, folded."""
        if self.collision_suffix is not None:
            key = re.sub(self.collision_suffix, "", key)
        return normalize_text_for_identity(key)


class FactKeyDisagreement(ValueError):
    """The per-key diff did not report what the compiler decided for a keyed unit. Ids only."""

    def __init__(self, *, source: str, key: str, decision: str, kinds: list[str]) -> None:
        super().__init__(
            f"keyed identity disagreement in {source} at {key}: compiler {decision}, diff {kinds}"
        )
        self.source = source
        self.key = key
        self.decision = decision
        self.kinds = kinds


def refusal(
    declaration: FactKeyDeclaration,
    current_keys: Sequence[str | None],
    previous_anchors: Sequence[str],
) -> str | None:
    """The document-level detector that keeps a document on today's path, or None.

    D-MISSING: a current region without a key, or a key or previous anchor the pattern rejects
    (a mixed document included). D-DUP: two keys of one version equal under the identity fold or
    after stripping the collision suffix; or a current key that folds to a previous key while
    differing from it raw (N1), because the fold would join two spellings across versions.
    """
    if not all(declaration.is_key(key) for key in current_keys) or not all(
        declaration.is_key(anchor) for anchor in previous_anchors
    ):
        return "D-MISSING"
    keys = [key for key in current_keys if key is not None]
    for side in (keys, list(previous_anchors)):
        if len({normalize_text_for_identity(k) for k in side}) != len(side):
            return "D-DUP"
        if len({declaration.base(k) for k in side}) != len(side):
            return "D-DUP"
    previous_by_fold = {normalize_text_for_identity(a): a for a in previous_anchors}
    if any(previous_by_fold.get(normalize_text_for_identity(k), k) != k for k in keys):
        return "D-DUP"
    return None


def relocations(
    current: Sequence[tuple[str, str]], previous: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    """D-RELOC, per unit, counted, never refusing (D12-D12): (previous key, current key) for each
    current unit whose text is unique in its version and stands, unique, under another key in
    the previous version. Inputs are (key, text); texts are compared under the identity fold."""
    current_text = [normalize_text_for_identity(text) for _, text in current]
    previous_text = [normalize_text_for_identity(text) for _, text in previous]
    current_count, previous_count = Counter(current_text), Counter(previous_text)
    previous_key_by_text = {
        text: key
        for (key, _), text in zip(previous, previous_text, strict=True)
        if previous_count[text] == 1
    }
    found: list[tuple[str, str]] = []
    for (key, _), text in zip(current, current_text, strict=True):
        before = previous_key_by_text.get(text)
        if current_count[text] != 1 or before is None:
            continue
        # The text is unique before, so the current key's own previous unit (if any) carries
        # other text: no further check is needed for "P(key) absent or different".
        if normalize_text_for_identity(before) != normalize_text_for_identity(key):
            found.append((before, key))
    return found


def keyed_decisions(
    incoming: Sequence[LogicalUnitFingerprint], previous: Sequence[LogicalUnitFingerprint]
) -> tuple[list[LogicalIdentityDecision], list[int | None]]:
    """One unchanged 1x1 matcher call per current key: against the previous unit with the same
    folded key, or against nothing (NEW with the unit's own seed). Returns the decisions and,
    per current unit, the index of its same-key previous unit."""
    by_key = {normalize_text_for_identity(unit.anchor): j for j, unit in enumerate(previous)}
    partners = [by_key.get(normalize_text_for_identity(unit.anchor)) for unit in incoming]
    decisions = [
        assign_one_to_one([unit], [previous[j]] if j is not None else [])[0]
        for unit, j in zip(incoming, partners, strict=True)
    ]
    return decisions, partners


def keyed_document_changes(
    *,
    before_sha256: str,
    after_sha256: str,
    before_shape: DocumentShape,
    after_shape: DocumentShape,
    previous: Sequence[UnitSnapshot],
    resolved: Sequence[UnitSnapshot],
    decisions: Sequence[LogicalIdentityDecision],
    partners: Sequence[int | None],
    source: str,
) -> list[SemanticChange]:
    """The diff of a keyed document from unchanged `diff_documents` calls: one structural call,
    one per current unit in order (its same-key previous unit or none), one per previous key that
    is gone. Each per-key call runs inside the diff exactly the 1x1 matcher call the compiler
    ran; what it emits is checked against the compiler's decision (S3) and a mismatch raises."""
    changes = list(
        diff_documents(
            before_sha256=before_sha256,
            after_sha256=after_sha256,
            level=DiffLevel.STRUCTURAL,
            before_shape=before_shape,
            after_shape=after_shape,
        ).changes
    )

    def call(before: list[UnitSnapshot], after: list[UnitSnapshot]) -> list[SemanticChange]:
        return list(
            diff_documents(
                before_sha256=before_sha256,
                after_sha256=after_sha256,
                level=DiffLevel.GRAPH,
                before_shape=DocumentShape(),
                after_shape=DocumentShape(),
                before_units=before,
                after_units=after,
                source=source,
            ).changes
        )

    for unit, decision, j in zip(resolved, decisions, partners, strict=True):
        partner = previous[j] if j is not None else None
        emitted = call([partner] if partner else [], [unit])
        _agree(source, unit.anchor, decision.match, unit, partner, emitted)
        changes.extend(emitted)
    taken = {j for j in partners if j is not None}
    for j, gone in enumerate(previous):
        if j in taken:
            continue
        emitted = call([gone], [])
        if [(c.kind, c.logical_id) for c in emitted] != [
            (ChangeKind.UNIT_REMOVED, gone.logical_id)
        ]:
            raise FactKeyDisagreement(
                source=source,
                key=gone.anchor,
                decision="REMOVED",
                kinds=[c.kind.value for c in emitted],
            )
        changes.extend(emitted)
    return changes


def _agree(
    source: str,
    key: str,
    match: LogicalMatch,
    unit: UnitSnapshot,
    partner: UnitSnapshot | None,
    emitted: list[SemanticChange],
) -> None:
    added = [c.logical_id for c in emitted if c.kind is ChangeKind.UNIT_ADDED]
    removed = [c.logical_id for c in emitted if c.kind is ChangeKind.UNIT_REMOVED]
    unresolved = [c for c in emitted if c.kind is ChangeKind.IDENTITY_UNRESOLVED]
    if match is LogicalMatch.MATCHED:
        ok = (
            partner is not None
            and not added
            and not removed
            and not unresolved
            and all(c.logical_id == partner.logical_id for c in emitted)
        )
    elif match is LogicalMatch.AMBIGUOUS:
        ok = (
            partner is not None
            and not added
            and not removed
            and len(unresolved) == 1
            and partner.logical_id in unresolved[0].candidates
        )
    else:
        ok = (
            added == [unit.logical_id]
            and removed == ([partner.logical_id] if partner else [])
            and not unresolved
        )
    if not ok:
        raise FactKeyDisagreement(
            source=source, key=key, decision=match.value, kinds=[c.kind.value for c in emitted]
        )
