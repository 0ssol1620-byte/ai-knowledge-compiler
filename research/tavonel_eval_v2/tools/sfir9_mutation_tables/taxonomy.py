"""Mutations for the legacy-failure classification behind D == 0.

Each entry is one specific weakening, written by hand: what it changes,
and the text it replaces. Lifted verbatim from the driver that first ran
them, so the committed table is the table that produced the recorded
result.
"""

from __future__ import annotations

TARGET = 'tools/sfir9_legacy_taxonomy.py'

TESTS = ['tests/test_sfir9_legacy_taxonomy.py']

MUTATIONS = [
    ("T1 an unrecognised failure defaults to a harmless category",
     '        "category": D,\n        "signature": None,',
     '        "category": C,\n        "signature": None,'),
    ("T2 an unrecognised failure is not value-bearing",
     '        "value_bearing_for_sfir9": True,\n'
     '        "sfir9_components_in_traceback": [],\n'
     "    }\n\n\ndef taxonomy",
     '        "value_bearing_for_sfir9": False,\n'
     '        "sfir9_components_in_traceback": [],\n'
     "    }\n\n\ndef taxonomy"),
    ("T3 the freeze condition ignores D",
     '        "freeze_condition_met": counts[D] == 0,',
     '        "freeze_condition_met": True,'),
    ("T4 the freeze condition tolerates a few Ds",
     '        "freeze_condition_met": counts[D] == 0,',
     '        "freeze_condition_met": counts[D] < 3,'),
    ("T5 a component in the traceback no longer forces D",
     "    touched = touches_sfir9(record)\n    if touched:",
     "    touched = touches_sfir9(record)\n    if False:"),
    ("T6 the component check runs after signature matching, so a benign match wins",
     "    touched = touches_sfir9(record)\n    if touched:",
     "    touched = []\n    if touched:"),
    ("T7 the watched component list is narrowed",
     '    "sfir9_selection",\n)',
     ")"),
    ("T8 the component scan only looks at the exception, not the traceback",
     "    text = _text_of(record)\n"
     "    return [module for module in SFIR9_COMPONENT_MODULES if module in text]",
     "    text = record.get('exception', '')\n"
     "    return [module for module in SFIR9_COMPONENT_MODULES if module in text]"),
    ("T9 every category becomes non-value-bearing",
     "VALUE_BEARING_FOR_SFIR9 = frozenset({D})",
     "VALUE_BEARING_FOR_SFIR9 = frozenset()"),
    ("T10 every category becomes value-bearing",
     "VALUE_BEARING_FOR_SFIR9 = frozenset({D})",
     "VALUE_BEARING_FOR_SFIR9 = frozenset({A, B, C, D})"),
    ("T11 the dependency signature swallows every module error",
     r'        r"ModuleNotFoundError: No module named",',
     r'        r"Error",'),
    ("T12 the frame-absence signature drops its second half",
     r'        r"assert not True[\s\S]{0,400}?sfi3_lineages\.json",',
     r'        r"assert not True",'),
    ("T13 the frozen-contract signature matches any assertion error",
     r'        r"AssertionError: (cohort_floor_190|twelve_revision_bound|"',
     r'        r"AssertionError: (.*|twelve_revision_bound|"'),
    ("T14 a signature is reclassified from B to A",
     '        "spent_source_digest_drift",\n        B,',
     '        "spent_source_digest_drift",\n        A,'),
    ("T15 a signature is reclassified from A to B",
     '        "sfi3_frame_materialised",\n        A,',
     '        "sfi3_frame_materialised",\n        B,'),
    ("T16 the signature list is truncated",
     '    Signature(\n        "real_network_guard",',
     '    Signature(\n        "_removed_real_network_guard",'),
    ("T17 signature matching becomes a full match rather than a search",
     "        return re.search(self.pattern, text) is not None",
     "        return re.fullmatch(self.pattern, text) is not None"),
    ("T18 the rows lose their per-failure signature text",
     '        row["failure_signature"] = (record.get("exception") or "").strip()[:400]',
     '        row["failure_signature"] = ""'),
    ("T19 the counts stop counting one category",
     "        name: len([r for r in rows if r[\"category\"] == name]) for name in CATEGORIES",
     "        name: 0 for name in CATEGORIES"),
    ("T20 the examined count is decoupled from the rows",
     '        "failures_examined": len(rows),',
     '        "failures_examined": 60,'),
    ("T21 the digest stops moving with the classification",
     '        "taxonomy_digest": "sha256:"\n'
     "        + hashlib.sha256(\n"
     '            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")\n'
     "        ).hexdigest(),",
     '        "taxonomy_digest": "sha256:" + "0" * 64,'),
    ("T22 the receipt stops declaring what unclassified means",
     '        "unclassified_defaults_to": D,',
     '        "unclassified_defaults_to": C,'),
    ("T23 the category definitions are dropped",
     '        "category_definitions": CATEGORIES,',
     '        "category_definitions": {},'),
    ("T24 the rows are dropped from the receipt",
     '        "rows": sorted(rows, key=lambda r: r["nodeid"]),',
     '        "rows": [],'),
    ("T25 the collector records passes as failures too",
     '        if report.outcome != "failed":\n            return',
     "        if False:\n            return"),
    ("T26 the collector keeps no traceback, only the headline",
     '                "traceback_tail": "\\n".join(lines[-25:]),',
     '                "traceback_tail": "",'),
    ("T27 a matched signature reports no reason",
     '                "why": signature.why,',
     '                "why": "",'),
    ("T28 the component-forced D reports no components",
     '            "sfir9_components_in_traceback": touched,',
     '            "sfir9_components_in_traceback": [],'),
    ("T29 exit code ignores the freeze condition",
     '    return 0 if report["freeze_condition_met"] else 1',
     "    return 0"),
]
