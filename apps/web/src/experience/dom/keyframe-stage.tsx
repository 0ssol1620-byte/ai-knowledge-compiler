"use client";

import type { ReactNode } from "react";

import { ARTBOARD, ZONES, COMPOSITION_CONTRACTS } from "../manifest/layout";
import { computeDensityCentroid, CENTROID } from "../world/topology";

/**
 * A canonical 1440x900 artboard, scaled to whatever width it is given.
 *
 * Phase 1 is judged at the canonical artboard (§6.1), so the review surface
 * shows the real geometry rather than a responsive approximation of it. The
 * scale is a CSS transform on a fixed-size box: every canonical pixel in the
 * shot specs can then be written literally, which is the only way a reviewer
 * can check "E1 x90 y390 w500" against what is on screen.
 */
export function KeyframeStage({
  children,
  showZones = false,
  showGuides = false,
}: {
  children: ReactNode;
  showZones?: boolean;
  showGuides?: boolean;
}) {
  return (
    <div
      data-tvx
      style={{
        position: "relative",
        width: "100%",
        aspectRatio: `${ARTBOARD.width} / ${ARTBOARD.height}`,
        overflow: "hidden",
        containerType: "inline-size",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          width: ARTBOARD.width,
          height: ARTBOARD.height,
          transformOrigin: "top left",
          // 1440 canonical px mapped onto the container's width.
          transform: `scale(calc(100cqw / ${ARTBOARD.width}))`,
        }}
      >
        {children}
        {showZones && <ZoneOverlay />}
        {showGuides && <CompositionGuides />}
      </div>
    </div>
  );
}

/**
 * The §6.3 zones, drawn over the frame. A review tool, never shipped to a
 * visitor — it is the Z9 debug layer of §6.5 and lives behind an explicit
 * toggle.
 */
function ZoneOverlay() {
  return (
    <svg
      width={ARTBOARD.width}
      height={ARTBOARD.height}
      style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
      aria-hidden
    >
      {Object.values(ZONES).map((z) => (
        <g key={z.id}>
          <rect
            x={z.x}
            y={z.y}
            width={z.w}
            height={z.h}
            fill="none"
            stroke="#6D85FF"
            strokeOpacity="0.5"
            strokeWidth="1"
            strokeDasharray="4 4"
          />
          <text
            x={z.x + 5}
            y={z.y + 12}
            fill="#6D85FF"
            fontSize="9"
            fontFamily="ui-monospace, monospace"
            letterSpacing="0.08em"
          >
            {z.id}
          </text>
        </g>
      ))}
    </svg>
  );
}

/**
 * The composition contracts of §6.4 made visible: the editorial guard, the
 * copy-width ceiling, and the density-centroid target box with the world's
 * actual measured centroid plotted inside it.
 *
 * The measurement is the point. "The centroid should be around x 58–64%" is
 * the kind of rule that quietly stops being true three shots later; plotting
 * it means a reviewer sees the drift instead of trusting the intent.
 */
function CompositionGuides() {
  const measured = computeDensityCentroid();
  const box = COMPOSITION_CONTRACTS.worldCentroid;
  const inside =
    measured.x >= box.x.min &&
    measured.x <= box.x.max &&
    measured.y >= box.y.min &&
    measured.y <= box.y.max;

  return (
    <svg
      width={ARTBOARD.width}
      height={ARTBOARD.height}
      style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
      aria-hidden
    >
      {/* Editorial guard — nothing dense may cross this line. */}
      <line
        x1={COMPOSITION_CONTRACTS.editorialTerritoryMaxX}
        y1={0}
        x2={COMPOSITION_CONTRACTS.editorialTerritoryMaxX}
        y2={ARTBOARD.height}
        stroke="#B88A48"
        strokeOpacity="0.6"
        strokeWidth="1"
      />
      <text
        x={COMPOSITION_CONTRACTS.editorialTerritoryMaxX + 6}
        y={ARTBOARD.height - 12}
        fill="#B88A48"
        fontSize="9"
        fontFamily="ui-monospace, monospace"
        letterSpacing="0.08em"
      >
        EDITORIAL GUARD x520
      </text>

      {/* Copy width ceiling. */}
      <line
        x1={90 + COMPOSITION_CONTRACTS.mainCopyMaxWidth}
        y1={0}
        x2={90 + COMPOSITION_CONTRACTS.mainCopyMaxWidth}
        y2={ARTBOARD.height}
        stroke="#8AA5B5"
        strokeOpacity="0.4"
        strokeWidth="1"
        strokeDasharray="3 6"
      />

      {/* Centroid target and measurement. */}
      <rect
        x={box.x.min}
        y={box.y.min}
        width={box.x.max - box.x.min}
        height={box.y.max - box.y.min}
        fill="none"
        stroke={inside ? "#8AA5B5" : "#9D5752"}
        strokeWidth="1"
      />
      <circle
        cx={measured.x}
        cy={measured.y}
        r="4"
        fill="none"
        stroke={inside ? "#8AA5B5" : "#9D5752"}
        strokeWidth="1.5"
      />
      <circle cx={CENTROID.x} cy={CENTROID.y} r="1.5" fill="#8AA5B5" />
      <text
        x={box.x.max + 10}
        y={box.y.min + 12}
        fill={inside ? "#8AA5B5" : "#9D5752"}
        fontSize="9"
        fontFamily="ui-monospace, monospace"
        letterSpacing="0.06em"
      >
        {`CENTROID ${measured.x.toFixed(0)},${measured.y.toFixed(0)} ${inside ? "IN RANGE" : "OUT OF RANGE"}`}
      </text>
    </svg>
  );
}
