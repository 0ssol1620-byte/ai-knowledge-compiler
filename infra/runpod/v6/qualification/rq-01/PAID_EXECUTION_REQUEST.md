# rq-01 — Paid Execution Request (approval document, not a receipt)

**Status of this document itself: a request for explicit, separate user
approval.** It contains no live qualification receipt, claims that nothing
has been built or run, and marks every dollar figure `(ESTIMATE_UNVERIFIED)`
because this agent has no live RunPod rate-card access. Approving this
document does not itself create a pod, push an image, or spend money — each
of the numbered items below is its own decision point.

---

## 0. What this request is, in one paragraph

D1–D9 produced two runtime-image *definitions*
(`paddleocr-vl-1.6-fastdeploy-c8`, `mineru-3.4.4-vlm-c1`), a synthetic smoke
fixture, a build workflow, and an anti-fabrication qualification mechanism —
all as source code, never executed against real GPU hardware. This document
asks for permission to spend real money and take an irreversible registry
action so that qualification smoke testing (not confirmatory inference) can
actually run and produce a real `folynta.baked-runtime-qualification.v1`
receipt for each of the two images.

---

## 1. Target GPU

Source: `infra/runpod/v6/pod_client.py` `_ALLOWED_GPU` (the only GPUs this
codebase's pod client will accept — this request does not propose any GPU
type outside that allowlist):

```
NVIDIA GeForce RTX 4090
NVIDIA A40
NVIDIA RTX A6000
NVIDIA L40S
```

| Priority | GPU | Why |
|---|---|---|
| **Primary** | NVIDIA L40S (48 GB VRAM) | Both candidate models are small (PaddleOCR-VL-1.6 ≈0.9B params, MinerU2.5-Pro-2605-1.2B ≈1.2B params — see `infra/runpod/v6/qualification/rq-01/lineage.json` `targets.*.weights_repository`). Neither needs anywhere near 48 GB; L40S is chosen for comfortable headroom against the FastDeploy/Paddle inference-server overhead and PyTorch/transformers activation memory during a cold first-run smoke pass, at a mid-tier hourly rate rather than the higher-end A100/H100 tiers (which are not even on the allowlist and are correctly excluded). |
| **Fallback** | NVIDIA RTX A6000 (48 GB VRAM) | Same VRAM class as L40S, same headroom rationale, used only if L40S availability or price is unfavorable in the target region at request time. |

`NVIDIA A40` (48 GB) and `NVIDIA GeForce RTX 4090` (24 GB) remain on the
allowlist as further fallbacks in that order — the 4090's 24 GB is still
comfortably sufficient for models this size but has the least headroom of
the four, so it is listed last rather than excluded.

Both `QualificationPodSpec.__post_init__` (`infra/runpod/v6/qualification_pod.py:60-61`)
and `PodCreateSpec.from_mapping` (`infra/runpod/v6/pod_client.py:111-112`)
independently reject any GPU type not in their respective allowlists, so an
out-of-list GPU cannot be created even by mistake.

---

## 2. Run count

Up to **4 pod sessions total** — baseline + validation for each of the 2
candidate images:

| Candidate | Baseline run | Validation run | Condition to proceed to validation |
|---|---|---|---|
| `paddleocr-vl-1.6-fastdeploy-c8` | 1 | 0 or 1 | Only if the baseline's qualification result reports `intra_pod_determinism: true` |
| `mineru-3.4.4-vlm-c1` | 1 | 0 or 1 | Only if the baseline's qualification result reports `intra_pod_determinism: true` |

**Explicit non-retry rule:** if a baseline run's smoke output is
non-deterministic (`intra_pod_determinism: false` — the field asserted by
`infra/runpod/v6/build_runtime_qualification.py` and
`infra/runpod/v6/runtime_smoke_baseline.py`), that candidate **stops at 1 run**
for this round. It is not silently retried and does not proceed to a
validation run. This is a deliberate cost-saving and honesty rule, not an
oversight: a non-deterministic baseline is itself the qualification finding
(the image fails qualification), and spending on a second run would not
change that finding.

Worst case this round therefore spends on 4 runs; best/expected case (if
either candidate is non-deterministic) is fewer.

---

## 3. Estimated time per run

All figures are ranges, not single numbers, and are `(ESTIMATE_UNVERIFIED)`
— no run has ever been executed against real GPU hardware in this project.

| Phase | Paddle (`paddleocr-vl-1.6-fastdeploy-c8`) | MinerU (`mineru-3.4.4-vlm-c1`) | Note |
|---|---|---|---|
| Image pull (cold) | 8–20 min (ESTIMATE_UNVERIFIED) | 10–25 min (ESTIMATE_UNVERIFIED) | MinerU's Dockerfile does a git clone of the full MinerU source plus a torch/torchvision cu128 reinstall on top of the `runpod/pytorch` base, in addition to its own model weights layer — visibly more install surface than Paddle's single venv + FastDeploy patch, so its image is expected to be at least as large if not larger, and pull time is estimated proportionally higher. |
| Service startup (model load into VRAM) | 2–5 min (ESTIMATE_UNVERIFIED) | 2–6 min (ESTIMATE_UNVERIFIED) | Both models are small (<1.5B params); most of this window is process/runtime warm-up rather than weight loading. |
| Smoke repeats — baseline (3×) | 3–9 min (ESTIMATE_UNVERIFIED) | 3–10 min (ESTIMATE_UNVERIFIED) | 3 repeats against the single synthetic D2 fixture image, per `primary_repeats_lane_b`-style repeat logic used for determinism checking (`intra_pod_determinism`). |
| Smoke repeat — validation (1×) | 1–3 min (ESTIMATE_UNVERIFIED) | 1–4 min (ESTIMATE_UNVERIFIED) | Only runs if the candidate's baseline passed the determinism gate in §2. |
| Evidence collection (receipt build, hash verification, pod delete/absence proof) | 1–3 min (ESTIMATE_UNVERIFIED) | 1–3 min (ESTIMATE_UNVERIFIED) | Includes the `delete()` + `get()` 404 absence proof described in §7 before the session is considered closed. |
| **Total per baseline run** | **~15–40 min (ESTIMATE_UNVERIFIED)** | **~17–48 min (ESTIMATE_UNVERIFIED)** | |
| **Total per validation run** | **~10–25 min (ESTIMATE_UNVERIFIED)** | **~11–30 min (ESTIMATE_UNVERIFIED)** | Pull may be cached from the baseline run on the same account/region, shortening this. |

---

## 4. Cost estimate

All figures below are `(ESTIMATE_UNVERIFIED)` — derived from the
`maximum_hourly_rate_usd ≤ $5/hr` ceiling already hard-coded in
`QualificationPodSpec.__post_init__` (`infra/runpod/v6/qualification_pod.py:70-71`)
and the time ranges in §3, **not** from any live RunPod price quote.

| Item | Low estimate | High estimate | Basis |
|---|---|---|---|
| Paddle qualification, baseline run (1×) | $0.19 (ESTIMATE_UNVERIFIED) | $3.33 (ESTIMATE_UNVERIFIED) | 15–40 min × up to $5/hr cap |
| Paddle qualification, validation run (0–1×) | $0.00 (ESTIMATE_UNVERIFIED) | $2.08 (ESTIMATE_UNVERIFIED) | 0 or 10–25 min × up to $5/hr cap |
| **Paddle qualification, round total** | **$0.19 (ESTIMATE_UNVERIFIED)** | **$5.41 (ESTIMATE_UNVERIFIED)** | sum of the two rows above |
| MinerU qualification, baseline run (1×) | $0.22 (ESTIMATE_UNVERIFIED) | $4.00 (ESTIMATE_UNVERIFIED) | 17–48 min × up to $5/hr cap |
| MinerU qualification, validation run (0–1×) | $0.00 (ESTIMATE_UNVERIFIED) | $2.50 (ESTIMATE_UNVERIFIED) | 0 or 11–30 min × up to $5/hr cap |
| **MinerU qualification, round total** | **$0.22 (ESTIMATE_UNVERIFIED)** | **$6.50 (ESTIMATE_UNVERIFIED)** | sum of the two rows above |
| **Combined round total (both candidates, up to 4 runs)** | **$0.41 (ESTIMATE_UNVERIFIED)** | **$11.91 (ESTIMATE_UNVERIFIED)** | sum of both candidate totals |

These are worked backward from the codebase's own hard hourly-rate ceiling
(`≤ $5/hr`, an already-approved constant in existing code, not a new number
introduced by this document) and the time ranges in §3 — they are not a
quote from RunPod's live pricing API, which this agent cannot reach.

---

## 5. Hard cap proposal (separate from the $500 confirmatory budget)

| Cap | Proposed value | Status |
|---|---|---|
| Per-run cap | $5.00/hr × ≤8h runtime ceiling, i.e. ≤ **$40.00 (ESTIMATE_UNVERIFIED)** absolute per-run ceiling (matching the existing `QualificationPodSpec.maximum_cost_usd` formula: `maximum_hourly_rate_usd × maximum_runtime_hours + non_compute_contingency_usd`, which already caps at $5/hr × 8h + $2 = $42.00 (ESTIMATE_UNVERIFIED) per run) | proposed for this request |
| Total-round cap (≤4 runs) | **$50.00 (ESTIMATE_UNVERIFIED)** | proposed for this request |

Both the per-run rate (`≤ $5/hr`) and per-run runtime (`≤ 8h`) ceilings are
not new — they are already enforced in code by
`QualificationPodSpec.__post_init__` (`infra/runpod/v6/qualification_pod.py:70-73`)
and by `RunPodQualificationClient.create`/`verify_ready`, which delete the pod
and raise `QualificationPodError` if the observed hourly rate ever exceeds
the cap (`infra/runpod/v6/qualification_pod.py:167-170,202-204`). This
request's total-round cap of $50.00 is a new, additional ceiling proposed
specifically for this round's up-to-4 qualification runs; it is far above
the §4 high estimate of $11.91 to leave margin for provider price variance,
while still being a hard stop well below what 4 runs at the absolute
per-run ceiling could theoretically reach (4 × $42.00 (ESTIMATE_UNVERIFIED) = $168.00 (ESTIMATE_UNVERIFIED)).

**This is a SEPARATE budget from `research/experiments/SEM-RISK-CONF-02/protocol.json`'s
`cost.hard_cap_usd: 500.0`.** That $500 cap is reserved for the later,
separate confirmatory-inference round (the 192-input frozen cohort). This
request's proposed $50.00 total-round cap does not draw from, reduce, or
otherwise touch that $500 figure — they are tracked as two independent
budgets against two independent purposes.

---

## 6. Explicit confirmation: confirmatory inference is NOT in scope

**The 192-input frozen confirmatory cohort (lane A: 64 pages + lane B: 64
pages × subsets, per `SEM-RISK-CONF-02/protocol.json` `selection`) is NOT
included in this request.** This request is scoped **only** to qualification
smoke testing against the synthetic D2 fixture
(`infra/runpod/v6/qualification/rq-01/fixtures/rq-01-smoke-001.png`,
`evidence_class: SYNTHETIC_UNSPENT_NO_GROUND_TRUTH` per `lineage.json`).
No ground-truth-bearing document is read, transmitted, or processed by any
run approved under this request. A separate, later approval request — after
this one, and after both images pass qualification — is required before any
GPU spend against the confirmatory cohort or its $500 budget.

---

## 7. Cleanup plan

Every run approved under this request is bounded by mechanisms already built
and present in the codebase, not new proposals:

- **GPU-identity and rate-drift auto-delete on create.**
  `RunPodQualificationClient.create` deletes the pod and raises
  `QualificationPodError` immediately if the provider-reported name drifts
  from the requested name, if the GPU identity does not match the requested
  `gpu_type`'s alias set, or if the observed hourly rate exceeds
  `maximum_hourly_rate_usd` (`infra/runpod/v6/qualification_pod.py:160-170`).
- **Readiness-time drift re-check.** `RunPodQualificationClient.verify_ready`
  re-validates name, `RUNNING` status, GPU identity, and hourly rate before
  the pod is treated as usable, and raises without proceeding if any of
  those checks fail (`infra/runpod/v6/qualification_pod.py:194-204`).
- **Explicit `delete()` + `get()` 404 as absence proof.** The pod lifecycle
  pattern already implemented for confirmatory runs
  (`infra/runpod/v6/confirmatory_pod_controller.py:702-778`) calls
  `client.delete_pod(pod_id)` and then treats only a subsequent `404` on
  `get_pod` as proof of absence — logged as `"observation": "GET_404_NOT_FOUND"`
  — rather than trusting the delete call's own return value. Any pod created
  under this request is deleted through this same delete-then-verify-absence
  pattern.
- **Watchdog deadline.** The same controller computes
  `deadline_monotonic = started_monotonic + maximum_runtime_hours * 3600.0`
  and forces cleanup with a `"confirmatory run exceeded its authorized
  watchdog deadline"` error if the deadline is exceeded
  (`infra/runpod/v6/confirmatory_pod_controller.py:722,749-751`) — this is
  the mechanism that enforces the `≤ 8h` runtime ceiling in practice, not
  just at spec-validation time.
- **Failure or timeout always triggers deletion, independent of outcome.**
  None of the above mechanisms are conditioned on whether qualification
  passed or failed — a pod is torn down on determinism failure, smoke
  failure, timeout, or success alike. No run approved under this request is
  left running past its own smoke pass.

---

## 8. GHCR push — separate irreversible-action approval item

Building either image to a usable, pod-pullable state requires pushing it to
GHCR so the pod can pull it by immutable digest (`QualificationPodSpec`
requires `ghcr.io/...@sha256:...`, `infra/runpod/v6/qualification_pod.py:24,58-59`).
**This push costs $0 but is flagged here as its own approval item, bundled
into this same request, because it is irreversible in a way spend is not:**
GHCR package *versions* are not fully deletable once pushed (they can be
hidden/deprecated but the underlying version history and digest are not
guaranteed to be fully erasable the way a local artifact is). `lineage.json`
currently records `"ghcr_push_performed": false`, and that field must stay
`false` until this specific approval item is granted — approving GPU spend
in §4/§5 does not implicitly approve this push, and vice versa.

---

## 9. Commit/push precondition (separate decision, before the build workflow)

A meaningful build-integrity receipt requires `source_commit` and
`source_tree_sha256` fields that only make sense for **committed, pushed**
source — a receipt claiming build provenance from an untracked working tree
would not actually prove what commit produced the image. Per
`git status --short` at the time this document was written, every new file
from this round (`infra/runpod/v6/qualification/`, the two
`infra/runpod/v6/images/*` directories, `PAID_EXECUTION_REQUEST.md` itself,
and the D1–D9 supporting files) is **untracked**, and per this repository's
"never commit without explicit user ask" policy, none of it has been
committed. **Committing and pushing this work to the remote is therefore
itself a prerequisite decision the user must make before the build workflow
(`.github/workflows/build-ovis-runtime.yml` or an equivalent for these two
images) can produce a receipt that means anything** — this is separate from,
and comes before, the GPU-spend approval in §4/§5.

---

## 10. What's done vs. what remains

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Lineage manifest (`lineage.json`) recording both candidates' weights/source revisions, artifact hashes, runner pins | DONE | `infra/runpod/v6/qualification/rq-01/lineage.json` |
| 2 | Synthetic smoke fixture (no ground truth) | DONE | `infra/runpod/v6/qualification/rq-01/fixtures/rq-01-smoke-001.png`, `evidence_class: SYNTHETIC_UNSPENT_NO_GROUND_TRUTH` |
| 3 | Two Docker image definitions with pinned base image, pinned package versions, pinned model/source revisions, and fail-closed hash checks at build time | DONE | `infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/Dockerfile`, `infra/runpod/v6/images/mineru-3.4.4-vlm-c1/Dockerfile` |
| 4 | Build workflow | DONE | per task context (D5) |
| 5 | Anti-fabrication qualification mechanism (`intra_pod_determinism`, `smoke_passed`, `passed` fields; content-bound receipts) | DONE | `infra/runpod/v6/runtime_qualification.py`, `infra/runpod/v6/build_runtime_qualification.py` |
| 6 | 78 new passing tests (D7/D8) | DONE | per task context |
| 7 | Security audit | DONE (clean) | per task context |
| 8 | Documentation | DONE | `infra/runpod/v6/qualification/rq-01/README.md`, `KNOWN_ISSUES.md`, `SECURITY_REVIEW.md` |
| 9 | This approval request document | DONE | `infra/runpod/v6/qualification/rq-01/PAID_EXECUTION_REQUEST.md` (this file) |
| 10 | Commit + push of this round's work | **NOT STARTED — blocked on user decision (§9)** | `git status --short` shows all round files untracked |
| 11 | GHCR image build + push for both images | **NOT STARTED — blocked on user approval (§8)** | `lineage.json`: `"ghcr_push_performed": false` |
| 12 | Baseline qualification run (both candidates) | **NOT STARTED — blocked on user approval (§4/§5)** | `lineage.json`: `"paid_capacity_ready": false` |
| 13 | Validation run (conditional on baseline determinism, §2) | **NOT STARTED — blocked on items 10–12** | none exists |
| 14 | Real qualification receipt, independently verified | **NOT STARTED** | no `folynta.baked-runtime-qualification.v1` file with `"passed": true` exists anywhere in this repo for either candidate (verified by grep, see report) |

**Nothing in items 10–14 is proven by this document.** This document's own
completeness is the only thing being claimed as done here; the underlying
images and qualification remain `IMPLEMENTED`/`TESTED` at most, not `PROVEN`,
until a real run produces and verifies a real receipt.

---

## 11. Known limitation: qualification-path cleanup and watchdog

`RunPodQualificationClient` (`infra/runpod/v6/qualification_pod.py`) — the
actual client this qualification phase uses — does not itself implement the
delete-then-verify-404-absence-proof pattern described in §7, nor a watchdog
that terminates a pod once its `maximum_runtime_hours` deadline is reached.
Its `delete()` method issues a single `DELETE` call and returns
(`infra/runpod/v6/qualification_pod.py:241-243`); nothing in this class
follows up with a `get()` to confirm the pod is actually gone. Likewise,
`maximum_runtime_hours` on `QualificationPodSpec` is validated at
construction time and feeds the `maximum_cost_usd` calculation
(`infra/runpod/v6/qualification_pod.py:79-84`), but nothing in
`RunPodQualificationClient` reads a clock against that deadline or forces
cleanup if it is exceeded. The delete-then-verify-absence pattern and the
watchdog deadline described in §7 exist today only in
`confirmatory_pod_controller.py`, which this qualification phase does not
use.

A separate driver script — the qualification session driver, being built in
parallel as part of this same round — is responsible for supplying both of
these safety properties around `RunPodQualificationClient`, since the client
itself does not provide them. Until that driver exists and is used for every
run approved under this request, the cleanup guarantees in §7 that reference
delete-then-verify-absence and watchdog enforcement describe the intended
operating procedure, not a property of `RunPodQualificationClient` in
isolation.
