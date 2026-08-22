# MinerU 3.4.4 VLM Runtime Diagnostic

MinerU's local VLM engine passed a one-image smoke after the declared optional
dependency `accelerate>=1.5.1` was supplied as the pinned version 1.14.0. The
same runtime then failed its 18-page, three-repeat cohort at the default local
API concurrency of three: 6/54 completed and 48/54 failed.

The dominant error was a tensor-shape mismatch in concurrent VLM inference.
The successful page identities changed between repeats, so no accuracy metric
was computed and the candidate is not promotion-eligible. Empty artifacts were
recorded as failures, never as successful blank pages.

The model artifact, run summary, stderr/stdout, successful outputs, and all
empty failure artifacts are preserved by SHA-256. A concurrency-one isolation
run is the required next stage. This diagnostic is operational evidence, not a
model-quality score.
