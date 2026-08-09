# Frontend evidence handoff

The public benchmark campaign has produced measured results that the site can
publish. This note says what is ready, what must not be published, and what is
still being measured.

Nothing under `apps/` was touched by the benchmark work, so this handoff should
merge without conflicting with website changes.

## Read these two files

- `docs/evidence/folynta-public-claims-pack.json`
  — machine readable. Labels, numbers and constraints are ready to render.
- `docs/evidence/FOLYNTA_PUBLIC_CLAIMS.md`
  — the same content for human review.

Both are generated from the evidence receipts. **Do not edit the numbers in
them.** If a figure looks wrong, say so and it will be regenerated from source
rather than corrected by hand.

Each claim names the receipt it came from under `evidence`, and every one of
those files is now **in the repository** at `docs/evidence/artifacts/`, with its
`evidence_sha256` beside it. You have them locally and can verify any figure
against the artifact it came from.

That was not true before. The paths used to point into
`benchmark/reports/generated/`, which is git-ignored: eleven of the fourteen
cited files existed only on the machine that produced them, and nine claims
carried a path with no hash at all. The generator now refuses to emit a claim
that cites a file git ignores, or a path without a hash, so this cannot quietly
regress. `evidence_source` records where each artifact was produced.

Each claim carries a `status`:

| status | what to do |
|---|---|
| `approved` | publish; use `numbers` as given |
| `conditional` | publish only with every entry in `conditions` shown |
| `withheld` | do not publish; `why_withheld` explains |

Claims also carry `must_say` / `must_say_en` (text that must accompany the
number) and `forbidden` (phrasings that must not appear).

## Work items

1. **Headline numbers.** Completion 99.98%, recovery 99.94%, benchmark accuracy
   80.6%. Completion and accuracy are different measures and must never be
   presented as one figure.
2. **Accuracy by document type.** Render from `accuracy-by-document-type`, which
   ships `label_ko` / `label_en` per row. The `benchmark_slice` field
   (`old_scans.jsonl` and similar) is an internal identifier — never display it.
   The low-quality scan row (36.9%) must stay in the table.
3. **Recovery contribution.** The strongest result on the page: with the
   recovery lane disabled, the identical pipeline scores 53.7 instead of 80.6.
   Three benchmarks agree. State that only the recovery lane differs between
   the two runs.
4. **Customer-facing fidelity.** 94.2% character-level text match and 95.5%
   table structure accuracy are more intuitive than the benchmark score and are
   measured on the same corpus. Label what each number measures if both appear.
5. **Pipeline description.** `product-pipeline` lists the stages, the seven
   built-in knowledge blueprints and the four export targets. These stages have
   no benchmark score, so do not attach an accuracy percentage to them; the
   supportable evidence is `compilation-guarantees`.

## What changed since you last copied the pack

Your copy at `apps/web/src/data/claims/public-claims-pack.json` is behind.
`verify-claims.mjs` will fail on drift until you re-copy, which is the gate
working. Re-copy from `docs/evidence/folynta-public-claims-pack.json`.

**`must_say_en` was missing on seven claims, not five.** The live page currently
renders Korean sentences on an English page in at least two places — under the
recovery counterfactual and under the OmniDocBench row. All seven now carry
English: `completion-rate`, `recovery-rate`, `compilation-guarantees`,
`corpus-scale`, and all three `recovery-contribution-*`.

**`recovery-contribution-parsebench` gained a constraint it did not have.**
Removing the recovery lane makes the ParseBench *layout* pass rate go **up**,
0.757 to 0.770, because a document with no content has no elements to score and
the denominator falls from 40,287 to 23,025. Quoted as a rate, no-recovery looks
better than recovery. The claim now carries that sentence in `must_say` and
forbids citing the layout rate as evidence of recovery's effect. The page's
current "the other two benchmarks agree" block quotes absolute failure counts
and table GriTS, which is correct — this is to keep it that way.

**`corpus-scale` gained one too.** 5,132 is documents evaluated, not capacity
and not customer volume.

**The olmOCR counterfactual artifact was regenerated.** It had two null hash
fields, and one field named `relative_score_delta` holding 0.5009 — the gap
measured against the *without-recovery* score. Against the with-recovery score
it is 0.3337. Both are true and they say different things. The ambiguous field
is gone, replaced by `score_share_lost_without_recovery` and
`score_uplift_over_no_recovery`. **Neither figure was ever on the page** — the
site quotes 80.6 and 53.7 directly — so no rendered number was wrong. Do not
introduce either ratio without its denominator in the label.

## Hard rules

- Never describe the 99.98% completion rate as accuracy. 72.3% of documents
  carry at least one failure, so nothing may imply flawless output.
- Every rate needs its denominator. The 99.94% recovery rate is measured over
  documents that actually failed, not over the corpus.
- Leaderboard rows for other systems are quoted from public sources and were
  not reproduced here. Do not claim we beat any named product by any margin.
- The `$1.23` per 1,000 pages is raw GPU cost, not a price. Do not place it
  beside a competitor's retail price.

## Still being measured

`quality-retry-improvement` is withheld because the targeted retry and its
no-regression gate have not finished. When they do, the pack is regenerated and
that claim unblocks with a measured figure. Please leave room for it rather
than designing around its absence.

## Backend changes in this branch

One product change affects behaviour: vault link validation now ignores math
spans, so a document containing notation such as `$[[s \otimes f]]$` is no
longer refused for a link that was never a link. No API shape changed. The rest
of the diff is benchmark tooling, evidence receipts and operational scripts.

## On the merge order

Your `docs/PARALLEL_SESSIONS.md` has #33 and #34 landing first, then one rebase
here. That still holds and this branch is not rebasing before it.

Two things you should know before that happens.

**PR #24 conflicts with `main` in 37 files, 26 of them under `apps/web`.** They
are not disagreements about your work. This branch predates the TAVONEL reset
and still carries the whole previous website generation — it has no
`design-system/tavonel` and no `apps/web/src/styles`, and it has components
`main` has since dropped. Under the ownership split in PARALLEL_SESSIONS,
`apps/web/` and `design-system/` are yours, so the rebase here takes `main`'s
side wholesale for both. Nothing of yours is at risk in that resolution, and no
review of those 26 files is needed from you.

**`scripts/check_migration_chain.py` does not exist on this branch**, so the one
guard that would catch the duplicate 0023 was not running here. There is now an
equivalent at `tests/unit/test_migration_graph.py` that runs in the normal
suite: it fails on a fork, a second head, a dangling parent, a cycle, or an
unreachable revision. Verified against the real case — dropping a second `0023`
with the same parent into `migrations/versions` fails three of its six checks
and names both files. Keep whichever of the two you prefer after the merge;
running both is harmless.
