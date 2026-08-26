import { ArrowLeft, ArrowUpRight, Check, CirclePlay, FileText, FolderTree, Layers3, ScanText, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import "../demo.css";
import "../demo-atlas.css";

const SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm";

const STAGES = [
  { id: "source", label: "Source", state: "SEC EDGAR / HTML", detail: "Public filing enters a visible perimeter", icon: FileText },
  { id: "read", label: "Read", state: "LAYOUT + iXBRL", detail: "Sections, tables and source anchors resolve", icon: ScanText },
  { id: "resolve", label: "Resolve", state: "REPRESENTATIONS", detail: "Source forms remain related, not erased", icon: Layers3 },
  { id: "context", label: "Compile", state: "REVIEWABLE CONTEXT", detail: "A proposed directory and evidence map emerge", icon: FolderTree },
];

export default function SecCinematicDemo() {
  const [active, setActive] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    if (!isPlaying) return;
    if (active >= STAGES.length - 1) { const stop = window.setTimeout(() => setIsPlaying(false), 800); return () => window.clearTimeout(stop); }
    const timer = window.setTimeout(() => setActive((value) => Math.min(value + 1, STAGES.length - 1)), 960);
    return () => window.clearTimeout(timer);
  }, [active, isPlaying]);

  const current = STAGES[active];
  return <main className="demo-shell">
    <header className="demo-topbar"><a href="/" className="demo-brand"><ArrowLeft size={15} /><img src="/manus-storage/tavonel-mark_761fadd4.png" alt="" /> <span>TAVONEL<small>KNOWLEDGE COMPILER</small></span></a><span>PUBLIC PROOF / SEC FIXTURE</span><a href={SEC_URL} target="_blank" rel="noreferrer">OPEN ORIGINAL <ArrowUpRight size={14} /></a></header>
    <section className="demo-hero"><div><span className="demo-kicker">SEC FILING / PUBLIC COMPILER</span><h1>Every conclusion<br />keeps its <em>proof.</em></h1></div><div className="demo-hero-proof"><div className="hero-atlas-mark"><img src="/manus-storage/tavonel-mark_761fadd4.png" alt="" /><i /><i /><b>01</b></div><p>Apple Inc.의 공개 2024 Form 10-K를 기준으로, 한 원문이 읽기 가능한 구조·근거 관계·검토 가능한 컨텍스트로 어떻게 변하는지 보여줍니다.</p><small>ORIGINAL PRESERVED · CURRENTNESS REVIEWED</small></div></section>
    <section className={`demo-instrument phase-${active} ${isPlaying ? "is-playing" : ""}`}>
      <div className="demo-source-pane"><div className="pane-top"><span>ORIGINAL SURFACE</span><span>01 / PUBLIC</span></div><div className="demo-filing"><div className="filing-stamp">SEC EDGAR</div><h2>APPLE INC.<br />FORM 10-K</h2><div className="filing-line" /><p>For the fiscal year ended September 28, 2024</p><div className="filing-blocks"><i /><i /><i /><i /><i /></div><small>0000320193 · aapl-20240928.htm</small></div><div className="source-anchor anchor-a">§ ITEM 1A</div><div className="source-anchor anchor-b">TABLE / iXBRL</div><div className="scan-beam" /></div>
      <div className="demo-core-pane"><div className="core-coordinate coordinate-top">SOURCE → STRUCTURE</div><div className="core-coordinate coordinate-bottom">EVERY OUTPUT / INSPECTABLE</div><div className="core-orbit orbit-a" /><div className="core-orbit orbit-b" /><div className="core-orbit orbit-c" /><div className="core-node"><small>{current.state}</small><strong>{current.label.toUpperCase()}</strong><i /></div><div className="evidence-thread thread-a" /><div className="evidence-thread thread-b" /><div className="evidence-thread thread-c" /><div className="thread-signal signal-a">HTML</div><div className="thread-signal signal-b">iXBRL</div><div className="thread-signal signal-c">PROOF</div></div>
      <div className="demo-context-pane"><div className="pane-top"><span>PROPOSED CONTEXT</span><span>{String(active + 1).padStart(2, "0")} / 04</span></div><div className="context-output"><span className="output-label">{current.state}</span>{active === 0 && <><h2>Private perimeter<br />is ready.</h2><p>The original stays addressable before anything is inferred.</p></>}{active === 1 && <><h2>Structure surfaces<br />with its anchors.</h2><p>Headings, tables and readable regions carry their source form forward.</p></>}{active === 2 && <><h2>Forms stay linked,<br />not collapsed.</h2><p>HTML and iXBRL are modeled as related representations for review.</p></>}{active === 3 && <><h2>Context becomes<br />answerable.</h2><div className="demo-directory"><span>Public filings</span><i>/</i><span>Apple Inc.</span><i>/</i><b>FY2024 · 10-K</b></div><div className="demo-entities"><em>Apple Inc.</em><em>Form 10-K</em><em>FY2024</em></div></>}</div><div className="proof-callout"><ShieldCheck size={15} /> ORIGINAL LINK PRESERVED</div></div>
    </section>
    <section className="demo-control"><div className="demo-stages">{STAGES.map((stage, index) => { const Icon = stage.icon; return <button type="button" className={active === index ? "is-active" : ""} onClick={() => { setIsPlaying(false); setActive(index); }} key={stage.id}><span>{String(index + 1).padStart(2, "0")}</span><Icon size={16} /><b>{stage.label}</b>{index < active && <Check size={14} />}</button>; })}</div><div className="demo-action"><p>{current.detail}</p><button type="button" onClick={() => { if (active === STAGES.length - 1) setActive(0); setIsPlaying(true); }}><CirclePlay size={17} /> {isPlaying ? "Compiling from source" : active === STAGES.length - 1 ? "Replay compilation" : "Continue compilation"}</button></div></section>
    <footer className="demo-foot"><span>PUBLIC FIXTURE · NO CUSTOMER DATA</span><span>This is an explanatory interaction, not an automated factual conclusion.</span><a href="/world"><Sparkles size={15} /> COMPILE YOUR SOURCES</a></footer>
  </main>;
}
