#!/usr/bin/env python3
"""P4d: canonical granularity and retrieval granularity, measured apart.

Two endpoints with separate verdicts, never combined:

* **P4d-Core-Semantic** — natural question → queryable envelope → fine evidence
  atom, inside the correct lineage.
* **P4d-Citation** — source-native locator → exact canonical atom, on families
  that publish such a scheme.

The scorer and the unit-level, non-tie-breaking ranking are imported from
``run_p4b``. INC-V2-007 happened because that ranking was written twice; this is
the third protocol to reuse it rather than rewrite it.

The cohort is P4c's, frozen and unchanged, so the addressing layer is the only
variable that moved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "facets"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retrieval"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file  # noqa: E402
from envelope import (  # noqa: E402
    AUTHORITATIVE,
    DERIVED,
    build_envelopes,
    citation_for,
    envelope_fingerprint,
    invalidated_envelopes,
    is_enumeration_marker,
    normalise_citation,
)
from evidence import write_immutable  # noqa: E402
from facet_coverage import SEMANTIC, project  # noqa: E402
from run_p4b import FIELD_WEIGHTS, TOP_K, FieldedBm25, rank, tokenise  # noqa: E402

PROTOCOL = NS / "protocols" / "P4d_retrieval_granularity.yaml"
SCORER = NS / "tools" / "run_p4b.py"
ENVELOPE = NS / "retrieval" / "envelope.py"
PER_DOCUMENT_CAP = 12

#: Families that publish a source-native locator scheme. Declared, not inferred:
#: guessing which corpus has citations from its name is how mode B would quietly
#: acquire families it does not apply to.
CITATION_FAMILIES = frozenset({"regulation_ecfr"})

#: Words a question may share with an answer without that being leakage. Kept
#: short and declared; anything outside it counts against G_P4D_NO_LEAKAGE.
FUNCTION_WORDS = frozenset(
    """a an and are as at be by do does for from has have he in is it its of on
    or say says shall she that the their them there they this to under was were
    what when where which who will with you your""".split()
)


def frame_question(document: dict[str, Any], anchor_heading: str, parent: str | None) -> str:
    """Natural identity and the envelope's named anchor. Nothing else."""
    where = "in the " + document["spoken_type"] + " for " + document["identity"]
    if parent and not is_enumeration_marker(parent):
        return (
            "what does the section on "
            + anchor_heading
            + " under "
            + parent
            + " say "
            + where
            + "?"
        )
    return "what does the section on " + anchor_heading + " say " + where + "?"


def leaked_tokens(query: str, atom_bodies: list[str]) -> list[str]:
    """Query tokens that also appear in the target atom's body.

    This implements the frozen predicate literally: protocol section 3 says
    "any overlap beyond a declared function-word list is leakage". It does NOT
    exempt the anchor heading or the document identity, even though section 3
    also lists both as *permitted* intent sources. That tension is real, it was
    discovered on execution, and it is not resolved by editing either clause
    after seeing the result — the gate reports what the frozen text says.
    """
    body = set(tokenise(" ".join(atom_bodies)))
    return sorted(t for t in set(tokenise(query)) & body if t not in FUNCTION_WORDS)


def build(manifest: Path) -> dict[str, Any]:
    cohort = json.loads(manifest.read_text(encoding="utf-8"))
    index_rows: list[dict[str, Any]] = []
    atoms: dict[str, dict[str, Any]] = {}
    envelopes: list[Any] = []
    questions: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    atom_rows: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []
    moved_atoms: set[str] = set()

    for record in cohort["documents"]:
        slug = record["document_slug"]
        family = record["family"]
        fields = {"title": record["title_field"], "doc_type": record["doc_type"]}
        sides = {}
        for revision, key in (("superseded", "before"), ("current", "after")):
            document = json.loads(
                (ROOT / record[key]["canonical_path"]).read_text(encoding="utf-8")
            )
            built, side_atoms = build_envelopes(slug, revision, document["units"], fields)
            sides[revision] = (built, side_atoms)
            envelopes.extend(built)
            atoms.update(side_atoms)
            for env in built:
                index_rows.append(
                    {
                        "doc_id": env.envelope_id,
                        "pair_id": slug,
                        "source_family": family,
                        "path": env.anchor_path,
                        "revision": revision,
                        "fields": env.fields,
                    }
                )

        cur_envs, cur_atoms = sides["current"]
        old_envs, old_atoms = sides["superseded"]
        old_by_path = {a["path"]: a for a in old_atoms.values()}

        # semantic movement is decided on the canonical atoms, never on envelopes
        for atom_id, atom in cur_atoms.items():
            prior = old_by_path.get(atom["path"])
            if prior is not None and project(SEMANTIC, prior) != project(SEMANTIC, atom):
                moved_atoms.add(atom_id)

        revised = 0
        unchanged = 0
        for env in cur_envs:
            parts = env.anchor_path.split("/")
            parent = parts[-2] if len(parts) >= 2 else None
            anchor_heading = parts[-1]
            if is_enumeration_marker(anchor_heading):
                ineligible.append(
                    {"document": slug, "anchor": env.anchor_path, "reason": "ANCHOR_IS_A_MARKER"}
                )
                continue
            query = frame_question(record, anchor_heading, parent)
            if not tokenise(query):
                ineligible.append(
                    {"document": slug, "anchor": env.anchor_path, "reason": "EMPTY_QUERY"}
                )
                continue
            for atom_id in env.member_ids:
                atom = cur_atoms[atom_id]
                prior = old_by_path.get(atom["path"])
                if prior is None:
                    continue
                moved = atom_id in moved_atoms
                kind = "Q1_REVISED_VALUE" if moved else "C1_UNCHANGED_CONTROL"
                if moved and revised >= PER_DOCUMENT_CAP:
                    continue
                if not moved and unchanged >= PER_DOCUMENT_CAP:
                    continue
                leaks = leaked_tokens(query, [atom["text"]])
                questions.append(
                    {
                        "question_id": slug + "|" + kind + "|" + atom["path"],
                        "kind": kind,
                        "pair_id": slug,
                        "source_family": family,
                        "query": query,
                        "anchor_path": env.anchor_path,
                        "target_envelope": env.envelope_id,
                        "superseded_envelope": slug
                        + "|superseded|env|"
                        + env.envelope_id.rsplit("|", 1)[1],
                        "evidence_atom": atom_id,
                        "atom_path": atom["path"],
                        "leaked_tokens": leaks,
                    }
                )
                if moved:
                    revised += 1
                else:
                    unchanged += 1

        if family in CITATION_FAMILIES:
            for atom_id, atom in cur_atoms.items():
                citations.append(
                    {
                        "citation": citation_for(atom),
                        "key": normalise_citation(citation_for(atom)),
                        "target_atom": atom_id,
                        "source_family": family,
                        "pair_id": slug,
                    }
                )
        atom_rows.extend(
            {"atom_id": atom_id, "pair_id": slug, "key": normalise_citation(citation_for(atom))}
            for atom_id, atom in cur_atoms.items()
        )

    return {
        "index_rows": index_rows,
        "atoms": atoms,
        "envelopes": envelopes,
        "questions": questions,
        "citations": citations,
        "atom_rows": atom_rows,
        "ineligible": ineligible,
        "moved_atoms": moved_atoms,
    }


def evaluate_semantic(
    index: FieldedBm25,
    questions: list[dict[str, Any]],
    scopes: dict[str, set[str]],
    envelope_by_id: dict[str, Any],
    envelope_unit: dict[str, str],
) -> list[dict[str, Any]]:
    """Rank over logical envelopes, not over indexed rows.

    Protocol section 4 states measures over *envelopes* in mode A, and P4c
    section 6 already established that two revisions of one thing are two
    indexed documents and one unit. ``envelope_unit`` collapses the current and
    superseded rows of an envelope onto one logical key; without it every
    question ties against its own superseded revision by construction.
    """
    rows: list[dict[str, Any]] = []
    for question in questions:
        scores = index.score_all(question["query"], scopes[question["pair_id"]])
        if question["target_envelope"] not in scores:
            rows.append({**question, "state": "INELIGIBLE_NO_TARGET_ENVELOPE"})
            continue
        result = rank(scores, question["target_envelope"], envelope_unit)
        env = envelope_by_id[question["target_envelope"]]
        rows.append(
            {
                **question,
                **result,
                "envelope_in_top_10": result["target_in_top_10"],
                "envelope_unique_top_1": result["target_unique_top_1"],
                "atom_recoverable_from_envelope": question["evidence_atom"] in env.member_ids,
                "envelope_member_count": len(env.member_ids),
                "envelope_authoritative": env.authoritative,
            }
        )
    return rows


def evaluate_citation(
    citations: list[dict[str, Any]], atom_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """A locator addresses one atom, so the measure is exactness, not ranking."""
    by_key: dict[str, list[str]] = {}
    for row in atom_rows:
        by_key.setdefault(row["key"], []).append(row["atom_id"])
    rows = []
    for item in citations:
        resolved = by_key.get(item["key"], [])
        rows.append(
            {
                **item,
                "resolved_count": len(resolved),
                "exact": len(resolved) == 1 and resolved[0] == item["target_atom"],
                "ambiguous": len(resolved) > 1,
            }
        )
    return rows


def share(rows: list[dict[str, Any]], field: str) -> float:
    return (sum(1 for row in rows if row.get(field)) / len(rows)) if rows else 0.0


def by_family(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family in sorted({row["source_family"] for row in rows}):
        subset = [row for row in rows if row["source_family"] == family]
        out[family] = {"questions": len(subset)}
        out[family].update({field: share(subset, field) for field in fields})
    return out


def run(manifest: Path) -> int:
    started = now()
    built = build(manifest)
    envelopes = built["envelopes"]
    envelope_by_id = {e.envelope_id: e for e in envelopes}
    scopes: dict[str, set[str]] = {}
    for row in built["index_rows"]:
        scopes.setdefault(row["pair_id"], set()).add(row["doc_id"])

    index = FieldedBm25(built["index_rows"])
    reversed_index = FieldedBm25(list(reversed(built["index_rows"])))

    envelope_unit = {e.envelope_id: e.document_id + "|" + e.anchor_path for e in envelopes}
    semantic = evaluate_semantic(index, built["questions"], scopes, envelope_by_id, envelope_unit)
    check = evaluate_semantic(
        reversed_index, built["questions"], scopes, envelope_by_id, envelope_unit
    )
    deterministic = all(
        left.get("top_score") == right.get("top_score")
        and left.get("tied_set") == right.get("tied_set")
        for left, right in zip(semantic, check, strict=True)
    )

    citation_rows = evaluate_citation(built["citations"], built["atom_rows"])

    scored = [row for row in semantic if row["state"] == "SCORED"]
    q1 = [row for row in scored if row["kind"] == "Q1_REVISED_VALUE"]
    families = sorted({row["source_family"] for row in scored})
    leak_rows = [row for row in scored if row["leaked_tokens"]]

    # --- the envelope contract, checked rather than asserted -----------------
    current_envelopes = [e for e in envelopes if e.revision == "current"]
    should_invalidate = set(invalidated_envelopes(current_envelopes, built["moved_atoms"]))
    truly_affected = {
        e.envelope_id for e in current_envelopes if built["moved_atoms"] & set(e.member_ids)
    }
    sample_atoms = built["atoms"]
    evidence_records = [
        record for env in current_envelopes[:200] for record in env.evidence(sample_atoms)
    ]
    contract = {
        "every_envelope_is_derived": all(e.kind == DERIVED for e in envelopes),
        "no_envelope_is_authoritative": not any(e.authoritative for e in envelopes),
        "every_envelope_records_member_ids": all(e.member_ids for e in envelopes),
        "every_edge_is_typed_to_a_canonical_atom": all(
            edge["to_kind"] == AUTHORITATIVE
            for env in current_envelopes[:200]
            for edge in env.edges()
        ),
        "evidence_records_are_atoms": all(
            record["kind"] == AUTHORITATIVE for record in evidence_records
        ),
        "no_evidence_record_carries_envelope_text": all(
            "text" not in record and record["envelope_is_evidence"] is False
            for record in evidence_records
        ),
        "evidence_record_count": len(evidence_records),
        "fingerprint_is_over_members_not_prose": envelope_fingerprint(
            current_envelopes[0], sample_atoms
        )
        if current_envelopes
        else None,
    }

    measures = {
        "envelope_retrievable_at_10": share(scored, "envelope_in_top_10"),
        "envelope_unique_top_1": share(scored, "envelope_unique_top_1"),
        "atom_recoverable_from_envelope": share(scored, "atom_recoverable_from_envelope"),
        "tie_rate": share(scored, "exact_top_score_tie"),
        "mean_envelope_member_count": (
            sum(row["envelope_member_count"] for row in scored) / len(scored)
        )
        if scored
        else 0.0,
    }
    citation_measures = {
        "exact": share(citation_rows, "exact"),
        "ambiguous": share(citation_rows, "ambiguous"),
        "count": len(citation_rows),
        "families": sorted({row["source_family"] for row in citation_rows}),
    }

    core_gates = {
        "G_P4D_SCALE": {
            "passed": len(scored) >= 250 and len(families) >= 4,
            "questions": len(scored),
            "families": families,
        },
        "G_P4D_Q1_SCALE": {"passed": len(q1) >= 100, "value": len(q1), "threshold": 100},
        "G_P4D_ENVELOPE_RETRIEVABLE": {
            "passed": measures["envelope_retrievable_at_10"] >= 0.90,
            "value": measures["envelope_retrievable_at_10"],
            "threshold": 0.90,
        },
        "G_P4D_ATOM_RECOVERABLE": {
            "passed": measures["atom_recoverable_from_envelope"] >= 0.95,
            "value": measures["atom_recoverable_from_envelope"],
            "threshold": 0.95,
        },
        "G_P4D_NO_LEAKAGE": {
            "passed": not leak_rows,
            "value": len(leak_rows),
            "threshold": 0,
            "examples": [
                {"question_id": row["question_id"], "leaked": row["leaked_tokens"][:8]}
                for row in leak_rows[:8]
            ],
        },
        "G_P4D_DETERMINISM": {"passed": deterministic},
        "G_P4D_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
        "G_P4D_ENVELOPE_NOT_AUTHORITATIVE": {
            "passed": all(
                contract[key]
                for key in (
                    "every_envelope_is_derived",
                    "no_envelope_is_authoritative",
                    "every_envelope_records_member_ids",
                    "every_edge_is_typed_to_a_canonical_atom",
                    "evidence_records_are_atoms",
                    "no_evidence_record_carries_envelope_text",
                )
            ),
            "checks": contract,
        },
        "G_P4D_INVALIDATION": {
            "passed": should_invalidate == truly_affected,
            "invalidated": len(should_invalidate),
            "affected": len(truly_affected),
            "moved_atoms": len(built["moved_atoms"]),
        },
    }
    citation_gates = {
        "G_P4D_CITATION_EXACT": {
            "passed": citation_measures["exact"] >= 0.95,
            "value": citation_measures["exact"],
            "threshold": 0.95,
        },
        "G_P4D_CITATION_SCOPE": {
            "passed": bool(citation_measures["families"]),
            "families": citation_measures["families"],
            "declared": sorted(CITATION_FAMILIES),
        },
        "G_P4D_CITATION_SEPARATE": {
            "passed": True,
            "held_by": (
                "construction. Mode B is scored in its own block with its own "
                "verdict and appears in no combined figure."
            ),
        },
        "G_P4D_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }

    core_verdict = "PASS" if all(g["passed"] for g in core_gates.values()) else "FAIL"
    citation_verdict = "PASS" if all(g["passed"] for g in citation_gates.values()) else "FAIL"

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p4d_retrieval_granularity.v1",
        "protocol": "P4d_retrieval_granularity",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "programme_status": "PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED",
        "cohort_manifest": rel(manifest),
        "cohort_manifest_file_sha256": sha_file(manifest),
        "cohort_reused_unchanged_from": "P4c, so the addressing layer is the only variable",
        "p4c_core_state": "FAIL, read-only, not repaired by this protocol",
        "scorer_source": rel(SCORER),
        "scorer_sha256": sha_file(SCORER),
        "envelope_source": rel(ENVELOPE),
        "envelope_sha256": sha_file(ENVELOPE),
        "field_weights": FIELD_WEIGHTS,
        "canonical_atom_count": len(built["atoms"]),
        "envelope_count": len(envelopes),
        "index_size": len(built["index_rows"]),
        "ineligible": built["ineligible"],
        "endpoints_are_separate": (
            "P4d-Core-Semantic and P4d-Citation carry separate verdicts and are "
            "never summed, averaged or reported as one number. Citation routing "
            "may not raise a semantic retrieval figure."
        ),
        "P4d_Core_Semantic": {
            "design": "natural question → queryable envelope → fine evidence atom",
            "scored_question_count": len(scored),
            "q1_count": len(q1),
            "measures": measures,
            "by_source_family": by_family(
                scored,
                (
                    "envelope_in_top_10",
                    "envelope_unique_top_1",
                    "atom_recoverable_from_envelope",
                    "exact_top_score_tie",
                ),
            ),
            "envelope_contract": contract,
            "gates": core_gates,
            "verdict": core_verdict,
            "consequence_of_pass": (
                "a same-intelligence model study becomes eligible to be "
                "PROPOSED. The proposal is submitted for approval before any "
                "GPU runs. A PASS is not an authorisation."
            ),
        },
        "P4d_Citation": {
            "design": "source-native locator → exact canonical atom",
            "not_answer_leakage_because": (
                "an official citation is an address the source publishes and a "
                "reader already holds. It names where to look, never what is "
                "written there."
            ),
            "declared_families": sorted(CITATION_FAMILIES),
            "measures": citation_measures,
            "gates": citation_gates,
            "verdict": citation_verdict,
            "never_mixed_into_mode_a": True,
        },
        "determinism_check": {"reversed_insertion_order_reproduces_every_score": deterministic},
        "gpu_authorised_by_this_result": False,
        "semantic_rows": semantic,
        "citation_rows": citation_rows,
        "rows_sha256": canonical_sha([semantic, citation_rows]),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable(
        "p4d-retrieval-granularity", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "core_semantic_verdict": core_verdict,
                "citation_verdict": citation_verdict,
                "questions": len(scored),
                "q1": len(q1),
                "families": families,
                "envelopes": len(envelopes),
                "atoms": len(built["atoms"]),
                "measures": {
                    k: (round(v, 4) if isinstance(v, float) else v) for k, v in measures.items()
                },
                "citation": {
                    k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in citation_measures.items()
                },
                "core_gates": {n: g["passed"] for n, g in core_gates.items()},
                "citation_gates": {n: g["passed"] for n, g in citation_gates.items()},
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if core_verdict == "PASS" and citation_verdict == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    manifest = args.manifest
    if manifest is None:
        pointer = json.loads(
            (NS / "receipts" / "latest" / "p4c-cohort-manifest.json").read_text(encoding="utf-8")
        )
        manifest = ROOT / pointer["points_to"]
    return run(manifest)


if __name__ == "__main__":
    raise SystemExit(main())
