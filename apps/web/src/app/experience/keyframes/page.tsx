"use client";

import { useState } from "react";

import { KeyframeStage } from "@/experience/dom/keyframe-stage";
import { HomeStage } from "@/experience/scenes/home-stage";
import {
  CANONICAL_SCENES,
  SHOTS_BY_ID,
  type ShotId,
} from "@/experience/manifest/shots";

/**
 * Phase 1 review surface — the Visual Language Sprint, delivered in the browser
 * rather than in Figma.
 *
 * §20.1 forbids building the full code until four frames are founder-approved.
 * This page is where that approval happens. Each frame is the settled end frame
 * of its shot at the canonical 1440x900 artboard, shown beside the reject
 * conditions it has to survive — so the review is against the spec's own words,
 * not against a reviewer's memory of them.
 */

type Entry = {
  shot: ShotId;
  intent: string;
  composition: string;
  rejects: readonly string[];
  exit: string;
};

const ENTRIES: readonly Entry[] = [
  {
    shot: "H01",
    intent:
      "The visitor recognises their own PC and company material immediately.",
    composition: "E1 x90 y390 w500 · hero source group x690–1320 y120–780",
    rejects: [
      "identical white rectangles",
      "folder icon grid",
      "neon orb",
      "fast swarm",
      "unreadable fake text",
    ],
    exit: "At least five source families are distinguishable without a legend.",
  },
  {
    shot: "H06",
    intent:
      "Value, source, time, authority and revision compile into one layered Knowledge Object.",
    composition: "Fact Stack x875–1115 y315–565 · left copy minimal",
    rejects: [
      "solid glowing orb",
      "random geometry morph",
      "all layers same colour",
      "fake code rain",
    ],
    exit:
      "The visitor reads compilation as structured assembly, not magic ingestion.",
  },
  {
    shot: "H08",
    intent:
      "The first large WOW and the new category definition complete together.",
    composition: "E1 x90 y340 w560 · world centroid x885 y455",
    rejects: [
      "logo made from nodes",
      "giant centred logo",
      "dashboard appearing",
      "overactive idle world",
    ],
    exit:
      "A first visitor can explain that information became connected knowledge.",
  },
  {
    shot: "H16",
    intent: "Fix the core differentiator as visual cause and effect.",
    composition:
      "affected subgraph x700–1160 y250–650 · compile telemetry E7 x90 y620",
    rejects: [
      "global loading spinner",
      "world reset",
      "all nodes flashing",
      "fake progress without a deterministic event",
    ],
    exit:
      "A transform audit confirms the unaffected set did not move.",
  },
];

export default function KeyframesPage() {
  const [showZones, setShowZones] = useState(false);
  const [showGuides, setShowGuides] = useState(false);

  return (
    <main
      data-tvx
      style={{
        minHeight: "100vh",
        backgroundColor: "var(--tvx-void-950)",
        padding: "48px clamp(16px, 4vw, 64px) 96px",
      }}
    >
      <header style={{ maxWidth: 900, marginBottom: 48 }}>
        <p className="tvx-technical" style={{ margin: 0 }}>
          Phase 1 · Visual Language Sprint · founder approval gate
        </p>
        <h1
          className="tvx-statement"
          style={{ margin: "18px 0 0", maxWidth: 760 }}
        >
          Four frames decide whether the code gets built.
        </h1>
        <p className="tvx-sub" style={{ margin: "20px 0 0" }}>
          §20.1 holds full implementation until these are approved. Each frame is
          the settled end frame of its shot at the canonical 1440×900 artboard.
          Nothing below relies on motion to hold a composition together.
        </p>

        <div style={{ display: "flex", gap: 24, marginTop: 28 }}>
          <Toggle
            checked={showZones}
            onChange={setShowZones}
            label="Zone overlay (§6.3)"
          />
          <Toggle
            checked={showGuides}
            onChange={setShowGuides}
            label="Composition contracts (§6.4)"
          />
        </div>
      </header>

      <div style={{ display: "grid", gap: 88 }}>
        {ENTRIES.map((entry) => {
          const shot = SHOTS_BY_ID[entry.shot];
          const scene = CANONICAL_SCENES.find((s) => s.shot === entry.shot);
          const companion =
            scene && "companionShot" in scene && scene.companionShot
              ? SHOTS_BY_ID[scene.companionShot]
              : undefined;
          const frames = companion ? [companion, shot] : [shot];
          return (
            <section key={entry.shot}>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: "12px 32px",
                  alignItems: "baseline",
                  marginBottom: 16,
                  paddingBottom: 14,
                  borderBottom: "1px solid var(--tvx-rule)",
                }}
              >
                <h2
                  className="tvx-brand"
                  style={{ margin: 0, fontSize: 26, letterSpacing: "0.04em" }}
                >
                  {shot.id}
                </h2>
                <span className="tvx-technical" style={{ maxWidth: "none" }}>
                  {`${shot.startSeconds.toFixed(2)}–${shot.endSeconds.toFixed(2)}s · F${String(shot.startFrame).padStart(4, "0")}–F${String(shot.endFrame).padStart(4, "0")} · ${shot.camera.join(" → ")}`}
                </span>
              </div>

              {/* The settled end frame of the shot, rendered by the same
                * component the live experience runs. What is approved here is
                * literally what ships.
                *
                * Where the 2026-08-21 board split one approved scene in two,
                * both halves are shown: approving only the half that happens to
                * sit on the boundary would approve half a claim. */}
              {frames.map((frameShot) => (
                <div key={frameShot.id} style={{ marginBottom: 12 }}>
                  {frames.length > 1 && (
                    <p className="tvx-technical" style={{ margin: "0 0 8px" }}>
                      {`${frameShot.id} · ${frameShot.beat}`}
                    </p>
                  )}
                  <KeyframeStage showZones={showZones} showGuides={showGuides}>
                    <HomeStage shot={frameShot} progress={1} />
                  </KeyframeStage>
                </div>
              ))}

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                  gap: 32,
                  marginTop: 24,
                }}
              >
                <Field label="Intent">{entry.intent}</Field>
                <Field label="Exact composition">{entry.composition}</Field>
                <Field label="Exit condition">{entry.exit}</Field>
                <Field label="Reject if">
                  {entry.rejects.join(" · ")}
                </Field>
              </div>
            </section>
          );
        })}
      </div>
    </main>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="tvx-technical" style={{ margin: 0 }}>
        {label}
      </p>
      <p
        style={{
          margin: "8px 0 0",
          fontSize: 14,
          lineHeight: 1.5,
          color: "var(--tvx-fog-500)",
        }}
      >
        {children}
      </p>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 10,
        cursor: "pointer",
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{ accentColor: "var(--tvx-signal-cobalt)", width: 15, height: 15 }}
      />
      <span className="tvx-technical" style={{ maxWidth: "none" }}>
        {label}
      </span>
    </label>
  );
}
