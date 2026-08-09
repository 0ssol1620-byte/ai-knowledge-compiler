import type { Metadata } from "next";

import { HERO_COPY, HeroComp } from "@/components/facing/hero-comp";

/**
 * §5.2 slop-response review — DESIGN_MASTER_V3 §5.2, §25.1.
 *
 * Two of the four responses change the screen, and the Hero comp they change
 * is approved under G-F. §24.1 does not let an approved comp be edited without
 * approval, so this route exists to make the two states comparable rather than
 * described.
 *
 *   /design/slop
 *
 * Top pane is what §5.2 asks us to leave. Bottom is the response. Both render
 * the real component with the real copy; only the treatment differs.
 *
 * Not a product route: noindex, excluded from the sitemap, and deleted once
 * decision.md records the outcome.
 */

export const metadata: Metadata = {
  title: "§5.2 slop responses",
  robots: { index: false, follow: false },
};

const NOTES = [
  {
    treatment: "chrome" as const,
    heading: "Before — what §5.2 asks us to leave",
    detail:
      "Eyebrow is an uppercase tracked label in the accent colour. No grain: " +
      "the sheet is a flat fill.",
  },
  {
    treatment: "specific" as const,
    heading: "After — the §5.2 response",
    detail:
      "Eyebrow keeps its words and loses the chrome: sentence case, no extra " +
      "tracking, ink instead of accent. The sheet carries fibre at the " +
      "smooth end of the Munken bracket (Bendtsen 150 vs 300–1200).",
  },
];

export default function SlopComparisonPage() {
  return (
    <main id="main-content" className="tv-slop-review">
      <header className="tv-slop-review-head">
        <h1>§5.2 slop responses</h1>
        <p>
          The detector rules in play are <em>Warm Accent</em> and{" "}
          <em>Eyebrow Chrome</em>. §5.2 keeps the material and answers with
          specificity, so the copy is unchanged in both panes below — only the
          treatment differs. Zoom in to check the grain does not become a grid.
        </p>
      </header>

      {NOTES.map((note) => (
        <section key={note.treatment} className="tv-slop-review-pane">
          <div className="tv-slop-review-label">
            <h2>{note.heading}</h2>
            <p>{note.detail}</p>
          </div>
          {/*
            data-treatment="chrome" restores the old eyebrow. The grain is
            suppressed in the same pane by --tv-grain-strength: 0, so the two
            §5.2 items are shown together rather than one at a time.
          */}
          <div data-treatment={note.treatment} className="tv-slop-review-frame">
            <HeroComp variant="frame" copy={HERO_COPY.d1} />
          </div>
        </section>
      ))}
    </main>
  );
}
