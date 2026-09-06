#!/usr/bin/env python3
"""The model identity chain: expected revision == attested revision == frozen revision.

Founder decision of 2026-08-20, P0 and P0.1.

**Three layers, deliberately not merged**, because collapsing them is how a
programme convinces itself it pinned something it did not:

| layer | what it is | file |
|---|---|---|
| source register | *family* evidence: the model card | `docs/compliance/source-register.yaml` |
| candidate registry | the **expected exact revision** | `benchmark/v6/candidate-registry.yaml` |
| runtime attestation | the identity that **actually executed** | captured live, pinned by freeze |

A model card without a revision says nothing about whether the programme pinned
one. It did: `benchmark/v6/candidate-registry.yaml` carries the expected
revision, and the runtime registry has simply not been qualified against it yet.
The accurate statement is *"the candidate evidence registry carries an expected
pinned revision, while the runtime model registry has not yet been qualified
against it"* --- not *"no pinned revision"*.

**The expected revision is read from the registry, never copied into this file.**
A constant here would be a second source of truth, and the two would drift
exactly when it mattered.

**Failure states are distinct**, because they call for different actions:

- `MODEL_RUNTIME_NOT_READY` --- the runtime has not been qualified. Build it.
- `MODEL_IDENTITY_MISMATCH` --- something ran, and it was not the expected
  revision. **Do not overwrite the registry with what happened to run**, and do
  not open the holdout.
- `REGISTRY_AMBIGUOUS` --- the registry does not yield one expected revision.
  Resolve which entry governs before anything else.

**No fallback, at this boundary, regardless of what the serving stack would do.**
The runtime registry entry `qwen3_6_precision` declares
`rollout.fallback_recipe`, which is correct for serving and forbidden here: a
confirmatory run that silently answered from a different model would be
unfalsifiable. Confirmatory integrity outranks model convenience.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CANDIDATE_REGISTRY = ROOT / "benchmark" / "v6" / "candidate-registry.yaml"
RUNTIME_REGISTRY = ROOT / "infra" / "model-registry" / "models.yaml"

#: The W6 arm model. Named explicitly rather than matched by repository, because
#: `qwen3.6-27b-page-parse` shares the repository and is a different candidate:
#: matching on repository alone would silently pick whichever came first.
CANDIDATE_ID = "qwen3.6-27b"
RUNTIME_PROVIDER_KEY = "qwen3_6_precision"
EXPECTED_REPOSITORY = "Qwen/Qwen3.6-27B"

#: Every field the live runtime must produce. `quantization` is here because a
#: bf16 load and a quantized load of the same checkpoint are different executed
#: identities --- pinning the revision while the served weights differ would make
#: the chain look intact and be false. The runtime registry currently records
#: `quantization: review_required`, so this is an open field, not a formality.
REQUIRED_ATTESTATION_FIELDS = (
    "checkpoint_revision",
    "model_file_manifest_sha256",
    "tokenizer_identity",
    "tokenizer_hash",
    "quantization",
    "serving_runtime",
    "serving_runtime_version",
    "runtime_image_digest",
    "model_attestation",
)


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None


def expected_identity(registry: Any = None) -> dict[str, Any]:
    """Read the expected revision from the candidate registry.

    Returns a `state` rather than raising, so a caller can report
    `REGISTRY_AMBIGUOUS` instead of dying inside a gate.
    """
    data = registry if registry is not None else load_yaml(CANDIDATE_REGISTRY)
    if not data:
        return {"state": "REGISTRY_AMBIGUOUS", "why": "the candidate registry is missing "
                                                      "or unreadable"}
    matches = [c for c in (data.get("candidates") or []) if c.get("id") == CANDIDATE_ID]
    if len(matches) != 1:
        return {"state": "REGISTRY_AMBIGUOUS",
                "why": f"expected exactly one candidate with id {CANDIDATE_ID}, "
                       f"found {len(matches)}"}
    identity = matches[0].get("identity") or {}
    revision = identity.get("revision")
    if not revision:
        return {"state": "REGISTRY_AMBIGUOUS",
                "why": f"candidate {CANDIDATE_ID} carries no revision"}
    if identity.get("repository") != EXPECTED_REPOSITORY:
        return {"state": "REGISTRY_AMBIGUOUS",
                "why": f"candidate {CANDIDATE_ID} names repository "
                       f"{identity.get('repository')}, not {EXPECTED_REPOSITORY}"}
    return {
        "state": "EXPECTED_REVISION_PINNED",
        "candidate_id": CANDIDATE_ID,
        "repository": identity["repository"],
        "expected_revision": revision,
        "execution_state": matches[0].get("execution_state"),
        "conditions": matches[0].get("conditions") or [],
        "source": "benchmark/v6/candidate-registry.yaml",
    }


def runtime_registry_state(registry: Any = None) -> dict[str, Any]:
    """What the serving registry currently records. Reported, never trusted as identity."""
    data = registry if registry is not None else load_yaml(RUNTIME_REGISTRY)
    releases = (data or {}).get("releases") or []
    matches = [r for r in releases if r.get("provider_key") == RUNTIME_PROVIDER_KEY]
    if len(matches) != 1:
        return {"state": "REGISTRY_AMBIGUOUS",
                "why": f"expected exactly one release with provider_key "
                       f"{RUNTIME_PROVIDER_KEY}, found {len(matches)}"}
    release = matches[0]
    runtime = release.get("runtime") or {}
    unqualified = [name for name, value in (
        ("upstream_revision", release.get("upstream_revision")),
        ("runtime.version", runtime.get("version")),
        ("runtime.image_digest", runtime.get("image_digest")),
    ) if not value]
    return {
        "state": "QUALIFIED" if not unqualified else "NOT_QUALIFIED",
        "provider_key": RUNTIME_PROVIDER_KEY,
        "upstream_id": release.get("upstream_id"),
        "upstream_revision": release.get("upstream_revision"),
        "quantization": release.get("quantization"),
        "runtime_engine": runtime.get("engine"),
        "runtime_version": runtime.get("version"),
        "runtime_image_digest": runtime.get("image_digest"),
        "declared_fallback_recipe": (release.get("rollout") or {}).get("fallback_recipe"),
        "unqualified_fields": unqualified,
        "source": "infra/model-registry/models.yaml",
    }


def reconcile(attestation: dict[str, Any] | None, *, expected: dict[str, Any] | None = None,
              frozen_revision: str | None = None) -> dict[str, Any]:
    """Check the chain: expected == attested (== frozen, when a freeze exists).

    `frozen_revision` is compared when supplied so the freeze cannot pin a third
    value; a freeze that agrees with neither registry would be a lock on nothing.
    """
    expected = expected if expected is not None else expected_identity()
    if expected["state"] != "EXPECTED_REVISION_PINNED":
        return {"state": "REGISTRY_AMBIGUOUS", "expected": expected,
                "may_proceed": False,
                "why": expected["why"],
                "action": "resolve which registry entry governs before anything else"}

    if not attestation:
        return {
            "state": "MODEL_RUNTIME_NOT_READY", "expected": expected, "may_proceed": False,
            "why": "no live attestation. The candidate registry carries an expected pinned "
                   "revision; the runtime has not been qualified against it",
            "action": "build and qualify the runtime, then attest it",
        }

    missing = [f for f in REQUIRED_ATTESTATION_FIELDS if not attestation.get(f)]
    if missing:
        return {
            "state": "MODEL_RUNTIME_NOT_READY", "expected": expected, "may_proceed": False,
            "missing_attestation_fields": missing,
            "why": "the attestation is incomplete. A name and a revision alone do not "
                   "identify what executed: tokenizer, quantization, serving runtime and "
                   "image digest all change the served identity",
            "action": "capture the missing fields from the live runtime",
        }

    attested = attestation["checkpoint_revision"]
    if attested != expected["expected_revision"]:
        return {
            "state": "MODEL_IDENTITY_MISMATCH", "expected": expected, "may_proceed": False,
            "expected_revision": expected["expected_revision"],
            "attested_revision": attested,
            "why": "something executed and it was not the expected revision",
            "action": "do NOT overwrite the candidate registry with whatever ran, and do "
                      "NOT open the holdout. Either serve the expected revision or record "
                      "a deliberate, reviewed change of expectation",
        }

    if frozen_revision is not None and frozen_revision != attested:
        return {
            "state": "MODEL_IDENTITY_MISMATCH", "expected": expected, "may_proceed": False,
            "expected_revision": expected["expected_revision"],
            "attested_revision": attested, "frozen_revision": frozen_revision,
            "why": "the freeze pins a revision that is neither expected nor attested",
            "action": "a freeze that agrees with neither registry is a lock on nothing; "
                      "rebuild it from the attested identity",
        }

    return {
        "state": "MODEL_IDENTITY_RECONCILED", "may_proceed": True,
        "expected": expected,
        "chain": {
            "candidate_registry_expected_revision": expected["expected_revision"],
            "live_attested_revision": attested,
            "config_freeze_revision": frozen_revision,
        },
        "equality_note": "candidate registry expected == live attestation"
                         + (" == config freeze" if frozen_revision else
                            " (freeze not yet written)"),
    }


def fallback_is_forbidden_here(runtime_state: dict[str, Any]) -> dict[str, Any]:
    """The serving registry may declare a fallback. W6 may not use one.

    This is not a defect in the registry --- a fallback recipe is correct for
    serving. It is forbidden at this boundary, and the refusal has to live here
    rather than rely on the serving stack behaving.
    """
    declared = runtime_state.get("declared_fallback_recipe")
    return {
        "declared_fallback_recipe": declared,
        "fallback_permitted_for_w6": False,
        "holds": True,
        "why": "no automatic substitution: not another Qwen revision, not qwen3.5, not "
               "Gemma, not a provider API model, not the session model. If the expected "
               "revision cannot be qualified the run stays MODEL_RUNTIME_NOT_READY. "
               "Confirmatory integrity outranks model convenience.",
        "note": ("the runtime registry declares a fallback recipe for serving; W6 refuses "
                 "it independently rather than trusting the serving stack"
                 if declared else "the runtime registry declares no fallback recipe"),
    }


def identity_controls() -> dict[str, Any]:
    """Each failure state must be reachable, in this execution."""
    registry = {"candidates": [{
        "id": CANDIDATE_ID, "execution_state": "artifact_manifest_and_runtime_pending",
        "identity": {"repository": EXPECTED_REPOSITORY, "revision": "a" * 40},
        "conditions": [],
    }]}
    good = expected_identity(registry)
    complete = dict.fromkeys(REQUIRED_ATTESTATION_FIELDS, "value")
    complete["checkpoint_revision"] = "a" * 40

    reconciled = reconcile(complete, expected=good)
    mismatch = reconcile(dict(complete, checkpoint_revision="b" * 40), expected=good)
    not_ready = reconcile(None, expected=good)
    incomplete = reconcile({k: v for k, v in complete.items()
                            if k != "runtime_image_digest"}, expected=good)
    frozen_third = reconcile(complete, expected=good, frozen_revision="c" * 40)
    no_revision = reconcile(complete, expected=expected_identity(
        {"candidates": [{"id": CANDIDATE_ID,
                         "identity": {"repository": EXPECTED_REPOSITORY,
                                      "revision": None}}]}))
    duplicated = expected_identity({"candidates": [
        {"id": CANDIDATE_ID, "identity": {"repository": EXPECTED_REPOSITORY,
                                          "revision": "a" * 40}},
        {"id": CANDIDATE_ID, "identity": {"repository": EXPECTED_REPOSITORY,
                                          "revision": "b" * 40}}]})

    checks = {
        "matching_revision_reconciles": reconciled["state"] == "MODEL_IDENTITY_RECONCILED",
        "differing_revision_is_a_mismatch": mismatch["state"] == "MODEL_IDENTITY_MISMATCH",
        "mismatch_refuses_to_proceed": not mismatch["may_proceed"],
        "absent_attestation_is_not_ready": not_ready["state"] == "MODEL_RUNTIME_NOT_READY",
        "incomplete_attestation_is_not_ready":
            incomplete["state"] == "MODEL_RUNTIME_NOT_READY",
        "quantization_is_required": "quantization" in REQUIRED_ATTESTATION_FIELDS,
        "a_freeze_pinning_a_third_revision_is_a_mismatch":
            frozen_third["state"] == "MODEL_IDENTITY_MISMATCH",
        "a_registry_without_a_revision_is_ambiguous":
            no_revision["state"] == "REGISTRY_AMBIGUOUS",
        "a_duplicated_candidate_id_is_ambiguous":
            duplicated["state"] == "REGISTRY_AMBIGUOUS",
        "not_ready_and_mismatch_are_different_states":
            not_ready["state"] != mismatch["state"],
    }
    checks["separates"] = all(checks.values())
    return checks


def main() -> int:
    expected = expected_identity()
    runtime = runtime_registry_state()
    controls = identity_controls()
    chain = reconcile(None, expected=expected)
    fallback = fallback_is_forbidden_here(runtime)

    print(f"expected  : {expected.get('expected_revision')}  ({expected['state']})")
    print(f"runtime   : revision={runtime.get('upstream_revision')} "
          f"version={runtime.get('runtime_version')} "
          f"digest={runtime.get('runtime_image_digest')}  ({runtime['state']})")
    print(f"quantization: {runtime.get('quantization')}")
    print(f"declared fallback recipe: {fallback['declared_fallback_recipe']} "
          f"(permitted for W6: {fallback['fallback_permitted_for_w6']})")
    print(f"chain     : {chain['state']}  may_proceed={chain['may_proceed']}")
    print(f"controls separate: {controls['separates']}")
    print(json.dumps({"expected": expected, "runtime": runtime, "chain_state": chain["state"],
                      "controls": controls}, indent=2, sort_keys=True)[:0] or "", end="")
    return 0 if controls["separates"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
