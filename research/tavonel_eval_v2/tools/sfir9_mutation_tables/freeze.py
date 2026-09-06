"""Mutations for the instrument freeze.

Each entry is one specific weakening, written by hand: what it changes, and the
text it replaces. The freeze is the artifact everything downstream points at, so
these attack its refusals rather than its ability to succeed.
"""

from __future__ import annotations

TARGET = 'tools/sfir9_freeze.py'

TESTS = ['tests/test_sfir9_freeze.py']

MUTATIONS = [
    # --- the refusals
    ("Z1 a dirty namespace is frozen anyway",
     "    if not commit.namespace_is_clean:",
     "    if False:"),
    ("Z2 a closed gate does not stop the freeze",
     '    if not gate_report["gate_opens"]:',
     "    if False:"),
    ("Z3 an unproven condition is treated as passing",
     '    if not gate_report["gate_opens"]:',
     '    if not gate_report["conditions_passed"]:'),
    ("Z4 an opened cohort does not stop the freeze",
     "    if cohort.state != gate_module.PASS:",
     "    if False:"),
    ("Z5 a second freeze overwrites the first",
     "    if target.is_file() and not allow_refreeze:",
     "    if False:"),
    ("Z6 a missing supporting receipt is skipped",
     "        if not path.is_file():",
     "        if False:"),
    ("Z7 a git failure is assumed away",
     "    if result.returncode != 0:",
     "    if False:"),

    # --- the gate is re-derived, not read
    ("Z8 the gate verdict is read from the receipt instead of re-derived",
     "    gate_report = gate_module.gate(namespace)",
     "    gate_report = {'gate_opens': True, 'conditions_checked': 9,\n"
     "                   'conditions_passed': 9, 'gate_digest': 'sha256:x', 'conditions': []}"),
    ("Z9 the freeze stops recording that it re-derived the gate",
     '            "re_derived_here": True,',
     '            "re_derived_here": False,'),

    # --- what the receipt binds
    ("Z10 the supporting receipts are bound by nothing",
     '            "file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),\n'
     '            "self_digest": report.get(digest_key) if digest_key else None,\n'
     '            "bytes": len(raw),',
     '            "bytes": len(raw),'),
    ("Z11 the receipt file hash is not recorded",
     '            "file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),',
     '            "file_sha256": "sha256:" + "0" * 64,'),
    ("Z12 the receipt's own digest is not recorded",
     '            "self_digest": report.get(digest_key) if digest_key else None,',
     '            "self_digest": None,'),
    ("Z13 the bound receipt list is narrowed",
     '    ("historical_isolation", "sfir9-historical-isolation.json", None),\n)',
     ")"),
    ("Z14 the gate receipt is dropped from the bound list",
     '    ("freeze_gate", "sfir9-freeze-gate.json", "gate_digest"),\n',
     ""),
    ("Z15 the dirty-tree refusal stops naming what was uncommitted",
     '            f"{namespace_rel} has uncommitted changes: {list(commit.dirty_paths)[:5]}. "',
     '            f"{namespace_rel} has uncommitted changes. "'),
    ("Z16 the instrument commit is not recorded",
     '        "instrument_commit": commit.sha,',
     '        "instrument_commit": "",'),
    ("Z17 the protocol recorded is the draft one",
     "    frozen_protocol = protocol_module.Protocol().freeze()",
     "    frozen_protocol = protocol_module.Protocol()"),
    ("Z18 the closure is not bound into the freeze",
     '        "execution_closure": closure_result,',
     '        "execution_closure": {},'),
    ("Z19 the freeze manifest is not bound",
     '        "freeze_manifest": manifest,',
     '        "freeze_manifest": {},'),
    ("Z20 the upstream SFIR8 binding is not bound",
     '        "upstream_binding": upstream,',
     '        "upstream_binding": {},'),

    # --- verification
    ("Z21 the freeze digest is not recomputed on verify",
     '    if recomputed != report.get("freeze_digest"):',
     "    if False:"),
    ("Z22 a draft protocol verifies",
     '    if report.get("protocol", {}).get("freeze_state") != "PROTOCOL_FROZEN":',
     "    if False:"),
    ("Z23 any state verifies",
     '    if report.get("state") != FROZEN:',
     "    if False:"),
    ("Z24 verification passes with problems recorded",
     '        "verified": not problems,',
     '        "verified": True,'),
    ("Z25 the digest covers itself",
     '    body = {key: value for key, value in report.items() if key != "freeze_digest"}',
     "    body = report"),

    # --- the runner
    ("Z26 a refused freeze exits zero",
     '        print(f"REFUSED  {error}")\n        return 1',
     '        print(f"REFUSED  {error}")\n        return 0'),
    ("Z27 the freeze stops saying what it does not establish",
     '        "what_this_does_not_establish": (',
     '        "_removed_what_this_does_not_establish": ('),
    ("Z28 the freeze stops saying what it authorises",
     '        "what_this_authorises": (',
     '        "_removed_what_this_authorises": ('),
]
