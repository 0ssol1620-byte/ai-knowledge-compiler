"""Offline table-lane shadow harness (table/limits plan §C5, §C9 R2; task T4).

Every number asserted here was counted by hand from the SYNTHETIC fixtures, not read back from
the harness: page 0 reads a 3x2 table with one misread, unconfirmed cell; page 1 is a table the
reader refused as truncated; page 2 has no table; page 3 has no reader output at all.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import omnidoc_teds
import run_shadow
from run_shadow import REFUSAL_CODES, ShadowRefused, build_receipt, main, receipt_bytes

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"
MANIFEST = "SYNTHETIC-manifest.json"
GOLD = "SYNTHETIC-gold.json"
Json = dict[str, Any]


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A private copy of the fixtures, so a test can break one input."""
    target = tmp_path / "corpus"
    shutil.copytree(FIXTURES, target)
    return target


def edit(path: Path, mutate: Callable[[Json], None]) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def refused(manifest: Path) -> str:
    with pytest.raises(ShadowRefused) as caught:
        build_receipt(manifest)
    assert caught.value.reason_code in REFUSAL_CODES
    return caught.value.reason_code


def page(receipt: Json, index: int) -> Json:
    return next(row for row in receipt["pages"] if row["pageIndex0"] == index)


# --- fixtures ----------------------------------------------------------------------------------


def test_every_fixture_is_labelled_synthetic_in_name_and_data() -> None:
    files = sorted(FIXTURES.iterdir())
    assert len(files) == 7
    for path in files:
        assert path.name.startswith("SYNTHETIC-"), path.name
        assert "SYNTHETIC" in path.read_text(encoding="utf-8"), path.name
    for name in (MANIFEST, GOLD):
        assert json.loads((FIXTURES / name).read_text(encoding="utf-8"))["synthetic"] is True


# --- the receipt -------------------------------------------------------------------------------


def test_receipt_carries_the_section_c9_r2_fields() -> None:
    receipt = build_receipt(FIXTURES / MANIFEST)
    assert set(receipt) == {
        "schemaVersion",
        "synthetic",
        "note",
        "rightsStatus",
        "corpora",
        "conditions",
        "harness",
        "inputs",
        "ocrJsonByteCompare",
        "pages",
        "pageStatusCounts",
        "reasonCodeCounts",
        "rates",
        "teds",
        "readerWallSecondsPerPage",
        "doesNotProve",
    }
    assert receipt["schemaVersion"] == "tavonel.table_lane_shadow.v1"
    assert receipt["synthetic"] is True and receipt["rightsStatus"] == "synthetic"
    # Every input digest: manifest, both ocr.json, gold, each page's reader output.
    manifest_sha = "sha256:" + hashlib.sha256((FIXTURES / MANIFEST).read_bytes()).hexdigest()
    assert receipt["inputs"]["manifest"]["sha256"] == manifest_sha
    assert receipt["conditions"]["corpusManifestSha256"] == manifest_sha
    doc = receipt["inputs"]["documents"][0]
    for key in ("baselineOcrJson", "shadowOcrJson", "gold"):
        name = doc[key]["path"]
        assert (
            doc[key]["sha256"]
            == "sha256:" + hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        )
    assert [ref["path"] for ref in doc["tableRead"]] == [
        "SYNTHETIC-table-read-p0.json",
        "SYNTHETIC-table-read-p1.json",
        "SYNTHETIC-table-read-p2.json",
        None,
    ]
    # Per-page status and reasonCode counts.
    assert receipt["pageStatusCounts"] == {"read": 1, "no_table": 1, "unreadable": 1, "failed": 1}
    assert receipt["reasonCodeCounts"] == {
        "TABLE_CELL_TEXT_UNCONFIRMED": 1,
        "TABLE_OUTPUT_TRUNCATED": 1,
        "TABLE_READER_UNAVAILABLE": 1,
    }
    # TEDS is named with its evaluator commit and says it was not computed.
    assert receipt["teds"]["computed"] is False
    assert receipt["teds"]["evaluatorCommit"] == "193627ae9e97d89188468ed1ee3b7a856ff76044"
    assert "value" not in receipt["teds"]
    # Wall seconds: nothing was timed, so nothing is reported, with the page denominator.
    assert receipt["readerWallSecondsPerPage"] == {
        "measuredPages": 0,
        "pages": 4,
        "medianSeconds": None,
        "p90Seconds": None,
        "maxSeconds": None,
    }
    # No evaluator ran: the harness states what its own code does, and that no process started.
    assert receipt["harness"]["network"] == {
        "harnessProcess": run_shadow.HARNESS_NETWORK,
        "evaluatorSubprocess": None,
    }
    assert receipt["harness"]["gpu"] is False


def test_rates_are_numerator_over_denominator_counted_by_hand() -> None:
    rates = build_receipt(FIXTURES / MANIFEST)["rates"]
    assert {key: (rate["numerator"], rate["denominator"]) for key, rate in rates.items()} == {
        "ocrJsonByteIdentical": (1, 1),
        "pagesQualified": (3, 4),  # page 3: TABLE_READER_UNAVAILABLE
        "tablesReadOfReaderReported": (1, 2),  # page 0 read, page 1 refused
        "goldTablesMatched": (1, 3),
        "cellExactMatch": (5, 14),  # "Soutn" != "South"; pages 1 and 3 read nothing
        "readerCellsConfirmed": (5, 6),
        "dataCellsPromotedToClaims": (3, 4),  # the unconfirmed cell is no claim
    }


def test_every_rate_has_an_integer_numerator_and_denominator() -> None:
    rates = build_receipt(FIXTURES / MANIFEST)["rates"]
    assert rates
    for name, rate in rates.items():
        assert set(rate) == {"numerator", "denominator", "of"}, name
        assert type(rate["numerator"]) is int and type(rate["denominator"]) is int, name
        assert 0 <= rate["numerator"] <= rate["denominator"], name
        assert isinstance(rate["of"], str) and rate["of"], name


def test_data_cells_of_a_table_without_header_rows_stay_in_the_denominator(corpus: Path) -> None:
    # No header row: no cell has a column header path, so none is a claim, and all six count.
    edit(corpus / "SYNTHETIC-table-read-p0.json", lambda d: d["tables"][0].update(headerRowCount=0))
    assert build_receipt(corpus / MANIFEST)["rates"]["dataCellsPromotedToClaims"] == {
        "numerator": 0,
        "denominator": 6,
        "of": (
            "cells outside the header rows of the tables read; every cell of a table with no"
            " header row, which yields no claim"
        ),
    }


def test_an_unreadable_table_is_reported_with_its_gold_never_filled_in() -> None:
    receipt = build_receipt(FIXTURES / MANIFEST)
    truncated = page(receipt, 1)
    assert truncated["status"] == "unreadable"
    assert truncated["refusalCounts"] == {"TABLE_OUTPUT_TRUNCATED": 1}
    assert (truncated["tablesRead"], truncated["cellsRead"], truncated["claims"]) == (0, 0, 0)
    assert (truncated["goldCells"], truncated["goldCellsMatched"]) == (4, 0)
    absent = page(receipt, 3)
    # No reader output is "unavailable", never "no table"; its gold table still counts.
    assert absent["status"] == "failed"
    assert absent["reasonCode"] == "TABLE_READER_UNAVAILABLE"
    assert (absent["goldTables"], absent["goldTablesMatched"]) == (1, 0)


# --- determinism -------------------------------------------------------------------------------


def test_same_input_gives_the_same_receipt_sha256_wherever_it_sits(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = receipt_bytes(build_receipt(FIXTURES / MANIFEST))
    assert receipt_bytes(build_receipt(FIXTURES / MANIFEST)) == first
    assert receipt_bytes(build_receipt(corpus / MANIFEST)) == first  # another directory
    out = tmp_path / "out" / "TABLE-LANE-SHADOW-RECEIPT.json"
    assert main([str(corpus / MANIFEST), "--out", str(out)]) == 0
    digest = hashlib.sha256(first).hexdigest()
    assert out.read_bytes() == first
    assert Path(f"{out}.sha256").read_text(encoding="utf-8") == (
        f"{digest}  TABLE-LANE-SHADOW-RECEIPT.json\n"
    )
    assert f"sha256:{digest}" in capsys.readouterr().out
    assert b"\r\n" not in first and str(tmp_path).encode() not in first


def test_a_changed_shadow_ocr_json_is_a_recorded_byte_difference(corpus: Path) -> None:
    before = receipt_bytes(build_receipt(corpus / MANIFEST))
    shadow = corpus / "SYNTHETIC-ocr-shadow.json"
    shadow.write_bytes(shadow.read_bytes().replace(b'"confidence": 0.9', b'"confidence": 0.8', 1))
    receipt = build_receipt(corpus / MANIFEST)
    (compare,) = receipt["ocrJsonByteCompare"]
    assert compare["identical"] is False
    assert compare["baselineSha256"] != compare["shadowSha256"]
    assert receipt["rates"]["ocrJsonByteIdentical"]["numerator"] == 0
    assert receipt_bytes(receipt) != before


def test_timed_pages_report_median_p90_and_max() -> None:
    assert run_shadow._wall([3.0, 1.0, 10.0, 2.0], 5) == {
        "measuredPages": 4,
        "pages": 5,
        "medianSeconds": 2.5,
        "p90Seconds": 10.0,
        "maxSeconds": 10.0,
    }


def test_wall_seconds_flow_from_the_manifest(corpus: Path) -> None:
    def timed(manifest: Json) -> None:
        rows = manifest["documents"][0]["pages"]
        for row, seconds in zip(rows, (4, 9.5, None, None), strict=True):
            row["readerWallSeconds"] = seconds

    edit(corpus / MANIFEST, timed)
    wall = build_receipt(corpus / MANIFEST)["readerWallSecondsPerPage"]
    assert (wall["measuredPages"], wall["pages"], wall["maxSeconds"]) == (2, 4, 9.5)


# --- refusals: the whole run, with a reasonCode ------------------------------------------------


def test_gold_without_label_provenance_is_refused(corpus: Path) -> None:
    edit(corpus / GOLD, lambda gold: gold.pop("labelProvenance"))
    assert refused(corpus / MANIFEST) == "SHADOW_GOLD_UNLABELLED"


def test_gold_labelled_by_a_model_is_refused(corpus: Path) -> None:
    edit(corpus / GOLD, lambda gold: gold["labelProvenance"].update(method="model_output"))
    assert refused(corpus / MANIFEST) == "SHADOW_GOLD_UNLABELLED"


def test_a_gold_page_without_a_tables_label_is_refused(corpus: Path) -> None:
    edit(corpus / GOLD, lambda gold: gold["pages"][2].pop("tables"))
    assert refused(corpus / MANIFEST) == "SHADOW_GOLD_UNLABELLED"


def test_a_page_missing_from_gold_is_refused(corpus: Path) -> None:
    edit(corpus / GOLD, lambda gold: gold["pages"].pop())
    assert refused(corpus / MANIFEST) == "SHADOW_GOLD_UNLABELLED"


def test_gold_with_overlapping_cells_is_refused(corpus: Path) -> None:
    edit(
        corpus / GOLD,
        lambda gold: gold["pages"][0]["tables"][0]["cells"][1].update(columnIndex0=0),
    )
    assert refused(corpus / MANIFEST) == "SHADOW_GOLD_INVALID"


def test_corpora_of_different_rights_are_refused(corpus: Path) -> None:
    edit(
        corpus / MANIFEST,
        lambda m: m["corpora"].append(
            {"corpusId": "omnidocbench-diagnostic", "rightsStatus": "research_only_non_commercial"}
        ),
    )
    assert refused(corpus / MANIFEST) == "SHADOW_CORPUS_RIGHTS_MIXED"


def test_a_synthetic_label_on_a_non_synthetic_corpus_is_refused(corpus: Path) -> None:
    edit(corpus / MANIFEST, lambda m: m["corpora"][0].update(rightsStatus="customer_consented"))
    assert refused(corpus / MANIFEST) == "SHADOW_CORPUS_RIGHTS_MIXED"


def test_synthetic_gold_under_a_non_synthetic_manifest_is_refused(corpus: Path) -> None:
    def relabel(m: Json) -> None:
        m["corpora"][0]["rightsStatus"] = "customer_consented"
        m["synthetic"] = False

    edit(corpus / MANIFEST, relabel)
    assert refused(corpus / MANIFEST) == "SHADOW_CORPUS_RIGHTS_MIXED"


def test_an_unknown_rights_status_is_refused(corpus: Path) -> None:
    edit(corpus / MANIFEST, lambda m: m["corpora"][0].update(rightsStatus="public"))
    assert refused(corpus / MANIFEST) == "SHADOW_MANIFEST_INVALID"


def test_an_input_not_on_disk_is_refused(corpus: Path) -> None:
    (corpus / "SYNTHETIC-table-read-p2.json").unlink()
    assert refused(corpus / MANIFEST) == "SHADOW_INPUT_MISSING"


def test_a_path_outside_the_manifest_directory_is_refused(corpus: Path) -> None:
    edit(corpus / MANIFEST, lambda m: m["documents"][0].update(gold="../SYNTHETIC-gold.json"))
    assert refused(corpus / MANIFEST) == "SHADOW_MANIFEST_INVALID"


def test_a_manifest_that_skips_a_page_is_refused(corpus: Path) -> None:
    edit(corpus / MANIFEST, lambda m: m["documents"][0]["pages"].pop(2))
    assert refused(corpus / MANIFEST) == "SHADOW_MANIFEST_INVALID"


def test_missing_section_c5_conditions_are_refused(corpus: Path) -> None:
    edit(corpus / MANIFEST, lambda m: m["conditions"].pop("promptSha256"))
    assert refused(corpus / MANIFEST) == "SHADOW_MANIFEST_INVALID"


def test_an_ocr_json_for_other_bytes_is_refused(corpus: Path) -> None:
    edit(
        corpus / "SYNTHETIC-ocr-baseline.json",
        lambda ocr: ocr.update(inputSha256="sha256:" + "00" * 32),
    )
    assert refused(corpus / MANIFEST) == "SHADOW_OCR_BINDING_MISMATCH"


def test_an_ocr_json_without_a_source_immutable_key_is_refused(corpus: Path) -> None:
    # Without the key the binding cannot be checked, so it is refused, never assumed to hold.
    edit(corpus / "SYNTHETIC-ocr-baseline.json", lambda ocr: ocr.pop("sourceImmutableKey"))
    with pytest.raises(ShadowRefused) as caught:
        build_receipt(corpus / MANIFEST)
    assert caught.value.reason_code == "SHADOW_OCR_INVALID"
    assert "sourceImmutableKey" in caught.value.detail


def test_invariants_are_raised_not_asserted() -> None:
    # `python -O` strips assert statements; these checks must survive it.
    for module in (run_shadow, omnidoc_teds):
        tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
        assert not [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    with pytest.raises(ValueError, match="NOT_A_REFUSAL_CODE"):
        ShadowRefused("NOT_A_REFUSAL_CODE", "detail")
    with pytest.raises(ValueError, match="3 of 2"):
        run_shadow._rate(3, 2, "gold cells")


def test_a_refused_run_writes_no_receipt(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edit(corpus / GOLD, lambda gold: gold.pop("labelProvenance"))
    out = tmp_path / "receipt.json"
    assert main([str(corpus / MANIFEST), "--out", str(out)]) == 2
    assert not out.exists() and not Path(f"{out}.sha256").exists()
    assert "SHADOW_GOLD_UNLABELLED" in capsys.readouterr().err


# --- a page that fails is counted, not dropped -------------------------------------------------


def test_a_page_canonical_tables_rejects_is_counted_with_its_code(corpus: Path) -> None:
    # table_read.v1 allows a two-character cellId; CIR does not, so canonical_tables refuses it.
    edit(
        corpus / "SYNTHETIC-table-read-p0.json",
        lambda d: d["tables"][0]["cells"][0].update(cellId="c1"),
    )
    receipt = build_receipt(corpus / MANIFEST)
    row = page(receipt, 0)
    assert (row["status"], row["reasonCode"]) == ("failed", "TABLE_READ_SCHEMA_INVALID")
    assert receipt["rates"]["cellExactMatch"] == {
        "numerator": 0,
        "denominator": 14,
        "of": "gold cells",
    }


def test_reader_bytes_that_are_not_json_are_a_schema_failure(corpus: Path) -> None:
    (corpus / "SYNTHETIC-table-read-p2.json").write_bytes(b"{truncated")
    row = page(build_receipt(corpus / MANIFEST), 2)
    assert (row["status"], row["reasonCode"]) == ("failed", "TABLE_READ_SCHEMA_INVALID")


def test_reader_output_from_another_reader_is_a_binding_mismatch(corpus: Path) -> None:
    edit(
        corpus / "SYNTHETIC-table-read-p2.json",
        lambda d: d.update(readerBindingSha256="sha256:" + "ee" * 32),
    )
    row = page(build_receipt(corpus / MANIFEST), 2)
    assert (row["status"], row["reasonCode"]) == ("failed", "TABLE_BINDING_MISMATCH")


# --- no network, no GPU ------------------------------------------------------------------------


def test_the_harness_imports_nothing_that_reaches_a_network_or_a_process() -> None:
    tree = ast.parse(Path(run_shadow.__file__).read_text(encoding="utf-8"))
    imported = {
        (node.module or "") if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    roots = {name.split(".")[0] for name in imported}
    assert roots <= {
        "__future__",
        "argparse",
        "hashlib",
        "json",
        "math",
        "statistics",
        "sys",
        "collections",
        "pathlib",
        "typing",
        "akc_product_core",
    }, roots


def test_a_build_with_sockets_disabled_still_writes_the_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the shadow harness opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert build_receipt(FIXTURES / MANIFEST)["rates"]["cellExactMatch"]["denominator"] == 14


# --- TEDS: the pinned evaluator, or EVALUATOR_BLOCKED and no value -----------------------------

PIN = "193627ae9e97d89188468ed1ee3b7a856ff76044"


def no_number(block: Json) -> None:
    """A blocked teds block carries a reason and nothing a reader could take for a score."""
    assert block["status"] == "EVALUATOR_BLOCKED" and block["computed"] is False
    assert set(block) == {"status", "computed", "evaluator", "evaluatorCommit", "reason"}
    assert [value for value in block.values() if type(value) in (int, float)] == []


def test_without_an_evaluator_teds_is_blocked_with_no_value() -> None:
    receipt = build_receipt(FIXTURES / MANIFEST)
    no_number(receipt["teds"])
    assert receipt["teds"]["evaluatorCommit"] == PIN
    assert "TEDS: not computed (EVALUATOR_BLOCKED)." in receipt["doesNotProve"]


def test_an_absent_evaluator_path_is_evaluator_blocked_never_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "receipt.json"
    absent = tmp_path / "no-omnidocbench-here"
    code = omnidoc_teds.main(
        [str(FIXTURES / MANIFEST), "--out", str(out), "--evaluator", str(absent)]
    )
    assert code == 3  # the receipt is written, and the run says TEDS is blocked
    teds = json.loads(out.read_text(encoding="utf-8"))["teds"]
    no_number(teds)
    assert teds["reason"] == "the evaluator checkout is not on disk"
    assert "EVALUATOR_BLOCKED" in capsys.readouterr().err
    assert str(tmp_path).encode() not in out.read_bytes()


def test_a_manifest_without_an_evaluator_commit_is_blocked(corpus: Path, tmp_path: Path) -> None:
    edit(corpus / MANIFEST, lambda m: m["conditions"].update(evaluatorCommit=None))
    (tmp_path / "pdf_validation.py").write_text("raise SystemExit(9)\n", encoding="utf-8")

    def teds(pages: list[Json], commit: object, synthetic: bool) -> Json:
        return omnidoc_teds.run_evaluator(
            pages, commit, synthetic, evaluator=tmp_path, python=[sys.executable]
        )

    block = build_receipt(corpus / MANIFEST, teds=teds)["teds"]
    no_number(block)
    assert block["reason"] == "the manifest names no evaluatorCommit"


def test_table_html_is_the_rule_the_receipt_states() -> None:
    table = {
        "rowCount": 2,
        "columnCount": 2,
        "cells": [
            {"rowIndex0": 1, "columnIndex0": 1, "rowSpan": 1, "columnSpan": 1, "text": "<7 & 8>"},
            {"rowIndex0": 0, "columnIndex0": 0, "rowSpan": 2, "columnSpan": 1, "text": "Region"},
            {"rowIndex0": 0, "columnIndex0": 1, "rowSpan": 1, "columnSpan": 1, "text": "Units"},
        ],
    }
    assert omnidoc_teds.table_html(table) == (
        '<table><tr><td rowspan="2">Region</td><td>Units</td></tr>'
        "<tr><td>&lt;7 &amp; 8&gt;</td></tr></table>"
    )


def fake_result(tmp_path: Path, errors: list[Json]) -> tuple[list[Json], list[Json], Path, str]:
    """Evaluator-shaped output for one SYNTHETIC page holding gold table g0 of the fixtures."""
    gold = json.loads((FIXTURES / GOLD).read_text(encoding="utf-8"))["pages"][0]["tables"]
    pages = [{"documentId": "SYNTHETIC-doc-0001", "pageIndex0": 0, "gold": gold, "read": gold}]
    work = tmp_path / "work"
    work.mkdir()
    gt, _ = omnidoc_teds.write_inputs(pages, work, "SYNTHETIC-")
    result = work / "result"
    result.mkdir()
    debug = {"TEDS": {"error_cases": errors, "timeout_cases": []}}
    metric = json.dumps({"table": {"metric_debug": debug}})
    (result / "S_metric_result.json").write_text(metric, encoding="utf-8")
    (result / "S_table_result.json").write_text("[]", encoding="utf-8")
    return pages, gt, result, gt[0]["layout_dets"][0]["html"]


def rows(result: Path, *table_rows: Json) -> None:
    (result / "S_table_result.json").write_text(json.dumps(list(table_rows)), encoding="utf-8")


IMAGE = "SYNTHETIC-page-0000.png"


def test_a_teds_error_the_evaluator_logged_is_blocked_not_zero(tmp_path: Path) -> None:
    pages, gt, result, html = fake_result(tmp_path, [{"img_id": IMAGE}])
    # The evaluator writes 0.0 for a pair it could not score; that 0.0 is not a score.
    rows(
        result,
        {
            "img_id": IMAGE,
            "gt": html,
            "pred": html,
            "metric": {"TEDS": 0.0, "TEDS_structure_only": 0.0},
        },
    )
    scores = omnidoc_teds.read_scores(pages, gt, result, "S")
    assert scores["scored"] == []
    assert scores["blocked"] == [
        {
            "documentId": "SYNTHETIC-doc-0001",
            "pageIndex0": 0,
            "goldTableId": "g0",
            "reason": "evaluator logged a TEDS error or timeout",
        }
    ]


def test_evaluator_output_without_teds_debug_is_an_error(tmp_path: Path) -> None:
    pages, gt, result, _ = fake_result(tmp_path, [])
    (result / "S_metric_result.json").write_text(json.dumps({"table": {}}), encoding="utf-8")
    assert "error" in omnidoc_teds.read_scores(pages, gt, result, "S")
    (result / "S_metric_result.json").unlink()
    assert omnidoc_teds.read_scores(pages, gt, result, "S") == {
        "error": "the evaluator wrote no table result"
    }


def test_a_gold_table_with_no_or_two_teds_rows_is_blocked(tmp_path: Path) -> None:
    pages, gt, result, html = fake_result(tmp_path, [])
    reason = omnidoc_teds.read_scores(pages, gt, result, "S")["blocked"][0]["reason"]
    assert reason == "0 TEDS rows for one gold table"
    row = {
        "img_id": IMAGE,
        "gt": html,
        "pred": "",
        "metric": {"TEDS": 0.5, "TEDS_structure_only": 1.0},
    }
    rows(result, row, row)
    reason = omnidoc_teds.read_scores(pages, gt, result, "S")["blocked"][0]["reason"]
    assert reason == "2 TEDS rows for one gold table"
    rows(result, row)
    (scored,) = omnidoc_teds.read_scores(pages, gt, result, "S")["scored"]
    assert (scored["teds"], scored["tedsStructureOnly"], scored["predEmpty"]) == (0.5, 1.0, True)


# A stand-in for pdf_validation.py: one TEDS row of 0.5 for every gold table it is given.
FAKE_EVALUATOR = """import json, pathlib, re, sys
gt_path, pred_path = re.findall(r"data_path: '(.+)'", pathlib.Path(sys.argv[2]).read_text("utf-8"))
pred = pathlib.Path(pred_path)
rows = [
    {
        "img_id": page["page_info"]["image_path"],
        "gt": det["html"],
        "pred": (pred / page["page_info"]["image_path"].replace(".png", ".md")).read_text("utf-8"),
        "metric": {"TEDS": 0.5, "TEDS_structure_only": 0.5},
    }
    for page in json.loads(pathlib.Path(gt_path).read_text("utf-8"))
    for det in page["layout_dets"]
]
out = pathlib.Path("result")
out.mkdir()
debug = {"TEDS": {"error_cases": [], "timeout_cases": []}}
(out / f"{pred.name}_quick_match_metric_result.json").write_text(
    json.dumps({"table": {"metric_debug": debug}})
)
(out / f"{pred.name}_quick_match_table_result.json").write_text(json.dumps(rows))
"""


def fake_evaluator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str = FAKE_EVALUATOR
) -> Callable[[list[Json], object, bool], Json]:
    """run_evaluator over a stand-in checkout that git reports at the pin and unmodified."""
    checkout = tmp_path / "fake-omnidocbench"
    checkout.mkdir(parents=True)
    (checkout / "pdf_validation.py").write_text(script, encoding="utf-8")
    monkeypatch.setattr(
        omnidoc_teds, "_git", lambda _checkout, *args: PIN if args[0] == "rev-parse" else ""
    )

    def teds(pages: list[Json], commit: object, synthetic: bool) -> Json:
        return omnidoc_teds.run_evaluator(
            pages, commit, synthetic, evaluator=checkout, python=[sys.executable]
        )

    return teds


def test_a_page_the_reader_never_ran_is_not_a_teds_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    block = build_receipt(FIXTURES / MANIFEST, teds=fake_evaluator(tmp_path, monkeypatch))["teds"]
    assert block["status"] == "COMPUTED"
    # Page 3 has no reader output (TABLE_READER_UNAVAILABLE, operational). Its gold table g3 is
    # not a reader that scored 0.0: it is never sent to the evaluator and never summed.
    assert [row["goldTableId"] for row in block["tables"]] == ["g0", "g1"]
    assert block["excludedTables"] == [
        {
            "documentId": "SYNTHETIC-doc-0001",
            "pageIndex0": 3,
            "goldTableId": "g3",
            "reasonCode": "TABLE_READER_UNAVAILABLE",
            "reasonClass": "operational",
        }
    ]
    assert block["blockedTables"] == []
    summed = {key: value for key, value in block["tedsSum"].items() if key != "of"}
    assert summed == {
        "teds": 1.0,
        "tedsStructureOnly": 1.0,
        "scoredTables": 2,
        "excludedTables": 1,
        "blockedTables": 0,
        "goldTables": 3,
    }


def test_a_page_bound_to_another_reader_is_excluded_as_an_evidence_failure(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edit(
        corpus / "SYNTHETIC-table-read-p0.json",
        lambda d: d.update(readerBindingSha256="sha256:" + "ee" * 32),
    )
    block = build_receipt(corpus / MANIFEST, teds=fake_evaluator(tmp_path, monkeypatch))["teds"]
    assert [row["goldTableId"] for row in block["tables"]] == ["g1"]
    assert [(row["goldTableId"], row["reasonClass"]) for row in block["excludedTables"]] == [
        ("g0", "evidence"),
        ("g3", "operational"),
    ]


def test_teds_is_blocked_when_every_gold_table_is_on_a_failed_page(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_output(manifest: Json) -> None:
        for row in manifest["documents"][0]["pages"]:
            row["tableRead"] = None

    edit(corpus / MANIFEST, no_output)
    block = build_receipt(corpus / MANIFEST, teds=fake_evaluator(tmp_path, monkeypatch))["teds"]
    no_number(block)
    assert (
        block["reason"] == "every gold table is on a page that failed operationally or on evidence"
    )


def test_the_receipt_says_what_kept_the_evaluator_offline_and_no_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = {
        "started": True,
        "offlineEnv": {
            "HF_HUB_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
        "networkIsolated": False,
    }
    receipt = build_receipt(FIXTURES / MANIFEST, teds=fake_evaluator(tmp_path / "a", monkeypatch))
    assert receipt["harness"]["network"] == {
        "harnessProcess": run_shadow.HARNESS_NETWORK,
        "evaluatorSubprocess": started,
    }
    assert "evaluatorSubprocess" not in receipt["teds"]
    # A run that started the evaluator and then failed still says the process started.
    failing = fake_evaluator(tmp_path / "b", monkeypatch, script="raise SystemExit(1)\n")
    receipt = build_receipt(FIXTURES / MANIFEST, teds=failing)
    no_number(receipt["teds"])
    assert receipt["harness"]["network"]["evaluatorSubprocess"] == started
    # Refused before any process started: nothing is claimed about one.
    absent = fake_evaluator(tmp_path / "c", monkeypatch, script="")
    receipt = build_receipt(
        FIXTURES / MANIFEST,
        teds=lambda pages, commit, synthetic: absent(pages, None, synthetic),
    )
    assert receipt["harness"]["network"]["evaluatorSubprocess"] is None


def test_the_evaluator_runner_imports_nothing_that_reaches_a_network() -> None:
    tree = ast.parse(Path(omnidoc_teds.__file__).read_text(encoding="utf-8"))
    roots = {
        ((node.module or "") if isinstance(node, ast.ImportFrom) else alias.name).split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    # One process (git, then the evaluator); no socket, http, urllib or ssl.
    assert roots <= {
        "__future__",
        "argparse",
        "hashlib",
        "html",
        "json",
        "os",
        "shlex",
        "subprocess",
        "sys",
        "tempfile",
        "collections",
        "pathlib",
        "typing",
        "run_shadow",
    }, roots


EVALUATOR = os.environ.get("TAVONEL_OMNIDOC_EVALUATOR")


@pytest.mark.skipif(
    not EVALUATOR, reason="opt-in: TAVONEL_OMNIDOC_EVALUATOR names a checkout at the pin"
)
def test_the_pinned_evaluator_scores_the_fixtures_the_same_twice(corpus: Path) -> None:
    def teds(pages: list[Json], commit: object, synthetic: bool) -> Json:
        return omnidoc_teds.run_evaluator(
            pages, commit, synthetic, evaluator=Path(str(EVALUATOR)), python=["py", "-3.10"]
        )

    first = receipt_bytes(build_receipt(FIXTURES / MANIFEST, teds=teds))
    assert receipt_bytes(build_receipt(corpus / MANIFEST, teds=teds)) == first
    block = json.loads(first)["teds"]
    assert (block["status"], block["computed"], block["evaluatorHead"]) == ("COMPUTED", True, PIN)
    by_table = {row["goldTableId"]: row for row in block["tables"]}
    # g0: same 3x2 grid, one cell "Soutn" for "South": 1 edit / 5 chars over 9 nodes (3 tr, 6 td).
    assert by_table["g0"]["teds"] == pytest.approx(1 - (1 / 5) / 9)
    assert (by_table["g0"]["tedsStructureOnly"], by_table["g0"]["predEmpty"]) == (1.0, False)
    # g1: the reader refused it as truncated (semantic), so it is scored against nothing.
    assert (by_table["g1"]["teds"], by_table["g1"]["predEmpty"]) == (0.0, True)
    # g3: no reader output at all (operational): never scored, listed with its reason.
    assert set(by_table) == {"g0", "g1"}
    assert [(row["goldTableId"], row["reasonCode"]) for row in block["excludedTables"]] == [
        ("g3", "TABLE_READER_UNAVAILABLE")
    ]
    assert block["blockedTables"] == []
    counts = ("scoredTables", "excludedTables", "blockedTables", "goldTables")
    assert tuple(block["tedsSum"][key] for key in counts) == (2, 1, 0, 3)
