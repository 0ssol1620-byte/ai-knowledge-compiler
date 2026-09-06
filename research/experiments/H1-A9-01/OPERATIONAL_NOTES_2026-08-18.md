# A9 holdout — operational notes

Things observed while running the confirmatory holdout that are not research
findings but should not be lost. Each says what was seen, what was done, and
what was deliberately *not* done.

---

## 1. Leftover R2 objects from earlier campaigns

Five objects remain under `tavonel/stage1/hard200/` from campaigns that predate
this work. They are **flagged, not deleted.**

This run's own uploaded input bundle was deleted and its absence verified, and
the execution log confirms `r2_absence_verified: true` on all nine controller
attempts, including the seven that failed. So nothing this experiment created is
still sitting in object storage.

The five older objects are a different matter: deleting them would be an
irreversible action against artifacts belonging to work this session did not
run, and the constitution puts destructive data handling behind explicit
authorization. They are recorded here so that the next person to look at that
prefix knows they were seen and consciously left alone, rather than missed.

## 2. The 420-second vLLM health deadline is marginal on community hosts

Seven of nine controller attempts failed with `TimeoutError` against the sealed
v4 qualifier's 420-second assembly health deadline. Timing from one failure:
engine start 07:36:06, `torch.compile` 67.4 s, initial profiling/warmup 137.0 s,
health timeout at 07:42:33 — the deadline exactly, missed by seconds.

Both successful runs cleared the same deadline on the same GPU type and cloud.
The variable is community-host cold-start speed, not the deadline.

**No qualifier bytes were edited.** The qualifier is frozen contract, and
widening a health deadline to make a run pass is precisely the kind of change
that quietly converts a fail-closed check into a formality. Retrying was chosen
instead, and it worked on the sixth attempt.

If this recurs often enough to matter, the options that do *not* touch frozen
bytes are worth costing before any that do: constraining host selection toward
the faster CUDA pool, or reducing cold-start work that is not part of the
assembly's inference configuration. Neither was needed here.

## 3. Two controller defects fixed, both of the same shape

Both were constants that were correct for the 200-page campaign and wrong for an
800-page one, and both fired *after* the expensive work was already done:

- `stage1_same_pod_driver_v4` hard-codes a 90-minute inference timeout sized for
  200 pages. 800 pages at the measured rate lands within a minute of it, so a
  correct run would have been killed for being large. v5 reads the cohort size
  from the hash-bound shard manifest and scales the timeout from it.
- v10's result validation compares the returned receipt against a literal `200`
  in two places, and fired after the archive was downloaded and the Pod cleaned
  up. Run 1 completed 800 of 800 with zero failures and was then reported as a
  failure. v18 rebuilds that function from v10's own source with the count read
  from the bundle receipt, and raises if the expected literals are no longer
  there rather than silently binding an unpatched copy.

Run 1 was harvested from its existing archive rather than re-run. Re-running to
satisfy a constant that was itself wrong would have spent another half hour of
GPU and produced a *different* sample of a nondeterministic process — worse
evidence, not better, and in a two-run stability experiment it would have
silently changed what the second run was being compared against.

## 4. One post-unsealing code change, disclosed

`r4_marginal_analysis.py` read the second parser's prediction unconditionally
and raised `FileNotFoundError` on the holdout, where 15 pages have no MinerU
output. It was repaired after the primary test had already run and written its
receipt.

The repair aligns it with amendment 01 — a missing second-parser prediction
scores zero agreement and abstains — which is what the confirmatory test already
did. The primary test's code and result are untouched. Recorded in the protocol's
§10 as well, because a change made after unsealing must be disclosed even when
it is mechanical and even when it only affects a descriptive analysis.

## 5. A capture thread died during the deterministic re-score, and why it did not matter

During the corrected evaluator's 800-page pass, the harness printed:

    Exception in thread Thread-2 (_readerthread)
    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xbf in position 0

It comes from the runtime-environment capture step probing for a system package
manager on a Korean-locale Windows host: a child process emitted cp949 bytes
into a reader opened as UTF-8. Its only consequence is the recorded
`package_manager: unavailable`. Scoring, matching and artifacts are untouched,
and the run completed with all 800 pages scored.

It is recorded because of what it *could* have hidden rather than what it did.
The determinism contract's original evidence that no wall-clock fallback fired
was a count of `[match-timeout]` lines in captured stdout — and a dead capture
thread is exactly the failure that makes such a count silently read zero. The
right response to "the log might be incomplete" is not to trust the log harder.

So the contract now takes the count from two independent places: the log, and
the evaluator's own `stage_execution.json`, which records the timeout values
actually in force and the fallbacks actually taken. For this run both timeout
fields are `null` and both fallback counters are `0` across 800 pages. A run
that cannot produce its own record is now treated as unverified rather than as
clean, which is the distinction the log-only check could not make.
