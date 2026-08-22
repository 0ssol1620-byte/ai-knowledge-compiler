"use client";

import { useEffect, useRef, useState } from "react";

import { DART_PUBLIC_FIXTURE } from "@/lib/dart-public-fixture";
import type { StructaraLocale } from "@/lib/locale";

const PHASES = [
  "collect",
  "structure",
  "verify",
  "knowledge",
  "package",
] as const;
type Phase = (typeof PHASES)[number];

const LABELS: Record<StructaraLocale, Record<Phase, string>> = {
  en: {
    collect: "Collect",
    structure: "Structure",
    verify: "Verify",
    knowledge: "Knowledge",
    package: "Package",
  },
  ko: {
    collect: "수집",
    structure: "구조화",
    verify: "검증",
    knowledge: "지식화",
    package: "패키지",
  },
};

const COPY = {
  en: {
    eyebrow: "LIVE PRODUCT · DETERMINISTIC PUBLIC FIXTURE",
    title: "Watch evidence become usable knowledge.",
    pause: "Pause demo",
    resume: "Resume demo",
    replay: "Replay demo",
    source: "Public source",
    receipt: "OpenDART receipt",
    exact: "Exact source cell",
    noClaim: "Native XBRL authority · no parser-quality claim",
  },
  ko: {
    eyebrow: "라이브 제품 · 결정론적 공개 픽스처",
    title: "근거가 활용 가능한 지식이 되는 과정을 확인하세요.",
    pause: "데모 일시정지",
    resume: "데모 계속 재생",
    replay: "데모 다시 재생",
    source: "공개 원본",
    receipt: "OpenDART 접수번호",
    exact: "정확한 원본 셀",
    noClaim: "네이티브 XBRL 권위 근거 · 파서 품질 주장 아님",
  },
} satisfies Record<StructaraLocale, Record<string, string>>;

export function StructaraLiveDemo({
  locale = "en",
}: {
  locale?: StructaraLocale;
}) {
  const [phaseIndex, setPhaseIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [inView, setInView] = useState(true);
  const [documentVisible, setDocumentVisible] = useState(true);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const rootRef = useRef<HTMLElement>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const phase = PHASES[phaseIndex]!;
  const labels = LABELS[locale];
  const copy = COPY[locale];

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      setReducedMotion(media.matches);
      if (media.matches) setPhaseIndex(PHASES.length - 1);
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => setInView(Boolean(entry?.isIntersecting)),
      { rootMargin: "100px" },
    );
    const onVisibility = () => setDocumentVisible(!document.hidden);
    observer.observe(node);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  useEffect(() => {
    if (paused || reducedMotion || !inView || !documentVisible) return;
    const id = window.setInterval(() => {
      setPhaseIndex((current) => (current + 1) % PHASES.length);
    }, 2400);
    return () => window.clearInterval(id);
  }, [paused, reducedMotion, inView, documentVisible]);

  function selectPhase(nextIndex: number, announce = true) {
    setPhaseIndex(nextIndex);
    setPaused(true);
    if (announce) {
      setAnnouncement(`${labels[PHASES[nextIndex]!]} phase selected`);
    }
  }

  function handleTabKey(
    event: React.KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % PHASES.length;
    else if (event.key === "ArrowLeft")
      next = (index - 1 + PHASES.length) % PHASES.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = PHASES.length - 1;
    else return;
    event.preventDefault();
    selectPhase(next);
    tabRefs.current[next]?.focus();
  }

  return (
    <section
      ref={rootRef}
      className="st-live-demo"
      data-phase={phase}
      data-paused={paused || reducedMotion}
      aria-labelledby="st-live-demo-title"
    >
      <header className="st-live-demo-header">
        <div>
          <p>{copy.eyebrow}</p>
          <h2 id="st-live-demo-title">{copy.title}</h2>
        </div>
        <div className="st-live-demo-controls">
          <button type="button" onClick={() => setPaused((value) => !value)}>
            {paused ? copy.resume : copy.pause}
          </button>
          <button
            type="button"
            onClick={() => {
              setPhaseIndex(0);
              setPaused(false);
              setAnnouncement(`${labels.collect} phase selected`);
            }}
          >
            {copy.replay}
          </button>
        </div>
      </header>

      <div
        className="st-live-demo-tabs"
        role="tablist"
        aria-label="Knowledge compilation phases"
      >
        {PHASES.map((item, index) => (
          <button
            key={item}
            ref={(node) => {
              tabRefs.current[index] = node;
            }}
            id={`st-live-tab-${item}`}
            type="button"
            role="tab"
            aria-selected={phase === item}
            aria-controls={`st-live-panel-${item}`}
            tabIndex={phase === item ? 0 : -1}
            onClick={() => selectPhase(index)}
            onKeyDown={(event) => handleTabKey(event, index)}
          >
            <span>{String(index + 1).padStart(2, "0")}</span>
            {labels[item]}
          </button>
        ))}
      </div>

      <div className="st-live-demo-stage">
        <aside className="st-live-source" aria-label={copy.source}>
          <div className="st-live-source-meta">
            <span>{copy.source}</span>
            <strong>{DART_PUBLIC_FIXTURE.company}</strong>
            <small>
              {copy.receipt} {DART_PUBLIC_FIXTURE.receiptNumber}
            </small>
          </div>
          <div className="st-live-page">
            <i className="st-live-page-title" />
            <i className="st-live-page-line" />
            <i className="st-live-page-line st-live-page-line-short" />
            <div className="st-live-page-table">
              <span>Revenue</span>
              <b className={phase === "verify" ? "is-exact" : undefined}>
                {DART_PUBLIC_FIXTURE.rows[0].current}
              </b>
              <span>{DART_PUBLIC_FIXTURE.rows[0].prior}</span>
            </div>
          </div>
          <footer>
            <span>{copy.exact}</span>
            <code>{DART_PUBLIC_FIXTURE.rows[0].taxonomy}</code>
          </footer>
        </aside>

        <div
          className="st-live-output"
          id={`st-live-panel-${phase}`}
          role="tabpanel"
          aria-labelledby={`st-live-tab-${phase}`}
          tabIndex={0}
        >
          <header>
            <span className="st-live-status">
              <i /> {labels[phase]}
            </span>
            <small>{String(phaseIndex + 1).padStart(2, "0")} / 05</small>
          </header>
          <PhaseContent phase={phase} locale={locale} />
        </div>
      </div>

      <footer className="st-live-demo-footer">
        <div aria-hidden="true">
          {PHASES.map((item, index) => (
            <i key={item} data-complete={index <= phaseIndex} />
          ))}
        </div>
        <span>{copy.noClaim}</span>
        <code title={DART_PUBLIC_FIXTURE.archiveSha256}>
          sha256:{DART_PUBLIC_FIXTURE.archiveSha256.slice(0, 12)}…
        </code>
      </footer>
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </section>
  );
}

function PhaseContent({
  phase,
  locale,
}: {
  phase: Phase;
  locale: StructaraLocale;
}) {
  if (phase === "collect") {
    return (
      <div className="st-live-manifest">
        <h3>{locale === "ko" ? "컬렉션 매니페스트" : "Collection manifest"}</h3>
        <dl>
          <div>
            <dt>Files</dt>
            <dd>24</dd>
          </div>
          <div>
            <dt>Folders</dt>
            <dd>6 preserved</dd>
          </div>
          <div>
            <dt>Policy</dt>
            <dd>KR · private</dd>
          </div>
          <div>
            <dt>Dedupe</dt>
            <dd>2 provisional</dd>
          </div>
        </dl>
      </div>
    );
  }
  if (phase === "structure") {
    return (
      <div className="st-live-structure">
        <h3>{locale === "ko" ? "페이지 구조" : "Typed page structure"}</h3>
        <ol>
          <li data-kind="heading">
            <span>Heading</span>
            <b>Income statement</b>
          </li>
          <li data-kind="table">
            <span>Table</span>
            <b>4 rows · 3 columns</b>
          </li>
          <li data-kind="footnote">
            <span>Footnote</span>
            <b>Unit · JPY</b>
          </li>
          <li data-kind="excluded">
            <span>Excluded</span>
            <b>Repeated header</b>
          </li>
        </ol>
      </div>
    );
  }
  if (phase === "verify") {
    return (
      <div className="st-live-verify">
        <h3>
          {locale === "ko" ? "First Verified 판정" : "First Verified decision"}
        </h3>
        <div className="st-live-route">
          <span>Native authority</span>
          <strong>Accepted</strong>
          <span>Parser candidate</span>
          <b>Review</b>
        </div>
        <div className="st-live-fact">
          <small>Revenue · {DART_PUBLIC_FIXTURE.currentPeriod}</small>
          <strong>
            {DART_PUBLIC_FIXTURE.rows[0].current} {DART_PUBLIC_FIXTURE.unit}
          </strong>
          <span>
            Numeric gate · exact · source line{" "}
            {DART_PUBLIC_FIXTURE.rows[0].sourceLine}
          </span>
        </div>
      </div>
    );
  }
  if (phase === "knowledge") {
    return (
      <div className="st-live-knowledge">
        <h3>
          {locale === "ko" ? "근거 연결 지식" : "Evidence-linked knowledge"}
        </h3>
        <div className="st-live-note">
          <small>NOTE</small>
          <strong>JTC — 2026 Q1 revenue</strong>
          <span>source refs · 1</span>
        </div>
        <div className="st-live-relation" aria-label="JTC reported Revenue">
          <span>JTC</span>
          <i>reported</i>
          <span>Revenue</span>
        </div>
        <p>1 note · 2 entities · 1 relation · 0 unsupported claims</p>
      </div>
    );
  }
  return (
    <div className="st-live-package">
      <h3>
        {locale === "ko" ? "이식 가능한 패키지" : "Portable knowledge package"}
      </h3>
      <ul>
        <li>
          <span>Markdown</span>
          <strong>Ready</strong>
        </li>
        <li>
          <span>Obsidian vault</span>
          <strong>Ready</strong>
        </li>
        <li>
          <span>RAG JSONL</span>
          <strong>Ready</strong>
        </li>
        <li>
          <span>JSON-LD / RDF</span>
          <strong>Ready</strong>
        </li>
      </ul>
      <code>package-manifest.json · evidence bound</code>
    </div>
  );
}
