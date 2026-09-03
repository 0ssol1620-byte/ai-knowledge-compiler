/**
 * Master shot board — MANUS_COMPLETE_WEBSITE_EXPERIENCE_FREE_ASSET_MASTER_BRIEF
 * (2026-08-21) §5.3, which supersedes CINEMATIC_DESIGN_MASTER_SPEC (2026-08-20)
 * §8.1 under the newer brief's §0.1 authority order.
 *
 * The board was rewritten, not renamed. H00–H23 is a different cut of the same
 * causal chain: 24 beats where the older board had 27, retimed throughout, with
 * SOURCE REGISTRATION added as its own beat and CATEGORY LOCK split out of the
 * world reveal. The superseded board is kept below rather than deleted — the
 * same rule the product itself runs on, that a superseded fact stays historical
 * and inspectable (2026-08-20 §21.3).
 *
 * Frame law: start_frame = round(start_time * 60) at 60fps canonical. A shot's
 * end frame is the next shot's start frame minus one.
 */

import type { CameraPresetId } from "./cameras";

export const CANONICAL_FPS = 60;

/**
 * §5.3's last beat is written "65.0–66+" — the sequence does not stop, it hands
 * over. 66.0 is the handover instant, and Explore runs from there.
 */
export const SEQUENCE_DURATION_SECONDS = 66;

export type ActId =
  | "VOID"
  | "MESS"
  | "REGISTER"
  | "DISCOVER"
  | "RESOLVE"
  | "COMPILE"
  | "CATEGORY"
  | "TRUTH"
  | "CHANGE"
  | "ASK"
  | "EVIDENCE"
  | "SCALE"
  | "ACTIVATE";

export type ShotId =
  | "H00" | "H01" | "H02" | "H03" | "H04" | "H05"
  | "H06" | "H07" | "H08" | "H09" | "H10" | "H11"
  | "H12" | "H13" | "H14" | "H15" | "H16" | "H17"
  | "H18" | "H19" | "H20" | "H21" | "H22" | "H23";

export type Shot = {
  readonly id: ShotId;
  readonly act: ActId;
  /** §5.3's beat name, verbatim. */
  readonly beat: string;
  readonly startSeconds: number;
  readonly endSeconds: number;
  readonly startFrame: number;
  readonly endFrame: number;
  /**
   * Camera presets are **derived, not transcribed**. The 2026-08-21 brief
   * restates the camera *law* (§23.2) but not the preset table, so §7.2 of the
   * 2026-08-20 spec still supplies the numbers and the mapping from beat to
   * preset is this file's inference. Treat a preset here as a proposal a
   * reviewer can overrule; treat the times and beats as founder-locked.
   */
  readonly camera: readonly CameraPresetId[];
  /** §5.3's "Visitor takeaway" column, verbatim. */
  readonly takeaway: string;
};

const shot = (
  id: ShotId,
  act: ActId,
  beat: string,
  startSeconds: number,
  endSeconds: number,
  camera: readonly CameraPresetId[],
  takeaway: string,
): Shot => ({
  id,
  act,
  beat,
  startSeconds,
  endSeconds,
  startFrame: Math.round(startSeconds * CANONICAL_FPS),
  endFrame: Math.round(endSeconds * CANONICAL_FPS) - 1,
  camera,
  takeaway,
});

export const SHOTS: readonly Shot[] = [
  shot("H00", "VOID", "VOID / REALITY HINT", 0.0, 1.2, ["P0_VOID"],
    "Something precise is beginning."),
  shot("H01", "MESS", "YOUR WORK IS EVERYWHERE", 1.2, 3.4, ["P1_MESS_NEAR"],
    "My work is scattered."),
  shot("H02", "REGISTER", "SOURCE REGISTRATION", 3.4, 5.6, ["P1_MESS_NEAR"],
    "TAVONEL sees source structure."),
  shot("H03", "DISCOVER", "SEMANTIC EXTRACTION", 5.6, 7.7, ["P2_DISCOVER"],
    "It understands meaning."),
  shot("H04", "RESOLVE", "IDENTITY RESOLUTION", 7.7, 9.3, ["P3_RESOLVE"],
    "It knows when things refer to the same thing."),
  shot("H05", "RESOLVE", "VERSION / AUTHORITY RESOLUTION", 9.3, 10.9, ["P3_RESOLVE"],
    "It resolves versions and current state."),
  shot("H06", "COMPILE", "COMPILED KNOWLEDGE OBJECT", 10.9, 12.6, ["P4_COMPILE_CLOSE"],
    "A fact is more than text."),
  shot("H07", "COMPILE", "WORLD REVEAL", 12.6, 15.8, ["P5_WORLD_HERO"],
    "My digital world can be compiled."),
  shot("H08", "CATEGORY", "CATEGORY LOCK", 15.8, 18.8, ["P5_WORLD_HERO"],
    "I know what category this is."),
  shot("H09", "TRUTH", "QUERY", 18.8, 22.5, ["P6_TRUTH"],
    "Ask the current world."),
  shot("H10", "TRUTH", "CANDIDATE FACTS", 22.5, 26.2, ["P6_TRUTH"],
    "Documents disagree."),
  shot("H11", "TRUTH", "CURRENT TRUTH", 26.2, 29.4, ["P6_TRUTH"],
    "It knows which answer is current."),
  shot("H12", "TRUTH", "PROVENANCE HINT", 29.4, 32.0, ["P6_TRUTH"],
    "The answer has a source."),
  shot("H13", "CHANGE", "SOURCE CHANGE", 32.0, 35.2, ["P7_CHANGE"],
    "The world changed."),
  shot("H14", "CHANGE", "SEMANTIC DIFF", 35.2, 38.2, ["P7_CHANGE"],
    "It understands what changed."),
  shot("H15", "CHANGE", "IMPACT FIELD", 38.2, 42.2, ["P8_IMPACT_WIDE"],
    "It knows what the change affects."),
  shot("H16", "CHANGE", "SELECTIVE RECOMPILATION", 42.2, 46.4, ["P8_IMPACT_WIDE"],
    "Only affected knowledge is updated."),
  shot("H17", "CHANGE", "NEW WORLD STATE", 46.4, 48.8, ["P8_IMPACT_WIDE"],
    "A new current state is active."),
  shot("H18", "ASK", "ANSWER", 48.8, 52.0, ["P9_ANSWER"],
    "The answer changed because reality changed."),
  shot("H19", "EVIDENCE", "EVIDENCE DIVE", 52.0, 55.4,
    ["P10_EVIDENCE_APPROACH", "P11_CELL_MACRO"],
    "Every answer has a way home."),
  shot("H20", "SCALE", "PERSONAL", 55.4, 58.6, ["P12_PERSONAL_WIDE"],
    "This can understand my own work."),
  shot("H21", "SCALE", "TEAM", 58.6, 62.0, ["P13_TEAM_WIDE"],
    "Teams need shared truth without losing boundaries."),
  shot("H22", "SCALE", "ENTERPRISE", 62.0, 65.0, ["P14_ENTERPRISE"],
    "This scales to the organization."),
  shot("H23", "ACTIVATE", "YOUR TURN", 65.0, 66.0, ["P15_EXPLORE"],
    "Now I can explore it."),
] as const;

export const SHOTS_BY_ID: Readonly<Record<ShotId, Shot>> = Object.fromEntries(
  SHOTS.map((s) => [s.id, s]),
) as Readonly<Record<ShotId, Shot>>;

/**
 * Control modes — §5.2.
 *
 * **These boundaries disagree with the §5.3 shot table and the disagreement is
 * not resolved here.** §5.2 places Guided Proof at roughly 15.8–50.2s and Scale
 * Reveal at 50.2–66s, but §5.3 runs ANSWER to 52.0, EVIDENCE DIVE to 55.4, and
 * only starts PERSONAL — the first scale beat — at 55.4. The gap is 5.2s.
 *
 * §5.2 says "approximately" and its numbers are inherited unchanged from the
 * 2026-08-20 board, whose beats they did fit; §5.3 is the new material. That
 * suggests the table is right and §5.2 is a stale carry-over, which is why the
 * derived boundary below follows the table. It is flagged rather than silently
 * corrected: if the intent really is a hard 50.2s handover, three beats move.
 */
export const CONTROL_MODE_BOUNDARIES = {
  directorEnds: 15.8,
  /** Derived from §5.3: the last non-scale beat, H19, ends here. */
  guidedEndsDerived: 55.4,
  /** As literally written in §5.2. Conflicts with the line above. */
  guidedEndsAsWritten: 50.2,
  exploreBegins: 66.0,
  unresolvedConflict: true,
} as const;

/**
 * Timeline labels — 2026-08-20 §19.5, remapped onto the new board. One labelled
 * semantic timeline; never scattered setTimeout calls.
 */
export const TIMELINE_LABELS = {
  H00_VOID: "H00",
  H01_MESS: "H01",
  H02_REGISTER: "H02",
  H03_DISCOVER: "H03",
  H04_IDENTITY: "H04",
  H06_COMPILE: "H06",
  H07_WORLD: "H07",
  H08_CATEGORY: "H08",
  H11_TRUTH: "H11",
  H13_CHANGE: "H13",
  H15_IMPACT: "H15",
  H16_RECOMPILE: "H16",
  H19_EVIDENCE: "H19",
  H23_EXPLORE: "H23",
} as const satisfies Record<string, ShotId>;

export type TimelineLabel = keyof typeof TIMELINE_LABELS;

/**
 * The four canonical scenes both documents independently gate on.
 *
 * 2026-08-20 §20.1 named four frames that must be founder-approved before full
 * implementation. The 2026-08-21 brief's §33/§34 PHASE 2 names four canonical
 * scenes to finish first — and they are the same four, arrived at separately.
 * That agreement is the reason this gate survived the supersession intact when
 * the shot board around it did not.
 */
export const CANONICAL_SCENES = [
  { key: "A", copy: "YOUR WORK IS EVERYWHERE", shot: "H01", supersedes: "A-01" },
  { key: "B", copy: "COMPILED KNOWLEDGE OBJECT", shot: "H06", supersedes: "A-07" },
  {
    key: "C",
    copy: "YOUR DIGITAL WORLD, COMPILED",
    // §5.4 runs the statement and the brand lock as one copy block. The new
    // board splits it: H07 is the world reveal that carries the sentence, H08
    // is the category lock that carries the name. A-09's exit condition needs
    // both — "the first large WOW and the new category definition complete
    // together" — so the scene is approved as a pair rather than at whichever
    // half happens to sit on the boundary.
    shot: "H08",
    companionShot: "H07",
    supersedes: "A-09",
  },
  { key: "D", copy: "ONLY AFFECTED KNOWLEDGE IS UPDATED", shot: "H16", supersedes: "C-03" },
] as const satisfies readonly {
  key: string;
  copy: string;
  shot: ShotId;
  /** Present only where the new board split one approved scene in two. */
  companionShot?: ShotId;
  supersedes: string;
}[];

export type CanonicalSceneKey = (typeof CANONICAL_SCENES)[number]["key"];

/** Every frame the founder gate has to see, companions included. */
export const FOUNDER_APPROVAL_KEYFRAMES: readonly ShotId[] =
  CANONICAL_SCENES.flatMap((s) =>
    "companionShot" in s && s.companionShot ? [s.companionShot, s.shot] : [s.shot],
  );

/**
 * The superseded 2026-08-20 §8.1 board, kept for traceability.
 *
 * Two beats have no successor on the new board, and that is worth noticing
 * rather than discovering later:
 *
 *   - `A-02` MESS / SCALE WITHOUT CHAOS — scale of the scattering
 *   - `A-04` ROUTE / RECOVER MICRO-PROOF — the one-second beat that showed the
 *     compiler does not hide its own failures
 *
 * A-04 in particular carried a trust claim nothing else in the sequence makes.
 * Its absence from §5.3 may be deliberate compression or may be an oversight;
 * this file does not decide, it records.
 */
export const SUPERSEDED_2026_08_20_BOARD = {
  shotCount: 27,
  idRange: "A-00 … E-03",
  droppedBeats: [
    { id: "A-02", beat: "MESS / SCALE WITHOUT CHAOS" },
    { id: "A-04", beat: "ROUTE / RECOVER MICRO-PROOF" },
  ],
  retimedExamples: [
    { was: "A-01 0.60–2.10s", now: "H01 1.20–3.40s" },
    { was: "A-07 9.60–11.40s", now: "H06 10.90–12.60s" },
    { was: "A-09 13.10–15.80s", now: "H07 12.60–15.80s + H08 15.80–18.80s" },
    { was: "C-03 36.00–39.20s", now: "H16 42.20–46.40s" },
  ],
} as const;

/**
 * Visual-regression checkpoints. The 2026-08-20 §21.7 frame numbers were keyed
 * to the old board and are meaningless against the new one, so they are
 * re-derived: each canonical scene is captured at its settled end frame, which
 * is what §21.7 was actually asking for.
 */
export const SCREENSHOT_CHECKPOINTS: readonly {
  shot: ShotId;
  frame: number;
  name: string;
}[] = FOUNDER_APPROVAL_KEYFRAMES.map((shot) => ({
  shot,
  frame: SHOTS_BY_ID[shot].endFrame,
  name:
    CANONICAL_SCENES.find(
      (s) => s.shot === shot || ("companionShot" in s && s.companionShot === shot),
    )?.copy ?? SHOTS_BY_ID[shot].beat,
}));
