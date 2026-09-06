#!/usr/bin/env python3
"""Verify `docs/ip/claim-evidence-matrix.yaml` against the receipts it cites.

The rule this tool exists to enforce is the repository's own: never publish a
claim without a receipt. So it does not render a document and trust the author.
For every claim it:

  * resolves each evidence path and hashes it;
  * re-reads each `asserts` entry out of the receipt by JSON pointer and compares
    the value the claim says is there;
  * where a claim pins source files, checks the receipt's recorded hash still
    matches the live file, so a claim cannot quietly drift off the code it was
    measured against;
  * refuses to emit anything at all if any of that fails.

A missing receipt, a moved number or a changed core module is an error, not a
warning. The matrix is only worth having if it cannot be green while wrong.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs" / "ip" / "claim-evidence-matrix.yaml"

TERMINAL_STATUSES = {
    "SUPERSEDED",
    "FAILED",
    "WITHDRAWN",
    "NOT_RUN",
    "BLOCKED_EXTERNAL",
    "BLOCKED_INTERNAL",
}


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def resolve_pointer(document: Any, pointer: str) -> Any:
    """RFC 6901, including the `~1` / `~0` escapes.

    The escapes were skipped originally because no claim needed them. Receipts
    that key a map by file path do -- `pinned_files` has `/` inside its keys --
    and a resolver that silently fails on those would report a claim as
    unverifiable when the value is right there.
    """
    node = document
    for raw in pointer.lstrip("/").split("/"):
        if raw == "":
            continue
        token = raw.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def check_claim(claim: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    checked_evidence: list[dict[str, Any]] = []

    for item in claim.get("evidence", []):
        path = ROOT / item["path"]
        record: dict[str, Any] = {"path": item["path"]}
        if not path.exists():
            problems.append(f"{claim['id']}: evidence missing on disk: {item['path']}")
            record["status"] = "MISSING"
            checked_evidence.append(record)
            continue
        record["sha256"] = sha256_file(path)
        record["status"] = "PRESENT"

        asserts = item.get("asserts") or []
        if asserts and path.suffix != ".json":
            problems.append(
                f"{claim['id']}: asserts given for a non-JSON receipt {item['path']}"
            )
        elif asserts:
            document = json.loads(path.read_text(encoding="utf-8"))
            verified = []
            for assertion in asserts:
                pointer = assertion["pointer"]
                try:
                    actual = resolve_pointer(document, pointer)
                except (KeyError, IndexError, ValueError):
                    problems.append(
                        f"{claim['id']}: {item['path']} has no value at {pointer}"
                    )
                    continue
                if "equals" in assertion:
                    if actual != assertion["equals"]:
                        problems.append(
                            f"{claim['id']}: {item['path']}{pointer} is {actual!r}, "
                            f"claim says {assertion['equals']!r}"
                        )
                        continue
                elif "close_to" in assertion:
                    if abs(float(actual) - float(assertion["close_to"])) > 1e-6:
                        problems.append(
                            f"{claim['id']}: {item['path']}{pointer} is {actual!r}, "
                            f"claim says approximately {assertion['close_to']!r}"
                        )
                        continue
                else:
                    problems.append(f"{claim['id']}: assertion at {pointer} has no comparison")
                    continue
                verified.append({"pointer": pointer, "value": actual})
            record["verified_assertions"] = verified
        checked_evidence.append(record)

    # A claim may pin the source it was measured against. If the file moved, the
    # claim is about code that no longer exists and must not read as current.
    pinned: list[dict[str, Any]] = []
    for pin in claim.get("code_pinned", []) or []:
        source = ROOT / pin["path"]
        receipt_path = ROOT / claim["evidence"][0]["path"]
        if not source.exists():
            problems.append(f"{claim['id']}: pinned source missing: {pin['path']}")
            continue
        document = json.loads(receipt_path.read_text(encoding="utf-8"))
        try:
            recorded = resolve_pointer(document, pin["pointer_in_receipt"])
        except (KeyError, IndexError, ValueError):
            problems.append(
                f"{claim['id']}: receipt has no hash at {pin['pointer_in_receipt']}"
            )
            continue
        live = sha256_file(source)
        if recorded != live:
            problems.append(
                f"{claim['id']}: {pin['path']} has changed since the claim was "
                f"measured (receipt {recorded}, live {live})"
            )
        pinned.append(
            {
                "path": pin["path"],
                "recorded": recorded,
                "live": live,
                "match": recorded == live,
            }
        )

    # Every claim that is not terminal has to say where it lands.
    if claim.get("status") not in TERMINAL_STATUSES:
        if not claim.get("paper_section"):
            problems.append(f"{claim['id']}: no paper_section")
        if not claim.get("patent"):
            problems.append(f"{claim['id']}: no patent mapping")
    if not claim.get("limitations"):
        problems.append(f"{claim['id']}: no limitations recorded")

    return (
        {
            "id": claim["id"],
            "title": " ".join(str(claim["title"]).split()),
            "status": claim["status"],
            "scope": claim.get("scope", ""),
            "evidence": checked_evidence,
            "code_pinned": pinned,
            "permitted_wording": " ".join(str(claim.get("permitted_wording", "")).split()) or None,
            "forbidden_wording": claim.get("forbidden_wording", []),
            "limitations": claim.get("limitations", []),
            "paper_section": claim.get("paper_section"),
            "patent": claim.get("patent"),
        },
        problems,
    )


def render(verified: list[dict[str, Any]], receipt: dict[str, Any]) -> str:
    lines = [
        "# TAVONEL claim-evidence matrix",
        "",
        "**Generated — do not edit.** Source of truth is",
        "`docs/ip/claim-evidence-matrix.yaml`; regenerate with",
        "`python tools/ip/build_claim_evidence_matrix.py`.",
        "",
        "Every row below was verified against the receipt it cites: the file was",
        "hashed, and each asserted number was re-read out of the receipt by JSON",
        "pointer. The generator refuses to emit this file if any claim says",
        "something its receipt does not say.",
        "",
        f"Generated {receipt['generated_at']} · {len(verified)} claims · "
        f"matrix sha256 `{receipt['receipt_sha256'].split(':', 1)[1][:16]}…`",
        "",
        "## Summary",
        "",
        "| claim | status | paper | patent |",
        "|---|---|---|---|",
    ]
    for row in verified:
        lines.append(
            f"| `{row['id']}` | {row['status']} | {row['paper_section'] or '—'} | "
            f"{row['patent'] or '—'} |"
        )
    lines.append("")

    for row in verified:
        lines.extend([f"## {row['id']}", "", row["title"], "", f"**Status** {row['status']}"])
        if row["scope"]:
            lines.append(f"  ·  **Scope** {row['scope']}")
        lines.append("")
        if row["permitted_wording"]:
            lines.extend(["**Permitted wording**", "", f"> {row['permitted_wording']}", ""])
        if row["forbidden_wording"]:
            lines.append("**Must not be written as**")
            lines.append("")
            for bad in row["forbidden_wording"]:
                lines.append(f"- {bad}")
            lines.append("")
        lines.append("**Evidence**")
        lines.append("")
        for item in row["evidence"]:
            digest = item.get("sha256", "—")
            short = digest.split(":", 1)[1][:16] + "…" if digest != "—" else "—"
            lines.append(f"- `{item['path']}` — {item['status']}, sha256 `{short}`")
            for assertion in item.get("verified_assertions", []):
                lines.append(f"  - verified `{assertion['pointer']}` = `{assertion['value']}`")
        lines.append("")
        if row["code_pinned"]:
            lines.append("**Code pinned to this measurement**")
            lines.append("")
            for pin in row["code_pinned"]:
                state = "unchanged" if pin["match"] else "**CHANGED**"
                lines.append(f"- `{pin['path']}` — {state} since measurement")
            lines.append("")
        lines.append("**Limitations**")
        lines.append("")
        for limitation in row["limitations"]:
            lines.append(f"- {' '.join(str(limitation).split())}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument(
        "--markdown", type=Path, default=ROOT / "docs" / "ip" / "CLAIM_EVIDENCE_MATRIX.md"
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=ROOT / "docs" / "ip" / "receipts" / "claim-evidence-matrix.json",
    )
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    registry = yaml.safe_load(args.registry.read_text(encoding="utf-8"))
    verified: list[dict[str, Any]] = []
    problems: list[str] = []
    for claim in registry["claims"]:
        row, claim_problems = check_claim(claim)
        verified.append(row)
        problems.extend(claim_problems)

    if problems:
        print("claim-evidence matrix REFUSED to build:\n")
        for problem in problems:
            print(f"  - {problem}")
        print(f"\n{len(problems)} problem(s). Nothing was written.")
        return 1

    by_status: dict[str, int] = {}
    for row in verified:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1

    receipt = {
        "schema": "tavonel.claim-evidence-matrix-verification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "registry_sha256": sha256_file(args.registry),
        "generator_sha256": sha256_file(Path(__file__)),
        "claims": verified,
        "claim_count": len(verified),
        "status_counts": by_status,
        "all_assertions_verified": True,
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    if args.check_only:
        print(f"claim-evidence matrix OK - {len(verified)} claims, all assertions verified")
        return 0

    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render(verified, receipt), encoding="utf-8")
    print(f"claim-evidence matrix OK - {len(verified)} claims")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    print(f"wrote {args.markdown}")
    print(f"wrote {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
