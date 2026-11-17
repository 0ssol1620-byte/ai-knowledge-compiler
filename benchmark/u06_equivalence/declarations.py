"""The U06 benchmark's fact-key declaration (WO-D12-13, ADR-010). Benchmark only, sec-fsds only.

The SEC key is our adapter's, built from the filing's fact fields (tag, period end, quarters,
unit; `benchmark/local_public/sec_pairs.py:129`, collision suffix `-l<pre.line>` at :131). No
source document defines it, so the evidence is that line at the commit below plus the Step 0
receipt that measured it on the 100 pairs. A pinned source definition is a production
requirement (WO-D12-14), not this benchmark's. The pattern is imported, never restated here.
"""

from __future__ import annotations

from akc_product_core.fact_keys import (
    SEC_FSDS_COLLISION_SUFFIX,
    SEC_FSDS_KEY_PATTERN,
    FactKeyDeclaration,
)

ASSIGNED_BY = "adapter_from_source_fields"
SEC_PAIRS_COMMIT = "a3e9be639738f242b6529e5aed222122dee1ef8d"
STEP0_RECEIPT = "receipts/WO-D12-12/step0/keyed.json"
STEP0_KEYED_SHA256 = "292ee657498e850785acda46e464f7f24e2d47936bf0d533689d5f0ee00dd83c"

SEC_FSDS = FactKeyDeclaration(
    connector_type="sec-fsds",
    key_pattern=SEC_FSDS_KEY_PATTERN,
    collision_suffix=SEC_FSDS_COLLISION_SUFFIX,
    evidence_ref=(
        f"benchmark/local_public/sec_pairs.py:129-131 @ {SEC_PAIRS_COMMIT}; {STEP0_RECEIPT}; "
        f"assigned_by={ASSIGNED_BY}"
    ),
    evidence_sha256=STEP0_KEYED_SHA256,
)
DECLARATIONS: tuple[FactKeyDeclaration, ...] = (SEC_FSDS,)
