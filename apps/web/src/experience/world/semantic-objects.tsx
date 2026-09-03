/**
 * The §19 semantic families the causal loop needs beyond the source objects,
 * the Fact Stack and the world topology.
 *
 * All procedural, per §19's rule that TAVONEL-specific assets are bespoke in
 * behaviour but code-generated rather than hand-modelled. Each one exists
 * because a specific beat on the H00–H23 board cannot be told without it, and
 * each is drawn from the thing it means rather than from a stock visual idea:
 * an identity capsule is aliases converging on a registration mark, not a
 * glowing node; a semantic shard keeps the footprint of the source region it
 * lifted out of.
 */

import type { ReactNode } from "react";

import { ARTBOARD, SAFE_AREA } from "../manifest/layout";

/**
 * Horizontal advance of one 12px character in the instrument mono stack.
 * SVG cannot measure text before it paints, and every alternative here is
 * worse: wrapping labels in `foreignObject` breaks the screenshot pipeline,
 * and a hidden measuring pass costs a layout per label. A mono face makes the
 * advance a constant, which is one more reason the instrument voice is mono.
 */
export const MONO_ADVANCE_12 = 7.22;

/** Eased 0..1 ramp used to drive entry. `ease.reveal` from the token layer. */
export function ease(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return 1 - Math.pow(1 - x, 3);
}

/** Maps a shot-local progress window onto 0..1. */
export function window_(progress: number, from: number, to: number): number {
  if (to <= from) return progress >= to ? 1 : 0;
  return Math.min(1, Math.max(0, (progress - from) / (to - from)));
}

/* ── Source registration — H02 ─────────────────────────────────────────── */

/**
 * H02's mechanism: "useful areas of sources register with thin hairlines; no
 * magic center orb". A registration mark is a corner bracket, the way a
 * measuring instrument frames a region it is about to read — not a highlight
 * box, which would say "selected" instead of "measured".
 */
export function RegistrationMark({
  x,
  y,
  width,
  height,
  progress,
}: {
  x: number;
  y: number;
  width: number;
  height: number;
  progress: number;
}) {
  const t = ease(progress);
  const arm = Math.min(width, height) * 0.28 * t;
  if (arm < 0.5) return null;
  const c = "var(--tvx-signal-cobalt)";
  return (
    <g stroke={c} strokeWidth="1" fill="none" opacity={0.35 + t * 0.5}>
      <path d={`M ${x} ${y + arm} L ${x} ${y} L ${x + arm} ${y}`} />
      <path
        d={`M ${x + width - arm} ${y} L ${x + width} ${y} L ${x + width} ${y + arm}`}
      />
      <path
        d={`M ${x + width} ${y + height - arm} L ${x + width} ${y + height} L ${x + width - arm} ${y + height}`}
      />
      <path
        d={`M ${x + arm} ${y + height} L ${x} ${y + height} L ${x} ${y + height - arm}`}
      />
    </g>
  );
}

/* ── Semantic shard — H03 ──────────────────────────────────────────────── */

export type SemanticKind = "PERSON" | "PROJECT" | "DECISION" | "DATE" | "FACT";

/**
 * H03: "person/project/decision/date/fact shards lift from their exact source
 * positions." The shard travels from `originX/Y` to `targetX/Y` and leaves a
 * hairline behind — the tether is the claim that extraction did not forget
 * where it came from, which D-01/H19 later cashes in.
 */
export function SemanticShard({
  originX,
  originY,
  targetX,
  targetY,
  kind,
  text,
  progress,
}: {
  originX: number;
  originY: number;
  targetX: number;
  targetY: number;
  kind: SemanticKind;
  text: string;
  progress: number;
}) {
  const t = ease(progress);
  const x = originX + (targetX - originX) * t;
  const y = originY + (targetY - originY) * t;
  // The box is measured from its content. A fixed 108 was fine for "Approved"
  // and overran on "October 15, 2026" — and a value spilling past the plate
  // that is supposed to contain it undercuts the exact claim of the beat.
  const h = 22;
  const w = Math.max(74, text.length * MONO_ADVANCE_12 + 16);

  return (
    <g opacity={Math.min(1, progress * 3)}>
      <line
        x1={originX + w / 2}
        y1={originY + h / 2}
        x2={x + w / 2}
        y2={y + h / 2}
        stroke="#B9B2A4"
        strokeOpacity={0.22 * t}
        strokeWidth="1"
      />
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        fill="var(--tvx-graphite-800)"
        stroke="var(--tvx-signal-cool)"
        strokeOpacity="0.55"
        strokeWidth="1"
      />
      <text
        x={x + 7}
        y={y + h / 2 + 4}
        fill="var(--tvx-bone-100)"
        fontSize="12"
        fontFamily="var(--tvx-font-instrument)"
        letterSpacing="0.02em"
      >
        {text}
      </text>
      <text
        x={x}
        y={y - 6}
        fill="var(--tvx-fog-500)"
        fontSize="12"
        fontFamily="var(--tvx-font-instrument)"
        letterSpacing="0.11em"
      >
        {kind}
      </text>
    </g>
  );
}

/* ── Identity capsule — H04 ────────────────────────────────────────────── */

/**
 * H04: "aliases converge into one identity object". The aliases slide onto a
 * common axis and lock into a registration frame. Deliberately not a merge into
 * a glowing sphere — §3.5 rejects the neural-network cliché, and the point is
 * that the aliases are still individually inspectable after resolution.
 */
export function IdentityCapsule({
  x,
  y,
  aliases,
  resolved,
  progress,
}: {
  x: number;
  y: number;
  aliases: readonly string[];
  resolved: string;
  progress: number;
}) {
  const converge = ease(window_(progress, 0, 0.7));
  const lock = ease(window_(progress, 0.65, 1));
  const w = 232;
  const rowH = 24;

  return (
    <g>
      {aliases.map((alias, i) => {
        const spread = (i - (aliases.length - 1) / 2) * 62;
        const ay = y + spread * (1 - converge) + i * rowH * converge;
        const ax = x + spread * 0.6 * (1 - converge);
        return (
          <g key={alias}>
            <rect
              x={ax}
              y={ay}
              width={w}
              height={rowH - 4}
              fill="var(--tvx-graphite-800)"
              stroke="var(--tvx-steel-650)"
              strokeOpacity={0.8 - lock * 0.4}
              strokeWidth="1"
            />
            <text
              x={ax + 9}
              y={ay + rowH / 2 + 2}
              fill="var(--tvx-fog-500)"
              fontSize="12"
              fontFamily="var(--tvx-font-instrument)"
            >
              {alias}
            </text>
          </g>
        );
      })}

      {/* The registration frame that arrives on lock. Etched, not lit. */}
      {lock > 0.01 && (
        <g opacity={lock}>
          <rect
            x={x - 10}
            y={y - 12}
            width={w + 20}
            height={aliases.length * rowH + 42}
            fill="none"
            stroke="var(--tvx-signal-cool)"
            strokeWidth="1"
          />
          <text
            x={x - 10}
            y={y + aliases.length * rowH + 44}
            fill="var(--tvx-bone-100)"
            fontSize="13"
            fontWeight="500"
            fontFamily="var(--tvx-font-editorial)"
          >
            {resolved}
          </text>
          <text
            x={x - 10}
            y={y - 20}
            fill="var(--tvx-fog-500)"
            fontSize="12"
            fontFamily="var(--tvx-font-instrument)"
            letterSpacing="0.11em"
          >
            ONE IDENTITY
          </text>
        </g>
      )}
    </g>
  );
}

/* ── Candidate fact — H10, H11 ─────────────────────────────────────────── */

export type CandidateResolution = "current" | "superseded" | "unapproved";

/**
 * H10 and H11. The losers stay inspectable: §5.2's rule is that they remain
 * attached to their source, time and authority, and §21.3 requires superseded
 * facts to stay historical rather than be deleted. So a resolved-away candidate
 * recedes and desaturates; it never disappears and it is never struck through.
 */
export function CandidateFact({
  x,
  y,
  value,
  label,
  resolution,
  resolved,
}: {
  x: number;
  y: number;
  value: string;
  label: string;
  resolution: CandidateResolution;
  /** 0 before resolution, 1 after. Drives recession, not removal. */
  resolved: number;
}) {
  const isCurrent = resolution === "current";
  const recede = isCurrent ? 0 : ease(resolved);
  const w = 300;
  const h = 46;

  return (
    <g
      opacity={1 - recede * 0.55}
      transform={`translate(${recede * 26} 0)`}
    >
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        fill="var(--tvx-graphite-800)"
        stroke={
          isCurrent && resolved > 0.4
            ? "var(--tvx-signal-cool)"
            : "var(--tvx-steel-650)"
        }
        strokeWidth={isCurrent && resolved > 0.4 ? 1.25 : 1}
      />
      <text
        x={x + 12}
        y={y + 26}
        fill="var(--tvx-bone-100)"
        fontSize="17"
        fontWeight="500"
        fontFamily="var(--tvx-font-instrument)"
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {value}
      </text>
      <text
        x={x + 12}
        y={y + 40}
        fill="var(--tvx-fog-500)"
        fontSize="12"
        fontFamily="var(--tvx-font-instrument)"
        letterSpacing="0.04em"
      >
        {label}
      </text>
      {/* Authority registration mark, only on the value that wins. It is a
        * mark on the object, not a colour swap — §32.5 forbids reducing
        * authority semantics to colour decoration. */}
      {isCurrent && resolved > 0.5 && (
        <rect
          x={x + w - 14}
          y={y + 10}
          width="2"
          height={h - 20}
          fill="var(--tvx-signal-cool)"
          opacity={ease(window_(resolved, 0.5, 1))}
        />
      )}
    </g>
  );
}

/* ── Semantic diff — H13, H14 ──────────────────────────────────────────── */

/**
 * H14: "old/new value separate cleanly; no explosion." The old value slides up
 * and dims into history; the new one arrives beneath it on the same baseline,
 * so the reader's eye does not have to hunt for what replaced what.
 */
export function SemanticDiff({
  x,
  y,
  from,
  to,
  field,
  progress,
}: {
  x: number;
  y: number;
  from: string;
  to: string;
  field: string;
  progress: number;
}) {
  const split = ease(window_(progress, 0.1, 0.75));
  const arrive = ease(window_(progress, 0.45, 1));

  return (
    <g>
      <text
        x={x}
        y={y - 14}
        fill="var(--tvx-fog-500)"
        fontSize="12"
        fontFamily="var(--tvx-font-instrument)"
        letterSpacing="0.11em"
      >
        {field.toUpperCase()}
      </text>

      <g transform={`translate(0 ${-split * 34})`} opacity={1 - split * 0.6}>
        <text
          x={x}
          y={y + 20}
          fill="var(--tvx-fog-500)"
          fontSize="26"
          fontFamily="var(--tvx-font-instrument)"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {from}
        </text>
        <line
          x1={x}
          y1={y + 26}
          x2={x + from.length * 15.6}
          y2={y + 26}
          stroke="var(--tvx-steel-650)"
          strokeWidth="1"
          opacity={split}
        />
      </g>

      <g opacity={arrive} transform={`translate(0 ${(1 - arrive) * 12})`}>
        <text
          x={x}
          y={y + 44}
          fill="var(--tvx-warning-amber)"
          fontSize="26"
          fontFamily="var(--tvx-font-instrument)"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {to}
        </text>
      </g>
    </g>
  );
}

/* ── Evidence page — H19 ───────────────────────────────────────────────── */

/**
 * The evidence dive's destination: a real page with a real table, and the exact
 * cell framed. §22.3 makes paper the brightest legitimate surface, and the cell
 * is marked by a registration frame rather than a highlighter — a glowing
 * marker would read as a UI annotation rather than as the source itself.
 */
export function EvidencePage({
  x,
  y,
  width,
  height,
  rows,
  markedRow,
  markedColumn,
  caption,
  locator,
  progress,
}: {
  x: number;
  y: number;
  width: number;
  height: number;
  rows: readonly (readonly [string, string])[];
  markedRow: number;
  markedColumn: 0 | 1;
  caption: string;
  /** Printed at the foot of the page, as the document's own reference. */
  locator: string;
  progress: number;
}) {
  const t = ease(progress);
  // The table used to start 30% down a 600px page and end halfway, leaving the
  // brightest surface in the composition two-thirds empty. Paper is allowed to
  // be the brightest thing on screen (§22.3); it is not allowed to be the
  // emptiest.
  const tableTop = y + 86;
  const rowH = 30;
  const colX = [x + 28, x + width * 0.62] as const;
  const colW = [width * 0.55 - 28, width * 0.33] as const;

  return (
    <g opacity={t}>
      <rect x={x} y={y} width={width} height={height} fill="var(--tvx-paper-050)" />
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill="none"
        stroke="#8E8878"
        strokeOpacity="0.5"
      />

      <text
        x={x + 28}
        y={y + 44}
        fill="#1B1A17"
        fontSize="15"
        fontWeight="600"
        fontFamily="var(--tvx-font-evidence)"
      >
        {caption}
      </text>

      {rows.map((row, i) => {
        const ry = tableTop + i * rowH;
        return (
          <g key={row[0]}>
            <line
              x1={x + 28}
              y1={ry}
              x2={x + width - 28}
              y2={ry}
              stroke="#B9B2A4"
              strokeWidth="1"
            />
            <text
              x={colX[0]}
              y={ry + 20}
              fill="#1B1A17"
              fontSize="13"
              fontFamily="var(--tvx-font-evidence)"
            >
              {row[0]}
            </text>
            <text
              x={colX[1]}
              y={ry + 20}
              fill="#1B1A17"
              fontSize="13"
              fontFamily="var(--tvx-font-evidence)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {row[1]}
            </text>
          </g>
        );
      })}
      <line
        x1={x + 28}
        y1={tableTop + rows.length * rowH}
        x2={x + width - 28}
        y2={tableTop + rows.length * rowH}
        stroke="#B9B2A4"
        strokeWidth="1"
      />

      {/* The locator, printed as page furniture rather than as UI chrome. It
        * is the same locator the Evidence Console shows, which is the point of
        * the dive: the answer's address is a property of the source, not of the
        * interface looking at it. */}
      <line
        x1={x + 28}
        y1={y + height - 52}
        x2={x + width - 28}
        y2={y + height - 52}
        stroke="#B9B2A4"
        strokeWidth="1"
      />
      <text
        x={x + 28}
        y={y + height - 30}
        fill="#5A554B"
        fontSize="12"
        fontFamily="var(--tvx-font-instrument)"
        letterSpacing="0.06em"
      >
        {locator}
      </text>

      {/* The exact cell. A frame, drawn last so nothing overlaps it. */}
      <rect
        x={colX[markedColumn] - 8}
        y={tableTop + markedRow * rowH + 4}
        width={colW[markedColumn] + 16}
        height={rowH - 6}
        fill="none"
        stroke="var(--tvx-signal-cobalt)"
        strokeWidth="1.5"
        opacity={ease(window_(progress, 0.5, 1))}
      />
    </g>
  );
}

/* ── Permission boundary — H21, H22 ────────────────────────────────────── */

/**
 * H21: "shared entities resolve while private boundaries persist." The boundary
 * is drawn before the merge and stays after it. §32.3's Team checkpoint is
 * specifically the *boundary*, not the merge, which is why this renders as a
 * containment line rather than as a join.
 */
export function PermissionBoundary({
  points,
  label,
  progress,
}: {
  points: readonly (readonly [number, number])[];
  label: string;
  progress: number;
}) {
  const t = ease(progress);
  const d =
    points
      .map(([px, py], i) => `${i === 0 ? "M" : "L"} ${px} ${py}`)
      .join(" ") + " Z";

  // The label goes above the polygon's topmost vertex, not on its first one.
  // Anchoring to points[0] put "PRIVATE · ALICE" on top of a territory and
  // ran the boundary stroke straight through "SHARED · PLATFORM TEAM"; both
  // were unreadable in the captured frame. A backing plate does the rest —
  // §13.5's rule that a label owns its own ground, not the world's.
  let top = points[0] ?? ([0, 0] as const);
  for (const p of points) if (p[1] < top[1]) top = p;
  const labelW = label.length * MONO_ADVANCE_12 * 1.11 + 16;
  // A boundary whose top vertex sits near the right edge would push its label
  // off the artboard — which is how "SHARED · PLATFORM TEAM" lost its second
  // word. Clamping to the safe area keeps the label attached to its boundary
  // and inside the frame; §6.2 makes the safe area the limit, not the canvas.
  const labelX = Math.min(
    Math.max(top[0], SAFE_AREA.left),
    ARTBOARD.width - SAFE_AREA.right - labelW,
  );
  const labelY = top[1] - 16;

  return (
    <g opacity={t}>
      <path
        d={d}
        fill="var(--tvx-signal-cool)"
        fillOpacity="0.04"
        stroke="var(--tvx-signal-cool)"
        strokeOpacity="0.6"
        strokeWidth="1"
        strokeDasharray="7 5"
      />
      <rect
        x={labelX - 8}
        y={labelY - 13}
        width={labelW}
        height={19}
        fill="var(--tvx-graphite-900)"
        fillOpacity="0.92"
      />
      <text
        x={labelX}
        y={labelY}
        fill="var(--tvx-signal-cool)"
        fontSize="12"
        fontFamily="var(--tvx-font-instrument)"
        letterSpacing="0.11em"
      >
        {label}
      </text>
    </g>
  );
}

/* ── World-state receipt — H17 ─────────────────────────────────────────── */

/** H17: "World State n → n+1 receipt settles." A quiet instrument line. */
export function WorldStateReceipt({
  x,
  y,
  from,
  to,
  progress,
}: {
  x: number;
  y: number;
  from: string;
  to: string;
  progress: number;
}) {
  const t = ease(progress);
  return (
    <g opacity={t}>
      <text
        x={x}
        y={y}
        fill="var(--tvx-fog-500)"
        fontSize="12"
        fontFamily="var(--tvx-font-instrument)"
        letterSpacing="0.11em"
      >
        WORLD STATE
      </text>
      <text
        x={x}
        y={y + 26}
        fill="var(--tvx-bone-100)"
        fontSize="17"
        fontFamily="var(--tvx-font-instrument)"
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {`${from}  →  ${to}`}
      </text>
      <line
        x1={x}
        y1={y + 38}
        x2={x + 300 * t}
        y2={y + 38}
        stroke="var(--tvx-signal-cool)"
        strokeWidth="1"
      />
    </g>
  );
}

/** Convenience wrapper so scenes can fade a whole group on one progress value. */
export function Fade({
  in: inProgress,
  children,
}: {
  in: number;
  children: ReactNode;
}) {
  const t = ease(inProgress);
  if (t <= 0.001) return null;
  return <g opacity={t}>{children}</g>;
}
