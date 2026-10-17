"""Offline table-lane shadow harness (table/limits plan §C5, §C9 R2; task T4).

Every number asserted here was counted by hand from the SYNTHETIC fixtures, not read back from
the harness: page 0 reads a 3x2 table with one misread, unconfirmed cell; page 1 is a table the
reader refused as truncated; page 2 has no table; page 3 has no reader output at all.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

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
        "schemaVersion", "synthetic", "note", "rightsStatus", "corpora", "conditions", "harness",
        "inputs", "ocrJsonByteCompare", "pages", "pageStatusCounts", "reasonCodeCounts", "rates",
        "teds", "readerWallSecondsPerPage", "doesNotProve",
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
        assert doc[key]["sha256"] == "sha256:" + hashlib.sha256(
            (FIXTURES / name).read_bytes()
        ).hexdigest()
    assert [ref["path"] for ref in doc["tableRead"]] == [
        "SYNTHETIC-table-read-p0.json", "SYNTHETIC-table-read-p1.json",
        "SYNTHETIC-table-read-p2.json", None,
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
        "measuredPages": 0, "pages": 4, "medianSeconds": None, "p90Seconds": None,
        "maxSeconds": None,
    }
    assert receipt["harness"]["network"] is False and receipt["harness"]["gpu"] is False


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
        "measuredPages": 4, "pages": 5, "medianSeconds": 2.5, "p90Seconds": 10.0,
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
        "numerator": 0, "denominator": 14, "of": "gold cells"
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
        "__future__", "argparse", "hashlib", "json", "math", "statistics", "sys", "collections",
        "pathlib", "typing", "akc_product_core",
    }, roots


def test_a_build_with_sockets_disabled_still_writes_the_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the shadow harness opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert build_receipt(FIXTURES / MANIFEST)["rates"]["cellExactMatch"]["denominator"] == 14
