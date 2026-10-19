"""Mocked vendor adapter harness for ``tavonel.vendor_comparison.v1`` (lane AT-2).

COMPETITOR-PROTOCOL-2026-10-17 §4.2-4.4 and §4.7. Every adapter reads documents through an
injected transport; the only transport shipped here replays SYNTHETIC fixtures. Live vendor
execution is refused by ``run.py`` (FD-1 vendor terms, FD-2 keys and spend caps).
"""
