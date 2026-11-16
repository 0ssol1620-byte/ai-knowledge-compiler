"""Task contract and metrics for the retrieval baseline harness."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

KINDS = frozenset({"retrieval", "temporal", "acl_negative"})
PROVENANCES = frozenset({"generated", "annotated"})
CUT_KEYS = ("valid_at", "known_at", "available_at")


class TaskError(ValueError):
    """A task row that does not meet the shared contract."""


def parse_moment(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise TaskError(f"{field} must be an ISO-8601 string")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TaskError(f"{field} is not ISO-8601: {value!r}") from exc
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise TaskError(f"{field} must carry a UTC offset: {value!r}")
    return moment


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    kind: str
    tenant: str
    query: str
    cut: dict[str, datetime] | None
    gold_evidence_ids: frozenset[str]
    answerable: bool
    provenance: str
    generator: str
    seed: int


def parse_task(row: Mapping[str, Any]) -> Task:
    try:
        kind = row["kind"]
        provenance = row["provenance"]
        gold = row["gold_evidence_ids"]
        answerable = row["answerable"]
        raw_cut = row["cut"]
        task = Task(
            task_id=str(row["task_id"]),
            kind=kind,
            tenant=str(row["tenant"]),
            query=str(row["query"]),
            cut=None,
            gold_evidence_ids=frozenset(gold),
            answerable=answerable,
            provenance=provenance,
            generator=str(row["generator"]),
            seed=int(row["seed"]),
        )
    except KeyError as exc:
        raise TaskError(f"task is missing field {exc.args[0]!r}") from exc
    if kind not in KINDS:
        raise TaskError(f"unknown task kind {kind!r}")
    if provenance not in PROVENANCES:
        raise TaskError(f"unknown provenance {provenance!r}")
    if not isinstance(answerable, bool):
        raise TaskError("answerable must be a boolean")
    if answerable != bool(task.gold_evidence_ids):
        raise TaskError("answerable must match whether gold_evidence_ids is non-empty")
    cut: dict[str, datetime] | None = None
    if raw_cut is not None:
        unknown = set(raw_cut) - set(CUT_KEYS)
        if unknown:
            raise TaskError(f"unknown cut keys {sorted(unknown)}")
        cut = {k: parse_moment(v, field=k) for k, v in raw_cut.items() if v is not None}
        cut = cut or None
    return replace(task, cut=cut)


def load_tasks(lines: Iterable[str]) -> list[Task]:
    return [parse_task(json.loads(line)) for line in lines if line.strip()]


def violates_cut(metadata: Mapping[str, Any], cut: Mapping[str, datetime]) -> bool:
    """Independent of the harness filter: True when a hit could not be known at the cut."""

    def moment(key: str) -> datetime | None:
        raw = metadata.get(key)
        return parse_moment(raw, field=key) if raw is not None else None

    if "known_at" in cut:
        recorded = moment("recorded_at")
        if recorded is None or recorded > cut["known_at"]:
            return True
    if "available_at" in cut:
        available = moment("available_at")
        if available is None or available > cut["available_at"]:
            return True
    if "valid_at" in cut:
        start, end = moment("valid_from"), moment("valid_to")
        if (start is not None and start > cut["valid_at"]) or (
            end is not None and end <= cut["valid_at"]
        ):
            return True
    return False


def score_task(
    hit_ids: tuple[str, ...],
    gold: frozenset[str],
    evidence_of: Mapping[str, frozenset[str]],
) -> dict[str, float | None]:
    """recall@k and source precision@k for one task; None when undefined."""
    found: set[str] = set()
    for h in hit_ids:
        found |= evidence_of.get(h, frozenset()) & gold
    relevant = sum(1 for h in hit_ids if evidence_of.get(h, frozenset()) & gold)
    return {
        "recall": len(found) / len(gold) if gold else None,
        "precision": relevant / len(hit_ids) if gold and hit_ids else None,
    }


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
