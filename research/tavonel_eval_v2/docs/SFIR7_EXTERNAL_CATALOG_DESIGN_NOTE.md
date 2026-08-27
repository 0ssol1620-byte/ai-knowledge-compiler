# SFIR7 — which external catalogue, and on what terms

Design note for `protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7_DESIGN_CHARTER.yaml`.
Nothing here authorises an acquisition, a census or a freeze.

Interpreter of record for every figure below:
`D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe` (INC-V2-103).

## What the catalogue is for

SFIR7 exists because SFIR5 and SFIR6 cannot answer one question: when the git
frame yields few qualifying revision pairs, is that the system or the frame?
The only way to ask it honestly is to stop choosing repositories. So the
requirement on the catalogue is not that it be good, or large, or current. It is
that **someone else decided what is in it, for reasons that have nothing to do
with this study's result.**

That gives four hard requirements and one soft one:

1. **Third-party inclusion decisions.** TAVONEL must not appear anywhere in how
   the catalogue was built.
2. **A pinnable snapshot.** Bytes on disk, digest recorded, reproducible later.
3. **Fields sufficient for the declared predicates**, published by the catalogue
   itself: host, owner/name, SPDX licence, creation date, last activity date.
4. **The catalogue's own ordinal**, so the ranking is theirs and not ours.
5. Soft: enough eligible records that N=125 is a cut rather than the whole pool.
   Soft because a short pool is a reportable finding, never a reason to widen a
   predicate.

Requirement 4 is where most candidates fail. A catalogue with no ordinal forces
TAVONEL to invent a ranking, and an invented ranking is exactly the discretion
SFIR7 is trying to remove.

## Candidates

### A. Libraries.io Open Data — proposed primary

An open dataset of package and repository metadata published by Libraries.io,
deposited on Zenodo as versioned, DOI-addressed archives. Its `repositories`
table carries host type, `name_with_owner`, declared licence, creation and last
push timestamps, primary language, and **SourceRank** — the project's own
composite ordinal.

- **Independence.** Published by Libraries.io/Tidelift. No TAVONEL involvement in
  what is indexed or in how SourceRank is computed. The ranking predates this
  study by years and cannot have been influenced by it.
- **Pinnability.** A Zenodo deposit is immutable per version and carries its own
  checksums; a specific version's archive is straightforwardly digest-pinned.
- **Field fit.** The only candidate that satisfies requirement 4 directly.
- **Currency.** The dataset is a snapshot of its release date, not of today. The
  frame rule already anchors both date predicates to `snapshot_date_utc` rather
  than to "now", so a historical snapshot is handled correctly rather than
  awkwardly — but it does mean the universe is the software landscape *as of that
  release*, which is a scientific fact about SFIR7 that must be reported, not a
  footnote.

**Licensing — FLAGGED, not resolved.** The dataset is published under a Creative
Commons licence in the BY-SA family. Two things follow that this lane cannot
decide:

- **Attribution** is easy and will be honoured in every receipt.
- **Share-alike is a real question.** SFIR7 would publish a derived roster of 125
  repositories, plus per-record dispositions, plus a rule digest. Whether that
  roster is an "adapted work" that must itself carry a share-alike licence, or a
  use of unprotectable facts extracted from a database, is a legal judgement.
  The project constitution is explicit that "an OSS licence is not patent freedom
  to operate" and that code, weights, dataset and API terms are separate
  licences; the same care applies here. **This is a founder decision.** Do not
  assume the permissive reading.

I have deliberately not asserted a specific DOI or version string in the charter
or in the code. The exact deposit must be resolved and pinned at acquisition
time, by someone looking at the deposit page, and recorded with its digest —
not written down here from memory.

### B. OpenSSF Criticality Score published results

The OpenSSF publishes criticality scores for open-source projects, computed by
their own tooling from their own signal set.

- **Independence.** Good. The ranking is theirs, published, and documented.
- **Field fit.** Repository URL and an ordinal, yes. Licence, creation date and
  last-activity date are generally **not** in the published results, so those
  predicates would have to be sourced from somewhere else — which reintroduces a
  second, differently-governed input and weakens the "one frozen universe"
  property.
- **Licensing.** The tooling is Apache-2.0; the terms attached to a specific
  published results release must be confirmed against that release. **Not
  assumed here.**
- **Concern specific to this study.** Criticality is partly computed from commit
  and contributor activity. Ranking on it is not a capacity quantity in this
  programme's sense — nothing TAVONEL measured — but it is closer to the axis
  under test than SourceRank is, and a reader may reasonably say the universe was
  ranked by something correlated with the outcome. Worth stating plainly if this
  candidate is chosen.

### C. Debian archive `Sources` index via `snapshot.debian.org`

Debian's own source-package index, retrieved from the Debian archive snapshot
service, which serves immutable timestamped states of the archive.

- **Independence.** The strongest of the three. Inclusion in Debian is decided by
  Debian's ftp-masters under the Debian Free Software Guidelines, by a process
  that is public, adversarial and entirely outside this study.
- **Pinnability.** Excellent. Snapshot URLs are timestamped and the archive's
  indices are already hash-addressed.
- **Field fit.** Weakest. There is **no repository-level ordinal**, so a ranking
  would have to be declared by TAVONEL — either an arbitrary-but-external total
  order (e.g. byte order of the source package name) or a second dataset such as
  the Debian popularity contest. An arbitrary external order is defensible on
  outcome-independence grounds and indefensible on relevance grounds; a second
  dataset means two universes.
- **Second problem.** `Vcs-Git` frequently points at Debian *packaging*
  repositories rather than upstream, and packaging repositories are not the
  documentation corpus this study is about.
- **Licensing.** The index files are factual archive metadata; Debian's terms for
  them should be confirmed rather than assumed. Content in the archive is
  DFSG-free by construction, which is a genuine advantage for requirement 3.

## Recommendation, and the part that is blocked

**Proposed: A (Libraries.io Open Data), with C as the licence-safest fallback.**
A is the only candidate that gives the frame rule everything it needs from one
frozen file with one set of terms.

**BLOCKED, and not an agent's call:**

- *Which catalogue.* This is a scientific commitment about what "the universe of
  documented software" means, and it will be argued about when SFIR7 reports.
- *Whether A's share-alike terms permit publishing a derived roster* in this
  programme's receipts under this programme's usual terms.

Both are founder decisions. The charter records `catalog_id:
PENDING_FOUNDER_DECISION`, and `design_freeze_state.frozen: false` with these two
items named as the blockers. Everything else in SFIR7's design is complete and
independent of the answer: `tools/sfir7_frame.py` takes `catalog_id`,
`snapshot_sha256` and `snapshot_date_utc` as parameters, so the rule is already
written and already controlled whichever catalogue is chosen.

## Three things this note is careful not to do

- It does not name a DOI, a version string or a file size from memory. Those go
  into the charter at acquisition time, from the page, with a digest.
- It does not read as a licence clearance. Attribution is easy; share-alike over
  a derived roster is not, and "probably fine" is not a finding.
- It does not choose the catalogue that would produce the most repositories. The
  ranking above is by independence and field fit. The eligible pool size is not a
  selection criterion for the catalogue, for the same reason it is not one for N.
