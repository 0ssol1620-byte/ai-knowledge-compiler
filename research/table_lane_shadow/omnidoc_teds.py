"""TEDS for the table-lane shadow receipt, computed by the pinned OmniDocBench evaluator.

    python research/table_lane_shadow/omnidoc_teds.py MANIFEST.json --out RECEIPT.json \
        --evaluator <checkout at the manifest's evaluatorCommit> [--python "py -3.10"]

The receipt is `run_shadow.build_receipt` with its `teds` block filled in here. The evaluator is
run the way the KB-A4 lane ran it (`research/kb1_korean_bench/omnidoc_adapter.py` on the KB
branch; nothing is imported from there): `pdf_validation.py --config <end2end config>` under a
separate Python 3.10, offline, its code unmodified. Its cwd is a fresh temporary directory, so
the `result/` and `logs/` it writes never land in the checkout. One process, no network.

It does not score anything itself. Gold tables and the tables the reader read become
OmniDocBench end2end inputs (one GT table det per gold table, its box from bbox1000 in a
1000x1000 page frame; one markdown file per page holding the reader's tables as HTML), and the
evaluator's own per-table TEDS rows are read back. Anything that keeps the evaluator from
running gives `EVALUATOR_BLOCKED` and no value, never 0: no checkout on disk, HEAD that is not
the manifest's evaluatorCommit, tracked files changed, no interpreter, a failed or timed-out
run, missing output. A table the evaluator logged a TEDS error or timeout for (it writes 0.0
for those) is listed as blocked, not scored.

A gold table the reader produced no table for is scored by the evaluator against an empty
prediction, which its TEDS defines as 0.0 (`src/metrics/table_metric.py`, `evaluate`). That row
is kept, marked `predEmpty`, and stays in the denominator.

OmniDocBench: evaluator code Apache-2.0; the dataset is research-only-non-commercial and is never
read here. Neither licence is patent freedom to operate.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_shadow
from run_shadow import teds_blocked

Json = dict[str, Any]
ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONIOENCODING": "utf-8",
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}
RUN_TIMEOUT_SECONDS = 600
HTML_RULE = (
    "<table><tr><td>: one <tr> per grid row, each cell in the row it starts in, ordered by"
    " column, rowspan/colspan only when above 1, text HTML-escaped. Header rows are not"
    " marked; gold and reader tables get the same rule."
)

# The KB-A4 end2end config (Arena lane fields and timeouts; CDM off), workers=1.
CONFIG = """end2end_eval:
  metrics:
    text_block:
      metric: [Edit_dist]
    display_formula:
      metric: [Edit_dist]
    table:
      metric: [TEDS, Edit_dist]
      teds_workers: 1
    reading_order:
      metric: [Edit_dist]
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: '{gt}'
    prediction:
      data_path: '{pred}'
    match_method: quick_match
    match_workers: 1
    deterministic_matching: false
    quick_match_truncated_timeout_sec: 60
    match_timeout_sec: 90
    timeout_fallback_max_chunk_span: 10
    timeout_fallback_order_penalty: 0.10
"""


def table_html(table: Json) -> str:
    """A located grid (gold or table_read.v1) as the HTML the evaluator's TEDS reads."""
    rows: list[str] = []
    for r in range(table["rowCount"]):
        cells = sorted(
            (c for c in table["cells"] if c["rowIndex0"] == r), key=lambda c: c["columnIndex0"]
        )
        tds = []
        for cell in cells:
            attrs = "".join(
                f' {name}="{cell[key]}"'
                for name, key in (("rowspan", "rowSpan"), ("colspan", "columnSpan"))
                if cell[key] > 1
            )
            tds.append(f"<td{attrs}>{html.escape(cell['text'], quote=False)}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(evaluator: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv: git and the checkout path
            ["git", "-C", str(evaluator), *args],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def write_inputs(pages: list[Json], work: Path, label: str) -> tuple[list[Json], Json]:
    """GT JSON, one markdown per page and the config. Returns (GT pages, input digests)."""
    gt: list[Json] = []
    pred_dir = work / f"{label}markdown"
    pred_dir.mkdir()
    predictions: Json = {}
    for number, page in enumerate(pages):
        stem = f"{label}page-{number:04d}"
        dets = [
            {
                "category_type": "table",
                "html": table_html(table),
                "poly": [x0, y0, x1, y0, x1, y1, x0, y1],
                "order": order,
                "anno_id": order,
                "ignore": False,
            }
            for order, table in enumerate(page["gold"], start=1)
            for x0, y0, x1, y1 in [table["bbox1000"]]
        ]
        gt.append(
            {
                "layout_dets": dets,
                "extra": {"relation": []},
                "page_info": {
                    "page_no": number,
                    "width": 1000,
                    "height": 1000,
                    "image_path": f"{stem}.png",
                    "page_attribute": {},
                },
            }
        )
        text = "\n\n".join(table_html(table) for table in page["read"])
        (pred_dir / f"{stem}.md").write_text(text, encoding="utf-8", newline="\n")
        predictions[f"{stem}.md"] = _sha(text)
    # ASCII-escaped: the evaluator opens the GT file without naming an encoding.
    gt_text = json.dumps(gt, ensure_ascii=True, indent=1) + "\n"
    (work / f"{label}omnidoc-gt.json").write_text(gt_text, encoding="ascii", newline="\n")
    config = CONFIG.format(
        gt=(work / f"{label}omnidoc-gt.json").as_posix().replace("'", "''"),
        pred=pred_dir.as_posix().replace("'", "''"),
    )
    (work / f"{label}omnidoc-config.yaml").write_text(config, encoding="utf-8", newline="\n")
    return gt, {"gtSha256": _sha(gt_text), "predictionSha256": predictions}


def read_scores(pages: list[Json], gt: list[Json], result: Path, save_name: str) -> Json:
    """The evaluator's TEDS rows, one per gold table, or the reason a table has none."""
    try:
        metric = json.loads((result / f"{save_name}_metric_result.json").read_text("utf-8"))
        rows = json.loads((result / f"{save_name}_table_result.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {"error": "the evaluator wrote no table result"}
    table = metric.get("table") if isinstance(metric, dict) else None
    debug = table.get("metric_debug", {}).get("TEDS") if isinstance(table, dict) else None
    if (
        not isinstance(debug, dict)
        or not isinstance(rows, list)
        or not all(isinstance(debug.get(key), list) for key in ("error_cases", "timeout_cases"))
    ):
        return {"error": "the evaluator's TEDS debug is missing, so a 0.0 cannot be trusted"}
    failed = {case.get("img_id") for case in (*debug["error_cases"], *debug["timeout_cases"])}
    scored: list[Json] = []
    blocked: list[Json] = []
    for page, gt_page in zip(pages, gt, strict=True):
        image = gt_page["page_info"]["image_path"]
        for gold, det in zip(page["gold"], gt_page["layout_dets"], strict=True):
            where = {
                "documentId": page["documentId"],
                "pageIndex0": page["pageIndex0"],
                "goldTableId": gold["tableId"],
            }
            found = [
                row
                for row in rows
                if isinstance(row, dict)
                and row.get("img_id") == image
                and row.get("gt") == det["html"]
            ]
            values = found[0].get("metric") if len(found) == 1 else None
            if image in failed:
                blocked.append({**where, "reason": "evaluator logged a TEDS error or timeout"})
            elif not isinstance(values, dict) or not all(
                type(values.get(k)) is float for k in ("TEDS", "TEDS_structure_only")
            ):
                blocked.append({**where, "reason": f"{len(found)} TEDS rows for one gold table"})
            else:
                scored.append(
                    {
                        **where,
                        "teds": values["TEDS"],
                        "tedsStructureOnly": values["TEDS_structure_only"],
                        "predEmpty": not found[0].get("pred"),
                    }
                )
    return {"scored": scored, "blocked": blocked, "interpreter": _interpreter(result, save_name)}


def _interpreter(result: Path, save_name: str) -> Json | None:
    """Python and package versions as the evaluator recorded them; None if it recorded none."""
    try:
        env = json.loads((result / f"{save_name}_runtime_environment.json").read_text("utf-8"))
        return {
            "pythonVersion": env["system"]["python_version"],
            "pythonPackages": env["python_packages"],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def run_evaluator(
    pages: list[Json], commit: object, synthetic: bool, *, evaluator: Path, python: list[str]
) -> Json:
    """The receipt's `teds` block. Every way this can fail is EVALUATOR_BLOCKED, never 0."""
    if not isinstance(commit, str) or not commit:
        return teds_blocked(commit, "the manifest names no evaluatorCommit")
    if not (evaluator / "pdf_validation.py").is_file():
        return teds_blocked(commit, "the evaluator checkout is not on disk")
    if not any(page["gold"] for page in pages):
        return teds_blocked(commit, "no gold table to score")
    head = _git(evaluator, "rev-parse", "HEAD")
    if head != commit:
        return teds_blocked(commit, f"evaluator HEAD {head} is not evaluatorCommit")
    if _git(evaluator, "status", "--porcelain", "--untracked-files=no") != "":
        return teds_blocked(commit, "evaluator tracked files are modified or unreadable")
    label = "SYNTHETIC-" if synthetic else ""
    config_name = f"{label}omnidoc-config.yaml"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")} | ENV
    with tempfile.TemporaryDirectory(prefix="table-lane-teds-") as tmp:
        work = Path(tmp)
        gt, digests = write_inputs(pages, work, label)
        argv = [*python, str(evaluator / "pdf_validation.py"), "--config", str(work / config_name)]
        try:
            done = subprocess.run(  # noqa: S603 - the evaluator the operator named
                argv,
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=RUN_TIMEOUT_SECONDS,
                check=False,
            )
        except OSError as error:
            reason = f"the evaluator interpreter did not start: {type(error).__name__}"
            return teds_blocked(commit, reason)
        except subprocess.TimeoutExpired:
            return teds_blocked(commit, f"the evaluator ran past {RUN_TIMEOUT_SECONDS} s")
        if done.returncode != 0:
            print(done.stdout[-4000:], done.stderr[-4000:], sep="\n", file=sys.stderr)
            return teds_blocked(commit, f"the evaluator exited {done.returncode}")
        scores = read_scores(pages, gt, work / "result", f"{label}markdown_quick_match")
    if "error" in scores:
        return teds_blocked(commit, scores["error"])
    if _git(evaluator, "status", "--porcelain", "--untracked-files=no") != "":
        return teds_blocked(commit, "evaluator tracked files changed during the run")
    scored, unscored = scores["scored"], scores["blocked"]
    if not scored:
        return teds_blocked(commit, "the evaluator scored no gold table")
    gold_tables = sum(len(page["gold"]) for page in pages)
    return {
        "status": "COMPUTED",
        "computed": True,
        "evaluator": run_shadow.EVALUATOR,
        "evaluatorCommit": commit,
        "evaluatorHead": head,
        "evaluatorTrackedFilesUnmodified": True,
        "command": {
            "argv": [*python, "<evaluator>/pdf_validation.py", "--config", f"<work>/{config_name}"],
            "cwd": "<work>",
            "env": ENV,
            "placeholders": {
                "<evaluator>": "the checkout at evaluatorHead",
                "<work>": "a fresh temporary directory holding the inputs below",
            },
            "code": run_shadow._code_ref(Path(__file__)),
        },
        "interpreter": scores["interpreter"],
        "inputs": digests,
        "htmlRule": HTML_RULE,
        "tables": scored,
        "blockedTables": unscored,
        "tedsSum": {
            "teds": sum(row["teds"] for row in scored),
            "tedsStructureOnly": sum(row["tedsStructureOnly"] for row in scored),
            "scoredTables": len(scored),
            "goldTables": gold_tables,
            "of": "gold tables the evaluator scored; predEmpty rows are 0.0 by its rule",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--python", default="py -3.10", help="interpreter for the evaluator")
    args = parser.parse_args(argv)

    def teds(pages: list[Json], commit: object, synthetic: bool) -> Json:
        return run_evaluator(
            pages, commit, synthetic, evaluator=args.evaluator, python=shlex.split(args.python)
        )

    try:
        receipt = run_shadow.build_receipt(args.manifest, teds=teds)
    except run_shadow.ShadowRefused as refused:
        print(f"refused {refused.reason_code}: {refused.detail}", file=sys.stderr)
        return 2
    run_shadow.write_receipt(receipt, args.out)
    if receipt["teds"]["status"] != "COMPUTED":
        print(f"teds EVALUATOR_BLOCKED: {receipt['teds']['reason']}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
