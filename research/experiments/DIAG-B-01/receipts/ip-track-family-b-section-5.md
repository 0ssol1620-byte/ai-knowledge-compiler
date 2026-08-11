# `DIAG-B-01` → Family B §5 — the causal wording, settled

> **NOT CLEARED FOR EXTERNAL DISCLOSURE.** Internal record. Every number here is
> a read-only counterfactual on a synthetic fixture.

*Deliverable for the IP track, which was holding for this. **This file is not
the disclosure.** It supplies the causal finding Family B §5 was blocked on, in
the form §5 needs it, for the IP track to carry across.*

---

## The claim state, unchanged by this diagnostic

| state | asserts | current |
|---|---|---|
| `IMPLEMENTED` | the mechanism exists in code | **yes** |
| `DEMONSTRATED` | a narrow recompilation benefit is proven | **no** |
| `NOT YET DEMONSTRATED` | neither shown end to end | **this is the state** |

`DIAG-B-01` explains *why* the benefit is unproven. It does not prove it, and
nothing in it moves the state. **`DEMONSTRATED` remains unavailable** until a
corrected changed-set channel exists and is measured, which is a Protected Core
change this diagnostic neither makes nor authorises.

## The causal finding

Over the same 660 document pairs `EXP-0101` used:

**95.9% of the traversal seed set — 10,320 of 10,759 logical ids — is there
because a unit moved and for no other reason.** `EVIDENCE_MOVED` and a genuine
meaning change travel down one channel: `SemanticChange` carries a single
`logical_id` whatever the kind, and `changed_logical_ids`
(`semantic_diff.py:195`) collects from every kind that is not
`IDENTITY_UNRESOLVED`. Dependency traversal cannot tell the two apart, so it
treats "this clause moved down the page" as "this clause changed".

| counterfactual | rebuild fraction | equivalence | artifacts left stale |
|---|---|---|---|
| actual | 1.0000 | 660/660 | 0 |
| evidence ids stable where the unit did not move | 0.2503 | 660/660 | 0 |
| **only meaning-changing kinds in the changed set** | **0.1263** | **660/660** | **0** |
| both of the above | 0.1263 | 660/660 | 0 |
| dependency rollup removed | 0.0802 | **180/660** | **480** |

## What Family B §5 may now say, and what it may not

**May say:** the degeneration is caused by **the changed-set channel carrying
positional and semantic change under one identifier**. That is `C3`, and it is
both dominant and sufficient: correcting it alone takes the rebuild fraction
from 1.0000 to 0.1263 with equivalence intact and zero artifacts left stale.

**May say:** the dependency invalidation rule is **not** the cause. Narrowing it
is cheaper and wrong — equivalence collapses to 180/660 with 480 stale
artifacts. The breadth is real, and the rule is doing its job.

**May say:** evidence identity design is **not required** to change. `C3` alone
reaches the floor, so no new evidence-id derivation and no
`IDENTITY_SCHEME_VERSION` migration is implied. Version-scoped evidence ids
contribute (1.0000 → 0.2503, safely) but are **not necessary** once `C3` is
addressed: adding them to `C3` changes nothing.

**May not say:** that selective recompilation has been shown to reduce work.
`0.1263` is what a corrected channel *would* have cost on this fixture. The
corrected channel does not exist.

**May not say:** that the cause is established beyond this fixture. Seventeen
units per document, every one carrying an evidence id. A corpus whose units
mostly lack evidence ids would show a smaller share for `evidence_moved_only`,
and the attribution would shift accordingly.

## Why the shape of this finding matters for enablement

The mechanism is not broken and the design is not wrong. What the measurement
found is narrower and more specific: **two different notions of "changed" share
one channel**, and the consumer downstream cannot distinguish them. That is a
statement about an interface, not about whether the invention works — which is
the distinction §5's wording has to hold, in both directions.

Under-claiming is a failure here too. "Selective recompilation does not work" is
not what was measured and is not supportable.

## Receipts

| what | where |
|---|---|
| verdict, machine-readable | `research/experiments/DIAG-B-01/receipts/verdict.json` |
| findings table | `research/experiments/DIAG-B-01/tables/findings.md` |
| per-counterfactual raw | `research/experiments/DIAG-B-01/raw/counterfactuals.jsonl` |
| digests | `research/experiments/DIAG-B-01/receipts/receipts.json` |
| the number this explains | `research/experiments/EXP-0101/metrics/summary.json` |

**Filing and publication timing is the founder's alone.**
