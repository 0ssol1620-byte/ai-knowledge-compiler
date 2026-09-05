# `arena.opus` — Claude Opus 5, Claude Code subscription surface (lane D)

Masterplan §21–22, ARENA_CONTRACT §7. Not a GPU runtime: this lane drives the
locally installed Claude Code CLI once per page and writes the same page receipt
every other model writes, with `runtime_mode: "subscription"`.

The results this lane produces are **Claude Code product-surface** results. They
include Claude Code's system prompt, its `Read` tool's image handling and its
own auxiliary model traffic. They are not an API raw-image benchmark and the
report must say so (MP §21.10). The public name of the row is exactly
`Claude Opus 5 — Claude Code subscription surface`.

## Commands

```
python -m arena.opus preflight              # host check; spends nothing
python -m arena.opus probe                  # ONE trivial call; proves auth + model id
python -m arena.opus canary                 # the frozen 50-page opus_canary block
python -m arena.opus run --execute          # the full pass (founder decision)
python -m arena.opus status                 # receipt counts + checkpoint state
python -m arena.opus resume --execute       # continue from checkpoint.json
python -m arena.opus verify                 # re-validate receipts on disk; spends nothing
python -m arena.opus canary-receipt          # re-emit receipts/canary-opus5_subscription.json; spends nothing
```

Flags: `--workers` (default 2, hard max 6), `--limit`, `--timeout` (default
600 s per page), `--effort` (default `high`), `--claude <path>`, `--case-key`
(repeatable, overrides selection).

Exit codes: `0` ok, `1` a page failed or the pool stopped, **`75` a
subscription / rate / capacity limit stopped the pool**, `2` usage error.

## Files

| file | what it owns |
|---|---|
| `command.py` | the per-page argv, the no-fallback assertion, model attribution |
| `env.py` | the scrubbed child environment and the preflight that blocks on `ANTHROPIC_API_KEY` |
| `limits.py` | `SUBSCRIPTION_LIMIT` / `RATE_LIMIT` / `TEMPORARY_CAPACITY` detection, with the source of every matched string |
| `runner.py` | the worker pool, the 2→N ramp, per-page receipts, checkpointing |
| `canary_receipt.py` | the shared-schema canary receipt (ARENA_CONTRACT 11.6 D37), derived from every page receipt on disk -- no new inference |
| `pricing.py` | API-equivalent list price from `price_snapshot.json` |
| `selection.py` | page resolution from the staged manifests; the frozen `opus_canary` block, cross-checked |
| `prompt.py` | prompt resolution (lane A4 registry wins; private copy is the fallback) |
| `paths.py` | atomic writes, canonical JSON, the secret-free check |
| `CLAUDE_CLI_FLAGS.md` | **the verified flag list**, the probe and the canary evidence |
| `price_snapshot.json` | Opus 5 list prices with source URL and captured_at |
| `_fallback_prompt_v1.txt` | MP §21.5 verbatim; byte-identical to the lane A4 registry copy |

## Identifiers and selection (ARENA_CONTRACT 11.5 D27)

Every identifier is derived through `arena.core.ids`; this lane holds no private
implementation of one. `inference_job_id` comes from the nine canonical fields,
`case_key` and `sample_id` from `case_key_from_staged` / `sample_id_from_staged`,
and `shard_id` from `shard_id()` at width 4 (`opus5_subscription-omnidoc-0000`).

`runtime_image_digest` is `subscription:claude-code-<cli version>-<model id>`,
e.g. `subscription:claude-code-2.1.252-claude-opus-5`. `env.subscription_image_digest`
checks the result against `arena.core.ids.RUNTIME_IMAGE_DIGEST_PATTERN` and
raises if the grammar is not accepted there: an identifier the shared module
would reject never reaches a receipt.

**The deterministic fallback selection is refused once `canary_selection.json`
exists.** The canary runs lane A2's frozen `opus_canary` block, and each page's
`sample_id` and `input_png_sha256` are cross-checked against what the staged
manifest derives. `--limit` may only trim that block; asking for more pages than
it holds is an error, never a top-up from elsewhere.

Every page receipt is validated against `page-receipt.schema.json` through
`arena.core.receipts.validate` before it is written; the outcome is recorded on
the receipt as `receipt_schema_valid` / `receipt_schema_error`, and a page whose
receipt does not validate is reported `FAILED`, never counted as a success.

## Canary receipt (ARENA_CONTRACT 11.6 D37)

`receipts/canary-opus5_subscription.json` is this lane's canary receipt in
the shared schema (`arena/core/schemas/canary-receipt.schema.json`) every
other lane's canary receipt uses. `gpu_type`/`pod_id`/`base_image`/the
authorization and pod-ledger fields are `null` -- a hosted subscription
surface has none of those -- and the ten masterplan section 17 criteria are
evaluated for a lane with no GPU: `vram_headroom` passes because there is no
VRAM to measure headroom on, `gpu_hours_projected` and
`raw_gpu_cost_projected_usd` are genuinely `0.0` (not a placeholder -- the
true GPU cost of a lane with no GPU), and the number that actually matters
for this lane -- projected wall-clock time and the API-equivalent list-price
floor for the full 5,132-page run, at p50 and p90 of the canary's measured
per-page distribution -- is carried in the extension field
`full_run_projection` (the schema is extension-open, D26).

The `canary` command writes this receipt automatically after every canary
run, from the complete set of page receipts on disk (not just the pages that
run just executed), so it stays correct across a `resume`. Run
`python -m arena.opus canary-receipt` on its own to re-derive it at any time
without running a single page -- this is also what a future canary run
should fall back on if the automatic write is ever skipped. Both paths call
`arena.opus.canary_receipt.build_canary_receipt`, which performs no new
inference: every field is derived from the receipts that are already on
disk, and the receipt is validated against the schema before it is written.

This is also the answer to "is anything in this lane's output cumulative
across resumes": `canary/run-summary.json` is not (see its docstring in
`runner.py`) but the canary receipt is, because it is rebuilt from every
receipt file on disk rather than from one invocation's in-memory report.

## The three rules this lane exists to keep

1. **No fallback.** `assert_no_fallback()` runs on every argv before dispatch and
   refuses `--bare`, `--fallback-model`, and any non-Opus model name. On a limit
   the pool stops, checkpoints and exits 75; it never downgrades and never
   switches to the API (MP §21.8, §43).
2. **No `$0/page`.** `actual_marginal_api_cost` is the string `"N/A"`,
   `subscription_included_usage` is `true`, and the separate
   `api_equivalent_list_price_usd` column carries the price-snapshot hash and,
   when cache tokens are unpriced, `api_equivalent_price_complete: false` with
   the uncovered components named (MP §22).
3. **The model is checked, not assumed.** Claude Code reports a Haiku entry in
   `modelUsage` beside the Opus one; the lane classifies that as an auxiliary
   model, records it separately, and fails the page with
   `UNKNOWN "unexpected model"` (stopping the pool) if any other model appears
   or if no Opus 5 entry does.

## Known gaps

- `--output-format json` does not emit `system/api_retry` events, so MP §21.9
  retry telemetry (`attempt`, `max_retries`, `retry_delay_ms`) is not captured.
  It needs `stream-json`, which changes the output contract; recorded as an open
  question rather than silently dropped.
- The limit-wording matchers are built on documented error *categories*
  (`rate_limit`, `overloaded`, `server_error` from the headless docs) plus the
  usage-limit wording family, because Anthropic's support article publishes no
  verbatim CLI string. Every detection records which pattern fired and where it
  came from, so a wrong matcher is visible in the checkpoint.
- `~/.claude/CLAUDE.md` (auto-memory) still loads into every child; only the
  forbidden `--bare` would remove it. Settings, hooks, MCP servers and project
  `CLAUDE.md` are all excluded — see `CLAUDE_CLI_FLAGS.md`.
