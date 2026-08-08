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

Each claim names the receipt it came from under `evidence`. Those receipts live
under `benchmark/reports/generated/`, which is git-ignored because it holds
multi-gigabyte evaluation output. The paths are there so a figure can be traced
on the machine that produced it; you will not have those files locally and do
not need them to build the page.

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
