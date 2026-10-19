"""Mock-replay runner for the vendor adapter harness. Live execution is refused.

    python -m research.vendor_comparison_20261017.run [--out REPORT.json]
    python -m research.vendor_comparison_20261017.run --execute --arm D-V-llamaparse \
        --fd1-receipt FD1.json --fd2-receipt FD2.json

Vendor terms read on 2026-10-17 forbid benchmarking or competitive use (COMPETITOR-PROTOCOL
§2.2). ``--execute`` is checked before anything else in ``main``: it refuses unless the founder's
FD-1 receipt (``{"decision": "FD-1", "approved_arms": [...]}``) and FD-2 receipt
(``{"decision": "FD-2", "spend_cap_usd": {arm: usd}}``) exist and name the arm. Even then it
refuses, because this package ships no live transport; adding one is its own reviewed change.

Without ``--execute`` it replays every SYNTHETIC fixture through its adapter and prints a report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from .adapters import ADAPTERS
from .adapters.base import Document, ParseResult, Pin, ReplayTransport, ResponseShape
from .cost import SNAPSHOTS, document_cost

EXIT_OK, EXIT_EXPECTATION_MISMATCH, EXIT_REFUSED = 0, 1, 3
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "synthetic"
SHARED_FIXTURE = "SYNTHETIC-transport-failures.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mock-replay vendor adapter harness (AT-2).")
    parser.add_argument("--execute", action="store_true", help="run against a live vendor")
    parser.add_argument("--arm", help="arm id, e.g. D-V-llamaparse (with --execute)")
    parser.add_argument("--fd1-receipt", type=Path, help="founder FD-1 terms decision receipt")
    parser.add_argument("--fd2-receipt", type=Path, help="founder FD-2 key and spend-cap receipt")
    parser.add_argument("--out", type=Path, help="write the mock report here instead of stdout")
    return parser


def _receipt_problem(decision: str, path: Path | None, arm: str) -> str | None:
    if path is None:
        return f"{decision} receipt not given (--{decision.lower().replace('-', '')}-receipt)"
    if not path.is_file():
        return f"{decision} receipt file does not exist: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"{decision} receipt is not readable JSON: {exc}"
    if not isinstance(data, dict) or data.get("decision") != decision:
        return f"{path} does not record decision {decision}"
    if decision == "FD-1":
        approved = data.get("approved_arms")
        if not isinstance(approved, list) or arm not in approved:
            return f"FD-1 receipt does not approve arm {arm}"
    else:
        caps = data.get("spend_cap_usd")
        cap = caps.get(arm) if isinstance(caps, dict) else None
        if isinstance(cap, bool) or not isinstance(cap, int | float) or cap <= 0:
            return f"FD-2 receipt sets no positive spend cap for arm {arm}"
    return None


def execute_refusal(argv: Sequence[str]) -> str | None:
    """None when --execute is absent; otherwise the reason execution is refused."""
    args = _parser().parse_args(argv)
    if not args.execute:
        return None
    if not args.arm:
        return "REFUSED: --execute needs --arm"
    for decision, path in (("FD-1", args.fd1_receipt), ("FD-2", args.fd2_receipt)):
        problem = _receipt_problem(decision, path, args.arm)
        if problem:
            return f"REFUSED (vendor terms forbid benchmarking until FD-1/FD-2): {problem}"
    return (
        f"REFUSED: FD-1 and FD-2 receipts name {args.arm}, but this harness ships no live "
        "transport (AT-2 is mock-only); a live transport is a separate reviewed change"
    )


def _shape(spec: Mapping[str, Any] | None) -> ResponseShape | None:
    if spec is None:
        return None
    page_count = spec.get("page_count")
    return ResponseShape(
        source=spec["source"],
        markdown=tuple(spec["markdown"]),
        page_count=None if page_count is None else tuple(page_count),
        usage={name: tuple(path) for name, path in spec.get("usage", {}).items()},
    )


def _document(spec: Mapping[str, Any]) -> Document:
    pdf = spec["pdf_text"].encode("ascii")
    pdf += b" " * max(0, int(spec.get("pad_to_bytes", 0)) - len(pdf))
    return Document(spec["doc_id"], pdf, int(spec["pages"]))


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not path.name.startswith("SYNTHETIC-") or data.get("label") != "SYNTHETIC":
        raise ValueError(f"{path.name}: every fixture is SYNTHETIC in its name and its data")
    return dict(data)


def cases(fixture_dir: Path = FIXTURE_DIR) -> list[dict[str, Any]]:
    """Every (vendor fixture x scenario) pair, the shared transport failures included."""
    shared = load_fixture(fixture_dir / SHARED_FIXTURE)["scenarios"]
    out = []
    for path in sorted(fixture_dir.glob("SYNTHETIC-*.json")):
        if path.name == SHARED_FIXTURE:
            continue
        fixture = load_fixture(path)
        pin_spec = fixture["pin"]
        pin = Pin(
            arm_id=pin_spec["arm_id"],
            api_key_env=pin_spec["api_key_env"],
            timeout_s=float(pin_spec["timeout_s"]),
            config=dict(pin_spec.get("config", {})),
            response_shape=_shape(fixture.get("response_shape")),
        )
        for scenario in [*fixture["scenarios"], *shared]:
            document = _document({**fixture["document"], **scenario.get("document", {})})
            out.append({**scenario, "vendor": fixture["vendor"], "pin": pin, "document": document})
    return out


def run_case(case: Mapping[str, Any]) -> tuple[ParseResult, ReplayTransport]:
    transport = ReplayTransport(case["exchanges"])
    adapter = ADAPTERS[case["vendor"]](transport, sleep=lambda _seconds: None)
    return adapter.parse(case["document"], case["pin"]), transport


def _usd(amount: Decimal) -> str:
    return str(amount.quantize(Decimal("0.000001")))


def _row(case: Mapping[str, Any]) -> dict[str, Any]:
    result, transport = run_case(case)
    cost = document_cost(case["vendor"], result, case["document"], case["pin"].config)
    row: dict[str, Any] = {
        key: value
        for key, value in asdict(result).items()
        if key != "elapsed_s"  # wall time of a replay measures nothing
    }
    row.update(
        vendor=case["vendor"],
        scenario=case["name"],
        failure_class=result.failure_class,
        requests=[request.operation for request in transport.requests],
        unused_exchanges=transport.unused,
        cost="not_applicable"
        if cost is None
        else {
            "snapshot_usd": _usd(cost.snapshot_usd),
            "metadata_usd": None if cost.metadata_usd is None else _usd(cost.metadata_usd),
            "charged_usd": _usd(cost.charged_usd),
        },
    )
    expected = case["expected"]
    mismatches = [key for key, want in expected.items() if key not in row or row[key] != want]
    if transport.unused:
        mismatches.append("unused_exchanges")
    row["expected"], row["mismatches"] = expected, mismatches
    return row


def report(fixture_dir: Path = FIXTURE_DIR) -> dict[str, Any]:
    rows = [_row(case) for case in cases(fixture_dir)]
    summary: dict[str, Any] = {}
    for arm in sorted({row["arm_id"] for row in rows}):
        arm_rows = [row for row in rows if row["arm_id"] == arm]
        classes = Counter(row["failure_class"] for row in arm_rows if row["failure_class"])
        summary[arm] = {
            "N": len(arm_rows),
            "status_counts": dict(sorted(Counter(row["status"] for row in arm_rows).items())),
            "completion": {
                "numerator": sum(row["status"] == "ok" for row in arm_rows),
                "denominator": len(arm_rows),
                "meaning": "non-empty output / N (completion, not accuracy)",
            },
            "failure_classes": dict(sorted(classes.items())),
        }
    return {
        "schema": "tavonel.vendor_comparison.harness_mock_run.v1",
        "label": "SYNTHETIC",
        "lane": "AT-2",
        "mode": "mock_replay",
        "vendor_calls": 0,
        "measured_numbers": "none: every row replays a SYNTHETIC fixture, not a vendor",
        "adapters": {vendor: cls.wire_source for vendor, cls in sorted(ADAPTERS.items())},
        "price_snapshots": {vendor: asdict(snap) for vendor, snap in sorted(SNAPSHOTS.items())},
        "rows": rows,
        "summary": summary,
        "all_expectations_met": all(not row["mismatches"] for row in rows),
    }


def main(argv: Sequence[str] | None = None) -> int:
    if (refusal := execute_refusal(sys.argv[1:] if argv is None else argv)) is not None:
        print(refusal, file=sys.stderr)
        return EXIT_REFUSED
    args = _parser().parse_args(argv)
    result = report()
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return EXIT_OK if result["all_expectations_met"] else EXIT_EXPECTATION_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())
