"""Bind Native to historical model rule rows; descriptive spent evidence only.

No fitted policy, runtime selection, output merging, new inference or fresh holdout.
Missing model rows remain false. Unknown, duplicate or differently bound rows refuse.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def bind_rows(canonical: list[dict], rows: list[dict]) -> tuple[list[bool], int]:
    reference = {row["test_id"]: row for row in canonical}
    if len(reference) != len(canonical):
        raise ValueError("DUPLICATE_REFERENCE_RULE")
    bound = {}
    for row in rows:
        key = row["test_id"]
        if key not in reference or key in bound:
            raise ValueError("UNKNOWN_OR_DUPLICATE_RULE")
        for field in ("pdf", "page", "type", "source_jsonl"):
            if row[field] != reference[key][field]:
                raise ValueError("RULE_BINDING_MISMATCH")
        if type(row["passed"]) is not bool:
            raise ValueError("NON_BOOLEAN_RESULT")
        bound[key] = row["passed"]
    return [bound.get(row["test_id"], False) for row in canonical], len(reference) - len(bound)


def summarize(canonical: list[dict], arms: dict[str, list[bool]]) -> dict:
    counts = Counter(row["source_jsonl"] for row in canonical)
    weights = [1 / (len(counts) * counts[row["source_jsonl"]]) for row in canonical]
    pages = defaultdict(list)
    for index, row in enumerate(canonical):
        pages[(row["pdf"], row["page"])].append(index)
    fixed = {name: sum(w for w, passed in zip(weights, values, strict=True) if passed)
             for name, values in arms.items()}
    # This oracle sees hidden scores. It is exclusively diagnostic, never a router.
    model_names = [name for name in arms if name != "native"]
    if not model_names:
        raise ValueError("MODEL_BASELINES_REQUIRED")
    def oracle(names: list[str]) -> float:
        return sum(max(sum(weights[i] for i in indices if arms[name][i]) for name in names)
                   for indices in pages.values())
    peers = {}
    for name in model_names:
        values = arms[name]
        failures = sum(not value for value in values)
        recoverable = sum(n and not p for n, p in zip(arms["native"], values, strict=True))
        peers[name] = {
            "peer_failed_rules": failures,
            "native_pass_peer_fail_rules": recoverable,
            "native_pass_given_peer_fail": recoverable / failures if failures else None,
            "both_fail_rules": sum(not n and not p for n, p in
                                   zip(arms["native"], values, strict=True)),
        }
    return {
        "rules": len(canonical), "pages": len(pages), "bucket_denominators": dict(counts),
        "fixed_scores": fixed, "native_rule_complementarity": peers,
        "diagnostic_page_oracle_models_only": oracle(model_names),
        "diagnostic_page_oracle_with_native": oracle(list(arms)),
        "runtime_router_score": None, "SCLR": None, "cost": None, "p95": None,
        "confirmatory_eligible": False, "production_qualified": False,
        "scope": "Historical mixed-runtime outcomes joined by exact rule/page identity; "
                 "no policy value claim",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--arena-bind", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    scratch = Path(__file__).resolve().parents[2] / ".chatgpt2codex"
    if not output.is_relative_to(scratch) or output == scratch:
        raise ValueError("OUTPUT_MUST_BE_NEW_WORKTREE_SCRATCH")
    result = read(args.native / "RESULT.json")
    rules_path = args.native / "rule-results.jsonl"
    if result["status"] != "DEVELOPMENT_SCORED" or result["evaluator_errors"] != 0:
        raise ValueError("QUALIFIED_SCORING_REQUIRED")
    if digest(rules_path) != result["rule_results_sha256"]:
        raise ValueError("NATIVE_RULE_HASH_MISMATCH")
    canonical = [json.loads(line) for line in rules_path.read_text(encoding="utf-8").splitlines()]
    if len(canonical) != 8413:
        raise ValueError("FULL_RULE_DENOMINATOR_REQUIRED")
    arms = {"native": bind_rows(canonical, canonical)[0]}
    binding = read(args.arena_bind)
    if binding["campaign_id"] != "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1":
        raise ValueError("WRONG_SPENT_CAMPAIGN")
    score_freeze = read(args.native / "FREEZE.json")
    capture_freeze = args.capture / "FREEZE.json"
    if score_freeze["capture_sha256"] != digest(capture_freeze):
        raise ValueError("CAPTURE_FREEZE_BINDING_MISMATCH")
    manifest_hash = binding["required_artifacts"]["source_manifest.jsonl"]["sha256"]
    if read(capture_freeze)["source_manifest_sha256"] != manifest_hash:
        raise ValueError("SOURCE_CORPUS_BINDING_MISMATCH")
    arena = Path(binding["arena_root"]).resolve(strict=True)
    inputs = {"arena_bind": digest(args.arena_bind), "native_rules": digest(rules_path),
              "native_freeze": digest(args.native / "FREEZE.json"), "code": digest(Path(__file__))}
    missing = {}
    excluded = binding["founder_excluded_models"]
    for name, model in sorted(binding["models"].items()):
        if name in excluded:
            continue
        benchmark = model["benchmarks"]["olmocr"]
        artifact = benchmark.get("artifacts", {}).get("official_result")
        if not benchmark["available"] or not artifact:
            arms[name] = [False] * len(canonical)
            missing[name] = len(canonical)
            continue
        path = (arena / artifact["relative_path"]).resolve(strict=True)
        if not path.is_relative_to(arena) or digest(path) != artifact["sha256"]:
            raise ValueError("MODEL_ARTIFACT_BINDING_MISMATCH")
        raw = read(path)
        if raw["candidate"] != name:
            raise ValueError("MODEL_ID_MISMATCH")
        arms[name], missing[name] = bind_rows(canonical, raw["tests"])
        inputs[name] = digest(path)
    summary = summarize(canonical, arms)
    summary["missing_rule_rows_retained_as_false"] = missing
    summary["founder_excluded_models"] = excluded
    output.mkdir(parents=True, exist_ok=False)
    for filename, value in (("BIND.json", inputs), ("RESULT.json", summary)):
        with (output / filename).open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
