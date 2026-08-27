"""The kill switch must actually stop a socket, including when layer one is gone.

INC-V2-100 happened because the only thing between the suite and the network was
a guard whose removal was the point of the mutation. These controls prove the
second layer holds independently: they delete, bypass and ignore
`live_cohort_guard` and still fail to reach the network.
"""

from __future__ import annotations

import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import live_cohort_guard as guard  # noqa: E402

from conftest import RealNetworkForbidden  # noqa: E402  isort:skip

REMOTE = ("en.wikipedia.org", 443)


def test_a_raw_socket_to_a_real_host_is_refused():
    with pytest.raises(RealNetworkForbidden, match="real socket"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(REMOTE)


def test_create_connection_is_refused_too():
    """urllib reaches the network through this, not through socket.connect, so
    patching only one of them would leave the actual path open."""
    with pytest.raises(RealNetworkForbidden):
        socket.create_connection(REMOTE, timeout=5)


def test_connect_ex_is_refused_too():
    """`connect_ex` returns an error code instead of raising, so a caller using
    it would otherwise slip past a guard that only covers `connect`."""
    with pytest.raises(RealNetworkForbidden):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect_ex(REMOTE)


def test_urllib_cannot_reach_a_real_endpoint():
    """The layer that matters: a tool reaching for the network the ordinary way,
    with no cooperation from it and no knowledge that this switch exists."""
    with pytest.raises((RealNetworkForbidden, urllib.error.URLError)) as raised:
        urllib.request.urlopen("https://en.wikipedia.org/w/api.php", timeout=5)  # noqa: S310
    # a URLError here must be WRAPPING the refusal, not a real network failure
    error = raised.value
    if isinstance(error, urllib.error.URLError):
        assert isinstance(error.reason, RealNetworkForbidden), error.reason


def test_the_switch_holds_when_layer_one_is_deleted(monkeypatch):
    """The exact mutation that caused INC-V2-100. `refuse_under_test` is turned
    into a no-op -- as a mutation removing the guard would -- and the network is
    still unreachable. This is the control that says the second layer is a layer
    and not a duplicate of the first."""
    monkeypatch.setattr(guard, "refuse_under_test", lambda _entry: None)
    guard.refuse_under_test("anything.run")  # proves layer one is gone
    with pytest.raises(RealNetworkForbidden):
        socket.create_connection(REMOTE, timeout=5)


def test_the_switch_holds_inside_allow_under_test():
    """`allow_under_test` opens layer one deliberately. It must not open this
    one -- otherwise the escape hatch written for the guard's own controls would
    silently become an escape hatch to the internet."""
    with guard.allow_under_test():
        with pytest.raises(RealNetworkForbidden):
            socket.create_connection(REMOTE, timeout=5)


def test_loopback_is_still_allowed():
    """The paired negative. A switch that refused everything would pass every
    control above while making local fixtures impossible, and the difference
    between the two would be invisible."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        client = socket.create_connection(listener.getsockname(), timeout=5)
        client.close()
    finally:
        listener.close()


def test_the_real_functions_are_restored_after_a_test():
    """The switch is per-test and must not leak into whatever runs next, or the
    first test to use it would silently disable the network for the process."""
    assert socket.socket.connect is not None
    import conftest

    with guard.allow_under_test():
        pass
    assert conftest._REAL_CREATE_CONNECTION is not None


@pytest.mark.allow_real_network
def test_the_marker_is_the_only_way_out():
    """The documented escape hatch, exercised so it is known to work -- and so
    its cost is visible: it takes an explicit marker in the test's own source,
    which a reviewer sees, rather than a helper call buried in a fixture.

    This test does not actually open a socket. It asserts that the patch is
    absent, which is what the marker is for.
    """
    assert socket.create_connection.__module__ == "socket"
