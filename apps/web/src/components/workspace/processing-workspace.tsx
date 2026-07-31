"use client";

import {
  ArrowLeft,
  CaretDown,
  Check,
  CheckCircle,
  Clock,
  DownloadSimple,
  FileText,
  Gauge,
  LockKey,
  ShieldCheck,
  Warning,
} from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useRef, useState, type CSSProperties } from "react";

import { ExportDialog } from "@/components/workspace/export-dialog";
import { MarkdownWorkspace } from "@/components/workspace/markdown-workspace";
import { PageRail } from "@/components/workspace/page-rail";
import { ReviewDrawer } from "@/components/workspace/review-drawer";
import { ProcessingWorkspaceLive } from "@/components/workspace/processing-workspace-live";
import { SourceViewer } from "@/components/workspace/source-viewer";
import {
  demoBlocks,
  demoEstimate,
  demoPages,
  demoReviews,
} from "@/lib/demo-data";
import type { ReviewItem } from "@/lib/types";
import { useDialogFocus } from "@/lib/use-dialog-focus";

const stages = [
  { id: "upload", label: "Upload", done: true },
  { id: "security_scan", label: "Security", done: true },
  { id: "preflight", label: "Preflight", done: true },
  { id: "extract", label: "Extract", done: false, progress: 88 },
  { id: "normalize", label: "Structure", done: false, progress: 72 },
  { id: "knowledge", label: "Knowledge", done: false, progress: 44 },
  { id: "validate", label: "Validate", done: false, progress: 26 },
  { id: "package", label: "Package", done: false, progress: 0 },
] as const;

type MobileTab = "progress" | "pages" | "source" | "result" | "review";

export function ProcessingWorkspace() {
  return process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true" ? (
    <DemoProcessingWorkspace />
  ) : (
    <ProcessingWorkspaceLive />
  );
}

function DemoProcessingWorkspace() {
  const searchParams = useSearchParams();
  const showEstimateInitially = searchParams.get("estimate") === "1";
  const [estimateOpen, setEstimateOpen] = useState(showEstimateInitially);
  const [processingStarted, setProcessingStarted] = useState(
    !showEstimateInitially,
  );
  const [selectedPageId, setSelectedPageId] = useState("page_8");
  const [selectedBlockId, setSelectedBlockId] = useState("blk_paragraph");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>("progress");

  const selectedPage = useMemo(
    () => demoPages.find((page) => page.id === selectedPageId) ?? demoPages[0]!,
    [selectedPageId],
  );
  const visibleBlocks =
    selectedPage.blocks.length > 0 ? selectedPage.blocks : demoBlocks;

  function selectEvidence(item: ReviewItem) {
    if (item.page_id) setSelectedPageId(item.page_id);
    if (item.block_id) setSelectedBlockId(item.block_id);
    setMobileTab("source");
  }

  return (
    <div className="processing-page">
      <header className="processing-header">
        <div className="processing-title-row">
          <Link
            href="/"
            className="icon-button back-button"
            aria-label="Return to projects"
          >
            <ArrowLeft size={18} />
          </Link>
          <div className="document-identity">
            <span className="document-icon" aria-hidden="true">
              <FileText size={20} weight="duotone" />
            </span>
            <div>
              <p>RAG evidence fidelity study</p>
              <h1>evidence-grounded-rag-evaluation.pdf</h1>
            </div>
          </div>
          <button
            className="mode-select"
            type="button"
            disabled
            title="Route changes require a live processing session."
            data-sample-static-control
          >
            <Gauge size={15} weight="fill" aria-hidden="true" />
            Balanced
            <CaretDown size={13} aria-hidden="true" />
          </button>
          <span
            className="live-badge demo-snapshot-badge"
            aria-label="Demo snapshot, not a live connection"
          >
            <Clock size={14} aria-hidden="true" />
            Demo snapshot
          </span>
        </div>
        <div className="processing-actions">
          <button
            className="review-button"
            type="button"
            onClick={() => setReviewOpen(true)}
          >
            <Warning size={15} weight="fill" aria-hidden="true" />
            Review
            <span>{demoReviews.length}</span>
          </button>
          <button
            className="primary-button compact"
            type="button"
            onClick={() => setExportOpen(true)}
          >
            <DownloadSimple size={15} weight="bold" aria-hidden="true" />
            Export
          </button>
        </div>
      </header>

      <section className="pipeline-bar" aria-label="Processing progress">
        <div className="pipeline-summary">
          <div
            className="overall-progress-ring"
            style={{ "--progress": "68%" } as CSSProperties}
          >
            <strong>68%</strong>
          </div>
          <div>
            <strong>
              {processingStarted
                ? "Compiling knowledge"
                : "Review preflight estimate"}
            </strong>
            <span>
              {processingStarted
                ? "16 / 18 pages usable"
                : "No credits are used before approval."}
            </span>
          </div>
        </div>
        <div className="stage-track">
          {stages.map((stage, index) => (
            <div
              className={clsx(
                "stage-item",
                stage.done && "done",
                !stage.done && stage.progress > 0 && "active",
                stage.id === "knowledge" && "current",
              )}
              key={stage.id}
            >
              <span className="stage-node">
                {stage.done ? (
                  <Check size={12} weight="bold" aria-hidden="true" />
                ) : (
                  index + 1
                )}
              </span>
              <span>{stage.label}</span>
              {index < stages.length - 1 && (
                <i>
                  <b
                    style={{
                      width: stage.done ? "100%" : `${stage.progress}%`,
                    }}
                  />
                </i>
              )}
            </div>
          ))}
        </div>
        <div className="cost-meter">
          <span>
            <small>Estimated</small>
            <strong>42</strong>
          </span>
          <span>
            <small>Used</small>
            <strong>31</strong>
          </span>
          <span>
            <small>Reserved</small>
            <strong>7</strong>
          </span>
          <span>
            <small>Maximum</small>
            <strong>48</strong>
          </span>
          <em>credits</em>
        </div>
      </section>

      <nav
        className="mobile-workspace-tabs"
        aria-label="Mobile processing views"
      >
        {(
          [
            ["progress", "Progress"],
            ["pages", "Pages"],
            ["source", "Source"],
            ["result", "Result"],
            ["review", `Review ${demoReviews.length}`],
          ] as Array<[MobileTab, string]>
        ).map(([id, label]) => (
          <button
            type="button"
            className={mobileTab === id ? "active" : undefined}
            onClick={() => {
              setMobileTab(id);
              if (id === "review") setReviewOpen(true);
            }}
            aria-pressed={mobileTab === id}
            key={id}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="processing-grid">
        <section
          className={clsx(
            "mobile-progress-panel mobile-panel",
            mobileTab !== "progress" && "mobile-hidden",
          )}
          aria-label="Processing details"
        >
          <div className="mobile-progress-overview">
            <div
              className="overall-progress-ring"
              style={{ "--progress": "68%" } as CSSProperties}
              aria-label="Overall progress 68%"
            >
              <strong>68%</strong>
            </div>
            <div>
              <span className="mobile-progress-label">Current stage</span>
              <strong>Building knowledge structure</strong>
              <span>16 of 18 pages available</span>
            </div>
          </div>
          <ol className="mobile-stage-list">
            {stages.map((stage, index) => (
              <li
                className={clsx(
                  stage.done && "done",
                  stage.id === "knowledge" && "current",
                )}
                key={stage.id}
              >
                <span className="mobile-stage-marker" aria-hidden="true">
                  {stage.done ? <Check size={13} weight="bold" /> : index + 1}
                </span>
                <span>
                  <strong>{stage.label}</strong>
                  <small>
                    {stage.done
                      ? "Completed"
                      : stage.progress > 0
                        ? `${stage.progress}% complete`
                        : "Waiting"}
                  </small>
                </span>
                <b
                  className="mobile-stage-value"
                  aria-label={
                    stage.done ? "Complete" : `Progress ${stage.progress}%`
                  }
                >
                  {stage.done ? "Done" : `${stage.progress}%`}
                </b>
              </li>
            ))}
          </ol>
          <div
            className="mobile-credit-summary"
            aria-label="Credit usage summary"
          >
            <span>
              <small>Estimated</small>
              <strong>42</strong>
            </span>
            <span>
              <small>Used</small>
              <strong>31</strong>
            </span>
            <span>
              <small>Reserved</small>
              <strong>7</strong>
            </span>
            <span>
              <small>Maximum</small>
              <strong>48</strong>
            </span>
          </div>
        </section>
        <div
          className={clsx(
            "mobile-panel",
            mobileTab !== "pages" && "mobile-hidden",
          )}
        >
          <PageRail
            pages={demoPages}
            selectedPageId={selectedPageId}
            onSelect={(pageId) => {
              setSelectedPageId(pageId);
              setMobileTab("source");
            }}
          />
        </div>
        <div
          className={clsx(
            "mobile-panel",
            mobileTab !== "source" && "mobile-hidden",
          )}
        >
          <SourceViewer
            page={selectedPage}
            sample
            selectedBlockId={selectedBlockId}
            onSelectBlock={(blockId) => {
              setSelectedBlockId(blockId);
              setMobileTab("result");
            }}
          />
        </div>
        <div
          className={clsx(
            "mobile-panel",
            mobileTab !== "result" && "mobile-hidden",
          )}
        >
          <MarkdownWorkspace
            blocks={visibleBlocks}
            selectedBlockId={selectedBlockId}
            onSelectBlock={(blockId) => {
              setSelectedBlockId(blockId);
            }}
          />
        </div>
      </div>

      <footer className="processing-footer">
        <div>
          <span>
            <CheckCircle size={14} weight="fill" aria-hidden="true" />
            16 pages completed
          </span>
          <span>12 Native</span>
          <span>4 OCR</span>
          <span>3 tables rebuilt</span>
          <span>11 knowledge notes</span>
        </div>
        <div>
          <span>
            <ShieldCheck size={14} weight="fill" aria-hidden="true" />
            Third-party model API: none
          </span>
          <span>
            <Clock size={14} aria-hidden="true" />
            2m 14s elapsed
          </span>
        </div>
      </footer>

      <ReviewDrawer
        items={demoReviews}
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        onSelectEvidence={selectEvidence}
      />
      {reviewOpen && (
        <button
          className="drawer-scrim"
          aria-label="Close review pane"
          onClick={() => setReviewOpen(false)}
        />
      )}
      <ExportDialog open={exportOpen} onClose={() => setExportOpen(false)} />

      {estimateOpen && (
        <EstimateDialog
          onCancel={() => {
            setEstimateOpen(false);
          }}
          onConfirm={() => {
            setEstimateOpen(false);
            setProcessingStarted(true);
          }}
        />
      )}
    </div>
  );
}

function EstimateDialog({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const consentRef = useRef<HTMLInputElement>(null);
  const dialogRef = useDialogFocus<HTMLElement>({
    open: true,
    onClose: onCancel,
    initialFocusRef: consentRef,
  });

  return (
    <div
      className="modal-backdrop estimate-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <section
        ref={dialogRef}
        className="modal-card estimate-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="estimate-title"
        tabIndex={-1}
      >
        <div className="estimate-heading">
          <span className="estimate-icon">
            <Gauge size={22} weight="duotone" aria-hidden="true" />
          </span>
          <div>
            <h2 id="estimate-title">Review the estimate before processing</h2>
            <p>
              This estimate comes from a fast structural analysis. Any
              difference is returned after the actual route completes.
            </p>
          </div>
        </div>
        <div className="estimate-page-grid">
          <article>
            <small>Total</small>
            <strong>{demoEstimate.total_pages}</strong>
            <span>pages</span>
          </article>
          <article>
            <small>Native text</small>
            <strong>{demoEstimate.native_pages}</strong>
            <span>Lower-cost route</span>
          </article>
          <article>
            <small>Visual parsing</small>
            <strong>{demoEstimate.visual_pages}</strong>
            <span>OCR·layout</span>
          </article>
          <article>
            <small>Precision candidates</small>
            <strong>{demoEstimate.precision_candidate_pages}</strong>
            <span>Selective cross-checking</span>
          </article>
        </div>
        <div className="estimate-details">
          <div>
            <span>Detected structure</span>
            <strong>
              Tables {demoEstimate.tables} · formulas {demoEstimate.formulas} ·
              figures {demoEstimate.figures}
            </strong>
          </div>
          <div>
            <span>Estimated time</span>
            <strong>
              {demoEstimate.expected_duration_min}–
              {demoEstimate.expected_duration_max} min
            </strong>
          </div>
          <div>
            <span>External model APIs</span>
            <strong className="safe-value">
              <LockKey size={14} weight="fill" aria-hidden="true" />
              Not used
            </strong>
          </div>
        </div>
        <div className="estimate-credit">
          <div>
            <span>Estimated credits</span>
            <strong>
              {demoEstimate.credit_min}–{demoEstimate.credit_max}
            </strong>
          </div>
          <p>
            Reserve up to <strong>{demoEstimate.credit_max} credits</strong>.
            Unused credits are returned immediately.
          </p>
        </div>
        <label className="consent-check">
          <input ref={consentRef} type="checkbox" defaultChecked />
          <span>
            I reviewed the {demoEstimate.credit_max}-credit maximum reservation
            and automatic return policy for failed pages.
          </span>
        </label>
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onCancel}>
            Change options
          </button>
          <button type="button" className="primary-button" onClick={onConfirm}>
            <Check size={16} weight="bold" aria-hidden="true" />
            Start processing
          </button>
        </div>
      </section>
    </div>
  );
}
