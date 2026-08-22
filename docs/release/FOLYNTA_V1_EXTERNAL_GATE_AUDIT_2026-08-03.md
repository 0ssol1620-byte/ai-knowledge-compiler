# FOLYNTA v1 external gate audit — 2026-08-03

Authority: `D:\FOLYNTA_NEAR_PERFECT_BACKEND_AND_CINEMATIC_WORLD_CLASS_FRONTEND_MASTERPLAN_FINAL_v1_KO_2026-08-03.md`

Release decision: `PRODUCTION-REJECT`

This audit records live, secret-free observations. It does not convert a
provider smoke, a small demo cohort, or a disposable CI service into production
evidence.

## Live observations

| Gate | Observation | Decision |
| --- | --- | --- |
| RunPod inventory | Serverless endpoint inventory returned `[]`; GPU Pod inventory returned zero Pods. | Cleanup state verified; parser/compiler qualification is still open. |
| RunPod billing | The last 72 hourly buckets returned zero records and provider total `0`. | No invoice-backed model run exists in this window; cost and concurrency gates remain open. |
| Cloudflare R2 | Four private buckets, exact-origin CORS where configured, ETag exposure, and incomplete-multipart lifecycle rules are observable. Both supplied credential profiles can list objects across multiple buckets. | `PARTIAL`; role-separated, bucket/prefix-scoped application credentials are not proven. |
| PostgreSQL | The configured URL resolves to loopback PostgreSQL. The existing GitHub Actions receipt proves migrations and RLS only on a disposable PostgreSQL 17 service. | Production RLS, backup, and isolated restore remain open. |
| Public Core | Only the 18-image OmniDocBench demo and evaluator/adapter caches are present locally. The host GPU is a GTX 1660 SUPER with 6 GiB VRAM. | Full OmniDocBench, ParseBench, and olmOCR-Bench candidate/incumbent runs repeated three times are not executable from this host state. |
| Private Q1/Q2/Q3 | No approved 1,500-page/10,000-fact or 5,000-page/30,000-fact private ground-truth manifest is present; the 100,000-page field window has not elapsed. | Required external empirical evidence remains open. |
| Independent gates | No independent beta panel receipt, legal/domain clearance, or external Ed25519 release-key signature is available. | Human and third-party approval gates remain open. |

## Evidence receipts

- `benchmark/reports/folynta-runpod-inventory-live-2026-08-03.json` — SHA-256 `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`
- `benchmark/reports/folynta-runpod-pod-inventory-live-2026-08-03.json` — SHA-256 `b6f4f2e65211a927a90b464c3a259c5a2dcc631fc5e9415bb84b74232f8ef2ea`
- `benchmark/reports/folynta-runpod-billing-72h-live-2026-08-03.json` — SHA-256 `4974d0c18835c0a54cfbb355e87fa544c0cab855b7b727afb00a863ad06a0920`
- `benchmark/reports/folynta-r2-production-gate-live-2026-08-03.json` — SHA-256 `620299c7b5c5b200d17207212e05354a6af28d151593d5b2bcf122f71d97a8d1`
- `benchmark/reports/folynta-postgres-rls-ci-gate-2026-08-02.json` — disposable-CI boundary only; not production proof.
- `benchmark/reports/public-core-tier0-status-2026-07-31.json` — adapter/evaluator smoke only; all three full official runs remain false.

All 2026-08-03 provider probes were read-only. No endpoint, Pod, bucket,
credential, object, database, or billing state was created, changed, or deleted.

## Required evidence before launch

1. Candidate and incumbent full Public Core runs, exactly three repeats under
   frozen identities, plus signed official and critical evaluator receipts.
2. Owner-approved Q1 and Q2 private manifests and independent annotations,
   including 30,000 critical facts, followed by the Q3 field-shadow window.
3. Separate bootstrap and least-privilege R2 application credentials, an
   object-prefix policy receipt, and timed delete/restore evidence.
4. Managed production PostgreSQL with non-owner/no-BYPASSRLS roles, backup/PITR,
   cross-tenant denial, and an isolated timed restore.
5. RunPod parser/compiler concurrency and fault drills with invoice
   reconciliation and terminal cleanup receipts.
6. Independent private beta evidence, legal/domain/commercial clearance, and an
   external release-owner signature.

Until every item above passes, deployment of this branch as production would
violate the masterplan's truth and release requirements.
