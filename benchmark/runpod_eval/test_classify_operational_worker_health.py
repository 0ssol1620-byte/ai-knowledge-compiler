from __future__ import annotations

import json
from pathlib import Path

from classify_operational_worker_health import WorkerResult, classify_workers

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")


def _write_summary(path: Path, *, failed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "input_count": 10,
                "runs": [
                    {
                        "repeat_index": 1,
                        "completed": 10 - failed,
                        "failed": failed,
                        "return_code": 1 if failed else 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_repeated_stalls_and_multi_suite_failures_quarantine_worker(
    tmp_path: Path,
) -> None:
    results: list[WorkerResult] = []
    for worker in range(4):
        root = tmp_path / f"worker-{worker:02d}"
        results.append(WorkerResult(worker, root))
        for suite in SUITES:
            failed = 0
            if worker == 1 and suite in {"parsebench", "omnidocbench"}:
                failed = 7
            if worker == 2 and suite == "parsebench":
                failed = 3
            if worker == 3 and suite in {"parsebench", "omnidocbench"}:
                failed = 2
            _write_summary(root / suite / "run-summary.json", failed=failed)
    (results[1].result_root / "stall-watchdog.jsonl").write_text(
        "\n".join(
            (
                json.dumps({"event": "suite_stall_detected", "suite": "parsebench"}),
                json.dumps({"event": "suite_stall_detected", "suite": "omnidocbench"}),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    receipt = classify_workers(
        worker_results=tuple(results), output_path=tmp_path / "health.json"
    )

    states = {item["worker_index"]: item["state"] for item in receipt["workers"]}
    assert states == {0: "HEALTHY", 1: "QUARANTINED", 2: "DEGRADED", 3: "DEGRADED"}
    assert receipt["eligible_retry_workers"] == [0, 2, 3]
    assert receipt["quarantined_worker_indices"] == [1]
    assert receipt["replacement_required"] is False
