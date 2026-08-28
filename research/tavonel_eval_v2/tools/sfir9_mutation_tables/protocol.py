"""Mutations for the declared quantities the freeze hashes.

Each entry is one specific weakening, written by hand: what it changes,
and the text it replaces. Lifted verbatim from the driver that first ran
them, so the committed table is the table that produced the recorded
result.
"""

from __future__ import annotations

TARGET = 'tools/sfir9_protocol.py'

TESTS = ['tests/test_sfir9_protocol.py']

MUTATIONS = [
    ("P1 the capacity floor is lowered to what SFIR7 reached",
     "MINIMUM_C = 750", "MINIMUM_C = 459"),
    ("P2 the quota floor is lowered",
     "MINIMUM_Q = 600", "MINIMUM_Q = 300"),
    ("P3 the quota fraction is widened",
     "QUOTA_FRACTION_NUMERATOR = 8", "QUOTA_FRACTION_NUMERATOR = 9"),
    ("P4 the quota cap is raised",
     "MAXIMUM_Q = 1000", "MAXIMUM_Q = 2000"),
    ("P5 the quota rounds instead of flooring",
     "        count * QUOTA_FRACTION_NUMERATOR // QUOTA_FRACTION_DENOMINATOR,",
     "        round(count * QUOTA_FRACTION_NUMERATOR / QUOTA_FRACTION_DENOMINATOR),"),
    ("P6 the criterion checks only the count",
     "    return count >= MINIMUM_C and quota_for(count) >= MINIMUM_Q",
     "    return count >= MINIMUM_C"),
    ("P7 the criterion checks only the quota",
     "    return count >= MINIMUM_C and quota_for(count) >= MINIMUM_Q",
     "    return quota_for(count) >= MINIMUM_Q"),
    ("P8 the retry fail-safe is widened",
     "RETRY_WAIT_SECONDS = 60", "RETRY_WAIT_SECONDS = 300"),
    ("P9 the total fail-safe is widened",
     "TOTAL_WAIT_SECONDS = 180", "TOTAL_WAIT_SECONDS = 900"),
    ("P10 a population-calibrated frontier bound comes back",
     '                "population_calibrated_bounds": [],',
     '                "population_calibrated_bounds": [158, 256],'),
    ("P11 freezing changes what the protocol says",
     "        return (\n            \"sha256:\"\n            + hashlib.sha256(\n                json.dumps(self.terms(), sort_keys=True, separators=(\",\", \":\")).encode(",
     "        return (\n            \"sha256:\"\n            + hashlib.sha256(\n                json.dumps(self.as_dict_unstable(), sort_keys=True, separators=(\",\", \":\")).encode("),
    ("P12 a draft is treated as frozen",
     "        if not self.is_frozen():", "        if False:"),
    ("P13 freeze() reports frozen without recording it",
     "        return self.freeze_state == FROZEN", "        return True"),
    ("P14 freeze() is a no-op",
     "        return Protocol(freeze_state=FROZEN)", "        return self"),
    ("P15 the salt reaches the published receipt",
     '            "salt_digest": salt_digest(),', '            "salt_digest": SELECTION_SALT,'),
    ("P16 the salt digest ignores the salt",
     '    return "sha256:" + hashlib.sha256(SELECTION_SALT.encode("utf-8")).hexdigest()',
     '    return "sha256:" + hashlib.sha256(b"").hexdigest()'),
    ("P17 the execution envelope escapes the digest",
     '            "execution_envelope": {', '            "_execution_envelope": {'),
    ("P18 the selection terms escape the digest",
     '            "selection": {', '            "_selection": {'),
    ("P19 the traversal terms escape the digest",
     '            "traversal": {', '            "_traversal": {'),
    ("P20 the partition is keyed on the address, so a rename moves it",
     '                "partition_keyed_on": "host_uuid",',
     '                "partition_keyed_on": "name_with_owner",'),
    ("P21 the partition collapses to a single bucket",
     "PARTITION_COUNT = 64", "PARTITION_COUNT = 1"),
    ("P22 the budget is denominated in logical requests again",
     '                "denominated_in": "provider_charge",',
     '                "denominated_in": "logical_requests",'),
    ("P23 a rate window ends the study rather than the segment",
     '                "on_a_reset_beyond_the_fail_safe": "SEGMENT_COMPLETE_RATE_WINDOW",',
     '                "on_a_reset_beyond_the_fail_safe": "STUDY_ABORT",'),
    ("P24 the study reuses a spent protocol id",
     'PROTOCOL_ID = "SOURCE_FACT_IR_FRESH_HELDOUT_V9"',
     'PROTOCOL_ID = "SOURCE_FACT_IR_FRESH_HELDOUT_V7"'),
    ("P25 the study declares itself exploratory",
     'STUDY_KIND = "FRESH_HELDOUT_CONFIRMATORY"', 'STUDY_KIND = "EXPLORATORY"'),
    ("P26 the working storage budget silently shrinks",
     "DECLARED_WORKING_STORAGE_BYTES = 2 * 1024 * 1024 * 1024",
     "DECLARED_WORKING_STORAGE_BYTES = 2 * 1024 * 1024"),
]
