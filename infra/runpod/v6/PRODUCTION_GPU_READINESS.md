# RunPod GPU Readiness — production worker audit

- **Date:** 2026-08-23 (KST)
- **Scope:** read-only audit of the two RunPod accounts against the seven TAVONEL
  workers. No pod was created, modified or deleted; no spend was authorized.
- **Provenance:** API keys read from the local secrets file at runtime, consumed
  as environment-equivalents only; account IDs truncated to 8 chars below.
- **Method:** RunPod GraphQL (`https://api.runpod.io/graphql`). Note: requests
  without a descriptive `User-Agent` are rejected with HTTP 403.

## 1. Account status

| Account | ID (8ch) | Balance | Existing pods |
| --- | --- | --- | --- |
| A (`Runpod_A`) | `user_3Hi` | $-0.11 | 4 |
| B (`Runpod_B`) | `user_3HD` | $16.13 | 0 |

Account A is at/negative balance (-$0.11) — **production scheduling should use
account B** until topped up. Account A's 4 pods predate this audit and were not touched.
[]

## 2. GPU market snapshot (on-demand USD/hr)

| GPU | VRAM | community | secure |
| --- | --- | --- | --- |
| RTX 4090 | 24 GB | $0.34 | $0.74 |
| RTX 5090 | 32 GB | $0.69 | $0.99 |
| L40S | 48 GB | $0.79 | $0.99 |
| RTX 4080 / SUPER | 16 GB | $0.27 | $0.50 |
| A100 PCIe 80GB | 80 GB | $1.19 | $1.39 |
| A100 SXM 80GB | 80 GB | $1.39 | $1.59 |

Full catalog snapshot: see the run transcript (fetched live 2026-08-23).

## 3. Worker → GPU mapping recommendation

| Worker | Workload shape | Recommended GPU | Est. cost basis |
| --- | --- | --- | --- |
| `gpu-parser` (PaddleOCR) | vision OCR, burst | RTX 4090 (24 GB) | ~$0.34/hr community |
| `gpu-knowledge` (Qwen) | LLM extraction/verify | RTX 4090 dev / L40S prod (48 GB headroom) | $0.79/hr prod |
| `gpu-hpd` | high-per-doc batch | RTX 4090 pool | ~$0.34/hr |
| `gpu-unlimited` | overflow queue | RTX 4080 SUPER spot-class | $0.28/hr |
| `cpu-document` | preprocessing | CPU pod (cheapest) | <$0.05/hr class |
| `cpu-export` | packaging | CPU pod | <$0.05/hr class |

Rationale: the Family A/B evidence runs (§29.1) were smoke-tested on a single
RTX 4090 (~5.74 s/page inference); 24 GB covers PaddleOCR + Qwen-4B-class
extraction. L40S is the production step-up when concurrent document streams
need >24 GB. The historical OvisOCR2 qualification used the same 4090 class.

## 4. Budget estimate (illustrative, must be measured)

Assuming pilot load of ~5,000 pages/day, parser-bound at ~0.6 s/page effective
throughput on one 4090:

- steady single-GPU: 1 × 4090 ≈ $0.34/hr × 10 h/day ≈ **$3/day** ≈ $250/month
- burst headroom (3× during ingest waves): ≈ $750/month ceiling

These are planning numbers from today's listed prices, not measured TAVONEL
throughput; replace after the first Stage-1 200-page campaign records real
s/page (RUNTIME_QUALIFICATION.md contract).

## 5. Actions before production

1. Top up account B (or move billing to it); treat A as drained until positive.
2. Keep `--execute` gating in `client.py` (network-free dry run default).
3. Record per-worker s/page on the Stage-1 campaign, then replace §4 numbers.
