# Structara v6 benchmark control plane

This package implements the local, provider-neutral benchmark contracts from
masterplan sections 0–23 and 38–47. It does not read a credential, mount ground
truth into inference, create a paid endpoint, or claim that an external model
was executed.

## Implemented contracts

- A fail-closed registry covering every mandatory Tier A/B/C parser and every
  required Knowledge Compiler candidate. Unknown revisions, licenses, or image
  identities remain explicit and make promotion impossible.
  Read-only upstream research pins the model revisions it could prove; an HF or
  Git commit still does not substitute for a downloaded file manifest, runtime
  recipe, signed image digest, or actual benchmark receipt.
- A v6 dataset lock that mirrors the three immutable public-core identities and
  keeps robustness/private manifests explicitly pending rather than inventing
  unavailable hashes or scores.
- An immutable environment identity binding source commit/tree, model artifact,
  image digest, GPU/CUDA/driver/framework, prompt, decoding, dataset, evaluator,
  and network policy. Mutable aliases and an inference GT mount are rejected.
- Stable document-preserving shard assignment. Input ordering and Python hash
  randomization cannot change ownership; page loss, duplication, document
  splitting, order changes, or manifest tampering fail validation.
- Adaptive same-environment public-core repeats: every candidate receives one
  full pass and three stratified determinism audits. Finalists, runtime failures,
  prediction-hash drift, or score drift expand to exactly three isolated full
  successful runs with distinct prediction/log/official/critical roots. A failed
  attempt is retained as evidence but never counts as a completed repeat.
- Canonical Ed25519 evidence envelopes bind candidate, distinct incumbent,
  requested target, release commit/tree, registry and Champion Matrix digests,
  the exact G0–G8/MP0–MP6 snapshot, and all signed run records. Public Core
  promotion requires the exact 18-receipt matrix: candidate and incumbent ×
  three suites × repeats 1/2/3, with unique roots/logs and one immutable cohort
  and environment per suite. There is no embedded key; unsigned, tampered,
  cross-candidate, cross-release, gate-replayed, local-only, or incomplete
  evidence cannot promote a candidate.
- G0–G8 plus MP0–MP6 arbitration and computed G9. Critical failures reject;
  missing evidence remains shadow-only. Majority vote is never authority.
- A page-class Champion Matrix that keeps every unknown primary unresolved until
  a production promotion decision references signed actual evidence.
- RunPod pool, idempotency, spend/runaway, zero-duplicate-charge, drain,
  endpoint deletion, and orphan-audit contracts under `infra/runpod/v6`.
- A live-v2 strict RunPod adapter, adaptive initial planner, and exact-three
  write-ahead coordinator reserved for finalist/drift/runtime-failure expansion, and
  append-only hash-chain JSONL ledger. Re-running the same cohort resumes
  acknowledged jobs; an unacknowledged provider write hard-stops instead of
  issuing a duplicate. Provider billing and accepted-only user billing remain
  separate ledgers.

The locked public-core suites remain the existing OmniDocBench, ParseBench, and
olmOCR-Bench registry, with source-only inference, prediction freeze, evaluator-
only GT, adaptive repeat screening, and exactly three full repeats for promotion
finalists or any unstable run.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q benchmark/tests/v6
.\.venv\Scripts\python.exe -m ruff check benchmark/v6 benchmark/tests/v6 infra/runpod/v6
.\.venv\Scripts\python.exe -m benchmark.v6.preflight
```

Focused provider tests use `httpx.MockTransport`; they prove zero real provider
retry, management inventory/create/update/drain/delete, queue run/status/cancel,
strict live response parsing, adaptive-plan isolation, expansion-only
exactly-three resume without duplicate dispatch,
accepted-only billing, tamper/truncation detection, delete-confirmed orphan
audit, and terminal cleanup only after provider GET 404. They never use a real
credential or paid endpoint.

The preflight deliberately reports `local_contract_gate=pass` and
`production_gate=reject`. Production requires actual immutable model/runtime
receipts, paid external runs, failure drills, actual cost/speedup, terminal
endpoint cleanup receipts, and an external release-key signature.

## Recovery and detector campaign

The recovery evidence command binds exact failure labels, detector predictions,
paired selective/full-replay outcomes, and adaptive repeat observations into one
fail-closed receipt:

```powershell
.\.venv\Scripts\python.exe -m tools.release.run_folynta_recovery_campaign `
  --input benchmark/v6/cohorts/recovery-fault-injection-golden.json `
  --output benchmark/reports/generated/folynta-recovery-fault-injection-golden-2026-08-03.json
```

The included golden cohort covers all 18 masterplan failure codes and one
healthy control. It is deliberately marked `synthetic_contract_only`; it proves
the detector/recovery/repeat evidence wiring, not public-core model accuracy.
Real public-core claims require the same receipt builder to consume frozen
model outputs and evaluator-only labels from the exact locked dataset revisions.

## Actual control-plane smoke boundary

On 2026-08-01, the live adapter and exact-three coordinator were exercised
against a temporary RunPod hello-world endpoint. All three control jobs reached
`COMPLETED`; endpoint deletion ended in provider GET 404 and the tagged orphan
audit found zero endpoints. The cleanup receipt is
`sha256:d968ac2e2702a40db4ecb5c95b5866c043f2d7c2ae40a32f6783efa149e4abbb`
and the orphan-audit receipt is
`sha256:a875a4c897ddbd88e36cfea8545619c8f4e96c539708d7e05d2eaa9892898671`.

This was a provider-control smoke using the official hello-world image. It is
not parser or compiler inference, a Public Core repeat, model speedup evidence,
or Champion evidence. The pre-cleanup billing query returned no records, which
may reflect provider accounting delay and is not a final zero-cost claim. See
`docs/release/STRUCTARA_V6_COMPLETION_REPORT_2026-08-01.md`.
