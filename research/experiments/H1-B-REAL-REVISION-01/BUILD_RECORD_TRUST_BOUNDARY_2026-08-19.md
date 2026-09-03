# The build-record trust boundary, measured

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

Receipt: `receipts/build-record-mutation-2026-08-19.json`
(seed `20260822`, 2 declaration modes × 9 record mutations × 7 shape classes ×
60 cases = 7,560 runs). External GPU cost: **$0.00**.

---

## 1. The assumption that replaced the last one

Moving promotion safety off the dependency declaration and onto the build record
did not remove an assumption; it moved it. Safety now rests on the record being a
complete and accurate account of what the builder consumed. This attacks that.

**The first run of this sweep returned all zeros and proved nothing.** With
honest declarations, PRECISE leaves nothing stale — so there was no staleness for
a bad record to conceal, and every mutation scored zero for the same
uninformative reason. The build record is the *second* line of defence and can
only be tested once the first has failed. The sweep therefore layers each record
mutation on top of an under-declared graph.

## 2. Result, under an already-failed planner

180 escape cases per row. `honest` declaration is all-zero throughout and is kept
in the receipt as the control.

| build-record mutation | blocked | **stale promoted** | detected? |
|---|---|---|---|
| honest | 180 | **0** | — |
| semantic input omitted | 180 | **0** | yes |
| partial reading order recorded | 180 | **0** | yes |
| extra nonexistent input recorded | 180 | **0** | yes |
| wrong block count recorded | 120 | **60** | partial |
| misrecorded consumption order | 120 | **60** | partial |
| **structural input omitted entirely** | 0 | **180** | **no** |
| **stale record reused from prior revision** | 0 | **180** | **no** |
| **old receipt attached to rebuilt artifact** | 0 | **180** | **no** |

## 3. What this falsifies, including my own prediction

The prediction written into the script was that corruption present on *both*
sides would cancel and corruption present on *one* side would show up as a
mismatch. The first half held. **The second half was wrong**, and the three
fail-open rows say why.

The gate compares a fingerprint *now* against a fingerprint *at build time*. Any
mutation that makes those two agree is invisible, and one-sidedness does not
guarantee disagreement — attaching the prior revision's record to the "now" side
makes it agree with the stored side exactly, which is agreement, which the gate
reads as evidence of currency.

That yields a design rule the measurement produced rather than confirmed:

> The **expected** side may legitimately come from a stored build receipt. The
> **now** side must be recomputed from the live source and never derived from
> stored state. Where both sides are read from records, staleness cancels and the
> check degenerates into comparing a record with itself.

## 4. The boundary, stated plainly

**Detectable:** a record that misstates *which* inputs were read, when the
underlying data still differs between revisions.

**Undetectable by fingerprint comparison alone:**

1. **Consistent omission of a whole input class.** A builder that never records
   shape produces two fingerprints that agree because neither contains the thing
   that changed. No comparison of two such fingerprints can recover it.
2. **Any record substitution that makes the two sides agree**, including reusing
   the prior revision's record.

Partial detection (`wrong_block_count`, `misrecorded_order` at 120/180) happens
only because *other* recorded facts still differ; it is a side effect, not a
guarantee, and must not be reported as one.

## 5. What follows

**Cryptographic binding helps with (2) and not with (1).** Binding
`artifact_sha256 ↔ build_receipt_hash ↔ input_fingerprint`, with the builder
version and build action id inside the hashed body, makes a receipt from another
build unattachable: it names bytes that are not these bytes. It does nothing
about a builder that never recorded shape, because that receipt is internally
consistent and simply silent.

**(1) is closable only by construction, not by verification.** If consumption is
captured automatically during build execution rather than declared by hand, a
class of input cannot be silently omitted — there is no hand-written list to omit
it from. That is the design direction, recorded here as a direction: it is not
implemented and nothing here measures it.

Until then this is the honest three-layer statement:

| layer | source | verified against | residual assumption |
|---|---|---|---|
| planning | channel declarations | — | may be wrong; costs correctness, not safety |
| build provenance | recorded consumption | — | **must be complete; not verifiable from itself** |
| promotion | live recomputation vs stored receipt | build receipt | now-side must not come from stored state |

"Independent of the declaration" remains supported. **"Independent of everything"
is false and is now measured to be false.**

---

## 6. Implemented: receipt binding — and an audit of what it cannot cover

`akc_cir.build_receipt` seals `artifact_id`, `artifact_sha256`,
`input_fingerprint`, `build_action_id`, `parent_world_state_id`,
`builder_version` and a tracked-capture flag into one digest. Every field is
inside the seal, so there is none left to edit undetected.
`tests/unit/test_build_receipt.py` turns each observed failure red, and removing
the parent-world-state check alone makes
`test_a_receipt_from_the_prior_revision_is_refused` fail — the binding is
load-bearing, not decorative.

The asymmetry is enforced in the signature rather than documented in prose:
`verify_carry_forward` takes `live_input_fingerprint` as a required argument with
no default, so it cannot quietly become `receipt.input_fingerprint` and compare
the receipt with itself.

| observed failure | before | now |
|---|---|---|
| stale receipt reused from prior revision | 180 promoted | refused — `WRONG_WORLD_STATE` |
| receipt from another build attached | 180 promoted | refused — `WRONG_ARTIFACT` / `WRONG_BYTES` |
| correct receipt, rebuilt artifact bytes | undetected | refused — `WRONG_BYTES` |
| **builder never recorded an input class** | 180 promoted | **still not detected** |

### The tracked/untracked boundary, audited rather than assumed

The proposed close for the last row is a provenance-aware build API —
`BuildContext.read_unit()`, `read_structure()`, `read_order()` — where reading is
the thing that records. Before claiming automatic capture, the question is
whether builders can be *prevented* from reading anything else.

**They cannot, today.** The v3 adapter's `artifact_hashes` takes a plain Python
dict and a list of `UnitSnapshot`s and reads them directly; nothing constrains a
builder from touching module globals, the filesystem or any object handed to it.
So "consumption capture is complete" is not a supportable claim for any builder
in this repository.

What is supportable is a fail-closed policy, and it is what the module
implements: a receipt carries `consumption_automatically_captured`, and
`verify_carry_forward` refuses an untracked builder's artifact by default. That
is **declining to vouch**, not detecting — a weaker guarantee, named as one. The
permissive path exists and must be asked for by name.

Until a controlled access boundary exists and is enforced, builders divide into
**tracked** and **untracked**, and untracked output is not eligible for
high-integrity promotion.
