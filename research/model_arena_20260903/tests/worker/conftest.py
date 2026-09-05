"""Worker-test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fake_adapter import RELEASE


@pytest.fixture(scope="session", autouse=True)
def _release_sleeping_adapters() -> Iterator[None]:
    """Wake any adapter still sleeping inside a timed-out ``infer`` call.

    The worker deliberately abandons a timed-out inference thread; without this
    the interpreter would block at exit waiting for it.
    """
    yield
    RELEASE.set()
