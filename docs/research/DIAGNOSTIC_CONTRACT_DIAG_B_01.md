# `DIAG-B-01` — Why selective recompilation degenerates to a full rebuild

*Written 2026-08-12 against `9e3a793`. Registered engineering gap, opened by the
`EXP-0101` result.*

**This is a diagnostic contract. It produces an explanation, not a fix.**
No change to `akc_cir` is authorised by this document, and none may be made
under it. Which cause is real decides what a fix would even be; choosing a fix
first would mean guessing.

**NOT CLEARED FOR EXTERNAL DISCLOSURE.**

---

## 1. The observation

Across all 660 cases of `EXP-0101`, every arm that goes through
`akc_cir.semantic_diff` produced `mean_rebuild_fraction = 1.0000`. Every
artifact was rebuilt in every case, including the four mutation classes where no
unit's text changed at all.

The prior-art baseline, which does not route through that path, produced
**0.0800** on the same manifest.

Selective/full equivalence was 1.0000 for the core-path arms — **and that is the
part most likely to be misread.** Equivalence held because nothing was ever
carried over. A rebuild-everything plan is trivially equivalent to a full
rebuild. It is not evidence that the diff was right.

Receipts: `research/experiments/EXP-0101/metrics/summary.json`,
`tables/headline-metrics.md`, and the caveat section of
`tables/gate-adjudication.md`.

## 2. The claim discipline this forces

**Three permitted claim states, and no others.** Anything written about selective
recompilation — disclosure text, claim support, public copy, benchmark
commentary — uses one of these words and means it:

| state | what it asserts |
|---|---|
| `IMPLEMENTED` | the mechanism exists in code |
| `DEMONSTRATED` | a narrow recompilation benefit is proven |
| `NOT YET DEMONSTRATED` | neither of the above has been shown end to end |

**Current state: `NOT YET DEMONSTRATED`.** `plan_recompilation`, `impact_of`,
`verify_equivalence`, `ArtifactState` and the dirty-set machinery are
`IMPLEMENTED` — they exist, are tested, and do what their authors intended.
Nothing measured shows they reduce work in the assembled pipeline, and one
measurement shows they did not on this fixture. `DEMONSTRATED` is unreached.

**This is linked to the IP track and gates Family B §5.** The §5 consistency
pass happens **after** this diagnostic, and the IP track is holding for it. A
document that claims `DEMONSTRATED` on the strength of `IMPLEMENTED` is the
failure this section exists to prevent.

Note the direction of the opposite error too. The finding is **not** "selective
recompilation does not work". It is "it has not been shown to work end to end,
and one measurement on a synthetic fixture says it did not". Over- and
under-claiming are both wrong here.

**Do not settle the cause before the diagnostic runs.** §3's four candidates are
decomposed by read-only counterfactual, and no cause is named in any document
until §5 attributes shares to them.

## 3. Candidate causes — exactly one question to settle

The diagnostic determines which of these four is the cause, or which combination
and in what proportion. It does not assume.

### C1 — Evidence identity design

Is the design of evidence identity itself the problem: that an evidence id is
required to be a *location*, so a unit that did not change but was re-rendered
necessarily gets a new one?

### C2 — Version-scoped evidence id

`evidence_id()` requires a `document_version` prefix (`identity.py:150`, and the
`dv_` check at `identity.py:164`). Two versions of an unchanged unit therefore
**cannot** share an evidence id. `diff_documents` compares
`counterpart.evidence_id != incoming.evidence_id` at `semantic_diff.py:433` and
emits `EVIDENCE_MOVED` whenever they differ — which, given the above, is always.

This is the cause the observation most obviously fits. It is listed second, not
first, because "most obviously fits" is where a diagnostic goes wrong.

### C3 — Conflation of semantic identity with evidence identity

`SemanticChange` carries one `logical_id` regardless of kind, and
`changed_logical_ids` (`semantic_diff.py:195`) collects it from every change
that is not `IDENTITY_UNRESOLVED`. So `EVIDENCE_MOVED` — a statement that a unit
sits somewhere new — contributes to the set that dependency traversal treats as
*changed knowledge*. Is the defect that two different notions of "changed" share
one channel?

### C4 — Dependency invalidation rule

`plan_recompilation` seeds `graph.impact_of(diff.changed_logical_ids)`. Is the
rule itself too broad — should an artifact derived from a unit go stale when the
unit's *anchor* moved but its *content* did not, and is that decision even
representable today?

## 4. Method

Read-only. Instrumentation and counterfactual measurement over the frozen
`EXP-0101` manifest; **no edit to any Protected Core module**, including a
temporary one.

1. **Attribute the changed set.** For every case, partition
   `changed_logical_ids` by the change kind that put each id there. Report what
   share arrives solely via `EVIDENCE_MOVED`. Denominator: all ids in the set.
2. **Counterfactual, computed outside the core.** Recompute the rebuild plan
   from a changed set with `EVIDENCE_MOVED`-only ids withheld, by calling
   `plan_recompilation` with a filtered `SemanticDiff` constructed in the
   diagnostic package. If the fraction collapses, C2/C3 dominate. If it does
   not, C4 is live.
3. **Separate C2 from C3.** Synthesise a pair whose evidence ids are held equal
   across versions — legitimate only where the anchor genuinely did not move —
   and see whether `EVIDENCE_MOVED` stops firing. If the fraction still does not
   fall, the channel conflation (C3) is doing the work independently.
4. **Test C1 against a non-location anchor.** Ask whether an evidence identity
   that is stable under re-render is expressible at all under the current
   scheme, or whether `IDENTITY_SCHEME_VERSION` would have to move. This is a
   design question and its answer is prose plus a worked example, not a number.
5. **Test C4 in isolation.** Hold the changed set fixed and vary only the
   propagation rule, over the same graph.

Every step is paired at document-pair level over the same 660 cases, with
denominators, so the shares are comparable to `EXP-0101`'s.

## 5. Deliverable

`research/experiments/DIAG-B-01/`, §0.10 structure.

- An attribution of the full-rebuild behaviour across C1–C4, **with a share for
  each**, not a single named winner unless the evidence is that clean.
- The counterfactual rebuild fraction under each withholding.
- A statement of which causes are design and which are implementation. They have
  different remedies and different risk.
- **No proposed fix.** A fix is decided after this analysis and goes through the
  Protected Core ladder — compatibility contract → shadow → benchmark → canary →
  rollout → deprecate — and it is a separate authorisation.

## 6. What would falsify the framing

If the attribution shows `EVIDENCE_MOVED` accounts for a minority of the changed
set, the framing in §1 is wrong and the diagnostic says so in those words. The
observation would then be about the fixture — 17 units per document, every one
carrying an evidence id — rather than about the pipeline.

**That outcome is recorded, not buried.** It is the cheapest possible correction
and it is worth more than a confirmed hypothesis.

## 7. Constraints

- **No Protected Core modification.** `akc_cir.{inspection, recovery_policy,
  reconciler, identity, semantic_diff, dependency, recompilation, world_state}`
  are read and called, never edited.
- No production write path. Diagnostic code sits behind an `ABSORB_*`-style flag
  in a package that does not ship, as `packages/absorption` does.
- `docs/evidence/**` untouched. No public claim is derived from this.
- Every number bound to a receipt.

## 8. IP linkage

Ledger entry **`ABS-B-01`**, appended as a note — this diagnostic arose from
that experiment and shares its manifest. It does not open a new entry, and it
does not move `gate_status`.

**Family B §5 is finalised after this diagnostic, not before, and the IP track is
holding for it.** Until then §2 governs what may be written: the state is
**`NOT YET DEMONSTRATED`**, the machinery is **`IMPLEMENTED`**, and
`DEMONSTRATED` is not available.

**Filing and publication timing is the founder's alone.**
