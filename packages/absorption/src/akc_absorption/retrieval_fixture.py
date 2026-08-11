"""EXP-0103's missing dataset — queries, gold evidence, and unauthorized probes.

Contract C states the gap plainly: documents can come from the existing corpus,
but **there are no query or gold-evidence labels**, so a new fixture is required
before the experiment can be scored at all. That is what this module builds.

Three arms, and only two of them are populated here:

1. **Controlled synthetic queries** over a multi-granularity unit store, with
   gold evidence derived by construction rather than by annotation. Populated.
2. **A cross-tenant unauthorized probe set.** Populated, and it is the one that
   matters most: the unauthorized candidate rate is not a statistic in Contract
   C, it is a hard gate at zero, and a gate with no probe behind it is a
   sentence rather than a check.
3. **Automatic truth from SEC XBRL and OpenDART structured facts** (§31.4).
   **Not populated.** `queries_from_structured_facts` is the entry point they
   plug into and it works, but no XBRL or DART extract exists in this
   repository, so nothing has been run through it. That is a gap in the fixture
   and it is stated rather than filled with a synthetic stand-in wearing the
   name of a filing.

**The visual lane is out of scope for this batch** per Contract C, so no unit
here carries a page image and none pretends to.

What this module does *not* do is run retrieval. Contract C's challenger --
intent-driven granularity plus score-distribution adaptive-k -- is not
implemented here; the approved order puts EXP-0101 first and this round stops at
fixture readiness.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "FIXTURE_VERSION",
    "EvidenceUnit",
    "GoldQuery",
    "RetrievalFixture",
    "RetrievalIntent",
    "StructuredFact",
    "UnauthorizedProbe",
    "UnitGranularity",
    "VersionState",
    "build_retrieval_fixture",
    "queries_from_structured_facts",
]

FIXTURE_VERSION = "amgr-1"

_TENANTS = ("tenant-alpha", "tenant-bravo", "tenant-charlie", "tenant-delta")
_PROJECTS = ("proj-core", "proj-legal", "proj-ops")
_METRICS = (
    "operating margin",
    "deferred revenue",
    "headcount",
    "capital expenditure",
    "days sales outstanding",
    "renewal rate",
)
_PERIODS = ("FY2024", "FY2025", "FY2026")


class RetrievalIntent(StrEnum):
    """Blueprint §8.5's intent classes."""

    EXACT_EVIDENCE = "EXACT_EVIDENCE"
    FACT = "FACT"
    TABLE = "TABLE"
    PROCEDURE = "PROCEDURE"
    ENTITY = "ENTITY"
    RELATION = "RELATION"
    CHANGE = "CHANGE"
    HISTORICAL = "HISTORICAL"
    IMPACT = "IMPACT"


class UnitGranularity(StrEnum):
    """The granularities the challenger would choose between."""

    TABLE_CELL = "TABLE_CELL"
    TABLE_ROW = "TABLE_ROW"
    CLAIM = "CLAIM"
    PARAGRAPH = "PARAGRAPH"
    SECTION = "SECTION"


class VersionState(StrEnum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


#: Which granularity each intent should prefer. Written down so the experiment
#: can score "did the challenger pick the right granularity" separately from
#: "did it retrieve the right unit", which a single recall number conflates.
PREFERRED_GRANULARITY: dict[RetrievalIntent, UnitGranularity] = {
    RetrievalIntent.EXACT_EVIDENCE: UnitGranularity.TABLE_CELL,
    RetrievalIntent.FACT: UnitGranularity.TABLE_CELL,
    RetrievalIntent.TABLE: UnitGranularity.TABLE_ROW,
    RetrievalIntent.PROCEDURE: UnitGranularity.SECTION,
    RetrievalIntent.ENTITY: UnitGranularity.CLAIM,
    RetrievalIntent.RELATION: UnitGranularity.CLAIM,
    RetrievalIntent.CHANGE: UnitGranularity.CLAIM,
    RetrievalIntent.HISTORICAL: UnitGranularity.CLAIM,
    RetrievalIntent.IMPACT: UnitGranularity.SECTION,
}


def _pick(options: tuple[str, ...], *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


def _pick_int(low: int, high: int, *parts: str) -> int:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return low + int.from_bytes(digest[4:8], "big") % (high - low + 1)


@dataclass(frozen=True, slots=True)
class EvidenceUnit:
    """One retrievable unit, at one granularity, owned by exactly one tenant."""

    unit_id: str
    tenant_id: str
    project_id: str
    document_id: str
    granularity: UnitGranularity
    text: str
    section: str
    fact_key: str = ""
    version_state: VersionState = VersionState.CURRENT
    version_label: str = "v1"

    def as_record(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "document_id": self.document_id,
            "granularity": self.granularity.value,
            "text": self.text,
            "section": self.section,
            "fact_key": self.fact_key,
            "version_state": self.version_state.value,
            "version_label": self.version_label,
        }


@dataclass(frozen=True, slots=True)
class GoldQuery:
    """One query with the evidence that answers it, and who is allowed to ask."""

    query_id: str
    tenant_id: str
    project_id: str
    intent: RetrievalIntent
    text: str
    gold_unit_ids: tuple[str, ...]
    preferred_granularity: UnitGranularity
    critical: bool
    truth_source: str
    #: The gold unit that is current, where the fact has more than one version.
    version_correct_unit_ids: tuple[str, ...] = ()

    def as_record(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "intent": self.intent.value,
            "text": self.text,
            "gold_unit_ids": list(self.gold_unit_ids),
            "preferred_granularity": self.preferred_granularity.value,
            "critical": self.critical,
            "truth_source": self.truth_source,
            "version_correct_unit_ids": list(self.version_correct_unit_ids),
        }


@dataclass(frozen=True, slots=True)
class UnauthorizedProbe:
    """A query whose answer exists, in a tenant the asker may not read.

    The probe is deliberately *answerable* somewhere. A probe whose answer does
    not exist anywhere tests nothing: an empty result would be correct for the
    wrong reason, and the failure it is meant to catch -- a candidate crossing a
    tenant boundary before the permission filter -- could never fire.
    """

    probe_id: str
    asking_tenant_id: str
    asking_project_id: str
    text: str
    #: Units that answer the query and that the asker must never be offered.
    forbidden_unit_ids: tuple[str, ...]
    #: What the asker is legitimately allowed to see for this query. Often none.
    permitted_unit_ids: tuple[str, ...] = ()

    def as_record(self) -> dict[str, object]:
        return {
            "probe_id": self.probe_id,
            "asking_tenant_id": self.asking_tenant_id,
            "asking_project_id": self.asking_project_id,
            "text": self.text,
            "forbidden_unit_ids": list(self.forbidden_unit_ids),
            "permitted_unit_ids": list(self.permitted_unit_ids),
        }


@dataclass(frozen=True, slots=True)
class StructuredFact:
    """One machine-readable fact from a filing — the XBRL/DART plug point.

    `value` stays a string. A filing's own rendering of a number is what the
    document says, and reparsing it into a float here would silently normalise
    away the thing an exact-evidence query is supposed to match.
    """

    fact_key: str
    value: str
    period: str
    tenant_id: str
    project_id: str
    document_id: str
    section: str
    unit_of_measure: str = ""


@dataclass(frozen=True, slots=True)
class RetrievalFixture:
    units: tuple[EvidenceUnit, ...]
    queries: tuple[GoldQuery, ...]
    probes: tuple[UnauthorizedProbe, ...]

    @property
    def manifest_sha256(self) -> str:
        payload = json.dumps(
            {
                "fixture_version": FIXTURE_VERSION,
                "units": [unit.as_record() for unit in self.units],
                "queries": [query.as_record() for query in self.queries],
                "probes": [probe.as_record() for probe in self.probes],
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def units_for(self, tenant_id: str) -> tuple[EvidenceUnit, ...]:
        return tuple(unit for unit in self.units if unit.tenant_id == tenant_id)

    def as_record(self) -> dict[str, object]:
        return {
            "fixture_version": FIXTURE_VERSION,
            "manifest_sha256": self.manifest_sha256,
            "counts": {
                "units": len(self.units),
                "queries": len(self.queries),
                "probes": len(self.probes),
                "tenants": len({unit.tenant_id for unit in self.units}),
            },
            "units": [unit.as_record() for unit in self.units],
            "queries": [query.as_record() for query in self.queries],
            "probes": [probe.as_record() for probe in self.probes],
        }


def _fact_key(tenant: str, project: str, metric: str, period: str) -> str:
    return f"{tenant}/{project}/{metric.replace(' ', '_')}/{period}"


def _units_for_fact(
    tenant: str, project: str, metric: str, period: str, *, superseded: bool
) -> list[EvidenceUnit]:
    """The same fact stated at three granularities, and optionally twice.

    Stating one fact as a cell, a row and a claim is what makes granularity
    selection measurable: a fixed-k retriever over one granularity cannot be
    distinguished from an intent-aware one unless the alternatives exist.
    """
    key = _fact_key(tenant, project, metric, period)
    document = f"doc-{tenant}-{project}-{period}".replace("tenant-", "")
    section = f"{metric.title()} / {period}"
    value = _pick_int(10, 95, "value", key)
    units: list[EvidenceUnit] = []

    versions: list[tuple[str, VersionState, int]] = [("v2", VersionState.CURRENT, value)]
    if superseded:
        versions.append(("v1", VersionState.SUPERSEDED, max(1, value - 7)))

    for label, state, amount in versions:
        suffix = f"{label}"
        units.append(
            EvidenceUnit(
                unit_id=f"u:{key}:cell:{suffix}",
                tenant_id=tenant,
                project_id=project,
                document_id=document,
                granularity=UnitGranularity.TABLE_CELL,
                text=f"{amount}",
                section=section,
                fact_key=key,
                version_state=state,
                version_label=label,
            )
        )
        units.append(
            EvidenceUnit(
                unit_id=f"u:{key}:row:{suffix}",
                tenant_id=tenant,
                project_id=project,
                document_id=document,
                granularity=UnitGranularity.TABLE_ROW,
                text=f"{metric} | {period} | {amount}",
                section=section,
                fact_key=key,
                version_state=state,
                version_label=label,
            )
        )
        units.append(
            EvidenceUnit(
                unit_id=f"u:{key}:claim:{suffix}",
                tenant_id=tenant,
                project_id=project,
                document_id=document,
                granularity=UnitGranularity.CLAIM,
                text=(
                    f"For {period} the reported {metric} was {amount}, measured "
                    "under the group accounting policy."
                ),
                section=section,
                fact_key=key,
                version_state=state,
                version_label=label,
            )
        )
    units.append(
        EvidenceUnit(
            unit_id=f"u:{key}:section",
            tenant_id=tenant,
            project_id=project,
            document_id=document,
            granularity=UnitGranularity.SECTION,
            text=(
                f"{section}. This section explains how {metric} is calculated, "
                "which entities are consolidated, and how the figure is reviewed."
            ),
            section=section,
            fact_key=key,
        )
    )
    return units


def queries_from_structured_facts(
    facts: list[StructuredFact], units: list[EvidenceUnit]
) -> list[GoldQuery]:
    """Turn machine-readable filing facts into queries with automatic gold.

    §31.4's pattern: the filing already says what the number is, so the gold
    evidence for "what was X in period P" is every unit carrying that fact key.
    No human annotation, and no room for an annotator to disagree with the
    filing.

    **Nothing has been run through this.** There is no XBRL or DART extract in
    this repository, so it is a working entry point with an empty input, and
    Contract C's first dataset arm is therefore unbuilt rather than built.
    """
    by_key: dict[str, list[EvidenceUnit]] = {}
    for unit in units:
        if unit.fact_key:
            by_key.setdefault(unit.fact_key, []).append(unit)

    queries: list[GoldQuery] = []
    for fact in facts:
        gold = by_key.get(fact.fact_key, [])
        if not gold:
            # No unit states this fact. Emitting a query with an empty gold set
            # would put an unanswerable item in the recall denominator.
            continue
        queries.append(
            GoldQuery(
                query_id=f"q:xbrl:{fact.fact_key}",
                tenant_id=fact.tenant_id,
                project_id=fact.project_id,
                intent=RetrievalIntent.FACT,
                text=f"What was {fact.fact_key.split('/')[-2].replace('_', ' ')} "
                f"in {fact.period}?",
                gold_unit_ids=tuple(sorted(unit.unit_id for unit in gold)),
                preferred_granularity=PREFERRED_GRANULARITY[RetrievalIntent.FACT],
                critical=True,
                truth_source="structured_fact",
                version_correct_unit_ids=tuple(
                    sorted(
                        unit.unit_id
                        for unit in gold
                        if unit.version_state is VersionState.CURRENT
                    )
                ),
            )
        )
    return queries


_QUERY_TEMPLATES: dict[RetrievalIntent, str] = {
    RetrievalIntent.EXACT_EVIDENCE: "Show the exact figure for {metric} in {period}.",
    RetrievalIntent.FACT: "What was {metric} in {period}?",
    RetrievalIntent.TABLE: "Give the {period} row for {metric}.",
    RetrievalIntent.PROCEDURE: "How is {metric} calculated and reviewed?",
    RetrievalIntent.HISTORICAL: "What did we previously report for {metric} in {period}?",
    RetrievalIntent.CHANGE: "What changed in the reported {metric} for {period}?",
}


def build_retrieval_fixture(
    *, tenants: tuple[str, ...] = _TENANTS, periods: tuple[str, ...] = _PERIODS
) -> RetrievalFixture:
    """The whole fixture, deterministically. No sampling, no PRNG, no network."""
    units: list[EvidenceUnit] = []
    for tenant in tenants:
        for project in _PROJECTS:
            for metric in _METRICS:
                for period in periods:
                    superseded = (
                        _pick(("yes", "no"), "superseded", tenant, project, metric, period)
                        == "yes"
                    )
                    units.extend(
                        _units_for_fact(
                            tenant, project, metric, period, superseded=superseded
                        )
                    )

    by_key: dict[str, list[EvidenceUnit]] = {}
    for unit in units:
        if unit.fact_key:
            by_key.setdefault(unit.fact_key, []).append(unit)

    queries: list[GoldQuery] = []
    for key, group in sorted(by_key.items()):
        tenant, project, metric_key, period = key.split("/")
        metric = metric_key.replace("_", " ")
        intent_name = _pick(
            tuple(item.value for item in _QUERY_TEMPLATES), "intent", key
        )
        intent = RetrievalIntent(intent_name)
        preferred = PREFERRED_GRANULARITY[intent]
        has_history = any(
            unit.version_state is VersionState.SUPERSEDED for unit in group
        )
        if intent in {RetrievalIntent.HISTORICAL, RetrievalIntent.CHANGE} and not has_history:
            # A history question over a fact with one version has no answer that
            # differs from the current one. Asking it anyway would score every
            # arm as if it had done version reasoning it never did.
            intent = RetrievalIntent.FACT
            preferred = PREFERRED_GRANULARITY[intent]

        relevant = [unit for unit in group if unit.granularity is preferred]
        if not relevant:
            relevant = list(group)
        queries.append(
            GoldQuery(
                query_id=f"q:{key}:{intent.value}",
                tenant_id=tenant,
                project_id=project,
                intent=intent,
                text=_QUERY_TEMPLATES[intent].format(metric=metric, period=period),
                gold_unit_ids=tuple(sorted(unit.unit_id for unit in relevant)),
                preferred_granularity=preferred,
                critical=intent
                in {RetrievalIntent.EXACT_EVIDENCE, RetrievalIntent.FACT},
                truth_source="synthetic_controlled",
                version_correct_unit_ids=tuple(
                    sorted(
                        unit.unit_id
                        for unit in relevant
                        if unit.version_state is VersionState.CURRENT
                    )
                ),
            )
        )

    probes = _build_probes(tenants, by_key)
    return RetrievalFixture(
        units=tuple(units), queries=tuple(queries), probes=tuple(probes)
    )


def _build_probes(
    tenants: tuple[str, ...], by_key: dict[str, list[EvidenceUnit]]
) -> list[UnauthorizedProbe]:
    """One probe per (asking tenant, owning tenant, metric) triple, crossed.

    Crossed rather than sampled because the unauthorized rate is a hard gate at
    zero. A sampled probe set can only ever say "we did not see a leak in the
    sample"; the gate is worth more when the denominator is every pair.
    """
    probes: list[UnauthorizedProbe] = []
    for asking in tenants:
        for owning in tenants:
            if asking == owning:
                continue
            for metric in _METRICS:
                forbidden: list[str] = []
                permitted: list[str] = []
                for key, group in by_key.items():
                    if metric.replace(" ", "_") not in key:
                        continue
                    for unit in group:
                        if unit.tenant_id == owning:
                            forbidden.append(unit.unit_id)
                        elif unit.tenant_id == asking:
                            permitted.append(unit.unit_id)
                if not forbidden:
                    continue
                probes.append(
                    UnauthorizedProbe(
                        probe_id=f"p:{asking}:{owning}:{metric.replace(' ', '_')}",
                        asking_tenant_id=asking,
                        asking_project_id=_PROJECTS[0],
                        text=(
                            f"What is {owning.replace('tenant-', '').title()}'s "
                            f"reported {metric}?"
                        ),
                        forbidden_unit_ids=tuple(sorted(forbidden)),
                        permitted_unit_ids=tuple(sorted(permitted)),
                    )
                )
    return probes
