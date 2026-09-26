"""Canary PASS/FAIL, cost ledger, freeze refusal, cleanup verification."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from arena.constants import TOTAL_SAMPLES
from arena.controller.canary import (
    OVERHEAD_FACTOR_HIGH,
    OVERHEAD_FACTOR_LOW,
    CanaryError,
    CanaryPageResult,
    evaluate_canary,
    load_canary_selection,
    project,
    stage_percentiles,
    write_canary_receipt,
    write_registry_update,
)
from arena.controller.cleanup import verify_cleanup
from arena.controller.cli import main
from arena.controller.cost import build_ledger_row, summarize
from arena.controller.freeze import freeze_model
from arena.controller.paths import CampaignPaths
from arena.controller.queue import PodRecord
from arena.provider.runpod_pods import RunPodPodsClient
from arena.provider.safety import atomic_write_bytes, sha256_text, write_json_atomic
from arena.provider.secrets import Secret
from tests.provider.conftest import RecordingTransport, json_response, pod_payload

EXPECTED_REVISION = "a" * 40


def _page(
    index: int, *, status: str = "SUCCESS", total_ms: int = 3500, chars: int = 1200, **kw: object
) -> CanaryPageResult:
    base: dict[str, object] = {
        "case_key": f"omnidocbench-{index:06d}",
        "sample_id": f"omnidoc:images/page_{index:04d}",
        "benchmark": "omnidoc",
        "status": status,
        "error_class": None if status == "SUCCESS" else "OUTPUT_EMPTY",
        "total_ms": total_ms,
        "load_ms": 0,
        "preprocess_ms": 100,
        "inference_ms": total_ms - 160,
        "postprocess_ms": 60,
        "output_chars": chars,
        "peak_vram_mb": 17000,
        "model_revision": EXPECTED_REVISION,
        "schema_valid": status == "SUCCESS",
        "warm": index > 0,
    }
    base.update(kw)
    return CanaryPageResult(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------------ canary


def test_a_slow_but_correct_runtime_passes() -> None:
    """Section 17: speed is an ETA, never a verdict."""

    slow = [_page(index, total_ms=90_000) for index in range(15)]
    report = evaluate_canary(
        "deepseek_ocr2",
        slow,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
        price_row_sha256="c" * 64,
    )
    assert report.passed is True
    assert report.failures == ()
    assert report.projection.warm_sec_per_page == pytest.approx(90.0)


def test_a_wrong_model_revision_fails_the_canary() -> None:
    pages = [_page(index) for index in range(5)]
    report = evaluate_canary(
        "paddleocr_vl_1_6",
        pages,
        expected_model_revision="b" * 40,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
    )
    assert report.passed is False
    assert report.checks["correct_model_revision"] is False
    assert any("not the pinned" in message for message in report.failures)


def test_an_empty_output_on_a_non_blank_page_fails() -> None:
    pages = [_page(index) for index in range(4)] + [_page(4, chars=0)]
    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
    )
    assert report.passed is False
    assert report.checks["output_non_empty_on_non_blank"] is False


def test_a_blank_source_may_legitimately_produce_nothing() -> None:
    """Masterplan section 41: a blank page is not an empty-output failure."""

    pages = [_page(index) for index in range(4)] + [_page(4, chars=0, blank_source=True)]
    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
    )
    assert report.checks["output_non_empty_on_non_blank"] is True


def test_a_hard_crash_fails_the_canary() -> None:
    pages = [_page(index) for index in range(5)]
    report = evaluate_canary(
        "hpd_parsing",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=80_000,
        hourly_rate_usd=1.99,
        hard_crashes=1,
    )
    assert report.passed is False
    assert report.checks["no_hard_crash"] is False


def test_an_evaluator_that_rejects_the_output_fails_the_canary() -> None:
    pages = [_page(index) for index in range(5)]
    report = evaluate_canary(
        "ovisocr2",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
        evaluator_accepts_output=False,
    )
    assert report.passed is False
    assert report.checks["evaluator_adapter_accepts"] is False


def test_projection_follows_section_18() -> None:
    pages = [_page(index, total_ms=4000) for index in range(11)]
    projection = project(pages, hourly_rate_usd=0.34, price_row_sha256="c" * 64, replica_count=4)
    assert projection.warm_sec_per_page == pytest.approx(4.0)
    expected_hours = 4.0 * TOTAL_SAMPLES / 3600.0
    assert projection.gpu_hours_projected == pytest.approx(expected_hours)
    assert projection.raw_gpu_cost_projected_usd == pytest.approx(expected_hours * 0.34)
    assert projection.wall_time_hours_low == pytest.approx(expected_hours / 4 * OVERHEAD_FACTOR_LOW)
    assert projection.wall_time_hours_high == pytest.approx(
        expected_hours / 4 * OVERHEAD_FACTOR_HIGH
    )


def test_projection_without_a_price_row_is_null_not_zero() -> None:
    pages = [_page(index) for index in range(3)]
    projection = project(pages, hourly_rate_usd=None, price_row_sha256=None)
    assert projection.raw_gpu_cost_projected_usd is None
    assert any("not computable" in note for note in projection.notes)


def test_projection_with_no_warm_success_is_null_not_zero() -> None:
    projection = project(
        [_page(0, status="FAILED", warm=True)], hourly_rate_usd=0.34, price_row_sha256="c" * 64
    )
    assert projection.warm_sec_per_page is None
    assert projection.gpu_hours_projected is None
    assert any("nothing can be projected" in note for note in projection.notes)


def test_stage_percentiles_cover_every_stage() -> None:
    pages = [_page(index, total_ms=1000 * (index + 1)) for index in range(10)]
    stages = stage_percentiles(pages)
    assert set(stages) == {
        "load_ms",
        "preprocess_ms",
        "inference_ms",
        "postprocess_ms",
        "total_ms",
    }
    assert stages["total_ms"]["p50"] is not None
    p95 = stages["total_ms"]["p95"]
    p50 = stages["total_ms"]["p50"]
    assert p95 is not None and p50 is not None and p95 > p50


def test_canary_receipts_are_written_and_the_registry_is_not_edited(
    paths: CampaignPaths,
) -> None:
    pages = [_page(index) for index in range(15)]
    report = evaluate_canary(
        "paddleocr_vl_1_6",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
        price_row_sha256="c" * 64,
    )
    receipt_path = write_canary_receipt(
        report,
        paths,
        # D15: a bootstrap canary's runtime identity is its bundle digest.
        runtime_image_digest="bootstrap:sha256:" + "d" * 64,
        gpu_type="NVIDIA GeForce RTX 4090",
        # D37: a non-subscription canary receipt must name the pod it ran on.
        pod_id="pod_canary0001",
    )
    update_path = write_registry_update(report, paths)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS"
    # D37: `criteria` is the list of named masterplan section 17 criteria.
    assert isinstance(receipt["criteria"], list)
    assert {entry["criterion"] for entry in receipt["criteria"]} >= {
        "process_start",
        "correct_model_revision",
        "zero_hard_crash",
    }
    assert receipt["criteria_basis"].startswith("runtime correctness only")
    assert receipt["runtime_image_digest"] == "bootstrap:sha256:" + "d" * 64
    update = json.loads(update_path.read_text(encoding="utf-8"))
    assert update["fields"]["canary_status"] == "PASS"
    assert "waiver" in update["note"]
    # model_registry.json is lane A3's file and is never edited in place.
    assert not paths.model_registry.exists()


def test_canary_selection_reader_handles_both_shapes(tmp_path: Path) -> None:
    shared = tmp_path / "shared.json"
    shared.write_text(json.dumps({"case_keys": ["a", "b"]}), encoding="utf-8")
    assert load_canary_selection(shared, "paddleocr_vl_1_6") == ("a", "b")

    per_model = tmp_path / "per_model.json"
    per_model.write_text(
        json.dumps({"per_model": {"mineru_vlm": ["x"]}, "case_keys": ["a"]}), encoding="utf-8"
    )
    assert load_canary_selection(per_model, "mineru_vlm") == ("x",)

    with pytest.raises(CanaryError, match="lane A2"):
        load_canary_selection(tmp_path / "absent.json", "m")


def test_evaluate_refuses_an_empty_canary() -> None:
    with pytest.raises(CanaryError, match="no page results"):
        evaluate_canary("m", [], expected_model_revision=EXPECTED_REVISION)


# -------------------------------------------------------------------- cost


def _pod(**kw: object) -> PodRecord:
    start = datetime(2026, 9, 3, 10, 0, 0, tzinfo=UTC)
    base: dict[str, object] = {
        "pod_id": "pod_a",
        "model_key": "paddleocr_vl_1_6",
        "name": "arena-paddleocr-vl-1-6-w0-20260903v1",
        "state": "TERMINATED",
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "listed_rate_usd_per_hour": 0.34,
        "provisioned_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_ready_at": (start + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "terminated_at": (start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_snapshot_sha256": "c" * 64,
    }
    base.update(kw)
    return PodRecord(**base)  # type: ignore[arg-type]


def test_ledger_splits_billed_time_into_its_four_parts() -> None:
    row = build_ledger_row(_pod(), useful_inference_seconds=2400.0, retry_seconds=100.0)
    assert row.billed_seconds == pytest.approx(3600.0)
    assert row.model_loading_seconds == pytest.approx(300.0)
    assert row.useful_inference_seconds == pytest.approx(2400.0)
    assert row.retry_seconds == pytest.approx(100.0)
    assert row.idle_seconds == pytest.approx(800.0)
    assert row.estimated_provider_cost_usd == pytest.approx(0.34)
    assert row.unmeasured == ()


def test_ledger_names_a_missing_price_instead_of_charging_zero() -> None:
    row = build_ledger_row(_pod(listed_rate_usd_per_hour=None), useful_inference_seconds=1000.0)
    assert row.estimated_provider_cost_usd is None
    assert any("cost cannot be estimated" in note for note in row.unmeasured)


def test_ledger_names_a_missing_ready_timestamp() -> None:
    row = build_ledger_row(_pod(model_ready_at=None), useful_inference_seconds=1000.0)
    assert row.model_loading_seconds == pytest.approx(0.0)
    assert any("model_loading_seconds" in note for note in row.unmeasured)


def test_campaign_cost_reports_operational_efficiency() -> None:
    row = build_ledger_row(_pod(), useful_inference_seconds=2400.0, retry_seconds=100.0)
    summary = summarize([row], successful_pages=680, attempted_pages=700)
    assert summary.operational_efficiency == pytest.approx(2400.0 / 3600.0, rel=1e-6)
    assert summary.idle_overhead_ratio == pytest.approx(800.0 / 3600.0, rel=1e-6)
    assert summary.startup_overhead_ratio == pytest.approx(300.0 / 3600.0, rel=1e-6)
    assert summary.cost_per_1000_pages_usd == pytest.approx(0.34 / 680 * 1000)
    assert summary.gpu_seconds_per_page == pytest.approx(3600.0 / 680)
    lines = "\n".join(summary.table_lines())
    assert "$/1,000 pages" in lines
    assert "operational eff." in lines


def test_campaign_cost_refuses_to_total_an_unpriced_pod() -> None:
    priced = build_ledger_row(_pod(), useful_inference_seconds=100.0)
    unpriced = build_ledger_row(
        _pod(pod_id="pod_b", listed_rate_usd_per_hour=None), useful_inference_seconds=100.0
    )
    summary = summarize([priced, unpriced], successful_pages=10, attempted_pages=10)
    assert summary.total_cost_usd is None
    assert summary.cost_per_1000_pages_usd is None
    assert any("not computable from record" in note for note in summary.notes)
    assert "unmeasured" in "\n".join(summary.table_lines())


def test_campaign_cost_with_no_pods_is_null_not_zero() -> None:
    summary = summarize([], successful_pages=0, attempted_pages=0)
    assert summary.total_cost_usd is None
    assert summary.operational_efficiency is None
    assert any("nothing has been provisioned" in note for note in summary.notes)


def test_ledger_prices_a_multi_gpu_pod_by_gpu_count() -> None:
    """D57 (defect: pod gx5b5cakrhp359, 2 x H100 billed as if it were 1)."""

    row = build_ledger_row(
        _pod(gpu_count=2, listed_rate_usd_per_hour=3.49),
        useful_inference_seconds=0.0,
    )
    assert row.gpu_count == 2
    # billed_seconds is 3600 from _pod()'s one-hour window.
    assert row.estimated_provider_cost_usd == pytest.approx(3.49 * 2)
    assert row.wasted_cost_usd == pytest.approx(3.49 * 2)


def test_ledger_defaults_a_pod_with_no_gpu_count_to_one() -> None:
    row = build_ledger_row(_pod(), useful_inference_seconds=2400.0)
    assert row.gpu_count == 1
    assert row.estimated_provider_cost_usd == pytest.approx(0.34)


def test_summarize_labels_pods_still_billing_to_now() -> None:
    """A pod with no terminated_at is measured to now, not to teardown, and
    that must be legible in the summary rather than silently blended into a
    total that also contains settled pods (root cause of the `cost` command
    reporting more GPU-hours than cost/pod_ledger.jsonl carries).
    """

    closed = build_ledger_row(_pod(), useful_inference_seconds=100.0)
    still_open = build_ledger_row(
        _pod(pod_id="pod_open", terminated_at=None),
        useful_inference_seconds=0.0,
        now=datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC),
    )
    summary = summarize([closed, still_open], successful_pages=10, attempted_pages=10)
    assert any("no terminated_at" in note and "1 of 2" in note for note in summary.notes)
    assert any("1 pod(s) are settled" in note for note in summary.notes)
    # nothing is dropped: both pods still count toward the total.
    assert summary.pod_count == 2
    expected_billed = closed.billed_seconds + still_open.billed_seconds
    assert summary.billed_seconds == pytest.approx(expected_billed)


def test_summarize_says_nothing_extra_when_every_pod_is_closed() -> None:
    row = build_ledger_row(_pod(), useful_inference_seconds=100.0)
    summary = summarize([row], successful_pages=10, attempted_pages=10)
    assert not any("no terminated_at" in note for note in summary.notes)


# ------------------------------------------------------------------ freeze


def _write_page(paths: CampaignPaths, model_key: str, case_key: str, raw: str) -> None:
    canonical = raw.upper()
    atomic_write_bytes(paths.raw_dir(model_key) / f"{case_key}.raw.txt", raw.encode("utf-8"))
    atomic_write_bytes(paths.canonical_dir(model_key) / f"{case_key}.md", canonical.encode("utf-8"))
    write_json_atomic(
        paths.receipt_dir(model_key) / f"{case_key}.json",
        {
            "schema": "tavonel.arena.page_receipt.v1",
            "case_key": case_key,
            "sample_id": f"omnidoc:images/{case_key}",
            "benchmark": "omnidoc",
            "status": "SUCCESS",
            "raw_output_sha256": sha256_text(raw),
            "canonical_output_sha256": sha256_text(canonical),
        },
    )


def test_freeze_writes_a_manifest_and_a_marker(paths: CampaignPaths) -> None:
    for index in range(3):
        _write_page(paths, "paddleocr_vl_1_6", f"case-{index:03d}", f"page {index}\n")
    result = freeze_model(
        "paddleocr_vl_1_6",
        paths=paths,
        model_revision=EXPECTED_REVISION,
        runtime_image_digest="sha256:" + "b" * 64,
    )
    assert result.frozen is True
    assert result.sample_count == 3
    assert result.success_count == 3
    manifest = paths.frozen_manifest("paddleocr_vl_1_6").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in manifest.strip().splitlines()]
    assert [entry["case_key"] for entry in entries] == ["case-000", "case-001", "case-002"]
    marker = json.loads(paths.frozen_marker("paddleocr_vl_1_6").read_text(encoding="utf-8"))
    assert marker["manifest_sha256"] == result.manifest_sha256
    assert marker["model_revision"] == EXPECTED_REVISION


def test_freeze_refuses_when_a_file_no_longer_matches_its_hash(
    paths: CampaignPaths,
) -> None:
    """A frozen manifest pointing at moved bytes is worse than no manifest."""

    for index in range(2):
        _write_page(paths, "glm_ocr", f"case-{index:03d}", f"page {index}\n")
    tampered = paths.raw_dir("glm_ocr") / "case-001.raw.txt"
    tampered.write_text("someone edited this after the fact\n", encoding="utf-8")

    result = freeze_model("glm_ocr", paths=paths)
    assert result.frozen is False
    assert result.manifest_path is None
    assert not paths.frozen_manifest("glm_ocr").exists()
    assert len(result.mismatches) == 1
    assert result.mismatches[0].case_key == "case-001"
    assert result.mismatches[0].field_name == "raw_output_sha256"


def test_freeze_refuses_when_a_referenced_file_is_missing(paths: CampaignPaths) -> None:
    _write_page(paths, "olmocr2", "case-000", "page\n")
    (paths.canonical_dir("olmocr2") / "case-000.md").unlink()
    result = freeze_model("olmocr2", paths=paths)
    assert result.frozen is False
    assert result.missing_files


# ----------------------------------------------------------------- cleanup


def test_cleanup_verify_loops_until_zero(paths: CampaignPaths) -> None:
    from arena.constants import CAMPAIGN_ID as CID

    # D20: an EXITED pod is *not* cleaned up. Only an empty listing verifies.
    responses = [
        {"pods": [pod_payload(status="EXITED", env={"ARENA_CAMPAIGN_ID": CID}, cost=0.0)]},
        {"pods": []},
    ]
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        payload = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return json_response(200, payload)

    client = RunPodPodsClient(
        key=Secret("runpodfake0000000000000000", label="Runpod_B"),
        execute=True,
        transport=RecordingTransport(handler),
    )
    slept: list[float] = []
    result = verify_cleanup(
        client,
        receipt_path=paths.cleanup_receipt,
        max_attempts=5,
        poll_seconds=1.0,
        sleep=slept.append,
    )
    client.close()
    assert result.verified is True
    assert result.attempts == 2
    assert slept == [1.0]
    receipt = json.loads(paths.cleanup_receipt.read_text(encoding="utf-8"))
    assert receipt["verified"] is True
    assert receipt["running_pod_count"] == 0


def test_cleanup_verify_reports_failure_rather_than_hiding_it(
    paths: CampaignPaths,
) -> None:
    from arena.constants import CAMPAIGN_ID as CID

    client = RunPodPodsClient(
        key=Secret("runpodfake0000000000000000", label="Runpod_B"),
        execute=True,
        transport=RecordingTransport(
            lambda _: json_response(200, {"pods": [pod_payload(env={"ARENA_CAMPAIGN_ID": CID})]})
        ),
    )
    result = verify_cleanup(
        client,
        receipt_path=paths.cleanup_receipt,
        max_attempts=2,
        poll_seconds=0.0,
        sleep=lambda _: None,
    )
    client.close()
    assert result.verified is False
    assert result.running_pod_count == 1
    receipt = json.loads(paths.cleanup_receipt.read_text(encoding="utf-8"))
    assert receipt["verified"] is False
    assert any("NOT verified" in note for note in receipt["notes"])


def test_cleanup_verify_in_a_dry_run_claims_nothing(paths: CampaignPaths) -> None:
    client = RunPodPodsClient(
        key=Secret("runpodfake0000000000000000", label="Runpod_B"), execute=False
    )
    result = verify_cleanup(client, receipt_path=paths.cleanup_receipt)
    assert result.verified is False
    assert result.mode == "dry_run"
    assert any("unverified" in note for note in result.notes)


def test_cleanup_ignores_pods_from_another_campaign(paths: CampaignPaths) -> None:
    """Someone else's pod is someone else's. Neither name nor env is ours."""

    client = RunPodPodsClient(
        key=Secret("runpodfake0000000000000000", label="Runpod_B"),
        execute=True,
        transport=RecordingTransport(
            lambda _: json_response(
                200,
                {
                    "pods": [
                        pod_payload(
                            name="someone-elses-notebook",
                            env={"ARENA_CAMPAIGN_ID": "OTHER-CAMPAIGN"},
                        )
                    ]
                },
            )
        ),
    )
    result = verify_cleanup(client, receipt_path=paths.cleanup_receipt, max_attempts=1)
    client.close()
    assert result.verified is True


def test_cleanup_claims_a_pod_that_only_the_name_prefix_identifies(
    paths: CampaignPaths,
) -> None:
    """D24: a pod whose env the provider dropped is still this campaign's.

    The name prefix is the second witness precisely because a pod that lost
    its `ARENA_CAMPAIGN_ID` must not become nobody's problem while it bills.
    """

    client = RunPodPodsClient(
        key=Secret("runpodfake0000000000000000", label="Runpod_B"),
        execute=True,
        transport=RecordingTransport(lambda _: json_response(200, {"pods": [pod_payload(env={})]})),
    )
    result = verify_cleanup(client, receipt_path=paths.cleanup_receipt, max_attempts=1)
    client.close()
    assert result.verified is False
    assert result.remaining[0].matched_by == "name_prefix"


# ------------------------------------------------------- D87 completeness


def _queued(paths: CampaignPaths, model_key: str, states: dict[str, int]) -> None:
    """Put jobs in the queue in the given states, without dispatching any."""

    from arena.controller.queue import CampaignQueue

    with CampaignQueue(paths.queue_db) as queue:
        rows = []
        index = 0
        for state, count in states.items():
            for _ in range(count):
                rows.append((f"{model_key}-job-{index:04d}", state))
                index += 1
        for job_id, state in rows:
            queue._connection.execute(
                "INSERT INTO jobs (inference_job_id, model_key, benchmark, sample_id, "
                "case_key, shard_id, job_kind, state, attempt, retry_count, queued_at, "
                "updated_at) VALUES (?,?,?,?,?,?,?,?,0,0,?,?)",
                (
                    job_id,
                    model_key,
                    "omnidoc",
                    f"omnidoc:images/{job_id}",
                    job_id,
                    "shard-000",
                    "page",
                    state,
                    "2026-09-04T00:00:00Z",
                    "2026-09-04T00:00:00Z",
                ),
            )
        queue._connection.commit()


def test_freeze_refuses_a_run_that_is_still_dispatching(paths: CampaignPaths) -> None:
    """D87. A partial manifest is indistinguishable from a whole one."""

    for index in range(3):
        _write_page(paths, "paddleocr_vl_1_6", f"case-{index:03d}", f"page {index}\n")
    _queued(paths, "paddleocr_vl_1_6", {"SUCCESS": 3, "PENDING": 2})

    code = main(["freeze", "--model", "paddleocr_vl_1_6", "--root", str(paths.root)])

    assert code != 0
    assert not paths.frozen_marker("paddleocr_vl_1_6").exists()
    assert not paths.frozen_manifest("paddleocr_vl_1_6").exists()


def test_a_settled_run_freezes_and_the_marker_says_it_is_complete(
    paths: CampaignPaths,
) -> None:
    """SUCCESS, FAILED and QUARANTINED have all reached an answer."""

    for index in range(3):
        _write_page(paths, "paddleocr_vl_1_6", f"case-{index:03d}", f"page {index}\n")
    _queued(paths, "paddleocr_vl_1_6", {"SUCCESS": 3, "FAILED": 1, "QUARANTINED": 1})

    code = main(["freeze", "--model", "paddleocr_vl_1_6", "--root", str(paths.root)])

    assert code == 0
    marker = json.loads(paths.frozen_marker("paddleocr_vl_1_6").read_text(encoding="utf-8"))
    assert marker["complete"] is True
    assert marker["planned_count"] == 5
    assert marker["settled_count"] == 5


def test_a_deliberate_partial_freeze_is_stamped_as_partial(paths: CampaignPaths) -> None:
    """--allow-incomplete seals, and says in the marker that it did."""

    for index in range(3):
        _write_page(paths, "paddleocr_vl_1_6", f"case-{index:03d}", f"page {index}\n")
    _queued(paths, "paddleocr_vl_1_6", {"SUCCESS": 3, "PENDING": 2})

    code = main(
        ["freeze", "--model", "paddleocr_vl_1_6", "--allow-incomplete", "--root", str(paths.root)]
    )

    assert code == 0
    marker = json.loads(paths.frozen_marker("paddleocr_vl_1_6").read_text(encoding="utf-8"))
    assert marker["complete"] is False
    assert marker["planned_count"] == 5
    assert marker["settled_count"] == 3
    assert marker["sample_count"] == 3
