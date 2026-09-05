"""The CLI: dry run by default, and --execute never provisions in this phase."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from arena.controller.cli import EXIT_BLOCKED, EXIT_OK, EXIT_REFUSED, build_parser, main
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry
from arena.controller.queue import CampaignQueue
from tests.controller.conftest import (
    MODEL_KEY,
    make_sample,
    write_catalog_snapshot,
    write_model_registry,
    write_runtime_json,
    write_source_manifest,
)


def _seed(paths: CampaignPaths, entry: ModelPlanEntry, **registry: object) -> None:
    write_source_manifest(paths.source_manifest, [make_sample(index) for index in range(6)])
    write_model_registry(paths.model_registry, entry, **registry)


def test_every_command_is_in_the_parser() -> None:
    parser = build_parser()
    for command in (
        "preflight",
        "plan",
        "canary",
        "run",
        "status",
        "pause",
        "resume",
        "drain",
        "freeze",
        "cleanup-verify",
        "cost",
    ):
        args = parser.parse_args([command])
        assert args.command == command
        assert args.execute is False  # dry run is the default, always


def test_plan_enqueues_and_is_idempotent(
    paths: CampaignPaths, entry: ModelPlanEntry, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(paths, entry)
    argv = ["plan", "--model", MODEL_KEY, "--root", str(paths.root)]
    assert main(argv) == EXIT_OK
    first = capsys.readouterr().out
    assert "6 job(s) (6 new, 0 already queued)" in first

    assert main(argv) == EXIT_OK
    second = capsys.readouterr().out
    assert "0 new, 6 already queued" in second

    receipt = json.loads(
        (paths.receipts_dir / f"plan-{MODEL_KEY}.json").read_text(encoding="utf-8")
    )
    assert receipt["job_count"] == 6
    assert receipt["ids_source"]


def test_plan_refuses_without_lane_a2_output(
    paths: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["plan", "--root", str(paths.root)]) == EXIT_REFUSED
    assert "lane A2" in capsys.readouterr().err


def test_run_is_blocked_when_the_canary_has_not_passed(
    paths: CampaignPaths, entry: ModelPlanEntry, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(paths, entry, canary_status="PENDING", full_run_eligible=False)
    code = main(["run", "--model", MODEL_KEY, "--root", str(paths.root)])
    assert code == EXIT_BLOCKED
    assert "REFUSED" in capsys.readouterr().out


def test_run_with_execute_is_blocked_without_an_authorization(
    paths: CampaignPaths, entry: ModelPlanEntry, capsys: pytest.CaptureFixture[str]
) -> None:
    """D6 replaced the build-phase refusal: the gate is now a real receipt."""

    _seed(paths, entry)
    write_runtime_json(paths)
    write_catalog_snapshot(paths)
    code = main(["run", "--model", MODEL_KEY, "--execute", "--root", str(paths.root)])
    assert code == EXIT_BLOCKED
    out = capsys.readouterr().out
    assert "authorization: BLOCKED" in out
    assert "no unexpired phase2_full_run authorization" in out


def test_canary_lists_the_pages_then_reaches_the_gate(
    paths: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths.canary_selection.write_text(
        json.dumps({"case_keys": [f"omnidocbench-{index:06d}" for index in range(15)]}),
        encoding="utf-8",
    )
    code = main(["canary", "--model", MODEL_KEY, "--root", str(paths.root)])
    # No runtime.json in this fixture: the gate refuses rather than guessing.
    assert code == EXIT_REFUSED
    assert "15 page(s) selected" in capsys.readouterr().out


def test_canary_without_a_price_snapshot_is_blocked(
    paths: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """MP section 13.2: a pod is never priced from memory."""

    paths.canary_selection.write_text(json.dumps({"case_keys": ["a"]}), encoding="utf-8")
    write_runtime_json(paths)
    code = main(["canary", "--model", MODEL_KEY, "--root", str(paths.root)])
    assert code == EXIT_BLOCKED
    err = capsys.readouterr().err
    assert "no catalog snapshot on disk" in err
    assert "priced from memory" in err


def test_canary_needs_a_model() -> None:
    assert main(["canary"]) == EXIT_REFUSED


def test_pause_and_resume_move_only_pending_jobs(
    paths: CampaignPaths, entry: ModelPlanEntry, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(paths, entry)
    main(["plan", "--model", MODEL_KEY, "--root", str(paths.root)])
    capsys.readouterr()

    with CampaignQueue(paths.queue_db) as queue:
        job = queue.pending_jobs(model_key=MODEL_KEY, limit=1)[0]
        queue.mark_running(job.inference_job_id, "w0")

    assert main(["pause", "--root", str(paths.root)]) == EXIT_OK
    assert "paused 5 pending job(s)" in capsys.readouterr().out
    with CampaignQueue(paths.queue_db) as queue:
        counts = queue.counts_by_state(model_key=MODEL_KEY)
        assert counts["PAUSED"] == 5
        assert counts["RUNNING"] == 1  # the in-flight page is untouched

    assert main(["resume", "--root", str(paths.root)]) == EXIT_OK
    with CampaignQueue(paths.queue_db) as queue:
        assert queue.counts_by_state(model_key=MODEL_KEY)["PENDING"] == 5


def test_status_prints_the_campaign_shape(
    paths: CampaignPaths, entry: ModelPlanEntry, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(paths, entry)
    main(["plan", "--model", MODEL_KEY, "--root", str(paths.root)])
    capsys.readouterr()
    assert main(["status", "--root", str(paths.root)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "budget state: NORMAL" in out
    assert MODEL_KEY in out


def test_cost_writes_a_campaign_table_with_no_pods(
    paths: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["cost", "--root", str(paths.root)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "unmeasured" in out
    summary = json.loads((paths.cost_dir / "campaign-cost.json").read_text(encoding="utf-8"))
    assert summary["total_cost_usd"] is None


def test_preflight_dry_run_contacts_nothing(
    paths: CampaignPaths, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    absent = tmp_path / "no_credentials.txt"
    code = main(
        ["preflight", "--root", str(paths.root), "--credentials", str(absent)]
    )
    out = capsys.readouterr().out
    assert code == EXIT_BLOCKED  # no credential file: reported, not guessed around
    assert "preflight (dry_run)" in out
    receipts = list(paths.receipts_dir.glob("preflight-*.json"))
    assert len(receipts) == 1
    report = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert report["mode"] == "dry_run"
    assert report["secrets_withheld"] is True


def test_freeze_needs_a_model() -> None:
    assert main(["freeze"]) == EXIT_REFUSED


def test_canary_refuses_when_the_run_config_hashes_disagree(
    paths: CampaignPaths, entry: ModelPlanEntry, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate pod 27f6f6dif3jcp6 did not have (2026-09-03).

    That canary passed every gate there was, rented an RTX 4090, reached READY
    and then answered HTTP 422 to all 13 pages, because its registry hash was
    of the model card rather than of runtime.json's inference_config. The
    disagreement is visible without a provider, so it is refused without one.
    """

    from dataclasses import replace

    from arena.worker.util import config_sha256
    from tests.controller.conftest import PROMPT_ID, write_prompt_registry

    inference_config = {"max_new_tokens": 4096}
    paths.canary_selection.write_text(
        json.dumps({"case_keys": [f"omnidocbench-{index:06d}" for index in range(15)]}),
        encoding="utf-8",
    )
    write_source_manifest(paths.source_manifest, [make_sample(index) for index in range(15)])
    write_runtime_json(paths, inference_config=inference_config, prompt_kind="none")
    index = write_prompt_registry(paths, prompt_id=PROMPT_ID, text="")
    prompt_sha = json.loads(index.read_text(encoding="utf-8"))[PROMPT_ID]
    write_catalog_snapshot(paths)

    agreed = replace(
        entry,
        prompt_id=PROMPT_ID,
        prompt_sha256=prompt_sha,
        inference_config_sha256=config_sha256(inference_config),
    )
    write_model_registry(paths.model_registry, agreed)
    # Agreeing, the canary walks past this gate and is stopped by the next one.
    assert main(["canary", "--model", MODEL_KEY, "--root", str(paths.root)]) != EXIT_REFUSED
    capsys.readouterr()

    write_model_registry(
        paths.model_registry,
        replace(agreed, inference_config_sha256="sha256:" + "f" * 64),
    )
    code = main(["canary", "--model", MODEL_KEY, "--root", str(paths.root)])

    assert code == EXIT_REFUSED
    captured = capsys.readouterr()
    assert "15 page(s) selected" in captured.out
    assert "run-config hashes disagree" in captured.err
    assert "CONFIG_MISMATCH" in captured.err
    assert "arena.registry resolve --offline" in captured.err
