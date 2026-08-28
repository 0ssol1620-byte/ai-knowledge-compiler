"""Mutations for the capacity criterion and its three-way verdict.

Each entry is one specific weakening, written by hand: what it changes,
and the text it replaces. Lifted verbatim from the driver that first ran
them, so the committed table is the table that produced the recorded
result.
"""

from __future__ import annotations

TARGET = 'tools/sfir9_scorer.py'

TESTS = ['tests/test_sfir9_scorer.py']

MUTATIONS = [
    # -- counted versus reached
    ("S1 a stopped root is treated as measured",
     "        return self.disposition == EXHAUSTED", "        return True"),
    ("S2 a stopped root is dropped from the denominator",
     "        return self.disposition in {EXHAUSTED, STOPPED}",
     "        return self.disposition == EXHAUSTED"),
    ("S3 a refused root enters the denominator",
     "        return self.disposition in {EXHAUSTED, STOPPED}", "        return True"),
    ("S4 an incomplete census reports an exact count",
     "    exact = lower_bound if census_complete else None", "    exact = lower_bound"),
    ("S5 completeness ignores the stopped roots",
     "    census_complete = not stopped and bool(counted)", "    census_complete = bool(counted)"),
    ("S6 an empty census counts as complete",
     "    census_complete = not stopped and bool(counted)", "    census_complete = not stopped"),
    ("S7 a stopped root's candidates are discarded rather than counted as a floor",
     "        for candidate in result.candidates:",
     "        for candidate in (result.candidates if result.measured() else ()):"),

    # -- the verdicts
    ("S8 a lower bound above the threshold does not settle the question",
     "    if criterion_met:", "    if criterion_met and census_complete:"),
    ("S9 an incomplete census below the threshold is reported as a failure",
     "    elif census_complete:\n        verdict = FAIL", "    elif True:\n        verdict = FAIL"),
    ("S10 the not-sealable verdict is collapsed into a pass",
     "        verdict = NOT_SEALABLE", "        verdict = PASS"),
    ("S11 the not-sealable verdict is collapsed into a failure",
     "        verdict = NOT_SEALABLE", "        verdict = FAIL"),
    ("S12 a complete census below the threshold passes",
     "        verdict = FAIL", "        verdict = PASS"),

    # -- the criterion
    ("S13 the criterion is not applied",
     "    criterion_met = protocol_module.meets_criterion(lower_bound)",
     "    criterion_met = True"),
    ("S14 only the count half of the criterion is applied",
     "    criterion_met = protocol_module.meets_criterion(lower_bound)",
     "    criterion_met = lower_bound >= protocol_module.MINIMUM_C"),
    ("S15 the criterion is applied to a padded total",
     "    criterion_met = protocol_module.meets_criterion(lower_bound)",
     "    criterion_met = protocol_module.meets_criterion(lower_bound + len(stopped) * 100)"),
    ("S16 the reported minimum is not the protocol's",
     '            "minimum_c": protocol_module.MINIMUM_C,', '            "minimum_c": 0,'),
    ("S17 the quota is not derived from the lower bound",
     "    quota = protocol_module.quota_for(lower_bound)", "    quota = protocol_module.MAXIMUM_Q"),
    ("S18 the redundancy note is dropped",
     '                "boundary, because 600 / 0.8 is exactly 750. The protocol retains "',
     '                "boundary. The protocol retains "'),

    # -- the pool
    ("S19 every path counts, whatever its extension",
     "            if not eligible(candidate.path):", "            if False:"),
    ("S20 the extension test matches anywhere in the path",
     "    return any(lowered.endswith(suffix) for suffix in protocol_module.CANDIDATE_EXTENSIONS)",
     "    return any(suffix in lowered for suffix in protocol_module.CANDIDATE_EXTENSIONS)"),
    ("S21 the extension test is case sensitive",
     "    lowered = path.lower()", "    lowered = path"),
    ("S22 the pool definition is a local copy",
     "    return any(lowered.endswith(suffix) for suffix in protocol_module.CANDIDATE_EXTENSIONS)",
     '    return any(lowered.endswith(suffix) for suffix in (".py", ".md", ".rst", ".txt"))'),
    ("S23 ineligible paths are not reported",
     "                ineligible += 1", "                pass"),

    # -- deduplication
    ("S24 candidates are counted rather than deduplicated",
     "    lower_bound = len(pool)", "    lower_bound = sum(len(r.candidates) for r in results)"),
    ("S25 deduplication ignores the repository",
     "            pool.add(candidate.key())",
     "            pool.add(candidate.key()[1:])"),
    ("S26 the pool digest depends on arrival order",
     "    return _digest(sorted(list(key) for key in keys))",
     "    return _digest([list(key) for key in keys])"),
    ("S26b the pool digest is not the one the score reports",
     '        "candidate_pool_digest": pool_digest(pool),',
     '        "candidate_pool_digest": "sha256:fixed",'),

    # -- census hygiene
    ("S27 an undeclared disposition is accepted",
     "        if result.disposition not in DISPOSITIONS:", "        if False:"),
    ("S28 a repeated root is accepted",
     "        if host_uuid in seen:", "        if False:"),
    ("S29 a root outside the roster is accepted",
     "        if host_uuid not in roster:", "        if False:"),
    ("S30 a refused root may carry candidates",
     "        if result.disposition == REFUSED and result.candidates:", "        if False:"),
    ("S31 a root may be identified by an address",
     "        host_uuid = identity.normalize_host_uuid(result.host_uuid)",
     "        host_uuid = str(result.host_uuid)"),
    ("S32 the roster size is reported as the census size",
     '            "roster_size": len(roster),', '            "roster_size": len(seen),'),
    ("S33 the score does not name the roster it scored",
     '        "roster_digest": roster_digest,', '        "roster_digest": "",'),
    ("S34 the stopped count is understated",
     '            "roots_stopped_before_exhaustion": len(stopped),',
     '            "roots_stopped_before_exhaustion": 0,'),
]
