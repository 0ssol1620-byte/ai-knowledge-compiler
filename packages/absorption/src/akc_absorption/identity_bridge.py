"""Where the alignment layer meets `akc_cir.identity`, and stops.

Contract A: the alignment signals go into the existing seven-signal system *as
additional signals*, and "final stable-ID assignment stays with
`akc_cir.identity` (§9.6) -- Protected Core untouched."

This module is the whole of that boundary. It subclasses
`LogicalIdentityResolver` from outside the core package and overrides one
private hook, `_signals`, which is the single place the core asks "what do you
know about this pair?". Everything after that -- availability-aware
renormalisation in `score_pair`, the critical-signal abstention, the tie band,
the 0.92 and 0.75 bands, the one-to-one matching in `assign_one_to_one` -- runs
unchanged and unread by this file.

Three properties follow, and the tests assert all three:

1. **With no alignment evidence the challenger is CURRENT, exactly.** Every
   alignment signal reports absent, `score_pair` renormalises over the core
   weights alone, and the core weights were scaled by one common factor, so the
   ratios and therefore the score are identical.
2. **Alignment evidence cannot rescue a missing critical signal.** The
   abstention in `decide_pair` reads `CRITICAL_IDENTITY_SIGNALS`, which this
   module does not touch and does not extend.
3. **No core signal is suppressed.** The override adds keys; it never removes
   one the base computed. Suppressing a core signal would be replacing the
   core's judgement rather than adding to it.
"""

from __future__ import annotations

from akc_cir.identity import (
    IDENTITY_SIGNAL_WEIGHTS,
    LogicalIdentityResolver,
    LogicalUnitFingerprint,
)

from .alignment import ALIGNMENT_SIGNAL_NAMES, AlignmentContext, compatibility
from .element_model import ElementIndex
from .flags import ABSORB_ALIGNMENT_DIFF, require_flag

__all__ = [
    "ALIGNMENT_SHARE",
    "ALIGNMENT_SIGNAL_SHARES",
    "AlignmentAwareResolver",
    "extended_weights",
]

#: How much of the total weight the five alignment signals hold between them.
#:
#: **Uncalibrated.** Blueprint §9.4 says the thresholds of this layer are
#: uncalibrated and that the Knowledge Evolution Suite is what decides them, so
#: this is a bootstrap value chosen before any result and frozen for the run.
#: It is not swept against the fixture: tuning a weight on the set the arms are
#: scored on is the thing §0.9 forbids, and a number tuned that way could not be
#: reported as a measurement afterwards.
ALIGNMENT_SHARE = 0.30

#: How that share splits between the five. Content carries the most because it
#: is the signal that separates a move from an edit; context the least because
#: it is derived from a pre-pass and is the least independent of the others.
ALIGNMENT_SIGNAL_SHARES: dict[str, float] = {
    "align_type": 0.20,
    "align_spatial": 0.20,
    "align_structural": 0.20,
    "align_content": 0.30,
    "align_context": 0.10,
}


def extended_weights(share: float = ALIGNMENT_SHARE) -> dict[str, float]:
    """The seven core weights scaled down, plus the five alignment weights.

    Scaling every core weight by one factor is what preserves property 1 above.
    The core scorer renormalises over available weight, so a pair with no
    alignment evidence divides `0.7 * core` by `0.7 * available` and lands on
    the number CURRENT would have produced.
    """
    if not 0.0 <= share < 1.0:
        raise ValueError("the alignment share must sit in [0, 1)")
    weights = {name: value * (1.0 - share) for name, value in IDENTITY_SIGNAL_WEIGHTS.items()}
    for name in ALIGNMENT_SIGNAL_NAMES:
        weights[name] = ALIGNMENT_SIGNAL_SHARES[name] * share
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9:  # pragma: no cover - guarded by the shares summing to 1
        raise ValueError(f"extended weights must sum to 1.0, got {total}")
    return weights


class AlignmentAwareResolver(LogicalIdentityResolver):
    """`LogicalIdentityResolver` with §9.3's signals added to its inputs.

    The two element indices are the before and after sides, joined to the core's
    fingerprints by `logical_id`. A fingerprint whose logical id is in neither
    index simply gets no alignment signals, which is the honest reading: the
    alignment layer has nothing to say about a unit it never saw.
    """

    def __init__(
        self,
        *,
        before_index: ElementIndex,
        after_index: ElementIndex,
        context: AlignmentContext | None = None,
        share: float = ALIGNMENT_SHARE,
        enabled: frozenset[str] = frozenset(ALIGNMENT_SIGNAL_NAMES),
        env: dict[str, str] | None = None,
    ) -> None:
        require_flag(ABSORB_ALIGNMENT_DIFF, env)
        unknown = enabled - frozenset(ALIGNMENT_SIGNAL_NAMES)
        if unknown:
            raise ValueError(f"unknown alignment signals: {sorted(unknown)}")
        super().__init__(weights=extended_weights(share))
        self._before_index = before_index
        self._after_index = after_index
        self._context = context or AlignmentContext.build(before_index, after_index)
        self._enabled = enabled

    @property
    def alignment_context(self) -> AlignmentContext:
        return self._context

    def _signals(
        self, candidate: LogicalUnitFingerprint, incoming: LogicalUnitFingerprint
    ) -> tuple[dict[str, float], dict[str, str]]:
        present, missing = super()._signals(candidate, incoming)

        before = self._before_index.by_logical_id.get(candidate.logical_id)
        after = self._after_index.by_logical_id.get(incoming.logical_id)
        if before is None or after is None:
            for name in ALIGNMENT_SIGNAL_NAMES:
                missing[name] = "NOT_APPLICABLE"
            return present, missing

        align_present, align_missing, _tier = compatibility(
            before,
            after,
            before_index=self._before_index,
            after_index=self._after_index,
            context=self._context,
            enabled=self._enabled,
        )
        # Adds keys, never removes one the core produced. See property 3.
        present.update(align_present)
        missing.update(align_missing)
        return present, missing
