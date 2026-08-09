"""Stable identity for sources, versions, evidence and knowledge units.

The North Star masterplan §9 states the constraint plainly: temporal knowledge
and incremental recompilation do not work without stable identity. Before this
module the repository derived none of these ids -- `document_version_id` was
passed in from the caller and never computed, and `logical_id` did not exist at
all. Everything §13 through §16 wants to build (valid time, dependency edges,
impact traversal, selective recompile) stands on being able to say *this is the
same thing as before* across two versions of a document.

Three of the four ids are pure functions of their inputs, so two compiles of the
same bytes produce the same id on any machine. The fourth -- logical identity --
is a judgement, and this module treats it as one: it returns a decision with the
evidence behind it, and it refuses to merge when the evidence is weak rather
than guessing. §9.4: "불확실한 경우 자동 merge 금지."
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "IDENTITY_SCHEME_VERSION",
    "LogicalIdentityDecision",
    "LogicalIdentityResolver",
    "LogicalMatch",
    "LogicalUnitFingerprint",
    "document_version_id",
    "evidence_id",
    "logical_id_seed",
    "normalize_bbox1000",
    "normalize_text_for_identity",
    "source_id",
]

# Bumping this changes every derived id, so it is versioned deliberately: an id
# computed under one scheme must never be silently compared against another.
IDENTITY_SCHEME_VERSION = "1"

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)


def _digest(prefix: str, *parts: str) -> str:
    """A namespaced digest over length-delimited parts.

    Length delimiting matters: without it, ("ab", "c") and ("a", "bc") hash to
    the same value, and a tenant named `ab` with connector `c` would collide
    with tenant `a` and connector `bc`.
    """
    payload = "\x1f".join(f"{len(part)}:{part}" for part in parts)
    body = f"akc.identity.v{IDENTITY_SCHEME_VERSION}\x1e{prefix}\x1e{payload}"
    return f"{prefix}_{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


def normalize_text_for_identity(text: str) -> str:
    """Fold the differences that should not change what a unit *is*.

    A clause that gains a trailing space, gets re-wrapped, or arrives from a
    parser that emits full-width punctuation is the same clause. Case and
    punctuation are folded for the same reason. This is deliberately lossy and
    is only ever used for identity, never for content.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = _PUNCTUATION.sub(" ", folded)
    return _WHITESPACE.sub(" ", folded).strip()


def normalize_bbox1000(
    bbox: tuple[int, int, int, int] | None, *, tolerance: int = 2
) -> tuple[int, int, int, int] | None:
    """Quantise a per-mille box so re-extraction jitter does not change an id.

    Two runs of the same parser on the same page can differ by a per-mille unit
    or two in a box edge. Without quantisation that makes a new evidence id for
    the same region, which would look like the evidence moved.
    """
    if bbox is None:
        return None
    if len(bbox) != 4:
        raise ValueError("bbox1000 must have four coordinates")
    if any(not (0 <= value <= 1000) for value in bbox):
        raise ValueError("bbox1000 coordinates must fall within 0..1000")
    x0, y0, x1, y1 = bbox
    if x1 < x0 or y1 < y0:
        raise ValueError("bbox1000 must not have inverted edges")
    step = max(1, tolerance)
    return tuple(round(value / step) * step for value in (x0, y0, x1, y1))  # type: ignore[return-value]


def source_id(*, tenant_id: str, connector_type: str, native_id: str) -> str:
    """§9.1 — one logical source, stable across every version of its content.

    `native_id` is the connector's own identifier where it has one, and a
    canonical path where it does not. It is never the display filename: a file
    renamed from `warranty.pdf` to `warranty_final.pdf` is the same source, and
    the masterplan's §8.1 forbids reading `FINAL` in a filename as meaning.
    """
    for name, value in (
        ("tenant_id", tenant_id),
        ("connector_type", connector_type),
        ("native_id", native_id),
    ):
        if not value or not value.strip():
            raise ValueError(f"{name} is required to derive a source id")
    return _digest("src", tenant_id.strip(), connector_type.strip(), native_id.strip())


def document_version_id(*, source: str, content_sha256: str) -> str:
    """§9.2 — one immutable version of one source.

    Keyed on content, so re-uploading identical bytes resolves to the version
    that already exists instead of creating a second one.
    """
    if not source.startswith("src_"):
        raise ValueError("document version id requires a source id")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", content_sha256):
        raise ValueError("content_sha256 must be a lowercase sha256: digest")
    return _digest("dv", source, content_sha256)


def evidence_id(
    *,
    document_version: str,
    page_number1: int,
    bbox1000: tuple[int, int, int, int] | None = None,
    span_text: str | None = None,
) -> str:
    """§9.3 — one anchored region of one document version.

    At least one anchor is required. An evidence id over a page number alone
    would make every unit on a page share an id, and §8.1 forbids inventing a
    box to fill the gap: a source without coordinates keeps `bbox1000=None` and
    anchors on its span instead.
    """
    if not document_version.startswith("dv_"):
        raise ValueError("evidence id requires a document version id")
    if page_number1 < 1:
        raise ValueError("page_number1 is 1-based")
    box = normalize_bbox1000(bbox1000)
    span = normalize_text_for_identity(span_text) if span_text is not None else ""
    if box is None and not span:
        raise ValueError(
            "evidence needs an anchor: supply a bbox, a span, or both. A page "
            "number alone would give every unit on the page the same id."
        )
    span_hash = hashlib.sha256(span.encode("utf-8")).hexdigest() if span else ""
    box_part = ",".join(str(value) for value in box) if box else ""
    return _digest("ev", document_version, str(page_number1), box_part, span_hash)


def logical_id_seed(*, source: str, document_path: tuple[str, ...], anchor: str) -> str:
    """The id a knowledge unit gets when nothing prior matches it.

    Seeded from the source and its structural path rather than its content, so
    that a clause keeps its identity when its wording changes -- which is the
    entire point of §9.4. Content is not in the seed.
    """
    if not source.startswith("src_"):
        raise ValueError("logical id requires a source id")
    path = "\x1d".join(normalize_text_for_identity(part) for part in document_path)
    return _digest("ku", source, path, normalize_text_for_identity(anchor))


class LogicalMatch(StrEnum):
    """What the resolver concluded, including when it concluded nothing."""

    MATCHED = "matched"
    NEW = "new"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class LogicalUnitFingerprint:
    """What the resolver compares. Deliberately small.

    Anything that changes freely between versions -- page number, bbox, sequence
    index in absolute terms -- is not here, because a unit that moves down a page
    is still the same unit.
    """

    logical_id: str
    document_path: tuple[str, ...]
    anchor: str
    normalized_text: str
    neighbour_anchors: tuple[str, ...] = ()

    @staticmethod
    def of(
        *,
        logical_id: str,
        document_path: tuple[str, ...],
        anchor: str,
        text: str,
        neighbour_anchors: tuple[str, ...] = (),
    ) -> LogicalUnitFingerprint:
        return LogicalUnitFingerprint(
            logical_id=logical_id,
            document_path=tuple(document_path),
            anchor=anchor,
            normalized_text=normalize_text_for_identity(text),
            neighbour_anchors=tuple(neighbour_anchors),
        )


@dataclass(frozen=True, slots=True)
class LogicalIdentityDecision:
    """A resolution and the reason for it.

    The reason is not decoration. When a resolver refuses to merge, the operator
    needs to see which signals agreed and which did not, because the alternative
    -- a bare "ambiguous" -- is indistinguishable from a bug.
    """

    match: LogicalMatch
    logical_id: str | None
    score: float
    signals: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    candidates: tuple[str, ...] = ()

    @property
    def merged(self) -> bool:
        return self.match is LogicalMatch.MATCHED


def _jaccard(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _path_agreement(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    if not left and not right:
        return 1.0
    normalized_left = [normalize_text_for_identity(part) for part in left]
    normalized_right = [normalize_text_for_identity(part) for part in right]
    shared = 0
    for a, b in zip(normalized_left, normalized_right, strict=False):
        if a != b:
            break
        shared += 1
    longest = max(len(normalized_left), len(normalized_right))
    return shared / longest if longest else 1.0


class LogicalIdentityResolver:
    """Decide whether a unit in a new version continues one from the old version.

    Four signals, none of which is trusted alone:

      structural path   the heading trail the unit sits under
      anchor            its own heading or first-line label
      content           token overlap of normalized text
      neighbours        the anchors immediately around it

    A high score merges, a low score starts a new identity, and the band between
    them is reported as ambiguous rather than resolved. That band is the whole
    reason this class exists: a wrong merge silently rewrites the history of a
    policy clause, and no downstream temporal query can detect it afterwards.
    """

    def __init__(
        self,
        *,
        merge_threshold: float = 0.72,
        new_threshold: float = 0.35,
        weights: dict[str, float] | None = None,
    ) -> None:
        if not 0.0 < new_threshold < merge_threshold <= 1.0:
            raise ValueError(
                "thresholds must satisfy 0 < new_threshold < merge_threshold <= 1"
            )
        self.merge_threshold = merge_threshold
        self.new_threshold = new_threshold
        self.weights = weights or {
            "path": 0.30,
            "anchor": 0.25,
            "content": 0.30,
            "neighbours": 0.15,
        }
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"identity signal weights must sum to 1.0, got {total}")

    def _score(
        self, candidate: LogicalUnitFingerprint, incoming: LogicalUnitFingerprint
    ) -> tuple[float, dict[str, float]]:
        signals = {
            "path": _path_agreement(candidate.document_path, incoming.document_path),
            "anchor": _jaccard(
                normalize_text_for_identity(candidate.anchor),
                normalize_text_for_identity(incoming.anchor),
            ),
            "content": _jaccard(candidate.normalized_text, incoming.normalized_text),
            "neighbours": _jaccard(
                " ".join(normalize_text_for_identity(a) for a in candidate.neighbour_anchors),
                " ".join(normalize_text_for_identity(a) for a in incoming.neighbour_anchors),
            ),
        }
        score = sum(signals[name] * weight for name, weight in self.weights.items())
        return score, signals

    def resolve(
        self,
        incoming: LogicalUnitFingerprint,
        previous: list[LogicalUnitFingerprint],
        *,
        seed_logical_id: str | None = None,
    ) -> LogicalIdentityDecision:
        if not previous:
            return LogicalIdentityDecision(
                match=LogicalMatch.NEW,
                logical_id=seed_logical_id or incoming.logical_id,
                score=0.0,
                reason="no prior version to continue from",
            )

        scored = sorted(
            ((self._score(candidate, incoming), candidate) for candidate in previous),
            key=lambda item: item[0][0],
            reverse=True,
        )
        (best_score, best_signals), best = scored[0]
        runner_up = scored[1][0][0] if len(scored) > 1 else 0.0

        if best_score < self.new_threshold:
            return LogicalIdentityDecision(
                match=LogicalMatch.NEW,
                logical_id=seed_logical_id or incoming.logical_id,
                score=best_score,
                signals=best_signals,
                reason=(
                    f"best candidate scored {best_score:.2f}, below the "
                    f"{self.new_threshold:.2f} floor for continuing an identity"
                ),
            )

        # Two candidates that score alike are the dangerous case: one of them is
        # the continuation and picking the wrong one rewrites the wrong history.
        if best_score - runner_up < 0.05 and len(scored) > 1:
            return LogicalIdentityDecision(
                match=LogicalMatch.AMBIGUOUS,
                logical_id=None,
                score=best_score,
                signals=best_signals,
                reason=(
                    f"two candidates scored within 0.05 ({best_score:.2f} and "
                    f"{runner_up:.2f}); merging would pick one history arbitrarily"
                ),
                candidates=(best.logical_id, scored[1][1].logical_id),
            )

        if best_score < self.merge_threshold:
            return LogicalIdentityDecision(
                match=LogicalMatch.AMBIGUOUS,
                logical_id=None,
                score=best_score,
                signals=best_signals,
                reason=(
                    f"score {best_score:.2f} sits between the {self.new_threshold:.2f} "
                    f"floor and the {self.merge_threshold:.2f} merge threshold"
                ),
                candidates=(best.logical_id,),
            )

        return LogicalIdentityDecision(
            match=LogicalMatch.MATCHED,
            logical_id=best.logical_id,
            score=best_score,
            signals=best_signals,
            reason=f"continues {best.logical_id} at {best_score:.2f}",
            candidates=(best.logical_id,),
        )
