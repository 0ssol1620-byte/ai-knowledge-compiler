# Verified `claude` CLI flags — Opus 5 subscription lane

Host: Windows 10 Home 10.0.19045.
Executable: `C:\Users\yspow\.local\bin\claude.EXE`
Version string, captured by `claude --version` with the scrubbed environment:

```
2.1.252 (Claude Code)
```

`runtime_image_digest` in every receipt of this lane is therefore
`claude-code-2.1.252`.

Every flag below was checked against the `claude --help` output of **this**
binary on 2026-09-03, and against the official docs
(<https://code.claude.com/docs/en/cli-reference>,
<https://code.claude.com/docs/en/headless>). The masterplan §21.4 draft command
is not used verbatim; the differences are listed at the end and each one has a
reason.

## The per-page command

```
<claude> -p
         --model opus
         --output-format json
         --permission-mode dontAsk
         --effort high
         --no-session-persistence
         --disable-slash-commands
         --strict-mcp-config
         --setting-sources project,local
         --add-dir <absolute directory holding the page PNG>
         --tools Read
         --allowedTools Read
```

with the prompt written to **stdin** and the child's cwd set to an empty
directory outside every repository.

## Flag-by-flag

| Flag | Verified in `--help` | Why this lane uses it |
|---|---|---|
| `-p`, `--print` | yes — "Print response and exit (useful for pipes)" | MP §21.4. Non-interactive. Also the flag whose docs state stdin is read. |
| `--model opus` | yes — "Provide an alias for the latest model (e.g. 'fable', 'opus', or 'sonnet')" | MP §21.4. The alias is passed; the *resolved* id is read back out of the payload and checked (see "Model attribution"). |
| `--output-format json` | yes — choices `text`, `json`, `stream-json` | MP §22 requires the whole JSON payload. |
| `--permission-mode dontAsk` | yes — choices include `dontAsk` | MP §21.4. Docs: "Claude Code denies anything not in your `permissions.allow` rules or the read-only command set", which is exactly the Read-only surface this benchmark wants. |
| `--effort high` | yes — "(low, medium, high, xhigh, max)" | MP §21.4. `xhigh`/`max` are not used: the masterplan pins `high`, and raising effort would change what is being measured. |
| `--no-session-persistence` | yes — "only works with --print" | MP §21.6 fresh context per page: nothing is written that a later page could resume. |
| `--disable-slash-commands` | yes — "Disable all skills" | ARENA_CONTRACT §7. Keeps a machine-local skill out of a benchmark page. |
| `--strict-mcp-config` | yes — "Only use MCP servers from --mcp-config, ignoring all other MCP configurations" | No `--mcp-config` is passed, so this loads **no** MCP servers. The headless docs warn that a `-p` session otherwise connects the servers in a project's `.mcp.json` with no approval prompt. |
| `--setting-sources project,local` | yes — "Comma-separated list of setting sources to load (user, project, local)" | Excludes **user** settings. See "Hooks" below. |
| `--add-dir <dir>` | yes — "Additional working directories for Claude to read and edit files" | The child's cwd is outside the repository, so the page PNG needs an explicit grant for `Read`. |
| `--tools Read` | yes — "Specify the list of available tools from the built-in set" | Restricts what exists. Docs for `--allowedTools`: "To restrict which tools are available, use `--tools` instead." |
| `--allowedTools Read` | yes (`--allowedTools, --allowed-tools`) | Auto-approves the one tool, so `dontAsk` cannot stall the run. |

### Not used, and why

- **`--bare` — forbidden** (MP §21.3). `--help` on this binary: "Anthropic auth
  is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings (OAuth and
  keychain are never read)." Using it would move the run onto API billing and
  make it a different experiment. `assert_no_fallback()` raises if it ever
  appears in argv.
- **`--fallback-model`** — refused by `assert_no_fallback()`. MP §21.8: no
  fallback, no downgrade, no API auto-switch.
- **`--dangerously-skip-permissions`** — refused. `dontAsk` + `--allowedTools`
  already removes prompting without removing the permission system.
- **`--json-schema`** — not used. The output contract is Markdown prose
  (MP §21.5), not a JSON object, and forcing a schema would change the task.
- **`--verbose` / `--include-partial-messages` / `stream-json`** — not used for
  the run. MP §21.9's `system/api_retry` capture requires `stream-json`; with
  `--output-format json` those events are not emitted, so retry telemetry is an
  accepted gap of this configuration and is listed in the lane's open questions.

### Prompt delivery: stdin, not a positional argument

`--tools`, `--allowedTools` and `--add-dir` are **variadic** (`<tools...>`,
`<directories...>`). A positional prompt placed after any of them is consumed as
another value for that option. Two ways out: keep all variadic options away from
the end of argv, or stop using a positional prompt. This lane does the second,
because the headless docs document it:

> Non-interactive mode reads stdin, so you can pipe data in and redirect the
> response out like any other command-line tool.
> — <https://code.claude.com/docs/en/headless>

Verified live by the qualification probe (below), which passed
`"Reply with the single word OK"` on stdin with `--tools Read --allowedTools
Read` as the final argv tokens and received `"result": "OK"`.

Piped stdin is capped at 10 MB per the same docs; the prompt is ~700 bytes.

### Hooks, CLAUDE.md, and why `user` settings are excluded

The headless docs are explicit that, without `--bare`, `claude -p` "loads the
same context an interactive session would, including anything configured in the
working directory or `~/.claude`". This machine's `~/.claude/settings.json`
carries hooks for `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
`PostToolUse`, `Stop` and more (the Hybrid Runtime). A `UserPromptSubmit` hook
can inject text into the prompt, which would silently contaminate every page of
the benchmark, and `SessionStart` hooks add startup latency to all 5,132 runs.

`--bare` is the documented way to skip hooks and is forbidden here, so the lane
uses the two legitimate levers instead:

1. `--setting-sources project,local` — the `user` source is not loaded, so the
   user-level hooks do not run.
2. The child's cwd is a fresh empty temporary directory **outside any
   repository**, so no project/`local` settings file and no project `CLAUDE.md`
   is discovered either. In combination, the child loads no settings file at all.

**Residual, recorded rather than hidden:** `~/.claude/CLAUDE.md` (auto-memory) is
not a settings source and is still loaded; only `--bare` would remove it. The
probe measured 11,947 `cache_creation_input_tokens` for a two-token prompt, which
is the size of Claude Code's system prompt plus tool definitions plus that
memory file. Every receipt therefore records `surface:
"claude-code-read-tool"`, and the results table must say these are Claude Code
product-surface numbers, not API raw-image numbers (MP §21.10).

## Model attribution — the probe found two models

`--output-format json` returned a `modelUsage` map with **two** keys:

```
"modelUsage": {
  "claude-haiku-4-5-20251001": { "inputTokens": 898,  "outputTokens": 11, "costUSD": 0.000953 },
  "claude-opus-5":             { "inputTokens": 2,    "outputTokens": 4,
                                 "cacheReadInputTokens": 1247,
                                 "cacheCreationInputTokens": 11947,
                                 "costUSD": 0.1202035,
                                 "canonicalModel": "claude-opus-5",
                                 "contextWindow": 1000000 }
}
```

Claude Code spends a little Haiku on its own housekeeping inside a `-p` run.
That is a property of the product surface, **not** a model fallback, so:

- `arena.opus.command.attribute_models` splits the reported models into
  Opus 5 / auxiliary (Haiku) / unexpected.
- A page is `FAILED / UNKNOWN "unexpected model"` and the pool stops if there is
  no Opus 5 entry, or if any model outside those two groups appears
  (MP §43 "unexpected fallback model").
- Benchmark token and price columns come from `modelUsage["claude-opus-5"]`, not
  from the merged figure; the Haiku tokens are recorded separately under
  `auxiliary_model_usage`.

A naive "first reported model" rule would have labelled every page as Haiku.

## Qualification probe — 2026-09-03

One trivial call, receipt at `receipts/opus-probe-20260903T061306Z.json`.

| | |
|---|---|
| exit code | `0` |
| wall clock (process spawn to exit) | **6.018 s** |
| `duration_ms` (payload) | 1,628 ms |
| `duration_api_ms` (payload) | 2,496 ms |
| `result` | `"OK"` |
| `is_error` / `subtype` | `false` / `"success"` |
| resolved model | `claude-opus-5` (`canonicalModel: "claude-opus-5"`, 1,000,000-token context) |
| usage (Opus entry) | input 2, output 4, cache-creation 11,947, cache-read 1,247 |
| `total_cost_usd` (client estimate) | 0.12115650 |
| nesting guard | **did not interfere** — the CLI ran normally inside a Claude Code session once `CLAUDECODE` and every `CLAUDE_CODE_*` variable was scrubbed |
| stderr | empty |

So ~4.4 s of the 6.0 s wall clock is process startup and context assembly, and
that fixed cost is paid **once per page** because MP §21.6 requires a fresh
process. That is the dominant scheduling fact for the full run.

**Cost warning that follows from the probe:** 11,947 cache-creation tokens
dwarf the page's own tokens, and `price_snapshot.json` has no published Opus 5
cache price. `api_equivalent_list_price_usd` therefore covers only uncached
input + output and every receipt carries
`api_equivalent_price_complete: false` with the uncovered components named. Do
not present that number as the full API-equivalent cost of this surface.

## Canary — 3 real pages, 2026-09-03 (SUPERSEDED)

> **Superseded by the 50-page canary below (ARENA_CONTRACT 11.5 D27).** These
> three pages were chosen by this lane's deterministic fallback while
> `canary_selection.json` already existed, and their receipts carry
> `runtime_image_digest: "claude-code-2.1.252"`, which is not the
> `subscription:<label>` grammar. Both are now refused by the code. The section
> is kept because the command shape and the auxiliary-Haiku observation it
> established still hold; the numbers are not Arena evidence. The original files
> are preserved under
> `runs/opus5_subscription/canary/superseded-20260903T062142Z/` with per-file
> hashes in `receipts/opus-canary-superseded-20260903T062142Z.json`.

`python -m arena.opus canary --limit 3 --workers 2 --timeout 600`, exit 0.
Receipt: `receipts/opus-canary-20260903T062142Z.json`; per-page receipts under
`runs/opus5_subscription/canary/receipts/`. Pages chosen by the deterministic
fallback rule (lane A2's `canary_selection.json` did not exist yet): staged
OmniDocBench PNG names sorted by `sha256(name + CANARY_SALT)`.

| case_key | page px | bytes | wall s | in tok | out tok | cache write | cache read | out chars | API-equiv $ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `omnidocbench-f8cef2c074dd95a5d82ee18b` | 2000×1500 | 1,249,910 | 9.86 | 4 | 444 | 16,340 | 14,780 | 827 | 0.01112 |
| `omnidocbench-b73fb773014faab7624b88b1` | 1654×2339 | 454,449 | 15.46 | 4 | 763 | 16,162 | 14,776 | 1,312 | 0.019095 |
| `omnidocbench-2f33ac283a5cb9416aa0e83a` | 2000×1500 | 324,958 | 6.92 | 4 | 258 | 13,458 | 17,672 | 178 | 0.00647 |

Every page: `reported_model = claude-opus-5`, `num_turns = 2` (one `Read` call
then the answer), `conversion_notes = []` (no fence to unwrap, no whitespace to
strip), `is_error = false`, empty stderr. Output was faithful Markdown including
CJK exam text and LaTeX in a figure description, so `--tools Read
--allowedTools Read --add-dir` genuinely gives the model the page.

Three numbers that matter for planning the full run:

1. **`input_tokens` is 4 on every page.** The image and the prompt land in the
   *cached* prefix, so the uncached input column is meaningless here and the
   API-equivalent price is essentially output-only. With cache prices
   unpublished, the printed `api_equivalent_list_price_usd` is a **floor**, not
   the figure. `api_equivalent_price_complete` is `false` on all three receipts.
2. **13k–18k cache-creation tokens per page**, paid on every fresh process.
   MP §21.6 requires the fresh process, so this cost is structural.
3. **6.9–15.5 s per page** at 2 workers. Extrapolating 5,132 pages at ~10.7 s
   mean and 6 workers gives roughly 2.5 hours of wall clock if no limit is hit;
   that is a projection from three pages, not a measurement.

## Canary — the frozen 50 pages, 2026-09-03 (ARENA_CONTRACT 11.5 D27)

`python -m arena.opus canary --workers 2` over
`canary_selection.json["opus_canary"]` — 50 pages, 16 olmOCR-bench / 17
OmniDocBench / 17 ParseBench. Every page's `sample_id` and `input_png_sha256`
were cross-checked against the staged manifest before the first process started.

It took two invocations, and the reason is itself a result:

| # | command | pages | exit | outcome |
|---|---|---:|---:|---|
| 1 | `canary --workers 2` | 11 | **75** | 10 SUCCESS, 1 `INFRA_CAPACITY`; pool stopped on `TEMPORARY_CAPACITY` and checkpointed |
| 2 | `resume --workers 2` | 39 | 0 | 39 SUCCESS |

Campaign receipts `receipts/opus-canary-20260903T084836Z.json` and
`receipts/opus-canary-20260903T085449Z.json`; the 50-page aggregate is
`receipts/opus-canary-aggregate-20260903T085601Z.json`. Per-page receipts are
`runs/opus5_subscription/canary/receipts/` — exactly the frozen 50, all 50
validated by `arena.core.receipts.validate` with every id re-derived through
`arena.core.ids` (`python -m arena.opus verify`, exit 0, 50/50 ok).

**49 SUCCESS, 1 FAILED.** The failure is
`olmocr-bench-83a5e23571dfcfe2482ddf35`: after 201 s the payload carried
`api_retry error=overloaded`, classified `TEMPORARY_CAPACITY` →
`INFRA_CAPACITY`. That is an operational failure, not a semantic one — the model
was not wrong, the surface was busy. **It was not retried**: the runner retries
nothing, and overwriting the receipt would erase the only record of the capacity
event. It stays `FAILED` with `attempt: 1`.

Per-page wall clock, 49 successful pages, 2 workers (nearest-rank percentiles,
rank = `ceil(q·n)`):

| min | p50 | p90 | p95 | max | mean |
|---:|---:|---:|---:|---:|---:|
| 6.53 s | **17.18 s** | **31.42 s** | **34.03 s** | 43.06 s | 18.48 s |

Per benchmark: olmOCR p50 20.64 s / p95 43.06 s (n=15) · OmniDocBench p50
17.18 s / p95 32.58 s (n=17) · ParseBench p50 15.41 s / p95 34.03 s (n=17).
This is host wall clock for a whole fresh `claude -p` process — Claude Code
start-up and its `Read` tool included — not a server-side inference time.

**API-equivalent list price: $1.649 for 49 pages, mean $0.0337, p50 $0.0291 —
and every one of those is a FLOOR.** `api_equivalent_price_complete` is `false`
on all 49 receipts, for the reason the 3-page canary already found and this run
confirms at scale: `input_tokens` is 4 on every page because the image and the
prompt land in the cached prefix, and `price_snapshot.json` has no cache prices.
Cache-creation tokens ran 10,137–16,530 per page (p50 12,191), paid on every
page because MP §21.6 requires a fresh process. Output tokens 170–3,397
(p50 1,162). **Do not publish these as the API cost of this workload.**

Every page reported `claude-opus-5`; no other primary model appeared. Every
receipt carries `runtime_image_digest:
subscription:claude-code-2.1.252-claude-opus-5`, `runtime_mode: subscription`,
`actual_marginal_api_cost: "N/A"`, `subscription_included_usage: true`. Shard
ids are `opus5_subscription-<benchmark>-0000` (width 4).

One planning number: at this p50 and 2 workers, 5,132 pages is roughly 12 hours
of wall clock; at the §21.7 ceiling of 6 workers, roughly 4 hours — **if no
capacity event intervenes, and one did within the first 11 pages.** The full run
needs an operator watching for exit 75, not a fire-and-forget launch.

## Difference from the masterplan §21.4 draft

| MP §21.4 | Here | Reason |
|---|---|---|
| prompt as positional argument | prompt on stdin | variadic `--tools`/`--allowedTools`/`--add-dir` swallow a trailing positional |
| (not mentioned) | `--disable-slash-commands` | ARENA_CONTRACT §7 |
| (not mentioned) | `--strict-mcp-config`, `--setting-sources project,local`, `--add-dir` | hook/MCP/CLAUDE.md isolation without `--bare`; file access for `Read` |
| flag order as written | variadic flags moved to the end | argv parsing, above |

MP §21.4 itself says "실제 사용 전 설치된 Claude Code 버전에서 `claude --help`와
공식 docs로 flag를 재검증한다" — this file is that re-verification.
