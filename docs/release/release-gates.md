# Release Gates

No gate is satisfied by code presence alone. Evidence is immutable, linked to
the application/model/configuration revisions, and approved by the listed
owners.

The open external-evidence register is
`docs/release/EXTERNAL_GATES.md`. Deterministic product or test gaps remain in
`docs/IMPLEMENTATION_MATRIX.md` and must be closed before external evidence can
be accepted for the affected requirement.

## Evidence protocol

The `Release Gate Evidence` workflow is collection and verification tooling,
not a deploy or promotion workflow. It requires:

- an exact lowercase 40-character commit;
- successful `CI` and `Security` workflow run IDs whose `head_sha` matches;
- a successful matching `Model CI` run for Gates 2, 5, and 6;
- the SHA-256 of a separately reviewed external evidence bundle;
- an approval-record reference and the protected `release-approval`
  environment.

It re-runs local Python/web/contracts/policy checks and emits a hashed manifest
whose state remains `evidence-collected-awaiting-human-go-no-go`,
`deployment_performed=false`, and `promotion_authorized=false`. A digest proves
which external bundle was referenced, not that the workflow understood or
approved its contents.

External bundles must contain only sanitized evidence and bind every result to
the application, configuration, migration, model, dataset, hardware/provider,
and policy revisions that produced it. Do not upload customer content, tokens,
presigned URLs, raw prompts, or personal identifiers.

The repository rules and protected environments required for these controls
are listed in `docs/runbooks/repository-governance.md`. Checked-in workflows do
not prove that those external settings are active.

## Gate 0 - Architecture freeze

- CIR/AKMP 1.0, storage lifecycle, provider/event contracts, threat model, and
  benchmark manifest accepted.
- All ten known specification conflicts resolved by ADR.
- JSON Schema and generated type contracts pass.
- No unresolved high-risk license item.

## Gate 1 - Vertical slice

One synthetic and one approved text PDF complete:

`upload -> quarantine scan -> preflight -> native/OCR -> live event -> source map -> export -> scheduled purge`

Refresh/reconnect, retry, deletion, and deterministic export are demonstrated.

## Gate 2 - Golden benchmark

- At least 1,500 ground-truth pages and 150 documents.
- All baseline candidates run under reproducible conditions.
- Official claims and internal results remain separate.
- Champion recipe and rollback target approved.
- Numeric, page-loss, repetition, provenance, tenant, license, and external
  policy hard-fails are zero.

## Gate 3 - Private beta

- 30-100 explicit beta participants.
- Correction UI and failure taxonomy operational.
- Actual cost telemetry and stable review/fallback rates.
- Deletion verification and approved privacy/terms.
- Zero severe data-loss or security incident.

## Gate 4 - Paid beta

- Reserve/consume/release/refund/reversal ledger.
- Payment and storage plans, Precision opt-in, support workflow, and margin
  guardrails.
- Backup/PITR and restore drill evidence.
- Failure produces no duplicate charge.

Local deterministic prerequisite evidence (2026-07-30): the GPU scheduler
creates OOM-reduced or exact registry-approved internal fallback work as a new
immutable invocation, preserves parent/root hashes and strategy evidence, and
uses deterministic transition idempotency. Duplicate failure delivery retained
one child, one resume, and the original single credit-ledger entry in local
fake-provider tests. The complete scheduler suite passed 85 tests and the
SQLite migration cycle ended at `0020_gpu_invocation_transitions`. This does
not establish provider behavior, production reconciliation, load/chaos, or
invoice evidence; `EG-03`, `EG-07`, and `EG-09` remain open.

## Gate 5 - Public launch

- Versioned route-specific p95 SLOs pass.
- Cross-tenant, parser sandbox, SSRF, and prompt-injection suites pass.
- Model canary and one-change rollback demonstrated.
- SBOM, licenses, Third-Party Notices, provider disclosures, incident
  playbooks, subprocessor register, and legal approvals current.

## Gate 6 - Moat building

Learned router, evidence-grounded verifier/repair, consented correction
flywheel, domain packs, API ecosystem, and enterprise private processing remain
separately gated capabilities.

## Definition of done

```text
source preserved
+ accepted blocks pass quality gate
+ provenance complete
+ warnings surfaced
+ credits settled
+ retention scheduled
+ export reproducible
+ user can verify the result
```

## Evidence ownership

| Evidence                            | Accountable owner                      |
| ----------------------------------- | -------------------------------------- |
| architecture/schema compatibility   | Architecture                           |
| corpus/quality/promotion            | Quality and Model Platform             |
| RLS/upload/parser/incident controls | Security                               |
| consent/retention/deletion/DPA      | Privacy and Counsel                    |
| credit/cost/margin/refund           | Finance and Billing                    |
| SLO/load/restore/canary             | Platform/SRE                           |
| final go/no-go                      | Product and executive release approver |

## Required operating evidence

Depending on the gate, attach:

- recorded synthetic vertical slice with upload/security/preflight/SSE/export/
  deletion and credit/event/provenance reconciliation;
- licensed corpus manifest and immutable quality/cost/latency results;
- signed image digests, SBOMs, vulnerability/license decisions, model revision,
  and rollback recipe;
- route-specific load results and bounded chaos/failover evidence;
- timed database/object restore with measured RPO/RTO and isolated destruction;
- canary/rollback record and alert delivery;
- approved Terms, Privacy Notice, DPA/subprocessor/transfer decisions;
- beta participant consent, incident/support outcomes, and actual unit
  economics.

Missing, stale, mismatched, or synthetic-only evidence leaves the gate open.
