#!/usr/bin/env python3
"""Pin the two instrumentation scripts that were written after the holdout opened.

`verify_holdout_corpus_v8.py` and `seal_w6_endpoint_v8.py` did not exist when the
config freeze was written. That is a fact about them and it is not hidden: they
are **post-open** tooling. The config freeze is not reopened to absorb them --- a
freeze that is rewritten whenever something new needs to be inside it is not a
freeze --- so they are pinned here instead, in a receipt that is itself immutable.

What makes the classification defensible is not that the tools are harmless in
principle, but that they were written **before any holdout observation existed**:

- the holdout acquisition was still in flight;
- `corpus-v8-holdout` contained zero directories and zero files;
- no holdout question, answer, score or arm result had been produced or seen;
- implementation and positive controls used v7 **development** data only;
- the criteria they check --- acquisition integrity and endpoint sealing --- were
  already required by the protocol before the holdout was opened.

Neither script can move a number. Neither generates a question, selects a cohort,
holds a threshold, retrieves, decodes, scores or computes a statistic, and the
receipt records that as a checked property rather than a promise: the forbidden
identifiers are searched for in the pinned bytes.

Classification: `POST_OPEN_PRE_OBSERVATION_NON_ANALYTIC_INSTRUMENTATION`.

Re-running verifies instead of overwriting. After this receipt exists, the two
pinned scripts are not to be modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
RECEIPTS = EXP / "receipts"
CORPUS = EXP / "corpus-v8-holdout"
OUTPUT = RECEIPTS / "v8-post-open-instrumentation.json"

PINNED = ("verify_holdout_corpus_v8.py", "seal_w6_endpoint_v8.py")

#: Searched for in the pinned bytes. Any hit means the tool can reach into the
#: part of the pipeline that decides a number, and the receipt refuses.
FORBIDDEN_INFLUENCE = (
    "score_answer", "paired_comparison", "holm", "mcnemar",
    "BM25", "bm25", "rm3", "RM3", "top_k", "TOP_K",
    "temperature", "max_tokens", "enable_thinking",
    "build_question_set", "primary_attrs", "admission",
    "threshold", "CONTEXT_BUDGET",
)


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def corpus_observation() -> dict[str, Any]:
    directories = [p for p in CORPUS.iterdir() if p.is_dir()] if CORPUS.exists() else []
    files = [p for p in CORPUS.rglob("*") if p.is_file()] if CORPUS.exists() else []
    return {"path": "corpus-v8-holdout", "exists": CORPUS.exists(),
            "directories": len(directories), "files": len(files)}


def code_identifiers(path: Path) -> set[str]:
    """Every NAME token in the file, with comments and string literals excluded.

    The scan is over **identifiers, not prose**. A docstring that says "this holds
    no threshold" is the opposite of a violation, and a raw substring search over
    the whole file cannot tell the two apart --- it flagged exactly that sentence
    on the first run. What matters is whether the code can reach the scoring,
    retrieval or decoding surface, and that shows up as a name it calls or a
    constant it reads.
    """
    import io
    import tokenize
    names: set[str] = set()
    with path.open("rb") as handle:
        for token in tokenize.tokenize(io.BufferedReader(handle).readline):
            if token.type == tokenize.NAME:
                names.add(token.string)
    return names


def influence_scan() -> dict[str, Any]:
    """Case-insensitive, because the analytic surface is not consistently cased.

    The first version of this scan matched case-sensitively and came back clean on
    `vllm_model_v8.py`, which holds the decoding contract as `TEMPERATURE` and
    `MAX_TOKENS`. A tool that imported those constants would have passed. Matching
    is folded to lower case so that a name is caught however it is spelled.
    """
    hits: dict[str, list[str]] = {}
    forbidden = {token.lower() for token in FORBIDDEN_INFLUENCE}
    for name in PINNED:
        identifiers = {token.lower() for token in code_identifiers(HERE / name)}
        found = sorted(forbidden & identifiers)
        if found:
            hits[name] = found
    return {"forbidden_identifiers_searched": sorted(forbidden),
            "scan_domain": "python NAME tokens only, case-insensitive; comments and "
                           "string literals excluded",
            "hits": hits, "clean": not hits}


def build(*, acquisition_started_utc: str,
          supersedes: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = [n for n in PINNED if not (HERE / n).exists()]
    if missing:
        raise SystemExit("cannot pin: missing " + ", ".join(missing))

    scan = influence_scan()
    if not scan["clean"]:
        raise SystemExit(
            "refusing to classify these as non-analytic instrumentation: "
            f"{scan['hits']}. A tool that names the scoring, retrieval or decoding "
            "surface can influence the endpoint and does not belong in this category.")

    corpus = corpus_observation()
    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v8-post-open-instrumentation.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "classification": "POST_OPEN_PRE_OBSERVATION_NON_ANALYTIC_INSTRUMENTATION",
        "disclosure": (
            "both scripts were written after the v8 holdout was opened. This is stated "
            "rather than obscured. They were written before any holdout observation "
            "existed, and they are pinned here instead of inside the config freeze, "
            "which is not reopened."
        ),
        "config_freeze_not_reopened": {
            "config_freeze_sha256": file_sha256(RECEIPTS / "v8-config-freeze.json"),
            "why": "a freeze that is rewritten to absorb whatever is needed next is not a "
                   "freeze. These tools are pinned in a separate immutable receipt.",
        },
        "holdout_state_at_creation": {
            "acquisition_started_utc": acquisition_started_utc,
            "acquisition_in_flight": not (
                RECEIPTS / "acquisition-v8-holdout-completion.json").exists(),
            "holdout_corpus": corpus,
            "holdout_questions_observed": 0,
            "holdout_answers_observed": 0,
            "holdout_scores_observed": 0,
            "holdout_arm_results_observed": 0,
            "implementation_and_controls_used": "v7 development data only",
        },
        "pinned_sources": {name: file_sha256(HERE / name) for name in PINNED},
        "purpose": {
            "verify_holdout_corpus_v8.py":
                "nine fail-closed acquisition integrity checks between a finished "
                "acquisition and the question set",
            "seal_w6_endpoint_v8.py":
                "one immutable index binding the endpoint to the freeze, attestation, "
                "corpus root hash, gates, sources, timestamps and cost",
        },
        "criteria_predate_the_holdout_open": (
            "acquisition integrity and endpoint sealing were required by the confirmatory "
            "protocol before the holdout was opened. These scripts implement criteria that "
            "already existed; they do not introduce new ones."
        ),
        "forbidden_influence": {
            "question_selection": False, "cohort_selection": False, "thresholds": False,
            "retrieval": False, "arm_behaviour": False, "scoring": False,
            "statistics": False,
            "verified_by": "identifier scan over the pinned bytes",
            "scan": scan,
        },
        "modification_rule": (
            "after this receipt exists the two pinned scripts are not modified. A change "
            "to either is a drift finding, not an edit."
        ),
        "external_gpu_cost_usd": 0.0,
    }
    if supersedes is not None:
        receipt["supersedes"] = supersedes
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def verify(existing: dict[str, Any]) -> int:
    body = {k: v for k, v in existing.items() if k != "receipt_sha256"}
    intact = canonical_sha256(body) == existing.get("receipt_sha256")
    drift = [name for name, digest in (existing.get("pinned_sources") or {}).items()
             if not (HERE / name).exists() or file_sha256(HERE / name) != digest]
    print(f"instrumentation receipt from {existing.get('generated_at')}")
    print(f"classification: {existing.get('classification')}")
    print(f"self-hash intact: {intact}   pinned-source drift: {len(drift)}")
    for name in drift:
        print(f"  DRIFT {name}")
    print("INSTRUMENTATION PINNED" if intact and not drift else "INSTRUMENTATION BROKEN")
    return 0 if intact and not drift else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-started-utc", required=False,
                        help="ISO-8601 UTC start time of the acquisition process")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--supersede-reason",
                        help="replace an existing receipt, preserving it under a "
                             "timestamped name and recording this reason. Without it an "
                             "existing receipt is verified, never rewritten.")
    args = parser.parse_args()

    supersedes: dict[str, Any] | None = None
    if args.output.exists():
        if not args.supersede_reason:
            return verify(json.loads(args.output.read_text(encoding="utf-8")))
        # Superseding is never a silent overwrite. The prior receipt is moved
        # aside under a timestamped name and named here by digest, so the record
        # shows that it existed and why it was replaced. Anything else would make
        # "immutable" mean "immutable until inconvenient".
        prior = json.loads(args.output.read_text(encoding="utf-8"))
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archived = args.output.with_name(
            f"{args.output.stem}-superseded-{stamp}{args.output.suffix}")
        supersedes = {
            # `receipt` is the key the repository's retraction contract reads
            # (tests/unit/test_superseded_receipt_contract.py). A different key
            # here would make the retraction unverifiable by that guard.
            "receipt": archived.name,
            "sha256": file_sha256(args.output),
            "generated_at": prior.get("generated_at"),
            "reason": args.supersede_reason,
        }
        args.output.rename(archived)
        print(f"prior receipt preserved as {archived.name}")

    if not args.acquisition_started_utc:
        raise SystemExit("--acquisition-started-utc is required to write this receipt")

    receipt = build(acquisition_started_utc=args.acquisition_started_utc,
                    supersedes=supersedes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"classification: {receipt['classification']}")
    print(f"holdout corpus at creation: {receipt['holdout_state_at_creation']['holdout_corpus']}")
    print(f"pinned: {list(receipt['pinned_sources'])}")
    print(f"influence scan clean: {receipt['forbidden_influence']['scan']['clean']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
