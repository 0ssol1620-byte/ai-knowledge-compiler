# V5 Model Arena Corpus — Current State and Construction Plan

*Masterplan v5.0 PHASE 0 deliverable ("Arena corpus audit file"). Written
2026-08-11 against `9b5edd9`.*

v5 PART 8 makes the Arena a core system. This file records what the repository
holds toward it today and what has to be built. It is an inventory, not a
campaign — no page has been selected, no manifest exists, nothing has been run.

---

## Arena v1 — 1,000 pages, exactly

PART 34: *"Build Model Arena v1 as exactly 1,000 pages unless a receipt
documents a justified revision."*

| Block | Target | Present | Gap |
|---|---:|---|---|
| A. Public Ground Truth | 400 | corpora + official evaluators from the 5,132-doc campaign | stratified selection, slice labels, manifest |
| B. Real Corporate — DART | 150 | `benchmark/acquire_dart.py`, DART credential | acquisition run, page selection, truth refs |
| B. Real Corporate — SEC | 150 | nothing | acquisition, selection, XBRL truth binding |
| C. TAVONEL Failure Zoo | 200 | 1,797 recovery-required documents from the campaign | classification into nine slices, page extraction |
| D. Clean Control | 100 | nothing | sourcing |
| **Arena total** | **1,000** | | |
| Prompt calibration set | 100 | nothing | separate sourcing, family-disjoint from Arena |

### A — Public Ground Truth, 400 pages

Stratified from the three benchmarks the campaign already ran
(olmOCR-bench 1,403 · OmniDocBench 1,651 · ParseBench 2,078). Recommended slice
composition:

| Slice | Pages |
|---|---:|
| Clean digital | 60 |
| Table-heavy | 70 |
| Multi-column / reading order | 50 |
| Formula / academic | 50 |
| Low-quality / degraded scan | 60 |
| Small-font / long | 40 |
| Chart / figure / visual grounding | 40 |
| Headers/footers / presence-absence | 30 |

The per-benchmark split has to satisfy slice targets **and** official evaluator
coverage simultaneously, then be frozen in a manifest. This is the constraint
that makes selection non-trivial — a slice with no evaluator coverage produces
runs nobody can score.

### B — Real Corporate, 300 pages

DART 150: 사업보고서 · 반기/분기보고서 · 감사보고서 · 재무제표/주석 · 표 밀집 공시 ·
정정공시 · 긴 한글 문서 · 한/영 혼합 · 작은 글씨 · 이미지/스캔 첨부.

SEC 150: 10-K · 10-Q · 8-K · amendments · exhibits · financial statements ·
footnotes · inline XBRL-linked financial tables.

These two blocks are not scored only on OCR quality. PART 8.2 requires
**Critical Numeric Fidelity, amendment/version handling, source evidence and
downstream QA** — which is why inline XBRL matters: it is machine-readable truth
that costs nothing to adjudicate.

### C — Failure Zoo, 200 pages

The campaign's own failures, classified:

| Failure slice | Pages |
|---|---:|
| Degraded scans | 40 |
| Difficult tables | 40 |
| Reading order / multi-column | 30 |
| Formulas | 25 |
| Tiny text | 20 |
| Cross-page semantics | 15 |
| Blank / near-blank | 10 |
| Operational timeout / wall-clock | 10 |
| Misc. difficult / disagreement | 10 |

The metric this block exists for is
`Incremental Recovery Yield(model B | model A failure)` — not "who scores
highest", but "when A fails, does B actually recover it". That is the number the
router needs and no public leaderboard reports.

The last slice matters for a reason `CLAUDE.md` already states: **operational
failure and semantic failure are different problems.** A wall-clock timeout is
not a model being wrong, and mixing them corrupts the recovery statistics.

### D — Clean Control, 100 pages

Born-digital, single column, normal font, simple table, ordinary corporate
report or manual. Its purpose is to prove **where an expensive model is not
needed** — the block that saves money rather than measuring quality.

---

## Splits (PART 8.4)

Router data splits **by document family, not by random page**:

```text
60% ROUTER_TRAIN   20% ROUTER_CALIBRATION   20% ROUTER_HOLDOUT
```

Two pages of the same report must never land on both sides. Random page-level
splitting would leak the answer — the model that read page 3 of a filing has
seen the layout of page 4.

**If a router policy is revised after seeing holdout labels, it needs a new
policy version and a new holdout.** Reusing the holdout after looking at it is
the fastest way to a number that means nothing.

## Prompt calibration — separate, and frozen first

The 100-page calibration set decides provider-optimized prompts, schemas and
image resolution. It must be **family-disjoint** from the Arena, and prompts are
**frozen before** the Arena runs. Tuning on Arena pages turns a measurement into
a self-portrait.

---

## Evaluation tracks (PART 9)

| Track | Input | Question it answers |
|---|---|---|
| **I** Standardized page-image | same rendered image for every model | which family is stronger, all else equal |
| **N** Native provider best-practice | each provider's preferred input (native PDF etc.) | what each provider does at its best |
| **P** Provider-optimized prompt | tuned per provider, frozen pre-run | how much prompt engineering is worth |
| **B** Batch / bulk economics | batch endpoints and pricing | what it costs at volume |

Track I and Track N are reported separately. A single number spanning both is
not a result, and batch is not interchangeable with interactive until
equivalence is measured.

---

## Reproducibility and leakage

- A stratified subset runs **three times** (PART 34).
- Every run pins exact model ID, revision/snapshot, provider API version, input
  mode, prompt sha256, schema sha256, evaluator revision and price snapshot.
- **Raw provider output is preserved.** Normalization performs deterministic
  representation conversion only and may never add missing semantic content —
  a normalizer that fills a gap is fabricating evidence.
- Leakage control per PART 9.10; the calibration set is the first line.

---

## Schemas needed at Phase 1

Arena schemas move into the contract phase under v5, so the Phase 1 plan written
against v4 is incomplete without them. From APPENDIX A and PART 3.4:

| Contract | Carries |
|---|---|
| Case manifest | case_id, source_sha256, document_family_id, split, origin, slices, risk_class, truth refs, licence/publication |
| Run receipt | exact model id + revision, input/prompt track, batch mode, prompt/schema/input/raw/normalized sha256, status, latency, actual cost + price snapshot, evaluator receipts |
| Router oracle row | permitted paths, per-path outcome (trusted, cost, latency, catastrophic), cheapest-trusted / highest-quality / business-risk-optimal path |

Tables: `arena_campaigns`, `arena_cases`, `arena_runs`, `arena_scores`.

**`raw_output_sha256` and `normalized_output_sha256` are separate fields on
purpose.** Keeping both is what makes the "normalization added no content"
claim checkable instead of asserted.

---

## The rule that outranks the corpus design

PART 3.5, and it is easy to lose in the schema detail:

> Production route outcomes live in a namespace separate from the Arena.
> **Customer data is never automatically folded into the benchmark corpus.**

A customer document that fails in production is exactly the page an engineer
wants in the Failure Zoo. Putting it there automatically is a consent violation
and a leakage source at once.

---

## Status

Nothing here is built. No campaign, no manifest, no case, no run, no score.
Phases 1–3 come first, and the API-family credential decision
(`docs/audit/V5_COST_BUDGET.md` B-1) gates the cross-family comparison that is
the Arena's entire point.

Corpus construction — selection, manifests, DART/SEC acquisition, Failure Zoo
classification — needs no model credential and is the cheapest useful work
available. It can start whenever Phase 3 lands.
