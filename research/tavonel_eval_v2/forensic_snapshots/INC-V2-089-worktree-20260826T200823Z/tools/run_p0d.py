#!/usr/bin/env python3
"""P0d driver: source coverage, reference facts, and the currency rule.

Runs the whole chain on the existing raw sources — the canonical documents are
read, never rewritten, so the P0b and P0c corpora are untouched and their
results stand as they are.

The two constructed controls live in this namespace and are built here, because
a run in which the grammar happened to classify everything reads identically to
a run in which the residue check does not work.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "facets"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file, sha_text  # noqa: E402
from evidence import write_immutable  # noqa: E402
from facet_coverage import FACETS  # noqa: E402
from source_spans import (  # noqa: E402
    IGNORED,
    MODELED,
    UNMODELED,
    attribute_to_canonical,
    coverage,
    html_spans,
    markdown_spans,
    partition_holds,
    reference_facts,
)

PROTOCOL = NS / "protocols" / "P0d_source_coverage.yaml"
CONTROLS = NS / "artifacts" / "development" / "p0d_controls"

INC_V2_006_PAIRS = {
    "git-013-website-deployment": "reference_change_expected",
    "git-019-book-ch04-01-what-is-ownership": "ignored_change_expected",
}


def fact_projection(fact: dict[str, Any]) -> list[str]:
    """Which known facets a reference fact projects into.

    No new facet is introduced. A reference target is text, so it moves the
    lexical and semantic projections; its kind and position in the document are
    structural. That keeps the 2026-08-21 ruling — no arbitrary fourth domain
    facet — while still making the fact first-class.
    """
    projected: list[str] = []
    if fact.get("target") or fact.get("identifier"):
        projected.extend(["LEXICAL", "SEMANTIC"])
    if fact.get("reference_kind") is not None:
        projected.append("STRUCTURAL")
    return [facet for facet in FACETS if facet in projected]


def analyse(raw_path: Path, canonical_path: Path) -> dict[str, Any]:
    text = raw_path.read_text(encoding="utf-8", errors="replace")
    document = json.loads(canonical_path.read_text(encoding="utf-8"))
    is_markdown = raw_path.suffix.lower() in (".md", ".markdown")

    spans = markdown_spans(text) if is_markdown else html_spans(text)
    length = len(text) if is_markdown else len(spans)
    partition = partition_holds(spans, length)

    facts = reference_facts(spans)
    values = [
        str(fact.get("target") or fact.get("identifier") or fact.get("name") or "")
        for fact in facts
    ]
    attribution = (
        attribute_to_canonical(spans, [unit["text"] for unit in document["units"]], values)
        if is_markdown
        else {"spans_reclassified": 0, "unmodeled_span_count": 0, "unmodeled_spans": []}
    )

    measured = coverage(spans)
    unprojectable = [fact for fact in facts if not fact_projection(fact)]
    unmodeled_kinds = sorted({span.kind for span in spans if span.classification == UNMODELED})

    return {
        "raw_path": rel(raw_path),
        "raw_sha256": sha_file(raw_path),
        "granularity": "characters" if is_markdown else "parser_events",
        "partition": partition,
        "coverage": measured,
        "unmodeled_kinds": unmodeled_kinds,
        "attribution": attribution,
        "reference_fact_count": len(facts),
        "reference_facts": [
            {
                "reference_kind": fact.get("reference_kind"),
                "target": fact.get("target"),
                "identifier": fact.get("identifier"),
                "name": fact.get("name"),
                "arguments": fact.get("arguments"),
                "facets": fact_projection(fact),
            }
            for fact in facts
        ],
        "reference_facts_without_projection": len(unprojectable),
        "classification_values": sorted({span.classification for span in spans}),
    }


def fact_key(fact: dict[str, Any]) -> str:
    return (
        "|".join(
            str(fact.get(field) or "")
            for field in ("reference_kind", "name", "target", "identifier")
        )
        + "|"
        + json.dumps(fact.get("arguments") or {}, sort_keys=True)
    )


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    left = {fact_key(fact) for fact in before["reference_facts"]}
    right = {fact_key(fact) for fact in after["reference_facts"]}
    added = sorted(right - left)
    removed = sorted(left - right)

    # a source difference exists if the raw bytes differ at all
    source_moved = before["raw_sha256"] != after["raw_sha256"]
    unmodeled_present = (
        after["coverage"]["by_classification"].get(UNMODELED, 0) > 0
        or before["coverage"]["by_classification"].get(UNMODELED, 0) > 0
    )
    ignored_present = (
        after["coverage"]["by_classification"].get(IGNORED, 0) > 0
        or before["coverage"]["by_classification"].get(IGNORED, 0) > 0
    )
    return {
        "source_moved": source_moved,
        "reference_facts_added": added[:8],
        "reference_facts_removed": removed[:8],
        "reference_fact_change_count": len(added) + len(removed),
        "reference_facts_changed": bool(added or removed),
        "unmodeled_residue_present": unmodeled_present,
        "ignored_residue_present": ignored_present,
        "currency_state": (
            "SOURCE_COVERAGE_INCOMPLETE" if unmodeled_present else "SOURCE_COVERAGE_COMPLETE"
        ),
        "may_be_reported_current": not unmodeled_present,
    }


# --- constructed controls ----------------------------------------------------

_BASE = """---
title: P0d control document
---

# Overview

This paragraph is ordinary prose that the canonicaliser keeps in a unit so that
the containment probe has something to find. It is long enough to clear the text
floor without any difficulty at all.

See the [upstream guide](https://example.invalid/guide) for more.
"""

_IGNORED_AFTER = _BASE.replace("# Overview", "<!-- editorial note v1 -->\n# Overview")
_IGNORED_BEFORE = _BASE.replace("# Overview", "<!-- editorial note v2 -->\n# Overview")

_UNMODELED_MARKUP = '<policyref binding="true" targetref="reg/2026/117"></policyref>'
_UNMODELED_BEFORE = _BASE
_UNMODELED_AFTER = _BASE + "\n" + _UNMODELED_MARKUP + "\n"


def write_control(name: str, side: str, body: str) -> Path:
    target = CONTROLS / name / (side + ".md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def control_document(body: str) -> dict[str, Any]:
    """A minimal canonical document for a control, built here on purpose.

    The production canonicaliser is not invoked: these controls exist to
    exercise the classifier, and routing them through the canonicaliser would
    make the control's outcome depend on the component under study.
    """
    prose = [
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.startswith(("#", "---", "<!--", "<policyref", "title:"))
    ]
    return {
        "source_id": "control:p0d",
        "units": [
            {
                "explicit_path": ["Overview"],
                "heading": "Overview",
                "ordinal": 0,
                "text": " ".join(prose),
                "text_sha256": sha_text(" ".join(prose)),
            }
        ],
    }


def analyse_control(name: str, before_body: str, after_body: str) -> dict[str, Any]:
    rows = {}
    for side, body in (("before", before_body), ("after", after_body)):
        raw = write_control(name, side, body)
        canonical = CONTROLS / name / (side + ".canonical.json")
        canonical.write_text(
            json.dumps(control_document(body), sort_keys=True, indent=2), encoding="utf-8"
        )
        rows[side] = analyse(raw, canonical)
    return {
        "name": name,
        "before": rows["before"],
        "after": rows["after"],
        **compare(rows["before"], rows["after"]),
    }


def run(manifest: Path) -> int:
    started = now()
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    natural = [pair for pair in corpus["pairs"] if pair["group"] == "natural"]

    rows: list[dict[str, Any]] = []
    for pair in natural:
        pair_id = pair["pair_id"]
        raw_dir = NS / "artifacts" / "development" / "raw" / pair_id
        candidates = {
            side: next(iter(sorted(raw_dir.glob(side + ".*"))), None)
            for side in ("before", "after")
        }
        if not candidates["before"] or not candidates["after"]:
            rows.append({"pair_id": pair_id, "state": "RAW_SOURCE_ABSENT"})
            continue
        before = analyse(candidates["before"], ROOT / pair["before"]["path"])
        after = analyse(candidates["after"], ROOT / pair["after"]["path"])
        rows.append(
            {
                "pair_id": pair_id,
                "state": "ANALYSED",
                "group": "natural",
                "source_family": pair["source_family"],
                "source_id": pair["source_id"],
                "before": before,
                "after": after,
                **compare(before, after),
            }
        )

    controls = [
        analyse_control("ctrl-ignored-comment-only", _IGNORED_BEFORE, _IGNORED_AFTER),
        analyse_control("ctrl-unmodeled-construct", _UNMODELED_BEFORE, _UNMODELED_AFTER),
    ]

    analysed = [row for row in rows if row["state"] == "ANALYSED"]

    # --- per-family coverage, never summed across families ------------------
    by_family: dict[str, Any] = {}
    for family in sorted({row["source_family"] for row in analysed}):
        subset = [row for row in analysed if row["source_family"] == family]
        totals = {MODELED: 0, IGNORED: 0, UNMODELED: 0}
        for row in subset:
            for side in ("before", "after"):
                for key, value in row[side]["coverage"]["by_classification"].items():
                    totals[key] = totals.get(key, 0) + value
        grand = sum(totals.values())
        by_family[family] = {
            "documents": len(subset) * 2,
            "granularity": subset[0]["after"]["granularity"],
            "totals": totals,
            "source_coverage": ((totals[MODELED] + totals[IGNORED]) / grand) if grand else 0.0,
            "modeled_share": (totals[MODELED] / grand) if grand else 0.0,
            "unmodeled_share": (totals[UNMODELED] / grand) if grand else 0.0,
            "note": "an upper bound; the containment probe is loose in one direction only",
        }

    # --- gates ---------------------------------------------------------------
    partition_failures = [
        row["pair_id"]
        for row in analysed
        for side in ("before", "after")
        if not row[side]["partition"]["holds"]
    ]
    declared = {MODELED, IGNORED, UNMODELED}
    classification_failures = [
        row["pair_id"]
        for row in analysed
        for side in ("before", "after")
        if not set(row[side]["classification_values"]) <= declared
    ]
    unprojectable = sum(
        row[side]["reference_facts_without_projection"]
        for row in analysed
        for side in ("before", "after")
    )

    k8s = next((row for row in analysed if row["pair_id"] == "git-013-website-deployment"), None)
    rust = next(
        (row for row in analysed if row["pair_id"] == "git-019-book-ch04-01-what-is-ownership"),
        None,
    )
    reference_capture = {
        "kubernetes_reference_changed": bool(k8s and k8s["reference_facts_changed"]),
        "kubernetes_change": (k8s["reference_facts_added"] + k8s["reference_facts_removed"])[:4]
        if k8s
        else [],
        "rust_reference_changed": bool(rust and rust["reference_facts_changed"]),
        "rust_has_ignored_residue": bool(rust and rust["ignored_residue_present"]),
    }

    ignored_control = controls[0]
    unmodeled_control = controls[1]

    currency_violations = [
        row["pair_id"]
        for row in analysed
        if row["unmodeled_residue_present"] and row["may_be_reported_current"]
    ]

    equivalent_ids = set()
    p0c_pointer = NS / "receipts" / "latest" / "p0c-coverage-completeness.json"
    if p0c_pointer.is_file():
        p0c = json.loads(
            (ROOT / json.loads(p0c_pointer.read_text(encoding="utf-8"))["points_to"]).read_text(
                encoding="utf-8"
            )
        )
        equivalent_ids = {
            record["pair_id"]
            for record in p0c["records"]
            if record.get("equivalence_verdict") == "EQUIVALENT"
        }
    both = sorted(
        row["pair_id"]
        for row in analysed
        if row["pair_id"] in equivalent_ids
        and row["currency_state"] == "SOURCE_COVERAGE_INCOMPLETE"
    )

    gates = {
        "G_P0D_PARTITION": {"passed": not partition_failures, "failures": partition_failures},
        "G_P0D_CLASSIFICATION_TOTAL": {
            "passed": not classification_failures,
            "failures": classification_failures,
        },
        "G_P0D_FACT_PROJECTION": {
            "passed": unprojectable == 0,
            "reference_facts_without_projection": unprojectable,
        },
        "G_P0D_REFERENCE_CAPTURE": {
            "passed": reference_capture["kubernetes_reference_changed"]
            and not reference_capture["rust_reference_changed"]
            and reference_capture["rust_has_ignored_residue"],
            **reference_capture,
        },
        "G_P0D_UNMODELED_POSITIVE": {
            "passed": unmodeled_control["unmodeled_residue_present"]
            and unmodeled_control["currency_state"] == "SOURCE_COVERAGE_INCOMPLETE",
            "currency_state": unmodeled_control["currency_state"],
        },
        "G_P0D_IGNORED_POSITIVE": {
            "passed": ignored_control["ignored_residue_present"]
            and ignored_control["may_be_reported_current"],
            "currency_state": ignored_control["currency_state"],
            "reference_facts_changed": ignored_control["reference_facts_changed"],
        },
        "G_P0D_CURRENCY_RULE": {
            "passed": not currency_violations,
            "violations": currency_violations,
        },
        "G_P0D_EQUIVALENCE_IS_NOT_SUFFICIENT": {
            "passed": bool(both),
            "pairs_equivalent_but_source_coverage_incomplete": both[:12],
            "count": len(both),
            "p0c_equivalent_pairs_seen": len(equivalent_ids),
        },
        "G_P0D_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }

    incomplete = [
        row["pair_id"] for row in analysed if row["currency_state"] == "SOURCE_COVERAGE_INCOMPLETE"
    ]

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p0d_source_coverage.v1",
        "protocol": "P0d_source_coverage",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "corpus_manifest": rel(manifest),
        "corpus_manifest_file_sha256": sha_file(manifest),
        "classifier": rel(NS / "canonicalization" / "source_spans.py"),
        "classifier_sha256": sha_file(NS / "canonicalization" / "source_spans.py"),
        "pair_count": len(rows),
        "analysed_pair_count": len(analysed),
        "source_coverage_by_family": by_family,
        "families_are_not_comparable": (
            "markdown shares are over characters and HTML shares are over parser "
            "events. They are reported separately and are never summed."
        ),
        "pairs_source_coverage_incomplete": incomplete,
        "pairs_source_coverage_incomplete_count": len(incomplete),
        "controls": controls,
        "gates": gates,
        "verdict": "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL",
        "records": rows,
        "records_sha256": canonical_sha(rows),
        "equivalence_is_not_source_faithfulness": (
            "full-rebuild equivalence says the selective path and the full path "
            "agree. Both can agree about a canonical state that dropped a fact "
            "from the source. P0b and P0c are unaffected and unamended."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable(
        "p0d-source-coverage", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "verdict": body["verdict"],
                "pairs": len(analysed),
                "incomplete": len(incomplete),
                "coverage": {
                    family: round(values["source_coverage"], 4)
                    for family, values in by_family.items()
                },
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if body["verdict"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=NS / "receipts" / "p0b-corpus-manifest.json"
    )
    args = parser.parse_args()
    return run(args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
