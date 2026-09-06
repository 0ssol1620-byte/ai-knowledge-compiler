/**
 * The clock, proven rather than assumed.
 *
 * This exists because the browser preview in this environment never composites
 * frames, so `requestAnimationFrame` never fires and the live page sits on H00
 * forever — which looks exactly like a broken timeline and is not one. Driving
 * a stubbed rAF here is the only way to show that the sequence actually
 * advances, publishes each checkpoint once, and cancels cleanly.
 */

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SHOTS, type Shot } from "../manifest/shots";
import { useSemanticTimeline, type TimelineState } from "./semantic-timeline";
import type { MotionMode } from "../state/experience-state";

let frame: ((t: number) => void) | null = null;
let now = 0;

function advance(seconds: number, step = 1 / 60) {
  for (let t = 0; t < seconds; t += step) {
    const cb = frame;
    if (!cb) return;
    frame = null;
    now += step * 1000;
    act(() => cb(now));
  }
}

beforeEach(() => {
  frame = null;
  now = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: (t: number) => void) => {
    frame = cb;
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {
    frame = null;
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mount(motionMode: MotionMode) {
  const seen: Shot[] = [];
  let state: (TimelineState & { replay: () => void }) | null = null;

  function Probe() {
    const timeline = useSemanticTimeline({
      motionMode,
      paused: false,
      autoplay: true,
      onCheckpoint: (shot) => {
        seen.push(shot);
      },
    });
    state = timeline;
    return null;
  }

  const host = document.createElement("div");
  const root = createRoot(host);
  act(() => root.render(<Probe />));
  return { seen, get state() { return state!; }, unmount: () => act(() => root.unmount()) };
}

describe("the semantic timeline advances", () => {
  it("moves through the board and publishes every checkpoint once", () => {
    const t = mount("full");
    // The full board is 66 seconds; a little past the end proves it settles
    // rather than running on.
    advance(70);

    const ids = t.seen.map((s) => s.id);
    expect(ids).toEqual(SHOTS.map((s) => s.id));
    expect(new Set(ids).size, "a checkpoint fired twice").toBe(ids.length);
    expect(t.state.finished).toBe(true);
    t.unmount();
  });

  it("publishes a checkpoint only after its shot has settled", () => {
    const t = mount("full");
    // H00 runs 0.0–1.2s. A third of the way in it is still transforming.
    advance(0.4);
    expect(t.seen).toHaveLength(0);
    advance(0.6);
    expect(t.seen.map((s) => s.id)).toEqual(["H00"]);
    t.unmount();
  });

  it("reduced motion still walks the whole narrative", () => {
    const t = mount("reduced");
    advance(SHOTS.length * 1.6 + 2);
    expect(t.seen.map((s) => s.id)).toEqual(SHOTS.map((s) => s.id));
    // §18.1 — every frame is the settled one; nothing is mid-transition.
    expect(t.state.shotProgress).toBe(1);
    t.unmount();
  });

  it("a seek re-publishes that beat so its scene state reapplies", () => {
    const t = mount("full");
    advance(4);
    const before = t.seen.length;
    act(() => t.state.replay());
    advance(3);
    expect(t.seen.length).toBeGreaterThan(before);
    t.unmount();
  });

  it("does not fire a burst of checkpoints after a backgrounded tab returns", () => {
    const t = mount("full");
    // One frame carrying a 30-second delta, as a restored tab would deliver.
    const cb = frame!;
    frame = null;
    now += 30_000;
    act(() => cb(now));
    // The 0.25s clamp means at most the first shot has settled.
    expect(t.seen.length).toBeLessThanOrEqual(1);
    t.unmount();
  });
});
