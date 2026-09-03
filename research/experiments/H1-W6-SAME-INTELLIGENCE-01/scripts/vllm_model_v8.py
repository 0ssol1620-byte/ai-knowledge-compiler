#!/usr/bin/env python3
"""The frozen model behind an `arms_v8.AnswerModel`. One contract, four arms.

Everything in here is identical for `RAW`, `BASIC_RAG`, `BASIC_RAG_PLUS` and
`TAVONEL`: the same served checkpoint, the same system contract, the same
decoding, the same parse. **The only thing that differs between arms is the
context string**, which is the variable under test. The fairness contract in
`arms_v8` checks that claim against the configuration this class reports.

**The prompt is frozen before the holdout opens**, and it has to be, because it
is not a neutral detail. `scoring_v8.score_answer` scores an answer correct only
when its normalized token set equals the gold value's exactly, so a model that
replies *"The population was 1,450 as of 2024"* is scored wrong on a question it
answered. That is a property of the frozen scorer, not something to discover
mid-run: the contract therefore asks for the value alone, and asks for one exact
string when the excerpts do not contain it.

**No silent fallback.** A transport error, a refusal, an overlong prompt or an
unparseable body raises. An arm that quietly recorded an abstention on an HTTP
timeout would report a serving failure as a knowledge-representation finding.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

#: Frozen 2026-08-20, before the holdout. Changing either string after holdout
#: numbers are visible would make the run development.
SYSTEM_CONTRACT = (
    "You answer questions using only the source excerpts provided in the message. "
    "Reply with the answer value alone: no sentence, no explanation, no restatement "
    "of the question, and no units or qualifiers unless they appear in the excerpts. "
    "If the excerpts do not contain the answer, reply with exactly "
    "INSUFFICIENT_EVIDENCE and nothing else."
)
USER_TEMPLATE = "Source excerpts:\n{context}\n\nQuestion: {question}\nAnswer:"
ABSTENTION_TOKEN = "INSUFFICIENT_EVIDENCE"  # noqa: S105 - a sentinel string, not a secret

#: Founder decision of 2026-08-20. `tools` is off by construction: this client
#: has no tool definitions to send.
TEMPERATURE = 0.0
MAX_TOKENS = 256
SEED = 0

#: Qwen3.6 emits a reasoning preamble by default. Measured against the live
#: runtime on 2026-08-20, before the freeze: with thinking on, the answer to
#: *"Reply with exactly one word: attested."* was still inside a numbered
#: "Thinking Process" at the 256-token limit; with it off, the same runtime
#: returned `1,450` for a one-fact excerpt in 6 completion tokens.
#:
#: `max_tokens = 256` is a founder decision and is not being reinterpreted. Under
#: that budget, leaving thinking on would measure how far a reasoning preamble
#: gets in 256 tokens --- every arm truncated mid-reasoning, every answer scored
#: as an abstention --- rather than what the four representations supply. The
#: setting is applied identically to all four arms, so it changes the shared model
#: contract and not the variable under test, and it is pinned in the freeze and
#: reported in the results.
CHAT_TEMPLATE_KWARGS = {"enable_thinking": False}

#: Identifies this client to whatever sits between it and the runtime.
USER_AGENT = "TAVONEL-W6-v8/1.0 (research benchmark client)"


class ModelTransportError(RuntimeError):
    """The runtime did not answer. Never converted into an abstention."""


class ContextOverflow(RuntimeError):
    """The served context window rejected the prompt.

    Distinct from `ModelTransportError` because it is a measurable property of
    the run --- under `RAW_GETS_WHOLE_DOCUMENT_BUDGET` it is recorded as
    `RAW_CONTEXT_OVERFLOW` and reported separately, never truncated away.
    """


class VLLMChatModel:
    """OpenAI-compatible chat client against the attested runtime."""

    is_real_model = True

    def __init__(self, *, base_url: str, model_name: str, attestation: dict[str, Any],
                 timeout: float = 1800.0, retries: int = 2) -> None:
        self._base = base_url.rstrip("/")
        self._model = model_name
        self._attestation = attestation
        self._timeout = timeout
        self._retries = retries
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.latency_ms: list[float] = []

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "name": self._model,
            "is_real_model": True,
            "version": self._attestation.get("checkpoint_revision"),
            "revision": self._attestation.get("checkpoint_revision"),
            "serving_runtime": self._attestation.get("serving_runtime"),
            "serving_runtime_version": self._attestation.get("serving_runtime_version"),
            "runtime_image_digest": self._attestation.get("runtime_image_digest"),
            "model_file_manifest_sha256":
                self._attestation.get("model_file_manifest_sha256"),
            "tokenizer_hash": self._attestation.get("tokenizer_hash"),
            "quantization": self._attestation.get("quantization"),
            "model_attestation": self._attestation.get("model_attestation"),
        }

    @property
    def decoding(self) -> dict[str, Any]:
        return {"temperature": TEMPERATURE, "max_tokens": MAX_TOKENS, "tools": "off",
                "seed": SEED, "chat_template_kwargs": dict(CHAT_TEMPLATE_KWARGS),
                "reasoning_preamble": "disabled",
                "reasoning_preamble_reason":
                    "measured on the live runtime before the freeze: with the default "
                    "reasoning preamble on, a 256-token budget ends mid-preamble and "
                    "every arm scores as an abstention. Applied identically to all four "
                    "arms.",
                "system_contract": "identical across RAW, BASIC_RAG, BASIC_RAG_PLUS "
                                   "and TAVONEL"}

    def messages(self, question: str, context: str) -> list[dict[str, str]]:
        """Exposed so a test can assert the arms differ only in `context`."""
        return [{"role": "system", "content": SYSTEM_CONTRACT},
                {"role": "user",
                 "content": USER_TEMPLATE.format(context=context, question=question)}]

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            request = urllib.request.Request(  # noqa: S310
                f"{self._base}/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json",
                         # Runpod's edge rejects urllib's default agent with a 1010.
                         # Naming the client is honest and gets the request through.
                         "User-Agent": USER_AGENT},
                method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")[:2000]
                # A 400 from vLLM on an oversized prompt is a fact about the run,
                # not a transport hiccup, and retrying it would only waste GPU.
                if error.code == 400 and (
                        "maximum context length" in detail
                        or "longer than the maximum" in detail
                        or "context length" in detail):
                    raise ContextOverflow(detail) from error
                last = RuntimeError(f"HTTP {error.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
                last = error
            if attempt < self._retries:
                time.sleep(5 * (attempt + 1))
        raise ModelTransportError(f"the runtime did not answer: {last}")

    def answer(self, question: str, context: str) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "messages": self.messages(question, context),
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "seed": SEED,
            "chat_template_kwargs": dict(CHAT_TEMPLATE_KWARGS),
        }
        started = time.perf_counter()
        response = self._post(payload)
        self.latency_ms.append((time.perf_counter() - started) * 1000)

        usage = response.get("usage") or {}
        self.calls += 1
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)

        try:
            text = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ModelTransportError(f"unparseable completion: {response}"[:2000]) from error
        if text is None:
            raise ModelTransportError("the runtime returned a null completion")

        cleaned = text.strip()
        if cleaned.upper().startswith(ABSTENTION_TOKEN):
            return {"answer": None, "abstained": True, "evidence_present": False,
                    "raw_output": text, "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "finish_reason": (response["choices"][0] or {}).get("finish_reason")}
        return {"answer": cleaned or None, "abstained": not cleaned,
                "evidence_present": bool(cleaned), "raw_output": text,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "finish_reason": (response["choices"][0] or {}).get("finish_reason")}

    def usage_summary(self) -> dict[str, Any]:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens}
