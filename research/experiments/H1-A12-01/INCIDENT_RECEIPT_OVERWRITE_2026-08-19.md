# Incident — the readiness receipt was overwritten, 2026-08-19

**A receipt was destroyed by my own tooling change. This records what was lost,
what replaced it, and why the replacement is not the original.**

Recording it rather than quietly regenerating is the whole point: the repository
rule is that historical receipts are never edited or deleted, and that rule is
worth nothing if a violation can be tidied away.

---

## What happened

`scripts/audit_runtime_readiness.py` had a hardcoded output path
(`receipts/runtime-readiness-audit-2026-08-19.json`) and no `--output`
argument. To re-evaluate the gates after freezing the arm B recipe, an
`--output` argument was added so the earlier receipt would survive.

**The patch was applied incompletely.** The argument was added and the summary
line was updated, but the two lines that actually write the file still referred
to the module-level `OUTPUT` constant. The run reported writing to
`runtime-readiness-audit-v2-2026-08-19.json` while in fact overwriting
`runtime-readiness-audit-2026-08-19.json`.

The mistake was mine, and the guard that caught it was noticing that the
reported v2 file did not exist on disk while the original's mtime had moved.

## What was lost

| | |
|---|---|
| path | `research/experiments/H1-A12-01/receipts/runtime-readiness-audit-2026-08-19.json` |
| original `receipt_sha256` | `sha256:825fd68dd2b704c6cc5cdc22eae74b36506801192a58d864477e579ff9b8d078` |
| original `generated_at` | `2026-08-19T01:17:19.622320+00:00` |
| recoverable from git? | **No.** `research/experiments/H1-A12-01/receipts/` is untracked. |

The original's substantive content **is** known and was quoted in full earlier
in the session that destroyed it:

- `overall_state`: `BLOCKED_RUNTIME_AND_RECIPE`
- `blockers`: `formal_immutable_runtime_not_ready`,
  `exact_same_family_recipe_not_frozen`
- `gates.licence_ready`: `true`; `gates.source_only_ready`: `true`
- `gates.formal_immutable_runtime_ready`: `false`;
  `gates.exact_same_family_recipe_ready`: `false`
- `gpu_spend_authorized`: `false`; `incremental_gpu_spend_usd`: `0.0`
- `exact_recipe_artifact_candidates`: `[]`
- both candidate pools at `pending_exact_image_digest` with a null image digest

## What the path holds now

A **deterministic regeneration** of the pre-freeze audit, produced by moving the
recipe-freeze receipt aside and re-running the audit. Its gate state matches the
original in every field above, including the empty
`exact_recipe_artifact_candidates`.

**It is not the original receipt.** `generated_at` and therefore
`receipt_sha256` differ, and they always will. The regeneration currently on
that path is:

| | |
|---|---|
| regenerated `receipt_sha256` | `sha256:56ff7b44ec86946bd30e961376ceba8a3c3403e2c900884b1915b04b26a2e8f9` |
| regenerated `generated_at` | `2026-08-19T01:55:43.007803+00:00` |

That hash is pinned here so the file is checkable in both directions: it must
match neither the lost original (which would mean the loss did not happen) nor
some third value (which would mean the path moved again after this incident was
written). Anyone comparing this file
against the hash recorded above will find a mismatch, and that mismatch is
correct — it is the fingerprint of this incident, not of a tampered result.

The regeneration is independently checkable: move
`receipts/same-family-recipe-freeze-2026-08-19.json` out of the tree, re-run
`scripts/audit_runtime_readiness.py`, and compare every field except the
timestamp and the self-hash.

## What is at the v2 path

`receipts/runtime-readiness-audit-v2-2026-08-19.json` — the audit re-run **after**
the recipe freeze, which is what the re-run was for. Its blockers are
`["formal_immutable_runtime_not_ready"]` only.

## Why no result changed

The audit is a pure function of repository state. Nothing about A12's standing
moved because of this incident: `gpu_spend_authorized` was `false` before and is
`false` now, `incremental_gpu_spend_usd` is `0.0`, no arm ran, and no claim cites
either receipt for anything other than readiness.

Had the overwritten receipt been an *outcome* receipt rather than a readiness
audit, this would not have been recoverable in any form, and the correct entry
here would have been "evidence destroyed".

## What changed so it cannot recur

- `audit_runtime_readiness.py` now honours `--output` in the lines that actually
  write, verified by observing the v2 file appear on disk.
- **A patch that claims to redirect an output is not trusted until the new file
  is seen.** The reported path and the written path are different facts.
