"""U06 runner. `py -3.13 -m benchmark.u06_equivalence.run --manifest M.json --out DIR`.

Manifest (JSON): {"requested_at": ISO-8601 with tz, "tenant_id"?, "workspace_id"?, "collection_id"?,
"cases": [{"case_id", "stratum", "before": {"path", "sha256"}, "after": {"path", "sha256"}}]}.
Each path (relative to the manifest) holds a JSON list of ProductCoreDocument (camelCase).
`sha256` is of the file bytes; any mismatch refuses the whole run. Write --out outside the repo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from akc_product_core.contracts import ProductCoreDocument
from pydantic import TypeAdapter

from benchmark.u06_equivalence.harness import CaseResult, run_case

_DOCS = TypeAdapter(tuple[ProductCoreDocument, ...])


class ManifestHashMismatch(RuntimeError):
    pass


def _load(base: Path, ref: dict[str, str]) -> tuple[ProductCoreDocument, ...]:
    data = (base / ref["path"]).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != ref["sha256"].removeprefix("sha256:"):
        raise ManifestHashMismatch(f"{ref['path']}: sha256 {actual} != manifest {ref['sha256']}")
    return _DOCS.validate_json(data)


def summarize(rows: list[tuple[str, CaseResult]]) -> dict[str, object]:
    holds: Counter[str] = Counter()
    strata: dict[str, Counter[str]] = {}
    for stratum, result in rows:
        bucket = strata.setdefault(stratum, Counter())
        bucket[result.verdict.lower()] += 1
        bucket["phantom"] += result.phantom
        if result.verdict == "HOLD":
            holds.update(result.hold_reasons)
    return {
        "cases": len(rows),
        "equal": sum(r.verdict == "EQUAL" for _, r in rows),
        "hold": sum(r.verdict == "HOLD" for _, r in rows),
        "hold_by_reason": dict(holds),
        "diverged": sum(r.verdict == "DIVERGED" for _, r in rows),
        "phantom_total": sum(r.phantom for _, r in rows),
        "per_stratum": {k: dict(v) for k, v in strata.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw)
    scope = {
        k: manifest[k] for k in ("tenant_id", "workspace_id", "collection_id") if k in manifest
    }
    requested_at = datetime.fromisoformat(manifest["requested_at"])
    rows: list[tuple[str, CaseResult]] = []
    try:  # verify every hash before running anything or writing anything
        loaded = [
            (c, _load(args.manifest.parent, c["before"]), _load(args.manifest.parent, c["after"]))
            for c in manifest["cases"]
        ]
    except ManifestHashMismatch as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as sink:
        for case, before, after in loaded:
            result = run_case(before, after, requested_at=requested_at, **scope)
            rows.append((case["stratum"], result))
            line = {"case_id": case["case_id"], "stratum": case["stratum"], **asdict(result)}
            sink.write(json.dumps(line) + "\n")
    git_sha = subprocess.run(
        [shutil.which("git") or "git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    summary = {
        **summarize(rows),
        "git_sha": git_sha,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "python": platform.python_version(),
        "host": platform.node(),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 1 if summary["diverged"] or summary["phantom_total"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
