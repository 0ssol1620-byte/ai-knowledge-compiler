# ruff: noqa: E501, RUF001
# The long lines below are markdown table rows and the "-" of a delta label: reflowing a row
# would break the rendered table, and the minus sign is the intended typography.
"""Aggregate evidence/cells.jsonl into evidence/report.md and evidence/report.json.

Rules this file enforces, so a reader cannot mistake what was measured:
  - every rate prints its denominator;
  - a cell that was never run is NOT_RUN and is never filled with a zero;
  - a subject, adapter or judge failure is a zero that STAYS in the denominator;
  - a pairwise delta is computed only over tasks where BOTH arms have a cell (paired n),
    and the paired n is printed next to it;
  - a per-criterion verdict is read from the restricted run store, never guessed, and only its
    INDEX is published -- the rubric text is dataset content and is not redistributed here;
  - packet token counts are NOT_MEASURED: this lane has no tokenizer for the surface's model,
    and an estimated token count would be an invented number.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

EVIDENCE = Path(__file__).resolve().parent / "evidence"
ARMS = ("native_pdf", "compiled_context_pdf")
NOT_RUN = "NOT_RUN"


def load_cells(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def load_verdicts(manifest: dict[str, Any]) -> dict[tuple[str, str, int, str], list[bool]]:
    """Per-criterion judge verdicts, read from the restricted run store named by the manifest.

    They are never written into ``evidence/`` -- only the indices of the criteria that flipped
    between the arms are published, so no rubric text and no answer text leaves the run store.
    """
    out: dict[tuple[str, str, int, str], list[bool]] = {}
    for key, entry in (manifest.get("runs") or {}).items():
        run_id = key.split("/", 1)[0]
        store = Path(str(entry.get("raw_store", "")))
        if not store.is_dir():
            continue
        for record in store.glob("*.json"):
            try:
                payload = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            verdicts = payload.get("judge_verdicts")
            if not isinstance(verdicts, list):
                continue
            out[(run_id, entry["arm"], int(entry["epoch"]), record.stem)] = [
                bool(item.get("pass")) for item in verdicts
            ]
    return out


def case_candidates(
    by_arm: dict[str, list[dict[str, Any]]],
    verdicts: dict[tuple[str, str, int, str], list[bool]],
) -> list[dict[str, Any]]:
    """Tasks where the arms disagree, with the 1-based indices of the criteria that flipped.

    No answer text and no rubric text: a human opens the run store and pulls the excerpts.
    """
    native = {c["task_id"]: c for c in by_arm.get("native_pdf", [])}
    compiled = {c["task_id"]: c for c in by_arm.get("compiled_context_pdf", [])}
    rows: list[dict[str, Any]] = []
    for task_id in sorted(set(native) & set(compiled)):
        left, right = native[task_id], compiled[task_id]
        left_v = verdicts.get((left.get("run_id"), "native_pdf", left.get("epoch"), task_id))
        right_v = verdicts.get(
            (right.get("run_id"), "compiled_context_pdf", right.get("epoch"), task_id)
        )
        gained: list[int] | str = NOT_RUN
        lost: list[int] | str = NOT_RUN
        if left_v is not None and right_v is not None and len(left_v) == len(right_v):
            gained = [
                i for i, (a, b) in enumerate(zip(left_v, right_v, strict=True), 1) if b and not a
            ]
            lost = [
                i for i, (a, b) in enumerate(zip(left_v, right_v, strict=True), 1) if a and not b
            ]
        # Equal totals are not agreement: the arms can pass the same NUMBER of criteria and a
        # different SET of them, which is precisely the case a human should open.
        same_score = int(left.get("criteria_passed") or 0) == int(
            right.get("criteria_passed") or 0
        ) and bool(left.get("all_pass")) == bool(right.get("all_pass"))
        same_criteria = (not gained and not lost) if isinstance(gained, list) else True
        if same_score and same_criteria:
            continue
        rows.append(
            {
                "task_id": task_id,
                "domain": left.get("domain"),
                "pdf_pages": left.get("pdf_pages"),
                "criteria_count": left.get("criteria_count"),
                "native_passed": left.get("criteria_passed"),
                "compiled_passed": right.get("criteria_passed"),
                "native_all_pass": bool(left.get("all_pass")),
                "compiled_all_pass": bool(right.get("all_pass")),
                "criteria_gained_by_compiled": gained,
                "criteria_lost_by_compiled": lost,
                "compiled_adapter_failure": right.get("adapter_failure"),
                "run_store_hint": f"runs/<run_id>/<arm>/e<epoch>/{task_id}.json",
            }
        )
    rows.sort(
        key=lambda row: (
            -abs(int(row["compiled_passed"] or 0) - int(row["native_passed"] or 0)),
            row["task_id"],
        )
    )
    return rows


def packet_stats(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Compiled-packet size against PDF pages. Chars and bytes are measured; tokens are not."""
    rows = [
        {
            "task_id": c["task_id"],
            "pdf_pages": c.get("pdf_pages"),
            "packet_chars": c.get("context_chars"),
            "packet_bytes": c.get("context_bytes"),
            "regions": c.get("context_regions"),
            "claims": c.get("context_claims"),
            "truncated": c.get("context_truncated"),
        }
        for c in cells
        if c.get("arm") == "compiled_context_pdf" and c.get("context_bytes") is not None
    ]
    chars = [r["packet_chars"] for r in rows if isinstance(r["packet_chars"], int)]
    per_page = [
        r["packet_chars"] / r["pdf_pages"]
        for r in rows
        if isinstance(r["packet_chars"], int) and r.get("pdf_pages")
    ]
    if not rows:
        return {"n": 0, "note": "no compiled packet was attached to any scored cell"}
    return {
        "n": len(rows),
        "packet_chars_min": min(chars) if chars else NOT_RUN,
        "packet_chars_median": statistics.median(chars) if chars else NOT_RUN,
        "packet_chars_max": max(chars) if chars else NOT_RUN,
        "packet_chars_total": sum(chars) if chars else NOT_RUN,
        "packet_chars_per_pdf_page_median": statistics.median(per_page) if per_page else NOT_RUN,
        "packets_truncated_by_budget": sum(1 for r in rows if r.get("truncated")),
        "packet_tokens": NOT_RUN,
        "packet_tokens_note": (
            "NOT_MEASURED: this lane has no tokenizer for the surface's model. The measured "
            "token figures are the per-arm input/output totals in the cost table, which cover "
            "the whole conversation, not the packet alone."
        ),
        "rows": rows,
    }


def hardest_documents(by_arm: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The 15 tasks the two arms together did worst on, with both arms side by side.

    The published key names are the ones the benchmark page validates
    (``gates-lanes/gdp/nextjs/lib/gdp-pdf-page-data.ts``). No document title, question or answer
    is carried -- only the task id, which is a pointer into the restricted run store.
    """
    native = {c["task_id"]: c for c in by_arm.get("native_pdf", [])}
    compiled = {c["task_id"]: c for c in by_arm.get("compiled_context_pdf", [])}
    rows: list[dict[str, Any]] = []
    for task_id in sorted(set(native) | set(compiled)):
        nat, com = native.get(task_id), compiled.get(task_id)
        any_cell = nat if nat is not None else com
        if any_cell is None:
            continue
        rows.append(
            {
                "task_id": task_id,
                "domain": any_cell.get("domain"),
                "pages": any_cell.get("pdf_pages"),
                "criteria": any_cell.get("criteria_count"),
                "scanned": bool(
                    com is not None and com.get("adapter_failure") == "scanned_no_text_layer"
                ),
                "native_micro": None if nat is None else float(nat.get("mean_criteria") or 0.0),
                "native_pdf_all_pass": None if nat is None else bool(nat.get("all_pass")),
                "native_pdf_passed": None if nat is None else nat.get("criteria_passed"),
                "compiled_micro": None if com is None else float(com.get("mean_criteria") or 0.0),
                "compiled_context_pdf_all_pass": None if com is None else bool(com.get("all_pass")),
                "compiled_context_pdf_passed": None if com is None else com.get("criteria_passed"),
                "failure": (
                    (nat or {}).get("subject_failure")
                    or (nat or {}).get("judge_failure")
                    or (com or {}).get("adapter_failure")
                    or (com or {}).get("subject_failure")
                    or (com or {}).get("judge_failure")
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            (row["native_micro"] or 0.0) + (row["compiled_micro"] or 0.0),
            -(row["pages"] or 0),
            row["task_id"],
        )
    )
    return rows[:15]


def compile_summary(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """What Product Core actually produced for the compiled arm, per document and in aggregate."""
    rows = [
        {
            "task_id": c["task_id"],
            "pdf_pages": c.get("pdf_pages"),
            "adapter_version": c.get("context_adapter_version"),
            "lifecycle": c.get("context_lifecycle"),
            "regions": c.get("context_regions"),
            "claims": c.get("context_claims"),
            "entities": c.get("context_entities"),
            "relations": c.get("context_relations"),
            "region_citation_unavailable": c.get("context_region_citation_unavailable"),
        }
        for c in cells
        if c.get("arm") == "compiled_context_pdf" and c.get("context_sha256")
    ]
    if not rows:
        return {"n": 0}

    def spread(key: str) -> dict[str, Any]:
        values = [r[key] for r in rows if isinstance(r[key], int)]
        if not values:
            return {"reported_for": 0, "min": NOT_RUN, "median": NOT_RUN, "max": NOT_RUN}
        return {
            "reported_for": len(values),
            "min": min(values),
            "median": statistics.median(values),
            "max": max(values),
            "total": sum(values),
        }

    lifecycles: dict[str, int] = {}
    versions: dict[str, int] = {}
    for row in rows:
        lifecycles[str(row["lifecycle"])] = lifecycles.get(str(row["lifecycle"]), 0) + 1
        versions[str(row["adapter_version"])] = versions.get(str(row["adapter_version"]), 0) + 1
    return {
        "n": len(rows),
        "adapter_versions": versions,
        "lifecycles": lifecycles,
        **{key: spread(key) for key in ("regions", "claims", "entities", "relations")},
        "documents_with_unresolvable_citation": sum(
            1
            for r in rows
            if isinstance(r["region_citation_unavailable"], int)
            and r["region_citation_unavailable"] > 0
        ),
        "rows": rows,
    }


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def total_input(cell: dict[str, Any]) -> int | None:
    """Every input token the surface reported, cached or not.

    ``input_tokens`` alone is near-zero on this surface because Claude Code caches the system
    prompt; reporting it on its own would understate the arm by orders of magnitude.
    """
    parts = [
        cell.get("input_tokens"),
        cell.get("cache_creation_input_tokens"),
        cell.get("cache_read_input_tokens"),
    ]
    known = [p for p in parts if isinstance(p, int)]
    return sum(known) if known else None


def summarize(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Macro/micro over EVERY cell handed in; failures are zeros kept in the denominator."""
    n = len(cells)
    if n == 0:
        return {"n": 0, "macro_all_pass": NOT_RUN, "micro_mean_criteria": NOT_RUN}
    latencies = [
        c["latency_seconds"] for c in cells if isinstance(c.get("latency_seconds"), (int, float))
    ]
    inputs = [t for t in (total_input(c) for c in cells) if t is not None]
    outputs = [c["output_tokens"] for c in cells if isinstance(c.get("output_tokens"), int)]
    micros = [c["cost_usd_micros"] for c in cells if isinstance(c.get("cost_usd_micros"), int)]
    judge_micros = [
        c["judge_cost_usd_micros"] for c in cells if isinstance(c.get("judge_cost_usd_micros"), int)
    ]
    return {
        "n": n,
        "macro_all_pass": sum(1 for c in cells if c.get("all_pass")) / n,
        "macro_all_pass_count": sum(1 for c in cells if c.get("all_pass")),
        "micro_mean_criteria": sum(float(c.get("mean_criteria") or 0.0) for c in cells) / n,
        "criteria_passed_total": sum(int(c.get("criteria_passed") or 0) for c in cells),
        "criteria_total": sum(int(c.get("criteria_count") or 0) for c in cells),
        "subject_failures": sum(1 for c in cells if c.get("subject_failure")),
        "adapter_failures": sum(1 for c in cells if c.get("adapter_failure")),
        "judge_failures": sum(1 for c in cells if c.get("judge_failure")),
        "input_tokens_total": sum(inputs) if inputs else NOT_RUN,
        "input_tokens_reported_for": len(inputs),
        "output_tokens_total": sum(outputs) if outputs else NOT_RUN,
        "latency_p50_seconds": percentile(latencies, 0.50),
        "latency_p95_seconds": percentile(latencies, 0.95),
        "latency_mean_seconds": statistics.mean(latencies) if latencies else None,
        "subject_cost_usd_micros_total": sum(micros) if micros else NOT_RUN,
        "judge_cost_usd_micros_total": sum(judge_micros) if judge_micros else NOT_RUN,
        "cost_complete": all(c.get("cost_complete") for c in cells) if cells else False,
    }


def domain_cut(s: dict[str, Any]) -> str:
    """`macro (k/n) | micro (passed/total)` for one arm in one domain, denominators included."""
    if s["n"] == 0:
        return f"{NOT_RUN} | {NOT_RUN}"
    return (
        f"{pct(s['macro_all_pass'])} ({s['macro_all_pass_count']}/{s['n']}) "
        f"| {pct(s['micro_mean_criteria'])} "
        f"({s['criteria_passed_total']}/{s['criteria_total']})"
    )


def fmt(value: Any, spec: str = "") -> str:
    if value is None:
        return NOT_RUN
    if isinstance(value, str):
        return value
    return format(value, spec) if spec else str(value)


def pct(value: Any) -> str:
    return NOT_RUN if not isinstance(value, (int, float)) else f"{value * 100:.1f}%"


def build(
    cells: list[dict[str, Any]],
    manifest: dict[str, Any],
    verdicts: dict[tuple[str, str, int, str], list[bool]] | None = None,
) -> tuple[str, dict[str, Any]]:
    by_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    for cell in cells:
        by_arm.setdefault(cell["arm"], []).append(cell)
    arms = {arm: summarize(by_arm.get(arm, [])) for arm in ARMS}

    domains = sorted({c["domain"] for c in cells})
    per_domain = {
        domain: {
            arm: summarize([c for c in by_arm.get(arm, []) if c["domain"] == domain])
            for arm in ARMS
        }
        for domain in domains
    }

    paired_ids = {c["task_id"] for c in by_arm.get(ARMS[0], [])} & {
        c["task_id"] for c in by_arm.get(ARMS[1], [])
    }
    paired = {
        arm: summarize([c for c in by_arm.get(arm, []) if c["task_id"] in paired_ids])
        for arm in ARMS
    }
    if paired_ids:
        delta = {
            "paired_n": len(paired_ids),
            "macro_delta_pp": (
                paired["compiled_context_pdf"]["macro_all_pass"]
                - paired["native_pdf"]["macro_all_pass"]
            )
            * 100,
            "micro_delta_pp": (
                paired["compiled_context_pdf"]["micro_mean_criteria"]
                - paired["native_pdf"]["micro_mean_criteria"]
            )
            * 100,
        }
    else:
        delta = {"paired_n": 0, "macro_delta_pp": NOT_RUN, "micro_delta_pp": NOT_RUN}

    report = {
        "manifest": manifest,
        "official_comparable": False,
        "cells_recorded": len(cells),
        "arms": arms,
        "per_domain": per_domain,
        "paired": paired,
        "pairwise_delta": delta,
    }

    lines: list[str] = [
        "# GDP.pdf — does compiled TAVONEL context help a frontier model?",
        "",
        "**NOT OFFICIAL-COMPARABLE.** Three sealed deviations, all deliberate:",
        "",
        "1. **Surface** `claude-code-read-tool` — the official condition disables tools; here the "
        "Read tool is enabled so the model pages through the PDF agentically.",
        "2. **Judge** `claude-opus-5 (non-official)` — the official protocol names "
        "`gemini-3.5-flash`; no Gemini key is available in this lane.",
        "3. **Dataset revision** — the sealed revision's `data.parquet` blob is stranded on a "
        "retired CDN host (403). The run is pinned to the head commit instead; both digests are "
        "in the manifest.",
        "",
        "Nothing here is a same-condition comparison with any published GDP.pdf score, and no "
        "row may be quoted next to one.",
        "",
        "## Run",
        "",
        f"- dataset revision run: `{manifest.get('dataset_revision', NOT_RUN)}`",
        f"- sealed revision (unreachable): `{manifest.get('sealed_revision', NOT_RUN)}`",
        f"- task set digest: `{manifest.get('task_set_digest', NOT_RUN)}`",
        f"- tasks in catalog: {manifest.get('task_count_in_catalog', NOT_RUN)}",
        f"- seed: `{manifest.get('seed', NOT_RUN)}`",
        f"- cells recorded: {len(cells)}",
        "",
        "## Headline, per arm",
        "",
        "Macro = every rubric criterion passed. Micro = mean fraction of criteria passed. A "
        "subject, adapter or judge failure is a zero that stays in the denominator.",
        "",
        "| arm | n (denominator) | macro all-pass | micro mean-criteria | criteria passed | subject fail | adapter fail | judge fail |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm in ARMS:
        s = arms[arm]
        if s["n"] == 0:
            lines.append(
                f"| `{arm}` | 0 | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} |"
            )
            continue
        lines.append(
            f"| `{arm}` | {s['n']} | {pct(s['macro_all_pass'])} ({s['macro_all_pass_count']}/{s['n']}) "
            f"| {pct(s['micro_mean_criteria'])} | {s['criteria_passed_total']}/{s['criteria_total']} "
            f"| {s['subject_failures']} | {s['adapter_failures']} | {s['judge_failures']} |"
        )

    lines += [
        "",
        "## Cost, tokens and latency, per arm",
        "",
        "`api-equivalent list price` is a LIST-PRICE EQUIVALENT for a run billed to a Claude Max "
        "subscription. It is never an invoice amount. Input tokens are the sum of uncached, "
        "cache-creation and cache-read tokens; the arena price snapshot has no cache-token price, "
        "so where `cost complete` is false the money column covers uncached input and output only "
        "and **understates** the run.",
        "",
        "| arm | n | input tokens | output tokens | p50 latency | p95 latency | subject $ (list-equiv) | judge $ (list-equiv) | cost complete |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm in ARMS:
        s = arms[arm]
        if s["n"] == 0:
            lines.append(
                f"| `{arm}` | 0 | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} |"
            )
            continue
        sub = s["subject_cost_usd_micros_total"]
        jud = s["judge_cost_usd_micros_total"]
        lines.append(
            f"| `{arm}` | {s['n']} | {fmt(s['input_tokens_total'], ',')} | {fmt(s['output_tokens_total'], ',')} "
            f"| {fmt(s['latency_p50_seconds'], '.1f')}s | {fmt(s['latency_p95_seconds'], '.1f')}s "
            f"| {'$' + format(sub / 1e6, '.4f') if isinstance(sub, int) else NOT_RUN} "
            f"| {'$' + format(jud / 1e6, '.4f') if isinstance(jud, int) else NOT_RUN} "
            f"| {s['cost_complete']} |"
        )

    lines += [
        "",
        "## Per domain",
        "",
        "Every cell carries its own denominator: macro is `share (all-pass / n)`, micro is "
        "`share (criteria passed / criteria total)`.",
        "",
        "| domain | native n | native macro | native micro | compiled n | compiled macro | compiled micro |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for domain in domains:
        nat, com = per_domain[domain]["native_pdf"], per_domain[domain]["compiled_context_pdf"]
        lines.append(
            f"| {domain} | {nat['n']} | {domain_cut(nat)} | {com['n']} | {domain_cut(com)} |"
        )

    lines += [
        "",
        "## Pairwise delta (compiled_context_pdf − native_pdf)",
        "",
        f"Computed only over the **{delta['paired_n']}** tasks that have a cell in both arms.",
        "",
        "| metric | native | compiled | delta (pp) | paired n |",
        "| --- | --- | --- | --- | --- |",
    ]
    if delta["paired_n"]:
        lines += [
            f"| macro all-pass | {pct(paired['native_pdf']['macro_all_pass'])} "
            f"| {pct(paired['compiled_context_pdf']['macro_all_pass'])} "
            f"| {delta['macro_delta_pp']:+.1f} | {delta['paired_n']} |",
            f"| micro mean-criteria | {pct(paired['native_pdf']['micro_mean_criteria'])} "
            f"| {pct(paired['compiled_context_pdf']['micro_mean_criteria'])} "
            f"| {delta['micro_delta_pp']:+.1f} | {delta['paired_n']} |",
        ]
    else:
        lines.append(f"| macro all-pass | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | 0 |")
        lines.append(f"| micro mean-criteria | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | 0 |")

    # A second denominator, never a replacement headline: it separates "the adapter had no
    # packet for this document" from "the packet did not help". The headline above keeps the
    # adapter failures in, because that is what the sealed failure policy requires.
    packet_ids = {
        c["task_id"] for c in by_arm.get("compiled_context_pdf", []) if not c.get("adapter_failure")
    } & paired_ids
    subset = {
        arm: summarize([c for c in by_arm.get(arm, []) if c["task_id"] in packet_ids])
        for arm in ARMS
    }
    report["compiled_available_subset"] = {"n": len(packet_ids), **{a: subset[a] for a in ARMS}}
    lines += [
        "",
        "### Secondary cut: only the tasks where a compiled packet actually existed",
        "",
        f"**A different denominator (n = {len(packet_ids)}), not a replacement headline.** The "
        "headline above keeps the adapter failures in the denominator, as the sealed failure "
        "policy requires. This cut drops them so that 'no packet existed for this document' can "
        "be told apart from 'the packet did not help'. Quoting this row without its denominator "
        "would be a misreport.",
        "",
        "| metric | native | compiled | delta (pp) | n |",
        "| --- | --- | --- | --- | --- |",
    ]
    if packet_ids:
        macro_d = (
            subset["compiled_context_pdf"]["macro_all_pass"]
            - subset["native_pdf"]["macro_all_pass"]
        ) * 100
        micro_d = (
            subset["compiled_context_pdf"]["micro_mean_criteria"]
            - subset["native_pdf"]["micro_mean_criteria"]
        ) * 100
        report["compiled_available_subset"]["macro_delta_pp"] = macro_d
        report["compiled_available_subset"]["micro_delta_pp"] = micro_d
        lines += [
            f"| macro all-pass | {pct(subset['native_pdf']['macro_all_pass'])} "
            f"| {pct(subset['compiled_context_pdf']['macro_all_pass'])} | {macro_d:+.1f} | {len(packet_ids)} |",
            f"| micro mean-criteria | {pct(subset['native_pdf']['micro_mean_criteria'])} "
            f"| {pct(subset['compiled_context_pdf']['micro_mean_criteria'])} | {micro_d:+.1f} | {len(packet_ids)} |",
        ]
    else:
        lines.append(f"| macro all-pass | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | 0 |")
        lines.append(f"| micro mean-criteria | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | 0 |")

    hardest = hardest_documents(by_arm)
    report["hardest_documents"] = hardest
    lines += [
        "",
        "## Hardest documents",
        "",
        "Ranked by the sum of the two arms’ micro scores, hardest first; at most 15 rows. "
        "`NOT_RUN` means that arm has no cell for the task, which is never the same as a zero. "
        "`scanned?` is true when the compiled arm refused the document as "
        "`scanned_no_text_layer` — a zero that stays in the denominator.",
        "",
        "| task | domain | pages | criteria | scanned? | native pass | compiled pass | native all-pass | compiled all-pass | failure |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in hardest:
        total = row["criteria"]
        native_passed, compiled_passed = (
            row["native_pdf_passed"],
            row["compiled_context_pdf_passed"],
        )
        nat_cell = NOT_RUN if native_passed is None else f"{native_passed}/{total}"
        com_cell = NOT_RUN if compiled_passed is None else f"{compiled_passed}/{total}"
        lines.append(
            f"| `{row['task_id'][:8]}` | {row['domain']} | {row['pages']} | {total} "
            f"| {row['scanned']} | {nat_cell} | {com_cell} "
            f"| {NOT_RUN if row['native_pdf_all_pass'] is None else row['native_pdf_all_pass']} "
            f"| {NOT_RUN if row['compiled_context_pdf_all_pass'] is None else row['compiled_context_pdf_all_pass']} "
            f"| {row['failure'] or '-'} |"
        )

    compiled_stats = compile_summary(cells)
    report["compile_stats"] = compiled_stats
    lines += [
        "",
        "## Compiled arm: what Product Core actually produced",
        "",
        "Per-document compile facts for every cell that had a packet. The full per-document rows "
        "are in the cell ledger under `evidence/`; this is their spread. "
        "`REGION_CITATION_UNAVAILABLE` counts the documents where at least one unit could not be "
        "cited to a region -- the defect that made the superseded v1 adapter degenerate.",
        "",
        f"- documents with a packet: **{compiled_stats.get('n', 0)}**",
        f"- adapter versions in this run: `{compiled_stats.get('adapter_versions', NOT_RUN)}`",
        f"- candidate lifecycle: `{compiled_stats.get('lifecycles', NOT_RUN)}`",
        "- documents with an unresolvable citation: "
        f"**{compiled_stats.get('documents_with_unresolvable_citation', NOT_RUN)}**",
        "",
        "| quantity | reported for | min | median | max | total |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key in ("regions", "claims", "entities", "relations"):
        spread = compiled_stats.get(key) or {}
        lines.append(
            f"| {key} | {spread.get('reported_for', 0)} | {fmt(spread.get('min'), ',')} "
            f"| {fmt(spread.get('median'), ',.0f')} | {fmt(spread.get('max'), ',')} "
            f"| {fmt(spread.get('total'), ',')} |"
        )

    packets = packet_stats(cells)
    report["packet_size"] = packets
    lines += [
        "",
        "## Compiled packet size against PDF pages",
        "",
        "Characters and bytes are measured from the packet files. **Token counts are "
        "NOT_MEASURED**: this lane has no tokenizer for the surface’s model, and an estimate "
        "would be an invented number. The measured token totals are the per-arm figures in the "
        "cost table, which cover the whole conversation rather than the packet alone.",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| packets attached to a scored cell (n) | {packets['n']} |",
    ]
    if packets["n"]:
        lines += [
            f"| packet chars, min | {fmt(packets['packet_chars_min'], ',')} |",
            f"| packet chars, median | {fmt(packets['packet_chars_median'], ',.0f')} |",
            f"| packet chars, max | {fmt(packets['packet_chars_max'], ',')} |",
            f"| packet chars per PDF page, median | {fmt(packets['packet_chars_per_pdf_page_median'], ',.0f')} |",
            f"| packets truncated by the stated budget rule | {packets['packets_truncated_by_budget']} of {packets['n']} |",
            f"| packet tokens | {NOT_RUN} |",
        ]

    cases = case_candidates(by_arm, verdicts or {})
    report["case_candidates"] = cases
    lines += [
        "",
        "## Case candidates (the two arms disagree)",
        "",
        f"**{len(cases)}** paired tasks scored differently. Criterion numbers are 1-based indices "
        "into that task’s rubric in the out-of-repo catalog; rubric text and answer text stay in "
        "the restricted run store and are not reproduced here. A human opens the run-store record "
        "and pulls the excerpts.",
        "",
        "| task | domain | pages | native | compiled | criteria gained by compiled | criteria lost by compiled | adapter |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in cases:
        total = row["criteria_count"]
        gained, lost = row["criteria_gained_by_compiled"], row["criteria_lost_by_compiled"]
        lines.append(
            f"| `{row['task_id'][:8]}` | {row['domain']} | {row['pdf_pages']} "
            f"| {row['native_passed']}/{total} | {row['compiled_passed']}/{total} "
            f"| {gained if isinstance(gained, str) else (gained or '-')} "
            f"| {lost if isinstance(lost, str) else (lost or '-')} "
            f"| {row['compiled_adapter_failure'] or '-'} |"
        )
    if not cases:
        lines.append(f"| {NOT_RUN} | | | | | | | |")

    lines += [
        "",
        "## Case study",
        "",
        "Raw prompts, answers and judge rationales are in the restricted run store, never in this "
        "repository. To fill a case study, open the run-store record for the task and copy in the "
        "excerpts by hand; leave every row below as NOT_RUN until then.",
        "",
        "| field | value |",
        "| --- | --- |",
        f"| task_id | {NOT_RUN} |",
        f"| domain | {NOT_RUN} |",
        f"| question | {NOT_RUN} |",
        f"| native answer excerpt | {NOT_RUN} |",
        f"| compiled answer excerpt | {NOT_RUN} |",
        f"| judge criteria the arms differ on | {NOT_RUN} |",
        f"| evidence locator (page / chunk / evidence id) | {NOT_RUN} |",
        f"| run-store path | {manifest.get('raw_store', NOT_RUN)} |",
        "",
        "## Not run",
        "",
        "The `fixed_control_retrieval_rerank` and `adaptive_router` arms of the sealed four-arm "
        "protocol were not executed in this lane. They are NOT_RUN, not zero.",
        "",
    ]
    return "\n".join(lines), report


def results_summary(report: dict[str, Any]) -> str:
    """One page, Korean and English, stating the result whichever direction it goes."""
    nat = report["arms"]["native_pdf"]
    com = report["arms"]["compiled_context_pdf"]
    delta = report["pairwise_delta"]
    subset = report.get("compiled_available_subset", {})
    packets = report.get("packet_size", {})

    def line(s: dict[str, Any]) -> str:
        if s["n"] == 0:
            return NOT_RUN
        return (
            f"macro {pct(s['macro_all_pass'])} ({s['macro_all_pass_count']}/{s['n']}), "
            f"micro {pct(s['micro_mean_criteria'])} "
            f"({s['criteria_passed_total']}/{s['criteria_total']} criteria)"
        )

    macro_d = delta.get("macro_delta_pp")
    micro_d = delta.get("micro_delta_pp")
    direction_en = (
        NOT_RUN
        if not isinstance(macro_d, (int, float))
        else (
            "the compiled arm did NOT beat the native arm"
            if macro_d < 0
            else (
                "the two arms tied on macro"
                if macro_d == 0
                else "the compiled arm beat the native arm"
            )
        )
    )
    direction_ko = (
        NOT_RUN
        if not isinstance(macro_d, (int, float))
        else (
            "\ucef4\ud30c\uc77c \ucee8\ud14d\uc2a4\ud2b8 \uc554\uc740 \ub124\uc774\ud2f0\ube0c \uc554\uc744 \uc774\uae30\uc9c0 \ubabb\ud588\ub2e4"
            if macro_d < 0
            else (
                "\ub450 \uc554\uc740 macro\uc5d0\uc11c \ub3d9\uc810\uc774\ub2e4"
                if macro_d == 0
                else "\ucef4\ud30c\uc77c \ucee8\ud14d\uc2a4\ud2b8 \uc554\uc774 \ub124\uc774\ud2f0\ube0c \uc554\uc744 \uc774\uacbc\ub2e4"
            )
        )
    )
    delta_text = (
        NOT_RUN
        if not isinstance(macro_d, (int, float))
        else f"macro {macro_d:+.1f} pp, micro {micro_d:+.1f} pp (paired n = {delta['paired_n']})"
    )
    subset_text = (
        NOT_RUN
        if not subset.get("n")
        else (
            f"macro {subset.get('macro_delta_pp', 0):+.1f} pp, "
            f"micro {subset.get('micro_delta_pp', 0):+.1f} pp (n = {subset['n']})"
        )
    )
    return "\n".join(
        [
            "# GDP.pdf two-arm experiment - RESULTS SUMMARY / \uacb0\uacfc \uc694\uc57d",
            "",
            "**NOT OFFICIAL-COMPARABLE / \uacf5\uc2dd \ube44\uad50 \ubd88\uac00.** Surface uses the Read tool, the judge is "
            "Opus and not `gemini-3.5-flash`, and the dataset is pinned to the head revision "
            "because the sealed revision's parquet blob is stranded on a retired CDN. "
            "Full detail in `report.md`.",
            "",
            "## EN",
            "",
            f"- Cells scored: **{report['cells_recorded']}**.",
            f"- `native_pdf`: {line(nat)}.",
            f"- `compiled_context_pdf`: {line(com)}.",
            f"- Paired delta (compiled - native): **{delta_text}**.",
            f"- Result, plainly: **{direction_en}** on this corpus, this surface and this judge.",
            "- Secondary cut, tasks where a compiled packet existed at all (a different "
            f"denominator, not a replacement headline): {subset_text}.",
            f"- Adapter failures kept in the denominator: {com.get('adapter_failures', NOT_RUN)} "
            "documents with no text layer, scored zero, never dropped.",
            f"- Compiled packet size: median {fmt(packets.get('packet_chars_median'), ',.0f')} "
            f"characters, {packets.get('packets_truncated_by_budget', NOT_RUN)} of "
            f"{packets.get('n', 0)} truncated by the stated budget rule. Token counts are "
            "NOT_MEASURED.",
            "",
            "## KO / \ud55c\uad6d\uc5b4",
            "",
            f"- \ucc44\uc810\ub41c \uc140: **{report['cells_recorded']}**\uac1c.",
            f"- `native_pdf`: {line(nat)}.",
            f"- `compiled_context_pdf`: {line(com)}.",
            f"- \uc30d\uc73c\ub85c \ube44\uad50\ud55c \ucc28\uc774(\ucef4\ud30c\uc77c - \ub124\uc774\ud2f0\ube0c): **{delta_text}**.",
            f"- \uacb0\ub860\uc744 \uadf8\ub300\ub85c \uc801\uc73c\uba74: \uc774 \ucf54\ud37c\uc2a4, \uc774 \uc11c\ud398\uc774\uc2a4, \uc774 \ud310\uc815\uc790 \uae30\uc900\uc73c\ub85c **{direction_ko}**.",
            f"- \ubcf4\uc870 \ub2e8\uba74(\ucef4\ud30c\uc77c \ud328\ud0b7\uc774 \uc2e4\uc81c\ub85c \uc874\uc7ac\ud55c \uacfc\uc81c\ub9cc; \ubd84\ubaa8\uac00 \ub2e4\ub974\uba70 \ud5e4\ub4dc\ub77c\uc778 \ub300\uccb4\uac00 \uc544\ub2c8\ub2e4): {subset_text}.",
            f"- \ubd84\ubaa8\uc5d0 \uadf8\ub300\ub85c \ub0a8\uae34 \uc5b4\ub311\ud130 \uc2e4\ud328: \ud14d\uc2a4\ud2b8 \ub808\uc774\uc5b4\uac00 \uc5c6\ub294 "
            f"{com.get('adapter_failures', NOT_RUN)}\uac1c \ubb38\uc11c. 0\uc810 \ucc98\ub9ac\ud558\ub418 \uc81c\uc678\ud558\uc9c0 \uc54a\uc558\ub2e4.",
            f"- \ucef4\ud30c\uc77c \ud328\ud0b7 \ud06c\uae30: \uc911\uc559\uac12 {fmt(packets.get('packet_chars_median'), ',.0f')} \uc790, "
            f"{packets.get('n', 0)}\uac1c \uc911 {packets.get('packets_truncated_by_budget', NOT_RUN)}\uac1c\uac00 \uba85\uc2dc\ub41c "
            "\uc608\uc0b0 \uaddc\uce59\uc73c\ub85c \uc798\ub838\ub2e4. \ud1a0\ud070 \uc218\ub294 \uce21\uc815\ud558\uc9c0 \uc54a\uc558\ub2e4(NOT_MEASURED).",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cells",
        type=Path,
        nargs="+",
        default=[EVIDENCE / "cells.jsonl"],
        help="one or more ledgers; concurrent runs write one file each, never a shared one",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        nargs="+",
        default=[EVIDENCE / "manifest.json"],
        help="one or more manifests; concurrent runs write one each and they are merged here",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="RUN_ID:ARM",
        help=(
            "keep only these (run_id, arm) pairs, e.g. pilot10:native_pdf "
            "pilot10v2:compiled_context_pdf. A superseded run is never silently mixed with the "
            "run that replaced it."
        ),
    )
    parser.add_argument("--out", type=Path, default=EVIDENCE, help="directory for the report")
    args = parser.parse_args()
    keep = {tuple(token.split(":", 1)) for token in args.only} if args.only else None

    seen: set[tuple[Any, ...]] = set()
    cells: list[dict[str, Any]] = []
    for path in args.cells:
        for cell in load_cells(path):
            if keep is not None and (cell.get("run_id"), cell["arm"]) not in keep:
                continue
            key = (cell.get("run_id"), cell["arm"], cell.get("epoch"), cell["task_id"])
            if key in seen:
                continue
            seen.add(key)
            cells.append(cell)
    runs: dict[str, Any] = {}
    for path in args.manifest:
        if path.exists():
            runs.update(json.loads(path.read_text(encoding="utf-8")).get("runs", {}))
    if keep is not None:
        runs = {
            key: entry
            for key, entry in runs.items()
            if (key.split("/", 1)[0], entry.get("arm")) in keep
        }
    # The restricted run store's own path is not a public fact, and report.json is copied into
    # the public site's content directory. Strip every local path before it is written.
    private = ("raw_store", "cells_path")
    runs = {
        key: {k: v for k, v in entry.items() if k not in private} for key, entry in runs.items()
    }
    manifest = dict(next(iter(runs.values()), {}))
    manifest["runs"] = runs
    markdown, report = build(cells, manifest, load_verdicts(manifest))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(markdown, encoding="utf-8")
    (args.out / "RESULTS_SUMMARY.md").write_text(results_summary(report), encoding="utf-8")
    (args.out / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    print(f"cells={len(cells)} -> {args.out / 'report.md'}")
    for arm in ARMS:
        s = report["arms"][arm]
        print(
            f"  {arm:22s} n={s['n']:3d} macro={pct(s['macro_all_pass'])} micro={pct(s['micro_mean_criteria'])}"
        )
    return 0


def demo() -> None:
    cells = [
        {
            "arm": "native_pdf",
            "task_id": "a",
            "domain": "D",
            "criteria_count": 2,
            "criteria_passed": 2,
            "all_pass": True,
            "mean_criteria": 1.0,
            "latency_seconds": 10.0,
            "output_tokens": 5,
            "input_tokens": 1,
            "cache_read_input_tokens": 99,
            "cost_usd_micros": 100,
            "cost_complete": False,
            "pdf_pages": 3,
        },
        {
            "arm": "native_pdf",
            "task_id": "b",
            "domain": "D",
            "criteria_count": 2,
            "criteria_passed": 0,
            "all_pass": False,
            "mean_criteria": 0.0,
            "subject_failure": "TIMEOUT",
            "pdf_pages": 9,
        },
    ]
    s = summarize(cells)
    assert s["n"] == 2, "a failure must stay in the denominator"
    assert s["macro_all_pass"] == 0.5 and s["micro_mean_criteria"] == 0.5
    assert s["subject_failures"] == 1
    assert s["input_tokens_total"] == 100, "input must include cache tokens"
    empty = summarize([])
    assert empty["macro_all_pass"] == NOT_RUN, "an unrun arm must be NOT_RUN, never 0"
    markdown, report = build(cells, {"seed": "s"})
    assert "NOT_RUN" in markdown and "`compiled_context_pdf` | 0" in markdown
    assert report["pairwise_delta"]["paired_n"] == 0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    print("build_report demo ok")


if __name__ == "__main__":
    import sys

    raise SystemExit(demo() if "--demo" in sys.argv else main())
