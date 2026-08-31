# Known issues — rq-01

## FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256: object-hash vs. file-hash mismatch (Ovis lineage, pre-existing)

**Status:** confirmed, pre-existing, not introduced by this round, out of
scope to fix here.

**Where:**

- `infra/runpod/v6/pod_client.py` (around lines 179–182, in
  `PodCreateSpec.provider_payload`): when `baked_runtime_receipt_sha256` is
  set, it is written into the pod's environment as
  `FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256`. Per `PodCreateSpec`'s own
  validation (`self.baked_runtime_receipt_sha256 !=
  self.baked_runtime_qualification.receipt_sha256` is rejected), this value
  is the canonical SHA-256 of the *entire qualification-receipt object* —
  the full `folynta.baked-runtime-qualification.v1` mapping described in
  `infra/runpod/v6/RUNTIME_QUALIFICATION.md` — not the hash of any single
  file baked into the image.
- `benchmark/runpod_eval/bootstrap_ovisocr2_m1.sh` (around lines 37–41):

  ```bash
  if [[ -n "${FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256:-}" ]]; then
    printf '%s  %s\n' \
      "${FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256#sha256:}" \
      "$BAKED_RECEIPT" | sha256sum --check --strict
  fi
  ```

  This treats `FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256` as the expected hash of
  the *file* `$BAKED_RECEIPT` (`/opt/folynta/baked-runtime-receipt.txt`) and
  runs `sha256sum --check` against it.

**The defect:** a category mismatch. The environment variable carries an
object hash (hash of the whole qualification receipt, computed by the
control plane from data that is not, and cannot be, byte-identical to any
single file inside the image). The bootstrap script instead validates it as
a file hash (hash of one specific file's on-disk bytes). These two
quantities have no reason to be equal, so `sha256sum --check` here would
either fail every legitimate run or (if the check is more permissive than it
appears) pass without actually verifying what it claims to verify.

**Why it has never triggered:** every Ovis image spec in this repository is
still `qualification_state: BUILD_REQUIRED` (see
`infra/runpod/v6/RUNTIME_QUALIFICATION.md`, "The current Ovis specs
correctly remain `BUILD_REQUIRED`"). `PodCreateSpec` refuses to create paid
capacity for a `BUILD_REQUIRED` spec, so `baked_runtime_receipt_sha256` has
never been populated for a real pod create call, `provider_payload` has
never set `FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256` to a real value on an
actual pod, and this branch of `bootstrap_ovisocr2_m1.sh` has never executed
against real data. It is a latent defect in code that has never run for
real, not a regression discovered via a failing job.

## This round's two new images do not replicate the pattern

The two new images built for rq-01 —
`infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/` and
`infra/runpod/v6/images/mineru-3.4.4-vlm-c1/` — deliberately avoid this bug
in their `verify-runtime.sh` scripts:

- Both scripts read `FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256` (when set) and log
  it for traceability only. Neither script ever runs a hash comparison
  against it.
- The baked-runtime-file identity check in both scripts instead compares the
  on-disk receipt file's hash against a **separate, build-time-baked
  constant** (`/opt/folynta/baked-runtime-receipt.sha256` in both images) —
  a file-hash-to-file-hash comparison, which is the category-correct check.
- Both scripts carry inline comments pointing back at this file and at
  `pod_client.py` explaining why the pattern is deliberately different from
  `bootstrap_ovisocr2_m1.sh`.

## Recommendation

Fix this in a separate, future round scoped specifically to the Ovis
lineage (`infra/runpod/v6/images/ovisocr2-m1/` and
`benchmark/runpod_eval/bootstrap_ovisocr2_m1.sh`). That round should decide
whether the bootstrap script should stop validating
`FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256` as a file hash (matching the pattern
now used by the paddleocr/mineru images — log-only, with a separate
build-time-baked file-hash constant for the actual identity check) or
whether `pod_client.py` should instead pass a *file*-hash environment
variable under a differently named key for that purpose. Either fix touches
`pod_client.py` and/or `bootstrap_ovisocr2_m1.sh`, both of which are
out of scope for this round.
