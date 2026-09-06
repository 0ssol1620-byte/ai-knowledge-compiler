# A12 runtime-readiness audit — 2026-08-19

This audit reconciles the frozen A12 v2 preregistration with **live repository state**. It does not change the A12 endpoint or authorize a GPU run.

## Binding stop-before-spend gates

`preregistration-v2.json` requires stopping before spend if any of the following is true:

1. formal immutable runtime is not READY/qualified;
2. source-only artifact identity cannot be reconstructed exactly;
3. the same-family ablation recipe is not frozen before scoring;
4. the independent outcome/evaluator contract is unavailable;
5. predicted spend exceeds the nominal cap without a smaller informative design.

The audit is fail-closed: all pre-spend gates that can be established locally must pass before provider provisioning is attempted.

## Machine-verifiable interpretation

For the two independent-family candidates, formal runtime readiness requires both the candidate registry and the RunPod pool registry to expose an immutable usable runtime identity. A pool with `enabled: false`, `identity_state: pending_exact_image_digest`, or `image_digest: null` is **not READY**.

The source-only gate passes only if the frozen 48-case receipt states all input hashes verified, case count 48, and no ground truth in or mounted with the bundle.

An exact same-family ablation recipe is not satisfied by prose saying “MinerU same-family recipe frozen before scoring.” It must already identify, before outcomes, at least the concrete candidate/variant, immutable model/code/runtime identity, inference settings, and action/output identity needed to distinguish an exact reusable arm. No such machine-readable frozen recipe artifact is present under `H1-A12-01` or `H1-A9-A12-SHARED-01` at this audit point.

## Consequence

Because the immutable-runtime gate is false (and the exact same-family recipe gate is independently false), provider provisioning and GPU spend are prohibited by the existing preregistration. A historical cost estimate below USD 3 cannot override those earlier stop gates.

This state is **not a licence blocker** and **not a source-data blocker**. It is `BLOCKED_RUNTIME_AND_RECIPE`; production promotion remains a separate question and stays false in the candidate registry.
