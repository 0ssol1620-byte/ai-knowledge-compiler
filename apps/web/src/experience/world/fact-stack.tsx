/**
 * The Compiled Knowledge Object — A-07's signature asset.
 *
 * A-07 rejects a solid glowing orb, a random geometry morph, layers that are
 * all one colour, and fake code rain. Its exit condition is that the visitor
 * reads compilation as *structured assembly*, not magic ingestion. So this is
 * drawn as six registered plates in an axonometric stack: a thing that was
 * built out of parts, where each part is still nameable afterwards.
 *
 * The six plates are the six things TAVONEL actually resolves — value, semantic
 * type, source, time, authority, revision. §14 gates label exposure at five, so
 * the type plate carries no label; it is present in the geometry because the
 * object has it, not because the caption needs it.
 */

import type { KnowledgePlate } from "../fixtures/project-atlas";

/**
 * Plate materials, running §11.3 from bottom to top. The source plate is raw
 * paper, the middle plates are compiled ceramic, and only the authority plate
 * gets authority metal. That ordering is the claim: a raw document was refined
 * into a registered fact.
 */
const PLATE_STYLE: Record<
  KnowledgePlate["kind"],
  { top: string; side: string; front: string; ink: string; metal?: boolean }
> = {
  // Raw paper at the bottom, refined ceramic through the middle, authority
  // metal near the top, and the value plate brightest of all. The first pass
  // put the four middle plates within a few values of each other and tripped
  // A-07's "all layers same colour" reject; the ramp is now wide enough that
  // the stack reads as six distinct materials at a glance.
  SOURCE: { top: "#CFC7B5", side: "#8E8778", front: "#B6AE9D", ink: "#22211D" },
  REVISION: { top: "#6E7880", side: "#434C53", front: "#59626A", ink: "#E4E8EA" },
  TIME: { top: "#889298", side: "#565F6C", front: "#6F7887", ink: "#E4E8EA" },
  AUTHORITY: {
    top: "#CDD2D5",
    side: "#767D83",
    front: "#A3ABB0",
    ink: "#14181A",
    metal: true,
  },
  TYPE: { top: "#9EA8AD", side: "#646D73", front: "#828C92", ink: "#14181A" },
  VALUE: { top: "#F2EFE7", side: "#A6A296", front: "#DFDACD", ink: "#14181A" },
};

/** Bottom-to-top assembly order. The value plate lands last and sits on top. */
const STACK_ORDER: KnowledgePlate["kind"][] = [
  "SOURCE",
  "REVISION",
  "TIME",
  "AUTHORITY",
  "TYPE",
  "VALUE",
];

/** §A-07 label exposure — five, and the type plate is the one left unnamed. */
const LABELLED: ReadonlySet<KnowledgePlate["kind"]> = new Set([
  "VALUE",
  "SOURCE",
  "TIME",
  "AUTHORITY",
  "REVISION",
]);

export type FactStackProps = {
  readonly plates: readonly KnowledgePlate[];
  /** Top-left of the object's bounding box, in canonical artboard pixels. */
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  /**
   * Screen-space separation between plates. A-07's interaction contract is
   * 8–12px on hover; the settled state uses the micro-gap that reveals the
   * layers without pulling the object apart.
   */
  readonly separation?: number;
  readonly showLabels?: boolean;
};

export function FactStack({
  plates,
  x,
  y,
  width,
  height,
  separation = 0,
  showLabels = true,
}: FactStackProps) {
  const byKind = new Map(plates.map((p) => [p.kind, p]));

  // Axonometric constants. A shallow angle: the object must read as layered
  // from the front, not as a 3D render showing off its own perspective.
  // A-07 makes this the hero of the frame at visual priority 1. The first pass
  // used a 14px face on a 26px pitch and the object came out a third the height
  // of its 240x250 box — physically inside the spec's coordinates and yet
  // clearly not the subject of the shot. These fill the box.
  const plateW = width * 0.82;
  const plateH = 22; // face height of one plate
  const depthX = width * 0.18; // horizontal run of the top face
  const depthY = 14; // vertical rise of the top face
  const pitch = 36 + separation; // vertical distance between plate faces

  const stackHeight = (STACK_ORDER.length - 1) * pitch + plateH + depthY;
  // Bottom of the stack, so the whole object sits centred in its box.
  const baseY = y + (height - stackHeight) / 2 + stackHeight - plateH;

  return (
    <g>
      {STACK_ORDER.map((kind, i) => {
        const plate = byKind.get(kind);
        if (!plate) return null;
        const s = PLATE_STYLE[kind];
        const py = baseY - i * pitch;
        const px = x;

        return (
          <g key={kind}>
            {/* Top face — the parallelogram that makes the stack legible. */}
            <path
              d={`M ${px} ${py} L ${px + depthX} ${py - depthY} L ${px + depthX + plateW} ${py - depthY} L ${px + plateW} ${py} Z`}
              fill={s.top}
            />
            {/* Front face — carries the plate's text. */}
            <rect x={px} y={py} width={plateW} height={plateH} fill={s.front} />
            {/* Right side face. */}
            <path
              d={`M ${px + plateW} ${py} L ${px + depthX + plateW} ${py - depthY} L ${px + depthX + plateW} ${py - depthY + plateH} L ${px + plateW} ${py + plateH} Z`}
              fill={s.side}
            />
            {/* Registration hairline between plates. This is the "micro-gap
              * reveals layers" of A-07 — a machined seam, not a drop shadow. */}
            <line
              x1={px}
              y1={py}
              x2={px + plateW}
              y2={py}
              stroke="#050607"
              strokeOpacity="0.35"
              strokeWidth="0.75"
            />

            {/* §11.4 authority glint: narrow and rare. One plate in the system
              * gets it, and it is a specular edge, not a halo. */}
            {s.metal && (
              <rect
                x={px + depthX * 0.18}
                y={py - depthY + 1.5}
                width={plateW * 0.34}
                height="1.25"
                fill="#F2F4F5"
                opacity="0.72"
              />
            )}

            <text
              x={px + 12}
              y={py + plateH / 2 + 4}
              fill={s.ink}
              fontSize={kind === "VALUE" ? 14 : 12}
              fontWeight={kind === "VALUE" ? 600 : 500}
              fontFamily="var(--tvx-font-instrument)"
              letterSpacing={kind === "VALUE" ? "0.01em" : "0.03em"}
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {plate.text}
            </text>

            {showLabels && LABELLED.has(kind) && (
              <g>
                {/* Leader to a screen-space label — §13.5, well inside the
                  * 120px desktop ceiling. It leaves from the middle of the
                  * plate's own face: leaving from the top face put every label
                  * half a plate high, so each one appeared to name the layer
                  * above the one it described. */}
                <line
                  x1={px + depthX + plateW}
                  y1={py + plateH / 2 - depthY / 2}
                  x2={px + depthX + plateW + 28}
                  y2={py + plateH / 2 - depthY / 2}
                  stroke="var(--tvx-steel-650)"
                  strokeWidth="1"
                />
                <text
                  x={px + depthX + plateW + 36}
                  y={py + plateH / 2 - depthY / 2 + 3.5}
                  fill="var(--tvx-fog-500)"
                  fontSize="12"
                  fontWeight="500"
                  fontFamily="var(--tvx-font-instrument)"
                  letterSpacing="0.12em"
                >
                  {kind}
                </text>
              </g>
            )}
          </g>
        );
      })}
    </g>
  );
}

/**
 * The tether from the compiled object back to the source it was built from.
 * §13.2 gives `supported_by` a thin warm-silver profile; it is the visual
 * promise that D-01 later cashes in.
 */
export function SourceTether({
  from,
  to,
}: {
  from: readonly [number, number];
  to: readonly [number, number];
}) {
  const [x1, y1] = from;
  const [x2, y2] = to;
  // A single controlled arc. Not a bezier spray, not a particle trail.
  const mx = (x1 + x2) / 2;
  return (
    <path
      d={`M ${x1} ${y1} Q ${mx} ${y1}, ${x2} ${y2}`}
      fill="none"
      stroke="#B9B2A4"
      strokeOpacity="0.34"
      strokeWidth="1"
    />
  );
}
