/**
 * The Personal World, rendered from the authored topology.
 *
 * A-09 rejects a logo made of nodes, a giant centred logo, a dashboard
 * appearing, and an overactive idle world. C-03 rejects a global spinner, a
 * world reset and all-nodes-flashing. Both constraints point the same way:
 * the world is a *place*, drawn as territory and elevation, and change is
 * local to the things that changed.
 *
 * This is the §19.7 fallback tier — authored 2D, no WebGL. It is built first
 * rather than last because §18.4 requires it to carry the full narrative when
 * the GPU is unavailable, and because a composition that works flat is the
 * evidence that the composition is real and not lighting tricks.
 */

import { TOPOLOGY, type Territory } from "./topology";

/**
 * Warm graphite, lifted toward steel by presence. §11.4's first-world reveal
 * rule is that structure appears by revealing geometry and depth, never by
 * raising global exposure — so presence changes *contrast*, and the stage
 * behind it never brightens.
 */
/**
 * The first pass mapped presence linearly from graphite.800 to steel.650 and
 * the world came out nearly invisible against the stage: most territories sit
 * at presence 0.3–0.8, so most of them landed within a few values of the
 * background and §3.6's "the world is the protagonist, not wallpaper" failed.
 *
 * The fix is a floor and a curve, not a brighter stage. Even the faintest
 * island clears the graphite by a readable margin, and the ramp is eased so the
 * near territories separate from the mid ones instead of bunching at the top.
 */
function faceColour(presence: number): string {
  const p = 0.26 + Math.pow(presence, 0.78) * 0.74;
  const mix = (a: number, b: number) => Math.round(a + (b - a) * p);
  // graphite.800 #141A1D → a value past steel.650, so the core reads as lit
  // rather than merely less dark.
  return `rgb(${mix(0x14, 0x44)} ${mix(0x1a, 0x52)} ${mix(0x1d, 0x5a)})`;
}

function sideColour(presence: number): string {
  const p = 0.26 + Math.pow(presence, 0.78) * 0.74;
  const mix = (a: number, b: number) => Math.round(a + (b - a) * p * 0.62);
  return `rgb(${mix(0x07, 0x1e)} ${mix(0x09, 0x26)} ${mix(0x0b, 0x2b)})`;
}

/**
 * The upper edge of a plate catches the key light (§11.4). This is the one
 * highlight in the world, and it is a geometric edge rather than a glow — which
 * is what lets the reveal read as structure appearing instead of the exposure
 * being turned up.
 */
function litEdge(
  pts: readonly (readonly [number, number])[],
): readonly (readonly [number, number])[] {
  // The run of vertices on the top half, in draw order.
  const minY = Math.min(...pts.map((p) => p[1]));
  const maxY = Math.max(...pts.map((p) => p[1]));
  const mid = minY + (maxY - minY) * 0.42;
  return pts.filter((p) => p[1] <= mid);
}

const toPath = (pts: readonly (readonly [number, number])[], dy = 0) =>
  pts
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${(y + dy).toFixed(1)}`)
    .join(" ") + " Z";

export type WorldState = "settled" | "affected" | "recompiling" | "selected";

export type PersonalWorldProps = {
  /** Ids to mark as affected — §5.3's "what it affects", never everything. */
  readonly affectedIds?: readonly string[];
  readonly selectedId?: string;
  /**
   * When false the source rear stratum is omitted. A-09 wants it; C-03's wide
   * impact camera does not need a fourth depth layer competing for attention.
   */
  readonly showSourceStratum?: boolean;
};

function TerritoryPlate({
  t,
  state,
}: {
  t: Territory;
  state: WorldState;
}) {
  const accent =
    state === "affected"
      ? "var(--tvx-warning-amber)"
      : state === "selected"
        ? "var(--tvx-signal-cobalt)"
        : undefined;

  return (
    <g>
      {/* Extruded side. Elevation is how a territory reads as land rather than
        * as a blob, and it is the only depth cue at this tier. */}
      <path d={toPath(t.polygon, t.lift)} fill={sideColour(t.presence)} />
      <path d={toPath(t.polygon)} fill={faceColour(t.presence)} />
      <path
        d={toPath(t.polygon)}
        fill="none"
        stroke={accent ?? "var(--tvx-steel-650)"}
        strokeOpacity={accent ? 0.9 : 0.34 + t.presence * 0.4}
        strokeWidth={accent ? 1.25 : 1}
      />
      {/* Key-light edge. Open path, top vertices only — a lit rim, not an
        * outline, so the plate reads as a solid with a direction of light. */}
      {!accent && (
        <path
          d={litEdge(t.polygon)
            .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`)
            .join(" ")}
          fill="none"
          stroke="#C8D2D8"
          strokeOpacity={0.06 + t.presence * 0.3}
          strokeWidth="1"
          strokeLinecap="round"
        />
      )}

      {/* People marks. Small, square, quiet — §13.1's people clusters, not a
        * scatter of glowing dots. */}
      {t.people.map(([x, y], i) => (
        <rect
          key={`p${i}`}
          x={x - 1.4}
          y={y - 1.4}
          width="2.8"
          height="2.8"
          fill="var(--tvx-fog-500)"
          opacity={0.2 + t.presence * 0.42}
        />
      ))}

      {/* Decision landmarks. A notched mark, distinct in shape from a person,
        * so the two are told apart without colour doing the work. */}
      {t.decisions.map(([x, y], i) => (
        <path
          key={`d${i}`}
          d={`M ${x} ${y - 4} L ${x + 3.4} ${y} L ${x} ${y + 4} L ${x - 3.4} ${y} Z`}
          fill="none"
          stroke={accent ?? "var(--tvx-signal-cool)"}
          strokeWidth="1"
          opacity={accent ? 0.95 : 0.3 + t.presence * 0.45}
        />
      ))}
    </g>
  );
}

export function PersonalWorld({
  affectedIds = [],
  selectedId,
  showSourceStratum = true,
}: PersonalWorldProps) {
  const affected = new Set(affectedIds);

  // Painter's order: far first. Sorting by presence is what lets near
  // territories occlude far ones honestly (§6.6 depth-aware occlusion) without
  // a z-buffer.
  const ordered = [...TOPOLOGY.territories].sort(
    (a, b) => a.presence - b.presence,
  );
  const byId = new Map(TOPOLOGY.territories.map((t) => [t.id, t]));

  return (
    <g>
      {showSourceStratum && <SourceStratum />}

      {/* Sparse bridges, drawn under the plates so a territory sits on top of
        * the relations that reach it. */}
      <g>
        {TOPOLOGY.bridges.map((b, i) => {
          const a = byId.get(b.from);
          const c = byId.get(b.to);
          if (!a || !c) return null;
          const dashed = b.kind === "depends_on";
          return (
            <line
              key={i}
              x1={a.cx}
              y1={a.cy}
              x2={c.cx}
              y2={c.cy}
              stroke="var(--tvx-steel-650)"
              strokeWidth="1"
              strokeOpacity={0.3}
              strokeDasharray={dashed ? "5 4" : undefined}
            />
          );
        })}
      </g>

      {ordered.map((t) => (
        <TerritoryPlate
          key={t.id}
          t={t}
          state={
            affected.has(t.id)
              ? "affected"
              : selectedId === t.id
                ? "selected"
                : "settled"
          }
        />
      ))}

      <FaultZone />
    </g>
  );
}

/**
 * The source rear stratum — §13.1. Documents, still present behind the
 * compiled world, so the world never looks like it replaced its evidence.
 * Positions are a fixed arithmetic lattice with a deterministic offset rather
 * than random scatter: it must be identical across screenshots.
 */
function SourceStratum() {
  const ticks: { x: number; y: number; w: number }[] = [];
  for (let row = 0; row < 6; row += 1) {
    for (let col = 0; col < 26; col += 1) {
      const x = 560 + col * 38 + ((row * 17) % 31);
      const y = 74 + row * 27 + ((col * 13) % 11);
      ticks.push({ x, y, w: 9 + ((col * 7 + row * 5) % 8) });
    }
  }
  return (
    <g opacity="0.5">
      {ticks.map((t, i) => (
        <rect
          key={i}
          x={t.x}
          y={t.y}
          width={t.w}
          height="1.5"
          fill="var(--tvx-fog-500)"
          opacity={0.14}
        />
      ))}
    </g>
  );
}

/**
 * Conflict fault zones — §13.1. Two seams, in oxide, because §11.2 reserves
 * oxide for real conflict. They are thin and rare; a world full of red seams
 * would say the compiler is failing, which is a different claim.
 */
function FaultZone() {
  return (
    <g opacity="0.55">
      <path
        d="M 742 596 L 806 610 L 858 602 L 918 618"
        fill="none"
        stroke="var(--tvx-critical-oxide)"
        strokeWidth="1.25"
        strokeDasharray="2 5"
      />
      <path
        d="M 1148 268 L 1196 282 L 1244 276"
        fill="none"
        stroke="var(--tvx-critical-oxide)"
        strokeWidth="1.25"
        strokeDasharray="2 5"
      />
    </g>
  );
}
