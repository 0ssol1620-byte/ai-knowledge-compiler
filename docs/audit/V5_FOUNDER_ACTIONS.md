# Founder Actions and Costs

*Consolidated 2026-08-11 against `b62db24`. Everything here needs a person —
an account, a payment method, a signature or a judgement. No agent can do these.*

Nothing here has been purchased, signed up for, or authorized.

**Reading order.** §1 is what blocks work now. §2 is the credential rotation task,
which is unrelated to the Arena and should not wait for it. §3–§5 are money. §6 is
decisions that cost money without being purchases.

---

## 1. Hard blockers

Only two things actually block the current phase. Everything else in this file
can wait for its phase.

| # | Action | Blocks | Commitment now |
|---|---|---|---|
| **A-1** | Create **OpenAI** API account, set org + project hard limit, load Stage-0 minimum | Arena Phase 4 | ~$10 |
| **A-2** | Create **Anthropic** API account, set spend limit below tier cap, load Stage-0 minimum | Arena Phase 4 | ~$10 |
| **A-3** | Create **Google AI Studio** project, set project spend cap, enable billing | Arena Phase 4 | ~$10 |
| **A-4** | **Check RunPod balance** (keys already exist) | Arena local families | check only |

**Not blocking now, but discovered and worth knowing:** there is no managed
PostgreSQL anywhere. v5 names it as base infrastructure; `infra/terraform/`
provisions an AWS KMS key and an IAM policy; the only Postgres in the tree is the
`pgvector/pgvector:pg17` loopback container in `docker-compose.dev.yml`. Phases
1–3 run against that container and CI. **Anything deployed does not.** Cost when
it is needed: ~$20–70/month.

### Why all three providers, and not one

The Arena compares families on identical documents. v5 PART 0.5 explicitly allows
the conclusion that an API-only architecture wins, and PART 34 says not to force
the hybrid conclusion. One provider — or none — produces a Document Performance
Map that cannot answer its own question, and quietly biases the result toward the
architecture already built.

---

## 2. Credential rotation and migration

**Do this regardless of anything else in this file. It is free.**

A plaintext credential file on `D:` holds live payment provider keys, an
administrator account password, and Cloudflare account/user secret access keys.
Values are not reproduced here, in any log, or in any prompt — and must not be.

**Rotation status: rotate.** The user's own criterion is exposure to cloud sync,
backup, remote support, or agent context. **That file was read into an agent
context during this session** in order to inventory which providers had
credentials. That satisfies the criterion on its own, independently of whether
the file has ever synced or been opened elsewhere.

| # | Action | Scope |
|---|---|---|
| **R-1** | Rotate live payment provider client secret | payment provider console |
| **R-2** | Rotate Cloudflare R2 account + user API tokens and access keys | Cloudflare dashboard |
| **R-3** | Rotate the administrator account password | application |
| **R-4** | Rotate RunPod, HuggingFace, Vercel, GitHub, DART tokens | respective consoles |
| **R-5** | Move all of the above out of the plaintext file into a secret manager or environment injection | — |

**R-5 covers the new keys too.** The three Model Arena API keys about to be
created will be the highest-spend credentials in the project. They go into a
secret manager or environment injection from the start — **not** into the
plaintext file, not into `.env` committed anywhere, not into a chat message.

`.env.example` holds names only and `.env` is git-ignored and untracked, so
nothing has entered version control. This is not an incident; it is the
arrangement that becomes one. Structural fix is **S-6** in
`V4_LICENSE_AND_SUPPLY_CHAIN.md`.

---

## 3. Provider billing and hard caps — verified against official documentation

Checked 2026-08-11. **All three offer a spend cap that pauses or blocks requests.
None of them is precise, and one has a documented gap in exactly the lane the
Arena needs.**

### OpenAI

Organization-level and project-level spend limits, with an **"Enforce a hard
limit"** toggle. When tracked spend reaches an enforced hard limit, affected
requests return `429` with `organization_spend_limit_exceeded` or
`project_spend_limit_exceeded`. Both levels can apply to one request.

> "Enforcement is not instantaneous, so recorded spend can slightly exceed the
> configured amount."

**Verdict: real hard cap, imprecise edge.**

### Anthropic

Two mechanisms. Tier spend caps are service-configured — Start **$500/month**,
Build **$1,000**, Scale **$200,000**; Custom tier has none. On top of that you can
set your own limit below the tier cap, on Settings → Billing → Spend limits, and
per-workspace spend and rate limits are available.

> "Once you reach your tier's spend cap, API usage pauses until the next month
> unless you request a higher limit."

**Verdict: real hard cap.** The Start tier's $500 ceiling is itself a backstop —
a new account cannot run away past it even if the self-set limit is misconfigured.

### Google (Gemini API)

Billing-account tier caps (**$250** Tier 1, **$2,000** Tier 2, $20,000+ Tier 3)
plus project-level caps set in AI Studio. Reaching the account tier limit pauses
service for all linked projects until the 1st of the next month.

Three documented gaps:

> "Billing data processing times can be delayed in AI Studio, up to around 10
> minutes. You may experience overages beyond your project cap if billing data
> hasn't processed before more charges are accrued."

> **"Long-running tasks like batch mode completions and agent sessions may incur
> overages beyond your project spend cap."**

> "Spend caps are not available for Invoiced (or Offline) accounts."

**Verdict: real hard cap with a batch-mode hole.**

### The finding that matters

**v5 Track B is batch mode.** PART 9.4 makes batch/bulk economics a required
evaluation track, and PART 7.2 records batch pricing at ~50% as the reason. So the
Arena's cheapest lane is precisely the lane Google documents as able to exceed the
cap, and the lane where OpenAI's propagation delay has the longest time to
accumulate — a batch job submits thousands of requests before any spend is
tracked.

**Therefore the application-side control is required, and not as a fallback.** The
providers' caps are real; they simply do not bind on the execution mode the Arena
depends on most.

| Control | Where | Why |
|---|---|---|
| Provider hard cap | all three consoles | outer backstop, catches runaway |
| **Budget circuit breaker** | TAVONEL, before any provider call | in-process ledger; refuses to dispatch when projected spend crosses the stage ceiling |
| **Per-run authorization** | TAVONEL, per Arena run | a run declares its projected cost and stops unless explicitly authorized for that stage |

This lands as implementation work in **Phase 4** (Arena harness), and the
`arena_runs.actual_cost_usd` + `price_snapshot_id` fields already specified for
Phase 1 are what the breaker meters against. Recorded here so the requirement
arrives with the phase rather than after the first surprising bill.

**Batch jobs need pre-submission estimation, not post-hoc metering.** A batch of
1,000 requests commits the spend at submission time; a breaker that checks after
each response has already lost. The per-run authorization has to price the batch
before it is submitted.

---

## 4. Stage-gated budget

No flat top-up. Each stage is authorized on the previous stage's report, per v5
PART 31.2.

| Stage | Scope | API calls | Load before it | Gate to the next |
|---|---|---:|---|---|
| **0** | capability + cost smoke | 300 | **~$10 per provider** | measured per-page cost exists for every candidate |
| **1** | screening, drop dominated models | 1,200 | set from Stage 0 receipts | screening report names survivors |
| **2** | Arena v1, 1,000 pages | ~3,400 | set from Stage 1 receipts | DPM + Oracle matrix exist |
| **3** | full public 5,132 | ~10,000 | set from Stage 2 receipts | — |
| calibration | prompt tuning, separate 100-page set | ~2,400 | folded into Stage 0–1 | prompts frozen |

API call counts are exact — 3 families × 2 tracks (Track I standardized image,
Track N provider-native) × the masterplan's fixed page counts.

**$10 per provider is deliberately small.** It covers Stage 0's 100 calls per
provider with wide margin, and it is the amount at which a misconfigured loop is
an annoyance rather than an event. Stage 0's entire purpose is to replace
estimates with receipts; it does not need headroom.

**Set the provider hard cap at the stage ceiling, not at the balance.** A prepaid
balance is not a cap — it is a floor on how much you can lose before noticing.

### Stop rules already agreed (v5 PART 31.3)

- Candidate projected cost exceeds budget with no unique expected value → stop.
- Catastrophic issue in the first 50 or 200 pages → stop and repair.
- Provider batch retry cost cap.
- **Full-run approval only after the screening report.**

**B-3** below is the outstanding piece: there is no number behind "budget" yet.

### Why no dollar total appears

v5 PART 7.2 pins a model catalogue as of 2026-08-11 and then instructs that
prices be re-queried at run time and that **the document's numbers are not
production price truth**. Quoting a per-token rate here would be inventing a
receipt. Two further reasons it would be wrong anyway: a PDF page is not a text
token count (Claude PDF processing combines extracted text *and* a per-page
image), and Track I / Track N are separate runs, so API calls are roughly double
the page count.

What is given instead is the multiplication. The counts above are fixed; multiply
by whatever rate Stage 0 measures.

---

## 5. GPU cost — measured, not estimated

From `docs/evidence/artifacts/folynta-measured-gpu-cost-2026-08-08.json`:

| | |
|---|---|
| GPU | NVIDIA RTX 4090 |
| Rate | **$0.74 / hour** |
| Healthy worker | 600 pages/pod-hour → **$1.23 / 1,000 pages** |
| Whole campaign | 41.03 pod-hours / 5,132 documents → **$5.92 / 1,000 pages** |

**The 4.8× gap between those rows is the most useful planning fact here.** $1.23
is a worker that never stalled. $5.92 is what happened, including every stall,
retry and dead worker. Plan against $5.92.

Pure compute across all four Arena stages is **$15–70**. That is not what will be
spent: the real consumption is pod time that is not extraction — model loading
(1–9B weights, minutes per cold start), image builds, adapter debugging, runs
redone after stalling. The campaign's own receipt shows the ratio: 41 pod-hours
for what should have taken ~9. Larger models also need larger GPUs than a 4090.

**A-4 is a balance check, not a top-up decision.** Once the balance is known, size
it against the stage you are authorizing — not against the whole program.

---

## 6. Recurring infrastructure

| Service | Need | Rough monthly |
|---|---|---|
| Managed PostgreSQL + pgvector | required for any deployment | $20–70 |
| Cloudflare R2 | artifacts, benchmark outputs | <$5 early; ~10 GB free, **no egress charge** |
| Vercel | web hosting | $0 on Hobby; $20/seat on Pro if a pilot needs it |
| Observability (OTLP endpoint) | `AKC_OTEL_EXPORTER_OTLP_ENDPOINT` declared, no provider chosen | free tier likely sufficient |
| Domain for TAVONEL | not registered as far as this repo knows | $10–40 / year |

**≈ $25–100 / month** before pilot traffic.

---

## 7. What you already have

| Service | Status | Action |
|---|---|---|
| GitHub, Vercel, HuggingFace, FRED | keys present | rotate (R-4) |
| Cloudflare R2 | account + user tokens present | rotate (R-2), check balance |
| RunPod | two keys present | **check balance (A-4)**, rotate (R-4) |
| DART (OpenDART) | key present | rotate (R-4); free, covers the 150-page DART corpus |
| SEC EDGAR | no key needed | — |
| Payment provider | **live** keys present | **rotate (R-1)** |

Corpus acquisition is nearly free: 400 public benchmark pages are already in the
repository, DART 150 needs only the existing key, SEC 150 needs nothing, and the
200-page Failure Zoo comes from the campaign's own recovery-required documents —
all public-source, per the IP-7 decision below.

---

## 8. Decisions that cost money but aren't purchases

| ID | Decision | When | Cost |
|---|---|---|---|
| **B-3** | Per-stage budget ceilings and the batch retry cost cap | before Phase 4 | — |
| **B-4** | Human adjudication budget for ambiguous / high-risk cases | Phase 5 | **possibly the largest line item** |
| **B-5** | Confirm the provider policy permits sending DART/SEC pages to three external providers | before Phase 4 | — |
| **IP-1** | Which of seven frozen technologies get a patent application, in what order | before any public description above VALUE_ONLY | attorney + prior-art search |
| **IP-2** | Research publication before or after filing | Phase 17 | publishing first forfeits foreign novelty |
| **IP-3** | TAVONEL trademark filing, and in which jurisdictions | affects launch copy risk | filing fees + attorney |
| **IP-5** | Whether provider terms permit publishing named model-vs-model comparisons | before any public Arena result | contractual review |
| **IP-6** | Is the Arena corpus publishable, or trade secret | before the campaign | — |

**B-4 deserves more weight than its position suggests.** v5 PART 31.4 says plainly
that human adjudication can cost more than GPU and API combined. The mitigation is
designed — official evaluators, SEC XBRL structured facts, OpenDART metadata,
deterministic numeric anchors, synthetic mutations — so humans see only ambiguous
and high-risk cases. But `CLAUDE.md`'s self-approval rule is not negotiable: blind
category tests and forced comparison judgements are made by a person.

**IP-5 and IP-6 pull against each other** and both must be settled *before*
results exist. A reproducible published benchmark needs its corpus disclosed; the
corpus manifest and case selection are classified as trade secret. Deciding after
the fact is not available.

### Already decided

| ID | Decision | Date |
|---|---|---|
| **IP-7** | Customer-derived documents may **not** enter the Arena corpus. Public sources only, no consent path. | 2026-08-11 |
| **B-2** | No flat provider top-up. Stage-gated: 50-case smoke → 200-case screening → 1,000-page Arena. | 2026-08-11 |
| — | PostgreSQL privilege separation implemented production-grade, in two stages, not recorded as unprovable. | 2026-08-11 |

---

## 9. If you only do three things

1. **Rotate the credentials in §2.** Free, unrelated to any phase, and the one
   item here with no good reason to wait.
2. **Create the three provider accounts, set a hard limit on each, load ~$10.**
   Unblocks Phase 4 with $30 of exposure.
3. **Check the RunPod balance.**

---

## Sources

Provider billing facts verified 2026-08-11 against:

- [OpenAI — Spend limits](https://developers.openai.com/api/docs/guides/spend-limits)
- [Anthropic — Rate limits (incl. spend limits)](https://platform.claude.com/docs/en/api/rate-limits)
- [Google — Gemini API billing](https://ai.google.dev/gemini-api/docs/billing)
- [Google Cloud — Manage spend cap budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)

Re-verify at signup. Pricing, tier ceilings and cap behaviour all change, and v5
requires a registry snapshot at run time rather than a document's numbers.
