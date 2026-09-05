"""End-to-end runner behaviour against the fake Claude Code CLI.

Covers the happy path, the limit -> checkpoint -> exit 75 -> resume cycle, the
unexpected-model stop, the timeout kill, and the environment scrub (the fake CLI
exits 90 if a forbidden variable reaches it).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from arena.core import ids as core_ids
from arena.core import receipts as core_receipts
from arena.opus import runner as opus_runner
from arena.opus.runner import (
    LIMIT_EXIT_CODE,
    RunnerConfig,
    canonicalize_raw_text,
    run_page,
    run_pages,
    write_run_summary,
)
from arena.opus.selection import PageSpec

pytestmark = pytest.mark.usefixtures("isolated_run_root")


def env_with(base: dict[str, str], **extra: str) -> dict[str, str]:
    return {**base, **extra}


def test_happy_path_writes_raw_canonical_and_receipt(
    page_spec: PageSpec, runner_config: RunnerConfig, isolated_run_root: Path
) -> None:
    cfg = replace(
        runner_config,
        env=env_with(
            dict(runner_config.env or {}),
            FAKE_CLAUDE_MODE="ok",
            FAKE_CLAUDE_RESULT="# Title\n\nBody line.\n",
            FAKE_CLAUDE_INPUT_TOKENS="2000",
            FAKE_CLAUDE_OUTPUT_TOKENS="1000",
        ),
    )
    outcome = run_page(page_spec, cfg, worker_index=0)

    assert outcome.status == "SUCCESS", outcome.error_message
    canary = isolated_run_root / "canary"
    raw = canary / "raw" / f"{page_spec.case_key}.raw.txt"
    payload = canary / "raw" / f"{page_spec.case_key}.claude.json"
    canonical = canary / "canonical" / f"{page_spec.case_key}.md"
    receipt_path = canary / "receipts" / f"{page_spec.case_key}.json"

    assert raw.read_text(encoding="utf-8") == "# Title\n\nBody line.\n"
    assert canonical.read_text(encoding="utf-8") == "# Title\n\nBody line."
    assert json.loads(payload.read_text(encoding="utf-8"))["is_error"] is False

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "SUCCESS"
    assert receipt["runtime_mode"] == "subscription"
    assert receipt["runtime_image_digest"] == (
        "subscription:claude-code-2.1.252-claude-opus-5"
    )
    # D27: every id comes from arena.core.ids, shard width 4.
    assert receipt["shard_id"] == "opus5_subscription-omnidoc-0000"
    assert receipt["worker_id"] == "opus5_subscription-w0-local"
    assert receipt["inference_job_id"] == core_ids.inference_job_id(
        campaign_id=receipt["campaign_id"],
        benchmark_revision=receipt["benchmark_revision"],
        sample_id=receipt["sample_id"],
        source_sha256=receipt["source_sha256"],
        model_repo=receipt["model_repo"],
        model_revision=receipt["model_revision"],
        runtime_image_digest=receipt["runtime_image_digest"],
        prompt_sha256=receipt["prompt_sha256"],
        inference_config_sha256=receipt["inference_config_sha256"],
    )
    # The receipt this lane writes satisfies the shared page-receipt schema.
    assert receipt["receipt_schema_valid"] is True
    assert receipt["receipt_schema_error"] is None
    core_receipts.validate({k: v for k, v in receipt.items()})
    assert receipt["surface"] == "claude-code-read-tool"
    assert receipt["actual_marginal_api_cost"] == "N/A"
    assert receipt["subscription_included_usage"] is True
    assert receipt["reported_model"] == "claude-opus-5"
    assert receipt["auxiliary_models"] == ["claude-haiku-4-5-20251001"]
    assert receipt["model_key"] == "opus5_subscription"
    # Masterplan 21.10: the image facts must be on the receipt.
    assert receipt["image_width"] == 8
    assert receipt["image_height"] == 6
    assert receipt["input_bytes"] == page_spec.image_path.stat().st_size
    assert receipt["source_sha256"] == page_spec.manifest_input_sha256
    # Tokens come from the Opus entry, not from the auxiliary model.
    assert receipt["input_tokens"] == 2000
    assert receipt["output_tokens"] == 1000
    assert receipt["usage_source"] == "modelUsage[claude-opus-5]"
    # 2000/1e6*5 + 1000/1e6*25 = 0.01 + 0.025
    assert receipt["api_equivalent_list_price_usd"] == pytest.approx(0.035)
    assert receipt["api_equivalent_price_complete"] is True
    assert len(receipt["inference_job_id"]) == 64


def test_child_environment_is_scrubbed(
    page_spec: PageSpec, runner_config: RunnerConfig
) -> None:
    """The fake CLI exits 90 if ANTHROPIC_API_KEY or CLAUDECODE reaches it."""
    from arena.opus.env import scrub_env

    parent = {
        **dict(runner_config.env or {}),
        "ANTHROPIC_API_KEY": "must-not-reach-the-child",
        "ANTHROPIC_AUTH_TOKEN": "must-not-reach-the-child",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "FAKE_CLAUDE_MODE": "ok",
    }
    scrubbed = scrub_env(parent)
    assert "ANTHROPIC_API_KEY" not in scrubbed
    assert "CLAUDECODE" not in scrubbed
    assert "CLAUDE_CODE_ENTRYPOINT" not in scrubbed

    # Run through the real scrub, re-adding only the fake CLI's own knobs.
    cfg = replace(runner_config, env={**scrubbed, "FAKE_CLAUDE_MODE": "ok"})
    outcome = run_page(page_spec, cfg, worker_index=0)

    assert outcome.status == "SUCCESS", outcome.error_message
    assert outcome.receipt["cli_exit_code"] == 0


def test_environment_leak_is_visible_as_a_failure(
    page_spec: PageSpec, runner_config: RunnerConfig
) -> None:
    """Negative control: if the scrub were skipped, the child would refuse."""
    cfg = replace(
        runner_config,
        env=env_with(
            dict(runner_config.env or {}),
            FAKE_CLAUDE_MODE="ok",
            ANTHROPIC_API_KEY="leaked",
        ),
    )
    outcome = run_page(page_spec, cfg, worker_index=0)

    assert outcome.status == "FAILED"
    assert outcome.receipt["cli_exit_code"] == 90


def test_prompt_is_delivered_on_stdin_with_the_image_path(
    page_spec: PageSpec, runner_config: RunnerConfig, tmp_path: Path
) -> None:
    record = tmp_path / "invocations.jsonl"
    cfg = replace(
        runner_config,
        env=env_with(
            dict(runner_config.env or {}),
            FAKE_CLAUDE_MODE="ok",
            FAKE_CLAUDE_RECORD=str(record),
        ),
    )
    run_page(page_spec, cfg, worker_index=0)

    entry = json.loads(record.read_text(encoding="utf-8").splitlines()[0])
    assert entry["stdin"].rstrip().endswith(
        f"The page image is at: {page_spec.image_path.resolve()}"
    )
    assert not any("The page image is at" in token for token in entry["argv"])
    assert entry["cwd"] == str(cfg.child_cwd)


def test_limit_stops_the_pool_writes_a_checkpoint_and_exits_75(
    page_spec: PageSpec,
    second_page_spec: PageSpec,
    runner_config: RunnerConfig,
    isolated_run_root: Path,
) -> None:
    cfg = replace(
        runner_config,
        workers=1,
        env=env_with(dict(runner_config.env or {}), FAKE_CLAUDE_MODE="limit"),
    )
    report = run_pages([page_spec, second_page_spec], cfg)

    assert report.stopped
    assert report.stop_reason == "limit:SUBSCRIPTION_LIMIT"
    assert report.limit is not None
    assert report.limit.reset_hint == "2026-09-03T18:00:00Z"
    assert report.exit_code == LIMIT_EXIT_CODE

    checkpoint = json.loads(
        (isolated_run_root / "checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["stop_reason"] == "limit:SUBSCRIPTION_LIMIT"
    assert checkpoint["reset_hint"] == "2026-09-03T18:00:00Z"
    assert checkpoint["done_case_keys"] == []
    assert page_spec.case_key in checkpoint["failed_case_keys"]
    assert "no_fallback" in checkpoint["no_fallback_assertion"].lower().replace(" ", "_")


def test_resume_runs_only_the_pending_pages(
    page_spec: PageSpec,
    second_page_spec: PageSpec,
    runner_config: RunnerConfig,
    isolated_run_root: Path,
) -> None:
    limited = replace(
        runner_config,
        workers=1,
        env=env_with(dict(runner_config.env or {}), FAKE_CLAUDE_MODE="limit"),
    )
    first = run_pages([page_spec, second_page_spec], limited)
    assert first.stopped

    checkpoint = json.loads(
        (isolated_run_root / "checkpoint.json").read_text(encoding="utf-8")
    )
    pending = checkpoint["pending_case_keys"] + checkpoint["failed_case_keys"]
    assert pending

    by_key = {s.case_key: s for s in (page_spec, second_page_spec)}
    resumed_specs = [by_key[k] for k in pending]

    healthy = replace(
        runner_config,
        workers=1,
        env=env_with(dict(runner_config.env or {}), FAKE_CLAUDE_MODE="ok"),
    )
    second = run_pages(resumed_specs, healthy)

    assert not second.stopped
    assert sorted(second.succeeded) == sorted(pending)
    assert second.exit_code == 0


def test_unexpected_model_fails_the_page_and_stops_the_pool(
    page_spec: PageSpec, second_page_spec: PageSpec, runner_config: RunnerConfig
) -> None:
    cfg = replace(
        runner_config,
        workers=1,
        env=env_with(
            dict(runner_config.env or {}),
            FAKE_CLAUDE_MODE="wrong_model",
            FAKE_CLAUDE_MODEL="claude-sonnet-4-5-20250929",
        ),
    )
    report = run_pages([page_spec, second_page_spec], cfg)

    assert report.stopped
    assert report.stop_reason == "unexpected_model"
    # A stop for an unexpected model is not a limit, so it is not exit 75.
    assert report.exit_code == 1
    failed = report.outcomes[0]
    assert failed.error_class == "UNKNOWN"
    assert failed.error_message is not None
    assert "unexpected model" in failed.error_message


def test_auth_expired_stops_the_pool_without_a_page_receipt(
    page_spec: PageSpec,
    second_page_spec: PageSpec,
    runner_config: RunnerConfig,
    isolated_run_root: Path,
) -> None:
    """DEFECT 2: an expired subscription OAuth session must not be scored as a
    page failure. No receipt is written for the page that hit it, the pool
    stops before the second page runs, the checkpoint carries stop_reason
    limit:AUTH_EXPIRED with the fixed re-auth hint, and the case_key stays
    pending for `resume` (mirrors the 2026-09-04T05:46 attempt)."""
    cfg = replace(
        runner_config,
        workers=1,
        env=env_with(dict(runner_config.env or {}), FAKE_CLAUDE_MODE="auth_expired"),
    )
    report = run_pages([page_spec, second_page_spec], cfg)

    assert report.stopped
    assert report.stop_reason == "limit:AUTH_EXPIRED"
    assert report.exit_code == LIMIT_EXIT_CODE
    # Neither page produced a scored outcome: the page that hit auth failure
    # is not a page result, and the pool stopped before the second page ran.
    assert report.outcomes == []
    assert report.succeeded == []
    assert report.failed == []

    canary = isolated_run_root / "canary"
    assert not (canary / "receipts" / f"{page_spec.case_key}.json").exists()
    assert not (canary / "receipts" / f"{second_page_spec.case_key}.json").exists()

    checkpoint = json.loads(
        (isolated_run_root / "checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["stop_reason"] == "limit:AUTH_EXPIRED"
    from arena.opus.limits import AUTH_EXPIRED_RESET_HINT

    assert checkpoint["reset_hint"] == AUTH_EXPIRED_RESET_HINT
    assert page_spec.case_key in checkpoint["pending_case_keys"]
    assert page_spec.case_key not in checkpoint["failed_case_keys"]
    assert page_spec.case_key not in checkpoint["done_case_keys"]


def test_timeout_kills_the_child_and_records_inference_timeout(
    page_spec: PageSpec, runner_config: RunnerConfig
) -> None:
    cfg = replace(
        runner_config,
        timeout_seconds=1,
        env=env_with(
            dict(runner_config.env or {}), FAKE_CLAUDE_MODE="hang", FAKE_CLAUDE_SLEEP="30"
        ),
    )
    outcome = run_page(page_spec, cfg, worker_index=0)

    assert outcome.status == "FAILED"
    assert outcome.error_class == "INFERENCE_TIMEOUT"
    assert outcome.receipt["raw_output_sha256"] is None


def test_non_json_stdout_is_output_malformed(
    page_spec: PageSpec, runner_config: RunnerConfig
) -> None:
    cfg = replace(
        runner_config,
        env=env_with(dict(runner_config.env or {}), FAKE_CLAUDE_MODE="garbage"),
    )
    outcome = run_page(page_spec, cfg, worker_index=0)

    assert outcome.error_class == "OUTPUT_MALFORMED"


def test_empty_result_is_output_empty(
    page_spec: PageSpec, runner_config: RunnerConfig
) -> None:
    cfg = replace(
        runner_config,
        env=env_with(
            dict(runner_config.env or {}), FAKE_CLAUDE_MODE="ok", FAKE_CLAUDE_RESULT="   \n"
        ),
    )
    outcome = run_page(page_spec, cfg, worker_index=0)

    assert outcome.error_class == "OUTPUT_EMPTY"


def test_image_hash_mismatch_fails_closed(
    page_spec: PageSpec, runner_config: RunnerConfig
) -> None:
    tampered = replace(page_spec, manifest_input_sha256="sha256:" + "0" * 64)
    cfg = replace(
        runner_config,
        env=env_with(dict(runner_config.env or {}), FAKE_CLAUDE_MODE="ok"),
    )
    outcome = run_page(tampered, cfg, worker_index=0)

    assert outcome.status == "FAILED"
    assert outcome.error_class == "CHECKSUM"


def test_run_summary_never_says_zero_cost(
    page_spec: PageSpec, runner_config: RunnerConfig
) -> None:
    cfg = replace(
        runner_config,
        workers=1,
        env=env_with(dict(runner_config.env or {}), FAKE_CLAUDE_MODE="ok"),
    )
    report = run_pages([page_spec], cfg)
    target = write_run_summary(report, cfg, extra={"selection_source": "test"})
    summary = json.loads(target.read_text(encoding="utf-8"))

    assert summary["actual_marginal_api_cost"] == "N/A"
    assert summary["subscription_included_usage"] is True
    assert summary["api_equivalent_list_price_usd_total"] > 0


def test_ramp_gate_opens_only_after_the_success_threshold() -> None:
    gate = opus_runner._RampGate(initial=2, target=6, threshold=3)
    assert gate.current_limit == 2
    gate.note_success()
    gate.note_success()
    assert gate.current_limit == 2
    gate.note_success()
    assert gate.current_limit == 6


@pytest.mark.parametrize(
    ("raw", "expected", "note_fragment"),
    [
        ("  # Title\n\ntext  \n", "# Title\n\ntext", "stripped"),
        ("```markdown\n# Title\n\ntext\n```", "# Title\n\ntext", "unwrapped"),
        ("```\nplain\n```", "plain", "unwrapped"),
        ("# Title\n\n```py\ncode\n```\n\nmore", "# Title\n\n```py\ncode\n```\n\nmore", None),
        (
            "```\nouter\n```text\ninner\n```\n```",
            "```\nouter\n```text\ninner\n```\n```",
            "nested",
        ),
    ],
)
def test_canonicalization_only_strips_and_unwraps(
    raw: str, expected: str, note_fragment: str | None
) -> None:
    text, notes = canonicalize_raw_text(raw)
    assert text == expected
    if note_fragment is None:
        assert notes == []
    else:
        assert any(note_fragment in note for note in notes)


def test_an_operator_stop_file_checkpoints_the_rest_and_is_consumed(
    page_spec: PageSpec,
    second_page_spec: PageSpec,
    runner_config: RunnerConfig,
    isolated_run_root: Path,
) -> None:
    """D63: STOP under RUN_ROOT drains what is running, starts nothing new,
    checkpoints the rest like a limit would, and is removed once acknowledged."""
    isolated_run_root.mkdir(parents=True, exist_ok=True)
    (isolated_run_root / "STOP").write_text("ramp to 4 workers", encoding="utf-8")
    cfg = replace(
        runner_config,
        workers=1,
        env=env_with(dict(runner_config.env or {}), FAKE_CLAUDE_MODE="ok"),
    )
    report = run_pages([page_spec, second_page_spec], cfg)

    assert report.stopped
    assert report.stop_reason == "operator_stop"
    assert report.limit is None
    assert report.outcomes == []
    assert sorted(report.pending) == sorted([page_spec.case_key, second_page_spec.case_key])
    assert not (isolated_run_root / "STOP").exists()
    checkpoint = json.loads(
        (isolated_run_root / "checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["stop_reason"] == "operator_stop"
    assert sorted(checkpoint["pending_case_keys"]) == sorted(report.pending)
