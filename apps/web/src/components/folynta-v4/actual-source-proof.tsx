"use client";

import {
  ArrowSquareOut,
  CheckCircle,
  FilePdf,
  Minus,
  Plus,
  Warning,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { DART_PUBLIC_FIXTURE } from "@/lib/dart-public-fixture";
import { SEC_PUBLIC_FIXTURE } from "@/lib/sec-public-fixture";
import type { StructaraLocale } from "@/lib/locale";

import styles from "./folynta-v4.module.css";

type Market = "dart" | "sec";
type View = "Original" | "Structured" | "Knowledge" | "Proof";

function PdfSource({ scale }: { scale: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    let cancelled = false;
    let cancelRender: (() => void) | undefined;
    async function render() {
      setState("loading");
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc =
          "/proof-sources/pdf.worker-6.2.108.min.mjs";
        const document = await pdfjs.getDocument({
          url: "/proof-sources/dart-jtc-2026-q1.pdf",
        }).promise;
        const page = await document.getPage(30);
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas || cancelled) return;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("2D canvas unavailable");
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
        const renderTask = page.render({
          canvas,
          canvasContext: context,
          viewport,
        });
        cancelRender = () => renderTask.cancel();
        await renderTask.promise;
        if (!cancelled) setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    }
    void render();
    return () => {
      cancelled = true;
      cancelRender?.();
    };
  }, [scale]);
  return (
    <div className={styles.pdfViewport} data-render-state={state}>
      {state === "loading" && <p>PDF.js · loading actual source bytes…</p>}
      {state === "error" && (
        <p>
          <Warning size={15} />
          PDF rendering failed. Use the official source link.
        </p>
      )}
      <canvas
        ref={canvasRef}
        aria-label="DART JTC 2026 Q1 filing, actual PDF page 30"
      />
      <span>PDF.js 6.2.108 · actual DART PDF · page 30 / 121</span>
    </div>
  );
}

function LazyPdfSource({ scale }: { scale: number }) {
  const boundaryRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    const boundary = boundaryRef.current;
    if (!boundary || typeof IntersectionObserver === "undefined") {
      setActive(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        setActive(true);
        observer.disconnect();
      },
      { rootMargin: "240px 0px" },
    );
    observer.observe(boundary);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={boundaryRef} className={styles.pdfBoundary}>
      {active ? (
        <PdfSource scale={scale} />
      ) : (
        <div className={styles.pdfViewport} data-render-state="idle">
          <p>Actual source loads when this scene enters the viewport.</p>
        </div>
      )}
    </div>
  );
}

export function ActualSourceProof({ locale }: { locale: StructaraLocale }) {
  const [market, setMarket] = useState<Market>(
    locale === "ko" ? "dart" : "sec",
  );
  const [view, setView] = useState<View>("Original");
  const [scale, setScale] = useState(0.82);
  const ko = locale === "ko";
  const revenue = DART_PUBLIC_FIXTURE.rows[0];
  return (
    <section
      id="actual-source"
      className={styles.section}
      data-scene="04-actual-source"
    >
      <header className={styles.sectionHeading}>
        <p>04 · ACTUAL SOURCE PROOF</p>
        <h2>
          {ko
            ? "결과를 클릭하면 실제 원문 페이지로 돌아갑니다."
            : "Select a result. Return to the actual source page."}
        </h2>
        <span>
          {ko
            ? "DART 기본 장면은 2,276,931바이트의 실제 공시 PDF를 PDF.js로 렌더링합니다. DOM 재구성을 원문으로 표시하지 않습니다."
            : "The DART scene renders the 2,276,931-byte official filing PDF with PDF.js. A DOM reconstruction is never labeled as original."}
        </span>
      </header>
      <div className={styles.proofFrame} data-market={market}>
        <div className={styles.proofToolbar}>
          <div
            role="group"
            aria-label={ko ? "공개 근거 시장" : "Public proof market"}
          >
            <button
              type="button"
              aria-pressed={market === "dart"}
              onClick={() => setMarket("dart")}
            >
              DART · KR
            </button>
            <button
              type="button"
              aria-pressed={market === "sec"}
              onClick={() => setMarket("sec")}
            >
              SEC · US
            </button>
          </div>
          <div role="tablist" aria-label={ko ? "증명 보기" : "Proof views"}>
            {(["Original", "Structured", "Knowledge", "Proof"] as const).map(
              (item) => (
                <button
                  key={item}
                  role="tab"
                  type="button"
                  aria-selected={view === item}
                  onClick={() => setView(item)}
                >
                  {item}
                </button>
              ),
            )}
          </div>
        </div>
        {market === "dart" && view === "Original" && (
          <div className={styles.pdfStage}>
            <div className={styles.pdfControls}>
              <FilePdf size={15} />
              <strong>[JTC] 분기보고서 (2026.07.30)</strong>
              <button
                type="button"
                aria-label="Zoom out"
                onClick={() => setScale((value) => Math.max(0.55, value - 0.1))}
              >
                <Minus size={14} />
              </button>
              <button
                type="button"
                aria-label="Zoom in"
                onClick={() => setScale((value) => Math.min(1.2, value + 0.1))}
              >
                <Plus size={14} />
              </button>
            </div>
            <LazyPdfSource scale={scale} />
            <aside>
              <small>SELECTED RESULT</small>
              <strong>Revenue · {revenue.current} JPY</strong>
              <span>
                Actual PDF page 30 · source-native XBRL line{" "}
                {revenue.sourceLine}
              </span>
              <code>receipt {DART_PUBLIC_FIXTURE.receiptNumber}</code>
              <a
                href={DART_PUBLIC_FIXTURE.sourceUrl}
                target="_blank"
                rel="noreferrer"
              >
                Open official filing
                <ArrowSquareOut size={13} />
              </a>
            </aside>
          </div>
        )}
        {market === "sec" && view === "Original" && (
          <div className={styles.externalOriginal}>
            <Warning size={18} />
            <div>
              <strong>Official SEC Inline XBRL source</strong>
              <p>
                {ko
                  ? "SEC 원문은 공식 HTML 문서입니다. PDF로 위장하지 않고 공식 아카이브에서 엽니다."
                  : "This SEC source is official Inline XBRL HTML. It is opened at the archive, never disguised as a PDF."}
              </p>
              <a
                href={SEC_PUBLIC_FIXTURE.source.archiveUrl}
                target="_blank"
                rel="noreferrer"
              >
                Open accession {SEC_PUBLIC_FIXTURE.source.accession}
                <ArrowSquareOut size={14} />
              </a>
            </div>
          </div>
        )}
        {view === "Structured" && (
          <div className={styles.structuredView}>
            <small>SOURCE-LINKED STRUCTURE</small>
            <h3>
              {market === "dart"
                ? "Consolidated statement of comprehensive income"
                : "Products and Services Performance"}
            </h3>
            <table>
              <thead>
                <tr>
                  <th>Fact</th>
                  <th>Current</th>
                  <th>Prior</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {market === "dart"
                  ? DART_PUBLIC_FIXTURE.rows.slice(0, 3).map((row) => (
                      <tr key={row.label}>
                        <th>{row.label}</th>
                        <td>{row.current}</td>
                        <td>{row.prior}</td>
                        <td>p.30 · line {row.sourceLine}</td>
                      </tr>
                    ))
                  : SEC_PUBLIC_FIXTURE.facts.slice(0, 3).map((row) => (
                      <tr key={row.id}>
                        <th>{row.label}</th>
                        <td>${row.valueMillions.toLocaleString()}m</td>
                        <td>{row.period}</td>
                        <td>{row.sourceRow}</td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        )}
        {view === "Knowledge" && (
          <div className={styles.knowledgeView}>
            <article>
              <small>VAULT</small>
              <strong>
                {market === "dart"
                  ? "JTC / 2026 / Q1 / Revenue.md"
                  : "Apple / 2025 / Revenue.md"}
              </strong>
              <span>Portable note with source receipt</span>
            </article>
            <article>
              <small>RELATION</small>
              <strong>
                {market === "dart"
                  ? "JTC → reported → Revenue"
                  : "Apple 10-K → reports → Net sales"}
              </strong>
              <span>Edge resolves to the selected fact</span>
            </article>
            <article>
              <small>EXPORT</small>
              <strong>Markdown · JSONL · JSON-LD</strong>
              <span>One verified core, multiple derived formats</span>
            </article>
          </div>
        )}
        {view === "Proof" && (
          <div className={styles.receiptView}>
            {[
              [
                "Authority",
                market === "dart"
                  ? "Financial Supervisory Service DART"
                  : SEC_PUBLIC_FIXTURE.source.authority,
              ],
              [
                "Receipt / accession",
                market === "dart"
                  ? DART_PUBLIC_FIXTURE.receiptNumber
                  : SEC_PUBLIC_FIXTURE.source.accession,
              ],
              [
                "Source location",
                market === "dart"
                  ? "Actual PDF page 30"
                  : SEC_PUBLIC_FIXTURE.source.sourceLocation,
              ],
              [
                "Archive hash",
                market === "dart"
                  ? "fb998430db82774a…"
                  : "pending controlled retrieval",
              ],
            ].map(([label, value], index) => (
              <div key={label} data-complete={market === "dart" || index < 3}>
                <CheckCircle size={15} />
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        )}
        <footer className={styles.truthFooter}>
          {ko
            ? "공개 픽스처 제품 증명 · 벤치마크 정확도 주장 아님"
            : "Public-fixture product proof · not a benchmark accuracy claim"}
        </footer>
      </div>
    </section>
  );
}
