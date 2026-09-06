from __future__ import annotations

import json

import pytest

import confirmatory_sec_staging as s
from confirmatory_source_acquisition import SecFiling


def _filing() -> SecFiling:
    return SecFiling(
        cik="320193",
        company="Example Corp",
        form="10-Q",
        filed_date="2026-08-01",
        archive_filename="edgar/data/320193/0000320193-26-000123.txt",
    )


def _submission() -> bytes:
    return b"""<SUBMISSION>
<DOCUMENT>
<TYPE>10-Q
<SEQUENCE>2
<FILENAME>main.htm
<DESCRIPTION>Quarterly report
<TEXT><html><head><link rel='stylesheet' href='style.css'></head><body><img src='logo.png'><div style=\"background:url(bg.png)\">x</div></body></html></TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>GRAPHIC
<SEQUENCE>3
<FILENAME>logo.png
<TEXT>embedded-logo</TEXT>
</DOCUMENT>
</SUBMISSION>"""


def test_parse_submission_documents_and_primary_selection():
    docs = s.parse_submission_documents(_submission())
    assert [row.filename for row in docs] == ["main.htm", "logo.png"]
    primary = s.primary_document(docs, "10-Q")
    assert primary.filename == "main.htm"
    assert primary.sequence == 2


def test_duplicate_submission_filename_is_refused():
    raw = _submission() + b"<DOCUMENT><TYPE>EX-1<SEQUENCE>4<FILENAME>logo.png<TEXT>x</TEXT></DOCUMENT>"
    with pytest.raises(s.SecStagingRefused, match="duplicate SEC document filename"):
        s.parse_submission_documents(raw)


def test_required_assets_include_src_stylesheet_inline_css_and_srcset():
    html = b"""<html><head><link rel='stylesheet' href='a.css'></head><body>
<img src='one.png' srcset='two.png 2x, three.png 3x'>
<div style=\"background-image:url('four.png')\"></div><style>.x{background:url(five.png)}</style>
</body></html>"""
    assert s.required_local_assets(html) == (
        "a.css",
        "five.png",
        "four.png",
        "one.png",
        "three.png",
        "two.png",
    )


def test_external_or_traversal_asset_is_refused():
    with pytest.raises(s.SecStagingRefused, match="external asset"):
        s.required_local_assets(b"<img src='https://tracker.example/x.png'>")
    with pytest.raises(s.SecStagingRefused, match="unsafe SEC asset path"):
        s.required_local_assets(b"<img src='../x.png'>")


def test_archive_url_comes_from_master_index_identity():
    filing = _filing()
    assert s.archive_base_url(filing) == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/"
    )
    assert s.archive_asset_url(filing, "images/a logo.png").endswith("images/a%20logo.png")


def test_render_bundle_requires_every_local_asset_and_uses_embedded_docs(tmp_path):
    with pytest.raises(s.SecStagingRefused, match="missing required local assets"):
        s.build_render_bundle(
            filing=_filing(), submission=_submission(), acquired_assets={}, output_dir=tmp_path / "red"
        )
    bundle = s.build_render_bundle(
        filing=_filing(),
        submission=_submission(),
        acquired_assets={"style.css": b"body{}", "bg.png": b"background"},
        output_dir=tmp_path / "green",
    )
    assert bundle["missing_required_assets"] == []
    assert bundle["external_assets_permitted"] is False
    assert set(bundle["staged_file_sha256"]) == {"main.htm", "style.css", "logo.png", "bg.png"}
    recorded = json.loads((tmp_path / "green" / "render-bundle.json").read_text(encoding="utf-8"))
    assert recorded["render_bundle_digest"] == bundle["render_bundle_digest"]


def test_existing_bundle_directory_is_refused(tmp_path):
    target = tmp_path / "bundle"
    target.mkdir()
    with pytest.raises(s.SecStagingRefused, match="already exists"):
        s.build_render_bundle(
            filing=_filing(), submission=_submission(), acquired_assets={}, output_dir=target
        )