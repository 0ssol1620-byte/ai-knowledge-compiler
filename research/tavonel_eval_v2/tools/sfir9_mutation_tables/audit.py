"""Mutations for the hostile audit's ability to report a failure.

Each entry is one specific weakening, written by hand: what it changes,
and the text it replaces. Lifted verbatim from the driver that first ran
them, so the committed table is the table that produced the recorded
result.
"""

from __future__ import annotations

TARGET = 'tools/sfir9_hostile_audit.py'

TESTS = ['tests/test_sfir9_hostile_audit.py']

MUTATIONS = [
    # --- the verdict itself
    ("H1 the audit passes regardless of the results",
     '        "audit_passes": len(refused) == len(results),',
     '        "audit_passes": True,'),
    ("H2 the audit passes if anything at all was refused",
     '        "audit_passes": len(refused) == len(results),',
     '        "audit_passes": len(refused) > 0,'),
    ("H3 a control failure is counted as a refusal",
     '    refused = [r for r in results if r["outcome"] == REFUSED]',
     '    refused = [r for r in results if r["outcome"] != NOT_REFUSED]'),
    ("H4 a wrong-reason refusal is counted as a refusal",
     '    refused = [r for r in results if r["outcome"] == REFUSED]',
     '    refused = [r for r in results if r["outcome"] in (REFUSED, WRONG_CODE)]'),
    ("H5 the exit code ignores the verdict",
     '    return 0 if report["audit_passes"] else 1',
     "    return 0"),

    # --- the control, which is what makes silence mean something
    ("H6 the control is never run",
     "        attack.control(control_sandbox)",
     "        pass"),
    ("H7 a failed control is reported as a refusal",
     '            "outcome": CONTROL_FAILED,',
     '            "outcome": REFUSED,'),
    ("H8 a failed control no longer explains itself",
     '            "why_this_is_not_a_pass": (',
     '            "_why_removed": ('),
    ("H9 the control failure count stops counting",
     '        "attacks_whose_control_failed": len(\n'
     '            [r for r in results if r["outcome"] == CONTROL_FAILED]\n'
     "        ),",
     '        "attacks_whose_control_failed": 0,'),
    ("H10 the control runs in the attacked sandbox",
     '    control_sandbox = sandbox / f"{attack.name}__control"',
     '    control_sandbox = sandbox / f"{attack.name}__attack"'),

    # --- the code assertion
    ("H11 any refusal counts, whatever its reason",
     "        matched = attack.expected_code in str(error) or attack.expected_code == code",
     "        matched = True"),
    ("H12 only the message is checked, never the code attribute",
     "        matched = attack.expected_code in str(error) or attack.expected_code == code",
     "        matched = attack.expected_code in str(error)"),
    ("H13 only the code attribute is checked, never the message",
     "        matched = attack.expected_code in str(error) or attack.expected_code == code",
     "        matched = attack.expected_code == code",),
    ("H14 an unexpected exception type is treated as a refusal",
     '            "outcome": WRONG_CODE,\n'
     '            "expected_code": attack.expected_code,\n'
     '            "observed": f"{type(error).__name__}: {error}",\n'
     "        }\n"
     "    return {",
     '            "outcome": REFUSED,\n'
     '            "expected_code": attack.expected_code,\n'
     '            "observed": f"{type(error).__name__}: {error}",\n'
     "        }\n"
     "    return {"),
    ("H15 an attack that got through is reported as refused",
     '        "outcome": NOT_REFUSED,',
     '        "outcome": REFUSED,'),
    ("H16 every exception type is accepted as a refusal",
     "    except attack.refusals as error:",
     "    except Exception as error:"),

    # --- the roster of attacks
    ("H17 the attack list is truncated",
     "    Attack(\n"
     '        "checkpoint_chain_from_another_roster",',
     "    Attack(\n"
     '        "_removed_checkpoint_chain_from_another_roster",'),
    ("H18 the closure-omission attack drops nothing",
     "        closure_module.COMPONENTS = tuple(\n"
     "            c for c in original if c.name != name\n"
     "        )",
     "        closure_module.COMPONENTS = original"),
    ("H19 the substituted component is written back identical",
     '        (sandbox / target).write_bytes(committed[target] + b"\\n# substituted\\n")',
     "        (sandbox / target).write_bytes(committed[target])"),
    ("H20 the blob attack changes the length, so a size check would catch it",
     '    (sandbox / target).write_bytes(committed[target].replace(b"protocol", b"protocoL", 1))',
     '    (sandbox / target).write_bytes(committed[target] + b"x")'),
    ("H21 the dirty-tree attack points at the honest origin",
     '    origins["sfir9_scorer"] = "/some/other/dirty/tree/tools/sfir9_scorer.py"',
     "    pass"),
    ("H22 the upstream attack mutates nothing",
     '    mutated = committed[target] + b"\\n# mutated upstream\\n"',
     "    mutated = committed[target]"),
    ("H23 the spent-root attack excludes a root that was never selected",
     '    selected = selection["roster"][0]["host_uuid"]',
     '    selected = "999999999"'),
    ("H24 the draft-protocol attack uses a frozen protocol",
     "def _draft_protocol_attack(_sandbox):\n"
     "    return _roster(protocol=protocol_module.Protocol())",
     "def _draft_protocol_attack(_sandbox):\n"
     "    return _roster(protocol=protocol_module.Protocol().freeze())"),
    ("H25 the prerequisite attack names a receipt that never drifted",
     "    affected = sorted(drift.affected_receipts)[0]",
     '    affected = "a-receipt-that-never-existed.json"'),
    ("H26 the lookup attack plants deterministic code",
     "    return sorted(root.glob('*.json'))[-1]\\n\",",
     "    return root / 'named.json'\\n\",",),
    ("H27 the selection-digest attack reuses the roster's own digest",
     '        chain.open_next(_handoff(selection_digest="sha256:selection-B"))',
     "        chain.open_next(_handoff())"),
    ("H28 the other-roster attack reuses the same roster",
     '    return chain.append(chain.open_next(_handoff(roster_digest="sha256:roster-B")))',
     "    return chain.append(chain.open_next(_handoff()))"),

    # --- the receipt
    ("H29 the digest stops moving with the results",
     '        "audit_digest": "sha256:"\n'
     "        + hashlib.sha256(\n"
     '            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")\n'
     "        ).hexdigest(),",
     '        "audit_digest": "sha256:" + "0" * 64,'),
    ("H30 the results are dropped from the receipt",
     '        "results": results,',
     '        "results": [],'),
    ("H31 the mounted count is asserted rather than measured",
     '        "attacks_mounted": len(results),',
     '        "attacks_mounted": 13,'),
    ("H32 the auditor starts carrying its own copy of a rule",
     "@dataclass\nclass Attack:",
     "class ClosureRefused(Exception):\n    pass\n\n\n@dataclass\nclass Attack:"),
    ("H33 the refusal list gets a permissive default again",
     "    refusals: tuple[type[BaseException], ...]",
     "    refusals: tuple[type[BaseException], ...] = (Exception,)"),
]
