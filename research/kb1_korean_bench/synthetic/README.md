# KB1 KS — SYNTHETIC Korean fixtures

Design: `KOREAN-BENCHMARK-DESIGN-2026-10-17.md` §4 (KS), §5.7 (gold), §5.11 (leakage).

KS is a **harness control**. It checks that the KB1 harness, adapters and arms read
Korean pages end to end. It is never a headline, never a public number, and says
nothing about real Korean documents: the harness reports the category as
`SYNTHETIC_NOT_PUBLISHABLE`.

## Files (`out/`)

| File | What |
|---|---|
| `SYNTHETIC-KS-p01-statute-table.png` | 저작권법 제7조 items (quoted, see below) and a merged-cell table (rowspan 2, colspan 2 and 4) with Korean amounts and dates |
| `SYNTHETIC-KS-p02-vertical-hanja.png` | five vertical-rl columns (right to left) mixing hanja and hangul, then horizontal 국한문 lines |
| `SYNTHETIC-KS-p03-symbols.png` | ①–⑳, ※, 「」, 『』, 〔〕, ㈜, ·, ㆍ, ○, □, Korean article/date/amount/percent tokens |
| `SYNTHETIC-KS-p04-seal-approval.png` | fictional notice, 결재란 (approval box) and a red 견본 stamp pressed over the issuer line |
| `SYNTHETIC-KS-pages.pdf` | the four pages as an image-only PDF (150 dpi) |
| `SYNTHETIC-KS-gold.json` | gold, `tavonel.kb1.gold.v1` (the harness's `parse_gold` accepts it) |
| `SYNTHETIC-KS-manifest.sha256.json` | sha256 and size of every file above, seed, generator sha256, interpreter, Pillow/FreeType/zlib/libjpeg versions, font path, sha256 and licence string |

## Gold

Gold is written by `generate.py` at render time from the strings and boxes it drew.
Nothing is OCR'd back and nothing is inferred:

- `text` is the page's lines in reading order joined by `\n`; `blocks` group them
  (a table is one block read row-major; each vertical column is its own block, right
  to left, so M5 can see reading-order errors).
- `lines[].bbox` is the union of the ink boxes Pillow reported for each character.
  Pixels at 150 dpi, origin top-left, page 1240 × 1754. The product's `bbox1000`
  frame is a conversion for the adapter, not stored here.
- `tables[]` carries the HTML (with `rowspan`/`colspan`), every cell's stroked
  rectangle and text box, and `text_span`; `table_text_spans` feeds M4's text CER.
- `seal.occluded_spans` are the `[start, end)` offsets of every character whose ink
  box meets a non-transparent stamp pixel. The stamp text is `견본`, `fictional: true`.
- `approval_box` is true only where a 결재란 was drawn.

## Regenerate

```
py -3.13 research/kb1_korean_bench/synthetic/generate.py            # seed 20261017, writes out/
py -3.13 research/kb1_korean_bench/synthetic/generate.py --seed 7 --out <dir>
```

The run renders everything in memory and writes nothing if any check fails. It
refuses an output directory that holds files it does not produce. Same seed,
Pillow, FreeType, zlib, libjpeg, font bytes and generator give byte-identical files:
Python 3.12.13 and 3.13.0 rendered identical bytes with Pillow 12.3.0 / FreeType
2.14.3. The seed only moves and turns the stamp, so a new seed changes the p04 PNG,
the PDF and the gold, and nothing else. After editing `generate.py`, re-run it:
a test fails while the manifest's generator sha256 differs from the file.

## Text and names

- Self-written sentences, except the five 저작권법 제7조 items on p01. Those are
  rendered as quoted in `korean-benchmark-receipts/TERMS-QUOTES-20261017.json`
  (sha256 `2f29a949…5e7e`), which quotes easylaw.go.kr. They were **not** checked
  against the official text at law.go.kr, and the page heading says so
  (`인용, 공식 원문과 대조 전`). Gold is what was drawn either way.
- Organisation names are fictional and carry 가상 or 견본 (`가상기관 견본청`,
  `㈜가상견본상사`). No real institution, seal, person, phone or registration
  number appears; a test checks a list of real names stays absent.
- Amounts and dates in the table are invented for the fixture and labelled 가상 수치.

## Fonts

Only `C:\Windows\Fonts\NotoSansKR-VF.ttf` (Noto Sans KR, variable, `wght` 400). The
generator holds a path allowlist and reads the licence from the font's own name
table (ID 13); it must name the SIL Open Font License.

- `NanumGothic.ttf` on the build machine says `NHN Corporation` in name ID 13, not
  OFL, so the generator refuses it.
- Wanted Sans ships as 92 split WOFF2 subsets; their name tables are Brotli-compressed
  and cannot be read with the standard library, so it is not used.
- malgun is never on the allowlist.

A character the font draws as `.notdef` or as nothing stops the run. U+2024 (one-dot
leader, in the harness's proposed M6 set) is such a character for Noto Sans KR, so KS
does not cover it.

## Limits

- Clean renders: no scan noise, skew, blur or compression on the PNGs (the PDF embeds
  JPEG). One font, four pages, four families. KS cannot stand in for K1–K6.
- KS gold is in the repository. A score on KS is a wiring check, never evidence about
  a model or a threshold. Do not tune `_prefer_korean`, prompts or normalisation on KS
  (§5.11): calibration uses the calibration split, confirm stays sealed.
- M4 TEDS on these tables needs the OmniDocBench adapter (KB-A4); until then a
  table-structure arm's M4 is `EVALUATOR_BLOCKED`.
