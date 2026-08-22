# Production GPU readiness (RunPod)

Snapshot date: **2026-08-23, 06:04–06:20 KST** · Source: `https://api.runpod.io/graphql`
(read-only queries only — `myself`, `gpuTypes`). No pod was created, modified,
resumed, or deleted, and no billable action was taken while producing this
document. This document records provider readiness only; it authorizes nothing.

## Method and credential boundary

- Two operator accounts were queried through two distinct RunPod API keys.
- Keys were parsed from the local credential file into process environment
  variables only (`RUNPOD_A` / `RUNPOD_B`), sent exclusively as
  `Authorization: Bearer …` headers, and are **not** reproduced anywhere in
  this repository or its output. Key length (50 chars each) is the only
  key-derived fact retained.
- Account identifiers are truncated to their first 8 characters below, per the
  same disclosure rule as the rest of the v6 contract set.
- The endpoint exposes catalog pricing through
  `gpuTypes { lowestPrice(input:{gpuCount:1}) { minimumBidPrice } }`. Only
  `minimumBidPrice` exists on `LowestPrice` in this dialect; an on-demand /
  uninterruptible price field is **not exposed**, so every figure below is a
  *lowest listed floor rate*, and real invoices can land above it. There is no
  stock-count field on `GpuType`; a type with no listed price is treated as
  "not currently offerable" rather than "out of stock".

## Account status (reconfirmation)

| Account | ID (8ch) | Balance (USD) | Current spend/hr | Pods | Previous check | Match |
|---|---|---|---|---|---|---|
| A | `user_3Hi` | **−$0.1137** | $0 | 4 | −$0.11, 4 pods | ✅ |
| B | `user_3HD` | **+$16.1309** | $0 | 0 | +$16.13, 0 pods* | ✅ balance |

Account A details — all four pods are terminal, none accrue cost:

| Pod (id 8ch) | Name | Status | Listed $/hr |
|---|---|---|---|
| `3yj5ghss` | tavonel-ovis-diag-20260815-111821 | EXITED | 0.74 |
| `gos4tphd` | tavonel-ovis-vllm-smoke-185603 | EXITED | 0.74 |
| `o2ygas8f` | tavonel-ovis-diag-20260815-114611 | EXITED | 0.74 |
| `wo7fvlnl` | tavonel-ovis-diag-20260815-110547 | EXITED | 0.53 |

Readiness implications:

1. **Account A cannot start any paid capacity.** The negative balance blocks
   new spend; a top-up is required before A hosts anything.
2. Account A carries four EXITED pods from the 2026-08-15 Ovis diag/vLLM smoke
   series. They are idle, but they should be explicitly drained/deleted through
   the normal fail-closed lifecycle (with orphan audit) rather than left to rot.
3. Account B is clean (zero pods, zero burn) and is the only account currently
   able to execute paid work. Its runway at floor rates is roughly
   **47 × RTX 4090-hours**, 49 × A6000-hours, or 46 × A40-hours.

## GPU candidate table (catalog snapshot, floor rates)

Priced candidates relevant to the v6 worker fleet (full catalog has 48 types;
unpriced ones omitted except where noted):

| GPU | VRAM | Secure / Community | Floor $/hr | Max GPUs/node |
|---|---|---|---|---|
| RTX 3090 | 24 GB | both | 0.22 | 8 |
| RTX A6000 | 48 GB | both | 0.33 | 10 |
| **RTX 4090** | 24 GB | both | **0.34** | 8 |
| A40 | 48 GB | secure only | 0.35 | 10 |
| RTX 5090 | 32 GB | both | 0.69 | 10 |
| RTX 6000 Ada | 48 GB | both | 0.74 | 8 |
| L40S | 48 GB | both | 0.79 | 8 |
| RTX PRO 6000 (Blackwell Server) | 96 GB | both | 1.69 | 9 |
| A100 PCIe | 80 GB | both | 1.19 | 8 |
| A100 SXM | 80 GB | both | 1.39 | 8 |
| H100 NVL | 94 GB | both | 2.59 | 10 |
| H100 SXM | 80 GB | both | 2.69 | 8 |
| H200 SXM | 141 GB | both | 3.59 | 8 |

Currently **without a listed price** (treat as unavailable for planning):
H100 PCIe, H200 NVL, L4, L40, RTX A5000, RTX 4080/4080 SUPER, RTX PRO 6000
MaxQ/WK, and others — 13 of 48 types returned no `minimumBidPrice`.

Planning notes:

- RTX 4090 remains the price/performance anchor for ≤24 GB workloads at
  $0.34/hr floor; the 48 GB band is covered by A6000 ($0.33, older arch),
  A40 ($0.35, secure-only), RTX 6000 Ada ($0.74) and L40S ($0.79).
- The `L4` class referenced throughout `pool-registry.yaml` has **no listed
  price in this snapshot**, so any pool plan that pins L4 as its primary class
  is not executable until pricing/stock returns or the class mapping changes.
- Floor-rate caveat applies to everything above (see Method).

## Worker → GPU mapping recommendation

Worker inventory is the seven-lane set recorded in
`docs/audit/V4_BASELINE_RECEIPT.md`: `cpu-document`, `cpu-export`,
`gpu-common`, `gpu-hpd`, `gpu-knowledge`, `gpu-parser`, `gpu-unlimited`.
Registry GPU-class names map to catalog entries as:
`RTX_4090_PRO → RTX 4090`, `A6000 → RTX A6000`, `A40 → A40`,
`A100_80GB → A100 PCIe/SXM`, `H100_80GB → H100 SXM`, `L4 → (currently unpriced)`.

| Worker | Workload evidence | Recommended class | Catalog pick (floor $/hr) | Rationale |
|---|---|---|---|---|
| `gpu-parser` | PaddleOCR adapter (`workers/gpu-parser/paddleocr_adapter.py`); parser pools pin `[L4, RTX_4090_PRO, A6000]` | RTX_4090_PRO / A6000 | RTX 4090 0.34 (alt: A6000 0.33) | 24 GB suffices for OCR-VL batch pages; A6000 trades arch age for 48 GB headroom |
| `gpu-knowledge` | Qwen adapter (`workers/gpu-knowledge/qwen_adapter.py`); `knowledge-qwen3-5` pins `[L4, RTX_4090_PRO, A6000]`; `knowledge-qwen3-6` (27B) pins `[A100_80GB, H100_80GB]` | RTX_4090_PRO default; A100_80GB for 27B | RTX 4090 0.34; A100 PCIe 1.19 | 9B-class compile on 24 GB; 27B-class compile needs 80 GB |
| `gpu-hpd` | Document-VLM lane (OvisOCR2-M1/vLLM image qualification context, `RUNTIME_QUALIFICATION.md`) | A40 / RTX_6000_ADA / L40S | A40 0.35 (alt: RTX 6000 Ada 0.74) | vLLM + vision model wants ≥48 GB; A40 is the cheapest 48 GB secure entry |
| `gpu-unlimited` | Long-running recovery/batch lane (MinerU-quality retry, alternate-recovery candidates) | A6000 / A100_80GB, interruptable pricing where allowed | A6000 0.33; A100 PCIe 1.19 | Long jobs favor cheap VRAM-heavy cards plus mandatory checkpoint/resume |
| `gpu-common` | Shared auxiliary GPU lane | RTX 3090 / RTX_4090_PRO | RTX 3090 0.22 (alt: RTX 4090 0.34) | Lowest-cost 24 GB for small embedding/utility inference |
| `cpu-document` | analysis_tasks consumer, preprocessing, sandbox runner (`workers/cpu-document/src/akc_worker_document/`) | CPU-only pod | n/a — CPU SKUs not exposed by this GraphQL catalog | No GPU required; price via REST v2 inventory before scheduling |
| `cpu-export` | AKMP/exporter byte-reproducible artifacts (`packages/exporters`) | CPU-only pod | n/a — same as above | Deterministic packaging; cheapest CPU shape wins |

Deployment posture follows `pool-registry.yaml` defaults: queue-based
serverless endpoints, `min_workers: 0` (scale-to-zero), auto scale-down,
provider retry count 0, callback auth required. Every GPU pool stays
`enabled: false` until its exact image digest (and license receipt, where
applicable) lands, so none of the mappings above imply immediate spend.

## Monthly budget estimate

Explicit usage patterns (all rates = floor rates from the table above;
serverless scale-to-zero assumed, so idle time costs nothing):

| Scenario | Pattern | Composition | Est. USD/month |
|---|---|---|---|
| S1 — Burst validation | Weekdays only; parser 4 h/day + knowledge 2 h/day + HPD 2 h/day, 20 days | 80 h × 4090 + 40 h × 4090 + 40 h × A40 | **≈ $54.80** |
| S2 — Business-hours pilot | 22 days; parser 8 h/day, knowledge 4 h/day, HPD 4 h/day (48 GB), unlimited 2 h/day | 176 h × 4090 + 88 h × 4090 + 88 h × RTX 6000 Ada + 44 h × A6000 | **≈ $169.40** |
| S3a — Steady single lane | 24/7 one RTX 4090 | 720 h × 0.34 | **≈ $244.80** |
| S3b — Steady three lanes | 24/7 parser+knowledge (4090) + HPD (A40) | 720 h × 1.02 | **≈ $734.40** |

Funding reality check against today's balances:

- Account B ($16.13) covers roughly **half of S1 for one week** — it does not
  fund a month of any scenario. Top-up sizing must precede any cohort dispatch.
- Account A (−$0.11) is blocked until topped up; even after top-up it should be
  treated as secondary until its four EXITED pods are cleaned up.

## Consistency with the v6 contract documents

- `README.md` (orchestration contract): this document performs read-only
  GraphQL reads only; every mutation-capable operation still requires the
  `--execute` gate and `RUNPOD_API_KEY` env injection described there. The
  fail-closed lifecycle (`absent → … → deleted`) and `SpendGuard`
  soft-alert/hard-stop semantics remain the governing rules for any spend that
  follows this readiness check. Note the dialect split: the client pins **REST
  v2** for endpoint management, while this snapshot uses the **GraphQL console
  API** for balances/catalog — both stay read-only here.
- `RUNTIME_QUALIFICATION.md`: GPU capacity readiness is **not** runtime
  qualification. Receipts continue to carry
  `runtime_qualification_required: true` and `paid_capacity_ready: false`
  until the baked-image qualification chain (identity, artifact, smoke gates,
  zero critical vulnerabilities) passes for the exact image/GPU/CUDA triple.
  Nothing in this document waives those gates.
- `pool-registry.yaml`: all pools remain `enabled: false` pending exact image
  digests; `min_workers: 0` defaults are what make the S-scenario math valid.

## Reproduction

```bash
# Keys come from the local credential file via environment only. Never log them.
export RUNPOD_KEY="$(python -c '...parse Runpod_A...')"
curl -sS https://api.runpod.io/graphql \
  -H "Authorization: Bearer ${RUNPOD_KEY}" \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: folynta-runpod-readiness-doc/1.0' \
  -d '{"query":"query { myself { clientBalance currentSpendPerHr pods { id name desiredStatus costPerHr } } }"}'
curl -sS https://api.runpod.io/graphql \
  -H "Authorization: Bearer ${RUNPOD_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"query":"query { gpuTypes { id displayName memoryInGb secureCloud communityCloud maxGpuCount lowestPrice(input:{gpuCount:1}){ minimumBidPrice } } }"}'
```

Operational notes learned while taking this snapshot: plain urllib without a
browser-like or named User-Agent is rejected with HTTP 403 by the edge, and
POSTs without an explicit `Content-Type: application/json` are rejected as
potential CSRF; introspection (`__schema`/`__type`) is disabled on this
endpoint, so field discovery must rely on validation-error hints or the
queries already proven in `tools/release/*folynta*.py`.
