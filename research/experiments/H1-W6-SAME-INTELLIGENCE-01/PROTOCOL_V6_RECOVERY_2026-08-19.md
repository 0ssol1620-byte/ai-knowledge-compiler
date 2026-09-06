# W6 v6 — recovery protocol, frozen

**Frozen 2026-08-19, before any v6 acquisition runs.** Supersedes nothing: v3's
scientific rules stand unchanged and are pinned by hash below.

`scientific_rules_changed: false`. This protocol changes **where** acquisition
writes and **nothing else**.

---

## 1. Why a fresh corpus rather than a resume

Measured, not assumed — `receipts/recovery-fixture-2026-08-19.json` confirms all
five predictions of the static audit:

| property | measured |
|---|---|
| a re-run overwrites an existing complete pair | confirmed |
| a kill mid-pair leaves an incomplete directory | confirmed |
| no `metadata.json` is written on a partial pair | confirmed |
| `metadata.json` is a sound completion marker when present | confirmed |
| writing into a fresh corpus dir does not touch the old one | confirmed |

A safe resume would need skip-on-exists, integrity validation and atomic writes.
Adding them means editing `acquire_w6_v3.py`, whose sha256 the frozen title
manifest pins and which the script self-checks. **Immutability and recoverability
cannot both be had here**, and immutability is what makes the 6,987-title cohort
trustworthy.

**And there is nothing to resume.** `corpus-v5`'s single directory holds
`before.wikitext` and `after.wikitext` but no `metadata.json`, so by the
semantics measured above it is an **incomplete** pair. corpus-v5 contains **0
complete pairs**. Resuming would save no work at all.

## 2. What v6 does

1. acquire into a new `corpus-v6/`, leaving `corpus-v5/` byte-untouched;
2. reuse the **same** frozen 6,987-title manifest, the same `BEFORE_CUTOFF` /
   `AFTER_CUTOFF`, the same separation minimum and the same cohort/stop rules;
3. retain `corpus-v5/` as failed-run evidence, referenced by the health-check and
   completeness receipts.

Because the cutoffs pin which revision is fetched per title and the traversal is
deterministic over the frozen manifest, cohort composition is reproducible and
does not depend on where the previous run died.

## 3. Forbidden

- copying v5's partial pair into v6 — that would make the cohort depend on the
  crash point;
- selecting, reordering or trimming titles based on anything v5 acquired;
- editing `acquire_w6_v3.py`, whose hash the manifest pins;
- restarting into `corpus-v5`, where the first write would overwrite
  non-atomically;
- adjusting any threshold, cutoff or stop rule. The endpoint stays what v2/v3
  froze.

## 4. Completion criteria for the acquisition itself

- a completion sidecar receipt exists and records a return code;
- every pair directory either contains all three files or is reported as
  incomplete;
- the acquisition receipt pins the manifest file hash, the manifest receipt hash,
  the protocol hash and the script hash.

An acquisition that ends without a sidecar is a **failed run**, exactly as v5
was, and is recorded as one.

## 5. What this protocol does NOT authorise

It does not authorise interpreting the W6 endpoint. Acquisition completing means
a corpus exists; whether the primary endpoint can be evaluated depends on whether
the frozen question set finds moved facts, which is the question v2 already
declared NOT RUN once rather than weaken. **That declaration stands and this
protocol does not revisit it.**

## 6. Status

Frozen and **not executed**. Execution requires network access and a run measured
in hours. Everything up to the network boundary is complete: audit, fixture,
decision, protocol.
