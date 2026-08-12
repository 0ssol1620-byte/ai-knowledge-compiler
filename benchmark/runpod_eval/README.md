# RunPod model evaluation programs

These programs run inference only. They never mount benchmark ground truth and
therefore cannot score or promote a model by themselves. Copy the immutable raw
artifacts back to the evaluator environment, freeze their hashes, and then run
the official and Structara critical evaluators.

Every model runner defaults to one full pass. Public-core execution accepts
only the adaptive shapes: initial full index 1, expansion full indexes 2-3, or
finalist full indexes 1-3. A stratified audit must use the same frozen audit
manifest for indexes 1-3. A failed page stays in the evidence as a failure.

`public_core_audit.py` derives a source-only deterministic audit selection from
each full input manifest. The current frozen selection contains 128 inputs per
suite and covers all observed non-answer strata. The selection manifest is
content-bound to the full input manifest and never exposes expected content.

`mineru_stage2.py` invokes the immutable MinerU CLI once per repeat, retains
the vendor output and logs, and creates evaluator-ready Markdown directories.
Its input directory must contain images only; the program records that the
ground-truth annotation was not mounted in the inference environment.

`ovisocr2_stage2.py` reproduces the official OvisOCR2 vLLM 0.22.1 inference
contract with deterministic decoding, model-card pixel bounds, truncated-tail
cleanup, the default visual-region tag filter, and vLLM's documented `spawn`
multiprocessing mode for a library entrypoint. It uses the same ground-truth
isolation boundary as the other inference runners.

`deepseek_ocr2_stage2.py` pins the official Transformers path, Markdown prompt,
dynamic-resolution sizes, BF16 precision, FlashAttention implementation, and
per-page vendor `infer` call. Returned or vendor-persisted Markdown is retained;
an absent output remains a failed case.

`artifact_manifest.py` hashes every byte of the resolved model directory and
produces the immutable identity digest passed into either inference runner.

The Paddle dynamic backend is retained as a diagnostic lane. Production-speed
evaluation uses PaddleX's documented VLM-service split, with the layout stage
in the client and the VLM recognition stage in a separately versioned
FastDeploy or vLLM service. `artifact-manifest-sha256` binds the run to the
downloaded layout and VLM bytes instead of treating a mutable provider model
name as an immutable identity.

`paddleocr_vl_stage2.py` records one cold initialization and executes only the
explicit adaptive repeat indexes over the bound full or audit cohort.

`summarize_omnidoc_evidence.py` runs only after inference outputs enter the
separate evaluator environment. It refuses inconsistent repeats and failed
inference, reports edit distances and TEDS with their exact aggregation names,
derives page-level exact-repeat stability from the frozen hashes, and marks CDM
unavailable when its external rendering toolchain fails. An evaluator failure
is never converted into a model score of zero or an overall score.

`publish_omnidoc_demo_snapshot.py` is the only publication path for the public
demo snapshot. It validates candidate identity, evaluator revision,
ground-truth isolation, three-repeat promotion, and stability before deriving
browser metrics. It then hashes the evidence bundle and validates the final
snapshot against the browser contract schema.

## Full public-core recovery workflow

The 5,132-case public-core campaign is intentionally split into operational
completion and quality recovery. `remote_stall_watchdog.sh` detects a suite
that has produced no new artifact for a bounded interval, records the event,
and terminates only the stalled MinerU service so the worker can advance. The
failed remainder remains explicit in `run-summary.json`.

`collect_public_core_worker.py` downloads only run summaries, Markdown, model
JSON, logs, and stall evidence. Its archive allowlist rejects source documents,
credentials, path traversal, links, and unexpected files. It verifies the
remote and local SHA-256 before extracting.

After all primary workers finish, use `plan_operational_retries.py` to stage
every failed case on the different worker frozen in the shard plan. Once those
retry runs return, `apply_operational_retries.py` creates a derived composite
view without mutating primary evidence. The composite summaries retain both
primary and retry summary hashes. `public_core_merge.py` can then produce the
complete official evaluator inputs.

Run the three frozen official evaluators with
`evaluate_parsebench_official.py`, `evaluate_omnidoc_repeats.py`, and
`evaluate_olmocr_official.py`. OmniDocBench evaluation captures the official
per-page edit-distance and per-table TEDS artifacts, and emits exact non-perfect
elements rather than inferring failures from aggregate scores.

`build_public_failure_records.py` binds every official failure to the exact
prediction, evaluator revision, authority evidence, minimum recovery scope,
and ordered alternate model route. Text omission routes to DeepSeek-OCR-2;
formula, table, numeric, layout, and reading-order failures route to
PaddleOCR-VL. Hallucination-only rules remain non-recoverable unless independent
authority permits replacement. A recovered candidate is accepted only after
the same official rule improves and no previously passing rule regresses.

The independent worker-health evidence command is:

```powershell
.\.venv\Scripts\python.exe -m tools.release.run_folynta_worker_fault_campaign `
  --output benchmark/reports/generated/folynta-worker-fault-campaign-2026-08-04.json
```

It exercises the production `WorkerHealthRegistry` against three healthy
controls, 10% last-row deletion, 5% digit mutation, wrong revision, OOM,
timeout, delayed straggler, stale cache, and corrupt callback scenarios.
