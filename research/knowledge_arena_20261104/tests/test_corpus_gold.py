from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from karena.corpus import (
    Case,
    CorpusError,
    Document,
    Licence,
    assign_split,
    check_split_integrity,
)
from karena.gold import sec
from karena.gold.fetch import Fetcher, FetchError
from karena.gold.htmltext import fact_value, html_to_text, tidy

LICENCE = Licence(
    licence_id="US-GOV-17USC105", basis="b", evidence="api type", source_url="https://x.gov/d"
)


def _case(case_id: str, family: str, split: str | None = None) -> Case:
    return Case(
        case_id=case_id,
        task="doc_type",
        split=split or assign_split(family),  # type: ignore[arg-type]
        family_ids=(family,),
        origin="US_GOV_FR",
        language="en",
        source_doc_ids=(case_id,),
        licences=("US-GOV-17USC105",),
        input={"text": "t"},
        truth={"label": "FR_RULE"},
    )


def test_licence_outside_the_cleared_sources_is_refused() -> None:
    with pytest.raises(CorpusError):
        Licence(licence_id="CC-BY-4.0", basis="b", evidence="e", source_url="https://x/y")
    with pytest.raises(CorpusError):
        Licence(licence_id="KOGL-TYPE-1", basis="b", evidence=" ", source_url="https://x/y")


def test_document_without_licence_record_is_refused() -> None:
    row = Document(
        doc_id="fr:1",
        origin="US_GOV_FR",
        family_id="fr:agency:a",
        label="FR_RULE",
        language="en",
        url="https://x",
        fetched_at="t",
        raw_sha256="sha256:0",
        text="body",
        licence=LICENCE,
    ).to_dict()
    assert Document.from_dict(row).licence.licence_id == "US-GOV-17USC105"
    del row["licence"]
    with pytest.raises(CorpusError, match="no licence"):
        Document.from_dict(row)


def test_split_is_by_family_and_integrity_is_enforced() -> None:
    assert assign_split("sec:cik:1") == assign_split("sec:cik:1")
    families = [f"fam{i}" for i in range(40)]
    assert {assign_split(f) for f in families} == {"CALIBRATION", "EVALUATION"}
    check_split_integrity([_case("a", "fam1"), _case("b", "fam1")])
    wrong = "EVALUATION" if assign_split("fam1") == "CALIBRATION" else "CALIBRATION"
    with pytest.raises(CorpusError, match="belongs to"):
        check_split_integrity([_case("c", "fam1", wrong)])
    unlicensed = Case(**{**_case("d", "fam2").to_dict(), "licences": ()})  # type: ignore[arg-type]
    with pytest.raises(CorpusError, match="licence"):
        check_split_integrity([unlicensed])


IXBRL = """<html><body><div style="display:none"><ix:header><ix:resources>
<xbrli:context id="d2025"><xbrli:entity/><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
<xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="seg"><xbrli:entity><xbrli:segment>x</xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
</ix:resources></ix:header></div>
<p>Statement</p><table><tr><td><p>Net</p>
<p>loss</p></td><td></td><td>(<ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="d2025"
unitRef="usd" scale="6" sign="-" format="ixt:num-dot-decimal">1,234.5</ix:nonFraction>)</td></tr>
<tr><td>Seg</td><td><ix:nonFraction name="us-gaap:Assets" contextRef="seg" unitRef="usd"
format="ixt:num-dot-decimal">9</ix:nonFraction></td></tr></table></body></html>"""


def test_inline_xbrl_facts_keep_offsets_scale_sign_and_dimensions() -> None:
    parsed = html_to_text(IXBRL)
    net, seg = parsed.facts
    assert fact_value(net) == Decimal("-1234500000")
    assert parsed.text[net.offset : net.offset + len(net.displayed)] == "1,234.5"
    assert parsed.contexts["d2025"].start == "2025-01-01"
    assert not parsed.contexts["d2025"].dimensional
    assert parsed.contexts["seg"].dimensional
    assert "2025-12-31" not in parsed.text  # hidden header is not text
    text = tidy(parsed.text)
    assert "| Net loss | | (1,234.5)" in text  # cell kept on one line, empty cell kept
    assert fact_value(seg) == Decimal(9)


def test_unreadable_number_is_none_not_a_guess() -> None:
    fact = html_to_text(
        '<ix:nonFraction name="us-gaap:Assets" contextRef="c" format="ixt:numwordsen">'
        "none</ix:nonFraction>"
    ).facts[0]
    assert fact_value(fact) is None


def test_daily_index_parsing_and_user_agent_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    line = (
        "DEF 14A          Example Corp                                          320193      "
        "20260401    edgar/data/320193/0000320193-26-000010.txt"
    )
    (row,) = sec.parse_daily_index("header\n" + line + "\n")
    assert (row.form, row.cik, row.accession) == ("DEF 14A", 320193, "0000320193-26-000010")
    monkeypatch.delenv("KARENA_SEC_USER_AGENT", raising=False)
    with pytest.raises(CorpusError, match="KARENA_SEC_USER_AGENT"):
        sec.sec_user_agent()


def _fetcher(tmp_path, routes: dict[str, object]) -> Fetcher:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(str(request.url))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, content=json.dumps(body).encode())

    return Fetcher(
        tmp_path, headers={}, min_interval_seconds=0, transport=httpx.MockTransport(handler)
    )


def _filing() -> tuple[Document, object]:
    parsed = html_to_text(IXBRL)
    document = Document(
        doc_id="sec:0000000001-26-000001",
        origin="SEC",
        family_id="sec:cik:1",
        label="SEC_10K",
        language="en",
        url="https://www.sec.gov/x.htm",
        fetched_at="t",
        raw_sha256="sha256:0",
        text=parsed.text,
        licence=Licence(
            licence_id="SEC-EDGAR-PUBLIC-FILING",
            basis="b",
            evidence="index",
            source_url="https://www.sec.gov/x.htm",
        ),
        meta={"cik": 1, "accession": "0000000001-26-000001"},
    )
    return document, parsed


def test_gold_fact_needs_both_sec_sources_to_agree(tmp_path) -> None:  # type: ignore[no-untyped-def]
    document, parsed = _filing()
    url = "https://data.sec.gov/api/xbrl/companyconcept/CIK0000000001/us-gaap/NetIncomeLoss.json"
    row = {"accn": "0000000001-26-000001", "start": "2025-01-01", "end": "2025-12-31"}
    agree = _fetcher(tmp_path / "a", {url: {"units": {"USD": [{**row, "val": -1234500000}]}}})
    facts, counts = sec.gold_facts(agree, document, parsed, per_filing=4)  # type: ignore[arg-type]
    assert [f.value for f in facts] == [Decimal("-1234500000")]
    assert counts["dimensional"] == 1
    disagree = _fetcher(tmp_path / "b", {url: {"units": {"USD": [{**row, "val": -1}]}}})
    facts, counts = sec.gold_facts(disagree, document, parsed, per_filing=4)  # type: ignore[arg-type]
    assert facts == [] and counts["disagree"] == 1
    missing = _fetcher(tmp_path / "c", {})
    facts, counts = sec.gold_facts(missing, document, parsed, per_filing=4)  # type: ignore[arg-type]
    assert facts == [] and counts["api_missing"] == 1


def test_fetcher_caches_and_refuses_offline_misses(tmp_path) -> None:  # type: ignore[no-untyped-def]
    fetcher = _fetcher(tmp_path, {"https://x.gov/a": {"k": 1}})
    first = fetcher.get("https://x.gov/a")
    with pytest.raises(FetchError, match="HTTP 404"):
        fetcher.get("https://x.gov/missing")
    offline = Fetcher(tmp_path, headers={}, offline=True)
    assert offline.get("https://x.gov/a").sha256 == first.sha256
    with pytest.raises(FetchError, match="offline"):
        offline.get("https://x.gov/other")
