"""WO-D02-3C: synthetically degraded prints, gold carried over. Synthetic records and a generated
PDF only; no real corpus directory and no real gold file is read."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pytest
from akc_api.parsers import parse_document
from akc_api.settings import Settings

from benchmark.local_public import sec_screen
from benchmark.screen import degrade
from benchmark.screen import manifest as screen_manifest
from benchmark.tests.test_screen_manifest import WRONG, _sec, _sec_set, field_paths, mutated
from benchmark.v6.contracts import ContractError, canonical_sha256

LEVELS = ("scan_fair", "scan_poor")


def _pdf(*texts: str, box: bytes = b"0 0 300 200") -> bytes:
    """A small born-digital PDF with a real text layer, one page per text."""
    n = len(texts)
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(n))
        + b"] /Count %d >>" % n,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(texts):
        stream = b"BT /F1 14 Tf 20 150 Td (" + text.encode("ascii") + b") Tj ET"
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox ["
            + box
            + b"] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (5 + 2 * i)
        )
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for k, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % k + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def _native_text(data: bytes) -> str:
    settings = Settings(env="test", max_pages=10, local_background_tasks=False)
    return "".join(p.text for p in parse_document("page.pdf", data, settings).pages)


def _profile(tmp: Path, n: int = 3) -> tuple[Path, list[dict[str, Any]]]:
    root = tmp / "screen"
    (root / "corpus").mkdir(parents=True)
    recs = []
    for i in range(n):
        data = _pdf(f"Total revenue {1000 + i} Net income {200 + i}")
        rec = _sec(i, data=data)
        (root / "corpus" / rec["doc_id"]).write_bytes(data)
        recs.append(rec)
    (root / "records.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs), "utf-8"
    )
    return root, recs


def _files(d: Path) -> dict[str, bytes]:
    return {
        p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()
    }


def _lines(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]


def test_second_run_is_byte_identical_and_records_describe_each_page(tmp_path: Path) -> None:
    src, recs = _profile(tmp_path)
    r1 = degrade.build(src, tmp_path / "a", seed="5h-2")
    degrade.build(src, tmp_path / "b", seed="5h-2")
    a, b = _files(tmp_path / "a"), _files(tmp_path / "b")
    assert a == b and len(a) == 3 + 6 + 2  # 3 sources + 6 derived + records + receipt
    assert r1["documents"] == {"source": 3, "scan_fair": 3, "scan_poor": 3}
    assert r1["label"] == degrade.LABEL and r1["renderer"] == degrade.renderer()
    out = _lines(tmp_path / "a/records.jsonl")
    by_id = {r["doc_id"]: r for r in recs}
    for d in out:
        data = a[f"corpus/{d['doc_id']}"]
        assert d["source_sha256"] == "sha256:" + hashlib.sha256(data).hexdigest()
        assert d["byte_size"] == len(data) and d["page_count"] == 1
        if "derived_from" not in d:
            assert d == by_id[d["doc_id"]] and data == (src / "corpus" / d["doc_id"]).read_bytes()
            continue
        assert b"CreationDate" not in data and b"ModDate" not in data
        source = next(r for r in recs if r["source_sha256"] == d["derived_from"])
        level = d["degradation"]["level"]
        assert d["doc_id"] == source["doc_id"].replace(".pdf", f"-{level}.pdf")
        assert d["provenance"] == source["provenance"] and d["rights"] == source["rights"]
        assert (d["page_origin"], d["stratum"]) == ("synthetic_degradation", "distorted")
        assert degrade.LABEL in d["notes"] and d["degradation"]["label"] == degrade.LABEL
        key = degrade.page_seed("5h-2", source["source_sha256"], level)
        assert d["degradation"]["page_seed_sha256"] == key
        assert d["degradation"]["parameters"] == degrade.draw(level, key)
    seeds = [d["degradation"]["page_seed_sha256"] for d in out if "degradation" in d]
    assert len(set(seeds)) == 6  # (seed, source sha256, level) -> one seed per derived page
    # the output freezes as one lpc_sec dev manifest: 3 clean + 6 derived
    m = screen_manifest.freeze(out, "s", "lpc_sec", split="dev")
    assert m["counts"]["dev_pages"] == 9
    screen_manifest.verify(m, tmp_path / "a/corpus")  # one corpus root holds every page


def test_a_different_seed_changes_every_derived_file(tmp_path: Path) -> None:
    src, _ = _profile(tmp_path, n=2)
    degrade.build(src, tmp_path / "a", seed="one")
    degrade.build(src, tmp_path / "b", seed="two")
    a, b = _files(tmp_path / "a"), _files(tmp_path / "b")
    derived = [k for k in a if k.startswith("corpus/") and "-scan_" in k]
    assert len(derived) == 4 and all(a[k] != b[k] for k in derived)
    assert all(a[k] == b[k] for k in a if k.startswith("corpus/") and k not in derived)


def test_parameters_stay_inside_each_level() -> None:
    for i in range(200):
        fair = degrade.draw("scan_fair", f"k{i}")
        poor = degrade.draw("scan_poor", f"k{i}")
        assert set(fair) == {"dpi", "jpeg_quality", "skew_deg"}
        assert (fair["dpi"], fair["jpeg_quality"]) == (150, 60) and abs(fair["skew_deg"]) <= 1.0
        assert (poor["dpi"], poor["jpeg_quality"]) == (100, 35) and abs(poor["skew_deg"]) <= 2.5
        assert 0.6 <= poor["blur_radius"] <= 1.2 and 0.6 <= poor["contrast"] <= 0.8
        assert isinstance(poor["noise_amplitude"], int) and 10 <= poor["noise_amplitude"] <= 24
    skews = {degrade.draw("scan_poor", f"k{i}")["skew_deg"] for i in range(200)}
    assert min(skews) < -1.5 and max(skews) > 1.5  # the draw spans the range, both signs


def test_every_drawn_parameter_is_applied_and_the_page_keeps_its_size() -> None:
    src = _pdf("Total revenue 1000")
    p = degrade.draw("scan_poor", "k")
    base = degrade.degrade_pdf(src, p, "k")
    for name, other in (
        ("skew_deg", 0.0),
        ("blur_radius", None),
        ("noise_amplitude", None),
        ("contrast", None),
        ("jpeg_quality", 95),
        ("dpi", 150),
    ):
        q = {k: v for k, v in p.items() if k != name}
        if other is not None:
            q[name] = other
        assert degrade.degrade_pdf(src, q, "k") != base, name
    assert degrade.degrade_pdf(src, p, "other-key") != base  # the noise follows the page seed
    for level in LEVELS:
        doc = pdfium.PdfDocument(degrade.degrade_pdf(src, degrade.draw(level, "k"), "k"))
        w, h = doc[0].get_size()  # 300 x 200 pt source, grown only by the skew
        assert 300 <= w <= 312 and 200 <= h <= 215, (level, w, h)


def test_derived_pages_have_no_text_layer(tmp_path: Path) -> None:
    src, recs = _profile(tmp_path, n=1)
    assert "Total revenue 1000" in _native_text((src / "corpus" / recs[0]["doc_id"]).read_bytes())
    degrade.build(src, tmp_path / "out", seed="s")
    derived = sorted((tmp_path / "out/corpus").glob("*-scan_*.pdf"))
    assert len(derived) == 2
    for p in derived:
        assert _native_text(p.read_bytes()).strip() == ""


def test_a_page_that_keeps_text_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    class Leaky:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.pages = [type("P", (), {"extract_text": lambda self: "Total revenue 1000"})()]

    monkeypatch.setattr(degrade, "PdfReader", Leaky)
    p = degrade.draw("scan_fair", "k")
    with pytest.raises(degrade.DegradeError, match="text layer"):
        degrade.degrade_pdf(_pdf("x"), p, "k")


def _sealed(path: Path, recs: list[dict[str, Any]]) -> dict[str, int]:
    """Synthetic sealed gold: 2-4 critical fields per page. Returns fields per source doc."""
    rows, fields = [], {}
    for i, r in enumerate(recs):
        k = 2 + i % 3
        fields[r["doc_id"]] = k
        cf = [
            {"field_id": f"f{j}", "kind": "amount", "value": str(7 * j + i), "anchor": f"L{j}"}
            for j in range(k)
        ]
        rows.append({"page_id": f"{r['doc_id']}#0", "truth": {"critical_fields": cf}})
    path.write_text(
        "".join(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n" for x in rows), "utf-8"
    )
    return fields


def _write_manifest(path: Path, docs: list[dict[str, Any]]) -> Path:
    body = {"profile": "lpc_sec", "salt": "s", "counts": {}, "documents": docs}
    path.write_text(json.dumps({**body, "manifest_sha256": canonical_sha256(body)}), "utf-8")
    return path


def test_gold_rows_per_level_equal_the_source_and_no_value_is_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src, recs = _profile(tmp_path)
    degrade.build(src, tmp_path / "out", seed="s")
    m = screen_manifest.freeze(_lines(tmp_path / "out/records.jsonl"), "s", "lpc_sec", split="dev")
    mpath = tmp_path / "m.json"
    mpath.write_text(json.dumps(m), "utf-8")
    sealed = src / "gold.sealed.jsonl"
    fields = _sealed(sealed, recs)
    source_rows = {g["page_id"].split("#")[0]: g for g in _lines(sealed)}
    rec = sec_screen.split_gold(mpath, sealed)
    assert capsys.readouterr() == ("", "")
    dev = _lines(src / "gold.dev.jsonl")
    assert len(dev) == 9 and _lines(src / "gold.holdout.jsonl") == []
    assert sorted(g["page_id"] for g in dev) == sorted(f"{d['doc_id']}#0" for d in m["documents"])
    for g in dev:
        doc_id = g["page_id"].split("#")[0]
        d = next(x for x in m["documents"] if x["doc_id"] == doc_id)
        by_sha = {x["source_sha256"]: x["doc_id"] for x in recs}
        src_id = by_sha[d["derived_from"]] if "derived_from" in d else doc_id
        assert g["truth"] == source_rows[src_id]["truth"]  # carried unchanged
    total = sum(fields.values())
    assert rec["gold_rows_by_level"]["dev"] == {
        f"{lv}.{k}": v
        for lv in ("scan_fair", "scan_poor", "source")
        for k, v in (("critical_fields", total), ("pages", 3))
    }
    assert rec["gold_rows_by_level"]["holdout"] == {}
    assert rec["derived_pages"] == sec_screen.DERIVED_NOTE and not sealed.exists()


def test_a_derived_page_whose_source_is_not_in_the_manifest_is_refused(tmp_path: Path) -> None:
    src, recs = _profile(tmp_path, n=2)
    degrade.build(src, tmp_path / "out", seed="s")
    docs = [dict(d, split="dev") for d in _lines(tmp_path / "out/records.jsonl")]
    sealed = src / "gold.sealed.jsonl"
    _sealed(sealed, recs)
    orphaned = [d for d in docs if d["doc_id"] != recs[0]["doc_id"]]
    with pytest.raises(ContractError):  # freeze refuses it too (WO-D02-3A)
        screen_manifest.freeze(orphaned, "s", "lpc_sec", split="dev")
    with pytest.raises(sec_screen.ScreenError, match="source page is not in the manifest"):
        sec_screen.split_gold(_write_manifest(tmp_path / "m1.json", orphaned), sealed)
    moved = [dict(d, split="holdout") if d.get("derived_from") else d for d in docs]
    with pytest.raises(sec_screen.ScreenError, match="same split"):
        sec_screen.split_gold(_write_manifest(tmp_path / "m2.json", moved), sealed)
    assert sealed.exists() and not (src / "gold.dev.jsonl").exists()


def test_inputs_that_are_not_clean_matching_one_page_sources_are_refused(tmp_path: Path) -> None:
    src, recs = _profile(tmp_path, n=1)
    with pytest.raises(degrade.DegradeError, match="seed"):
        degrade.build(src, tmp_path / "o0", seed=" ")
    with pytest.raises(degrade.DegradeError, match="levels"):
        degrade.build(src, tmp_path / "o1", seed="s", levels=("scan_awful",))
    (tmp_path / "exists").mkdir()
    with pytest.raises(degrade.DegradeError, match="write-once"):
        degrade.build(src, tmp_path / "exists", seed="s")
    for change, match in (
        ({"derived_from": recs[0]["source_sha256"]}, "clean one-page"),
        ({"page_count": 2}, "clean one-page"),
        ({"byte_size": recs[0]["byte_size"] + 1}, "do not match"),
        ({"doc_id": "../escape.pdf"}, "plain file name"),
    ):
        bad = tmp_path / f"bad{len(match)}{len(change)}{next(iter(change))}"
        (bad / "corpus").mkdir(parents=True)
        (bad / "corpus" / recs[0]["doc_id"]).write_bytes(
            (src / "corpus" / recs[0]["doc_id"]).read_bytes()
        )
        (bad / "records.jsonl").write_text(json.dumps({**recs[0], **change}) + "\n", "utf-8")
        with pytest.raises((degrade.DegradeError, ValueError), match=match):
            degrade.build(bad, tmp_path / f"o-{bad.name}", seed="s")
    with pytest.raises(degrade.DegradeError, match="git work tree"):
        degrade.build(src, Path(__file__).parent / "never-written", seed="s")
    assert not (Path(__file__).parent / "never-written").exists()
    clash = tmp_path / "clash"  # a source named like another source's derived page
    (clash / "corpus").mkdir(parents=True)
    named = []
    for name in ("sec-0000-scan_fair.pdf", "sec-0000.pdf"):
        data = _pdf(name)
        named.append(_sec(len(named), data=data) | {"doc_id": name})
        (clash / "corpus" / name).write_bytes(data)
    (clash / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in named), "utf-8")
    with pytest.raises(FileExistsError):
        degrade.build(clash, tmp_path / "o-clash", seed="s", levels=("scan_fair",))
    with pytest.raises(degrade.DegradeError, match="one-page sources only"):
        degrade.degrade_pdf(_pdf("a", "b"), degrade.draw("scan_fair", "k"), "k")


def test_command_line_writes_once_and_takes_levels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src, _ = _profile(tmp_path, n=1)
    args = ["--profile-dir", str(src), "--out", str(tmp_path / "o"), "--seed", "s"]
    assert degrade.main([*args, "--levels", "scan_poor"]) == 0
    assert json.loads(capsys.readouterr().out)["documents"] == {"source": 1, "scan_poor": 1}
    assert degrade.main(args) == 1
    assert "write-once" in capsys.readouterr().err


# ---------------------------------------------------------------- round 2 (lead A, B, C)


def test_level_names_are_the_manifest_rule() -> None:
    assert tuple(degrade.LEVELS) == screen_manifest.DERIVED_LEVELS


def _dev_docs() -> list[dict[str, Any]]:
    return [dict(d, split="dev") for d in _sec_set(0, n=2, derived=True)]


def test_split_gold_never_defaults_a_level(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases: list[Any] = [
        lambda ds: ds[2].pop("degradation"),
        lambda ds: ds[2]["degradation"].pop("level"),
        lambda ds: ds[2]["degradation"].update(level="scan_awful"),
        lambda ds: ds[2].update(degradation=None),
        lambda ds: ds[0].update(degradation={"level": "scan_fair"}),
    ]
    for i, mutate in enumerate(cases):
        docs = _dev_docs()
        mutate(docs)
        sealed = tmp_path / "gold.sealed.jsonl"
        _sealed(sealed, docs[:2])
        manifest = _write_manifest(tmp_path / f"m{i}.json", docs)
        with pytest.raises(ContractError, match="degradation"):
            sec_screen.split_gold(manifest, sealed)
        assert sealed.exists() and not (tmp_path / "gold.dev.jsonl").exists()
        assert sec_screen.main(["split-gold", "--manifest", str(manifest), "--gold", str(sealed)])
        assert capsys.readouterr().err.startswith("REFUSED: ContractError")
    # the reviewer's probe P1: a real degrade output with `degradation` removed
    src, recs = _profile(tmp_path / "p1", n=2)
    degrade.build(src, tmp_path / "p1/out", seed="s")
    stripped = [
        {k: v for k, v in d.items() if k != "degradation"}
        for d in _lines(tmp_path / "p1/out/records.jsonl")
    ]
    with pytest.raises(ContractError, match=r"degradation\.level"):
        screen_manifest.freeze(stripped, "s", "lpc_sec", split="dev")
    _sealed(src / "gold.sealed.jsonl", recs)
    with pytest.raises(ContractError, match=r"degradation\.level"):
        sec_screen.split_gold(
            _write_manifest(tmp_path / "p1.json", [dict(d, split="dev") for d in stripped]),
            src / "gold.sealed.jsonl",
        )


def test_split_gold_fuzz_refuses_with_its_own_errors_and_counts_only_validated_levels(
    tmp_path: Path,
) -> None:
    """Each field of a source page and of a derived page, set to each wrong-typed value or
    deleted: split_gold's manifest side (``split_documents``) refuses with ScreenError or
    ContractError (nothing else escapes) or gives a validated level to every SEC page.
    Accepted cases run end to end: rows land only under validated levels, one page row per SEC
    page, and a refusal writes nothing."""
    base = _dev_docs()
    levels = {"source", *screen_manifest.DERIVED_LEVELS}
    refused, accepted = 0, []
    for which in (0, 2):
        for path in field_paths(base[which]):
            for value in (*WRONG, mutated):
                docs = mutated(base, which, path, value)
                try:
                    mine, level_of, source_of = sec_screen.split_documents(docs)
                except (sec_screen.ScreenError, ContractError):
                    refused += 1
                    continue
                assert set(level_of) == set(mine) and set(level_of.values()) <= levels
                assert all(level_of[d] != "source" for d in source_of)
                accepted.append(docs)
    assert refused > 300 and accepted
    twin = [*base, dict(base[0], source_sha256="sha256:" + "d" * 64)]  # same doc_id twice
    with pytest.raises(ContractError, match="duplicate doc_id"):
        sec_screen.split_documents(twin)
    for i, docs in enumerate(accepted[::7]):  # end to end on a spread of the accepted cases
        case = tmp_path / f"c{i}"
        case.mkdir()
        sealed = case / "gold.sealed.jsonl"
        _sealed(sealed, base[:2])
        try:
            rec = sec_screen.split_gold(_write_manifest(case / "m.json", docs), sealed)
        except sec_screen.ScreenError:  # e.g. a renamed source no longer matches its gold
            assert sealed.exists() and not (case / "gold.dev.jsonl").exists()
            continue
        by = rec["gold_rows_by_level"]["dev"]
        assert {k.split(".")[0] for k in by} <= levels
        sec = [d for d in docs if isinstance(p := d.get("provenance"), dict) and "adsh" in p]
        assert sum(v for k, v in by.items() if k.endswith(".pages")) == len(sec)
    for i, row in enumerate(
        (
            "5",
            '"x"',
            '{"page_id": 5, "truth": {"critical_fields": []}}',
            '{"page_id": "sec-0000.pdf", "truth": {"critical_fields": []}}',
            '{"page_id": "sec-0000.pdf#a", "truth": {"critical_fields": []}}',
            '{"page_id": "sec-0000.pdf#0"}',
            '{"page_id": "sec-0000.pdf#0", "truth": {"critical_fields": 5}}',
        )
    ):
        case = tmp_path / f"g{i}"
        case.mkdir()
        sealed = case / "gold.sealed.jsonl"
        _sealed(sealed, base[:2])
        lines = sealed.read_text("utf-8").splitlines()
        sealed.write_text("\n".join([row, *lines[1:]]) + "\n", "utf-8")
        with pytest.raises(sec_screen.ScreenError, match="gold row"):
            sec_screen.split_gold(_write_manifest(case / "m.json", base), sealed)
        assert sealed.exists() and not (case / "gold.dev.jsonl").exists()
    with pytest.raises((sec_screen.ScreenError, ContractError)):
        sec_screen.split_gold(_write_manifest(tmp_path / "x.json", [*base, 5]), sealed)


def test_a_refusal_leaves_nothing_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src, recs = _profile(tmp_path, n=3)
    good = (src / "records.jsonl").read_text("utf-8")

    def left() -> list[str]:
        return sorted(p.name for p in tmp_path.iterdir())

    before = left()
    rendered: list[int] = []
    real = degrade.degrade_pdf

    def counting(*a: Any) -> bytes:
        rendered.append(1)
        return real(*a)

    monkeypatch.setattr(degrade, "degrade_pdf", counting)
    last = dict(recs[-1], byte_size=recs[-1]["byte_size"] + 1)
    (src / "records.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in [*recs[:-1], last]), "utf-8"
    )
    with pytest.raises(degrade.DegradeError, match="do not match"):
        degrade.build(src, tmp_path / "out", seed="s")
    assert rendered == [] and left() == before  # every source verified before any write
    (tmp_path / "taken").mkdir()
    with pytest.raises(degrade.DegradeError, match="write-once"):
        degrade.build(src, tmp_path / "taken", seed="s")
    assert rendered == [] and not any((tmp_path / "taken").iterdir())
    (tmp_path / "taken").rmdir()
    (src / "records.jsonl").write_text(good, "utf-8")

    def flaky(*a: Any) -> bytes:
        rendered.append(1)
        if len(rendered) == 4:
            raise degrade.DegradeError("render failed")
        return real(*a)

    monkeypatch.setattr(degrade, "degrade_pdf", flaky)
    with pytest.raises(degrade.DegradeError, match="render failed"):
        degrade.build(src, tmp_path / "out", seed="s")
    assert left() == before
    monkeypatch.setattr(degrade, "degrade_pdf", real)
    real_write = degrade._write_once

    def corrupt(path: Path, data: bytes) -> None:
        real_write(path, data[:-1] + b"X" if path.name == recs[1]["doc_id"] else data)

    monkeypatch.setattr(degrade, "_write_once", corrupt)
    with pytest.raises(degrade.DegradeError, match="after the copy"):
        degrade.build(src, tmp_path / "out", seed="s")
    assert left() == before
    monkeypatch.undo()
    with pytest.raises(degrade.DegradeError, match="does not exist"):
        degrade.build(src, tmp_path / "missing" / "out", seed="s")
    assert left() == before
    degrade.build(src, tmp_path / "out", seed="s")
    assert left() == sorted([*before, "out"])
    tagged = dict(recs[0], degradation={"level": "scan_fair"})  # a source must be clean
    (src / "records.jsonl").write_text(json.dumps(tagged) + "\n", "utf-8")
    with pytest.raises(degrade.DegradeError, match="clean one-page"):
        degrade.build(src, tmp_path / "out2", seed="s")
    assert left() == sorted([*before, "out"])


def test_an_oversized_or_unreadable_page_is_refused_before_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for box in (b"0 0 612 792", b"0 0 1224 200", b"0 0 200 1224"):  # Letter; at the bound
        degrade.check_source(_pdf("x", box=box), "x")

    def no_render(*_: Any, **__: Any) -> Any:
        raise AssertionError("rendered")

    monkeypatch.setattr(pdfium.PdfPage, "render", no_render)
    p = degrade.draw("scan_fair", "k")
    for box in (b"0 0 1300 200", b"0 0 200 1300", b"0 0 14400 14400"):
        with pytest.raises(degrade.DegradeError, match="page size"):
            degrade.degrade_pdf(_pdf("x", box=box), p, "k")
    with pytest.raises(degrade.DegradeError, match="not a readable PDF"):
        degrade.degrade_pdf(b"%PDF-1.4 not really", p, "k")
    root = tmp_path / "big"
    (root / "corpus").mkdir(parents=True)
    recs = []
    for i, data in enumerate((_pdf("a"), _pdf("b", box=b"0 0 1300 200"))):
        recs.append(_sec(i, data=data))
        (root / "corpus" / recs[-1]["doc_id"]).write_bytes(data)
    (root / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), "utf-8")
    with pytest.raises(degrade.DegradeError, match="page size"):
        degrade.build(root, tmp_path / "o", seed="s")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["big"]
