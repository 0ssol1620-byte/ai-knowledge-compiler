"""Mutations for the sealed cohort roster.

Each entry is one specific weakening, written by hand: what it changes,
and the text it replaces. Lifted verbatim from the driver that first ran
them, so the committed table is the table that produced the recorded
result.
"""

from __future__ import annotations

TARGET = 'tools/sfir9_cohort_roster.py'

TESTS = ['tests/test_sfir9_cohort_roster.py']

MUTATIONS = [
    ("R1 a forbidden field is filtered instead of refusing",
     "    if present:", "    if False:"),
    ("R2 the forbidden set drops the earlier study's output",
     '        "candidate_count",\n        "tree_size",', '        "tree_size",'),
    ("R3 the forbidden set drops the live-execution facts",
     '        "rename_status",\n        "renamed",\n        "canonical_address",', "        "),
    ("R4 the permitted field list is widened",
     '    "selection_ordinal",\n)', '    "selection_ordinal",\n    "canonical_address",\n)'),
    ("R5 an entry may be identified by an address",
     '    host_uuid = identity.normalize_host_uuid(row["host_uuid"])',
     '    host_uuid = str(row["host_uuid"])'),

    ("R6 the partition digest ignores the identity",
     '            "host_uuid": host_uuid,\n        }\n    )',
     '            "host_uuid": "",\n        }\n    )'),
    ("R7 the partition digest ignores the bucket index",
     '            "partition_index": partition_index,\n            "host_uuid": host_uuid,',
     '            "partition_index": 0,\n            "host_uuid": host_uuid,'),
    ("R8 the partition digest ignores the bucket count",
     '            "partition_count": partition_count,\n            "partition_index"',
     '            "partition_count": 0,\n            "partition_index"'),
    ("R9 the partition digest ignores the salt",
     '            "salt_digest": salt_digest,\n            "partition_count"',
     '            "salt_digest": "",\n            "partition_count"'),
    ("R10 the salt itself is published instead of its digest",
     "            salt_digest=partition[\"salt_digest\"],",
     "            salt_digest=str(partition),"),

    ("R11 a spent root in the roster is accepted",
     "            if entry.host_uuid in spent:", "            if False:"),
    ("R12 the exclusion proof is not carried into the roster body",
     '            "exclusion_proof": self.exclusion_proof,', '            "exclusion_proof": {},'),

    ("R13 duplicate repositories are accepted",
     "        if len(set(uuids)) != len(uuids):", "        if False:"),
    ("R14 duplicate catalogue records are accepted",
     "        if len(set(records)) != len(records):", "        if False:"),
    ("R15 the ordinals are not checked",
     "        if ordinals != list(range(1, len(entries) + 1)):", "        if False:"),
    ("R16 the ordinals start at zero",
     "        for ordinal, row in enumerate(selection[\"roster\"], start=1):",
     "        for ordinal, row in enumerate(selection[\"roster\"], start=0):"),
    ("R17 the well-formedness check is never invoked",
     "        self._check_wellformed(entries)", "        pass"),

    ("R18 a draft protocol may generate a roster",
     '        protocol.require_frozen("roster generation")', "        pass"),
    ("R19 the roster does not record its protocol",
     '            "protocol_digest": self.protocol_digest,', '            "protocol_digest": "",'),
    ("R20 the roster does not record its selection",
     '            "selection_digest": self.selection_digest,', '            "selection_digest": "",'),

    ("R21 sealing twice is idempotent",
     "        if self._sealed:", "        if False:"),
    ("R22 sealing changes what the roster says",
     "        self._seal_digest = self.digest()", '        self._seal_digest = "sha256:sealed"'),
    ("R23 the seal is not recorded",
     "        self._sealed = True\n        self._seal_digest = self.digest()",
     "        self._seal_digest = self.digest()"),
    ("R24 an unsealed roster passes the seal requirement",
     "        if not self._sealed:", "        if False:"),
    ("R25 the seal verifies against itself instead of a recomputation",
     "        recomputed = self.digest()", "        recomputed = self._seal_digest"),
    ("R26 the seal reports intact whatever it found",
     '            "intact": recomputed == self._seal_digest,', '            "intact": True,'),
    ("R27 the roster digest ignores the entries",
     '            "entries": [entry.as_dict() for entry in self.entries],',
     '            "entries": [],'),
    ("R28 the roster digest ignores the entry order",
     '            "entries": [entry.as_dict() for entry in self.entries],',
     '            "entries": sorted((entry.as_dict() for entry in self.entries), key=repr),'),

    ("R29 execution evidence is merged into the roster body",
     '            "is_part_of_the_roster": False,', '            "is_part_of_the_roster": True,'),
    ("R30 execution evidence does not require a seal",
     '        self.require_sealed("recording execution evidence")', "        pass"),
    ("R31 execution evidence accepts a root outside the roster",
     "            if host_uuid not in known:", "            if False:"),
    ("R32 execution evidence is not bound to the roster digest",
     '            "roster_digest": self._seal_digest,\n            "observations": rows,',
     '            "roster_digest": None,\n            "observations": rows,'),
    ("R33 the live rename is dropped from execution evidence",
     '                    "renamed": bool(observation.get("renamed")),',
     '                    "renamed": False,'),
]
