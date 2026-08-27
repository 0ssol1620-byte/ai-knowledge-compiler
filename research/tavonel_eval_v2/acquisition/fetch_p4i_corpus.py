#!/usr/bin/env python3
"""Build the P4i cohort. CPU only, network reads only, nothing published.

The four selectors are P4g's, imported and re-pointed at P4i's declared lists
through the seams that module already exposes (``_repositories``, ``_parts``,
``_articles``, ``_issuers``, ``_quota``). Rewriting them here would be a second
selector pretending to be the same one — the mistake INC-V2-007 and INC-V2-009
were both caused by.

Two things are new, and both come from INC-V2-016:

* each family **over-selects** to 1.5x its quota and the admitted list is
  truncated at the quota in declared order, because P4g stopped at a quota of
  *selected* documents while attrition happened later;
* every rejected candidate carries one of the declared admission failure codes,
  so an admitted count can be told apart from a broken fetcher.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_p4c_corpus as p4c  # noqa: E402
import fetch_p4g_corpus as p4g  # noqa: E402
from common import NS, canonical_sha, now, rel, sha_bytes  # noqa: E402
from evidence import write_immutable  # noqa: E402
from sources_p4i import (  # noqa: E402
    ACQUISITION_TARGET,
    ADMISSION_FAILURE_CODES,
    CONSUMPTION_ORDER,
    DART,
    ECFR_PARTS_ALL,
    FAILURE_CODE_MAP,
    FAMILY_QUOTA,
    GIT_REPOSITORIES_ALL,
    NETWORK,
    OVER_SELECTION,
    P4G_ADMITTED_MIX,
    REDISTRIBUTION,
    REVISION_SPACING,
    SEC_ISSUERS_ALL,
    SELECTION_RULE,
    WIKIPEDIA_ARTICLES_ALL,
)

RAW = NS / "artifacts" / "development" / "raw_p4i"
CANONICAL = NS / "artifacts" / "development" / "canonical_p4i"
SOURCES = Path(__file__).resolve().parent / "sources_p4i.py"
MANIFEST = NS / "artifacts" / "development" / "p4i_cohort.json"

FAMILIES = ("git_docs", "regulation_ecfr", "encyclopedia_wikipedia", "sec_edgar")
MIN_UNITS = p4g.MIN_UNITS


def _install_p4i_inputs() -> None:
    """Re-point P4g's selectors at P4i's declared lists and over-selection."""
    factor = OVER_SELECTION["factor"]
    p4g._repositories = lambda: GIT_REPOSITORIES_ALL
    p4g._parts = lambda: ECFR_PARTS_ALL
    p4g._articles = lambda: WIKIPEDIA_ARTICLES_ALL
    p4g._issuers = lambda: SEC_ISSUERS_ALL
    p4g._quota = lambda family: int(FAMILY_QUOTA[family] * factor)


def code_for(reason: str) -> str:
    return FAILURE_CODE_MAP.get(reason, "OTHER")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-payloads", action="store_true")
    args = parser.parse_args()
    started = now()
    _install_p4i_inputs()

    dart = p4c.probe_dart()
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for family, selector in (
        ("git_docs", p4g.git_documents),
        ("regulation_ecfr", p4g.ecfr_documents),
        ("encyclopedia_wikipedia", p4g.wikipedia_documents),
        ("sec_edgar", p4g.sec_documents),
    ):
        documents, excluded = selector()
        selected.extend(documents)
        rejected.extend(
            {**item, "family": family, "code": code_for(item["reason"]), "stage": "selection"}
            for item in excluded
        )
        print(
            json.dumps({"stage": "selected", "family": family, "candidates": len(documents)}),
            flush=True,
        )

    if args.skip_payloads:
        print(json.dumps({"selected": len(selected), "rejected": len(rejected)}, sort_keys=True))
        return 0

    admitted: list[dict[str, Any]] = []
    per_family: Counter[str] = Counter()
    for position, document in enumerate(selected):
        family = document["family"]
        if per_family[family] >= FAMILY_QUOTA[family]:
            # truncation at the quota, in declared order. Not by outcome:
            # no coverage or eligibility figure exists at this point.
            rejected.append(
                {
                    "document_id": document["document_id"],
                    "family": family,
                    "reason": "BEYOND_FAMILY_QUOTA",
                    "code": "OTHER",
                    "stage": "truncation",
                }
            )
            continue
        if position and position % 50 == 0:
            print(
                json.dumps({"stage": "payloads", "done": position, "admitted": len(admitted)}),
                flush=True,
            )
        try:
            sides = {side: p4c.payload_for(document, side) for side in ("before", "after")}
        except Exception as error:
            rejected.append(
                {
                    "document_id": document["document_id"],
                    "family": family,
                    "reason": "FETCH_FAILED",
                    "code": "PAYLOAD_UNAVAILABLE",
                    "stage": "payload",
                    "error": type(error).__name__,
                }
            )
            continue
        if sides["before"] == sides["after"]:
            rejected.append(
                {
                    "document_id": document["document_id"],
                    "family": family,
                    "reason": "INELIGIBLE_NO_SOURCE_CHANGE",
                    "code": "NO_SOURCE_CHANGE",
                    "stage": "payload",
                }
            )
            continue
        try:
            canonical = {side: p4c.canonicalise(document, side, sides[side]) for side in sides}
        except Exception as error:
            rejected.append(
                {
                    "document_id": document["document_id"],
                    "family": family,
                    "reason": "CANONICALISATION_FAILED",
                    "code": "PARSE_FLOOR",
                    "stage": "canonicalisation",
                    "error": type(error).__name__,
                }
            )
            continue
        if any(len(value["units"]) < MIN_UNITS for value in canonical.values()):
            rejected.append(
                {
                    "document_id": document["document_id"],
                    "family": family,
                    "reason": "INELIGIBLE_PARSE_FLOOR",
                    "code": "PARSE_FLOOR",
                    "stage": "canonicalisation",
                    "units": {s: len(v["units"]) for s, v in canonical.items()},
                }
            )
            continue

        slug = re.sub(r"[^A-Za-z0-9]+", "-", document["document_id"]).strip("-").lower()[:80]
        record = {k: v for k, v in document.items() if not k.startswith("_")}
        record["document_slug"] = slug
        for side in ("before", "after"):
            raw_path = RAW / slug / (side + document["suffix"])
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(sides[side])
            canonical_path = CANONICAL / slug / (side + ".json")
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(
                json.dumps(canonical[side], sort_keys=True, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            record[side] = {
                **{k: v for k, v in record.get(side, {}).items()},
                "raw_path": rel(raw_path),
                "raw_sha256": sha_bytes(sides[side]),
                "canonical_path": rel(canonical_path),
                "unit_count": len(canonical[side]["units"]),
            }
        admitted.append(record)
        per_family[family] += 1

    family_counts = {family: per_family[family] for family in FAMILIES if per_family[family]}
    by_code = Counter(item["code"] for item in rejected)
    by_family_code = {
        family: dict(
            Counter(item["code"] for item in rejected if item.get("family") == family)
        )
        for family in FAMILIES
    }
    manifest = {
        "schema": "tavonel.v2.p4i_cohort.v1",
        "protocol": "P4i_cohort_expansion",
        "built_at": started,
        "ended_at": now(),
        "sources_declaration": rel(SOURCES),
        "acquisition_target": ACQUISITION_TARGET,
        "family_quota": FAMILY_QUOTA,
        "family_quota_is": (
            "acquisition quotas scaled up from P4g's predeclared nominal balance "
            "rule, NOT P4g's realized proportions"
        ),
        "p4g_admitted_mix": P4G_ADMITTED_MIX,
        "over_selection": OVER_SELECTION,
        "consumption_order": CONSUMPTION_ORDER,
        "revision_spacing": REVISION_SPACING,
        "selection_rule": SELECTION_RULE,
        "network": NETWORK,
        "redistribution": REDISTRIBUTION,
        "dart": dart,
        "documents": admitted,
        "document_count": len(admitted),
        "family_counts": family_counts,
        "candidates_selected": len(selected),
        "rejected": rejected,
        "rejected_count": len(rejected),
        "admission_failure_codes": list(ADMISSION_FAILURE_CODES),
        "rejected_by_code": dict(by_code),
        "rejected_by_family_and_code": by_family_code,
        "documents_sha256": canonical_sha(admitted),
        "frozen_before_any_eligibility_result": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    written = write_immutable(
        "p4i-cohort-manifest",
        {
            "schema": "tavonel.v2.p4i_cohort_receipt.v1",
            "protocol": "P4i_cohort_expansion",
            "manifest_path": rel(MANIFEST),
            "documents_sha256": manifest["documents_sha256"],
            "document_count": len(admitted),
            "family_counts": family_counts,
            "candidates_selected": len(selected),
            "rejected_count": len(rejected),
            "rejected_by_code": dict(by_code),
            "rejected_by_family_and_code": by_family_code,
            "acquisition_target": ACQUISITION_TARGET,
            "breadth_floor": FAMILY_QUOTA["breadth_floor"],
            "meets_breadth_floor": len(admitted) >= FAMILY_QUOTA["breadth_floor"]
            and len(family_counts) >= 4,
            "dart": dart,
            "frozen_before_any_eligibility_result": True,
            "gpu_seconds": 0,
            "estimated_cost_usd": 0.0,
        },
        tool=Path(__file__).resolve(),
        protocol=SOURCES,
    )
    print(
        json.dumps(
            {
                "documents": len(admitted),
                "families": family_counts,
                "candidates": len(selected),
                "rejected_by_code": dict(by_code),
                "meets_breadth_floor": len(admitted) >= 400 and len(family_counts) >= 4,
                "manifest": rel(MANIFEST),
                **written,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
