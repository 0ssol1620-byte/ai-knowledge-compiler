/**
 * Screen, grid and layer system — §6, plus the label rules of §13.3–13.5.
 *
 * Every pixel value here is canonical at the 1440x900 artboard. Nothing in the
 * renderer may consume these as raw pixels at another viewport: pass them
 * through `normalizeZone` first, which is the "convert to normalized layout
 * tokens" rule of §6.1 made mechanical rather than remembered.
 */

export const ARTBOARD = { width: 1440, height: 900 } as const;

/** §6.2 — global safe area, in canonical pixels. */
export const SAFE_AREA = {
  left: 90,
  right: 90,
  top: 36,
  bottom: 54,
} as const;

export type ZoneId =
  | "E1_EDITORIAL"
  | "E2_WORLD"
  | "E3_QUERY"
  | "E4_EVIDENCE_CONSOLE"
  | "E5_TEMPORAL_SPINE"
  | "E6_QUIET_STATUS"
  | "E7_COMPILE_REPORT"
  | "E8_PROJECTION_SWITCH";

export type Zone = {
  readonly id: ZoneId;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  readonly purpose: string;
};

/** §6.3 — core zones. */
export const ZONES: Readonly<Record<ZoneId, Zone>> = {
  E1_EDITORIAL: {
    id: "E1_EDITORIAL",
    x: 90,
    y: 330,
    w: 520,
    h: 238,
    purpose: "Hero/act statement",
  },
  E2_WORLD: {
    id: "E2_WORLD",
    x: 540,
    y: 54,
    w: 900,
    h: 792,
    purpose: "Main spatial stage",
  },
  E3_QUERY: {
    id: "E3_QUERY",
    x: 90,
    y: 642,
    w: 550,
    h: 142,
    purpose: "Guided command and answer",
  },
  E4_EVIDENCE_CONSOLE: {
    id: "E4_EVIDENCE_CONSOLE",
    x: 1000,
    y: 126,
    w: 370,
    h: 612,
    purpose: "Earned forensic instrument",
  },
  E5_TEMPORAL_SPINE: {
    id: "E5_TEMPORAL_SPINE",
    x: 90,
    y: 744,
    w: 1260,
    h: 64,
    purpose: "Time/revision instrument",
  },
  E6_QUIET_STATUS: {
    id: "E6_QUIET_STATUS",
    x: 90,
    y: 36,
    w: 1260,
    h: 36,
    purpose: "Sample/world-state/status",
  },
  E7_COMPILE_REPORT: {
    id: "E7_COMPILE_REPORT",
    x: 90,
    y: 606,
    w: 455,
    h: 190,
    purpose: "World-linked instrumentation",
  },
  E8_PROJECTION_SWITCH: {
    id: "E8_PROJECTION_SWITCH",
    x: 1130,
    y: 792,
    w: 240,
    h: 42,
    purpose: "World / Knowledge / Source",
  },
} as const;

export type NormalizedZone = {
  readonly left: string;
  readonly top: string;
  readonly width: string;
  readonly height: string;
};

/**
 * Convert a canonical zone to percentages of the artboard. This is the only
 * sanctioned way to place a zone at a non-canonical viewport (§6.1).
 */
export function normalizeZone(zone: Zone): NormalizedZone {
  const pct = (n: number, total: number) => `${((n / total) * 100).toFixed(4)}%`;
  return {
    left: pct(zone.x, ARTBOARD.width),
    top: pct(zone.y, ARTBOARD.height),
    width: pct(zone.w, ARTBOARD.width),
    height: pct(zone.h, ARTBOARD.height),
  };
}

/**
 * §6.4 — composition contracts. These are assertions the layout tests read, so
 * a regression fails a test rather than only failing a reviewer's eye.
 */
export const COMPOSITION_CONTRACTS = {
  /** Hero statement baseline is anchored left; centring it is a defect. */
  heroBaselineX: 90,
  heroCentred: false,
  mainCopyMaxWidth: 620,
  mainCopyAbsoluteCeiling: 620,
  /** Visible density centroid of the world, canonical px. */
  worldCentroid: { x: { min: 835, max: 920 }, y: { min: 432, max: 468 } },
  /** The world must bleed past the right, top and bottom edges. */
  worldExtendsBeyondFrame: true,
  /** 0–520px must stay low density in hero and world shots. */
  editorialTerritoryMaxX: 520,
  /** §3.6 — the world is the protagonist, not wallpaper. */
  worldVisualPresence: { min: 0.6, max: 0.75 },
  uiMayBeEqualBoxGrid: false,
  evidenceConsoleMaxScreenWidth: 0.27,
  /** Compile counts tether to world features; detached KPI cards are banned. */
  compileCountsDetached: false,
} as const;

/** §6.5 — layer stack. Z9 is development-only and must not ship. */
export const LAYER_STACK = [
  "Z0_BACKGROUND_ATMOSPHERE",
  "Z1_FAR_SOURCE_HORIZON",
  "Z2_WORLD_TOPOLOGY",
  "Z3_HERO_OBJECTS",
  "Z4_RELATIONS",
  "Z5_WORLD_LABELS",
  "Z6_EDITORIAL_COPY",
  "Z7_INSTRUMENTS",
  "Z8_NAV_A11Y",
  "Z9_DEBUG",
] as const;

export type LayerId = (typeof LAYER_STACK)[number];

export const LAYER_Z_INDEX: Readonly<Record<LayerId, number>> =
  Object.fromEntries(
    LAYER_STACK.map((id, index) => [id, index * 10]),
  ) as Readonly<Record<LayerId, number>>;

/**
 * §13.4 — collision priority. Lower number wins. When two labels cannot both
 * be placed, the loser is hidden, never shrunk below the minimum (§6.6).
 */
export const COLLISION_PRIORITY = {
  P0_EXACT_EVIDENCE: 0,
  P1_HERO_EDITORIAL: 1,
  P2_SELECTED_OBJECT: 2,
  P3_STATE: 3,
  P4_SOURCE_BREADCRUMB: 4,
  P5_NEIGHBOR_ENTITY: 5,
  P6_TERRITORY: 6,
  P7_FAR: 7,
} as const;

/** §6.6 — a label is hidden rather than rendered below this size. */
export const MIN_LABEL_PX = 12;

/** §13.5 — leader line ceilings. */
export const MAX_LEADER_PX = { desktop: 120, mobile: 72 } as const;

/** §13.5 — labels fade; they never pop or bounce. */
export const LABEL_FADE_MS = { min: 120, max: 180 } as const;

/**
 * §13.3 — readable label budgets per act. Exceeding these is the difference
 * between an authored world and a force-directed graph.
 */
export const LABEL_BUDGETS = {
  MESS: { desktop: 6, mobile: 3, required: "source families" },
  DISCOVER: { desktop: 7, mobile: 4, required: "semantic types" },
  RESOLVE: { desktop: 7, mobile: 4, required: "aliases + result" },
  WORLD_REVEAL: { desktop: 4, mobile: 2, required: "meaningful landmarks only" },
  TRUTH: { desktop: 8, mobile: 5, required: "candidates + states" },
  CHANGE: { desktop: 7, mobile: 4, required: "changed meaning + affected subset" },
  EVIDENCE: { desktop: 8, mobile: 5, required: "breadcrumb + value" },
  EXPLORE: { desktop: 15, mobile: 7, required: "selected neighborhood" },
} as const;

/** §21.4 — every layout gate runs at these seven widths. */
export const VERIFICATION_VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
  { width: 360, height: 800 },
] as const;

/** §21.4 — no touch target below this, in CSS px. */
export const MIN_TOUCH_TARGET_PX = 44;
