import { describe, expect, it } from "vitest";

import {
  buildThreads,
  describeThread,
  MAX_ACTIVE_THREADS,
  type FacingGeometry,
  type ThreadAnchor,
} from "@/lib/facing/thread";

const geometry: FacingGeometry = {
  versoRight: 0.42,
  rectoLeft: 0.58,
  orientation: "horizontal",
};

function anchor(overrides: Partial<ThreadAnchor> = {}): ThreadAnchor {
  return {
    id: "a",
    bbox: [100, 200, 400, 260],
    targetY: 0.3,
    label: "Table 14, block 7",
    state: "verified",
    ...overrides,
  };
}

describe("buildThreads", () => {
  it("drops anchors with no bbox instead of inventing a position", () => {
    // §4.4 — this is the rule the whole module exists to enforce.
    const threads = buildThreads(
      [anchor({ id: "has-coords" }), anchor({ id: "no-coords", bbox: null })],
      geometry,
    );
    expect(threads.map((thread) => thread.id)).toEqual(["has-coords"]);
  });

  it("returns nothing when no anchor has coordinates", () => {
    const threads = buildThreads(
      [anchor({ bbox: null }), anchor({ id: "b", bbox: null })],
      geometry,
    );
    expect(threads).toEqual([]);
  });

  it("caps concurrent threads at three", () => {
    const anchors = Array.from({ length: 6 }, (_, index) =>
      anchor({ id: `a${index}` }),
    );
    expect(buildThreads(anchors, geometry)).toHaveLength(MAX_ACTIVE_THREADS);
  });

  it("starts at the right edge of the source box and ends at the recto edge", () => {
    const [thread] = buildThreads([anchor()], geometry);
    // bbox x2 = 400/1000 scaled into the verso panel
    expect(thread!.from.x).toBeCloseTo(0.42 * 0.4, 5);
    // bbox vertical centre = (200 + 260) / 2 / 1000
    expect(thread!.from.y).toBeCloseTo(0.23, 5);
    expect(thread!.to.x).toBeCloseTo(0.58, 5);
    expect(thread!.to.y).toBeCloseTo(0.3, 5);
  });

  it("emits a cubic in the 0-1000 viewBox space", () => {
    const [thread] = buildThreads([anchor()], geometry);
    expect(thread!.path).toMatch(/^M [\d.]+ [\d.]+ C /);
    const numbers = thread!.path.match(/[\d.]+/g)!.map(Number);
    expect(numbers.every((value) => value >= 0 && value <= 1000)).toBe(true);
  });

  it("runs the curve vertically when the layout is stacked", () => {
    const [horizontal] = buildThreads([anchor()], geometry);
    const [vertical] = buildThreads([anchor()], {
      ...geometry,
      orientation: "vertical",
    });
    expect(vertical!.path).not.toEqual(horizontal!.path);
    // A stacked thread travels top to bottom, so its endpoints differ in y.
    expect(vertical!.to.y).not.toBeCloseTo(vertical!.from.y, 3);
  });
});

describe("describeThread", () => {
  it("states the same fact the thread draws", () => {
    expect(describeThread(anchor(), 31)).toBe(
      "Table 14, block 7, page 31 — verified",
    );
  });

  it("says so when the position is unknown rather than implying one", () => {
    expect(describeThread(anchor({ bbox: null }), 31)).toBe(
      "Table 14, block 7, page 31, position unavailable — verified",
    );
  });
});
