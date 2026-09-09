"""Source-bound candidate on the same five spent Apple filings; not a benchmark claim."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research" / "apple_temporal_world_20260908"
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(ROOT / "services" / "core-v3" / "src"))
import run_chain  # noqa: E402
import sec_adapter  # noqa: E402
from akc_core_v3.projection_update import compile_source_bound_update  # noqa: E402
from akc_core_v3.projections import plan_artifacts  # noqa: E402


@pytest.fixture(scope="module")
def parsed() -> dict[str, Any]:
    result = {}
    for filing in run_chain.FILINGS:
        data = (RESEARCH / "sources" / filing.pdf_filename).read_bytes()
        assert hashlib.sha256(data).hexdigest() == filing.pdf_sha256
        result[filing.filing_id] = sec_adapter.parse_filing(
            filing,
            data,
            tenant_id=run_chain.TENANT_ID,
            created_at=run_chain.BUILT_AT,
        )
    assert sum(item.page_count for item in result.values()) == 290
    return result


@pytest.mark.parametrize("chain", ["A", "B"])
def test_source_bound_candidate_equals_full_rebuild_on_apple(
    parsed: dict[str, Any], chain: str
) -> None:
    previous = None
    previous_hashes = {}
    results = []
    if chain == "A":
        steps = [(step, members) for step, _label, members in run_chain.CHAIN_A_STEPS]
        lineage = run_chain.COLLECTION_LINEAGE
    else:
        steps = [(step, (filing_id,)) for step, _label, filing_id in run_chain.CHAIN_B_STEPS]
        lineage = run_chain.source_id(
            tenant_id=run_chain.TENANT_ID,
            connector_type="sec-edgar",
            native_id="cik-0000320193/form-10-q",
        )
    for step, members in steps:
        documents, units, facts = [], [], []
        for filing_id in members:
            item = parsed[filing_id]
            document = sec_adapter.load(
                item, **({"document_id": "apple-form-10-q"} if chain == "B" else {})
            )
            current_units, current_facts = sec_adapter.sec_canonicalise(
                item,
                document,
                lineage_source=lineage if chain == "B" else item.source,
                lineage_title="Apple Inc. Form 10-Q" if chain == "B" else item.filing.title,
                lineage_document_id="apple-form-10-q" if chain == "B" else filing_id,
            )
            documents.append(document)
            units.extend(current_units)
            facts.extend(item.parse_facts)
            facts.extend(current_facts)
        current = sec_adapter.resolve_filing([], documents, units, facts)
        full = plan_artifacts(current).full_rebuild()
        if previous is None:
            previous_hashes = full
        else:
            update = compile_source_bound_update(
                before=previous,
                after=current,
                previous_hashes=previous_hashes,
                source_lineage=lineage,
            )
            assert update.equivalence.equivalent, (chain, step)
            assert update.equivalence.stale_left_behind == (), (chain, step)
            assert update.candidate_hashes == full
            previous_hashes = update.candidate_hashes
            results.append(
                {
                    "chain": chain,
                    "step": step,
                    "rebuilt": len(update.rebuilt),
                    "carried": len(update.carried),
                    "artifacts": len(full),
                    "stale": 0,
                    "equivalent": True,
                    "status": "DEVELOPMENT_CANDIDATE_NOT_PROMOTED",
                }
            )
        previous = current
    assert len(results) == (4 if chain == "A" else 2)
    receipt = os.environ.get("SOURCE_BOUND_APPLE_RECEIPT_DIR")
    if receipt:
        output = Path(receipt).resolve()
        if not output.is_relative_to(ROOT / ".chatgpt2codex"):
            raise ValueError(
                "Candidate receipts may only go to isolated scratch, never frozen evidence"
            )
        output.mkdir(parents=True, exist_ok=True)
        (output / f"chain-{chain.lower()}.json").write_text(
            json.dumps(
                {
                    "confirmatory_eligible": False,
                    "public_claim": False,
                    "scope": (
                        "Same five spent filings; SEC adapter, native-only; "
                        "no publication or customer-data authority"
                    ),
                    "steps": results,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
