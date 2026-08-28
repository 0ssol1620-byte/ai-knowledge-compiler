"""Mutations for the ten-component execution closure.

Each entry is one specific weakening, written by hand: what it changes,
and the text it replaces. Lifted verbatim from the driver that first ran
them, so the committed table is the table that produced the recorded
result.
"""

from __future__ import annotations

TARGET = 'tools/sfir9_execution_closure.py'

TESTS = ['tests/test_sfir9_execution_closure.py', '-k', 'not test_the_disagreement_check_runs_before_any_component_is_verified and not test_the_closure_says_out_loud_what_it_cannot_certify and not test_the_closure_passes_against_this_repository and not test_every_component_reports_all_five_bindings and not test_the_closure_digest_is_stable_and_covers_the_components and not test_the_closure_carries_the_upstream_binding_when_given_one and not test_the_manifest_records_the_closure_tools_own_bytes and not test_the_manifest_reads_the_tool_from_disk_rather_than_importing_it and not test_a_good_manifest_verifies and not test_a_manifest_pinning_a_different_tool_does_not_verify and not test_a_manifest_pinning_a_different_blob_does_not_verify and not test_a_manifest_edited_after_writing_does_not_verify and not test_a_manifest_from_another_closure_does_not_verify and not test_the_closure_comparison_is_skipped_rather_than_assumed_when_absent and not test_the_manifest_verifies_a_tool_it_did_not_produce and not test_the_manifest_notices_a_tool_edited_in_the_tree_it_is_checked_against and not test_the_manifest_says_why_it_is_a_separate_artifact']

MUTATIONS = [
    ("E1 the component lists are not compared",
     "    if set(ours) != set(theirs):", "    if False:"),
    ("E2 the lists are compared by length only",
     "    if set(ours) != set(theirs):", "    if len(ours) != len(theirs):"),
    ("E3 the list check is never invoked by the closure",
     "    require_component_lists_agree()\n    origins", "    origins"),
    ("E4 the component list is narrowed",
     '    Component("scorer", "sfir9_scorer"),\n', "    "),
    ("E5 a component pointing at a missing file passes",
     "    if not path.exists():", "    if False:"),
    ("E6 committed bytes are not compared with working bytes",
     "    if committed != working:", "    if False:"),
    ("E7 committed and working are compared by length",
     "    if committed != working:", "    if len(committed) != len(working):"),
    ("E8 a component that was never imported passes",
     "    if origin is None:", "    if False:"),
    ("E9 the import origin is not compared with the verified file",
     "    if resolved != path:", "    if False:"),
    ("E10 the origin check accepts any file of the same name",
     "    if resolved != path:", "    if resolved.name != path.name:"),
    ("E13 the closure digest ignores the components",
     '        "components": records,', '        "components": [],'),
    ("E14 the closure digest ignores the upstream binding",
     '        "upstream_binding": upstream_binding,', '        "upstream_binding": None,'),
    ("E15 the closure claims to certify its own bytes",
     '            "its own bytes. This module is one of the ten it verifies, and a "',
     '            "everything, including itself. Nothing further is needed: a "'),

    ("E16 the manifest does not record the tool hash",
     '            "sha256": transport.sha256_of(working),\n            "git_blob_id": transport.git_blob_id_of(working),',
     '            "sha256": "sha256:unread",\n            "git_blob_id": transport.git_blob_id_of(working),'),
    ("E17 the manifest does not record the tool blob id",
     '            "git_blob_id": transport.git_blob_id_of(working),\n            "bytes": len(working),',
     '            "git_blob_id": "0" * 40,\n            "bytes": len(working),'),
    ("E18 the manifest does not record which closure it belongs to",
     '        "closure_digest": closure_result["closure_digest"],',
     '        "closure_digest": "sha256:any",'),
    ("E19 the manifest is written against an uncommitted tool",
     "    if committed != working:\n        raise ClosureRefused(\n            BYTES_MISMATCH,\n            f\"{CLOSURE_PATH} differs",
     "    if False:\n        raise ClosureRefused(\n            BYTES_MISMATCH,\n            f\"{CLOSURE_PATH} differs"),
    ("E20 the manifest asks the module instead of reading the file",
     "    working = path.read_bytes()\n    committed = read_committed_bytes(repository_root, CLOSURE_PATH)",
     "    working = importlib.import_module(CLOSURE_MODULE).__doc__.encode()\n    committed = working"),

    ("E21 verification does not re-read the tool",
     "    tool_sha_matches = recorded.get(\"sha256\") == transport.sha256_of(working)",
     "    tool_sha_matches = True"),
    ("E22 verification does not check the tool blob id",
     '    tool_blob_matches = recorded.get("git_blob_id") == transport.git_blob_id_of(working)',
     "    tool_blob_matches = True"),
    ("E23 verification does not check the manifest's own digest",
     '    manifest_intact = _digest(body) == manifest.get("manifest_digest")',
     "    manifest_intact = True"),
    ("E24 the manifest digest is computed over itself, so any edit still matches",
     "    body = {key: value for key, value in manifest.items() if key != \"manifest_digest\"}",
     "    body = dict(manifest)"),
    ("E25 an absent closure result is treated as a match",
     "    closure_matches = None", "    closure_matches = True"),
    ("E26 a mismatched closure result is not a problem",
     "    if closure_matches is False:", "    if False:"),
    ("E27 verification reports verified whatever it found",
     '        "verified": not problems,', '        "verified": True,'),
    ("E28 verification hides the problems it found",
     '        "problems": problems,', '        "problems": [],'),
]
