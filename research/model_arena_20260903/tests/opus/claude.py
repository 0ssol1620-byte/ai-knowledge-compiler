"""A stand-in for the Claude Code CLI, driven entirely by environment variables.

Invoked as ``<python> <this file> <the real argv>`` so no executable bit, no
PATH shim and no shell is needed on Windows. Everything it does is configured by
``FAKE_CLAUDE_*`` variables, which the runner's scrubbed environment would
normally strip -- the tests pass an explicit env that keeps them.

Modes (``FAKE_CLAUDE_MODE``):

``ok``            emit a success payload; the result text is ``FAKE_CLAUDE_RESULT``
``limit``         emit ``is_error`` with usage-limit wording and exit non-zero
``auth_expired``  emit the OAuth-expired failure shape (masterplan 21.8 AUTH_EXPIRED):
                  ``is_error`` true, ``modelUsage`` empty, no model named anywhere
``wrong_model``   emit a success payload attributed to a non-Opus model
``hang``          sleep ``FAKE_CLAUDE_SLEEP`` seconds so the caller's timeout fires
``crash``         write to stderr and exit ``FAKE_CLAUDE_EXIT``
``garbage``       write non-JSON to stdout

Every mode asserts that the child environment is clean: if ``ANTHROPIC_API_KEY``
or ``CLAUDECODE`` reached this process, it exits 90 with a message, which turns
into a visible test failure rather than a silently-passing run.
"""

from __future__ import annotations

import json
import os
import sys
import time

LEAK_EXIT_CODE = 90
FORBIDDEN_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE")


def _leaked() -> list[str]:
    leaked = [name for name in FORBIDDEN_ENV if name in os.environ]
    leaked += [
        name
        for name in os.environ
        if name.startswith("CLAUDE_CODE_") and not name.startswith("CLAUDE_CODE_FAKE")
    ]
    return sorted(set(leaked))


def _usage() -> dict[str, object]:
    return {
        "input_tokens": int(os.environ.get("FAKE_CLAUDE_INPUT_TOKENS", "1200")),
        "output_tokens": int(os.environ.get("FAKE_CLAUDE_OUTPUT_TOKENS", "800")),
        "cache_creation_input_tokens": int(
            os.environ.get("FAKE_CLAUDE_CACHE_WRITE_TOKENS", "0")
        ),
        "cache_read_input_tokens": int(os.environ.get("FAKE_CLAUDE_CACHE_READ_TOKENS", "0")),
    }


def _payload(model: str, *, is_error: bool, result: str) -> dict[str, object]:
    usage = _usage()
    return {
        "type": "result",
        "subtype": "error" if is_error else "success",
        "is_error": is_error,
        "result": result,
        "session_id": "00000000-0000-4000-8000-00000000fake",
        "num_turns": 1,
        "duration_ms": 1234,
        "total_cost_usd": 0.01,
        "usage": usage,
        "modelUsage": {
            "claude-haiku-4-5-20251001": {
                "inputTokens": 100,
                "outputTokens": 5,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
            },
            model: {
                "inputTokens": usage["input_tokens"],
                "outputTokens": usage["output_tokens"],
                "cacheReadInputTokens": usage["cache_read_input_tokens"],
                "cacheCreationInputTokens": usage["cache_creation_input_tokens"],
                "canonicalModel": model,
            },
        },
    }


def main() -> int:
    leaked = _leaked()
    if leaked:
        print(f"FAKE CLAUDE: forbidden environment reached the child: {leaked}", file=sys.stderr)
        return LEAK_EXIT_CODE

    argv = sys.argv[1:]
    if "--version" in argv:
        print(os.environ.get("FAKE_CLAUDE_VERSION", "2.1.252 (Claude Code)"))
        return 0

    record = os.environ.get("FAKE_CLAUDE_RECORD")
    if record:
        stdin_text = "" if sys.stdin is None else sys.stdin.read()
        with open(record, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "argv": argv,
                        "stdin": stdin_text,
                        "cwd": os.getcwd(),
                        "env_names": sorted(os.environ),
                    }
                )
                + "\n"
            )

    mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")

    if mode == "hang":
        time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "30")))
        return 0

    if mode == "crash":
        print(os.environ.get("FAKE_CLAUDE_STDERR", "boom"), file=sys.stderr)
        return int(os.environ.get("FAKE_CLAUDE_EXIT", "1"))

    if mode == "garbage":
        print("this is not json")
        return int(os.environ.get("FAKE_CLAUDE_EXIT", "0"))

    if mode == "auth_expired":
        # Mirrors runs/opus5_subscription/raw/olmocr-bench-83a5e23571dfcfe2482ddf35
        # .claude.json (the 2026-09-04T05:46 attempt): is_error true,
        # terminal_reason api_error, modelUsage empty, no model named anywhere.
        payload = {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "terminal_reason": "api_error",
            "result": os.environ.get(
                "FAKE_CLAUDE_RESULT",
                "Failed to authenticate: OAuth session expired and could not be refreshed",
            ),
            "session_id": "00000000-0000-4000-8000-00000000fake",
            "num_turns": 1,
            "duration_ms": 419,
            "total_cost_usd": 0,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "modelUsage": {},
        }
        print(json.dumps(payload))
        return int(os.environ.get("FAKE_CLAUDE_EXIT", "1"))

    if mode == "limit":
        payload = _payload(
            "claude-opus-5",
            is_error=True,
            result=os.environ.get(
                "FAKE_CLAUDE_RESULT",
                "Claude usage limit reached. Your limit resets at 2026-09-03T18:00:00Z.",
            ),
        )
        print(json.dumps(payload))
        return int(os.environ.get("FAKE_CLAUDE_EXIT", "1"))

    if mode == "wrong_model":
        payload = _payload(
            os.environ.get("FAKE_CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
            is_error=False,
            result=os.environ.get("FAKE_CLAUDE_RESULT", "# Page\n\nSome text.\n"),
        )
        print(json.dumps(payload))
        return 0

    payload = _payload(
        os.environ.get("FAKE_CLAUDE_MODEL", "claude-opus-5"),
        is_error=False,
        result=os.environ.get("FAKE_CLAUDE_RESULT", "# Heading\n\nBody text.\n"),
    )
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
