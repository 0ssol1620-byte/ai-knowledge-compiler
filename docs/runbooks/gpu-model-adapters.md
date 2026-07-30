# GPU model adapters

The parser and knowledge workers have production adapter modules, but remain
disabled until the model registry, license review, immutable artifacts, and
private benchmark gates pass. A passing local contract test is not evidence
that either model is production-ready.

## PaddleOCR-VL 1.6

`paddleocr_adapter` invokes the complete `PaddleOCRVL` pipeline: layout
analysis plus element recognition. It does not invoke the standalone VLM as if
that were the full parser. The production image must install a reviewed,
exactly pinned PaddleOCR/PaddlePaddle/CUDA set and mount both model directories
read-only.

Required values:

- `MODEL_REVISION`: exact upstream 40-64 character hexadecimal revision.
- `MODEL_ADAPTER_MODULE=paddleocr_adapter`.
- `PADDLEOCR_MODEL_MANIFEST`: path to a JSON document satisfying
  `infra/model-registry/paddleocr-model-manifest.schema.json`.
- `PADDLEOCR_MODEL_MANIFEST_SHA256`: SHA-256 of that exact manifest.
- `PADDLEOCR_ENGINE`: one reviewed engine from `paddle`, `paddle_static`,
  `paddle_dynamic`, or `transformers`.
- `PADDLEOCR_DEVICE`: `gpu:N` in production.

Every file listed in the manifest is re-hashed before the pipeline is loaded.
The adapter refuses path traversal, missing coverage for either model
directory, model revision drift, multiple returned pages, invalid boxes, and
non-JSON output. It preserves the structured provider result (without raw
image payloads) and its digest. Markdown is regenerated downstream from CIR.

## Qwen 3.5 knowledge compiler

`qwen_adapter` talks only to an OpenAI-compatible inference server on loopback.
This keeps the worker from silently becoming an external data-transfer path.
The serving engine is a separately pinned process or sidecar and must expose
the exact attested model name from `/v1/models`.

Required values:

- `MODEL_REVISION`: exact upstream 40-64 character hexadecimal revision.
- `MODEL_ADAPTER_MODULE=qwen_adapter`.
- `RUNTIME_IMAGE_DIGEST`: exact `sha256:` digest of the running worker image.
- `ADAPTER_VERSION`: exact adapter version in both the control request and
  model attestation.
- `QWEN_MODEL_ATTESTATION`: path to a document satisfying
  `infra/model-registry/qwen-model-attestation.schema.json`.
- `QWEN_MODEL_ATTESTATION_SHA256`: SHA-256 of that exact attestation.
- `KNOWLEDGE_BUNDLE_SCHEMA`: read-only path to
  `packages/contracts/schemas/knowledge-bundle.schema.json`.
- `KNOWLEDGE_BUNDLE_SCHEMA_SHA256`: exact `sha256:` digest of that schema.
- `KNOWLEDGE_PIPELINE_SCHEMA`: read-only path to
  `packages/contracts/schemas/knowledge-pipeline-result.schema.json`.
- `KNOWLEDGE_PIPELINE_SCHEMA_SHA256`: exact `sha256:` digest of that schema.
- `QWEN_INFERENCE_URL`: loopback
  `http://127.0.0.1:PORT/v1/chat/completions`.
- `QWEN_INFERENCE_API_KEY`: optional local serving credential.
- `QWEN_MAX_OUTPUT_TOKENS`: bounded to 128-32768.

The durable control request contains only object keys, hashes, exact
attestations, and bounded options. Source blocks and source text live only in a
tenant-scoped derived input object and are downloaded inside the worker. They
must never be copied into Runpod request options, callbacks, events, or
database result manifests.

The request disables thinking, supplies no tools, and separates untrusted
document JSON from system instructions. The production path requests one
strict A-D result at a time rather than sending an entire document in one
generation. Stage A sees bounded previews, Stage B sees one bounded section
shard, Stage C sees semantic descriptors plus evidence snippets/hashes, and
Stage D sees only ACL-attested semantic retrieval candidates.

Admission requires exact prompt and schema hashes,
`unsupported_claim_count=0`, stage/unit/document scope, and complete
block-level evidence. Stage C requires exact compared candidate/evidence IDs
and a specific reason; a multi-candidate merge without conservative semantic
support is rejected. Stage D rejects candidates outside the attested
tenant/project scope and forbids links when retrieval is unverified. The
adapter also rejects unknown evidence block IDs, duplicate stable keys,
reasoning output, truncated generations, non-finite confidence, oversized
responses, and non-loopback endpoints. Raw completion output remains only in
the private derived result object; the control-plane manifest retains bounded
counts, attestations, and hashes.

## Promotion evidence

Do not enable a route until all of the following are attached to the registry
entry and release record:

1. exact model and runtime revisions plus image digest and SBOM;
2. model/code/dataset/runtime license snapshots and approval;
3. signed model manifest or attestation;
4. private golden-corpus report for quality, latency, VRAM, timeout, OOM, and
   schema conformance;
5. prompt-injection and unsupported-claim tests;
6. canary, rollback revision, and provider-outage drill evidence.

The official PaddleOCR and Qwen benchmark figures are upstream claims only.
They must not be relabeled as AKC internal results.
