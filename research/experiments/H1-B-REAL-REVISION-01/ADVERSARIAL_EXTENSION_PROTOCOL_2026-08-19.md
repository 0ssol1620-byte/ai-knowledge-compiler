# Family B adversarial topology extension — frozen before execution

This is a development validation, not the still-sealed fresh holdout. It closes
three topology gaps named in `research/HANDOFF_2026-08-19.md` before the final
one-shot holdout is spent.

## Cells

1. **deep semantic chain** — a semantic change at one knowledge unit feeds a
   64-artifact dependency chain. Every downstream artifact really consumes the
   prior artifact.
2. **cross-document dependency** — a changed unit in document A feeds an A
   artifact, a cross-document aggregate, then a document-B derived artifact.
   Artifact names/doc ownership must not terminate dependency propagation.
3. **diamond with conflicting channels** — one source unit fans out into a
   SEMANTIC branch and a STRUCTURAL branch, then rejoins at one aggregate whose
   branch edges preserve the respective channel. Run both a text-only semantic
   change and a shape-only structural change.

## Frozen counts / criterion

- 200 deterministic cases for each non-diamond cell.
- 200 semantic + 200 structural cases for the diamond cell.
- seed `2026081907`.
- structural policy `PRECISE`.
- **Primary criterion: exact artifact equivalence against an independently
  computed full rebuild. Zero stale escapes in every cell.**
- A promotion gate blocking a stale escape is safety evidence but does not turn
  an equivalence failure into a pass.
- No production-performance claim is derived from this synthetic/controlled
  topology sweep.
- GPU cost is $0.00; GPU is irrelevant to graph traversal/hash correctness.

If any cell fails, fix the implementation on development cases and add a
regression test before the fresh-seed holdout is unsealed. Do not reuse this
extension as the final independent holdout.
