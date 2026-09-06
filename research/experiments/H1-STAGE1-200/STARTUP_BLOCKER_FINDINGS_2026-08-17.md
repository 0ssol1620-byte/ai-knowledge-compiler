# Stage-1 startup blocker — measured findings, 2026-08-17/18

> **ROOT CAUSE FOUND, 2026-08-18 09:56 KST, from the RunPod web console.**
> The container never starts because the NVIDIA container runtime refuses it:
>
> ```
> Status: Image is up to date for vllm/vllm-openai@sha256:e1668bce...
> start container: begin
> error starting container: ... error running prestart hook #0: exit status 1,
> stderr: Auto-detected mode as 'legacy'
> nvidia-container-cli: requirement error: unsatisfied condition: cuda>=12.9,
> please update your driver to a newer version, or use an earlier cuda container
> ```
>
> and retries every ~17 s forever, which is why a Pod sits at `RUNNING`,
> `uptime 0`, no ports, indefinitely.
>
> **THE STARTUP WALL IS MEASURED CLEARED, 2026-08-18 01:52 UTC.**
> `run-d9f9586dc089` / Pod `m77c4g8wcdz24q` landed and got past every barrier
> above, on the assembly's own GPU:
>
> | | |
> |---|---|
> | host | NVIDIA GeForce RTX 4090, CUDA 12.9 |
> | container start | no `nvidia-container-cli` refusal, no CUDA 804 |
> | startup elapsed | **134.5 s** (previously: retry every ~17 s, forever) |
> | qualifier | reached `starting_vllm` at 01:54:46 |
>
> v12's compat removal and v13's CUDA floor did the work they were built for.
> **v15 is what kept the result**: `runtime_present_per_api: false` while
> `control_ports_reachable: {8001: true, 8002: true}` — the API called this
> healthy Pod dead, and a readiness check that trusted it would have discarded
> the first successful landing of the campaign.
>
> The Pod was lost anyway, to the v16 slot-collision defect below: its control
> token was never written, only `control_token_sha256` survives in
> `startup-attempts.json`, and port 8001 answers 401 to everyone without it. It
> was deleted with absence verification once that was confirmed unrecoverable.
>
> One correction to the paragraph below: this run carried v13's equality filter
> and still landed. The filter made a landing *rare*, not impossible — 12.9
> capacity appears intermittently and this run caught the window. The case for
> v17 is that the campaign was discarding the largest pool on its own GPU, not
> that no capacity existed.

> **SECOND ROOT CAUSE, 2026-08-18, from the RunPod capacity API.**
> The fix for the first one was implemented with the wrong relation. The image
> requires `cuda>=12.9`; v13 asked RunPod for `allowedCudaVersions: ["12.9"]`,
> which is `==`. Measured the same day:
>
> | GPU | cuda 12.8 | cuda 12.9 | cuda 13.0 |
> |---|---|---|---|
> | RTX 4090 (the assembly's GPU) | Medium | **Out** | **High** |
> | RTX 3090 | Low | Low | Medium |
> | RTX 5090 | Low | **Out** | High |
>
> A CUDA 13.0 host carries a 580-series driver, satisfies `cuda>=12.9`, and runs
> a cu129 image under ordinary backward compatibility — no forward compat, so no
> 804. It was always a valid host. The equality filter excluded the only pool
> with stock, and every run from v13 onward died on `create pod: There are no
> instances currently available` — a message that reads like a RunPod shortage
> and was in fact the campaign refusing its own capacity. The 20-minute capacity
> poll v13 added was spent waiting on a set the request had defined as empty.
>
> Fixed in `v17`: `allowedCudaVersions` = every platform version at or above the
> assembly's `cuda_version`. The lower bound is unchanged, so a 12.8 host is
> still refused for the reason v13 identified.
>
> **A third defect surfaced while testing v17.** `v14` and `v16` both installed
> into the same `v13` slot, and `v14.main()` runs after `v16.main()`, so v14
> silently overwrote v16 — the control token was never persisted and the
> reattach path was dead code from the moment it was written. v16 now wraps the
> function v14 installs. `test_every_wrapper_below_v17_still_reaches_the_payload`
> builds one payload through the top of the chain and asserts every layer's mark
> is on it, so a future wrapper cannot silently displace an earlier one.

> **The pull was never the problem.** `Status: Image is up to date` — the image
> was already on that host and resolved in under a second.
>
> The image carries `NVIDIA_REQUIRE_CUDA=cuda>=12.9`. Our create payload asked
> for `allowedCudaVersions: ["12.8", "12.9"]`, so RunPod was free to place us on
> hosts that cannot start this image at all. **That is the defect, it is ours,
> and it is in one line of `build_payload`.**
>
> Everything below this banner was written before that log existed. The
> measurements are real; several of the inferences drawn from them are not, and
> are marked. In particular:
>
> * **"Image size" is not the discriminator.** The correlation was real and
>   spurious: `python:3.12-slim` declares no CUDA requirement, `pytorch cu124`
>   declares `cuda>=12.4` which nearly every host satisfies, and the vLLM image
>   declares `cuda>=12.9` which few do. Same host, different label, different
>   outcome — nothing to do with gigabytes.
> * **`v13` was not refuted.** It was declared refuted on 2026-08-18 because one
>   host reporting driver 570.211.01 also reported `CUDA Version: 12.9` and
>   still failed. That host *did* start the container and died later on CUDA 804.
>   The hosts that never start are the 12.8 ones. `v13` is the fix.
> * The lesson is the one this file keeps re-learning: an inference from the
>   *outside* of a black box is a hypothesis, however many measurements support
>   it. One line of the provider's own log replaced six hours of them.

Status: `CAUSE_EXTERNAL_INTERMITTENT` · `STAGE1_200_ACTUAL_OUTPUTS = PENDING`

Stage-1 still has not produced its 200 outputs. Pods are created successfully
and then, some of the time, never start their container: `desiredStatus RUNNING`,
`uptime 0`, no port mappings, indefinitely. The rate of this changes over hours.

This file replaces an earlier version of itself whose conclusion ("only images
already cached on the host start") was **wrong**. It was written during a window
in which nothing started, and it read that window as a property of the images.
The correction is recorded rather than quietly edited, because the mistake is
the useful part: a negative result taken while the provider is failing does not
exonerate or convict anything.

## Every paid attempt

Every probe used the campaign's request shape: SECURE, one RTX 4090,
`containerDiskInGb` 80, `volumeInGb` 0, `ports: ["8001/http","8002/http"]`,
`interruptible false`. "27 B env" means the `minimal` arm — no Stage-1 payload,
no driver, no qualifier, no bundle, a two-line `python3 -m http.server`
entrypoint.

### Started

| image | size | env | machine | time to ports |
|---|---|---|---|---|
| `python:3.12-slim` | 0.05 GB | 27 B | `sms1rfl9ulmx` | 37.7 s |
| `pytorch…cudnn9-runtime` | 3.93 GB | 27 B | `0vkszbho34pn` | 39.3 s |
| **`vllm-openai@e1668bce`** | **11.79 GB** | 27 B | `k4spy5dg16nr` | **147.8 s** |
| `vllm-openai@e1668bce` (v8, 14:20 KST) | 11.79 GB | 26.7 KB | — | 102 s |

### Did not start

| image | size | env | machine | waited |
|---|---|---|---|---|
| `vllm-openai@e1668bce` | 11.79 GB | 27 B | `jkwji5720pz9` | 1810 s |
| `vllm-openai@e1668bce` | 11.79 GB | 27 B | `jmyslst0n1ku` | 360 s |
| `vllm-openai@e1668bce` | 11.79 GB | 31.5 KB | `jkwji5720pz9` | 300 s |
| `vllm-openai@e1668bce` | 11.79 GB | full v10 payload | 20 distinct | 300–616 s each |
| `vllm-openai:latest` | 9.11 GB | 27 B | `p4xsym9hchja` | 300 s |
| `pytorch…cudnn9-devel` | 7.97 GB | 27 B | `0ee055bh61jo` | 300 s |
| `pytorch…cudnn9-runtime` | 3.93 GB | 27 B | `9drulpjpn6uf` | 900 s |
| `python:3.12-slim` | 0.05 GB | 31.5 KB | `vopz33dblr47` | 240 s |
| **`python:3.12-slim`** | **0.05 GB** | **27 B** | — | **240 s** |

The last row is the one that settles it. That is the identical image, env,
entrypoint and request that started in 37.7 s earlier the same evening. Nothing
on our side changed between them.

## The image is back under suspicion — one machine, two images

`v3cvf82z17t2`, community RTX 3090, inside a single window, same 27-byte
`python3 -m http.server` entrypoint:

| image | size | result |
|---|---|---|
| `vllm-openai@e1668bce` | 11.79 GB | no ports in 300.9 s |
| `pytorch…cudnn9-runtime` | 3.93 GB | **READY in 25.0 s** |

This is the controlled comparison every earlier probe lacked: the *same machine*
started one image and not the other, minutes apart. The host was not broken.

It then replicated on a second, independent machine. `sn1ppj6hc2rb`, community
RTX 3090:

| image | size | result |
|---|---|---|
| `vllm-openai@e1668bce` | 11.79 GB | no ports in 364.8 s |
| `pytorch…cudnn9-devel` | 7.97 GB | **READY in 150.2 s** |

150.2 s for 7.97 GB is a genuine cold pull at ≈53 MB/s. At that throughput
11.79 GB implies ≈222 s, comfortably inside the 360 s cutoff — so the 11.79 GB
image is not merely slower than the budget on these hosts. **It stalls.** Two
machines, drawn independently, each pulled a multi-gigabyte image to completion
and each never finished this one.

The counterweight is `a8yxq52eobbn`, which served both `python:3.12-slim`
(37.1 s) and the 11.79 GB vLLM image (37.5 s). 11.79 GB in 37.5 s is not a cold
pull at any plausible throughput; that host already had the image. So the
pattern the measurements support is:

- image already on the host → starts in tens of seconds, every time
- cold pull of 3.93 GB or 7.97 GB → completes, 25 s to 150 s
- cold pull of the 11.79 GB vLLM image → sometimes completes (147.8 s, once),
  usually stalls with no ports and no progress

This is close to the conclusion this file originally reached and then retracted
("only images already cached on the host start"). It is not the same claim: the
147.8 s cold start really happened, so the honest form is *cold pulls of this
image succeed sometimes and stall often*, not *never*.

**This retires the "image size is ruled out" line below.** That exclusion rested
on one measurement — 11.79 GB starting in 147.8 s — taken hours earlier. That
measurement was real, so the honest statement is not "the image is the cause"
but: *the 11.79 GB image starts sometimes and the 3.93 GB one starts far more
often, and a window that serves the small image can still refuse the large one.*

Whether the discriminator is size or this specific digest is not yet separated.

## CUDA 804: reproduced, and the fix measured on the same Pod

`probe-6ab99e4c8189`, community RTX 3090, driver **570.211.01**, one Pod, two
consecutive measurements around a single `rm -rf`:

```
== ldconfig libcuda BEFORE ==
    libcudadebugger.so.1 => /usr/local/cuda-12.9/compat/libcudadebugger.so.1
== torch BEFORE ==
    Error 804: forward compatibility was attempted on non supported HW
    available False
== torch AFTER ==
    available True
    count 1
    name NVIDIA GeForce RTX 3090
```

That is the whole claim, measured: with the image's forward-compat libcuda on
the loader path a GeForce card returns 804 and CUDA is unusable; with the
directory gone the same card on the same host initialises and reports itself.

Two consequences worth stating plainly.

**The compat removal is proven, not merely harmless.** The earlier entry in this
file recording it as unproven was correct when written and is now superseded by
this measurement, not by an argument.

**The CUDA version filter is not the discriminator, and `v13` is refuted.** This
host runs driver 570.211.01 and `nvidia-smi` reports `CUDA Version: 12.9`, so it
would have satisfied `allowedCudaVersions: ["12.9"]` and failed anyway. Narrowing
the filter does not prevent 804; it only shrinks the pool, and measurably so —
a 12.9-only campaign create returned `create pod: There are no instances
currently available`, an error the wider filter never produced.

`run_stage1_v29_r2_v13_cuda_pin.py` is kept, unused, with this note attached. It
is not deleted because its reasoning is a trap worth being able to re-read: the
inference "a cu129 image cannot run on a 12.8 host" is sound in isolation and
still produced the wrong configuration, because the host's advertised CUDA
version and the container's library search order are independent facts.

The working configuration is `v12`: the wide filter the campaign always had,
plus the compat removal.

## Superseded: the compat hypothesis was once NOT confirmed

`probe-ff93e6235cbc` ran the diagnostic entrypoint on a community RTX 3090
(driver 575.51.03, ready at 325.2 s) and measured the opposite of the prediction:

```
== ldconfig libcuda BEFORE ==
    libcuda.so.1 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libcuda.so.1
== torch BEFORE ==
available True
count 1
== torch AFTER ==
available True
count 1
name NVIDIA GeForce RTX 3090
capability (8, 6)
```

`/usr/local/cuda/compat` exists on this image and holds `libcuda.so.575.57.08`,
but `ldconfig` resolves `libcuda.so.1` to the *driver's* copy, not the compat
one. Compat is present and inert, CUDA initialises, and removing compat changes
nothing because there was nothing to fix.

So the removal is **measured harmless and unproven as a fix**. What produced
`Error 804` on the 4090 Pod in `run-337b29eba37a` is still unexplained: it may be
a different driver version, a different mount, or something else entirely. The
comparison that would settle it is the same diagnostic on a 4090, which the
capacity wall has not yet allowed.

### Published sources explain the negative result

The vLLM image sets, in its own Dockerfile,

```
ENV LD_LIBRARY_PATH="/usr/local/cuda/compat:${LD_LIBRARY_PATH}"
```

which puts the forward-compat libcuda *ahead* of the driver's. Forward
compatibility is a data-center-GPU feature, so on a GeForce card that ordering
produces exactly `Error 804`. vLLM's tracker carries the same failure on RTX
4090 across several image versions ([#5510](https://github.com/vllm-project/vllm/issues/5510),
[#2013](https://github.com/vllm-project/vllm/issues/2013)), and NVIDIA's own
container issue ([nvidia-docker#1294](https://github.com/NVIDIA/nvidia-docker/issues/1294))
shows the same `LD_LIBRARY_PATH` line as the mechanism.

Our 3090 Pod did not reproduce it because RunPod's runtime had replaced that
variable on that host:

```
== LD_LIBRARY_PATH ==
/usr/local/nvidia/lib64:/usr/local/cuda/lib64:/usr/local/cuda/lib64
```

No `compat` entry, so the compat libcuda was present but never loaded. **804 is
therefore host-dependent**: some hosts keep the image's ordering and fail, some
replace it and work. The diagnostic drew one of the latter.

This is why v12 deletes the directory rather than only editing a path — with the
files gone, a surviving `LD_LIBRARY_PATH` entry resolves to nothing and the
loader falls through to the driver's libcuda. That covers both host types.

**Literature is not measurement.** The mechanism is now well supported and the
prediction is unchanged, but no 4090 of ours has yet been measured with compat
present and then absent. The receipt must say which of the two it has.

`run_stage1_v29_r2_v12_cuda_compat.py` is launched on that basis: the change is
measured harmless (3090, `probe-ff93e6235cbc`) and mechanistically indicated,
and the alternative is v11 with an already-observed 804.

### The pull stall is a reported RunPod behaviour

Other users report the same shape on large images: pulls that stop partway,
"image pull pending" loops, repeated "loading container image from cache"
without completion, and HTTP 206 failures on multi-gigabyte images. Several
reports attribute it to specific regions' infrastructure.

Region is therefore a candidate lever — `POST /v1/pods` accepts `dataCenterIds`
with `dataCenterPriority` — but **it is not being used yet**, because the Pod
record RunPod returns carries `machineId` and no data-center field, so there is
no way to check whether our own failures cluster by region. Choosing a region
now would be guessing, and this file already records what guessing cost.

## What is therefore ruled out

- **Our payload.** 27 bytes of env and a two-line entrypoint fail too, and
  31,555 bytes succeed nowhere and fail nowhere consistently. The env is not
  even truncated: RunPod's own record of a stalled Pod lists all 21 keys and
  31,565 bytes intact (`probe-10fcd0f9ed3e/pod-diagnostics.json`).
- ~~**Image size.** 0.05 GB fails; 11.79 GB starts in 147.8 s.~~ **Retired** by
  the one-machine two-image comparison above. Both halves of the original
  sentence are still true measurements; they simply do not exclude size.
- **Image identity or registry.** `vllm-openai:latest` and the pinned digest both
  fail and the pinned digest also starts. The digest resolves on Docker Hub
  (manifest list HTTP 200, amd64 `sha256:e3443c4b…`).
- **Cold pull duration.** 11.79 GB in 147.8 s is ≈80 MB/s, a real cold pull, and
  it clears the 360 s cutoff by 2.4x.
- **A single bad host.** 30+ distinct machines.
- **The startup budget.** 1810 s changed nothing on a host that was not going to
  start; every host that did start, started inside 148 s.
- **Our create path, ports, credentials, accounts, GPU availability.** All shared
  with the runs that succeeded. Secure-cloud 4090 `stockStatus` is `High`.

## RunPod's own words

The failing create finally explained itself, once the transport stopped
discarding non-2xx bodies:

```
POST /v1/pods -> 500
{'error': 'create pod: This machine does not have the resources to deploy your
           pod. Please try a different machine', 'status': 500}
```

This is a **capacity allocation failure, not a server bug**, and it is almost
certainly the same fault as the silent case: a Pod assigned to a host that
cannot deploy it is created, reports RUNNING with uptime 0, and never starts.
RunPod surfaces it as a 500 when it notices before assignment and says nothing
when it notices after.

Earlier readings of that 500 as "an intermittent server error" and as
"a non-Docker-Hub registry needs containerRegistryAuthId" were both wrong. The
curl transport threw the body away, so the server's explanation never reached
the log; `RunPodHttpxTransport._detail` now quotes it.

### `stockStatus` does not mean deployable

The GraphQL catalog reported `NVIDIA GeForce RTX 4090` secure stock as **High**
at the same minute that six consecutive creates returned the resource 500, and
community stock as **Low** while six more returned it. Whatever `stockStatus`
counts, it is not capacity that a create can actually obtain. It is not a
pre-flight check, and no decision in this campaign should read it as one.

### The failure is not specific to SECURE

`cloudType: COMMUNITY` returns the identical 500 on the identical image. Twelve
creates across both credentials and both cloud types produced no Pod at all
during that window. The capacity fault is not a property of the secure pool.

**The shortfall is not anything we ask for.** The only resource in our control
is container disk, and halving it changes nothing:

| containerDiskInGb | machine | result |
|---|---|---|
| 80 | `jkwji5720pz9` | no ports in 300 s |
| 40 | `j1752a7p7k3t` | no ports in 300 s |

Nor is it the GPU model. An `NVIDIA A40` create (48 GB VRAM, $0.44, stock High)
returned the same resource 500.

## Hosts are handed out while broken

Machine IDs, recorded from this session on:

| machine | outcome |
|---|---|
| `sms1rfl9ulmx`, `0vkszbho34pn`, `k4spy5dg16nr` | started (37.7 s, 39.3 s, 147.8 s) |
| **`jkwji5720pz9`** | **failed 4+ times across the evening** |
| `9drulpjpn6uf`, `0ee055bh61jo`, `p4xsym9hchja`, `jmyslst0n1ku`, `vopz33dblr47`, `j1752a7p7k3t` | failed |

Later draws added `4verk58nni1n`, `a601chw8r0jh` and `qm5dho5b2x1p` to the failed
column, and `qm5dho5b2x1p` is the most informative entry in this table:

| time | credential | machine | result |
|---|---|---|---|
| 20:09:32Z | Runpod_B | `qm5dho5b2x1p` | no ports in 310.3 s |
| 20:09:36Z | Runpod_A | `qm5dho5b2x1p` | no ports in 312.3 s |

Two separate accounts were assigned **the same host four seconds apart**, and it
deployed neither Pod. That rules out per-account placement, per-account quota and
anything else account-shaped as the cause of a failed draw, and it shows the
scheduler does not spread concurrent requests: drawing on both credentials at
once is not always two independent draws. Where earlier paired runs disagreed
(A READY on `jz4w568ke0n9` while B failed on `j1752a7p7k3t`) they were on
different hosts; the pairing is only an independent sample when the machine IDs
differ, and the receipt is what says whether they did.

`jkwji5720pz9` ran this exact image successfully on 2026-08-15 and has deployed
nothing since roughly 20:00 KST on 2026-08-17, yet the scheduler keeps assigning
it to this account. This is the concrete form a support ticket should take: not
"pods sometimes fail" but "machine `jkwji5720pz9` accepted N pods at these times
and deployed none of them."

## What remains

An intermittent provider-side capacity failure, whose rate varies over hours. Around 14:20 KST it was low (v8 started in 102 s). By 19:00 it was
total (0 of 18 attempts). At 22:44 it was partial (11.79 GB started in 147.8 s
on one credential while the other failed at the same minute). By 00:30 it was
total again.

**The mechanism is not observed and cannot be, from the API.** RunPod's REST API
exposes no log route for a Pod: `/v1/pods/{id}/logs`, `/system-logs` and
`/systemLogs` all return HTTP 400 "that path … does not exist in the
specification". A stalled Pod reports `machine: {}` and `publicIp: ""`.

Separately and less often, `POST /v1/pods` returns HTTP 500 and a retry seconds
later succeeds with the same payload. Two campaign launches died on one such
500 before v11 learned to reconcile by unique name and try again.

## What must not be concluded

- Not that the v29 assembly, READY, the v4 qualifier, the v4 driver or the
  hard-200 bundle are wrong. **None of them has been reached.** READY still
  verifies: `sha256(assembly_qualification_http_v4.py) == bootstrap_sha256`.
- Not that Stage-1 works. It has never run. No scoring, no A9/A12 paired GPU
  result and no patent effect sentence rests on anything here.
- Not that the v4 driver is exonerated either. It has never started, so it has
  never been tested. The `payload` and `v10` arms exist to separate it from the
  env, and both rounds so far were run in windows where the control also failed,
  which makes them uninformative rather than negative.

## Cost

≈$3.19 across the session: Runpod_A 7.0158 → 5.9172, Runpod_B 52.8906 → 50.7995.
Every Pod was deleted and its absence verified. One probe Pod leaked for ~40 s at
$0.00 when the host exhausted its commit charge and `CreateProcess` failed for
the poll and the cleanup alike; the cleanup path now runs on httpx and cannot
share that failure mode.

## How to resume

1. Run one `minimal` probe as a **provider health check** before spending
   anything else. If it does not start, the window is bad — stop, and try later.
   `--arm minimal --timeout-seconds 300`, ≈$0.06.
2. Only when that starts, launch `run_stage1_v29_r2_v11_fast_fail_hosts.py`.
3. If the campaign fails while the health check passes, run `payload` and `v10`
   arms **concurrently on the two credentials** so a changing provider rate
   cannot be mistaken for a payload effect.
