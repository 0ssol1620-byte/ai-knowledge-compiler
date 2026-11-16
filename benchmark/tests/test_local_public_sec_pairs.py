"""WO-LPC-5: SEC revision pairs. Synthetic FSDS rows only; no real data, no browser."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benchmark.local_public import sec_pairs as sp
from benchmark.local_public.sec_pairs import Dropped, PairError, Side
from benchmark.retrieval_baselines.metrics import parse_moment
from benchmark.u06_equivalence import run as u06_run
from benchmark.u06_equivalence.harness import compile_pair, judge

ACC = "2025-08-29 16:05:00.0"
W2 = "2025-08-29T20:05:22.000Z"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
IX_NS = (
    'xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
    'xmlns:xbrli="http://www.xbrl.org/2003/instance"'
)
BULK = {a: W2 for a in ("A", "B", "C", "D")}


def sub(adsh, form="10-K", period="20241231", ix=False, cik="111"):
    return {
        "adsh": adsh, "cik": cik, "form": form, "period": period, "fye": "1231", "fy": "2024",
        "fp": "FY", "accepted": ACC,
        "instance": "x-20241231_htm.xml" if ix else "x-20241231.xml",
    }  # fmt: skip


def num(tag, value, ddate="20241231", qtrs="0", **kw):
    return {
        "tag": tag, "version": "us-gaap/2024", "ddate": ddate, "qtrs": qtrs, "uom": "USD",
        "value": value, "segments": "", "coreg": "", **kw,
    }  # fmt: skip


def pre(tag, line, stmt="BS"):
    return {
        "tag": tag, "version": "us-gaap/2024", "stmt": stmt, "line": str(line),
        "plabel": tag, "negating": "0",
    }  # fmt: skip


def html(tag, ctx, start, end) -> bytes:
    period = (
        f"<xbrli:instant>{end}</xbrli:instant>"
        if start is None
        else f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>"
    )
    return (
        f'<html {IX_NS}><body><xbrli:context id="{ctx}"><xbrli:entity/><xbrli:period>{period}'
        f'</xbrli:period></xbrli:context><ix:nonFraction name="us-gaap:{tag}" '
        f'contextRef="{ctx}">1</ix:nonFraction></body></html>'
    ).encode()


def side(adsh, rows, pres, ix=False, h=None, **kw) -> Side:
    return Side(sub(adsh, ix=ix, **kw), rows, pres, h)


def original() -> Side:
    return side(
        "A",
        [num("Cash", "100"), num("Debt", "50"), num("Dim", "9", segments="x=y")],
        [pre("Cash", 1), pre("Debt", 2), pre("Dim", 3)],
    )


def test_restated_presented_row_changes_only_after_doc():
    amend = side(
        "B",
        [num("Cash", "110"), num("Debt", "50")],
        [pre("Cash", 1), pre("Debt", 2)],
        form="10-K/A",
    )
    case = sp.amendment_case(original(), amend, BULK)
    assert isinstance(case, sp.Case) and case.stratum == sp.RESTATED
    before = {d.native_id: d for d in case.before}
    after = {d.native_id: d for d in case.after}
    assert "100" in before["111-BS"].regions[0].text
    assert "110" not in before["111-BS"].regions[0].text
    assert "110" in after["111-BS"].regions[0].text
    assert "100" not in after["111-BS"].regions[0].text
    assert "/B/" in after["111-BS"].immutable_object_key
    assert "/A/" in before["111-BS"].immutable_object_key
    assert after["111-BS"].source_id is None and after["111-BS"].source_version_id is None


def test_dimensional_or_unpresented_change_is_same_values():
    amend = side(
        "B",
        [num("Cash", "100"), num("Debt", "50"), num("Dim", "10", segments="x=y"), num("Hid", "7")],
        [pre("Cash", 1), pre("Debt", 2), pre("Dim", 3)],
        form="10-K/A",
    )
    case = sp.amendment_case(original(), amend, BULK)
    assert isinstance(case, sp.Case) and case.stratum == sp.SAME_VALUES  # the 16 -> 15 case


def test_statement_missing_from_amendment_is_left_unchanged():
    base = side(
        "A", [num("Cash", "100"), num("Rev", "5", qtrs="4")], [pre("Cash", 1), pre("Rev", 2, "IS")]
    )
    amend = side("B", [num("Cash", "120")], [pre("Cash", 1)], form="10-K/A")
    case = sp.amendment_case(base, amend, BULK)
    assert isinstance(case, sp.Case)
    is_before = next(d for d in case.before if d.native_id == "111-IS")
    is_after = next(d for d in case.after if d.native_id == "111-IS")
    assert is_before == is_after and "/A/" in is_after.immutable_object_key


def test_part_iii_only_amendment_is_dropped():
    got = sp.amendment_case(original(), side("B", [], [], form="10-K/A"), BULK)
    assert got == Dropped("part_iii_only", "A>B")


def test_mixed_pair_uses_month_basis_and_date_format_alone_is_same_values():
    rows, pres = [num("Cash", "100")], [pre("Cash", 1)]
    orig = side("A", rows, pres)  # not iXBRL
    amend = side("B", rows, pres, ix=True, h=html("Cash", "c1", None, "2024-12-31"), form="10-K/A")
    case = sp.amendment_case(orig, amend, BULK)
    assert isinstance(case, sp.Case)
    assert case.date_basis == "month" and case.stratum == sp.SAME_VALUES
    assert "period ending 2024-12" in case.after[0].regions[0].text


def test_ixbrl_pair_states_the_context_dates():
    rows, pres = [num("Cash", "100")], [pre("Cash", 1)]
    h = html("Cash", "c1", None, "2025-01-02")  # FSDS ddate 20241231 is the rounded 2025-01-02
    orig = side("A", rows, pres, ix=True, h=h)
    amend = side("B", rows, pres, ix=True, h=h, form="10-K/A")
    case = sp.amendment_case(orig, amend, BULK)
    assert isinstance(case, sp.Case) and case.date_basis == "exact"
    assert "as of 2025-01-02" in case.after[0].regions[0].text


def test_unresolvable_context_falls_back_to_month_on_both_sides():
    rows, pres = [num("Cash", "100")], [pre("Cash", 1)]
    h = html("Other", "c1", None, "2024-12-31")  # no fact for Cash
    orig = side("A", rows, pres, ix=True, h=h)
    amend = side("B", rows, pres, ix=True, h=h, form="10-K/A")
    case = sp.amendment_case(orig, amend, BULK)
    assert isinstance(case, sp.Case) and case.date_basis == "month"
    assert case.before[0].regions[0].text == case.after[0].regions[0].text


def test_successor_is_ordered_by_period_and_reversed_is_refused():
    a = side("A", [num("Cash", "100")], [pre("Cash", 1)], period="20230331", form="10-Q")
    b = side("B", [num("Cash", "120")], [pre("Cash", 1)], period="20230630", form="10-Q")
    case = sp.successor_case(a, b, sp.SUCC_10Q, BULK)
    assert isinstance(case, sp.Case)
    assert (case.before_adsh, case.after_adsh) == ("A", "B") and case.stratum == sp.SUCC_10Q
    with pytest.raises(PairError, match="ordered by period"):
        sp.successor_case(b, a, sp.SUCC_10Q, BULK)
    with pytest.raises(PairError, match="not a successor"):
        sp.successor_case(a, b, sp.RESTATED, BULK)


def test_region_ids_are_unique_under_duplicate_pre_lines():
    rows = [num("Cash", "100"), {**num("Cash", "101"), "version": "us-gaap/2023"}]
    pres = [pre("Cash", 1), pre("Cash", 4), {**pre("Cash", 7), "version": "us-gaap/2023"}]
    docs = sp._docs(side("A", rows, pres), "month", NOW)
    ids = [r.region_id for r in docs[(111, "BS")].regions]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_unresolved_acceptance_drops_the_pair_with_a_reason():
    amend = side("B", [num("Cash", "1")], [pre("Cash", 1)], form="10-K/A")
    drop = Dropped("acceptance_unresolved", "A>B")
    assert sp.amendment_case(original(), amend, {"A": W2}) == drop
    assert sp.amendment_case(original(), amend, {"A": W2, "B": "2025-08-30T00:05:22.000Z"}) == drop


def test_available_at_is_timezone_aware_on_every_document():
    case = _case("B")
    for d in (*case.before, *case.after):
        assert d.available_at is not None and d.available_at.utcoffset() is not None
        assert parse_moment(d.available_at.isoformat(), field="t") == d.available_at


def test_missing_exclude_ciks_is_refused(tmp_path: Path, capsys):
    with pytest.raises(PairError):
        sp.load_excluded(None)
    with pytest.raises(PairError):
        sp.load_excluded(tmp_path / "absent.json")
    assert sp.main(["--seed", "s", "--out", str(tmp_path / "o")]) == 2
    assert "--exclude-ciks is required" in capsys.readouterr().err
    f = tmp_path / "ex.json"
    f.write_text(json.dumps({"ciks": [111, "222"]}))
    assert sp.load_excluded(f) == frozenset({111, 222})


def _case(b: str, value: str = "110") -> sp.Case:
    amend = side(b, [num("Cash", value)], [pre("Cash", 1)], form="10-K/A")
    got = sp.amendment_case(original(), amend, BULK)
    assert isinstance(got, sp.Case)
    return got


def test_a_listed_cik_never_reaches_the_output(tmp_path: Path):
    res = sp.Result(cases=[_case("B")])
    with pytest.raises(PairError, match="excluded CIK"):
        sp.write(
            res, tmp_path, requested_at=NOW, lpc_manifest_sha256="0", excluded=frozenset({111})
        )
    with pytest.raises(PairError, match="timezone"):
        sp.write(
            res, tmp_path, requested_at=datetime(2026, 1, 1), lpc_manifest_sha256="0",
            excluded=frozenset(),
        )  # fmt: skip


def test_fill_is_seed_ordered_and_never_padded():
    keys = [f"k{i}" for i in range(5)]
    got, _ = sp.fill(keys, "s", 3, lambda k: _case("B"))
    assert len(got) == 3
    got, drops = sp.fill(keys, "s", 9, lambda k: Dropped("x", k))
    assert got == [] and len(drops) == 5
    assert sp.order(keys, "s") == sp.order(reversed(keys), "s") != sp.order(keys, "t")


def test_manifest_loads_through_u06_and_a_tampered_side_raises(tmp_path: Path):
    res = sp.Result(cases=[_case("B")], shortfall={sp.SUCC_10K: 26})
    path = sp.write(
        res, tmp_path, requested_at=NOW, lpc_manifest_sha256="a" * 64, excluded=frozenset({9})
    )
    m = json.loads(path.read_text())
    assert m["provenance"]["shortfall"] == {sp.SUCC_10K: 26}
    assert m["provenance"]["cases"][0]["date_basis"] == "month"
    case = m["cases"][0]
    assert "/B/" in u06_run._load(tmp_path, case["after"])[0].immutable_object_key
    side_file = tmp_path / case["before"]["path"]
    side_file.write_bytes(side_file.read_bytes() + b" ")
    with pytest.raises(u06_run.ManifestHashMismatch):
        u06_run._load(tmp_path, case["before"])


def test_a_stale_original_row_in_the_incremental_world_is_a_phantom():
    case = _case("B")
    incremental, cold = compile_pair(case.before, case.after, requested_at=NOW)
    assert judge(incremental, cold).phantom == 0
    model = copy.deepcopy(incremental.candidate.canonical_knowledge_model)
    stale = copy.deepcopy(next(o for o in model["objects"] if o["sourceRefs"]))
    stale["stableId"] = "stale-original-row"
    stale["sourceRefs"][0]["documentVersionId"] = "version-of-the-original-10k"
    model["objects"].append(stale)
    cand = incremental.candidate.model_copy(update={"canonical_knowledge_model": model})
    assert judge(incremental.model_copy(update={"candidate": cand}), cold).phantom >= 1


def test_ixbrl_context_length_must_match_qtrs_so_q2_pair_is_exact():
    def ctx(cid, start, end):
        return (
            f'<xbrli:context id="{cid}"><xbrli:entity/><xbrli:period><xbrli:startDate>{start}'
            f"</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>"
        )

    fact = '<ix:nonFraction name="us-gaap:Rev" contextRef="{}">1</ix:nonFraction>'
    body = ctx("q", "2025-04-01", "2025-06-30") + ctx("y", "2025-01-01", "2025-06-30")
    h = f"<html {IX_NS}><body>{body}{fact.format('q')}{fact.format('y')}</body></html>".encode()
    rows = [
        num("Rev", "10", ddate="20250630", qtrs="1"),
        num("Rev", "25", ddate="20250630", qtrs="2"),
    ]
    pres = [pre("Rev", 1, "IS")]
    a = side("A", rows, pres, ix=True, h=h, period="20250331", form="10-Q")
    b = side("B", rows, pres, ix=True, h=h, period="20250630", form="10-Q")
    case = sp.successor_case(a, b, sp.SUCC_10Q, BULK)
    assert case.date_basis == "exact"
    text = " ".join(r.text for d in case.after for r in d.regions)
    assert "2025-04-01 to 2025-06-30" in text and "2025-01-01 to 2025-06-30" in text
