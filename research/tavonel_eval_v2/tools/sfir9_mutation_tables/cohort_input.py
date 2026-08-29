"""Mutations for the cohort-input binding.

Each entry is one specific weakening, written by hand: what it changes, and the
text it replaces. This binding is what stands between the frozen selection rule
and a catalogue nobody checked, so the mutations attack its refusals and the
independence proof rather than its ability to produce a receipt.
"""

from __future__ import annotations

#: Spelled out rather than escaped, so an anchor holding a newline stays
#: legible and cannot be mangled by a shell on its way into this file.
NL = chr(10)

TARGET = 'tools/sfir9_cohort_input.py'

TESTS = ['tests/test_sfir9_cohort_input.py']

MUTATIONS = [
    # --- the catalogue
    ("C1 an absent member is bound anyway",
     '    path = member_path or Path(pins["member_path"])\n    if not path.is_file():',
     '    path = member_path or Path(pins["member_path"])\n    if False:'),
    ("C2 a member whose bytes changed is accepted",
     '    if observed_sha != pins["member_sha256"]:',
     "    if False:"),
    ("C3 the recorded digest is copied instead of recomputed",
     "    observed_sha = sha256_of_file(path)",
     '    observed_sha = pins["member_sha256"]'),
    ("C4 only the first chunk is hashed",
     "        while True:" + NL + "            block = handle.read(chunk)",
     "        for _once in range(1):" + NL + "            block = handle.read(chunk)"),
    ("C5 the size is compared instead of the digest",
     '    if observed_sha != pins["member_sha256"]:',
     '    if path.stat().st_size != pins["member_bytes"]:'),
    ("C6 an absent snapshot receipt is skipped",
     "    path = namespace / SNAPSHOT_RECEIPT\n    if not path.is_file():",
     "    path = namespace / SNAPSHOT_RECEIPT\n    if False:"),
    ("C7 the recomputed digest is not recorded",
     '        "sha256_recomputed": observed_sha,',
     '        "sha256_recomputed": None,'),
    ("C8 the pinned digest is not recorded beside it",
     '        "sha256_recorded": pins["member_sha256"],',
     '        "sha256_recorded": None,'),

    # --- the readers
    ("C9 a reader that differs from the commit is bound",
     "        if committed != working:",
     "        if False:"),
    ("C10 a reader imported from elsewhere is bound",
     "        if origin is None or Path(origin).resolve() != path:",
     "        if False:"),
    ("C11 a reader with no recorded origin is bound",
     "        if origin is None or Path(origin).resolve() != path:",
     "        if Path(str(origin)).resolve() != path and origin is not None:"),
    ("C12 the origin is recorded without being resolved",
     "        origin = import_origins.get(module)",
     "        origin = import_origins.get(module) or str(path)"),
    ("C13 a missing reader is skipped",
     "        if not path.is_file():\n            raise CohortInputRefused(BYTES_MISMATCH,",
     "        if False:\n            raise CohortInputRefused(BYTES_MISMATCH,"),
    ("C14 the reader list is narrowed to one",
     '    "research/tavonel_eval_v2/tools/sfir7_roots.py",\n)',
     ")"),
    ("C15 the blob id is not recorded",
     '                "git_blob_id": hashlib.sha1(header + working).hexdigest(),  # noqa: S324',
     '                "git_blob_id": "0" * 8,'),
    ("C16 a git failure is assumed away",
     "    if result.returncode != 0:\n        raise CohortInputRefused(\n            BYTES_MISMATCH,\n            f\"{relative_path} is not in the commit: \"",
     "    if False:\n        raise CohortInputRefused(\n            BYTES_MISMATCH,\n            f\"{relative_path} is not in the commit: \""),

    # --- the inherited frame
    ("C17 an absent frame receipt is skipped",
     "    path = namespace / INHERITED_FRAME_RECEIPT\n    if not path.is_file():",
     "    path = namespace / INHERITED_FRAME_RECEIPT\n    if False:"),
    ("C18 a frame composed against other bytes is accepted",
     '    if rule["snapshot_sha256"] != snapshot_sha256:',
     "    if False:"),
    ("C19 a predicate naming an identity field is accepted",
     '        if predicate["field"] not in PREDICATE_FIELDS:',
     "        if False:"),
    ("C20 the identity fields become available to a predicate",
     '    return frozenset(sfir7_frame.SELECTABLE_FIELDS) - IDENTITY_FIELDS',
     "    return frozenset(sfir7_frame.SELECTABLE_FIELDS)"),
    ("C20a the allowed field set is restated instead of read",
     '    return frozenset(sfir7_frame.SELECTABLE_FIELDS) - IDENTITY_FIELDS',
     '    return frozenset({"host", "spdx_license_id", "created_utc",' + NL +
     '                      "last_activity_utc", "language", "fork", "status"})'),
    ("C20b only record_id is treated as identity",
     'IDENTITY_FIELDS = frozenset({"record_id", "host_uuid"})',
     'IDENTITY_FIELDS = frozenset({"record_id"})'),
    ("C20c the eligibility fields are not recorded",
     '        "eligibility_fields": sorted(eligibility_fields()),',
     '        "eligibility_fields": [],'),
    ("C21 only the first predicate is checked",
     '    for predicate in rule["predicates"]:',
     '    for predicate in rule["predicates"][:1]:'),
    ("C22 the independence check is dropped",
     "    if not frame_added < protocol_added:",
     "    if False:"),
    ("C23 a frame the same age as the protocol counts as older",
     "    if not frame_added < protocol_added:",
     "    if not frame_added <= protocol_added:"),
    ("C24 the comparison is reversed",
     "    if not frame_added < protocol_added:",
     "    if not protocol_added < frame_added:"),
    ("C25 the newest adding commit is taken as the age",
     "    return log[-1]",
     "    return log[0]"),
    ("C26 a path with no adding commit is given an age",
     "    if not log:",
     "    if False:"),
    ("C27 the frame receipt is not bound by its bytes",
     '        "receipt_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),',
     '        "receipt_sha256": "sha256:" + "0" * 64,'),
    ("C28 the predicates are not recorded",
     '        "predicates": rule["predicates"],',
     '        "predicates": [],'),
    ("C29 the independence timestamps are not recorded",
     '            "frame_entered_repository_at": frame_added,\n            "protocol_entered_repository_at": protocol_added,',
     '            "frame_entered_repository_at": None,\n            "protocol_entered_repository_at": None,'),
    ("C30 the binding stops saying what it does not inherit",
     '        "what_is_not_inherited": {',
     '        "_removed_what_is_not_inherited": {'),
    ("C31 the coincidence in N is presented as an inheritance",
     '                "is unrelated and the agreement is a coincidence, recorded here "',
     '                "is the same and the number was inherited, recorded here "'),

    # --- the frame is read, not restated
    ("C32 the predicates are restated in code instead of read",
     '    rule = json.loads(raw.decode("utf-8"))["frame_rule"]',
     '    rule = json.loads(raw.decode("utf-8"))["frame_rule"]\n'
     '    rule = {**rule, "predicates": [{"field": "host", "op": "eq", "value": "github"}]}'),

    # --- verification
    ("C33 the binding digest is not recomputed on verify",
     '    if _digest(body) != report.get("binding_digest"):',
     "    if False:"),
    ("C34 the digest covers itself",
     '    body = {key: value for key, value in report.items() if key != "binding_digest"}',
     "    body = report"),
    ("C35 verification passes with problems recorded",
     '        "verified": not problems,',
     '        "verified": True,'),
    ("C36 an empty reader list verifies",
     '    if not report.get("input_modules"):',
     "    if False:"),
    ("C37 an empty predicate list verifies",
     '    if not report.get("inherited_frame", {}).get("predicates"):',
     "    if False:"),
    ("C38 a member digest that is not the pinned one verifies",
     '    if member.get("sha256_recomputed") != report.get("catalogue", {}).get("member_sha256"):',
     "    if False:"),

    # --- the runner
    ("C39 a refused binding exits zero",
     '        print(f"REFUSED  {error}")\n        return 1',
     '        print(f"REFUSED  {error}")\n        return 0'),
    ("C40 the binding claims an authority it does not have",
     '        "this_binding_authorises_nothing": (',
     '        "_removed_this_binding_authorises_nothing": ('),
]
