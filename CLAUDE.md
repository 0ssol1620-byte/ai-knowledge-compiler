# TAVONEL — Project Constitution

North Star: `docs/north-star/TAVONEL_FINAL_NORTH_STAR_MASTERPLAN.md`
(sha256 `6876ea389c41ad6b7b2dec47505a18138116531d51d514cab60204458e276619`).

This file is short on purpose. It carries only the rules that bind. Detailed
design lives under `docs/architecture/` and `design-system/tavonel/`.

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
viewer.

**The moat is the combination, not any one feature:** evidence provenance ·
stable identity · document-semantic lineage · temporal integrity · dependency
graph · incremental recompilation · fail-closed validation · interoperable
outputs.

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
