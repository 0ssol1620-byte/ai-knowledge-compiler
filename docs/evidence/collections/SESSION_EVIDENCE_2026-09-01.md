# Session evidence — 2026-09-01

**Repository:** `ai-knowledge-compiler-vkc-research`, branch `agent/tavonel-vkc-research`
**Companion:** `ai-knowledge-compiler`, branch `agent/folynta-trust-integration-v1` (manuscript side)
**GPU spend this session:** $0.00

This records what was established, what failed, and what remains open. Failures
are reported at the same level as successes because two of the three results
here exist only because a first attempt failed and was kept.

---

## 1. Audit sections closed

| Section | Subject | Verdict |
|---|---|---|
| 28-B | Preservation scientific E2E | **CLOSED** — C-37 |
| 28-C | Family B robustness | **CLOSED** — C-36 |
| 28-E | Reproducibility package | **CLOSED** — 29 artifacts pinned |
| 28-F | Manuscript completeness | **CLOSED** — threats-to-validity added |
| 28-G | Adversarial review | **CLOSED** — mechanical, mutation-tested |
| 28-A | Semantic Risk confirmatory | **OPEN** — blocked on runtime images |
| 28-D | Ontology/graph appendix | Not attempted this session |

---

## 2. C-36 — regulatory robustness (28-C)

Eleven prospectively frozen revision pairs from eleven eCFR parts across seven
US federal regulators and six CFR titles.

```
equivalence            11/11
stale artifacts        0
agreement with the
  publisher's flag     11/11
semantic changes       94
locator/metadata       11,226
mean work avoided      88.66%
unresolved identity    6  (reported as unresolved, not counted as agreement)
GPU seconds            0
```

**Why eCFR rather than the SEC filings used elsewhere.** Each eCFR revision
record carries a publisher-assigned `substantive` boolean — an outside answer
to the question the compiler is being asked. Wikipedia has no equivalent. The
flag scored the result and was never used to select pairs; the protocol
forbids that, and the 28-G review checks the prohibition is still in force.

**The predecessor is the more useful half.** ECFR-01 (title 21 only) passed
both safety gates and produced a *higher* headline figure — 96.12% — then
failed its own preregistered adequacy gate at 5 changed pairs against a
required 6, because six of its eleven pairs were byte-identical
non-substantive reissues with nothing to recompile. The gate rejected the more
flattering cohort. The successor raised the threshold from 6 to 8 rather than
lowering it (**N-18**).

---

## 3. C-37 — preservation fault injection (28-B)

Forty-nine canonical documents built from real extraction output over the
frozen Lane A corpus, four fault families.

```
F1 missing source block      49/49
F2 cross-version evidence    49/49
F3 detached table cell       49/49
F4 dropped critical token    49/49
false positive rate          0.0
N1 uncited-mutation control  45 controls, 0 fired
repair locality, blocks      2.1%  mean quarantined fraction
repair locality, pages       6.0%
GPU seconds                  0
```

**The locality figure is the load-bearing one.** Detection rates of 1.0 on
deterministic structural invariants are closer to a correctness check than a
measurement. A single-block fault quarantining ~2% of blocks is what separates
local repair from reprocessing the document — the premise the whole selective
recompilation argument rests on.

**The predecessor failed and is kept.** PRESERVATION-E2E-01 detected 18 of 49
cross-version injections against a preregistered 1.0. Partitioning by whether
the mutated block was cited gave a perfect diagonal:

|  | mutated block cited | not cited |
|---|---|---|
| violation fired | 18 | 0 |
| no violation | 0 | 31 |

Every injection a binding witnessed was caught; every miss was a mutation of
evidence nothing cited. The defect was in the harness, which always mutated
the first block regardless of citation. E2E-02 changes that one line, leaves
the failed gate at 1.0, and promotes the accident into an explicit control
(**N-19**).

---

## 4. 28-G — adversarial review, and why it is trustworthy

Five of the nine hostile questions are checkable against receipts rather than
assertable in prose. Those five are implemented in
`research/experiments/adversarial_review_28g.py`. The other four are product
control-plane properties and are printed as out of scope rather than silently
counted as passes.

**It found two defects on first run, both mine:** Q5 compared a whole-file
hash against a pin that is actually the receipt's declared content hash, and
Q4 looked for a `verdict` field the ECFR receipts do not write.

**Then the review was mutation-tested,** because a review that only ever
prints PASS is decoration:

```
M1 lower the ECFR adequacy gate 8 -> 4          CAUGHT
M2 repoint C-37's receipt pin at a wrong hash   CAUGHT
M3 relabel C-36 held_out -> development         MISSED   <-- hole found
```

M3 exposed that Q4 asserted only that `split` was a known vocabulary word,
which a dishonest relabel satisfies trivially — while 28-G asks precisely
whether a development result was presented as confirmatory. Q4 now holds each
claim to the split its receipts entitle it to. Re-run: **3/3 caught**.

---

## 5. 28-A — why it is still open

The confirmatory inference needs two baked runtime images. Five distinct build
failures were diagnosed and fixed; the images are not the obstacle they were.

| # | Failure | Cause | Resolution |
|---|---|---|---|
| 1 | 4s | GitHub Actions billing | free minutes reset |
| 2 | 6m | `PackageNotFoundError: torch` | base image ships two interpreters; `pip` is 3.12, `python3` is 3.10 |
| 3 | 5m30 | `2.8.0` != `2.8.0+cu128` | CUDA local version tag; check now compares both halves and rejects cu126/CPU wheels |
| 4 | 13m30 | no space on device | Docker data-root moved to `/mnt` |
| 5 | 15m | artifact manifest mismatch | `.cache` metadata was being hashed; the frozen constant was right |

**Failure 5 mattered most.** Changing `ARTIFACT_MANIFEST_SHA256` to the
observed value would have turned the build green. Investigation instead showed
the model was intact — the Hugging Face API reports exactly 13 files totalling
2,328,028,720 bytes for revision `bff20d4a`, matching the 2026-08-01 record
byte for byte — and that `snapshot_download` writes `.cache/huggingface/`
metadata which was being hashed along with the weights. Both sibling
bootstraps already excluded it and said why. The Dockerfile was wrong; the
constant was right.

MinerU has built and pushed successfully:

```
ghcr.io/0ssol1620-byte/ai-knowledge-compiler/mineru-3.4.4-vlm-c1
  @sha256:d3bc0343ff3ae68d5804a15c86c88acd3f94e77e983330a69b6eecfe8b8753eb
```

### Paddle is blocked, and the block is recorded honestly

`fastdeploy-gpu==2.3.0` has been withdrawn upstream. Measured:

| Source | Result |
|---|---|
| PyPI project | 404 — not on PyPI at all |
| PaddlePaddle cu126 index | 200, advertises only 2.5.0 |
| CDN 2.3.0 cp310/311/312 | 404 |
| CDN 2.5.0 cp311 (control) | 200, 1,766,070,369 bytes |

The control returning 200 from the same URL shape makes this a withdrawal, not
a bad path. Bumping to 2.5.0 would void both the runtime assertion and a
sha256-checked source patch, and CONF-02 would run on a runtime the 2026-08-01
results do not describe.

Recovery from the surviving network volumes was attempted by two routes and
both are closed: no RunPod capacity in US-KS-2 or EU-RO-1 (an unconstrained
control create succeeded on the same GPU type, so this is placement, not the
volumes), and the S3 gateway rejects every credential we hold — the two S3 key
pairs on file are Cloudflare R2, not RunPod.

**Option 1 is untested, not refuted.** The wheel may still be on those
volumes; we cannot currently look. Recording "we could not look" must not
decay into "the artifact is gone".

---

## 6. Frozen-instrument integrity

`verify_frozen_integrity.py` was re-run after every stage of this session.
SEM-RISK-CONF-02's seal survives all of it: `all_checks_passed: true`. The
preservation experiments read its outputs and wrote nothing into that tree.

---

## 7. What a reviewer should distrust first

Both headline results come from instruments whose first version failed. That
is the honest history and also the classic route to a false positive. The
constraints are that gates were never loosened — ECFR 6→8, preservation held
at 1.0 — and that the 28-G review verifies this mechanically rather than
relying on the paragraph you are reading. Neither rules out the subtler
version: the diagnosis of each failure was chosen after seeing it.

Both cohorts are small (11 pairs, 49 documents), neither supports an interval,
and image-only pages and non-Latin scripts are absent from both — which is
where the measured mechanisms are most likely to behave differently.

Every result here was produced, checked, and written up by the same programme.
No external replication has been attempted.
