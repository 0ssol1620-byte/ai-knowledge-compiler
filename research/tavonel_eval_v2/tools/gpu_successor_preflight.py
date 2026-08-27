#!/usr/bin/env python3
"""GPU successor study preflight — CPU only, outcome-independent, runnable now.

STOP-V2-005 closed the exact-value model endpoint after three preregistered CPU
preflights refused it in turn: a cohort selected for semantic change could not
pose an exact-value question (10 of 296 survived), sources selected for
value-bearing structure yielded no moved value under blind sampling (0 of 174),
and a complete walk of 2,271 fresh lineages found a qualifying value transition
in 3. The founder's ruling on that closure is explicit: "no successor cohort may
be created to chase the 190 floor." This tool is not that successor.

The successor this tool prepares for is a different endpoint, built around what
SOURCE_FACT_IR_V1 (`source_fact_ir/ir.py`) actually repairs: representation
completeness. The exact-value endpoint needed a value that MOVED between two
revisions of one lineage — a temporal transition scarce enough that a complete
history walk found it three times in 2,271 tries. The typed-propagation
endpoint needs no transition at all. It needs a single revision carrying a
typed fact — a reference target, a language tag, an effective date, an
applicability scope — that is REPRESENTED_IN_COMPILED_STATE and is NOT visible
in the unit's own text. A system that keeps only the text cannot answer a
question built from that fact; a system that keeps the IR's representation can.
Eligibility is a property of one revision, not of a pair, and the previous
endpoint's scarcity problem does not apply to it by construction.

That is a hypothesis, not a result. This tool never asserts the hypothesis
holds — see `design_excludes_closed_endpoint` and the cohort-feasibility check
below, which is honest about zero when no cohort has been assembled.

What this tool checks, entirely on CPU, entirely before any held-out result
exists:

* the central gate — a fresh held-out SOURCE_FACT_IR study must have PASSED
  before this preflight will ever say the GPU study is ready. Absence is a
  hard block. There is no code path that reports "ready" around it;
* model and runtime identity, pinned by exact repository and revision, never
  read from a bare name (`capability_from_registry`, `model_identity_pin`);
* tokenizer parity, via the frozen probe battery already built for the closed
  study (`endpoint.tokenizer_parity`) — reused because the contract it checks
  (do two tokenizer loads segment text the same way) does not change with the
  endpoint;
* runtime image digest pinnability (a `repo@sha256:<64 hex>` reference, not a
  floating tag);
* cache and input-materializer readiness (the CPU materialization machinery
  this study would reuse is importable and carries the functions it needs);
* context-budget feasibility for the kind of prompt this endpoint would send;
* cohort feasibility — does a cohort of typed-fact questions actually exist at
  the declared floor? Checked against a manifest if one exists, and reported
  as infeasible with an honest zero if it does not. This is the check the
  three closed preflights teach loudest: check whether the cohort can pose its
  question before anything else;
* the cost cap, arithmetically: the declared study parameters are multiplied
  out to an estimated GPU-hour and dollar figure and compared against the
  founder's approved ceiling, with the arithmetic shown in the receipt rather
  than asserted.

Nothing here executes inference, provisions a pod, or spends a GPU second. Both
`gpu_seconds` and `estimated_cost_usd` are 0 in the receipt this tool itself
writes, always — see `G_GSP_NO_GPU_YET`.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "endpoint"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source_fact_ir"))

import freeze_gpu_successor_protocols as gpu_protocol_freeze
import ir
import live_cohort_guard
from common import NS, canonical_sha, now, rel, sha_file
from evidence import SCHEMA as IMMUTABLE_ENVELOPE_SCHEMA
from evidence import write_immutable
from tokenizer_parity import PROBE_CLASSES, battery_digest

# ---------------------------------------------------------------------------
# what the successor study is, declared, not measured
# ---------------------------------------------------------------------------

STUDY_ID = "SOURCE_FACT_PROPAGATION_MODEL_V1"

#: The two declarations that say what this study is and how it runs. The
#: preflight reads them, so the preflight records what it read.
STUDY_PROTOCOL = NS / "protocols" / "GPU_SUCCESSOR_STUDY_V1.yaml"
RUNTIME_PROTOCOL = NS / "protocols" / "GPU_SUCCESSOR_RUNTIME_V1.yaml"

PIN_RESOLUTION_SCHEMA = "tavonel.v2.gpu_successor_pin_resolution.v1"
PIN_RESOLUTION_STEM = "gpu-successor-pin"
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


#: Everything a GPU run is decided by, in one place. Six, not two: the study
#: and runtime declarations say what the run IS, the manifest says what it runs
#: OVER, the model pin says what runs it, and the two acceptances say what
#: authorised it. A digest recorded for four of six and re-read for two is a
#: binding with two unwatched doors.
DECLARATION_KEYS = (
    "study",
    "runtime",
    "manifest",
    "model_pin",
    "sfi3_acceptance",
    "four_link_acceptance",
)

#: What a block reports when the file is not there. Distinct from a digest, and
#: distinct from a missing key: an absent declaration and an unread one are
#: different states and only one of them is a reason to stop.
ABSENT = "ABSENT"


def _digest_block(path: Path | None) -> dict[str, str | None]:
    """One path as {path, sha256}, reporting absence rather than raising.

    `_safe_rel`, not `rel`: a named receipt may sit outside the repository
    entirely, and a path helper that raises would turn a reportable state into
    a crash.
    """
    if path is None:
        return {"path": None, "sha256": ABSENT}
    return {
        "path": _safe_rel(path),
        "sha256": sha_file(path) if path.is_file() else ABSENT,
    }


def declaration_digests(
    *,
    manifest: Path | None = None,
    model_pin: Path | None = None,
    sfi3_acceptance: Path | None = None,
    four_link_acceptance: Path | None = None,
) -> dict[str, dict[str, str | None]]:
    """The six inputs a GPU spend is decided by, as they are right now.

    The two protocol paths are fixed by this module; the other four are named
    by the caller, because an authority that can be searched for is an authority
    that can be found by accident.
    """
    out: dict[str, dict[str, str | None]] = {
        "study": _digest_block(STUDY_PROTOCOL),
        "runtime": _digest_block(RUNTIME_PROTOCOL),
        "manifest": _digest_block(manifest),
        "model_pin": _digest_block(model_pin),
        "sfi3_acceptance": _digest_block(sfi3_acceptance),
        "four_link_acceptance": _digest_block(four_link_acceptance),
    }
    #: Set equality, not a count: six wrong names would satisfy a count.
    #: INC-V2-067 is the record of what a count buys.
    if set(out) != set(DECLARATION_KEYS):
        raise RuntimeError(f"declaration domain drift: {sorted(set(out) ^ set(DECLARATION_KEYS))}")
    return out


#: The closed endpoint, cited so the exclusion check below has something
#: concrete to compare against rather than a description of it.
FORBIDDEN_ENDPOINT_ID = "MODEL_ENDPOINT_V1"
FORBIDDEN_STOP_RECORD = "STOP-V2-005"
#: `endpoint/value_scorer.py` classes for the closed exact-value endpoint,
#: named here (not imported) so this module carries no dependency on the
#: machinery it must not reuse.
FORBIDDEN_SCORER_CLASSES = ("CURRENT_ONLY", "SUPERSEDED_ONLY", "BOTH", "NO_MATCH")

#: The typed-fact kinds this endpoint draws questions from. Each is named
#: explicitly in the founder's framing of the successor: a reference target, a
#: language tag, an effective date, an applicability scope.
ELIGIBLE_KINDS: tuple[str, ...] = (
    ir.REFERENCE_TARGET,
    ir.LANGUAGE,
    ir.EFFECTIVE_TIME,
    ir.APPLICABILITY,
)

#: The property that made the closed endpoint's cohort scarce. This design
#: does not have it: eligibility is decided from one revision's representation,
#: never from whether a value moved between two revisions of a lineage.
REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS = False

#: This design's scorer classes. Disjoint from the closed endpoint's by
#: construction — see `design_excludes_closed_endpoint`.
SCORER_CLASSES = ("REPRESENTATION_CORRECT", "REPRESENTATION_INCORRECT", "REFUSED")

#: Declared, not measured. No fresh cohort has been walked for this study yet,
#: so there is no yield to fit this to. Chosen independently of the closed
#: study's 190 — a different endpoint carries a different power requirement,
#: and reusing that number here would look like a refit even though nothing
#: was refit.
COHORT_FLOOR = 120

ARMS = ("TYPED_REPRESENTATION", "TEXT_ONLY_BASELINE")
DETERMINISM_REPEATS = 2  # stage 1 pass + stage 2 determinism repeat, as MODEL_ENDPOINT_V1 used

#: CPU-only estimate of the budget one materialized prompt needs. This is a
#: declared parameter for the cost arithmetic below, not a live tokenizer
#: measurement — per-item tokenization happens in the study's own CPU
#: materialization stage, which this preflight does not perform because no
#: cohort exists yet to materialize.
ESTIMATED_PROMPT_TOKENS = 2048
MAX_NEW_TOKENS = 256
CONTEXT_BUDGET_TOKENS = 4096  # endpoint/context_builder.py's TOTAL_PROMPT_TOKENS

#: Declared throughput and price assumptions for the cost arithmetic. Neither
#: is a measurement — no GPU second has been spent — and both are recorded as
#: `declared_assumption` in the receipt so a reader cannot mistake them for
#: observed figures. The throughput is an aggregate batched figure (vLLM
#: continuous batching serves the whole cohort concurrently, not one
#: generation at a time), which is why it is far above a single-stream rate.
DECLARED_THROUGHPUT_TOKENS_PER_SECOND = 2000.0
DECLARED_GPU_HOURLY_RATE_USD = 2.5

CAP_GPU_HOURS = 6.0
CAP_USD = 40.0

#: The fresh held-out study this preflight refuses to proceed without.
#:
#: Corrected twice, and the second correction matters more than the first. It
#: began as a guess at a name (`sfh2-source-faithfulness`) made before any such
#: study existed, and was pointed at `sfi1-source-fact-ir` once that study ran.
#: SFI1 then returned FAIL, and the founder froze it: never rescored, its corpus
#: spent, its receipt permanent. So the stem named a study that COULD NEVER TURN
#: GREEN — the gate would have held, correctly by luck, while reporting "the
#: study did not pass" about a study that was no longer the one being waited on.
#:
#: A gate that blocks for the wrong reason will one day unblock for the wrong
#: reason too, and this is the second time that sentence has been the fix here.
#: It now names SFI2, the study whose PASS the founder's ruling actually
#: authorises GPU execution on.
#: RETIRED. SFI2 is frozen, FAIL, spent and permanently non-rescorable, so a
#: requirement for an SFI2 PASS was structurally impossible and can never have
#: been the live authorization path. The constant is kept, empty and named, so
#: a reader of an old receipt or an old branch finds the explanation rather than
#: a missing symbol -- and so that anything still importing it fails loudly on
#: an empty stem instead of quietly searching for a receipt that cannot exist.
#:
#: SFI2's receipts and history are untouched. Nothing here rescores or
#: reinterprets that study.
RETIRED_HELD_OUT_STUDY_STEM = ""
RETIRED_HELD_OUT_STUDY_REASON = (
    "sfi2-native-provenance is frozen, FAIL and spent. GPU authorization now "
    "requires an explicit SOURCE_FACT_IR_HELDOUT_ACCEPTANCE_V1 receipt for "
    "SOURCE_FACT_IR_HELDOUT_V3 plus a FOUR_LINK_ACCEPTANCE_V1 receipt for the "
    "exact cohort about to run."
)

#: Kept so the block message can say why the predecessor does not count. A
#: reader who remembers SFI1 as "the source-fact study" deserves to be told it
#: was superseded rather than left to wonder whether the gate forgot it.
SUPERSEDED_STUDY_STEMS: tuple[tuple[str, str], ...] = (
    (
        "sfi1-source-fact-ir",
        "returned FAIL on held-out data and is frozen; it is never rescored and "
        "its corpus is development material, so no PASS can ever appear under it",
    ),
    (
        "sfh1-source-faithfulness",
        "demoted to a development diagnostic by the hygiene pass; its chronology "
        "does not support a held-out reading",
    ),
)

RUNTIME_IMAGE_DIGEST_PATTERN = re.compile(r"^[\w./-]+@sha256:[0-9a-f]{64}$")

#: Import roots this module must never carry, checked by AST rather than
#: asserted. `G_GSP_NO_GPU_YET` used to be a hardcoded `True`, so nothing
#: distinguished a preflight that spends nothing from one that had just
#: grown an HTTP client -- INC-V2-036's class in its plainest form. INC-V2-104
#: B established the absence of any network symbol here as the authority for
#: moving the live-cohort guard off `run()`; that authority is now re-checked
#: on every run instead of being taken once by hand.
#:
#: AST, not a textual grep: this module's own docstring and comments discuss
#: sockets and HTTP clients in prose, and a grep would be red for the wrong
#: reason -- which is how a guard stops being read.
FORBIDDEN_RUNTIME_MODULE_ROOTS: frozenset[str] = frozenset(
    {
        "urllib",
        "socket",
        "http",
        "httplib",
        "requests",
        "httpx",
        "aiohttp",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "websockets",
        "ssl",
        "subprocess",
        "boto3",
        "openai",
        "anthropic",
        "huggingface_hub",
        "transformers",
        "torch",
        "vllm",
        "runpod",
    }
)

#: A capability pointer is registry evidence only if it is content-addressed —
#: it must carry a 64-hex digest naming the exact artifact the capability was
#: read out of. Searched anywhere in the pointer, not anchored, because the
#: pin's own pointer form is a path plus a fragment plus `= <digest>` and this
#: check is about whether a digest is present at all, not about its position.
CAPABILITY_EVIDENCE_DIGEST_PATTERN = re.compile(r"\b[0-9a-f]{64}\b")


def _safe_rel(path: Path) -> str:
    """`common.rel` assumes a path under the repo root, which a test fixture
    manifest or receipt need not be. Falls back to the plain string rather
    than raising, since this is a display field, not an identity check."""
    try:
        return rel(path)
    except ValueError:
        return str(path)


def _normalise_expected_sha(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.lower()
    return value if value.startswith("sha256:") else "sha256:" + value


def load_model_pin_artifact(path: Path | None, expected_file_sha256: str | None) -> dict[str, Any]:
    """Load an exact resolved-pin receipt or an exact flat sealed export.

    A caller must supply both a path and the file SHA it intended to consume.
    Resolver receipts expose the operational values under ``resolved_pin``;
    treating the envelope itself as that flat mapping was the old integration
    defect.  A flat export is also accepted, but only because the caller's
    expected file SHA seals every byte of that export.
    """
    expected = _normalise_expected_sha(expected_file_sha256)
    if path is None or expected is None:
        return {
            "passed": False,
            "path": _safe_rel(path) if path is not None else None,
            "expected_file_sha256": expected,
            "resolved_pin": {},
            "why": "exact model-pin artifact path and file SHA-256 are both required",
        }
    if not SHA256_PATTERN.fullmatch(expected):
        return {
            "passed": False,
            "path": _safe_rel(path),
            "expected_file_sha256": expected,
            "resolved_pin": {},
            "why": "expected model-pin file SHA-256 is malformed",
        }
    if not path.is_file():
        return {
            "passed": False,
            "path": _safe_rel(path),
            "expected_file_sha256": expected,
            "resolved_pin": {},
            "why": "named model-pin artifact is not on disk",
        }
    actual = sha_file(path)
    if actual != expected:
        return {
            "passed": False,
            "path": _safe_rel(path),
            "expected_file_sha256": expected,
            "actual_file_sha256": actual,
            "resolved_pin": {},
            "why": "model-pin artifact file SHA-256 drift",
        }
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "passed": False,
            "path": _safe_rel(path),
            "expected_file_sha256": expected,
            "actual_file_sha256": actual,
            "resolved_pin": {},
            "why": f"model-pin artifact is unreadable: {error}",
        }
    if not isinstance(body, dict):
        return {
            "passed": False,
            "path": _safe_rel(path),
            "expected_file_sha256": expected,
            "actual_file_sha256": actual,
            "resolved_pin": {},
            "why": "model-pin artifact is not a JSON mapping",
        }

    if "resolved_pin" in body:
        provenance = body.get("provenance")
        canonical = canonical_sha(
            {key: value for key, value in body.items() if key != "receipt_sha256"}
        )
        receipt_checks = {
            "resolution_schema": body.get("schema") == PIN_RESOLUTION_SCHEMA,
            "immutable_envelope": isinstance(provenance, dict)
            and provenance.get("schema") == IMMUTABLE_ENVELOPE_SCHEMA
            and provenance.get("immutable") is True
            and provenance.get("receipt_stem") == PIN_RESOLUTION_STEM,
            "canonical_receipt_digest": body.get("receipt_sha256") == canonical,
            "nested_mapping": isinstance(body.get("resolved_pin"), dict),
        }
        if not all(receipt_checks.values()):
            return {
                "passed": False,
                "path": _safe_rel(path),
                "expected_file_sha256": expected,
                "actual_file_sha256": actual,
                "kind": "resolver_receipt",
                "receipt_checks": receipt_checks,
                "resolved_pin": {},
                "why": "nested resolved-pin receipt is not an intact immutable resolver receipt",
            }
        resolved = body["resolved_pin"]
        kind = "resolver_receipt"
        #: The same sealed bytes also carry the resolver's frozen tokenizer-probe
        #: battery digest. Carried out here so `G_GSP_TOKENIZER_PARITY_BATTERY_
        #: AVAILABLE` has something outside itself to compare against; a flat
        #: export has no such block and is reported as None rather than assumed.
        attestation = body.get("tokenizer_parity")
    else:
        resolved = body
        kind = "sealed_flat_export"
        attestation = None

    required = {"repository", "revision", "tokenizer_file_sha256"}
    missing = sorted(required - set(resolved))
    if missing:
        return {
            "passed": False,
            "path": _safe_rel(path),
            "expected_file_sha256": expected,
            "actual_file_sha256": actual,
            "kind": kind,
            "resolved_pin": {},
            "why": f"model-pin artifact lacks required fields: {missing}",
        }
    return {
        "passed": True,
        "path": _safe_rel(path),
        "expected_file_sha256": expected,
        "actual_file_sha256": actual,
        "kind": kind,
        "resolved_pin": resolved,
        "tokenizer_parity_attestation": attestation
        if isinstance(attestation, dict)
        else None,
    }


# ---------------------------------------------------------------------------
# the central gate
# ---------------------------------------------------------------------------


def _read_acceptance(path: Path | None, module: Any, label: str) -> dict[str, Any]:
    """One explicit acceptance receipt, verified by ITS OWN module.

    No stem glob, no `latest`, no newest-wins. The obsolete
    `held_out_pass_receipt` searched `sfi2-native-provenance--*.json` for a
    body declaring `split == "held_out"` and `verdict == "PASS"` -- a search that
    could never succeed, because SFI2 is frozen, FAIL, spent and permanently
    non-rescorable. Replacing one ambiguous stem lookup with another would have
    moved the defect rather than closed it, so the caller names the receipt.

    The verification is delegated, never re-implemented here. SFI3's acceptance
    semantics live in `sfi3_acceptance` and the four-link chain's in
    `four_link_acceptance`; a second copy of either in this file would be a
    second acceptance rule that could drift from the one the study was scored
    under.
    """
    if path is None:
        return {
            "passed": False,
            "receipt": None,
            "receipt_sha256": None,
            "why": (
                f"no {label} acceptance receipt was named. GPU authority is one "
                "explicit immutable path and one digest; absence is a hard block, "
                "not a reason to go looking."
            ),
        }
    if not path.is_file():
        return {
            "passed": False,
            "receipt": _safe_rel(path),
            "receipt_sha256": None,
            "why": f"the named {label} acceptance is not on disk",
        }
    try:
        verify_authority = getattr(module, "verify_authority", None)
        body = (
            verify_authority(path)
            if verify_authority is not None
            else module.verify(json.loads(path.read_text(encoding="utf-8")))
        )
    except module.AcceptanceRefused as error:
        return {
            "passed": False,
            "receipt": _safe_rel(path),
            "receipt_sha256": sha_file(path),
            "why": str(error),
        }
    except (json.JSONDecodeError, OSError) as error:
        return {
            "passed": False,
            "receipt": _safe_rel(path),
            "receipt_sha256": None,
            "why": f"the named {label} acceptance could not be read: {error}",
        }
    return {
        "passed": True,
        "receipt": _safe_rel(path),
        "receipt_sha256": sha_file(path),
        "body": body,
    }


def sfi3_acceptance_gate(path: Path | None) -> dict[str, Any]:
    """The fresh held-out SOURCE_FACT_IR study passed. SFI2 cannot answer this."""
    import sfi3_acceptance

    return _read_acceptance(path, sfi3_acceptance, "SFI3")


def four_link_acceptance_gate(
    path: Path | None, *, launch_manifest_sha256: str | None = None
) -> dict[str, Any]:
    """The exact cohort presented to the GPU has a complete four-link chain.

    Separate from the SFI3 gate and never a substitute for it: one says the
    study passed, the other says this cohort is followable. A study can pass
    over a cohort that is not the one about to run.
    """
    import four_link_acceptance

    result = _read_acceptance(path, four_link_acceptance, "four-link")
    if result["passed"] and launch_manifest_sha256 is not None:
        try:
            four_link_acceptance.verify(
                json.loads(Path(path).read_text(encoding="utf-8")),
                launch_manifest_sha256=launch_manifest_sha256,
            )
        except four_link_acceptance.AcceptanceRefused as error:
            return {**result, "passed": False, "why": str(error)}
    return result


# ---------------------------------------------------------------------------
# model / runtime identity — never inferred from a name
# ---------------------------------------------------------------------------


def capability_from_registry(pin: dict[str, Any]) -> dict[str, Any]:
    """Capability comes from pinned registry evidence, or it does not exist.

    A bare repository string is not evidence of what a model can do. This
    function refuses to assert a capability unless the caller supplies a
    pointer to registry evidence distinct from the name itself; without one it
    reports `capability_claimed: False` rather than defaulting to a guess.
    """
    repository = pin.get("repository", "")
    evidence = pin.get("capability_evidence")
    if not evidence or evidence == repository:
        return {
            "repository": repository,
            "capability_claimed": False,
            "reason": (
                "no pinned registry evidence distinct from the model name was "
                "supplied; a name is not a capability and none is inferred from it"
            ),
        }
    evidence_text = evidence if isinstance(evidence, str) else json.dumps(evidence, sort_keys=True)
    digest_match = CAPABILITY_EVIDENCE_DIGEST_PATTERN.search(evidence_text)
    return {
        "repository": repository,
        "capability_claimed": True,
        "capability_evidence": evidence,
        "inferred_from_name": False,
        #: INC-V2-036 class. `inferred_from_name: False` is set on every path
        #: that reaches here, so a gate reading only that field can never be
        #: red -- it re-states, one line later, what the branch above already
        #: decided. This field is the part that can actually be false: a
        #: pointer that merely differs from the repository string ("trust me",
        #: "Qwen3.6 supports vision") is a second assertion, not registry
        #: evidence. `capability_claimed` deliberately keeps its documented
        #: meaning; this is an additional, independently-false property.
        "evidence_is_content_addressed": digest_match is not None,
        "evidence_digest": digest_match.group(0) if digest_match else None,
    }


def capability_not_inferred_from_name(capability: dict[str, Any]) -> bool:
    """G_GSP_CAPABILITY_NOT_INFERRED_FROM_NAME, as a callable predicate.

    Extracted from `run()` deliberately. The vacuous version of this gate lived
    as an inline expression inside `run()`, which refuses to execute under a
    test runner (`live_cohort_guard.refuse_under_test`) -- so no test could
    reach it, and a guard no test can reach is a guard nobody has watched fail.
    """
    if not capability.get("capability_claimed"):
        return True
    return (
        capability.get("inferred_from_name") is False
        and capability.get("evidence_is_content_addressed") is True
    )


def model_identity_pin(pin: dict[str, Any]) -> dict[str, Any]:
    """Everything about model identity this preflight can check without a GPU.

    Digest fields are read from `pin`, never fetched here — this tool must run
    with no network. A caller wiring this into the real study supplies the pin
    from an attestation receipt, the way `run_model_preflight.py` did for the
    closed endpoint.
    """
    repository = pin.get("repository", "")
    revision = pin.get("revision", "")
    tokenizer_sha = pin.get("tokenizer_file_sha256", "")
    capability = capability_from_registry(pin)
    revision_exact = bool(REVISION_PATTERN.fullmatch(revision))
    tokenizer_sha_exact = bool(SHA256_PATTERN.fullmatch(tokenizer_sha))
    pinned = bool(repository and revision_exact and tokenizer_sha_exact)
    return {
        "repository": repository,
        "revision": revision,
        "pinned_by_exact_revision": pinned,
        "revision_is_40_hex": revision_exact,
        "not_resolved_to_latest": revision != "latest",
        "tokenizer_file_sha256": tokenizer_sha,
        "tokenizer_sha_well_formed": tokenizer_sha_exact,
        "capability": capability,
    }


def tokenizer_parity_available(
    sealed_attestation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The frozen probe battery is the one the sealed model pin was resolved on.

    Reused from the closed study rather than rebuilt: the question the battery
    answers — do two tokenizer loads segment text identically — does not
    change with the endpoint. Running the battery against a live tokenizer
    happens on the GPU side of the real study.

    `deterministic` alone was vacuous and is kept only as a reported field.
    `battery_digest()` is a pure function of this module's frozen constants,
    so two calls in one process agree with each other for EVERY possible
    battery -- including one whose probes were deleted. Mutation-proven:
    dropping `long_context_boundary` from `PROBE_CLASSES` left the old gate
    green. The frozen contract therefore has to be compared with something
    outside this process, and the sealed `gpu-successor-pin` receipt already
    records `tokenizer_parity.battery_digest` under bytes that
    `G_GSP_MODEL_PIN_SOURCE_SEALED` verifies. Absence of that attestation is a
    block, not a pass -- there is then nothing the battery is frozen against.
    """
    first = battery_digest()
    second = battery_digest()
    sealed = sealed_attestation if isinstance(sealed_attestation, dict) else {}
    attested_digest = sealed.get("battery_digest")
    attested_classes = sealed.get("probe_classes")
    classes_match = isinstance(attested_classes, list) and list(attested_classes) == list(
        PROBE_CLASSES
    )
    return {
        "battery_digest": first,
        "deterministic": first == second,
        "probe_classes": list(PROBE_CLASSES),
        "attested_battery_digest": attested_digest,
        "attested_probe_classes": list(attested_classes)
        if isinstance(attested_classes, list)
        else None,
        "matches_sealed_attestation": attested_digest is not None
        and attested_digest == first,
        "probe_classes_match_sealed_attestation": classes_match,
        "why": None
        if attested_digest is not None
        else (
            "no sealed model-pin receipt supplied a tokenizer_parity.battery_digest "
            "to compare this battery against. Two calls agreeing with each other is "
            "not a frozen contract."
        ),
    }


def runtime_image_pinnable(image_digest: str) -> dict[str, Any]:
    matches = bool(RUNTIME_IMAGE_DIGEST_PATTERN.match(image_digest))
    return {
        "runtime_image_digest": image_digest,
        "matches_pinned_digest_form": matches,
        "form": "repository@sha256:<64 hex>, never a floating tag",
    }


def materializer_ready() -> dict[str, Any]:
    """The CPU materialization machinery this study would reuse is present.

    Checked by import and attribute presence only — no prompt is built, no
    cohort is read, because none exists yet.
    """
    try:
        import context_builder
    except ImportError as error:
        return {"importable": False, "error": f"{type(error).__name__}: {error}"}
    required = ("fit_to_budget", "prompt_parts", "TOTAL_PROMPT_TOKENS", "schedule")
    present = [name for name in required if hasattr(context_builder, name)]
    return {
        "importable": True,
        "module": context_builder.__name__,
        "required_attributes": list(required),
        "present_attributes": present,
        "ready": present == list(required),
    }


def context_budget_feasible() -> dict[str, Any]:
    """Whether the declared per-item budget leaves room for a typed-fact prompt.

    `ESTIMATED_PROMPT_TOKENS` is a declared allowance for the sources plus the
    frame, not a tokenizer measurement — the real count is only knowable once a
    cohort exists to materialize. This only checks that the declared allowance,
    plus the declared generation length, fits under the same budget the closed
    study used.
    """
    total = ESTIMATED_PROMPT_TOKENS + MAX_NEW_TOKENS
    #: `CONTEXT_BUDGET_TOKENS` is a RESTATEMENT of
    #: `endpoint/context_builder.py`'s `TOTAL_PROMPT_TOKENS`, and the old gate
    #: compared it only with another constant in this same file -- so it was
    #: true for every input and blind to the one thing that could make it
    #: wrong. Mutation-proven: halving the materializer's own budget left the
    #: gate green. The declared value is unchanged; it is now required to still
    #: equal the declaration it claims to copy, and an unimportable materializer
    #: is a block rather than a silent pass.
    materializer_error: str | None = None
    try:
        import context_builder
    except ImportError as error:
        materializer_budget: int | None = None
        materializer_error = f"{type(error).__name__}: {error}"
    else:
        materializer_budget = getattr(context_builder, "TOTAL_PROMPT_TOKENS", None)
    bound = materializer_budget == CONTEXT_BUDGET_TOKENS
    return {
        "estimated_prompt_tokens": ESTIMATED_PROMPT_TOKENS,
        "max_new_tokens": MAX_NEW_TOKENS,
        "estimated_total_tokens": total,
        "context_budget_tokens": CONTEXT_BUDGET_TOKENS,
        "materializer_budget_tokens": materializer_budget,
        "materializer_error": materializer_error,
        "budget_matches_materializer": bound,
        "feasible": ESTIMATED_PROMPT_TOKENS <= CONTEXT_BUDGET_TOKENS and bound,
    }


def no_gpu_and_no_network(source_path: Path | None = None) -> dict[str, Any]:
    """G_GSP_NO_GPU_YET, checked instead of asserted.

    The gate used to be a hardcoded `True` that said so in a comment. Saying so
    is not a control: nothing distinguished this module from the same module
    with an HTTP client bolted on, and INC-V2-104 B leaned on exactly that
    absence -- established once, by hand -- to move the live-cohort guard off
    `run()`. Mutation-proven: adding `import urllib.request` to this file left
    every control in the suite green.

    Read from the module's own AST, so the words `socket` and `HTTP client` in
    the docstring above do not count as imports and the check cannot be red for
    a reason that has nothing to do with what the module does.

    `source_path` is a parameter for one reason: a guard whose only input is
    `__file__` can be exercised in one direction only, and a control that can
    never see it refuse is not a control. Production always passes None.
    """
    source_path = (source_path or Path(__file__)).resolve()
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        return {
            "module": _safe_rel(source_path),
            "parsed": False,
            "clean": False,
            "why": f"the preflight could not read its own source: {error}",
        }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offending = sorted(
        name for name in imported if name.split(".")[0] in FORBIDDEN_RUNTIME_MODULE_ROOTS
    )
    return {
        "module": _safe_rel(source_path),
        "parsed": True,
        "imports_scanned": sorted(imported),
        "forbidden_module_roots": sorted(FORBIDDEN_RUNTIME_MODULE_ROOTS),
        "offending_imports": offending,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "clean": not offending,
        "why": None
        if not offending
        else (
            "this preflight imports a network, provider or GPU-runtime module. It is "
            "declared CPU-only and outcome-independent, and the live-cohort guard sits "
            "on main() rather than run() on the strength of that declaration."
        ),
    }


# ---------------------------------------------------------------------------
# cohort feasibility — check first, and check honestly
# ---------------------------------------------------------------------------


def _invisible_in_unit_text(fact: dict[str, Any]) -> bool:
    """True when the representation is not recoverable by reading the excerpt.

    A crude but honest proxy: the canonical representation, serialized, is not
    a substring of the witness's own excerpt. A fact whose representation
    reproduces the text it was drawn from would be answerable from the text
    alone and does not belong in this cohort — that is exactly the property
    the successor design depends on.
    """
    witness = fact.get("witness") or {}
    excerpt = witness.get("excerpt", "") or ""
    representation = fact.get("representation")
    if representation is None:
        return False
    rep_text = (
        representation
        if isinstance(representation, str)
        else json.dumps(representation, sort_keys=True)
    )
    return bool(rep_text.strip()) and rep_text not in excerpt


def cohort_feasibility(manifest: Path) -> dict[str, Any]:
    """Does a cohort of typed-fact questions exist at the declared floor?

    Checked against a manifest of extracted `SourceFact` records if one
    exists. If none does, the honest answer is zero and infeasible — this
    function never estimates a count from a partial or planned corpus. The
    three closed preflights died precisely because an earlier version of this
    programme was optimistic about a cohort it had not yet counted.
    """
    if not manifest.exists():
        return {
            "manifest": _safe_rel(manifest),
            "manifest_present": False,
            "eligible_count": 0,
            "by_kind": {kind: 0 for kind in ELIGIBLE_KINDS},
            "floor": COHORT_FLOOR,
            "feasible": False,
            "reason": (
                "no cohort manifest exists yet. This is reported as infeasible, "
                "not as unknown, because a floor comparison against a manifest "
                "that does not exist can only ever be honestly zero."
            ),
        }
    body = json.loads(manifest.read_text(encoding="utf-8"))
    facts = body.get("facts", [])
    by_kind: dict[str, int] = {kind: 0 for kind in ELIGIBLE_KINDS}
    eligible_ids: list[str] = []
    for fact in facts:
        if fact.get("kind") not in ELIGIBLE_KINDS:
            continue
        if fact.get("state") != ir.REPRESENTED:
            continue
        if not _invisible_in_unit_text(fact):
            continue
        by_kind[fact["kind"]] += 1
        eligible_ids.append(fact["fact_id"])
    count = len(eligible_ids)
    return {
        "manifest": _safe_rel(manifest),
        "manifest_present": True,
        "manifest_sha256": sha_file(manifest),
        "facts_scanned": len(facts),
        "eligible_count": count,
        "by_kind": by_kind,
        "floor": COHORT_FLOOR,
        "feasible": count >= COHORT_FLOOR,
    }


# ---------------------------------------------------------------------------
# design must not be the closed endpoint
# ---------------------------------------------------------------------------


def design_excludes_closed_endpoint() -> dict[str, Any]:
    """Assert, structurally, that this design cannot select the closed endpoint.

    Not a description of intent — a comparison against the closed endpoint's
    own identifiers and scorer classes, and against the property
    (`REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS`) that made its cohort scarce.
    """
    scorer_overlap = set(SCORER_CLASSES) & set(FORBIDDEN_SCORER_CLASSES)
    return {
        "study_id": STUDY_ID,
        "forbidden_endpoint_id": FORBIDDEN_ENDPOINT_ID,
        "forbidden_stop_record": FORBIDDEN_STOP_RECORD,
        "is_forbidden_endpoint": STUDY_ID == FORBIDDEN_ENDPOINT_ID,
        "scorer_classes": list(SCORER_CLASSES),
        "forbidden_scorer_classes": list(FORBIDDEN_SCORER_CLASSES),
        "scorer_class_overlap": sorted(scorer_overlap),
        "requires_value_transition_between_revisions": (
            REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS
        ),
        "why_this_avoids_the_closed_endpoint": (
            "MODEL_ENDPOINT_V1 needed a value that moved between two revisions "
            "of one lineage; a complete walk of 2,271 lineages found that three "
            "times. This design's eligibility is a property of a single "
            "revision's typed representation, never of a transition between "
            "two, so the scarcity that closed the exact-value endpoint does not "
            "apply to it by construction."
        ),
        "clean": (
            STUDY_ID != FORBIDDEN_ENDPOINT_ID
            and not scorer_overlap
            and not REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS
        ),
    }


# ---------------------------------------------------------------------------
# cost arithmetic
# ---------------------------------------------------------------------------


def estimate_cost(
    *,
    cohort_size: int,
    arms: int = len(ARMS),
    repeats: int = DETERMINISM_REPEATS,
    prompt_tokens: int = ESTIMATED_PROMPT_TOKENS,
    max_new_tokens: int = MAX_NEW_TOKENS,
    tokens_per_second: float = DECLARED_THROUGHPUT_TOKENS_PER_SECOND,
    gpu_hourly_rate_usd: float = DECLARED_GPU_HOURLY_RATE_USD,
    cap_gpu_hours: float = CAP_GPU_HOURS,
    cap_usd: float = CAP_USD,
) -> dict[str, Any]:
    """The declared study parameters, multiplied out, arithmetic shown.

    Every input past `cohort_size` is a declared assumption, not a
    measurement — no GPU second has been spent for this study. The arithmetic
    is deliberately linear and inspectable: total tokens, divided by a
    declared throughput, converted to hours, priced at a declared rate,
    compared against the founder's approved cap.
    """
    tokens_per_item = prompt_tokens + max_new_tokens
    total_calls = cohort_size * arms * repeats
    total_tokens = total_calls * tokens_per_item
    estimated_seconds = total_tokens / tokens_per_second if tokens_per_second else float("inf")
    estimated_gpu_hours = estimated_seconds / 3600.0
    estimated_cost_usd = estimated_gpu_hours * gpu_hourly_rate_usd
    within_hours_cap = estimated_gpu_hours <= cap_gpu_hours
    within_usd_cap = estimated_cost_usd <= cap_usd
    return {
        "inputs": {
            "cohort_size": cohort_size,
            "arms": arms,
            "repeats": repeats,
            "prompt_tokens": prompt_tokens,
            "max_new_tokens": max_new_tokens,
            "declared_assumption": {
                "tokens_per_second": tokens_per_second,
                "gpu_hourly_rate_usd": gpu_hourly_rate_usd,
            },
        },
        "arithmetic": {
            "tokens_per_item": f"{prompt_tokens} + {max_new_tokens} = {tokens_per_item}",
            "total_calls": f"{cohort_size} x {arms} x {repeats} = {total_calls}",
            "total_tokens": f"{total_calls} x {tokens_per_item} = {total_tokens}",
            "estimated_seconds": f"{total_tokens} / {tokens_per_second} = {estimated_seconds:.1f}",
            "estimated_gpu_hours": f"{estimated_seconds:.1f} / 3600 = {estimated_gpu_hours:.4f}",
            "estimated_cost_usd": (
                f"{estimated_gpu_hours:.4f} x {gpu_hourly_rate_usd} = {estimated_cost_usd:.2f}"
            ),
        },
        "estimated_gpu_hours": estimated_gpu_hours,
        "estimated_cost_usd": estimated_cost_usd,
        "cap_gpu_hours": cap_gpu_hours,
        "cap_usd": cap_usd,
        "within_hours_cap": within_hours_cap,
        "within_usd_cap": within_usd_cap,
        "within_cap": within_hours_cap and within_usd_cap,
    }


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def run(
    *,
    manifest: Path,
    model_pin: dict[str, Any],
    runtime_image_digest: str,
    sfi3_acceptance_receipt: Path | None = None,
    four_link_acceptance_receipt: Path | None = None,
    model_pin_path: Path | None = None,
    model_pin_sha256: str | None = None,
    protocol_freeze_receipt: Path | None = None,
    protocol_freeze_sha256: str | None = None,
) -> dict[str, Any]:
    started = now()

    #: Both mandatory, neither substituting for the other. There is no stem
    #: parameter any more: an authority that can be searched for is an authority
    #: that can be found by accident.
    sfi3 = sfi3_acceptance_gate(sfi3_acceptance_receipt)
    four_link = four_link_acceptance_gate(
        four_link_acceptance_receipt,
        launch_manifest_sha256=sha_file(manifest) if manifest.is_file() else None,
    )
    model_pin_source = load_model_pin_artifact(model_pin_path, model_pin_sha256)
    effective_model_pin = (
        model_pin_source["resolved_pin"] if model_pin_source["passed"] else model_pin
    )
    identity = model_identity_pin(effective_model_pin)
    protocol_freeze = gpu_protocol_freeze.verify_freeze(
        protocol_freeze_receipt,
        protocol_freeze_sha256,
        study_path=STUDY_PROTOCOL,
        runtime_path=RUNTIME_PROTOCOL,
    )
    parity = tokenizer_parity_available(
        model_pin_source.get("tokenizer_parity_attestation")
        if model_pin_source["passed"]
        else None
    )
    image = runtime_image_pinnable(runtime_image_digest)
    materializer = materializer_ready()
    budget = context_budget_feasible()
    cohort = cohort_feasibility(manifest)
    exclusion = design_excludes_closed_endpoint()
    no_spend = no_gpu_and_no_network()
    cost = estimate_cost(cohort_size=max(cohort["floor"], cohort["eligible_count"]))

    gates: dict[str, dict[str, Any]] = {
        "G_GSP_SFI3_ACCEPTANCE_PASS": {
            "passed": sfi3["passed"],
            "detail": sfi3,
            "rule": (
                "GPU inference is not permitted until the fresh held-out "
                "SOURCE_FACT_IR_HELDOUT_V3 study PASSES, proven by an explicit "
                "SOURCE_FACT_IR_HELDOUT_ACCEPTANCE_V1 receipt named by path and "
                "digest. SFI2 is frozen, FAIL and spent, and can never satisfy "
                "this. Absence is a hard block."
            ),
        },
        "G_GSP_FOUR_LINK_ACCEPTANCE_PASS": {
            "passed": four_link["passed"],
            "detail": four_link,
            "rule": (
                "the exact cohort presented to the GPU must carry a complete "
                "four-link chain and clear its floor, proven by an explicit "
                "FOUR_LINK_ACCEPTANCE_V1 receipt. Mandatory, and never a "
                "substitute for the SFI3 acceptance: one says the study passed, "
                "the other says this cohort is followable."
            ),
        },
        "G_GSP_PROTOCOL_BUNDLE_FROZEN": {
            "passed": protocol_freeze["passed"],
            "detail": protocol_freeze,
            "rule": (
                "the GPU study and runtime declarations must both be bound by one "
                "explicit immutable bundle-freeze receipt, named by exact path and "
                "file SHA-256, and both declarations must still match it byte for byte"
            ),
        },
        "G_GSP_MODEL_PIN_SOURCE_SEALED": {
            "passed": model_pin_source["passed"],
            "detail": {
                key: value
                for key, value in model_pin_source.items()
                if key not in {"resolved_pin", "tokenizer_parity_attestation"}
            },
            "rule": (
                "the model identity must come from an explicitly named resolver "
                "receipt or flat sealed export whose exact file SHA-256 the caller supplied"
            ),
        },
        "G_GSP_MODEL_PINNED": {
            "passed": identity["pinned_by_exact_revision"],
            "detail": identity,
        },
        "G_GSP_CAPABILITY_NOT_INFERRED_FROM_NAME": {
            "passed": capability_not_inferred_from_name(identity["capability"]),
            "detail": identity["capability"],
            "rule": (
                "a claimed capability must be grounded in content-addressed "
                "registry evidence -- a pointer carrying the 64-hex digest of the "
                "artifact the capability was read out of. A pointer that merely "
                "differs from the repository string is a second assertion about "
                "the model, not evidence about it. No claim is the other legal "
                "state; an ungrounded claim is not."
            ),
        },
        "G_GSP_TOKENIZER_PARITY_BATTERY_AVAILABLE": {
            "passed": parity["deterministic"]
            and parity["matches_sealed_attestation"]
            and parity["probe_classes_match_sealed_attestation"],
            "detail": parity,
            "rule": (
                "the frozen tokenizer probe battery must still hash to the digest "
                "the sealed model-pin receipt was resolved on, and must still carry "
                "the same probe classes. Two calls in one process agreeing with each "
                "other proves only that a pure function is pure."
            ),
        },
        "G_GSP_RUNTIME_IMAGE_PINNABLE": {
            "passed": image["matches_pinned_digest_form"],
            "detail": image,
        },
        "G_GSP_MATERIALIZER_READY": {
            "passed": materializer.get("ready", False),
            "detail": materializer,
        },
        "G_GSP_CONTEXT_BUDGET_FEASIBLE": {
            "passed": budget["feasible"],
            "detail": budget,
        },
        "G_GSP_COHORT_FEASIBILITY": {
            "passed": cohort["feasible"],
            "detail": cohort,
        },
        "G_GSP_EXCLUDES_CLOSED_ENDPOINT": {
            "passed": exclusion["clean"],
            "detail": exclusion,
        },
        "G_GSP_COST_WITHIN_CAP": {
            "passed": cost["within_cap"],
            "detail": cost,
        },
        "G_GSP_NO_GPU_YET": {
            "passed": no_spend["clean"],
            "detail": no_spend,
            "gpu_seconds": 0,
            "estimated_cost_usd": 0.0,
            "rule": (
                "this preflight is CPU-only and outcome-independent. Checked against "
                "the module's own AST rather than asserted: a hardcoded True cannot "
                "tell a preflight that spends nothing from one that has grown an HTTP "
                "client, and INC-V2-104 B rests on that absence."
            ),
        },
    }

    verdict = "READY_TO_AUTHORIZE" if all(gate["passed"] for gate in gates.values()) else "BLOCKED"
    blocking = sorted(name for name, gate in gates.items() if not gate["passed"])

    return {
        "schema": "tavonel.v2.gpu_successor_preflight.v1",
        "study_id": STUDY_ID,
        "started_at": started,
        "ended_at": now(),
        "split": "development",
        "supersedes": None,
        #: What this preflight was reading when it decided. Recorded so the
        #: launcher can refuse to spend against a study or runtime declaration
        #: that moved after the gates passed: without these two digests the
        #: launcher's only link to the preflight is "a receipt exists", which
        #: says nothing about whether the rules are still the rules.
        "declarations": declaration_digests(
            manifest=manifest,
            model_pin=model_pin_path,
            sfi3_acceptance=sfi3_acceptance_receipt,
            four_link_acceptance=four_link_acceptance_receipt,
        ),
        "protocol_bundle_freeze": {
            "path": _safe_rel(protocol_freeze_receipt)
            if protocol_freeze_receipt is not None
            else None,
            "expected_file_sha256": _normalise_expected_sha(protocol_freeze_sha256),
        },
        "closed_endpoint": {
            "protocol": FORBIDDEN_ENDPOINT_ID,
            "stop_record": FORBIDDEN_STOP_RECORD,
        },
        "design": {
            "eligible_kinds": list(ELIGIBLE_KINDS),
            "arms": list(ARMS),
            "determinism_repeats": DETERMINISM_REPEATS,
            "cohort_floor": COHORT_FLOOR,
            "context_budget_tokens": CONTEXT_BUDGET_TOKENS,
        },
        "budget": {"gpu_hours": CAP_GPU_HOURS, "hard_spend_cap_usd": CAP_USD},
        "gates": gates,
        "blocking_gates": blocking,
        "verdict": verdict,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "authorisation_note": (
            "the founder authorised, in advance, that on a fresh held-out PASS "
            "the successor study may run without a further founder wait, under "
            "<=6 GPU hours and <=$40. This receipt is not that authorisation; it "
            "is what the authorisation is conditional on, and it has not run any "
            "model."
        ),
    }


def default_model_pin() -> dict[str, Any]:
    """No live attestation is fetched here — this tool runs with no network.

    A caller wiring this into the real study should pass the pin read from an
    attestation receipt, as `run_model_preflight.verify_model_identity` did
    for the closed endpoint. Left unset, the pin is honestly incomplete and
    `G_GSP_MODEL_PINNED` fails rather than assuming a value.
    """
    return {}


def main() -> int:
    # INC-V2-100, corrected by INC-V2-104. The guard used to sit on `run()`,
    # where it protected against nothing: `run()` opens no socket, imports no
    # HTTP client and no provider backend, and writes nothing -- it reads local
    # files and returns a dict. Its only effect was to redden two controls that
    # existed to prove the real tool blocks, and to make the gate-assembly block
    # unreachable from any test, which is how a gate that was true for every
    # input survived review (INC-V2-104 A).
    #
    # `main()` is where the harm actually is: it seals an immutable receipt and
    # moves a `receipts/latest` pointer. A stray call from a test runner would
    # write real evidence. So the guard moves to the function that causes the
    # thing it names, and `sys.modules` stays in this module's text where the
    # anti-blocker audit can see it.
    if "pytest" in sys.modules or "unittest" in sys.modules:
        live_cohort_guard.refuse_under_test("gpu_successor_preflight.main")
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
        help=(
            "an immutable gpu-successor-pin resolver receipt (resolved_pin is read "
            "from inside it) or a flat sealed JSON export"
        ),
    )
    parser.add_argument(
        "--model-pin-sha256",
        default=None,
        help="expected file SHA-256 for --model-pin; mandatory when --model-pin is named",
    )
    parser.add_argument(
        "--runtime-image-digest",
        default="runpod/pytorch@sha256:0a360022e8de4375af99430f84e8b38951acc397252163a37ceac7204d01be35",
    )
    parser.add_argument(
        "--sfi3-acceptance",
        type=Path,
        default=None,
        help="explicit SOURCE_FACT_IR_HELDOUT_ACCEPTANCE_V1 receipt; no default, no search",
    )
    parser.add_argument(
        "--four-link-acceptance",
        type=Path,
        default=None,
        help="explicit FOUR_LINK_ACCEPTANCE_V1 receipt for the cohort about to run",
    )
    parser.add_argument(
        "--protocol-freeze",
        type=Path,
        default=None,
        help="exact immutable GPU study/runtime bundle-freeze receipt",
    )
    parser.add_argument(
        "--protocol-freeze-sha256",
        default=None,
        help="expected file SHA-256 for --protocol-freeze; mandatory with the path",
    )
    args = parser.parse_args()

    body = run(
        manifest=args.manifest,
        model_pin=default_model_pin(),
        runtime_image_digest=args.runtime_image_digest,
        sfi3_acceptance_receipt=args.sfi3_acceptance,
        four_link_acceptance_receipt=args.four_link_acceptance,
        model_pin_path=args.model_pin,
        model_pin_sha256=args.model_pin_sha256,
        protocol_freeze_receipt=args.protocol_freeze,
        protocol_freeze_sha256=args.protocol_freeze_sha256,
    )
    written = write_immutable(
        "gpu-successor-preflight",
        body,
        tool=Path(__file__).resolve(),
        protocol=None,
    )
    summary = {**written, "verdict": body["verdict"], "blocking_gates": body["blocking_gates"]}
    print(json.dumps(summary, indent=2))
    return 0 if body["verdict"] == "READY_TO_AUTHORIZE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
