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
| `EG-07` | Performance, SLO, load, fairness, and chaos        | Route-specific p50/p95 baseline; error budgets; alert delivery; exact 5,000-file manifest, interrupted 10 GiB/new-process resume, 30,000-page preflight, 1,000-page UI, 10,000-block workspace, 5,000-node graph, 1,000 SSE, 100 upload, 10,000-page enqueue, mixed-size fairness, and export-burst results; provider slowdown, DB/Redis restart/failover, OOM, partial upload, duplicate completion, expired URL, rollback, and clock-skew drills. | SRE / Platform                        | v4 32, 42 Wave 10, 44.6, Gate 5    |
| `EG-08` | Backup, restore, deletion, and incident readiness  | Timed PostgreSQL backup/PITR and object restore with measured RPO/RTO; isolated destruction; mass deletion receipt and backup-expiry proof; provider-outage, credential-rotation, breach, and incident-escalation exercises.                                                                                                                                                                                                                          | SRE / Security / Privacy              | 18.12, 21.13–21.14, 23.8, Gate 4–5 |
| `EG-09` | Merchant, credits, invoices, and unit economics    | Approved merchant connector; purchase→reserve→consume/release→refund/reversal and dispute evidence; no duplicate charge; provider invoice reconciliation; storage/support/refund costs; recognized revenue; plan-level margin and budget guardrails.                                                                                                                                                                                                  | Finance / Billing                     | 20, 31 과금, 41, Gate 4            |
| `EG-10` | Legal, licenses, notices, and product claims       | Current model/code/dataset/runtime licenses and upstream terms; SBOMs; generated Third-Party Notices; MinerU decision and attribution if used; approved Terms, Privacy Notice, DPA, subprocessors, transfer/residency decisions, upload-rights clause, training statement, and external-provider disclosure.                                                                                                                                          | Counsel / Compliance                  | 2, 30, 31 법률·라이선스, 40, 44    |
| `EG-11` | Private-beta outcome                               | 30–100 explicitly opted-in participants; consent record; support/failure taxonomy; actual correction, fallback, review, export/reuse, cost and margin data; deletion verification; zero severe data-loss/security incident; recorded exit decision.                                                                                                                                                                                                   | Product / Support / Privacy           | Phase 7, 28, Gate 3                |
| `EG-12` | Paid beta and public launch approval               | Storage plan and Precision opt-in disclosures; support workflow; passing Gate 4 evidence; public-launch p95 and security evidence; incident playbook exercise; final current notices and model disclosures; recorded independent go/no-go.                                                                                                                                                                                                            | Product / Executive release approver  | 31, Gate 4–5                       |
| `EG-13` | Enterprise and moat capabilities                   | Customer-backed SSO/SAML/SCIM, BYOK, legal hold, zero-retention, data-residency, dedicated VPC/private-cloud requirements; private deployment proof; consented correction flywheel; trained learned router/verifier; domain-pack and API-ecosystem adoption evidence.                                                                                                                                                                                 | Enterprise / Security / Product       | 38, 40, 42.4–42.5, Gate 6          |
| `EG-14` | Current market and source claims                   | Re-fetch and date every drift-prone source; archive the reviewed snapshot; verify competitor pricing/features, provider pricing, framework compatibility, model revisions, and product wording immediately before release.                                                                                                                                                                                                                            | Product Marketing / Compliance        | 2, 20, 35, 44                      |
| `EG-15` | Full Public Core benchmark execution               | Three complete OmniDocBench v1.7, ParseBench five-dimension, and olmOCR-Bench all-category candidate and incumbent runs on one immutable environment; GT-isolation audit; frozen prediction hashes; official and Structara-critical raw outputs; cost/latency; failure artifacts; bounded variance; license approval; and a signed report bound to the release candidate. Tier-0 smoke evidence is insufficient.                                      | Quality / Model Platform / Compliance | 15A, Phase 5A, Gate 2              |

### Collection semantic retrieval closure evidence

The checked-in collection finalizer, semantic compiler, PostgreSQL retrieval
adapter, Settings validation, and Kubernetes contracts are implementation
evidence only. They do not close `EG-02`, `EG-03`, `EG-05`, `EG-06`, or
`EG-07`. Enabling the collection finalizer and semantic retrieval in a release
overlay requires one immutable evidence bundle containing all of the following:

1. the exact application commit, rendered overlay, signed image digests,
   PostgreSQL migration head, database role grants, and RLS policy inspection;
2. proof that `AKC_COLLECTION_FINALIZER_ENABLED` and
   `AKC_COLLECTION_SEMANTIC_RETRIEVAL_ENABLED` changed from `false` to `true`
   atomically, while provider and HMAC values came only from the approved
   external Secret controller;
3. the provider endpoint identity, provider ID, model ID, immutable model
   revision, endpoint-scoped credential grant, and an attested 1024-dimensional
   embedding response with no customer content;
4. rendered NetworkPolicy or CNI evidence for only dispatch-to-API TCP 8000,
   the managed PostgreSQL destination, and the exact approved embedding FQDN on
   TLS 443, with no wildcard public API egress;
5. a synthetic end-to-end canary that records the canonical plan, semantic
   model, retrieval-index receipt, query result, package export/import hashes,
   terminal events, and deployment revision from the same run;
6. deployed failure injections for provider timeout, attestation or model-pin
   mismatch, database unavailability, and package validation failure, proving
   no completed terminal state and exactly one idempotent credit refund where
   credits were consumed; and
7. key-rotation and one-change disable/rollback evidence proving both runtime
   flags return to `false` together without accepting stale-model or stale-plan
   retrieval rows.

Credentials and raw secret values must never be included in the bundle. Record
only Secret object versions or external-controller references and the reviewed
scope of each credential.

### Collection metadata encryption closure evidence

The repository's AEAD codec, blind-index contract, 0026/0027 migrations,
tenant-scoped backfill command, and SQLite/PostgreSQL contract tests do not by
themselves close `EG-02`, `EG-06`, or `EG-08`. Production activation also
requires one reviewed bundle containing:

1. the pre-change backup/PITR recovery point and a timed restore proof;
2. external Secret object versions for the AES decrypt keyring, active key ID,
   and independent blind-index key, without raw secret values;
3. a dated collection-write fence/drain record, serving-role denial on the
   checkpoint table, and the exact managed PostgreSQL migration from 0025 to
   bridge revision 0026;
4. count-only dry-run, apply, and authenticated verify reports for every data
   tenant, plus verified checkpoint/key-ID/count reconciliation;
5. the global 0027 fail-closed gate result, schema inspection proving all three
   plaintext columns are absent, and an authorized API round-trip canary;
6. log, trace, analytics, event, idempotency, replica, snapshot, backup, and WAL
   handling evidence showing where pre-0027 plaintext may remain and its
   approved expiration or cryptographic-erasure date; and
7. an encryption-key rotation, blind-index full-reindex rehearsal, and restore
   or disable rollback exercise using the same write-fence procedure.

Use `docs/runbooks/collection-metadata-encryption.md`. A local report, an
unexecuted runbook, a checkpoint without the authenticated verifier, or a
successful 0027 migration on an empty database is insufficient evidence.

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
