"""A network kill switch for this study's test suite. INC-V2-100.

Why this exists, in one sentence: mutation-testing `live_cohort_guard` meant
deleting the guard and re-running controls that call the real `run()`, and the
suite then performed real traversals against real endpoints -- exactly the
accident the guard was written to prevent.

The lesson is not "write a better guard". It is that a single layer whose whole
job is to be deleted during mutation testing cannot be the only thing standing
between the suite and the network. This is the second layer, and it is designed
so that removing the first one does not reach the socket:

    test process -> injected fake transport only -> real socket forbidden

It is deliberately independent of `live_cohort_guard`: different module,
different mechanism, different failure mode. `allow_under_test()` does NOT open
this one. A test that genuinely needs a socket has to say so in its own source,
with a marker, which is a visible and reviewable act rather than a side effect
of a helper someone else called.

## What it does and does not cover

Covers: every outbound connection attempted by this process, including ones made
deep inside a library that never asks permission.

Does NOT cover: a subprocess. `git`, for instance, is a separate process with
its own sockets, and nothing here can reach into it. That gap is stated rather
than papered over -- the incident this guards against was in-process, and a
claim of total coverage would be the kind of overreach this study catalogues.

Loopback is allowed. A local fixture server is not the hazard, and blocking it
would push tests toward mocking things they could otherwise exercise honestly.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

_REAL_SOCKET_CONNECT = socket.socket.connect
_REAL_SOCKET_CONNECT_EX = socket.socket.connect_ex
_REAL_CREATE_CONNECTION = socket.create_connection

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", ""})  # noqa: S104

MARKER = "allow_real_network"


class RealNetworkForbidden(RuntimeError):
    """A test tried to open a real socket."""


def _is_loopback(address: Any) -> bool:
    if isinstance(address, tuple) and address:
        return str(address[0]) in _LOOPBACK
    return False


def _refuse(address: Any) -> RealNetworkForbidden:
    host = address[0] if isinstance(address, tuple) and address else address
    return RealNetworkForbidden(
        f"this test tried to open a real socket to {host!r}. The suite is barred "
        "from the network so a deleted or mutated guard cannot reach a live "
        f"endpoint (INC-V2-100). Inject a fake transport, or mark the test "
        f"@pytest.mark.{MARKER} if it genuinely must use one."
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MARKER}: this test genuinely needs a real socket and has been reviewed as such",
    )


@pytest.fixture(autouse=True)
def _forbid_real_network(request: pytest.FixtureRequest) -> Iterator[None]:
    """Autouse, so a test cannot avoid it by not asking for it.

    Patched on the socket CLASS rather than on any HTTP client, because the
    library a future tool reaches for is not knowable from here -- urllib,
    requests, httpx and everything else end at this method.
    """
    if request.node.get_closest_marker(MARKER) is not None:
        yield
        return

    def connect(self: socket.socket, address: Any) -> Any:
        if _is_loopback(address):
            return _REAL_SOCKET_CONNECT(self, address)
        raise _refuse(address)

    def connect_ex(self: socket.socket, address: Any) -> Any:
        if _is_loopback(address):
            return _REAL_SOCKET_CONNECT_EX(self, address)
        raise _refuse(address)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        if _is_loopback(address):
            return _REAL_CREATE_CONNECTION(address, *args, **kwargs)
        raise _refuse(address)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.create_connection = create_connection  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = _REAL_SOCKET_CONNECT  # type: ignore[method-assign]
        socket.socket.connect_ex = _REAL_SOCKET_CONNECT_EX  # type: ignore[method-assign]
        socket.create_connection = _REAL_CREATE_CONNECTION  # type: ignore[assignment]
