"""Mutations for repository identity and the spent-development exclusion.

Each entry is one specific weakening, written by hand: what it changes,
and the text it replaces. Lifted verbatim from the driver that first ran
them, so the committed table is the table that produced the recorded
result.
"""

from __future__ import annotations

TARGET = 'tools/sfir9_identity_logic.py'

TESTS = ['tests/test_sfir9_identity_logic.py']

MUTATIONS = [
    ("I1 an address is accepted as an identity",
     '    if "/" in text:', "    if False:"),
    ("I3 the decimal form is not enforced",
     "    if not _NUMERIC.match(text):", "    if False:"),
    ("I4 the id pattern accepts a numeric prefix",
     '_NUMERIC = re.compile(r"\\A[1-9][0-9]*\\Z")',
     '_NUMERIC = re.compile(r"\\A[1-9][0-9]*")'),
    ("I5 the id pattern accepts a leading zero",
     '_NUMERIC = re.compile(r"\\A[1-9][0-9]*\\Z")',
     '_NUMERIC = re.compile(r"\\A[0-9]*\\Z")'),
    ("I8 whitespace is not stripped, so an int and its string differ",
     "    text = str(value).strip()", "    text = str(value)"),

    ("I9 attestation does not compare the ids",
     "        if observed != self.host_uuid:", "        if False:"),
    ("I10 attestation compares addresses instead of ids",
     "        observed = normalize_host_uuid(observed_id)",
     "        observed = str(observed_id)"),

    ("I11 adopting a name changes the identity",
     "        return RepositoryIdentity(\n            host_uuid=self.host_uuid,",
     "        return RepositoryIdentity(\n            host_uuid=canonical_address,"),
    ("I12 an unusable canonical address is adopted",
     '        if not isinstance(canonical_address, str) or canonical_address.count("/") != 1:',
     "        if False:"),
    ("I13 a case-only difference counts as a rename",
     "        return self.canonical_address.casefold() != self.catalogue_address.casefold()",
     "        return self.canonical_address != self.catalogue_address"),
    ("I14 an unresolved root is reported as renamed",
     "        if self.canonical_address is None:\n            return False", "        if False:\n            return False"),
    ("I15 sameness is decided by the address",
     "    return left.host_uuid == right.host_uuid",
     "    return left.catalogue_address == right.catalogue_address"),

    ("I16 the blob sha is not validated",
     "        if not isinstance(text, str) or not _BLOB_SHA.match(text):", "        if False:"),
    ("I17 a truncated blob sha is accepted",
     '_BLOB_SHA = re.compile(r"\\A[0-9a-f]{40}\\Z")',
     '_BLOB_SHA = re.compile(r"\\A[0-9a-f]{7,40}\\Z")'),
    ("I18 the blob sha is not lowercased, so one blob has two identities",
     "        text = blob_sha.lower() if isinstance(blob_sha, str) else blob_sha",
     "        text = blob_sha"),
    ("I19 the path is not validated",
     "        if not isinstance(path, str) or not path:", "        if False:"),
    ("I20 the candidate key drops the repository",
     "        return (self.repository_numeric_id, self.path, self.blob_sha)",
     "        return (self.path, self.blob_sha)"),
    ("I21 the candidate key drops the content",
     "        return (self.repository_numeric_id, self.path, self.blob_sha)",
     "        return (self.repository_numeric_id, self.path)"),
    ("I22 the candidate key drops the path",
     "        return (self.repository_numeric_id, self.path, self.blob_sha)",
     "        return (self.repository_numeric_id, self.blob_sha)"),
    ("I23 a candidate may be identified by an address",
     "            repository_numeric_id=normalize_host_uuid(repository_numeric_id),",
     "            repository_numeric_id=str(repository_numeric_id),"),

    ("I24 the set digest stops ignoring order",
     "    return _digest(sorted(list(candidate.key()) for candidate in candidates))",
     "    return _digest([list(candidate.key()) for candidate in candidates])"),
    ("I25 the order digest starts ignoring order",
     "    return _digest([list(candidate.key()) for candidate in candidates])",
     "    return _digest(sorted(list(candidate.key()) for candidate in candidates))"),

    ("I26 an observation in an exclusion proof is filtered instead of refusing",
     "        if present:", "        if False:"),
    ("I27 the forbidden exclusion set is narrowed",
     '        "candidate_count",\n        "tree_size",', '        "tree_size",'),
    ("I28 the proof need not name the study",
     "        if study not in SPENDING_STUDIES:", "        if False:"),
    ("I29 the spending studies are widened to include SFIR9 itself",
     'SPENDING_STUDIES = ("SFIR7", "SFIR8")', 'SPENDING_STUDIES = ("SFIR7", "SFIR8", "SFIR9")'),
    ("I30 an exclusion may be identified by an address",
     '                host_uuid=normalize_host_uuid(record["host_uuid"]),',
     '                host_uuid=str(record["host_uuid"]),'),
    ("I31 the exclusion reason is widened",
     '            "reason": SPENT,\n            "spent_by_study": self.spent_by_study,',
     '            "reason": "EXCLUDED",\n            "spent_by_study": self.spent_by_study,'),
    ("I32 the proof digest ignores which study spent the root",
     '        "digest": _digest(sorted(entries, key=lambda e: e["host_uuid"])),',
     '        "digest": _digest(sorted(e["host_uuid"] for e in entries)),'),
    ("I33 the proof digest depends on arrival order",
     '        "digest": _digest(sorted(entries, key=lambda e: e["host_uuid"])),',
     '        "digest": _digest(entries),'),
    ("I34 an exclusion is marked value-bearing",
     '            "value_bearing": False,', '            "value_bearing": True,'),
    ("I35 the exclusion count is not reported",
     '        "count": len(entries),', '        "count": 0,'),
]
