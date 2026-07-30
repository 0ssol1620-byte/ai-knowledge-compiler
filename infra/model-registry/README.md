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
