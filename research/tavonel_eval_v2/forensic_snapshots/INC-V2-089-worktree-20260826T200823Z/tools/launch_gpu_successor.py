#!/usr/bin/env python3
"""Unattended launcher for SOURCE_FACT_PROPAGATION_MODEL_V1 -- the GPU
successor study `tools/gpu_successor_preflight.py` gates and
`protocols/GPU_SUCCESSOR_STUDY_V1.yaml` defines.

The founder's advance authorisation is unusual: once V2R4 passes, SFI3
passes on fresh held-out material, and the four-link gate passes on the
ACTUAL frozen candidate universe, this study may run under <=6 GPU hours and
<=$40 with NO further human check-in. That means this file is reviewed
*before* the verdict exists, not after -- nobody looks at it again between
PASS and launch. Every refusal path below is load-bearing, not defensive
boilerplate.

The authority is NOT `sfi2-native-provenance`. That stem is retired: SFI2 is
frozen, FAIL, spent and permanently non-rescorable, and a search for a PASS
under it could never have succeeded. It was not replaced with a search under
an SFI3 stem either -- see layer 2.

Layers of refusal, all of which must clear before a single GPU second is
requested:

1. `gpu_successor_preflight.run()` returns `READY_TO_AUTHORIZE`. This
   launcher imports and calls the preflight; it does not re-derive or
   restate any of its gates (`G_GSP_*`). A blocked preflight blocks here,
   unconditionally, and every blocking gate it named is surfaced.
2. Two acceptance receipts, both named explicitly on the command line, are
   read again here and REVALIDATED -- not reinterpreted. `--sfi3-acceptance`
   says the fresh held-out study passed; `--four-link-acceptance` says the
   exact cohort about to run is followable end to end. Neither substitutes
   for the other: a study can pass over a cohort that is not this one. Each
   is verified by its own module (`sfi3_acceptance`, `four_link_acceptance`),
   whose digest must equal the digest the preflight gated on, and the
   four-link acceptance must bind the same manifest digest this launch runs.
   There is no stem, no glob and no `latest` anywhere in this path: one
   authority, one immutable path, one digest.
3. `gpu_successor_preflight.estimate_cost` (imported, not reimplemented) is
   used to project GPU-hours and dollars for the cohort size the preflight
   itself measured, and the projection must clear both the 6-hour and $40
   cap. This is a pre-flight *prediction*; see (5) for the live ceiling.
4. `--dry-run` is the default. Provisioning requires `--execute`, spelled
   out on the command line every time. There is no flag, argument or
   environment variable that skips any of the above -- see
   `test_no_bypass_flag_or_env_var_exists` in the test suite, which exists
   to catch a later edit that adds one.
5. If `--execute` clears every gate above, a `Watchdog` is armed the moment
   provisioning succeeds and tears the instance down at the same 6-hour
   cap, independent of whether anything else in this process is still
   running. A pre-flight estimate is a prediction; the watchdog is the
   spend limit.

Every run -- refused, dry-run, or executed -- writes an immutable receipt
via `evidence.write_immutable`, including the refusal paths. Nothing here
provisions or bills unless invoked as
`python launch_gpu_successor.py --execute` after every gate above has
already passed.

`RunpodPodProvisioner` (imported from `runpod_provisioner.py`, not defined
here) is wired against the real Runpod REST v1 and GraphQL pod-lifecycle APIs. It is split
into its own module rather than defined in this file because
`test_no_bypass_flag_or_env_var_exists` asserts this module's own source text
never mentions the `os` module's environment-variable readers, and reading
the Runpod API key legitimately needs exactly that -- see
`runpod_provisioner.py`'s module docstring for why the split exists and what
each Runpod surface is used for.

6. Even a fully-wired provisioner is bounded by a second, independent stop
   that does not depend on this process staying alive: every pod
   `runpod_provisioner.RunpodPodProvisioner.provision` creates carries a
   platform-side `terminateAfter` (Runpod's own GraphQL `stopAfter`/
   `terminateAfter` fields on `podFindAndDeployOnDemand`), capped at the same
   `CAP_GPU_HOURS`. If this launcher's own process is killed the instant
   after `--execute` succeeds -- the exact gap the in-process `Watchdog`
   cannot cover -- Runpod itself still tears the pod down at the cap. The two
   stops are independent on purpose: neither one's failure leaves spend
   unbounded on its own.

7. Pod lifecycle is not scientific execution. The current Runpod backend
   reports `execution_readiness.passed == false` because it has no pinned
   worker entrypoint, content-addressed input/output transport, terminal-status
   channel, live dollar-cap poll, or frozen reducer/scorer. `--execute` therefore
   refuses before pod creation until those prerequisites are implemented. A
   test backend can exercise the complete contract, but only a terminal
   `completed` result with verified input/output hashes, observed usage, and
   teardown proof becomes launcher outcome `COMPLETED`.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gpu_successor_execution as gse
import gpu_successor_preflight as gsp
from common import NS, now, rel, sha_file
from evidence import write_immutable
from gpu_successor_preflight import _safe_rel
from runpod_provisioner import RunpodPodProvisioner

RUNTIME_PROTOCOL = NS / "protocols" / "GPU_SUCCESSOR_RUNTIME_V1.yaml"

#: NO ENDPOINT ARITHMETIC LIVES HERE ANY MORE.
#:
#: This launcher used to carry seven SFI2 endpoint names and require every one
#: `MET`. That was SFI2's acceptance rule, SFI2 is frozen/FAIL/spent, and SFI3
#: does not work that way: it declares nine endpoints of which E1-E7 and E9 are
#: the PASS-contributing primaries, while E8 is a mandatory safety veto whose
#: clean state is `VETO_CLEAR_NO_POSITIVE_CREDIT` and never `MET`.
#:
#: Reimplementing that here would be a second acceptance rule, and two
#: implementations of an acceptance rule are two rules. `sfi3_acceptance` is the
#: single implementation; this file REVALIDATES its receipt and re-derives
#: nothing.
CAP_GPU_HOURS = gsp.CAP_GPU_HOURS
CAP_USD = gsp.CAP_USD
CAP_SECONDS = CAP_GPU_HOURS * 3600.0

RECEIPT_STEM = "gpu-successor-launch"


# ---------------------------------------------------------------------------
# provisioning
# ---------------------------------------------------------------------------


class Provisioner(Protocol):
    """What `launch()` needs from a provisioning backend. Tests supply a fake
    implementing this shape; production supplies
    `runpod_provisioner.RunpodPodProvisioner`, wired against the real Runpod
    APIs."""

    def provision(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Stand up the instance(s) described by `spec`. Returns a handle
        `teardown` can use to tear them back down."""
        ...

    def teardown(self, handle: dict[str, Any]) -> None:
        """Tear down whatever `provision` stood up. Must be safe to call more
        than once and must not raise merely because teardown was already
        performed."""
        ...

    def execution_readiness(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Return a typed, fail-closed readiness result before provisioning."""
        ...

    def execute_scientific_workload(
        self, handle: dict[str, Any], spec: dict[str, Any]
    ) -> dict[str, Any]:
        """Run through terminal completion and return a retrieved result."""
        ...


# ---------------------------------------------------------------------------
# the live spend ceiling -- a prediction is not a limit
# ---------------------------------------------------------------------------


class Watchdog:
    """Tears the provisioned instance down at the hard cap, independent of
    whether anything else in the process is still watching.

    `estimate_cost` in the preflight is a projection made before any GPU
    second is spent; it can be wrong. This is the mechanism that bounds
    actual spend regardless: once armed, it fires unconditionally at
    `cap_seconds` and calls `teardown`, whether or not the rest of the
    process is still alive to see it.
    """

    def __init__(self, cap_seconds: float, teardown: Any) -> None:
        self.cap_seconds = cap_seconds
        self.fired = False
        self._teardown = teardown
        self._timer = threading.Timer(cap_seconds, self._fire)
        self._timer.daemon = True

    def start(self) -> None:
        self._timer.start()

    def cancel(self) -> None:
        self._timer.cancel()

    def _fire(self) -> None:
        self.fired = True
        self._teardown()


# ---------------------------------------------------------------------------
# receipts -- every path, including refusal, including dry-run
# ---------------------------------------------------------------------------


def _write_receipt(
    *,
    outcome: str,
    reason: str,
    args: argparse.Namespace,
    preflight_body: dict[str, Any] | None,
    endpoint_gate: dict[str, Any] | None,
    cost: dict[str, Any] | None,
    gpu_seconds: float,
    estimated_cost_usd: float,
    provisioning: dict[str, Any] | None = None,
    actual_usage: dict[str, Any] | None = None,
    declaration_gate: dict[str, Any] | None = None,
    execution_readiness: dict[str, Any] | None = None,
    execution_result: dict[str, Any] | None = None,
    execution_authority_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": "tavonel.v2.gpu_successor_launch.v1",
        "study_id": gsp.STUDY_ID,
        "generated_at": now(),
        "outcome": outcome,
        "reason": reason,
        "invocation": {
            "execute": bool(getattr(args, "execute", False)),
            "manifest": _safe_rel(Path(args.manifest)),
            "runtime_image_digest": args.runtime_image_digest,
            "sfi3_acceptance": _safe_rel(Path(args.sfi3_acceptance))
            if args.sfi3_acceptance
            else None,
            "four_link_acceptance": _safe_rel(Path(args.four_link_acceptance))
            if args.four_link_acceptance
            else None,
            "materialized_inputs": _safe_rel(Path(args.materialized_inputs))
            if getattr(args, "materialized_inputs", None)
            else None,
            "model_pin_sha256": getattr(args, "model_pin_sha256", None),
            "protocol_freeze": _safe_rel(Path(args.protocol_freeze))
            if getattr(args, "protocol_freeze", None)
            else None,
            "protocol_freeze_sha256": getattr(args, "protocol_freeze_sha256", None),
        },
        "runtime_declaration": {
            "path": rel(RUNTIME_PROTOCOL),
            "sha256": sha_file(RUNTIME_PROTOCOL),
        },
        # Whether the declarations this launch ran under are the ones the
        # preflight gated on. `None` only on paths that refused before the
        # comparison was reached.
        "declaration_gate": declaration_gate,
        "preflight": preflight_body,
        "endpoint_gate": endpoint_gate,
        "projected_cost": cost,
        "gpu_seconds": gpu_seconds,
        "estimated_cost_usd": estimated_cost_usd,
        "provisioning": provisioning,
        # Never the estimate re-reported as if observed. `None` on every path
        # that never provisioned (REFUSED, DRY_RUN); on COMPLETED/
        # EXECUTE_FAILED it is whatever `RunpodPodProvisioner.teardown` wrote
        # into the handle -- real numbers read from the pod itself, or the
        # literal string `NOT_RETRIEVED` in both fields if that read failed.
        # See `runpod_provisioner.RunpodPodProvisioner._read_usage`.
        "actual_usage": actual_usage,
        "execution_readiness": execution_readiness,
        "execution_result": execution_result,
        "execution_authority_gate": execution_authority_gate,
        "hard_caps": {"gpu_hours": CAP_GPU_HOURS, "usd": CAP_USD},
    }
    written = write_immutable(
        RECEIPT_STEM, body, tool=Path(__file__).resolve(), protocol=RUNTIME_PROTOCOL
    )
    return {**body, **written}


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def _load_model_pin(args: argparse.Namespace) -> dict[str, Any]:
    if args.model_pin is not None:
        return json.loads(Path(args.model_pin).read_text(encoding="utf-8"))
    return gsp.default_model_pin()


def _declaration_gate(args: Any, preflight_body: dict[str, Any]) -> dict[str, Any]:
    """The declarations the preflight read are the declarations on disk now.

    Without this the launcher's only link to the preflight is that a receipt
    exists. The gates could have passed against one set of rules and the spend
    happen under another, and every receipt would still look clean -- the shape
    that ended the V2R3 chain, in the one place where the cost of missing it is
    billed GPU time rather than CPU.

    The digests are re-read here rather than trusted from the preflight body,
    because a body this process just built and a file on disk are different
    claims and only the second one is what a run would actually use.
    """
    actual = gsp.declaration_digests(
        manifest=args.manifest,
        model_pin=args.model_pin,
        sfi3_acceptance=args.sfi3_acceptance,
        four_link_acceptance=args.four_link_acceptance,
    )
    recorded = preflight_body.get("declarations")
    if not recorded:
        return {
            "passed": False,
            "reason": (
                "the preflight receipt records no study or runtime declaration "
                "digest, so there is nothing for this launcher to bind to"
            ),
            "recorded": None,
            "actual": actual,
        }
    #: Set equality on the declaration domain, both directions. A preflight that
    #: recorded five of six would otherwise pass the loop below on the five it
    #: has, and the sixth would be bound by nothing at all.
    missing = sorted(set(gsp.DECLARATION_KEYS) - set(recorded))
    extra = sorted(set(recorded) - set(gsp.DECLARATION_KEYS))
    if missing or extra:
        return {
            "passed": False,
            "reason": (
                "the preflight's declaration domain is not this launcher's: "
                f"missing={missing} unexpected={extra}"
            ),
            "recorded": recorded,
            "actual": actual,
        }
    absent = sorted(name for name, block in actual.items() if block["sha256"] == gsp.ABSENT)
    if absent:
        return {
            "passed": False,
            "reason": f"declaration or bound input missing on disk: {absent}",
            "recorded": recorded,
            "actual": actual,
        }
    moved = sorted(
        name
        for name, block in actual.items()
        if block["sha256"] != (recorded.get(name) or {}).get("sha256")
    )
    return {
        "passed": not moved,
        "reason": (
            f"{moved} changed between the preflight and this launch"
            if moved
            else "all six bound inputs are byte-identical to what the preflight gated on"
        ),
        "recorded": recorded,
        "actual": actual,
    }


def _acceptance_gate(args: argparse.Namespace, preflight_body: dict[str, Any]) -> dict[str, Any]:
    """Revalidate BOTH acceptances, and require the preflight to have used them.

    This is revalidation, not reinterpretation. The launcher re-runs each
    acceptance module against the receipt it was handed and compares the digest
    to the one the preflight recorded -- so an acceptance swapped between the two
    stages is refused, and neither stage's opinion of the study is taken on
    trust from the other.

    The four-link acceptance is additionally checked against the digest of the
    manifest THIS launch is about to run. A green four-link receipt over a
    different cohort authorizes nothing about this one.
    """
    import four_link_acceptance as fla
    import sfi3_acceptance as sfi3

    manifest = Path(args.manifest)
    manifest_digest = sha_file(manifest) if manifest.is_file() else None

    checks: dict[str, Any] = {}
    problems: list[str] = []
    for label, path, module, kwargs in (
        ("sfi3", args.sfi3_acceptance, sfi3, {}),
        (
            "four_link",
            args.four_link_acceptance,
            fla,
            {"launch_manifest_sha256": manifest_digest},
        ),
    ):
        gate_name = (
            "G_GSP_SFI3_ACCEPTANCE_PASS" if label == "sfi3" else "G_GSP_FOUR_LINK_ACCEPTANCE_PASS"
        )
        recorded = ((preflight_body.get("gates") or {}).get(gate_name) or {}).get("detail") or {}
        if path is None or not Path(path).is_file():
            problems.append(f"no {label} acceptance receipt was named to this launcher")
            checks[label] = {"passed": False, "receipt": None}
            continue
        digest = sha_file(Path(path))
        if recorded.get("receipt_sha256") != digest:
            problems.append(
                f"the {label} acceptance this launcher was given "
                f"({digest}) is not the one the preflight gated on "
                f"({recorded.get('receipt_sha256')})"
            )
            checks[label] = {"passed": False, "receipt": _safe_rel(Path(path))}
            continue
        try:
            verify_authority = getattr(module, "verify_authority", None)
            if verify_authority is not None:
                if kwargs:
                    raise module.AcceptanceRefused(
                        "single-authority verification does not accept alternate arguments"
                    )
                verify_authority(Path(path))
            else:
                module.verify(json.loads(Path(path).read_text(encoding="utf-8")), **kwargs)
        except module.AcceptanceRefused as error:
            problems.append(f"{label}: {error}")
            checks[label] = {"passed": False, "receipt": _safe_rel(Path(path))}
            continue
        checks[label] = {
            "passed": True,
            "receipt": _safe_rel(Path(path)),
            "receipt_sha256": digest,
        }

    return {
        "passed": not problems,
        "checks": checks,
        "launch_manifest_sha256": manifest_digest,
        "reason": (
            "; ".join(problems)
            if problems
            else (
                "both acceptances revalidated against the receipts the preflight "
                "gated on, and the four-link cohort is the manifest about to run"
            )
        ),
        "revalidated_not_reinterpreted": (
            "each acceptance module was re-run against its own receipt. This "
            "launcher carries no endpoint arithmetic of its own."
        ),
    }


def _execution_authority_gate(
    args: argparse.Namespace, preflight_body: dict[str, Any]
) -> dict[str, Any]:
    """Re-bind the exact model-pin and protocol-freeze files for execution.

    The preflight performs the semantic validation.  The launcher independently
    requires the same explicit paths and expected file hashes, re-hashes both
    files, and checks that the READY preflight recorded those same identities.
    """
    problems: list[str] = []
    checks: dict[str, Any] = {}
    for label, path_value, expected_value, gate_name in (
        (
            "model_pin",
            getattr(args, "model_pin", None),
            getattr(args, "model_pin_sha256", None),
            "G_GSP_MODEL_PIN_SOURCE_SEALED",
        ),
        (
            "protocol_freeze",
            getattr(args, "protocol_freeze", None),
            getattr(args, "protocol_freeze_sha256", None),
            "G_GSP_PROTOCOL_BUNDLE_FROZEN",
        ),
    ):
        path = Path(path_value) if path_value is not None else None
        expected = str(expected_value).lower() if expected_value is not None else None
        if expected is not None and not expected.startswith("sha256:"):
            expected = "sha256:" + expected
        actual = sha_file(path) if path is not None and path.is_file() else None
        recorded = (preflight_body.get("gates") or {}).get(gate_name) or {}
        detail = recorded.get("detail") or {}
        recorded_expected = detail.get("expected_file_sha256")
        recorded_actual = detail.get("actual_file_sha256")
        passed = (
            path is not None
            and expected is not None
            and bool(gsp.SHA256_PATTERN.fullmatch(expected))
            and actual == expected
            and recorded.get("passed") is True
            and recorded_expected == expected
            and recorded_actual == actual
        )
        if not passed:
            problems.append(
                f"{label} exact path/hash is absent, drifted, or not the identity "
                "the preflight verified"
            )
        checks[label] = {
            "passed": passed,
            "path": _safe_rel(path) if path is not None else None,
            "expected_file_sha256": expected,
            "actual_file_sha256": actual,
            "preflight_gate": gate_name,
        }
    return {
        "passed": not problems,
        "checks": checks,
        "reason": "; ".join(problems) if problems else "exact execution authorities revalidated",
    }


def launch(
    args: argparse.Namespace, provisioner: Provisioner | None = None
) -> tuple[int, dict[str, Any]]:
    """Run every gate in order and either refuse, dry-run, or execute.

    Returns `(exit_code, receipt)`. `provisioner` is injected for tests; a
    real invocation lets it default to
    `runpod_provisioner.RunpodPodProvisioner`.
    """
    model_pin = _load_model_pin(args)

    preflight_body = gsp.run(
        manifest=Path(args.manifest),
        model_pin=model_pin,
        runtime_image_digest=args.runtime_image_digest,
        sfi3_acceptance_receipt=args.sfi3_acceptance,
        four_link_acceptance_receipt=args.four_link_acceptance,
        model_pin_path=args.model_pin,
        model_pin_sha256=getattr(args, "model_pin_sha256", None),
        protocol_freeze_receipt=getattr(args, "protocol_freeze", None),
        protocol_freeze_sha256=getattr(args, "protocol_freeze_sha256", None),
    )

    if preflight_body["verdict"] != "READY_TO_AUTHORIZE":
        receipt = _write_receipt(
            outcome="REFUSED",
            reason=(
                "gpu_successor_preflight is not READY_TO_AUTHORIZE; blocking "
                f"gates: {preflight_body['blocking_gates']}"
            ),
            args=args,
            preflight_body=preflight_body,
            endpoint_gate=None,
            cost=None,
            gpu_seconds=0,
            estimated_cost_usd=0.0,
        )
        return 2, receipt

    endpoint_gate = _acceptance_gate(args, preflight_body)
    if not endpoint_gate["passed"]:
        receipt = _write_receipt(
            outcome="REFUSED",
            reason=f"the acceptance revalidation does not hold: {endpoint_gate['reason']}",
            args=args,
            preflight_body=preflight_body,
            endpoint_gate=endpoint_gate,
            cost=None,
            gpu_seconds=0,
            estimated_cost_usd=0.0,
        )
        return 3, receipt

    declarations = _declaration_gate(args, preflight_body)
    if not declarations["passed"]:
        receipt = _write_receipt(
            outcome="REFUSED",
            reason=(
                f"a bound input does not match what the preflight read: {declarations['reason']}"
            ),
            args=args,
            preflight_body=preflight_body,
            endpoint_gate=endpoint_gate,
            cost=None,
            gpu_seconds=0,
            estimated_cost_usd=0.0,
            declaration_gate=declarations,
        )
        return 5, receipt

    cohort_detail = preflight_body["gates"]["G_GSP_COHORT_FEASIBILITY"]["detail"]
    cohort_size = max(cohort_detail["floor"], cohort_detail["eligible_count"])
    cost = gsp.estimate_cost(cohort_size=cohort_size)
    if not cost["within_cap"]:
        receipt = _write_receipt(
            outcome="REFUSED",
            reason=(
                "projected cost exceeds the hard cap: "
                f"{cost['estimated_gpu_hours']:.4f}h / ${cost['estimated_cost_usd']:.2f} "
                f"against {CAP_GPU_HOURS}h / ${CAP_USD}"
            ),
            args=args,
            preflight_body=preflight_body,
            endpoint_gate=endpoint_gate,
            cost=cost,
            gpu_seconds=0,
            estimated_cost_usd=0.0,
            declaration_gate=declarations,
        )
        return 4, receipt

    if not args.execute:
        receipt = _write_receipt(
            outcome="DRY_RUN",
            reason="--execute was not passed; dry-run is the default and provisions nothing",
            args=args,
            preflight_body=preflight_body,
            endpoint_gate=endpoint_gate,
            cost=cost,
            gpu_seconds=0,
            estimated_cost_usd=0.0,
            declaration_gate=declarations,
        )
        return 0, receipt

    # --execute: authorization is necessary but not sufficient. Bind the exact
    # materialized input set and require a real scientific execution channel
    # before creating anything billable.
    execution_authority = _execution_authority_gate(args, preflight_body)
    if not execution_authority["passed"]:
        receipt = _write_receipt(
            outcome="REFUSED",
            reason=f"explicit execution authority failed: {execution_authority['reason']}",
            args=args,
            preflight_body=preflight_body,
            endpoint_gate=endpoint_gate,
            cost=cost,
            gpu_seconds=0.0,
            estimated_cost_usd=0.0,
            declaration_gate=declarations,
            execution_authority_gate=execution_authority,
        )
        return 6, receipt

    materialized_path = getattr(args, "materialized_inputs", None)
    if materialized_path is None:
        readiness = {
            "passed": False,
            "missing_prerequisites": [
                {
                    "code": "MATERIALIZED_INPUTS_NOT_NAMED",
                    "detail": "--execute requires one explicit immutable materialized input path",
                }
            ],
        }
        receipt = _write_receipt(
            outcome="REFUSED",
            reason="scientific execution is not ready: materialized inputs were not named",
            args=args,
            preflight_body=preflight_body,
            endpoint_gate=endpoint_gate,
            cost=cost,
            gpu_seconds=0.0,
            estimated_cost_usd=0.0,
            declaration_gate=declarations,
            execution_readiness=readiness,
            execution_authority_gate=execution_authority,
        )
        return 6, receipt

    try:
        input_contract = gse.load_input_contract(Path(materialized_path), Path(args.manifest))
    except gse.ExecutionContractError as error:
        readiness = {
            "passed": False,
            "missing_prerequisites": [
                {"code": "MATERIALIZED_INPUT_CONTRACT_INVALID", "detail": str(error)}
            ],
        }
        receipt = _write_receipt(
            outcome="REFUSED",
            reason="scientific execution is not ready: materialized input contract failed",
            args=args,
            preflight_body=preflight_body,
            endpoint_gate=endpoint_gate,
            cost=cost,
            gpu_seconds=0.0,
            estimated_cost_usd=0.0,
            declaration_gate=declarations,
            execution_readiness=readiness,
            execution_authority_gate=execution_authority,
        )
        return 6, receipt

    sealed_model_pin = gsp.load_model_pin_artifact(
        args.model_pin, getattr(args, "model_pin_sha256", None)
    )
    effective_model_pin = sealed_model_pin["resolved_pin"]
    model_pin_sha256 = execution_authority["checks"]["model_pin"]["actual_file_sha256"]
    spec = {
        "model_pin": effective_model_pin,
        "model_pin_sha256": model_pin_sha256,
        "runtime_image_digest": args.runtime_image_digest,
        "cohort_size": cohort_size,
        "projected_cost": cost,
        "input_contract": input_contract,
        # The scientific controller independently requires both exact receipt
        # identities; booleans without the revalidated file hashes authorize
        # nothing.
        "execution_authority": {
            "fresh_study_acceptance": endpoint_gate["checks"]["sfi3"]["passed"] is True,
            "fresh_study_acceptance_sha256": endpoint_gate["checks"]["sfi3"].get("receipt_sha256"),
            "fresh_study_acceptance_path": str(Path(args.sfi3_acceptance).resolve()),
            "four_link_acceptance": endpoint_gate["checks"]["four_link"]["passed"] is True,
            "four_link_acceptance_sha256": endpoint_gate["checks"]["four_link"].get(
                "receipt_sha256"
            ),
            "four_link_acceptance_path": str(Path(args.four_link_acceptance).resolve()),
        },
    }

    if provisioner is None:
        runtime_values = {
            "worker_bundle": getattr(args, "worker_bundle", None),
            "worker_bundle_sha256": getattr(args, "worker_bundle_sha256", None),
            "execution_ledger": getattr(args, "execution_ledger", None),
            "retrieved_output": getattr(args, "retrieved_output", None),
            "r2_endpoint_url": getattr(args, "r2_endpoint_url", None),
            "r2_bucket": getattr(args, "r2_bucket", None),
            "r2_region": getattr(args, "r2_region", None),
        }
        if not all(runtime_values.values()):
            readiness = RunpodPodProvisioner.execution_readiness(spec)
            active_provisioner: Provisioner | None = None
        else:
            try:
                from gpu_successor_runpod_backend import build_environment_backend

                active_provisioner = build_environment_backend(
                    worker_bundle_path=Path(runtime_values["worker_bundle"]),
                    worker_bundle_sha256=str(runtime_values["worker_bundle_sha256"]),
                    materialized_input_path=Path(materialized_path),
                    output_path=Path(runtime_values["retrieved_output"]),
                    ledger_path=Path(runtime_values["execution_ledger"]),
                    r2_endpoint_url=str(runtime_values["r2_endpoint_url"]),
                    r2_bucket=str(runtime_values["r2_bucket"]),
                    r2_region=str(runtime_values["r2_region"]),
                )
                readiness = active_provisioner.execution_readiness(spec)
            except Exception as error:
                active_provisioner = None
                readiness = {
                    "passed": False,
                    "missing_prerequisites": [
                        {
                            "code": "EXPLICIT_RUNTIME_BACKEND_CONFIGURATION_FAILED",
                            "detail": f"{type(error).__name__}; backend detail suppressed",
                        }
                    ],
                }
    else:
        active_provisioner = provisioner
        readiness_fn = getattr(active_provisioner, "execution_readiness", None)
        readiness = (
            readiness_fn(spec)
            if callable(readiness_fn)
            else {
                "passed": False,
                "missing_prerequisites": [
                    {
                        "code": "BACKEND_EXECUTION_CONTRACT_ABSENT",
                        "detail": "backend has no execution_readiness contract",
                    }
                ],
            }
        )
    if readiness.get("passed") is not True:
        receipt = _write_receipt(
            outcome="REFUSED",
            reason="scientific execution backend is not ready; no pod was provisioned",
            args=args,
            preflight_body=preflight_body,
            endpoint_gate=endpoint_gate,
            cost=cost,
            gpu_seconds=0.0,
            estimated_cost_usd=0.0,
            declaration_gate=declarations,
            execution_readiness=readiness,
            execution_authority_gate=execution_authority,
        )
        return 6, receipt
    if active_provisioner is None:
        # This branch is reachable only after the real backend eventually
        # advertises a complete execution transport. Credential loading stays
        # after readiness so a fail-closed audit never needs a secret.
        active_provisioner = RunpodPodProvisioner()

    handle: dict[str, Any] | None = None
    watchdog: Watchdog | None = None
    outcome = "EXECUTE_FAILED"
    error_text: str | None = None
    raw_result: dict[str, Any] | None = None
    validated_result: dict[str, Any] | None = None
    try:
        handle = active_provisioner.provision(spec)
        watchdog = Watchdog(CAP_SECONDS, lambda: active_provisioner.teardown(handle))
        watchdog.start()
        raw_result = active_provisioner.execute_scientific_workload(handle, spec)
    except Exception as error:
        # Exception bodies can echo request headers or credentials. Receipts
        # persist the phase and exception type, never the backend's raw text.
        error_text = f"{type(error).__name__}: execution failed; backend detail suppressed"
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if handle is not None:
            try:
                active_provisioner.teardown(handle)
            except Exception as teardown_error:
                note = (
                    "teardown also failed; backend detail suppressed "
                    f"({type(teardown_error).__name__})"
                )
                error_text = f"{error_text}; {note}" if error_text else note

    actual_usage = handle.get("actual_usage") if handle is not None else None
    if error_text is None and raw_result is not None and handle is not None:
        try:
            validated_result = gse.validate_terminal_result(
                raw_result,
                contract=input_contract,
                runtime_image_digest=args.runtime_image_digest,
                model_pin_sha256=model_pin_sha256,
                handle=handle,
            )
            outcome = "COMPLETED"
        except gse.ExecutionContractError as error:
            error_text = f"ExecutionContractError: {error}"

    observed_gpu_seconds = 0.0
    observed_cost_usd = 0.0
    if validated_result is not None:
        observed = validated_result["observed_usage"]
        observed_gpu_seconds = observed["gpu_seconds"]
        observed_cost_usd = observed["cost_usd"]

    public_provisioning = None
    if handle is not None:
        public_provisioning = {
            "pod_id": handle.get("pod_id") or handle.get("id"),
            "gpu_type": handle.get("gpu_type"),
            "gpu_count": handle.get("gpu_count"),
            "image_digest": handle.get("image_digest"),
            "runpod_terminate_after": handle.get("runpod_terminate_after"),
            "torn_down": handle.get("torn_down") is True,
        }

    receipt = _write_receipt(
        outcome=outcome,
        reason=error_text or "terminal scientific output validated and teardown verified",
        args=args,
        preflight_body=preflight_body,
        endpoint_gate=endpoint_gate,
        cost=cost,
        gpu_seconds=observed_gpu_seconds,
        estimated_cost_usd=observed_cost_usd,
        declaration_gate=declarations,
        provisioning=public_provisioning,
        actual_usage=actual_usage,
        execution_readiness=readiness,
        execution_result=validated_result,
        execution_authority_gate=execution_authority,
    )
    return (0 if outcome == "COMPLETED" else 5), receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=NS / "artifacts" / "development" / "typed_fact_cohort.json",
        help="a manifest of extracted SourceFact records, if one has been built",
    )
    parser.add_argument(
        "--model-pin",
        type=Path,
        default=None,
        help="a JSON file with repository/revision/tokenizer_file_sha256/capability_evidence",
    )
    parser.add_argument(
        "--runtime-image-digest",
        default="runpod/pytorch@sha256:0a360022e8de4375af99430f84e8b38951acc397252163a37ceac7204d01be35",
    )
    parser.add_argument(
        "--sfi3-acceptance",
        type=Path,
        default=None,
        help=(
            "explicit SOURCE_FACT_IR_HELDOUT_ACCEPTANCE_V1 receipt. No default and "
            "no search: GPU authority is one immutable path and one digest."
        ),
    )
    parser.add_argument(
        "--four-link-acceptance",
        type=Path,
        default=None,
        help="explicit FOUR_LINK_ACCEPTANCE_V1 receipt for the cohort about to run",
    )
    parser.add_argument("--worker-bundle", type=Path, default=None)
    parser.add_argument("--worker-bundle-sha256", default=None)
    parser.add_argument("--execution-ledger", type=Path, default=None)
    parser.add_argument("--retrieved-output", type=Path, default=None)
    parser.add_argument("--r2-endpoint-url", default=None)
    parser.add_argument("--r2-bucket", default=None)
    parser.add_argument("--r2-region", default=None)
    parser.add_argument(
        "--model-pin-sha256",
        default=None,
        help="expected exact file SHA-256 for --model-pin; required with --execute",
    )
    parser.add_argument(
        "--materialized-inputs",
        type=Path,
        default=None,
        help=(
            "explicit immutable successor-materialized-inputs receipt. Required "
            "with --execute; never discovered by glob or latest pointer."
        ),
    )
    parser.add_argument(
        "--protocol-freeze",
        type=Path,
        default=None,
        help="exact immutable GPU study/runtime protocol-bundle freeze receipt",
    )
    parser.add_argument(
        "--protocol-freeze-sha256",
        default=None,
        help="expected exact file SHA-256 for --protocol-freeze; required with --execute",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help=(
            "actually provision. Without this flag the launcher only ever "
            "dry-runs, regardless of what the gates above decide."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    code, receipt = launch(args)
    summary = {
        "run_id": receipt.get("run_id"),
        "receipt": receipt.get("receipt"),
        "outcome": receipt.get("outcome"),
        "reason": receipt.get("reason"),
        "blocking_gates": (receipt.get("preflight") or {}).get("blocking_gates"),
    }
    print(json.dumps(summary, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
