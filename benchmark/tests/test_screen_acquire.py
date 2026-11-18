from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
import yaml

from benchmark.screen import acquire as acq

SCREEN = Path(acq.__file__).parent
LICENCE = b"<html>US federal public information</html>"
DOC = b"%PDF-1.4 filing"
DOC_URL = "https://www.sec.gov/Archives/a.pdf"
LICENCE_URL = "https://www.sec.gov/about/privacy-information#copyright"


def _csv(tmp_path: Path, *rows: tuple[str, str, str]) -> Path:
    p = tmp_path / "urls.csv"
    p.write_text(
        "url,source_family,licence\n" + "".join(",".join(r) + "\n" for r in rows), encoding="utf-8"
    )
    return p


def _client(handler, sleeps: list[float] | None = None) -> acq.PacedClient:
    return acq.PacedClient(
        "TAVONEL-test/1.0 (+test)",
        transport=httpx.MockTransport(handler),
        min_interval_s=0,
        sleep=(sleeps if sleeps is not None else []).append,
    )


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=LICENCE if "privacy" in request.url.path else DOC)


ROW = (DOC_URL, "sec_edgar", "SEC-WEBSITE-POLICY")


def test_strata_targets_sum_and_korean_share() -> None:
    strata = yaml.safe_load((SCREEN / "strata.yaml").read_text(encoding="utf-8"))["strata"]
    assert len(strata) == 9
    for split, total in (("dev_pages", 300), ("holdout_pages", 100)):
        assert sum(s[split] for s in strata) == total
        assert sum(s[split] for s in strata if s["language"] == "ko") * 2 >= total


def test_sources_exclude_research_only_sets() -> None:
    fams = acq.load_families()
    assert not {"omnidocbench", "olmocr_bench"} & set(fams)
    assert {f["rights_class"] for f in fams.values()} <= {
        "owned",
        "public_domain",
        "public_record",
        "permissive_licence",
        "synthetic",
    }


def test_acquire_records_rights_fields(tmp_path: Path) -> None:
    out = tmp_path / "rights.jsonl"
    recs = acq.acquire(_csv(tmp_path, ROW), tmp_path / "corpus", out, _client(_ok), recorded_by="t")
    sha = hashlib.sha256(DOC).hexdigest()
    assert (tmp_path / "corpus" / "docs" / f"{sha}.pdf").read_bytes() == DOC
    rights = json.loads(out.read_text(encoding="utf-8"))["rights"]
    assert recs[0]["source_sha256"] == f"sha256:{sha}" and recs[0]["byte_size"] == len(DOC)
    assert rights["licence_snapshot_sha256"] == "sha256:" + hashlib.sha256(LICENCE).hexdigest()
    assert rights["rights_class"] == "public_record"
    assert rights["licence_id"] == "SEC-WEBSITE-POLICY"


def test_unknown_family_refused_before_any_request(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _ok(request)

    with pytest.raises(acq.AcquireError, match="allowlist"):
        acq.acquire(
            _csv(tmp_path, ROW, ("https://x.org/o.pdf", "omnidocbench", "CC-BY-4.0")),
            tmp_path / "c",
            tmp_path / "o.jsonl",
            _client(handler),
            recorded_by="t",
        )
    assert calls == []


def test_host_and_licence_must_match_family(tmp_path: Path) -> None:
    for row in (
        ("https://evil.example/a.pdf", "sec_edgar", "SEC-WEBSITE-POLICY"),
        (DOC_URL, "sec_edgar", "CC-BY-4.0"),
        (DOC_URL, "sec_edgar", "US-FED-PUBLIC"),
        ("http://www.sec.gov/a.pdf", "sec_edgar", "SEC-WEBSITE-POLICY"),
        ("https://x/a", "founder_owned", "OWNED-FOUNDER"),
    ):
        with pytest.raises(acq.AcquireError):
            acq.acquire(
                _csv(tmp_path, row),
                tmp_path / "c",
                tmp_path / "o.jsonl",
                _client(_ok),
                recorded_by="t",
            )


def test_missing_licence_snapshot_refused_and_no_document_written(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404)
            if "privacy" in request.url.path
            else httpx.Response(200, content=DOC)
        )

    with pytest.raises(acq.AcquireError, match="404"):
        acq.acquire(
            _csv(tmp_path, ROW),
            tmp_path / "c",
            tmp_path / "o.jsonl",
            _client(handler),
            recorded_by="t",
        )
    assert not list((tmp_path / "c" / "docs").iterdir())
    assert not (tmp_path / "o.jsonl").exists()


def test_corpus_root_inside_repo_refused(tmp_path: Path) -> None:
    with pytest.raises(acq.AcquireError, match="outside the repository"):
        acq.acquire(
            _csv(tmp_path, ROW),
            acq.REPO_ROOT / "benchmark" / "corpus_tmp",
            tmp_path / "o.jsonl",
            _client(_ok),
            recorded_by="t",
        )
    assert not (acq.REPO_ROOT / "benchmark" / "corpus_tmp").exists()


def test_retry_after_honoured(tmp_path: Path) -> None:
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "privacy" not in request.url.path:
            hits["n"] += 1
            if hits["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "7"})
        return _ok(request)

    sleeps: list[float] = []
    recs = acq.acquire(
        _csv(tmp_path, ROW),
        tmp_path / "c",
        tmp_path / "o.jsonl",
        _client(handler, sleeps),
        recorded_by="t",
    )
    assert len(recs) == 1 and hits["n"] == 2 and 7.0 in sleeps


def test_retry_after_beyond_cap_gives_up(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "86400"})

    with pytest.raises(acq.AcquireError, match="giving up"):
        _client(handler).get(DOC_URL)


def test_user_agent_required_and_sent() -> None:
    with pytest.raises(acq.AcquireError):
        acq.PacedClient("  ")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, content=b"x")

    _client(handler).get(DOC_URL)
    assert seen == ["TAVONEL-test/1.0 (+test)"]


@pytest.mark.skipif(
    not (SCREEN / "manifest.py").exists(), reason="WO-D02-1 screen manifest not merged yet"
)
def test_output_matches_manifest_schema(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (SCREEN.parent / "schemas" / "screen-manifest.schema.json").read_text(encoding="utf-8")
    )
    rec = acq.acquire(
        _csv(tmp_path, ROW), tmp_path / "c", tmp_path / "o.jsonl", _client(_ok), recorded_by="t"
    )[0]
    props = schema["properties"]["documents"]["items"]["properties"]
    jsonschema.validate(rec["rights"], props["rights"])
    jsonschema.validate(rec["source_sha256"], props["source_sha256"])


def test_digests_prefixed_and_redistribution_boolean(tmp_path: Path) -> None:
    rec = acq.acquire(
        _csv(tmp_path, ROW), tmp_path / "c", tmp_path / "o.jsonl", _client(_ok), recorded_by="t"
    )[0]
    assert rec["source_sha256"] == "sha256:" + hashlib.sha256(DOC).hexdigest()
    snap = "sha256:" + hashlib.sha256(LICENCE).hexdigest()
    assert rec["rights"]["licence_snapshot_sha256"] == snap
    assert rec["rights"]["redistribution"] is False


def _arxiv(abs_body: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=abs_body if "/abs/" in request.url.path else DOC)

    return handler


ARXIV_ROW = ("https://arxiv.org/pdf/2401.00001.pdf", "arxiv_cc_by", "CC-BY-4.0")


def test_arxiv_snapshot_is_the_paper_abs_page(tmp_path: Path) -> None:
    page = b'<a href="http://creativecommons.org/licenses/by/4.0/">license</a>'
    rec = acq.acquire(
        _csv(tmp_path, ARXIV_ROW),
        tmp_path / "c",
        tmp_path / "o.jsonl",
        _client(_arxiv(page)),
        recorded_by="t",
    )[0]
    assert rec["rights"]["licence_snapshot_sha256"] == "sha256:" + hashlib.sha256(page).hexdigest()


def test_arxiv_without_cc_by_link_refused(tmp_path: Path) -> None:
    page = b'<a href="http://arxiv.org/licenses/nonexclusive-distrib/1.0/">license</a>'
    with pytest.raises(acq.AcquireError, match="does not link"):
        acq.acquire(
            _csv(tmp_path, ARXIV_ROW),
            tmp_path / "c",
            tmp_path / "o.jsonl",
            _client(_arxiv(page)),
            recorded_by="t",
        )


def test_empty_recorded_by_refused(tmp_path: Path) -> None:
    with pytest.raises(acq.AcquireError, match="recorded_by"):
        acq.acquire(
            _csv(tmp_path, ROW), tmp_path / "c", tmp_path / "o.jsonl", _client(_ok), recorded_by=" "
        )


def test_cli_refuses_unlisted_family(tmp_path: Path) -> None:
    bad = _csv(tmp_path, ("https://x.example/a.pdf", "nope", "X"))
    argv = ["--csv", str(bad), "--corpus-root", str(tmp_path / "c")]
    argv += ["--out", str(tmp_path / "o.jsonl"), "--user-agent", "ua", "--recorded-by", "t"]
    assert acq.main(argv) == 1
    assert not (tmp_path / "o.jsonl").exists()
