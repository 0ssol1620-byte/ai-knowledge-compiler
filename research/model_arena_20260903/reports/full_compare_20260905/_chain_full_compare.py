"""Full-compare chain: wait OmniDoc -> prepare+score olmOCR -> prepare+score ParseBench.

Excludes infinity_parser2_pro (FOUNDER_EXCLUDED). Idempotent: skips models with
successful run_summary. Does not kill live OmniDoc supervisors.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
REPORT = ROOT / "reports" / "full_compare_20260905"
ARENA_PY = Path(r"D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe")

OMNI_RAW = REPORT / "omnidoc_raw"
OLM_RAW = REPORT / "olmocr_raw"
PB_RAW = REPORT / "parsebench_raw"
CHAIN_LOG = REPORT / "chain_full_compare.log"
CHAIN_STATE = REPORT / "chain_state.json"
STATUS_MD = REPORT / "STATUS_CHAIN.md"

MAIN_MODELS = [
    "paddleocr_vl_1_6",
    "deepseek_ocr2",
    "hpd_parsing",
    "mineru_pipeline",
    "mineru_vlm",
    "monkeyocrv2_b",
    "ovisocr2",
    "olmocr2",
    "unlimited_ocr",
    "opus5_subscription",
    "glm_ocr",
    "infinity_parser2_flash",
]
EXCLUDED = {"infinity_parser2_pro"}

GT_OMNI = Path(
    r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\omnidocbench\OmniDocBench.json"
)
GT_OLM = Path(
    r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\olmocr-bench\bench_data"
)
GT_OLM_PDFS = GT_OLM / "pdfs"
GT_PB = Path(
    r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\parsebench\docs"
)

POLL_SEC = 60


def now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with CHAIN_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_state(phase: str, extra: dict | None = None) -> None:
    payload = {
        "updated_kst": now(),
        "phase": phase,
        "main_models": MAIN_MODELS,
        "excluded": sorted(EXCLUDED),
    }
    if extra:
        payload.update(extra)
    CHAIN_STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_status_md(phase: str, notes: list[str]) -> None:
    omni_done = [m for m in MAIN_MODELS if bench_done("omnidoc", m)]
    olm_done = [m for m in MAIN_MODELS if bench_done("olmocr", m)]
    pb_done = [m for m in MAIN_MODELS if bench_done("parsebench", m)]
    lines = [
        f"# Full-compare chain status",
        f"",
        f"Updated: **{now()} KST**",
        f"Phase: `{phase}`",
        f"Cloud cost: **$0** (local CPU). Pro excluded.",
        f"",
        f"| Bench | Done / Main |",
        f"|---|---|",
        f"| OmniDoc | {len(omni_done)}/{len(MAIN_MODELS)} |",
        f"| olmOCR | {len(olm_done)}/{len(MAIN_MODELS)} |",
        f"| ParseBench | {len(pb_done)}/{len(MAIN_MODELS)} |",
        f"",
        f"### OmniDoc done",
        f"`{', '.join(omni_done) or '(none)'}`",
        f"",
        f"### OmniDoc pending",
        f"`{', '.join(m for m in MAIN_MODELS if m not in omni_done) or '(none)'}`",
        f"",
        f"### olmOCR done",
        f"`{', '.join(olm_done) or '(none)'}`",
        f"",
        f"### ParseBench done",
        f"`{', '.join(pb_done) or '(none)'}`",
        f"",
        f"### Notes",
    ]
    for n in notes[-30:]:
        lines.append(f"- {n}")
    STATUS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def raw_root(bench: str) -> Path:
    if bench == "omnidoc":
        return OMNI_RAW
    if bench == "olmocr":
        return OLM_RAW
    if bench == "parsebench":
        return PB_RAW
    raise ValueError(bench)


def bench_done(bench: str, model: str) -> bool:
    rs = raw_root(bench) / model / "run_summary.json"
    if not rs.is_file():
        # also accept scores/<model>/<bench>/evaluator_raw markers for parsebench via arena.scoring
        if bench == "parsebench":
            alt = ROOT / "scores" / model / "parsebench" / "chain_run_summary.json"
            if alt.is_file():
                try:
                    d = json.loads(alt.read_text(encoding="utf-8"))
                    return d.get("returncode") == 0
                except Exception:
                    return False
        if bench == "olmocr":
            # parallel driver writes olmocr_raw; also check official in scores
            alt = ROOT / "scores" / model / "olmocr" / "evaluator_raw" / "benchmark" / "official-result.json"
            rs2 = OLM_RAW / model / "run_summary.json"
            if rs2.is_file():
                try:
                    d = json.loads(rs2.read_text(encoding="utf-8"))
                    return d.get("returncode") == 0
                except Exception:
                    return False
            return alt.is_file()
        return False
    try:
        d = json.loads(rs.read_text(encoding="utf-8"))
    except Exception:
        return False
    if bench == "omnidoc":
        return d.get("returncode") == 0 and bool(d.get("metric_result_exists"))
    return d.get("returncode") == 0


def prepared(bench: str, model: str) -> bool:
    base = ROOT / "scores" / model / bench / "evaluator_input"
    if not base.is_dir():
        return False
    if bench == "omnidoc":
        return (base / "markdown").is_dir()
    # any non-empty content
    try:
        return any(base.iterdir())
    except OSError:
        return False


def list_python_cmdlines() -> list[str]:
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "ForEach-Object { $_.CommandLine }"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    return lines


def omni_supervisors_alive() -> list[str]:
    hits = []
    for cl in list_python_cmdlines():
        low = cl.lower()
        if "pdf_validation" in low and "omnidoc" in low:
            hits.append("pdf_validation")
        if "_parallel_omnidoc.py" in low or "_priority_omnidoc" in low:
            hits.append(Path(cl).name if False else "omnidoc_driver")
            # keep short tag
            if "_priority_omnidoc_flash" in low:
                hits.append("priority_flash")
            elif "_priority_omnidoc_opus" in low:
                hits.append("priority_opus_glm")
            elif "_parallel_omnidoc.py" in low:
                hits.append("parallel_omnidoc")
            elif "_priority_omnidoc_olmocr_unlimited" in low:
                hits.append("priority_olm_unlim")
    # unique preserve
    out, seen = [], set()
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def run_cmd(args: list[str], cwd: Path, log_stem: str, timeout: int | None = None) -> int:
    out_p = REPORT / f"{log_stem}.out.log"
    err_p = REPORT / f"{log_stem}.err.log"
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    log(f"RUN {' '.join(args)}")
    with out_p.open("a", encoding="utf-8", errors="replace") as out_h, err_p.open(
        "a", encoding="utf-8", errors="replace"
    ) as err_h:
        out_h.write(f"\n==== {now()} ====\n")
        err_h.write(f"\n==== {now()} ====\n")
        out_h.flush()
        err_h.flush()
        try:
            proc = subprocess.run(
                args,
                cwd=str(cwd),
                stdout=out_h,
                stderr=err_h,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=timeout,
            )
            return proc.returncode
        except subprocess.TimeoutExpired:
            log(f"TIMEOUT {log_stem}")
            return 124


def qa_prepare(model: str, bench: str, gt: Path) -> dict:
    """Run qa then prepare. Return outcome dict; never raises."""
    if prepared(bench, model):
        return {"model": model, "benchmark": bench, "status": "already_prepared"}
    rc_qa = run_cmd(
        [str(ARENA_PY), "-m", "arena.scoring", "qa", "--model", model, "--benchmark", bench],
        ROOT,
        f"chain_qa_{bench}_{model}",
        timeout=1800,
    )
    if rc_qa != 0:
        return {"model": model, "benchmark": bench, "status": "qa_red", "qa_rc": rc_qa}
    gt_arg = str(gt)
    # scoring CLI wants olmocr gt ending in bench_data/pdfs for some paths; prepare batch used bench_data
    if bench == "olmocr":
        gt_arg = str(GT_OLM)
    rc_prep = run_cmd(
        [
            str(ARENA_PY),
            "-m",
            "arena.scoring",
            "prepare",
            "--model",
            model,
            "--benchmark",
            bench,
            "--gt-path",
            gt_arg,
        ],
        ROOT,
        f"chain_prepare_{bench}_{model}",
        timeout=3600,
    )
    ok = prepared(bench, model) and rc_prep == 0
    return {
        "model": model,
        "benchmark": bench,
        "status": "prepared" if ok else "prepare_failed",
        "prepare_rc": rc_prep,
    }


def wait_omnidoc(notes: list[str]) -> None:
    log("PHASE wait_omnidoc")
    save_state("wait_omnidoc")
    while True:
        pending = [m for m in MAIN_MODELS if not bench_done("omnidoc", m)]
        alive = omni_supervisors_alive()
        write_status_md(
            "wait_omnidoc",
            notes
            + [
                f"omni pending={pending}",
                f"alive={alive}",
            ],
        )
        save_state(
            "wait_omnidoc",
            {"omni_pending": pending, "omni_alive": alive},
        )
        if not pending:
            log("OmniDoc all main models done")
            notes.append("OmniDoc wave complete for main board")
            break
        if alive:
            log(f"OmniDoc waiting: pending={pending} alive={alive}")
            time.sleep(POLL_SEC)
            continue
        # no supervisors but pending -> launch remaining
        log(f"OmniDoc supervisors idle; launching remaining {pending}")
        notes.append(f"relaunch OmniDoc for {pending}")
        rc = run_cmd(
            [str(ARENA_PY), "-u", str(REPORT / "_parallel_omnidoc.py"), *pending],
            REPORT,
            "chain_omni_remaining",
            timeout=None,
        )
        log(f"OmniDoc remaining wave rc={rc}")
        # loop to re-check
        if all(bench_done("omnidoc", m) for m in pending):
            break
        # if still pending after launch exited, don't tight-loop forever — wait once then retry once more
        still = [m for m in pending if not bench_done("omnidoc", m)]
        if still:
            log(f"OmniDoc still pending after launch: {still}; will retry after sleep")
            time.sleep(POLL_SEC)
            # second attempt
            still = [m for m in MAIN_MODELS if not bench_done("omnidoc", m)]
            if still and not omni_supervisors_alive():
                run_cmd(
                    [str(ARENA_PY), "-u", str(REPORT / "_parallel_omnidoc.py"), *still],
                    REPORT,
                    "chain_omni_remaining_retry",
                )
            # accept incomplete after retry — mark and continue so later benches still run
            final_pending = [m for m in MAIN_MODELS if not bench_done("omnidoc", m)]
            if final_pending:
                notes.append(f"OmniDoc incomplete after retries: {final_pending}; continuing chain")
                log(notes[-1])
                break
    # refresh comparison
    run_cmd([str(ARENA_PY), str(REPORT / "_build_comparison.py")], REPORT, "chain_build_comparison")


def score_olmocr(notes: list[str]) -> None:
    log("PHASE prepare+score olmocr")
    save_state("olmocr")
    prep_results = []
    for m in MAIN_MODELS:
        r = qa_prepare(m, "olmocr", GT_OLM)
        prep_results.append(r)
        log(f"olmocr prepare {m}: {r.get('status')}")
        notes.append(f"olmocr {m}: {r.get('status')}")
        write_status_md("olmocr_prepare", notes)
    ready = [m for m in MAIN_MODELS if prepared("olmocr", m) and not bench_done("olmocr", m)]
    already = [m for m in MAIN_MODELS if bench_done("olmocr", m)]
    log(f"olmocr already={already} to_score={ready}")
    if ready:
        # expand parallel driver models via argv
        rc = run_cmd(
            [str(ARENA_PY), "-u", str(REPORT / "_parallel_olmocr.py"), *ready],
            REPORT,
            "chain_olmocr_score",
        )
        notes.append(f"olmocr score wave rc={rc} models={ready}")
    save_state("olmocr_done", {"prep": prep_results})
    write_status_md("olmocr_done", notes)


def score_parsebench(notes: list[str]) -> None:
    log("PHASE prepare+score parsebench")
    save_state("parsebench")
    PB_RAW.mkdir(parents=True, exist_ok=True)
    prep_results = []
    for m in MAIN_MODELS:
        r = qa_prepare(m, "parsebench", GT_PB)
        prep_results.append(r)
        log(f"parsebench prepare {m}: {r.get('status')}")
        notes.append(f"parsebench {m}: {r.get('status')}")
        write_status_md("parsebench_prepare", notes)

    for m in MAIN_MODELS:
        if bench_done("parsebench", m):
            log(f"SKIP parsebench score {m}")
            continue
        if not prepared("parsebench", m):
            log(f"SKIP parsebench score {m} (not prepared)")
            summary = {
                "model": m,
                "benchmark": "parsebench",
                "returncode": 2,
                "error": "not_prepared",
            }
            (PB_RAW / m).mkdir(parents=True, exist_ok=True)
            (PB_RAW / m / "run_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            continue
        out_dir = PB_RAW / m
        out_dir.mkdir(parents=True, exist_ok=True)
        started = time.time()
        rc = run_cmd(
            [
                str(ARENA_PY),
                "-m",
                "arena.scoring",
                "score",
                "--model",
                m,
                "--benchmark",
                "parsebench",
                "--gt-path",
                str(GT_PB),
            ],
            ROOT,
            f"chain_parsebench_score_{m}",
            timeout=21600,
        )
        elapsed = time.time() - started
        # detect some artifact
        raw_score = ROOT / "scores" / m / "parsebench" / "evaluator_raw"
        has_raw = raw_score.is_dir() and any(raw_score.rglob("*"))
        summary = {
            "model": m,
            "benchmark": "parsebench",
            "returncode": rc,
            "elapsed_seconds": elapsed,
            "evaluator_raw_exists": has_raw,
        }
        (out_dir / "run_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (ROOT / "scores" / m / "parsebench" / "chain_run_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        notes.append(f"parsebench score {m} rc={rc} elapsed={elapsed:.0f}s")
        write_status_md("parsebench_score", notes)
        log(notes[-1])

    save_state("parsebench_done", {"prep": prep_results})
    write_status_md("parsebench_done", notes)


def main() -> int:
    REPORT.mkdir(parents=True, exist_ok=True)
    notes: list[str] = [f"chain started pid={os.getpid()}"]
    log("=" * 60)
    log(f"CHAIN START pid={os.getpid()}")
    save_state("start", {"pid": os.getpid()})
    write_status_md("start", notes)

    wait_omnidoc(notes)
    score_olmocr(notes)
    score_parsebench(notes)

    # final refresh
    if (REPORT / "_build_comparison.py").is_file():
        run_cmd([str(ARENA_PY), str(REPORT / "_build_comparison.py")], REPORT, "chain_build_comparison_final")

    notes.append("chain complete")
    save_state("complete", {"notes": notes[-20:]})
    write_status_md("complete", notes)
    log("CHAIN COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
