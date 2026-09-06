#!/usr/bin/env python3
"""Detect inference written in the grammar of measurement.

Five findings in this programme share one root cause, and it is not carelessness
about any particular fact:

    P15  a facet described as "preserved" that nothing had measured
    P16  a failure *cause* inferred from a disk signature and stated as fact
    P17  "all twelve facets compared", written while enumerating eleven
    P18  a subset test result reported under a repository-wide label
    E4   removing a claim limitation described as narrowing the claim

Root class: **INFERENCE_PROMOTED_TO_MEASUREMENT** -- asserting something in the
register reserved for observation, on the strength of what the structure implies,
without an observation behind it.

Prose cannot be checked for truth. It can be checked for *register*: whether a
sentence claims observation, and whether anything observed is attached to it.
This tool enforces the register.

Origin classes, and what each licenses:

    MEASURED           an experiment produced it -- receipt required
    STATIC_CODE_AUDIT  reading the code establishes it -- audit record required
    DERIVED            computed from measured values -- inputs must be measured
    INFERRED           follows from structure; NOT observed
    EXPECTED           anticipated; NOT observed
    EXTERNAL           someone else's result -- quoted, never reproduced
    NOT_MEASURED       explicitly outstanding

The promotion rule is one-directional: INFERRED and EXPECTED never become
MEASURED without a run. This tool cannot verify that a number is *correct*; it
verifies that a sentence claiming observation has an observation to point at,
which is precisely the step all five findings skipped.

`--self-test` runs the positive control. A detector that has never fired is an
assertion, and this programme has voided an experiment on exactly that.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

DOCS = {
    "manuscript": "docs/paper/MANUSCRIPT_v1_2026-08-19.md",
    "tables": "docs/paper/TABLES_2026-08-19.md",
    "figures": "docs/paper/FIGURES_2026-08-19.md",
    "claim_set": "docs/ip/PATENT_CLAIM_SET_v1_2026-08-19.md",
    "specification": "docs/ip/PATENT_SPECIFICATION_v1_2026-08-19.md",
}

RECEIPT_ROOTS = ["research/experiments", "docs/ip/receipts", "docs/repro"]

#: Verbs that assert an observation was made.
MEASUREMENT = re.compile(
    r"\b(measured|observed|demonstrated|verified|confirmed|reproduced|recorded a|"
    r"we ran|was run|executed)\b",
    re.I,
)

#: Markers that an assertion rests on structure or expectation, not observation.
INFERENCE = re.compile(
    r"\b(implied|implies|strongly implied|presumably|should (?:be|do|hold|follow)|"
    r"expected to|would (?:be|have)|likely|ought to|by construction it must|"
    r"it follows that|necessarily)\b",
    re.I,
)

#: Words that hedge. Legitimate, but never in the same breath as a measurement verb.
#:
#: Bare "may" is deliberately excluded. In a patent specification it is the
#: standard word for a permissible embodiment ("the candidate may be activated"),
#: which is deontic permission rather than epistemic hedging -- and it fired on
#: exactly that construction the first time this detector was run against the
#: corpus. Hedging senses of "may" are caught by the explicit forms below.
HEDGE = re.compile(
    r"\b(suggests|might|possibly|appears to|may (?:indicate|suggest|imply|reflect|"
    r"well be|therefore be assumed))\b",
    re.I,
)

#: Numbers worth binding to a receipt. Years and section-like decimals excluded.
NUMBER = re.compile(r"(?<![\w./-])(\d{1,3}(?:,\d{3})+|\d{2,})(?![\w./%-])")
YEARISH = re.compile(r"^(19|20)\d{2}$")

#: Sentences that discuss the register itself. Excluded, or the tool flags its own
#: findings text forever -- every hostile-review entry quotes the defect it records.
META = re.compile(
    r"\b(overclaim|unsupported|not a defence|nothing had measured|red[- ]team|"
    r"P1[4-8]\b|E[45]\b|register|wording|we decline|would be the same|"
    r"is not a defence|inference|convergence has not)\b",
    re.I,
)

SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*`\"'])")


HEXISH = re.compile(r"^[0-9a-f]{16,}$", re.I)


def _harvest(node: Any, seen: set[str]) -> None:
    """Collect numeric leaves and short numeric strings, skipping digests.

    Scraping digit runs out of the raw JSON text was the first implementation and
    it was worthless: a sha256 contains long digit runs, so ~69,000 tokens counted
    as "bound" and almost any number in the prose matched one. A check that
    accepts everything is decorative, which is the failure mode this whole tool
    exists to catch -- so it is not left in place here.
    """
    if isinstance(node, bool):
        return
    if isinstance(node, int):
        seen.add(str(node))
        seen.add(f"{node:,}")
    elif isinstance(node, float):
        seen.add(str(node))
        if node.is_integer():
            seen.add(str(int(node)))
    elif isinstance(node, str):
        if len(node) > 200 or HEXISH.match(node.removeprefix("sha256:")):
            return
        for raw in re.findall(r"(?<![\w.])\d{1,3}(?:,\d{3})*(?![\w.])|(?<![\w.])\d+(?![\w.])",
                              node):
            token = raw.replace(",", "")
            if token.isdigit() and len(token) <= 9:
                seen.add(token)
                seen.add(f"{int(token):,}")
    elif isinstance(node, dict):
        for key, value in node.items():
            if "sha256" in key.lower() or "hash" in key.lower():
                continue
            _harvest(value, seen)
    elif isinstance(node, list):
        for value in node:
            _harvest(value, seen)


def receipt_numbers() -> set[str]:
    """Numbers a receipt actually asserts, as opposed to digits inside a digest."""
    seen: set[str] = set()
    for rel in RECEIPT_ROOTS:
        for path in (ROOT / rel).rglob("*.json"):
            try:
                _harvest(json.loads(path.read_text(encoding="utf-8")), seen)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
    return seen


def sentences(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", ">", "```", "- [")):
            continue
        for part in SENTENCE.split(stripped):
            if part.strip():
                out.append((lineno, part.strip()))
    return out


def scan_text(name: str, text: str, known: set[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for lineno, sentence in sentences(text):
        if META.search(sentence):
            continue

        meas = MEASUREMENT.search(sentence)
        if not meas:
            continue

        infer = INFERENCE.search(sentence) or HEDGE.search(sentence)
        if infer:
            findings.append(
                {
                    "document": name,
                    "line": lineno,
                    "kind": "REGISTER_MIXED",
                    "why": (
                        "one sentence claims an observation and hedges or infers it. "
                        "Split them: state what was observed, then state separately what "
                        "is believed to follow."
                    ),
                    "measurement_term": meas.group(0),
                    "inference_term": infer.group(0),
                    "sentence": sentence[:300],
                }
            )
            continue

        unbound = [
            n.replace(",", "")
            for n in NUMBER.findall(sentence)
            if not YEARISH.match(n.replace(",", ""))
            and n.replace(",", "") not in known
            and n not in known
        ]
        if unbound:
            findings.append(
                {
                    "document": name,
                    "line": lineno,
                    "kind": "MEASUREMENT_CLAIM_WITH_UNBOUND_NUMBER",
                    "why": (
                        "a sentence in the measurement register carries a number that "
                        "appears in no live receipt. Either bind it or move the sentence "
                        "out of that register."
                    ),
                    "measurement_term": meas.group(0),
                    "unbound_numbers": sorted(set(unbound)),
                    "sentence": sentence[:300],
                }
            )
    return findings


def self_test(known: set[str]) -> dict[str, Any]:
    """Positive control: synthetic text carrying each defect, plus a clean case."""
    mixed = "The future path was measured and is strongly implied to hold generally."
    unbound = "We verified 987654321 distinct assignments across the corpus."
    clean = "The candidate set was emptied and the comparator produced divergent decisions."

    r_mixed = scan_text("__control__", mixed, known)
    r_unbound = scan_text("__control__", unbound, known)
    r_clean = scan_text("__control__", clean, known)

    return {
        "purpose": (
            "Prove each detector fires. A register check that has never rejected a "
            "sentence is an assertion about itself."
        ),
        "mixed_register_detected": any(f["kind"] == "REGISTER_MIXED" for f in r_mixed),
        "unbound_number_detected": any(
            f["kind"] == "MEASUREMENT_CLAIM_WITH_UNBOUND_NUMBER" for f in r_unbound
        ),
        "clean_sentence_passes": not r_clean,
        "separates": (
            any(f["kind"] == "REGISTER_MIXED" for f in r_mixed)
            and any(f["kind"] == "MEASUREMENT_CLAIM_WITH_UNBOUND_NUMBER" for f in r_unbound)
            and not r_clean
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    known = receipt_numbers()
    control = self_test(known)

    findings: list[dict[str, Any]] = []
    coverage = {"sentences": 0, "measurement_register": 0, "meta_suppressed": 0,
                "meta_suppressed_and_mixed": 0}
    if not args.self_test:
        for name, rel in DOCS.items():
            path = ROOT / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            findings += scan_text(name, text, known)
            # Coverage, so a zero can be told apart from a filter that ate everything.
            for _, sentence in sentences(text):
                coverage["sentences"] += 1
                if not MEASUREMENT.search(sentence):
                    continue
                coverage["measurement_register"] += 1
                if META.search(sentence):
                    coverage["meta_suppressed"] += 1
                    if INFERENCE.search(sentence) or HEDGE.search(sentence):
                        coverage["meta_suppressed_and_mixed"] += 1

    receipt: dict[str, Any] = {
        "schema": "tavonel.inference-vs-measurement-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "root_class_guarded": "INFERENCE_PROMOTED_TO_MEASUREMENT",
        "origin_classes": [
            "MEASURED", "STATIC_CODE_AUDIT", "DERIVED", "INFERRED",
            "EXPECTED", "EXTERNAL", "NOT_MEASURED",
        ],
        "promotion_rule": (
            "INFERRED and EXPECTED are never promoted to MEASURED without a run. This "
            "tool enforces the register a sentence writes in, not the truth of its content."
        ),
        "documents_scanned": sorted(DOCS),
        "receipt_number_tokens": len(known),
        "positive_control": control,
        "detector_is_live": control["separates"],
        "coverage": coverage,
        "coverage_note": (
            "A zero is only meaningful with the denominator beside it. `measurement_register` "
            "is how many sentences the detector actually judged; `meta_suppressed` is how "
            "many it declined to judge because they discuss the defect itself. If "
            "meta_suppressed approached measurement_register, the null would mean the filter "
            "ate the corpus rather than that the corpus is clean."
        ),
        "findings": findings,
        "finding_count": len(findings),
        "clean": not findings,
        "scope_limitation": (
            "Lexical, not semantic. It cannot tell whether a measured number is correct, "
            "and it deliberately skips sentences that discuss the defect itself, or every "
            "hostile-review entry quoting an overclaim would be flagged as one. It narrows "
            "the manual surface; it does not replace it."
        ),
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()

    out = ROOT / "docs" / "ip" / "receipts" / "inference-vs-measurement-audit-2026-08-19.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"detector live: {control['separates']}  "
          f"(mixed={control['mixed_register_detected']}, "
          f"unbound={control['unbound_number_detected']}, "
          f"clean_passes={control['clean_sentence_passes']})")
    print(f"receipt number tokens: {len(known)}")
    if not args.self_test:
        print(f"coverage: {coverage['measurement_register']} measurement-register sentences "
              f"of {coverage['sentences']}; {coverage['meta_suppressed']} suppressed as meta "
              f"({coverage['meta_suppressed_and_mixed']} of those mixed)")
    print(f"findings: {len(findings)}")
    for f in findings[:25]:
        print(f"  ! {f['document']}:{f['line']} {f['kind']} [{f.get('measurement_term')}] "
              f"{f.get('inference_term') or f.get('unbound_numbers')}")
        print(f"      {f['sentence'][:150]}")
    return 0 if control["separates"] else 1


if __name__ == "__main__":
    sys.exit(main())
