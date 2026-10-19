"""D-V-unstructured: API default partition strategy (pinned from the response).

Blocked twice over: FD-1, and Platform Terms 3.2(a) takes a perpetual training licence that no
corpus we hold lets us grant (COMPETITOR-PROTOCOL §3). competitor-protocol-receipts holds only
pricing, terms and benchmark pages, so no wire shape was captured: this adapter has no default
response shape and refuses to read a response until a docs-receipt shape is pinned.
"""

from __future__ import annotations

from .base import Adapter


class UnstructuredAdapter(Adapter):
    vendor = "unstructured"
    wire_source = "not captured: no Unstructured API docs page in competitor-protocol-receipts"
