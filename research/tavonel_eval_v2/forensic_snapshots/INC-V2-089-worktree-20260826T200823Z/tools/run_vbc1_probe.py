#!/usr/bin/env python3
"""Run the frozen VBC1 chain over the burned probe cohort. CPU only, $0.

This measures one number that no projection can supply: on sources chosen for
value-bearing structure, what fraction of documents yields a question that
survives *every* frozen step — a stable property with a changed single value, an
evidence atom that carries that contrast alone, and local source-coverage
completeness on that atom.

The steps are the protocol's, in the protocol's order, and each one only
subtracts. Nothing here can admit a candidate that a later step would refuse,
because every refusal is recorded with its own code rather than being retried
under a weaker rule.

The cohort is burned. Its eligibility outcome is visible from here on, so none
of its lineages may enter the confirmatory cohort.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "canonicalization"))
sys.path.insert(0, str(HERE.parents[0] / "retrieval"))
sys.path.insert(0, str(HERE.parents[0] / "endpoint"))

from common import NS, ROOT, now, rel, sha_file  # noqa: E402
from coverage_witness import COMPLETE  # noqa: E402
from coverage_witness_v2 import build_witness, witness_status  # noqa: E402
from envelope import build_envelopes  # noqa: E402
from evidence import write_immutable  # noqa: E402
from source_map_v2 import located_spans  # noqa: E402
from source_spans import attribute_to_canonical, reference_facts  # noqa: E402

from value_fact import (  # noqa: E402
    atom_contrast_is_single,
    question_id,
    question_is_blind_to_the_value,
    question_query,
    value_facts,
)

MANIFEST = NS / "artifacts" / "development" / "vbc1_probe_cohort.json"
PROTOCOL = NS / "protocols" / "VALUE_BEARING_COHORT_V1.yaml"

#: Reasons a value fact does not become a probe question. Each subtracts.
ATOM_NOT_LOCATED = "ATOM_NOT_LOCATED"
ATOM_NOT_UNIQUE = "ATOM_NOT_UNIQUE"
NO_SUPERSEDED_ATOM = "NO_SUPERSEDED_ATOM"
AMBIGUOUS_VALUE_FACT = "AMBIGUOUS_VALUE_FACT"
COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
QUESTION_NOT_BLIND = "QUESTION_NOT_BLIND"


def _atoms(slug: str, revision: str, record: dict[str, Any], side: str) -> dict[str, Any]:
    document = json.loads((ROOT / record[side]["canonical_path"]).read_text(encoding="utf-8"))
    envelopes, atoms = build_envelopes(
        slug,
        revision,
        document["units"],
        {"title": record.get("title_field", ""), "doc_type": record.get("doc_type", "")},
    )
    return {"envelopes": envelopes, "atoms": atoms, "units": document["units"]}


def _locate(atoms: dict[str, dict[str, Any]], fact: dict[str, Any]) -> list[str]:
    """Atoms carrying both the property label and its current value."""
    label = fact["property_label"]
    value = fact["current_value_text"].strip()
    return [
        atom_id
        for atom_id, atom in atoms.items()
        if label in atom["text"] and value in atom["text"]
    ]


def run() -> int:
    started = now()
    cohort = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = cohort["documents"]

    excluded: Counter[str] = Counter()
    per_family_docs: Counter[str] = Counter()
    per_family_facts: Counter[str] = Counter()
    per_family_questions: Counter[str] = Counter()
    questions: list[dict[str, Any]] = []

    for record in records:
        slug = record["document_slug"]
        family = record["family"]
        per_family_docs[family] += 1
        before_raw = (
            (ROOT / record["before"]["raw_path"]).read_bytes().decode("utf-8", errors="replace")
        )
        after_raw = (
            (ROOT / record["after"]["raw_path"]).read_bytes().decode("utf-8", errors="replace")
        )
        extracted = value_facts(record["document_id"], before_raw, after_raw, record["suffix"])
        for item in extracted["rejected"]:
            excluded[item["code"]] += 1
        if not extracted["facts"]:
            continue
        per_family_facts[family] += len(extracted["facts"])

        current = _atoms(slug, "current", record, "after")
        superseded = _atoms(slug, "superseded", record, "before")
        by_path = {atom["path"]: atom for atom in superseded["atoms"].values()}

        canonical_text = " ".join(unit["text"] for unit in current["units"])
        spans, grammar = located_spans(after_raw, record["suffix"], canonical_text)
        facts_in_spans = reference_facts(spans)
        targets = [str(item.get("target") or "") for item in facts_in_spans]
        if grammar == "markdown":
            attribute_to_canonical(spans, [a["text"] for a in current["atoms"].values()], targets)
        envelope_by_id = {envelope.envelope_id: envelope for envelope in current["envelopes"]}
        anchor_of = {
            member: envelope.envelope_id
            for envelope in current["envelopes"]
            for member in envelope.member_ids
        }

        for fact in extracted["facts"]:
            located = _locate(current["atoms"], fact)
            if not located:
                excluded[ATOM_NOT_LOCATED] += 1
                continue
            if len(located) > 1:
                excluded[ATOM_NOT_UNIQUE] += 1
                continue
            atom_id = located[0]
            atom = current["atoms"][atom_id]
            counterpart = by_path.get(atom["path"])
            if counterpart is None:
                excluded[NO_SUPERSEDED_ATOM] += 1
                continue
            single = atom_contrast_is_single(fact, atom["text"], counterpart["text"])
            if not single["single_contrast"]:
                excluded[AMBIGUOUS_VALUE_FACT] += 1
                continue

            envelope = envelope_by_id.get(anchor_of.get(atom_id, ""))
            members = (
                [
                    current["atoms"][member]["text"]
                    for member in envelope.member_ids
                    if member in current["atoms"] and member != atom_id
                ]
                if envelope is not None
                else []
            )
            witness = build_witness(
                spans,
                atom["text"],
                members,
                targets,
                raw=after_raw,
                canonical_text=canonical_text,
                grammar=grammar,
            )
            status = witness_status(witness, spans)
            if status["status"] != COMPLETE:
                excluded[COVERAGE_INCOMPLETE] += 1
                continue

            query = question_query(fact)
            blind = question_is_blind_to_the_value(query, fact)
            if not blind["blind"]:
                excluded[QUESTION_NOT_BLIND] += 1
                continue

            questions.append(
                {
                    "question_id": question_id(
                        family,
                        record["document_id"],
                        record["before_version"],
                        record["after_version"],
                        atom_id,
                        atom["path"],
                        "Q1_REVISED_VALUE",
                        fact["property_id"],
                    ),
                    "family": family,
                    "document_slug": slug,
                    "property_label": fact["property_label"],
                    "column_label": fact["column_label"],
                    "value_kind": fact["value_kind"],
                    "current_value": fact["current_value"],
                    "superseded_value": fact["superseded_value"],
                    "atom_path": atom["path"],
                    "query": query,
                }
            )
            per_family_questions[family] += 1

    ids = [row["question_id"] for row in questions]
    duplicates = sorted({q for q in ids if ids.count(q) > 1})
    documents = len(records)
    body = {
        "schema": "tavonel.v2.vbc1_probe_result.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "probe": {
            "burned": True,
            "not_the_confirmatory_cohort": True,
            "why": "its eligibility outcome is now visible",
        },
        "started_at": started,
        "ended_at": now(),
        "cohort": {
            "manifest": rel(MANIFEST),
            "documents": documents,
            "by_family": dict(per_family_docs),
        },
        "value_facts_by_family": dict(per_family_facts),
        "questions": questions,
        "question_count": len(questions),
        "questions_by_family": dict(per_family_questions),
        "families_with_questions": sorted(per_family_questions),
        "excluded_by_reason": dict(excluded),
        "question_id_injective": {
            "rows": len(ids),
            "unique": len(set(ids)),
            "injective": len(set(ids)) == len(ids),
            "duplicates": duplicates,
        },
        "yield": {
            "questions_per_document": round(len(questions) / documents, 4) if documents else 0.0,
            "documents_needed_for_190": (
                int(190 * documents / len(questions)) if questions else None
            ),
            "note": (
                "a rate measured on a burned probe, reported so the confirmatory "
                "acquisition can be sized from a measurement rather than a guess. "
                "It is not an eligibility result and gates nothing."
            ),
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable(
        "vbc1-probe-result", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                **written,
                "documents": documents,
                "questions": len(questions),
                "by_family": dict(per_family_questions),
                "excluded": dict(excluded),
                "yield": body["yield"],
                "injective": body["question_id_injective"]["injective"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
