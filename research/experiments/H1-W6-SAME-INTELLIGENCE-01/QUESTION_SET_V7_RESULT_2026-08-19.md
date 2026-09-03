# W6 corpus-v7 question set — arms NOT RUN, blocked at the frozen pre-arm gates

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

Protocol: `PROTOCOL_V2_2026-08-19.md`, frozen 2026-08-19 before any v2 question
existed and **not amended for this run**.

Receipts:

- `receipts/question-set-v7-2026-08-19.json`
- `receipts/v7-pre-arm-gates-2026-08-19.json`

No LLM. GPU cost $0.00. No network. `corpus-v7` unmodified.

**`QUESTION_SET_V2_RESULT_2026-08-19.md` and
`receipts/question-set-v2-2026-08-19.json` are neither edited nor superseded.**
They are the correct finding for the old consecutive-revision corpora. This is a
separate finding for a different corpus.

---

## 1. The corpus blocker is gone. A different one is now visible.

v2 reported the primary endpoint NOT RUN for one reason: **0 revision-sensitive
questions against a required 60**, because the Family B corpora were revision
pairs minutes apart and structured facts do not move in that window.

corpus-v7 was acquired against exactly that diagnosis — snapshots 2023-06-30 and
2026-06-30, minimum separation 1,095 days — and it worked:

| class | required | v2 produced | **v7 produced** | state |
|---|---|---|---|---|
| simple retrieval (control) | 40 | 73 | **2,522** | SUFFICIENT |
| **revision-sensitive (primary)** | **60** | **0** | **293** | **SUFFICIENT** |
| conflicting evidence | 30 | 0 | **0** | NOT RUN — insufficient real cases (corpus property) |
| multi-document | 30 | 0 | **0** | NOT RUN — GENERATOR_SCOPE_LIMITATION |
| provenance-sensitive | 40 | 0 | **293** | SUFFICIENT |

293 revision-sensitive questions across **151 articles**, from 272 of 391 pages
with parsable infoboxes.

**The acquisition's own attribute lists were cross-checked, not trusted.** Both
revisions of all 391 pages were reparsed with the frozen v2 parser and compared
against `changed_attributes` in the acquisition receipt: **0 disagreements**.

**The instrument was imported, not copied.** `infobox_facts`, `SKIP`,
`VALUE_NOISE` and the three §2 templates come from `build_question_set_v2.py` at
a pinned sha256. A reimplementation would have made the two question sets
incomparable, and the v2 finding is the thing this run is measured against.

## 2. Two classes are NOT RUN, and for different reasons

PROTOCOL_V2 §1 excuses a class that *the corpus* cannot supply. It does not
excuse a class the *generator* cannot express, and conflating the two would
report a design limit as a data limit.

**Conflicting evidence — 0, measured.** Every `(subject, attribute)` pair's
value assertions were laid out with their validity intervals and checked for two
different values over *overlapping* validity. `before`'s interval ends exactly
where `after`'s begins, so a superseded value is not a conflict. §3 forbids
manufacturing one. **This is a corpus property.**

**Multi-document — 0, by construction.** Every question is one attribute of one
article's infobox and is answerable from that one document. No amount of corpus
would change this: it follows from the §2 template rule, which is frozen.
**This is a generator property**, and producing multi-document questions needs a
different generation rule and a new protocol, not a looser reading of this one.

## 3. The pre-arm gates fail. The arms did not run.

§3 says a set breaching the leakage criteria **is discarded before any arm runs**,
and §5's baseline gate is re-run before any arm. Both fail.

### §3 leakage — FAIL on all three template forms

| form | median (≤ 0.50) | p90 (≤ 0.75) | verbatim (= 0) | verdict |
|---|---|---|---|---|
| `query_current` | **0.750** | **0.857** | 0 | FAIL |
| `query_as_of` | **0.750** | **0.857** | 0 | FAIL |
| `query_provenance` | **0.600** | **0.820** | 0 | FAIL |

n = 265 of 293 (28 gold values could not be localised to a unit; §4 below).

### §5 baseline validity — FAIL on 6 of 8, §4 pool PASS on both

| criterion | bound | measured | verdict |
|---|---|---|---|
| Recall@1 | 0.30 – 0.90 | **0.1887** | FAIL (below) |
| Recall@5 | 0.60 – 0.98 | **0.5925** | FAIL (below) |
| exact-tie rate | ≤ 0.05 | **0.1038** | FAIL |
| median overlap | ≤ 0.50 | **0.750** | FAIL |
| p90 overlap | ≤ 0.75 | **0.857** | FAIL |
| same-document top-1 share | ≤ 0.80 | **0.9585** | FAIL |
| candidate entropy | ≥ 1.5 bits | 3.304 | PASS |
| revision-leaking queries | 0 | **37** | FAIL |
| §4 median score gap | > 0 | 0.223 | PASS |
| §4 p25 gap < 3× median | — | 0.055 < 0.670 | PASS |

**Note the direction.** v1 failed by being too easy — Recall@1 0.9969, overlap
1.0, a task that could not fail. This fails in the opposite direction on recall:
BM25 finds the right *document* almost always (0.9585) and the right *unit*
rarely (0.1887). Both are the same mechanism, described below.

## 4. Why — and acquiring more pages of the same kind would not change it

**§2's template mandates the subject. The subject is the article title. The
article contains its own title.**

Measured rather than argued: of the tokens shared between query and oracle, the
median share contributed by the subject's own name is **0.667**. Recomputing the
same overlap with the subject's tokens excluded — recorded as a labelled
DIAGNOSTIC that **did not enter any gate verdict**:

| form | gate median → diagnostic | gate p90 → diagnostic |
|---|---|---|
| `query_current` | 0.750 → **0.500** | 0.857 → **0.667** |
| `query_as_of` | 0.750 → **0.500** | 0.857 → **0.667** |
| `query_provenance` | 0.600 → **0.333** | 0.820 → **0.667** |

Every form lands inside §3's thresholds once the subject's own name is removed.
**The breach is the article containing its title, not the answer leaking into the
question.** Verbatim containment is 0 across all three forms — the failure §3 was
written to catch is absent.

The same mechanism drives §5: title tokens dominate the BM25 query, so the right
document wins (0.9585 same-document top-1) while the answer-bearing unit inside
it does not (0.1887 Recall@1).

**Under the v7 subject-titled representation, the frozen §2 templates, and the
current BM25 / section-unit-indexing baseline, the §3 and §5 gates could not be
jointly satisfied.** That is the claim the measurement supports and it is
deliberately no wider.

**This is a protocol-design finding, not an impossibility result.** Nothing here
was measured over other retrieval architectures, other chunkings, other subject
representations, or other admissible baselines, so nothing here says a
satisfying configuration does not exist. It says this one did not satisfy them.

It is the first run in which the question could be asked at all: §3 is evaluated
on the primary class, and until corpus-v7 the primary class was empty. v1 and v2
could not have surfaced it.

**A measurement defect was fixed first, before the gate result was accepted.**
The oracle matcher initially localised 205 of 293 gold values by raw substring;
`section_units` normalises the body, so `Group&nbsp;1` in wikitext is `Group 1`
in the unit. The frozen retrieval tokenizer localised 249 but drops pure numerals
— and "1995" is an answer. A value-presence matcher that keeps numerals and drops
markup tokens localises **265**. A gate failing on a broken measurement is not a
finding, and the first two readings were not reported as one.

## 5. What was deliberately not done

- **No template changed.** §2 is frozen.
- **No threshold moved.** §3 and §5 are frozen, and the diagnostic in §4 above is
  labelled as such precisely so it cannot be read as a relaxed gate.
- **No question, cohort or class dropped** to improve a number. The 28
  unlocalisable gold values are excluded from *retrieval and provenance*
  measurement only, before any arm scored anything, and they remain valid for
  answer correctness — the gold is known from the acquisition.
- **No arm was run.** Running arms behind a failed §3 gate would produce a number
  the protocol forbids reporting.

## 6. Status

**`endpoint_status: NOT_RUN`.** The reason has changed and the change is the
result:

| | v2 | **v7** |
|---|---|---|
| blocker | corpus had no revision-sensitive cases | **§2 templates vs §3/§5 gates, under this representation and baseline** |
| primary class | 0 of 60 | **293 of 60** |
| more pages of the same kind would help | yes — and they did | **no; the gate outcome is driven by representation, not by n** |

The corpus blocker is fully resolved. What blocks the endpoint now is a conflict
between two frozen sections of the protocol **as instantiated by this question
representation and this baseline**, discovered by running it.

**The next step is a founder/scientific decision and is not an agent's call.**
It is a change to what a public claim would rest on, and the options are not
equivalent:

1. Amend §3 to measure overlap on the query *excluding the subject's own name*,
   with the rationale that the subject is the question's addressing information
   and not its answer. The diagnostic above says all three forms would then pass.
2. Amend §2 to a generation rule whose queries do not name the subject — which
   changes what is being asked, and needs its own leakage argument.
3. Accept the endpoint as NOT RUN and publish the conflict as the finding.

Each is a new protocol version frozen before the arms run, and under §10 any of
them makes this run **development**, requiring an untouched holdout. That cost is
real and is the reason the decision is not being made here.
