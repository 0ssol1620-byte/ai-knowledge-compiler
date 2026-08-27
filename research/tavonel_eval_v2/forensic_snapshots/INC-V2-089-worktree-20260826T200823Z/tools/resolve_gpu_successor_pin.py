#!/usr/bin/env python3
"""Resolve `protocols/GPU_SUCCESSOR_MODEL_PIN_V1.yaml` into an attested pin.

`tools/gpu_successor_preflight.py` reports `G_GSP_MODEL_PINNED: passed=false`
because it is never handed a pin — its `default_model_pin()` returns `{}` on
purpose (see that function's docstring). This tool is the thing a caller wires
in instead: it loads the pin declaration, validates its shapes, cross-checks
every value it claims to have copied from `MODEL_ENDPOINT_V1.yaml` against
that file as it exists right now (not against a comment describing it), and
refuses loudly on any mismatch. A successor silently running a different
revision than the one MODEL_ENDPOINT_V1 attested is exactly the failure mode
this exists to catch before a single GPU second is spent.

Nothing here fetches over the network or loads a model. The tokenizer parity
check calls only `tokenizer_parity.battery_digest()` — the frozen probe
battery's own digest, CPU-only and content-independent of any live tokenizer —
and records it as such. `run_battery()`, which needs an actual loaded
tokenizer, is not invoked; see `GPU_SUCCESSOR_MODEL_PIN_V1.yaml`'s
`tokenizer_parity.what_is_not_attestable_here`.

This tool never touches `receipts/sfi2-*` or `artifacts/development/sfi2_cache/`
— it reads only `protocols/GPU_SUCCESSOR_MODEL_PIN_V1.yaml` and
`protocols/MODEL_ENDPOINT_V1.yaml`, and writes exactly one new immutable
receipt under a distinct stem (`gpu-successor-pin`) via
`tools/evidence.py::write_immutable`, which creates a new run-specific file
and never overwrites or reads any other stem's receipts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "endpoint"))

from common import NS, now, rel, sha_file
from evidence import write_immutable
from gpu_successor_preflight import RUNTIME_IMAGE_DIGEST_PATTERN
from tokenizer_parity import PROBE_CLASSES, battery_digest

PIN_PATH = NS / "protocols" / "GPU_SUCCESSOR_MODEL_PIN_V1.yaml"
MODEL_ENDPOINT_PATH = NS / "protocols" / "MODEL_ENDPOINT_V1.yaml"

REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
TOKENIZER_SHA_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

#: The pin fields that must agree, byte for byte, with MODEL_ENDPOINT_V1's own
#: `model:` block and `runtime.runtime_image_digest`. Keyed by the pin's field
#: name -> the closed protocol's field path, so a mismatch report can say
#: exactly which two values disagreed and where each came from.
CROSS_CHECK_FIELDS: tuple[tuple[str, str], ...] = (
    ("repository", "model.repository"),
    ("revision", "model.revision"),
    ("tokenizer_revision", "model.tokenizer_revision"),
    ("tokenizer_file_sha256", "model.tokenizer_file_sha256"),
    ("chat_template_sha256", "model.chat_template_sha256"),
)


class PinValidationError(RuntimeError):
    """The pin declaration is malformed, or disagrees with what it claims to copy."""


def _get_path(body: dict[str, Any], dotted: str) -> Any:
    node: Any = body
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise PinValidationError(
                f"MODEL_ENDPOINT_V1.yaml has no field '{dotted}' to cross-check against"
            )
        node = node[part]
    return node


def load_pin(path: Path = PIN_PATH) -> dict[str, Any]:
    if not path.exists():
        raise PinValidationError(f"pin file not found: {rel(path)}")
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise PinValidationError(f"{rel(path)} did not parse to a mapping")
    return body


def load_model_endpoint(path: Path = MODEL_ENDPOINT_PATH) -> dict[str, Any]:
    if not path.exists():
        raise PinValidationError(f"MODEL_ENDPOINT_V1.yaml not found: {rel(path)}")
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise PinValidationError(f"{rel(path)} did not parse to a mapping")
    return body


def validate_shapes(pin: dict[str, Any]) -> dict[str, Any]:
    """Structural checks only. Refuses loudly (raises) rather than reporting a
    passed=False gate, because a malformed pin is a bug in the pin, not a
    finding about the study — the caller should not be able to proceed past
    this by design."""
    model = pin.get("model")
    if not isinstance(model, dict):
        raise PinValidationError("pin has no 'model' mapping")

    repository = model.get("repository", "")
    if not repository:
        raise PinValidationError("pin.model.repository is empty")

    revision = model.get("revision", "")
    if revision == "latest":
        raise PinValidationError(
            "pin.model.revision is 'latest' — exact revision required, refused"
        )
    if not REVISION_PATTERN.match(revision or ""):
        raise PinValidationError(
            f"pin.model.revision {revision!r} is not 40 hex characters — refused"
        )

    tokenizer_sha = model.get("tokenizer_file_sha256", "")
    if not TOKENIZER_SHA_PATTERN.match(tokenizer_sha or ""):
        raise PinValidationError(
            f"pin.model.tokenizer_file_sha256 {tokenizer_sha!r} is not 'sha256:' + 64 hex — refused"
        )

    image_digest = pin.get("runtime_image_digest", "")
    if not RUNTIME_IMAGE_DIGEST_PATTERN.match(image_digest or ""):
        raise PinValidationError(
            f"pin.runtime_image_digest {image_digest!r} does not match "
            "gpu_successor_preflight.RUNTIME_IMAGE_DIGEST_PATTERN — refused"
        )

    return {
        "repository": repository,
        "revision": revision,
        "revision_is_40_hex": True,
        "revision_not_latest": True,
        "tokenizer_file_sha256": tokenizer_sha,
        "tokenizer_sha_well_formed": True,
        "runtime_image_digest": image_digest,
        "runtime_image_digest_well_formed": True,
    }


def cross_check_against_model_endpoint(
    pin: dict[str, Any], model_endpoint: dict[str, Any]
) -> dict[str, Any]:
    """Every value the pin claims to have copied from MODEL_ENDPOINT_V1, compared
    against that file as it stands now. Raises on the first mismatch — this is
    the check that exists specifically to catch a successor silently drifting
    from the endpoint it says it reused."""
    model = pin["model"]
    results: dict[str, dict[str, Any]] = {}
    mismatches: list[str] = []

    for pin_field, endpoint_path in CROSS_CHECK_FIELDS:
        pin_value = model.get(pin_field)
        endpoint_value = _get_path(model_endpoint, endpoint_path)
        matches = pin_value == endpoint_value
        results[pin_field] = {
            "pin_value": pin_value,
            "model_endpoint_v1_value": endpoint_value,
            "model_endpoint_v1_path": endpoint_path,
            "matches": matches,
        }
        if not matches:
            mismatches.append(pin_field)

    pin_image = pin.get("runtime_image_digest")
    endpoint_image = _get_path(model_endpoint, "runtime.runtime_image_digest")
    image_matches = pin_image == endpoint_image
    results["runtime_image_digest"] = {
        "pin_value": pin_image,
        "model_endpoint_v1_value": endpoint_image,
        "model_endpoint_v1_path": "runtime.runtime_image_digest",
        "matches": image_matches,
    }
    if not image_matches:
        mismatches.append("runtime_image_digest")

    if mismatches:
        detail = "; ".join(
            f"{field}: pin={results[field]['pin_value']!r} != "
            f"MODEL_ENDPOINT_V1.{results[field]['model_endpoint_v1_path']}="
            f"{results[field]['model_endpoint_v1_value']!r}"
            for field in mismatches
        )
        raise PinValidationError(
            "pin disagrees with protocols/MODEL_ENDPOINT_V1.yaml on "
            f"{len(mismatches)} field(s), refused: {detail}"
        )

    return {"fields_checked": list(results), "all_match": True, "detail": results}


def capability_report(pin: dict[str, Any]) -> dict[str, Any]:
    """Report what `capability_evidence` claims, verbatim, for the caller to
    hand to `gpu_successor_preflight.capability_from_registry`. This function
    does not itself decide `capability_claimed` — that decision belongs to the
    preflight, which this tool must not duplicate or loosen."""
    evidence = pin.get("capability_evidence", {})
    return {
        "present": bool(evidence.get("present")),
        "pointer": evidence.get("pointer"),
        "distinct_from_repository_name": evidence.get("distinct_from_repository_name"),
    }


def tokenizer_parity_report() -> dict[str, Any]:
    """The frozen-contract check only — see module docstring."""
    first = battery_digest()
    second = battery_digest()
    return {
        "battery_digest": first,
        "deterministic": first == second,
        "probe_classes": list(PROBE_CLASSES),
        "kind": "frozen_contract_digest",
        "live_tokenizer_parity": "NOT_YET_ATTESTED — no tokenizer loaded, no network, no GPU",
    }


def resolved_pin_dict(pin: dict[str, Any]) -> dict[str, Any]:
    """The shape `gpu_successor_preflight.model_identity_pin` expects: a flat
    dict with `repository`, `revision`, `tokenizer_file_sha256` and
    `capability_evidence` (a pointer string, or falsy/name-equal to signal no
    evidence — see `capability_from_registry`)."""
    model = pin["model"]
    evidence = pin.get("capability_evidence", {})
    capability_evidence_value = evidence.get("pointer") if evidence.get("present") else None
    return {
        "repository": model["repository"],
        "revision": model["revision"],
        "tokenizer_file_sha256": model["tokenizer_file_sha256"],
        "capability_evidence": capability_evidence_value,
    }


def write_sealed_export(path: Path, resolved_pin: dict[str, Any]) -> dict[str, str]:
    """Write the flat preflight input once and return the file digest that seals it.

    The export deliberately contains only the operational pin fields.  Its
    authority is the exact path plus the returned file SHA-256; callers must
    supply both to ``gpu_successor_preflight.py``.  Exclusive creation prevents
    a later resolution from silently replacing the bytes behind an old path.
    """
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(resolved_pin, indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")
    return {"sealed_export": str(target), "sealed_export_file_sha256": sha_file(target)}


def resolve(
    pin_path: Path = PIN_PATH, model_endpoint_path: Path = MODEL_ENDPOINT_PATH
) -> dict[str, Any]:
    started = now()
    pin = load_pin(pin_path)
    model_endpoint = load_model_endpoint(model_endpoint_path)

    shapes = validate_shapes(pin)
    cross_check = cross_check_against_model_endpoint(pin, model_endpoint)
    capability = capability_report(pin)
    parity = tokenizer_parity_report()
    resolved = resolved_pin_dict(pin)
    closed_endpoint_relationship = pin.get("closed_endpoint_relationship", {})

    return {
        "schema": "tavonel.v2.gpu_successor_pin_resolution.v1",
        "started_at": started,
        "ended_at": now(),
        "pin_source": {
            "path": rel(pin_path),
            "sha256": sha_file(pin_path),
        },
        "model_endpoint_source": {
            "path": rel(model_endpoint_path),
            "sha256": sha_file(model_endpoint_path),
        },
        "shape_validation": shapes,
        "cross_check_against_model_endpoint": cross_check,
        "closed_endpoint_relationship": closed_endpoint_relationship,
        "capability_evidence": capability,
        "tokenizer_parity": parity,
        "resolved_pin": resolved,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "note": (
            "this receipt attests that the pin is well-formed and agrees with "
            "MODEL_ENDPOINT_V1.yaml. It does not attest a live tokenizer load, "
            "a live config.json re-hash, or any model capability beyond what "
            "capability_evidence.pointer names. No GPU second was spent."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=Path, default=PIN_PATH)
    parser.add_argument("--model-endpoint", type=Path, default=MODEL_ENDPOINT_PATH)
    parser.add_argument(
        "--sealed-export",
        type=Path,
        default=None,
        help="optionally write the resolved_pin mapping once to this exact path",
    )
    args = parser.parse_args()

    try:
        body = resolve(args.pin, args.model_endpoint)
    except PinValidationError as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 2

    written = write_immutable(
        "gpu-successor-pin",
        body,
        tool=Path(__file__).resolve(),
        protocol=args.pin,
    )
    export = (
        write_sealed_export(args.sealed_export, body["resolved_pin"])
        if args.sealed_export is not None
        else {}
    )
    summary = {**written, **export, "resolved_pin": body["resolved_pin"]}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
