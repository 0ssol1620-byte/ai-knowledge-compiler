#!/usr/bin/env python3
"""MODEL_ENDPOINT_V1 preflight. Everything the GPU run needs, decided on CPU.

Nothing here calls a model. It materialises every input the study will send —
query, prompt, context, ordering, provenance, token count, truncation — under
the pinned tokenizer, applies the context-validity filter and the value
distinguishability filter, assigns the arm schedule, runs the scorer controls,
and seals the lot in an immutable receipt.

The eligibility labels are **read from the sealed P4i receipt**, not recomputed.
P4i was scored once and stays scored once. What is regenerated here is only the
deterministic retrieval machinery — same inputs, same code, same outputs — so
that the queries and rankings the contexts are built from are the ones P4i used.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "endpoint"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retrieval"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file  # noqa: E402
from context_builder import (  # noqa: E402
    APPEND_ONLY,
    ARMS,
    COMPILED_CURRENT,
    FULL_CURRENT_ORACLE,
    MAX_NEW_TOKENS,
    SINGLE_REVISION_ARMS,
    SUPERSEDED_CONTROL,
    TOTAL_PROMPT_TOKENS,
    arm_candidates,
    fit_to_budget,
    prompt_carries_no_arm_label,
    prompt_parts,
    prompt_template_digest,
    schedule,
    schedule_balance,
)
from envelope import build_envelopes  # noqa: E402
from evidence import write_immutable  # noqa: E402
from run_p4b import FieldedBm25  # noqa: E402
from run_p4e import PERMITTED_INTENT_SOURCES, build, evaluate  # noqa: E402
from value_scorer import CLASSES, markers, run_controls  # noqa: E402

PROTOCOL = NS / "protocols" / "MODEL_ENDPOINT_V1.yaml"
MANIFEST = NS / "artifacts" / "development" / "p4i_cohort.json"
ATTESTATION = (
    ROOT
    / "research"
    / "experiments"
    / "H1-W6-SAME-INTELLIGENCE-01"
    / "receipts"
    / "v8-model-attestation.json"
)
INPUTS = NS / "artifacts" / "development" / "model_endpoint_inputs.json"

COHORT_FLOOR = 190
TRUNCATION_CEILING = 0.25

RUNTIME = {
    "serving_runtime": "vllm",
    "serving_runtime_version": "0.27.1",
    "dtype": "bfloat16",
    "quantization": "none",
    "temperature": 0.0,
    "decoding": "greedy",
    "max_new_tokens": MAX_NEW_TOKENS,
    "thinking": "off",
    "tools": "off",
    "runtime_image_digest": (
        "runpod/pytorch@sha256:0a360022e8de4375af99430f84e8b38951acc397252163a37ceac7204d01be35"
    ),
    "attested_gpu": "NVIDIA H200",
}


# --- model identity -----------------------------------------------------------


def verify_model_identity() -> dict[str, Any]:
    """The pinned tokenizer, checked two ways: its bytes and its behaviour."""
    attested = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    revision = attested["checkpoint_revision"]
    repository = attested["repository"]
    probe_text = attested["tokenizer_behaviour_probe"]["text"]
    expected_tokens = attested["tokenizer_behaviour_probe"]["token_count"]

    from huggingface_hub import hf_hub_download  # noqa: PLC0415
    from transformers import AutoTokenizer  # noqa: PLC0415

    tokenizer_path = hf_hub_download(repository, "tokenizer.json", revision=revision)
    digest = "sha256:" + sha256(Path(tokenizer_path).read_bytes()).hexdigest()
    template_path = hf_hub_download(repository, "chat_template.jinja", revision=revision)
    template_digest = "sha256:" + sha256(Path(template_path).read_bytes()).hexdigest()

    tokenizer = AutoTokenizer.from_pretrained(repository, revision=revision)
    observed_tokens = len(tokenizer.encode(probe_text, add_special_tokens=False))

    return {
        "tokenizer": tokenizer,
        "record": {
            "repository": repository,
            "revision": revision,
            "tokenizer_revision": revision,
            "source_of_pin": rel(ATTESTATION),
            "tokenizer_file_sha256": digest,
            "tokenizer_file_sha256_attested": attested["tokenizer_hash"],
            "tokenizer_file_matches": digest == attested["tokenizer_hash"],
            "chat_template_sha256": template_digest,
            "chat_template_sha256_attested": attested["model_file_manifest"]["chat_template.jinja"][
                "sha256"
            ],
            "chat_template_matches": template_digest
            == "sha256:" + attested["model_file_manifest"]["chat_template.jinja"]["sha256"],
            "behaviour_probe": {
                "text": probe_text,
                "expected_tokens": expected_tokens,
                "observed_tokens": observed_tokens,
                "matches": observed_tokens == expected_tokens,
            },
            "tokenizer_class_here": type(tokenizer).__name__,
            "tokenizer_class_attested": attested["tokenizer_identity"]["tokenizer_class"],
            "added_tokens_here": len(tokenizer.get_added_vocab()),
            "added_tokens_attested": attested["tokenizer_identity"]["added_tokens"],
            "vocab_size_here": tokenizer.vocab_size,
            "vocab_size_attested": attested["tokenizer_identity"]["vocab_size"],
            "vocab_size_note": (
                "the two libraries report this field differently — transformers "
                "here excludes added tokens. Identity rests on the file digest "
                "and the behaviour probe, which match exactly."
            ),
            "no_auto_update": "pinned by commit; resolving to latest is forbidden",
        },
    }


def token_counter(tokenizer: Any):
    def count(system: str, user: str) -> int:
        text = tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tokenize=False,
            add_generation_prompt=True,
        )
        return len(tokenizer.encode(text, add_special_tokens=False))

    return count


# --- cohort -------------------------------------------------------------------


def eligible_question_ids(receipt: Path) -> tuple[set[str], dict[str, Any]]:
    body = json.loads(receipt.read_text(encoding="utf-8"))
    ids = {
        row["question_id"]
        for row in body["coverage_rows"]
        if row["status"] == "QUESTION_LOCAL_COVERAGE_COMPLETE" and row["kind"] == "Q1_REVISED_VALUE"
    }
    return ids, {
        "receipt": rel(receipt),
        "receipt_file_sha256": sha_file(receipt),
        "eligible_q1_in_receipt": body["totals"]["locally_complete_q1"],
        "read_not_recomputed": (
            "P4i was scored once and stays scored once. Coverage labels are read "
            "from its sealed receipt; only the deterministic retrieval machinery "
            "is regenerated."
        ),
    }


def atoms_for(record: dict[str, Any], slug: str) -> dict[str, Any]:
    sides: dict[str, Any] = {}
    for revision, key in (("current", "after"), ("superseded", "before")):
        document = json.loads((ROOT / record[key]["canonical_path"]).read_text(encoding="utf-8"))
        envelopes, atoms = build_envelopes(
            slug,
            revision,
            document["units"],
            {"title": record["title_field"], "doc_type": record["doc_type"]},
        )
        sides[revision] = {"envelopes": envelopes, "atoms": atoms}
    return sides


def ranked_atoms(
    envelopes: list[Any], atoms: dict[str, Any], scores: dict[str, float]
) -> list[dict[str, Any]]:
    """Envelopes by score, then their member atoms in document order."""
    ordered = sorted(envelopes, key=lambda e: (-scores.get(e.envelope_id, 0.0), e.anchor_path))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for envelope in ordered:
        for atom_id in envelope.member_ids:
            atom = atoms.get(atom_id)
            if atom is None or atom_id in seen:
                continue
            seen.add(atom_id)
            out.append({"atom_id": atom_id, "path": atom["path"], "text": atom["text"]})
    return out


def document_order_atoms(atoms: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"atom_id": atom_id, "path": atom["path"], "text": atom["text"]}
        for atom_id, atom in sorted(atoms.items(), key=lambda kv: kv[1].get("ordinal", 0))
    ]


def run(manifest: Path, receipt: Path) -> int:
    started = now()
    identity = verify_model_identity()
    tokenizer = identity["tokenizer"]
    count = token_counter(tokenizer)

    eligible, provenance_of_labels = eligible_question_ids(receipt)
    built = build(manifest)
    envelope_by_id = {e.envelope_id: e for e in built["envelopes"]}
    envelope_unit = {e.envelope_id: e.document_id + "|" + e.anchor_path for e in built["envelopes"]}
    scopes: dict[str, set[str]] = {}
    for row in built["index_rows"]:
        scopes.setdefault(row["pair_id"], set()).add(row["doc_id"])
    index = FieldedBm25(built["index_rows"])
    rows = evaluate(index, built["questions"], scopes, envelope_by_id, envelope_unit)
    candidates = [
        row for row in rows if row["state"] == "SCORED" and row["question_id"] in eligible
    ]

    cohort = {
        record["document_slug"]: record
        for record in json.loads(manifest.read_text(encoding="utf-8"))["documents"]
    }
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_pair.setdefault(row["pair_id"], []).append(row)

    materialized: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for slug, questions in sorted(by_pair.items()):
        record = cohort[slug]
        sides = atoms_for(record, slug)
        current_atoms = sides["current"]["atoms"]
        superseded_atoms = sides["superseded"]["atoms"]
        superseded_by_path = {a["path"]: (aid, a) for aid, a in superseded_atoms.items()}
        scope = scopes[slug]

        for row in sorted(questions, key=lambda r: r["question_id"]):
            query = row["query"]
            target_id = row["evidence_atom"]
            target = current_atoms.get(target_id)
            path = row["atom_path"]
            prior = superseded_by_path.get(path)
            if target is None or prior is None:
                excluded.append(
                    {"question_id": row["question_id"], "reason": "NO_SUPERSEDED_COUNTERPART"}
                )
                continue
            prior_id, prior_atom = prior

            distinguishing = markers(target["text"], prior_atom["text"])
            if not distinguishing["distinguishable"]:
                excluded.append(
                    {
                        "question_id": row["question_id"],
                        "reason": "VALUES_NOT_DISTINGUISHABLE",
                        "detail": distinguishing["reasons"],
                    }
                )
                continue

            scores = index.score_all(query, scope)
            current_ranked = ranked_atoms(sides["current"]["envelopes"], current_atoms, scores)
            superseded_ranked = ranked_atoms(
                sides["superseded"]["envelopes"], superseded_atoms, scores
            )
            merged = sorted(
                current_ranked + superseded_ranked,
                key=lambda a: (
                    -scores.get(a["atom_id"].rsplit("|", 1)[0], 0.0),
                    a["path"],
                    a["atom_id"],
                ),
            )
            oracle = document_order_atoms(current_atoms)

            arm_records: dict[str, Any] = {}
            invalid: list[str] = []
            for arm in ARMS:
                pool = arm_candidates(arm, current_ranked, superseded_ranked, oracle, merged)
                fitted = fit_to_budget(query, pool, count, TOTAL_PROMPT_TOKENS)
                wanted = prior_id if arm == SUPERSEDED_CONTROL else target_id
                present = wanted in fitted["context_atom_ids"]
                fitted["target_evidence_atom"] = wanted
                fitted["target_evidence_present"] = present
                fitted["prompt_sha256"] = (
                    "sha256:"
                    + sha256(
                        (fitted["system"] + "\x00" + fitted["user"]).encode("utf-8")
                    ).hexdigest()
                )
                arm_records[arm] = fitted
                if arm in SINGLE_REVISION_ARMS and not present:
                    invalid.append(arm)

            if invalid:
                excluded.append(
                    {
                        "question_id": row["question_id"],
                        "reason": "TARGET_EVIDENCE_LOST_TO_TRUNCATION",
                        "arms": invalid,
                    }
                )
                continue

            materialized.append(
                {
                    "question_id": row["question_id"],
                    "pair_id": slug,
                    "source_family": row["source_family"],
                    "atom_path": path,
                    "query": query,
                    "provenance": row["provenance"],
                    "current_atom_id": target_id,
                    "superseded_atom_id": prior_id,
                    "current_markers": distinguishing["current"],
                    "superseded_markers": distinguishing["superseded"],
                    "arms": arm_records,
                }
            )

    assignment = schedule([q["question_id"] for q in materialized])
    balance = schedule_balance(assignment)
    for question in materialized:
        question["arm_order"] = assignment[question["question_id"]]

    truncation = {
        arm: (
            sum(1 for q in materialized if q["arms"][arm]["truncated"]) / len(materialized)
            if materialized
            else 0.0
        )
        for arm in ARMS
    }
    controls = run_controls()
    sample = (
        materialized[0]["arms"][COMPILED_CURRENT] if materialized else {"system": "", "user": ""}
    )
    label_check = prompt_carries_no_arm_label(sample["system"], sample["user"])
    family_counts = Counter(q["source_family"] for q in materialized)

    gates = {
        "G_ME1_MODEL_PINNED": {
            "passed": identity["record"]["tokenizer_file_matches"]
            and identity["record"]["behaviour_probe"]["matches"]
            and identity["record"]["chat_template_matches"],
            "detail": {
                k: identity["record"][k]
                for k in (
                    "tokenizer_file_matches",
                    "chat_template_matches",
                    "behaviour_probe",
                )
            },
        },
        "G_ME1_RUNTIME_DECLARED": {"passed": True, "runtime": RUNTIME},
        "G_ME1_INPUTS_MATERIALIZED": {
            "passed": bool(materialized)
            and all(
                set(q["arms"]) == set(ARMS)
                and all(
                    q["arms"][a].get("prompt_sha256") and q["arms"][a].get("context_token_count")
                    for a in ARMS
                )
                for q in materialized
            ),
            "questions": len(materialized),
            "arms": len(ARMS),
            "prompts": len(materialized) * len(ARMS),
        },
        "G_ME1_PROMPT_CARRIES_NO_ARM_LABEL": {
            "passed": label_check["clean"],
            "template_digest": label_check["digest"],
            "found": label_check["found"],
        },
        "G_ME1_CONTEXT_VALIDITY": {
            "passed": all(
                q["arms"][arm]["target_evidence_present"]
                for q in materialized
                for arm in SINGLE_REVISION_ARMS
            ),
            "single_revision_arms": list(SINGLE_REVISION_ARMS),
            "append_only_excluded_because": (
                "the two revisions crowd each other out of the budget, which is "
                "part of the intervention rather than a defect"
            ),
        },
        "G_ME1_TRUNCATION": {
            "passed": all(rate <= TRUNCATION_CEILING for rate in truncation.values()),
            "ceiling": TRUNCATION_CEILING,
            "rates": truncation,
        },
        "G_ME1_SCORER_CONTROLS": {
            "passed": controls["all_agree"] and controls["three_directions"]["passed"],
            "detail": controls["three_directions"],
            "count": len(controls["results"]),
        },
        "G_ME1_VALUES_DISTINGUISHABLE": {
            "passed": all(
                q["current_markers"]
                and q["superseded_markers"]
                and not (set(q["current_markers"]) & set(q["superseded_markers"]))
                for q in materialized
            ),
            "excluded_indistinguishable": sum(
                1 for e in excluded if e["reason"] == "VALUES_NOT_DISTINGUISHABLE"
            ),
        },
        "G_ME1_SCHEDULE_BALANCED": {
            "passed": balance["balanced"],
            "detail": balance,
        },
        "G_ME1_COHORT_FLOOR": {
            "passed": len(materialized) >= COHORT_FLOOR,
            "final_cohort": len(materialized),
            "floor": COHORT_FLOOR,
        },
        "G_ME1_NO_GPU_YET": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }
    verdict = "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL"

    INPUTS.parent.mkdir(parents=True, exist_ok=True)
    INPUTS.write_text(
        json.dumps(
            {
                "schema": "tavonel.v2.model_endpoint_inputs.v1",
                "protocol": "MODEL_ENDPOINT_V1",
                "model": {k: v for k, v in identity["record"].items()},
                "runtime": RUNTIME,
                "questions": materialized,
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    body: dict[str, Any] = {
        "schema": "tavonel.v2.model_endpoint_preflight.v1",
        "protocol": "MODEL_ENDPOINT_V1",
        "started_at": started,
        "ended_at": now(),
        "programme_status": "PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED",
        "split": "MODEL-ENDPOINT CONFIRMATORY — MODEL OUTCOMES UNSEEN",
        "split_note": (
            "the P4i corpus already carries retrieval and source-coverage "
            "development results. Only the model's answers have never been "
            "opened, so it is not an untouched confirmatory corpus."
        ),
        "model": identity["record"],
        "runtime": RUNTIME,
        "eligibility_labels": provenance_of_labels,
        "cohort_manifest": rel(manifest),
        "cohort_manifest_file_sha256": sha_file(manifest),
        "inputs_path": rel(INPUTS),
        "inputs_sha256": canonical_sha(materialized),
        "prompt_template_digest": prompt_template_digest(),
        "context_budget": {
            "total_prompt_tokens": TOTAL_PROMPT_TOKENS,
            "measured_with": "the pinned tokenizer, after the chat template",
            "max_new_tokens": MAX_NEW_TOKENS,
        },
        "totals": {
            "eligible_q1_from_p4i": len(eligible),
            "candidates_regenerated": len(candidates),
            "final_frozen_cohort": len(materialized),
            "excluded": len(excluded),
            "prompts_materialized": len(materialized) * len(ARMS),
        },
        "final_cohort_by_family": dict(family_counts),
        "excluded_by_reason": dict(Counter(e["reason"] for e in excluded)),
        "excluded_detail": excluded[:200],
        "truncation_rates": truncation,
        "schedule_balance": balance,
        "scorer": {
            "classes": list(CLASSES),
            "primary_success": "CURRENT_ONLY",
            "both_and_no_match_are_failures": True,
            "controls": controls,
            "deterministic_only": True,
        },
        "assay_sensitivity_gate": {
            "predicate": (
                "compiled_current current-value accuracy minus superseded_control accuracy >= 0.15"
            ),
            "kind": "VALIDITY GATE, not a significance test",
            "p_value": None,
            "evaluated": "after the full first pass of all four arms, never sequentially",
            "on_failure": "ENDPOINT_INSENSITIVE_TO_CURRENCY; no primary product-effect claim",
        },
        "primary_test": {
            "one_only": "exact McNemar, compiled_current versus append_only_stale_capable",
            "alpha": 0.05,
            "two_sided": True,
            "no_other_hypothesis_tests": True,
        },
        "budget": {"gpu_hours": 6, "hard_spend_cap_usd": 40},
        "gates": gates,
        "verdict": verdict,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "gpu_authorised": verdict == "PASS",
        "gpu_authorisation_note": (
            "the founder approved execution without a further check-in on "
            "condition that this preflight passes. It has not run any model."
        ),
    }
    written = write_immutable(
        "model-endpoint-preflight", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "verdict": verdict,
                "final_cohort": len(materialized),
                "by_family": dict(family_counts),
                "excluded": dict(Counter(e["reason"] for e in excluded)),
                "truncation_rates": truncation,
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if verdict == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument(
        "--p4i-receipt",
        type=Path,
        default=NS / "receipts" / "p4i--20260822T142215Z-d7c7ff4a8c3b.json",
    )
    args = parser.parse_args()
    return run(args.manifest, args.p4i_receipt)


if __name__ == "__main__":
    raise SystemExit(main())
