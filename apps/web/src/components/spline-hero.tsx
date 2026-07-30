"use client";

import { BracketsCurly, ShieldCheck, Table } from "@phosphor-icons/react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const Spline = dynamic(() => import("@splinetool/react-spline/next"), {
  ssr: false,
  loading: () => <CompilerFallback />,
});

const SCENE_URL = process.env.NEXT_PUBLIC_AKC_SPLINE_SCENE_URL?.trim();

export function SplineHero() {
  const [reduceMotion, setReduceMotion] = useState(true);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduceMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  if (!SCENE_URL || reduceMotion) {
    return <CompilerFallback />;
  }

  return (
    <div
      className="compiler-scene spline-scene"
      data-scene-source="spline"
      aria-label="Interactive 3D document-to-knowledge compilation"
    >
      <Spline scene={SCENE_URL} renderOnDemand />
      <div className="spline-scene-caption" aria-hidden="true">
        <span>Source document</span>
        <span>Grounded knowledge</span>
      </div>
    </div>
  );
}

function CompilerFallback() {
  return (
    <div
      className="compiler-scene"
      data-scene-source="native-fallback"
      aria-label="Document pages becoming source-grounded knowledge"
    >
      <div className="scene-grid" aria-hidden="true" />
      <div className="scene-label scene-label-source">Source pages</div>
      <div className="scene-label scene-label-result">Verified output</div>
      <div className="page-plane page-plane-back">
        <i />
        <i />
        <i />
      </div>
      <div className="page-plane page-plane-mid">
        <i />
        <i />
        <i />
        <i />
      </div>
      <div className="page-plane page-plane-front">
        <span>Annual report</span>
        <i className="scene-heading" />
        <i />
        <i className="scene-table" />
        <i />
      </div>
      <div className="typed-block block-heading">Heading</div>
      <div className="typed-block block-table">
        <Table size={13} aria-hidden="true" />
        Table
      </div>
      <div className="typed-block block-metric">Metric</div>
      <div className="markdown-plane">
        <div className="markdown-title">
          <BracketsCurly size={15} aria-hidden="true" />
          verified-output.md
        </div>
        <strong># Revenue overview</strong>
        <span>Source-linked financial result</span>
        <div className="markdown-table">
          <i />
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
        <small>
          <ShieldCheck size={12} weight="fill" aria-hidden="true" />
          Evidence coverage verified
        </small>
      </div>
      <svg
        className="provenance-thread provenance-one"
        viewBox="0 0 180 80"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path d="M2 68 C60 68 96 15 178 15" />
      </svg>
      <svg
        className="provenance-thread provenance-two"
        viewBox="0 0 200 110"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path d="M2 20 C72 20 110 94 198 94" />
      </svg>
      <div className="knowledge-node node-company">Company</div>
      <div className="knowledge-node node-metric">Metric</div>
      <div className="knowledge-node node-evidence">Evidence</div>
      <span className="scene-status">
        <span aria-hidden="true" />
        Deterministic sample replay
      </span>
    </div>
  );
}
