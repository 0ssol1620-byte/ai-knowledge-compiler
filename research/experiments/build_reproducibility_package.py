"""Assemble the reproducibility package for audit section 28-E.

28-E asks for exact commits, model revisions, dataset revisions, input
manifests, SHA-256s, scripts, environment identity, raw immutable receipts,
and final tables generated from receipts rather than hand-entered.

This walks the claims established in this session, resolves every artifact
they depend on, hashes it on disk, and emits a single manifest. It refuses to
emit a manifest with a missing or unhashable dependency, so an incomplete
package fails loudly instead of shipping with holes.

Read-only apart from writing its own receipt.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

VKC = Path(r"D:\CodexProjects\ai-knowledge-compiler-vkc-research")
OUT = VKC / "research" / "experiments" / "REPRODUCIBILITY_PACKAGE.json"

# Every artifact a reader needs to re-run what this session established.
ARTIFACTS: dict[str, list[str]] = {
    "C-36 eCFR regulatory robustness": [
        "research/experiments/H3-B-REGULATORY-ECFR-01/protocol.json",
        "research/experiments/H3-B-REGULATORY-ECFR-01/run_experiment.py",
        "research/experiments/H3-B-REGULATORY-ECFR-01/receipts/pre-fetch-seal.json",
        "research/experiments/H3-B-REGULATORY-ECFR-01/receipts/regulatory-revision-result.json",
        "research/experiments/H3-B-REGULATORY-ECFR-02/protocol.json",
        "research/experiments/H3-B-REGULATORY-ECFR-02/run_experiment.py",
        "research/experiments/H3-B-REGULATORY-ECFR-02/receipts/pre-fetch-seal.json",
        "research/experiments/H3-B-REGULATORY-ECFR-02/receipts/regulatory-revision-result.json",
        "research/experiments/H3-B-CURRENT-CORE-PUBLIC-REVISION-01/run_experiment.py",
    ],
    "C-37 preservation fault injection": [
        "research/experiments/PRESERVATION-E2E-01/protocol.json",
        "research/experiments/PRESERVATION-E2E-01/run_experiment.py",
        "research/experiments/PRESERVATION-E2E-01/receipts/pre-run-seal.json",
        "research/experiments/PRESERVATION-E2E-01/receipts/result.json",
        "research/experiments/PRESERVATION-E2E-02/protocol.json",
        "research/experiments/PRESERVATION-E2E-02/run_experiment.py",
        "research/experiments/PRESERVATION-E2E-02/receipts/pre-run-seal.json",
        "research/experiments/PRESERVATION-E2E-02/receipts/result.json",
        "packages/cir-python/src/akc_cir/semantic_preservation.py",
    ],
    "28-G adversarial review": [
        "research/experiments/adversarial_review_28g.py",
        "research/experiments/ADVERSARIAL_REVIEW_28G_2026-09-01.txt",
    ],
    "SEM-RISK-CONF-02 frozen instrument": [
        "research/experiments/SEM-RISK-CONF-02/protocol.json",
        "research/experiments/SEM-RISK-CONF-02/verify_frozen_integrity.py",
        "research/experiments/SEM-RISK-CONF-02/receipts/lane-a-native-freeze.json",
        "research/experiments/SEM-RISK-CONF-02/inference-manifests/lane-a-public-core.json",
    ],
    "runtime image definitions": [
        "infra/runpod/v6/images/mineru-3.4.4-vlm-c1/Dockerfile",
        "infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/Dockerfile",
        "infra/runpod/v6/qualification/rq-01/KNOWN_ISSUES.md",
        "benchmark/v6/candidate-registry.yaml",
        ".github/workflows/baked-confirmatory-images.yml",
    ],
}

# Upstream identities the results depend on but which live outside the repo.
EXTERNAL_PINS = {
    "mineru_model": {
        "repo_id": "opendatalab/MinerU2.5-Pro-2605-1.2B",
        "revision": "bff20d4ae2bf202df9f45284b4d43681555a97ed",
        "file_count": 13,
        "bytes": 2328028720,
        "artifact_manifest_sha256": "sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84",
        "verified_against": "benchmark/reports/mineru-3.4.4-vlm-concurrency-diagnostic-2026-08-01.json",
        "verification_note": "file count and byte total re-queried from the Hugging Face API on 2026-09-01 and matched the 2026-08-01 record exactly",
    },
    "mineru_source": {
        "repo": "https://github.com/opendatalab/MinerU.git",
        "revision": "79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7",
    },
    "paddle_runtime": {
        "status": "BLOCKED",
        "reason": "fastdeploy-gpu 2.3.0 withdrawn from PyPI and the vendor CDN; see INC-RUNPOD-05",
        "frozen_manifest": "benchmark/reports/paddleocr-vl-1.6-fastdeploy-runtime-manifest-2026-08-01.json",
    },
    "ecfr_api": {
        "base": "https://www.ecfr.gov/api/versioner/v1",
        "note": "eCFR serves current content; the receipts pin the fetched bytes by sha256 so a later upstream edit is detectable",
    },
}


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(VKC), capture_output=True, text=True, timeout=60
    ).stdout.strip()


def main() -> int:
    missing: list[str] = []
    groups: dict[str, list[dict[str, object]]] = {}

    for group, rels in ARTIFACTS.items():
        entries = []
        for rel in rels:
            path = VKC / rel
            if not path.exists():
                missing.append(rel)
                continue
            entries.append(
                {"path": rel, "sha256": sha256(path), "bytes": path.stat().st_size}
            )
        groups[group] = entries

    if missing:
        print("REFUSING to emit an incomplete package. Missing:")
        for rel in missing:
            print(f"  {rel}")
        return 1

    package = {
        "schema": "tavonel.reproducibility-package.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "closes_audit_section": "28-E",
        "scope": (
            "artifacts required to reproduce the claims established in the "
            "2026-09-01 session (C-36, C-37) and to audit the state of the "
            "blocked Paddle lane"
        ),
        "repository": {
            "name": "ai-knowledge-compiler-vkc-research",
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "note": (
                "the experiments are pure-Python and GPU-free; the runtime "
                "image definitions are included for the GPU work that remains"
            ),
        },
        "external_pins": EXTERNAL_PINS,
        "artifacts": groups,
        "artifact_count": sum(len(v) for v in groups.values()),
        "gpu_seconds": 0.0,
        "estimated_cost_usd": 0.0,
    }

    body = json.dumps(package, indent=2, sort_keys=True)
    package["package_sha256"] = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    OUT.write_text(json.dumps(package, indent=2, sort_keys=True), encoding="utf-8")

    print(f"wrote {OUT.relative_to(VKC)}")
    print(f"  artifacts : {package['artifact_count']}")
    print(f"  commit    : {package['repository']['commit'][:12]}")
    print(f"  dirty     : {package['repository']['dirty']}")
    print(f"  package   : {package['package_sha256']}")
    for group, entries in groups.items():
        print(f"  {len(entries):>2}  {group}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
