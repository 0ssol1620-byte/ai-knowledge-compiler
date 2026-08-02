"use client";

import { useState } from "react";

import { DART_PUBLIC_FIXTURE } from "@/lib/dart-public-fixture";
import type { StructaraLocale } from "@/lib/locale";

const tabs = ["Original", "Markdown", "Vault", "Graph", "Proof"] as const;
const viewContent = {
  Original: {
    eyebrow: "ORIGINAL · PUBLIC SOURCE FIXTURE",
    title: "Source filing",
    statement:
      "The selected revenue cell remains attached to the exact XBRL taxonomy and acquired source line.",
    code: "ifrs-full_Revenue · line 3669",
  },
  Markdown: {
    eyebrow: "MARKDOWN · SOURCE-LINKED OUTPUT",
    title: "Revenue overview",
    statement:
      "JTC reported consolidated revenue of 4,902,490,901 JPY for 2026 Q1.",
    code: "| Revenue | 4,902,490,901 | 10,048,464,180 |",
  },
  Vault: {
    eyebrow: "VAULT · PORTABLE KNOWLEDGE",
    title: "JTC — 2026 Q1 revenue",
    statement:
      "A focused note preserves company, period, currency, report, and the original receipt as portable properties.",
    code: "source_receipt: 20260730000413",
  },
  Graph: {
    eyebrow: "GRAPH · RELATION WITH PROOF",
    title: "JTC → reported → Revenue",
    statement:
      "The relation resolves to the same public filing evidence instead of becoming an unsupported graph edge.",
    code: "JTC —[reported]→ Revenue · evidence: 1",
  },
  Proof: {
    eyebrow: "PROOF · CRYPTOGRAPHIC RECEIPT",
    title: "Evidence record",
    statement:
      "The source archive and extracted XML are hash-pinned so the demonstration can be reproduced and audited.",
    code: "archive sha256 3b7876350a203296…",
  },
} satisfies Record<
  (typeof tabs)[number],
  {
    eyebrow: string;
    title: string;
    statement: string;
    code: string;
  }
>;

type EvidenceState = "idle" | "hover" | "keyboard" | "pinned" | "compare";

export function StructaraProofDemo({
  locale = "en",
}: {
  locale?: StructaraLocale;
}) {
  const [active, setActive] = useState<(typeof tabs)[number]>("Proof");
  const [evidenceState, setEvidenceState] = useState<EvidenceState>("pinned");
  const revenue = DART_PUBLIC_FIXTURE.rows[0];
  const view = viewContent[active];

  return (
    <div className="st-proof-demo" data-evidence-state={evidenceState}>
      <div className="st-proof-tabs" role="tablist" aria-label="DART demo view">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={active === tab}
            onClick={() => {
              setActive(tab);
              setEvidenceState(tab === "Original" ? "compare" : "pinned");
            }}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="st-proof-workspace">
        <div className="st-proof-rail">
          <span>Report cover</span>
          <span>Financial statements</span>
          <strong>Income statement · Table</strong>
          <span>Notes</span>
        </div>
        <div className="st-proof-source">
          <small>
            ORIGINAL · OPENDART RECEIPT {DART_PUBLIC_FIXTURE.receiptNumber}
          </small>
          <h3>{DART_PUBLIC_FIXTURE.company}</h3>
          <p>{DART_PUBLIC_FIXTURE.statement}</p>
          <div className="st-source-table">
            <span>Line item</span>
            <span>{DART_PUBLIC_FIXTURE.currentPeriod}</span>
            <span>{DART_PUBLIC_FIXTURE.priorPeriod}</span>
            {DART_PUBLIC_FIXTURE.rows.slice(0, 2).map((row, index) => (
              <div className="st-source-table-row" key={row.label}>
                <span>{row.label}</span>
                <button
                  type="button"
                  className={
                    index === 0 ? "st-source-cell-selected" : undefined
                  }
                  aria-label={
                    index === 0
                      ? `${row.label} ${row.current} ${DART_PUBLIC_FIXTURE.unit}, selected source evidence`
                      : undefined
                  }
                  onMouseEnter={() => index === 0 && setEvidenceState("hover")}
                  onMouseLeave={() => index === 0 && setEvidenceState("idle")}
                  onFocus={() => index === 0 && setEvidenceState("keyboard")}
                  onBlur={() => index === 0 && setEvidenceState("idle")}
                  onClick={() => index === 0 && setEvidenceState("pinned")}
                >
                  {row.current}
                </button>
                <span>{row.prior}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="st-proof-result">
          <small>{view.eyebrow}</small>
          <h3>{view.title}</h3>
          <p>{view.statement}</p>
          {active === "Graph" && (
            <div
              className="st-proof-mini-graph"
              aria-label="JTC reported revenue"
            >
              <span>JTC</span>
              <i />
              <span>Revenue</span>
            </div>
          )}
          {active !== "Graph" && <code>{view.code}</code>}
          <div className="st-proof-evidence">
            <span>Source</span>
            <strong>
              {revenue.taxonomy} · source line {revenue.sourceLine}
            </strong>
            <small>
              Origin: native XBRL-tagged table · Unit:{" "}
              {DART_PUBLIC_FIXTURE.unit} · No quality claim
            </small>
          </div>
          <div className="folynta-evidence-state" aria-live="polite">
            <span>{locale === "ko" ? "상호작용 상태" : "Interaction state"}</span>
            <strong>{evidenceState}</strong>
            <small>
              {locale === "ko"
                ? "hover · keyboard · pinned · compare를 직접 확인할 수 있습니다. loading · missing · unresolved는 유효한 현재 픽스처에 적용되지 않습니다."
                : "Inspect hover, keyboard, pinned, and compare directly. Loading, missing, and unresolved do not apply to this valid fixture."}
            </small>
          </div>
        </div>
      </div>
      <footer className="st-proof-provenance">
        <span>Public filing · deterministic fixture</span>
        <a
          href={DART_PUBLIC_FIXTURE.sourceUrl}
          target="_blank"
          rel="noreferrer"
        >
          Verify receipt {DART_PUBLIC_FIXTURE.receiptNumber}
        </a>
        <code title={DART_PUBLIC_FIXTURE.archiveSha256}>
          archive sha256 {DART_PUBLIC_FIXTURE.archiveSha256.slice(0, 12)}…
        </code>
      </footer>
    </div>
  );
}
