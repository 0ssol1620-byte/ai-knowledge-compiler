# End-to-End Accuracy & Credit Research Blueprint Traceability

Authority: `D:/Structara_End_to_End_Accuracy_Credit_Routing_Autonomous_Verification_Research_Blueprint_FINAL_KO_2026-08-01.md`
Authority SHA-256: `4e1c6465d0445f1363509b535b2ededd2c7f8bc85f41bf3f025b41a912ebc2d8`
Review date: 2026-08-02 KST

## Interpretation boundary

“Implemented” means the repository contains an executable contract and tests.
It does not turn an untrained learned component into production authority, an
unavailable metric into zero, or a small reproducibility cohort into a public
leaderboard result. Learned classification, routing, or meta-verification stays
shadow-only until its declared calibration and promotion evidence exists.

## Chapter coverage

| Blueprint chapter | Repository realization | Verification state |
| --- | --- | --- |
| 0. Executive decisions | Evidence-first flow across intake, router, parallel runtime, quality, CIR, retrieval, exporters, and UI | Implemented |
| 1. Full design review | This traceability file, model failure reports, unavailable-state semantics | Implemented |
| 2. Target architecture | `services/api`, worker services, PostgreSQL contracts, R2 adapters, immutable event/attempt contracts | Implemented; deployment evidence separate |
| 3. Knowledge Intake | collection manifest, upload policy, resumable intake, digest/dedupe, security/CDR packages | Implemented and tested |
| 4. Static Preflight | `akc_router.preflight`, `estimation.StaticDocumentFeatures`, deterministic first stage and zero-authority learned shadow | Implemented; trained GBDT intentionally not fabricated |
| 5. Clustering & Template Memory | stable cluster identity, population/calibration records, adaptive cluster sampling | Deterministic bootstrap implemented; learned clustering remains promotion-gated |
| 6. Adaptive Sampling | forced extrema, adaptive samples, new `BetaBinomialPosterior` sequential stop | Implemented and tested |
| 7. Credit & Time Estimation | PCU/credit ledgers, P50/P95 estimator, seeded Monte Carlo schedule estimator, reserve/settle contracts | Implemented and tested |
| 8. Risk-Constrained Router | hierarchical deterministic router, candidate forecasts, calibrated lower-bound selector and abstention | Implemented and tested |
| 9. Context Sharding & Multi-Pod | continuity-aware sharding, ownership overlap, size-aware bin packing, hedging, idempotency | Implemented and tested |
| 10. Parser/Model Portfolio | ground-truth-isolated RunPod runners, artifact manifests, three-repeat evaluator, and five formal MinerU/Paddle/DeepSeek/Ovis candidates | Formal demo portfolio complete; continuous/full-corpus evidence remains gated |
| 11. ValidationEvidence 0–10 | `EvidenceLevel`, immutable evidence receipts, numeric/table/source/continuity validators | Implemented and tested |
| 12. Validator Fusion | hard gates, evidence sufficiency, selective risk-coverage curve, autonomous decision | Implemented; learned meta-verifier remains calibration-gated |
| 13. Semantic Worker Health | infrastructure/semantic separation plus stratified Beta posterior, EWMA and CUSUM monitor | Implemented and tested |
| 14. Impact Scope & Recovery | immutable attempt graph, quarantine impact, recovery scopes/actions, First Verified finalization | Implemented and tested |
| 15. Continuity Merge | typed continuity edges, block fingerprinting, cross-page table identity, deterministic merger | Implemented and tested |
| 16. Verified CIR | stable block/page IDs, source refs, canonicalization, user edit lock contracts | Implemented and tested |
| 17. Knowledge Compiler | explicit structure, atomic notes, architecture plans, typed claims and evidence-bound package generation | Implemented and tested |
| 18. Entity Resolution & Graph | new auditable Fellegi-Sunter linkage, authority-conflict hard stop, typed graph contracts | Implemented and tested |
| 19. Retrieval/RAG | tenant-safe hybrid retrieval, structured filters, reranking, answer verification, graph-aware lookup | Implemented and tested |
| 20. Provenance/Package | PROV-compatible refs, checksums, Obsidian/RAG/JSON-LD/package exporters, round-trip validation | Implemented and tested |
| 21. Benchmark/TEVV | repeat-environment identity, official partial evaluator, mutation/fault fixtures, failure-preserving reports | Implemented; continuous/full-corpus evidence remains an operating program |
| 22. Security & Privacy | upload limits, CDR, parser isolation, prompt-injection/markup defense, SSRF controls, tenant/redaction/deletion contracts | Implemented and tested |
| 23. Data & API Contracts | versioned JSON schemas, OpenAPI, attempts/routes/estimates/events and generated TS contracts | Implemented and tested |
| 24. Product UI | intake estimate, processing theater, integrity console, billing truth, completion/package scenes | Implemented with honest unavailable states |
| 25. Technology Stack | monorepo packages, Next.js, FastAPI/Python, PostgreSQL/R2/telemetry adapters, build-vs-buy boundary | Implemented; provider credentials remain environment-only |
| 26. Roadmap | phases represented by package boundaries, tests, this traceability and release gates | Implemented as executable work breakdown |
| 27. Priority Experiments | `RESEARCH_EXPERIMENT_REGISTRY.yml` contains all 24 experiments and evidence owners | Registered and gated |
| 28. KPI & SLO | telemetry metrics, benchmark aggregates, estimate error, worker and cost views | Implemented; field SLO proof requires production observation |
| 29. Risk Register | failure classes, health transitions, hard gates, promotion policy and public truth boundary | Implemented |
| 30. Definition of Done | CI/test/build/browser/deployment evidence checklist in this file and page/asset manifests | Repository gates executable; external gates never self-certified |
| Appendices A–E | bootstrap policy, reason codes, target files, pipeline orchestration, interpretation rules | Reflected in contracts, enums, tests, and this matrix |
| Research registry | official source links frozen in evaluation reports and runtime manifests | Implemented |

## New algorithm evidence

- `packages/router/src/akc_router/research.py`: Beta-Binomial posterior,
  sequential stop, seeded Monte Carlo scheduling, calibrated risk-constrained
  selection and abstention.
- `packages/quality/src/akc_quality/evidence_ladder.py`: levels 0–10, hard-gate
  evidence policy, evidence sufficiency, risk-coverage curve.
- `packages/parallel-runtime/src/akc_parallel_runtime/semantic_monitor.py`:
  stratified posteriors, EWMA, CUSUM, deterministic health projection.
- `packages/retrieval/src/akc_retrieval/entity_resolution.py`: normalized
  Fellegi-Sunter scoring and authoritative-identifier conflict rejection.

## Model evidence boundary

The publishable release contains five formal candidates on the same 18-page
official OmniDocBench demo subset with three blind repeats each: MinerU 3.4.4
pipeline, PaddleOCR-VL 1.6 FastDeploy, MinerU 3.4.4 VLM c1,
DeepSeek-OCR-2, and OvisOCR2 0.9B under the official vLLM cu129 runtime. This is
270 successful formal inference cases with zero hard failure. The subset is
Apache-2.0, ground truth was absent from inference workers, and CDM/overall are
unavailable. Failed Ovis runtime identities remain diagnostic and unscored;
only the separately frozen cu129 identity passed Stage 1 and the three-repeat
gate. Full-corpus and field evidence remain an operating program.

## Final repository verification

- Python: 1,468 tests passed in 527.45 seconds; Ruff passed; mypy passed for
  185 source files.
- Web: 214 unit tests passed; TypeScript, ESLint, and production build passed.
- Browser: 77 E2E checks passed with 17 intentional project-scope skips; the
  independent nine-project browser/viewport matrix passed.
- Visual evidence: 11 deterministic baselines and 532 current-worktree scenes
  passed with zero blocking automated findings.
- Runtime hygiene: the paid RunPod evaluation pod was terminated and the final
  inventory confirmed that the pod was no longer listed.
