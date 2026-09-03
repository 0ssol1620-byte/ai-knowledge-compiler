/**
 * The seven source families A-01 requires, as authored SVG.
 *
 * A-01's exit condition is that at least five families are distinguishable
 * *without a legend*, and its first reject condition is "identical white
 * rectangles". So each family is drawn from the structural feature a person
 * actually recognises it by — a folio by its bound edge and its table, an email
 * thread by its quote indents, a diff by its gutter — rather than by an icon
 * sitting on a generic card.
 *
 * Everything here draws in a local 0,0 → w,h box. Placement, depth and rotation
 * belong to the composition, not to the object.
 */

import type { ReactNode } from "react";

import type { SourceFamily, SourceState } from "../fixtures/project-atlas";

/**
 * §11.3 material families, reduced to what a flat renderer can honestly carry:
 * a paper value and an ink value. The fallback tier cannot do roughness, so it
 * does not pretend to — it carries the *state* difference, which is the part
 * that means something.
 *
 * `superseded` is dimmer and cooler but never struck through or greyed to
 * illegibility: §21.3 requires old facts to stay historical rather than look
 * deleted.
 */
const SURFACE: Record<
  SourceState,
  { paper: string; ink: string; rule: string; edge: string }
> = {
  "active-approved": {
    paper: "#F4EFE5",
    ink: "#1B1A17",
    rule: "#B9B2A4",
    edge: "#8E8878",
  },
  "active-unapproved": {
    paper: "#DCD7CC",
    ink: "#2B2A26",
    rule: "#AFA99C",
    edge: "#7E796C",
  },
  superseded: {
    paper: "#9FA5A6",
    ink: "#31383A",
    rule: "#7C8486",
    edge: "#5B6365",
  },
  "scoped-exception": {
    paper: "#E8E2D5",
    ink: "#1B1A17",
    rule: "#B9B2A4",
    edge: "#8E8878",
  },
};

export type SourceObjectProps = {
  /**
   * Unique within the document. It keys the gradient this object's key light
   * lives in, so it must be stable between server and client render — a
   * render-time counter would drift and silently hand every object the first
   * one's lighting after hydration.
   */
  readonly id: string;
  readonly family: SourceFamily;
  readonly state?: SourceState;
  readonly width: number;
  readonly height: number;
  /**
   * 0 = nearest hero object, 1 = far field. Drives opacity only; scale and
   * position are the composition's business. §3.6 wants the far field present
   * but never competing with the readable foreground.
   */
  readonly depth?: number;
};

/**
 * A paper face. The two-stop gradient is the key light of §11.4 falling across
 * a sheet — a 5% delta, which is material, not decoration. There is no glow, no
 * shadow bloom and no coloured tint.
 */
function Face({
  width,
  height,
  state,
  id,
}: {
  width: number;
  height: number;
  state: SourceState;
  id: string;
}) {
  const s = SURFACE[state];
  return (
    <>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0.35" y2="1">
          <stop offset="0" stopColor={s.paper} />
          <stop offset="1" stopColor={s.edge} stopOpacity="0.22" />
        </linearGradient>
      </defs>
      <rect width={width} height={height} fill={s.paper} />
      <rect width={width} height={height} fill={`url(#${id})`} opacity="0.5" />
      <rect
        width={width}
        height={height}
        fill="none"
        stroke={s.edge}
        strokeOpacity="0.55"
        strokeWidth="1"
      />
    </>
  );
}

/** Ruled text, drawn as measured bars. Never fake glyphs — §21.1 rejects
 * unreadable fake text, and a bar reads as "text" without lying about words. */
function TextBlock({
  x,
  y,
  width,
  lines,
  colour,
  lineHeight = 7,
  lastLineRatio = 0.62,
}: {
  x: number;
  y: number;
  width: number;
  lines: number;
  colour: string;
  lineHeight?: number;
  lastLineRatio?: number;
}) {
  return (
    <g fill={colour} opacity="0.5">
      {Array.from({ length: lines }, (_, i) => (
        <rect
          key={i}
          x={x}
          y={y + i * lineHeight}
          width={i === lines - 1 ? width * lastLineRatio : width}
          height="2"
        />
      ))}
    </g>
  );
}

function PolicyFolio({ width, height, state, uid }: FamilyProps) {
  const s = SURFACE[state];
  const m = width * 0.11;
  return (
    <g>
      {/* The bound spine is what makes a folio a folio at silhouette size. */}
      <rect
        x={-width * 0.035}
        y={height * 0.02}
        width={width * 0.045}
        height={height * 0.96}
        fill={s.edge}
        opacity="0.5"
      />
      <Face width={width} height={height} state={state} id={`f-${uid}`} />
      <TextBlock x={m} y={height * 0.12} width={width - m * 2} lines={3} colour={s.ink} />
      <TextBlock x={m} y={height * 0.26} width={width - m * 2} lines={4} colour={s.ink} />
      {/* The launch-schedule table — the object the evidence dive lands on. */}
      <g stroke={s.rule} strokeWidth="1" opacity="0.85">
        <rect
          x={m}
          y={height * 0.52}
          width={width - m * 2}
          height={height * 0.26}
          fill="none"
        />
        <line x1={m} y1={height * 0.585} x2={width - m} y2={height * 0.585} />
        <line x1={m} y1={height * 0.65} x2={width - m} y2={height * 0.65} />
        <line x1={m} y1={height * 0.715} x2={width - m} y2={height * 0.715} />
        <line
          x1={m + (width - m * 2) * 0.58}
          y1={height * 0.52}
          x2={m + (width - m * 2) * 0.58}
          y2={height * 0.78}
        />
      </g>
      <TextBlock x={m} y={height * 0.85} width={width - m * 2} lines={2} colour={s.ink} />
    </g>
  );
}

function EmailThread({ width, height, state, uid }: FamilyProps) {
  const s = SURFACE[state];
  const rows = 4;
  const gap = height / rows;
  return (
    <g>
      <Face width={width} height={height} state={state} id={`f-${uid}`} />
      {Array.from({ length: rows }, (_, i) => {
        const top = i * gap + 6;
        // Each reply indents further. That staircase is the thread.
        const indent = 10 + i * 9;
        return (
          <g key={i}>
            <rect
              x={indent - 5}
              y={top}
              width="2"
              height={gap - 12}
              fill={s.rule}
              opacity="0.8"
            />
            <rect
              x={indent}
              y={top}
              width={(width - indent - 12) * 0.5}
              height="3"
              fill={s.ink}
              opacity="0.62"
            />
            <TextBlock
              x={indent}
              y={top + 8}
              width={width - indent - 12}
              lines={2}
              colour={s.ink}
              lineHeight={6}
            />
            {i < rows - 1 && (
              <line
                x1="0"
                y1={top + gap - 6}
                x2={width}
                y2={top + gap - 6}
                stroke={s.rule}
                strokeWidth="1"
                opacity="0.5"
              />
            )}
          </g>
        );
      })}
    </g>
  );
}

function SpreadsheetSlab({ width, height, state, uid }: FamilyProps) {
  const s = SURFACE[state];
  const cols = 6;
  const rows = 8;
  const cw = width / cols;
  const rh = height / rows;
  return (
    <g>
      <Face width={width} height={height} state={state} id={`f-${uid}`} />
      {/* A filled header row and a filled index column: the two features that
       * read as "spreadsheet" at 40px and at 400px alike. */}
      <rect width={width} height={rh} fill={s.edge} opacity="0.28" />
      <rect width={cw * 0.7} height={height} fill={s.edge} opacity="0.16" />
      <g stroke={s.rule} strokeWidth="0.75" opacity="0.7">
        {Array.from({ length: rows - 1 }, (_, i) => (
          <line key={`r${i}`} x1="0" y1={(i + 1) * rh} x2={width} y2={(i + 1) * rh} />
        ))}
        {Array.from({ length: cols - 1 }, (_, i) => (
          <line key={`c${i}`} x1={(i + 1) * cw} y1="0" x2={(i + 1) * cw} y2={height} />
        ))}
      </g>
      {/* Numerals live in one column, right-aligned, as real slabs do. */}
      <g fill={s.ink} opacity="0.45">
        {Array.from({ length: rows - 2 }, (_, i) => (
          <rect
            key={i}
            x={cw * 4.35}
            y={rh * (i + 1.35)}
            width={cw * 0.5}
            height="2.5"
          />
        ))}
      </g>
    </g>
  );
}

function CalendarTile({ width, height, state, uid }: FamilyProps) {
  const s = SURFACE[state];
  const cols = 7;
  const rows = 5;
  const pad = width * 0.08;
  const gw = (width - pad * 2) / cols;
  const headH = height * 0.2;
  const gh = (height - headH - pad) / rows;
  return (
    <g>
      <Face width={width} height={height} state={state} id={`f-${uid}`} />
      <rect x={pad} y={pad * 0.7} width={width * 0.42} height="4" fill={s.ink} opacity="0.6" />
      <g>
        {Array.from({ length: rows }, (_, r) =>
          Array.from({ length: cols }, (_, c) => {
            // One marked day. Not a heat map, not a full grid of dots.
            const marked = r === 2 && c === 3;
            return (
              <rect
                key={`${r}-${c}`}
                x={pad + c * gw + 1}
                y={headH + r * gh + 1}
                width={gw - 3}
                height={gh - 3}
                fill={marked ? s.ink : s.rule}
                opacity={marked ? 0.78 : 0.22}
              />
            );
          }),
        )}
      </g>
    </g>
  );
}

function CodeDiffRibbon({ width, height, state, uid }: FamilyProps) {
  const s = SURFACE[state];
  const lines = 9;
  const lh = height / lines;
  const gutter = width * 0.12;
  // Added, removed and context lines. Marked by gutter sign and indent, not by
  // red and green fills — §11.2 keeps colour for meaning the system owns.
  const kind = ["c", "c", "-", "+", "+", "c", "-", "c", "c"] as const;
  return (
    <g>
      <Face width={width} height={height} state={state} id={`f-${uid}`} />
      <rect width={gutter} height={height} fill={s.edge} opacity="0.2" />
      <line x1={gutter} y1="0" x2={gutter} y2={height} stroke={s.rule} strokeWidth="1" />
      {kind.map((k, i) => {
        const y = i * lh + lh * 0.35;
        const indent = gutter + 8 + (i % 3) * 7;
        return (
          <g key={i}>
            {k !== "c" && (
              <rect
                x={gutter * 0.32}
                y={y - 1}
                width={gutter * 0.36}
                height="2"
                fill={s.ink}
                opacity="0.7"
              />
            )}
            {k === "+" && (
              <rect
                x={gutter * 0.5 - 1}
                y={y - 4}
                width="2"
                height="8"
                fill={s.ink}
                opacity="0.7"
              />
            )}
            <rect
              x={indent}
              y={y - 1}
              width={(width - indent - 10) * (0.45 + ((i * 37) % 50) / 100)}
              height="2"
              fill={s.ink}
              opacity={k === "c" ? 0.32 : 0.58}
            />
          </g>
        );
      })}
    </g>
  );
}

function MeetingNote({ width, height, state, uid }: FamilyProps) {
  const s = SURFACE[state];
  const m = width * 0.1;
  const items = 5;
  return (
    <g>
      <Face width={width} height={height} state={state} id={`f-${uid}`} />
      <rect x={m} y={height * 0.08} width={width * 0.5} height="4" fill={s.ink} opacity="0.6" />
      <line
        x1={m}
        y1={height * 0.19}
        x2={width - m}
        y2={height * 0.19}
        stroke={s.rule}
        strokeWidth="1"
      />
      {/* Bulleted action items — the shape of a note, unlike a folio's prose. */}
      {Array.from({ length: items }, (_, i) => {
        const y = height * 0.28 + i * (height * 0.12);
        return (
          <g key={i}>
            <rect x={m} y={y - 2} width="4" height="4" fill={s.ink} opacity="0.55" />
            <rect
              x={m + 11}
              y={y - 1.5}
              width={(width - m * 2 - 11) * (0.55 + ((i * 29) % 40) / 100)}
              height="2.5"
              fill={s.ink}
              opacity="0.4"
            />
          </g>
        );
      })}
    </g>
  );
}

function SignedContract({ width, height, state, uid }: FamilyProps) {
  const s = SURFACE[state];
  const m = width * 0.12;
  return (
    <g>
      <Face width={width} height={height} state={state} id={`f-${uid}`} />
      <TextBlock x={m} y={height * 0.1} width={width - m * 2} lines={5} colour={s.ink} />
      <TextBlock x={m} y={height * 0.35} width={width - m * 2} lines={4} colour={s.ink} />
      {/* Signature rule, a real handwritten stroke, and an embossed seal.
       * §11.3 gives authority its own material; here it is the one place the
       * object carries a metal-weight mark. */}
      <line
        x1={m}
        y1={height * 0.74}
        x2={m + (width - m * 2) * 0.52}
        y2={height * 0.74}
        stroke={s.rule}
        strokeWidth="1"
      />
      <path
        d={`M ${m + 4} ${height * 0.73}
            c ${width * 0.06} -${height * 0.05}, ${width * 0.1} ${height * 0.05}, ${width * 0.16} -${height * 0.02}
            s ${width * 0.09} -${height * 0.04}, ${width * 0.14} ${height * 0.015}`}
        fill="none"
        stroke={s.ink}
        strokeOpacity="0.62"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <circle
        cx={width - m - 12}
        cy={height * 0.76}
        r={width * 0.075}
        fill="none"
        stroke={s.edge}
        strokeWidth="1.5"
        opacity="0.7"
      />
      <circle
        cx={width - m - 12}
        cy={height * 0.76}
        r={width * 0.045}
        fill={s.edge}
        opacity="0.22"
      />
    </g>
  );
}

type FamilyProps = {
  width: number;
  height: number;
  state: SourceState;
  uid: string;
};

const RENDERERS: Record<SourceFamily, (p: FamilyProps) => ReactNode> = {
  PolicyFolio,
  EmailThread,
  SpreadsheetSlab,
  CalendarTile,
  CodeDiffRibbon,
  MeetingNote,
  SignedContract,
};

/**
 * Renders one source object. Gradient ids must be unique per instance or the
 * first object's key light gets reused by every later one — a real bug that
 * looks like a lighting mistake.
 */
export function SourceObject({
  id,
  family,
  state = "active-approved",
  width,
  height,
  depth = 0,
}: SourceObjectProps) {
  const uid = `${family}-${id}`;
  const Renderer = RENDERERS[family];
  // Far objects lose contrast against the graphite, they do not blur. §11.4
  // keeps fog low-density and explicitly rules out a nightclub haze.
  const opacity = 1 - depth * 0.72;
  return (
    <g opacity={opacity}>
      <Renderer width={width} height={height} state={state} uid={uid} />
    </g>
  );
}

export { SURFACE as SOURCE_SURFACE };
