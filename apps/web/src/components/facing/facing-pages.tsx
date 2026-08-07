import type { ReactNode } from "react";

import {
  buildThreads,
  describeThread,
  type FacingGeometry,
  type ThreadAnchor,
} from "@/lib/facing/thread";

/**
 * FacingPages — DESIGN_MASTER_V3 §4.
 *
 * The one form every scene on the site is a variation of: source on the left,
 * output on the right, a spine between them, and threads computed from real
 * coordinates. §4.4 forbids swapping the sides and forbids drawing a thread
 * without coordinates, both of which are enforced here rather than left to
 * each caller.
 *
 * Ratios come from §6.4 and are the only ones allowed:
 *
 *   hero       5 : 7      proof     7 : 5
 *   knowledge  4 : 8      trust     6 : 6   (Trust only — even splits are dull)
 *
 * It responds to its own container width, not the viewport (§18.3), so the
 * same component collapses to a vertical stack wherever it is placed.
 */

export type FacingRatio = "hero" | "proof" | "knowledge" | "trust";

const RATIOS: Record<FacingRatio, { verso: number; recto: number }> = {
  hero: { verso: 5, recto: 7 },
  proof: { verso: 7, recto: 5 },
  knowledge: { verso: 4, recto: 8 },
  trust: { verso: 6, recto: 6 },
};

export type FacingPagesProps = {
  ratio?: FacingRatio;
  /** The source page. Always rendered on the left; §4.4 forbids swapping. */
  verso: ReactNode;
  /** The structured output. Always on the right. */
  recto: ReactNode;
  /**
   * Evidence links. Anchors without a bbox are dropped by buildThreads, so
   * passing an incomplete set yields fewer lines, never a fabricated one.
   */
  anchors?: readonly ThreadAnchor[];
  /** Page number the anchors refer to, for the text equivalent (§21). */
  sourcePageNumber?: number;
  /** Meta bar above the frame, e.g. "AAPL · FORM 10-K · FY2025 · PAGE 31". */
  meta?: ReactNode;
  /** Mono caption under the frame. */
  caption?: ReactNode;
  className?: string;
};

export function FacingPages({
  ratio = "hero",
  verso,
  recto,
  anchors = [],
  sourcePageNumber,
  meta,
  caption,
  className,
}: FacingPagesProps) {
  const { verso: versoCols, recto: rectoCols } = RATIOS[ratio];

  // Panel edges in frame space. The gutter is the spine (§4.1: 40–72px), held
  // here as a fraction so the thread geometry and the grid agree.
  const total = versoCols + rectoCols;
  const gutter = 0.045;
  const versoRight = (versoCols / total) * (1 - gutter);
  const rectoLeft = versoRight + gutter;

  const geometry: FacingGeometry = {
    versoRight,
    rectoLeft,
    orientation: "horizontal",
  };
  const threads = buildThreads(anchors, geometry);

  return (
    <figure
      className={["fl-facing", className].filter(Boolean).join(" ")}
      style={
        {
          // The unit belongs in the value: `var(--facing-verso)fr` is not
          // valid CSS, and an invalid grid-template-columns silently drops the
          // whole declaration, collapsing the spread into one column.
          "--facing-verso": `${versoCols}fr`,
          "--facing-recto": `${rectoCols}fr`,
        } as React.CSSProperties
      }
      data-ratio={ratio}
    >
      {meta && <div className="fl-facing-meta">{meta}</div>}

      <div className="fl-facing-frame">
        <div className="fl-facing-verso">{verso}</div>
        <div className="fl-facing-spine" aria-hidden="true" />
        <div className="fl-facing-recto">{recto}</div>

        {threads.length > 0 && (
          <>
            <svg
              className="fl-facing-threads"
              viewBox="0 0 1000 1000"
              preserveAspectRatio="none"
              aria-hidden="true"
              focusable="false"
            >
              {threads.map((thread) => (
                <path key={thread.id} d={thread.path} data-state={thread.state} />
              ))}
            </svg>

            {/*
              Endpoints are positioned elements, not <circle>. The path SVG
              stretches with preserveAspectRatio="none" so the curve tracks the
              panels at any aspect; a circle inside it would stretch into an
              ellipse. §4.1 asks for 3px dots, so they stay outside.
            */}
            {threads.map((thread) => (
              <span key={`${thread.id}-ends`} aria-hidden="true">
                <span
                  className="fl-facing-thread-dot"
                  data-state={thread.state}
                  style={{
                    left: `${thread.from.x * 100}%`,
                    top: `${thread.from.y * 100}%`,
                  }}
                />
                <span
                  className="fl-facing-thread-dot"
                  data-state={thread.state}
                  style={{
                    left: `${thread.to.x * 100}%`,
                    top: `${thread.to.y * 100}%`,
                  }}
                />
              </span>
            ))}
          </>
        )}
      </div>

      {/*
        §21 — the thread is a visual aid; the same fact has to be readable.
        Anchors with no coordinates are listed here even though no line is
        drawn for them, so the evidence is never silently missing.
      */}
      {anchors.length > 0 && sourcePageNumber !== undefined && (
        <ul className="sr-only">
          {anchors.map((anchor) => (
            <li key={anchor.id}>{describeThread(anchor, sourcePageNumber)}</li>
          ))}
        </ul>
      )}

      {caption && <figcaption className="fl-facing-caption">{caption}</figcaption>}
    </figure>
  );
}
