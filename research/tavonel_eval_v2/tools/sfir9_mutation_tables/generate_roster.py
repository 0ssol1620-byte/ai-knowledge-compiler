"""Mutations for cohort generation.

The step that cannot be rerun, so these attack its refusals, its accounting and
its claim to be inheriting rather than deciding. A generator that quietly
reimplemented one predicate would produce a plausible roster nobody could ever
show was wrong.
"""

from __future__ import annotations

#: Spelled out rather than escaped, so an anchor holding a newline stays legible.
NL = chr(10)

TARGET = 'tools/sfir9_generate_roster.py'

TESTS = ['tests/test_sfir9_generate_roster.py']

MUTATIONS = [
    # --- the once-only refusal
    ("G1 a second roster overwrites the first",
     "    if target.is_file():",
     "    if False:"),
    ("G2 the second roster is written elsewhere instead of refused",
     "    if target.is_file():",
     "    if target.is_file() and False:"),

    # --- both authorities
    ("G3 an absent freeze is skipped",
     "    path = namespace / relative" + NL + "    if not path.is_file():",
     "    path = namespace / relative" + NL + "    if False:"),
    ("G4 a freeze that does not verify is accepted",
     '    if not verdict["verified"]:',
     "    if False:"),
    ("G5 the binding is read instead of re-derived",
     "    rederived = cohort_input.binding(namespace=namespace, repository_root=repository_root)",
     "    rederived = recorded"),
    ("G6 a drifted binding is accepted",
     '    if rederived["binding_digest"] != recorded["binding_digest"]:',
     "    if False:"),
    ("G7 the freeze is verified against nothing",
     "    verdict = freeze_module.verify(freeze)",
     '    verdict = {"verified": True, "problems": []}'),

    # --- eligibility is inherited, not decided here
    ("G8 the predicates are replaced by a locally written one",
     '        for declared in binding["inherited_frame"]["predicates"]',
     '        for declared in [{"field": "host", "op": "eq", "value": "github"}]'),
    ("G9 only the first predicate is applied",
     "        for predicate in predicates:",
     "        for predicate in predicates[:1]:"),
    ("G10 a failing predicate no longer stops the row",
     "                verdict = f\"REJECTED_{predicate.field}_{predicate.op}\"" + NL
     + "                break",
     "                verdict = f\"REJECTED_{predicate.field}_{predicate.op}\""),
    ("G11 the disposition stops naming which predicate rejected the row",
     "                verdict = f\"REJECTED_{predicate.field}_{predicate.op}\"",
     '                verdict = "REJECTED"'),
    ("G12 the predicate result is inverted",
     "            if not frame._evaluate(predicate, projected):",
     "            if frame._evaluate(predicate, projected):"),
    ("G13 ineligible rows are yielded anyway",
     '        if verdict != "ELIGIBLE":' + NL + "            continue",
     '        if verdict != "ELIGIBLE":' + NL + "            pass"),
    ("G14 the projection is bypassed and the raw record is judged",
     "        projected, sidecar = projection.project(record)",
     "        projected, sidecar = record, record"),

    # --- identity and the partition key
    ("G15 a row with no host id is given one",
     "        if not sidecar.host_uuid:",
     "        if False:"),
    ("G16 a row with no host id is dropped without being counted",
     '            tally["ELIGIBLE_BUT_NO_HOST_UUID"] += 1',
     "            pass"),
    ("G17 the address is used as the identity",
     '            "host_uuid": sidecar.host_uuid,',
     '            "host_uuid": sidecar.name_with_owner,'),
    ("G18 the rank is recomputed rather than copied",
     '            "source_rank": projected.catalog_rank_value,',
     '            "source_rank": len(sidecar.name_with_owner),'),
    ("G19 the tie-break key is dropped",
     '            "record_id": projected.record_id,',
     '            "record_id": "",'),

    # --- spent identities
    ("G20 the spent set is empty",
     "    spent = frozenset(str(entry[\"host_uuid\"]) for entry in sfir7_roots.frozen_roster())",
     "    spent = frozenset()"),
    ("G21 the spent set is keyed on the address instead of the id",
     "    spent = frozenset(str(entry[\"host_uuid\"]) for entry in sfir7_roots.frozen_roster())",
     "    spent = frozenset(str(entry[\"name_with_owner\"]) for entry in sfir7_roots.frozen_roster())"),
    ("G22 the exclusion proof is not carried into the roster",
     '        exclusion_proof=selection["exclusions"],',
     '        exclusion_proof={"host_uuids": [], "count": 0},'),
    ("G23 the count of spent identities is not recorded",
     '        "spent_identities_excluded": len(spent),',
     '        "spent_identities_excluded": 0,'),

    # --- the frozen rule
    ("G24 the roster is generated against a draft protocol",
     "    protocol = protocol_module.Protocol().freeze()",
     "    protocol = protocol_module.Protocol()"),
    ("G25 the partition index moves",
     "        partition_index=protocol_module.PARTITION_INDEX,",
     "        partition_index=protocol_module.PARTITION_INDEX + 1,"),
    ("G26 the partition count moves",
     "        partition_count=protocol_module.PARTITION_COUNT,",
     "        partition_count=protocol_module.PARTITION_COUNT // 2,"),
    ("G27 the salt moves",
     "        salt=protocol_module.SELECTION_SALT,",
     '        salt=protocol_module.SELECTION_SALT + "x",'),
    ("G28 an envelope term is sourced from something the study measured",
     "            source=selection_module.EXTERNAL,",
     "            source=selection_module.OBSERVATION,"),
    ("G29 the per-root allowance is widened, which widens N",
     "            protocol_module.PER_ROOT_CHARGE_ALLOWANCE,",
     "            protocol_module.PER_ROOT_CHARGE_ALLOWANCE // 2,"),

    # --- accounting
    ("G30 unreadable rows are not tallied by reason",
     "            parser_tally[reason] += 1",
     "            pass"),
    ("G31 the row count comes from the consumer instead of the producer",
     '    tally["ROWS_READ"] = yielded[0]',
     '    tally["ROWS_READ"] = sum(tally.values())'),
    ("G32 the eligibility dispositions are not recorded",
     '            "eligibility_dispositions": dict(sorted(tally.items())),',
     '            "eligibility_dispositions": {},'),
    ("G33 the unreadable total is folded into one number",
     '            "unreadable_total": sum(parser_tally.values()),',
     '            "unreadable_total": 0,'),

    # --- the seal and the receipt
    ("G34 the roster is not sealed",
     "    seal = roster.seal()",
     "    seal = roster.digest()"),
    ("G35 the seal is not recorded",
     '        "roster_seal": seal,',
     '        "roster_seal": "",'),
    ("G36 the receipt does not bind the freeze it ran under",
     '        "instrument_freeze": authorities["freeze"]["freeze_digest"],',
     '        "instrument_freeze": None,'),
    ("G37 the receipt does not bind the input it selected from",
     '        "cohort_input_binding": authorities["binding"]["binding_digest"],',
     '        "cohort_input_binding": None,'),
    ("G38 the receipt claims the cohort says something about capacity",
     '        "what_this_does_not_establish": (',
     '        "_removed_what_this_does_not_establish": ('),

    # --- verification
    ("G39 the generation digest is not recomputed",
     '    if _digest(body) != report.get("generation_digest"):',
     "    if False:"),
    ("G40 the digest covers itself",
     '    body = {key: value for key, value in report.items() if key != "generation_digest"}',
     "    body = report"),
    ("G41 an unsealed roster verifies",
     '    if not report.get("roster_seal"):',
     "    if False:"),
    ("G42 broken ordinals verify",
     "    if ordinals != list(range(1, len(entries) + 1)):",
     "    if False:"),
    ("G43 verification passes with problems recorded",
     '        "verified": not problems,',
     '        "verified": True,'),

    # --- the runner
    ("G44 a refused generation exits zero",
     '        print(f"REFUSED  {error}")' + NL + "        return 1",
     '        print(f"REFUSED  {error}")' + NL + "        return 0"),
]
