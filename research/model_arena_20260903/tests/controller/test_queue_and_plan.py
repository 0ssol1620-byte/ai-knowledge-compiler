"""Queue idempotency and deterministic planning."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from arena.controller.ids_local import (
    IDS_SOURCE_CORE,
    ids_source,
    inference_job_id,
    shard_id,
    worker_id,
)
from arena.controller.paths import CampaignPaths
from arena.controller.plan import (
    ModelPlanEntry,
    PlanError,
    build_plan,
    load_model_registry,
    load_source_manifest,
)
from arena.controller.queue import CampaignQueue, JobRecord, PodRecord, QueueError
from arena.controller.scheduler import SchedulerError
from tests.controller.conftest import (
    MODEL_KEY,
    make_sample,
    write_model_registry,
    write_source_manifest,
)


def test_inference_job_id_is_the_contract_hash() -> None:
    fields = {
        "campaign_id": "C",
        "benchmark_revision": "R",
        "sample_id": "S",
        "source_sha256": "sha256:" + "a" * 64,
        "model_repo": "repo",
        "model_revision": "rev",
        "runtime_image_digest": "sha256:" + "b" * 64,
        "prompt_sha256": "sha256:" + "c" * 64,
        "inference_config_sha256": "sha256:" + "d" * 64,
    }
    first = inference_job_id(**fields)  # type: ignore[arg-type]
    assert len(first) == 64
    assert first == inference_job_id(**fields)  # type: ignore[arg-type]
    changed = {**fields, "prompt_sha256": "sha256:" + "e" * 64}
    assert inference_job_id(**changed) != first  # type: ignore[arg-type]


def test_inference_job_id_refuses_an_empty_field() -> None:
    with pytest.raises(ValueError, match="benchmark_revision"):
        inference_job_id(
            campaign_id="C",
            benchmark_revision="",
            sample_id="S",
            source_sha256="sha256:" + "a" * 64,
            model_repo="repo",
            model_revision="rev",
            runtime_image_digest="sha256:" + "b" * 64,
            prompt_sha256="sha256:" + "c" * 64,
            inference_config_sha256="sha256:" + "d" * 64,
        )


def test_shard_and_worker_ids_follow_the_contract() -> None:
    assert shard_id("mineru_vlm", "olmocr", 7) == "mineru_vlm-olmocr-0007"
    assert worker_id("mineru_vlm", 2, "pod_x") == "mineru_vlm-w2-pod_x"


def test_plan_is_deterministic(samples: tuple, entry: ModelPlanEntry) -> None:
    first = build_plan(model_key=MODEL_KEY, samples=samples, entry=entry)
    shuffled = tuple(reversed(samples))
    second = build_plan(model_key=MODEL_KEY, samples=shuffled, entry=entry)
    assert [job.inference_job_id for job in first.jobs] == [
        job.inference_job_id for job in second.jobs
    ]
    assert [shard.shard_id for shard in first.shards] == [
        shard.shard_id for shard in second.shards
    ]


def test_plan_shards_by_the_registry_hint(samples: tuple, entry: ModelPlanEntry) -> None:
    small = replace(entry, shard_size=10)
    plan = build_plan(model_key=MODEL_KEY, samples=samples, entry=small)
    assert len(plan.shards) == 1
    assert plan.shards[0].job_count == 6
    assert plan.shards[0].predicted_seconds == pytest.approx(6 * 3.525)


def test_plan_refuses_duplicate_job_ids(entry: ModelPlanEntry) -> None:
    duplicate = make_sample(0)
    with pytest.raises(PlanError, match="derive the same inference_job_id"):
        build_plan(model_key=MODEL_KEY, samples=(duplicate, duplicate), entry=entry)


def test_manifest_reader_refuses_a_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "source_manifest.jsonl"
    path.write_text('{"sample_id": "omnidoc:x"}\n', encoding="utf-8")
    with pytest.raises(PlanError, match="case_key"):
        load_source_manifest(path)


def test_manifest_reader_refuses_a_duplicate_case_key(tmp_path: Path) -> None:
    path = tmp_path / "source_manifest.jsonl"
    write_source_manifest(path, [make_sample(0), make_sample(0)])
    with pytest.raises(PlanError, match="duplicates case_key"):
        load_source_manifest(path)


def test_manifest_reader_names_the_absent_file(tmp_path: Path) -> None:
    with pytest.raises(PlanError, match="lane A2"):
        load_source_manifest(tmp_path / "nothing.jsonl")


def test_registry_reader_round_trips(tmp_path: Path, entry: ModelPlanEntry) -> None:
    path = tmp_path / "model_registry.json"
    write_model_registry(path, entry)
    loaded = load_model_registry(path, MODEL_KEY)
    assert loaded.model_repo == entry.model_repo
    assert loaded.per_worker_concurrency == 2
    assert loaded.predicted_seconds_per_page == pytest.approx(3.525)
    assert "historical" in loaded.predicted_seconds_source


def test_registry_reader_refuses_an_out_of_band_shard_hint(
    tmp_path: Path, entry: ModelPlanEntry
) -> None:
    path = tmp_path / "model_registry.json"
    write_model_registry(path, entry, shard_size_hint=5000)
    with pytest.raises(PlanError, match=r"15\.6 band"):
        load_model_registry(path, MODEL_KEY)


def test_registry_reader_refuses_mineru_vlm_above_concurrency_one(
    tmp_path: Path, entry: ModelPlanEntry
) -> None:
    """Masterplan section 14 is a rule, not a default to be clamped silently."""

    path = tmp_path / "model_registry.json"
    vlm = replace(entry, model_key="mineru_vlm")
    write_model_registry(path, vlm, concurrency_policy={"per_worker": 3})
    with pytest.raises(SchedulerError, match="section 14"):
        load_model_registry(path, "mineru_vlm")


def test_missing_predicted_seconds_is_labelled_not_invented(
    tmp_path: Path, entry: ModelPlanEntry
) -> None:
    path = tmp_path / "model_registry.json"
    write_model_registry(path, entry, historical_sec_per_page=None)
    loaded = load_model_registry(path, MODEL_KEY)
    assert "ordering hint only" in loaded.predicted_seconds_source


def test_enqueue_is_idempotent(paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry) -> None:
    plan = build_plan(model_key=MODEL_KEY, samples=samples, entry=entry)
    with CampaignQueue(paths.queue_db) as queue:
        added, skipped = queue.enqueue(plan.jobs)
        assert (added, skipped) == (6, 0)
        added, skipped = queue.enqueue(plan.jobs)
        assert (added, skipped) == (0, 6)
        assert queue.counts_by_state(model_key=MODEL_KEY)["PENDING"] == 6


def test_a_success_job_is_never_re_enqueued_or_reset(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    plan = build_plan(model_key=MODEL_KEY, samples=samples, entry=entry)
    job = plan.jobs[0]
    with CampaignQueue(paths.queue_db) as queue:
        queue.enqueue(plan.jobs)
        queue.mark_running(job.inference_job_id, "w0")
        queue.mark_success(
            job.inference_job_id,
            raw_output_sha256="sha256:" + "1" * 64,
            receipt_sha256="sha256:" + "2" * 64,
        )
        # Re-planning the same campaign skips it entirely.
        added, skipped = queue.enqueue(plan.jobs)
        assert (added, skipped) == (0, 6)
        # And every path that would re-run it refuses.
        for operation in (
            lambda: queue.mark_running(job.inference_job_id, "w1"),
            lambda: queue.requeue(job.inference_job_id, reason="operator"),
            lambda: queue.mark_failed(job.inference_job_id, error_class="UNKNOWN"),
        ):
            with pytest.raises(QueueError, match="already SUCCESS"):
                operation()
        assert queue.pending_jobs(model_key=MODEL_KEY, limit=100)[0].case_key != job.case_key


def test_success_requires_both_hashes(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    plan = build_plan(model_key=MODEL_KEY, samples=samples, entry=entry)
    with CampaignQueue(paths.queue_db) as queue:
        queue.enqueue(plan.jobs)
        with pytest.raises(QueueError, match="requires both"):
            queue.mark_success(
                plan.jobs[0].inference_job_id, raw_output_sha256="", receipt_sha256="x"
            )


def test_resume_reopens_the_same_database(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    plan = build_plan(model_key=MODEL_KEY, samples=samples, entry=entry)
    with CampaignQueue(paths.queue_db) as queue:
        queue.enqueue(plan.jobs)
        queue.mark_running(plan.jobs[0].inference_job_id, "w0")
        queue.mark_success(
            plan.jobs[0].inference_job_id,
            raw_output_sha256="sha256:" + "1" * 64,
            receipt_sha256="sha256:" + "2" * 64,
        )
    with CampaignQueue(paths.queue_db) as reopened:
        counts = reopened.counts_by_state(model_key=MODEL_KEY)
        assert counts["SUCCESS"] == 1
        assert counts["PENDING"] == 5


def test_pod_record_gpu_count_round_trips(paths: CampaignPaths) -> None:
    """D57: a 2-GPU pod's count survives an upsert/read cycle."""

    with CampaignQueue(paths.queue_db) as queue:
        queue.upsert_pod(
            PodRecord(
                pod_id="pod_2gpu",
                model_key="infinity_parser2_pro",
                name="arena-infinity-parser2-pro-w0-20260903v1",
                state="TERMINATED",
                gpu_type="NVIDIA H100 80GB HBM3",
                listed_rate_usd_per_hour=3.49,
                gpu_count=2,
                provisioned_at="2026-09-03T20:46:34Z",
                terminated_at="2026-09-03T20:54:13Z",
            )
        )
    with CampaignQueue(paths.queue_db) as reopened:
        pods = {pod.pod_id: pod for pod in reopened.pods()}
        assert pods["pod_2gpu"].gpu_count == 2


def test_pod_record_gpu_count_defaults_to_one(paths: CampaignPaths) -> None:
    """A pod row that never named gpu_count means one GPU, not unknown."""

    with CampaignQueue(paths.queue_db) as queue:
        queue.upsert_pod(
            PodRecord(
                pod_id="pod_default",
                model_key="paddleocr_vl_1_6",
                name="arena-paddleocr-vl-1-6-w0-20260903v1",
                state="TERMINATED",
                listed_rate_usd_per_hour=0.34,
            )
        )
    with CampaignQueue(paths.queue_db) as reopened:
        pods = {pod.pod_id: pod for pod in reopened.pods()}
        assert pods["pod_default"].gpu_count == 1


def test_pod_record_refuses_a_non_positive_gpu_count() -> None:
    with pytest.raises(QueueError, match="gpu_count"):
        PodRecord(
            pod_id="pod_bad",
            model_key="paddleocr_vl_1_6",
            name="arena-paddleocr-vl-1-6-w0-20260903v1",
            state="TERMINATED",
            gpu_count=0,
        )


def test_a_pods_table_without_gpu_count_is_migrated_on_open(paths: CampaignPaths) -> None:
    """D57 backward compat: a queue database created before this revision --
    literally, a ``pods`` table with no ``gpu_count`` column -- must still
    open, and every pre-existing row must read back as one GPU rather than
    failing to load.
    """

    import sqlite3

    paths.queue_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(paths.queue_db)
    con.execute(
        """
        CREATE TABLE pods (
            pod_id TEXT PRIMARY KEY,
            worker_id TEXT,
            model_key TEXT NOT NULL,
            name TEXT NOT NULL,
            gpu_type TEXT,
            cloud_type TEXT,
            data_center_id TEXT,
            runtime_mode TEXT,
            listed_rate_usd_per_hour REAL,
            price_snapshot_sha256 TEXT,
            provisioned_at TEXT,
            model_ready_at TEXT,
            last_job_finished_at TEXT,
            terminated_at TEXT,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        INSERT INTO pods (pod_id, model_key, name, gpu_type, listed_rate_usd_per_hour,
            provisioned_at, terminated_at, state, updated_at)
        VALUES ('old_pod', 'paddleocr_vl_1_6', 'arena-old', 'NVIDIA GeForce RTX 4090', 0.34,
            '2026-09-01T00:00:00Z', '2026-09-01T01:00:00Z', 'TERMINATED', '2026-09-01T01:00:00Z')
        """
    )
    con.commit()
    con.close()

    with CampaignQueue(paths.queue_db) as queue:
        pods = {pod.pod_id: pod for pod in queue.pods()}
        assert pods["old_pod"].gpu_count == 1


def test_quarantined_jobs_are_not_dispatchable(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    plan = build_plan(model_key=MODEL_KEY, samples=samples, entry=entry)
    with CampaignQueue(paths.queue_db) as queue:
        queue.enqueue(plan.jobs)
        queue.mark_running(plan.jobs[0].inference_job_id, "w0")
        queue.mark_failed(
            plan.jobs[0].inference_job_id, error_class="TENSOR_SHAPE", quarantine=True
        )
        pending = queue.pending_jobs(model_key=MODEL_KEY, limit=100)
        assert plan.jobs[0].inference_job_id not in {job.inference_job_id for job in pending}


def test_error_class_outside_the_taxonomy_is_refused(paths: CampaignPaths) -> None:
    with pytest.raises(QueueError, match="outside the taxonomy"):
        JobRecord(
            inference_job_id="a" * 64,
            model_key=MODEL_KEY,
            benchmark="omnidoc",
            sample_id="s",
            case_key="c",
            shard_id="s0",
            job_kind="inference",
            error_class="MADE_UP",
        )


def test_local_and_core_id_derivations_agree() -> None:
    """Lane A1 owns arena.core.ids; the controller's copy must not drift.

    When A1's module is present the controller delegates to it. This asserts
    the two derivations produce the same id for the same inputs, so a future
    divergence surfaces here rather than as duplicate paid inference.
    """

    import hashlib

    from arena.provider.safety import canonical_json_bytes

    fields = {
        "campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1",
        "benchmark_revision": "aa1ee96d" + "0" * 32,
        "sample_id": "omnidoc:images/PPT_1001115_eng_page_003",
        "source_sha256": "sha256:" + "a" * 64,
        "model_repo": "PaddlePaddle/PaddleOCR-VL-1.6",
        "model_revision": "b" * 40,
        "runtime_image_digest": "sha256:" + "c" * 64,
        "prompt_sha256": "sha256:" + "d" * 64,
        "inference_config_sha256": "sha256:" + "e" * 64,
    }
    local = hashlib.sha256(canonical_json_bytes(fields)).hexdigest()
    assert inference_job_id(**fields) == local  # type: ignore[arg-type]
    if ids_source() == IDS_SOURCE_CORE:
        from arena.core.ids import inference_job_id as core_ids

        assert core_ids(**fields) == local  # type: ignore[arg-type]


def test_a_failed_job_with_no_retry_budget_is_not_re_dispatched(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    """Masterplan 15.9's most expensive pattern: retrying a deterministic error.

    The retry path returns a job to PENDING explicitly. Anything still FAILED
    has spent its budget, so it must never appear in the dispatch selection.
    """

    plan = build_plan(model_key=MODEL_KEY, samples=samples, entry=entry)
    job = plan.jobs[0]
    with CampaignQueue(paths.queue_db) as queue:
        queue.enqueue(plan.jobs)
        queue.mark_running(job.inference_job_id, "w0")
        queue.mark_failed(job.inference_job_id, error_class="DEPENDENCY")
        dispatchable = {
            item.inference_job_id for item in queue.pending_jobs(model_key=MODEL_KEY, limit=100)
        }
        assert job.inference_job_id not in dispatchable
        assert len(dispatchable) == 5
        # An allowed retry does put it back, under the same id.
        queue.requeue(job.inference_job_id, reason="worker lost")
        assert job.inference_job_id in {
            item.inference_job_id for item in queue.pending_jobs(model_key=MODEL_KEY, limit=100)
        }


RACER_SOURCE = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from arena.controller.queue import CampaignQueue, JobRecord
jobs = [
    JobRecord(
        inference_job_id=f"job-{i:05d}",
        model_key="racer",
        benchmark="omnidoc",
        sample_id=f"s{i}",
        case_key=f"c{i}",
        shard_id=f"shard-{i % 4}",
        job_kind="inference",
    )
    for i in range(400)
]
with CampaignQueue(Path(sys.argv[1])) as queue:
    added, skipped = queue.enqueue(jobs)
print(f"{added} {skipped}")'''


def test_two_processes_planning_the_same_model_do_not_collide(tmp_path: Path) -> None:
    """D80: one driver per shard slice means several of them plan the same
    model at the same instant. Before this, ``enqueue`` read "absent" and then
    inserted, so both processes inserted and the loser died on
    jobs.inference_job_id -- eighteen of thirty-one Full Run slices exited that
    way on 2026-09-04, the rest on "database is locked" while nine drivers took
    the write lock 5,132 times each.

    Threads would share a connection, so this races real subprocesses against
    the real file.
    """

    import subprocess
    import sys

    namespace_root = str(Path(__file__).resolve().parents[2])
    database = tmp_path / "race.sqlite"
    with CampaignQueue(database) as queue:
        queue.enqueue([])  # create the schema before the racers open it

    script = tmp_path / "racer.py"
    script.write_text(RACER_SOURCE, encoding="utf-8")

    racers = [
        subprocess.Popen(
            [sys.executable, str(script), str(database), namespace_root],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    results = [racer.communicate() for racer in racers]

    for (out, err), process in zip(results, racers, strict=True):
        assert process.returncode == 0, err
        assert out.strip(), err
    assert sum(int(out.split()[0]) for out, _err in results) == 400
    with CampaignQueue(database) as queue:
        assert len(queue.jobs_for_model("racer", state="PENDING")) == 400
