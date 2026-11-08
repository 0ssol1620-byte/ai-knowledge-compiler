# ADR-008: Fold corpus parts into one World in the live Core (`corpus_reduce`), shadow first

- Status: **Proposed** — shadow wiring only; nothing served changes
- Date: 2026-11-08
- Scope: `akc_product_core.corpus_reduce` (new), `akc_product_core.api` (shadow hook),
  `akc_product_core.contracts.CorpusPart` (optional request field),
  `akc_product_core.semantics.contradiction_candidates` (extracted, behaviour unchanged),
  `benchmark/product_core_corpus_reduce.py` (the gate)
- Program: PROGRAM-2026-11-04 §4.B, B3; risk §0.3 (3)
- Changes digests of existing compiles: **no** (golden digests unchanged; the release digest
  changes because the vendored package gains files)

## This is live-Core semantics, not Protected Core

`corpus_reduce` belongs to the product-core compiler that is deployed as
`tavonel-product-core-v2`. It is **not** `akc_cir`, does not replace, refactor or reimplement
any `akc_cir.*` module (identity, world_state, recompilation, semantic_diff, dependency,
reconciler), and does not move any identity threshold. It calls `akc_cir` the same way the
compiler does (`source_id`, `build_knowledge_object`, `SourceRef`). A future adapter from the
Protected Core identity path is B5's ladder, not this one.

## Context

Foundation compiles a corpus of up to 128 documents in parts of 12 (`corpus-batching.ts`),
and says so: the parts are separate Worlds because nothing merged them. Concatenating part
ontologies would duplicate entities and lose every contradiction that crosses a part seam.

## Decision

`corpus_reduce(parts) -> (corpus_world, receipt)` is a pure, deterministic function over the
verified `/v2/compile` outputs of every part of one corpus:

1. **Verify each part** before reading it: its receipt binds the request ID, the request-body
   digest and the digest of the candidate as served; all parts share corpus, tenant,
   workspace, collection, blueprint and Core release; the part set is complete
   (`0..partCount-1`, no duplicates); every part is an `initial_compile` and not rejected.
2. **Union** documents, units, blocks, evidence, claims and relations by their
   content-derived IDs. The same ID in two parts must be byte-identical once attempt fields
   (request time, activity, the object hash that covers the activity) are set aside, or the
   reduce refuses with `REDUCE_ID_COLLISION`.
3. **Entities merge only on the compiler's exact key** (the casefolded label is the entity
   ID). Names that agree only after dropping case, spacing and punctuation
   (`Globex-Corp` / `Globex Corp`) are returned as `reviewCandidates` with
   `decision: human_review_required` and are never merged.
4. **Recompute over the union:** contradiction candidates (shared function with the compiler),
   semantic profile, domain, architecture plan, ontology terms and the collection root.
5. Review reasons: per-document and validation reasons are a union; recomputed ones are
   recomputed; an unknown reason refuses (`REDUCE_REVIEW_REASON_UNKNOWN`) rather than vanish.
6. Provenance: copied objects keep the part activity that produced them; recomputed objects
   carry a reduce activity bound to the part output digests; `parts[]` lists each part's
   request, digests, World ID and documents.
7. Output lifecycle is `candidate` or `review_required`, `candidatePromotion: false`.
   Nothing here activates a World. The receipt carries input digests, output digest,
   canonical-form digest, part count, cross-part merge and contradiction counts and the
   review-candidate count.

Every refusal is a `CorpusReduceError` with a stable code; there is no partial World.

The reduce emits the corpus World **model**. The delivery package (markdown, JSON-LD, TTL,
CSV, RAG chunks) is a deterministic projection of that model and is built at rollout, when
the package-size check (24 MiB / 200 files) for 128-document corpora is measured.

## The gate: split compile + reduce == whole compile, 100%

`benchmark/product_core_corpus_reduce.py` compiles a corpus whole, compiles it in parts under
several split strategies (Foundation's 12-document partition, contiguous k=2/3/4/6,
interleaved k=2/3 so every neighbour pair straddles a seam, singletons, reversed part input,
and identical overlap), reduces, and compares canonical forms: ordered documents, units and
knowledge objects without attempt fields, plus semantic profile, architecture, review reasons
and lifecycle. A naive concatenating reduce is run as a negative control and must be detected.

- Synthetic fixtures (committed test): 26 corpora, 247 cases, 247/247 equal, negative control
  detected. These are regression fixtures, not evidence about customer documents.
- **Rollout requires 100% on a real corpus** (≥ 20 corpora of ≤ 12 documents, plus > 12-document
  corpora compared with a single offline whole compile) run with `--corpus` under `outputs/`.
  One divergent case fails the gate.

Known approximation, surfaced by the gate rather than hidden: validation-check reasons are a
union of the part verdicts, not a re-run of the checks on a corpus package. If ADR-007 changes
contradiction encoding, the reduce follows it through the shared `contradiction_candidates`.

## Shadow wiring and flag

`TAVONEL_CORPUS_REDUCE_MODE` (PROGRAM 부록 A): `off` (default) | `shadow`. `on` refuses to
start the process until the gate above has passed and a reviewed change enables it.

In `shadow`, a compile request that names its `corpusPart {corpusId, partIndex, partCount}`
is served exactly as in `off`; afterwards the process holds the served part (bounded at
128 MiB, oldest corpus dropped and logged) and, when every part of the corpus has been served
by the same process, reduces and logs `corpus_reduce_shadow` with the receipt (digests and
counts only, no document text). Refusals log `corpus_reduce_shadow_refused` with the code;
any other error logs `corpus_reduce_shadow_error` with its type and never reaches the caller.

Ceiling: the shadow is process-local. On a multi-instance deployment the parts of one corpus
can be served by different instances and that corpus is not reduced. A durable shadow needs
Foundation to send `corpusPart` (not yet sent) and, for rollout, to hand the stored part
Worlds to one reduce call.

## Ladder

contract (this change) → shadow (this change, flag default off) → benchmark on a real corpus
(orchestrator-provided) → canary (cohort, corpus World card with parts folded) → rollout →
deprecate the per-part World list (data kept).

## Rollback

Unset `TAVONEL_CORPUS_REDUCE_MODE` (or `off`) and redeploy: the hook is skipped and served
bytes are unchanged in either mode. Reverting the commit restores the previous release; part
Worlds were never altered, so nothing needs repair.
