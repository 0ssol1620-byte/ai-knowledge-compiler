# Model Registry

The committed registry is fail-closed. Real model entries intentionally remain
`candidate_unverified` with null revisions until release engineering captures
the official full revision, license snapshot, runtime version, image digest,
and reproducible benchmark. They therefore cannot receive production traffic.

Validation:

```bash
python infra/model-registry/validate_registry.py
```

`--strict` is a promotion check and is expected to fail until every candidate
has been pinned. Promotion additionally requires security/model CI, the quality
report, canary evidence, and a one-change rollback target.

The Paddle worker consumes a signed-by-release-process, checksummed document
matching `paddleocr-model-manifest.schema.json`; the Qwen worker consumes
`qwen-model-attestation.schema.json`. These files bind the runtime to exact
local model artifacts and an immutable serving image. See
`docs/runbooks/gpu-model-adapters.md` for the full activation procedure.

## Gemma 4 12B challenger boundary

The v4 masterplan names Gemma 4 12B as an independent Knowledge Compiler
challenger. On 2026-07-31, official Google documentation listed the 12B family
and the public `google/gemma-4-12B` repository reported immutable revision
`023679ed352de9bb66cc873c9009ce3482585c08` with Apache-2.0 weight-license
metadata. Those public discovery facts are recorded in `models.yaml`; the
identifier and revision are not inferred aliases.

This is not an internal model attestation. The repository has not captured an
approved license snapshot, downloaded and checksummed the weights, pinned a
compatible runtime and serving-image digest, or executed the private Knowledge
Compiler benchmark. Consequently:

- `gemma4_12b_challenger` has zero traffic;
- `knowledge_gemma_challenger_v1` is disabled and falls back to `unresolved`;
- no endpoint or feature flag is enabled; and
- `validate_registry.py` rejects traffic or an enabled recipe until full
  license/runtime/image/internal-validation evidence exists.

Public references reviewed:

- <https://ai.google.dev/gemma/docs/core>
- <https://ai.google.dev/gemma/docs/releases>
- <https://huggingface.co/google/gemma-4-12B>
- <https://huggingface.co/api/models/google/gemma-4-12B>

Re-fetch and archive these sources under the release-owned model supply-chain
process before promotion; current metadata is drift-prone and does not close
`EG-03`, `EG-04`, `EG-05`, or `EG-10`.
