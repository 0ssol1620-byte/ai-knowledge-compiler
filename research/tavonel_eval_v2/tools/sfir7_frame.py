#!/usr/bin/env python3
"""SFIR7's frame rule: eligibility, ranking and top-N selection, as pure functions.

SFIR5 measured C=293 qualifying candidates for `git_docs` against a declared
minimum of 750. SFIR6 repairs instruments under an UNCHANGED frame and will
either confirm that shortfall or not. Neither study can distinguish two very
different explanations of a shortfall:

    the SYSTEM cannot produce qualifying revision pairs at that density, or
    the FRAME that was constructed does not contain them.

SFIR7 asks the second question, and the only honest way to ask it is to stop
choosing repositories. This module therefore contains no repository names. It
contains a rule that a *third party's* catalogue, frozen by digest, is fed
through. Whatever comes out is the frame.

The failure mode this module exists to make impossible is one specific act:
adding repositories, or nudging a threshold, until the count clears 750. Three
structural properties do that work, and each is testable:

    1. Nothing here can see a capacity quantity. Eligibility predicates may only
       name fields that exist on `FrameCatalogRecord`, and any predicate naming a
       capacity term is refused. There is no code path from a candidate count
       into a selection decision because there is no parameter to carry one.

    2. N is not chosen. It is *derived* by `derive_n` from three numbers that
       exist for reasons outside this study -- the inherited per-root Git request
       bound, the inherited wall-clock bound, and GitHub's published
       authenticated primary rate limit. `refuse_count_tuned_rule` refuses any
       rule whose declared N is not exactly that arithmetic. A hand-set N is a
       refusal, not a warning.

    3. Ranking is a strict total order or it is a refusal. `select_top_n` builds
       its order from sorted tuples only, and refuses outright if two eligible
       records share a full ranking key. A tie that reaches a tie-break of last
       resort is a tie that some implementation detail would otherwise settle.

NO NETWORK. This module does not import `socket`, `ssl`, `http`, `urllib`,
`requests` or `httpx`, and `test_sfir7_frame.py` reads this file's own bytes to
prove it. The catalogue snapshot arrives as bytes already on disk, pinned by
sha256; acquiring it is a separate, later, authorised act that is NOT part of
SFIR7's design freeze.

Interpreter of record: D:\\CodexProjects\\ai-knowledge-compiler\\.venv\\Scripts\\python.exe
(the bare `python` on PATH resolves `akc_cir` from a different checkout, INC-V2-103).
"""

from __future__ import annotations

import hashlib
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir5_transport as t5  # noqa: E402  -- read only; the inherited total request cap
import sfir6_transport as t6  # noqa: E402  -- read only; the inherited wall-clock bound
from acquisition import sources_sfir4 as sources  # noqa: E402  -- read only

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"
FRAME_SCHEMA = "tavonel.sfir7.external_frame_rule.v1"


class SFIR7Refused(RuntimeError):
    """A rule, a snapshot or a selection that this study will not accept."""


# --------------------------------------------------------------------------
# What a catalogue record is allowed to be
# --------------------------------------------------------------------------
# The field set is closed on purpose. An eligibility predicate may only name a
# field that appears here, so a predicate cannot reach a quantity the catalogue
# does not publish -- and in particular cannot reach anything TAVONEL measured.


@dataclass(frozen=True, slots=True)
class FrameCatalogRecord:
    """One repository as the external catalogue describes it. Nothing added."""

    record_id: str  # the catalogue's own stable identifier; total-order key
    host: str  # e.g. "github"
    namespace: str  # owner / organisation, as the catalogue spells it
    name: str
    primary_language: str  # "" when the catalogue declares none
    spdx_license_id: str  # "" when the catalogue declares none
    created_utc: str  # ISO-8601 date, catalogue-declared
    last_activity_utc: str  # ISO-8601 date, catalogue-declared
    catalog_rank_value: int  # the catalogue's own ordinal; NOT computed here


CATALOG_FIELDS = frozenset(f.name for f in fields(FrameCatalogRecord))

#: The selectable field set, written out rather than only derived, because
#: deriving it means any field added to the projection silently becomes
#: available to a predicate. `host_uuid`, `fork` and `status` exist on the raw
#: publisher record and are deliberately NOT here: the rule was designed blind
#: over exactly these nine fields, and a rule that can reach a tenth is not the
#: rule that was designed blind. A control asserts the two agree.
SELECTABLE_FIELDS = frozenset(
    {
        "record_id",
        "host",
        "namespace",
        "name",
        "primary_language",
        "spdx_license_id",
        "created_utc",
        "last_activity_utc",
        "catalog_rank_value",
    }
)

#: Carried on the raw record for provenance and identity attestation, and
#: forbidden to the selection rule. Naming them is the point -- an omission is
#: invisible, a declared exclusion is not.
PROVENANCE_ONLY_FIELDS = frozenset({"host_uuid", "fork", "status"})

# Substrings that must never appear in a predicate field, a ranking field or an
# N justification. These are the names a capacity quantity travels under in this
# programme. A rule that reaches for one of them is reaching for the answer.
CAPACITY_TERMS = (
    "capacity",
    "candidate",
    "qualifying",
    "qualified",
    "revision_pair",
    "pair_count",
    "c_per_family",
    "q_per_family",
    "min_c",
    "min_q",
    "shortfall",
    "threshold",
    "yield",
)

# The two numerals SFIR7 must be able to prove it did not aim at.
FORBIDDEN_NUMERALS = ("750", "293", "600", "234")


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """An external catalogue, frozen. `sha256` binds the bytes, not the parse."""

    catalog_id: str
    snapshot_uri: str
    snapshot_sha256: str
    snapshot_date_utc: str
    records: tuple[FrameCatalogRecord, ...]


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------

_OPS: Mapping[str, str] = MappingProxyType(
    {
        "eq": "equals",
        "in": "is one of",
        "not_in": "is not one of",
        "on_or_before": "date is on or before",
        "on_or_after": "date is on or after",
        "gte": "integer is at least",
        "lte": "integer is at most",
    }
)

# Every derivation SFIR7 will accept for N. The enum is closed so that "I picked
# it" cannot be spelled as a justification.
N_DERIVATIONS = frozenset({"min_of_rate_limited_and_capped_budget_over_per_root_bound"})

# GitHub's published authenticated primary rate limit, requests per hour. An
# external vendor constant. It is not a TAVONEL choice and it does not move when
# a census comes out badly.
PUBLISHED_GITHUB_AUTHENTICATED_RATE_LIMIT_PER_HOUR = 5000

# --------------------------------------------------------------------------
# Vocabulary reconciliation
#
# The predicates were declared while SFIR6 was blind, which is what makes them
# outcome-independent -- and also means they were written in SPDX's vocabulary
# and our casing, without having seen what the publisher actually wrote. Measured
# against the snapshot (receipts/sfir7-catalog-vocabulary.json, 37,702,060 rows,
# 69 distinct licence values), two spellings do not exist in the catalogue at
# all:
#
#   declared            catalogue       rows
#   GPL-2.0-only        GPL-2.0         338,234
#   GPL-3.0-only        GPL-3.0         653,544
#   LGPL-2.1-only       LGPL-2.1         27,554
#   LGPL-3.0-only       LGPL-3.0         57,403
#
# All four declared spellings matched ZERO rows. Left alone they would have
# silently removed every copyleft repository from the universe and left a roster
# of permissive licences -- smaller, entirely real, and wrong in a way no
# downstream check could see. That is INC-V2-106's shape applied to a filter.
#
# The mapping below is decided on SEMANTIC grounds, not on which spelling yields
# more rows:
#
#   * SPDX 3.0 split the ambiguous `GPL-2.0` into `-only` and `-or-later`. This
#     catalogue predates that and writes the or-later variant with a `+` suffix
#     (`GPL-3.0+`, `LGPL-2.1+`, `LGPL-3.0+` are all present). So in ITS
#     vocabulary, the unsuffixed form denotes exactly what `-only` denotes, and
#     the `+` forms are deliberately NOT mapped in.
#   * The set of ten licence families is unchanged. Nothing was added.
#
# What is eligible did not change. Only the strings did, and only to the ones the
# publisher wrote.
LICENSE_SPELLINGS_IN_THIS_CATALOG: dict[str, tuple[str, ...]] = {
    "GPL-2.0-only": ("GPL-2.0",),
    "GPL-3.0-only": ("GPL-3.0",),
    "LGPL-2.1-only": ("LGPL-2.1",),
    "LGPL-3.0-only": ("LGPL-3.0",),
}

#: The `+` forms mean "or later" and are deliberately excluded, named here so
#: that exclusion is a declared act rather than an omission nobody noticed.
OR_LATER_SPELLINGS_DELIBERATELY_EXCLUDED = ("GPL-3.0+", "LGPL-2.1+", "LGPL-3.0+")

#: Fields compared without regard to case, each for a reason that comes from the
#: field's own domain rather than from our convenience.
#:
#: `spdx_license_id`: SPDX identifiers are matched case-insensitively by the SPDX
#: specification itself, and this catalogue is internally inconsistent about it
#: -- it carries both `MIT` (3,054,331 rows) and `mit` (8,347), `Apache-2.0` and
#: `apache-2.0`, and eleven more such pairs. A case-sensitive match would drop
#: the lowercase rows silently.
#:
#: `host`: the catalogue writes `GitHub`, the charter declared `github`, and
#: these are three proper nouns in a closed set of three.
#:
#: The contrast with INC-V2-109 is deliberate and worth keeping in view. There,
#: case-folding was WRONG, because MediaWiki titles are case-sensitive after the
#: first character and `CD8+` and `Cd8+` are two different pages. Here it is
#: right, because SPDX says so. The same operation, correct in one domain and a
#: defect in the other -- decided by the data's own rules, never by what is
#: convenient.
CASE_INSENSITIVE_FIELDS = frozenset({"spdx_license_id", "host"})


def catalog_spellings(declared_value: str) -> tuple[str, ...]:
    """Every spelling in this catalogue that denotes the declared value."""
    return LICENSE_SPELLINGS_IN_THIS_CATALOG.get(declared_value, (declared_value,))


@dataclass(frozen=True, slots=True)
class EligibilityPredicate:
    """One deterministic test over one catalogue field, decided in advance."""

    field: str
    op: str
    value: Any
    why: str


@dataclass(frozen=True, slots=True)
class RankKey:
    field: str
    descending: bool


@dataclass(frozen=True, slots=True)
class FrameRule:
    catalog_id: str
    snapshot_sha256: str
    predicates: tuple[EligibilityPredicate, ...]
    ranking: tuple[RankKey, ...]
    tie_breaker: str
    n: int
    n_derivation: str
    n_inputs: Mapping[str, int]
    n_justification: str


@dataclass(frozen=True, slots=True)
class FrameSelection:
    protocol_id: str
    schema: str
    catalog_id: str
    snapshot_sha256: str
    eligible_count: int
    n: int
    selected: tuple[FrameCatalogRecord, ...]
    dispositions: Mapping[str, str]


# --------------------------------------------------------------------------
# Snapshot binding
# --------------------------------------------------------------------------


def digest_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def bind_snapshot_bytes(payload: bytes, declared_sha256: str) -> str:
    """Refuse a snapshot whose bytes are not the bytes that were declared.

    Reads bytes. Fetches nothing. The universe is reproducible only if this
    holds, so it is a refusal and not a note in a receipt.
    """
    actual = digest_bytes(payload)
    declared = (
        declared_sha256 if declared_sha256.startswith("sha256:") else f"sha256:{declared_sha256}"
    )
    if actual != declared:
        raise SFIR7Refused(
            f"catalogue snapshot digest does not match: declared {declared}, "
            f"bytes {actual}. An unpinned universe is not a reproducible frame."
        )
    return actual


def read_snapshot_bytes(path: Path) -> bytes:
    """Working-tree bytes, verbatim. No decode, no newline translation.

    INC-V2-105: EOL is determined by counting bytes, never by a shell `grep`.
    """
    return Path(path).read_bytes()


def snapshot_eol(payload: bytes) -> str:
    crlf = payload.count(b"\r\n")
    lf = payload.count(b"\n") - crlf
    if crlf and lf:
        return "MIXED"
    return "CRLF" if crlf else "LF"


# --------------------------------------------------------------------------
# Capacity blindness
# --------------------------------------------------------------------------


def _names_a_capacity_term(text: str) -> str | None:
    lowered = text.casefold()
    for term in CAPACITY_TERMS:
        if term in lowered:
            return term
    return None


def assert_capacity_blind(rule: FrameRule) -> None:
    """Refuse any rule that could have looked at how much the frame will yield.

    Two ways in are closed here: a predicate or ranking key naming a field that
    is not on `FrameCatalogRecord`, and any field or justification naming a capacity
    term. A rule cannot be tuned against a number it cannot name.
    """
    for predicate in rule.predicates:
        if predicate.field not in CATALOG_FIELDS:
            raise SFIR7Refused(
                f"eligibility predicate names {predicate.field!r}, which the external "
                f"catalogue record does not carry. Allowed: {sorted(CATALOG_FIELDS)}"
            )
        if predicate.op not in _OPS:
            raise SFIR7Refused(f"unknown eligibility operator {predicate.op!r}")
        term = _names_a_capacity_term(predicate.field) or _names_a_capacity_term(predicate.why)
        if term is not None:
            raise SFIR7Refused(
                f"eligibility predicate on {predicate.field!r} reaches a capacity term "
                f"({term!r}). Eligibility is decided without any capacity quantity."
            )
    for key in rule.ranking:
        if key.field not in CATALOG_FIELDS:
            raise SFIR7Refused(f"ranking key names {key.field!r}, not a catalogue field")
        term = _names_a_capacity_term(key.field)
        if term is not None:
            raise SFIR7Refused(f"ranking key {key.field!r} reaches a capacity term ({term!r})")
    if rule.tie_breaker not in CATALOG_FIELDS:
        raise SFIR7Refused(f"tie breaker names {rule.tie_breaker!r}, not a catalogue field")


# --------------------------------------------------------------------------
# N: derived, never chosen
# --------------------------------------------------------------------------


def inherited_wall_clock_hours() -> int:
    """Read live from SFIR6's transport, not copied. Editing that turns this red."""
    seconds = int(t6.MAX_TOTAL_WALL_CLOCK_SECONDS)
    if seconds % 3600:
        raise SFIR7Refused(
            f"inherited wall-clock bound {seconds}s is not a whole number of hours; "
            "N's derivation is defined over whole rate-limit hours"
        )
    return seconds // 3600


def inherited_per_root_request_bound() -> int:
    """Read live from the frozen source module, not copied."""
    return int(sources.MAX_GIT_API_REQUESTS_PER_ROOT)


def inherited_total_request_cap() -> int:
    """Read live from SFIR5's transport, not copied.

    The second operational bound. SFIR7's first draft derived N from the wall
    clock alone and produced a roster whose worst case needed 30,000 requests
    against an inherited cap of 12,000 -- a conflict no value satisfied. It is
    resolved by applying the STRONGER of the two bounds that already existed,
    not by raising either. Raising a budget after a census disappoints is a
    tuning act; taking the tighter of two constraints written beforehand is not.
    """
    return int(t5.MAX_TOTAL_REQUESTS)


def derive_n(
    *,
    wall_clock_hours: int,
    published_rate_limit_per_hour: int,
    per_root_request_bound: int,
    inherited_total_request_cap: int,
) -> int:
    """N = floor(min(hours * rate_limit, total_cap) / per_root_request_bound).

    Every input exists for a reason outside this study. The wall-clock bound, the
    per-root request bound and the total request cap are inherited unchanged from
    SFIR4/SFIR5/SFIR6. The rate limit is GitHub's published figure. None of the
    four moves when a capacity number is disappointing, and the arithmetic leaves
    no free parameter.

    The `min` is the whole point. Two operational bounds already constrained this
    study and the first draft honoured only one of them, which is how it arrived
    at a roster the transport could not have finished. Applying the tighter bound
    lowers N. That direction matters: a rule that reduces the roster cannot be
    suspected of having been written to reach a capacity number.

    The rate limit is an UPPER bound, not a guaranteed sustained throughput --
    GitHub enforces secondary limits as well, so execution still paces serially
    and honours `Retry-After`, `remaining` and `reset`.
    """
    for label, value in (
        ("wall_clock_hours", wall_clock_hours),
        ("published_rate_limit_per_hour", published_rate_limit_per_hour),
        ("per_root_request_bound", per_root_request_bound),
        ("inherited_total_request_cap", inherited_total_request_cap),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise SFIR7Refused(f"{label} must be a positive integer, got {value!r}")
    available = min(wall_clock_hours * published_rate_limit_per_hour, inherited_total_request_cap)
    return available // per_root_request_bound


def refuse_count_tuned_rule(rule: FrameRule) -> int:
    """Refuse an N that was picked rather than derived.

    This is the gate the whole lane turns on. `git_docs` measured 293 against
    750; adding roots until the number clears is the forbidden act, and the only
    way to make it structurally impossible is to leave N with no degree of
    freedom. Three things are checked, and each of them can go red on its own:

        the derivation is one this study accepts,
        the declared inputs are the live inherited bounds, and
        the declared N is exactly the arithmetic over those inputs.
    """
    if rule.n_derivation not in N_DERIVATIONS:
        raise SFIR7Refused(
            f"N derivation {rule.n_derivation!r} is not in the closed set "
            f"{sorted(N_DERIVATIONS)}. 'chosen' is not a derivation."
        )
    term = _names_a_capacity_term(rule.n_justification)
    if term is not None:
        raise SFIR7Refused(
            f"N's justification names a capacity term ({term!r}). N is justified "
            "from a transport budget, never from what the frame is hoped to yield."
        )
    for numeral in FORBIDDEN_NUMERALS:
        if re.search(rf"(?<!\d){numeral}(?!\d)", rule.n_justification):
            raise SFIR7Refused(
                f"N's justification cites {numeral}, a figure from the capacity "
                "criterion or from SFIR5's measurement. N is derived without reference to either."
            )
    expected_inputs = {
        "wall_clock_hours": inherited_wall_clock_hours(),
        "published_rate_limit_per_hour": PUBLISHED_GITHUB_AUTHENTICATED_RATE_LIMIT_PER_HOUR,
        "per_root_request_bound": inherited_per_root_request_bound(),
        "inherited_total_request_cap": inherited_total_request_cap(),
    }
    declared_inputs = dict(rule.n_inputs)
    if declared_inputs != expected_inputs:
        raise SFIR7Refused(
            f"N's declared inputs are not the inherited bounds: rule {declared_inputs}, "
            f"live modules {expected_inputs}. An input moved after a result was known."
        )
    expected_n = derive_n(**expected_inputs)
    if rule.n != expected_n:
        raise SFIR7Refused(
            f"N is {rule.n} but its own derivation yields {expected_n}. A hand-set N "
            "is a count chosen against a target, whatever it is called."
        )
    return expected_n


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------


def _as_date(value: Any, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:  # pragma: no cover - message path
        raise SFIR7Refused(f"{label} is not an ISO-8601 date: {value!r}") from exc


def _comparable(value: Any, field: str) -> Any:
    """Fold case only where the field's own domain says case carries no meaning."""
    if field in CASE_INSENSITIVE_FIELDS and isinstance(value, str):
        return value.casefold()
    return value


def _accepted_values(predicate: EligibilityPredicate) -> tuple[Any, ...]:
    """Expand each declared value into the spellings this catalogue uses for it."""
    expanded: list[Any] = []
    for value in tuple(predicate.value):
        if predicate.field == "spdx_license_id" and isinstance(value, str):
            expanded.extend(catalog_spellings(value))
        else:
            expanded.append(value)
    return tuple(_comparable(value, predicate.field) for value in expanded)


def _evaluate(predicate: EligibilityPredicate, record: FrameCatalogRecord) -> bool:
    observed = getattr(record, predicate.field)
    op = predicate.op
    if op == "eq":
        return _comparable(observed, predicate.field) == _comparable(
            predicate.value, predicate.field
        )
    if op == "in":
        return _comparable(observed, predicate.field) in _accepted_values(predicate)
    if op == "not_in":
        return _comparable(observed, predicate.field) not in _accepted_values(predicate)
    if op == "on_or_before":
        return _as_date(observed, label=predicate.field) <= _as_date(predicate.value, label="value")
    if op == "on_or_after":
        return _as_date(observed, label=predicate.field) >= _as_date(predicate.value, label="value")
    if op == "gte":
        return int(observed) >= int(predicate.value)
    if op == "lte":
        return int(observed) <= int(predicate.value)
    raise SFIR7Refused(f"unknown eligibility operator {op!r}")


def apply_eligibility(
    snapshot: CatalogSnapshot, rule: FrameRule
) -> tuple[tuple[FrameCatalogRecord, ...], dict[str, str]]:
    """Every record gets a disposition: ELIGIBLE, or the first predicate it failed.

    Predicates are applied in declared order and the first failure is recorded,
    so the dispositions are a function of the rule's own text rather than of
    iteration order.
    """
    assert_capacity_blind(rule)
    eligible: list[FrameCatalogRecord] = []
    dispositions: dict[str, str] = {}
    for record in snapshot.records:
        verdict = "ELIGIBLE"
        for predicate in rule.predicates:
            if not _evaluate(predicate, record):
                verdict = f"REJECTED_{predicate.field}_{predicate.op}"
                break
        dispositions[record.record_id] = verdict
        if verdict == "ELIGIBLE":
            eligible.append(record)
    return tuple(eligible), dispositions


# --------------------------------------------------------------------------
# Documentation-file eligibility
# --------------------------------------------------------------------------

DOC_EXTENSIONS = tuple(sources.SOURCE_POOLS["git_docs"]["extensions"])


def is_documentation_path(path: str) -> bool:
    """The inherited extension allow-list, read live rather than restated.

    Documentation eligibility is a property of a path, not of a repository, and
    it is deliberately NOT one of the catalogue predicates: a catalogue does not
    know what is in a tree, and pretending it does would smuggle a TAVONEL
    judgement into an external universe.
    """
    lowered = str(path).casefold()
    return any(lowered.endswith(extension) for extension in DOC_EXTENSIONS)


# --------------------------------------------------------------------------
# Ranking and selection
# --------------------------------------------------------------------------


def _ranking_key(record: FrameCatalogRecord, rule: FrameRule) -> tuple[Any, ...]:
    parts: list[Any] = []
    for key in rule.ranking:
        observed = getattr(record, key.field)
        if key.descending:
            if isinstance(observed, int) and not isinstance(observed, bool):
                parts.append(-observed)
            else:
                raise SFIR7Refused(
                    f"ranking key {key.field!r} is descending but is not an integer; "
                    "descending order over non-integers has no total-order definition here"
                )
        else:
            parts.append(observed)
    parts.append(getattr(record, rule.tie_breaker))
    return tuple(parts)


def assert_strict_total_order(
    records: Sequence[FrameCatalogRecord], rule: FrameRule
) -> None:
    """Refuse if any two eligible records share a full ranking key.

    A tie that survives the declared tie-breaker would be settled by whatever
    order the records happened to arrive in. That is the defect class this
    programme has paid for repeatedly: a rule that looks deterministic because
    the input happened to be sorted.
    """
    seen: dict[tuple[Any, ...], str] = {}
    for record in records:
        key = _ranking_key(record, rule)
        if key in seen:
            raise SFIR7Refused(
                f"ranking key {key!r} is shared by {seen[key]!r} and {record.record_id!r}. "
                "A tie the declared tie-breaker cannot settle is not a deterministic frame."
            )
        seen[key] = record.record_id


def select_top_n(snapshot: CatalogSnapshot, rule: FrameRule) -> FrameSelection:
    """The frame. Deterministic given the snapshot bytes and the rule."""
    if rule.catalog_id != snapshot.catalog_id:
        raise SFIR7Refused(
            f"rule is written for catalogue {rule.catalog_id!r} but the snapshot is "
            f"{snapshot.catalog_id!r}"
        )
    if rule.snapshot_sha256 != snapshot.snapshot_sha256:
        raise SFIR7Refused(
            f"rule binds snapshot {rule.snapshot_sha256} but was given "
            f"{snapshot.snapshot_sha256}. The universe is bound by digest or it is not bound."
        )
    n = refuse_count_tuned_rule(rule)
    eligible, dispositions = apply_eligibility(snapshot, rule)
    assert_strict_total_order(eligible, rule)
    ordered = tuple(sorted(eligible, key=lambda record: _ranking_key(record, rule)))
    return FrameSelection(
        protocol_id=PROTOCOL_ID,
        schema=FRAME_SCHEMA,
        catalog_id=snapshot.catalog_id,
        snapshot_sha256=snapshot.snapshot_sha256,
        eligible_count=len(eligible),
        n=n,
        selected=ordered[:n],
        dispositions=MappingProxyType(dispositions),
    )


def selection_is_short(selection: FrameSelection) -> bool:
    """The eligible pool was smaller than N.

    This is reported, never repaired. Widening a predicate because the pool came
    out small is the same forbidden act as adding a root because C came out at
    293 -- it is just performed one stage earlier.
    """
    return selection.eligible_count < selection.n


def frame_fingerprint(selection: FrameSelection) -> str:
    """A digest over exactly what was selected, in the order it was selected."""
    payload = "\n".join(
        f"{record.host}/{record.namespace}/{record.name}#{record.record_id}"
        for record in selection.selected
    )
    return digest_bytes(payload.encode("utf-8"))


def module_source_bytes() -> bytes:
    return Path(__file__).read_bytes()


NETWORK_TOKENS = (
    "import socket",
    "import ssl",
    "import http",
    "import urllib",
    "import requests",
    "import httpx",
    "urlopen",
    "http.client",
    "requests.get",
)


def declares_no_network() -> bool:
    """This module's own bytes, checked for any way out to a network.

    Written as a function so the control in the test suite reads this file
    rather than trusting a comment. `NETWORK_TOKENS` appearing inside this tuple
    is not an import, so the scan skips the tuple's own definition.
    """
    text = module_source_bytes().decode("utf-8")
    marker = "NETWORK_TOKENS = ("
    start = text.index(marker)
    end = text.index(")", start)
    scanned = text[:start] + text[end:]
    return not any(token in scanned for token in NETWORK_TOKENS)


def iter_selected_full_names(selection: FrameSelection) -> Iterable[str]:
    for record in selection.selected:
        yield f"{record.namespace}/{record.name}"


# --------------------------------------------------------------------------
# The declared rule
# --------------------------------------------------------------------------
# Frozen in code rather than in prose so that a test can assert it, and so that
# changing it is a diff someone has to sign rather than an edit to a document.

SPDX_ALLOWLIST = (
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "MIT",
    "ISC",
    "MPL-2.0",
    "GPL-2.0-only",
    "GPL-3.0-only",
    "LGPL-2.1-only",
    "LGPL-3.0-only",
)

MINIMUM_HISTORY_AGE_DAYS = 1095  # three years, so a repository can have a past
MAXIMUM_ACTIVITY_GAP_DAYS = 365  # catalogue-declared recency, not a measured yield


def _shift(iso_date: str, *, days: int) -> str:
    from datetime import timedelta

    return (_as_date(iso_date, label="snapshot_date_utc") - timedelta(days=days)).isoformat()


def declared_rule(*, catalog_id: str, snapshot_sha256: str, snapshot_date_utc: str) -> FrameRule:
    """SFIR7's frame rule, computable before any capacity datum exists.

    Read the predicates as a list of things the *catalogue* already says. None of
    them is a statement about what TAVONEL will find in a tree. The one thing a
    reader might expect and will not find is an exclusion of SFIR1-SFIR4's twenty
    repositories: excluding them would be TAVONEL curating the external universe
    again, which is the exact habit SFIR7 exists to stop. Whether the external
    rule happens to reselect any of them is a diagnostic, not an input.
    """
    predicates = (
        EligibilityPredicate(
            field="host",
            op="eq",
            value="github",
            why=(
                "the inherited git_docs adapter addresses one host; changing hosts "
                "would confound the frame question with an instrument change"
            ),
        ),
        EligibilityPredicate(
            field="spdx_license_id",
            op="in",
            value=SPDX_ALLOWLIST,
            why=(
                "an SPDX identifier the catalogue itself declares, from a list "
                "fixed before the snapshot was taken"
            ),
        ),
        EligibilityPredicate(
            field="created_utc",
            op="on_or_before",
            value=_shift(snapshot_date_utc, days=MINIMUM_HISTORY_AGE_DAYS),
            why=(
                "minimum history age of three years, so that a repository has a "
                "revision history at all"
            ),
        ),
        EligibilityPredicate(
            field="last_activity_utc",
            op="on_or_after",
            value=_shift(snapshot_date_utc, days=MAXIMUM_ACTIVITY_GAP_DAYS),
            why=(
                "catalogue-declared activity within a year, so the universe is live "
                "software rather than an archive"
            ),
        ),
    )
    inputs = {
        "wall_clock_hours": inherited_wall_clock_hours(),
        "published_rate_limit_per_hour": PUBLISHED_GITHUB_AUTHENTICATED_RATE_LIMIT_PER_HOUR,
        "per_root_request_bound": inherited_per_root_request_bound(),
        "inherited_total_request_cap": inherited_total_request_cap(),
    }
    return FrameRule(
        catalog_id=catalog_id,
        snapshot_sha256=snapshot_sha256,
        predicates=predicates,
        ranking=(RankKey(field="catalog_rank_value", descending=True),),
        tie_breaker="record_id",
        n=derive_n(**inputs),
        n_derivation="min_of_rate_limited_and_capped_budget_over_per_root_bound",
        n_inputs=MappingProxyType(dict(inputs)),
        n_justification=(
            "N is the whole number of roots the inherited transport budget can visit. "
            "Two operational bounds constrain it and the STRONGER one applies: the "
            "inherited wall-clock bound in whole hours multiplied by GitHub's published "
            "authenticated primary rate limit per hour, or the inherited total request "
            "cap, whichever is smaller -- divided by the inherited per-root request "
            "bound, floored. Every input predates this study's question and none of them "
            "moves when a census disappoints. Taking the tighter of two pre-existing "
            "constraints LOWERS N, which is the direction that cannot be suspected of "
            "having been chosen to reach a number. The rate limit is an upper bound and "
            "not a guaranteed sustained throughput; secondary limits exist, so execution "
            "still paces serially and honours Retry-After, remaining and reset. SFIR7 may "
            "come up short at this N, and if it does, that is a finding rather than a "
            "reason to recompute N."
        ),
    )
