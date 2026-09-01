# SEM-RISK-CONF-02 — status after the Paddle runtime loss

**Date:** 2026-09-01
**Audit section:** 28-A
**Verdict: the confirmatory experiment cannot be executed as specified. It is
blocked, not failed, and no partial result may be reported as if it were the
experiment.**

---

## What the protocol requires

`research/experiments/SEM-RISK-CONF-02/protocol.json` names two parsers:

```
parser_roles.primary               = paddleocr-vl-1.6
parser_roles.primary_repeats_lane_a = 1
parser_roles.primary_repeats_lane_b = 3
parser_roles.research_specialist   = mineru-3.4.4-vlm
parser_roles.specialist_promotion_status
    = "research_comparator_only_license_review_required"
```

Both acceptance lanes are defined against the **primary**, not the specialist:

- **Lane A** asks whether a deterministic source-native parser (pypdf) is a
  usable cheap disagreement signal. Its endpoint is defined as
  `high_primary_damage_definition = primary semantic damage >= 0.20 OR primary
  critical-token error > 0`. Without Paddle there is no primary damage, so
  there is no label to compute AUROC against.
- **Lane B** measures `Paddle repeat instability across exactly 3 frozen
  inference repeats`. Without Paddle the lane has no signal at all.

MinerU is a **research comparator**, explicitly not promoted, with a license
review outstanding (AGPL). It cannot be substituted for the primary.

## Why Paddle cannot run

`fastdeploy-gpu==2.3.0` is pinned in six places including the 2026-08-01
runtime manifest, and it has been withdrawn upstream. Measured, not assumed:

| Source | Result |
|---|---|
| PyPI project `fastdeploy-gpu` | 404 — no project |
| `paddle-whl.cdn.bcebos.com/stable/cu126/.../2.5.0-cp310-manylinux_2_28` | **200**, 1,765,435,821 bytes (control) |
| same prefix, `2.3.0` cp310 / cp311 / cp312 | 404 / 404 / 404 |
| FastDeploy GitHub release `v2.3.0` | 0 assets |
| Network volume `o9eslyovmd` (EU-RO-1), mounted and inspected | **empty**, 512 bytes, no entries |
| Network volume `j5wfgniyjx` (US-KS-2) | no capacity, not inspected |

The 2.5.0 control returning 200 on the identical prefix is what makes the
404s evidence rather than a bad URL. The image also applies a
sha256-verified source patch to a 2.3.0 file, so a version bump breaks the
patch gate as well as the runtime assertion.

## What is NOT blocked, and what it is worth

The MinerU image now clears every build gate. Its receipt:

```
build_passed                   = True
critical_vulnerability_count   = 0
model_revision                 = bff20d4ae2bf202df9f45284b4d43681555a97ed
model_artifact_sha256          = sha256:1611a889...   (2026-08-01 value, unchanged)
image_digest                   = ghcr.io/.../mineru-3.4.4-vlm-c1@sha256:42daa3f2...
runtime_qualification_required = True
paid_capacity_ready            = False
```

That is a real, checkable result: the specialist half of the confirmatory
runtime is reproducible at its frozen identity, from source, with zero
critical vulnerabilities and the frozen weights manifest intact.

It is **not** the confirmatory experiment, and running MinerU alone would
produce numbers with no lane to attach them to.

## The three options, and why none is taken silently

**Option 2 — bump to fastdeploy-gpu 2.5.0.** Voids the runtime assertion, the
sha256-checked source patch, and the claim that CONF-02 runs the same runtime
as the 2026-08-01 measurements. The experiment would then be measuring a
different system than the one its cohort and thresholds were frozen against.

**Option 3 — rebuild Paddle from source at the 2.3.0 tag.** Possible in
principle; FastDeploy's v2.3.0 tag exists even though its release carries no
wheels. A source build produces a *different artifact* than the wheel the
2026-08-01 manifest hashes, so the runtime identity still changes — just less
visibly, which is worse.

**Option 4 — re-freeze the confirmatory protocol against a currently
reproducible runtime.** Honest, expensive, and it forfeits comparability with
2026-08-01. It is also the only route that ends with a valid confirmatory
result rather than a caveated one.

All four change what may be claimed. Choosing among them is a research
decision with a cost, not an implementation detail, so it is recorded here
rather than made inside a Dockerfile.

## What this costs the paper

The manuscript already states, in section 13 limitations, that **no model
experiment ran** and that claims about generation quality, model accuracy or
GPU efficiency are unavailable. That statement remains true and is now
supported by a measured cause rather than an absence.

C-36 and C-37 — the two claims established in this session — are GPU-free and
unaffected. Neither depends on CONF-02 inference; the preservation experiment
reads CONF-02's *native* Lane A outputs, which were produced with
`gpu_seconds: 0.0` and are frozen.

## Frozen-instrument integrity

`verify_frozen_integrity.py` still reports `all_checks_passed: true`. Nothing
in this session's work modified the sealed instrument, and the Paddle loss is
an upstream availability fact, not a break in our chain.
