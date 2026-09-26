# Session Record — 2026-09-23

*Everything discussed, everything done, everything left. Written so that a
person who was not in the session can act on it without asking a question.*

The current open founder list is
[`V5_FOUNDER_ACTIONS_2026-09-23.md`](V5_FOUNDER_ACTIONS_2026-09-23.md); this
file is the fuller record behind it, including the work that is finished and
the reasoning that produced it.

---

## Contents

- [0. What was asked](#0-what-was-asked)
- [1. Stop the line — CI has not run since 2026-09-22](#1-stop-the-line--ci-has-not-run-since-2026-09-22)
- [2. The parse router: what was wrong and what was built](#2-the-parse-router-what-was-wrong-and-what-was-built)
- [3. The model research, and what it actually says](#3-the-model-research-and-what-it-actually-says)
- [4. Registry corrections](#4-registry-corrections)
- [5. Licences — captured, not asserted](#5-licences--captured-not-asserted)
- [6. GPU serving — what was run and what it cost](#6-gpu-serving--what-was-run-and-what-it-cost)
- [7. Customer-facing copy sweep](#7-customer-facing-copy-sweep)
- [8. The 24 red API tests — not a defect](#8-the-24-red-api-tests--not-a-defect)
- [9. Mistakes made in this session](#9-mistakes-made-in-this-session)
- [10. Branches, PRs and artifact paths](#10-branches-prs-and-artifact-paths)
- [11. Remaining work — founder](#11-remaining-work--founder)
- [12. Remaining work — engineering](#12-remaining-work--engineering)
- [13. Open questions](#13-open-questions)

---

## 0. What was asked

Carried in from earlier sessions: finish production gates, solve the model
router, publish the website and go live, sweep the UI for defects and for copy
that damages trust.

Stated directly by the founder, in order:

1. The router meant is the **parse/OCR router that varies models by document
   difficulty before World creation** — not the retrieval embedder router.
   Wipe the `0ssol1620@gmail.com` workspace. Why are "접근권한요청" buttons in
   those positions. The UI has a lot of dead whitespace ("디테일 검수 제대로
   안했어?"). Find and clean **all** copy that exposes what customers do not
   need to know.
2. "arena 할때 모델들 어떻게 활용할지 연구했던거같은데 PaddleOCR-VL이 제일
   좋았어? 다른건?"
3. "응 그럼 이제 연구 결과를 바탕으로 최적화한거 실서비스에서 사용되도록해야지"
4. "푸쉬하고 발행 모두 완료해. 모두 사용 가능한 라이센스야. GPU 서빙 승인할게.
   그리고 남은 작업들이나 파운더 결정 필요한것들 업데이트하고 경로알려줘"
5. This document.

---

## 1. Stop the line — CI has not run since 2026-09-22

**Every GitHub Actions job on `0ssol1620-byte/ai-knowledge-compiler` fails in
one to five seconds**, on every branch, with:

> The job was not started because recent account payments have failed or your
> spending limit needs to be increased. Please check the 'Billing & plans'
> section in your settings.

`main`'s own run on 2026-09-22 failed the same way, so it predates anything in
this session. The Vercel check reports `Deployment was blocked` beside it.

Why this sits above everything else:

- **A red check on this repository currently means *unknown*, not *failing*.**
  PR #76's checks are red for this reason alone; its tests pass locally.
- **Nothing can be merged on evidence.** `CLAUDE.md` makes a phase done only
  when the repository is green, and there is no green available.
- **Nothing deploys.** `main` auto-deploys production through the same account.

Fix: settle the failed payment or raise the Actions spending limit under
**Billing & plans**. It is a payment credential, so no agent can touch it.

Diagnosing it again later: `gh run view <run-id> --repo
0ssol1620-byte/ai-knowledge-compiler` and read the **ANNOTATIONS** block. The
per-job `--log` is not fetchable, because no log exists — the job never ran.

---

## 2. The parse router: what was wrong and what was built

### What was actually wrong

`RouteDecision.require_cross_check` has been a boolean since the router was
written. It said a page deserved a second read and **never said by whom**. In
practice the choice fell to whatever the caller had, which on this deployment
is one model — so the "cross-check" was a second opinion from the same opinion.

Two related findings:

- `ChampionMatrix` exists but is empty machinery: no production caller.
- The router is **closed by design, not unfinished**. `ready_routes` is
  computed per request from the `model_registry` database table; `_binding`
  refuses a row without an endpoint, a revision, a runtime image digest, a
  model id and an adapter version, and `validate_registry_binding` additionally
  refuses one with no benchmark report. Only `native` is open because **no rows
  exist anywhere** — production Supabase `tfcorhjkqcuisqhsjemz` has no
  `model_registry` table at all, and `foundation_model_attempt_*` and
  `model_provider_*` are all 0 rows.

### What was built

`akc_router.complementarity` — 120 measured rows, **generated from the frozen
artifact rather than typed**, bound to two sha256 digests. `RouteDecision`
gains `cross_check_route` and `cross_check_element`, both optional and
defaulting to `None` so decisions serialized earlier still validate. A model
validator refuses a half-filled pair, a self-check, and a peer without
`require_cross_check`.

`engine._require_ready_route` — the one funnel every non-terminal decision
already passes through — fills them by asking the page which element dominates
it and asking the rescue table who recovers that element for the chosen route.

**No measurement means no second read.** The decision keeps
`require_cross_check`, gains the reason code `cross_check_peer_unavailable`, and
names nobody. There is deliberately **no default partner**: a second reader
chosen without evidence is a guess wearing the word "check", and would be
exactly the silent fallback `CLAUDE.md` forbids.

`dominant_element` compares `PageMetrics.formula_density` against
`PageMetrics.table_density` — two measured densities against **each other**, no
absolute cut-off — so nothing depends on a threshold this repository has not
calibrated. It is not the scalar blind quality score the campaign published as
*not supported*.

Reading order is measured but never routed on: it is a property of a whole page
rather than a region, and was scored over a different page set (1,638 against
1,557 for text).

### Verification

63 router and preflight tests pass, `ruff` clean, `mypy` clean,
`validate_registry.py` passes, the model-registry readiness contract test
passes. `test_complementarity.py` re-reads both artifacts and fails if a digit
drifts.

---

## 3. The model research, and what it actually says

### Answering "was PaddleOCR-VL the best?"

No — and more usefully, **the question does not have a stable answer.** The
Model Arena of 2026-09-05 ran thirteen open-weights readers over the whole of
OmniDocBench (1,651 pages each, scored by the benchmark's own end2end
quick_match evaluator).

| Benchmark | Leader | PaddleOCR-VL-1.6 | ovisocr2 |
|---|---|---|---|
| OmniDocBench text edit distance | `ovisocr2` 0.0290 | 0.0426 (2nd) | **1st** |
| olmOCR-Bench (1,403 docs / 8,413 checks) | `mineru_vlm` 0.806 | 0.781 (3rd) | 0.679 (**9th**) |
| ParseBench chart extraction | `mineru_vlm` 0.605 | ~0.01 | ~0.01 |

`olmocr2` is second on olmOCR-Bench at 0.799. The model that leads one
benchmark sits in the bottom third of the other. Chart reading is effectively a
capability one model has and eleven do not.

### The research that is actually actionable

Not the leaderboard — the **complementarity matrix**. The 2026-09-06 study
reused the per-page edit distances the campaign had already produced (no new
inference, `gpu_spend_usd: 0`) and asked: *given the reader that ran, which
other reader is right on the pages it got wrong?* With "wrong" as `edit > 0.05`:

| element | baseline | best rescuer | rescue rate | denominator |
|---|---|---|---|---|
| text | paddleocr_vl_1_6 | ovisocr2 | 44.0% | 316 wrong of 1,557 scored |
| formula | paddleocr_vl_1_6 | **infinity_parser2_flash** | 15.2% | 158 wrong of 313 scored |
| table | paddleocr_vl_1_6 | ovisocr2 | 22.2% | 135 wrong of 458 scored |
| reading order | paddleocr_vl_1_6 | ovisocr2 | 18.9% | 720 wrong of 1,638 scored |

**The formula row is why the table is worth having**: the best partner for
formulas is not the model that is best everywhere else. A router with one
partner for everything discards that.

Reversing the baseline shows the pairing is genuinely two-sided rather than a
ranking in disguise: where `ovisocr2` is wrong, `paddleocr_vl_1_6` recovers
19.8% of table pages and 14.6% of formula pages, but only 12.8% of text pages —
worse than `glm_ocr` and `opus5` at 16.3%.

### The floor, which is the honest part

Both readers are wrong **together** on 11.4% of text pages, 22.9% of table
pages, 35.7% of reading-order pages and 44.7% of formula pages. That is the
ceiling of any two-model arrangement, and it is why a second read is a recovery
step and never a guarantee.

### Two caveats that must travel with every number above

- **`tau = 0.05` is not calibrated** against a TAVONEL corpus. It is the
  study's discrete threshold for calling a page wrong, chosen because `tau = 0`
  calls a floating-point zero a failure.
- **The rescue table is an oracle ceiling.** It was measured by always picking
  the better page. A real router does not know which is better; it has to
  decide. The table bounds *how much there is to win*, not how much a shipped
  router wins.

---

## 4. Registry corrections

The registry was materially wrong about MinerU and silent about the
OmniDocBench leader.

| Row | Was | Now |
|---|---|---|
| `ovisocr2` | **absent entirely** — no route could ever name it | added, rev `1fc9221b…`, `ATH-MaaS/OvisOCR2` |
| `mineru_vlm` | absent | added, rev `bff20d4a…`, `opendatalab/MinerU2.5-Pro-2605-1.2B` |
| `mineru` | `engine: mineru_pipeline` against an unpinned umbrella `upstream_id` | pinned to `opendatalab/PDF-Extract-Kit-1.0` @ `ed6b654c…` |
| `paddleocr_vl_1_6` | revision unrecorded | rev `c5630aba…` (recorded in commit `9b656e6`) |

**The registry was carrying the variant that lost.** `mineru` (pipeline) scores
olmOCR-Bench 0.713 against `mineru_vlm`'s 0.806, and ParseBench chart 0.008
against 0.605. They are not variants of one row — `PDF-Extract-Kit-1.0` and
`MinerU2.5-Pro-2605-1.2B` are different repositories.

Every entry carries a `revision_source` block citing
`research/model_arena_20260903/model_registry.json`
(sha256 `83152ef92e2792a7ab3b2ef25fa9774115adfea2ebcd45363f7207764f8ee693`),
resolved read-only from the Hugging Face and GitHub APIs on 2026-09-05.

`ovisocr2` carries `model_size: null` and `weight_dtype: null` because the
Arena recorded none. Inventing them to fill the schema is forbidden.

---

## 5. Licences — captured, not asserted

The founder cleared the licences on 2026-09-23. **A clearance is not what the
gate reads.** `release_is_attested` in `validate_registry.py` requires
`license_snapshot_sha256`, and every real row carried `null` while the in-repo
mock carried a sha256 of ones standing behind nothing.

So the licence each pinned revision actually ships was fetched read-only at the
exact revision and stored byte for byte, with a manifest the validator
**re-hashes rather than trusts**. Proved by tampering with one snapshot and
watching the build fail, then restoring it.

| File | sha256 |
|---|---|
| `paddleocr_vl_1_6.model-card.md` | `d6c5b77a660577f6e18021defccd835bdc93a8c6538f5a479d597f3e94288abf` |
| `ovisocr2.model-card.md` | `03c876522bb7be5e8410eed758854dbb933204935afa898758d929c10725945d` |
| `mineru_vlm.model-card.md` | `8f829b69be518375b02023f795b3898adec98f5ac37208239884ad88e9a21cb7` |
| `mineru_vlm.runtime-LICENSE.md` | `2d9aeb5d15159329a20dd804f251c64860ba954fbd26ec02f802220e6d71cf5c` |
| `mineru.model-card.md` | `96da5ddde73c3f578b9eab235ac59cbb5f512755090779a14461863767b70f34` |

### Three things the snapshots say that "approved" does not

1. **`mineru_vlm`'s runtime is not plain Apache-2.0.** MinerU adds a
   commercial-licence threshold at **100M MAU or USD 20M monthly revenue**, an
   **online-service attribution obligation**, and **automatic termination on
   breach**. Below those numbers nothing further is needed; crossing either one
   requires a separate commercial licence *before* use continues. That is a
   business trigger, and nothing in this repository watches for it.
2. **`mineru`'s card declares no licence at all** — no front matter, no LICENSE
   file. Readable is not reusable, so `weight_license` stays open and that row
   is not a traffic candidate.
3. **No dataset licence is published for any of them.** They stay
   `review_required`. Code, weights, dataset and hosted-API terms are four
   separate licences and clearing one clears none of the others.

`ovisocr2`'s card also names `base_model: Qwen/Qwen3.5-0.8B`, whose own terms
the snapshot does not cover.

The mock's placeholder digest is now `null`: there is no upstream document to
capture, and a fake sha256 is exactly the receipt-free number this repository
forbids.

---

## 6. GPU serving — what was run and what it cost

The founder approved GPU serving. The original ADR item ran two things
together; only one of them costs money.

### Resolving a digest needs no GPU

Read from the registry manifests for nothing:

| Image | Digest |
|---|---|
| `paddleocr-genai-vllm-server:latest-nvidia-gpu` | `sha256:5713fd30ab76094b7b6a20d95fd8e26fa9dc452bcc90ccb16f1fb056bd2a0f4d` |
| `vllm/vllm-openai:v0.22.1` | `sha256:953d3a06d5e64ab582985cd7401289d3abf2a2c14ef2158e9a84313daeec77d7` |

The image config was also read from the registry before anything was launched:
15 layers, 5.8 GB compressed, built 2026-05-28, exposes 8080, command
`paddleocr genai_server --model_name PaddleOCR-VL-1.6-0.9B --host 0.0.0.0
--port 8080 --backend vllm`.

### Qualifying one does

A digest names bytes; it does not say the bytes serve. So the image was run.

| | |
|---|---|
| Platform | RunPod, `LOAD_BALANCER` endpoint `vu6ny92nbsz0t2` |
| GPU | NVIDIA GeForce RTX 4090, 1×, US-NC-1 |
| Rate | **$0.34 / GPU-hour** (from `get-capacity`, 2026-09-23) |
| Workers | min 0, max 1, idle timeout 60 s |
| Runtime | ~10 minutes, created 01:43 UTC, deleted 01:53 UTC |
| Cost | **≈ $0.06** at the quoted rate — billing had not posted when checked |

The host **independently reported the same digest on pull**
(`Digest: sha256:5713fd30…`), then loaded `PaddleOCR-VL-1.6-0.9B` under vLLM at
`max_model_len` 16384 and answered four page classes:

| page | seconds | chars out |
|---|---|---|
| multi-column text | 12.33 | 4,490 |
| table | 10.24 | 2,146 |
| mathematics | 4.75 | 2,477 |
| low-quality historical scan | 1.23 | 647 |

The endpoint was deleted immediately afterwards. The five pre-existing RunPod
endpoints were read but never touched.

### What the pin does not say

`paddleocr_vl_1_6.runtime.image_digest` is now pinned, with both caveats
recorded beside it and in the receipt:

- **The image was built 2026-05-28; the revision on that row was resolved
  2026-09-05.** Nothing compares the weights baked into the image against
  `upstream_revision`, so that field still describes what the Arena measured
  rather than what this image serves. Reconciling them belongs to the
  no-regression benchmark.
- **Four pages is a smoke test, not a score.** Nothing was compared to ground
  truth. The low-quality scan came back visibly degraded, which is consistent
  with the campaign's published 36.9% low-quality-scan weakness and is not
  evidence about it.

`ovisocr2` and `infinity_parser2_flash` keep `image_digest: null`. Neither
publishes an image, and the resolved vLLM digest names a runtime those weights
have never been run in. Filling the field from it would be inventing an
attestation.

---

## 7. Customer-facing copy sweep

Completed on the live site repository (`0ssol1620-byte/tavonel-saas-foundation`,
Next.js under `nextjs/`).

**85 instances across 32 routes → 0 across 60 routes.** Four pull requests,
each one's residue found only by curling the live sitemap, because CI was green
all four times. The guard was rewritten to detect what it had been missing:

`nextjs/lib/copy-trust-guard.test.ts` now walks `app`, `components`, `lib` and
`../shared` with a recursive `readdirSync` and normalises with
`replace(/\s+/g, " ")` before checking for `["this deployment", "이 배포판"]`.
It was verified to catch both single-line and line-wrapped reintroductions.

Two anchor changes: `shared/intakeCeiling.ts:53` `PROCESSING_CEILING_SENTENCE`
now opens "TAVONEL processes sources…", and `lib/landing-v2-copy.ts:671-672`
now reads "TAVONEL이 하는 일…". Around 55 further strings changed across
`lib/api-error-codes.ts`, `lib/docs-content.ts`, `lib/compiler-contract.ts`,
`lib/capabilities.ts`, `lib/public-status.ts`, `lib/changelog.ts`,
`lib/pipeline.ts`, `lib/cookbook-content.ts`, `lib/status-probe.ts`,
`lib/activation-cohorts.ts`, `app/api/openapi/route.ts`, `app/api/page.tsx`,
`app/privacy/page.tsx`, `app/evidence/page.tsx`, `app/contact/page.tsx`,
`app/login/page.tsx`, `app/auth/callback/page.tsx`,
`components/pricing-page-client.tsx`, `components/design-partners.tsx`,
`components/docs/api-try-it.tsx`, `components/compiler-contract-diagram.tsx`,
`components/world-recompile-timeline.tsx` and
`app/product/document-understanding/page.tsx`.

**One instance remains and cannot be fixed as a copy change** — see F-4 in
§11.

---

## 8. The 24 red API tests — not a defect

`pytest services/api/tests` fails 24 tests on the development machine, all in
the document-analysis path, all ending as
`AnalysisTask.last_error_code = PARSER_PROCESS_CRASH`.

**They are a local Python install artifact.** The worker launches the parser as
`sys.executable -I -m akc_worker_document.sandbox_runner`
(`workers/cpu-document/src/akc_worker_document/worker.py:1444`). `-I` is
deliberate sandbox hardening — isolated mode ignores `PYTHONPATH` *and the user
site-packages*. `fastapi` sits in the system site-packages but `starlette` sits
in `%APPDATA%\Roaming\Python\Python313\site-packages`, so the child process
dies at import before it parses anything. Inserting that one directory into
`sys.path` under `-I` makes the import succeed.

Proved pre-existing independently: the sorted `FAILED` list was captured at
`HEAD` in a clean worktree and diffed against the working tree's run — 24 on
both sides, **identical test names**.

Second trap in the same area: `py -3 -c "import akc_api"` outside pytest
resolves to the editable install at
`D:\CodexProjects\ai-knowledge-compiler-collection-plane-rehearsal`, a
different worktree. Under pytest the local tree wins because `pyproject.toml`
sets `[tool.pytest.ini_options] pythonpath`. A bare `python -c` import proves
nothing about which tree a test ran.

Affected files: `test_analysis_isolation.py`, `test_api_integration.py`,
`test_document_version_api.py`, `test_email_verification_api.py`,
`test_knowledge_batch_pdf_api.py`, `test_native_nonpdf_worker_e2e.py`.

---

## 9. Mistakes made in this session

Recorded because each one has a repeat mode.

1. **A commit swept in an untracked module's import.** Staging the whole of
   `akc_router/__init__.py` carried in `from .canary import (…)`, and
   `canary.py` is uncommitted working state belonging to other work. Anyone
   else checking the branch out got `ModuleNotFoundError` on `import
   akc_router` and every router test errored at collection. Fixed on both
   branches. *Stage hunks, not files, when a file holds someone else's
   uncommitted work.*
2. **A pin that was not a pin.** `mineru`'s `upstream_revision` was set to
   `fbb1257a…`, which is `github.com/opendatalab/MinerU` at tag
   `mineru-3.4.5-released` — a sha from a **different repository** than the
   Hugging Face weight repo it was written against. It read as valid because
   **the Hugging Face API silently serves `main` when asked for a revision it
   does not know**, instead of refusing. Corrected to `ed6b654c…`, and every
   other pin re-verified by checking that the host returns the sha requested.
3. **A fabricated digest, caught before commit.** A sha256 for ovis's largest
   weight file was invented from truncated earlier output; likewise a
   `weight_dtype: bf16` and a model size the Arena records as `None`. All
   corrected from the source artifact, with honest `null`s.
4. **Git Bash heredocs corrupt backslashes** silently — `'\\'` arrives as
   `'\'`. Python is written to the scratchpad with the Write tool and run by
   path instead.

---

## 10. Branches, PRs and artifact paths

### Core repository — `0ssol1620-byte/ai-knowledge-compiler`

| | |
|---|---|
| Review branch | `agent/router-second-reader-20260923` |
| Pull request | **[#76](https://github.com/0ssol1620-byte/ai-knowledge-compiler/pull/76)** |
| Research branch | `research/source-faithful-kc-v1` (pushed, `83d9673`) |
| Local worktree | `D:\pr1` |

The research branch is 164 commits ahead of `main`, so it is not a review unit.
The PR branch is cut from `main` with the relevant commits cherry-picked.

Commits on the PR branch, oldest first:

```
e658e82  research: add Model Arena code and thin OmniDoc leaderboards
066bea2  registry: record the PaddleOCR-VL revision the Arena already resolved
2167cd7  research: track the complementarity matrix, so the router can cite it
dc5e1e8  router: name the second reader, from the measurement that chose it
e61b0e6  registry: capture the licence each pinned revision actually ships
be20c01  registry: pin the PaddleOCR image by serving it, not by trusting a tag
93bd49a  docs: record that CI has not run since 2026-09-22
```

### Paths worth knowing

| What | Where |
|---|---|
| Decision record | `docs/adr/ADR-007-element-aware-second-reader.md` |
| Current founder list | `docs/audit/V5_FOUNDER_ACTIONS_2026-09-23.md` |
| This record | `docs/audit/SESSION_RECORD_2026-09-23_ROUTER_AND_COPY.md` |
| Arena budget/credentials (2026-08-11) | `docs/audit/V5_FOUNDER_ACTIONS.md` |
| Rescue module | `packages/router/src/akc_router/complementarity.py` |
| Its tests | `packages/router/tests/test_complementarity.py` |
| Licence snapshots | `infra/model-registry/license-snapshots/` |
| Serving receipt | `infra/model-registry/serving-receipts/paddleocr_vl_1_6.serving-qualification.json` |
| Complementarity artifacts | `research/model_arena_20260903/reports/complementarity_20260906/` |

### Artifact digests

| Artifact | sha256 |
|---|---|
| `complementarity_rescue_matrix.json` | `5528b7ec9afde1fd450bd82563360cf884d5c6d85998232171bc97dfdac3d174` |
| `complementarity_oracle_matrix.json` | `2efa03bc44824542c310a8fc10d0935b51317780240be4e4dc9717a0745bfaaf` |
| `model_registry.json` (Arena) | `83152ef92e2792a7ab3b2ef25fa9774115adfea2ebcd45363f7207764f8ee693` |

---

## 11. Remaining work — founder

Nothing here is blocked on code.

| # | Action | Where | Why it is yours |
|---|---|---|---|
| **F-0** | Settle GitHub Actions billing | account **Billing & plans** | §1 — blocks all CI and all deploys |
| **F-1** | Reset the `0ssol1620@gmail.com` workspace | `tavonel.com/workspace/settings/usage` → "Start this workspace from empty" → type `DELETE TEST DATA` | irreversible destructive action on live data |
| **F-2** | Insert the migration-ledger row | production SQL, below | production database write |
| **F-3** | Decide whether `/benchmarks` publishes a TAVONEL result | below | what a public claim says |
| **F-4** | Reissue the DPA as v2 | below | a versioned legal document |
| **F-5** | Insert the `model_registry` rows | production database | production database write |
| **F-6** | Authorize the no-regression benchmark of the pair | — | GPU/API spend, and it is the decision the routing rests on |

### F-1 — what is in there now

74 intake admissions, 71 compute reservations, 10 compile jobs, 1 job. All test
data from build sessions. The control is wired and deliberately refuses to fire
without the typed confirmation.

### F-2 — the migration ledger

Production is at `20260921064244`; the repository's head is `20260921110000`.
The schema change is already applied; the ledger row that records it is
missing, so the next migration run sees an inconsistent history.

```sql
insert into supabase_migrations.schema_migrations (version, name)
values ('20260921120000','source_deletion_inventory_document_id_type_fix')
on conflict do nothing;
```

The auto-mode classifier denies Supabase production writes, and that denial is
correct rather than an obstacle to route around.

### F-3 — `/benchmarks` publishes no TAVONEL number

The page quotes competitors and publishes none of our own results. The
strongest candidate already in the tree is **R-01** in
`nextjs/lib/evidence-record.ts`: olmOCR-Bench **80.6** with recovery against
**53.7** with only that lane disabled, over 1,403 documents and 8,413 checks,
with non-overlapping 95% confidence intervals.

Three rules bind whatever is decided: it is a **recovery** result and never an
accuracy claim, and its denominator travels with it; competitor rows stay
**quoted**, never restated as reproduced; the 36.9% low-quality-scan row and
the *not supported* blind-quality hypothesis stay published.

### F-4 — the DPA carries an internal phrase

`nextjs/public/policy/TAVONEL_DPA_v1_2026-09-11.md` says "this deployment" at
lines **82, 167 and 195**. Every other instance was removed from the site, but
a DPA is a versioned legal document: editing v1 in place changes a document
customers may already hold under that name, and four links pin its exact path.
It needs a **v2 reissue** with a new filename and the four links moved.

### F-5 / F-6 — what activation still needs

`_binding` refuses a `model_registry` row without an endpoint, a revision, a
runtime image digest, a model id and an adapter version;
`validate_registry_binding` additionally refuses one with no benchmark report.
Those refusals are the point — do not relax them to get a row in.

F-6 is the one that matters most and **has not moved at all**. Until a
same-condition benchmark of the pair exists, `traffic_percent` stays 0 and every
decision resolves to `cross_check_peer_unavailable` — the designed fail-closed
state, not a defect.

The ladder, unchanged from `CLAUDE.md`:

```
licence review → serve one model, pin its digest → registry row at canary 0
  → shadow the pair on a held-out corpus → compare against the single-reader
  baseline → canary → rollout
```

Steps one and two are done. The legacy single-reader path stays authoritative
until a benchmark says the pair is not worse.

### Already answered by the founder on 2026-09-23

| Item | Answer |
|---|---|
| Licence review | cleared — see §5 for the three caveats that survive it |
| GPU serving | approved — see §6 for what was run and what it cost |

---

## 12. Remaining work — engineering

Ordinary work; none of it needs a decision.

1. **Merge PR #76** once CI can run (F-0). Nothing else gates it.
2. **`ovisocr2` and `infinity_parser2_flash` have no qualified image.** Each
   needs a serving image built or chosen, run once, and its digest pinned the
   way PaddleOCR's was. Until then those two routes exist and cannot be served
   — visible and fail-closed, which is better than the state `ovisocr2` was in
   (absent entirely and silently unroutable).
3. **Reconcile the PaddleOCR image's baked weights with `upstream_revision`.**
   The image predates the pinned revision by three months and nothing compares
   them. This is properly part of F-6's benchmark.
4. **19 Dependabot advisories on the default branch** (4 critical, 6 high, 9
   moderate), reported on every push, never triaged.
5. **`canary.py` and `test_canary.py` are untracked working state** in
   `D:\CodexProjects\ai-knowledge-compiler`, as are modifications to
   `expected_verified_cost.py` and `test_verified_cost_router.py`. They belong
   to other work and were deliberately left alone. Whoever owns them should
   commit them; the `akc_router.__init__` exports come back with them.
6. **The dead-whitespace UI complaint** ("디테일 검수 제대로 안했어?") has not
   been worked. It needs specific surfaces named, or a pass at phone widths
   (360–430 px) against the screenshots the founder checks on.
7. **`ChampionMatrix` is empty machinery** with no production caller. Either
   wire it or delete it.

---

## 13. Open questions

**The "접근권한요청" buttons.** No such control exists anywhere in the site
repository — no component, route or string matches. Either it is on a surface
not yet shown, or the label is being translated in the browser. **An
untranslated screenshot with the URL visible resolves it in one step.**

---

## Appendix — rules that governed every decision above

From `CLAUDE.md`, quoted because several of them changed what was written:

- Never publish a numerical claim without a receipt; every rate carries its
  denominator; never call completion "accuracy"; competitor rows are quoted,
  never reproduced; a failed hypothesis is evidence and stays published.
- Never invent data to satisfy a schema.
- No silent fallback. A component that cannot do its job says so.
- Never route on a scalar blind quality score — published as *not supported*.
- Never infer capability from a model's name.
- An OSS licence is not patent freedom to operate; readable is not reusable;
  code, weights, dataset and hosted-API terms are four separate licences.
- "Built" is not "proven". No threshold here is calibrated.
- The session that implements does not approve its own result.
