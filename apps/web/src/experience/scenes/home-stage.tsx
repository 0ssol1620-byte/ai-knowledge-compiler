"use client";

/**
 * The Home stage — one implementation for all 24 beats of the §5.3 board.
 *
 * The keyframe review renders this frozen at a shot's settled progress; the
 * live experience renders it driven by the semantic timeline. That is
 * deliberate: an approval surface that draws the frames separately from the
 * thing that ships approves something that does not exist. Whatever the founder
 * signs off on here is literally what runs.
 *
 * Everything is authored SVG plus DOM text — the §19.7 fallback tier, which
 * §27.3 requires to carry the full narrative without WebGL. §19's rule that
 * proprietary semantic assets be procedural rather than hand-modelled is what
 * makes that affordable.
 */

import { ARTBOARD, ZONES } from "../manifest/layout";
import {
  BRAND_LOCK,
  QUIET_STATUS,
  SHOT_COPY,
  TRUTH_COPY,
} from "../manifest/copy";
import { COMPILE_REPORT_FIGURES } from "../manifest/truth-contract";
import type { Shot, ShotId } from "../manifest/shots";
import {
  CURRENT_ANSWER,
  LAUNCH_DATE_CANDIDATES,
  LAUNCH_DATE_OBJECT,
  RECOMPILE_LEDGER,
  WORLD_STATES,
} from "../fixtures/project-atlas";
import { FactStack, SourceTether } from "../world/fact-stack";
import { PersonalWorld } from "../world/personal-world";
import { SourceObject } from "../world/source-objects";
import {
  AFFECTED_OBJECT_POSITIONS,
  SYSTEM_BOUNDARIES,
  type AffectedObjectId,
} from "../world/topology";
import {
  CandidateFact,
  EvidencePage,
  Fade,
  IdentityCapsule,
  PermissionBoundary,
  RegistrationMark,
  SemanticDiff,
  SemanticShard,
  WorldStateReceipt,
  ease,
  window_,
} from "../world/semantic-objects";

const SAMPLE_STATUS =
  COMPILE_REPORT_FIGURES.find((f) => f.id === "files")?.status ?? "ILLUSTRATIVE";

/* ─────────────────────────────────────────────────────────────────────────
 * Shared source layout. H01 places it, H02 registers on it, H03 lifts meaning
 * out of it, and H06 keeps one folio on screen. One array, so the folio the
 * evidence dive returns to is the folio the visitor first saw.
 * ──────────────────────────────────────────────────────────────────────── */

const SOURCES = [
  { id: "note", family: "MeetingNote", x: 918, y: 148, w: 148, h: 178, depth: 0.46, rot: -1.4 },
  { id: "sheet", family: "SpreadsheetSlab", x: 1142, y: 236, w: 196, h: 152, depth: 0.2, rot: 1.1 },
  { id: "mail", family: "EmailThread", x: 698, y: 292, w: 202, h: 176, depth: 0.28, rot: -0.8 },
  { id: "diff", family: "CodeDiffRibbon", x: 742, y: 566, w: 166, h: 168, depth: 0.32, rot: 1.6 },
  { id: "cal", family: "CalendarTile", x: 1176, y: 548, w: 144, h: 132, depth: 0.22, rot: -1.2 },
  { id: "sow", family: "SignedContract", x: 1010, y: 638, w: 178, h: 136, depth: 0.14, rot: 0.9 },
  // The hero folio: nearest, allowed up to 2.5° of rotation into the light, and
  // the one H19 dives back into.
  { id: "folio", family: "PolicyFolio", x: 946, y: 356, w: 214, h: 282, depth: 0, rot: 2.5 },
] as const;

/** §13.3 MESS budget is six readable labels; four filenames stays under it. */
const FILENAMES = [
  { text: "approved_product_plan.docx", x: 946, y: 344 },
  { text: "atlas_capacity_model.xlsx", x: 1142, y: 224 },
  { text: "RE: Atlas launch logistics", x: 698, y: 280 },
  { text: "release/atlas-gate.yaml", x: 742, y: 554 },
] as const;

/** The regions H02 registers — real content areas, not whole documents. */
const REGISTRATIONS = [
  { x: 992, y: 520, w: 130, h: 90 },
  { x: 1176, y: 268, w: 130, h: 96 },
  { x: 712, y: 306, w: 168, h: 62 },
  { x: 1196, y: 588, w: 96, h: 62 },
] as const;

/** H03: what lifts out, and from where. Origins sit on the real regions. */
const SHARDS = [
  { kind: "DATE", text: "October 15, 2026", ox: 992, oy: 540, tx: 1044, ty: 300 },
  { kind: "PROJECT", text: "Project Atlas", ox: 712, oy: 316, tx: 700, ty: 246 },
  { kind: "PERSON", text: "Alice Kim", ox: 1176, oy: 286, tx: 1188, ty: 200 },
  { kind: "DECISION", text: "Approved", ox: 1196, oy: 600, tx: 1214, ty: 664 },
  { kind: "FACT", text: "Launch date", ox: 1000, oy: 566, tx: 858, ty: 662 },
] as const;

function SourceGroup({ opacity = 1 }: { opacity?: number }) {
  return (
    <g opacity={opacity}>
      {SOURCES.map((s) => (
        <g
          key={s.id}
          transform={`translate(${s.x} ${s.y}) rotate(${s.rot} ${s.w / 2} ${s.h / 2})`}
        >
          <SourceObject
            id={s.id}
            family={s.family}
            width={s.w}
            height={s.h}
            depth={s.depth}
          />
        </g>
      ))}
    </g>
  );
}

function FarField({ opacity = 0.22 }: { opacity?: number }) {
  return (
    <g opacity={opacity}>
      {Array.from({ length: 54 }, (_, i) => {
        const x = 640 + ((i * 149) % 700);
        const y = 96 + ((i * 83) % 660);
        const w = 14 + ((i * 31) % 22);
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={w}
            height={w * 1.32}
            fill="none"
            stroke="var(--tvx-steel-650)"
            strokeWidth="0.75"
          />
        );
      })}
    </g>
  );
}

function Filenames({ opacity = 1 }: { opacity?: number }) {
  return (
    <g opacity={opacity}>
      {FILENAMES.map((f) => (
        <text
          key={f.text}
          x={f.x}
          y={f.y}
          fill="var(--tvx-fog-500)"
          fontSize="12"
          fontFamily="var(--tvx-font-instrument)"
          letterSpacing="0.02em"
        >
          {f.text}
        </text>
      ))}
    </g>
  );
}

/** The world hint under a close-up beat — visual priority 4, never a subject. */
function WorldHorizon() {
  return (
    <g opacity="0.5">
      {[
        "M 620 720 L 700 700 L 812 706 L 880 726 L 792 744 L 676 740 Z",
        "M 900 748 L 986 730 L 1088 738 L 1140 758 L 1040 774 L 942 768 Z",
        "M 1150 706 L 1226 690 L 1330 698 L 1382 716 L 1288 730 L 1192 724 Z",
      ].map((d, i) => (
        <path key={i} d={d} fill="#1E272C" stroke="#3A464D" strokeWidth="1" />
      ))}
    </g>
  );
}

/** §13.5 — screen-space label with a world-space tether. */
function WorldLabel({
  x,
  y,
  anchorX,
  anchorY,
  children,
}: {
  x: number;
  y: number;
  anchorX: number;
  anchorY: number;
  children: string;
}) {
  return (
    <g>
      <line
        x1={anchorX}
        y1={anchorY}
        x2={x - 7}
        y2={y - 4}
        stroke="var(--tvx-steel-650)"
        strokeWidth="1"
        strokeOpacity="0.8"
      />
      <circle cx={anchorX} cy={anchorY} r="2" fill="var(--tvx-signal-cool)" />
      <text
        x={x}
        y={y}
        fill="var(--tvx-bone-100)"
        fontSize="13"
        fontWeight="500"
        fontFamily="var(--tvx-font-editorial)"
        letterSpacing="0.01em"
      >
        {children}
      </text>
    </g>
  );
}

/** §A-09 budget: four meaningful labels, hand-placed clear of their plates. */
const WORLD_LABELS = [
  { text: "Project Atlas", x: 940, y: 545, ax: 886, ay: 470 },
  { text: "Platform", x: 1128, y: 322, ax: 1074, ay: 338 },
  { text: "Alice Kim", x: 662, y: 622, ax: 752, ay: 566 },
  { text: "Q4 decisions", x: 1044, y: 620, ax: 992, ay: 604 },
] as const;

const AFFECTED = [
  { id: "knowledge:project-atlas/launch-date", label: "LAUNCH DATE", value: "November 3, 2026" },
  { id: "knowledge:project-atlas/launch-readiness-review", label: "READINESS REVIEW", value: "October 27, 2026" },
  { id: "knowledge:project-atlas/marketing-freeze", label: "MARKETING FREEZE", value: "October 20, 2026" },
  { id: "knowledge:project-atlas/eu-rollout-window", label: "EU ROLLOUT", value: "November 30, 2026" },
] as const satisfies readonly { id: AffectedObjectId; label: string; value: string }[];

/**
 * The beats that show recompiled values while the previous world state is
 * still the active one. Capturing the frames made the violation obvious: H16
 * displayed "November 3, 2026" under a strip reading WORLD STATE
 * SAMPLE-018291 · CURRENT. Either the values were wrong or the label was —
 * §21.3's rule is that partial world state is never exposed as ACTIVE, so the
 * label is what has to change, and the values have to say they are in flight.
 */
const RECOMPILING_SHOTS: ReadonlySet<string> = new Set(["H15", "H16"]);

function AffectedObject({
  x,
  y,
  label,
  value,
  /** 0 = intact, 1 = separated into plates and relocked. */
  rebuild,
  /** The value is the recompilation's output and is not yet active. */
  recompiling,
}: {
  x: number;
  y: number;
  label: string;
  value: string;
  rebuild: number;
  recompiling: boolean;
}) {
  const w = 150;
  const plateH = 15;
  // Plates separate in the middle of the beat and settle back — C-03's
  // "affected objects separate into plates … objects reassemble locally".
  const separation = Math.sin(Math.min(1, rebuild) * Math.PI) * 9;
  const pitch = 19 + separation;
  return (
    <g>
      {[0, 1, 2].map((i) => (
        <rect
          key={i}
          x={x}
          y={y + i * pitch}
          width={w}
          height={plateH}
          fill="var(--tvx-graphite-800)"
          stroke="var(--tvx-warning-amber)"
          strokeOpacity={i === 0 ? 0.9 : 0.42}
          strokeWidth="1"
        />
      ))}
      <text
        x={x + 7}
        y={y + plateH - 4}
        // An in-flight value is stated at reduced weight. It is legible — the
        // beat is about seeing the update happen — but it does not carry the
        // typographic authority of a settled fact.
        fill={recompiling ? "var(--tvx-fog-500)" : "var(--tvx-bone-100)"}
        fontSize="12"
        fontFamily="var(--tvx-font-instrument)"
        letterSpacing="0.02em"
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {value}
      </text>
      <text
        x={x}
        y={y - 8}
        fill="var(--tvx-warning-amber)"
        fontSize="12"
        fontFamily="var(--tvx-font-instrument)"
        letterSpacing="0.09em"
      >
        {recompiling ? `${label} · RECOMPILING` : label}
      </text>
    </g>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
 * The world layer, per beat.
 * ──────────────────────────────────────────────────────────────────────── */

function WorldLayer({ shot, progress }: { shot: Shot; progress: number }) {
  const id = shot.id;

  switch (id) {
    case "H00":
      // §5.3: near-black; one or two fragments barely emerge. Not a logo, not
      // a loading state — the stillness before a precise instrument starts.
      return (
        <g opacity={0.1 + ease(progress) * 0.2}>
          <g transform="translate(946 356) rotate(2.5 107 141)">
            <SourceObject
              id="void-folio"
              family="PolicyFolio"
              width={214}
              height={282}
              depth={0.88}
            />
          </g>
          <g transform="translate(698 292) rotate(-0.8 101 88)">
            <SourceObject
              id="void-mail"
              family="EmailThread"
              width={202}
              height={176}
              depth={0.94}
            />
          </g>
        </g>
      );

    case "H01":
      return (
        <>
          <FarField />
          <SourceGroup />
          <Fade in={window_(progress, 0.3, 1)}>
            <Filenames />
          </Fade>
        </>
      );

    case "H02":
      return (
        <>
          <FarField opacity={0.16} />
          <SourceGroup />
          <Filenames opacity={0.5} />
          {REGISTRATIONS.map((r, i) => (
            <RegistrationMark
              key={i}
              x={r.x}
              y={r.y}
              width={r.w}
              height={r.h}
              // Staggered: the instrument reads one region at a time.
              progress={window_(progress, i * 0.14, i * 0.14 + 0.5)}
            />
          ))}
        </>
      );

    case "H03":
      return (
        <>
          <SourceGroup opacity={1 - ease(progress) * 0.55} />
          {SHARDS.map((s, i) => (
            <SemanticShard
              key={s.text}
              originX={s.ox}
              originY={s.oy}
              targetX={s.tx}
              targetY={s.ty}
              kind={s.kind}
              text={s.text}
              progress={window_(progress, i * 0.1, i * 0.1 + 0.6)}
            />
          ))}
        </>
      );

    case "H04":
      return (
        <>
          <SourceGroup opacity={0.16} />
          <IdentityCapsule
            x={880}
            y={396}
            aliases={["Alice Kim", "A. Kim", "alice@company.com"]}
            resolved="One person · 3 sources"
            progress={progress}
          />
        </>
      );

    case "H05":
      return (
        <>
          <SourceGroup opacity={0.14} />
          {LAUNCH_DATE_CANDIDATES.map((c, i) => (
            <CandidateFact
              key={c.occurrenceId}
              x={860}
              y={286 + i * 62}
              value={c.value}
              label={c.label}
              resolution={c.resolution}
              resolved={window_(progress, 0.35, 1)}
            />
          ))}
        </>
      );

    case "H06":
      return (
        <>
          <WorldHorizon />
          <g transform="translate(1180 92) rotate(1.8 84 110)" opacity="0.9">
            <SourceObject
              id="h06-folio"
              family="PolicyFolio"
              width={168}
              height={220}
              depth={0.42}
            />
          </g>
          <SourceTether from={[1206, 262]} to={[1115, 352]} />
          <FactStack
            plates={LAUNCH_DATE_OBJECT.initial.plates}
            x={875}
            y={315}
            width={240}
            height={250}
            separation={(1 - ease(progress)) * 22}
          />
        </>
      );

    case "H07":
    case "H08":
      return (
        <>
          <PersonalWorld />
          <Fade in={window_(progress, 0.4, 1)}>
            {WORLD_LABELS.map((l) => (
              <WorldLabel key={l.text} x={l.x} y={l.y} anchorX={l.ax} anchorY={l.ay}>
                {l.text}
              </WorldLabel>
            ))}
          </Fade>
        </>
      );

    case "H09":
      return <PersonalWorld showSourceStratum={false} />;

    case "H10":
    case "H11":
    case "H12":
      return (
        <>
          <PersonalWorld showSourceStratum={false} />
          {/* The candidates sit over a dimmed world: §23.1 protects the copy
            * column, and the world stays visible because the answer belongs to
            * it. A modal panel would break the one-world rule. */}
          <rect
            x={540}
            y={0}
            width={900}
            height={900}
            fill="var(--tvx-graphite-900)"
            opacity={0.62}
          />
          {LAUNCH_DATE_CANDIDATES.map((c, i) => (
            <CandidateFact
              key={c.occurrenceId}
              x={860}
              y={252 + i * 68}
              value={c.value}
              label={c.label}
              resolution={c.resolution}
              resolved={id === "H10" ? 0 : window_(progress, 0.1, 0.8)}
            />
          ))}
          {id === "H12" && (
            <Fade in={window_(progress, 0.2, 1)}>
              <SourceTether from={[1160, 400]} to={[1290, 636]} />
              {/* Anchored to its right edge and pinned inside the safe area.
                * Set from the left it ran past x1440 and lost "row 4" — the
                * one part of the line that makes it a locator. */}
              <text
                x={1350}
                y={672}
                textAnchor="end"
                fill="var(--tvx-fog-500)"
                fontSize="12"
                fontFamily="var(--tvx-font-instrument)"
                letterSpacing="0.09em"
              >
                approved_product_plan.docx · p6 · row 4
              </text>
            </Fade>
          )}
        </>
      );

    case "H13":
    case "H14":
      return (
        <>
          <PersonalWorld showSourceStratum={false} />
          <rect
            x={540}
            y={0}
            width={900}
            height={900}
            fill="var(--tvx-graphite-900)"
            opacity={0.66}
          />
          <g transform="translate(1140 168) rotate(1.4 84 110)">
            <SourceObject
              id="h13-folio"
              family="PolicyFolio"
              width={168}
              height={220}
              depth={0.3}
            />
          </g>
          <RegistrationMark
            x={1162}
            y={288}
            width={124}
            height={34}
            progress={id === "H13" ? progress : 1}
          />
          {id === "H14" && (
            <SemanticDiff
              x={790}
              y={456}
              from="OCT 15"
              to="NOV 03"
              field="Launch date"
              progress={progress}
            />
          )}
        </>
      );

    case "H15":
    case "H16":
    case "H17":
      return (
        <>
          <PersonalWorld
            affectedIds={["territory:project-atlas"]}
            showSourceStratum={false}
          />
          {AFFECTED.slice(1).map((o) => {
            const [x, y] = AFFECTED_OBJECT_POSITIONS[o.id];
            const [ox, oy] =
              AFFECTED_OBJECT_POSITIONS["knowledge:project-atlas/launch-date"];
            // The impact signal travels along the filament in H15 and is
            // already arrived by H16.
            const reach = id === "H15" ? ease(window_(progress, 0.2, 0.9)) : 1;
            return (
              <line
                key={o.id}
                x1={ox + 64}
                y1={oy + 13}
                x2={ox + 64 + (x - ox) * reach}
                y2={oy + 13 + (y - oy) * reach}
                stroke="var(--tvx-warning-amber)"
                strokeOpacity="0.5"
                strokeWidth="1"
                strokeDasharray="4 5"
              />
            );
          })}
          {AFFECTED.map((o, i) => {
            const [x, y] = AFFECTED_OBJECT_POSITIONS[o.id];
            const appear =
              id === "H15" ? window_(progress, 0.15 + i * 0.14, 0.5 + i * 0.14) : 1;
            return (
              <Fade key={o.id} in={appear}>
                <AffectedObject
                  x={x}
                  y={y}
                  label={o.label}
                  value={o.value}
                  rebuild={id === "H16" ? window_(progress, 0.1, 0.9) : 0}
                  recompiling={RECOMPILING_SHOTS.has(id)}
                />
              </Fade>
            );
          })}
          {id === "H17" && (
            <WorldStateReceipt
              x={790}
              y={716}
              from={WORLD_STATES.initial}
              to={WORLD_STATES.recompiled}
              progress={progress}
            />
          )}
        </>
      );

    case "H18":
      return (
        <>
          <PersonalWorld showSourceStratum={false} />
          <rect
            x={540}
            y={0}
            width={900}
            height={900}
            fill="var(--tvx-graphite-900)"
            opacity={0.68}
          />
          <Fade in={window_(progress, 0.1, 0.7)}>
            <text
              x={800}
              y={430}
              fill="var(--tvx-bone-100)"
              fontSize="54"
              fontWeight="450"
              fontFamily="var(--tvx-font-editorial)"
              letterSpacing="-0.02em"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {CURRENT_ANSWER.value}
            </text>
            <text
              x={800}
              y={466}
              fill="var(--tvx-signal-cool)"
              fontSize="12"
              fontFamily="var(--tvx-font-instrument)"
              letterSpacing="0.11em"
            >
              {CURRENT_ANSWER.state}
            </text>
          </Fade>
        </>
      );

    case "H19":
      return (
        <>
          <PersonalWorld showSourceStratum={false} />
          <rect
            x={0}
            y={0}
            width={ARTBOARD.width}
            height={900}
            fill="var(--tvx-void-950)"
            opacity={0.72 * ease(progress)}
          />
          <EvidencePage
            x={720}
            y={196}
            width={620}
            height={440}
            locator="approved_product_plan.docx · p6 · Launch schedule · row 4"
            caption="Launch schedule — approved_product_plan.docx · p6"
            rows={[
              ["Design freeze", "September 12, 2026"],
              ["Capacity review", "October 28, 2026"],
              ["Readiness review", "October 27, 2026"],
              ["Atlas GA", "November 3, 2026"],
              ["EU rollout", "November 30, 2026"],
            ]}
            markedRow={3}
            markedColumn={1}
            progress={progress}
          />
        </>
      );

    case "H20":
      return <PersonalWorld />;

    case "H21":
      return (
        <>
          <PersonalWorld showSourceStratum={false} />
          <PermissionBoundary
            points={[
              [620, 400],
              [900, 336],
              [1010, 470],
              [880, 610],
              [640, 560],
            ]}
            label="PRIVATE · ALICE"
            progress={window_(progress, 0, 0.5)}
          />
          <PermissionBoundary
            points={[
              [980, 320],
              [1330, 300],
              [1400, 520],
              [1120, 620],
              [960, 500],
            ]}
            label="SHARED · PLATFORM TEAM"
            progress={window_(progress, 0.3, 0.9)}
          />
        </>
      );

    case "H22":
      return (
        <>
          <PersonalWorld showSourceStratum={false} />
          {/* Heterogeneous systems, not more dots — §32.3's Enterprise
            * checkpoint. Each boundary is computed from the territories it
            * actually contains, so the claim "your knowledge lives in four
            * different systems" is drawn from the world instead of asserted
            * over it. */}
          {SYSTEM_BOUNDARIES.map((t, i) => (
            <PermissionBoundary
              key={t.label}
              points={t.points}
              label={t.label}
              progress={window_(progress, i * 0.12, i * 0.12 + 0.5)}
            />
          ))}
        </>
      );

    case "H23":
      return (
        <>
          <PersonalWorld />
          <Fade in={window_(progress, 0.2, 1)}>
            {WORLD_LABELS.map((l) => (
              <WorldLabel key={l.text} x={l.x} y={l.y} anchorX={l.ax} anchorY={l.ay}>
                {l.text}
              </WorldLabel>
            ))}
          </Fade>
        </>
      );

    default:
      return <PersonalWorld />;
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * Editorial and instrument layers.
 * ──────────────────────────────────────────────────────────────────────── */

/** §14.1 quiet status strip. Wide tracking, no filled badge. */
function QuietStatus({ shot, worldStateId }: { shot: Shot; worldStateId: string }) {
  const z = ZONES.E6_QUIET_STATUS;
  // §3.8/§14.1 — the strip is earned, appearing after brand lock.
  const brandLocked = shot.startSeconds >= 15.8;
  const items: string[] = [QUIET_STATUS.sample];
  if (brandLocked) {
    items.push(
      RECOMPILING_SHOTS.has(shot.id)
        ? QUIET_STATUS.worldStateRecompiling(worldStateId)
        : QUIET_STATUS.worldState(worldStateId),
    );
  }

  return (
    <div
      style={{
        position: "absolute",
        left: z.x,
        top: z.y,
        width: z.w,
        height: z.h,
        display: "flex",
        alignItems: "center",
        gap: 28,
      }}
    >
      {items.map((item) => (
        <span key={item} className="tvx-technical" style={{ maxWidth: "none" }}>
          {item}
        </span>
      ))}
    </div>
  );
}

/**
 * §14.4 — the question stays on screen while it is being answered.
 *
 * H09 and H18 ask; H10–H12 and H19 resolve. Capturing the board showed the
 * question vanishing the instant the candidates appeared, which leaves four
 * dates floating with nothing to be four answers *to*. The echo is set in the
 * query voice at reduced size: still the question, no longer the subject.
 */
const QUERY_ECHO: Readonly<Record<string, string>> = {
  H10: TRUTH_COPY.question,
  H11: TRUTH_COPY.question,
  H12: TRUTH_COPY.question,
  H19: CURRENT_ANSWER.question,
};

function QueryEcho({ shot }: { shot: Shot }) {
  const question = QUERY_ECHO[shot.id];
  if (!question) return null;
  const z = ZONES.E3_QUERY;
  return (
    <div style={{ position: "absolute", left: z.x, top: z.y, width: z.w }}>
      <p className="tvx-technical" style={{ margin: 0 }}>
        ASKED
      </p>
      <p
        className="tvx-query"
        style={{
          margin: "10px 0 0",
          fontSize: 20,
          color: "var(--tvx-fog-500)",
        }}
      >
        {question}
      </p>
    </div>
  );
}

/** §14.2 compile report. Tethered lines, never four statistic cards. */
function CompileReport({ shot, progress }: { shot: Shot; progress: number }) {
  if (shot.id !== "H16") return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 90,
        top: 620,
        width: 455,
        opacity: ease(window_(progress, 0.2, 0.8)),
      }}
    >
      <p className="tvx-numeric" style={{ margin: 0, fontSize: 34, color: "var(--tvx-warning-amber)" }}>
        <span className="tvx-tabular">{RECOMPILE_LEDGER.recompiling}</span>
        <span
          className="tvx-technical"
          style={{ marginLeft: 12, display: "inline", color: "var(--tvx-fog-500)" }}
        >
          {`RECOMPILING OF ${RECOMPILE_LEDGER.totalSampleObjects.toLocaleString("en-US")} `}
          <span style={{ color: "var(--tvx-steel-650)" }}>{SAMPLE_STATUS}</span>
        </span>
      </p>
    </div>
  );
}

function EditorialLayer({ shot, progress }: { shot: Shot; progress: number }) {
  const copy = SHOT_COPY[shot.id];
  if (!copy) return null;

  // §23.1 editorial territory: x 6.25%–40%, y 38%–60%. The brand lock sits a
  // little higher because it is a two-line block, not a three-line statement.
  const top = shot.id === "H08" ? 340 : shot.act === "SCALE" ? 360 : 342;
  const reveal = ease(window_(progress, 0.05, 0.55));

  return (
    <div
      style={{
        position: "absolute",
        left: 90,
        top,
        width: 560,
        opacity: reveal,
        transform: `translateY(${(1 - reveal) * 12}px)`,
      }}
    >
      {shot.id === "H08" ? (
        <>
          <p className="tvx-brand" style={{ margin: 0, letterSpacing: "0.02em" }}>
            {BRAND_LOCK.name}
          </p>
          <p
            className="tvx-technical"
            style={{ margin: "12px 0 0", color: "var(--tvx-bone-100)" }}
          >
            {BRAND_LOCK.category}
          </p>
          <p className="tvx-sub" style={{ margin: "28px 0 0", maxWidth: 520 }}>
            {copy.support}
          </p>
        </>
      ) : (
        <>
          <h2
            className={shot.act === "MESS" ? "tvx-h1" : "tvx-statement"}
            style={{ margin: 0, whiteSpace: "pre-line" }}
          >
            {copy.statement}
          </h2>
          {copy.support && (
            <p className="tvx-sub" style={{ margin: "22px 0 0", whiteSpace: "pre-line" }}>
              {copy.support}
            </p>
          )}
          {/* §1.6 — the technical name only after the plain sentence, and only
            * once the statement has settled. */}
          {copy.technical && (
            <p
              className="tvx-technical"
              style={{
                margin: "26px 0 0",
                maxWidth: 455,
                letterSpacing: "0.055em",
                opacity: ease(window_(progress, 0.55, 0.95)),
              }}
            >
              {copy.technical}
            </p>
          )}
        </>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
 * The stage.
 * ──────────────────────────────────────────────────────────────────────── */

export function HomeStage({
  shot,
  progress,
  worldStateId,
}: {
  shot: Shot;
  progress: number;
  worldStateId?: string;
}) {
  // §21.3 — the world state the frame reads is the one the beat has activated,
  // never a fixed label. H17 is the activation, so everything from there on
  // reads the recompiled id.
  const activated =
    worldStateId ??
    (shot.startSeconds >= 46.4 ? WORLD_STATES.recompiled : WORLD_STATES.initial);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        width: ARTBOARD.width,
        height: ARTBOARD.height,
        backgroundColor: "var(--tvx-graphite-900)",
        overflow: "hidden",
      }}
    >
      <svg
        width={ARTBOARD.width}
        height={ARTBOARD.height}
        style={{ position: "absolute", inset: 0 }}
        aria-hidden
      >
        <WorldLayer shot={shot} progress={progress} />
      </svg>

      <EditorialLayer shot={shot} progress={progress} />
      <QueryEcho shot={shot} />
      <CompileReport shot={shot} progress={progress} />
      <QuietStatus shot={shot} worldStateId={activated} />
    </div>
  );
}

export type { ShotId };
