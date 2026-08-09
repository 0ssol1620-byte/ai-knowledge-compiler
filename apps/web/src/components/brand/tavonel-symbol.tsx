/**
 * TAVONEL symbol — DESIGN_MASTER_V3 §8.1, amended (decision.md A-06).
 *
 * The facing-pages form at its smallest scale (§4.3): a longer source leaf, a
 * shorter knowledge leaf, and one thread crossing the fold between them.
 *
 *   verso (source)     x 2.5–9.5,  y 3–21    top corner cut (the page fold)
 *   recto (knowledge)  x 14.5–21.5, y 6.5–17.5
 *   thread             (9.5, 15.4) → (14.5, 12)   Δ5 : Δ3.4 = −34.2°
 *
 * The source leaf is longer on purpose: sources are many, knowledge is
 * compressed. −34° is the only diagonal the site uses; every thread, arrow,
 * and graph edge belongs to that family.
 *
 * WHY THIS DIFFERS FROM §8.1 AS WRITTEN. The spec draws the spine as a fourth
 * stroke at x 11.5, one unit from the verso edge at x 10. At stroke 1.75 those
 * two strokes occupy 9.1–10.9 and 10.6–12.4 — they overlap, and they render as
 * a single thick bar with the thread buried inside it. The spec's own
 * acceptance test ("the three elements must read apart at 16px") fails on the
 * spec's own geometry, at every size.
 *
 * The fix keeps the meaning and drops the redundant stroke: the gutter *is*
 * the spine, which is what a folio actually looks like, and the count returns
 * to the three elements §8.1 asks to be legible — verso, recto, thread. Tested
 * at 16 · 20 · 24 · 32 · 64 · 128 and under greyscale blur (§25.4).
 *
 * §8.2 forbids rotating the symbol, and §8.1 says a legibility failure is
 * fixed with a heavier stroke rather than a smaller knowledge leaf — so `size`
 * drives an optical stroke, never a scale transform.
 */
export function TavonelSymbol({
  size = 24,
  title,
}: {
  size?: number;
  /** Omit inside a labelled wordmark; supply when the symbol stands alone. */
  title?: string;
}) {
  const stroke = size <= 20 ? 1.9 : 1.6;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      role={title ? "img" : "presentation"}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {/* Verso — the source leaf, with the corner cut that reads as a fold. */}
      <path
        d="M2.5 5 4.5 3H9.5v18h-7z"
        stroke="currentColor"
        strokeWidth={stroke}
        strokeLinejoin="miter"
      />

      {/* Recto — the knowledge leaf. Shorter than the verso, inset top and bottom. */}
      <path
        d="M14.5 6.5h7v11h-7z"
        stroke="currentColor"
        strokeWidth={stroke}
        strokeLinejoin="miter"
      />

      {/* Thread — the single −34° diagonal, crossing the gutter. */}
      <path
        d="M9.5 15.4 14.5 12"
        stroke="currentColor"
        strokeWidth={stroke}
        strokeLinecap="butt"
      />
    </svg>
  );
}
