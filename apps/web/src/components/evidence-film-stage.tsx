"use client";

import { ArrowLeft, ArrowRight, Pause, Play } from "@phosphor-icons/react";
import Image from "next/image";
import Link from "next/link";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";

import { publicBenchmarkSnapshot } from "@/lib/benchmark-public";

const measuredCandidates = publicBenchmarkSnapshot.datasets.filter(
  (dataset) => dataset.status === "available",
);
const formalCaseCount = measuredCandidates.reduce(
  (total, dataset) => total + (dataset.evidence?.case_count ?? 0),
  0,
);

const scenes = [
  {
    eyebrow: "01 · Intake",
    title: "One collection. Every source preserved.",
    body: "Folder identity, SHA-256, duplicate groups, document class, and privacy policy are fixed before a model is selected.",
    image: "/product/workspace-home.webp",
    signal: "Hash → dedupe → classify",
  },
  {
    eyebrow: "02 · Preflight",
    title: "The route is estimated before the spend.",
    body: "Static features and adaptive samples produce bounded credit, duration, and quality-risk forecasts.",
    image: "/product/workspace-home.webp",
    signal: "P50 42.8 · P95 51.6 credits",
  },
  {
    eyebrow: "03 · Structure",
    title: "Parallel pages keep one continuity map.",
    body: "Typed blocks, page anchors, table identities, and immutable attempts move through independent worker pools.",
    image: "/product/processing.webp",
    signal: "Page → block → source region",
  },
  {
    eyebrow: "04 · Verify",
    title: "A failure becomes a bounded repair.",
    body: "Numeric, schema, source, row-omission, and continuity gates isolate the smallest affected scope and reverify it.",
    image: "/product/review.webp",
    signal: "Detect → repair → reverify",
  },
  {
    eyebrow: "05 · Measured model portfolio",
    title: "Different strengths become one routing advantage.",
    body: "Same 18-page OmniDocBench demo, three blind repeats, one RTX 4090. CDM and overall remain unavailable—not zero.",
    signal: `${formalCaseCount} / ${formalCaseCount} formal inference cases completed`,
    metrics: true,
  },
  {
    eyebrow: "06 · Knowledge",
    title: "Documents become inspectable notes.",
    body: "Sections, entities, relations, and claims retain evidence receipts back to the originating page and block.",
    image: "/product/knowledge.webp",
    signal: "Notes · entities · relations",
  },
  {
    eyebrow: "07 · Connect",
    title: "Every edge carries its proof.",
    body: "The graph is not decoration. Selecting a relation returns to the exact source evidence that supports it.",
    image: "/product/graph.webp",
    signal: "Relation → evidence → source",
  },
  {
    eyebrow: "08 · Package",
    title: "Compile once. Leave with the knowledge.",
    body: "Portable Markdown, Obsidian, RAG JSONL, JSON-LD, and manifests derive from one verified CIR.",
    image: "/product/exports.webp",
    signal: "Portable · source-linked · policy-controlled",
  },
  {
    eyebrow: "09 · FOLYNTA",
    title: "Do not organize the files. Compile the knowledge.",
    body: "An evidence-first knowledge compiler for people, enterprise systems, and AI.",
    image: "/product/processing.webp",
    signal: "From every page, a system of knowledge.",
  },
] as const;

function MetricScene() {
  const percent = (value: number | null) =>
    value === null ? "—" : `${(value * 100).toFixed(2)}%`;
  const rows = [
    ["Text 1−edit", (value: (typeof measuredCandidates)[number]) => percent(value.metrics.text_edit_companion)],
    ["Formula 1−edit", (value: (typeof measuredCandidates)[number]) => percent(value.metrics.formula_edit_companion)],
    ["Table TEDS", (value: (typeof measuredCandidates)[number]) => percent(value.metrics.table_teds)],
    ["Table 1−edit", (value: (typeof measuredCandidates)[number]) => percent(value.metrics.table_edit_companion)],
    ["Mean sec/page", (value: (typeof measuredCandidates)[number]) => value.metrics.mean_latency_ms === null ? "—" : (value.metrics.mean_latency_ms / 1_000).toFixed(3)],
    ["Est. USD/page", (value: (typeof measuredCandidates)[number]) => value.metrics.cost_per_page_usd === null ? "—" : `$${value.metrics.cost_per_page_usd.toFixed(6)}`],
    ["Exact repeats", (value: (typeof measuredCandidates)[number]) => value.metrics.exact_repeat_ratio === null || value.page_count === null ? "—" : `${Math.round(value.metrics.exact_repeat_ratio * value.page_count)} / ${value.page_count}`],
  ] as const;
  const gridStyle = {
    gridTemplateColumns: `minmax(94px, 1.2fr) repeat(${measuredCandidates.length}, minmax(72px, 1fr))`,
  } satisfies CSSProperties;
  const shortLabel = (label: string) =>
    label
      .replace("MinerU 3.4.4 · Pipeline", "MinerU pipe")
      .replace("PaddleOCR-VL 1.6 · FastDeploy c8", "Paddle VL")
      .replace("MinerU 3.4.4 · VLM c1", "MinerU VLM")
      .replace("DeepSeek-OCR-2 · Transformers", "DeepSeek 2")
      .replace("OvisOCR2 0.9B · vLLM cu129", "Ovis 0.9B");
  return (
    <div
      className="film-metrics"
      role="region"
      aria-label="Measured model comparison"
      tabIndex={0}
      style={{ minWidth: `${150 + measuredCandidates.length * 94}px` }}
    >
      <div className="film-metrics-head" style={gridStyle}>
        <span>Official partial metrics</span>
        {measuredCandidates.map((candidate) => <strong key={candidate.id}>{shortLabel(candidate.label)}</strong>)}
      </div>
      {rows.map(([metric, renderValue]) => (
        <div key={metric} style={gridStyle}>
          <span>{metric}</span>
          {measuredCandidates.map((candidate) => <strong key={candidate.id}>{renderValue(candidate)}</strong>)}
        </div>
      ))}
      <small>Lower edit distance is better; displayed 1−edit values are derived companions. Runtime cost excludes orchestration and evaluation.</small>
    </div>
  );
}

export function EvidenceFilmStage() {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [staticMode, setStaticMode] = useState(false);
  const [holdFinal, setHoldFinal] = useState(false);
  const scene = scenes[index] ?? scenes[0];

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = Number(params.get("scene"));
    const isStatic = params.get("static") === "1";
    const shouldHoldFinal = params.get("hold") === "1";
    const initialization = window.setTimeout(() => {
      if (Number.isInteger(requested) && requested >= 0 && requested < scenes.length) {
        setIndex(requested);
      }
      setStaticMode(isStatic);
      setHoldFinal(shouldHoldFinal);
      if (isStatic) setPlaying(false);
    }, 0);
    return () => window.clearTimeout(initialization);
  }, []);

  useEffect(() => {
    if (!playing || staticMode) return;
    const timer = window.setInterval(
      () =>
        setIndex((value) =>
          holdFinal ? Math.min(value + 1, scenes.length - 1) : (value + 1) % scenes.length,
        ),
      6_000,
    );
    return () => window.clearInterval(timer);
  }, [holdFinal, playing, staticMode]);

  const progress = useMemo(() => ((index + 1) / scenes.length) * 100, [index]);
  return (
    <main className="film-stage" id="main-content">
      <header className="film-stage-nav">
        <Link href="/" aria-label="FOLYNTA home"><span className="film-mark">F</span><strong>FOLYNTA</strong></Link>
        <span>Evidence in Motion · measured 2026-08-01</span>
      </header>
      <section className="film-scene" key={index} aria-live="polite">
        <div className="film-copy">
          <p>{scene.eyebrow}</p>
          <h1>{scene.title}</h1>
          <span>{scene.body}</span>
          <small>{scene.signal}</small>
        </div>
        <div className={`film-visual${"metrics" in scene ? " film-visual-metrics" : ""}`}>
          {"metrics" in scene ? <MetricScene /> : (
            <Image src={scene.image} alt="" fill priority sizes="(max-width: 900px) 100vw, 65vw" />
          )}
          <div className="film-proof-chip"><span>Evidence</span><strong>source-linked</strong><small>verified CIR</small></div>
        </div>
      </section>
      <footer className="film-controls">
        <div className="film-progress" aria-hidden="true">
          <span style={{ transform: `scaleX(${progress / 100})` }} />
        </div>
        <span>{String(index + 1).padStart(2, "0")} / {String(scenes.length).padStart(2, "0")}</span>
        <div>
          <button type="button" onClick={() => setIndex((index - 1 + scenes.length) % scenes.length)} aria-label="Previous scene"><ArrowLeft aria-hidden="true" /></button>
          <button type="button" onClick={() => setPlaying((value) => !value)} aria-label={playing ? "Pause film" : "Play film"}>{playing ? <Pause weight="fill" aria-hidden="true" /> : <Play weight="fill" aria-hidden="true" />}</button>
          <button type="button" onClick={() => setIndex((index + 1) % scenes.length)} aria-label="Next scene"><ArrowRight aria-hidden="true" /></button>
        </div>
      </footer>
    </main>
  );
}
