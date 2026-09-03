# W6 v8 — confirmatory protocol, frozen before any v8 holdout title is chosen

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

**`PROTOCOL_V2_2026-08-19.md` is not edited and not superseded.** It governs v1,
v2 and v7, and those runs are read against it. This is a new protocol for a new
run, and the v2/v7 history stays exactly as it is.

**v7 is sealed development evidence** — `receipts/v7-development-seal-2026-08-19.json`,
classification `SEALED_DEVELOPMENT_PROTOCOL_CONFLICT_RUN`, 13 artifacts pinned by
sha256 and re-verifiable. Every design decision below is traceable to something
v7 measured. None of it may be reported as an outcome.

---

## 0. The development findings this protocol is a response to

Two, both from v7, both measured:

**Raw lexical overlap confounded legitimate structured intent with leakage.**
PROTOCOL_V2 §3 exists to catch a question built backwards out of the oracle
passage's own wording — v1's failure, median overlap 1.0. In v7 the §2 template
mandates the subject, the subject is the article title, and a Wikipedia article
contains its own title, so the median query↔oracle overlap was 0.750 against a
0.50 ceiling while **verbatim containment was 0**. Of the tokens shared between
query and oracle, the median share contributed by the subject's own name was
**0.667**; excluding those tokens the same measurement gives median 0.500 and p90
0.667, inside the frozen thresholds. The metric was counting the question's
addressing information as leakage.

**Open-corpus BM25 confounded entity localization with temporal-unit retrieval.**
Under the same mechanism the baseline found the right *document* almost always
(same-document top-1 share **0.9585**) and the right *unit* rarely (Recall@1
**0.1887**, exact-tie rate 0.1038). Title tokens are shared by every unit of the
target article, so they route to the document and then stop discriminating. One
BM25 ranking was being asked to do two different jobs.

**Scope of these findings.** They hold for the v7 subject-titled representation,
the frozen §2 templates, and the BM25 / section-unit-indexing baseline actually
run. **Nothing here is an impossibility result.** No other retrieval
architecture, chunking, subject representation or admissible baseline was
measured, and this protocol does not claim a satisfying configuration under
PROTOCOL_V2 does not exist. The following wording is forbidden in every v8
artifact: *inherently unsatisfiable*, *mathematically incompatible*, *impossible
for subject-titled questions*, *no valid RAG baseline can satisfy the gates*,
*mutually unsatisfiable*.

---

## 1. What v8 measures

W6's claim is not "can a retriever find the article". It is whether knowledge
about the **same subject that changed over time** is answered with the correct
revision and provenance.

**Primary: W6-T, entity-conditioned temporal retrieval.**

A common Stage 0 gives every arm the same deterministic subject → document
namespace resolution. Stage 0 supplies **which subject the question is about**
and nothing else: not the value, not the revision, not the answer-bearing unit.

| arm | evidence it receives, after Stage 0 |
|---|---|
| `RAW` | that subject's before + after whole documents |
| `BASIC RAG` | BM25 top-k over that subject's units from **both** revisions |
| `TAVONEL` | that subject's compiled temporal world |

Same model, same decoding parameters, same questions, same top-k, same Stage 0.
The comparison is therefore **temporal / revision evidence selection**, not
document discovery.

**Secondary: W6-O, open-corpus retrieval.** The v7-style all-document candidate
pool is **not deleted**. It becomes a separate, exploratory benchmark for the
subject-title shortcut and intra-document unit collision. It is reported
separately and never mixed into the primary endpoint.

---

## 2. Leakage, in two layers

### 2A. Structural / taint gate — PRIMARY

The question builder may read **only**: `subject`, `attribute`, `date` where the
template requires one, and a fixed `template_id`.

It may **not** read: the value, the oracle sentence, the surrounding passage, or
any answer-bearing lexical context.

Enforced by a dataflow audit over the builder plus a receipt pinning the builder
by sha256.

**Positive falsification, required to run in the same execution:** a synthetic
mutant builder that injects one content token from the oracle passage into the
query **must** make the gate FAIL. A taint gate that has never rejected anything
is not evidence, and this programme has shipped detectors that could not fire.

### 2B. Residual lexical overlap — SECOND gate

Raw overlap is not used. Query tokens are labelled by provenance —
`SUBJECT`, `ATTRIBUTE`, `DATE`, `TEMPLATE` — and overlap is decomposed into:

- **structured-intent overlap** — tokens the template legitimately supplied
- **passage-derived residual overlap** — everything else

**The residual is the gate.** Thresholds are **not** set by looking at v7's
numbers and picking something that passes. The calibration *rule* is fixed here,
applied once to the v7 DEVELOPMENT distribution, and frozen before any v8
holdout title is chosen:

> residual median ceiling = the v7 development residual median, rounded up to the
> next 0.05, plus 0.05 headroom; residual p90 ceiling = the same construction on
> the development p90. Both recorded with the development distribution that
> produced them, in one receipt, before v8 acquisition.

Positive controls for 2B run in the same execution: a query with an injected
oracle token must exceed the residual ceiling, and an untouched query must not.

---

## 3. Baseline validity, redesigned for an entity-conditioned task

**`same-document top-1 share` is retired from the primary gate, and the reason is
recorded rather than the metric quietly swapped.** Under W6-T every candidate is
deliberately from the same subject's document family, so the metric no longer
measures difficulty — it is ~1.0 by construction of the task, not by weakness of
the question set. It remains a *reported* metric in W6-O, where it still means
what it meant.

The v8 primary gate is evaluated over at least:

| criterion | why |
|---|---|
| unit Recall@1, Recall@5 | can the right unit be found at all |
| exact-tie rate | v7 measured 0.1038; ties hide behind index order |
| candidate entropy | a degenerate score distribution is not a retrieval task |
| **before/after ambiguity** | share of questions whose two revisions are separable |
| **oracle vs strongest wrong-revision unit gap** | the discrimination actually under test |
| **stale-revision retrieval rate** | how often the superseded revision wins |
| distractor competitiveness | neither trivial nor degenerate |

**The strong distractor is `CORRECT SUBJECT + WRONG REVISION`, not a random
unit.** A temporal benchmark whose distractors are random passages measures
nothing about time. Bounds are two-sided, as in PROTOCOL_V2 §5: a ceiling is a
failure by rule.

---

## 4. BASIC RAG is built to be strong

If TAVONEL only beats a weak retriever, the result is not worth reporting.

`BASIC RAG` gets reasonable chunking, standard BM25, the same deterministic
entity routing, **both revisions indexed**, the same top-k, and no handicap. It
is denied exactly one thing — temporal metadata — because that is the variable
under test.

`BASIC RAG+` is added if a stronger non-temporal retriever is available at zero
additional cost from what the repository already has. **No new model intelligence
is given to TAVONEL alone.** If a capability cannot be given to the baseline, it
is not given to TAVONEL either.

The question is not *does TAVONEL beat a weak retriever*. It is: **with retrieval
capability controlled, does temporal compilation add anything on stale-answer
rate and provenance?**

---

## 5. Classes that are not forced

**Multi-document.** The §2 generator asks one attribute of one article, so
multi-document is a `GENERATOR_SCOPE_LIMITATION`, not missing data. It is
**removed from the v8 primary scope**. It returns only as a separate W6-MD
experiment with its own frozen generator over an independent structured
relationship source. Otherwise it stays
`MULTI_DOCUMENT = NOT_RUN / OUT_OF_PRIMARY_SCOPE`. No synthetic multi-hop
questions are manufactured for the primary.

**Conflicting evidence.** v7 measured 0 genuine overlapping-validity conflicts:
`before` validity ends exactly where `after` begins, so a superseded value is not
a conflict. That is a real corpus property. **No synthetic conflict enters the
primary W6.** If conflict handling needs evidence it is a separate controlled
adversarial experiment, reported separately and never merged with a natural W6
result.

---

## 6. The holdout, and what makes it untouched

**Every v7 title is development data.** The seal records **750** titles v7
fetched, resolved to, or excluded, out of the frozen 6,987-title manifest. The v8
holdout is drawn only from the **6,237** untouched titles, and the builder checks
against the sealed list rather than against a recollection.

Frozen before any title is chosen:

- deterministic manifest-order or hash-order selection — never selection on an
  outcome
- **article-level disjoint**; v7 title/revision overlap must be **0**, verified
  against the seal
- availability rule predeclared
- minimum primary n predeclared
- maximum acquisition budget and stop condition predeclared

---

## 7. Engineering finishes on v7 before the holdout is opened

This is the rule that protects the holdout. Discovering a harness bug after
acquiring v8 spends the holdout on a defect.

The entire pipeline — v8 question generator, structural taint detector, residual
lexical detector, entity routing, `RAW`, `BASIC RAG`, `TAVONEL` adapter, scoring,
statistics, receipts, failure paths, positive falsification — is built and
end-to-end verified **using the v7 development set only**.

**Arm results produced during that verification are DEVELOPMENT ONLY and may
never be reported as a paper endpoint.**

Only when every stage functions are the following frozen in one receipt: source
hashes · config · models · decoding · top-k · chunking · metrics · thresholds ·
exclusions · statistical tests. The v8 holdout is opened after that, and not
before.

---

## 8. Stop rule — frozen before the holdout

v8 is a **confirmatory** holdout.

- **Gates PASS** → run the three arms → report the endpoint and its statistics.
- **Gates FAIL** → report `endpoint NOT_RUN` or the failed pre-arm gate, as
  measured.

**A v8 gate failure does not authorize an immediate v9.** Amending the protocol
again on seeing a second failure would make every future run development, and
the confirmatory claim would never exist. A v9 requires a recorded decision, not
a reflex.

---

## 9. Endpoints and reporting

**Primary:** answer correctness on revision-sensitive questions.
**Primary comparison:** TAVONEL vs **strong** BASIC RAG. RAW is a floor.

Reported together, always, never selectively: stale-answer rate · temporal
correctness · evidence correctness · provenance localization · unsupported
assertion rate · appropriate abstention.

**Effect size and paired uncertainty are reported with every comparison.**
"Significant" or "not significant" alone is not a result. Paired by question;
McNemar for binary outcomes; per-class results reported separately with no
aggregate mean across classes.

Abstention scoring is unchanged from PROTOCOL_V2 §9: abstaining on an answerable
question is wrong, abstaining where evidence genuinely does not determine an
answer is correct, and confidently answering the latter is an unsupported
assertion. An arm cannot win by refusing to answer, and cannot win by guessing.

---

## 10. A negative result is a result

Five outcomes are all valid and all publishable as measured:

**A.** TAVONEL significantly better · **B.** similar correctness, lower stale
rate · **C.** no measurable advantage · **D.** worse · **E.** gate failure.

**If TAVONEL does not win, that is reported.** Redesigning the benchmark after
seeing the result ends the confirmatory claim — which is the same rule that kept
the B-EQUIV fresh-seed holdout unspent, and the same rule that made v7
development rather than a result.
