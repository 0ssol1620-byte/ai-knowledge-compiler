"""Tests for the KB1 -> OmniDocBench adapter (design §5.3 M4/M5/M6, §5.4 rule 6, I-10).

Internal cross-validation only: OmniDocBench is research-only-non-commercial and its
dataset is never touched here. Every page is the SYNTHETIC KS fixture or a SYNTHETIC
mutation of it, and every "evaluator output" below is a SYNTHETIC file shaped like the
pinned evaluator's (receipt core-lanes/KB-A4). No number in this file is a measured result.

The ``*_evaluator`` tests run the pinned evaluator's own ``normalized_text`` from an
unmodified local checkout at the pin (``KB1_OMNIDOC_EVALUATOR``, default
``benchmark/cache/omnidoc``; interpreter ``KB1_OMNIDOC_PYTHON``, default ``py -3.10``)
and compare it with the adapter's restatement. Without the checkout they skip and
say where they looked; the ``*_restatement`` tests still pin the restatement.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from research.kb1_korean_bench import harness
from research.kb1_korean_bench import omnidoc_adapter as oa
from research.kb1_korean_bench.harness import GoldContractError, RunContractError
from research.kb1_korean_bench.ko_tokens import extract
from research.kb1_korean_bench.omnidoc_adapter import AdapterError

KS_GOLD = Path(harness.__file__).resolve().parent / "synthetic" / "out" / "SYNTHETIC-KS-gold.json"
SAVE = "SYNTHETIC-markdown_quick_match"
P01, P02, P03, P04 = (
    "SYNTHETIC-KS-p01-statute-table",
    "SYNTHETIC-KS-p02-vertical-hanja",
    "SYNTHETIC-KS-p03-symbols",
    "SYNTHETIC-KS-p04-seal-approval",
)
CIRCLED_1_TO_20 = frozenset(chr(0x2460 + i) for i in range(20))
CAPS = {"blocks": True, "table_structure": True, "region_bbox": False, "approval_box": False}


@pytest.fixture
def gold() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(KS_GOLD.read_text(encoding="utf-8"))
    return data


def _page(gold: dict[str, Any], page_id: str) -> dict[str, Any]:
    return next(p for p in gold["pages"] if p["page_id"] == page_id)


# ------------------------------------------------------------- KS gold -> GT


def test_ks_gold_converts_block_for_block(gold: dict[str, Any]) -> None:
    gt = oa.to_omnidoc_gt(gold)
    assert [p["page_info"]["kb1_page_id"] for p in gt] == [P01, P02, P03, P04]
    for page, raw in zip(gt, gold["pages"], strict=True):
        info = page["page_info"]
        assert info["image_path"] == raw["image"]
        assert (info["width"], info["height"]) == (1240, 1754)
        assert info["label"] == "SYNTHETIC"
        assert info["page_attribute"] == {}  # the evaluator's language enum has no Korean
        assert page["extra"] == {"relation": []}
        dets = page["layout_dets"]
        assert [d["order"] for d in dets] == list(range(1, len(raw["blocks"]) + 1))
        assert {d["category_type"] for d in dets} <= {"text_block", "table"}
        tables = [d for d in dets if d["category_type"] == "table"]
        assert [d["html"] for d in tables] == [t["html"] for t in raw["tables"]]
        assert [d["poly"] for d in tables] == [oa._poly(t["bbox"]) for t in raw["tables"]]
        texts = [d["text"] for d in dets if d["category_type"] == "text_block"]
        assert len(texts) + len(tables) == len(raw["blocks"])
        assert all(text in raw["blocks"] for text in texts)
        # A seal has no OmniDocBench category; its text never becomes a det.
        assert all(d.get("text") != "견본" for d in dets)
    p01, p04 = gt[0]["layout_dets"], gt[3]["layout_dets"]
    assert p01[4]["category_type"] == "table" and p04[3]["category_type"] == "table"


def test_text_poly_is_the_union_of_its_own_gold_lines(gold: dict[str, Any]) -> None:
    raw = _page(gold, P01)
    det = oa.to_omnidoc_gt(gold)[0]["layout_dets"][2]  # the seven statute item lines
    boxes = [line["bbox"] for line in raw["lines"][2:9]]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    assert det["poly"] == [x0, y0, x1, y0, x1, y1, x0, y1]
    assert det["text"] == "\n".join(line["text"] for line in raw["lines"][2:9])


def test_write_inputs_names_files_the_way_the_evaluator_resolves_them(
    gold: dict[str, Any], tmp_path: Path
) -> None:
    md = {p["page_id"]: p["text"] for p in gold["pages"]}
    paths = oa.write_inputs(gold, md, tmp_path / "run", workers=1)
    assert paths["gt"].name == "SYNTHETIC-omnidoc-gt.json"
    assert paths["predictions"].name == "SYNTHETIC-markdown"  # evaluator save_name prefix
    # The evaluator opens the GT without an encoding, so it is written as pure ASCII.
    gt = json.loads(paths["gt"].read_bytes().decode("ascii"))
    assert gt == oa.to_omnidoc_gt(gold)
    names = sorted(f.name for f in paths["predictions"].iterdir())
    assert names == sorted(p["image"][:-4] + ".md" for p in gold["pages"])
    page = gold["pages"][0]
    md_path = paths["predictions"] / (page["image"][:-4] + ".md")
    assert md_path.read_text(encoding="utf-8") == md[page["page_id"]]
    config = paths["config"].read_text(encoding="utf-8")
    assert paths["gt"].resolve().as_posix() in config
    assert "metric: [TEDS, Edit_dist]" in config and "match_method: quick_match" in config


def test_run_predictions_send_empty_pages_for_failed_rows(gold: dict[str, Any]) -> None:
    rows = [
        {"page_id": p["page_id"], "status": "SUCCESS", "text": p["text"]} for p in gold["pages"]
    ]
    rows[1] = {"page_id": P02, "status": "FAILED"}
    run = {
        "schema": harness.RUN_SCHEMA,
        "arm": {
            "arm_id": "SYNTHETIC",
            "capabilities": {
                "blocks": False,
                "table_structure": False,
                "region_bbox": False,
                "approval_box": False,
            },
        },
        "pages": rows,
    }
    predictions = oa.run_predictions(run, gold)
    assert predictions[P02] == ""
    assert predictions[P01] == _page(gold, P01)["text"]
    with pytest.raises(RunContractError, match="missing 1"):
        oa.run_predictions({**run, "pages": rows[:3]}, gold)


# ------------------------------------------------------ pinned blind spot (I-10)


M6_VIEWS = {c: str(ord(c) - 0x2460 + 1) if c in CIRCLED_1_TO_20 else "" for c in harness.M6_SYMBOLS}
NUMERIC_PAIRS = [("1,234,000원", "1234000원"), ("-2.50%", "250%"), ("2026. 10. 17.", "20261017")]
SURVIVORS = ("대한민국", "大韓", "ㆍ", "本文書", chr(0xF900))
QUIRKS = {"a/nb\tc\nd": "abcd", "\\textcircled{7}": "7", "x_y": "x_y"}  # underscore is \w

EVALUATOR_ENV, PYTHON_ENV = "KB1_OMNIDOC_EVALUATOR", "KB1_OMNIDOC_PYTHON"
EVALUATOR = Path(
    os.environ.get(EVALUATOR_ENV)
    or Path(__file__).resolve().parents[3] / "benchmark" / "cache" / "omnidoc"
)
# Runs inside the checkout; imports the evaluator's code as it is, edits nothing.
_NORMALIZE = (
    "import json, sys\n"
    "from src.core.preprocess.data_preprocess import normalized_text\n"
    "json.dump({p: normalized_text(p) for p in json.load(sys.stdin)}, sys.stdout)\n"
)
Evaluator = Callable[[Iterable[str]], dict[str, str]]


def _git(*args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(EVALUATOR), *args],  # noqa: S607 - git from PATH
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture(scope="module")
def evaluator() -> Evaluator:
    """The pinned evaluator's ``normalized_text``, from an unmodified checkout at the pin."""
    if not (EVALUATOR / "src" / "core" / "preprocess" / "data_preprocess.py").is_file():
        pytest.skip(f"no OmniDocBench evaluator checkout at {EVALUATOR} (set {EVALUATOR_ENV})")
    configured = os.environ.get(PYTHON_ENV)
    python = [configured] if configured else ["py", "-3.10"]
    if shutil.which(python[0]) is None:
        pytest.skip(f"evaluator interpreter {python[0]!r} not on PATH (set {PYTHON_ENV})")
    head = _git("rev-parse", "HEAD")
    if head != oa.EVALUATOR_PIN:
        pytest.fail(f"{EVALUATOR} is at {head}, not the pin {oa.EVALUATOR_PIN}")
    if changed := _git("status", "--porcelain", "--untracked-files=no"):
        pytest.fail(f"{EVALUATOR} is modified; the evaluator must run unmodified:\n{changed}")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}

    def run(probes: Iterable[str]) -> dict[str, str]:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [*python, "-B", "-c", _NORMALIZE],
            cwd=EVALUATOR,
            env=env,
            input=json.dumps(sorted(set(probes))),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        views: dict[str, str] = json.loads(done.stdout)
        return views

    return run


def test_m6_symbols_fold_or_vanish_in_the_restatement() -> None:
    assert {c: oa.omnidoc_text_view(c) for c in harness.M6_SYMBOLS} == M6_VIEWS
    assert CIRCLED_1_TO_20 < harness.M6_SYMBOLS


def test_m6_symbols_fold_or_vanish_in_the_evaluator(evaluator: Evaluator) -> None:
    views = evaluator(harness.M6_SYMBOLS)
    for char in harness.M6_SYMBOLS:
        assert (char, views[char]) == (char, oa.omnidoc_text_view(char))
    assert views == M6_VIEWS  # ① -> "1", ⑳ -> "20", the rest deleted


def test_hangul_hanja_and_araea_survive_the_restatement() -> None:
    for text in SURVIVORS:
        assert oa.omnidoc_text_view(text) == text


def test_korean_numerics_lose_their_punctuation_in_the_restatement() -> None:
    for gold_text, output in NUMERIC_PAIRS:
        assert oa.omnidoc_text_view(gold_text) == oa.omnidoc_text_view(output)
        assert extract(gold_text) != extract(output)  # M3 sees what Edit_dist cannot


def test_korean_numerics_lose_their_punctuation_in_the_evaluator(evaluator: Evaluator) -> None:
    views = evaluator(text for pair in NUMERIC_PAIRS for text in pair)
    for gold_text, output in NUMERIC_PAIRS:
        assert views[gold_text] == oa.omnidoc_text_view(gold_text)
        assert views[output] == oa.omnidoc_text_view(output)
        assert views[gold_text] == views[output]


def test_restated_quirks_of_the_pinned_clean_string() -> None:
    for text, view in QUIRKS.items():
        assert oa.omnidoc_text_view(text) == view


def test_restated_quirks_and_survivors_match_the_evaluator(evaluator: Evaluator) -> None:
    views = evaluator([*QUIRKS, *SURVIVORS])
    for text in [*QUIRKS, *SURVIVORS]:
        assert views[text] == oa.omnidoc_text_view(text), text
    assert views == {**QUIRKS, **{text: text for text in SURVIVORS}}


def test_ks_gold_text_matches_the_evaluator(gold: dict[str, Any], evaluator: Evaluator) -> None:
    texts = [p["text"] for p in gold["pages"]]
    probes = {*texts, *(char for text in texts for char in text)}
    views = evaluator(probes)
    mismatched = {p: (views[p], oa.omnidoc_text_view(p)) for p in probes}
    assert {p: v for p, v in mismatched.items() if v[0] != v[1]} == {}


def test_ks_blind_spot_is_pinned(gold: dict[str, Any]) -> None:
    spots = {p["page_id"]: oa.symbol_blind_spot(p["text"]) for p in gold["pages"]}
    # Characters the harness scores that the pinned evaluator deletes, per page.
    assert spots[P03]["deleted"] == Counter(
        {
            ".": 7,
            ",": 4,
            "·": 4,
            "(": 2,
            ")": 2,
            "%": 1,
            ":": 1,
            "※": 1,
            "□": 1,
            "○": 1,
            "「": 1,
            "」": 1,
            "『": 1,
            "』": 1,
            chr(0x3014): 1,
            chr(0x3015): 1,
            "㈜": 1,
        }
    )
    assert spots[P03]["folded"] == Counter(dict.fromkeys(CIRCLED_1_TO_20, 1))
    assert spots[P01]["deleted"] == Counter(
        {",": 12, "·": 11, ".": 9, "(": 2, ")": 2, "%": 1, ":": 1}
    )
    assert spots[P02]["deleted"] == Counter({"(": 5, ")": 5, "·": 5, ".": 2, ":": 2, ",": 1})
    assert spots[P04]["deleted"] == Counter({".": 6, ",": 2, "·": 2, "-": 1})
    assert not any(spots[p]["folded"] for p in (P01, P02, P04))


def test_harness_scores_what_the_evaluator_cannot_see(gold: dict[str, Any]) -> None:
    raw = _page(gold, P03)
    output = "".join(oa._CIRCLED.get(c, "") if c in harness.M6_SYMBOLS else c for c in raw["text"])
    assert oa.omnidoc_text_view(output) == oa.omnidoc_text_view(raw["text"])  # Edit_dist 0

    page = next(p for p in harness.parse_gold(gold) if p.page_id == P03)
    row = harness.RunPage(P03, "SUCCESS", output, (), (), None, None)
    metrics = harness.score_page(page, row, CAPS)
    gold_ns = harness._strip_ws(unicodedata.normalize("NFC", raw["text"]))[0]
    hanja = sum(harness.is_hanja(c) for c in gold_ns)
    symbols = sum(c in harness.M6_SYMBOLS for c in gold_ns)
    assert symbols == 34  # 20 circled digits + 10 brackets and marks + 4 middle dots
    m6 = metrics["M6"]
    assert isinstance(m6, dict)
    assert (m6["recalled"], m6["gold_set_chars"]) == (hanja, hanja + symbols)
    m1 = metrics["M1"]
    assert isinstance(m1, dict) and m1["edits"] >= symbols


# --------------------------------------------------------------- failure paths


def test_inline_formulas_and_multi_character_rules_are_refused() -> None:
    with pytest.raises(AdapterError, match="inline formula"):
        oa.omnidoc_text_view("면적은 $x^2$이다")
    with pytest.raises(AdapterError, match="inline formula"):
        oa.omnidoc_text_view("\\(a\\)")
    with pytest.raises(AdapterError, match="multi-character"):
        oa.symbol_blind_spot("경로 a/nb")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["lines"][3].update(text="SYNTHETIC 다른 줄"), "consecutive gold lines"),
        (lambda p: p["lines"].append({**p["lines"][0]}), "lines outside any block"),
        (lambda p: p["tables"][0].update(text_span=[285, 400]), "not exactly one block"),
        (lambda p: p["tables"][0].pop("html"), "needs html"),
        (lambda p: p.update(table_count=2), "table_count"),
        (lambda p: p.update(image="SYNTHETIC-KS-p01.pdf"), "bare .png/.jpg"),
        (lambda p: p.update(image="sub/SYNTHETIC-KS-p01.png"), "bare .png/.jpg"),
        (lambda p: p.pop("image"), "bare .png/.jpg"),
    ],
)
def test_gold_that_cannot_be_converted_without_guessing_is_refused(
    gold: dict[str, Any], mutate: Any, message: str
) -> None:
    broken = copy.deepcopy(gold)
    mutate(broken["pages"][0])
    with pytest.raises((AdapterError, GoldContractError), match=message):
        oa.to_omnidoc_gt(broken)


def test_duplicate_stems_bad_frame_and_pua_are_refused(gold: dict[str, Any]) -> None:
    dup = copy.deepcopy(gold)
    dup["pages"][1]["image"] = dup["pages"][0]["image"][:-4] + ".jpg"
    with pytest.raises(AdapterError, match="two pages map"):
        oa.to_omnidoc_gt(dup)
    frame = copy.deepcopy(gold)
    frame["coordinate_frame"]["unit"] = "bbox1000"
    with pytest.raises(AdapterError, match="coordinate_frame"):
        oa.to_omnidoc_gt(frame)
    pua = copy.deepcopy(gold)
    pua["pages"][0]["text"] += chr(0xE000)
    with pytest.raises(GoldContractError, match="Private Use Area"):
        oa.to_omnidoc_gt(pua)


def test_write_inputs_refuses_partial_predictions_and_reused_dirs(
    gold: dict[str, Any], tmp_path: Path
) -> None:
    md = {p["page_id"]: "" for p in gold["pages"]}
    with pytest.raises(AdapterError, match="missing"):
        oa.write_inputs(gold, {k: v for k, v in md.items() if k != P04}, tmp_path / "a")
    with pytest.raises(AdapterError, match="unknown"):
        oa.write_inputs(gold, {**md, "SYNTHETIC-extra": ""}, tmp_path / "b")
    oa.write_inputs(gold, md, tmp_path / "c")
    with pytest.raises(AdapterError, match="not empty"):
        oa.write_inputs(gold, md, tmp_path / "c")


# ------------------------------------------------- evaluator output -> harness M4


def _result(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    errors: tuple[str, ...] = (),
    debug: bool = True,
) -> Path:
    """SYNTHETIC files shaped like the pinned evaluator's table outputs (receipt KB-A4)."""
    out = tmp_path / "result"
    out.mkdir(parents=True)
    teds = {
        "stage": "TEDS",
        "sample_count": len(rows),
        "timeout_cases": [],
        "error_cases": [{"img_id": img, "gt_idx": [0], "reason": "SYNTHETIC"} for img in errors],
    }
    metric: dict[str, Any] = {"table": {"all": {}}}
    if debug:
        metric["table"]["metric_debug"] = {"TEDS": teds}
    (out / f"{SAVE}_metric_result.json").write_text(json.dumps(metric), encoding="utf-8")
    (out / f"{SAVE}_table_result.json").write_text(json.dumps(rows), encoding="utf-8")
    return out


def _row(image: str, teds: float, struct: float) -> dict[str, Any]:
    return {"gt_idx": [0], "img_id": image, "metric": {"TEDS": teds, "TEDS_structure_only": struct}}


def _ks_m4(gold: dict[str, Any], scores: dict[str, Any]) -> dict[str, Any]:
    run = {
        "schema": harness.RUN_SCHEMA,
        "arm": {"arm_id": "SYNTHETIC-echo", "capabilities": CAPS},
        "pages": [
            {"page_id": p["page_id"], "status": "SUCCESS", "text": p["text"], "blocks": p["blocks"]}
            for p in gold["pages"]
        ],
    }
    m4: dict[str, Any] = harness.score(gold, run, scores, resamples=50)["categories"]["KS"][
        "metrics"
    ]["M4"]
    return m4


def test_teds_scores_feed_the_harness_m4(gold: dict[str, Any], tmp_path: Path) -> None:
    images = [_page(gold, P01)["image"], _page(gold, P04)["image"]]
    result = _result(tmp_path, [_row(images[0], 1.0, 1.0), _row(images[1], 0.5, 0.75)])
    scores = oa.teds_scores(gold, result, SAVE)
    assert scores["pages"] == {
        P01: {"teds": 1.0, "teds_struct": 1.0},
        P04: {"teds": 0.5, "teds_struct": 0.75},
    }
    assert scores["blocked"] == {}
    assert scores["evaluator"]["main_pin"] == oa.EVALUATOR_PIN
    assert scores["evaluator"]["use"] == "internal_cross_validation_only"
    m4 = _ks_m4(gold, scores)
    assert m4["status"] == harness.MEASURED
    assert m4["teds"] == {"numerator": 1.5, "denominator": 2, "value": 0.75}


def test_an_evaluator_error_is_blocked_not_zero(gold: dict[str, Any], tmp_path: Path) -> None:
    p01, p04 = _page(gold, P01)["image"], _page(gold, P04)["image"]
    # The evaluator writes 0.0 for a table it failed to score; that is not a score.
    result = _result(tmp_path, [_row(p01, 0.0, 0.0), _row(p04, 1.0, 1.0)], errors=(p01,))
    scores = oa.teds_scores(gold, result, SAVE)
    assert P01 not in scores["pages"] and P01 in scores["blocked"]
    assert scores["pages"][P04] == {"teds": 1.0, "teds_struct": 1.0}
    assert _ks_m4(gold, scores)["status"] == harness.EVALUATOR_BLOCKED


def test_negative_teds_passes_through_unclamped(gold: dict[str, Any], tmp_path: Path) -> None:
    p01, p04 = _page(gold, P01)["image"], _page(gold, P04)["image"]
    scores = oa.teds_scores(gold, _result(tmp_path, [_row(p01, -0.25, 0.1), _row(p04, 1, 1)]), SAVE)
    assert scores["pages"][P01]["teds"] == -0.25
    assert _ks_m4(gold, scores)["status"] == harness.EVALUATOR_BLOCKED  # out of [0, 1]


def test_missing_rows_debug_or_files_fail_closed(gold: dict[str, Any], tmp_path: Path) -> None:
    p04 = _page(gold, P04)["image"]
    scores = oa.teds_scores(gold, _result(tmp_path / "rows", [_row(p04, 1.0, 1.0)]), SAVE)
    assert scores["blocked"] == {P01: "0 TEDS rows for one gold table"}
    with pytest.raises(AdapterError, match="cannot be trusted"):
        oa.teds_scores(gold, _result(tmp_path / "debug", [], debug=False), SAVE)
    with pytest.raises(AdapterError, match="missing"):
        oa.teds_scores(gold, tmp_path / "nothing", SAVE)


def test_a_page_with_two_tables_gets_no_invented_mean(gold: dict[str, Any], tmp_path: Path) -> None:
    two = copy.deepcopy(gold)
    p04 = _page(two, P04)
    block_2 = len(p04["blocks"][0]) + 1 + len(p04["blocks"][1]) + 1
    span = [block_2, block_2 + len(p04["blocks"][2])]
    p04["tables"].append({**p04["tables"][0], "text_span": span})
    p04["table_count"] = 2
    p04["table_text_spans"].append(span)
    rows = [_row(_page(two, P01)["image"], 1.0, 1.0), _row(p04["image"], 1.0, 1.0)]
    scores = oa.teds_scores(two, _result(tmp_path, rows), SAVE)
    assert scores["blocked"] == {P04: "2 gold tables; one score per page is not defined"}


def test_cli_prepare_and_collect(gold: dict[str, Any], tmp_path: Path) -> None:
    gold_path = tmp_path / "SYNTHETIC-gold.json"
    gold_path.write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")
    run = {
        "schema": harness.RUN_SCHEMA,
        "arm": {"arm_id": "SYNTHETIC", "capabilities": dict.fromkeys(CAPS, False)},
        "pages": [
            {"page_id": p["page_id"], "status": "SUCCESS", "text": p["text"]} for p in gold["pages"]
        ],
    }
    run_path = tmp_path / "SYNTHETIC-run.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    assert (
        oa.main(
            [
                "prepare",
                "--gold",
                str(gold_path),
                "--run",
                str(run_path),
                "--out",
                str(tmp_path / "inputs"),
            ]
        )
        == 0
    )
    assert (tmp_path / "inputs" / "SYNTHETIC-omnidoc-gt.json").is_file()
    images = [_page(gold, P01)["image"], _page(gold, P04)["image"]]
    result = _result(tmp_path, [_row(images[0], 1.0, 1.0), _row(images[1], 1.0, 1.0)])
    out = tmp_path / "SYNTHETIC-scores.json"
    assert (
        oa.main(
            [
                "collect",
                "--gold",
                str(gold_path),
                "--result-dir",
                str(result),
                "--save-name",
                SAVE,
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert set(json.loads(out.read_text(encoding="utf-8"))["pages"]) == {P01, P04}
