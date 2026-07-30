# Repository governance

Repository settings are an external control and are not proven by committed
workflow files. Configure them before accepting release evidence.

## Protected default branch

- require pull requests and at least one CODEOWNER approval;
- dismiss stale approvals and require approval of the latest push;
- require conversation resolution;
- block force pushes, branch deletion, and administrator bypass;
- require signed commits or an equivalent verified-identity policy;
- require the current `CI`, `Security`, and applicable `Model CI` checks;
- require linear history if that matches the repository merge policy.

Do not mark a workflow optional merely because a dependency, vulnerability,
license, infrastructure, or external-evidence gate is red.

For a private repository without GitHub Advanced Security, leave the repository
variable `AKC_GHAS_ENABLED` unset. The Security workflow still fails on Trivy,
Python, JavaScript, image, secret, IaC, and license findings, while the
GHAS-only CodeQL, dependency-review API, and SARIF upload steps remain skipped.
After GHAS is enabled, set `AKC_GHAS_ENABLED=true` and add the CodeQL and
dependency-review jobs to the required checks. A skipped GHAS-only job is not
evidence that CodeQL or dependency review passed.

## Protected environments

Create these environments with independent reviewers and no self-approval:

| Environment        | Purpose                           | Required configuration                                                          |
| ------------------ | --------------------------------- | ------------------------------------------------------------------------------- |
| `release-approval` | Non-promotional Gate 0-6 evidence | release approvers, no deployment credentials                                    |
| `model-staging`    | One-page provider smoke           | `RUNPOD_API_KEY`, `GPU_CALLBACK_HMAC_SECRET`, synthetic input URL/key/checksum  |
| `staging-drill`    | Bounded k6 evidence               | exact `AKC_STAGING_DRILL_ALLOWED_ORIGINS`, disposable test user/project secrets |

Limit secret access to the workflow/environment that needs it. Rotate a secret
after suspected exposure, remove old versions after overlap verification, and
never copy values into issues, pull requests, logs, artifacts, or evidence
manifests.

## Periodic audit

Quarterly and before public launch, export or screenshot the active rulesets,
environment reviewers, installed GitHub Apps, deploy keys, Actions permissions,
OIDC trust policies, and audit-log retention. Bind that snapshot to the release
revision. A checked-in document is guidance, not proof that those controls are
currently enabled.
