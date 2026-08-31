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

---

# Provider-contract defects measured on 2026-08-31

The three issues below were each observed directly against the live RunPod
API while attempting the rq-01 image build, not inferred from documentation.
All three cost real money before they were understood.

## INC-RUNPOD-02 — a Pod can bill indefinitely without its container ever starting

**Status:** confirmed against a live Pod; mitigation exists in code but was
not applied to the Pod that failed.

Pod `tcmo7xom13m2ch`
(`tavonel-r-http-qual-strong-v9-phase-new-pod-after-host-gpu-unavailable`)
was rented on 2026-08-30T13:43:24Z and was still `desiredStatus: RUNNING`
roughly 23.6 hours later, having accrued approximately **$17.5** at
$0.74/hr. Its GraphQL `runtime` reported `uptimeInSeconds: 0` — the
container had never started even once. The provider log for that Pod:

```
start container for runpod/pytorch@sha256:263d4144...: begin
error starting container: ... error running prestart hook #0: exit status 1,
stderr: Auto-detected mode as 'legacy'
nvidia-container-cli: requirement error: unsatisfied condition: cuda>=12.8,
please update your driver to a newer version, or use an earlier cuda container
```

The Pod was placed on a host whose NVIDIA driver predates CUDA 12.8, so
`runc` failed in its prestart hook and crash-looped. **RunPod bills the
rented GPU regardless.** `desiredStatus: RUNNING` is a statement of intent,
not evidence that anything is running; only `runtime.uptimeInSeconds > 0`
is that evidence.

Two consequences for this project:

1. **`allowedCudaVersions` is a cost-safety control, not a nicety.**
   `QualificationPodSpec.allowed_cuda_versions` already defaults to
   `("12.8", "12.9")` and is sent as `allowedCudaVersions`
   (`infra/runpod/v6/qualification_pod.py:52,125`), which constrains
   placement to hosts that can actually start these images. The failed Pod
   predates or bypassed that path. Every future paid create must go through
   a spec that sets it — the two rq-01 images both derive from
   `runpod/pytorch@sha256:263d4144...`, the exact image that failed here, so
   they are subject to the same failure on an unconstrained host.
2. **Readiness polling must check `uptimeInSeconds`, not just status.** A
   watchdog that waits for `RUNNING` will wait forever on a Pod like this
   while it bills.

## INC-RUNPOD-03 — Pod create is not atomic: HTTP 500 can still create the Pod

**Status:** confirmed by direct measurement; mitigated in
`infra/runpod/v6/run_builder_session.py`.

`POST rest.runpod.io/v1/pods` returned **HTTP 500** while nonetheless
creating Pod `net5nm21hawfox`; the 500 response body was a complete, valid
Pod object. An identical request issued minutes later returned **201**. The
failure is intermittent and the status code carries no information about
whether paid capacity now exists.

`RunPodBuilderClient.create` only accepts `{201}` and raises otherwise
(`infra/runpod/v6/builder_pod.py:164-165`), so on a 500 it discards the
response — including the `id` of the Pod that was just created. Its own
comment anticipates this ("The write outcome may be ambiguous ... require
inventory reconciliation") but nothing in the class performs that
reconciliation, so the caller is left billing for a Pod it cannot name.

Mitigation added in `run_builder_session.py`: `find_pods_by_name` lists the
Pod inventory and matches on the requested name, and
`reconcile_orphans_by_name` deletes each match and proves its absence with a
`GET` 404. `open_builder_session` runs that reconciliation whenever `create`
raises. This removes capacity and never re-creates it, so the "never
auto-retry a paid write" rule is preserved.

Verified by drill on 2026-08-31: a Pod was deliberately created outside the
client (`znv463lkoax5r0`), found by name, deleted, and confirmed absent
(`GET_404_NOT_FOUND`, `absence_proven: true`), leaving an empty inventory.

## INC-RUNPOD-04 — the builder Pod cannot run buildah: seccomp blocks unshare

**Status:** confirmed; the `_BOOTSTRAP` builder design in
`infra/runpod/v6/builder_pod.py` does not work as written on RunPod.

`builder_pod._BOOTSTRAP` installs `buildah` and expects to build images
inside the Pod. On a live builder Pod (`18i7owilyecsew`, RTX 4090, buildah
1.33.7 present and on PATH) every buildah invocation — including a bare
`buildah images` — failed with:

```
Error during unshare(CLONE_NEWUSER): Operation not permitted
```

The Pod runs as uid 0 but under a seccomp filter (`Seccomp: 2`) with
`CapEff: 00000000a80425fb`, which lacks `CAP_SYS_ADMIN`. `unshare --user
true` fails directly, so this is the container's syscall policy, not a
buildah configuration problem. `/proc/sys/user/max_user_namespaces` is
permissive (2147483647) and `unprivileged_userns_clone` is 1 — neither is
the constraint.

Ruled out by measurement, in this order:

| Attempt | Result |
|---|---|
| `BUILDAH_ISOLATION=chroot` + `STORAGE_DRIVER=vfs` | same unshare failure |
| `_CONTAINERS_USERNS_CONFIGURED=done` | same unshare failure |
| explicit `/etc/containers/storage.conf` (vfs) + `containers.conf` + root entries in `/etc/subuid`/`/etc/subgid` | same unshare failure |
| kaniko executor binary | not distributed as a standalone binary; the release asset download yielded 9 bytes |
| docker / podman | neither installed; `docker.io` is not in the Pod's apt sources and no `/var/run/docker.sock` exists |

Consequence: **do not budget GPU time for a buildah-on-RunPod build until
this is solved.** The image build path that is known to work is
`.github/workflows/baked-confirmatory-images.yml`, which builds on a GitHub
runner and additionally produces the SBOM, vulnerability scan and
`folynta.baked-image-build-integrity.v1` receipt that
`RUNTIME_QUALIFICATION.md` requires — none of which the buildah path was
going to produce on its own.

A future round that wants an in-provider builder should either request a
privileged/CAP_SYS_ADMIN-capable Pod (if RunPod offers one), or use a
docker-in-docker base image rather than `ubuntu` plus an apt-installed
buildah. Neither has been tested.

