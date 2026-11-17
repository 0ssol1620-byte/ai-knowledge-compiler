from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchmark.local_public import sources as S


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    src = tmp_path / "src"
    fsds = src / "cache/sec_fsds_official"
    c2 = src / "raw/v401_text/C2_edgar_docs"
    (c2 / "docs/1").mkdir(parents=True)
    fsds.mkdir(parents=True)
    zbytes = b"PK-fake-zip"
    (fsds / "2024q1.zip").write_bytes(zbytes)
    (fsds / "manifest.json").write_text(
        json.dumps(
            {"files": [{"quarter": "2024q1", "url": "https://x/2024q1.zip", "sha256": _h(zbytes)}]}
        )
    )
    html = b"<html>filing</html>"
    (c2 / "docs/1/0000000001-24-000001.html.gz").write_bytes(gzip.compress(html))
    (c2 / "manifest.jsonl").write_text(
        json.dumps(
            {
                "adsh": "0000000001-24-000001",
                "cik": 1,
                "url": "https://x/f.htm",
                "sha256": _h(html),
                "path": "docs/1/0000000001-24-000001.html.gz",
            }
        )
        + "\n"
    )
    (c2 / "index.jsonl").write_text("{}\n")
    (src / "raw/sec_submissions_20260816.zip").write_bytes(b"bulk")
    lic = tmp_path / "licences"
    lic.mkdir()
    terms = b"<html>terms</html>"
    (lic / f"{_h(terms)}.html").write_bytes(terms)
    (lic / "terms.json").write_text(
        json.dumps(
            [
                {
                    "source_id": "sec",
                    "url": "https://sec/t",
                    "fetched_at": "2026-11-16T00:00:00+00:00",
                    "sha256": _h(terms),
                    "http_status": 200,
                }
            ]
        )
    )
    return {
        "src": src,
        "terms": lic / "terms.json",
        "out": tmp_path / "out/m.json",
        "zip": fsds / "2024q1.zip",
        "gz": c2 / "docs/1/0000000001-24-000001.html.gz",
        "root": tmp_path,
    }


def _build(t: dict[str, Path], **kw: object) -> dict[str, Any]:
    return S.build(t["src"], t["out"], t["terms"], **kw)  # type: ignore[arg-type]


def test_round_trip_and_cli(tree: dict[str, Path]) -> None:
    m = _build(tree)
    assert {e["name"] for e in m["entries"]} >= {
        "sec_fsds/2024q1",
        "sec_filing/0000000001-24-000001",
        "sec_submissions_bulk",
        "terms/sec",
    }
    lo = S.Loader(tree["out"])
    with lo.open_verified("sec_fsds/2024q1") as f:
        assert f.read() == b"PK-fake-zip"
    assert lo.ledger.consumed[0]["name"] == "sec_fsds/2024q1"
    assert S.main(["verify", "--manifest", str(tree["out"])]) == 0


def test_missing_and_one_byte_change(tree: dict[str, Path]) -> None:
    _build(tree)
    lo = S.Loader(tree["out"])
    data = tree["zip"].read_bytes()
    tree["zip"].write_bytes(data[:-1] + b"X")
    with pytest.raises(S.HashMismatch):
        lo.open_verified("sec_fsds/2024q1")
    tree["zip"].unlink()
    with pytest.raises(S.SourceMissing):
        lo.open_verified("sec_fsds/2024q1")
    assert S.main(["verify", "--manifest", str(tree["out"])]) == 1


def test_fsds_hash_vs_collector_refused(tree: dict[str, Path]) -> None:
    tree["zip"].write_bytes(b"changed after collection")
    with pytest.raises(S.HashMismatch):
        _build(tree)


def test_gz_content_hash_vs_c2_manifest_refused(tree: dict[str, Path]) -> None:
    tree["gz"].write_bytes(gzip.compress(b"<html>other</html>"))
    with pytest.raises(S.HashMismatch):
        _build(tree)


def test_missing_terms_refused(tree: dict[str, Path]) -> None:
    tree["terms"].unlink()
    with pytest.raises(S.SourceMissing):
        _build(tree)


@pytest.mark.parametrize(
    "name",
    [
        "raw/v401_text/C2_edgar_docs/index.jsonl",
        "raw/v401_text/C2_edgar_docs/submissions/x.json",
        "raw/v401_text/C2_edgar_docs/hdr/x.sgml",
        "raw/sec_facts.csv.gz",
        "alfred_series/VIXCLS",
        "alfred_vintages",
        "alfred_vintages_metadata",
    ],
)
def test_excluded_names(tree: dict[str, Path], name: str) -> None:
    _build(tree)
    with pytest.raises(S.ExcludedSource):
        S.Loader(tree["out"]).open_verified(name)


def test_unknown_name_refused(tree: dict[str, Path]) -> None:
    _build(tree)
    with pytest.raises(S.SourceMissing):
        S.Loader(tree["out"]).open_verified("sec_fsds/1999q1")


def test_output_inside_git_tree_refused(tree: dict[str, Path]) -> None:
    (tree["root"] / "repo/.git").mkdir(parents=True)
    with pytest.raises(S.SourceError):
        S.build(tree["src"], tree["root"] / "repo/sub/m.json", tree["terms"])


def test_tampered_manifest_refused(tree: dict[str, Path]) -> None:
    _build(tree)
    m = json.loads(tree["out"].read_text())
    m["entries"][0]["sha256"] = "0" * 64
    tree["out"].write_text(json.dumps(m))
    with pytest.raises(S.HashMismatch):
        S.Loader(tree["out"])


def test_receipt_verify_and_changed_input(tree: dict[str, Path]) -> None:
    _build(tree)
    lo = S.Loader(tree["out"])
    lo.verified_path("sec_submissions_bulk")
    out = tree["root"] / "derived.json"
    out.write_text("{}")
    rec = S.receipt(lo.ledger, [out], ["stmt"])
    assert rec["lpc_manifest_sha256"] == lo.manifest["manifest_sha256"]
    run, audit = tree["root"] / "run", tree["root"] / "audit"
    path = S.write_receipt(rec, run, audit)
    assert (audit / "receipt.json").read_bytes() == path.read_bytes()
    S.verify_receipt(path, tree["out"])
    assert S.main(["verify", "--manifest", str(tree["out"]), "--receipt", str(path)]) == 0
    (tree["src"] / "raw/sec_submissions_20260816.zip").write_bytes(b"BULK")
    with pytest.raises(S.HashMismatch):
        S.verify_receipt(path, tree["out"])


def test_receipt_output_changed(tree: dict[str, Path]) -> None:
    _build(tree)
    lo = S.Loader(tree["out"])
    out = tree["root"] / "derived.json"
    out.write_text("{}")
    path = S.write_receipt(S.receipt(lo.ledger, [out], []), tree["root"] / "run")
    out.write_text("{ }")
    with pytest.raises(S.HashMismatch):
        S.verify_receipt(path, tree["out"])


def test_verified_path_tampered_renderer(tree: dict[str, Path]) -> None:
    exe = tree["root"] / "chrome-headless-shell.exe"
    exe.write_bytes(b"exe")
    _build(tree, renderer=exe, renderer_version="149.0.7827.55", renderer_licence_sha256="a" * 64)
    lo = S.Loader(tree["out"])
    assert lo.verified_path("tool/chrome-headless-shell") == exe.resolve()
    exe.write_bytes(b"evil")
    with pytest.raises(S.HashMismatch):
        lo.verified_path("tool/chrome-headless-shell")


def test_receipt_never_overwritten(tree: dict[str, Path]) -> None:
    _build(tree)
    lo = S.Loader(tree["out"])
    run, audit = tree["root"] / "run", tree["root"] / "audit"
    first = S.write_receipt(S.receipt(lo.ledger, [], ["first"]), run, audit)
    before = (first.read_bytes(), (audit / "receipt.json").read_bytes())
    with pytest.raises(S.SourceError):
        S.write_receipt(S.receipt(lo.ledger, [], ["second"]), run, audit)
    with pytest.raises(S.SourceError):  # fresh run dir, existing audit copy
        S.write_receipt(S.receipt(lo.ledger, [], ["third"]), tree["root"] / "run2", audit)
    assert (first.read_bytes(), (audit / "receipt.json").read_bytes()) == before
    assert not (tree["root"] / "run2" / "receipt.json").exists()


def test_denied_alfred_contributes_no_file_digest_or_row(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tree["src"] / "raw/alfred_vintages.csv.gz").write_bytes(b"alfred-csv")
    (tree["src"] / "raw/alfred_vintages.metadata.json").write_text("{}")
    real = S._sha256_file

    def guarded(path: Path) -> tuple[str, int]:
        if path.name.lower().startswith("alfred"):
            raise AssertionError(f"ALFRED path touched: {path}")
        return real(path)

    monkeypatch.setattr(S, "_sha256_file", guarded)
    m = _build(tree)
    assert not [e for e in m["entries"] if "alfred" in e["name"]]
    assert m["alfred"] == S.ALFRED_DENIED_STATEMENT and "denied" in m["alfred"]
    by = {e["name"]: e for e in m["entries"]}
    assert by["sec_fsds/2024q1"]["sha256"] == _h(b"PK-fake-zip")
    assert by["sec_submissions_bulk"]["sha256"] == _h(b"bulk")
    assert by["sec_filing/0000000001-24-000001"]["content_sha256"] == _h(b"<html>filing</html>")
    with pytest.raises(S.ExcludedSource):
        S.Loader(tree["out"]).verified_path("alfred_vintages")


def test_stale_manifest_with_alfred_entries_refused_nothing_opened(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _build(tree)
    m = json.loads(tree["out"].read_text())
    alf = tree["root"] / "alfred.csv"
    alf.write_bytes(b"alfred")
    m["entries"].append(
        {"name": "alfred_vintages", "path": alf.as_posix(), "sha256": _h(b"alfred")}
    )
    m["excluded"] = [x for x in m["excluded"] if "alfred" not in x["pattern"]]
    m["manifest_sha256"] = S._digest({k: v for k, v in m.items() if k != "manifest_sha256"})
    tree["out"].write_text(json.dumps(m))

    def boom(*a: object, **k: object) -> object:
        raise AssertionError("opened or hashed")

    monkeypatch.setattr(S, "_sha256_file", boom)
    lo = S.Loader(tree["out"])
    with pytest.raises(S.ExcludedSource):
        lo.verified_path("alfred_vintages")
    with pytest.raises(S.ExcludedSource, match="rebuild"):
        lo.verified_path("sec_fsds/2024q1")


def test_alfred_terms_rows_are_neither_pinned_nor_hashed(
    tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    page = b"<html>fred page</html>"
    snap = tree["terms"].parent / f"{_h(page)}.html"
    snap.write_bytes(page)
    rows = json.loads(tree["terms"].read_text())
    for sid in ("data_alfred_vintages", "data_alfred_vintages/UNRATE"):
        rows.append(
            {
                "source_id": sid,
                "url": "https://fred.stlouisfed.org/x",
                "fetched_at": "2026-11-16T00:00:00+00:00",
                "sha256": _h(page),
                "http_status": 200,
            }
        )
    tree["terms"].write_text(json.dumps(rows))
    real = S._sha256_file

    def guarded(path: Path) -> tuple[str, int]:
        if path == snap:
            raise AssertionError(f"ALFRED terms snapshot hashed: {path}")
        return real(path)

    monkeypatch.setattr(S, "_sha256_file", guarded)
    m = _build(tree)
    assert not [e for e in m["entries"] if "alfred" in e["name"]]
    assert "terms/sec" in {e["name"] for e in m["entries"]}


def test_loader_refuses_manifest_with_alfred_terms_entry(tree: dict[str, Path]) -> None:
    _build(tree)
    m = json.loads(tree["out"].read_text())
    m["entries"].append(
        {"name": "terms/data_alfred_vintages/UNRATE", "path": "x", "sha256": "0" * 64}
    )
    m["manifest_sha256"] = S._digest({k: v for k, v in m.items() if k != "manifest_sha256"})
    tree["out"].write_text(json.dumps(m))
    with pytest.raises(S.ExcludedSource, match="rebuild"):
        S.Loader(tree["out"]).verified_path("sec_fsds/2024q1")
