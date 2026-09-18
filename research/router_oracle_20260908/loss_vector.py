"""Loss vector freeze — map the stored Arena metrics onto the section 31 taxonomy.

Section 33 requires the aggregation weights to be frozen *before* any holdout.
Phase A has no holdout at all -- it is a ceiling computed on stored outputs --
so the freeze here is the record that these weights were written down before
``oracle.py`` was run, and that they were chosen from the taxonomy's own
structure rather than from any observed per-model result.

Where the taxonomy has no signal in the artifacts, the row says NO_SIGNAL and
carries weight 0.0. Zero here means *unmeasurable from stored outputs*, not
*unimportant*. Nothing is fabricated to fill a row.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

FREEZE_ID = "TAVONEL-ROUTER-ORACLE-LOSSVEC-2026-09-08-V1"

# Composite unit-loss weights over the taxonomy classes that have a signal.
# Rationale is structural, not empirical: text carries most of the page's
# information, tables carry the highest-consequence structured content, and
# reading order and formula split the remainder. No per-model score was
# consulted to pick these.
WEIGHTS: dict[str, float] = {
    "L0": 0.00,  # applied as a hard override, not a weighted term
    "L1": 0.40,
    "L2": 0.00,  # NO_SIGNAL
    "L3": 0.15,
    "L4": 0.30,
    "L5": 0.15,
    "L6": 0.00,  # chart-only signal, ParseBench facet, reported separately
    "L7": 0.00,  # NO_SIGNAL
    "L8": 0.00,  # NO_SIGNAL
}

# Which stored per-unit field feeds each taxonomy class, per benchmark.
TAXONOMY: dict[str, dict[str, Any]] = {
    "L0": {
        "name": "File/Page",
        "section_31_rows": ["missing file/page", "duplicate page"],
        "signals": {
            "frozen_outputs": "manifest.jsonl status FAILED per sample",
            "omnidoc": "page absent from a model's per-page edit JSON",
            "olmocr": "official_result.json candidate_errors + absent test rows",
            "parsebench": "example absent from a model's evaluation CSV",
        },
        "covered": ["missing file/page"],
        "no_signal_rows": ["duplicate page"],
        "application": "hard override: a missing unit scores loss 1.0 in the "
        "missing-as-failure cohort and is excluded from the intersection cohort",
    },
    "L1": {
        "name": "Text",
        "section_31_rows": [
            "missing/hallucinated text",
            "CER/WER/edit",
            "truncation/repetition",
        ],
        "signals": {
            "omnidoc": "text_block_per_page_edit.json (normalized edit distance)",
            "olmocr": "per-test passed where type in {present, absent, baseline}",
            "parsebench": "text_content _evaluation_results.csv record-pass rate",
        },
        "covered": ["CER/WER/edit", "missing/hallucinated text (partially, via edit)"],
        "no_signal_rows": [
            "truncation vs repetition as separate labelled failure modes"
        ],
    },
    "L2": {
        "name": "Critical Token",
        "section_31_rows": ["number", "sign", "date", "unit", "currency", "identifier"],
        "signals": {},
        "covered": [],
        "no_signal_rows": ["number", "sign", "date", "unit", "currency", "identifier"],
        "status": "NO_SIGNAL",
        "why": "No evaluator in this campaign annotates typed critical tokens. "
        "olmOCR present/absent tests check literal string presence and are NOT a "
        "substitute: they are untyped and their anchors were not selected for "
        "numeric/date/unit consequence. SCLR (section 32) therefore cannot be "
        "computed from stored outputs and needs a critical-token detector.",
    },
    "L3": {
        "name": "Structure",
        "section_31_rows": ["heading", "paragraph", "list", "columns", "reading order"],
        "signals": {
            "omnidoc": "reading_order_per_page_edit.json",
            "olmocr": "per-test passed where type == order",
            "parsebench": "text_formatting _evaluation_results.csv",
        },
        "covered": ["reading order", "columns (indirectly, via multi_column slice)"],
        "no_signal_rows": ["heading", "paragraph", "list"],
    },
    "L4": {
        "name": "Table",
        "section_31_rows": [
            "row/column",
            "cell",
            "merged cell",
            "headers",
            "continuation",
            "footnote",
        ],
        "signals": {
            "omnidoc": "table_per_page_edit.json; table_per_table_TEDS.json",
            "olmocr": "per-test passed where type == table",
            "parsebench": "table _evaluation_results.csv (teds, grits)",
        },
        "covered": ["row/column", "cell", "headers (inside TEDS structure)"],
        "no_signal_rows": ["merged cell", "continuation", "footnote"],
    },
    "L5": {
        "name": "Formula",
        "section_31_rows": [
            "token/operator",
            "superscript/subscript",
            "layout/semantic equivalence",
        ],
        "signals": {
            "omnidoc": "display_formula_per_page_edit.json",
            "olmocr": "per-test passed where type == math",
        },
        "covered": ["token/operator", "superscript/subscript (inside the edit)"],
        "no_signal_rows": ["layout/semantic equivalence as a separate judgement"],
    },
    "L6": {
        "name": "Visual",
        "section_31_rows": [
            "chart",
            "figure",
            "diagram",
            "caption",
            "labels",
            "relationships",
        ],
        "signals": {
            "parsebench": "chart _evaluation_results.csv record-pass rate"
        },
        "covered": ["chart"],
        "no_signal_rows": ["figure", "diagram", "caption", "labels", "relationships"],
        "status": "PARTIAL",
        "why": "Only ParseBench chart has a per-example signal, and the "
        "leaderboard records ParseBench layout as N/A for every model (empty "
        "layout predictions), so figure/diagram geometry is unmeasurable here.",
    },
    "L7": {
        "name": "Evidence/Provenance",
        "section_31_rows": [
            "source locator",
            "SourceVersion",
            "representation",
            "hash/lineage",
        ],
        "signals": {},
        "covered": [],
        "no_signal_rows": [
            "source locator",
            "SourceVersion",
            "representation",
            "hash/lineage",
        ],
        "status": "NO_SIGNAL",
        "why": "The three public evaluators score parsed content only. No "
        "provenance or evidence-locator field is emitted per unit.",
    },
    "L8": {
        "name": "Temporal/Identity",
        "section_31_rows": [
            "wrong version",
            "stale fact",
            "false merge",
            "missed change",
            "false change",
        ],
        "signals": {},
        "covered": [],
        "no_signal_rows": [
            "wrong version",
            "stale fact",
            "false merge",
            "missed change",
            "false change",
        ],
        "status": "NO_SIGNAL",
        "why": "Single-shot page parsing. No temporal cohort, no identity graph, "
        "no second version of any source in this campaign.",
    },
}

# Per-benchmark composite rules, frozen with the weights.
BENCHMARK_RULES: dict[str, Any] = {
    "omnidoc": {
        "unit": "page (OmniDocBench image_path)",
        "per_class_loss": {
            "L1": "text_block edit, clipped to [0, 1]",
            "L3": "reading_order edit, clipped to [0, 1]",
            "L4": "table edit, clipped to [0, 1]",
            "L5": "display_formula edit, clipped to [0, 1]",
        },
        "composite": "weighted mean of the classes PRESENT on that page, with "
        "WEIGHTS renormalized over the present classes. A page with no table has "
        "no table term; it is not scored 0 and it is not scored 1.",
        "page_class_labels": "OmniDocBench page_attribute: data_source, language, "
        "layout, subset, special_issue",
        "cluster": "document family = image_path prefix before the trailing page number",
    },
    "olmocr": {
        "unit": "test (olmOCR-Bench per-test row)",
        "per_class_loss": {
            "L1": "1 - passed for type in {present, absent, baseline}",
            "L3": "1 - passed for type == order",
            "L4": "1 - passed for type == table",
            "L5": "1 - passed for type == math",
        },
        "composite": "the primary olmOCR loss is the unweighted mean of per-test "
        "loss, which is the benchmark's own aggregation. The frozen WEIGHTS are "
        "NOT re-applied across test types: the class mix is fixed by the "
        "benchmark, and reweighting it would silently invent a different "
        "benchmark. The per-class breakdown is reported separately.",
        "page_class_labels": "source_jsonl (arxiv_math, multi_column, old_scans, "
        "old_scans_math, table_tests, headers_footers, long_tiny_text, baseline)",
        "cluster": "pdf",
    },
    "parsebench": {
        "unit": "example (test_id in _evaluation_results.csv)",
        "per_class_loss": {
            "L1": "1 - text_content record pass",
            "L3": "1 - text_formatting record pass",
            "L4": "1 - teds",
            "L6": "1 - chart record pass",
        },
        "composite": "reported per facet only. ParseBench layout is EXCLUDED: the "
        "leaderboard records layout N/A for every model (empty layout "
        "predictions), so a layout term would score the harness, not the model.",
        "page_class_labels": "tags column (easy/hard, facet)",
        "cluster": "document directory of test_id",
    },
}


def write_text_lf(path: Path, text: str) -> str:
    """Write UTF-8 with LF endings and return the digest of the bytes on disk.

    Path.write_text would translate newlines on Windows, so a digest printed
    from the in-memory string would not match the file. A receipt that does
    not verify is worse than no receipt.
    """
    data = text.encode("utf-8")
    path.write_bytes(data)
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def freeze_payload() -> dict[str, Any]:
    return {
        "schema": "tavonel.router_oracle.loss_vector_freeze.v1",
        "freeze_id": FREEZE_ID,
        "frozen_before": "any oracle computation in this lane (section 33 rule 1)",
        "holdout": "none — Phase A is an oracle ceiling on stored outputs, not a "
        "holdout evaluation. The freeze is recorded so Phase B/C cannot retune it.",
        "weights": WEIGHTS,
        "weights_basis": "structural: chosen from the section 31 taxonomy, not "
        "from any observed per-model score. Zero weight means NO_SIGNAL in the "
        "stored artifacts, never 'unimportant'.",
        "taxonomy": TAXONOMY,
        "benchmark_rules": BENCHMARK_RULES,
        "no_signal_classes": [
            key for key, row in TAXONOMY.items() if row.get("status") == "NO_SIGNAL"
        ],
        "partial_signal_classes": [
            key for key, row in TAXONOMY.items() if row.get("status") == "PARTIAL"
        ],
        "consequences": [
            "SCLR (section 32) is NOT computable in Phase A: it needs L2 critical "
            "token opportunities and an accept/refuse decision, and stored outputs "
            "carry neither.",
            "IRR (section 33) is reported here as an IRR PROXY over L1/L3/L4/L5 "
            "only. It is not the IRR of the blueprint, which spans L0-L8.",
            "Any headline that needs L2, L7 or L8 is out of reach until a "
            "critical-token detector and an evidence/temporal cohort exist.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out_path = Path(__file__).with_name("LOSS_VECTOR_FREEZE.json")
    if argv and argv[0] == "--out":
        out_path = Path(argv[1])
    payload = freeze_payload()
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    # self_sha256 is the digest of the payload WITHOUT the field, so it stays
    # verifiable: strip the key from the file and re-hash what is left.
    payload["self_sha256"] = f"sha256:{digest}"
    final = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    file_digest = write_text_lf(out_path, final)
    print(f"wrote {out_path}")
    print(f"content_sha256(without self_sha256) = sha256:{digest}")
    print(f"file_sha256 = {file_digest}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
