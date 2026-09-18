# SEC Source-Fact Router Development Holdout

Status: **RESEARCH_PROVEN NEGATIVE · NO PUBLIC CLAIM · NO PRODUCTION PROMOTION**

## Question

Can the frozen two-primary plus adjudicator policy reduce silent critical fact
loss while avoiding an always-all execution cost on previously unopened SEC
filing regions?

## Bound execution

- Six fixed issuers, four deterministic facts each, 24 regions total.
- SEC EDGAR Inline XBRL HTML was the source authority.
- The input set, three model revisions, runtime bundles, prompts, model outputs,
  and output-only routing decisions were frozen before the sealed facts opened.
- MinerU and Paddle ran on all 24 regions. Ovis ran only on the 17 primary
  disagreements.
- All 65 RunPod responses passed checksum and runtime-identity checks. Every
  created pod was deleted; the observed live-pod count after execution was zero.
- Reconciled experimental GPU cost was USD 0.317190.

The concrete scoring implementation was committed after the truth opened. This
makes the result development evidence rather than a clean confirmatory result.
The scorer was then executed twice and produced byte-identical result and
per-region files.

## Result

| System | Signed fact retention | SCLR | Detected/unresolved | Warm inference USD/1k | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| MinerU fixed | 70.8% | 25.0% | 4.2% | 0.242726 | 1,058 ms | 1,476 ms |
| Paddle fixed | 62.5% | 8.3% | 29.2% | 0.130691 | 693 ms | 797 ms |
| Frozen Router | 37.5% | 12.5% | 50.0% | 0.409423 | 1,202 ms | 3,046 ms |
| Executed-output Oracle | 87.5% | diagnostic only | n/a | n/a | n/a | n/a |

Paddle is the best fixed primary under the predeclared SCLR-first comparison.
The Router is 4.17 percentage points worse on SCLR and 25 points worse on signed
fact retention. The paired issuer-cluster bootstrap interval for the Router
minus Paddle SCLR difference is `[-8.33, 16.67]` percentage points. The interval
does not establish an improvement.

Eleven routes were refused. Only one refusal had no correct accepted candidate
among the outputs that were actually run; ten were avoidable with a better
output-only election rule. One primary agreement consisted of semantic empty
outputs and must be stopped by a semantic-error hard gate.

## Diagnosis

The candidate policy compares complete row-level critical-token multisets.
Small non-target disagreements therefore trigger adjudication or refusal even
when two models preserved the selected fact. This is the wrong evidence unit
for a source-bound region executor. It also makes the system slower and more
expensive than the best fixed primary on this set.

The next candidate must:

1. reject every transport or semantic error before agreement or selection;
2. use the bound target bbox to execute and compare the target cell or a tightly
   padded target region instead of the complete table row;
3. verify magnitude, sign, percent, unit, and cell alignment as separate loss
   channels;
4. keep unresolved when the target-specific verifier lacks corroboration;
5. demonstrate positive value on spent development data before another policy,
   threshold, runtime, and evaluator freeze;
6. open a new untouched holdout only after that freeze, followed by shadow,
   rollback, and bounded-rollout evidence.

## Claim boundary

This run does not support “TAVONEL beats the tested models,” “faster than a
single model,” or “minimal information loss.” It supports a narrower and useful
finding: exact whole-row agreement is a poor proxy for target fact correctness,
and a source-bound target-region verifier is required.

Hashes and exact metrics are frozen in `SEC_SOURCE_FACT_SCORE_FREEZE.json`.
