# TAVONEL eval v2 — consolidated report

**Date:** 2026-08-21
**Namespace:** `research/tavonel_eval_v2/` (everything produced here lives inside it)
**Split:** development throughout. No confirmatory split was opened.
**Cost:** GPU seconds 0, paid inference $0, cumulative external spend $0.
**IP gate:** CLOSED. Nothing here was published, uploaded, released or demonstrated.

**Overall status: `PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED`.**

Fixed by founder ruling, 2026-08-22, and binding on every future report of this
programme. `PROVEN` is **not** available as an overall status while P4c-Core
stands at FAIL, the untouched confirmatory split is unopened and no model
endpoint has been executed. Individual protocol verdicts remain what their gates
recorded; the *programme* has evidenced mechanisms and has not established an
endpoint, and those are different claims.

A protocol-level `PASS` means the protocol's own gates were satisfied and nothing
wider. In particular **P0d's `PASS` does not mean source coverage is adequate.**
It means the coverage measurement, the span partition and the fail-closed rule
behaved as the protocol specified. The measured result on natural data is that
**all 26 pairs are `SOURCE_COVERAGE_INCOMPLETE`**, and that stands.

Protocol results, receipts and gate scores are never repaired into passes, and no
threshold, metric or tie policy is changed after a result is seen.

---

## A. What was executed

| step | protocol frozen at | verdict |
|---|---|---|
| INC-V2-001 provenance forensic | — (read-only investigation) | 1 recoverable, 3 quarantined — §C |
| INC-V2-003 impact analysis | after P0b freeze, by design | measured |
| P0b recompilation mechanics | `sha256:e35cde9f…` | **PASS**, 9/9 gates |
| P2 multi-revision lineage | `sha256:3809c14d…` | **PASS**, 5/5 gates |
| P3 failure injection | `sha256:d5fd5379…` | **FAIL**, 5/6 gates |
| P4 retrieval-validity preflight | `sha256:c04d2063…` | **FAIL**, 4/7 gates → STOP |

Every protocol was frozen with a self-hashed receipt **before** its driver
produced a single number. The freeze tool refuses to re-freeze a changed
protocol without an explicit `--amend`.

---

## B. P0 v1 is preserved verbatim, not corrected

`receipts/p0-v1-seal.json` (`sha256:70b25d32…`) seals eighteen files and the
result they produced. It is unchanged by everything that follows.

| P0 v1 finding | preserved as |
|---|---|
| `G_P0_SEALED` | **FAIL / BLOCKED** |
| `G_P0_EQUIVALENCE` | **FAIL** |
| natural pairs artifact-exact | 29 of 30 (25/26 natural, 4/4 control) |
| stale escapes | 2 |

The seal was re-verified at the end of this session: 18 files, no drift.

Two things this programme deliberately does **not** do:

- it does not retroactively reinterpret either gate as PASS;
- it does not describe the pre-existing 28-pair Wikipedia experiment as an
  independent full rebuild oracle. That experiment computed both sides with one
  `artifact_hashes()` in one process. Its correct name is
  **same-implementation full recomputation equivalence**, and it is used under
  that name only.

`receipts/founder-decision-2026-08-21.json` (`sha256:6df86176…`) records the
ruling that isolated v2 development may continue while `G_P0_SEALED` stays
FAIL/BLOCKED. That receipt is explicit that it resolves no drift and re-promotes
no evidence.

---

## C. INC-V2-001 — sealed evidence drift, and what the forensic found

**The finding.** 192 sealed receipts carrying 434 `(path, sha256)` bindings were
verified read-only. 404 bindings match the bytes on disk, 22 name
container-internal paths outside this tree, 4 are superseded by a later receipt
that pins the current bytes, and **4 have drifted with no receipt anywhere
binding the current bytes**. Two receipt self-hashes do not recompute.

Three extractor defects were found and fixed *before* that number was reported —
a document-canonical digest being read as a file-bytes digest, relative bindings
resolved only against the repository root, and any `*_sha256` key treated as a
self-hash. Missing bindings went 173 → 0 and self-hash failures 13 → 2 as a
result. What remains survived those fixes.

**The forensic** (`receipts/inc-v2-001-provenance-forensic.json`) searched, for
each drifted binding, whether the pinned bytes still exist anywhere:

| source | distinct digests indexed |
|---|---:|
| git object database, reachable or not | 4,224 |
| archive members (every `.zip` in the tree) | 687 |
| working tree outside dependency and cache directories | 56,605 |

| file | classification | pinned bytes found |
|---|---|---|
| `EXP-0101/receipts/committed-bytes-verification.json` | `ACCIDENTAL_MODIFICATION` | **yes** — git blob `e3055210` |
| `docs/audit/HOSTILE_REVIEW_2026-08-19.md` | `EVIDENCE_QUARANTINE` | no |
| `docs/repro/TEST_SCOPE_STATUS.json` | `EVIDENCE_QUARANTINE` | no |
| `H1-W6-…/receipts/question-set-v8-dev-2026-08-19.json` | `EVIDENCE_QUARANTINE` | no |

**Not one drift is a documented intentional amendment.** For none of the four
does the repository record a reason for the change.

**Why three cannot be recovered, and what that says.** All three are untracked
and not git-ignored: they exist only as working-tree files that were never
committed. There is no history of them anywhere. The single copy was overwritten
in place. That is a finding about the sealing process, not only about three
files — a receipt pinned the digest of a file that was never committed, so the
seal had nothing durable behind it from the moment it was written.

> A hash binding is only as recoverable as the least durable copy of the bytes
> it names.

**The two self-hash failures** stay unresolved, with one fact added: no version
anywhere in the searched sources has file bytes equal to either declared
`receipt_sha256`. That absence is reported, not read as proof — the declared
value is a canonical digest over the document rather than over the file bytes, so
a byte match was never expected. Both are recorded as
`UNRESOLVED_ENCODING_OR_DRIFT`.

**Nothing was re-sealed, restored, repaired or given a superseding receipt.** The
three quarantined artifacts are cited in support of no claim. The recoverable one
is not quarantined; whether to restore its bytes or write a superseding receipt
is the founder's call. None of the four is an input to any v2 step executed here.

---

## D. INC-V2-002 — the escape class, and the design that addresses it

**The defect.** One natural pair in P0 v1 left two `section:` artifacts stale.
The whole difference between the two revisions of those units is capitalisation.
`akc_cir.identity.normalize_text_for_identity` casefolds, so the change detector
saw nothing; artifact spec v1 stores raw text, so the full rebuild produced
different bytes.

> A selective compiler is only safe when the normalisation its change detector
> compares under is at least as fine-grained as the payload of every artifact
> that derives from it.

**Neither offered repair was adopted.** Global payload normalisation would have
made the escape impossible by discarding case and punctuation from every derived
artifact. Global raw-byte invalidation would have rebuilt everything. Instead,
identity normalisation and invalidation fidelity are separated
(`design/CHANGE_FACETS_AND_ARTIFACT_SENSITIVITY_v1.md`):

- three change facets — `SEMANTIC` (identity-normalised), `LEXICAL` (NFC raw),
  `STRUCTURAL` (explicit path + ordinal);
- per-artifact sensitivity **observed** while the artifact is built, through a
  recording accessor view, rather than declared. A declaration can be silently
  wrong, which is this incident one level up;
- an input fingerprint per artifact, and a carry-forward rule that rebuilds when
  the traversal facets intersect the edge facets *or* the fingerprint moved,
  with disagreements between the two recorded rather than reconciled.

**P0 v1 was not modified.** The design is validated only in a new protocol.

**Measured in P0b.** Four constructed lexical controls (the after revision of a
natural pair with every unit upper-cased, verified at construction to move every
`LEXICAL` projection and no `SEMANTIC` one):

| control | `section:` | `semantic-summary:` | rebuilt |
|---|---|---|---:|
| `lex-git-000-prometheus-configuration` | 74 rebuilt | 74 carried | 74/154 |
| `lex-git-001-prometheus-configuration` | 74 rebuilt | 74 carried | 74/154 |
| `lex-git-002-prometheus-configuration` | 74 rebuilt | 74 carried | 74/154 |
| `lex-git-003-prometheus-functions` | 60 rebuilt | 60 carried | 60/126 |

Under global payload normalisation none of the 282 section artifacts would have
rebuilt and the escape would have recurred; under global raw-byte invalidation
all 588 would have rebuilt.

**Residual risk, unchanged:** a change that no facet projects is still
invisible. Design §8 says so; one development run does not retire it. The
incident stays **OPEN**.

---

## E. INC-V2-003 — P0 ran an identity rule its protocol excluded

`protocols/P0_master_protocol.yaml` §3 fixes deterministic explicit-path
identity and reserves fuzzy identity for P2. `compiler/selective_build.py:195`
calls `diff_documents()`, which constructs a default `LogicalIdentityResolver`
and runs `assign_one_to_one` — global weighted assignment with
`MERGE_THRESHOLD = 0.92`, `NEW_IDENTITY_THRESHOLD = 0.75` and a 0.05 tie band.

Consistent with the data: 8 of 26 natural pairs carried an `UNRESOLVED`
identity, a state the declared rule cannot produce.

**Impact, by single-variable counterfactual**
(`receipts/inc-v2-003-impact-analysis.json`; only the matching rule changes —
same artifact spec, same graph, same `plan_recompilation`, same oracle output on
the full-rebuild side):

| figure | as executed (fuzzy) | counterfactual (deterministic) |
|---|---:|---:|
| pairs with an unresolved identity | 8 | 0 |
| unresolved decisions | 26 | 0 |
| continuation decisions | 1,108 | 1,136 |
| new units | 8 | 6 |
| removed / retired units | 41 | 39 |
| mean rebuilt fraction, natural | 0.2871 | 0.2673 |
| mean work avoided, natural | 0.7129 | 0.7327 |
| unnecessary rebuilds | 56 | 44 |
| rebuild set differs | — | 6 of 30 pairs |
| **equivalence verdicts** | 25/26 + 4/4 | **identical, pair for pair** |
| **stale escapes** | 2 | **2** |

The wrong rule contaminated the identity, unresolved, rebuild-fraction,
work-avoided and unnecessary-rebuild figures. It changed no equivalence verdict,
and it did not cause INC-V2-002 — those two escapes reproduce under the rule the
protocol specified.

---

## F. P0b — recompilation mechanics, PASS

Corpus: 26 natural pairs (22 `git_docs`, 4 `sec_edgar`) + 4 structural controls
+ 4 lexical controls = 34 pairs; 12 lineages.

| gate | result |
|---|---|
| `G_P0B_SCALE` | PASS — 26 natural pairs, 2 families |
| `G_P0B_EQUIVALENCE` | PASS — 34/34 equivalent, 0 stale, 0 engine failures |
| `G_P0B_IDENTITY_SCOPE` | PASS — 0 forbidden symbols, 0 unresolved |
| `G_P0B_SENSITIVITY_OBSERVED` | PASS — observed matched every pre-registered prediction |
| `G_P0B_LEXICAL_DISCRIMINATION` | PASS — 4/4 controls discriminate |
| `G_P0B_STRUCTURAL_DISCRIMINATION` | PASS — 4/4 controls discriminate |
| `G_P0B_FINGERPRINT_AGREEMENT` | PASS — 0 disagreements |
| `G_P0B_ISOLATION` | PASS |
| `G_P0B_COST` | PASS — 0 GPU seconds, $0 |

**Oracle independence** is structural, not asserted: a separate executable,
stdlib-only imports verified by AST scan, launched with `python -I -S` (`-I`
alone is insufficient because `akc_cir` is editable-installed into
site-packages), a `sys.meta_path` guard probed on every run, distinct PIDs,
disjoint output roots, and a comparator that imports neither side. The P0b
oracle re-derives the semantic projection from the protocol's prose; a unit test
confirms it agrees with the named implementation on adversarial samples.

The single `akc_cir` symbol reachable from the P0b engine is
`normalize_text_for_identity`.

**Positive controls matter here.** Sensitivity predictions were registered in the
frozen protocol before the run. Without the four lexical and four structural
controls, a mechanism that never fires would read identically to a clean result
— a defect this programme has shipped before.

---

## G. P2 — multi-revision lineage, PASS (one hypothesis falsified)

8 chains, 94 revisions, 86 steps, horizons 1/2/3/5/10, three arms.

| arm | unresolved | forced continuations | mean rebuilt/step | mean affected-set divergence |
|---|---:|---:|---:|---:|
| A deterministic (reference) | 0 | 0 | 5.30 | 0.0 |
| B global one-to-one | 36 | 0 | 5.98 | 0.045 |
| C forced continuation | 0 | 36 | 5.30 | 0.0007 |

All five gates pass, including equivalence in **every** arm with zero stale
artifacts left behind at every horizon.

| hypothesis | result |
|---|---|
| H4a divergence non-decreasing in horizon | holds in all three arms |
| H4b forced ≥ preserving in divergence | **falsified** |
| H4c downstream equivalence in every arm | holds |

H4b was pre-registered and is reported as falsified. The permitted statement of
that result, and the only one made here:

> On this development corpus, against the explicit-path reference, global fuzzy
> assignment showed a larger downstream affected-set divergence than the forced
> arm — 0.045 against 0.0007.

**This is not a finding that forced continuation is generally more accurate.**
Arm A is an explicit-path reference, not a true semantic-lineage oracle.
Divergence from it is distance from a bookkeeping convention, not error against
ground truth, and a rule that diverges less from that convention has not been
shown to be more correct about anything.

Every B-arm first divergence is `UNRESOLVED_VS_DECIDED`: the assignment
declining to decide where the explicit path decides.

**Boundary.** Arm A is the lineage the documents' own heading paths declare, not
an oracle of true authorship lineage. Divergence from it is not an error rate.

---

## H. P3 — failure injection at the publication boundary, FAIL

17 declared scenarios, 17 executed, 0 reported `NOT_IMPLEMENTED`.

| gate | result |
|---|---|
| `G_P3_COVERAGE` | PASS — 17/17 |
| `G_P3_EXPECTATIONS` | PASS — 0 mismatched |
| `G_P3_POSITIVE_CONTROL` | PASS — healthy admitted, gate-break refused |
| `G_P3_ORDER_INVARIANCE` | PASS — 11 candidates × 120 permutations, decision invariant |
| `G_P3_COST` | PASS |
| **`G_P3_ASSERTIONS`** | **FAIL — A3 on `BUILD_PREDICATE_RAISES`** |

3,000 concurrent reads across 6 threads during 17 activations produced **zero**
mixed-state observations. Every refused candidate left the active reference where
it was. No admission occurred with any declared predicate `NOT_REACHED` or
`UNVERIFIABLE`. A repaired candidate that later admitted did not remove or alter
the earlier refusal event.

**The one failure — INC-V2-004.** When a predicate raises, the refusal names the
predicate and carries the exception type, and its `evidence_refs` tuple is empty.
A3 requires at least one evidence reference. Refusing correctly is not the same
as refusing legibly, and the frozen contract asks for both.

A3 was **not** amended to permit an empty tuple, and `knowledge_store.py` was
**not** changed to synthesise one. Whether to carry the artifact under evaluation
or to state in the contract that the exception path has no evidence is a design
decision, so it is not made here. P3 stands at FAIL.

---

## I. P4 — retrieval-validity preflight, FAIL → STOP-V2-001

This is the gate between the programme and its first dollar. It ran on CPU with
BM25 (k1 = 1.2, b = 0.75) over an append-only index holding **both** revisions of
every admitted pair — deliberately the pathological configuration.

| gate | threshold | measured | |
|---|---|---:|---|
| `G_P4_SCALE` | ≥ 200 questions, ≥ 10 lineages | 182 questions, 12 lineages | **FAIL** |
| `G_P4_DETERMINISM` | reversed insertion order reproduces every score | exact | PASS |
| `G_P4_TIE_CEILING` | tie rate ≤ 0.10 | **0.846** | **FAIL** |
| `G_P4_RETRIEVABILITY` | retrievable@10 ≥ 0.90 | **0.346** | **FAIL** |
| `G_P4_SEPARATION` | ≥ 0.90 on Q1 | 0.900 | PASS |
| `G_P4_CONTROL` | ≥ 0.95 on C1 | 1.000 | PASS |
| `G_P4_COST` | 0 GPU seconds, $0 | 0, $0 | PASS |

**What this establishes, at the strength the evidence supports.** The P4
question construction is **unfit for measuring the endpoint**: queries built from
the period of report and a heading path, scored against a body-only BM25 index,
put the oracle-current unit in the top ten on 34.6% of questions, with 154 of 182
ending in an exact top-score tie.

**What it does not establish is that the representation is adequate.** Separation
on Q1 is 0.90 — the two revisions receive different scores — but wrong-revision
dominance is **0.32**, so on roughly a third of revised units the superseded
revision strictly *outranks* the current one. A representation that orders two
revisions in the wrong direction is not shown adequate by the fact that it orders
them at all. An earlier draft of this report said the fault was "question
construction, not representation"; that overstated what the numbers carry, and it
is corrected here.

P4b separates targeting from revision selection for exactly this reason — P4
could not tell the two failures apart.

**Consequence, per the frozen protocol:** STOP. No model arm, no spend request,
no GPU, and no threshold relaxed after the fact. Rebuilding the question set
means a new protocol and a new cohort.

`wrong_revision_dominance` on Q1 is 0.32 — under this representation, roughly a
third of revised units have their superseded revision strictly outrank the
current one. That is exactly the endpoint the programme exists to measure, and it
is recorded here as an observation about BM25 on this corpus, not a claim about
retrieval in general. It is also the reason the separation figure above cannot be
read as a clean bill of health for the representation.

---

## J. Tests

`python -m pytest research/tavonel_eval_v2/tests -q` → **18 passed**.

- `tests/test_p0_findings.py` (5): case-only invisibility to the identity
  normaliser, reproduction of the two escapes, reorder discrimination, the oracle
  import guard actually firing, oracle determinism.
- `tests/test_p0b_and_boundary.py` (13): facet projection on case-only / rewrite
  / reorder edits; observed sensitivity per builder; the INC-V2-002 case at unit
  level (raw artifact rebuilt, semantic one carried, state still equal to a full
  rebuild); no fuzzy-identity symbol imported by the P0b engine (checked through
  the syntax tree, since the module's prose legitimately names one); the oracle's
  prose-derived semantic projection agreeing with the named implementation;
  admission requiring predicate *presence*; `NOT_REACHED`/`UNVERIFIABLE` never
  admitting; a refused candidate leaving the active reference in place; a stale
  compare-and-swap refused.

---

## K. What this evidence does not support

- **Nothing here is confirmatory.** Every result is development split. The
  untouched confirmatory split was not opened.
- **Nothing here is an efficiency result.** The P0 report's timing section was
  corrected during the run: the selective implementation computes the full after
  state in order to source rebuilt values, so selective-versus-oracle wall time
  is not a comparison. Only structural counts (rebuilt sets, carried sets,
  work-avoided fractions) are valid, and those carry INC-V2-003 where identity
  is involved.
- **P0b's pass is one run on one corpus** of 34 pairs and 12 lineages, mostly
  developer documentation. It does not retire INC-V2-002.
- **P3 makes no claim of crash atomicity** — no process is killed — and none
  about a distributed store, a database or a consensus protocol. The injection
  matrix is a declared list; its completeness is not established.
- **P4 says nothing about a dense or hybrid representation**, which was not run,
  and nothing about answer correctness, since no model was executed.
- **The pre-existing 28-pair Wikipedia result** is same-implementation full
  recomputation equivalence. It is not an independent full rebuild oracle and is
  not cited as one.
- **No published number is asserted to be wrong** by any incident in this
  programme.

---

## L. Open, and awaiting a decision that is not an agent's to make

| # | item | needs |
|---|---|---|
| 1 | `EXP-0101/receipts/committed-bytes-verification.json` | restore the pinned bytes from git blob `e3055210`, or write a superseding receipt. Both are irreversible acts on sealed evidence, so neither was done |
| 1b | 3 quarantined artifacts whose pinned bytes are gone | a ruling on how to record evidence whose bytes no longer exist anywhere, and whether the two generated ones should be regenerated under new receipts |
| 2 | Two W6 question-set receipt self-hashes | whether they were sealed under a different canonical encoding — a documentation gap — or drifted |
| 3 | INC-V2-002 residual | a change no facet projects is still invisible; whether a fourth facet is warranted |
| 4 | INC-V2-004 | carry evidence through the exception path, or state in the contract that it has none and why |
| 5 | P4 question construction | a new protocol and a new cohort; the current question set cannot discriminate arms |

**No GPU or paid inference was used and none is requested.** The frozen P4 gate
did not pass, so the precondition for a spend request has not been met. The next
step on the retrieval track is a rewritten question set under a new protocol, at
$0.

**IP gate remains CLOSED.** Nothing in `research/tavonel_eval_v2/` was published,
uploaded to arXiv, pushed to a public repository, released as a benchmark or
dataset, or demonstrated.

---
---

# Part 2 — executed under the founder rulings of 2026-08-21

Order as directed: `INC-V2-005 evidence plumbing → INC-V2-001 disposition →
coverage-completeness/UNKNOWN control → P3b → P4b`. CPU only. GPU seconds 0,
paid inference $0, cumulative spend $0. IP gate CLOSED throughout.

**Part 2 status: `PARTIAL`.** Two new protocols passed, one refused. Nothing in
Part 1 was amended, re-scored or re-run.

| step | outcome |
|---|---|
| INC-V2-005 immutable receipt plumbing | built; needed within the hour |
| INC-V2-001 disposition | 1 binding restored, 3 permanently quarantined, 2 self-hashes held |
| P0c coverage completeness | **PASS**, 9/9 gates — and it found `INC-V2-006` |
| P3b refusal legibility | **PASS**, 7/7 gates |
| P4b retrieval validity | **FAIL** on `G_P4B_B_LINEAGE` → `STOP-V2-002` |

---

## M. INC-V2-005 — an evidence run destroyed an evidence run

The forensic tool wrote to a fixed path. Two runs completed. The second
overwrote the first, and the first no longer exists.

The judgements agreed, which is not the point: **no receipt can be shown for the
first run**, so the correct statement is that *the surviving run produced a
reproducible judgement*, not that two receipts reproduced byte-identically. The
earlier claim of two-run reproducibility is withdrawn.

**The plumbing** (`tools/evidence.py`). Every receipt now carries a run-specific
immutable filename, its own content hash, a run id, a timestamp, and the digests
of the tool and the protocol behind it. `write_immutable` opens with mode `"x"`
and **has no force flag** — the only reason to want one is the failure it exists
to prevent. `receipts/latest/<stem>.json` is a pointer whose body says it is not
evidence and which carries a path and a digest, never a finding.

Receipts written before it keep their paths: relocating evidence to prevent
evidence from being relocated is the same act. All 21 were pinned by digest in an
immutable register instead, which makes a later overwrite **detectable** rather
than impossible — and the register says so rather than implying the gap is
closed. One tool cannot migrate at all: `verify_sealed_evidence.py` is inside the
P0 v1 seal, so its runs are wrapped in an immutable envelope instead.

**It earned itself immediately.** `INC-V2-007` — a conformance defect in P4b —
is a claim that can be checked only because both P4b runs survive.

---

## N. INC-V2-001 disposition

**Restored, one binding.** `EXP-0101/receipts/committed-bytes-verification.json`.
The current bytes were snapshotted inside this namespace **first** — restoring is
what destroys them — then the file was rewritten from git blob `e3055210`.

| | |
|---|---|
| before | `sha256:f4831788…`, preserved at `forensic_snapshots/INC-V2-001/…pre-restoration` |
| after | `sha256:287003fa…` |
| pinned by `receipts.json` | `sha256:287003fa…` |
| binding verifies | **yes** |
| superseding receipt written | **no**, per the ruling |

The drift was a regeneration against a later commit: the pinned bytes attest 25
of 25 receipts at `82ca6c4`, the bytes found attest 27 of 27 at `e804a47`. Both
GREEN. The later attestation is the *more complete* one, which is why its bytes
are kept as forensic material rather than discarded — but it is not what was
pinned. Sealed-evidence verification re-run afterwards: matching bindings
404 → **405**, drifted 4 → **3**. Verdict stays FAIL, as it must.

**Permanent historical evidence quarantine, three artifacts.** Pinned bytes exist
in no source on this machine. These bindings cannot be re-established and no
future artifact may be presented as the evidence the old receipts described.
Binding rule, applied: `old unrecoverable artifact != regenerated artifact` — a
generator may be re-run, its output takes a new artifact id, a new version and a
new receipt, and inherits nothing. Nothing was regenerated.

**`UNVERIFIED_SELF_HASH / EVIDENCE_QUARANTINE`, two receipts.** Held until the
canonicalisation recipe is demonstrated. **No encoding was guessed.** Trying
encodings until one reproduces the digest would manufacture the provenance rather
than establish it — the artifact would carry a recipe chosen by its own answer.

`INC-V2-001` stays **OPEN**. One of six items is repaired.

---

## O. P0c — coverage completeness, PASS, and a real finding

Protocol `sha256:733deaf2…`, frozen before the run. 43 pairs, 43 equivalent, 0
stale, 9 of 9 gates.

**No fourth facet**, per the ruling. A facet covers one more thing and leaves the
same open edge behind it. What was added is an invariant over the model already
there:

> every input access a builder makes is attributed to a known facet, or the
> artifact cannot prove its coverage and may not be carried forward

Access is recorded as a **(field, facet)** pair. An access to a field the
projection map does not name is recorded `UNCLASSIFIED` and **returns its value**
rather than raising — refusing it would let a builder be written around the
check. An artifact that read *nothing* is unproven too: it cannot be shown
insensitive to its inputs, only shown not to have looked.

A projection-completeness repair came with it: P0b attributed a `heading` read to
`STRUCTURAL` while P0b's `STRUCTURAL` projection was not a function of `heading`.
P0c's is. Declared before the run; measured after: **zero rebuild-set differences
across all 34 shared pairs**, matching the prediction. P0b is not amended.

| gate | result |
|---|---|
| `G_P0C_ATTRIBUTION` | PASS — no production builder made an unattributed access |
| `G_P0C_CARRY_BAN` | PASS — no coverage-unproven artifact carried, on any pair |
| `G_P0C_PROBE_FIRES` | PASS — 3/3 probe controls refused |
| `G_P0C_DIAGNOSTIC` | PASS — 3/3 positives fired, 0/3 negatives |
| `G_P0C_NO_GLOBAL_REBUILD` | PASS — no proven-coverage artifact rebuilt on a diagnostic |
| `G_P0C_EQUIVALENCE` | PASS — 43/43, 0 stale |
| `G_P0C_ISOLATION`, `G_P0C_SCALE`, `G_P0C_COST` | PASS |

### INC-V2-006 — the diagnostic found something on its first natural corpus

The pre-registered prediction was that no natural pair would fire
`UNCLASSIFIED_SOURCE_CHANGE`. **Two did**, and the protocol said in advance that
this would be reported as a finding about the canonicaliser.

| pair | what changed in the raw source |
|---|---|
| `rust-lang/book` ch04-01 | an HTML comment: `Old heading` → `Old headings`, twice |
| `kubernetes/website` deployment.md | a Hugo shortcode target: `workload-resources/deployment-v1` → `apps/deployment-v1` |

Both are real adjacent commits. In both, **every canonical unit is
byte-identical**.

The second one matters: **that is a link destination**. The canonicaliser strips
shortcodes, so the compiled knowledge holds neither the old target nor the new
one, and nothing downstream can tell that the document now points somewhere else.

**It is not an equivalence failure** — the full rebuild sees the same units and
produces the same artifacts, so carrying forward was correct. **It is a coverage
failure at the canonicaliser**, one stage earlier than anything P0b or P0c
measure. The selective compiler cannot invalidate on a difference that never
reaches it.

Nothing was changed to make it go away: the canonicaliser was not taught to emit
shortcodes, and the diagnostic was not escalated into a rebuild that would have
cost full price to produce identical artifacts.

**2 of 26 natural pairs, both `git_docs`, one development split. No rate is
claimed.**

---

## P. P3b — refusal legibility, PASS. P3 v1 still FAIL.

Protocol `sha256:77de9cbe…`, frozen before the run. 19 scenarios, 13 refusals,
7 of 7 gates. New subject module; `knowledge_store.py` is byte-unchanged and P3
v1's FAIL is not re-scored.

**The contract was not weakened.** A3 is carried over verbatim — the same
sentence that failed in P3. What changed is where the evidence comes from: **a
predicate no longer supplies the evidence for its own failure.** Each predicate
declares the part of the candidate it evaluates over, and the framework resolves
that domain to concrete references *before* calling it. A predicate that raises
on its first line still produces a refusal carrying what it was about to read.

| | P3 v1 | P3b |
|---|---|---|
| `BUILD_PREDICATE_RAISES` evidence refs | **0** | **9** |
| reason code | `RuntimeError` | `PREDICATE_RAISED:RuntimeError` |
| candidate state digest | absent | present |
| evaluation event id | absent | present |
| exception message / traceback | none | none |

**Message and traceback stay unrecorded**, deliberately: a message can carry a
document fragment, a path or a credential from whatever the predicate was
reading. To make that testable rather than asserted, the injected predicate
raises with a message containing a fake secret and a fake path, and assertion A7
fails if any of it reaches a record. None did.

Two scenarios were added at the places a naive repair falls back to an empty
tuple. `RAISE_ON_EMPTY_DOMAIN` — a predicate raises while its domain resolves to
nothing — still yields a reference. `RAISE_IN_EVERY_POSITION` — each of the five
predicates made to raise, first and last in the conjunction — 10 of 10 satisfied
the full field contract, with one distinct reason code across all of them.

The requirement is **enforced by the type**: constructing a refusal with no
evidence raises, except for the predicates whose evidence is the pointer itself,
named explicitly. `G_P3B_STRUCTURAL_ENFORCEMENT` demonstrates both halves in the
run — without it, this could have passed because no scenario happened to produce
an empty refusal, which is exactly what "no failures observed" meant for the four
P3 assertions that did hold.

---

## Q. P4b — FAIL → STOP-V2-002. No spend request.

Protocol `sha256:a526fac2…`, frozen before any score. 312 questions, 12 lineages,
1,753 indexed units, $0.

| gate | threshold | measured | |
|---|---|---:|---|
| `G_P4B_SCALE` | ≥ 200 q, ≥ 10 lineages | 312 / 12 | PASS |
| `G_P4B_DETERMINISM` | reversed order reproduces every score | exact | PASS |
| `G_P4B_A_TIE` | ≤ 0.10 | **0.000** | PASS |
| `G_P4B_A_RETRIEVABLE` | ≥ 0.90 | **0.968** | PASS |
| `G_P4B_A_TOP1` | ≥ 0.60 | **0.792** | PASS |
| `G_P4B_B_LINEAGE` | ≥ 0.80 | **0.141** | **FAIL** |
| `G_P4B_B_UNIT` | ≥ 0.75 | 0.914 | PASS |
| `G_P4B_CONTROL_ARM` | ≥ 0.99 | 1.000 | PASS |
| `G_P4B_COST` | 0 GPU seconds, $0 | 0, $0 | PASS |

**Stage A: targeting is fixed.** P4's 0.346 becomes **0.968** inside a lineage,
with a zero tie rate and 0.792 exact-first. The fielded index puts the fields a
query names into the index instead of leaving them absent from a body-only one.
This replaces P4's representation; it does not rehabilitate it.

**Stage B: routing does not work, for two reasons at once.** `lineage_at_1_B` is
0.141 against a 0.80 bar. A diagnostic receipt — **explicitly not a gate result,
and it changes no verdict** — separates the causes and finds both:

1. **Cohort granularity.** 26 natural pairs come from only **12** distinct source
   documents; 21 pairs share a document with another pair. Two revision pairs of
   the same file are identical in title, type, heading path and heading, so no
   permitted question can route between them.
2. **The method too.** The same measure at source-document granularity is
   **0.718** — still under 0.80. Granularity is not the whole story, and that is
   stated so the fix is not mistaken for a pass.

### Predictions, scored

| prediction | outcome |
|---|---|
| a fielded index fixes targeting | **held** — 0.346 → 0.968 within lineage |
| `LEXICAL_ONLY` near chance on revision selection | **falsified** — 0.690 current / 0.241 superseded / 0.069 undecided |
| SEC routing harder than git | **falsified in the opposite direction** — SEC 0.611, git 0.112 |

The SEC reversal shares the routing failure's cause: SEC titles carry a ticker and
a CIK, which discriminate; seven git documents contribute three pairs each with
byte-identical titles.

`LEXICAL_ONLY` picking the **superseded** revision on 24% of revised units against
`COMPILED_CURRENCY` at 100% is the contrast this programme exists to measure —
but it rests on **58** Q1 questions on one development corpus, and no rate is
claimed. No model was executed; both arms are index policies over the same
scores.

### INC-V2-007 — the first P4b run did not implement its own protocol

Corrected **after seeing a FAIL**, which is when a change to measurement code is
most suspect, so the justification is the frozen text rather than the result. The
protocol states stage A's measures over *units* and forbids breaking ties by
document id; the first implementation scored *documents* and read ranks off a
key-sorted list. No threshold, weight, tie policy, question construction or gate
predicate changed, and the protocol digest is identical for both runs.

The fix moved `lineage_at_1_B` **down** — 0.314 → 0.141 — by removing credit the
first run had been taking from incidental ordering. A correction that only ever
helps is the one to distrust; this one did not. FAIL either way.

Both runs' receipts exist because of the plumbing built two hours earlier.

---

## R. Open as of Part 2 (superseded by section W)

| # | item | needs |
|---|---|---|
| 1 | 3 permanently quarantined artifacts | how to record evidence whose bytes are gone; whether the two generated ones get new ids and new receipts |
| 2 | 2 `UNVERIFIED_SELF_HASH` receipts | a demonstrated canonicalisation recipe, not a guessed one |
| 3 | `INC-V2-006` | should link targets and directive parameters be first-class canonical units, or an out-of-band source-digest record? A scope decision about what counts as knowledge |
| 4 | `INC-V2-002` residual | narrowed, not closed: attribution is measured against the projection map; the map's own adequacy is not |
| 5 | `INC-V2-004` against `knowledge_store.py` | repaired in `knowledge_store_p3b.py`; the v1 module is unchanged and still carries the defect |
| 6 | P4c | new protocol, new cohort: one pair per source document or a title carrying the revision window; SEC titles that separate two filings of the same form and issuer; routing better than 0.718 |
| 7 | two-run reproducibility check | owed on the fixed infrastructure; the original claim is withdrawn |

**No GPU or paid inference was used, and none is requested.** P4b did not pass, so
the precondition for a spend request is not met. The next step is P4c, at $0.

**IP gate remains CLOSED.** Nothing was published, uploaded, pushed to a public
repository, released as a benchmark or dataset, or demonstrated.

---

# Part 3 — executed under the direction of 2026-08-22

Part 2's results are preserved unchanged. `P0b`, `P0c`, `P2`, `P3b` and `P4b`
keep their protocols, receipts and verdicts; nothing in this part re-scores them.
Three things were executed, in the directed order: the reproducibility check owed
by INC-V2-005, source-coverage hardening as a research axis, and P4c on a new
cohort.

Everything below is CPU-only. **0 GPU seconds, $0.**

## S. R1 — the two-run reproducibility check, PASS

INC-V2-005 was opened because a forensic's second run overwrote its own receipt.
The plumbing was rebuilt then; the check that the plumbing works was owed.

The subject is a deterministic fixture — a pure function of a pinned literal
input and its own source, with no clock, no randomness, no environment and no
filesystem read. It is run twice as **separate subprocesses**, because the run id
mixes in the pid and two runs inside one process would not be two runs.

| gate | result |
|---|---|
| both immutable receipts exist, self-hashes recompute | PASS |
| the two receipts are at different immutable paths | PASS |
| same semantic result digest | PASS — `sha256:8f9f9a3e…` |
| identical tool and protocol digests | PASS |
| run two did not modify run one's file | PASS — same sha256 before and after |
| re-using an immutable filename is refused | PASS — `ReceiptExists`, file unchanged after the attempt |
| the `latest` pointer is not evidence | PASS — `is_evidence: false`, no payload field, no result digest |

7 of 7. Receipt `r1-reproducibility-check--20260822T013341Z-683664c5041e.json`.

**What this does not do.** It reproduces a fixture. It reproduces no P0, P2, P3
or P4 result, and the withdrawn INC-V2-005 claim that two independent forensic
receipts had reproduced byte-identically **stays withdrawn** — the first receipt
is gone and no later run recovers it. The frozen protocol also records that
byte-identical receipts are not the target and never could be: the run id and the
timestamp differ by design, so identity is asserted over the *semantic result
digest*, not over the file.

## T. P0d — source coverage, PASS, and the finding it was built to test

INC-V2-006 was recorded in Part 2 as a one-off observation: two Kubernetes
revisions differed in an `api-reference` directive argument that no facet
projection carried. Part 3 treats it as what it is — a **raw-source → canonical-
state coverage gap at the front end**, not a selective-recompilation defect — and
measures it.

Every span of every raw source is classified into exactly one of three states:

- `MODELED` — the span reached the canonical state
- `IGNORED_BY_DECLARED_POLICY` — declared non-semantic in advance, with a written
  justification. HTML comments, front matter delimiters, presentational
  attributes
- `UNMODELED_SOURCE_FACT` — not projectable onto any known facet or fact, and
  **not usable for a downstream CURRENT determination**

Reference destinations are preserved as typed edges rather than discarded:
hyperlink, image, link definition, directive, include, anchor.

| family | documents | granularity | source coverage | modeled | ignored |
|---|---|---|---|---|---|
| git_docs | 44 | characters | 0.7861 | 0.7847 | 0.0014 |
| sec_edgar | 8 | parser events | 0.9794 | 0.2435 | 0.7359 |

The two rows are **not summed**: characters and parser events are different
units. SEC's high coverage is mostly declared-ignored HTML presentation, which is
the honest reading of a filing rendered as a styled document.

Both figures are **upper bounds**. The containment probe that decides whether a
raw span reached canonical state folds to alphanumerics, which is loose in one
direction only: it can say a span *did* reach the canonical state when a stricter
comparison would not. Under a stricter probe the unmodeled share is larger, never
smaller.

Nine gates passed, including three controls: a document differing only in an HTML
comment is `SOURCE_COVERAGE_COMPLETE`, a document carrying a constructed
unmodeled construct is `SOURCE_COVERAGE_INCOMPLETE`, and the partition holds with
zero gaps and zero overlaps.

### The result that matters

**All 26 natural revision pairs are `SOURCE_COVERAGE_INCOMPLETE`, and 12 of them
are pairs P0c independently called equivalent.**

A pair can be equivalent under every known facet *and* have raw source content
that never reached the canonical state at all. So:

> Full-rebuild equivalence does not establish source-faithful correctness. P0c
> proved the selective build agrees with the independent oracle. It did not prove
> either of them saw the whole source, and P0d shows that on this corpus neither
> did.

P0c's and P0b's results are unchanged. P0d does not contradict them; it measures
a stage upstream of what they measure. Receipt
`p0d-source-coverage--20260822T014018Z-fd08c210d582.json`.

## U. The P4c cohort

P4b's global routing failed partly on cohort construction — 26 pairs from 12
documents, three pairs of one file competing as separate routing targets while
identical in every field a question may name. P4c admits **one revision pair per
source document**, by a rule frozen in `acquisition/sources_p4c.py` before any
retrieval result existed, with a cap of 4 documents per repository, issuer or CFR
part.

| family | documents | source |
|---|---|---|
| encyclopedia_wikipedia | 18 | two most recent revisions, MediaWiki API |
| regulation_ecfr | 19 | two most recent dated versions, eCFR versioner API |
| git_docs | 7 | consecutive-commit pairs, existing acquisition |
| sec_edgar | 4 | amendment pairs, existing acquisition |

48 documents admitted, 10 excluded by the eligibility clause, 4 families.

**DART is blocked.** `opendart.fss.or.kr` answers, but every call returns
`status 010` — an unregistered certification key. A missing credential is a
founder decision, so DART was declared in the frozen acquisition inputs,
attempted at fetch time, and recorded as `BLOCKED_MISSING_CREDENTIAL` with the
API's own response. It was not quietly dropped and not silently substituted;
eCFR and Wikipedia were added to reach four families, and that substitution is on
the record here.

**The CIK is gone from every query.** P4b put ticker and CIK in the same string,
and its SEC routing looked comparatively strong for a reason unconnected to how
anyone asks a question. Machine identifiers remain *indexed* — they are
source-provided — but they are never injected into user intent. Section V records
what that cost.

## V. P4c — Core FAIL, Global PASS. No spend request.

Two endpoints with separate verdicts, **never combined into one number**.
522 scored questions, 47 source documents, 4 families, 2,817 indexed units.
Full detail and the per-family diagnosis are in the ledger at STOP-V2-003.

### P4c-Core — FAIL, 5 of 8 gates

| gate | bar | observed |
|---|---|---|
| `G_P4C_CORE_RETRIEVABLE` | ≥ 0.90 | **0.8621** |
| `G_P4C_CORE_TOP1` | ≥ 0.60 | **0.5441** |
| `G_P4C_CORE_Q1_SCALE` | ≥ 100 | **67** |
| `G_P4C_CORE_TIE` | ≤ 0.10 | 0.0 |
| `G_P4C_CORE_HARNESS` | ≥ 0.99 | 1.0 |

The failure is one family. eCFR reaches 0.641 top-ten and 0.120 top-one against
1.000/0.760 for Wikipedia, 0.966/0.828 for git and 1.000/1.000 for SEC. The
cause is identified rather than guessed: **80.7% of the eCFR questions have a
leaf heading that tokenises to the empty string**, because the heading is an
enumerated paragraph marker — `(a)`, `(3)`, `(c)`. Siblings share the document
title and the parent heading, so under an answer-independent construction rule
the query contains nothing that distinguishes them, and the rank distribution is
correspondingly near-uniform.

That is a limit of question construction against enumerated regulatory text at
this unit granularity, not a property of the representation. **It is not fixed by
relaxing the forbidden list** — taking a token from the body to name the
subsection is the answer leakage the protocol was frozen to exclude, and doing so
after seeing a FAIL would repeat INC-V2-007 without its justification.

Excluding eCFR gives 330 questions at 0.9909 and 0.7909, both above the bars.
**That is a diagnostic decomposition, not a pass.** The gate is defined over the
frozen cohort. P4c-Core stands at FAIL.

### P4c-Global — PASS, 5 of 5

`lineage_at_1` **0.9732** against a 0.80 bar; unit-in-top-ten 0.8563 against
0.75; tie rate 0.0.

P4b's global routing was 0.141. The only thing that changed is the independence
rule. That is confirmation of the P4b diagnosis — the earlier number was
measuring the corpus — and **not** evidence that the method improved, because
nothing about the representation moved. Weights, scorer and tie policy were
carried across unchanged and the ranking implementation was *imported* from P4b
rather than written a third time, which is the fix for the class of defect
INC-V2-007 recorded.

Global's unit retrieval sits within 0.006 of Core's. Opening the whole corpus
costs almost nothing once the cohort is independent; the within-document
targeting is now the binding constraint. That is the reverse of P4b's shape and
is itself a finding.

### Predictions, scored

| prediction | outcome |
|---|---|
| SEC routing looks worse without the CIK | **confirmed** — SEC global `lineage_at_1` 9/18 = 0.50 |
| global is harder than core | direction correct, **magnitude nil** (0.8563 vs 0.8621) |
| `LEXICAL_ONLY` picks superseded at a non-trivial rate | **observed, not claimed** — 18 superseded / 42 current / 7 undecidable of 67 Q1. `G_P4C_CORE_Q1_SCALE` failed, so no rate is stated |
| regulation and encyclopedia differ | **confirmed strongly**, with the cause identified |

`COMPILED_CURRENCY` selected the current revision on 67 of 67. Per the frozen
claim boundary this is a **harness control, not a TAVONEL performance result**,
and it is not quoted as one. The measurement this programme cares about is the
first row of the arm comparison — how often lexical retrieval takes the
superseded revision once the correct unit is secured — and 67 questions is below
the scale at which that rate may be stated.

## W. Open as of Part 3 (superseded by section AA)

| # | item | needs |
|---|---|---|
| 1 | 3 permanently quarantined artifacts | how to record evidence whose bytes are gone; whether the two generated ones get new ids and new receipts |
| 2 | 2 `UNVERIFIED_SELF_HASH` receipts | a demonstrated canonicalisation recipe, not a guessed one |
| 3 | `INC-V2-006` scope | measured in P0d. Whether link targets, directive arguments and include targets become first-class canonical facts — or the coverage gap is accepted and declared — is a decision about what counts as knowledge |
| 4 | `INC-V2-002` residual | narrowed, not closed: attribution is measured against the projection map; the map's own adequacy is not |
| 5 | `INC-V2-004` against `knowledge_store.py` | repaired in `knowledge_store_p3b.py`; the v1 module is unchanged and still carries the defect |
| 6 | enumerated regulatory subsections | not addressable by answer-independent user intent at this unit granularity. A coarser unit for enumerated text, a family-specific intent rule, or accepting the family is out of scope — each changes what the product claims to retrieve |
| 7 | DART credential | `status 010`, unregistered certification key. The family stays absent until a key exists |
| 8 | P4c-Core's remaining gap | after item 6 is decided, a further cohort. `G_P4C_CORE_Q1_SCALE` also needs revisions further apart than adjacent ones |

### Items closed since Part 2

| item | closed by |
|---|---|
| two-run reproducibility check owed by INC-V2-005 | section S, 7/7 gates |
| P4c cohort construction | section U; the independence rule fixed P4b's global failure |

**No GPU or paid inference was used, and none is requested.** P4c-Core did not
pass, so the precondition for a spend request does not exist. GPU 0, paid API 0,
spend $0.

**IP gate remains CLOSED.** Nothing was published, uploaded, pushed to a public
repository, released as a benchmark or dataset, or demonstrated. `docs/ip/` was
not modified.

---

# Part 4 — executed under the founder ruling of 2026-08-22

Part 3's protocols, results and receipts are preserved unchanged. Two things
were done: the status vocabulary was corrected, and the enumerated-regulatory
finding was answered by separating canonical granularity from retrieval
granularity.

**0 GPU seconds, $0.**

## X. Status vocabulary — `PROVEN` withdrawn

The Part 3 summary reported an overall `PROVEN`. That is withdrawn and is not
used again in this programme. The binding overall status is

> `PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED`

because P4c-Core stands at FAIL, the untouched confirmatory split is unopened,
and no model endpoint has run. Individual protocol verdicts are unaffected — a
gate that passed still passed — but a programme that has evidenced mechanisms
has not thereby established an endpoint, and the two claims are different.

The same correction applies one level down. **P0d's `PASS` does not mean source
coverage is adequate.** It means the coverage measurement, the span partition
and the fail-closed currency rule satisfied the protocol. The measured result on
natural data — 26 of 26 pairs `SOURCE_COVERAGE_INCOMPLETE` — is unchanged, is
not softened, and no coverage adequacy threshold is set retroactively. If one is
ever needed, it is declared in a new protocol on data separated from
development.

## Y. The envelope layer — canonical and retrieval granularity separated

None of the three options at the end of Part 3 was adopted. The founder's ruling
keeps fine canonical atoms exactly as they are and adds a second addressing
layer above them.

`§ X.Y → (a) → (1) → (i)` each remain the atom of stable identity, revision
lineage, source evidence and invalidation. What changes is that they are no
longer forced to be the direct target of a natural-language question, which is
what P4c measured failing at 0.120 top-one on eCFR.

A **queryable retrieval envelope** is the structurally determined minimal
self-contained window: a named anchor heading with its own text and its
enumerated descendants. It is a *derived retrieval artifact*, and five
properties make that checkable rather than decorative — each one verified in the
run, not asserted in prose:

| property | how it is held |
|---|---|
| records member logical ids | `member_ids`, checked non-empty for every envelope |
| source evidence traces to child atoms | `evidence()` returns atom records only |
| a member change invalidates the envelope | typed `covers_canonical_atom` edges; 58 affected, exactly 58 invalidated |
| answers return fine atom evidence | every returned record is a canonical atom, none carries envelope text |
| never a source of truth | `authoritative` is `False` on every envelope |

Envelope construction sees document structure and nothing else. No question, no
score and no retrieval outcome enters it, and the rule was frozen in
`P4d_retrieval_granularity.yaml` (`sha256:e3fd7edf…`) before the first envelope
was built.

Retrieval is split into two modes that are never combined: **semantic-intent**,
which searches envelopes, and **citation-addressed**, which routes a
source-native locator straight to the exact atom. A locator is not answer
leakage — it is an address the source publishes and a reader already holds,
naming where to look and never what is written there.

## Z. P4d — Core-Semantic FAIL, Citation PASS. No spend request.

522 questions, 4 families, 2,817 canonical atoms, 2,331 envelopes, mean 5.97
members. The cohort is P4c's, reused unchanged, so the addressing layer is the
only variable that moved. Detail is in the ledger at STOP-V2-004.

### What the layer did

| family | P4c atom top-10 / top-1 | P4d envelope top-10 / top-1 |
|---|---|---|
| regulation_ecfr | 0.641 / 0.120 | **1.000 / 0.891** |
| encyclopedia_wikipedia | 1.000 / 0.760 | 1.000 / 0.822 |
| git_docs | 0.966 / 0.828 | 1.000 / 0.782 |
| sec_edgar | 1.000 / 1.000 | 1.000 / 1.000 |

**The two columns are not the same metric** — P4c targeted an atom, P4d targets
an envelope — so this is not a before/after of one quantity. What it shows is
that the family which could not be addressed at all becomes the best-addressed
one once the addressing layer stops requiring `(a)` to carry semantic intent.
eCFR was the pre-registered place for the effect to appear, and it appeared
there; had it not, the STOP-V2-003 diagnosis would have been wrong.

`atom_recoverable_from_envelope` is **1.0** on every family, against a 0.95 bar.
The pre-registered risk was that a larger window buys retrievability by losing
the atom inside it. On this cohort it did not.

### What failed

| gate | bar | observed |
|---|---|---|
| `G_P4D_NO_LEAKAGE` | 0 | **475 of 522** |
| `G_P4D_Q1_SCALE` | ≥ 100 | **67** |

`G_P4D_Q1_SCALE` is a property of the reused cohort, not of the envelope layer:
adjacent revisions move few units, P4c produced 67 Q1 questions, and P4d inherits
exactly that shortfall by design.

`G_P4D_NO_LEAKAGE` exposed a **contradiction inside the frozen protocol**. §3
lists document identity, document type, anchor heading and parent heading as
permitted intent, and also defines leakage as any query/body token overlap
outside a function-word list. Both cannot hold on real text: a section headed
"Adding dependencies" in the uv documentation contains "dependencies" and "uv"
in its body, so a query built only from permitted sources overlaps its own
answer. Of the 475 failures, 105 leak only anchor-heading tokens and 370 leak
document identity or parent heading. **None leaks an answer span**, which is
what the gate exists to catch.

The predicate was not edited. A gate relaxed after it fails is not a gate.
Resolving this needs a successor protocol that states the leakage check against
the *complement* of the permitted intent sources — declared before results.

### P4d-Citation — PASS, 4 of 4

Source-native locators route to the exact canonical atom on **0.9931** of 577
eCFR citations, 0.0069 ambiguous. `regulation_ecfr` was the only family declared
to have a citation scheme, declared in the tool before the run. This figure is
never mixed into mode A and never raises a semantic retrieval number.

### Predictions, scored

| prediction | outcome |
|---|---|
| eCFR improves most under mode A | **confirmed** — the pre-registered discriminator, and the diagnosis survives it |
| named-heading families move little | **confirmed** — top-10 already saturated; git top-1 moved slightly *down*, which a coarser target can do |
| atom recovery is the binding constraint | **falsified on this cohort** — 1.0 everywhere. The binding constraints were leakage and Q1 scale |
| citation routing is near-exact | **confirmed** — 0.9931 |

### INC-V2-009

The first P4d run ranked over indexed rows instead of logical envelopes, so each
envelope tied against its own superseded revision: tie rate 0.705, 368 tied sets
of size 2. Corrected against frozen §4 and P4c §6. **The correction moved
numbers sharply up** — top-1 0.220 → 0.847 — which is the kind of correction to
distrust, so it rests on the frozen text rather than on its effect: an object
competing against itself is not a retrieval result at any threshold. Both
receipts are preserved and the verdict is FAIL either way.

## AA. Open as of Part 4 (superseded by section AF)

| # | item | needs |
|---|---|---|
| 1 | 3 permanently quarantined artifacts | how to record evidence whose bytes are gone |
| 2 | 2 `UNVERIFIED_SELF_HASH` receipts | a demonstrated canonicalisation recipe, not a guessed one |
| 3 | `INC-V2-006` scope | measured in P0d; whether reference targets become first-class canonical facts is a decision about what counts as knowledge. Hardening continues either way |
| 4 | `INC-V2-002` residual | attribution is measured against the projection map; the map's own adequacy is not |
| 5 | `INC-V2-004` against `knowledge_store.py` | repaired in `knowledge_store_p3b.py`; the v1 module still carries the defect |
| 6 | leakage predicate vs permitted intent | they contradict each other on real text. A successor protocol must state which governs, before results |
| 7 | Q1 scale | 67 against a bar of 100. Needs revisions further apart than adjacent ones, which means a new cohort, not a new metric |
| 8 | DART credential | `status 010`. Blocks nothing; the 4-family evidence stands |

### Items closed since Part 3

| item | closed by |
|---|---|
| enumerated regulatory subsections unaddressable | section Y — the envelope layer; eCFR 0.120 → 0.891 on its own target |
| whether an envelope could stay derived | section Z — all five contract properties checked in-run |

**No GPU or paid inference was used, and none is requested.** P4d-Core-Semantic
did not pass, so no model study is proposed. When it and Q1 scale do pass, the
submission is a written proposal — frozen cohort, baseline arms, exact model,
exact decoding, retrieval and context budgets, TAVONEL arm, full/current oracle
arm, stale/superseded control arm, primary endpoint, statistical test, GPU hours,
estimated cost — presented for approval **before** any GPU runs.

**IP gate remains CLOSED.** Nothing was published, uploaded, pushed to a public
repository, released as a benchmark or dataset, or demonstrated. `docs/ip/` was
not modified.

---

# Part 5 — executed under the founder ruling of 2026-08-22 (P4e)

P4d is preserved in full: its protocol, both execution receipts, INC-V2-009,
STOP-V2-004 and its Core-Semantic FAIL / Citation PASS verdicts. Its leakage
predicate was **not** amended and P4d was **not** re-scored.

**0 GPU seconds, $0.**

## AB. Leakage is provenance, and the enforcement is structural

P4d's leakage gate compared query tokens against body tokens and failed 475 of
522 questions, **none of which carried an answer span**. Every failure was
permitted metadata recurring in prose. Under the ruling of 2026-08-22 the
`permitted_intent_sources` take precedence and answer independence is verified
as *information provenance*, not string matching.

So the check moved upstream, from inspecting the finished string to constraining
what the builder can reach. The query builder's only argument is an
`IntentView`, which

- refuses **at construction** any field outside the five permitted sources — a
  view that accepted the field and then declined to return it would still have
  put it in the builder's memory;
- defines `__slots__`, forbids assignment and is not iterable, so the
  constructor's whitelist is the whole story;
- records every read with its source, and a query field with *no* provenance
  record fails exactly as a forbidden source does.

Lexical overlap is still computed. It is labelled `DIAGNOSTIC_ONLY` and is never
a gate, and re-promoting it would need its own frozen justification.

## AC. P4e — Core PASS, 12 of 12

720 scored questions · 56 documents · 4 families · protocol frozen at
`sha256:a6060213…` before the cohort was scored. Detail is in the ledger.

| gate | result |
|---|---|
| provenance ∈ permitted sources, every field | PASS |
| forbidden-source contribution | PASS, **0** |
| body access by the builder | PASS — one restricted argument, no forbidden name in its AST |
| revision neutrality | PASS — 18 excluded as `INELIGIBLE_INTENT_CHANGED_ACROSS_REVISIONS` |
| negative controls rejected | PASS — both |
| scale ≥250 / ≥40 / ≥4 | PASS — 720 / 56 / 4 |
| Q1 ≥ 100 | PASS, **175** |
| envelope retrievable@10 ≥ 0.90 | PASS, 0.9903 |
| atom recoverable ≥ 0.95 | PASS, **1.0** |
| coverage recorded, determinism, cost | PASS |

The negative controls are what make the provenance gates evidence rather than
assertion: a view handed an `atom_body` field is refused with
`ForbiddenIntentSource`, and a heading that exists only in the current revision
is refused as intent-changed. A gate that cannot be made to fail on purpose has
not been shown to work.

**Lexical overlap is present on 0.9097 of questions** — as high as in P4d, where
the same figure failed 475. Under a provenance definition that is not a finding
about leakage, and the two numbers side by side is the point.

**Wider revision spacing did what it was declared to do.** Q1 went 67 → **175**
against a bar of 100 that was not moved. The only change to pair selection was
the frozen spacing rule, and no clause of it can see a unit count, a score or
the Q1 total. P4d's 67 stays FAIL.

## AD. The finding: the constraint is now source coverage, not retrieval

**20 of 720 questions are `QUESTION_LOCAL_COVERAGE_COMPLETE` — 0.0278.** That is
the entire GPU-confirmatory candidate pool.

**This figure is dominated by the coverage instrument and must not be read as a
property of the sources.** The locality rule was declared before it was applied
and has two branches:

| granularity | families | questions | can grant local completeness |
|---|---|---|---|
| character offsets | git_docs | 87 | yes — 20 granted, 0.23 |
| parser events | wikipedia, eCFR, SEC | 633 | only if the whole document has zero unmodeled facts — in practice never |

**88% of the questions were measured by a rule that can only under-grant**, and
all 20 eligible questions come from one family. Local coverage completeness is
currently only *measurable* on markdown. For HTML and XML the instrument cannot
localise an unmodeled fact to an atom, so it refuses — the right direction for a
fail-closed rule and the wrong basis for a cohort.

P0d is untouched: **26 of 26 document revisions remain
`SOURCE_COVERAGE_INCOMPLETE`.** No revision here is called globally CURRENT and
no result is called source-faithful end-to-end. The two endpoints stay apart:

- **controlled currency** — measurable on locally coverage-complete targets;
- **source-faithful end-to-end** — `NOT_ESTABLISHED`, and never implied by a
  controlled-currency figure.

### Predictions, scored

| prediction | outcome |
|---|---|
| wider spacing raises Q1 | **confirmed** — 67 → 175 |
| overlap stays high and no longer matters | **confirmed** — 0.9097, ungated |
| some questions excluded as intent changed | **confirmed** — 18; zero would have meant the check was not reaching the field |
| question-local coverage far from universal | **confirmed, more so than expected** — 0.0278, with the instrument identified as the dominant cause |

## AE. Model study — proposed, not started

P4e-Core passed every gate, so a model study is eligible to be **proposed**. The
proposal is `MODEL_STUDY_PROPOSAL_2026-08-22.md`: four arms (TAVONEL
compiled-current, same-source full/current oracle, append-only stale-capable,
superseded-control) under one model, one decoding, one retrieval-context budget;
primary endpoint on Q1 questions; McNemar's exact test on the paired outcome;
frozen confirmatory cohort; ≤4 GPU hours; $25 ceiling; five stop rules.

**Its own recommendation is that it not be run yet.** The powered endpoint needs
about 190 eligible Q1 questions and 20 exist, all from one family — a tenfold
shortfall whose cause is the instrument. The proposal's stop rule 5 makes that
explicit: *eligible Q1 below 190 — do not start.*

**No GPU has run. No paid inference has run. Spend is $0** and stays there until
the proposal is approved.

## AF. Open as of Part 5 (superseded by section AM)

| # | item | needs |
|---|---|---|
| 1 | 3 permanently quarantined artifacts | how to record evidence whose bytes are gone |
| 2 | 2 `UNVERIFIED_SELF_HASH` receipts | a demonstrated canonicalisation recipe, not a guessed one |
| 3 | `INC-V2-006` scope | whether reference targets become first-class canonical facts |
| 4 | `INC-V2-002` residual | the projection map's own adequacy is unmeasured |
| 5 | `INC-V2-004` against `knowledge_store.py` | the v1 module still carries the defect |
| 6 | confirmatory cohort size | whether a 20-question study is ever acceptable, and whether the model study waits for the instrument or runs on markdown alone with the narrowing stated |
| 7 | model choice for the study | a parameter of the approval, deliberately not decided in the design |
| 8 | DART credential | `status 010`. Blocks nothing |

### Items closed since Part 4

| item | closed by |
|---|---|
| leakage predicate vs permitted intent | section AB — provenance replaces string matching, enforced structurally |
| Q1 scale | section AC — 175 against a bar of 100, by frozen spacing rather than by selection |

### Next, CPU-only and already scoped

Extend positional locality in the span classifier to HTML and XML so coverage
eligibility becomes measurable on the three families where it currently is not,
then re-derive eligibility on the frozen P4e cohort **without adjusting any
threshold to meet it**. That is ordinary engineering and needs no approval; what
needs a decision is item 6, and only after the new number exists.

**IP gate remains CLOSED.** Nothing was published, uploaded, pushed to a public
repository, released as a benchmark or dataset, or demonstrated. `docs/ip/` was
not modified.

---

# Part 6 — Source Coverage Locality v2, and the decision gate

P4e is preserved in full: `Core PASS 12/12`, 720 questions, Q1 = 175, envelope
retrievable@10 = 0.9903, atom recovery = 1.0, provisional locally-complete = 20.
None of it is re-scored. P0d's classifier was not edited.

**0 GPU seconds, $0.**

## AG. The instrument was finished against fixtures, then sealed, then applied once

The founder's anti-fitting rule governed the order of work, and the order is the
substance: eight development controls with no relation to the cohort were written
first, the instrument was completed against them, `SOURCE_LOCALITY_V2` was frozen
at `sha256:37db14dc…`, the tool digests were sealed, and only then did the
instrument see the P4e cohort — **once**.

Two of the eight controls are a directional pair, gated together because one
alone is satisfiable by an instrument that always refuses or always grants:

- `out_of_range_link_definition` must be INCOMPLETE — the over-grant case v1
  admitted in its own docstring it could miss;
- `unrelated_unmodeled_outside_witness` must be COMPLETE — otherwise the witness
  is the document-level rule wearing a new name.

`out_of_range_link_definition` **failed on the first two implementations**, which
is what the controls were for. It drove both substantive rules: line-scoped
dependency regions (a reference definition's grammar span stops at the first
whitespace inside its target, so following the identifier reached the definition
but not the region it points at) and `UNRESOLVED_INCLUDE_TARGET` (an include
names content not in this source; calling it MODELED because the directive parsed
would be reading the signpost and reporting the road).

## AH. What the witness is

`QUESTION_LOCAL_COVERAGE_COMPLETE` is granted only from an explicit, recorded
`SOURCE_COVERAGE_WITNESS` — the dependency closure over the atom's direct span,
its envelope members' spans, reference and link definitions it uses,
include/directive targets and arguments, anchor and citation dependencies, and
the spans that produced its canonical facts. Every element records the role that
admitted it and why. A closure that existed only inside a boolean could not be
argued with.

For HTML and XML there is now a real source map — `raw interval → parser event →
canonical fact`, built forward from the parser rather than inferred backwards.
`convert_charrefs` is off, because with it on adjacent text and character
references merge into one event whose reported position is the start of the
merged run: an almost-right interval. Where a position cannot be proven it is not
guessed — the span is `LOCATION_UNVERIFIABLE`, cannot support completeness, and
is treated as inside the closure since it cannot be shown to be outside it.

**`LOCATION_UNVERIFIABLE` across the whole cohort: 0.** Position is no longer the
constraint.

## AI. Decision-gate numbers

| | |
|---|---|
| locally-complete total | **77** of 720 (0.1069) |
| **locally-complete Q1** | **5** |
| locally-complete Q1 by family | `git_docs: 5`; wikipedia, eCFR, SEC all **0** |
| Q1 by family | wikipedia 93, eCFR 59, SEC 17, git 6 |
| `UNMODELED_SOURCE_FACT_IN_CLOSURE` | 586 |
| `NO_DIRECT_SPAN_FOR_TARGET_ATOM` | 98 |
| `LOCATION_UNVERIFIABLE` | **0** |
| over-grant control | rejected correctly |
| under-grant control | granted correctly |

**The instrument was not adjusted after these numbers were seen.**

The instrument improved substantially — locally-complete rose 20 → 77 and every
markup event is now located — while the number that gates the model study **fell
to 5**, because eligibility is now measured on Q1 questions through a real
closure instead of a document-level refusal.

The structure matters more than the total: within `git_docs` eligibility is
**5 of 6 = 0.83**, while the other three families contribute **169 Q1 questions
and zero eligible ones**. So the binding constraint is **front-end source
coverage on HTML and XML** — not cohort size, and no longer position.

## AJ. Exact power replaces "about 190"

| n | 50 | 100 | 150 | **190** | 200 | 250 | 300 |
|---|---|---|---|---|---|---|---|
| power | 0.407 | 0.747 | 0.916 | **0.967** | 0.974 | 0.993 | 0.998 |

Exact McNemar, summing over the binomial distribution of the discordant count —
the normal approximation is optimistic at exactly the sizes under argument.
Parameters are protocol values: alpha 0.05 two-sided, effect 0.15 as a difference
in marginal proportions, discordant rate 0.30, target power ≥ 0.95.

Target power is first reached at **n = 173**, so the declared floor of **190 is
genuinely conservative**. It is not lowered. Power at the observed eligible Q1
of 5 is **0.0**.

## AK. Gate outcome — expand, and do not narrow

5 is far below 190, so per the ruling: **no GPU request, no re-fitting, no
markdown-only narrowing, no lowering the floor.** `P4f_cohort_expansion` is
frozen at `sha256:117e5586…`.

P4f records the arithmetic *before* acquisition begins, because freezing a plan
that cannot work and finding out afterwards would waste both the acquisition and
the argument. At the naive overall yield of 0.0286, reaching 190 would need about
6,650 Q1 questions and roughly **2,166 documents** — 38× the current cohort. But
three of four families yield exactly zero, and **expansion multiplies a zero**.
So P4f pairs a 400-document expansion across all four families with a declared
markup coverage workstream, completed before the expanded cohort is scored.

P4f also names the trap it must not walk into: the fastest way to raise
eligibility is to declare more HTML constructs `IGNORED_BY_DECLARED_POLICY`, each
reclassification defensible alone while the aggregate is an eligibility count
engineered to clear the floor. Any addition must be justified on what the
construct means, written down, and declared before the measurement it affects.

## AL. Confirmatory query-builder hardening

`retrieval/isolated_builder.py` runs the builder in a separate interpreter under
`python -I -S`, receiving only a serialised `IntentView` on stdin. Verified: the
child imports **no repository module**, `site` is not loaded, the parent refuses
a forbidden field before serialising it, the child refuses independently when one
is forced past the parent, and the query produced is identical to the in-process
builder's.

This does not revise P4e, whose in-process result stands. It is a stronger
isolation contract for the confirmatory experiment, where "nothing else was
reachable" should not rest on the discipline of every module sharing a process.

## AM. Open, still not an agent's call (superseded by section AT)

| # | item | needs |
|---|---|---|
| 1 | 3 permanently quarantined artifacts | how to record evidence whose bytes are gone |
| 2 | 2 `UNVERIFIED_SELF_HASH` receipts | a demonstrated canonicalisation recipe |
| 3 | markup coverage workstream | whether each HTML/XML construct is modelled as a fact or declared non-semantic. P4f admits both and forbids the third option of granting completeness anyway |
| 4 | `INC-V2-002` residual | the projection map's own adequacy is unmeasured |
| 5 | `INC-V2-004` against `knowledge_store.py` | the v1 module still carries the defect |
| 6 | P4f targets | 400 documents and the family mix are frozen, not immutable. Changing them is fine if deliberate and recorded, never in response to a number |
| 7 | model choice for the study | a parameter of the approval |
| 8 | DART credential | `status 010`. Blocks nothing |

### Items closed since Part 5

| item | closed by |
|---|---|
| HTML/XML positional provenance | section AH — `LOCATION_UNVERIFIABLE = 0` across the cohort |
| markdown interval over-grant | section AG — witness closure; the adversarial control now fails correctly |
| "about 190" | section AJ — exact power; 173 for 0.95, 0.967 at the floor |
| confirmatory builder isolation | section AL |
| what to do below the floor | section AK — P4f frozen |

**No GPU. No paid inference. $0.** The model-study proposal remains submitted and
unapproved, and its own recommendation is still that it not be run: eligible Q1
is 5 against a floor of 190.

**IP gate remains CLOSED.** Nothing was published, uploaded, pushed to a public
repository, released as a benchmark or dataset, or demonstrated. `docs/ip/` was
not modified.

---

# Part 7 — What counts as knowledge in markup

*2026-08-22. `MARKUP_SEMANTICS_V1` and `P4g_cohort_expansion`, both frozen before
any expanded cohort is acquired. No GPU. No paid inference. $0.*

## AN. The fourteen attributes nobody argued for

Part 6 ended with eligible Q1 = 5 and the cause named: 586 `UNMODELED_SOURCE_FACT`
occurrences inside witness closures, not missing positions — `LOCATION_UNVERIFIABLE`
was 0. Independent review then asked a sharper question about the other half of
the classifier, the half that decides what is *not* a fact.

P0d's `_HTML_IGNORED_ATTRS` classified as blanket presentation:

| attribute | what it actually does |
|---|---|
| `colspan`, `rowspan` | change which header a cell answers to |
| `scope`, `headers` | declare header governance and explicit cell association |
| `role`, `aria-*` | change what an assistive consumer is told |
| `alt` | for a non-visual consumer, **is** the content |
| `title` | an accessible name of last resort |
| `lang`, `dir` | change interpretation and reading order |
| `rel` | canonical, nofollow and license assert different things about one URL |
| `media` | applicability, not styling |
| `target` | browsing context, which is behaviour |
| `content`, `http-equiv` | the whole payload of a meta element, and pragma directives |

The source map compounded it: start tags, end tags, entity references and
character references were IGNORED by default. `&#160;` alone appears **15,415
times** in the development corpus and produces a real character in canonical
text.

This is `INC-V2-010`. It is **not** a retroactive FAIL. P0d and
`SOURCE_LOCALITY_V2` keep their results, which stand under the grammar each
declared at the time — that is the only honest reading of them. What must not
happen is that stronger source-faithful evidence inherits the policy silently, so
the repair is forward-only.

## AO. The rule that replaces "is it user-visible prose"

> Can a change to this source construct change the compiled interpretation or a
> downstream artifact?

Nine facets: `CONTENT_LEXICAL` · `STRUCTURAL` · `REFERENCE_LOCATOR` · `TEMPORAL` ·
`AUTHORITY_APPLICABILITY` · `METADATA` · `ACCESSIBILITY` · `VISUAL` ·
`EXTERNAL_DEPENDENCY_EXECUTION`.

Not every canonical source fact is a retrieval knowledge unit. `colspan` and
`rowspan` are recorded as **control facts**: a reader never asks about them, and
an answer can be wrong because of them. Collapsing the two ideas is what let the
old policy discard them — they are not what anyone retrieves, so they looked
like nothing.

**Ignoring now costs three things**: a statement of what the construct means, an
argument that under a *named* consumer it changes none of the nine facets, and
that argument recorded before the measurement it affects. "It is a presentation
attribute" is a category name, not an argument, and it is how fourteen wrong
entries got in. Naming the consumer is what makes the remaining arguments
falsifiable at all.

## AP. The third state, and why the binary was the defect

`UNRESOLVED_SOURCE_FACT` exists so nothing is forced into a fit it does not have.
`class` (65,485 occurrences) and `style` (25,441) are UNRESOLVED, not ignored: an
external rule may hide or reorder the element, and neither MODELED nor IGNORED is
a claim supportable from local source. UNRESOLVED blocks question-local
completeness exactly as UNMODELED does — fail closed. The same applies to
unresolved include targets, script-driven inclusion, and processing instructions
with unknown transformation semantics.

68 attributes and 50 elements declared: **88 MODELED, 12 UNRESOLVED, 18 IGNORED**,
every ignored entry carrying its reason. An undeclared construct resolves to
UNMODELED, never IGNORED.

## AQ. Controls are pairs, in three directions

The claim under test is not "this attribute is classified somehow" but "a change
to it changes the compiled interpretation" — and only a pair shows that. Eight
controls, each two sources differing in exactly one construct, all agreeing:

| control | expected | facet |
|---|---|---|
| `rowspan` changes table association | MODELED | STRUCTURAL |
| `alt` changes accessible content | MODELED | ACCESSIBILITY |
| `lang` changes interpretation | MODELED | METADATA |
| `rel` changes relationship | MODELED | REFERENCE_LOCATOR |
| charref changes canonical text | MODELED | CONTENT_LEXICAL |
| nesting changes structure, **identical visible tokens** | MODELED | STRUCTURAL |
| `class` external dependency | UNRESOLVED | EXTERNAL_DEPENDENCY_EXECUTION |
| `cellpadding` stays ignorable | IGNORED | — |

The last one carries the weight. A policy that called everything meaningful would
pass the first seven and be useless; `G_MS1_THREE_DIRECTIONS` requires a MODELED,
the UNRESOLVED and the IGNORED control to return their expected state in the same
execution.

`G_MS1_UNKNOWN_IS_NOT_IGNORED` failed on its first run. The probe asked about a
`data-` name — which the policy **does** declare, by prefix rule, as UNRESOLVED —
so it tested nothing about undeclared constructs. The probe was changed to one
(`binding`); that is conformance to the frozen predicate, not a weakening of it.
The failing receipt is preserved beside the passing one, and the composite
identity is unchanged, because a probe is not part of the instrument.

## AR. Sealing the policy, not just the tool

`INC-V2-011`: P4f required the markup workstream to change classification
semantics *and* required `G_P4F_INSTRUMENT_UNCHANGED` to hold a single tool
digest constant. Both cannot be satisfied. The deeper defect is that one digest
is the wrong notion of identity once policy and code are separable — it permits
drift in either direction.

P4f is **not modified**. It is preserved as `SUPERSEDED_BEFORE_EXECUTION`:
expansion-planning evidence that was never run, so no result is superseded, only
a plan. Its arithmetic carries forward because it was correct.

`P4g_cohort_expansion` defines instrument identity as a composition of the
source-map code digest, the witness code digest, the markup-semantics policy
digest and the schema digest, hashed together.

| part | value |
|---|---|
| policy digest | `sha256:7dfa3dac52cf9a06cefc9e9eec4482aab5a15884dff6143a88f2d603df586f12` |
| schema digest | `sha256:f4d1aec809956d845b2789124bc0122f832587606531cd6b861e35e5e0a6f953` |
| **composite** | `sha256:3dda8243749788e939f6fb8916dacb8f16cefa6cca9d7a3cc5e4d3c373fe1f3a` |

The policy digest is computed over the **declared mapping**, not the file bytes.
Reformatting a comment or rewrapping a justification leaves it unchanged;
reclassifying one attribute always moves it. A file hash has neither property,
and a test pins both.

Protocols frozen: `MARKUP_SEMANTICS_V1`
`sha256:4cba5049326f32495f168b1186a93fe072a3ebc98017c6543f6a5ff9e08027eb`,
`P4g_cohort_expansion`
`sha256:dc7b59a78ce5004cc715205c81da3f0292a0d7cf9d83d2bf7fc0fb3d8b6de88f`.
`G_P4G_COMPOSITE_IDENTITY` replaces `G_P4F_INSTRUMENT_UNCHANGED`.

## AS. What is deliberately not predicted

P4f's structural finding stands: within `git_docs`, eligibility was 5 of 6 Q1;
the other three families contributed 169 Q1 and zero eligible. Expansion in that
mix multiplies a zero, which is why expansion was paired with this workstream.

**No prediction is offered about what the new policy does to eligibility.**
`class` and `style` are the two most frequent attributes in the corpus and are
both UNRESOLVED, which blocks completeness — eligibility may well stay low. That
would be a finding, not a failure to be engineered away.

P4g names the temptation in its own text: moving either to IGNORED would raise
eligibility more than any other single edit, and doing so requires *proving* no
external rule changes visibility, ordering or behaviour for that corpus, declared
before the measurement. The floor stays at eligible Q1 >= 190, spread across more
than one family, and the expanded cohort is scored exactly once.

The corpus survey — `class` 65,485, `href` 58,014, `title` 39,399, `style`
25,441, `&#160;` 15,415, `colspan` 1,198, `alt` 963, `role` 575, XBRL
`contextref` 194, `lang` 167 — was used to learn which constructs *exist*. Every
classification was decided by the semantic-effect rule. Neither is a substitute
for the other, and the protocol records which is which.

## AT. Open, still not an agent's call (superseded by section BA)

| # | item | why it is not decided here |
|---|---|---|
| 1 | corpus licensing for public release | founder |
| 2 | 2 `UNVERIFIED_SELF_HASH` receipts | a demonstrated canonicalisation recipe |
| 3 | `INC-V2-002` residual | the projection map's own adequacy is unmeasured |
| 4 | `INC-V2-004` against `knowledge_store.py` | the v1 module still carries the defect |
| 5 | P4g targets | 400 documents and the family mix are frozen, not immutable. Changing them is fine if deliberate and recorded, never in response to a number |
| 6 | model choice for the study | a parameter of the approval |
| 7 | whether `class`/`style` can ever leave UNRESOLVED | requires a proof about external rules over a named corpus, not a judgement call |
| 8 | DART credential | `status 010`. Blocks nothing |

### Items closed since Part 6

| item | closed by |
|---|---|
| markup coverage workstream | sections AN–AR — `MARKUP_SEMANTICS_V1` frozen |
| P4f's contradictory gates | section AR — `INC-V2-011`, P4f preserved, P4g frozen |
| tool-digest-only sealing loophole | section AR — composite identity, policy hashed over the mapping |

221 tests green. **No GPU. No paid inference. $0.** Overall programme status is
unchanged: **PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED.**

**IP gate remains CLOSED.** `docs/ip/` was not modified.

---

# Part 8 — The expanded cohort, scored once

*2026-08-22. `P4g` executed. **Eligible Q1 = 174** against a floor of 190. No
GPU. No paid inference. $0.*

## AU. Two defects found before the number, and one after the crash

The markup policy was frozen at the end of Part 7 — and nothing read it.
`markup_semantics` was imported by its own controls and by the tool that seals
it, while the source map still classified with P0d's grammar. A cohort scored at
that moment would have produced a number the workstream never touched, while the
report said the workstream was done. Not a wrong number: a **plausible** one.
That is `INC-V2-013`, and it was repaired forward with `source_map_v2` and
`coverage_witness_v2`, leaving `source_map.py`, `coverage_witness.py` and
`source_spans.py` untouched so Locality v2's eligible Q1 = 5 stays reproducible.

`INC-V2-012` is smaller and the same shape: P4g inherits `spacing_rule:
unchanged from P4e`, but P4e's git and SEC rule was *the pair already held* — 8
and 10 documents. A rule that selects from a held set of 8 cannot produce 120.
The two rules that had to be written are labelled `EXTENSION` rather than
`verbatim`, frozen before the first fetch.

`INC-V2-014` records that the declared lists reached 300 of a 400-document
target, and `INC-V2-015` that the first scoring attempt died with `MemoryError`
before writing anything — which matters only because "scored exactly once" has
to mean something. No receipt, no figure, no figure seen; the budget was not
consumed and the repair could not have been aimed at a number that did not exist.

## AV. The over-grant that an improvement produced

A dry run on the P4e cohort, before P4g was touched, returned **42 of 42
complete** on Wikipedia. The v1 closure admits a span when its *text* appears in
the atom, which for HTML admits character data and essentially nothing else:
every tag and attribute inside the atom's own region falls outside the closure.
Under the old grammar that was invisible, because the character data was
`UNMODELED` and blocked anyway. Under the new policy the character data is
`MODELED` when traceable, so the same closure granted completeness to documents
whose markup it never looked at.

An over-grant produced by an improvement is the most dangerous kind, because
every individual step was an upgrade. The markup closure now also admits every
span overlapping the source region the atom occupies, grown across the tags that
delimit it and stopping at the next unit's text. An atom that no unambiguous
fragment can place refuses with `ATOM_SOURCE_REGION_NOT_LOCALISABLE` rather than
guessing. Widening a closure can only block, never grant.

Content is granted the same way: the policy's `MODELED / CONTENT_LEXICAL` is a
statement about a construct's *kind*, so text and character references are
modelled when traceable into the canonical text of that revision and `UNMODELED`
when not. `&#160;` must be found as itself — a canonicaliser that folded it to an
ordinary space did not carry the character through.

## AW. The result

| | |
|---|---|
| documents | 321 — Wikipedia 114, `git_docs` 98, eCFR 93, SEC 16 |
| questions scored | 3,710 |
| Q1 | 1,014 |
| **eligible Q1** | **174** |
| floor | 190, unchanged |
| families with eligible Q1 | 3 of 4 |
| `LOCATION_UNVERIFIABLE` | **0** |
| envelope retrievable@10 | 0.9863 |
| atom recoverable from envelope | 1.0 |

**Verdict FAIL**, on one gate: `G_P4G_SCALE`, 321 documents against 400. Every
other gate passed. So 174 is a measurement on a 321-document cohort, not on the
cohort the protocol asked for, and it is not reported as one.

| family | Q1 | eligible | eligible per document |
|---|---|---|---|
| `git_docs` | 168 | 109 | 1.11 |
| `regulation_ecfr` | 272 | 58 | 0.62 |
| `encyclopedia_wikipedia` | 518 | 7 | 0.06 |
| `sec_edgar` | 56 | 0 | 0.00 |

## AX. What the markup workstream did, measured

`regulation_ecfr` went from **0 eligible under Locality v2 to 58**. That family
was unreachable because its XML constructs fell to `UNMODELED` by default; under
a declared semantics they resolve with reasons, and a fifth of its questions now
clear. That is the workstream doing the thing it was built for.

`INC-V2-013` recorded a prediction before the run: eligibility would **fall**,
because `class` and `style` are `UNRESOLVED` and are the most frequent
attributes in the corpus. Per markup question it did — Wikipedia questions that
would have passed on text alone now refuse. The total rose from 5 to 174 anyway,
because the cohort is 5.6 times larger and because eCFR was unlocked. Both are
true, and writing the prediction down beforehand is what makes it possible to
say which part of the movement came from which cause.

`LOCATION_UNVERIFIABLE = 0` across 321 documents: position is no longer a
limitation anywhere in the instrument.

## AY. `attr:class`, and the line-of-code that would clear the floor

| refusal | count |
|---|---|
| `UNMODELED_SOURCE_FACT_IN_CLOSURE` | 2,455 |
| `UNRESOLVED_SOURCE_FACT_IN_CLOSURE` | 1,878 |
| `NO_DIRECT_SPAN_FOR_TARGET_ATOM` | 433 |
| `ATOM_SOURCE_REGION_NOT_LOCALISABLE` | 210 |

`attr:class` alone accounts for **1,795 of the 1,878** unresolved refusals, and
is why Wikipedia yields 7 eligible Q1 from 518. Under a fail-closed reading, an
element carrying a class cannot be shown to be unaffected by an external rule,
so encyclopedic HTML cannot presently support question-local source-faithful
completeness.

That is a finding, not a problem to be edited away. Moving `class` to `IGNORED`
would lift eligibility past the floor in one line — which is exactly why P4g
named it in advance as the specific temptation, before any number existed. It
stays `UNRESOLVED`. Changing it would require *proving*, for a named corpus and
declared before any measurement, that no external rule changes visibility,
ordering or behaviour. A proof with its own controls, not a reclassification.

## AZ. P4h — expansion, with the mix deliberately not re-weighted

174 < 190, so: no GPU request, no re-fitting of instrument or policy, no
narrowing, and the floor is not lowered — specifically not to 174.
`P4h_cohort_expansion` is frozen at
`sha256:03fcaae58ee63f9af906db40bd3fb51e255956cac423c69f4afee7140c774035`,
with the instrument identical to the one that produced 174, sealed at composite
`sha256:0ed844f6…` and gated with no escape clause.

550 documents, quota 165 / 165 / 165 / 55, the same balance rule as P4g. The
available move was to shift the quota toward `git_docs`, which yields 1.11
eligible Q1 per document and would reach the floor with a fraction of the
documents. **It is not taken.** Choosing a cohort by which families score well is
conditioning selection on an eligibility result — the mirror of fitting the
instrument to the cohort, forbidden for the same reason. The cost of refusing it
is that P4h needs more documents, and that 165 Wikipedia documents are expected
to contribute about ten eligible Q1.

Scaling the observed per-document yield projects about 295 eligible Q1, roughly
1.55× the floor. That is a projection, binds nothing, and gates nothing — a
cohort sized to land just above 190 would make the gate the target, and P4g
already showed per-family yield moves when the policy does.

P4h also over-selects at 1.5× quota per family, because P4g's shortfall was
mechanical: selectors stop at a quota of *selected* documents while attrition
happens later, at payload and parse floor. Truncation is by declared order,
fixed before the first fetch.

## BA. Open as of Part 8 (superseded by Part 9)

| # | item | why it is not decided here |
|---|---|---|
| 1 | corpus licensing for public release | founder |
| 2 | whether to run the P4h acquisition now | it is frozen and ready; executing it is a scope decision |
| 3 | the `class` / `style` proof | a workstream with its own evidence, not a classification change |
| 4 | 2 `UNVERIFIED_SELF_HASH` receipts and 3 unexplained drifts | all from an unrelated 2026-08-19 experiment; standing |
| 5 | `INC-V2-002` residual and `INC-V2-004` against `knowledge_store.py` | unchanged |
| 6 | model choice for the study | a parameter of the approval |
| 7 | DART credential | `status 010`. Blocks nothing |

### Items closed since Part 7

| item | closed by |
|---|---|
| the markup policy being sealed but unread | section AU — `INC-V2-013`, `source_map_v2`, `coverage_witness_v2` |
| whether markup semantics changes anything measurable | section AX — eCFR 0 → 58 eligible Q1 |
| HTML/XML positional provenance at scale | section AW — `LOCATION_UNVERIFIABLE = 0` over 321 documents |
| what to do below the floor | section AZ — `P4h` frozen |

**No GPU. No paid inference. $0.** The model study is not requested: eligible Q1
is 174 against a floor of 190. Overall programme status is unchanged:
**PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED.**

**IP gate remains CLOSED.** `docs/ip/` was not modified.

---

# Part 9 — P4i clears both gates

*2026-08-22. **511 documents, eligible Q1 = 296**, verdict PASS on 10 of 10
gates. No GPU. No paid inference. $0.*

## BB. A protocol that predicted its own failure

`P4h` set family quotas `165 / 165 / 165 / 55 = 550` and required
`G_P4H_SCALE: at least 550 admitted documents`, while truncating each family at
its own quota — and predicted, in its own text, that `sec_edgar` would admit 20
to 55. If SEC admitted 20 the ceiling was 515 and the gate failed before a single
document was scored. Over-selection at 1.5× mitigates attrition *inside* a
family; this was a shortfall *across* families that per-family truncation forbids
anyone from covering.

The underlying error was a category error: a **document count** and a **powered
question count** were welded into one gate. They are different claims with
different failure modes, and a protocol that fails the first cannot report on the
second. That is `INC-V2-016`. P4h was preserved unmodified as
`SUPERSEDED_BEFORE_EXECUTION` — it produced no result, so superseding it discards
no evidence.

Two of my own descriptions were corrected at the same time. P4h called
`165 / 165 / 165 / 55` the realized proportions behind 174; they are not, P4g's
admitted mix was `98 / 93 / 114 / 16`, and the accurate phrase carried into P4i
is **acquisition quotas scaled up from P4g's predeclared nominal balance rule**.
And P4h's `expected eligible ≈ 295` multiplied a per-admitted-document yield by a
nominal quota, silently assuming every quota fills — the assumption
`INC-V2-014` had already recorded as false. It was withdrawn rather than carried
forward.

## BC. Two gates, two claims

`P4i_cohort_expansion`, frozen `sha256:b7aa130c…`:

| | |
|---|---|
| acquisition target | 550 — attempted for headroom, **non-gating** |
| breadth gate | **≥ 400 admitted across ≥ 4 families** |
| power gate | **eligible Q1 ≥ 190**, in ≥ 2 families |

400 is not a number invented to fit 174. It is the bar `G_P4G_SCALE` already
carried before any result existed, and which P4g failed at 321. Inheriting it
leaves the acquisition bar exactly where it was set in advance, while the
statistical claim moves to its own gate where it belongs.

## BD. The result

| | |
|---|---|
| documents admitted | **511** — git 165, eCFR 165, Wikipedia 165, SEC 16 |
| candidates selected | 768 |
| questions scored | 5,686 |
| Q1 | 1,564 |
| **eligible Q1** | **296** |
| floor | 190, unchanged |
| **exact power at 296** | **0.9977** |
| families with eligible Q1 | 3 |
| `LOCATION_UNVERIFIABLE` | 0 |
| envelope retrievable@10 | 0.9863 |
| atom recoverable from envelope | 1.0 |
| verdict | **PASS**, 10 of 10 gates |

| family | admitted | Q1 | eligible Q1 | per Q1 |
|---|---|---|---|---|
| `git_docs` | 165 | 274 | **202** | 0.74 |
| `regulation_ecfr` | 165 | 467 | **87** | 0.19 |
| `encyclopedia_wikipedia` | 165 | 767 | **7** | 0.01 |
| `sec_edgar` | 16 | 56 | 0 | 0.00 |

511 is short of the 550 target, and that is explicitly not a failure — the gate
is 400. Every rejection is reason-coded: `SOURCE_EXHAUSTION` 4,490 ·
`PARSE_FLOOR` 122 · `SPACING_NOT_MET` 60 · `PAYLOAD_UNAVAILABLE` 6 ·
`NO_SOURCE_CHANGE` 4 · `LISTING_FAILED` 3 · `RELATION_FAILURE` 3 · `OTHER` 125.
The exhaustion figure is overwhelmingly CFR sections carrying a single dated
version — a property of the source, not of the fetcher, which is precisely the
distinction reason codes exist to make.

## BE. How 174 became 296

**190 more documents.** Everything that could have been loosened was not:

- the **instrument** is byte-identical to the one that produced 174 —
  `sha256:0ed844f6…`, gated by `G_P4I_INSTRUMENT_UNCHANGED` **with no escape
  clause**;
- the **floor** is still 190, and specifically was not lowered to 174 when P4g
  came one gate short;
- the **markup policy** is untouched: `attr:class` and `attr:style` remain
  `UNRESOLVED_SOURCE_FACT`, and `attr:class` still accounts for **2,629 of the
  2,716** unresolved refusals. Either one reclassified to `IGNORED` would have
  cleared the floor on P4g in a single line;
- the **mix** was not re-weighted. `git_docs` yields 0.74 eligible per Q1 against
  Wikipedia's 0.01, so shifting the quota would have reached 296 with far fewer
  documents. `G_P4I_MIX_NOT_REWEIGHTED` forbids it, and the price paid was 165
  Wikipedia documents contributing 7 eligible questions.

`sec_edgar` reached 16 of a 55 quota and contributed zero. It is reported at what
it reached — not padded by relaxing the parse floor, not dropped. A family that
yields nothing is evidence about the family.

Two `run_p4i` invocations died before writing anything: the first with
`KeyError: 'acquisition_target'`, because the scorer was scaffolded from
`run_p4g` and its `--manifest` default still pointed at the P4g cohort. No
receipt, no figure printed, none seen — the once-only budget was not consumed, on
the basis `INC-V2-015` had already established.

## BF. What is now requested

`admitted >= 400` ✓ · `eligible Q1 >= 190` ✓ · `eligible families >= 2` ✓ ·
every integrity gate PASS ✓.

`MODEL_STUDY_PROPOSAL_v2_2026-08-22.md` is submitted with the real numbers.
v1 is preserved unmodified: its recommendation was *do not run*, on eligible
Q1 = 5, and that was correct when written.

The study is sized for the actual 296 rather than the 190 floor: 1,184
generations, ≤ 6 GPU hours, a hard **$40** ceiling, five stop rules, the
confirmatory split opened once. Model choice remains a parameter of the approval.

**GPU has not run and will not run before approval.** Meeting these gates makes
the study *proposable*; approving it is a separate decision.

## BG. What 296 does not mean

It does not make any document revision source-faithful end-to-end. P0d's standing
result is unchanged and not worked around: **26 of 26 revisions are
`SOURCE_COVERAGE_INCOMPLETE`**. The two endpoints stay apart —

- **controlled currency**: what the study would measure, on locally
  coverage-complete targets;
- **source-faithful end-to-end**: `NOT_ESTABLISHED`.

And it does not mean encyclopedic HTML is solved. Wikipedia yields 7 of 767
because `class` cannot be shown to be unaffected by an external rule. The study
is powered *despite* that constraint, not by relaxing it. Resolving it needs a
proof about external stylesheets for a named corpus, declared before any
measurement — a workstream with its own controls, not a reclassification.

310 tests green. Programme status unchanged:
**PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED.**

**IP gate remains CLOSED.** `docs/ip/` was not modified.

---

# Part 10 — The model-endpoint preflight, and the run that did not start

## BH. What was frozen before anything was measured

`MODEL_ENDPOINT_V1` was authored and sealed at
`sha256:2b0487c41076fee00dfc9eae6265881c0d6918a9a66f5337b35130000b1172f4`
before the first model input existed. It fixes eleven things the founder's
conditional approval named: the pinned model and revision, the runtime, the four
arms, CPU materialization of every prompt, the 4,096-token budget, the
context-validity filter, the truncation stop, the 190 cohort floor, the
deterministic scorer with its controls, the Latin-square arm schedule, and the
two execution stages with the assay-sensitivity validity gate between them.

Two corrections from the approval are carried in the protocol text itself.
`materially` is gone from the stop condition, replaced by
`compiled_current − superseded_control >= 0.15`, declared a **validity gate, not
a significance test**, with `p_value: null` and evaluation only after the full
first pass. And the corpus is never called untouched: the recorded term is
**`MODEL-ENDPOINT CONFIRMATORY — MODEL OUTCOMES UNSEEN`**, because P4i's
retrieval and coverage figures were seen and only the model's answers were not.

## BI. The verdict

The preflight ran once, entirely on CPU:
`receipts/model-endpoint-preflight--20260822T151517Z-43f9291f0970.json`.

**FAIL.** Nine gates pass, two fail.

| gate | result |
|---|---|
| `G_ME1_MODEL_PINNED` | PASS — tokenizer digest byte-identical, probe 20/20 |
| `G_ME1_RUNTIME_DECLARED` | PASS |
| `G_ME1_INPUTS_MATERIALIZED` | PASS — 10 questions × 4 arms = 40 prompts |
| `G_ME1_PROMPT_CARRIES_NO_ARM_LABEL` | PASS |
| `G_ME1_CONTEXT_VALIDITY` | PASS |
| `G_ME1_SCORER_CONTROLS` | PASS — 8 of 8, all three directions |
| `G_ME1_VALUES_DISTINGUISHABLE` | PASS |
| `G_ME1_SCHEDULE_BALANCED` | PASS — spread 1 |
| `G_ME1_NO_GPU_YET` | PASS — 0 seconds, $0 |
| **`G_ME1_COHORT_FLOOR`** | **FAIL — 10 against a floor of 190** |
| **`G_ME1_TRUNCATION`** | **FAIL — 0.70 / 0.40 / 0.40 / 0.20 against 0.25** |

The protocol's own instruction applies without interpretation:
`if_any_gate_fails: GPU does not start`. **No GPU second was spent, no model was
called, and $0 of the approved $40 was drawn.**

## BJ. Local coverage completeness is not endpoint eligibility

This is the finding, and it is not a mishap on the way to one.

Of 296 regenerated candidates, 286 were excluded before any model call:

    VALUES_NOT_DISTINGUISHABLE            274
    TARGET_EVIDENCE_LOST_TO_TRUNCATION     12

and inside the first, by direction:

    neither revision carries a distinguishing value   140
    the superseded revision carries none               35
    the current revision carries none                  15

P4i's eligibility asks: *is the compiled state locally complete against its
source?* The model endpoint asks something strictly harder: *do the two
revisions differ in a value an answer can select between* — a number, date,
version, percentage, amount or identifier. **92.6% of the eligible Q1 population
differs only in prose, structure or wording.** There is nothing there for a
model to get right or wrong. Scoring those questions would have measured
phrasing overlap between two paraphrases and reported it as currency selection.

The 296 was never wrong. It answered its own question correctly. What Part 9
called a powered cohort was powered for the coverage endpoint, and the model
endpoint turns out to be a different population with a much smaller intersection.

## BK. The two failing gates are not independent

Truncation rates are computed over the ten survivors, so `0.70` is seven
documents out of ten. At n = 10 the figure carries no stability worth acting on.
**The cohort floor is the primary failure; truncation is a symptom reported at a
sample size that cannot support it**, and it is recorded that way rather than
argued into a pass or quietly dropped.

## BL. What was not moved

Each of these would have produced a passing preflight within minutes.

- **The value patterns were not widened.** Admitting ordinary changed words as
  markers clears the floor at once — and destroys the endpoint in the same
  stroke, because `CURRENT_ONLY` would stop meaning *selected the current
  value*. The scorer is byte-identical to what was frozen and its eight controls
  all pass, including the two that exist to stop exactly this drift:
  `42` must not match inside `4200`, and `42.50` must not collapse into `42.05`.
- **The 4,096-token budget was not raised** to rescue the truncation rate.
- **The 190 floor was not lowered**, on the same standing rule that held it at
  190 when P4g returned 174.
- **The protocol was not amended and the preflight was not re-run.**
- `docs/ip/` was not modified. The IP gate remains CLOSED.

## BM. Two accounting notes, recorded rather than smoothed

`eligible_q1_from_p4i` reads 293 against 296 coverage rows: three `question_id`
strings collide across documents where anchor paths repeat. It affects set
cardinality, not candidate iteration, and it is reported rather than
deduplicated in silence.

The tokenizer reports `Qwen2TokenizerFast` here against `Qwen2Tokenizer`
attested, and `vocab_size` 248044 against 248320. Both are `transformers`
reporting differences. Identity rests on the `tokenizer.json` digest — byte
identical to the W6 attestation — and on the behaviour probe, which returns the
attested 20 tokens on
`TAVONEL 1,450 — café ü 42.50 USD`. Two independent checks, both matching; the
field discrepancy is stated rather than glossed.

## BN. Standing position

Everything built to answer *is the instrument pinned, is the prompt clean, is
the schedule balanced, does the scorer work, is the context valid* passes. What
fails is the corpus's ability to pose the question at all. That is a genuine
result about the corpus and it is preserved as
**`MODEL_ENDPOINT_INFEASIBLE_ON_THIS_COHORT`** (`INC-V2-017`).

Every route forward changes what is being measured — acquiring sources selected
for value-bearing revisions, or redefining the endpoint away from value
selection. Both are founder decisions, not implementation ones. Nothing is
re-run until one exists.

337 tests green, 1 skipped. Programme status unchanged:
**PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED.**

---

# Part 11 — Route A: the value-bearing cohort, and where it actually stops

## BO. What was frozen, and in what order

The founder adopted Route A and kept the primary endpoint. `MODEL_ENDPOINT_V1`'s
failure, its final cohort of 10, `INC-V2-017` and P4i's 296 are read-only
evidence and were not touched.

The development order was followed as specified, each freeze preceding the data
it would be applied to:

1. `INC-V2-018` registered — non-injective question identity;
2. `VALUE_BEARING_COHORT_V1` frozen at
   `sha256:a4a2b568d3d04b475ea9edccf28f588c6d349852e960a55f608500c049d0e68e`;
3. the ValueFact extractor developed on P4i's permitted development data;
4. thirteen fixtures passing — positive, negative and adversarial;
5. extractor, property taxonomy and question generator frozen at
   `receipts/value-fact-freeze--20260822T170435Z-7f50504835c5.json`;
6. fresh candidate lists frozen, checked disjoint from P4i;
7. a bounded feasibility probe, CPU only.

## BP. INC-V2-018 — identity, fixed only forward

P4i's receipt holds 296 coverage rows; the preflight read 293 unique
`question_id` strings. The identifier was a rendered string —
`<document>|<kind>|<anchor path>` — and anchor paths repeat inside a document
whenever the same labelled construct recurs. `(3)#1` under two subsections of one
CFR part is the ordinary case.

Nothing downstream was wrong by it: the preflight iterated candidates rather than
the set, so 296 were materialized. P4i's figures were **not** recomputed.
Correcting a sealed result to tidy a later number is precisely what this ledger
exists to prevent.

The successor replaces it with a content-addressed hash over eight declared
inputs, and the property id is what makes it injective where the anchor path is
not. The gate is hard: `unique ids == rows`, one duplicate stops the run. A
collision is not a miscount — McNemar pairs *by question id*, so a collision
silently pairs one arm's answer with a different question.

## BQ. The extractor, and the one thing it had to be allowed to do

`value_fact.py` reads a source's own structure — a table row under a named column
header, a `<th>/<td>` infobox row — and reports the value bound to that label.
Two shapes, declared in the taxonomy before any source was read. Every rule can
only refuse: a cell must hold exactly one value, both revisions must bind the
same label, both values must be the same kind, the label must be readable
without reading the value, and the evidence atom must carry no other changed
value.

One correction was needed and it is worth stating because it looks like a
loosening and is not. The frozen scorer's patterns overlap deliberately —
`2.14.1` matches the version chain *and* the plain number `2.14` inside it. For
judging an answer that redundancy is harmless. For *selecting* a candidate it is
fatal: a cell holding one version reads as a cell holding two values, and no
version-chain property could ever become a question. `dominant_tokens` drops
matches nested inside a longer match, and decides nesting by **span
containment, never string containment** — in `5 to 15` the token `5` is a
substring of `15` but holds its own position, so both survive and the cell is
correctly refused. The scorer itself is byte-identical; the refinement lives on
the acquisition side, where a mistake can only cost candidates.

## BR. Development measurement on P4i

The extractor was frozen, then run over P4i's 511 documents as permitted
development data.

    value facts             git 0 · eCFR 1 · wiki 38 · SEC 0
    documents with a fact   9 of 511  (1.8%)
    facts in documents that also produced a locally-complete Q1
                            16, all encyclopedia_wikipedia

The git zero is not a defect: 165 git documents produced 50 property bindings
across 11 documents, every one `VALUE_UNCHANGED` or `PROPERTY_NOT_STABLE`. The
tables were read; their values did not move.

Two things this did **not** authorise. It did not authorise widening the
taxonomy — the two shapes were sealed before the measurement existed. It did not
authorise re-weighting the declared family shares, in the same words that
forbade re-weighting P4g's mix. And it did not authorise abandoning the route on
a projection: P4i admitted documents for carrying *any* semantic change, so its
density says nothing reliable about a population admitted for carrying a value
change.

## BS. The probe — 45 fresh documents, and a zero that is informative

Rather than size a multi-thousand-document acquisition from the wrong
population, a deliberately small probe fetched 45 fresh documents across all
four families. Its lists were checked disjoint from P4i by code, not asserted —
the check caught four SEC issuers on the first run and refused to fetch until
they were replaced.

    documents            45   (git 14 · eCFR 14 · wiki 14 · SEC 3)
    properties read     174
    VALUE_UNCHANGED     154
    PROPERTY_NOT_STABLE  20
    value facts           0
    questions             0

**The zero is not an extractor failure.** 174 source-native property/value
bindings were read and paired across revisions. The tables were found, the
labels read, the values compared.

**Nothing reached the coverage step.** `COVERAGE_INCOMPLETE`, `ATOM_NOT_LOCATED`
and `AMBIGUOUS_VALUE_FACT` are all zero, so `attr:class`, truncation, the token
budget and context validity were never consulted. The binding constraint sits
*earlier* than everything the previous two failures were about.

## BT. What the constraint actually is

P4g's selector — inherited unchanged through P4i and this probe — picks two
revisions separated by a spacing rule and differing somewhere. Documents change
constantly; the particular table cell binding a labelled quantity changes
rarely. Sampling two revisions blind to whether a value moved and then asking
whether one did is a low-probability draw, and 0 of 174 is what that looks like.

So the sequence of three failures is not three versions of one problem:

- `INC-V2-017` — the endpoint could not be posed on a cohort selected for
  semantic change;
- the P4i development measurement — value-bearing revisions are ~2% of that
  population;
- `INC-V2-019` — and on fresh sources chosen for value-bearing *structure*, the
  rate of value-bearing *revisions* under blind pair sampling is zero in 174.

Structure is common. Movement is rare. The study has been selecting for the
first and requires the second.

## BU. The probe is burned, and that was the point of keeping it small

Its 45 lineages have had their eligibility seen and are excluded from any
confirmatory cohort — the same rule that excluded P4i's lineages and
`MODEL_ENDPOINT_V1`'s ten survivors. That cost is exactly why the probe was 45
documents and not 600.

## BV. What was not moved, again

The scorer is byte-identical and its eight controls pass. No value kind was
added. The thirteen extractor fixtures pass unchanged after the zero. The 190
floor stands, the 4,096-token budget stands, the declared family shares stand,
and no confirmatory acquisition was started. GPU seconds 0, spend $0, and none
of the $40 ceiling drawn. `docs/ip/` untouched; the IP gate remains CLOSED.

## BW. The decision handed back

A value-bearing cohort requires selecting the **revision pair** by the frozen
predicate — searching a document's revision history for a pair in which a
labelled quantity moved — rather than sampling two revisions and testing them
afterwards. That is still admission by the frozen predicate, which the protocol
already requires. But it replaces an acquisition primitive that P4g, P4i and this
probe all share, and it interacts with the revision-spacing rule those protocols
froze. It is a founder decision, not an implementation one.

365 tests green, 1 skipped. Programme status unchanged:
**PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED.**

---

# Part 12 — VBC2: history search, a parallel executor, and a complete walk

## BX. What changed and what did not

The founder approved revision-history search and, separately, a parallel
executor. Both were treated as changes to *how* the same answer is computed. The
candidate list, family quotas and shares, the ValueFact extractor, the transition
predicate, the acquisition cutoff, the 1,460-day horizon, the twelve-revision
bound, the newest-qualifying rule, one question per lineage and the 190 floor are
the frozen ones throughout.

`VALUE_BEARING_COHORT_V2` was frozen at
`sha256:5f3a860138fe1c7a6fd0b7e571723e8224d325037cd7e3ecfabc7e511e4ca8b7`, and
2,271 fresh lineages — git 915, eCFR 928, Wikipedia 300, SEC 128 — were frozen
before any history was read, checked disjoint from P4i, the V1 probe and the
`MODEL_ENDPOINT_V1` survivors.

## BY. Three incidents on the way

**`INC-V2-020`** — the exact McNemar power calculation assumes independent paired
observations, and one document can yield several correlated ValueFacts. One
primary question per lineage, gated hard. The floor now means 190 *independent
lineages*: a stricter bar than the one that failed twice.

**`INC-V2-021`** — two acquisition processes ran concurrently against one output
path. Neither reached its write, so nothing was contaminated. The instructive
part is what would have happened if they had: both walk the same frozen list
under the same deterministic predicate, so they would have produced *the same*
cohort and the second write would have looked like a normal success. **A
duplicate that agrees is harder to notice than one that disagrees.** The trigger
was reading an empty log as death — but a walk that logs every ten admissions is
silent for hours when admissions are rare, which `INC-V2-019` had already
established was the expected regime. Silence was the prediction, not the anomaly.

**`INC-V2-022`** — nothing downstream could tell a completed walk from an
interrupted one. A budget-stopped walk that happened to admit 190 lineages would
have cleared every gate. That is not a cohort that fell short; it is **a cohort
whose denominator is unknown.**

## BZ. The executor, and the equivalence gate it had to pass first

Three roles that do not overlap: many read workers, one deterministic reducer,
one writer. A worker sees one lineage and two injected callables — it cannot see
the global quota, the admitted count, any other result, or any coverage,
retrieval or model figure. A test strips docstrings and greps the code, because
prose *about* a forbidden name is not access to it.

Completion order is not selection order. Results are collected as they finish and
re-sorted into frozen lineage order before a single admission pass that is the
serial algorithm unchanged. Completion order correlates with latency, payload
size and provider health; admitting on arrival would make the cohort a function
of the network.

Proven on a synthetic fixture **before** the walk ran:

    serial admitted ids        == parallel admitted ids
    serial selected transition == parallel selected transition
    serial primary property    == parallel primary property
    manifest semantic digest    identical across every rotation of arrival order

The semantic digest excludes timestamps, worker counts, cache statistics and host
tallies — they differ between serial and parallel by construction, and a digest
containing them could never demonstrate equivalence.

Transport is host-scoped: per-host semaphores and cooldowns, `Retry-After`,
exponential backoff with jitter. One global sleep is exactly why the serial walk
ran at its slowest provider's pace. The enumerators are the frozen ones; only the
byte-carrying function was swapped.

**Result: 165 minutes for 3 admissions serially, against 67 minutes for the
complete 2,271-lineage walk.**

## CA. The complete walk

    status                    COMPLETE   (stopped_on_wall_clock_budget false)
    lineages walked           2,271 of 2,271
    admitted                  3          (git 2 · Wikipedia 1)

    NO_QUALIFYING_TRANSITION  1,144
    TOO_FEW_REVISIONS         1,107
    PAYLOAD_UNAVAILABLE          16
    PARSE_FLOOR                   1

By family:

    eCFR    778 too-few-revisions · 148 no-transition   (928 = all of them)
    git     264 too-few-revisions · 634 no-transition
    wiki      1 too-few-revisions · 298 no-transition
    SEC      64 too-few-revisions ·  64 no-transition   (128 = all of them)

## CB. The two refusals are different failures, and both were measured

They are not one problem counted twice.

**`TOO_FEW_REVISIONS` is history depth.** A direct check of the enumerators:

    ecfr:2:200:200.0    revisions 1
    ecfr:2:200:200.1    revisions 1
    ecfr:2:200:200.10   revisions 0

Most CFR sections carry a single dated version inside the horizon. P4i saw the
same property from the other side as 4,490 `SOURCE_EXHAUSTION` rejections.

**`NO_QUALIFYING_TRANSITION` is what twelve revisions covers in time**, and that
depends entirely on how busy the lineage is:

    wikipedia:en:Augsburg     12 revisions spanning  135 days
    wikipedia:en:Erlangen     12 revisions spanning  124 days
    wikipedia:en:Fürth        12 revisions spanning  149 days
    git:sqlite/…-windows.md   12 revisions spanning  660 days

Encyclopedic infobox quantities — population, area, elevation — update roughly
annually. Twelve revisions of a busy article is about four months, so the window
almost never contains one. The bound and the edit rate interact, and the
interaction runs opposite on the two ends: busy lineages give a window too short
in time, quiet ones give too few revisions at all.

**The twelve-revision bound was not moved.** It is frozen on API, compute and
reproducibility grounds with `explicitly_not_basis: observed value-fact yield`,
and this measurement is exactly the yield it must not be tuned against.

## CC. Transport did not cause this

eCFR throttled 179 times. Every one was absorbed by the pool's backoff and
**zero became a `LISTING_FAILED`** — eCFR's 928 rejections are 778 + 148 + 2,
which is all of them accounted for by source properties. GitHub, Wikipedia and
raw.githubusercontent threw no throttles at all. That distinction is why the
reason codes exist: a provider slowing the walk and a provider making a lineage
unreadable are different events, and only the second could be mistaken for a
source property.

## CD. `INC-V2-023` — a defect the small cohort exposed

All three admitted lineages were then excluded by the preflight as
`ATOM_NOT_LOCATED`:

    label='**App size**'         atoms=7   label_hits=0
    label='`background.paper`'   atoms=25  label_hits=0
    label='Romania'              atoms=4   label_hits=0

The extractor reads property labels out of **raw markup**, so they carry it —
`**App size**`. The preflight searched for that string inside **canonical atom
text**, where emphasis markers and code fences are already stripped. The two
halves of the instrument were comparing different representations of the same
document, and that substring test could only fail.

It was recorded before it was repaired, and the repair is safe for a specific
reason worth stating: **three lineages cannot reach a floor of 190 under any
locator.** A locator repaired after seeing a result is suspicious exactly when it
could change the number, and here it demonstrably cannot. After the repair the
three exclusions separate into three genuinely different reasons —
`ATOM_NOT_LOCATED`, `ATOM_NOT_UNIQUE`, `COVERAGE_INCOMPLETE` — instead of
collapsing into one string-matching failure. Had acquisition yielded hundreds,
this defect would have emptied the cohort at the preflight step and the failure
would have looked like coverage or truncation rather than string matching.

## CE. Preflight verdict

**FAIL.** Twelve of fourteen gates pass; the two that fail are the two that
depend on the cohort existing.

    G_VBC2_COHORT_FLOOR    FAIL   0 distinct lineages against a floor of 190
    G_VBC2_FAMILIES        FAIL   0 families contribute

    everything else PASS — scorer unchanged, extractor unchanged, question ids
    injective, one question per lineage, pairs adjacent, selection blind,
    question blind to value, context validity, truncation, schedule balanced,
    tokenizer parity, no GPU

**GPU did not start. 0 seconds, $0 of the approved $40.**

## CF. What this leaves standing

Three protocols have now failed to reach 190 for three different reasons, and
the reasons narrow rather than repeat:

- `MODEL_ENDPOINT_V1` — a cohort selected for semantic change could not pose an
  exact-value question (274 of 296 indistinguishable);
- `VALUE_BEARING_COHORT_V1` — sources selected for value-bearing *structure*
  yielded no value-bearing *revisions* under blind pair sampling (0 of 174
  properties moved);
- `VALUE_BEARING_COHORT_V2` — searching revision *history* for a moved value
  finds them at a rate of 3 in 2,271 lineages, split between histories too
  short and windows too narrow in time.

Structure is common. Movement is rare. Movement *observable inside a bounded
revision window* is rarer still, and the bound cannot be relaxed to find more
without the bound becoming a function of the thing it is measuring.

441 tests green, 1 skipped. Programme status unchanged:
**PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED.**
`docs/ip/` untouched; the IP gate remains CLOSED.

---

# Part 13 — Route A closed, and the Paper Closure Program

> **§CH onward is superseded in its framing by Part 14.** Every number below
> stands exactly as executed; nothing is repaired, re-scored or re-run. What
> Part 14 withdraws is the word *held-out* for both Workstream A and Workstream
> B, and the name *oracle* for Workstream B's result. The text is left as
> written rather than edited, because a report that quietly acquires the
> conclusions of its own later audit stops being a record of what was believed
> when.


## CG. The stopping record

`STOP-V2-005 — EXACT_VALUE_MODEL_ENDPOINT_NOT_FEASIBLE_UNDER_DECLARED_PUBLIC_SOURCE_FRAME`.

The founder's ruling names it `STOP-V2-004`. That identifier has been held since
2026-08-22 by the P4d-Core-Semantic stop and this ledger is append-only, so
reusing it would mean overwriting evidence in the act of recording evidence. The
ruling permits an equivalent record; this is that record at the next free
number, carrying the label verbatim.

    model experiment      NOT_RUN — PREDEFINED CPU PREFLIGHT INFEASIBLE
    GPU authorisation     TERMINATED_FOR_THIS_RESEARCH_CYCLE
    GPU used              0 seconds · $0 of an approved $40

Not *failed*, not *inconclusive*. The predefined CPU preflight ran and could not
be satisfied, so no model was ever asked anything. A future model study needs
its own protocol and its own approval; nothing carries forward.

The frozen contract the ruling forbids refitting — the twelve-revision bound,
the 1,460-day horizon, the source families, the family weighting, the value
scorer, the ValueFact taxonomy and the 190 floor — is pinned in the closure
receipt **by digest**, so a later edit is visible rather than arguable. No VBC3
exists and none will.

`INC-V2-024` classifies the `INC-V2-023` locator repair as a
`POST_ACQUISITION_DIAGNOSTIC`. The repair is valid and stays; what it produced
is not a confirmatory result. Three lineages examined after the outcome was
known, on an instrument that had just been changed, have none of the properties
that make a confirmatory result worth anything. The stop verdict does not depend
on it in either direction: **theoretical best case is 3 of 3, and 3 < 190.**

## CH. Workstream A — held-out source front-end faithfulness

`SOURCE_FAITHFULNESS_HELDOUT_V1`, frozen before its data, then amended once —
before any pair was scored — to declare a 2 MB payload bound on compute grounds.

The question is narrower than P0d's and it is the one a revision pair makes
answerable: **when a region of source changes, does the system say what became of
it?** Every changed region must land in exactly one of three states, and a
changed byte that no state covers is a hard failure rather than a row in a table.

    310 pairs · 4 families · 2,268 lineages walked · 29 minutes · 0 GPU seconds

    changed regions                            373,006
      UNCLASSIFIED                                   0     ← gate PASS
      MODELED                                  121,682
        verified against the compiled state     58,486
        not carried by the compiled state       63,196
      IGNORED_BY_PREDECLARED_POLICY             97,560
      UNRESOLVED_SOURCE_FACT                   153,764

**Nothing fell through.** That is the half that passed, and it is what makes the
rest readable: every one of 373,006 changed regions carries a declared state.

**52% of MODELED claims cannot be carried.** 54,053 of the 63,196 fail for one
declared reason — the facet has no place in a compiled artifact. An artifact
holds unit text, headings, explicit paths and document order. A reference target,
a language declaration, an accessibility string and an effective date have
nowhere to live in that, and the facet→compiled-state map that says so is
declared in the instrument rather than discovered per row, so a reader can
disagree with one line instead of with an aggregate.

**In 30 of 310 pairs the loss is not declared.**

    scopes examined                              1,010
    scopes the run declared locally complete       601
    pairs where a loss sat inside a complete scope   30
    pairs where the compiled state did not move      60

The witness decides local completeness from the grammar's four states alone. It
has no knowledge of whether a MODELED claim survived verification against the
compiled state, so a construct the policy calls MODELED and the compiler does not
store passes it unnoticed. That is the whole mechanism, and this gate is the only
place it shows.

**The gate had power.** 601 scopes were declared complete, so a passing result
would have meant something. A safety endpoint that is never exercised has not
been met — it has been skipped — and the run reports `gate_power` for exactly
that reason.

**`INC-V2-026`, recorded with a bound rather than a promise.** Markdown scope
regions are derived as a minimum-to-maximum interval over located witness
elements, which is a *superset*; on 76 of 101 multi-scope pairs every scope
resolved to the same interval. So the scope-level figure of 209 is an upper
bound and is never used as a headline. An attribution-free criterion — the
compiled state did not move at all while some scope was declared complete —
needs no overlap test at all and gives **34 pairs, larger than the gate's 30**.
The verdict is not an artefact of the coarseness; on this cohort the frozen gate
is the more conservative of the two. The localiser is not repaired and the run is
not re-scored, because unlike `INC-V2-023` a repair here demonstrably *could*
move the number.

Verdict **FAIL** on `G_SFH1_NO_SILENT_DROP`, `G_SFH1_LOCALLY_COMPLETE_CLEAN` and
`G_SFH1_UNRESOLVED_FAIL_CLOSED`. Six other gates pass. 44 revisions exceeded the
declared payload bound and are reported under `PAYLOAD_TOO_LARGE_TO_CLASSIFY`
rather than silently skipped.

## CI. Workstream B — an oracle that does not read the engine's output

The 28-pair Wikipedia result is not restated as an independent-oracle result
anywhere, and the protocol says so in its own header. The correction stands: it
was same-implementation full-recomputation equivalence, because both sides
consumed the canonical document the engine had already produced.

`ORACLE_INDEPENDENCE_V2` changes exactly one thing, and it is the one that
mattered:

    v1 oracle:  canonical document  →  expected artifacts
    v2 oracle:  RAW SOURCE BYTES    →  its own units  →  expected artifacts

Three roles, three processes, none of them two of the roles. The oracle runs
under `python -I -S` with an import guard armed inside it; the comparator runs as
its own process, imports neither side, and is **the only process that hashes the
comparison** — whichever side hashes becomes the standard, and the point is that
neither is. Both files are checked by *import graph* as well as by guard: a
runtime guard proves what one run did, the syntax tree proves what the file can
ever do.

    170 pairs attempted · 164 judged · 6 UNJUDGED · 22 minutes · 0 GPU seconds

    exactly equivalent                             114
    divergent                                       50   (30.5%)
    stale escapes                                    4   ← gate FAIL
    typed invalidation consistent                77 / 77
    reference-locator-only pairs                    12
      of which the engine reported no change        12

**Four stale escapes, where the same-implementation oracle found zero on 34
pairs.** One is an undeclared specification detail: the engine unescapes HTML
entities in headings and the oracle does not, so `--bump <type>` and
`--bump &lt;type&gt;` produce different heading paths, different logical ids and
different bucket membership. The other three are pairs where the engine detected
**no change of any kind** and carried every artifact forward, while an
independent reading of the same bytes found changed content inside a modelled
unit. Moving the oracle's starting point is what made them visible.

**Two implementations of the same written specification disagree on 30.5% of
pairs.** On Wikipedia the engine derives four units where the oracle derives
one. This is a finding about the specification, not a defect rate of the
selective path, and it is why the permitted wording is *independent
implementation* and never *independent verification*. The protocol states the
limitation in its own §1 under `not_achieved`, before any result existed.

**All twelve reference-locator-only pairs were reported clean.** An instrument
built for a different question, on a cohort disjoint from workstream A's,
reproduced §CH's finding exactly. Two independent measurements, one conclusion:
when only a reference target moves, the system sees nothing.

Six pairs the oracle could not judge were reported `UNJUDGED`, and none was
counted as a pass. `sec_edgar` contributed zero judged pairs and is reported as
zero rather than back-filled.

## CJ. Workstream C — the claim matrix

`paper/CLAIM_MATRIX.yaml` carries seventeen claims. Each one binds exact wording
to a protocol, a receipt pinned by digest, a split, its limitations, the wording
that is **permitted** and the stronger wording that is **not**.

The matrix is only worth having if something refuses it, and
`tools/build_claim_matrix.py` does the refusing: a claim citing a receipt that
does not exist, whose bytes moved under it, or whose self-hash does not
recompute, is a failure; so is a claim missing a split, a status or either
wording list; so is any forbidden phrase appearing in a claim or anywhere in the
internal draft. Two tests poison the matrix deliberately to prove the refusals
fire.

Five claims are forbidden outright in any wording: general source-faithful
end-to-end correctness · model QA improvement over all semantic revisions ·
general forced-continuation superiority · P3b as evidence of a production
implementation · the 28-pair equivalence as an independent-oracle result.

Nine negative findings are published rather than buried, five of them held-out.
Five readiness gaps are named, including the two that bound everything: every
mechanism result is development-split, and no model was run.

`paper/TAVONEL_PAPER_DRAFT_INTERNAL.md` is the internal draft. It is marked
NOT FOR RELEASE, the IP gate is CLOSED in the matrix itself, and every public
channel is `FORBIDDEN`. `docs/ip/` is unmodified and a test asserts it.

## CK. What the two workstreams together establish

They were built for different questions and they answer the same one from
opposite sides.

Workstream A asked whether a loss is *declared*, and found that 52% of what the
grammar calls modelled cannot be carried at all, that the system says so most of
the time, and that in 30 of 310 held-out pairs it does not.

Workstream B asked whether the selective path agrees with a rebuild that never
saw its output, and found that it usually does, that the specification the two
share is under-determined in a third of cases, and that starting from raw bytes
surfaces stale escapes a canonical-document oracle structurally cannot.

Both are FAILs. Both were produced by instruments whose failure states are
reachable, whose gates were shown to have power, and whose bounds were declared
on grounds that are not the observed outcome. **A safety endpoint the system does
not meet, measured on held-out data by an instrument that could have said
otherwise, is the most useful thing this programme has produced.**

    494 tests green, 1 skipped.
    GPU 0 seconds · $0 · docs/ip/ unmodified · IP gate CLOSED.
    Programme status: PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT ESTABLISHED.

---

# Part 14 — The evidence-hygiene pass, and what survives it

Executed under the founder ruling of 2026-08-23, which accepted Part 13 as a
negative closure result *subject to corrections*. No GPU. No model endpoint. No
repair and no rescore of either frozen study.

## CL. Both studies fail a one-sided test

The ruling's wording is the whole section:

> if it cannot be demonstrated that no outcome-derived count/score/gate was
> inspected before the amendment, downgrade SFH1 from held-out to development
> diagnostic. Do not argue around this.

It cannot be demonstrated. `tools/evidence_hygiene_pass.py` derives the answer
mechanically from immutable receipt timestamps and file modification times —
artefacts written before anyone knew this test would be applied — rather than
from anyone's recollection:

    02:06:07  SFH1 smoke run, 8 lineages, receipt written and INSPECTED
              outcome keys: verdict, gates, summary, by_family, result_digest
    02:07:06  SFH1 full run #1 starts
    02:13:01  Workstream B smoke run, 6 lineages, receipt written and INSPECTED
    02:22:51  SFH1 protocol frozen  — after its own smoke run, and after the
              full run it governs had already started
    02:22:52  Workstream B protocol frozen — nine minutes after its smoke run
    02:41:16  SFH1 amendment frozen        (e946298b)
    02:41:47  Workstream B amendment frozen (e47993fc)
    03:10:17  SFH1 run #2 completes; its outcome metrics first exist
    03:33:20  Workstream B completes

Two receipts carrying outcome-derived metrics predate the amendments by 35 and
28 minutes. A third fact is worse and was not part of the ruling's test: **both
protocols were first frozen after the runs they govern had begun.** Neither ever
held the property its own header claims.

    SOURCE_FAITHFULNESS_HELDOUT_V1   held_out -> development_diagnostic
    ORACLE_INDEPENDENCE_V2           held_out -> development_diagnostic

The ruling ordered the first downgrade. The second fails the identical test on
identical evidence, and applying a test to one study but not the other would
leave the stronger-sounding claim standing on the weaker evidence.

`development_diagnostic` is deliberately a third value rather than a fold into
`development`: the difference between a study that was always development and
one that was demoted is exactly what a reader needs.

**Nothing else moves.** The 310 pairs, the 373,006 classified regions, the 0
unclassified, the 30 undeclared losses, the 164 judged pairs and the 30.5%
divergence are all exactly as executed. The pre-amendment executions stay
immutable and are marked superseded in a *new* receipt
(`pre-amendment-supersession`) rather than by editing them — editing a receipt
to record that it is superseded is a mutation of evidence in the name of
describing evidence. Full run #1 is `PARTIAL_EXECUTION_NO_RESULT_WRITTEN`: it
was stopped by hand and wrote nothing.

**Still held out:** `VALUE_BEARING_COHORT_V1`, `VALUE_BEARING_COHORT_V2` and
`STOP-V2-005`. The programme's held-out evidence is therefore its *negative
closure* evidence, not its mechanism evidence — and that distinction is now
carried explicitly in the draft's §1 and §6 and in gap `G-01`, so a negative
held-out study is never described as development-only.

## CM. The rename, and where it could not be applied

Workstream B's result is an **independent implementation differential study**,
not independent oracle verification. The two implementations share a
specification and that specification was written by reading the engine, so a
defect living in the specification is common-mode and this design cannot see it.

The rename lands where a name is actually asserted — the claim matrix, the
draft, this report. It does **not** land in
`protocols/ORACLE_INDEPENDENCE_V2.yaml`, which is frozen and byte-pinned at
`e47993fc…` by its own freeze receipt. Editing a frozen protocol to improve its
framing is the mutation every gate here exists to refuse, and the protocol's own
header already records that independence was not achieved and why.
`receipts/study-rename--*.json` binds old name to new and names both sets of
surfaces.

True independent verification would first require an independently checkable
reference semantics for the supported grammar. Labelling a second implementation
an oracle does not produce one.

## CN. Four oracle-relative divergences, confirmed the hard way

The ruling forbade strengthening the four reported stale escapes from the
differential result alone, and it is right to: a disagreement between the
production path and a second implementation says where to look, not what
happened. They were frozen as **oracle-relative divergences**, and the question
was then asked on the terms the ruling set —

    production clean full rebuild(new raw)  vs  production selective result(new raw)

— with freshly fetched bytes (never the cache, which is a copy and not
evidence), the production canonicaliser and the production compiler. The
independent implementation appears nowhere in the check.

**All four confirm.**

| case | clean rebuild moved | selective detected | carried though moved |
|---|---|---|---|
| `wikipedia:en:Three Villages` | 1 | *nothing* | `section:u:95960f72…` |
| `wikipedia:en:Monteceneri` | 1 | *nothing* | `section:u:0bf3fdf6…` |
| `wikipedia:en:Locarno` | 1 | *nothing* | `section:u:55f9943b…` |
| `git:pnpm/pnpm.io:docs/cli/change.md` | 6 | `evidence_moved`, `structure_changed` | `topic-bucket:…:0` |

In the three Wikipedia cases the selective path detected **no change of any
kind**, rebuilt nothing and carried all four artifacts forward, while a clean
full rebuild of the same bytes produces a different `section:` artifact.

**Four named cases are not a denominator.** Post-result forensic confirmation:
not a rate, not a rescore, and §5.2's receipt is untouched.

## CO. The root cause is not the one the table suggests

Each stale artifact's source difference was classified against a fixed, declared,
cumulative normalisation ladder — identical, whitespace, html_entities,
unicode_nfkc, typographic_punctuation, case, alphanumeric, substantive. The
first rung at which the two texts agree names the difference, so the answer is a
property of the pair rather than of the analyst:

    typographic_punctuation        1    curly quotes against ASCII quotes
    alphanumeric                   2    punctuation-only differences
    artifact_membership_or_order   1    a topic bucket whose membership moved

**Not one of the four is the compiler missing a substantive content change.**
Three are cases where the semantic diff correctly judged an edit non-semantic
and the artifact fingerprint moved anyway; the fourth is a plan-coverage gap on a
derived membership artifact. The defect is an alignment failure with a precise
shape:

> the diff's notion of "changed" and the fingerprint's notion of "changed" are
> two different functions, and nothing requires them to agree.

The consequence is not that an edit is lost. It is that **the selective state is
not reproducible by a clean rebuild** — quieter, and worse, because it means
every equivalence result this programme has produced was measured on pairs where
the two notions happened to agree.

## CP. What Part 14 leaves for the successor

`SOURCE_FACT_IR_V1` is the next main programme, and the ruling fixes its shape:
recognition by the parser is not representation, so `MODELED` splits into
`REPRESENTED_IN_COMPILED_STATE` and `RECOGNIZED_BUT_UNREPRESENTED`, and a
non-ignored source fact without a canonical representation is fail-closed.
Reference targets, language, accessibility and applicability metadata, effective
time, authority, canonical locator and provenance spans become first-class — not
stuffed into unit text — so a reference-target-only change produces a typed delta
and downstream invalidation even when the visible text is unchanged. Every
represented fact needs the whole chain:

    source witness -> canonical representation -> fingerprint -> dependency path

A missing link means the state cannot be called source-faithful CURRENT.

The repair is demonstrated on a **fresh disjoint held-out corpus**, with quotas
and family composition frozen from the acquisition frame before scoring. SFH1 is
not reusable for that purpose and is not reused. And the lesson from §CL binds
the successor directly: **a smoke run is an execution.** Running one on real
cohort lineages before the protocol is frozen spends the held-out property of
every lineage it touches and of the study around it. The successor smoke-tests on
fixtures only, and freezes before a single real lineage is read.

    Two studies demoted, no number changed.
    Four stale escapes confirmed against production alone; root cause: alignment.
    GPU 0 seconds · $0 · docs/ip/ unmodified · IP gate CLOSED.
    Programme status: PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT ESTABLISHED.

---

# Part 15 — SOURCE_FACT_IR, and the first genuinely held-out negative result

Executed under the founder ruling of 2026-08-23 (maximum parallel closure mode).
Eight lanes implemented simultaneously against one written contract, integrated
deterministically, frozen, then scored once on a fresh disjoint corpus. GPU 0
seconds, $0, `docs/ip/` untouched, IP gate CLOSED.

## CQ. The verdict

`SOURCE_FACT_IR_HELDOUT_V1` — **FAIL**.

    260 pairs · 128,715 source facts · 3 families · 3,448 s · 0 GPU seconds

    E1  no unclassified changed region        MET      0 violations   260 exercising
    E2  no recognized-but-unrepresented       FAILED   1,284          260
    E3  no silent loss in a complete scope    MET      0               81
    E4  no reference/locator-only clean miss  MET      0               30
    E5  no confirmed selective stale escape   SKIPPED  never exercised  0
    E6  selective/clean-rebuild equivalence   SKIPPED  never exercised  0
    E7  unresolved fails closed               MET      0              121

    REPRESENTED_IN_COMPILED_STATE   121,065
    UNRESOLVED_SOURCE_FACT            4,826
    IGNORED_BY_PREDECLARED_POLICY     1,540
    RECOGNIZED_BUT_UNREPRESENTED      1,284

**This is the programme's first held-out result that is actually held out.** The
protocol was frozen at `0531dd0e...` before one real lineage was read; the frame
was expanded and sealed after that; the study was smoke-tested on fixtures only.
The chronology that demoted SFH1 and the differential study does not exist here,
and the scoring tool refuses to run at all without a freeze receipt whose pinned
digest still matches the file.

## CR. Two of the three grounds for FAIL are absences

E5 and E6 are SKIPPED, and each fails the study on its own. They require
artifacts rebuilt from raw payloads and nothing in this run did that.

The temptation to call them "not applicable" and pass on the remaining five is
exactly the failure this vocabulary exists to refuse. **An endpoint nothing could
have violated has not been met — it has been avoided.** So the two questions
INC-V2-028 actually raised — is the selective state reproducible by a clean
rebuild, and do stale artifacts escape — have **no held-out evidence at all**
from this study. That gap is the largest thing this result does not cover, and it
is stated in C-22's limitations rather than left for a reader to notice.

## CS. The third ground is one kind, and it is link 1 of the chain

Every one of the 1,284 unrepresented facts is a `PROVENANCE_SPAN`, and every one
carries the same reason: the unit's text could not be located in the raw source.
1,048 git markdown, 124 Wikipedia, 112 eCFR.

The canonicaliser strips markup, collapses whitespace and joins blocks, so a
unit's text is generally not a substring of the bytes it came from. Three
declared location strategies recover the overwhelming majority — 121,065 facts
resolve — and for 1,284 units none of them does. Those units hold text in the
compiled state that **cannot be pointed back at any source bytes**.

Being exact about what that is and is not:

- it is **not** a lost edit. The content is present and its digest matches.
- it **is** a missing witness. No witness, no anchor; no anchor, and nothing
  downstream can attribute a source change to that unit; and the scope containing
  it cannot be called source-faithful CURRENT.

The old instrument could not have found this. It asked the grammar whether a
paragraph was modelled, the grammar said yes, and the grammar was *right* — the
text is carried. Whether the carried text is traceable to its source was not a
question the previous design could pose. Splitting `MODELED` into represented and
recognised is what made it askable, and the first thing the split found is a
failure the old vocabulary had no word for.

## CT. What was deliberately not done

**`_locate` was not improved and the study was not re-run.** Widening the
location strategies until 1,284 becomes zero, on the very corpus that produced
the 1,284, is fitting an instrument to its own result. The corpus is spent. The
repair, when attempted, is demonstrated on a fresh disjoint one or not at all.

**The two SKIPPED endpoints were not dropped.** They stay in the frozen protocol,
stay SKIPPED, and stay counted against the verdict.

**The eCFR shortfall was not absorbed.** eCFR admitted 70 against a quota of 100.
The floor of 200 and the three-family requirement were both met, and the quota
was not lowered afterwards — a quota moved after a count exists is not a quota.

**`sec_edgar` was declared absent before the run, not after.** Every predecessor
issuer is exhausted and fresh identifiers cannot be verified without acquisition.
Quotas were not redistributed to the remaining three families to keep the target,
because moving a quota to cover an absent family is tuning against yield by a
sympathetic route. This is a real narrowing of grammar breadth and it is recorded
as one.

## CU. GPU remains 0, and the gate now blocks for the right reason

The founder authorised the GPU successor study to be frozen and run without a
further wait **on a fresh held-out PASS**. There is no PASS.
`tools/gpu_successor_preflight.py` reports `BLOCKED` on
`G_GSP_HELD_OUT_PASS_PRESENT`, among others.

One correction was needed for that block to mean anything. The preflight had been
written against a guessed receipt stem (`sfh2-source-faithfulness`) before the
study existed. It would have blocked either way — but for the wrong reason, "no
receipt with that name" rather than "the study did not pass", and **a gate that
blocks for the wrong reason will one day unblock for the wrong reason too.** It
now reads `sfi1-source-fact-ir`, the study that actually ran.

    GPU authorisation: unchanged. 0 seconds, $0, cap ≤6 GPU hours / ≤$40 unused.

## CV. What parallel implementation cost, measured

Eight lanes, one written contract, one deterministic integration. Every lane's
own suite passed throughout. The integration found four defects no lane could
have found alone (`INC-V2-029`), and all four share one shape: **none of them
raised — each reported a clean result.**

- the IR module loaded twice under two names, producing two registries. An
  extractor was registered, tested, and produced nothing.
- witness `unit_path` was document-qualified on one side of the contract and bare
  on the other, so the resolver addressed invalidation to a document key that did
  not exist.
- an unsupported construct produced no fact at all; a section containing MathML
  scored perfectly.
- two lanes disagreed on percent-encoding, one reporting a false delta for a
  re-encoding of the same URI.

Finding that failure class in the import system, in a tuple convention and in a
normalisation rule — three mechanisms with nothing in common — is the strongest
evidence this programme has produced that the class is real rather than an
artefact of one component.

The fix for the third became load-bearing. `UNSUPPORTED_CONSTRUCT` is a facet
kind for constructs whose facet cannot be named, always UNRESOLVED, never
representable and never declinable by policy. It made E3 measurable for the first
time: you cannot count a fact that produced nothing, and detection converts the
absence into a fail-closed fact that a checkable question can be asked about. E3
was MET over 81 exercising pairs — a real measurement that did not exist a day
ago.

## CW. Where this leaves the programme

    held-out evidence      three preflight refusals · the endpoint infeasibility
                           · STOP-V2-005 · and now SFI1's FAIL
    development evidence   the mechanism results, and the four replayed cases
    development diagnostic SFH1 and the independent implementation differential
                           study, both demoted by the hygiene pass

The programme's held-out evidence is entirely negative, and that is now true by
measurement rather than by accident. Four separate designs have each declined to
produce the positive result their authors expected, and each declined for a
different, nameable reason. That is what the paper has.

    765 tests green, 2 skipped · ruff clean
    GPU 0 seconds · $0 · docs/ip/ unmodified · IP gate CLOSED
    Programme status: PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT ESTABLISHED
