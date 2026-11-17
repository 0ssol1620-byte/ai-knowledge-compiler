"""Hosted arm (WO-D10-0D): the door, the spend stop, resume. Fakes and in-process markers only:
no key, no provider call, no network."""

from __future__ import annotations

import base64
import functools
import hashlib
import io
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
from hypothesis import given, settings
from hypothesis import strategies as st
from pypdf import PdfWriter

from benchmark.runners import gemini_api, vlm
from benchmark.runners.base import RunnerUnavailable
from benchmark.screen import hosted
from benchmark.screen.manifest import assign_split, freeze
from benchmark.v6.contracts import ContractError, canonical_sha256

MODEL = "gemini-4-hydrogen"
MISTRAL_MODEL = "mistral-ocr-4-1"
ENV = {"module_origins": {}, "renderer_version": "4.30.0"}
# The shape of the kept snapshots, small: each pinned price sits in its model's row for its
# mode (the repository spec's anchors), and the same strings also occur in other rows.
SNAPSHOT = (
    b"<html>\n## Gemini 4 Hydrogen  {% id=&quot;gemini-4-hydrogen&quot; %}\n"
    b"{% tab title=&quot;Standard&quot; %}\n* Input price\n* $1.50\n---\n{% /tab %}\n"
    b"{% tab title=&quot;Batch&quot; %}\n* Input price\n* $0.75\n---\n"
    b"* Output price (including thinking tokens)\n* $3.75\n---\n{% /tab %}\n"
    b"\n## Gemini 3.8 Flash  {% id=&quot;gemini-3.8-flash&quot; %}\n"
    b"{% tab title=&quot;Batch&quot; %}\n* Input price\n* $0.75\n---\n{% /tab %}\n"
    b"| [OCR 4.1](/models/ocr-4-1) | `mistral-ocr-4-1` | Input $4 /1000 Pages |\n"
    b"| [OCR 3](/models/ocr-3) | `mistral-ocr-2512` | Input $2 /1000 Pages |\n</html>"
)
# the hosts the transport may reach (the fakes replace the transport itself)
ALLOWLIST = "generativelanguage.googleapis.com,api.mistral.ai"
LICENCE_SNAPSHOT = "sha256:" + hashlib.sha256(b"test licence snapshot").hexdigest()
FILLER = "zz-filler"  # the stratum of the two filler PDFs that meet the screen floors
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
            "licence_snapshot_sha256": LICENCE_SNAPSHOT,
            "rights_class": rights,
            "redistribution": False,
            "recorded_by": "test fixture",
            "recorded_at": "2026-11-17",
        },
    }
    if split is None:
        del doc["split"]
    if rights is None:
        del doc["rights"]
    return doc


@functools.cache
def _blank_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(72, 72)
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()


def _corpus(tmp_path: Path, docs: list[dict[str, Any]]) -> tuple[Path, Path]:
    """The documents' files and their manifest, frozen by the real ``freeze`` (profile screen).

    Each document's ``split`` is the split the test wants; the salt is searched until
    ``assign_split`` gives exactly that, so ``freeze`` itself accepts it. The 300/100 floors
    are met by filler that the door refuses (rights ``owned``): per test stratum one page in
    the split the stratum needs besides the test's, and two PDFs (300 dev pages, 100 holdout
    pages) in a stratum of their own. Nothing is admitted that the test did not name."""
    root = tmp_path / "corpus"
    root.mkdir(exist_ok=True)
    want = {d["doc_id"]: d["split"] for d in docs}
    records = [{k: v for k, v in d.items() if k != "split"} for d in docs]
    for stratum in sorted({d["stratum"] for d in docs}):
        held = any(d["stratum"] == stratum and d["split"] == "holdout" for d in docs)
        records.append({**_doc(0, stratum=stratum, rights="owned"), "doc_id": f"zz-{stratum}.png"})
        want[f"zz-{stratum}.png"] = "dev" if held else "holdout"
    for split, pages in (("dev", 300), ("holdout", 100)):
        filler = _doc(0, stratum=FILLER, rights="owned")
        records.append({**filler, "doc_id": f"zz-{split}.pdf", "page_count": pages})
        want[f"zz-{split}.pdf"] = split
    for doc in records:
        doc.pop("split", None)
        if doc["doc_id"].endswith(".pdf"):
            data = _blank_pdf(doc["page_count"])
        else:
            data = b"\x89PNG fake " + doc["doc_id"].encode()
        (root / doc["doc_id"]).write_bytes(data)
        doc.update(source_sha256="sha256:" + hashlib.sha256(data).hexdigest(), byte_size=len(data))
    for n in range(1000):
        salt = f"hosted-{n}"
        assigned = assign_split(records, salt)
        if all(d["split"] == want[d["doc_id"]] for d in assigned):
            break
    else:
        raise AssertionError(f"no salt gives the splits {want}")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(freeze(assigned, salt, "screen")), encoding="utf-8")
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
        return sum(1 for m, p, _ in self.calls if m == "POST" and not p.endswith(":cancel"))

    def cancels(self) -> list[str]:
        return [p for m, p, _ in self.calls if m == "POST" and p.endswith(":cancel")]

    def add(self, display: str, keys: list[str]) -> str:
        name = f"batches/b{len(self.batches) + 1}"
        self.batches[name] = {"display": display, "keys": keys, "deleted": False, "state": None}
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
                "state": batch["state"] or self.state,
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
        if method == "POST" and path.endswith(":cancel"):
            self.batches[path.lstrip("/").removesuffix(":cancel")]["state"] = (
                "BATCH_STATE_CANCELLED"
            )
            return 200, "application/json", b"{}"
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
    path, corpus = _corpus(tmp_path, docs)
    frozen = {d["doc_id"]: d for d in json.loads(path.read_bytes())["documents"]}
    out = tmp_path / "out"
    _prepaid(spec, out, draw)
    arm = hosted.Arm(spec, out, hosted.GeminiBatches())
    arm.campaign.reserve_stage("dry", 0)
    pages = _pages([frozen[d["doc_id"]] for d in docs])
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
        hosted.call_mistral(arm, "dry", page, tmp_path, image_sha256=info["image_sha256"])
    assert fake.calls == [] and mistral_calls == [] and built == []
    pages, refused = hosted.page_list([doc])
    assert pages == [] and refused[0]["doc_id"] == doc["doc_id"]


def test_20_admitted_rights_classes_are_exactly_the_hosted_list() -> None:
    assert {"public_record", "permissive_licence", "synthetic"} == hosted.HOSTED_RIGHTS
    for rights in ("public_record", "permissive_licence", "synthetic"):
        hosted.admit(_doc(1, rights=rights))


# --- 21-24: money -----------------------------------------------------------------------------


def test_21_the_worst_case_is_the_formula_in_decimal(tmp_path: Path) -> None:
    # Lead decision E (round 2): maxOutputTokens bounds thinking and output combined, so the
    # worst case is 2500 x 0.75 + 8192 x 3.75 per 1M tokens, with no second thinking term,
    # whether the spec pins a budget or a level (was 0.036435 / 0.155475 before the decision).
    budget = _spec(tmp_path, thinking={"thinkingBudget": 1024})
    assert hosted.page_worst_usd(budget, "gemini_api") == Decimal("0.032595")
    assert hosted.thinking_bound(budget) == 1024
    level = _spec(tmp_path, thinking={"thinkingLevel": "LOW"})
    assert hosted.page_worst_usd(level, "gemini_api") == Decimal("0.032595")
    assert hosted.thinking_bound(level) == 8192
    assert hosted.page_worst_usd(level, "mistral_ocr_4") == Decimal("0.004")


def test_22_a_chunk_over_the_credit_left_is_refused_before_any_write(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    # a draw below one page's worst case (0.032595 since lead decision E; it was 0.10 against
    # the old 0.155475)
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1)], draw="0.03")
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
    monkeypatch.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", ALLOWLIST)
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
    _rebind_dry(spec, out, narrowed)
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


# --- round 2: a stage finishes only when every page and job has a terminal outcome ----------


class MistralScript:
    """vlm.post_bytes for Mistral: answers in call order from ``answers``, then 200. An int is
    an HTTP status; a str is a 200 naming that served model id."""

    def __init__(self, answers: list[Any]) -> None:
        self.answers, self.calls = list(answers), 0

    def __call__(
        self, config: Any, body: bytes, headers: dict[str, str], **_: Any
    ) -> tuple[int, str, bytes]:
        answer = self.answers[self.calls] if self.calls < len(self.answers) else 200
        self.calls += 1
        if answer == 200:
            return _mistral_ok(config, body, headers)
        if isinstance(answer, str):
            doc = {
                "model": answer,
                "pages": [{"index": 0, "markdown": "x"}],
                "usage_info": {"pages_processed": 1},
            }
            return 200, "application/json", json.dumps(doc).encode()
        return int(answer), "application/json", b'{"message": "no"}'


def _ledger_size(spec: hosted.HostedSpec, out: Path) -> int:
    return len(hosted.Arm(spec, out).ledger.replay())


def _manifest_page(tmp_path: Path, doc_id: str) -> hosted.Page:
    docs = json.loads((tmp_path / "manifest.json").read_text())["documents"]
    return hosted.Page(f"{doc_id}#0", next(d for d in docs if d["doc_id"] == doc_id), 0)


def _receipt_of(out: Path, stage: str) -> dict[str, Any]:
    return dict(json.loads((out / stage / "receipt.json").read_bytes()))


def _rebuild_ledger(spec: hosted.HostedSpec, out: Path, edit: Any) -> None:
    """A fresh ledger with the same events in order; ``edit(type, payload)`` returns the payload
    to keep, or None to leave the event out."""
    ledger = hosted.Arm(spec, out).ledger
    events = ledger.replay()
    ledger.path.unlink()
    for event in events:
        payload = edit(event.event_type, dict(event.payload))
        if payload is not None:
            ledger.append(event.event_type, payload)


def _rebind_dry(spec: hosted.HostedSpec, out: Path, dry: dict[str, Any]) -> None:
    """Another dry plan, as if the dry stage had written it: the receipt rewritten and a fresh
    ledger whose one ``hosted.dry_receipt.v1`` holds its sha256 (never a second event)."""
    path = out / "dry" / "receipt.json"
    path.write_text(json.dumps(dry), encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    _rebuild_ledger(
        spec,
        out,
        lambda kind, payload: {"sha256": digest} if kind == "hosted.dry_receipt.v1" else payload,
    )


def _main(tmp_path: Path, out: Path, stage: str) -> int:
    return hosted.main(
        [
            stage,
            "--out",
            str(out),
            "--spec",
            str(tmp_path / "spec.yaml"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--corpus-root",
            str(tmp_path / "corpus"),
            "--snapshot-dir",
            str(tmp_path / "snap"),
            "--max-wait",
            "0",
            "--interval",
            "0",
        ]
    )


def test_r2_a_mistral_429_in_full_is_pending_and_collect_sends_attempt_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, out, _ = _rehearse(tmp_path, monkeypatch)
    monkeypatch.setattr(hosted, "check_environment", lambda *a, **k: ENV)
    script = MistralScript([429])
    monkeypatch.setattr(vlm, "post_bytes", script)
    assert _paid(spec, out, tmp_path, "full") == 3
    assert not (out / "full" / "receipt.json").exists()
    assert hosted.in_progress_stage(hosted.Arm(spec, out, hosted.NoNetwork())) == "full"
    assert _main(tmp_path, out, "collect") == 0
    intents = [
        p
        for p in hosted.Arm(spec, out).events("job.dispatch.intent.v1")
        if p["provider"] == "mistral_ocr_4" and p["stage"] == "full"
    ]
    assert [(p["page_id"], p["attempt"]) for p in intents] == [("d4.png#0", 1), ("d4.png#0", 2)]
    assert len(list((out / "collected" / "mistral_ocr_4").iterdir())) == 4
    receipt = _receipt_of(out, "full")
    assert receipt["results"]["failures"]["mistral_ocr_4"] == {
        "operational": {},
        "model": {},
        "not_collected": [],
    }
    assert script.calls == 2


def test_r2_a_mistral_429_backs_off_the_rest_of_the_run_and_collect_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    script = MistralScript([429])
    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini())
    monkeypatch.setattr(vlm, "post_bytes", script)
    assert _paid(spec, out, tmp_path, "rehearsal") == 3
    assert script.calls == 1  # the rate-limited provider is not called again in this run
    assert _paid(spec, out, tmp_path, "rehearsal") == 0
    assert script.calls == 4  # attempt 2 of the first page, then the two others
    assert len(list((out / "collected" / "mistral_ocr_4").iterdir())) == 3


def test_r2_reserved_attempts_used_up_give_a_terminal_row_reported_apart_from_model_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, out, _ = _rehearse(tmp_path, monkeypatch)
    script = MistralScript([429, 429])
    monkeypatch.setattr(vlm, "post_bytes", script)
    assert _paid(spec, out, tmp_path, "full") == 3
    assert _paid(spec, out, tmp_path, "full") == 0  # attempt 2 also 429: exhausted, terminal
    case = _manifest_page(tmp_path, "d4.png").case_id
    row = json.loads((out / "collected" / "mistral_ocr_4" / f"{case}.json").read_bytes())
    assert row["failure"] == {"reason": hosted.EXHAUSTED}
    assert row["receipt"]["attempts"] == hosted.MISTRAL_ATTEMPTS_RESERVED == script.calls
    failures = _receipt_of(out, "full")["results"]["failures"]["mistral_ocr_4"]
    assert failures["operational"] == {hosted.EXHAUSTED: 1} and failures["model"] == {}
    docs = json.loads((tmp_path / "manifest.json").read_text())["documents"]
    gold = {
        f"{d['doc_id']}#0": {"text": "x", "blocks": [], "critical_fields": []}
        for d in docs
        if d["split"] == "dev"
    }
    scored = hosted.score(spec, out, tmp_path / "manifest.json", tmp_path / "corpus", gold)
    assert scored["failures"]["mistral_ocr_4"]["operational"] == {hosted.EXHAUSTED: 1}
    assert scored["failures"]["mistral_ocr_4"]["model"] == {}


def test_r2_finish_refuses_a_stage_with_a_page_without_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, out, _ = _rehearse(tmp_path, monkeypatch)
    page = _manifest_page(tmp_path, "d4.png")  # never sent: not collected
    pages = hosted.StagePages((page,), (page,), (), {})
    with pytest.raises(ContractError, match="not complete"):
        hosted._finish_stage(hosted.Arm(spec, out), "full", pages, ENV, [], {}, [], {})
    assert hosted.stage_gaps(hosted.Arm(spec, out), "full", pages) == [
        "gemini_api:d4.png#0",
        "mistral_ocr_4:d4.png#0",
    ]


def test_r2_a_stopped_arm_cancels_what_runs_collects_nothing_new_and_tears_down_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini(state="BATCH_STATE_RUNNING")
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    assert _paid(spec, out, tmp_path, "rehearsal") == 3
    hosted.Arm(spec, out).stop("some_other_stop")
    creates = fake.creates()
    assert _paid(spec, out, tmp_path, "rehearsal") == 3  # polled; still running: cancelled
    assert fake.cancels() == ["/batches/b1:cancel"]
    with pytest.raises(ContractError, match="lead decides"):
        _paid(spec, out, tmp_path, "rehearsal")
    arm = hosted.Arm(spec, out)
    terminal = arm.events("hosted.job.terminal.v1")
    assert [(t["state"], t["reason"]) for t in terminal] == [
        ("BATCH_STATE_CANCELLED", "job_not_succeeded")
    ]
    assert arm.events("campaign.teardown.v1")[-1]["confirmed_404"] == ["b1"]
    assert fake.batches["batches/b1"]["deleted"] and fake.creates() == creates
    size = _ledger_size(spec, out)
    for _ in range(3):  # idempotent once everything is terminal
        with pytest.raises(ContractError, match="lead decides"):
            _paid(spec, out, tmp_path, "rehearsal")
    assert _ledger_size(spec, out) == size and len(fake.cancels()) == 1


def test_r2_a_stopped_arm_still_collects_a_job_it_paid_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini(state="BATCH_STATE_RUNNING")
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    assert _paid(spec, out, tmp_path, "rehearsal") == 3
    hosted.Arm(spec, out).stop("some_other_stop")
    fake.state = "BATCH_STATE_SUCCEEDED"
    assert _paid(spec, out, tmp_path, "rehearsal") == 0
    assert len(list((out / "collected" / "gemini_api").iterdir())) == 3
    receipt = _receipt_of(out, "rehearsal")
    assert [s["reason"] for s in receipt["results"]["stops"]] == ["some_other_stop"]
    assert receipt["teardown"]["confirmed_404"] == ["b1"] and fake.cancels() == []


def test_r2_a_mapping_failure_closes_the_job_once(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    fake = FakeGemini(tweak=_drop)
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1), _doc(2)])
    hosted.submit_chunk(arm, "dry", chunks[0], pages, corpus)
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    assert (
        hosted.poll(arm, "dry", max_wait=600, interval=60, sleep=sleep, clock=lambda: now[0]) == 0
    )
    gets = [c for c in fake.calls if c[0] == "GET" and c[1] != "/batches"]
    assert len(gets) == 1
    assert len(arm.events("hosted.batch.mapping_failed.v1")) == 1
    assert len(arm.events("campaign.stopped.v1")) == 1
    (closed,) = arm.events("hosted.job.terminal.v1")
    assert closed["reason"] == "mapping_failed"
    assert Decimal(closed["actual_usd"]) == 2 * hosted.page_worst_usd(spec, "gemini_api")
    size = _ledger_size(spec, arm.out)
    for _ in range(3):
        hosted.poll(arm, "dry", max_wait=600, interval=60, sleep=sleep, clock=lambda: now[0])
    assert _ledger_size(spec, arm.out) == size and len(fake.calls) == len(gets) + 1


def test_r2_main_maps_every_failure_to_a_documented_exit_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini()

    def limited(config: Any, method: str, body: Any, headers: Any, **kw: Any) -> Any:
        if method == "POST":
            return 429, "application/json", b"{}"
        return fake(config, method, body, headers, **kw)

    monkeypatch.setattr(gemini_api, "request_bytes", limited)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    monkeypatch.setattr(hosted, "check_environment", lambda *a, **k: ENV)
    assert _main(tmp_path, out, "rehearsal") == 3
    assert "rerun collect later" in capsys.readouterr().err
    url = "https://generativelanguage.googleapis.com/v1beta/batches/x"
    for error, code in [
        (RunnerUnavailable(url), 3),
        (hosted.ImmutableOutputError("x.json: raw output differs"), 2),
        (KeyError(url), 1),
        (ValueError(url), 1),
    ]:

        def boom(*_a: Any, error: Exception = error, **_k: Any) -> int:
            raise error

        monkeypatch.setattr(hosted, "run_paid", boom)
        assert _main(tmp_path, out, "rehearsal") == code
        err = capsys.readouterr().err
        assert url not in err and "Traceback" not in err


def test_r2_the_paid_stage_takes_the_dry_plans_pages_and_records_its_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    path = out / "dry" / "receipt.json"
    dry = json.loads(path.read_bytes())
    dry["mistral_pages"].remove("d1.png#0")
    dry["page_refusals"].append(
        {"page_id": "d1.png#0", "provider": "mistral_ocr_4", "reason": "page_over_image_limit"}
    )
    _rebind_dry(spec, out, dry)
    script = MistralScript([])
    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini())
    monkeypatch.setattr(vlm, "post_bytes", script)
    assert _paid(spec, out, tmp_path, "rehearsal") == 0
    receipt = _receipt_of(out, "rehearsal")
    assert script.calls == 2 and "d1.png#0" not in receipt["mistral_pages"]
    assert receipt["page_refusals"] == [dry["page_refusals"][-1]]


@pytest.mark.parametrize("damage", ["admitted", "image"])
def test_r2_a_paid_stage_whose_pages_differ_from_the_dry_plan_is_refused(
    damage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    path = out / "dry" / "receipt.json"
    dry = json.loads(path.read_bytes())
    if damage == "image":
        dry["pages"][0]["image_sha256"] = "sha256:" + "0" * 64
        _rebind_dry(spec, out, dry)
        with pytest.raises(ContractError, match="dry plan"):
            _paid(spec, out, tmp_path, "rehearsal")
        assert fake.calls == []
        return
    assert _paid(spec, out, tmp_path, "rehearsal") == 0
    dry["admitted"]["page_ids"] = dry["admitted"]["page_ids"][:-1]
    _rebind_dry(spec, out, dry)
    calls = len(fake.calls)
    with pytest.raises(ContractError, match="differs from the dry receipt"):
        _paid(spec, out, tmp_path, "full")
    assert len(fake.calls) == calls


def test_r2_full_rechecks_the_whole_remaining_gemini_worst_case_before_its_first_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, out, fake = _rehearse(tmp_path, monkeypatch)
    arm = hosted.Arm(spec, out)
    assert arm.credit is not None
    spent = arm.credit.remaining_usd - hosted.page_worst_usd(spec, "gemini_api") / 2
    # an earlier job charged at its worst case (e.g. one that failed): the credit left now
    # holds half of the one remaining page's worst case
    arm.ledger.append(
        "job.dispatch.intent.v1",
        {
            "idempotency_key": "sha256:" + "e" * 64,
            "logical_work_id": "gemini_api:sha256:" + "e" * 64,
            "input_sha256": "sha256:" + "e" * 64,
            "provider": "gemini_api",
            "stage": "rehearsal",
            "reserved_usd": str(spent),
            "pages": [],
        },
    )
    arm.ledger.append(
        "hosted.job.terminal.v1",
        {
            "idempotency_key": "sha256:" + "e" * 64,
            "provider": "gemini_api",
            "actual_usd": str(spent),
        },
    )
    creates = fake.creates()
    with pytest.raises(ContractError, match="above the credit left"):
        _paid(spec, out, tmp_path, "full")
    assert fake.creates() == creates
    assert not [
        p
        for p in hosted.Arm(spec, out).events("campaign.stage_reserved.v1")
        if p["stage"] == "full"
    ]


def _spec_with_snapshot(tmp_path: Path, data: bytes) -> hosted.HostedSpec:
    spec = _spec(tmp_path)
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / "snap" / f"{sha}.html").write_bytes(data)
    raw = yaml.safe_load(spec.path.read_text(encoding="utf-8"))
    for block in raw["hosted"].values():
        for price in block["prices"].values():
            price.update(snapshot_file=f"{sha}.html", snapshot_sha256=sha)
    spec.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return hosted.load_hosted_spec(spec.path)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # hydrogen's Batch input price differs; "$0.75" stays only in Flash's Batch row
        (b"* Input price\n* $0.75\n---\n* Output", b"* Input price\n* $0.80\n---\n* Output"),
        # the value sits in hydrogen's Standard tab, not its Batch tab
        (b"* $1.50", b"* $0.75 x"),
        # OCR 4.1 reads $40; "$4" alone is not in its row
        (b"Input $4 /1000", b"Input $40 /1000"),
        # the anchor's start occurs twice: not one row
        (b"<html>", b"<html>| `mistral-ocr-4-1` |"),
    ],
)
def test_r2_a_price_is_confirmed_only_in_its_models_row_for_its_mode(
    old: bytes, new: bytes, tmp_path: Path
) -> None:
    damaged = SNAPSHOT.replace(old, new, 1)
    if old == b"* $1.50":  # Standard holds $0.75 and Batch no longer does
        batch_row = b"* Input price\n* $0.75\n---\n* Output"
        damaged = damaged.replace(batch_row, batch_row.replace(b"$0.75", b"$0.9"))
    assert damaged != SNAPSHOT
    ok = tmp_path / "ok"
    ok.mkdir()
    assert len(hosted.check_snapshots(_spec(ok), ok / "snap")) == 3
    spec = _spec_with_snapshot(tmp_path, damaged)
    with pytest.raises(ContractError, match="row for that model and mode"):
        hosted.check_snapshots(spec, tmp_path / "snap")


@pytest.mark.parametrize(
    ("tweak_name", "reason"),
    [("cutoff", "output_token_cutoff"), ("over", "output_tokens_over_bound")],
)
def test_r2_a_cut_off_rehearsal_page_is_a_failure_row_counted_and_stops_the_arm(
    tweak_name: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def tweak(entries: list[Any]) -> list[Any]:
        response = entries[0]["response"]
        if tweak_name == "cutoff":
            response["candidates"][0]["finishReason"] = "MAX_TOKENS"
        else:  # 300 candidate + 8000 thought tokens: over maxOutputTokens 8192
            response["usageMetadata"]["thoughtsTokenCount"] = 8000
        return entries

    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini(tweak=tweak))
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    assert _paid(spec, out, tmp_path, "rehearsal") == 0
    receipt = _receipt_of(out, "rehearsal")
    assert receipt["results"]["failures"]["gemini_api"]["model"] == {reason: 1}
    assert [s["reason"] for s in receipt["results"]["stops"]] == ["rehearsal_page_cut_off"]
    (job,) = receipt["results"]["accepted"]
    assert [p["thoughts_tokens"] for p in job["pages"]] == [
        8000 if tweak_name == "over" else 100,
        100,
        100,
    ]
    with pytest.raises(ContractError, match="stopped"):
        _paid(spec, out, tmp_path, "full")


def test_r2_served_ids_are_a_closed_map_holding_the_pinned_id(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    assert spec.mistral["served_ids"] == {"mistral-ocr-4-1": ["mistral-ocr-4-1"]}
    for served in (
        {"mistral-ocr-4-1": ["mistral-ocr-2512"]},
        {"mistral-ocr-4-1": ["mistral-ocr-4-1"], "mistral-ocr-4": ["mistral-ocr-4"]},
        {"mistral-ocr-4-1": "mistral-ocr-4-1"},
        None,
    ):
        raw = yaml.safe_load(spec.path.read_text(encoding="utf-8"))
        raw["hosted"]["mistral_ocr_4"]["served_ids"] = served
        spec.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        with pytest.raises(ContractError, match="served_ids"):
            hosted.load_hosted_spec(spec.path)


def test_r2_a_dated_served_id_stops_the_arm_with_the_observed_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini())
    monkeypatch.setattr(vlm, "post_bytes", MistralScript(["mistral-ocr-2512"]))
    with pytest.raises(ContractError, match="lead decides"):
        _paid(spec, out, tmp_path, "rehearsal")
    (stop,) = hosted.Arm(spec, out).events("campaign.stopped.v1")
    assert stop["reason"] == "mistral_served_model_differs"
    assert stop["observed_model"] == "mistral-ocr-2512"


@pytest.mark.parametrize("status", [401, 403])
def test_r2_a_mistral_401_or_403_stops_the_mistral_half_and_gemini_proceeds(
    status: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    script = MistralScript([status])
    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini())
    monkeypatch.setattr(vlm, "post_bytes", script)
    assert _paid(spec, out, tmp_path, "rehearsal") == 0
    receipt = _receipt_of(out, "rehearsal")
    assert script.calls == 1 and len(receipt["results"]["mistral_not_run"]) == 2
    assert receipt["results"]["failures"]["mistral_ocr_4"]["operational"] == {f"http_{status}": 1}
    assert receipt["results"]["stops"] == []
    assert _paid(spec, out, tmp_path, "full") == 0  # Gemini only; Mistral recorded not run
    assert script.calls == 1
    # full owns every admitted page: the two the rehearsal did not run, and d4
    assert _receipt_of(out, "full")["results"]["mistral_not_run"] == [
        "d2.png#0",
        "d3.png#0",
        "d4.png#0",
    ]


def test_r2_a_listing_token_outside_the_accepted_shape_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = iter(
        [
            {"operations": [], "nextPageToken": "abc+/=="},
            {"operations": [], "nextPageToken": "a b"},
        ]
    )
    seen: list[Any] = []

    def listing(token: Any, *, allow_network: bool) -> dict[str, Any]:
        seen.append(token)
        raw = json.dumps(next(pages)).encode()
        return {"http_status": 200, "raw_b64": base64.b64encode(raw).decode()}

    monkeypatch.setattr(gemini_api, "batch_list", listing)
    with pytest.raises(ContractError, match="page token"):
        hosted.GeminiBatches().list_all()
    assert seen == [None, "abc+/=="]


# --- round 2: fuzzing the paid stages over provider answers ----------------------------------


@pytest.fixture(scope="module")
def dried(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("dried")
    with pytest.MonkeyPatch.context() as mp:
        _through_dry(root, _spec(root), mp)
    return root


_GEMINI_CASES = {
    "ok": None,
    "drop": _drop,
    "failed": "BATCH_STATE_FAILED",
    "cutoff": lambda entries: [
        {**e, "response": {**e["response"], "candidates": [{"finishReason": "MAX_TOKENS"}]}}
        if i == 0
        else e
        for i, e in enumerate(entries)
    ],
}


@settings(max_examples=25, deadline=None, derandomize=True)
@given(
    gemini=st.sampled_from(sorted(_GEMINI_CASES)),
    answers=st.lists(
        st.sampled_from([200, 200, 429, 500, 401, 400, "mistral-ocr-2512"]), max_size=8
    ),
)
def test_r2_fuzz_every_paid_run_ends_complete_pending_or_refused_and_terminal_runs_add_nothing(
    dried: Path, gemini: str, answers: list[Any]
) -> None:
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as mp:
        root = Path(tmp) / "r"
        shutil.copytree(dried, root)
        spec = hosted.load_hosted_spec(root / "spec.yaml")
        out = root / "out"
        mp.setenv("GEMINI_API_KEY", _marker())
        mp.setenv("MISTRAL_API_KEY", _marker("mk"))
        mp.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", ALLOWLIST)
        case = _GEMINI_CASES[gemini]
        fake = FakeGemini(state=case) if isinstance(case, str) else FakeGemini(tweak=case)
        mp.setattr(gemini_api, "request_bytes", fake)
        mp.setattr(vlm, "post_bytes", MistralScript(answers))
        for stage in ("rehearsal", "full"):
            code = 3
            for _ in range(8):
                try:
                    code = _paid(spec, out, root, stage)
                except ContractError:
                    code = 2
                assert code in (0, 2, 3)
                assert (out / stage / "receipt.json").exists() == (code == 0)
                attempts: dict[str, int] = {}
                for p in hosted.Arm(spec, out).events("job.dispatch.intent.v1"):
                    if p["provider"] == "mistral_ocr_4":
                        attempts[p["page_id"]] = attempts.get(p["page_id"], 0) + 1
                assert max(attempts.values(), default=0) <= hosted.MISTRAL_ATTEMPTS_RESERVED
                if code != 3:
                    break
            assert code != 3, "a stage stayed pending with nothing left to wait for"
            if code == 0:
                receipt = _receipt_of(out, stage)
                dry = json.loads((out / "dry" / "receipt.json").read_bytes())
                admitted, _ = hosted.page_list(
                    json.loads((root / "manifest.json").read_bytes())["documents"]
                )
                pages = hosted.stage_pages(stage, admitted, dry)
                assert hosted.stage_gaps(hosted.Arm(spec, out), stage, pages) == []
                for row in (out / "collected" / "mistral_ocr_4").iterdir():
                    reason = (json.loads(row.read_bytes()).get("failure") or {}).get("reason")
                    assert reason != "http_429"
                assert set(receipt["results"]["failures"]) == {"gemini_api", "mistral_ocr_4"}
            size = _ledger_size(spec, out)
            for _ in range(2):  # a terminal stage: running it again appends nothing
                with pytest.raises(ContractError):
                    _paid(spec, out, root, stage)
            assert _ledger_size(spec, out) == size
            if code == 2:
                break


# --- WO-D10-0J: the reviewer's eight notes ---------------------------------------------------


def test_0j_1_a_job_whose_get_answers_404_is_closed_once_and_the_stopped_stage_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini(state="BATCH_STATE_RUNNING")
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    monkeypatch.setattr(hosted, "check_environment", lambda *a, **k: ENV)
    assert _paid(spec, out, tmp_path, "rehearsal") == 3
    fake.batches["batches/b1"]["deleted"] = True  # gone outside the arm
    with pytest.raises(ContractError, match="lead decides"):
        _paid(spec, out, tmp_path, "rehearsal")
    arm = hosted.Arm(spec, out)
    (closed,) = arm.events("hosted.job.terminal.v1")
    (intent,) = [p for p in arm.events("job.dispatch.intent.v1") if p["provider"] == "gemini_api"]
    assert (closed["state"], closed["reason"]) == ("NOT_FOUND", "job_not_found")
    assert closed["actual_usd"] == intent["reserved_usd"]  # the worst case is kept
    assert [s["reason"] for s in arm.events("campaign.stopped.v1")] == ["batch_not_found"]
    size = _ledger_size(spec, out)
    for _ in range(2):
        with pytest.raises(ContractError, match="lead decides"):
            _paid(spec, out, tmp_path, "rehearsal")
    assert _main(tmp_path, out, "collect") == 2
    assert _ledger_size(spec, out) == size


@pytest.mark.parametrize("status", [429, 500, 503])
def test_0j_2_only_a_200_counts_as_the_cancel_and_a_refused_one_is_tried_again(
    status: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini(state="BATCH_STATE_RUNNING")
    first = [True]

    def flaky(config: Any, method: str, body: Any, headers: Any, **kw: Any) -> Any:
        if method == "POST" and config.endpoint.endswith(":cancel") and first[0]:
            first[0] = False
            return status, "application/json", b"{}"
        return fake(config, method, body, headers, **kw)

    monkeypatch.setattr(gemini_api, "request_bytes", flaky)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    assert _paid(spec, out, tmp_path, "rehearsal") == 3
    hosted.Arm(spec, out).stop("some_other_stop")
    assert _paid(spec, out, tmp_path, "rehearsal") == 3  # the cancel was refused: running
    assert _paid(spec, out, tmp_path, "rehearsal") == 3  # tried again: 200
    assert fake.cancels() == ["/batches/b1:cancel"]
    with pytest.raises(ContractError, match="lead decides"):
        _paid(spec, out, tmp_path, "rehearsal")  # cancelled: closed and torn down
    arm = hosted.Arm(spec, out)
    assert [p["http_status"] for p in arm.events("hosted.job.cancel_requested.v1")] == [
        status,
        200,
    ]
    assert fake.cancels() == ["/batches/b1:cancel"]


_LOCAL = {  # the operator's environment: refused, recorded once, the arm NOT stopped
    "no_mistral_key": [("mistral_ocr_4", "no_key")],
    "no_gemini_key": [("gemini_api", "no_key")],
    "no_key_at_all": [("gemini_api", "no_key"), ("mistral_ocr_4", "no_key")],
    "allowlist_unset": [
        ("gemini_api", "host_not_allowlisted"),
        ("mistral_ocr_4", "host_not_allowlisted"),
    ],
    "mistral_host_not_listed": [("mistral_ocr_4", "host_not_allowlisted")],
}


def _break_environment(cause: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if cause in ("no_mistral_key", "no_key_at_all"):
        monkeypatch.delenv("MISTRAL_API_KEY")
    if cause in ("no_gemini_key", "no_key_at_all"):
        monkeypatch.delenv("GEMINI_API_KEY")
    if cause == "allowlist_unset":
        monkeypatch.delenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST")
    if cause == "mistral_host_not_listed":
        monkeypatch.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", "generativelanguage.googleapis.com")


@pytest.mark.parametrize("cause", sorted(_LOCAL))
def test_0j_3_an_operator_refusal_reserves_nothing_stops_nothing_and_the_fixed_rerun_continues(
    cause: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake, script = FakeGemini(), MistralScript([])
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", script)
    with monkeypatch.context() as broken:
        _break_environment(cause, broken)
        for _ in range(2):  # one event per distinct reason, not one per run
            with pytest.raises(ContractError, match="local refusal"):
                _paid(spec, out, tmp_path, "rehearsal")
    arm = hosted.Arm(spec, out)
    found = [(r["provider"], r["reason"]) for r in arm.events("hosted.local_refusal.v1")]
    assert found == _LOCAL[cause]
    assert not arm.campaign.stopped
    assert fake.calls == [] and script.calls == 0
    assert not arm.events("job.dispatch.intent.v1") and not arm.events("hosted.page.settled.v1")
    assert not [p for p in arm.events("campaign.stage_reserved.v1") if p["stage"] == "rehearsal"]
    assert _paid(spec, out, tmp_path, "rehearsal") == 0  # the environment fixed: it continues


def test_0j_3_a_credential_in_a_case_id_is_an_integrity_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake, script = FakeGemini(), MistralScript([])
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", script)
    case_id = _manifest_page(tmp_path, "d3.png").case_id  # a declared credential equal to it
    monkeypatch.setenv("AKC_BENCHMARK_PROVIDER_TOKEN", case_id)
    with pytest.raises(ContractError, match="lead decides"):
        _paid(spec, out, tmp_path, "rehearsal")
    arm = hosted.Arm(spec, out)
    (refusal,) = arm.events("hosted.local_refusal.v1")
    assert (refusal["provider"], refusal["reason"]) == ("gemini_api", "credential_in_inputs")
    assert [s["reason"] for s in arm.events("campaign.stopped.v1")] == ["local_refusal"]
    assert fake.calls == [] and script.calls == 0
    assert not arm.events("job.dispatch.intent.v1") and not arm.events("hosted.page.settled.v1")
    assert not [p for p in arm.events("campaign.stage_reserved.v1") if p["stage"] == "rehearsal"]
    with pytest.raises(ContractError, match="stopped"):
        _paid(spec, out, tmp_path, "rehearsal")


def test_0j_3_a_rehearsal_page_that_exhausts_its_attempts_stops_the_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    script = MistralScript([429, 429])
    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini())
    monkeypatch.setattr(vlm, "post_bytes", script)
    assert _paid(spec, out, tmp_path, "rehearsal") == 3
    with pytest.raises(ContractError, match="lead decides"):
        _paid(spec, out, tmp_path, "rehearsal")
    (stop,) = hosted.Arm(spec, out).events("campaign.stopped.v1")
    assert stop == {"reason": "rehearsal_page_exhausted", "page_id": "d1.png#0"}
    assert script.calls == hosted.MISTRAL_ATTEMPTS_RESERVED
    with pytest.raises(ContractError, match="rehearsal"):
        _paid(spec, out, tmp_path, "full")


def test_0j_4_an_anchor_whose_end_is_not_found_confirms_nothing(tmp_path: Path) -> None:
    step = [{"start": "| `m` |", "end": "\n"}]
    assert hosted.anchored("a | `m` | $4 /1000\nb $40", step) == " $4 /1000"
    assert hosted.anchored("a | `m` | $4 /1000 b $40", step) is None
    # the OCR 4.1 row is the snapshot's last text and no line end follows it
    head = SNAPSHOT.split(b"| `mistral-ocr-4-1` |")[0]
    spec = _spec_with_snapshot(tmp_path, head + b"| `mistral-ocr-4-1` | Input $4 /1000 Pages |")
    with pytest.raises(ContractError, match="row for that model and mode"):
        hosted.check_snapshots(spec, tmp_path / "snap")


def test_0j_5_the_dry_receipt_is_bound_by_the_sha256_the_ledger_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    path = out / "dry" / "receipt.json"
    (recorded,) = hosted.Arm(spec, out).events("hosted.dry_receipt.v1")
    assert recorded["sha256"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    dry = json.loads(path.read_bytes())
    dry["estimate"]["gemini_api"]["worst_usd"] = "0"  # no page-list check would see this
    path.write_text(json.dumps(dry, indent=1, sort_keys=True), encoding="utf-8")
    with pytest.raises(ContractError, match="the ledger recorded"):
        _paid(spec, out, tmp_path, "rehearsal")
    assert fake.calls == []


@pytest.mark.parametrize("dropped_from", ["both_lists", "mistral_pages"])
def test_0j_5_a_page_the_dry_plan_neither_rendered_nor_refused_refuses_the_stage(
    dropped_from: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    dry = json.loads((out / "dry" / "receipt.json").read_bytes())
    if dropped_from == "both_lists":
        dry["pages"] = [r for r in dry["pages"] if r["page_id"] != "d4.png#0"]
    dry["mistral_pages"].remove("d4.png#0")
    _rebind_dry(spec, out, dry)
    fake, script = FakeGemini(), MistralScript([])
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", script)
    assert _paid(spec, out, tmp_path, "rehearsal") == 0  # d4 is not a rehearsal page
    calls = (len(fake.calls), script.calls)
    with pytest.raises(ContractError, match="neither rendered nor refused"):
        _paid(spec, out, tmp_path, "full")
    assert (len(fake.calls), script.calls) == calls


def test_0j_6_a_mistral_page_image_is_compared_with_the_dry_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    dry = json.loads((out / "dry" / "receipt.json").read_bytes())
    # d1's Gemini half refused by the plan: in the paid stage only Mistral renders d1
    dry["page_refusals"].append(
        {"page_id": "d1.png#0", "provider": "gemini_api", "reason": "page_over_inline_limit"}
    )
    row = next(r for r in dry["pages"] if r["page_id"] == "d1.png#0")
    row["image_sha256"] = "sha256:" + "0" * 64
    _rebind_dry(spec, out, dry)
    script = MistralScript([])
    monkeypatch.setattr(gemini_api, "request_bytes", FakeGemini())
    monkeypatch.setattr(vlm, "post_bytes", script)
    with pytest.raises(ContractError, match="differs from the dry plan"):
        _paid(spec, out, tmp_path, "rehearsal")
    assert script.calls == 0
    arm = hosted.Arm(spec, out)
    assert [s["reason"] for s in arm.events("campaign.stopped.v1")] == [
        "mistral_image_differs_from_dry_plan"
    ]
    (settled,) = arm.events("hosted.page.settled.v1")
    assert (settled["page_id"], settled["actual_usd"]) == ("d1.png#0", "0")


def test_0j_7_resubmit_after_absent_is_recorded_once_per_intent(
    tmp_path: Path, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    arm, chunks, pages, corpus = _arm_with_chunk(tmp_path, spec, [_doc(1)])
    fake.fail_create = "before"
    for _ in range(3):  # the first create and two re-creates never reach the provider
        fresh = hosted.Arm(spec, arm.out, hosted.GeminiBatches())
        with pytest.raises(RunnerUnavailable):
            hosted.submit_chunk(fresh, "dry", chunks[0], pages, corpus)
    fake.fail_create = None
    fresh = hosted.Arm(spec, arm.out, hosted.GeminiBatches())
    hosted.submit_chunk(fresh, "dry", chunks[0], pages, corpus)
    assert len(fresh.events("hosted.resubmit_after_absent.v1")) == 1
    assert len(fresh.events("job.dispatched.v1")) == 1 and len(fake.batches) == 1


@pytest.mark.parametrize(
    "extra",
    [
        "mistral-ocr-4-0",
        "mistral-ocr-4",
        "mistral-ocr-latest",
        "mistral-ocr-4-1-latest",
        "Mistral-OCR-Latest",
        "mistral-ocr-4-0-2505",  # a dated form of the retired id
        "mistral-ocr-4-1-2611",  # a dated form not on the reviewed list
        "mistral-ocr-4-2",  # unknown
        "MISTRAL-OCR-4-1",  # no normalisation
    ],
)
def test_0j_8_served_ids_refuse_the_retired_id_and_every_alias(extra: str, tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    raw = yaml.safe_load(spec.path.read_text(encoding="utf-8"))
    raw["hosted"]["mistral_ocr_4"]["served_ids"] = {"mistral-ocr-4-1": ["mistral-ocr-4-1", extra]}
    spec.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ContractError, match="served_ids"):
        hosted.load_hosted_spec(spec.path)


# --- WO-D10-0J round 2: evidence written once; local refusals; cancel; served ids; shapes ----


def _snapshot(out: Path) -> dict[str, bytes]:
    """Every file under the arm's output directory, by relative path."""
    return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def _dry_again(tmp_path: Path, spec: hosted.HostedSpec, out: Path) -> None:
    hosted.run_dry(
        spec,
        out,
        tmp_path / "manifest.json",
        tmp_path / "corpus",
        tmp_path / "snap",
        environment=lambda: ENV,
    )


@pytest.mark.parametrize("after", ["dry", "rehearsal"])
def test_0j_r2_a_second_dry_is_refused_before_any_write(
    after: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe Q1/Q9: the dry command run again (also after a paid stage) never rewrites the dry
    receipt nor binds a second one; ``full`` still runs against the first."""
    if after == "dry":
        spec = _spec(tmp_path)
        out = _through_dry(tmp_path, spec, monkeypatch)
    else:
        spec, out, _ = _rehearse(tmp_path, monkeypatch)
    files = _snapshot(out)
    with monkeypatch.context() as keyless:
        keyless.delenv("GEMINI_API_KEY")
        keyless.delenv("MISTRAL_API_KEY")
        with pytest.raises(ContractError, match="already recorded"):
            _dry_again(tmp_path, spec, out)
        assert _main(tmp_path, out, "dry") == 2  # the CLI, through the real check
    assert _snapshot(out) == files
    assert len(hosted.Arm(spec, out).events("hosted.dry_receipt.v1")) == 1


def test_0j_r2_two_dry_receipt_events_bind_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    (recorded,) = hosted.Arm(spec, out).events("hosted.dry_receipt.v1")
    hosted.Arm(spec, out).ledger.append("hosted.dry_receipt.v1", dict(recorded))  # even equal
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    monkeypatch.setattr(hosted, "check_environment", lambda *a, **k: ENV)
    with pytest.raises(ContractError, match="dry_incomplete"):
        _paid(spec, out, tmp_path, "rehearsal")
    with pytest.raises(ContractError, match="exactly one"):
        hosted.dry_receipt(hosted.Arm(spec, out))
    capsys.readouterr()
    for stage in ("collect", "score"):  # every stage, also those that never read the receipt
        assert _main(tmp_path, out, stage) == 2
    assert capsys.readouterr().err.count("dry_incomplete") == 2
    assert fake.calls == []


@pytest.mark.parametrize("missing", ["pages", "mistral_pages", "page_refusals", "admitted"])
def test_0j_r2_a_missing_dry_list_is_a_refusal_not_an_empty_default(missing: str) -> None:
    """A dry plan that refused every page for both providers reads as an empty stage; the same
    plan with one of its lists missing is refused, never read as an empty list."""
    docs = [_doc(1), _doc(2)]
    admitted = _pages(docs)
    ids = [p.page_id for p in admitted]
    dry: dict[str, Any] = {
        "pages": [],
        "mistral_pages": [],
        "page_refusals": [{"page_id": i, "provider": "both", "reason": "x"} for i in ids],
        "admitted": {"page_ids": ids},
    }
    empty = hosted.stage_pages("full", admitted, dry)
    assert empty.gemini == () and empty.mistral == () and len(empty.refusals) == 2
    del dry[missing]
    with pytest.raises(ContractError):
        hosted.stage_pages("full", admitted, dry)


@pytest.mark.parametrize("stage", ["rehearsal", "full"])
def test_0j_r2_a_paid_stage_never_replaces_a_receipt_file(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file already at the receipt's path (or its temporary) is left as it is, and the stage
    refuses before anything is reserved or sent."""
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    if stage == "full":
        assert _paid(spec, out, tmp_path, "rehearsal") == 0
    calls, files = len(fake.calls), _snapshot(out)
    for name in ("receipt.json", "receipt.json.tmp"):
        planted = out / stage / name
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_bytes(b'{"planted": true}')
        with pytest.raises(ContractError, match="written once"):
            _paid(spec, out, tmp_path, stage)
        assert planted.read_bytes() == b'{"planted": true}'
        planted.unlink()
    assert len(fake.calls) == calls and _snapshot(out) == files


def test_0j_r2_every_stage_run_again_changes_no_receipt_and_no_ledger_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, out, _ = _rehearse(tmp_path, monkeypatch)
    assert _paid(spec, out, tmp_path, "full") == 0
    files = _snapshot(out)
    with pytest.raises(ContractError, match="already recorded"):
        hosted.record_prepaid(spec, out, "13.50", "12.15", "again")
    with monkeypatch.context() as keyless:
        keyless.delenv("GEMINI_API_KEY")
        keyless.delenv("MISTRAL_API_KEY")
        with pytest.raises(ContractError, match="already recorded"):
            _dry_again(tmp_path, spec, out)
    for stage in ("rehearsal", "full"):
        with pytest.raises(ContractError, match="already complete"):
            _paid(spec, out, tmp_path, stage)
    arm = hosted.Arm(spec, out, hosted.NoNetwork())
    for stage in ("prepaid", "dry", "rehearsal", "full"):  # the writer itself refuses
        with pytest.raises(ContractError, match="written once"):
            hosted._write_receipt(arm, stage, {"stage": stage, "forged": True})
    assert _snapshot(out) == files
    stray = out / "score" / "receipt.json.tmp"  # a temporary left by a crash is not replaced
    stray.parent.mkdir()
    stray.write_bytes(b"stray")
    with pytest.raises(ContractError, match="written once"):
        hosted._write_receipt(arm, "score", {"n": 0})
    assert stray.read_bytes() == b"stray" and not (out / "score" / "receipt.json").exists()
    stray.unlink()
    hosted._write_receipt(arm, "score", {"n": 1})
    score = (out / "score" / "receipt.json").read_bytes()
    with pytest.raises(ContractError, match="written once"):
        hosted._write_receipt(arm, "score", {"n": 2})
    assert (out / "score" / "receipt.json").read_bytes() == score


_PARTIAL = ["crash_before_event", "temporary", "event_without_receipt", "receipt_without_event"]


@pytest.mark.parametrize("state", _PARTIAL)
def test_0j_r2_a_partial_dry_stage_refuses_every_stage_with_dry_incomplete(
    state: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = _spec(tmp_path)
    if state == "crash_before_event":  # the real dry stage dies at the ledger write
        real = hosted.EvidenceLedger.append

        def append(self: Any, event_type: str, payload: Any, **kw: Any) -> Any:
            if event_type == "hosted.dry_receipt.v1":
                raise OSError("disk full")
            return real(self, event_type, payload, **kw)

        monkeypatch.setattr(hosted.EvidenceLedger, "append", append)
        with pytest.raises(OSError):
            _through_dry(tmp_path, spec, monkeypatch)
        monkeypatch.setattr(hosted.EvidenceLedger, "append", real)
        out = tmp_path / "out"
        assert (out / "dry" / "receipt.json.tmp").exists()
        assert not (out / "dry" / "receipt.json").exists()
        monkeypatch.setenv("GEMINI_API_KEY", _marker())
        monkeypatch.setenv("MISTRAL_API_KEY", _marker("mk"))
        monkeypatch.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", ALLOWLIST)
    else:
        out = _through_dry(tmp_path, spec, monkeypatch)
        receipt = out / "dry" / "receipt.json"
        if state == "temporary":
            (out / "dry" / "receipt.json.tmp").write_bytes(receipt.read_bytes())
        elif state == "event_without_receipt":
            receipt.unlink()
        else:
            _rebuild_ledger(
                spec, out, lambda kind, p: None if kind == "hosted.dry_receipt.v1" else p
            )
    fake = FakeGemini()
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    monkeypatch.setattr(hosted, "check_environment", lambda *a, **k: ENV)
    files = _snapshot(out)
    for stage in ("rehearsal", "full"):
        with pytest.raises(ContractError, match="dry_incomplete"):
            _paid(spec, out, tmp_path, stage)
    with monkeypatch.context() as keyless:
        keyless.delenv("GEMINI_API_KEY")
        keyless.delenv("MISTRAL_API_KEY")
        with pytest.raises(ContractError, match="dry_incomplete"):
            _dry_again(tmp_path, spec, out)
        capsys.readouterr()
        assert _main(tmp_path, out, "dry") == 2
    for stage in ("rehearsal", "full", "collect", "score"):
        assert _main(tmp_path, out, stage) == 2
    err = capsys.readouterr().err
    assert err.count("dry_incomplete") == 5 and "start a new arm output directory" in err
    assert fake.calls == [] and _snapshot(out) == files


@pytest.mark.parametrize("status", [400, 403, 404, 409])
def test_0j_r2_a_cancel_answering_another_status_is_recorded_once_and_never_posted_again(
    status: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe Q2: only 429 and 5xx are retried; the job stays open at its worst case."""
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini(state="BATCH_STATE_RUNNING")
    posts: list[int] = []

    def refusing(config: Any, method: str, body: Any, headers: Any, **kw: Any) -> Any:
        if method == "POST" and config.endpoint.endswith(":cancel"):
            posts.append(status)
            return status, "application/json", b"{}"
        return fake(config, method, body, headers, **kw)

    monkeypatch.setattr(gemini_api, "request_bytes", refusing)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    assert _paid(spec, out, tmp_path, "rehearsal") == 3
    hosted.Arm(spec, out).stop("some_other_stop")
    for _ in range(4):
        assert _paid(spec, out, tmp_path, "rehearsal") == 3  # still running: pending
    arm = hosted.Arm(spec, out)
    assert posts == [status]
    assert arm.events("hosted.cancel_refused.v1") == [{"job": "batches/b1", "http_status": status}]
    assert arm.events("hosted.job.cancel_requested.v1") == []
    (intent,) = [p for p in arm.events("job.dispatch.intent.v1") if p["provider"] == "gemini_api"]
    assert intent["idempotency_key"] not in hosted._closed(arm)  # its worst case stays reserved
    assert arm.credit is not None
    report: Any = arm.credit.report()
    assert intent["idempotency_key"] in report["reservations"]
    assert intent["idempotency_key"] not in report["settlements"]


def test_0j_r2_a_resume_without_a_key_while_a_batch_runs_cancels_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe Q3: Gemini batch running, Mistral page 2 still to do, the Mistral key removed."""
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini(state="BATCH_STATE_RUNNING")
    script = MistralScript([200, 429])
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", script)
    assert _paid(spec, out, tmp_path, "rehearsal") == 3
    calls = (len(fake.calls), script.calls)
    with monkeypatch.context() as broken:
        broken.delenv("MISTRAL_API_KEY")
        for _ in range(2):
            with pytest.raises(ContractError, match="local refusal"):
                _paid(spec, out, tmp_path, "rehearsal")
    arm = hosted.Arm(spec, out)
    assert (len(fake.calls), script.calls) == calls and fake.cancels() == []
    assert not arm.campaign.stopped
    assert arm.events("hosted.local_refusal.v1") == [
        {"provider": "mistral_ocr_4", "stage": "rehearsal", "reason": "no_key"}
    ]
    fake.state = "BATCH_STATE_SUCCEEDED"
    assert _paid(spec, out, tmp_path, "rehearsal") == 0  # the same command, the key back


def test_0j_r2_collect_of_a_stopped_arm_without_its_key_is_refused_not_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    fake = FakeGemini(state="BATCH_STATE_RUNNING")
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", _mistral_ok)
    monkeypatch.setattr(hosted, "check_environment", lambda *a, **k: ENV)
    assert _paid(spec, out, tmp_path, "rehearsal") == 3
    hosted.Arm(spec, out).stop("some_other_stop")
    calls = len(fake.calls)
    monkeypatch.delenv("GEMINI_API_KEY")
    assert _main(tmp_path, out, "collect") == 2
    arm = hosted.Arm(spec, out)
    assert arm.events("hosted.local_refusal.v1") == [
        {"provider": "gemini_api", "stage": "rehearsal", "reason": "no_key"}
    ]
    assert len(fake.calls) == calls and fake.cancels() == []


def test_0j_r2_a_dry_mistral_list_naming_an_unrendered_page_is_refused_before_any_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    dry = json.loads((out / "dry" / "receipt.json").read_bytes())
    dry["pages"] = [r for r in dry["pages"] if r["page_id"] != "d1.png#0"]  # d1 kept for Mistral
    dry["page_refusals"].append({"page_id": "d1.png#0", "provider": "both", "reason": "x"})
    _rebind_dry(spec, out, dry)
    fake, script = FakeGemini(), MistralScript([])
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", script)
    with pytest.raises(ContractError, match="did not render"):
        _paid(spec, out, tmp_path, "rehearsal")
    arm = hosted.Arm(spec, out)
    assert fake.calls == [] and script.calls == 0
    assert not [p for p in arm.events("campaign.stage_reserved.v1") if p["stage"] == "rehearsal"]


_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=8), inner),
    max_leaves=6,
)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    stage=st.sampled_from(["rehearsal", "full"]),
    key=st.sampled_from(["pages", "page_refusals", "mistral_pages", "admitted"]),
    how=st.sampled_from(["replace", "delete", "append", "extra_mistral_page"]),
    value=_JSON,
)
def test_0j_r2_fuzz_stage_pages_reads_a_malformed_dry_receipt_only_as_a_refusal(
    dried: Path, stage: str, key: str, how: str, value: Any
) -> None:
    """Any shape of the four lists the paid stage reads: a ContractError, or pages that the dry
    plan rendered (each with its image sha256); never a KeyError, TypeError or a default."""
    dry = json.loads((dried / "out" / "dry" / "receipt.json").read_bytes())
    admitted, _ = hosted.page_list(json.loads((dried / "manifest.json").read_bytes())["documents"])
    if how == "replace":
        dry[key] = value
    elif how == "delete":
        del dry[key]
    elif how == "append" and isinstance(dry[key], list):
        dry[key].append(value)
    elif how == "extra_mistral_page":
        dry["mistral_pages"].append(value if isinstance(value, str) else "d9.png#0")
    try:
        pages = hosted.stage_pages(stage, admitted, dry)
    except ContractError:
        return
    for page in (*pages.gemini, *pages.mistral):
        assert isinstance(pages.image_sha256[page.page_id], str)


@pytest.mark.parametrize(
    ("damage", "message"), [(b"[1]", "receipt object"), (b"{not json", "readable receipt")]
)
def test_0j_r2_a_predecessor_receipt_that_is_not_an_object_is_a_refusal(
    damage: bytes, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    _corpus(tmp_path, _docs3())
    out = tmp_path / "out"
    _prepaid(spec, out)
    (out / "prepaid" / "receipt.json").write_bytes(damage)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(ContractError, match=message):
        _dry_again(tmp_path, spec, out)


def test_0j_r2_quarantine_never_overwrites_an_earlier_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec(tmp_path)
    out = _through_dry(tmp_path, spec, monkeypatch)
    arm = hosted.Arm(spec, out)
    secret = os.environ["MISTRAL_API_KEY"]
    planted = out / "rehearsal" / "planted.json"
    planted.parent.mkdir(parents=True, exist_ok=True)
    kept = []
    for n in (1, 2):
        data = json.dumps({"n": n, "raw": base64.b64encode(secret.encode()).decode()}).encode()
        planted.write_bytes(data)
        kept.append(data)
        assert hosted.scan_credentials(arm, [out / "rehearsal"])["hits"]
    quarantined = sorted(p.read_bytes() for p in (out / "quarantine" / "rehearsal").iterdir())
    assert quarantined == sorted(kept) and not planted.exists()


# --- WO-D10-0N: a manifest that fails its schema is refused by every stage ------------------


def _stale_rights(m: dict[str, Any]) -> None:
    rights = m["documents"][0]["rights"]
    rights["retrieved_at"] = rights.pop("recorded_at")


_SCHEMA_BREAKS: dict[str, Any] = {
    "no_profile": lambda m: m.pop("profile"),  # the shape of the stale fixtures
    "stale_rights": _stale_rights,  # their rights record, too
    "unknown_field": lambda m: m.update(note="x"),
    "page_count_text": lambda m: m["documents"][0].update(page_count="1"),
}


@pytest.mark.parametrize("damage", sorted(_SCHEMA_BREAKS))
def test_0n_a_manifest_failing_its_schema_is_refused_by_every_stage_before_any_write(
    damage: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A frozen manifest broken one way, its digest recomputed so that only the schema refuses:
    dry, rehearsal, collect, full and score exit 2, write nothing (no reservation, no ledger
    byte) and send nothing; the intact manifest then runs each stage."""
    spec = _spec(tmp_path)
    good, corpus = _corpus(tmp_path, _docs3())
    broken_manifest = json.loads(good.read_bytes())
    _SCHEMA_BREAKS[damage](broken_manifest)
    body = {k: v for k, v in broken_manifest.items() if k != "manifest_sha256"}
    broken_manifest["manifest_sha256"] = canonical_sha256(body)
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(broken_manifest), encoding="utf-8")
    gold = tmp_path / "gold.json"
    gold.write_text("{}", encoding="utf-8")
    fake, script = FakeGemini(state="BATCH_STATE_RUNNING"), MistralScript([])
    monkeypatch.setattr(gemini_api, "request_bytes", fake)
    monkeypatch.setattr(vlm, "post_bytes", script)
    monkeypatch.setattr(hosted, "check_environment", lambda *a, **k: ENV)
    out = tmp_path / "out"

    def refused(stage: str) -> None:
        files, calls = _snapshot(out), (len(fake.calls), script.calls)
        capsys.readouterr()
        argv = [stage, "--out", str(out), "--spec", str(spec.path), "--manifest", str(broken)]
        argv += ["--corpus-root", str(corpus), "--snapshot-dir", str(tmp_path / "snap")]
        argv += ["--gold", str(gold), "--max-wait", "0", "--interval", "0"]
        assert hosted.main(argv) == 2
        assert "manifest fails its schema" in capsys.readouterr().err
        assert _snapshot(out) == files and (len(fake.calls), script.calls) == calls

    for name in ("GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    _prepaid(spec, out)
    refused("dry")
    hosted.run_dry(spec, out, good, corpus, tmp_path / "snap", environment=lambda: ENV)
    monkeypatch.setenv("GEMINI_API_KEY", _marker())
    monkeypatch.setenv("MISTRAL_API_KEY", _marker("mk"))
    monkeypatch.setenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", ALLOWLIST)
    refused("rehearsal")
    assert not hosted.Arm(spec, out).events("job.dispatch.intent.v1")
    assert _paid(spec, out, tmp_path, "rehearsal") == 3  # the batch runs: a stage in progress
    refused("collect")
    fake.state = "BATCH_STATE_SUCCEEDED"
    assert _paid(spec, out, tmp_path, "rehearsal") == 0
    refused("full")
    assert not [
        p
        for p in hosted.Arm(spec, out).events("campaign.stage_reserved.v1")
        if p["stage"] == "full"
    ]
    assert _paid(spec, out, tmp_path, "full") == 0
    refused("score")
    assert not (out / "score").exists()
