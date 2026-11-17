"""Hosted arm (WO-D10-0D): the door, the spend stop, resume. Fakes and in-process markers only:
no key, no provider call, no network."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from benchmark.runners import gemini_api, vlm
from benchmark.runners.base import RunnerUnavailable
from benchmark.screen import hosted
from benchmark.v6.contracts import ContractError, canonical_sha256

MODEL = "gemini-4-hydrogen"
MISTRAL_MODEL = "mistral-ocr-4-1"
ENV = {"module_origins": {}, "renderer_version": "4.30.0"}
SNAPSHOT = b"<html>Batch $0.75 ... $3.75 ... OCR 4.1 Input $4 /1000 Pages</html>"
GOOD_USAGE = {"promptTokenCount": 1200, "candidatesTokenCount": 300, "thoughtsTokenCount": 100}


def _marker(prefix: str = "AIza") -> str:
    return prefix + secrets.token_urlsafe(30)  # made in this process, never a real key


def _spec(
    tmp_path: Path, *, thinking: dict[str, Any] | None = None, limits: dict[str, Any] | None = None
) -> hosted.HostedSpec:
    raw = yaml.safe_load(hosted.SPEC_PATH.read_text(encoding="utf-8"))
    snap = tmp_path / "snap"
    snap.mkdir(exist_ok=True)
    sha = hashlib.sha256(SNAPSHOT).hexdigest()
    (snap / f"{sha}.html").write_bytes(SNAPSHOT)
    for block in raw["hosted"].values():
        for price in block["prices"].values():
            price.update(snapshot_file=f"{sha}.html", snapshot_sha256=sha)
    if thinking is not None:
        raw["hosted"]["gemini_api"]["options"]["thinking_config"] = thinking
    raw["hosted"]["gemini_api"]["limits"].update(limits or {})
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return hosted.load_hosted_spec(path)


def _doc(
    n: int,
    *,
    stratum: str = "s",
    language: str = "en",
    split: Any = "dev",
    rights: Any = "public_record",
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "doc_id": f"d{n}.png",
        "page_count": 1,
        "stratum": stratum,
        "language": language,
        "document_class": "c",
        "split": split,
        "rights": {
            "source_url": "https://example.org",
            "licence_id": "x",
            "licence_snapshot_sha256": None,
            "rights_class": rights,
            "redistribution": False,
            "retrieved_at": "2026-11-17",
        },
    }
    if split is None:
        del doc["split"]
    if rights is None:
        del doc["rights"]
    return doc


def _corpus(tmp_path: Path, docs: list[dict[str, Any]]) -> tuple[Path, Path]:
    root = tmp_path / "corpus"
    root.mkdir(exist_ok=True)
    for doc in docs:
        data = b"\x89PNG fake " + doc["doc_id"].encode()
        (root / doc["doc_id"]).write_bytes(data)
        doc.update(source_sha256="sha256:" + hashlib.sha256(data).hexdigest(), byte_size=len(data))
    body = {"documents": docs}
    manifest = {**body, "manifest_sha256": canonical_sha256(body)}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, root


def _pages(docs: list[dict[str, Any]]) -> list[hosted.Page]:
    return [hosted.Page(f"{d['doc_id']}#0", d, 0) for d in docs]


class FakeGemini:
    """The Gemini batch REST surface, in memory. ``tweak`` edits the inline responses."""

    def __init__(
        self, *, page_size: int = 100, tweak: Any = None, state: str = "BATCH_STATE_SUCCEEDED"
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.batches: dict[str, dict[str, Any]] = {}
        self.page_size, self.tweak, self.state = page_size, tweak, state
        self.fail_create: str | None = None  # "before" or "after": the connection drops

    def creates(self) -> int:
        return sum(1 for m, p, _ in self.calls if m == "POST")

    def add(self, display: str, keys: list[str]) -> str:
        name = f"batches/b{len(self.batches) + 1}"
        self.batches[name] = {"display": display, "keys": keys, "deleted": False}
        return name

    def op(self, name: str) -> dict[str, Any]:
        batch = self.batches[name]
        entries = [
            {
                "metadata": {"key": k},
                "response": {
                    "modelVersion": MODEL,
                    "candidates": [
                        {"finishReason": "STOP", "content": {"parts": [{"text": "page"}]}}
                    ],
                    "usageMetadata": dict(GOOD_USAGE),
                },
            }
            for k in batch["keys"]
        ]
        if self.tweak:
            entries = self.tweak(entries)
        return {
            "name": name,
            "metadata": {
                "model": f"models/{MODEL}",
                "displayName": batch["display"],
                "state": self.state,
            },
            "done": True,
            "response": {"inlinedResponses": {"inlinedResponses": entries}},
        }

    def __call__(
        self,
        config: Any,
        method: str,
        body: Any,
        headers: dict[str, str],
        *,
        query: Any = None,
        max_response_bytes: int = 0,
    ) -> tuple[int, str, bytes]:
        assert headers["x-goog-api-key"]
        path = config.endpoint.split("/v1beta", 1)[1]
        self.calls.append((method, path, dict(query or {})))
        if method == "POST":
            if self.fail_create == "before":
                raise RunnerUnavailable("benchmark provider is unavailable")
            batch = json.loads(body)["batch"]
            keys = [r["metadata"]["key"] for r in batch["inputConfig"]["requests"]["requests"]]
            name = self.add(batch["displayName"], keys)
            if self.fail_create == "after":
                raise RunnerUnavailable("benchmark provider is unavailable")
            return 200, "application/json", json.dumps({"name": name}).encode()
        if method == "GET" and path == "/batches":
            live = [n for n, b in self.batches.items() if not b["deleted"]]
            start = int((query or {}).get("pageToken", "0"))
            ops = [self.op(n) for n in live[start : start + self.page_size]]
            page: dict[str, Any] = {"operations": ops}
            if start + self.page_size < len(live):
                page["nextPageToken"] = str(start + self.page_size)
            return 200, "application/json", json.dumps(page).encode()
        name = path.lstrip("/")
        if name not in self.batches or self.batches[name]["deleted"]:
            return 404, "application/json", b"{}"
        if method == "DELETE":
            self.batches[name]["deleted"] = True
            return 200, "application/json", b"{}"
        return 200, "application/json", json.dumps(self.op(name)).encode()


def _mistral_ok(
    config: Any, body: bytes, headers: dict[str, str], **_: Any
) -> tuple[int, str, bytes]:
    doc = {
        "model": MISTRAL_MODEL,
        "pages": [{"index": 0, "markdown": "x"}],
        "usage_info": {"pages_processed": 1},
    }
    return 200, "application/json", json.dumps(doc).encode()


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    markers = {"GEMINI_API_KEY": _marker(), "MISTRAL_API_KEY": _marker("mk")}
    for name, value in markers.items():
        monkeypatch.setenv(name, value)
    return markers


def _prepaid(spec: hosted.HostedSpec, out: Path, draw: str = "12.15") -> None:
    hosted.record_prepaid(spec, out, "13.50", draw, "test fixture")


def _arm_with_chunk(
    tmp_path: Path, spec: hosted.HostedSpec, docs: list[dict[str, Any]], *, draw: str = "12.15"
) -> tuple[hosted.Arm, list[hosted.Chunk], dict[str, hosted.Page], Path]:
    _, corpus = _corpus(tmp_path, docs)
    out = tmp_path / "out"
    _prepaid(spec, out, draw)
    arm = hosted.Arm(spec, out, hosted.GeminiBatches())
    arm.campaign.reserve_stage("dry", 0)
    pages = _pages(docs)
    plan = hosted.build_plan(spec, pages, corpus)
    return arm, plan.chunks, {p.page_id: p for p in pages}, corpus


# --- 16-19, 25: collection ------------------------------------------------------------------


def _drop(entries: list[Any]) -> list[Any]:
    return entries[:-1]


def _duplicate(entries: list[Any]) -> list[Any]:
    entries[1]["metadata"]["key"] = entries[0]["metadata"]["key"]
    return entries


def _unknown(entries: list[Any]) -> list[Any]:
    entries[1]["metadata"]["key"] = "page-not-sent"
    return entries


@pytest.mark.parametrize("tweak", [_drop, _duplicate, _unknown])
def test_16_a_missing_duplicated_or_unknown_key_fails_the_chunk_and_writes_no_page(
    tweak: Any, tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    fake = FakeGemini(tweak=tweak)
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1), _doc(2)])
    hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)
    hosted.poll(arm, "dry", max_wait=0, interval=0, sleep=lambda _: None)
    assert arm.events("hosted.batch.mapping_failed.v1")
    assert arm.campaign.stopped
    assert not (arm.out / "collected").exists()


def test_17_a_served_model_difference_marks_the_page_and_stops_the_next_submit(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path, limits={"max_requests_per_batch": 1})

    def other_model(entries: list[Any]) -> list[Any]:
        entries[0]["response"]["modelVersion"] = "gemini-4-hydrogen-002"
        return entries

    fake = FakeGemini(tweak=other_model)
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1), _doc(2)])
    hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)
    hosted.poll(arm, "dry", max_wait=0, interval=0, sleep=lambda _: None)
    case = pages[chunks[0].pages[0]["page_id"]].case_id
    stored = json.loads((arm.out / "collected" / "gemini_api" / f"{case}.json").read_text())
    assert stored["failure"]["reason"] == "served_model_differs"
    with pytest.raises(ContractError, match="stopped"):
        hosted.submit_chunk(hosted.Arm(spec, arm.out), "dry", chunks[1], pages, corpus)
    assert fake.creates() == 1


def test_18_an_entry_error_is_a_failure_row_with_its_bytes(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)

    def error(entries: list[Any]) -> list[Any]:
        entries[0] = {
            "metadata": entries[0]["metadata"],
            "error": {"code": 13, "message": "internal"},
        }
        return entries

    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini(tweak=error))
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1)])
    hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)
    hosted.poll(arm, "dry", max_wait=0, interval=0, sleep=lambda _: None)
    case = pages["d1.png#0"].case_id
    stored = json.loads((arm.out / "collected" / "gemini_api" / f"{case}.json").read_text())
    assert stored["failure"]["reason"] == "batch_entry_error"
    kept = json.loads(base64.b64decode(stored["receipt"]["raw_response_b64"]))
    assert kept["error"] == {"code": 13, "message": "internal"}


def test_19_the_batch_raw_is_written_before_anything_parses_it(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini())
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1)])
    hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)

    def explode(_: Any) -> Any:
        raise ValueError("parser broke")

    monkeypatch.setattr(hosted, "_loads", explode)
    with pytest.raises(ValueError):
        hosted.poll(arm, "dry", max_wait=0, interval=0, sleep=lambda _: None)
    written = list((arm.out / "dry" / "raw" / "batches").rglob("*.json"))
    assert written and json.loads(written[0].read_bytes())["name"] == "batches/b1"


def test_25_an_entry_without_usage_is_charged_its_worst_case_and_flagged(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)

    def no_usage(entries: list[Any]) -> list[Any]:
        del entries[0]["response"]["usageMetadata"]
        return entries

    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini(tweak=no_usage))
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1)])
    hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)
    hosted.poll(arm, "dry", max_wait=0, interval=0, sleep=lambda _: None)
    accepted = arm.events("job.accepted.v1")[0]
    assert accepted["flagged_no_usage"] == ["d1.png#0"]
    assert Decimal(accepted["actual_usd"]) == hosted.page_worst_usd(spec, "gemini_api")


# --- 20: the door ---------------------------------------------------------------------------

_REFUSED = [
    _doc(1, split="holdout"),
    _doc(2, rights="owned"),
    _doc(3, rights="public_domain"),
    _doc(4, split=None),
    _doc(5, rights=None),
]


@pytest.mark.parametrize(
    "doc", _REFUSED, ids=["holdout", "owned", "public_domain", "no_split", "no_rights"]
)
def test_20_the_door_refuses_before_any_request_is_built(
    doc: dict[str, Any], tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    fake = FakeGemini()
    mistral_calls: list[Any] = []
    built: list[Any] = []
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", lambda *a, **k: mistral_calls.append(a))
    monkeypatch.setattr(hosted, "_render", lambda *a: built.append(a))
    monkeypatch.setattr(hosted, "build_provider_payload", lambda *a, **k: built.append(a))
    out = tmp_path / "out"
    _prepaid(spec, out)
    arm = hosted.Arm(spec, out, hosted.GeminiBatches())
    arm.campaign.reserve_stage("dry", 0)
    page = hosted.Page(f"{doc['doc_id']}#0", doc, 0)
    info = {"page_id": page.page_id, "case_id": "page-x", "image_sha256": "sha256:" + "0" * 64}
    chunk = hosted.Chunk(hosted.chunk_key(spec, [(page.page_id, info["image_sha256"])]), (info,))
    with pytest.raises(hosted.HostedPageRefused):
        hosted.submit_chunk(arm, "dry", chunk, {page.page_id: page}, tmp_path)
    with pytest.raises(hosted.HostedPageRefused):
        hosted.call_mistral(arm, "dry", page, tmp_path)
    assert fake.calls == [] and mistral_calls == [] and built == []
    pages, refused = hosted.page_list([doc])
    assert pages == [] and refused[0]["doc_id"] == doc["doc_id"]


def test_20_admitted_rights_classes_are_exactly_the_hosted_list() -> None:
    assert {"public_record", "permissive_licence", "synthetic"} == hosted.HOSTED_RIGHTS
    for rights in ("public_record", "permissive_licence", "synthetic"):
        hosted.admit(_doc(1, rights=rights))


# --- 21-24: money -----------------------------------------------------------------------------


def test_21_the_worst_case_is_the_formula_in_decimal(tmp_path: Path) -> None:
    budget = _spec(tmp_path, thinking={"thinkingBudget": 1024})
    # 2500 x 0.75 + (8192 + 1024) x 3.75, per 1M tokens
    assert hosted.page_worst_usd(budget, "gemini_api") == Decimal("0.036435")
    level = _spec(tmp_path, thinking={"thinkingLevel": "LOW"})
    # a level has no numeric bound: costed at MAX_THINKING_BUDGET (32768)
    assert hosted.page_worst_usd(level, "gemini_api") == Decimal("0.155475")
    assert hosted.page_worst_usd(level, "mistral_ocr_4") == Decimal("0.004")


def test_22_a_chunk_over_the_credit_left_is_refused_before_any_write(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1)], draw="0.10")
    with pytest.raises(ContractError):
        hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)
    assert fake.creates() == 0 and not arm.events("job.dispatch.intent.v1")


def test_22_a_mistral_stage_above_its_cap_is_refused_before_any_create(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(hosted, "MISTRAL_ATTEMPTS_RESERVED", 10**6)
    with pytest.raises(ContractError):
        _paid(spec, out, tmp_path, "rehearsal")
    assert fake.creates() == 0


def test_23_a_fresh_process_rebuilds_the_credit_from_the_ledger(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path, limits={"max_requests_per_batch": 1})
    worst = hosted.page_worst_usd(spec, "gemini_api")
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    arm, chunks, pages, corpus = _arm_with_chunk(
        tmp_path, spec, [_doc(1), _doc(2)], draw=str(worst + Decimal("0.001"))
    )
    hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)
    hosted.poll(arm, "dry", max_wait=0, interval=0, sleep=lambda _: None)  # settles X
    fresh = hosted.Arm(spec, arm.out, hosted.GeminiBatches())
    with pytest.raises(ContractError):
        hosted.submit_chunk(fresh, "dry", chunks[1], pages, corpus)
    assert fake.creates() == 1


@pytest.mark.parametrize("damage", ["missing", "sha", "price"])
def test_24_dry_refuses_a_missing_changed_or_priceless_snapshot(
    damage: str, tmp_path: Path
) -> None:
    spec = _spec(tmp_path)
    snap = tmp_path / "snap"
    file = next(snap.iterdir())
    if damage == "missing":
        file.unlink()
    elif damage == "sha":
        file.write_bytes(SNAPSHOT + b" ")
    else:  # same sha recorded, price text gone
        file.write_bytes(SNAPSHOT.replace(b"$0.75", b"$0.70"))
        sha = hashlib.sha256(file.read_bytes()).hexdigest()
        file.rename(snap / f"{sha}.html")
        raw = yaml.safe_load(spec.path.read_text())
        for block in raw["hosted"].values():
            for price in block["prices"].values():
                price.update(snapshot_file=f"{sha}.html", snapshot_sha256=sha)
        spec.path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        spec = hosted.load_hosted_spec(spec.path)
    with pytest.raises(ContractError, match="snapshot"):
        hosted.check_snapshots(spec, snap)


def test_24_the_repository_spec_pins_prices_that_occur_in_the_kept_snapshots() -> None:
    spec = hosted.load_hosted_spec()
    kept = Path("D:/CodexProjects/v34-lanes/receipts/WO-D10-0D/doc-snapshots")
    if not kept.is_dir():
        pytest.skip("the snapshot directory lives outside the repository")
    assert len(hosted.check_snapshots(spec, kept)) == 3


# --- 26-28: resume and the key --------------------------------------------------------------


def test_26_after_a_crash_past_dispatch_the_rerun_polls_and_never_creates(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1)])
    hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)
    fresh = hosted.Arm(spec, arm.out, hosted.GeminiBatches())  # the process died here
    hosted.submit_chunk(fresh, "dry", chunks[0], pages, corpus)
    assert hosted.poll(fresh, "dry", max_wait=0, interval=0, sleep=lambda _: None) == 0
    assert fake.creates() == 1 and fresh.events("job.accepted.v1")


@pytest.mark.parametrize("where", ["after", "before"])
def test_27_an_intent_without_dispatch_is_adopted_from_the_listing_or_created_once(
    where: str, tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    fake = FakeGemini(page_size=1)
    fake.add("someone-else", [])  # our batch, if any, lands on page 2 of the listing
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1)])
    fake.fail_create = where
    with pytest.raises(RunnerUnavailable):
        hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)
    assert arm.events("job.dispatch.intent.v1") and not arm.events("job.dispatched.v1")
    fake.fail_create = None
    before = fake.creates()
    fresh = hosted.Arm(spec, arm.out, hosted.GeminiBatches())
    hosted.submit_chunk(fresh, "dry", chunks[0], pages, corpus)
    dispatched = fresh.events("job.dispatched.v1")
    assert len(dispatched) == 1
    if where == "after":
        assert fake.creates() == before and dispatched[0]["adopted"] is True
        assert not fresh.events("hosted.resubmit_after_absent.v1")
    else:
        assert fake.creates() == before + 1
        assert fresh.events("hosted.resubmit_after_absent.v1")


def test_28_the_idempotency_key_is_stable_and_moves_with_every_pin(tmp_path: Path) -> None:
    spec = _spec(tmp_path, thinking={"thinkingBudget": 1024})
    pages = [("b.pdf#0", "sha256:" + "1" * 64), ("a.pdf#0", "sha256:" + "2" * 64)]
    key = hosted.chunk_key(spec, pages)
    assert key == hosted.chunk_key(spec, list(reversed(pages)))
    code = (
        "import sys;from pathlib import Path;from benchmark.screen import hosted as h;"
        f"s=h.load_hosted_spec(Path({str(spec.path)!r}));"
        f"print(h.chunk_key(s,{pages!r}))"
    )
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        got = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        assert got.stdout.strip() == key, got.stderr
    from dataclasses import replace

    changed = [
        replace(spec, gemini={**spec.gemini, "model": "gemini-4-argon"}),
        replace(spec, gemini_config={**spec.gemini_config, "prompt": "other prompt"}),
        replace(
            spec,
            gemini_config={
                **spec.gemini_config,
                "generation": {
                    **spec.gemini_config["generation"],
                    "mediaResolution": "MEDIA_RESOLUTION_LOW",
                },
            },
        ),
        replace(spec, gemini={**spec.gemini, "api_version": "v1"}),
    ]
    for other in changed:
        assert hosted.chunk_key(other, pages) != key
    assert hosted.chunk_key(spec, [pages[0], ("a.pdf#0", "sha256:" + "3" * 64)]) != key


# --- 29-32: stages, receipts and the scan ---------------------------------------------------


def _docs3() -> list[dict[str, Any]]:
    return [
        _doc(1, stratum="a"),
        _doc(2, stratum="b", rights="synthetic"),
        _doc(3, stratum="c", language="ko", rights="permissive_licence"),
        _doc(4, stratum="a"),
        _doc(5, stratum="d", split="holdout"),
    ]


def _through_dry(tmp_path: Path, spec: hosted.HostedSpec, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    manifest, corpus = _corpus(tmp_path, _docs3())
    out = tmp_path / "out"
    _prepaid(spec, out)
    hosted.run_dry(spec, out, manifest, corpus, tmp_path / "snap", environment=lambda: ENV)
    monkeypatch.setenv("GEMINI_API_KEY", _marker())
    monkeypatch.setenv("MISTRAL_API_KEY", _marker("mk"))
    return out


def _paid(spec: hosted.HostedSpec, out: Path, tmp_path: Path, stage: str) -> int:
    return hosted.run_paid(
        spec,
        out,
        stage,
        tmp_path / "manifest.json",
        tmp_path / "corpus",
        tmp_path / "snap",
        environment=lambda: ENV,
        max_wait=0,
        interval=0,
        sleep=lambda _: None,
    )


def test_29_each_stage_needs_its_predecessor_receipt_under_this_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    _corpus(tmp_path, _docs3())
    out = tmp_path / "out"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(ContractError, match="prepaid"):  # dry without the prepaid receipt
        hosted.run_dry(
            spec,
            out,
            tmp_path / "manifest.json",
            tmp_path / "corpus",
            tmp_path / "snap",
            environment=lambda: ENV,
        )
    _prepaid(spec, out)
    with pytest.raises(ContractError, match="dry"):
        _paid(spec, out, tmp_path, "rehearsal")
    second = tmp_path / "second"
    second.mkdir()
    spec = _spec(second)
    out = _through_dry(second, spec, monkeypatch)
    with pytest.raises(ContractError, match="rehearsal"):
        _paid(spec, out, second, "full")
    receipt = out / "dry" / "receipt.json"
    original = receipt.read_bytes()
    receipt.write_text(json.dumps({**json.loads(original), "spec_sha256": "sha256:" + "0" * 64}))
    with pytest.raises(ContractError, match="another spec"):
        _paid(spec, out, second, "rehearsal")
    narrowed = json.loads(original)
    narrowed["pages"] = narrowed["pages"][:1]
    narrowed["mistral_pages"] = narrowed["mistral_pages"][:1]
    receipt.write_text(json.dumps(narrowed))
    with pytest.raises(ContractError, match="subset"):
        _paid(spec, out, second, "rehearsal")


def test_30_dry_needs_no_network_and_no_key_and_a_paid_stage_refuses_its_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)

    def no_network(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("dry touched the network")

    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.delenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", raising=False)
    out = _through_dry(tmp_path, spec, monkeypatch)
    receipt = json.loads((out / "dry" / "receipt.json").read_bytes())
    assert receipt["dry_run"] is True and receipt["fake_records"]["count"] == 8  # 4 dev pages x 2
    monkeypatch.setenv("MISTRAL_API_KEY", _marker("mk"))
    with pytest.raises(ContractError, match="no key"):
        hosted.run_dry(
            spec,
            tmp_path / "o2",
            tmp_path / "manifest.json",
            tmp_path / "corpus",
            tmp_path / "snap",
            environment=lambda: ENV,
        )
    monkeypatch.setattr(vlm, "post_bytes", hosted.DryTransport())
    with pytest.raises(ContractError, match="fake transport"):
        _paid(spec, out, tmp_path, "rehearsal")


def _rehearse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[hosted.HostedSpec, Path, FakeGemini]:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    assert _paid(spec, out, tmp_path, "rehearsal") == 0
    return spec, out, fake


def test_31_dry_and_paid_receipts_share_one_key_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, out, fake = _rehearse(tmp_path, monkeypatch)
    dry = json.loads((out / "dry" / "receipt.json").read_bytes())
    paid = json.loads((out / "rehearsal" / "receipt.json").read_bytes())
    assert set(dry) == set(paid) == set(hosted.RECEIPT_KEYS)
    assert dry["dry_run"] is True and paid["dry_run"] is False
    assert set(dry["estimate"]) == {"gemini_api", "mistral_ocr_4"}
    assert Decimal(dry["estimate"]["gemini_api"]["worst_usd"]) > 0
    # one batch of three pages, three Mistral calls, the batch deleted and confirmed gone
    assert fake.creates() == 1 and len(paid["jobs"]) == 1
    assert len(paid["results"]["mistral"]) == 3
    assert paid["teardown"]["done"] is True and paid["teardown"]["confirmed_404"] == ["b1"]


def test_32_every_receipt_carries_the_flags_and_the_scan_finds_a_planted_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, out, _ = _rehearse(tmp_path, monkeypatch)
    for stage in ("prepaid", "dry", "rehearsal"):
        receipt = json.loads((out / stage / "receipt.json").read_bytes())
        assert receipt["publication"] == {
            "mistral_ocr_4": {"publishable": False, "reason": "mistral_tos_6_1_b"},
            "gemini_api": {"publishable": False, "reason": "§9 claims rule"},
        }
        assert receipt["gold_eligible"] is False and receipt["training_eligible"] is False
    assert (
        json.loads((out / "rehearsal" / "receipt.json").read_bytes())["credential_scan"]["hits"]
        == []
    )
    arm = hosted.Arm(hosted.load_hosted_spec(tmp_path / "spec.yaml"), out)
    clean = tmp_path / "out" / "clean"
    clean.mkdir()
    (clean / "a.json").write_text('{"x": 1}')
    assert hosted.scan_credentials(arm, [clean])["hits"] == []
    planted = out / "rehearsal" / "planted.json"
    secret = os.environ["MISTRAL_API_KEY"]
    planted.write_text(json.dumps({"raw": base64.b64encode(secret.encode()).decode()}))
    found = hosted.scan_credentials(arm, [out / "rehearsal"])
    assert found["hits"] == ["rehearsal/planted.json".replace("/", os.sep)]
    assert not planted.exists() and (out / "quarantine" / "rehearsal" / "planted.json").exists()
    assert hosted.Arm(arm.spec, out).campaign.stopped


# --- 33-34: score and the environment -------------------------------------------------------


def test_33_score_reads_collected_pages_only_and_a_missing_one_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    for provider in ("gemini_api", "mistral_ocr_4"):
        hosted.hosted_candidate(spec, provider).validate()
    fake_root = out / "dry" / "fake"
    missing = sorted((fake_root / "gemini_api").iterdir())[0]
    missing.unlink()
    docs = json.loads((tmp_path / "manifest.json").read_text())["documents"]
    gold = {
        f"{d['doc_id']}#0": {"text": "x", "blocks": [], "critical_fields": []}
        for d in docs
        if d["split"] == "dev"
    }
    result = hosted.score(
        spec, out, tmp_path / "manifest.json", tmp_path / "corpus", gold, fake_root
    )
    records = [
        json.loads(line) for line in (out / "score" / "gemini_api.jsonl").read_text().splitlines()
    ]
    unavailable = [r for r in records if r["hard_failures"] == ["provider_unavailable"]]
    assert len(records) == 4 and len(unavailable) == 1
    assert result["gold_eligible"] is False


def test_34_the_environment_check_refuses_a_foreign_module_or_renderer(tmp_path: Path) -> None:
    inside = str(tmp_path / "pkg" / "__init__.py")
    ok = hosted.check_environment(
        tmp_path, "4.30.0", origin=lambda _: inside, version=lambda: "4.30.0"
    )
    assert ok["renderer_version"] == "4.30.0" and set(ok["module_origins"]) == {
        "akc_security",
        "akc_quality",
        "benchmark",
    }
    with pytest.raises(ContractError, match="akc_security"):
        hosted.check_environment(
            tmp_path, "4.30.0", origin=lambda _: "C:/elsewhere/x.py", version=lambda: "4.30.0"
        )
    with pytest.raises(ContractError, match="renderer_version"):
        hosted.check_environment(
            tmp_path, "4.30.0", origin=lambda _: inside, version=lambda: "5.15.2"
        )
