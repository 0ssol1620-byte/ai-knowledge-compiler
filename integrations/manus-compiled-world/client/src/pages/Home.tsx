/**
 * TAVONEL — Compiled World Atlas
 * Design reminder: Swiss editorial information design; moss field, parchment paper,
 * precise mono metadata, and intentional motion that explains knowledge compilation.
 */
import "../proof-motion.css";
import { useEffect, useRef, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  Database,
  FileSearch,
  GitCompareArrows,
  Menu,
  Network,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";

const steps = [
  {
    id: "01",
    label: "Structure",
    short: "SOURCE PAGE",
    title: "Read the page as more than text.",
    body: "제목, 문단, 표, 수식, 각주, 읽기 순서를 하나의 검사 가능한 문서 구조로 분리합니다. 구조는 원문을 떠나지 않습니다.",
    metric: "OpenDART · JTC public filing",
    node: "3 TYPED BLOCKS",
  },
  {
    id: "02",
    label: "Evidence",
    short: "SOURCE LINK",
    title: "Keep every result connected to its proof.",
    body: "결과에는 페이지·블록·원문 위치를 함께 남깁니다. 근거가 없는 연결선은 그리지 않고, 검토가 필요한 상태를 그대로 보존합니다.",
    metric: "Revenue · source line 3669",
    node: "TRACEABLE RESULT",
  },
  {
    id: "03",
    label: "Relations",
    short: "KNOWLEDGE GRAPH",
    title: "Connect evidence into reusable knowledge.",
    body: "섹션은 노트가 되고, 노트는 엔터티를 드러냅니다. 서로 분리돼 있던 문서는 근거가 남은 관계로 이어집니다.",
    metric: "JTC · 950170 · quarterly filing",
    node: "3 LINKED ENTITIES",
  },
  {
    id: "04",
    label: "Package",
    short: "PORTABLE OUTPUT",
    title: "Compile once. Use it where work happens.",
    body: "Markdown, Obsidian, RAG JSONL, JSON-LD와 프로젝트 패키지는 모두 같은 출처 지도를 기반으로 생성됩니다.",
    metric: "Markdown · Vault · RAG JSONL · JSON-LD",
    node: "4 DESTINATIONS",
  },
];

const products = [
  {
    number: "01",
    icon: FileSearch,
    name: "Convert",
    eyebrow: "PAGE → TYPED BLOCKS",
    description: "문서의 계층과 읽기 순서를 보존해, 사람이 검토할 수 있는 구조로 변환합니다.",
    tags: ["Heading", "Table", "Reading order"],
    tone: "product-forest",
  },
  {
    number: "02",
    icon: GitCompareArrows,
    name: "Verify",
    eyebrow: "RESULT → PROOF",
    description: "중요한 결과를 원문 페이지와 블록으로 되돌려, 확인 가능한 답변을 만듭니다.",
    tags: ["Page", "Block", "Source line"],
    tone: "product-paper",
  },
  {
    number: "03",
    icon: Network,
    name: "Knowledge",
    eyebrow: "EVIDENCE → CONTEXT",
    description: "검증된 구조를 노트, 엔터티, 관계와 이식 가능한 지식 패키지로 확장합니다.",
    tags: ["Notes", "Entities", "Relations"],
    tone: "product-grid",
  },
];

const proofViews = [
  {
    id: "original",
    label: "Original",
    eyebrow: "PUBLIC SOURCE / SEC EDGAR",
    title: "A source page remains a source page.",
    description: "Apple Inc.의 2024 Form 10-K 원문에서 비즈니스, MD&A, 재무제표의 구조를 읽습니다.",
    signal: "APPLE INC. / FORM 10-K / 2024",
  },
  {
    id: "evidence",
    label: "Evidence",
    eyebrow: "TRACEABLE STRUCTURE",
    title: "A result carries its way back.",
    description: "추출한 구조는 filing 내 항목·페이지·블록 위치를 통해 언제든 다시 확인할 수 있습니다.",
    signal: "ITEM 1 / PAGE 1 / BLOCK 04",
  },
  {
    id: "knowledge",
    label: "Knowledge",
    eyebrow: "CONNECTED CONTEXT",
    title: "Structure becomes reusable context.",
    description: "발행사, 티커, filing의 관계는 독립된 문서를 탐색 가능한 지식 구조로 바꿉니다.",
    signal: "APPLE INC. → AAPL → 10-K",
  },
  {
    id: "package",
    label: "Package",
    eyebrow: "PORTABLE OUTPUT",
    title: "One source map, many destinations.",
    description: "같은 출처 지도를 Markdown, Vault, RAG JSONL, JSON-LD로 옮길 수 있습니다.",
    signal: "4 PORTABLE DESTINATIONS",
  },
];

const SEC_DEMO_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm";

export default function Home() {
  const [activeStep, setActiveStep] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeProof, setActiveProof] = useState(0);
  const [isExtracting, setIsExtracting] = useState(false);
  const stepRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const extractionTimer = useRef<number | null>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible) {
          setActiveStep(Number(visible.target.getAttribute("data-step-index")));
        }
      },
      { rootMargin: "-28% 0px -48% 0px", threshold: [0.2, 0.5, 0.8] },
    );

    stepRefs.current.forEach((node) => node && observer.observe(node));
    return () => observer.disconnect();
  }, []);

  useEffect(() => () => {
    if (extractionTimer.current) window.clearTimeout(extractionTimer.current);
  }, []);

  const selected = steps[activeStep];
  const selectedProof = proofViews[activeProof];

  const runExtraction = (nextIndex = activeProof) => {
    setActiveProof(nextIndex);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (extractionTimer.current) window.clearTimeout(extractionTimer.current);
    setIsExtracting(true);
    extractionTimer.current = window.setTimeout(() => setIsExtracting(false), 920);
  };

  return (
    <main className="site-shell">
      <section className="hero" id="top">
        <div className="hero-grain" aria-hidden="true" />
        <nav className="site-nav" aria-label="주요 탐색">
          <a className="brand" href="#top" aria-label="TAVONEL 첫 화면으로 이동">
            <img src="/manus-storage/tavonel-mark_761fadd4.png" alt="" className="brand-mark" />
            <span className="brand-title">TAVONEL<small>KNOWLEDGE COMPILER</small></span>
          </a>
          <div className="nav-links" aria-label="데스크톱 메뉴">
            <a href="#compiler">Compiler</a>
            <a href="#proof">Proof</a>
            <a href="#products">Products</a>
            <a href="#principles">Principles</a>
          </div>
          <a className="nav-cta" href="/world">Launch a world <ArrowUpRight size={15} /></a>
          <button className="menu-button" type="button" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen} aria-label="메뉴 열기">
            {menuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </nav>

        <div className={`mobile-menu ${menuOpen ? "is-open" : ""}`}>
          <a href="#compiler" onClick={() => setMenuOpen(false)}>Compiler</a>
          <a href="#proof" onClick={() => setMenuOpen(false)}>Proof</a>
          <a href="#products" onClick={() => setMenuOpen(false)}>Products</a>
          <a href="#principles" onClick={() => setMenuOpen(false)}>Principles</a>
          <a href="/world" onClick={() => setMenuOpen(false)}>Launch a world</a>
        </div>

        <div className="hero-copy">
          <div className="eyebrow light"><span className="pulse-dot" /> KNOWLEDGE COMPILER / 01</div>
          <h1>Every output returns<br />to its <em>source.</em></h1>
          <p>TAVONEL turns documents into structured, verified knowledge that people and AI can inspect, reuse, and trace to the original page.</p>
          <div className="hero-actions">
            <a className="button button-lime" href="/demo/sec">Explore SEC demo <ArrowUpRight size={18} /></a>
            <a className="text-link light" href="/world">Compile your sources <ArrowUpRight size={16} /></a>
          </div>
        </div>

        <div className="hero-visual" aria-label="흩어진 원본이 컴파일된 지식 구조로 정렬되는 모습">
          <div className="hero-visual-art" />
          <div className="file-particle particle-a"><span>OPENDART</span><b>JTC · 2026 Q1</b></div>
          <div className="file-particle particle-b"><span>TABLE</span><b>Revenue · 4,902,490,901</b></div>
          <div className="file-particle particle-c"><span>PROOF</span><b>source line 3669</b></div>
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="compile-core">
            <div className="core-top">TAVONEL</div>
            <div className="core-label">VERIFIED<br />KNOWLEDGE</div>
            <div className="core-line" />
            <div className="core-status"><span /> SOURCE LINKED</div>
          </div>
          <div className="provenance-chip"><ShieldCheck size={14} /> PUBLIC PROOF</div>
        </div>

        <div className="hero-foot">
          <span>SCROLL TO COMPILE</span>
          <div className="scroll-rule"><i /></div>
          <span>© 2026 TAVONEL</span>
        </div>
      </section>

      <section className="proof-strip" aria-label="TAVONEL 핵심 원칙">
        <p>Originals stay where they are. <strong>Every result remains inspectable.</strong></p>
        <div className="proof-cells">
          <span>READ-ONLY DISCOVERY</span><span>REVIEW BEFORE CHANGE</span><span>PROVENANCE BY DEFAULT</span>
        </div>
      </section>

      <section className="compiler-section" id="compiler">
        <div className="section-intro">
          <div className="eyebrow"><span>02</span> THE COMPILER / PUBLIC FILING</div>
          <div>
            <h2>From a source page to<br /><em>knowledge with proof.</em></h2>
            <p>공개 DART filing 하나를 따라가 보세요. TAVONEL은 원문을 숨기지 않고, 사람이 확인할 수 있는 근거를 지식 구조 안에 보존합니다.</p>
          </div>
        </div>

        <div className="process-layout">
          <aside className="world-panel" aria-live="polite">
            <div className="world-grid" />
            <div className="world-panel-top"><span>PUBLIC EVIDENCE SURFACE</span><span>{selected.id}/04</span></div>
            <div className={`world-orbit orbit-state-${activeStep}`}>
              <span className="world-node node-one">DART</span>
              <span className="world-node node-two">P.01</span>
              <span className="world-node node-three">ROW</span>
              <span className="world-node node-four">JSON</span>
              <div className="world-center"><small>{selected.short}</small><strong>{selected.node}</strong><i /></div>
            </div>
            <div className="world-panel-bottom">
              <span className="status-live"><i /> {selected.metric}</span>
              <span>PUBLIC FIXTURE</span>
            </div>
          </aside>

          <div className="stage-rail">
            {steps.map((step, index) => (
              <button
                key={step.id}
                ref={(node) => { stepRefs.current[index] = node; }}
                type="button"
                data-step-index={index}
                className={`stage-card ${activeStep === index ? "is-active" : ""}`}
                onClick={() => setActiveStep(index)}
                onFocus={() => setActiveStep(index)}
                aria-pressed={activeStep === index}
              >
                <span className="stage-index">{step.id}</span>
                <span className="stage-content">
                  <span className="stage-label">{step.label}</span>
                  <strong>{step.title}</strong>
                  <span className="stage-body">{step.body}</span>
                  <span className="stage-metric">{step.metric} <ArrowUpRight size={15} /></span>
                </span>
                <span className="stage-track"><i /></span>
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="proof-lens" id="proof" aria-labelledby="proof-title">
        <div className="proof-lens-heading">
          <div className="eyebrow"><span>03</span> PROOF LENS / PUBLIC FILING</div>
          <div>
            <h2 id="proof-title">Do not take the answer.<br /><em>Inspect the path.</em></h2>
            <p>원문, 추출된 구조, 개별 근거, 지식 관계가 하나의 공개 filing에서 어떻게 이어지는지 직접 확인하세요.</p>
          </div>
        </div>

        <div className="proof-workbench">
          <div className="proof-tabs" role="tablist" aria-label="검증 가능한 지식 보기">
            {proofViews.map((view, index) => (
              <button
                key={view.id}
                type="button"
                role="tab"
                aria-selected={activeProof === index}
                aria-controls="proof-surface"
                className={activeProof === index ? "is-active" : ""}
                onClick={() => runExtraction(index)}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>{view.label}
              </button>
            ))}
          </div>

          <div className={`proof-surface ${isExtracting ? "is-extracting" : ""}`} id="proof-surface" role="tabpanel">
            <article className="proof-source">
              <div className="proof-source-head"><span>SEC EDGAR</span><span>CIK 0000320193</span></div>
              <div className="proof-document">
                <small>{selectedProof.eyebrow}</small>
                <h3>{selectedProof.signal}</h3>
                {activeProof === 0 && <><p>Apple Inc. / Form 10-K / fiscal year ended September 28, 2024</p><div className="proof-table"><span>Item 1</span><strong>Business</strong><span>Item 7</span><strong>MD&amp;A</strong><span>Item 8</span><strong>Financial Statements</strong></div></>}
                {activeProof === 1 && <div className="proof-evidence-row"><span>Structured section</span><strong>Item 1 · Business</strong><em>business-description</em><b>page 1 · block 04</b></div>}
                {activeProof === 2 && <div className="proof-entity-stack"><span>Apple Inc. <i>issuer</i></span><span>AAPL <i>ticker</i></span><span>Form 10-K 2024 <i>filing</i></span></div>}
                {activeProof === 3 && <div className="proof-package-stack"><span>Markdown</span><span>Obsidian Vault</span><span>RAG JSONL</span><span>JSON-LD</span></div>}
              </div>
              <a href={SEC_DEMO_URL} target="_blank" rel="noreferrer">Open SEC filing <ArrowUpRight size={15} /></a>
            </article>

            <div className="proof-thread" aria-hidden="true"><span /><i /><span /></div>

            <article className="proof-result">
              <span className="proof-result-label">TAVONEL COMPILED CONTEXT</span>
              <h3>{selectedProof.title}</h3>
              <p>{selectedProof.description}</p>
              <button className="proof-replay" type="button" onClick={() => runExtraction()}><span>{isExtracting ? "EXTRACTING" : "REPLAY EXTRACTION"}</span><ArrowUpRight size={15} /></button>
              <div className="proof-result-foot"><span aria-live="polite">{isExtracting ? "SOURCE → STRUCTURE → EVIDENCE → CONTEXT" : "PROVENANCE PRESERVED"}</span><b>{selectedProof.signal}</b></div>
            </article>
          </div>
        </div>
      </section>

      <section className="principles-section" id="principles">
        <div className="principle-intro">
          <div className="eyebrow light"><span>04</span> WHY IT HOLDS</div>
          <h2>AI should not have to<br />guess what is true.</h2>
        </div>
        <div className="principle-list">
          <article><Database size={23} /><span>01</span><small className="principle-stamp">SOURCE / INDEX</small><h3>Organization</h3><p>파일을 저장하는 대신 의미에 따라 구조를 설계합니다.</p></article>
          <article><Sparkles size={23} /><span>02</span><small className="principle-stamp">STATE / CURRENT</small><h3>Currentness</h3><p>서로 충돌하는 문서 중 현재 유효한 사실을 결정합니다.</p></article>
          <article><ShieldCheck size={23} /><span>03</span><small className="principle-stamp">PROOF / LINKED</small><h3>Provenance</h3><p>모든 사실을 원문·페이지·문장·시점까지 추적합니다.</p></article>
          <article><GitCompareArrows size={23} /><span>04</span><small className="principle-stamp">DELTA / SCOPED</small><h3>Incremental</h3><p>변경된 지식과 영향 범위만 선택적으로 다시 컴파일합니다.</p></article>
        </div>
      </section>

      <section className="products-section" id="products">
        <div className="products-heading">
          <div className="eyebrow"><span>05</span> PRODUCT SYSTEM</div>
          <h2>Three entry points.<br />One <em>evidence standard.</em></h2>
          <p>문서를 읽는 순간부터 결과를 재사용하는 순간까지, 모든 계층은 하나의 출처 연결 원칙을 공유합니다.</p>
        </div>
        <div className="products-grid">
          {products.map((product) => {
            const Icon = product.icon;
            return (
              <article className={`product-card product-card--${product.number} ${product.tone}`} key={product.number}>
                <div className="product-card-top"><span>{product.number}</span><Icon size={23} /></div>
                <div className="product-art" aria-hidden="true"><div className="art-core" /><div className="art-line art-line-a" /><div className="art-line art-line-b" /><div className="art-line art-line-c" /></div>
                <div className="product-card-copy">
                  <span className="product-eyebrow">{product.eyebrow}</span>
                  <h3>{product.name}</h3>
                  <p>{product.description}</p>
                </div>
                <div className="product-card-footer">
                  <div>{product.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                  <ArrowUpRight size={20} className="card-arrow" />
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="contact-section" id="contact">
        <div className="contact-mark"><img src="/manus-storage/tavonel-mark_761fadd4.png" alt="" /><span>ARC / 05</span></div>
        <div><div className="eyebrow light">START WITH WHAT YOU ALREADY HAVE</div><h2>Make your documents<br /><em>answerable.</em></h2></div>
        <div className="contact-coordinate" aria-hidden="true"><span>DOCUMENT</span><i /><span>PROOF</span><i /><span>CONTEXT</span></div>
        <a className="button button-lime contact-button" href="mailto:hello@tavonel.ai">Start a conversation <ArrowUpRight size={18} /></a>
      </section>

      <footer className="site-footer"><span>© TAVONEL / KNOWLEDGE COMPILER</span><span>ORIGINALS PRESERVED. CONTEXT COMPILED.</span><a href="#top">BACK TO TOP ↑</a></footer>
    </main>
  );
}
