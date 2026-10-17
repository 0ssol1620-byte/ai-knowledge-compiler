"""Per-vendor price and terms snapshots and their run-time validator (lane AT-3).

COMPETITOR-PROTOCOL-2026-10-17 §2.1-2.2 and §7 AT-3. ``price_snapshot_schema`` loads the
``<vendor>.price_snapshot.json`` files; ``validate`` refuses a run whose snapshot is unbound,
stale (more than 7 days old) or whose terms page changed since the founder's FD-1 decision.
"""
