/**
 * Truth contract — §0.4, §19.10, §21.3.
 *
 * The repository rule is that a numerical claim without a receipt is not
 * published. The cinematic makes that harder, not easier: the compile report
 * shows large figures that read like measurements. So every figure the
 * experience can render is declared here with its status, and the renderer has
 * no path to displaying a number that is not in this table.
 *
 * `illustrative` figures are honest scene-setting. They are never presented as
 * measured, and §0.4 requires the label to travel with them on screen.
 */

export type ClaimStatus =
  /** Backed by an artifact under docs/evidence/artifacts by sha256. */
  | "MEASURED"
  /** A plausible sample figure. Must render with its label visible. */
  | "ILLUSTRATIVE"
  /** Designed, not built. */
  | "PRODUCT_VISION"
  /** Built, not verified against a corpus. */
  | "PROTOTYPE"
  /** Committed to, not started. */
  | "PLANNED";

export type Figure = {
  readonly id: string;
  readonly value: string;
  readonly label: string;
  readonly status: ClaimStatus;
  /**
   * Required when status is MEASURED: the receipt this figure binds to.
   * Absent for every other status, which is why the type is optional here and
   * checked by `assertFigureIntegrity`.
   */
  readonly receipt?: string;
};

/**
 * §14.2 — the compile report. Never four statistic cards; each line tethers to
 * the topology it describes, which is why every figure carries a `tetherTo`.
 */
export const COMPILE_REPORT_FIGURES: readonly (Figure & {
  tetherTo: string;
})[] = [
  {
    id: "files",
    value: "1.2M",
    label: "files compiled from",
    status: "ILLUSTRATIVE",
    tetherTo: "world.source-stratum",
  },
  {
    id: "artifacts",
    value: "287K",
    label: "meaningful artifacts",
    status: "ILLUSTRATIVE",
    tetherTo: "world.semantic-layer",
  },
  {
    id: "projects",
    value: "34",
    label: "projects",
    status: "ILLUSTRATIVE",
    tetherTo: "world.project-territories",
  },
  {
    id: "people",
    value: "621",
    label: "people",
    status: "ILLUSTRATIVE",
    tetherTo: "world.people-clusters",
  },
  {
    id: "decisions",
    value: "12,490",
    label: "decisions",
    status: "ILLUSTRATIVE",
    tetherTo: "world.decision-marks",
  },
  {
    id: "conflicts",
    value: "8,200",
    label: "stale, duplicate or conflicting states",
    status: "ILLUSTRATIVE",
    tetherTo: "world.fault-zones",
  },
] as const;

/**
 * The sample mode banner. §0.4 requires this to be exposed at all times while
 * synthetic data is on screen — it is not a dismissible toast.
 */
export const SAMPLE_MODE_NOTICE = "SAMPLE WORKSPACE · SYNTHETIC DATA";

/**
 * §21.3 — truth gates, as machine-checkable assertions rather than a checklist
 * a reviewer ticks from memory. The experience tests import these ids.
 */
export const TRUTH_GATES = [
  {
    id: "figures-labelled",
    assertion:
      "Every public demo figure is labelled synthetic or illustrative unless measured.",
  },
  {
    id: "no-fake-confidence",
    assertion: "No confidence percentage is rendered anywhere.",
  },
  {
    id: "answer-has-evidence",
    assertion:
      "The current answer carries authority, applicability and time evidence.",
  },
  {
    id: "history-preserved",
    assertion: "Superseded facts remain historical rather than deleted.",
  },
  {
    id: "exception-not-conflict",
    assertion: "A scoped exception is never styled as a conflict.",
  },
  {
    id: "atomic-activation",
    assertion: "World state activates atomically; no partial state is ACTIVE.",
  },
  {
    id: "id-match",
    assertion: "answer.worldStateId equals evidence.worldStateId.",
  },
  {
    id: "fy2008-exact",
    assertion:
      "FY2008 values and their allowed interpretation are exact and unembellished.",
  },
] as const;

export type TruthGateId = (typeof TRUTH_GATES)[number]["id"];

/**
 * §19.10 — deterministic sample events. Sample mode emits exactly these; it
 * does not run an unrelated animation and call it processing.
 */
export const SAMPLE_EVENT_TYPES = [
  "source.admitted",
  "source.revised",
  "document.profiled",
  "route.selected",
  "inspection.failed",
  "document.rerouted",
  "recovery.completed",
  "knowledge.created",
  "identity.resolved",
  "conflict.detected",
  "impact.detected",
  "recompile.completed",
  "world_state.activated",
  "answer.resolved",
  "evidence.located",
] as const;

export type SampleEventType = (typeof SAMPLE_EVENT_TYPES)[number];

/**
 * Fails loudly rather than rendering an unbacked number. Called by the compile
 * report and by the truth tests; it is the fail-closed half of §21.3.
 */
export function assertFigureIntegrity(figure: Figure): void {
  if (figure.status === "MEASURED" && !figure.receipt) {
    throw new Error(
      `Figure "${figure.id}" claims MEASURED without a receipt. A measured ` +
        `figure binds to an artifact by sha256 or it is not published.`,
    );
  }
  if (figure.status !== "MEASURED" && figure.receipt) {
    throw new Error(
      `Figure "${figure.id}" carries a receipt but is not MEASURED. Either ` +
        `promote it or drop the receipt; a half-bound claim reads as proven.`,
    );
  }
}

/** True when a figure must render its status label alongside the value. */
export function requiresVisibleStatusLabel(figure: Figure): boolean {
  return figure.status !== "MEASURED";
}
