#!/usr/bin/env python3
"""SFIR5's charter freeze. The science is carried by reference; this seals that.

SFIR5 exists because SFIR4 stopped operationally, not because anything about the
question changed. So the charter's job here is unusual: most of it is about what
SFIR5 must NOT contain.

`require_carried_forward` refuses the SFIR5 charter if it declares any field that
SFIR4's charter owns -- families, roots, the capacity rule, the caps, the salt,
the identity and payload policies. That is what makes "carried forward unchanged"
a checkable property rather than a sentence in a document. A copied field would
be free to drift the moment either file was edited, and the drift would be
invisible: two documents that disagree look exactly like two documents that
agree until someone reads both.

The census itself runs SFIR4's probe against SFIR4's charter, and that probe
re-hashes itself against the charter it was given before it does anything. So the
statement "the same science ran" is not a claim about intent; it is the same
bytes, verified by the same code, refusing to start if either has moved.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir4_protocol as protocol  # noqa: E402
import sfir5_transport as transport  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V5"
CHARTER_SCHEMA = "tavonel.sfir5.design_charter_freeze.v1"

CHARTER_YAML = NS / "protocols" / f"{PROTOCOL_ID}_DESIGN_CHARTER.yaml"
SFIR4_CHARTER_YAML = (
    NS / "protocols" / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4_DESIGN_CHARTER.yaml"
)

#: The fields SFIR4's charter owns. SFIR5 may name them in its
#: `fields_owned_by_that_document` list -- that is a pointer -- but may not
#: declare them at the top level, which would be a copy.
SCIENTIFIC_FIELDS_OWNED_BY_SFIR4 = (
    "family_authorities",
    "capacity_rule",
    "git_tree_enumeration",
    "spent_policy",
    "payload_policy",
    "terminal_policy",
)


class SFIR5Refused(RuntimeError):
    """A pre-freeze condition was not met. Terminal; nothing is sealed."""


def require_carried_forward(document: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse an SFIR5 charter that restates any of SFIR4's science.

    The control that makes the reference real. Without it, "carried forward
    unchanged" is an assertion in a comment, and the first edit to either file
    turns it into a false one silently.
    """
    block = document.get("carried_forward_by_reference")
    if not isinstance(block, Mapping):
        raise SFIR5Refused("SFIR5 charter does not say what it carries forward")
    redeclared = sorted(field for field in SCIENTIFIC_FIELDS_OWNED_BY_SFIR4 if field in document)
    if redeclared:
        raise SFIR5Refused(
            f"SFIR5 charter redeclares {', '.join(redeclared)}, which SFIR4's charter owns. "
            "A copy can drift from the thing it copied; carry it by reference."
        )
    if (
        block.get("charter") != protocol_relative(SFIR4_CHARTER_YAML)
        or tuple(block.get("fields_owned_by_that_document") or ())
        != SCIENTIFIC_FIELDS_OWNED_BY_SFIR4
        or block.get("redeclaring_any_of_them_here_is_a_refusal") is not True
        or block.get("the_probe_is_sfir4s_probe") is not True
    ):
        raise SFIR5Refused("SFIR5 carry-forward block does not bind SFIR4's charter exactly")
    if not SFIR4_CHARTER_YAML.is_file():
        raise SFIR5Refused("the SFIR4 charter this one defers to is absent")
    return {
        "charter": protocol_relative(SFIR4_CHARTER_YAML),
        "sha256": "sha256:" + hashlib.sha256(SFIR4_CHARTER_YAML.read_bytes()).hexdigest(),
        "fields_carried": list(SCIENTIFIC_FIELDS_OWNED_BY_SFIR4),
        "fields_redeclared": [],
    }


def protocol_relative(path: Path) -> str:
    return path.relative_to(NS).as_posix()


def require_transport_matches_charter(document: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse a charter whose declared transport is not the code that will run.

    Both directions matter. A charter that promises 7 seconds while the module
    paces at 2 is a receipt describing a run that did not happen; a module that
    paces at 7 while the charter is silent is an unfrozen parameter. So this
    compares the document against the module's own constants rather than against
    a second copy of the numbers.
    """
    block = document.get("transport_policy")
    if not isinstance(block, Mapping):
        raise SFIR5Refused("SFIR5 charter declares no transport policy")
    declared = {
        "host_min_interval_seconds": dict(block.get("host_min_interval_seconds") or {}),
        "default_min_interval_seconds": block.get("default_min_interval_seconds"),
        "max_total_wall_clock_seconds": block.get("max_total_wall_clock_seconds"),
        "max_total_requests": block.get("max_total_requests"),
        "bounded_concurrency_per_host": block.get("bounded_concurrency_per_host"),
    }
    running = {
        "host_min_interval_seconds": dict(transport.HOST_MIN_INTERVAL_SECONDS),
        "default_min_interval_seconds": transport.DEFAULT_MIN_INTERVAL_SECONDS,
        "max_total_wall_clock_seconds": transport.MAX_TOTAL_WALL_CLOCK_SECONDS,
        "max_total_requests": transport.MAX_TOTAL_REQUESTS,
        "bounded_concurrency_per_host": transport.MAX_CONCURRENT_REQUESTS_PER_HOST,
    }
    if declared != running:
        raise SFIR5Refused(
            "the charter's transport policy is not the transport that will run: "
            f"charter says {declared}, module says {running}"
        )
    return running


def require_sfir4_bounds_untouched(document: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse a charter that quietly enlarged the budget SFIR4 stopped on.

    This is the one repair the founder's ruling and this study's own standard
    both refuse, so it gets a check rather than a promise. It reads the live
    values out of `sources_sfir4`, not out of a constant here, so editing the
    frozen module is what fails -- which is the thing being guarded against.
    """
    block = (document.get("transport_policy") or {}).get("sfir4_retry_bounds_unmodified")
    actual = {
        "maximum_retries_per_request": sources.PAGINATION_CONTRACT["maximum_retries_per_request"],
        "max_rate_limit_wait_seconds": sources.MAX_RATE_LIMIT_WAIT_SECONDS,
        "max_total_rate_limit_wait_seconds": sources.MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS,
    }
    if not isinstance(block, Mapping) or dict(block) != actual:
        raise SFIR5Refused(
            "SFIR4's retry bounds are not what SFIR5's charter says they are; a bound "
            f"chosen after watching a run fail is chosen by the failure. {actual}"
        )
    return actual


def require_batching_unchanged(document: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse a charter that changed what one response covers.

    The founder's ruling asked whether official batching could replace paced
    serial traversal. The answer is that the bound SFIR3 adapter already batches,
    at sizes SFIR4 froze, so there is nothing to adopt: a different batch size
    would change how many pages one response covers, and with it the ordering and
    the request-to-response mapping. That is a change to the instrument, not to
    its pacing, so SFIR5 does not make it.
    """
    block = document.get("batching_policy")
    pool = sources.SOURCE_POOLS["encyclopedia_wikipedia"]
    actual = {
        "category_page_size": pool["category_page_size"],
        "revision_batch_size": pool["revision_batch_size"],
    }
    if (
        not isinstance(block, Mapping)
        or block.get("new_batching_introduced_by_sfir5") is not False
        or block.get("inherited_from_bound_sfir3_adapter") is not True
        or block.get("category_page_size") != actual["category_page_size"]
        or block.get("revision_batch_size") != actual["revision_batch_size"]
    ):
        raise SFIR5Refused(
            "SFIR5's batching declaration does not match the frozen adapter's "
            f"batch sizes {actual}; changing them changes what a response covers"
        )
    return actual


def require_census_identity(document: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse a charter that does not admit whose protocol_id the census carries.

    SFIR4's probe stamps `SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4` into the
    census input, because it is SFIR4's algorithm running. That is correct and it
    is also the most mistakable thing about this design, so the charter says it
    out loud and the seal binds the census by digest under SFIR5's name.
    """
    block = document.get("census_identity")
    if (
        not isinstance(block, Mapping)
        or block.get("census_input_carries_sfir4_protocol_id") is not True
        or block.get("executed_under") != PROTOCOL_ID
        or block.get("seal_binds_census_input_by_exact_digest") is not True
    ):
        raise SFIR5Refused("SFIR5 charter does not declare whose protocol_id the census carries")
    return dict(block)


def load(charter_yaml: Path = CHARTER_YAML) -> dict[str, Any]:
    if not charter_yaml.is_file():
        raise SFIR5Refused("SFIR5 charter is absent")
    document = yaml.safe_load(charter_yaml.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("protocol_id") != PROTOCOL_ID
        or document.get("state") != "PROSPECTIVE_PRE_CENSUS"
        or document.get("result_blind_design") is not True
        or document.get("succeeds") != protocol.PROTOCOL_ID
        or document.get("succeeds_because") != "TERMINAL_OPERATIONAL_STOP"
    ):
        raise SFIR5Refused("SFIR5 charter header is incomplete or drifted")
    return document


def freeze(
    destination: Path,
    generated_at: str,
    charter_yaml: Path = CHARTER_YAML,
    root: Path | None = None,
) -> Path:
    """Seal the charter, or refuse. Every gate runs before anything is written."""
    document = load(charter_yaml)
    carried = require_carried_forward(document)
    transport_bounds = require_transport_matches_charter(document)
    sfir4_bounds = require_sfir4_bounds_untouched(document)
    batching = require_batching_unchanged(document)
    census_identity = require_census_identity(document)
    base = root or NS.parents[1]
    core: dict[str, Any] = {
        "schema": CHARTER_SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "generated_at": generated_at,
        "state": "FROZEN_PRE_CENSUS",
        "charter": protocol.exact_ref(base, charter_yaml),
        "carried_forward_by_reference": carried,
        "toolchain": {
            "sfir5_transport": protocol.exact_ref(base, NS / "tools" / "sfir5_transport.py"),
            "sfir5_charter": protocol.exact_ref(base, Path(__file__)),
            "probe_sfir5_capacity": protocol.exact_ref(
                base, NS / "tools" / "probe_sfir5_capacity.py"
            ),
            "probe_sfir4_capacity": protocol.exact_ref(
                base, NS / "tools" / "probe_sfir4_capacity.py"
            ),
            "sources_sfir4": protocol.exact_ref(base, NS / "acquisition" / "sources_sfir4.py"),
        },
        "transport_bounds": transport_bounds,
        "sfir4_retry_bounds_unmodified": sfir4_bounds,
        "batching": batching,
        "census_identity": census_identity,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    core["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return protocol.write_immutable(destination, core)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from common import now

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination", type=Path, default=NS / "receipts" / "sfir5-design-charter-freeze.json"
    )
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args(argv)
    try:
        path = freeze(args.destination, args.generated_at or now())
    except SFIR5Refused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4
    print(json.dumps({"state": "SEALED", "path": path.as_posix()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
