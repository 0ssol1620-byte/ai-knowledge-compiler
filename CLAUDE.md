# TAVONEL — Project Constitution

North Star: `docs/north-star/TAVONEL_MASTERPLAN_v4.0.md`
(sha256 `c996c372ca4702af1f11a67da61fee90c54c332b9238a89f0e1df7942d1b5e5a`).

Superseded but preserved:

- `docs/north-star/TAVONEL_MASTERPLAN_v3.1.md`
  (sha256 `cd69a8634520cc9f3a9be5e8ac3059c1fe2e445bea39e7ab9a99d81d28ba39fb`)
- `docs/north-star/TAVONEL_FINAL_NORTH_STAR_MASTERPLAN.md`
  (sha256 `6876ea389c41ad6b7b2dec47505a18138116531d51d514cab60204458e276619`)

**Precedence, when two documents disagree** — v4.0's own ordering:

    v4 execution boundary / definition of done / phase gates
      >  v4 normative architecture, security, evidence, migration rules
      >  hash-verified evidence, artifact hashes, benchmark receipts
      >  docs/architecture/v31-phase-gap-matrix.md (current state, not future design)
      >  v3.1 detail that v4 does not contradict
      >  v2/v1 and earlier design documents

Three consequences that have already bitten:

- **v4's PHASE 0–18 governs implementation order.** v3.1's N41 Phase 0–17 and
  §44's PHASE 0–11 are both history now. Phase numbers are dependency order, not
  priority.
- **A v3.1 number that v4 restates differently is v4's number** — the same rule
  that moved the identity merge bar from 0.72 to 0.92. Code written to the older
  number was not wrong when it was written.
- **`v31-phase-gap-matrix.md` is a current-state baseline, never a design.** It
  says what exists. It does not say what to build.

Verified evidence figures, artifact hashes and the historical `FOLYNTA` label are
**not** rewritten by any masterplan revision.

This file is short on purpose. It carries only the rules that bind. Detailed
design lives under `docs/architecture/`, `docs/audit/` and
`design-system/tavonel/`.

Every change answers one question first:

> Does this bring TAVONEL closer to a system that continuously compiles
> organizational knowledge an AI can trust?

If not, it goes to backlog.

---

## North Star

**TAVONEL is the Knowledge Compiler for AI.**

Compile fragmented organizational knowledge into trusted, temporal, traceable
context for AI and agents.

**Never regress into:** a PDF converter, a generic RAG builder, a generic graph
viewer, an OCR API wrapper, an "upload PDF → chat" service.

**The moat is the combination, not any one feature:** evidence provenance ·
stable identity · document-semantic lineage · temporal integrity · dependency
graph · incremental recompilation · fail-closed validation · interoperable
outputs.

**The v4 objective function is Minimum Cost to Trusted Output.** Not the best
model, not the cheapest output, not the highest average benchmark. The question
for every routing, recovery and execution decision is: *what is the least
expensive path that reaches the required trust level?* Models are replaceable
workers. The router, the failure classification, the identity, the lineage and
the evidence are the product.

---

## Protected Core

These are not replaced without a same-condition no-regression benchmark. Not
rewritten "more cleanly", not refactored across a version boundary, not swapped
for a library:

`akc_cir.inspection` · `akc_cir.recovery_policy` · `akc_cir.reconciler` ·
`akc_cir.identity` · `akc_cir.semantic_diff` · `akc_cir.dependency` ·
`akc_cir.recompilation` · `akc_cir.world_state` · tested entity/authority/temporal
logic · every evidence artifact and claim receipt.

**Every replacement anywhere goes through the same ladder:**

    compatibility contract → shadow → benchmark → canary → rollout → deprecate

No big-bang rewrite. The legacy path stays authoritative until a benchmark says
the new one is not worse.

**"Built" is not "proven".** Almost everything in this repository is
`IMPLEMENTED_NOT_PROVEN`: tests show the code does what its author intended, and
nothing shows the threshold is right. No threshold here is calibrated —
`CalibrationTable.calibrated` is `False` and refuses to be set true without
naming a corpus. Do not present an uncalibrated threshold as a measured result.
Status vocabulary and the current per-module classification live in
`docs/audit/V4_MIGRATION_MATRIX.md`.

---

## Evidence

The campaign that backs every public number is
`docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md`. The claims pack
(`docs/evidence/folynta-public-claims-pack.json`) is generated, never edited.

- **Never publish a numerical claim without a receipt.** Every claim binds to an
  artifact under `docs/evidence/artifacts/` by sha256, and the generator refuses
  to emit a claim citing a git-ignored file or a path without a hash.
- **Never call 99.98% completion "accuracy."** It is the share of documents that
  produced output.
- **Every rate carries its denominator.** 99.94% recovery is measured over the
  1,797 documents that actually failed, not over the corpus.
- **The 36.9% low-quality-scan row stays.** Weaknesses are published, not
  averaged away.
- Competitor leaderboard rows are **quoted**, never claimed as reproduced.
- The $1.23/1,000 pages is raw GPU cost and never sits beside a retail price.
- A failed hypothesis is evidence. Blind quality detection is published as
  *not supported*.

**FOLYNTA is the internal campaign name; TAVONEL is the public brand.** Artifact
filenames, hashes and receipts keep their FOLYNTA names — renaming them would
break reproducibility. Public copy says TAVONEL.

---

## Implementation

- TypeScript strict. Python typed. `ruff` and `mypy` clean.
- Migrations single-head. `tests/unit/test_migration_graph.py` enforces it.
- Tests required, including the failure path.
- **No silent fallback.** A component that cannot do its job says so.
- **Fail closed on integrity violations.** Broken knowledge must fail visibly
  rather than look successful. A vault with an unresolved link is not emitted.
- Never invent data to satisfy a schema: no fabricated bbox, no inferred date
  stored as fact, no claim without a source.

### Runtime invariants

- **Object storage is immutable artifact truth. PostgreSQL is workflow,
  identity, permission and publish truth.** Neither substitutes for the other.
- **Delivery is at-least-once, so every consumer is idempotent.** A worker ACKs
  only after its output is durable and a receipt is committed — never before.
- **Every document is hostile data.** Parsing models get no tools, no broad
  credentials and no outbound network.
- **Never route on a scalar blind quality score.** The campaign published that
  hypothesis as *not supported*; the inspector deliberately has none.
- **Separate operational failure from semantic failure.** A pod that died and a
  model that was wrong are different problems with different recoveries.
- **Never infer capability from a model's name.** Vision, language and format
  support come from registry capability evidence or they do not exist.
- **Never auto-resolve an authoritative conflict on insufficient evidence**, and
  never expose partial world state as ACTIVE.
- **Never let an ACL revoke wait for a background reindex.**
- **Never expose route features, scores, thresholds, prompts, the cost matrix or
  the Router Outcome Dataset** in a public DTO or a client bundle. Public and
  internal DTOs are separate types, not the same type with a filter.
- **No Kubernetes, Kafka, Neo4j or custom foundation model** without a measured
  bottleneck and an ADR.

### Stop the line

Halt new feature work and fix, in this order, before anything else ships:
cross-tenant leak · unsupported claim published · source or evidence hash
mismatch · world-state partial publish · permission revoke past SLO · runaway
GPU/API spend · historical evidence overwritten · unlicensed component in
production · catastrophic benchmark regression.

---

## Frontend

The agent contract for UI work is `AGENTS.md`. The visual source of truth is
`design-system/tavonel/DESIGN_MASTER_V3.md`; where it conflicts with
`design-system/tavonel/decision.md`, decision.md wins.

- Motion encodes meaning. Decorative animation is not shipped.
- No generic AI visual cliché: no glowing brain, no purple neon, no random
  particles, no stock robot, no meaningless orb.
- Product UI is the marketing asset. Real Evidence Inspector, Change Center,
  Timeline — not illustrations of them.
- Reduced motion, WebGL fallback and mobile are part of done, not follow-ups.
- A page is not complete because it renders. It is complete after desktop,
  mobile, performance and reduced-motion QA.

### 3D — reinstated 2026-08-09

Decision G-C scrapped TIER 1 3D on 2026-08-07 and removed `three`,
`@react-three/fiber` and `@react-three/drei`. **The owner reversed that on
2026-08-09** in favour of the masterplan's §26–30 cinematic hero. R3F returns.

Two consequences that must not be quietly skipped:

1. **The §22 script budget will move.** The ratchet at 200,000 bytes is a
   measurement, and the rule that it is never raised to make a build pass still
   holds. A deliberate change to what the page contains means the ratchet is
   **re-derived from a new measurement**, recorded with the decision that
   authorized it. That is a different act from raising it to go green, and the
   commit must say which one it is.
2. **G-C's other half stands.** The hero is still the working drop zone; the
   cinematic is what surrounds it. `structara-webgl-scene.tsx` and its infinite
   parallax were removed for violating §10.4 and do not come back.

No paid 3D dependency. No GetLayers or Spline scene as a required dependency.

---

## Self-approval

The session that implements does not approve its own result. Blind category
tests and forced comparison judgements are made by a person.

An implementation agent cannot approve its own production-critical work. Every
phase runs implementer → deterministic CI → independent reviewer → evidence and
security audit → release. A phase is done only when code exists, tests *and
failure paths* pass, telemetry exists, security and tenant checks pass, evidence
is produced where relevant, docs and ADR are updated, rollback is tested, the
phase report names what is still missing, and the repository is green.
**Code presence is not completion.**

## What is not an agent's call

Ask the founder; do not decide and do not infer from the masterplan:

- patent filing and research publication timing (`docs/ip/V4_DISCLOSURE_REGISTRY.yaml`)
- what a public claim says, and whether evidence supports it
- customer data consent, pilot contract terms, pricing
- irreversible production or destructive actions
- missing secrets and payment credentials

Everything else the v4 document already decided. Do not re-ask it.
