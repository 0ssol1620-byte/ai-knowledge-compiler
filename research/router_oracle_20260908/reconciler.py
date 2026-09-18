"""FROZEN_RECONCILER_V1 — the GT-blind rule used by the ALWAYS_ALL plan.

Written down and frozen BEFORE any oracle score was computed. It never reads
ground truth, an evaluator score, or any leaderboard rank.

    For a unit u, let C(u) be the models whose frozen manifest records
    status == SUCCESS for u and whose canonical output file exists.

    1. Normalize each candidate output:
         - casefold
         - drop the markdown syntax characters  # * _ ` ~ | > - = + [ ] ( ) $ \\
         - collapse all whitespace
         - split on whitespace into a token SET
    2. sim(a, b) = |A & B| / |A | B|   (Jaccard)
         - both empty        -> 1.0
         - exactly one empty -> 0.0
    3. agreement(m) = mean over the other candidates of sim(m, .)
         - a single candidate has agreement 1.0
    4. Select argmax agreement.
       TIE-BREAK: smallest model_key in lexicographic order. The tie-break is
       deliberately alphabetical, not quality-ordered: ordering it by any
       observed benchmark rank would leak evaluation truth into a rule that is
       supposed to be blind.
    5. C(u) empty -> UNRESOLVED. The plan does not silently fall back.

Why a medoid and not a vote: the outputs are free text, so there is no ballot
to count. The most-agreed-with output is the closest thing to a majority that
free text admits, and it is exactly the signal a production reconciler would
have without labels.

Known ceiling. ponytail: token-set Jaccard, whole page. It is order-blind and
cannot reconcile at region level. A field-level reconciler is Phase B work and
needs the region contracts from WP-R2.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

RECONCILER_ID = "FROZEN_RECONCILER_V1"

_MARKDOWN_SYNTAX = re.compile(r"[#*_`~|>\-=+\[\]()$\\]+")
_WHITESPACE = re.compile(r"\s+")

UNRESOLVED = "__UNRESOLVED__"


def normalize(text: str) -> frozenset[str]:
    """Step 1 of the frozen rule: text -> token set."""
    stripped = _MARKDOWN_SYNTAX.sub(" ", text.casefold())
    return frozenset(_WHITESPACE.sub(" ", stripped).split())


def similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Step 2: Jaccard, with the empty-set conventions spelled out."""
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union


def select(candidates: dict[str, frozenset[str]]) -> str:
    """Steps 3-5: agreement medoid with a lexicographic tie-break."""
    if not candidates:
        return UNRESOLVED
    if len(candidates) == 1:
        return next(iter(candidates))
    keys = sorted(candidates)
    best_key = UNRESOLVED
    best_score = float("-inf")
    for key in keys:
        others = [similarity(candidates[key], candidates[other]) for other in keys if other != key]
        score = sum(others) / len(others)
        if score > best_score:
            best_score = score
            best_key = key
    return best_key


def _unit_key(benchmark: str, original_source_relative_path: str) -> str:
    """Map a manifest row to the key used by that benchmark's score files."""
    path = original_source_relative_path
    if benchmark == "omnidoc":
        return path.rsplit("/", 1)[-1]  # e.g. PPT_1001115_eng_page_003.png
    if benchmark == "olmocr":
        return path.removeprefix("bench_data/pdfs/")  # e.g. arxiv_math/2502.15977_pg21.pdf
    if benchmark == "parsebench":
        return path.removeprefix("docs/").removesuffix(".pdf")  # e.g. table/1 timetable (1)_page2
    raise ValueError(f"unknown benchmark {benchmark}")


def _case_key_to_unit(root: Path, benchmark: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with (root / "source_manifest.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("benchmark") != benchmark:
                continue
            source = row.get("original_source_relative_path")
            if source:
                mapping[str(row["case_key"])] = _unit_key(benchmark, str(source))
    return mapping


def build_selection(root: Path, benchmark: str, models: list[str]) -> dict[str, Any]:
    """Run the frozen rule over every unit of one benchmark.

    Returns {unit_key: selected_model_key or UNRESOLVED} plus a candidate count.
    """
    case_to_unit = _case_key_to_unit(root, benchmark)
    per_unit: dict[str, dict[str, frozenset[str]]] = {}
    read_failures = 0
    for model in models:
        manifest = root / "frozen_outputs" / model / "manifest.jsonl"
        if not manifest.is_file():
            continue
        with manifest.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("benchmark") != benchmark or row.get("status") != "SUCCESS":
                    continue
                unit = case_to_unit.get(str(row.get("case_key")))
                if unit is None:
                    continue
                path = root / str(row["canonical_path"])
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    read_failures += 1
                    continue
                per_unit.setdefault(unit, {})[model] = normalize(text)
    selection = {unit: select(cands) for unit, cands in per_unit.items()}
    return {
        "reconciler_id": RECONCILER_ID,
        "benchmark": benchmark,
        "models": sorted(models),
        "selection": selection,
        "candidate_counts": {unit: len(c) for unit, c in per_unit.items()},
        "canonical_read_failures": read_failures,
        "unresolved": sum(1 for v in selection.values() if v == UNRESOLVED),
    }


def cached_selection(
    root: Path, benchmark: str, models: list[str], cache_dir: Path
) -> dict[str, Any]:
    """build_selection with an on-disk cache keyed by benchmark + model set."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256("|".join(sorted(models)).encode("utf-8")).hexdigest()[:12]
    cache = cache_dir / f"reconciler_selection_{benchmark}_{fingerprint}.json"
    if cache.is_file():
        payload: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
        if payload.get("models") == sorted(models):
            return payload
    payload = build_selection(root, benchmark, models)
    cache.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    )
    return payload
