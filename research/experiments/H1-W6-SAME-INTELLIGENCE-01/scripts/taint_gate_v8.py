#!/usr/bin/env python3
"""The v8 structural taint gate: what the question builder was allowed to read.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §2A. The builder may read `subject`,
`attribute`, `date` where a template requires one, and a fixed `template_id`. It
may not read the value, the oracle sentence, the surrounding passage, or any
answer-bearing lexical context.

**Why this replaces raw overlap as the primary leakage gate.** v7 measured median
query↔oracle overlap 0.750 against a 0.50 ceiling with **verbatim containment 0**,
and 0.667 of the shared tokens were the subject's own name. The overlap metric was
counting the question's addressing information as leakage. Overlap answers "do
these strings resemble each other". This answers the question §3 was actually
written to ask: **could the builder have seen the answer?**

The check is a runtime taint test rather than a promise about the code. Every
content token of a rendered query must be derivable from the declared inputs or
from the template's own fixed literals. A token that is in the query and in the
oracle passage but in none of the declared inputs is **tainted** — it can only
have come from the passage.

**The gate is required to fail on a mutant, in the same execution.** A taint gate
that has never rejected anything is not evidence; this programme has shipped
three detectors that could not fire. `MUTANTS` below inject oracle tokens the way
a careless builder would, and every one must be caught or the gate reports
NOT_RUN and none of its results may be cited.
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

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
BASELINE = HERE / "validate_baseline.py"
PROTOCOL = EXP / "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md"

#: The only inputs a v8 question builder may read. Named here so the gate and the
#: builder cannot drift apart silently.
DECLARED_INPUTS = ("subject", "attribute", "date", "template_id")

#: §2 templates, carried forward unchanged from PROTOCOL_V2 so v7 and v8 questions
#: remain comparable. Their fixed literals are a legitimate token source.
TEMPLATES = {
    "current": "What is the {attribute} of {subject}?",
    "as_of": "As of {date}, what is the {attribute} of {subject}?",
    "provenance": "Which source states the {attribute} of {subject}, and where?",
}

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


def template_literals() -> set[str]:
    """Tokens the fixed templates contribute regardless of any input."""
    out: set[str] = set()
    for template in TEMPLATES.values():
        out |= tokens(re.sub(r"\{\w+\}", " ", template))
    return out


LITERALS = template_literals()


def render(*, subject: str, attribute: str, date: str, template_id: str) -> str:
    """The reference builder. Its signature is the taint boundary.

    It cannot read a value, a passage or an oracle because it is never given one.
    That is the structural half; the runtime check below is what makes the claim
    checkable rather than asserted.
    """
    return TEMPLATES[template_id].format(subject=subject, attribute=attribute, date=date)


def taint_of(query: str, *, subject: str, attribute: str, date: str) -> set[str]:
    """Query tokens that no declared input and no template literal can explain."""
    allowed = tokens(subject) | tokens(attribute) | tokens(date) | LITERALS
    return tokens(query) - allowed


def evaluate(builder: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Run a builder over items and report tainted output.

    A token is only counted as tainted when it also appears in the oracle
    passage. A builder that emitted an unexplained token found nowhere in the
    source would be a different defect -- and calling it leakage would overstate
    what this gate observes.
    """
    tainted: list[dict[str, Any]] = []
    rendered = 0
    for item in items:
        for template_id in TEMPLATES:
            query = builder(
                subject=item["subject"], attribute=item["attribute"],
                date=item["date"], template_id=template_id, oracle=item["oracle"],
            )
            rendered += 1
            stray = taint_of(query, subject=item["subject"], attribute=item["attribute"],
                             date=item["date"])
            from_passage = sorted(stray & tokens(item["oracle"]))
            if from_passage:
                tainted.append({
                    "subject": item["subject"], "attribute": item["attribute"],
                    "template_id": template_id, "tokens_from_passage": from_passage[:8],
                })
    return {"queries_rendered": rendered, "tainted_queries": len(tainted),
            "examples": tainted[:5], "passes": not tainted}


# --- mutants: how a builder leaks a passage in practice ---------------------

def _clean(*, subject: str, attribute: str, date: str, template_id: str,
           oracle: str) -> str:
    return render(subject=subject, attribute=attribute, date=date, template_id=template_id)


def _first_oracle_token(*, subject: str, attribute: str, date: str, template_id: str,
                        oracle: str) -> str:
    """One content token lifted from the passage -- the minimal leak.

    The token must be one no declared input could have supplied. An earlier
    revision of this mutant did not subtract the date tokens, so on 48 of 711
    queries it "injected" a numeral the template had already licensed -- not a
    leak, and correctly not flagged. A mutant that injects a non-leak measures
    the gate's tolerance, not its sensitivity.
    """
    base = render(subject=subject, attribute=attribute, date=date, template_id=template_id)
    extra = sorted(tokens(oracle) - tokens(subject) - tokens(attribute) - tokens(date) - LITERALS)
    return f"{base} {extra[0]}" if extra else base


def _paraphrase_from_passage(*, subject: str, attribute: str, date: str, template_id: str,
                             oracle: str) -> str:
    """The v1 failure: the question built out of the passage's own sentence."""
    sentence = oracle.strip().split("\n")[0][:160]
    return f"{render(subject=subject, attribute=attribute, date=date, template_id=template_id)} " \
           f"{sentence}"


def _value_appended(*, subject: str, attribute: str, date: str, template_id: str,
                    oracle: str) -> str:
    """A builder that helpfully includes the answer it is asking about."""
    base = render(subject=subject, attribute=attribute, date=date, template_id=template_id)
    return f"{base} (currently {oracle.strip().split(chr(10))[0][:60]})"


MUTANTS = {
    "single_oracle_token": _first_oracle_token,
    "passage_paraphrase": _paraphrase_from_passage,
    "value_appended": _value_appended,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question-set", type=Path, required=True,
                    help="v7 DEVELOPMENT question set; v8 holdout is not opened here")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    base = load(BASELINE, "w6v8_baseline")
    adapter = load(
        ROOT / "research/experiments/H1-B-REAL-REVISION-01/scripts/"
        "run_public_real_revision_holdout_v3.py", "w6v8_adapter")

    qs = json.loads(args.question_set.read_text(encoding="utf-8"))
    primary = [q for q in qs["questions"] if q["question_class"] == "revision_sensitive"]
    primary = sorted(primary, key=lambda q: q["question_id"])[: args.limit]

    # Oracle passage per item: the unit of the after revision carrying the value.
    cache: dict[str, list[str]] = {}
    items: list[dict[str, Any]] = []
    for q in primary:
        path = q["relative_after_path"]
        if path not in cache:
            text = (EXP / path).read_text(encoding="utf-8")
            revision = adapter.Revision(title=q["subject"], revid=q["after_revision_id"],
                                        parentid=0, timestamp=q["after_timestamp"],
                                        mw_sha1="", text=text)
            snapshots, _shape = adapter.section_units(revision)
            cache[path] = [s.text for s in snapshots if len(base.tokens(s.text)) >= 20]
        wanted = tokens(q["gold_current"])
        carrying = [u for u in cache[path] if wanted and wanted <= tokens(u)]
        if not carrying:
            continue
        items.append({
            "subject": q["subject"], "attribute": q["attribute"],
            "date": q["before_timestamp"][:10],
            "oracle": min(carrying, key=len),
        })

    clean = evaluate(_clean, items)
    mutant_results = {name: evaluate(fn, items) for name, fn in MUTANTS.items()}
    all_mutants_caught = all(not r["passes"] for r in mutant_results.values())
    separates = clean["passes"] and all_mutants_caught

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v8-structural-taint-gate.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md",
        "protocol_sha256": "sha256:" + hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "run_class": "DEVELOPMENT_ONLY",
        "run_class_note": (
            "measured on the v7 development question set. The v8 holdout is not opened by "
            "this script and no result here is a paper endpoint. Protocol section 7 requires "
            "the pipeline to be verified on development data before a holdout title is read."
        ),
        "development_question_set_sha256": qs.get("receipt_sha256"),
        "declared_builder_inputs": list(DECLARED_INPUTS),
        "forbidden_builder_inputs": [
            "the attribute's value", "the oracle sentence", "the surrounding passage",
            "any answer-bearing lexical context",
        ],
        "templates": TEMPLATES,
        "template_literal_tokens": sorted(LITERALS),
        "items_evaluated": len(items),
        "reference_builder": clean,
        "mutants": mutant_results,
        "all_mutants_caught": all_mutants_caught,
        "gate_is_live": separates,
        "gate_state": "PASS" if separates else ("NOT_RUN" if not all_mutants_caught else "FAIL"),
        "why_this_is_the_primary_leakage_gate": (
            "v7 measured median overlap 0.750 against a 0.50 ceiling with verbatim "
            "containment 0, and 0.667 of the shared tokens were the subject's own name. "
            "Overlap asks whether two strings resemble each other. This asks whether the "
            "builder could have seen the answer, which is what section 3 was written to ask."
        ),
        "what_this_does_not_establish": [
            "not a residual-overlap measurement -- that is the second gate and is separate",
            "not a claim that the questions are hard, only that they are not built from the "
            "passage",
            "a builder could still leak through a token that appears in neither the declared "
            "inputs nor the oracle passage; that would be a different defect and this gate "
            "does not observe it",
            "a passage token that coincides with a declared-input token -- a year that is also "
            "in the date, a word that is also in the subject -- is invisible to this gate by "
            "construction. It carries no information the template had not already licensed, "
            "but the gate cannot distinguish the two cases and does not claim to",
        ],
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"items evaluated: {len(items)}   queries per builder: {clean['queries_rendered']}")
    print(f"  reference builder    tainted={clean['tainted_queries']:<5} "
          f"{'PASS' if clean['passes'] else 'FAIL'}")
    for name, r in mutant_results.items():
        print(f"  mutant {name:<22} tainted={r['tainted_queries']:<5} "
              f"{'CAUGHT' if not r['passes'] else 'ESCAPED'}")
    print(f"gate is live: {separates}   state: {receipt['gate_state']}")
    print(f"wrote {args.output.resolve().relative_to(ROOT).as_posix()}")
    return 0 if separates else 1


if __name__ == "__main__":
    sys.exit(main())
