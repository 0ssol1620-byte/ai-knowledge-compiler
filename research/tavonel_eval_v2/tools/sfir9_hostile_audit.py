#!/usr/bin/env python3
"""Thirteen attacks the study must refuse, each mounted for real.

**Every attack is paired with its own control.** An attack that could not be
mounted -- a fixture that errored, a path that did not exist, an import that
failed -- produces the same "no result came back" as an attack that was properly
refused, and the difference is the whole audit. So each entry runs twice: once
clean, which must succeed, and once attacked, which must refuse with a named
code. An attack whose control fails is reported as `CONTROL_FAILED` and the audit
does not pass, because nothing was learned from it.

**The refusal has to come from the study's own machinery.** Nothing here
implements a check. Each attack reaches for a real component -- the closure, the
isolation gate, the roster, the chain, the transport binding -- and records which
refusal fired. An audit that carried its own copy of the rules would be testing
its copy.

**The codes are asserted, not just the fact of a refusal.** A refusal for the
wrong reason is a refusal that will stop firing when the wrong reason goes away.

Run it to produce `receipts/sfir9-hostile-audit.json`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_checkpoint_chain as chain_module  # noqa: E402
import sfir9_cohort_roster as roster_module  # noqa: E402
import sfir9_execution_closure as closure_module  # noqa: E402
import sfir9_identity_logic as identity  # noqa: E402
import sfir9_isolation_gate as gate  # noqa: E402
import sfir9_protocol as protocol_module  # noqa: E402
import sfir9_selection as selection_module  # noqa: E402
import sfir9_transport as transport  # noqa: E402

REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir9-hostile-audit.json"
SCHEMA = "tavonel.sfir9.hostile_audit.v1"

REFUSED = "REFUSED"
NOT_REFUSED = "NOT_REFUSED"
WRONG_CODE = "REFUSED_FOR_THE_WRONG_REASON"
CONTROL_FAILED = "CONTROL_FAILED"


@dataclass
class Attack:
    """One hostile move, its control, and the refusal it must provoke."""

    name: str
    what_it_tries: str
    expected_code: str
    control: Callable[[Path], Any]
    attack: Callable[[Path], Any]
    # Required, with no default. A default of `Exception` would have meant an
    # attack could silently accept any failure as its refusal.
    refusals: tuple[type[BaseException], ...]


# ----------------------------------------------------------------- fixtures


def _copy_components(sandbox: Path) -> tuple[dict[str, bytes], dict[str, str]]:
    """A checkout holding the ten components, with a committed-bytes reader."""
    tools = sandbox / closure_module.TOOLS
    tools.mkdir(parents=True, exist_ok=True)
    committed: dict[str, bytes] = {}
    origins: dict[str, str] = {}
    for component in closure_module.COMPONENTS:
        raw = (REPO / component.relative_path).read_bytes()
        committed[component.relative_path] = raw
        (sandbox / component.relative_path).write_bytes(raw)
        origins[component.module] = str(tools / f"{component.module}.py")
    return committed, origins


def _copy_upstream(sandbox: Path) -> dict[str, bytes]:
    tools = sandbox / "research/tavonel_eval_v2/tools"
    tools.mkdir(parents=True, exist_ok=True)
    committed: dict[str, bytes] = {}
    for pinned in transport.UPSTREAM_MODULES:
        raw = (REPO / pinned.relative_path).read_bytes()
        committed[pinned.relative_path] = raw
        (sandbox / pinned.relative_path).write_bytes(raw)
    return committed


def _closure(sandbox, committed, origins, **kwargs):
    return closure_module.closure(
        repository_root=sandbox,
        import_origins=origins,
        read_committed_bytes=lambda _root, path: committed[path],
        **kwargs,
    )


def _catalogue(count=4000):
    return [
        {
            "host_uuid": str(100000 + i),
            "name_with_owner": f"org{i}/repo{i}",
            "record_id": f"r{i:06d}",
            "source_rank": i % 30,
        }
        for i in range(count)
    ]


def _rule(**overrides):
    term = selection_module.EnvelopeTerm
    body = dict(
        salt="sfir9-audit-salt",
        partition_count=8,
        partition_index=0,
        envelope=selection_module.ExecutionEnvelope(
            permitted_rate_windows=term(
                name="permitted_rate_windows", value=6,
                source=selection_module.EXTERNAL, rationale="declared",
            ),
            usable_charge_per_window=term(
                name="usable_charge_per_window", value=4500,
                source=selection_module.EXTERNAL, rationale="declared",
            ),
            per_root_charge_allowance=term(
                name="per_root_charge_allowance", value=540,
                source=selection_module.EXTERNAL, rationale="declared",
            ),
        ),
        spent_host_uuids=frozenset(),
    )
    body.update(overrides)
    return selection_module.FrozenSelection(**body)


def _roster(*, protocol=None, spent=()):
    selection = selection_module.select(_catalogue(), _rule())
    proof = identity.exclusion_proof(identity.spent_set(spent))
    return roster_module.CohortRoster(
        protocol=protocol or protocol_module.Protocol().freeze(),
        selection=selection,
        exclusion_proof=proof,
    )


def _handoff(**overrides):
    body = dict(
        protocol_digest=protocol_module.Protocol().digest(),
        roster_digest="sha256:roster-A",
        selection_digest="sha256:selection-A",
        current_root_host_uuid="12345",
        canonical_address="a/b",
        frontier_digest="sha256:f",
        visited_digest="sha256:v",
        candidate_accumulator_digest="sha256:c",
        logical_request_count=1,
        network_hop_count=1,
        provider_charged_count=1,
        provider_remaining=100,
        provider_reset_epoch=1,
        previous_segment_digest=chain_module.GENESIS,
        disposition=chain_module.RATE_WINDOW,
    )
    body.update(overrides)
    return transport.TransportHandoff(**body)


def _chain(**overrides):
    body = dict(
        study_id=protocol_module.PROTOCOL_ID,
        protocol_digest=protocol_module.Protocol().digest(),
        roster_digest="sha256:roster-A",
        selection_digest="sha256:selection-A",
    )
    body.update(overrides)
    return chain_module.SegmentChain(**body)


def _drift_record():
    return gate.read_drift(NS / "receipts/frozen-instrument-integrity.json")


def _gate_components(sandbox: Path) -> dict[str, str]:
    tools = sandbox / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in gate.REQUIRED_COMPONENTS:
        relative = f"tools/sfir9_{name}.py"
        (sandbox / relative).write_text(
            f'"""SFIR9 {name}."""\nVALUE = "{name}"\n', encoding="utf-8"
        )
        paths[name] = relative
    return paths


def _declaration(paths, **overrides):
    body = dict(
        components=dict(paths),
        historical_inputs=[],
        scientific_prerequisites=[],
        source_digests={},
        claims_continuity_with_historical_pin=False,
    )
    body.update(overrides)
    return gate.Sfir9Declaration(**body)


# ------------------------------------------------------------------ attacks


def _drop_component(name):
    """Return control/attack pair for a closure that omits one component."""

    def control(_sandbox):
        closure_module.require_component_lists_agree()

    def attack(_sandbox):
        original = closure_module.COMPONENTS
        closure_module.COMPONENTS = tuple(
            c for c in original if c.name != name
        )
        try:
            closure_module.require_component_lists_agree()
        finally:
            closure_module.COMPONENTS = original

    return control, attack


def _substitute_component(module_name):
    """A component whose bytes change after the roster is sealed."""

    def control(sandbox):
        committed, origins = _copy_components(sandbox)
        _roster().seal()
        return _closure(sandbox, committed, origins)

    def attack(sandbox):
        committed, origins = _copy_components(sandbox)
        _roster().seal()
        target = f"{closure_module.TOOLS}/{module_name}.py"
        (sandbox / target).write_bytes(committed[target] + b"\n# substituted\n")
        return _closure(sandbox, committed, origins)

    return control, attack


def _upstream_control(sandbox):
    committed = _copy_upstream(sandbox)
    origins = {
        pinned.module: str(sandbox / pinned.relative_path)
        for pinned in transport.UPSTREAM_MODULES
    }
    return transport.verify_upstream_binding(
        repository_root=sandbox,
        import_origins=origins,
        read_committed_bytes=lambda _root, path: committed[path],
    )


def _upstream_attack(sandbox):
    committed = _copy_upstream(sandbox)
    origins = {
        pinned.module: str(sandbox / pinned.relative_path)
        for pinned in transport.UPSTREAM_MODULES
    }
    target = "research/tavonel_eval_v2/tools/sfir8_traversal.py"
    mutated = committed[target] + b"\n# mutated upstream\n"
    committed[target] = mutated
    (sandbox / target).write_bytes(mutated)
    return transport.verify_upstream_binding(
        repository_root=sandbox,
        import_origins=origins,
        read_committed_bytes=lambda _root, path: committed[path],
    )


def _blob_control(sandbox):
    committed, origins = _copy_components(sandbox)
    return _closure(sandbox, committed, origins)


def _blob_attack(sandbox):
    committed, origins = _copy_components(sandbox)
    target = f"{closure_module.TOOLS}/sfir9_protocol.py"
    # Same length, different bytes: a size comparison would not see it.
    (sandbox / target).write_bytes(committed[target].replace(b"protocol", b"protocoL", 1))
    return _closure(sandbox, committed, origins)


def _dirty_tree_attack(sandbox):
    committed, origins = _copy_components(sandbox)
    origins["sfir9_scorer"] = "/some/other/dirty/tree/tools/sfir9_scorer.py"
    return _closure(sandbox, committed, origins)


def _selection_digest_control(_sandbox):
    chain = _chain()
    return chain.append(chain.open_next(_handoff()))


def _selection_digest_attack(_sandbox):
    chain = _chain()
    return chain.append(
        chain.open_next(_handoff(selection_digest="sha256:selection-B"))
    )


def _draft_protocol_control(_sandbox):
    return _roster(protocol=protocol_module.Protocol().freeze())


def _draft_protocol_attack(_sandbox):
    return _roster(protocol=protocol_module.Protocol())


def _spent_root_control(_sandbox):
    return _roster(spent=[{"host_uuid": "999999999", "spent_by_study": "SFIR7"}])


def _spent_root_attack(_sandbox):
    selection = selection_module.select(_catalogue(), _rule())
    selected = selection["roster"][0]["host_uuid"]
    return roster_module.CohortRoster(
        protocol=protocol_module.Protocol().freeze(),
        selection=selection,
        exclusion_proof=identity.exclusion_proof(
            identity.spent_set([{"host_uuid": selected, "spent_by_study": "SFIR7"}])
        ),
    )


def _prerequisite_control(sandbox):
    paths = _gate_components(sandbox)
    return gate.evaluate(_declaration(paths), _drift_record(), root=sandbox)


def _prerequisite_attack(sandbox):
    paths = _gate_components(sandbox)
    drift = _drift_record()
    affected = sorted(drift.affected_receipts)[0]
    return gate.evaluate(
        _declaration(paths, scientific_prerequisites=[affected]),
        drift,
        root=sandbox,
    )


def _lookup_control(sandbox):
    paths = _gate_components(sandbox)
    return gate.evaluate(_declaration(paths), _drift_record(), root=sandbox)


def _lookup_attack(sandbox):
    paths = _gate_components(sandbox)
    (sandbox / paths["scorer"]).write_text(
        '"""SFIR9 scorer."""\n'
        "def newest(root):\n"
        "    return sorted(root.glob('*.json'))[-1]\n",
        encoding="utf-8",
    )
    return gate.evaluate(_declaration(paths), _drift_record(), root=sandbox)


def _other_roster_control(_sandbox):
    chain = _chain()
    return chain.append(chain.open_next(_handoff()))


def _other_roster_attack(_sandbox):
    chain = _chain()
    return chain.append(chain.open_next(_handoff(roster_digest="sha256:roster-B")))


_scorer_control, _scorer_attack = _substitute_component("sfir9_scorer")
_transport_control, _transport_attack = _substitute_component("sfir9_transport")
_selection_omitted_control, _selection_omitted_attack = _drop_component("selection_rule")
_gate_omitted_control, _gate_omitted_attack = _drop_component("historical_isolation_gate")


ATTACKS = (
    Attack(
        "selection_rule_omitted_from_closure",
        "drop the selection rule from the closure, so the code choosing which "
        "repositories are studied could change unnoticed",
        closure_module.LIST_DISAGREEMENT,
        _selection_omitted_control,
        _selection_omitted_attack,
        (closure_module.ClosureRefused,),
    ),
    Attack(
        "isolation_gate_omitted_from_closure",
        "drop the isolation gate from the closure, so the code judging historical "
        "dependence could change unnoticed",
        closure_module.LIST_DISAGREEMENT,
        _gate_omitted_control,
        _gate_omitted_attack,
        (closure_module.ClosureRefused,),
    ),
    Attack(
        "scorer_substituted_after_roster_seal",
        "swap the scorer's bytes once the cohort is sealed",
        closure_module.BYTES_MISMATCH,
        _scorer_control,
        _scorer_attack,
        (closure_module.ClosureRefused,),
    ),
    Attack(
        "transport_substituted_after_roster_seal",
        "swap the transport's bytes once the cohort is sealed",
        closure_module.BYTES_MISMATCH,
        _transport_control,
        _transport_attack,
        (closure_module.ClosureRefused,),
    ),
    Attack(
        "upstream_sfir8_module_mutated",
        "edit a frozen SFIR8 module the instrument executes",
        transport.UPSTREAM_HASH,
        _upstream_control,
        _upstream_attack,
        (transport.TransportRefused,),
    ),
    Attack(
        "committed_blob_differs_from_working_bytes",
        "run one thing while the commit records another",
        closure_module.BYTES_MISMATCH,
        _blob_control,
        _blob_attack,
        (closure_module.ClosureRefused,),
    ),
    Attack(
        "import_resolves_from_a_shared_dirty_tree",
        "hash correctly on disk while the interpreter loads another copy",
        closure_module.ORIGIN_MISMATCH,
        _blob_control,
        _dirty_tree_attack,
        (closure_module.ClosureRefused,),
    ),
    Attack(
        "segment_under_a_different_selection_digest",
        "continue a census under a selection rule the roster did not come from",
        chain_module.WRONG_SELECTION,
        _selection_digest_control,
        _selection_digest_attack,
        (chain_module.ChainRefused,),
    ),
    Attack(
        "roster_generated_before_the_protocol_freeze",
        "look at the cohort while the salt, partition and N are still adjustable",
        "PROTOCOL_DRAFT",
        _draft_protocol_control,
        _draft_protocol_attack,
        (protocol_module.ProtocolRefused,),
    ),
    Attack(
        "spent_sfir7_root_appears_in_the_cohort",
        "put a root an earlier study already looked at into the held-out cohort",
        roster_module.SPENT_IN_ROSTER,
        _spent_root_control,
        _spent_root_attack,
        (roster_module.RosterRefused,),
    ),
    Attack(
        "drifted_historical_receipt_as_a_scientific_prerequisite",
        "make a receipt from the failed historical chain a prerequisite of an "
        "SFIR9 gate",
        gate.REFUSAL,
        _prerequisite_control,
        _prerequisite_attack,
        (gate.IsolationRefused,),
    ),
    Attack(
        "authority_selected_by_recency_or_shape",
        "let a component pick its authority with a glob instead of a name and digest",
        gate.REFUSAL,
        _lookup_control,
        _lookup_attack,
        (gate.IsolationRefused,),
    ),
    Attack(
        "checkpoint_chain_from_another_roster",
        "resume a census from a checkpoint belonging to a different cohort",
        chain_module.WRONG_ROSTER,
        _other_roster_control,
        _other_roster_attack,
        (chain_module.ChainRefused,),
    ),
)


def run_attack(attack: Attack, sandbox: Path) -> dict[str, Any]:
    """Control first. An attack whose control failed has taught us nothing."""
    control_sandbox = sandbox / f"{attack.name}__control"
    control_sandbox.mkdir(parents=True, exist_ok=True)
    try:
        attack.control(control_sandbox)
    except Exception as error:
        return {
            "attack": attack.name,
            "what_it_tries": attack.what_it_tries,
            "outcome": CONTROL_FAILED,
            "expected_code": attack.expected_code,
            "observed": f"{type(error).__name__}: {error}",
            "why_this_is_not_a_pass": (
                "the unattacked case did not succeed, so a refusal in the attacked "
                "case would not be evidence that the attack was what refused it."
            ),
        }

    attack_sandbox = sandbox / f"{attack.name}__attack"
    attack_sandbox.mkdir(parents=True, exist_ok=True)
    try:
        attack.attack(attack_sandbox)
    except attack.refusals as error:
        code = getattr(error, "code", None) or type(error).__name__
        matched = attack.expected_code in str(error) or attack.expected_code == code
        return {
            "attack": attack.name,
            "what_it_tries": attack.what_it_tries,
            "outcome": REFUSED if matched else WRONG_CODE,
            "expected_code": attack.expected_code,
            "observed_code": code,
            "refused_by": type(error).__module__,
        }
    except Exception as error:
        return {
            "attack": attack.name,
            "what_it_tries": attack.what_it_tries,
            "outcome": WRONG_CODE,
            "expected_code": attack.expected_code,
            "observed": f"{type(error).__name__}: {error}",
        }
    return {
        "attack": attack.name,
        "what_it_tries": attack.what_it_tries,
        "outcome": NOT_REFUSED,
        "expected_code": attack.expected_code,
    }


def audit(sandbox: Path) -> dict[str, Any]:
    results = [run_attack(attack, sandbox) for attack in ATTACKS]
    refused = [r for r in results if r["outcome"] == REFUSED]
    body = {
        "schema": SCHEMA,
        "attacks_mounted": len(results),
        "attacks_refused": len(refused),
        "results": results,
        "audit_passes": len(refused) == len(results),
        "attacks_whose_control_failed": len(
            [r for r in results if r["outcome"] == CONTROL_FAILED]
        ),
        "why_a_control_failure_is_not_a_pass": (
            "an attack that could not be mounted produces the same silence as an "
            "attack that was refused. Without the control, a broken fixture would "
            "read as a defence."
        ),
        "why_the_code_is_asserted": (
            "a refusal for the wrong reason will stop firing when the wrong reason "
            "goes away."
        ),
    }
    return {
        **body,
        "audit_digest": "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        report = audit(Path(temporary))
    OUTPUT.write_bytes(
        json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    for result in report["results"]:
        print(f"{result['outcome']:<16} {result['attack']}")
    print("-" * 60)
    print(f"{report['attacks_refused']}/{report['attacks_mounted']} refused")
    print(f"HOSTILE_AUDIT = {'PASS' if report['audit_passes'] else 'FAIL'}")
    print(f"written to {OUTPUT.relative_to(REPO).as_posix()}")
    return 0 if report["audit_passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
