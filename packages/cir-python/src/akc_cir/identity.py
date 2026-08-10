"""Stable identity for sources, versions, evidence and knowledge units.

The masterplan states the constraint plainly: temporal knowledge and incremental
recompilation do not work without stable identity. Before this module the
repository derived none of these ids -- `document_version_id` was passed in from
the caller and never computed, and `logical_id` did not exist at all. Everything
the temporal, dependency, impact and recompile layers want to build stands on
being able to say *this is the same thing as before* across two versions.

Three of the four ids are pure functions of their inputs, so two compiles of the
same bytes produce the same id on any machine. The fourth -- logical identity --
is a judgement, and this module treats it as one: it returns a decision with the
evidence behind it, and it refuses to merge when the evidence is weak rather
than guessing.

The matching method follows v3.1 §N15, which outranks the earlier §9 sketch this
module was first written against. Two things changed as a result and both matter:

**The merge bar moved from 0.72 to 0.92.** §N15.4 sets it there and invariant 10
says why -- *false merge는 false split보다 비싸다*. A wrong merge rewrites the
history of a clause, and no temporal query afterwards can detect it. A wrong
split is visible: two identities where there should be one, which a reviewer can
join.

**A missing signal is missing, not zero.** §N4.4 forbids filling an absent
feature with a zero. Applied here it is not a nicety: most prose paragraphs carry
no explicit clause identifier, and scoring that signal zero caps every such unit
at 0.85 -- below the 0.92 bar, forever. Nothing would ever merge. So the score is
renormalised over the signals that have values, the absent ones are recorded with
a reason, and when a *critical* signal is absent the resolver abstains instead of
scoring the remainder higher.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "CRITICAL_IDENTITY_SIGNALS",
    "IDENTITY_SCHEME_VERSION",
    "IDENTITY_SIGNAL_WEIGHTS",
    "MERGE_THRESHOLD",
    "NEW_IDENTITY_THRESHOLD",
    "LogicalIdentityDecision",
    "LogicalIdentityResolver",
    "LogicalMatch",
    "LogicalRelation",
    "LogicalUnitFingerprint",
    "MissingReason",
    "assign_one_to_one",
    "document_version_id",
    "evidence_id",
    "generate_candidates",
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
    """One logical source, stable across every version of its content.

    `native_id` is the connector's own identifier where it has one, and a
    canonical path where it does not. It is never the display filename: a file
    renamed from `warranty.pdf` to `warranty_final.pdf` is the same source, and
    §X5.6 forbids reading `FINAL` in a filename as meaning.
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
    """One immutable version of one source.

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
    """One anchored region of one document version.

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
    entire point. Content is not in the seed.
    """
    if not source.startswith("src_"):
        raise ValueError("logical id requires a source id")
    path = "\x1d".join(normalize_text_for_identity(part) for part in document_path)
    return _digest("ku", source, path, normalize_text_for_identity(anchor))


# ---------------------------------------------------------------------------
# §N15 — stable semantic identity
# ---------------------------------------------------------------------------


class LogicalMatch(StrEnum):
    """What the resolver concluded, including when it concluded nothing."""

    MATCHED = "matched"
    NEW = "new"
    AMBIGUOUS = "ambiguous"


class LogicalRelation(StrEnum):
    """§N15.3 — how a new unit relates to what came before.

    Continuation is not the only outcome. A clause split in two, or two merged
    into one, is a real editorial act; recording it as `SAME_AS_VERSION` for one
    half and a fresh identity for the other loses the fact that they are related,
    and the impact traversal then under-reports the blast radius.
    """

    SAME_AS_VERSION = "SAME_AS_VERSION"
    SPLIT_INTO = "SPLIT_INTO"
    MERGED_FROM = "MERGED_FROM"
    MOVED_FROM = "MOVED_FROM"


class MissingReason(StrEnum):
    """§N4.4 — why a signal has no value. It is never filled with a zero."""

    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    ERROR = "ERROR"


#: §N15.2's weights, verbatim.
IDENTITY_SIGNAL_WEIGHTS: dict[str, float] = {
    "source_continuity": 0.25,
    "structural_path": 0.20,
    "explicit_identifier": 0.15,
    "semantic": 0.15,
    "previous_neighbor": 0.10,
    "next_neighbor": 0.10,
    "geometry_style": 0.05,
}

#: The signals without which a merge is a guess rather than a judgement. §N5.5
#: lists "critical features missing" as a mandatory abstention, and identity is
#: where abstaining is cheapest: an unresolved identity costs a rebuild, a wrong
#: one costs a rewritten history.
CRITICAL_IDENTITY_SIGNALS = frozenset(
    {"source_continuity", "structural_path", "semantic"}
)

#: §N15.4 bootstrap bands. `>=0.92` auto same logical id, `0.75-0.92` ambiguous
#: and reviewable, `<0.75` a new logical id. Deliberately more conservative than
#: a scoring intuition suggests; calibrated per route/document type later, and
#: the masterplan says to stay conservative until then.
MERGE_THRESHOLD = 0.92
NEW_IDENTITY_THRESHOLD = 0.75

#: Two candidates this close apart are not distinguishable by the score, so
#: picking the higher one picks a history arbitrarily.
_TIE_BAND = 0.05

#: Per-version decay for a candidate that is not the immediately preceding
#: version. Bootstrap, floored so an old version stays a plausible ancestor.
_LINEAGE_DECAY = 0.15
_LINEAGE_FLOOR = 0.25


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


@dataclass(frozen=True, slots=True)
class LogicalUnitFingerprint:
    """What the resolver compares -- one input per §N15.2 signal.

    Anything that changes freely between versions (page number, absolute
    sequence index) is deliberately absent: a unit that moves down a page is
    still the same unit.

    Every comparable field may be empty, and empty means *not available* rather
    than *empty string*. §N4.4 is explicit that the two are different, and the
    scorer treats them differently.
    """

    logical_id: str
    document_path: tuple[str, ...]
    anchor: str
    normalized_text: str
    #: The source this unit came from. Candidates from a different source score
    #: zero on continuity rather than being silently comparable.
    source_lineage: str = ""
    #: How many versions back this fingerprint sits. 1 is the immediately
    #: preceding version. Only meaningful on a candidate, not on the incoming.
    version_distance: int = 1
    #: A clause/table/section number the document itself gave, e.g. "4.2".
    explicit_identifier: str = ""
    previous_anchor: str = ""
    next_anchor: str = ""
    #: A stable summary of font/size/indent, however the parser spells it.
    geometry_style: str = ""

    @staticmethod
    def of(
        *,
        logical_id: str,
        document_path: tuple[str, ...],
        anchor: str,
        text: str,
        source_lineage: str = "",
        version_distance: int = 1,
        explicit_identifier: str = "",
        previous_anchor: str = "",
        next_anchor: str = "",
        geometry_style: str = "",
        neighbour_anchors: tuple[str, ...] = (),
    ) -> LogicalUnitFingerprint:
        """Build a fingerprint, normalising the text.

        `neighbour_anchors` is accepted as a convenience for callers that carry
        the surrounding anchors as one sequence: the first is read as the
        previous anchor and the last as the next. An explicit
        `previous_anchor`/`next_anchor` always wins.
        """
        if neighbour_anchors:
            previous_anchor = previous_anchor or neighbour_anchors[0]
            next_anchor = next_anchor or neighbour_anchors[-1]
        return LogicalUnitFingerprint(
            logical_id=logical_id,
            document_path=tuple(document_path),
            anchor=anchor,
            normalized_text=normalize_text_for_identity(text),
            source_lineage=source_lineage,
            version_distance=version_distance,
            explicit_identifier=explicit_identifier,
            previous_anchor=previous_anchor,
            next_anchor=next_anchor,
            geometry_style=geometry_style,
        )


@dataclass(frozen=True, slots=True)
class LogicalIdentityDecision:
    """A resolution and the reason for it.

    The reason is not decoration. When a resolver refuses to merge, the operator
    needs to see which signals agreed, which disagreed and which had no value at
    all, because the alternative -- a bare "ambiguous" -- is indistinguishable
    from a bug.
    """

    match: LogicalMatch
    logical_id: str | None
    score: float
    signals: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    candidates: tuple[str, ...] = ()
    #: §N4.4 -- signal name to the reason it had no value. Never zero-filled.
    missing: dict[str, str] = field(default_factory=dict)
    relation: LogicalRelation | None = None

    @property
    def merged(self) -> bool:
        return self.match is LogicalMatch.MATCHED


def generate_candidates(
    incoming: LogicalUnitFingerprint,
    previous: list[LogicalUnitFingerprint],
    *,
    window: int = 24,
) -> list[LogicalUnitFingerprint]:
    """§N15.1 -- restrict who a unit may be compared against.

    *전 workspace global all-pairs 비교 금지.* Two reasons, and the second is the
    one that bites: all-pairs is quadratic, and it also raises the chance that
    some unrelated unit in another document happens to score above the bar. A
    smaller candidate set is both cheaper and safer.

    Kept: same source lineage, same or adjacent structural path, a matching
    explicit identifier, or an anchor that appears as this unit's neighbour. The
    ordering is by structural proximity so the window keeps the nearest.
    """
    same_source = [
        candidate
        for candidate in previous
        if not incoming.source_lineage
        or not candidate.source_lineage
        or candidate.source_lineage == incoming.source_lineage
    ]

    def keep(candidate: LogicalUnitFingerprint) -> bool:
        if (
            incoming.explicit_identifier
            and candidate.explicit_identifier
            and normalize_text_for_identity(candidate.explicit_identifier)
            == normalize_text_for_identity(incoming.explicit_identifier)
        ):
            return True
        if candidate.anchor and candidate.anchor in {
            incoming.previous_anchor,
            incoming.next_anchor,
        }:
            return True
        return _path_agreement(candidate.document_path, incoming.document_path) > 0.0

    kept = [candidate for candidate in same_source if keep(candidate)]
    kept.sort(
        key=lambda candidate: (
            -_path_agreement(candidate.document_path, incoming.document_path),
            candidate.logical_id,
        )
    )
    return kept[:window]


class LogicalIdentityResolver:
    """Decide whether a unit in a new version continues one from the old version.

    Seven signals per §N15.2, none trusted alone, each able to say *I have no
    value* rather than being coerced to zero. The score is the weighted mean over
    the signals that do have values; a signal with no value neither helps nor
    hurts, which is the only reading of §N4.4 that keeps prose units mergeable at
    all.

    Abstention is a first-class outcome. If one of the critical signals has no
    value the resolver returns AMBIGUOUS whatever the others say, because the
    remaining signals renormalised to 1.0 would otherwise manufacture a
    confident score out of a thin one.
    """

    def __init__(
        self,
        *,
        merge_threshold: float = MERGE_THRESHOLD,
        new_threshold: float = NEW_IDENTITY_THRESHOLD,
        weights: dict[str, float] | None = None,
        tie_band: float = _TIE_BAND,
    ) -> None:
        if not 0.0 < new_threshold < merge_threshold <= 1.0:
            raise ValueError(
                "thresholds must satisfy 0 < new_threshold < merge_threshold <= 1"
            )
        self.merge_threshold = merge_threshold
        self.new_threshold = new_threshold
        self.tie_band = tie_band
        self.weights = dict(weights or IDENTITY_SIGNAL_WEIGHTS)
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"identity signal weights must sum to 1.0, got {total}")

    # -- signals ----------------------------------------------------------

    def _source_continuity(
        self, candidate: LogicalUnitFingerprint, incoming: LogicalUnitFingerprint
    ) -> tuple[float | None, MissingReason | None]:
        if not candidate.source_lineage or not incoming.source_lineage:
            return None, MissingReason.NOT_APPLICABLE
        if candidate.source_lineage != incoming.source_lineage:
            return 0.0, None
        steps = max(0, candidate.version_distance - 1)
        return max(_LINEAGE_FLOOR, 1.0 - _LINEAGE_DECAY * steps), None

    def _explicit_identifier(
        self, candidate: LogicalUnitFingerprint, incoming: LogicalUnitFingerprint
    ) -> tuple[float | None, MissingReason | None]:
        # Only comparable when both sides have one. If the old clause was
        # numbered and the new one is not, that is a document that dropped its
        # numbering, not evidence that the clauses differ -- and scoring it zero
        # would push a genuine continuation below the bar.
        if not candidate.explicit_identifier or not incoming.explicit_identifier:
            return None, MissingReason.NOT_APPLICABLE
        left = normalize_text_for_identity(candidate.explicit_identifier)
        right = normalize_text_for_identity(incoming.explicit_identifier)
        return (1.0 if left == right else 0.0), None

    @staticmethod
    def _anchor_pair(
        left: str, right: str
    ) -> tuple[float | None, MissingReason | None]:
        if not left or not right:
            # The first unit in a document has no previous anchor. That is a
            # property of where it sits, not a failure to compute anything.
            return None, MissingReason.NOT_APPLICABLE
        return (
            _jaccard(
                normalize_text_for_identity(left), normalize_text_for_identity(right)
            ),
            None,
        )

    def _signals(
        self, candidate: LogicalUnitFingerprint, incoming: LogicalUnitFingerprint
    ) -> tuple[dict[str, float], dict[str, str]]:
        raw: dict[str, tuple[float | None, MissingReason | None]] = {
            "source_continuity": self._source_continuity(candidate, incoming),
            "structural_path": (
                _path_agreement(candidate.document_path, incoming.document_path),
                None,
            ),
            "explicit_identifier": self._explicit_identifier(candidate, incoming),
            "semantic": (
                None
                if not candidate.normalized_text and not incoming.normalized_text
                else _jaccard(candidate.normalized_text, incoming.normalized_text),
                MissingReason.NOT_APPLICABLE
                if not candidate.normalized_text and not incoming.normalized_text
                else None,
            ),
            "previous_neighbor": self._anchor_pair(
                candidate.previous_anchor, incoming.previous_anchor
            ),
            "next_neighbor": self._anchor_pair(
                candidate.next_anchor, incoming.next_anchor
            ),
            "geometry_style": self._anchor_pair(
                candidate.geometry_style, incoming.geometry_style
            ),
        }
        present: dict[str, float] = {}
        missing: dict[str, str] = {}
        for name, (value, reason) in raw.items():
            if value is None:
                missing[name] = (reason or MissingReason.MODEL_UNAVAILABLE).value
            else:
                present[name] = value
        return present, missing

    def score_pair(
        self, candidate: LogicalUnitFingerprint, incoming: LogicalUnitFingerprint
    ) -> tuple[float, dict[str, float], dict[str, str]]:
        """The weighted mean over signals that have values.

        Renormalising over available weight -- rather than dividing by 1.0 with
        zeros in the gaps -- is what §N4.4 requires. The alternative caps a prose
        unit with no clause number at 0.85 and makes the 0.92 bar unreachable.
        """
        present, missing = self._signals(candidate, incoming)
        available = sum(self.weights[name] for name in present)
        if available <= 0.0:
            return 0.0, present, missing
        score = sum(present[name] * self.weights[name] for name in present) / available
        return score, present, missing

    # -- resolution -------------------------------------------------------

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
            ((self.score_pair(candidate, incoming), candidate) for candidate in previous),
            key=lambda item: (-item[0][0], item[1].logical_id),
        )
        (best_score, best_signals, best_missing), best = scored[0]
        runner_up = scored[1][0][0] if len(scored) > 1 else 0.0
        runner_up_id = scored[1][1].logical_id if len(scored) > 1 else None

        return self.decide_pair(
            incoming=incoming,
            partner=best,
            score=best_score,
            signals=best_signals,
            missing=best_missing,
            runner_up=runner_up,
            runner_up_id=runner_up_id,
            seed_logical_id=seed_logical_id,
        )

    def decide_pair(
        self,
        *,
        incoming: LogicalUnitFingerprint,
        partner: LogicalUnitFingerprint,
        score: float,
        signals: dict[str, float],
        missing: dict[str, str],
        runner_up: float,
        runner_up_id: str | None,
        seed_logical_id: str | None,
    ) -> LogicalIdentityDecision:
        """Apply §N15.4's bands to one candidate pair.

        Split out from `resolve` because the window matching in
        `assign_one_to_one` has already chosen *who* pairs with whom; it needs
        the bands applied to that pair, not a fresh search for the best one.
        Letting it call `resolve` was the bug: `resolve` re-picked the highest
        scorer and handed the same old unit to two new ones, which is the exact
        thing §N15.3 exists to prevent.
        """
        best = partner
        best_score = score
        best_signals = signals
        best_missing = missing

        absent_critical = sorted(CRITICAL_IDENTITY_SIGNALS & set(best_missing))
        if absent_critical:
            return LogicalIdentityDecision(
                match=LogicalMatch.AMBIGUOUS,
                logical_id=None,
                score=best_score,
                signals=best_signals,
                missing=best_missing,
                reason=(
                    "critical signal(s) "
                    + ", ".join(absent_critical)
                    + " had no value; the remaining signals renormalised to "
                    f"{best_score:.2f} would be a confident score built on a "
                    "thin one"
                ),
                candidates=(best.logical_id,),
            )

        if best_score < self.new_threshold:
            return LogicalIdentityDecision(
                match=LogicalMatch.NEW,
                logical_id=seed_logical_id or incoming.logical_id,
                score=best_score,
                signals=best_signals,
                missing=best_missing,
                reason=(
                    f"best candidate scored {best_score:.2f}, below the "
                    f"{self.new_threshold:.2f} floor for continuing an identity"
                ),
            )

        # Two candidates that score alike are the dangerous case: one of them is
        # the continuation and picking the wrong one rewrites the wrong history.
        if runner_up_id is not None and best_score - runner_up < self.tie_band:
            return LogicalIdentityDecision(
                match=LogicalMatch.AMBIGUOUS,
                logical_id=None,
                score=best_score,
                signals=best_signals,
                missing=best_missing,
                reason=(
                    f"two candidates scored within {self.tie_band:.2f} "
                    f"({best_score:.2f} and {runner_up:.2f}); merging would pick "
                    "one history arbitrarily"
                ),
                candidates=(best.logical_id, runner_up_id),
            )

        if best_score < self.merge_threshold:
            return LogicalIdentityDecision(
                match=LogicalMatch.AMBIGUOUS,
                logical_id=None,
                score=best_score,
                signals=best_signals,
                missing=best_missing,
                reason=(
                    f"score {best_score:.2f} sits in the review band between "
                    f"{self.new_threshold:.2f} and {self.merge_threshold:.2f}"
                ),
                candidates=(best.logical_id,),
            )

        moved = _path_agreement(best.document_path, incoming.document_path) < 1.0
        return LogicalIdentityDecision(
            match=LogicalMatch.MATCHED,
            logical_id=best.logical_id,
            score=best_score,
            signals=best_signals,
            missing=best_missing,
            reason=f"continues {best.logical_id} at {best_score:.2f}",
            candidates=(best.logical_id,),
            relation=(
                LogicalRelation.MOVED_FROM if moved else LogicalRelation.SAME_AS_VERSION
            ),
        )


def _max_weight_matching(weights: list[list[float]]) -> dict[int, int]:
    """Maximum-weight bipartite matching by the Hungarian method.

    Rows are incoming units, columns are candidates. Returns row -> column for
    the assignment that maximises total weight. The matrix is padded to square
    with zero weight so a row or column with no good partner is simply left
    unmatched rather than forced onto someone.
    """
    rows = len(weights)
    cols = len(weights[0]) if rows else 0
    if not rows or not cols:
        return {}
    size = max(rows, cols)
    # Minimise cost = -weight.
    cost = [
        [-(weights[i][j] if i < rows and j < cols else 0.0) for j in range(size)]
        for i in range(size)
    ]

    inf = float("inf")
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    parent = [0] * (size + 1)
    way = [0] * (size + 1)

    for i in range(1, size + 1):
        parent[0] = i
        j0 = 0
        minv = [inf] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[j0] = True
            i0 = parent[j0]
            delta = inf
            j1 = 0
            for j in range(1, size + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[parent[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if parent[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            parent[j0] = parent[j1]
            j0 = j1

    assignment: dict[int, int] = {}
    for j in range(1, size + 1):
        row = parent[j] - 1
        col = j - 1
        if row < rows and col < cols:
            assignment[row] = col
    return assignment


def assign_one_to_one(
    incoming: list[LogicalUnitFingerprint],
    previous: list[LogicalUnitFingerprint],
    *,
    resolver: LogicalIdentityResolver | None = None,
) -> list[LogicalIdentityDecision]:
    """§N15.3 -- resolve a whole window at once, one old unit to one new unit.

    Resolving each unit independently lets one old clause be claimed as the
    continuation of two different new ones. Both look locally reasonable and the
    result is a history that forked without anyone deciding to fork it. A
    maximum-weight matching over the window makes that impossible.

    The matching decides *who pairs with whom*; the thresholds still decide
    whether a pair is a merge. A pair the matching produced that scores below the
    merge bar comes back AMBIGUOUS or NEW exactly as it would alone -- the
    matching never promotes a weak pair just because it was the best left over.
    """
    engine = resolver or LogicalIdentityResolver()
    if not incoming:
        return []
    if not previous:
        return [engine.resolve(unit, []) for unit in incoming]

    scores = [
        [engine.score_pair(candidate, unit) for candidate in previous]
        for unit in incoming
    ]
    assignment = _max_weight_matching([[cell[0] for cell in row] for row in scores])

    decisions: list[LogicalIdentityDecision] = []
    for index, unit in enumerate(incoming):
        column = assignment.get(index)
        if column is None:
            decisions.append(engine.resolve(unit, []))
            continue

        # The runner-up is the best candidate that is still *available*. A
        # candidate the matching gave to another row is not competition for this
        # one, and counting it would fire the tie guard on a pair the global
        # assignment had already resolved confidently.
        taken = {col for row, col in assignment.items() if row != index}
        rivals = [
            (scores[index][col][0], previous[col].logical_id)
            for col in range(len(previous))
            if col != column and col not in taken
        ]
        runner_up, runner_up_id = max(rivals, default=(0.0, None))

        score, signals, missing = scores[index][column]
        decisions.append(
            engine.decide_pair(
                incoming=unit,
                partner=previous[column],
                score=score,
                signals=signals,
                missing=missing,
                runner_up=runner_up,
                runner_up_id=runner_up_id,
                seed_logical_id=unit.logical_id,
            )
        )
    return decisions
