"""The one model surface used by both arms and the judge: ``claude -p --model opus``.

Reuses the Model Arena's Opus subscription lane contract (research/model_arena_20260903/
arena/opus/command.py): stdin prompt delivery, JSON output, Read as the only tool, no
session persistence, no fallback, no API key. The price snapshot is read from the arena's
frozen file so this lane cannot drift to a different list price.

Surface label: ``claude-code-read-tool``. The Read tool lets the model page through the PDF
agentically, so this is NOT the official GDP.pdf "no tools" condition. Every receipt this
module emits carries ``official_comparable=False``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SURFACE = "claude-code-read-tool"
MODEL_ALIAS = "opus"
DECLARED_MODEL = "claude-opus-5"
OPUS5_MODEL_RE = re.compile(r"(?:^|[^a-z0-9])opus[-_.]?5(?:$|[^0-9])", re.IGNORECASE)
AUXILIARY_MODEL_RE = re.compile(r"haiku", re.IGNORECASE)
FORBIDDEN_ARGS = ("--bare", "--fallback-model", "--dangerously-skip-permissions")
PRICE_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1]
    / "model_arena_20260903"
    / "arena"
    / "opus"
    / "price_snapshot.json"
)


def price_snapshot() -> dict[str, Any]:
    return json.loads(PRICE_SNAPSHOT_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class Surface:
    claude_executable: str = "claude"
    effort: str = "high"
    timeout_seconds: int = 900

    def config(self) -> dict[str, Any]:
        """The frozen surface settings, hashed into the run manifest."""
        return {
            "surface": SURFACE,
            "model_alias": MODEL_ALIAS,
            "declared_model": DECLARED_MODEL,
            "effort": self.effort,
            "output_format": "json",
            "permission_mode": "dontAsk",
            "prompt_delivery": "stdin",
            "tools": ["Read"],
            "allowed_tools": ["Read"],
            "no_session_persistence": True,
            "disable_slash_commands": True,
            "strict_mcp_config": True,
            "setting_sources": [],
            "timeout_seconds": self.timeout_seconds,
            "official_comparable": False,
            "official_comparable_reason": (
                "The official condition disables tools; here the Read tool is enabled so the "
                "model can page through the PDF. Judge is Opus, not gemini-3.5-flash."
            ),
        }

    def argv(self, add_dirs: list[Path]) -> list[str]:
        argv = [
            self.claude_executable,
            "-p",
            "--model",
            MODEL_ALIAS,
            "--output-format",
            "json",
            "--permission-mode",
            "dontAsk",
            "--effort",
            self.effort,
            "--no-session-persistence",
            "--disable-slash-commands",
            "--strict-mcp-config",
        ]
        for directory in add_dirs:
            argv += ["--add-dir", str(directory)]
        argv += ["--tools", "Read", "--allowedTools", "Read"]
        assert_no_fallback(argv)
        return argv


def assert_no_fallback(argv: list[str]) -> None:
    """Fail closed if argv could select anything but Opus, or switch to API billing."""
    lowered = [a.lower() for a in argv]
    for bad in FORBIDDEN_ARGS:
        if bad in lowered:
            raise RuntimeError(f"{bad} is forbidden on the subscription lane")
    for i, arg in enumerate(lowered):
        if arg == "--model":
            value = lowered[i + 1] if i + 1 < len(lowered) else ""
            if value != MODEL_ALIAS and not OPUS5_MODEL_RE.search(value):
                raise RuntimeError(f"--model {value!r} is not an Opus 5 model")


# Claude Code's Read tool renders PDF pages with poppler's pdftoppm. The host has xpdf's
# pdftotext only, so without this the model cannot open a single PDF and the native arm would
# score zero for a tooling reason, not a reading one. Portable poppler lives outside every
# repository, next to the evaluation cache.
POPPLER_BIN = Path(r"D:\CodexData\tools\poppler-26.09.0\Library\bin")


def scrub_env() -> dict[str, str]:
    """Child env with any API-key path removed, so the run stays on the OAuth subscription."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    if not (POPPLER_BIN / "pdftoppm.exe").is_file():
        raise RuntimeError(
            f"pdftoppm is missing from {POPPLER_BIN}; the Read tool cannot open PDFs"
        )
    env["PATH"] = str(POPPLER_BIN) + os.pathsep + env.get("PATH", "")
    return env


def attribute_models(payload: dict[str, Any]) -> tuple[str | None, list[str], list[str]]:
    """(primary opus-5 model, auxiliary models, unexpected models) from ``modelUsage``."""
    usage = payload.get("modelUsage")
    reported = sorted(usage) if isinstance(usage, dict) else []
    model = payload.get("model")
    if not reported and isinstance(model, str):
        reported = [model]
    opus5 = [m for m in reported if OPUS5_MODEL_RE.search(m)]
    auxiliary = [m for m in reported if AUXILIARY_MODEL_RE.search(m)]
    unexpected = [m for m in reported if m not in opus5 and m not in auxiliary]
    return (opus5[0] if opus5 else None), auxiliary, unexpected


def _usage_for(payload: dict[str, Any], model: str | None) -> dict[str, Any]:
    source: Any = None
    label = "missing"
    model_usage = payload.get("modelUsage")
    if model and isinstance(model_usage, dict) and isinstance(model_usage.get(model), dict):
        source, label = model_usage[model], "modelUsage"
    elif isinstance(payload.get("usage"), dict):
        source, label = payload["usage"], "usage"
    if source is None:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": None,
            "usage_source": label,
        }

    def pick(*names: str) -> int | None:
        for name in names:
            value = source.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    return {
        "input_tokens": pick("input_tokens", "inputTokens"),
        "output_tokens": pick("output_tokens", "outputTokens"),
        "cache_creation_input_tokens": pick(
            "cache_creation_input_tokens", "cacheCreationInputTokens"
        ),
        "cache_read_input_tokens": pick("cache_read_input_tokens", "cacheReadInputTokens"),
        "usage_source": label,
    }


def api_equivalent_micros(usage: dict[str, Any], prices: dict[str, Any]) -> tuple[int | None, bool]:
    """API-equivalent LIST price in USD micros, and whether it covers every token.

    Never an invoice amount: this run is included in a Claude Max subscription. Cache-token
    prices are null in the arena snapshot, so a run reporting cache tokens is price-incomplete
    rather than silently priced with an invented multiplier.
    """
    p = prices["prices"]
    tokens_in, tokens_out = usage.get("input_tokens"), usage.get("output_tokens")
    if tokens_in is None or tokens_out is None:
        return None, False
    usd = tokens_in / 1e6 * p["input_per_mtok_usd"] + tokens_out / 1e6 * p["output_per_mtok_usd"]
    complete = not (
        usage.get("cache_creation_input_tokens") or usage.get("cache_read_input_tokens")
    )
    return round(usd * 1_000_000), complete


class AuthExpired(RuntimeError):
    """The OAuth subscription is no longer usable; the campaign must stop."""


AUTH_MARKERS = (
    "oauth token has expired",
    "please run /login",
    "invalid api key",
    "authentication_error",
    "credit balance is too low",
)

# A throttle is an OPERATIONAL failure, not a wrong answer, and the constitution keeps the two
# apart. These markers are only ever consulted on a call the CLI itself reported as failed, so a
# document that happens to contain the words "rate limit" cannot be mistaken for one.
RATE_LIMIT_MARKERS = (
    "rate limit",
    "rate_limit",
    "429",
    "too many requests",
    "usage limit",
    "session limit",
    "overloaded",
    "capacity constraints",
)


def looks_rate_limited(blob: str) -> bool:
    lowered = blob.lower()
    return any(marker in lowered for marker in RATE_LIMIT_MARKERS)


def invoke(surface: Surface, prompt: str, add_dirs: list[Path]) -> dict[str, Any]:
    """One ``claude -p`` call. Returns a receipt; never raises for a model-side failure."""
    argv = surface.argv(add_dirs)
    started = time.time()
    monotonic = time.perf_counter()
    try:
        completed = subprocess.run(  # noqa: S603 - argv is built from pinned parts by Surface.argv
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=surface.timeout_seconds,
            env=scrub_env(),
            cwd=str(Path.home()),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "failure": "TIMEOUT",
            "wall_seconds": time.perf_counter() - monotonic,
            "started_at": started,
            "detail": f"exceeded {surface.timeout_seconds}s",
        }
    except OSError as exc:
        return {
            "ok": False,
            "failure": "DEPENDENCY",
            "wall_seconds": time.perf_counter() - monotonic,
            "started_at": started,
            "detail": f"{type(exc).__name__}: {exc}",
        }

    wall = time.perf_counter() - monotonic
    blob = (completed.stdout or "") + (completed.stderr or "")
    lowered = blob.lower()
    if any(marker in lowered for marker in AUTH_MARKERS):
        raise AuthExpired(blob[:2000])

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "failure": "RATE_LIMITED" if looks_rate_limited(blob) else "OUTPUT_MALFORMED",
            "wall_seconds": wall,
            "started_at": started,
            "detail": blob[:2000],
            "returncode": completed.returncode,
        }

    primary, auxiliary, unexpected = attribute_models(payload)
    usage = _usage_for(payload, primary)
    micros, price_complete = api_equivalent_micros(usage, price_snapshot())
    receipt: dict[str, Any] = {
        "ok": True,
        "wall_seconds": wall,
        "started_at": started,
        "reported_model": primary,
        "auxiliary_models": auxiliary,
        "unexpected_models": unexpected,
        "num_turns": payload.get("num_turns"),
        "duration_ms": payload.get("duration_ms"),
        "api_equivalent_list_price_usd_micros": micros,
        "api_equivalent_price_complete": price_complete,
        "actual_marginal_api_cost": "N/A (Claude Max subscription)",
        "text": payload.get("result") if isinstance(payload.get("result"), str) else None,
        **usage,
    }
    text = receipt["text"]
    if primary is None and isinstance(text, str) and looks_rate_limited(text):
        # "You have hit your session limit - resets <time>": the subscription refused the call,
        # so there is no model to attribute and nothing was measured. Operational, not semantic.
        receipt.update(ok=False, failure="RATE_LIMITED", detail=text[:2000])
    elif unexpected:
        receipt.update(ok=False, failure="UNEXPECTED_MODEL", detail=str(unexpected))
    elif primary is None:
        receipt.update(ok=False, failure="UNEXPECTED_MODEL", detail="no Opus 5 model reported")
    elif payload.get("is_error") or receipt["text"] is None:
        detail = str(payload.get("result"))[:2000]
        receipt.update(
            ok=False,
            failure="RATE_LIMITED" if looks_rate_limited(detail) else "OUTPUT_MALFORMED",
            detail=detail,
        )
    return receipt


def demo() -> None:
    s = Surface()
    assert s.argv([Path.home()])[:4] == ["claude", "-p", "--model", "opus"]
    for bad in (["claude", "--model", "sonnet"], ["claude", "--bare", "--model", "opus"]):
        try:
            assert_no_fallback(bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"should have refused {bad}")
    assert "ANTHROPIC_API_KEY" not in scrub_env()
    payload = {
        "modelUsage": {
            "claude-opus-5-20260724": {"input_tokens": 1000, "output_tokens": 200},
            "claude-haiku-4-5-20251001": {"input_tokens": 9, "output_tokens": 1},
        }
    }
    primary, aux, unexpected = attribute_models(payload)
    assert primary == "claude-opus-5-20260724" and aux and not unexpected
    micros, complete = api_equivalent_micros(_usage_for(payload, primary), price_snapshot())
    # 1000 * $5/Mtok + 200 * $25/Mtok = $0.010 = 10_000 micros
    assert (micros, complete) == (10_000, True), (micros, complete)
    assert looks_rate_limited("API Error: 429 Too Many Requests")
    assert looks_rate_limited("You've hit your session limit — resets 12:30am (Asia/Seoul)")
    assert not looks_rate_limited("the policy limits the daily benefit")
    print("surface demo ok")


if __name__ == "__main__":
    demo()
