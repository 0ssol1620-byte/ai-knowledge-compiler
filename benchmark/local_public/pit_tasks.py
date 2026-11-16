"""SEC temporal tasks on the point-in-time corpus (LPC design 4, Amendment 4, WO-LPC-6B).

Every task targets the FIRST-REPORTING accession of its key (`rows_index.jsonl`), so a later
comparative row is never the target. There is no SEC `late_recorded` stratum: SEC rows have
`recorded_at == available_at`, so it would equal `backdated` cut A. Cut B of `backdated` carries
`known_at = accepted_at(R) + 1 s` besides `valid_at`, so later rows of the same key are not
counted against precision. Queries are verbatim row-text tokens without the value. ALFRED rows
and tasks (WO-LPC-7) enter through the `alfred` argument of `generate`, and are counted as
skipped when absent. Fewer than FLOOR tasks -> exit 1 with the shortfall; never padded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from benchmark.retrieval_baselines.metrics import TaskError, parse_moment, parse_task

GENERATOR = "benchmark.local_public.pit_tasks/1"
FLOOR = 200
STRATA = ("backdated", "added_later", "modified")
# row text: "{name}: {label}: {value} {uom}, {period text}" (pit_rows.filing_rows)
_TEXT = re.compile(r"^(.*): (-?[0-9][0-9.eE+-]*) (\S+), (.+)$", re.S)
STATEMENTS = (
    "Pre-training exposure cannot be controlled: these are large public companies' public XBRL "
    "values, and a model may have memorised them. A holdout here is hidden from tuning, not "
    "from pre-training.",
    "Selection condition: SEC rows are the presented non-dimensional FSDS facts of the chosen "
    "filings; validity dates exist for inline-XBRL filings only. Scores hold for that "
    "population only.",
    "No arm comparison from this stratum: no result here compares a text-layer arm with a "
    "vision arm.",
    "Not covered: the filer's own PDF, images, tables that run across pages, MD&A and "
    "narrative accuracy, dimensional and segment values, scans of any kind.",
    "Gold after a later restatement is not generated: the harness has no transaction-time "
    "supersession for rows.",
)


class PitTaskError(Exception):
    pass


def _iso(m: datetime) -> str:
    return m.isoformat()


def _split(text: str) -> tuple[str, str] | None:
    """(query without the value, value) or None."""
    m = _TEXT.match(text)
    return (f"{m[1]}: {m[4]}", m[2]) if m else None


def _recorded(r: dict[str, Any]) -> datetime:
    return parse_moment(r["metadata"]["recorded_at"], field="recorded_at")


def generate(
    corpus: list[dict[str, Any]],
    index: list[dict[str, Any]],
    *,
    strata: Iterable[str] = STRATA,
    seed: int = 0,
    max_per_stratum: int | None = None,
    alfred: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    strata = tuple(strata)
    bad = set(strata) - set(STRATA)
    if bad:
        raise PitTaskError(f"SEC strata {sorted(bad)} are not generated (no SEC late_recorded)")
    idx = {i["logical_id"]: i for i in index}
    if len(idx) != len(index) or {r["logical_id"] for r in corpus} != set(idx):
        raise PitTaskError("corpus.jsonl and rows_index.jsonl do not describe the same rows")
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    filings: dict[str, dict[str, datetime]] = defaultdict(dict)  # cik -> adsh -> recorded_at
    for r in corpus:
        k = idx[r["logical_id"]]["fsds_key"]
        groups[tuple(k[f] for f in ("cik", "tag", "ddate", "qtrs", "uom"))].append(r)
        filings[k["cik"]][r["source_id"]] = _recorded(r)
    skipped: Counter[str] = Counter()
    cands: dict[str, list[dict[str, Any]]] = {s: [] for s in strata}

    def task(stratum: str, variant: str, r: dict[str, Any], q: str, cut: dict[str, str]) -> None:
        gold = [r["evidence_id"]] if stratum == "modified" or variant == "B" else []
        tid = (
            f"{stratum}-{variant}-"
            + hashlib.sha256(f"{r['logical_id']}{q}{sorted(cut.items())}".encode()).hexdigest()[:12]
        )
        cands[stratum].append(
            {
                "task_id": tid, "kind": "temporal", "stratum": stratum, "variant": variant,
                "tenant": r["tenant"], "query": q, "cut": cut, "gold_evidence_ids": gold,
                "answerable": bool(gold), "provenance": "generated", "generator": GENERATOR,
                "seed": seed,
            }
        )  # fmt: skip

    for key, rows in sorted(groups.items()):
        fr = idx[rows[0]["logical_id"]]["first_reported_by"]
        if fr is None:
            skipped["first_reporting_unresolved"] += 1
            continue
        first = [r for r in rows if r["source_id"] == fr]
        if len(first) != 1:
            skipped["first_reporting_row_not_unique"] += 1
            continue
        (r,) = first
        parts = _split(r["text"])
        if parts is None:
            skipped["row_text_unparsed"] += 1
            continue
        q, value = parts
        md = r["metadata"]
        t_a = _recorded(r)
        if "backdated" in strata:
            task("backdated", "A", r, q, {"known_at": _iso(t_a - timedelta(days=1))})
            if md["valid_to"] is None:
                skipped["backdated_cut_b_no_validity"] += 1
            else:
                end = parse_moment(md["valid_to"], field="valid_to") - timedelta(days=1)
                known = _iso(t_a + timedelta(seconds=1))
                task("backdated", "B", r, q, {"valid_at": _iso(end), "known_at": known})
        if "added_later" in strata:
            prev = [t for t in filings[key[0]].values() if t < t_a]
            if not prev:
                skipped["added_later_no_previous_filing"] += 1
            elif t_a - max(prev) < timedelta(seconds=1):
                skipped["added_later_window_under_1s"] += 1
            else:
                task("added_later", "A", r, q, {"known_at": _iso(t_a - timedelta(seconds=1))})
        if "modified" in strata:
            changed = [
                x
                for x in rows
                if x["source_id"] != fr
                and _recorded(x) > t_a
                and (_split(x["text"]) or ("", ""))[1] not in ("", value)
            ]
            if changed:
                task("modified", "A", r, q, {"known_at": _iso(t_a + timedelta(seconds=1))})
            else:
                skipped["modified_no_later_value_change"] += 1
    tasks: list[dict[str, Any]] = []
    for s in strata:
        pool = sorted(
            cands[s], key=lambda t: hashlib.sha256(f"{seed}:{t['task_id']}".encode()).hexdigest()
        )
        tasks += pool[:max_per_stratum] if max_per_stratum is not None else pool
    out_corpus = list(corpus)
    if alfred is None:
        skipped["alfred_input_absent"] = 1
    else:
        out_corpus += alfred[0]
        tasks += alfred[1]
    ids = [t["task_id"] for t in tasks]
    if len(set(ids)) != len(ids):
        raise PitTaskError("duplicate task ids")
    try:
        for t in tasks:
            parse_task(t)
    except TaskError as exc:
        raise PitTaskError(f"task violates the shared contract: {exc}") from exc
    tasks.sort(key=lambda t: t["task_id"])
    return {"tasks": tasks, "corpus": out_corpus, "skipped": dict(skipped)}


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()


def write(
    result: dict[str, Any], out: Path, basis: str, corpus_sha256: str, index_sha256: str
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    raw = _jsonl(result["tasks"])
    (out / "tasks.jsonl").write_bytes(raw)
    counts = Counter(t["stratum"] for t in result["tasks"])
    summary = {
        "schema": "tavonel.lpc.pit_tasks.manifest.v1",
        "generator": GENERATOR,
        "provenance": "generated",
        "valid_time_basis": basis,
        "statements": list(STATEMENTS),
        "corpus_sha256": corpus_sha256,
        "rows_index_sha256": index_sha256,
        "tasks_sha256": hashlib.sha256(raw).hexdigest(),
        "tasks": len(result["tasks"]),
        "counts_by_stratum": dict(sorted(counts.items())),
        "floor": FLOOR,
        "shortfall": max(0, FLOOR - len(result["tasks"])),
        "skipped": result["skipped"],
    }
    (out / "tasks_manifest.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def _lines(raw: bytes) -> list[dict[str, Any]]:
    return [json.loads(x) for x in raw.decode("utf-8").splitlines() if x]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pit_tasks")
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--rows-dir", type=Path, required=True, help="pit_rows output directory")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-per-stratum", type=int)
    ap.add_argument("--strata", nargs="+", default=list(STRATA))
    a = ap.parse_args(argv)
    try:
        c_raw = (a.rows_dir / "corpus.jsonl").read_bytes()
        i_raw = (a.rows_dir / "rows_index.jsonl").read_bytes()
        meta = json.loads((a.rows_dir / "pit_rows_meta.json").read_text("utf-8"))
        result = generate(
            _lines(c_raw),
            _lines(i_raw),
            strata=a.strata,
            seed=a.seed,
            max_per_stratum=a.max_per_stratum,
        )
        summary = write(
            result,
            a.out,
            meta["valid_time_basis"],
            hashlib.sha256(c_raw).hexdigest(),
            hashlib.sha256(i_raw).hexdigest(),
        )
    except (PitTaskError, OSError, KeyError, ValueError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: summary[k] for k in ("tasks", "counts_by_stratum", "shortfall")}))
    return 1 if summary["shortfall"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
