"""Execute one arm of the GDP.pdf experiment and judge it, on the Opus subscription surface.

Raw prompts, answers and judge rationales stay in the out-of-repo run store. Only digests and
metrics are written under ``evidence/``.

Failure policy, mirrored from the sealed protocol:
  subject failure -> score 0, kept in the denominator
  adapter failure -> score 0, kept in the denominator, blocks promotion
  judge failure   -> score 0, kept in the denominator, blocks promotion
Nothing is ever dropped from a denominator, and a cell that was not run is absent, never zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from surface import AuthExpired, Surface, invoke

SEED = "gdp-pdf-20260921"
# A throttle is an operational failure, so the cell is retried after a wait instead of being
# scored zero. After the last wait the arm stops with a receipt and the cell stays UNRUN, which
# is resumable: a cell that was not run is absent from the ledger, never a zero in it.
RATE_LIMIT_BACKOFF_SECONDS = (60, 180, 420, 900, 1800)
CACHE = Path(r"D:\CodexData\gdp-pdf-cache\8d1efb32cb57baec2265bb84da03b30654761373")
CATALOG_PATH = CACHE / "task_catalog.json"
RAW_ROOT = CACHE / "runs"
EVIDENCE = Path(__file__).resolve().parent / "evidence"

NATIVE_PROMPT = """You are answering an expert question about a document. Answer in English.

The document is a PDF at this absolute path:
{pdf_path}

It has {pages} pages. Use the Read tool to read it. Read accepts at most 20 pages per call, so \
page through the document in ranges until you have read every part relevant to the question.

Question:
{question}

Write a complete, precise answer grounded only in this document. Give the specific values, names, \
dates, section numbers and conditions the document states. If the document does not contain \
something the question asks for, say so explicitly. Do not speculate beyond the document. Output \
the answer only: no preamble, no description of how you read the file.
"""

COMPILED_PROMPT = """You are answering an expert question about a document. Answer in English.

The document is a PDF at this absolute path:
{pdf_path}

It has {pages} pages. Use the Read tool to read it. Read accepts at most 20 pages per call, so \
page through the document in ranges until you have read every part relevant to the question.

A TAVONEL compiled-context packet for the same document is at this absolute path:
{context_path}

Read the packet as well. It was compiled from the document's own content and carries page \
anchors for its units; the PDF remains the authority where they differ.

Question:
{question}

Write a complete, precise answer grounded only in this document. Give the specific values, names, \
dates, section numbers and conditions the document states. If the document does not contain \
something the question asks for, say so explicitly. Do not speculate beyond the document. Output \
the answer only: no preamble, no description of how you read the file.
"""

JUDGE_PROMPT = """You are grading one answer against a rubric. Judge each criterion \
independently and strictly. Do not use any tool; everything you need is below.

QUESTION:
{question}

CRITERIA (each is independent; number them exactly as given):
{criteria}

ANSWER UNDER TEST (everything between the two markers):
--- BEGIN ANSWER ---
{answer}
--- END ANSWER ---

For each criterion decide whether the answer satisfies it. A criterion passes only if the answer \
actually contains what the criterion requires; a plausible but absent or contradicted fact fails. \
Grade only against the criterion text, not against your own expectations.

Reply with a single JSON object and nothing else, no code fence:
{{"1": {{"pass": true, "why": "<=20 words"}}, "2": {{"pass": false, "why": "<=20 words"}}}}
It must contain exactly the keys "1" through "{count}".
"""

PROMPT_DIGESTS = {
    "native_pdf": hashlib.sha256(NATIVE_PROMPT.encode("utf-8")).hexdigest(),
    "compiled_context_pdf": hashlib.sha256(COMPILED_PROMPT.encode("utf-8")).hexdigest(),
    "judge": hashlib.sha256(JUDGE_PROMPT.encode("utf-8")).hexdigest(),
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_digest(obj: Any) -> str:
    return sha256_text(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str))


def ordered_tasks(catalog: dict[str, Any], epoch: int) -> list[dict[str, Any]]:
    """Deterministic per-epoch order from the seed, so drift never always favours one arm."""
    return sorted(catalog["tasks"], key=lambda t: sha256_text(f"{SEED}|{epoch}|{t['task_id']}"))


def parse_judge(text: str, count: int) -> list[dict[str, Any]] | None:
    """Strict: every criterion 1..count present with a boolean. Anything else is a judge failure."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    out = []
    for index in range(1, count + 1):
        entry = raw.get(str(index))
        if not isinstance(entry, dict) or not isinstance(entry.get("pass"), bool):
            return None
        out.append({"pass": entry["pass"], "why": str(entry.get("why", ""))[:200]})
    return out


def judge_cell(
    surface: Surface, task: dict[str, Any], answer: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(judge receipt for the evidence row, raw record for the run store)."""
    criteria = "\n".join(f"{i}. {c}" for i, c in enumerate(task["criteria"], start=1))
    prompt = JUDGE_PROMPT.format(
        question=task["prompt"], criteria=criteria, answer=answer, count=task["criteria_count"]
    )
    receipt = invoke(surface, prompt, [])
    raw = {"judge_prompt": prompt, "judge_text": receipt.get("text")}
    if not receipt["ok"]:
        return {
            "judge_failure": receipt.get("failure", "UNKNOWN"),
            "judge_detail": str(receipt.get("detail"))[:400],
            "judge_wall_seconds": receipt.get("wall_seconds"),
        }, raw
    verdicts = parse_judge(receipt["text"], task["criteria_count"])
    if verdicts is None:
        return {
            "judge_failure": "JUDGE_UNPARSEABLE",
            "judge_detail": receipt["text"][:400],
            "judge_wall_seconds": receipt["wall_seconds"],
        }, raw
    raw["judge_verdicts"] = verdicts
    passed = sum(1 for v in verdicts if v["pass"])
    return {
        "judge_failure": None,
        "judge_model": receipt["reported_model"],
        "judge_wall_seconds": receipt["wall_seconds"],
        "judge_input_tokens": receipt["input_tokens"],
        "judge_output_tokens": receipt["output_tokens"],
        "judge_cost_usd_micros": receipt["api_equivalent_list_price_usd_micros"],
        "judge_receipt_digest": canonical_digest(
            {"prompt_sha256": sha256_text(prompt), "verdicts": verdicts}
        ),
        "criteria_passed": passed,
        "criteria_count": task["criteria_count"],
        "all_pass": passed == task["criteria_count"],
        "mean_criteria": passed / task["criteria_count"],
    }, raw


def run_cell(
    surface: Surface,
    task: dict[str, Any],
    arm: str,
    epoch: int,
    context_dir: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One (task, arm, epoch) cell: subject call, then judge. Returns (evidence row, raw record)."""
    pdf = Path(task["pdf_local_path"])
    cell: dict[str, Any] = {
        "task_id": task["task_id"],
        "task_response_id": task["task_response_id"],
        "domain": task["domain"],
        "pdf_sha256": task["pdf_sha256"],
        "pdf_pages": task["pdf_pages"],
        "prompt_sha256": task["prompt_sha256"],
        "rubric_sha256": task["rubric_sha256"],
        "criteria_count": task["criteria_count"],
        "arm": arm,
        "epoch": epoch,
        "arm_prompt_template_sha256": PROMPT_DIGESTS[arm],
        "judge_prompt_template_sha256": PROMPT_DIGESTS["judge"],
        "criteria_passed": 0,
        "all_pass": False,
        "mean_criteria": 0.0,
        "subject_failure": None,
        "adapter_failure": None,
        "judge_failure": None,
    }

    add_dirs = [pdf.parent]
    if arm == "native_pdf":
        prompt = NATIVE_PROMPT.format(
            pdf_path=pdf, pages=task["pdf_pages"], question=task["prompt"]
        )
    else:
        if context_dir is None:
            raise SystemExit("compiled_context_pdf needs --context-dir")
        index = json.loads((context_dir / "index.json").read_text(encoding="utf-8"))
        entry = index.get(task["task_id"], {})
        if not entry.get("compiled"):
            cell["adapter_failure"] = entry.get("reason", "context_missing")
            return cell, {"adapter_failure": cell["adapter_failure"]}
        context_path = Path(entry["path"])
        stats = entry.get("compile_stats") or {}
        budget = entry.get("packet_budget") or {}
        cell.update(
            context_sha256=entry["packet_sha256"],
            context_bytes=entry["packet_bytes"],
            context_chars=entry.get("packet_chars"),
            context_lines=entry.get("packet_lines"),
            context_manifest_digest=entry["manifest_digest"],
            context_adapter_version=entry["adapter_version"],
            context_lifecycle=entry.get("lifecycle"),
            context_truncated=budget.get("truncated"),
            context_budget_chars=budget.get("budget_chars"),
            context_regions=stats.get("regions"),
            context_claims=stats.get("claim_count"),
            context_entities=stats.get("entity_count"),
            context_relations=stats.get("relation_count"),
            context_region_citation_unavailable=stats.get("region_citation_unavailable"),
        )
        add_dirs.append(context_path.parent)
        prompt = COMPILED_PROMPT.format(
            pdf_path=pdf,
            pages=task["pdf_pages"],
            context_path=context_path,
            question=task["prompt"],
        )

    receipt = invoke(surface, prompt, add_dirs)
    raw = {"prompt": prompt, "answer": receipt.get("text")}
    cell.update(
        subject_model=receipt.get("reported_model"),
        latency_seconds=receipt.get("wall_seconds"),
        input_tokens=receipt.get("input_tokens"),
        output_tokens=receipt.get("output_tokens"),
        cache_creation_input_tokens=receipt.get("cache_creation_input_tokens"),
        cache_read_input_tokens=receipt.get("cache_read_input_tokens"),
        cost_usd_micros=receipt.get("api_equivalent_list_price_usd_micros"),
        cost_complete=receipt.get("api_equivalent_price_complete"),
        num_turns=receipt.get("num_turns"),
    )
    if not receipt["ok"]:
        cell["subject_failure"] = receipt.get("failure", "UNKNOWN")
        cell["subject_detail"] = str(receipt.get("detail"))[:400]
        return cell, raw
    cell["answer_sha256"] = sha256_text(receipt["text"])
    cell["answer_chars"] = len(receipt["text"])

    verdict, judge_raw = judge_cell(surface, task, receipt["text"])
    cell.update(verdict)
    raw.update(judge_raw)
    cell["cell_receipt_digest"] = canonical_digest(
        {
            k: cell.get(k)
            for k in (
                "task_id",
                "arm",
                "epoch",
                "pdf_sha256",
                "prompt_sha256",
                "rubric_sha256",
                "answer_sha256",
                "judge_receipt_digest",
                "criteria_passed",
                "criteria_count",
            )
        }
    )
    return cell, raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=["native_pdf", "compiled_context_pdf"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--limit", type=int, default=10, help="tasks, in the seeded order")
    parser.add_argument("--epoch", type=int, default=1)
    parser.add_argument("--context-dir", type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--cells",
        type=Path,
        default=None,
        help="evidence ledger to append to; one file per concurrent process, never shared",
    )
    args = parser.parse_args()

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    tasks = ordered_tasks(catalog, args.epoch)[: args.limit]
    surface = Surface(timeout_seconds=args.timeout)
    raw_dir = RAW_ROOT / args.run_id / args.arm / f"e{args.epoch}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    cells_path = args.cells or EVIDENCE / "cells.jsonl"
    cells_path.parent.mkdir(parents=True, exist_ok=True)

    done = set()
    if cells_path.exists():
        for line in cells_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((row["run_id"], row["arm"], row["epoch"], row["task_id"]))

    started = time.time()
    for position, task in enumerate(tasks, start=1):
        key = (args.run_id, args.arm, args.epoch, task["task_id"])
        if key in done:
            print(f"[{position}/{len(tasks)}] skip (already recorded) {task['task_id']}")
            continue
        try:
            for attempt, wait in enumerate((*RATE_LIMIT_BACKOFF_SECONDS, None)):
                cell, raw = run_cell(surface, task, args.arm, args.epoch, args.context_dir)
                throttled = "RATE_LIMITED" in (
                    str(cell.get("subject_failure")),
                    str(cell.get("judge_failure")),
                )
                if not throttled:
                    break
                if wait is None:
                    (EVIDENCE / "RATE_LIMITED.json").write_text(
                        json.dumps(
                            {
                                "run_id": args.run_id,
                                "arm": args.arm,
                                "epoch": args.epoch,
                                "task_id": task["task_id"],
                                "stopped_at": time.time(),
                                "attempts": attempt + 1,
                                "detail": str(cell.get("subject_detail"))[:1000],
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    print("RATE_LIMITED after backoff - stopping, resume later", file=sys.stderr)
                    return 3
                print(f"  rate limited, waiting {wait}s (attempt {attempt + 1})", flush=True)
                time.sleep(wait)
        except AuthExpired as exc:
            (EVIDENCE / "AUTH_EXPIRED.json").write_text(
                json.dumps(
                    {
                        "run_id": args.run_id,
                        "arm": args.arm,
                        "epoch": args.epoch,
                        "task_id": task["task_id"],
                        "stopped_at": time.time(),
                        "detail": str(exc)[:1000],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print("AUTH_EXPIRED - stopping", file=sys.stderr)
            return 2
        cell["run_id"] = args.run_id
        cell["seed"] = SEED
        cell["order_position"] = position
        (raw_dir / f"{task['task_id']}.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        with cells_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(cell, sort_keys=True) + "\n")
        print(
            f"[{position}/{len(tasks)}] {task['task_id'][:8]} {task['domain'][:14]:14s} "
            f"pass={cell['criteria_passed']}/{cell['criteria_count']} "
            f"all={cell['all_pass']} {cell.get('latency_seconds', 0):.0f}s "
            f"{cell['subject_failure'] or cell['adapter_failure'] or cell['judge_failure'] or ''}",
            flush=True,
        )

    # One manifest per ledger. Two workers running at once must not read-modify-write the same
    # file, or the entry that loses the race is simply gone from the evidence.
    manifest_path = (
        cells_path.with_suffix(".manifest.json") if args.cells else EVIDENCE / "manifest.json"
    )
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    manifest.setdefault("runs", {})[f"{args.run_id}/{args.arm}/e{args.epoch}"] = {
        "arm": args.arm,
        "epoch": args.epoch,
        "tasks_attempted": len(tasks),
        "seed": SEED,
        "dataset_revision": catalog["run_revision"],
        "sealed_revision": catalog["sealed_revision"],
        "sealed_revision_unreachable": catalog["sealed_revision_unreachable"],
        "task_set_digest": catalog["task_set_digest"],
        "task_count_in_catalog": catalog["task_count"],
        "surface": surface.config(),
        "prompt_template_digests": PROMPT_DIGESTS,
        "judge": "claude-opus-5 (non-official; the official protocol names gemini-3.5-flash)",
        "official_comparable": False,
        "raw_store": str(raw_dir),
        "cells_path": str(cells_path),
        "wall_seconds": time.time() - started,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"done in {time.time() - started:.0f}s -> {cells_path}")
    return 0


def demo() -> None:
    assert parse_judge('{"1":{"pass":true,"why":"x"},"2":{"pass":false}}', 2) == [
        {"pass": True, "why": "x"},
        {"pass": False, "why": ""},
    ]
    assert parse_judge('{"1":{"pass":true}}', 2) is None, "missing criterion must fail the judge"
    assert parse_judge('{"1":{"pass":"yes"}}', 1) is None, "non-boolean must fail the judge"
    assert parse_judge("no json here", 1) is None
    assert parse_judge('prose {"1":{"pass":true}} trailing', 1) == [{"pass": True, "why": ""}]
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    first, second = ordered_tasks(catalog, 1), ordered_tasks(catalog, 1)
    assert [t["task_id"] for t in first] == [t["task_id"] for t in second], "order is not stable"
    assert [t["task_id"] for t in ordered_tasks(catalog, 2)] != [t["task_id"] for t in first]
    print("run demo ok")


if __name__ == "__main__":
    raise SystemExit(demo() if "--demo" in sys.argv else main())
