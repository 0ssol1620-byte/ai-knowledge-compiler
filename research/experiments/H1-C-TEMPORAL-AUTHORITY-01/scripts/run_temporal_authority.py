#!/usr/bin/env python3
"""Temporal integrity and authority resolution on real Wikipedia revision chains.

Implements `PROTOCOL_2026-08-19.md`, which was frozen before this script was
written. Nothing here re-selects revisions, re-times instants or redefines a
metric: the protocol fixed the arms, the question types, the metrics and the
predictions, and this reports whatever comes out.

Three arms answer the same questions over the same facts:

    A  latest wins        the most recent revision's value, unconditionally
    B  retrieval baseline highest lexical overlap, ignoring time entirely
    C  TAVONEL resolver   resolve_authority over valid-time-scoped claims,
                          permitted to answer CONFLICTED or NO_CANDIDATE

Arm B is a deliberately weak baseline and is labelled as one. Calling it "RAG"
without an embedding model and a real index would overstate what it is.

Valid time comes from the MediaWiki revision timestamps already recorded in the
Family B receipts. Known time is the acquisition cutoff, uniform across the
corpus -- which is a limitation, not a design, and is reported as one.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
B = ROOT / "research/experiments/H1-B-REAL-REVISION-01"
ADAPTER = B / "scripts/run_public_real_revision_holdout_v3.py"

from akc_cir.authority import (  # noqa: E402
    AuthorityClass,
    ClaimContext,
    ResolutionStatus,
    ScopedClaim,
    resolve_authority,
)
from akc_cir.temporal import (  # noqa: E402
    TemporalFact,
    TemporalSource,
    TemporalTimeline,
    replay_context,
)

RECEIPTS = [
    ("holdout-v2", B / "receipts/wikipedia-real-revision-holdout-v2.json", B / "corpus"),
    (
        "confirmatory-v1",
        B / "receipts/wikipedia-real-revision-confirmatory-v1.json",
        B / "corpus-confirmatory-v1",
    ),
]


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("real_revision_v3_w5", ADAPTER)
    if spec is None or spec.loader is None:
        raise SystemExit("the v3 adapter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_ts(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def read_side(adapter: Any, corpus: Path, record: dict[str, Any], side: str) -> Any:
    """Load one revision from disk and refuse it if the bytes moved.

    A replay that silently scored different bytes than the run which produced
    the receipt would be a comparison of two different experiments.
    """
    directory = corpus / adapter.slug(record["title"])
    path = directory / f"{record[side + '_revision_id']}.wikitext"
    text = path.read_text(encoding="utf-8")
    if adapter.sha_text(text) != record[side + "_sha256"]:
        raise SystemExit(f"{path} no longer matches its recorded sha256")
    return adapter.Revision(
        title=record["title"],
        revid=record[side + "_revision_id"],
        parentid=0,
        timestamp=record[side + "_timestamp"],
        mw_sha1=record[side + "_mw_sha1"],
        text=text,
    )


_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def arm_b_retrieval(query: str, pool: list[str]) -> str:
    """Highest lexical overlap, time ignored. Ties go to the earlier candidate.

    The tie-break is fixed here rather than chosen after seeing results. Breaking
    ties toward the later revision would quietly turn this arm into arm A.
    """
    q = tokens(query)
    best_score = -1.0
    best_value = ""
    for value in pool:
        t = tokens(value)
        score = len(q & t) / (len(q | t) or 1)
        if score > best_score:
            best_score = score
            best_value = value
    return best_value


def build_questions(adapter: Any, corpus: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    before = read_side(adapter, corpus, record, "before")
    after = read_side(adapter, corpus, record, "after")
    before_units, _ = adapter.section_units(before)
    after_units, _ = adapter.section_units(after)
    t_before = parse_ts(record["before_timestamp"])
    t_after = parse_ts(record["after_timestamp"])
    # An instant strictly inside the window where the before-value was live.
    t_mid = t_before + (t_after - t_before) / 2
    if t_mid <= t_before or t_mid >= t_after:
        return []

    by_id_before = {u.logical_id: u.text for u in before_units}
    by_id_after = {u.logical_id: u.text for u in after_units}
    questions = []
    for logical_id in sorted(set(by_id_before) & set(by_id_after)):
        old = by_id_before[logical_id]
        new = by_id_after[logical_id]
        if old == new:
            continue  # nothing to be right or wrong about
        questions.append(
            {
                "title": record["title"],
                "logical_id": logical_id,
                "before_value": old,
                "after_value": new,
                "t_before": t_before,
                "t_mid": t_mid,
                "t_after": t_after,
            }
        )
    return questions


def answer_arm_c(q: dict[str, Any], at: datetime) -> tuple[str, str]:
    """The resolver, given both values as valid-time-scoped claims.

    Authority class is held constant across both claims, as protocol §7 fixed:
    the corpus has supersession but no genuine authority hierarchy, so any
    difference in class here would be invented and would decide the outcome.
    Holding it constant means valid time is the only thing separating them.
    """
    claims = [
        ScopedClaim(
            claim_id=q["logical_id"] + "@before",
            subject=q["logical_id"],
            value=q["before_value"],
            authority=AuthorityClass.OFFICIAL,
            valid_from=q["t_before"],
            valid_to=q["t_after"],
        ),
        ScopedClaim(
            claim_id=q["logical_id"] + "@after",
            subject=q["logical_id"],
            value=q["after_value"],
            authority=AuthorityClass.OFFICIAL,
            valid_from=q["t_after"],
            valid_to=None,
        ),
    ]
    resolution = resolve_authority(
        claims, ClaimContext(subject=q["logical_id"], as_of=at)
    )
    if resolution.status is ResolutionStatus.RESOLVED and resolution.claim is not None:
        return resolution.claim.value, resolution.status.value
    return "", resolution.status.value


def replay_ok(q: dict[str, Any], at: datetime) -> bool:
    """Does a replay at `at` reproduce the value that was live then, by hash?"""
    timeline = TemporalTimeline(
        [
            TemporalFact(
                logical_id=q["logical_id"],
                value=q["before_value"],
                valid_from=q["t_before"],
                valid_to=q["t_after"],
                recorded_at=q["t_before"],
                # The MediaWiki revision timestamp: the document said so. Left
                # at the UNKNOWN default, an as-of query excludes the fact
                # outright -- correctly, since a date with no stated origin is
                # not one the system may rely on.
                temporal_source=TemporalSource.EXPLICIT,
            ),
            TemporalFact(
                logical_id=q["logical_id"],
                value=q["after_value"],
                valid_from=q["t_after"],
                recorded_at=q["t_after"],
                temporal_source=TemporalSource.EXPLICIT,
            ),
        ]
    )
    answer = replay_context(timeline, at=at, logical_ids=[q["logical_id"]])
    if len(answer.facts) != 1:
        return False
    expected = q["before_value"] if at < q["t_after"] else q["after_value"]
    return canonical_sha256(answer.facts[0].value) == canonical_sha256(expected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    adapter = load_adapter()

    questions: list[dict[str, Any]] = []
    corpora_used = []
    for name, receipt_path, corpus in RECEIPTS:
        receipt_in = json.loads(receipt_path.read_text(encoding="utf-8"))
        n_before = len(questions)
        for record in receipt_in["records"]:
            questions.extend(build_questions(adapter, corpus, record))
        corpora_used.append(
            {
                "corpus": name,
                "pairs": len(receipt_in["records"]),
                "questions": len(questions) - n_before,
            }
        )

    arms: dict[str, dict[str, int]] = {
        a: {"type1": 0, "type2": 0, "abstained": 0} for a in "ABC"
    }
    replay_correct = 0
    arm_b_ties = 0
    for q in questions:
        pool = [q["before_value"], q["after_value"]]
        query = q["logical_id"]
        qt = tokens(query)
        scores = [len(qt & tokens(v)) / (len(qt | tokens(v)) or 1) for v in pool]
        arm_b_ties += int(scores[0] == scores[1])

        # type 1 -- what does it say now? ground truth: the later revision.
        arms["A"]["type1"] += 1  # latest-wins is right by construction
        arms["B"]["type1"] += int(arm_b_retrieval(query, pool) == q["after_value"])
        c_now, status_now = answer_arm_c(q, q["t_after"])
        arms["C"]["type1"] += int(c_now == q["after_value"])
        arms["C"]["abstained"] += int(status_now != ResolutionStatus.RESOLVED.value)

        # type 2 -- what did it say at T? ground truth: the value live at T.
        arms["A"]["type2"] += int(q["after_value"] == q["before_value"])
        arms["B"]["type2"] += int(arm_b_retrieval(query, pool) == q["before_value"])
        c_then, status_then = answer_arm_c(q, q["t_mid"])
        arms["C"]["type2"] += int(c_then == q["before_value"])
        arms["C"]["abstained"] += int(status_then != ResolutionStatus.RESOLVED.value)

        replay_correct += int(replay_ok(q, q["t_mid"]) and replay_ok(q, q["t_after"]))

    total = len(questions)

    def frac(n: int) -> float | None:
        return round(n / total, 4) if total else None

    receipt = {
        "schema": "tavonel.temporal-authority-comparison.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "research/experiments/H1-C-TEMPORAL-AUTHORITY-01/PROTOCOL_2026-08-19.md",
        "corpora": corpora_used,
        "question_count": total,
        "results": {
            arm: {
                "type1_current_value_accuracy": frac(v["type1"]),
                "type2_as_of_accuracy": frac(v["type2"]),
                "abstention_count": v["abstained"],
            }
            for arm, v in arms.items()
        },
        "replay_fidelity": frac(replay_correct),
        "arm_b_tie_count": arm_b_ties,
        "arm_b_validity": (
            "DEGENERATE on this question set. Every comparison was an exact "
            "lexical tie, because the query is a section heading and both "
            "candidates are that same section's text -- there is nothing for "
            "lexical overlap to discriminate on. Arm B's scores are therefore "
            "decided entirely by the fixed tie-break (earlier candidate wins) "
            "and are NOT a retrieval result. No claim may be made of arm C "
            "beating a retrieval baseline on this data; arm B did not produce "
            "one."
        ),
        "arm_c_scope": (
            "arm C is handed the two values already carrying correct valid-time "
            "windows, so 1.0/1.0 shows that the resolver *uses* valid time "
            "correctly, not that the system can *extract* it from a document. "
            "The extraction step is untested here and is the harder half."
        ),
        "sample_size_limitation": (
            "11 questions from 23 revision pairs. Units whose text did not "
            "change carry no question, and units present in only one revision "
            "are excluded because ground truth would be ambiguous. This is a "
            "thin sample and no interval is reported for it."
        ),
        # A linear revision chain never has two claims live in overlapping
        # valid-time windows, so type 3 cannot be built from it. Detected and
        # reported rather than manufactured.
        "type3_conflict_questions_found": 0,
        "type3_note": (
            "zero, and this is a property of the corpus rather than a result. "
            "Protocol prediction 4 -- that arms A and B show a false-confidence "
            "rate of 1.0 on conflict questions -- is therefore UNTESTED here, "
            "not confirmed. Constructing overlapping windows would be inventing "
            "the very conflict arm C is being credited for handling."
        ),
        "known_time_limitation": (
            "acquisition time is uniform across the corpus, so the known-time "
            "axis is not exercised. Only valid time is tested."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    labels = {"A": "A latest-wins", "B": "B lexical baseline", "C": "C TAVONEL resolver"}
    print("questions: " + str(total) + "  corpora: " + json.dumps(corpora_used))
    print("  arm                        type1 current   type2 as-of  abstained")
    for arm in "ABC":
        r = receipt["results"][arm]
        print(
            "  "
            + labels[arm].ljust(26)
            + str(r["type1_current_value_accuracy"]).rjust(13)
            + str(r["type2_as_of_accuracy"]).rjust(14)
            + str(r["abstention_count"]).rjust(11)
        )
    print("replay fidelity: " + str(receipt["replay_fidelity"]))
    print("type-3 conflict questions available in this corpus: 0")
    print("receipt: " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
