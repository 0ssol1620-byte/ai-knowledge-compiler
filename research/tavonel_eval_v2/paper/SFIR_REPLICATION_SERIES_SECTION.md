# The SFIR replication series: a completed measurement, a repair under an unchanged frame, and a new frame question

**INTERNAL DRAFT — NOT FOR RELEASE.** IP gate CLOSED. This is a drop-in section
for later integration into `paper/TAVONEL_PAPER_DRAFT_INTERNAL.md`. It does not
edit that draft, and it does not edit `paper/CLAIM_MATRIX.yaml`; proposed claim
rows are marked `[CLAIM-PENDING]` inline for the programme that owns those files.
It extends §10.4, which reports SFIR5 alone.

**This section was written while SFIR6's census was executing and no SFIR6
number existed.** Every place an SFIR6 quantity belongs carried the literal
marker `[SFIR6-RESULT-PENDING]` until the census returned; each has since been
resolved from `receipts/sfir6-capacity-outcome.json` and
`receipts/sfir6-capacity-census-seal.json` and from nowhere else, and no
sentence around them was rewritten to suit what they turned out to say. That
ordering is deliberate and is part of the method rather than an accident of
scheduling: a Methods section written after seeing a result is not the same
document as one written before, and the difference is not recoverable by
resolving to be careful. The same discipline
produced the two artifacts this section leans on hardest — INC-V2-108, which
registers four live instrument defects before SFIR6 could return, and the SFIR7
charter, which was designed without reading a result that did not yet exist.

Three studies are described here and they are **not three attempts at one
thing.** SFIR5 is a completed capacity measurement. SFIR6 is an instrument
repair under an explicitly unchanged frame. SFIR7 is a different scientific
question about how the frame was constructed. Collapsing them into "the git
study, take three" would be the single most damaging misreading available, and
the charters are written to make it hard.

---

## A. SFIR5 — the first completed census, and the instrument defect it exposed

SFIR5 is the first instrument in this programme to complete a capacity census
and have the criterion evaluated against it. SFIR1 through SFIR4 each stopped
upstream; SFIR4's stop receipt records `scientific_threshold_evaluated: false`.

The criterion is pre-registered and requires **every** family: `C_f ≥ 750` and
`Q_f ≥ 600`, with `Q_f = min(1000, floor(0.8 · C_f))`
(`receipts/sfir5-capacity-outcome.json`). The three declared families returned
three different kinds of answer, and the distinction between the kinds is the
result.

| family | roots declared | roots COMPLETE | C | Q | verdict | is this a measurement? |
|---|---|---|---|---|---|---|
| `regulation_ecfr` | 50 | 49 | 859 | 687 | `MEETS_CRITERION` | yes |
| `git_docs` | 20 | 13 | 293 | 234 | `SHORTFALL_MEASURED` | yes |
| `encyclopedia_wikipedia` | 30 | 1 | — | — | `NOT_MEASURED_INSTRUMENT_DEFECT` | **no** |

**`regulation_ecfr` is a valid capacity measurement and it passes.** Forty-nine
of fifty roots enumerated to exhaustion; the remaining reserved title carries no
versions at all, and its zero is the one zero in this census that genuinely means
an empty corpus.

**`git_docs` is a valid capacity measurement and it fails.** Thirteen of twenty
roots enumerated to queue exhaustion and seven hit declared tree-traversal bounds
and were excluded as the charter requires. No root reached its per-root candidate
cap of 80 — the highest returned 73 — so 293 is not an artifact of the cap. It is
what the declared frame yields under the declared bounds.

**`encyclopedia_wikipedia` was not measured, and its zero is not a capacity
statement.** Twenty-nine of its thirty roots were filed
`TRUNCATED_OR_INCOMPLETE_ENUMERATION`. The adapter supplies fifty page ids
together with `rvlimit=2`; MediaWiki answers `invalidparammix`, because that
parameter may only be used on a single page. Every revision request the
programme has ever issued to that endpoint has been refused, and no Wikipedia
candidate has ever been produced by any SFIR study (INC-V2-106). The response
evidence shows the shape without any new traffic: sixty requests across thirty
roots, exactly two per root, and a 611-byte response returned for fifty page ids
and again for twenty-five. A response size independent of how much was asked for
is an error envelope, not data.

Recording that family as `C = 0` beside `git_docs`'s 293 would have been the
worst false negative available here: a broken instrument's silence presented as a
measured absence, and a criterion that appeared to have been evaluated on three
families when it was evaluated on two. The receipt states in its own field that
nothing in this programme establishes that family's capacity **in either
direction**.

**SFIR5 is closed, is not rescored, and its numbers are not copied into any
successor.** Both successor charters restate its per-family verdicts explicitly
so they cannot be quietly superseded, and both declare that its numbers are not
carried into them. A later study that passes does not convert this failure into a
pass; it stands as the measurement of the frame that was declared at the time it
was declared.

[CLAIM-PENDING: bind to `receipts/sfir5-capacity-outcome.json`. The claim stays
narrow — the declared frame did not meet a pre-registered capacity criterion on
the two families that were measured. It is not a claim about Wikipedia, and not
a claim that the frame could not be made to meet it.]

---

## B. SFIR6 — a confirmatory repair under an unchanged frame

SFIR6 exists because two defects in SFIR5's instrument were **unconditional**,
and that word carries the whole argument.

A defect is unconditional here if it was wrong for every possible input — if no
data, however favourable, could have made the code behave correctly. Neither of
SFIR6's two repairs is therefore a value chosen by looking at SFIR5's outcome,
and that is what separates a repair from a redesign that has learned the answer.

- **INC-V2-106.** The MediaWiki request combined multiple page ids with
  `rvlimit`. MediaWiki refuses that combination for every input, on every run of
  every study. It is replaced by the officially supported two-pass form:
  batched latest revisions with no `rvlimit`, then batched parent revisions by
  `revids`. The population and the ordering are unchanged; only the request
  grammar moves.
- **INC-V2-107.** The capacity seal compared the pagination block by strict set
  equality against a field set that this study's own earlier repair had widened.
  The seal would therefore have refused **every** census, for every family,
  whatever the data said. The instrument could not have produced a capacity
  authority even from a perfect run.

That INC-V2-107 does not explain SFIR5's failure was established by running it
rather than by arguing it: the field set was corrected in memory only, the seal
re-run against the same sealed census, and the refusal became
`encyclopedia_wikipedia capacity shortfall` — the criterion reached, and not met.
The frozen module on disk was not edited, and `git diff` confirms it. This
matters because the defect would otherwise have been an extremely convenient
explanation for a disappointing result.

**Everything that could have made SFIR6 outcome-conditioned is declared
unchanged** and is enumerated in the charter rather than described: 20 git roots,
50 eCFR roots, 30 Wikipedia roots; a minimum `C` of 750 and a minimum `Q` of 600
per family; the quota formula; per-root caps; the selection salt; the selection
ordering; the inclusion and exclusion rules; the identity semantics; the scorer;
the acceptance logic; the scientific endpoints. The charter carries one field
whose only purpose is to foreclose the most tempting move available after seeing
293: `no_git_root_is_added_after_seeing_293: true`. Its verdict policy is equally
blunt — `if_git_fails_again_the_criterion_fails: true`, and lowering a threshold
or adding a root on failure is forbidden.

The one thing SFIR6 adds is a gate SFIR5 did not have, and it is kept as its own
section of the charter because the lesson is structural rather than
Wikipedia-specific: transport success is not protocol success is not semantic
completeness. Its independent oracle runs against envelopes captured from the
live endpoint **before the adapter was written**, not against the adapter's own
model of the API, and the charter states outright that predecessor equivalence
may not be used as a correctness argument.

The repaired grammar was verified against the live endpoint before the charter
was frozen (`receipts/sfir6-adapter-canary.json`). The canary used three pages
that are not among the thirty declared roots, and it is marked
`excluded_from_the_scientific_denominator: true`; its own note says the count of
pages yielding a pair "is not a candidate count and has no relationship to `C_f`
for any family". One of its four gates exists solely to demonstrate that the two
layers really are independent, live: it re-issues SFIR5's request shape and
records `transport_status: 200` together with `protocol_layer_refused: true` in
the same response.

**Result: `CAPACITY_CRITERION_APPLIED_AND_FAILED`, and it fails on
`git_docs`** (`receipts/sfir6-capacity-outcome.json`, over the census sealed at
`receipts/sfir6-capacity-census-seal.json`). All three families were re-measured
and no family result was reused from SFIR5; the receipt states in its own
`predecessor` block that SFIR5's counts appear there only as a comparison target
and that every figure in its `families` block was computed from SFIR6's own
census.

| family | roots declared | roots COMPLETE | C | Q | verdict | sealable? |
|---|---|---|---|---|---|---|
| `regulation_ecfr` | 50 | 49 | 859 | 687 | `MEETS_CRITERION` | yes |
| `git_docs` | 20 | 13 | 293 | 234 | `SHORTFALL_MEASURED` | yes |
| `encyclopedia_wikipedia` | 30 | 29 | 2,152 | 1,000 | `MEASURED_NOT_SEALABLE` | **no** |

**`git_docs` reproduces SFIR5 not merely in count but in identical lineage set.**
The two censuses' candidate lineage sets were compared as sets rather than as
counts: 0 lineages in SFIR5 only, 0 in SFIR6 only. Equal counts could coincide;
equal sets could not. The same holds for `regulation_ecfr` at 859. That is what
makes 293 a **twice-measured** shortfall rather than two observations that
happen to agree, and it is also the control on the repair: the two families the
repair was not aimed at ran through the inherited code path and returned the
same corpus, so SFIR6's Wikipedia number is not confounded by a transport that
quietly moved underneath them.

**The INC-V2-106 repair worked, and this is the first Wikipedia measurement the
programme has ever had.** Twenty-nine of thirty roots are `COMPLETE` with the
reason `CATEGORY_CONTINUATION_EXHAUSTED_AND_PAIRS_RESOLVED`, against 29 of 30
filed `TRUNCATED_OR_INCOMPLETE_ENUMERATION` in SFIR5 — and C = 2,152 where no
candidate had ever been produced by any SFIR study. The thirtieth root
enumerated and yielded no revision pair; that is an honest `ZERO_CANDIDATE`, the
kind of zero SFIR5's twenty-nine were not. Note that this family's Q of 1,000 is
the `min(1000, …)` term binding for the first time in the series and not
`0.8 · C`: floor(0.8 · 2,152) is 1,721.

**And the family is `MEASURED_NOT_SEALABLE`, which is a fourth kind of answer
this series had not previously needed.** Its set was enumerated but could not be
certified: the identity proof refused it, four aliases out of 9,887 each being
claimed by two lineages (INC-V2-109, below). So C = 2,152 records what the
repaired instrument enumerated and is **not** a sealed capacity. Nothing in this
receipt establishes that `encyclopedia_wikipedia` meets the criterion or that it
misses it — the `meets_C` and `meets_Q` flags in its family block are computed
over a set the seal declined to certify, and are not a verdict.

**None of that changes the outcome.** The criterion requires every family, and
`git_docs` fails it on a candidate set identical to the one that failed it in
SFIR5. The charter's `if_git_fails_again_the_criterion_fails: true` is the field
that was written for exactly this, before the number existed. No threshold was
lowered, no root was added, and no view of the Wikipedia family can change the
verdict.

**Census transport, from the seal.** 3,198 requests — `api.github.com` 2,043,
`www.ecfr.gov` 1,011, `en.wikipedia.org` 144 — against a frozen cap of 12,000,
in 3,029.174 seconds of wall clock of which 1,150.952 were spent pacing, under a
frozen cap of 21,600 seconds. 0 GPU seconds and an estimated cost of $0 (`gpu_seconds: 0`,
`estimated_cost_usd: 0.0`), as with every receipt in this series. The Wikipedia lane's 144 requests against SFIR5's
60 are the two-pass grammar's second pass, which SFIR5 never got to issue.

**Nothing downstream ran.** The receipt records
`acquisition_started: false`, `roster_frozen: false`, `payload_opened: false`
and `corpus_spent: false`, on the authority of the charter's
`terminal_policy: no_roster_or_acquisition_on_capacity_shortfall`. A capacity
shortfall stops the study at the census; it does not proceed to spend a corpus
on a frame that did not clear the bar.

[CLAIM-PENDING: bind to `receipts/sfir6-capacity-outcome.json`. Two separable
rows. First, that a repaired instrument reproduced a predecessor's candidate set
exactly — identical lineage sets on two of three families — which is a claim
about replication and not about capacity. Second, that the declared frame failed
the same pre-registered criterion a second time on `git_docs`. Neither row may
cite `encyclopedia_wikipedia`'s C as a capacity figure, because its set was not
sealed.]

### B.1 — INC-V2-109: the defect the first measurement bought

The seal refused `encyclopedia_wikipedia` with a namespace collision on
`wiki:en:title:cd8+`, claimed by two lineages at once. Four aliases out of 9,887
collide across the 2,152 candidates, and all four have the same single cause:
**TAVONEL's alias identity case-folds the whole MediaWiki title, and MediaWiki
titles are case-sensitive after the first character.**

| collapsed alias | one page | the other page |
|---|---|---|
| `cd8+` | `CD8+` → Cytotoxic T cell | `Cd8+` → CD8 |
| `emergency surgery` | `Emergency Surgery` → Surgery | `Emergency surgery` → Elective surgery |
| `communication systems` | `Communication Systems` → Telecommunications | `Communication systems` → Communications system |
| `telecommunication systems` | `Telecommunication Systems` → Communications system | `Telecommunication systems` → Telecommunications |

Each was confirmed against the live API rather than inferred. Resolving `CD8+`
returns exactly one target — `{"from": "CD8+", "to": "Cytotoxic T cell"}` — which
is the point: every one of these redirects is unambiguous *in the source*. The
ambiguity is manufactured downstream.

**It is not the corpus and it is not the adapter.** Every batch in the census
returned `batchcomplete`, with no continuation and no warnings. Transport,
protocol and semantic completeness all passed. The defect is in our
normalisation, one layer further in than any gate SFIR6 was built to add — which
is why the receipt's own `whose_defect` field says "ours".

**It was not repaired, and the refusal is correct behaviour.** Three independent
reasons, any one sufficient: SFIR6's charter freezes `identity_semantics:
unchanged`; `akc_cir.identity` is Protected Core and cannot change without a
same-condition no-regression benchmark; and the outcome was already known by the
time the collision surfaced, so changing an identity rule at that point would be
outcome-conditioned by construction, whatever its merits. Beyond the procedural
reasons, failing closed here is the behaviour the system is supposed to have: an
authoritative conflict on insufficient evidence must not be auto-resolved, and it
was not. A study that quietly merged `CD8+` with `Cd8+` to obtain a sealable set
would have reported a larger number and a worse result.

**The general point is the one worth carrying past this study: repairing one
instrument exposed a defect in a different layer.** INC-V2-109 was not missed by
four studies through inattention — it was **unreachable**. `encyclopedia_wikipedia`
had never produced a candidate, so the identity proof had no Wikipedia input to
run on at all. The defect sat behind INC-V2-106 and could only surface once
INC-V2-106 was fixed. That `git_docs` and `regulation_ecfr` aliases do not
collide under case-folding is a property of those two corpora, not evidence that
the rule is safe.

This is the ordinary way a first measurement pays for itself, and it is an
argument for the same thing §E argues from the other direction: a defect upstream
of every previous stop is a defect no previous stop can reveal, and the corollary
is that **completing a run buys defects in layers the run was not aimed at.**
INC-V2-110 arrived by the same route in the same census — a third instance of
INC-V2-107's strict-set-equality class, this time refusing the repaired Wikipedia
adapter for carrying *more* evidence than the schema allows. It is recorded and
not repaired because it is not load-bearing: removing the extra proof lets the
seal proceed and it then refuses on INC-V2-109 instead.

[CLAIM-PENDING: bind to `incident_ledger.md` INC-V2-109 and to
`receipts/sfir6-capacity-outcome.json`'s `defects_found_by_this_census`. The
claim is about the programme's own normalisation and about fail-closed refusal;
it is not a claim about MediaWiki, and not a claim that the identity rule is
wrong everywhere — only that it is wrong for case-sensitive title namespaces.]

---

## C. SFIR7 — an independently predeclared expanded-frame study, not a repair

SFIR5 and SFIR6 measure the same declared narrow git frame. Neither can separate
two very different explanations of a shortfall: that the **system** cannot
produce qualifying revision pairs at that density, or that the **frame that was
constructed** does not contain them. SFIR7 evaluates the second explanation, by
applying the same unchanged instrument, scorer and acceptance logic to a universe
TAVONEL does not curate.

It is not an instrument repair, not a rerun of SFIR5, and not a rerun of SFIR6.
Its charter says so in a section whose only job is to say so, because that is the
sentence most likely to be lost. Two universes producing different capacities is
the finding, not a contradiction to be resolved in favour of the larger number.
And the asymmetry is stated in advance: a pass would mean the narrow frame
under-covered, and would **not** validate the system at the narrow frame; a
failure would mean that broadening coverage under an externally defined universe
does not lift the yield, which is a far stronger statement about the system than
any narrow-frame result could be.

Four design commitments make the roster outcome-independent, and each is
implemented as a refusal rather than a guideline.

1. **The universe is externally defined, and it is now named.** Inclusion is
   decided by a third party's published catalogue: the **Libraries.io Open
   Source Repository and Dependency Metadata, version 1.6.0**, DOI
   `10.5281/zenodo.3626071`, deposited 2020-01-12 — a dated, immutable dataset
   that existed years before SFIR5 and SFIR6 and could not have been chosen for
   what it would yield. It publishes a stable repository identifier, its own
   ordinal, creation and update timestamps, language and licence, which is
   everything the frame rule needs from one frozen file and nothing TAVONEL
   computed. The snapshot is pinned by URI and by a sha-256 over working-tree
   bytes, with the digest determined by byte counting rather than a shell
   line-ending grep (INC-V2-105); a snapshot whose bytes do not match its digest
   is refused. Its identity and its licence terms were **not an agent's call**
   and both were settled by founder ruling on 2026-08-27 — the licence
   conservatively, because the Zenodo record's metadata says CC BY 4.0 while
   Libraries.io states share-alike terms, and SFIR7 operates under the stricter
   reading with the discrepancy recorded rather than resolved. Which one governs
   is a legal question, not an agent's.
2. **Four eligibility predicates over catalogue-published fields only.** Host is
   `github`, because the inherited adapter addresses one host and changing hosts
   would confound the frame question with an instrument change; the SPDX licence
   identifier is one of ten fixed before the snapshot was taken; creation is at
   least 1,095 days before the snapshot date, so a repository has a revision
   history at all; last activity is within 365 days, so the universe is live
   software rather than an archive. A predicate naming a field outside the
   catalogue record is refused, and so is a predicate whose stated reason names a
   capacity term. Documentation-file eligibility is deliberately *not* a
   catalogue predicate, because a catalogue does not know what is in a tree.
3. **Ranking uses the catalogue's own published ordinal, descending, verbatim**,
   tie-broken by the catalogue's own stable record identifier. Ties the
   tie-breaker cannot settle are refused rather than resolved. TAVONEL may not
   recompute popularity or yield and call the result a rank: a rank TAVONEL
   recomputed would be a TAVONEL judgement wearing an external catalogue's name,
   and the independence of the frame rests entirely on the ordinal having been
   decided by someone else before this study existed. Ranking on any quantity
   TAVONEL measured is a forbidden act.
4. **N is derived, not chosen — and it was revised downward.**
   `N = floor(min(wall_clock_hours · published_rate_limit_per_hour,
   inherited_total_request_cap) / per_root_request_bound)`, which under the
   currently inherited bounds is `floor(min(6 · 5000, 12000) / 240) = 50`. Three
   of the four inputs are bounds inherited unchanged from SFIR4, SFIR5 and SFIR6
   and read live from the modules; the fourth is a vendor's published figure.
   None of them moves when a census disappoints, and the arithmetic leaves no
   free parameter. A hand-set N is refused, and an N whose declared inputs have
   drifted from the live bounds is refused. The justification may not cite the
   capacity minimum or any predecessor measurement. The published rate limit is
   also treated as an upper bound on requests issued and not as a throughput
   guarantee — GitHub enforces secondary limits, and planning a census on 5,000
   per hour sustained would plan one the endpoint will not serve.

The charter also lists the acts it forbids, as acts rather than as values:
adding repositories one at a time until a count clears a threshold; removing or
widening an eligibility predicate once the pool size is known; choosing N by
reference to what would clear the minimum; re-drawing the frame after a census
and reporting only the second draw; and treating a short eligible pool as a
defect to be repaired rather than reported. That SFIR7 may still come up short at
this N, and that a short result is reported rather than repaired, are fields in
the document.

**SFIR7 was designed while SFIR6 was still blind.** The charter records SFIR6's
result as `NOT_YET_IN_EXISTENCE` and states that the charter was designed without
reading it. That is not decoration: the root-selection rule is outcome-
independent only if it was computable before SFIR6's census existed, and it was —
every input is either an external catalogue's published field or a bound
inherited from a predecessor, and no part of the rule can be evaluated against a
capacity quantity.

**The one blocking conflict was resolved by tightening rather than by raising,
and that direction is the methodological point.** It was registered on the blind
footing above: the first draft derived N from the wall clock alone and produced
N = 125, which at a per-root bound of 240 requests implies a worst case of 30,000
requests against an inherited cap of 12,000 — an acquisition that refuses at
request 12,001 part way through the roster, producing a partial census rather
than a measurement. Two honest resolutions existed. Raising the cap to 30,000
would have been a budget expansion decided after SFIR6 returned a shortfall, and
no amount of documentation makes that outcome-independent. The founder ruling of
2026-08-27 took the other: the cap stays at 12,000 and N is derived from the
stronger of two constraints that both already existed, which needs no new number
at all. **N fell from 125 to 50.** A roster that shrinks cannot be suspected of
having been sized to reach a capacity figure; a roster that grows after a
disappointing predecessor always can, however good its stated reason. The
conflict block is kept in the charter rather than deleted, because the record of
what it was and how it was settled is the evidence that it was not settled to
suit a result.

**SFIR7 is still not frozen and no acquisition is authorised.** Two things
remain: the catalogue snapshot has not been acquired and its digest is not
pinned, and the selected roots have not been frozen. `frozen: false` and
`roster_frozen: false` are fields in the document. Every SFIR7 figure in this
section is therefore a **design** figure — a rule and its arithmetic — and not a
measurement; SFIR7 has produced no capacity number, and the charter states
outright that it may still come up short at N = 50 and that a short result is
reported rather than repaired.

---

## D. Limitations

**Four defects of the INC-V2-106 class are confirmed live in the git and eCFR
adapters, and they were registered before SFIR6's census returned.** That
ordering is the load-bearing fact about this subsection. A limitation registered
after a disappointing result is indistinguishable from an excuse for it; the same
limitation registered before the result cannot be one. The four:

- **eCFR files an HTTP 404, 409 or 451 as a corpus zero.** The probe returns
  `ZERO_CANDIDATE_ROOT_DISPOSITION` for a root the server refused. The identical
  status in `git_docs` returns `UNAVAILABLE_ROOT_DISPOSITION` — one census, one
  HTTP status, two incompatible meanings, with the correct state already present
  in the seal's allowed set.
- **eCFR files an unfinishable enumeration as a corpus zero.** Five distinct
  instrument failures — page bound, byte bound, `meta` drift between pages,
  `rows_seen != result_count`, and two crawls disagreeing — all reach the same
  `ZERO_CANDIDATE`. The reason strings distinguish them; the state does not, and
  the state is what the arithmetic reads.
- **A git documentation path whose commit history returns `[]` disappears
  uncounted.** GitHub answers HTTP 200 `[]` for a path filter that matched
  nothing. A path read out of the HEAD tree in the same census cannot honestly
  have zero commits, so `[]` there is the API refusing the filter — yet it is
  dropped by the same `len(commits) < 2: continue` branch as a genuine
  single-commit file, and no proof field records it. A root where every path
  answered `[]` would seal as `COMPLETE` with zero candidates: the same false
  zero as INC-V2-106, arriving through `COMPLETE` instead of through
  `ZERO_CANDIDATE`.
- **Repository identity is never verified.** The metadata body is accepted if it
  merely carries a string `default_branch`; `full_name` is never compared against
  the repository that was asked for, and urllib follows GitHub's rename 301
  silently. Candidates could be attributed to a root naming a repository that
  does not hold them, and the static-disjointness check could not see it, because
  it compares declared names while the census reads redirect targets.

**Magnitude, measured rather than assumed.** Counted over the 100 sealed root
dispositions in SFIR5's census — 50 eCFR, 20 git, 30 Wikipedia — the eCFR
conflation **never fired**. `regulation_ecfr` shows 49 `COMPLETE` and one
`ZERO_CANDIDATE` carrying `EMPTY_ENUMERATION_NO_VERSIONS`, the one reason that
genuinely means an empty corpus; no eCFR root took a refused-or-truncated path.
**eCFR's 859 is therefore not contaminated by these defects.** `git_docs` used
`EXCLUDED_INCOMPLETE` correctly for all seven bounded roots. Its exposure is the
uncounted `[]` history and the unverified identity, neither of which leaves a
trace in any receipt — which is precisely why they need counters in a successor
rather than reasoning in a paper.

**Direction of bias.** Filing a failure as a zero can only lower a capacity
count, never raise it. These defects therefore cannot inflate a passing family,
and a family that passes despite them has passed. They bound a **shortfall**, and
only a shortfall. **The repository-identity defect is the stated exception:** it
is a misattribution rather than a count error, and it can move candidates between
roots in either direction.

**SFIR6 is not amended for any of this.** It is frozen with
`repairs: [INC-V2-106, INC-V2-107]` and was executing when the four were
confirmed. They are unconditional and were found before its result existed, so
amending it would not have been outcome-conditioned — but it would still be an
edit to a sealed charter during the census that charter authorises, and a freeze
that can be widened mid-run is not a freeze. SFIR6 reports under its declared
scope with this entry as its named limitation.

**One reported finding was refuted, and the refutation is worth more than the
finding.** The same audit reported that only `git_docs` reaches the hash-chained
response ledger, because the sole call site of the observing wrapper in SFIR4's
probe is a git call site and the other two families go through the legacy fetch
path directly. That is true of **SFIR4's probe** and false of the transport that
executed SFIR5 and is executing SFIR6, whose subclass replaces the legacy closure
with one that observes. This is not an argument;
`receipts/sfir5-capacity-census-seal.json` records
`families_in_ledger: [encyclopedia_wikipedia, git_docs, regulation_ecfr]` and
`per_host_requests: {api.github.com: 1879, en.wikipedia.org: 60,
www.ecfr.gov: 1011}` across 2,950 requests. Had eCFR bypassed the ledger, its
1,011 requests would have left no rows and the family-coverage check would have
refused the census.

The finding was reasoned from the frozen module without reading the subclass that
overrides it. The general form is worth carrying: **an audit of an inherited
module is not an audit of the code that runs.** It is the mirror image of
INC-V2-036 — there, a guard was written where its failure was structurally
impossible; here, a defect was reported where the code alleged to contain it was
not the code being executed. Both are failures to check a statement against the
behaviour, and a hostile audit is not exempt from that requirement merely because
it is hostile.

**Two further limitations inherited from the programme's method.** First, the
capacity thresholds are **declared, not calibrated**: 750 and 600 are
pre-registered figures, and this series reports whether a frame clears them, not
that they are the right numbers. Nothing here should be read as a calibrated
result. Second, every figure in this section names its interpreter of record —
the repository's own virtual environment — because the bare `python` on this
machine resolved the core package from a different checkout and invalidated a
session's worth of measurements before it was caught (INC-V2-103).

---

## E. Methodological contributions

Two ideas produced by this series generalise past it, and both were paid for.

**1. Adapter gates are layered, and a success at one layer is evidence for no
other.** SFIR6's charter separates three, and INC-V2-108 adds a fourth:

| gate | question | failure the layer below cannot see |
|---|---|---|
| transport | did bytes arrive? | an error envelope arrives as bytes |
| protocol | did the API say yes? | MediaWiki returns `error`, `warnings`, `missing`, `invalid`, `badrevids`, or omits `batchcomplete`, all under HTTP 200 |
| semantic completeness | did we get what we asked for? | a batch answers for a subset and the subset seals as the whole |
| identity | is the thing that answered the thing we asked for? | a silent rename 301 answers for a different repository under HTTP 200 |

**HTTP 200 is a sufficient condition for none of them.** The Wikipedia lane
returned HTTP 200 on every request for four studies while every one of those
requests was refused at the protocol layer, and the SFIR6 canary demonstrates the
independence live rather than in a fixture: the same response carries
`transport_status: 200` and `protocol_layer_refused: true`. The fourth gate was
added because transport, protocol and semantic completeness can all pass on a
response from the wrong resource. The practical form of the rule is that each
layer needs its own counter in a receipt; a layer whose failures are only visible
in a reason string is a layer the arithmetic cannot read.

**2. Predecessor-equivalence is not correctness.** SFIR5's charter declared its
batching unchanged from the frozen adapter, and a pre-freeze gate verified the
declared sizes against that adapter. The gate passed, and it was doing exactly
what it was written to do. What it established is that the successor inherited
the predecessor's behaviour — and the predecessor's behaviour was an error on
every request it had ever made.

**A check that compares a successor to an ancestor cannot find a defect they
share.** This is the more uncomfortable of the two findings, because the gate was
working correctly the entire time and no amount of running it more carefully
would have helped. It belongs beside INC-V2-036's rule — *a guard placed where
its failure is impossible is not a guard* — as its inheritance-shaped case. The
corrective SFIR6 adopts is stated as a prohibition and an obligation together:
predecessor equivalence may not be used as a correctness argument, and the
independent oracle must run against envelopes captured from the live endpoint
before the adapter was written, so that the control cannot inherit the adapter's
model of the API.

A related structural point, and the reason SFIR5's completion mattered more than
its verdict: **a defect upstream of every previous stop is a defect no previous
stop can reveal.** Four instruments carried the Wikipedia lane without once
running far enough for its output to be looked at. That is an argument for
completing runs even when the outcome is expected to be negative, and for
treating a first-ever completion as an instrument event rather than only a
scientific one.

[CLAIM-PENDING: rows binding §D to `incident_ledger.md` INC-V2-108 and
`receipts/sfir5-capacity-census-seal.json`, and §E to the SFIR6 charter's
`adapter_gate_separation` block and `receipts/sfir6-adapter-canary.json`. The
three `[SFIR6-RESULT-PENDING]` markers are now resolved against
`receipts/sfir6-capacity-outcome.json` and
`receipts/sfir6-capacity-census-seal.json`, so §B's rows may bind — with one
standing exclusion that outlives this note: **no row may cite
`encyclopedia_wikipedia`'s C = 2,152 as a capacity figure.** That set was
enumerated and not sealed, and a claim resting on it would be a claim the
identity proof declined to certify.]

---

## F. Generated tables

The per-study capacity table and the incident table are generated artifacts, not
prose, and are rebuilt from receipts and from the ledger on every run of
`paper/build_paper_artifacts.py`:

- `paper/generated/table6_sfir_capacity_series.json` and its markdown rendering
  `table6_sfir_capacity_series.md` — capacity by study and family across SFIR5
  and SFIR6, each study read from its own outcome receipt, with SFIR6's
  set-versus-set replication comparison, the pre-registered-not-calibrated note
  on 750 and 600, and the denominator each `roots_complete` is counted over.
- `paper/generated/table7_sfir_incidents.json` and
  `table7_sfir_incidents.md` — INC-V2-106 through INC-V2-111, with each entry's
  own class and disposition, and a column separating the two that only the
  ledger records from the four a sealed receipt also names. Its denominator is
  every entry the ledger holds, so the six read as a named selection.

`paper/generated/reproducibility.json` pins both capacity receipts and the
ledger by sha-256, so a rebuild that reads different bytes surfaces as a manifest
disagreement rather than as a quietly different table.
