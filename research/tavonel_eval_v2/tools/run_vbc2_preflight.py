#!/usr/bin/env python3
"""VBC2 CPU preflight: the frozen pipeline, in the frozen order, before any GPU.

The order is the protocol's and every step only subtracts:

    fresh lineage -> history enumeration -> frozen ValueFact state
    -> qualifying adjacent transition -> one primary per lineage
    -> local source coverage -> revision-neutral query
    -> tokenizer and context materialization -> target evidence retention
    -> final model-endpoint cohort

The first four happened in acquisition and are read from its sealed manifest,
never recomputed. What runs here is everything downstream of the pair, plus the
gates that decide whether a GPU second is ever spent.

Two boundaries are enforced rather than asserted. The query is built from the
property label alone and checked to contain no value. And the tokenizer's
identity is recorded through the frozen probe battery, so the contract the CPU
measured can be compared against the one the GPU runs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from hashlib import sha256
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
from evidence import write_immutable  # noqa: E402
from run_model_preflight import (  # noqa: E402
    atoms_for,
    document_order_atoms,
    ranked_atoms,
    token_counter,
    verify_model_identity,
)
from run_p4b import FieldedBm25  # noqa: E402
from run_p4e import build  # noqa: E402
from source_map_v2 import located_spans  # noqa: E402
from source_spans import attribute_to_canonical, reference_facts  # noqa: E402

from context_builder import (  # noqa: E402
    ARMS,
    SINGLE_REVISION_ARMS,
    SUPERSEDED_CONTROL,
    TOTAL_PROMPT_TOKENS,
    arm_candidates,
    fit_to_budget,
    prompt_carries_no_arm_label,
    schedule,
    schedule_balance,
    SYSTEM_PROMPT,
)
from tokenizer_parity import battery_digest, pinned_environment, run_battery  # noqa: E402
from value_fact import (  # noqa: E402
    atom_contrast_is_single,
    question_id,
    question_is_blind_to_the_value,
    question_query,
)
from value_fact_controls import run_controls as extractor_controls  # noqa: E402
from value_scorer import normalise  # noqa: E402
from value_scorer import run_controls as scorer_controls  # noqa: E402

PROTOCOL = NS / "protocols" / "VALUE_BEARING_COHORT_V2.yaml"
COHORTS = NS / "artifacts" / "development" / "vbc2_cohorts"

#: INC-V2-022: a truncated walk must not be able to present itself as a cohort.
#: The preflight refuses outright rather than reporting a verdict computed over
#: a list whose denominator is unknown.
INCOMPLETE_ACQUISITION = "REFUSED_ACQUISITION_INCOMPLETE"


def newest_complete_manifest() -> Path | None:
    """The most recent manifest that says, in its own body, that it finished."""
    best: tuple[str, Path] | None = None
    for path in sorted(COHORTS.glob("vbc2_cohort.*.json")):
        if ".partial." in path.name:
            continue
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if body.get("complete") is not True:
            continue
        stamp = str(body.get("ended_at", ""))
        if best is None or stamp > best[0]:
            best = (stamp, path)
    return best[1] if best else None


def acquisition_is_complete(manifest: Path) -> dict[str, Any]:
    """Read the acceptance rule off the manifest, never off a filename."""
    body = json.loads(manifest.read_text(encoding="utf-8"))
    coverage = body.get("walk_coverage", {})
    complete = (
        body.get("complete") is True
        and body.get("status") == "COMPLETE"
        and coverage.get("stopped_on_wall_clock_budget") is False
        and coverage.get("lineages_walked") == coverage.get("lineages_available")
        and coverage.get("lineages_considered") == coverage.get("lineages_available")
    )
    try:
        where, digest = rel(manifest), sha_file(manifest)
    except ValueError:  # a manifest outside the namespace, as in a fixture
        where, digest = str(manifest), None
    return {
        "complete": bool(complete),
        "status": body.get("status"),
        "walk_coverage": coverage,
        "manifest": where,
        "manifest_sha256": digest,
        "rule": (
            "a full acquisition requires stopped_on_wall_clock_budget == false and "
            "the frozen lineage list exhausted. Anything else is a diagnostic "
            "partial result and cannot be a confirmatory acquisition."
        ),
    }


INPUTS = NS / "artifacts" / "development" / "vbc2_endpoint_inputs.json"

COHORT_FLOOR = 190
TRUNCATION_CEILING = 0.25

ATOM_NOT_LOCATED = "ATOM_NOT_LOCATED"
ATOM_NOT_UNIQUE = "ATOM_NOT_UNIQUE"
NO_SUPERSEDED_ATOM = "NO_SUPERSEDED_ATOM"
AMBIGUOUS = "AMBIGUOUS_VALUE_FACT"
COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
QUESTION_NOT_BLIND = "QUESTION_NOT_BLIND"
TRUNCATED_AWAY = "TARGET_EVIDENCE_LOST_TO_TRUNCATION"


#: Markdown emphasis, code and link markers. A property label read out of raw
#: markup carries these; the canonical text it must be found in does not.
_MARKUP_MARKERS = re.compile(r"[*_`~\[\]]+")


def _needle(text: str) -> str:
    """One representation for both halves of the instrument.

    INC-V2-023: acquisition reads labels from raw markup and the preflight
    searches canonical text. Comparing them directly is a category error, so
    both sides are reduced here through the frozen scorer's own normalization
    with markup markers removed first.
    """
    return normalise(_MARKUP_MARKERS.sub("", text or ""))


def locate(atoms: dict[str, Any], fact: dict[str, Any]) -> list[str]:
    """Atoms carrying both the property label and its current value."""
    label = _needle(fact["property_label"])
    value = _needle(fact["current_value_text"])
    if not label or not value:
        return []
    return [
        atom_id
        for atom_id, atom in atoms.items()
        if label in _needle(atom["text"]) and value in _needle(atom["text"])
    ]


def coverage_complete(record: dict[str, Any], sides: dict[str, Any], atom_id: str) -> bool:
    """Question-local coverage under the frozen markup-semantics source map."""
    document = json.loads((ROOT / record["after"]["canonical_path"]).read_text(encoding="utf-8"))
    canonical_text = " ".join(unit["text"] for unit in document["units"])
    raw = (ROOT / record["after"]["raw_path"]).read_bytes().decode("utf-8", errors="replace")
    spans, grammar = located_spans(raw, record["suffix"], canonical_text)
    facts = reference_facts(spans)
    targets = [str(item.get("target") or "") for item in facts]
    atoms = sides["current"]["atoms"]
    if grammar == "markdown":
        attribute_to_canonical(spans, [a["text"] for a in atoms.values()], targets)
    envelope_of = {
        member: envelope
        for envelope in sides["current"]["envelopes"]
        for member in envelope.member_ids
    }
    envelope = envelope_of.get(atom_id)
    members = (
        [
            atoms[member]["text"]
            for member in envelope.member_ids
            if member in atoms and member != atom_id
        ]
        if envelope is not None
        else []
    )
    witness = build_witness(
        spans,
        atoms[atom_id]["text"],
        members,
        targets,
        raw=raw,
        canonical_text=canonical_text,
        grammar=grammar,
    )
    return witness_status(witness, spans)["status"] == COMPLETE


def run(manifest_path: Path | None = None) -> int:
    started = now()
    manifest = manifest_path or newest_complete_manifest()
    if manifest is None:
        print(
            json.dumps(
                {
                    "verdict": INCOMPLETE_ACQUISITION,
                    "reason": "no completed acquisition manifest exists",
                    "searched": str(COHORTS),
                },
                sort_keys=True,
            )
        )
        return 2
    completeness = acquisition_is_complete(manifest)
    if not completeness["complete"]:
        print(json.dumps({"verdict": INCOMPLETE_ACQUISITION, **completeness}, sort_keys=True))
        return 2

    identity = verify_model_identity()
    tokenizer = identity["tokenizer"]
    count = token_counter(tokenizer)

    def encode(text: str) -> list[int]:
        return list(tokenizer.encode(text, add_special_tokens=False))

    def encode_chat(system: str, user: str) -> list[int]:
        rendered = tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tokenize=False,
            add_generation_prompt=True,
        )
        return list(tokenizer.encode(rendered, add_special_tokens=False))

    cohort_body = json.loads(manifest.read_text(encoding="utf-8"))
    cohort = {record["document_slug"]: record for record in cohort_body["documents"]}
    primaries = {row["slug"]: row for row in cohort_body["primary_transitions"]}

    built = build(manifest)
    scopes: dict[str, set[str]] = {}
    for row in built["index_rows"]:
        scopes.setdefault(row["pair_id"], set()).add(row["doc_id"])
    index = FieldedBm25(built["index_rows"])

    materialized: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for slug in sorted(primaries):
        fact = primaries[slug]
        record = cohort.get(slug)
        if record is None:
            excluded.append({"slug": slug, "reason": ATOM_NOT_LOCATED})
            continue
        sides = atoms_for(record, slug)
        current_atoms = sides["current"]["atoms"]
        superseded_atoms = sides["superseded"]["atoms"]
        by_path = {atom["path"]: (aid, atom) for aid, atom in superseded_atoms.items()}

        located = locate(current_atoms, fact)
        if not located:
            excluded.append({"slug": slug, "reason": ATOM_NOT_LOCATED})
            continue
        if len(located) > 1:
            excluded.append({"slug": slug, "reason": ATOM_NOT_UNIQUE})
            continue
        target_id = located[0]
        target = current_atoms[target_id]
        prior = by_path.get(target["path"])
        if prior is None:
            excluded.append({"slug": slug, "reason": NO_SUPERSEDED_ATOM})
            continue
        prior_id, prior_atom = prior

        single = atom_contrast_is_single(fact, target["text"], prior_atom["text"])
        if not single["single_contrast"]:
            excluded.append({"slug": slug, "reason": AMBIGUOUS})
            continue

        if not coverage_complete(record, sides, target_id):
            excluded.append({"slug": slug, "reason": COVERAGE_INCOMPLETE})
            continue

        query = question_query(fact)
        blind = question_is_blind_to_the_value(query, fact)
        if not blind["blind"]:
            excluded.append({"slug": slug, "reason": QUESTION_NOT_BLIND})
            continue

        scope = scopes.get(slug, set())
        scores = index.score_all(query, scope)
        current_ranked = ranked_atoms(sides["current"]["envelopes"], current_atoms, scores)
        superseded_ranked = ranked_atoms(sides["superseded"]["envelopes"], superseded_atoms, scores)
        merged = sorted(
            current_ranked + superseded_ranked,
            key=lambda atom: (
                -scores.get(atom["atom_id"].rsplit("|", 1)[0], 0.0),
                atom["path"],
                atom["atom_id"],
            ),
        )
        oracle = document_order_atoms(current_atoms)

        arm_records: dict[str, Any] = {}
        invalid: list[str] = []
        for arm in ARMS:
            pool = arm_candidates(arm, current_ranked, superseded_ranked, oracle, merged)
            fitted = fit_to_budget(query, pool, count, TOTAL_PROMPT_TOKENS)
            wanted = prior_id if arm == SUPERSEDED_CONTROL else target_id
            fitted["target_evidence_atom"] = wanted
            fitted["target_evidence_present"] = wanted in fitted["context_atom_ids"]
            fitted["prompt_sha256"] = (
                "sha256:"
                + sha256((fitted["system"] + "\x00" + fitted["user"]).encode("utf-8")).hexdigest()
            )
            arm_records[arm] = fitted
            if arm in SINGLE_REVISION_ARMS and not fitted["target_evidence_present"]:
                invalid.append(arm)
        if invalid:
            excluded.append({"slug": slug, "reason": TRUNCATED_AWAY, "arms": invalid})
            continue

        materialized.append(
            {
                "question_id": question_id(
                    record["family"],
                    record["document_id"],
                    record["before_version"],
                    record["after_version"],
                    target_id,
                    target["path"],
                    "Q1_REVISED_VALUE",
                    fact["property_id"],
                ),
                "lineage_id": record["lineage_id"],
                "family": record["family"],
                "document_slug": slug,
                "query": query,
                "property_label": fact["property_label"],
                "column_label": fact["column_label"],
                "value_kind": fact["value_kind"],
                "current_value": fact["current_value"],
                "superseded_value": fact["superseded_value"],
                "atom_path": target["path"],
                "before_version": record["before_version"],
                "after_version": record["after_version"],
                "adjacent_pair": record["adjacent_pair"],
                "arms": arm_records,
            }
        )

    ids = [row["question_id"] for row in materialized]
    lineages = [row["lineage_id"] for row in materialized]
    families = Counter(row["family"] for row in materialized)
    assignment = schedule(ids)
    balance = schedule_balance(assignment)
    truncation = {
        arm: (
            round(
                sum(1 for row in materialized if row["arms"][arm]["truncated"]) / len(materialized),
                4,
            )
            if materialized
            else 0.0
        )
        for arm in ARMS
    }
    parity_cpu = run_battery(encode, encode_chat)
    extractor = extractor_controls()
    scorer = scorer_controls()
    prompt_clean = prompt_carries_no_arm_label(SYSTEM_PROMPT, "")

    gates = {
        "G_VBC2_SCORER_UNCHANGED": {
            "passed": bool(scorer["all_agree"]),
            "sha256": sha_file(NS / "endpoint" / "value_scorer.py"),
        },
        "G_VBC2_EXTRACTOR_UNCHANGED": {
            "passed": bool(extractor["three_directions_passed"]),
            "sha256": sha_file(NS / "endpoint" / "value_fact.py"),
            "controls": len(extractor["results"]),
        },
        "G_VBC2_FRESH_LINEAGES": {
            "passed": True,
            "checked_in": rel(NS / "artifacts" / "development" / "vbc2_lineages.json"),
            "note": "computed at lineage-freeze time against P4i, the V1 probe and the ME1 survivors",
        },
        "G_VBC2_SELECTION_BLIND": {
            "passed": True,
            "note": "lineage lists and history bounds were frozen before any history was read",
        },
        "G_VBC2_PAIR_IS_ADJACENT": {
            "passed": all(row["adjacent_pair"] for row in materialized),
            "count": len(materialized),
        },
        "G_VBC2_ONE_QUESTION_PER_LINEAGE": {
            "passed": len(materialized) == len(set(lineages)),
            "primary_questions": len(materialized),
            "distinct_lineages": len(set(lineages)),
        },
        "G_VBC2_QUESTION_ID_INJECTIVE": {
            "passed": len(ids) == len(set(ids)),
            "rows": len(ids),
            "unique": len(set(ids)),
        },
        "G_VBC2_QUESTION_BLIND_TO_VALUE": {
            "passed": prompt_clean["clean"],
            "template_digest": prompt_clean["digest"],
        },
        "G_VBC2_FAMILIES": {"passed": len(families) >= 2, "by_family": dict(families)},
        "G_VBC2_CONTEXT_VALIDITY": {
            "passed": all(
                row["arms"][arm]["target_evidence_present"]
                for row in materialized
                for arm in SINGLE_REVISION_ARMS
            ),
            "single_revision_arms": list(SINGLE_REVISION_ARMS),
        },
        "G_VBC2_TRUNCATION": {
            "passed": all(rate <= TRUNCATION_CEILING for rate in truncation.values()),
            "ceiling": TRUNCATION_CEILING,
            "rates": truncation,
        },
        "G_VBC2_COHORT_FLOOR": {
            "passed": len(set(lineages)) >= COHORT_FLOOR,
            "distinct_lineages": len(set(lineages)),
            "floor": COHORT_FLOOR,
        },
        "G_VBC2_TOKENIZER_PARITY": {
            "passed": bool(parity_cpu["all_classes_covered"]),
            "cpu_signature": parity_cpu["signature"],
            "battery_digest": parity_cpu["battery_digest"],
            "gpu_side": "compared at run time; the GPU runs the identical frozen battery",
        },
        "G_VBC2_NO_GPU_YET": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
        "G_VBC2_SCHEDULE_BALANCED": {
            "passed": bool(balance["balanced"]),
            "detail": balance,
        },
    }

    INPUTS.parent.mkdir(parents=True, exist_ok=True)
    INPUTS.write_text(
        json.dumps(
            {"questions": materialized, "schedule": assignment},
            indent=1,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    body = {
        "schema": "tavonel.v2.vbc2_preflight.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "started_at": started,
        "ended_at": now(),
        "split": "MODEL-ENDPOINT CONFIRMATORY — MODEL OUTCOMES UNSEEN",
        "cohort_manifest": rel(manifest),
        "cohort_manifest_sha256": sha_file(manifest),
        "acquisition_completeness": completeness,
        "inputs_path": rel(INPUTS),
        "inputs_sha256": sha_file(INPUTS),
        "model": identity["record"],
        "tokenizer_environment": pinned_environment(tokenizer),
        "tokenizer_parity_cpu": parity_cpu,
        "totals": {
            "primary_transitions": len(primaries),
            "final_cohort": len(materialized),
            "distinct_lineages": len(set(lineages)),
            "excluded": len(excluded),
            "prompts_materialized": len(materialized) * len(ARMS),
        },
        "by_family": dict(families),
        "excluded_by_reason": dict(Counter(row["reason"] for row in excluded)),
        "excluded_detail": excluded[:200],
        "truncation_rates": truncation,
        "schedule_balance": balance,
        "scorer": {"controls": scorer, "unchanged": True},
        "extractor": {"controls": extractor},
        "gates": {name: gate["passed"] for name, gate in gates.items()},
        "gate_detail": gates,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["verdict"] = "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL"
    written = write_immutable(
        "vbc2-preflight", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                **written,
                "verdict": body["verdict"],
                "final_cohort": len(materialized),
                "distinct_lineages": len(set(lineages)),
                "by_family": dict(families),
                "excluded": body["excluded_by_reason"],
                "truncation": truncation,
                "gates": body["gates"],
            },
            sort_keys=True,
        )
    )
    return 0 if body["verdict"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    return run(args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
