"use client";

import { useEffect, useRef, useState } from "react";

import { StructaraGlyph } from "@/components/structara-glyph";
import type { StructaraLocale } from "@/lib/locale";

const copy = {
  en: {
    eyebrow: "Knowledge flow",
    title: "Many inputs. One verified core. Portable outputs.",
    body: "The lines represent provenance routes, not integrations or live throughput. They animate once when this explanation enters view.",
    inputs: "Inputs",
    compiler: "Compiler",
    outputs: "Outputs",
    inputItems: ["PDF", "Office", "Images", "URL"],
    coreItems: ["Structure", "Verify", "Connect"],
    outputItems: ["Markdown", "Obsidian", "Graph", "RAG"],
  },
  ko: {
    eyebrow: "지식 흐름",
    title: "다양한 입력을 하나의 검증 코어와 이식 가능한 출력으로.",
    body: "선은 연동이나 실시간 처리량이 아니라 원본 추적 경로를 뜻합니다. 이 설명이 화면에 들어올 때 한 번만 움직입니다.",
    inputs: "입력",
    compiler: "컴파일러",
    outputs: "출력",
    inputItems: ["PDF", "Office", "이미지", "URL"],
    coreItems: ["구조화", "검증", "연결"],
    outputItems: ["Markdown", "Obsidian", "그래프", "RAG"],
  },
} as const;

export function KnowledgeFlow({ locale }: { locale: StructaraLocale }) {
  const text = copy[locale];
  const rootRef = useRef<HTMLElement>(null);
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setEntered(true);
          observer.disconnect();
        }
      },
      { threshold: 0.3 },
    );
    observer.observe(root);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      ref={rootRef}
      className="st-knowledge-flow"
      data-entered={entered}
      data-signature-asset="A04"
      data-truth-class="deterministic-reference-scene"
    >
      <header>
        <p>{text.eyebrow}</p>
        <h2>{text.title}</h2>
        <span>{text.body}</span>
      </header>
      <div className="st-flow-stage">
        <FlowColumn title={text.inputs} items={text.inputItems} glyph="page" />
        <svg viewBox="0 0 220 280" aria-hidden="true">
          {[48, 108, 172, 232].map((y, index) => (
            <path
              key={y}
              className="st-flow-path"
              style={{ animationDelay: `${index * 100}ms` }}
              d={`M 0 ${y} C 88 ${y}, 110 140, 220 140`}
            />
          ))}
        </svg>
        <div className="st-flow-core">
          <span>{text.compiler}</span>
          <StructaraGlyph name="verified" size={36} />
          {text.coreItems.map((item) => (
            <strong key={item}>{item}</strong>
          ))}
        </div>
        <svg viewBox="0 0 220 280" aria-hidden="true">
          {[48, 108, 172, 232].map((y, index) => (
            <path
              key={y}
              className="st-flow-path st-flow-path-reverse"
              style={{ animationDelay: `${400 + index * 100}ms` }}
              d={`M 0 140 C 110 140, 132 ${y}, 220 ${y}`}
            />
          ))}
        </svg>
        <FlowColumn
          title={text.outputs}
          items={text.outputItems}
          glyph="package"
        />
      </div>
      <ol className="st-flow-text-alternative">
        <li>{`${text.inputs}: ${text.inputItems.join(", ")}`}</li>
        <li>{`${text.compiler}: ${text.coreItems.join(", ")}`}</li>
        <li>{`${text.outputs}: ${text.outputItems.join(", ")}`}</li>
      </ol>
    </section>
  );
}

function FlowColumn({
  title,
  items,
  glyph,
}: {
  title: string;
  items: readonly string[];
  glyph: "page" | "package";
}) {
  return (
    <div className="st-flow-column">
      <span>{title}</span>
      {items.map((item) => (
        <div key={item}>
          <StructaraGlyph name={glyph} size={18} />
          <strong>{item}</strong>
        </div>
      ))}
    </div>
  );
}
