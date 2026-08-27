# INC-V2-096 -- the freeze receipts of the aborted census attempts

Kept so INC-V2-096's account can be checked rather than believed.

`sfir4-design-charter-freeze.json` is the charter freeze the second census
ran under. Its value is one field:

    toolchain.bound_sfir3_ecfr_wikipedia_adapter.sha256
      = sha256:162226e6a604960083b56428703e026d516647839d2eb2267a068471695bf311

That is `tools/probe_sfir3_capacity.py` BEFORE the empty-root fix. It is what
lets a reader confirm the re-freeze changed the adapter and nothing else: the
charter yaml digest, the other five toolchain pins and every declared bound are
identical in the receipt that replaced it.

## Why the spent-identity authority is not kept beside it

It was captured, compared against the one produced by the re-freeze, and
discarded. The two differ in exactly one key:

    keys differing: ['generated_at']
    alias_ids   identical, n = 16456
    lineage_ids identical, n = 9453

A 1.5 MB byte-for-byte duplicate whose only new information is a timestamp is
not evidence; it is a second copy that can rot out of step with the first. The
comparison above is the finding, and it is recorded here rather than in a file
nobody will open.

Neither attempt reached a census result. Both aborted inside the eCFR
enumeration before any capacity quantity was computed, printed or written --
which is what keeps the re-freeze result-blind. See INC-V2-095 and INC-V2-096.
