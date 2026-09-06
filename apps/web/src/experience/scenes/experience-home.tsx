"use client";

/**
 * The Home closed loop — §33 Phase 3.
 *
 * "Closed loop" is the operative word: the film is not a video that plays over
 * a page. Every beat writes into one semantic state, the controls write into
 * the same state, and the accessibility mirror reads it. So a visitor who
 * presses Explore at H09 and a visitor who watched all 66 seconds arrive at the
 * same world with the same world-state id, and a screen reader gets the
 * argument rather than a note that a decorative animation was skipped.
 */

import Link from "next/link";

import { useCallback, useEffect, useMemo, useReducer, useState } from "react";

import { ZONES } from "../manifest/layout";
import { CONTROLS, CTA, NAV, QUIET_STATUS } from "../manifest/copy";
import {
  SEQUENCE_DURATION_SECONDS,
  SHOTS,
  type Shot,
} from "../manifest/shots";
import { WORLD_STATES } from "../fixtures/project-atlas";
import {
  controlModeForShot,
  useSemanticTimeline,
} from "../motion/semantic-timeline";
import {
  experienceReducer,
  type ExperienceState,
  type MotionMode,
} from "../state/experience-state";
import { KeyframeStage } from "../dom/keyframe-stage";
import { HomeStage } from "./home-stage";
import { narrate } from "./narration";

const INITIAL_STATE: ExperienceState = {
  act: "VOID",
  shot: "H00",
  controlMode: "director",
  worldStateId: WORLD_STATES.initial,
  impactSet: [],
  unaffectedControlSet: [],
  motionMode: "full",
  qualityTier: "fallback",
  projection: "world",
  sampleMode: true,
  paused: false,
  intentEpoch: 0,
};

export function ExperienceHome() {
  const [state, dispatch] = useReducer(experienceReducer, INITIAL_STATE);
  const [started, setStarted] = useState(false);

  // §18.1 — the OS preference is honoured on arrival, and a later change to it
  // is honoured too. A visitor who turns reduced motion on mid-film means it.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = (matches: boolean) => {
      dispatch({ type: "setMotionMode", motionMode: matches ? "reduced" : "full" });
    };
    apply(mq.matches);
    const onChange = (e: MediaQueryListEvent) => apply(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const onCheckpoint = useCallback((shot: Shot) => {
    dispatch({ type: "checkpoint", shot: shot.id, act: shot.act });
    // §21.3 — the world state flips at its own beat, atomically, and only
    // there. Nothing else in the film may write this id.
    if (shot.id === "H17") {
      dispatch({
        type: "activateWorldState",
        worldStateId: WORLD_STATES.recompiled,
      });
    }
  }, []);

  const timeline = useSemanticTimeline({
    motionMode: state.motionMode,
    paused: state.paused,
    onCheckpoint,
    autoplay: started,
  });

  const shot = timeline.shot;
  const controlMode = controlModeForShot(shot);
  const atEnd = timeline.finished;

  // Keyboard is a first-class path through the film, not a fallback: §18.2's
  // controls are all reachable, and Escape hands the world over immediately.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      switch (e.key) {
        case " ":
          e.preventDefault();
          dispatch({ type: state.paused ? "resume" : "pause" });
          break;
        case "ArrowRight":
          e.preventDefault();
          timeline.seekToShot(
            (SHOTS[Math.min(SHOTS.length - 1, timeline.shotIndex + 1)] ?? shot).id,
          );
          break;
        case "ArrowLeft":
          e.preventDefault();
          timeline.back();
          break;
        case "Escape":
          dispatch({ type: "exploreNow" });
          timeline.skipToEnd();
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.paused, timeline, shot]);

  const runControl = useCallback(
    (id: (typeof CONTROLS)[number]["id"]) => {
      switch (id) {
        case "skip":
          dispatch({ type: "skipMotion" });
          break;
        case "pause":
          dispatch({ type: state.paused ? "resume" : "pause" });
          break;
        case "replay":
          timeline.replay();
          break;
        case "back":
          timeline.back();
          break;
        case "explore":
          dispatch({ type: "exploreNow" });
          timeline.skipToEnd();
          break;
      }
    },
    [state.paused, timeline],
  );

  return (
    <main
      data-tvx
      style={{
        minHeight: "100vh",
        backgroundColor: "var(--tvx-void-950)",
        color: "var(--tvx-bone-100)",
      }}
    >
      <Nav />

      <div style={{ position: "relative" }}>
        <KeyframeStage>
          <HomeStage
            shot={shot}
            progress={timeline.shotProgress}
            worldStateId={state.worldStateId}
          />
          <TemporalSpine
            elapsed={timeline.elapsedSeconds}
            shotIndex={timeline.shotIndex}
            motionMode={state.motionMode}
            onSeek={timeline.seekToShot}
          />
        </KeyframeStage>

        {!started && <StartCurtain onStart={() => setStarted(true)} />}
      </div>

      <ControlBar
        controlMode={controlMode}
        paused={state.paused}
        motionMode={state.motionMode}
        shot={shot}
        atEnd={atEnd}
        onControl={runControl}
      />

      <AccessibilityMirror shot={shot} worldStateId={state.worldStateId} />

      {atEnd && <ClosingCta />}
    </main>
  );
}

/* ── Chrome ────────────────────────────────────────────────────────────── */

function Nav() {
  return (
    <nav
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "20px clamp(16px, 3vw, 40px)",
        borderBottom: "1px solid var(--tvx-rule)",
      }}
    >
      <span className="tvx-brand" style={{ fontSize: 17, letterSpacing: "0.14em" }}>
        {NAV.brand}
      </span>
      <div style={{ display: "flex", gap: 26, alignItems: "center" }}>
        {NAV.links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className="tvx-technical"
            style={{ maxWidth: "none", textDecoration: "none" }}
          >
            {l.label}
          </Link>
        ))}
        <Link
          href={NAV.signIn.href}
          className="tvx-technical"
          style={{
            maxWidth: "none",
            textDecoration: "none",
            color: "var(--tvx-bone-100)",
          }}
        >
          {NAV.signIn.label}
        </Link>
      </div>
    </nav>
  );
}

/**
 * Autoplaying 66 seconds of film at a visitor who has not asked for it is the
 * behaviour §18.2's controls exist to make unnecessary. The curtain is the
 * first frame, held, with one affordance — and the whole sequence is reachable
 * as text underneath without ever pressing it.
 */
function StartCurtain({ onStart }: { onStart: () => void }) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "rgba(9, 11, 12, 0.72)",
      }}
    >
      <button
        type="button"
        onClick={onStart}
        className="tvx-technical"
        style={{
          maxWidth: "none",
          background: "transparent",
          border: "1px solid var(--tvx-signal-cool)",
          color: "var(--tvx-bone-100)",
          padding: "14px 26px",
          cursor: "pointer",
          minHeight: 44,
        }}
      >
        BEGIN — 66 SECONDS
      </button>
    </div>
  );
}

/**
 * E5 temporal spine. It is a seek control, not a progress bar: §5.2's guided
 * mode means the visitor can move between semantic checkpoints at will, and a
 * spine that only reports position would make the film feel like a video again.
 */
function TemporalSpine({
  elapsed,
  shotIndex,
  motionMode,
  onSeek,
}: {
  elapsed: number;
  shotIndex: number;
  motionMode: MotionMode;
  onSeek: (id: Shot["id"]) => void;
}) {
  const z = ZONES.E5_TEMPORAL_SPINE;
  const fraction =
    motionMode === "reduced"
      ? (shotIndex + 1) / SHOTS.length
      : Math.min(1, elapsed / SEQUENCE_DURATION_SECONDS);

  return (
    <div
      style={{
        position: "absolute",
        left: z.x,
        top: z.y + 30,
        width: z.w,
        height: 34,
      }}
    >
      <div
        style={{
          position: "relative",
          height: 1,
          backgroundColor: "var(--tvx-rule)",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            height: 1,
            width: `${fraction * 100}%`,
            backgroundColor: "var(--tvx-signal-cool)",
          }}
        />
        {SHOTS.map((s, i) => (
          <button
            key={s.id}
            type="button"
            onClick={() => onSeek(s.id)}
            aria-label={`${s.id} — ${s.beat}`}
            title={`${s.id} — ${s.beat}`}
            style={{
              position: "absolute",
              left: `${(s.startSeconds / SEQUENCE_DURATION_SECONDS) * 100}%`,
              top: -14,
              width: 14,
              height: 28,
              padding: 0,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              transform: "translateX(-7px)",
            }}
          >
            <span
              style={{
                display: "block",
                margin: "0 auto",
                width: 1,
                height: i <= shotIndex ? 12 : 7,
                backgroundColor:
                  i === shotIndex
                    ? "var(--tvx-signal-cool)"
                    : "var(--tvx-steel-650)",
              }}
            />
          </button>
        ))}
      </div>
    </div>
  );
}

function ControlBar({
  controlMode,
  paused,
  motionMode,
  shot,
  atEnd,
  onControl,
}: {
  controlMode: string;
  paused: boolean;
  motionMode: MotionMode;
  shot: Shot;
  atEnd: boolean;
  onControl: (id: (typeof CONTROLS)[number]["id"]) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: "12px 20px",
        padding: "16px clamp(16px, 3vw, 40px)",
        borderBottom: "1px solid var(--tvx-rule)",
      }}
    >
      {CONTROLS.map((c) => {
        const label =
          c.id === "pause" ? (paused ? "Resume cinematic" : c.label) : c.label;
        const done =
          (c.id === "skip" && motionMode !== "full") ||
          (c.id === "explore" && atEnd);
        return (
          <button
            key={c.id}
            type="button"
            onClick={() => onControl(c.id)}
            className="tvx-technical"
            style={{
              maxWidth: "none",
              minHeight: 44,
              padding: "0 14px",
              background: "transparent",
              border: "1px solid var(--tvx-rule)",
              color: done ? "var(--tvx-steel-650)" : "var(--tvx-bone-100)",
              cursor: "pointer",
            }}
          >
            {label}
          </button>
        );
      })}

      <span className="tvx-technical" style={{ maxWidth: "none", marginLeft: "auto" }}>
        {`${shot.id} · ${controlMode.toUpperCase()} · ${QUIET_STATUS.motion(
          motionMode === "full" ? "FULL" : "REDUCED",
        )}`}
      </span>
    </div>
  );
}

/**
 * §18.3 — the whole sequence as text, always present rather than behind a
 * toggle. The live region announces the current beat; the list beneath it is the
 * complete argument, readable without ever starting the film.
 */
function AccessibilityMirror({
  shot,
  worldStateId,
}: {
  shot: Shot;
  worldStateId: string;
}) {
  const current = useMemo(() => narrate(shot), [shot]);

  return (
    <section
      style={{
        padding: "40px clamp(16px, 3vw, 40px) 72px",
        maxWidth: 820,
      }}
    >
      <p aria-live="polite" className="tvx-sub" style={{ margin: 0 }}>
        {current}
      </p>
      <p className="tvx-technical" style={{ margin: "10px 0 0" }}>
        {QUIET_STATUS.worldState(worldStateId)}
      </p>

      <h2 className="tvx-technical" style={{ margin: "44px 0 0" }}>
        THE SEQUENCE, IN FULL
      </h2>
      <ol
        style={{
          margin: "18px 0 0",
          padding: 0,
          listStyle: "none",
          display: "grid",
          gap: 14,
        }}
      >
        {SHOTS.map((s) => (
          <li
            key={s.id}
            style={{
              color:
                s.id === shot.id
                  ? "var(--tvx-bone-100)"
                  : "var(--tvx-fog-500)",
              fontSize: 15,
              lineHeight: 1.55,
            }}
          >
            <span className="tvx-technical" style={{ display: "inline", marginRight: 10 }}>
              {s.id}
            </span>
            {narrate(s)}
          </li>
        ))}
      </ol>
    </section>
  );
}

function ClosingCta() {
  return (
    <section
      style={{
        padding: "0 clamp(16px, 3vw, 40px) 96px",
        display: "flex",
        flexWrap: "wrap",
        gap: 18,
      }}
    >
      <Link
        href="/app/home"
        className="tvx-technical"
        style={{
          maxWidth: "none",
          minHeight: 44,
          display: "inline-flex",
          alignItems: "center",
          padding: "0 20px",
          border: "1px solid var(--tvx-signal-cool)",
          color: "var(--tvx-bone-100)",
          textDecoration: "none",
        }}
      >
        {CTA.primary}
      </Link>
      <Link
        href="/security"
        className="tvx-technical"
        style={{
          maxWidth: "none",
          minHeight: 44,
          display: "inline-flex",
          alignItems: "center",
          padding: "0 20px",
          border: "1px solid var(--tvx-rule)",
          color: "var(--tvx-bone-100)",
          textDecoration: "none",
        }}
      >
        {CTA.secondary}
      </Link>
    </section>
  );
}
