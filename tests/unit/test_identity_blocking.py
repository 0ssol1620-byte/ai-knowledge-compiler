"""§N15.1 sparse blocking must never change a decision, only its cost.

The blocking index chooses the order candidates are examined in, never the
candidate set, so every decision has to equal the brute-force scan it
replaced -- same match, same id, same score to the last bit, same reason
strings. The first test here holds the implementation to that on hundreds of
randomised corpora; the negative tests then sabotage the blocking layer on
purpose to prove the harness can fail when the guarantee is broken.
"""

from __future__ import annotations

import random

import pytest
from akc_cir.identity import (
    BlockingCandidateIndex,
    LogicalIdentityDecision,
    LogicalIdentityResolver,
    LogicalMatch,
    LogicalUnitFingerprint,
    resolve_units,
)

_WORDS = [
    "warranty", "coverage", "shipping", "carrier", "parts", "labour",
    "delivery", "scope", "claims", "remedies", "rates", "overview",
    "two", "three", "years", "consumables", "cosmetic",
]


# --------------------------------------------------------------------------
# The oracle: resolve() as it was written before blocking -- public
# primitives only, verbatim logic.
# --------------------------------------------------------------------------


def _legacy_resolve(
    resolver: LogicalIdentityResolver,
    incoming: LogicalUnitFingerprint,
    previous: list[LogicalUnitFingerprint],
    seed: str | None = None,
) -> LogicalIdentityDecision:
    if not previous:
        return LogicalIdentityDecision(
            match=LogicalMatch.NEW,
            logical_id=seed or incoming.logical_id,
            score=0.0,
            reason="no prior version to continue from",
        )
    scored = sorted(
        ((resolver.score_pair(candidate, incoming), candidate) for candidate in previous),
        key=lambda item: (-item[0][0], item[1].logical_id),
    )
    (best_score, best_signals, best_missing), best = scored[0]
    runner_up = scored[1][0][0] if len(scored) > 1 else 0.0
    runner_up_id = scored[1][1].logical_id if len(scored) > 1 else None
    return resolver.decide_pair(
        incoming=incoming,
        partner=best,
        score=best_score,
        signals=best_signals,
        missing=best_missing,
        runner_up=runner_up,
        runner_up_id=runner_up_id,
        seed_logical_id=seed,
    )


def _assert_identical(left: LogicalIdentityDecision, right: LogicalIdentityDecision) -> None:
    """Every field, and the floats bitwise -- approximately-equal hides bugs."""
    assert left.match is right.match
    assert left.logical_id == right.logical_id
    assert left.score == right.score
    assert left.signals == right.signals
    assert left.missing == right.missing
    assert left.reason == right.reason
    assert left.candidates == right.candidates
    assert left.relation is right.relation


# --------------------------------------------------------------------------
# Randomised corpora with every awkward shape the scorer has to survive
# --------------------------------------------------------------------------


def _random_fingerprint(
    rng: random.Random, index: int, lineages: list[str], *, raw_text: bool = False
) -> LogicalUnitFingerprint:
    def maybe(value: str) -> str:
        roll = rng.random()
        if roll < 0.15:
            return ""
        if roll < 0.20:
            return "   "
        return value

    words = [rng.choice(_WORDS) for _ in range(rng.randrange(0, 14))]
    text = " ".join(words)
    section = f"{rng.randrange(1, 10)}.{rng.randrange(1, 9)}"
    path = tuple(
        rng.choice(_WORDS) for _ in range(rng.randrange(0, 4))
    )
    neighbours = tuple(
        f"{rng.randrange(1, 10)}.{rng.randrange(1, 9)} {rng.choice(_WORDS)}"
        for _ in range(2)
    )
    duplicate_roll = rng.randrange(6, 40)
    logical_id = (
        f"ku_{index % max(1, duplicate_roll)}" if rng.random() < 0.08 else f"ku_{index}"
    )
    unit = LogicalUnitFingerprint.of(
        logical_id=logical_id,
        document_path=path,
        anchor=maybe(f"{section} {' '.join(words[:2])}"),
        text=text,
        source_lineage=rng.choice(lineages),
        version_distance=rng.randint(1, 5),
        explicit_identifier=maybe(section),
        previous_anchor=maybe(neighbours[0]),
        next_anchor=maybe(neighbours[1]),
        geometry_style=maybe(rng.choice(["body 10pt indent-0", "heading 14pt"])),
    )
    if raw_text:
        # A directly-constructed fingerprint whose normalized_text was never
        # normalised: the prepared path must treat it exactly as score_pair does.
        unit = LogicalUnitFingerprint(
            logical_id=unit.logical_id,
            document_path=unit.document_path,
            anchor=unit.anchor,
            normalized_text=f"  {text}  ".upper(),
            source_lineage=unit.source_lineage,
            version_distance=unit.version_distance,
            explicit_identifier=unit.explicit_identifier,
            previous_anchor=unit.previous_anchor,
            next_anchor=unit.next_anchor,
            geometry_style=unit.geometry_style,
        )
    return unit


def _random_case(rng: random.Random) -> tuple[
    LogicalUnitFingerprint, list[LogicalUnitFingerprint],
]:
    lineages = ["src_doc_a", "src_doc_b", ""]
    size = rng.choice([0, 1, 2, 3, 5, 8, 13, 21, 34])
    previous = [
        _random_fingerprint(rng, i, lineages, raw_text=rng.random() < 0.2)
        for i in range(size)
    ]
    incoming = _random_fingerprint(rng, 9000 + rng.randrange(50), lineages)
    return incoming, previous


# --------------------------------------------------------------------------
# Equivalence — hundreds of random cases, three paths, one answer each
# --------------------------------------------------------------------------


def test_blocking_matches_brute_force_on_random_corpora() -> None:
    """Same input, same decision: fresh index, shared index, and legacy scan."""
    rng = random.Random(20260823)
    cases = 400
    mismatches: list[str] = []
    for step in range(cases):
        incoming, previous = _random_case(rng)
        seed = f"ku_seed_{step}" if step % 7 == 0 else None
        resolver = LogicalIdentityResolver()

        expected = _legacy_resolve(resolver, incoming, previous, seed=seed)
        fresh = resolver.resolve(incoming, previous, seed_logical_id=seed)
        _assert_identical(expected, fresh)

        if previous:
            shared_index = BlockingCandidateIndex(previous)
            with_index = resolver.resolve(
                incoming, previous, seed_logical_id=seed, index=shared_index
            )
            _assert_identical(expected, with_index)

            # resolve_units seeds from each unit's own logical id, which is
            # its contract; compare it against the same-contract oracle.
            batch = resolve_units([incoming], previous, resolver=resolver)[0]
            _assert_identical(
                _legacy_resolve(resolver, incoming, previous,
                                seed=incoming.logical_id),
                batch,
            )

        if fresh.match != expected.match or fresh.score != expected.score:
            mismatches.append(f"case {step}")

    assert cases >= 300
    assert not mismatches, mismatches


def test_a_shared_index_stays_correct_across_many_incoming_units() -> None:
    """One corpus, many units against it: reuse must not drift per unit."""
    rng = random.Random(99)
    lineages = ["src_one", "src_two", ""]
    previous = [_random_fingerprint(rng, i, lineages) for i in range(25)]
    incoming = [_random_fingerprint(rng, 500 + i, lineages) for i in range(30)]
    resolver = LogicalIdentityResolver()

    index = BlockingCandidateIndex(previous)
    for unit in incoming:
        expected = _legacy_resolve(resolver, unit, previous, seed=unit.logical_id)
        actual = resolver.resolve(unit, previous, seed_logical_id=unit.logical_id, index=index)
        _assert_identical(expected, actual)


def test_the_prepared_scorer_is_bitwise_score_pair_on_random_pairs() -> None:
    """_score_pair_prepared is an implementation detail pinned to score_pair."""
    from akc_cir.identity import _prepare_features

    rng = random.Random(1234)
    lineages = ["src_x", "src_y", ""]
    for _ in range(300):
        left = _random_fingerprint(rng, rng.randrange(200), lineages, raw_text=True)
        right = _random_fingerprint(rng, rng.randrange(200, 400), lineages, raw_text=True)
        resolver = LogicalIdentityResolver()

        score, signals, missing = resolver.score_pair(left, right)
        p_score, p_signals, p_missing = resolver._score_pair_prepared(
            _prepare_features(left), _prepare_features(right)
        )

        assert p_score == score
        assert p_signals == signals
        assert p_missing == missing


def test_the_upper_bound_never_underestimates_the_true_score() -> None:
    """Admissibility is the whole safety argument; check it pair by pair."""
    from akc_cir.identity import _prepare_features

    rng = random.Random(5678)
    lineages = ["src_x", "src_y", ""]
    for _ in range(300):
        left = _random_fingerprint(rng, rng.randrange(200), lineages)
        right = _random_fingerprint(rng, rng.randrange(200, 400), lineages)
        resolver = LogicalIdentityResolver()
        bound = resolver._score_upper_bound(
            _prepare_features(left), _prepare_features(right)
        )
        score, _, _ = resolver.score_pair(left, right)
        assert 0.0 <= bound <= 1.0
        assert bound >= score - 1e-12


# --------------------------------------------------------------------------
# Fallbacks and guards
# --------------------------------------------------------------------------


def test_an_empty_corpus_keeps_the_plain_new_fallback_through_resolve_units() -> None:
    resolver = LogicalIdentityResolver()
    unit = LogicalUnitFingerprint.of(
        logical_id="ku_seed",
        document_path=("Doc",),
        anchor="4.2 Exceptions",
        text="The warranty covers parts and labour.",
    )
    decisions = resolve_units([unit], [], resolver=resolver)

    assert len(decisions) == 1
    assert decisions[0].match is LogicalMatch.NEW
    assert decisions[0].logical_id == "ku_seed"
    assert decisions[0].reason == "no prior version to continue from"


def test_blocking_keys_that_hit_nothing_still_resolve_like_brute_force() -> None:
    """A unit unrelated to the whole corpus: no key hits, NEW either way."""
    resolver = LogicalIdentityResolver()
    previous = [
        LogicalUnitFingerprint.of(
            logical_id="ku_warranty",
            document_path=("Warranty", "Coverage"),
            anchor="4.2 Exceptions",
            text="The warranty covers parts and labour for two years.",
            source_lineage="src_a",
            explicit_identifier="4.2",
            neighbour_anchors=("4.1 Scope", "4.3 Claims"),
            geometry_style="body 10pt",
        )
    ]
    stranger = LogicalUnitFingerprint.of(
        logical_id="ku_stranger",
        document_path=("Privacy", "Retention"),
        anchor="11.9 Retention schedule",
        text="Zebra quixotic jumps over sleepy fences nightly, very oddly indeed.",
        source_lineage="src_b",
        explicit_identifier="11.9",
        neighbour_anchors=("11.8 Notice", "12.0 Disposal"),
        geometry_style="body 11pt indent-3",
    )

    expected = _legacy_resolve(resolver, stranger, previous)
    actual = resolver.resolve(stranger, previous, index=BlockingCandidateIndex(previous))
    _assert_identical(expected, actual)
    assert actual.match is LogicalMatch.NEW


def test_an_index_over_a_different_corpus_is_refused() -> None:
    resolver = LogicalIdentityResolver()
    units = lambda start, n: [  # noqa: E731
        LogicalUnitFingerprint.of(
            logical_id=f"ku_{i}", document_path=("D",), anchor=f"{i}.0 x", text=f"unit {i}"
        )
        for i in range(start, start + n)
    ]
    wrong_index = BlockingCandidateIndex(units(100, 5))
    try:
        resolver.resolve(units(0, 1)[0], units(0, 4), index=wrong_index)
    except ValueError as error:
        assert "different corpus" in str(error)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("mismatched index/corpus lengths were accepted")


def test_resolution_is_repeatable_under_the_same_inputs() -> None:
    rng = random.Random(31)
    incoming, previous = _random_case(rng)
    resolver = LogicalIdentityResolver()
    once = resolver.resolve(incoming, previous)
    twice = resolver.resolve(incoming, previous)
    _assert_identical(once, twice)


# --------------------------------------------------------------------------
# Negative checks — sabotage the blocking layer, watch the harness catch it
# --------------------------------------------------------------------------


def _sabotage_check(sabotage) -> int:
    """Run random equivalence cases against a sabotaged resolver.

    Returns how many decisions diverged from brute force. The sabotages are
    real defects of the kind this test file exists to catch; if any of them
    slips through undetected, the equivalence harness is decoration.
    """
    rng = random.Random(777)
    diverged = 0
    for _ in range(120):
        incoming, previous = _random_case(rng)
        resolver = LogicalIdentityResolver()
        expected = _legacy_resolve(resolver, incoming, previous)
        actual = sabotage(incoming, previous)
        if (
            actual.match != expected.match
            or actual.logical_id != expected.logical_id
            or actual.score != expected.score
            or actual.reason != expected.reason
        ):
            diverged += 1
    return diverged


def test_an_inadmissible_upper_bound_is_caught_by_the_equivalence_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defect: the screening bound under-reports, so the walk stops too early."""
    import akc_cir.identity as identity_module

    real_bound = identity_module._pair_score_upper_bound

    def inadmissible_bound(candidate, incoming, weights):
        return min(real_bound(candidate, incoming, weights), 0.05)

    monkeypatch.setattr(
        identity_module, "_pair_score_upper_bound", inadmissible_bound
    )

    def sabotage(incoming, previous):
        resolver = LogicalIdentityResolver()
        return resolver.resolve(incoming, previous)

    diverged = _sabotage_check(sabotage)
    assert diverged > 0, (
        "an under-estimating bound changed decisions but the harness saw "
        "nothing: the equivalence checks cannot be trusted"
    )


def test_a_key_order_violation_is_caught_by_the_equivalence_harness() -> None:
    """Defect: candidates examined out of bound order while the stop rule stays."""

    class _ScrambledIndex(BlockingCandidateIndex):
        def examination_order(self, incoming, resolver):
            prepared, order = super().examination_order(incoming, resolver)
            scrambled = list(order)
            rng = random.Random(len(scrambled))
            rng.shuffle(scrambled)
            return prepared, scrambled

    def sabotage(incoming, previous):
        resolver = LogicalIdentityResolver()
        return resolver.resolve(incoming, previous, index=_ScrambledIndex(previous))

    diverged = _sabotage_check(sabotage)
    assert diverged > 0, (
        "scrambling the examination order broke the stop rule but the "
        "harness saw nothing: the equivalence checks cannot be trusted"
    )
