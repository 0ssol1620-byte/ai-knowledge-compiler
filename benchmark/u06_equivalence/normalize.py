"""Frozen normalization of a Product-Core response for U06.

Raw hashes cannot match between an incremental and a cold compile: the incremental keeps the
previous revision's logical IDs and claim IDs embed them. So every ID that embeds a logical id is
rewritten to the unit key `(sourceId, anchor)` / the claim key `(unit key, casefolded text)`.

FROZEN LIST of what is dropped (never edit to make a case pass; change only with an
architect-reviewed note): `stableId` (after rewrite), `createdByActivity`, `version`, `hash`
(it hashes the stableId), and the ID-valued payload keys that are rewritten rather than compared.
World-level response fields are not compared at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from akc_product_core.contracts import ProductCoreCompileResponse

DROPPED_KEYS = frozenset({"stableId", "createdByActivity", "version", "hash"})
_ASSERTION_KINDS = frozenset(
    {"claim", "validation_record", "block", "document", "collection", "ontology_term"}
)


class NormalizationAmbiguous(ValueError):
    """Two things normalize to the same key, so equality cannot be decided."""


@dataclass(frozen=True)
class NormalizedWorld:
    assertions: frozenset[str]
    entities: frozenset[str]
    evidence: frozenset[str]
    edges: frozenset[str]
    claim_keys: frozenset[str]

    def all(self) -> frozenset[str]:
        return self.assertions | self.entities | self.evidence | self.edges


# Lists whose order is an artifact of ID order, not meaning. Everything else keeps its order.
_UNORDERED = frozenset({"links", "claimIds", "evidenceIds", "entityIds", "sourceRefs"})


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _rewrite(value: Any, ids: dict[str, str], key: str = "") -> Any:
    if isinstance(value, str):
        return ids.get(value, value)
    if isinstance(value, list | tuple):
        items = [_rewrite(item, ids) for item in value]
        return sorted(items, key=_dump) if key in _UNORDERED else items
    if isinstance(value, dict):
        return {k: _rewrite(v, ids, k) for k, v in value.items() if k not in DROPPED_KEYS}
    return value


def normalize(response: ProductCoreCompileResponse) -> NormalizedWorld:
    unit_keys: dict[str, str] = {}
    for unit in response.candidate.units:
        key = f"unit:{unit.source_id}|{unit.anchor}"
        if key in unit_keys.values():
            raise NormalizationAmbiguous(f"duplicate unit key {key}")
        unit_keys[unit.logical_id] = key
    objects = [
        dict(o)
        for o in cast(list[dict[str, Any]], response.candidate.canonical_knowledge_model["objects"])
    ]

    ids = dict(unit_keys)
    claim_keys: set[str] = set()
    for obj in objects:
        if obj["kind"] != "claim":
            continue
        payload = obj["payload"]
        unit_key = unit_keys.get(payload["logicalId"])
        if unit_key is None:
            raise NormalizationAmbiguous(
                f"claim refers to unknown logical id {payload['logicalId']}"
            )
        key = f"claim:{unit_key}|{payload['text'].casefold()}"
        if key in claim_keys:
            raise NormalizationAmbiguous(f"duplicate claim key {key}")
        claim_keys.add(key)
        ids[obj["stableId"]] = ids[payload["claimId"]] = key
    for obj in objects:  # second pass: ids that are hashes of claim ids
        payload = obj["payload"]
        if obj["kind"] == "relation":
            key = "relation:" + "|".join(
                ids.get(payload[f], payload[f]) for f in ("subjectId", "predicate", "objectId")
            )
            ids[obj["stableId"]] = ids[payload["relationId"]] = key
        elif obj["kind"] == "validation_record":
            members = sorted(ids.get(c, c) for c in payload["claimIds"])
            key = "contradiction:" + "|".join(members) + f"|{payload.get('reason', '')}"
            ids[obj["stableId"]] = ids[payload["contradictionId"]] = key

    buckets: dict[str, set[str]] = {"a": set(), "n": set(), "e": set(), "r": set()}
    for obj in objects:
        kind = obj["kind"]
        record = _dump(
            {
                "kind": kind,
                "payload": _rewrite(obj["payload"], ids),
                "links": _rewrite(obj["links"], ids, "links"),
                "sourceRefs": _rewrite(obj["sourceRefs"], ids, "sourceRefs"),
                "verificationState": obj["verificationState"],
            }
        )
        if kind in _ASSERTION_KINDS:
            buckets["a"].add(record)
        elif kind == "entity":
            buckets["n"].add(record)
        elif kind == "evidence":
            buckets["e"].add(record)
        elif kind == "relation":
            buckets["r"].add(record)
        else:
            raise NormalizationAmbiguous(f"unknown object kind {kind!r}; not silently ignored")
    return NormalizedWorld(
        assertions=frozenset(buckets["a"]),
        entities=frozenset(buckets["n"]),
        evidence=frozenset(buckets["e"]),
        edges=frozenset(buckets["r"]),
        claim_keys=frozenset(claim_keys),
    )
