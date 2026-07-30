"""Acquire bounded OpenDART business-report sources for private benchmarking."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.sources.dart import (
    DART_CONFIRMATION,
    DartApiError,
    DartClient,
    acquire_disclosures,
    load_dart_api_key,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--begin-date", required=True, help="YYYYMMDD")
    parser.add_argument("--end-date", required=True, help="YYYYMMDD")
    parser.add_argument("--corp-code", help="Optional eight-digit OpenDART corporation code")
    parser.add_argument("--maximum-filings", type=int, default=1)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("benchmark/datasets/private/dart"),
    )
    parser.add_argument(
        "--credential-file",
        type=Path,
        help="Local file containing one line labeled DART and a 40-character key",
    )
    parser.add_argument("--confirm", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        api_key = load_dart_api_key(credential_file=args.credential_file)
        receipts = acquire_disclosures(
            client=DartClient(api_key),
            output_root=args.output_root,
            begin_date=args.begin_date,
            end_date=args.end_date,
            corporation_code=args.corp_code,
            maximum_filings=args.maximum_filings,
            confirmation=args.confirm,
        )
    except (DartApiError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc), "credentials_exposed": False},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "receipt_count": len(receipts),
                "output_root": str(args.output_root.resolve()),
                "labels_present": False,
                "eligible_for_quality_claims": False,
                "confirmation": DART_CONFIRMATION,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
