import localFont from "next/font/local";

/**
 * Latin typeface — DESIGN_MASTER_V3 §7, gate G-B.
 *
 * Wanted Sans Variable (SIL OFL 1.1, wanteddev/wanted-sans v1.0.3). Chosen over
 * Pretendard because Pretendard's Latin is an Inter derivative and §7.1 rules
 * Inter out as a template signal, and over SUIT and IBM Plex Sans KR for
 * coverage and variable-axis reasons recorded in decision.md G-B.
 *
 * The file here is the Latin-only variable subset built by
 * tools/fonts/build_fonts.py — 27.8 KB against the 60 KB /en budget in
 * decision.md A-01. Korean is deliberately absent: it ships as static
 * instances declared in src/styles/korean.css from the /ko segment (A-02,
 * A-03), because next/font cannot emit unicode-range.
 */
export const wantedSans = localFont({
  src: [
    {
      path: "../../public/fonts/wanted-sans-latin-var.woff2",
      // The whole axis in one file. §7.2 plan B uses non-integer stops
      // (510 / 590) rather than 400/500/600, which needs the range intact.
      weight: "400 1000",
      style: "normal",
    },
  ],
  variable: "--font-wanted-sans",
  display: "swap",
  preload: true,
  fallback: [
    "Segoe UI Variable Text",
    "Segoe UI",
    "system-ui",
    "sans-serif",
  ],
  // next/font measures the real face and generates a matching fallback so the
  // swap does not shift layout. §22 counts CLS as a deploy blocker.
  adjustFontFallback: "Arial",
});
