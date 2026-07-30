# User action handoff

Updated: 2026-07-30

Repository-local implementation is ready. The items below require an account,
payment method, domain control, licensed data, an independent reviewer, or a
real operating environment. Do not paste secrets into chat or commit them.
Store them in the deployment secret manager and provide only the resulting
secret references, resource IDs, and approved public URLs.

## No action required now

- OpenDART: the credential already present on this workstation was verified
  with the official disclosure search and original-document endpoints. The
  repository collector reads it without printing or committing it.
- Local application review: the site, API, deterministic workers, browser
  flow, local operational matrix, and synthetic benchmark contracts run
  without paid services.

## Immediate action needed to publish the completed branch

The local branch `agent/complete-masterplan-local-implementation` is committed
and ready to push. The refreshed token authenticates as
`0ssol1620-byte`, but that account cannot currently resolve or push to the
configured remote `phillipsoul/ai-knowledge-compiler`.

Choose one:

1. grant `0ssol1620-byte` write access to
   `phillipsoul/ai-knowledge-compiler`; or
2. provide the exact GitHub repository URL that should replace the current
   origin.

No new token is required if the existing account receives repository access.
After either action, the prepared branch can be pushed and opened as a draft
pull request without further code changes.

## Actions needed for native design and UX-research evidence

1. Finish connecting the Figma plugin and select the destination team/project
   if a native Figma file is required. The repository already freezes the
   variable, component-variant, naming, and handoff contract.
2. Recruit and consent the participants defined in UI masterplan chapter 32,
   then provide the research workspace or approved findings IDs. Local
   prototypes and test scripts cannot substitute for participant evidence.

## Actions needed before a real model benchmark

1. Create or approve the GPU/serverless account and billing limit.
2. Create dedicated endpoint-scoped provider credentials; never reuse a
   personal full-account key.
3. Provide endpoint IDs and immutable model/runtime image revisions for
   PaddleOCR-VL, Qwen, and any approved comparison candidates.
4. Approve a hard cost ceiling for the one-page smoke, Gate 2 benchmark, and
   load/chaos environment.
5. Provide a rights-cleared corpus manifest with at least 150 documents and
   1,500 pages, frozen train/validation/holdout hashes, labels, annotation QA,
   and an independent approver.

Ready inputs:

```text
AKC_RUNPOD_API_KEY
AKC_QWEN_ENDPOINT_ID
AKC_QWEN_MODEL_REVISION
AKC_QWEN_RUNTIME_IMAGE_DIGEST
AKC_GPU_ALLOWED_INPUT_HOSTS
AKC_GPU_ALLOWED_OUTPUT_HOSTS
```

The exact execution and promotion gates are already fail-closed in
`infra/model-registry/`, `benchmark/`, and
`docs/runbooks/gpu-provider-jobs.md`.

## Actions needed before staging or production deployment

1. Choose the cloud account, region, public domain, and DNS owner.
2. Provision managed PostgreSQL, Redis over TLS, private object storage,
   workload identity, secrets, ingress, backups, and isolated staging.
3. Create the production OIDC application and approved callback URL; provide
   issuer, client ID/secret, endpoint hosts, and claims policy.
4. Verify an email-sending domain and create a restricted Resend key and
   sender.
5. Create a Turnstile site/secret pair for the public registration domain.
6. Choose the merchant/payment connector, complete its KYC/settlement setup,
   and provide the merchant ID and dedicated webhook secret.
7. Choose or provision the malware scanner and CDR service if those controls
   are required for the launch tier.

Ready inputs are enumerated in `.env.example` and
`infra/kubernetes/secret-keys.md`. Production validators reject fake providers,
local credentials, missing TLS, wildcard origins, and incomplete secret sets.

## Actions needed for launch approval

1. Enable branch protection, CODEOWNERS, required CI/Security/Model checks, and
   protected deployment reviewers in the GitHub repository.
2. Commission the independent tenant-isolation/security assessment and
   penetration test.
3. Obtain counsel approval for Terms, Privacy Notice, DPA, subprocessors,
   dataset/model/runtime licenses, notices, residency, and training language.
4. Recruit 30–100 consented private-beta users and name accountable product,
   security, SRE, finance, and release approvers.
5. Run the prepared nonproduction scale matrix: 1,000 SSE clients, 100
   uploads, a 10,000-page enqueue, mixed-tenant fairness, export burst, and the
   named failure drills.
6. Approve the canary sequence and perform the recorded one-change rollback.

The immutable evidence requirements and ownership are defined in
`docs/release/EXTERNAL_GATES.md`. No local or synthetic result is allowed to
close those external gates.

## Handoff format

When the actions are complete, provide only:

- the secret-manager reference names, not secret values;
- cloud resource IDs and exact public origins;
- provider endpoint/model/image revisions;
- corpus manifest path and its SHA-256;
- GitHub repository/branch and required-check names;
- approver names or review ticket IDs;
- the approved spend ceilings.

With those references available, the remaining work is configuration,
deployment, evidence execution, and final gate sign-off; no product redesign is
required.
