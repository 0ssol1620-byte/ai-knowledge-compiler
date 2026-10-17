"""Every test of the vendor harness runs with the network unplugged."""

from __future__ import annotations

import socket
from typing import NoReturn

import pytest


def _refuse(*_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("network access attempted in an offline vendor-harness test")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
