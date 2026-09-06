#!/usr/bin/env python3
"""Seal the corpus-v7 run as DEVELOPMENT, and make the seal mechanically checkable.

PROTOCOL_V2 §10: a run whose configuration changes after results are seen is
sealed as development and a new untouched holdout is required. The v7 pre-arm
gates failed, the design is changing because of what they showed, and so v7 is
development evidence by that rule — not a weaker result, and not an outcome.

A seal written only in prose is a promise. This pins every v7 artifact by sha256
so that "v7 was not edited afterwards" is a check rather than an assurance, and
so that "no v8 holdout title was used in v7" can be verified against a fixed
list of titles rather than against memory.

Re-running this script **verifies** the seal when the manifest already exists;
it writes one only when there is none. It never overwrites a seal, because a
seal that can be silently reissued is not a seal.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
OUTPUT = EXP / "receipts" / "v7-development-seal-2026-08-19.json"

#: Every artifact the v7 run produced or depended on. Sealing the protocol and
#: the instrument alongside the results is the point: a result is only fixed if
#: the thing that produced it is fixed too.
SEALED = [
    "PROTOCOL_V2_2026-08-19.md",
    "QUESTION_SET_V7_RESULT_2026-08-19.md",
    "receipts/question-set-v7-2026-08-19.json",
    "receipts/v7-pre-arm-gates-2026-08-19.json",
    "receipts/acquisition-v7-2026-08-19.json",
    "receipts/v7-corpus-integrity-2026-08-19.json",
    "receipts/v7-endpoint-sufficiency-2026-08-19.json",
    "receipts/v7-launch-provenance-2026-08-19.json",
    "receipts/title-manifest-v3-2026-08-19.json",
    "scripts/build_question_set_v2.py",
    "scripts/build_question_set_v7.py",
    "scripts/gate_question_set_v7.py",
    "scripts/acquire_w6_v3.py",
]


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def build() -> dict[str, Any]:
    acq = json.loads((EXP / "receipts/acquisition-v7-2026-08-19.json").read_text("utf-8"))
    qs = json.loads((EXP / "receipts/question-set-v7-2026-08-19.json").read_text("utf-8"))
    gates = json.loads((EXP / "receipts/v7-pre-arm-gates-2026-08-19.json").read_text("utf-8"))
    integrity = json.loads(
        (EXP / "receipts/v7-corpus-integrity-2026-08-19.json").read_text("utf-8"))

    records = acq.get("records", [])
    v7_titles = sorted({r["title"] for r in records})
    v7_resolved = sorted(
        {r.get("resolved_title_before") for r in records}
        | {r.get("resolved_title_after") for r in records}
    )
    v7_touched = sorted(
        set(v7_titles) | {t for t in v7_resolved if t}
        | {e.get("title") for e in acq.get("exclusions", []) if e.get("title")}
    )

    return {
        "schema": "tavonel.w6-v7-development-seal.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "sealed_at": datetime.now(UTC).isoformat(),
        "classification": "SEALED_DEVELOPMENT_PROTOCOL_CONFLICT_RUN",
        "authority": (
            "PROTOCOL_V2 section 10: prompt, retrieval, top-k and questions are frozen at "
            "sections 1-6, and if any needs changing after results are seen, that run is "
            "sealed as development and a new untouched holdout question set is required. "
            "The v7 pre-arm gates failed and the design is changing because of what they "
            "showed, so v7 is development by that rule."
        ),
        "what_this_does_not_mean": [
            "not a retraction: every v7 measurement stands as measured",
            "not a weaker result: it is development evidence, which is a role, not a grade",
            "not permission to re-run v7 with different thresholds or templates -- the same "
            "293 questions over the same 151 articles may not be re-gated",
        ],
        "authoritative_v7_result": {
            "corpus": {
                "eligible_pages": acq.get("eligible_records"),
                "revision_sensitive_items": acq.get("primary_revision_sensitive_retained"),
                "articles_with_primary": acq.get("articles_with_primary"),
                "unchanged_controls": acq.get("unchanged_controls"),
                "integrity_gates_passed": integrity.get("gates_passed"),
                "integrity_gates_total": (
                    integrity.get("gates_passed", 0) + integrity.get("gates_failed", 0)
                    + integrity.get("gates_unknown", 0)),
                "incomplete_directories": 0,
                "corpus_root_sha256": integrity.get("corpus_root_sha256"),
            },
            "question_construction": {
                "acquisition_vs_independent_reparse_disagreements":
                    qs.get("attribute_change_set_disagreements"),
                "documents_with_parsable_infoboxes": qs.get("documents_with_parsable_infoboxes"),
            },
            "class_states": qs.get("class_states"),
            "conflicting_evidence": {
                "count": 0,
                "classification": "NOT_RUN_INSUFFICIENT_REAL_CASES",
                "why": (
                    "measured: no (subject, attribute) carries two different values over "
                    "overlapping validity. A corpus property."
                ),
            },
            "multi_document": {
                "count": 0,
                "classification": "NOT_RUN_GENERATOR_SCOPE_LIMITATION",
                "why": (
                    "the frozen section 2 generator asks one attribute of one article's "
                    "infobox, which is answerable from one document. A generator property, "
                    "not insufficient real data, and acquisition would not change it."
                ),
            },
            "pre_arm": {
                "arms_run": False,
                "leakage_gate": gates.get("leakage_gate"),
                "baseline_gate": gates.get("baseline_gate"),
                "leakage_median": 0.750, "leakage_p90": 0.857,
                "frozen_limits": {"median": 0.50, "p90": 0.75},
                "verbatim_containment": 0,
                "diagnostic_only_subject_tokens_excluded": {"median": 0.500, "p90": 0.667},
                "baseline_examples": {
                    "recall_at_1": 0.1887,
                    "same_document_top1_share": 0.9585,
                    "exact_tie_rate": 0.1038,
                },
            },
            "interpretation": (
                "Under the v7 subject-titled representation, the frozen section 2 templates, "
                "and the current BM25 / section-unit-indexing baseline, the section 3 and "
                "section 5 gates could not be jointly satisfied. This is a protocol-design "
                "finding, not an impossibility result: no other retrieval architecture, "
                "chunking, subject representation or admissible baseline was measured."
            ),
            "forbidden_wording": [
                "inherently unsatisfiable",
                "mathematically incompatible",
                "impossible for subject-titled questions",
                "no valid RAG baseline can satisfy the gates",
                "mutually unsatisfiable",
            ],
        },
        "development_titles_excluded_from_v8": {
            "count": len(v7_touched),
            "titles": v7_touched,
            "rule": (
                "every title v7 fetched, resolved to, or excluded is development data. A v8 "
                "holdout may contain none of them, at article level, and the v8 manifest "
                "builder checks against this list rather than against a recollection."
            ),
        },
        "sealed_artifacts": [
            {"path": rel, "sha256": sha256_file(EXP / rel)} for rel in SEALED
        ],
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }


def main() -> int:
    fresh = build()
    if OUTPUT.exists():
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
        drift = []
        recorded = {a["path"]: a["sha256"] for a in existing.get("sealed_artifacts", [])}
        for artifact in fresh["sealed_artifacts"]:
            was = recorded.get(artifact["path"])
            if was is None:
                drift.append({"path": artifact["path"], "state": "NOT_IN_SEAL"})
            elif was != artifact["sha256"]:
                drift.append({"path": artifact["path"], "state": "MODIFIED_AFTER_SEAL",
                              "sealed": was, "now": artifact["sha256"]})
        print(f"seal exists, sealed at {existing.get('sealed_at')}")
        print(f"artifacts checked: {len(fresh['sealed_artifacts'])}   drift: {len(drift)}")
        for d in drift:
            print(f"  {d['state']:<22} {d['path']}")
        print("SEAL INTACT" if not drift else "SEAL BROKEN")
        return 0 if not drift else 1

    fresh["seal_sha256"] = canonical_sha256(fresh)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(fresh, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"sealed {len(fresh['sealed_artifacts'])} artifacts")
    print(f"development titles excluded from v8: "
          f"{fresh['development_titles_excluded_from_v8']['count']}")
    print(f"wrote {OUTPUT.resolve().relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
