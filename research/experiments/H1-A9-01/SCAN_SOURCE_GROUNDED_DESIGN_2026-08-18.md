# Source-grounded acceptance on scans — design

Phase 0 recorded this arm as unavailable. That verdict was about one check —
`native_text_source_check`, which asks a PDF for its embedded text layer — and
not about the arm. The 200 sources are page images and have no text layer, so
that check can only ever return "no". What it cannot tell us is whether the
*page image itself* can serve as the evidence source.

It can. The material is local and needs no GPU, no new licence and no new model:

| material | where | what it gives |
|---|---|---|
| 200 source page images | `.chatgpt2codex/stage1-hard-200-v1/inputs/` (named by case id; the manifest maps them to page names) | the ink |
| 10,205 ground-truth regions with `poly` | `OmniDocBench-subset.json` | correctness outcome only |
| second parser per-block `bbox` + `type` | MinerU staged output | the model's own geometry claim |

**The anti-circularity rule holds without exception.** Ground truth is the
correctness outcome and nothing else. No gate signal below may read it — not the
polygons, not the text, not the category labels. A gate that has seen the answer
is not a gate.

---

## Design 1 — region evidence alignment

**Question.** Does the parser's own claim about where content is agree with where
ink actually is?

The parser emits a block list with bounding boxes. Render the page image to a
binary ink mask by local thresholding, then for each emitted block compare the
ink inside the box with the characters the parser says it read there. Two
failures fall out without OCR:

- **claimed but empty** — a block with substantive text over a region that is
  blank. This is hallucination, and it is the failure a text-only metric is
  worst at catching, because a fluent invented paragraph scores well against
  nothing.
- **inked but unclaimed** — a connected ink region of document-scale size that
  no emitted block covers. This is omission: a column, a footnote, a table
  dropped entirely. The single most damaging error mode for a knowledge
  compiler, because the output looks complete.

**Signal.** Per page, the unclaimed-ink fraction and the empty-claim count. Both
are computed from the image and the parser output alone.

**Cost.** CPU. Thresholding and connected components over 200 pages is seconds,
not minutes. No inference.

**What can go wrong, and the honest reading.** Ink coverage is not text
coverage — a figure, a stamp, a scan artefact or a dark margin all read as ink,
and OmniDocBench's hard subset is full of exactly those. So the *inked but
unclaimed* signal will over-fire on figure-heavy pages, and the instrument must
be validated the same way the output instruments just were: inject a deleted
column into a clean output and require the signal to move, before any
performance number is reported. An instrument that has not caught a defect
placed in front of it has not been shown to work.

## Design 2 — OCR-independent visual verification

**Question.** Is the amount of text the parser emitted for a region consistent
with the amount of ink in that region?

Per emitted block, the ratio of ink pixels to emitted character count. Real text
lives in a narrow band of ink-per-character for a given font size; gross
omission pushes the ratio up, gross hallucination pushes it down. Neither
direction needs to read the characters, which is the point — an OCR-based check
would just be a third parser, and would inherit the same failure modes as the
two we have.

**Signal.** Per page, the count of blocks outside a band whose edges are fixed on
the discovery set and then frozen.

**Cost.** CPU, same pass as Design 1.

**Limits, stated up front.** This does not detect a *substitution* — a number
read as a different number of the same length is invisible to it. It is a
complement to the critical-token check, not a replacement, and the two should be
measured for complementarity the way stability and agreement just were rather
than assumed to stack.

## Design 3 — a small human-verified gold subset

Not an agent's call. Blind category judgements and forced comparisons are made by
a person under this repository's self-approval rule, so this design is recorded
and stops here: 40–60 pages, sampled to over-represent the disagreement and
instability cases so the judgements land where the signal is, labelled by a
person who has not seen either parser's output.

---

## Where this fits

If either design separates severe error at all, it is worth more than the
signals now measured, for one reason: **it costs no additional inference.** The
stability gate needs a second run and the agreement gate needs a second parser,
each roughly doubling GPU spend. `evidence_validity` and both designs here read
only what the single run already produced.

That does not make them better signals. It makes them cheaper ones, and whether
cheap-and-weak beats expensive-and-strong is the R4 question, answered by
measurement rather than by preference.

## Status

`DESIGNED_NOT_IMPLEMENTED`. Nothing here has been run. No number in this file
describes the system, because there are none.
