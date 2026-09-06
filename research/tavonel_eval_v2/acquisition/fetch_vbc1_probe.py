#!/usr/bin/env python3
"""Fetch the VBC1 feasibility probe cohort. CPU only, network reads only.

The fetch itself is `fetch_p4i_corpus.main`, called unmodified. Only its inputs
are re-pointed: the source lists, the per-family quota, the output trees and the
receipt stem. Re-implementing the payload, spacing, parse-floor and reason-code
logic here would produce a second acquisition path that *looks* like the first
one — which is exactly how INC-V2-007 and INC-V2-009 happened. One path, four
substitutions, all of them declared below.

The result is a burned cohort. It is written under `raw_vbc1_probe` and
`canonical_vbc1_probe` and carries `burned_after_use`, so it cannot be quietly
merged into a confirmatory acquisition later.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_p4g_corpus as p4g  # noqa: E402
import fetch_p4i_corpus as p4i  # noqa: E402
import sources_p4i as p4i_sources  # noqa: E402
from common import NS, rel  # noqa: E402
from evidence import write_immutable as _write_immutable  # noqa: E402
from sources_vbc1_probe import (  # noqa: E402
    CONSUMPTION_ORDER,
    ECFR_PARTS,
    GIT_REPOSITORIES,
    OVER_SELECTION,
    PROBE,
    PROBE_QUOTA,
    SEC_ISSUERS,
    WIKIPEDIA_ARTICLES,
)

RAW = NS / "artifacts" / "development" / "raw_vbc1_probe"
CANONICAL = NS / "artifacts" / "development" / "canonical_vbc1_probe"
MANIFEST = NS / "artifacts" / "development" / "vbc1_probe_cohort.json"
SOURCES = Path(__file__).resolve().parent / "sources_vbc1_probe.py"
PROTOCOL = NS / "protocols" / "VALUE_BEARING_COHORT_V1.yaml"


def disjoint_from_p4i() -> dict[str, Any]:
    """Overlap is checked, not asserted. A shared lineage would void the probe."""
    overlaps = {
        "git_docs": sorted(
            {r["owner"] + "/" + r["repo"] for r in GIT_REPOSITORIES}
            & {r["owner"] + "/" + r["repo"] for r in p4i_sources.GIT_REPOSITORIES_ALL}
        ),
        "regulation_ecfr": sorted(
            "-".join(pair)
            for pair in (
                {(t, p) for t, p, _ in ECFR_PARTS}
                & {(t, p) for t, p, _ in p4i_sources.ECFR_PARTS_ALL}
            )
        ),
        "encyclopedia_wikipedia": sorted(
            set(WIKIPEDIA_ARTICLES) & set(p4i_sources.WIKIPEDIA_ARTICLES_ALL)
        ),
        "sec_edgar": sorted(
            {cik for _, cik in SEC_ISSUERS} & {cik for _, cik in p4i_sources.SEC_ISSUERS_ALL}
        ),
    }
    return {"overlaps": overlaps, "disjoint": not any(overlaps.values())}


def _install_probe_inputs() -> None:
    """The four substitutions, and nothing else."""
    factor = OVER_SELECTION["factor"]
    p4g._repositories = lambda: GIT_REPOSITORIES
    p4g._parts = lambda: ECFR_PARTS
    p4g._articles = lambda: WIKIPEDIA_ARTICLES
    p4g._issuers = lambda: SEC_ISSUERS
    p4g._quota = lambda family: int(PROBE_QUOTA[family] * factor)


def _relabelled(stem: str, body: dict[str, Any], **kwargs: Any) -> dict[str, str]:
    """Probe receipts never land under a P4i stem."""
    del stem
    return _write_immutable(
        "vbc1-probe-cohort",
        {
            **body,
            "schema": "tavonel.v2.vbc1_probe_cohort_receipt.v1",
            "protocol": "VALUE_BEARING_COHORT_V1",
            "probe": PROBE,
            "sources_declaration": rel(SOURCES),
            "consumption_order": CONSUMPTION_ORDER,
            "freshness": disjoint_from_p4i(),
            "breadth_floor": None,
            "meets_breadth_floor": None,
            "breadth_note": "a probe has no breadth floor; it is a measurement, not a cohort",
        },
        **kwargs,
    )


def main() -> int:
    freshness = disjoint_from_p4i()
    if not freshness["disjoint"]:
        print(json.dumps({"verdict": "REFUSED", "freshness": freshness}, sort_keys=True))
        return 1

    p4i.RAW = RAW
    p4i.CANONICAL = CANONICAL
    p4i.MANIFEST = MANIFEST
    p4i.SOURCES = SOURCES
    # P4i's quota table carries a breadth floor; the probe has none, and 0 says
    # so plainly rather than inventing a threshold a measurement is not held to.
    p4i.FAMILY_QUOTA = {**PROBE_QUOTA, "breadth_floor": 0}
    p4i.ACQUISITION_TARGET = sum(PROBE_QUOTA.values())
    p4i.CONSUMPTION_ORDER = CONSUMPTION_ORDER
    p4i._install_p4i_inputs = _install_probe_inputs
    p4i.write_immutable = _relabelled
    return p4i.main()


if __name__ == "__main__":
    raise SystemExit(main())
