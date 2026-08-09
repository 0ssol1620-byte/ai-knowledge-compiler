"use client";

import {
  ArrowClockwise,
  Check,
  FileMagnifyingGlass,
  Prohibit,
  Warning,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useState } from "react";

const issues = [
  {
    id: "numeric",
    severity: "Critical",
    type: "Numeric mismatch",
    page: 42,
    summary: "12,345,678 vs 12,345,673",
  },
  {
    id: "table",
    severity: "High",
    type: "Table structure",
    page: 18,
    summary: "Merged header spans 3 columns",
  },
  {
    id: "order",
    severity: "Review",
    type: "Reading order",
    page: 7,
    summary: "Caption may precede figure",
  },
] as const;

const SAMPLE_CONTROL_TITLE = "This action requires a connected review session.";

export function ReviewStudio() {
  const [selectedId, setSelectedId] = useState("numeric");
  const selected = issues.find((issue) => issue.id === selectedId) ?? issues[0];
  const demoMode = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

  if (!demoMode) {
    return (
      <div className="simple-page">
        <h1>Review Studio</h1>
        <div className="honest-state panel">
          <FileMagnifyingGlass size={26} aria-hidden="true" />
          <p>
            Select a finding in Processing Studio to open its document range and
            audit context here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="review-studio-page">
      <header className="review-studio-header">
        <div>
          <p>Projects / Financial report / Review</p>
          <h1>Review Studio</h1>
        </div>
        <span className="demo-sample-chip">Sample review · 3 open</span>
        <button
          type="button"
          className="secondary-button compact"
          disabled
          title={SAMPLE_CONTROL_TITLE}
          data-sample-static-control
        >
          Completion summary
        </button>
      </header>
      <div className="review-studio-layout">
        <aside className="issue-queue">
          <header>
            <strong>Issue queue</strong>
            <small>Ordered by risk × impact</small>
          </header>
          {issues.map((issue, index) => (
            <button
              type="button"
              className={selectedId === issue.id ? "active" : undefined}
              onClick={() => setSelectedId(issue.id)}
              key={issue.id}
            >
              <span data-severity={issue.severity}>{issue.severity}</span>
              <strong>{issue.type}</strong>
              <small>
                Page {issue.page} · {issue.summary}
              </small>
              <i>{index + 1}</i>
            </button>
          ))}
        </aside>
        <section className="review-source-pane">
          <header>
            <span>Source · Page {selected.page}</span>
            <Link
              className="icon-button compact"
              href="/documents/sample-dart/sources"
              aria-label="Open source evidence"
            >
              <FileMagnifyingGlass size={16} />
            </Link>
          </header>
          <div className="review-paper">
            <span>Consolidated financial statements</span>
            <h2>Revenue by reporting segment</h2>
            <p>
              The table below presents revenue by major reporting segment for
              the fiscal year.
            </p>
            <div className="review-paper-table">
              <span>Segment</span>
              <span>FY 2025</span>
              <strong>Enterprise</strong>
              <strong>12,345,678</strong>
              <span>Consumer</span>
              <span>8,904,221</span>
            </div>
            <i>
              <Warning size={12} weight="fill" />
              Numeric evidence · 2 values
            </i>
          </div>
        </section>
        <aside className="candidate-pane">
          <header>
            <div>
              <span>{selected.severity}</span>
              <strong>{selected.type}</strong>
            </div>
            <small>Page {selected.page} · 2 evidence values</small>
          </header>
          <section>
            <span>CURRENT RESULT</span>
            <strong>12,345,673</strong>
            <small>OCR extraction · disagreement</small>
          </section>
          <div className="candidate-choice-grid">
            <button
              type="button"
              disabled
              title={SAMPLE_CONTROL_TITLE}
              data-sample-static-control
            >
              <span>Candidate A · Native</span>
              <strong>12,345,678</strong>
              <small>Matches source text layer</small>
            </button>
            <button
              type="button"
              disabled
              title={SAMPLE_CONTROL_TITLE}
              data-sample-static-control
            >
              <span>Candidate B · OCR</span>
              <strong>12,345,673</strong>
              <small>Visual model result</small>
            </button>
          </div>
          <label>
            <span>Manual value</span>
            <input
              defaultValue="12,345,678"
              disabled
              title={SAMPLE_CONTROL_TITLE}
            />
          </label>
          <div className="candidate-actions">
            <button
              className="secondary-button compact"
              type="button"
              disabled
              title={SAMPLE_CONTROL_TITLE}
              data-sample-static-control
            >
              <ArrowClockwise size={14} />
              Reprocess
            </button>
            <button
              className="secondary-button compact"
              type="button"
              disabled
              title={SAMPLE_CONTROL_TITLE}
              data-sample-static-control
            >
              <Prohibit size={14} />
              Ignore with reason
            </button>
            <button
              className="primary-button compact"
              type="button"
              disabled
              title={SAMPLE_CONTROL_TITLE}
              data-sample-static-control
            >
              <Check size={14} />
              Accept candidate A
            </button>
          </div>
          <p className="review-shortcuts">
            Sample evidence only · connect a review session to edit or accept
          </p>
        </aside>
      </div>
    </div>
  );
}
