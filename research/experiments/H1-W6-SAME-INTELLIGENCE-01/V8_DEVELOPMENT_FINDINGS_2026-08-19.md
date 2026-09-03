# v8 pipeline engineering on v7 development data — findings

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

**Run class: `DEVELOPMENT_ONLY`.** Everything here was measured on the sealed v7
development set (`receipts/v7-development-seal-2026-08-19.json`). **No number in
this document is a paper endpoint**, no v8 holdout title has been read, and the
gate verdicts below are rehearsals of the gate *mechanism*, not the v8 pre-arm
verdict. This is `W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §7 — the stage that
exists so a harness defect is paid for with development data instead of holdout
titles.

Three of the four defects below would have consumed the v8 holdout. That is the
whole return on doing this stage.

---

## 1. §2A structural / taint gate — `PASS`, and it can fail

`receipts/v8-structural-taint-gate-dev-2026-08-19.json`

The builder receives `subject`, `attribute`, `date`, `template_id` and nothing
else. Every content token of a rendered query must be explainable by a declared
input or a fixed template literal; a token explainable by neither, which also
occurs in the oracle passage, is tainted.

| builder | queries | tainted | |
|---|---|---|---|
| reference | 711 | 0 | `PASS` |
| mutant `single_oracle_token` | 711 | 711 | `CAUGHT` |
| mutant `passage_paraphrase` | 711 | 711 | `CAUGHT` |
| mutant `value_appended` | 711 | 711 | `CAUGHT` |

**Defect found and fixed here.** The minimal-leak mutant first caught 663 of 711.
The 48 escapes were cases where the token it injected was a numeral that also
occurs in the date — a token the template had already licensed, so not a leak,
and correctly not flagged. A mutant that injects a non-leak measures the gate's
tolerance rather than its sensitivity. The mutant now subtracts the date tokens
and injects a genuine leak; 711/711.

**Limitation, stated rather than papered over.** A passage token that coincides
with a declared-input token is invisible to this gate by construction. It carries
no information the template had not already licensed, but the gate cannot
distinguish the two cases and does not claim to.

---

## 2. §2B residual overlap — calibrated once, frozen

`receipts/v8-residual-calibration-dev-2026-08-19.json`

Query tokens labelled `SUBJECT > ATTRIBUTE > DATE > TEMPLATE > RESIDUAL`, each
credited once, and the oracle overlap split into structured intent and residual.

| | median | p90 |
|---|---|---|
| raw overlap | 0.6667 | 0.8571 |
| structured intent | 0.6667 | 0.8571 |
| **residual (the gate)** | **0.0** | **0.0** |

This is the v7 finding quantified: **the entire raw overlap is addressing
information**, not passage-derived text. v7's §3 failure was the metric counting
the question's own subject and attribute against it.

Calibration rule, fixed in the protocol before this ran and applied exactly once:
ceiling = statistic rounded up to the next 0.05, plus 0.05 headroom.
**Frozen: residual median ≤ 0.05, residual p90 ≤ 0.05.** Positive controls in the
same execution: 711/711 injected-token queries exceed the ceiling, every
untouched query is within it.

**What this gate is worth, honestly.** For a builder that passes §2A the residual
is 0 by construction, so on a clean builder 2B confirms 2A rather than adding an
independent signal. It is retained because it operates on the *emitted questions*
rather than on the builder, so it still fires on a question set whose taint audit
was skipped, bypassed, or run against different code.

---

## 3. §1/§3 entity-conditioned baseline gate — `FAIL`, with the cause identified

`receipts/v8-entity-conditioned-gate-dev-2026-08-19.json`

Stage 0 restricts the candidate pool to the subject's own before + after
revisions, both indexed, no temporal metadata. 265 questions evaluated, 25
skipped for no locatable oracle, 3 for a degenerate value.

| criterion | value | bound | |
|---|---|---|---|
| unit Recall@1 | 0.3736 | ≥ 0.1189 (random), ≤ 0.95 | `PASS` |
| unit Recall@5 | 0.9623 | ≥ 0.4923 (random), ≤ 0.99 | `PASS` |
| exact tie rate | 0.0906 | ≤ 0.10 | `PASS` |
| normalized candidate entropy | 0.6558 | 0.20–0.99 | `PASS` |
| **before/after separable share** | **0.6679** | **≥ 0.80** | **`FAIL`** |
| stale-revision retrieval rate | 0.5283 | 0.02–0.90 | `PASS` |
| new value absent from before revision | 0.2302 | reported, not gated | — |

**Entity conditioning did what it was designed to do.** Unit Recall@1 moved
0.1887 → 0.3736 and the tie rate 0.1038 → 0.0906 against v7's open-corpus
measurement. The document-discovery half is no longer inflating the result.

**The temporal challenge is real and is the hard part.** The stale revision wins
top-1 on 0.5283 of questions, and the oracle-minus-strongest-wrong-revision gap
has median **−0.0333** with **0.6264** of questions negative: on most questions
BM25 ranks a superseded-revision unit above the current one. That is precisely
the discrimination W6 was written to test, and a non-temporal retriever does not
have it.

`same_document_top_1_share` is **retired from this gate** — under entity
conditioning it is ~1.0 by construction of the task rather than by weakness of
the question set. It is not silently dropped: it remains reported in W6-O, where
it still measures difficulty. v7's value was 0.9585.

---

## 4. The defect that matters most: v7's revision-sensitive class is ~1/3 hollow

**96 of 293 (32.8%) `revision_sensitive` questions have no semantic change.** The
v7 generator detected change by comparing raw wikitext strings, so pure markup
edits were admitted as revision-sensitive:

| attribute | before | after |
|---|---|---|
| `honorific prefix` | `Sir` | `[[Sir]]` |
| `location` | `[[Chicago]], [[Illinois]], US` | `[[Chicago]], Illinois, US` |
| `predecessor3` | `[[George M. Bibb\|George Bibb]]` | `[[George M. Bibb]]` |
| `location` | `…<br>[[Suzuka, Mie\|Suzuka]]…` | `…<br />[[Suzuka, Mie\|Suzuka]]…` |
| `place of origin` | `Canada <br /> United States` | `[[Canada]]<br />[[United States]]` |

The answer is identical before and after. A third of the primary endpoint class
was asking a temporal question with no temporal content, which would have diluted
every arm's measured effect toward zero and made a real TAVONEL advantage harder
to detect — or manufactured an apparent one from noise.

**Binding consequence for the v8 generator:** revision-sensitivity is decided by
**value-token inequality**, not raw wikitext inequality. Markup-only edits are
excluded at generation and the exclusion count is reported. This is fixed before
the holdout exists.

---

## 5. Two changes made after seeing a failure, declared as such

Redesigning a measurement after seeing it fail is the move that ends a
confirmatory claim, so both are recorded rather than absorbed. Both are
construct-validity corrections on development data — neither is a threshold
relaxed to obtain a pass, and the gate still reports `FAIL`.

**5.1 The oracle and separability matcher.** The first run used the retrieval
tokenizer, which requires a leading letter. A numeric value — a year, a
population, an area — tokenizes to the empty set, and the empty set is a subset
of every unit. 18 of 300 golds were affected. Replaced with the v7 value matcher,
which keeps numerals and drops markup tokens. A gate failing on a broken
measurement is not a finding.

**5.2 The separability construct.** The first operationalization asked whether
the new value appears *anywhere* in the before revision, and measured 0.1727.
That is a distractor property — a new value can appear in the old article's
prose, a list, or a different infobox field while the attribute itself still
differs — and it is not what §3's criterion names. The criterion is now the
attribute's value differing between revisions (0.6679, still `FAIL`), and the
original measurement is **kept and reported** as
`new_value_absent_from_before_revision_share` (0.2302) rather than deleted.

---

## 6. The v8 generator, and a guard that could not fire

`receipts/question-set-v8-dev-2026-08-19.json`, built from the v7 development
acquisition so the generator is exercised before a holdout exists.

Admission changes in exactly one way: a revision-sensitive question requires the
attribute's **value** to change, decided on markup-normalized value tokens. The
instrument is otherwise v7's — the frozen §2 templates, the same infobox parser,
the three-per-article cap fixed by hash order at acquisition — so v7 and v8
questions stay comparable.

| | v7 rule | v8 rule |
|---|---|---|
| revision-sensitive | 293 | **194** |
| markup-only, primary-eligible | admitted | **96 excluded** |
| markup-only, outside the primary path | — | 20 excluded |
| degenerate value | — | 3 excluded |
| simple retrieval | 2,522 | 2,522 |

**96 is the same 96** the §4 diagnostic found by a different code path. Two
independent paths agreeing is what makes it a number rather than an artefact.
The exclusion is 0.331 of what v7's rule would have admitted, and every exclusion
class is counted in the receipt — a generator that quietly discards a third of
its input is indistinguishable from one that had a third less input.

The admission control runs in the same execution: four markup-only shapes taken
from the v7 corpus must be rejected and three real value changes admitted. A
filter that rejects everything would be worse than v7's, so both directions are
asserted.

**Defect found here, and it is the serious kind.** §6 requires a holdout build to
refuse a corpus overlapping v7's titles, checked against the seal rather than
against a recollection. The check read `development_titles`; the seal stores them
under `development_titles_excluded_from_v8.titles`. The lookup returned empty, so
the overlap set was empty, so **the guard passed everything**. It now reads the
right key and refuses outright if the seal records no titles — an inert guard is
worse than no guard, because it reports success. The unit test drives the refusal
path rather than asserting the key name.

---

## 6a. The gate re-run on the corrected question set — `PASS`, with one caveat that matters

`receipts/v8-entity-conditioned-gate-on-v8-questions-dev-2026-08-19.json`

The same gate, same bounds, same code, against the v8 question set instead of
v7's. 177 questions evaluated, 17 skipped for no locatable oracle.

| criterion | on v7 questions | on v8 questions | |
|---|---|---|---|
| unit Recall@1 | 0.3736 | 0.3672 | `PASS` |
| unit Recall@5 | 0.9623 | 0.9492 | `PASS` |
| exact tie rate | 0.0906 | 0.0734 | `PASS` |
| normalized candidate entropy | 0.6558 | 0.6693 | `PASS` |
| before/after separable share | 0.6679 `FAIL` | **1.0** | `PASS` |
| stale-revision retrieval rate | 0.5283 | 0.4972 | `PASS` |
| new value absent from before revision | 0.2302 | 0.3390 | reported |

**`before_after_separable_share` = 1.0 is tautological and is not evidence.** The
v8 generator admits an attribute only when its value tokens differ, and the gate
measures whether the value tokens differ — the same comparison on both sides. The
criterion now verifies that the generator did what it says, which is worth having,
but it is **not an independent difficulty check** and must not be read as one.
This is precisely the critique that retired `same-document top-1 share` in §3, and
it applies to a criterion this protocol introduced, so it is recorded here rather
than left for a reviewer to find. Whether it should be replaced by a construct the
generator does not determine is an open question for the protocol freeze; it is
not resolved by this run.

The metrics the generator does *not* determine moved little: Recall@1 0.3736 →
0.3672, tie rate 0.0906 → 0.0734, stale-revision retrieval 0.5283 → 0.4972. The
oracle-minus-wrong-revision gap stays negative — median **−0.0464**, **0.6328** of
questions negative. **Removing the hollow questions did not make the temporal
discrimination easy**, which is the outcome that keeps W6 worth running.

**This `PASS` is on development data and is not the v8 pre-arm verdict.** The v8
pre-arm gate runs on holdout questions from a holdout corpus, and nothing here
substitutes for it.

---

## 6b. The four arms run end to end — and RAW is being destroyed by the shared budget

`receipts/v8-development-arm-run-2026-08-19.json`

177 questions, four arms, all three controls separating in the same execution
(fairness contract holds; scorer separates; statistics separate).

**The model performs no inference.** `ExtractiveDevelopmentModel` returns the
first gold candidate the supplied context actually contains, which makes every
arm's result a pure function of the evidence it retrieved. That is what verifies
the plumbing, and it is why **none of these numbers is a result about any model**.
The receipt carries `run_class: DEVELOPMENT_ONLY` and `is_real_model: false`.

| arm | answer correct | evidence correct | stale | truncation | **oracle lost to truncation** |
|---|---|---|---|---|---|
| RAW | 0.8305 | 0.1299 | 0.1017 | 0.8701 | **0.5763** |
| BASIC_RAG | 0.8927 | 0.6045 | 0.0339 | 0.0113 | 0.0282 |
| BASIC_RAG_PLUS | 0.8814 | 0.5593 | 0.0226 | 0.0395 | 0.0395 |
| TAVONEL | 0.9096 | 0.9153 | 0.0113 | 0.0395 | 0.0113 |

**The finding: RAW loses the oracle to truncation on 57.6% of questions.** Under
the shared 3,000-token budget, whole documents do not fit, and RAW is answering
more than half the questions from evidence that no longer contains the answer.
Its `evidence_correct` of 0.1299 is therefore **not a floor established by
representation — it is a floor established by context budget**, and reporting it
as "RAW is the floor" would attribute to knowledge representation what the budget
did.

This is precisely the distortion §3 of the review instruction names, and it must
be resolved in the protocol **before** the freeze, not after seeing holdout
results. Two defensible options, and the choice is not this code's to make:

**A. Keep one shared budget for all arms.** Honest and simple, but then RAW is a
*budget-limited* floor and every report must say so in those words. The
comparison remains valid for TAVONEL vs BASIC RAG, which is the primary anyway.

**B. Give RAW a budget large enough to hold both whole documents**, and give the
retrieval arms their top-k as before. This tests representation rather than
capacity, but it hands RAW strictly more context than the other arms, which must
then be stated as a deliberate asymmetry favouring the floor.

Doing neither — leaving a shared budget unstated — is the only unacceptable
option, because it produces a TAVONEL advantage that is partly a context-window
advantage and reads as a representation advantage.

**The primary comparison is not significant here and that is expected.** TAVONEL
vs BASIC RAG on answer correctness: effect **+0.0169**, 95% CI **[−0.0465,
0.0808]**, **3 discordant pairs**, exact McNemar **p = 0.25**. With a
non-inferring model the arms mostly agree, so 3 discordant pairs is what a
working harness should produce. Reporting the p-value alone would hide that the
comparison rests on three questions.

The one column where the arms separate sharply is `evidence_correct` — 0.9153 for
TAVONEL against 0.6045 for BASIC RAG — which is the harness confirming that
valid-time ordering routes different evidence, exactly what it was built to do.
It is a plumbing check, not a claim.

---

## 6c. The fail-closed pre-holdout gate

`receipts/v8-holdout-preflight-2026-08-19.json`

Opening the holdout is the one irreversible act in this experiment, so the gate
defaults to refusal and the acquisition path cannot run around it. Sixteen
conditions, each carrying the reason it exists; fifteen break-controls run in the
same execution and **all fifteen refused**. The gate reads development-side state
only --- it opens, reads, inspects, previews and dry-runs nothing.

It currently says **no**, for five reasons, and four of them are open decisions
rather than defects:

| condition | state |
|---|---|
| `config_freeze_exists` | `FAIL` --- the freeze has not been written |
| `no_source_drift` | `FAIL` --- no frozen hashes to compare against yet |
| `model_is_pinned_and_real` | `FAIL` --- the development model performs no inference |
| `raw_context_budget_policy_decided` | `FAIL` --- §6b is unresolved |
| `separability_metric_disposition_decided` | `FAIL` --- §6a is unresolved |
| the other eleven | `PASS` |

The gate exists partly because this programme has already shipped a guard that
could not fire: the generator's overlap check read `development_titles` while the
seal stores `development_titles_excluded_from_v8.titles`, found nothing, and
therefore passed everything. `empty_seal_titles` is now a refusal, and a test
drives that specific path.

---

## 6d. The three decisions, taken 2026-08-20, and what they changed

**1. Model identity: `Qwen/Qwen3.6-27B`, pinned by attestation rather than by
name.** The repository's source register carries the model card (`S39`) but no
revision, so the attestation must come from the live runtime. Eight fields are
required before the holdout opens: checkpoint revision · model-file manifest
sha256 · tokenizer identity · tokenizer hash · serving runtime · serving runtime
version · immutable runtime image digest · model attestation. A name pins
nothing --- two runtimes serving the same name can differ in checkpoint,
tokenizer, quantization and serving stack.

Decoding, identical across all four arms: `temperature = 0.0`,
`max_tokens = 256`, `tools = off`, one shared system and evaluation contract.

**There is no fallback model.** If the exact runtime cannot be attested the
preflight fails as `MODEL_RUNTIME_NOT_READY` and the holdout stays closed. The
freeze builder refuses with exit code 3 on a substituted model or an incomplete
attestation, and does not write a partial freeze.

**2. RAW context budget: option B, and the measurement confirms it was right.**
RAW now receives the whole before + after document pair against the frozen
model's context rather than the 3,000-token retrieval budget. Re-running the
development pipeline under the new policy:

| | shared budget | whole-document budget |
|---|---|---|
| RAW truncation rate | 0.8701 | **0.0** |
| RAW oracle lost to truncation | 0.5763 | **0.0** |
| RAW evidence correctness | 0.1299 | **0.2260** |
| RAW answer correctness | 0.8305 | **0.9209** |

The old floor **was** a context-budget floor: removing the budget moved it. What
remains --- RAW recovering the right revision only 22.6% of the time --- is the
real floor, and it is what a whole-document arm without temporal metadata can
do, since document order puts the superseded revision first and nothing marks
which one is current.

The asymmetry is deliberate, favours the floor, and is reported rather than
hidden. RAW is a **floor only**; the primary comparison stays TAVONEL vs BASIC
RAG. Per-arm input tokens, context utilization, latency and inference cost are
reported separately; cost is `null` on development runs because no inference
occurs, with the reason recorded rather than the field omitted.

**Overflow is never silent.** If the whole-document pair exceeds the frozen
context, `RawContextOverflow` is raised, the question is recorded as
`RAW_CONTEXT_OVERFLOW`, RAW is scored as an abstention there and reported
separately. The paired TAVONEL vs BASIC RAG endpoint is unaffected, because RAW
is not the comparator. RAW also refuses to run at all before the context window
is known --- falling back to the retrieval budget would rebuild exactly the
defect this decision removes.

**3. Separability: option A.** `before_after_separable_share` is
`GENERATOR_INTEGRITY_CHECK_ONLY` and is **excluded from difficulty evidence**.
Its 1.0 is not independent difficulty evidence and is never cited as such. **No
replacement difficulty metric is added**: choosing one after seeing the v7
development result would weaken the confirmatory design, which is the same
reasoning that made v7 development rather than a result.

The preflight now enforces all three as exact values --- reverting to the shared
RAW budget, or swapping the separability disposition for a replacement metric,
each trips its own break-control and refuses.

---

## 7. State, and what has not been done

- §2A taint gate — **built, live, `PASS`**, three mutants caught
- §2B residual gate — **built, live, `CALIBRATED`**, ceilings frozen
- Stage 0 entity routing — **built**
- §3 baseline validity gate — **built, live, `FAIL` on development data**, cause
  identified as the v7 generator's markup-only admissions
- v8 question generator — **built**, admission control separates, holdout
  overlap guard live and tested
- `RAW`, `BASIC RAG`, `BASIC RAG+`, `TAVONEL` adapters — **built**, fairness
  contract live and controlled
- answer normalization, evidence/provenance/temporal/abstention scoring — **built**,
  control separates (it caught a numeric-normalization defect: `1,450` scored
  wrong against `1450` on thousands separators alone)
- paired statistics — **built** without scipy: exact binomial McNemar, Newcombe
  paired interval, Holm over the 7 secondaries; control separates
- RAW context-budget measurement — **built**, and it found the truncation problem
  in §6b that needs a protocol decision
- fail-closed pre-holdout gate — **built**, 15/15 break-controls refuse, and it
  currently refuses for five named reasons
- v8 holdout — **NOT OPENED**, and the gate refuses to allow it
- config-freeze builder — **built**; it takes the three decisions as required
  arguments with no defaults, refuses without any one of them, and verifies
  rather than overwrites an existing freeze
- config freeze receipt — **NOT WRITTEN**. Three of its fields are founder
  decisions rather than code: the model identity, the RAW context-budget policy
  from §6b, and the separability disposition from §6a. The handoff for the fresh
  session is `V8_FRESH_SESSION_HANDOFF_2026-08-19.md`.

The §3 `FAIL` on development data is not a v8 gate failure and does not trigger
the §8 stop rule. It is the expected outcome of running a corrected gate against
a question set built by an uncorrected generator, which is the reason §7 puts
this stage before the holdout.
