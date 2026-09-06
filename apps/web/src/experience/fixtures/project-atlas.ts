/**
 * Project Atlas semantic fixture — the Phase 0 truth freeze.
 *
 * This file is the single source for every id the guided proof depends on. The
 * §19.4 identity invariants are only checkable because the same literal ids
 * appear in the source, the fact, the answer and the evidence:
 *
 *   - the same source revision id survives from MESS to EVIDENCE
 *   - the same semantic occurrence id survives from extraction to fact
 *   - the same knowledge logical id survives across world-state versions
 *   - answer.worldStateId === evidence.worldStateId
 *
 * Two world states exist. `018291` is what A-09 reveals; `018292` is what C-04
 * activates after the selective recompile. They are not "before and after
 * screenshots" — the later one supersedes the earlier while the earlier stays
 * historical, which is the §21.3 rule that old facts are never deleted.
 */

import type { SampleEventType } from "../manifest/truth-contract";

export const WORLD_STATES = {
  /** Revealed at A-09, current through B-04. */
  initial: "SAMPLE-018291",
  /** Activated at C-04 after selective recompilation. */
  recompiled: "SAMPLE-018292",
} as const;

export type WorldStateId = (typeof WORLD_STATES)[keyof typeof WORLD_STATES];

/** §11.1 maps these to material and colour; none of them is a rainbow category. */
export type SourceState =
  | "active-approved"
  | "active-unapproved"
  | "superseded"
  | "scoped-exception";

export type SourceFamily =
  | "PolicyFolio"
  | "EmailThread"
  | "SpreadsheetSlab"
  | "CalendarTile"
  | "CodeDiffRibbon"
  | "MeetingNote"
  | "SignedContract";

export type SourceLocator = {
  readonly uri: string;
  readonly page?: number;
  readonly table?: string;
  readonly row?: number;
  readonly value: string;
};

export type SourceRevision = {
  readonly id: string;
  readonly family: SourceFamily;
  /** The filename a visitor recognises. §21.1 rejects placeholder documents. */
  readonly filename: string;
  readonly state: SourceState;
  readonly authority: "internal-approved" | "unapproved" | "external";
  readonly effectiveFrom: string;
  readonly locator: SourceLocator;
};

/**
 * The seven source families A-01 requires. Five must be distinguishable
 * without a legend for A-01 to pass its exit condition.
 */
export const SOURCE_REVISIONS: readonly SourceRevision[] = [
  {
    id: "source:atlas-approved-plan:r3",
    family: "PolicyFolio",
    filename: "approved_product_plan.docx",
    state: "active-approved",
    authority: "internal-approved",
    effectiveFrom: "2026-10-02",
    locator: {
      uri: "file://approved_product_plan.docx",
      page: 6,
      table: "Launch schedule",
      row: 4,
      value: "October 15",
    },
  },
  {
    id: "source:atlas-approved-plan:r4",
    family: "PolicyFolio",
    filename: "approved_product_plan.docx",
    state: "active-approved",
    authority: "internal-approved",
    effectiveFrom: "2026-11-01",
    locator: {
      uri: "file://approved_product_plan.docx",
      page: 6,
      table: "Launch schedule",
      row: 4,
      value: "November 3",
    },
  },
  {
    id: "source:atlas-launch-plan:r1",
    family: "PolicyFolio",
    filename: "launch_plan_draft.docx",
    state: "superseded",
    authority: "internal-approved",
    effectiveFrom: "2026-09-01",
    locator: {
      uri: "file://launch_plan_draft.docx",
      page: 2,
      value: "September 1",
    },
  },
  {
    id: "source:atlas-standup-note:r1",
    family: "MeetingNote",
    filename: "atlas_standup_0915.md",
    state: "active-unapproved",
    authority: "unapproved",
    effectiveFrom: "2026-09-15",
    locator: { uri: "file://atlas_standup_0915.md", value: "September 15" },
  },
  {
    id: "source:atlas-launch-calendar:r2",
    family: "CalendarTile",
    filename: "Project Atlas — Launch",
    state: "active-approved",
    authority: "internal-approved",
    effectiveFrom: "2026-10-02",
    locator: {
      uri: "calendar://project-atlas/launch-event",
      value: "October 15",
    },
  },
  {
    id: "source:atlas-vendor-thread:r1",
    family: "EmailThread",
    filename: "RE: Atlas launch logistics",
    state: "active-approved",
    authority: "external",
    effectiveFrom: "2026-10-04",
    locator: { uri: "mail://atlas/launch-logistics", value: "October 15" },
  },
  {
    id: "source:atlas-capacity-model:r7",
    family: "SpreadsheetSlab",
    filename: "atlas_capacity_model.xlsx",
    state: "active-approved",
    authority: "internal-approved",
    effectiveFrom: "2026-10-02",
    locator: {
      uri: "file://atlas_capacity_model.xlsx",
      table: "Ramp",
      row: 12,
      value: "October 15",
    },
  },
  {
    id: "source:atlas-release-gate:r2",
    family: "CodeDiffRibbon",
    filename: "release/atlas-gate.yaml",
    state: "active-approved",
    authority: "internal-approved",
    effectiveFrom: "2026-10-02",
    locator: { uri: "repo://release/atlas-gate.yaml", value: "2026-10-15" },
  },
  {
    id: "source:atlas-vendor-sow:r1",
    family: "SignedContract",
    filename: "atlas_launch_sow_signed.pdf",
    state: "scoped-exception",
    authority: "external",
    effectiveFrom: "2026-10-02",
    locator: {
      uri: "file://atlas_launch_sow_signed.pdf",
      page: 3,
      value: "EU rollout: November 30",
    },
  },
] as const;

/**
 * §5.2 candidate facts. Four candidates, one question, one current answer.
 * The two `superseded`/`unapproved` rows are what makes the resolution mean
 * something — they are not noise to be hidden.
 */
export type CandidateFact = {
  readonly occurrenceId: string;
  readonly sourceRevisionId: string;
  readonly value: string;
  readonly label: string;
  readonly resolution: "current" | "superseded" | "unapproved";
};

export const LAUNCH_DATE_CANDIDATES: readonly CandidateFact[] = [
  {
    occurrenceId: "occ:atlas-launch-date:draft-sep01",
    sourceRevisionId: "source:atlas-launch-plan:r1",
    value: "SEP 01",
    label: "superseded launch plan",
    resolution: "superseded",
  },
  {
    occurrenceId: "occ:atlas-launch-date:note-sep15",
    sourceRevisionId: "source:atlas-standup-note:r1",
    value: "SEP 15",
    label: "meeting note · unapproved",
    resolution: "unapproved",
  },
  {
    occurrenceId: "occ:atlas-launch-date:plan-oct15",
    sourceRevisionId: "source:atlas-approved-plan:r3",
    value: "OCT 15",
    label: "approved product plan · active",
    resolution: "current",
  },
  {
    occurrenceId: "occ:atlas-launch-date:calendar-oct15",
    sourceRevisionId: "source:atlas-launch-calendar:r2",
    value: "OCT 15",
    label: "launch calendar · active",
    resolution: "current",
  },
] as const;

/**
 * The compiled knowledge object A-07 assembles, plate by plate. Plate order is
 * the assembly order and the hover-separation order; it is not decorative.
 */
export type KnowledgePlate = {
  readonly kind: "VALUE" | "TYPE" | "SOURCE" | "TIME" | "AUTHORITY" | "REVISION";
  readonly text: string;
};

export type KnowledgeObject = {
  /** Stable across world-state versions — §19.4. */
  readonly logicalId: string;
  readonly worldStateId: WorldStateId;
  readonly plates: readonly KnowledgePlate[];
  readonly supportedBy: readonly string[];
};

export const LAUNCH_DATE_OBJECT: Readonly<
  Record<"initial" | "recompiled", KnowledgeObject>
> = {
  initial: {
    logicalId: "knowledge:project-atlas/launch-date",
    worldStateId: WORLD_STATES.initial,
    plates: [
      { kind: "VALUE", text: "October 15, 2026" },
      { kind: "TYPE", text: "Launch date" },
      // The plate names the source. The exact page/table/cell locator is the
      // Evidence Console's job (§14.3) and D-01's payoff — putting it here
      // overran the plate and duplicated the one place it has to be precise.
      { kind: "SOURCE", text: "approved_product_plan.docx" },
      { kind: "TIME", text: "Effective 2026-10-02" },
      { kind: "AUTHORITY", text: "Internal · approved" },
      { kind: "REVISION", text: "r3" },
    ],
    supportedBy: [
      "source:atlas-approved-plan:r3",
      "source:atlas-launch-calendar:r2",
    ],
  },
  recompiled: {
    logicalId: "knowledge:project-atlas/launch-date",
    worldStateId: WORLD_STATES.recompiled,
    plates: [
      { kind: "VALUE", text: "November 3, 2026" },
      { kind: "TYPE", text: "Launch date" },
      // The plate names the source. The exact page/table/cell locator is the
      // Evidence Console's job (§14.3) and D-01's payoff — putting it here
      // overran the plate and duplicated the one place it has to be precise.
      { kind: "SOURCE", text: "approved_product_plan.docx" },
      { kind: "TIME", text: "Effective 2026-11-01" },
      { kind: "AUTHORITY", text: "Internal · approved" },
      { kind: "REVISION", text: "r4" },
    ],
    supportedBy: [
      "source:atlas-approved-plan:r4",
      "source:atlas-launch-calendar:r2",
    ],
  },
} as const;

/**
 * C-02 and C-03. Exactly four objects are affected; the control set is what
 * proves selectivity, so it is declared rather than implied by absence.
 *
 * C-03's exit condition is a transform audit: every id in
 * `unaffectedControlSet` must be pixel-identical before and after. The test
 * reads this array, so adding an id here without making it genuinely stable
 * fails the gate rather than passing quietly.
 */
export const IMPACT_SET: readonly string[] = [
  "knowledge:project-atlas/launch-date",
  "knowledge:project-atlas/launch-readiness-review",
  "knowledge:project-atlas/marketing-freeze",
  "knowledge:project-atlas/eu-rollout-window",
] as const;

export const UNAFFECTED_CONTROL_SET: readonly string[] = [
  "knowledge:project-atlas/team-roster",
  "knowledge:project-atlas/pricing-tier",
  "knowledge:project-borealis/launch-date",
  "knowledge:project-borealis/owner",
  "knowledge:project-cassini/status",
  "knowledge:hr/leave-policy",
] as const;

/** §14.2 / C-03 label: "RECOMPILING 4 / SAMPLE 18,201". */
export const RECOMPILE_LEDGER = {
  recompiling: IMPACT_SET.length,
  totalSampleObjects: 18_201,
} as const;

/**
 * §5.4 answer and its evidence, bound to one world state. The pair is exported
 * together precisely so no component can render the answer with one id and the
 * evidence with another.
 */
export const CURRENT_ANSWER = {
  question: "WHAT IS THE CURRENT LAUNCH DATE?",
  value: "NOVEMBER 3",
  state: "CURRENT · APPROVED · EFFECTIVE",
  worldStateId: WORLD_STATES.recompiled,
  factLogicalId: "knowledge:project-atlas/launch-date",
  evidence: {
    worldStateId: WORLD_STATES.recompiled,
    sourceRevisionId: "source:atlas-approved-plan:r4",
    locator: {
      uri: "file://approved_product_plan.docx",
      page: 6,
      table: "Launch schedule",
      row: 4,
      value: "November 3",
    },
    excerpt:
      "Launch schedule — Atlas GA moves to November 3, 2026 following the capacity review of October 28.",
  },
} as const;

/**
 * §19.10 — the deterministic sample event sequence for the guided proof. Sample
 * mode replays exactly this; it never invents progress.
 */
export const SAMPLE_EVENT_SEQUENCE: readonly {
  type: SampleEventType;
  subjectId: string;
}[] = [
  { type: "source.admitted", subjectId: "source:atlas-approved-plan:r3" },
  { type: "document.profiled", subjectId: "source:atlas-approved-plan:r3" },
  { type: "route.selected", subjectId: "source:atlas-approved-plan:r3" },
  { type: "inspection.failed", subjectId: "source:atlas-vendor-sow:r1" },
  { type: "document.rerouted", subjectId: "source:atlas-vendor-sow:r1" },
  { type: "recovery.completed", subjectId: "source:atlas-vendor-sow:r1" },
  { type: "identity.resolved", subjectId: "entity:person/alice-kim" },
  { type: "knowledge.created", subjectId: "knowledge:project-atlas/launch-date" },
  { type: "conflict.detected", subjectId: "occ:atlas-launch-date:note-sep15" },
  { type: "world_state.activated", subjectId: WORLD_STATES.initial },
  { type: "answer.resolved", subjectId: "knowledge:project-atlas/launch-date" },
  { type: "source.revised", subjectId: "source:atlas-approved-plan:r4" },
  { type: "impact.detected", subjectId: "knowledge:project-atlas/launch-date" },
  { type: "recompile.completed", subjectId: WORLD_STATES.recompiled },
  { type: "world_state.activated", subjectId: WORLD_STATES.recompiled },
  { type: "answer.resolved", subjectId: "knowledge:project-atlas/launch-date" },
  { type: "evidence.located", subjectId: "source:atlas-approved-plan:r4" },
] as const;

/**
 * §19.4, made executable. The truth tests call this; it throws rather than
 * returning false so a broken lineage cannot be caught and ignored.
 */
export function assertIdentityInvariants(): void {
  const { evidence, worldStateId, factLogicalId } = CURRENT_ANSWER;

  if (evidence.worldStateId !== worldStateId) {
    throw new Error(
      "answer.worldStateId does not match evidence.worldStateId; the answer " +
        "and its proof are reading different world states.",
    );
  }

  const recompiled = LAUNCH_DATE_OBJECT.recompiled;
  if (recompiled.logicalId !== factLogicalId) {
    throw new Error(
      "The answer's fact id is absent from the recompiled world state.",
    );
  }
  if (LAUNCH_DATE_OBJECT.initial.logicalId !== recompiled.logicalId) {
    throw new Error(
      "The knowledge logical id changed across world-state versions; " +
        "identity must survive recompilation.",
    );
  }

  if (!recompiled.supportedBy.includes(evidence.sourceRevisionId)) {
    throw new Error(
      "The evidence source revision is not in the answer's lineage.",
    );
  }

  const known = new Set(SOURCE_REVISIONS.map((s) => s.id));
  for (const candidate of LAUNCH_DATE_CANDIDATES) {
    if (!known.has(candidate.sourceRevisionId)) {
      throw new Error(
        `Candidate ${candidate.occurrenceId} cites an unknown source revision.`,
      );
    }
  }

  const overlap = IMPACT_SET.filter((id) =>
    UNAFFECTED_CONTROL_SET.includes(id),
  );
  if (overlap.length > 0) {
    throw new Error(
      `Objects appear in both the impact set and the control set: ${overlap.join(", ")}`,
    );
  }
}
