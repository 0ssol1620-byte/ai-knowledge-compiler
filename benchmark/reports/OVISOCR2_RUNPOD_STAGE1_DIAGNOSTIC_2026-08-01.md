# OvisOCR2 RunPod Stage 1 Diagnostic

Date: 2026-08-01 KST
State: blocked before inference; no quality score exists

## Frozen candidate

| Item | Value |
| --- | --- |
| Model | `ATH-MaaS/OvisOCR2` |
| Model revision | `65c619d374b55d4152e85150fc1b003700bc1f0c` |
| Artifact bytes | 1,731,025,221 |
| Artifact files | 46 |
| Artifact manifest | `sha256:847f485bc71908a70075fe6b0d76609f52bc7f1e730c03670c764da56da08c9a` |
| Runtime | `vllm==0.22.1`, `torch==2.11.0`, Python 3.11.10 |
| GPU | NVIDIA GeForce RTX 4090, 24,564 MiB |
| Host driver capability | CUDA 12.8 / driver 570.158.01 |

## Diagnostic sequence

1. The first Stage 1 initialization used vLLM's library default on Linux and
   failed because CUDA was reinitialized in a forked subprocess.
2. The runner was corrected to set the documented
   `VLLM_WORKER_MULTIPROC_METHOD=spawn` before importing vLLM.
3. The engine then reached CUDA initialization and stopped because the official
   vLLM 0.22.1 PyPI environment selected Torch 2.11 / CUDA 13, while the pod
   host driver exposes CUDA 12.8 compatibility.

No page entered generation in either attempt. Completed inference cases are
therefore zero, and all accuracy, latency-per-page, stability, and cost-per-page
metrics are unavailable. The vendor's model-card benchmark is not copied into
Structara's measured result table.

## Correct next admission

The candidate can re-enter Stage 1 only on a host driver compatible with the
official CUDA 13 runtime or through a separately frozen CUDA 12.8 source build
of vLLM 0.22.1. Any alternate runtime must receive a new candidate identity and
must repeat artifact, Stage 1, and three-repeat gates.

## Subsequent recovery under a new identity

The original failed identity remains blocked and unscored. A separate
`ovisocr2-0.9b-vllm-0.22.1-cu129` candidate was later frozen with the official
vLLM 0.22.1 CUDA 12.9 release wheel and Torch 2.11.0+cu129. It passed a fresh
18/18 Stage 1 and then completed 54/54 formal cases. Its measured results live
in
`OVISOCR2_0_9B_VLLM_CU129_OMNIDOCBENCH_DEMO_EVALUATION_2026-08-01.md`;
they do not retroactively turn this failed runtime into a successful run.

## Evidence

- Artifact manifest:
  `benchmark/reports/ovisocr2-artifact-manifest-2026-08-01.json`
- Ground-truth-isolated runner:
  `benchmark/runpod_eval/ovisocr2_stage2.py`
- vLLM multiprocessing contract:
  <https://docs.vllm.ai/en/stable/design/multiprocessing/>
- vLLM 0.22.1 CUDA build variable:
  <https://docs.vllm.ai/en/v0.22.1/configuration/env_vars/>
- OvisOCR2 model card: <https://huggingface.co/ATH-MaaS/OvisOCR2>
