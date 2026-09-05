# FP-200 change receipt — a named gap, and what the chain did instead

Campaign `TAVONEL-CATEGORY-LEADERSHIP-20260905-V1`, lane `change-receipt`,
core commit `26bb8926334246bbc666d6cc5abbb7291dac53f1`.

The lane was asked for a deterministic, hash-bound receipt proving full-rebuild
equivalence for the FP-200 fixture — the maintenance manual at revision B and
revision C, the change notice and the service log — produced by the real core
chain. It was also told that if the chain cannot consume the fixture without
touching Protected Core, the deliverable is the gap, named exactly.

**That is what happened. There is no equivalence receipt. There are two gaps and
two findings, all four measured rather than argued, and `receipt.json` holds the
runs behind them.**

---

## The one-paragraph answer

The core's source resolver builds knowledge units only from printed clause
numbers under printed numbered headings. The FP-200 corpus is unnumbered prose.
All ten regions of the four documents resolve to `UNNUMBERED_PARAGRAPH` /
`UNRESOLVED_SOURCE_FACT`, no unit survives, and `resolve_sources` refuses with
`CORE_V3_NO_RESOLVABLE_UNIT` before a world exists. Restating the same sentences
under clause numbers gets through the resolver and to the end of the chain, and
the chain does not pass: the amended clause's identity lands in the declared
review band, two artifacts are quarantined, the revision is `review_required`
rather than promotable, and full-rebuild equivalence **fails** on two claims that
were carried forward with a stale bounding box.

So `ExploreChangeStory.equivalence` in the lane contract's §4.3 must stay
`not_yet`. Nothing in this directory may be wired into `/explore` as an
equivalence result, and there is no `PASS` to show.

---

## What is here

| Path | What it is |
|---|---|
| `receipt.json` | Every run, with digests. `deterministic` is byte-stable; `environment` is not and is excluded from the digest. |
| `build_receipt.py` | Drives the real core services and writes `receipt.json`. Compiles nothing itself. |
| `render_fixture.mjs` | Writes every file under `inputs/`, after proving it reproduces a PDF the site has already committed. |
| `inputs/` | The four site-form documents and the four clause-form ones, plus the OCR records fed to the core. |
| `test_explore_change_receipt.py` | Reproduces the receipt and re-derives its claims from the artifacts. |

The receipt digests itself. `deterministicSha256` is a sha256 over the canonical
JSON of the `deterministic` block and reads

    sha256:2a9606ca4e2114db0f9d1de61be2e12fdf63eeed73e2dfd38c477b62aa74e748

at this commit. `test_the_receipt_digest_is_over_the_receipt` recomputes it from
the bytes beside it and `test_the_receipt_is_reproduced_byte_for_byte` re-runs
the chain and compares, so a stale digest fails rather than sits there.

---

## Gap F1 — unit extraction

**Function.** `akc_core_v3.canonicalise_document`, in
`services/core-v3/src/akc_core_v3/sources.py`. The classification branches at
lines 457–495; the refusal is raised at line 576 by `resolve_sources`.

**Input shape it requires.** A region matching `_CLAUSE` — a number containing at
least one dot, then the clause body — beneath a region matching `_HEADING` — a
number, then a heading of at most 60 characters containing no full stop. The
clause number is the anchor identity travels on, which is the reason the rule
exists: it survives a re-typeset, and a positional identity would not.

**Input shape the fixture has.** Unnumbered prose. Not one region of
`fp-200-maintenance-manual-revC.pdf`, `fp-200-change-notice-CN-2026-03.pdf` or
`fp-200-service-log-2026.pdf` carries a printed clause number, and neither does
the revision-B manual built to the same description.

**What the run shows.** `receipt.json` → `runs[0]`. Ten regions in, zero units
out, one `UNRESOLVED_SOURCE_FACT` per region with the reason the canonicaliser
itself wrote, and `CORE_V3_NO_RESOLVABLE_UNIT` at 422.

**Why it was not closed here.** Closing it means changing how the production
resolver decides what a knowledge unit is. `sources.py` is owned by no lane in
this campaign, the rule it encodes is load-bearing for identity across
re-typesets, and widening it is an architecture decision with an ADR behind it —
not a research lane's edit. No file outside this directory was touched.

---

## Gap F2 — document identity across revisions

**Where.** `sources.py:498` — `logical_id = f"ku_{document_id}_{identifier}"`.
The document id is what carries a unit's identity across a revision, and every
artifact id is built from the logical id in turn.

**The mismatch.** The site publishes revision B and revision C as two files with
two document ids (`fp200-maintenance-manual-rev-b`, `…-rev-c`). The core models a
revision as one document id at two `contentSha256` versions. Handing it the two
ids describes a collection in which one manual was deleted and another appeared.

**What it costs, measured.** `runs[1]` and `runs[2]` differ in exactly this and
nothing else:

| | one id across both revisions | one id per revision |
|---|---|---|
| units continued | 9 | 9 |
| artifacts carried over | 17 | 15 |
| artifacts quarantined | 2 | 12 |
| equivalence | fails on 2 claims | fails on `collection:directory` |

The interesting half is that *identity survives the id change* — the resolver
matches on heading path and clause anchor, so nine units still continue — while
the **artifact layer does not**: every artifact of the manual is withheld, along
with the three collection projections that read every unit. Identity is
anchored on structure; artifact reuse is anchored on the document id. A caller
that changes the id keeps its lineage and loses its incremental compile.

---

## Finding F3 — a claim keeps its words and loses its box

This is the one worth reading twice, because it is a correctness finding and
nothing in the repository was asserting the opposite loudly.

`verify_equivalence` reported two artifacts as `stale_left_behind` in `runs[1]`:

    claim:ku_fp200-maintenance-manual_3_1
    claim:ku_fp200-maintenance-manual_4_1

Both were carried forward untouched. A full rebuild produces different bytes for
both. `runs[1].staleLeftBehindWitness` holds the two bodies side by side, and the
difference is entirely in the provenance:

    text        identical, byte for byte
    bbox1000    [111, 237, 744, 285]  ->  [111, 255, 744, 303]

The clause did not change. It moved, because the clause above it grew from one
line to two when the interval sentence gained its second half. A world at
revision C therefore holds a claim whose citation box points at where the clause
used to be.

**The mechanism, from the code rather than from the outcome.**

- `projections.py:230` — `channels[claim_id(unit)] = _SEMANTIC`. A claim declares
  itself sensitive to the semantic channel and to nothing else, so a locator
  change cannot reach it and it is never rebuilt.
- `projections.py:208–218` — the claim body embeds `unit.provenance()`: page,
  `bbox1000`, `evidenceId`, `regionId`. Every one of those is a locator field.
- `projections.py:66–71` — the comment states the intent plainly: a grounded
  chunk goes stale when the evidence moves, *"a claim does not, so it does not."*

The declaration and the body disagree. The module's own comment describes the
behaviour it wants; the body it builds does not have that property.
`retrieval:` gets this right — it declares `_GROUNDED`, which is semantic plus
locator plus visual — and `claim:` does not.

Two honest caveats on the evidence. The `evidenceId` and `regionId` in the
witness also differ, but that part is a property of this fixture: region ids are
named after the file they came from, and the two revisions are two files. The
**bounding box difference is not** — it is a real re-typeset, and it is enough on
its own. And this was reached through the clause-form restatement, so it is
demonstrated on a fixture rather than on a corpus.

**Not fixed here.** `projections.py` belongs to no lane in this campaign, and
changing an artifact's declared channel sensitivity changes what every
incremental compile rebuilds. Reported, not touched.

---

## Finding F4 — the identity layer abstained, as designed

The amended clause `2.1` came back `AMBIGUOUS` with a single candidate and the
reason:

> score 0.90 sits in the review band between 0.75 and 0.92

This is **not a defect.** `identity.py:252–256` declares `MERGE_THRESHOLD = 0.92`
and `NEW_IDENTITY_THRESHOLD = 0.75` as a bootstrap band, explicitly not a
calibrated operating point, and `CLAUDE.md` says no threshold in this repository
is calibrated and none may be moved to make a run pass. The amendment nearly
doubled the clause's length; 0.90 is the resolver saying so and declining to
merge a history on its own authority.

The consequence travels: `claim:` and `retrieval:` for clause 2.1 are quarantined
rather than rebuilt or reused, and the disposition is `review_required`. The
world a person would be offered here is one the compiler has already said needs
review. That is the state machine working.

---

## How it was produced

```
# 1. the inputs (needs the site checkout for the renderer fidelity check)
cd research/explore_change_receipt_20260905
OUT=$PWD/inputs \
SITE_PDFS=/d/CodexProjects/tavonel-saas-foundation/nextjs/public/explore-sample \
SITE_INPUTS=/d/CodexProjects/tavonel-saas-foundation/nextjs/lib/explore-sample.inputs.json \
PDFJS=D:/CodexProjects/tavonel-saas-foundation/nextjs/node_modules/pdfjs-dist/legacy/build/pdf.mjs \
node render_fixture.mjs

# 2. the receipt
cd <repo root>
.venv/Scripts/python.exe research/explore_change_receipt_20260905/build_receipt.py

# 3. the checks
.venv/Scripts/python.exe -m pytest research/explore_change_receipt_20260905 -q
.venv/Scripts/python.exe -m ruff check research/explore_change_receipt_20260905
MYPYPATH='<repo>\services\core-v3\src;<repo>\packages\cir-python\src' \
  .venv/Scripts/python.exe -m mypy research/explore_change_receipt_20260905
```

`research/` is not in `testpaths`, so step 3 runs by path. `MYPYPATH` is needed
locally because this checkout's editable install predates `services/core-v3`, so
`akc_core_v3` is not importable the way `akc_cir` is — which is also why
`build_receipt.py` puts the worktree's `services/core-v3/src` and
`packages/cir-python/src` at the front of `sys.path` before it imports anything.
CI installs the project fresh (`uv run --locked --extra dev mypy packages
services`) and does not need the variable.

**The renderer proves itself first.** `render_fixture.mjs` carries the layout code
from the site's `nextjs/scripts/build-explore-sample.mjs`, and before it emits
anything it re-renders `fp-200-maintenance-manual-revC.pdf` and compares against
the file the site committed. It reproduces it byte for byte
(`sha256:e8772bf1…ee48e4`), and stops if it ever does not. Without that check a
revision-B manual produced here would be a document nobody could check against
the one the site will ship.

**Determinism.** No creation date or timestamp reaches an emitted PDF. Every
request id, idempotency key and `requestedAt` is fixed and the envelope clock is
pinned, so the signed bytes are the same on every run. `receipt.json`'s
`deterministic` block is byte-identical across runs; the interpreter path and
platform live in `environment`, outside the digest, because they are properties
of the machine and not of the compile.

**The chain that was driven.** `InitialCompileService` and `RevisionService`,
constructed in-process with the same signed envelope the Node client sends and
verified by the same `verify_envelope`, over `ProductionSourceResolver`. Not
over HTTP — the socket adds a transport and no compiler behaviour, and it would
put a live clock into a receipt that has to be reproducible. Where the sealed
response carries a count but not the object behind it (`RecompilationPlan`,
`EquivalenceReport`), the identical request is resolved a second time through the
same resolver and passed to `compile_revision` directly; `receipt.json` records
`sealedResponseAgreesWithDirectCompile`, and the test asserts it, so the plan and
the manifest are known to come from the same compile.

---

## What this proves, and what it does not

**It proves**

- the FP-200 corpus as the site publishes it cannot reach the core compiler at
  `26bb892`, and the refusal is the resolver's, not this lane's — the test
  re-raises it straight out of `resolve_sources`;
- the four documents' bytes are what the receipt says they are; every digest in
  `inputs` is recomputed from disk by the test;
- on the clause-form restatement the chain runs end to end and **does not**
  produce a promotable world or an equivalence pass;
- carrying a claim forward across a re-typeset leaves a stale bounding box, and
  `verify_equivalence` catches it — the module does the job it was written for.

**It does not prove**

- anything about the FP-200 documents the site serves beyond the refusal. There
  is no compiled FP-200 world here, no equivalence result for it, and no number
  from these runs may be printed beside it;
- anything about production scale, cost or latency. Ten regions, four documents,
  in-process;
- that F3 reproduces outside this fixture. It is one re-typeset on one corpus.
  It is a defect with a mechanism and a witness, not a measured rate;
- that any threshold here is right. None is calibrated, and F4 is an abstention
  inside a band nobody has fitted to a corpus.

**The clause-form corpus is a fixture, not a document.** It exists so the gap can
be located rather than asserted. It is not what the product serves, no PDF of it
is published, and `runs[1]` and `runs[2]` each carry
`corpusIsSiteFixture: false`, `wireableIntoExplore: false` and a caveat string
saying so.

---

## What a founder still has to decide

1. **Which way F1 is closed.** Teach the resolver to canonicalise unnumbered
   prose (a change to what a knowledge unit is, with an ADR and a re-run of every
   identity test), or require clause-numbered sources and say so in the product,
   or give `/explore` a fixture that is already clause-numbered. Each is a
   different product.
2. **Whether F3 is stop-the-line.** A carried-forward claim with a stale citation
   box is a world that looks compiled and cites the wrong place. It is on a
   research fixture and on no production path today, so this lane reports it and
   does not halt anything — but the call belongs upstairs.
3. **The exact bytes of `fp-200-maintenance-manual-revB.pdf`.** §4.3 pins the
   difference from revision C as "the interval text: 1,500 hours, and no
   'replaces revision B' sentence" and does not say what the title paragraph
   reads. This lane wrote "…revision B." and the file here is
   `sha256:1738896a4f79d2dc06930ccccb78940c579b0a91d80487afc56155beb9b11c5a`.
   The `explore` lane generates the same document from the same sentence and
   freezes its digest. If the two lanes read it differently the digests differ
   and one of them is wrong. Pin it once.
4. **Whether the revision-B world may contain the change notice at all.** The
   notice announces the 2,000-hour interval, so a world whose manual says 1,500
   already disagrees with itself. The core does not resolve that here — authority
   and conflict resolution are a different module — and the fixture keeps the
   notice because carrying it forward untouched is what demonstrates selective
   recompilation. Whether the `/explore` story should show that conflict, or
   avoid it, is a product decision.
