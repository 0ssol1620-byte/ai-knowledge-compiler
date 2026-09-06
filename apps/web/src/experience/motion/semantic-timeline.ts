"use client";

/**
 * The one labelled semantic timeline — §28.1, §19.5.
 *
 * The brief asks for "GSAP or equivalent". This is the equivalent, and it is
 * hand-written on purpose. GSAP would add a dependency to a repository whose
 * §22 script budget is a ratchet that may not be raised to make a build pass,
 * and what is actually needed here is small: advance a clock, know which shot
 * that lands in, publish a checkpoint once per shot after it settles, and stop
 * dead when the visitor takes over. A timeline library would bring easing and
 * tweening this file does not use — the scenes ease themselves, in CSS.
 *
 * The rule the brief cares about is "no loose timeout choreography", and that
 * is structural rather than about which library runs the clock: there is one
 * clock, every beat is addressed by a shot id, and nothing schedules itself.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  SEQUENCE_DURATION_SECONDS,
  SHOTS,
  type Shot,
  type ShotId,
} from "../manifest/shots";
import type { MotionMode } from "../state/experience-state";

/**
 * §18.1 — reduced motion is a complete narrative, not "animation off". Each
 * shot still happens; it holds long enough to read and cross-fades instead of
 * travelling. A dwell of 1.6s is slower than the fastest shots on the board
 * (H04 and H05 run 1.6s) and much faster than the longest, which is the point:
 * without camera travel to carry it, an even cadence reads better than the
 * cinematic one.
 */
const REDUCED_DWELL_SECONDS = 1.6;

/**
 * A checkpoint is published after the shot has visually settled, not when it
 * starts — §19.5. Two thirds through is past the "primary transformation" band
 * of every shot's motion spec and inside its readable hold.
 */
const SETTLE_FRACTION = 0.66;

export type TimelineState = {
  readonly shot: Shot;
  readonly shotIndex: number;
  /** 0..1 within the current shot. Always 1 in reduced motion. */
  readonly shotProgress: number;
  readonly elapsedSeconds: number;
  readonly finished: boolean;
};

export type TimelineControls = {
  readonly seekToShot: (id: ShotId) => void;
  /** §18.2 — replay the current step. */
  readonly replay: () => void;
  /** §18.2 — back to the prior semantic checkpoint. */
  readonly back: () => void;
  /** Jump to the end and hand over. */
  readonly skipToEnd: () => void;
};

function shotAt(elapsed: number): { shot: Shot; index: number } {
  for (let i = SHOTS.length - 1; i >= 0; i -= 1) {
    const s = SHOTS[i]!;
    if (elapsed >= s.startSeconds) return { shot: s, index: i };
  }
  return { shot: SHOTS[0]!, index: 0 };
}

export function useSemanticTimeline({
  motionMode,
  paused,
  onCheckpoint,
  autoplay = true,
}: {
  motionMode: MotionMode;
  paused: boolean;
  /** Called once per shot, after it settles. */
  onCheckpoint: (shot: Shot) => void;
  autoplay?: boolean;
}): TimelineState & TimelineControls {
  const [elapsed, setElapsed] = useState(0);
  const rafRef = useRef<number | null>(null);
  const lastTickRef = useRef<number | null>(null);
  const publishedRef = useRef<Set<ShotId>>(new Set());

  // Held in a ref so the animation loop never re-subscribes when the parent
  // re-renders with a new closure. A loop that restarts on every render drops
  // frames and, worse, re-fires checkpoints.
  const checkpointRef = useRef(onCheckpoint);
  useEffect(() => {
    checkpointRef.current = onCheckpoint;
  }, [onCheckpoint]);

  const running = autoplay && !paused && motionMode !== "none";

  useEffect(() => {
    if (!running) {
      lastTickRef.current = null;
      return;
    }

    let cancelled = false;

    const tick = (now: number) => {
      if (cancelled) return;
      const last = lastTickRef.current;
      lastTickRef.current = now;
      // A tab that was backgrounded returns a huge delta. Clamping keeps a
      // return-to-tab from skipping five shots and firing their checkpoints in
      // one frame.
      const deltaSeconds = last === null ? 0 : Math.min((now - last) / 1000, 0.25);

      setElapsed((prev) => {
        const cap =
          motionMode === "reduced"
            ? SHOTS.length * REDUCED_DWELL_SECONDS
            : SEQUENCE_DURATION_SECONDS;
        return Math.min(prev + deltaSeconds, cap);
      });

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      lastTickRef.current = null;
    };
  }, [running, motionMode]);

  const reduced = motionMode === "reduced";

  const state = useMemo<TimelineState>(() => {
    if (reduced) {
      const index = Math.min(
        SHOTS.length - 1,
        Math.floor(elapsed / REDUCED_DWELL_SECONDS),
      );
      const shot = SHOTS[index]!;
      return {
        shot,
        shotIndex: index,
        // Reduced motion has no in-shot progress; every frame is the settled
        // one, which is exactly what §18.1's static checkpoints are.
        shotProgress: 1,
        elapsedSeconds: elapsed,
        finished: index >= SHOTS.length - 1,
      };
    }

    const { shot, index } = shotAt(elapsed);
    const span = shot.endSeconds - shot.startSeconds;
    const progress =
      span <= 0 ? 1 : Math.min(1, Math.max(0, (elapsed - shot.startSeconds) / span));
    return {
      shot,
      shotIndex: index,
      shotProgress: progress,
      elapsedSeconds: elapsed,
      finished: elapsed >= SEQUENCE_DURATION_SECONDS,
    };
  }, [elapsed, reduced]);

  // Publish each shot's checkpoint exactly once, after it settles.
  useEffect(() => {
    if (state.shotProgress < SETTLE_FRACTION) return;
    if (publishedRef.current.has(state.shot.id)) return;
    publishedRef.current.add(state.shot.id);
    checkpointRef.current(state.shot);
  }, [state.shot, state.shotProgress]);

  const seekToShot = useCallback(
    (id: ShotId) => {
      const index = SHOTS.findIndex((s) => s.id === id);
      if (index < 0) return;
      // Re-publishing is correct on a seek: the visitor asked to see that beat
      // again, and the scene state it drives has to be reapplied.
      publishedRef.current.delete(id);
      setElapsed(
        reduced ? index * REDUCED_DWELL_SECONDS : SHOTS[index]!.startSeconds,
      );
    },
    [reduced],
  );

  const replay = useCallback(() => {
    seekToShot(state.shot.id);
  }, [seekToShot, state.shot.id]);

  const back = useCallback(() => {
    const prev = SHOTS[Math.max(0, state.shotIndex - 1)]!;
    seekToShot(prev.id);
  }, [seekToShot, state.shotIndex]);

  const skipToEnd = useCallback(() => {
    const last = SHOTS.at(-1)!;
    seekToShot(last.id);
  }, [seekToShot]);

  return { ...state, seekToShot, replay, back, skipToEnd };
}

/**
 * §5.2 control mode for a shot. Derived from the shot board rather than from
 * §5.2's own boundaries, which disagree with it — see
 * `CONTROL_MODE_BOUNDARIES` in the shot manifest.
 */
export function controlModeForShot(shot: Shot): "director" | "guided" | "scale" | "explore" {
  if (shot.act === "ACTIVATE") return "explore";
  if (shot.act === "SCALE") return "scale";
  if (shot.startSeconds < 15.8) return "director";
  return "guided";
}
