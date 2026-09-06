#!/usr/bin/env python3
"""Build the W6 question set over corpus-v7, under the frozen PROTOCOL_V2.

`QUESTION_SET_V2_RESULT_2026-08-19.md` is the result over the *old* consecutive-
revision corpora and is not touched by this script. It reported the primary
endpoint NOT RUN with 0 of 60 revision-sensitive questions, because the Family B
corpora were revision pairs minutes apart and structured facts do not move in
that window. That finding stands and is a property of that corpus.

corpus-v7 was acquired against that diagnosis: snapshots at 2023-06-30 and
2026-06-30, minimum separation 1,095 days, three primary attributes per article
retained under a hash order fixed before any value was seen.

**The instrument is not rebuilt.** `infobox_facts`, `SKIP`, `VALUE_NOISE` and the
three §2 templates are imported from `build_question_set_v2.py` rather than
copied. A copy would drift, and a question set built by a differently-behaving
parser is not comparable to the one that produced the v2 finding.

**The acquisition's own attribute lists are cross-checked, not trusted.** The
acquisition recorded which attributes changed; this reparses both revisions and
reports any disagreement as a finding rather than adopting either side.

Classes not producible by this generator are reported NOT_RUN with the reason,
and the reason distinguishes *the corpus has no such case* from *this generator
cannot express one*. Those are different facts and PROTOCOL_V2 §1 only excuses
the first.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
ACQ = EXP / "receipts" / "acquisition-v7-2026-08-19.json"
INTEGRITY = EXP / "receipts" / "v7-corpus-integrity-2026-08-19.json"
PROTOCOL = EXP / "PROTOCOL_V2_2026-08-19.md"
V2_BUILDER = HERE / "build_question_set_v2.py"

#: PROTOCOL_V2 §1, frozen before any corpus existed.
MINIMUMS = {
    "simple_retrieval": 40,
    "revision_sensitive": 60,
    "conflicting_evidence": 30,
    "multi_document": 30,
    "provenance_sensitive": 40,
}


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_v2_instrument() -> Any:
    spec = importlib.util.spec_from_file_location("w6_qs_v2_instrument", V2_BUILDER)
    if spec is None or spec.loader is None:
        raise SystemExit("the v2 question-set instrument cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    integrity = json.loads(INTEGRITY.read_text(encoding="utf-8"))
    if not integrity.get("all_gates_pass"):
        print("REFUSING: corpus-v7 integrity gates did not all pass")
        return 2

    v2 = load_v2_instrument()
    acq = json.loads(ACQ.read_text(encoding="utf-8"))
    records = acq.get("records", [])

    questions: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    docs_with_facts = 0
    parse_disagreements = 0

    # (subject, attribute) -> list of (value, valid_from, valid_to, source)
    assertions: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for record in records:
        sides = {}
        ok = True
        for side in ("before", "after"):
            path = EXP / record[f"relative_{side}_path"]
            raw = path.read_bytes()
            if "sha256:" + hashlib.sha256(raw).hexdigest() != record[f"{side}_sha256"]:
                findings.append({
                    "kind": "CORPUS_FILE_HASH_MISMATCH",
                    "title": record["title"], "side": side,
                    "why": "the file no longer matches the acquisition receipt; not used",
                })
                ok = False
                break
            sides[side] = raw.decode("utf-8", errors="replace")
        if not ok:
            continue

        before_facts = v2.infobox_facts(sides["before"])
        after_facts = v2.infobox_facts(sides["after"])
        if not before_facts or not after_facts:
            continue
        docs_with_facts += 1

        shared = sorted(set(before_facts) & set(after_facts))
        observed_changed = {a for a in shared if before_facts[a] != after_facts[a]}
        recorded_changed = set(record.get("changed_attributes") or [])
        primary = [a for a in (record.get("primary_retained_changed_attributes") or [])]

        # Cross-check rather than adopt. A disagreement means the acquisition and
        # this parser read the same bytes differently, and neither is privileged.
        if observed_changed != recorded_changed:
            parse_disagreements += 1
            findings.append({
                "kind": "ATTRIBUTE_CHANGE_SET_DISAGREEMENT",
                "title": record["title"],
                "recorded_only": sorted(recorded_changed - observed_changed),
                "observed_only": sorted(observed_changed - recorded_changed),
                "why": (
                    "the acquisition receipt and this reparse disagree on which attributes "
                    "changed. Questions are built only from attributes both agree on, so a "
                    "disagreement shrinks the set rather than seeding a wrong gold answer."
                ),
            })

        date = record["before_timestamp"][:10]
        for attribute in shared:
            old, new = before_facts[attribute], after_facts[attribute]
            changed = old != new

            # Validity intervals, used by the conflict measurement below.
            assertions[(record["title"], attribute)].append({
                "value": old, "valid_from": record["before_timestamp"],
                "valid_to": record["after_timestamp"],
                "revision": record["before_revision_id"], "side": "before",
            })
            assertions[(record["title"], attribute)].append({
                "value": new, "valid_from": record["after_timestamp"],
                "valid_to": None,
                "revision": record["after_revision_id"], "side": "after",
            })

            if changed:
                # Only the primary retained attributes count toward the primary
                # endpoint. The three-per-article cap was frozen in the
                # acquisition by hash order, before any value was seen, and
                # widening it here would be selecting on the outcome.
                if attribute not in primary or attribute not in recorded_changed:
                    continue
                klass = "revision_sensitive"
            else:
                klass = "simple_retrieval"

            questions.append({
                "question_id": canonical_sha256([record["title"], attribute])[7:23],
                "subject": record["title"],
                "attribute": attribute,
                "gold_current": new,
                "gold_as_of_before": old,
                "changed_between_revisions": changed,
                "question_class": klass,
                "query_current": v2.TEMPLATES["current"].format(
                    attribute=attribute, subject=record["title"]),
                "query_as_of": v2.TEMPLATES["as_of"].format(
                    date=date, attribute=attribute, subject=record["title"]),
                "query_provenance": v2.TEMPLATES["provenance"].format(
                    attribute=attribute, subject=record["title"]),
                "before_revision_id": record["before_revision_id"],
                "after_revision_id": record["after_revision_id"],
                "before_timestamp": record["before_timestamp"],
                "after_timestamp": record["after_timestamp"],
                "separation_days": record["separation_days"],
                "relative_before_path": record["relative_before_path"],
                "relative_after_path": record["relative_after_path"],
                # Provenance gold: the exact revision the answer comes from.
                "provenance_gold": {
                    "current": {"revision_id": record["after_revision_id"],
                                "path": record["relative_after_path"]},
                    "as_of": {"revision_id": record["before_revision_id"],
                              "path": record["relative_before_path"]},
                },
            })

    # ---- §3 conflicting evidence: measured, never manufactured -------------
    conflicts = []
    for (subject, attribute), asserted in assertions.items():
        for i, a in enumerate(asserted):
            for b in asserted[i + 1:]:
                if a["value"] == b["value"]:
                    continue
                # Overlapping validity is required. before ends exactly where
                # after begins, so a sequential pair does not overlap and a
                # superseded value is not a conflict.
                a_to, b_from = a["valid_to"], b["valid_from"]
                b_to, a_from = b["valid_to"], a["valid_from"]
                overlap = (a_to is None or a_to > b_from) and (b_to is None or b_to > a_from)
                if overlap:
                    conflicts.append({"subject": subject, "attribute": attribute,
                                      "values": [a["value"], b["value"]]})

    # ---- multi-document: measured against the generation rule --------------
    # A question requires >= 2 sources only if its gold answer cannot be
    # established from one document. Every question here is (article title,
    # attribute of that article's infobox), so each is answerable from one.
    multi_document = 0

    by_class: dict[str, int] = defaultdict(int)
    for q in questions:
        by_class[q["question_class"]] += 1
    # Provenance questions are the same items asked with the provenance template
    # and scored on evidence location. They are not additional items.
    by_class["provenance_sensitive"] = by_class["revision_sensitive"]
    by_class["conflicting_evidence"] = len(conflicts)
    by_class["multi_document"] = multi_document

    # A class the corpus cannot supply and a class the generator cannot express
    # are different facts, and PROTOCOL_V2 section 1 only excuses the first.
    # Reporting the second as INSUFFICIENT_REAL_CASES would file a design limit
    # under a data limit, where more acquisition looks like the remedy.
    GENERATOR_SCOPE_LIMITED = {"multi_document"}
    class_states = {}
    for name, minimum in MINIMUMS.items():
        got = by_class.get(name, 0)
        if got >= minimum:
            state = "SUFFICIENT"
        elif name in GENERATOR_SCOPE_LIMITED:
            state = "NOT_RUN_GENERATOR_SCOPE_LIMITATION"
        else:
            state = "NOT_RUN_INSUFFICIENT_REAL_CASES"
        class_states[name] = {"produced": got, "required": minimum, "state": state}
    class_states["conflicting_evidence"]["why"] = (
        "measured, not assumed: no (subject, attribute) pair carries two different values "
        "over overlapping validity. before's interval ends exactly where after's begins, so "
        "a superseded value is not a conflict. PROTOCOL_V2 section 3 includes this class only "
        "where real conflicts exist and forbids manufacturing one."
    )
    class_states["multi_document"]["why"] = (
        "0 by construction of the generator, not by scarcity in the corpus. Every question "
        "is an attribute of one article's infobox and is answerable from that one document. "
        "This is a limit of the section 2 template rule, which is frozen; producing "
        "multi-document questions would need a different generation rule and a new protocol, "
        "not a looser reading of this one."
    )
    class_states["provenance_sensitive"]["why"] = (
        "the same revision-sensitive items asked with the section 2 provenance template and "
        "scored on exact evidence location. Not additional items, and counted as the same n."
    )

    articles = len({q["subject"] for q in questions if q["question_class"] == "revision_sensitive"})

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-question-set.v7",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus": "corpus-v7",
        "corpus_root_sha256": integrity.get("corpus_root_sha256"),
        "acquisition_receipt_sha256": acq.get("receipt_sha256"),
        "protocol": "PROTOCOL_V2_2026-08-19.md",
        "protocol_sha256": "sha256:" + hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "instrument": {
            "source": "scripts/build_question_set_v2.py",
            "sha256": "sha256:" + hashlib.sha256(V2_BUILDER.read_bytes()).hexdigest(),
            "imported_not_copied": True,
            "why": (
                "the parser and the three templates that produced the v2 finding are "
                "imported so the two question sets are comparable. A copy would drift."
            ),
        },
        "supersedes_nothing": (
            "QUESTION_SET_V2_RESULT_2026-08-19.md and receipts/question-set-v2-2026-08-19.json "
            "are the result over the old consecutive-revision corpora. They are neither "
            "edited nor superseded by this file: they remain the correct finding for that "
            "corpus, and this is a separate finding for a different one."
        ),
        "documents_considered": len(records),
        "documents_with_parsable_infoboxes": docs_with_facts,
        "attribute_change_set_disagreements": parse_disagreements,
        "counts_by_class": dict(by_class),
        "class_states": class_states,
        "articles_with_revision_sensitive_questions": articles,
        "primary_endpoint_class": "revision_sensitive",
        "primary_endpoint_state": class_states["revision_sensitive"]["state"],
        "conflicts_found": conflicts[:20],
        "questions": questions,
        "question_count": len(questions),
        "generation_rule": (
            "rendered from the article title and the infobox attribute name only. The value, "
            "and the sentence carrying it, never enter the query."
        ),
        "findings": findings,
        "finding_count": len(findings),
        "leakage_measured_here": False,
        "leakage_note": (
            "section 3's overlap criteria are a separate measurement and a separate gate. "
            "This receipt is the set; it is not cleared to run until that gate passes."
        ),
        "endpoint_status": "NOT_RUN",
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
        "identity_module_modified": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")

    print(f"documents with parsable infoboxes: {docs_with_facts} of {len(records)}")
    print(f"attribute change-set disagreements: {parse_disagreements}")
    for name in MINIMUMS:
        st = class_states[name]
        print(f"  {st['state']:<32} {name:<22} {st['produced']:>5} / {st['required']}")
    print(f"articles with revision-sensitive questions: {articles}")
    print(f"total question items: {len(questions)}")
    print(f"receipt: {args.output.resolve().relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
