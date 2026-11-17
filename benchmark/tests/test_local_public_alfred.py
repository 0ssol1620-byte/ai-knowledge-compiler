"""WO-LPC-7: ALFRED local reader and tasks. Synthetic CSVs built here; no other file is opened."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from akc_source_adapters.public_data.rights import RightsDenied, RightsRecord
from akc_source_adapters.public_data.sources import DEFAULT_RIGHTS, REVIEWED_RIGHTS
from akc_source_adapters.public_data.vintage import VintageObservation

from benchmark.local_public import alfred_local as al
from benchmark.local_public import pit_tasks as pt
from benchmark.local_public import sources as S
from benchmark.local_public import terms
from benchmark.retrieval_baselines.metrics import parse_moment, parse_task, violates_cut

TODAY = date(2026, 11, 17)
HEAD = "series_id,observed_at,available_at,vintage_date,realtime_end,value,source_method\n"


def allow(series: str) -> RightsRecord:
    return RightsRecord(
        rights_id=f"alfred:{series}",
        source_id="alfred",
        series_id=series,
        terms_url="https://fred.stlouisfed.org/docs/api/terms_of_use.html",
        terms_snapshot_sha256="0" * 64,
        verified_on=date(2026, 11, 1),
        reviewer="t",
        expires_on=None,
        attribution=None,
        permissions={"model_processing": "allow", "derive": "allow"},
    )


REGISTER = [allow(s) for s in S.DENIED_ALFRED_SERIES]
LINES = [
    "CPIAUCSL,2024-01-01,2024-02-01,2024-02-01,2024-02-01,300.1,alfred_vintage",
    "CPIAUCSL,2024-01-01,2024-03-01,2024-03-01,2024-03-01,300.5,alfred_vintage",
    "CPIAUCSL,2024-02-01,2024-03-01,2024-03-01,2024-03-01,301.0,alfred_vintage",
    "DFF,2024-01-02,2024-01-03,2024-01-03,2024-01-03,5.33,alfred_vintage",
    "DFF,2024-01-02,2024-01-03,2024-01-03,2024-01-03,5.33,fred_market_observed_release_lagged",
    "DFF,2024-01-05,2024-01-06,2024-01-06,2024-01-06,5.33,fred_market_observed_release_lagged",
    "VIXCLS,2024-01-02,2024-01-03,2024-01-03,2024-01-03,13.0,alfred_vintage",
    "DGS10,2024-01-02,2024-01-03,2024-01-03,2024-01-03,.,alfred_vintage",
]


def write(tmp: Path, lines: list[str] = LINES) -> Path:
    p = tmp / "v.csv.gz"
    p.write_bytes(gzip.compress((HEAD + "\n".join(lines) + "\n").encode()))
    return p


def built(
    tmp: Path, chain: dict[str, list[str]] | None = None
) -> tuple[
    list[VintageObservation],
    Counter[str],
    tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]],
]:
    obs, counts = al.read_local_vintages(write(tmp), S.DENIED_ALFRED_SERIES, REGISTER, TODAY)
    return obs, counts, al.generate(obs, chain_verified=chain)


def test_excluded_series_refused_before_reading(tmp_path: Path) -> None:
    with pytest.raises(al.AlfredError):
        al.read_local_vintages(tmp_path / "missing.csv", ["VIXCLS"], REGISTER, TODAY)


def test_default_rights_denied(tmp_path: Path) -> None:
    with pytest.raises(RightsDenied):
        al.read_local_vintages(tmp_path / "missing.csv", ["CPIAUCSL"], DEFAULT_RIGHTS, TODAY)
    m = manifest_for(tmp_path, write(tmp_path))
    assert al.main(["--manifest", str(m), "--out", str(tmp_path / "o")]) == 2


def manifest_for(tmp: Path, csv_path: Path) -> Path:
    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    e = {"name": "alfred_vintages", "role": "vintages", "path": csv_path.as_posix(),
         "bytes": csv_path.stat().st_size, "sha256": sha}  # fmt: skip
    m = {"schema": S.SCHEMA, "entries": [e], "excluded": []}
    m["manifest_sha256"] = S._digest(m)
    p = tmp / "m.json"
    p.write_text(json.dumps(m))
    return p


def test_changed_csv_is_hash_mismatch_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(al, "DEFAULT_RIGHTS", REGISTER)  # rights pass, so the hash check is reached
    csv_path = write(tmp_path)
    m = manifest_for(tmp_path, csv_path)
    write(
        tmp_path,
        [*LINES, "CPIAUCSL,2024-03-01,2024-04-01,2024-04-01,2024-04-01,9.9,alfred_vintage"],
    )
    out = tmp_path / "o"
    with pytest.raises(S.HashMismatch):
        al.main(["--manifest", str(m), "--out", str(out)])
    assert not out.exists()


def test_receipt_carries_manifest_sha_and_output_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = manifest_for(tmp_path, write(tmp_path))
    monkeypatch.setattr(al, "DEFAULT_RIGHTS", REGISTER)
    out = tmp_path / "o"
    monkeypatch.setattr(S, "_inside_git_tree", lambda _p: False)
    assert al.main(["--manifest", str(m), "--out", str(out)]) == 0
    rec = json.loads((out / "receipt.json").read_text())
    assert rec["lpc_manifest_sha256"] == json.loads(m.read_text())["manifest_sha256"]
    assert [i["name"] for i in rec["inputs_consumed"]] == ["alfred_vintages"]
    assert {Path(o["path"]).name for o in rec["outputs"]} == {
        "corpus_alfred.jsonl",
        "tasks_alfred.jsonl",
    }
    with pytest.raises(FileExistsError):  # never overwritten
        al.main(["--manifest", str(m), "--out", str(out)])


def test_mapping_and_lagged_rows(tmp_path: Path) -> None:
    obs, counts, (rows, _, skipped) = built(tmp_path)
    assert counts == {"series_not_selected": 1, "missing_value": 1}
    assert {o.unit for o in obs} == {"unstated"} and {o.frequency for o in obs} == {None}
    assert all(o.superseded_on is None for o in obs)
    assert skipped["held_vintage_chain_unverified"] == 4
    by = {r["logical_id"]: r["metadata"] for r in rows}
    dated = by["lpc-alfred/CPIAUCSL/2024-01-01@2024-02-01"]
    assert dated["recorded_at"] == "2024-02-02T12:00:00+00:00" == dated["available_at"]
    lagged = by["lpc-alfred/DFF/2024-01-05@lagged-2024-01-06"]
    assert lagged["recorded_at"] is None and lagged["available_at"] is None
    for m in (dated["recorded_at"], dated["valid_from"]):
        assert parse_moment(m, field="m").tzinfo is not None


def test_tasks_and_leaks(tmp_path: Path) -> None:
    _, _, (rows, tasks, skipped) = built(tmp_path)
    ev = {r["logical_id"]: r for r in rows}
    by: dict[str, list[dict[str, Any]]] = {t["stratum"]: [] for t in tasks}
    for t in tasks:
        parse_task(t)
        by[t["stratum"]].append(t)
    # chain unverified: no as-of tasks, counted
    assert "modified" not in by and skipped["modified_chain_unverified"] == 1
    late = next(t for t in by["late_recorded"] if t["query"] == "CPIAUCSL 2024-01-01")
    row = ev["lpc-alfred/CPIAUCSL/2024-01-01@2024-02-01"]
    assert late["gold_evidence_ids"] == [] and not late["answerable"]
    cut = {k: parse_moment(v, field=k) for k, v in late["cut"].items()}
    assert cut["known_at"] == datetime(2024, 2, 2, 11, 59, 59, tzinfo=UTC)
    assert violates_cut(row["metadata"], cut)
    # the lagged row with no dated sibling is a leak under an available_at cut
    unk = [t for t in by["unknown_availability"] if t["query"] == "DFF 2024-01-05"]
    assert len(unk) == 1 and unk[0]["gold_evidence_ids"] == []
    ucut = {k: parse_moment(v, field=k) for k, v in unk[0]["cut"].items()}
    assert violates_cut(ev["lpc-alfred/DFF/2024-01-05@lagged-2024-01-06"]["metadata"], ucut)
    # DFF 2024-01-02 has a dated row available by the cut, so no abstain task
    assert skipped["unknown_availability_key_has_dated_row"] == 1


def test_modified_only_with_matching_chain_file(tmp_path: Path) -> None:
    csv_path = write(tmp_path)
    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    good = tmp_path / "chain.json"
    good.write_text(
        json.dumps({"schema": al.CHAIN_SCHEMA, "csv_sha256": sha,
                    "series": {"CPIAUCSL": ["2024-03-01", "2024-02-01"], "DFF": ["2024-01-03"]}})
    )  # fmt: skip
    chain = al.load_chain_verified(good, sha)
    _, _, (rows, tasks, skipped) = built(tmp_path, chain)
    (m,) = [t for t in tasks if t["stratum"] == "modified"]
    assert m["query"] == "CPIAUCSL 2024-01-01" and "modified_chain_unverified" not in skipped
    assert m["gold_evidence_ids"] == ["ev:lpc-alfred/CPIAUCSL/2024-01-01@2024-02-01"]
    leak = next(r for r in rows if r["logical_id"].endswith("2024-01-01@2024-03-01"))
    cut = {k: parse_moment(v, field=k) for k, v in m["cut"].items()}
    assert violates_cut(leak["metadata"], cut)  # v_{k+1} is flagged
    assert not violates_cut(
        next(r for r in rows if r["evidence_id"] == m["gold_evidence_ids"][0])["metadata"], cut
    )
    # a vintage set that differs from the CSV's does not verify the series
    _, _, (_, tasks2, sk2) = built(tmp_path, {"CPIAUCSL": ["2024-02-01"]})
    assert (
        not [t for t in tasks2 if t["stratum"] == "modified"] and sk2["modified_chain_unverified"]
    )
    with pytest.raises(al.AlfredError):
        al.load_chain_verified(good, "f" * 64)


def test_merges_into_pit_tasks_and_duplicates_refused(tmp_path: Path) -> None:
    _, _, (rows, tasks, _) = built(tmp_path)
    out = pt.generate([], [], alfred=(rows, tasks))
    assert len(out["tasks"]) == len(tasks) and len(out["corpus"]) == len(rows)
    dup = write(tmp_path, [LINES[0], LINES[0]])
    obs, _ = al.read_local_vintages(dup, ["CPIAUCSL"], REGISTER, TODAY)
    with pytest.raises(al.AlfredError):
        al.generate(obs)


def test_reviewed_rights_deny_alfred_before_the_file_is_opened(tmp_path: Path) -> None:
    missing = tmp_path / "never_opened.csv"  # opening it would raise FileNotFoundError instead
    with pytest.raises(RightsDenied):
        al.read_local_vintages(missing, S.DENIED_ALFRED_SERIES, REVIEWED_RIGHTS, TODAY)
    assert not missing.exists()


def test_terms_snapshot_refuses_alfred_sources_without_a_request(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"x")

    with pytest.raises(S.SourceError, match="rights denied"):
        terms.snapshot(
            tmp_path / "o",
            sources=[("data_alfred_vintages", "https://fred.stlouisfed.org/legal/")],
            user_agent="t t@example.org",
            transport=httpx.MockTransport(handler),
        )
    assert calls == []
    assert all(s.startswith("data_sec") for s, _ in terms.SOURCES)


def test_main_refuses_on_rights_before_any_file_is_resolved_hashed_or_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the other project's file was touched")

    m = manifest_for(tmp_path, write(tmp_path))  # a real, correctly pinned file that must stay shut
    monkeypatch.setattr(S.Loader, "verified_path", boom)
    monkeypatch.setattr(S.Loader, "resolve", boom)
    monkeypatch.setattr(S, "_sha256_file", boom)
    monkeypatch.setattr(Path, "read_bytes", boom)
    out = tmp_path / "o"
    assert al.main(["--manifest", str(m), "--out", str(out)]) == 2
    assert "refused" in capsys.readouterr().err and not out.exists()
    assert al.main(["--manifest", str(m), "--out", str(out), "--series", "VIXCLS"]) == 2
