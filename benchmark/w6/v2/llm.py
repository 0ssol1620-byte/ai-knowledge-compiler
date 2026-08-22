"""Minimal OpenRouter chat client for the W6 v2 pilot.

Pins one model id at probe time (preregistered primary + fallback order),
temperature 0 everywhere, retries transient failures, records usage. Never logs
prompt content or the API key.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .credentials import CredentialError, load_openrouter_key

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class ModelProbeError(RuntimeError):
    pass


@dataclass
class UsageLedger:
    calls: int = 0
    hard_failures: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "hard_failures": self.hard_failures,
            "retries": self.retries,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "events": self.events[-200:],
        }


class OpenRouterClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
        max_attempts: int = 4,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout_s = timeout_s
        self._max_attempts = max_attempts
        self.usage = UsageLedger()

    @classmethod
    def probe(
        cls,
        *,
        primary: str,
        fallback_order: list[str],
        environment: dict[str, str] | None = None,
        credential_file=None,
        timeout_s: float = 45.0,
    ) -> tuple["OpenRouterClient", str]:
        """Return (client, pinned_model_id); fallbacks only on auth/model errors."""
        try:
            api_key = load_openrouter_key(environment=environment, credential_file=credential_file)
        except CredentialError as exc:
            raise ModelProbeError(f"credential unavailable: {exc}") from exc
        candidates = [primary, *fallback_order]
        last_error = ""
        for model_id in candidates:
            client = cls(api_key=api_key, model=model_id, timeout_s=timeout_s)
            try:
                client.complete(
                    [{"role": "user", "content": "Reply with the single word: ok"}],
                    max_tokens=5,
                    phase="probe",
                )
                return client, model_id
            except ModelAuthError as exc:
                last_error = f"{model_id}: auth/model error"
                client.usage.events.append({"event": "probe_fallback", "from": model_id})
                continue
            except ModelTransientError as exc:
                # network/429/5xx on the primary is NOT an auth failure: keep it pinned
                if model_id == primary:
                    return client, model_id
                last_error = str(exc)
                continue
        raise ModelProbeError(f"all candidate models failed probe ({last_error})")

    # -- core ---------------------------------------------------------------
    def complete(self, messages: list[dict[str, str]], *, max_tokens: int, phase: str) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        backoffs = [2.0, 4.0, 8.0]
        for attempt in range(1, self._max_attempts + 1):
            self.usage.calls += 1
            started = time.monotonic()
            try:
                response = httpx.post(API_URL, headers=headers, json=payload, timeout=self._timeout_s)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                self._record(phase, attempt, "transport_error", round(time.monotonic() - started, 2))
                if attempt < self._max_attempts:
                    self._sleep(attempt)
                    continue
                self.usage.hard_failures += 1
                raise ModelTransientError(f"{phase}: transport failed after {attempt} attempts") from exc
            if response.status_code in (401, 403) or (
                response.status_code == 400 and "not a valid model" in response.text.lower()
            ):
                self.usage.hard_failures += 1
                raise ModelAuthError(f"{phase}: rejected by provider (status {response.status_code})")
            if response.status_code == 429 or response.status_code >= 500:
                self._record(phase, attempt, f"http_{response.status_code}", round(time.monotonic() - started, 2))
                if attempt < self._max_attempts:
                    self._sleep(attempt)
                    continue
                self.usage.hard_failures += 1
                raise ModelTransientError(f"{phase}: http {response.status_code} after {attempt} attempts")
            if response.status_code != 200:
                self.usage.hard_failures += 1
                raise ModelHardError(f"{phase}: unexpected http {response.status_code}")
            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"] or ""
                usage = body.get("usage", {})
                self.usage.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
                self.usage.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            except (ValueError, KeyError, IndexError) as exc:
                self._record(phase, attempt, "malformed_body", round(time.monotonic() - started, 2))
                if attempt < self._max_attempts:
                    self._sleep(attempt)
                    continue
                self.usage.hard_failures += 1
                raise ModelHardError(f"{phase}: malformed response body") from exc
            self._record(phase, attempt, "ok", round(time.monotonic() - started, 2))
            return content
        self.usage.hard_failures += 1
        raise ModelTransientError(f"{phase}: exhausted attempts")

    def complete_json(self, messages: list[dict[str, str]], *, max_tokens: int, phase: str) -> Any:
        text = self.complete(messages, max_tokens=max_tokens, phase=phase)
        return parse_json_loose(text)

    def _sleep(self, attempt: int) -> None:
        self.usage.retries += 1
        time.sleep(backoff_for(attempt))

    def _record(self, phase: str, attempt: int, outcome: str, seconds: float) -> None:
        self.usage.events.append(
            {"phase": phase, "attempt": attempt, "outcome": outcome, "seconds": seconds}
        )


def backoff_for(attempt: int) -> float:
    table = {0: 0.0, 1: 2.0, 2: 4.0, 3: 8.0}
    return table.get(attempt, 8.0)


def parse_json_loose(text: str) -> Any:
    """Parse JSON out of a model reply that may carry fences or prose."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except ValueError:
            pass
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except ValueError:
            pass
    raise ModelHardError("model did not return parseable JSON")


class ModelAuthError(ModelProbeError):
    pass


class ModelTransientError(RuntimeError):
    pass


class ModelHardError(RuntimeError):
    pass
