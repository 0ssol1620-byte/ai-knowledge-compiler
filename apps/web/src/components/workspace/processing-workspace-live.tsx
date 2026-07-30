"use client";

import {
  ArrowLeft,
  Check,
  CheckCircle,
  Clock,
  DownloadSimple,
  FileText,
  Gauge,
  ShieldCheck,
  Warning,
  WifiHigh,
  WifiSlash,
} from "@phosphor-icons/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useEffect,
  useCallback,
  useReducer,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import {
  ExportDialog,
  type VaultMergePreview,
} from "@/components/workspace/export-dialog";
import { MarkdownWorkspace } from "@/components/workspace/markdown-workspace";
import { ModelMergeDialog } from "@/components/workspace/model-merge-dialog";
import { PageRail } from "@/components/workspace/page-rail";
import { ReviewDrawer } from "@/components/workspace/review-drawer";
import { SourceViewer } from "@/components/workspace/source-viewer";
import {
  apiRequest,
  recordProductAnalyticsEvent,
  streamJob,
} from "@/lib/api-client";
import {
  initialLiveJobState,
  reduceJobEvent,
  weightedOverallProgress,
} from "@/lib/event-reducer";
import {
  displayDocumentMetadata,
  normalizedDocumentVersion,
} from "@/lib/document-metadata";
import type {
  BlockModelMergeResponse,
  CanonicalBlock,
  CanonicalBlockPatch,
  JobEvent,
  PageSummary,
  PreflightEstimate,
  ReviewItem,
  ReviewScopePreview,
  SourceRef,
} from "@/lib/types";
import { useThrottledAnnouncement } from "@/lib/use-throttled-announcement";
import { useSseSilenceFallback } from "@/lib/use-sse-silence-fallback";

const stageLabels = [
  ["upload", "Upload"],
  ["security_scan", "Security"],
  ["preflight", "Preflight"],
  ["extract", "Extract"],
  ["normalize", "Structure"],
  ["knowledge", "Knowledge"],
  ["validate", "Validate"],
  ["package", "Package"],
] as const;

type MobileTab = "progress" | "pages" | "source" | "result" | "review";

interface JobSnapshot {
  last_sequence?: number;
  document_version?: number;
  job: {
    id: string;
    status:
      "created" | "queued" | "running" | "completed" | "failed" | "cancelled";
    route_profile: string;
    progress: number;
    credits: {
      estimated: number;
      used: number;
      reserved: number;
      maximum: number;
    };
  };
  document: {
    id: string;
    title: string;
    filename: string;
    version?: number;
    file_type?: string | null;
    semantic_classification?: {
      semantic_type: string;
      languages: string[];
      topics: string[];
      domains: string[];
      evidence_block_ids: string[];
      confidence: number;
    } | null;
  };
  stage_progress: Record<string, { done: number; total: number }>;
  pages: PageSummary[];
  reviews: ReviewItem[];
  summary: {
    completed_pages: number;
    native_pages: number;
    ocr_pages: number;
    tables_rebuilt: number;
    knowledge_notes: number;
    third_party_pages: number;
    elapsed_seconds: number;
    blocks: number;
    route_totals: Record<string, number>;
    block_type_totals: Record<string, number>;
    removed_header_footer: {
      header: number;
      footer: number;
    };
    review_blocks: number;
    gpu_seconds: number | null;
    queue_position: number | null;
  };
}

export function ProcessingWorkspaceLive() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const documentId = searchParams.get("document");

  if (jobId) return <LiveJobView key={jobId} jobId={jobId} />;
  if (documentId)
    return <EstimateView key={documentId} documentId={documentId} />;

  return (
    <div className="processing-empty">
      <FileText size={30} weight="duotone" aria-hidden="true" />
      <h1>선택한 처리 작업이 없습니다.</h1>
      <p>프로젝트에서 문서를 선택하거나 새 자료를 업로드하세요.</p>
      <Link href="/" className="primary-button">
        프로젝트로 돌아가기
      </Link>
    </div>
  );
}

function EstimateView({ documentId }: { documentId: string }) {
  const router = useRouter();
  const analyticsRecorded = useRef(false);
  const [consented, setConsented] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string>();
  const estimate = useQuery({
    queryKey: ["document-estimate", documentId],
    queryFn: () =>
      apiRequest<PreflightEstimate>(`/v1/documents/${documentId}/estimate`),
  });

  useEffect(() => {
    if (!estimate.data || analyticsRecorded.current) return;
    analyticsRecorded.current = true;
    void recordProductAnalyticsEvent({
      event_type: "estimate_viewed",
      document_id: documentId,
    }).catch(() => {
      // Optional analytics must never block the processing workflow.
    });
  }, [documentId, estimate.data]);

  if (estimate.isPending) {
    return (
      <WorkspaceState
        busy
        message="보안 검사와 preflight 견적을 확인하고 있습니다."
      />
    );
  }
  if (estimate.isError) {
    return (
      <WorkspaceState
        message={`견적을 불러오지 못했습니다: ${estimate.error.message}`}
        retry={() => {
          void estimate.refetch();
        }}
      />
    );
  }

  const value = estimate.data;
  return (
    <div className="estimate-page-live">
      <section
        className="modal-card estimate-modal"
        aria-labelledby="estimate-live-title"
      >
        <div className="estimate-heading">
          <span className="estimate-icon">
            <Gauge size={22} weight="duotone" aria-hidden="true" />
          </span>
          <div>
            <p className="eyebrow">Preflight complete</p>
            <h1 id="estimate-live-title">처리 전 견적을 확인하세요</h1>
            <p>
              실제 보안 검사와 preflight 결과이며 승인 전에는 크레딧을 사용하지
              않습니다.
            </p>
          </div>
        </div>
        <EstimateFacts estimate={value} />
        <label className="consent-check">
          <input
            type="checkbox"
            checked={consented}
            onChange={(event) => setConsented(event.currentTarget.checked)}
          />
          <span>
            최대 {value.credit_max} credits 예약과 실패 페이지 자동 반환 정책을
            확인했습니다.
          </span>
        </label>
        {startError && (
          <p className="form-error" role="alert">
            {startError}
          </p>
        )}
        <div className="modal-actions">
          <Link href="/" className="secondary-button">
            취소
          </Link>
          <button
            type="button"
            className="primary-button"
            disabled={!consented || starting}
            onClick={() => {
              setStarting(true);
              setStartError(undefined);
              void apiRequest<{ job_id: string }>(
                `/v1/documents/${documentId}/compile`,
                {
                  method: "POST",
                  idempotencyKey: crypto.randomUUID(),
                  body: JSON.stringify({
                    route_profile: "parse_balanced_v1",
                    max_credits: value.credit_max,
                    external_processing_consent: false,
                  }),
                },
              )
                .then((result) =>
                  router.replace(`/workspace?job=${result.job_id}`),
                )
                .catch((reason: unknown) => {
                  setStartError(
                    reason instanceof Error
                      ? reason.message
                      : "처리 작업을 시작하지 못했습니다.",
                  );
                })
                .finally(() => setStarting(false));
            }}
          >
            <Check size={16} weight="bold" aria-hidden="true" />
            {starting ? "예약·시작 중" : "처리 시작"}
          </button>
        </div>
      </section>
    </div>
  );
}

function EstimateFacts({ estimate }: { estimate: PreflightEstimate }) {
  return (
    <>
      <div className="estimate-page-grid">
        <EstimateFact
          label="전체"
          value={estimate.total_pages}
          detail="pages"
        />
        <EstimateFact
          label="Native text"
          value={estimate.native_pages}
          detail="낮은 비용 경로"
        />
        <EstimateFact
          label="Visual parsing"
          value={estimate.visual_pages}
          detail="OCR·layout"
        />
        <EstimateFact
          label="Precision 후보"
          value={estimate.precision_candidate_pages}
          detail="선택적 교차 검증"
        />
      </div>
      <div className="estimate-details">
        <div>
          <span>검출된 구조</span>
          <strong>
            표 {estimate.tables} · 수식 {estimate.formulas} · 그림{" "}
            {estimate.figures}
          </strong>
        </div>
        <div>
          <span>예상 시간</span>
          <strong>
            {estimate.expected_duration_min}–{estimate.expected_duration_max}분
          </strong>
        </div>
        <div>
          <span>외부 모델 API</span>
          <strong
            className={
              estimate.third_party_model_api ? "warning-value" : "safe-value"
            }
          >
            {estimate.third_party_model_api ? "동의 필요" : "사용 안 함"}
          </strong>
        </div>
      </div>
      <div className="estimate-credit">
        <div>
          <span>예상 크레딧</span>
          <strong>
            {estimate.credit_min}–{estimate.credit_max}
          </strong>
        </div>
        <p>사용하지 않은 예약분은 원장 트랜잭션으로 반환됩니다.</p>
      </div>
    </>
  );
}

function EstimateFact({
  label,
  value,
  detail,
}: {
  label: string;
  value: number;
  detail: string;
}) {
  return (
    <article>
      <small>{label}</small>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  );
}

function LiveJobView({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient();
  const [eventState, dispatch] = useReducer(
    reduceJobEvent,
    initialLiveJobState,
  );
  const lastEventId = useRef<string | undefined>(undefined);
  const replayInFlight = useRef(false);
  const resultViewRecorded = useRef(false);
  const [connection, setConnection] = useState<
    "connecting" | "live" | "reconnecting" | "closed"
  >("connecting");
  const [selectedPageId, setSelectedPageId] = useState<string>();
  const [selectedBlockId, setSelectedBlockId] = useState<string>();
  const [modelMergeBlockId, setModelMergeBlockId] = useState<string>();
  const [highlightedEvidence, setHighlightedEvidence] = useState<{
    blockId: string;
    source: SourceRef;
  }>();
  const [reviewOpen, setReviewOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>("progress");

  const snapshot = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => apiRequest<JobSnapshot>(`/v1/jobs/${jobId}`),
  });
  const status = snapshot.data?.job.status;
  const snapshotIsTerminal =
    status === "completed" || status === "failed" || status === "cancelled";
  const refetchAfterSseSilence = useCallback(() => {
    void queryClient.refetchQueries({
      queryKey: ["job", jobId],
      exact: true,
      type: "active",
    });
  }, [jobId, queryClient]);
  const markSseActivity = useSseSilenceFallback({
    active: !snapshotIsTerminal && eventState.terminalStatus === undefined,
    onSilence: refetchAfterSseSilence,
  });

  useEffect(() => {
    if (
      snapshot.data?.job.status !== "completed" ||
      resultViewRecorded.current
    ) {
      return;
    }
    resultViewRecorded.current = true;
    void recordProductAnalyticsEvent({
      event_type: "result_first_viewed",
      job_id: jobId,
    }).catch(() => {
      // Optional analytics must never block result rendering.
    });
  }, [jobId, snapshot.data?.job.status]);

  useEffect(() => {
    const controller = new AbortController();
    void streamJob(
      {
        jobId,
        lastEventId: lastEventId.current,
        signal: controller.signal,
      },
      {
        onActivity: markSseActivity,
        onEvent(event) {
          lastEventId.current = event.event_id;
          dispatch(event);
          if (
            event.event_type === "job.completed.v1" ||
            event.event_type === "job.failed.v1" ||
            event.event_type === "page.needs_review.v1"
          ) {
            void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
          }
        },
        onConnection: setConnection,
        onReset() {
          void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
        },
      },
    )
      .then(() => {
        if (!controller.signal.aborted) setConnection("closed");
      })
      .catch(() => {
        if (!controller.signal.aborted) setConnection("reconnecting");
      });
    return () => controller.abort();
  }, [jobId, markSseActivity, queryClient]);

  useEffect(() => {
    if (
      !eventState.needsReplay ||
      eventState.gapFrom === undefined ||
      replayInFlight.current
    ) {
      return;
    }
    const controller = new AbortController();
    replayInFlight.current = true;
    void apiRequest<JobEvent[]>(
      `/v1/jobs/${jobId}/events/replay?after_sequence=${eventState.lastSequence}`,
      { signal: controller.signal },
    )
      .then((events) => {
        for (const event of events.sort(
          (left, right) => left.sequence - right.sequence,
        )) {
          dispatch(event);
        }
        if (events.length === 0) {
          void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
          dispatch({
            kind: "snapshot.reset",
            lastSequence:
              snapshot.data?.last_sequence ?? eventState.lastSequence,
          });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
        }
      })
      .finally(() => {
        replayInFlight.current = false;
      });
    return () => controller.abort();
  }, [
    eventState.gapFrom,
    eventState.lastSequence,
    eventState.needsReplay,
    jobId,
    queryClient,
    snapshot.data?.last_sequence,
  ]);

  if (snapshot.isPending) {
    return (
      <WorkspaceState
        busy
        message="저장된 작업 snapshot을 불러오고 있습니다."
      />
    );
  }
  if (snapshot.isError) {
    return (
      <WorkspaceState
        message={`처리 작업을 불러오지 못했습니다: ${snapshot.error.message}`}
        retry={() => {
          void snapshot.refetch();
        }}
      />
    );
  }

  const data = snapshot.data;
  const pages = data.pages.map((page) => {
    const patchedBlocks = page.blocks.map((block) => {
      const patch = eventState.blockPatches[block.id];
      return patch ? { ...block, ...patch } : block;
    });
    const appended = Object.values(eventState.blockPatches)
      .filter(isCanonicalBlock)
      .filter(
        (block) =>
          !patchedBlocks.some((existing) => existing.id === block.id) &&
          block.source_refs.some(
            (source) => source.page_number === page.page_number,
          ),
      );
    return {
      ...page,
      status: eventState.pageStatus[page.id] ?? page.status,
      blocks: [...patchedBlocks, ...appended],
    };
  });
  const effectivePageId = selectedPageId ?? pages[0]?.id;
  const selectedPage = pages.find((page) => page.id === effectivePageId);
  const modelMergeBlock = modelMergeBlockId
    ? pages
        .flatMap((page) => page.blocks)
        .find((block) => block.id === modelMergeBlockId)
    : undefined;
  const progress = { ...data.stage_progress, ...eventState.stageProgress };
  const overallProgress =
    Object.keys(progress).length > 0
      ? weightedOverallProgress(progress)
      : Math.round(data.job.progress * 100);
  const terminal =
    data.job.status === "completed" ||
    data.job.status === "failed" ||
    data.job.status === "cancelled";
  const documentMetadata = displayDocumentMetadata(
    data.document.file_type,
    data.document.semantic_classification?.semantic_type,
  );
  const documentVersion = normalizedDocumentVersion(
    data.document_version,
    data.document.version,
  );

  function selectEvidence(item: ReviewItem) {
    if (item.page_id) setSelectedPageId(item.page_id);
    if (item.block_id) setSelectedBlockId(item.block_id);
    setMobileTab("source");
  }

  function interactWithEvidence(
    blockId: string,
    source: SourceRef,
    action: "focus" | "blur" | "select" | "pin",
  ) {
    if (action === "blur") {
      setHighlightedEvidence((current) =>
        current?.blockId === blockId &&
        current.source.document_version_id === source.document_version_id &&
        current.source.page_number === source.page_number &&
        current.source.bbox1000?.join(",") === source.bbox1000?.join(",")
          ? undefined
          : current,
      );
      return;
    }
    setHighlightedEvidence({ blockId, source });
    if (action === "select" || action === "pin") {
      const sourcePage = pages.find(
        (page) => page.page_number === source.page_number,
      );
      if (sourcePage) setSelectedPageId(sourcePage.id);
      setSelectedBlockId(blockId);
      setMobileTab(action === "select" ? "source" : "result");
    }
  }

  return (
    <div className="processing-page">
      <ProgressAnnouncement
        message={`${jobStatusLabel(data.job.status)}. ${
          data.summary.completed_pages
        } / ${pages.length} pages completed. ${
          terminal ? overallProgress : Math.floor(overallProgress / 5) * 5
        } percent.`}
      />
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
              <p>{data.document.title}</p>
              <h1>{data.document.filename}</h1>
              <div
                className="document-classification-row"
                role="group"
                aria-label="Document version, source, and semantic metadata"
              >
                {documentVersion !== undefined && (
                  <span
                    className="document-metadata-badge"
                    data-kind="version"
                    aria-label={`Document version ${documentVersion}`}
                  >
                    v{documentVersion}
                  </span>
                )}
                <span className="document-metadata-badge">
                  File type: {documentMetadata.fileType}
                </span>
                <span
                  className="document-metadata-badge"
                  data-state={
                    documentMetadata.semanticClassificationAvailable
                      ? "classified"
                      : "pending"
                  }
                >
                  Semantic type: {documentMetadata.semanticType}
                </span>
              </div>
            </div>
          </div>
          <span className="mode-select">
            <Gauge size={15} weight="fill" aria-hidden="true" />
            {data.job.route_profile}
          </span>
          <span
            className={clsx(
              "live-badge",
              connection !== "live" && "reconnecting",
            )}
            aria-label={`실시간 연결: ${connection}`}
          >
            {connection === "live" ? (
              <WifiHigh size={14} weight="fill" aria-hidden="true" />
            ) : (
              <WifiSlash size={14} aria-hidden="true" />
            )}
            {connection === "live" ? "Live" : connection}
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
            <span>
              {data.reviews.filter((item) => item.status === "open").length}
            </span>
          </button>
          <button
            className="primary-button compact"
            type="button"
            disabled={!terminal || data.job.status !== "completed"}
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
            style={{ "--progress": `${overallProgress}%` } as CSSProperties}
          >
            <strong>{overallProgress}%</strong>
          </div>
          <div>
            <strong>{jobStatusLabel(data.job.status)}</strong>
            <span>
              {data.summary.completed_pages} / {pages.length} pages completed
            </span>
          </div>
        </div>
        <div className="stage-track">
          {stageLabels.map(([id, label], index) => {
            const value = progress[id];
            const fraction =
              value && value.total > 0 ? value.done / value.total : 0;
            return (
              <div
                className={clsx(
                  "stage-item",
                  fraction >= 1 && "done",
                  fraction > 0 && fraction < 1 && "active",
                )}
                key={id}
              >
                <span className="stage-node">
                  {fraction >= 1 ? (
                    <Check size={12} weight="bold" />
                  ) : (
                    index + 1
                  )}
                </span>
                <span>{label}</span>
                {index < stageLabels.length - 1 && (
                  <i>
                    <b style={{ width: `${Math.min(1, fraction) * 100}%` }} />
                  </i>
                )}
              </div>
            );
          })}
        </div>
        <div className="cost-meter">
          <Credit label="Estimated" value={data.job.credits.estimated} />
          <Credit label="Used" value={data.job.credits.used} />
          <Credit label="Reserved" value={data.job.credits.reserved} />
          <Credit label="Maximum" value={data.job.credits.maximum} />
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
            ["review", `Review ${data.reviews.length}`],
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

      {selectedPage ? (
        <div className="processing-grid">
          <div
            className={clsx(
              "mobile-panel",
              mobileTab !== "pages" && "mobile-hidden",
            )}
          >
            <PageRail
              pages={pages}
              selectedPageId={selectedPage.id}
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
              selectedBlockId={selectedBlockId}
              highlightedEvidence={highlightedEvidence}
              onSelectBlock={(blockId) => {
                setSelectedBlockId(blockId);
                setMobileTab("result");
              }}
              onEvidenceInteraction={(blockId, source, action) =>
                interactWithEvidence(blockId, source, action)
              }
            />
          </div>
          <div
            className={clsx(
              "mobile-panel",
              mobileTab !== "result" && "mobile-hidden",
            )}
          >
            <MarkdownWorkspace
              blocks={selectedPage.blocks}
              selectedBlockId={selectedBlockId}
              onSelectBlock={setSelectedBlockId}
              qualityEvidence={selectedPage.attempt?.quality}
              onCompareModel={(block) => setModelMergeBlockId(block.id)}
              onEvidenceInteraction={(block, source, action) =>
                interactWithEvidence(block.id, source, action)
              }
              onSave={(block, markdown) =>
                apiRequest(`/v1/blocks/${block.id}`, {
                  method: "PATCH",
                  idempotencyKey: crypto.randomUUID(),
                  headers: {
                    "If-Match": `"revision-${block.revision}"`,
                  },
                  body: JSON.stringify({ markdown, user_locked: true }),
                }).then(() => {
                  void queryClient.invalidateQueries({
                    queryKey: ["job", jobId],
                  });
                })
              }
            />
          </div>
        </div>
      ) : (
        <div className="honest-state">
          <p>페이지 snapshot이 아직 생성되지 않았습니다.</p>
        </div>
      )}

      <footer className="processing-footer">
        <div className="processing-footer-primary">
          <span>
            <CheckCircle size={14} weight="fill" aria-hidden="true" />
            {data.summary.completed_pages} pages completed
          </span>
          <span>{data.summary.native_pages} Native</span>
          <span>{data.summary.ocr_pages} OCR</span>
          <span>{data.summary.tables_rebuilt} tables rebuilt</span>
          <span>{data.summary.knowledge_notes} knowledge notes</span>
        </div>
        <div>
          <span>
            <ShieldCheck size={14} weight="fill" aria-hidden="true" />
            Third-party model API: {data.summary.third_party_pages} pages
          </span>
          <span>
            <Clock size={14} aria-hidden="true" />
            {formatElapsed(data.summary.elapsed_seconds)}
          </span>
        </div>
        <div
          className="operational-counters"
          aria-label="Measured processing counters"
        >
          <OperationalMetric
            label="Routes"
            value={formatCounterMap(data.summary.route_totals)}
          />
          <OperationalMetric
            label="Blocks"
            value={formatCounterMap(data.summary.block_type_totals)}
          />
          <OperationalMetric
            label="Removed margins"
            value={`H ${data.summary.removed_header_footer.header} / F ${data.summary.removed_header_footer.footer}`}
          />
          <OperationalMetric
            label="Open review"
            value={String(data.summary.review_blocks)}
          />
          <OperationalMetric
            label="GPU seconds"
            value={
              data.summary.gpu_seconds === null
                ? null
                : data.summary.gpu_seconds.toFixed(2)
            }
          />
          <OperationalMetric
            label="Queue position"
            value={
              data.summary.queue_position === null
                ? null
                : String(data.summary.queue_position)
            }
          />
        </div>
      </footer>

      <ReviewDrawer
        items={data.reviews}
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        onSelectEvidence={selectEvidence}
        onResolve={(item, resolution) =>
          apiRequest(`/v1/review-items/${item.id}/resolve`, {
            method: "POST",
            idempotencyKey: crypto.randomUUID(),
            body: JSON.stringify({
              action: resolution.action,
              value: resolution.value ?? null,
              note: resolution.note ?? null,
            }),
          }).then(() => {
            void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
          })
        }
        onReprocess={(item) => {
          if (!item.page_id) {
            return Promise.reject(
              new Error("재처리할 페이지 근거가 없습니다."),
            );
          }
          return apiRequest(`/v1/pages/${item.page_id}/reprocess`, {
            method: "POST",
            idempotencyKey: crypto.randomUUID(),
          }).then(() => {
            void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
          });
        }}
        onPreviewRule={(item) =>
          apiRequest<ReviewScopePreview>(
            `/v1/review-items/${item.id}/scope-preview`,
          )
        }
        onApplyRule={(item, action, previewSha256) =>
          apiRequest(`/v1/review-items/${item.id}/apply-rule`, {
            method: "POST",
            idempotencyKey: crypto.randomUUID(),
            body: JSON.stringify({
              action,
              preview_sha256: previewSha256,
              note: "Document-wide rule applied from review queue",
            }),
          }).then(() => {
            void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
          })
        }
      />
      {modelMergeBlock && (
        <ModelMergeDialog
          block={modelMergeBlock}
          open
          onClose={() => setModelMergeBlockId(undefined)}
          onPreview={(block, request, idempotencyKey) =>
            apiRequest<BlockModelMergeResponse>(
              `/v1/blocks/${block.id}/model-merge`,
              {
                method: "POST",
                idempotencyKey,
                headers: {
                  "If-Match": `"revision-${block.revision}"`,
                },
                body: JSON.stringify(request),
              },
            )
          }
          onApply={(block, preview, resolvedMarkdown, idempotencyKey) =>
            apiRequest(`/v1/blocks/${block.id}`, {
              method: "PATCH",
              idempotencyKey,
              headers: {
                "If-Match": preview.etag,
              },
              body: JSON.stringify({
                markdown: resolvedMarkdown,
                user_locked: true,
              }),
            }).then(() =>
              queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
            )
          }
          onStale={() => {
            void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
          }}
        />
      )}
      {reviewOpen && (
        <button
          className="drawer-scrim"
          aria-label="검토 창 닫기"
          onClick={() => setReviewOpen(false)}
        />
      )}
      <ExportDialog
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        summary={{
          pages: pages.length,
          blocks: data.summary.blocks,
          knowledgeNotes: data.summary.knowledge_notes,
          reviewWarnings: data.reviews.filter((item) => item.status === "open")
            .length,
        }}
        onExport={(profiles) =>
          apiRequest<{ export_id: string; download_url: string }>(
            `/v1/jobs/${jobId}/exports`,
            {
              method: "POST",
              idempotencyKey: crypto.randomUUID(),
              body: JSON.stringify({ profiles }),
            },
          ).then((result) => ({
            exportId: result.export_id,
            downloadUrl: result.download_url,
          }))
        }
        onVaultPreview={(exportId, vault, policy) => {
          const body = new FormData();
          body.set("existing_vault", vault);
          body.set("policy", policy);
          return apiRequest<VaultMergePreview>(
            `/v1/exports/${exportId}/vault-merge-preview`,
            { method: "POST", body },
          );
        }}
      />
    </div>
  );
}

function ProgressAnnouncement({ message }: { message: string }) {
  const announcement = useThrottledAnnouncement(message, 4_000);
  return (
    <p
      className="visually-hidden"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {announcement}
    </p>
  );
}

function isCanonicalBlock(block: CanonicalBlockPatch): block is CanonicalBlock {
  return (
    typeof block.order === "number" &&
    typeof block.type === "string" &&
    typeof block.markdown === "string" &&
    typeof block.source_text === "string" &&
    typeof block.origin === "string" &&
    typeof block.content_layer === "string" &&
    Array.isArray(block.source_refs) &&
    Array.isArray(block.quality_flags) &&
    typeof block.revision === "number"
  );
}

function Credit({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function OperationalMetric({
  label,
  value,
}: {
  label: string;
  value: string | null;
}) {
  return (
    <span className="operational-metric" data-available={value !== null}>
      <small>{label}</small>
      <strong>{value ?? "Unavailable"}</strong>
    </span>
  );
}

function formatCounterMap(values: Record<string, number>): string {
  const entries = Object.entries(values).filter(([, value]) => value > 0);
  if (entries.length === 0) return "None";
  return entries.map(([key, value]) => `${key} ${value}`).join(" · ");
}

function WorkspaceState({
  message,
  busy = false,
  retry,
}: {
  message: string;
  busy?: boolean;
  retry?: () => void;
}) {
  return (
    <div className="processing-empty" aria-busy={busy}>
      {busy ? (
        <span className="spinner" aria-hidden="true" />
      ) : (
        <Warning size={24} />
      )}
      <h1>{busy ? "처리 증거 확인 중" : "작업을 표시할 수 없습니다."}</h1>
      <p>{message}</p>
      {retry && (
        <button type="button" className="secondary-button" onClick={retry}>
          다시 시도
        </button>
      )}
      <Link href="/" className="text-link">
        프로젝트로 돌아가기
      </Link>
    </div>
  );
}

function jobStatusLabel(status: JobSnapshot["job"]["status"]): string {
  return {
    created: "처리 준비 중",
    queued: "처리 대기 중",
    running: "지식 컴파일 진행 중",
    completed: "처리 완료",
    failed: "처리 실패",
    cancelled: "처리 취소됨",
  }[status];
}

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.max(0, Math.round(seconds % 60));
  return `${minutes}m ${remainder}s elapsed`;
}
