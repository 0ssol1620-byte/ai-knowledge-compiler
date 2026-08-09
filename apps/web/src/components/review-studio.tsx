"use client";

import {
  ArrowClockwise,
  Check,
  CheckCircle,
  FileMagnifyingGlass,
  Prohibit,
  StackSimple,
  Warning,
} from "@phosphor-icons/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import { apiRequest } from "@/lib/api-client";
import { demoReviews } from "@/lib/demo-data";
import type { StructaraLocale } from "@/lib/locale";
import {
  publicCandidateLabel,
  publicOriginLabel,
} from "@/lib/public-processing-labels";
import type {
  PageSummary,
  ReviewItem,
  ReviewResolution,
  ReviewScopePreview,
} from "@/lib/types";

type ReviewJobSnapshot = {
  document: { id: string; title: string; filename: string };
  pages: PageSummary[];
  reviews: ReviewItem[];
};

type AuditEntry = {
  id: string;
  reviewId: string;
  action: string;
  at: string;
};

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

const REVIEW_COPY = {
  en: {
    loading: "Loading the integrity ledger…",
    title: "Legacy integrity decisions",
    loadError: "The integrity ledger could not be loaded",
    retry: "Retry",
    breadcrumbReview: "Integrity",
    sample: "Interactive sample",
    connected: "Connected integrity ledger",
    openSuffix: "open",
    completion: "Completion summary",
    auditUnavailable:
      "Audit export is unavailable in the deterministic demo workspace.",
    exportAudit: "Export audit",
    summaryLabel: "Integrity finding summary",
    open: "Open",
    resolved: "Resolved",
    critical: "Critical",
    highRisk: "High risk",
    auditEvents: "Audit events",
    completeTitle: "No unresolved findings remain",
    completeBody:
      "The current document version has no unresolved integrity findings.",
    returnProcessing: "Return to processing",
    queueLabel: "Risk-ordered integrity findings",
    queue: "Integrity findings",
    queueNote: "Ordered by severity and source impact",
    source: "Source",
    page: "Page",
    evidenceBlock: "Evidence block",
    openEvidence: "Open source evidence",
    block: "Block",
    origin: "Origin",
    revision: "Revision",
    evidenceLinks: "Evidence links",
    exactContext: "Exact source context · no synthetic confidence score",
    decisionRequired: "Optional evidence decision",
    currentResult: "CURRENT RESULT",
    reviewRequired: "Unresolved",
    candidateComparison: "candidate comparison",
    candidateNote: "Use this value and preserve an audit event",
    manual: "Manual replacement",
    reprocess: "Reprocess",
    ignoreReason: "Ignore with reason",
    accept: "Accept replacement",
    rule: "Document-wide rule",
    ruleNote: "Preview the exact matching scope before applying.",
    preview: "Preview scope",
    matches: "matching item(s)",
    scope: "scope",
    adopt: "Adopt sources",
    ignoreApprove: "Ignore & approve",
    approveAll: "Approve all",
    saving: "Saving the audited decision…",
    latestAudit: "LATEST AUDIT EVENT",
    selectedCandidate: "Selected candidate",
    ignoredAudit: "Ignored with an explicit audit reason",
    manualAccepted: "Optional replacement recorded in the legacy integrity ledger",
  },
  ko: {
    loading: "무결성 원장을 불러오는 중…",
    title: "레거시 무결성 결정",
    loadError: "무결성 원장을 불러올 수 없습니다",
    retry: "다시 시도",
    breadcrumbReview: "무결성",
    sample: "인터랙티브 샘플",
    connected: "연결된 무결성 원장",
    openSuffix: "개 미해결",
    completion: "완료 요약",
    auditUnavailable:
      "결정적 데모 워크스페이스에서는 감사 내보내기를 사용할 수 없습니다.",
    exportAudit: "감사 내보내기",
    summaryLabel: "무결성 항목 요약",
    open: "미해결",
    resolved: "해결됨",
    critical: "Critical",
    highRisk: "High 위험",
    auditEvents: "감사 이벤트",
    completeTitle: "남은 미해결 항목이 없습니다",
    completeBody: "현재 문서 버전에는 해결되지 않은 무결성 항목이 없습니다.",
    returnProcessing: "처리 화면으로 돌아가기",
    queueLabel: "위험도 순 무결성 항목",
    queue: "무결성 항목",
    queueNote: "심각도와 원본 영향 순으로 정렬",
    source: "원본",
    page: "페이지",
    evidenceBlock: "근거 블록",
    openEvidence: "원본 근거 열기",
    block: "블록",
    origin: "출처",
    revision: "리비전",
    evidenceLinks: "근거 링크",
    exactContext: "정확한 원본 맥락 · 합성 confidence 점수 없음",
    decisionRequired: "선택적 근거 결정",
    currentResult: "현재 결과",
    reviewRequired: "미해결",
    candidateComparison: "후보 비교",
    candidateNote: "이 값을 사용하고 감사 이벤트를 보존합니다",
    manual: "직접 교체",
    reprocess: "재처리",
    ignoreReason: "사유와 함께 무시",
    accept: "교체값 승인",
    rule: "문서 전체 규칙",
    ruleNote: "적용 전에 정확한 일치 범위를 미리 확인합니다.",
    preview: "범위 미리보기",
    matches: "개 일치 항목",
    scope: "범위",
    adopt: "원본 채택",
    ignoreApprove: "무시 후 승인",
    approveAll: "모두 승인",
    saving: "감사 결정 저장 중…",
    latestAudit: "최근 감사 이벤트",
    selectedCandidate: "후보 선택",
    ignoredAudit: "명시적 감사 사유와 함께 무시",
    manualAccepted: "레거시 무결성 원장에 선택적 교체값 기록",
  },
} as const;

export function ReviewStudio({
  documentId = "sample-dart",
  jobId,
  locale = "en",
}: {
  documentId?: string;
  jobId?: string | null;
  locale?: StructaraLocale;
}) {
  const copy = REVIEW_COPY[locale];
  const queryClient = useQueryClient();
  const [demoItems, setDemoItems] = useState<ReviewItem[]>(() =>
    demoReviews.map((item) => ({ ...item })),
  );
  const [selectedId, setSelectedId] = useState<string>(
    demoReviews[0]?.id ?? "",
  );
  const [manualValue, setManualValue] = useState(
    demoReviews[0]?.candidates?.[0]?.value ?? "",
  );
  const [pendingId, setPendingId] = useState<string>();
  const [error, setError] = useState<string>();
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [scopePreview, setScopePreview] = useState<ReviewScopePreview>();
  const [audit, setAudit] = useState<AuditEntry[]>([]);

  const snapshot = useQuery({
    queryKey: ["review-studio", jobId],
    queryFn: () => apiRequest<ReviewJobSnapshot>(`/v1/jobs/${jobId}/snapshot`),
    enabled: !DEMO_MODE && Boolean(jobId),
  });

  const items = useMemo(
    () => (DEMO_MODE ? demoItems : (snapshot.data?.reviews ?? [])),
    [demoItems, snapshot.data?.reviews],
  );
  const selected = items.find((item) => item.id === selectedId) ?? items[0];
  const openItems = items.filter((item) => item.status === "open");
  const resolvedItems = items.length - openItems.length;

  function selectItem(item: ReviewItem) {
    setSelectedId(item.id);
    setManualValue(item.candidates?.[0]?.value ?? "");
    setScopePreview(undefined);
    setError(undefined);
  }

  const selectedPage = snapshot.data?.pages.find(
    (page) => page.id === selected?.page_id,
  );
  const selectedBlock = selectedPage?.blocks.find(
    (block) => block.id === selected?.block_id,
  );
  const sourceValue =
    selectedBlock?.source_text ||
    selected?.candidates?.[0]?.value ||
    "Source evidence is available from the linked page and block.";
  const documentTitle = DEMO_MODE
    ? "Canonical public-filing fixture"
    : snapshot.data?.document.title ||
      snapshot.data?.document.filename ||
      "Document integrity";

  const severityCounts = useMemo(
    () =>
      items.reduce<Record<ReviewItem["severity"], number>>(
        (counts, item) => {
          if (item.status === "open") counts[item.severity] += 1;
          return counts;
        },
        { low: 0, medium: 0, high: 0, critical: 0 },
      ),
    [items],
  );

  async function resolve(item: ReviewItem, resolution: ReviewResolution) {
    setPendingId(item.id);
    setError(undefined);
    try {
      if (DEMO_MODE) {
        setDemoItems((current) =>
          current.map((candidate) =>
            candidate.id === item.id
              ? { ...candidate, status: "resolved" }
              : candidate,
          ),
        );
      } else {
        await apiRequest(`/v1/review-items/${item.id}/resolve`, {
          method: "POST",
          idempotencyKey: crypto.randomUUID(),
          body: JSON.stringify({
            action: resolution.action,
            value: resolution.value ?? null,
            note: resolution.note ?? null,
          }),
        });
        await snapshot.refetch();
        await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      }
      setAudit((current) => [
        {
          id: crypto.randomUUID(),
          reviewId: item.id,
          action: resolution.note || resolution.action,
          at: new Date().toISOString(),
        },
        ...current,
      ]);
      const nextItem = openItems.find((candidate) => candidate.id !== item.id);
      if (nextItem) selectItem(nextItem);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The integrity decision could not be saved.",
      );
    } finally {
      setPendingId(undefined);
    }
  }

  async function reprocess(item: ReviewItem) {
    if (!item.page_id) {
      setError("No page evidence is available for reprocessing.");
      return;
    }
    setPendingId(item.id);
    setError(undefined);
    try {
      if (DEMO_MODE) {
        await new Promise((resolveDelay) =>
          window.setTimeout(resolveDelay, 180),
        );
        setAudit((current) => [
          {
            id: crypto.randomUUID(),
            reviewId: item.id,
            action: "Reprocessing requested for the sample page",
            at: new Date().toISOString(),
          },
          ...current,
        ]);
      } else {
        await apiRequest(`/v1/pages/${item.page_id}/reprocess`, {
          method: "POST",
          idempotencyKey: crypto.randomUUID(),
        });
        await snapshot.refetch();
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Page reprocessing could not be requested.",
      );
    } finally {
      setPendingId(undefined);
    }
  }

  async function previewDocumentRule(item: ReviewItem) {
    setPendingId(item.id);
    setError(undefined);
    try {
      const preview = DEMO_MODE
        ? {
            document_id: documentId,
            category: item.category,
            item_count: items.filter(
              (candidate) =>
                candidate.status === "open" &&
                candidate.category === item.category,
            ).length,
            review_ids: items
              .filter(
                (candidate) =>
                  candidate.status === "open" &&
                  candidate.category === item.category,
              )
              .map((candidate) => candidate.id),
            preview_sha256: "demo-scope-7e81f14a6e2d",
            allowed_actions: ["accept", "adopt_source", "reject"] as const,
          }
        : await apiRequest<ReviewScopePreview>(
            `/v1/review-items/${item.id}/scope-preview`,
          );
      setScopePreview({
        ...preview,
        allowed_actions: [...preview.allowed_actions],
      });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The document-wide rule could not be previewed.",
      );
    } finally {
      setPendingId(undefined);
    }
  }

  async function applyDocumentRule(
    item: ReviewItem,
    action: "accept" | "adopt_source" | "reject",
  ) {
    if (!scopePreview) return;
    setPendingId(item.id);
    setError(undefined);
    try {
      if (DEMO_MODE) {
        const ids = new Set(scopePreview.review_ids);
        setDemoItems((current) =>
          current.map((candidate) =>
            ids.has(candidate.id)
              ? { ...candidate, status: "resolved" }
              : candidate,
          ),
        );
      } else {
        await apiRequest(`/v1/review-items/${item.id}/apply-rule`, {
          method: "POST",
          idempotencyKey: crypto.randomUUID(),
          body: JSON.stringify({
            action,
            preview_sha256: scopePreview.preview_sha256,
            note: "Document-wide rule applied from the legacy integrity ledger",
          }),
        });
        await snapshot.refetch();
      }
      setAudit((current) => [
        {
          id: crypto.randomUUID(),
          reviewId: item.id,
          action: `Document rule: ${action} (${scopePreview.item_count} items)`,
          at: new Date().toISOString(),
        },
        ...current,
      ]);
      setScopePreview(undefined);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The document-wide rule could not be applied.",
      );
    } finally {
      setPendingId(undefined);
    }
  }

  if (!DEMO_MODE && !jobId) {
    return (
      <div className="simple-page">
        <h1>Legacy integrity decisions</h1>
        <div className="honest-state panel">
          <FileMagnifyingGlass size={26} aria-hidden="true" />
          <div>
            <h2>Open a compiled job to inspect its integrity evidence</h2>
            <p>
              The dedicated studio requires a job snapshot so every decision can
              be persisted against an exact document version.
            </p>
            <Link
              className="primary-button compact"
              href={`/documents/${documentId}/processing?document=${documentId}`}
            >
              Open Processing Studio
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (snapshot.isPending && !DEMO_MODE) {
    return <div className="st-document-loading">{copy.loading}</div>;
  }

  if (snapshot.isError && !DEMO_MODE) {
    return (
      <div className="simple-page">
        <h1>{copy.title}</h1>
        <div className="honest-state panel">
          <Warning size={26} weight="fill" aria-hidden="true" />
          <div>
            <h2>{copy.loadError}</h2>
            <p>{snapshot.error.message}</p>
            <button
              type="button"
              className="primary-button compact"
              onClick={() => void snapshot.refetch()}
            >
              {copy.retry}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="review-studio-page"
      data-review-mode={DEMO_MODE ? "sample" : "live"}
      data-locale={locale}
    >
      <header className="review-studio-header">
        <div>
          <p>
            Projects / {documentTitle} / {copy.breadcrumbReview}
          </p>
          <h1>{copy.title}</h1>
        </div>
        <span className="demo-sample-chip">
          {DEMO_MODE ? copy.sample : copy.connected} · {openItems.length}{" "}
          {copy.openSuffix}
        </span>
        <button
          type="button"
          className="secondary-button compact"
          aria-expanded={summaryOpen}
          onClick={() => setSummaryOpen((current) => !current)}
        >
          <CheckCircle size={15} aria-hidden="true" />
          {copy.completion}
        </button>
        {DEMO_MODE && (
          <button
            type="button"
            className="secondary-button compact"
            data-sample-static-control
            disabled
            title={copy.auditUnavailable}
          >
            {copy.exportAudit}
          </button>
        )}
      </header>

      {summaryOpen && (
        <section
          className="review-completion-summary"
          aria-label={copy.summaryLabel}
        >
          <div>
            <span>{copy.open}</span>
            <strong>{openItems.length}</strong>
          </div>
          <div>
            <span>{copy.resolved}</span>
            <strong>{resolvedItems}</strong>
          </div>
          <div>
            <span>{copy.critical}</span>
            <strong>{severityCounts.critical}</strong>
          </div>
          <div>
            <span>{copy.highRisk}</span>
            <strong>{severityCounts.high}</strong>
          </div>
          <div>
            <span>{copy.auditEvents}</span>
            <strong>{audit.length}</strong>
          </div>
        </section>
      )}

      {items.length === 0 ? (
        <section className="review-complete-state">
          <CheckCircle size={34} weight="fill" aria-hidden="true" />
          <h2>{copy.completeTitle}</h2>
          <p>{copy.completeBody}</p>
          <Link
            className="primary-button compact"
            href={`/documents/${documentId}/processing${jobId ? `?job=${jobId}` : ""}`}
          >
            {copy.returnProcessing}
          </Link>
        </section>
      ) : (
        <div className="review-studio-layout">
          <aside className="issue-queue" aria-label={copy.queueLabel}>
            <header>
              <strong>{copy.queue}</strong>
              <small>{copy.queueNote}</small>
            </header>
            {items.map((item, index) => (
              <button
                type="button"
                className={selected?.id === item.id ? "active" : undefined}
                onClick={() => selectItem(item)}
                key={item.id}
              >
                <span data-severity={severityLabel(item.severity, locale)}>
                  {severityLabel(item.severity, locale)}
                </span>
                <strong>{categoryLabel(item.category, locale)}</strong>
                <small>{item.message}</small>
                <i>
                  {item.status === "resolved" ? <Check size={12} /> : index + 1}
                </i>
              </button>
            ))}
          </aside>

          <section className="review-source-pane">
            <header>
              <span>
                {copy.source} ·{" "}
                {selectedPage
                  ? `${copy.page} ${selectedPage.page_number}`
                  : copy.evidenceBlock}
              </span>
              <Link
                className="icon-button compact"
                href={`/documents/${documentId}/sources${jobId ? `?job=${jobId}` : ""}`}
                aria-label={copy.openEvidence}
              >
                <FileMagnifyingGlass size={16} />
              </Link>
            </header>
            <div className="review-paper">
              <span>
                {snapshot.data?.document.filename || "canonical-source.pdf"}
              </span>
              <h2>{categoryLabel(selected?.category || "review", locale)}</h2>
              <p>{selected?.message}</p>
              <blockquote>{sourceValue}</blockquote>
              {selectedBlock && (
                <dl className="review-source-metadata">
                  <div>
                    <dt>{copy.block}</dt>
                    <dd>{selectedBlock.id}</dd>
                  </div>
                  <div>
                    <dt>{copy.origin}</dt>
                    <dd>{selectedBlock.origin.replaceAll("_", " ")}</dd>
                  </div>
                  <div>
                    <dt>{copy.revision}</dt>
                    <dd>{selectedBlock.revision}</dd>
                  </div>
                  <div>
                    <dt>{copy.evidenceLinks}</dt>
                    <dd>{selectedBlock.source_refs.length}</dd>
                  </div>
                </dl>
              )}
              <i>
                <Warning size={12} weight="fill" />
                {copy.exactContext}
              </i>
            </div>
          </section>

          {selected && (
            <aside className="candidate-pane">
              <header>
                <div>
                  <span>{severityLabel(selected.severity, locale)}</span>
                  <strong>{categoryLabel(selected.category, locale)}</strong>
                </div>
                <small>
                  {selected.status === "resolved"
                    ? copy.resolved
                    : copy.decisionRequired}
                </small>
              </header>

              <section>
                <span>{copy.currentResult}</span>
                <strong>
                  {selected.candidates?.[1]?.value ||
                    selectedBlock?.markdown ||
                    copy.reviewRequired}
                </strong>
                <small>
                  {selectedBlock?.origin
                    ? publicOriginLabel(selectedBlock.origin, locale)
                    : copy.candidateComparison}
                </small>
              </section>

              {selected.candidates && selected.candidates.length > 0 && (
                <div className="candidate-choice-grid">
                  {selected.candidates.map((candidate) => {
                    const candidateLabel = publicCandidateLabel(
                      candidate.engine,
                      locale,
                    );
                    return (
                      <button
                        type="button"
                        key={candidate.engine}
                        disabled={
                          selected.status === "resolved" ||
                          pendingId === selected.id
                        }
                        onClick={() =>
                          void resolve(selected, {
                            action: "replace",
                            value: candidate.value,
                            note: `${copy.selectedCandidate}: ${candidateLabel}`,
                          })
                        }
                      >
                        <span>{candidateLabel}</span>
                        <strong>{candidate.value}</strong>
                        <small>{copy.candidateNote}</small>
                      </button>
                    );
                  })}
                </div>
              )}

              <label>
                <span>{copy.manual}</span>
                <input
                  value={manualValue}
                  disabled={
                    selected.status === "resolved" || pendingId === selected.id
                  }
                  onChange={(event) =>
                    setManualValue(event.currentTarget.value)
                  }
                />
              </label>

              <div className="candidate-actions">
                <button
                  className="secondary-button compact"
                  type="button"
                  disabled={
                    selected.status === "resolved" || pendingId === selected.id
                  }
                  onClick={() => void reprocess(selected)}
                >
                  <ArrowClockwise size={14} />
                  {copy.reprocess}
                </button>
                <button
                  className="secondary-button compact"
                  type="button"
                  disabled={
                    selected.status === "resolved" || pendingId === selected.id
                  }
                  onClick={() =>
                    void resolve(selected, {
                      action: "reject",
                      note: copy.ignoredAudit,
                    })
                  }
                >
                  <Prohibit size={14} />
                  {copy.ignoreReason}
                </button>
                <button
                  className="primary-button compact"
                  type="button"
                  disabled={
                    selected.status === "resolved" ||
                    pendingId === selected.id ||
                    manualValue.trim().length === 0
                  }
                  onClick={() =>
                    void resolve(selected, {
                      action: "replace",
                      value: manualValue,
                      note: copy.manualAccepted,
                    })
                  }
                >
                  <Check size={14} />
                  {copy.accept}
                </button>
              </div>

              <div className="review-rule-scope-inline">
                <div>
                  <StackSimple size={15} aria-hidden="true" />
                  <span>
                    <strong>{copy.rule}</strong>
                    <small>{copy.ruleNote}</small>
                  </span>
                </div>
                {!scopePreview ? (
                  <button
                    type="button"
                    className="secondary-button compact"
                    disabled={
                      selected.status === "resolved" ||
                      pendingId === selected.id
                    }
                    onClick={() => void previewDocumentRule(selected)}
                  >
                    {copy.preview}
                  </button>
                ) : (
                  <div className="review-rule-confirm-inline">
                    <p>
                      {scopePreview.item_count} {copy.matches} · {copy.scope}{" "}
                      {scopePreview.preview_sha256.slice(0, 12)}
                    </p>
                    <div>
                      <button
                        type="button"
                        onClick={() =>
                          void applyDocumentRule(selected, "adopt_source")
                        }
                      >
                        {copy.adopt}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          void applyDocumentRule(selected, "reject")
                        }
                      >
                        {copy.ignoreApprove}
                      </button>
                      <button
                        type="button"
                        className="primary-button compact"
                        onClick={() =>
                          void applyDocumentRule(selected, "accept")
                        }
                      >
                        {copy.approveAll}
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              {pendingId === selected.id && (
                <p className="review-shortcuts" role="status">
                  {copy.saving}
                </p>
              )}
              {audit[0] && (
                <div className="review-latest-audit">
                  <span>{copy.latestAudit}</span>
                  <strong>{audit[0].action}</strong>
                  <small>
                    {new Date(audit[0].at).toLocaleString(
                      locale === "ko" ? "ko-KR" : "en-US",
                    )}
                  </small>
                </div>
              )}
            </aside>
          )}
        </div>
      )}
    </div>
  );
}

function severityLabel(
  severity: ReviewItem["severity"],
  locale: StructaraLocale,
): string {
  return locale === "ko"
    ? {
        critical: "Critical",
        high: "High",
        medium: "미해결",
        low: "알림",
      }[severity]
    : {
        critical: "Critical",
        high: "High",
        medium: "Unresolved",
        low: "Notice",
      }[severity];
}

function categoryLabel(category: string, locale: StructaraLocale): string {
  return (
    (locale === "ko"
      ? {
          number_mismatch: "숫자 불일치",
          merged_cell: "표 구조",
          reading_order: "읽기 순서",
          missing_content: "누락 콘텐츠",
          visual_security: "시각 보안",
        }
      : {
          number_mismatch: "Numeric mismatch",
          merged_cell: "Table structure",
          reading_order: "Reading order",
          missing_content: "Missing content",
          visual_security: "Visual security",
        })[category] || category.replaceAll("_", " ")
  );
}
