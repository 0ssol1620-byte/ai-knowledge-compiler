# Product-Core semantic qualification receipts

These are regression receipts from `benchmark/product_core_semantic_qualification.py`: 7 synthetic documents, 5 queries, `externalGeneralizationClaim: false`. They are not public claims, and the claims pack does not cite them.

A receipt is never rewritten. When the shipped `semantics.py` or `retrieval.py` changes, add a new receipt with a new date. `tests/unit/test_product_core_semantic_qualification.py` regenerates the current receipt and fails if it no longer matches.

| Receipt | `semantics.py` | `retrieval.py` | Status |
|---|---|---|---|
| `product-core-semantic-qualification-2026-08-29.json` | `sha256:7289b28c…` | `sha256:a5ace289…` | **Superseded** by 2026-11-05. `semantics.py` changed five times after this receipt was taken. That code is no longer in the tree, and the file is kept as history. |
| `product-core-semantic-qualification-2026-11-05.json` | `sha256:2e2ec557…` | `sha256:a5ace289…` | **Superseded** by 2026-11-08. Baseline precision@1 0.4 (2/5), candidate 1.0 (5/5). One baseline top-1 differs from 2026-08-29 (`a-distractor` → `b-informal` on one query). Neither precision value changed. |
| `product-core-semantic-qualification-2026-11-08.json` | `sha256:29cba395…` | `sha256:a5ace289…` | **Superseded** by 2026-11-09. `semantics.py` changed only by moving the contradiction pairing into `contradiction_candidates` (shared with `corpus_reduce`, ADR-008); behaviour is unchanged. Every field except `algorithmSha256.semantics.py` and `qualificationDate` is identical to 2026-11-05. |
| `product-core-semantic-qualification-2026-11-09.json` | `sha256:8fbed511…` | `sha256:a5ace289…` | **Current.** `semantics.py` bounds contradiction pairing (`MAX_CONTRADICTION_PAIRS_PER_GROUP` 496, `MAX_CONTRADICTION_PAIRS_PER_COMPILE` 1,024; D0 2026-11-09); no fixture here comes near either bound, so retrieval is unchanged. Every field except `algorithmSha256.semantics.py` and `qualificationDate` is identical to 2026-11-08. |
