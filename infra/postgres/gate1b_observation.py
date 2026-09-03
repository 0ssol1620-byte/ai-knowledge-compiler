"""Gate 1B real-workload observation receipt generator.

This tool deliberately does *not* decide how much production traffic is
"enough". Gate 1B is an operational-confidence gate, not a code gate. The
operator must provide explicit minimum attempt/grant deltas for the observation
window, together with Prometheus/OpenMetrics snapshots taken before and after
real workload.

No database role is changed and Canary B is never invoked by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

QUEUE = "gpu_provider_invocations"
_REQUIRED = (
    "akc_claim_poll_attempts_total",
    "akc_claim_poll_grants_total",
    "akc_claim_poll_backlog",
    "akc_claim_poll_claimable",
    "akc_claim_poll_consecutive_zero_polls",
    "akc_claim_poll_starved",
)
_SAMPLE = re.compile(
    r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+([-+0-9.eE]+)(?:\s+\d+)?$'
)
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')


@dataclass(frozen=True)
class Snapshot:
    attempts: float
    grants: float
    backlog: float
    claimable: float
    zero_run: float
    starved: float


@dataclass(frozen=True)
class Gate1BReceipt:
    status: str
    queue: str
    before_sha256: str
    after_sha256: str
    attempts_delta: float
    grants_delta: float
    min_attempts: int
    min_grants: int
    final_backlog: float
    final_claimable: float
    final_zero_run: float
    final_starved: float
    checks: dict[str, bool]
    blockers: tuple[str, ...]


def _unescape_label(value: str) -> str:
    return bytes(value, "utf-8").decode("unicode_escape")


def _parse_labels(raw: str) -> dict[str, str]:
    return {key: _unescape_label(value) for key, value in _LABEL.findall(raw)}


def parse_snapshot(text: str, *, queue: str = QUEUE) -> Snapshot:
    values: dict[str, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE.match(line)
        if not match:
            continue
        metric, raw_labels, raw_value = match.groups()
        if metric not in _REQUIRED:
            continue
        labels = _parse_labels(raw_labels)
        if labels.get("queue") != queue:
            continue
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"non-finite {metric} for queue {queue}")
        values[metric] = value

    missing = [metric for metric in _REQUIRED if metric not in values]
    if missing:
        raise ValueError(f"missing Gate 1B metrics for queue {queue}: {', '.join(missing)}")

    return Snapshot(
        attempts=values["akc_claim_poll_attempts_total"],
        grants=values["akc_claim_poll_grants_total"],
        backlog=values["akc_claim_poll_backlog"],
        claimable=values["akc_claim_poll_claimable"],
        zero_run=values["akc_claim_poll_consecutive_zero_polls"],
        starved=values["akc_claim_poll_starved"],
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def evaluate(
    before_bytes: bytes,
    after_bytes: bytes,
    *,
    min_attempts: int,
    min_grants: int,
    queue: str = QUEUE,
) -> Gate1BReceipt:
    if min_attempts <= 0:
        raise ValueError("--min-attempts must be > 0")
    if min_grants < 0:
        raise ValueError("--min-grants must be >= 0")
    if min_grants > min_attempts:
        raise ValueError("--min-grants cannot exceed --min-attempts")

    before = parse_snapshot(before_bytes.decode("utf-8"), queue=queue)
    after = parse_snapshot(after_bytes.decode("utf-8"), queue=queue)
    attempts_delta = after.attempts - before.attempts
    grants_delta = after.grants - before.grants

    checks = {
        "counter_attempts_monotonic": attempts_delta >= 0,
        "counter_grants_monotonic": grants_delta >= 0,
        "attempts_observed": attempts_delta >= min_attempts,
        "grants_observed": grants_delta >= min_grants,
        "grants_not_above_attempts": grants_delta <= attempts_delta,
        "backlog_nonnegative": after.backlog >= 0,
        "claimable_nonnegative": after.claimable >= 0,
        "claimable_not_above_backlog": after.claimable <= after.backlog,
        "zero_run_nonnegative": after.zero_run >= 0,
        "starvation_clear": after.starved == 0,
    }
    blockers = tuple(name for name, passed in checks.items() if not passed)
    return Gate1BReceipt(
        status="PASS" if not blockers else "BLOCKED",
        queue=queue,
        before_sha256=_sha256(before_bytes),
        after_sha256=_sha256(after_bytes),
        attempts_delta=attempts_delta,
        grants_delta=grants_delta,
        min_attempts=min_attempts,
        min_grants=min_grants,
        final_backlog=after.backlog,
        final_claimable=after.claimable,
        final_zero_run=after.zero_run,
        final_starved=after.starved,
        checks=checks,
        blockers=blockers,
    )


def _read(path: Path) -> bytes:
    data = path.read_bytes()
    if not data:
        raise ValueError(f"empty metrics snapshot: {path}")
    return data


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--min-attempts", type=int, required=True)
    parser.add_argument("--min-grants", type=int, required=True)
    parser.add_argument("--queue", default=QUEUE)
    parser.add_argument("--receipt", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = evaluate(
        _read(args.before),
        _read(args.after),
        min_attempts=args.min_attempts,
        min_grants=args.min_grants,
        queue=args.queue,
    )
    payload = json.dumps(asdict(receipt), indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if receipt.status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
