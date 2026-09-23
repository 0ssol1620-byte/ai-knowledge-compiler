# Apple temporal World — full proof through the Python Core

**INTERNAL. Not cleared for external disclosure. No number in this directory is
a public claim, a benchmark result, or evidence that selective recompilation
delivers a stated benefit.**

Program §24 (five filings, ~290 pages, entirely through the compiler path) and
§26 (the end-to-end stage list), run on the Python Core rather than on the
site's TypeScript demo compiler. Before this run, no Apple filing had ever gone
through `akc_cir` / `akc_core_v3`: there were zero pytest references to Apple,
AAPL, 10-K, 10-Q or DEF 14A in either core tree.

## What is here

| path | what it is |
|---|---|
| `sources/` | the five committed filing PDFs, byte-identical to `site-main/nextjs/public/explore-sample/`; digests are recorded in `receipts/MANIFEST.json` under `inputs` and re-checked on every run |
| `sec_adapter.py` | native PDF → validated regions → SEC canonical units. A research adapter; it imports Protected Core and modifies none of it |
| `run_chain.py` | the two chains, the three recompilation arms, the world publishes and the fail-closed controls |
| `receipts/MANIFEST.json` | inputs, runtime, declared constants, the §26 stage dispositions, and the sha256 of every other receipt |
| `receipts/steps/chain-a.json` | W0 → W4, the §24 chain |
| `receipts/steps/chain-b.json` | R0 → R2, the quarterly-revision chain (declared modelling assumption, below) |
| `receipts/steps/stock-core-arm.json` | what the Core's own canonicaliser does with these filings, unmodified |
| `receipts/world/*.json` | the unit index of each World: logical id, section, printed identifier, page, bbox1000, evidence id, text digest |

Replay: `tests/research/test_apple_temporal_world.py` (marked `slow`, ~100 s).
It re-runs the whole chain into a temp directory and holds the receipts to the
digests recorded here.

## The two chains, and why there are two

**Chain A — corpus growth.** W0 (2025 10-K) → W1 (+2026 Q1 10-Q) → W2
(+DEF 14A) → W3 (+Q2) → W4 (+Q3), exactly as §24 declares. Each filing is its
own source with its own lineage. Nothing is asserted to be a version of anything
else, so these numbers answer one question honestly: what does adding a filing
to a compiled World cost?

**Chain B — quarterly revision.** The three 2026 10-Qs treated as three versions
of one disclosure lineage. **This is a declared modelling assumption, not a fact
about SEC filings.** Three accession numbers are three filings; calling Q2 a
revision of Q1 is a choice about what the World tracks. It is made because it is
the only place in this corpus where a section's evidence *moves* while its
meaning may or may not change — the exact distinction the semantic-impact
channel exists to draw, and one Chain A cannot exercise at all.

## Things this run does not do

- No OCR, no vision model, no GPU, no paid API. Native PDF text layer only.
- No CDR and no malware scan, so no sanitized representation exists and the
  render is never labelled one.
- No loss detector (WP-R7 does not exist), no independent model verifier, no
  Ask. `receipts/MANIFEST.json` carries a disposition and a reason for all 26 stages.
- Nothing is promoted. The challenger arm is a shadow measurement under the
  compatibility ladder.

## Declared constants — read these before reading a number

- **`NATIVE_TEXT_LAYER_CONFIDENCE = 1.0` is declared, not measured.** The OCR
  record shape the Core reads requires a per-region confidence. Nothing
  recognised anything here; the bytes are the PDF's own text layer. The constant
  records "no recogniser stood between the source and this text". It is not a
  model score and the Core's `DECLARED_CONFIDENCE_FLOOR` therefore never fires
  on this corpus — correctly, since that floor exists to refuse text a
  recogniser did not stand behind.
- **The anchor rule is a heuristic with a stated ceiling.** A filing prints its
  section number in the table of contents, in a summary table, and as a running
  header on every page of the section. Consecutive occurrences merge; among what
  is left, the occurrence with the most body text wins. Every rejected
  occurrence is recorded as a fail-closed source fact, not dropped. If this
  proves too blunt, the upgrade is the render's outline or the filing's own XBRL
  section tags, not a longer regex.
- **The 2025 Form 10-K PDF is encrypted with an empty user password.**
  `parse_pdf_to_cir` refuses an encrypted PDF outright unless the caller passes
  one. `Filing.empty_user_password` is set only for that filing, so the refusal
  is visible in the corpus declaration instead of being hidden by always passing
  `b""`.
