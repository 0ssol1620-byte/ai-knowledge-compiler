"""Receipt conformance: every receipt this lane writes is judged by the shared
schema and by ``arena.core.ids``.

ARENA_CONTRACT 11.5 D27 item 4. These tests exercise the same code path the
``verify`` command uses, so a receipt that would pass here cannot fail there.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from arena.opus import cli as opus_cli
from arena.opus.runner import RunnerConfig, run_page, schema_error
from arena.opus.selection import PageSpec

pytestmark = pytest.mark.usefixtures("isolated_run_root")


def env_with(base: dict[str, str], **extra: str) -> dict[str, str]:
    return {**base, **extra}


def test_a_success_receipt_satisfies_the_shared_schema(
    page_spec: PageSpec,
    runner_config: RunnerConfig,
    child_env: dict[str, str],
    isolated_run_root: Path,
) -> None:
    from dataclasses import replace

    cfg = replace(
        runner_config,
        env=env_with(child_env, FAKE_CLAUDE_MODE="ok", FAKE_CLAUDE_RESULT="# A\n\nB\n"),
    )
    outcome = run_page(page_spec, cfg, worker_index=0)
    assert outcome.status == "SUCCESS", outcome.error_message

    written = json.loads(
        (isolated_run_root / "canary" / "receipts" / f"{page_spec.case_key}.json").read_text(
            encoding="utf-8"
        )
    )
    assert written["receipt_schema_valid"] is True
    assert written["receipt_schema_error"] is None
    assert schema_error(written) is None
    assert opus_cli._verify_receipt(written) == []


def test_a_failed_receipt_also_satisfies_the_shared_schema(
    page_spec: PageSpec,
    runner_config: RunnerConfig,
    child_env: dict[str, str],
    isolated_run_root: Path,
) -> None:
    """A failure receipt is evidence too, and must not be schema-invalid."""
    from dataclasses import replace

    cfg = replace(
        runner_config,
        env=env_with(child_env, FAKE_CLAUDE_MODE="garbage"),
    )
    outcome = run_page(page_spec, cfg, worker_index=0)
    assert outcome.status == "FAILED"

    written = json.loads(
        (isolated_run_root / "canary" / "receipts" / f"{page_spec.case_key}.json").read_text(
            encoding="utf-8"
        )
    )
    assert written["error_class"] == "OUTPUT_MALFORMED"
    assert written["receipt_schema_valid"] is True, written["receipt_schema_error"]
    assert opus_cli._verify_receipt(written) == []


def test_verify_reports_a_tampered_job_id(
    page_spec: PageSpec,
    runner_config: RunnerConfig,
    child_env: dict[str, str],
    isolated_run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``verify`` recomputes the id; it does not take the receipt's word for it."""
    from dataclasses import replace

    cfg = replace(runner_config, env=env_with(child_env, FAKE_CLAUDE_MODE="ok"))
    assert run_page(page_spec, cfg, worker_index=0).status == "SUCCESS"

    receipt_dir = isolated_run_root / "canary" / "receipts"
    path = receipt_dir / f"{page_spec.case_key}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["inference_job_id"] = "0" * 64
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    monkeypatch.setattr(opus_cli, "CANARY_DIR", isolated_run_root / "canary")
    monkeypatch.setattr(opus_cli, "RECEIPT_DIR", isolated_run_root / "receipts")
    code = opus_cli.cmd_verify(argparse.Namespace())
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["failed"] == 1
    assert any(
        "inference_job_id" in problem
        for row in report["receipts"]
        for problem in row["problems"]
    )


def test_a_completed_resume_strikes_its_pages_off_the_checkpoint(
    page_spec: PageSpec,
    second_page_spec: PageSpec,
    runner_config: RunnerConfig,
    child_env: dict[str, str],
    isolated_run_root: Path,
) -> None:
    """A stale checkpoint would make the next resume re-spend the allowance."""
    from dataclasses import replace

    from arena.opus import paths as opus_paths
    from arena.opus.runner import run_pages

    checkpoint = opus_paths.CHECKPOINT_PATH
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(
        json.dumps(
            {
                "schema": "tavonel.arena.opus-checkpoint.v1",
                "stop_reason": "limit:TEMPORARY_CAPACITY",
                "done_case_keys": [],
                "failed_case_keys": [],
                "pending_case_keys": [page_spec.case_key, second_page_spec.case_key],
                "counts": {"done": 0, "failed": 0, "pending": 2},
            }
        ),
        encoding="utf-8",
    )

    cfg = replace(runner_config, env=env_with(child_env, FAKE_CLAUDE_MODE="ok"), workers=1)
    report = run_pages([page_spec], cfg)
    assert not report.stopped

    settled = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert settled["pending_case_keys"] == [second_page_spec.case_key]
    assert settled["counts"]["pending"] == 1
    # The stop that created the checkpoint is not rewritten away.
    assert settled["stop_reason"] == "limit:TEMPORARY_CAPACITY"
    assert settled["settled_runs"][0]["succeeded"] == [page_spec.case_key]


def test_a_run_that_stops_still_writes_a_fresh_checkpoint(
    page_spec: PageSpec,
    runner_config: RunnerConfig,
    child_env: dict[str, str],
) -> None:
    """Settling must not swallow the stop path."""
    from dataclasses import replace

    from arena.opus import paths as opus_paths
    from arena.opus.runner import run_pages

    cfg = replace(
        runner_config, env=env_with(child_env, FAKE_CLAUDE_MODE="limit"), workers=1
    )
    report = run_pages([page_spec], cfg)
    assert report.stopped
    assert opus_paths.CHECKPOINT_PATH.is_file()


def test_verify_passes_on_untampered_receipts(
    page_spec: PageSpec,
    runner_config: RunnerConfig,
    child_env: dict[str, str],
    isolated_run_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dataclasses import replace

    cfg = replace(runner_config, env=env_with(child_env, FAKE_CLAUDE_MODE="ok"))
    assert run_page(page_spec, cfg, worker_index=0).status == "SUCCESS"

    monkeypatch.setattr(opus_cli, "CANARY_DIR", isolated_run_root / "canary")
    monkeypatch.setattr(opus_cli, "RECEIPT_DIR", isolated_run_root / "receipts")
    assert opus_cli.cmd_verify(argparse.Namespace()) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["checked"] == 1
    assert report["counts"]["failed"] == 0
