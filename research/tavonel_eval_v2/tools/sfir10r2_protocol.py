#!/usr/bin/env python3
"""SFIR10R2 prospective protocol: isolate provider-accounting authority.

SFIR10R1 opened partition one, froze a fifty-root roster, and then terminated
``MEASUREMENT_UNPROVEN`` before sealing any census window because one cohort
response observed a provider remaining-counter delta of two. The frozen R1
instrument correctly refused to attribute that decrement to a single request.
Post-terminal diagnostics on one fixed non-cohort public repository then
produced nine consecutive unit decrements with request identifiers, so R2 treats
that event as an execution-authority problem rather than changing the
scientific criterion.

R2 inherits every scientific threshold, storage/root envelope, candidate
extension, selection salt, and 64-way partition rule unchanged. Because
partition one is spent, R2 mechanically selects partition two. The sole new
authority is a frozen per-segment exclusivity preflight: before any cohort root
is contacted, exactly ten authenticated GETs are sent to one fixed public
non-cohort endpoint. Every response must stay in one reset epoch, expose a
request id, and decrement the provider counter by exactly one; an uncharged
``/rate_limit`` reconciliation must then prove exactly ten charges. Only after
that preflight and a remaining balance of at least 4,500 may the cohort segment
start. Preflight failure sends no cohort request and is retryable. Once cohort
contact begins, R1's fail-closed unattributed-delta policy remains unchanged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sfir10r1_protocol as predecessor

PROTOCOL_ID = "SOURCE_FACT_IR_FRESH_HELDOUT_V10R2"
SCHEMA = "tavonel.sfir10r2.protocol.v1"
STUDY_KIND = "FRESH_HELDOUT_CONFIRMATORY_SUCCESSOR"
PREDECESSOR_TERMINAL_STUDY = predecessor.PROTOCOL_ID
PREDECESSOR_PRECOHORT_INSTRUMENT = predecessor.PROTOCOL_ID

# Scientific criterion and execution envelope are inherited unchanged.
MINIMUM_C = predecessor.MINIMUM_C
MAXIMUM_Q = predecessor.MAXIMUM_Q
QUOTA_FRACTION_NUMERATOR = predecessor.QUOTA_FRACTION_NUMERATOR
QUOTA_FRACTION_DENOMINATOR = predecessor.QUOTA_FRACTION_DENOMINATOR
MINIMUM_Q = predecessor.MINIMUM_Q
PERMITTED_RATE_WINDOWS = predecessor.PERMITTED_RATE_WINDOWS
USABLE_CHARGE_PER_WINDOW = predecessor.USABLE_CHARGE_PER_WINDOW
PER_ROOT_CHARGE_ALLOWANCE = predecessor.PER_ROOT_CHARGE_ALLOWANCE
DECLARED_WORKING_STORAGE_BYTES = predecessor.DECLARED_WORKING_STORAGE_BYTES
CANDIDATE_EXTENSIONS = predecessor.CANDIDATE_EXTENSIONS

# Selection uses the same salt and mechanically advances from spent R1 partition 1.
SELECTION_SALT = predecessor.SELECTION_SALT
PARTITION_COUNT = predecessor.PARTITION_COUNT
PREDECESSOR_PARTITION_INDEX = predecessor.PARTITION_INDEX
PARTITION_INDEX = (PREDECESSOR_PARTITION_INDEX + 1) % PARTITION_COUNT

# Frozen segment-start and exclusivity control flow.
RATE_LIMIT_ENDPOINT = "https://api.github.com/rate_limit"
SEGMENT_START_OBSERVATIONS = 1
POLL_DURING_SEGMENT = False
WAIT_INSIDE_SEGMENT = False
EXCLUSIVITY_PREFLIGHT_ENDPOINT = "https://api.github.com/repos/octocat/Hello-World"
EXCLUSIVITY_PREFLIGHT_REQUESTS = 10
EXCLUSIVITY_PREFLIGHT_REQUIRE_REQUEST_ID = True
EXCLUSIVITY_PREFLIGHT_REQUIRE_UNIQUE_REQUEST_IDS = True
EXCLUSIVITY_PREFLIGHT_REQUIRE_UNIT_DELTA = True
EXCLUSIVITY_PREFLIGHT_RECONCILE_EXACT_CHARGES = 10
EXCLUSIVITY_PREFLIGHT_WAIT_SECONDS = 0
EXCLUSIVITY_PREFLIGHT_FAILURE_POLICY = "SEGMENT_NOT_STARTED_RETRY_ALLOWED"

MAX_HOPS_PER_LOGICAL_REQUEST = 4
REQUIRE_RATE_REMAINING_HEADER = True
REQUIRE_RATE_RESET_HEADER = True
RATE_LIMIT_HTTP_STATUSES = (403, 429)
MID_SEGMENT_WINDOW_RESET_POLICY = "MEASUREMENT_UNPROVEN_STOP"
UNATTRIBUTED_PROVIDER_DELTA_POLICY = "MEASUREMENT_UNPROVEN_STOP"
REQUEST_RESERVATION_CHARGES = MAX_HOPS_PER_LOGICAL_REQUEST
REQUIRE_FULL_ROSTER = True
ROOT_SNAPSHOT_POLICY = "PIN_ON_FIRST_SUCCESSFUL_SEED_NEVER_RESEED"
RESUME_IDENTITY_FAILURE_POLICY = "STOPPED_BEFORE_EXHAUSTION"
ALL_REFUSED_POLICY = "MEASURED_NOT_SEALABLE"

DRAFT = "PROTOCOL_DRAFT"
FROZEN = "PROTOCOL_FROZEN"


class ProtocolRefused(RuntimeError):
    pass


def quota_for(count: int) -> int:
    return min(MAXIMUM_Q, count * QUOTA_FRACTION_NUMERATOR // QUOTA_FRACTION_DENOMINATOR)


def meets_criterion(count: int) -> bool:
    return count >= MINIMUM_C and quota_for(count) >= MINIMUM_Q


def derive_n() -> int:
    return (PERMITTED_RATE_WINDOWS * USABLE_CHARGE_PER_WINDOW) // PER_ROOT_CHARGE_ALLOWANCE


def salt_digest() -> str:
    return "sha256:" + hashlib.sha256(SELECTION_SALT.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Protocol:
    freeze_state: str = DRAFT

    def terms(self) -> dict[str, Any]:
        return {
            "protocol_id": PROTOCOL_ID,
            "schema": SCHEMA,
            "study_kind": STUDY_KIND,
            "predecessor_terminal_study": PREDECESSOR_TERMINAL_STUDY,
            "predecessor_precohort_instrument": PREDECESSOR_PRECOHORT_INSTRUMENT,
            "criterion": {
                "minimum_c": MINIMUM_C,
                "maximum_q": MAXIMUM_Q,
                "quota_fraction": [QUOTA_FRACTION_NUMERATOR, QUOTA_FRACTION_DENOMINATOR],
                "minimum_q": MINIMUM_Q,
                "inherited_unchanged_from": "SFIR10R1",
            },
            "execution_envelope": {
                "permitted_rate_windows": PERMITTED_RATE_WINDOWS,
                "usable_provider_charges_per_window": USABLE_CHARGE_PER_WINDOW,
                "per_root_cumulative_provider_charge_allowance": PER_ROOT_CHARGE_ALLOWANCE,
                "declared_working_storage_bytes_per_root": DECLARED_WORKING_STORAGE_BYTES,
                "candidate_extensions": list(CANDIDATE_EXTENSIONS),
                "n": derive_n(),
                "require_full_roster_before_census": REQUIRE_FULL_ROSTER,
                "n_formula": "(windows * usable_charges_per_window) // per_root_charge_allowance",
                "inherited_unchanged_from": "SFIR10R1",
            },
            "selection": {
                "salt_digest": salt_digest(),
                "partition_count": PARTITION_COUNT,
                "predecessor_partition_index": PREDECESSOR_PARTITION_INDEX,
                "partition_index": PARTITION_INDEX,
                "partition_rule": "(predecessor_partition_index + 1) mod partition_count",
                "partition_key": "host_uuid",
                "ordering": ["source_rank descending", "record_id ascending"],
                "why_no_new_salt": (
                    "choosing a new salt after R1 opened partition one would add a post-outcome "
                    "selection degree of freedom; the predecessor salt is inherited unchanged"
                ),
            },
            "rate_window_execution": {
                "segment_start_endpoint": RATE_LIMIT_ENDPOINT,
                "segment_start_observations": SEGMENT_START_OBSERVATIONS,
                "segment_start_requires_remaining_before_preflight_at_least": (
                    USABLE_CHARGE_PER_WINDOW + EXCLUSIVITY_PREFLIGHT_REQUESTS
                ),
                "segment_start_requires_remaining_after_preflight_at_least": (
                    USABLE_CHARGE_PER_WINDOW
                ),
                "poll_during_segment": POLL_DURING_SEGMENT,
                "wait_inside_segment": WAIT_INSIDE_SEGMENT,
                "exclusive_credential_preflight": {
                    "endpoint": EXCLUSIVITY_PREFLIGHT_ENDPOINT,
                    "requests": EXCLUSIVITY_PREFLIGHT_REQUESTS,
                    "require_request_id": EXCLUSIVITY_PREFLIGHT_REQUIRE_REQUEST_ID,
                    "require_unique_request_ids": EXCLUSIVITY_PREFLIGHT_REQUIRE_UNIQUE_REQUEST_IDS,
                    "require_unit_delta_each_response": EXCLUSIVITY_PREFLIGHT_REQUIRE_UNIT_DELTA,
                    "reconcile_exact_charges": EXCLUSIVITY_PREFLIGHT_RECONCILE_EXACT_CHARGES,
                    "wait_seconds": EXCLUSIVITY_PREFLIGHT_WAIT_SECONDS,
                    "failure_policy": EXCLUSIVITY_PREFLIGHT_FAILURE_POLICY,
                    "cohort_contact_before_success": False,
                    "scientific_data_consumed": False,
                },
                "observe_every_response": [
                    "x-ratelimit-remaining",
                    "x-ratelimit-reset",
                    "retry-after",
                ],
                "require_remaining_header": REQUIRE_RATE_REMAINING_HEADER,
                "require_reset_header": REQUIRE_RATE_RESET_HEADER,
                "rate_limit_http_statuses": list(RATE_LIMIT_HTTP_STATUSES),
                "request_reservation_provider_charges": REQUEST_RESERVATION_CHARGES,
                "close_before_request_when_segment_reservation_would_exceed": (
                    USABLE_CHARGE_PER_WINDOW
                ),
                "stop_root_before_request_when_root_reservation_would_exceed": (
                    PER_ROOT_CHARGE_ALLOWANCE
                ),
                "mid_segment_window_reset_policy": MID_SEGMENT_WINDOW_RESET_POLICY,
                "unattributed_provider_delta_policy": UNATTRIBUTED_PROVIDER_DELTA_POLICY,
                "why_no_wait": (
                    "R2 adds no adaptive polling or waiting: exclusivity is established by one "
                    "fixed ten-request preflight, cohort execution then follows R1 unchanged, and "
                    "exhaustion closes a segment for later durable resume"
                ),
            },
            "result_visibility": {
                "partial_c_forbidden": True,
                "partial_q_forbidden": True,
                "per_root_candidate_yield_progress_forbidden": True,
                "score_only_after_census_seal": True,
            },
            "root_snapshot_and_completion": {
                "snapshot_policy": ROOT_SNAPSHOT_POLICY,
                "record_at_first_seed": [
                    "repository_numeric_id",
                    "canonical_address",
                    "default_branch",
                    "root_commit_sha",
                    "root_tree_sha",
                ],
                "resume_re_attests_numeric_identity": True,
                "resume_never_reseeds_default_branch": True,
                "resume_identity_failure_policy": RESUME_IDENTITY_FAILURE_POLICY,
                "all_refused_policy": ALL_REFUSED_POLICY,
                "census_complete_requires": "zero stopped roots AND at least one counted root",
            },
        }

    def digest(self) -> str:
        raw = json.dumps(self.terms(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    def freeze(self) -> Protocol:
        return Protocol(freeze_state=FROZEN)

    def require_frozen(self, action: str) -> None:
        if self.freeze_state != FROZEN:
            raise ProtocolRefused(f"{action} requires {FROZEN}, got {self.freeze_state}")

    def as_dict(self) -> dict[str, Any]:
        return {**self.terms(), "freeze_state": self.freeze_state, "protocol_digest": self.digest()}
