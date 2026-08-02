"use client";

import { useId, useState } from "react";

import { DART_PUBLIC_FIXTURE } from "@/lib/dart-public-fixture";
import type { StructaraLocale } from "@/lib/locale";

const copy = {
  en: {
    eyebrow: "One source · two states",
    title: "Move the boundary. Keep the evidence.",
    body: "The same public filing fragment is shown before and after compilation. The result adds structure and a source route; it does not replace the original.",
    raw: "Raw document",
    compiled: "Compiled knowledge",
    repeated: "REVENUE  |  REVENUE  |  REVENUE",
    pageBreak: "— page boundary —",
    source: "No source route",
    heading: "Revenue",
    table: "Normalized table object",
    proof: "Page 13 · table 02 · source cell",
    slider: "Comparison boundary",
    rawButton: "Original",
    splitButton: "Split",
    compiledButton: "Result",
  },
  ko: {
    eyebrow: "하나의 원본 · 두 가지 상태",
    title: "경계를 움직여도 근거는 남습니다.",
    body: "동일한 공개 공시 조각을 컴파일 전후로 비교합니다. 결과는 구조와 원본 경로를 더할 뿐 원본을 대체하지 않습니다.",
    raw: "원본 문서",
    compiled: "컴파일된 지식",
    repeated: "매출  |  매출  |  매출",
    pageBreak: "— 페이지 경계 —",
    source: "원본 경로 없음",
    heading: "매출",
    table: "정규화된 표 객체",
    proof: "13페이지 · 표 02 · 원본 셀",
    slider: "비교 경계",
    rawButton: "원본",
    splitButton: "분할",
    compiledButton: "결과",
  },
} as const;

export function RawCompiledCompare({ locale }: { locale: StructaraLocale }) {
  const text = copy[locale];
  const [position, setPosition] = useState(50);
  const labelId = useId();
  const value = DART_PUBLIC_FIXTURE.rows[0]?.current ?? "4,902,490,901";

  return (
    <section
      className="st-reference-compare"
      data-signature-asset="A02"
      data-truth-class="public-filing-reference-snapshot"
    >
      <header>
        <p>{text.eyebrow}</p>
        <h2>{text.title}</h2>
        <span>{text.body}</span>
      </header>
      <div className="st-compare-stage">
        <article className="st-compare-layer st-compare-raw">
          <small>{text.raw}</small>
          <div className="st-raw-fragment">
            <b>{text.repeated}</b>
            <i />
            <i />
            <strong>{value}</strong>
            <em>{text.pageBreak}</em>
            <span>{text.source}</span>
          </div>
        </article>
        <article
          className="st-compare-layer st-compare-compiled"
          style={{ clipPath: `inset(0 0 0 ${position}%)` }}
        >
          <small>{text.compiled}</small>
          <div className="st-compiled-fragment">
            <p>{text.heading}</p>
            <div>
              <span>{text.table}</span>
              <strong>{value}</strong>
            </div>
            <code>{text.proof}</code>
          </div>
        </article>
        <div className="st-compare-rule" style={{ left: `${position}%` }}>
          <span aria-hidden="true">↔</span>
        </div>
        <input
          id={labelId}
          className="st-compare-range"
          type="range"
          min="0"
          max="100"
          step="2"
          value={position}
          aria-label={text.slider}
          aria-valuetext={`${position}%`}
          onChange={(event) => setPosition(Number(event.target.value))}
          onKeyDown={(event) => {
            if (event.key === " ") {
              event.preventDefault();
              setPosition(50);
            }
          }}
        />
      </div>
      <div className="st-compare-actions" role="group" aria-label={text.slider}>
        <button
          type="button"
          aria-pressed={position === 100}
          onClick={() => setPosition(100)}
        >
          {text.rawButton}
        </button>
        <button
          type="button"
          aria-pressed={position === 50}
          onClick={() => setPosition(50)}
        >
          {text.splitButton}
        </button>
        <button
          type="button"
          aria-pressed={position === 0}
          onClick={() => setPosition(0)}
        >
          {text.compiledButton}
        </button>
      </div>
    </section>
  );
}
