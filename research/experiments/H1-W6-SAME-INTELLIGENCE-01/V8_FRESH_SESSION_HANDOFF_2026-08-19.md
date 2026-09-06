# v8 holdout — fresh-session handoff

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.
`HOLDOUT_STATUS = UNOPENED`.

**Opening the v8 holdout is a provenance boundary and is done in a fresh
session.** Not because this session lacks the code --- the pipeline is complete
and green --- but because the moment a holdout title is read is the moment the
confirmatory claim starts, and it should start from a session that reconciled the
live repository rather than one carrying a long working context.

This session's runtime is additionally pinned to a superseded generation:
`hybrid_goal_update_intent` returns `STALE_RUNTIME_SESSION` with
`canonical_mutation: 0`. Reads are unaffected; no goal, epoch, acceptance or DAG
write can land from here. **That blocked the canonical record, not the
development work**, which is why A6.5 was finished here.

---

## Do not redo any of this

It is done, tested and green. Re-running the development pipeline in the new
session would waste time and, worse, invite tuning after the fact.

| piece | state |
|---|---|
| §2A structural taint gate | built, `PASS`, 3 mutants caught 711/711 |
| §2B residual gate | built, `CALIBRATED`, ceilings frozen at 0.05 / 0.05 |
| Stage 0 entity routing | built |
| §3 baseline validity gate | built; `PASS` on the v8 question set |
| v8 question generator | built; markup-only admission defect fixed |
| `RAW` · `BASIC_RAG` · `BASIC_RAG_PLUS` · `TAVONEL` | built |
| fairness contract | built, control separates |
| answer normalization + scoring | built, control separates |
| paired statistics | built without scipy, control separates |
| deterministic end-to-end run | 177 questions × 4 arms, all controls separate |
| RAW context-budget measurement | built |
| fail-closed pre-holdout gate | built, 15/15 break-controls refuse |
| config-freeze builder | built, refuses without the decisions |
| repository | **GREEN** --- 2,955 collected, 2,909 passed, 0 failed, 46 skipped |
| v7 development seal | **INTACT** --- 13 artifacts, 0 drift |

Findings and their evidence: `V8_DEVELOPMENT_FINDINGS_2026-08-19.md`.

---

## Three decisions gate the freeze, and none is an agent's call

The pre-holdout gate currently refuses and names each one.

**1. Model identity.** The protocol pins "the same frozen model" without naming
one. Everything is built against an injectable interface. The freeze needs the
model id, its version or hash, and the decoding config. Until then the arms run
against `ExtractiveDevelopmentModel`, which performs no inference and is marked
`is_real_model: false` so its output cannot be mistaken for a result.

**2. RAW context-budget policy** (findings §6b). Under the shared 3,000-token
budget RAW truncates on **0.8701** of questions and loses the oracle on
**0.5763**. Its floor is therefore set by context budget, not by knowledge
representation.

- `SHARED_BUDGET_RAW_IS_BUDGET_LIMITED` --- one declared budget for every arm,
  and every report says RAW is a *budget-limited* floor in those words.
- `RAW_GETS_WHOLE_DOCUMENT_BUDGET` --- RAW gets enough context for both whole
  documents, stated as a deliberate asymmetry favouring the floor.

Leaving it unstated is the only unacceptable option: it turns a context-window
effect into what reads as a representation effect.

**3. Separability disposition** (findings §6a). `before_after_separable_share` is
**1.0 by construction** --- the generator admits on the same value-token
comparison the gate measures.

- `GENERATOR_INTEGRITY_CHECK_ONLY` --- declared a generator check, excluded from
  difficulty evidence.
- `REPLACED_BY_INDEPENDENT_METRIC` --- a replacement designed from v7 development
  data with its own positive control, frozen before the holdout.

Choosing a replacement *after* seeing v8 results would end the confirmatory
claim, which is why this is decided now rather than later.

---

## The order for the fresh session

1. Reconcile the live repository; confirm the runtime generation is current and
   canonical mutation is accepted.
2. Verify every development artifact hash --- `seal_v7_development.py` must print
   `SEAL INTACT`.
3. Update the canonical goal state, which this session could not do.
4. Take the three decisions and write the freeze:

```bash
.venv/Scripts/python.exe research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/freeze_config_v8.py --model-id <id> --model-version <version-or-hash> --decoding '{"temperature": 0.0, "max_tokens": 256}' --raw-context-budget-policy <policy> --separability-disposition <disposition>
```

5. Re-run the freeze command with no arguments; it must print `FREEZE INTACT`
   and refuse to overwrite.
6. Run the full repository suite and confirm `repository_green: true`.
7. Run the pre-holdout gate; **every** condition must pass:

```bash
.venv/Scripts/python.exe research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/preflight_holdout_v8.py
```

8. Only then build the holdout manifest from the untouched titles and acquire.

**The holdout is opened once.** Question set → leakage gates → baseline validity
gates. If they pass, run the four arms and report the endpoint with effect size,
paired difference, confidence interval and discordant counts. If they fail,
report the failed pre-arm gate as measured. A v8 gate failure does not authorize
an immediate v9 --- amending again on a second failure would make every future
run development, and the confirmatory claim would never exist.

**If TAVONEL does not win, that is reported.** A, B, C, D and E are all valid
outcomes. Redesigning the benchmark after seeing the result ends the
confirmatory claim.

---

## Not done, and not to be done before the above

- the holdout manifest from the 6,237 untouched titles
- holdout acquisition
- the v8 pre-arm gates on holdout questions
- the four arms on holdout data
- the endpoint and its statistics
- patent and paper synchronisation, which waits on the W6 result

Nothing in this experiment has opened, read, inspected, previewed or dry-run a
holdout title.
