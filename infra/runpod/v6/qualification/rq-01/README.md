# rq-01 — Runtime Qualification Lineage

This directory holds the lineage-level evidence, fixtures, and documentation
for baking and qualifying the two runtime images (`paddleocr-vl-1.6-fastdeploy-c8`,
`mineru-3.4.4-vlm-c1`) that `research/experiments/SEM-RISK-CONF-02` needs before
GPU inference can run.

## Why this lives here, not under `research/experiments/`

1. **`research/experiments/` is reserved for protocol-bearing scientific
   experiments.** Every entry there (`EXP-0101`, `SEM-RISK-CONF-01/02`,
   `H3-B-CURRENT-CORE-PUBLIC-REVISION-01/02/03`) carries a frozen protocol, a
   claim boundary, and an acceptance gate, and follows a single stable name
   with a trailing `-NN` revision suffix — never a compound name. This work
   has no protocol, no claim, and no acceptance gate of its own; it is
   infrastructure that a scientific experiment consumes, not an experiment
   itself.
2. **Naming collision risk.** Placing this under `research/experiments/` next
   to `SEM-RISK-CONF-02` would put an infrastructure artifact directly beside
   the frozen scientific experiments it feeds, and risks exactly the kind of
   ID confusion this project has been warned against — this lineage must never
   be mistaken for, or bleed into, the frozen `experiment_id: "SEM-RISK-CONF-01"`
   protocol.
3. **There is already a placement precedent for this kind of artifact.**
   `infra/runpod/v6/images/<candidate-id>/` is the existing convention for
   per-candidate image build definitions (precedent: `infra/runpod/v6/images/ovisocr2-m1/`).
   `infra/runpod/v6/qualification/rq-01/` extends that same tree with a
   lineage-level record (`rq` = runtime qualification, `-01` following the
   repo's trailing-revision convention) that ties candidate ids, weights/source
   revisions, runner pins, and build state together across both new images —
   without touching the scientific experiment directories or the candidate
   registry.

## What remains before paid execution can be triggered

- [ ] Baked image built and pushed to GHCR for `paddleocr-vl-1.6-fastdeploy-c8`
      and `mineru-3.4.4-vlm-c1` — **blocked pending approval** (GHCR image push
      is out of scope for this round).
- [ ] Qualification smoke run executed on real GPU hardware — **blocked
      pending approval** (RunPod pod creation is out of scope for this round).
- [ ] Qualification receipt produced and independently verified.

`paid_capacity_ready` and `ghcr_push_performed` in `lineage.json` are both
`false` and must stay `false` until the corresponding checklist item above is
completed and approved.

## Scope boundary

No file under `research/experiments/SEM-RISK-CONF-02/` is created, modified,
or read-written by this lineage. No file under `benchmark/v6/candidate-registry.yaml`
is modified — it is read-only and re-verified by hash (`candidate_registry_sha256`
in `lineage.json` was independently recomputed with `hashlib.sha256` against
the live file and confirmed to match the value frozen in
`research/experiments/SEM-RISK-CONF-02/protocol.json`'s `source_hashes` map).
