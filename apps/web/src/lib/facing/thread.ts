import type { Bbox1000 } from "@/lib/bbox";

/**
 * Evidence threads — DESIGN_MASTER_V3 §4.1, §4.4.
 *
 * A thread is the curve from a bounding box on the source page (verso) to the
 * row it produced on the knowledge side (recto). §4.4 is categorical about it:
 *
 *   > 좌표 없는 장식 스레드 금지. 좌표가 없으면 threads=[] 로 둔다.
 *
 * So every function here takes real coordinates and there is no code path that
 * invents one. `buildThreads` drops any anchor missing a bbox rather than
 * guessing a position — a screen with a gap is correct, a screen with a
 * plausible line is not.
 *
 * Coordinates are expressed in the [0,1] space of the FacingPages frame, which
 * keeps the geometry independent of the rendered pixel size. §14.4 lists five
 * more stages (CropBox, rotation, DPR, PDF.js viewport) that W4 adds once the
 * G-E schema lands; until then the input is the server's bbox1000 and nothing
 * pretends otherwise.
 */

export type ThreadAnchor = {
  id: string;
  /** Source bbox in the server's 0–1000 integer space, or null when unknown. */
  bbox: Bbox1000 | null;
  /** Vertical centre of the destination row, 0–1 within the recto panel. */
  targetY: number;
  label: string;
  state: "verified" | "review" | "recovered";
};

export type Thread = {
  id: string;
  path: string;
  /** Start point in frame space, for the origin dot. */
  from: { x: number; y: number };
  /** End point in frame space, for the arrival dot. */
  to: { x: number; y: number };
  label: string;
  state: ThreadAnchor["state"];
};

export type FacingGeometry = {
  /** Right edge of the verso panel, 0–1 across the frame. */
  versoRight: number;
  /** Left edge of the recto panel, 0–1 across the frame. */
  rectoLeft: number;
  /** Stacked layout puts recto below verso and runs threads vertically. */
  orientation: "horizontal" | "vertical";
};

/** §4.4 — at most three threads may be active at once. */
export const MAX_ACTIVE_THREADS = 3;

/**
 * The single diagonal the site is allowed to use is −34° (§8.1). Control
 * points are placed so the curve leaves and arrives near that slope instead of
 * bulging to an arbitrary tangent.
 */
const SIGNATURE_SLOPE = Math.tan((-34 * Math.PI) / 180);

export function buildThreads(
  anchors: readonly ThreadAnchor[],
  geometry: FacingGeometry,
): Thread[] {
  const threads: Thread[] = [];

  for (const anchor of anchors) {
    // §4.4: no coordinates, no thread. Not a fallback, not a placeholder.
    if (!anchor.bbox) continue;
    if (threads.length >= MAX_ACTIVE_THREADS) break;

    const [x1, y1, x2, y2] = anchor.bbox;
    const sourceCentreY = (y1 + y2) / 2 / 1000;
    const sourceRightX = x2 / 1000;

    const from =
      geometry.orientation === "horizontal"
        ? {
            x: geometry.versoRight * sourceRightX,
            y: sourceCentreY,
          }
        : {
            x: (x1 + x2) / 2 / 1000,
            y: geometry.versoRight * sourceCentreY,
          };

    const to =
      geometry.orientation === "horizontal"
        ? { x: geometry.rectoLeft, y: anchor.targetY }
        : { x: anchor.targetY, y: geometry.rectoLeft };

    threads.push({
      id: anchor.id,
      path: curve(from, to, geometry.orientation),
      from,
      to,
      label: anchor.label,
      state: anchor.state,
    });
  }

  return threads;
}

/**
 * A cubic whose control points sit on the gutter, so the curve crosses the
 * spine perpendicular to it and reads as one continuous line rather than two
 * hooks. Emitted in a 0–1000 viewBox so the SVG scales with the frame.
 */
function curve(
  from: { x: number; y: number },
  to: { x: number; y: number },
  orientation: FacingGeometry["orientation"],
): string {
  const sx = from.x * 1000;
  const sy = from.y * 1000;
  const ex = to.x * 1000;
  const ey = to.y * 1000;

  if (orientation === "vertical") {
    const span = (ey - sy) * 0.45;
    return `M ${round(sx)} ${round(sy)} C ${round(sx)} ${round(sy + span)}, ${round(ex)} ${round(ey - span)}, ${round(ex)} ${round(ey)}`;
  }

  const gutter = (ex - sx) * 0.5;
  // Nudge the control points along the signature slope so the curve's entry
  // and exit tangents stay in the same family as every other diagonal.
  const lift = Math.min(Math.abs(gutter * SIGNATURE_SLOPE * 0.12), 40);
  const direction = ey >= sy ? 1 : -1;

  return `M ${round(sx)} ${round(sy)} C ${round(sx + gutter)} ${round(sy + lift * direction)}, ${round(ex - gutter)} ${round(ey - lift * direction)}, ${round(ex)} ${round(ey)}`;
}

function round(value: number) {
  return Math.round(value * 100) / 100;
}

/**
 * The accessible equivalent §21 requires: a thread is decoration, and the same
 * fact has to be available as text.
 *
 *   "Table 14, page 31, block 7 — verified"
 */
export function describeThread(
  anchor: ThreadAnchor,
  pageNumber: number,
): string {
  const where = anchor.bbox
    ? `page ${pageNumber}`
    : `page ${pageNumber}, position unavailable`;
  return `${anchor.label}, ${where} — ${anchor.state}`;
}
