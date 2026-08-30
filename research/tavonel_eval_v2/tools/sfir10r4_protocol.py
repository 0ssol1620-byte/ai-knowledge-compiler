#!/usr/bin/env python3
"""SFIR10R4 prospective protocol: rollover-safe conservative accounting.

R3 correctly separated scientific capacity from exact shared-provider cost,
but it still treated a normal GitHub primary-rate window rollover as
MEASUREMENT_UNPROVEN.  GitHub documents ``x-ratelimit-reset`` as the UTC epoch
at which the current primary window resets, so a long traversal can cross that
boundary without any loss of source identity or response authenticity.

R4 keeps every R3 scientific threshold and conservative accounting rule, but
turns a reset-epoch change into a *segment boundary*.  The first response seen
under the new epoch is never consumed as scientific data: its body is not
parsed, its tree is not expanded, and it is not credited to candidate yield or
the old window's minimum-attributable charge count.  The active frontier entry
is released and the logical request is replayed only after a fresh segment
preflight under the new provider window.  Because the boundary request cannot
be assigned cleanly to the old window, exact provider-cost publication is
withheld for that segment; capacity evidence remains valid.

All scientific thresholds, candidate rules, storage/root envelopes, selection
salt, and the 64-way partition scheme are inherited unchanged.  R3 partition 3
is spent because cohort contact occurred; R4 mechanically opens partition 4.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sfir10r3_protocol as predecessor

PROTOCOL_ID = "SOURCE_FACT_IR_FRESH_HELDOUT_V10R3"
SCHEMA = "tavonel.sfir10r4.protocol.v1"
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

# Selection mechanically advances from spent R3 partition 3 with no new salt.
SELECTION_SALT = predecessor.SELECTION_SALT
PARTITION_COUNT = predecessor.PARTITION_COUNT
PREDECESSOR_PARTITION_INDEX = predecessor.PARTITION_INDEX
PARTITION_INDEX = (PREDECESSOR_PARTITION_INDEX + 1) % PARTITION_COUNT

# Frozen segment-boundary/accounting control flow.
RATE_LIMIT_ENDPOINT = "https://api.github.com/rate_limit"
ACCOUNTING_PREFLIGHT_ENDPOINT = "https://api.github.com/repos/octocat/Hello-World"
ACCOUNTING_PREFLIGHT_REQUESTS = 10
ACCOUNTING_PREFLIGHT_REQUIRE_REQUEST_ID = True
ACCOUNTING_PREFLIGHT_REQUIRE_UNIQUE_REQUEST_IDS = True
ACCOUNTING_PREFLIGHT_MIN_DELTA_EACH_RESPONSE = 1
ACCOUNTING_PREFLIGHT_WAIT_SECONDS = 0
ACCOUNTING_PREFLIGHT_FAILURE_POLICY = "SEGMENT_NOT_STARTED_RETRY_ALLOWED"
SEGMENT_START_OBSERVATIONS = 1
POLL_DURING_SEGMENT = False
WAIT_INSIDE_SEGMENT = False

# Cohort accounting.
MINIMUM_ATTRIBUTABLE_CHARGE_PER_NETWORK_HOP = 1
REQUIRE_PROVIDER_REQUEST_ID = True
REQUIRE_RATE_REMAINING_HEADER = True
REQUIRE_RATE_RESET_HEADER = True
RATE_LIMIT_HTTP_STATUSES = (403, 429)
MID_SEGMENT_WINDOW_RESET_POLICY = "CLOSE_SEGMENT_DISCARD_BOUNDARY_RESPONSE_REPLAY_NEXT_WINDOW"
ROLLOVER_BOUNDARY_RESPONSE_POLICY = "NEVER_CONSUME_AS_SCIENTIFIC_DATA"
ROLLOVER_PROVIDER_COST_POLICY = "WITHHOLD_EXACT_COST_FOR_BOUNDARY_SEGMENT"
SECONDARY_LIMIT_WITH_RETRY_AFTER_POLICY = "CLOSE_SEGMENT_RETRY_NOT_BEFORE_HEADER_DELAY"
SECONDARY_LIMIT_WITHOUT_RETRY_AFTER_POLICY = "CLOSE_SEGMENT_RETRY_NOT_BEFORE_60_SECONDS"
SECONDARY_LIMIT_MINIMUM_WAIT_SECONDS = 60
ZERO_OR_NEGATIVE_PROVIDER_DELTA_POLICY = "MEASUREMENT_UNPROVEN_STOP"
UNATTRIBUTED_EXTRA_POLICY = "RECORD_AS_EXTERNAL_INTERFERENCE_NEVER_CREDIT_TO_YIELD"
PROVIDER_COST_CLAIM_POLICY = "WITHHOLD_UNLESS_ZERO_UNATTRIBUTED_EXTRA"
CAPACITY_CLAIM_DEPENDS_ON_EXACT_PROVIDER_COST = False
MAX_HOPS_PER_LOGICAL_REQUEST = 4
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
                "inherited_unchanged_from": "SFIR10R3",
            },
            "execution_envelope": {
                "permitted_rate_windows": PERMITTED_RATE_WINDOWS,
                "usable_minimum_attributable_charges_per_window": USABLE_CHARGE_PER_WINDOW,
                "per_root_cumulative_minimum_attributable_charge_allowance": (
                    PER_ROOT_CHARGE_ALLOWANCE
                ),
                "declared_working_storage_bytes_per_root": DECLARED_WORKING_STORAGE_BYTES,
                "candidate_extensions": list(CANDIDATE_EXTENSIONS),
                "n": derive_n(),
                "require_full_roster_before_census": REQUIRE_FULL_ROSTER,
                "n_formula": "(windows * usable_charges_per_window) // per_root_charge_allowance",
                "inherited_unchanged_from": "SFIR10R3",
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
                    "changing the salt after R3 contacted partition three would add a post-outcome "
                    "selection degree of freedom; the predecessor salt is inherited unchanged"
                ),
            },
            "rate_window_execution": {
                "segment_start_endpoint": RATE_LIMIT_ENDPOINT,
                "segment_start_observations": SEGMENT_START_OBSERVATIONS,
                "poll_during_segment": POLL_DURING_SEGMENT,
                "wait_inside_segment": WAIT_INSIDE_SEGMENT,
                "accounting_sanity_preflight": {
                    "endpoint": ACCOUNTING_PREFLIGHT_ENDPOINT,
                    "requests": ACCOUNTING_PREFLIGHT_REQUESTS,
                    "require_request_id": ACCOUNTING_PREFLIGHT_REQUIRE_REQUEST_ID,
                    "require_unique_request_ids": ACCOUNTING_PREFLIGHT_REQUIRE_UNIQUE_REQUEST_IDS,
                    "minimum_delta_each_response": ACCOUNTING_PREFLIGHT_MIN_DELTA_EACH_RESPONSE,
                    "wait_seconds": ACCOUNTING_PREFLIGHT_WAIT_SECONDS,
                    "failure_policy": ACCOUNTING_PREFLIGHT_FAILURE_POLICY,
                    "cohort_contact_before_success": False,
                    "scientific_data_consumed": False,
                    "external_extra_permitted": True,
                    "purpose": (
                        "prove headers/reset/request-id/monotone accounting work before cohort; "
                        "do not claim credential exclusivity"
                    ),
                },
                "segment_start_requires_remaining_after_preflight_at_least": (
                    USABLE_CHARGE_PER_WINDOW
                ),
                "observe_every_response": [
                    "x-ratelimit-remaining",
                    "x-ratelimit-reset",
                    "x-github-request-id",
                    "retry-after",
                ],
                "minimum_attributable_charge_per_network_hop": (
                    MINIMUM_ATTRIBUTABLE_CHARGE_PER_NETWORK_HOP
                ),
                "require_provider_request_id": REQUIRE_PROVIDER_REQUEST_ID,
                "require_remaining_header": REQUIRE_RATE_REMAINING_HEADER,
                "require_reset_header": REQUIRE_RATE_RESET_HEADER,
                "rate_limit_http_statuses": list(RATE_LIMIT_HTTP_STATUSES),
                "request_reservation_minimum_attributable_charges": REQUEST_RESERVATION_CHARGES,
                "close_before_request_when_minimum_attributable_reservation_would_exceed": (
                    USABLE_CHARGE_PER_WINDOW
                ),
                "stop_root_before_request_when_minimum_attributable_reservation_would_exceed": (
                    PER_ROOT_CHARGE_ALLOWANCE
                ),
                "mid_segment_window_reset_policy": MID_SEGMENT_WINDOW_RESET_POLICY,
                "rollover_boundary_response_policy": ROLLOVER_BOUNDARY_RESPONSE_POLICY,
                "rollover_provider_cost_policy": ROLLOVER_PROVIDER_COST_POLICY,
                "rollover_replay_rule": (
                    "release the active frontier entry and replay the logical request only after "
                    "a fresh segment preflight under the new reset epoch"
                ),
                "secondary_limit_with_retry_after_policy": (
                    SECONDARY_LIMIT_WITH_RETRY_AFTER_POLICY
                ),
                "secondary_limit_without_retry_after_policy": (
                    SECONDARY_LIMIT_WITHOUT_RETRY_AFTER_POLICY
                ),
                "secondary_limit_minimum_wait_seconds": SECONDARY_LIMIT_MINIMUM_WAIT_SECONDS,
                "zero_or_negative_provider_delta_policy": ZERO_OR_NEGATIVE_PROVIDER_DELTA_POLICY,
                "unattributed_extra_policy": UNATTRIBUTED_EXTRA_POLICY,
                "provider_cost_claim_policy": PROVIDER_COST_CLAIM_POLICY,
                "capacity_claim_depends_on_exact_provider_cost": (
                    CAPACITY_CLAIM_DEPENDS_ON_EXACT_PROVIDER_COST
                ),
                "why_interference_cannot_inflate_capacity": (
                    "candidate evidence comes only from authenticated response bodies and pinned "
                    "revision traversal; external provider-counter decrements add no candidates "
                    "and can only consume remaining quota sooner"
                ),
            },
            "result_visibility": {
                "partial_c_forbidden": True,
                "partial_q_forbidden": True,
                "per_root_candidate_yield_progress_forbidden": True,
                "score_only_after_census_seal": True,
                "provider_cost_claim_separate_from_capacity_claim": True,
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
