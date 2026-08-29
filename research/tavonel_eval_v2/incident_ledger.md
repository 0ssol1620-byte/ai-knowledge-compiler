# TAVONEL eval v2 — incident ledger

Append-only. An entry is never edited after it is written; a correction is a new
entry that names the one it corrects.

---

## INC-V2-001 — sealed evidence drift, 4 files, no superseding receipt

- **Opened:** 2026-08-21
- **Raised by:** `research/tavonel_eval_v2/tools/verify_sealed_evidence.py`
- **Receipt:** `research/tavonel_eval_v2/receipts/p0-sealed-evidence-verification.json`
- **State:** `BLOCKED — founder decision required`
- **Effect on this programme:** none of the four files is an input to any v2 step
  executed so far. Nothing was modified, repaired, re-sealed or worked around.

### What was checked

192 sealed receipts under `docs/evidence/`, `docs/ip/receipts/` and
`research/experiments/*/receipts/`, carrying 434 `(path, sha256)` bindings.

| bucket | count |
|---|---:|
| bindings matching bytes on disk | 404 |
| bindings naming a path outside this working tree (container-internal `/opt/...`) | 22 |
| bindings superseded by a later receipt that pins the current bytes | 4 |
| **bindings drifted with no receipt binding the current bytes** | **4** |
| bindings whose target is missing | 0 |
| receipts whose declared self-hash recomputes | 127 |
| receipts declaring no self-hash field | 63 |
| **receipts whose declared self-hash does not recompute** | **2** |

### The four drifted files

| file | pinned by | pinned digest | digest on disk |
|---|---|---|---|
| `docs/audit/HOSTILE_REVIEW_2026-08-19.md` | `docs/ip/receipts/submission-package-index-2026-08-19.json` | `93420f8b…` | `c25ecbb4…` |
| `docs/repro/TEST_SCOPE_STATUS.json` | `docs/ip/receipts/submission-package-index-2026-08-19.json` | `0c12365d…` | `4f354e3e…` |
| `research/experiments/EXP-0101/receipts/committed-bytes-verification.json` | `research/experiments/EXP-0101/receipts/receipts.json` | `287003fa…` | `f4831788…` |
| `research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-dev-2026-08-19.json` | `…/receipts/v8-development-arm-run-2026-08-19.json` | `1d0f2a77…` | `c23c3b4b…` |

### The two self-hash failures

- `research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-dev-2026-08-19.json`
- `research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-holdout.json`

Both declare `receipt_sha256`; neither recomputes over the remaining keys under
the canonical encoding (`sort_keys`, `(",", ":")` separators, `ensure_ascii`
false) that every other sealing script in this repository uses. Either the
bytes changed after sealing, or these two receipts were sealed under a different
encoding that is not recorded anywhere. The first file appears in both lists.

### What was ruled out

- **Line endings.** Each drifted file was re-hashed as-is, CRLF→LF and LF→CRLF.
  No variant reproduces the pinned digest.
- **Committed bytes.** `git show HEAD:<path>` was compared for every drifted
  binding. No drifted file matches its pinned digest at HEAD either, so this is
  not "the working tree moved on from a reproducible commit".
- **Amendment.** Four further mismatches *were* explained this way and are
  reported separately as `SUPERSEDED_BY_LATER_RECEIPT`: for
  `tie_path_dependence.py`, `shadow-equivalence-rerun-pinned-2026-08-19.json`
  and `PATENT_CLAIM_SET_v1_2026-08-19.md` a later receipt in scope binds exactly
  the bytes now on disk. For the four above, no receipt anywhere in scope binds
  the current bytes.
- **Verifier false positives.** Three extractor defects were found and fixed
  before this entry was written: a document-canonical digest being read as a
  file-bytes digest, relative bindings resolved only against the repository
  root, and any `*_sha256` key being treated as a self-hash. Missing bindings
  went 173 → 0 and self-hash failures 13 → 2 as a result. What remains survived
  those fixes.

### What is NOT claimed

This entry does not claim the underlying results are wrong. It claims that four
sealed bindings and two receipt self-hashes no longer verify, so the chain from
those receipts to the bytes they describe is broken and cannot currently be used
as evidence. `question-set-v8-dev-2026-08-19.json` belongs to the stopped
same-intelligence study (W6/V8); the stopping decision itself is recorded
elsewhere and is not affected by this entry.

### Founder decision required

Not an agent's call, and deliberately left open:

1. whether each drifted file is an undocumented amendment that needs a
   superseding receipt written, or an accidental modification that needs the
   original bytes restored from backup;
2. whether the two W6 question-set receipts were sealed under a different
   canonical encoding, which would be a documentation gap rather than drift.

Until then the v2 programme treats these six artifacts as **unusable as
evidence** and cites none of them.

---

## INC-V2-002 — normalisation-invisible edit escapes invalidation

- **Opened:** 2026-08-21
- **Raised by:** `research/tavonel_eval_v2/tools/run_p1_smoke.py`, pair `git-020-book-ch04-01-what-is-ownership`
- **Receipt:** `research/tavonel_eval_v2/receipts/p0-oracle-independence.json`
- **Forensics:** `research/tavonel_eval_v2/artifacts/development/forensic/git-020-book-ch04-01-what-is-ownership/`
- **Reproduction:** `research/tavonel_eval_v2/tests/test_p0_findings.py`
- **State:** `OPEN — recorded, not repaired`
- **Gate:** `G_P0_EQUIVALENCE` FAIL

### What happened

One natural revision pair out of 26 was not artifact-exact against the
independent full rebuild. Two `section:` artifacts were carried forward while
the full rebuild produced different bytes for them — two stale escapes.

The revision is a real edit in `rust-lang/book`,
`src/ch04-01-what-is-ownership.md`. The entire difference in the two affected
sections is capitalisation:

| unit | difference |
|---|---|
| `u:139a7c0549681d70218e6101` | `w` → `W`, and `t` → `T` |
| `u:30a46678d68d4d23cd0c71d8` | `w` → `W` |

### Why it escaped

`akc_cir.identity.normalize_text_for_identity` casefolds. The semantic differ
compares units through that normalisation, so it saw no change and emitted no
`MODIFIED_CLAIM` for these two units. Nothing seeded the dependency traversal,
the two `section:` artifacts were labelled current, and they were carried
forward.

Artifact spec v1 stores the unit's **raw** text in the `section:` payload. The
independent full rebuild therefore produced different bytes. Verified directly:
raw text differs, `normalize_text_for_identity` output is equal.

### The general statement

> A selective compiler is only safe when the normalisation its change detector
> compares under is at least as fine-grained as the payload of every artifact
> that derives from it. Where the artifact payload is finer-grained than the
> detector's normalisation, the difference between the two is a silent stale
> window.

This is the same *shape* as the published structure-only defect — a real
difference that the comparison the compiler happens to run cannot see — on a
different axis. Reading order was the first axis. Text normalisation is the
second.

### What this says about the existing evidence — and what it does not

The H1-B/H1-F adapter behind the 28-pair Wikipedia result builds its section
artifacts from `normalize_text_for_identity(...)`, not from raw text
(`research/experiments/H1-B-REAL-REVISION-01/scripts/run_public_real_revision_holdout_v3.py`,
`artifact_hashes`). Detector and payload use the same normalisation there, so
this failure mode **could not have arisen** in that experiment. That is not a
defect in the 28-pair result; it is a boundary on it. The result holds for
artifacts whose payload is identity-normalised, and says nothing about
artifacts whose payload is not.

No claim is made here that any published number is wrong.

### Deliberately not done

The artifact specification was not changed to normalise the `section:` payload,
the parser was not changed to fold case, and the protocol was not amended. Any
of those would have turned a measured failure into a passing gate. The
divergence stands as the result.

### Open question for the founder

Whether artifact payloads should be required to be identity-normalised (which
makes this class of escape impossible but discards case and punctuation from
every derived artifact), or the change detector should carry a raw-bytes
channel alongside the normalised one (which keeps the payload faithful at the
cost of invalidating on edits that carry no meaning). This is a design decision
with a real trade-off, not a bug fix.

---

## INC-V2-003 — P0 identity-scope protocol/implementation mismatch

- **Opened:** 2026-08-21
- **Raised by:** independent review of the P0 v1 result
- **State:** `RECORDED — P0 v1 scope restated, not repaired`
- **Affects:** every P0 v1 identity, changed-set and rebuild figure. Not the
  isolation evidence, which is independent of which identity rule ran.

### The mismatch

`protocols/P0_master_protocol.yaml` §3 fixes P0's identity rule and its scope:

> `logical_id_rule.formula: 'u:' + sha256(source_id + "\n" + "/".join(explicit_path))[:24]`
>
> *Deterministic from the revision alone … Identity is therefore
> explicit-identifier-based in P0. Fuzzy cross-revision identity is out of P0
> scope and is P2's subject.*

The implementation derives that identifier and then hands both unit lists to
`diff_documents()` (`compiler/selective_build.py:195`). That function does not
compare identifiers. At `semantic_diff.py:525` it constructs a default
`LogicalIdentityResolver()` and at `:539` runs `assign_one_to_one` — a global
one-to-one assignment over weighted similarity signals, with
`MERGE_THRESHOLD = 0.92`, `NEW_IDENTITY_THRESHOLD = 0.75`, `_TIE_BAND = 0.05`
and the seven-signal weight vector in `identity.py:234`.

So P0 v1 declared deterministic explicit-path identity and ran production
fuzzy, global, threshold-and-tie-band identity resolution. The protocol reserved
that mechanism for P2.

### Consistent with the observed data

8 of 26 natural pairs carried an unresolved identity. Under the declared rule
`UNRESOLVED` is unreachable: an explicit path either matches a prior path or it
does not, and there is no score, no tie band and no ambiguity state. Every one
of those 8 is a product of the mechanism the protocol excluded.

### What it does and does not put in question

Contaminated — attributable to the wrong identity rule, in whole or in part:
identity outcomes, unresolved rate, the changed-logical-id set, the traversal
seed, rebuild fraction, work avoided, unnecessary rebuild fraction.

Not contaminated — established independently of which identity rule ran:

- the oracle isolation evidence, which concerns process, path and import
  structure;
- the four structural positive controls, whose units are byte-identical on both
  sides, so no identity decision changes their outcome;
- `INC-V2-002`, whose two escapes are carried-forward artifacts whose units
  matched on both rules — the escape is a normalisation-resolution mismatch, not
  an identity decision.

Whether the wrong rule changed the *equivalence verdict* is not asserted here.
It is measured in `receipts/inc-v2-003-impact-analysis.json`, which compares the
same corpus under both rules, and is produced only after the P0b protocol has
been frozen so that the comparison cannot be read back into the protocol.

### Disposition

P0 v1 is not re-run, re-scoped or re-labelled. It stands as `PARTIAL/FAILED`
development evidence whose identity-dependent figures carry this incident. P0b
is a new protocol, frozen before its results, that runs the mechanics the P0
protocol actually specified.

---

## INC-V2-002 — update, 2026-08-21: design ruled, mechanism validated in P0b

Amends nothing above. The original entry stands as written.

**Founder ruling (`FD-2026-08-21-03`).** Both repairs the entry named were
rejected. Identity normalisation and invalidation fidelity are separated
instead: a `LEXICAL` change dimension beside `SEMANTIC` and `STRUCTURAL`, and
per-artifact sensitivity carried by an input fingerprint. Artifacts needing raw,
case or punctuation fidelity depend on the lexical dimension; semantic-only
artifacts do not.

Design: `design/CHANGE_FACETS_AND_ARTIFACT_SENSITIVITY_v1.md`. One departure
from the ruling as stated is worth flagging: sensitivity is **observed** while
each artifact is built, not declared. A declaration can be wrong silently, which
is the failure this incident is about, one level up.

**First measurement, P0b** (`receipts/p0b-mechanics.json`, protocol
`sha256:e35cde9f…` frozen before the run). Four constructed lexical controls,
each the after revision of a natural pair with every unit's text upper-cased,
verified at construction to move every `LEXICAL` projection and no `SEMANTIC`
projection:

| control | changed facets | `section:` | `semantic-summary:` | rebuilt |
|---|---|---|---|---:|
| `lex-git-000-prometheus-configuration` | `LEXICAL` | 74 rebuilt | 74 carried | 74/154 |
| `lex-git-001-prometheus-configuration` | `LEXICAL` | 74 rebuilt | 74 carried | 74/154 |
| `lex-git-002-prometheus-configuration` | `LEXICAL` | 74 rebuilt | 74 carried | 74/154 |
| `lex-git-003-prometheus-functions` | `LEXICAL` | 60 rebuilt | 60 carried | 60/126 |

All four equivalent to the independent full rebuild, zero stale escapes. Under
global payload normalisation none of the 282 section artifacts would have
rebuilt and the escape would have recurred; under global raw-byte invalidation
all 588 artifacts would have rebuilt.

Observed sensitivity matched the pre-registered prediction on every artifact
kind: `section` `[LEXICAL]`, `semantic-summary` `[SEMANTIC]`, `document-index`,
`structure-map` and `topic-bucket` `[STRUCTURAL]`.

**State:** the escape class did not recur on the P0b corpus. The incident stays
`OPEN`. One development-split run is not confirmatory, the residual risk in
design §8 is unchanged — a change no facet projects is still invisible — and
nothing here is a performance result.

---

## INC-V2-003 — update, 2026-08-21: impact measured

Receipt: `receipts/inc-v2-003-impact-analysis.json`.

**Method.** A single-variable counterfactual, not a P0 v1 versus P0b diff. It
keeps artifact specification v1, the same dependency graph and channel
declarations, the same `plan_recompilation` call with
`StructuralPolicy.PRECISE`, and the same identity-normalised basis for deciding
a unit's content moved. Only the matching rule changes: explicit-path equality
in place of the resolver. The full-rebuild side is the P0 v1 oracle output,
which rebuilds the after revision from the after revision alone and so cannot
have been influenced by any identity rule.

**What the wrong rule changed** — 30 pairs:

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

**What it did not change:**

| figure | as executed | counterfactual |
|---|---:|---:|
| equivalence verdicts | 25/26 natural, 4/4 control | identical, pair for pair |
| stale escapes | 2 | 2 |

So the identity mismatch inflated the rebuild set on 6 pairs, produced all 26
unresolved decisions and 12 of the 56 unnecessary rebuilds — and changed no
equivalence verdict. In particular it did not cause `INC-V2-002`: those two
escapes reproduce identically under the identity rule the protocol specified.

**Disposition unchanged.** P0 v1's identity, unresolved, rebuild-fraction,
work-avoided and unnecessary-rebuild figures carry this incident and are not
cited without it. Its equivalence verdicts and isolation evidence do not.

---

## INC-V2-004 — a refusal raised by an exception carries no evidence reference

- **Opened:** 2026-08-21
- **Raised by:** `tools/run_p3.py`, scenario `BUILD_PREDICATE_RAISES`
- **Receipt:** `receipts/p3-failure-injection.json`
- **Gate:** `G_P3_ASSERTIONS` FAIL
- **State:** `OPEN — recorded, not repaired`

### What happened

P3 assertion A3, frozen before the run, requires that

> every refusal event carries the predicate that refused, its state, and at
> least one evidence reference, unless the predicate is one whose evidence is
> the pointer itself.

When a predicate raises, `knowledge_store.evaluate` converts the exception into
`GateResult(name, UNVERIFIABLE, (), type(error).__name__)`. The refusal that
follows names the predicate and carries the exception type as its reason code,
and its `evidence_refs` tuple is empty. An operator sees *which* predicate could
not evaluate and *what kind* of error stopped it, and has nothing to look at.

Every other refusal path in the run satisfied A3.

### Why it is a real gap and not a bad assertion

The exception path is the one where an operator most needs a pointer to
something — a predicate that fails cleanly at least names the artifacts that
failed it. Refusing correctly is not the same as refusing legibly, and the
contract as written asks for both. The failure is small and the fix is
plausible: carry the artifact or input the predicate was evaluating when it
raised, or state explicitly in the contract that the exception path has no
evidence and why.

Which of those is right is a design decision, so it is not made here.

### Deliberately not done

Assertion A3 was not amended to permit an empty evidence tuple, and
`knowledge_store.py` was not changed to synthesise one. Either would have turned
a measured failure into a passing gate after the result was known. `P3` stands
at `FAIL` on this one assertion, with sixteen other scenarios, both controls,
3,000 concurrent reads with zero mixed-state observations, and order invariance
over 120 permutations of twelve candidates all passing.

---

## STOP-V2-001 — P4 retrieval-validity preflight did not pass

Not a defect entry. A protocol gate refused, which is the outcome it exists to
be able to produce.

- **Recorded:** 2026-08-21
- **Receipt:** `receipts/p4-retrieval-validity.json`
- **Protocol:** `protocols/P4_retrieval_validity.yaml`, `sha256:c04d2063…`,
  frozen before any score was computed
- **Consequence:** no model arm, no spend request, no GPU. The programme stops
  here on the retrieval track.

### Result against the frozen thresholds

| gate | threshold | measured | |
|---|---|---:|---|
| `G_P4_SCALE` | ≥ 200 questions, ≥ 10 lineages | 182 questions | FAIL |
| `G_P4_DETERMINISM` | reversed insertion order reproduces every score | exact | PASS |
| `G_P4_TIE_CEILING` | tie rate ≤ 0.10 | **0.846** | FAIL |
| `G_P4_RETRIEVABILITY` | current unit in top 10 ≥ 0.90 | **0.346** | FAIL |
| `G_P4_SEPARATION` | current vs superseded score differs ≥ 0.90 on Q1 | 0.900 | PASS, at the line |
| `G_P4_CONTROL` | unchanged-control stability ≥ 0.95 | 1.000 | PASS |
| `G_P4_COST` | 0 GPU seconds, $0.00 | 0 / $0.00 | PASS |

Secondary: wrong-revision dominance on Q1 was 0.32, and the current unit was the
unique top-scoring document for 2.75% of questions.

### What failed, precisely

The two failures decompose cleanly, and they are not the same problem.

**The representation can separate revisions.** On Q1 questions — units whose
semantic facet moved — the current and superseded versions received different
scores 90% of the time. A lexical scorer over an append-only index is able, in
principle, to prefer one revision over the other.

**The questions do not find their own unit.** 154 of 182 questions ended in an
exact top-score tie, 141 of them with a tied set of five or more, and only 63
retrieved their oracle-current unit anywhere in the top ten. The query is built
from the document title and the unit's heading path, which is the right
discipline — an answer span copied into the query measures nothing — but heading
words such as "lead" or "overview" occur across a 1,753-unit global index, and
for the SEC family `source_id` yields a period-of-report date rather than a
title, so those queries carry almost no discriminating token at all.

So the preflight failed on **question construction**, not on the retrieval
representation. That distinction is the whole return on running this gate for
$0 rather than discovering it after a model arm had been paid for.

### Deliberately not done

No threshold was moved after the scores were seen. The tie policy was not
changed to break ties by position. The index was not silently widened to include
heading text, and the query was not silently widened to include answer tokens —
either would raise retrievability and would also destroy what the question is
supposed to measure.

### What a rebuild would require

A new protocol and a new cohort, per the handoff's stopping rule. The candidate
changes are known and are recorded here so that the next protocol is written
against a diagnosis rather than a guess:

1. index the heading path alongside the body, so a heading-derived query has
   something to match;
2. scope retrieval per document lineage rather than globally, or state that
   cross-lineage routing is part of what is being measured;
3. give the SEC family a real title field; a period-of-report date is not one;
4. build question intent from a source field that is discriminating and is still
   independent of the answer text.

None of these is applied to the current run. They are the input to the next
protocol, not a repair of this one.

---

## INC-V2-001 — update, 2026-08-21: provenance forensic complete

Amends nothing above. The original entry stands as written. Read-only: nothing
was re-sealed, restored, repaired, or given a superseding receipt.

- **Receipt:** `receipts/inc-v2-001-provenance-forensic.json`
- **Tool:** `tools/forensic_sealed_drift.py`
- **Git HEAD at time of run:** `46edd908b83d8d4390039a0db4d52ae56d917c8a`

### Sources searched, and their size

| source | distinct digests indexed |
|---|---:|
| git object database (`--batch-all-objects`, reachable or not) | 4,224 |
| archive members (every `.zip` in the tree) | 687 |
| working tree outside `.git`, `node_modules`, `.venv`, `.next`, `__pycache__`, `.mypy_cache` | 56,605 |

Blobs and archive members are hashed by streaming. An earlier version of this
tool read the whole object store and individual compressed members into single
buffers and exhausted memory; the index it builds is small, but the buffers it
built it from were not. That defect produced no result, only a crash.

### Result — 4 drifted bindings

| file | classification | pinned bytes found |
|---|---|---|
| `research/experiments/EXP-0101/receipts/committed-bytes-verification.json` | `ACCIDENTAL_MODIFICATION` | **yes** — git blob `e3055210` |
| `docs/audit/HOSTILE_REVIEW_2026-08-19.md` | `EVIDENCE_QUARANTINE` | no |
| `docs/repro/TEST_SCOPE_STATUS.json` | `EVIDENCE_QUARANTINE` | no |
| `research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-dev-2026-08-19.json` | `EVIDENCE_QUARANTINE` | no |

**Not one drift was classified as a documented intentional amendment.** No
`INTENTIONAL_AMENDMENT_DOCUMENTED` finding was produced, because for none of the
four does the repository record a reason for the change.

### The one recoverable file

`EXP-0101/receipts/committed-bytes-verification.json` is tracked, and the bytes
its receipt pinned survive in the object database as blob `e3055210`. Its three
most recent commits concern attestation refreshes. Nothing in those messages, in
a sibling file, or anywhere else records a decision to change this receipt, so
it is classified as an accidental modification rather than an amendment.

**The bytes were not restored.** Whether to restore them or to write a
superseding receipt is a founder decision, and the entry above left it open.

### Why the other three cannot be recovered — the mechanism

All three are **untracked and not git-ignored**. They exist only as working-tree
files that were never committed. There is therefore no history of them anywhere:
not in the object database, not in an archive, not in a backup directory, not
under another name in the tree. The single copy was overwritten in place, and
the bytes the receipt pinned no longer exist on this machine.

This is a finding about the sealing process, not only about three files. A
receipt pinned the digest of a file that was never committed, so the seal had
nothing durable behind it from the moment it was written. A hash binding is only
as recoverable as the least durable copy of the bytes it names.

### Two files are also generated

`docs/repro/TEST_SCOPE_STATUS.json` and `question-set-v8-dev-2026-08-19.json`
carry generator markers. A regenerated file with different content is still a
broken binding: the receipt names bytes, and these are not those bytes. It does
mean the *content* may be reproducible by re-running the generator — which would
produce a new artifact needing a new receipt, and would not re-establish the old
binding.

### The two self-hash failures

Unchanged and still unresolved, now with one fact added: for neither
`question-set-v8-dev-2026-08-19.json` nor `question-set-v8-holdout.json` does any
version anywhere in the searched sources have file bytes equal to the declared
`receipt_sha256`. Both are recorded as `UNRESOLVED_ENCODING_OR_DRIFT`.

That absence is reported, not read as proof. The declared value is a canonical
digest over the document rather than over the file bytes, so a byte match was
never expected; what is established is only that the declared digest does not
recompute over the document now on disk, and that no candidate version was found
that would explain it as an encoding difference.

### Quarantine

Three artifacts are placed in evidence quarantine:

- `docs/audit/HOSTILE_REVIEW_2026-08-19.md`
- `docs/repro/TEST_SCOPE_STATUS.json`
- `research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-dev-2026-08-19.json`

They are not cited in support of any claim, strong or weak, and their content is
not read back into any v2 result. `EXP-0101/receipts/committed-bytes-verification.json`
is not quarantined — its binding is broken but repairable, and the repair is the
founder's call.

None of the four is an input to any v2 step executed in this programme.

### State

`INC-V2-001` stays **BLOCKED — founder decision required**. The forensic narrows
the decision but does not make it: one file needs restore-or-supersede, three
need a ruling on how to record evidence whose bytes are gone, and two receipts
need a ruling on encoding versus drift.

---

## INC-V2-001 — note, 2026-08-21: the forensic ran twice, and what differed

Corrects two figures in the update above, which were transcribed from a run that
the receipt on disk no longer describes. It corrects nothing else.

Two invocations of `tools/forensic_sealed_drift.py` completed. The second
overwrote `receipts/inc-v2-001-provenance-forensic.json`; that file
(`generated_at 2026-08-21T06:51:01Z`) is the one whose self-hash recomputes and
the one every figure here is now taken from.

**Identical across both runs:** drift 4, recovered 1, quarantined 3, the
quarantine set itself, and the classification of each of the four bindings. The
git object database index was 4,224 digests both times.

**Different:** the archive index (690 → 687) and the working-tree index
(56,361 → 56,605).

The reason is a property of the tool worth stating plainly: it walks the whole
working tree, **including this programme's own namespace**, so its index grows
and shifts as the programme writes files. Between the two runs the consolidated
report, this ledger update and a test edit were written, and the first run's own
receipt existed during one walk and not the other.

That does not affect a finding. The question the tool answers is whether a
specific pinned digest is present in the index, and adding or removing unrelated
files cannot make a digest that was absent appear. But it does mean the index
sizes are not a stable property of the repository, and they should not be quoted
as though they were a measurement of it.

Both figures are corrected above. The earlier ones were not wrong when they were
read; they described a receipt that has since been superseded, which is the
distinction this ledger exists to keep.

---

## INC-V2-005 — mutable forensic receipt overwritten by a subsequent run

- **Opened:** 2026-08-21
- **Raised by:** founder review of the two-run forensic discrepancy
- **State:** `PLUMBING FIXED — historical loss permanent`
- **Class:** provenance defect. Not a wrong finding; a lost one.

### What happened

`tools/forensic_sealed_drift.py` wrote to a fixed path,
`receipts/inc-v2-001-provenance-forensic.json`. Two runs of it completed. The
second overwrote the first. The first run's receipt no longer exists.

The judgements happened to agree. That is not the point. **An evidence-producing
run destroyed the evidence of an earlier one**, and no receipt can now be shown
for the first.

### What may not be claimed

Not: *two independent receipts reproduced byte-identically.* One receipt exists.
The correct statement is that **the surviving run produced a reproducible
judgement**, and the figures quoted anywhere are the surviving run's.

The comparison recorded in the note above was made between a receipt in memory
and a receipt on disk, not between two artifacts. A real two-run reproducibility
check is owed, and it happens on the fixed infrastructure, not on this one.

### The plumbing, from now on

`tools/evidence.py`. Every experiment or forensic receipt written through it
carries:

| field | why |
|---|---|
| run-specific immutable filename `<stem>--<run_id>.json` | two runs cannot collide on a path |
| `receipt_sha256` over the whole envelope | the content is pinned by itself |
| `provenance.run_id`, `provenance.generated_at` | when, and which run |
| `provenance.tool` + `tool_sha256` | which code produced it |
| `provenance.protocol` + `protocol_sha256` | which contract it ran under |

`write_immutable` **refuses to overwrite** and has no force flag: it opens with
mode `"x"`, so even two processes racing on the same run id produce one success
and one loud failure rather than two silent winners. The only reason to want a
force flag is the failure this module exists to prevent.

`receipts/latest/<stem>.json` is a pointer, not evidence. Its body says so, and
it carries a path and a digest — never a finding.

### The receipts that predate it

They keep their paths. Relocating evidence to prevent evidence from being
relocated is the same act, and the founder ruling preserves the
P0/P0b/P2/P3/P4 results unmodified. Instead
`tools/register_legacy_receipts.py` pinned the file digest of all 21 of them in
an immutable register. That makes a later overwrite **detectable**, not
impossible, and the register says so in its own body rather than implying the
gap is closed.

One tool cannot be migrated at all: `tools/verify_sealed_evidence.py` is inside
the P0 v1 seal, so changing it to write immutably would break the seal it
exists to check. Its runs are wrapped instead —
`tools/seal_verification_envelope.py` writes an immutable receipt carrying the
raw output's digest, the verifier's digest and the totals.

### A dry run left a receipt, and it stays

The first invocation of `tools/inc_v2_001_disposition.py --dry-run` wrote an
immutable receipt whose body did not record that it was a dry run — readable
only as `restored: false`, which is ambiguous between "not attempted" and
"failed". The tool now records `mode`. The ambiguous receipt
(`inc-v2-001-disposition--20260821T080923Z-fb76632a81d0.json`) **was not
deleted or rewritten**; it is distinguishable by its `provenance.tool_sha256`,
which names the pre-fix tool. Immutability that bends for tidiness is not
immutability.

---

## INC-V2-001 — restoration event, 2026-08-21

Appends to the incident. **The incident is not closed.**

- **Authority:** founder ruling, 2026-08-21
- **Receipt:** `receipts/inc-v2-001-disposition--20260821T080937Z-cd6ed740dcde.json`
- **Tool:** `tools/inc_v2_001_disposition.py`
- **Verification:** `receipts/sealed-evidence-verification--20260821T081018Z-578301c32326.json`

### 1. Restored — one binding

`research/experiments/EXP-0101/receipts/committed-bytes-verification.json`

| step | value |
|---|---|
| bytes found on disk before | `sha256:f4831788…` |
| preserved as | `forensic_snapshots/INC-V2-001/committed-bytes-verification.json.pre-restoration` |
| snapshot digest | `sha256:f4831788…` |
| restored from | git blob `e305521066691b34219297c96d9968c7d51c73cf` |
| bytes on disk after | `sha256:287003fa…` |
| digest `receipts.json` pinned | `sha256:287003fa…` |
| **binding verifies** | **yes** |
| superseding receipt written | **no** |

The snapshot is written **before** the restore, on every invocation including a
dry run, because restoring is the act that destroys the current bytes. The tool
also refuses to overwrite an existing snapshot holding different bytes.

**What the drift actually was.** The file was regenerated against a later commit:
the pinned bytes attest 25 of 25 receipts at commit `82ca6c4`, the bytes found on
disk attest 27 of 27 at `e804a47`. Both report GREEN. The later attestation is
the *more complete* one — which is exactly why its bytes are preserved as
forensic material rather than discarded — but it is not what `receipts.json`
pinned, so it could not stand under that binding.

Nothing here claims the later attestation was wrong, or that restoring these
bytes re-establishes anything beyond this one binding.

**Measured effect**, sealed verifier re-run after the restore:

| | before | after |
|---|---:|---:|
| bindings matching bytes on disk | 404 | **405** |
| bindings drifted with no receipt | 4 | **3** |

The verdict stays `FAIL`, because three drifted bindings and two self-hash
failures remain. It was never going to become `PASS` from this.

### 2. Permanent historical evidence quarantine — three bindings

- `docs/audit/HOSTILE_REVIEW_2026-08-19.md`
- `docs/repro/TEST_SCOPE_STATUS.json`
- `research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-dev-2026-08-19.json`

The pinned bytes exist in no source on this machine. These bindings **cannot be
re-established**, and no future artifact may be presented as the evidence the old
receipts described.

**Regeneration rule, binding:**

> `old unrecoverable artifact != regenerated artifact`

Two of the three have generators and may be re-run. Any output takes a **new
artifact id, a new version and a new receipt**, and inherits nothing from the old
binding. Nothing was regenerated here.

### 3. `UNVERIFIED_SELF_HASH / EVIDENCE_QUARANTINE` — two receipts

- `…/receipts/question-set-v8-dev-2026-08-19.json`
- `…/receipts/question-set-v8-holdout.json`

Held until the canonicalisation recipe they were sealed under is *demonstrated*.
No encoding was guessed. Trying encodings until one reproduces the digest would
manufacture the provenance rather than establish it, and the artifact would then
carry a recipe chosen by its own answer.

### State

`INC-V2-001` remains **OPEN**. One binding is repaired; three are permanently
unrecoverable and two self-hashes are unresolved, and none of those five stops
being true because the sixth was fixed.

---

## INC-V2-006 — two real revisions changed the source and moved no projection

- **Opened:** 2026-08-21
- **Raised by:** `G_P0C_DIAGNOSTIC`, `UNCLASSIFIED_SOURCE_CHANGE` on natural pairs
- **Receipt:** `receipts/p0c-coverage-completeness--20260821T081849Z-4a2233f5cb22.json`
- **State:** `OPEN — recorded, not repaired`
- **Gate effect:** none. P0c passes. This is a reported finding, not a gate failure.

### The pre-registered prediction was wrong

P0c section 7 predicted that no natural pair would fire the diagnostic, on the
reasoning that every natural pair has at least one moved projection. Two did:

| pair | source |
|---|---|
| `git-013-website-deployment` | `kubernetes/website` `content/en/docs/concepts/workloads/controllers/deployment.md` |
| `git-019-book-ch04-01-what-is-ownership` | `rust-lang/book` `src/ch04-01-what-is-ownership.md` |

In both, the two revisions are real adjacent commits, the raw source digests
differ, and **every canonical unit is byte-identical**. The protocol said that if
this happened it would be reported as a finding about the canonicaliser. It is.

### What actually changed

`rust-lang/book`, two occurrences of an HTML comment:

    <!-- Old heading. Do not remove or links may break. -->
    <!-- Old headings. Do not remove or links may break. -->

`kubernetes/website`, a Hugo shortcode's target:

    {{< api-reference page="workload-resources/deployment-v1" >}}
    {{< api-reference page="apps/deployment-v1" >}}

The first is a comment addressed to editors and carries little for a reader. The
second is not: **it is a link destination**. The canonicaliser strips Hugo
shortcodes, so the compiled knowledge holds neither the old target nor the new
one, and nothing downstream can tell that the document now points somewhere
else. A consumer relying on this compiled state to answer "where is the
Deployment API reference" would be answering from a document whose answer moved.

### What this is, and what it is not

**It is not an equivalence failure.** The independent full rebuild sees the same
unit set and produces the same artifacts, so carrying forward was correct and the
state is consistent. Both revisions compile to the same knowledge because the
canonicaliser emits the same units for both.

**It is a coverage failure at the canonicaliser, not at the invalidator.** The
selective compiler cannot invalidate on a difference that never reaches it. The
blind spot is between the raw source and the canonical unit, one stage earlier
than every mechanism P0b and P0c measure.

**The diagnostic is what made it visible.** Without
`UNCLASSIFIED_SOURCE_CHANGE`, these two pairs are indistinguishable from a pair
where nothing happened, and the programme would have recorded "no change" for a
commit that moved an API link.

### Deliberately not done

The canonicaliser was not changed to emit shortcodes, comments or link targets
as units. Doing so mid-protocol would have converted a finding into an absent
one and changed the P0b/P0c corpora underneath results already produced. The
diagnostic fired, the finding is recorded, and the corpus is unchanged.

Nor was the diagnostic escalated into a rebuild. Rebuilding on it would have
produced identical artifacts at full cost and learned nothing — the artifacts
are not stale; the *unit model* is incomplete.

### Open question for the founder

Whether the canonical unit model should carry a fourth kind of content — link
targets and directive parameters — as first-class units, or whether an
out-of-band `source_digest` mismatch record is the right place for it. This is a
scope decision about what the compiler considers knowledge, not a bug fix.

### Scale, honestly

2 of 26 natural pairs. One developer-documentation corpus, one development split,
two source families, and the two firings are both `git_docs`. Nothing here
establishes a rate.

---

## INC-V2-002 — update, 2026-08-21: coverage invariant validated in P0c

Amends nothing above. **P0b is not amended** and its PASS stands on its own
projection.

- **Protocol:** `protocols/P0c_coverage_completeness.yaml`, `sha256:733deaf2…`,
  frozen before the run
- **Receipt:** `receipts/p0c-coverage-completeness--20260821T081849Z-4a2233f5cb22.json`
- **Verdict:** PASS, 9 of 9 gates, 43 pairs, 43 equivalent, 0 stale

### What the ruling asked for, and what was built

No fourth domain facet. A facet covers one more thing and leaves the same open
edge behind it. What was added is an invariant over the model already there:

> every input access a builder makes is attributed to a known facet, or the
> artifact cannot prove its coverage and may not be carried forward

Three mechanical consequences, in `facets/coverage.py`:

1. Access is recorded as a **(field, facet)** pair, not a bare facet.
2. An access to any field the projection map does not name is recorded as
   `UNCLASSIFIED` and **returns its value** rather than raising. Refusing it
   would let a builder be written around the check; recording it disqualifies
   the artifact and leaves the decision visible.
3. An artifact that read *nothing* is also unproven. It cannot be shown to be
   insensitive to its inputs — only shown not to have looked, which is the same
   evidential position.

A projection-completeness repair came with it: P0b attributed a `heading` read
to `STRUCTURAL`, but P0b's `STRUCTURAL` projection was not a function of
`heading`. P0c's is. Declared in the protocol before the run, and measured
after: **zero rebuild-set differences against P0b across all 34 shared pairs**,
matching the pre-registered prediction.

### Results against the frozen gates

| gate | result |
|---|---|
| `G_P0C_ATTRIBUTION` | PASS — no production builder made an unattributed access |
| `G_P0C_CARRY_BAN` | PASS — no coverage-unproven artifact was ever carried, on any pair |
| `G_P0C_PROBE_FIRES` | PASS — 3 of 3 probe controls recorded `UNCLASSIFIED` and were refused |
| `G_P0C_DIAGNOSTIC` | PASS — 3 of 3 positive controls fired, 0 of 3 negatives |
| `G_P0C_NO_GLOBAL_REBUILD` | PASS — no proven-coverage artifact rebuilt on a diagnostic |
| `G_P0C_EQUIVALENCE` | PASS — 43/43, 0 stale |
| `G_P0C_ISOLATION` | PASS |
| `G_P0C_SCALE` | PASS — 26 natural pairs plus all three control families |
| `G_P0C_COST` | PASS — 0 GPU seconds, $0 |

Observed sensitivity matched the pre-registered prediction on every kind,
including `coverage-probe: [UNCLASSIFIED]`.

### The residual is narrowed, not closed

What P0c establishes is that an access the model cannot classify is *visible*
and *disqualifying*. What it does not establish, and the protocol says so:

- the projection map is not shown to be complete. Attribution is measured
  against the map; the map's adequacy is not.
- a change inside a projected field that the projection maps to the same value
  is still invisible. Casefolding still folds case for `SEMANTIC`; that is what
  `LEXICAL` is for, and the next such pair is the next such pair.

The incident stays **OPEN**. And the diagnostic found something real on its
first natural corpus — see `INC-V2-006`.

---

## INC-V2-004 — update, 2026-08-21: repair validated in P3b, P3 v1 still FAIL

Amends nothing above. **P3 v1 stands at FAIL** on assertion A3, its subject
module is byte-unchanged, and its receipt is untouched.

- **Protocol:** `protocols/P3b_refusal_legibility.yaml`, `sha256:77de9cbe…`,
  frozen before the run
- **Receipt:** `receipts/p3b-refusal-legibility--20260821T082358Z-92483663a802.json`
- **Subject:** `activation/knowledge_store_p3b.py`, a new module
- **Verdict:** PASS, 7 of 7 gates, 19 scenarios, 13 refusals

### The contract was not weakened

A3 is carried over **verbatim**. It failed in P3 and it is the same sentence in
P3b. What changed is where the evidence comes from.

**A predicate no longer supplies the evidence for its own failure.** Every
predicate declares the part of the candidate it evaluates over — its *domain* —
and the framework resolves that domain to concrete references **before** calling
it. A predicate that raises on its first line still produces a refusal carrying
the artifacts or inputs it was about to read, because resolving them never ran
the predicate's code.

Every refusal now carries: predicate name · state (`UNVERIFIABLE` on the
exception path, never `PASS`) · a stable reason code · candidate state id ·
candidate state digest · evaluation event id · at least one evidence reference.

### Not recorded, deliberately

The exception **message** and the **traceback**. A message can carry a document
fragment, a path or a credential from whatever the predicate was reading, and
evidence that cannot be shown to an operator is not evidence. The reason code is
the exception's class name — stable across runs and across message changes, and
groupable.

To make that testable rather than asserted, the injected predicate raises with a
message containing `SENSITIVE-FRAGMENT-DO-NOT-RECORD /etc/secret token=abc123`.
Assertion A7 fails if any part of it reaches a refusal record. It did not, on any
scenario.

### Measured

| | P3 v1 | P3b |
|---|---|---|
| `BUILD_PREDICATE_RAISES` evidence refs | **0** | **9** |
| reason code | `RuntimeError` | `PREDICATE_RAISED:RuntimeError` |
| candidate state digest | absent | present |
| evaluation event id | absent | present |
| exception text in the record | none | none |

Two scenarios were added because they are where a naive repair falls back to an
empty tuple:

- **`RAISE_ON_EMPTY_DOMAIN`** — a predicate raises while its domain resolves to
  nothing. The refusal still carries a reference:
  `candidate-state:c-raise-empty-domain (declared_inputs is empty)`.
- **`RAISE_IN_EVERY_POSITION`** — each of the five predicates made to raise, both
  first and last in the conjunction. 10 of 10 satisfied the full field contract,
  with a single distinct reason code across all of them (A8).

### Enforced by the type, not only by a test

Constructing a `RefusalEvent` with no evidence reference **raises**, except for
the predicates whose evidence is the pointer itself — named explicitly, not left
as a general exemption. `G_P3B_STRUCTURAL_ENFORCEMENT` demonstrates both halves
in the run: the empty refusal raises, and the exempt predicate still constructs.

Without that gate, this run could have passed because no scenario happened to
produce an empty refusal — which is exactly what "no failures observed" meant for
the four P3 assertions that did hold.

### State

`INC-V2-004` is **repaired in `knowledge_store_p3b.py` and validated in P3b**. It
is not closed against `knowledge_store.py`, which is unchanged and still carries
the defect, and P3 v1's FAIL is not re-scored by any of this.

---

## INC-V2-007 — the first P4b run did not implement the protocol it ran under

- **Opened:** 2026-08-21
- **State:** `CORRECTED — both runs preserved`
- **Superseded run:** `receipts/p4b-retrieval-validity--20260821T082817Z-b85adb26e76a.json`
- **Conforming run:** `receipts/p4b-retrieval-validity--20260821T082931Z-465c768ca50c.json`

Recorded because the correction was made **after seeing a FAIL**, which is the
exact circumstance in which a change to measurement code is most suspect. The
justification therefore has to be the frozen text, not the result.

### The two defects

The frozen protocol states stage A's measures over **units**:

> `tie_rate_A`: questions whose maximum score is shared by two or more **units**
> `unit_top_1_A`: the oracle-current **unit** is the unique top-scoring unit

and section 6 states:

> ties are never broken by list position, index order, document id or any other
> incidental ordering

The first implementation scored index **documents** and read ranks off a
key-sorted list. Both revisions of one unit are two documents, so a question that
found its unit perfectly still registered as a tie, and `sorted(...)[0]` broke
every tie by document id — twice over, for the top pick and for the rank.

### What changed, and what did not

Changed: a unit's score is the best score among its revisions; rank is the
conservative position with every tied competitor counted against the target; the
top is the whole tied set rather than a member of it; `lineage_at_1` holds only
when **every** unit in the tied top set is in the correct lineage.

Not changed: no threshold, no field weight, no tie policy, no question
construction, no gate predicate. The protocol digest is the same
`sha256:a526fac2…` for both runs.

### Effect

| measure | first run | conforming run |
|---|---:|---:|
| `tie_rate_A` | 0.869 | **0.000** |
| `unit_top_1_A` | 0.080 | **0.792** |
| `unit_retrievable_at_10_A` | 0.958 | 0.968 |
| `lineage_at_1_B` | 0.314 | **0.141** |
| `unit_retrievable_at_10_B` | 0.779 | 0.914 |

The conformance fix moved `lineage_at_1_B` **down**, not up: refusing to break
ties by id removed 17 points of credit the first run had been taking from
incidental ordering. A correction that only ever helps the result is the one to
distrust; this one did not.

The verdict is FAIL either way.

### Why the superseded run still exists

Because of INC-V2-005. Under the old mutable-path plumbing the second run would
have destroyed the first, and this entry would have been a claim with nothing
behind it. Both receipts are on disk, both self-hash, and the two are
distinguishable by `provenance.tool_sha256`. This is the first time the
immutable receipt infrastructure was actually needed, and it was needed within an
hour of being built.

---

## STOP-V2-002 — P4b did not pass. No spend request.

Not a defect entry. A frozen gate refused.

- **Recorded:** 2026-08-21
- **Protocol:** `protocols/P4b_retrieval_validity.yaml`, `sha256:a526fac2…`,
  frozen before any score
- **Receipt:** `receipts/p4b-retrieval-validity--20260821T082931Z-465c768ca50c.json`
- **Consequence:** no model arm, no GPU, no paid inference, no spend request.
  312 questions, 12 lineages, 1,753 indexed units, $0.

### Result against the frozen thresholds

| gate | threshold | measured | |
|---|---|---:|---|
| `G_P4B_SCALE` | ≥ 200 questions, ≥ 10 lineages | 312 / 12 | PASS |
| `G_P4B_DETERMINISM` | reversed order reproduces every score | exact | PASS |
| `G_P4B_A_TIE` | ≤ 0.10 | **0.000** | PASS |
| `G_P4B_A_RETRIEVABLE` | ≥ 0.90 | **0.968** | PASS |
| `G_P4B_A_TOP1` | ≥ 0.60 | **0.792** | PASS |
| `G_P4B_B_LINEAGE` | ≥ 0.80 | **0.141** | **FAIL** |
| `G_P4B_B_UNIT` | ≥ 0.75 | 0.914 | PASS |
| `G_P4B_CONTROL_ARM` | ≥ 0.99 | 1.000 | PASS |
| `G_P4B_COST` | 0 GPU seconds, $0 | 0, $0 | PASS |

### Stage A: the targeting failure is fixed

P4's `retrievable@10` of 0.346 becomes **0.968** inside a lineage, with a **zero**
tie rate and 0.792 exact-first. The pre-registered prediction that a fielded
index would fix targeting holds: the fields a query names are now indexed fields
rather than absent from a body-only index.

This does **not** rehabilitate P4's representation. It replaces it.

### Stage B: routing does not work, for two reasons at once

`lineage_at_1_B` = 0.141 against a 0.80 bar. The diagnostic
(`receipts/p4b-lineage-diagnostic--20260821T083106Z-c81546b4d13d.json`, **not a
gate result**) separates two causes and finds both present:

1. **Cohort granularity.** 26 natural pairs are drawn from only **12** distinct
   source documents, and 21 pairs share their document with another pair. Two
   revision pairs of the same file are identical in title, document type, heading
   path and heading, so no question the protocol permits can route between them.
   The gate was partly measuring the corpus.
2. **The method, too.** Taking the same measure at source-document granularity
   gives **0.718** — still under 0.80. Granularity is not the whole story, and
   this is stated explicitly so the fix is not mistaken for a pass.

### Predictions, scored

| prediction | outcome |
|---|---|
| a fielded index fixes targeting | **held** — 0.346 → 0.968 within lineage |
| `LEXICAL_ONLY` near chance on revision selection | **falsified** — 0.690 current, 0.241 superseded, 0.069 undecided |
| SEC routing harder than git | **falsified, and in the opposite direction** — SEC 0.611, git 0.112 |

The SEC reversal has the same cause as the routing failure: SEC titles carry a
ticker and a CIK, which discriminate, while seven git documents contribute three
pairs each with byte-identical titles.

`LEXICAL_ONLY` picking the superseded revision on **24%** of revised units, against
`COMPILED_CURRENCY` at **100%**, is the contrast the programme exists to measure —
but it rests on **58** Q1 questions on one development corpus, and no rate is
claimed from it.

### What may not be said

- not that routing works. It was not demonstrated.
- not that the cohort granularity is the whole cause. It is not; 0.718 < 0.80.
- not that P4's representation was adequate. P4b replaced it rather than
  vindicating it.
- not that a passed stage A licenses spend. Stage B is the gate that stands
  between the programme and its first dollar, and it refused.

### What P4c needs

A new protocol and a new cohort: one revision pair per source document, or a
title field carrying the revision window; SEC titles that separate two filings of
the same form by the same issuer; and a routing method that does better than
0.718 at the granularity a question can address. This cohort is spent.

---

## INC-V2-008 — the coverage module shadowed an installed package

- **Opened:** 2026-08-21
- **State:** `CORRECTED — every affected run repeated, results identical`
- **Class:** a name collision that a subprocess hid and a test runner exposed.

### What happened

`facets/coverage.py` shares its name with the widely installed `coverage`
test-coverage package. Under `python -I -S` in its own subprocess, which is how
P0c executes, the namespace directory wins and the right module loads. Under
pytest, `coverage` is already in `sys.modules` before any path insert, so
`from coverage import FACETS` resolved to the installed package and the import
failed.

The failure was loud, which is the only reason this is a note rather than an
incident with a corrupted result behind it. Had the installed package happened to
export a name this code imports, it would have been silent.

### Correction

Renamed to `facets/facet_coverage.py`. A name change only: no projection, no
threshold, no rule, no gate predicate differs, and the frozen P0c protocol is
untouched at `sha256:733deaf2…`.

Every run that touched the module was repeated afterwards:

| protocol | verdict before | verdict after | gates |
|---|---|---|---|
| P0c | PASS | PASS | 9/9, 43/43 equivalent, 0 stale — identical |
| P3b | PASS | PASS | 7/7, 19 scenarios, 13 refusals — identical |
| P4b | FAIL | FAIL | same gate failing, every measure identical to 4 decimal places |

The superseded receipts remain on disk. Both the before and after runs of each
protocol can be compared by anyone who wants to check that claim, which is again
INC-V2-005's plumbing doing the work it was built for.

### The general point

A module in a namespace directory that shares a name with a common installed
package is a latent import hazard, and the hazard is invisible in exactly the
execution mode this programme relies on for isolation — `-I -S` in a subprocess.
The isolation that makes the oracle trustworthy is the same isolation that hid
this.

---

## STOP-V2-003 — P4c-Core FAIL. Global PASS. No spend request.

**Opened** 2026-08-22 · **Receipt**
`receipts/p4c-retrieval-validity--20260822T015247Z-448b82aa9ed8.json` ·
**Protocol** `P4c_retrieval_validity` v1, frozen before the cohort was scored.

Two endpoints, two verdicts, never combined:

| endpoint | verdict | gates |
|---|---|---|
| P4c-Core | **FAIL** | 5 of 8 |
| P4c-Global | **PASS** | 5 of 5 |

522 scored questions · 47 source documents · 4 families · 2,817 indexed units ·
0 GPU seconds · $0.

### What failed

| gate | bar | observed |
|---|---|---|
| `G_P4C_CORE_RETRIEVABLE` | ≥ 0.90 | **0.8621** |
| `G_P4C_CORE_TOP1` | ≥ 0.60 | **0.5441** |
| `G_P4C_CORE_Q1_SCALE` | ≥ 100 | **67** |

`G_P4C_CORE_TIE` (0.0), `G_P4C_CORE_HARNESS` (1.0) and all three shared gates
passed. The harness control passing is what makes the failure readable rather
than void.

### Cause, per family

| family | questions | target in top 10 | unique top 1 |
|---|---|---|---|
| sec_edgar | 18 | 1.000 | 1.000 |
| encyclopedia_wikipedia | 225 | 1.000 | 0.760 |
| git_docs | 87 | 0.966 | 0.828 |
| **regulation_ecfr** | **192** | **0.641** | **0.120** |

The failure is one family. **80.7% of the eCFR questions have a leaf heading that
tokenises to the empty string** — the heading is an enumerated paragraph marker,
`(a)`, `(3)`, `(c)`. Every sibling subsection inside the section shares the same
document title and the same parent heading, so under an answer-independent
construction rule the query carries *no* term that distinguishes one subsection
from another. The observed rank distribution over those questions is close to
uniform across the section's units, which is what an uninformative query produces
and not a property of the representation.

This is a limit of question construction against enumerated regulatory text at
this unit granularity. **It is not fixed by relaxing §3's forbidden list.** Taking
a token from the body to name the subsection is precisely the answer leakage the
protocol was frozen to exclude, and doing it after seeing a FAIL would be the
INC-V2-007 mistake with none of INC-V2-007's justification.

Removing eCFR gives 330 questions at 0.9909 top-10 and 0.7909 top-1, both above
the bars. **That is a diagnostic decomposition, not a result and not a pass.**
The gate is defined over the frozen cohort, the cohort included eCFR by
pre-registered selection, and P4c-Core stands at FAIL.

`G_P4C_CORE_Q1_SCALE` failed for a separate reason: adjacent revisions of a long
encyclopedia article or a CFR section move very few units, so the cohort yielded
67 Q1 questions (eCFR 29, SEC 17, Wikipedia 15, git 6). The gate was written to
stop a rate being claimed from a handful, and it did that job — see below.

### P4c-Global passed, and that is the informative half

| measure | bar | observed |
|---|---|---|
| `lineage_at_1` | ≥ 0.80 | **0.9732** |
| unit in top 10 | ≥ 0.75 | 0.8563 |
| tie rate | — | 0.0 |

P4b's global routing failed at 0.141. The only thing that changed is the
independence rule: one revision pair per source document. That is direct
confirmation of the P4b diagnosis — three pairs of the same file competing as
separate routing targets while identical in every field a question may name was
measuring the corpus, not the method. It is **not** evidence that the method
improved; nothing about the representation changed.

Global's unit-retrieval (0.8563) is within 0.006 of Core's (0.8621). With an
independent cohort, opening the whole corpus costs almost nothing — the
within-document targeting is the binding constraint, which is the reverse of P4b's
shape.

### Predictions, scored

| prediction | outcome |
|---|---|
| SEC routing looks worse than in P4b | **confirmed** — global `lineage_at_1` for SEC is 9/18 = 0.50. P4b's strong SEC routing was reading the CIK out of the query |
| global is harder than core | **direction correct, magnitude nil** — 0.8563 vs 0.8621. The gap is not the interesting quantity it was expected to be |
| `LEXICAL_ONLY` selects the superseded revision at a non-trivial rate | **observed, not claimed** — 18 superseded / 42 current / 7 undecidable of 67. `G_P4C_CORE_Q1_SCALE` failed, so no rate is stated |
| regulation and encyclopedia differ | **confirmed, strongly** — 0.641/0.120 against 1.000/0.760, and the cause is identified above |

`COMPILED_CURRENCY` selected the current revision on 67/67. Per the frozen claim
boundary this is a harness control and is **not** quoted as a TAVONEL result.

### Consequence

- **No GPU request is made.** P4c-Core did not pass, so the precondition does not
  exist. GPU 0, paid API 0, spend $0 continues.
- The global end-to-end GPU endpoint is unaffected by Core's failure in the other
  direction: Global passed, but Core is what gates a controlled
  same-intelligence experiment, and it did not.
- P4, P4b and P4c all stand at FAIL and none is re-scored.
- Thresholds are not adjusted. A bar moved after seeing the number it failed is
  not a bar.

### Open for a decision that is not an agent's

Enumerated regulatory subsections are not addressable by answer-independent user
intent at this unit granularity. There are at least three responses — a coarser
unit for enumerated text, a family-specific permitted-intent rule, or accepting
that this family is out of scope for retrieval measurement — and choosing among
them changes what the product claims to retrieve. That is a scope decision.

---

## Status vocabulary, fixed by founder ruling 2026-08-22

`PROVEN` is not available as an overall status for this programme, and was
withdrawn from the Part 3 summary. The binding overall status is:

    PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED

P4c-Core stands at FAIL, the untouched confirmatory split is unopened, and no
model endpoint has been executed. Protocol-level verdicts are unaffected: a gate
that passed still passed.

**A protocol `PASS` is a statement about that protocol's gates and nothing
wider.** In particular **P0d's `PASS` does not mean source coverage is
adequate.** It means the coverage measurement, the span partition and the
fail-closed currency rule behaved as the protocol specified. The measured result
on natural data — **26 of 26 pairs `SOURCE_COVERAGE_INCOMPLETE`** — stands
unchanged and is not to be softened, and no coverage adequacy threshold is
declared retroactively. If one is ever needed it is declared in a new protocol on
data separated from development.

---

## INC-V2-009 — the first P4d run ranked over indexed rows, not over envelopes

**Opened and corrected** 2026-08-22. Both receipts preserved:
`p4d-retrieval-granularity--20260822T022753Z-cc4b49a27fc0.json` (defective) and
`--20260822T022902Z-b4e65b1bf1ee.json` (conforming).

This is the INC-V2-007 class again, in a new module.

P4d's frozen protocol §4 states measures over **envelopes** in mode A, and P4c
§6 had already settled the general form: two revisions of one thing are two
indexed documents and one logical unit. The first implementation passed an
identity map to the ranking function, so an envelope's current and superseded
rows competed as two separate targets. Because both revisions of an envelope
carry the same title, doc type, heading path and heading, and mode-A queries name
only those fields, the two rows score identically **by construction**. Every such
question therefore produced a two-way tie with itself.

Observed: tie rate 0.705, and 368 of 522 tied sets had exactly size 2.

### The correction and its direction

`envelope_unit` maps both revisions of an envelope onto one logical key, which
is what §4 and P4c §6 require.

| measure | defective run | conforming run |
|---|---|---|
| tie rate | 0.7050 | **0.0** |
| envelope retrievable @10 | 0.9828 | **1.0** |
| envelope unique top-1 | 0.2203 | **0.8467** |
| atom recoverable | 1.0 | 1.0 |

**This correction moved numbers sharply up, and that is the kind of correction
to distrust.** INC-V2-007's fix moved its headline *down*, which is part of why
it was easy to accept. This one is stated on its justification rather than its
effect: the frozen protocol names envelopes as the measurement granularity, the
defect made an object compete against itself, and a self-tie is not a retrieval
result under any threshold. No gate predicate, weight, tie policy, question
construction or cohort changed. The verdict is **FAIL either way** — the two
gates that fail are untouched by this correction.

### Second defect, documentation only

`leaked_tokens` carried a docstring claiming anchor-heading tokens were removed
before the leakage check. The code never did that, and the code is what conforms
to frozen §3 ("any overlap beyond a declared function-word list is leakage").
The docstring was corrected to describe the code. The predicate was **not**
touched — see STOP-V2-004.

---

## STOP-V2-004 — P4d-Core-Semantic FAIL. Citation PASS. No spend request.

**Opened** 2026-08-22 · **Protocol** `P4d_retrieval_granularity` v1,
`sha256:e3fd7edf9537d126a94c7fbc8a03ca90e3bc155377d3d7c655e87e8ff228c5e6`,
frozen before any envelope was built · **Receipt**
`p4d-retrieval-granularity--20260822T022902Z-b4e65b1bf1ee.json`.

| endpoint | verdict | gates |
|---|---|---|
| P4d-Core-Semantic | **FAIL** | 7 of 9 |
| P4d-Citation | **PASS** | 4 of 4 |

522 scored questions · 4 families · 2,817 canonical atoms · 2,331 envelopes ·
mean 5.97 members · 0 GPU seconds · $0.

P4c is untouched: Core stays FAIL, Global stays PASS, neither is re-scored, and
P4d does not repair either.

### What the envelope layer did

The founder's diagnosis is confirmed, and it is the substantive finding:

| family | P4c atom top-10 / top-1 | P4d envelope top-10 / top-1 |
|---|---|---|
| regulation_ecfr | 0.641 / 0.120 | **1.000 / 0.891** |
| encyclopedia_wikipedia | 1.000 / 0.760 | 1.000 / 0.822 |
| git_docs | 0.966 / 0.828 | 1.000 / 0.782 |
| sec_edgar | 1.000 / 1.000 | 1.000 / 1.000 |

**The two columns measure different targets** — an atom in P4c, an envelope in
P4d — so they are not the same metric and the rows are not a before/after of one
quantity. What they do show is that the family which could not be addressed at
all becomes the best-addressed one once the addressing layer stops demanding
that `(a)` carry semantic intent. eCFR was the pre-registered place for this to
appear, and it appeared there.

`atom_recoverable_from_envelope` is **1.0** on every family. The window is not
buying retrievability by losing the atom, which was the pre-registered risk.

### What failed

| gate | bar | observed |
|---|---|---|
| `G_P4D_NO_LEAKAGE` | 0 | **475 of 522 questions** |
| `G_P4D_Q1_SCALE` | ≥ 100 | **67** |

**`G_P4D_Q1_SCALE`** is inherited from the cohort, not caused by the envelope
layer. P4c produced 67 Q1 questions because adjacent revisions of a long article
or a CFR section move few units, and P4d reuses that cohort deliberately so the
addressing layer is the only variable. It is the same shortfall, unrepaired.

**`G_P4D_NO_LEAKAGE` exposes a contradiction inside the frozen protocol, and
the contradiction is not resolved here.** §3 lists the document identity, the
document type, the anchor heading and its parent as *permitted* intent sources.
§3 also defines leakage as any query/body token overlap outside a declared
function-word list. Those two clauses cannot both hold on real text: a section
headed "Adding dependencies" in the uv documentation says "dependencies" and
"uv" in its body, so a query built entirely from permitted sources overlaps its
own answer.

Of the 475 failing questions, 105 leak only anchor-heading tokens and 370 leak
tokens that are also document identity or parent heading. **Not one leaks an
answer span**, which is what the gate was written to catch.

The predicate was **not** edited. A gate relaxed after it fails is not a gate,
and this failure was seen before any change could be contemplated. The frozen
text says what it says and the run reports it. Resolving the tension needs a
successor protocol that states the leakage predicate against the *complement* of
the permitted intent sources rather than against the whole body — declared
before results, on a protocol frozen for that purpose.

### P4d-Citation — PASS

Source-native locators route to the exact canonical atom on **0.9931** of 577
eCFR citations; 0.0069 are ambiguous. Only `regulation_ecfr` was declared as
having a citation scheme, and the declaration was made in the tool before the
run rather than inferred from family names.

Per the founder's ruling this is **not** answer leakage: an official citation is
an address the source publishes and a reader already holds, naming where to look
and never what is written there. Per the same ruling it is **never mixed into
mode A**, carries its own verdict, and may not raise any semantic figure.

### The envelope contract held

Every property was checked in the run rather than asserted in prose:

- every envelope reports `kind = DERIVED_RETRIEVAL_ARTIFACT` and
  `authoritative = False`
- every envelope records its member logical ids
- every dependency edge is typed and points at a canonical atom
- every returned evidence record is a canonical atom, and none carries
  envelope-level text
- invalidation is exact: 58 envelopes contain a semantically moved atom and
  exactly those 58 are invalidated, from 68 moved atoms

### Consequence

- **No GPU request, no model study proposal.** P4d-Core-Semantic did not pass.
  GPU 0, paid API 0, spend $0 continues.
- Programme status stays `PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET
  ESTABLISHED`.
- P4, P4b, P4c and P4d-Core-Semantic all stand at FAIL. None is re-scored.
- DART stays `BLOCKED_MISSING_CREDENTIAL` and blocks nothing.

### Open for a decision that is not an agent's

The leakage predicate and the permitted-intent list contradict each other on
real text. A successor protocol must state which one governs — most plausibly by
checking the query against the body *minus* the permitted intent sources — and
that choice determines what "answer-independent" means for every later
retrieval result. It is declared before results or it is worthless.

---

## P4e — Core PASS, 12 of 12. The binding constraint moved to source coverage.

**Opened and closed** 2026-08-22 · **Protocol** `P4e_provenance_retrieval` v1,
`sha256:a6060213407fce8da9622979cb97c5e522ed30e942719c6c92e55141e46366d6`,
frozen before the cohort was scored · **Receipt**
`p4e-provenance-retrieval--20260822T080030Z-4f1f2fdaa1ab.json` ·
**Cohort receipt** `p4e-cohort-manifest--20260822T075642Z-5039a951e220.json`.

P4d is read-only. Its protocol, both execution receipts, INC-V2-009, STOP-V2-004
and its Core-Semantic FAIL / Citation PASS verdicts stand unchanged. P4d's
leakage predicate was **not** amended and P4d was **not** re-scored.

720 scored questions · 56 source documents · 4 families · 2,331→ new envelopes ·
0 GPU seconds · $0.

### Leakage redefined as provenance, and enforced structurally

The query builder no longer receives a document. Its only argument is an
`IntentView` that:

- refuses **at construction** to carry any field outside the five permitted
  intent sources — a view that accepted the field and then declined to return it
  would still have put it in the builder's memory;
- defines `__slots__`, forbids attribute assignment and is not iterable, so the
  constructor's whitelist is the whole story;
- records every read with its source, and a query field with **no** provenance
  record fails the gate exactly as a forbidden source does.

| gate | result |
|---|---|
| `G_P4E_PROVENANCE` — every query field's provenance is a permitted source | PASS |
| `G_P4E_NO_FORBIDDEN_CONTRIBUTION` — forbidden contribution == 0 | PASS, 0 |
| `G_P4E_NO_BODY_ACCESS` — single restricted argument, no forbidden name in the builder's AST | PASS |
| `G_P4E_REVISION_NEUTRAL` | PASS, 18 questions excluded as `INELIGIBLE_INTENT_CHANGED_ACROSS_REVISIONS` |
| `G_P4E_CONTROLS_REJECTED` | PASS — both negative controls rejected |
| `G_P4E_SCALE` — ≥250 questions, ≥40 documents, ≥4 families | PASS, 720 / 56 / 4 |
| `G_P4E_Q1_SCALE` — ≥100 | PASS, **175** |
| `G_P4E_ENVELOPE_RETRIEVABLE` — ≥0.90 | PASS, 0.9903 |
| `G_P4E_ATOM_RECOVERABLE` — ≥0.95 | PASS, **1.0** |
| `G_P4E_COVERAGE_RECORDED` | PASS |
| `G_P4E_DETERMINISM` | PASS |
| `G_P4E_COST` | PASS, 0 / $0 |

The negative controls are what make the first two gates evidence rather than
assertion. `ctrl-body-token-injected` hands the view an `atom_body` field and is
refused with `ForbiddenIntentSource`; `ctrl-current-only-heading` presents a
heading that exists only in the current revision and is refused as
`INELIGIBLE_INTENT_CHANGED_ACROSS_REVISIONS`. A gate that cannot be made to fail
on purpose has not been shown to work.

### The diagnostic that used to be a gate

**Lexical overlap is present on 0.9097 of questions** — as high as it was in
P4d, where it failed 475 of 522. Under the provenance definition that is not a
finding about leakage at all, and the two numbers standing side by side is the
point of reporting both. It is recorded as `DIAGNOSTIC_ONLY` and is not gated.

### Wider revision spacing did what it was declared to do

`Q1 = 175` against P4d's 67, on a bar of 100 that was **not moved**. The only
change to pair selection was the frozen spacing rule — Wikipedia's newest
revision paired with the newest at least 180 days older, eCFR's newest dated
version paired with the oldest the versioner reports. Neither clause can see a
unit count, a score or the Q1 total. P4d's 67 stays FAIL.

### The finding: coverage eligibility, not retrieval, is now the constraint

**20 of 720 questions are `QUESTION_LOCAL_COVERAGE_COMPLETE` — 0.0278.** The
GPU-confirmatory candidate pool is therefore 20 questions.

**That figure is dominated by the coverage instrument, not by the corpus, and
must not be read as a property of the sources.** The locality rule was declared
before it was applied and has two branches:

| granularity | families | questions | can grant local completeness? |
|---|---|---|---|
| character offsets | git_docs (markdown) | 87 | yes — positional locality |
| parser events | wikipedia, eCFR, SEC (HTML/XML) | 633 | only if the *whole document* has zero unmodeled facts |

So **88% of the questions were measured by a rule that can only under-grant.**
All 20 locally-complete questions are git_docs, where the localisable share is
**20 of 87 = 0.23**. Of the other 67 markdown questions, 41 were refused because
no modeled span could be placed in scope and 26 had a relevant unmodeled
construct in range.

Stated plainly: **local coverage completeness is currently only *measurable* on
markdown sources.** For HTML and XML the instrument cannot localise an unmodeled
fact to an atom, so it conservatively refuses — which is the correct direction
for a fail-closed rule and the wrong basis for a cohort.

P0d's result is untouched: **26 of 26 pairs remain `SOURCE_COVERAGE_INCOMPLETE`,
and no document revision here is called globally CURRENT or source-faithful
end-to-end.** A question-local status is never a claim about its document.

### Predictions, scored

| prediction | outcome |
|---|---|
| wider spacing raises Q1 | **confirmed** — 67 → 175 |
| lexical overlap stays high and no longer matters | **confirmed** — 0.9097, ungated |
| some questions excluded as intent changed | **confirmed** — 18. A zero here would have meant the neutrality check was not reaching the field |
| question-local coverage far from universal | **confirmed, and more so than expected** — 0.0278, with the instrument identified as the dominant cause |

### Consequence

- **P4e-Core passed every gate, so a model study is now eligible to be
  PROPOSED.** The proposal is written and submitted at
  `MODEL_STUDY_PROPOSAL_2026-08-22.md`. **No GPU has run and none is started
  until that proposal is approved.**
- The proposal's own source-coverage eligibility section reports 20 eligible
  questions and says plainly that this is not a viable confirmatory cohort. The
  recommendation inside it is coverage-instrument hardening first.
- Programme status stays `PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET
  ESTABLISHED`.
- P4, P4b, P4c-Core and P4d-Core-Semantic all remain FAIL. None is re-scored,
  and P4e repairs none of them.
- GPU 0, paid API 0, spend $0.

### Open for a decision that is not an agent's

Extending positional locality to HTML and XML sources is the next
source-coverage work and it is ordinary engineering. What is not an agent's call
is whether a 20-question confirmatory cohort is ever acceptable, and whether the
model study waits for the instrument or runs on markdown alone with the
narrowing stated. Both choices change what the paper can claim.

---

## Source Coverage Locality v2 — PASS 7/7, 8/8 controls. Decision gate: expand.

**Opened and closed** 2026-08-22 · **Protocol** `SOURCE_LOCALITY_V2`,
`sha256:37db14dc9db77e465b4ad6b4876b35dc3a993e5509b6f59388a81103c8395adc`,
frozen after the instrument was completed against development fixtures and
**before** it touched the cohort · **Receipt**
`locality-v2--20260822T084840Z-5c1f0581ac04.json`.

P4e is not re-scored. Its 720 questions, Q1 = 175, envelope retrievable@10 =
0.9903, atom recovery = 1.0 and provisional locally-complete = 20 stand exactly
as recorded. Locality v2 is a **separate measurement by a different instrument
on the same frozen cohort**, recorded under its own name.

P0d's classifier `source_spans.py` was not edited. The new instrument lives in
new modules with their own digests — the honest way to change an instrument is a
new protocol, not an edit that silently moves an older sealed result.

### What v1 got wrong, in both directions at once

| defect | direction | effect on P4e's figure of 20 |
|---|---|---|
| markdown interval rule missed dependencies outside the atom's range | **over-grant** | some of the 20 may not have deserved it |
| HTML/XML events carried no position, so a document-level rule applied | **under-grant** | 633 of 720 questions could not be granted at all |

Both were live simultaneously, which is why the figure could not be read as a
property of the corpus and was not reported as one.

### The witness

`QUESTION_LOCAL_COVERAGE_COMPLETE` is now granted only from an explicit
`SOURCE_COVERAGE_WITNESS` — the dependency closure over the atom's direct span,
its envelope members' spans, reference and link definitions it uses,
include/directive targets and arguments, anchor and citation dependencies, and
the spans that produced its canonical facts. Every element records the role that
admitted it and why. A closure that existed only inside a boolean could not be
argued with.

Two rules were added **because a control caught them failing**, not by
inspection:

- **line-scoped dependency regions.** A reference definition's grammar span
  stops at the first whitespace inside its target, so following the identifier
  reached the definition but not the region it points at. Widening to the lines
  the dependency occupies is the syntactic unit the source itself defines.
- **`UNRESOLVED_INCLUDE_TARGET`.** An include names content not present in this
  source, so nothing about its coverage is established. Calling it MODELED
  because the directive parsed would be reading the signpost and reporting the
  road.

### Positional provenance for markup

`raw interval → parser event → canonical fact`, built forward from the parser
rather than inferred backwards. `HTMLParser.getpos()` gives each event's start;
events close at the next one's start, so intervals partition the source in
reading order. `convert_charrefs` is off, because with it on adjacent text and
character references merge into one event whose reported position is the start
of the merged run — an almost-right interval.

Where position cannot be proven it is **not guessed**: the span is
`LOCATION_UNVERIFIABLE`, cannot support completeness, and because an unlocatable
element cannot be shown to lie outside the closure it is treated as inside it.

**Across the entire cohort, `LOCATION_UNVERIFIABLE` = 0.** The source map
located every event in every document. Position is no longer the constraint.

### Controls — 8 of 8, both directions

Built on development fixtures with no relation to the cohort, and completed
before the instrument was frozen.

| control | expects | got |
|---|---|---|
| `direct_span_positive` | COMPLETE | COMPLETE |
| **`out_of_range_link_definition`** | INCOMPLETE | INCOMPLETE |
| `include_directive_dependency` | INCOMPLETE | INCOMPLETE |
| **`unrelated_unmodeled_outside_witness`** | COMPLETE | COMPLETE |
| `html_attribute` | INCOMPLETE | INCOMPLETE |
| `nested_markup` | INCOMPLETE | INCOMPLETE |
| `malformed_markup` | INCOMPLETE | INCOMPLETE |
| `ambiguous_location` | INCOMPLETE | INCOMPLETE |

The two bolded controls are a directional pair and are gated together. One alone
is satisfiable by an instrument that always refuses or always grants.
`out_of_range_link_definition` **failed on the first two implementations** and
drove both fixes above; `unrelated_unmodeled_outside_witness` is what stops the
witness from degenerating into the document-level rule under a new name.

### Decision-gate numbers, accepted as the result

| | |
|---|---|
| locally-complete total | **77** of 720 (0.1069) |
| **locally-complete Q1** | **5** |
| locally-complete Q1 by family | `git_docs: 5` — and nothing else |
| Q1 by family | wikipedia 93, eCFR 59, SEC 17, git 6 |
| witness failures: `UNMODELED_SOURCE_FACT_IN_CLOSURE` | 586 |
| witness failures: `NO_DIRECT_SPAN_FOR_TARGET_ATOM` | 98 |
| `LOCATION_UNVERIFIABLE` | **0** |
| over-grant control | rejected correctly |
| under-grant control | granted correctly |

**The instrument was not adjusted after these numbers were seen, and will not
be.**

### Reading the result honestly

The instrument improved substantially — total locally-complete rose 20 → 77 and
every markup event is now located — and the number that gates the model study
**fell to 5**, because eligibility is now measured on Q1 questions through a
real closure rather than a document-level refusal.

The structure matters more than the total:

- within `git_docs`, **5 of 6 Q1 questions are eligible — 0.83**;
- the other three families contribute **169 Q1 questions and zero eligible
  ones**.

So the binding constraint is **front-end source coverage on HTML and XML**, not
cohort size and no longer position. 586 of the failures are genuine unmodeled
facts inside the closure.

### Exact power replaces "about 190"

`tools/mcnemar_power.py`, exact rather than normal-approximation because
McNemar's test conditions on a random discordant count and the approximation is
optimistic at exactly the sizes under argument.

| n | 50 | 100 | 150 | **190** | 200 | 250 | 300 |
|---|---|---|---|---|---|---|---|
| power | 0.407 | 0.747 | 0.916 | **0.967** | 0.974 | 0.993 | 0.998 |

Target power 0.95 is first reached at **n = 173**. The declared floor of **190
is therefore genuinely conservative** and is not lowered. Power at the observed
eligible Q1 of 5 is **0.0**.

### Consequence — gate outcome `FREEZE_A_NEW_COHORT_ACQUISITION_PROTOCOL`

5 is far below 190, so per the ruling: **no GPU request, no re-fitting, no
markdown-only narrowing, no lowering the floor.** `P4f_cohort_expansion` is
frozen at `sha256:117e55864f912b44c086beeeb2d4d89082049cd8e5503f8137e462d1508400e3`.

It records the arithmetic before acquisition begins, because freezing a plan
that cannot work and discovering it afterwards would waste both the acquisition
and the argument: at the naive overall yield of 0.0286, reaching 190 needs about
6,650 Q1 questions and roughly **2,166 documents** — 38× the current cohort. But
three of four families yield **exactly zero**, and **expansion multiplies a
zero**. P4f therefore pairs a 400-document expansion with a declared markup
coverage workstream, completed before the expanded cohort is scored.

P4f also names the trap explicitly: the fastest way to raise eligibility is to
declare more HTML constructs `IGNORED_BY_DECLARED_POLICY`, each reclassification
looking defensible alone while the aggregate is an eligibility count engineered
to clear the floor. Any such addition must be justified on what the construct
means, written down, and declared before the measurement it affects.

### Confirmatory query-builder hardening

`retrieval/isolated_builder.py` runs the builder in a separate interpreter under
`python -I -S`, receiving only a serialised `IntentView` on stdin. Verified: the
child imports **no repository module**, `site` is not loaded, the parent refuses
a forbidden field before serialising it, and the child refuses independently
when one is forced past the parent. The query it produces is identical to the
in-process builder's.

This does **not** revise P4e, whose in-process result stands. It is a stronger
isolation contract for the confirmatory experiment, where "nothing else was
reachable" should not rest on the discipline of every module sharing a process.

### Open for a decision that is not an agent's

Whether the markup coverage workstream models the constructs or declares them
non-semantic is a decision about what counts as knowledge, and P4f admits both
while forbidding the third option of granting completeness anyway. The 400
document target and the family mix are also open to revision before acquisition
starts — they are frozen, not immutable, and the freeze exists so that any
change is deliberate and recorded rather than responsive to a number.

### Note — the power tool was memoised after its first receipt

`tools/mcnemar_power.py` was given `lru_cache` on its binomial pmf and
rejection region after the first receipt was written, because the uncached form
made the test suite unusably slow. The change is performance only: power(190) =
0.9670, required_n = 173 and power(5) = 0.0 are byte-identical before and after,
and the parameters are untouched.

It still moved the tool digest, so the tool was re-run and a second receipt
exists at the current digest. Both receipts are preserved. Recording this rather
than quietly re-sealing is the point of the plumbing INC-V2-005 produced.

---

## INC-V2-010 — over-broad declared-irrelevant markup policy

**Opened** 2026-08-22, from independent review. **Not** a retroactive FAIL.

P0d's `_HTML_IGNORED_ATTRS` classified as blanket presentation a set of
attributes that change structure, accessibility, interpretation, reference or
metadata:

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
character references were all IGNORED by default. `&#160;` alone appears
**15,415 times** in the development corpus and produces a real character in the
canonical text.

### Disposition

P0d and `SOURCE_LOCALITY_V2` are **not** re-scored and not retroactively
failed. Their results stand as results **under the grammar each declared at the
time**, which is the only honest reading of them. What must not happen is that
stronger source-faithful evidence inherits that policy silently, so the fix is
forward-only: `MARKUP_SEMANTICS_V1`, frozen at
`sha256:4cba5049326f32495f168b1186a93fe072a3ebc98017c6543f6a5ff9e08027eb`.

### The rule that replaces "is it user-visible prose"

> Can a change to this source construct change the compiled interpretation or a
> downstream artifact?

Nine facets: `CONTENT_LEXICAL` · `STRUCTURAL` · `REFERENCE_LOCATOR` ·
`TEMPORAL` · `AUTHORITY_APPLICABILITY` · `METADATA` · `ACCESSIBILITY` ·
`VISUAL` · `EXTERNAL_DEPENDENCY_EXECUTION`. Not every canonical source fact is a
retrieval knowledge unit — `colspan` and `rowspan` are recorded as **control
facts**, because nobody asks about them and an answer can be wrong because of
them.

**Ignoring now requires three things**: a statement of what the construct means,
an argument that it changes none of the nine facets under a **named** consumer,
and that argument recorded before the measurement. "It is a presentation
attribute" is a category name, not an argument, and naming the consumer is what
makes the arguments falsifiable at all.

### The third state

`UNRESOLVED_SOURCE_FACT` exists so nothing is forced into a binary it does not
fit. `class` (65,485 occurrences) and `style` (25,441) are UNRESOLVED, not
ignored: an external rule may hide or reorder the element, and neither
"MODELED" nor "IGNORED" is a claim anyone here can support. UNRESOLVED blocks
question-local coverage completeness exactly as UNMODELED does — fail closed.

### Result

68 attributes and 50 elements declared: **88 MODELED, 12 UNRESOLVED, 18
IGNORED**, every ignored entry carrying its reason. Unknown constructs resolve
to UNMODELED, never IGNORED. Policy digest
`sha256:7dfa3dac52cf9a06cefc9e9eec4482aab5a15884dff6143a88f2d603df586f12`,
computed over the declared mapping rather than the file bytes — reformatting
cannot move it and reclassifying one attribute always does.

Eight adversarial controls, each a **pair** of sources differing in one
construct, because the claim under test is not "this is classified somehow" but
"a change to it changes the interpretation". All eight agree, in three
directions: MODELED (six), UNRESOLVED (`class`), and IGNORED
(`cellpadding` — the control that stops the policy collapsing into "everything
matters", which would pass the other seven and be useless).

---

## INC-V2-011 — P4f's markup workstream conflicts with its instrument-identity gate

**Opened** 2026-08-22, from independent review.

`P4f_cohort_expansion` required a markup coverage workstream that changes
classification semantics, and simultaneously required `G_P4F_INSTRUMENT_UNCHANGED`
to hold the Locality v2 tool digests constant. Both cannot be satisfied: doing
the workstream breaks the gate, and satisfying the gate forbids the workstream.

The deeper defect is that a **single tool digest is the wrong notion of
instrument identity** once policy and code are separable. It permits the
loophole in both directions — policy semantics drifting behind unchanged code,
and resolution logic drifting behind an unchanged mapping.

### Disposition

P4f is **not modified**. It is preserved as
`SUPERSEDED_BEFORE_EXECUTION` — expansion-planning evidence that was never run,
so no result is superseded, only a plan. Its arithmetic is carried forward
because it was correct.

`P4g_cohort_expansion` is frozen at
`sha256:dc7b59a78ce5004cc715205c81da3f0292a0d7cf9d83d2bf7fc0fb3d8b6de88f`, with
instrument identity defined as a **composition**:

    source-map code digest
  + witness code digest
  + markup-semantics policy digest
  + schema digest

Composite at freeze:
`sha256:3dda8243749788e939f6fb8916dacb8f16cefa6cca9d7a3cc5e4d3c373fe1f3a`.
A change to any part moves it. `G_P4G_COMPOSITE_IDENTITY` replaces
`G_P4F_INSTRUMENT_UNCHANGED`.

### What P4g carries forward, and what it refuses to predict

P4f's structural finding stands: within `git_docs` eligibility was 5 of 6 Q1 =
0.83, while the other three families gave 169 Q1 and zero eligible, so expansion
in that mix multiplies a zero. The markup workstream is what has changed since.

**No prediction is offered about what that does to eligibility.** `class` and
`style` are UNRESOLVED and are the two most frequent attributes in the corpus,
so eligibility may well stay low. That would be a finding, not a failure to be
engineered away — and P4g names the temptation explicitly: moving either to
IGNORED would raise eligibility more than any other single edit, and doing so
requires *proving* no external rule changes visibility, ordering or behaviour
for that corpus, declared before the measurement.

### Conformance note — a gate probe, not a gate, was wrong

`G_MS1_UNKNOWN_IS_NOT_IGNORED` failed on its first execution because the probe
asked about `data-not-declared-anywhere-xyz`. The policy **does** declare
`data-` by prefix rule, as UNRESOLVED, so the probe tested nothing about
undeclared constructs. The frozen predicate concerns constructs the policy
declares nowhere; the probe was changed to one (`binding`), which is conformance
to the frozen text rather than a weakening of it. The failing receipt is
preserved alongside the passing one, and the composite identity is unchanged by
the fix because a probe is not part of the instrument.

---

## INC-V2-012 — P4g inherits a spacing rule that cannot produce its own target

**Opened** 2026-08-22, at acquisition time, before any figure existed.

`P4g_cohort_expansion` §3 declares `spacing_rule: unchanged from P4e` and
`markdown_family_documents: 120`. P4e's rule for `git_docs` and `sec_edgar` was
*the pair already held*, and the acquisition manifest holds **8** git documents
and **10** SEC documents. A rule that selects from a held set of 8 cannot
produce 120. For eCFR and Wikipedia the inheritance is literal and those rules
are copied verbatim.

### Disposition

P4g is **not modified**. The two rules that had to be written are declared in
`acquisition/sources_p4g.py`, hashed and sealed by the acquisition receipt, and
labelled `EXTENSION` rather than `provenance: verbatim from P4e`, so nobody has
to reconstruct which is which:

* `git_docs` — newest commit touching an admitted path, paired with the newest
  commit touching it at least **180 days** older. The separation is not chosen:
  it is the only temporal separation P4e declared, and commits are the only
  other timestamped revision series in the cohort.
* `sec_edgar` — the amendment relation is P4c's, unchanged. Only its **scale**
  changes: pairs come from the live index for 20 issuers instead of the 10
  already on disk.

Both were frozen **before any fetch** and before any eligibility, coverage or
retrieval figure existed. That is the property the anti-fitting rules protect —
not the literal word "unchanged".

---

## INC-V2-013 — the markup policy was sealed and nothing read it

**Opened** 2026-08-22, before any P4g figure existed.

`MARKUP_SEMANTICS_V1` was frozen, its eight controls pass, and its policy digest
is sealed. But `canonicalization/markup_semantics` was imported by exactly two
things: its own controls, and the tool that seals it. The source map still
classified markup with P0d's grammar — every start tag, end tag, entity
reference and character reference `IGNORED` by default, and the fourteen
attributes of `INC-V2-010` still ignored as presentation.

So a cohort scored at that moment would have produced a number the markup
workstream did not touch, while the report said the workstream was done. That is
the more dangerous half of this defect: not a wrong number, a **plausible** one.

The founder's instruction was `markup semantics와 new source-map contract가
freeze되면 그때 400-document acquisition을 진행하십시오`. The source-map contract
did not exist when P4g was frozen, and the 400-document acquisition was started
before it did. The acquisition is blind — it selects documents by dates and
never sees a classification — so nothing about the cohort is contaminated, but
the ordering was still wrong and is recorded rather than tidied away.

### Disposition

P4g is **not modified**, and neither is `source_map.py`, `coverage_witness.py`
or `source_spans.py`. `SOURCE_LOCALITY_V2`'s instrument stays byte-identical and
its eligible Q1 = 5 stays reproducible; the honest way to change an instrument
is a new module with its own digest.

Two new modules carry the contract:

* `canonicalization/source_map_v2.py` — the same forward-built position map,
  with every construct classified by the frozen policy.
* `canonicalization/coverage_witness_v2.py` — the same closure, with
  `UNRESOLVED_SOURCE_FACT` blocking completeness exactly as `UNMODELED` does and
  counted separately, and embedded markup classified by the policy.

**Content constructs are not granted by policy alone.** The policy's statement
that character data and character references are `MODELED / CONTENT_LEXICAL` is
about their *kind*. Whether one occurrence reached the compiled artifact is a
different question, and answering it by assertion would be an over-grant. Text
and references are `MODELED` when traceable into the canonical text of that
revision and `UNMODELED_SOURCE_FACT` when not. Structural, reference, metadata
and accessibility constructs are classified by policy alone, because their
effect is on interpretation rather than on a string that could be looked for.

### The gate this changes, and why it is not a loophole

`G_P4G_COMPOSITE_IDENTITY` reads: *the composite instrument identity at scoring
time equals the value frozen here, **or a recorded incident explains the
difference***. This is that incident. The composite moves because two of its
parts are now different files.

That escape clause could be abused, so the two conditions that make this use of
it legitimate are stated plainly: the change was made **before any eligibility
number was seen**, and it was not aimed at a number. The direction is evidence
for the second claim — `class` and `style` are `UNRESOLVED`, they are the two
most frequent attributes in the corpus, and every occurrence of either now
**blocks** completeness. The predictable effect of this change is that
eligibility goes **down**, not up.

No prediction of the resulting figure is offered, and the cohort is scored once.

---

## INC-V2-014 — the declared lists reached 300 of a 400-document target

**Opened** 2026-08-22, at acquisition time. Nothing has been scored.

The first P4g acquisition pass admitted **300** documents — Wikipedia 96,
`git_docs` 98, eCFR 93, SEC 13 — against a target of 400. The exclusion ledger
says where the shortfall came from, and it is mechanical rather than a defect:

| reason | count |
|---|---|
| `INELIGIBLE_SINGLE_VERSION` (eCFR section has one dated version) | 2,320 |
| `INELIGIBLE_PARSE_FLOOR` (fewer than 3 canonical units) | 69 |
| `TOO_FEW_COMMITS` | 25 |
| `INELIGIBLE_SPACING_NOT_MET` (under 180 days) | 22 |
| `NO_MARKDOWN_UNDER_PREFIX` | 6 |

`sec_edgar` is the binding constraint and no list of issuers fixes it: of the
15 amendment pairs found across 20 issuers, 23 candidates failed the parse floor
because the primary document is a wrapper whose text does not reach three units.
The family is reported at whatever it reaches. It is **not** padded by relaxing
the parse floor, and it is not dropped.

### What the top-up is conditioned on

A **document count**, and nothing else. `P4g`'s `never_conditioned_on` list names
any eligibility count, any coverage status, any retrieval score and the Q1 count;
a document count is none of them, and could not sensibly be one — a target of 400
that may not be revised toward from below is not a target. The cohort has not
been scored, so there is no result to aim at.

### Disposition

`TOP_UP`, `TOP_UP_QUOTA` and four reserve lists are declared in
`acquisition/sources_p4g.py` **before** the top-up fetch: 10 more documentation
trees, 12 more CFR parts, 40 more articles, 15 more issuers. Every rule is
unchanged — the 180-day separation, the maximal-eCFR-separation rule, the
amendment relation, the container cap of 8, the parse floor, one pair per source
document. The reserves are additional *inputs*, not new rules.

The top-up quota is balanced at 120 / 120 / 120 / 60 so no family exceeds 30% of
the target, which is the constraint the first pass was built under. The first
pass's manifest is preserved as `p4g_cohort_pass1.json`, because its receipt
binds that path by hash and overwriting it would break a binding to make a
number nicer.

If the second pass still lands under 400, that is what is reported.
`G_P4G_SCALE` fails on the recorded number rather than on an adjusted one.

---

## INC-V2-015 — the first P4g scoring attempt died before it scored anything

**Opened** 2026-08-22.

`run_p4g` aborted with `MemoryError` inside `_region_of`. Two causes, both mine:
the region finder rebuilt a `{(start, end): span}` index of the entire document
**per question**, and `score_coverage` held the spans of all 321 documents in
scope at once.

It matters only because "the cohort is scored exactly once" has to mean
something. The run died before `write_immutable` was reached, so **no receipt
exists, no eligibility figure was produced and none was seen**. The once-only
budget was not consumed, and the repair could not have been aimed at a number
that did not exist.

Repaired by reading the fragment from `raw[start:end]` instead of indexing every
span, and by streaming one document at a time. Neither touches a classification,
a threshold or a gate. The contract was re-sealed afterwards, so the composite
identity recorded on the scoring receipt is the one the scoring code actually
had.

---

## Result — P4g, scored once

| | |
|---|---|
| documents | 321 (Wikipedia 114, `git_docs` 98, eCFR 93, SEC 16) |
| questions scored | 3,710 |
| Q1 | 1,014 |
| **eligible Q1** | **174** |
| floor | 190, unchanged |
| families with eligible Q1 | 3 of 4 |
| `LOCATION_UNVERIFIABLE` | 0 |
| envelope retrievable@10 | 0.9863 |
| atom recoverable from envelope | 1.0 |
| GPU / spend | 0 seconds, $0 |

**Verdict FAIL**, on one gate: `G_P4G_SCALE`, 321 documents against a required
400. Every other gate passed, including `G_P4G_COMPOSITE_IDENTITY` (the
difference is explained by `INC-V2-013`), `G_P4G_SELECTION_BLIND`,
`G_P4G_NO_NARROWING` and `G_P4G_SCORED_ONCE`. So 174 is a measurement on a
321-document cohort, not on the 400-document cohort the protocol asked for, and
it is not reported as one.

### Eligible Q1 per family, and the yield behind it

| family | Q1 | eligible | yield per Q1 | eligible per document |
|---|---|---|---|---|
| `git_docs` | 168 | 109 | 0.649 | 1.11 |
| `regulation_ecfr` | 272 | 58 | 0.213 | 0.62 |
| `encyclopedia_wikipedia` | 518 | 7 | 0.014 | 0.06 |
| `sec_edgar` | 56 | 0 | 0.000 | 0.00 |

### What the markup workstream actually did

`regulation_ecfr` went from **0 eligible under Locality v2 to 58**. That family
was previously unreachable because its XML constructs fell to `UNMODELED` by
default; under a declared semantics they resolve with reasons and a fifth of its
questions now clear. That is the workstream doing the thing it was built for.

The prediction recorded in `INC-V2-013` was that eligibility would *fall*, and
per markup question it did — Wikipedia questions that would have passed on text
alone now refuse. The total rose from 5 to 174 anyway, because the cohort is 5.6
times larger and because eCFR was unlocked. Both statements are true and neither
cancels the other; recording the prediction before the run is what makes it
possible to say so.

### Why the remaining refusals happen

| reason | count |
|---|---|
| `UNMODELED_SOURCE_FACT_IN_CLOSURE` | 2,455 |
| `UNRESOLVED_SOURCE_FACT_IN_CLOSURE` | 1,878 |
| `NO_DIRECT_SPAN_FOR_TARGET_ATOM` | 433 |
| `ATOM_SOURCE_REGION_NOT_LOCALISABLE` | 210 |
| `LOCATION_UNVERIFIABLE` | **0** |

`attr:class` alone accounts for **1,795** of the 1,878 unresolved refusals, and
it is why Wikipedia yields 7 of 518. Under a fail-closed reading, an element
carrying a class cannot be shown to be unaffected by an external rule, so
encyclopedic HTML cannot presently support question-local source-faithful
completeness.

**That is a finding, not a problem to be edited away.** Moving `class` to
IGNORED would lift eligibility past the floor in one line, which is exactly why
`P4g` named it in advance as the specific temptation. It stays `UNRESOLVED`.
Changing it would require *proving* that no external rule changes visibility,
ordering or behaviour for that corpus — a separate workstream with its own
evidence, declared before any measurement, not a reclassification.

`LOCATION_UNVERIFIABLE = 0` across 321 documents confirms that position is no
longer a limitation anywhere in the instrument.

### Disposition

174 < 190. Per the standing ruling: **no GPU request, no re-fitting of the
instrument or the policy to this cohort, no narrowing to one family, and the
floor is not lowered.** The prescribed response is a successor acquisition
protocol expanding documents and revision pairs, which is `P4h`.

---

## INC-V2-016 — P4h's admitted-scale gate is structurally coupled to full quota fill

**Opened** 2026-08-22, from independent review. P4h was never executed, so no
empirical result is discarded.

`P4h_cohort_expansion` sets family quotas `165 / 165 / 165 / 55 = 550` and
requires `G_P4H_SCALE: at least 550 admitted documents across at least 4
families`. Each family truncates at its own quota, so no family can compensate
for another. The same protocol also predicts `sec_edgar: 20 to 55, probably
nearer the low end`.

Those clauses cannot all hold. If SEC admits 20, the ceiling is 515 and the gate
fails before a single document is scored — the protocol predicts its own gate
failure in its own text. Over-selection at 1.5x does not help: it mitigates
attrition *inside* a family, and this is a shortfall *across* families that
per-family truncation forbids anyone from covering.

The deeper error is mine, and it is a category error: a **document count** and a
**powered question count** were welded into one gate. Acquisition breadth and
statistical power are different claims with different failure modes, and a
protocol that fails the first cannot report on the second.

### Disposition

P4h is **not modified**. It is preserved as `SUPERSEDED_BEFORE_EXECUTION`.

`P4i_cohort_expansion` separates the two:

* **breadth** — `admitted >= 400 documents across >= 4 families`. This is not a
  number invented to fit 174. It is the bar `P4g` carried in
  `G_P4G_SCALE` before any result existed, and P4g failed it at 321. Inheriting
  it keeps the acquisition bar exactly where it was set in advance.
* **statistical power** — `eligible Q1 >= 190`, unchanged, on its own gate.

550 remains the acquisition *target*: what is attempted, for headroom. Falling
short of 550 because of source scarcity, parse floor or payload failure does not
fail the acquisition gate as long as 400 admitted is reached.

### One correction to how P4h described its own quotas

P4h called `165 / 165 / 165 / 55` the realized proportions that produced 174.
They are not. P4g's admitted mix was `98 / 93 / 114 / 16`. The accurate
description, carried into P4i, is **"acquisition quotas scaled up from P4g's
predeclared nominal balance rule"** — a plan scaled, not an outcome copied.

### And one projection withdrawn

P4h's `expected eligible Q1 ≈ 295` multiplied P4g's per-admitted-document yield
by P4h's *nominal quota*, silently assuming every quota fills. Admission
attrition is exactly what `INC-V2-014` had already recorded. The figure is
withdrawn rather than carried forward. P4i states expected yields as a layered
chain — candidate attempt → expected admission → expected Q1 → expected eligible
— marked `DIAGNOSTIC_ONLY / NON_GATING`.

---

## Result — P4i, scored once. Verdict PASS, 10 of 10 gates

| | |
|---|---|
| documents admitted | **511** across 4 families — git 165, eCFR 165, Wikipedia 165, SEC 16 |
| breadth gate | >= 400 across >= 4 families — **PASS** |
| acquisition target | 550, attempted; non-gating |
| candidates selected | 768 |
| questions scored | 5,686 |
| Q1 | 1,564 |
| **eligible Q1** | **296** |
| floor | 190, unchanged |
| exact power at 296 | **0.9977** |
| families with eligible Q1 | 3 — git 202, eCFR 87, Wikipedia 7 |
| `LOCATION_UNVERIFIABLE` | 0 |
| envelope retrievable@10 | 0.9863 |
| atom recoverable | 1.0 |
| GPU / spend | 0 seconds, $0 |

Instrument composite at scoring time
`sha256:0ed844f6eb83e8b342f6790a772099c8ebec4c80c525cdf721b59a54df10fe2a` —
byte-identical to the one that produced 174 on P4g, gated by
`G_P4I_INSTRUMENT_UNCHANGED` with no escape clause.

### How 174 became 296

**190 more documents.** Not a looser rule:

* the markup policy is untouched — `attr:class` and `attr:style` are still
  `UNRESOLVED_SOURCE_FACT` and still block, accounting for 2,629 of 2,716
  unresolved refusals;
* the floor is still 190, and specifically was not lowered to 174;
* the family quotas are still the declared scale-up of P4g's nominal balance
  rule, gated by `G_P4I_MIX_NOT_REWEIGHTED`. `git_docs` yields 0.74 eligible per
  Q1 against Wikipedia's 0.01, so re-weighting would have reached 296 with far
  fewer documents. It was not done, and the price was 165 Wikipedia documents
  contributing 7 eligible questions.

`sec_edgar` reached 16 of a 55 quota and contributed zero eligible Q1. Reported
at what it reached — not padded by relaxing the parse floor, not dropped. A
family that yields nothing is evidence about the family.

### Admission accounting

`SOURCE_EXHAUSTION` 4,490 · `PARSE_FLOOR` 122 · `SPACING_NOT_MET` 60 ·
`PAYLOAD_UNAVAILABLE` 6 · `NO_SOURCE_CHANGE` 4 · `LISTING_FAILED` 3 ·
`RELATION_FAILURE` 3 · `OTHER` 125 (beyond family quota). The exhaustion figure
is overwhelmingly CFR sections carrying one dated version — a property of the
source, not of the fetcher, which is the distinction reason codes exist to make.

### A crash before the figure, again

The first `run_p4i` invocation died with `KeyError: 'acquisition_target'`: the
scorer was scaffolded from `run_p4g` and its `--manifest` default still pointed
at the P4g cohort. It failed in the gates block before `write_immutable`, so no
receipt was written, no figure printed and none seen. The once-only budget was
not consumed, on the same basis as `INC-V2-015`, and `P4g`'s own receipt is
untouched. Not opened as a separate incident: same defect class, same
disposition, and the ledger is for distinct failures rather than repeat
instances of one.

### Disposition

`admitted >= 400`, `eligible Q1 >= 190`, `eligible families >= 2`, all integrity
gates PASS. Per the standing ruling the model-study proposal is updated with the
real numbers and submitted for founder approval:
`MODEL_STUDY_PROPOSAL_v2_2026-08-22.md`. v1 is preserved unmodified — its
*do not run* recommendation was correct on eligible Q1 = 5.

**GPU is not executed.** Approval of the study is a separate decision from
meeting these gates, and nothing runs before it.

---

## INC-V2-017 — the model-endpoint preflight fails; GPU does not start

**Opened** 2026-08-23 · **Class** endpoint feasibility ·
**Disposition** PRESERVED, NOT RE-RUN · **GPU seconds** 0 · **Cost** $0

`MODEL_ENDPOINT_V1` was frozen at
`sha256:2b0487c41076fee00dfc9eae6265881c0d6918a9a66f5337b35130000b1172f4`
before any model call, and the CPU-only preflight ran once:
`receipts/model-endpoint-preflight--20260822T151517Z-43f9291f0970.json`.

**Verdict FAIL. Nine of eleven gates pass; two fail.**

    G_ME1_COHORT_FLOOR   final cohort 10   floor 190      FAIL
    G_ME1_TRUNCATION     0.70 / 0.40 / 0.40 / 0.20        FAIL   ceiling 0.25

The founder's condition was explicit — execution without a further check-in *on
condition that this preflight passes*, and `if_any_gate_fails: GPU does not
start`. It did not pass. No GPU second is spent and no model has been called.

### What actually collapsed the cohort

Of 296 regenerated candidates, 286 were excluded:

    VALUES_NOT_DISTINGUISHABLE            274
    TARGET_EVIDENCE_LOST_TO_TRUNCATION     12

and within the distinguishability failures (first 200 recorded in detail):

    neither direction carries a distinguishing value   140
    superseded revision carries none                    35
    current revision carries none                       15

This is the finding, not an obstacle to it. **A question can be
`QUESTION_LOCAL_COVERAGE_COMPLETE` and still have nothing for a model to get
right.** P4i's eligibility asks whether the compiled state is locally complete
against its source. The model endpoint asks a strictly harder question: whether
the two revisions differ in a *value* — a number, date, version, percentage,
amount or identifier — that an answer can select between. 92.6% of the eligible
Q1 population differs only in prose, structure or wording. Scoring those would
have measured phrasing overlap and reported it as currency selection.

The two gates are not independent. The truncation rates are computed over the
surviving ten questions, so `0.70` is seven documents out of ten, and the
figure carries the instability of n=10. The cohort floor is the primary
failure; truncation is a symptom reported at a sample size that cannot support
it, and is recorded as such rather than argued away.

### What was not done

- The scorer was **not** loosened. Widening `_VALUE_PATTERNS` to admit ordinary
  words would clear the floor immediately and would also destroy the endpoint:
  the class would stop meaning *selected the current value*. The scorer's eight
  controls all pass and it is left byte-identical.
- The 4,096-token budget was **not** raised to rescue the truncation rate.
- The 190 floor was **not** lowered, on the same standing rule that kept it at
  190 when P4g returned 174.
- The protocol was **not** amended and the preflight was **not** re-run.
- `docs/ip/` is untouched.

### Two accounting notes, recorded rather than smoothed

- `eligible_q1_from_p4i` is 293 against 296 coverage rows: three `question_id`
  strings collide across documents once anchor paths repeat. It affects the set
  cardinality, not the candidate iteration, and it is reported rather than
  deduplicated silently.
- `tokenizer_class` reads `Qwen2TokenizerFast` here against `Qwen2Tokenizer`
  attested, and `vocab_size` 248044 against 248320. Both are transformers
  reporting differences. Identity rests on the `tokenizer.json` digest, which is
  byte-identical, and on the behaviour probe, which returns the attested 20
  tokens.

### Standing position

The gates that were built to answer *is the instrument pinned, is the prompt
clean, is the schedule balanced, does the scorer work* all pass. What fails is
the corpus's ability to pose the question. That is a real result about the
corpus and it is preserved: **`MODEL_ENDPOINT_INFEASIBLE_ON_THIS_COHORT`**.

Any route forward — acquiring sources selected for value-bearing revisions,
or redefining the endpoint — changes what is being measured and is a founder
decision, not an implementation one. Nothing is re-run until that decision
exists.

---

## INC-V2-018 — non-injective question identity silently collapses repeated anchor paths

**Opened** 2026-08-23 · **Class** identity ·
**Disposition** PRIOR RESULTS UNMODIFIED; FIXED IN SUCCESSOR ONLY ·
**GPU seconds** 0 · **Cost** $0

P4i's sealed receipt carries **296** `QUESTION_LOCAL_COVERAGE_COMPLETE` Q1
coverage rows. The model preflight read **293** unique `question_id` strings
from the same rows. Three collided.

The cause is that the identifier is a rendered string rather than a key:

    <document>|<question kind>|<anchor path>

Anchor paths repeat inside a document whenever the same labelled construct
occurs more than once — `(3)#1` under two different subsections of the same
CFR part is the ordinary case, not the exotic one. Two distinct questions
therefore render to one string, and any set-valued operation over question ids
silently merges them.

**Nothing downstream of this was wrong by it.** The preflight iterated
candidates, not the set, so 296 candidates were materialized and 286 excluded
and 10 retained; the collision affected the reported cardinality only. P4i's
figures stand and are not recomputed: `511 documents / 1564 Q1 / 296 eligible
Q1 / 3 eligible families`. `INC-V2-017`'s preflight FAIL stands unmodified.
Correcting a sealed result to make a later number tidier is the failure mode
this ledger exists to prevent.

### What changes, and only in the successor

`VALUE_BEARING_COHORT_V1` replaces the rendered string with a canonical
content-addressed identifier. The inputs are declared before any question is
generated:

    source family
    source logical/document id
    before version id
    after version id
    stable atom id
    anchor path
    question kind
    value-property id

canonically serialized, then hashed. The property id is what makes it
injective where the anchor path is not: two questions at the same anchor about
different properties are different questions and now have different ids.

### New hard gate

    G_VBC1_QUESTION_ID_INJECTIVE
      predicate: number_of_unique_question_ids == number_of_question_rows
      on_failure: STOP

Not a warning and not a diagnostic. One duplicate stops the run. A cohort whose
questions cannot be told apart cannot support a paired test, because McNemar
pairs *by question id* — a collision does not merely miscount, it silently
pairs one arm's answer with another question's.

---

## Development finding — value-bearing density on the P4i corpus

**Measured** 2026-08-23 · **GPU seconds** 0 · **Cost** $0 ·
**Status** DEVELOPMENT EVIDENCE, NOT A RESULT

`VALUE_BEARING_COHORT_V1`'s extractor, its taxonomy and its thirteen controls
were frozen at `receipts/value-fact-freeze--20260822T170435Z-7f50504835c5.json`
before this was run on anything, and before any fresh candidate list exists.
P4i's 511 documents are permitted development data and were used as such.

    documents                    git 165 · eCFR 165 · wiki 165 · SEC 16
    value facts extracted        git 0 · eCFR 1 · wiki 38 · SEC 0
    documents carrying >=1 fact  9 of 511  (1.8%)
    facts in documents that also produced >=1 locally-complete Q1
                                 16, all encyclopedia_wikipedia

Three things follow, and the third is the one that matters.

**The git zero is not a defect.** 165 git documents produced 50 observed
property/value bindings across 11 documents; every one of them was
`VALUE_UNCHANGED` or `PROPERTY_NOT_STABLE`. The tables were read. Their values
simply did not move between the two revisions.

**The density is a property of the population, not of the extractor.** P4i
admitted documents for carrying *any* semantic source change with adequate
revision spacing. Value-bearing revisions are a small subpopulation of that,
which is the same finding `INC-V2-017` reported from the other end. A fresh
cohort admitted *because* a value changed is a different population and its
density cannot be read off this number.

**The families that carry value structure and the families that pass coverage
completeness are not the same families.** All 16 facts surviving into
coverage-complete documents are encyclopedic infoboxes — the family the
unresolved `attr:class` constraint blocks hardest (7 eligible of 767 in P4i).
eCFR contributed one fact; git and SEC contributed none. On this corpus the
`>= 2 eligible families` requirement would not be met at any acquisition volume.

### What this does not authorise

It does not authorise widening the taxonomy to reach a number. The two frozen
shapes are the two the protocol declared, and both were sealed before this
measurement existed. It does not authorise re-weighting the declared family
shares, which the protocol forbids in the same words that forbade re-weighting
P4g's mix. Neither does it authorise abandoning the route on a projection:
density measured on a population selected for something else is evidence about
that population.

### What it does require

A bounded CPU-only feasibility probe on *fresh* candidates selected for
value-bearing structure, run through the whole frozen chain, before committing
to a full acquisition. Sizing a several-thousand-document fetch from a density
measured on the wrong population would be the same error in the other
direction.

---

## INC-V2-019 — the value-bearing predicate is not the constraint; revision-pair sampling is

**Opened** 2026-08-23 · **Class** acquisition design ·
**Disposition** PROBE BURNED AND PRESERVED; NO CONFIRMATORY ACQUISITION STARTED ·
**GPU seconds** 0 · **Cost** $0

`VALUE_BEARING_COHORT_V1` was frozen at
`sha256:a4a2b568d3d04b475ea9edccf28f588c6d349852e960a55f608500c049d0e68e`,
and the extractor, taxonomy, generator and thirteen controls at
`receipts/value-fact-freeze--20260822T170435Z-7f50504835c5.json`, both before any
fresh candidate list existed. A deliberately small feasibility probe then fetched
45 fresh documents across all four families, disjoint from P4i by check rather
than by assertion, and ran the whole frozen chain.

    receipts/vbc1-probe-cohort--20260822T172038Z-6a613a7cdd69.json
    receipts/vbc1-probe-result--20260822T172056Z-c718e6225611.json

    documents            45   (git 14 · eCFR 14 · wiki 14 · SEC 3)
    properties read     174
    VALUE_UNCHANGED     154
    PROPERTY_NOT_STABLE  20
    value facts           0
    questions             0

### What the zero means, precisely

**It is not an extractor failure.** 174 source-native property/value bindings
were read out of these documents and paired across the two revisions. The tables
were found, the labels were read, the values were extracted and compared. The
machinery ran end to end.

**Nothing reached the coverage step.** Every candidate died at the value-fact
stage, so the `attr:class` constraint, the token budget, truncation and
context validity were never even consulted. The binding constraint sits earlier
than any of the ones the previous two failures were about.

**The constraint is how revision pairs are chosen.** P4g's selector — inherited
unchanged through P4i and through this probe — picks two revisions of a document
separated by a spacing rule and differing *somewhere*. Documents change
constantly; the specific table cell binding a labelled quantity changes rarely.
Sampling two revisions blind to whether a value moved and then asking whether one
did is a low-probability draw, and 0 of 174 is what that looks like.

Combined with the development measurement on P4i (39 facts in 511 documents,
1.8% of documents, none surviving the full chain on fresh data), the conclusion
is arithmetic rather than interpretive: **the current acquisition primitive
cannot reach the 190 floor at any volume this study could plausibly fetch.**

### What was not done

- The extractor was not widened after seeing the zero. Two shapes, frozen, and
  the thirteen controls still pass.
- No value kind was added, no pattern relaxed, no label rule loosened.
- The 190 floor stands. The 4,096-token budget stands. The declared family
  shares stand.
- No confirmatory acquisition was started. Sizing a multi-thousand-document
  fetch against a measured yield of zero would burn effort to reproduce a
  known answer.
- `docs/ip/` untouched. IP gate CLOSED.

### The probe is burned

Its 45 lineages have had their eligibility seen and are excluded from any
confirmatory cohort, by the same rule that excluded P4i's lineages and
`MODEL_ENDPOINT_V1`'s ten survivors. That cost is why the probe was 45
documents and not 600.

### The decision this hands back

Reaching a value-bearing cohort requires selecting the **revision pair** by the
frozen value-bearing predicate — searching a document's revision history for a
pair in which a labelled quantity actually moved — instead of sampling two
revisions and testing them afterwards. That is admission by the frozen
predicate, which the protocol already requires, but it replaces an acquisition
primitive that P4g, P4i and this probe all share, and it interacts with the
revision-spacing rule those protocols froze. It is a founder decision, not an
implementation one, and nothing further is run until it is made.

---

## INC-V2-020 — primary power count must not be inflated by within-lineage clustered questions

**Opened** 2026-08-23 · **Class** statistical design ·
**Disposition** PREVENTED BEFORE ANY MODEL RUN · **GPU seconds** 0 · **Cost** $0

No empirical result changes here, because no model has answered anything. This
is a defect recorded before it could occur.

The exact McNemar power calculation this study rests on — `required_n() = 173`
at alpha 0.05, effect 0.15, discordant rate 0.30 — assumes **independent paired
observations**. One document lineage can easily yield several qualifying
ValueFacts: a flags table with three changed defaults produces three questions
that share a document, a revision pair, a retrieval index, an evidence
neighbourhood and very often a single editorial act. Counting them as three
toward 190 would inflate n without adding information, and the test would report
a confidence the design never earned.

The temptation is concrete and would arrive at exactly the wrong moment. After
three failures to reach the floor, a lineage yielding four questions looks like
four-for-the-price-of-one.

### The rule

`VALUE_BEARING_COHORT_V2` limits the primary confirmatory cohort to **one
primary question per source-document lineage**, with a hard gate:

    G_VBC2_ONE_QUESTION_PER_LINEAGE
      predicate: number_of_primary_questions == number_of_distinct_primary_document_lineages
      on_failure: STOP

Where several properties qualify in the selected transition, the primary
question is the first by ascending canonical `property_id` hash — deterministic,
content-derived, and fixed before any value is read. The others are recorded as
acquisition diagnostics and are excluded from the primary McNemar sample.

The 190 floor is unchanged and now means, in plain terms, **190 independent
document lineages**. That is a stricter bar than the one that failed twice, and
it is stricter on purpose.

---

## INC-V2-021 — two acquisition processes ran concurrently against one output path

**Opened** 2026-08-23 · **Class** operational ·
**Disposition** BOTH STOPPED; NO CONTAMINATED ARTIFACT WAS PRODUCED ·
**GPU seconds** 0 · **Cost** $0

The VBC2 acquisition was launched twice. The first launch used a detached shell
whose wrapper exited immediately; reading the empty log, the run was judged dead
and relaunched. It was not dead. Both processes then walked the same frozen
lineage list, wrote into the same `raw_vbc2` tree, and were both headed for the
same `vbc2_cohort.json` and the same receipt stem.

    PID 23364   first launch, log truncated by the second
    PID 40444   second launch
    both stopped 2026-08-23, before either reached its write

### What was and was not at risk

**No artifact was contaminated.** Neither process reached the manifest write, so
no cohort file and no `vbc2-cohort` result receipt was produced by either. The
only receipt under that stem remains the one from the deliberate `--limit 6`
smoke run, which admitted nothing.

**Had they finished, the damage would have been quiet rather than loud.** Both
walk the same frozen list under the same deterministic predicate, so they would
have produced *the same* cohort — and the second write would have looked like a
normal successful run rather than a collision. A duplicate that agrees is harder
to notice than one that disagrees.

**The raw tree is not evidence and was not treated as any.** Payloads under
`raw_vbc2` are refetched and rewritten byte-identically by any later run; two
writers there change nothing that a receipt rests on.

### Why the empty log was misread

The log file was the only signal, and the relaunch truncated it. A process
writing progress every ten admissions produces no output at all for a long time
when admissions are rare — which, given `INC-V2-019`, is exactly the expected
regime. Silence was read as death when it was the predicted behaviour.

### What changed

Process identity is checked directly before any relaunch, not inferred from log
contents. The rerun is a single process with an explicit, recorded wall-clock
budget, so an interrupted walk reports itself as interrupted instead of leaving
an admitted count that reads like an exhausted list.

Family scheduling also changed, and it is recorded because it affects nothing:
lineages are now walked round-robin across families with each family's declared
order preserved. Quotas are per family, so the admitted set is identical to
sequential walking. What it buys is that an interrupted run has seen every
family rather than only the first — a partial result that can be read instead of
one that cannot.

---

## INC-V2-022 — a partial acquisition can currently be serialized as a normal cohort and accepted by preflight

**Opened** 2026-08-23 · **Class** provenance ·
**Disposition** RECORDED NOW, REPAIRED FORWARD ONLY, AFTER THE RUNNING WALK ENDS ·
**GPU seconds** 0 · **Cost** $0

`INC-V2-021` stopped two concurrent acquisitions before either wrote anything.
This entry is about the defect that made that near-miss possible and that
survives it: **nothing downstream can tell a completed walk from an interrupted
one.**

Three weaknesses compose into that.

**A partial run writes the canonical path.** `run_vbc2_acquire.py` writes
`artifacts/development/vbc2_cohort.json` whether the walk exhausted the frozen
lineage list or stopped on its wall-clock budget. The receipt records
`stopped_on_wall_clock_budget`, but the *manifest* — the thing the preflight
reads — carries an admitted count that looks identical either way.

**The preflight does not ask.** `run_vbc2_preflight.py` reads the manifest and
proceeds. A budget-stopped walk that happened to admit 190 lineages would clear
`G_VBC2_COHORT_FLOOR` and every other gate, and the run would report a
confirmatory cohort assembled from a truncated list. That is not a cohort that
fell short; it is a cohort whose denominator is unknown.

**The canonical path is mutable and already cited.** The `--limit 6` smoke
receipt names `vbc2_cohort.json`. A later full run overwrites that exact path,
so the smoke receipt would then point at content it never described. That
receipt is historical evidence and is **not edited**; the weakness is closed
going forward instead.

### The acceptance rule, effective now

A run counts as a full acquisition only when

    stopped_on_wall_clock_budget == false   and   the frozen lineage list was exhausted

Anything else is a **diagnostic partial result**. It may be analysed for
attrition and yield; it may not be used as a confirmatory acquisition, whatever
its admitted count.

### Forward repair, after the running walk ends and not before

The acquisition process running now is `PID 13624`, started 2026-08-23 05:32:02,
confirmed by OS process identity rather than by log contents. Editing its
sources mid-flight would leave the completion receipt's tool digest describing
bytes that never executed, so nothing it touches is modified until it exits.

Then, before the next execution:

- an atomic single-instance lock recording run id, PID and process start time. A
  second launch with a live owner is REFUSED immediately; a stale lock is
  reclaimed only after an OS liveness check, never on age alone.
- a partial run never writes the canonical manifest. It writes
  `vbc2_cohort.partial.<run-id>.json` and a `vbc2-cohort-partial` receipt.
- explicit `status: PARTIAL` / `COMPLETE: false`, and an exit status distinct
  from a full-run success, so a caller that reads only the exit code cannot
  mistake one for the other.
- a hard preflight gate: if the acquisition is not complete, the preflight
  refuses to run at all rather than reporting a verdict over a truncated list.
- run-specific immutable manifest filenames for full runs too, with
  `manifest_sha256` in the receipt, so a receipt names content that cannot
  change under it.

### What is not affected

The frozen protocol, the frozen lineage list and the frozen predicate are
untouched by all of this. The defect is in how a run is *serialized and
accepted*, not in what it selects. And the standing gate stands: a full walk
admitting fewer than 190 lineages is analysable on CPU, and still starts no GPU.

---

## Partial execution — the serial VBC2 walk, terminated and not used

**Recorded** 2026-08-23 · **Status** `PARTIAL_EXECUTION — NOT A COHORT RESULT` ·
**GPU seconds** 0 · **Cost** $0

    PID 13624   started 05:32:02   elapsed 165.3 min   admitted lineages 3
    manifest    never written      receipt   never written

Terminated deliberately under the execution-speed ruling. It produced no cohort
manifest and no result receipt, so there is nothing to supersede. **Its admitted
count is not a yield figure and is not used for any eligibility or feasibility
judgement** — three admissions in 165 minutes measures the executor, not the
sources.

What it does establish is the throughput problem: a serial walk of 2,271
lineages at this rate does not terminate on any useful horizon. That is an
executor property, and it is the only thing this run is cited for.

The raw payloads it left under `raw_vbc2` are cache, not evidence. They are
refetched and rewritten byte-identically by any later run and nothing rests on
them.

---

## Executor change — parallel VBC2 acquisition, scientific contract unchanged

**Recorded** 2026-08-23 · **Class** executor ·
**GPU seconds** 0 · **Cost** $0

The serial walk was a throughput failure, not a scientific one: 165 minutes for
three admissions. The contract is therefore untouched and only the executor is
replaced. The candidate list, family quotas and shares, the ValueFact extractor,
the transition predicate, the acquisition cutoff, the 1,460-day horizon, the
twelve-revision bound, the newest-qualifying rule, one question per lineage and
the 190 floor are the frozen ones.

### Three roles that do not overlap

**Workers** evaluate one lineage each. A worker cannot see the global quota, the
admitted count, any other lineage's result, any coverage or retrieval figure, or
any model output — checked by a test that strips docstrings and greps the code,
because prose *about* a forbidden name is not access to it. A worker that could
see how full the cohort already was would make selection a function of arrival.

**The coordinator** is the only thing holding the frozen lineage ordering and
the per-family quotas.

**The writer** is the only thing that touches the raw tree, the manifest and the
receipt. Several acquisition processes writing one manifest is the shape
`INC-V2-021` recorded, and it is now structurally impossible rather than merely
discouraged.

### Completion order is not selection order

Results are collected as they finish and then re-sorted into frozen lineage
order before a single admission pass that is the serial algorithm unchanged.
This matters because completion order correlates with latency, payload size and
provider health — admitting in arrival order would make the cohort a function of
the network.

Proven on a synthetic fixture, as a hard gate before the walk ran:

    serial admitted ids        == parallel admitted ids
    serial selected transition == parallel selected transition
    serial primary property    == parallel primary property
    manifest semantic digest    identical, across every rotation of arrival order

The semantic digest deliberately excludes timestamps, worker counts, cache
statistics and host tallies. Those differ between a serial and a parallel run by
construction, and a digest containing them could never demonstrate equivalence.

Within a lineage, revisions are prefetched up to a bounded window but *evaluated*
newest-to-oldest in frozen order, and the first qualifying transition wins. A
fixture where the value moves at r3→r4 and again at r4→r5 confirms the newest is
taken and the larger delta is not.

### Transport

Per-host semaphores, per-host cooldowns, `Retry-After` handling and exponential
backoff with jitter. Host-scoped because a GitHub throttle must not stall an
eCFR worker — the single global sleep is exactly why the serial walk was paced
by its slowest provider. Jitter is not decoration: without it every worker that
hits one throttle retries in lockstep and reproduces the burst that caused it.

The enumerators are not reimplemented. They are the frozen ones, building the
same URLs in the same order, with only the byte-carrying function swapped.

### Caches, which are not evidence

Payloads are content-addressed and every hit is re-hashed against the digest it
is filed under, so a tampered or truncated entry is a miss rather than a silent
substitution. Parsed state is keyed on the payload digest *and* the extractor's
own digest, so a changed extractor can never read a predecessor's state.
Deleting the cache changes run time and changes no result.

### INC-V2-022 closed forward

Single-instance lock keyed on run id, PID and process start time — a recycled
PID cannot pass as the same owner, and a lock whose liveness cannot be
established is never reclaimed. Partial runs write
`vbc2_cohort.partial.<run-id>.json` and a `vbc2-cohort-partial` receipt, carry
`status: PARTIAL` / `complete: false`, and exit 3 rather than 0. Full runs write
a run-scoped immutable manifest whose sha256 is in the receipt. The preflight
now refuses outright — `REFUSED_ACQUISITION_INCOMPLETE` — unless the manifest's
own body reports an exhausted walk with no budget stop, and it reads that from
the body rather than from the filename.

The existing smoke receipt is preserved unmodified as historical evidence.

---

## INC-V2-023 — the preflight locates atoms in canonical text using labels read from raw markup

**Opened** 2026-08-23 · **Class** instrument consistency ·
**Disposition** RECORDED BEFORE ANY FIX; VERDICT UNCHANGED EITHER WAY ·
**GPU seconds** 0 · **Cost** $0

The VBC2 acquisition admitted 3 lineages from a complete 2,271-lineage walk. All
three were then excluded by the preflight as `ATOM_NOT_LOCATED`, and the reason
is a defect in the locator rather than anything about the sources:

    label='**App size**'          atoms=7   label_hits=0  value_hits=1
    label='`background.paper`'    atoms=25  label_hits=0  value_hits=0
    label='Romania'               atoms=4   label_hits=0  value_hits=0

The extractor reads a property label out of **raw markup**, so it carries the
markup with it — `**App size**`, `` `background.paper` ``. The preflight then
searches for that string inside **canonical atom text**, where emphasis markers
and code fences have already been stripped. The two halves of the instrument are
looking at different representations of the same document, and a substring test
across that boundary can only fail.

### Why this is recorded before it is fixed

**The verdict does not depend on it.** Three admitted lineages cannot reach a
floor of 190 under any locator, so no repair here can rescue this run. That is
precisely why fixing it now is safe to do and worth stating: a locator repaired
after seeing a result is a suspicious act exactly when it could change the
number, and here it demonstrably cannot.

**It would have mattered at scale.** Had acquisition yielded hundreds of
lineages, this defect would have silently emptied the cohort at the preflight
step, and the failure would have looked like a coverage or truncation problem
rather than a string-matching one.

### What is not affected

The frozen extractor, the frozen scorer, the taxonomy, the transition predicate
and the acquisition are untouched. The defect is in `run_vbc2_preflight.py`'s
`locate`, which is not a frozen artifact. The acquisition receipt and its
manifest stand as written.

The fix is to compare both sides in one representation, using the frozen
scorer's own normalization plus markup-marker stripping, so the label that
acquisition found and the atom the preflight searches are compared as the same
kind of string.

---

## INC-V2-024 — INC-V2-023's locator repair is a post-acquisition diagnostic, not a result

**Opened** 2026-08-23 · **Class** disposition of an earlier entry ·
**Corrects** nothing in INC-V2-023; it classifies what INC-V2-023 produced ·
**GPU seconds** 0 · **Cost** $0

INC-V2-023 recorded, before repairing it, that the preflight searched for
property labels read out of **raw markup** inside **canonical atom text**. The
repair — comparing both sides in one representation — is a **valid forward
repair** and stays.

What the repair produced is not a result. Under the founder ruling of
2026-08-23 it is classified:

    class:                     POST_ACQUISITION_DIAGNOSTIC
    is_confirmatory_result:    false
    effect_on_stop_verdict:    none

After the repair the three admitted lineages separated into `ATOM_NOT_LOCATED`,
`ATOM_NOT_UNIQUE` and `COVERAGE_INCOMPLETE`. **Those three classifications must
not be called a confirmatory result.** They are a diagnostic of the locator: a
n=3 sample, examined after the acquisition outcome was known, on an instrument
that had just been changed. Every property that makes a confirmatory result
worth anything — preregistration, blindness to the outcome, a sample that can
carry a verdict — is absent from them.

**The primary stop verdict does not depend on this in either direction.** The
theoretical best case is that all three survive, and

    3 < 190

so no locator, repaired or unrepaired, changes `G_VBC2_COHORT_FLOOR`. That is
the same reasoning INC-V2-023 gave for why fixing it was safe, stated now as
the reason the fix cannot be read as rescuing or damaging anything.

---

## STOP-V2-005 — EXACT_VALUE_MODEL_ENDPOINT_NOT_FEASIBLE_UNDER_DECLARED_PUBLIC_SOURCE_FRAME

**Opened** 2026-08-23 · **Authorised by** founder ruling, 2026-08-23 ·
**Receipt** `receipts/route-a-closure--20260823T014801Z-660bb0cfcc24.json` ·
**GPU seconds** 0 · **Spend** $0 of an approved $40

### On the identifier

The ruling names this record `STOP-V2-004`. That identifier has been held since
2026-08-22 by the P4d-Core-Semantic stop, and this ledger is append-only, so
reusing it would mean overwriting evidence in the act of recording evidence. The
ruling permits "an equivalent clear stopping record"; this is that record at the
next free number, carrying the label the ruling specified verbatim.

### Model experiment status

    NOT_RUN — PREDEFINED CPU PREFLIGHT INFEASIBLE

Not *failed*, not *inconclusive*, not *pending*. The predefined CPU preflight
was executed and could not be satisfied, so no model was ever asked anything.
**The GPU authorisation for this research cycle is terminated.** A future model
study needs its own protocol and its own founder approval; nothing carries
forward.

### What is preserved, unmodified

    lineages walked            2,271 of 2,271     (complete; no budget stop)
    admitted                   3
    final endpoint cohort      0
    NO_QUALIFYING_TRANSITION   1,144
    TOO_FEW_REVISIONS          1,107
    GPU                        0 seconds · $0

### The three failures, and why they are one finding

| protocol | population | survivors | what it establishes |
|---|---|---:|---|
| `MODEL_ENDPOINT_V1` | 296 locally-complete semantic-change questions | 10 | locally-complete semantic change ≠ exact-value endpoint eligibility |
| `VALUE_BEARING_COHORT_V1` | 174 properties over 45 fresh value-bearing documents | 0 | value-bearing structure ≠ observable value transition |
| `VALUE_BEARING_COHORT_V2` | 2,271 fresh lineages searched by revision history | 3 | value-bearing structure ≠ *frequently* observable value transition |

They are not one failure counted three times, and they are not three unrelated
failures. Each removed the explanation the previous one left open. The first
could have been a bad cohort; the second used sources chosen for exactly the
right structure. The second could have been bad pair sampling; the third
searched revision history directly and enumerated every transition in the
frozen window. What is left is a property of the declared public source frame:
**stable labelled values in public sources move rarely enough that an
exact-value paired endpoint at n≥190 is not reachable within it.**

### What was not done, and will not be

- **No VBC3.** No successor cohort is created to chase 190.
- **No refitting.** The twelve-revision bound, the 1,460-day horizon, the source
  families, the family weighting, the value scorer, the ValueFact taxonomy and
  the 190 floor are unchanged, and their digests are in the receipt so a later
  edit is visible rather than arguable. The twelve-revision bound in particular
  is frozen with `explicitly_not_basis: observed value-fact yield`, and the
  measurement that would motivate moving it *is* that yield.
- **No rescue by scorer.** The endpoint was not widened to a semantic judge, a
  human adjudication or a broader answer definition. Route B remains available
  only as a separate study with its own preregistered scorer and its own cohort.
- **No GPU.** The most expensive thing this programme could have done was run a
  study whose cohort could not support its own analysis, and the preflight
  stopped it three times without a model ever being loaded.

### The finding worth publishing

An outcome-independent CPU preflight, frozen before acquisition, correctly
refused an expensive experiment three times. That is not a null result about the
instrument; it is the instrument working. The cost of learning that the target
population is too sparse was CPU time and $0.

### Successor

`PAPER CLOSURE PROGRAM` — workstreams A (held-out source-front-end
faithfulness), B (independent recompilation oracle) and C (claim/evidence
matrix and private draft). IP gate remains CLOSED; `docs/ip/` unmodified.

---

## INC-V2-025 — smoke runs on held-out lineages preceded both new protocol freezes

**Opened** 2026-08-23 · **Class** disclosure, not a defect ·
**Affects** `SOURCE_FAITHFULNESS_HELDOUT_V1`, `ORACLE_INDEPENDENCE_V2` ·
**GPU seconds** 0 · **Cost** $0

Both new instruments were smoke-run against a handful of real lineages before
their protocols were sealed:

    SFH1   --limit 8   admitted 3   receipt sfh1-source-faithfulness--20260823T020607Z-4d87a644df4d
    OI2    --limit 6   judged  2    receipt oracle-independence-v2--20260823T021301Z-f8d3eaca6dd1

Those lineages are drawn from the same held-out frame the full runs use, so
this is worth stating rather than leaving for a reader to notice.

### What was and was not changed afterwards

**No classification, verification or comparison logic was changed in response to
any row either smoke run produced.** The changes made after them were:

- SFH1: a `gate_power` field, which reports whether the silent-drop gate had
  anything to bite on. It reads results and cannot alter one.
- SFH1: an unused import tidied.
- OI2: nothing.

Every control fixture in `changed_region_controls.py`, including both burned
positives and the reachability control, was written and passing **before** the
first smoke run.

### Why the lineages are not withdrawn from the full runs

Withdrawing three lineages from a 320-pair cohort after seeing their rows is a
selection made on observed output, which is the thing these protocols exist to
avoid. Leaving them in and disclosing the exposure is the smaller error, and it
is the one that can be checked: both smoke receipts are immutable and their
contents can be compared against the same lineages in the full run.

### The residual risk, stated plainly

The smoke runs told the author that the harness executed end to end and that the
verdict shape was sensible. That is a weak form of exposure to held-out data and
it cannot be undone by asserting it was harmless. It is recorded here so a
reader can weight the held-out claim accordingly rather than discovering the
exposure afterwards.

---

## INC-V2-026 — the silent-drop localisation is coarse on markdown, and the verdict survives it

**Opened** 2026-08-23 · **Class** instrument limitation, recorded with a bound ·
**Affects** `SOURCE_FAITHFULNESS_HELDOUT_V1` gate `G_SFH1_NO_SILENT_DROP` ·
**GPU seconds** 0 · **Cost** $0

`G_SFH1_NO_SILENT_DROP` asks whether a blocking changed region lies inside a
scope the run declared locally complete. "Inside" needs the scope's source
region, and for markdown the run derives it as the minimum-to-maximum interval
over the witness's located elements. That interval is a **superset** of the
scope, and on 76 of the 101 multi-scope pairs every scope in the document
resolved to the *same* interval.

So the scope-level figure of 209 is an upper bound, and the pair-level figure of
30 could in principle be one too. A gate that fails on an over-attributed
overlap would be an instrument artefact, and calling that a finding would be the
mistake this ledger exists to catch.

### The attribution-free check

There is a criterion that needs no region at all. The pair predicate already
requires the two revisions' raw bytes to differ. So if:

    the compiled state did not move at all,  AND
    some scope was nonetheless declared QUESTION_LOCAL_COVERAGE_COMPLETE

then something changed in the source, nothing reached any artifact, and the
system reported a complete scope anyway. No overlap test is involved.

    attribution-free lower bound   34 pairs   (all git_docs)
    frozen gate, region-attributed 30 pairs

**The lower bound is larger than the gate's count.** The coarse interval is
therefore not inflating the verdict; on this cohort the frozen gate is the more
conservative of the two. `G_SFH1_NO_SILENT_DROP` FAILs under both.

### What is not done about it

The localisation is **not** repaired and the run is **not** re-scored. A
localisation improved after seeing a result is suspicious exactly where it could
move the number, and here it demonstrably could — unlike `INC-V2-023`, where the
cohort was too small for any repair to matter. The honest handling is to publish
both figures with the criterion each rests on, and to leave a sharper localiser
to a successor protocol that freezes it before it sees a cohort.

### Reporting rule that follows

- the pair-level count (30) and the attribution-free count (34) are reportable;
- the scope-level count (209) is reportable **only** as an upper bound, never as
  "209 silent drops";
- the figures that involve no region attribution at all —
  0 unclassified regions, 63,196 unverified MODELED claims of 121,682, and
  60 pairs whose compiled state did not move — carry none of this caveat.

---

## INC-V2-027 — SFH1 and the differential study are downgraded to development diagnostics

**Opened** 2026-08-23 · **Class** evidence hygiene · **Disposition** DOWNGRADED ·
**Receipts** `evidence-hygiene-pass--20260823T035908Z-043914a1ec34`,
`pre-amendment-supersession--20260823T040022Z-b9072c1eda2a` ·
**GPU seconds** 0 · **Cost** $0

The founder's test is one-sided and it is quoted here because the wording is the
whole entry:

> if it cannot be demonstrated that no outcome-derived count/score/gate was
> inspected before the amendment, downgrade SFH1 from held-out to development
> diagnostic. Do not argue around this.

It cannot be demonstrated. Here is why, from artefacts written before anyone knew
this test would be applied.

### The chronology, from immutable receipts and file times

    02:03:24  changed_region_controls.py last written
    02:06:07  SFH1 smoke run, 8 lineages, receipt written and INSPECTED
              outcome keys present: verdict, gates, summary, by_family, result_digest
    02:07:06  SFH1 full run #1 starts                     (process creation time)
    02:13:01  differential study smoke run, 6 lineages, receipt written and INSPECTED
              outcome keys present: verdict, gates, summary, by_family, result_digest
    02:22:51  SFH1 protocol frozen — FIFTEEN MINUTES AFTER ITS OWN SMOKE RUN
              and SIXTEEN MINUTES AFTER the full run it governs had started
    02:22:52  differential-study protocol frozen — nine minutes after its smoke run
    02:31:08  changed_regions.py modified (bisect span index; motivated by a timing
              probe, not by any classification outcome)
    02:34     full run #1 stopped by hand. No receipt of any kind was written.
    02:40:54  sources_sfh1.py and run_sfh1.py modified (2 MB payload bound)
    02:41:08  SFH1 protocol amended
    02:41:16  amendment frozen, digest e946298b
    02:41:47  differential-study amendment frozen, digest e47993fc
    02:41:5x  full run #2 starts
    03:10:17  full run #2 completes; its outcome metrics first exist
    03:33:20  differential study completes

### The finding

**Two receipts carrying outcome-derived metrics predate the amendment**, one per
study, by 35 and 28 minutes respectively. A third fact is worse and was not part
of the founder's test: **both protocols were first frozen after the runs they
govern had already begun.** Neither ever held the property its own header claims.

    SOURCE_FAITHFULNESS_HELDOUT_V1   held_out → development_diagnostic
    ORACLE_INDEPENDENCE_V2           held_out → development_diagnostic

The ruling ordered the first downgrade. The second fails the identical test on
identical evidence, and applying a test to one study and not the other would
leave the stronger-sounding claim standing on the weaker evidence.

### What does not change

**No result is repaired, re-scored or re-run.** Not one number in either study
moves. What changes is the split each may be reported under. The 310 pairs, the
373,006 classified regions, the 0 unclassified, the 30 undeclared losses, the 164
judged pairs and the 30.5% divergence are all exactly as executed.

The pre-amendment executions stay immutable and are marked superseded in a *new*
receipt rather than by editing them — editing a receipt to record that it is
superseded is a mutation of evidence in the name of describing evidence. Full run
#1 is marked `PARTIAL_EXECUTION_NO_RESULT_WRITTEN`: it was stopped by hand and
wrote nothing; the only figure it ever exposed was one progress line of
per-family admitted counts, which is an acquisition-yield figure rather than a
classification outcome and is recorded anyway, because a one-sided test does not
let the party being tested decide what counted.

### What is still held out

`VALUE_BEARING_COHORT_V1`, `VALUE_BEARING_COHORT_V2` and `STOP-V2-005` carry no
pre-amendment outcome exposure and were never amended after a result existed.
Their held-out status stands, and the programme's held-out evidence is therefore
its *negative closure* evidence, not its mechanism evidence.

### The lesson, stated so it binds the successor

A smoke run is an execution. Running one on real cohort lineages, before the
protocol is frozen, spends the held-out property of every lineage it touches and
of the study around it. The successor protocol runs its smoke tests on
**fixtures only**, and freezes before a single real lineage is read.

---

## INC-V2-028 — four confirmed selective stale escapes, and what actually caused them

**Opened** 2026-08-23 · **Class** production defect, forensically confirmed ·
**Receipts** `forensic-stale-escape--20260823T040142Z-0c6f0f65db2e`,
`forensic-stale-escape-root-cause--20260823T040418Z-c4160cdad636` ·
**GPU seconds** 0 · **Cost** $0

The differential study reported four stale escapes. Those were **oracle-relative
divergences** and the founder ruled they may not be strengthened from that result
alone. They were frozen as such, and a separate forensic confirmation was run on
the terms the ruling set:

    production clean full rebuild(new raw)  vs  production selective result(new raw)

Freshly fetched bytes, the production canonicaliser, the production compiler, and
no independent implementation anywhere in the check. The oracle's only role was
to say where to look.

### All four confirm

| case | clean rebuild moved | selective detected | carried though moved |
|---|---|---|---|
| `wikipedia:en:Three Villages` | 1 | *nothing* | `section:u:95960f72…` |
| `wikipedia:en:Monteceneri` | 1 | *nothing* | `section:u:0bf3fdf6…` |
| `wikipedia:en:Locarno` | 1 | *nothing* | `section:u:55f9943b…` |
| `git:pnpm/pnpm.io:docs/cli/change.md` | 6 | `evidence_moved`, `structure_changed` | `topic-bucket:…:0` |

In the three Wikipedia cases the selective path detected **no change of any
kind**, rebuilt nothing, and carried all four artifacts forward, while a clean
full rebuild of the same bytes produces a different `section:` artifact.

**Four named cases. Four is not a denominator.** This is post-result forensic
confirmation, not a rate estimate, and it re-scores nothing.

### The root cause is not what it looks like

Each stale artifact's source difference was classified against a fixed,
declared normalisation ladder — the first rung at which the two texts agree
names the difference:

    typographic_punctuation        1    curly quotes against ASCII quotes
    alphanumeric                   2    punctuation-only differences
    artifact_membership_or_order   1    a topic bucket whose membership moved

**Not one of the four is the compiler missing a substantive content change.**
Three are cases where the semantic diff correctly judged an edit non-semantic
and the artifact fingerprint moved anyway. The fourth is a plan-coverage gap on
a derived membership artifact.

So the defect is an **alignment failure**, and it has a precise shape:

> the diff's notion of "changed" and the artifact fingerprint's notion of
> "changed" are two different functions, and nothing requires them to agree.

The consequence is not that an edit is lost. It is that **the selective state is
not reproducible by a clean rebuild**, which is a different and quieter failure:
every equivalence result the programme has produced was measured on pairs where
the two happened to agree.

### What follows

Both halves are repairs the successor programme owns, and neither is applied
here:

1. the canonicaliser normalises typography and character references, so a
   non-semantic edit does not move a fingerprint; **or** the diff treats any
   fingerprint-moving edit as a change. One of the two, declared, not both by
   accident.
2. derived membership artifacts — topic buckets, indexes, structure maps — need
   their invalidation derived from membership rather than from the structural
   policy's judgement about the document.

Nothing is repaired in this entry. `SOURCE_FACT_IR_V1` is where the repair is
designed, and it must be demonstrated on a fresh disjoint corpus, not on these
four cases.

---

## INC-V2-029 — four cross-lane defects, none of which raised

**Opened** 2026-08-23 · **Class** integration · **Disposition** FIXED PRE-FREEZE ·
**Receipts** `sfi1-protocol-freeze--20260823T051315Z-540eefafba09` (records them
in the frozen protocol) · **GPU seconds** 0 · **Cost** $0

`SOURCE_FACT_IR_V1` was implemented by eight lanes working simultaneously against
one written contract, then integrated in a single deterministic pass. Every
lane's own suite passed throughout, before and after. The integration found four
defects, and the reason to write them down is not that they were hard — three
were one-line fixes — but that they share a shape:

> a cross-lane disagreement does not raise. It reports a clean result.

That is the failure class this whole IR exists to close, arriving through the
import system, through a tuple convention and through a normalisation rule
instead of through a parser. Finding it in three unrelated mechanisms is the
strongest evidence available that the class is real and not an artefact of one
component.

### D1 — two module objects, two registries

`source_fact_ir/ir.py` was imported both flatly (`import ir`, with the package
directory on `sys.path`) and package-qualified (`from source_fact_ir import ir`).
Python built two module objects, so `_REGISTRY` existed twice.

The reference extractor registered into one and `extract_all` walked the other.
It was imported, registered, unit-tested, and produced **nothing**. No exception,
no warning; documents simply contained no reference facts, which is
indistinguishable from documents with no references.

Fixed by having `ir.py` alias itself into `sys.modules` under both names, so
whichever name loads first owns the object and the second is bound to it.
`setdefault`, not assignment: the aliasing must not be able to replace a module
something already holds.

### D2 — an unqualified witness path

Lane 4's dependency resolver anchors on `witness.unit_path = (source_id,
*explicit_path)`. The core extractor emitted the bare `explicit_path`. The
resolver then read `explicit_path[0]` as the source id and derived a document key
of `040c3fd84a6e2c9e` where the real key was `e1f43638beb6bac5` — an invalidation
addressed to a document that does not exist.

Found twice independently: by the integration gate, and by lane 6's forensic tool
in a live run against the four confirmed stale escapes. Before the fix that tool
reported `TYPED_DELTA_WOULD_NOT_HAVE_NAMED_THE_STALE_ARTIFACT` for all four;
after it, `WOULD_HAVE_NAMED` for all four. **The same tool, the same bytes, the
opposite answer** — which is why C-23 records that verdict as a property of the
implementation on the day it ran rather than as a settled fact.

Fixed by declaring `ir.unit_path_for` centrally and requiring every extractor to
use it, with an integration test asserting the property over all registered
extractors rather than over any one of them.

### D3 — an unsupported construct produced nothing

An adversarial fixture put MathML in a document. No extractor claimed it, so no
fact described it, so nothing was wrong: the section scored perfectly. This is
SFH1's finding restated exactly, one level further out.

Fixed by adding the `UNSUPPORTED_CONSTRUCT` kind — a facet type for constructs
whose facet cannot be named, always `UNRESOLVED`, never representable and never
declinable by policy. A policy declining "everything unsupported" would restore
the silence with paperwork attached, so the IR refuses that state combination by
construction.

The side effect matters more than the fix: **the silent-loss endpoint became
measurable.** You cannot count a fact that produced nothing. Detection converts
the absence into a fail-closed fact, and the question turns into a checkable one
— is there a unit the run would call complete that nonetheless contains one?

The detector is a short named list, not a general detector. A general one would
fire on ordinary prose and bury the real cases. The list is checkable line by
line and grows by decision; what it must never do is shrink because a run scored
badly.

### D4 — a normalisation disagreement in both directions

Two lanes disagreed on percent-encoding. One reported a fact change for `%7E`
against `~` — the same URI under RFC 3986 §6.2.2.2, so a false delta and a
spurious recompilation. Over-correcting would have been worse: `%2F` and `/` are
**not** the same URI, and treating them as equal would lose a real path-structure
change.

Ruled by rule rather than by fixture: decode percent-encodings of unreserved
characters only, leave every reserved octet exactly as written. One rule, both
fixtures, no special cases.

### What was not done

**No fixture was widened to match an implementation.** Two adversarial fixtures
failed against real extractors and stayed failing until the extractors changed.
The corpus exists to disagree with the code; a fixture edited to accept the
spelling an extractor happens to handle is a corpus that has stopped being able
to find anything.

### The lesson for the successor

Parallel implementation against a written contract is cheap and it works, but the
contract's *conventions* are where lanes silently diverge — module identity, tuple
shape, normalisation rules. None of those is checkable from inside one lane. The
integration gate is not a formality between lanes; on this programme it was the
only thing that found any of these, and it must run before any freeze rather than
after.

---

## INC-V2-030 — 1,284 units whose text cannot be traced to any source bytes

**Opened** 2026-08-23 · **Class** source-faithfulness defect, held-out ·
**Disposition** OPEN, NOT REPAIRED ·
**Receipt** `sfi1-source-fact-ir--20260823T061908Z-f13fdaf22618` ·
**GPU seconds** 0 · **Cost** $0

`SOURCE_FACT_IR_HELDOUT_V1` returned FAIL on three grounds. This entry is the
third: 1,284 `RECOGNIZED_BUT_UNREPRESENTED` facts, every one a `PROVENANCE_SPAN`,
every one carrying the same reason —

> the unit's text could not be located in the raw source; the canonicaliser
> rewrote it beyond what the three declared location strategies recover

1,048 git markdown · 124 Wikipedia · 112 eCFR. Against 121,065 facts that did
resolve, so the rate is low; the significance is not the rate.

### What it is

Link 1 of the chain — the source witness — absent. The canonicaliser strips
markup, collapses whitespace and joins blocks, so a unit's text is generally not
a substring of the bytes it came from. Three declared strategies recover almost
all of it. For 1,284 units none does, and those units hold text in the compiled
state that **cannot be pointed back at any source bytes**.

Precisely what this is and is not:

- **not a lost edit.** The content is present and its digest matches.
- **a missing witness.** No witness, no anchor; no anchor, and nothing downstream
  can attribute a source change to that unit; and the scope containing it cannot
  be called source-faithful CURRENT.

### Why the old instrument could not have found it

It asked the grammar whether a paragraph was modelled. The grammar said yes, and
the grammar was **right** — the text is carried. Whether the carried text is
traceable to its source was not a question the previous design could pose, so it
had no word for the answer.

Splitting `MODELED` into `REPRESENTED_IN_COMPILED_STATE` and
`RECOGNIZED_BUT_UNREPRESENTED` is what made it askable. The first thing the split
found is a failure the old vocabulary could not have expressed. That is the
argument for the split, and it is stronger than a passing study would have been.

### Not repaired, deliberately

`_locate` was not improved and the study was not re-run. Widening the location
strategies until 1,284 becomes zero, on the corpus that produced the 1,284, is
fitting an instrument to its own result — the same act as moving a quota after a
count exists, in a more sympathetic costume.

The corpus is spent. When a repair is attempted it is demonstrated on a fresh
disjoint corpus or not at all, and this receipt stands as the measurement it is
measured against.

### The successor's actual problem

The repair is not "try harder to find the text". A tolerant matcher that
eventually locates everything is a matcher that will locate the wrong thing, and
a provenance span that is wrong is worse than one that is absent, because the
absent one is visible.

The real fix is upstream: **the canonicaliser should emit the span it read from
rather than leaving the IR to search for it afterwards.** It knows the offsets at
the moment it assembles a block and discards them. Recovering that is a change to
`canonicalization/canonical_document.py`, which is Protected Core and therefore
goes through the full ladder — compatibility contract, shadow, benchmark, canary,
rollout — not a patch.

---

## INC-V2-031 — two safety endpoints were never exercised, and the study failed for it

**Opened** 2026-08-23 · **Class** evidence coverage · **Disposition** RECORDED ·
**Receipt** `sfi1-source-fact-ir--20260823T061908Z-f13fdaf22618` ·
**GPU seconds** 0 · **Cost** $0

`E5_no_confirmed_selective_stale_escape` and
`E6_exact_selective_vs_clean_equivalence` were reported `SKIPPED_NEVER_EXERCISED`.
Each fails the study on its own, independently of INC-V2-030.

Both require artifacts rebuilt from raw payloads and compared, and nothing in
this run did that. The scorer refuses to call them MET under any circumstance
reachable from facts alone, including when the payload cache is present — a
scorer that answered them from facts would be inventing the programme's central
result.

### Why this is recorded as an incident rather than a footnote

Because the alternative was available and would have looked reasonable. Five
endpoints were MET with real gate power behind them; calling the other two "not
applicable to this instrument" and reporting PASS would have passed a review.

    an endpoint nothing could have violated has not been met — it has been avoided

So the two questions `INC-V2-028` actually raised — is the selective state
reproducible by a clean rebuild, and do stale artifacts escape — have **no
held-out evidence at all**. The four forensically confirmed escapes remain four
named cases on the development split, and the typed-delta replay of them
(`C-23`) is a diagnostic on the cases used to design the repair.

### What the successor owes

A study that actually rebuilds. Until one runs, no claim about selective-versus-
clean equivalence may cite SFI1 in either direction: it did not find escapes, and
it did not look.

---

## INC-V2-032 — three defects the V2 integration found, none of which raised

**Opened** 2026-08-23 · **Class** cross-lane integration · **Disposition** FIXED ·
**GPU seconds** 0 · **Cost** $0

Five lanes implemented native provenance in parallel against one written
contract. Every lane's own suite passed throughout. The deterministic
integration found three defects no lane could have found alone, and — as with
all four of the V1 round's — **none of them raised. Each reported a clean
result.**

### 1. The GPU gate was waiting on a study that could never turn green

`gpu_successor_preflight.HELD_OUT_STUDY_STEM` read `sfi1-source-fact-ir`. SFI1
returned FAIL and the founder froze it: never rescored, corpus spent, receipt
permanent. So the gate was waiting for a PASS that no future run could produce,
under a name that was no longer the study being waited on.

It would have held. That is the trap — it was *correct by luck*, and its block
message would have said "the study did not pass" about the wrong study. This is
the second time the fix here has been the same sentence: **a gate that blocks
for the wrong reason will one day unblock for the wrong reason too.** The stem
now names `sfi2-native-provenance`, and `SUPERSEDED_STUDY_STEMS` records why
SFI1 and SFH1 do not count, so a reader who remembers either is told rather than
left to wonder whether the gate forgot.

### 2. A kind was emitted for a year without being claimed

`CoreExtractor` produced `UNSUPPORTED_CONSTRUCT` facts while omitting the kind
from its `kinds` tuple. `unclaimed_kinds()` therefore reported it as a kind
nothing looks for, and something was looking for it.

Nothing broke, which is precisely why it survived: the declaration and the
behaviour disagreed, and only the declaration was ever read. Claiming it also
restores the registry's real function — refusing a second producer, since two
extractors emitting fail-closed facts for one construct would double-count every
unsupported region.

The integration test that catches it asserts the property rather than the
moment: every kind emitted on a fixture is a claimed kind.

### 3. The adversarial fixture corpus had no gate power at all

The provenance fixture lane built twelve adversarial fixtures and a checker,
with a failure witness for every expectation type — good work, and its own suite
was green. Against the real canonicaliser `check_all()` reported
`passed=0, not_exercised=12`: the corpus only accepts an entrypoint taking a
single raw-bytes argument, and `provenance_document` takes eight keyword
arguments.

The lane declined to fabricate the missing metadata, and declining was right —
inventing document metadata would have made every fixture's result partly a
statement about the invention. But the consequence could not stand. **A corpus
that exercises nothing proves its own checker and nothing about the system**,
which is the same failure shape as SFI1's two SKIPPED endpoints wearing
different clothes.

Two rulings closed it, both belonging to the integration rather than to the
lane: metadata is the constructor's context and supplying it is not fabrication,
provided `source_digest` is computed from the fixture's own bytes and the whole
block is visible in the source; and fixtures may be padded past the
canonicaliser's `MIN_TEXT_CHARS` gate provided the padding is a declared segment
in the same offset computation, never sits between a construct and the bytes an
expectation names, and is asserted not to contain any expectation's forbidden
strings.

With one rule above all of it: **a fixture that fails against the real
canonicaliser is reported as a failure, never widened until it passes.** A
fixture adjusted to match an implementation is not a test of that
implementation, it is a description of it.

### Why this keeps happening in exactly this shape

Seven cross-lane defects across two rounds, in an import system, a tuple
convention, a normalisation rule, a facet table, a receipt stem, a kind
declaration and an entrypoint signature. Seven mechanisms with nothing in
common, one shape: a clean result reported by something that was not doing its
job. That the class keeps appearing through unrelated mechanisms is the
strongest evidence this programme has that the class is real rather than an
artefact of any one component — and it is the argument for the integration gate
being a phase rather than a habit.

---

## INC-V2-033 — what the adversarial provenance corpus found before the freeze

**Opened** 2026-08-23 · **Class** instrument limitation, pre-freeze ·
**Disposition** TWO DECLARED, ONE RECLASSIFIED-IN-PROSE ·
**GPU seconds** 0 · **Cost** $0

Twelve adversarial fixtures were run against the real native canonicaliser after
the integration ruling that gave them gate power (`INC-V2-032` §3). Result:
`total=12, passed=9, failed=3, not_exercised=0`. All three failures were
reported as failures. No fixture, expectation or threshold was adjusted to make
one pass — the instruction was explicit and it was followed.

### 1. Malformed markup is absorbed, and the loss is silent (prov-009)

Independently reproduced. For the payload fragment

    The refund window is <b class="term"30 days</a> from delivery.

both the markdown strip and the HTML parser absorb the whole malformed span as
tag soup. `30 days` never reaches canonical text. The surviving unit reports:

    fully_sourced: True   ·   units_failed_verification: 0
    inserted_runs: 0      ·   parser_position_anomalies: 0

**Silent loss with a clean bill of health.** This is the forbidden output — a
construct that produces nothing is indistinguishable from a clean document — and
it sits *upstream of the span map*, so native provenance cannot see it. The map
faithfully describes text that is already missing content, which is exactly the
right behaviour for a map and no comfort at all.

It is not introduced by V2; the legacy canonicaliser strips identically. What is
new is that something finally looked.

**Declared, not repaired**, and the declaration is in the protocol before it was
frozen. The two available repairs are a heuristic detector for malformed markup
— which the `UNSUPPORTED` table deliberately avoids, because a general detector
fires on ordinary prose and buries the real cases — or a reader change, which
would alter what every frozen study would produce on re-run. An over-firing
detector would also push pairs into the fail-closed unsupported set, shrinking
the judged cohort and possibly costing E5 and E6 their gate power, which is the
precise failure V2 exists to remove. **Fitting a detector to a fixture days
before a freeze is how instruments come to describe themselves.**

So E3 now carries a `declared_blind_spot` and a sentence that must travel with
any E3 number this study produces: *MET means no silent loss was found among the
constructs this instrument can see. It does not mean none occurred.*

The successor is owed **byte accounting**: the span map measures output coverage
and nothing measures input coverage, so source bytes consumed inside a unit's
span and represented by nothing are currently uncountable. Counting them makes
this whole class visible with no heuristic at all.

### 2. Span answers are run-granular, and therefore over-approximate (prov-005)

`SpanMap.to_source` returns the minimal enclosure over covering segments. A
query for a sub-range inside one long `COPY` run returns the whole run's span,
which contains bytes the queried text did not come from. The CJK fixture hits
this because nothing — no tag, entity or stripped delimiter — breaks the run
around it.

Bounded honestly: the error is always a **widening**, never a wrong region, and
the IR never asks a sub-range question. `core_extractor` reads the whole-unit
span the canonicaliser computed, and at unit granularity the answer is exact.
A seam test now asserts that no scored path queries a sub-range, so the
limitation cannot be exercised by a future lane without the gate going red.

Recorded rather than fixed because fixing it means either carrying text into the
span map or splitting runs at every character, and the first widens the
contract while the second reintroduces the split-decision arithmetic that
per-character origin tracking was chosen to avoid.

### 3. A fixture whose premise the system cannot reach (prov-011)

`prov-011` asserts that a computed value with no literal source bytes reports an
absent span. `provenance_document` has no interpolation or substitution
mechanism, so the placeholder is never replaced and the value never appears.

**Left classified as FAIL, deliberately.** The accurate classification is
"not exercised — the premise cannot arise", and switching it would be defensible.
It is not switched, for two reasons: reclassifying a failure into a
non-failure is the exact move this programme refuses everywhere else, and the
conservative count costs nothing. What is recorded instead is the truth about
what the FAIL means — a fixture-system mismatch, not a provenance defect. The
general property it was reaching for (inserted text reports no source) is
covered by `prov-004` and by the span-map suite.

### The corpus is now worth what it claims

Nine fixtures pass against the real canonicaliser, three fail for stated
reasons, none is unexercised. Before the ruling it was twelve unexercised and a
green suite. **A fixture corpus that exercises nothing proves its own checker**
— and the two genuine findings above are the return on making it exercise
something.

---

## INC-V2-034 — an eligibility clause with no gate behind it, caught before its freeze

**Opened** 2026-08-23 · **Class** declaration/behaviour divergence, pre-freeze ·
**Disposition** RECORDED IN THE PROTOCOL, FOUNDER DECISION OWED ·
**GPU seconds** 0 · **Cost** $0

`GPU_SUCCESSOR_STUDY_V1` requires, among its eligibility conditions, that *all
four chain links resolve on the current revision — source witness, canonical
representation, fingerprint, dependency path all present.*

Nothing checks the last two. `gpu_successor_preflight.cohort_feasibility` and
`tools/build_successor_cohort.py` each verify kind, state and the
invisible-in-unit-text predicate; neither verifies that a fingerprint and a
dependency path actually resolve, because a cohort manifest does not carry them
— that machinery lives in the compiler lane.

**This is the same shape as INC-V2-029 and INC-V2-032**: a declaration nobody
reads against the behaviour, sitting quietly until something looks. It was found
by the lane building the cohort tooling, which noticed the protocol asked for
more than the preflight it was mirroring, and said so instead of matching the
weaker one silently.

Caught before the freeze, which is the only reason it is cheap. The clause is
annotated in place rather than softened, with the two admissible resolutions
named and the decision left where it belongs:

* **enforce it** — the builder resolves both links per fact and excludes,
  counting, any fact missing either. This may drop the cohort below its floor of
  120, and that would be a real finding about chain completeness rather than a
  defect to route around.
* **narrow the clause** to what is actually checked, and say plainly that
  eligibility is kind plus state plus invisibility, not the full four-link
  chain.

What is forbidden is freezing it as written while nothing checks it. The study
would then claim a cohort property it never verified — and a study that claims
an unverified property is worse than one that claims less, because the claim
survives longer than the memory of how it was checked.

---

## INC-V2-035 — the scorer read E5 under the wrong key, and my own seam test allowed it

**Opened** 2026-08-23 · **Class** cross-lane contract, scored run ·
**Disposition** CORRECTED BY RECEIPT, NOT RE-SCORED ·
**Receipt** `sfi2-score-correction--20260823T085421Z-be3e5836e575` ·
**GPU seconds** 0 · **Cost** $0

The scored SFI2 receipt reports:

    E5_no_confirmed_selective_stale_escape   SKIPPED_NEVER_EXERCISED   exercising 0

That sentence is false. The rebuild ran, 158 judged supported pairs could have
exhibited an escape, and **14 did.**

`rebuild_equivalence.summarise` writes its block under
`E5_confirmed_selective_stale_escape`. `score_sfi2` looked for
`E5_no_confirmed_selective_stale_escape` — the endpoint's name in the protocol.
The two differ by one word, and the word is load-bearing: the protocol names the
endpoint for the PROPERTY it asserts (*no* confirmed escape), while the executor
names its block for the MEASUREMENT it took (confirmed escape). E6's two names
happen to be identical, so E6 scored correctly, the run looked coherent, and
nothing raised.

### The part that is mine, and worse than the typo

I wrote a seam test for exactly this failure —
`test_the_scorer_reads_the_keys_the_summariser_writes` — and it passed
throughout. It drove the real summariser, then asserted:

    assert verdicts[endpoint]["verdict"] in (MET, SKIPPED, FAILED)

**SKIPPED was in the accepted set.** A missing block produces SKIPPED, so the
mismatch satisfied the test written to catch it. The comment beside that
assertion even said what must never happen — "the scorer failing to find the
block at all and reporting its absence as if the rebuild had not run" — and then
the assertion permitted it.

This is the eighth cross-lane defect in this programme and the first that is
mine rather than a lane's, and it is the same shape as all seven others: **it
did not raise. It reported a clean result.** A gate that accepts every outcome
is not a gate. Writing one, while describing in its own comment the outcome it
must reject, is the clearest illustration this programme has produced that a
test's prose is not its behaviour.

### What was done, and what was refused

The founder's order stands: *if FAIL, preserve it and do not repair or re-score
the spent corpus.* So:

* the corpus was **not** re-acquired. Nothing was fetched.
* nothing was **re-measured**. The rebuild ran once, during acquisition, and its
  result was already inside the receipt being corrected.
* the original receipt was **not modified**. It is immutable and it stands.
* no threshold, endpoint or cohort rule was touched.
* the **verdict did not move**: FAIL before, FAIL after.

A separate correction receipt names the original and supersedes its E5 line
only, deriving the true reading from the rebuild block already recorded in it.

**The correction runs in the unfavourable direction** — E5 goes from "not
measured" to "failed, 14 confirmed escapes" — which is the property that makes
it a correction rather than a refit. Nobody fits a result to make it worse.

### Fixed for the next study

`score_sfi2` now carries `REBUILD_BLOCKS`, an explicit mapping of endpoint id to
summary key, and **raises** on a block the executor does not write rather than
reporting the endpoint as unexercised — a scorer describing its own bug as a
property of the cohort is the failure being removed. The seam test now asserts
every key, count field and case field the scorer reads exists in what the
summariser actually writes, and no longer accepts SKIPPED as an outcome for a
rebuild that ran.

## INC-V2-036 — I specified an invariant on a seam where the failure is structurally impossible

**Opened** 2026-08-23 · **Class** contract specification, pre-acquisition ·
**Disposition** CAUGHT BEFORE THE V3 FREEZE, CONTRACT REDIRECTED ·
**Found by** Lane B, in its own `입증되지 않은 것` section ·
**GPU seconds** 0 · **Cost** $0

The founder's P0 ruling asks for an executor invariant:

    required_to_rebuild ∩ carried_forward_without_execution == ∅

I turned that into a written contract and handed it to Lane B as a fixed
interface. Lane B implemented it exactly, wired it at both stages, proved the
wiring with 17 tests, and then reported the thing I had not checked:

> `run_pair`'s classification loop is `if artifact in planned: ... elif artifact
> in prior_state: ...`. It structurally guarantees `planned ∩ carried == ∅`. Both
> checks always pass in this code.

And at the second stage, the equivalence proof is `final[artifact] ==
after_full[artifact]` where `final[artifact] = after_full[artifact]` was just
assigned — **identically true.**

So the invariant I specified could not fail, on a system that had failed E5 and
E6 fourteen times each the day before. Had this reached the V3 freeze, E8 would
have reported zero violations with no gate power for the life of the study, and
the protocol's own rule would then have scored it `SKIPPED` and failed the
study — which is the *lucky* outcome. The unlucky one is that I count a
denominator wrong somewhere and E8 reports MET.

### Where the seam actually is

Two established facts could not both be true alongside 14 stale artifacts:

* SFI2's typed cross-check was clean — 191 of 191 pairs named every moved
  artifact, zero under-invalidated. The invalidation set was **right**.
* nothing in `planned` can be carried. The carry stage is **closed**.

The loss is therefore between them: an artifact the typed delta NAMED that never
became scheduled work. `required_to_rebuild - planned`, not
`required_to_rebuild ∩ carried`. Lane B has been redirected there; Lane A's
forensic supersedes this inference if it lands elsewhere.

### The class, and why this instance is the worst of the nine

This is the ninth instance of *a declaration nobody reads against the behaviour*
— after the import system, the tuple convention, the normalisation rule, the
facet table, the receipt stem, the kind declaration, the entrypoint signature and
the summary key name. Every one reported a clean result rather than raising.

This one is worse than the other eight for a reason worth keeping. The others
were defects in implementations of a correct specification. This was a defect in
the **specification**, written by the party whose job is to check specifications
against behaviour, and handed downward as fixed. A lane implementing it perfectly
would have produced a perfect, useless guard — and only reported it because it
declined to describe an untested path as verified.

The general form: **a gate that accepts every outcome is not a gate, and a guard
placed where its failure is impossible is not a guard.** Before freezing any
endpoint, demonstrate that something could violate it. Lane C carries the same
requirement per channel, for the same reason.

### What was not done

The 14 SFI2 cases were not used to shape the redirection beyond what the frozen
receipt already reports. They remain development fixtures; a case used to
diagnose a defect cannot certify its repair.

## INC-V2-037 — identity normalization was asked whether a unit changed, and it answers a different question

**Opened** 2026-08-23 · **Class** Protected Core semantics, root cause of the SFI2 FAIL ·
**Disposition** ROOT CAUSE ESTABLISHED, REPAIR NOT YET DESIGNED ·
**Receipt** `sfi2-execution-forensic--20260823T095408Z-2dcd1681a54c` ·
**Found by** Lane A, by replaying all 14 cases through the real production
functions rather than reasoning backward from the stale artifact ·
**GPU seconds** 0 · **Cost** $0

All 14 confirmed selective stale escapes resolve to **one** cause,
`single_root_cause: true`, `distribution {"typed_delta": 14}`, 0 unresolved.

`akc_cir.semantic_diff.diff_documents` decides whether to emit `MODIFIED_CLAIM`
by testing `counterpart.identity_text != incoming.identity_text`.
`identity_text` is `akc_cir.identity.normalize_text_for_identity`: NFKC,
casefold, then every non-word/non-space character folded to a space and
whitespace collapsed. In all 14 cases the raw text genuinely differs and the
normalization folds the difference away:

    Apache → Apache®           punctuation folds to a space      8  Druid
    Github → GitHub            casefold makes them equal         1  dolphinscheduler
    "( e.g." → "(e.g."         whitespace collapse               2  eCFR
    hyphen → em dash           punctuation folds to a space      1  eCFR
    "§§ 262.14," → "§ 262.14," punctuation and whitespace        1  eCFR
    ellipsis removed           punctuation folds to a space      1  Playwright

Six surface varieties, one gate. Not six defects.

### Every stage downstream of the seed was correct

This is the part worth keeping. No `MODIFIED_CLAIM` is emitted, so the logical id
never enters `changed_logical_ids`; the graph traversal is never seeded, so it
never reaches the node; `plan.to_rebuild` correctly excludes an artifact nothing
reached — `plan.explain(artifact)` literally returns *"no change reached it"*;
and `run_pair` correctly carries it from `prior_state` because it is not in
`planned`. The scheduler cannot drop a member of `to_rebuild`, and
`verify_equivalence` is never called on the production path at all.

**There is no defective component.** Every stage did exactly what it was built to
do, given its input, and the output was fourteen stale artifacts in ACTIVE state.

### The conflation

`normalize_text_for_identity` exists to answer **"is this the same unit across
two revisions?"** For that question, folding `®`, case, and punctuation is
*correct* — the unit did not become a different unit because a trademark symbol
appeared. `diff_documents` then reuses that answer for a second question:
**"is this unit unchanged?"** For that question the same fold is *wrong*, because
a trademark symbol appearing is precisely a change.

    identity  — did this unit survive?         insensitivity is the feature
    change    — did this unit's content move?  insensitivity is the defect

One function, two questions, opposite requirements. The normalization was not
mis-implemented and no threshold here is mis-tuned; it was asked the wrong
question by a caller that had a different one.

### Why the typed cross-check reported clean, and what that teaches

SFI2's typed cross-check passed 191 of 191 pairs with zero under-invalidation,
and I used that in §9.5 and in INC-V2-036 to argue the invalidation set was
right. It was right — **over the units the delta named.** The cross-check
verifies that every artifact named as moved gets invalidated. It never verifies
that the delta named everything that actually moved.

> A cross-check computed over a set the defect removes members from cannot see
> the defect. Its denominator is downstream of the thing being tested.

That is the same shape as gate power, one level up, and it is the more dangerous
form because the check reported a perfect score. The ground truth it should have
been measured against was available and cheap — Lane A used it: two independent
`build_all()` calls, `clean_before[artifact] != clean_after[artifact]`.

### Corrections this forces

* **INC-V2-036's inference is withdrawn.** I reasoned that the loss sat between
  the invalidation set and `planned`. It sits above the invalidation set, in
  seeding. The finding of INC-V2-036 — that I specified a guard where failure was
  structurally impossible — stands and is unaffected; only my guess at the real
  seam was wrong. It is left in the ledger as written rather than edited, with
  this pointer.
* **Paper §9.5.1's sentence** "the typed delta named every artifact that needed
  rebuilding" is false as stated and must be narrowed to what the cross-check
  actually established.
* **E8's seam in the draft V3 protocol** is not where the repair must be
  measured, and E8 will have no natural gate power. Recorded in
  INC-V2-038 as a founder-visible question rather than resolved quietly.

### What was not established

* Whether any of the 14 lineages carry a second, unrelated divergence mode under
  a different artifact key. Only the keys named in each E5/E6 case were traced.
* The typed cross-check's own "0 under-invalidated" figure was cited from the
  frozen receipt, not recomputed.
* No repair is designed. `akc_cir.identity` and `akc_cir.semantic_diff` are
  Protected Core; any replacement goes through
  compatibility contract → shadow → benchmark → canary → rollout → deprecate,
  and the obvious one-line fix — compare raw text instead — would break unit
  identity across revisions, which is the thing the normalization exists to
  protect.

## INC-V2-038 — three of five typed dependency channels never seed a rebuild, and E4 passed anyway

**Opened** 2026-08-23 · **Class** executor coverage, pre-acquisition ·
**Disposition** ESTABLISHED, ENDPOINT ADDED TO THE DRAFT V3 PROTOCOL ·
**Found by** Lane C, from synthetic cases built from the channel definitions —
**not** from the 14 spent SFI2 cases ·
**GPU seconds** 0 · **Cost** $0

Lane C built an adversarial case per production dependency channel and ran each
through the real functions. Two channels complete the chain. Three never start
it.

| channel | edge in `graph_for` | seeds `changed_logical_ids` | rebuild requested |
|---|---|---|---|
| SEMANTIC | yes | yes | yes |
| STRUCTURAL | yes | yes | yes |
| REFERENTIAL / LOCATOR | **none** | no | **no** |
| TEMPORAL | **none** | no | **no** |
| DESCRIPTIVE / METADATA | **none** | no | **no** |

All three failures return the same sentence from the planner:
`plan.explain(artifact) == "no change reached it"`.

They are blocked twice over, independently. `selective_build.graph_for` builds
edges for SEMANTIC and STRUCTURAL only, and above it
`semantic_diff._SEMANTIC_RECOMPILATION_CHANNELS = {SEMANTIC, GRAPH}` means a
LOCATOR, TEMPORAL or METADATA change never enters `changed_logical_ids` even
when the diff detects it perfectly — and it does detect it, emitting
`EVIDENCE_MOVED`, `TEMPORAL_CHANGED` and `METADATA_CHANGED` respectively.

### The same shape as INC-V2-037, one level wider

INC-V2-037: a change is detected as text, then folded away by a normalization
answering a different question, and never seeds. This: a change is detected and
correctly typed, then filtered out by a channel allow-list, and never seeds.

> The system's ability to SEE a change and its willingness to ACT on one are
> separate mechanisms, and only the first has been under measurement.

### Which explains an SFI2 result that looked clean

SFI2 scored **E4 — no reference-or-locator-only clean miss — MET, 0 over 39
exercising pairs.** That reading is correct and it is not weakened. E4 asks
whether the system *reported no change* when only a reference or locator moved.
The diff reported the change every time; E4 is a detection endpoint and detection
works.

Nothing in SFI2 asked whether the detected change caused a rebuild. Thirty-nine
pairs exercised a channel that cannot seed recompilation at all, and the study
recorded a clean result for them.

An endpoint can be genuinely met, with genuine gate power, and sit directly
beside a defect it was never shaped to ask about. That is not a scoring error —
it is the limit of the question, and the fix is a new endpoint, not a re-reading
of the old one.

### Consequence for the draft V3 protocol

A ninth endpoint is added before the freeze: **every detected typed change in a
supported production channel must create a rebuild request.** On today's system
three of five channels fail it immediately. That is the point — an endpoint the
system already passes measures nothing, and this one is written from the channel
definitions rather than from the spent cases.

### Two further observations, recorded but not chased

* **The synthetic corpus's `section:` artifact digest is built from text alone**,
  ignoring `evidence_id`, `temporal_fingerprint` and `metadata_fingerprint`. So
  even with edges present, rebuild and carry-forward produce identical bytes in
  *that* corpus. Two layers — a missing edge, and a facet absent from the
  artifact spec — and the second would hide the first. Lane C states plainly
  that "a richer spec would differ" is inference, not measurement.
* **Physically reordering a document drives the identity resolver to AMBIGUOUS**,
  scoring 0.85–0.87 against the 0.92 merge threshold, so the pair reports
  `identity_unresolved` rather than `structure_changed`. Neighbour-anchor signals
  are order-sensitive. This is fail-closed and therefore not a silent loss, but
  it means the STRUCTURAL channel is harder to exercise on real reordered
  documents than it looks. The 0.92 threshold is uncalibrated, as all thresholds
  here are.

### Not established

* Three of the five channel rows are `UNPROVEN` at the power step, because
  `observe_no_unexecuted_carry_forward` had not landed when Lane C finished.
  Those tests are `skipif`-gated, not passing — an honest skip, and they must be
  run once the function lands rather than assumed green.
* Lane C's structural case manipulates `unit_order` directly rather than being
  produced end-to-end by one `run_pair` call, because of the ambiguity above.
  The execution half was verified separately on genuinely reordered documents.

## Correction — INC-V2-037's "Recorded in INC-V2-038" cross-reference

**Opened** 2026-08-23 · **Class** ledger correction, cross-reference only ·
**Disposition** CORRECTED, POINTER ONLY, NO HISTORICAL TEXT ALTERED ·
**Applies to** INC-V2-037, "Corrections this forces" bullet on E8's seam ·
**GPU seconds** 0 · **Cost** $0

INC-V2-037's "Corrections this forces" section states that E8's lack of natural
gate power was "Recorded in INC-V2-038 as a founder-visible question rather than
resolved quietly." Checked against INC-V2-038 as written above: its heading and
body are about the three of five typed dependency channels that never seed a
rebuild — the finding that motivates E9. Nothing in INC-V2-038 mentions E8 or a
founder-visible question about it. The cross-reference was wrong.

The E8 founder-visible question — the three-reading choice between (a) keeping
E8 PASS-contributing until its seam can be exercised, (b) reclassifying it as a
fault-injection-validated safety invariant excluded from PASS arithmetic, and
(c) dropping it — is recorded in `protocols/SOURCE_FACT_IR_HELDOUT_V3.yaml`,
under `founder_owed.E8_power`, not in this ledger.

The founder has since ruled on it: **option (b).** E8 is a mandatory fail-stop
safety invariant / veto, its instrumentation power proven pre-freeze by fault
injection, contributing no positive PASS arithmetic; E5, E6 and E9 carry the
held-out statistical criterion; E8's zero natural gate power is reported, never
hidden and never read as positive evidence. See `founder_owed.E8_power` in the
V3 protocol for the ruling in full, and INC-V2-039 below for why repeating an
unexercised endpoint's zero-violation observation still does not exercise it.

INC-V2-037's original text is left exactly as written, per this ledger's
append-only rule for historical entries. This entry is the correction and the
pointer.

## INC-V2-039 — a stable suite green was reported from an interpreter the project does not use

**Opened** 2026-08-23 · **Class** verification reporting ·
**Disposition** CORRECTED BY EXTERNAL REVIEW ·
**Found by** the founder's direct external check · **GPU seconds** 0 · **Cost** $0

`1292 passed, 4 skipped` was reported, stable across five consecutive runs, and
that stability was used to claim the integration was clean. An external run of
the same repository returned `1291 passed, 1 failed, 4 skipped`, with
`test_part14.py::test_a_stale_lock_is_reclaimed_only_after_an_os_liveness_check`
failing, and failing standalone too.

Both readings were accurate. They were taken with different interpreters:

    .venv\Scripts\python.exe   pytest 9.1.1, PyYAML 6.0.3, psutil ABSENT   -> 1 failed
    system python 3.13         psutil 7.1.3 present                        -> 0 failed

A bare `python` on PATH was invoked; the project's interpreter is the `.venv`.
Re-running both confirms the split.

Two distinct failures sit here, and the second is worse than the first.

The first is a reporting failure: which interpreter is authoritative was never
established, and repeating a measurement five times raises confidence in its
**stability**, not its **validity**. Five consistent runs of the wrong command
are five consistent wrong answers — the repetition made the report sound
stronger while adding nothing to it. This is the same shape as this ledger's
gate-power lesson one level up: a check repeated many times over a denominator
that cannot see the defect still cannot see the defect. **Repetition is not
validation. It only looks like validation when the thing being repeated is
correct.** It applies directly to E8's zero-violation cohort observation
(see the correction entry above and `founder_owed.E8_power` in the V3
protocol): reporting E8 clean on run after run of the natural cohort does not
exercise the seam, and is never read as if it did — only fault injection does
that, and it is reported separately as development evidence.

The second is a real defect the first was hiding. `instance_lock` decides
process liveness through an optional import, and `psutil` is not a declared
project dependency. A lock's fail-closed reclaim therefore means
`definitely absent` on a machine that happens to have `psutil` importable and
`undecidable` on one that does not. **A safety property whose meaning depends
on whether an undeclared package is importable is not a property.** The
Windows stale-lock repair needed here is a tri-state liveness check —
definitely-absent / definitely-present / undecidable — that does not depend on
`psutil`.

Also recorded: two `MemoryError` failures were classified as environmental.
Once that was correct in cause and still wrong in disposition — 180MB of
acquisition JSON held whole failed the suite at a *different test each run*,
and a gate that cannot give a stable answer is not a gate; the repair was
streaming. The same explanation was reached for a second failure and it was
simply wrong there. **"Environmental" is a hypothesis, not a disposition**, and
naming it twice was treated, wrongly, as discharging it.

### Fixed for the next report

Every suite claim now carries the exact interpreter and invocation that
produced it. A green result reported without that is not a result — it is an
unlabeled measurement, and this ledger has already shown what an unlabeled
measurement costs once, in INC-V2-035, INC-V2-036 and INC-V2-037.

## INC-V2-040 — "ruff clean" has been reported per-file for a tree CI does not lint

**Opened** 2026-08-23 · **Class** verification scope · **Disposition** RECORDED, NOT REPAIRED ·
**GPU seconds** 0 · **Cost** $0

Every lane in this programme has reported `ruff check <its own files>` → *All checks passed!*,
and every one of those reports is true. Measured today, from the repository root with the
project's own interpreter:

    .venv\Scripts\python.exe -m ruff check research/tavonel_eval_v2
    Found 758 errors.

And `.github/workflows/ci.yml` lints:

    ruff check packages services workers benchmark infra

`research/` is not in that list. It has never been linted by CI.

So two things are simultaneously true and were never stated together: each lane's file is
clean, and the tree those files sit in carries 758 findings. The project constitution says
`ruff` and `mypy` clean; that rule has been satisfied at the granularity anyone happened to
measure, and nobody measured the tree.

This is INC-V2-039's shape without the wrong interpreter. There the scope of a green result was
wrong; here it is merely unstated, which is the same defect earlier in its life. **A passing
check reported without its scope is not a result.** A per-file lint green reads as a tree-clean
claim to anyone who does not run the wider command, and no one had.

### Disposition, and why it is not "fix it"

Not repaired, deliberately. The findings are overwhelmingly pre-existing: `UP031` percent
formatting, `RUF012` mutable defaults, and several hundred `RUF100` unused-`noqa` markers for
`PLC0415`, a rule this configuration does not enable — the house style in this tree annotates
every function-local import with a suppression for a rule that is off. Rewriting 758 sites
across files five concurrent lanes are editing would produce a large mechanical diff, touch
code no one in this session owns, and risk exactly the kind of unreviewed collateral change the
migration ladder exists to prevent.

The honest disposition is to state the number, state that CI does not cover it, and leave the
decision about lint scope to the founder. It is recorded here so that no later reader mistakes
a lane's file-scoped green for a tree-wide one.

### What is owed

Either `research/` joins CI's lint scope and the debt is paid down deliberately, or the
constitution's "ruff clean" is scoped in writing to the trees CI actually checks. Both are
acceptable; silently continuing to report per-file greens against an unlinted tree is not.

### Not established

Whether any of the 758 are real defects rather than style debt. They were counted, not read.

## INC-V2-041 — my freeze gate reported green while checking eight of nineteen conditions

**Opened** 2026-08-23 · **Class** gate specification · **Disposition** REPAIRED BEFORE ANY FREEZE ·
**GPU seconds** 0 · **Cost** $0

I built `tools/freeze_sfi3_protocol.py` to make the founder's nineteen pre-freeze conditions
executable, on the reasoning that a clause with no gate behind it is what INC-V2-034 *is*. The
first version hardcoded eight checks and returned:

    may_freeze: True
    blocking: None

Nineteen conditions were declared. Eight were checked. The other eleven — including
*identity/change separation complete* and *five-channel contract complete*, both of which were
**FALSE**, since the production path still carried both defects — were not evaluated at all,
and their absence was reported as a green.

### Why this is the worst instance of the class so far

INC-V2-036 was a guard placed where its failure was structurally impossible: it could not
fire. This one could fire, and did fire, and reported PASS about things it had never looked
at. The difference matters. An unfireable guard is silent; a green gate is an active claim.
And this gate sits in front of the one irreversible step in the programme — after the freeze
the first fresh lineage may be read, and a corpus once looked at is spent.

Had it been trusted, SFI3 would have been frozen and run against a production system still
carrying INC-V2-037 and INC-V2-038. E9 would have failed on three of five channels and E6 on
the identity fold, and the held-out corpus would have been spent rediscovering two defects
already measured in development. **A held-out corpus can only be spent once, and spending it
to confirm a known answer is the most expensive mistake available here.**

### The repair, and why it is structural rather than additive

Adding eleven checks would have fixed today's gate and left the shape intact — the next
condition added to the protocol would silently go unchecked again. So the checklist is now
DERIVED from the protocol: `build_checks()` reads `pre_freeze_conditions` and maps each to a
check, and any condition with no mapping becomes `UNVERIFIABLE`, which blocks.

> A gate whose checklist is shorter than the list it claims to enforce reports green about
> things it never looked at. The checklist must be derived from the declaration, never
> maintained alongside it.

`UNVERIFIABLE` is deliberately not a softer third outcome. The correct response to a condition
nothing can check is to build the check, never to proceed because no one could tell.

After the rewrite the gate refuses with eight blockers: two hard FAIL (both Protected Core
defects intact in production) and six UNVERIFIABLE. That refusal is the true state, and it is
the first time the gate has said anything true.

### Related, and not the same

INC-V2-039 was a green from the wrong interpreter — the measurement was invalid. INC-V2-040
was a per-file lint green on a tree CI never lints — the measurement was valid but its scope
was unstated. This is the third form: the scope was not merely unstated but silently smaller
than the thing being certified. All three share one root, worth stating plainly because it has
now cost three separate results:

**A result is a measurement plus its scope. Reporting the first without the second is not a
weaker claim — it is a different claim, and usually a false one.**

### Not established

Whether the eleven previously-unchecked conditions had any other false readings among them.
They were unevaluated, not evaluated-and-wrong, so there is nothing to re-read — only the two
hard failures were discovered, and only because the derived checklist forced them to be asked.

## INC-V2-042 — the Protected Core migration ladder ran in the wrong order, and the receipts were written afterwards

**Opened** 2026-08-24 · **Class** process / Protected Core contract · **Disposition** OPEN — FOUNDER'S CALL ·
**GPU seconds** 0 · **Cost** $0

The founder's Lane P ruling named the ladder explicitly and in order:

    corpus-scale identity-regression benchmark -> adversarial controls -> canary -> production switch

What actually happened is the reverse at the end. The production switch landed first —
`akc_cir.semantic_diff` stopped deciding `MODIFIED_CLAIM` on `identity_text` and moved to the
declared change facets — and the lane then died at what its own last message called "rung 3"
before producing either the benchmark or the canary. The repository was left with a migrated
Protected Core module and no receipt for the two rungs that were supposed to authorise it.

I closed those rungs afterwards, in this session, by running the tools the lane had built:

    identity-change-benchmark--20260824T092056Z-eb6269afcbd0.json
    identity-change-canary--20260824T092141Z-36fa48664af6.json

The measurements are good, and they are not the point. Over 538 real revision pairs and 2,536
matched units: under-fire 0, `identity_records_disagree_pairs` 0, canary 5/5 non-tautological
checks, over-fire 1.10% of matched units with all 14 confirmed defect lineages inside it. If the
benchmark had run first it would have authorised the switch.

**But it did not run first, and a benchmark run after the switch is a different instrument.** The
constitution's rule is that "the legacy path stays authoritative until a benchmark says the new
one is not worse." A benchmark run afterwards cannot make the legacy path authoritative again for
the window in which it was not, and it is measured by someone who already knows which answer
would be convenient. The direction it came out is favourable, which is exactly the condition
under which a retroactive check is least trustworthy and most tempting to accept.

Compounding it: I also wrote the freeze-gate check that reads these receipts and grades them. The
implementer produced the evidence and the grader of the evidence. That is the self-approval shape
the constitution names, arrived at by drift rather than by decision.

**Not repaired here, because the remedy is not an agent's call.** The options are at least: accept
the retroactive closure and record why; or revert the production switch, re-run the benchmark
against the un-migrated path, and redo the ladder in order. The second is expensive and would
move everything downstream of it. Both are decisions about what counts as evidence, which the
constitution reserves.

---

## INC-V2-043 — the freeze gate would have sealed a protocol that cannot be executed

**Opened** 2026-08-24 · **Class** gate specification · **Disposition** REPAIRED BEFORE ANY FREEZE ·
**GPU seconds** 0 · **Cost** $0

With every one of the founder's nineteen pre-freeze conditions returning PASS, the gate reported:

    may_freeze: True
    blocking: None

It was wrong, and not in a way any of the nineteen could have caught. `tools/sfi3_worker.py` does
not exist, and `compiler/rebuild_equivalence.summarise` emits no aggregation block for
`E8_rebuild_required_carried_without_execution` or
`E9_detected_change_without_rebuild_request` — two of the four blocks `tools/score_sfi3.py`
reads, and the scorer raises `ContractBroken` rather than defaulting an absent block to SKIPPED.

Every one of the nineteen asks whether the *science* is ready. Not one asks whether the machinery
that would carry it out exists. The declared post-freeze order is

    freeze -> fresh parallel acquisition -> reducer -> scorer -> verdict

so the failure would have surfaced at the scorer — after acquisition, which is the step that
spends the corpus. A spent corpus, a sealed protocol that `_no_prior_freeze` forbids re-sealing,
and no result: the worst reachable ending, produced by a gate reporting green.

Repaired by adding a structural check, `_post_freeze_pipeline_exists`, which requires the worker,
scorer, frame and summariser to exist and derives the required aggregation blocks from
`score_sfi3.EXECUTOR_BLOCKS` rather than restating them — a restated list would drift, and drift
here is invisible until the corpus is gone. The gate now refuses, exit 4, on this alone.

**The general form, which is the fourth appearance of it in this study:** a checklist derived from
one declaration is only complete with respect to *that* declaration. The nineteen conditions were
a complete account of scientific readiness and a silent account of everything else. Deriving the
checklist from the protocol fixed INC-V2-041's undercount and could not fix this, because what
was missing was never in the protocol to be derived from.

---

## INC-V2-044 — two freeze conditions were checks that could only ever return FAIL

**Opened** 2026-08-24 · **Class** gate specification · **Disposition** REPAIRED ·
**GPU seconds** 0 · **Cost** $0

`_identity_change_separation_complete` and `_five_channel_contract_complete` each returned a
hardcoded `CONDITION_FAILED` carrying a sentence describing the tree at the moment they were
written — "the migration ladder stops at the differential", "E9 reports SILENT_DISAPPEARANCE on
LOCATOR, TEMPORAL and METADATA". Both sentences were true when written. Both became false when
lanes P and Q landed, and neither check noticed, because neither check looked.

This is INC-V2-036 pointed the other way. There the guard sat where its failure was structurally
impossible; here the guard sat where its *success* was structurally impossible. Both report a
fixed answer and neither is a measurement. The always-FAIL form is the more comfortable of the
two and not the safer one: it blocks correctly by accident, trains the reader to route around it,
and the day the tree really is ready it is indistinguishable from the day it is not.

Both now measure. The identity check reads the two ladder receipts *and* runs a live probe
against production — a case-only edit must still fold identity-equal (continuity preserved) and
must no longer leave a stale artifact (predicate moved) — so receipts alone cannot satisfy it.
The five-channel check runs the E9 oracle, requires all five channels present before reading any
verdict, and rejects a `SEED_SET` resolution with no dependents.

Thirteen tests in `tests/test_freeze_sfi3_gate.py` assert that each can come back red: missing
benchmark receipt, a single under-fire, identity records disagreeing, a benchmark over zero pairs,
a failed canary, a fold that stopped folding, a returning stale artifact, a probe that carried
nothing forward, one silent disappearance, fewer than five channels measured, an empty seed set.
**Replacing "always FAIL" with "always PASS" would have been no better and much harder to notice**,
which is what those tests exist to prevent.


---

## INC-V2-045 — the two ladder receipts are reclassified, and neither is touched

**Opened** 2026-08-25 · **Class** evidence standing / Protected Core ladder ·
**Disposition** RULING APPLIED, RECORDED IN A NEW APPEND-ONLY ARTIFACT ·
**Receipt** `identity-change-ladder-reclassification--20260825T001252Z-19a899282659` ·
**GPU seconds** 0 · **Cost** $0

INC-V2-042 recorded that the Protected Core ladder ran backwards: the INC-V2-037 production
switch shipped first, and the benchmark and canary that were supposed to authorise it were
produced retroactively in a later session by the same agent that wrote the gate grading them.
The founder ruled: keep the production implementation, preserve
`legacy_identity_change_predicate=True` as the pinned reference path, and reclassify the two
receipts as **RETROSPECTIVE MIGRATION SAFETY REGRESSION**, not prospective ladder qualification.

    receipts/identity-change-benchmark--20260824T092056Z-eb6269afcbd0.json
    receipts/identity-change-canary--20260824T092141Z-36fa48664af6.json

Both are cited by file digest and **neither was opened for writing.** The reclassification is a
new immutable receipt that points at them and says what they are. Correcting the standing of an
evidence artifact by editing that artifact is the shape INC-V2-005 exists to prevent — the record
of what was believed, and when, is itself the evidence — and the tool recomputes both digests
after writing and refuses to exit clean if either moved.

Two readings the ruling forbids, restated here because they are the easy ones to drift into:

* **The 1.10% over-fire figure is descriptive.** It is not an acceptance threshold and no
  criterion in the prospective closure is derived from it. A threshold may be used only if it was
  declared before the result it grades existed. None was.
* **An over-fire is not a false positive.** Legacy disagreement is not ground truth, because the
  legacy predicate is the defect under repair. Naming one a false positive would need an oracle,
  independent of both predicates, saying the unit's compiled-relevant state did not move. There
  is none, so the prospective closure takes its expectations from the declared facet contract
  instead — code that imports neither predicate and whose independence is re-checked by AST walk
  on every run.

---

## INC-V2-046 — three P4i cache slugs collide at 80 characters, and one payload overwrote another

**Opened** 2026-08-25 · **Class** acquisition, pre-existing ·
**Disposition** FOUND BY THE UNIVERSE FREEZE, AFFECTED PAIRS EXCLUDED AND NAMED ·
**GPU seconds** 0 · **Cost** $0

The migration-closure universe freeze recomputes every cached payload's sha256 against the digest
its manifest recorded. Six of 1,778 cached sides in `p4i_cohort.json` did not match.

The cause is not corruption. `document_slug` is truncated at 80 characters, and three pairs of
distinct documents collide there:

    git:kubernetes/website:.../access-application-cluster/access-cluster-services.md
    git:kubernetes/website:.../access-application-cluster/access-cluster.md
    git:grafana/grafana:.../create-data-source-managed-recording-rules.md
    git:grafana/grafana:.../create-grafana-managed-recording-rules.md
    git:kubernetes/website:.../kubeadm/control-plane-flags.md
    git:kubernetes/website:.../kubeadm/create-cluster-kubeadm.md

Each pair writes to one cache directory, so the second acquisition overwrote the first's bytes.
The manifest still records the first document's digest beside the second document's payload.

**Both members of each collision are excluded from the frozen universe, not only the side whose
digest fails.** One of the two holds the wrong bytes and the other may hold the right ones, and
nothing on disk says which is which; keeping the one that still verifies would be choosing the
convenient reading of an ambiguity. All six lineage ids are named in the universe freeze receipt
with their reason. The exclusion is a property of a filename and cannot correlate with any
closure outcome.

Not repaired here. The defect is in P4i acquisition, which is spent, and re-slugging it would
rewrite artifacts other studies already cite. What it costs the closure is three pairs out of 517
candidates. What it would cost a study that read those cached bytes as evidence without checking
them is a silent wrong-document comparison, which is why the check sits in the freeze rather than
in a reviewer's attention.

---

## INC-V2-047 — an unsettled identity is also reported removed, under both predicates

**Opened** 2026-08-25 · **Class** Protected Core semantics ·
**Disposition** ESTABLISHED, CLOSURE FAILS ON IT, NOT REPAIRED ·
**Receipt** `identity-change-migration-closure--20260825T001037Z-bee4064eae33` ·
**GPU seconds** 0 · **Cost** $0

IDENTITY_CHANGE_MIGRATION_CLOSURE_V1 graded **FAIL** on 514 disjoint development pairs. Seven of
its eight invariants are MET. INVARIANT_6 — *ambiguous identity remains unresolved rather than
being forced into continuity* — is VIOLATED, on 9 distinct (lineage, logical id) cases across 8
of the 514 lineages, out of 753 `identity_unresolved` records observed.

The shape, from `ecfr:40:141:141.153`. The before and after documents each carry a unit at the
explicit path `(1)#2`, and `logical_id` is a pure function of source id and explicit path, so both
sides derive the same id `u:aad22330ba59cb2db5271716`. The section was restructured, so the two
units say entirely different things. The resolver scores the incoming unit against a different
before-side unit at 0.77, inside the 0.75–0.92 review band, and returns AMBIGUOUS:

    identity_unresolved  u:aad22330ba59cb2db5271716   candidates ('u:a23ca7b334f770b3eec0d0b3',)
    unit_removed         u:aad22330ba59cb2db5271716

`diff_documents` protects the *named candidates* of an unsettled decision from being reported
removed — `unsettled.update(decision.candidates)` exists for exactly that — but the before-side
unit that shares a logical id with the unsettled incoming unit is not among those candidates. It
matches nothing, is not in `unsettled`, and falls through to UNIT_REMOVED. The diff then carries
two contradictory statements about one key: its identity is unsettled, and it was deleted.

Three things this is not:

* **It is not caused by the migration.** The violation is identical under
  `legacy_identity_change_predicate=True` and `False`, 9 cases each. INVARIANT_1 — identity
  decisions unchanged by the migration — is MET with zero violations over all 514 pairs. The
  predicate switch did not create this and does not touch it.
* **It is not the ambiguity fixture failing.** The declared fixture battery held 11 of 11,
  including the AMBIGUOUS case. The cohort found a shape the fixture does not have: a logical id
  present on both sides while the resolver is unsettled about a different pairing.
* **It is not repaired here.** `akc_cir.semantic_diff` is Protected Core, the ruling that
  authorised this work says to keep the production implementation, and a repair goes through
  compatibility contract → shadow → benchmark → canary → rollout → deprecate. Repairing it inside
  the closure that found it would be the INC-V2-042 shape again with the roles swapped.

The open question for whoever takes it: whether `unsettled` should hold every before-side unit
that shares a logical id with an unsettled incoming unit, or whether the deeper answer is that a
logical id derived from a path cannot carry an identity decision at all when the path survives a
restructure that replaces the unit under it. That is a design question and it is not an agent's
call.

**What the closure establishes, and what it does not.** On a protocol frozen before its cohort,
and a cohort frozen before its measurement, over 514 development pairs disjoint from the 538-pair
retrospective regression, it establishes: identity decisions were untouched by the migration
(INVARIANT_1, 514 pairs); the identity fold is still lossy and still identity-only over 8,132 real
perturbed texts with 8,132 lossiness witnesses (INVARIANT_2); the expectation oracle imports
neither predicate, by AST walk, signature check and runtime binding check (INVARIANT_3); every
changed compiled-relevant facet produced its typed record over 1,917 observations (INVARIANT_4);
nothing unresolved or unknown is discharged by silence anywhere in the oracle's 72-combination
input domain (INVARIANT_5); no ignore was taken that the frozen declaration does not name, over
85,194 facet observations (INVARIANT_7); and no SFI1/SFI2 pair or confirmed defect lineage entered
any denominator (INVARIANT_8). It does not establish INVARIANT_6, and the overall verdict is FAIL.

One further gap, declared in the protocol before execution rather than discovered after it:
production has no fail-closed behaviour for an ABSENT fingerprint on the non-CONTENT facets.
`_nonsemantic_dimension_changes` compares raw values, so two empty temporal fingerprints are equal
and nothing is emitted; the independent facet contract distinguishes "no data" from "the same
data" and reports UNRESOLVED. 37,864 observations landed there. They are counted, never recorded
as unchanged, and never counted as evidence that the channel works. Whether production *should*
distinguish the two is a real question, left to a successor rather than answered here.

A smaller divergence, found by the same fixture: `semantic_diff._content_facet_projection` guards
against a non-`str` text and answers `unresolved`; `change_facets._content_projection` has no such
guard and raises `TypeError`. Raising is still fail-closed — it is not `unchanged` — so it is a
divergence and not a violation, and the facet contract was deliberately not edited to make a
fixture hold. The branch is unreachable end to end in any case: `assign_one_to_one` fingerprints
every unit before the predicate runs, and the fingerprint normalizes `text`.

## INC-V2-048 — the freeze gate graded the migration on the more comfortable of two measurements

**Opened** 2026-08-25 · **Class** gate specification · **Disposition** REPAIRED BEFORE ANY FREEZE ·
**GPU seconds** 0 · **Cost** $0

`_identity_change_separation_complete` was rewritten in this session to stop being a hardcoded
FAIL (INC-V2-044). What it was rewritten to read was the 538-pair benchmark receipt, the canary
receipt, and a live production probe. All three were green, so the condition reported PASS and the
gate reported `may_freeze: True`.

Every one of those three is retrospective or local. The benchmark and canary were measured *after*
the production switch had shipped, by the agent that also wrote the check that grades them — that
is INC-V2-042, and the founder's ruling reclassified them as **RETROSPECTIVE MIGRATION SAFETY
REGRESSION, not prospective ladder qualification**. The probe is one synthetic pair.

Meanwhile the prospectively frozen closure the same ruling ordered had run, over 514 real revision
pairs disjoint from those 538, and returned:

    overall: FAIL      INVARIANT_6_ambiguous_identity_stays_unresolved: VIOLATED

The gate could not see it. Two measurements of one property disagreed, one of them far more
rigorous and specifically commissioned to outrank the other, and the condition was wired to the
weaker pair — so it reported the answer that permitted the freeze.

Nothing was falsified to produce that. The check read what it was pointed at, and it was pointed
at the evidence that existed when it was written. **That is the whole defect class**, now at ten or
so instances in this study: a declaration and a behaviour drift apart, and nobody reads one against
the other, so the stale reading is reported as a clean result. INC-V2-044 was the same shape and
its repair was incomplete in exactly this way — replacing an always-FAIL with a check that reads
the wrong evidence is not a repair, it is the same defect wearing a measurement.

Repaired: the condition now reads the closure receipt and fails while `overall != PASS`, naming the
violated invariant rather than counting it. The retrospective classification travels with the
reading, so a later reader cannot mistake a safety regression for ladder qualification. Three tests
assert the red directions — a failing closure, an absent closure, and the classification label —
and the green direction is supplied by a fixture, because the real closure does not currently pass
and a test suite that could only see red here would prove nothing.

**The gate now refuses.** 22 of 23 conditions PASS; the blocker is the closure, and it is the
correct blocker.



---

## INC-V2-049 — the V2 closure universe exists, and nothing in it has gone unmeasured

**Opened** 2026-08-25 · **Class** empirical power / cohort availability ·
**Disposition** ENUMERATED AND HANDED TO THE FREEZE; SUFFICIENCY IS A FOUNDER RULING ·
**Receipt** `identity-change-migration-closure-v2-universe-enumeration--20260825T014750Z-62ca59c4dbfa` ·
**GPU seconds** 0 · **Cost** $0

The ruling on INC-V2-047 keeps V1's FAIL permanently and requires a V2 closure on a NEW universe.
This is what is left on disk to build it from, enumerated by lineage identity, manifest structure
and payload digests only, before any V2 outcome could exist.

    eligible pairs                16     git_docs 7 · regulation_ecfr 6 · sec_edgar 3
    NEVER_MEASURED                 0
    OUTCOME_VISIBLE elsewhere     16     VBC1 value-bearing probe 15 · P4c retrieval validity 1

**Every eligible lineage has already been read by some other study.** Not by an identity
measurement — that category is excluded outright, and it is what removes the P0/P0b/P0c corpus and
seven of the eight P2 chains. But there is no untouched real-development revision pair left in this
tree. Fifteen of the sixteen come from the VBC1 feasibility probe, whose own frame says in as many
words that "every lineage listed here is spent the moment the probe reports". What it reported was
value-bearing question eligibility, not identity behaviour. Whether a burn taken for one question
reaches a different question is a decision about what counts as evidence, and the enumeration
surfaces it as `NO_NEVER_MEASURED_MATERIAL` rather than deciding it.

**The arithmetic the ruling needs.** At the INVARIANT_6 rate V1 published — 8 violated lineages of
514 — a 16-pair cohort has P(at least one violation observed) = 0.222. A V2 PASS on this universe
would be four-fifths consistent with the defect being entirely unrepaired. That is a limitation of
the material, not of the instrument, and it is stated here before the measurement rather than
discovered in its interpretation. The enumeration declares no sufficiency threshold: none was
declared before the count existed, and a floor chosen now is the thing the over-fire ruling forbids.

**What the founder is being asked, precisely.** Three options, and none of them is an agent's call:
run V2 at 16 pairs and record the power limitation on the face of the result; widen by ruling that
VBC1's burn does not reach an identity measurement, which changes nothing about these 16 but settles
the standing of the whole VBC1 pool; or acquire fresh non-SFI3 material for V2. Reusing V1 is not
among them.

**Two exclusions worth naming separately.** The six P4i collision lineages of INC-V2-046 stay out,
and they are now caught by a detector that does not need a failing digest: a collision is any cached
payload path claimed by two distinct lineages, checked before any digest is recomputed, so a
collision whose members both verify is caught too. And all fourteen Wikipedia candidates are
excluded as `SFI3_DISJOINTNESS_UNPROVABLE_WITHOUT_EXPANSION` — SFI3's roots for that family are
categories, article membership is not decidable from metadata, and expanding a category to find out
is the thing the SFI3 prohibition forbids. An unprovable disjointness is not an assumed one, so
the family leaves rather than being assumed clean. No SFI3 artifact was opened and
`artifacts/development/sfi3_lineages.json` is still absent.

The manifest sits at `artifacts/development/v2_universe/v2_universe_candidates.json`
(`sha256:617dcf5bc431016d5892b02007d730a4b8a62e7f2faaccd140158eb4f3640bc5`, 16 pairs,
universe `sha256:79c1ba79c915d6abadcbed7d876358849a319b31cff81413245c1abde84c6cf0`). It declares
`is_frozen: false` about itself; the freeze is rung 2 of the lane that owns it. Nothing historical
was rewritten: every exclusion lives in the manifest, never in the spent artifact it came from.

---

## INC-V2-050 — two of the checks I wrote to grade the quarantine were watching the wrong population

**Opened** 2026-08-25 · **Class** gate specification, self-inflicted ·
**Disposition** BOTH REPAIRED BEFORE ANY RUNG RECEIPT WAS CITED ·
**Receipts** `identity-quarantine-differential--20260825T015818Z-76663e190708`,
`identity-quarantine-canary--20260825T020817Z-f31ec5cf8a81` ·
**GPU seconds** 0 · **Cost** $0

Rungs 2, 3 and 4 of the INC-V2-047 quarantine ladder are built and green: over the 514-pair frozen
development universe, 4,553 of 4,603 units are classified identically under pin OFF and pin ON, no
unit gains a definite outcome it lacked, no unit vanishes from the diff, and the two transitions are
`identity_unresolved+unit_removed -> identity_unresolved` on the 9 INC-V2-047 cases across 8
lineages and `unit_added -> identity_unresolved` on 41 further units. That is the result. It is not
the entry.

**Both checks that were supposed to prove the reference arm honest reported clean while watching
nothing, and each was found by a different accident.**

The differential's `pin_off_still_reproduces_the_pre_repair_defect` property exists so that pin OFF
cannot quietly stop being production — if the reference arm no longer reproduces INC-V2-047, then
every other number in the differential is the repair compared with itself. It was written as
"`unit_removed` was lost **and** `identity_unresolved` was *gained*". In the INC-V2-047 shape the
unresolved record is **already present under pin OFF**: the whole defect is that the diff carries
two contradictory statements about one key at the same time. So a gained-test finds none of the
nine, and the first full-corpus run reported the reference arm as producing zero cases.

It surfaced only because that one property is gated as a *positive* requirement — it must observe
something — so a zero came back as a loud FAIL rather than as a clean green. **Every one of the
five other properties in the same tool is a must-be-zero.** The identical mistake in any of them —
a detector whose membership test does not match the shape it is looking for — returns zero
violations and a PASS, and nothing about the output distinguishes that from a repair that works.
The asymmetry is worth stating plainly: a check that must see something fails safe; a check that
must see nothing fails silent.

The second is control 2 of the adversarial battery — *an ambiguous candidate never receives a
concrete outcome*. Its predicate derives the population it grades from the `identity_unresolved`
records themselves. Under a mutation that drops every unresolved record — silent disappearance,
which is precisely what obligation 3 of the compatibility contract exists to forbid — control 2
stayed green over an empty population.

That was found by running each of the ten control functions under its declared mutation and
requiring an `AssertionError`, which is a step the battery's own `__can_come_back_red` tests **do
not take**. Those assert the red *condition* through the same predicate the green test uses, so a
predicate that is vacuous in both directions satisfies both halves and reads as a control proven
able to fail. Nine of ten went red immediately; control 2 did not. "Shown able to come back red" is
a claim about a specific mutation, and a red test written beside a green test inherits the green
test's blind spot unless something outside both is what pulls the lever.

Repaired: the differential detector now tests for `identity_unresolved` **present** under pin ON
rather than gained, and reports the withheld removals (9, on 8 lineages) and the withheld additions
(41) separately. Controls 2 and 7 now assert non-vacuity — that the shape produced at least one
implicated unit and a non-empty quarantine — before asserting that nothing implicated carries a
definite outcome. With those in place all ten controls go red under mutation and control 2 goes red
under the vacuity mutation as well.

**One operational note, recorded because it is why both tools are built the way they are.**
`semantic_diff.QUARANTINE_UNSETTLED_IDENTITY_DEFAULT` was read as `False` at the start of this
session, observed as `True` partway through — confirmed twice, by import and by reading line 88 of
the file — and is `False` again at its end, at
`sha256:6c0290c14c90a60a2a3ea9868c73a2f4583a6c0942b24ac9ed9dcddab010fb8c`. The file was rewritten
three times underneath these measurements. No judgement is offered about why, and the digest at the
moment the default read `True` was not captured; what follows from it is mechanical. Both tools pass
`quarantine_unsettled_identity` explicitly on **both** arms and never read the module default, so a
switch moving mid-run cannot turn a differential into a comparison of one behaviour with itself; the
observed default and the digests of both Protected Core files travel inside every receipt; and the
canary re-runs the differential rather than reading the stored artifact, because "stale" here is not
a hypothetical. The nine V1 cases are used as **development fixtures only** throughout.
IDENTITY_CHANGE_MIGRATION_CLOSURE_V1's FAIL is not rescored, repaired, or used as a denominator
anywhere in rungs 2 to 4.

---

## INC-V2-051 — a run id that names the second cannot name a rung, and a ladder made of four of them was a chain with one link

**Opened** 2026-08-25 · **Class** evidence plumbing / gate specification ·
**Disposition** WORKED AROUND IN THE V2 LADDER, NOT REPAIRED IN THE SHARED MODULE ·
**GPU seconds** 0 · **Cost** $0

`evidence.new_run_id` seeds a receipt's run id from the tool digest, the protocol digest, the wall
clock **to the second**, and the pid. That is sufficient for a tool that writes one receipt per run,
which is every tool in this namespace up to now: a stem holds one receipt, the id distinguishes runs
of that stem, and two runs a second apart never collide.

The V2 closure ladder writes four receipts — protocol, universe, scorer/acceptance, exclusions —
from one process, and rungs 2, 3 and 4 each record the run id of the rung before them so that the
ordering is a chain of references rather than a comparison of timestamps. Frozen in one second from
one process, **all four received the same id.** No file was overwritten, because the stems differ,
so nothing raised. The chain checks read as satisfied and would have gone on reading as satisfied
while comparing a value to itself.

What that costs, stated plainly: a stale receipt from an unrelated freeze in the same second would
satisfy a link it does not belong to, and the `require_*` refusals that exist to catch a broken
ladder would confirm one. The ordering discipline that INC-V2-042 bought would have been a string
comparison that could not fail.

It was found by an assertion in the green-direction test — `len({run_id for rung in chain}) == 4` —
written because the red tests alone would have proved that the refusals fire and nothing about
whether they can ever be satisfied correctly. The refusals all fired. The chain they were verifying
was one node wide.

**Worked around, not repaired.** The V2 ladder derives its own run id, adding the receipt stem and
the canonical digest of the receipt body to the seed, so two rungs cannot collide. `evidence.py` is
**not** changed: every existing receipt in this namespace was written under the old derivation, and
altering the function would make the ids in the tree no longer reproducible from the code that
claims to have produced them — which is the mutation-of-evidence shape INC-V2-005 exists to prevent,
arrived at while trying to prevent something else. The old derivation remains correct for the
one-receipt-per-run tools that use it.

**What a successor inherits.** Any future tool that writes more than one receipt per run from one
process has this defect until it does the same thing, and nothing in `evidence.py` warns it. The
general form is the one this study keeps meeting from a new angle: an identifier is only unique with
respect to the things it was designed to tell apart, and a checklist derived from one set of uses is
silent about every other. INC-V2-043 was that shape for a checklist; this is it for a primary key.

**A second observation, recorded because it shapes a criterion rather than a tool.** The INC-V2-047
repair makes an unsettled identity visible by emitting `ChangeKind.IDENTITY_UNRESOLVED` with
`candidates=(quarantine.implicated_by(implicated) or "",)` — `implicated_by` returns `str | None`
and the call site coerces a missing value to the empty string, so a visibility record can name its
implicating unit as `""`. This is **not** reported as a defect in the repair: the record is emitted,
the withholding is stated, and a fail-closed endpoint that says "unsettled, implicated by something
I cannot name" is still louder than silence. It is recorded because a closure criterion phrased as
"accounted for by being named among the candidates" would be satisfiable by that empty string, which
names nothing. IDENTITY_CHANGE_MIGRATION_CLOSURE_V2's INVARIANT_6(d) therefore requires a NON-EMPTY
logical id before it counts a unit as accounted for. Declared before the protocol's freeze, on a
reading of the repair's source rather than of any V2 result.

---

## INC-V2-052 — two of the quarantine contract's four clauses have no members anywhere, and one of them cannot have any

**Opened** 2026-08-25 · **Class** contract coverage / gate power ·
**Disposition** ESTABLISHED AND REPORTED ON THE FACE OF BOTH RUNG RECEIPTS, NOT REPAIRED ·
**Receipts** `identity-quarantine-differential--20260825T022223Z-aeb7bfe3bbf9`,
`identity-quarantine-canary--20260825T022426Z-0308c9c0ab39` ·
**GPU seconds** 0 · **Cost** $0

`akc_cir.identity_quarantine` declares the quarantine as four clauses: (1) every declared candidate,
(2) the selected candidate if a decision selected one, (3) the exact logical-id counterpart of the
unsettled incoming unit — the member INC-V2-047 is about — and (4), transitively, any before-side
unit a *definite* decision matched to an already-quarantined member. Rung 2 counted **membership**
per clause over all 514 pairs of the frozen development universe:

    declared_candidate              725
    logical_id_counterpart           38
    selected_candidate                0
    matched_to_a_quarantined_unit     0
                                    ---
    total members                   763

**Clause (2) is not merely unexercised; it is unreachable as `diff_documents` wires it.** All three
AMBIGUOUS returns in `LogicalIdentityResolver.decide_pair` set `logical_id=None`
(`identity.py:680`, `:712`, `:727`), and `diff_documents` builds `unsettled_decisions` only from
`decision.match is AMBIGUOUS`, passing `decision.logical_id` into the `selected` slot
(`semantic_diff.py:690`). An AMBIGUOUS decision therefore never selects, and the clause cannot
acquire a member from this caller. The clause is not wrong — `build_quarantine`'s docstring is
written for AMBIGUOUS *or* UNRESOLVED resolutions and the caller only supplies the first — but
nothing in this ladder is evidence about it.

**Clause (4) has zero members for a structural reason worth writing down**, because a later reader
will otherwise assume it is merely rare. A definite `MATCHED` between units carrying *different*
logical ids needs a score of at least 0.92. `logical_id` is a pure function of source id and
explicit path, so two different ids mean two different explicit paths, so
`explicit_identifier` scores 0.0 while contributing its 0.15 weight to the denominator. The
renormalised ceiling for such a pair is `(0.95 − 0.15) / 0.95 = 0.842`. It only clears 0.92 when two
distinct explicit paths fold to the *same* identity string under `normalize_text_for_identity` — a
punctuation or spacing difference in a path — which no pair in this universe does. So the clause is
reachable in principle and reached by nothing here, and the fixpoint loop the module's own docstring
calls defensive has never run against real data or against any fixture in the rung 3 battery.

**What made this visible was measuring membership rather than emitted records**, and the difference
is not a detail. Counting `identity_unresolved` records by their declared `detail` gives

    declared_candidate               41
    logical_id_counterpart            0

— zero for the clause the whole repair exists for. That is not a contradiction: clause (3)
suppresses a false `UNIT_REMOVED` while the record that makes the unit visible was already emitted
by the AMBIGUOUS branch under the same logical id, so it contributes no `detail` of its own. A gate
wired to emitted reasons would have reported the load-bearing clause as never firing on a corpus
where it fires 38 times and changes the outcome 9 times. The canary's
`the_quarantine_path_is_actually_exercised` check is gated on membership for exactly that reason,
and both receipts carry `clauses_never_exercised_on_this_corpus` on their face.

**Not repaired here, and the remedy is not an agent's call.** The options are at least: accept the
coverage as declared and record it against the rung 5 decision; add fixture power for clause (4) and
decide whether a contrived same-fold-different-path pair is representative enough to count; or
narrow clause (2) to what the caller can actually supply. What must not happen is a reading of rungs
2 to 4 as coverage of the whole contract. **They cover two clauses of four**, and the passing
verdicts say nothing about the other two.

## INC-V2-053 — the coercions were dead, and the probe that found them was itself powerless

**Raised by:** integration lane, answering two audit points Lane D handed over.
**Anchored to:** `semantic_diff.py` before the fix `sha256:6c0290c1…`,
`identity_quarantine.py` `sha256:7cdcd663…` — the digests Lane B's rung 2–4
receipts are anchored to, verified identical before this edit.

### Point 2 — CONFIRMED, and fixed

Lane D read `candidates=(quarantine.implicated_by(implicated) or "",)` from
source, did not execute the branch, and said: *"If it is in fact unreachable, my
non-empty requirement is a guard where failure is impossible — INC-V2-036
again, and I would rather be told."* It is unreachable, and Lane D is told.

Both call sites test membership first, and `QuarantineMember.reason` and
`.implicated_by` are non-optional `str`. `reason_for` / `implicated_by` answer
`None` only for a **non**-member, which neither call site can be. A probe over
every quarantine path across seven fixtures under both pins took the fallback
zero times. Lane B reached the same place independently from the other end: its
control-10 reachability predicate *filters empty-string candidates*, so the
coercion could not have satisfied it anyway.

The `or` was worse than merely dead. An empty candidate produces a record that
LOOKS well-formed and that a fail-closed consumer scanning for non-empty ids
drops on the floor — silent disappearance wearing the costume of a statement,
which is the exact defect this repair exists to prevent.

Fixed by `IdentityQuarantine.member()`, which raises on a non-member. At the
second call site this also makes an unstated property load-bearing: that branch
is entered on `in quarantine OR in unsettled`, so the lookup is total only
because every `unsettled` member is a DECLARED_CANDIDATE whenever the pin is on.
That subset relation was true and nowhere written down. Now it fails loudly.

### Point 1 — the partition is total, but my first two measurements had no power

Lane D asked whether *matched / added / removed / named-by-a-non-empty-id* is a
total partition. Two successive measurement defects, both mine:

1. The first classifier had **no MATCHED category**, because `SemanticDiff`
   publishes `changes`, `unresolved`, `changed_logical_ids` and
   `structural_change_present` and **has no matched surface at all**. A matched
   unit is only *inferable*, from presence on both sides plus the absence of any
   record. So every unchanged unit counted as unaccounted and the output said
   nothing. That absence is itself the answer to Lane D: **the fifth exit is
   silence**, and INVARIANT_6(d) cannot be computed from the change list alone.
   Any implementation of (d) must infer MATCHED from the before/after id sets,
   or it will fail every pair for a reason that is not the migration.

2. With MATCHED added the partition is total — `population = matched + definite
   + named`, with `vanished = appeared = contradictory = 0` across seven
   fixtures under both pins. But the counts were **identical under both pins**,
   which means none of those fixtures exercised the quarantine at all. A search
   over sixteen further synthetic fixtures — Beta-into-Alpha text blends at
   every strength, drops, swaps, three-to-one and three-to-two restructures —
   changed the outcome in **zero** cases. Two-unit synthetic markdown cannot
   reach the counterpart clause. A measurement that cannot distinguish the two
   paths is not evidence about the repair, and reporting `contradictory = 0`
   from it would have been INC-V2-036 committed by the person auditing for it.

The population that *does* have power is Lane B's rung-2 differential over the
real 514-pair corpus: 4,603 units, 50 changed over 25 lineages, `gained a
definite outcome = 0`, `vanished = 0`, `unresolved-and-also-definite = 0`. The
totality claim rests on that run, not on my fixtures. My fixtures establish only
that the partition holds on ordinary non-quarantine cases.

### Standing limitation, carried to the rung-5 decision

Lane B's INC-V2-052 stands unchanged by this: two of the quarantine contract's
four clauses have no members anywhere, and `selected_candidate` is unreachable
as wired because all three AMBIGUOUS returns set `logical_id=None`. Rungs 2–4
cover two clauses of four. Nothing here changes that, and nothing here is
prospective certification.

## INC-V2-054 — rung 5, and why it could not wait for V2

**Receipt:** `identity-quarantine-switch--20260825T025359Z-ff955fb5543c`
**Subject after the flip:** `semantic_diff.py sha256:05b6a7f7…`,
`identity_quarantine.py sha256:8d96f7fb…`. Rungs 2 and 4 were measured against
`6c0290c1…` / `7cdcd663…`; the delta between those digests is INC-V2-053's
coercion fix and this flip, and nothing else.

`QUARANTINE_UNSETTLED_IDENTITY_DEFAULT` is now `True`.

### The ordering argument, which is the whole reason this is not premature

`IDENTITY_CHANGE_MIGRATION_CLOSURE_V2` measures **production**. With the default
at `False`, V2 has exactly two options and both are worthless: measure the
unrepaired path, or pass the pin explicitly — and a closure that sets its own
pin is not measuring production, it is measuring an argument. So rung 5 is a
precondition of V2 having any power at all, not a reward for V2 passing.

This is the opposite of INC-V2-042's mistake and worth stating plainly, because
the two look alike from a distance. INC-V2-042 was a switch that shipped *ahead
of* the evidence meant to authorise it. This one ships *after* its four rungs,
each with its own receipt, against rows written in the rung-1 contract before
anything was measured. The evidence that is still absent — prospective closure —
is absent by construction and is V2's job, and V2 cannot do that job against a
switched-off repair.

### Discharged, each against a pre-written row

| contract row | observed |
|---|---|
| units gaining a definite outcome | 0 |
| units vanishing from the diff | 0 |
| `tests/unit`, pin ON vs OFF | 993 passed / 68 skipped, identical |
| pin OFF reproduces V1 | 9 cases, 8 lineages |
| the nine V1 cases, pin ON | all close, development only |

Full v2 suite with the flip live: **1903 passed, 4 skipped**. Lane D's two
in-flight failures are resolved. The pin-ON arm was verified genuinely on
(`PIN_ON_PLUGIN: default=True`) rather than assumed — an unconfirmed second arm
is a vacuous second measurement.

### The observer had to be able to say no

`tools/switch_identity_quarantine.py` does not perform the flip; it observes it
and reads each lower rung from that rung's own receipt rather than from anyone's
claim. Three negative controls, all red: pin off with a complete ladder →
`READY_BUT_NOT_SWITCHED`; canary receipt absent → `SWITCHED_WITHOUT_A_COMPLETE_
LADDER`; canary verdict doctored to FAIL → the same. A rung-5 receipt that could
only read PASS would have been INC-V2-044 in the one place it matters most.

### Carried forward, unchanged

V1 remains **FAIL**, permanently, never repaired, rescored, or reused as a
positive denominator. Two of four contract clauses have no members anywhere and
`selected_candidate` is unreachable as wired (INC-V2-052) — they ship inert and
stay declared rather than being quietly deleted. Nothing here is prospective
certification. Nothing is frozen. GPU spend remains 0. `docs/ip/` untouched.

## INC-V2-055 — STOP: the ladder is complete, V2 has no honest denominator, and the remaining question is the founder's

The founder's Section C predeclared this stopping point: *"If no meaningful
disjoint real-development cohort remains: DO NOT reuse V1 and DO NOT open SFI3
early. Run the prospectively frozen adversarial/property closure as far as it
can honestly establish the repair, then STOP and report the remaining empirical
power limitation for a founder ruling. Never invent a denominator."*

That is where the work now is.

### Done, and receipted

Rungs 1–5 of the INC-V2-047 repair ladder are complete: compatibility contract ·
shadow/differential over 514 pairs · ten-control adversarial/property battery,
each control proven able to go red · canary, 8/8 prospective · production switch
(INC-V2-054). The adversarial/property closure has been run as far as it goes:
it establishes that the repair only ever withholds, never silently drops, keeps
the definite vocabulary intact, and does not over-quarantine.

### The limitation, stated rather than papered over

Enumerating candidates from lineage/manifest metadata only — never from
outcomes — leaves **16 eligible pairs** across 3 families. Disjointness holds
against every excluded set: the retrospective 538, all 514 V1 lineages, the 14
SFI2 forensic cases, 6,127 spent SFI1/SFI2 lineages, 1,056 already read by a
non-identity measurement, and all SFI3 material. 1,465 candidates excluded across
14 named categories; 9 collision groups excluded whole.

At the violation rate V1 published (8 of 514 lineages), **a 16-pair cohort has
P(observing at least one violation) = 0.222**. A PASS on it would be weak
evidence of repair wearing the costume of a closure. That figure was computed
after selection was complete and selected nothing.

### Two questions that are not an agent's call

1. **`NO_NEVER_MEASURED_MATERIAL`** — all 16 eligible lineages have been read by
   some other study's measurement, none of them an identity measurement. Whether
   a burn taken for one question reaches a different question is a decision
   about what counts as evidence. Surfaced, not decided.
2. **Whether a 0.222-power cohort should run at all.** Running it and reporting
   PASS would manufacture a denominator; the constitution forbids exactly that.

### Held, pending the ruling

V1 remains FAIL, permanently. SFI3 is **unopened** — no freeze receipt exists
(0), no acquisition artifact exists, and the founder's Section F bars freezing
while V2 closure is absent or failed. GPU spend 0. `docs/ip/` untouched, IP gate
CLOSED. `identity_change_migration_closure_v2.py`, the V2 scorer of record named
in the V2 protocol, does not exist and is deliberately not being written ahead of
the ruling that decides whether V2 has anything to score.

## INC-V2-056 — FOUNDER RULING: the V2 route is ABORTED_BEFORE_FREEZE, and a new V2R1 opens

Additive. Nothing below rewrites or supersedes an existing record; the aborted
route is preserved in full so that the reason it was abandoned stays legible.

### Classification

    current route:  ABORTED_BEFORE_FREEZE
                    INSUFFICIENT_FRESH_CONFIRMATORY_MATERIAL

Not PASS. Not FAIL. Not UNPROVEN wearing a PASS label. The 16-pair cohort is
**not executed**, because executing it and printing a power disclaimer beside
the result would be manufacturing a denominator, which is the one thing the
constitution forbids outright.

**This is not a failed repair.** The INC-V2-047 ladder remains PROVEN at the
development/canary level and the production switch stays ON. What is missing is
prospective empirical closure *power*, which is a property of the available
material, not of the repair.

### Preserved, unmutated

| artifact | digest |
|---|---|
| `protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2.yaml` (draft) | `sha256:b7ab821f…` |
| `artifacts/development/v2_universe/v2_universe_candidates.json` | `sha256:1491f2f3…` |
| enumeration receipt | `identity-change-migration-closure-v2-universe-enumeration--20260825T014750Z-62ca59c4dbfa` |

INC-V2-049, INC-V2-055, the `NO_NEVER_MEASURED_MATERIAL` finding and the 0.222
power calculation all stand. The 16-lineage enumeration remains **descriptive /
development / availability-and-power evidence** and may never become the
positive confirmatory denominator for the repair.

### Burn scope is owned by each corpus's own predeclared contract

The founder declined a universal doctrine that any read burns a lineage for
every future question. Burn scope is whatever that corpus declared **before**
use. Two readings, both taken from source rather than from memory:

**VBC1 — globally burned for confirmatory reuse.** `sources_vbc1_probe.py`
declares, before use: *"This is not the confirmatory cohort and must never
become it"* and *"Every lineage listed here is spent the moment the probe
reports"*, with `burned_after_use: True` and `not_the_confirmatory_cohort:
True`. Its 15 lineages are therefore **ineligible** for any confirmatory
identity-change closure. Reinterpreting that now as "spent only for the
value-bearing question" would be narrowing a predeclared burn after observing
the material, which is the same move in a different costume.

**P4c — no burn declared at all.** `acquisition/sources_p4c.py` contains zero
occurrences of burn, spent, or confirmatory-reuse language; its frozen
`SELECTION_RULE` speaks only to cohort construction. Its declared burn scope is
therefore **NONE_DECLARED**, reported exactly and generalised into nothing. Its
disposition is moot regardless: one surviving lineage cannot constitute a
confirmatory cohort.

### What opens

`IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1` — new protocol id, new freeze chain,
new acquisition frame, no reuse of any frozen or spent denominator. The same
eight substantive invariants carry forward unweakened; INVARIANT_6 keeps zero
tolerance and gains an explicit total-accounting clause (d).

Cohort sufficiency, frozen **before** acquisition: `minimum_admitted_pairs: 200`,
`minimum_families: 3`, over `git_docs · regulation_ecfr · sec_edgar`.

The 200 is a **pre-measurement cohort sufficiency gate and nothing else**. Using
V1's published 8/514 only as a sample-size planning prior, 191 pairs reaches
~95.0% and 200 reaches ~95.66% chance of observing at least one old-rate
violation. That ratio never appears in V2R1's numerator, denominator or scorer.
Acceptance remains: violations == 0 AND all eight invariants MET AND none
UNPROVEN.

## INC-V2-057 — I froze a frame that did not say which sources, then wrote a guard that compared two absences

Two of my own defects on the V2R1 build, both caught before any acquisition, and
both worth recording because they are the same defect this programme keeps
paying for wearing two different costumes.

### (1) The frame was sealed without its roots

Founder ruling section 7 requires the acquisition frame to predeclare source
repositories, CFR parts and issuer sets. The frame I froze as rung 0 declared
families, quotas, traversal order, integrity rules, cache identity and nine
excluded sets — and no roots at all. It said HOW to walk the sources without
saying WHICH, which leaves the traversal underdetermined and leaves acquisition
free to reach for convenient material. That is precisely the steering rung 0
exists to prevent, so the rung was sealed around a hole.

Caught before a single fetch. Corrected by `supersede-frame`, guarded by
`_nothing_has_been_measured`, which permits supersession only while **no V2R1
acquisition artifact exists AND no rung after the protocol has frozen** — both
checked mechanically, neither asserted. That guard is deliberately not a general
amend path: it becomes unreachable the moment one pair is acquired. The
superseded receipt (`…062839Z-c428ff194d7a`) is preserved and named by its
replacement (`…063736Z-eb47b3b794f4`).

The replacement declares 38 documentation repositories and 40 CFR parts, every
one **availability-probed before being declared**, and an SEC issuer rule over
EDGAR's published 10,403-issuer universe. The probes asked only metadata
questions — does this repository exist, does this prefix hold documents, how
many sections carry two or more distinct dated versions, does this issuer have an
amendment pair. No revision content was read; nothing was diffed.

**Disjointness is established at CONTAINER level**, which is stronger than the
lineage-level disjointness the ruling requires and much easier to prove: not one
declared repository appears among the 176 named by any earlier sources module,
none is among SFI3's 32 root repositories, and not one declared CFR part appears
among the ~185 already consumed. A container never touched cannot hold a lineage
that was.

### (2) The chain-link guard compared None to None

Superseding rung 0 left rung 1 pointing at a frame no longer in force. Every
individual receipt was intact; the CHAIN was broken. So I added a check that
rung 1's recorded frame run id equals the frame in force.

It read `receipt.get("run_id")`. Run ids are stored under `provenance`, not at
the top level, so **both sides evaluated to None**, `None == None` held, and the
broken chain reported clean. A guard comparing two absences is a check that can
only return one answer — INC-V2-044's exact shape, written by the hand that had
just finished auditing for it, three hours later.

Fixed by `_run_id_of`, which reads `provenance.run_id`, and by an explicit
refusal when either side is missing: a None is UNKNOWN and blocks, never
"matches". Verified by observing the refusal fire against the real broken chain
before repairing it, rather than by reasoning that it would.

### Why both are recorded rather than quietly fixed

Neither reached data. Both were found by mechanisms this programme already
required — writing the guard's negative control, and running the check against a
state known to be broken. The lesson is not that these two bugs existed; it is
that *the author of a rule is not exempt from breaking it*, and the only thing
that caught either was a mechanical check rather than care.

## INC-V2-058 — a canonicalisation that production could not read, and a repair that destroyed metadata

Three findings on the V2R1 build. None reached a measurement; all three are mine.

### (1) The scorer of record carries a misleading filename, permanently

The frozen V2R1 protocol names
`research/tavonel_eval_v2/tools/identity_change_migration_closure_v2.py` in
`scorer.modules`. I corrected `manifest_contract.path` when deriving V2R1 from
the V2 draft and did not correct this one — the same incomplete-derivation error
as INC-V2-057(1), in a second field.

By the time it surfaced, rung 1 was frozen AND acquisition had happened, which
shuts the supersede path by design. Renaming the file breaks the frozen digest;
amending the protocol after data exists is exactly what the freeze forbids. So
the file keeps the name the contract gave it and its docstring says in its first
sentence that it scores **V2R1**, not the abandoned V2. The abandoned V2 has no
scorer and never will.

This is recorded rather than fixed because the honest options were a misleading
name or a broken freeze, and a broken freeze is worse.

### (2) The eCFR canonicalisation emitted a shape production cannot read

`fetch_v2r1_corpus.canonicalise` built eCFR units with `heading_path` and no
`heading`, and no `text_sha256`. `selective_build.snapshots` — the code
production actually uses — reads `unit["heading"]` and raises `KeyError`.

**All 106 eCFR pairs in the first frozen universe were unmeasurable.** Had the
closure run, they would have failed as a block for a reason with nothing to do
with the migration. That is precisely the trap INC-V2-053 records against
INVARIANT_6(d) — a criterion failing every pair because of how the data was
prepared — arriving from the opposite direction. It was caught by running the
scorer's plumbing over real pairs before freezing the scorer, which is the only
reason it was caught at all.

Fixed by mirroring `canonical_document`'s unit construction field for field
rather than inventing a parallel shape. A second shape for the same concept is a
second thing that can drift.

### (3) The repair silently replaced real timestamps with null

Re-deriving canonical documents from the stored raw bytes seemed safe:
canonicalisation is a deterministic transform of frozen bytes, selection is
pinned by lineage id and raw digest, and the tool refetches nothing and verifies
every raw digest before touching anything.

It was not safe. The acquisition manifest does not carry `known_at`, so the
re-derivation passed `None` — and **overwrote `version_time.known_at` in all 564
canonical documents**, replacing real git committer dates and SEC filing dates
with null. The tool reported "rewritten: 564, unreadable: 0" and looked like a
success. The giveaway was that git documents were rewritten too, when only eCFR
should have changed; a repair that touches more than its subject is a repair
that is doing something else as well.

The constitution's rule is *never invent data to satisfy a schema*. Writing null
over a known value is the same failure with the sign flipped: it destroys a fact
to satisfy a code path. The damaged corpus was set aside rather than patched,
and the corpus re-acquired from the sources.

Re-acquisition is legitimate here for one reason and it is worth naming: **no
outcome has ever been read.** The frame is frozen at rung 0, the procedure is
deterministic given that frame, and nothing about the new selection can have
been steered by a result nobody has seen.

### The guard added, and why it is weaker than the other two

`supersede_universe` is gated on `_nothing_has_been_scored` — no measurement
receipt exists — rather than on `_nothing_has_been_measured`, which the rung-0
and rung-1 paths use.

The two guard different things. Rungs 0 and 1 protect SELECTION, so they must
shut as soon as any corpus exists: once you can see the material you could
choose around it. Rung 3 pins the universe, and re-sealing it only becomes
dangerous once an OUTCOME has been observed, because that is the first moment a
change could be steered by a result. Before then, a universe that cannot be
measured at all is simply broken, and refusing to repair it protects nothing —
it only guarantees the closure fails for a reason unrelated to the question.

The distinction is deliberate and is the kind of thing that should be argued
rather than assumed. If a later reader disagrees, the place to say so is here.

## INC-V2-059 — IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1 = FAIL. Executed once. Corpus spent.

**Receipt:** `identity-change-migration-closure-v2r1--20260825T075028Z-fc54677a5d9a`
**Universe:** 285 pairs — git_docs 126, regulation_ecfr 109, sec_edgar 50.
**Verdict:** `INVARIANT_6` **VIOLATED**, 30 violations. Executed exactly once,
with `--write-receipt`, and no preview run: a dry run would have let the author
see the answer before committing it, which is the optionality this whole
apparatus exists to remove.

### What passed, with power

| clause | violations | observations |
|---|---|---|
| (a)(b) unsettled identity carries no continuity assertion | 0 | 332 |
| (c) AMBIGUOUS never enters matched-facet reproduction | 0 | 330 |
| (d) TOTAL UNIT ACCOUNTING | **30** | 4,545 |
| (e) every unsettled identity visible on `identity_unresolved` | 0 | 330 |

None of these is vacuous. 330 unsettled identities actually occurred, so (c) and
(e) had something to fail on and did not. (d) examined 4,545 units.

Cohort gates, all frozen before acquisition and all met: 285 ≥ 200 admitted;
3 ≥ 3 families; per-family floors 126/109/50 against 40/40/25. Disjointness holds
against all nine excluded sets, and with real power — 1,799 / 1,715 / 562 / 348 /
208 / 16 comparable ids, plus 32 SFI3 and 42 VBC1 root containers compared at
container level.

### The 30 violations, split by cause

Concentrated in **3 lineages**, not spread: `ecfr:40:273:273.3` (27),
`git:qdrant/landing_page:…/capacity-planning.md` (2), `ecfr:47:54:54.101` (1).

    13 of 30   the unit IS named by another record kind -- `evidence_moved` --
               that clause (d)'s implementation does not count as accounting
    17 of 30   the unit is named by NOTHING: no record of any kind mentions it

**The first 13 are a defect in my scorer, not in production.** Clause (d)
counted only `unit_added`, `unit_removed`, `modified_claim` as definite and
`identity_unresolved` as named. `EVIDENCE_MOVED` is a fourth exit, and I did not
account for it — despite writing a paragraph about silence being "the fifth
exit". This is Lane D's warning landing exactly where it was aimed: *"If there
is a fifth exit I did not think of, (d) will fail every pair for a reason that
is not the migration."*

**The second 17 are a real observation about production.** On
`ecfr:40:273:273.3` the before and after documents each hold 14 units with
**zero shared logical ids**. Production emitted 14 `evidence_moved` records —
every one naming a BEFORE-side id — and one `modified_claim`. Not a single
after-side id is named by any record. So a move is recorded against its ORIGIN
only, and the destination unit cannot be accounted for by id at all. Whether
that is a correctness defect or a representation gap is not mine to rule on; it
is exactly the kind of thing (d) was written to surface.

### What happens now, per founder ruling section 12

    V2R1 = FAIL, permanently.
    The 285-pair corpus is SPENT as prospective closure evidence.
    NO repair-and-rescore on this corpus. Clause (d) is NOT fixed and re-run here.
    SFI3 remains UNOPENED. GPU remains 0.

The temptation is obvious and is refused on the record: 13 of the 30 are my
scorer's fault, so "fix (d) and rerun" would very likely turn FAIL into PASS.
That is precisely the move the ruling forbids and precisely why it forbids it —
a corpus that has shown its answer cannot then be asked a slightly different
question. The same reasoning that made V1's FAIL permanent applies here with no
discount for the failure being partly mine.

Stopped for a founder ruling.

## INC-V2-060 — FOUNDER ADJUDICATION: V2R1 was an invalid instrument, not a production failure

Additive. INC-V2-059 stays exactly as written — it is the true record of what was
executed and what the frozen scorer returned. This entry adds what that result
MEANS, which is a different question and one INC-V2-059 got wrong.

**Adjudication receipt:** `identity-change-migration-closure-v2r1-adjudication--20260825T094904Z-2abd1efe37e4.json`

    raw_execution_verdict            FAIL
    scientific_adjudication          INVALID_INSTRUMENT_CONTRACT
    production_correctness_verdict   NOT_ESTABLISHED
    corpus_status                    SPENT
    rescore_permitted                false

V2R1 was executed prospectively and exactly once, but its frozen INVARIANT_6(d)
encoded the wrong identity-accounting ontology and therefore did not validly
measure the intended property. It is **not** a successful closure, **not**
evidence that production failed INVARIANT_6, and **not** convertible to PASS.

### All 30 violations are instrument false violations

My 13/17 split is superseded, and both halves of it were wrong. Recomputed
independently here rather than transcribed:

| lineage | before | after | raw overlap | resolver | matched w/ differing raw id |
|---|---|---|---|---|---|
| `ecfr:40:273:273.3` | 14 | 14 | 0 | MATCHED 14 | 14 |
| `git:qdrant/…/capacity-planning.md` | 7 | 18 | 1 | MATCHED 2, AMBIGUOUS 2, NEW 14 | 2 |
| `ecfr:47:54:54.101` | 5 | 3 | 0 | MATCHED 1, AMBIGUOUS 1, NEW 1 | 1 |

**14 + 2 + 1 = 17** — exactly the count of alleged silent appearances. They are
resolver-MATCHED incoming units whose revision-local raw ids differ from the
stable before-side ids the resolver chose. The 13 alleged disappearances are the
before-side counterparts consumed by those same matches, correctly not reported
as removed.

### Root cause

`selective_build.snapshots` derives a snapshot logical id from
`source_id + explicit_path`, so an incoming unit's revision-local id changes when
its path changes. `LogicalIdentityResolver` exists precisely to bridge that: on
MATCHED it returns the BEFORE-side stable logical id while the incoming snapshot
keeps its own. Therefore `before_ids ∩ after_ids` is **not** the set of
cross-revision identity matches.

`matched_pairs()` already documents this exact case and reproduces
`assign_one_to_one` for exactly this reason. I read that function, reused it for
clauses (c) and (e), and then built (d) on raw id intersection anyway — the
correct model was in front of me and in use two lines away.

### EVIDENCE_MOVED is not the fix and not a defect

Adding `EVIDENCE_MOVED` to `DEFINITE_KINDS` would be an outcome-informed local
patch preserving the wrong ontology. It is emitted only AFTER the resolver has
matched a counterpart, so it is a facet event on an established correspondence,
never an identity disposition. Neither is `MODIFIED_CLAIM`. The two concepts are
now separated explicitly:

    identity disposition   MATCHED / NEW / REMOVED / AMBIGUOUS-UNRESOLVED
    facet event on a match MODIFIED_CLAIM, EVIDENCE_MOVED, TEMPORAL_CHANGED, …

Production keys EVIDENCE_MOVED to the stable resolved prior identity, which is
consistent with MATCHED semantics. Recorded as **representation / observability
debt**, not a correctness failure: `SemanticDiff` publishes no first-class
matched-correspondence surface, which forced the scorer to reconstruct matching
and contributed directly to the bad inference. **Production is not altered to
make a spent receipt green.**

### What opens

`IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2`, with all 285 V2R1 lineages excluded
from the prospective denominator and the ≥200 / ≥3 floor preserved. The three
violating lineages become DEVELOPMENT/FORENSIC regressions and may never certify
V2R2.

---

## INC-V2-061 — V2R2 opens: one resolver surface, a thirteen-shape mutation battery, and two adapter traps caught before the freeze

**Date:** 2026-08-25
**Status:** OPEN — V2R2 frozen through rung 1, acquisition running
**Supersedes nothing. Repairs nothing. Rescores nothing.**

### What was built

Founder ruling sections 6 through 9 open
`IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2` with a redesigned INVARIANT_6(d). The
apparatus:

| piece | what it is |
|---|---|
| `tools/v2r2_resolver_surface.py` | the single identity-disposition surface (c), (d) and (e) all read |
| `tools/v2r2_invariant6.py` | the clauses, rebuilt over that surface |
| `tests/test_v2r2_invariant6.py` | the thirteen §9 controls plus the three spent V2R1 shapes |
| `acquisition/sources_v2r2.py` | rung-0 frame: 35 repositories, 34 CFR parts, SEC above CIK 8177 |
| `protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2.yaml` | new id, new chain, `sha256:56bbe4c4…` |
| `tools/freeze_migration_closure_v2r2.py` | an ADAPTER over V2R1's freezer, not a fork |
| `tools/enumerate_v2r2_universe.py` | ten excluded sets, V2R1's spent cohort first |
| `acquisition/fetch_v2r2_corpus.py` | the fetch rung 0 authorises |
| `tools/identity_change_migration_closure_v2r2.py` | the scorer of record |

### The correction, stated once

V2R1's clause (d) asked whether a unit carried SOME record. V2R2's asks whether
it carried the RIGHT one for its resolver disposition:

- **A MATCHED (b, a)** — the ids MAY DIFFER. Silence is legitimate. A
  `unit_added` for either id, or a `unit_removed` for `b`, is a violation.
- **B NEW (a)** — `unit_added` required; silence is a violation.
- **C AMBIGUOUS (a)** — `identity_unresolved` required, no definite outcome.
- **D before-side unconsumed** — `unit_removed` or a visible unresolved naming;
  silence is a violation.

Plus one-to-one conservation, which V2R1 never checked at all.

**The same absence of a record is legitimate under A and a violation under B and
D.** That is the whole thing. Silence is interpreted by the resolver's decision,
never by its own absence. A clause that read silence as one fixed thing had to
be wrong in one direction; V2R1's managed to be wrong in both at once, turning
one renamed unit into a fabricated silent appearance plus a fabricated silent
disappearance.

`EVIDENCE_MOVED` was NOT added to the definite-outcome set. Control 12 asserts a
MATCHED unit carrying it PASSES, so the forbidden repair cannot creep back in
without a red test.

### The battery discriminates — checked, not assumed

V2R1's clause (d) passed its own test suite, because the tests and the
classifier were written from the same wrong idea. So the new battery was run
against the OLD clause on control 1's shape:

```
V2R1 clause on control-1 shape: 2 violations / 2 observed
  src:old/path#1 :: a before-side unit left the diff with no record of any kind
  src:new/path#1 :: an after-side unit appeared with no record of any kind
```

The old clause fabricates exactly the pair the adjudication describes; the new
one is clean. A battery both clauses passed would have proved nothing.

The three spent V2R1 shapes come back clean over non-empty populations
(14 / 23 / 7 observations) and still carry 17 renamed correspondences, asserted
by a test — a regression over material that no longer exhibits the defect would
be hollow.

### Two traps the adapter set, and why the adapter is still right

The V2R1 freezer is ~1,900 lines of chain, digest and refusal logic that must
behave identically. Forking it would create a second implementation free to
drift. So V2R2 imports and overrides. Both failures below were caught before any
freeze:

**(1) A dataclass default cannot be rebound by assigning a module global.**
`base.Workspace` compiles its field defaults into `__init__` at class creation,
so setting `base.PROTOCOL = <v2r2 path>` left `base.Workspace()` handing out
V2R1's protocol — and every rung inside the base module resolves
`ws or Workspace()`. A V2R2 rung would have sealed itself against V2R1's
protocol with nothing to show for it. Fixed by subclassing (frozen, like its
parent) and rebinding `base.Workspace` to the subclass.

**(2) The derived gate test called `base.load_protocol()` bare** — whose default
argument is the same baked-in V2R1 path. Twenty-four tests named `..._v2r2` were
asserting things about the PREDECESSOR and passing. Three failed loudly only
because their assertions happened to name the protocol id and the manifest path;
the other twenty-one would have stayed green forever.

`_verify_override_targets()` runs at import and raises if any override target
has vanished from the base module, and `test_override_target_verification_actually_fires`
proves that guard can go red. The lesson is the same one this ledger keeps
recording: **an override that lands on nothing is not an override**, and the
only difference between (1), (2) and INC-V2-036 is which layer the unreachable
guard was sitting in.

A third, smaller find: V2R1's `freeze_acquisition_frame` checked for existing
material at `ws.root / "artifacts" / "development" / "v2r1_corpus"`, but
`ws.root` is the REPOSITORY root while the corpus lives under
`research/tavonel_eval_v2/`. That path never existed, so the guard could not
fire. **Not repaired in V2R1** — its run is spent and its digests are bound into
the adjudication receipt. V2R2's adapter checks the real path first and the
reason is recorded here rather than smoothed away.

### Disjointness

Ten excluded sets, V2R1's spent cohort first. The enumerator subtracts the UNION
across every V2R1 universe receipt (286 ids, superseded ones included); the
measured cohort is 285 and is counted separately so the two are never confused.
The universe freeze re-reads V2R1's receipt and proves disjointness
independently — the filter and the proof are separate implementations, because
a filter and a proof written as one piece of code agree by construction.

Container-level disjointness is additionally established: not one of the 35
repositories or 34 CFR parts appears among the 235 repositories and 215 CFR
parts any earlier sources module names, and the SEC walk starts strictly above
CIK 8177, V2R1's highest admitted issuer. A container never touched cannot hold
a lineage that was. That is stronger than required and does not license skipping
the lineage-level check.

### What is NOT claimed

- Nothing about V2R2's outcome. Nothing has been acquired, enumerated, frozen
  past rung 1, or scored.
- Nothing about production correctness. V2R1 established none and V2R2 has not
  run.
- The three spent shapes certify nothing. They are development regressions.
- V2R1 is untouched: no edit, no delete, no rescore. INC-V2-059 stands.

### State

- V2R2 rung 0 frozen `20260825T102142Z-94aedc16c7a3`, rung 1 frozen
  `20260825T102151Z-de4c44b1b9c8`.
- Suite: 1,959 passed / 4 skipped before the adapter tests; +13 adapter, +24
  gate.
- SFI3 unopened. GPU 0. `docs/ip/` untouched, IP gate CLOSED.

---

## INC-V2-062 — IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2 = FAIL. Executed once. Corpus spent. 13 clause-(d) violations, all disposition B.

**Date:** 2026-08-25
**Receipt:** `identity-change-migration-closure-v2r2--20260825T104800Z-c1041a14bdc3.json`
**Verdict:** `INVARIANT_6` **VIOLATED** — 13 violations over 4,661 clause-(d) observations.
**Corpus:** SPENT. No rescore, no same-corpus repair, no second run. The re-run
guard is live and refusing.

### The chain, all frozen before execution

| rung | run id | pinned |
|---|---|---|
| 0 acquisition frame | `20260825T102142Z-94aedc16c7a3` | `sources_v2r2.py` |
| 1 protocol | `20260825T102151Z-de4c44b1b9c8` | `sha256:56bbe4c4…` |
| 3 universe | `20260825T104523Z-6a50832c28d1` | `sha256:8450deb2…`, 270 pairs |
| 4 scorer/acceptance | `20260825T104559Z-db606c6abc47` | 5 modules |
| 5 exclusions | `20260825T104603Z-df0b99bbab45` | policy + realised set |

Executed once, no preview. The gate re-verified every digest and every link
after the run and still reports `READY` with the measurement named under
`already_measured`.

### Cohort

459 candidates constructed → 274 admitted → **270** after disjointness
subtraction. git_docs 126 / regulation_ecfr 77 / sec_edgar 67. Floor 200 met,
three families, every family floor met. 540 sides, 6,956 canonical units, all
readable by `selective_build.snapshots` (checked structurally before the scorer
freeze — the check INC-V2-058.2 cost a whole corpus for lacking).

### Result

```
INVARIANT_6  : VIOLATED
  violations : 13
  observations: {"a_b": 310, "c": 349, "d": 4661, "e": 349}
  clause_a_b : 0 violations
  clause_c   : 0 violations / 349 observations
  clause_d   : 13 violations / 4,661 observations
  clause_e   : 0 violations / 349 observations
dispositions : {"matched": 2295, "matched_with_differing_raw_ids": 34,
                "new": 652, "ambiguous": 297, "unmatched_before": 1417}
```

**The cohort contained 34 renamed correspondences and clause (d) passed every
one of them.** That was the whole point of the redesign, and the census is in
the receipt so the claim is checkable rather than asserted. A V2R2 PASS over a
cohort with zero renames would have been a pass the V2R1 defect could also have
produced; this cohort had them and the new clause handled them.

### The 13, and what production actually did

All 13 are **disposition B**, across three eCFR lineages:
`ecfr:47:20:20.19` (8), `ecfr:7:3560:3560.105` (4), `ecfr:7:3560:3560.102` (1).

Disposition B says: the resolver settled this after-side unit as NEW, therefore
`unit_added` naming it is required, and silence is a violation.

Forensics on the spent corpus — recomputed, not transcribed:

| lineage | before/after | diff emitted | NEW without `unit_added` |
|---|---|---|---|
| `ecfr:47:20:20.19` | 76 / 94 | 44 `identity_unresolved`, 17 `unit_added`, 6 `unit_removed` | 8 |
| `ecfr:7:3560:3560.105` | 45 / 52 | 27 `identity_unresolved`, 6 `unit_added`, 3 `modified_claim`, 2 `unit_removed` | 4 |
| `ecfr:7:3560:3560.102` | 73 / 52 | 23 `identity_unresolved`, 11 `unit_added`, 26 `unit_removed` | 1 |

**Every one of the 13 was emitted as the SUBJECT of an `identity_unresolved`
record, and additionally named as a candidate inside another one.** Production
did not go silent. It declined to assert the unit was added and stated the
uncertainty instead.

The branch is deliberate and `semantic_diff` says so in its own comment:

> the quarantine, applied to EVERY definite outcome and asked before any of them
> is emitted. It was first written just below the NEW branch, so a quarantined
> id could still escape as `UNIT_ADDED` — one of the exact outcomes the invariant
> forbids. The development replay caught it: violations went from 0 to 12 against
> a pre-repair baseline of 0, all of them `unit_added` on a quarantined id.

Suppression is selective, not blanket: those same three lineages emitted 17, 6
and 11 `unit_added` records for NEW units that were *not* quarantine-implicated.

### My reading — offered as a hypothesis, NOT as an adjudication

I believe disposition B as I wrote it is too strict, and that this is an
asymmetry in my clause rather than a defect in production. Disposition D was
written as *`unit_removed` **or** visibly unresolved*; disposition B was written
as *`unit_added`* with no equivalent alternative — even though the same argument
applies to both. A unit whose identity is entangled in a quarantine has not been
established as new, and asserting `unit_added` would make exactly the definite
claim the quarantine exists to withhold.

**I am not deciding this and the founder should not read it as decided.** Two
reasons:

1. **I got the V2R1 diagnosis wrong.** I reported a confident 13/17 split with a
   root cause, and founder ruling §2 superseded all of it: "the previous 13/17
   split is superseded." A second confident diagnosis from me, of the same
   clause, in the same direction, is worth less than the evidence above.
2. **Founder ruling §4 forbids exactly the move my hypothesis suggests** in its
   V2R1 form: do not repair a clause so a spent receipt turns green. Whether
   "disposition B should accept a visible unresolved record" is a legitimate
   pre-registered semantics correction or the same forbidden move wearing a new
   hat is a judgement about the contract, and the contract is not mine.

What is not in doubt: **V2R2's raw verdict is FAIL, the corpus is spent, and no
rescore is permitted.** Whatever adjudication follows, it cannot make this run
a PASS.

### What was NOT done

- The measurement receipt is untouched. Nothing rescored, nothing re-run.
- **No production code was altered.** `semantic_diff` was not changed to make
  the receipt green, and `EVIDENCE_MOVED` was not added to any definite set.
- No clause was edited after the freeze. The scorer modules still match their
  rung-4 digests; the gate re-verified them after the run.
- No pair was removed, added or re-selected.
- SFI3 remains unopened. GPU 0. `docs/ip/` untouched, IP gate CLOSED.

### Disjointness, for the record

Ten excluded sets, all holding on the frozen 270. Four lineages left the
universe under `NOT_DISJOINT_FROM_SFI1_SPENT` **and**
`NOT_DISJOINT_FROM_VBC1_PROBE` — all four sections of 7 CFR 273, which I had
declared as a fresh root and which turned out to be both SFI1-spent and a VBC1
declared root. My pre-declaration scan of prior sources modules missed it
because those modules store CFR parts in a different tuple shape than the one I
matched.

That miss surfaced a second defect, in the enumerator inherited from V2R1: its
disjointness pass could only **report** an overlap, never subtract it. It had
never fired, because V2R1's cohort happened to have none — a guard that was
correct, was checked, and had no effect. INC-V2-036's shape in a new place. The
enumerator now subtracts, names every set that claimed each row (all four rows
were claimed by two), and re-proves disjointness over the survivors. The
universe freeze proves it again independently from the frozen receipts.

**The subtraction is not a repair of the cohort.** It applies exclusions the
rung-0 frame declared before any fetch, no outcome was read, and no reason was
invented at run time.

### State

- V2R1: FAIL, `INVALID_INSTRUMENT_CONTRACT`, spent, untouched.
- V2R2: FAIL, spent, awaiting adjudication.
- Suite: 54 V2R2 tests passing, no skips.
- Blocked on the founder for the §11/§12 question: V2R2 FAILED, so SFI3 stays
  unopened and the successor chain does not advance.

---

## INC-V2-063 — FOUNDER ADJUDICATION: V2R2 carried CONTRADICTORY OBLIGATIONS. Invalid instrument, not a production failure.

**Date:** 2026-08-25
**Adjudication receipt:** `identity-change-migration-closure-v2r2-adjudication--*`
**V2R2 raw receipt:** untouched. `RAW_EXECUTION_VERDICT = FAIL`,
`INVARIANT_6 = VIOLATED`, `CLAUSE_D_RAW_VIOLATIONS = 13`. Corpus SPENT, no
rescore.

```
SCIENTIFIC_ADJUDICATION        = INVALID_INSTRUMENT_CONTRACT
PRODUCTION_FAILURE_ESTABLISHED = false
CORPUS_SPENT                   = true
RESCORE_PERMITTED              = false
```

### The finding is stronger than what I reported

I reported this as "disposition B was too strict" and offered it as a
hypothesis. The founder's inspection found something categorically worse, and
the correction is worth stating precisely because the difference is not one of
degree.

V2R2's INVARIANT_6 was **unsatisfiable**. For a unit in

    resolver NEW  ∩  quarantined

- clause (d) disposition B **required** `unit_added`;
- the INC-V2-047 compatibility contract, clause 2, **forbids** `unit_added` on
  any quarantined member;
- V2R2's own clause (e) **required** `identity_unresolved` for the same unit.

No implementation can emit and not emit the same record. The instrument did not
measure a property production failed. **It described a state production is
forbidden to occupy.** "Too strict" describes a bar set high; this was two bars
pointing in opposite directions, one of them inside the same invariant.

### Recomputed evidence

| lineage | quarantine members | `unit_added` emitted | violating units |
|---|---|---|---|
| `ecfr:47:20:20.19` | 37 | 17 | 8 |
| `ecfr:7:3560:3560.102` | 29 | 11 | 1 |
| `ecfr:7:3560:3560.105` | 24 | 6 | 4 |

Census over all 13: `NEW+QUARANTINED: 13`, `stated_as_identity_unresolved: 13`,
`asserted_as_unit_added: 0`.

Every one was quarantined, every one was stated on the unresolved channel, and
none was asserted as added. Meanwhile 34 `unit_added` records were emitted for
NEW units that were *not* quarantined, in those same three lineages. The
suppression is selective and it is the contract working.

### Why this is not an outcome-conditioned relaxation

The adjudication receipt binds
`docs/COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md`
(`sha256:655fd3d8…`) and the pre-existing quarantine differential receipt.
Every semantics cited was written, implemented and receipted **before V2R2 was
drafted**:

- the contract predates the ladder rungs and V2R2;
- production's guard predates V2R2 and sits above the NEW branch deliberately —
  its own comment records that placing it below produced 12 violations in a
  development replay, all `unit_added` on a quarantined id;
- the differential receipt already contained `UNIT_ADDED → IDENTITY_UNRESOLVED`
  transitions.

Nothing is being loosened after seeing a result. The instrument contradicted a
contract that already existed.

### The model that was missing

Identity has **three layers**, and V2R2 had one:

    LAYER 1  ResolverDecisionSurface           local decision
    LAYER 2  IndependentQuarantineSurface      overlay
    LAYER 3  EffectiveIdentityDispositionSurface   the composition

Quarantine does not change the resolver's historical result. **It changes what
production is allowed to ASSERT from that result.** V2R2 called Layer 1 the
final identity disposition — the same category error as V2R1's, one layer up:
V2R1 mistook a raw snapshot id for a resolved identity, V2R2 mistook a resolver
decision for an effective disposition.

### Production is NOT changed

No repair is authorised from this result. Specifically forbidden: moving the
quarantine guard below NEW, emitting `unit_added` alongside
`identity_unresolved`, weakening the quarantine, removing the transitive clause,
changing identity normalisation, changing the facet predicate. Production's
`local definite result + global quarantine → explicit unresolved` is the
intended fail-closed behaviour, established before V2R2.

### What follows

`IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3`, and a **contract-consistency gate**
that mechanically compares the executable semantics against the compatibility
contract before any freeze. That gate is the hole that let V2R2 through: the
contradiction was reachable, statable and provable before a single pair was
fetched, and nothing was looking. `NEW + QUARANTINED` should have been a
mandatory negative-control row.

V2R1 and V2R2 are both spent and both become development regressions:
V2R1's shapes must show renamed correspondences accounted through the resolver
mapping, V2R2's 13 must classify as resolver-local NEW plus quarantine override
yielding `EFFECTIVE_UNRESOLVED`. Neither becomes positive confirmatory evidence,
and no "corrected V2R2 verdict" is written.

SFI3 unopened. GPU 0. `docs/ip/` untouched, IP gate CLOSED.

---

## INC-V2-064 — The V2R3 instrument, repaired at the layer both predecessors collapsed: resolver decision, quarantine overlay, effective disposition

**Date:** 2026-08-25
**Status:** OPEN — instrument repaired and proved; V2R3 not yet framed, not frozen, not executed
**Supersedes nothing. Repairs no production code. Rescores nothing.**

### The defect, stated at the layer it lives on

V2R1 read a raw snapshot id as a resolved identity. V2R2 read a resolver-local
decision as a final disposition. These are the same mistake at two depths:
**collapsing a layer that production keeps separate.**

Production has three, and only the third is a thing anybody is entitled to
assert:

| layer | what it is | who owns it |
|---|---|---|
| 1 `ResolverDecisionSurface` | MATCHED / NEW / AMBIGUOUS, per after-side unit | `assign_one_to_one` |
| 2 `IndependentQuarantineSurface` | which ids are under identity uncertainty | the INC-V2-047 contract |
| 3 `EffectiveIdentityDispositionSurface` | what production may ASSERT | layer 1 composed with layer 2 |

**Quarantine OVERRIDES a locally definite identity assertion.** It does not
rewrite the resolver's answer — the resolver said NEW and historically still
says NEW — it changes what may be claimed from that answer. V2R2's clause (d)
read layer 1 and its clause (e) read layer 2, so for `NEW ∩ QUARANTINED` the
instrument required `unit_added` and forbade it in the same breath. That is not
a strict rule. It is an **unsatisfiable contract**, and no production behaviour
could have satisfied it.

### What was built

| piece | what it is |
|---|---|
| `tools/v2r3_effective_identity.py` | the three layers, composed once, rows A–G, `verify_total()` |
| `tools/v2r3_state_table.py` | the finite model checker: 8 reachable rows, side-scoped obligations |
| `tools/v2r3_quarantine_oracle.py` | the expected side, independent of production's implementation |
| `tools/v2r3_invariant6.py` | (c), (d), (e) rebuilt so all three read ONE surface |
| `tools/root_identity.py` | one canonical root reader for all 17 historical attribute shapes |
| `tests/test_v2r3_power_battery.py` | the 18 section-8 controls, each with a red mutation direction |
| `tests/test_v2r3_instrument.py` | independence, satisfiability, roots, and both spent corpora |

### Satisfiability is proved before the freeze, not asserted in prose

`check_contract()` enumerates every reachable (side, resolver state,
quarantined) combination, obtains the disposition by **calling the classifier**
rather than by consulting a parallel table, and refuses if any row's required
and forbidden sets intersect:

```
after  MATCHED q=False -> EFFECTIVE_MATCHED    [E] require=[]                    forbid=[unit_added, identity_unresolved]
after  MATCHED q=True  -> EFFECTIVE_UNRESOLVED [D] require=[identity_unresolved] forbid=[unit_added]
after  NEW     q=False -> EFFECTIVE_NEW        [C] require=[unit_added]          forbid=[identity_unresolved]
after  NEW     q=True  -> EFFECTIVE_UNRESOLVED [B] require=[identity_unresolved] forbid=[unit_added]
after  AMBIGUOUS q=any -> EFFECTIVE_UNRESOLVED [A] require=[identity_unresolved] forbid=[unit_added]
before unconsumed q=False -> EFFECTIVE_REMOVED    [G] require=[unit_removed]        forbid=[modified_claim, identity_unresolved]
before unconsumed q=True  -> EFFECTIVE_UNRESOLVED [F] require=[identity_unresolved] forbid=[unit_removed, modified_claim]
SATISFIABLE: 8 reachable rows
```

Row B is the one V2R2 died of. It now requires a **visible** unresolved record
and forbids `unit_added` — one obligation, not two contradictory ones.

The gate is mutation-controlled: reinstating V2R2's obligations makes
`check_contract()` raise `CONTRACT_BROKEN`. A satisfiability check that has only
ever returned SATISFIABLE is indistinguishable from one that always will
(INC-V2-044).

**Over-quarantine is a defect too.** A genuine addition with no uncertainty
still REQUIRES `unit_added`; a genuine removal still REQUIRES `unit_removed`.
The repair is not a blanket surrender, and two controls hold that line.

### The oracle is independent, and an AST guard proves it

`v2r3_quarantine_oracle.py` reimplements the INC-V2-047 compatibility contract
(`docs/COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md`,
`sha256:655fd3d85eebec5209a2489290b34a8ca9d6c4cff8f1ac39e8504e4447f1b101`) from
the contract text. It imports `akc_cir.identity` — obtaining decisions from the
resolver is allowed, the property under test is their integration — and nothing
else from production. A test walks its whole AST, not just the top level,
because a function-local import would be exactly as much of a tautology.

Oracle-vs-production parity is checked **separately and on spent material**, and
is labelled DEVELOPMENT. It is not the expected side and never will be:
comparing production to itself yields a check that can only agree.

### A third instance of the same family, found on spent data

Writing the accounting surfaced a defect one layer below both predecessors: a
logical id is unique **per side**, not across sides. One id can carry an
unmatched before-side unit that ended and an unmatched after-side unit that
began at the same path. Production correctly emits `unit_added` and
`unit_removed` for that id; an accounting that indexed by id alone read each as
a violation of the other.

The repair is side-scoped obligations plus explicit composition — required by
union, forbidden by **unanimous** intersection minus required — which makes the
composition satisfiable by construction rather than by inspection.

Control 1 then caught the composition's own trap: a MATCHED correspondence whose
before and after ids are EQUAL contributes twice from **one** unit, and
intersecting those two contributions cancelled both prohibitions, letting a
matched unit be reported added. Same-holder contributions are now unioned first,
and only different holders compose. **One unit speaking twice is one obligation;
two units sharing an id are two obligations that must agree before either binds.**

### The root normaliser catches what V2R2's frame missed

Each sources module encodes roots in its own shape, so V2R2's pre-declaration
scan matched one of them and admitted 7 CFR 273 — SFI1-spent and a VBC1 declared
root. `root_identity.py` is the single reader: 12 modules, **875 canonical
identities** (ecfr 265, git 268, sec 18, wikipedia 324), **0 unverifiable**. A
shape it cannot interpret returns `UNVERIFIABLE` and **blocks**. It is never
assumed disjoint — that assumption is the whole mechanism of the V2R2 clash.

### Both spent corpora, as DEVELOPMENT regressions only

All six spent shapes come back clean over non-empty populations. On the V2R2
side, **13 quarantine overrides** (8 + 4 + 1) are exercised — the exact 13 units
that produced V2R2's raw violations now classify as resolver-local NEW with a
quarantine override to `EFFECTIVE_UNRESOLVED`, and production's explicit
`identity_unresolved` records discharge that obligation.

**These results certify nothing.** V2R1's 285 and V2R2's 270 lineages are SPENT.
Material whose outcomes have been read cannot become a prospective confirmatory
denominator, and this ledger entry is not a corrected V2R2 verdict. V2R2's raw
FAIL stands, unrescored, adjudicated `INVALID_INSTRUMENT_CONTRACT`.

### State

`tests/test_v2r3_power_battery.py` 19 passed · `tests/test_v2r3_instrument.py`
27 passed · full `research/tavonel_eval_v2` suite **2042 passed, 4 skipped** ·
ruff clean.

**Production code is untouched.** `akc_cir.semantic_diff`,
`akc_cir.identity_quarantine` and `akc_cir.identity` are byte-identical to their
pre-V2R2 state. No guard was moved below NEW, no quarantine was weakened, no
transitive clause was removed, no normalisation or facet predicate was changed.
Founder ruling section 3 forbids all of it, and nothing here is a repair of
production: **an invalid instrument establishes no production defect to repair.**

### Still owed before execution

Section 10's contract-consistency freeze gate · section 13's V2R3 protocol,
frame, enumerator, fetcher, scorer and freezer · section 14's full precondition
set, then exactly one execution with no preview.

---

## INC-V2-065 — FOUNDER AUDIT: V2R3's new proofs were computed but never sealed. A false-provenance seam, caught before rung 0.

**Date:** 2026-08-26
**Status:** REPAIRED — rung 0 not executed; no V2R3 corpus, no V2R3 receipts
**Found by:** founder audit, independent repository inspection
**Production code untouched. No spent tooling edited.**

### P0 — the seam

The V2R3 freeze wrappers did the equivalent of:

```python
proof = compute_v2r3_proof()
result = base.freeze_...(ws)
result["proof"] = proof
return result
```

The base freezer **writes its immutable receipt inside its return path**. So the
three V2R3-only fields — `root_disjointness`, `contract_consistency`,
`spent_disjointness` — existed in the returned dictionary and in console output,
and **in no frozen body at all**.

**A console line saying the proof passed is not a frozen proof.** The run would
have looked proved while the receipt recorded nothing, which is the same shape as
every defect this study has caught in itself: a check whose result nothing can
later verify is not a check.

### P0.1 — and the gate would not have caught it

`STAGES = dict(base.STAGES)` inherited `gate`, so the execution gate was the
base's, which verifies protocol → universe → scorer → exclusions and knows
nothing about the three V2R3 proofs. All three could print PASS and the chain
could report READY with no immutable receipt binding any of them.

### The repair — companion attestations, not a hook in the base

V2R1's and V2R2's freeze machinery is **spent-run evidence**. Adding a hook to it
would change the tooling that produced receipts the founder ordered preserved. So
each V2R3 rung now writes a SECOND immutable receipt that BINDS the base receipt
it attests and carries the proof in its own frozen body.

| attestation | binds | proves |
|---|---|---|
| `frame_attestation` | base frame receipt (path, run id, file digest) · `sources_v2r3.py` · `root_identity.py` · a canonical digest of the whole prior-root set | unverifiable == 0, clashes == 0 |
| `protocol_attestation` | base protocol receipt · protocol yaml · `v2r3_state_table.py` · `v2r3_effective_identity.py` · `v2r3_quarantine_oracle.py` · the consistency suite · the INC-V2-047 compatibility contract | SATISFIABLE, 8 reachable rows, required ∩ forbidden empty per row, prose ↔ executable rows exact |
| `universe_attestation` | base universe receipt · V2R1's universe receipt · V2R2's universe receipt | V2R3 ∩ V2R1 == 0, V2R3 ∩ V2R2 == 0, recomputed |

**Bound three ways**: path, run id, and the digest of the receipt file on disk.
The path alone can be replaced and the run id lives inside the file it
identifies, so the file digest is what makes the binding checkable from outside.

**The prior-root-set digest is pinned**, not just its count. Zero clashes against
a *different* prior set — a sources module added, removed or edited — is not the
proof that was frozen, and a count would not catch the swap.

**An attestation of a superseded rung is refused.** Otherwise a base rung could
be re-frozen and its predecessor's attestation would still satisfy the gate.

### `require_v2r3_execution_preconditions`

`STAGES["gate"]` is overridden by name. The gate runs the base chain, then
requires all three attestations, re-verifies each against the base receipt it
claims to attest, recomputes every pinned digest, and **re-runs all three proofs
from scratch** rather than trusting the recorded finding — an attestation read
but not recomputed only proves a file has not changed, which is not the same as
the proof still holding.

It also **refuses** when a V2R3 measurement already exists. The base gate
*reports* prior measurements; a closure runs exactly once, and a report is not a
refusal.

The V2R3 scorer will call this gate and never `base.require_execution_preconditions`.

### A second defect the repair exposed — and the wrong fix I tried first

Wrapping the rungs turned **eight V2R2 adapter tests red** in a single pytest
process. Every adapter over this base rebinds names on ONE module object, so a
permanent rebind at import makes correctness depend on **which adapter imported
last**. That is not a theoretical worry twice over: the same mechanism made 21 of
24 V2R2 gate tests assert things about V2R1 and pass (INC-V2-061).

My first repair was `_assert_bindings()` at the start of every rung — **detection,
not correction**. A refusal telling the operator to re-import in a different order
is a correct diagnosis of a design nobody should have to remember.

`_bound()` now applies the bindings for the duration of ONE RUNG and restores
them afterwards, on the error path too. Import order stops deciding anything.
`_assert_bindings()` is retained inside it for the case the applier cannot fix: a
base that renamed an attribute out from under the adapter, where `setattr`
quietly creates a new name nothing reads.

### P1 — two declarations of one truth

`FAMILY_QUOTA` summed to 480, its declared target. `FAMILY_SHARE` summed to
**0.99**. The comment claimed they were the same composition.

`FAMILY_QUOTA` is now the single authoritative declaration and `FAMILY_SHARE` is
derived from it as **exact rationals** — `17/48`, `5/16`, `1/3`, summing to
exactly 1. Rounded floats cannot sum to one, and a test that allowed them to be
close would be a tolerance in a file that has no tolerances.

### Red directions, each proved to fire

deleted companion receipt · edited attested source file · edited bound base
receipt · attestation bound to a superseded rung · introduced root clash ·
introduced UNVERIFIABLE root shape · changed prior-root-set digest · contradictory
state-table row · a genuinely failing consistency suite · base chain green but
attestations absent · a measurement that already exists. Plus the green
direction: an intact chain reports READY carrying all three recomputed proofs.

One test was found passing for a weaker reason than it claimed — a superseding
receipt written in the same second does not reliably sort later, because run ids
share a timestamp and are ordered by a hash suffix. It now writes an explicit
lexicographically greater run id, so the test passes by the property rather than
by luck.

### State

`tests/test_v2r3_attestation.py` 23 passed · the three instrument/contract files
59 passed · full `research/tavonel_eval_v2` suite **2078 passed, 4 skipped** ·
ruff clean.

**Rung 0 is NOT executed.** No V2R3 corpus exists, no V2R3 freeze or measurement
receipt exists, and no V2R3 outcome has been read. The remaining lanes —
enumerator, fetcher, scorer — are drafted and tested before any fetch runs
against the fresh roots.

---

## INC-V2-066 — the V2R3 chain froze, a stale test executed the closure and crashed before grading, and the repair is inside a rung-4-pinned module. BLOCKED on a founder ruling.

**Date:** 2026-08-26
**Status:** BLOCKED — gate REFUSED; no measurement receipt; no outcome read
**Production code untouched. No spent tooling edited. docs/ip untouched.**

### The chain that was built and verified

| rung | receipt run_id |
|---|---|
| 0 acquisition_frame | `20260825T173240Z-2ddcbbfc3c8d` |
| 0a frame_attestation | `20260825T173240Z-8d8c7cbeb23e` |
| 1 protocol | `20260825T173257Z-170b873cf8c2` |
| 1a protocol_attestation | `20260825T173258Z-5954c7c33e27` |
| 3 universe | `20260825T180058Z-914589827af0` |
| 3a universe_attestation | `20260825T180058Z-82b34786f311` |
| 4 scorer_acceptance | `20260825T180251Z-bb65b8985c08` |
| 5 exclusions | `20260825T180316Z-38ee80b8cb07` |

Acquisition admitted **300 pairs** (git_docs 133, regulation_ecfr 104,
sec_edgar 63) from 480 candidates. Floor 200 MET, every family above its own
floor, SUFFICIENT, `disjointness_holds True`, zero subtractions. Universe
attestation recomputed `intersections {'v2r1': 0, 'v2r2': 0}` independently of
the enumerator's own filter. The V2R3-specific gate reported **READY** once.

### Three adapter defects found only because the chain actually ran

1. **`RecursionError` after 996 frames.** `excluded_sets()` called
   `base.excluded_sets()`, which `_bound()` had just rebound to `excluded_sets`
   itself. The lane test passed because it called the adapter from OUTSIDE the
   binding scope — *a test that exercises a wrapper outside the state the wrapper
   exists to create is not exercising the wrapper.* Fixed by capturing
   `_BASE_EXCLUDED_SETS` at import.
2. **Silent payload-path miss.** `_repoint_payload_paths` read `body["rows"]`;
   the enumerator emits `pairs`. The loop ran zero times, the per-path assertion
   never fired, and 300 pairs were written still pointing into V2R2's corpus
   while the tool reported success. **The test used the same wrong key as the
   code**, because it was written from my implementation rather than from the
   real artefact. Fixed the key, added a refusal when a non-empty universe
   repoints nothing (INC-V2-044), and re-anchored the test to the real output.
3. **Inherited stages ran against V2R1's defaults.** `STAGES` copied the base's
   bound methods, so `scorer` read V2R1's protocol and refused "rung 3 is already
   frozen". Masked while the earlier permanent import-time rebind was in place.
   Fixed by wrapping every inherited stage in `_bound()`.

### The crash

`test_the_scorer_refuses_while_the_chain_is_unfrozen` was written when nothing
was frozen. Once the chain froze it stopped being a refusal test: it called
`scorer.run()`, diffed all 300 pairs, and died at
`tools/identity_change_migration_closure_v2r3.py:244` with `KeyError: 'effective'`
while aggregating the census — the scorer summed key names the effective surface
does not report.

**No measurement receipt was written. No clause result, violation count, census
figure or verdict was printed or read.** The traceback carried only the missing
key name. `receipts/` holds the eight freeze/attestation receipts above and no
ninth.

Repaired: the census key names corrected against
`EffectiveSurface.as_dict()`, plus `_require_census_keys()` raising
`ClosureRefused` *before* any aggregation so the same shape mismatch can never
again surface as a bare `KeyError`. The dangerous test is replaced by
`test_no_test_in_this_suite_executes_the_closure` (an AST scan over every
`tests/test_*.py` for a call into the closure) and a synthetic-surface key check
that needs no corpus. 105 V2R3 tests pass; ruff clean.

### Why this is blocked and not merely fixed

The repaired file is pinned at rung 4. The gate correctly REFUSES:

```
a frozen scorer module has changed since rung 3:
  research/tavonel_eval_v2/tools/identity_change_migration_closure_v2r3.py
  frozen:  sha256:2b392c8fd63439493f620e1314ab7fc140ceda866d7c417b917bd50bb7fe138d
  current: sha256:f5b8de50019ef4efe6a83ddeb295178c35848f78c94daabef0669fe044eb1e0d
```

Two predeclared clauses point opposite ways.

`execution.what_counts_as_a_score`: *"A run that raises before grading — a
missing file, a crash, a refused precondition — is not a score, produces no
receipt, and is repaired and re-run. Declared here BEFORE execution so that the
distinction cannot be invented afterwards."* By this clause the event is not a
score and the corpus is not spent.

`freeze.no_post_freeze_change`: *"after rung 4 nothing in this file, in the
scorer modules, in the acceptance semantics or in the exclusion policy may
change. There is no amend path and no force flag. A change that is genuinely
necessary is a NEW protocol with a new id, a new freeze chain and a new
universe."* By this clause the repair path is closed.

The tension is real: a crash located *inside* a rung-4-pinned module makes
"repaired and re-run" unreachable without breaking rung 4.

**`supersede-scorer` is not the answer and was not used.** Its own contract says
*"The scorer CODE and the acceptance semantics are unchanged here — what moved is
the link to rung 3 — and the receipt records both so a reader can tell a
relinking from a semantics change."* Here the code *did* change. Using it would
write a receipt asserting something false about the very distinction it exists to
preserve.

### What the ruling has to decide

Nothing was decided here. The open questions are: whether the crash-before-grading
clause authorises re-sealing rung 4 for a repair that touches no invariant,
obligation, threshold, population or grading rule; or whether a new protocol id
with a new freeze chain is required; and, if so, whether the unmeasured 300-pair
corpus is spent — no outcome value was ever produced or observed from it.

---

## INC-V2-067 — V2R3R1 executed once. INVARIANT_6 MET over 300 pairs, non-vacuously. But the frozen pass rule requires eight invariants and the instrument grades one.

**Date:** 2026-08-26
**Status:** SCORED — corpus SPENT. Overall closure verdict BLOCKED on a founder ruling.
**Production code untouched. No spent tooling edited. docs/ip untouched. GPU 0.**

### The successor chain, built under the ruling of 2026-08-26

The parent V2R3 chain was adjudicated `ABORTED_PRE_RESULT_INSTRUMENT_CRASH`, its
rung 4 permanently non-resealable, and its unscored 300-pair corpus
`EXACT_CARRY_FORWARD_ELIGIBLE`. Two receipts were written before anything was
inherited:

| receipt | run_id |
|---|---|
| v2r3 non-disclosure (four legs) | `20260825T204825Z-9a9095df6202` |
| v2r3 chain-disposition | `20260825T204825Z-620d496e43b9` |

The non-disclosure attestation's load-bearing leg is an AST proof that `run()`,
`measure_extra_clauses()`, `_require_census_keys()` and `_sum_maps()` contain
zero output calls, and that every print in `main()` reading `body` or `six` is
lexically after `body = run()`. The KeyError escaped `run()`, so the assignment
never completed and the whole output block was unreachable. pytest is configured
`-ra --strict-config --strict-markers` — no `--showlocals`, no `-l` — so the
traceback could not have rendered `extra`, `pair_results` or any census value.

`IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1` was then derived from its parent by
twelve asserted targeted replacements, so every scientific block arrives
byte-identical. `tools/v2r3r1_semantics.py` proves the normalised scientific
projection IDENTICAL — every top-level block classified scientific or
administrative explicitly, an unclassified block refusing rather than being
absorbed. The projection caught two real attempts to move it: a new
`one_shot_authorisation` key (classified administrative, with the reason) and a
STRENGTHENED `smoke_tests` clause, which was reverted — *"preserve exactly" has
no exception for changes the author thinks are improvements.*

Final chain, after one re-seal:

| rung | run_id |
|---|---|
| 0 acquisition_frame | `20260825T211445Z-c30ab96cb45a` |
| 0a frame_attestation | `20260825T211445Z-b4c352f5ec5a` |
| 1 protocol | `20260825T211446Z-b932c264c89c` |
| 1a protocol_attestation | `20260825T211447Z-702db72e7d2b` |
| 3 universe | `20260825T211450Z-32a41ad55999` |
| 3a universe_attestation | `20260825T211450Z-8a413d28e215` |
| 4 scorer_acceptance | `20260825T212103Z-426c31cc4eed` (12 modules) |
| 5 exclusions | `20260825T212109Z-17a83906b1d2` (0 exclusions) |
| — measurement | `20260825T213041Z-f710e6b3d6f5` |

### Exact carry-forward

The carried input is the parent's CANDIDATE manifest, pinned by the digest its
frozen universe receipt recorded (`sha256:67ad8a11…`), not the parent's frozen
universe. Feeding the output back as input would ask rung 3 to verify recomputed
digests against themselves, which reports every side verified and proves nothing.

Rung 3 then re-ran its entire verification path — 1,200 payloads re-hashed from
disk, collisions re-detected, the exclusion policy re-applied — and produced
`universe_sha256 sha256:628f29617f43ab4113ad5ab172ddcafb635a0f98f01f432afc4531abb0bd0739`,
**byte-identical to the parent's**. A switched-off filter could never have shown
that; a filter that runs and lands in the same place proves its decisions are
unchanged. All eight declared deltas 0; composition git_docs 133 /
regulation_ecfr 104 / sec_edgar 63; spent intersections v2r1 0, v2r2 0.

### The re-seal, and why it was needed

Rungs 0/0a were frozen while the carry-forward comparison still matched the
candidate manifest to the frozen universe POSITIONALLY. The two are in different
orders by construction — the manifest is in acquisition order, rung 3 sorts by
`(lineage_id, before_version, after_version)` — so it reported 300 mismatches and
no missing lineages. Fixing it changed two files the frame attestation pins and
the attestation correctly went red.

**That is the parent chain's failure arriving one rung earlier, and the lesson is
the same: freezing before the code has settled buys nothing and costs a rung.**
The difference is where the boundary falls: `no_post_freeze_change` bites after
rung 4, and `reseal_pre_scorer_chain` refuses outright once rung 4 or 5 has
frozen or any measurement exists. It re-seals 0, 1 and 3 together with fresh
companions, because superseding rung 0 alone would leave 1 and 3 linked to the
receipt it replaced.

### The execution boundary

`run()` takes an `ExecutionAuthorisation` that only the CLI entry point can mint;
the mint refuses while a test runner is loaded; the check is the FIRST statement
in `run()`. The negative control patches `fz.workspace` to raise — an
AssertionError would mean the chain was already being touched — and the refusal
arrives instead. **The full suite was then run twice with the chain frozen:
2,175 passed, 4 skipped, and no measurement receipt appeared.** That is the exact
condition that killed the parent chain.

### The result

    pairs        : 300  {git_docs: 133, regulation_ecfr: 104, sec_edgar: 63}
    INVARIANT_6  : MET
      violations : 0
      observations: {a_b: 323, c: 353, d: 4363, e: 648}
    census       : effective {MATCHED 2500, NEW 416, REMOVED 799, UNRESOLVED 648}
                   matched_with_differing_raw_ids 6
                   quarantine_members 325
                   quarantine_overrides 1  (by resolver state: NEW 1, MATCHED 0)

Non-vacuous in the two ways that matter. `quarantine_overrides` NEW = 1 means
**row B — `resolver NEW ∩ quarantined`, the exact state whose contradictory
obligations made V2R2 an invalid instrument — was exercised, and it did not
violate.** `matched_with_differing_raw_ids` = 6 means the cohort contained
renamed correspondences, so this is not the pass V2R1's collapsed-layer defect
could also have produced.

### Why this is NOT reported as a closure PASS

The frozen `pass_rule` requires:

    pairs_resolved > 0
    all eight invariants MET
    no invariant UNPROVEN
    … plus the four chain links

The measurement receipt reports **one** invariant. `measure_pair` computes
per-pair violations for INVARIANT_1, 4, 5, 6 and 7, but the V2 scorer aggregates
only INVARIANT_6; 2, 3 and 8 are graded nowhere in this instrument. V2R1's and
V2R2's result receipts carry the same single invariant, so this is a property of
the V2 instrument, not of this run.

Under the frozen `vacuity_rule` — *"an exercising count of zero yields UNPROVEN,
and an UNPROVEN invariant can never contribute to a PASS"* — seven invariants are
UNPROVEN and the overall verdict cannot be PASS.

**This was found by reading the instrument against its own pass rule, not by
reading the outcome.** It is visible without any result and would have been
equally true had the run come back the other way.

### Standing facts

- The run GRADED and produced a receipt, so under `what_counts_as_a_score` it IS
  the one score. **The 300-pair corpus is SPENT.** No rescore is permitted.
- INVARIANT_6 MET, 0 violations, non-vacuous, is a real prospective result about
  the INC-V2-037 migration and the INC-V2-047 repair, on material disjoint from
  V1's universe, V2R1's 285, V2R2's 270, the 538 retrospective and the 14 SFI2.
- It is not the eight-invariant closure the frozen pass rule describes.
- SFI3 is NOT opened. GPU spend remains 0. docs/ip untouched. IP gate CLOSED.

---

## INC-V2-068 — systemic anti-blocker audit (Lane E), and the five prospective repairs it forced

**Date:** 2026-08-26
**Status:** ANTI_BLOCKER_AUDIT_PASS (0 blockers, 14 findings reported)
**Instrument:** `tools/anti_blocker_audit.py`, tested by `tests/test_anti_blocker_audit.py`

Every blocker this study has hit was found by hitting it. The audit scans the
fourteen founder-named defect classes over the modules the REMAINING serial
chain will execute — the SFI3 pipeline, the four-link gate, the GPU launcher —
and nothing else. A scan over every historical study would report hundreds of
true findings about work that is already spent and can no longer hurt anything.

Severities are `BLOCKER` (would stop or corrupt a chain that has not run),
`FINDING` (a real defect where it cannot currently reach a frozen result), and
`ACCEPTED` (the shape is present and a structural feature of the same module
removes its power — and that feature is CHECKED by the scanner, never asserted).

### What it found that was real, and what was repaired

1. **`score_sfi3` graded a set of endpoints nobody compared to the protocol.**
   The freezer counted `len(body["endpoints"])`. A count is not a
   correspondence: two lists of nine can disagree on every member. This is
   INC-V2-067 in its SFI3 form — a frozen pass rule the instrument cannot
   answer. Repaired by `score_sfi3.require_declared_endpoints()`, which refuses
   in BOTH directions (declared-but-not-graded, graded-but-not-declared) before
   the freeze receipt is even located.
2. **`score_sfi3` borrowed `MET`/`FAILED`/`SKIPPED` from the spent SFI1 study
   with nothing checking them.** Those exact strings are written into a frozen
   receipt. Repaired by `require_shared_verdict_vocabulary()`, which caught on
   its first run that the label is `SKIPPED_NEVER_EXERCISED`, not `SKIPPED`.
3. **The GPU preflight and launcher had no binding to each other's rules.** The
   preflight recorded no study or runtime declaration digest, so the launcher's
   only link to it was that a receipt existed. The gates could pass under one
   declaration and the spend happen under another, with every receipt reading
   clean — the V2R3 shape, in the one place where the cost is billed GPU time.
   Repaired by `gpu_successor_preflight.declaration_digests()` and
   `launch_gpu_successor._declaration_gate()`, with four red directions.
4. **`E9_gate_power` was spelled in both the rehearsal and the freezer that
   gates on it.** A rename would have left the freezer reading a key that no
   longer existed and treating the absence as "no power". Single-sourced.
5. **`sources_sfi3` spelled SFI2's E5 receipt key itself.** Now taken from
   `score_sfi2.REBUILD_BLOCKS` and checked against the receipt it is about to
   index, so a bare `KeyError` cannot hide which of the two moved.

### What it found that stands, unrepaired and reported

- `acquisition/sources_sfi3.py` builds a path through `receipts/latest/` and
  reads it at import time (classes 11 and 6). Lowered to FINDING, not dropped:
  the read resolves a `points_to` indirection to the immutable receipt, and the
  module publishes a `frame_digest`. Together those do not PREVENT the pointer
  moving — they make a move visible in the frozen frame's digest instead of
  silent. **The frame is not yet sealed, and changing its source path before the
  seal would be an acquisition-semantics change, which is not a tooling repair.**
- Ten class-4 findings: tests re-spelling endpoint ids rather than importing
  them. Real, and none of them can reach a frozen result.
- Two class-10 findings: `gpu_successor_preflight` and `preflight_sfi3_roots`
  expose cohort-touching entry points with no test-runner refusal.

### Defects in the audit itself, found by driving it red

The first run reported 18 blockers, of which four were the scanner's own:
a module docstring explaining why a mutable `latest` is refused was read as the
path; `if __name__ == "__main__"` bodies were treated as import-time work,
reporting every CLI entry point in the repository; `revision != "latest"` — the
guard AGAINST class 11 — was read as the class, which is INC-V2-036 in the
auditor rather than the audited; and SFI2's `E1` colliding by name with SFI3's
`E1` was reported as drift between two studies that never read each other.
**A scanner that reports PASS because its checks cannot fire converts "we did
not look" into "we looked and it was clean."** `tests/test_anti_blocker_audit.py`
drives all fourteen classes red on synthetic modules, and asserts the opposite
direction wherever a check could plausibly flag everything.

---

## INC-V2-069 — STEP 2 is blocked, and the blocker is INC-V2-067 on a spent corpus

**Date:** 2026-08-26
**Status:** BLOCKED — founder decision required
**Instrument:** `tools/freeze_sfi3_protocol.py --dry-run` (23 conditions)

After Lanes B–E completed and the repairs below landed, the SFI3 protocol freeze
gate has **exactly one** blocking condition left:

    FAIL   identity/change separation complete
           "the prospective migration closure is FAIL:
            INVARIANT_6_ambiguous_identity_stays_unresolved. A closure that does
            not close is not closed by the age of the receipts beside it"

Twenty-two of twenty-three PASS. The full suite the gate runs — six of its
conditions each run it in full — is green at 2,248 passed, 4 skipped.

### Two separate facts, and only one of them is a tooling defect

**1. The gate is bound to a superseded receipt (defect class 7).**
`CLOSURE_STEM = "identity-change-migration-closure"` globs
`identity-change-migration-closure--*.json`, which matches only the V1 closure of
2026-08-25T00:10:37Z. V2R1, V2R2 and V2R3R1 all write *different stems*, so none
of them is visible to this gate. It is reading a chain that three successors have
superseded.

**2. Repointing it would not produce a PASS, and repointing it is not mine to do.**
The V2R3R1 measurement receipt
(`identity-change-migration-closure-v2r3r1--20260825T213041Z-f710e6b3d6f5.json`)
carries no `overall` field at all. Its keys are `INVARIANT_6_…`,
`effective_census`, `unsettled_identities_total`, `pair_count`, `by_family`,
`authorisation`, `preconditions`, `provenance`, `universe_sha256`. The V2
instrument never renders an overall verdict, because — INC-V2-067 — its frozen
`pass_rule` requires all eight invariants MET and none UNPROVEN, and the
instrument grades one.

So the gate would read `None`, which is not `"PASS"`, and fail identically.

**Deciding which closure receipt is authoritative for this gate, after the
outcome is known, is a held-out-interpretation change.** The founder's operating
rule names "acceptance rule" and "held-out interpretation" as escalation
triggers, and an actual graded FAIL has occurred. Neither is repaired here.

**The 300-pair corpus is spent.** There is no rescore. Whatever the resolution
is, it cannot be "measure it again".

### What is NOT blocked

- The SFI3 execution pipeline is built and rehearsed end to end on development
  fixtures: clean-fixture PASS, injected-defect FAIL, 8 negative controls, no
  fresh SFI3 payload opened.
- The four-link gate is complete, and an independent validator re-derived all
  20,018 eligible records' four link digests against the frozen gate receipt and
  held.
- The GPU launcher is ready and structurally spend-locked: dry-run is the
  default, three preflight gates block, 0 GPU seconds and $0 spent.

### Repair landed in the same pass: the V2R3 sweep captured its own successor

`v2r3_chain_disposition._is_v2r3` matched `"v2r3" in name`, which was correct for
every artefact that existed when it was written and wrong the moment V2R3R1 ran.
The successor GRADED, so its receipt carries outcome keys by right; the substring
match reported that legitimate result as the predecessor's leaked one and turned
the suite red on two tests. Narrowed to a token boundary (`v2r3` not followed by
another alphanumeric), with `parent_protocol` deliberately dropped from the
evidence fields — every V2R3R1 receipt names V2R3 as its parent, and treating a
parent reference as membership captures the entire successor chain by design.
**The V2R3 non-disclosure proof was made and frozen before any V2R3R1 receipt
existed, so narrowing the attribution changes nothing about what was proven.**

---

## INC-V2-070 — V2R3R1 adjudicated INCOMPLETE_INSTRUMENT_COVERAGE; V2R4 opened

**Date:** 2026-08-26
**Founder ruling:** INC-V2-067 / INC-V2-069, 2026-08-26
**Status:** V2R4 under construction

### The scientific record for V2R3R1, preserved exactly

    RAW_I6_VERDICT                  MET
    OVERALL_CLOSURE_VERDICT         NOT_ESTABLISHED
    UNGRADED_INVARIANTS             7
    PRODUCTION_FAILURE_ESTABLISHED  false
    CORPUS_STATUS                   SPENT
    RESCORE_PERMITTED               false

    classification: INCOMPLETE_INSTRUMENT_COVERAGE
                  = OVERALL_CLOSURE_NOT_ESTABLISHED

300 prospective pairs. INVARIANT_6 MET, 0 violations, over clauses a/b = 0,
c = 0/353, d = 0/4363, e = 0/648. Non-vacuous power present:
`matched_with_differing_raw_ids = 6` and `quarantine_overrides = 1` (resolver
NEW = 1) — so the two exact states that invalidated the predecessor instruments
were exercised prospectively and both passed the corrected instrument:

    V2R1's defect: matched correspondence with differing raw ids
    V2R2's defect: resolver-local NEW under quarantine override

**This is valid prospective endpoint evidence and is not a production FAIL.**
It is not upgraded, not rescored, not discarded, and not combined with V1's
seven-of-eight into a synthetic PASS.

The defect is coverage, not result:

    frozen acceptance domain   = 8 invariants
    executable grading domain  = 1 invariant

The instrument could never have produced the PASS its own frozen rule required.

### What was built in response

**`tools/invariant_domain.py`** — ACCEPTANCE DOMAIN == EXECUTABLE GRADING DOMAIN,
as set equality on full identifiers across three sources: what the protocol
declares, what the scorer *actually emits*, and what the result schema requires.

The graded domain is obtained by EXECUTING the grading function on a null
population and reading the keys it emitted. This is the load-bearing choice. A
module can carry a tuple naming eight invariants and aggregate one — that is
precisely what happened — and any check reading the tuple would have agreed with
the protocol and reported clean.

`CANONICAL_INVARIANTS` verifies its own shape at import: eight distinct ids over
ordinals 1..8 exactly. An anchor nobody checks is a ninth place for the defect to
live.

All eight red controls the ruling names are in
`tests/test_invariant_domain.py`, and the decisive one runs the REAL V2R3R1
receipt through the gate and requires it to be refused. A gate that cannot catch
the defect it was written for is decoration.

**Anti-blocker audit defect class 15** now flags any active module declaring a
PASS-contributing set that nothing compares to what the instrument grades. It
immediately found `launch_gpu_successor.REQUIRED_ENDPOINTS`: the launcher checked
"is every name I know about MET", which is safe against a rename — an unknown
name reads `None` and refuses — and blind in the other direction. An endpoint the
study graded and FAILED, whose name was not in the tuple, would never have been
looked at and the spend would have proceeded past it. Repaired to a two-way
domain equality with four red directions.

**`tools/v2r4_grading.py`** — the join, not a rewrite. V1's `grade()` already
aggregates eight and already produces PASS/FAIL/UNPROVEN/VACUOUS_FAIL; V2R3R1 has
the corrected INVARIANT_6 and not the other seven. Neither is missing what the
other has. INVARIANT_6 is re-derived over five clauses — V1's (a),(b) plus V2R3's
(c),(d),(e) over one `EffectiveSurface` — with each clause's denominator reported
apart, and every other invariant's verdict is V1's untouched. The overall verdict
comes from `invariant_domain.overall_from`, so the pass rule has exactly one
implementation and the scorer applies it. No interpretation step after execution.

INVARIANT_8's exclusion set is checked as a DOMAIN for the same reason: a
universe proving seven of eight spent cohorts and reporting `holds: true` for
each is not disjoint from the eighth, it never looked. **Silence is not
disjointness.** The declared set adds the V2R3/V2R3R1 300, VBC1 burned material
and all SFI3 material to what V2R3 already excluded.

### Still open, and on the declared irreversible path

`gpu_successor_preflight.HELD_OUT_STUDY_STEM` is `"sfi2-native-provenance"`,
whose only held-out receipt reads `verdict: FAIL`. SFI3 is
`SOURCE_FACT_IR_HELDOUT_V3` and writes a different stem, so an SFI3 PASS would
not be visible to `G_GSP_HELD_OUT_PASS_PRESENT` and STEP 4 would remain blocked.
This is the same stale-binding class as `CLOSURE_STEM`. **Which study authorises
GPU spend is not a tooling question, so it is reported and not repaired.**

---

## INC-V2-071 — the GPU authorization route repaired end to end (2026-08-26)

**Status: IMPLEMENTED.** Not TESTED as a route — no fresh SFI3 material exists,
so nothing has run the green path on real evidence. What is tested is every
refusal.

The founder ruled that the GPU authorization source was already decided and that
the stale binding above was a tooling defect to repair prospectively, not a
policy question to re-ask. Both halves of INC-V2-069's class are now closed.

### `sfi2-native-provenance` is retired, and was NOT replaced by another stem

`held_out_pass_receipt()` searched `sfi2-native-provenance--*.json` for a body
declaring `split == "held_out"` and `verdict == "PASS"`. SFI2 is frozen, FAIL,
spent and permanently non-rescorable, so that search **could never succeed**. It
was not a gate that happened to be shut; it was a requirement that had no
satisfying state, and nothing in it could say so.

The obvious repair — point the stem at SFI3 — would have moved the defect rather
than closed it. `RETIRED_HELD_OUT_STUDY_STEM` is now `""` with its reason
recorded beside it, and the lookup is gone. SFI2's receipts, history and stem are
untouched: `tools/score_sfi2.py` still writes `sfi2-native-provenance` and
nothing downstream reads it as authorisation.

### Two acceptances, both mandatory, neither substituting for the other

`tools/sfi3_acceptance.py` (`SOURCE_FACT_IR_HELDOUT_ACCEPTANCE_V1`) answers *did
the fresh held-out study pass*. `tools/four_link_acceptance.py`
(`FOUR_LINK_ACCEPTANCE_V1`) answers *is the cohort about to run followable end to
end*. A study can pass over a cohort that is not the one about to run, so
`G_GSP_SFI3_ACCEPTANCE_PASS` and `G_GSP_FOUR_LINK_ACCEPTANCE_PASS` are separate
gates and both block.

Neither is resolved by search. Each is named by explicit path on the command
line and bound by SHA-256: **one authority, one immutable path, one digest.**
There is no default, no `latest`, no fallback and no bypass flag.

SFI3's acceptance rule is not "all endpoints MET". Nine are declared; E1–E7 and
E9 are the PASS-contributing primaries, and E8 is a mandatory safety veto whose
clean state is `VETO_CLEAR_NO_POSITIVE_CREDIT` — never `MET`, contributing no
positive evidence, failing the whole study if violated. Crediting its clean zero
would manufacture positive evidence from an instrument whose seam is structurally
closed and which could not have fired.

### The launcher revalidates; it no longer reinterprets

`launch_gpu_successor.REQUIRED_ENDPOINTS`, its `MET` constant and
`held_out_endpoints_gate` are deleted. **Two implementations of an acceptance
rule are two rules**, and the copy that is not the one the study was scored under
is the one that drifts. The launcher now re-runs each acceptance module against
the receipt it was handed, requires the digest to equal what the preflight gated
on, and requires the four-link acceptance to bind the manifest digest this launch
is about to run.

### Six bound inputs, not two

The preflight records the digest of everything a spend is decided by — study
declaration, runtime declaration, manifest, model pin, and both acceptances — and
the launcher re-reads all six from disk. Comparison is **set equality on the
declaration domain in both directions**: a preflight that recorded five of six
would otherwise pass the loop on the five it had, and the sixth would be bound by
nothing at all. That is INC-V2-067's defect pointed at money instead of a corpus.

### What the audit caught in the repair itself

Adding the four new acceptance modules to `anti_blocker_audit.ACTIVE_TOOLS`
turned it red on two shapes in code written the same day:

* class 13 — `MEASUREMENT_SCHEMA` restated `"tavonel.v2.sfi3_score.v1"` beside
  the scorer's own literal. Repaired by naming it once, in `score_sfi3` where the
  receipt is built, and importing it.
* class 15 — `sfi3_acceptance` declared `PRIMARY_ENDPOINTS` and re-derived
  `declared != graded` itself instead of calling
  `score_sfi3.require_declared_endpoints()`. Two implementations of a domain
  equality are two domains. Repaired by delegating.

Neither was found by reading the diff.

### One test in the repair was wrong in the way this study keeps finding

`test_red_11` first asserted `"VETO_CLEAR_NO_POSITIVE_CREDIT" not in source`. It
went red on the launcher's own comment block *explaining why no endpoint
arithmetic lives there* — the same blindness that made the first version of
`test_no_bypass_flag_or_env_var_exists` wrong. Rewritten to walk the AST, where a
comment is not a node, and mutation-controlled in both directions.

---

## INC-V2-072 — `IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4` derived (2026-08-26)

**Status: IMPLEMENTED (draft).** `protocols/IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4.yaml`
exists, parses, and its declared invariant set equals the executed grading domain
and the result schema's required keys. It is `DRAFT_NOT_FROZEN` and two of its
pinned modules do not exist yet, which is the correct order: rung 3 refuses until
they do.

Derived from V2R3R1 by **targeted replacement**, not transcription. The ruling is
that V2R4 is the same study on fresh material — same eight invariants, same
zero-tolerance semantics, same effective identity state machine, same independent
quarantine oracle, same ignored-facet policy, same pass rule, same vacuity rule,
same floors — so every line the successor relationship does not change is carried
byte for byte. A fresh transcription would have been a second protocol wearing
the same name.

What changed:

* **parentage** — V2R3R1 recorded as `INCOMPLETE_INSTRUMENT_COVERAGE`:
  `raw_i6_verdict: MET`, `overall_closure_verdict: NOT_ESTABLISHED`,
  `ungraded_invariants: 7`, `production_failure_established: false`,
  `corpus_status: SPENT`, `rescore_permitted: false`. Its I6 endpoint is
  preserved as valid prospective evidence and is not read into this closure —
  not as a prior, not as a denominator, not as partial credit.
* **`carry_forward` deleted** — V2R3R1 inherited an *unscored* frozen universe,
  which was legitimate because no outcome had been observed. Those 300 pairs have
  now been scored and their I6 outcome read. Material whose outcome has been
  observed can never again be prospective, whatever the instrument failed to
  grade alongside it.
* **INVARIANT_8 widened to eight populations**, compared by set equality against
  what the universe actually proves, in both directions. Silence is not
  disjointness.
* **a fourth attestation rung** binding the declared/graded/receipt equality,
  with the graded set obtained by *executing* the grading function on a null
  population. A module can carry a tuple naming eight and aggregate one; V2R3R1's
  did, and a check that read the tuple would have agreed with the protocol.
* **the pass rule now names the receipt shape** — `overall`, `pairs_resolved`,
  and a block per invariant. There is no separate interpretation step after
  execution.

Every freeze stem is this chain's own. Downstream, the SFI3 gate binds this
study through `MIGRATION_CLOSURE_ACCEPTANCE_V1` by path and digest, never by stem
glob — the repair for INC-V2-069.

### Next, in order

1. `tools/freeze_migration_closure_v2r4.py` and `tools/v2r4_attestation.py`.
2. The pre-freeze rehearsal: every one of the eight invariants driven red
   independently, then the whole synthetic/spent-development closure driven
   green. A scorer that has not demonstrated both directions for all eight may
   not be frozen. **No fresh V2R4 material is used for this.**
3. Fresh cohort ≥200 pairs across ≥3 families, all eight spent populations
   excluded. If fresh material is insufficient: STOP `INSUFFICIENT_COHORT`.

### V2R4 cohort feasibility — a first reading, not a declaration

Recorded here because §9's `INSUFFICIENT_COHORT` stop is a real possible outcome
and the answer should be written down before a frame is built around it, not
after. **This is a capacity reading from declarations already on disk. It is not
an acquisition frame and it declares nothing.**

What V2R3R1's frozen universe spent (300 pairs): 133 git, 104 eCFR across 37
distinct parts, 63 SEC across CIKs 21535–33213.

What is already declared across all 14 source modules: 960 canonical root
identities — 309 eCFR, 308 git, 324 Wikipedia, 19 SEC.

Headroom, by family:

* **sec_edgar** — ample. The declared universe carries 7,998 distinct CIKs and
  V2R3R1 consumed a window ending at 33213. `start_after_cik` moves to 33213 by
  the same construction V2R3 used against V2R2, which makes the family
  container-disjoint from every predecessor rather than relying on lineage-level
  exclusion alone.
* **regulation_ecfr** — ample in principle; 309 parts are declared against a
  corpus of thousands, but fresh parts must be declared and probed rather than
  assumed.
* **git_docs** — supply is not the constraint; 308 repositories are already
  declared and each new root needs its revision behaviour probed before it can be
  declared honestly.
* **encyclopedia_wikipedia** — still excluded, for V2R3's reason unchanged: it is
  an SFI3 root family, metadata-only disjointness from SFI3 roots is not reliably
  provable for it, and expanding an SFI3 category to make it provable would spend
  another study's prospective confirmatory material to buy a disjointness
  argument here.

So the floor is not obviously unreachable, and it is **not yet reachable
either** — nothing has been probed. The frame will declare containers and probe
their capacity BEFORE rung 0 seals, which is the only order in which a quota can
be honest. If the probe comes back short: STOP `INSUFFICIENT_COHORT`. The floor
does not move, families are not redistributed into, and no family is topped up
from a more productive one.

---

## INC-V2-073 — V2R4 depended on an artifact that must not exist yet

**Class:** circular gate. **Direction:** prospective — repaired before any V2R4
acquisition artifact, freeze receipt or measurement receipt existed.

`INVARIANT_8` listed `from_sfi3_material` among its required disjointness
populations, and `v2r4_grading.REQUIRED_DISJOINTNESS` graded it. SFI3's cohort
does not exist. It must not exist until V2R4 passes, because SFI3's freeze gate
is downstream of `MIGRATION_CLOSURE_ACCEPTANCE_V1`. So V2R4 waited for SFI3's
acquisition while SFI3 waited for V2R4's PASS, and the only ways out of that
loop were both forbidden: open SFI3 material early to satisfy V2R4, or let
INVARIANT_8 pass vacuously over a population that is empty because it cannot yet
be non-empty. The second is the shape INC-V2-036 names — a guard placed where
its failure is impossible.

**What was wrong is not the requirement, it is where it was enforced.** SFI3
separation is real and stays. It moved from a COHORT COMPARISON, which is
undecidable now, to a CONTAINER RESERVATION, which is decidable now:
`SFI3_ROOT_RESERVATION_V1` (`tools/sfi3_root_reservation.py`), built from source
and root IDENTITY METADATA ONLY. It opens no revision, counts no qualifying
pair, and reads no change outcome. It pins the SFI3 protocol id, the sha256 of
`acquisition/sources_sfi3.py`, the exact git / eCFR / SEC / Wikipedia root
identities, and the predeclared legal replacement pool for any SFI3 root that
later fails availability — so a replacement cannot widen the reservation after
the fact. Both studies bind it by path and sha256 at rung 0.

Three families are decidable on identity alone. `encyclopedia_wikipedia` is not:
membership is by category, and category expansion is not visible from a root
list. It is therefore declared UNDECIDABLE and **fails closed** — V2R4 excludes
the family rather than assuming disjointness, and no SFI3 category is opened to
buy a V2R4 argument.

The reverse direction is proved before SFI3 acquires, not after: SFI3's freeze
condition 21 resolves the reservation through V2R4's frame attestation binding,
never a stem glob (INC-V2-069), and checks V2R4's declared containers against
the reserved roots. It currently fails closed — no V2R4 frame attestation
exists yet — which is the correct answer today.

**One defect was found inside this repair, by a test written for it.** The gate
first called `require_within_reservation(reservation=stored, families=declared_roots())`,
which can never refuse: `verify()` compares the stored digest against a build
over exactly those roots and fires first. That is INC-V2-036 again, inside the
fix for a different defect. The CODE was changed, not the test.

## INC-V2-074 — "SCIENTIFIC PROJECTION IDENTICAL" was false

**Class:** a declaration that claimed more than the checker could prove.
**Direction:** prospective.

V2R4's fourth attestation rung claimed the V2R3R1 → V2R4 scientific projection
is IDENTICAL, and bound `tools/v2r3r1_semantics.py` to prove it. Running that
checker on the pair refuses, and the first difference it reports is
`/cohort/floor_is_not_lowered` — a field V2R4 added *precisely to say the floor
did not move*.

The old checker was right and was not weakened. It was built for V2R3 → V2R3R1,
where the SAME UNSCORED 300 pairs crossed the boundary; under exact
carry-forward, any difference means the successor is not asking the parent's
question about the parent's material, so exact equality was both true and
required. V2R4 has a fresh protocol id, a fresh cohort, no carry-forward,
full-eight executable grading and new spent populations to exclude. Exact
equality is neither true nor required here. `v2r3r1_semantics.py` is PRESERVED
UNTOUCHED — it is the historical evidence for the carry-forward decision, and
editing it to make this transition pass would have destroyed what it was built
to detect while making a false claim true by fiat.

`tools/v2r4_semantics_delta.py` / `V2R4_ALLOWED_DELTA_V1` proves the weaker true
statement: **SCIENTIFIC_CORE_PRESERVED_WITH_PREDECLARED_HYGIENE_DELTAS.** 39
core paths byte-identical; every remaining difference at a path covered by one
of nine predeclared hygiene categories; no wildcard may reach the core; and a
declaration covering no actual difference is REFUSED as dead permission, because
dead permission is what a later unreviewed edit slips through. Live result: 216
accepted deltas, each listed with its path, its category and the declaration
that licenses it — a machine-readable list, never a count.

**The checker corrected the protocol twice while being built.** Refusing seven
dead declarations is what established that `status`, `split`, `predecessor`,
`background` and `release` do not move at all, and that `authorised_by` was
genuinely stale — it named the ruling that opened V2R3. The delta enumeration
also surfaced a stray quote in a `pass_rule` clause and a stale phrase reading
"the eight required disjointness proofs" where there are now seven.

The pass rule lost nothing: every V2R3R1 clause survives, three were added, and
one was RENAMED one-for-one — "all eight invariants MET" became "every declared
invariant's verdict is MET", which is strictly stronger, since a count of eight
is satisfied by eight wrong names and a declared set is not. A rename that did
not actually happen is refused, in both directions.

Seventeen red controls drive the contract red independently, plus a green
control asserting the exact intended transition and its delta list. `protocol_delta`
and `companion_attestations` were rewritten to match what the checker permits —
no prose claims fewer deltas than the contract allows.

**Neither incident is a V2R4 failure and neither opened a V2R5.** No immutable
scientific boundary had been crossed: V2R4 acquisition artifacts NONE, freeze
receipts NONE, measurement receipts NONE, fresh corpus spent NO. Both were
ordinary pre-freeze contract defects, fixed in V2R4.

## INC-V2-075 — a frozen chain pinned a test file a successor forced to change

**Class:** live recomputation of a frozen fact. **Direction:** prospective; no
measurement, receipt or scientific artifact was altered.

`tests/test_v2r3_contract_consistency.py` asserted that V2R3's
`root_normalisation.realised_at_declaration` block equals a root screen computed
against the LIVE tree. Those numbers are, by the block's own name, facts about
the moment V2R3 declared. Adding `acquisition/sources_v2r4.py` put 86 new
identities in front of `root_identity`'s glob and turned 875 into 961 — without
a single V2R3 number changing, and without any V2R3 root ceasing to be disjoint.

The assertion was split rather than relaxed. Declaration-time counts are now
re-derived over the modules that existed THEN (`sources_v2r3` plus its
successors excluded), which reproduces V2R3's frozen 875 / 12 modules /
per-family figures exactly. DISJOINTNESS stayed LIVE, against every frame that
exists today including successors — strictly stronger than the assertion it
replaced, because a successor that declared one of V2R3's roots now turns it red
where the old frozen-count comparison would not have noticed.

**There was no way to leave the file untouched.** Making the old assertion true
again would have required V2R4's roots to be invisible to `root_identity`, and
that reader is the one control standing between a future study and a spent
container — the control whose absence let 7 CFR 273, SFI1-spent and named by
VBC1, into the V2R2 frame. `tools/root_identity.py` is itself pinned by V2R3's
frame attestation, so the fix could not go there either.

**The cost, stated plainly.** V2R3R1's protocol attestation pinned that test
file by sha256 at freeze time, so `v2r3r1_attestation.verify_protocol` now
refuses with "attests files that have since changed". That refusal is the pin
WORKING: the tree it was proved about did move. Seven of the eight pinned files
— both protocols, the state table, the effective-identity module, the quarantine
oracle, the semantics checker and the compat document — still hash to exactly
what V2R3R1 sealed, and `test_every_scientific_pin_v2r3r1_froze_still_holds`
walks them one by one so a SECOND file moving is a new red rather than being
absorbed into an expected one. `test_the_protocol_rung_refuses_and_names_the_file_that_moved`
asserts the refusal names the consistency suite and does NOT name any scientific
artifact.

**No frozen receipt was rewritten, superseded or re-sealed**, and V2R3R1's rung 1
was not re-run. The chain's evidence is intact; what changed is a tooling file it
happened to pin, and this entry is the record of which one and why.

## INC-V2-076 — the capacity probe read page 1 and reported it as the whole

**Class:** silent truncation in a measurement the frame would have declared as
fact. **Direction:** prospective — caught before rung 0 sealed, before any
acquisition, and before the pre-acquisition gate receipt was written.

`tools/probe_v2r4_roots.py` scanned all fifty CFR titles through the eCFR
versions endpoint and counted, per PART, how many sections carry two or more
distinct dated versions. It read the response and stopped. **That endpoint pages
at 1,000 rows** and reports the truth in `meta.total_pages`: title 2 alone
carries 3,350 rows across 4 pages. The probe was reading between a quarter and
all of each title, depending on the title's size.

**The direction of the error is understatement, and that is not why it matters.**
Under-reported supply is conservative for a quota. What it corrupts is the
SELECTION: the rule ranks parts by multi-version-section count and takes the top
two per title, so ranking on partial data means ranking by *supply visible on
page 1*. Title 2 part 180 read as 20 multi-version sections when it has 117, and
parts with real supply were invisible entirely — the first scan found 57
declarable parts across 25 titles where title 7 alone has 73.

The rule itself was not changed and was still fixed before the scan ran, so
selection stayed blind to outcomes throughout. What changed is that it now sees
the whole population it was always meant to rank.

**How it surfaced.** Verifying that a hyphenated part number (41 CFR 102-117)
would survive URL construction in the acquisition fetcher. The per-PART query
returned 117 multi-version sections for 2-180 against the title-wide scan's 20,
and a discrepancy that large in a number the frame was about to declare as
"probed" is not something to note and move past.

**The repair.** `title_versions` follows `meta.total_pages` to the last page and
REFUSES a response whose meta declares more rows than were read — a partial
supply reading that reports itself as complete is exactly the defect, so the
repaired function cannot commit it silently. All fifty titles were re-scanned in
full and the selection re-derived under the unchanged rule.

**A second truncation, found by the same question and handled differently.** The
acquisition fetcher queries `versions/title-N.json?part=P` and does not follow
pagination either. That base is V2R2 tooling — spent-run evidence that must not
be edited — so the control went into the FRAME instead: every declared part was
queried at exactly the URL the fetcher will use, and any part reporting more than
one page is excluded by name. A part the fetcher can only half-read would have
its traversal restricted to whatever page 1 held: deterministic, but not the
traversal the frame declares, and a frame that describes a traversal the
acquisition does not perform describes nothing.

**Nothing was spent.** No V2R4 acquisition artifact, freeze receipt or
measurement existed, the pre-acquisition gate receipt had not been written, and
the gate run that was in flight was stopped rather than allowed to seal a READY
verdict over a frame that was about to change.

## INC-V2-077 — the sealed disjointness proof named the two oldest cohorts and was silent on the nearest

**Class:** delegation to a parent whose scope is narrower than the caller's.
**Direction:** prospective — caught before rung 4, before the exclusion freeze,
before the gate, before any V2R4 measurement. **Second instance:** the same
class as the `prove_root_disjointness` defect caught earlier the same day, in
the same module, by the same reading.

`v2r4_attestation.prove_spent_disjointness` was written as a one-line delegation:

    def prove_spent_disjointness(ws):
        return att.prove_spent_disjointness(ws)

V2R3's version iterates V2R3's `SPENT_UNIVERSE_STEMS`, which names `v2r1` and
`v2r2` — the only spent cohorts that existed when it was written. Rung 3's
companion attestation therefore sealed a receipt reporting
`intersections: {v2r1: 0, v2r2: 0}` under a rung whose stated purpose is
disjointness from **every** spent cohort.

**What it was silent about is the part that matters.** V2R3's 300 lineages were
carried forward unscored into V2R3R1 and MEASURED there. They are spent, they
are the most recently drawn material in the programme, and they are drawn from
the families V2R4 draws from — the cohort most likely to overlap is precisely the
one the sealed proof never looked at.

**Nothing was contaminated.** Recomputed against all four cohorts the
intersection is empty: v2r1 285 / 0, v2r2 270 / 0, v2r3 300 / 0, v2r3r1 300 / 0
against 223 frozen pairs. The enumerator's subtraction worked. But a proof is not
made complete by being lucky, and the sealed sentence claimed a completeness it
had not checked. **Silence is not disjointness.**

**Why delegation keeps producing this.** A delegated proof returns a TRUE
statement about a NARROWER question, under a rung that claims to have answered
the whole one. It cannot fail loudly, because nothing it asserts is false. Both
instances today were found by reading the returned dictionary and asking what was
missing from it, not by any check — and no check existed that could have caught
either, because a proof that reports `holds` over the sets it happened to check
is indistinguishable from a complete one at the type level.

**The repair.** V2R4 owns its own `SPENT_UNIVERSE_STEMS` naming all four cohorts
with their expected sizes, and its own proof, parameterised the way
`prove_root_disjointness` already was. `verify_universe` now compares the attested
and computed cohort sets as SET EQUALITY and refuses a mismatch with a sentence —
where a `zip(..., strict=True)` raised a bare `ValueError` and a non-strict zip
would have compared the two cohorts they share and reported agreement.

The sealed receipt is superseded through
`freeze_migration_closure_v2r4.py supersede-universe-attestation`, guarded like
the base `supersede_*` family: refused once any V2R4 outcome has been read, so a
proof cannot be widened after a result that could have steered it. The prior
receipt is preserved and named, with what it proved and what it omitted.

**A third instance of the same class, in the guard on the repair itself.** The
first draft of that supersede called `base._nothing_has_been_scored(ws)`, which
reads the module global `base.MEASUREMENT_GLOB`. The V2R2 adapter rebinds that
global PERMANENTLY at import, so which study's outcomes the guard looked for
depended on import order. It now derives the glob from this protocol's own
`measurement` stem. **A gate that can be aimed at another cohort's receipts by
import order is not a gate.**

## INC-V2-078 — rung 3 is not idempotent, and re-running it orphaned its own attestation

**Class:** an inherited rung whose contract the wrapper asserted rather than
checked. **Direction:** prospective — no measurement existed, no outcome was
read, and the two receipts are content-identical.

`_companion` in the V2R4 freezer carries this docstring: *"A base rung is
idempotent — it returns ALREADY_FROZEN rather than writing a second receipt — so
its companion has to be too."* That is true of `freeze_acquisition_frame` and
`freeze_protocol`. It is **false of `base.freeze_universe`**, which rebuilds the
universe and calls `write_receipt` unconditionally, with no existence check.

Re-running rung 3 to confirm the repair above therefore wrote a SECOND universe
receipt. Both carry `universe_sha256 2ff5ade2…` and 223 pairs — identical
content, new run id. `latest_receipt` sorts by name, so the newer one silently
became the rung in force, and the companion attestation just superseded was left
binding a receipt that no longer was. The chain broke by being run again, not by
anything changing.

**It failed loudly, which is the only reason this is a paragraph and not a
finding.** `_verify_base_binding` refused: *"An attestation of a superseded rung
does not attest the run that would execute."* The binding check earned itself.

**Two repairs, both prospective.** The V2R4 wrapper now returns `ALREADY_FROZEN`
when a universe receipt exists, naming the receipt, the pair count and the digest,
and pointing at `supersede-universe` for a universe that genuinely has to change.
The guard is in the wrapper and not in the base: the base is spent-run evidence
for three closed studies and is not edited.

`supersede_universe_attestation`'s no-op guard was widened to the same
distinction the base `supersede_universe` already draws — a no-op means BOTH the
proof and the chain link are already right. An attestation can be complete in
what it proves and still bind a receipt that is no longer authoritative, and
refusing to re-seal that would be refusing to repair a broken chain because the
proof had not moved. Its `why` field is now assembled from what actually moved:
the first draft hardcoded the delegation story, and the second supersede was a
rebind, so that prose would have sealed a receipt whose stated reason was false.
**A `why` that does not depend on what changed is not a reason, it is a label.**

**Both universe receipts are preserved.** Neither is deleted. The superseding
attestation names which one it binds and which one it replaced.

## INC-V2-079 — four controls asserted a moment, and went red when the chain moved past it

**Class:** a control written against a state rather than a mechanism. **Direction:**
prospective — found by running the suite after a repair, before rung 4.
**Related:** INC-V2-036 (a guard placed where its failure is impossible is not a
guard) and INC-V2-044 (a check that can only return one answer is not a
measurement). This is the mirror of both: a check that could only return one
answer *for a while*.

Four tests in `tests/test_v2r4_frame.py` asserted, in effect, "nothing has been
frozen or acquired yet":

- `test_the_fetcher_refuses_without_a_rung_zero_receipt` — called
  `require_frozen_frame()` against the live receipts directory and expected a
  refusal, which held only until rung 0 sealed.
- `test_nothing_has_been_measured_yet` — asserted `_nothing_has_been_measured`
  returns clean, which is FALSE by design once the corpus exists.
- `test_the_protocol_is_bound_by_digest_and_not_merely_named` — expected the
  binding to refuse with "rung 1 is missing", and its own docstring said so:
  *"Rung 1 has not frozen, so the binding REFUSES -- which is the correct answer
  today."* The word `today` was the defect, written down at the time.
- `test_the_gate_refuses_before_the_protocol_is_frozen` — matched on "rung 1 is
  missing" and, once rung 1 froze, started matching rung 3's message instead. It
  passed for one reason and then failed for another, **both of them correct
  behaviour**.

**Nothing was broken.** §H froze rungs 0, 1 and 3 and acquired 223 pairs exactly
as the ruling directs. The tests went red because the world advanced.

**Why that is worse than not existing.** A control that expires costs a real
investigation at the moment it goes red — four failures in a suite run to confirm
an unrelated repair, each of which had to be read before it could be dismissed —
and it teaches the reader that red in this file is routine. The third one is the
sharpest case: it was checking that a digest is compared rather than a filename,
and the only thing it actually exercised was the *absence* of the receipt. It
never once reached the comparison it was named for.

**The repair.** Each is driven by an EMPTY RECEIPTS DIRECTORY (`_bare`) rather
than by the calendar, so the refusal is caused by the absence the guard exists to
catch and stays true at every point in the chain's life. Where the live chain now
has a definite answer, that answer is asserted TOO, in both directions:
`_nothing_has_been_measured` must be clean on an untouched chain and CLOSED on
this one, naming both blockers — a guard that answered the same way before and
after acquisition would not be a guard. The digest binding now asserts the
positive path (`protocol_sha256` equals the file's hash) and gains the red control
it never had: same filename, different bytes.

`require_frozen_frame` gained an optional `receipts` argument for exactly this
reason. A refusal path that cannot be driven is a refusal path that is tested
only while the world happens to be in the state that triggers it.

**The condition the founder ruling actually binds is narrower and still holds:**
no V2R4 MEASUREMENT receipt exists. That is now its own test, separate from the
stronger pre-acquisition guard it had been conflated with.

## INC-V2-080 — INVARIANT_8's seven declared populations were proved, but not where the scorer looks

**Class:** a declared domain and its proof source living in different layers.
**Direction:** prospective — caught while wiring the traversal, before the one
authorised execution, with the cohort untouched. **The check that caught it is
the one written for INC-V2-067's shape**, `require_disjointness_domain`, doing
exactly its job.

`v2r4_grading.disjointness_from` maps a universe receipt's `disjointness` block
onto V1's grading input, and it assumes that block is keyed by
`REQUIRED_DISJOINTNESS` — the seven populations V2R4 declares. On this chain the
assumption is false:

- The universe rung is frozen by V1's `build_universe`, which computes **three**
  proofs under V1's own names: `from_the_538_pair_retrospective_cohort`,
  `from_the_14_confirmed_sfi2_lineages`, `from_the_v1_frozen_universe`.
- The **enumerator** proves **twelve**, under its own ids, and writes them to the
  candidates artifact.

So `disjointness_from(universe["disjointness"])` refuses: six declared
populations never proved, three proved but not declared. **Every one of the seven
IS actually proved** — v2r1, v2r2, the v2r3/v2r3r1 300 and the VBC1 burn are all
established by the enumerator, and the rung-3a attestation independently
recomputes four of them. Nothing was unchecked. What was wrong is that the scorer
would have looked for them in the one place that does not carry them.

**Where it would have failed matters more than that it would have.** The call
sits after the traversal in the natural writing order, so the refusal would have
landed after 223 pairs had been read and diffed — the same shape as the V2R1
chain's crash in census aggregation after 300 pairs, where no outcome escaped
only because of where the exception happened to land.

**The repair.** The mapping from declared population to proving evidence is made
EXPLICIT in the traversal, as a declared `PROOF_SOURCES` table, and
`require_disjointness_domain` still decides — set equality on full identifiers,
never a count. What moved is where the seven proofs are read from, not whether
all seven must be present. Four properties keep that from being a loophole:

1. **The source is pinned, not a side channel.** The candidates artifact is
   re-hashed against `manifest.sha256` in the frozen universe receipt before a
   single proof is read. Reading a proof out of an unpinned file to satisfy a
   frozen rung is the false-provenance seam this study keeps recording.
2. **The universe's own three must still agree.** Two independent computations of
   the same disjointness, both required. Replacing the universe's proofs with the
   enumerator's would have removed a check while appearing to repair one.
3. **A weak proof does not establish a population on its own.**
   `retrospective_538` carries 14 comparable ids and says in its own `coverage`
   field that full coverage comes from `sfi1_spent` and `sfi2_spent`. The declared
   population is bound to all three and needs all three, or the domain check would
   have been satisfied with a fraction of the cohort actually compared.
4. **Unconsumed proofs are named, not dropped.** Three enumerator proofs bind to
   no declared population. A new one appearing, or a declared one vanishing,
   refuses: a proof nobody bound to a population is a population nobody declared,
   and a vanished one is a proof somebody stopped computing.

The assembly now runs BEFORE the traversal. It costs nothing and refuses on a
domain mismatch while the cohort is still unread.

**A gap this leaves, stated rather than smoothed over.** Rung 4 pinned fourteen
scorer modules and the traversal is not among them, because it did not exist when
rung 4 froze. Every GRADING module it calls is pinned; what is not is the
traversal itself and the `PROOF_SOURCES` mapping. Mitigations that do apply: the
mapping is recorded inline in the measurement receipt, the artifact it reads is
digest-pinned by rung 3, and `write_immutable` stamps the traversal's own sha256
into the receipt's provenance. Re-sealing rung 4 to include it is not available —
`supersede_scorer` would invalidate rung 5's `scorer_freeze_run_id` and there is
no `supersede_exclusions`. **This is a real weakness in the chain and is recorded
as one.**

## INC-V2-081 — a control grepped for a flag and matched the sentence promising it does not exist

**Class:** a source-text assertion matching its own documentation. **Direction:**
prospective — caught by the control going red on first run, in the same commit
that introduced it. Small, and recorded because the shape is not.

`test_there_is_no_limit_or_sample_flag` read the traversal's source and asserted
`"--limit" not in source`. It went red immediately: the module's docstring
contains the sentence *"THERE IS NO `--limit`"*, explaining why the flag does not
exist.

**Both of its failure directions are wrong.** It fails on prose that promises the
property it checks for, and it would pass if that prose were deleted — so the
strongest version of the file scores worst and the least documented scores best.
It never inspected the parser at all.

Repaired by asking the ARGUMENT PARSER what it declares, through the real
`--help` path, and asserting both directions: no `--limit`, `--sample`,
`--preview`, `--force`, `--dry-run` or `--rescore`, and `--execute` present — so
a probe that silently caught nothing fails rather than passing empty.

**INC-V2-079 — update, 2026-08-26: a fourth instance, inside the repair itself.**
`test_the_gate_names_the_first_unfrozen_rung_on_the_live_chain` was written as
part of the repair above and asserted the gate refuses with `rung 3 is missing`.
That was true when it was written and false twenty minutes later, when rung 4
sealed. The repair for "controls that pin a moment" pinned a moment.

The lesson is sharper than the original: **naming a specific unfrozen rung on a
chain still being built pins a moment however carefully the name is chosen.** The
only live-chain assertion that does not expire is the one about the chain's FINAL
state — every rung sealed, gate READY, four companions present. The "names the
first unfrozen rung" property belongs at the bare workspace, where the answer
cannot move.

## INC-V2-082 — the traversal called the pinned grader with the parent's signature

**Class:** an adapter re-deriving a composition its pinned dependency already
owns. **Direction:** prospective — raised `TypeError` on pair 0 of the one
authorised execution. **No outcome was read, no receipt was written, the corpus
is unspent.**

`v2r4_grading.measure_pair` composes V1's measurement with V2R3's (c),(d),(e)
clauses and returns the two populations SEPARATELY, so `grade` can check they line
up row for row rather than assuming it. Rung 4 pinned that module by digest.

The V2R4 traversal called it with V2R3R1's argument list — without
`declared_record` and `level` — and then called `parent.measure_extra_clauses`
beside it, re-deriving the same composition by hand.

**It failed safely, and that is luck rather than design.** The mismatch happened
to be in the ARITY, so Python refused at the first call, before a single pair was
diffed. Had the parent's signature been a superset rather than a subset, the run
would have completed: every one of the 223 pairs diffed TWICE — once inside the
pinned grader, once beside it — and the composition rung 4 sealed silently
re-derived in a module rung 4 does not pin. That result would have looked
complete. The double cost would have shown only in the wall clock.

**This is the same shape as the delegation defects of INC-V2-077 and the
root-disjointness one before it**, pointed the other way: not calling a
dependency that knows less than you, but reimplementing beside one that knows
more.

**The repair.** One call, both halves unpacked from its return. And a control
bound to `inspect.signature(grading.measure_pair)` rather than to a remembered
argument list, plus one asserting `parent.measure_extra_clauses` does not appear
in the traversal at all — so a drift in either module is a red test rather than a
`TypeError` during the one execution the protocol allows.

**What let it through.** The gate's `v2r4_full_eight_rehearsal` exercises the
GRADER on synthetic pairs; it cannot exercise the traversal, which did not exist
when the gate sealed. A rehearsal that covers the instrument but not the code
that feeds it leaves exactly this gap, and the gap is where this landed.

## INC-V2-083 — the acceptance compared two absent digests and called it agreement

**Class:** a check whose failure was impossible for the case it most needed to
catch. **Direction:** prospective — surfaced while sealing
`MIGRATION_CLOSURE_ACCEPTANCE_V1` for the V2R4 PASS, before SFI3 was opened.
**Sibling of INC-V2-036**, arriving from a different direction.

`migration_closure_acceptance.verify` enforces that the acceptance and the
measurement agree on the chain digests:

    for field in ("protocol_sha256", "universe_sha256"):
        if body.get(field) != acceptance[field]:
            raise AcceptanceRefused(...)

Both sides use `.get`. For a measurement receipt that records neither digest,
both sides are `None`, `None != None` is false, and the clause PASSES — an
acceptance binding a chain digest that does not exist, checked against a
measurement that never carried one. The clause a reader would point to as
"the digests are verified" is precisely the clause that cannot fail there.

**How it surfaced, and it was not by that hole.** V2R4's traversal embeds the
gate result whole under `preconditions`, so its protocol digest is nested rather
than top-level; V1's scorer put it at the top. `build` read only the top level and
refused: *"the acceptance records no protocol_sha256."* Chasing that refusal is
what exposed the vacuous comparison one function away.

**Two shapes, one digest, and which is not a clause of the contract.** The
protocol digest in `preconditions` is the SAME digest, from the same gate, that
V1 wrote at the top level. Which key a scorer happened to record it under is
plumbing. What the contract requires — that the acceptance bind it and that it
still match disk — is unchanged and still enforced by re-hashing.

**The repair.** One reader, `measurement_digest(body, field)`, used by both
`build` and `verify`. It looks top-level, then under `preconditions`, and
**refuses rather than returning `None`**. That is the whole point of it being a
function: the absent case now raises instead of comparing two nothings.

**A second gap, found in the same minute.** `build` returned a verified draft and
nothing sealed it. `latest_acceptance` globs the receipts directory and
`freeze_sfi3_protocol` takes an explicit acceptance PATH, so neither could ever
find one. An acceptance existing only in console output is the false-provenance
seam the companion attestations exist to close, one layer up. `seal()` now writes
it immutably, verifies the assembled draft again before writing, and refuses a
second acceptance for the same closure — a second would let a later reader choose
which one to bind.

## INC-V2-084 — predecessor-successor handoff schema mismatch

**Class:** administrative cross-stage binding failure. **Scientific scope:**
NONE. **V2R4 disposition:** PASS and CLOSED; the historical V2R4 frame
attestation and measurement remain authoritative and byte-for-byte unchanged.
**SFI3 disposition:** unopened and blocked before protocol freeze.

The SFI3 freeze gate claimed that it resolved the reservation through V2R4's
historical frame attestation, but the gate expected two fields that attestation
never carried: `sfi3_root_reservation` and `declared_containers`. Its tests built
that later, imagined shape instead of exercising the actual immutable artifact.
The scientific result is not defective; the successor handoff adapter is.

The repair is additive. A separate immutable
`V2R4_SFI3_RESERVATION_HANDOFF_V1` receipt binds the exact historical frame
attestation, its exact acquisition-frame freeze, the exact pre-result SFI3 root
reservation, and the V2R4 container identities derived only from the frozen
frame. It verifies strict reservation-before-attestation-before-measurement
chronology, schema/id/content/module-digest equivalence, and zero container
collisions using identity metadata only. It records hashes of the historical
`root_disjointness` and `sfi3_separation` blocks rather than duplicating or
replacing them.

SFI3 consumes the exact handoff receipt path and file SHA-256 pinned in its
protocol. It never resolves this authority by a newest-wins glob. Any missing,
drifted, reordered, colliding, payload-reading, or outcome-reading input blocks
before SFI3 opens. No endpoint, threshold, scorer rule, V2R4 invariant, or
historical receipt is changed by this administrative bridge.

## INC-V2-085 — SFI3 exhausts its frozen frame but remains non-scorable

**Class:** predeclared family-quota shortfall after exhaustive acquisition.
**Disposition:** HELD-OUT CORPUS SPENT, NOT SCORED, NOT REPAIRED.
**GPU seconds:** 0 · **Cost:** $0 · **IP gate:** CLOSED.

`SOURCE_FACT_IR_HELDOUT_V3` considered every one of the 1,698 identities in its
frozen lineage frame. The immutable acquisition admitted 245 pairs and rejected
1,453. Git documentation filled 120 of 120 and eCFR regulation filled 100 of
100. Wikipedia encyclopedia admitted 25 of its frozen quota of 70.

The frame verifier reconciled every candidate, recorded
`EXHAUSTED_EVERY_CANDIDATE_CONSIDERED`, and returned `scorable: false`. Passing
the overall floor and representing all three families do not replace a frozen
family quota. The 45-pair shortfall is reported; it is not redistributed and the
quota is not lowered.

No SFI3 endpoint was scored, so this is not an endpoint FAIL and it is not
evidence that the production repair passed or failed. The opened corpus is
spent under the frozen protocol. There is no repair, reacquisition, rescore,
SFI3 acceptance, successor cohort, four-link acceptance or GPU execution from
this result.

**Authority:**
`receipts/sfi3-frame-verification--20260826T120526Z-b4f647f6e883.json`
(`receipt_sha256` `sha256:065dac3b984eecbfdb883611e53f10528e33ca41f40123e56e3040c0777b1f1f`;
file SHA-256 `sha256:54291a2ccba0b7faee8be2bc554a4529b2f64d0cc0ad26a8f1ed91e8e9194287`).

## INC-V2-086 — SFIR1 capacity instrument terminates on frozen Git-root HTTP 404

**Class:** metadata-only capacity-instrument refusal before payload.
**Disposition:** TERMINAL PRE-PAYLOAD; NO RETRY, CHARTER AMENDMENT, ROSTER,
ACQUISITION OR SCORE. **GPU seconds:** 0 · **Cost:** $0 · **IP gate:** CLOSED.

`SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V1` froze its design charter and spent-
identity authority before its capacity probe. The probe terminated in the Git
documentation family when frozen root metadata returned HTTP 404. It wrote no
capacity metadata artifact and opened no payload. No diff, SourceFact, endpoint
outcome or score exists.

This is an instrument refusal, not a compiler endpoint FAIL. The exact root was
not promoted into a scientific result, and the instrument was not retried or
amended after the refusal.

**Authority:** `receipts/sfir1-capacity-failure-authority.json` (file SHA-256
`sha256:944b3ff6baff5b125c22ed96d4f222043d741c25cf54d7ea13156e34252deb6c`).

## INC-V2-087 — SFIR2 capacity instrument refuses Git revision chronology

**Class:** metadata-only capacity-instrument refusal before payload.
**Disposition:** TERMINAL PRE-PAYLOAD; NO RETRY, CHARTER AMENDMENT, ROSTER,
ACQUISITION OR SCORE. **GPU seconds:** 0 · **Cost:** $0 · **IP gate:** CLOSED.

`SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V2` used a separately frozen charter and
spent-identity chain. Its capacity probe terminated inside the Git documentation
family because revision chronology did not satisfy the frozen instrument
contract. The exact root is unknown; eCFR and Wikipedia were not reached. No
capacity metadata artifact was written, no payload was opened, and no diff,
SourceFact, endpoint outcome or score was computed.

This raw refusal is preserved separately from SFIR1. It is neither a retry of
SFIR1 nor evidence that the compiler passed or failed an endpoint.

**Authority:** `receipts/sfir2-capacity-failure-authority.json` (file SHA-256
`sha256:83b43161d056087318aa02d24c8621688b38881b254f12949f8e73caa242dbde`).

## INC-V2-088 — SFIR3 response bound closes the replication redesign sequence

**Class:** metadata-only capacity-instrument refusal before payload, followed by
a prospective-adaptation stop. **Disposition:** TERMINAL PRE-PAYLOAD; NO SFIR4
OPENED. **GPU seconds:** 0 · **Cost:** $0 · **IP gate:** CLOSED.

`SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V3` froze a third charter and authority
chain before its capacity probe. In the Git documentation family, a recursive-
tree response declared a `Content-Length` above the instrument's frozen 16 MiB
metadata-response bound. The probe refused the response before writing capacity
metadata or opening payload. The exact root is unknown; eCFR and Wikipedia were
not reached. No roster, acquisition, diff, SourceFact, endpoint outcome or score
exists.

After three separately frozen instruments had exposed three different failure
surfaces — HTTP 404, revision chronology, then response size — no SFIR4 was
opened. Another redesign conditioned on all three observed refusals would risk
result-following adaptation. This decision does not prove that every possible
instrument is infeasible; it preserves the boundary around what these frozen
instruments actually measured.

The sequence is methodological negative evidence only. It is not an endpoint
FAIL, not a pooled compiler result, and not a model result. Founder, human and
counsel review remain pending; `INTERNAL_ONLY` and IP gate CLOSED remain in
force.

**Authority:** `receipts/sfir3-capacity-failure-authority.json` (file SHA-256
`sha256:531773f0aa1877f82e324611383cc69d29b9ca5a699b63ca68299953548d7273`).

## INC-V2-089 - the frozen instrument drifted, and the verifier could not see it

**Class:** evidence-integrity breach with no recovery source. **Disposition:**
STOP THE LINE; no re-pin; no new freeze; no acquisition; no GPU.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

`verify_sealed_evidence.py` reports PASS-shaped totals over a scope that is
declared in its own receipt as:

    docs/evidence/*.json - docs/ip/receipts/*.json -
    research/experiments/*/receipts/*.json - research/experiments/*/manifest.json

`research/tavonel_eval_v2/receipts/*.json` is not in it. Every freeze this study
performed pins its instrument there. For the whole life of the study no verifier
read those pins, so the pins could not fail, so their silence meant nothing.
This is the INC-V2-036 class again -- a guard placed where its failure is
impossible -- and it is the reason the drift below went unobserved rather than
the reason it happened.

`tools/verify_frozen_instrument_integrity.py` is that missing guard. Aimed at the
skipped surface it returns, on first execution:

    bindings_checked          526
    bindings_match            341
    bindings_frozen_drift     59
    bindings_advisory_drift   126
    frozen_files_drifted      29
    frozen_receipts_affected  20
    verdict                   FAIL

Advisory drift is not a finding: a suite-evidence or hygiene receipt records the
tree at a moment and the tree is expected to move on. Frozen drift is the
finding. 29 files that 20 freeze or attestation receipts declared
immutable no longer carry the bytes those receipts pin.

### Which files

- `compiler/selective_build.py`
- `tests/test_v2r3_contract_consistency.py`
- `tools/common.py`
- `tools/enumerate_v2r3r1_universe.py`
- `tools/freeze_migration_closure_v2r3.py`
- `tools/freeze_migration_closure_v2r4.py`
- `tools/identity_change_migration_closure.py`
- `tools/identity_change_migration_closure_v2r2.py`
- `tools/identity_change_migration_closure_v2r3.py`
- `tools/invariant_domain.py`
- `tools/probe_sfir1_capacity.py`
- `tools/probe_sfir2_capacity.py`
- `tools/probe_sfir3_capacity.py`
- `tools/probe_v2r4_roots.py`
- `tools/rehearse_v2r4_closure.py`
- `tools/root_identity.py`
- `tools/run_p1_smoke.py`
- `tools/sfi3_root_reservation.py`
- `tools/sfir3_spent_authority.py`
- `tools/v2r2_invariant6.py`
- `tools/v2r3_attestation.py`
- `tools/v2r3_effective_identity.py`
- `tools/v2r3_quarantine_oracle.py`
- `tools/v2r3_state_table.py`
- `tools/v2r3r1_carry_forward.py`
- `tools/v2r4_attestation.py`
- `tools/v2r4_grading.py`
- `tools/v2r4_semantics_delta.py`
- `tools/verify_sealed_evidence.py`

### Which frozen receipts

- `identity-change-migration-closure-v2r2-scorer-freeze--20260825T104559Z-db606c6abc47.json`
- `identity-change-migration-closure-v2r3-frame-attestation--20260825T173240Z-8d8c7cbeb23e.json`
- `identity-change-migration-closure-v2r3-protocol-attestation--20260825T173258Z-5954c7c33e27.json`
- `identity-change-migration-closure-v2r3-scorer-freeze--20260825T180251Z-bb65b8985c08.json`
- `identity-change-migration-closure-v2r3r1-frame-attestation--20260825T210400Z-fbab51b67a9e.json`
- `identity-change-migration-closure-v2r3r1-protocol-attestation--20260825T210409Z-b2cca585b5a3.json`
- `identity-change-migration-closure-v2r3r1-protocol-attestation--20260825T211447Z-702db72e7d2b.json`
- `identity-change-migration-closure-v2r3r1-scorer-freeze--20260825T212103Z-426c31cc4eed.json`
- `identity-change-migration-closure-v2r4-domain-attestation--20260826T061752Z-371566b4e8b7.json`
- `identity-change-migration-closure-v2r4-frame-attestation--20260826T050508Z-a1a4ec80798a.json`
- `identity-change-migration-closure-v2r4-protocol-attestation--20260826T050543Z-53b2dc7abad8.json`
- `identity-change-migration-closure-v2r4-scorer-freeze--20260826T061751Z-f76342b0a123.json`
- `p0-v1-seal.json`
- `sfir1-capacity-failure-authority.json`
- `sfir1-design-charter-freeze.json`
- `sfir1-spent-identity-authority.json`
- `sfir2-capacity-failure-authority.json`
- `sfir2-design-charter-freeze.json`
- `sfir3-capacity-failure-authority.json`
- `sfir3-design-charter-freeze.json`

### What this costs

The V2R4 chain is affected at all four of its rungs -- frame, protocol, domain
and scorer. The scorer freeze pins `tools/v2r4_grading.py`, and the grading
module that produced the only PASS this study holds is not the grading module on
disk. The V2R4 measurement receipt
`identity-change-migration-closure-v2r4--20260826T064947Z-e6cab21d2c93.json` is
untouched and its recorded result stands exactly as recorded, but it is **no
longer byte-reproducible from this worktree**. That is a strictly weaker claim
than the one the frozen-instrument design existed to support, and the difference
must not be papered over.

The same applies to the negative evidence. `probe_sfir1_capacity.py`,
`probe_sfir2_capacity.py` and `probe_sfir3_capacity.py` are each pinned by the
capacity-failure authority that records why that instrument refused, and each
has drifted. INC-V2-086, INC-V2-087 and INC-V2-088 remain true statements about
what was observed; they are no longer re-derivable.

`tools/v2r3r1_semantics.py` did **not** drift. The founder's preservation order
over that file held.

### Why there is no recovery

`research/tavonel_eval_v2/` is not ignored by git and never was. It is
**untracked** -- `git ls-files` returns 0 paths under it. The study kept its
history in receipts and never in version control, so when a file changed there
was no second copy of the previous bytes anywhere. `forensic_snapshots/` holds
one directory (`INC-V2-001`) and does not cover these files. The original bytes
are gone, and no honest procedure recovers them.

The absence of version control is the root cause. The missing verifier is why it
stayed invisible; the missing repository is why it is unrecoverable.

### What was deliberately not done

The pins were not rewritten. Writing current digests into
`identity-change-migration-closure-v2r4-scorer-freeze` would turn FAIL into PASS
without changing a single fact, and `historical evidence overwritten` is itself a
stop-the-line item in the project constitution. The verifier that found this is
built so that it cannot perform that repair: it has no write path to any pin.

No SFIR4 freeze was opened, no corpus was acquired, no GPU was provisioned and
no paper claim was strengthened while this stands open.

**Authority:** `receipts/frozen-instrument-integrity.json`
(schema `tavonel.v2.frozen_instrument_integrity.v1`, verdict `FAIL`).

## INC-V2-090 - SFIR4 hostile audit, closed before the instrument was frozen

**Class:** four prospective instrument defects, found and repaired while SFIR4
was still unopened. **Disposition:** REPAIRED; SFIR4 STILL UNFROZEN.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

None of these was reachable after a freeze. SFIR1, SFIR2 and SFIR3 each died at
a different surface of a frozen instrument, and each time the only honest
response was to close the study. This audit ran while the instrument could still
be changed.

### A - the census recorded what it asked for, not what came back

`probe_sfir4_capacity` recorded `refs.append(url)`, and `_response_size` measured
`len(json.dumps(parsed_value))`. A URL is a record of a request. The size was a
property of `json.dumps` -- key order, separators, escaping -- not of any bytes
that crossed the wire, and it sat in the receipt beside real byte bounds. The
actual bytes were in `_http_json`'s local `raw` and were discarded after parsing.

`tools/sfir4_response_evidence.py` records, per request: the immutable target,
the sha-256 of the bytes received, declared and observed length, the position in
a global sequence, the root, and how the request ended. The sequence is bound by
a hash chain, so dropping or reordering an observation changes the head and the
per-root arithmetic stops summing to the global count.
`_assert_response_evidence` refuses a census whose chain does not recompute.

Two properties that are not obvious and are the point:

* **Failures stay in the chain.** A request that returned no body still consumed
  the budget the frozen bounds are checked against. Arithmetic that silently
  omits failures does not reconcile with the bound it claims to respect.
* **A synthesised census cannot pose as a live one.** An injected fetcher has no
  bytes, so its observations are recorded as `synthesized-sha256` with
  `observed_bytes: false`, and sealing refuses. Without that, a test double
  could manufacture evidence a receipt would present as observed.

No header is stored anywhere. The GitHub token travels in an `Authorization`
header, and the guarantee that it cannot reach an artifact is that no code path
writes a header into one. `assert_credential_free` additionally refuses a URL
carrying userinfo or a secret-shaped parameter.

### B - SFIR4 delegated its own locator contract to SFIR1

`sfir4_worker.resolve_payload_locator` called `sfir1_worker`. This is the
delegation-to-parent class inverted: the parent knows SFIR1's contract, not
SFIR4's, so SFIR4's frozen candidate contract was never what got enforced. The
parent accepts, and `tests/test_sfir4_locator.py` holds a red control for each:

1. a mutable Git ref (`blob/main/...`) where the family requires an immutable
   commit -- the whole "immutable target" property of `git_docs` lost silently;
2. path traversal (`../..`), which survives because `quote` leaves `.` alone;
3. an empty path segment, which passes `if not document` because the list is
   non-empty;
4. credentials in the netloc, carried into the resolved URL;
5. percent-encoded separators, giving two locators for one document;
6. an eCFR section validated and then dropped from the resolution, so the
   resolved URL was not an identifier of the candidate;
7. non-ASCII digits and non-canonical ids (`007`), because `str.isdigit()` is
   true for Arabic-Indic digits and `int()` parses them.

`tools/sfir4_locator.py` is SFIR4's own grammar: ASCII only, percent-encoding
refused outright rather than canonicalised, canonical form required, and every
identifier in exactly one spelling.

On (6) the request was deliberately **not** changed. The eCFR versioner serves a
whole part and the section is isolated locally afterwards; forcing `section` into
the query would make `resolve` injective on its own but would also change what
the live API is asked for, and an unverified change to a live API contract
immediately before a frozen census is precisely what ended SFIR1, SFIR2 and
SFIR3. Injectivity is recovered by `resolution_identity`, and
`test_distinct_locators_never_share_a_resolution_identity` executes the map over
a matrix rather than asserting the property in prose.

`test_the_inherited_resolver_accepted_what_this_grammar_refuses` fails if a hole
is later closed upstream, so this entry cannot quietly become false.

### C - the identity proof was wrong in both directions at once

The collision proof pooled `container_id`, `lineage_id` and `alias_ids` into one
flat, casefolded, cross-family set. Neither error was visible because they
cancelled in the cases that were exercised:

* **False refusal.** Pooling across families meant an accidental string equality
  between unrelated corpora would be reported as scientific identity
  equivalence. Requiring `container_id` unique refused every candidate after the
  first in one container.
* **False pass.** `root_container_id` was never added to the set at all, so a
  `root_container_id` equal to another candidate's `container_id` was not a
  collision to that proof.
* **`casefold` had both error modes and the guarantee of neither.** It
  over-merged (the German sharp s and `ss` fold together, so live candidates
  collided spuriously) and under-merged (no Unicode normalisation, so an
  NFD-spelled spent identity never matched its NFC candidate and was admitted as
  fresh).

`tools/sfir4_identity_domain.py` types the five fields into three namespaces --
DOCUMENT proved unique, CONTAINER and ROOT proved consistent because repetition
is legitimate there -- keeps the one cross-check that was right (no name denotes
both a document and its container), and splits the comparison in two: exact
after NFC between live candidates, deliberately widened (NFKC, format characters
stripped, whitespace collapsed, casefold) against the spent set. The two want
opposite errors, which is why one function could not serve both.

Case-variant refusal is a **declared per-family property** read off the
constructors, not a blanket rule: `git_docs` lineages carry the tree path
verbatim and `README.md`/`readme.md` are two real files, so refusing them would
discard a legitimate candidate; Wikipedia aliases are built with `.casefold()`
already, so a case variant there cannot come from the API and is refused.

The proof now runs BEFORE the capacity threshold. An identity defect is more
fundamental than a shortfall, and whichever check runs first is the one the
refusal reports.

### D - the prospective answer to INC-V2-089

`tools/sfir4_execution_closure.py` computes the SFIR4 execution closure by
static import analysis -- parsing, never importing, because `sources_sfir4` runs
`assert_static_disjointness()` at module scope and an import-based closure would
execute the instrument in order to describe it -- takes a sha-256 manifest over
it, asks git which of those files are tracked, and REFUSES the freeze if any is
not. Both `freeze_roster` and `freeze_protocol` call it before anything is
sealed.

Current verdict, sealed at `receipts/sfir4-execution-closure.json`:

    closure_files       68
    tracked             3
    untracked           65
    unresolved_imports  0
    verdict             REFUSE

The three tracked files are the Protected Core modules under
`packages/cir-python/`. The other 65 are the research tree, which has
never been committed. **SFIR4 cannot be frozen until they are tracked**, and
putting them under version control is a separate act requiring the founder's
instruction; this gate reports the list and does not perform it.

An unresolved import is a REFUSE, not a warning: it means the closure may be
missing files, and an under-inclusive closure is exactly the failure the gate
exists to prevent -- one that would not be visible.

### What this entry does not claim

The historical FAIL is untouched and unchanged: 59 frozen bindings, 29 files, 20
receipts. Nothing here recovers a byte of it. `ANTI_BLOCKER_AUDIT_PASS` with 0
blockers is not a correctness proof and 14 FINDINGs remain open. SFIR4 is
unfrozen, no roster exists, no payload has been opened, and no GPU has been
provisioned.

**Authority:** `receipts/sfir4-execution-closure.json` (verdict `REFUSE`) and
`receipts/frozen-instrument-integrity.json` (verdict `FAIL`, unchanged).

## INC-V2-091 - the closure reaches Protected Core that another workstream is holding open

**Class:** recoverability blocked by uncommitted third-party state, found by the
gate it was built to trip. **Disposition:** SFIR4 FREEZE BLOCKED; FOUNDER
DECISION REQUIRED. **GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

Commit `79dd3b7` put the SFIR4 execution and verification closure under version
control: 77 research-tree files plus a tree-local `.gitattributes`, every one
byte-identical to its committed blob. The gate advanced from 77 uncommitted to
0. It still REFUSES, for a different and narrower reason:

    closure_files          80
    committed_at_head      80
    uncommitted             0
    byte_identical_to_head 77
    divergent_from_head     3      <- the refusal
    unresolved_imports      0

The three are Protected Core, which SFIR4 executes:

- `packages/cir-python/src/akc_cir/dependency.py`
- `packages/cir-python/src/akc_cir/recompilation.py`
- `packages/cir-python/src/akc_cir/semantic_diff.py`

They are committed, and they are not recoverable. Their working trees carry 982
uncommitted lines belonging to a different workstream (the INC-V2-037 and
INC-V2-047 identity/quarantine work). The manifest digest is taken over the
working tree, so while these differ from HEAD, a fresh clone at `79dd3b7`
reconstructs a **different instrument** than the one a freeze would pin. That is
INC-V2-089's defect exactly -- a pin naming bytes git will not return -- and the
gate is correct to refuse.

### Why this was not resolved directly

Reaching PASS requires committing another workstream's in-flight changes to
Protected Core. Three separate rules forbid it: the commit scope authorised for
this work excludes unrelated dirty state and requires it preserved; Protected
Core is not modified outside its own replacement ladder; and an agent does not
land another agent's unfinished work in order to unblock itself.

Discarding the working-tree changes to reach PASS would destroy 982 lines of
someone else's work and is not considered.

### What must not be done instead

Narrowing the closure so `akc_cir` falls outside it would turn REFUSE into PASS
without changing a single fact. SFIR4 imports these modules; a closure that does
not reach them is not a closure, and the gate would then be a guard placed where
its failure is impossible -- INC-V2-036, for the fourth time in this study.
`test_freeze_refuses_while_the_protected_core_diverges_from_head` fails if the
divergence is resolved, so the state cannot silently change without notice.

### The two paths open

1. **The other workstream commits.** Its owner lands the `akc_cir` changes; the
   gate goes PASS and SFIR4 freezes against a clean HEAD. Simplest, and correct
   if that work is ready.
2. **SFIR4 runs from an isolated checkout at a fixed commit.** The study stops
   depending on whatever happens to be in a shared working tree and executes
   against a clone pinned to one revision. More work, and the durable answer:
   it removes an entire class of dependency on uncommitted local state, which
   is the class INC-V2-089 belongs to.

Path 2 is the recommendation for the study as a whole; path 1 unblocks SFIR4
sooner if that workstream is finished.

### State at this entry

    SFIR4 focused suite            236 passed
    anti_blocker_audit             PASS, 0 blockers, 14 FINDINGs open
    source recoverability          REFUSE (3 divergent)
    frozen instrument integrity    FAIL 59 / 29 / 20, unchanged
    unrelated dirty files          42, untouched
    SFIR4                          unfrozen, no roster, no payload, no GPU

The historical FAIL is unchanged and no historical receipt was touched. Commit
`79dd3b7` establishes that current bytes are recoverable from 2026-08-27
onward; it recovers nothing, and must not be recorded as repairing INC-V2-089.

**Authority:** `receipts/sfir4-execution-closure.json` (verdict `REFUSE`,
head_commit `79dd3b70460b6fc0a7deb44c6f29ecf99049f06e`).

## INC-V2-092 - PROTECTED_CORE_NOT_LANDED

**Class:** the intended algorithm exists only in uncommitted state, so no
revision can be frozen against it. **Disposition:** SFIR4 FREEZE STOPPED;
FOUNDER DECISION REQUIRED. **GPU seconds:** 0 - **Cost:** $0 - **IP gate:**
CLOSED.

The instruction was to run SFIR4 from an isolated checkout at a fixed revision
rather than from the shared dirty working tree, and explicitly *not* to check
out `79dd3b7` and freeze. That check was made and it changed the answer.

### The isolated checkout was built and rejected

A detached worktree at `79dd3b7` was created, verified clean (0 status entries)
and left the shared tree untouched (566 entries preserved). It is not a viable
scientific baseline, and the reason is not recoverability -- it satisfies every
recoverability property this study checks:

    closure_files 83 - committed_at_head 83 - uncommitted 0
    byte_identical_to_head 80 - unresolved_imports 0

SFIR4 cannot import it. Every one of the 18 suite failures at that revision
traces to a single root cause:

    ImportError: cannot import name 'DependencyChannel' from 'akc_cir.dependency'

The worktree has since been removed so that a rejected revision cannot be
mistaken for a baseline. It is reproducible at any time with
`git worktree add --detach <path> <revision>`.

### A trap that would have manufactured a false PASS

The shared virtualenv installs the repository editable and its `.pth` hard-codes
`D:\CodexProjects\ai-knowledge-compiler\packages\cir-python\src` -- an
absolute path into the SHARED working tree. An isolated checkout run with that
interpreter imports the shared tree's Protected Core regardless of what revision
it is pinned to. Every receipt would have recorded `isolated_git_checkout` and
the pinned commit, and the code that actually ran would have been whatever a
developer had open at that moment.

The import failure above is visible only because `PYTHONPATH` was forced to the
isolated tree first. Without that, the isolated run would have passed, and the
pass would have meant nothing. `sfir4_core_conformance` now records where
`akc_cir` actually resolved and refuses when it is not the intended root.

### The semantic comparison

`79dd3b7` committed core versus the shared working tree, by API surface, read
with `ast` and never by importing either side:

                        committed    worktree   API added   API removed
    dependency.py           11630       13498           2             0
    recompilation.py        11505       30250           8             0
    semantic_diff.py        18387       45131           9             0

**Zero removals.** This is not two divergent implementations; the working tree is
a strict superset. It is unlanded work, not a fork.

Seven of the additions carry paper claims, and none exists at `79dd3b7`:

    dependency      DependencyChannel                      typed dependency propagation
    dependency      ALL_DEPENDENCY_CHANNELS                closed, enumerable channel set
    recompilation   FacetVerdict                           UNRESOLVED is recorded, not silent
    recompilation   StructuralPolicy                       structural participation is declared
    semantic_diff   ChangeChannel                          identity and change decided independently
    semantic_diff   content_facet_verdict                  change decided on CONTENT, not identity
    semantic_diff   QUARANTINE_UNSETTLED_IDENTITY_DEFAULT  unsettled identity quarantined, fail-closed

Mapped onto the contribution the paper argues, five of its seven links are
implemented only in uncommitted state:

    stable identity != evidence occurrence   UnitSnapshot.logical_unit_id /
                                             .evidence_occurrence_id     UNLANDED
    independent typed identity/change        ChangeChannel,
                                             content_facet_verdict       UNLANDED
    unresolved -> fail-closed quarantine     QUARANTINE_UNSETTLED_...,
                                             FacetVerdict.UNRESOLVED     UNLANDED
    typed dependency propagation             DependencyChannel           UNLANDED
    selective candidate recompilation        FacetPolicy, StructuralPolicy,
                                             FacetResolution             UNLANDED
    provenance continuity / equivalence      research tree               committed
    atomic verified activation               research tree               committed

### Classification

These are not refactors and not unrelated implementation work. Two of them carry
incident numbers in their own docstrings and describe correctness failures on
the paper's central claim:

* **INC-V2-038** (`FacetPolicy`): LOCATOR, TEMPORAL and METADATA changes were
  detected and correctly typed and then reached nothing, because
  `changed_logical_ids` admitted only SEMANTIC and GRAPH. Artifacts that read the
  changed unit were labelled `CURRENT, "no change reached it"` -- a **claim of
  freshness that was false**. That is the exact failure a knowledge compiler
  exists to prevent.
* **`StructuralPolicy`**: the previous `ALWAYS` behaviour raised false
  invalidation to 80.5% on real-revision corpora while buying no correctness. A
  measured result, and it lives only in the working tree.

So the honest classification is `intended final TAVONEL semantics` plus
`correctness fix`, not `experimental algorithm change`.

### The work is committed nowhere

Every branch in the repository was checked, including
`agent/tavonel-protected-core-promotion`. **No branch's committed Protected Core
carries all 13 required symbols.** These changes exist in exactly one place: the
shared working tree, uncommitted. Nothing in git holds them.

### What was deliberately not done

The dirty bytes were not copied into the isolated checkout, no patch was
applied, and no snapshot was promoted to a scientific baseline. Freezing against
a working tree is what INC-V2-089 already cost this study once.

`REQUIRED_SYMBOLS` was not narrowed so that `79dd3b7` would conform. That would
convert REFUSE into PASS without changing a fact, and would leave the paper
claiming an algorithm the frozen instrument does not contain.

### The order that must be followed

    dirty Protected Core
      -> a normal dedicated commit, in its owning workstream
      -> new isolated checkout at that revision
      -> recoverability + conformance + hostile audit + suite
      -> freeze
      -> metadata-only live capacity census

### State at this entry

    baseline commit                2e0ba427bd84eb478d1e75ceb2d05e4eae3ad244
    SFIR4 focused suite            250 passed
    anti_blocker_audit             PASS, 0 blockers, 14 FINDINGs open
    Protected Core conformance     PASS against the shared core, REFUSE at 79dd3b7 (7 absent)
    source recoverability          REFUSE (3 divergent, the Protected Core)
    frozen instrument integrity    FAIL 59 / 29 / 20, unchanged
    shared tree dirty entries      566, untouched
    SFIR4                          unfrozen, no roster, no payload, no GPU

The historical FAIL is unchanged, no historical receipt was touched, and the
isolated checkout is not recorded as having recovered any of it.

**Authority:** `receipts/sfir4-core-conformance.json`,
`receipts/sfir4-core-revision-comparison.json`,
`receipts/sfir4-execution-closure.json`.

## INC-V2-093 - the Protected Core landed, and the research tree entered version control

**Class:** the root cause of INC-V2-089, closed prospectively. **Disposition:**
SFIR4 UNBLOCKED; historical irreproducibility PRESERVED. **GPU seconds:** 0 -
**Cost:** $0 - **IP gate:** CLOSED.

INC-V2-092 stopped SFIR4 with `PROTECTED_CORE_NOT_LANDED`: the algorithm the
paper describes existed only as 982 uncommitted lines in a shared working tree,
so no revision could be frozen against it, and `79dd3b7` -- clean, committed,
byte-identical, fully closed under imports -- was missing seven claim-bearing
symbols and could not import SFIR4 at all.

### What was audited before it was landed

The change was hostile-reviewed on correctness, intended semantics, backward
compatibility and regression before any commit. It is not a refactor:

- `dependency.py` -- `DependencyEdge.channels` defaults to
  `ALL_DEPENDENCY_CHANNELS`, so every existing adapter is unaffected. Additive.
- `semantic_diff.py` -- the `MODIFIED_CLAIM` gate moves off
  `normalize_text_for_identity`, a fold documented as lossy and built for a
  different question, onto the CONTENT facet derived from raw text under NFC
  alone. `legacy_identity_change_predicate=True` keeps the old path reachable
  for canary comparison and rollback.
- `recompilation.py` -- `StructuralPolicy.LEGACY` with the legacy flag off
  reproduces prior behaviour exactly. Two defaults do change, deliberately and
  with measurement attached: `facet_policy=DECLARED` and
  `seed_unresolved_incoming=True`, the latter costing two additional artifact
  rebuilds out of 334 across 23 real revision pairs. `StructuralPolicy.ALWAYS`
  ships available and non-default: it was measured at 80.5% false invalidation
  on real-revision corpora while buying no correctness.
- `identity.py` -- the N x M signal/missing cache is dropped; it turned a
  10,000-unit version pair into a `MemoryError`. The assignment is unchanged and
  the per-row signals are recomputed by the same pure function on the same
  inputs.

Two of these carry incident numbers in their own docstrings and describe
correctness failures on the paper's central claim, INC-V2-038 above all:
LOCATOR, TEMPORAL and METADATA changes were detected, correctly typed, and then
reached nothing, and the artifacts reading them were labelled
`CURRENT, "no change reached it"` -- a claim of freshness that was false.

### The commits

    4823d5d  Protected Core: 20 modules, 20 tests
             1091 passed, 68 skipped; ruff clean; mypy clean over 40 modules
    18bae72  the three SFIR3 predecessor receipts SFIR4 READS
    b5fe0b4  DECLARED_DATA extended; the landing control inverted
    ad99d18  the rest of the research tree, 1445 files
    37fe319  the isolated-execution gate hardened

None is pushed. 146 unrelated dirty entries elsewhere in the working tree are
untouched, no historical receipt is modified, and no repository-wide reformat
was run.

### Two evidence-integrity hazards found while landing it

**End-of-line conversion.** 19 of the 40 Protected Core files were CRLF in the
working tree, and the repository's `.gitattributes` declares `* text=auto
eol=lf`. Committing them unchanged would have produced blobs differing from the
bytes every freeze digest is taken over -- INC-V2-089's failure mode in new
clothes, arriving through a checkout rather than a rewrite. They were normalised
to LF before staging and verified blob-for-byte afterwards. The research tree
needs no such treatment: its own `.gitattributes` (`* -text -eol`) already
keeps committed blobs identical to the files the digests cover.

**The declared inputs were not in the closure.** The closure covered SFIR4's
code and not the SFI2/SFIR3 receipts SFIR4 reads. The gate therefore passed on
the machine that authored those files while eighteen SFIR4 controls failed in an
isolated checkout that could not construct them. A declared input only one
machine can produce is not recoverable, whatever the code says. `DECLARED_DATA`
now covers them, and the isolated suite went from 232/250 to 265/265 -- a
difference produced by version control, not by a line of logic.

### The isolated execution environment, and two false-isolation traps

SFIR4 now runs from `D:\CodexProjects\_sfir4_isolated`, a detached worktree with
its own venv, verified clean at every step. Two ways the isolation claim could
have been false, both real on this machine:

1. the shared venv installs the repository editable, and its `.pth` hard-codes
   fifteen absolute paths into the SHARED working tree;
2. the bash-PATH `python` resolves `akc_cir` out of a DIFFERENT clone entirely,
   `ai-knowledge-compiler-collection-plane-rehearsal`.

Either would have produced receipts reading `execution_environment:
isolated_git_checkout` over code nobody pinned. `sfir4_isolated_env` refuses
both; the refusals were exercised, not assumed.

Its ancestor rule was also hardened here. Admitting a `.pth` reference that sits
under the nearest common ancestor of the venv and the intended root is right for
a monorepo venv INSIDE a checkout and wrong for one placed beside it, where the
ancestor is a container directory holding every other clone. The ancestor must
now BE a git checkout root -- `.git` as a directory in a clone, as a file in a
linked worktree. Mutation-tested: forcing that predicate true fails the refusal
control and nothing else.

### What this does NOT do

**It recovers nothing.** The 59 drifted bindings across 29 files and 20
receipts belong to the V2R4 and SFIR1-3 chains. Those bytes were never
committed and no commit returns them. `verify_frozen_instrument_integrity`
still reports `FAIL 59 / 29 / 20` and must continue to.

What changed is prospective and only that: from `ad99d18` forward the failure
mode that produced INC-V2-089 cannot recur, because the bytes a freeze pins are
bytes git will return. The historical chain stays an irreproducibility
limitation, published as one. Recording this as a repair of INC-V2-089 would be
the laundering that entry exists to forbid.

**Authority:** `receipts/sfir4-execution-closure.json`,
`receipts/sfir4-core-conformance.json`, and the five commits named above.


## INC-V2-094 - the live-census proof was forgeable, and two pins were pins over nothing

**Class:** three defects found by an adversarial pre-freeze audit, each of the
INC-V2-036 family. **Disposition:** ALL THREE CLOSED BEFORE ANY SEAL; study
still result-blind. **GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

An adversarial audit was run against the isolated checkout before the freeze,
which is the only time a defect in an instrument is free to fix. It returned
three BLOCKERs. Each was reproduced against the real production functions before
anything was changed. Nothing had been sealed: the census run aborted for an
unrelated reason (INC-V2-095) and no capacity number has been observed.

### A -- a census of nothing certified itself

`verify_chain` recomputes the hash chain over `observations` and reads nothing
else. `_assert_response_evidence` then read `global.all_observed`,
`global.sequence_is_dense`, `global.requests` and `per_root_requests_sum`
straight out of the same untrusted document and compared them only to each
other. None of those four fields was covered by anything at all.

Reproduced exactly: a block with `observations: []` and a hand-written `global`
claiming a thousand fully observed requests verified its chain -- the head of an
empty chain is `sha256(CHAIN_SEED)`, a public unkeyed constant anyone can
compute -- and PASSED. A live-census gate certified a census in which no request
was ever made.

`ResponseLedger.require_all_observed`, written for precisely this and quoted in
the module's own docstring as the thing that prevents it, had zero call sites
anywhere. It could not have had a useful one: it is a method on a ledger held in
memory, and every sealing caller holds a JSON file.

`require_observed_census` now RECOMPUTES `global`, `per_root` and
`per_root_requests_sum` from the observations and compares them field by field,
refuses an empty observation list with a message that says why an empty chain
proves nothing, and tests for synthesis on two independent signals -- the
`observed_bytes` flag AND the `synthesized-sha256:` digest prefix. Two, because
a forger who rewrites one leaves the other; a forgery that rebuilt the chain
over edited rows and recomputed every aggregate was still refused on the prefix.

### B -- five of the charter's six toolchain pins were never read again

The charter pins six modules by sha at freeze time. Exactly one was ever checked
afterwards: the probe verifies its own file before a census.

`acquisition/sources_sfir4.py` holds `SOURCE_POOLS`, `declared_roots` and
`SELECTION_SALT` -- the roots, the per-root caps, the deterministic ordering.
It was imported at four call sites and compared to its pin at none. The
consequence is a complete path around pre-registration: a census short for one
family could be rescued by widening a root list in that module, re-running the
probe in a fresh process, and sealing against the SAME already-frozen charter,
with nothing comparing the new bytes to the pinned hash. Post-hoc root addition,
wearing a frozen charter.

`verify_toolchain` re-hashes all six and refuses on drift. `seal_capacity` and
both freeze paths call it, and the sealed receipt now carries the re-verified
digests BESIDE the charter's, in a separate field, because a field that merely
echoes the charter cannot show that anything was checked.

### C -- the freeze never asked which Protected Core would load

Both freeze paths called `conformance.require_conformant()` with no expected
root, so the branch that checks WHERE `akc_cir` resolved never ran: the gate
only asked whether SOME importable core exposed the right symbol names. And
`sfir4_isolated_env` -- written for exactly the shared-venv absolute-path `.pth`
described in INC-V2-093 -- had zero call sites and was not in the closure's
verification entry points, so nothing even required it to be committed.

A receipt would have recorded `execution_environment: isolated_git_checkout`
while the interpreter imported whatever a developer had open. That is
INC-V2-092's finding restated: a checkout can satisfy every recoverability
property and still not be the code that runs.

`_require_reproducible_instrument()` now runs all three -- recoverable,
conformant, isolated -- from one place, so the two freeze paths cannot drift
apart, against an `EXPECTED_CORE_ROOT` derived from the running checkout rather
than configured. There is no value anyone can set to make a freeze run from one
checkout expect another checkout's core.

### D (MAJOR) -- a docstring described a property nothing established

`payload_resolution_identity`'s docstring: "a roster proves distinctness over
this value, never over `resolve_payload_locator`". The function had no call
sites, in the pipeline or in a test.

The roster now computes it. The honest framing, recorded in the code:
injectivity is established UPSTREAM by `_validate_candidate`, which derives each
locator from the candidate's own fields and refuses any mismatch, so two
candidates with different `lineage_id`s cannot reach the loop sharing one
resolution identity. What was added is a cross-check of that derivation, not the
proof -- it fires the day the derivation stops binding the section into the
locator, which is the day the eCFR URL-sharing case silently returns. Its
controls reach it by suspending the upstream validator, and a separate control
names that validator as the real source of the property, so the cross-check
cannot be mistaken for it.

Wiring it up immediately found something else: the eCFR test fixture emitted
`str(index + 1)` as a section designator. A real one is `<part>.<n>` -- `1.1`,
`170.3` -- and the versioner API has never served a bare integer. The grammar
refused it correctly; nothing had noticed, because until now no code in the
freeze path resolved a candidate's locator.

### Why the audit found what the suite did not

Every existing response-evidence test started from an honestly computed
`ledger.proof()`. None constructed the document a tamperer would. A suite built
only from the happy artefact tests that the artefact is well-formed, never that
a malformed one is refused -- and the gap sat between two functions each of
which was individually correct.

**Authority:** the reproductions, re-run against the fixes; commits `51b8260`
and `8095d03`.


## INC-V2-095 - eCFR renamed a metadata field between SFIR3 and SFIR4

**Class:** external API drift, aborting a live census in flight.
**Disposition:** ADAPTER CORRECTED; charter re-frozen result-blind; census
re-run. **GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

The first live metadata-only capacity census ran for roughly fifty minutes and
aborted:

    sfir3_protocol.SFIR3Refused: eCFR latest_date metadata malformed

The eCFR versioner API serves `meta.latest_amendment_date` and served
`meta.latest_date` when SFIR3 read it. The old key is absent from the current
response, not null. Confirmed directly against the live endpoint:

    meta keys: latest_amendment_date, latest_issue_date, page, per_page,
               result_count, title, total_pages
    latest_date            -> None
    latest_amendment_date  -> '2026-08-19'

Nothing else moved. The row shape is unchanged: 981 of 1000 rows on title-21
page 1 still satisfy the adapter's `type == "section"` filter with `part`,
`identifier` and `date` present.

### The fix, and why it is a disjunction and not a fallback

Both spellings are accepted, explicitly. SFIR3's frozen receipts were produced
against `latest_date`, so that branch is what still lets this adapter reproduce
SFIR3's reading; the new branch reads the endpoint as it stands. Both are
reachable, which is what separates a disjunction from a guard that can never
fire. Neither present is still a refusal: the value pins which edition of the
regulation an enumeration describes, and an enumeration that cannot say which
edition it read is not evidence about any of them.

### Why re-freezing the charter here is result-blind

The design charter pins `probe_sfir3_capacity.py` by sha, so correcting it
required re-freezing. Three facts make that legitimate rather than a protocol
change made after seeing data:

1. **No result existed.** The run raised before any capacity number was
   computed, printed or written. The captured output contains a traceback and
   nothing else -- no C_f, no Q_f, no candidate count. Grepped and confirmed
   before anything was touched.
2. **Nothing about the criterion moved.** The change is to an input-parsing
   adapter. No threshold, root set, per-root cap, cohort, selection salt or
   scorer differs by a byte.
3. **The correction is determined by the endpoint, not by an outcome.** A
   renamed field has one right answer, and it is the same answer whichever way
   the census comes out.

Recorded because the reverse -- adjusting an instrument after a census returns a
number one does not like -- is indistinguishable from this if nobody writes down
which one happened. This is the entry that says which.

### What the study still owes

`probe_sfir2_capacity.py` reads `meta.latest_date` at line 326 and is NOT
corrected here. SFI2 is spent; changing its adapter would alter a spent study's
instrument for no benefit, and its receipts were produced while that field
existed. It is left exactly as it stands, and named here so a later reader does
not mistake the omission for an oversight.

**Authority:** the aborted run's traceback; the live endpoint probe; commit
`51b8260`.

## INC-V2-096 - a reserved CFR title aborted the census on a correct answer

**Class:** an instrument requiring a field that cannot exist, aborting a live
census on a root that had answered correctly.
**Disposition:** ADAPTER CORRECTED; three zero-candidate reasons separated;
charter re-frozen result-blind. **GPU seconds:** 0 - **Cost:** $0 -
**IP gate:** CLOSED.

The second live metadata-only capacity census aborted:

    sfir3_protocol.SFIR3Refused: eCFR edition date is absent under both
    'latest_amendment_date' and 'latest_date'

This is not INC-V2-095 recurring. That was a renamed field, and the disjunction
that closed it is intact. This is a title for which NEITHER spelling exists,
because the title has no edition to date.

All fifty declared eCFR titles were probed directly:

    titles with an edition date: 49
    titles WITHOUT:               1
        title 35 -> meta keys ['result_count', 'title'],
                    result_count '0', content_versions 0 rows

CFR title 35 is reserved. The versioner API answers 200, honestly, with nothing
in it. The adapter then demanded a date the response could not carry and refused
the whole census.

### The defect is in the instrument, not the endpoint

The endpoint is right. An empty root has no edition date because there is no
edition. The adapter had one path for "this root answered" and one for "this
root failed", and no path for "this root answered and is empty" -- so an empty
root fell into the second and took the study with it.

The charter already declares the disposition this should have produced:
`ZERO_CANDIDATE_ROOT_DISPOSITION`. Nothing new was invented. What was missing
was the code that reaches it.

### Why the check is narrow, and asserted on two fields

Emptiness is decided BEFORE the date is required, and only emptiness excuses a
missing date. A NON-empty enumeration that cannot say which edition it read is
still refused -- it is not evidence about any edition, and widening the
exemption to cover it would have turned a correct refusal into silence.

Emptiness is asserted on two independent fields, the declared `result_count`
and the actual row list, joined by `and`. A response that claims zero while
carrying rows, or claims rows while carrying none, contradicts itself and falls
through to the refusal rather than being absorbed as an empty root. A control
covers each direction, and weakening the `and` to an `or` turns both red.

### Three ways to reach zero, three reasons

All three end at `ZERO_CANDIDATE_ROOT_DISPOSITION`, and a reader who cannot tell
them apart cannot tell what was observed:

| reason | what was observed |
|---|---|
| `EMPTY_ENUMERATION_NO_VERSIONS` | the root answered and holds nothing |
| `TRUNCATED_OR_INCOMPLETE_ENUMERATION` | the read could not be finished or reconciled |
| `EMPTY_ENUMERATION_DISAGREES_WITH_FIRST_CENSUS` | two reads seconds apart disagreed |

The third was found while writing the controls, not while writing the fix. The
first draft caught the empty enumeration at both `crawl()` call sites and gave
both the same reason -- so a root that the first census read as non-empty and
the second read as empty would have been reported as a root with no versions,
publishing a removal observed mid-census as a property of the corpus. The second
call site now carries its own reason. This is the INC-V2-036 class inverted: not
a guard that cannot fire, but a guard that fires correctly and says the wrong
thing when it does.

### Controls, and their mutation results

Seven controls in `tests/test_sfir3_protocol_capacity.py`, each mutation-tested
against the defect it claims to catch:

| mutation | red |
|---|---|
| empty check removed | 3 |
| `and` weakened to `or` | 2 |
| emptiness checked after the date requirement | 2 |
| both call sites share one reason | 2 |

The suite is 25 passed with the code correct.

### Why re-freezing the charter here is result-blind

Identical in kind to INC-V2-095, and the same three facts hold:

1. **No result existed.** The run raised before any capacity number was
   computed, printed or written. The captured output holds a traceback and
   nothing else. Grepped and confirmed before anything was touched.
2. **Nothing about the criterion moved.** No threshold, root set, per-root cap,
   cohort, selection salt or scorer differs by a byte. The change is to an
   input-parsing adapter.
3. **The correction is determined by the endpoint, not by an outcome.** An empty
   root has one right disposition and it is the same one whichever way the
   census comes out.

### What I now know that I did not before, and disclose

Diagnosing this told me that CFR title 35 contributes zero candidates. That is
outcome information about one of fifty roots, learned before the census
completed, and it is recorded here rather than left unstated. It cannot be
unlearned, so what protects the study is that it changed nothing: the root set
is charter-frozen and title 35 remains in it, its disposition is computed by the
adapter rather than chosen, and a root the criterion already counts as zero
cannot be dropped to improve a count.

The verification probe run over all fifty titles was written to be shape-only
for the same reason -- it checked which fields exist and refused to count
eligible candidates, so the capacity quantity remains unobserved. It found zero
shape problems across all fifty, which is what says title 35 is the only empty
root and the fix needs to be no wider than it is.

**Authority:** the aborted run's traceback; the fifty-title live shape probe;
`tests/test_sfir3_protocol_capacity.py` and its mutation results.

## INC-V2-097 - the recoverability commit left one pointer naming nothing

**Class:** a committed pointer whose target was never committed, found in the
commit whose purpose was recoverability.
**Disposition:** REPAIRED; standing gate added. **GPU seconds:** 0 -
**Cost:** $0 - **IP gate:** CLOSED.

While clearing unrelated churn before committing INC-V2-096, the working tree
showed `receipts/latest/r1-reproducibility-fixture.json` modified. Reverting it
to HEAD did not help: the file HEAD names does not exist either. An audit of
every mutable pointer in the tree found the extent exactly:

    pointers: 102
    resolvable on disk AND at HEAD: 101
    target absent from disk: 1
    target on disk but NOT committed at HEAD: 0

One. And `git log --all` on the target returns nothing -- it was never committed
at all. The pointer was committed in `ad99d18`, *"place the tavonel_eval_v2
study under version control"*: the commit whose entire purpose was to make this
tree recoverable published one name for bytes it did not carry. This is
INC-V2-089's failure in miniature, produced while repairing INC-V2-089.

### How it happened, and why nothing caught it

`tools/reproducibility_fixture.py` writes an immutable receipt AND updates the
mutable pointer beside it. It ran on 2026-08-26T14:35. The immutable receipt was
untracked when `ad99d18` was assembled and was removed before the commit; the
pointer, already tracked, went in carrying the new target name.

Nothing caught it because nothing asked. The SFIR4 execution closure verifies
that the files IT declares are committed and byte-identical to HEAD; no check
existed that a receipt pointer resolves to anything. A pointer is not evidence
and says so in its own `note` -- but it is the only published handle on the
receipt it names, so a pointer git cannot follow is a citation into nothing.

### What was actually lost: nothing

The R1 fixture is deterministic by construction -- no clock, no randomness, no
environment, no filesystem scan. Re-running it produces a new run id and the
same finding. All six runs on record agree:

    20260822T013341Z-2be902c53afd   sha256:8f9f9a3e7a58ee90e68a9ef...
    20260822T013341Z-8ddf1de00011   sha256:8f9f9a3e7a58ee90e68a9ef...
    20260822T020257Z-660e7e970d18   sha256:8f9f9a3e7a58ee90e68a9ef...
    20260822T020257Z-ef3e5fa61232   sha256:8f9f9a3e7a58ee90e68a9ef...
    20260823T100124Z-c08b5b0fe504   sha256:8f9f9a3e7a58ee90e68a9ef...
    20260827T020427Z-0545b82e7c4d   sha256:8f9f9a3e7a58ee90e68a9ef...

Five days, six runs, one semantic result digest. The repair is the sixth row and
its pointer, both committed together. The 2026-08-26 receipt's exact bytes remain
permanently unrecoverable, and that is stated rather than papered over -- what
makes it harmless is that it carried no finding the other five do not, and that
nothing in the tree ever cited it. Grepped: the only file that mentioned that
run id was the dangling pointer itself.

**This is a repair, not a re-pin.** No historical receipt was edited, no digest
was re-stated, and the five earlier runs are untouched. A new run was added; the
mutable pointer -- which is mutable by design and declares itself not evidence --
now names it.

### The gate

`preflight_checks.receipt_pointer_targets_are_recoverable` asserts every
`receipts/latest/*.json` pointer names a file present on disk AND committed at
HEAD. Both halves are required and they fail differently:

- **absent from disk** -- the receipt is gone from this checkout, and it is
  obvious the moment anyone looks;
- **on disk but not at HEAD** -- the receipt is gone from every *other*
  checkout, and everything works locally. That is the half that shipped, and
  the harder one to notice.

Missing git returns `UNVERIFIABLE`, not `FAIL`: not knowing whether a file is
committed is a different fact from knowing it is not, and a check that fires in
every git-less export is one people learn to ignore.

Five controls, each reaching one branch: the passing tree, the disk-absent
target, the never-committed target, the git-less tree, and the real 102-pointer
receipts tree. The negative controls build a real one-commit repository rather
than a mocked git, because the check asks git a question and a mocked answer
would test the mock.

**Authority:** the 102-pointer audit; `git log --all` on the missing target
returning empty; the six-run digest agreement above.

## INC-V2-098 - one dropped connection ended a twelve-minute census

**Class:** an unhandled transport exception class in a frozen instrument.
**Disposition:** INSTRUMENT REPAIRED; retry bounded by the already-frozen
budget; charter re-frozen result-blind. **GPU seconds:** 0 - **Cost:** $0 -
**IP gate:** CLOSED.

The third live census ran twelve minutes and died:

    http.client.RemoteDisconnected: Remote end closed connection without response

Not eCFR this time. The traceback lands in `_git` -> `fetch` -> `_observe` ->
`_http_json_observed`, enumerating a GitHub tree.

### Why no handler caught it

`_http_json_observed` handled `urllib.error.HTTPError` (status codes),
then `(urllib.error.URLError, TimeoutError, json.JSONDecodeError)`.
`http.client.RemoteDisconnected` is none of those. It subclasses
`ConnectionResetError` and `BadStatusLine` -- **not** `URLError` -- so it matched
nothing and propagated raw through every layer.

The charter permits 4,800 requests. One dropped connection somewhere in 4,800 is
not an edge case, it is the expected case; three censuses have now died before
producing a number, and this instrument would have kept dying. An instrument that
cannot survive a single lost TCP connection is not an instrument.

### The repair, and what it deliberately does not do

`TransportInterrupted` is a new class, distinct from the three that existed:

| signal | what it means |
|---|---|
| `RootUnavailable` | the server answered with a status |
| `RateLimited` | the server answered and asked us to wait |
| `SFIR4Refused` | the response arrived and was unusable |
| `TransportInterrupted` | the connection failed; nothing was observed |

It is **not** folded into `RateLimited`, though that would have been a two-line
change and would have worked. A receipt that spells a dropped connection as rate
limiting puts a network event into the count a reader uses to judge whether the
endpoint was throttling us. The census receipt now reports
`rate_limit_retries`, `transport_retries` and `retries_total` separately,
because a run that lost one connection and a run that lost two hundred are
different observations and one number cannot tell them apart.

`TimeoutError` moved from the refusing branch to the retrying one. A read
timeout is a fact about the network like the others; refusing it ends a
quarter-hour census because one request was slow, and if the endpoint is
genuinely unresponsive the retry budget still ends the run -- with an honest
reason.

`json.JSONDecodeError` deliberately stayed refusing. Bytes arrived and were not
JSON: a fact about the RESPONSE, not the network. Retrying fetches the same bad
body, so a handler wide enough to retry it turns a permanent defect into a loop
that ends only when the budget does.

**No bound was widened.** Retries run under the already-frozen
`maximum_retries_per_request`, `MAX_RATE_LIMIT_WAIT_SECONDS` and
`MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS`. Nothing about the criterion moved.

### The closed vocabulary refused the new outcome, and that was correct

`sfir4_response_evidence.OUTCOMES` rejected `TRANSPORT_INTERRUPTED` until it was
registered by an explicit edit. That refusal is the design working: a new kind
of request ending reaches the evidence chain by a deliberate change to that set,
never by a caller inventing a string. An interrupted attempt is still recorded
in the observation ledger -- `verify_chain` reads the observations, so a silent
retry would be a request the arithmetic cannot see.

### A control that could not fail

Mutation testing caught a defect in my own controls, not only in the code. The
first `test_a_malformed_body_is_still_refused_not_retried` asserted
`pytest.raises(Exception)`, which `TransportInterrupted` also satisfies -- so it
passed whichever branch the code took and proved nothing. Two mutations
(malformed body made retryable; outcome vocabulary reopened) stayed green until
the controls were rewritten to name exact types.

This is the INC-V2-036 class arriving in the test suite rather than the product,
and it is recorded because it is the second time in two days that writing the
control was where the real defect surfaced.

Final mutation results, all red as they should be:

| mutation | red |
|---|---|
| the transport clause removed (the original defect) | 7 |
| a malformed body made retryable | 1 |
| an interruption relabelled as rate limiting | 1 |
| the outcome vocabulary reopened | 1 |
| a failed request allowed to carry a body | 1 |

### Result-blindness, third time

Unchanged and verified the same way. The run raised before any capacity number
was computed, printed or written; no receipt exists at the destination path; the
captured output holds a traceback and nothing else. The criterion -- threshold,
root set, per-root cap, cohort, selection salt, scorer -- is untouched, and the
correction is determined by an exception hierarchy rather than by any outcome.

**Authority:** the aborted run's traceback; the mutation table above; the
frozen bounds the retry runs under.

## INC-V2-099 - the forensic exclusion set follows a pointer nobody verifies

**Class:** a mutable pointer read as authority, on a path that reaches the new
SFIR4 chain. **Disposition:** GUARDED FROM OUTSIDE the frozen file; the frozen
file deliberately untouched. **GPU seconds:** 0 - **Cost:** $0 -
**IP gate:** CLOSED.

Triaging the anti-blocker audit's 24 entries (14 FINDING, 10 ACCEPTED; the audit
itself reports `ANTI_BLOCKER_AUDIT_PASS`, so none is a blocker) began with the
assumption that all of them sit in spent studies and none reaches SFIR4. That
assumption was wrong, and checking it was the point:

    distinct files carrying a FINDING: 7
    of those, inside the SFIR4 execution closure: 2
        acquisition/sources_sfi3.py
        tools/preflight_sfi3_roots.py

### What `sources_sfi3.py` actually does

At **import time** it derives `SFI2_E5E6_FORENSIC_LINEAGES` -- the fourteen
lineages SFI2 used to confirm the selective stale escape, the cases that must
NOT certify their own repair -- by reading
`receipts/latest/sfi2-native-provenance.json`, following its `points_to`, and
taking the confirmed ids from the receipt it names.

It handles the pointer being **missing** (raises, with a good reason: "a
forensic set that quietly shrinks re-admits a diagnostic case"). It does not
handle the pointer having **moved**. The pointer states
`points_to_file_sha256`; this reader never compares it. The digest is
decorative at that call site.

A repointed pointer would silently change which cases are excluded from a
confirmatory cohort. That is the neighbourhood of the fourth stop condition, and
it is reachable from the chain SFIR4 is about to run.

### Why the fix is NOT in that file

`sources_sfi3.py` is pinned by frozen receipts and is **not** currently among
the 29 files in `frozen-instrument-integrity.json`'s `frozen_drift`. Editing it
would newly break a frozen pin and grow the preserved historical FAIL from
59/29/20. INC-V2-095 and the founder's standing instruction say preserve that
measurement; nothing authorises enlarging it to make a repair convenient.

So the guard went where it costs no drift: `preflight_checks.
receipt_pointer_targets_are_recoverable` now also compares each pointer's stated
`points_to_file_sha256` against the bytes it resolves to. That covers all 102
pointers rather than the one reader, and it required no change to any frozen
file.

    102 pointers checked; 102 state a target digest; 0 mismatched

Every pointer in this tree makes the claim, and until now nothing in the tree
compared it.

### What this does not fix

The reader still does not verify. If someone repoints the pointer AND updates
its digest field, `sources_sfi3.py` follows it and the gate agrees, because both
are then self-consistent. Closing that needs the fourteen identities pinned
independently of the pointer -- and the natural place to pin them is inside the
frozen file, which is exactly where nothing may be edited. Recorded as a known
limitation rather than dressed up as a repair.

Three controls: a mismatched digest fails, a matching digest passes, and a
pointer that states no digest is not treated as mismatched -- absence of a claim
is not a false claim. Both mutations (never compare; treat no-claim as
mismatch) turn it red.

**Authority:** the closure-membership check above; `frozen_drift` not naming
`sources_sfi3.py`; the 102-pointer digest scan.

## INC-V2-097 update - the same pointer dangled again, and the gate caught it

**Disposition:** REGENERATED; cause of THIS recurrence undetermined and said so.

Sealing SFIR4's terminal stop, the pointer check added for the first occurrence
went red:

    102 pointers checked; 1 target absent from disk

Same pointer, new run id: `r1-reproducibility-fixture--20260827T024437Z-...`,
written at 02:44:37 and gone. The receipt was written and later vanished --
`write_immutable` creates the immutable file with an exclusive open BEFORE it
touches the pointer, so a crash between the two leaves the safe half, not this
one. No test patches `evidence.RECEIPTS` or `evidence.POINTERS`, so it was not a
tmp-directory redirection either.

**The cause of this recurrence is not established.** What is known is the window:
02:44 sits inside the INC-V2-100 incident, where `allow_under_test` was mutated
to latch permission on and `v2r4_preacquisition_gate.run()` executed for real
until the run was killed. A gate run does write receipts. That is a plausible
account and it is not a demonstrated one, and the difference is recorded rather
than smoothed over -- writing "caused by the latched guard" would be a
delegation defect: a true statement about a narrower question (it happened in
that window) presented as an answer to a wider one (what removed the file).

The repair is the same as before and no stronger: re-run the deterministic
fixture, commit the receipt and the pointer together. All runs on disk still
carry one semantic result digest, so nothing was lost but bytes.

**What this says about the first fix.** INC-V2-097 added a gate and regenerated
a receipt. The gate worked -- this was found in seconds, by a check, rather than
in a year by a reader following a citation into nothing. The regeneration did
not prevent recurrence, because it was never going to: it treated the symptom,
and the entry said so at the time. What is now also clear is that the underlying
cause remains unidentified after two occurrences, which is the honest headline
and the reason this is an update rather than a closure.

**Authority:** the failing gate output; `write_immutable`'s write order; the
absence of any test patching the receipt directories.


## INC-V2-100 - a live cohort was one stray import away from a test run

**Class:** an unguarded cohort-touching entry point reachable from pytest.
**Disposition:** GUARDED, with a self-inflicted live traversal recorded below.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

The anti-blocker audit's defect class 10 named three tools -- `preflight_sfi3_
roots`, `gpu_successor_preflight`, `v2r4_preacquisition_gate` -- each exposing a
`run()` that reaches real roots with no test-runner refusal. In the audit's own
words, an accidental import was the only thing standing between a stray call and
a live traversal.

The failure this prevents is not a crash. A stray traversal **succeeds**: it
walks the real roots, spends real request budget against real endpoints, and
observes. This study's method rests on doing that exactly once, under a frozen
protocol, with the result recorded -- and a test that quietly performed one
would be indistinguishable afterwards from one that did not.

None of the three is pinned by a FROZEN-class receipt (checked with
`verify_frozen_instrument_integrity.classify`, positively controlled against a
known `-freeze` stem), so guarding them costs no drift and does not enlarge the
preserved historical FAIL.

The refusal keys on `sys.modules` rather than `PYTEST_CURRENT_TEST`: the runner
is in `sys.modules` for the whole process once imported, so collection-time and
import-time calls are guarded too, and an import-time call is exactly the
accident being guarded against. It is written **inline** in each module because
`anti_blocker_audit` detects the guard by looking for `sys.modules` in the module
text -- a fix a detector cannot see leaves the finding standing, and the answer
to that is to make the fix visible, not to loosen the detector.

Class 10 is now empty; the audit's FINDING count fell from 14 to 11.

### I caused the exact harm the guard prevents, while testing the guard

Mutation-testing it meant disabling the refusal and re-running the controls --
and the controls call the real `run()`. So the suite did what the guard exists
to stop: a live traversal from inside pytest, twice. The first mutation run took
67 seconds because it was really walking roots. The second mutation broke
`allow_under_test`'s restore, which left the permission latched on and started
further traversals until the run was killed and the file restored from backup.

Recorded rather than quietly cleaned up, because it is the sharpest available
evidence for why the guard was needed: the accident it describes is not
hypothetical, and the person who caused it had just finished reading the finding
that described it.

**The method was wrong, not just unlucky.** A guard whose removal causes real
network effects must not be mutation-tested by removing it and calling the real
entry point. The corrected approach is to mutate against a stub module, or to
assert on source structure -- which is what
`test_the_refusal_is_the_first_thing_run_does` already does, and which caught
the first mutation without making a single request.

**Authority:** the audit's class-10 list before and after; the 67-second
mutation run; `classify` returning no FROZEN receipt for any of the three.


## INC-V2-101 - the frozen instrument cannot reach Wikipedia at the declared frame

**Class:** an operational bound specified an order of magnitude below what the
endpoint requires. **Disposition:** NOT REPAIRED IN SFIR4 -- founder decision
required. **GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

The fourth census ran 29 minutes and refused:

    sfir4_protocol.SFIR4Refused: encyclopedia_wikipedia rate-limit retry budget
    exhausted

The transport repair (INC-V2-098) held -- this run passed the point where all
three predecessors died. It stopped on a different thing, and the difference
matters: the instrument was not broken, it was **too impatient to finish**.

### A mis-diagnosis, corrected, and recorded because it was persuasive

The first measurement looked decisive. An interleaved A/B against the live
endpoint, seconds apart:

    BAD  User-Agent -> HTTP 429 (retry-after 17)
    GOOD User-Agent -> HTTP 200
    BAD  User-Agent -> HTTP 429 (retry-after 13)
    GOOD User-Agent -> HTTP 200
    BAD  User-Agent -> HTTP 429 (retry-after 9)
    GOOD User-Agent -> HTTP 200

Six alternating trials, perfectly separated. The conclusion drawn was that
Wikimedia rate-limits by User-Agent and ours was non-compliant.

It was wrong. Minutes later the **bare** User-Agent returned 200 as well. The
retry-after values in the trace above were counting down -- 17, 13, 9 -- because
the bucket our census had exhausted was recovering. The A/B did not isolate the
User-Agent; it compared an exhausted bucket against a fresh one, and the clean
alternation came from that, not from a policy.

This is recorded because a wrong answer that reproduces six times is more
dangerous than one that does not, and because the correction came from a control
the first test lacked: re-testing the arm that had failed, after waiting.

### What the endpoint actually demands

Unpaced, back-to-back, single-threaded:

    25 requests -> 10 succeeded, 15 throttled
    Retry-After: 55, 54, 54, 53, 53, 52, 51, 51, 50, 50 ...

About ten requests, then roughly a minute of enforced silence. The declared
Wikipedia frame is 30 roots at up to 100 category pages each -- up to 3,000
requests, which at the permitted rate is on the order of **4.6 hours**.

The frozen budget allows `maximum_retries_per_request: 5` and
`MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS: 180`.

Three minutes of patience against an endpoint that needs hours. This is not a
parameter that is slightly wrong; the instrument cannot reach a Wikipedia
capacity measurement at this frame under any sequence of events.

### Why SFIR4 was NOT re-frozen to fix it

The three previous corrections were unconditional defects: a field that had been
renamed, a title with no edition to date, an exception class no handler named.
Each had one right answer, the same answer whichever way the census came out.

This one is a **tuning parameter**, and a value chosen after watching a run fail
is a value chosen partly by the failure. The paper's own section 2 states the
standard: redesigning after observing successive failure modes makes the next
instrument increasingly a function of prior outcomes. Editing the budget now
would be the first correction in this study that fails that test.

Note also what a "fix" would actually require. Making the traversal feasible
means either accepting a multi-hour census or reducing
`max_category_pages_per_root` -- and the second changes the cohort, which the
standing instruction forbids outright after a failure.

So nothing in SFIR4 was touched. The run stands as an operational stop.

### The decision this needs, and who owns it

Three routes, and choosing between them is a research-design call, not an
implementation detail:

1. **Publish SFIR4 as a fourth instrument stop.** Honest, cheap, and consistent
   with how SFIR1-3 were reported. The independent-replication sequence would
   then stand at four stops and no corpus.
2. **Open SFIR5** with a declared pacing budget, frozen before any data. The
   standing instruction explicitly allows a methodologically valid new study to
   take a new protocol ID, and the capacity criterion -- threshold, roots, caps,
   salt, scorer -- would be carried across unchanged, so it remains the same
   question asked by an instrument able to reach it.
3. **Authenticated access**, which raises the limits but requires credentials
   this agent may not obtain or hold.

Route 2 is the technically indicated one. It is put to the founder rather than
taken, because route 2 is also the one where an agent deciding for itself to
re-run after a failure is hardest to distinguish from an agent tuning until it
passes -- and route 3 needs a credential decision that is explicitly not an
agent's call.

**Result-blindness at the stop.** Verified as at every previous abort: no receipt
at the destination path, and no capacity quantity computed, printed or written.
The captured output holds a traceback and nothing else.

**Authority:** the aborted run's refusal; the 25-request throttling measurement;
the frozen bounds read from `sources_sfir4.PAGINATION_CONTRACT`.

### Correction, same day: the volume figure above is wrong

The section headed *What the endpoint actually demands* states the declared
Wikipedia frame at "up to 3,000 requests ... on the order of 4.6 hours". That is
wrong, and it was wrong when written.

It assumed one request per candidate page. The adapter already batches, and has
all along:

    category_page_size:          500   (one request covers a 100-page root)
    revision_batch_size:          50   (prop=revisions over 50 titles at once)
    max_category_pages_per_root: 100
    roots:                        30

Which is roughly **3 requests per root, ~90 in total** -- not 3,000. At the
observed throughput that is about ten minutes, not four and a half hours.

The error came from reading `max_category_pages_per_root: 100` as a request
count when it is a page count, and never checking the number against the code
that issues the requests. The conclusion drawn from it -- "the instrument cannot
reach a Wikipedia capacity measurement at this frame under any sequence of
events" -- was therefore overstated. What is true is narrower and still
sufficient to have stopped SFIR4: **~90 unpaced requests exhaust a 5-retry
budget**, because the endpoint admits about ten per minute and the frozen total
wait is 180 seconds.

This is the second wrong first answer in this incident, after the User-Agent
A/B. Both are left in place above rather than edited away. A study whose method
is that incidents are evidence does not get to quietly delete the two occasions
its own analysis was confidently wrong before it was right.

**The disposition does not change.** SFIR4 remains a terminal operational stop
and its budget is still not edited: the corrected figure makes the successor
cheaper to run, not the frozen bound retroactively adequate. 180 seconds is
still less than ~90 requests need.

### What the successor's pacing is actually based on

Measured directly, after the correction, with a cool-down between arms so one
trial's bucket could not bleed into the next:

| inter-request delay | result |
|---|---|
| 0 s | 10 ok, 2 throttled |
| 2 s | 10 ok, 2 throttled |
| 5 s | 11 ok, 1 throttled |
| **7 s** | **20 ok, 0 throttled** (over 150 s) |

Spacing below about 6 seconds does not help, which says the limit is a quota per
roughly-60-second window rather than a rate: ten-ish requests get through
whatever the gaps between them. At 7 s the window never fills and nothing is
refused.

That is the operational motivation recorded in SFIR5's provenance, and it is
admissible for designing a new prospective protocol because it is a measurement
of the endpoint, not of SFIR5's capacity result -- no candidate was counted, no
threshold evaluated, no cohort read.

## INC-V2-102 - the response-evidence chain covered one family of three

**Class:** a hash-chained evidence ledger that two of three families never
reached, and a consistency check that could not notice.
**Disposition:** REPAIRED IN SFIR5; SFIR4 left untouched as a terminal stop.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

Found while building SFIR5's transport, by asking a question that had not been
asked before: which code path actually writes to the response ledger?

    ledger.record call sites in probe_sfir4_capacity: 5
    all five are inside _observe
    call sites reaching _observe: 1   ("git_docs", line 392)

`regulation_ecfr` and `encyclopedia_wikipedia` never touch `_observe`. They reach
the network through `legacy_fetch -> _http_json`, and `_http_json` calls
`_http_json_observed` and **discards the observation**, returning the value only.

Measured rather than inferred -- a full eCFR family call against SFIR4's
transport:

    eCFR family: ledger observations recorded = 0
    ledger sees families: NONE

### Why this is worse than a gap

The census receipt carries a hash-chained response ledger and a request
arithmetic that reconciles against it. A reader takes that to cover the census.
It would have covered `git_docs`.

Two of three families would have contributed candidates to a capacity figure
while producing **no response evidence at all** -- no observed bytes, no digest,
no chain entry, nothing to re-verify. The receipt would not have been lying in
any field. It would simply have been silent about the silence.

### The check that could not fail

`require_observed_census` was hardened earlier the same day (INC-V2-094) to
recompute the chain and refuse aggregates that disagree with the observations.
It is a good check and it cannot catch this. A family that never records leaves
no rows; no rows means no aggregate; and an empty recomputation agrees with an
empty declaration exactly.

This is the INC-V2-036 class in its purest form so far. Not a guard placed where
its failure is unlikely -- a guard placed where its failure is **arithmetically
impossible**, because the quantity it compares is derived from the same absence
on both sides. The study has now paid for this defect class five times, and this
is the first instance where the check was written, reviewed and strengthened
without anyone noticing it was comparing a thing to itself.

### The repair, and the check that CAN fail

SFIR5's transport routes the legacy families through `_observe` as well, so all
three families land in one chain with `observed_bytes: true`. Verified:

    eCFR ledger observations: 1
    families in ledger: ['regulation_ecfr']
    observed_bytes all true: True

`require_family_coverage` compares the ledger's families against the families the
**census reports candidates for**. That is the one comparison silence cannot
satisfy: a family that records nothing and reports candidates is a contradiction
between two independent structures, not an agreement between two empty ones.

### Why SFIR4 was not repaired

It is sealed as a terminal operational stop. Editing its frozen instrument now
would grow the preserved historical FAIL and would be repairing an instrument
that will never run again. The defect is recorded against SFIR4 and fixed in the
successor, which is what a successor is for.

**One consequence for the paper.** SFIR1, SFIR2 and SFIR3 also stopped before
producing a capacity artifact, so no sealed census exists anywhere in this
programme that could have been affected. Nothing published needs retraction. The
finding is about what the instrument WOULD have certified, and it is worth
publishing precisely because it was caught by construction rather than by
consequence.

**Authority:** the call-site count above; the zero-observation measurement; the
post-repair measurement; `_http_json`'s discard of the observation it receives.

## INC-V2-103 - the whole session ran against a different checkout's core

**Class:** the interpreter imported `akc_cir` from another working tree, and
every test result taken before this was measured against code nobody intended.
**Disposition:** REPAIRED BEFORE THE SFIR5 CENSUS; earlier measurements retracted.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

Found by running SFIR4's pre-census instrument gates for the first time on this
machine. Two of the three refused immediately:

    recoverable  PASS
    conformant   REFUSED - 13 required Protected Core symbols are absent;
                 13 paper claims are unimplemented by the core that would load;
                 akc_cir resolves from
                 D:\CodexProjects\ai-knowledge-compiler-collection-plane-rehearsal
    isolated     REFUSED - akc_cir.dependency could not be imported

The cause is a single line in the global interpreter's site-packages:

    _editable_impl_ai_knowledge_compiler.pth
      -> D:\CodexProjects\ai-knowledge-compiler-collection-plane-rehearsal\packages\cir-python\src

An editable install pointing at a *rehearsal* checkout. The repository's own
`.venv` resolves `akc_cir` correctly from this tree; the bare `python` on PATH
does not. Both interpreters run, both import, neither says anything.

### What this invalidates

Every full-suite run in this session was executed with the bare interpreter.
The figures reported earlier -- 3274 passed, 63 failed, 4 errors, and the
controlled comparison that showed the new SFIR5 files added 55 passes and no
failures -- were measured against the rehearsal checkout's Protected Core.

The comparison's *conclusion* survives, because both arms of it ran under the
same wrong interpreter and the SFIR5 modules do not import `akc_cir` at all.
The absolute numbers do not. They are not a baseline for this repository and are
not cited as one. The SFIR5 controls were re-run under `.venv` and pass there.

### Correction before this entry was committed: this is not a discovery

The paragraph that stood here called this the first occasion `require_isolated`
was invoked and treated the finding as new. Both claims are wrong, and the
ledger already said so.

INC-V2-089's section *The isolated execution environment, and two false-isolation
traps* names this exact condition as trap 2 -- "the bash-PATH `python` resolves
`akc_cir` out of a DIFFERENT clone entirely,
`ai-knowledge-compiler-collection-plane-rehearsal`" -- and records that the
refusals "were exercised, not assumed". The trap was known, the gate was written
for it, and the gate had already caught it once.

So the correct reading is narrower and less flattering: **the repair did not
hold across sessions.** SFIR4's answer was to run from
`D:\CodexProjects\_sfir4_isolated`, a detached worktree with its own venv. This
session did not start there, ran several hundred test invocations from the bare
interpreter, and only noticed when the pre-census gates were run. Nothing
prevented the regression, because the gate protects the census and nothing
protects the sessions around it.

What is genuinely new here is only the scope of what was measured wrongly, and
one gap noted below.

### A gap this exposed in `require_recoverable`

While repairing the environment, `require_recoverable()` returned PASS at a
moment when two of the four modules the SFIR5 charter pins --
`probe_sfir5_capacity.py` and the edited `sfir5_charter.py` -- existed only in
the working tree and in no commit. A pin over bytes git cannot return is
INC-V2-089's failure mode precisely, and the gate written after INC-V2-089 did
not see it, because its scope is the frozen SFIR4 instrument and not a
successor's toolchain.

Both files were committed before the census could seal anything, which changes
no bytes and leaves the pins valid. The gate's scope is recorded here as
narrower than its name suggests.

### The repair

The SFIR5 census runs under `.venv/Scripts/python.exe`, where all three gates
pass. The `.pth` was **not** edited: it belongs to another checkout's
environment, and rewriting a global editable install to make this study's gates
go green would be repairing the measurement rather than the instrument -- and
would silently move whatever that other checkout is doing.

**Standing consequence.** A test figure from this repository is only meaningful
with the interpreter named beside it. Any future full-suite number that does not
say which interpreter produced it should be treated as unmeasured.

**Authority:** the two refusals above; the `.pth` contents; the same three gates
passing under `.venv`; `sys.modules`-level confirmation that `akc_cir.__file__`
pointed outside this tree.

## INC-V2-104 - the capability rule was unenforced, and its guard could not fail

**Class:** INC-V2-036, sixth recurrence -- plus the same class inverted, a guard
placed where the harm it names is impossible.
**Disposition:** A REPAIRED AND MUTATION-PROVEN; B-F RECORDED, four of them
deliberately not fixed.
**GPU seconds:** 0 - **Cost:** $0 (no pod, no provider call) - **IP gate:** CLOSED.

Found by a parallel lane auditing the GPU successor preflight while the SFIR5
census ran.

### A - `G_GSP_CAPABILITY_NOT_INFERRED_FROM_NAME` was true for every input

The constitution says: *never infer capability from a model's name; capability
comes from registry capability evidence or it does not exist.* The gate meant to
enforce it read:

    not identity["capability"]["capability_claimed"]
    or identity["capability"].get("inferred_from_name") is False

`capability_from_registry` returns exactly two shapes. Either
`capability_claimed` is False, satisfying the first disjunct; or it is True on a
branch that sets `inferred_from_name = False` **unconditionally**, satisfying the
second. The gate re-states, one line later, the branch that was just taken.

Measured across an 11-pin probe: **0 of 11 reachable red states.**
`capability_evidence: "trust me"` produced a claimed capability and a green gate.
The only thing actually required was that the pointer string differ from the
repository string.

The tell is general enough to grep for, and it is the sharpest statement of this
defect class the study has: **the guard read a field that the branch producing it
had just set unconditionally.** Five earlier recurrences were harder to see than
this one; that this one survived review says the class is not being looked for
by shape.

A contributing cause: the gate lived as an inline expression inside `run()`,
which the live-cohort guard blocks under pytest -- **no test could reach it.**
The repair extracts `capability_not_inferred_from_name` so the predicate is
reachable, and requires the evidence pointer to be content-addressed by a 64-hex
digest naming the artifact the capability was read from. The live pin still
passes; its pointer already carried one. No protocol file was edited, and
`capability_claimed` keeps its documented meaning, so
`GPU_SUCCESSOR_MODEL_PIN_V1.yaml`'s statement about it stays true.

Mutation-proven, and proven in both directions: reverting the predicate to the
old tautology reddens 6 of 8 controls, while the two that must stay green -- no
claim made, and the real sealed pin -- stay green. A fix that reddened
everything would have proved nothing.

### B - the live-cohort guard is itself misplaced here

`live_cohort_guard`'s docstring says all three guarded tools "expose a `run()`
that reaches out to real roots", and that a stray call "spends real request
budget against real endpoints". For `gpu_successor_preflight` that is **false**,
and checkable in one grep: the module imports no `urllib`, no `socket`, no HTTP
client and no provider backend. It reads local files and does arithmetic.

The premise was taken from the anti-blocker audit's own wording and applied to
three tools without checking it against each. Its cost is not theoretical: the
guard reddens two controls that existed specifically to prove the real tool
blocks, and it made the entire gate-assembly block untestable -- which is how A
survived.

This is the same defect class in the other direction. A is a guard that cannot
fail; B is a guard that cannot be reached past. Both are the result of asserting
a property instead of exercising it.

**What is true** is that `run()` writes immutable receipts and moves a
`receipts/latest` pointer, so calling it from a test does pollute real evidence.
That is a genuine harm, and a different one from the harm the guard names. The
escape hatch for exactly this case already exists and is documented in the
guard's own docstring.

### C - three further vacuous gates, recorded and NOT fixed

- `G_GSP_EXCLUDES_CLOSED_ENDPOINT` compares the module's literals to the
  module's own literals. Repointing it at the protocol would redden a path the
  protocol documents as deliberate: `GPU_SUCCESSOR_STUDY_V1.yaml` declares a
  currency axis and three scorer classes, while the preflight declares a
  representation axis and different ones, and the protocol names that divergence
  under `arms_axis`. **Whether those two axes are meant to be the same is a
  founder question, not an agent's.**
- `G_GSP_CONTEXT_BUDGET_FEASIBLE` compares two module constants. Verified
  correct on the substance -- the prompt budget genuinely is separate from
  generation -- so it is vacuous, not wrong.
- `G_GSP_NO_GPU_YET` is a hardcoded `True`, and says so.

### D - the cost gate prices a run nobody intends

`estimate_cost` is called with `max(floor, eligible_count)` = **20,018**, the
entire universe rather than a sample: 25.62 GPU-h, $64.06, against caps of 6.0 h
and $40. It fails closed, which is why this is a finding and not an incident with
a spend attached. But the receipt's headline figure describes a run that is not
planned, and a launcher reading it would be reading the wrong number. The
underlying throughput (2000 tok/s) and rate ($2.50/h) are `declared_assumption`
and have never been measured.

### E - teardown and output-completeness are ABSENT from the V1 path

Not weak -- absent. `GPU_SUCCESSOR_RUNTIME_V1.yaml` contains no deletion,
termination, watchdog or absence-proof clause at all, and `STUDY_V1` has no
completeness criterion. Both exist in the V2 protocols, which are frozen, and
**the V1 preflight never opens them.** Any claim that the GPU lane has a teardown
guarantee is a claim about V2 made against a preflight that reads V1.

### F - the cohort is one typed-fact kind wearing four labels

20,018 of 20,018 eligible, and the floor of 120 is cleared 166 times over. The
composition is `REFERENCE_TARGET` 19,714 (98.5%), `LANGUAGE` 275,
`APPLICABILITY` 29, `EFFECTIVE_TIME` **0**. Three of the four typed-fact kinds
the successor design names are near-absent and one is empty. A result over this
cohort would be a result about reference targets, whatever the design says it is
about, and a per-kind breakdown cannot be produced for a kind with no instances.

**Authority:** the 11-pin probe and its 0/11 result; the mutation table in both
directions; the absence of any network symbol in `gpu_successor_preflight`; the
two named controls reddened by the guard; the preflight receipt's own cost and
cohort figures; grep returning nothing for teardown terms in
`GPU_SUCCESSOR_RUNTIME_V1.yaml`.

## INC-V2-097 update - cause established: a test moved a real pointer and deleted its target

**Disposition:** CAUSE ESTABLISHED AND REPAIRED. Supersedes the previous
update's "cause of THIS recurrence undetermined".
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

Three occurrences, twice regenerated, cause recorded as unknown both times. It
recurred a fourth time during the SFIR5 census session and was caught in
`git status` rather than by luck:

    receipts/latest/r1-reproducibility-fixture.json
      points_to  r1-reproducibility-fixture--20260827T051827Z-bb56f881f8fa.json
      on disk    NO
      in HEAD    NO

The timestamp fell inside this session, which is what made it findable: the
window contained exactly one full-suite run.

### The cause

`tests/test_part3.py::test_two_subprocess_runs_agree_on_the_semantic_digest_but_not_the_path`.

It runs `tools/reproducibility_fixture.py` twice as a subprocess. That is
correct and deliberate -- the contract under test is that two runs collide on
semantics and not on path, which cannot be exercised against a fake directory.
Each subprocess therefore writes a real immutable receipt, and because
`write_immutable` takes `pointer: bool = True` and the fixture's `main()` never
overrides it, **each run also moves the real `receipts/latest` pointer.**

The test then deleted both receipts and did not restore the pointer. What it
left behind was a pointer naming the second run's receipt, which no longer
existed anywhere.

Not one of the three earlier investigations looked at the test suite, because
the pointer's mtime was read as evidence that a *tool* had written it. A test
that shells out to a tool leaves exactly the same trace as the tool.

### Why this is not a housekeeping defect

A dangling pointer is an authority naming bytes nobody can produce. That is
INC-V2-089's shape, and the reason `receipt_pointer_targets_are_recoverable`
was added as a standing gate covering all 102 pointers. The gate worked; what
was missing was an explanation, and an unexplained recurrence is a defect that
is free to happen again -- which it did, three times.

### The repair

The test now snapshots the pointer's bytes and restores them in a `finally`,
after the unlinks. In `finally` specifically: a failed assertion previously
left the pointer dangling too, which is one of the ways this went unattributed.

A second control asserts, against the real pointer, that the receipt it names is
on disk. The tree-wide gate already checks all 102; this one is local so a
regression is attributed to the test that causes it instead of surfacing later
as an unexplained dangling reference somewhere else.

Mutation-proven: removing the restore turns the local control red
(1 failed, 1 passed) and the pointer is left dangling exactly as observed.

**One correction to the earlier updates.** Both said the cause was not
established, which was honest and is now superseded rather than deleted. Neither
should be read as having been wrong to say so -- what was wrong was investigating
only the tools.

**Authority:** the four dangling states; `write_immutable`'s `pointer=True`
default and `reproducibility_fixture.main()`'s call site; the mutation result;
`git status` clean on that pointer after the repaired test runs.

## INC-V2-105 - two detection tools that under-report what they exist to find

**Class:** an audit whose scope is narrower than its name, and a measurement
whose instrument was wrong about the thing being measured.
**Disposition:** A RECORDED, deliberately not fixed; B REPAIRED AS PRACTICE.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

Both found by the lane closing defect-class-4 findings while the SFIR5 census
ran. Class 4 is "an acceptance-criterion identifier re-spelled as a literal in a
test instead of imported", and it matters because a test carrying its own copy of
an identifier keeps passing after the canonical one is renamed -- it is then a
guard whose failure is impossible, the INC-V2-036 family again.

Nine class-4 findings became six. The three closed are real: mutation MUT-D
(delete E5 from `ENDPOINTS` while `EXECUTOR_BLOCKS` still grades it) turns six
tests from passing-against-a-stale-spelling to failing, and no test moved the
other way.

### A - `anti_blocker_audit` class 4 walks string literals only

The identical defect spelled as a **keyword-argument name** is invisible to it:

    _executor(E5_confirmed_selective_stale_escape=_block(...))

is exactly as stale as the literal form and is not reported. The residual
failures under a block-key-rename mutation land precisely on those sites, which
is how they were found -- by a mutation the audit does not model, not by the
audit.

`tools/score_sfi3.py` itself re-spells three endpoint ids at lines 637-639, so
the tool the tests are told to import from also carries copies.

**Not fixed, and the reason is not cost.** Widening the audit would raise the
finding count on files three other lanes own, mid-flight, during a live census.
More importantly the count is currently read as a progress figure, and a
detector that grows its own denominator halfway through is worse than one that
under-reports consistently. Recorded so the six remaining is understood as
**six of the shapes this audit can see**, not six defects of this kind.

### B - the EOL instrument was wrong about the file it was measuring

`grep -c $'$'` under the Bash tool reported 490 of 553 lines CRLF for a file
that `pathlib.read_bytes()` proves is pure LF. Acting on that reading would have
rewritten both files to CRLF.

That is not a formatting nuisance. This research tree sets `* -text -eol` because
freeze receipts digest **working-tree bytes**, so a whole-file EOL rewrite
silently changes every pinned digest in the tree. The session had already
produced three EOL incidents, one of which reached a commit; this would have been
the fourth and the largest.

**Standing practice, adopted:** EOL counts come from `read_bytes()` and byte
comparison, never from a shell line-ending grep. The repo is genuinely mixed --
`tools/*.py` CRLF, several test modules pure LF -- so "what convention does this
repo use" has no answer and the question is always per file.

### C - the obvious remediation route is closed, by design

`tools/score_sfi3.py` is sha256-pinned in `receipts/frozen-instrument-integrity.json`
at `4b566415...d445b4`. Exporting a new constant to import would break that
digest. So class-4 remediation on frozen modules must **derive** identifiers from
what the module already exports, never add to it. Two tests were deliberately
left pinning policy by stem rather than derivation: an acceptance criterion that
may not be skipped is a statement about the criterion, and deriving it from the
module would make the test agree with whatever the module says -- a tautology
wearing a test's name.

The pin was verified byte-identical after every mutation and at rest.

**Authority:** the MUT-D failure list; the six residual findings and their new
attribution; the literal-versus-keyword blind spot demonstrated by mutation; the
grep/`read_bytes` disagreement on a file with 0 CRLF and 506 LF; the frozen
digest matching before and after.

## INC-V2-106 - the Wikipedia lane has never worked, in any SFIR study

**Class:** an adapter whose every request is rejected by the endpoint, producing
zeros that read as measurements.
**Disposition:** CAUSE ESTABLISHED. The family is recorded as NOT_MEASURED, not
as short of capacity. Not repaired in SFIR5, which is closed.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

Found when SFIR5 became the first census in the programme to complete. Wikipedia
returned 0 candidates from 30 roots, 29 of them filed
`TRUNCATED_OR_INCOMPLETE_ENUMERATION`, on only 60 requests -- exactly two per
root.

The sealed response ledger shows the shape without any new traffic. Per root:

    list=categorymembers&cmtitle=Category:Astronomy&cmlimit=500   3222 bytes, 200
    pageids=<50 ids>&prop=revisions|info|redirects&rvlimit=2       611 bytes, 200

611 bytes for fifty page ids, and 611 bytes again for twenty-five. A response
size independent of how much was asked for is an error envelope, not data.

One diagnostic request to the endpoint -- two page ids, no cohort read, no
candidate counted -- returned it verbatim:

    "code": "invalidparammix",
    "info": "\"titles\", \"pageids\" or a generator was used to supply multiple
             pages, but the \"rvlimit\" ... parameters may only be used on a
             single page."

The adapter batches 50 page ids **and** sets `rvlimit=2`. MediaWiki refuses that
combination outright. Every revision request in every SFIR census has therefore
failed, `seen_batch != set(batch)` on every root, and **no Wikipedia candidate
has ever been produced by this programme.**

### Why it was invisible for four studies

SFIR1, SFIR2 and SFIR3 stopped before reaching the family. SFIR4 reached it and
died on rate limits (INC-V2-101) before completing. The lane has been carried
through four instruments without once running to the point where its output
could be looked at. A defect that is upstream of every previous stop is a defect
no previous stop could reveal.

### The correction this forces on INC-V2-101

That entry's own correction section examined `revision_batch_size: 50` and used
it to show the frame needed roughly 90 requests, not 3,000. The arithmetic was
right -- 60 requests were actually issued. The inference drawn from it was not.
It treated the batching as evidence that the instrument was sound and merely
needed pacing. The batch size that made the volume tractable is the same
parameter that makes every request invalid.

So INC-V2-101 now has **three** wrong answers preserved rather than two: the
User-Agent A/B, the volume estimate, and this. All three stay.

### The correction this forces on SFIR5's own charter

SFIR5's `batching_policy` declares `new_batching_introduced_by_sfir5: false` and
`require_batching_unchanged` verifies the declared sizes against the frozen
adapter's. That gate passed, and it was doing exactly what it was written to do:
proving SFIR5 batches identically to SFIR4.

It is worth stating plainly what that gate is therefore worth. **Semantic
equivalence to a predecessor is not correctness.** The gate could only ever have
established that the successor inherited the predecessor's behaviour, and the
predecessor's behaviour was an error on every request. A check that compares a
successor to an ancestor cannot find a defect they share, and this study now has
a measured instance of that.

### Why the zero is not reported as a capacity result

`sfir5-capacity-outcome.json` records this family as
`NOT_MEASURED_INSTRUMENT_DEFECT` and states that nothing establishes its capacity
in either direction. Filing it as C=0 alongside `git_docs`'s C=293 would present
a broken instrument's silence as a measured absence -- and it would make the
capacity criterion look like it had been evaluated on three families when it was
evaluated on two.

**Authority:** the 60 ledger observations and their constant 611-byte size; the
`invalidparammix` response; 29 of 30 roots at
`TRUNCATED_OR_INCOMPLETE_ENUMERATION`; the `seen_batch != set(batch)` branch in
`probe_sfir3_capacity`.


## INC-V2-107 - the capacity seal could not have accepted any census

**Class:** producer and consumer of one block disagreed, and the consumer had
never run.
**Disposition:** CAUSE ESTABLISHED; the frozen module was NOT edited. Proven not
to change SFIR5's outcome.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

`seal_capacity` refused SFIR5's completed census with
`encyclopedia_wikipedia pagination proof drifted` -- before reaching any capacity
arithmetic at all.

The cause is a defect introduced by this study's own INC-V2-098 repair. That
repair added `retries_total` and `transport_retries` to the pagination block
`probe_capacity` writes, so a reader could tell a census that lost connections
from one that was throttled. `seal_capacity` compares that block with **strict
set equality** against `CAPACITY_PAGINATION_FIELDS`, which was not updated.

    expected: cap_reached, exhausted, rate_limit_retries,
              rate_limit_wait_seconds, roots_processed
    written : the same five, plus retries_total, transport_retries

So the seal would have refused **every** census, for **every** family, whatever
the data said. The instrument could not have produced a capacity authority even
from a perfect run.

It survived because no census had ever completed. All four SFIR4 runs died
upstream, so this path had never been exercised against real output -- the same
shape as INC-V2-092 and INC-V2-103, where a check with no reachable call site
protects nothing.

### It does not change SFIR5's outcome, and that was run rather than argued

The field set was corrected **in memory only** and `seal_capacity` re-run against
the same sealed census. The refusal became `encyclopedia_wikipedia capacity
shortfall`. The module on disk was not edited, and `git diff` confirms it.

That matters because the defect would otherwise be a convenient explanation for
the failure. It is not the explanation: with it corrected, the criterion is
reached and is not met.

**Why the module was not repaired here.** `sfir4_protocol.py` is pinned in the
charter freeze the census ran under. Editing it now would mean sealing SFIR5's
result against a toolchain SFIR5 did not use -- and `seal_capacity` does not
verify that the census it is handed was produced by the charter it is given,
which is a second finding worth recording on its own. The repair belongs to the
successor, before its census, not to a study whose census is already sealed.

**Authority:** the refusal string; the field-set comparison above; the in-memory
correction producing a different refusal; `git diff` clean on
`tools/sfir4_protocol.py`.


## INC-V2-108 - the same silent-error class in the git and eCFR adapters, registered before SFIR6's census returned

**Class:** INC-V2-106 generalised. A hostile audit of the two families the
Wikipedia incident did not touch.
**Disposition:** FOUR DEFECTS CONFIRMED LIVE, ONE REPORTED DEFECT REFUTED,
MAGNITUDE MEASURED ON SFIR5. SFIR6's frozen charter is NOT amended.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

INC-V2-106 was a Wikipedia defect with a general shape: transport success
(bytes arrived) is not protocol success (the API said yes) is not semantic
completeness (we got what we asked for). This entry records what that lens
found when turned on `git_docs` and `regulation_ecfr`.

**This entry is written while the SFIR6 census is still running and no SFIR6
number exists.** That ordering is the point. A limitation registered after a
disappointing result is indistinguishable from an excuse for it; the same
limitation registered before the result cannot be one.

### Confirmed live

- **eCFR files an HTTP 404/409/451 as a corpus zero.** `probe_sfir3_capacity`
  returns `_zero(...)`, i.e. `ZERO_CANDIDATE_ROOT_DISPOSITION`, for a root the
  server refused. The identical status in `git_docs` returns
  `UNAVAILABLE_ROOT_DISPOSITION`. One census, one HTTP status, two incompatible
  meanings - and the correct state already exists in the seal's allowed set.
- **eCFR files an unfinishable enumeration as a corpus zero.** Five distinct
  instrument failures - page bound, byte bound, `meta` drift between pages,
  `rows_seen != result_count`, and two crawls disagreeing - all reach the same
  `ZERO_CANDIDATE`. The reason strings distinguish them; the state does not, and
  the state is what the arithmetic reads. This is INC-V2-106's exact shape.
- **A git doc path whose commit history returns `[]` disappears uncounted.**
  GitHub answers HTTP 200 `[]` for a path filter that matched nothing - captured
  live at `/repos/pypa/setuptools/commits?path=NO_SUCH_PATH_zzz.md`. A path read
  out of the HEAD tree in the same census cannot honestly have zero commits, so
  `[]` there is the API refusing the filter. It is dropped by the same
  `len(commits) < 2: continue` as a genuine single-commit file, and no proof
  field records it. **A root where every path answered `[]` would seal as
  `COMPLETE` with zero candidates** - the same false zero as INC-V2-106,
  arriving through `COMPLETE` instead of through `ZERO_CANDIDATE`.
- **Repository identity is never verified.** `_git` accepts the metadata body if
  it merely carries a string `default_branch`; `full_name` is never compared to
  the repository asked for. Captured live: `GET /repos/facebook/jest` returns
  HTTP 200 from `/repositories/15062869` with `full_name: jestjs/jest`. urllib
  follows GitHub's rename 301 silently. Candidates would be attributed to a
  `discovery_root_id` and `payload_ref` naming a repository that does not hold
  them, and `assert_static_disjointness` - which compares declared names while
  the census reads redirect targets - could not see it.

**A fourth gate follows from the last one:** *identity success - the thing that
answered is the thing we asked for.* Transport, protocol and semantic
completeness can all pass on a response from the wrong resource.

### Refuted: the response ledger does cover all three families

The audit reported that only `git_docs` reaches the ledger, because
`probe_sfir4_capacity.py:392` is the sole call site of `_observe` and eCFR and
Wikipedia go through `legacy_fetch` directly to `_http_json`. That is true of
**SFIR4's probe** and false of **the transport that executed SFIR5 and is
executing SFIR6**. `PacedObservingTransport.__init__` replaces the legacy
closure with one whose body is `return self._observe(family, root_id, url)`.

That is not an argument, it is in the receipt.
`receipts/sfir5-capacity-census-seal.json` records
`families_in_ledger: [encyclopedia_wikipedia, git_docs, regulation_ecfr]` and
`per_host_requests: {api.github.com: 1879, en.wikipedia.org: 60,
www.ecfr.gov: 1011}`. Had eCFR bypassed the ledger, its 1,011 requests would
have left no rows and `require_family_coverage` would have refused the census.

The finding was reasoned from the frozen module without reading the subclass that
overrides it. **An audit of an inherited module is not an audit of the code that
runs** - the mirror image of INC-V2-036, and worth keeping next to it.

### Magnitude, measured rather than assumed

Counted over the 100 root dispositions in SFIR5's sealed census:

| family | COMPLETE | EXCLUDED_INCOMPLETE | ZERO_CANDIDATE |
|---|---|---|---|
| `regulation_ecfr` | 49 | 0 | 1 (`EMPTY_ENUMERATION_NO_VERSIONS`) |
| `git_docs` | 13 | 7 | 0 |
| `encyclopedia_wikipedia` | 1 | 0 | 29 (`TRUNCATED_OR_INCOMPLETE_ENUMERATION`) |

The eCFR conflation **never fired**. Its single zero carries the one reason that
genuinely means an empty corpus, and no root took a refused-or-truncated path.
eCFR's 859 is not contaminated by these defects. `git_docs` used
`EXCLUDED_INCOMPLETE` correctly for all seven bounded roots; its exposure is the
uncounted `[]` history and the unverified identity, neither of which leaves a
trace in a receipt - which is exactly why they need counters rather than
reasoning.

**Direction of bias.** Filing a failure as a zero can only lower a capacity
count, never raise it. So these defects cannot inflate a passing family, and a
family that passes despite them has passed. They bound a *shortfall*, and only a
shortfall. The identity defect is the exception: it is a misattribution, not a
count error, and it can move candidates between roots in either direction.

### Why SFIR6 is not amended

SFIR6 is frozen with `repairs: [INC-V2-106, INC-V2-107]` and is executing. These
defects are unconditional and were found before its result existed, so amending
it now would not be outcome-conditioned - but it would still be an edit to a
sealed charter during the census it authorises, and a freeze that can be widened
mid-run is not a freeze. SFIR6 reports under its declared scope, with this entry
as its named limitation.

**Authority:** `probe_sfir3_capacity._zero` call sites; `probe_sfir4_capacity`
`len(commits) < 2: continue` and the metadata acceptance branch; the live
`facebook/jest` and `pypa/setuptools` responses; `sfir5_transport.py:147-157`;
`receipts/sfir5-capacity-census-seal.json`; the disposition counts above.


## INC-V2-109 - alias identity case-folds MediaWiki titles, which are case-sensitive

**Class:** an identity normalisation that merges two distinct real-world things.
**Disposition:** CAUSE ESTABLISHED AND VERIFIED LIVE. NOT REPAIRED - identity
semantics are frozen for SFIR6 and `akc_cir.identity` is Protected Core.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

SFIR6's capacity seal refused `encyclopedia_wikipedia` with

    DOCUMENT namespace collision on 'wiki:en:title:cd8+':
    claimed by alias_ids and again by alias_ids

Four aliases out of 9,887 collide across the 2,152 candidates. All four have the
same single cause, confirmed against the live API rather than inferred:

| collapsed alias | one page | the other page |
|---|---|---|
| `cd8+` | `CD8+` -> Cytotoxic T cell (211947) | `Cd8+` -> CD8 (2305842) |
| `emergency surgery` | `Emergency Surgery` -> Surgery (45599) | `Emergency surgery` -> Elective surgery (12712661) |
| `communication systems` | `Communication Systems` -> Telecommunications | `Communication systems` -> Communications system |
| `telecommunication systems` | `Telecommunication Systems` -> Communications system | `Telecommunication systems` -> Telecommunications |

**MediaWiki titles are case-sensitive after the first character.** `CD8+` and
`Cd8+` are two different redirect pages pointing at two different articles.
TAVONEL's alias identity case-folds the whole title and merges them, so one
identity is claimed by two lineages and the identity proof fails closed.

Resolving `CD8+` through the API returns exactly one target
(`{"from": "CD8+", "to": "Cytotoxic T cell"}`), which is the point: each redirect
is unambiguous in the source, and the ambiguity is manufactured by the
normalisation.

**This is our defect, not the corpus's and not the adapter's.** The fetch is
sound - every batch returned `batchcomplete`, no continuation, no warnings.

### Why it was not repaired here

Three independent reasons, any one sufficient. The SFIR6 charter freezes
`identity_semantics: unchanged`. `akc_cir.identity` is Protected Core and cannot
be changed without a same-condition no-regression benchmark. And the outcome was
already known when this surfaced - changing an identity rule at that point is
outcome-conditioned by construction, whatever its merits.

The failure is also **correct behaviour**: an authoritative conflict on
insufficient evidence must not be auto-resolved, and it was not.

### Why four studies did not find it

It was unreachable. `encyclopedia_wikipedia` had never produced a candidate -
INC-V2-106 meant every revision request was rejected, so the identity proof had
no Wikipedia input to run on. **Repairing one instrument exposed a defect in a
different layer**, which is the ordinary way a first measurement pays for itself.
`git_docs` and `regulation_ecfr` aliases evidently do not collide under
case-folding; that is a property of those corpora, not evidence the rule is safe.

**Authority:** the seal's refusal string; the four collisions in
`receipts/sfir6-capacity-metadata-census.json`; the six live API responses above,
each with `batchcomplete: true` and no continuation.


## INC-V2-110 - the disposition field set is INC-V2-107's defect a third time

**Class:** strict set equality over a field set that a legitimate change grows.
**Disposition:** IDENTIFIED, NOT LOAD-BEARING for SFIR6's verdict.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

`seal_capacity` compares each root disposition against
`CAPACITY_DISPOSITION_FIELDS`, permitting `traversal_proof` **only** for
`git_docs`. SFIR6's repaired Wikipedia adapter emits a traversal proof for every
root, so the seal refuses with `encyclopedia_wikipedia root disposition fields
drifted` - because the census carries **more** evidence than the schema allows.

That is the same shape as INC-V2-107 and, counting the pagination block, the
third instance in one module. The generalisation worth keeping: **a schema that
compares an evidence block by strict set equality punishes any successor that
produces better evidence.** Additive evidence and schema drift are not
distinguishable to `!=`, and the study that adds a counter is the one that pays.

It is recorded rather than repaired because it is not load-bearing here. Removing
the extra proof to satisfy the frozen contract lets the seal proceed - and it
then refuses on INC-V2-109 instead, which is a finding about the data and not
about the schema. The field-set gate therefore stands between the census and
nothing; `git_docs`'s 293 decides the verdict either way.


## INC-V2-111 - a procedural slip of my own: counts read before the seal ran

**Class:** result-blindness given up when it did not have to be.
**Disposition:** RECORDED. No artifact is affected.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

After the census completed I counted candidates per family directly from
`receipts/sfir6-capacity-metadata-census.json` **before** invoking the seal. The
seal is the instrument that produces the verdict; reading the raw counts first
was unnecessary and meant that when the seal then refused twice - once on
INC-V2-110, once on INC-V2-109 - I was already holding the outcome.

Nothing was changed to suit it, and the two refusals were handled as findings
rather than as obstacles: identity semantics were not touched, no threshold
moved, no root was added. INC-V2-110's proof is that removing the extra evidence
reaches the same place, and the verdict rests on `git_docs = 293`, which
reproduces SFIR5's number **and its exact lineage set**.

But "it did not change anything" is a weaker guarantee than "it could not have",
and the second is the one the design is supposed to provide. The rule for the
successor: **run the seal first, read the census afterwards.** The seal is
blind; a person reading a census is not.


## INC-V2-112 - a control that could never go green, and three gates that could never go red

**Class:** INC-V2-036, both faces of it, in the GPU successor preflight.
**Disposition:** CONTROL REPAIRED AND MUTATION-PROVEN; THREE GATES BOUND TO WHAT
THEY NAME. Two findings referred to the founder, not decided here.
**GPU seconds:** 0 - **Cost:** $0 - **IP gate:** CLOSED.

### The control that was red for the life of the repair it was meant to watch

`tests/test_live_cohort_guard.py` was **failing at HEAD**, and had been since
INC-V2-104 B:

    FAILED test_each_named_tool_refuses_its_own_run_under_pytest[gpu_successor_preflight]
    FAILED test_the_refusal_is_the_first_thing_run_does[gpu_successor_preflight]

INC-V2-104 B moved the live-cohort guard off `run()` -- which opens no socket and
writes nothing -- and onto `main()`, which seals a receipt. That was the right
move. Both controls kept naming `run()`, so from the moment the repair landed
they asserted something that was deliberately no longer true.

**A control that can never go green distinguishes nothing, exactly like one that
can never go red.** INC-V2-036 has been recorded seven times as a guard whose
failure is impossible; this is the same defect with the sign flipped, and it is
worth naming because it hides differently. A vacuous guard hides in a green
suite. This one sat in a red one, where a standing failure becomes scenery.

Repaired by pointing both at `GUARDED_ENTRY` -- `main` for the preflight, `run`
for the other two tools -- and adding a control that pins the other half of
INC-V2-104 B: `run` is *deliberately* unguarded. Both directions are
mutation-proven: removing the guard from `main` reddens the suite, and putting it
back on `run` reddens it harder.

### Three gates that were true for every input

| gate | what it compared | now |
|---|---|---|
| `G_GSP_NO_GPU_YET` | nothing - a hardcoded `True` | reads the module's own AST and refuses a forbidden import root |
| `G_GSP_CONTEXT_BUDGET_FEASIBLE` | two constants in one file | also requires equality with `context_builder.TOTAL_PROMPT_TOKENS` |
| `G_GSP_TOKENIZER_PARITY_BATTERY_AVAILABLE` | `battery_digest()` with itself | compares against the digest attested inside the sealed pin receipt |

The third is the sharpest: a pure function agrees with itself for every possible
battery, so the gate was green whatever the battery contained. It now compares
against bytes that a *different* gate already proves sealed, which means the
evidence comes from outside the thing being checked.

`G_GSP_NO_GPU_YET` reads the AST rather than grepping, because the module's own
docstring discusses sockets and HTTP clients in prose and a grep would go red for
the wrong reason -- the INC-V2-105 lesson applied before it could recur.

**No threshold moved.** `COHORT_FLOOR` 120, `CAP_GPU_HOURS` 6.0, `CAP_USD` 40.0,
`CONTEXT_BUDGET_TOKENS` 4096, all unchanged. 25 mutations, 25 killed, zero
survivors, against 346 passing controls.

### One gate left vacuous on purpose

`G_GSP_EXCLUDES_CLOSED_ENDPOINT` compares this module's literals with this
module's literals and cannot be reddened by any input. It is left that way:
INC-V2-104 C records that repointing it at the study protocol would redden a
divergence the protocol documents as deliberate under `arms_axis`, which is a
founder question. It is not silently unguarded - a control binds
`FORBIDDEN_SCORER_CLASSES` to the real `endpoint/value_scorer.CLASSES`, so drift
is caught even though the gate cannot see it.

### Two findings for the founder, not decided here

**The default cohort comes from a study that is frozen, FAIL and spent.** The
preflight's default manifest `artifacts/development/typed_fact_cohort.json`
clears the floor 166 times over, and its own header names
`artifacts/sfi2/sfi2_acquisition.json` as its source. SFI2 is spent. SFIR6 froze
no roster and spent no corpus, so **nothing in the programme has produced a
cohort for this study**. The green on that gate is a green over development
material from a dead study. Whether development material may back a GPU study is
not an agent's call.

**`cohort_feasibility` binds the manifest to nothing.** Demonstrated: a JSON file
containing only a `facts` list -- no schema, no study id, no acquisition
provenance -- returns `feasible = True`. INC-V2-104 called this "the check the
three closed preflights teach loudest". Defining what makes a cohort manifest
legitimate is a protocol change, so it is recorded rather than written. The hole
is in this gate alone: the four-link gate does bind the launch manifest to an
acceptance receipt by sha256.

### Standing, unchanged from INC-V2-104

The cost gate still prices `max(floor, eligible)` = 20,018 facts at 25.6 GPU-hours
and $64.06 against caps of 6.0 and $40 - a run nobody intends. It fails closed,
but the receipt's headline number describes the wrong run. `EFFECTIVE_TIME`
remains 0 of four typed-fact kinds.

Current verdict on the tool's own defaults: **BLOCKED** on seven gates. No
receipt was written, no corpus spent, no roster frozen, no payload opened.

**Authority:** the two named failures reproduced at HEAD by stashing this
session's tree and re-running; the 25-mutation table with zero survivors; the
bare-`facts` manifest returning `feasible = True`; the manifest header naming
SFI2; `receipts/` carrying no SFI3 acceptance, no four-link acceptance and no
protocol bundle-freeze.

## INC-V2-113

**A unit test of a guard is not a test that the guard is wired in.**

Recorded 2026-08-27, while building SFIR7's streaming selection driver. Found by
mutation, not by review.

`stream_select` calls `_require_distinct_keys(ordered, rule)` before returning,
which refuses a roster containing two roots the declared ranking cannot separate.
The suite had a test for `_require_distinct_keys`: it built two identical records,
called the function directly, and required `SelectionRefused`. Green, and correct.

Deleting the call from `stream_select` left all eighteen tests green.

The function worked. Nothing tested that anything used it. Every property the
guard protects was asserted one level below the place the guard actually sits,
so removing the guard removed nothing any control could see. This is INC-V2-036's
shape for the ninth time -- a guard whose failure the suite has made impossible --
but the mechanism is new enough to name separately: **the guard is real and the
call site is untested.** A unit test proves capability; only a test that drives
the caller proves the capability is reachable.

Repaired by adding `test_a_duplicated_catalogue_row_refuses_the_whole_selection`,
which writes a fixture catalogue containing one record id twice at equal rank and
requires `stream_select` itself to refuse. The unit test was kept -- it localises
the failure -- but it is no longer the only thing standing there. With both, the
deletion goes red.

**Rule taken forward:** for every fail-closed guard, one control at the function
and one control through the caller. Where a guard is invoked from several places,
the caller-level control goes on the path that actually runs in production.

Fifteen mutations over the driver, zero survivors after the repair. Before it,
one.

## INC-V2-114

**A rule that dies on the real universe is not a rule that was tested.**

Recorded 2026-08-27, on the first full selection pass over the Libraries.io
Repositories table.

The frame rule compares two dates: `created_utc on_or_before` a cutoff and
`last_activity_utc on_or_after` another. 129 tests passed over fixtures whose
timestamps were always well-formed, because the fixture row was written by hand
from a real-looking example. The deposit is not like that. Somewhere in the 37.7
million rows sits a repository whose `Last pushed Timestamp` is the empty string,
and `frame._as_date` refuses it -- correctly, loudly, and fatally, taking the
whole selection with it after several minutes of streaming.

Two things were wrong, and only one of them was the blank cell.

The first: the parser admitted a row that could not answer a question the
declared rule asks. It already refuses `NO_PUBLISHED_RANK` on exactly that
principle -- the rank is the field the rule orders on, so a row without one is
dropped and counted. The two date fields are equally load-bearing and had no such
refusal. Repaired with four reasons: `NO_CREATED_TIMESTAMP`,
`NO_LAST_ACTIVITY_TIMESTAMP`, `CREATED_TIMESTAMP_NOT_A_DATE`,
`LAST_ACTIVITY_TIMESTAMP_NOT_A_DATE`. A refused row is tallied and attributable
by host like every other unusable row, so the cost of the repair is *published*
rather than absorbed.

The second, and the more interesting one: the parser's notion of a readable date
and the evaluator's were two separate pieces of code with no binding between
them. Fixing the first without the second would leave a class of rows the parser
admits and the evaluator dies on -- the same defect, moved. So
`test_the_parser_accepts_exactly_what_the_frame_can_read` runs nine values
through both and requires the same answer from each. If either side's date
handling moves, that test goes red rather than a future run dying at minute
seven.

**Direction of bias, registered before the count exists.** Refusing a row can
only lower the number of eligible repositories. It cannot raise it. The change
was made with no capacity or yield figure in hand: the projection audit
deliberately computes none, and the selection that would have produced one had
not completed. The eligible count was unknown when this was decided and is
unknown as this is written.

**Cost:** the projection-audit receipt was invalidated -- its `rows_parsed` and
rejection tallies describe the old parser -- and is being regenerated over the
full 10.17 GB member rather than edited. A receipt that describes code which no
longer exists is worse than no receipt.

**What this says about the 129 green tests.** They were not wrong. They were
written against fixtures, and a fixture is a hypothesis about the data. The
hostile-test discipline this programme uses generates adversarial *structure* --
extra slashes, swapped columns, dropped identifiers -- and it did not generate an
adversarial *value*, because the value came from a row somebody had seen. Tests
green is not the universe read.

## INC-V2-115

**A second inherited request cap, tighter than the one N was derived from, and
specific to the only family SFIR7 traverses.**

Registered 2026-08-27, before the roster was frozen, before any SFIR7 census ran,
and before any SFIR7 eligible or capacity count existed. Nothing about SFIR7's
outcome was known when this was written and nothing is known as it stands.

**The finding.** N was derived by founder ruling as

    N = floor( min(wall_clock_hours * published_rate_limit, inherited_total_request_cap)
               / per_root_request_bound )
      = floor( min(6 * 5000, 12000) / 240 ) = 50

The `inherited_total_request_cap` term was bound to `sfir5_transport.MAX_TOTAL_REQUESTS`
= 12,000, which is the cap across **all three families**. There is a second
inherited cap, frozen in SFIR4 and never repealed:

    acquisition/sources_sfir4.MAX_GIT_API_REQUESTS_GLOBAL = 4800

It is not decorative. `probe_sfir4_capacity` refuses a Git fetch once the global
counter reaches it, and `sfir4_protocol` refuses a seal whose arithmetic proof
reports a global count above it. SFIR7 traverses Git and nothing else, so this is
the cap that actually binds, and it is tighter by a factor of 2.5.

Under the same formula with the tighter term:

    floor( min(6 * 5000, 12000, 4800) / 240 ) = 20

**What is measured, and what that does and does not license.** SFIR6's Git census
over 20 roots consumed 1,879 requests -- per root 23 at the lowest, 160 at the
highest, 94 on average, with the global counter reaching 2,043. Extrapolated at
the mean, 50 roots need roughly 4,700 and would just fit; at the observed maximum
they need 8,000 and would not. So whether 50 roots fit under the inherited Git cap
depends on which repositories the catalogue selects, which is not knowable before
the roster is frozen.

**That extrapolation is explicitly not a derivation of N.** Sizing a frame from
measured per-root consumption would make N a function of prior results, which is
the move this protocol forbids by name. The theoretical bound frozen in SFIR4 --
240 requests per root -- is the outcome-independent figure, and it is the one the
formula uses. The measurement is recorded here as a magnitude, in the same way
INC-V2-108 recorded the magnitude of defects before SFIR6 returned.

**What was done about it: nothing to N.** N = 50 is a founder ruling of
2026-08-27, frozen by name, and the standing instruction is that SFIR7's roots,
threshold and N are not readjusted. Lowering N to 20 would be the tightening
direction and would be defensible on the founder's own stated principle, but it
is still a change to a number the founder froze, and that is not an
implementation decision. It is reported rather than taken.

**What the census will therefore do.** Fifty roots are frozen and visited in
frozen order. If the inherited global Git cap is reached, `GitRequestBoundExceeded`
excludes the remaining roots as INCOMPLETE -- a defined, tested disposition that
already exists for exactly this case, not a crash and not a silent stop. A root
excluded by a bound is never recorded as a root with zero candidates: SFIR4's
comment on that distinction predates this study.

**Direction of bias.** Any root excluded by the cap can only lower the measured
capacity. It cannot raise it. So if SFIR7's Git capacity clears its criterion
despite bound exclusions, the finding is sound and the exclusions cost nothing; if
it falls short, the shortfall is not attributable to the frame being too small,
because the frame was cut by a bound frozen two studies earlier and not by
anything chosen here.

**Why this was not caught earlier.** `refuse_count_tuned_rule` checks that N's
declared inputs equal the live inherited bounds -- and it checks the four inputs
the derivation names. A bound the derivation never names cannot fail that check.
The guard is sound over its own inputs and blind outside them, which is a smaller
and more ordinary relative of INC-V2-036: not a guard whose failure is impossible,
but a guard whose *scope* was set by the thing it was meant to constrain.

## INC-V2-114 -- update: the measured cost of the date refusal

The regenerated projection audit over the full 10.17 GB member, 2026-08-27:

    rows read                 37,702,060
    rows parsed               36,519,358
    rows rejected              1,182,702
      NAME_WITH_OWNER...          39,401
      NO_LAST_ACTIVITY_TIMESTAMP 1,143,301
      NO_CREATED_TIMESTAMP             0
      *_NOT_A_DATE                     0

3.03% of the deposit carries no `Last pushed Timestamp`. Every unreadable
timestamp is a *blank* one -- not a single malformed or out-of-range date in 37.7
million rows -- which reads as Libraries.io recording an absent value rather than
a corrupt one, most plausibly a repository never pushed to.

**Where the loss falls is the part worth publishing.** By host:

    GitLab       838,988 rejected of   864,563  (97.0%)
    Bitbucket    269,930 rejected of   269,931  (99.9997%)
    GitHub        73,784 rejected of 36,567,566 (0.20%)

The refusal lands almost entirely on the two hosts the frame rule excludes by its
first predicate. GitHub -- the only host SFIR7 addresses -- loses one row in five
hundred.

That is a convenient result and it is stated with the discomfort that deserves.
The rule was written before this was measured; the parser refusal was written
before this was measured; both were chosen on the principle that a row which
cannot answer a declared question is dropped and counted. Had the split gone the
other way -- had GitHub been the host missing its timestamps -- the same refusal
would stand and the cost would be published in the same place. A rule that only
survives when the number is flattering is not a rule.

The recomputed licence coverage moves by the same small margin: MIT 3,062,669 ->
3,062,224, Apache-2.0 857,997 -> 857,827, GPL-3.0 654,162 -> 653,935. Every
declared licence is still present, and record ids remain unique (36,519,358
distinct, zero duplicates, strictly increasing), which is what the strict total
order rests on.

## SFIR7 ROSTER FROZEN -- 2026-08-27

`receipts/sfir7-roster-freeze.json`, state `ROSTER_FROZEN`.

    universe        Libraries.io Open Data 1.6.0, 2020-01-12
                    DOI 10.5281/zenodo.3626071
    archive         sha256:9b5c8bbebdd3bfb20638ca9ebf195be327ebef5a609a1771730cc3e5f7aec9f0
    member          sha256:148c71eb47f5990f1b5270e681df3e3e2ae34c2586ea8f9fabbe2b45a115fcfb
    rows parsed     36,519,358
    eligible        65,174
    N               50
    roster          sha256:e328ec8fb910c62a9af0bc8e5868976d9872bf3efaa050cd62adda1b4f9c34df
    sidecar         sha256:5d910f373e0430802ffd6d1...

Dispositions, first failing predicate in declared order:

    ELIGIBLE                                   65,174
    REJECTED_spdx_license_id_in            31,164,781
    REJECTED_last_activity_utc_on_or_after  3,038,235
    REJECTED_created_utc_on_or_before       2,225,592
    REJECTED_host_eq                           25,576

The licence predicate does most of the work, which is what an allow-list of ten
families does to a catalogue where the great majority of rows declare no licence
at all.

**Zero overlap with the twenty Git roots SFIR1-SFIR4 used.** SFIR7 deliberately
does not exclude them -- excluding them would be TAVONEL curating an external
universe again -- so this is a diagnostic and was never an input. The external
rule simply did not reselect any of them.

**The tie-break is lexicographic over the catalogue's record id as written, not
numeric.** At rank 24 the roster runs 10160, 126181, 129764, 148300, 15838, and
so on. That is `record_id` compared as a string, which is what the declared rule
says and what makes the order reproducible from the bytes. Reading it as numeric
order would be reading it wrong.

**Composition, registered as a limitation before the census, not after.**
`receipts/sfir7-frame-composition.json`, SFIR7-L1 and SFIR7-L2.

    JavaScript 35, TypeScript 5, Ruby 4, Java 2, C++ 1, PHP 1, C 1, CoffeeScript 1
    MIT 40, Apache-2.0 5, BSD-3-Clause 3, ISC 2

Six of the ten declared licence families do not appear at all: BSD-2-Clause,
MPL-2.0, GPL-2.0, GPL-3.0, LGPL-2.1, LGPL-3.0.

Seventy per cent of the roster is JavaScript because Libraries.io's SourceRank is
computed over a catalogue whose package managers are overwhelmingly npm. This is
**not repaired**, and the reason is worth stating precisely: balancing by language
or adding a per-licence floor would be a TAVONEL judgement about which
repositories deserve to be in the universe, applied on top of an external ordinal
chosen so that no such judgement is made. A stratified frame is a defensible
design. It is a *different* design, and adopting one now -- roster in hand,
census unrun -- would mean choosing a frame while able to guess at its yield.

What it threatens is external validity: a capacity result over this roster speaks
to repositories like these and not to open-source documentation at large. It does
not threaten internal validity. The rule is declared, deterministic, and
reproducible from the pinned digest by anyone who downloads the same deposit.

The freeze chain binds eight modules, three receipts and the charter, plus the
member digest recomputed from the file on disk. No census has started, no corpus
is spent, no payload has been opened.

## INC-V2-116

**A number was allocated and never written, and the gap was closed by
recording it rather than by renumbering.**

The coherence check reads the ledger's headings and reports any gap in the
declared numbering, on the reasoning that a missing number is usually a lost
entry rather than a deliberate skip. It was right to report this one: nothing
was ever written as INC-V2-116, and nothing anywhere in the repository or in
git history refers to it.

Renumbering 117 and everything after it would have closed the gap too, and
would have been the wrong repair. Those numbers are cited from other ledger
entries, from commit messages and from receipts; the identifiers are the only
thing making those citations resolvable. A gap is cheap. A citation that
silently now points at a different incident is not.

So the number stays spent, and this entry is what it was spent on. The
alternative repair -- teaching the checker to accept gaps -- was available and
was not taken, because the check would then have stopped reporting the case it
exists for.

**Status:** closed. The gap is recorded, not reconciled away.

## INC-V2-117

**The census spent its whole budget and then died writing the receipt, because
the receipt path had never once been executed.**

2026-08-27. SFIR7's first live census traversed the frozen roots, and on the last
statement of the function raised:

    AttributeError: module 'evidence' has no attribute 'ResponseLedger'

`import evidence` bound `tools/evidence.py`. The module wanted was
`sfir4_response_evidence`, which is what `probe_sfir4_capacity` imports *under
the alias* `evidence`, and the alias is what made the mistake invisible to a
reader copying the surrounding idiom. Two modules, one name, and the wrong one
had no ledger class.

No census was written. Nothing was sealed. No corpus was marked spent. The
identity authority is untouched. What was lost is a run.

**Why no test caught it.** `census` calls `live_cohort_guard.refuse_under_test`
at its head, so nothing in the suite can reach its body, and the receipt assembly
sat at its tail behind fifty live HTTP traversals. Twenty-one controls covered
the loop's pieces. Zero executed the statement that failed. This is INC-V2-113's
class -- a guard, or here a whole step, whose call site no control can reach --
but with the cost inverted: INC-V2-113 cost a mutation-testing round, this cost a
census.

**The repair is an ordering rule, not a fixed import.** Fixing the import alone
would leave the next unexecuted statement in exactly the same position.
`preflight_receipt_path` now assembles the real body with the real writer against
a real destination *before the first request leaves the machine*, into a
temporary directory it then removes. An unresolvable import, a schema violation,
a missing directory or a full disk now costs one temporary file instead of a
whole budget.

**Cheap before expensive.** Whatever the expensive, irreversible step is, every
step that runs *after* it and can fail should be run once *before* it against
throwaway inputs. That is the rule taken forward, and it is more general than
this incident.

**The third occurrence in one session of the same untested-call-site pattern.**
Deleting `preflight_receipt_path(destination)` from `census` left all twenty-seven
controls green -- the repair for INC-V2-117 acquired INC-V2-113's defect
immediately. So the control added for it is an *ordering* control by source
inspection: it parses `census`, finds the preflight call and the first transport
call, and requires the first to precede the second. Static inspection is weaker
than execution and it is honest about that; deleting the call, or moving it after
the loop, both go red. Where a function refuses to run under a harness, its call
ordering is checkable and its call presence is checkable, and that is better than
prose.

**What was observed of the failed run, and what it does not license.** The
GitHub rate-limit endpoint reported 497 requests used in the current hourly
window. That figure was read to decide whether re-running immediately would
exhaust the quota -- an operational question -- and it is not a measurement of
anything: hourly windows reset, the run spanned one, and the number covers part
of the run only. No candidate count, no per-root count and no disposition was
observed, because none was ever written. SFIR7's capacity remains unknown as this
is recorded.

**Re-running is not re-spending.** No receipt exists, no lineage was sealed and
the spent-identity authority is unchanged, so the second run measures a corpus
nothing has consumed. The precedent is SFIR6, which re-measured after repairing
INC-V2-106 under an unchanged frame. The frame here is likewise unchanged: same
fifty roots, same fingerprint, same N, same threshold. Only the instrument moved,
and it moved before any result existed to move it towards.

## INC-V2-118

**Fifty roots do not fit inside one hour of GitHub's quota, and the wrong limit
firing first destroys the census instead of trimming it.**

2026-08-27, second live run. It refused:

    {"state": "REFUSED", "why": "git retry wait exceeds frozen fail-safe bound"}

GitHub reported 5,000 of 5,000 requests used, resetting in 1,053 seconds. SFIR4's
frozen fail-safe permits a 60-second wait per retry and 180 seconds in total,
which is a bound built for a brief secondary-limit backoff and not for waiting
out an hourly window. The census stopped, correctly, and wrote nothing.

**Two ceilings, and the order they fire in decides what the run produces.**

    SFIR4 MAX_GIT_API_REQUESTS_GLOBAL   4,800   ours, frozen two studies ago
    GitHub authenticated primary limit  5,000   theirs, per hour

Ours firing first files the remaining roots as
`EXCLUDED_INCOMPLETE_ROOT_DISPOSITION` with the bound that stopped them: a
census, trimmed, with the trimming recorded. Theirs firing first asks for a wait
the fail-safe forbids: no census at all. The difference between those two
outcomes is 200 requests of headroom, and the run began on a window that already
had roughly five hundred spent in it -- the residue of the run INC-V2-117 lost.

**The repair is a precondition, not a wider fail-safe.** `require_rate_limit_headroom`
refuses to begin unless GitHub reports at least `MAX_GIT_API_REQUESTS_GLOBAL`
requests remaining, so ours is guaranteed to bite first. The check costs no
quota -- `/rate_limit` is free -- and it runs beside the receipt preflight,
before anything is spent. The observed headroom is written into the census,
because a run that began on a partly-spent window is a different observation
from one that began fresh.

**Widening the fail-safe was available and is refused.** Raising the retry bound
to an hour would have let the second run finish. That bound exists to stop a
census idling indefinitely; stretching it to absorb an operational inconvenience
would be loosening a safety limit so a run could succeed, which is the shape of
the move this programme forbids by name. A control now asserts both numbers are
unchanged.

**What this measures, and what it does not.** The run reached roughly 4,500
requests before the wall, so fifty roots at SFIR4's traversal cost more Git
requests than one hourly window provides and land close to the 4,800 cap. That is
an operational magnitude, and it is the second independent confirmation of
INC-V2-115: the inherited Git budget was sized for twenty roots and N = 50 does
not fit inside it. Under the founder's own formula with the tighter term, N is
20.

**N is still unchanged, and still not mine to change.** No candidate count, no
per-root count and no disposition has been observed. Request volume is a function
of tree shape, not of how many documents carry a usable revision pair, so nothing
here anticipates the capacity result. The next run starts on a fresh window,
visits the same fifty frozen roots in the same frozen order, and records whatever
the inherited cap leaves.

## INC-V2-119

**GitHub counts requests that our counter does not, so our own cap cannot be
relied on to fire before theirs -- and when theirs fires, the census died
instead of recording it.**

2026-08-27, third live run, on a window verified fresh twice ten seconds apart:
5,000 remaining, 0 used, 3,599 seconds to the next reset. It refused with the
same message as the second run:

    {"state": "REFUSED", "why": "git retry wait exceeds frozen fail-safe bound"}

Afterwards GitHub reported `remaining 0, used 5000`. So the run began with the
whole hour available, spent all of it, and stopped -- with SFIR4's own global cap
of 4,800 never having fired.

**Our counter and theirs disagree.** `_global_git_request_count` increments once
per `fetch` inside `_git`, and 4,800 is checked against it before every request,
so by our arithmetic the census could not have exceeded 4,800. GitHub charged
5,000. Roughly two hundred requests exist that we make and do not count. The
likeliest cause is redirect following -- a repository renamed since the January
2020 deposit answers 301 and `urllib` follows it, which is two requests to
GitHub and one to us -- and SFIR7's roster is six years old, so renames are
expected rather than exotic. **That explanation is not established.** What is
established is the disagreement and its size.

**The consequence was total rather than proportional.** The two ceilings sit 200
apart:

    SFIR4 MAX_GIT_API_REQUESTS_GLOBAL   4,800   ours
    GitHub authenticated primary        5,000   theirs

Ours firing first trims the census and records the trim. Theirs firing first
asked for a 38-minute wait, which SFIR4's frozen fail-safe forbids, and the whole
census was abandoned -- three roots' work and forty-seven roots' work discarded
alike. A gap of 200 requests decided between a result and nothing.

**The repair changes what the instrument RECORDS, not what it may wait for.** The
fail-safe is untouched: 60 seconds per retry, 180 in total, read live, with a
control asserting both. What changed is the decision that predicate drives. A
wait outside the fail-safe now excludes the current root and every root after it
as `EXCLUDED_INCOMPLETE_ROOT_DISPOSITION` with reason
`EXTERNAL_RATE_LIMIT_EXHAUSTED`, and the loop stops without making another
request -- asking again would spend requests to be told the same thing, against
the very window that has to reset before anything can run again.

**The two exclusion kinds are counted separately and must stay that way.**
`GLOBAL_GIT_REQUEST_BOUND` is a budget this programme chose two studies ago
firing as designed. `EXTERNAL_RATE_LIMIT_EXHAUSTED` is a budget imposed from
outside, which we have now measured we cannot preempt. Merging them would erase
the only evidence of which one actually binds, and that is precisely the open
question INC-V2-115 raised. The census carries a `which_budget_actually_bound`
summary for the same reason.

**Widening the fail-safe would have produced a census, and is refused.** An hour
of waiting per retry would have let all three failed runs finish. That bound
exists so a census cannot idle indefinitely, and stretching it to absorb an
operational inconvenience is loosening a safety limit so a run can succeed.

**Where this leaves N.** Three live attempts have now failed, and the third
failed on a full hour of quota with no measurement produced. Fifty roots at
SFIR4's traversal cost more than one window provides, from a host that charges us
more than we charge ourselves. This is the third independent confirmation of
INC-V2-115 and the second by measurement. Under the founder's own formula with
the binding term, N is 20. **N remains 50 and remains a founder ruling.** The
repair here makes a trimmed census recordable at N = 50; it does not make fifty
roots fit, and no repair inside this study's remit can.

**Still nothing observed about capacity.** No candidate count, no per-root count,
no disposition has ever been written. Request volume is a function of tree shape,
not of how many documents carry a usable revision pair.

## SFIR7 CAPACITY OUTCOME -- 2026-08-27

`receipts/sfir7-capacity-metadata-census.json`,
`receipts/sfir7-capacity-outcome.json`.

    state     CAPACITY_CRITERION_APPLIED_AND_FAILED
    verdict   MEASURED_NOT_SEALABLE
    C         459   (criterion requires 750)
    Q         367   (criterion requires 600)

**The criterion fails, and the number is a floor rather than a measurement.**
Both statements matter and neither replaces the other. 459 distinct documents
with a usable revision pair were found across fifty externally selected roots.
Twenty-four of those fifty roots never finished, so 459 is a lower bound for the
frame and the outcome is recorded `MEASURED_NOT_SEALABLE` -- the status SFIR6
introduced for its Wikipedia family, arriving here for an entirely different
reason.

**Root dispositions.**

    26   NONRECURSIVE_TREE_BFS_QUEUE_EXHAUSTED          completed
    15   TREE_QUEUE_OR_PATH_MAP_BOUND_BEFORE_ENQUEUE    truncated by an inherited bound
     5   TREE_BFS_BOUND_BEFORE_QUEUE_EXHAUSTION         truncated by an inherited bound
     4   EXTERNAL_RATE_LIMIT_EXHAUSTED                  GitHub declined to serve
     0   GLOBAL_GIT_REQUEST_BOUND                       our own cap never fired
     0   roots at the per-root candidate cap of 80

**The headline is not the shortfall. It is that the instrument could not finish
forty per cent of the frame.** SFIR4's per-root traversal bounds --
`MAX_GIT_TREE_OBJECTS_PER_ROOT = 158`, `MAX_GIT_TREE_QUEUE_ENTRIES = 256`,
`MAX_GIT_API_REQUESTS_PER_ROOT = 240` -- were frozen around twenty repositories
TAVONEL chose, which are mostly single-purpose Python and C libraries. Libraries.io's
published ordinal selected `babel/babel`, `rails/rails`, `facebook/react`,
`angular/angular`, `spring-projects/spring-boot`, `webpack/webpack`. Those trees
do not fit in 256 queue entries, and an externally chosen frame is under no
obligation to pick repositories that fit an instrument calibrated on a different
population.

**What the completed roots say, and its limits.** The twenty-six roots that ran
to exhaustion produced 459 documents, about 17.7 each, against SFIR6's 14.7 per
root over its twenty. So on the roots the instrument could finish, the external
frame yielded *more* per root, not less. That comparison is worth exactly what it
is worth: the twenty-six that finished are the twenty-six with small enough
trees, which is a selected subset and not a random one, and extrapolating from it
to the other twenty-four would be inventing the number this study exists to
measure.

**The delta against the predecessor, stated carefully.** SFIR6 measured 293 over
twenty TAVONEL-chosen roots; SFIR7 measured 459 over fifty externally chosen ones.
The +166 is not evidence that external selection is better: the root counts
differ, the traversal completed on only half the frame, and 459 is a floor. What
can be said is narrower and still useful -- *changing who chose the roots did not
close the gap to 750*, and it did not close it for a reason that is about the
instrument as much as about the corpus.

**The fourth gate earned its place on the first live run.** Nine of the fifty
addresses have been renamed since the January 2020 deposit:

    facebook/react                 -> react/react
    facebook/jest                  -> jestjs/jest
    facebook/create-react-app      -> react/create-react-app
    ReactTraining/react-router     -> remix-run/react-router
    bundler/bundler                -> rubygems/bundler
    erikhuda/thor                  -> rails/thor
    mui-org/material-ui            -> mui/material-ui
    webpack-contrib/css-loader     -> webpack/css-loader
    yannickcr/eslint-plugin-react  -> jsx-eslint/eslint-plugin-react

Every one kept its numeric repository id, so identity held and all nine were
censused as the repositories the frame selected. Under SFIR5's and SFIR6's three
gates each of these would have passed silently, and nothing in the receipt would
have shown that the address had moved. Eighteen per cent of a six-year-old roster
renamed is not an edge case; it is what a six-year-old roster looks like.
Forty-seven of fifty roots were attested -- the three unattested are among the
four GitHub declined to serve, which were never reached.

**Nothing was adjusted to suit this result.** No root was added, no threshold
lowered, N is still 50, the roster fingerprint is unchanged, and the per-root
traversal bounds that truncated twenty roots are recorded rather than raised.
Raising them is the obvious way to turn `MEASURED_NOT_SEALABLE` into a
measurement and it is exactly the move the charter forbids: they are inherited
constants, the shortfall is known, and changing them now would be tuning an
instrument against a number already in hand.

**What a follow-up study would have to do, and why it is not this one.** Bounds
sized for the frame's actual population, chosen and frozen before any census
runs, would let all fifty roots finish. That is a different study with a
different pre-registration, and proposing it is not the same as running it.

## INC-V2-120 -- SFIR8 opens: GitHub charges per network hop, and that is measured

2026-08-27. SFIR7 is terminal evidence by founder ruling and was not re-run.
SFIR8 is a development / instrument calibration study and produces no capacity
claim.

**The question.** SFIR7's counter recorded at most 4,800 Git requests and GitHub
charged 5,000. INC-V2-119 named redirect following as the likely cause and
recorded it as a suspicion, because a roster deposited in January 2020 had nine
of fifty addresses renamed by 2026 and `urllib` follows a 301 silently. The
founder ruling required the cause to be instrumented and measured, not assumed.

**The measurement.** GitHub returns `x-ratelimit-remaining` on every response,
including the one at the end of a redirect chain, so the drop in that header
across a single logical request *is* what the provider charged. No model of
GitHub's accounting is needed and none is used. Seventy-two logical requests over
eighteen repositories -- nine renamed, nine not -- across all four endpoint shapes
the traversal uses:

    unrenamed   36 logical   36 hops   36 charged   1.0 per request, 0 redirected
    renamed     36 logical   72 hops   76 charged   2.0 modal,      36 redirected

Thirty-three of the thirty-six renamed requests were exactly two hops and two
charges. Three were charged more than their observed hops -- two on
`webpack-contrib/css-loader` and one on `yannickcr/eslint-plugin-react` -- and
those are recorded as observations rather than folded into the rule.

**The instrument now keeps three counts apart**, because conflating two of them
is what cost SFIR7 four runs:

    logical_requests   what the traversal algorithm asked for
    network_hops       HTTP responses actually received, redirects included
    provider_charged   what the provider's own header says it deducted

`provider_charged` is the only one comparable with a rate limit.
`logical_requests` is what a traversal bound governs. A bound expressed in the
first cannot protect a budget denominated in the third, however carefully it is
derived -- which is the whole of SFIR7's operational failure in one sentence.

**Applying the rule to SFIR7 does NOT close the gap, and the receipt says so.**
Reading the terminal census only, and making no requests:

    logical requests recorded              3,970
    of those, on renamed addresses           790
    predicted provider charge              4,760
    provider limit                         5,000
    residual unexplained                     240

Per-hop charging accounts for a 790-request surcharge -- measured -- and leaves
240 charges unattributed. Two candidates are recorded and **neither is adopted**:
the run may have met a *secondary* rate limit with primary quota remaining, in
which case the residual is not a charge at all; or the provider charges something
the redirect handler cannot see, which the three outlier requests are consistent
with. The reconciliation reports
`PER_HOP_CHARGING_EXPLAINS_PART_OF_THE_DIVERGENCE` and refuses to say more.

**It is settled prospectively rather than argued.** SFIR7's census is not re-run
to resolve this. SFIR9's traversal will carry per-request charge accounting, so
the next live run answers the question with data instead of arithmetic.

**A note on using the mode rather than the mean.** The mean charge on renamed
requests is 2.11, inflated by the three outliers. Reconciling on 2.11 would have
predicted 4,848 and shrunk the visible residual to 152 -- absorbing an
unexplained observation into the rule and making the remaining mystery look
smaller than it is. The mode is what the provider does to a request of that kind;
everything else belongs in the residual where someone has to account for it.

**Two controls were missing and mutation found them**, both the
untested-call-site shape this session keeps producing. Every hop test built a
`RequestAccounting` by hand, so deleting the redirect hops from `fetch`'s
assembly stayed green; and the mode/mean fixture happened to have
`int(mean) == mode`, so swapping one for the other changed nothing. Fifteen
mutations, zero survivors after repair.

## INC-V2-121 -- the guard that was never installed, and the receipt that said so anyway

2026-08-28. SFIR8 sections A and B. Development instrument work; no capacity claim.

**What was built.** A transport that follows redirects itself instead of letting
`urllib` do it silently, writing one evidence atom per network hop --
`logical_request_id`, `hop_index`, `requested_url`, `status`,
`redirect_target_digest`, `response_body_sha256`, provider remaining before and
after, the charge delta, and GitHub's request id. Credential material is never
recorded: `_header_str` refuses by header *name*, so no value can reach an atom
even if a response echoes one back. Alongside it, a reconciliation that compares
three internal sums against `/rate_limit` read before and after, and reports the
difference as `UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA` without classifying it.

Canonical address resolution is the other half. A root's catalogue address is
followed once, the live numeric repository id is checked against the id the
roster froze, and only then is the live name adopted for the rest of that root's
traversal. A redirect to a *different* numeric id is refused, not adopted. SFIR7
spent 790 extra provider charges re-paying the redirect toll on every request of
every renamed root; this pays it once, per root, after proving identity.

**Twenty-seven controls passed on the first run. Two mutations survived.**

`T1` turned automatic redirect following back on -- deleting the entire reason
the module exists -- and the suite stayed green. Two independent reasons, and
both are the same mistake wearing different clothes:

  - The control tested `_NoRedirect.redirect_request` in isolation. That is a
    unit test of a guard, not a test that the guard is installed. The stub
    server replaced `build_opener` wholesale and never inspected its arguments,
    so whether a handler was passed at all was invisible to every test.
  - `totals()` reported `"automatic_redirect_following": False` as a **literal**.
    The receipt asserted the property rather than reading it. Remove the handler
    and the receipt goes on claiming manual following, in writing, to a reader
    who has no way to check.

The second is the worse of the two, and it is a new shape for this ledger. A
false field in a receipt is not a missing test -- it is evidence that says
something untrue. The repair makes the field a reading:
`follows_redirects_automatically()` instantiates the handler the fetch path will
actually use and asks it what it would do with a 301. Substitute a following
handler and the receipt now says `True` about itself.

`T10` appended a refused request to the completed-request list at the hop-bound
refusal, inflating the logical count with a request that never resolved. The
control for this existed but exercised the *other* refusal path -- the
Location-less one. Two `raise` statements, one covered.

**INC-V2-113, sixth recurrence.** Every time it has appeared in this study the
shape has been identical: the guard has a test, the call site does not.
Twice now the fix has had to be a control that inspects *how a collaborator was
constructed* rather than what it returns. That is uncomfortable to write and it
is the only thing that would have caught either of these.

**After repair: nineteen mutations, zero survivors.** T1 was split into T1a
(handler not installed) and T1b (reported policy hardcoded), because they fail
independently and a single mutation would have let one hide behind the other.

**What this does not settle.** The residual 240 from INC-V2-120 remains
unattributed and is not attributed here. The reconciliation is instrumented but
has not yet been run against a live isolated window, so
`UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA` has no measured value yet. Credential
exclusivity cannot currently be established, and that is recorded as a
limitation on the measurement rather than argued away -- another process holding
the same token produces arithmetic identical to a hidden provider-side charge,
and this instrument cannot tell them apart.

## INC-V2-122 -- the accounting closes, and both defects that hid it were mine

2026-08-28. SFIR8 sections A and B, first live run. Development instrument;
SFIR7's roots are spent material and no capacity claim is made from this.

**The first run produced two wrong numbers and neither was GitHub's fault.**

`TOLL_REMAINS`: canonical-addressed renamed roots cost 1.0 charge per request,
the never-moved baseline cost 1.2. A baseline more expensive than the treatment
is not a result, it is a broken control group -- and it was. The probe sampled
five of the nine known renames and then built its baseline by excluding *only
those five*, so `facebook/react` sat in the control group and redirected on
every one of its three requests. The entire 1.2-vs-1.0 difference was that one
contaminant. The exclusion set is now every known rename, and the receipt
carries `baseline_group_is_uncontaminated` so the next reader does not have to
take it on trust.

`UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA = 1`: forty-three hops, forty-two
charges. The transport's remaining-counter starts at `None`, so the very first
hop of a run has no `before` reading and its charge is unknowable -- correctly
recorded as unknown rather than as zero, which is why it showed up as a gap
instead of silently vanishing. But a gap of exactly one, in a receipt about
unattributed provider charges, is indistinguishable from the thing the receipt
exists to detect. `/rate_limit` is free and was already being read immediately
beforehand; the counter is now seeded from it.

**With both repaired, the accounting closes exactly.**

    logical requests        35
    network hops            40
    per-request charge sum  40
    provider used delta     40
    UNATTRIBUTED             0

Forty hop atoms, every one priced. And the canonical-addressing question is
answered: fifteen requests against five resolved canonical addresses, zero
redirects, 1.0 charge each -- identical to five repositories that never moved.
Resolution costs two hops once per root and nothing thereafter. Each of the five
was verified by numeric repository id before its live name was adopted:
`ReactTraining/react-router` -> 19872456, `bundler/bundler` -> 488514,
`erikhuda/thor` -> 15257, `facebook/create-react-app` -> 63537249,
`facebook/jest` -> 15062869.

**What this does and does not say about the residual 240.** At this scale
per-hop accounting closes perfectly, which is evidence against the hypothesis
that GitHub levies charges the response headers never expose. It is not proof:
thirty-five requests in a quiet window is not thirty-nine hundred in a saturated
one, and a secondary limit would not engage at this volume at all. The residual
stays unattributed. SFIR9 carries this accounting into a full traversal, which
is where the question gets answered.

**A note on what the zero is worth.** Credential exclusivity was not
established, and the receipt says so even though the delta came out zero. A zero
delta is consistent with exclusive use; it does not establish it. The limitation
is registered on a favourable result for the same reason it would be on an
unfavourable one -- a limitation that only appears when the number disappoints
is not a limitation, it is an excuse.

**Three further mutations, T13-T15, cover the seeding.** Twenty-two total, zero
survivors. The one worth naming is T14, which gives the unseeded counter a
plausible starting value instead of `None`: it makes every charge look
measurable while making the first one wrong. Reporting unknown as unknown is
what turned a silent one-unit error into a visible one.

## INC-V2-123 -- the frontier goes on disk, and the bound stops being about repositories

2026-08-28. SFIR8 sections C, D, E and F. Development instrument; no capacity claim.

**What SFIR7 actually measured when it truncated twenty roots.** Not that those
repositories were too large to count. Not that the request budget ran out. The
frontier was a Python list with a cardinality bound of 256, and SFIR4 arrived at
256 by looking at twenty smaller hand-picked repositories. `babel`, `rails` and
`react` exceeded it, and the census recorded them among the measured. They were
not measured; the instrument stopped.

**A bound derived from repositories cannot tell "large" from "unmeasurable".**
That is the defect in one line, and it is why the repair is not a larger number.
Raising 256 to 1024 would fail on the next repository nobody looked at, and
choosing 1024 *because* 256 failed is outcome-fitting. The frontier moved to
SQLite instead: durable, ordered, deterministic, standard library. Entries come
out in enqueue order and only in enqueue order, and the visited set is a table
rather than a set in memory, so both survive the process that built them.

**The remaining bound is bytes, and its derivation runs the other way.** A
declared working-storage envelope -- a property of the machine the study may run
on -- divided by the largest an entry can serialize to, built from Git's own
maxima rather than estimated. Nothing in the derivation reads a repository. The
disposition when it binds is `WORKING_STORAGE_BUDGET_EXHAUSTED`, an operational
stop, never mixed in with roots that finished. And because the bound is on what
is *held* rather than what has passed through, a traversal that keeps up with
itself is never stopped by it: a control expands fifty trees under a two-entry
ceiling.

**Segments replace waiting.** The frozen 60s-per-retry / 180s-total fail-safe is
unchanged, because widening an execution bound after a disappointing result is
the one thing the protocol forbids. When the window resets further away than the
fail-safe permits, the segment closes as `SEGMENT_COMPLETE_RATE_WINDOW` and the
next window resumes from a checkpoint it can prove it inherited. Each segment
names its predecessor's digest, so drop one, swap two, edit a field or arrive
with a different roster and the chain refuses to open. Counters are checked for
monotonicity across every boundary: work does not un-happen, and a counter that
fell means the segment did not inherit the state it claims.

**Four mutation findings worth keeping.**

`F3` deleted the statement that marks an entry as dequeued, and the suite *hung*
rather than failed -- the drain was `iter(f.dequeue, None)`, which reads
beautifully and never terminates against a queue that re-serves its head. A
control that hangs is indistinguishable from a broken runner, so it is not a
control. The drain is bounded now and the bound is an assertion.

`F9` deleted the UTF-8 encode from the entry size and survived, and the cause was
upstream of the mutation: `json.dumps` escapes non-ASCII by default, so the
string was already ASCII and the encode had nothing left to do. A number no
control can distinguish from its own absence is not being checked. The size is
now measured as SQLite actually stores it, which is also the honest unit for a
storage budget.

`F14` and `F15` were equivalent mutants -- a column DEFAULT that never applies,
and AUTOINCREMENT, which is *stricter* about reuse rather than looser. Neither
could express the defect it was named for, so both were replaced. The real F15,
returning `pending_count()` as the ordinal, then survived on a coincidence:
until something is dequeued, the count and the ordinal are the same number.
Dequeue first and they diverge.

`C10`, `C14` and `C16` survived for one reason in three costumes: each control
asserted something adjacent to its claim rather than the claim. Two frontiers
that differed in their ordinals could not detect an order-insensitive digest;
checkpoints all built key-by-key in one order could not detect a non-canonical
one; and looking for the word "unchanged" elsewhere in a sentence could not
detect the clause that said the bound had been widened.

**A defect in the harness itself.** The drivers never checked that the suite was
green before mutating. A red baseline makes every mutation look killed, which is
the most flattering possible failure mode. One run did exactly that and reported
17/17 while a control was failing on unmutated code. All three drivers now
refuse to start against a red baseline.

**The redirect driver was also corrupting what it tested.** It round-tripped
through `read_text`/`write_text`, which translates newlines on Windows, so every
run silently rewrote the module as CRLF. That is how f79d50c came to commit CRLF
blobs against a `.gitattributes` that says `eol=lf`, and why the EOL guard fired
on the commit after it. Bytes in, bytes out now. A tool that modifies the
artifact it is measuring was worth more than the mutation results it produced.

Final: frontier 16/16, checkpoint 17/17, redirect 22/22, each against a verified
green baseline. 108 controls across the four SFIR8 modules.

## INC-V2-124 -- an equivalence test cannot check the equivalence it uses

2026-08-28. SFIR8 section J, plus the first SFIR9 gate. Development instrument;
no capacity claim.

**The controls passed and meant almost nothing.** J1 compares an uninterrupted
traversal against a segmented one by asserting
`segmented.scientific_identity() == straight.scientific_identity()`. Twenty-five
controls, all green. Then mutation testing deleted candidate order from
`scientific_identity()`, and they stayed green. Then dispositions. Then the
visited set. Then frontier exhaustion. Then it keyed candidate identity on the
address instead of the numeric repository id. Green every time.

The reason is structural and worth stating plainly: **a self-comparison is
invariant under any change applied to both sides.** Removing a field removes it
from the left and the right at once, so the equality survives. The assertion was
never testing what the runs contained; it was testing that one function agrees
with itself. Eight of twenty-two mutations died. Fourteen lived.

The repair is two-sided. The relation is now pinned against explicit expected
content -- a golden assertion naming every candidate, ordinal, disposition and
visited tree of the fixture -- and against runs that *genuinely differ* and must
therefore not compare equal: a reversed candidate order, a missing candidate, a
truncated root, a different visited set, an unexhausted frontier. And one that
must still compare equal: a different transport trace. That last one is not
padding. It is the direction the whole section depends on, because a segment
interrupted mid-root legitimately costs more requests than an uninterrupted run,
and treating that as a failure would be as wrong as ignoring a real one.

**A surviving mutation found a real defect, not a missing test.** `INSERT OR
IGNORE` versus `INSERT OR REPLACE` for candidates made no difference to any
control, and the reason turned out to be worse than a weak test: a candidate was
never re-offered, because `dequeue` marked an entry consumed the moment it was
handed out. So a segment that ended between the hand-out and the expansion --
which is exactly what a `WorkingStorageExhausted` refusal does -- dropped that
entry, and with it every candidate beneath the subtree it named. Nothing
reported the loss. The frontier simply looked emptier than it should and the
root was recorded as exhausted.

Dequeue is a lease now. An entry is finished only when expansion says so;
anything left in flight when a segment ends returns to pending, and reopening
the store reclaims stale leases because a lease belongs to the process that took
it. The storage path releases rather than consumes. Five new mutations cover the
lease itself.

**Two constants that described behaviour were never checked against it.**
`OPEN_ROOT_REQUEST_COST` is the number the minimum segment budget is derived
from, and changing it left every control green -- the derivation still held, and
nothing compared the declaration against what opening a root actually costs. It
is measured now. A constant that describes behaviour and is only ever read by
code derived from it is a comment with a type.

**And one guard was deleted rather than tested.** The runtime no-progress check
could not fire: the budget pre-check already refuses anything below
open-cost-plus-one, so a segment that reaches the loop always expands or
advances a root. INC-V2-036, twelve recurrences and counting -- a guard placed
where its failure is impossible is not a guard. The pre-check is the whole of
the protection and it is reachable.

Final: traversal 19/21 then 24/24 after repair, frontier 21/21, checkpoint
17/17, redirect 22/22, isolation gate 26/26. All against verified green
baselines.

**J1 and J2 both hold.** Segmenting at four granularities leaves candidate
identities, candidate order, root dispositions, the visited set and frontier
exhaustion identical while the request count differs. Addressing one repository
by its 2020 catalogue name through a verified redirect, or by its canonical name
today, yields one identical population from one numeric identity -- and a
redirect that leads to a *different* numeric id produces no candidates at all
rather than a plausible set.

**The first SFIR9 gate is machine-checkable, and it is not a repair.** The
founder ruling preserves all fifty-nine drifted frozen attestations as the
evidence of a reproducibility chain that failed. The isolation gate reads that
receipt, records its digest, and never writes to it. It refuses a drifted
receipt used as a scientific prerequisite, a historical expected digest used to
certify current source, a claim of continuity with an old pin, an undeclared or
value-bearing historical input, and any component that selects an authority by
recency or shape rather than by name and digest.

It deliberately does *not* refuse a file merely for appearing in the drift list.
Current bytes may be newly frozen for SFIR9 with a new digest against a current
Git blob -- that is "the current implementation newly frozen", never "the old
component restored" -- and a gate that forbade it would make the failed chain
permanently contagious, rendering every file it ever touched unusable however
sound its implementation today.

The proof block reports both states side by side and says in its own text that
they are not merged: historical integrity FAIL, fifty-nine frozen drifts,
`PRESERVED_FAIL`; SFIR9 integrity independently evaluated. It also records what
it cannot establish -- the lookup scan is static and cannot prove that no
component selects an authority by recency at runtime. A control that overstates
itself is worse than none.

## INC-V2-125 -- three freeze preconditions were true and none was checkable

**The evidence for each lived in a session transcript rather than in the
repository.**

The ruling lists "mutation baselines green" among the conditions the freeze
depends on. It was green: twelve components, three hundred and ninety-one
hand-written mutations, zero survivors. But the drivers that produced that
number were scratchpad scripts. Nothing in the repository could be re-run to
reproduce it, and nothing would have noticed if a component later drifted out
from under its own table. The claim rested entirely on an implementer saying
so, which is the one form of evidence this project's own rules refuse.

The same was true of the legacy failure taxonomy, classified by reading
tracebacks in a terminal, and of the hostile audit's relationship to the rest
of the gate: each artifact existed, and no single thing could be run to check
that they still held together against the tree that would actually execute.

**The repair moved the evidence rather than strengthening the claim.** The
mutation tables were lifted verbatim into `tools/sfir9_mutation_tables/` and
the forty-line driver loop around them became one engine, so what is
committed is thirteen tables and one runner rather than thirteen
near-identical scripts. The classification became
`tools/sfir9_legacy_taxonomy.py`, which runs the suite and matches root causes
against declared signatures. Both write receipts. A gate,
`tools/sfir9_freeze_gate.py`, reads them, recomputes their digests, and
refuses to open unless every condition passes.

**What the move surfaced, which is why it was worth doing.** Writing controls
for the engine and the gate found three defects that the twelve scratchpad
drivers had all shared and none could have reported.

An emptied test selection read as a failing suite. The closure cannot verify
itself -- mutating it breaks its own committed-versus-working check -- so its
real-repository controls are excluded by name and copy-tree equivalents carry
the load. An exclusion that removed *every* test would have been just as
invisible, and pytest exits 5 on "no tests collected", which the drivers'
`returncode != 0` read as red. Red is nearly the right answer, but for the
wrong reason, and the reason is what would have had to be believed later. The
engine checks for the empty selection first and reports
`BASELINE_SELECTED_NO_TESTS`.

The gate's first draft carried an impossible check. It read each closure
record's `committed_bytes_equal_working_bytes` and
`import_origin_is_the_verified_file` and reported a failure if either was
false. Neither can be false: `closure()` raises on the first component that
fails any of its five bindings, so a returned record can only say they held.
**INC-V2-036, sixteenth recurrence** -- a guard placed where its failure is
impossible. Removed, with the reason recorded where the check used to be.

Seven of the gate's own thirty-two mutations then survived their first pass,
every one in a branch the controls never reached: the suite runner, the
closure's two "could not" exits, the re-derivation, and `main()`. **A branch
nothing drives is not defended**, and a mutation score computed only over the
branches someone happened to exercise is a measure of the test author's
attention, not of the code's defences.

**Status:** closed. The preconditions are receipts a fresh checkout can
regenerate, and the gate that reads them refuses on `UNPROVEN` as well as on
`FAIL` -- a condition nobody could measure and a condition that failed are
different problems, and only one of them looks like a clean bill.

## INC-V2-126 -- the freeze binds a receipt that a later commit may legitimately regenerate

**Observed.** Re-verifying the instrument freeze against the working tree found
`freeze_gate` DRIFTED while the other four bound receipts matched. Git reported
the receipts directory clean, so the committed gate receipt was not the one the
freeze recorded.

**Cause, established rather than assumed.** The freeze bound
`sfir9-freeze-gate.json` as it stood at the instrument commit `f2912af`, and
that hash still matches the blob at `f2912af` exactly. Commit `4150f90` -- the
commit that recorded the freeze -- also replaced the gate receipt with one
regenerated in the main working tree. The two receipts carry the same verdict:
`gate_opens` true in both, 9/9 in both, the same nine condition names, and no
condition in a different state. They differ in wall-clock timings and in one
suite line, `772 passed, 4 skipped` from the isolated checkout against
`779 passed` from the main tree, which is the untracked
`infra.runpod.v6.credentials` import resolving in one tree and not the other.

**What was not done.** The freeze's recorded hash was not rewritten, and the
older receipt was not restored over the newer one. Both moves would have made a
check go green by editing the evidence it checks. This is the same ruling the
fifty-nine historical frozen drifts are held under: preserve, do not reconcile.

**The actual defect is the verification procedure, not the freeze.** A freeze
binds bytes as they were at the instrument commit. Its supporting receipts are
regenerable artifacts, so any honest re-run of the gate produces different bytes
for the same verdict, and a verifier comparing the freeze against the *working
tree* will report drift every time without that drift meaning anything. The
comparison that carries information is against the blob at the instrument
commit:

    git show <instrument_commit>:<relative_path> | sha256sum

**Status:** open as a documentation defect. The freeze receipt records
`instrument_commit`, so the correct comparison is available to anyone holding
the receipt, but the receipt does not say that the working tree is the wrong
side to compare against. A verifier that drifts benignly on every re-run trains
its reader to ignore it, and a binding whose failures are all false is not
usefully different from no binding at all.

## INC-V2-127 -- a killed mutation run left a frozen component mutated on disk

**Observed.** A full mutation run was started, then stopped because it would
have overwritten `sfir9-mutation-baselines.json`, which the instrument freeze
binds by hash. Afterwards `test_every_mutation_anchor_is_present_in_its_component`
reported one stale anchor, `audit: H30 the results are dropped from the receipt`.
`git diff` showed why: `tools/sfir9_hostile_audit.py` was still holding H30,
with `"results": results` replaced by `"results": []`.

**Cause.** The engine applies a mutation, runs the suite, and restores the file
in a `finally`. A `finally` covers an exception. It does not cover the process
being killed, and the run was killed between the write and the restore.

**Why it mattered more than a dirty file.** `sfir9_hostile_audit.py` is a
component the instrument freeze binds. Left as it was, the next mutation run
would have scored against a file nobody wrote, and the hostile audit itself
would have produced a receipt with an empty `results` list while still
reporting `audit_passes` true -- because the count of refusals and the count of
results were both taken from the same emptied list.

**Repair.** The single file was restored from its committed bytes with
`git checkout -- <path>`, not a repository-wide restore, and all ten frozen
closure components were then re-checked against the hashes the freeze recorded.
All ten matched.

**Change.** `sfir9_mutation.py` now refuses to run when any target it is about
to mutate differs from its committed bytes, naming them. The check lives in the
runner rather than in `run_component`, because the sandboxes the engine's own
tests build are not in the repository at all and a check there would refuse
every one of them.

**Consequence that is not a defect.** A component cannot be measured before it
is committed. That ordering is the point: a baseline recorded against
uncommitted bytes describes a file that may never exist again.

**Status:** closed. The engine refuses the condition, and two controls cover it
-- one that a named dirty target refuses, and one that a clean tree does not.

## INC-V2-128 -- SFIR9 has no frozen rate-window orchestration, and the absence is load-bearing

**The question, asked before any cohort repository was contacted.** What
pre-roster frozen artifact specifies when the runner invokes
`observe_rate_window`, how `remaining` / `reset_epoch` / `retry_after` are
obtained, and when a segment must terminate?

**Answer: none.** Established mechanically by
`tools/sfir9_execution_authority_gap.py`, which parses call sites rather than
grepping, because a mention in a docstring is not a caller and this finding
turns on that difference.

    observe_rate_window production callers   []
    observe_rate_window test callers         7
    plan_wait production callers             only observe_rate_window itself
    HopAtom carries reset epoch              False
    HopAtom carries retry-after              False
    upstream reads x-ratelimit-remaining     True
    upstream reads x-ratelimit-reset         False
    upstream reads Retry-After               False
    declared_surface observed_from           all three

So the decision function has no caller; two of its three inputs cannot be
carried by the frozen hop record and are never read from response headers by
the frozen upstream; and the transport's own declared surface names all three as
observed. The declaration is frozen. The acquisition is absent.

**Frozen constants are not a frozen control flow.** `RETRY_WAIT_SECONDS`,
`TOTAL_WAIT_SECONDS` and `SEGMENT_COMPLETE_RATE_WINDOW` are all frozen and all
three describe what happens once the decision function has been called with
three observed values. None says when to call it. SFIR8's equivalence controls
segment at budgets of 1, 3 and 4 precisely to show that where a segment ends
does not change candidate identities, order, dispositions, the visited set or
frontier exhaustion -- they prove segmentation is scientifically neutral given
eventual completion, and specify no production schedule at all.

**Why the gap is not cosmetic.** With no caller, nothing closes a segment on a
rate window. A 403 returns through the frozen upstream as an ordinary record
with a non-dict body; `_expand` reads that as an empty tree; the frontier
drains; and the root is recorded `FRONTIER_EXHAUSTED`, which the frozen scorer
defines as a count that is exact.

That is SFIR7 restated exactly -- twenty of fifty roots recorded as measured
when the instrument had merely stopped -- and it is the single failure SFIR9
was built to eliminate. Inventing the orchestration now, with the roster
visible, would mean choosing when the study stops looking after seeing what it
would be looking at.

**Ruling applied.** SFIR9 stops as a non-sealable prospective chain. It is not
repaired after roster opening. The instrument freeze, the cohort-input binding
and the sealed fifty-root roster are all preserved unchanged, and no cohort
repository has been contacted.

**What was not done.** No polling schedule was invented, no segment budget
chosen, no checkpoint cadence selected. `sfir9_census_authority.py` was written
and then removed unissued: an execution authority that binds a driver which must
not exist is an invitation to run one.

**An evidentiary correction worth keeping.** That authority draft marked
`cohort_network_contact_before_driver_freeze = false` as OBSERVED, justified by
the absence of census and frontier artifacts. Artifact absence cannot establish
that no request whatsoever ever occurred -- a manual metadata GET leaves no
frontier database. The observable facts are narrower and should be recorded
separately from the stronger claim: no census artifact exists, no
frontier-or-segment artifact exists, no capacity or score receipt exists. The
universal statement rests on operator knowledge and is ASSERTED. Evidence must
not be stronger than its source, which is this paper's own thesis pointed at its
own receipts.

**Status:** closed as a finding. SFIR9 remains a valid frozen instrument for a
future protocol whose orchestration is frozen before selection; what it cannot
be is this study's sealable capacity result.

