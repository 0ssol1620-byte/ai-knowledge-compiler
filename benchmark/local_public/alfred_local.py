"""ALFRED local reader, D14 rows and temporal tasks (LPC design 4, WO-LPC-7).

Reads a local vintage CSV (series_id, observed_at, available_at, vintage_date, realtime_end, value,
source_method) for the six allowed series only, behind the per-series rights gate: a series that
is not allowed, or whose `model_processing` or `derive` right is not verified, is refused BEFORE
the file is opened. `alfred_vintage` rows map through `VintageObservation`
(`available_on = vintage_date`, `recorded_at = available_upper_bound(vintage_date)`); the lagged
rows get `recorded_at = available_at = None` and are never known-at facts. The CSV states no
unit, frequency or supersession: `unit = "unstated"`, `frequency = None`, `superseded_on = None`,
and every row is held `vintage_chain_unverified` (`realtime_end == vintage_date`, so chain
completeness cannot be proven locally). Without a `--vintage-chain-verified` file that matches
the CSV's vintage set, the as-of `modified` stratum is counted as skipped, never generated.
Gold is relative to the corpus built here, not to the publisher's full history.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from akc_source_adapters.public_data import rights
from akc_source_adapters.public_data.sources import DEFAULT_RIGHTS, PUBLIC_SOURCES
from akc_source_adapters.public_data.vintage import VintageObservation, available_upper_bound

from benchmark.local_public.sources import ALLOWED_ALFRED_SERIES
from benchmark.retrieval_baselines.metrics import TaskError, parse_task

GENERATOR = "benchmark.local_public.alfred_local/1"
TENANT = "lpc-alfred"
CHAIN_SCHEMA = "tavonel.lpc.alfred.vintage_chain_verified.v1"
VINTAGE, LAGGED = "alfred_vintage", "fred_market_observed_release_lagged"
STRATA = ("late_recorded", "modified", "unknown_availability")
_COLUMNS = {
    "series_id", "observed_at", "available_at", "vintage_date", "realtime_end", "value",
    "source_method",
}  # fmt: skip
_MISSING = (".", "")


class AlfredError(Exception):
    pass


def _check_series(series: Iterable[str]) -> tuple[str, ...]:
    out = tuple(series)
    bad = sorted(set(out) - set(ALLOWED_ALFRED_SERIES))
    if bad or not out:
        raise AlfredError(f"series not allowed (rights or terms): {bad or 'none given'}")
    return out


def read_local_vintages(
    path: Path,
    series: Iterable[str],
    register: Iterable[rights.RightsRecord],
    today: date,
) -> tuple[list[VintageObservation], Counter[str]]:
    """Observations of the given series plus counts of rows not mapped.

    Refuses (AlfredError / RightsDenied) before opening `path`."""
    wanted = _check_series(series)
    register = tuple(register)
    records = {}
    for s in wanted:
        for action in ("model_processing", "derive"):
            records[s] = rights.require(PUBLIC_SOURCES["alfred"], s, action, register, today=today)
    raw = path.read_bytes()
    sha = "sha256:" + hashlib.sha256(raw).hexdigest()
    text = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8")
    reader = csv.DictReader(text.splitlines())
    if not set(reader.fieldnames or ()) >= _COLUMNS:
        raise AlfredError(f"CSV lacks columns {sorted(_COLUMNS - set(reader.fieldnames or ()))}")
    uri = PUBLIC_SOURCES["alfred"].docs_urls[-1]
    out: list[VintageObservation] = []
    counts: Counter[str] = Counter()
    for r in reader:
        sid = r["series_id"]
        if sid not in records:
            counts["series_not_selected"] += 1
            continue
        method = r["source_method"]
        if method not in (VINTAGE, LAGGED):
            raise AlfredError(f"unknown source_method {method!r}")
        if r["value"].strip() in _MISSING:
            counts["missing_value"] += 1
            continue
        try:
            observed, vdate = (
                date.fromisoformat(r["observed_at"]),
                date.fromisoformat(r["vintage_date"]),
            )
        except ValueError as exc:
            raise AlfredError(f"{sid}: bad date in row {r}") from exc
        lagged = method == LAGGED
        out.append(
            VintageObservation(
                source_id="alfred",
                series_id=sid,
                period_start=observed,
                period_end=None,
                value=r["value"],
                unit="unstated",
                frequency=None,
                seasonal_adjustment=None,
                measure=sid,
                geography_id=None,
                geography_level=None,
                geography_vintage=None,
                vintage_id=f"{'lagged-' if lagged else ''}{vdate.isoformat()}",
                available_on=None if lagged else vdate,
                available_precision=None if lagged else "day",
                superseded_on=None,
                source_uri=uri,
                raw_sha256=sha,
                rights_id=records[sid].rights_id,
            )
        )
    return out, counts


def _midnight(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat()


def corpus_row(o: VintageObservation) -> dict[str, Any]:
    """D14 row. A lagged observation (no available_on) has recorded_at = available_at = None."""
    stamp = None if o.available_on is None else available_upper_bound(o.available_on).isoformat()
    lid = f"{TENANT}/{o.series_id}/{o.period_start.isoformat()}@{o.vintage_id}"
    return {
        "tenant": TENANT,
        "logical_id": lid,
        "source_id": f"alfred:{o.series_id}",
        "source_version_id": o.vintage_id,
        "evidence_id": f"ev:{lid}",
        "text": f"{o.series_id} {o.period_start}: {o.value} {o.unit}, vintage {o.vintage_id}.",
        "authority": "official",
        "metadata": {
            "valid_from": _midnight(o.period_start),
            "valid_to": None,
            "recorded_at": stamp,
            "available_at": stamp,
        },
    }


def load_chain_verified(path: Path, csv_sha256: str) -> dict[str, list[str]]:
    """{series: vintage dates} of a `--vintage-chain-verified` file; refuses another CSV's."""
    doc = json.loads(path.read_text("utf-8"))
    if doc.get("schema") != CHAIN_SCHEMA or doc.get("csv_sha256") != csv_sha256:
        raise AlfredError("vintage-chain file is not for this CSV")
    return {s: sorted(v) for s, v in doc["series"].items()}


def generate(
    observations: list[VintageObservation],
    *,
    chain_verified: dict[str, list[str]] | None = None,
    seed: int = 0,
    max_per_stratum: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """(corpus rows, tasks, skipped counts); the first two are what `pit_tasks.generate` takes."""
    rows = [corpus_row(o) for o in observations]
    if len({r["logical_id"] for r in rows}) != len(rows):
        raise AlfredError("duplicate logical ids: a (series, observed_at, vintage) repeats")
    skipped: Counter[str] = Counter()
    by_key: dict[tuple[str, date], list[tuple[VintageObservation, dict[str, Any]]]] = defaultdict(
        list
    )
    vintage_dates: dict[str, set[str]] = defaultdict(set)
    for o, r in zip(observations, rows, strict=True):
        by_key[(o.series_id, o.period_start)].append((o, r))
        if o.available_on is not None:
            vintage_dates[o.series_id].add(o.available_on.isoformat())
    verified = {
        s
        for s, d in (chain_verified or {}).items()
        if s in vintage_dates and set(d) == vintage_dates[s]
    }
    held = sum(
        1 for o in observations if o.available_on is not None and o.series_id not in verified
    )
    if held:
        skipped["held_vintage_chain_unverified"] = held
    cands: dict[str, list[dict[str, Any]]] = {s: [] for s in STRATA}

    def task(
        stratum: str, o: VintageObservation, cut: dict[str, str], gold: list[str], tag: str
    ) -> None:
        q = f"{o.series_id} {o.period_start.isoformat()}"
        tid = (
            f"{stratum}-"
            + hashlib.sha256(f"{q}{tag}{sorted(cut.items())}".encode()).hexdigest()[:12]
        )
        cands[stratum].append(
            {
                "task_id": tid, "kind": "temporal", "stratum": stratum, "tenant": TENANT,
                "query": q, "cut": cut, "gold_evidence_ids": gold, "answerable": bool(gold),
                "provenance": "generated", "generator": GENERATOR, "seed": seed,
            }
        )  # fmt: skip

    for (_, _), group in sorted(by_key.items()):
        dated = sorted(
            ((o, r) for o, r in group if o.available_on is not None),
            key=lambda x: (x[0].available_on or date.min, x[0].vintage_id),
        )
        by_day: dict[date, list[tuple[VintageObservation, dict[str, Any]]]] = defaultdict(list)
        for o, r in dated:
            assert o.available_on is not None
            by_day[o.available_on].append((o, r))
        days = sorted(by_day)
        if dated:
            first, r0 = by_day[days[0]][0]
            t0 = datetime.fromisoformat(r0["metadata"]["recorded_at"])
            task(
                "late_recorded",
                first,
                {"known_at": (t0 - timedelta(seconds=1)).isoformat()},
                [],
                "",
            )
        if len(days) > 1:
            if any(len({x[0].value for x in by_day[d]}) > 1 for d in days):
                skipped["modified_ambiguous_vintage"] += 1
            else:
                i = next(
                    (
                        i
                        for i in range(len(days) - 1)
                        if by_day[days[i]][0][0].value != by_day[days[i + 1]][0][0].value
                    ),
                    None,
                )
                if i is None:
                    skipped["modified_no_value_change"] += 1
                elif group[0][0].series_id not in verified:
                    skipped["modified_chain_unverified"] += 1
                else:
                    o, r = by_day[days[i]][0]
                    known = available_upper_bound(days[i]).isoformat()
                    task("modified", o, {"known_at": known}, [r["evidence_id"]], "")
        for o, _r in group:
            if o.available_on is not None:
                continue
            cut_at = available_upper_bound(date.fromisoformat(o.vintage_id.removeprefix("lagged-")))
            if any(
                datetime.fromisoformat(dr["metadata"]["recorded_at"]) <= cut_at for _, dr in dated
            ):
                skipped["unknown_availability_key_has_dated_row"] += 1
            else:
                task(
                    "unknown_availability",
                    o,
                    {"available_at": cut_at.isoformat()},
                    [],
                    o.vintage_id,
                )
    tasks: list[dict[str, Any]] = []
    for s in STRATA:
        pool = sorted(
            cands[s], key=lambda t: hashlib.sha256(f"{seed}:{t['task_id']}".encode()).hexdigest()
        )
        tasks += pool[:max_per_stratum] if max_per_stratum is not None else pool
    ids = [t["task_id"] for t in tasks]
    if len(set(ids)) != len(ids):
        raise AlfredError("duplicate task ids")
    try:
        for t in tasks:
            parse_task(t)
    except TaskError as exc:
        raise AlfredError(f"task violates the shared contract: {exc}") from exc
    return rows, tasks, dict(skipped)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--series", nargs="+", default=list(ALLOWED_ALFRED_SERIES))
    p.add_argument("--vintage-chain-verified", type=Path)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-per-stratum", type=int)
    a = p.parse_args(argv)
    try:
        # ponytail: DEFAULT_RIGHTS refuses until WO-D21-5 supplies verified per-series records.
        obs, counts = read_local_vintages(a.csv, a.series, DEFAULT_RIGHTS, datetime.now(UTC).date())
        sha = hashlib.sha256(a.csv.read_bytes()).hexdigest()
        chain = (
            load_chain_verified(a.vintage_chain_verified, sha) if a.vintage_chain_verified else None
        )
        rows, tasks, skipped = generate(
            obs, chain_verified=chain, seed=a.seed, max_per_stratum=a.max_per_stratum
        )
    except (AlfredError, rights.RightsDenied) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    for name, data in (("corpus_alfred.jsonl", rows), ("tasks_alfred.jsonl", tasks)):
        (a.out / name).write_text(
            "".join(json.dumps(x, sort_keys=True) + "\n" for x in data), encoding="utf-8"
        )
    print(json.dumps({"rows": len(rows), "tasks": len(tasks), "skipped": {**counts, **skipped}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
