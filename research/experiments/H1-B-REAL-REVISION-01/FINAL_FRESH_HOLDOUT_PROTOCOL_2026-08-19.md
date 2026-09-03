# Family B final fresh-seed holdout protocol — frozen before seed generation

This is the final independent controlled holdout for B-EQUIV. All development
seeds/results remain development evidence. No Protected-Core or generator bytes
may change after the seed-hash freeze and before the one-shot run.

## Frozen generators and cells

The runner combines two already-debugged development mechanisms without using a
development seed:

1. change-space classes: `unchanged`, `semantic_only`, `structural_only`,
   `mixed`, `ambiguous` — 400 cases/class;
2. topology cells: 64-deep semantic chain, cross-document dependency,
   semantic-channel diamond, structural-channel diamond — 200 cases/cell.

Policy under test: `StructuralPolicy.PRECISE`, with the current default
`seed_unresolved_incoming=True`.

## Primary success criterion

**All cells must have zero stale escapes and exact selective-vs-independent-full
artifact equivalence.** A gate that blocks an escape is containment evidence but
is still an equivalence failure. No cell may be dropped or pooled away.

Secondary descriptive outputs: false invalidations, artifacts rebuilt, and gate
containment. They cannot rescue a primary failure.

## Seed and one-shot seal

After this protocol and runner pass compile/lint:

1. generate one 128-bit OS-random integer outside the repository;
2. write only `sha256(str(seed))`, protocol sha256, runner sha256 and relevant
   Protected-Core sha256 values to the preregistration receipt;
3. do not edit the runner, protocol or Protected-Core after that receipt;
4. execute exactly once using the hidden seed;
5. disclose the seed in the result receipt and verify its sha256 equals the
   preregistered hash.

An execution/infrastructure failure before any case result is produced may be
retried with the *same* seed and identical hashes. A scientific failure may not
be retried/tuned into a pass; it is the final holdout result.

GPU cost is $0.00; this is deterministic graph/diff/hash validation, not model
inference. Synthetic/controlled distributions are not represented as real-world
frequency estimates.
