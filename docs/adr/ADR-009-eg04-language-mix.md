# ADR-009: EG-04 language mix — per-stratum floors replace the Korean >=50% rule

- Status: **Proposed** — the lead adopts or changes the numbers at review. Nothing is enforced until WO-LPC-ADR-IMPL.
- Date: 2026-11-16
- Work order: WO-LPC-ADR (`v34-lanes/workorders/local-public-corpus.md`). The rule change is decided by Amendment 4 of
  `v34-lanes/adr/SCOPE-FOUNDER-20261116.md` (decision L-1), on Amendment 2's global-first gold.
- Scope: the **EG-04 profile only**. The model screen (`profile: screen`, nine strata in `benchmark/screen/strata.yaml`, dev 300 / holdout 100 pages) is unchanged.
- Changes digests of existing compiles: no. Touches no Protected Core module.

## Context

The rule "EG-04 corpus is at least 50% Korean pages" lives in five places:

| Place | Text | Changed by |
|---|---|---|
| `docs/masterplan/AI_Knowledge_Compiler_SaaS_Masterplan_FINAL_v2_KO_2026-07-29.md` §37.1 "Private beta 전 최소" (line ~6650) | "한국어 페이지 50% 이상". The frozen source (`docs/IMPLEMENTATION_MATRIX.md` line 4) and the origin of the CORPUS_POLICY bullet | Not edited: the file is frozen. For EG-04 only, this ADR supersedes that one bullet; the rest of §37.1 stands |
| `benchmark/corpus/CORPUS_POLICY.md`, "Minimum corpus gates" | "Private beta: 1,500 pages, 150 documents, at least 50% Korean, at least ten document classes" | WO-LPC-ADR-IMPL |
| `benchmark/screen/manifest.py` (lines ~165, ~209-210) | `korean_pages` count and `ContractError("eg04 needs >=50% Korean pages ...")` | WO-LPC-ADR-IMPL |
| `benchmark/screen/strata.yaml` header comment (lines 2-3) | "Korean strata (language: ko) must be >= 50% of pages (benchmark/corpus/CORPUS_POLICY.md)" (the screen's own plan meets it: 235 of 300 dev, 79 of 100 holdout pages) | Comment only, and **not** in WO-LPC-ADR-IMPL's write scope as written. The screen share stays; only its stated basis moves from CORPUS_POLICY to the screen's own plan. The lead adds that one comment to IMPL's scope or leaves it until a screen work order touches the file |
| `v34-lanes/workorders/core-runtime-arena.md` (outside the repository): §7 EG-04 plan (line ~412), and the already-implemented WO-D02-1 (lines ~111, ~114) and WO-D02-2 (line ~123) specs | ">=50% Korean pages"; §7 source plan ≈ 40% OpenDART/KOGL, 15% SEC, 10% CC-BY, 20% owned scans, 15% synthetic | The lead (plan text). The two WO specs are history. WO-D02-1's eg04 code (`manifest.py`, `test_screen_manifest.py`) is changed by WO-LPC-ADR-IMPL; WO-D02-2's code (`strata.yaml`, `test_screen_acquire.py`) is the screen profile and keeps its numbers (see the tests below) |

It is also pinned by two tests:

- `benchmark/tests/test_screen_manifest.py::test_eg04_profile_accepts_disjoint_and_rejects_overlap_and_low_korean` (lines ~167-187:
  the `_eg04_docs(korean_ratio=…)` fixture at 167, the 40%-Korean rejection at 186-187). It tests the EG-04 rule, and WO-LPC-ADR-IMPL
  changes it.
- `benchmark/tests/test_screen_acquire.py::test_strata_targets_sum_and_korean_share` (lines ~44-49; line 49 asserts
  `sum(s[split] for s in strata if s["language"] == "ko") * 2 >= total` over `strata.yaml`, for dev and holdout). It is WO-D02-2's code,
  written to that spec's "Korean strata >=50% of pages, matching CORPUS_POLICY" (core-runtime-arena.md line ~123). It tests the
  **screen** plan, which this ADR does not change, so it is **not edited**: it stays as an invariant of the screen's own plan, not of
  CORPUS_POLICY. When the `strata.yaml` comment is next changed, its basis is rewritten to the screen's own plan in the same way.

`docs/release/EXTERNAL_GATES.md` describes EG-04 (>=1,500 pages, >=150 documents) without a language share, so it does not change.

How the list was made, so it can be re-run. A share rule can be written as prose or as arithmetic, so one pattern is not enough. These
are the exact commands, run from the repository root in Git Bash; the patterns avoid a literal `'` (they use `\x27`) so they paste
unchanged. JSON (so `benchmark/schemas/`) and `apps/` are searched; only the generated `apps/web/public` and this record (by
its name, so it still matches after renumbering; the other ADRs are searched) are excluded:

```bash
V34=D:/CodexProjects/v34-lanes
PROSE='(korean|한국어|\bko\b)[^\n]{0,60}(50 ?%|>= ?50|≥ ?50|과반|절반|majority|\bhalf\b)|(50 ?%|>= ?50|≥ ?50|과반|절반|majority|\bhalf\b)[^\n]{0,40}(korean|한국어)|한국어 ?중심|korean[- ]centric'
CODE='korean_(pages|share|ratio)|ko_share|language_distribution|\b(language|lang)[\x27"]?\]?\s*(==|!=)\s*[\x27"]ko[\x27"]|[\x27"]ko[\x27"]\s*(==|!=)\s*\w*\[?[\x27"]?(language|lang)|\* ?2 ?(>=|<)'
READERS='strata\.yaml'
for P in "$PROSE" "$CODE" "$READERS"; do
  git grep -n -I -i -P "$P" -- . ':!apps/web/public' ':!docs/adr/*eg04-language-mix.md'
  grep -rnIiP "$P" "$V34/workorders" "$V34/adr"
done
```

`PROSE` finds a Korean term within a line of a share, in either order, and the "Korean-centred" wording. `CODE` finds the share
variables, **every** comparison of a `language`/`lang` field with `"ko"`, and every `* 2 >=` / `* 2 <` halving test (that is how
`korean_pages * 2 < pages` and `… == "ko") * 2 >= total` are written). `READERS` finds every file that reads or names `strata.yaml`.
Each hit was read by hand. Every hit file is either a rule place in the table or test list above, or one of these, which are not:

- decision records, which record the decision to change the rule, not the rule: `v34-lanes/workorders/local-public-corpus.md` (§2.7,
  the WO-LPC-ADR spec, L-1, the WO index), `local-public-corpus.v1.md` (its superseded first version), `LPC.json` and `ALL.json` (the
  work-order index), and `v34-lanes/adr/SCOPE-FOUNDER-20261116.md` (Amendment 4, the decision itself);
- `core-runtime-arena.md` line ~121: WO-D02-2's write-scope list naming `strata.yaml` (that file is already in the table);
- `docs/north-star/TAVONEL_MASTERPLAN_v3.1.md` line ~3752: `language_distribution: {ko: 0.7, en: 0.3}` is one page's profiler output
  in an example, not a corpus rule;
- the frozen masterplan §32.6 "실제 해자" (line ~6289): "한국어 중심 Golden Corpus" names the golden corpus as a moat and states no
  share, so it is not a rule place and is not edited. Amendment 2 moves the headline corpus to global-first; Korean stays a set of
  strata, as below.

The frozen masterplan's §22.2 golden-corpus table plans Korean pages by area but states no share and no pattern above matches it, so it
is not a rule place either. For each rule place, the "Changed by" entry was checked against that work order's write scope.

Amendment 2 made the target customer global and the gold global-first (SEC EDGAR, ESEF, UK iXBRL, NIST OSCAL, US federal data). Korean
sources are kept only for the Korean/HWP stratum. A corpus-wide Korean majority now contradicts the product claim, and one aggregate
share hides the thing EG-04 must show: quality **per document class**.

The only corpus that exists locally is the SEC set (Amendment 3). It is born-digital English financial filings. That fact shapes
what can be promised.

## Options

- **(a) Keep >=50% Korean.** Contradicts the global decision, and forces most of the corpus to be sourced from Korean material that
  Amendment 2 says is not the headline.
- **(b) Per-stratum page floors, plus an English tables stratum.** Each class has its own minimum, so a strong stratum cannot pay for
  a missing one. **Recommended.**
- **(c) Drop any language floor.** An aggregate of 1,500 pages could then be all clean English text and still pass. Rejected.

## Decision (proposed): option (b)

EG-04 keeps its minimums (1,500 pages, 150 documents, at least ten classes) and replaces the aggregate Korean share with the floors
below. The strata are the screen-v1 strata, with `tables` split by language (`ko_tables`, new `en_tables`) and `ko_hwp` added (the
blueprint's V31 Korean/HWP stratum, which the screen does not have).

"Public" in the last column means the stratum's result may back a public number. Under Amendment 1 that needs gold from the
publisher's own structured record; a stratum without one is scored for internal routing only.

| Stratum | Lang | Page floor | Min docs | Why this number | Can show | Cannot show | Gold (Amendment 1) / public? |
|---|---|---|---|---|---|---|---|
| `en_native` | en | 225 (15%) | 20 | Global headline class; same share as the largest Korean stratum so neither language dominates | Critical-field exactness on real English filings | Reading order, headings or footnotes as a public number (no publisher gold; on SEC pages DOM text is diagnostic only, L-4); any text-layer vs vision comparison (Amendment 4); scans; non-English | Issuer inline XBRL (SEC; ESEF / UK iXBRL) / public, critical fields only |
| `en_tables` (new) | en | 225 (15%) | 20 | Financial statements are the product's money case; a class of its own so a table number cannot be averaged with prose | Exact statement values, units and periods | Table grid and span structure as a public number (XBRL carries values, not grids); tables in scans; other languages | Issuer inline XBRL / public, values only; grid/span internal |
| `ko_native` | ko | 250 (17%) | 20 | Largest class, because Korean born-digital quality is the cheapest regression to catch | Critical-field exactness on Korean filings; mixed ko/en lines internally | Layout stress | DART XBRL for critical fields / public for those only; other text internal until a publisher gold is named |
| `ko_scan` | ko | 150 (10%) | 15 | Scans are the hard class: the olmOCR-Bench low-quality-scans row (36.9%, 194 of 526 checks) shows it, but that row is not Korean and no Korean scan has been measured; needs enough pages to give an interval, not an anecdote | Recovery cost and failure classes on scanned Korean | Anything in English scans | None / internal only |
| `ko_tables` | ko | 150 (10%) | 15 | Korean statements and forms use different borders and units than SEC tables | Korean statement values and units | Table claims for other languages; grid structure as a public number | DART XBRL values / public, values only |
| `ko_hwp` (new) | ko | 75 (5%) | 10 | The blueprint's own HWP stratum; small because HWP is a conversion path, not a model path | HWP/HWPX conversion fidelity | OCR or scan quality | Chosen when the HWP lane opens (after U40, D01 A10) / internal until then |
| `slides` | open | 100 (7%) | 10 | Slide layout is a distinct failure class (text boxes, no flow) | Region order on non-flow layouts | Dense-text behaviour | The source deck file a PDF was rendered from, where rights allow / public only with that; otherwise internal |
| `formulas` | en | 75 (5%) | 10 | Few documents, but every formula is a binary pass/fail | LaTeX recovery on typeset math | Handwritten math | The authors' LaTeX source (licence checked per paper) / public |
| `handwriting` | open | 75 (5%) | 10 | Hard class with high variance; small floor, reported with its interval | Handwriting transcription | Printed-text quality | None / internal only |
| `distorted` | open | 100 (7%) | 10 | Skew, blur, curve; shows where the recovery ladder escalates | Degraded-image recovery | Clean-scan quality | None / internal only |
| `adversarial` | en | 75 (5%) | 10 | Hostile-document handling (injection text, malformed files); each page is a pass/fail safety check | Fail-closed behaviour | Typical quality | The expected outcome written with each constructed page (not model-made) / a pass/fail count, always labelled constructed |

`open` means the language is not fixed: those strata are sourced global-first, and the screen-v1 `ko` labels on them are not carried into EG-04. Floors sum to 1,500 pages and 150 documents (20+20+20+15+15+10+10+10+10+10+10), equal to `EG04_MIN_DOCS`. They are **floors**: a stratum above its floor does not relax another stratum. No
backfilling: a shortfall in one stratum is reported as a shortfall and is not covered by pages from another stratum.

Two guards go with the floors, because floors alone can be gamed by one large document:
- a document counts toward its stratum's floor with at most ⌈floor / 10⌉ pages (`ko_hwp`: 8; `en_native`: 23). The cap is taken from
  the **floor**, not from the stratum's actual page count, so adding pages to a stratum never raises it. Pages above the cap are still
  evaluated; they do not count toward the floor. With the minimum documents above, every floor stays reachable under the cap (tightest:
  `slides` and `distorted`, 10 × 10 = 100 = floor);
- each stratum has at least 5 distinct issuers/publishers (or authors, for handwriting). This is a corpus-policy rule, stated in the
  CORPUS_POLICY private-beta bullet (place 2 below). No manifest field records an issuer, so `manifest.py` does not check it: it is
  checked at freeze by the corpus builder's freeze receipt, computed from the source records where the issuer is recorded (for SEC
  filings, WO-LPC-4's `provenance.cik`; for OpenDART, the corporation code a filing is fetched by). A stratum whose source records do
  not record an issuer is reported by name as unverified, and EG-04 is not marked passed (see "Where each rule is checked" below).

Language shares are an **outcome, not a rule**. With these floors, fixed-language pages are Korean 625 (41.7%) and English 600 (40%);
the other 275 pages (18.3%) are `open` and are not sourced from Korean material. No share is required to exceed 50%, and if the lead
moves numbers nothing requires one to.

Difference from the core-runtime-arena §7 plan: the Korean fixed strata are 625 pages against §7's ≈ 40% OpenDART/KOGL (≈ 600); the
English floors are 450 pages (30%) against §7's 15% SEC (≈ 225, the share WO-LPC-R2 selects); `adversarial` (75) and any synthetic
degradation stay inside §7's 15% synthetic cap. A synthetic degradation is never placed in a scan stratum (`ko_scan`, `handwriting`,
`distorted`) and never counts toward any floor in this table.

### Where each rule is checked, and from which field

A manifest document carries exactly `doc_id`, `source_sha256`, `byte_size`, `page_count`, `stratum`, `language`, `document_class`,
`rights` and an optional `split` (`manifest.py` `_DOC_FIELDS`; `benchmark/schemas/screen-manifest.schema.json` closes the record with
`additionalProperties: false`). Its fields record what a person decided and `manifest.py` never infers one, so a rule is checked in
`manifest.py` only when these fields decide it. The rest is checked at corpus freeze by the corpus builder's freeze receipt, computed
from the source records the documents were built from; it is not dropped. A rule whose input the source records do not carry is
reported in the receipt by name as unverified, and EG-04 is not marked passed while any row below is unverified.
Each receipt row names the source-record value that passes the rule and the value that fails it, and reports any other record as
unverified. An input present on both sides of a rule does not decide it: a written expected outcome alone is not one, because a
synthetic degradation carries one too (`benchmark/auto_gold.py`).

| Rule | Fields read | Checked by |
|---|---|---|
| 1,500 pages, 150 documents, ten document classes (unchanged) | `page_count`, `document_class` | `manifest.py` (exists today) |
| Every document's `stratum` is one of the eleven above | `stratum` | `manifest.py`, WO-LPC-ADR-IMPL (an unknown stratum is rejected, not ignored) |
| Page floor and minimum documents per stratum; every shortfall named in one error | `stratum`, `page_count` | `manifest.py`, WO-LPC-ADR-IMPL |
| Per-document cap ⌈floor / 10⌉ | `stratum`, `page_count` | `manifest.py`, WO-LPC-ADR-IMPL |
| A fixed-language stratum holds only documents of that language; `open` holds any | `stratum`, `language` | `manifest.py`, WO-LPC-ADR-IMPL |
| A `synthetic` document is rejected in `ko_scan`, `handwriting` and `distorted`, and counts toward no floor except `adversarial`'s | `stratum`, `rights.rights_class` | `manifest.py`, WO-LPC-ADR-IMPL |
| At least 5 distinct issuers/publishers (authors, for handwriting) per stratum; a corpus-policy rule | No manifest field (the record has no issuer, and reading one out of `source_url` would be inferring it). The source records carry it where the issuer is known: WO-LPC-4's `provenance.cik`, the OpenDART corporation code. A `sources.yaml` family names the source (`sec_edgar`), not the issuer, so it does not count | The corpus builder's freeze receipt, listing the distinct issuers per stratum from the source records; a stratum with fewer than five recorded issuers fails the rule, is named, and EG-04 is not marked passed; a stratum whose records do not record an issuer is reported by name as unverified and EG-04 is not marked passed |
| `adversarial` holds constructed hostile pages only, never a synthetic degradation | No manifest field (`rights_class` says `synthetic` for both). The source record says which: a constructed hostile case carries an expected fail-closed outcome, an expected error code and terminal state (`auto_gold` `MutationGold`: `expected_error_code`, `expected_terminal_state`); a degradation or plain fixture carries an expected preserved reading instead (`MetamorphicGold`: `invariant_sha256`; `SyntheticGold`: `exact_ground_truth`). Both carry a written expected outcome, so its presence decides nothing | The corpus builder's freeze receipt, from each page's source record: a page passes only when its record states it was constructed as a hostile case with an expected fail-closed outcome (expected error code and terminal state); a page whose record is a degradation or a plain fixture (an expected preserved reading, e.g. a metamorphic case) fails the rule, is named, and EG-04 is not marked passed; a page whose record states neither or has no written expected outcome is reported as unverified and EG-04 is not marked passed |
| A rasterised print is never in a scan stratum (Amendment 4) | No manifest field (a rendered print is recorded as `public_record` like a real scan). The source record carries it: a page made by the pinned renderer has WO-LPC-4's `provenance.renderer_sha256` | The corpus builder's freeze receipt, from the source record and the renderer receipt: a scan-stratum document whose record has `provenance.renderer_sha256` fails the rule, is named, and EG-04 is not marked passed; one passes only when its record states its image was captured from a physical page (a scan or photograph); a scan-stratum document whose source record does not say how its image was made is reported as unverified and EG-04 is not marked passed |

`_counts` keeps its `korean_pages` entry: it is part of every frozen screen manifest's digest, and removing it would change those
digests. Only the eg04 comparison against it goes.

## What the local SEC corpus can and cannot fill

SEC filings are born-digital English HTML/iXBRL, rendered to PDF by the pinned renderer. They can fill:

- `en_native` and `en_tables`, **up to the EG-04 SEC share WO-LPC-R2 selects** (≈ 225 pages, CIK-disjoint from the screen and excluding
  the amendment-pair companies reserved by P5 of `v34-lanes/workorders/external-gates.md`), with gold taken from the registrant's XBRL
  (publisher-authored, per Amendment 1). The other ≈ 225 pages of the two English floors come from the other global-first iXBRL sources
  (ESEF, UK Companies House) unless the lead raises R2's quantity. Whether the 654 local companies can supply more under one record per
  CIK and those exclusions is not measured; R2's census reports it.

They cannot fill, and the ADR does not pretend otherwise:

- **Korean strata** (`ko_native`, `ko_tables`, `ko_scan`, `ko_hwp`) — no Korean text exists in the SEC set;
- **scans** — a rendered PDF has a perfect text layer, and printing and rescanning would be a synthetic degradation, not a real scan;
  per Amendment 4 (L-8) a rasterised print is never placed in a scan stratum, and that covers `ko_scan`, `handwriting` and `distorted`;
- **handwriting** and **distorted** (`open`) — none exists in the set;
- **slides** — filings are flow documents (investor decks are not in the pinned set);
- **formulas** — financial filings contain almost no typeset math, so `formulas` is not fillable from SEC;
- **adversarial** — real filings are not hostile; adversarial pages must be constructed and labelled as constructed;
- **HWP** — no HWP files exist in the set.

Those strata therefore need another source: DART and other Korean public sources only for the Korean strata (`ko_native`, `ko_tables`,
`ko_scan`, `ko_hwp`), per Amendment 2, never as the headline corpus; global-first sources for the `open` strata (`slides`, `handwriting`,
`distorted`); own or constructed documents for `adversarial`. Each source gets its row in `docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml`
before anything is pulled. `ko_hwp` cannot be filled before the Korean HWP lane opens after U40 (D01 A10). Until every stratum is
sourced and rights-cleared, EG-04 is not closable. The corpus freeze must report each unfilled stratum by name and shortfall, and must
not mark EG-04 passed. Screen-v1 is unaffected: SEC still fills `en_native` there (Amendment 4), and the screen's other eight strata stay
as they are.

## Consequences

- Tables are measured separately in English and Korean; a single "tables" number can no longer average them.
- The 1,500-page total can be reached only when every stratum is filled, which is stricter than the old rule for a corpus that is
  mostly English and weaker for one that is mostly Korean.
- Public numbers can come only from strata with publisher gold (the last column): critical fields and statement values from
  `en_native`, `en_tables`, `ko_native` and `ko_tables`; `formulas`; `slides` where the source deck is available; `adversarial` as a
  labelled constructed pass/fail count. `ko_scan`, `handwriting` and `distorted` have no authoritative structured gold, so their results
  are internal routing evidence and cannot become public numbers. Whether publisher gold satisfies EG-04's annotation-QA wording is
  decided at D36 (Amendment 1); this ADR does not decide it.
- Floors are plans, not measurements. No floor is calibrated; they are not evidence of a model's quality on that class.

## Places to change when accepted (WO-LPC-ADR-IMPL)

1. `benchmark/screen/manifest.py`: replace the eg04 `korean_pages * 2 < pages` check with the rows of "Where each rule is checked"
   that say WO-LPC-ADR-IMPL (stratum ids, floors and minimum documents, the per-document cap, fixed-language strata, `synthetic`
   placement). Nothing else in the file changes: `_DOC_FIELDS`, `_counts` (including `korean_pages`) and the screen profile stay. The
   five-issuer guard, the `adversarial` rule and the rasterised-print rule are **not** in `manifest.py`; the corpus builder's freeze
   receipt checks them.
2. `benchmark/corpus/CORPUS_POLICY.md`: the private-beta bullet replaces "at least 50% Korean" with the per-stratum floors (and minimum
   documents and per-document cap) above, and states the five-issuer rule as corpus policy, checked by the corpus builder's freeze
   receipt from the source records; a stratum the receipt cannot verify leaves EG-04 not passed.
3. `benchmark/screen/strata.yaml`: header comment only — its basis becomes the screen's own plan instead of CORPUS_POLICY (the screen strata and their Korean share are unchanged); EG-04 floors live with the profile, not in the screen list. Not in IMPL's write scope as written: the lead adds it or defers it.
4. `benchmark/tests/test_screen_manifest.py`: `test_eg04_profile_...` and its helper `_eg04_docs` (line ~167). The old fixture puts
   every document in stratum `s0`, so it fails on the unknown-stratum check, not on language, at any Korean ratio. The helper is rebuilt
   over the eleven strata. A rebuilt fixture that meets every floor with 40% Korean pages passes (the Korean floors alone are 625 of
   1,500 pages, 41.7%, so that fixture carries English pages above their floors); a fixture missing the `en_tables` floor fails, naming
   `en_tables`. The helper also feeds `test_doc_id_cannot_escape_corpus_root_and_eg04_needs_intact_screen_manifest` (line ~297),
   whose body does not change and which must still fail on "intact manifest"; IMPL's scope line names only `test_eg04_profile_…`, so
   the lead confirms that the shared helper is in scope.
5. `benchmark/tests/test_screen_acquire.py::test_strata_targets_sum_and_korean_share`: **not edited**. It pins the screen plan, which keeps its Korean share; it is no longer read as enforcing CORPUS_POLICY.
6. `docs/masterplan/AI_Knowledge_Compiler_SaaS_Masterplan_FINAL_v2_KO_2026-07-29.md` §37.1: **not edited** (frozen); this ADR is the superseding record for its Korean bullet, for EG-04 only.
7. `v34-lanes/workorders/core-runtime-arena.md` §7 (outside this repository): the lead updates the plan text.

## Rollback

Restore the `korean_pages * 2 < pages` check, the CORPUS_POLICY bullet and the old fixture. No data or digest depends on this rule.
