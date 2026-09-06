#!/usr/bin/env python3
"""Build the W6 v2 question set from structured facts, not from passage wording.

v1 died because queries were built from the target passage's own remaining
sentences: median query-to-oracle token overlap 1.0, Recall@1 0.9969, a task that
could not fail. The fix is not a better paraphrase — any question derived from
the passage inherits its vocabulary. The intent has to come from somewhere else.

Wikitext infoboxes supply it. Each is a set of `attribute = value` pairs, and a
question can be rendered from the **article title and the attribute name alone**,
per the frozen templates. The value never enters the query, and neither does the
sentence carrying it, so the overlap the leakage criterion measures is between a
short attribute phrase and a long passage rather than between a passage and
itself.

Revision-sensitivity is read off the data rather than assigned: an attribute
whose value differs between the before and after revisions is revision-sensitive
by observation, and one whose value is identical is a simple-retrieval control.
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
B = ROOT / "research/experiments/H1-B-REAL-REVISION-01"
ADAPTER = B / "scripts/run_public_real_revision_holdout_v3.py"

CORPORA = [
    ("holdout-v2", B / "receipts/wikipedia-real-revision-holdout-v2.json", B / "corpus"),
    (
        "confirmatory-v1",
        B / "receipts/wikipedia-real-revision-confirmatory-v1.json",
        B / "corpus-confirmatory-v1",
    ),
]

TEMPLATES = {
    "current": "What is the {attribute} of {subject}?",
    "as_of": "As of {date}, what is the {attribute} of {subject}?",
    "provenance": "Which source states the {attribute} of {subject}, and where?",
}

#: Infobox keys that carry presentation rather than fact. A question about an
#: image width is not a knowledge question and would pad the set with noise.
SKIP = re.compile(
    r"^(image|caption|width|alt|logo|photo|file|align|style|color|colour|"
    r"header|label|above|below|footnote|signature|map|pushpin|module)",
    re.I,
)
VALUE_NOISE = re.compile(r"\{\{|\}\}|<ref|<!--|\[\[File:|\[\[Image:", re.I)


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("v3_for_w6_qs", ADAPTER)
    if spec is None or spec.loader is None:
        raise SystemExit("the v3 adapter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def infobox_facts(text: str) -> dict[str, str]:
    """`attribute -> value` from the first infobox, conservatively parsed.

    Anything with template markup, a reference or a file link in its value is
    dropped rather than cleaned: a half-parsed value would become a gold answer
    that is wrong, which is worse than a smaller question set.
    """
    match = re.search(r"\{\{\s*[Ii]nfobox", text)
    if not match:
        return {}
    depth, i = 0, match.start()
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
        elif text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
        else:
            i += 1
    body = text[match.start() : i]
    facts: dict[str, str] = {}
    for line in body.split("\n|")[1:]:
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower().replace("_", " ")
        value = value.strip().split("\n")[0].strip()
        if not key or not value or SKIP.match(key) or VALUE_NOISE.search(value):
            continue
        if len(value) > 120 or len(key) > 40:
            continue
        facts[key] = value
    return facts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    adapter = load_adapter()

    questions: list[dict[str, Any]] = []
    docs_with_facts = 0
    for _name, receipt_path, corpus in CORPORA:
        for record in json.loads(receipt_path.read_text(encoding="utf-8"))["records"]:
            directory = corpus / adapter.slug(record["title"])
            sides = {}
            for side in ("before", "after"):
                path = directory / f"{record[side + '_revision_id']}.wikitext"
                text = path.read_text(encoding="utf-8")
                if adapter.sha_text(text) != record[side + "_sha256"]:
                    raise SystemExit(f"{path} no longer matches its recorded sha256")
                sides[side] = text
            before_facts = infobox_facts(sides["before"])
            after_facts = infobox_facts(sides["after"])
            if not before_facts or not after_facts:
                continue
            docs_with_facts += 1
            for attribute in sorted(set(before_facts) & set(after_facts)):
                old, new = before_facts[attribute], after_facts[attribute]
                changed = old != new
                questions.append(
                    {
                        "subject": record["title"],
                        "attribute": attribute,
                        "gold_current": new,
                        "gold_as_of_before": old,
                        "changed_between_revisions": changed,
                        # Read off the data, not assigned: an attribute whose
                        # value moved is revision-sensitive by observation.
                        "question_class": (
                            "revision_sensitive" if changed else "simple_retrieval"
                        ),
                        "query_current": TEMPLATES["current"].format(
                            attribute=attribute, subject=record["title"]
                        ),
                        "query_as_of": TEMPLATES["as_of"].format(
                            date=record["before_timestamp"][:10],
                            attribute=attribute,
                            subject=record["title"],
                        ),
                        "query_provenance": TEMPLATES["provenance"].format(
                            attribute=attribute, subject=record["title"]
                        ),
                        "before_revision_id": record["before_revision_id"],
                        "after_revision_id": record["after_revision_id"],
                        "before_timestamp": record["before_timestamp"],
                        "after_timestamp": record["after_timestamp"],
                    }
                )

    by_class: dict[str, int] = {}
    for question in questions:
        by_class[question["question_class"]] = by_class.get(question["question_class"], 0) + 1

    receipt = {
        "schema": "tavonel.w6-question-set.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "research/experiments/H1-W6-SAME-INTELLIGENCE-01/PROTOCOL_V2_2026-08-19.md",
        "templates": TEMPLATES,
        "documents_with_parsable_infoboxes": docs_with_facts,
        "counts_by_class": by_class,
        "questions": questions,
        "generation_rule": (
            "questions are rendered from the article title and the infobox "
            "attribute name only. The value, and the sentence carrying it, never "
            "enter the query -- which is what v1 got wrong."
        ),
        "conservative_parsing_note": (
            "values containing template markup, references or file links are "
            "dropped rather than cleaned. A half-parsed value becomes a gold "
            "answer that is wrong, which is worse than a smaller set."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"documents with parsable infoboxes: {docs_with_facts}")
    for name, count in sorted(by_class.items()):
        print(f"  {name:24}{count}")
    print(f"total questions: {len(questions)}")
    print(f"receipt: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
