"""S0 driver (WO-D10-0G): fakes only. No socket, no model, no corpus; the token is fake.

``request`` is a fake pod (readiness, key probe, /metrics, /health); ``call`` is a fake model
that returns what the runners return (results, failure rows, ``RunnerUnavailable``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from benchmark.runners.base import RunnerUnavailable
from benchmark.runners.vlm import PageRefused
from benchmark.screen import s0, select_5h
from benchmark.screen.manifest import HoldoutGuard
from benchmark.v6.contracts import canonical_sha256

MARKER = "fake-token-for-tests-Qx7Zp9"  # not a credential: set only in this test environment
POD = "podabc123"
CREATED = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
REV_CHAT = "1fc9221b7823a371d6e97f92d527cc847e24e107"
SERVED = f"ATH-MaaS/OvisOCR2@{REV_CHAT}"
REV_PAGE = "b" * 40
RECIPE = "c" * 64
IMG = "sha256:" + "e" * 64
PRICE = 0.69
TEXT = "<table><tr><td>Revenue</td><td>1,234</td></tr></table>"
GOLD_TEXT = "GOLD-ONLY-TEXT Revenue 1,234 page 7"


class Clock:
    def __init__(self, at: datetime = CREATED + timedelta(minutes=5)) -> None:
        self.t = at

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


class Pod:
    """The pod as the driver sees it through ``request``."""

    def __init__(self, kind: str = "chat") -> None:
        self.calls: list[tuple[str, str, bool]] = []
        self.state = (404, b"")
        self.models = {False: 401, True: 200}
        self.health: dict[str, Any] = {
            "provider": "mineru",
            "model_revision": REV_PAGE,
            "ready": True,
        }
        self.parse_unauth = 401
        self.running = "0.0"
        self.down = False
        self.body: dict[str, bytes] = {}  # a path answering 200 with these bytes, as-is

    def __call__(
        self, method: str, url: str, body: bytes | None, headers: dict[str, str]
    ) -> tuple[int, str, bytes]:
        path = url.split(".proxy.runpod.net", 1)[1]
        auth = headers.get("Authorization") == f"Bearer {MARKER}"
        self.calls.append((method, path, auth))
        if self.down:
            return 502, "text/html", b""
        if path in self.body and (path != "/v1/models" or auth):
            return 200, "application/octet-stream", self.body[path]
        if path == "/akc-state":
            return self.state[0], "text/plain", self.state[1]
        if path == "/v1/models":
            status = self.models[auth]
            data = json.dumps({"data": [{"id": SERVED}]}).encode() if status == 200 else b""
            return status, "application/json", data
        if path == "/health":
            return 200, "application/json", json.dumps(self.health).encode()
        if path == "/parse":
            return (400 if auth else self.parse_unauth), "application/json", b"{}"
        if path == "/metrics":
            line = f'vllm:num_requests_running{{model_name="m"}} {self.running}\n'
            return 200, "text/plain", line.encode()
        return 404, "text/plain", b""


Behaviour = Callable[[dict[str, Any]], dict[str, Any]]


def ok(kind: str = "chat", text: str = TEXT, latency: float = 1800.0, recipe: str = RECIPE):
    def run(case: dict[str, Any]) -> dict[str, Any]:
        receipt: dict[str, Any] = {"revision_attested": True}
        if kind == "page":
            receipt["recipe"] = {"name": "c0", "sha256": recipe}
        return {
            "schema_version": "1.0",
            "benchmark_case_id": case["benchmark_case_id"],
            "provider": "ovis_ocr2" if kind == "chat" else "mineru",
            "model_revision": REV_CHAT if kind == "chat" else REV_PAGE,
            "text": text,
            "reading_order": [],
            "blocks": [],
            "generated_claims": [],
            "metrics": {"latency_ms": latency, "receipt": receipt},
            "warnings": [],
        }

    return run


def row(reason: str, kind: str = "chat") -> Behaviour:
    def run(case: dict[str, Any]) -> dict[str, Any]:
        receipt: dict[str, Any] = {"revision_attested": False, "raw_response_b64": ""}
        if kind == "page":
            receipt["recipe"] = {"name": "c0", "sha256": RECIPE}
        return {
            "schema_version": "1.0",
            "benchmark_case_id": case["benchmark_case_id"],
            "provider": "ovis_ocr2" if kind == "chat" else "mineru",
            "model_revision": REV_CHAT if kind == "chat" else REV_PAGE,
            "failure": {"reason": reason},
            "receipt": receipt,
        }

    return run


def down(case: dict[str, Any]) -> dict[str, Any]:
    raise RunnerUnavailable("benchmark provider is unavailable")


def refused(case: dict[str, Any]) -> dict[str, Any]:
    raise PageRefused("page_over_pixel_cap")


class Model:
    def __init__(self, plan: dict[str, Behaviour | list[Behaviour]], default: Behaviour) -> None:
        self.plan, self.default = plan, default
        self.calls: list[str] = []
        self.on_call: Callable[[], None] | None = None

    def __call__(self, candidate: Any, case: dict[str, Any], corpus_root: Path) -> dict[str, Any]:
        doc = case["source"]["path"]
        self.calls.append(doc)
        if self.on_call is not None:
            self.on_call()
        b = self.plan.get(doc, self.default)
        if isinstance(b, list):
            b = b[min(self.calls.count(doc), len(b)) - 1]
        return b(case)


def world(
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pages: int = 3,
    origins: list[str] | None = None,
    truth: Callable[[str], dict[str, Any]] | None = None,
) -> Path:
    """Manifest, corpus and gold under ``tmp``; returns ``tmp``."""
    corpus = tmp / "corpus"
    corpus.mkdir()
    docs, gold = [], []
    for i, origin in enumerate(origins or ["born_digital_html_print"] * pages):
        doc_id = f"p{i}.pdf"
        data = f"synthetic page {i}".encode()
        (corpus / doc_id).write_bytes(data)
        docs.append(
            {
                "doc_id": doc_id,
                "source_sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                "byte_size": len(data),
                "page_count": 1,
                "stratum": "en_native",
                "language": "en",
                "document_class": "sec_statement",
                "split": "dev",
                "page_origin": origin,
            }
        )
        t = (truth or _truth)(doc_id)
        gold.append(json.dumps({"page_id": f"{doc_id}#0", "truth": t}))
    body = {"profile": "lpc_sec", "documents": docs}
    manifest = {**body, "manifest_sha256": canonical_sha256(body)}
    (tmp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp / "gold.jsonl").write_text("\n".join(gold) + "\n", encoding="utf-8")
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", MARKER)
    monkeypatch.setattr(s0, "_pypdfium2_version", lambda: s0.PYPDFIUM2_VERSION)
    return tmp


def _truth(doc_id: str) -> dict[str, Any]:
    return {
        "critical_fields": [
            {"field_id": "f1", "kind": "number", "value": "1,234", "anchor": "Revenue"}
        ],
        "text": GOLD_TEXT,
    }


def argv(w: Path, kind: str = "chat", out: str = "out", **over: str) -> list[str]:
    a = {
        "--candidate-id": "C2" if kind == "chat" else "C0",
        "--provider": "ovis_ocr2" if kind == "chat" else "mineru",
        "--revision": REV_CHAT if kind == "chat" else REV_PAGE,
        "--image-digest": IMG,
        "--pod-id": POD,
        "--created-utc": CREATED.isoformat(),
        "--usd-per-hour": str(PRICE),
        "--manifest": str(w / "manifest.json"),
        "--corpus-root": str(w / "corpus"),
        "--gold": str(w / "gold.jsonl"),
        "--out": str(w / out),
    }
    if kind == "page":
        a["--config-sha256"] = "sha256:" + RECIPE
    a.update(over)
    return [x for k, v in a.items() if v != "" for x in (k, v)]


def host(kind: str = "chat") -> str:
    return f"{POD}-{8000 if kind == 'chat' else 8080}.proxy.runpod.net"


def run(
    w: Path,
    monkeypatch: pytest.MonkeyPatch,
    model: Model,
    *,
    kind: str = "chat",
    pod: Pod | None = None,
    clock: Clock | None = None,
    out: str = "out",
    **over: str,
) -> tuple[int, Pod, Clock]:
    monkeypatch.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", host(kind))
    pod = pod or Pod(kind)
    clock = clock or Clock()
    rc = s0.main(
        argv(w, kind, out, **over), request=pod, call=model, now=clock.now, sleep=clock.sleep
    )
    return rc, pod, clock


def final(w: Path, out: str = "out") -> list[dict[str, Any]]:
    lines = (w / out / "final-records.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines]


def raw(w: Path, record: dict[str, Any], out: str = "out") -> dict[str, Any]:
    path = w / out / "raw" / (record["record_key"].removeprefix("sha256:") + ".json")
    return json.loads(path.read_bytes())


# ---------------------------------------------------------------- refused before any page


def _pdfium(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    mp.setattr(s0, "_pypdfium2_version", lambda: "4.31.0")
    return {}


def _reader(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    mp.setattr(s0, "READER_V1_SHA256", "sha256:" + "0" * 64)
    return {}


def _manifest(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    (w / "corpus" / "p1.pdf").write_bytes(b"synthetic page X")
    return {}


def _allowlist(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    mp.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", host() + ",x.example")
    return {}


def _token(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    mp.delenv("AKC_BENCHMARK_PROVIDER_TOKEN")
    return {}


def _gold_dup(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    text = (w / "gold.jsonl").read_text(encoding="utf-8")
    (w / "gold.jsonl").write_text(text + text.splitlines()[0] + "\n", encoding="utf-8")
    return {}


def _pins(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    (w / "out").mkdir()
    pins = {"candidate_id": "C2", "provider": "ovis_ocr2", "revision": "f" * 40}
    (w / "out" / "s0-run.json").write_text(json.dumps(pins), encoding="utf-8")
    return {}


def _chat_config(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    return {"--config-sha256": "sha256:" + RECIPE}


def _price(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    return {"--usd-per-hour": "nan"}


def _pod_id(w: Path, mp: pytest.MonkeyPatch) -> dict[str, str]:
    return {"--pod-id": "pod.evil"}


@pytest.mark.parametrize(
    "spoil",
    [
        _pdfium,
        _reader,
        _manifest,
        _allowlist,
        _token,
        _gold_dup,
        _pins,
        _chat_config,
        _price,
        _pod_id,
    ],
)
def test_each_precheck_refuses_with_exit_2_and_no_request(tmp_path, monkeypatch, spoil):
    w = world(tmp_path, monkeypatch)
    model = Model({}, ok())
    monkeypatch.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", host())
    over = spoil(w, monkeypatch)
    pod, clock = Pod(), Clock()
    rc = s0.main(argv(w, **over), request=pod, call=model, now=clock.now, sleep=clock.sleep)
    assert rc == 2
    assert pod.calls == [] and model.calls == []


def test_page_candidate_without_its_recipe_digest_is_refused(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    model = Model({}, ok("page"))
    rc, pod, _ = run(w, monkeypatch, model, kind="page", **{"--config-sha256": ""})
    assert rc == 2 and pod.calls == [] and model.calls == []


# ---------------------------------------------------------------- readiness


def test_launch_marker_exits_3_and_prints_the_marker_only(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    pod = Pod()
    pod.state = (200, b"FAILED S0-OPERATIONAL-DOWNLOAD\n")
    model = Model({}, ok())
    rc, _, _ = run(w, monkeypatch, model, pod=pod)
    out = capsys.readouterr().out
    assert rc == 3 and model.calls == []
    assert out.strip().endswith("exit 3: FAILED S0-OPERATIONAL-DOWNLOAD")


def test_a_bearer_the_server_refuses_is_key_mismatch(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    pod = Pod()
    pod.models = {False: 401, True: 401}
    model = Model({}, ok())
    rc, _, _ = run(w, monkeypatch, model, pod=pod)
    assert rc == 3 and model.calls == []
    assert "KEY-MISMATCH" in capsys.readouterr().out


def test_not_ready_45_minutes_after_creation_exits_3(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    pod = Pod()
    pod.down = True
    model = Model({}, ok())
    rc, _, clock = run(w, monkeypatch, model, pod=pod)
    assert rc == 3 and model.calls == []
    assert CREATED + timedelta(minutes=45) <= clock.t <= CREATED + timedelta(minutes=46)


def test_a_server_that_answers_without_the_key_is_refused_before_any_page(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    pod = Pod()
    pod.models = {False: 200, True: 200}
    model = Model({}, ok())
    rc, _, _ = run(w, monkeypatch, model, pod=pod)
    assert rc == 2 and model.calls == []


def test_page_server_without_the_key_is_refused_before_any_page(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    pod = Pod("page")
    pod.parse_unauth = 409
    model = Model({}, ok("page"))
    rc, _, _ = run(w, monkeypatch, model, kind="page", pod=pod)
    assert rc == 2 and model.calls == []
    assert ("POST", "/parse", False) in pod.calls


# ---------------------------------------------------------------- pages


@pytest.mark.parametrize("status", ["http_500", "http_502"])
def test_down_status_is_unavailable_retried_once_never_a_third_time(tmp_path, monkeypatch, status):
    w = world(tmp_path, monkeypatch)
    model = Model({"p1.pdf": row(status)}, ok())
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 0
    assert model.calls.count("p1.pdf") == 2
    rec = {r["doc_id"]: r for r in final(w)}["p1.pdf"]
    assert rec["hard_failures"] == ["provider_unavailable"] and rec["raw_sha256"] is None
    rc, _, _ = run(w, monkeypatch, model)  # resume: the retry is spent
    assert rc == 0 and model.calls.count("p1.pdf") == 2
    summary = json.loads((w / "out" / "s0-summary.json").read_text(encoding="utf-8"))
    assert summary["failure_classes"]["operational"] == 1
    assert summary["retries"] == 1


def test_proxy_cut_is_stored_and_waits_for_idle(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    model = Model({"p0.pdf": row("http_524")}, ok())
    rc, pod, _ = run(w, monkeypatch, model)
    assert rc == 0
    rec = final(w)[0]
    assert rec["raw_sha256"] is not None and rec["hard_failures"] == ["contract_failed"]
    assert ("GET", "/metrics", True) in pod.calls
    summary = json.loads((w / "out" / "s0-summary.json").read_text(encoding="utf-8"))
    assert summary["failure_classes"]["time_limit"] == 1


def test_proxy_cut_with_a_busy_server_stops_with_exit_3(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    pod = Pod()
    pod.running = "1.0"
    model = Model({"p0.pdf": row("http_524")}, ok())
    rc, _, _ = run(w, monkeypatch, model, pod=pod)
    assert rc == 3
    assert model.calls == ["p0.pdf"]
    assert not (w / "out" / "final-records.jsonl").exists()


def test_a_400_is_a_stored_model_failure(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    model = Model({"p0.pdf": row("http_400")}, ok())
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 0 and model.calls.count("p0.pdf") == 1
    assert final(w)[0]["raw_sha256"] is not None
    summary = json.loads((w / "out" / "s0-summary.json").read_text(encoding="utf-8"))
    assert summary["failure_classes"]["model"] == 1


def test_page_server_reporting_not_ready_stops_the_run(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    pod = Pod("page")
    model = Model({"p0.pdf": down}, ok("page"))

    def broke() -> None:
        pod.health = {**pod.health, "ready": False}

    model.on_call = broke
    rc, _, _ = run(w, monkeypatch, model, kind="page", pod=pod)
    assert rc == 3 and model.calls == ["p0.pdf"]


def test_recipe_digest_mismatch_on_page_1_is_integrity_after_one_call(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    model = Model({}, ok("page", recipe="d" * 64))
    rc, _, _ = run(w, monkeypatch, model, kind="page", pod=Pod("page"))
    assert rc == 4 and model.calls == ["p0.pdf"]
    assert not (w / "out" / "raw").exists() or not any((w / "out" / "raw").iterdir())


def test_served_model_differs_is_integrity(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    model = Model({"p0.pdf": row("served_model_differs")}, ok())
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 4 and model.calls == ["p0.pdf"]


def test_cost_is_price_times_latency_and_none_on_failure_rows(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    model = Model({"p2.pdf": row("finish_reason_not_stop")}, ok(latency=1800.0))
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 0
    recs = {r["doc_id"]: r for r in final(w)}
    assert recs["p0.pdf"]["provider_cost_usd"] == pytest.approx(PRICE * 1800.0 / 3.6e6)
    assert recs["p2.pdf"]["provider_cost_usd"] is None
    stored = raw(w, recs["p0.pdf"])
    assert stored["metrics"]["cost_basis"] == {
        "kind": s0.COST_KIND,
        "usd_per_hour": PRICE,
        "pod_id": POD,
    }
    # the frozen reader scored the normalised text; the text before is kept
    assert recs["p0.pdf"]["critical"]["exact"] == 1
    assert stored["metrics"]["normaliser"]["text_before"] == TEXT
    assert stored["metrics"]["normaliser"]["residual"] == 0


def test_three_unavailable_in_a_row_exit_3_and_resume_gives_one_record_per_page(
    tmp_path, monkeypatch
):
    w = world(tmp_path, monkeypatch, pages=4)
    model = Model({}, down)
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 3 and model.calls == ["p0.pdf", "p1.pdf", "p2.pdf"]
    model = Model({}, ok())
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 0
    assert sorted(r["page_id"] for r in final(w)) == [f"p{i}.pdf#0" for i in range(4)]
    attempts = (w / "out" / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(attempts) == 2


def dies(pod: Pod) -> Behaviour:
    """The pod goes down while serving this page."""

    def run(case: dict[str, Any]) -> dict[str, Any]:
        pod.down = True
        raise RunnerUnavailable("benchmark provider is unavailable")

    return run


def served_by(pod: Pod, kind: str) -> Behaviour:
    """A page answer while the pod is up; unavailable once it is down."""
    healthy = ok(kind)

    def run(case: dict[str, Any]) -> dict[str, Any]:
        if pod.down:
            raise RunnerUnavailable("benchmark provider is unavailable")
        return healthy(case)

    return run


@pytest.mark.parametrize("kind", ["chat", "page"])
@pytest.mark.parametrize("dies_at", [2, 3, 4])
def test_a_dead_pod_never_spends_a_retry_and_a_resume_completes(
    tmp_path, monkeypatch, kind, dies_at
):
    """The retry is spent in the same invocation only while the pod is healthy; a page that
    failed on a dead pod keeps it for the resume on a new pod, and is never tried a third time."""
    w = world(tmp_path, monkeypatch, pages=5)
    pod = Pod(kind)
    model = Model({f"p{dies_at}.pdf": dies(pod)}, served_by(pod, kind))
    rc, _, _ = run(w, monkeypatch, model, kind=kind, pod=pod)
    assert rc == 3
    assert model.calls == [f"p{i}.pdf" for i in range(5)]  # one attempt each, no retry pass
    assert not (w / "out" / "final-records.jsonl").exists()
    resumed = Model({}, ok(kind))
    rc, _, _ = run(w, monkeypatch, resumed, kind=kind, pod=Pod(kind))
    assert rc == 0
    assert resumed.calls == [f"p{i}.pdf" for i in range(dies_at, 5)]
    assert [r["accepted"] for r in final(w)] == [True] * 5
    transport = (w / "out" / "transport.jsonl").read_text(encoding="utf-8").splitlines()
    tried = [json.loads(x)["case"] for x in transport]
    assert max(tried.count(c) for c in tried) == 2


def test_a_record_without_output_or_failure_is_integrity_not_a_model_failure(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch, pages=1)
    record = {"page_id": "p0.pdf#0", "raw_sha256": None, "hard_failures": [], "accepted": False}
    monkeypatch.setattr(s0, "run_screen", lambda **kw: [record])
    rc, _, _ = run(w, monkeypatch, Model({}, ok()))
    assert rc == 4
    assert not (w / "out" / "final-records.jsonl").exists()


def boom(case: dict[str, Any]) -> dict[str, Any]:
    raise ValueError("the runner raised")


def test_a_runner_exception_is_its_own_class_and_counts_toward_rejection(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    model = Model({"p0.pdf": row("http_500"), "p1.pdf": boom, "p2.pdf": row("http_524")}, ok())
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 0 and model.calls.count("p1.pdf") == 2
    summary = json.loads((w / "out" / "s0-summary.json").read_text(encoding="utf-8"))
    assert summary["failure_classes"] == {
        "operational": 1,
        "time_limit": 1,
        "runner_error": 1,
        "exit_unclassified": 0,
        "page_refused": 0,
        "model": 0,
    }
    assert summary["operational_plus_time_limit_plus_runner_error"] == 3


@pytest.mark.parametrize("value", ["1e", "e", "+-", ".", "1e5e5", "1.2.3"])
def test_a_metrics_value_that_does_not_parse_is_not_idle_and_the_524_row_is_kept(
    tmp_path, monkeypatch, value
):
    w = world(tmp_path, monkeypatch)
    pod = Pod()
    pod.running = value
    model = Model({"p0.pdf": row("http_524")}, ok())
    rc, _, _ = run(w, monkeypatch, model, pod=pod)
    assert rc == 3 and model.calls == ["p0.pdf"]
    lines = (w / "out" / "records.jsonl").read_text(encoding="utf-8").splitlines()
    p0 = [r for r in map(json.loads, lines) if r["doc_id"] == "p0.pdf"]
    assert len(p0) == 1 and p0[0]["raw_sha256"] is not None
    assert p0[0]["provider_error_type"] is None  # the wrapper returned; nothing escaped it


HOSTILE = [
    b"\xff\xfe\x00not utf-8",
    b"[" * 50_000,
    b"null",
    b"[]",
    b'{"data": 5}',
    b'{"data": [{"id": [1]}, {"id": {"a": 1}}]}',
    b'{"ready": "true", "provider": [1], "model_revision": {}}',
]


@pytest.mark.parametrize("body", HOSTILE, ids=range(len(HOSTILE)))
def test_a_hostile_pod_answer_is_a_refusal_or_a_wait_never_a_crash(tmp_path, monkeypatch, body):
    """Whatever the pod answers, the driver refuses (2) or stops (3); an exception never
    leaves it (1), and a page the pod failed stays operational, never a runner error."""
    w = world(tmp_path, monkeypatch)
    pod = Pod()
    pod.body["/v1/models"] = body
    model = Model({}, ok())
    rc, _, _ = run(w, monkeypatch, model, pod=pod, out="models")
    assert rc == 2 and model.calls == []
    pod = Pod("page")
    pod.body["/health"] = body
    model = Model({}, ok("page"))
    rc, _, _ = run(w, monkeypatch, model, kind="page", pod=pod, out="health")
    assert rc in (2, 3) and model.calls == []
    pod = Pod()
    pod.body["/metrics"] = body
    model = Model({"p0.pdf": row("http_524")}, ok())
    rc, _, _ = run(w, monkeypatch, model, pod=pod, out="metrics")
    assert rc == 3 and model.calls == ["p0.pdf"]
    pod = Pod("page")
    model = Model({"p0.pdf": down}, ok("page"))
    model.on_call = lambda: pod.body.__setitem__("/health", body)
    rc, _, _ = run(w, monkeypatch, model, kind="page", pod=pod, out="health-mid")
    lines = (w / "health-mid" / "records.jsonl").read_text(encoding="utf-8").splitlines()
    p0 = [r for r in map(json.loads, lines) if r["doc_id"] == "p0.pdf"]
    # an object that does not name the pinned provider and revision is an integrity stop
    if body.startswith(b"{"):
        assert rc == 4 and model.calls == ["p0.pdf"]
    else:  # no answer: not healthy before the retry pass, the page keeps its retry
        assert rc == 3 and model.calls == ["p0.pdf", "p1.pdf", "p2.pdf"]
    assert p0[0]["hard_failures"] == ["provider_unavailable"]


def test_two_hours_after_creation_the_driver_stops_before_the_next_page(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    clock = Clock()
    model = Model({}, ok())
    model.on_call = lambda: clock.sleep(70 * 60)
    rc, _, _ = run(w, monkeypatch, model, clock=clock)
    assert rc == 3 and model.calls == ["p0.pdf", "p1.pdf"]


def test_page_refusal_is_a_record_not_a_retry(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    model = Model({"p0.pdf": refused}, ok())
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 0 and model.calls.count("p0.pdf") == 1
    summary = json.loads((w / "out" / "s0-summary.json").read_text(encoding="utf-8"))
    assert summary["failure_classes"]["page_refused"] == 1
    assert summary["accepted"] + 1 == summary["pages"]


def test_a_changed_pin_on_resume_is_refused(tmp_path, monkeypatch):
    w = world(tmp_path, monkeypatch)
    rc, _, _ = run(w, monkeypatch, Model({}, ok()))
    assert rc == 0
    rc, _, _ = run(w, monkeypatch, Model({}, ok()), **{"--image-digest": "sha256:" + "a" * 64})
    assert rc == 2


def test_the_token_is_in_no_file_and_no_stream_and_doc_ids_and_text_are_on_no_stream(
    tmp_path, monkeypatch, capsys
):
    """Exactly what this asserts: the fake token is in no file under out/ and on neither
    stdout nor stderr; document ids, page text and gold text are on neither stream.
    records.jsonl and final-records.jsonl carry doc_id by design (the record schema)."""
    w = world(tmp_path, monkeypatch)
    model = Model({"p1.pdf": row("http_400"), "p2.pdf": [down, ok()]}, ok())
    rc, pod, _ = run(w, monkeypatch, model)
    assert rc == 0
    assert ("GET", "/v1/models", True) in pod.calls  # the bearer was sent, as a header
    streams = capsys.readouterr()
    for printed in (streams.out, streams.err):
        for leak in (MARKER, "p0.pdf", "p1.pdf", "p2.pdf", "Revenue", "GOLD-ONLY-TEXT"):
            assert leak not in printed
    assert "S0 C2 page 1/3 ok" in streams.out
    for path in (w / "out").rglob("*"):
        if path.is_file():
            assert MARKER.encode() not in path.read_bytes(), path.name
    for name in ("records.jsonl", "final-records.jsonl"):  # by design, not a leak
        assert b'"doc_id": "p0.pdf"' in (w / "out" / name).read_bytes()


def test_a_crash_is_exit_1_with_the_type_only(tmp_path, monkeypatch, capsys):
    w = world(tmp_path, monkeypatch)
    lines = (w / "gold.jsonl").read_text(encoding="utf-8").splitlines()
    (w / "gold.jsonl").write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    rc, _, _ = run(w, monkeypatch, Model({}, ok()))
    out = capsys.readouterr().out
    assert rc == 1 and "crash ContractError" in out and "p0.pdf" not in out


def summary_of(w: Path, out: str = "out") -> dict[str, Any]:
    return json.loads((w / out / "s0-summary.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- round 3


def test_an_answer_over_the_size_bound_is_a_stored_failure_never_normalised(tmp_path, monkeypatch):
    """B: one pod answer must not hold the run. A text of MAX_TEXT_CHARS is normalised; one
    character more is the failure output_too_large (page_refused), its length kept, no retry."""
    assert s0.MAX_TEXT_CHARS == 2_000_000
    w = world(tmp_path, monkeypatch)
    at_bound = "Revenue 1,234 " + "x" * (s0.MAX_TEXT_CHARS - 14)
    model = Model({"p0.pdf": ok(text=at_bound + "y"), "p1.pdf": ok(text=at_bound)}, ok())
    seen: list[int] = []
    real = s0.normalise

    def spy(provider: str, text: str) -> tuple[str, int]:
        seen.append(len(text))
        return real(provider, text)

    monkeypatch.setattr(s0, "normalise", spy)
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 0
    assert seen == [s0.MAX_TEXT_CHARS, len(TEXT)]  # p1 and p2 only: p0 never reached it
    recs = {r["doc_id"]: r for r in final(w)}
    big = raw(w, recs["p0.pdf"])
    assert big["failure"] == {"reason": "output_too_large"}
    assert big["metrics"] == {"text_chars": s0.MAX_TEXT_CHARS + 1} and "text" not in big
    assert not recs["p0.pdf"]["accepted"] and recs["p0.pdf"]["provider_cost_usd"] is None
    assert recs["p1.pdf"]["accepted"]
    summary = summary_of(w)
    assert summary["failure_classes"]["page_refused"] == 1
    assert summary["failure_reasons"] == {"output_too_large": 1}
    rc, _, _ = run(w, monkeypatch, model)  # resume: a stored failure is never retried
    assert rc == 0 and model.calls.count("p0.pdf") == 1


def test_a_page_that_returns_past_the_deadline_stops_the_run(tmp_path, monkeypatch):
    """B: the run deadline is checked when a page returns, not only before the call: the last
    page coming back past two hours stops the run (exit 3) with its answer stored."""
    w = world(tmp_path, monkeypatch, pages=1)
    clock = Clock()
    model = Model({}, ok())
    model.on_call = lambda: clock.sleep(2 * 60 * 60)
    rc, _, _ = run(w, monkeypatch, model, clock=clock)
    assert rc == 3 and model.calls == ["p0.pdf"]
    assert not (w / "out" / "final-records.jsonl").exists()
    lines = (w / "out" / "records.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["accepted"] for x in lines] == [True]
    model.on_call = None
    rc, _, _ = run(w, monkeypatch, model)  # a resume on a new pod: nothing left to call
    assert rc == 0 and model.calls == ["p0.pdf"]


def _other_model(pod: Pod) -> None:
    pod.body["/v1/models"] = json.dumps(
        {"data": [{"id": f"ATH-MaaS/OvisOCR2@{'f' * 40}"}]}
    ).encode()


def _other_revision(pod: Pod) -> None:
    pod.health = {**pod.health, "model_revision": "f" * 40}


def _other_provider(pod: Pod) -> None:
    pod.health = {**pod.health, "provider": "ovis_ocr3"}


def _no_provider(pod: Pod) -> None:
    pod.health = {"ready": True, "model_revision": REV_PAGE}


@pytest.mark.parametrize(
    ("kind", "change"),
    [
        ("chat", _other_model),
        ("page", _other_revision),
        ("page", _other_provider),
        ("page", _no_provider),
    ],
)
def test_a_health_answer_naming_other_pins_before_the_retry_is_integrity(
    tmp_path, monkeypatch, kind, change
):
    """C(i): the pod answers the health check before the retry pass, but names another served
    model, provider or revision (or none): integrity (exit 4), not operational; no retry."""
    w = world(tmp_path, monkeypatch)
    pod = Pod(kind)
    fail = row("http_502") if kind == "chat" else down
    model = Model({"p1.pdf": fail}, ok(kind))

    def after_last() -> None:
        if len(model.calls) == 3:
            change(pod)

    model.on_call = after_last
    rc, _, _ = run(w, monkeypatch, model, kind=kind, pod=pod)
    assert rc == 4
    assert model.calls == ["p0.pdf", "p1.pdf", "p2.pdf"]  # the retry was not spent


@pytest.mark.parametrize("kind", ["chat", "page"])
@pytest.mark.parametrize("value", [[], ["text"], "text", None, 7, 1.5, True])
def test_a_runner_result_that_is_not_an_object_is_a_runner_error_row(
    tmp_path, monkeypatch, kind, value
):
    """C(ii): inside the driver, a non-object result becomes the failure row
    runner_result_unshaped (class runner_error); run_screen and the summary never see it."""
    w = world(tmp_path, monkeypatch)
    model = Model({"p0.pdf": lambda case: value}, ok(kind))
    rc, _, _ = run(w, monkeypatch, model, kind=kind, pod=Pod(kind))
    assert rc == 0 and model.calls.count("p0.pdf") == 1
    recs = {r["doc_id"]: r for r in final(w)}
    stored = raw(w, recs["p0.pdf"])
    assert stored["failure"] == {"reason": "runner_result_unshaped"}
    assert stored["metrics"] == {"result_type": type(value).__name__}
    summary = summary_of(w)
    assert summary["failure_classes"]["runner_error"] == 1
    assert summary["operational_plus_time_limit_plus_runner_error"] == 1
    assert summary["accepted"] == 2


def test_the_summary_counts_pages_with_a_dash_cell_before_a_number(tmp_path, monkeypatch):
    """D: a dash-only cell is not joined to its number; the summary shows how often it
    happens, read from the normalised text only."""
    w = world(tmp_path, monkeypatch)
    dash = "<table><tr><td>Revenue</td><td>-</td><td>1,234</td></tr></table>"
    model = Model({"p0.pdf": ok(text=dash), "p2.pdf": ok(text=dash)}, ok())
    rc, _, _ = run(w, monkeypatch, model)
    assert rc == 0
    assert summary_of(w)["normaliser"]["dash_cell_before_number_pages"] == 2
    recs = {r["doc_id"]: r for r in final(w)}
    assert "- | 1,234" in raw(w, recs["p0.pdf"])["text"]  # never joined into -1,234


def test_failure_classes() -> None:
    assert s0.failure_class("output_too_large") == "page_refused"
    assert s0.failure_class("runner_result_unshaped") == "runner_error"
    assert s0.failure_class("provider_unavailable") == "operational"
    assert s0.failure_class("page_timeout") == "time_limit"
    assert s0.failure_class("http_524") == "time_limit"
    assert s0.failure_class("pipeline_exit_nonzero") == "exit_unclassified"
    assert s0.failure_class("page_over_pixel_cap") == "page_refused"
    assert s0.failure_class("finish_reason_not_stop") == "model"
    assert s0.failure_class("provider_error") == "runner_error"


# ---------------------------------------------------------------- select_5h compatibility


def _sec_truth(doc_id: str) -> dict[str, Any]:
    """Shaped like ``sec_screen._truth``: high_risk and the whole page text."""
    return {
        "critical_fields": [
            {"field_id": "f1", "kind": "number", "value": "1,234", "anchor": "Revenue"},
            {"field_id": "f2", "kind": "number", "value": "500", "anchor": "Net income"},
        ],
        "high_risk": True,
        "text": "Revenue 1,234 Net income 500 Form 10-Q page 7",
        "text_source": "html_dom_text",
        "gold_source": "sec_fsds_inline_xbrl",
    }


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="needs lead decision 5H-10 (L1): select_5h counts score flags "
    "(high_risk_numeric_below_threshold) as failed pages; fixed in the selection lane, WO-D08-9",
)
def test_select_s1_on_s0_records_yields_a_non_degenerate_leader(tmp_path, monkeypatch):
    origins = [select_5h.DEGRADED] * 3 + ["born_digital_html_print"] * 3
    w = world(tmp_path, monkeypatch, origins=origins, truth=_sec_truth)
    page_text = "<table><tr><td>Revenue</td><td>1,234</td></tr><tr><td>Net income</td><td>500</td>"
    rc, _, _ = run(w, monkeypatch, Model({}, ok(text=page_text + "</tr></table>")), out="c2")
    assert rc == 0
    worse = "| Revenue | 1,234 |\n| Net income | 50 |"
    model = Model({}, ok("page", text=worse))
    rc, _, _ = run(w, monkeypatch, model, kind="page", pod=Pod("page"), out="c0")
    assert rc == 0
    records = final(w, "c2") + final(w, "c0")
    manifest = json.loads((w / "manifest.json").read_text(encoding="utf-8"))
    s1 = select_5h.select_s1(
        records, guard=HoldoutGuard(manifest, w / "access.jsonl"), baseline="C0"
    )
    assert s1["leader"] == "C2"
    assert s1["cells"]["H"]["C2"]["critical_exact_rate"] > 0
