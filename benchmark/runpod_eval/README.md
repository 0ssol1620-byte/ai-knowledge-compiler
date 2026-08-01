# RunPod model evaluation programs

These programs run inference only. They never mount benchmark ground truth and
therefore cannot score or promote a model by themselves. Copy the immutable raw
artifacts back to the evaluator environment, freeze their hashes, and then run
the official and Structara critical evaluators.

`paddleocr_vl_stage2.py` records one cold initialization followed by exactly
three same-process repetitions over a frozen image cohort. A failed page stays
in the evidence as a failure.

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
