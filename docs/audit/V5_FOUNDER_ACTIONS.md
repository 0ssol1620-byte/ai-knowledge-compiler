# Founder Actions and Costs

*Consolidated 2026-08-11 against `5087484`. Everything here needs a person —
an account, a payment method, a signature or a judgement. No agent can do these.*

Nothing in this file has been purchased, signed up for, or authorized. It is a
shopping list with reasoning, not a record of spending.

---

## 1. What blocks work right now

| # | Action | Blocks | Cost |
|---|---|---|---|
| **A-1** | Sign up for **OpenAI** API + payment method | Arena Phase 4–5, OpenAI family | usage-based, see §4 |
| **A-2** | Sign up for **Anthropic** API + payment method | Arena Phase 4–5, Claude family | usage-based, see §4 |
| **A-3** | Sign up for **Google AI Studio / Vertex** | Arena Phase 4–5, Gemini family | usage-based, see §4 |
| **A-4** | Provision **managed PostgreSQL + pgvector** | any deployed environment | ~$20–70 / month |
| **A-5** | Top up **RunPod** balance | Arena local families, all GPU work | ~$200–400 for the whole Arena, see §3 |

A-1 through A-3 are the same blocker wearing three hats: **there is no
credential for any of the three model providers.** The available set covers
GitHub, Vercel, DART, RunPod, HuggingFace, Cloudflare R2, a payment provider and
FRED.

**Why all three and not one.** The Arena exists to compare families on identical
documents. v5 PART 0.5 explicitly allows the conclusion that an API-only
architecture wins, and PART 34 says not to force the hybrid conclusion. Running
with one provider — or with none — produces a Document Performance Map that
cannot answer the question it was built to answer, and quietly biases the result
toward the architecture already built.

**A-4 is the gap nobody has noticed yet.** v5 names "Managed PostgreSQL/pgvector"
as base infrastructure. `infra/terraform/` provisions an AWS KMS key and an IAM
policy — no database. PostgreSQL exists only as `pgvector/pgvector:pg17` in
`docker-compose.dev.yml`, a loopback dev container. **There is no database to
deploy to.** This does not block Phases 1–3, which run against the local
container and CI, but it blocks any deployed environment.

---

## 2. What you already have

Checked against the credential set on hand.

| Service | Status | Action needed |
|---|---|---|
| GitHub | key present | none |
| Vercel | token present | check plan — Hobby may suffice until pilot traffic |
| Cloudflare R2 | account + user tokens present | check balance; ~10 GB free, then storage-priced, **zero egress fees** |
| RunPod | two keys present | **balance check / top-up** (A-5) |
| HuggingFace | key present | none — public model weights are free |
| DART (OpenDART) | key present | none — free, covers the 150-page DART corpus |
| SEC EDGAR | no key needed | none — public, covers the 150-page SEC corpus |
| FRED | key present | not used by v5 |
| Payment provider | **live** keys present | see §6 |

Corpus acquisition is therefore **almost entirely free**: 400 public benchmark
pages already sit in the repository, 150 DART pages need only the existing key,
150 SEC pages need nothing, and the 200-page Failure Zoo comes from the
campaign's own recovery-required documents.

---

## 3. GPU cost — measured, not estimated

This is the one number the repository actually knows, from
`docs/evidence/artifacts/folynta-measured-gpu-cost-2026-08-08.json`:

| | |
|---|---|
| GPU | NVIDIA RTX 4090 |
| Rate | **$0.74 / hour** |
| Healthy worker | 600 pages/pod-hour → **$1.23 / 1,000 pages** |
| Whole campaign | 41.03 pod-hours for 5,132 documents → **$5.92 / 1,000 pages** |

**The 4.8× gap between those two rows is the most useful planning fact here.**
$1.23 is what a worker that never stalls costs. $5.92 is what actually happened,
including every stall, retry and dead worker. Budget against $5.92.

Applying it to the Arena's page counts:

| Stage | Local page-runs | At $1.23/1k | At $5.92/1k |
|---|---:|---:|---:|
| 0 — smoke (50 pages × 3 local) | 150 | $0.18 | $0.89 |
| 1 — screening (200 × 3) | 600 | $0.74 | $3.55 |
| 2 — Arena v1 (1,000 × survivors + 3× repro subset) | ~3,000 | $3.69 | $17.76 |
| 3 — full public (5,132 × survivors) | ~7,700 | $9.47 | $45.58 |

**Pure compute for the entire Arena is $15–$70.** That is not the number to
budget, because it is not what you will spend.

What you will actually spend goes to pod time that is not extraction: model
loading (1–9B weights, minutes per cold start), container image builds, debugging
a provider adapter, a run that stalls at 80% and gets redone. The campaign's own
receipt shows this — 41 pod-hours for what should have taken ~9. Larger models
also need larger GPUs than a 4090, at correspondingly higher hourly rates.

**Budget: $200–400 for RunPod across the whole Arena program.** Real compute is
a rounding error inside it; the rest is the cost of iteration.

---

## 4. API cost — what I can and cannot tell you

**I cannot give you a dollar figure, and neither can the masterplan.** v5 PART 7.2
pins a model catalogue as of 2026-08-11 and then says explicitly that prices must
be re-queried at run time and that **the document's numbers are not production
price truth**. Quoting a rate here would be inventing a receipt.

Three things make estimation worse than usual:

1. **A PDF page is not a text token count.** v5 records that Claude PDF
   processing combines extracted text *and an image of each page*. Estimating
   from text tokens understates the real cost by an unknown factor.
2. **Batch pricing is roughly half** for Claude and Gemini per PART 7.2 — but
   v5 forbids treating batch and interactive as one execution path until
   equivalence is *measured*. A cheaper number from a path that produces
   different output is not a saving.
3. **Track I and Track N are separate runs.** Providers accepting native PDF get
   evaluated twice — once on the standardized page image, once on their own
   preferred input — so API page-runs are roughly double the page count.

What I *can* give you exactly is the multiplication, because the page counts are
fixed by the masterplan:

| Stage | API page-runs (3 families × 2 tracks) |
|---|---:|
| 0 — smoke | 50 × 3 × 2 = **300** |
| 1 — screening | 200 × 3 × 2 = **1,200** |
| 2 — Arena v1 | ~**3,400** (survivors + reproducibility) |
| 3 — full public | ~**10,000** (2–4 survivor paths) |
| Prompt calibration (separate 100-page set, several prompt iterations) | ~**2,400** |

Multiply your observed per-page rate by those counts. **Stage 0 exists precisely
to turn this into a receipt for about 300 API calls of exposure** — that is the
smallest useful commitment, and its output is the input to every budget question
after it.

As an order of magnitude for deciding how much to load onto a card: page-image
extraction on vision-capable models has historically sat in the fractions of a
cent to low cents per page. Against the counts above that puts the whole Arena
program somewhere in the **low hundreds of dollars**, with Stage 3 dominating.
Treat that as a bracket for sizing a prepaid balance, not as a plan — it is
inference from what these models used to cost, not a quote.

**Suggested initial load: $50 per provider.** Enough for Stage 0 and Stage 1 with
margin, small enough that a mistake is cheap.

### Stop rules already agreed (v5 PART 31.3)

- Candidate projected cost exceeds budget with no unique expected value → stop.
- Catastrophic issue in the first 50 or 200 pages → stop and repair.
- Provider batch retry cost cap.
- **Full-run approval only after the screening report.**

There is no number behind "budget" yet. Setting per-stage ceilings is **B-3**
in §7.

---

## 5. Recurring infrastructure

| Service | Need | Rough monthly |
|---|---|---|
| Managed PostgreSQL + pgvector (A-4) | required for any deployment | $20–70 |
| Cloudflare R2 | artifacts, benchmark outputs | <$5 early; ~10 GB free, **no egress charge** |
| Vercel | web hosting | $0 on Hobby; $20/seat on Pro if pilot needs it |
| Observability (OTLP endpoint) | `AKC_OTEL_EXPORTER_OTLP_ENDPOINT` is declared, no provider chosen | free tier likely sufficient early |
| Domain for TAVONEL | not registered as far as this repo knows | $10–40 / year |

**≈ $25–100 / month** before any pilot traffic. R2's lack of egress fees is why
it was chosen and is worth preserving in any storage decision.

---

## 6. One thing to fix regardless of any of the above

The credential file on `D:` holds **live payment keys** (`tsck_live_…`,
`tssk_live_…`), an admin account password, and Cloudflare secret access keys —
in plaintext, unencrypted.

Nothing has leaked through version control: the file is outside the repository
and `.env` is git-ignored and untracked. This is not an incident. It is the
setup that becomes one.

The v5 principle (APPENDIX B, carried from v4) is that `.env.example` holds names
only and production values live in a managed secret store. There is no secret
store yet — that is **S-6** in `V4_LICENSE_AND_SUPPLY_CHAIN.md`, currently
scheduled for enterprise hardening.

Two things worth doing sooner than that, both free:

- **Rotate the live payment keys** if that file has ever been shared, synced to
  cloud storage, or opened on another machine.
- **Do not add the three new model-provider keys to the same file.** They will be
  the highest-spend credentials in the project — an API key with a payment method
  behind it and no spend cap is the one that turns a mistake into a bill. Set a
  **hard spend limit** in each provider console at signup; every one of them
  offers it, and it is the single cheapest control available.

---

## 7. Decisions that cost money but aren't purchases

| ID | Decision | When | Cost |
|---|---|---|---|
| **B-2** | Authorize Stage 0 spend (50 pages × candidates) | before Phase 4 | ~$5–20 total |
| **B-3** | Set per-stage budget ceilings and the batch retry cap | before Phase 4 | — |
| **B-4** | Human adjudication budget for ambiguous / high-risk cases | Phase 5 | **possibly the largest line item** |
| **B-5** | Confirm the provider policy permits sending DART/SEC pages to three external providers | before Phase 4 | — |
| **IP-1** | Which of seven frozen technologies get a patent application, in what order | before any public description above VALUE_ONLY | attorney + prior-art search, typically thousands per application |
| **IP-2** | Research publication before or after filing | Phase 17 | publishing first forfeits foreign novelty |
| **IP-3** | TAVONEL trademark filing, and in which jurisdictions | affects launch copy risk | filing fees + attorney |
| **IP-5** | Whether provider terms permit publishing named model-vs-model comparisons | before any public Arena result | contractual review |
| **IP-6** | Is the Arena corpus publishable, or trade secret | before the campaign | — |

**B-4 deserves more attention than its position suggests.** v5 PART 31.4 says
plainly that human adjudication can cost more than GPU and API combined. The
mitigation is already designed — official benchmark evaluators, SEC XBRL
structured facts, OpenDART metadata, deterministic numeric anchors, synthetic
mutations — so that humans only see ambiguous and high-risk cases. But
`CLAUDE.md`'s self-approval rule is not negotiable: blind category tests and
forced comparison judgements are made by a person, and that person's time is a
real cost.

**IP-5 and IP-6 pull against each other** and both have to be settled *before*
results exist. A reproducible published benchmark needs its corpus disclosed;
the corpus manifest and case selection are classified as trade secret. Deciding
after the fact is not available — publication cannot be undone.

### Already decided

| ID | Decision | Date |
|---|---|---|
| **IP-7** | Customer-derived documents may **not** enter the Arena corpus. Public sources only, no consent path. | 2026-08-11 |
| — | PostgreSQL privilege separation to be implemented production-grade, not recorded as unprovable. | 2026-08-11 |

---

## 8. If you only do three things

1. **Set up the three provider accounts with a hard spend limit each and $50
   loaded.** Unblocks Phase 4–5 and caps the downside at $150.
2. **Check the RunPod balance.** Everything local stalls without it, and the
   Arena's local families are the half that is otherwise unblocked.
3. **Rotate the live payment keys** if that credential file has ever left the
   machine.

A-4 (managed PostgreSQL) is genuinely not urgent — Phases 1–3 run against the
local container and CI. It becomes urgent the first time anything needs to be
deployed, and it is better discovered now than on the day of a pilot.
