# V5 R&D / Evaluation Cost Budget

*Masterplan v5.0 PHASE 0 deliverable ("cost-budget audit file"). Written
2026-08-11 against `9b5edd9`.*

v5 PART 31's question is the only one this file answers:

> **다음 $100가 어떤 uncertainty를 줄이는가?**

No spend is authorized by this document. It records what the Arena would cost to
run, what is blocked, and what a founder has to decide before Phase 4 starts.

---

## The blocker, stated first

**C-7 — there is no OpenAI, Anthropic or Google credential available to this
repository.**

v5 PART 7.1 names three General Multimodal API families as Arena candidates, and
PART 34 requires measuring *actual* API usage rather than estimating it. The
credential set on hand covers GitHub, Vercel, DART, RunPod, HuggingFace,
Cloudflare R2, a payment provider and FRED. It contains no key for any of the
three model providers.

Consequence, split by family:

| Candidate family | Credential | Phase 4–5 status |
|---|---|---|
| MinerU 3.4.4 (historical champion) | RunPod + HuggingFace ✓ | **unblocked** |
| PaddleOCR-VL-1.6 | RunPod + HuggingFace ✓ | **unblocked** |
| DeepSeek-OCR-2 | RunPod + HuggingFace ✓ | **unblocked** |
| OpenAI image-capable models | **absent** | blocked |
| Anthropic Claude vision/PDF models | **absent** | blocked |
| Google Gemini document/vision models | **absent** | blocked |
| Mistral OCR (optional specialist) | **absent** | blocked, and optional |

This is a missing secret, which PART 34 lists among the few things to ask the
founder for rather than work around. **It is not a reason to delay Phases 1–3**,
which contain no model calls.

It *is* a reason not to start Phase 4 with local families alone. The Arena's
whole purpose is the cross-family comparison — PART 0.5 explicitly allows the
conclusion that an API-only architecture wins. Running local-only would produce a
Document Performance Map that cannot answer the question it exists to answer,
and would quietly bias the result toward the architecture already built. That is
the failure mode PART 34 names: *"Do not force the conclusion that hybrid/local
is better."*

---

## Corpus acquisition — what a key buys

| Source | Credential | Status |
|---|---|---|
| DART (150 pages) | DART key ✓ | acquirable — `benchmark/acquire_dart.py` exists |
| SEC (150 pages) | none needed (EDGAR is public) | acquisition code absent |
| Public benchmarks (400 pages) | none needed | corpora present from the campaign |
| Failure Zoo (200 pages) | none needed | raw material present, unclassified |
| Clean Control (100 pages) | none needed | absent |

Corpus construction is therefore **almost entirely unblocked**. It can run in
parallel with the credential decision, and it is the cheapest work in the Arena.

---

## Stage gates (PART 31.2)

Spend rises by roughly 5× per stage. Each gate is a stop, not a formality.

| Stage | Scope | Buys |
|---|---|---|
| **0** | 50 pages × candidates | exact input path works; real usage/token/GPU cost; schema feasibility |
| **1** | 200 pages × all candidates | drops dominated models; finds unique specialist niches |
| **2** | 1,000-page Arena | Pareto survivors + required controls + TAVONEL adaptive |
| **3** | 5,132 full public | 2–4 survivor paths only |
| **4** | DART/SEC expansion | slices with real enterprise value |

### Stop rules (PART 31.3)

- Projected candidate cost exceeds budget with no unique expected value → stop.
- Catastrophic issue in the first 50 or 200 pages → stop and repair.
- Provider batch retry cost cap.
- **Full-run approval only after the screening report.**

### The cost lever v5 names

Batch is priced at ~50% of interactive for the providers PART 7.2 lists. v5 does
not let that be assumed: **batch and interactive equivalence must be measured
before they are treated as one execution path** (PART 34). A cheaper number from
a path that produces different output is not a saving.

### The estimate this file deliberately does not give

No dollar figure appears above. Three reasons, in order of weight:

1. **Pricing is not knowable from the document.** PART 7.2's own instruction is
   to re-query prices at run time via a registry snapshot and never use the
   document's numbers as production price truth.
2. **PDF cost is not text-token cost.** PART 7.2 records that Claude PDF
   processing combines extracted text *and a per-page image*. Estimating from
   text tokens understates it by an unknown factor.
3. **Local GPU cost must be measured, not modelled.** The one figure this
   repository does have — `$1.23 / 1,000 pages` — is measured raw GPU cost for
   MinerU, holds only for that path, and per `CLAUDE.md` never sits beside a
   retail price.

Stage 0 exists precisely to replace estimates with receipts. **The first
authorized spend should be Stage 0, and its output is the input to every budget
question after it.**

---

## Ground-truth cost (PART 31.4)

> GPU/API보다 human adjudication이 더 비쌀 수 있다.

Automatic truth first, humans only for ambiguous and high-risk cases:

- official benchmark evaluators (present for all three public corpora)
- SEC XBRL / structured facts
- OpenDART metadata
- deterministic numeric and source anchors
- synthetic controlled mutations

`CLAUDE.md`'s self-approval rule still binds: blind category tests and forced
comparison judgements are made by a person. Budget for that person's time.

---

## Founder decisions

| ID | Decision | Blocks | Note |
|---|---|---|---|
| **B-1** | Provision OpenAI / Anthropic / Google API credentials for evaluation | Phase 4–5 API families | Missing secret. Which providers, and under what data-processing terms — PART 19 requires a model provider policy, and evaluation traffic carries DART/SEC corpus pages |
| **B-2** | Authorize Stage 0 spend (50 pages × candidates) | Phase 4 start | Smallest useful commitment. Produces the receipts every later budget question needs |
| **B-3** | Set the per-stage budget ceiling and the batch retry cost cap | Phase 4–5 | PART 31.3 requires a number to stop against; there is none yet |
| **B-4** | Approve human adjudication budget | Phase 5 | Possibly the largest line item |
| **B-5** | Confirm DART/SEC corpus pages may be sent to third-party model providers | Phase 4–5 | Both are public filings, so this is a policy question rather than a consent question — but PART 19's provider policy has to say so explicitly before traffic flows |

B-5 is easy to skip and shouldn't be. Public filings are public, but "we send
them to three external providers under evaluation" is still a statement the
provider policy has to contain before it is true.
