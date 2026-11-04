from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pytest
from arena.controller.watchdogs import CircuitBreaker
from arena.provider.secrets import Secret
from arena.provider.worker_client import WorkerHTTPError
from karena import freeze as freeze_module
from karena import table_track
from karena.corpus import Case
from karena.serving import ChatResult, LlmPodSpec, VllmEndpoint, vllm_args
from karena.stage0 import Guard, StopRun, run_tasks
from karena.tasks import load_task

ROW = {
    "model_key": "qwen3_8b",
    "registry_id": "karena:qwen3_8b",
    "exact_model_id": "Qwen/Qwen3-8B",
    "exact_revision": "b968826d9c46dd6066d109eabc6255188de91218",
}


def _spec(key: Secret) -> LlmPodSpec:
    return LlmPodSpec(
        name="arena-qwen3-8b-w0-karena20261104",
        image_name="vllm/vllm-openai:v0.19.0@sha256:" + "a" * 64,
        gpu_type_ids=("NVIDIA L40S",),
        model_key="qwen3_8b",
        model_revision=ROW["exact_revision"],
        runtime_mode="baked",
        image_digest="sha256:" + "a" * 64,
        args=vllm_args(ROW, served_name="qwen3-8b", max_model_len=16384),
        api_key=key,
    )


def test_pod_payload_carries_args_and_redacts_the_vllm_key() -> None:
    key = Secret("kar" + "0123456789abcdef" * 3, label="VLLM_API_KEY")
    spec = _spec(key)
    payload = spec.to_payload("NVIDIA L40S")
    assert payload["cmd"][:3] == ["Qwen/Qwen3-8B", "--revision", ROW["exact_revision"]]  # type: ignore[index]
    assert payload["env"]["VLLM_API_KEY"] == key.reveal()  # type: ignore[index]
    redacted = spec.redacted_payload("NVIDIA L40S")
    assert redacted["env"]["VLLM_API_KEY"] == "<redacted>"  # type: ignore[index]
    assert key.reveal() not in json.dumps(redacted)


def _endpoint(handler: Any) -> VllmEndpoint:
    return VllmEndpoint(
        "pod",
        api_key=Secret("k" * 20, label="VLLM_API_KEY"),
        served_name="qwen3-8b",
        base_url="https://pod-8000.proxy.runpod.net",
        transport=httpx.MockTransport(handler),
    )


def test_readiness_and_chat_envelopes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["authorization"] != "Bearer " + "k" * 20:
            return httpx.Response(401)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen3-8b"}]})
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["strict"] is True
        assert "$schema" not in body["response_format"]["json_schema"]["schema"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"a":1}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    endpoint = _endpoint(handler)
    assert endpoint.ready() == {"stage": "READY"}
    result = endpoint.chat(
        [{"role": "user", "content": "x"}],
        schema={"$schema": "s", "type": "object"},
        schema_name="t",
        params={"temperature": 0, "seed": 0, "max_tokens": 5},
        chat_template_kwargs={},
    )
    assert (result.content, result.prompt_tokens, result.error) == ('{"a":1}', 7, None)
    refused = _endpoint(lambda request: httpx.Response(401))
    with pytest.raises(WorkerHTTPError) as caught:
        refused.ready()
    assert caught.value.status_code == 401
    broken = _endpoint(lambda request: httpx.Response(500, text="boom"))
    failed = broken.chat(
        [],
        schema={},
        schema_name="t",
        params={"temperature": 0, "seed": 0, "max_tokens": 1},
        chat_template_kwargs={},
    )
    assert failed.error == "HTTP 500" and failed.raw_body == "boom"


class FakeEndpoint:
    def __init__(self, reply: ChatResult) -> None:
        self.reply = reply
        self.calls = 0

    def chat(self, messages: Sequence[Mapping[str, str]], **_: Any) -> ChatResult:
        self.calls += 1
        return self.reply


def _doc_type_cases(n: int) -> list[Case]:
    return [
        Case(
            case_id=f"doc_type:{i}",
            task="doc_type",
            split="CALIBRATION",
            family_ids=("f",),
            origin="US_GOV_FR",
            language="en",
            source_doc_ids=(str(i),),
            licences=("US-GOV-17USC105",),
            input={"text": f"Federal Register rule {i}"},
            truth={"label": "FR_RULE"},
        )
        for i in range(n)
    ]


def _guard(tmp_path: Path, *, budget: float = 60.0, prior: float = 0.0) -> Guard:
    return Guard(
        run_dir=tmp_path,
        budget_usd=budget,
        prior_spend_usd=prior,
        rate_usd_per_hour=0.8,
        started=datetime.now(tz=UTC),
        max_seconds=3600.0,
        breaker=CircuitBreaker("qwen3_8b"),
    )


def _run(tmp_path: Path, endpoint: FakeEndpoint, guard: Guard, n: int = 6) -> dict[str, Any]:
    return run_tasks(
        endpoint,
        [load_task("doc_type")],
        {"doc_type": _doc_type_cases(n)},
        run_dir=tmp_path,
        row=ROW,
        guard=guard,
        concurrency=2,
        repeat_subset=2,
        repeats=3,
    )


GOOD = ChatResult(
    200, '{"label": "FR_RULE", "evidence_quote": "rule"}', "stop", 10, 5, 12, "{}", None
)


def test_run_writes_raw_normalised_and_a2_receipts_with_repeats(tmp_path: Path) -> None:
    endpoint = FakeEndpoint(GOOD)
    outcome = _run(tmp_path, endpoint, _guard(tmp_path))
    receipts = [json.loads(line) for line in (tmp_path / "receipts.jsonl").read_text().splitlines()]
    assert outcome["stopped"] is None and endpoint.calls == 6 + 2 * 2
    assert {r["repeat_index"] for r in receipts} == {0, 1, 2}
    first = receipts[0]
    for field in ("prompt_sha256", "schema_sha256", "input_artifact_sha256", "raw_output_sha256"):
        assert first[field].startswith("sha256:")
    assert first["status"] == "SUCCESS" and first["exact_revision"] == ROW["exact_revision"]
    assert len(list((tmp_path / "raw" / "doc_type").iterdir())) == 10
    assert len(list((tmp_path / "normalized" / "doc_type").iterdir())) == 10


def test_stop_file_halts_before_the_next_batch(tmp_path: Path) -> None:
    (tmp_path / "STOP").write_text("")
    endpoint = FakeEndpoint(GOOD)
    outcome = _run(tmp_path, endpoint, _guard(tmp_path))
    assert outcome["stopped"] == "STOP file present" and endpoint.calls == 0


def test_operational_failures_trip_the_arena_circuit_breaker(tmp_path: Path) -> None:
    endpoint = FakeEndpoint(
        ChatResult(None, None, None, None, None, 5, "", "transport: ConnectError")
    )
    outcome = _run(tmp_path, endpoint, _guard(tmp_path))
    assert outcome["stopped"].startswith("circuit breaker")
    assert endpoint.calls == 4  # two batches of two, then the identical-signature streak trips


def test_semantic_failures_do_not_stop_the_run(tmp_path: Path) -> None:
    endpoint = FakeEndpoint(ChatResult(200, "not json", "stop", 1, 1, 5, "{}", None))
    outcome = _run(tmp_path, endpoint, _guard(tmp_path))
    assert outcome["stopped"] is None and endpoint.calls == 10


def test_budget_cap_stops_the_run(tmp_path: Path) -> None:
    endpoint = FakeEndpoint(GOOD)
    outcome = _run(tmp_path, endpoint, _guard(tmp_path, budget=60.0, prior=59.99))
    assert outcome["stopped"].startswith("budget") and endpoint.calls == 0
    with pytest.raises(StopRun):
        _guard(tmp_path, budget=60.0, prior=60.0).check()


def test_freeze_detects_changed_bytes_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = tmp_path / "p.txt"
    prompt.write_text("v1")
    monkeypatch.setattr(freeze_module, "NAMESPACE_ROOT", tmp_path)
    monkeypatch.setattr(freeze_module, "FREEZE_DIR", tmp_path / "freeze")
    monkeypatch.setattr(freeze_module, "frozen_paths", lambda: [prompt])
    freeze_module.freeze("t1")
    assert freeze_module.verify_frozen("t1")["files"] == {
        "p.txt": freeze_module.sha256_file(prompt)
    }
    with pytest.raises(freeze_module.FreezeError, match="never overwritten"):
        freeze_module.freeze("t1")
    prompt.write_text("v2")
    with pytest.raises(freeze_module.FreezeError, match="bytes changed"):
        freeze_module.verify_frozen("t1")
    with pytest.raises(freeze_module.FreezeError, match="freeze before measuring"):
        freeze_module.verify_frozen("t2")


def _letter_pdf() -> bytes:
    document = pdfium.PdfDocument.new()
    document.new_page(612, 792)
    import io

    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def test_product_raster_matches_the_cdr_then_ocr_two_pass_sizes() -> None:
    raster = table_track.product_raster(_letter_pdf(), 0)
    assert raster.cdr_dpi == pytest.approx(108.0)
    assert raster.cdr_pixels == (918, 1188)  # 612 x 792 pt at scale 1.5
    assert raster.ocr_pixels == (1224, 1584)  # the OCR worker's own scale 2.0


def test_cdr_budget_lowers_scale_then_refuses() -> None:
    assert table_track.cdr_scale([(612, 792)], 1.5) == 1.5
    huge = [(5000.0, 5000.0)]
    assert table_track.cdr_scale(huge, 1.5) == pytest.approx(30_000_000**0.5 / 5000)
    with pytest.raises(table_track.TableTrackError, match="refuses"):
        table_track.cdr_scale([(8000.0, 8000.0)], 1.5)


def test_numeric_cells_exact_multiset() -> None:
    gold = "<table><tr><td>Revenue</td><td>1,234</td><td>(56)</td></tr></table>"
    assert table_track.numeric_cell_match(gold, gold) == {"gold": 2, "predicted": 2, "matched": 2}
    assert table_track.numeric_cell_match(gold, None)["matched"] == 0
    swapped = gold.replace("(56)", "56")
    assert table_track.numeric_cell_match(gold, swapped)["matched"] == 1
