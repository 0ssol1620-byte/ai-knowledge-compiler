"""Sealed, content-bound smoke baseline for runtime qualification.

A qualification gate that compares a fresh smoke prediction against an
"expected" hash is only meaningful if that expected hash cannot be produced
from the very run it is meant to judge.  This module seals the *only*
legitimate source of ``smoke_expected_sha256``: an earlier, separate pod
session that repeated the same smoke prediction three times and found the
same content every time.

``build_and_seal_baseline`` never resolves disagreement between the three
repeats.  Non-determinism across repeats is a genuine finding
(``intra_pod_determinism: false``) and is recorded as a failed baseline, not
papered over with a majority vote.

This module performs no network access, no GPU access and constructs no
provider client - it only reads local smoke-run markdown output and writes a
JSON receipt.
"""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from infra.runpod.v6.pod_client import write_receipt_exclusive

_SCHEMA: Final = "folynta.baked-runtime-smoke-baseline.v1"
_REQUIRED_REPEATS: Final = 3


def canonical_smoke_prediction_bytes(markdown_dir: Path) -> bytes:
    """Deterministic byte representation of a smoke run's markdown output.

    ``markdown_dir`` is the root of one smoke-run session and is expected to
    contain the ``markdown-repeat-{N}/{case_id}.md`` layout used by
    ``research/experiments/SEM-RISK-CONF-02/evaluate_confirmatory.py`` (read
    only, never imported or modified here - the convention is reproduced
    independently so this module has no dependency on a frozen experiment).

    Every matching file is sorted by filename, normalized (CRLF -> LF,
    trailing whitespace stripped per line, exactly one trailing newline), and
    joined with a NUL separator so the result is independent of filesystem
    iteration order and incidental whitespace drift. This is the single
    shared normalization logic - both ``runtime_smoke_baseline.py`` and
    ``build_runtime_qualification.py`` must call this function rather than
    reimplementing it.
    """

    files = sorted(
        markdown_dir.glob("markdown-repeat-*/*.md"), key=lambda path: (path.name, str(path))
    )
    if not files:
        raise ValueError(f"no smoke prediction markdown files found under {markdown_dir}")

    parts: list[bytes] = []
    for path in files:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        lines = [line.rstrip() for line in text.split("\n")]
        while lines and lines[-1] == "":
            lines.pop()
        normalized = "\n".join(lines) + "\n"
        parts.append(normalized.encode("utf-8"))
    return b"\x00".join(parts)


def _sha256_of(markdown_dir: Path) -> str:
    return "sha256:" + hashlib.sha256(canonical_smoke_prediction_bytes(markdown_dir)).hexdigest()


def build_smoke_baseline(
    *,
    repeat_dirs: tuple[Path, Path, Path],
    pod_id: str,
    started_at: str,
    image_digest: str,
    sealed_at: str | None = None,
) -> dict[str, Any]:
    """Assemble (but do not write) a ``folynta.baked-runtime-smoke-baseline.v1`` object.

    ``pod_id`` and ``started_at`` must be real values from the actual pod
    session that produced ``repeat_dirs`` - there is no default for either,
    so a caller cannot fake provenance by omission.  ``baseline_run_id`` is
    derived from them, never accepted directly, so it always traces back to
    a concrete pod identifier and start time.
    """

    if len(repeat_dirs) != _REQUIRED_REPEATS:
        raise ValueError(f"exactly {_REQUIRED_REPEATS} repeat directories are required")
    if not pod_id.strip():
        raise ValueError("pod_id is required")
    if not started_at.strip():
        raise ValueError("started_at is required")
    if not image_digest.strip():
        raise ValueError("image_digest is required")

    repeat_hashes = [_sha256_of(repeat_dir) for repeat_dir in repeat_dirs]
    intra_pod_determinism = len(set(repeat_hashes)) == 1
    established_expected_sha256 = repeat_hashes[0] if intra_pod_determinism else None

    return {
        "schema": _SCHEMA,
        "baseline_run_id": f"{pod_id}@{started_at}",
        "image_digest": image_digest,
        "repeat_sha256": repeat_hashes,
        "intra_pod_determinism": intra_pod_determinism,
        "established_expected_sha256": established_expected_sha256,
        "passed": intra_pod_determinism,
        "sealed_at": sealed_at or datetime.now(UTC).isoformat(),
    }


def build_and_seal_baseline(
    *,
    repeat_dirs: tuple[Path, Path, Path],
    pod_id: str,
    started_at: str,
    image_digest: str,
    output_path: Path,
    sealed_at: str | None = None,
) -> dict[str, Any]:
    """Build the baseline and seal it with an exclusive-create write.

    ``write_receipt_exclusive`` opens the output path with Python's true
    exclusive-create mode (``open("x", ...)``); if a baseline receipt already
    exists at ``output_path`` this raises ``FileExistsError`` and that
    exception is allowed to propagate unmodified - a baseline is sealed once,
    never silently replaced.
    """

    baseline = build_smoke_baseline(
        repeat_dirs=repeat_dirs,
        pod_id=pod_id,
        started_at=started_at,
        image_digest=image_digest,
        sealed_at=sealed_at,
    )
    write_receipt_exclusive(output_path, baseline)
    return baseline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repeat-dir",
        action="append",
        type=Path,
        required=True,
        help="directory for one repeated smoke run; pass exactly three times",
    )
    parser.add_argument(
        "--pod-id", required=True, help="real pod identifier for this baseline session"
    )
    parser.add_argument(
        "--started-at", required=True, help="ISO-8601 start time of the baseline pod session"
    )
    parser.add_argument(
        "--image-digest", required=True, help="immutable image digest used for this baseline run"
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repeat_dirs = tuple(args.repeat_dir)
    if len(repeat_dirs) != _REQUIRED_REPEATS:
        raise SystemExit(
            f"--repeat-dir must be passed exactly {_REQUIRED_REPEATS} times, got {len(repeat_dirs)}"
        )
    build_and_seal_baseline(
        repeat_dirs=repeat_dirs,
        pod_id=args.pod_id,
        started_at=args.started_at,
        image_digest=args.image_digest,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "build_and_seal_baseline",
    "build_smoke_baseline",
    "canonical_smoke_prediction_bytes",
    "main",
]
