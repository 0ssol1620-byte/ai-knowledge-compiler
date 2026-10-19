"""The four vendor adapters and the D-T-live stub, keyed by ``Adapter.vendor``."""

from __future__ import annotations

from .base import Adapter
from .landingai import LandingAIAdapter
from .llamaparse import LlamaParseAdapter
from .reducto import ReductoAdapter
from .tavonel_live_stub import TavonelLiveStub
from .unstructured import UnstructuredAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    cls.vendor: cls
    for cls in (
        ReductoAdapter,
        LlamaParseAdapter,
        LandingAIAdapter,
        UnstructuredAdapter,
        TavonelLiveStub,
    )
}
