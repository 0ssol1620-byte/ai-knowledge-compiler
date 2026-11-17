"""Stage S0 driver (WO-D10-0G): one candidate on one pod over the dev pages, then exit.

``python -m benchmark.screen.s0 --candidate-id ... --out DIR`` refuses before any page (exit 2)
when the renderer, the manifest, the reader, the endpoint allow-list, the bearer token, the
gold or the pins of an earlier run in ``DIR`` are not what they must be. It then waits for the
pod: a launch-script failure marker at ``/akc-state`` ends it (exit 3); a server that answers
without the key ends it (exit 2); a chat server that refuses the key is KEY-MISMATCH (exit 3);
no server 45 minutes after the pod was created ends it (exit 3). Then ``run_screen`` runs with
``wrap`` as its call: each page result's text goes through ``normalise_v1`` (the text before
is kept in ``metrics.normaliser``), and its cost is derived from the price stated when the pod
was created and the runner's measured request latency (labelled "not billed"). A text longer
than ``MAX_TEXT_CHARS`` is not normalised: the page is stored as the failure
``output_too_large`` with its length. A runner result that is not an object is stored as the
failure ``runner_result_unshaped`` (a runner error), never handed to ``run_screen``. A pod that is
down (a status that means "no answer from the model") is a retried page, never a stored model
failure; one retry per page, spent in the same run only on a pod that answers healthy, else
kept for the resume. The driver enforces its own deadlines (two hours after creation, checked
before each call and again when it returns; 180 s for the server to go idle after a proxy cut)
and stops after three operational failures in a row (exit 3; resume with the same ``--out`` on
a new pod). A wrong served model, provider, revision or recipe, in a page answer or in a health
answer, is an integrity stop (exit 4). A failure is classed by the selection's one table
(``select_5h``, decision 5H-18), read the way S1 reads it; a token outside that table refuses
the summary (exit 4), never a class of its own. Nothing printed carries page text, a doc id,
gold or a credential: progress lines name the page by its ordinal only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from benchmark.runners.base import (
    PROVIDER_CREDENTIAL,
    RunnerConfig,
    RunnerUnavailable,
    read_credential,
    request_bytes,
)
from benchmark.runners.registry import RUNNER_CONFIGS
from benchmark.runners.vlm import PageRefused, config_sha256
from benchmark.screen import critical_fields
from benchmark.screen.manifest import HoldoutGuard, verify
from benchmark.screen.normalise_v1 import (
    MODULE_SHA256,
    dash_cell_before_number,
    normalise,
    profile_of,
)
from benchmark.screen.run_screen import (
    Candidate,
    ImmutableOutputError,
    _call,
    _case,
    run_screen,
)
from benchmark.screen.select_5h import (
    FAILURE_CLASSES,
    INTEGRITY,
    MECHANICAL,
    OPERATIONAL,
    READER_V1_SHA256,
    failure_class,
)
from benchmark.screen.select_5h import _reason as selection_reason
from benchmark.v6.contracts import ContractError

PYPDFIUM2_VERSION = "4.30.0"
READY_DEADLINE = timedelta(minutes=45)
RUN_DEADLINE = timedelta(hours=2)
POLL_S = 30.0
IDLE_WAIT_S = 180.0
IDLE_POLL_S = 10.0
MAX_ATTEMPTS = 2  # one retry per page (section 5)
MAX_OPERATIONAL_IN_A_ROW = 3
CHAT_PORT, PAGE_PORT = 8000, 8080
# Failure rows the driver writes itself. A page answer longer than this is not normalised: a
# one-page statement is a few thousand characters, and one answer must not hold the run.
MAX_TEXT_CHARS = 2_000_000
OUTPUT_TOO_LARGE = "output_too_large"
UNSHAPED = "runner_result_unshaped"  # the runner returned something that is not an object
COST_KIND = "derived: stated price \N{MULTIPLICATION SIGN} measured request latency; not billed"
EXIT_OK, EXIT_CRASH, EXIT_REFUSED, EXIT_OPERATIONAL, EXIT_INTEGRITY = 0, 1, 2, 3, 4

_MARKER = re.compile(r"FAILED S0-OPERATIONAL-[A-Z-]{1,40}")
_RUNNING = re.compile(
    r"^vllm:num_requests_running(?:\{[^{}\n]{0,1000}\})? ([0-9.eE+-]{1,32})$", re.MULTILINE
)
_POD = re.compile(r"[a-z0-9]{1,64}")
_TOKEN = re.compile(r"[a-z0-9_]{1,64}")

# (method, url, body, headers) -> (status, content type, body)
Request = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, str, bytes]]
Call = Callable[[Candidate, dict[str, Any], Path], dict[str, Any]]


class Exit(Exception):
    """End the driver with ``code``; ``message`` is fixed text, never page or gold content."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _pypdfium2_version() -> str:
    try:
        return importlib.metadata.version("pypdfium2")
    except importlib.metadata.PackageNotFoundError:
        return "absent"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _network(provider: str, revision: str) -> Request:
    def go(method: str, url: str, body: bytes | None, headers: dict[str, str]) -> Any:
        config = RunnerConfig(provider, revision, url, True, timeout_seconds=30)
        return request_bytes(config, method, body, headers, max_response_bytes=1 << 20)

    return go


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _append(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _reason(value: Any) -> str:
    """A failure reason as it may be printed: a fixed token, or ``other``."""
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else "other"


def _zero(value: str) -> bool:
    """A /metrics sample that reads as exactly zero; one that does not parse is not zero."""
    try:
        return float(value) == 0
    except ValueError:
        return False


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m benchmark.screen.s0")
    for name in ("candidate-id", "provider", "revision", "image-digest", "pod-id", "created-utc"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--config-sha256", default=None)
    p.add_argument("--usd-per-hour", required=True, type=float)
    for name in ("manifest", "corpus-root", "gold", "out"):
        p.add_argument(f"--{name}", required=True, type=Path)
    return p.parse_args(argv)


class Driver:
    """Pre-checks, readiness and the per-page ``call`` passed to ``run_screen``."""

    def __init__(
        self,
        args: argparse.Namespace,
        *,
        request: Request | None,
        call: Call,
        now: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self.args, self.inner, self.now, self.sleep = args, call, now, sleep
        self.cid = str(args.candidate_id)
        self.provider = str(args.provider)
        self.kind = "chat" if self.provider in RUNNER_CONFIGS else "page"
        self.out = Path(args.out)
        self.stop: str | None = None  # "operational" or "integrity"
        self.why = ""
        self.in_a_row = 0
        self.attempts: Counter[str] = Counter()
        self.precheck()
        self.request = request or _network(self.provider, self.args.revision)

    # ------------------------------------------------------------ before any page

    def precheck(self) -> None:
        a = self.args
        if _pypdfium2_version() != PYPDFIUM2_VERSION:
            raise Exit(EXIT_REFUSED, f"pypdfium2 must be {PYPDFIUM2_VERSION}")
        if _sha_file(Path(critical_fields.__file__)) != READER_V1_SHA256:
            raise Exit(EXIT_REFUSED, "critical_fields.py is not reader v1")
        if not _POD.fullmatch(a.pod_id):
            raise Exit(EXIT_REFUSED, "pod id must be lowercase letters and digits")
        try:
            created = datetime.fromisoformat(a.created_utc)
        except ValueError:
            raise Exit(EXIT_REFUSED, "created-utc is not an ISO 8601 time") from None
        if created.tzinfo is None:
            raise Exit(EXIT_REFUSED, "created-utc needs a UTC offset")
        self.created = created
        if not (math.isfinite(a.usd_per_hour) and a.usd_per_hour > 0):
            raise Exit(EXIT_REFUSED, "usd-per-hour must be a positive number")
        self.port = CHAT_PORT if self.kind == "chat" else PAGE_PORT
        self.host = f"{a.pod_id}-{self.port}.proxy.runpod.net"
        route = "/v1/chat/completions" if self.kind == "chat" else "/parse"
        self.endpoint = f"https://{self.host}{route}"
        try:
            profile_of(self.provider)
        except ValueError:
            raise Exit(EXIT_REFUSED, "no normaliser profile for this provider") from None
        if self.kind == "chat":
            if a.config_sha256 is not None:
                raise Exit(EXIT_REFUSED, "a chat candidate's config digest comes from its runner")
            try:
                pinned = RUNNER_CONFIGS[self.provider](revision=a.revision)
            except RunnerUnavailable:
                raise Exit(EXIT_REFUSED, "the runner refused the revision") from None
            config, self.served = config_sha256(pinned), str(pinned["served_model_name"])
        else:
            if a.config_sha256 is None:
                raise Exit(EXIT_REFUSED, "a page-server candidate needs --config-sha256")
            config = str(a.config_sha256)
        self.candidate = Candidate(
            candidate_id=self.cid,
            provider=self.provider,
            revision=a.revision,
            image_digest=a.image_digest,
            config_sha256=config,
            endpoint=self.endpoint,
            allow_network=True,
        )
        try:
            self.candidate.validate()
        except Exception as exc:
            raise Exit(EXIT_REFUSED, f"candidate refused ({type(exc).__name__})") from None
        try:
            manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
            verify(manifest, Path(a.corpus_root))
        except Exception as exc:  # the message may name a document: print the type only
            raise Exit(EXIT_REFUSED, f"manifest verify failed ({type(exc).__name__})") from None
        self.guard = HoldoutGuard(manifest, self.out / "holdout-access.jsonl")
        allow = {
            h.strip().lower()
            for h in os.getenv("AKC_BENCHMARK_ENDPOINT_ALLOWLIST", "").split(",")
            if h.strip()
        }
        if allow != {self.host}:
            raise Exit(EXIT_REFUSED, "AKC_BENCHMARK_ENDPOINT_ALLOWLIST must be exactly the host")
        token = read_credential(PROVIDER_CREDENTIAL, self.endpoint)
        if token is None:
            raise Exit(EXIT_REFUSED, f"{PROVIDER_CREDENTIAL} is not set")
        self.auth = {"Authorization": f"Bearer {token}"}
        self.gold = self._gold(Path(a.gold))
        self.out.mkdir(parents=True, exist_ok=True)
        pins = {
            "candidate_id": self.cid,
            "provider": self.provider,
            "revision": a.revision,
            "image_digest": a.image_digest,
            "config_sha256": config,
            "normaliser_sha256": MODULE_SHA256,
        }
        run_file = self.out / "s0-run.json"
        if run_file.is_file():
            if json.loads(run_file.read_text(encoding="utf-8")) != pins:
                raise Exit(EXIT_REFUSED, "out holds a run with other pins; use a new --out")
        else:
            _atomic_write(run_file, (json.dumps(pins, indent=2, sort_keys=True) + "\n").encode())
        self.transport = self.out / "transport.jsonl"
        if self.transport.is_file():
            for line in self.transport.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.attempts[json.loads(line)["case"]] += 1
        docs = self.guard.load("dev", "tune")
        self.case_of = {
            f"{d['doc_id']}#{p}": _case(d, p)["benchmark_case_id"]
            for d in docs
            for p in range(d["page_count"])
        }
        self.ordinal = {c: i for i, c in enumerate(self.case_of.values(), 1)}
        _append(
            self.out / "attempts.jsonl",
            {
                "pod_id": a.pod_id,
                "usd_per_hour": a.usd_per_hour,
                "created_utc": self.created.isoformat(),
                "started_utc": self.now().isoformat(),
            },
        )

    @staticmethod
    def _gold(path: Path) -> dict[str, dict[str, Any]]:
        gold: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                page_id, truth = row["page_id"], row["truth"]
            except (ValueError, KeyError, TypeError):
                raise Exit(EXIT_REFUSED, "a gold row is not {page_id, truth}") from None
            if not isinstance(page_id, str) or not isinstance(truth, dict):
                raise Exit(EXIT_REFUSED, "a gold row is not {page_id, truth}")
            if page_id in gold:
                raise Exit(EXIT_REFUSED, "gold has a duplicate page_id")
            gold[page_id] = truth
        return gold

    # ------------------------------------------------------------ the pod

    def _get(self, path: str, *, auth: bool) -> tuple[int, str, bytes]:
        try:
            return self.request(
                "GET", f"https://{self.host}{path}", None, self.auth if auth else {}
            )
        except RunnerUnavailable:
            return 0, "", b""

    def _json(self, body: bytes) -> Any:
        """The pod's JSON, or None for anything that does not parse (bad UTF-8, too deep)."""
        try:
            return json.loads(body)
        except (ValueError, RecursionError):
            return None

    def _models(self, body: bytes) -> list[Any] | None:
        """The model ids a /v1/models answer lists, or None when it is not a listing."""
        listing = self._json(body)
        data = listing.get("data") if isinstance(listing, dict) else None
        if not isinstance(data, list):
            return None
        return [m["id"] if isinstance(m, dict) and "id" in m else None for m in data]

    def _served(self, body: bytes) -> bool:
        """A /v1/models listing names the pinned served model."""
        return self.served in (self._models(body) or [])

    def _health(self) -> dict[str, Any] | None:
        """The page server's /health, or None when no answer parses as one. An answer that
        names another provider or revision (or none) is an integrity stop, and None."""
        status, _, body = self._get("/health", auth=False)
        health = self._json(body) if status == 200 else None
        if not isinstance(health, dict):
            return None
        if (health.get("provider"), health.get("model_revision")) != (
            self.provider,
            self.args.revision,
        ):
            self._halt("integrity", "the page server names another provider or revision")
            return None
        return health

    def _healthy(self) -> bool:
        """The pod still serves the pinned model: checked before a page spends its retry. No
        answer is operational; an answer that names another served model, provider or revision
        is an integrity stop (exit 4)."""
        if self.kind == "chat":
            status, _, body = self._get("/v1/models", auth=True)
            models = self._models(body) if status == 200 else None
            if models is not None and self.served not in models:
                self._halt("integrity", "the server lists another served model")
            return models is not None and self.served in models
        health = self._health()
        return health is not None and health.get("ready") is True

    def wait_ready(self) -> None:
        while True:
            if self.now() >= self.created + READY_DEADLINE:
                raise Exit(EXIT_OPERATIONAL, "not ready 45 min after pod creation")
            status, _, body = self._get("/akc-state", auth=False)
            marker = body.decode("utf-8", "replace").strip() if status == 200 else ""
            if _MARKER.fullmatch(marker):
                raise Exit(EXIT_OPERATIONAL, marker)
            if self._ready():
                return
            self.sleep(POLL_S)

    def _ready(self) -> bool:
        if self.kind == "chat":
            status, _, _ = self._get("/v1/models", auth=False)
            if status == 200:
                raise Exit(EXIT_REFUSED, "the server answered /v1/models without the key")
            if status != 401:
                return False
            status, _, body = self._get("/v1/models", auth=True)
            if status == 401:
                raise Exit(EXIT_OPERATIONAL, "KEY-MISMATCH")
            if status != 200:
                return False
            if not self._served(body):
                raise Exit(EXIT_REFUSED, "the server does not serve the pinned revision")
            return True
        status, _, body = self._get("/health", auth=False)
        health = self._json(body) if status == 200 else None
        if not isinstance(health, dict):
            return False
        if (health.get("provider"), health.get("model_revision")) != (
            self.provider,
            self.args.revision,
        ):
            raise Exit(EXIT_REFUSED, "the page server names another provider or revision")
        if health.get("ready") is not True:
            return False
        try:
            status, _, _ = self.request("POST", f"https://{self.host}/parse", b"", {})
        except RunnerUnavailable:
            return False
        if status != 401:
            raise Exit(EXIT_REFUSED, "the page server accepted a request without the key")
        return True

    def _idle(self) -> bool:
        """After a proxy cut: wait until vLLM runs no request, at most IDLE_WAIT_S."""
        deadline = self.now() + timedelta(seconds=IDLE_WAIT_S)
        while True:
            status, _, body = self._get("/metrics", auth=True)
            if status == 200:
                found = _RUNNING.findall(body.decode("utf-8", "replace"))
                if found and all(_zero(v) for v in found):
                    return True
            if self.now() >= deadline:
                return False
            self.sleep(IDLE_POLL_S)

    # ------------------------------------------------------------ one page

    def _halt(self, kind: str, why: str) -> None:
        if self.stop != "integrity":
            self.stop, self.why = kind, why

    def _log(
        self, n: int, what: str, latency: Any = None, cost: Any = None, res: Any = None
    ) -> None:
        def show(v: Any, fmt: str) -> str:
            return format(v, fmt) if isinstance(v, int | float) else "-"

        total = len(self.ordinal)
        print(
            f"S0 {self.cid} page {n}/{total} {what} latency={show(latency, '.0f')} "
            f"cost={show(cost, '.6f')} residual={show(res, 'd')}",
            flush=True,
        )

    def _attempt(self, case_id: str, outcome: str) -> None:
        self.attempts[case_id] += 1
        _append(
            self.transport,
            {
                "case": case_id,
                "outcome": outcome,
                "pod_id": self.args.pod_id,
                "utc": self.now().isoformat(),
            },
        )

    def _unavailable(self, n: int, case_id: str) -> None:
        self._attempt(case_id, "unavailable")
        self._log(n, "unavailable")
        self.in_a_row += 1
        if self.in_a_row >= MAX_OPERATIONAL_IN_A_ROW:
            self._halt("operational", "three operational failures in a row")

    def _row(self, case_id: str, reason: str, metrics: dict[str, Any]) -> dict[str, Any]:
        """A failure row the driver writes itself, shaped like the runners' own rows."""
        return {
            "schema_version": "1.0",
            "benchmark_case_id": case_id,
            "provider": self.provider,
            "model_revision": self.args.revision,
            "failure": {"reason": reason},
            "metrics": metrics,
            "receipt": {"revision_attested": False},
        }

    def _deadline(self) -> None:
        if self.stop is None and self.now() >= self.created + RUN_DEADLINE:
            self._halt("operational", "two hours after pod creation")

    def __call__(
        self, candidate: Candidate, case: dict[str, Any], corpus_root: Path
    ) -> dict[str, Any]:
        try:
            return self._page(candidate, case, corpus_root)
        finally:  # checked again when the page returns: a slow page stops the run at once
            self._deadline()

    def _page(
        self, candidate: Candidate, case: dict[str, Any], corpus_root: Path
    ) -> dict[str, Any]:
        case_id = case["benchmark_case_id"]
        n = self.ordinal.get(case_id, 0)
        self._deadline()
        if self.stop is not None:
            raise RunnerUnavailable("S0 stopped; page not sent")
        if self.attempts[case_id] >= MAX_ATTEMPTS:
            raise RunnerUnavailable("page already had its retry")
        try:
            result: object = self.inner(candidate, case, corpus_root)  # typed, not trusted
        except PageRefused as refused:  # decided before any call; a record of its own
            self._log(n, f"failure:{_reason(refused.reason)}")
            raise
        except RunnerUnavailable:
            self._unavailable(n, case_id)
            if self.kind == "page":
                health = self._health()
                if health is not None and health.get("ready") is False:
                    self._halt("operational", "page server reports ready false")
            raise
        except Exception:
            self._attempt(case_id, "error")
            self._log(n, "failure:provider_error")
            self.in_a_row = 0
            raise
        if not isinstance(result, dict):  # never handed on: everything after reads an object
            self.in_a_row = 0
            self._attempt(case_id, UNSHAPED)
            self._log(n, f"failure:{UNSHAPED}")
            return self._row(case_id, UNSHAPED, {"result_type": type(result).__name__})
        failure = result.get("failure")
        reason = _reason(failure.get("reason")) if isinstance(failure, dict) else None
        if reason in INTEGRITY:  # 5H-19: halted on, never stored
            self._attempt(case_id, reason)
            self._halt("integrity", "the server answered with another served model")
            raise RunnerUnavailable("served model differs; not stored")
        if self.kind == "chat" and reason in OPERATIONAL:  # a pod that is down, not an answer
            self._unavailable(n, case_id)
            raise RunnerUnavailable("pod answered with an unavailable status; not stored")
        if self.kind == "page":
            runtime = result.get("metrics")
            if reason:
                receipt = result.get("receipt")
            else:
                receipt = runtime.get("receipt") if isinstance(runtime, dict) else None
            recipe = receipt.get("recipe") if isinstance(receipt, dict) else None
            got = recipe.get("sha256") if isinstance(recipe, dict) else None
            attested = isinstance(receipt, dict) and receipt.get("revision_attested") is True
            if f"sha256:{got}" != self.candidate.config_sha256 or (reason is None and not attested):
                self._attempt(case_id, "integrity")
                self._halt("integrity", "the page server's recipe or attestation differs")
                raise RunnerUnavailable("recipe differs; not stored")
        self.in_a_row = 0
        if reason is not None:
            self._attempt(case_id, reason)
            self._log(n, f"failure:{reason}")
            if reason == "http_524" and self.kind == "chat" and not self._idle():
                self._halt("operational", "server not idle 180 s after a proxy cut")
            return result
        return self._finish(n, case_id, result)

    def _finish(self, n: int, case_id: str, result: dict[str, Any]) -> dict[str, Any]:
        text, metrics = result.get("text"), result.get("metrics")
        if not isinstance(text, str) or not isinstance(metrics, dict):
            self._attempt(case_id, "unshaped")
            self._log(n, "failure:unshaped")
            return result  # run_screen records contract_failed
        latency = metrics.get("latency_ms")
        if not (
            isinstance(latency, int | float)
            and not isinstance(latency, bool)
            and math.isfinite(latency)
            and latency >= 0
        ):
            latency = None  # a measurement or nothing: nan and inf fail it
        if len(text) > MAX_TEXT_CHARS:  # not normalised; a failed page, stored, never retried
            self._attempt(case_id, OUTPUT_TOO_LARGE)
            self._log(n, f"failure:{OUTPUT_TOO_LARGE}")
            kept: dict[str, float] = {"text_chars": len(text)}
            if latency is not None:  # the pod's time was spent: cost attribution needs it
                kept["latency_ms"] = latency
            return self._row(case_id, OUTPUT_TOO_LARGE, kept)
        normalised, residual = normalise(self.provider, text)
        metrics = {
            **metrics,
            "normaliser": {
                "profile": profile_of(self.provider),
                "module_sha256": MODULE_SHA256,
                "text_before": text,
                "residual": residual,
            },
        }
        cost = None
        if latency is not None:
            cost = self.args.usd_per_hour * latency / 3.6e6
            metrics["estimated_cost_usd"] = cost
            metrics["cost_basis"] = {
                "kind": COST_KIND,
                "usd_per_hour": self.args.usd_per_hour,
                "pod_id": self.args.pod_id,
            }
        self._attempt(case_id, "ok")
        self._log(n, "ok", latency, cost, residual)
        return {**result, "text": normalised, "metrics": metrics}

    # ------------------------------------------------------------ the run

    def run(self) -> int:
        records: list[dict[str, Any]] = []
        for attempt in range(MAX_ATTEMPTS):  # a second pass gives an unavailable page its retry
            if attempt and not self._healthy():  # a dead pod would spend it: keep it for resume
                self._halt("operational", "pod not healthy before the retry pass")
                break
            records = run_screen(
                guard=self.guard,
                split="dev",
                purpose="tune",
                candidate=self.candidate,
                corpus_root=Path(self.args.corpus_root),
                gold=self.gold,
                raw_dir=self.out / "raw",
                records_path=self.out / "records.jsonl",
                call=self,
            )
            retry = [
                r
                for r in records
                if r["raw_sha256"] is None
                and self.attempts[self.case_of[r["page_id"]]] < MAX_ATTEMPTS
                and {"provider_unavailable", "provider_error"} & set(r["hard_failures"])
            ]
            if self.stop is not None or not retry:
                break
        if self.stop == "integrity":
            raise Exit(EXIT_INTEGRITY, self.why)
        if self.stop == "operational":
            raise Exit(EXIT_OPERATIONAL, self.why)
        for r in records:
            if r["raw_sha256"] is not None and _sha_file(self._raw(r)) != r["raw_sha256"]:
                raise Exit(EXIT_INTEGRITY, "a raw output differs from its record")
        summary = self.summary(records)  # refuses first: no final records without a summary
        body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)
        _atomic_write(self.out / "final-records.jsonl", body.encode("utf-8"))
        _atomic_write(
            self.out / "s0-summary.json",
            (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode(),
        )
        print(
            f"S0 {self.cid} done pages={summary['pages']} accepted={summary['accepted']}",
            flush=True,
        )
        return EXIT_OK

    def _raw(self, record: dict[str, Any]) -> Path:
        return self.out / "raw" / (str(record["record_key"]).removeprefix("sha256:") + ".json")

    def summary(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        classes = dict.fromkeys(FAILURE_CLASSES, 0)
        reasons: Counter[str] = Counter()
        flags: Counter[str] = Counter()
        residual = dash_pages = 0
        for r in records:
            try:  # S1's own reading of the page (5H-18): the same table, refused alike
                reason = selection_reason(r, self.out / "raw")
            except ContractError:  # its message may name a document: fixed text only
                raise Exit(
                    EXIT_INTEGRITY, "a record's failure is not one the 5H-18 table classes"
                ) from None
            if reason is not None:
                reasons[reason] += 1
                classes[str(failure_class(reason))] += 1
                continue
            flags.update(r["hard_failures"])  # score flags: reported, never a failure
            raw = json.loads(self._raw(r).read_bytes())
            norm = (raw.get("metrics") or {}).get("normaliser")
            if isinstance(norm, dict) and isinstance(norm.get("residual"), int):
                residual += norm["residual"]
            dash_pages += dash_cell_before_number(raw["text"])  # validated output: a str
        tried: Counter[str] = Counter()
        if self.transport.is_file():
            for line in self.transport.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    tried[json.loads(line)["case"]] += 1
        costs = [r["provider_cost_usd"] for r in records if r["provider_cost_usd"] is not None]
        return {
            "candidate_id": self.cid,
            "pins": json.loads((self.out / "s0-run.json").read_text(encoding="utf-8")),
            "pages": len(records),
            "accepted": sum(1 for r in records if r["accepted"]),
            "failure_classes": classes,
            "failure_reasons": dict(sorted(reasons.items())),
            # 5H-12/5H-18's mechanical rejection count: a candidate is out above 20 of 99 pages
            "mechanical": {
                "classes_counted": list(MECHANICAL),
                "pages": sum(classes[k] for k in MECHANICAL),
            },
            "score_flags_not_failures": dict(sorted(flags.items())),
            "attempts": sum(tried.values()),
            "retries": sum(c - 1 for c in tried.values() if c > 1),
            "cost": {
                "kind": COST_KIND,
                "pages_with_cost": len(costs),
                "mean_usd_per_page": sum(costs) / len(costs) if costs else None,
            },
            "normaliser": {
                "profile": profile_of(self.provider),
                "module_sha256": MODULE_SHA256,
                "residual_sum": residual,
                # decision D: a dash-only cell is never joined to the number after it; pages
                # where one is, read from the normalised text only (no gold)
                "dash_cell_before_number_pages": dash_pages,
            },
        }


def main(
    argv: list[str] | None = None,
    *,
    request: Request | None = None,
    call: Call = _call,
    now: Callable[[], datetime] = _utcnow,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = parse_args(argv)
    try:
        driver = Driver(args, request=request, call=call, now=now, sleep=sleep)
        driver.wait_ready()
        return driver.run()
    except Exit as stop:
        print(f"S0 {args.candidate_id} exit {stop.code}: {stop}", flush=True)
        return stop.code
    except ImmutableOutputError:
        print(
            f"S0 {args.candidate_id} exit {EXIT_INTEGRITY}: stored raw output changed", flush=True
        )
        return EXIT_INTEGRITY
    except Exception as exc:  # the message may quote a document: the type only
        print(f"S0 {args.candidate_id} exit {EXIT_CRASH}: crash {type(exc).__name__}", flush=True)
        return EXIT_CRASH


if __name__ == "__main__":
    sys.exit(main())
