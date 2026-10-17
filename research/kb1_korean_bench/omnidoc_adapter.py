r"""KB1 gold -> OmniDocBench end2end inputs, for INTERNAL cross-validation only.

Design: KOREAN-BENCHMARK-DESIGN-2026-10-17 §5.3 (M4 TEDS, M5 reading order, M6),
§5.4 rule 6 (evaluator pin), §5.7 (gold), inventory row I-10.

**Internal cross-validation only.** OmniDocBench is research-only-non-commercial:
its *dataset* licence is ``research-only-non-commercial`` and its *evaluator code*
at pin ``193627ae`` is Apache-2.0 (Arena ``evaluator_registry.json``). Those are
separate licences, and neither is patent freedom to operate. This module never
reads, copies or ships the OmniDocBench dataset and never vendors evaluator code:
it writes KB1 gold in the evaluator's input format and reads the evaluator's
output back. No number it helps produce is a public number; the KB1 primary
metrics (M1, M6) come from the KB1 harness, never from OmniDocBench.

Conversion rules (``to_omnidoc_gt``), each refusing rather than guessing:

* one ``layout_det`` per gold block, in gold reading order (``order`` 1..n);
* a block that is exactly a gold table's ``text_span`` becomes a ``table`` det
  carrying the gold HTML and the drawn table box; every other block is a
  ``text_block``. Gold has no finer layout category, so none is invented;
* a text det's ``poly`` is the union of the block's own gold line boxes. The page
  text must be its blocks joined by ``\n`` and each block its consecutive lines
  joined by ``\n``; otherwise the block box cannot be derived and the page is
  refused (no fabricated bbox);
* a seal has no OmniDocBench category and is not emitted (M7 is harness-only);
* ``page_attribute`` is empty: the evaluator's language enum has no Korean.

Symbol blind spot (design I-10). The pinned evaluator scores text after
``replace_textcircle`` and ``clean_string`` (``src/core/preprocess/
data_preprocess.py`` lines 80-82, 92-99 and 776-782 at 193627ae). Circled
digits and letters are *folded* into plain ones (``①`` -> ``1``, ``⑳`` -> ``20``);
everything outside ``[\w\u4e00-\u9fff]`` is *deleted*, which includes ``※ 「 」
『 』 ㈜ · ○ □``, the tortoise-shell brackets U+3014/U+3015 and also ASCII
punctuation, so ``1,234,000원`` and ``1234000원``, or ``-2.50%`` and ``250%``,
are the same text to it. Hangul, hanja and ``ㆍ`` (U+318D, a Hangul letter)
survive. ``omnidoc_text_view`` restates that rule so CI can pin it without the
evaluator; the KB-A4 receipt checks the restatement against the pinned code.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .harness import _nfc, _strip_ws, parse_gold, parse_run

EVALUATOR_REPOSITORY = "https://github.com/opendatalab/OmniDocBench.git"
EVALUATOR_PIN = "193627ae9e97d89188468ed1ee3b7a856ff76044"
EVALUATOR_LICENSE = "Apache-2.0 (evaluator code only)"
DATASET_LICENSE = "research-only-non-commercial (OmniDocBench dataset; never read here)"
ADAPTER_REVISION = "kb1-omnidoc-adapter-r1"
USE = "internal_cross_validation_only"
IMAGE_EXT = (".png", ".jpg")

# Restatement of the pinned evaluator's text normalisation (see module docstring).
_CIRCLED = {chr(0x2460 + i): str(i + 1) for i in range(20)}
_CIRCLED.update({chr(0x24D0 + i): chr(ord("a") + i) for i in range(26)})
_CIRCLED.update({chr(0x24B6 + i): chr(ord("A") + i) for i in range(26)})
_TEXTCIRCLED = re.compile(r"\\textcircled\s*\{\s*([^{}]+?)\s*\}")
_INLINE_FORMULA = re.compile(r"\$(.*?)\$|\\\((.*?)\\\)")
_REMOVED_TOKENS = ("\\t", "\\n", "\t", "\n", "/t", "/n")
_DELETED = re.compile(r"[^\w\u4e00-\u9fff]")


class AdapterError(ValueError):
    """KB1 gold or evaluator output cannot be converted without guessing."""


def omnidoc_text_view(text: str) -> str:
    """What the pinned evaluator's text Edit_dist compares for ``text``.

    Text with an inline-formula delimiter is refused: the evaluator routes it
    through a LaTeX-to-text path this restatement does not model.
    """
    if _INLINE_FORMULA.search(text):
        raise AdapterError("inline formula delimiters ($...$, \\(...\\)) are not modelled")
    text = _TEXTCIRCLED.sub(lambda m: m.group(1).strip(), text)
    text = "".join(_CIRCLED.get(char, char) for char in text)
    for token in _REMOVED_TOKENS:
        text = text.replace(token, "")
    return _DELETED.sub("", text)


def symbol_blind_spot(text: str) -> dict[str, Counter[str]]:
    """Characters the KB1 harness scores (M1, whitespace removed) that the evaluator
    deletes or folds into another character, counted per character."""
    chars = _strip_ws(_nfc(text))[0]
    views = [omnidoc_text_view(char) for char in chars]
    if "".join(views) != omnidoc_text_view(chars):
        raise AdapterError("text has a multi-character evaluator rule; a per-character view lies")
    deleted: Counter[str] = Counter()
    folded: Counter[str] = Counter()
    for char, view in zip(chars, views, strict=True):
        if not view:
            deleted[char] += 1
        elif view != char:
            folded[char] += 1
    return {"deleted": deleted, "folded": folded}


# ------------------------------------------------------------------ gold -> GT


def _union(boxes: Sequence[Sequence[float]]) -> list[float]:
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _poly(box: Sequence[float]) -> list[float]:
    x0, y0, x1, y1 = (float(v) for v in box)
    return [x0, y0, x1, y0, x1, y1, x0, y1]


def _image_name(raw: Mapping[str, Any], page_id: str) -> str:
    image = raw.get("image")
    # The evaluator finds a prediction by dropping the last four characters.
    if not isinstance(image, str) or Path(image).name != image or image[-4:] not in IMAGE_EXT:
        raise AdapterError(f"gold page {page_id}: 'image' must be a bare .png/.jpg file name")
    return image


def _page_size(gold: Mapping[str, Any]) -> tuple[int, int]:
    frame = gold.get("coordinate_frame")
    size = frame.get("page_size_px") if isinstance(frame, Mapping) else None
    if (
        not isinstance(frame, Mapping)
        or frame.get("unit") != "pixel"
        or not isinstance(size, list)
        or len(size) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in size)
    ):
        raise AdapterError("gold needs coordinate_frame {unit: pixel, page_size_px: [w, h]}")
    return size[0], size[1]


def _page_dets(raw: Mapping[str, Any], page_id: str) -> list[dict[str, Any]]:
    text, blocks = raw["text"], raw.get("blocks") or []
    lines = raw.get("lines") or []
    if not blocks or "\n".join(blocks) != text:
        raise AdapterError(f"gold page {page_id}: text is not its blocks joined by newlines")
    tables: dict[tuple[int, int], Mapping[str, Any]] = {}
    for table in raw.get("tables") or []:
        span, box = table.get("text_span"), table.get("bbox")
        if not (
            isinstance(table.get("html"), str)
            and isinstance(span, list)
            and len(span) == 2
            and all(isinstance(v, int) for v in span)
            and isinstance(box, list)
            and len(box) == 4
        ):
            raise AdapterError(f"gold page {page_id}: a table needs html, text_span and bbox")
        tables[(span[0], span[1])] = table
    if len(tables) != raw.get("table_count", 0):
        raise AdapterError(f"gold page {page_id}: table_count does not match tables[]")
    dets: list[dict[str, Any]] = []
    line_at, offset = 0, 0
    for order, block in enumerate(blocks, start=1):
        parts = block.split("\n")
        own = lines[line_at : line_at + len(parts)]
        if [line["text"] for line in own] != parts:
            raise AdapterError(
                f"gold page {page_id}: block {order} is not its consecutive gold lines,"
                " so its box cannot be derived"
            )
        line_at += len(parts)
        det: dict[str, Any] = {"order": order, "anno_id": order, "ignore": False}
        table = tables.pop((offset, offset + len(block)), None)
        if table is not None:
            det |= {"category_type": "table", "html": table["html"], "poly": _poly(table["bbox"])}
        else:
            det |= {
                "category_type": "text_block",
                "text": block,
                "poly": _poly(_union([line["bbox"] for line in own])),
            }
        dets.append(det)
        offset += len(block) + 1
    if line_at != len(lines) or tables:
        raise AdapterError(
            f"gold page {page_id}: {len(lines) - line_at} lines outside any block,"
            f" {len(tables)} table spans that are not exactly one block"
        )
    return dets


def to_omnidoc_gt(gold: Mapping[str, Any]) -> list[dict[str, Any]]:
    """KB1 gold (``tavonel.kb1.gold.v1``) as OmniDocBench end2end GT pages."""
    parse_gold(gold)  # the KB1 gold contract first: schema, ids, PUA, lines, spans
    width, height = _page_size(gold)
    pages: list[dict[str, Any]] = []
    stems: set[str] = set()
    for page_no, raw in enumerate(gold["pages"]):
        page_id = raw["page_id"]
        image = _image_name(raw, page_id)
        if image[:-4] in stems:
            raise AdapterError(f"gold page {page_id}: two pages map to the stem {image[:-4]!r}")
        stems.add(image[:-4])
        pages.append(
            {
                "layout_dets": _page_dets(raw, page_id),
                "extra": {"relation": []},
                "page_info": {
                    "page_no": page_no,
                    "width": width,
                    "height": height,
                    "image_path": image,
                    "page_attribute": {},
                    "kb1_page_id": page_id,
                    "kb1_family_id": raw["family_id"],
                    "label": "SYNTHETIC" if raw.get("synthetic") else None,
                },
            }
        )
    return pages


# --------------------------------------------------------------- evaluator inputs


def end2end_config(gt_path: Path, prediction_dir: Path, *, workers: int = 4) -> str:
    """End2end config with the Arena lane's fields and timeouts (TEDS and Edit_dist only;
    CDM is off because it needs TeX). ``deterministic_matching`` is carried for parity
    with the Arena config; the pinned evaluator does not read it."""

    def quoted(path: Path) -> str:
        return path.resolve().as_posix().replace("'", "''")

    return f"""end2end_eval:
  metrics:
    text_block:
      metric: [Edit_dist]
    display_formula:
      metric: [Edit_dist]
    table:
      metric: [TEDS, Edit_dist]
      teds_workers: {workers}
    reading_order:
      metric: [Edit_dist]
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: '{quoted(gt_path)}'
    prediction:
      data_path: '{quoted(prediction_dir)}'
    match_method: quick_match
    match_workers: {workers}
    deterministic_matching: false
    quick_match_truncated_timeout_sec: 60
    match_timeout_sec: 90
    timeout_fallback_max_chunk_span: 10
    timeout_fallback_order_penalty: 0.10
"""


def write_inputs(
    gold: Mapping[str, Any], predictions: Mapping[str, str], dest: Path, *, workers: int = 4
) -> dict[str, Path]:
    """Write GT JSON, one ``<image stem>.md`` per gold page and the config into ``dest``.

    Every gold page needs a prediction entry (``""`` for a page with no output),
    and nothing else may be passed; ``dest`` must be empty or absent. The GT is
    written ASCII-escaped because the evaluator opens it without an encoding.
    """
    gt = to_omnidoc_gt(gold)
    ids = [page["page_info"]["kb1_page_id"] for page in gt]
    missing, extra = sorted(set(ids) - set(predictions)), sorted(set(predictions) - set(ids))
    if missing or extra:
        raise AdapterError(
            f"predictions must cover every gold page: missing {missing}, unknown {extra}"
        )
    if dest.exists() and any(dest.iterdir()):
        raise AdapterError(f"{dest} is not empty; refusing to mix runs")
    label = "SYNTHETIC-" if all(page["page_info"]["label"] for page in gt) else ""
    pred_dir = dest / f"{label}markdown"
    pred_dir.mkdir(parents=True)
    for page in gt:
        stem = page["page_info"]["image_path"][:-4]
        text = predictions[page["page_info"]["kb1_page_id"]]
        (pred_dir / f"{stem}.md").write_text(text, encoding="utf-8", newline="\n")
    gt_path = dest / f"{label}omnidoc-gt.json"
    gt_path.write_text(json.dumps(gt, ensure_ascii=True, indent=1) + "\n", encoding="ascii")
    config = dest / f"{label}omnidoc-config.yaml"
    config.write_text(end2end_config(gt_path, pred_dir, workers=workers), encoding="utf-8")
    return {"gt": gt_path, "predictions": pred_dir, "config": config}


def run_predictions(run: Mapping[str, Any], gold: Mapping[str, Any]) -> dict[str, str]:
    """A KB1 run's SUCCESS text per gold page; other statuses predict an empty page."""
    _, _, rows = parse_run(run, [page.page_id for page in parse_gold(gold)])
    return {pid: row.text if row.status == "SUCCESS" else "" for pid, row in rows.items()}


# ----------------------------------------------------------- evaluator -> harness


def _read(path: Path) -> Any:
    if not path.is_file():
        raise AdapterError(f"evaluator output {path.name} is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def teds_scores(gold: Mapping[str, Any], result_dir: Path, save_name: str) -> dict[str, Any]:
    """The evaluator's per-table TEDS as the harness's ``evaluator_scores`` (M4).

    A page is left out, and listed under ``blocked``, when the evaluator logged a
    TEDS error or timeout for it (it writes 0.0 for those, which is not a score),
    when it has more than one gold table (the harness takes one score per page and
    no mean is invented), or when no TEDS row came back. The harness then reports
    EVALUATOR_BLOCKED for it. Values are passed through unclamped.
    """
    table = _read(result_dir / f"{save_name}_metric_result.json").get("table")
    debug = table.get("metric_debug", {}).get("TEDS") if isinstance(table, Mapping) else None
    if not isinstance(debug, Mapping) or not all(
        isinstance(debug.get(key), list) for key in ("error_cases", "timeout_cases")
    ):
        raise AdapterError("metric_result.json has no table TEDS debug; a 0.0 cannot be trusted")
    failed = {case.get("img_id") for case in (*debug["error_cases"], *debug["timeout_cases"])}
    rows: dict[str, list[dict[str, Any]]] = {}
    for sample in _read(result_dir / f"{save_name}_table_result.json"):
        rows.setdefault(str(sample.get("img_id")), []).append(sample)

    pages: dict[str, dict[str, float]] = {}
    blocked: dict[str, str] = {}
    for gt_page in to_omnidoc_gt(gold):
        info = gt_page["page_info"]
        tables = sum(d["category_type"] == "table" for d in gt_page["layout_dets"])
        if not tables:
            continue
        page_id, image = info["kb1_page_id"], info["image_path"]
        found = rows.get(image, [])
        metric = found[0].get("metric") if len(found) == 1 else None
        if image in failed:
            blocked[page_id] = "evaluator logged a TEDS error or timeout"
        elif tables > 1:
            blocked[page_id] = f"{tables} gold tables; one score per page is not defined"
        elif not isinstance(metric, Mapping) or not all(
            isinstance(metric.get(k), int | float) for k in ("TEDS", "TEDS_structure_only")
        ):
            blocked[page_id] = f"{len(found)} TEDS rows for one gold table"
        else:
            pages[page_id] = {
                "teds": float(metric["TEDS"]),
                "teds_struct": float(metric["TEDS_structure_only"]),
            }
    return {
        "evaluator": {
            "name": "omnidocbench",
            "repository": EVALUATOR_REPOSITORY,
            "main_pin": EVALUATOR_PIN,
            "license": EVALUATOR_LICENSE,
            "dataset_license": DATASET_LICENSE,
            "adapter_revision": ADAPTER_REVISION,
            "use": USE,
            "save_name": save_name,
        },
        "pages": pages,
        "blocked": blocked,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KB1 <-> OmniDocBench (internal cross-check).")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="gold + KB1 run -> evaluator inputs")
    prepare.add_argument("--gold", type=Path, required=True)
    prepare.add_argument("--run", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    collect = sub.add_parser("collect", help="evaluator results -> harness evaluator_scores")
    collect.add_argument("--gold", type=Path, required=True)
    collect.add_argument("--result-dir", type=Path, required=True)
    collect.add_argument("--save-name", required=True)
    collect.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    if args.command == "prepare":
        run = json.loads(args.run.read_text(encoding="utf-8"))
        paths = write_inputs(gold, run_predictions(run, gold), args.out)
        print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))
    else:
        scores = teds_scores(gold, args.result_dir, args.save_name)
        args.out.write_text(json.dumps(scores, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
