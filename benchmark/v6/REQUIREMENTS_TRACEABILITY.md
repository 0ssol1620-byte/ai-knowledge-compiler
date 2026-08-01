# Structara v6 benchmark and RunPod requirements traceability

Scope is limited to `benchmark/v6`, `infra/runpod/v6`, and focused tests. The
table distinguishes locally provable contracts from execution evidence that can
only come from real models, datasets, provider resources, or product services.

| Masterplan | Local evidence | Current verdict |
|---|---|---|
| 0 spend authorization and runaway exceptions | `SpendPolicy` never uses expected cost as a mandatory-test block; `SpendGuard` hard-stops duplicate identities, retries, double billing, and anomalous error cost | Contract pass; actual hello-world control smoke run, mandatory model spend pending |
| 1 research identity corrections | Candidate records preserve stated repositories/versions while unresolved exact revisions and licenses remain non-promotable | Contract pass; external identity review pending |
| 2 authority-first, hard-fail-first selection | `evaluate_promotion` and `build_champion_matrix` reject critical failures, majority authority, and non-production champions | Pass |
| 3–4 parser and compiler registries | `candidate-registry.yaml` includes 45 mandatory/optional recipes; official read-only research pins 20 model revisions (18 of 28 required candidates) while missing file manifests and images remain null | Pass; all external candidates fail closed |
| 5 agent mesh isolation duties | Environment identity forbids inference GT; signed artifacts bind evidence and failures | Contract pass |
| 6 runtime identity/readiness | Immutable image/model/GPU/CUDA/framework identity and model-isolated disabled pools | Contract pass; boot/warm/restart/cache receipts pending |
| 7–9 stages, public gates, critical metrics | Existing public registry is checked for all three suites, GT isolation, and exactly three repeats; run schemas capture critical/GT/cost evidence | Contract pass; full runs and scores pending |
| 10 autonomous states | Billing contract recognizes verified/authority/cross-model/auto-repaired and makes unresolved/quarantined/failed non-billable | Pass |
| 11–15 recovery, compiler, package, retrieval, estimates | G4–G8 stay blocked until corresponding actual artifacts exist; no adapter or mock can satisfy promotion | Fail-closed contract pass; execution external to this package |
| 16 RunPod execution | Live REST v2 management inventory/create/update/drain/delete, queue run/status/cancel, billing history, per-model pools, provider retry zero, write-ahead idempotency, cost anomaly, GET-404 deletion receipt, and tagged orphan audit | Local/mock pass plus actual hello-world control endpoint, exact-three completion, GET 404, and orphan 0; model execution receipts pending |
| 17–18 waves and artifacts | Repeat directories, environment/run/endpoint/spend/promotion/champion/evidence schemas | Pass |
| 19 G0–G9 | G0–G8 are inputs, G9 is computed only after all G/MP gates and candidate/incumbent/target/release/registry-bound signed actual evidence pass; Public Core requires the exact 18-receipt candidate+incumbent × 3 suites × 3 repeats matrix | Pass |
| 20 Champion Matrix | Eight page classes start unresolved; authority fields do not imply a parser champion | Pass; selection pending real evidence |
| 21–22 forced execution and DoD | Offline preflight refuses false completion and lists exact external blockers | Pass as a truth gate; production DoD not met |
| 23 source registry | Candidate source identifiers are recorded without treating mutable upstream names as exact identity | Pass; independent upstream verification pending |
| 38 deterministic parallel benchmark | Document groups remain intact; exactly three repeats share one environment and never share prediction/log roots; the hash-chain ledger resumes acknowledged provider jobs without redispatch | Pass |
| 39 cost and scaling | Fair priority lanes, deterministic size-aware least-load assignment, capability/infra/semantic health filtering, URL/cache/evaluator/DB backpressure, dynamic target caps, soft cost alert, runaway stop, and cleanup contracts | Contract pass; actual queue speedup and cost remain pending |
| 40 research backlog | No learned/meta/conformal research item is presented as production evidence | Pass |
| 41 failure scenarios | Focused tests cover silent contract violations, duplicates, retry/runaway, cleanup preconditions, tampering, and page loss | Local pass; real kill/OOM/network/straggler drills pending |
| 42 database/events/idempotency | Append-only write-ahead dispatch intent, provider acknowledgement, status, acceptance, separate provider/user billing, cleanup, and hard-stop events are hash chained; ambiguous writes never auto-retry | Contract pass; shared DB/event integration belongs to platform runtime |
| 43 product UI | No Pod implementation detail is exposed from this package; promotion remains blocked without product evidence | Not claimed here |
| 44 parallel waves | P0/P1/P8 release contracts and gates are executable offline | Partial; provider waves pending |
| 45 MP0–MP6 | Required by promotion; MP0 has deterministic local proof, remaining real-operation gates cannot be synthesized | Fail closed |
| 46 forced prompt prohibitions | HTTP success, mocks, cost skipping, unsigned evidence, duplicate charge, and fail-overwrite cannot promote | Pass |
| 47 final DoD | Preflight reports Production Reject until actual multi-worker, cost, quality, failure, continuity, package, retrieval, and cleanup evidence is signed | Honest Production Reject |

## External execution gaps

1. Resolve every mandatory candidate to an exact immutable model revision,
   artifact manifest SHA-256, runtime recipe/image digest, and license receipt.
2. Build and boot isolated images; record cold 3/3, warm 20/20, restart 3/3,
   offline cache, GPU leak, and readiness evidence.
3. Run complete public core, robustness, and private hard sets. Candidate and
   incumbent public-core cohorts require exactly three same-environment repeats.
4. Measure multi-worker speedup, GPU seconds, provider invoice, retry/idle waste,
   cost per page, accepted page, and verified page.
5. Perform real worker kill/OOM/network/cache/semantic/straggler/quarantine and
   selective replay drills.
6. Persist failure bundles and every model-cohort endpoint cleanup receipt;
   provider inventory must prove orphan endpoint count zero. The 2026-08-01
   hello-world control cohort satisfied cleanup and orphan-audit mechanics only.
7. Sign the commit-bound external evidence payload with the approved release
   Ed25519 key. Only then may G9 and a Champion Matrix primary become production.
