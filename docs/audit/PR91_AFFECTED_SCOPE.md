# PR91 affected workflow scope

This successor selects checks for the reviewed parser delta while preserving a separate
full release prerequisite. It does not claim a hosted run, deployment qualification,
or a pass inherited from an older run. Publication and any full/manual execution remain
the release coordinator's decisions.

## Source and comparison identity

The workflow packet has exactly eight paths: six existing workflow files, this document,
and `tests/unit/test_pr91_affected_workflow_contract.py`. Its exact preimage is the
unpublished reviewed tree `397210e9e91fd398165988ef533f29b3ff283d36`. A separate two-path
packet supplies the classifier and its direct unit test. The old parser payload and
fixture/test packets are unchanged.

The classifier checks the actual event head and the pinned historical anchor commit
`621b7d692d21ca73e133010e7e234cc0ffe28086`, tree
`be7d4a6a5166b4b6a31372d1496fa3d7a26e65c8`. Its fixed-anchor delta and the cumulative PR
merge-base diff are separate receipts. The remote checkout need not contain the private
397 tree object: the six reviewed payload blob identities are checked directly at the
event head. Missing or incorrect identity, unexpected file modes, deletion of a registered
path, payload drift, and malformed PR91 inputs fail with `broad-required`. A changed path
outside the reviewed payload escalates to `full` (next section). Other PRs, main pushes,
manual runs, and the existing Security schedule retain full selection policy within their
existing workflow triggers.

## Unknown-path escalation to full qualification

Rule: on PR #91, when any path in the fixed-anchor delta lies outside the reviewed narrow
payload (the six parser payload files, the K15 entity pair, the named CI-control files, the
K06 test, the eight joined sources and the four OCR v3 paths), the classifier selects
`mode=full`. Every job runs, exactly as a `workflow_dispatch` run does, and CI, Security
and Model CI each produce their `Full qualification` marker from that full path. It never
selects a narrower mode and never refuses for that reason. The receipt and the step log say
so: `reason_codes` is `["unknown-path-full-escalation"]`, `unreviewed_paths` lists every
such path, and the CLI prints `Full qualification selected: ...` before the mode line.

Reason: an unknown path is more risk, not less. Refusing it (the earlier
`broad-required: unknown-path` verdict) failed every pull_request run and left the PR with
no current qualification at all, while a narrower mode would have omitted the checks that
an unreviewed path most needs. Full is the original policy every other PR already gets, so
the escalation removes no guard.

Narrow modes remain only for heads whose every changed path is inside the payload. Those
heads still pass every existing narrow check (payload and entity blob identity, unchanged
build inputs, file modes, no deletion or rename, required test presence, route
combinations); a failure there is still `broad-required`. The escalation happens after the
event identity, same-repository, anchor-tree and ancestry checks, so a wrong head, a fork or
missing history still fails closed. A full result inherits no narrow admission: the receipt
carries no `unchanged_inputs`, `entity_sources`, `joined_sources` or `ocr_v3_product_core`.

Same-repository source checkouts now explicitly use the actual PR source head rather
than the synthetic merge revision. Existing Foundation repository/ref inputs and the
manual release revision remain unchanged. The five scope jobs fetch full history with
credential persistence disabled and publish the tested checkout identity.

## Selected execution

| Workflow | `parser-delta` execution | Full selection |
| --- | --- | --- |
| CI | Classification and exact current-outcome receipt | Existing nine broad jobs and full marker |
| PR91 focused | Python 3.12/3.13: fixture preparation, selected collection, original nine files, seven shared/routing files, changed-file Ruff, affected package mypy | Existing image/GPU/web/joined jobs also execute; collection remains full; focused result alone cannot qualify release |
| Security | Python CodeQL under the existing GHAS condition; filesystem vulnerability/secret/IaC/license/SBOM scans; IP privilege guard | Dependency review/audit and application images also execute under existing conditions; full marker |
| Model CI | Classification and explicit unexecuted-job receipt | Existing registry, local images, optional manual provider smoke, and full marker |
| Joined E2E | Classification and explicit unexecuted-journey receipt | Existing joined journey executes |

The focused original nine-file array is preserved. Historical fixture preparation precedes
collection. The seven additional files cover parser-cache/history/semantic pipeline
consumers, answer compilation, semantic fixtures, and both new routing contracts.
Collection, each pytest group, lint, and type checking must succeed on both interpreters.
Narrow Ruff consumes only the safely validated exact anchor-to-head changed `.py` paths
from `delta.python_paths`, using NUL-separated shell arguments. Full Ruff preserves its
existing `956b2efb458bb6062e94f83247acd83696bd3a57` comparison. Mypy checks the compiler
runtime and CIR source packages because those are the affected shared type dependencies.

Aggregate jobs validate the exact expected `needs` set, successful classification,
recognized mode, and every current selected result. Omitted jobs must be skipped and
are recorded as not executed. Failed/cancelled/missing jobs cannot become a pass.
The existing focused aggregate name is retained, and its receipt always states that
focused qualification alone is insufficient for full release qualification.

## OCR v3 product-core scope

`parser-entity-ocr-v3-delta` is a separate finite registration, not the parser/entity route:
exactly `packages/product-core/src/akc_product_core/{contracts,compiler,journal}.py` and
`tests/unit/test_product_core_ocr_v3.py`, regular files only, with that test required in the
change set. It is admitted only on top of the pinned parser and entity payloads. An adjacent
path, including a rename target, is outside the payload and escalates to `full`. Any other
combination, deletion or mode change stays `broad-required`, and every parser/entity
payload, unchanged-input, ancestry and identity check still applies.

PR91 focused adds the OCR v3 test and the direct journal, journal-maintenance, region-anchor
and bridge tests to the parser and entity files, and adds `packages/product-core/src` to mypy.
Changed-path Ruff and the seven shared routing files run as before. Security runs its existing
core set. Joined E2E runs only when joined sources are selected. Product-core ships in the
packaged wheel and in its own image, so the compiler-runtime wheel-exclusion argument does not
apply. Each aggregate receipt lists every omitted job as `pending_debt`, and
`full_qualification` stays false. No workflow builds `infra/product-core/Dockerfile` in any mode.

## Full prerequisite and release guard

CI, Security, and Model CI each have an exact `Full qualification` job. It runs only after
successful classification in full mode and requires all appropriate existing jobs to
succeed. Security retains explicit private-repository GHAS exemptions and the original
PR-only dependency-review condition. Model CI retains its explicit optional manual
provider-smoke condition. These exemptions are reflected in the current outcome receipt;
they are not inherited passes or blanket scanner omissions.

The manual release prerequisite retains the original workflow display-name and successful
run checks, then also checks each canonical workflow path (`ci.yml`, `security.yml`, or
`model-ci.yml` under `.github/workflows`), the immutable source revision, completed status,
and latest run attempt. A documented `@ref` suffix is stripped from the run path. The
attempt-specific jobs endpoint must return a complete list with at most 100 jobs and one
exact successful, completed full marker with the same run ID and head SHA. Missing,
duplicate, truncated, paginated, wrong-path, stale-attempt, and wrong-revision evidence
fails closed. The latest run is read again after fetching jobs to reject a changed attempt.

Attempt identity comes from the attempt-specific endpoint and the latest-run recheck;
the guard does not require an undocumented `run_attempt` field on each job. The API
contracts are documented in GitHub's [workflow run response](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run)
and [attempt-specific job listing](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt).
Model CI remains mandatory for release gates 2, 5, and 6 as before. Manual release
checkout fetches historical objects and prepares the pinned parser fixtures before its
existing full pytest gate. A green narrow workflow cannot satisfy these full markers.

## Evidence boundaries

Unchanged source inputs are static provenance only. In particular, unchanged wheel/runtime
inputs do not prove identical image bytes or digests: builder context/package copies and
runtime virtual-environment copies still have to be built and observed when selected.
Historical CI/security/model/image results remain historical; this packet inherits none.

Local evidence uses the existing Python 3.12.14 interpreter and standard library. The new
17 contract methods check bounded known workflow text and execute the actual inline
Python evaluators and release guard with synthetic outcome/API payloads. A matching exact
397 baseline fails those new requirements. Three selected immutable parser-upgrade CI
methods also pass using exact 397 runtime/CIR/fixture/test source copies and the candidate
workflow copies; temporary historical fixtures are prepared from local pinned Git objects.
Their source bytes remain unchanged, and no older compilation cases or full suites run.

These witnesses do not parse all YAML, evaluate GitHub expressions, or run Actions. No
local YAML parser/actionlint, locked pytest/Ruff/mypy, Python 3.13, hosted CI, browser,
image build, provider, or release job was executed. Those execution gates remain open.
Required-check policy compatibility and actual hosted workflow parsing still require the
coordinator's review before any claim of hosted qualification.
