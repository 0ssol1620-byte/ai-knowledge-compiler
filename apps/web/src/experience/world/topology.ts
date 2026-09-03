/**
 * Authored Personal World topology.
 *
 * §3.6 is the rule this file exists to obey: the world is "not the accidental
 * result of a force simulation, but authored topology plus semantic
 * constraints". A force layout would put the densest mass wherever physics left
 * it and would drift every reload. Here the arrangement is a seeded, once-
 * computed structure with the constraints written down as constraints:
 *
 *   - density centroid lands at x 835–920, y 432–468 canonical (§6.4)
 *   - x < 520 stays low density, because that is editorial territory (§6.4)
 *   - the world bleeds past the right, top and bottom edges (§6.4)
 *   - a dense current-project core, people clusters, decision landmarks, a
 *     source rear stratum, fault zones, sparse bridges, peripheral islands
 *     (§13.1)
 *
 * The seed is fixed. This is a designed composition that must be identical on
 * the server, in the client, and in every screenshot the visual gate compares —
 * `Math.random()` here would fail hydration and make regression testing
 * meaningless at the same time.
 */

import { ARTBOARD } from "../manifest/layout";

/** Deterministic PRNG. Same seed, same world, every render and every capture. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const WORLD_SEED = 18291;

/** §6.4 — the visible density centroid the composition is authored around. */
export const CENTROID = { x: 885, y: 455 } as const;

/** §6.4 — left of this is editorial territory and stays quiet. */
export const EDITORIAL_GUARD_X = 520;

export type TerritoryKind =
  /** The project the guided proof is about. Densest, nearest, most detailed. */
  | "core"
  /** Active projects around the core. */
  | "active"
  /** Older work, pushed into depth. */
  | "archive"
  /** Beyond the main mass — the world continues past the frame. */
  | "island";

export type Territory = {
  readonly id: string;
  readonly kind: TerritoryKind;
  readonly cx: number;
  readonly cy: number;
  readonly radius: number;
  /** 0 = far, 1 = near. Drives contrast and extrusion, never blur. */
  readonly presence: number;
  /** Vertical extrusion of the plate, canonical px. */
  readonly lift: number;
  readonly polygon: readonly (readonly [number, number])[];
  /** People marks sitting on this territory. */
  readonly people: readonly (readonly [number, number])[];
  /** Decision landmarks — §13.1. Sparse and meaningful. */
  readonly decisions: readonly (readonly [number, number])[];
};

export type Bridge = {
  readonly from: string;
  readonly to: string;
  readonly kind: "works_on" | "depends_on" | "belongs_to";
};

/** An irregular plate. Regular polygons read as generated; these do not. */
function plate(
  rnd: () => number,
  cx: number,
  cy: number,
  radius: number,
): readonly (readonly [number, number])[] {
  const sides = 6 + Math.floor(rnd() * 3);
  const start = rnd() * Math.PI * 2;
  const pts: [number, number][] = [];
  for (let i = 0; i < sides; i += 1) {
    const a = start + (i / sides) * Math.PI * 2;
    // Radial jitter plus a vertical squash: the world is seen obliquely, so a
    // territory is an ellipse-ish plate rather than a circle.
    const r = radius * (0.72 + rnd() * 0.46);
    pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r * 0.52]);
  }
  return pts;
}

function scatterOn(
  rnd: () => number,
  cx: number,
  cy: number,
  radius: number,
  count: number,
): readonly (readonly [number, number])[] {
  const out: [number, number][] = [];
  for (let i = 0; i < count; i += 1) {
    const a = rnd() * Math.PI * 2;
    const r = Math.sqrt(rnd()) * radius * 0.62;
    out.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r * 0.52]);
  }
  return out;
}

/**
 * 34 territories — the illustrative project count the compile report cites.
 * The two numbers are tied on purpose: if the report says 34 projects, the
 * world shows 34 territories, or the instrumentation is decorative.
 */
export const TERRITORY_COUNT = 34;

function buildTopology(): {
  territories: readonly Territory[];
  bridges: readonly Bridge[];
} {
  const rnd = mulberry32(WORLD_SEED);
  const territories: Territory[] = [];

  // Ring plan. Authored, not simulated: each ring has a stated count, radius
  // band and role, so the density falloff away from the centroid is a decision
  // rather than an emergent property.
  const rings: {
    kind: TerritoryKind;
    count: number;
    rMin: number;
    rMax: number;
    sizeMin: number;
    sizeMax: number;
    presence: [number, number];
  }[] = [
    { kind: "core", count: 1, rMin: 0, rMax: 0, sizeMin: 84, sizeMax: 84, presence: [1, 1] },
    { kind: "active", count: 6, rMin: 120, rMax: 205, sizeMin: 44, sizeMax: 64, presence: [0.82, 0.95] },
    { kind: "active", count: 9, rMin: 215, rMax: 340, sizeMin: 30, sizeMax: 50, presence: [0.6, 0.8] },
    { kind: "archive", count: 9, rMin: 350, rMax: 520, sizeMin: 20, sizeMax: 38, presence: [0.34, 0.56] },
    // The outer ring has to reach past the frame. At the 0.58 vertical squash,
    // r=820 puts the lowest islands at y≈931 against a 900px artboard, which is
    // what §6.4's "world extends beyond right/top/bottom edges" actually costs.
    { kind: "island", count: 9, rMin: 560, rMax: 820, sizeMin: 14, sizeMax: 32, presence: [0.18, 0.34] },
  ];

  let index = 0;
  for (const ring of rings) {
    for (let i = 0; i < ring.count; i += 1) {
      let cx = CENTROID.x;
      let cy = CENTROID.y;

      if (ring.rMax > 0) {
        const angle = (i / ring.count) * Math.PI * 2 + (rnd() - 0.5) * 0.9;
        const r = ring.rMin + rnd() * (ring.rMax - ring.rMin);
        cx = CENTROID.x + Math.cos(angle) * r;
        // Squashed vertically: an oblique view, not a top-down map.
        cy = CENTROID.y + Math.sin(angle) * r * 0.58;

        // A territory that would land in editorial territory is reflected
        // across the centroid rather than clamped. Clamping was the first
        // attempt and it stacked the rejects into a visible vertical seam just
        // right of the guard — a column of plates that no ring had asked for.
        // Reflection keeps the ring's radius and its angular spacing, and
        // spends the rejects on the side that is supposed to carry the mass.
        if (cx < EDITORIAL_GUARD_X + 60) {
          cx = CENTROID.x + Math.abs(CENTROID.x - cx);
          cy = CENTROID.y - (cy - CENTROID.y);
        }
      }

      const radius = ring.sizeMin + rnd() * (ring.sizeMax - ring.sizeMin);
      const presence =
        ring.presence[0] + rnd() * (ring.presence[1] - ring.presence[0]);
      const kind = ring.kind;

      territories.push({
        id: index === 0 ? "territory:project-atlas" : `territory:${index}`,
        kind,
        cx,
        cy,
        radius,
        presence,
        lift: kind === "core" ? 13 : 3 + presence * 7,
        polygon: plate(rnd, cx, cy, radius),
        people: scatterOn(
          rnd,
          cx,
          cy,
          radius,
          kind === "core" ? 9 : Math.round(presence * 5),
        ),
        decisions:
          kind === "core"
            ? scatterOn(rnd, cx, cy, radius * 0.8, 3)
            : presence > 0.66
              ? scatterOn(rnd, cx, cy, radius * 0.8, 1)
              : [],
      });
      index += 1;
    }
  }

  // Sparse inter-project bridges — §13.1 says sparse, so this is capped at a
  // dozen and only connects territories that are actually near each other.
  const bridges: Bridge[] = [];
  const kinds = ["works_on", "depends_on", "belongs_to"] as const;
  for (let i = 1; i < territories.length && bridges.length < 12; i += 1) {
    const a = territories[i];
    if (!a) continue;
    let best: Territory | undefined;
    let bestD = Infinity;
    for (let j = 0; j < territories.length; j += 1) {
      const b = territories[j];
      if (i === j || !b) continue;
      const d = Math.hypot(a.cx - b.cx, a.cy - b.cy);
      if (d < bestD && d > a.radius + b.radius) {
        bestD = d;
        best = b;
      }
    }
    if (best && bestD < 260 && i % 2 === 1) {
      bridges.push({
        from: a.id,
        to: best.id,
        kind: kinds[i % kinds.length] ?? "belongs_to",
      });
    }
  }

  return { territories, bridges };
}

export const TOPOLOGY = buildTopology();

/**
 * The four affected knowledge objects of C-03, placed inside the affected
 * subgraph box the shot specifies (x 700–1160, y 250–650). They are authored
 * positions rather than derived ones, because the shot's composition depends on
 * where they land and a derived position would move when the seed changes.
 */
export type AffectedObjectId =
  | "knowledge:project-atlas/launch-date"
  | "knowledge:project-atlas/launch-readiness-review"
  | "knowledge:project-atlas/marketing-freeze"
  | "knowledge:project-atlas/eu-rollout-window";

export const AFFECTED_OBJECT_POSITIONS: Readonly<
  Record<AffectedObjectId, readonly [number, number]>
> = {
  "knowledge:project-atlas/launch-date": [872, 402],
  "knowledge:project-atlas/launch-readiness-review": [988, 318],
  // Pulled left from 1042 when the objects grew to 150px wide to carry 12px
  // text: at the old x the plate ran to 1192 and broke out of the shot's
  // x700–1160 affected-subgraph box.
  "knowledge:project-atlas/marketing-freeze": [1000, 470],
  "knowledge:project-atlas/eu-rollout-window": [800, 556],
};

/** The affected-subgraph box the shot specifies. Asserted by the layout test. */
export const AFFECTED_SUBGRAPH_BOX = {
  x: { min: 700, max: 1160 },
  y: { min: 250, max: 650 },
} as const;

/** Rendered footprint of one affected object, in canonical px. */
export const AFFECTED_OBJECT_SIZE = { width: 150, height: 53 } as const;

/** §21.7 sanity: the composition must actually satisfy §6.4's centroid rule. */
export function computeDensityCentroid(): { x: number; y: number } {
  let wx = 0;
  let wy = 0;
  let w = 0;
  for (const t of TOPOLOGY.territories) {
    // Weight by visible mass: area times presence. A faint far island should
    // not pull the centroid as hard as the core does.
    const mass = t.radius * t.radius * t.presence;
    if (t.cx < 0 || t.cx > ARTBOARD.width) continue;
    if (t.cy < 0 || t.cy > ARTBOARD.height) continue;
    wx += t.cx * mass;
    wy += t.cy * mass;
    w += mass;
  }
  return { x: wx / w, y: wy / w };
}

/**
 * H22's heterogeneous systems, derived from the world rather than drawn beside
 * it.
 *
 * The first pass authored four boundary quads at the corners of the frame. In
 * the captured still they enclosed empty stage while every territory sat
 * between them — four labelled boxes containing nothing, which is the exact
 * opposite of the beat's claim that an enterprise's knowledge lives inside
 * heterogeneous systems. A boundary has to contain what it names, so these are
 * computed from the territories they actually hold.
 *
 * The assignment is by angle around the density centroid: four sectors, so
 * every territory belongs to exactly one system and no territory is orphaned.
 */
export type SystemBoundary = {
  readonly label: string;
  readonly points: readonly (readonly [number, number])[];
};

const SYSTEM_LABELS = ["ERP", "CRM", "TICKETS", "CODE"] as const;

function buildSystemBoundaries(): readonly SystemBoundary[] {
  // Not a partition of the whole world. Carving every territory into four
  // angular sectors produced pie wedges that ran off the frame and enclosed
  // mostly empty stage — and it also asserted something false, that all
  // knowledge already sits inside a system of record. Four tight clusters says
  // the true thing: these systems hold real material, and there is more
  // material around them that none of them owns.
  const claimed = new Set<string>();
  const byPresence = [...TOPOLOGY.territories].sort(
    (a, b) => b.presence - a.presence,
  );

  return SYSTEM_LABELS.map((label) => {
    const seed =
      byPresence.find(
        (t) =>
          !claimed.has(t.id) &&
          // Seeds are kept apart so the four systems read as four places.
          !isNearClaimed(t, claimed, 210),
      ) ?? byPresence.find((t) => !claimed.has(t.id))!;

    // Membership is bounded by distance, not just by rank. Taking the four
    // nearest unclaimed territories regardless of how far away they were
    // stretched CODE and TICKETS across half the frame to reach an outer
    // island — a boundary that spans the stage stops meaning "a system".
    const CLUSTER_RADIUS = 190;
    const neighbours = TOPOLOGY.territories
      .filter((t) => t.id !== seed.id && !claimed.has(t.id))
      .map((t) => ({ t, d: Math.hypot(t.cx - seed.cx, t.cy - seed.cy) }))
      .sort((a, b) => a.d - b.d);
    const within = neighbours
      .filter((n) => n.d <= CLUSTER_RADIUS)
      .slice(0, 4)
      .map((n) => n.t);
    // A hull needs three points to be a shape; if the seed is genuinely
    // isolated, take its two nearest anyway rather than draw a line.
    const cluster = [seed].concat(
      within.length >= 2 ? within : neighbours.slice(0, 2).map((n) => n.t),
    );
    for (const t of cluster) claimed.add(t.id);

    const hull = convexHull(cluster.map((t) => [t.cx, t.cy] as const));
    const gx = cluster.reduce((a, t) => a + t.cx, 0) / cluster.length;
    const gy = cluster.reduce((a, t) => a + t.cy, 0) / cluster.length;
    const pad = 46;
    const points = hull.map(([px, py]) => {
      const dx = px - gx;
      const dy = py - gy;
      const len = Math.hypot(dx, dy) || 1;
      return [px + (dx / len) * pad, py + (dy / len) * pad] as const;
    });
    return { label, points };
  });
}

function isNearClaimed(
  candidate: Territory,
  claimed: ReadonlySet<string>,
  minDistance: number,
): boolean {
  for (const t of TOPOLOGY.territories) {
    if (!claimed.has(t.id)) continue;
    if (Math.hypot(t.cx - candidate.cx, t.cy - candidate.cy) < minDistance) {
      return true;
    }
  }
  return false;
}

/** Andrew's monotone chain. Small n, so the sort dominates and that is fine. */
function convexHull(
  input: readonly (readonly [number, number])[],
): (readonly [number, number])[] {
  const pts = [...input].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;

  const cross = (
    o: readonly [number, number],
    a: readonly [number, number],
    b: readonly [number, number],
  ) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

  const build = (source: readonly (readonly [number, number])[]) => {
    const chain: (readonly [number, number])[] = [];
    for (const p of source) {
      while (
        chain.length >= 2 &&
        cross(chain[chain.length - 2]!, chain[chain.length - 1]!, p) <= 0
      ) {
        chain.pop();
      }
      chain.push(p);
    }
    chain.pop();
    return chain;
  };

  return [...build(pts), ...build([...pts].reverse())];
}

export const SYSTEM_BOUNDARIES = buildSystemBoundaries();
