# TAVONEL assurance and incremental runtime

Status: implemented production-core hardening, 2026-08-15.

This note records the contracts that now connect document assurance, adaptive
recovery, incremental recompilation, temporal publication, provider cost control,
and tenant/storage boundaries. It intentionally reuses the repository's existing
world-state, temporal, PostgreSQL RLS/claim, deletion, and RunPod v6 control-plane
contracts rather than building parallel systems.

## 1. Assurance evidence is typed and correlation-aware

`akc_cir.inspection.DetectorSignal` carries both `evidence_channel` and
`independence_group`. Legacy detector callers remain valid because a channel and
group are inferred from their failure code. Aggregation takes the strongest signal
within one independence group and applies noisy-or only across independent groups.
Two detectors that inspect the same render therefore cannot manufacture confidence
by double-counting one observation.

Inspection outcomes are no longer binary. `UNKNOWN_REFERENCE` means a required
reference does not exist; `UNRESOLVED` means evidence/recovery could not settle the
case. Only `PASS` has `acceptable=True`. Neither absence nor disagreement can leak
through a publish boundary as success.

Calibration lives in `akc_cir.calibration`. Isotonic, logistic, and conformal
artifacts are deterministic and versioned. Training sample identifiers are stored
only as SHA-256-derived fingerprints, and evaluation refuses train/eval overlap.
ECE, Brier score, and reliability bins are reported independently rather than
collapsed into one opaque quality score.

## 2. Silent semantic corruption and adaptive verification

`akc_cir.critical_tokens` verifies facts whose small transcription change can
remain fluent while changing meaning: numbers, signs, units, dates, currencies,
identifiers, and explicitly named critical table cells. It exposes its finding as
a normal inspection signal so it participates in the same fail-closed policy.

`akc_absorption.synthetic_corruption` creates deterministic digit/sign/unit/date/
currency/header/table/drop/duplication/cross-page mutations with explicit expected
failure families. `ASSURANCE-A-01` contains a reproducible CPU pilot and a
secret-free receipt.

`akc_cir.parser_verification` is provider-neutral. Runtime capabilities describe
which parsers are actually available; risk, uncertainty, failure taxonomy and hard
cost/GPU limits decide whether an independent parser is warranted. Low-risk pages
stay single-parser. Visual round-trip is gated by actual visual/table content, and
cross-page checks begin with a cheap textual boundary check. Parser agreement keeps
text similarity and critical-fact agreement as separate axes; critical disagreement
ends as unresolved instead of being averaged away.

## 3. Recovery is budgeted, traceable, and loop-safe

The existing failure-taxonomy registry remains the source of retry/reparse/
rerender/escalation choices. `RecoveryBudget` now enforces wall-clock time in
addition to GPU and cost. Existing failure-signature/policy-signature checks prevent
deterministic retry loops. `RecoveryTraceReceipt` provides a deterministic,
tenant/page-scoped, secret-free account of attempts, GPU seconds, wall-clock time,
cost units, and the final decision.

Experiment spending is independently guarded by
`akc_absorption.assurance_experiment.ExperimentGuardrail`:

- external GPU/API work is forbidden until the CPU/synthetic gate is GREEN;
- Stage 1 is capped at 300 samples by default and has explicit GPU/cost limits;
- Stage 2 is capped at 2,000 samples and additionally requires Stage 1 GREEN;
- a large benchmark is never automatically authorized.

This is a hard pre-execution boundary, not merely an after-the-fact cost report.

## 4. Logical identity is separate from evidence occurrence

`UnitSnapshot.logical_unit_id` names stable semantic identity while
`evidence_occurrence_id` names a concrete version/location observation. Existing
wire fields remain backward compatible.

`ChangeChannel` separates semantic, graph, locator, structural, visual, temporal,
metadata and unresolved change. Semantic recompilation seeds only semantic/graph
changes. A page/anchor move remains visible to provenance consumers but cannot by
itself make every semantic derivative stale.

`DependencyEdge.channels` makes dependency sensitivity explicit. Existing untyped
traversal still works; a consumer that knows its change channel can request typed
propagation and avoid irrelevant invalidation.

## 5. Derivation, caching and reproducibility

`DerivationManifest` records tenant, logical units, evidence occurrences, source
content hashes, dependency channels, parser/model versions, config fingerprint,
calibration artifact, recovery trace, generation, and execution class.

The lineage fingerprint always retains evidence occurrences. A semantic-only cache
key intentionally omits occurrence location, so an unchanged fact moving from one
page to another preserves the cached semantic result while the manifest still says
where the original observation came from. Locator/visual/structural-sensitive
derivations include occurrence identity and therefore invalidate on movement.

Execution classes are `PURE`, `PINNED_STOCHASTIC`, and `IMPURE`. Pinned stochastic
work requires a seed and pinned model version; impure work cannot enter the reusable
content-addressed cache. Cache lookup is tenant-scoped and supports tenant purge.

## 6. Selective invalidation is proven against a full-rebuild oracle

The prior production-core behavior had a historical `mean_rebuild_fraction=1.0`.
DIAG-B-01 showed that the safe fix was not to shrink the dependency graph: doing so
left stale artifacts behind. The promoted fix is to prevent locator-only evidence
movement from seeding semantic traversal.

The current evolution-suite promotion check (`documents=30`, current generator)
produces 330 mutation cases. The post-fix result is:

- mean rebuild fraction: `0.12626262626262624`;
- min/max rebuild fraction: `0.0 / 0.2222222222222222`;
- full-rebuild semantic equivalence: `330/330`;
- stale artifacts left behind: `0`.

The committed receipt is
`research/experiments/DIAG-B-01/receipts/production-semantic-channel-promotion.json`.
The historical 1.0 value came from an older committed corpus generation, so it is
retained as historical context, not presented as a paired statistical comparison.

`akc_cir.shadow_audit` adds a production safety net: high-risk changes are always
sampled against a full rebuild, lower-risk changes use deterministic random
sampling, and any mismatch forces full-rebuild fallback.

## 7. Atomic publication and temporal retrieval reuse existing core contracts

No second publication system was introduced. `akc_cir.world_state` already stages
a candidate generation, validates it, then swaps the active pointer atomically;
rollback returns to a known validated generation and readers never observe a
partial candidate as ACTIVE.

No second temporal database was introduced. `akc_cir.temporal` already separates
valid-time from known-time and supports as-of retrieval/replay. Derivation manifests
and generation identifiers now give assurance/incremental work the lineage needed
to connect to those existing temporal semantics.

## 8. Tenant, storage and provider boundaries

PostgreSQL RLS, claim-broker and lease boundaries remain authoritative. Recovery
and cache records carry tenant identity rather than introducing a global cache
namespace. Existing security tests cover tenant context and claim broker behavior.

Object-store/database deletion continues through the existing API/scheduler
deletion lifecycle. The derivation cache's tenant purge is an in-process semantic
counterpart, not a replacement for R2/object-store deletion. Existing document
workers remain responsible for ephemeral work-directory cleanup.

RunPod v6 remains dry-run-first. Execute mode accepts a primary process-local key
and an optional process-local fallback. Secrets never enter receipts. 401/403 may
fail over because the provider explicitly rejected the request; HTTP 429 may fail
over only for GET. Writes never fail over after rate limiting or an ambiguous
transport result, preventing duplicate paid jobs.

## 9. Evidence and release gates

The runtime is not considered externally proven merely because these contracts and
CPU tests pass. A paid Stage-1 parser pilot is allowed only when a qualified/pinned
runtime endpoint and hard-sample corpus are present and the CPU gate is GREEN. The
pilot must record exact parser/runtime identity, quality metrics, latency, GPU
seconds and provider cost, then terminate/clean up through the existing v6 lifecycle.

Stage 2 and larger runs remain conditional on prior-stage evidence. This keeps the
research path aligned with Minimum Cost to Trusted Output rather than spending GPU
budget to compensate for unresolved software correctness.