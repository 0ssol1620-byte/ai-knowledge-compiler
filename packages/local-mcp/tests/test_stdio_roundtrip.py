"""A real stdio roundtrip: boot the server, speak JSON-RPC to it.

This is the end-to-end proof that the package is an MCP server and not just a
library: a subprocess running `python -m akc_local_mcp` receives an
`initialize` handshake, a `tools/list` request, a `resources/list` request and
one real `tools/call`, and answers every one of them on stdout.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

REQUEST_TIMEOUT_S = 30.0


class _StdoutReader(threading.Thread):
    """Collect stdout lines so the test thread can wait with a timeout."""

    def __init__(self, stream) -> None:  # type: ignore[no-untyped-def]
        super().__init__(daemon=True)
        self._stream = stream
        self.lines: queue.Queue[str | None] = queue.Queue()

    def run(self) -> None:
        try:
            for line in self._stream:
                self.lines.put(line)
        finally:
            self.lines.put(None)

    def next_message(self, timeout: float) -> dict[str, object]:
        line = self.lines.get(timeout=timeout)
        if line is None:
            raise AssertionError("server closed stdout before answering")
        return json.loads(line)  # type: ignore[no-any-return]


@pytest.fixture()
def server_process(fixture_world_state_dir: Path) -> Iterator[_ProcessHarness]:
    harness = _ProcessHarness(world_state_dir=fixture_world_state_dir)
    try:
        yield harness
    finally:
        harness.stop()


class _ProcessHarness:
    def __init__(self, world_state_dir: Path) -> None:
        env = {
            **os.environ,
            "AKC_LOCAL_MCP_WORLD_STATE_DIR": str(world_state_dir),
            "PYTHONIOENCODING": "utf-8",
        }
        self.process = subprocess.Popen(
            [sys.executable, "-m", "akc_local_mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.reader = _StdoutReader(self.process.stdout)
        self.reader.start()
        self._next_id = 0

    def send(self, method: str, params: dict[str, object] | None = None) -> int:
        """Send a request; returns its id."""
        self._next_id += 1
        message: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        return self._next_id

    def notify(self, method: str, params: dict[str, object] | None = None) -> None:
        message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def await_response(self, request_id: int) -> dict[str, object]:
        while True:
            message = self.reader.next_message(timeout=REQUEST_TIMEOUT_S)
            if message.get("id") == request_id:
                return message

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)


def _assert_result(message: dict[str, object]) -> dict[str, object]:
    if "error" in message:
        raise AssertionError(f"server returned an error: {message!r}")
    result = message.get("result")
    assert isinstance(result, dict), f"missing result in {message!r}"
    return result


def test_initialize_tools_list_resources_list_and_one_call(
    server_process: _ProcessHarness,
) -> None:
    # 1. The MCP initialize handshake.
    init_id = server_process.send(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "akc-local-mcp-test", "version": "0.0.0"},
        },
    )
    init_result = _assert_result(server_process.await_response(init_id))

    protocol_info = init_result.get("protocolVersion")
    assert isinstance(protocol_info, str) and protocol_info
    server_info = init_result.get("serverInfo")
    assert isinstance(server_info, dict)
    assert server_info.get("name") == "akc-local-mcp"

    # 2. Tell the server the handshake completed.
    server_process.notify("notifications/initialized")

    # 3. tools/list must expose exactly the read-only surface.
    tools_id = server_process.send("tools/list")
    tools_result = _assert_result(server_process.await_response(tools_id))
    tool_names = sorted(tool["name"] for tool in tools_result["tools"])
    assert tool_names == [
        "ask_as_of",
        "compare_worlds",
        "get_change",
        "get_claim",
        "get_current_truth",
        "get_entity",
        "get_evidence",
        "get_world",
        "search_world",
        "trace_impact",
    ]
    assert len(tool_names) == 10
    for tool in tools_result["tools"]:
        assert tool["inputSchema"]["type"] == "object"

    # 4. resources/list must expose the worlds index; the per-world manifest
    #    is a resource template and shows up under resources/templates/list.
    resources_id = server_process.send("resources/list")
    resources_result = _assert_result(server_process.await_response(resources_id))
    resource_uris = {resource["uri"] for resource in resources_result["resources"]}
    assert "worlds://index" in resource_uris
    templates_id = server_process.send("resources/templates/list")
    templates_result = _assert_result(server_process.await_response(templates_id))
    template_uris = {template["uriTemplate"] for template in templates_result["resourceTemplates"]}
    assert "worlds://{world_id}/manifest" in template_uris

    # 5. A real call: the fixture world answers CURRENT with its claims.
    call_id = server_process.send(
        "tools/call",
        {
            "name": "get_current_truth",
            "arguments": {"topic": "ingest-pipeline"},
        },
    )
    call_result = _assert_result(server_process.await_response(call_id))
    assert call_result.get("isError") in (False, None)
    content = call_result["content"]
    assert isinstance(content, list) and content
    assert content[0]["type"] == "text"
    answer = json.loads(content[0]["text"])
    assert answer["status"] == "CURRENT"
    assert answer["topic"]["topic_id"] == "ingest-pipeline"
    assert answer["world"]["world_id"] == "atlas-demo"


def test_unresolvable_topic_answers_unresolved_over_stdio(
    server_process: _ProcessHarness,
) -> None:
    init_id = server_process.send(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "akc-local-mcp-test", "version": "0.0.0"},
        },
    )
    _assert_result(server_process.await_response(init_id))
    server_process.notify("notifications/initialized")

    call_id = server_process.send(
        "tools/call",
        {
            "name": "search_world",
            "arguments": {"query": "zzz-nothing-matches-this"},
        },
    )
    call_result = _assert_result(server_process.await_response(call_id))
    content = call_result["content"]
    assert isinstance(content, list) and content
    answer = json.loads(content[0]["text"])
    assert answer["status"] == "UNRESOLVED"
    assert answer["reason"]["code"] == "NO_MATCHES"


def test_server_boots_without_a_world_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    harness = _ProcessHarness(world_state_dir=missing)
    try:
        init_id = harness.send(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "akc-local-mcp-test", "version": "0.0.0"},
            },
        )
        _assert_result(harness.await_response(init_id))
        harness.notify("notifications/initialized")
        call_id = harness.send(
            "tools/call",
            {
                "name": "get_current_truth",
                "arguments": {"topic": "anything"},
            },
        )
        call_result = _assert_result(harness.await_response(call_id))
        content = call_result["content"]
        assert isinstance(content, list) and content
        answer = json.loads(content[0]["text"])
        assert answer["status"] == "UNRESOLVED"
        assert answer["reason"]["code"] == "WORLD_STATE_UNAVAILABLE"
    finally:
        harness.stop()
