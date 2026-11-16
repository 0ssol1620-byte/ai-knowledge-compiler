"""WO-LPC-6A: SEC point-in-time rows. Synthetic fixtures only."""

from __future__ import annotations

import gzip
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest

from benchmark.local_public import pit_rows as pr
from benchmark.local_public import sec_time, sources
from benchmark.retrieval_baselines.metrics import parse_moment, violates_cut
from benchmark.tests.test_local_public_sec_align import (
    CTX,
    KOHLS,
    doc,
    fact,
    gold_value,
    num,
    pre,
    row,
)

ACC = datetime(2025, 8, 29, 20, 5, 22, tzinfo=UTC)
EARLY = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
SUB = {**KOHLS, "cik": "0000885639", "name": "KOHLS Corp"}
HTML = doc(CTX, [row(fact("1,234"))])


def one_filing(
    html: bytes = HTML,
    acc: datetime | None = ACC,
    n: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return pr.filing_rows(SUB, [n or num()], pre(), html, gold_value, acc)


def plain_filing(adsh: str, acc: datetime | None) -> Any:
    sub = {**SUB, "adsh": adsh, "instance": "kss-20250202.xml"}
    return pr.filing_rows(
        sub, [{**num(), "adsh": adsh}], [{**pre()[0], "adsh": adsh}], b"", gold_value, acc
    )


def test_ixbrl_duration_validity_and_cut_edges() -> None:
    (r,), _ = one_filing()
    md = r["metadata"]
    assert md["valid_from"] == "2025-05-04T00:00:00+00:00"
    assert md["valid_to"] == "2025-08-03T00:00:00+00:00"
    assert md["recorded_at"] == md["available_at"] == "2025-08-29T20:05:22+00:00"
    assert r["logical_id"] == f"lpc-sec/885639/Revenues/2025-05-04_2025-08-02/USD@{SUB['adsh']}"
    assert "KOHLS Corp: Revenues: 1234000000 USD, 2025-05-04 to 2025-08-02." in r["text"]
    first = parse_moment(md["valid_from"], field="f")
    last = parse_moment(md["valid_to"], field="t")
    assert not violates_cut(md, {"valid_at": first})
    assert violates_cut(md, {"valid_at": first - timedelta(seconds=1)})
    assert not violates_cut(md, {"valid_at": last - timedelta(seconds=1)})
    assert violates_cut(md, {"valid_at": last})


def test_ixbrl_instant_validity() -> None:
    html = doc([("c1", None, "2025-08-02", False)], [row(fact("1,234"))])
    (r,), _ = one_filing(html=html, n=num(qtrs="0"))
    assert r["metadata"]["valid_from"] == "2025-08-02T00:00:00+00:00"
    assert r["metadata"]["valid_to"] == "2025-08-03T00:00:00+00:00"
    assert "as of 2025-08-02." in r["text"]


def test_non_ixbrl_has_null_validity_and_no_ddate_as_date() -> None:
    (r,), (k,) = plain_filing("0000885639-25-000001", ACC)
    assert r["metadata"]["valid_from"] is None and r["metadata"]["valid_to"] is None
    assert r["logical_id"].endswith("/20250731m1/USD@0000885639-25-000001")
    assert "month as rounded by FSDS" in r["text"]
    assert k["ddate_precision"] == "month_rounded"
    for key in ("recorded_at", "available_at"):
        parse_moment(r["metadata"][key], field=key)


def test_unresolved_acceptance_writes_no_row() -> None:
    assert one_filing(acc=None) == ([], [])
    assert plain_filing("0000885639-25-000001", None) == ([], [])


def test_naive_acceptance_refused() -> None:
    with pytest.raises(pr.PitError):
        one_filing(acc=datetime(2025, 8, 29, 20, 5, 22))


def test_first_reporting_joins_on_fsds_key_across_ixbrl_and_plain() -> None:
    """Plain 10-K first, iXBRL 10-Q later: joined on (cik, tag, ddate, qtrs, uom)."""
    k10 = plain_filing("0000885639-25-000001", EARLY)
    corpus, index = pr.assemble([one_filing(), k10])
    assert len(corpus) == 2
    assert {i["first_reported_by"] for i in index} == {"0000885639-25-000001"}
    assert {i["adsh"]: i["fsds_key"]["ddate"] for i in index}[SUB["adsh"]] == "20250731"
    assert all("_key" not in r and "first_reported_by" not in r for r in corpus)


def test_key_carried_by_unresolved_filing_has_no_first_reporter() -> None:
    _, index = pr.assemble(
        [one_filing()], unresolved_keys=[("885639", "Revenues", "20250731", "1", "USD")]
    )
    assert index[0]["first_reported_by"] is None


def test_duplicate_logical_id_raises() -> None:
    with pytest.raises(pr.PitError, match="duplicate"):
        pr.assemble([one_filing(), one_filing()])


def test_cap_raises() -> None:
    with pytest.raises(pr.PitError, match="cap"):
        pr.assemble([one_filing()], cap=0)


def test_missing_exclude_ciks_refuses(tmp_path: Path) -> None:
    with pytest.raises(pr.PitError, match="exclude-ciks"):
        pr.build(tmp_path / "o", None)
    assert pr.main(["build", "--out", str(tmp_path / "o")]) == 1


def test_pick_ciks_never_returns_excluded() -> None:
    allc = {str(i) for i in range(1, 50)}
    ex = {str(i) for i in range(1, 40)}
    assert pr.pick_ciks(allc, ex, 12, 7) == allc - ex
    assert pr.pick_ciks(allc, set(), 12, 7) == pr.pick_ciks(allc, set(), 12, 7)


C2: list[tuple[str, str | None, str, bool]] = [
    ("c1", "2025-05-04", "2025-08-02", False),
    ("c2", "2024-05-05", "2024-08-03", False),
]


def comparative_filing(**kw: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """10-Q row: current quarter and prior-year quarter facts on one line."""
    html = doc(C2, [["Total revenues", fact("1,234"), fact("1,000", ctx="c2")]])
    nums = [num(), num(value="1000000000", ddate="20240731")]
    return pr.filing_rows(SUB, nums, pre(), html, gold_value, ACC, **kw)


def test_ixbrl_comparative_column_is_a_row_with_its_own_context_dates() -> None:
    reasons: dict[str, int] = {}
    rows, keys = comparative_filing(reasons=reasons)
    assert len(rows) == len(keys) == 2
    prior = next(r for r in rows if "2024-05-05_2024-08-03" in r["logical_id"])
    assert prior["metadata"]["valid_from"] == "2024-05-05T00:00:00+00:00"
    assert prior["metadata"]["valid_to"] == "2024-08-04T00:00:00+00:00"
    assert reasons == {"not_first_column": 1}


def test_ixbrl_row_without_matching_context_is_month_basis_with_null_validity() -> None:
    html = doc(C2[:1], [["Total revenues", fact("1,234"), fact("1,000", ctx="c9")]])
    nums = [num(), num(value="1000000000", ddate="20240731")]
    rows, _ = pr.filing_rows(SUB, nums, pre(), html, gold_value, ACC)
    prior = next(r for r in rows if r["logical_id"].endswith("/20240731m1/USD@" + SUB["adsh"]))
    assert prior["metadata"]["valid_from"] is None and prior["metadata"]["valid_to"] is None
    assert "month as rounded by FSDS" in prior["text"]


@pytest.mark.parametrize(
    "content",
    [
        {"screen": ["1"], "eg04": ["2"]},
        {"ciks": ["1"], "extra": 1},
        [],
        {"ciks": []},
        ["abc"],
        [1.5],
        [True],
        "123",
        [None],
    ],
)
def test_load_ciks_refuses_unrecognised_holdout_shapes(tmp_path: Path, content: Any) -> None:
    p = tmp_path / "x.json"
    p.write_text(json.dumps(content), "utf-8")
    with pytest.raises(pr.PitError, match="exclude-ciks"):
        pr._load_ciks(p)


def test_load_ciks_accepts_list_and_ciks_dict(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    for content in ([1, "0000002"], {"ciks": ["0000001", 2]}):
        p.write_text(json.dumps(content), "utf-8")
        assert pr._load_ciks(p) in ({"1", "2"},)


def test_build_records_manifest_digest_and_reason_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adsh = SUB["adsh"]

    def tsv(rows: list[dict[str, str]]) -> bytes:
        cols = list(rows[0])
        return "\n".join(
            "\t".join(r[c] for c in cols) for r in [dict(zip(cols, cols, strict=True)), *rows]
        ).encode()

    sub = {**SUB, "accepted": "2025-08-29 20:05:22.0"}
    html = doc(C2, [["Total revenues", fact("1,234"), fact("1,000", ctx="c2")]])
    nums = [{**num(), "adsh": adsh}, {**num(value="1000000000", ddate="20240731"), "adsh": adsh}]
    fsds = io.BytesIO()
    with zipfile.ZipFile(fsds, "w") as z:
        z.writestr("sub.txt", tsv([sub]))
        z.writestr("num.txt", tsv(nums))
        z.writestr("pre.txt", tsv([{**pre()[0], "adsh": adsh}]))
    gz = gzip.compress(html)
    c2 = tmp_path / "c2.jsonl"
    c2.write_text(json.dumps({"cik": "885639", "adsh": adsh}) + "\n", "utf-8")

    class Loader:
        manifest: ClassVar[dict[str, Any]] = {
            "manifest_sha256": "f" * 64,
            "entries": [{"name": "sec_fsds/2025q3"}],
        }

    monkeypatch.setattr(sources, "configure", lambda m: Loader())
    monkeypatch.setattr(sources, "verified_path", lambda n: c2)
    monkeypatch.setattr(
        sources,
        "open_verified",
        lambda n: io.BytesIO(
            fsds.getvalue()
            if n.startswith("sec_fsds")
            else gz
            if n.startswith("sec_filing")
            else b""
        ),
    )
    monkeypatch.setattr(zipfile, "ZipFile", _zip_or_empty(zipfile.ZipFile))
    monkeypatch.setattr(sec_time, "bulk_index", lambda z: {})
    monkeypatch.setattr(sec_time, "accepted_at", lambda a, b: ACC)
    ex = tmp_path / "ex.json"
    ex.write_text("[999]", "utf-8")
    out = tmp_path / "o"
    assert pr.build(out, ex, gold_value=gold_value)["rows"] == 2
    meta = json.loads((out / "pit_rows_meta.json").read_text("utf-8"))
    assert meta["lpc_manifest_sha256"] == "f" * 64
    assert meta["ixbrl_rows_without_screen_candidate_by_align_reason"] == {"not_first_column": 1}


def _zip_or_empty(real: Any) -> Any:
    def make(f: Any, *a: Any, **k: Any) -> Any:
        try:
            return real(f, *a, **k)
        except zipfile.BadZipFile:  # the submissions-bulk stand-in is not a zip
            return real(_EMPTY_ZIP)

    return make


_buf = io.BytesIO()
with zipfile.ZipFile(_buf, "w"):
    pass
_EMPTY_ZIP = io.BytesIO(_buf.getvalue())
