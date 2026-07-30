"use client";

import {
  ArrowRight,
  FileText,
  Funnel,
  Graph,
  MagnifyingGlass,
  Rows,
  ShieldCheck,
} from "@phosphor-icons/react";
import { useState } from "react";

const tabs = [
  "Overview",
  "Notes",
  "Graph",
  "Entities",
  "Relations",
  "Evidence",
];

export function KnowledgeStudio() {
  const [activeTab, setActiveTab] = useState("Graph");
  const demoMode = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

  return (
    <div className="knowledge-studio-page">
      <header className="knowledge-context-header">
        <div>
          <p>Knowledge Bases / Research evidence</p>
          <h1>Research evidence</h1>
        </div>
        <span className="demo-sample-chip">
          {demoMode ? "Sample preview" : "No live base selected"}
        </span>
        <button className="secondary-button compact" type="button">
          <Funnel size={14} aria-hidden="true" />
          Perspective
        </button>
      </header>
      <nav className="knowledge-tabs" aria-label="지식베이스 보기">
        {tabs.map((tab) => (
          <button
            type="button"
            className={activeTab === tab ? "active" : undefined}
            aria-pressed={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            key={tab}
          >
            {tab}
          </button>
        ))}
      </nav>

      {!demoMode ? (
        <div className="honest-state knowledge-empty">
          <Graph size={28} weight="duotone" aria-hidden="true" />
          <div>
            <h2>표시할 지식베이스를 선택하세요.</h2>
            <p>
              라이브 데이터가 선택되기 전에는 샘플 엔터티나 관계 수를 표시하지
              않습니다.
            </p>
          </div>
        </div>
      ) : (
        <div className="knowledge-layout">
          <aside className="knowledge-explorer">
            <label>
              <MagnifyingGlass size={14} aria-hidden="true" />
              <input type="search" placeholder="노트 또는 엔터티 검색" />
            </label>
            <span>NOTES · SAMPLE</span>
            {[
              ["MOC", "Evidence-grounded RAG"],
              ["Concept", "Source coverage"],
              ["Method", "Numeric verification"],
              ["Finding", "Retrieval quality"],
              ["Risk", "Unsupported claims"],
            ].map(([type, label], index) => (
              <button
                type="button"
                className={index === 0 ? "active" : undefined}
                key={label}
              >
                <FileText size={15} weight="duotone" aria-hidden="true" />
                <span>
                  <strong>{label}</strong>
                  <small>{type}</small>
                </span>
              </button>
            ))}
          </aside>

          <section className="knowledge-canvas">
            <header>
              <div>
                <span>LOCAL GRAPH · DEPTH 1</span>
                <strong>Evidence-grounded RAG</strong>
              </div>
              <div>
                <button className="secondary-button compact" type="button">
                  <Rows size={14} aria-hidden="true" />
                  Table alternative
                </button>
              </div>
            </header>
            <div className="graph-sample" aria-label="샘플 로컬 지식 그래프">
              <svg viewBox="0 0 800 480" aria-hidden="true">
                <path d="M400 240 L210 120 M400 240 L594 112 M400 240 L650 300 M400 240 L230 345 M400 240 L405 60" />
                <path d="M210 120 L405 60 M594 112 L650 300 M230 345 L650 300" />
              </svg>
              <button className="graph-node graph-node-center" type="button">
                <strong>Evidence-grounded RAG</strong>
                <small>Knowledge note</small>
              </button>
              <button className="graph-node graph-node-a" type="button">
                Source coverage
              </button>
              <button className="graph-node graph-node-b" type="button">
                Numeric check
              </button>
              <button className="graph-node graph-node-c" type="button">
                Retrieval quality
              </button>
              <button className="graph-node graph-node-d" type="button">
                Unsupported claim
              </button>
              <button className="graph-node graph-node-e" type="button">
                Research paper
              </button>
              <span className="graph-sample-label">
                Sample data · 6 nodes · 8 relations
              </span>
            </div>
          </section>

          <aside className="knowledge-evidence-panel">
            <header>
              <ShieldCheck size={18} weight="fill" aria-hidden="true" />
              <div>
                <strong>Evidence</strong>
                <small>1 source block</small>
              </div>
            </header>
            <div className="evidence-assertion">
              <span>KNOWLEDGE ASSERTION</span>
              <p>
                Results linked to source evidence reduce unsupported claims in
                retrieval evaluation.
              </p>
            </div>
            <ol>
              <li>
                <span>1</span>
                <div>
                  <strong>research-paper.pdf</strong>
                  <small>Page 8 · paragraph · native extraction</small>
                </div>
              </li>
              <li>
                <span>2</span>
                <div>
                  <strong>Source block</strong>
                  <small>blk_paragraph · verified · revision 1</small>
                </div>
              </li>
              <li>
                <span>3</span>
                <div>
                  <strong>Review history</strong>
                  <small>No unresolved issues</small>
                </div>
              </li>
            </ol>
            <button className="secondary-button" type="button">
              원본 근거 열기
              <ArrowRight size={14} aria-hidden="true" />
            </button>
          </aside>
        </div>
      )}
    </div>
  );
}
