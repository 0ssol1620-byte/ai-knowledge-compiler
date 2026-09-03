/**
 * Phase 3 gates.
 *
 * These render the real stage rather than assert against a description of it.
 * A test that checks the manifest agrees with itself proves nothing about what
 * a visitor sees; the defects this phase can actually produce are a beat that
 * throws, a beat that draws nothing, and a beat whose copy appears in the wrong
 * order. So every one of the 24 beats is rendered, at three points in its own
 * progress, and inspected.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SHOTS, SHOTS_BY_ID, CANONICAL_SCENES } from "../manifest/shots";
import { SHOT_COPY } from "../manifest/copy";
import { WORLD_STATES } from "../fixtures/project-atlas";
import { ARTBOARD } from "../manifest/layout";
import { HomeStage } from "./home-stage";
import { narrate } from "./narration";

function render(shotId: string, progress: number): string {
  const shot = SHOTS_BY_ID[shotId as keyof typeof SHOTS_BY_ID];
  return renderToStaticMarkup(<HomeStage shot={shot} progress={progress} />);
}

/** Strips tags so a text assertion is about text, not about markup. */
function textOf(html: string): string {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

describe("HomeStage renders every beat", () => {
  for (const shot of SHOTS) {
    it(`${shot.id} — ${shot.beat}`, () => {
      for (const progress of [0, 0.5, 1]) {
        const html = render(shot.id, progress);
        // Every beat must put something on screen. H00 is the darkest and is
        // still two barely-emerging fragments, not an empty frame.
        expect(html.length).toBeGreaterThan(400);
      }
    });
  }
});

describe("§1.6 — plain sentence before technical name", () => {
  it("no shot carries a technical annotation without a statement", () => {
    for (const [id, copy] of Object.entries(SHOT_COPY)) {
      if (copy.technical) {
        expect(copy.statement, `${id} has a technical label and no statement`)
          .toBeTruthy();
      }
    }
  });

  it("the technical annotation is absent early in the beat and present once settled", () => {
    // H05's technical line is AUTHORITY · APPLICABILITY · TEMPORAL VALIDITY.
    // At the start of the shot it must not be leading the plain sentence.
    const early = render("H05", 0.1);
    const settled = render("H05", 1);
    const needle = "AUTHORITY · APPLICABILITY";

    // It is rendered at opacity 0 rather than removed, so the check is on the
    // opacity the beat computes, not on presence in the string.
    expect(settled).toContain(needle);
    const earlyOpacity = /opacity:0([^0-9]|$)/.test(early.replace(/\s/g, ""));
    expect(earlyOpacity || !early.includes(needle)).toBe(true);
  });
});

describe("§A-07 / H06 — the object is the argument", () => {
  it("carries no editorial statement", () => {
    expect(SHOT_COPY.H06).toBeUndefined();
  });

  it("still narrates its claim for a reader who cannot see it", () => {
    const text = narrate(SHOTS_BY_ID.H06);
    expect(text).not.toBe(SHOTS_BY_ID.H06.beat);
    expect(text.toLowerCase()).toContain("authority");
  });
});

describe("§18.3 — the accessibility mirror is complete", () => {
  it("narrates all 24 beats with real prose", () => {
    for (const shot of SHOTS) {
      const text = narrate(shot);
      expect(text.length, `${shot.id} narration too short`).toBeGreaterThan(24);
    }
  });

  it("does not describe pictures where an argument is available", () => {
    // A narration that merely repeated the beat label would be a description of
    // the shot list, not of the claim. Only beats with no copy at all may fall
    // back, and both of those have explicit prose.
    const fellBack = SHOTS.filter((s) => narrate(s) === s.beat);
    expect(fellBack.map((s) => s.id)).toEqual([]);
  });
});

describe("§21.3 — world state activates once, at its own beat", () => {
  /**
   * The claim under test is about the *quiet status strip*, which is the one
   * place the frame asserts which world state it is reading. H17's receipt
   * deliberately shows both ids — that transition is the content of the beat —
   * so an assertion over the whole frame would have flagged the correct
   * behaviour and pushed the fix into the wrong place.
   */
  function statusClaim(
    shotId: string,
  ): { id: string; state: string } | undefined {
    const text = textOf(render(shotId, 1));
    const match = /WORLD STATE (SAMPLE-\d+) · (CURRENT|RECOMPILING)/.exec(text);
    return match ? { id: match[1]!, state: match[2]! } : undefined;
  }

  it("does not claim a world state before the brand lock has been earned", () => {
    // §14.1 — the strip arrives with the category lock at 15.8s, not before.
    for (const id of ["H00", "H01", "H06"]) {
      expect(
        statusClaim(id),
        `${id} claims a world state too early`,
      ).toBeUndefined();
    }
  });

  it("beats between the brand lock and H17 read the initial world state", () => {
    for (const id of ["H08", "H12", "H16"]) {
      expect(statusClaim(id)?.id).toBe(WORLD_STATES.initial);
    }
  });

  it("beats from H17 read the recompiled world state", () => {
    for (const id of ["H17", "H19", "H23"]) {
      expect(statusClaim(id)?.id).toBe(WORLD_STATES.recompiled);
    }
  });

  /**
   * The gate that caught a real defect. H16 showed "November 3, 2026" under a
   * strip reading CURRENT for the world state those values do not belong to
   * yet — §21.3's "never expose partial world state as ACTIVE", violated in
   * the founder's own gate frame.
   */
  it("never labels a world state CURRENT while it is being recompiled", () => {
    for (const id of ["H15", "H16"]) {
      const claim = statusClaim(id);
      expect(claim?.id).toBe(WORLD_STATES.initial);
      expect(claim?.state, `${id} calls a recompiling state current`).toBe(
        "RECOMPILING",
      );
    }
  });

  it("the strip never names two world states at once", () => {
    for (const shot of SHOTS) {
      const text = textOf(render(shot.id, 1));
      const claims =
        text.match(/WORLD STATE SAMPLE-\d+ · (?:CURRENT|RECOMPILING)/g) ?? [];
      expect(claims.length, `${shot.id} half-activated`).toBeLessThan(2);
    }
  });
});

describe("§14.1 — the sample-mode notice is never absent", () => {
  it("every beat declares synthetic data", () => {
    for (const shot of SHOTS) {
      expect(
        textOf(render(shot.id, 1)),
        `${shot.id} renders without the sample-mode notice`,
      ).toContain("SYNTHETIC DATA");
    }
  });
});

describe("the four canonical scenes render their approved copy", () => {
  for (const scene of CANONICAL_SCENES) {
    it(`${scene.key} · ${scene.shot} · ${scene.copy}`, () => {
      // A scene the new board split across two beats is approved as the pair,
      // so its copy is checked against the pair.
      const companion =
        "companionShot" in scene && scene.companionShot
          ? textOf(render(scene.companionShot, 1))
          : "";
      const text = `${companion} ${textOf(render(scene.shot, 1))}`;
      if (scene.shot === "H06") {
        // Scene B's copy is the name of the object, not a line on screen.
        expect(text).toContain("Launch date");
        return;
      }
      // Compare on words, since the rendered copy carries its own punctuation.
      const words = scene.copy.split(" ").filter((w) => w.length > 3);
      for (const word of words) {
        expect(text.toUpperCase()).toContain(word.toUpperCase());
      }
    });
  }
});

/**
 * The gate for the defect class that turned up three separate times while
 * looking at the captured stills: a shard box narrower than its own value, a
 * boundary label pushed past the right edge, and an evidence locator that lost
 * "row 4" off the end of the frame. Each was invisible in code and obvious in
 * a screenshot.
 *
 * SVG cannot measure text, but the instrument voice is monospaced, so its
 * extent is arithmetic. That covers exactly the labels that keep overflowing.
 */
describe("§6.2 — instrument text stays inside the artboard", () => {
  const ADVANCE_12 = 7.22;
  const attr = (tag: string, name: string) =>
    new RegExp(`${name}="([^"]*)"`).exec(tag)?.[1];

  for (const shot of SHOTS) {
    it(`${shot.id} keeps its labels on screen`, () => {
      const html = render(shot.id, 1);
      // A fresh regex per test: a shared /g literal carries lastIndex
      // between tests and silently matches nothing on the second use.
      const text = /<text([^>]*)>([^<]*)<\/text>/g;
      for (const match of html.matchAll(text)) {
        const tag = match[1] ?? "";
        const content = match[2] ?? "";
        if (!content.trim()) continue;
        // Only the mono instrument voice has a known advance; editorial text
        // is proportional and is checked by eye at the review surface.
        if (!/font-family="[^"]*instrument/.test(tag)) continue;

        const size = Number(attr(tag, "font-size") ?? "12");
        const x = Number(attr(tag, "x") ?? "0");
        const anchor = attr(tag, "text-anchor") ?? "start";
        const tracking = /letter-spacing="([0-9.]+)em"/.exec(tag);
        const perChar =
          (size / 12) * ADVANCE_12 + (tracking ? Number(tracking[1]) * size : 0);
        const width = content.length * perChar;
        const left = anchor === "end" ? x - width : x;
        const right = anchor === "end" ? x : x + width;

        expect(left, `${shot.id}: "${content}" starts off-frame`).toBeGreaterThan(-1);
        expect(
          right,
          `${shot.id}: "${content}" overruns the right edge`,
        ).toBeLessThanOrEqual(ARTBOARD.width);
      }
    });
  }
});
