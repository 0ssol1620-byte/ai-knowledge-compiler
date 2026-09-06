#!/usr/bin/env python3
"""Verify SFI3's actual declared roots against one exact predecessor handoff.

This is a pre-payload gate.  It accepts no default receipt, performs no search,
and reads only root/container identity metadata.  Both the worker and scorer call
the same function so the reservation cannot be checked under two subtly
different contracts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("tools", "acquisition"):
    _value = str(NS / _sub)
    if _value not in sys.path:
        sys.path.insert(0, _value)

import sfi3_root_reservation as reservation  # noqa: E402
import v2r4_sfi3_reservation_handoff as handoff_contract  # noqa: E402
from common import canonical_sha, sha_file  # noqa: E402


class BindingRefused(RuntimeError):
    """The exact handoff or the actual SFI3 root set is not the sealed binding."""


def _resolve_exact(path: Path) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    candidate = candidate.resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as error:
        raise BindingRefused(f"binding receipt escapes the repository: {path}") from error
    if not candidate.is_file():
        raise BindingRefused(f"exact binding receipt is absent: {candidate}")
    return candidate


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BindingRefused(f"cannot read exact {label} {path}: {error}") from error
    if not isinstance(body, dict):
        raise BindingRefused(f"exact {label} is not a JSON object: {path}")
    return body


def verify_binding(
    *,
    handoff_receipt: Path,
    handoff_sha256: str,
    actual_roots: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    """Verify one exact handoff and prove the actual SFI3 roots remain inside it."""
    if not handoff_sha256.startswith("sha256:"):
        raise BindingRefused("the exact handoff sha256 must include the 'sha256:' prefix")
    handoff_path = _resolve_exact(handoff_receipt)
    actual_handoff_sha256 = sha_file(handoff_path)
    if actual_handoff_sha256 != handoff_sha256:
        raise BindingRefused(
            "exact handoff file digest mismatch: "
            f"expected {handoff_sha256}, found {actual_handoff_sha256}"
        )

    handoff = _read_object(handoff_path, "handoff receipt")
    try:
        handoff_held = handoff_contract.verify(handoff)
    except handoff_contract.HandoffRefused as error:
        raise BindingRefused(f"predecessor handoff refused: {error}") from error

    reference = handoff.get("reservation")
    if not isinstance(reference, dict):
        raise BindingRefused("the exact handoff carries no reservation reference")
    reservation_path_value = reference.get("receipt")
    reservation_sha256 = reference.get("file_sha256")
    if not isinstance(reservation_path_value, str) or not reservation_path_value:
        raise BindingRefused("the exact handoff carries no reservation path")
    if not isinstance(reservation_sha256, str) or not reservation_sha256:
        raise BindingRefused("the exact handoff carries no reservation file sha256")

    reservation_path = _resolve_exact(Path(reservation_path_value))
    actual_reservation_sha256 = sha_file(reservation_path)
    if actual_reservation_sha256 != reservation_sha256:
        raise BindingRefused(
            "reservation file digest differs from the exact handoff: "
            f"expected {reservation_sha256}, found {actual_reservation_sha256}"
        )
    stored = _read_object(reservation_path, "reservation receipt")

    roots = reservation.declared_roots() if actual_roots is None else actual_roots
    if not isinstance(roots, dict) or not roots:
        raise BindingRefused("the actual frozen SFI3 root set is absent")
    try:
        within = reservation.require_within_reservation(
            reservation=stored,
            families=roots,
        )
    except reservation.ReservationRefused as error:
        raise BindingRefused(f"actual frozen SFI3 roots refuse reservation: {error}") from error

    return {
        "held": True,
        "handoff": _relative(handoff_path),
        "handoff_sha256": actual_handoff_sha256,
        "handoff_id": handoff_held["handoff_id"],
        "reservation": _relative(reservation_path),
        "reservation_sha256": actual_reservation_sha256,
        "reservation_id": within["reservation_id"],
        "reservation_content_digest": within["content_digest"],
        "actual_roots_sha256": canonical_sha(roots),
        "actual_root_counts": {family: len(values) for family, values in sorted(roots.items())},
        "families_checked": within["families_checked"],
        "decision_basis": "root/container identity metadata only; no payload or revision read",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--handoff-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_binding(
            handoff_receipt=args.handoff,
            handoff_sha256=args.handoff_sha256,
        )
    except BindingRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2))
        return 4
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
