/**
 * Semantic state contract — §19.3, with the intent-epoch rule of §19.5.
 *
 * The epoch is the part that is easy to leave out and expensive to add later.
 * Every user intent increments it; every asynchronous camera move, timeline
 * callback and asset arrival carries the epoch it was issued under and is
 * dropped on arrival if the epoch has moved. Without it, a visitor who presses
 * "Explore now" mid-transition gets the old transition landing on top of their
 * choice a second later.
 */

import type { ActId, ShotId } from "../manifest/shots";
import type { WorldStateId } from "../fixtures/project-atlas";

export type MotionMode = "full" | "reduced" | "none";
export type QualityTier = "high" | "medium" | "low" | "fallback";
export type ControlMode = "director" | "guided" | "scale" | "explore";
export type Projection = "world" | "knowledge" | "source";

export type ExperienceState = {
  readonly act: ActId;
  readonly shot: ShotId;
  readonly controlMode: ControlMode;
  readonly worldStateId: WorldStateId;
  readonly selectedObjectId?: string;
  readonly selectedSourceRevisionId?: string;
  readonly queryId?: string;
  readonly answerFactId?: string;
  readonly impactSet: readonly string[];
  readonly unaffectedControlSet: readonly string[];
  readonly motionMode: MotionMode;
  readonly qualityTier: QualityTier;
  readonly projection: Projection;
  readonly sampleMode: boolean;
  readonly paused: boolean;
  readonly intentEpoch: number;
};

export type ExperienceAction =
  /** The timeline reached a semantic checkpoint after visual settle. */
  | { type: "checkpoint"; shot: ShotId; act: ActId }
  | { type: "activateWorldState"; worldStateId: WorldStateId }
  | { type: "select"; objectId: string | undefined }
  | { type: "selectSourceRevision"; sourceRevisionId: string | undefined }
  | { type: "setImpact"; impactSet: readonly string[]; unaffected: readonly string[] }
  | { type: "resolveAnswer"; factId: string; queryId: string }
  | { type: "setProjection"; projection: Projection }
  | { type: "setMotionMode"; motionMode: MotionMode }
  | { type: "setQualityTier"; qualityTier: QualityTier }
  | { type: "pause" }
  | { type: "resume" }
  | { type: "skipMotion" }
  | { type: "exploreNow" };

/**
 * Actions the visitor initiated. These bump the epoch; timeline-driven
 * checkpoints do not, or the sequence would invalidate its own transitions on
 * every shot boundary.
 */
const USER_INTENTS: ReadonlySet<ExperienceAction["type"]> = new Set([
  "select",
  "selectSourceRevision",
  "setProjection",
  "setMotionMode",
  "pause",
  "resume",
  "skipMotion",
  "exploreNow",
]);

export function isUserIntent(action: ExperienceAction): boolean {
  return USER_INTENTS.has(action.type);
}

export function experienceReducer(
  state: ExperienceState,
  action: ExperienceAction,
): ExperienceState {
  const epoch = isUserIntent(action)
    ? state.intentEpoch + 1
    : state.intentEpoch;

  switch (action.type) {
    case "checkpoint":
      return { ...state, shot: action.shot, act: action.act };

    case "activateWorldState":
      // §21.3 — activation is atomic. The id flips in one reduction; there is
      // no intermediate state in which half the world reads the new id.
      return { ...state, worldStateId: action.worldStateId, intentEpoch: epoch };

    case "select":
      return { ...state, selectedObjectId: action.objectId, intentEpoch: epoch };

    case "selectSourceRevision":
      return {
        ...state,
        selectedSourceRevisionId: action.sourceRevisionId,
        intentEpoch: epoch,
      };

    case "setImpact":
      return {
        ...state,
        impactSet: action.impactSet,
        unaffectedControlSet: action.unaffected,
      };

    case "resolveAnswer":
      return {
        ...state,
        answerFactId: action.factId,
        queryId: action.queryId,
      };

    case "setProjection":
      // §14.5 — the selected object id persists across projections. Switching
      // the lens must not drop the selection.
      return { ...state, projection: action.projection, intentEpoch: epoch };

    case "setMotionMode":
      return { ...state, motionMode: action.motionMode, intentEpoch: epoch };

    case "setQualityTier":
      return { ...state, qualityTier: action.qualityTier };

    case "pause":
      return { ...state, paused: true, intentEpoch: epoch };

    case "resume":
      return { ...state, paused: false, intentEpoch: epoch };

    case "skipMotion":
      // §18.1 — reduced is a complete narrative, not "animation off". The
      // static checkpoints stay; only travel and parallax stop.
      return { ...state, motionMode: "reduced", intentEpoch: epoch };

    case "exploreNow":
      return {
        ...state,
        controlMode: "explore",
        paused: false,
        intentEpoch: epoch,
      };

    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}

/**
 * A transition issued under `issuedEpoch` may only land while the epoch is
 * unchanged. §19.5: stale camera and timeline transitions cancel.
 */
export function isStale(state: ExperienceState, issuedEpoch: number): boolean {
  return issuedEpoch !== state.intentEpoch;
}
