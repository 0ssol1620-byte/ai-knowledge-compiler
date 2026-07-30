# Multimodal retrieval boundary

`akc_retrieval` implements the model-agnostic retrieval boundary described by
the masterplan. Text, table, formula, and image-derived records share one
strict contract while retaining source hashes and evidence block IDs.

The query contract enforces the initial operating window:

- 30–100 vector candidates;
- 5–15 final results;
- an explicit tenant and 1–50 allowed projects;
- an explicit modality allowlist;
- finite, non-zero vectors with a fixed index dimension.

The store must apply tenant, project, and modality filters before ranking.
`RetrievalService` repeats those checks on every returned candidate and rejects
duplicate IDs. A reranker may only reorder or select from the supplied
candidate IDs. Its provider ID and immutable revision must match configuration,
and every final result retains the source hash and evidence block IDs.

`InMemoryVectorStore` is deterministic test/development infrastructure only.
Production activation remains off until Qwen3 Embedding/Reranker revisions,
runtime images, corpus indexing, deletion propagation, recall/nDCG results,
latency, and cost are validated. The API must return unavailable rather than
silently using this in-memory store as production persistence.
