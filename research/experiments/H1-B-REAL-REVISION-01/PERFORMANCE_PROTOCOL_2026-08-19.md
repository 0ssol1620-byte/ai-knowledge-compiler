# Family B compute / latency measurement protocol — frozen before timing

This closes evidence-axis 6. Previous Family-B receipts counted artifacts but did
**not** measure compute, wall-clock time, memory, or bytes written. Those counts
must not be presented as performance measurements.

## 1. Two evidence strata, never pooled

### A. Real-revision replay
Use the already frozen `holdout-v2` and `confirmatory-v1` Wikipedia pairs. Raw
wikitext sha256 must match the acquisition receipts. For every pair, compare:

- **full rebuild:** compute every artifact hash for the after revision;
- **selective rebuild:** compute semantic diff + PRECISE plan, then compute after
  hashes only for artifacts in `to_rebuild`, carrying the remaining frozen before
  hashes.

Report pair-level wall time and rebuild fraction. The primary real-data number is
paired median wall-time ratio; p50/p95 are descriptive because n is small.

### B. Controlled scaling harness
Generate deterministic semantic dependency graphs at **1,000** and **10,000**
section artifacts plus one document-index artifact. Exactly **1%** of units change,
selected by a frozen seed. Every section artifact consumes one unit; the index
consumes all units. Edges are declared SEMANTIC-only. This is a controlled
algorithmic scaling benchmark, **not production traffic** and not a claim about
real-world graph distributions.

For each scale run 3 warm-up iterations excluded from timing, then 30 recorded
iterations per arm. Alternate arm order by trial. Report p50/p95 and all raw
samples.

## 2. What is timed

Two timings are reported rather than hiding planner overhead:

1. **build-only:** hash/serialize the artifacts each arm actually rebuilds;
2. **end-to-end change handling:**
   - full = rebuild every after-state artifact + serialize outputs;
   - selective = semantic diff + plan + rebuild planned artifacts + serialize
     outputs + verify the reconstructed result against the full oracle hash map.

The full oracle required for *verification* is prepared outside the selective
end-to-end timer. Otherwise the selective arm would be charged the full rebuild
whose purpose is only experimental scoring.

## 3. Memory and I/O

`tracemalloc` peak Python allocation is recorded separately from process RSS and
labelled as such. Serialized JSONL output is written to a temporary file in every
recorded build-only trial; actual file byte size is recorded. It is a harness I/O
measure, not an assertion that production persists artifacts in this format.

GPU cost is $0.00. No GPU is useful for these Python graph/hash operations.

## 4. Correctness gate

No performance ratio is reportable unless every selective reconstructed artifact
hash equals the independently computed full after-state oracle. Any stale escape,
missing artifact or hash divergence invalidates that cell before speed is read.

## 5. Reproducibility

Pin script sha256, seed, Python version, platform, CPU logical count, protocol
sha256, source receipt hashes, raw timing samples and canonical receipt sha256.
No claim about a 100k scale is made from extrapolation; 100k may be listed only as
future work unless directly measured in a separate preregistered run.
