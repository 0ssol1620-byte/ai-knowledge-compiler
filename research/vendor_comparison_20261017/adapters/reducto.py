"""D-V-reducto: ``/parse`` defaults, no options, synchronous call.

competitor-protocol-receipts holds Reducto's pricing, terms and blog pages only: no request or
response shape was captured on 2026-10-17, and the protocol forbids fetching one here. This
adapter therefore has no default response shape and refuses to read a response until an arm
pin supplies one taken from a docs receipt (tests use a SYNTHETIC shape). Whether ``/parse``
defaults to r-1 is itself unconfirmed (COMPETITOR-PROTOCOL §9).
"""

from __future__ import annotations

from .base import Adapter


class ReductoAdapter(Adapter):
    vendor = "reducto"
    wire_source = "not captured: no Reducto API docs page in competitor-protocol-receipts"
