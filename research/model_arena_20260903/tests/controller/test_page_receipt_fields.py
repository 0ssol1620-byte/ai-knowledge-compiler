"""Page-receipt fields the integration pass added, and the bytes behind them.

D3 -- ``semantic_error_class`` is *copied* from the worker response and
``recovery_job_id`` is set only on a recovery job.

D8 -- the raw and canonical files hold exactly the UTF-8 bytes whose digests
the receipt records: no BOM, no appended newline, no CRLF translation, and
nothing normalized. The test uses non-ASCII text and a trailing newline
because those are the two ways this silently goes wrong on Windows.
"""

from __future__ import annotations

import json

import pytest
from arena.controller.events import EventLog
from arena.controller.freeze import freeze_model
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry, SourceSample, build_plan
from arena.controller.queue import CampaignQueue
from arena.controller.run import RunError, dispatch_page
from arena.provider.safety import sha256_bytes, sha256_text
from arena.provider.worker_client import WorkerClient, worker_base_url
from tests.controller.conftest import MODEL_KEY, sample_bytes
from tests.controller.test_run_loop import BEARER, FakeWorkerTransport, _response_body

# The en dash, the ellipsis and the combining-capable Latin are deliberate: a
# byte-exactness test that used only ASCII would prove nothing.
RAW_NON_ASCII = "제목\n\n– en dash, ünicode, 漢字 …\ntrailing newline follows\n"  # noqa: RUF001
CANONICAL_NON_ASCII = "# 제목\n\n– en dash, ünicode, 漢字 …\n"  # noqa: RUF001


def _text_response(job_id: str, raw: str, canonical: str, **extra: object) -> dict[str, object]:
    return _response_body(
        job_id,
        output_bytes=len(raw.encode("utf-8")),
        output_chars=len(raw),
        raw_output={
            "raw_text": raw,
            "output_format": "markdown",
            "native_json": None,
            "usage": {},
            "warnings": [],
        },
        canonical={
            "markdown": canonical,
            "elements": None,
            "lossy": False,
            "conversion_notes": [],
        },
        raw_output_sha256=sha256_text(raw),
        canonical_output_sha256=sha256_text(canonical),
        **extra,
    )


def _dispatch(
    paths: CampaignPaths,
    samples: tuple[SourceSample, ...],
    entry: ModelPlanEntry,
    *,
    transport: FakeWorkerTransport,
    job_kind: str = "inference",
    recovery_job_id: str | None = None,
) -> tuple[str, object]:
    plan = build_plan(model_key=MODEL_KEY, samples=samples, entry=entry, job_kind=job_kind)
    queue = CampaignQueue(paths.queue_db)
    queue.upsert_shards(plan.shards)
    queue.enqueue(plan.jobs)
    events = EventLog(paths.events_log)
    client = WorkerClient(worker_base_url("pod_fake"), bearer=BEARER, transport=transport)
    job = queue.get_job(plan.jobs[0].inference_job_id)
    assert job is not None
    sample = next(item for item in samples if item.case_key == job.case_key)
    try:
        outcome = dispatch_page(
            worker=client,
            worker_id="w0",
            pod_id="pod_fake",
            gpu_type="NVIDIA GeForce RTX 4090",
            job=job,
            sample=sample,
            entry=entry,
            paths=paths,
            queue=queue,
            events=events,
            image_bytes=sample_bytes(sample),
            recovery_job_id=recovery_job_id,
        )
    finally:
        queue.close()
        client.close()
    return job.case_key, outcome


def _receipt(paths: CampaignPaths, case_key: str) -> dict[str, object]:
    path = paths.receipt_dir(MODEL_KEY) / f"{case_key}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


# --------------------------------------------------------------------- D3


def test_an_empty_output_is_success_carrying_output_empty(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    transport = FakeWorkerTransport(
        run_override=lambda job_id: _text_response(
            job_id, "", "", semantic_error_class="OUTPUT_EMPTY"
        )
    )
    case_key, outcome = _dispatch(paths, samples, entry, transport=transport)
    assert outcome.succeeded  # type: ignore[attr-defined]
    receipt = _receipt(paths, case_key)
    assert receipt["status"] == "SUCCESS"
    assert receipt["error_class"] is None
    assert receipt["semantic_error_class"] == "OUTPUT_EMPTY"
    assert receipt["recovery_job_id"] is None


def test_no_semantic_class_means_null_not_a_guess(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    case_key, _ = _dispatch(paths, samples, entry, transport=FakeWorkerTransport())
    assert _receipt(paths, case_key)["semantic_error_class"] is None


def test_a_semantic_class_outside_the_enum_is_rejected(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    transport = FakeWorkerTransport(
        run_override=lambda job_id: _response_body(job_id, semantic_error_class="OUTPUT_UGLY")
    )
    _case_key, outcome = _dispatch(paths, samples, entry, transport=transport)
    assert outcome.succeeded is False  # type: ignore[attr-defined]
    assert outcome.error_class == "OUTPUT_MALFORMED"  # type: ignore[attr-defined]


def test_a_recovery_receipt_names_its_recovery_job(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    case_key, _ = _dispatch(
        paths,
        samples,
        entry,
        transport=FakeWorkerTransport(),
        job_kind="recovery",
        recovery_job_id="rec-0001",
    )
    receipt = _receipt(paths, case_key)
    assert receipt["job_kind"] == "recovery"
    assert receipt["recovery_job_id"] == "rec-0001"


def test_a_recovery_page_without_its_job_id_fails_closed(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    with pytest.raises(RunError, match="recovery_job_id"):
        _dispatch(paths, samples, entry, transport=FakeWorkerTransport(), job_kind="recovery")


def test_a_recovery_id_on_an_ordinary_page_is_refused(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    with pytest.raises(RunError, match="job_kind"):
        _dispatch(
            paths,
            samples,
            entry,
            transport=FakeWorkerTransport(),
            recovery_job_id="rec-0002",
        )


# --------------------------------------------------------------------- D8


def test_the_files_hold_the_exact_bytes_that_were_hashed(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    transport = FakeWorkerTransport(
        run_override=lambda job_id: _text_response(
            job_id, RAW_NON_ASCII, CANONICAL_NON_ASCII
        )
    )
    case_key, outcome = _dispatch(paths, samples, entry, transport=transport)
    assert outcome.succeeded  # type: ignore[attr-defined]

    raw_bytes = (paths.raw_dir(MODEL_KEY) / f"{case_key}.raw.txt").read_bytes()
    canonical_bytes = (paths.canonical_dir(MODEL_KEY) / f"{case_key}.md").read_bytes()

    assert raw_bytes == RAW_NON_ASCII.encode("utf-8")
    assert canonical_bytes == CANONICAL_NON_ASCII.encode("utf-8")
    assert not raw_bytes.startswith(b"\xef\xbb\xbf")  # no BOM
    assert raw_bytes.endswith(b"\n")
    assert not raw_bytes.endswith(b"\n\n")  # nothing appended
    assert b"\r\n" not in raw_bytes  # no CRLF translation on Windows

    receipt = _receipt(paths, case_key)
    assert receipt["raw_output_sha256"] == sha256_bytes(raw_bytes) == sha256_text(RAW_NON_ASCII)
    assert receipt["canonical_output_sha256"] == sha256_bytes(canonical_bytes)


def test_freeze_recomputes_those_bytes_and_agrees(
    paths: CampaignPaths, samples: tuple, entry: ModelPlanEntry
) -> None:
    transport = FakeWorkerTransport(
        run_override=lambda job_id: _text_response(
            job_id, RAW_NON_ASCII, CANONICAL_NON_ASCII
        )
    )
    _dispatch(paths, samples, entry, transport=transport)
    result = freeze_model(MODEL_KEY, paths=paths)
    assert result.frozen is True
    assert result.mismatches == ()
    assert result.missing_files == ()
