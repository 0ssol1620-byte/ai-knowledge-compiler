"use client";

import { useState } from "react";

const tabs = ["Original", "Markdown", "Vault", "Graph", "Proof"] as const;

export function StructaraProofDemo() {
  const [active, setActive] = useState<(typeof tabs)[number]>("Proof");

  return (
    <div className="st-proof-demo">
      <div className="st-proof-tabs" role="tablist" aria-label="DART demo view">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={active === tab}
            onClick={() => setActive(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="st-proof-workspace">
        <div className="st-proof-rail">
          <span>Page 126</span>
          <span>Page 127</span>
          <strong>Page 128 · Table</strong>
          <span>Page 129</span>
        </div>
        <div className="st-proof-source">
          <small>ORIGINAL · PAGE 128</small>
          <h3>Consolidated revenue</h3>
          <p>Revenue by reportable segment</p>
          <div className="st-source-table">
            <span>Segment</span>
            <span>2025</span>
            <span>2024</span>
            <span>Platform</span>
            <b>12,345,678</b>
            <span>11,832,091</span>
            <span>Services</span>
            <span>4,882,103</span>
            <span>4,412,870</span>
          </div>
          <i className="st-source-box" />
        </div>
        <div className="st-proof-result">
          <small>{active.toUpperCase()} · VERIFIED SAMPLE</small>
          <h3>{active === "Original" ? "Source page" : "Revenue overview"}</h3>
          <p>
            The Platform segment reported consolidated revenue of{" "}
            <button type="button">12,345,678</button>.
          </p>
          <code>| Platform | 12,345,678 | 11,832,091 |</code>
          <div className="st-proof-evidence">
            <span>Source</span>
            <strong>p128 · block 07 · cell R2C2</strong>
            <small>Origin: native table · Review: verified sample</small>
          </div>
        </div>
      </div>
    </div>
  );
}
