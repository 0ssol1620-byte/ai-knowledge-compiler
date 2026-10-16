"""Reject bounded native CIR before the canonical occupied-grid validator."""

from __future__ import annotations

import builtins
import copy

import pytest
from akc_cir.base import canonical_json
from akc_product_core.native_cir import parse_native_request
from akc_product_core.native_facts import NativeFactsDraft, project_native_facts

from .test_product_core_native_cir import _body
from .test_product_core_native_facts import _payload


@pytest.mark.parametrize("entry", ["json", "python", "models"])
@pytest.mark.parametrize("budget", ["cells", "blocks", "bytes"])
def test_draft_native_budget_rejects_before_any_grid_work(monkeypatch, entry, budget) -> None:
    import akc_cir.models as cir_models
    import akc_product_core.native_cir as native

    request = parse_native_request(_body(_payload()))
    draft = project_native_facts(request)
    payload = draft.model_dump(mode="json", by_alias=True, exclude_none=True)
    if entry == "models":
        payload["canonicalDocuments"] = draft.canonical_documents
    calls = []

    def grid_range(*args):
        calls.append(args)
        return builtins.range(*args)

    monkeypatch.setattr(cir_models, "range", grid_range, raising=False)
    monkeypatch.setattr(native, {
        "cells": "MAX_NATIVE_CELLS",
        "blocks": "MAX_NATIVE_BLOCKS",
        "bytes": "MAX_NATIVE_CIR_BYTES",
    }[budget], 1)
    with pytest.raises(ValueError, match={
        "cells": "native cell/grid limit",
        "blocks": "native block limit",
        "bytes": "native CIR byte limit",
    }[budget]):
        if entry == "json":
            NativeFactsDraft.model_validate_json(canonical_json(payload))
        else:
            NativeFactsDraft.model_validate(payload)
    assert calls == [], f"out-of-budget CIR performed {len(calls)} grid-range calls"


@pytest.mark.parametrize("mutation", ["dimensions", "depth", "document-count", "later-document"])
def test_malformed_cir_budget_rejects_before_any_grid_work(monkeypatch, mutation) -> None:
    import akc_cir.models as cir_models

    draft = project_native_facts(parse_native_request(_body(_payload())))
    payload = draft.model_dump(mode="json", by_alias=True, exclude_none=True)
    cir = payload["canonicalDocuments"][0]
    if mutation == "dimensions":
        next(block["table"] for block in cir["blocks"] if "table" in block)["rowCount"] = 100_001
    elif mutation == "depth":
        nested = cir["metadata"]
        for _ in range(33):
            nested["nested"] = {}
            nested = nested["nested"]
    elif mutation == "document-count":
        payload["canonicalDocuments"] *= 17
    else:
        later = copy.deepcopy(cir)
        next(block["table"] for block in later["blocks"] if "table" in block)["rowCount"] = 100_001
        payload["canonicalDocuments"].append(later)

    def forbidden_grid_range(*args):
        pytest.fail("out-of-budget CIR reached the occupied-grid validator")

    monkeypatch.setattr(cir_models, "range", forbidden_grid_range, raising=False)
    with pytest.raises(ValueError, match=r"limit|bounds"):
        NativeFactsDraft.model_validate_json(canonical_json(payload))
