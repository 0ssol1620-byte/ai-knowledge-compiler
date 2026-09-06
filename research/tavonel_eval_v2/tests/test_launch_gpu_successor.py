"""Tests for `tools/launch_gpu_successor.py` -- the sixteen red controls of the
GPU authorization route, plus the green direction that keeps them honest.

Nothing here provisions. Every test either calls `launch()` with a fake
`Provisioner` (never `RunpodPodProvisioner`) or exercises the pure gate
functions directly. `RunpodPodProvisioner` itself is only ever driven through
`httpx.MockTransport` in the final section, so no test in this file can reach
the network, request a GPU second or bill a dollar.

The route this file guards has exactly two authorities, and it is worth being
precise about what each one answers:

    --sfi3-acceptance        the fresh held-out SOURCE_FACT_IR study PASSED
    --four-link-acceptance   THIS cohort has a complete four-link chain

Neither substitutes for the other. A study can pass over a cohort that is not
the one about to run, and a followable cohort says nothing about whether the
instrument works. Both are named explicitly, by immutable path, and bound by
SHA-256: there is no stem, no glob and no `latest` anywhere on this route,
because the defect being repaired (INC-V2-069) was a stem search that could
never succeed and had no way to say so.

The launcher carries NO endpoint arithmetic of its own. It used to require
seven SFI2 endpoints all `MET`; SFI3 declares nine of which E8 is a safety veto
that must never read `MET`, and two implementations of an acceptance rule are
two rules. Every endpoint question below is asked of `sfi3_acceptance`, which is
the single implementation, and this file checks that the launcher revalidates
rather than reinterprets.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS / "source_fact_ir"))

import gpu_authorization_fixtures as fixtures  # noqa: E402
import gpu_successor_execution as gse  # noqa: E402
import gpu_successor_preflight as gsp  # noqa: E402
import launch_gpu_successor as launcher  # noqa: E402
import runpod_provisioner as rp  # noqa: E402
import sfi3_acceptance as acc  # noqa: E402

from infra.runpod.v6.credentials import RunPodCredentialSet  # noqa: E402
from common import canonical_sha, sha_file, sha_text  # noqa: E402

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def route(tmp_path, monkeypatch):
    """A fully-wired authorization route: manifest, both acceptances, args.

    The acceptance receipts are REAL -- they are the artefacts the genuine
    `sfi3_acceptance.verify` and `four_link_acceptance.verify` accept. A fixture
    that monkeypatched the verifiers would produce a gate agreeing with itself,
    which is the failure this whole route exists to prevent.
    """

    def build(*, execute: bool = False, model_pin: Path | None = None) -> argparse.Namespace:
        sfi3 = fixtures.land_sfi3_acceptance(tmp_path, monkeypatch)
        manifest, four_link = fixtures.land_four_link_acceptance(tmp_path, monkeypatch)
        manifest_body = json.loads(manifest.read_text(encoding="utf-8"))
        materialized_items = []
        for fact in manifest_body["facts"]:
            item = {
                "fact_id": fact["fact_id"],
                "arms": {
                    gse.ARMS[0]: {"fixture": "current"},
                    gse.ARMS[1]: {"fixture": "stale"},
                },
            }
            item["item_digest"] = canonical_sha(item)
            materialized_items.append(item)
        materialized = tmp_path / "successor-materialized-inputs.json"
        materialized.write_text(
            json.dumps(
                {
                    "schema": gse.MATERIALIZED_SCHEMA,
                    "study_id": gsp.STUDY_ID,
                    "manifest_facts_digest": manifest_body["facts_digest"],
                    "item_count": len(materialized_items),
                    "items": materialized_items,
                    "set_digest": canonical_sha(
                        [item["item_digest"] for item in materialized_items]
                    ),
                }
            ),
            encoding="utf-8",
        )
        if model_pin is None:
            #: A READY preflight cannot exist without one -- `G_GSP_MODEL_PINNED`
            #: fails on an empty pin -- so an authorized route always names a pin
            #: file, and the declaration gate is right to treat its absence as a
            #: block rather than as agreement.
            model_pin = tmp_path / "model-pin.json"
            model_pin.write_text(
                json.dumps(
                    {
                        "repository": "Qwen/Qwen3.6-27B",
                        "revision": "6a9e13bd6fc8f0983b9b99948120bc37f49c13e9",
                        "tokenizer_file_sha256": "sha256:" + "a" * 64,
                        "capability_evidence": "receipts/v8-model-attestation.json",
                    }
                ),
                encoding="utf-8",
            )
        protocol_freeze = tmp_path / "gpu-protocol-freeze.json"
        protocol_freeze.write_text(json.dumps({"fixture": "sealed"}), encoding="utf-8")
        return argparse.Namespace(
            manifest=manifest,
            model_pin=model_pin,
            model_pin_sha256=sha_file(model_pin),
            runtime_image_digest="repo/image@sha256:" + "0" * 64,
            sfi3_acceptance=sfi3,
            four_link_acceptance=four_link,
            materialized_inputs=materialized,
            protocol_freeze=protocol_freeze,
            protocol_freeze_sha256=sha_file(protocol_freeze),
            execute=execute,
        )

    return build


def make_args(tmp_path: Path, *, execute: bool = False) -> argparse.Namespace:
    """An invocation that names NO acceptance at all -- the unauthorized route."""
    return argparse.Namespace(
        manifest=tmp_path / "no-such-manifest.json",
        model_pin=None,
        model_pin_sha256=None,
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
        sfi3_acceptance=None,
        four_link_acceptance=None,
        materialized_inputs=None,
        protocol_freeze=None,
        protocol_freeze_sha256=None,
        execute=execute,
    )


def ready_body(
    args: argparse.Namespace, *, floor: int = 120, eligible_count: int = 120
) -> dict[str, Any]:
    """A `gpu_successor_preflight.run()`-shaped body reporting READY, whose
    digests are the REAL ones read from disk rather than invented.

    Both gates the launcher revalidates against are recorded here exactly as a
    genuine preflight would record them. A stub that made both sides up would
    prove only that the launcher agrees with itself; the red controls below
    move one side at a time.
    """
    return {
        "verdict": "READY_TO_AUTHORIZE",
        "blocking_gates": [],
        "declarations": gsp.declaration_digests(
            manifest=args.manifest,
            model_pin=args.model_pin,
            sfi3_acceptance=args.sfi3_acceptance,
            four_link_acceptance=args.four_link_acceptance,
        ),
        "gates": {
            "G_GSP_PROTOCOL_BUNDLE_FROZEN": {
                "passed": True,
                "detail": {
                    "expected_file_sha256": args.protocol_freeze_sha256,
                    "actual_file_sha256": sha_file(args.protocol_freeze),
                },
            },
            "G_GSP_MODEL_PIN_SOURCE_SEALED": {
                "passed": True,
                "detail": {
                    "expected_file_sha256": args.model_pin_sha256,
                    "actual_file_sha256": sha_file(args.model_pin),
                },
            },
            "G_GSP_COHORT_FEASIBILITY": {
                "passed": True,
                "detail": {"floor": floor, "eligible_count": eligible_count},
            },
            "G_GSP_SFI3_ACCEPTANCE_PASS": {
                "passed": True,
                "detail": {
                    "receipt": str(args.sfi3_acceptance),
                    "receipt_sha256": gsp.sha_file(Path(args.sfi3_acceptance))
                    if args.sfi3_acceptance
                    else None,
                },
            },
            "G_GSP_FOUR_LINK_ACCEPTANCE_PASS": {
                "passed": True,
                "detail": {
                    "receipt": str(args.four_link_acceptance),
                    "receipt_sha256": gsp.sha_file(Path(args.four_link_acceptance))
                    if args.four_link_acceptance
                    else None,
                },
            },
        },
    }


def drive(
    args: argparse.Namespace,
    monkeypatch,
    *,
    preflight_body: dict[str, Any] | None = None,
    provisioner: Any = None,
    cost: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], list[tuple[Any, ...]]]:
    """Run `launch()` with the preflight stubbed to a READY body.

    The preflight has its own suite (`tests/test_sfi_gpu_preflight.py`); what
    this file tests is what the LAUNCHER does with a READY preflight, so the
    preflight call is stubbed and everything downstream of it is real.
    """
    calls: list[tuple[Any, ...]] = []

    def fake_write_immutable(stem, body, **_kwargs):
        calls.append((stem, body))
        return {"receipt": f"fixture/{stem}.json", "run_id": "fixture", **body}

    monkeypatch.setattr(launcher, "write_immutable", fake_write_immutable)
    monkeypatch.setattr(
        gsp, "run", lambda **_kwargs: preflight_body or ready_body(args)
    )
    monkeypatch.setattr(gsp, "estimate_cost", lambda **_kwargs: cost or {"within_cap": True})
    code, receipt = launcher.launch(args, provisioner=provisioner)
    return code, receipt, calls


class FakeProvisioner:
    """Records calls; never touches anything real."""

    def __init__(self, *, fail_provision: bool = False, fail_teardown: bool = False) -> None:
        self.fail_provision = fail_provision
        self.fail_teardown = fail_teardown
        self.provisioned: list[dict[str, Any]] = []
        self.torn_down: list[dict[str, Any]] = []

    def provision(self, spec: dict[str, Any]) -> dict[str, Any]:
        if self.fail_provision:
            raise RuntimeError("fixture: provisioning refused")
        handle = {"id": "fake-pod-1", "spec": spec}
        self.provisioned.append(handle)
        return handle

    def execution_readiness(self, _spec: dict[str, Any]) -> dict[str, Any]:
        return {"passed": True, "backend": "fixture"}

    def execute_scientific_workload(
        self, handle: dict[str, Any], spec: dict[str, Any]
    ) -> dict[str, Any]:
        contract = spec["input_contract"]
        output = {
            "schema": gse.RAW_OUTPUT_SCHEMA,
            "status": "completed",
            "input_set_digest": contract["input_set_digest"],
            "items": [],
        }
        for fact_id in contract["fact_ids"]:
            arms = {}
            for arm in gse.ARMS:
                text = f"fixture response for {fact_id} {arm}"
                arms[arm] = {
                    "repetitions": [
                        {"response_text": text, "response_sha256": sha_text(text)}
                        for _ in range(gsp.DETERMINISM_REPEATS)
                    ]
                }
            output["items"].append({"fact_id": fact_id, "arms": arms})
        output_path = Path(contract["materialized_path"]).with_name("fixture-gpu-output.json")
        output_path.write_text(json.dumps(output), encoding="utf-8")
        return {
            "schema": gse.WORKER_RESULT_SCHEMA,
            "status": "completed",
            "input_set_digest": contract["input_set_digest"],
            "manifest_sha256": contract["manifest_sha256"],
            "runtime_image_digest": spec["runtime_image_digest"],
            "model_pin_sha256": spec["model_pin_sha256"],
            "output_path": str(output_path),
            "output_sha256": sha_file(output_path),
        }

    def teardown(self, handle: dict[str, Any]) -> None:
        if self.fail_teardown:
            raise RuntimeError("fixture: teardown refused")
        self.torn_down.append(handle)
        handle["actual_usage"] = {
            "gpu_seconds": 30.0,
            "cost_usd": 0.05,
            "source": "fixture",
        }
        handle["torn_down"] = True


class RaisingWatchdog:
    """Stands in for `launcher.Watchdog` to force an exception between a
    successful `provision()` and the try block's normal completion, so the
    `finally` teardown path can be exercised without waiting on a real
    6-hour timer."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def start(self) -> None:
        raise RuntimeError("fixture: watchdog arming failed")

    def cancel(self) -> None:
        pass


# ---------------------------------------------------------------------------
# THE GREEN DIRECTION -- first, so no red control below is vacuous
# ---------------------------------------------------------------------------


def test_green_a_fully_authorized_route_dry_runs_and_provisions_nothing(route, monkeypatch):
    args = route()
    provisioner = FakeProvisioner()
    code, receipt, calls = drive(args, monkeypatch, provisioner=provisioner)

    assert code == 0
    assert receipt["outcome"] == "DRY_RUN"
    assert provisioner.provisioned == []
    assert receipt["endpoint_gate"]["passed"] is True
    assert receipt["endpoint_gate"]["checks"]["sfi3"]["passed"] is True
    assert receipt["endpoint_gate"]["checks"]["four_link"]["passed"] is True
    assert receipt["declaration_gate"]["passed"] is True
    assert receipt["gpu_seconds"] == 0
    assert receipt["estimated_cost_usd"] == 0.0
    assert calls[0][0] == launcher.RECEIPT_STEM


def test_green_the_receipt_names_both_acceptances_it_was_authorized_by(route, monkeypatch):
    """A receipt that does not say what authorized it cannot be audited later."""
    args = route()
    _code, receipt, _calls = drive(args, monkeypatch)
    invocation = receipt["invocation"]
    assert invocation["sfi3_acceptance"] is not None
    assert invocation["four_link_acceptance"] is not None
    assert "held_out_stem" not in invocation


def test_green_a_cleared_execute_run_provisions_and_tears_down(route, monkeypatch):
    args = route(execute=True)
    provisioner = FakeProvisioner()
    code, receipt, _calls = drive(args, monkeypatch, provisioner=provisioner)

    assert code == 0
    assert receipt["outcome"] == "COMPLETED"
    assert len(provisioner.provisioned) == 1
    assert len(provisioner.torn_down) == 1


# ---------------------------------------------------------------------------
# RED CONTROLS 1-4 -- an authority that is absent, or not where it is claimed
# ---------------------------------------------------------------------------


def test_red_01_no_sfi3_acceptance_named_refuses(route, monkeypatch):
    args = route()
    body = ready_body(args)
    args.sfi3_acceptance = None
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert receipt["outcome"] == "REFUSED"
    assert receipt["endpoint_gate"]["checks"]["sfi3"]["passed"] is False
    assert "no sfi3 acceptance receipt was named" in receipt["endpoint_gate"]["reason"]


def test_red_02_no_four_link_acceptance_named_refuses(route, monkeypatch):
    args = route()
    body = ready_body(args)
    args.four_link_acceptance = None
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert receipt["endpoint_gate"]["checks"]["four_link"]["passed"] is False


def test_red_03_an_sfi3_acceptance_not_on_disk_refuses(route, monkeypatch, tmp_path):
    args = route()
    body = ready_body(args)
    args.sfi3_acceptance = tmp_path / "never-written.json"
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert receipt["endpoint_gate"]["checks"]["sfi3"]["receipt"] is None


def test_red_04_a_four_link_acceptance_not_on_disk_refuses(route, monkeypatch, tmp_path):
    args = route()
    body = ready_body(args)
    args.four_link_acceptance = tmp_path / "never-written.json"
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert receipt["endpoint_gate"]["checks"]["four_link"]["receipt"] is None


# ---------------------------------------------------------------------------
# RED CONTROLS 5-7 -- an authority swapped between the preflight and the launch
#
# This is the shape that ended the V2R3 chain, pointed at money: every gate can
# pass under one artefact and the spend happen under another, and every receipt
# still reads clean.
# ---------------------------------------------------------------------------


def test_red_05_an_sfi3_acceptance_swapped_after_the_preflight_refuses(
    route, monkeypatch, tmp_path
):
    args = route()
    body = ready_body(args)
    swapped = tmp_path / "other-sfi3-acceptance.json"
    swapped.write_text(
        json.dumps(json.loads(Path(args.sfi3_acceptance).read_text(encoding="utf-8"))
                   | {"measurement_run_id": "20260101T000000Z-somethingelse"}),
        encoding="utf-8",
    )
    args.sfi3_acceptance = swapped
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert "is not the one the preflight gated on" in receipt["endpoint_gate"]["reason"]


def test_red_06_a_four_link_acceptance_swapped_after_the_preflight_refuses(
    route, monkeypatch, tmp_path
):
    args = route()
    body = ready_body(args)
    swapped = tmp_path / "other-four-link-acceptance.json"
    swapped.write_text(
        Path(args.four_link_acceptance).read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    args.four_link_acceptance = swapped
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert "is not the one the preflight gated on" in receipt["endpoint_gate"]["reason"]


def test_red_07_a_green_four_link_receipt_over_another_manifest_refuses(
    route, monkeypatch, tmp_path
):
    """The 20,018-record receipt is good evidence about A manifest.

    It is not permission to spend on THIS one. `--manifest` decides what runs;
    the four-link acceptance must bind that same digest or the chain proves
    nothing about the cohort the GPU is about to see.
    """
    args = route()
    other = tmp_path / "a-different-manifest.json"
    other.write_text(json.dumps({"facts": []}), encoding="utf-8")
    args.manifest = other
    body = ready_body(args)
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert receipt["endpoint_gate"]["checks"]["four_link"]["passed"] is False


# ---------------------------------------------------------------------------
# RED CONTROLS 8-11 -- the acceptance itself does not hold
#
# Every one of these is decided by `sfi3_acceptance`, not here. What these
# controls prove is that the launcher actually RE-RUNS it rather than reading
# the preflight's word for it.
# ---------------------------------------------------------------------------


def test_red_08_an_sfi3_acceptance_over_a_failing_measurement_refuses(
    tmp_path, monkeypatch, route
):
    args = route()
    failing = fixtures.land_sfi3_acceptance(tmp_path, monkeypatch, verdict="FAIL")
    args.sfi3_acceptance = failing
    body = ready_body(args)
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert receipt["endpoint_gate"]["checks"]["sfi3"]["passed"] is False


def test_red_09_a_primary_endpoint_not_met_refuses(tmp_path, monkeypatch, route):
    args = route()
    endpoints = fixtures.sfi3_endpoints()
    endpoints[acc.PRIMARY_ENDPOINTS[0]] = {
        "verdict": acc.FAILED,
        "violations": 3,
        "pairs_exercising": 12,
        "why": "fixture",
    }
    args.sfi3_acceptance = fixtures.land_sfi3_acceptance(
        tmp_path, monkeypatch, endpoints=endpoints
    )
    body = ready_body(args)
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert receipt["endpoint_gate"]["checks"]["sfi3"]["passed"] is False


def test_red_10_crediting_the_safety_veto_as_met_refuses(tmp_path, monkeypatch, route):
    """E8's clean state is VETO_CLEAR_NO_POSITIVE_CREDIT and never MET.

    Reading its clean zero as a met endpoint would manufacture positive evidence
    from an instrument whose seam is structurally closed and which could not
    have fired.
    """
    args = route()
    endpoints = fixtures.sfi3_endpoints()
    endpoints[acc.VETO_ENDPOINT] = {
        "verdict": acc.MET,
        "violations": 0,
        "pairs_exercising": 0,
        "natural_gate_power": False,
        "stages_checked": list(acc.STAGES_REQUIRED),
        "stages_missing": [],
        "cases": [],
    }
    args.sfi3_acceptance = fixtures.land_sfi3_acceptance(
        tmp_path, monkeypatch, endpoints=endpoints
    )
    body = ready_body(args)
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 3
    assert receipt["endpoint_gate"]["checks"]["sfi3"]["passed"] is False


def test_red_11_the_launcher_carries_no_endpoint_arithmetic_of_its_own():
    """Two implementations of an acceptance rule are two rules.

    A copy here could pass while `sfi3_acceptance` refused, and the receipt
    would look identical either way. Checked structurally as well as by name:
    the module defines no endpoint tuple and no verdict constants.
    """
    #: Structurally, never by scanning the raw text. The comment block in
    #: `launch_gpu_successor.py` that EXPLAINS why no endpoint arithmetic lives
    #: there necessarily names `VETO_CLEAR_NO_POSITIVE_CREDIT`, and a substring
    #: scan cannot tell prose about a rule from an implementation of it -- the
    #: same blindness that made the first version of
    #: `test_no_bypass_flag_or_env_var_exists` wrong.
    source = Path(launcher.__file__).read_text(encoding="utf-8")
    assert not hasattr(launcher, "REQUIRED_ENDPOINTS")
    assert not hasattr(launcher, "held_out_endpoints_gate")
    assert not hasattr(launcher, "MET")

    tree = ast.parse(source)
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert not {name for name in assigned if "ENDPOINT" in name.upper()}

    #: And no string literal anywhere in the module's CODE is an SFI3 verdict
    #: or endpoint name. A comment is not a node in a Python AST, so this sees
    #: only what the module would actually compare against.
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    docstrings = {
        ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef)
    }
    for literal in literals - docstrings:
        assert acc.VETO_CLEAR not in literal
        for endpoint in (*acc.PRIMARY_ENDPOINTS, acc.VETO_ENDPOINT):
            assert endpoint not in literal


# ---------------------------------------------------------------------------
# RED CONTROLS 12-16 -- the six bound inputs moved between preflight and launch
# ---------------------------------------------------------------------------


def _moved(args: argparse.Namespace, name: str) -> dict[str, Any]:
    """A READY body whose recorded digest for `name` is not what is on disk."""
    body = ready_body(args)
    body["declarations"][name] = {"path": "x", "sha256": "sha256:" + "0" * 64}
    return body


def test_red_12_a_moved_study_declaration_refuses(route, monkeypatch):
    args = route()
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=_moved(args, "study"))
    assert code == 5
    assert "['study']" in receipt["reason"]
    assert receipt["declaration_gate"]["passed"] is False


def test_red_13_a_moved_runtime_declaration_refuses(route, monkeypatch):
    args = route()
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=_moved(args, "runtime"))
    assert code == 5
    assert "['runtime']" in receipt["reason"]


def test_red_14_a_moved_manifest_refuses(route, monkeypatch):
    """The cohort itself is a bound input, not merely an argument."""
    args = route()
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=_moved(args, "manifest"))
    assert code == 5
    assert "['manifest']" in receipt["reason"]


def test_red_15_a_moved_model_pin_refuses(route, monkeypatch):
    """What runs the study is a bound input too, not only what it runs over."""
    args = route()
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=_moved(args, "model_pin"))
    assert code == 5
    assert "['model_pin']" in receipt["reason"]


def test_red_16_a_preflight_recording_five_of_six_declarations_refuses(route, monkeypatch):
    """Set equality on the declaration domain, both directions.

    A loop over what the preflight happened to record would pass on the five it
    has, and the sixth would be bound by nothing at all. That is INC-V2-067's
    acceptance-domain defect pointed at money instead of a corpus.
    """
    args = route()
    body = ready_body(args)
    body["declarations"].pop("four_link_acceptance")
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 5
    assert "declaration domain is not this launcher's" in receipt["reason"]
    assert "missing=['four_link_acceptance']" in receipt["reason"]


def test_a_preflight_that_recorded_no_declarations_at_all_refuses(route, monkeypatch):
    """An old receipt shape is not treated as agreement.

    Absent evidence and matching evidence are different states, and only one of
    them is a reason to spend.
    """
    args = route()
    body = ready_body(args)
    body.pop("declarations")
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 5
    assert "records no study or runtime declaration digest" in receipt["reason"]


def test_an_absent_declaration_file_refuses(route, monkeypatch, tmp_path):
    """A declaration that is gone cannot be the one the preflight gated on."""
    monkeypatch.setattr(gsp, "STUDY_PROTOCOL", tmp_path / "not-here.yaml")
    args = route()
    body = ready_body(args)
    body["declarations"]["study"] = {"path": "x", "sha256": "sha256:" + "1" * 64}
    code, receipt, _calls = drive(args, monkeypatch, preflight_body=body)
    assert code == 5
    assert "missing on disk" in receipt["reason"]


def test_the_declaration_gate_rereads_disk_rather_than_trusting_the_body(route, monkeypatch):
    """Both sides of the comparison are not the same object.

    A gate that compared the preflight body against itself would agree on every
    input, including a forged one.
    """
    args = route()
    body = ready_body(args)
    forged = {"path": "x", "sha256": "sha256:" + "a" * 64}
    body["declarations"] = dict.fromkeys(gsp.DECLARATION_KEYS, forged)
    gate = launcher._declaration_gate(args, body)
    assert gate["passed"] is False
    assert gate["actual"] != gate["recorded"]


# ---------------------------------------------------------------------------
# the preflight's own verdict is never overridden here
# ---------------------------------------------------------------------------


def test_blocked_preflight_refuses_to_launch(tmp_path, monkeypatch):
    """No acceptance named anywhere -> the REAL preflight is BLOCKED -> refuse."""
    args = make_args(tmp_path)
    monkeypatch.setattr(launcher, "write_immutable", lambda *a, **k: {"receipt": "fixture"})

    code, receipt = launcher.launch(args)

    assert code != 0
    assert receipt["outcome"] == "REFUSED"
    assert receipt["preflight"]["verdict"] == "BLOCKED"
    assert "G_GSP_SFI3_ACCEPTANCE_PASS" in receipt["preflight"]["blocking_gates"]
    assert "G_GSP_FOUR_LINK_ACCEPTANCE_PASS" in receipt["preflight"]["blocking_gates"]
    assert receipt["gpu_seconds"] == 0
    assert receipt["estimated_cost_usd"] == 0.0


def test_launch_always_calls_preflight_before_anything_else(tmp_path, monkeypatch):
    """`--execute` does not skip the preflight call. Even with --execute set,
    a blocked preflight still refuses and never reaches the provisioner."""
    monkeypatch.setattr(launcher, "write_immutable", lambda *a, **k: {"receipt": "fixture"})
    provisioner = FakeProvisioner()
    args = make_args(tmp_path, execute=True)

    code, receipt = launcher.launch(args, provisioner=provisioner)

    assert code != 0
    assert receipt["outcome"] == "REFUSED"
    assert provisioner.provisioned == []


# ---------------------------------------------------------------------------
# the cost caps -- a prediction that clears is still bounded by the watchdog
# ---------------------------------------------------------------------------


def test_projected_cost_over_gpu_hours_cap_refuses(route, monkeypatch):
    args = route()
    code, receipt, _calls = drive(
        args,
        monkeypatch,
        cost={
            "within_cap": False,
            "within_hours_cap": False,
            "within_usd_cap": True,
            "estimated_gpu_hours": 7.68,
            "estimated_cost_usd": 19.2,
        },
    )
    assert code == 4
    assert receipt["outcome"] == "REFUSED"
    assert receipt["projected_cost"]["within_cap"] is False
    assert receipt["gpu_seconds"] == 0
    assert receipt["estimated_cost_usd"] == 0.0


def test_projected_cost_over_usd_cap_refuses(route, monkeypatch):
    args = route()
    code, receipt, _calls = drive(
        args,
        monkeypatch,
        cost={
            "within_cap": False,
            "within_hours_cap": True,
            "within_usd_cap": False,
            "estimated_gpu_hours": 1.0,
            "estimated_cost_usd": 999.0,
        },
    )
    assert code == 4
    assert receipt["projected_cost"]["within_cap"] is False


def test_build_parser_execute_defaults_to_false():
    parser = launcher.build_parser()
    args = parser.parse_args([])
    assert args.execute is False


def test_build_parser_names_no_default_for_either_acceptance():
    """No 'latest', no implicit default, no fallback to SFI2.

    A default would be a search result by another name: the launcher would spend
    against whatever the default happened to point at.
    """
    parser = launcher.build_parser()
    args = parser.parse_args([])
    assert args.sfi3_acceptance is None
    assert args.four_link_acceptance is None


# ---------------------------------------------------------------------------
# teardown runs even when the body raises
# ---------------------------------------------------------------------------


def test_teardown_runs_even_when_watchdog_arming_raises(route, monkeypatch):
    monkeypatch.setattr(launcher, "Watchdog", RaisingWatchdog)
    provisioner = FakeProvisioner()
    code, receipt, _calls = drive(route(execute=True), monkeypatch, provisioner=provisioner)

    assert len(provisioner.provisioned) == 1
    assert len(provisioner.torn_down) == 1
    assert provisioner.torn_down[0] is provisioner.provisioned[0]
    assert code != 0
    assert receipt["outcome"] == "EXECUTE_FAILED"
    assert "RuntimeError" in receipt["reason"]
    assert "backend detail suppressed" in receipt["reason"]


def test_teardown_runs_even_when_provisioning_itself_raises(route, monkeypatch):
    provisioner = FakeProvisioner(fail_provision=True)
    code, receipt, _calls = drive(route(execute=True), monkeypatch, provisioner=provisioner)

    assert provisioner.provisioned == []
    assert provisioner.torn_down == []  # nothing was provisioned, so nothing to tear down
    assert code != 0
    assert receipt["outcome"] == "EXECUTE_FAILED"
    assert "RuntimeError" in receipt["reason"]
    assert "backend detail suppressed" in receipt["reason"]


# ---------------------------------------------------------------------------
# a receipt is written on every path, including refusal
# ---------------------------------------------------------------------------


def test_receipt_written_on_refusal_path(tmp_path, monkeypatch):
    calls: list[tuple[Any, ...]] = []

    def fake_write_immutable(stem, body, **_kwargs):
        calls.append((stem, body))
        return {"receipt": f"fixture/{stem}.json", "run_id": "fixture"}

    monkeypatch.setattr(launcher, "write_immutable", fake_write_immutable)
    args = make_args(tmp_path)

    code, receipt = launcher.launch(args)

    assert code != 0
    assert len(calls) == 1
    assert calls[0][0] == launcher.RECEIPT_STEM
    assert calls[0][1]["outcome"] == "REFUSED"
    assert receipt["receipt"] == "fixture/gpu-successor-launch.json"


def test_receipt_written_on_dry_run_path(route, monkeypatch):
    _code, _receipt, calls = drive(route(), monkeypatch)
    assert len(calls) == 1
    assert calls[0][1]["outcome"] == "DRY_RUN"
    assert calls[0][1]["gpu_seconds"] == 0
    assert calls[0][1]["estimated_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# no flag, argument or env var bypasses the preflight
#
# The original version of this test scanned the module's raw source TEXT for
# forbidden substrings (`"os.environ" not in source`, etc). That is exactly
# as blind as it sounds: it fails just as hard on a comment or a docstring
# *explaining* why no such access exists as it would on a real bypass, and it
# would pass right through `if some_flag: skip_preflight()` -- a real bypass
# shaped nothing like "os.environ" or "--force". Both failure modes were
# caught in review (2026-08-23): a docstring in `launch_gpu_successor.py`
# describing why `runpod_provisioner.py` reads `RUNPOD_API_KEY` instead of
# this module tripped the substring scan even though no code changed.
#
# Everything below parses the module with `ast` and inspects the syntax
# tree instead. Comments are not nodes in a Python AST at all, and a
# docstring is a `Constant` string sitting in an `Expr` statement -- neither
# can register as an `Attribute` access or an `Import` statement, so prose
# describing a design decision is now structurally invisible to the checks
# that matter.
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = ("force", "bypass", "skip", "override", "ignore", "no_preflight", "unsafe")
_OS_ENV_ATTRS = frozenset({"environ", "getenv", "putenv"})


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no function named {name!r} found")


def _call_name(node: ast.AST) -> str | None:
    """The bare or attribute name a Call node invokes -- `gsp.run(...)` ->
    `"run"`, `_acceptance_gate(...)` -> `"_acceptance_gate"`."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _top_level_index_of_assign_call(body: list[ast.stmt], call_name: str) -> int | None:
    """The index of the first TOP-LEVEL statement in `body` that assigns the
    result of a call named `call_name`. Deliberately does not recurse into
    nested `If`/`Try`/`For` blocks: a gate call moved inside a conditional
    stops being a top-level statement and this returns `None` for it, which
    is exactly the signal a reordering-into-a-guard bypass should trip."""
    for index, stmt in enumerate(body):
        if (
            isinstance(stmt, ast.Assign)
            and isinstance(stmt.value, ast.Call)
            and _call_name(stmt.value) == call_name
        ):
            return index
    return None


def _assert_no_os_env_access(tree: ast.Module, *, label: str) -> None:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations += [f"import {alias.name}" for alias in node.names if alias.name == "os"]
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            violations.append("from os import ...")
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr in _OS_ENV_ATTRS
        ):
            violations.append(f"os.{node.attr}")
    assert not violations, f"{label} accesses the os environment APIs directly: {violations}"


def test_no_bypass_flag_or_env_var_exists():
    """A later edit that adds a `--force`/`--skip-preflight`/env-var escape
    hatch must fail this test. `--execute` itself is not a bypass -- it still
    goes through every refusal gate in `launch()`; it only chooses whether a
    fully-cleared run provisions or dry-runs."""
    parser = launcher.build_parser()
    for action in parser._actions:
        haystacks = [*(action.option_strings or []), action.dest or ""]
        for haystack in haystacks:
            lowered = haystack.lower().replace("-", "_")
            for forbidden in _FORBIDDEN_SUBSTRINGS:
                assert forbidden not in lowered, (
                    f"argparse action {action.option_strings} looks like a preflight bypass"
                )

    option_strings = {opt for action in parser._actions for opt in (action.option_strings or [])}
    assert option_strings == {
        "-h",
        "--help",
        "--manifest",
        "--model-pin",
        "--model-pin-sha256",
        "--runtime-image-digest",
        "--sfi3-acceptance",
        "--four-link-acceptance",
        "--materialized-inputs",
        "--protocol-freeze",
            "--protocol-freeze-sha256",
            "--worker-bundle",
            "--worker-bundle-sha256",
            "--execution-ledger",
            "--retrieved-output",
            "--r2-endpoint-url",
            "--r2-bucket",
            "--r2-region",
            "--execute",
    }

    # No environment-variable escape hatch, anywhere in the module -- checked
    # structurally (AST), not by scanning raw text (see the block comment
    # above for why the text-scanning version of this check was wrong).
    _assert_no_os_env_access(_parse(Path(launcher.__file__)), label="launch_gpu_successor.py")

    # Exactly one boolean flag exists (`--execute`), and it does not itself
    # skip a gate -- it is read once, in `launch()`, only to decide whether a
    # run that already cleared every refusal gate provisions or dry-runs.
    store_true_actions = [
        action
        for action in parser._actions
        if getattr(action, "const", None) is True or action.__class__.__name__ == "_StoreTrueAction"
    ]
    assert [action.dest for action in store_true_actions] == ["execute"]


def test_preflight_gates_are_unconditional_top_level_statements_in_launch():
    """The check the text-scanning version of this suite lacked: that the
    preflight call, the acceptance revalidation, the declaration gate and the
    cost-cap gate cannot be moved behind a condition without failing a test.
    An enumeration of CLI flags can never catch
    `if some_condition: skip_preflight()` -- that bypass shape does not touch
    argparse at all. This walks `launch()`'s own syntax tree instead and
    requires:

    1. `gsp.run(...)`, `_acceptance_gate(...)`, `_declaration_gate(...)` and
       `gsp.estimate_cost(...)` each appear as a top-level (unguarded)
       assignment in `launch()`, in that order;
    2. every one of them is followed, before the next gate, by a top-level
       `if ...: return ...` that can actually refuse the run;
    3. the statement that finally calls `.provision(` on the provisioner
       comes after all four -- so no reordering can let a run reach
       provisioning without every gate's result already having been computed
       and checked, in this file, in this order.
    """
    tree = _parse(Path(launcher.__file__))
    launch_fn = _find_function(tree, "launch")
    body = launch_fn.body

    preflight_idx = _top_level_index_of_assign_call(body, "run")
    acceptance_idx = _top_level_index_of_assign_call(body, "_acceptance_gate")
    declaration_idx = _top_level_index_of_assign_call(body, "_declaration_gate")
    cost_idx = _top_level_index_of_assign_call(body, "estimate_cost")

    provision_call_idx = None
    for index, stmt in enumerate(body):
        if any(_call_name(node) == "provision" for node in ast.walk(stmt)):
            provision_call_idx = index
            break

    assert preflight_idx is not None, (
        "gsp.run(...) is no longer an unconditional top-level statement in "
        "launch() -- if it now lives inside an `if`, that `if` could skip it"
    )
    assert acceptance_idx is not None, (
        "_acceptance_gate(...) is no longer an unconditional top-level statement "
        "in launch()"
    )
    assert declaration_idx is not None, (
        "_declaration_gate(...) is no longer an unconditional top-level statement "
        "in launch()"
    )
    assert cost_idx is not None, (
        "gsp.estimate_cost(...) is no longer an unconditional top-level "
        "statement in launch()"
    )
    assert provision_call_idx is not None, "launch() no longer calls .provision( at all"
    assert preflight_idx < acceptance_idx < declaration_idx < cost_idx < provision_call_idx, (
        "the preflight, acceptance, declaration and cost gates must run, in this "
        "order, before anything in launch() calls .provision("
    )

    # Between each gate's computation and the next lives an early-return
    # guard -- at least four of them (blocked preflight, failed acceptance,
    # moved declaration, over-cap cost) sit strictly before provisioning.
    guarding_returns = [
        index
        for index, stmt in enumerate(body)
        if isinstance(stmt, ast.If) and any(isinstance(n, ast.Return) for n in ast.walk(stmt))
    ]
    assert sum(1 for index in guarding_returns if index < provision_call_idx) >= 4, (
        "fewer than 4 early-return guards sit between the top of launch() and "
        "the provisioning call -- a refusal gate may have lost its ability to "
        "actually refuse"
    )


def test_runpod_provisioner_exposes_no_bypass_shaped_parameter():
    """`runpod_provisioner.py` legitimately reads the Runpod API key from the
    environment (via `RunPodCredentialSet.from_environment`) -- that is
    expected and is not what this checks. What this checks is that nothing
    in the module gives a caller a way to reach a real Runpod call without
    going through `launch()`'s gates: no constructor or method parameter
    anywhere in the module is shaped like a bypass flag, and `provision()`
    still contains its own independent image-pin and cost-cap checks."""
    tree = _parse(Path(rp.__file__))

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for arg in [*node.args.args, *node.args.kwonlyargs]:
                lowered = arg.arg.lower().replace("-", "_")
                for forbidden in _FORBIDDEN_SUBSTRINGS:
                    if forbidden in lowered:
                        violations.append(f"{node.name}({arg.arg})")
    assert not violations, f"runpod_provisioner.py exposes a bypass-shaped parameter: {violations}"

    provision_fn = _find_function(tree, "provision")
    dumped = ast.dump(provision_fn)
    assert "within_cap" in dumped, (
        "provision() no longer re-checks spec['projected_cost']['within_cap'] "
        "independently of launch()'s own cap gate"
    )
    assert "_require_pinned_image" in dumped, (
        "provision() no longer refuses a floating image tag before any API call"
    )


def test_no_test_in_this_file_ever_provisions_for_real():
    """The one property this whole file depends on being true of itself.

    Every `--execute` path above is driven with a `FakeProvisioner`, and the
    only place `RunpodPodProvisioner` is constructed is behind
    `httpx.MockTransport`. No test names a real transport.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == "RunpodPodProvisioner":
            keywords = {kw.arg for kw in node.keywords}
            assert "transport" in keywords, (
                "a RunpodPodProvisioner is constructed without a mock transport"
            )


# ---------------------------------------------------------------------------
# RunpodPodProvisioner -- the real backend, exercised only against
# httpx.MockTransport. No test below ever reaches the network: every
# request the provisioner would send is intercepted by the handler passed to
# MockTransport and answered locally, so nothing here can provision, bill,
# or even attempt a live connection. RunPodCredentialSet is constructed
# directly from a fixture string rather than read from the environment, so
# these tests do not depend on RUNPOD_API_KEY being set in CI.
# ---------------------------------------------------------------------------

FAKE_CREDENTIALS = RunPodCredentialSet(("fixture-not-a-real-key",))
PINNED_DIGEST = "repo/image@sha256:" + "a" * 64


def _spec(*, digest: str = PINNED_DIGEST, within_cap: bool = True) -> dict[str, Any]:
    return {"runtime_image_digest": digest, "projected_cost": {"within_cap": within_cap}}


def _provisioner(handler) -> rp.RunpodPodProvisioner:
    return rp.RunpodPodProvisioner(
        credentials=FAKE_CREDENTIALS, transport=httpx.MockTransport(handler)
    )


def _create_response(pod_id: str = "pod-fixture-1") -> httpx.Response:
    return httpx.Response(
        200, json={"data": {"podFindAndDeployOnDemand": {"id": pod_id, "costPerHr": 4.59}}}
    )


def test_floating_image_tag_is_refused_before_any_api_call():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError(f"no API call should happen for a floating tag: {request.url}")

    provisioner = _provisioner(handler)
    with pytest.raises(rp.ProvisioningError, match="not pinned"):
        provisioner.provision(_spec(digest="repo/image:latest"))
    provisioner.close()


def test_provisioner_rechecks_cost_cap_before_any_api_call():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError(f"no API call should happen when within_cap is False: {request.url}")

    provisioner = _provisioner(handler)
    with pytest.raises(rp.ProvisioningError, match="within_cap"):
        provisioner.provision(_spec(within_cap=False))
    provisioner.close()


def test_teardown_on_a_never_provisioned_handle_does_not_raise():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError(f"teardown of nothing should never call the API: {request.url}")

    provisioner = _provisioner(handler)
    provisioner.teardown(None)
    provisioner.teardown({})
    provisioner.teardown({"pod_id": None})
    provisioner.close()


def test_teardown_is_idempotent_second_call_is_a_noop():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if "graphql" in str(request.url):
            return _create_response()
        if request.method == "GET":
            return httpx.Response(200, json={"uptimeSeconds": 42, "costPerHr": 4.59})
        if request.method == "DELETE":
            return httpx.Response(202)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    provisioner = _provisioner(handler)
    handle = provisioner.provision(_spec())
    provisioner.teardown(handle)
    calls_after_first = list(calls)
    provisioner.teardown(handle)  # second call

    assert calls == calls_after_first, "a second teardown() must not issue any new API call"
    assert handle["torn_down"] is True
    provisioner.close()


def test_teardown_treats_an_already_terminated_pod_as_success():
    """DELETE on a pod Runpod has already removed (its own terminateAfter
    fired, or a human deleted it) returns 404. Teardown must treat that as
    the goal state, not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "graphql" in str(request.url):
            return _create_response()
        if request.method == "GET":
            return httpx.Response(200, json={"uptimeSeconds": 10, "costPerHr": 4.59})
        if request.method == "DELETE":
            return httpx.Response(404)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    provisioner = _provisioner(handler)
    handle = provisioner.provision(_spec())
    provisioner.teardown(handle)  # must not raise
    assert handle["torn_down"] is True
    provisioner.close()


def test_teardown_does_not_mask_the_original_exception():
    """When the caller's own body raises between provision() and teardown(),
    the try/finally in launch_gpu_successor.launch() calls teardown() on its
    way out. If teardown() itself also raises, launch()'s own finally block
    appends a note rather than losing the first error (see the
    test_teardown_runs_even_when_watchdog_arming_raises test above, which
    exercises that composition with a fake provisioner). This test isolates
    the provisioner's own half of that contract: teardown() must complete
    (or raise its OWN clearly-labeled error) without ever silently replacing
    or discarding an exception the caller is already handling."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "graphql" in str(request.url):
            return _create_response()
        if request.method == "GET":
            return httpx.Response(200, json={"uptimeSeconds": 5, "costPerHr": 4.59})
        if request.method == "DELETE":
            return httpx.Response(500)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    provisioner = _provisioner(handler)
    handle = provisioner.provision(_spec())
    try:
        raise RuntimeError("the caller's own body failed first")
    except RuntimeError as original:
        try:
            provisioner.teardown(handle)
        except rp.ProvisioningError as teardown_error:
            # teardown is allowed to surface its own failure (a 500 is a real
            # provider error, not an already-gone pod) -- what it must not do
            # is silently swallow or overwrite the original exception still
            # live in this except block.
            assert original.args == ("the caller's own body failed first",)
            assert "500" in str(teardown_error)
        else:
            pytest.fail("DELETE returning 500 should have raised ProvisioningError")
    provisioner.close()


def test_runpod_side_auto_terminate_is_set_on_every_provision_request():
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "graphql" in str(request.url):
            captured.append(json.loads(request.content))
            return _create_response()
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    provisioner = _provisioner(handler)
    handle = provisioner.provision(_spec())

    assert len(captured) == 1
    graphql_input = captured[0]["variables"]["input"]
    assert graphql_input.get("terminateAfter"), (
        "every provision request must carry a platform-side terminateAfter -- "
        "the watchdog gap this study's own launcher docstring names is exactly "
        "the process being killed after --execute succeeds, and only a "
        "Runpod-side stop survives that"
    )
    assert handle["runpod_terminate_after"] == graphql_input["terminateAfter"]
    provisioner.close()


def test_real_usage_is_read_after_teardown_and_recorded_as_not_retrieved_when_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        if "graphql" in str(request.url):
            return _create_response()
        if request.method == "GET":
            return httpx.Response(500)  # usage genuinely unavailable
        if request.method == "DELETE":
            return httpx.Response(200)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    provisioner = _provisioner(handler)
    handle = provisioner.provision(_spec())
    provisioner.teardown(handle)

    usage = handle["actual_usage"]
    assert usage["gpu_seconds"] == rp.NOT_RETRIEVED
    assert usage["cost_usd"] == rp.NOT_RETRIEVED
    provisioner.close()


def test_real_usage_is_read_from_the_pod_when_available():
    def handler(request: httpx.Request) -> httpx.Response:
        if "graphql" in str(request.url):
            return _create_response()
        if request.method == "GET":
            return httpx.Response(200, json={"uptimeSeconds": 600, "costPerHr": 2.0})
        if request.method == "DELETE":
            return httpx.Response(200)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    provisioner = _provisioner(handler)
    handle = provisioner.provision(_spec())
    provisioner.teardown(handle)

    usage = handle["actual_usage"]
    assert usage["gpu_seconds"] == 600.0
    assert usage["cost_usd"] == pytest.approx(600.0 / 3600.0 * 2.0)
    provisioner.close()


def test_real_provisioner_refuses_before_pod_creation_without_scientific_transport(
    route, monkeypatch
):
    """A real pod lifecycle backend is not yet a scientific executor."""
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "graphql" in str(request.url):
            return _create_response()
        if request.method == "GET":
            return httpx.Response(200, json={"uptimeSeconds": 30, "costPerHr": 4.59})
        if request.method == "DELETE":
            return httpx.Response(200)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    provisioner = _provisioner(handler)
    code, receipt, _calls = drive(route(execute=True), monkeypatch, provisioner=provisioner)

    assert code == 6
    assert receipt["outcome"] == "REFUSED"
    assert receipt["execution_readiness"]["passed"] is False
    assert calls == []
    provisioner.close()
