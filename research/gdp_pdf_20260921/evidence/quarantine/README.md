# Quarantined cells - subscription session limit, 2026-09-21 full100 run

These rows are NOT measurements and are NOT in any denominator.

At order position 47 (native) / 50 (compiled) of the seeded order the Claude Max
subscription answered every call with `You've hit your session limit - resets 12:30am
(Asia/Seoul)`. That reply carries no `modelUsage`, so `surface.attribute_models` found no
Opus 5 model and the cell was written as `subject_failure=UNEXPECTED_MODEL`, a zero in the
denominator - for a call the subscription never ran.

That is an operational failure, not a semantic one, and the project constitution keeps the
two apart. The rows were therefore moved here rather than scored, and the tasks were re-run
after the session reset. `surface.py` now classifies a session limit as `RATE_LIMITED` and
`run.py` backs off and retries instead of recording a zero.

Nothing here was deleted: every quarantined row is preserved verbatim, and the raw prompts
and replies stay in the out-of-repo run store.

- cells.full.native.jsonl: kept 46, quarantined 54
- cells.full.compiled.jsonl: kept 52, quarantined 48
