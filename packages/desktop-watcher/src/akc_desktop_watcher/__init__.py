"""akc_desktop_watcher — crash-safe local-folder watcher for AKC collections.

Watches configured roots with watchdog, stabilizes bursts, dedupes by
sha256, journals everything for replay, and emits envelopes compatible with
``collection-event.schema.json`` (event type ``file.discovered.v1``).
"""

from __future__ import annotations

from .config import ConfigError, RootConfig, WatcherConfig
from .events import (
    EVENT_TYPE_FILE_DISCOVERED,
    SCHEMA_VERSION,
    build_discovery_envelope,
    build_event_key,
    deterministic_event_id,
    source_root_id_for,
    validate_envelope,
)
from .journal import DedupEntry, Journal, ReplayResult
from .sink import (
    CallbackEventSink,
    CompositeEventSink,
    EventSink,
    JsonlFileSink,
    SinkDeliveryError,
)
from .watcher import DesktopWatcher, WatcherStats

__version__ = "0.1.0"

__all__ = [
    "EVENT_TYPE_FILE_DISCOVERED",
    "SCHEMA_VERSION",
    "CallbackEventSink",
    "CompositeEventSink",
    "ConfigError",
    "DedupEntry",
    "DesktopWatcher",
    "EventSink",
    "JsonlFileSink",
    "Journal",
    "ReplayResult",
    "RootConfig",
    "SinkDeliveryError",
    "WatcherConfig",
    "WatcherStats",
    "build_discovery_envelope",
    "build_event_key",
    "deterministic_event_id",
    "source_root_id_for",
    "validate_envelope",
]
