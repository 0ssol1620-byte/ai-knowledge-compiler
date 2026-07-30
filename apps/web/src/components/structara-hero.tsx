"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

const WebglScene = dynamic(() => import("./structara-webgl-scene"), {
  ssr: false,
  loading: () => null,
});

export function StructaraHeroScene() {
  const [enhance, setEnhance] = useState(false);
  const [inView, setInView] = useState(true);
  const [documentVisible, setDocumentVisible] = useState(true);
  const sceneRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const observer = new IntersectionObserver(
      ([entry]) => setInView(Boolean(entry?.isIntersecting)),
      { rootMargin: "120px" },
    );
    const handleVisibility = () => setDocumentVisible(!document.hidden);
    observer.observe(scene);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  return (
    <div ref={sceneRef} className="st-hero-scene" data-enhanced={enhance}>
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
          <WebglScene active={inView && documentVisible} />
        </div>
      )}
      <span className="st-scene-label st-scene-source">Source pages</span>
      <span className="st-scene-label st-scene-output">
        Connected knowledge
      </span>
      <small>Illustrative model · synthetic sample</small>
    </div>
  );
}
