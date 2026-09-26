"""A CPU-only stand-in for a real model adapter.

Behaviour is driven entirely by ``runtime.json``'s ``inference_config``: every
key prefixed ``fake_`` becomes a knob (``fake_delay_seconds``,
``fake_error_class``, ``fake_load_error``, ``fake_text``, ...). A request may
override any of them through ``metadata["fake"]``, which lets one running
server exercise several failure paths.

Nothing here touches a GPU, the network, or a benchmark sample.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from arena.worker.adapter_api import (
    AdapterConfig,
    AdapterError,
    LoadReceipt,
    PageInput,
    RawOutput,
    WarmupReceipt,
)

# Tests set this to release an adapter that is sleeping inside ``infer`` so a
# timed-out worker thread does not outlive the test session.
RELEASE = threading.Event()

ZERO_MANIFEST = "sha256:" + "0" * 64


class FakeAdapter:
    """Implements ``arena.worker.adapter_api.ArenaModelAdapter``."""

    model_key = "fake"

    def __init__(self) -> None:
        self.config: AdapterConfig | None = None
        self.infer_calls = 0
        self.load_calls = 0
        self.warmup_calls = 0
        self.closed = False
        self._behaviour: dict[str, Any] = {}

    # -- lifecycle ---------------------------------------------------------

    def load(self, cfg: AdapterConfig) -> LoadReceipt:
        self.config = cfg
        self.model_key = cfg.model_key
        self.load_calls += 1
        self._behaviour = {
            key[len("fake_") :]: value
            for key, value in cfg.inference_config.items()
            if key.startswith("fake_")
        }
        # ARENA_CONTRACT 11.5 D19: a runtime whose entrypoint starts a local
        # model server answers connection-refused until the weights are in.
        refusals = int(self._behaviour.get("load_refusals") or 0)
        if self.load_calls <= refusals:
            raise ConnectionRefusedError(
                111, f"fake model server not up yet (attempt {self.load_calls}/{refusals})"
            )
        load_error = self._behaviour.get("load_error")
        if load_error:
            raise AdapterError(str(load_error), "fake adapter was configured to fail on load")
        revision = str(self._behaviour.get("load_revision") or cfg.model_revision)
        return LoadReceipt(
            model_key=cfg.model_key,
            model_repo=cfg.model_repo,
            model_revision=revision,
            weights_sha256_manifest=ZERO_MANIFEST,
            load_ms=7,
            cache_hit=False,
            runtime_provenance={
                "backend": "fake",
                "prompt_id": cfg.prompt_id,
                "prompt_chars": len(cfg.prompt_text),
                "inference_config_sha256": cfg.inference_config_sha256,
                "weights_dir": str(cfg.weights_dir),
            },
        )

    def warmup(self, synthetic_image: Path) -> WarmupReceipt:
        self.warmup_calls += 1
        refusals = int(self._behaviour.get("warmup_refusals") or 0)
        if self.warmup_calls <= refusals:
            raise ConnectionRefusedError(
                111, f"fake model server still loading (attempt {self.warmup_calls}/{refusals})"
            )
        if not synthetic_image.is_file():
            raise AdapterError("MODEL_LOAD", f"warm-up image missing: {synthetic_image}")
        if synthetic_image.stat().st_size <= 0:
            raise AdapterError("MODEL_LOAD", "warm-up image is empty")
        return WarmupReceipt(
            warmup_ms=3,
            output_chars=64,
            schema_valid=not bool(self._behaviour.get("warmup_invalid")),
            peak_vram_mb=1024,
        )

    # -- inference ---------------------------------------------------------

    def infer(self, page: PageInput) -> RawOutput:
        self.infer_calls += 1
        behaviour = dict(self._behaviour)
        override = page.metadata.get("fake")
        if isinstance(override, Mapping):
            behaviour.update({str(key): value for key, value in override.items()})

        delay = float(behaviour.get("delay_seconds") or 0.0)
        if delay > 0:
            RELEASE.wait(delay)

        error_class = behaviour.get("error_class")
        if error_class:
            raise AdapterError(
                str(error_class), str(behaviour.get("error_message") or "fake adapter failure")
            )
        if behaviour.get("raise_plain_exception"):
            raise ValueError("fake adapter raised a non-AdapterError")
        if not page.image_path.is_file():
            raise AdapterError("PREPROCESS", f"page image missing: {page.image_path}")

        text = str(
            behaviour.get("text")
            or f"# {page.case_key}\n\nfake transcription of {page.sample_id}\n"
        )
        warnings = tuple(str(item) for item in (behaviour.get("warnings") or ()))
        semantic = behaviour.get("semantic_error_class")
        return RawOutput(
            raw_text=text,
            output_format="markdown",
            native_json={"case_key": page.case_key, "chars": len(text)},
            usage={"input_tokens": 11, "output_tokens": len(text)},
            timings_ms={
                "preprocess_ms": 1,
                "inference_ms": max(1, int(delay * 1000)),
                "postprocess_ms": 1,
            },
            peak_vram_mb=2048,
            first_token_at=None,
            warnings=warnings,
            semantic_error_class=None if semantic is None else str(semantic),
        )

    def runtime_provenance(self) -> Mapping[str, Any]:
        return {"backend": "fake", "fake_adapter": True, "infer_calls": self.infer_calls}

    def close(self) -> None:
        self.closed = True


def create_adapter() -> FakeAdapter:
    return FakeAdapter()
