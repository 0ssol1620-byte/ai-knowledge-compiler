# External Evidence Gates

- Assessed: 2026-07-30
- Scope: evidence that cannot be established by repository contents alone
- Masterplan: `AKC-MASTERPLAN-KO-20260729-V2`

This register prevents a checked-in adapter, workflow, template, or runbook from
being mistaken for an operating production control. Every gate below is
currently **OPEN**. A gate may be closed only by immutable evidence bound to the
exact application commit, configuration, migration head, model and dataset
revisions, provider or hardware profile, and policy version that produced it.

Repository implementation gaps are not external gates. They are tracked in
`docs/IMPLEMENTATION_MATRIX.md` under **Remaining local implementation gaps**.
An external bundle cannot waive missing product code or missing deterministic
tests.

## Evidence rules

An acceptable evidence bundle:

1. has a SHA-256 and a stable review reference;
2. contains no customer content, credentials, raw prompts, presigned URLs, or
   personal identifiers;
3. records the exact revision and environment, not merely a date or screenshot;
4. includes raw machine-readable results, failures, exclusions, and the
   command or workflow that produced them;
5. names an accountable owner and independent approver;
6. states an expiry or revalidation trigger for drift-prone facts; and
7. does not convert synthetic contract evidence into a quality, SLO, legal, or
   production-readiness claim.

## Gate register

| ID      | Open external gate                                 | Required acceptance evidence                                                                                                                                                                                                                                                                                                                                                                                                                          | Owner                                 | Masterplan mapping                 |
| ------- | -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | ---------------------------------- |
| `EG-01` | Repository governance and hosted CI                | Private repository URL; protected default-branch rules; CODEOWNER and latest-push approval; required `CI`, `Security`, and applicable `Model CI` checks; protected-environment reviewers; successful run IDs on the release commit; source archive hash.                                                                                                                                                                                              | Repository administrators / Release   | 26.13–26.15, 31, Gate 0–1          |
| `EG-02` | Production cloud and data plane                    | Provisioned regional PostgreSQL, Redis/queue, object storage, ingress, workload identity, secrets, network policies, encryption keys, lifecycle policies, and least-privilege roles; deployment and rollback record; no local-development credential reuse.                                                                                                                                                                                           | Platform / Security                   | 5, 18, 19, 23, 32, Gate 1 and 5    |
| `EG-03` | Real model and provider attestation                | Exact model repository IDs and full immutable revisions; weight checksums; runtime/framework/CUDA versions; quantization and decoding settings; worker image digest and signature; endpoint ID; callback-edge authentication; one-page synthetic provider smoke with revision/checksum/cost cap.                                                                                                                                                      | Model Platform / Security             | 11, 19, 30, 35, Phase 2/4/8        |
| `EG-04` | Licensed golden corpus and measured quality        | Rights-cleared corpus manifest, split hashes, annotation QA, holdout isolation, at least 1,500 pages and 150 documents for Gate 2, all required candidate runs, immutable raw outputs, failure cases, per-class quality/cost/latency, hard-fail checks, champion recipe, and rollback target. Synthetic fixtures do not close this gate.                                                                                                              | Quality / Data Governance             | 22, 34, 37, Gate 2                 |
| `EG-05` | Model promotion, canary, and rollback              | Shadow results; staged 1%→5%→20% evidence (and later stages where approved); route-, language-, and document-class metrics; user-edit and failure signals; one-change rollback demonstration; independent promotion approval.                                                                                                                                                                                                                         | Model Platform / SRE                  | 22.8–22.10, 23, 35.3–35.4, Gate 5  |
| `EG-06` | Security, privacy, and tenant-isolation assessment | Exact production OIDC tenant/issuer/client/callback/claims/JWKS-rotation verification and Team/Enterprise MFA enrollment, challenge, recovery, and policy evidence; deployed cross-tenant/IDOR/BOLA and PostgreSQL RLS report; presigned URL, SSRF, parser sandbox, XSS/CSP, prompt-injection, audit-integrity, API-key-scope, webhook, payment-webhook, and secret-rotation results; cloud-policy review; penetration test and vulnerability triage. | Security / Privacy                    | 5.3, 7, 21, 26.10, 40, Gate 5      |
| `EG-07` | Performance, SLO, load, fairness, and chaos        | Route-specific p50/p95 baseline; error budgets; alert delivery; 1,000 SSE, 100 upload, 10,000-page enqueue, mixed-size fairness and export-burst results; provider slowdown, DB/Redis restart/failover, OOM, partial upload, duplicate completion, expired URL, rollback, and clock-skew drills.                                                                                                                                                      | SRE / Platform                        | 23, 26.11–26.12, Gate 5            |
| `EG-08` | Backup, restore, deletion, and incident readiness  | Timed PostgreSQL backup/PITR and object restore with measured RPO/RTO; isolated destruction; mass deletion receipt and backup-expiry proof; provider-outage, credential-rotation, breach, and incident-escalation exercises.                                                                                                                                                                                                                          | SRE / Security / Privacy              | 18.12, 21.13–21.14, 23.8, Gate 4–5 |
| `EG-09` | Merchant, credits, invoices, and unit economics    | Approved merchant connector; purchase→reserve→consume/release→refund/reversal and dispute evidence; no duplicate charge; provider invoice reconciliation; storage/support/refund costs; recognized revenue; plan-level margin and budget guardrails.                                                                                                                                                                                                  | Finance / Billing                     | 20, 31 과금, 41, Gate 4            |
| `EG-10` | Legal, licenses, notices, and product claims       | Current model/code/dataset/runtime licenses and upstream terms; SBOMs; generated Third-Party Notices; MinerU decision and attribution if used; approved Terms, Privacy Notice, DPA, subprocessors, transfer/residency decisions, upload-rights clause, training statement, and external-provider disclosure.                                                                                                                                          | Counsel / Compliance                  | 2, 30, 31 법률·라이선스, 40, 44    |
| `EG-11` | Private-beta outcome                               | 30–100 explicitly opted-in participants; consent record; support/failure taxonomy; actual correction, fallback, review, export/reuse, cost and margin data; deletion verification; zero severe data-loss/security incident; recorded exit decision.                                                                                                                                                                                                   | Product / Support / Privacy           | Phase 7, 28, Gate 3                |
| `EG-12` | Paid beta and public launch approval               | Storage plan and Precision opt-in disclosures; support workflow; passing Gate 4 evidence; public-launch p95 and security evidence; incident playbook exercise; final current notices and model disclosures; recorded independent go/no-go.                                                                                                                                                                                                            | Product / Executive release approver  | 31, Gate 4–5                       |
| `EG-13` | Enterprise and moat capabilities                   | Customer-backed SSO/SAML/SCIM, BYOK, legal hold, zero-retention, data-residency, dedicated VPC/private-cloud requirements; private deployment proof; consented correction flywheel; trained learned router/verifier; domain-pack and API-ecosystem adoption evidence.                                                                                                                                                                                 | Enterprise / Security / Product       | 38, 40, 42.4–42.5, Gate 6          |
| `EG-14` | Current market and source claims                   | Re-fetch and date every drift-prone source; archive the reviewed snapshot; verify competitor pricing/features, provider pricing, framework compatibility, model revisions, and product wording immediately before release.                                                                                                                                                                                                                            | Product Marketing / Compliance        | 2, 20, 35, 44                      |
| `EG-15` | Full Public Core benchmark execution               | Three complete OmniDocBench v1.7, ParseBench five-dimension, and olmOCR-Bench all-category candidate and incumbent runs on one immutable environment; GT-isolation audit; frozen prediction hashes; official and Structara-critical raw outputs; cost/latency; failure artifacts; bounded variance; license approval; and a signed report bound to the release candidate. Tier-0 smoke evidence is insufficient.                                      | Quality / Model Platform / Compliance | 15A, Phase 5A, Gate 2              |

## Gate-to-release mapping

| Release gate                 | External gates that must be closed                                          |
| ---------------------------- | --------------------------------------------------------------------------- |
| Gate 0 — Architecture freeze | `EG-01`, applicable portions of `EG-03`, `EG-04`, `EG-06`, `EG-10`, `EG-14` |
| Gate 1 — Vertical slice      | `EG-01`, `EG-02`, applicable portions of `EG-06` and `EG-08`                |
| Gate 2 — Golden benchmark    | `EG-03`, `EG-04`, `EG-05`, `EG-10`, `EG-14`, `EG-15`                        |
| Gate 3 — Private beta        | `EG-02`, `EG-06`, `EG-08`, `EG-10`, `EG-11`                                 |
| Gate 4 — Paid beta           | `EG-08`, `EG-09`, `EG-10`, `EG-12`                                          |
| Gate 5 — Public launch       | `EG-01`–`EG-10`, `EG-12`, `EG-14`, `EG-15` as applicable                    |
| Gate 6 — Moat building       | `EG-13`, plus the still-current operational gates above                     |

## Evidence that is explicitly insufficient

The following artifacts are useful prerequisites but do not close an external
gate:

- a checked-in Terraform, Kubernetes, Compose, Runpod, or monitoring file;
- an unexecuted workflow or a workflow run from a different commit;
- a mock or fake-provider test;
- the synthetic benchmark under `benchmark/ground-truth/synthetic-v1.jsonl`;
- a model registry entry containing an unresolved or placeholder revision;
- a legal, privacy, DPA, notice, or subprocessor template;
- an estimate derived from worker timing instead of a provider invoice;
- a local SQLite or disposable PostgreSQL test presented as production RLS;
- a runbook without a dated drill record; or
- a source URL without a current captured and reviewed snapshot.

## Closure record

When an external gate is closed, append a release-owned record outside this
file containing:

```text
gate_id
application_commit
configuration_revision
migration_head
model_dataset_runtime_revisions
environment_or_provider_profile
evidence_bundle_sha256
workflow_run_ids
owner
independent_approver
approved_at
expires_at_or_revalidation_trigger
decision
```

Do not edit an `OPEN` row to `CLOSED` merely because implementation work
finished. The evidence record and approval must exist first.
