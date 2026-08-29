#!/usr/bin/env python3
"""SFIR10R1 prospective protocol: close two pre-cohort V10 defects before selection.

SFIR9 stopped after sealing its roster because constants existed but no frozen
control flow said when rate-window state was observed or when a segment ended.
SFIR10 fixed that *before* selecting another cohort, but its frozen runner was
then found to have one further pre-cohort defect: an all-refused cohort could be
labelled complete. A second suspected defect -- re-seeding a root that had been
seeded but not expanded -- was falsified by a hostile control because the frozen
frontier records `visited` at enqueue time. No V10 roster was ever generated.
R1 fixes the real completeness defect and adds an explicit immutable root
snapshot as extra reproducibility evidence before opening the same still-unseen
partition one. It changes no
capacity threshold and chooses no new salt: the next untouched partition is the
cyclic successor of SFIR9's partition zero under the same 64-way partition.

The important addition is an executable rate-window contract.  A segment reads
GitHub's uncharged ``/rate_limit`` endpoint exactly once before touching a cohort
root, requires a full declared usable window, then reads rate headers on every
response.  There is no polling loop and no in-process waiting.  Exhaustion closes
the segment; a later invocation may resume only from the durable frontier.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sfir9_protocol as predecessor

PROTOCOL_ID = "SOURCE_FACT_IR_FRESH_HELDOUT_V10R1"
SCHEMA = "tavonel.sfir10r1.protocol.v1"
STUDY_KIND = "FRESH_HELDOUT_CONFIRMATORY_SUCCESSOR"
PREDECESSOR_TERMINAL_STUDY = "SOURCE_FACT_IR_FRESH_HELDOUT_V9"
PREDECESSOR_PRECOHORT_INSTRUMENT = "SOURCE_FACT_IR_FRESH_HELDOUT_V10"

# Scientific criterion: inherited unchanged.  The successor exists to repair an
# execution-authority gap, not to make the population easier to pass.
MINIMUM_C = predecessor.MINIMUM_C
MAXIMUM_Q = predecessor.MAXIMUM_Q
QUOTA_FRACTION_NUMERATOR = predecessor.QUOTA_FRACTION_NUMERATOR
QUOTA_FRACTION_DENOMINATOR = predecessor.QUOTA_FRACTION_DENOMINATOR
MINIMUM_Q = predecessor.MINIMUM_Q

# Execution envelope: inherited unchanged and now enforced, not merely used to
# derive N.
PERMITTED_RATE_WINDOWS = predecessor.PERMITTED_RATE_WINDOWS
USABLE_CHARGE_PER_WINDOW = predecessor.USABLE_CHARGE_PER_WINDOW
PER_ROOT_CHARGE_ALLOWANCE = predecessor.PER_ROOT_CHARGE_ALLOWANCE
DECLARED_WORKING_STORAGE_BYTES = predecessor.DECLARED_WORKING_STORAGE_BYTES
CANDIDATE_EXTENSIONS = predecessor.CANDIDATE_EXTENSIONS

# Selection: same secret salt and partition count.  The only new selection term
# is the mechanically determined next partition.  No result from partition zero
# participates in this arithmetic.
SELECTION_SALT = predecessor.SELECTION_SALT
PARTITION_COUNT = predecessor.PARTITION_COUNT
PREDECESSOR_PARTITION_INDEX = predecessor.PARTITION_INDEX
PARTITION_INDEX = (PREDECESSOR_PARTITION_INDEX + 1) % PARTITION_COUNT

# Fully declared rate-window control flow.  These values are not tuned from any
# repository or from the opened SFIR9 roster.
RATE_LIMIT_ENDPOINT = "https://api.github.com/rate_limit"
SEGMENT_START_OBSERVATIONS = 1
POLL_DURING_SEGMENT = False
WAIT_INSIDE_SEGMENT = False
MAX_HOPS_PER_LOGICAL_REQUEST = 4
REQUIRE_RATE_REMAINING_HEADER = True
REQUIRE_RATE_RESET_HEADER = True
RATE_LIMIT_HTTP_STATUSES = (403, 429)
MID_SEGMENT_WINDOW_RESET_POLICY = "MEASUREMENT_UNPROVEN_STOP"
UNATTRIBUTED_PROVIDER_DELTA_POLICY = "MEASUREMENT_UNPROVEN_STOP"

# A request is sent only when the worst possible four-hop logical request fits
# both the current provider window and the current root's cumulative allowance.
# This can leave up to three charges unused; it can never overspend the declared
# envelope merely because a redirect occurred.
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
                "inherited_unchanged_from": "SFIR9",
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
                "inherited_unchanged_from": "SFIR9",
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
                    "choosing a new salt after seeing SFIR9 partition zero would add a "
                    "post-outcome "
                    "selection degree of freedom; the predecessor salt is inherited unchanged"
                ),
            },
            "rate_window_execution": {
                "segment_start_endpoint": RATE_LIMIT_ENDPOINT,
                "segment_start_observations": SEGMENT_START_OBSERVATIONS,
                "segment_start_requires_remaining_at_least": USABLE_CHARGE_PER_WINDOW,
                "poll_during_segment": POLL_DURING_SEGMENT,
                "wait_inside_segment": WAIT_INSIDE_SEGMENT,
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
                    "SFIR9 froze wait constants without freezing an observation schedule. SFIR10 "
                    "removes that degree of freedom: exhaustion closes a segment and resume occurs "
                    "only in a later provider window from durable state"
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
