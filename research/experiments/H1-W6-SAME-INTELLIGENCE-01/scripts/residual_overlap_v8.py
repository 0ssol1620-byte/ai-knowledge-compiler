#!/usr/bin/env python3
"""The v8 residual-overlap gate, and the one calibration it is allowed.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §2B. Raw query↔oracle overlap is not
used, because v7 measured it at 0.750 against a 0.50 ceiling while verbatim
containment was 0 and the median share contributed by the subject's own name was
0.667. Overlap was counting the question's addressing information as leakage.

Here every query token is labelled by provenance — `SUBJECT`, `ATTRIBUTE`,
`DATE`, `TEMPLATE`, or `RESIDUAL` — and the overlap with the oracle passage is
split in two:

- **structured intent** — tokens a declared input or a fixed template literal
  supplied. Reported, never gated.
- **passage-derived residual** — everything else. **This is the gate.**

**The calibration rule was fixed in the protocol before this ran, and is applied
once.** Ceiling = the v7 development residual median rounded up to the next 0.05,
plus 0.05 headroom; the same construction on the p90. The rule is not "pick a
number that the development distribution passes" — the number is a function of
the distribution, computed once, and frozen before a v8 holdout title is chosen.

**What this gate is worth, stated honestly.** For a builder that passes the §2A
taint gate the residual is 0 by construction, so 2B confirms 2A rather than
adding an independent signal on a clean builder. Its value is as a second,
differently-implemented detector over the *emitted questions* rather than over
the builder: it still fires if a question set arrives from a builder whose taint
audit was skipped, bypassed, or run against different code. The positive controls
below are what make that claim checkable.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
PROTOCOL = EXP / "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md"

TOKEN = re.compile(r"[a-z0-9]{2,}")


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


def tokens(text: str) -> set[str]:
    return set(TOKEN.findall(text.lower()))


def label(query: str, *, subject: str, attribute: str, date: str,
          literals: set[str]) -> dict[str, set[str]]:
    """Assign each query token to the earliest provenance that can explain it.

    Order matters and is declared: SUBJECT, then ATTRIBUTE, then DATE, then
    TEMPLATE. A token explainable by more than one input is credited to the first
    -- overlapping credit would let the same token be counted twice and make the
    residual look smaller than it is.
    """
    remaining = tokens(query)
    out: dict[str, set[str]] = {}
    for name, source in (("SUBJECT", tokens(subject)), ("ATTRIBUTE", tokens(attribute)),
                         ("DATE", tokens(date)), ("TEMPLATE", literals)):
        out[name] = remaining & source
        remaining = remaining - source
    out["RESIDUAL"] = remaining
    return out


def measure(query: str, oracle: str, *, subject: str, attribute: str, date: str,
            literals: set[str]) -> dict[str, float]:
    parts = label(query, subject=subject, attribute=attribute, date=date, literals=literals)
    q = tokens(query)
    o = tokens(oracle)
    if not q:
        return {"raw_overlap": 0.0, "structured_intent_overlap": 0.0, "residual_overlap": 0.0}
    structured = set().union(*(parts[k] for k in ("SUBJECT", "ATTRIBUTE", "DATE", "TEMPLATE")))
    return {
        "raw_overlap": len(q & o) / len(q),
        "structured_intent_overlap": len(structured & o) / len(q),
        "residual_overlap": len(parts["RESIDUAL"] & o) / len(q),
    }


def ceiling_from(value: float) -> float:
    """The frozen calibration rule: round up to the next 0.05, add 0.05 headroom."""
    import math
    return round(math.ceil(value / 0.05) * 0.05 + 0.05, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question-set", type=Path, required=True,
                    help="v7 DEVELOPMENT question set; the v8 holdout is not opened here")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    taint = load(HERE / "taint_gate_v8.py", "w6v8_taint")
    base = load(HERE / "validate_baseline.py", "w6v8_baseline2")
    adapter = load(
        ROOT / "research/experiments/H1-B-REAL-REVISION-01/scripts/"
        "run_public_real_revision_holdout_v3.py", "w6v8_adapter2")
    literals = taint.LITERALS

    qs = json.loads(args.question_set.read_text(encoding="utf-8"))
    primary = sorted((q for q in qs["questions"] if q["question_class"] == "revision_sensitive"),
                     key=lambda q: q["question_id"])[: args.limit]

    cache: dict[str, list[str]] = {}
    rows: list[dict[str, Any]] = []
    for q in primary:
        path = q["relative_after_path"]
        if path not in cache:
            revision = adapter.Revision(
                title=q["subject"], revid=q["after_revision_id"], parentid=0,
                timestamp=q["after_timestamp"], mw_sha1="",
                text=(EXP / path).read_text(encoding="utf-8"))
            snapshots, _shape = adapter.section_units(revision)
            cache[path] = [s.text for s in snapshots if len(base.tokens(s.text)) >= 20]
        wanted = tokens(q["gold_current"])
        carrying = [u for u in cache[path] if wanted and wanted <= tokens(u)]
        if not carrying:
            continue
        oracle = min(carrying, key=len)
        date = q["before_timestamp"][:10]
        for template_id in taint.TEMPLATES:
            query = taint.render(subject=q["subject"], attribute=q["attribute"],
                                 date=date, template_id=template_id)
            rows.append({
                "template_id": template_id, "oracle": oracle, "query": query,
                "subject": q["subject"], "attribute": q["attribute"], "date": date,
                **measure(query, oracle, subject=q["subject"], attribute=q["attribute"],
                          date=date, literals=literals),
            })

    def dist(key: str) -> dict[str, float]:
        vals = sorted(r[key] for r in rows)
        n = len(vals)
        return {
            "median": round(statistics.median(vals), 4),
            "p90": round(vals[min(n - 1, int(0.9 * n))], 4),
            "max": round(vals[-1], 4),
        }

    residual = dist("residual_overlap")
    raw = dist("raw_overlap")
    structured = dist("structured_intent_overlap")
    median_ceiling = ceiling_from(residual["median"])
    p90_ceiling = ceiling_from(residual["p90"])

    # Positive controls, in this execution: an injected oracle token must exceed
    # the ceiling, an untouched query must not.
    injected: list[float] = []
    for r in rows:
        extra = sorted(tokens(r["oracle"]) - tokens(r["subject"]) - tokens(r["attribute"])
                       - tokens(r["date"]) - literals)
        if not extra:
            continue
        m = measure(f"{r['query']} {extra[0]}", r["oracle"], subject=r["subject"],
                    attribute=r["attribute"], date=r["date"], literals=literals)
        injected.append(m["residual_overlap"])
    injected_exceeds = bool(injected) and all(v > median_ceiling for v in injected)
    clean_within = all(r["residual_overlap"] <= median_ceiling for r in rows)
    separates = injected_exceeds and clean_within

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v8-residual-overlap-calibration.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md",
        "protocol_sha256": "sha256:" + hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "run_class": "DEVELOPMENT_ONLY",
        "run_class_note": (
            "the calibration distribution is the v7 development set. No v8 holdout title is "
            "read here, and no number in this receipt is a paper endpoint."
        ),
        "development_question_set_sha256": qs.get("receipt_sha256"),
        "queries_measured": len(rows),
        "token_provenance_labels": ["SUBJECT", "ATTRIBUTE", "DATE", "TEMPLATE", "RESIDUAL"],
        "label_precedence": "SUBJECT > ATTRIBUTE > DATE > TEMPLATE; a token is credited once",
        "raw_overlap_distribution": raw,
        "structured_intent_overlap_distribution": structured,
        "residual_overlap_distribution": residual,
        "calibration_rule": (
            "ceiling = residual statistic rounded up to the next 0.05, plus 0.05 headroom. "
            "Fixed in the protocol before this measurement and applied exactly once."
        ),
        "frozen_residual_median_ceiling": median_ceiling,
        "frozen_residual_p90_ceiling": p90_ceiling,
        "frozen_before": "any v8 holdout title is chosen",
        "positive_controls": {
            "injected_oracle_token_exceeds_ceiling": injected_exceeds,
            "injected_controls_run": len(injected),
            "untouched_query_within_ceiling": clean_within,
            "separates": separates,
        },
        "gate_state": "CALIBRATED" if separates else "NOT_RUN",
        "relationship_to_the_structural_gate": (
            "for a builder that passes the section 2A taint gate the residual is 0 by "
            "construction, so on a clean builder this confirms 2A rather than adding an "
            "independent signal. It is retained as a second detector over the emitted "
            "questions rather than over the builder, so it still fires on a question set "
            "whose taint audit was skipped, bypassed, or run against different code."
        ),
        "what_v7_measured_and_why_it_was_not_leakage": (
            "raw overlap median 0.750 against a 0.50 ceiling, verbatim containment 0, median "
            "subject-name share of shared tokens 0.667. The decomposition above separates "
            "that addressing information from passage-derived text."
        ),
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"queries measured: {len(rows)}")
    print(f"  raw overlap          median={raw['median']:<8} p90={raw['p90']}")
    print(f"  structured intent    median={structured['median']:<8} p90={structured['p90']}")
    print(f"  residual (the gate)  median={residual['median']:<8} p90={residual['p90']}")
    print(f"frozen ceilings: median<={median_ceiling}  p90<={p90_ceiling}")
    print(f"controls: injected exceeds={injected_exceeds} (n={len(injected)})  "
          f"clean within={clean_within}  separates={separates}")
    print(f"wrote {args.output.resolve().relative_to(ROOT).as_posix()}")
    return 0 if separates else 1


if __name__ == "__main__":
    sys.exit(main())
