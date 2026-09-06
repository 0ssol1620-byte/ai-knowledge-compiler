#!/usr/bin/env python3
"""P4e: answer independence by provenance, with source coverage bound in.

Three things distinguish this from P4d:

1. the query builder's only argument is a restricted ``IntentView``, so a
   forbidden source is unreachable rather than filtered;
2. permitted fields must be identical across the two revisions, or the question
   is excluded rather than adjusted;
3. every question carries a source-coverage status over its target atom, its
   evidence facts and its envelope membership.

The scorer, the ranking and the envelope layer are imported. INC-V2-007 and
INC-V2-009 were both caused by writing ranking logic a second time.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "facets"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retrieval"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file  # noqa: E402
from envelope import build_envelopes, is_enumeration_marker  # noqa: E402
from evidence import write_immutable  # noqa: E402
from facet_coverage import SEMANTIC, project  # noqa: E402
from intent_view import (  # noqa: E402
    ANCHOR,
    DOC_TYPE,
    FORBIDDEN_INTENT_SOURCES,
    IDENTITY,
    INTENT_CHANGED,
    PARENT,
    PERMITTED_INTENT_SOURCES,
    TITLE,
    ForbiddenIntentSource,
    IntentView,
    build_query,
    revision_neutral_fields,
)
from run_p4b import FIELD_WEIGHTS, FieldedBm25, rank, tokenise  # noqa: E402
from source_spans import (  # noqa: E402
    IGNORED,
    MODELED,
    UNMODELED,
    attribute_to_canonical,
    html_spans,
    markdown_spans,
    reference_facts,
)

PROTOCOL = NS / "protocols" / "P4e_provenance_retrieval.yaml"
SCORER = NS / "tools" / "run_p4b.py"
ENVELOPE = NS / "retrieval" / "envelope.py"
INTENT = NS / "retrieval" / "intent_view.py"
PER_DOCUMENT_CAP = 12

#: Diagnostic only. Kept so the overlap figure P4d gated on can still be read
#: beside the provenance result, which is the point of reporting both.
FUNCTION_WORDS = frozenset(
    """a an and are as at be by do does for from has have he in is it its of on
    or say says shall she that the their them there they this to under was were
    what when where which who will with you your""".split()
)

#: Locality rule for source coverage, declared before it is applied.
#:
#: Where the classifier yields character offsets (markdown), an unmodeled span
#: is *relevant* to a question when it lies inside the raw offset range spanned
#: by the atoms in scope. Where it yields parser events (HTML, XML), offsets are
#: not comparable to a text range, so the document-level rule applies: any
#: unmodeled fact anywhere in the document makes every question in it locally
#: incomplete.
#:
#: The direction of error differs between the two and both are stated. The
#: positional rule can miss an unmodeled construct outside the range that still
#: bears on the atom — a link reference definition at the foot of a file, say —
#: so it can over-grant local completeness. The document-level rule can only
#: under-grant. Neither is allowed to imply anything about the document as a
#: whole: a revision that is SOURCE_COVERAGE_INCOMPLETE stays so.
POSITIONAL = "character_offsets"
DOCUMENT_LEVEL = "parser_events"

LOCAL_COMPLETE = "QUESTION_LOCAL_COVERAGE_COMPLETE"
LOCAL_INCOMPLETE = "QUESTION_LOCAL_COVERAGE_INCOMPLETE"


def classify_source(raw: bytes, suffix: str, unit_texts: list[str]) -> dict[str, Any]:
    """Span classification for one raw source, with its granularity recorded."""
    text = raw.decode("utf-8", errors="replace")
    if suffix == ".md":
        spans = markdown_spans(text)
        granularity = POSITIONAL
    else:
        spans = html_spans(text)
        granularity = DOCUMENT_LEVEL
    facts = reference_facts(spans)
    attribute_to_canonical(spans, unit_texts, [str(f.get("target") or "") for f in facts])
    return {
        "spans": spans,
        "granularity": granularity,
        "reference_facts": facts,
        "unmodeled": [s for s in spans if s.classification == UNMODELED],
        "counts": {
            MODELED: sum(1 for s in spans if s.classification == MODELED),
            IGNORED: sum(1 for s in spans if s.classification == IGNORED),
            UNMODELED: sum(1 for s in spans if s.classification == UNMODELED),
        },
    }


def question_local_coverage(classified: dict[str, Any], scope_texts: list[str]) -> dict[str, Any]:
    """Coverage status over one question's target, evidence and envelope scope."""
    unmodeled = classified["unmodeled"]
    if classified["granularity"] == DOCUMENT_LEVEL:
        relevant = len(unmodeled)
        return {
            "status": LOCAL_COMPLETE if relevant == 0 else LOCAL_INCOMPLETE,
            "granularity": DOCUMENT_LEVEL,
            "relevant_unmodeled": relevant,
            "rule": "document-level; can only under-grant local completeness",
        }

    spans = classified["spans"]
    folded = {t for t in scope_texts if t}
    in_scope = [
        span
        for span in spans
        if span.classification == MODELED
        and any(span.text.strip() and span.text.strip() in text for text in folded)
    ]
    if not in_scope:
        return {
            "status": LOCAL_INCOMPLETE,
            "granularity": POSITIONAL,
            "relevant_unmodeled": len(unmodeled),
            "rule": "no modeled span could be placed in scope; not granted",
        }
    low = min(span.start for span in in_scope)
    high = max(span.end for span in in_scope)
    relevant = [span for span in unmodeled if span.start < high and span.end > low]
    return {
        "status": LOCAL_COMPLETE if not relevant else LOCAL_INCOMPLETE,
        "granularity": POSITIONAL,
        "relevant_unmodeled": len(relevant),
        "scope_range": [low, high],
        "rule": "positional; can over-grant if an out-of-range construct bears on the atom",
    }


def builder_reads_no_forbidden_name() -> dict[str, Any]:
    """Static check that ``build_query`` names no forbidden source.

    A runtime count of zero body accesses is necessary and not sufficient: it
    proves this run did not reach for one. Reading the builder's source proves
    it could not have.
    """
    tree = ast.parse(INTENT.read_text(encoding="utf-8"))
    builder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_query"
    )
    names = {node.id for node in ast.walk(builder) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(builder) if isinstance(node, ast.Attribute)
    }
    hits = sorted(names & set(FORBIDDEN_INTENT_SOURCES))
    return {
        "argument_count": len(builder.args.args),
        "single_restricted_argument": len(builder.args.args) == 1,
        "forbidden_names_referenced": hits,
        "passed": not hits and len(builder.args.args) == 1,
    }


def negative_controls() -> dict[str, Any]:
    """Two constructed controls that must be rejected by the gates they target."""
    body_token = {"rejected": False, "by": None}
    try:
        IntentView(
            "ctrl-body-token-injected",
            **{
                TITLE: "uv documentation",
                IDENTITY: "astral-sh/uv",
                DOC_TYPE: "documentation",
                ANCHOR: "Dependency fields",
                PARENT: "Managing dependencies",
                "atom_body": "the resolver reads dependency-groups from pyproject.toml",
            },
        )
    except ForbiddenIntentSource as error:
        body_token = {"rejected": True, "by": type(error).__name__, "detail": str(error)}

    before = {
        TITLE: "Ozone layer",
        IDENTITY: "Ozone layer",
        DOC_TYPE: "encyclopedia article",
        ANCHOR: "Depletion",
        PARENT: None,
    }
    after = {**before, ANCHOR: "Depletion and recovery"}
    fields, differing = revision_neutral_fields(before, after)
    current_only = {
        "rejected": fields is None,
        "by": INTENT_CHANGED if fields is None else None,
        "differing_fields": differing,
    }
    return {
        "ctrl_body_token_injected": body_token,
        "ctrl_current_only_heading": current_only,
        "passed": bool(body_token["rejected"] and current_only["rejected"]),
    }


def build(manifest: Path) -> dict[str, Any]:
    cohort = json.loads(manifest.read_text(encoding="utf-8"))
    index_rows: list[dict[str, Any]] = []
    envelopes: list[Any] = []
    questions: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    atoms: dict[str, dict[str, Any]] = {}

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
        old_env_by_anchor = {e.anchor_path: e for e in old_envs}

        moved: set[str] = set()
        for atom_id, atom in cur_atoms.items():
            prior = old_by_path.get(atom["path"])
            if prior is not None and project(SEMANTIC, prior) != project(SEMANTIC, atom):
                moved.add(atom_id)

        classified = classify_source(
            (ROOT / record["after"]["raw_path"]).read_bytes(),
            record["suffix"],
            [a["text"] for a in cur_atoms.values()],
        )

        revised = 0
        unchanged = 0
        for env in cur_envs:
            parts = env.anchor_path.split("/")
            anchor_heading = parts[-1]
            parent_heading = parts[-2] if len(parts) >= 2 else None
            if is_enumeration_marker(anchor_heading):
                excluded.append(
                    {"document": slug, "anchor": env.anchor_path, "reason": "ANCHOR_IS_A_MARKER"}
                )
                continue

            prior_env = old_env_by_anchor.get(env.anchor_path)
            after_fields = {
                TITLE: record["title_field"],
                IDENTITY: record["identity"],
                DOC_TYPE: record["spoken_type"],
                ANCHOR: anchor_heading,
                PARENT: None
                if parent_heading and is_enumeration_marker(parent_heading)
                else parent_heading,
            }
            before_fields = (
                after_fields if prior_env is not None else {**after_fields, ANCHOR: None}
            )
            neutral, differing = revision_neutral_fields(before_fields, after_fields)
            if neutral is None:
                excluded.append(
                    {
                        "document": slug,
                        "anchor": env.anchor_path,
                        "reason": INTENT_CHANGED,
                        "differing_fields": differing,
                    }
                )
                continue

            view = IntentView(slug + "|" + env.anchor_path, **neutral)
            query = build_query(view)
            provenance = view.provenance()
            if not tokenise(query):
                excluded.append(
                    {"document": slug, "anchor": env.anchor_path, "reason": "EMPTY_QUERY"}
                )
                continue

            scope_texts = [cur_atoms[a]["text"] for a in env.member_ids]
            coverage_status = question_local_coverage(classified, scope_texts)

            for atom_id in env.member_ids:
                atom = cur_atoms[atom_id]
                if atom["path"] not in old_by_path:
                    continue
                is_moved = atom_id in moved
                kind = "Q1_REVISED_VALUE" if is_moved else "C1_UNCHANGED_CONTROL"
                if is_moved and revised >= PER_DOCUMENT_CAP:
                    continue
                if not is_moved and unchanged >= PER_DOCUMENT_CAP:
                    continue
                overlap = sorted(
                    t
                    for t in set(tokenise(query)) & set(tokenise(atom["text"]))
                    if t not in FUNCTION_WORDS
                )
                questions.append(
                    {
                        "question_id": slug + "|" + kind + "|" + atom["path"],
                        "kind": kind,
                        "pair_id": slug,
                        "source_family": family,
                        "query": query,
                        "provenance": provenance,
                        "forbidden_contribution": [
                            p for p in provenance if p["provenance"] not in PERMITTED_INTENT_SOURCES
                        ],
                        "anchor_path": env.anchor_path,
                        "target_envelope": env.envelope_id,
                        "evidence_atom": atom_id,
                        "atom_path": atom["path"],
                        "source_coverage": coverage_status,
                        "lexical_overlap_tokens": overlap,
                        "lexical_overlap_is_diagnostic_only": True,
                    }
                )
                if is_moved:
                    revised += 1
                else:
                    unchanged += 1

    return {
        "index_rows": index_rows,
        "envelopes": envelopes,
        "atoms": atoms,
        "questions": questions,
        "excluded": excluded,
    }


def evaluate(
    index: FieldedBm25,
    questions: list[dict[str, Any]],
    scopes: dict[str, set[str]],
    envelope_by_id: dict[str, Any],
    envelope_unit: dict[str, str],
) -> list[dict[str, Any]]:
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
        out[family]["question_local_coverage_complete"] = sum(
            1 for r in subset if r["source_coverage"]["status"] == LOCAL_COMPLETE
        ) / len(subset)
        out[family]["lexical_overlap_present"] = sum(
            1 for r in subset if r["lexical_overlap_tokens"]
        ) / len(subset)
    return out


def run(manifest: Path) -> int:
    started = now()
    built = build(manifest)
    envelopes = built["envelopes"]
    envelope_by_id = {e.envelope_id: e for e in envelopes}
    envelope_unit = {e.envelope_id: e.document_id + "|" + e.anchor_path for e in envelopes}
    scopes: dict[str, set[str]] = {}
    for row in built["index_rows"]:
        scopes.setdefault(row["pair_id"], set()).add(row["doc_id"])

    index = FieldedBm25(built["index_rows"])
    reversed_index = FieldedBm25(list(reversed(built["index_rows"])))
    rows = evaluate(index, built["questions"], scopes, envelope_by_id, envelope_unit)
    check = evaluate(reversed_index, built["questions"], scopes, envelope_by_id, envelope_unit)
    deterministic = all(
        left.get("top_score") == right.get("top_score")
        and left.get("tied_set") == right.get("tied_set")
        for left, right in zip(rows, check, strict=True)
    )

    scored = [row for row in rows if row["state"] == "SCORED"]
    q1 = [row for row in scored if row["kind"] == "Q1_REVISED_VALUE"]
    families = sorted({row["source_family"] for row in scored})
    documents = len({row["pair_id"] for row in scored})

    provenance_ok = all(
        row["provenance"]
        and all(p["provenance"] in PERMITTED_INTENT_SOURCES for p in row["provenance"])
        for row in scored
    )
    forbidden_total = sum(len(row["forbidden_contribution"]) for row in scored)
    static = builder_reads_no_forbidden_name()
    controls = negative_controls()
    intent_changed = [e for e in built["excluded"] if e["reason"] == INTENT_CHANGED]
    locally_complete = [row for row in scored if row["source_coverage"]["status"] == LOCAL_COMPLETE]

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
    diagnostics = {
        "lexical_overlap_present_share": share(scored, "lexical_overlap_tokens"),
        "status": "DIAGNOSTIC_ONLY",
        "not_a_leakage_gate": (
            "under the founder ruling of 2026-08-22 leakage is a provenance "
            "property. This figure is reported beside the provenance result and "
            "never gated. P4d gated it and failed 475 questions that carried no "
            "answer span."
        ),
    }
    coverage_summary = {
        "question_local_coverage_complete": len(locally_complete),
        "question_local_coverage_complete_share": (
            len(locally_complete) / len(scored) if scored else 0.0
        ),
        "gpu_confirmatory_candidates": len(locally_complete),
        "document_revisions_still_incomplete": (
            "P0d's 26 of 26 SOURCE_COVERAGE_INCOMPLETE stands. A locally "
            "complete question is not a claim about its document."
        ),
        "by_granularity": {
            g: sum(1 for r in scored if r["source_coverage"]["granularity"] == g)
            for g in sorted({r["source_coverage"]["granularity"] for r in scored})
        },
    }

    gates = {
        "G_P4E_PROVENANCE": {"passed": provenance_ok},
        "G_P4E_NO_FORBIDDEN_CONTRIBUTION": {
            "passed": forbidden_total == 0,
            "value": forbidden_total,
            "threshold": 0,
        },
        "G_P4E_NO_BODY_ACCESS": {"passed": static["passed"], "static_check": static},
        "G_P4E_REVISION_NEUTRAL": {
            "passed": True,
            "held_by": "construction: a differing permitted field excludes the question",
            "excluded_as_intent_changed": len(intent_changed),
        },
        "G_P4E_CONTROLS_REJECTED": {"passed": controls["passed"], "controls": controls},
        "G_P4E_SCALE": {
            "passed": len(scored) >= 250 and documents >= 40 and len(families) >= 4,
            "questions": len(scored),
            "documents": documents,
            "families": families,
        },
        "G_P4E_Q1_SCALE": {"passed": len(q1) >= 100, "value": len(q1), "threshold": 100},
        "G_P4E_ENVELOPE_RETRIEVABLE": {
            "passed": measures["envelope_retrievable_at_10"] >= 0.90,
            "value": measures["envelope_retrievable_at_10"],
            "threshold": 0.90,
        },
        "G_P4E_ATOM_RECOVERABLE": {
            "passed": measures["atom_recoverable_from_envelope"] >= 0.95,
            "value": measures["atom_recoverable_from_envelope"],
            "threshold": 0.95,
        },
        "G_P4E_COVERAGE_RECORDED": {
            "passed": all(row.get("source_coverage") for row in scored),
            "note": "gates the recording, not the outcome",
        },
        "G_P4E_DETERMINISM": {"passed": deterministic},
        "G_P4E_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }
    verdict = "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL"

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p4e_provenance_retrieval.v1",
        "protocol": "P4e_provenance_retrieval",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "programme_status": "PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED",
        "cohort_manifest": rel(manifest),
        "cohort_manifest_file_sha256": sha_file(manifest),
        "predecessors_read_only": {
            "P4c_core": "FAIL",
            "P4c_global": "PASS",
            "P4d_core_semantic": "FAIL",
            "P4d_citation": "PASS, kept separate and not mixed into any semantic figure",
            "P0d": "PASS on its own gates; 26 of 26 pairs SOURCE_COVERAGE_INCOMPLETE stands",
        },
        "scorer_source": rel(SCORER),
        "scorer_sha256": sha_file(SCORER),
        "envelope_source": rel(ENVELOPE),
        "envelope_sha256": sha_file(ENVELOPE),
        "intent_view_source": rel(INTENT),
        "intent_view_sha256": sha_file(INTENT),
        "field_weights": FIELD_WEIGHTS,
        "permitted_intent_sources": list(PERMITTED_INTENT_SOURCES),
        "forbidden_intent_sources": list(FORBIDDEN_INTENT_SOURCES),
        "canonical_atom_count": len(built["atoms"]),
        "envelope_count": len(envelopes),
        "index_size": len(built["index_rows"]),
        "excluded": built["excluded"][:400],
        "excluded_count": len(built["excluded"]),
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
        "lexical_overlap_diagnostic": diagnostics,
        "source_coverage": coverage_summary,
        "endpoints": {
            "controlled_currency": "measurable on locally coverage-complete targets",
            "source_faithful_end_to_end": (
                "NOT_ESTABLISHED. Front-end source coverage is unresolved and no "
                "figure here may be read as establishing it."
            ),
            "never_combined": True,
        },
        "gates": gates,
        "verdict": verdict,
        "determinism_check": {"reversed_insertion_order_reproduces_every_score": deterministic},
        "gpu_authorised_by_this_result": False,
        "consequence_of_pass": (
            "a model study becomes eligible to be PROPOSED. The proposal — same "
            "model, same decoding, same retrieval-context budget, four arms, "
            "primary endpoint, statistical test, frozen cohort, source-coverage "
            "eligibility, GPU hours, cost ceiling and stop rule — is submitted "
            "and approved before any GPU runs."
        ),
        "rows": rows,
        "rows_sha256": canonical_sha(rows),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable(
        "p4e-provenance-retrieval", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "verdict": verdict,
                "questions": len(scored),
                "q1": len(q1),
                "documents": documents,
                "families": families,
                "measures": {
                    k: (round(v, 4) if isinstance(v, float) else v) for k, v in measures.items()
                },
                "locally_complete_share": round(
                    coverage_summary["question_local_coverage_complete_share"], 4
                ),
                "lexical_overlap_present_share": round(
                    diagnostics["lexical_overlap_present_share"], 4
                ),
                "intent_changed_exclusions": len(intent_changed),
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if verdict == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=NS / "artifacts" / "development" / "p4e_cohort.json",
    )
    args = parser.parse_args()
    return run(args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
