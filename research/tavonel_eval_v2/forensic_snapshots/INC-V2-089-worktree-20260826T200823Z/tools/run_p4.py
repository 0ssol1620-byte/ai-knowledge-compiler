#!/usr/bin/env python3
"""P4 retrieval-validity preflight. CPU only, no model, no spend.

Builds a lexical index over both revisions of every admitted pair, constructs
revision-sensitive questions from fields independent of the answer, and measures
whether the representation can tell a current fact from a superseded one at all.

The gate thresholds were frozen before this file produced a single score.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "facets"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file, write_hashed  # noqa: E402
from facets import SEMANTIC, project  # noqa: E402

TOKEN = re.compile(r"\w+", re.UNICODE)
K1 = 1.2
B = 0.75
PER_PAIR_CAP = 6
TOP_K = 10


def tokenise(text: str) -> list[str]:
    return [token for token in TOKEN.findall(text.casefold()) if len(token) >= 2]


class Bm25Index:
    """Deterministic BM25. Scores depend on the document set, never on order."""

    def __init__(self, documents: list[tuple[str, str]]) -> None:
        self.ids = [identifier for identifier, _ in documents]
        self.tokens = {identifier: tokenise(text) for identifier, text in documents}
        self.lengths = {identifier: len(value) for identifier, value in self.tokens.items()}
        self.average = sum(self.lengths.values()) / len(self.lengths) if self.lengths else 0.0
        self.frequencies = {identifier: Counter(value) for identifier, value in self.tokens.items()}
        document_frequency: Counter[str] = Counter()
        for value in self.tokens.values():
            document_frequency.update(set(value))
        total = len(self.ids)
        self.idf = {
            token: math.log(1.0 + (total - count + 0.5) / (count + 0.5))
            for token, count in document_frequency.items()
        }

    def score_all(self, query: str) -> dict[str, float]:
        terms = tokenise(query)
        scores: dict[str, float] = {}
        for identifier in self.ids:
            frequencies = self.frequencies[identifier]
            length = self.lengths[identifier]
            total = 0.0
            for term in terms:
                count = frequencies.get(term, 0)
                if not count:
                    continue
                denominator = count + K1 * (
                    1 - B + B * (length / self.average if self.average else 0.0)
                )
                total += self.idf.get(term, 0.0) * (count * (K1 + 1)) / denominator
            # Rounded so that two documents whose scores differ only by floating
            # point noise are recorded as tied rather than as ordered. A tie the
            # representation did not really express is still a tie the scorer
            # cannot resolve.
            scores[identifier] = round(total, 9)
        return scores


def build_corpus(manifest: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    documents: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []

    for pair in corpus["pairs"]:
        if pair["group"] != "natural":
            continue
        before = json.loads((ROOT / pair["before"]["path"]).read_text(encoding="utf-8"))
        after = json.loads((ROOT / pair["after"]["path"]).read_text(encoding="utf-8"))
        before_by_path = {"/".join(unit["explicit_path"]): unit for unit in before["units"]}
        after_by_path = {"/".join(unit["explicit_path"]): unit for unit in after["units"]}

        for key, unit in before_by_path.items():
            documents.append(
                {
                    "doc_id": pair["pair_id"] + "|before|" + key,
                    "pair_id": pair["pair_id"],
                    "path": key,
                    "revision": "superseded",
                    "text": unit["text"],
                }
            )
        for key, unit in after_by_path.items():
            documents.append(
                {
                    "doc_id": pair["pair_id"] + "|after|" + key,
                    "pair_id": pair["pair_id"],
                    "path": key,
                    "revision": "current",
                    "text": unit["text"],
                }
            )

        revised = 0
        unchanged = 0
        for key, unit in after_by_path.items():
            prior = before_by_path.get(key)
            if prior is None:
                continue
            moved = project(SEMANTIC, prior) != project(SEMANTIC, unit)
            kind = "Q1_REVISED_VALUE" if moved else "C1_UNCHANGED_CONTROL"
            if moved and revised >= PER_PAIR_CAP:
                continue
            if not moved and unchanged >= PER_PAIR_CAP:
                continue
            # Intent comes from the title and the heading path, never from the
            # answer text.
            query = pair["source_id"].rsplit(":", 1)[-1].replace("/", " ").replace("-", " ")
            query = query + " " + key.replace("/", " ")
            if not tokenise(query):
                ineligible.append(
                    {"pair_id": pair["pair_id"], "path": key, "reason": "INELIGIBLE_EMPTY_QUERY"}
                )
                continue
            questions.append(
                {
                    "question_id": pair["pair_id"] + "|" + kind + "|" + key,
                    "kind": kind,
                    "pair_id": pair["pair_id"],
                    "source_id": pair["source_id"],
                    "source_family": pair["source_family"],
                    "path": key,
                    "query": query,
                    "oracle_current_doc": pair["pair_id"] + "|after|" + key,
                    "superseded_doc": pair["pair_id"] + "|before|" + key,
                    "superseded_exists": True,
                }
            )
            if moved:
                revised += 1
            else:
                unchanged += 1

    return documents, questions, ineligible


def evaluate(index: Bm25Index, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for question in questions:
        scores = index.score_all(question["query"])
        if question["oracle_current_doc"] not in scores:
            rows.append({**question, "state": "INELIGIBLE_NO_ORACLE_UNIT"})
            continue
        top = max(scores.values())
        tied = sorted(key for key, value in scores.items() if value == top)
        ordered = sorted(scores, key=lambda key: (-scores[key], key))
        current = scores[question["oracle_current_doc"]]
        superseded = scores.get(question["superseded_doc"])
        rank = ordered.index(question["oracle_current_doc"]) + 1
        rows.append(
            {
                **question,
                "state": "SCORED",
                "top_score": top,
                "tied_set_size": len(tied),
                "exact_top_score_tie": len(tied) > 1,
                "current_score": current,
                "superseded_score": superseded,
                "scores_separate": superseded is not None and current != superseded,
                "current_rank": rank,
                "current_in_top_10": rank <= TOP_K,
                "current_unique_top_1": len(tied) == 1
                and tied[0] == question["oracle_current_doc"],
                "wrong_revision_dominant": superseded is not None and superseded > current,
                "tied_set": tied[:8],
            }
        )
    return rows


def run(manifest: Path, output: Path) -> int:
    started = now()
    documents, questions, ineligible = build_corpus(manifest)

    forward = Bm25Index([(item["doc_id"], item["text"]) for item in documents])
    reversed_index = Bm25Index([(item["doc_id"], item["text"]) for item in reversed(documents)])

    rows = evaluate(forward, questions)
    check = evaluate(reversed_index, questions)
    deterministic = all(
        left.get("top_score") == right.get("top_score")
        and left.get("tied_set") == right.get("tied_set")
        and left.get("current_score") == right.get("current_score")
        for left, right in zip(rows, check, strict=True)
    )

    scored = [row for row in rows if row["state"] == "SCORED"]
    q1 = [row for row in scored if row["kind"] == "Q1_REVISED_VALUE"]
    c1 = [row for row in scored if row["kind"] == "C1_UNCHANGED_CONTROL"]

    def share(rows_in: list[dict[str, Any]], field: str) -> float:
        return (sum(1 for row in rows_in if row[field]) / len(rows_in)) if rows_in else 0.0

    tie_rate = share(scored, "exact_top_score_tie")
    retrievable = share(scored, "current_in_top_10")
    separation = share(q1, "scores_separate")
    dominance = share(q1, "wrong_revision_dominant")
    control_stability = (
        sum(
            1
            for row in c1
            if row["superseded_score"] is None or row["current_score"] >= row["superseded_score"]
        )
        / len(c1)
        if c1
        else 0.0
    )
    lineages = len({row["source_id"] for row in scored})

    gates = {
        "G_P4_SCALE": {
            "passed": len(scored) >= 200 and lineages >= 10,
            "questions": len(scored),
            "lineages": lineages,
        },
        "G_P4_DETERMINISM": {"passed": deterministic},
        "G_P4_TIE_CEILING": {
            "passed": tie_rate <= 0.10,
            "value": tie_rate,
            "threshold": 0.10,
        },
        "G_P4_RETRIEVABILITY": {
            "passed": retrievable >= 0.90,
            "value": retrievable,
            "threshold": 0.90,
        },
        "G_P4_SEPARATION": {
            "passed": separation >= 0.90,
            "value": separation,
            "threshold": 0.90,
        },
        "G_P4_CONTROL": {
            "passed": control_stability >= 0.95,
            "value": control_stability,
            "threshold": 0.95,
        },
        "G_P4_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }
    verdict = "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL"

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p4_retrieval_validity.v1",
        "protocol": "P4_retrieval_validity",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "protocol_sha256": json.loads(
            (NS / "receipts" / "p4-protocol-freeze.json").read_text(encoding="utf-8")
        )["protocol_sha256"],
        "corpus_manifest": rel(manifest),
        "corpus_manifest_file_sha256": sha_file(manifest),
        "driver_sha256": sha_file(Path(__file__).resolve()),
        "representation": "BM25 k1=1.2 b=0.75, casefold word tokens of length >= 2",
        "index_size": len(documents),
        "question_count": len(questions),
        "scored_question_count": len(scored),
        "q1_count": len(q1),
        "c1_count": len(c1),
        "ineligible": ineligible,
        "measures": {
            "exact_top_score_tie_rate": tie_rate,
            "oracle_current_retrievable_at_10": retrievable,
            "oracle_current_top_1": share(scored, "current_unique_top_1"),
            "representation_separation_q1": separation,
            "wrong_revision_dominance_q1": dominance,
            "unchanged_control_stability": control_stability,
        },
        "determinism_check": {"reversed_insertion_order_reproduces_every_score": deterministic},
        "gates": gates,
        "verdict": verdict,
        "gpu_authorised_by_this_result": False,
        "next_step_if_failed": (
            "STOP. No model arm, no spend request, no threshold change. The question "
            "set or the representation must be rebuilt under a new protocol and a new "
            "cohort."
        ),
        "questions": rows,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["questions_sha256"] = canonical_sha(rows)
    write_hashed(output, body, "receipt_sha256")
    print(
        json.dumps(
            {
                "verdict": verdict,
                "questions": len(scored),
                "measures": {key: round(value, 4) for key, value in body["measures"].items()},
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                "receipt": rel(output),
            },
            sort_keys=True,
        )
    )
    return 0 if verdict == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=NS / "receipts" / "p0b-corpus-manifest.json"
    )
    parser.add_argument(
        "--output", type=Path, default=NS / "receipts" / "p4-retrieval-validity.json"
    )
    args = parser.parse_args()
    return run(args.manifest, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
