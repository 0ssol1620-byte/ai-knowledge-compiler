"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const WebglScene = dynamic(() => import("./structara-webgl-scene"), {
  ssr: false,
  loading: () => null,
});

export function StructaraHeroScene() {
  const [enhance, setEnhance] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const narrow = window.matchMedia("(max-width: 960px)").matches;
    const connection = (
      navigator as Navigator & { connection?: { saveData?: boolean } }
    ).connection;
    if (reduced || narrow || connection?.saveData) return;

    const id = window.requestIdleCallback(() => setEnhance(true), {
      timeout: 1600,
    });
    return () => {
      window.cancelIdleCallback(id);
    };
  }, []);

  return (
    <div className="st-hero-scene" data-enhanced={enhance}>
      <div className="st-hero-poster" aria-hidden="true">
        <div className="st-poster-pages">
          <i />
          <i />
          <div>
            <span>Annual report</span>
            <b />
            <em />
            <strong />
          </div>
        </div>
        <div className="st-poster-blocks">
          <i />
          <i />
          <i />
        </div>
        <div className="st-poster-graph">
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
      </div>
      {enhance && (
        <div className="st-webgl-layer" aria-hidden="true">
          <WebglScene />
        </div>
      )}
      <span className="st-scene-label st-scene-source">Source pages</span>
      <span className="st-scene-label st-scene-output">
        Connected knowledge
      </span>
      <small>Public sample · source structure preserved</small>
    </div>
  );
}
