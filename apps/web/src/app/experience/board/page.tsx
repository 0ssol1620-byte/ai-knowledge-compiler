"use client";

import { useState } from "react";

import { KeyframeStage } from "@/experience/dom/keyframe-stage";
import { HomeStage } from "@/experience/scenes/home-stage";
import { narrate } from "@/experience/scenes/narration";
import { FOUNDER_APPROVAL_KEYFRAMES, SHOTS } from "@/experience/manifest/shots";

/**
 * The whole §5.3 board as settled stills.
 *
 * The four-frame gate answers "is the visual language right". This answers a
 * different and equally load-bearing question: does the *sequence* hold when
 * nothing is moving. Twenty-four frames in a column is the cheapest way to see
 * a beat that draws nothing, a copy line that repeats its neighbour, or an act
 * that has no visual argument of its own — all of which motion hides.
 *
 * It is a review surface, not a visitor surface.
 */
export default function BoardPage() {
  const [progress, setProgress] = useState(1);

  return (
    <main
      data-tvx
      style={{
        minHeight: "100vh",
        backgroundColor: "var(--tvx-void-950)",
        padding: "40px clamp(16px, 4vw, 56px) 96px",
      }}
    >
      <header style={{ maxWidth: 820, marginBottom: 40 }}>
        <p className="tvx-technical" style={{ margin: 0 }}>
          §5.3 shot board · 24 beats · settled stills
        </p>
        <h1 className="tvx-statement" style={{ margin: "16px 0 0" }}>
          Does the sequence hold when nothing moves?
        </h1>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            marginTop: 28,
          }}
        >
          <span className="tvx-technical" style={{ maxWidth: "none" }}>
            {`IN-SHOT PROGRESS ${progress.toFixed(2)}`}
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={progress}
            onChange={(e) => setProgress(Number(e.target.value))}
            style={{ accentColor: "var(--tvx-signal-cobalt)", width: 260 }}
          />
        </label>
      </header>

      <div style={{ display: "grid", gap: 56 }}>
        {SHOTS.map((shot) => {
          const isGate = FOUNDER_APPROVAL_KEYFRAMES.includes(shot.id);
          return (
            <section key={shot.id} data-shot={shot.id}>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: "8px 22px",
                  alignItems: "baseline",
                  marginBottom: 12,
                  paddingBottom: 10,
                  borderBottom: `1px solid ${
                    isGate ? "var(--tvx-signal-cool)" : "var(--tvx-rule)"
                  }`,
                }}
              >
                <span
                  className="tvx-brand"
                  style={{ fontSize: 20, letterSpacing: "0.06em" }}
                >
                  {shot.id}
                </span>
                <span className="tvx-technical" style={{ maxWidth: "none" }}>
                  {`${shot.act} · ${shot.beat} · ${shot.startSeconds.toFixed(
                    2,
                  )}–${shot.endSeconds.toFixed(2)}s${isGate ? " · GATE FRAME" : ""}`}
                </span>
              </div>

              <KeyframeStage>
                <HomeStage shot={shot} progress={progress} />
              </KeyframeStage>

              <p
                style={{
                  margin: "12px 0 0",
                  maxWidth: 820,
                  fontSize: 14,
                  lineHeight: 1.55,
                  color: "var(--tvx-fog-500)",
                }}
              >
                {narrate(shot)}
              </p>
            </section>
          );
        })}
      </div>
    </main>
  );
}
