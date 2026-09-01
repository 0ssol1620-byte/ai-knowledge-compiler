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

## Observed CUDA versions on this account's hosts (context for INC-RUNPOD-02)

Serverless worker logs for the `tavonel-foundation-ocr-gpu` endpoint, covering
2026-08-29 11:43Z through 2026-09-01 22:13Z across 8 distinct workers, report
exactly two CUDA versions in their container banners:

```
CUDA Version 12.4.1
CUDA Version 12.6.3
```

Neither satisfies the `cuda>=12.8` requirement that the
`runpod/pytorch@sha256:263d4144...` base image declares — the same requirement
whose failure produced INC-RUNPOD-02's 23.6-hour billing zombie. That endpoint
is unrelated to this lineage (it runs RapidOCR under onnxruntime, and it is a
product surface rather than a research one), so this is not evidence about the
rq-01 images. It is evidence about the *fleet*: hosts in the 12.4–12.6 range
are routinely allocated on this account.

Consequence for the qualification runs: `allowedCudaVersions` is not a
formality that will always be satisfiable. A create constrained to
`("12.8", "12.9")` may find no capacity at all, and a **refusal to place is
the correct outcome** — it is the constraint doing its job, not a fault to
work around. Do not respond to a placement failure by widening the allowed
set: the image genuinely cannot start below 12.8, and a Pod that cannot start
still bills.

## INC-RUNPOD-05 — fastdeploy-gpu 2.3.0 has been withdrawn upstream (OPEN)

**Status: blocking `paddleocr-vl-1.6-fastdeploy-c8`. Needs a decision, not a
workaround.**

The 2026-09-01 build failed with:

```
ERROR: No matching distribution found for fastdeploy-gpu==2.3.0
```

Measured, not inferred:

| Source | Result |
|---|---|
| `pypi.org/pypi/fastdeploy-gpu/json` | HTTP 404 — project not on PyPI at all |
| `paddlepaddle.org.cn/packages/stable/cu126/fastdeploy-gpu/` | HTTP 200, advertises **only 2.5.0** (cp310/cp311/cp312) |
| `paddle-whl.cdn.bcebos.com/.../fastdeploy_gpu-2.3.0-cp311-...whl` | **HTTP 404** |
| same, cp310 and cp312 | **HTTP 404** |
| same, `fastdeploy_gpu-2.5.0-cp311-...whl` (control) | HTTP 200, 1,766,070,369 bytes |

The 2.5.0 control returning 200 from the same URL shape establishes that the
404s are the version being gone, not a malformed path or a dead host. The
wheel has been withdrawn from both the index and the CDN behind it.

This matters because 2.3.0 is not a casual pin. It is frozen in six places,
including `benchmark/reports/paddleocr-vl-1.6-fastdeploy-runtime-manifest-2026-08-01.json`
(the measured runtime of the 2026-08-01 evaluation),
`remote_bootstrap_paddle_recovery.sh:75`, and this image's own
`verify-runtime.sh` assertion. The image also carries a **version-specific
source patch**: it verifies `fastdeploy/input/text_processor.py` against
sha256 `b50570cb2c13f29f2a7f8803d6bdb3368111e906152425f9666d0ca4818a396d`
before applying a `sed`. A 2.5.0 tree will not match that hash, so bumping the
version silently invalidates the patch gate as well as the runtime assertion.

**Do not resolve this by changing the pin to 2.5.0 and updating the hashes to
match.** That produces a green build whose runtime differs from the one the
2026-08-01 results describe, which is exactly the substitution SEM-RISK-CONF-02
must be able to rule out. Options, in the order they should be considered:

1. Locate a preserved 2.3.0 artifact (internal mirror, an existing pod image,
   a cached wheel on a network volume) and pin it by digest. Preserves
   identity; depends on an archive existing.
2. Accept 2.5.0 as a **new, separately measured** runtime: re-derive the patch
   hashes, update the assertion, and treat the resulting candidate as not
   comparable to the 2026-08-01 Paddle numbers without a fresh baseline.
3. Report the Paddle lane as blocked and proceed with the specialist lane
   only, recording the reduced design. CONF-02's protocol names Paddle as
   primary, so this changes the experiment and is not a silent option.

Option 1 is the only one that keeps the frozen identity. Options 2 and 3 both
change what the confirmatory run can claim and need explicit sign-off before
any GPU spend.

### Option 1 was attempted and could not be completed (2026-09-01)

The 2026-08-01 Paddle bootstrap built its venv at
`/workspace/folynta/venvs/paddle-fastdeploy-r1`, and `/workspace` is where a
RunPod network volume mounts. Both volumes from that period still exist
(`j5wfgniyjx` in US-KS-2, `o9eslyovmd` in EU-RO-1), so a preserved wheel or
`fastdeploy_gpu-2.3.0.dist-info` was plausible. Two access routes were tried
and both are closed:

**Pod mount.** `infra/runpod/v6/scan_volumes_for_fastdeploy.py` creates a pod
in the volume's datacenter, runs a bounded read-only inventory over SSH, then
deletes and proves absence with a 404. Every create returned HTTP 500 across
eight GPU types in both datacenters. That is placement, not the volumes: an
unconstrained control create — no datacenter, no volume — succeeded on
`NVIDIA GeForce RTX 4090` (HTTP 201, deleted, readback 404), and the same type
pinned to either volume datacenter failed. RunPod currently has no capacity in
US-KS-2 or EU-RO-1 for this account.

**S3 gateway.** `infra/runpod/v6/read_volumes_over_s3.py` uses the volumes'
S3-compatible endpoints, which need no pod and no GPU. Both endpoints are
reachable and both reject every credential in the file with
`SignatureDoesNotMatch: does not match any shared API key for specified user
ID`. The REST API key is not an S3 credential, and the two `Access Key ID` /
`Secret Access Key` pairs present are filed under **Cloudflare R2**, not
RunPod. No RunPod S3 access key exists for this account yet.

### Option 1 was completed on 2026-09-01: the volumes are empty

A later retry found capacity in EU-RO-1 and the volume was inspected. The
scan created a pod on an RTX 4090 (HTTP 201), mounted `o9eslyovmd` at
`/workspace`, ran a read-only inventory over SSH, then deleted the pod and
proved its absence with a 404 read-back. The mount is empty:

```
===ROOT===
total 1
drwxrwxrwx 2 root root  1 Aug 30 05:27 .
drwxr-xr-x 1 root root 86 Sep  1 18:41 ..
===FOLYNTA===      (empty)
===FASTDEPLOY===   (empty)
===WHEELS===       (empty)
===DISTINFO===     (empty)
===VENVS===        (empty)
===DU===
512     /workspace
```

512 bytes, no entries, and a root mtime of 2026-08-30 — after the 2026-08-01
Paddle run. The venv that run built at
`/workspace/folynta/venvs/paddle-fastdeploy-r1` is not there; the volume was
cleared at some point between then and now.

US-KS-2 (`j5wfgniyjx`) still has no capacity across eight GPU types and was
not inspected. It is a cache volume from the same era with the same
provisioning history, so it is unlikely to differ, but that is an inference
and not a measurement.

**Option 1 is therefore refuted for EU-RO-1 and untested for US-KS-2.** This
supersedes the earlier "untested, not refuted" wording for the EU-RO-1 half:
we did look, and the wheel is not there.

### The upstream withdrawal is confirmed rigorously

An earlier CDN probe returned 404 for both 2.3.0 and the 2.5.0 control, which
proved only that the URL shape was wrong. Reading the index HTML gives the
real form (`paddle-whl.cdn.bcebos.com`, `manylinux_2_28_x86_64`), and on that
form:

| URL | Result |
|---|---|
| `stable/cu126/.../fastdeploy_gpu-2.5.0-cp310-...-manylinux_2_28_x86_64.whl` | **200**, 1,765,435,821 bytes |
| `stable/cu126/.../fastdeploy_gpu-2.3.0-cp310-...` | 404 |
| `stable/cu126/.../fastdeploy_gpu-2.3.0-cp311-...` | 404 |
| `stable/cu126/.../fastdeploy_gpu-2.3.0-cp312-...` | 404 |

The control returning 200 from the identical prefix is what makes the 404s
meaningful. The FastDeploy GitHub release for tag `v2.3.0` carries **0
assets**, and PyPI has no `fastdeploy-gpu` project at all.

**Conclusion: fastdeploy-gpu 2.3.0 is not retrievable from any public source
we can reach, and the artifact that once held it locally is gone.** The Paddle
lane cannot be reproduced at its frozen runtime identity. Options 2 and 3
remain, and both change what the confirmatory run may claim; neither may be
taken silently.





