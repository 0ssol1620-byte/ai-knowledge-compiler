import { describe, expect, it } from "vitest";

import { CAMERA_LIMITS, CAMERA_PRESETS } from "./manifest/cameras";
import {
  ARTBOARD,
  COMPOSITION_CONTRACTS,
  LABEL_BUDGETS,
  MIN_LABEL_PX,
  ZONES,
  normalizeZone,
} from "./manifest/layout";
import {
  CANONICAL_FPS,
  CANONICAL_SCENES,
  CONTROL_MODE_BOUNDARIES,
  SEQUENCE_DURATION_SECONDS,
  SHOTS,
  SHOTS_BY_ID,
  SUPERSEDED_2026_08_20_BOARD,
  TIMELINE_LABELS,
} from "./manifest/shots";
import {
  COMPILE_REPORT_FIGURES,
  assertFigureIntegrity,
  requiresVisibleStatusLabel,
} from "./manifest/truth-contract";
import {
  CURRENT_ANSWER,
  IMPACT_SET,
  LAUNCH_DATE_OBJECT,
  RECOMPILE_LEDGER,
  UNAFFECTED_CONTROL_SET,
  assertIdentityInvariants,
} from "./fixtures/project-atlas";
import {
  AFFECTED_OBJECT_POSITIONS,
  AFFECTED_OBJECT_SIZE,
  AFFECTED_SUBGRAPH_BOX,
  CENTROID,
  EDITORIAL_GUARD_X,
  TERRITORY_COUNT,
  TOPOLOGY,
  computeDensityCentroid,
} from "./world/topology";
import {
  experienceReducer,
  isStale,
  type ExperienceState,
} from "./state/experience-state";

/**
 * These are the spec's gates, executable.
 *
 * §21 lists them as checklists a reviewer ticks. A checklist catches a
 * regression on the day someone re-reads it; a test catches it on the commit
 * that caused it. Everything here is transcribed from a numbered rule, and the
 * section number is in the test name so a failure points at the clause rather
 * than at an opinion.
 */

describe("§8 shot board", () => {
  it("covers 0.00-66.00s with no gap and no overlap", () => {
    expect(SHOTS[0]?.startSeconds).toBe(0);
    expect(SHOTS.at(-1)?.endSeconds).toBe(SEQUENCE_DURATION_SECONDS);

    for (let i = 1; i < SHOTS.length; i += 1) {
      expect(SHOTS[i]?.startSeconds).toBeCloseTo(SHOTS[i - 1]!.endSeconds, 5);
    }
  });

  it("§8.2 derives frames as round(time * 60), ending one before the next shot", () => {
    for (let i = 0; i < SHOTS.length; i += 1) {
      const shot = SHOTS[i]!;
      expect(shot.startFrame).toBe(
        Math.round(shot.startSeconds * CANONICAL_FPS),
      );
      const next = SHOTS[i + 1];
      if (next) {
        expect(shot.endFrame).toBe(next.startFrame - 1);
      }
    }
  });

  it("names a camera preset that exists for every shot", () => {
    for (const shot of SHOTS) {
      expect(shot.camera.length).toBeGreaterThan(0);
      for (const id of shot.camera) {
        expect(CAMERA_PRESETS[id]).toBeDefined();
      }
    }
  });

  it("§19.5 resolves every timeline label to a real shot", () => {
    for (const shotId of Object.values(TIMELINE_LABELS)) {
      expect(SHOTS_BY_ID[shotId]).toBeDefined();
    }
  });

  it("gates implementation on the four canonical scenes both briefs name", () => {
    expect(CANONICAL_SCENES).toHaveLength(4);
    for (const scene of CANONICAL_SCENES) {
      expect(SHOTS_BY_ID[scene.shot], scene.key).toBeDefined();
    }
    expect(CANONICAL_SCENES.map((s) => s.key)).toEqual(["A", "B", "C", "D"]);
  });

  it("records what the 2026-08-21 board dropped rather than losing it", () => {
    // A-04 carried the "this compiler does not hide its failures" beat and has
    // no successor on the new board. Deleting the record would make that a
    // silent loss; the test exists so the omission stays visible in review.
    expect(SUPERSEDED_2026_08_20_BOARD.droppedBeats.map((b) => b.id)).toContain(
      "A-04",
    );
    expect(SUPERSEDED_2026_08_20_BOARD.shotCount).toBeGreaterThan(SHOTS.length);
  });

  it("flags the unresolved §5.2 / §5.3 control-mode boundary", () => {
    // §5.2 writes the Guided→Scale handover at 50.2s; §5.3's table puts the
    // last non-scale beat's end at 55.4s. Until the founder settles it, the
    // conflict is carried explicitly instead of one number quietly winning.
    expect(CONTROL_MODE_BOUNDARIES.unresolvedConflict).toBe(true);
    expect(CONTROL_MODE_BOUNDARIES.guidedEndsDerived).not.toBe(
      CONTROL_MODE_BOUNDARIES.guidedEndsAsWritten,
    );
    // Whatever it resolves to, the derived value must be a real shot boundary.
    expect(
      SHOTS.some((s) => s.endSeconds === CONTROL_MODE_BOUNDARIES.guidedEndsDerived),
    ).toBe(true);
  });
});

describe("§7 camera grammar", () => {
  it("§7.4 allows no unmotivated orbit and no production roll", () => {
    expect(CAMERA_LIMITS.unmotivatedOrbitDegrees).toBe(0);
    expect(CAMERA_LIMITS.productionRollDegrees).toBe(0);
    expect(CAMERA_LIMITS.springOvershoot).toBe(false);
    expect(CAMERA_LIMITS.perpetualBreathingScale).toBe(false);
  });

  it("§7.4 disables pointer parallax on mobile entirely", () => {
    expect(CAMERA_LIMITS.pointerParallaxMobile.yawDegrees).toBe(0);
    expect(CAMERA_LIMITS.pointerParallaxMobile.pitchDegrees).toBe(0);
  });

  it("keeps every preset's field of view inside the transcribed range", () => {
    for (const preset of Object.values(CAMERA_PRESETS)) {
      // 24° at the cell macro, 42° at enterprise scale. Anything outside that
      // is a transcription error, not a creative choice.
      expect(preset.fov).toBeGreaterThanOrEqual(24);
      expect(preset.fov).toBeLessThanOrEqual(42);
    }
  });
});

describe("§6 grid and composition", () => {
  it("keeps every zone inside the artboard", () => {
    for (const zone of Object.values(ZONES)) {
      expect(zone.x).toBeGreaterThanOrEqual(0);
      expect(zone.y).toBeGreaterThanOrEqual(0);
      expect(zone.x + zone.w).toBeLessThanOrEqual(ARTBOARD.width);
      expect(zone.y + zone.h).toBeLessThanOrEqual(ARTBOARD.height);
    }
  });

  it("§6.4 keeps the Evidence Console under 27% of screen width", () => {
    const ratio = ZONES.E4_EVIDENCE_CONSOLE.w / ARTBOARD.width;
    expect(ratio).toBeLessThanOrEqual(
      COMPOSITION_CONTRACTS.evidenceConsoleMaxScreenWidth,
    );
  });

  it("§6.4 anchors the hero left and never centres it", () => {
    expect(COMPOSITION_CONTRACTS.heroCentred).toBe(false);
    expect(COMPOSITION_CONTRACTS.heroBaselineX).toBe(90);
    expect(ZONES.E1_EDITORIAL.x).toBe(COMPOSITION_CONTRACTS.heroBaselineX);
  });

  it("§6.4 separates editorial from world by density, not by exclusion", () => {
    // The zones overlap on purpose: E1 runs 90–610 and E2 runs 540–1440. An
    // earlier version of this test asserted they must not, which reads like
    // the safer rule and is not the spec's. E2 is the *stage* the camera
    // frames, not a box copy is forbidden to enter; what §6.4 actually
    // constrains is that the left region stays low density. Asserting
    // non-overlap would have forced the world 70px right of where the shot
    // specs put it, to satisfy a rule nobody wrote.
    expect(ZONES.E1_EDITORIAL.x + ZONES.E1_EDITORIAL.w).toBeGreaterThan(
      ZONES.E2_WORLD.x,
    );
    // The guard that does bind is the density line, and it sits left of where
    // the world stage begins.
    expect(COMPOSITION_CONTRACTS.editorialTerritoryMaxX).toBeLessThan(
      ZONES.E2_WORLD.x,
    );
  });

  it("§6.4 keeps the copy column inside its absolute ceiling", () => {
    expect(COMPOSITION_CONTRACTS.mainCopyMaxWidth).toBeLessThanOrEqual(
      COMPOSITION_CONTRACTS.mainCopyAbsoluteCeiling,
    );
    expect(
      COMPOSITION_CONTRACTS.heroBaselineX +
        COMPOSITION_CONTRACTS.mainCopyAbsoluteCeiling,
    ).toBeLessThanOrEqual(ARTBOARD.width);
  });

  it("§6.1 normalises a zone to percentages of the artboard", () => {
    const n = normalizeZone(ZONES.E1_EDITORIAL);
    expect(n.left).toBe("6.2500%");
    expect(n.width).toBe("36.1111%");
  });

  it("holds technical labels at the 12px floor of the 2026-08-21 §22.4", () => {
    expect(MIN_LABEL_PX).toBe(12);
  });

  it("keeps every affected object inside C-03's subgraph box", () => {
    for (const [id, [x, y]] of Object.entries(AFFECTED_OBJECT_POSITIONS)) {
      expect(x, id).toBeGreaterThanOrEqual(AFFECTED_SUBGRAPH_BOX.x.min);
      expect(y, id).toBeGreaterThanOrEqual(AFFECTED_SUBGRAPH_BOX.y.min);
      // The whole footprint, not just the anchor. Checking the anchor alone is
      // how the marketing-freeze plate escaped the box unnoticed when the
      // objects were widened to carry 12px text.
      expect(x + AFFECTED_OBJECT_SIZE.width, id).toBeLessThanOrEqual(
        AFFECTED_SUBGRAPH_BOX.x.max,
      );
      expect(y + AFFECTED_OBJECT_SIZE.height, id).toBeLessThanOrEqual(
        AFFECTED_SUBGRAPH_BOX.y.max,
      );
    }
  });

  it("§13.3 keeps mobile label budgets below desktop for every act", () => {
    for (const [act, budget] of Object.entries(LABEL_BUDGETS)) {
      expect(budget.mobile, act).toBeLessThan(budget.desktop);
      expect(budget.required, act).not.toBe("");
    }
  });
});

describe("§3.6 / §6.4 authored world topology", () => {
  it("builds the 34 territories the compile report claims", () => {
    expect(TOPOLOGY.territories).toHaveLength(TERRITORY_COUNT);
    const projects = COMPILE_REPORT_FIGURES.find((f) => f.id === "projects");
    expect(projects?.value).toBe(String(TERRITORY_COUNT));
  });

  it("lands the visible density centroid inside the §6.4 target box", () => {
    const measured = computeDensityCentroid();
    const box = COMPOSITION_CONTRACTS.worldCentroid;
    expect(measured.x).toBeGreaterThanOrEqual(box.x.min);
    expect(measured.x).toBeLessThanOrEqual(box.x.max);
    expect(measured.y).toBeGreaterThanOrEqual(box.y.min);
    expect(measured.y).toBeLessThanOrEqual(box.y.max);
  });

  it("keeps every territory out of editorial territory", () => {
    for (const t of TOPOLOGY.territories) {
      // The plate's left extent, not just its centre: a wide territory whose
      // centre clears the guard can still put geometry under the headline.
      expect(t.cx - t.radius, t.id).toBeGreaterThan(EDITORIAL_GUARD_X - 40);
    }
  });

  it("§6.4 continues the world past the right and bottom edges", () => {
    const beyondRight = TOPOLOGY.territories.some(
      (t) => t.cx + t.radius > ARTBOARD.width,
    );
    const beyondBottom = TOPOLOGY.territories.some(
      (t) => t.cy + t.radius * 0.52 > ARTBOARD.height,
    );
    expect(beyondRight).toBe(true);
    expect(beyondBottom).toBe(true);
  });

  it("is deterministic, so a screenshot diff means a real change", () => {
    const a = computeDensityCentroid();
    const b = computeDensityCentroid();
    expect(a).toEqual(b);
    expect(TOPOLOGY.territories[0]?.cx).toBe(CENTROID.x);
  });

  it("§13.1 keeps inter-project bridges sparse", () => {
    expect(TOPOLOGY.bridges.length).toBeLessThanOrEqual(12);
    const ids = new Set(TOPOLOGY.territories.map((t) => t.id));
    for (const bridge of TOPOLOGY.bridges) {
      expect(ids.has(bridge.from)).toBe(true);
      expect(ids.has(bridge.to)).toBe(true);
      expect(bridge.from).not.toBe(bridge.to);
    }
  });
});

describe("§21.3 truth gates", () => {
  it("§19.4 holds every identity invariant across the guided proof", () => {
    expect(() => assertIdentityInvariants()).not.toThrow();
  });

  it("binds the answer and its evidence to one world state", () => {
    expect(CURRENT_ANSWER.evidence.worldStateId).toBe(
      CURRENT_ANSWER.worldStateId,
    );
  });

  it("keeps the knowledge logical id stable across recompilation", () => {
    expect(LAUNCH_DATE_OBJECT.initial.logicalId).toBe(
      LAUNCH_DATE_OBJECT.recompiled.logicalId,
    );
    expect(LAUNCH_DATE_OBJECT.initial.worldStateId).not.toBe(
      LAUNCH_DATE_OBJECT.recompiled.worldStateId,
    );
  });

  it("C-03 recompiles exactly the impact set and nothing else", () => {
    expect(RECOMPILE_LEDGER.recompiling).toBe(IMPACT_SET.length);
    expect(RECOMPILE_LEDGER.recompiling).toBeLessThan(
      RECOMPILE_LEDGER.totalSampleObjects,
    );
    for (const id of UNAFFECTED_CONTROL_SET) {
      expect(IMPACT_SET).not.toContain(id);
    }
  });

  it("labels every unmeasured figure and refuses a half-bound claim", () => {
    for (const figure of COMPILE_REPORT_FIGURES) {
      expect(() => assertFigureIntegrity(figure)).not.toThrow();
      expect(requiresVisibleStatusLabel(figure)).toBe(true);
    }

    // deslop-ignore 29 — the two figures below are the rejects. They exist to
    // prove the guard throws on an unbacked "99.9% accuracy", which is the
    // exact claim CLAUDE.md's evidence rules forbid publishing.
    expect(() =>
      assertFigureIntegrity({
        id: "fake",
        value: "99.9%",
        label: "accuracy",
        status: "MEASURED",
      }),
    ).toThrow(/without a receipt/);

    expect(() =>
      assertFigureIntegrity({
        id: "fake",
        value: "99.9%",
        label: "accuracy",
        status: "ILLUSTRATIVE",
        receipt: "sha256:...",
      }),
    ).toThrow(/half-bound/);
  });

  it("renders no confidence percentage anywhere in the report", () => {
    for (const figure of COMPILE_REPORT_FIGURES) {
      expect(figure.value).not.toMatch(/%$/);
    }
  });
});

describe("§19 experience state", () => {
  const base: ExperienceState = {
    act: "COMPILE",
    shot: "H08",
    controlMode: "director",
    worldStateId: "SAMPLE-018291",
    impactSet: [],
    unaffectedControlSet: [],
    motionMode: "full",
    qualityTier: "high",
    projection: "world",
    sampleMode: true,
    paused: false,
    intentEpoch: 0,
  };

  it("§19.5 bumps the intent epoch on user intent only", () => {
    const afterCheckpoint = experienceReducer(base, {
      type: "checkpoint",
      shot: "H09",
      act: "TRUTH",
    });
    expect(afterCheckpoint.intentEpoch).toBe(0);

    const afterSelect = experienceReducer(base, {
      type: "select",
      objectId: "knowledge:project-atlas/launch-date",
    });
    expect(afterSelect.intentEpoch).toBe(1);
  });

  it("§19.5 cancels a transition issued under a stale epoch", () => {
    const issuedEpoch = base.intentEpoch;
    const next = experienceReducer(base, { type: "exploreNow" });
    expect(isStale(next, issuedEpoch)).toBe(true);
    expect(isStale(next, next.intentEpoch)).toBe(false);
  });

  it("§14.5 keeps the selection when the projection changes", () => {
    const selected = experienceReducer(base, {
      type: "select",
      objectId: "knowledge:project-atlas/launch-date",
    });
    const projected = experienceReducer(selected, {
      type: "setProjection",
      projection: "source",
    });
    expect(projected.selectedObjectId).toBe(selected.selectedObjectId);
    expect(projected.projection).toBe("source");
  });

  it("§18.1 treats skip as reduced motion, not as no motion", () => {
    const skipped = experienceReducer(base, { type: "skipMotion" });
    expect(skipped.motionMode).toBe("reduced");
    expect(skipped.motionMode).not.toBe("none");
  });

  it("§21.3 activates a world state atomically", () => {
    const activated = experienceReducer(base, {
      type: "activateWorldState",
      worldStateId: "SAMPLE-018292",
    });
    expect(activated.worldStateId).toBe("SAMPLE-018292");
  });
});
