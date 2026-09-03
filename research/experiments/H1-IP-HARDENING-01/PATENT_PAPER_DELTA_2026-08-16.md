# TAVONEL H1 Patent / Paper Hardening Delta — 2026-08-16

Status: **INTERNAL IMPLEMENTATION EVIDENCE / NO FILING OR PUBLICATION AUTHORIZATION**

This addendum records only what changed in the current repository during the H1
hardening Goal. It does not amend a patent claim chart, authorize filing, modify
the frozen manuscript, or convert unit/integration evidence into an empirical
performance claim.

## 1. Family A — A9 source-grounded acceptance

### Before this Goal

The protected recovery core already enforced the important negative invariant:

- candidate agreement alone cannot produce `ACCEPT` when source-aware checks are
  absent;
- parser/model self-confidence may cause escalation but never acceptance.

However, repository search showed no real producer for
`source_aware_checks_passed`; the Boolean was exercised only by the recovery core
and tests. Therefore the earlier `PARTIAL` ruling was correct.

### Added in this Goal

`packages/cir-python/src/akc_cir/source_grounded_acceptance.py`

- typed source-check status: `PASS` / `FAIL` / `UNAVAILABLE`;
- typed source-correspondence check kinds;
- source revision hash + source locator + candidate hash bound into the receipt;
- a concrete born-digital/native-text source correspondence check;
- an independent critical-token check in addition to normalized text
  correspondence;
- `UNAVAILABLE` is explicit and cannot be treated as a pass;
- final arbitration remains delegated to the existing protected recovery core.

Evidence:

- A9/source-gate + protected arbitration + critical-token regression: **52/52
  PASS**.

Current claim status:

`IMPLEMENTED NATIVE-SOURCE WORKED EMBODIMENT / VISUAL-SOURCE + LIVE INTEGRATION PENDING / EMPIRICAL PRECISION BENEFIT WITHHELD`

What is still missing:

- a real visual-source verifier for scan/image-only pages;
- persistence/API/product wiring of the receipt;
- an independent held-out experiment showing that source-grounded acceptance has
  better accepted-output precision/coverage than agreement or genuine model
  self-confidence.

Research contract:

`research/experiments/H1-A9-01/preregistration.json`

The correctness outcome is explicitly independent from the gate itself to avoid
circular evaluation.

---

## 2. Family A — A12 cause-conditioned recovery

### Before this Goal

The recovery ladder was cost ordered and strongly bounded, but the operational
versus semantic distinction lived implicitly in policy contents rather than in a
first-class typed branch. The earlier claim chart therefore correctly called A12
`PLANNED`.

### Added in this Goal

`packages/cir-python/src/akc_cir/cause_conditioned_recovery.py`

- explicit `FailureClass`;
- explicit `RecoveryOperatorKind` independent from price/rung number;
- operational/transient failures retain bounded same-family retry;
- semantic/model failures may take source-preserving deterministic repair but
  skip same-family parser/model variation and move to an independent family,
  source verifier, reconciliation, review, or fail-closed path;
- security failures remain blocked by the existing protected core;
- budget, repeated-signature stop, mode ceiling and circuit semantics remain
  delegated to `recovery_policy.select_recovery` rather than being duplicated.

Evidence:

- A12 + protected recovery/inspection regression: **101/101 PASS**.

Current claim status:

`IMPLEMENTED / EMPIRICAL BENEFIT WITHHELD`

Research contract:

`research/experiments/H1-A12-01/preregistration.json`

The Phase-0 harness is zero-GPU and may measure only selector divergence. It is
not allowed to claim quality or cost benefit. Phase 1 executes both arms only on
policy-divergent cases; identical actions are executed once and shared between
arms.

Input discovery ruling:

`WAITING_ON_PRIMARY_ATTEMPT_LOG`

- existing paper experiment packs are aggregate evidence, not replayable
  counterfactual attempt histories;
- the recovery fault-injection golden explicitly says
  `evidence_class=synthetic_contract_only` and is excluded from empirical A12
  evidence;
- no performance result was reconstructed from aggregate totals.

---

## 3. Family B — B15 governed revision recomputation

### Before this Goal

Authority, applicability/authority scope, temporal resolution, typed dependency,
recompilation and candidate-world primitives existed independently. The missing
piece was a narrow source-revision composition that recomputed governed status
and converted the change into an explainable dirty plan.

### Added in this Goal

`packages/cir-python/src/akc_cir/revision_resolution.py`

- recomputes before/after governed resolution through the existing authority
  core;
- independently fingerprints authority, applicability and valid-time dimensions;
- semantic dimensions propagate through the semantic dependency channel;
- valid-time changes propagate through the temporal channel;
- creates an explainable `RecompilationPlan` with typed reason paths;
- may stage an existing `WorldStateRegistry` candidate;
- **never validates or activates the candidate**. Existing world-state validation
  and publish gates remain authoritative.

Evidence:

- B15 + authority/temporal/dependency/world-state regression: **111/111 PASS**.

Current claim status:

`IMPLEMENTED DOMAIN VERTICAL SLICE / LIVE PERSISTENCE + API/UI CONSUMER PENDING`

---

## 4. Family B — B14 exact stale-consumption lineage

### Before this Goal

`CONSUMED_BY` / export-oriented dependency vocabulary existed, but no real domain
object created exact prior-consumption edges and no function identified which
specific prior answer/agent consumption had become stale. The earlier claim chart
therefore correctly called B14 `PLANNED`.

### Added in this Goal

`packages/cir-python/src/akc_cir/consumption_lineage.py`

- `ConsumptionReceipt` binds exact consumed units to a source `world_state_id`;
- exact consumed-unit → receipt relations become typed `CONSUMED_BY` edges;
- stale risk exists only if normal dependency impact reaches that explicit edge;
- the result names source world, candidate world, changed IDs and a human-readable
  reason path;
- locator-only movement does not silently become a semantic stale-answer event;
- temporal impact can be traced separately;
- no notification, re-execution, write-MCP, or remediation behavior is claimed.

Evidence:

- B14 + dependency regression: **36/36 PASS**.
- integrated B15 → B14 source revision → governed resolution change → dirty answer
  → exact prior consumption stale-risk: **1/1 PASS**.

Current claim status:

`IMPLEMENTED DOMAIN VERTICAL SLICE / LIVE CONSUMPTION PERSISTENCE + PRODUCT ACTION PENDING`

---

## 5. Paper impact

The current *Beyond the Parser* manuscript remains evidence-bound and unchanged.
This Goal does **not** add unmeasured results to it.

What became stronger:

1. A9 now has a concrete native-source worked embodiment instead of only a
   negative Boolean acceptance invariant.
2. A12 now has a removable, directly ablatable implementation rather than a
   planned concept.
3. A9 and A12 each have pre-registered follow-on study contracts designed to
   reuse frozen outputs and spend GPU only where a counterfactual cannot be
   answered offline.
4. B15/B14 now have implementation evidence suitable for the separate living-
   knowledge/selective-recompilation research track, but no corpus-scale result is
   claimed.

Still withheld:

- A9 accepted-output precision improvement;
- A12 trusted-output/cost improvement;
- B14/B15 live-product/S4 behavior;
- generalized selective-recompile performance from the existing 30-document /
  330-case engineering evidence.

---

## 6. GPU / cost ruling

Incremental GPU spend for this H1 hardening batch so far: **USD 0.00**.

The registered experiment policy remains:

- offline/frozen-output analysis first;
- fresh inference only for unresolved counterfactuals;
- source/evaluator ground truth never mounts on GPU workers;
- prefer independent 4-way sharding after the immutable runtime is formally
  qualified;
- nominal pilot cap USD 3;
- hard cap USD 10 without a new explicit founder authorization.

No GPU experiment starts merely because code is complete. Formal image security,
build receipt and runtime qualification gates remain independent prerequisites.
