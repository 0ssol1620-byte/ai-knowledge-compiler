#!/usr/bin/env python3
"""v18 -- point the sealed Stage-1 controller at the A9 confirmatory holdout.

Everything below v18 is unchanged and stays authoritative: v17's CUDA lower
bound, v16's reattachable control token, v15's proxy readiness, v14's community
hosts, and v7's R2 upload, preflight, GT-free tar verification and cleanup with
absence proof. v18 changes exactly one thing -- **which sealed input bundle the
run consumes** -- and it does so by rebinding four module attributes on the base
layer rather than by editing any of them.

Why the base layer and not a new controller: the hard-200 constants are bound at
v7 module scope and read inside `require_preconditions()`. Rebinding them there
means every downstream check still runs against the holdout artifacts, which is
the point -- the goal is to reuse the integrity contract, not to route around it.

`require_preconditions` itself is replaced rather than patched, because its one
hard-coded value is the input count. The replacement performs the same checks in
the same order with the count read from the bundle receipt, and adds two the
original could not: that the READY it is handed is the holdout READY, and that
the bundle receipt binds the frozen holdout manifest. The GT-free, override-
forbidden, CRITICAL=0 and assembly-identity checks are copied verbatim.

**No READY file is edited by this module.** The holdout READY was derived by the
sealed generator from the same GPU qualification receipt, and the hard-200 READY
is untouched on disk.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SCRATCH = ROOT / ".chatgpt2codex"
HOLDOUT_DIR = SCRATCH / "a9-holdout-800-v1"

HOLDOUT_READY = HOLDOUT_DIR / "ovisocr2-v29-holdout800-ready.json"
HOLDOUT_BUNDLE = HOLDOUT_DIR / "holdout-800-source-only.tar"
HOLDOUT_BUNDLE_RECEIPT = HOLDOUT_DIR / "holdout-800-source-only.receipt.json"
HOLDOUT_OUT_ROOT = HOLDOUT_DIR / "runs"

# v4's driver hard-codes a 200-page cohort and a 90-minute inference timeout.
# 800 pages at the measured 6.71 s/page lands inside a minute of that limit, so
# a correct run would be killed for being large. v5 reads the cohort from the
# hash-bound shard manifest and scales the timeout from it.
HOLDOUT_DRIVER = Path(__file__).with_name("stage1_same_pod_driver_v5_holdout.py")

_spec = importlib.util.spec_from_file_location(
    "stage1_v17", Path(__file__).with_name("run_stage1_v29_r2_v17_cuda_at_least.py")
)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v17 module cannot be loaded")
v17 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v17
_spec.loader.exec_module(v17)

base = v17.v10.base  # the v7 layer, where the bundle constants live


def require_holdout_preconditions() -> dict[str, Any]:
    """v7's preconditions with the count read rather than assumed."""
    for path in (
        HOLDOUT_READY,
        base.FORMAL_QUAL,
        base.QUALIFIER,
        HOLDOUT_DRIVER,
        base.RUNNER,
        base.INPUT_CONTRACT,
        base.MODEL_RECEIPT,
        base.SECURITY_RECEIPT,
        HOLDOUT_BUNDLE,
        HOLDOUT_BUNDLE_RECEIPT,
    ):
        if not path.is_file():
            raise RuntimeError(f"Stage-1 prerequisite is missing: {path.name}")

    ready = base.read_object(HOLDOUT_READY)
    formal = base.read_object(base.FORMAL_QUAL)
    model = base.read_object(base.MODEL_RECEIPT)
    security = base.read_object(base.SECURITY_RECEIPT)
    bundle = base.read_object(HOLDOUT_BUNDLE_RECEIPT)

    if ready.get("schema") != "tavonel.verified-runtime-assembly-ready.v1":
        raise RuntimeError("v29 READY schema drifted")
    if ready.get("qualification_state") != "READY":
        raise RuntimeError("v29 runtime is not READY")
    if ready.get("fresh_pod_must_reverify_assembly_before_public_benchmark") is not True:
        raise RuntimeError("v29 READY does not require fresh-Pod requalification")
    if ready.get("manual_ready_override_allowed") is not False:
        raise RuntimeError("v29 READY unexpectedly permits manual override")
    if int(ready.get("persistent_volume_gb", -1)) != 0:
        raise RuntimeError("v29 READY persistent-volume contract drifted")
    if int(ready.get("critical_vulnerability_count", -1)) != 0:
        raise RuntimeError("v29 READY does not bind CRITICAL=0")
    if formal.get("passed") is not True or formal.get("provider_cleanup_verified") is not True:
        raise RuntimeError("formal v29 qualification/cleanup is not PASS")
    if formal.get("assembly_id") != ready.get("assembly_id"):
        raise RuntimeError("v29 formal/READY assembly id mismatch")
    if formal.get("model_artifact_sha256") != ready.get("model_artifact_sha256"):
        raise RuntimeError("v29 formal/READY model identity mismatch")
    if model.get("repository") != "ATH-MaaS/OvisOCR2" or int(model.get("file_count", -1)) != 14:
        raise RuntimeError("Ovis model receipt drifted")
    if security.get("inrelease_packages_hash_match") is not True:
        raise RuntimeError("security receipt is not Ubuntu-index-bound")

    expected = int(bundle.get("input_count", -1))
    if expected < 1:
        raise RuntimeError("holdout bundle declares no inputs")
    if (
        bundle.get("ground_truth_mounted") is not False
        or bundle.get("ground_truth_in_bundle") is not False
    ):
        raise RuntimeError("holdout bundle is not GT-free")
    if (
        bundle.get("all_input_hashes_verified") is not True
        or bundle.get("shard_parent_binding_verified") is not True
    ):
        raise RuntimeError("holdout bundle integrity receipt is not PASS")
    if bundle.get("tar_sha256") != base.sha256_file(HOLDOUT_BUNDLE):
        raise RuntimeError("holdout bundle hash drifted")

    stage1 = ready.get("stage1")
    if not isinstance(stage1, dict) or stage1.get("bundle_sha256") != bundle.get("tar_sha256"):
        raise RuntimeError("READY does not bind the sealed holdout bundle")
    if int(stage1.get("input_count", -1)) != expected:
        raise RuntimeError("READY input count does not match the holdout bundle")

    # v18's own checks: the run must be against the frozen holdout, not a slice
    # that happens to be lying at the same path.
    provenance = HOLDOUT_DIR / "holdout-provenance.json"
    if not provenance.is_file():
        raise RuntimeError("holdout slice provenance sidecar is missing")
    sidecar = json.loads(provenance.read_text(encoding="utf-8"))
    if sidecar.get("role") != "a9_confirmatory_holdout":
        raise RuntimeError("slice is not the A9 confirmatory holdout")
    if sidecar.get("shard_content_sha256") != bundle.get("shard_content_sha256"):
        raise RuntimeError("holdout slice and bundle receipt disagree on the shard")
    if int(sidecar.get("page_count", -1)) != expected:
        raise RuntimeError("holdout slice page count does not match the bundle")

    return {
        "ready": ready,
        "formal": formal,
        "model": model,
        "security": security,
        "bundle": bundle,
    }


def rebind_result_validation() -> None:
    """Re-express v10's result validation with the cohort size read, not assumed.

    v10's `fetch_and_validate_results` compares the returned receipt and the
    downloaded run summary against a literal 200 in two places. On an 800-page
    run both fire *after* the archive has already been downloaded and the Pod
    cleaned up, so the run succeeds and the controller reports failure -- which
    is exactly what happened on the first holdout run (800/800 completed, 0
    failed, then `Stage-1 receipt input count drifted`).

    The function is rebuilt from v10's own source with the two literals replaced
    by the count the bundle receipt declares, rather than retyped, so no other
    check can drift in the copy. If v10's source stops containing those exact
    literals this raises instead of silently binding an unpatched function.
    """
    source = Path(v17.v10.__file__).read_text(encoding="utf-8")
    start = source.index("def fetch_and_validate_results(")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]

    expected = int(
        json.loads(HOLDOUT_BUNDLE_RECEIPT.read_text(encoding="utf-8"))["input_count"]
    )
    replacements = (
        ('int(stage_receipt.get("input_count", -1)) != 200', f"!= {expected}"),
        ('int(summary.get("input_count", -1)) != 200', f"!= {expected}"),
        ('"input_count": 200,', f'"input_count": {expected},'),
    )
    for needle, _ in replacements:
        if needle not in body:
            raise RuntimeError(f"v10 result validation drifted; not found: {needle}")
    body = body.replace(
        'int(stage_receipt.get("input_count", -1)) != 200',
        f'int(stage_receipt.get("input_count", -1)) != {expected}',
    )
    body = body.replace(
        'int(summary.get("input_count", -1)) != 200',
        f'int(summary.get("input_count", -1)) != {expected}',
    )
    body = body.replace('"input_count": 200,', f'"input_count": {expected},')

    namespace = dict(vars(v17.v10))
    exec(compile(body, "<v18-result-validation>", "exec"), namespace)  # noqa: S102
    v17.v10.fetch_and_validate_results = namespace["fetch_and_validate_results"]


def main() -> int:
    base.READY = HOLDOUT_READY
    base.BUNDLE = HOLDOUT_BUNDLE
    base.BUNDLE_RECEIPT = HOLDOUT_BUNDLE_RECEIPT
    base.OUT_ROOT = HOLDOUT_OUT_ROOT
    # v10 ships the driver from its own constant, not from the base layer, so
    # rebinding base.DRIVER alone would upload v4 and kill the run on timeout.
    base.DRIVER = HOLDOUT_DRIVER
    v17.v10.V4_DRIVER = HOLDOUT_DRIVER
    base.require_preconditions = require_holdout_preconditions
    rebind_result_validation()
    return int(v17.main())


if __name__ == "__main__":
    raise SystemExit(main())
