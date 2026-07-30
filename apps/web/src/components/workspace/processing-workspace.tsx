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
            aria-label="프로젝트로 돌아가기"
          >
            <ArrowLeft size={18} />
          </Link>
          <div className="document-identity">
            <span className="document-icon" aria-hidden="true">
              <FileText size={20} weight="duotone" />
            </span>
            <div>
              <p>RAG 근거 충실도 연구</p>
              <h1>evidence-grounded-rag-evaluation.pdf</h1>
            </div>
          </div>
          <button className="mode-select" type="button">
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

      <section className="pipeline-bar" aria-label="처리 진행 상황">
        <div className="pipeline-summary">
          <div
            className="overall-progress-ring"
            style={{ "--progress": "68%" } as CSSProperties}
          >
            <strong>68%</strong>
          </div>
          <div>
            <strong>
              {processingStarted ? "지식 컴파일 진행 중" : "처리 전 견적 확인"}
            </strong>
            <span>
              {processingStarted
                ? "16 / 18 pages usable"
                : "승인 전에는 크레딧을 사용하지 않습니다."}
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

      <nav className="mobile-workspace-tabs" aria-label="모바일 처리 작업 보기">
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
          aria-label="처리 진행 상세"
        >
          <div className="mobile-progress-overview">
            <div
              className="overall-progress-ring"
              style={{ "--progress": "68%" } as CSSProperties}
              aria-label="전체 진행률 68%"
            >
              <strong>68%</strong>
            </div>
            <div>
              <span className="mobile-progress-label">현재 단계</span>
              <strong>지식 구조 생성</strong>
              <span>18페이지 중 16페이지 사용 가능</span>
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
                  aria-label={stage.done ? "완료" : `진행률 ${stage.progress}%`}
                >
                  {stage.done ? "Done" : `${stage.progress}%`}
                </b>
              </li>
            ))}
          </ol>
          <div className="mobile-credit-summary" aria-label="크레딧 사용 요약">
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
          aria-label="검토 창 닫기"
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
            <h2 id="estimate-title">처리 전 견적을 확인하세요</h2>
            <p>
              문서 구조를 빠르게 분석한 범위이며 실제 경로에 따라 차액을
              반환합니다.
            </p>
          </div>
        </div>
        <div className="estimate-page-grid">
          <article>
            <small>전체</small>
            <strong>{demoEstimate.total_pages}</strong>
            <span>pages</span>
          </article>
          <article>
            <small>Native text</small>
            <strong>{demoEstimate.native_pages}</strong>
            <span>낮은 비용 경로</span>
          </article>
          <article>
            <small>Visual parsing</small>
            <strong>{demoEstimate.visual_pages}</strong>
            <span>OCR·layout</span>
          </article>
          <article>
            <small>Precision 후보</small>
            <strong>{demoEstimate.precision_candidate_pages}</strong>
            <span>선택적 교차 검증</span>
          </article>
        </div>
        <div className="estimate-details">
          <div>
            <span>검출된 구조</span>
            <strong>
              표 {demoEstimate.tables} · 수식 {demoEstimate.formulas} · 그림{" "}
              {demoEstimate.figures}
            </strong>
          </div>
          <div>
            <span>예상 시간</span>
            <strong>
              {demoEstimate.expected_duration_min}–
              {demoEstimate.expected_duration_max}분
            </strong>
          </div>
          <div>
            <span>외부 모델 API</span>
            <strong className="safe-value">
              <LockKey size={14} weight="fill" aria-hidden="true" />
              사용 안 함
            </strong>
          </div>
        </div>
        <div className="estimate-credit">
          <div>
            <span>예상 크레딧</span>
            <strong>
              {demoEstimate.credit_min}–{demoEstimate.credit_max}
            </strong>
          </div>
          <p>
            최대 <strong>{demoEstimate.credit_max} credits</strong>를 예약하고,
            사용하지 않은 금액은 자동으로 즉시 반환합니다.
          </p>
        </div>
        <label className="consent-check">
          <input ref={consentRef} type="checkbox" defaultChecked />
          <span>
            최대 {demoEstimate.credit_max} credits 예약과 실패 페이지 자동 환불
            정책을 확인했습니다.
          </span>
        </label>
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onCancel}>
            옵션 수정
          </button>
          <button type="button" className="primary-button" onClick={onConfirm}>
            <Check size={16} weight="bold" aria-hidden="true" />
            처리 시작
          </button>
        </div>
      </section>
    </div>
  );
}
