"""WO-LPC-4: SEC screen / EG-04 records, sealed gold, split-gold.

Synthetic FSDS, filings and a fake renderer in tmp_path. No browser, no network, no real data.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest

from benchmark.local_public import pit_rows, sec_screen, sources
from benchmark.local_public.pit_tasks import SPEC_STATEMENTS
from benchmark.screen import manifest as screen_manifest
from benchmark.screen.critical_fields import gold_value
from benchmark.tests.test_local_public_sec_align import CTX as _CTX
from benchmark.tests.test_local_public_sec_align import doc, fact
from benchmark.v6.contracts import canonical_sha256

W1 = "2025-08-29 16:05:00.0"
W2 = "2025-08-29T20:05:22.000Z"
COLS_SUB = [
    "adsh",
    "cik",
    "name",
    "form",
    "period",
    "fye",
    "fy",
    "fp",
    "filed",
    "accepted",
    "prevrpt",
    "instance",
]
COLS_NUM = ["adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value"]
COLS_PRE = ["adsh", "report", "line", "stmt", "plabel", "negating", "tag", "version"]
CTX: list[tuple[str, str | None, str, bool]] = [*_CTX]
TAGS = ["Revenues", "CostOfRevenue", "GrossProfit", "NetIncomeLoss"]


def tsv(cols: list[str], rows: list[dict[str, str]]) -> bytes:
    return "\n".join(["\t".join(cols), *("\t".join(r[c] for c in cols) for r in rows)]).encode()


def page_html(label: str, script: bool = False, rows: int = 4) -> bytes:
    """A filing with a filer page break, then one table of `rows` presented rows."""
    cells = [
        [f"{label} Revenue", fact("1,234", tag="us-gaap:Revenues")],
        [f"{label} Cost", fact("500", tag="us-gaap:CostOfRevenue")],
        [f"{label} Profit", fact("90", tag="us-gaap:GrossProfit")],
        [f"{label} Loss", "$ (", fact("700", tag="us-gaap:NetIncomeLoss", sign="-"), ")"],
    ][:rows]
    html = doc(CTX, cells).replace(
        b"<table>", b'<div style="page-break-after:always"></div><table>', 1
    )
    return html.replace(b"<body>", b"<body><script>x=1</script>") if script else html


class World:
    """Fake pinned loader over files in tmp_path (the real Loader needs a real manifest)."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.subs: list[dict[str, str]] = []
        self.nums: list[dict[str, str]] = []
        self.pres: list[dict[str, str]] = []
        self.c2: list[dict[str, str]] = []
        self.bulk: dict[str, str] = {}
        self.html: dict[str, bytes] = {}

    def filing(
        self, adsh: str, cik: str, form: str = "10-Q", period: str = "20250731", **kw: Any
    ) -> str:
        label = kw.pop("label", adsh[-4:])
        html = kw.pop("html", None) or page_html(label)
        self.subs.append(
            dict(
                adsh=adsh,
                cik=cik,
                name=f"Co {cik}",
                form=form,
                period=period,
                fye="0131",
                fy="2025",
                fp="Q2",
                filed="20250829",
                accepted=W1,
                prevrpt="0",
                instance="x-20250802_htm.xml",
            )
        )
        values = {
            "Revenues": "1234000000",
            "CostOfRevenue": "500000000",
            "GrossProfit": "90000000",
            "NetIncomeLoss": "-700000000",
        }
        for i, t in enumerate(TAGS):
            self.nums.append(
                dict(
                    adsh=adsh,
                    tag=t,
                    version="us-gaap/2024",
                    ddate="20250731",
                    qtrs="1",
                    uom="USD",
                    segments="",
                    coreg="",
                    value=values[t],
                )
            )
            self.pres.append(
                dict(
                    adsh=adsh,
                    report="2",
                    line=str(i),
                    stmt="IS",
                    plabel=t,
                    negating="0",
                    tag=t,
                    version="us-gaap/2024",
                )
            )
        self.c2.append(
            {"adsh": adsh, "cik": cik, "url": f"https://www.sec.gov/Archives/{adsh}.htm"}
        )
        if "w2" not in kw:
            self.bulk[adsh] = W2
        self.html[adsh] = html
        return adsh

    def loader(self) -> sources.Loader:
        t = self.tmp / "src"
        t.mkdir(exist_ok=True)
        fs = t / "2025q3.zip"
        with zipfile.ZipFile(fs, "w") as z:
            z.writestr("sub.txt", tsv(COLS_SUB, self.subs))
            z.writestr("num.txt", tsv(COLS_NUM, self.nums))
            z.writestr("pre.txt", tsv(COLS_PRE, self.pres))
        bulk = t / "bulk.zip"
        with zipfile.ZipFile(bulk, "w") as z:
            body = {
                "filings": {
                    "recent": {
                        "accessionNumber": list(self.bulk),
                        "acceptanceDateTime": list(self.bulk.values()),
                    }
                }
            }
            z.writestr("CIK1.json", json.dumps(body))
        c2 = t / "manifest.jsonl"
        c2.write_text("\n".join(json.dumps(r) for r in self.c2), "utf-8")
        paths: dict[str, Path] = {
            "sec_fsds/2025q3": fs,
            "sec_submissions_bulk": bulk,
            "c2_manifest": c2,
        }
        entries: dict[str, dict[str, Any]] = {
            "sec_fsds/2025q3": {"name": "sec_fsds/2025q3"},
            "terms/data_sec_edgar_filings": {"sha256": "ab" * 32},
            sec_screen.RENDERER_ENTRY: {"sha256": "cd" * 32},
        }
        for adsh, html in self.html.items():
            p = t / f"{adsh}.htm.gz"
            p.write_bytes(gzip.compress(html))
            paths[f"sec_filing/{adsh}"] = p
            entries[f"sec_filing/{adsh}"] = {"content_sha256": hashlib.sha256(html).hexdigest()}
        return cast(sources.Loader, Fake(paths, entries))


class Fake:
    def __init__(self, paths: dict[str, Path], entries: dict[str, dict[str, Any]]) -> None:
        self.paths, self._by_name = paths, entries
        self.manifest = {"manifest_sha256": "sha256:" + "f" * 64}
        self.ledger = sources.InputLedger(self.manifest["manifest_sha256"])

    def resolve(self, name: str) -> dict[str, Any]:
        return self._by_name[name]

    def verified_path(self, name: str) -> Path:
        return self.paths[name]

    def open_verified(self, name: str) -> Any:
        return self.paths[name].open("rb")


def fake_render(pages: int = 1) -> Any:
    def render(html: Path, pdf: Path) -> int:
        pdf.write_bytes(b"%PDF-fake" + html.read_bytes())
        return pages

    return render


def run(w: World, tmp: Path, **kw: Any) -> tuple[dict[str, Any], Path]:
    out = tmp / "out"
    args: dict[str, Any] = dict(
        seed="s",
        screen_pages=1,
        eg04_pages=0,
        recorded_by="test",
        gold_value=gold_value,
        loader=w.loader(),
        render=fake_render(),
    )
    args.update(kw)
    return sec_screen.build(out, **args), out


def lines(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text("utf-8").splitlines()]


def test_one_filing_per_cik_and_records_pass_check_doc(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111")
    w.filing("0000000001-25-000002", "111")
    census, out = run(w, tmp_path, screen_pages=2)
    recs = lines(out / "screen/records.jsonl")
    assert len(recs) == 1 and census["shortfall"] == {"screen": 1, "eg04": 0}
    r = recs[0]
    screen_manifest._check_doc(r)
    assert r["rights"]["rights_class"] == "public_record" and r["rights"]["redistribution"] is False
    assert r["rights"]["licence_id"] == "SEC-WEBSITE-POLICY"
    assert r["rights"]["licence_snapshot_sha256"] == "sha256:" + "ab" * 32
    assert r["rights"]["source_url"].startswith("https://www.sec.gov/")
    assert (r["stratum"], r["language"], r["page_count"]) == ("en_native", "en", 1)
    assert r["document_class"] == "sec_10q_statement_print"
    assert set(r["provenance"]) == {
        "adsh",
        "cik",
        "form",
        "filing_content_sha256",
        "excerpt_html_sha256",
        "fsds_quarter",
        "renderer_sha256",
        "lpc_manifest_sha256",
    }
    pdf = out / "screen/corpus" / r["doc_id"]
    assert "sha256:" + hashlib.sha256(pdf.read_bytes()).hexdigest() == r["source_sha256"]
    assert not (out / "tmp").exists()


def test_every_gold_passes_gold_value_and_keeps_the_shown_sign(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111")
    _, out = run(w, tmp_path)
    gold = lines(out / "screen/gold.sealed.jsonl")
    assert len(gold) == 1 and gold[0]["page_id"].endswith(".pdf#0")
    fields = gold[0]["truth"]["critical_fields"]
    assert len(fields) == 3
    # the page shows "$ (700)", which the scorer cannot read: no gold, counted, never rewritten
    assert all("700" not in f["value"] for f in fields)
    for f in fields:
        gold_value(f)
        assert f["fsds"]["ddate_precision"] == "month_rounded" and f["fsds"]["quarter"] == "2025q3"
    t = gold[0]["truth"]
    assert t["text_source"] == "html_dom_text" and t["high_risk"] is True
    assert t["selection_condition"] == sec_screen.SELECTION


def test_sealed_gold_is_in_no_readable_record(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111")
    _, out = run(w, tmp_path)
    secrets = ["1,234", "(700)", "Revenue", "Cost", "Loss", "1234000000", "us-gaap"]
    for name in ("screen/records.jsonl", "selected_ciks.json", "receipt.json"):
        text = (out / name).read_text("utf-8")
        assert not [s for s in secrets if s in text], name
    assert "gold" not in json.dumps(lines(out / "screen/records.jsonl")[0]["provenance"])


def test_excluded_and_reserved_ciks_are_never_selected(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111")  # excluded by the frozen manifest
    w.filing("0000000002-25-000002", "222")  # reserved: 10-K/A with its 10-K in FSDS
    w.filing("0000000002-25-000003", "222", form="10-K", period="20241231")
    w.filing("0000000002-25-000004", "222", form="10-K/A", period="20241231")
    w.filing("0000000003-25-000005", "333")
    frozen = tmp_path / "frozen.json"
    frozen.write_text(
        json.dumps(
            {
                "documents": [
                    {"source_sha256": "sha256:" + "1" * 64, "provenance": {"cik": 111}},
                    {"source_sha256": "sha256:" + "2" * 64, "rights": {"licence_id": "X"}},
                ]
            }
        ),
        "utf-8",
    )
    census, out = run(w, tmp_path, exclude_from=frozen, pool=50)
    assert [r["provenance"]["cik"] for r in lines(out / "screen/records.jsonl")] == [333]
    assert census["reserved_amendment_ciks"] == 1 and census["excluded_from_ciks"] == 1


def test_frozen_sec_document_without_cik_refuses(tmp_path: Path) -> None:
    f = tmp_path / "f.json"
    f.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "doc_id": "d",
                        "source_sha256": "sha256:" + "1" * 64,
                        "rights": {"licence_id": "SEC-WEBSITE-POLICY"},
                    }
                ]
            }
        ),
        "utf-8",
    )
    with pytest.raises(sec_screen.ScreenError, match=r"provenance\.cik"):
        sec_screen.frozen_exclusions(f)


def test_excluded_source_hash_is_skipped(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111")
    _, out = run(w, tmp_path)
    h = lines(out / "screen/records.jsonl")[0]["source_sha256"]
    frozen = tmp_path / "f.json"
    frozen.write_text(json.dumps({"documents": [{"source_sha256": h}]}), "utf-8")
    got = sec_screen.build(
        tmp_path / "out2",
        seed="s",
        screen_pages=1,
        eg04_pages=0,
        recorded_by="t",
        gold_value=gold_value,
        loader=w.loader(),
        render=fake_render(),
        exclude_from=frozen,
    )
    assert (
        got["documents"]["screen"] == 0 and got["reasons"]["source_hash_excluded_or_duplicate"] == 1
    )


def test_unresolved_acceptance_is_skipped_and_counted(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111", w2=True)  # no second witness
    w.filing("0000000002-25-000002", "222")
    census, out = run(w, tmp_path, pool=50)
    assert [r["provenance"]["cik"] for r in lines(out / "screen/records.jsonl")] == [222]
    assert census["reasons"]["acceptance_unresolved"] == 1


def test_rights_class_missing_refuses_before_any_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Boom:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"read {name} before the rights check")

    monkeypatch.setattr(screen_manifest, "RIGHTS_CLASSES", ("owned", "synthetic"))
    with pytest.raises(sec_screen.ScreenError, match="public_record"):
        sec_screen.build(
            tmp_path / "o",
            seed="s",
            screen_pages=1,
            eg04_pages=0,
            recorded_by="t",
            gold_value=gold_value,
            loader=cast(sources.Loader, Boom()),
        )
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize(
    "families",
    [
        {},
        {"sec_edgar": {"rights_class": "public_record", "licences": {"OTHER": "u"}}},
        {
            "sec_edgar": {
                "rights_class": "permissive_licence",
                "licences": {"SEC-WEBSITE-POLICY": "u"},
            }
        },
    ],
)
def test_family_or_licence_missing_refuses(tmp_path: Path, families: dict[str, Any]) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111")
    with pytest.raises(sec_screen.ScreenError):
        run(w, tmp_path, families=families)
    assert not (tmp_path / "out").exists()


def test_selected_ciks_is_the_union_of_both_profiles_and_cik_disjoint(tmp_path: Path) -> None:
    w = World(tmp_path)
    for i in (1, 2, 3):
        w.filing(f"000000000{i}-25-00000{i}", f"{i}00")
    census, out = run(w, tmp_path, screen_pages=1, eg04_pages=2, pool=50)
    a = {r["provenance"]["cik"] for r in lines(out / "screen/records.jsonl")}
    b = {r["provenance"]["cik"] for r in lines(out / "eg04/records.jsonl")}
    assert len(a) == 1 and len(b) == 2 and not a & b
    sel = json.loads((out / "selected_ciks.json").read_text("utf-8"))
    assert sel == {"ciks": sorted(a | b)}
    assert pit_rows._load_ciks(out / "selected_ciks.json") == {str(c) for c in a | b}
    assert (
        census["selected_ciks_sha256"]
        == hashlib.sha256((out / "selected_ciks.json").read_bytes()).hexdigest()
    )


def test_receipt_has_statements_verbatim_and_census(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111")
    _, out = run(w, tmp_path)
    rec = json.loads((out / "receipt.json").read_text("utf-8"))
    for s in SPEC_STATEMENTS:
        assert s in rec["statements"]
    assert "Pre-training exposure cannot be controlled." in rec["statements"][0]
    assert rec["lpc_manifest_sha256"] == "sha256:" + "f" * 64
    y = rec["census"]["yield_over_presented_non_dimensional_rows"]
    assert y["denominator"] == 4 and y["gold"] == 0.75 and y["aligned"] == 0.75
    assert rec["census"]["reasons"]["gold_unparseable"] == 1
    assert rec["census"]["filer_agent_prefix_by_profile"]["screen"] == {"0000000001": 1}
    assert {o["path"].rsplit("/", 1)[-1] for o in rec["outputs"]} >= {
        "records.jsonl",
        "gold.sealed.jsonl",
        "selected_ciks.json",
    }


def test_multi_page_script_render_failure_and_no_breaks_are_counted(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111", html=page_html("a", script=True))
    w.filing("0000000002-25-000002", "222", html=doc(CTX, [["x", fact("1")]]))  # no page break
    w.filing("0000000003-25-000003", "333")
    w.filing("0000000004-25-000004", "444", html=page_html("d", rows=2))  # too few fields
    census, _ = run(w, tmp_path, render=fake_render(2), pool=50)
    assert census["documents"]["screen"] == 0
    r = census["reasons"]
    assert r["script_refused"] == 1 and r["no_filer_page_breaks"] == 1
    assert r["segment_multi_page"] == 1 and r["too_few_fields"] >= 2

    def boom(html: Path, pdf: Path) -> int:
        raise RuntimeError("renderer exited with 1")

    w2 = World(tmp_path / "w2")
    (tmp_path / "w2").mkdir()
    w2.filing("0000000003-25-000003", "333")
    census2, _ = run(w2, tmp_path / "w2", render=boom)
    assert census2["reasons"]["render_failed"] == 1 and census2["render_errors"]


def test_split_gold_writes_splits_and_removes_sealed(tmp_path: Path) -> None:
    w = World(tmp_path)
    for i in (1, 2):
        w.filing(f"000000000{i}-25-00000{i}", f"{i}00")
    _, out = run(w, tmp_path, screen_pages=2, pool=50)
    recs = lines(out / "screen/records.jsonl")
    for r, s in zip(recs, ("dev", "holdout"), strict=True):
        r["split"] = s
    body = {"profile": "screen", "salt": "s", "counts": {}, "documents": recs}
    m = tmp_path / "m.json"
    m.write_text(json.dumps({**body, "manifest_sha256": canonical_sha256(body)}), "utf-8")
    sealed = out / "screen/gold.sealed.jsonl"
    rec = sec_screen.split_gold(m, sealed)
    assert not sealed.exists()
    dev, hold = lines(out / "screen/gold.dev.jsonl"), lines(out / "screen/gold.holdout.jsonl")
    assert [g["page_id"] for g in dev] == [recs[0]["doc_id"] + "#0"]
    assert [g["page_id"] for g in hold] == [recs[1]["doc_id"] + "#0"]
    assert rec["documents"] == {"dev": 1, "holdout": 1}
    assert rec["filer_agent_prefix_by_split"]["dev"] == {recs[0]["provenance"]["adsh"][:10]: 1}


def _manifest(tmp: Path, recs: list[dict[str, Any]]) -> Path:
    body = {"profile": "screen", "salt": "s", "counts": {}, "documents": recs}
    m = tmp / "m.json"
    m.write_text(json.dumps({**body, "manifest_sha256": canonical_sha256(body)}), "utf-8")
    return m


def test_split_gold_refuses_when_doc_sets_differ_and_keeps_sealed(tmp_path: Path) -> None:
    w = World(tmp_path)
    for i in (1, 2):
        w.filing(f"000000000{i}-25-00000{i}", f"{i}00")
    _, out = run(w, tmp_path, screen_pages=2, pool=50)
    recs = lines(out / "screen/records.jsonl")
    for r in recs:
        r["split"] = "dev"
    sealed = out / "screen/gold.sealed.jsonl"
    with pytest.raises(sec_screen.ScreenError, match="sets differ"):
        sec_screen.split_gold(_manifest(tmp_path, recs[:1]), sealed)
    assert sealed.exists() and not (out / "screen/gold.dev.jsonl").exists()
    del recs[0]["split"]
    with pytest.raises(sec_screen.ScreenError, match="needs a split"):
        sec_screen.split_gold(_manifest(tmp_path, recs), sealed)
    bad = _manifest(tmp_path, recs)
    bad.write_text(bad.read_text("utf-8").replace('"salt": "s"', '"salt": "t"'), "utf-8")
    with pytest.raises(sec_screen.ScreenError, match="manifest_sha256"):
        sec_screen.split_gold(bad, sealed)


def test_output_inside_git_tree_and_zero_pages_refuse(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111")
    with pytest.raises(sec_screen.ScreenError, match="not both 0"):
        run(w, tmp_path, screen_pages=0, eg04_pages=0)
    with pytest.raises(sec_screen.ScreenError, match="git work tree"):
        sec_screen.build(
            Path(__file__).parent / "never",
            seed="s",
            screen_pages=1,
            eg04_pages=0,
            recorded_by="t",
            gold_value=gold_value,
            loader=w.loader(),
        )


def test_signed_adapter_is_strict_and_never_rewrites_the_shown_value() -> None:
    f = {"kind": "number", "anchor": "a"}
    read = sec_screen.signed(gold_value)
    assert read({**f, "value": "($ 700)"}) == -700 and read({**f, "value": "1,234"}) == 1234
    with pytest.raises(ValueError):  # what the page shows, "$ (700)", is not a readable gold
        read({**f, "value": "$ (700)"})
    with pytest.raises(ValueError):
        sec_screen.signed(lambda _f: 5)({**f, "value": "5"})
    with pytest.raises(ValueError):
        read({**f, "value": "(1,234"})


def test_rows_of_dom_refused_filings_stay_in_the_yield_denominator(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.filing("0000000001-25-000001", "111")
    w.filing(
        "0000000002-25-000002",
        "222",
        html=page_html("b").replace(b'<div style="page-break-after:always"></div>', b""),
    )
    census, _ = run(w, tmp_path, pool=50, screen_pages=2)
    assert census["reasons"]["no_filer_page_breaks"] == 1
    y = census["yield_over_presented_non_dimensional_rows"]
    assert y["denominator"] == 8 and y["gold"] == 0.375
