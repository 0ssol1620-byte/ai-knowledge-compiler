"""Integration: raw bytes and a canonical document in, a typed compiled state out.

This is the deterministic single reduction the ruling asks for. The lanes above
it run in parallel and each owns a slice of the fact space; this module is where
their output becomes one answer, and it is deliberately the only place that
decides anything.

What it produces, per revision:

    facts        every source fact, in every state, from every registered
                 extractor. Nothing is filtered out here — a filtered fact is an
                 invisible one.
    chain        the four links resolved per represented fact
    complete     whether the scope may be called locally complete
    faithful     whether the state may be called source-faithful CURRENT

And across a revision pair, the typed delta and the invalidation set.

The one design decision worth defending: **`compile_state` never raises.** The
gate raises; the compile reports. A compile that dies on an unresolved fact
cannot count unresolved facts, and a study that cannot count them is measuring
the absence of crashes rather than the presence of losses. The founder's
fail-closed requirement is satisfied by `faithful` being False and by
`assert_faithful` refusing — not by the pipeline falling over.

Lanes 2, 3 and 4 are imported defensively and their absence is reported rather
than assumed away. An extractor set that silently ran with nothing registered
would score every document as perfectly clean, which is the worst failure
available here: it is indistinguishable from success.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

try:  # loaded as a package member
    from . import ir
except ImportError:  # loaded flat
    import ir

#: Optional at import time because the lanes land independently. Required at run
#: time by `missing_lanes`, which the protocol's gates read.
_OPTIONAL = ("reference", "metadata", "fingerprint")


def _import(name: str) -> Any | None:
    """Package-qualified first, flat second.

    Both call styles are live in this namespace and the flat one is the older.
    Trying only one makes a present module look absent, and an absent extractor
    does not raise — it quietly produces no facts, which reads as a clean
    document. Import bookkeeping must never be able to manufacture a pass.
    """
    for candidate in (f"{__package__}.{name}" if __package__ else None, name):
        if candidate is None:
            continue
        try:
            return importlib.import_module(candidate)
        except ImportError:
            continue
    return None


def load_lanes() -> dict[str, Any]:
    """Import whatever lanes exist. Importing a lane registers its extractor."""
    loaded: dict[str, Any] = {}
    for name in _OPTIONAL:
        loaded[name] = _import(name)
    #: the core is not optional. If it is missing the run is not degraded, it is
    #: wrong, and it should fail here rather than produce an empty fact list.
    core = _import("core_extractor")
    if core is None:
        raise ImportError(
            "core_extractor is absent. A run without it would produce no content, "
            "structure or provenance facts and would score every document clean."
        )
    loaded["core"] = core
    return loaded


def missing_lanes() -> tuple[str, ...]:
    loaded = load_lanes()
    return tuple(name for name in _OPTIONAL if loaded[name] is None)


def _fingerprinter() -> ir.Fingerprinter | None:
    lanes = load_lanes()
    module = lanes.get("fingerprint")
    return getattr(module, "fingerprint", None) if module else None


def _dependencies() -> ir.DependencyResolver | None:
    lanes = load_lanes()
    module = lanes.get("fingerprint")
    if module is None:
        return None
    for name in ("dependency_keys", "dependency_edges"):
        resolver = getattr(module, name, None)
        if resolver is not None:
            return resolver
    return None


@dataclass(frozen=True)
class CompiledState:
    """One revision, compiled into typed facts and judged against the chain."""

    source_id: str
    version_id: str
    facts: tuple[ir.SourceFact, ...]
    links: tuple[dict[str, Any], ...]
    tally: dict[str, int]
    unclaimed_kinds: tuple[str, ...]
    lanes_missing: tuple[str, ...]
    broken_chains: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def fail_closed_facts(self) -> tuple[ir.SourceFact, ...]:
        return tuple(fact for fact in self.facts if fact.fail_closed)

    @property
    def complete(self) -> bool:
        """A scope may be called locally complete only with no fail-closed fact.

        Note what this does NOT require: it does not require every kind to be
        represented. A source that contains no dates is complete without an
        EFFECTIVE_TIME fact. What it forbids is a fact that was seen and lost.
        """
        return not self.fail_closed_facts

    @property
    def faithful(self) -> bool:
        """Source-faithful CURRENT: complete, and every chain link resolves.

        The second half is the part SFH1 had no way to check. A state can carry
        no losses and still be unfaithful, because a represented fact whose
        fingerprint or dependency path is absent cannot propagate — it looks
        carried and behaves dropped.
        """
        return self.complete and not self.broken_chains and not self.lanes_missing

    def why_not_faithful(self) -> list[str]:
        reasons: list[str] = []
        if self.lanes_missing:
            reasons.append(
                "extractor lanes absent, so facts they own were never looked for: "
                + ", ".join(self.lanes_missing)
            )
        for fact in self.fail_closed_facts[:8]:
            reasons.append(f"{fact.state} {fact.kind}: {fact.reason}")
        for links in self.broken_chains[:8]:
            absent = [
                name
                for name in ("witness", "representation", "fingerprint", "dependency_path")
                if not links.get(name)
            ]
            reasons.append(f"chain link absent ({', '.join(absent)}) for {links['kind']}")
        return reasons

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "version_id": self.version_id,
            "facts": len(self.facts),
            "tally": self.tally,
            "by_kind": self.by_kind(),
            "complete": self.complete,
            "faithful": self.faithful,
            "why_not_faithful": self.why_not_faithful(),
            "unclaimed_kinds": list(self.unclaimed_kinds),
            "lanes_missing": list(self.lanes_missing),
            "broken_chain_count": len(self.broken_chains),
        }

    def by_kind(self) -> dict[str, dict[str, int]]:
        rows: dict[str, dict[str, int]] = {}
        for fact in self.facts:
            row = rows.setdefault(fact.kind, {state: 0 for state in ir.STATES})
            row[fact.state] += 1
        return dict(sorted(rows.items()))


def compile_state(*, raw: bytes, document: dict[str, Any]) -> CompiledState:
    """Never raises. Reports. The gate below is what refuses."""
    load_lanes()
    facts = tuple(ir.extract_all(raw=raw, document=document))
    fingerprint = _fingerprinter()
    dependencies = _dependencies()

    links: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    for fact in facts:
        resolved = ir.chain(
            fact, raw=raw, fingerprint=fingerprint, dependencies=dependencies
        )
        links.append(resolved)
        if not ir.chain_complete(resolved):
            broken.append(resolved)

    return CompiledState(
        source_id=str(document.get("source_id", "")),
        version_id=str(document.get("version_id", "")),
        facts=facts,
        links=tuple(links),
        tally=ir.tally(facts),
        unclaimed_kinds=ir.unclaimed_kinds(),
        lanes_missing=missing_lanes(),
        broken_chains=tuple(broken),
    )


def assert_faithful(state: CompiledState) -> None:
    """The fail-closed gate. Call this wherever a run wants to say CURRENT."""
    if not state.faithful:
        raise ir.NotSourceFaithful(
            f"{state.source_id}@{state.version_id} is not source-faithful CURRENT: "
            + "; ".join(state.why_not_faithful()[:3])
        )


@dataclass(frozen=True)
class PairResult:
    """A revision pair, typed."""

    before: CompiledState
    after: CompiledState
    delta: Any | None
    invalidates: tuple[str, ...]
    delta_available: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
            "delta_available": self.delta_available,
            "invalidates": list(self.invalidates),
            "invalidates_count": len(self.invalidates),
        }


def compile_pair(
    *,
    before_raw: bytes,
    before_document: dict[str, Any],
    after_raw: bytes,
    after_document: dict[str, Any],
) -> PairResult:
    before = compile_state(raw=before_raw, document=before_document)
    after = compile_state(raw=after_raw, document=after_document)

    lanes = load_lanes()
    module = lanes.get("fingerprint")
    delta_fn = getattr(module, "delta", None) if module else None
    if delta_fn is None:
        #: honest degradation. An empty invalidation set reported as if it were
        #: computed would say "nothing needs rebuilding", which is precisely the
        #: stale-escape failure this programme confirmed four times.
        return PairResult(
            before=before, after=after, delta=None, invalidates=(), delta_available=False
        )

    delta = delta_fn(list(before.facts), list(after.facts))
    #: `invalidate` is the field TypedDelta actually declares. The two fallbacks
    #: are not politeness — a missing field silently yielding an empty set would
    #: report "nothing needs rebuilding", which is the stale escape this
    #: programme confirmed four times. Absence raises instead.
    for name in ("invalidate", "invalidates", "invalidation_keys"):
        keys = getattr(delta, name, None)
        if keys is not None:
            break
    else:
        raise AttributeError(
            f"{type(delta).__name__} declares no invalidation set; an empty one "
            "would be indistinguishable from 'nothing to rebuild'"
        )
    return PairResult(
        before=before,
        after=after,
        delta=delta,
        invalidates=tuple(sorted(keys)),
        delta_available=True,
    )
