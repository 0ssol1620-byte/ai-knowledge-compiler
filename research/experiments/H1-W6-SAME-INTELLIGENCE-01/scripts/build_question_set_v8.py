#!/usr/bin/env python3
"""The v8 question generator. Its one substantive difference from v7 is admission.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §7, and finding 4 of
`V8_DEVELOPMENT_FINDINGS_2026-08-19.md`.

**Why this exists.** v7 decided revision-sensitivity by comparing raw wikitext,
so a pure markup edit was admitted as a temporal question: `Sir` → `[[Sir]]`,
`<br>` → `<br />`, `[[George M. Bibb|George Bibb]]` → `[[George M. Bibb]]`. The
answer is identical before and after. **96 of 293 (32.8%)** of v7's primary class
were such questions, which would have pulled every arm's measured effect toward
zero and made a real advantage harder to see — or manufactured an apparent one
out of noise.

So v8 admits a revision-sensitive question only when the attribute's **value**
changed, decided on markup-normalized value tokens rather than on the wikitext
string. Everything else about the instrument — the frozen §2 templates, the
infobox parser, the three-per-article cap fixed by hash order at acquisition — is
v7's, unchanged, so v7 and v8 questions stay comparable.

**Exclusions are counted and reported, never silently dropped.** A generator that
quietly discards a third of its input looks identical to one that had a third
less input.

**Positive control, in the same execution:** a synthetic markup-only pair must be
excluded and a synthetic real change must be admitted. A filter that has never
rejected anything is not evidence, and one that rejects everything is worse.

The corpus is a parameter. Run against the v7 development acquisition now; the
same code runs against the v8 holdout acquisition when §7 is satisfied. The run
class is derived from the receipt, not asserted by the caller.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
PROTOCOL = EXP / "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md"
SEAL = EXP / "receipts" / "v7-development-seal-2026-08-19.json"


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def classify_change(old: str, new: str, value_tokens: Any) -> str:
    """`UNCHANGED` · `MARKUP_ONLY` · `SEMANTIC`.

    `MARKUP_ONLY` is the case v7 could not see: the wikitext differs, the value
    does not. `value_tokens` keeps numerals and drops markup tokens, so link
    piping, bracket addition and `<br>` spelling all normalize away while a real
    value change does not.
    """
    if old == new:
        return "UNCHANGED"
    return "SEMANTIC" if value_tokens(old) != value_tokens(new) else "MARKUP_ONLY"


def admission_control(value_tokens: Any) -> dict[str, Any]:
    """The filter must reject a markup-only edit and admit a real one, here.

    The cases are the shapes actually observed in v7 rather than invented ones,
    so a regression in the normalizer shows up against real input.
    """
    markup_only = [
        ("Sir", "[[Sir]]"),
        ("[[George M. Bibb|George Bibb]]", "[[George M. Bibb]]"),
        ("Canada <br /> United States", "[[Canada]]<br />[[United States]]"),
        ("[[Chicago]], [[Illinois]], US", "[[Chicago]], Illinois, US"),
    ]
    semantic = [
        ("1,200", "1,450"),
        ("[[Chicago]], Illinois", "[[Boston]], Massachusetts"),
        ("Democratic", "Republican"),
    ]
    rejects = [classify_change(o, n, value_tokens) == "MARKUP_ONLY" for o, n in markup_only]
    admits = [classify_change(o, n, value_tokens) == "SEMANTIC" for o, n in semantic]
    return {
        "markup_only_cases": len(markup_only), "markup_only_all_rejected": all(rejects),
        "semantic_cases": len(semantic), "semantic_all_admitted": all(admits),
        "separates": all(rejects) and all(admits),
        "note": "cases are shapes observed in the v7 corpus, not invented ones",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--acquisition", type=Path, required=True,
                    help="acquisition receipt for the corpus to build from")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--run-class", choices=["DEVELOPMENT_ONLY", "HOLDOUT_CONFIRMATORY"],
                    required=True)
    args = ap.parse_args()

    v2 = load(HERE / "build_question_set_v2.py", "w6v8_v2")
    v7gate = load(HERE / "gate_question_set_v7.py", "w6v8_v7g")
    taint = load(HERE / "taint_gate_v8.py", "w6v8_taint4")
    value_tokens = v7gate.value_tokens

    control = admission_control(value_tokens)

    acq = json.loads(args.acquisition.read_text(encoding="utf-8"))
    records = acq.get("records") or acq.get("articles") or []

    # A holdout build may not touch a title v7 used. Checked against the seal
    # rather than against a recollection of which titles those were.
    development_titles: set[str] = set()
    if SEAL.exists():
        seal = json.loads(SEAL.read_text(encoding="utf-8"))
        block = seal.get("development_titles_excluded_from_v8") or {}
        development_titles = set(block.get("titles") or [])
        if not development_titles:
            raise SystemExit(
                "the seal is present but records no development titles; the holdout "
                "overlap guard would be inert and a silent pass is worse than no guard")
    overlap = sorted({r["title"] for r in records} & development_titles)
    if args.run_class == "HOLDOUT_CONFIRMATORY" and overlap:
        raise SystemExit(
            f"refusing to build a holdout question set: {len(overlap)} titles are v7 "
            f"development data, e.g. {overlap[:3]}")

    questions: list[dict[str, Any]] = []
    excluded: Counter = Counter()
    excluded_examples: list[dict[str, str]] = []
    findings: list[dict[str, Any]] = []
    docs_with_facts = 0

    for record in records:
        sides: dict[str, str] = {}
        ok = True
        for side in ("before", "after"):
            path = EXP / record[f"relative_{side}_path"]
            if not path.exists():
                ok = False
                break
            raw = path.read_bytes()
            if "sha256:" + hashlib.sha256(raw).hexdigest() != record[f"{side}_sha256"]:
                findings.append({
                    "kind": "CORPUS_FILE_HASH_MISMATCH", "title": record["title"],
                    "side": side,
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

        recorded_changed = set(record.get("changed_attributes") or [])
        primary = set(record.get("primary_retained_changed_attributes") or [])
        date = record["before_timestamp"][:10]

        for attribute in sorted(set(before_facts) & set(after_facts)):
            old, new = before_facts[attribute], after_facts[attribute]
            kind = classify_change(old, new, value_tokens)

            if kind == "MARKUP_ONLY":
                # Split by primary eligibility. v7's rule only admitted attributes
                # that were primary-retained and recorded as changed, so mixing the
                # rest into the headline denominator would misstate the share.
                if attribute in primary and attribute in recorded_changed:
                    excluded["markup_only_primary_eligible"] += 1
                else:
                    excluded["markup_only_not_primary_eligible"] += 1
                if len(excluded_examples) < 12:
                    excluded_examples.append({"subject": record["title"],
                                              "attribute": attribute,
                                              "before": old[:120], "after": new[:120]})
                continue
            if kind == "SEMANTIC":
                if attribute not in primary or attribute not in recorded_changed:
                    excluded["not_a_primary_retained_attribute"] += 1
                    continue
                if not value_tokens(new):
                    excluded["degenerate_value"] += 1
                    continue
                klass = "revision_sensitive"
            else:
                klass = "simple_retrieval"

            questions.append({
                "question_id": canonical_sha256([record["title"], attribute])[7:23],
                "subject": record["title"], "attribute": attribute,
                "gold_current": new, "gold_as_of_before": old,
                "change_kind": kind, "question_class": klass,
                "query_current": taint.render(subject=record["title"], attribute=attribute,
                                              date=date, template_id="current"),
                "query_as_of": taint.render(subject=record["title"], attribute=attribute,
                                            date=date, template_id="as_of"),
                "query_provenance": taint.render(subject=record["title"], attribute=attribute,
                                                 date=date, template_id="provenance"),
                "before_revision_id": record["before_revision_id"],
                "after_revision_id": record["after_revision_id"],
                "before_timestamp": record["before_timestamp"],
                "after_timestamp": record["after_timestamp"],
                "separation_days": record["separation_days"],
                "relative_before_path": record["relative_before_path"],
                "relative_after_path": record["relative_after_path"],
                "provenance_gold": {
                    "current": {"revision_id": record["after_revision_id"],
                                "path": record["relative_after_path"]},
                    "as_of": {"revision_id": record["before_revision_id"],
                              "path": record["relative_before_path"]},
                },
            })

    by_class = Counter(q["question_class"] for q in questions)
    revision_sensitive = by_class["revision_sensitive"]
    markup_only = excluded["markup_only_primary_eligible"]
    v7_primary = revision_sensitive + markup_only

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-question-set.v8",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md",
        "protocol_sha256": "sha256:" + hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "run_class": args.run_class,
        "run_class_note": (
            "built from the v7 development acquisition to verify the generator before the "
            "holdout exists. No number here is a paper endpoint."
            if args.run_class == "DEVELOPMENT_ONLY" else
            "built from an acquisition verified disjoint from the v7 development titles."
        ),
        "acquisition_receipt": args.acquisition.name,
        "acquisition_receipt_sha256": "sha256:" + hashlib.sha256(
            args.acquisition.read_bytes()).hexdigest(),
        "instrument": "build_question_set_v2 infobox parser and frozen section 2 templates, "
                      "unchanged, so v7 and v8 questions stay comparable",
        "admission_rule": (
            "a revision-sensitive question requires the attribute's VALUE to change, decided "
            "on markup-normalized value tokens. v7 compared raw wikitext and admitted "
            "markup-only edits."
        ),
        "admission_control": control,
        "development_titles_overlap": len(overlap),
        "documents_with_parsable_infoboxes": docs_with_facts,
        "question_count": len(questions),
        "counts_by_class": dict(by_class),
        "excluded": dict(excluded),
        "excluded_markup_only_examples": excluded_examples,
        "markup_only_share_of_v7_primary_class": (
            round(markup_only / v7_primary, 4) if v7_primary else None),
        "markup_only_share_note": (
            "the share of what v7's rule would have admitted as revision-sensitive that this "
            "rule rejects as having no value change. The denominator is primary-eligible "
            "attributes only, matching v7's admission path; markup-only edits outside that "
            "path are counted separately and are not in this ratio. Reported so the exclusion "
            "is visible rather than showing up as a smaller corpus."
        ),
        "finding_count": len(findings),
        "findings": findings,
        "questions": questions,
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(
        {k: v for k, v in receipt.items() if k != "questions"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    print(f"run class: {args.run_class}   documents with infoboxes: {docs_with_facts}")
    print(f"admission control separates: {control['separates']}")
    print(f"questions: {len(questions)}   by class: {dict(by_class)}")
    print(f"excluded: {dict(excluded)}")
    print(f"markup-only share of what v7's rule would have admitted: "
          f"{receipt['markup_only_share_of_v7_primary_class']}")
    print(f"wrote {args.output.resolve().relative_to(ROOT).as_posix()}")
    return 0 if control["separates"] else 1


if __name__ == "__main__":
    sys.exit(main())
