# `EXP-0103` dataset contract — the structured-filing arm

*Written 2026-08-12 against `9e3a793`. Closes the dataset gap Contract C names
and this repository has not built.*

**This is a contract, not code and not a performance claim.**
**NOT CLEARED FOR EXTERNAL DISCLOSURE.**

**Retrieval does not start until this is closed.** The synthetic fixture built
in `research/experiments/EXP-0103/` is approved and is **not** sufficient to
draw a production-ready conclusion from. 216 generated gold queries whose
lexical overlap with their own gold evidence is cleaner than any real corpus
cannot decide an adaptive-k cutoff that will be trusted in production.

---

## 1. The two roles, and why they must not merge

| fixture | role | may be used for | may **not** be used for |
|---|---|---|---|
| **Synthetic controlled** (`amgr-1`, built) | development and calibration | building the retriever, choosing K_MIN/K_MAX, tuning the cutoff estimator, debugging, unit tests | any reported result, any comparison between arms, any public number |
| **Public structured filing** (this contract, unbuilt) | **holdout and evidence** | the reported CURRENT vs baseline vs challenger comparison, once and once only | any threshold fitting, any cutoff estimation, any prompt or config selection |

Batch 1 §0.9 governs the second: access is receipted, and **editing a policy or
threshold after seeing holdout labels requires a new policy version and a new
holdout.** A burned holdout does not come back.

The failure this table prevents is the ordinary one — calibrate on the real data
because it is more realistic, then report on it. That produces a number nobody
can defend.

## 2. Execution order — binding

```
1. SEC XBRL deterministic fact extraction
2. OpenDART structured fact extraction
3. Query / gold-evidence generation
4. Cross-tenant probe validation
5. Frozen manifest
6. CURRENT vs baseline vs challenger
```

Step 6 does not begin before step 5 is receipted.

## 3. What a prior-art and API scan established, and what it did not

A `researcher` pass on 2026-08-12 produced the grounding below. It is reported
with its confidence markers because **the crux question came back unanswered**,
and a contract written as if it had been answered would be the worse outcome.

### 3.1 Verified — read directly

- **OpenDART single-company key accounts.** `GET
  https://opendart.fss.or.kr/api/fnlttSinglAcnt.json`, parameters `crtfc_key`,
  `corp_code`, `bsns_year`, `reprt_code`. Returns `rcept_no`, `bsns_year`,
  `stock_code`, `reprt_code`, `account_nm`, `fs_div` (OFS/CFS), `fs_nm`,
  `sj_div` (BS/IS), `sj_nm`, `thstrm_*`, `frmtrm_*`, `bfefrmtrm_*`, `ord`,
  `currency`. Source: OpenDART guide `apiGrpCd=DS003&apiId=2019016`.
- **OpenDART original document.** `GET
  https://opendart.fss.or.kr/api/document.xml`, parameters `crtfc_key`,
  `rcept_no`. Returns a **ZIP of the original filing**, not structured JSON.
  Source: guide `apiGrpCd=DS001&apiId=2019003`.
- **OpenDART terms.** FSS holds copyright in the API; the filing itself belongs
  to its submitter; FSS does not warrant accuracy; statistical, promotional and
  **academic research** use is permitted as an exception. No explicit
  redistribution prohibition was found. Source: `opendart.fss.or.kr/intro/terms.do`.
- **Adjacent datasets.** FinRank (SEC 10-K/10-Q, 1,185 QA, evidence located by
  **manual page reference**, CC BY-NC 4.0) and DartLab (DART + EDGAR Parquet,
  CC BY 4.0) exist. FinQA is CC BY 4.0.

### 3.2 Not verified — and one of them is the crux

- **Every SEC primary source returned HTTP 403** in that session.
  `sec.gov/edgar/sec-api-documentation`, `data.sec.gov` responses, the webmaster
  FAQ and the XBRL Guide PDF were all unreadable. Everything about
  `companyfacts` / `companyconcept` / `frames`, the Financial Statement Data
  Sets, the declared-User-Agent requirement, the request-rate limit and the
  iXBRL mandate dates is therefore **second-hand**, from wrappers and law-firm
  summaries that agree with each other — which is weak evidence, because they
  may be citing one another.
- **The crux is unanswered.** Whether an official mapping exists from a fact in
  `companyfacts` to a **location in the rendered filing** — byte range, element
  id, page — or whether it must be recovered by parsing the iXBRL document, was
  not established. The inline-XBRL `id` attribute is reportedly optional.
- **No existing research dataset was found** that binds XBRL structured facts to
  evidence spans automatically. FinRank, the closest, labels evidence **by
  hand**.
- OpenDART's documented daily request limit is **contradictory** across sources
  (10,000 vs 20,000).
- Whether a Korean inline-XBRL equivalent anchors a fact to a document location
  is unknown.
- No primary-source text was obtained on SEC redistribution terms or on the
  boundary between the US government's work and the filer's copyright in the
  filing text.

### 3.3 What follows from that

**Contract C's §31.4 premise — "automatic truth from SEC XBRL and OpenDART
structured facts" — rests on a fact-to-span binding that nobody has shown us
exists, and that no dataset we found has achieved automatically.** The premise
may still be sound. It is not yet established, and building an extractor on the
assumption that it is would produce gold labels whose provenance is a guess.

## 4. Precondition — `INTAKE-0103`, blocking

**`INTAKE-0103` closes before any extraction code is written.** Not before it is
merged, before it is *written*.

Establish, in this order, each from the primary source:

1. **Direct SEC primary-source access.** The 403s are an **environment problem,
   not a retry problem.** Do not loop on them: obtain an unblocked environment,
   or record that the step is blocked on one and stop. A summary of a summary is
   not this step's output.
2. **Official `companyfacts` / `companyconcept` / `frames` fields** — exact
   endpoint, exact record shape, read from `data.sec.gov` itself.
3. **The User-Agent requirement**, as SEC states it.
4. **The official rate limit**, as SEC states it.
5. **Redistribution and data-use terms**, for the data *and* for the filing text,
   which are not the same question. Batch 1's rule holds: an open-data licence on
   an API is not permission for the document text it returns.
6. **Whether an *official* mapping exists from a structured XBRL fact to its
   evidence location in the rendered filing.** This is the one the fixture
   depends on and it is answered in writing, with a citation, as one of the three
   outcomes in §4.1.

Then, for Korea:

7. **OpenDART's daily rate limit resolved against its official page.** The
   sources currently disagree (10,000 vs 20,000) and the fixture's request budget
   depends on which is right.
8. **The full-financial-statement (multi-account) endpoint** identified, or
   recorded as absent.

Use the `researcher` agent. It is a lookup task; its output is findings.

**Anything still `UNVERIFIED` when `INTAKE-0103` closes is named in the manifest
as unverified.** Writing it down a second time does not promote it.

### 4.1 The three outcomes of question 6, and what each triggers

| outcome | what happens |
|---|---|
| **An official mapping exists** | name and cite it; the binding is derived from it |
| **No official mapping; iXBRL anchors exist** | **measure anchor coverage** by parsing iXBRL on a real sample and publish the share of facts carrying a usable anchor. Coverage is a number, not an assumption |
| **Neither is reliable** | §5.2's located-span fallback becomes the design, and Contract C's "automatic truth" language is corrected rather than left standing |

### 4.2 Forbidden

> **Storing an inferred gold evidence location is forbidden.**

A guessed anchor is worse than an excluded one: an exclusion is visible in the
denominator and correctable, while a guess is indistinguishable from evidence
and silently inflates every recall computed against it. This is the repository's
existing rule — no fabricated bbox, no inferred location stored as fact — applied
to the case that most tempts a violation.

## 5. Extraction

### 5.1 Determinism

A fact record is `(source, filer id, period, taxonomy tag, unit, value, filing
id, retrieved_at)`. **`value` stays a string.** The filing's own rendering of a
number is what the document says; reparsing it to a float normalises away the
thing an exact-evidence query is meant to match.

Every extraction run is receipted: source, endpoint, request parameters, response
digest, retrieval timestamp. **A cached response is what is hashed**, so the
fixture is reproducible after the upstream changes — which it will.

### 5.2 The fact-to-evidence binding, and its fallback

The gold evidence for "what was X in period P" must be **a region of the filed
document that states it**, not the API record. The API record is the *truth*; the
document region is the *evidence*.

Per §4.1, in order of preference:

1. **Official mapping** — the binding is derived from it, and the fixture records
   per query how it was derived.
2. **iXBRL anchors** — coverage measured and published; facts without a usable
   anchor fall to 3.
3. **Located spans** — the fact value is matched against the rendered document
   text, and **only an exact, unambiguous single match becomes gold**. Ambiguous
   and unmatched facts are **excluded and counted**. **The exclusion rate is
   published with the fixture**, because one that silently drops the hard half
   reports an inflated recall.

**Storing an inferred gold evidence location is forbidden** (§4.2). A guessed
anchor is worse than an excluded one.

### 5.3 Tenancy

Real filings have no tenants. Filers are mapped to synthetic tenants under a
recorded, deterministic assignment, and the cross-tenant probe construction that
already works on the synthetic fixture — every ordered tenant pair crossed, each
probe answerable in the tenant that owns it — is applied unchanged.

**The unauthorized candidate rate stays a hard gate at zero, not a statistic.**

## 6. Metrics

Contract C's list, unchanged, each with its denominator: recall@budget ·
critical evidence recall · version-correct recall · **unauthorized candidate rate
= 0** · context tokens · latency p50/p95 · downstream QA/citation accuracy under
one frozen LLM and configuration.

Reported **separately for the synthetic and the filing arm.** A pooled number
would let the easy corpus carry the hard one.

Statistics: paired per query, Wilcoxon signed-rank with bootstrap CI. The
unauthorized rate is not a statistic.

## 7. What is still blocked

- **Downstream QA needs an API credential.** Credential-gated; the retrieval
  metrics run without it.
- The **visual page lane is excluded from this batch** by Contract C.
- `ENTITY`, `RELATION` and `IMPACT` intents and `PARAGRAPH` granularity are
  declared in the synthetic fixture and **not exercised** — they need an entity
  or dependency graph over the units, which does not exist.

## 8. IP linkage

Ledger entry **`ABS-B-02`** (Contract C). This contract fills its dataset field
and moves no gate. `tech_smartchunk` stays **YELLOW / `CLEAN_ROOM_ONLY`**;
adaptive-k upstream stays **intake-required and blocked from dependency use**.

**Filing and publication timing is the founder's alone.**

---

## Acceptance

1. The two fixture roles are stated, with the calibration/evidence boundary and
   §0.9's holdout rule.
2. The execution order is binding and retrieval is last.
3. Verified and unverified findings are separated, and the unverified crux is
   named as such rather than assumed.
4. `INTAKE-0103` closes before extraction code is *written*, its steps are
   ordered, and it names the three outcomes the binding question may have.
5. A fallback exists for the case where automatic binding is impossible, and it
   excludes-and-counts rather than guessing. **Storing an inferred gold evidence
   location is stated as forbidden.**
6. The SEC 403s are recorded as needing an unblocked environment rather than a
   retry.
6. Every metric carries its denominator; arms are reported separately.
7. The unauthorized candidate rate is a gate at zero, not a statistic.
8. No number in this file is a measurement.
