"use client";

import {
  ArrowCounterClockwise,
  CheckCircle,
  Clock,
  Cpu,
  FileText,
  FolderOpen,
  GitBranch,
  Info,
  Package,
  Pulse,
  ShieldCheck,
  ShieldWarning,
  Warning,
  Wrench,
} from "@phosphor-icons/react";
import { useId, useMemo, useState, type ReactNode } from "react";

import styles from "./parallel-processing-theater.module.css";
import {
  deriveV6ProductView,
  eventCountForTypes,
  type AttemptPresentation,
  type CreditImpact,
  type IntegrityLedgerEntry,
  type PagePresentation,
  type PagePresentationState,
  type V6ProductView,
  type V6VersionedEvent,
  type WorkerPoolPresentation,
} from "./event-model";

export type V6ProductLocale = "en" | "ko";
export type V6ConnectionState = "live" | "replaying" | "offline" | "complete";

export type ParallelProcessingTheaterProps = {
  readonly events: readonly V6VersionedEvent[];
  readonly locale?: V6ProductLocale;
  readonly connection?: V6ConnectionState;
  readonly baselineSequence?: number;
  readonly defaultTechnicalOpen?: boolean;
};

type Copy = (typeof COPY)[V6ProductLocale];
const DISPLAY_WINDOW = 100;

const STAGES = [
  {
    id: "intake",
    types: [
      "page.preflight.completed.v1",
      "shard.planned.v1",
      "shard.dispatched.v1",
    ],
  },
  {
    id: "structure",
    types: [
      "page.route.selected.v1",
      "page.processing.started.v1",
      "page.layout.detected.v1",
      "page.block.completed.v1",
      "attempt.started.v1",
      "attempt.output.received.v1",
    ],
  },
  {
    id: "verify",
    types: [
      "attempt.validation.failed.v1",
      "attempt.accepted.v1",
      "attempt.rejected.v1",
      "page.completed.v1",
      "page.unresolved.v1",
      "page.quarantined.v1",
    ],
  },
  {
    id: "recover",
    types: [
      "page.retry.scheduled.v1",
      "recovery.region.requested.v1",
      "recovery.completed.v1",
    ],
  },
  {
    id: "knowledge",
    types: [
      "continuity.merge.started.v1",
      "continuity.merge.completed.v1",
      "document.knowledge.note_created.v1",
      "note.created.v1",
      "document.knowledge.link_created.v1",
      "relation.created.v1",
      "collection.retrieval.indexed.v1",
      "architecture.folder.created.v1",
      "document.finalized.v1",
    ],
  },
  {
    id: "package",
    types: [
      "export.started.v1",
      "export.completed.v1",
      "export.ready.v1",
      "package.validated.v1",
      "package.signed.v1",
      "job.completed.v1",
    ],
  },
] as const;

const COPY = {
  en: {
    eyebrow: "Autonomous processing",
    title: "Processing Theater",
    intro:
      "Event-backed state only. This view never estimates completion or animates synthetic progress.",
    connection: {
      live: "Live event stream",
      replaying: "Replaying durable events",
      offline: "Offline · last durable state",
      complete: "Event stream complete",
    },
    eventLedger: "Recorded event ledger",
    latestSequence: "Latest sequence",
    pageStates: "Parallel page states",
    pageStatesBody:
      "Each page reflects its latest accepted v1 event. Several active cards indicate concurrent work; they are not a speed claim.",
    noPages: "No page-level event has been received yet.",
    page: "Page",
    pageId: "Page ID",
    route: "Route",
    attempts: "Attempts",
    latestEvent: "Latest event",
    knowledgeOutputTitle: "Knowledge output ledger",
    knowledgeOutputBody:
      "Directories, notes, links, continuity merges, finalization, and package artifacts appear only when their event is recorded.",
    noKnowledgeOutput: "No knowledge-output event has been received yet.",
    outputEvidence: "Event evidence",
    recentWindow: (shown: number, total: number) =>
      `Showing the latest ${shown} of ${total} records. The durable event ledger remains authoritative.`,
    outputType: {
      "architecture.folder.created.v1": "Directory created",
      "document.knowledge.note_created.v1": "Knowledge note created",
      "note.created.v1": "Knowledge note created",
      "document.knowledge.link_created.v1": "Knowledge link created",
      "relation.created.v1": "Knowledge relation created",
      "collection.retrieval.indexed.v1": "Retrieval index verified",
      "continuity.merge.started.v1": "Continuity merge started",
      "continuity.merge.completed.v1": "Continuity merge completed",
      "document.finalized.v1": "Document finalized",
      "export.started.v1": "Export started",
      "export.completed.v1": "Export completed",
      "export.ready.v1": "Export ready",
      "package.validated.v1": "Package validated",
      "package.signed.v1": "Package signed",
    },
    notReported: "Not reported",
    recordedEvents: (count: number) =>
      `${count} recorded event${count === 1 ? "" : "s"}`,
    contractWarning: "Event evidence is incomplete",
    ignoredEvents: (count: number) =>
      `${count} unsupported or malformed event${count === 1 ? "" : "s"} ignored`,
    conflictingSequences: (count: number) =>
      `${count} conflicting sequence${count === 1 ? "" : "s"} isolated`,
    gaps: (count: number) =>
      `${count} missing sequence${count === 1 ? "" : "s"}; replay required`,
    stages: {
      intake: "Document intake",
      structure: "Structure analysis",
      verify: "Precision verification",
      recover: "Automatic recovery",
      knowledge: "Knowledge composition",
      package: "Packaging",
    },
    stageAwaiting: "No event recorded",
    state: {
      planned: "Planned",
      dispatched: "Dispatched",
      processing: "Processing",
      validating: "Validating",
      recovering: "Recovering",
      recovered_pending_validation: "Recovery complete · validation pending",
      verified: "Verified",
      authority_verified: "Authority verified",
      cross_model_verified: "Cross-model verified",
      auto_repaired: "Auto-repaired and verified",
      completed_unverified: "Completed · verification not reported",
      validation_failed: "Validation failed",
      unresolved: "Unresolved",
      quarantined: "Quarantined",
      failed: "Failed",
    },
    technicalTitle: "Advanced technical view",
    technicalBody:
      "Worker pools, immutable attempts, routes, validation telemetry, and measured cost fields.",
    activePages: "Pages with an active event state",
    poolCount: "Worker pools reported",
    attemptCount: "Immutable attempts",
    retryEvents: "Retry schedule events",
    gpuSeconds: "GPU seconds reported",
    consumedCredits: "Credits consumed",
    releasedCredits: "Credits released or refunded",
    providerCost: "Provider cost (USD)",
    poolLedger: "Worker pool ledger",
    noPools: "No worker-pool identity has been reported in the event stream.",
    workerCount: "Workers",
    poolAttempts: "Attempts",
    attemptLedger: "Attempt lineage",
    noAttempts: "No attempt event has been received yet.",
    attemptNumber: "Attempt number",
    rootAttempt: "Root attempt",
    parentAttempt: "Parent attempt",
    shard: "Shard",
    pool: "Pool",
    worker: "Worker",
    model: "Model revision",
    validator: "Validator",
    gpu: "GPU seconds",
    costSource: "Cost source",
    billable: "Billable",
    yes: "Yes",
    no: "No",
    integrityTitle: "Integrity state",
    integrityBody:
      "Automatic recovery, unresolved output, quarantine, evidence, reasons, and customer-credit impact.",
    recovered: "Recovery events resolved",
    unresolved: "Unresolved",
    quarantined: "Quarantined",
    verificationFailures: "Verification failures",
    cleanUnknown:
      "No integrity event has been received. This is not presented as a clean bill of health.",
    integrityLedger: "Integrity evidence ledger",
    evidence: "Evidence",
    reason: "Reason",
    creditImpact: "Credit impact",
    status: "Status",
    integrityKind: {
      automatic_recovery: "Automatic recovery",
      verification_failure: "Verification failure",
      unresolved: "Unresolved output",
      quarantined: "Quarantined output",
      worker_health: "Worker semantic health",
    },
    integrityStatus: {
      active: "Active",
      resolved: "Resolved",
      isolated: "Isolated",
    },
    credit: {
      not_billable: "Not billable",
      no_duplicate_charge_policy: "No duplicate charge by policy",
      not_reported: "Not reported",
      measured: "Reported",
    },
  },
  ko: {
    eyebrow: "자율 처리",
    title: "프로세싱 시어터",
    intro:
      "이벤트로 확인된 상태만 표시합니다. 완료율을 추정하거나 가짜 진행 애니메이션을 만들지 않습니다.",
    connection: {
      live: "실시간 이벤트 스트림",
      replaying: "영속 이벤트 재생 중",
      offline: "오프라인 · 마지막 영속 상태",
      complete: "이벤트 스트림 완료",
    },
    eventLedger: "기록된 이벤트 원장",
    latestSequence: "최신 시퀀스",
    pageStates: "병렬 페이지 상태",
    pageStatesBody:
      "각 페이지는 가장 최근에 수신한 v1 이벤트를 반영합니다. 여러 활성 카드는 동시 작업 상태이며 속도 주장이 아닙니다.",
    noPages: "아직 페이지 단위 이벤트가 수신되지 않았습니다.",
    page: "페이지",
    pageId: "페이지 ID",
    route: "라우트",
    attempts: "시도",
    latestEvent: "최근 이벤트",
    knowledgeOutputTitle: "지식 출력 원장",
    knowledgeOutputBody:
      "디렉터리, 노트, 링크, 연속성 병합, 최종화와 패키지 산출물은 해당 이벤트가 기록된 경우에만 표시합니다.",
    noKnowledgeOutput: "아직 지식 출력 이벤트가 수신되지 않았습니다.",
    outputEvidence: "이벤트 근거",
    recentWindow: (shown: number, total: number) =>
      `최근 ${total}건 중 ${shown}건을 표시합니다. 영속 이벤트 원장이 최종 기준입니다.`,
    outputType: {
      "architecture.folder.created.v1": "디렉터리 생성",
      "document.knowledge.note_created.v1": "지식 노트 생성",
      "note.created.v1": "지식 노트 생성",
      "document.knowledge.link_created.v1": "지식 링크 생성",
      "relation.created.v1": "지식 관계 생성",
      "collection.retrieval.indexed.v1": "검색 인덱스 검증 완료",
      "continuity.merge.started.v1": "연속성 병합 시작",
      "continuity.merge.completed.v1": "연속성 병합 완료",
      "document.finalized.v1": "문서 최종화",
      "export.started.v1": "내보내기 시작",
      "export.completed.v1": "내보내기 완료",
      "export.ready.v1": "내보내기 준비 완료",
      "package.validated.v1": "패키지 검증 완료",
      "package.signed.v1": "패키지 서명 완료",
    },
    notReported: "보고되지 않음",
    recordedEvents: (count: number) => `기록 이벤트 ${count}건`,
    contractWarning: "이벤트 증적이 불완전합니다",
    ignoredEvents: (count: number) =>
      `지원하지 않거나 잘못된 이벤트 ${count}건 제외`,
    conflictingSequences: (count: number) => `충돌 시퀀스 ${count}건 격리`,
    gaps: (count: number) => `누락 시퀀스 ${count}건 · 재생 필요`,
    stages: {
      intake: "문서 수집",
      structure: "구조 분석",
      verify: "정밀 확인",
      recover: "자동 복구",
      knowledge: "지식 구성",
      package: "패키징",
    },
    stageAwaiting: "기록된 이벤트 없음",
    state: {
      planned: "계획됨",
      dispatched: "배정됨",
      processing: "처리 중",
      validating: "검증 중",
      recovering: "복구 중",
      recovered_pending_validation: "복구 완료 · 검증 대기",
      verified: "검증됨",
      authority_verified: "권위 출처 검증됨",
      cross_model_verified: "교차 모델 검증됨",
      auto_repaired: "자동 복구 후 검증됨",
      completed_unverified: "완료 · 검증 상태 미보고",
      validation_failed: "검증 실패",
      unresolved: "미해결",
      quarantined: "격리됨",
      failed: "실패",
    },
    technicalTitle: "고급 기술 보기",
    technicalBody:
      "워커 풀, 불변 시도 계보, 라우트, 검증 텔레메트리와 실측 비용 필드입니다.",
    activePages: "활성 이벤트 상태 페이지",
    poolCount: "보고된 워커 풀",
    attemptCount: "불변 시도",
    retryEvents: "재시도 예약 이벤트",
    gpuSeconds: "보고된 GPU 초",
    consumedCredits: "사용 크레딧",
    releasedCredits: "반환·환불 크레딧",
    providerCost: "공급자 비용(USD)",
    poolLedger: "워커 풀 원장",
    noPools: "이벤트 스트림에 워커 풀 식별자가 보고되지 않았습니다.",
    workerCount: "워커",
    poolAttempts: "시도",
    attemptLedger: "시도 계보",
    noAttempts: "아직 시도 이벤트가 수신되지 않았습니다.",
    attemptNumber: "시도 번호",
    rootAttempt: "루트 시도",
    parentAttempt: "부모 시도",
    shard: "샤드",
    pool: "풀",
    worker: "워커",
    model: "모델 리비전",
    validator: "검증기",
    gpu: "GPU 초",
    costSource: "비용 출처",
    billable: "과금 대상",
    yes: "예",
    no: "아니요",
    integrityTitle: "무결성 상태",
    integrityBody:
      "자동 복구, 미해결 결과, 격리, 근거, 사유와 고객 크레딧 영향을 표시합니다.",
    recovered: "해결된 복구 이벤트",
    unresolved: "미해결",
    quarantined: "격리",
    verificationFailures: "검증 실패",
    cleanUnknown:
      "무결성 이벤트가 아직 수신되지 않았습니다. 이를 문제없음으로 표시하지 않습니다.",
    integrityLedger: "무결성 증적 원장",
    evidence: "근거",
    reason: "사유",
    creditImpact: "크레딧 영향",
    status: "상태",
    integrityKind: {
      automatic_recovery: "자동 복구",
      verification_failure: "검증 실패",
      unresolved: "미해결 결과",
      quarantined: "격리 결과",
      worker_health: "워커 의미 건강도",
    },
    integrityStatus: {
      active: "진행 중",
      resolved: "해결됨",
      isolated: "격리됨",
    },
    credit: {
      not_billable: "비과금",
      no_duplicate_charge_policy: "정책상 중복 과금 없음",
      not_reported: "보고되지 않음",
      measured: "보고됨",
    },
  },
} as const;

export function ParallelProcessingTheater({
  events,
  locale = "en",
  connection = "live",
  baselineSequence,
  defaultTechnicalOpen = false,
}: ParallelProcessingTheaterProps) {
  const view = useMemo(
    () => deriveV6ProductView(events, baselineSequence),
    [baselineSequence, events],
  );
  const titleId = useId();
  const pageStatesTitleId = useId();
  const copy = COPY[locale];
  const latestSequence = view.events.at(-1)?.sequence;
  const evidenceIssueCount =
    view.ignoredEventCount + view.conflictingSequenceCount + view.gapCount;

  return (
    <section className={styles.root} aria-labelledby={titleId}>
      <header className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h2 id={titleId}>{copy.title}</h2>
          <p className={styles.intro}>{copy.intro}</p>
        </div>
        <div
          className={styles.connection}
          data-state={connection}
          role="status"
        >
          <ConnectionIcon state={connection} />
          <span>{copy.connection[connection]}</span>
        </div>
      </header>

      <dl className={styles.runLedger} aria-live="polite">
        <Metric
          label={copy.eventLedger}
          value={formatInteger(locale, view.events.length)}
        />
        <Metric
          label={copy.latestSequence}
          value={
            latestSequence === undefined
              ? copy.notReported
              : formatInteger(locale, latestSequence)
          }
          mono={latestSequence !== undefined}
        />
      </dl>

      {evidenceIssueCount > 0 ? (
        <div className={styles.contractWarning} role="alert">
          <Warning size={19} weight="fill" aria-hidden="true" />
          <div>
            <strong>{copy.contractWarning}</strong>
            <ul>
              {view.ignoredEventCount > 0 ? (
                <li>{copy.ignoredEvents(view.ignoredEventCount)}</li>
              ) : null}
              {view.conflictingSequenceCount > 0 ? (
                <li>
                  {copy.conflictingSequences(view.conflictingSequenceCount)}
                </li>
              ) : null}
              {view.gapCount > 0 ? <li>{copy.gaps(view.gapCount)}</li> : null}
            </ul>
          </div>
        </div>
      ) : null}

      <ol className={styles.stageLedger} aria-label={copy.eventLedger}>
        {STAGES.map((stage) => {
          const count = eventCountForTypes(view.events, stage.types);
          return (
            <li key={stage.id} data-observed={count > 0}>
              <span className={styles.stageMarker} aria-hidden="true">
                {count > 0 ? (
                  <FileText size={17} weight="fill" />
                ) : (
                  <Clock size={17} />
                )}
              </span>
              <span>
                <strong>{copy.stages[stage.id]}</strong>
                <small>
                  {count > 0 ? copy.recordedEvents(count) : copy.stageAwaiting}
                </small>
              </span>
            </li>
          );
        })}
      </ol>

      <section className={styles.section} aria-labelledby={pageStatesTitleId}>
        <header className={styles.sectionHeader}>
          <div>
            <p className={styles.sectionIndex}>01</p>
            <h3 id={pageStatesTitleId}>{copy.pageStates}</h3>
          </div>
          <p>{copy.pageStatesBody}</p>
        </header>
        {view.pages.length > 0 ? (
          <div className={styles.pageGrid}>
            {view.pages.map((page) => (
              <PageCard
                key={page.pageId}
                page={page}
                locale={locale}
                copy={copy}
              />
            ))}
          </div>
        ) : (
          <EmptyState icon={<FileText size={22} />} text={copy.noPages} />
        )}
      </section>

      <KnowledgeOutputLedger view={view} locale={locale} />
      <IntegrityStatePanel view={view} locale={locale} />
      <AdvancedTechnicalView
        view={view}
        locale={locale}
        defaultOpen={defaultTechnicalOpen}
      />
    </section>
  );
}

function KnowledgeOutputLedger({
  view,
  locale,
}: {
  readonly view: V6ProductView;
  readonly locale: V6ProductLocale;
}) {
  const copy = COPY[locale];
  const titleId = useId();
  const outputTypes = new Set(Object.keys(copy.outputType));
  const allOutputEvents = view.events
    .filter((event) => outputTypes.has(event.event_type))
    .toReversed();
  const outputEvents = allOutputEvents.slice(0, DISPLAY_WINDOW);

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <header className={styles.sectionHeader}>
        <div>
          <p className={styles.sectionIndex}>02</p>
          <h3 id={titleId}>{copy.knowledgeOutputTitle}</h3>
        </div>
        <p>{copy.knowledgeOutputBody}</p>
      </header>
      {outputEvents.length > 0 ? (
        <ol className={styles.outputLedger}>
          {outputEvents.map((event) => {
            const detail = outputEventDetail(event);
            return (
              <li key={event.event_id}>
                <span className={styles.outputIcon} aria-hidden="true">
                  {event.event_type === "architecture.folder.created.v1" ? (
                    <FolderOpen size={19} />
                  ) : event.event_type.includes("package") ||
                    event.event_type.includes("export") ? (
                    <Package size={19} />
                  ) : (
                    <FileText size={19} />
                  )}
                </span>
                <div>
                  <strong>
                    {
                      copy.outputType[
                        event.event_type as keyof typeof copy.outputType
                      ]
                    }
                  </strong>
                  {detail ? <code>{detail}</code> : null}
                  <small>
                    {copy.outputEvidence}: event:{event.event_id}#
                    {event.sequence}
                  </small>
                </div>
                <time dateTime={event.occurred_at} title={event.occurred_at}>
                  {formatDateTime(locale, event.occurred_at)}
                </time>
              </li>
            );
          })}
        </ol>
      ) : (
        <EmptyState
          icon={<FolderOpen size={22} />}
          text={copy.noKnowledgeOutput}
        />
      )}
      {allOutputEvents.length > outputEvents.length ? (
        <p className={styles.windowNotice} role="status">
          {copy.recentWindow(outputEvents.length, allOutputEvents.length)}
        </p>
      ) : null}
    </section>
  );
}

export function IntegrityStatePanel({
  view,
  locale = "en",
}: {
  readonly view: V6ProductView;
  readonly locale?: V6ProductLocale;
}) {
  const copy = COPY[locale];
  const titleId = useId();
  const resolvedRecovery = view.integrityEntries.filter(
    (entry) =>
      entry.kind === "automatic_recovery" && entry.status === "resolved",
  ).length;
  const unresolved = view.pages.filter(
    (page) => page.state === "unresolved",
  ).length;
  const quarantined = view.pages.filter(
    (page) => page.state === "quarantined",
  ).length;
  const verificationFailures = view.integrityEntries.filter(
    (entry) => entry.kind === "verification_failure",
  ).length;
  const visibleIntegrityEntries = view.integrityEntries.slice(
    0,
    DISPLAY_WINDOW,
  );

  return (
    <section className={styles.section} aria-labelledby={titleId}>
      <header className={styles.sectionHeader}>
        <div>
          <p className={styles.sectionIndex}>03</p>
          <h3 id={titleId}>{copy.integrityTitle}</h3>
        </div>
        <p>{copy.integrityBody}</p>
      </header>
      <dl className={styles.integritySummary}>
        <Metric
          label={copy.recovered}
          value={formatInteger(locale, resolvedRecovery)}
          tone="verified"
        />
        <Metric
          label={copy.unresolved}
          value={formatInteger(locale, unresolved)}
          tone="warning"
        />
        <Metric
          label={copy.quarantined}
          value={formatInteger(locale, quarantined)}
          tone="danger"
        />
        <Metric
          label={copy.verificationFailures}
          value={formatInteger(locale, verificationFailures)}
          tone="warning"
        />
      </dl>
      {view.integrityEntries.length === 0 ? (
        <EmptyState icon={<Info size={22} />} text={copy.cleanUnknown} />
      ) : (
        <div>
          <h4 className={styles.ledgerTitle}>{copy.integrityLedger}</h4>
          <ol className={styles.integrityLedger}>
            {visibleIntegrityEntries.map((entry) => (
              <IntegrityEntry
                key={`${entry.eventId}:${entry.sequence}`}
                entry={entry}
                copy={copy}
                locale={locale}
              />
            ))}
          </ol>
          {view.integrityEntries.length > visibleIntegrityEntries.length ? (
            <p className={styles.windowNotice} role="status">
              {copy.recentWindow(
                visibleIntegrityEntries.length,
                view.integrityEntries.length,
              )}
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}

export function AdvancedTechnicalView({
  view,
  locale = "en",
  defaultOpen = false,
}: {
  readonly view: V6ProductView;
  readonly locale?: V6ProductLocale;
  readonly defaultOpen?: boolean;
}) {
  const copy = COPY[locale];
  const poolTitleId = useId();
  const attemptTitleId = useId();
  const [open, setOpen] = useState(defaultOpen);
  const activePages = view.pages.filter((page) =>
    ["processing", "validating", "recovering"].includes(page.state),
  ).length;
  const retryEvents = eventCountForTypes(view.events, [
    "page.retry.scheduled.v1",
  ]);
  const visibleAttempts = view.attempts.slice(0, DISPLAY_WINDOW);

  return (
    <details
      className={styles.technical}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <Cpu size={20} aria-hidden="true" />
        <span>
          <strong>{copy.technicalTitle}</strong>
          <small>{copy.technicalBody}</small>
        </span>
      </summary>
      <div className={styles.technicalBody}>
        <dl className={styles.technicalSummary}>
          <Metric
            label={copy.activePages}
            value={formatInteger(locale, activePages)}
          />
          <Metric
            label={copy.poolCount}
            value={formatInteger(locale, view.workerPools.length)}
          />
          <Metric
            label={copy.attemptCount}
            value={formatInteger(locale, view.attempts.length)}
          />
          <Metric
            label={copy.retryEvents}
            value={formatInteger(locale, retryEvents)}
          />
          <Metric
            label={copy.gpuSeconds}
            value={formatMeasured(
              locale,
              view.cost.gpuSeconds,
              2,
              copy.notReported,
            )}
          />
          <Metric
            label={copy.providerCost}
            value={formatMeasured(
              locale,
              view.cost.providerCostUsd,
              4,
              copy.notReported,
            )}
          />
          <Metric
            label={copy.consumedCredits}
            value={formatMeasured(
              locale,
              view.cost.consumedCredits,
              2,
              copy.notReported,
            )}
          />
          <Metric
            label={copy.releasedCredits}
            value={formatMeasured(
              locale,
              view.cost.releasedCredits,
              2,
              copy.notReported,
            )}
          />
        </dl>

        <section aria-labelledby={poolTitleId}>
          <h4 id={poolTitleId} className={styles.ledgerTitle}>
            {copy.poolLedger}
          </h4>
          {view.workerPools.length > 0 ? (
            <ol className={styles.poolLedger}>
              {view.workerPools.map((pool) => (
                <WorkerPool
                  key={pool.poolId}
                  pool={pool}
                  copy={copy}
                  locale={locale}
                />
              ))}
            </ol>
          ) : (
            <EmptyState icon={<Cpu size={22} />} text={copy.noPools} compact />
          )}
        </section>

        <section aria-labelledby={attemptTitleId}>
          <h4 id={attemptTitleId} className={styles.ledgerTitle}>
            {copy.attemptLedger}
          </h4>
          {view.attempts.length > 0 ? (
            <ol className={styles.attemptLedger}>
              {visibleAttempts.map((attempt) => (
                <AttemptEntry
                  key={attempt.attemptId}
                  attempt={attempt}
                  copy={copy}
                  locale={locale}
                />
              ))}
            </ol>
          ) : (
            <EmptyState
              icon={<GitBranch size={22} />}
              text={copy.noAttempts}
              compact
            />
          )}
          {view.attempts.length > visibleAttempts.length ? (
            <p className={styles.windowNotice} role="status">
              {copy.recentWindow(visibleAttempts.length, view.attempts.length)}
            </p>
          ) : null}
        </section>
      </div>
    </details>
  );
}

function PageCard({
  page,
  locale,
  copy,
}: {
  readonly page: PagePresentation;
  readonly locale: V6ProductLocale;
  readonly copy: Copy;
}) {
  return (
    <article className={styles.pageCard} data-state={page.state}>
      <header>
        <span className={styles.stateIcon} aria-hidden="true">
          <StateIcon state={page.state} />
        </span>
        <div>
          <p>
            {page.pageNumber1 === undefined
              ? copy.page
              : `${copy.page} ${formatInteger(locale, page.pageNumber1)}`}
          </p>
          <strong>{copy.state[page.state]}</strong>
        </div>
      </header>
      <dl>
        <CompactFact label={copy.pageId} value={page.pageId} mono />
        <CompactFact
          label={copy.route}
          value={page.route ?? copy.notReported}
        />
        <CompactFact
          label={copy.attempts}
          value={formatInteger(locale, page.attemptIds.length)}
        />
        <CompactFact label={copy.latestEvent} value={page.lastEventType} mono />
      </dl>
      <time dateTime={page.lastOccurredAt} title={page.lastOccurredAt}>
        {formatDateTime(locale, page.lastOccurredAt)}
      </time>
    </article>
  );
}

function IntegrityEntry({
  entry,
  copy,
  locale,
}: {
  readonly entry: IntegrityLedgerEntry;
  readonly copy: Copy;
  readonly locale: V6ProductLocale;
}) {
  return (
    <li data-kind={entry.kind}>
      <header>
        <span className={styles.integrityIcon} aria-hidden="true">
          {entry.kind === "automatic_recovery" ? (
            <ArrowCounterClockwise size={18} />
          ) : entry.kind === "quarantined" || entry.kind === "worker_health" ? (
            <ShieldWarning size={18} />
          ) : (
            <Warning size={18} />
          )}
        </span>
        <div>
          <strong>{copy.integrityKind[entry.kind]}</strong>
          <span>{copy.integrityStatus[entry.status]}</span>
        </div>
        <time dateTime={entry.occurredAt} title={entry.occurredAt}>
          {formatDateTime(locale, entry.occurredAt)}
        </time>
      </header>
      <dl>
        <CompactFact
          label={copy.reason}
          value={entry.reason ?? copy.notReported}
        />
        <CompactFact label={copy.evidence} value={entry.evidenceRef} mono />
        <CompactFact
          label={copy.creditImpact}
          value={creditImpactLabel(copy, entry.creditImpact)}
        />
      </dl>
    </li>
  );
}

function WorkerPool({
  pool,
  copy,
  locale,
}: {
  readonly pool: WorkerPoolPresentation;
  readonly copy: Copy;
  readonly locale: V6ProductLocale;
}) {
  return (
    <li data-state={pool.status}>
      <header>
        <Cpu size={18} aria-hidden="true" />
        <code>{pool.poolId}</code>
        <strong>{pool.status}</strong>
      </header>
      <dl>
        <CompactFact
          label={copy.workerCount}
          value={formatInteger(locale, pool.workerIds.length)}
        />
        <CompactFact
          label={copy.poolAttempts}
          value={formatInteger(locale, pool.attemptIds.length)}
        />
        <CompactFact
          label={copy.latestSequence}
          value={formatInteger(locale, pool.lastSequence)}
          mono
        />
      </dl>
    </li>
  );
}

function AttemptEntry({
  attempt,
  copy,
  locale,
}: {
  readonly attempt: AttemptPresentation;
  readonly copy: Copy;
  readonly locale: V6ProductLocale;
}) {
  return (
    <li data-state={attempt.status}>
      <header>
        <GitBranch size={18} aria-hidden="true" />
        <code>{attempt.attemptId}</code>
        <strong>{attempt.status}</strong>
      </header>
      <dl>
        <CompactFact
          label={copy.attemptNumber}
          value={
            attempt.attemptNumber === undefined
              ? copy.notReported
              : formatInteger(locale, attempt.attemptNumber)
          }
          mono={attempt.attemptNumber !== undefined}
        />
        <CompactFact
          label={copy.rootAttempt}
          value={attempt.rootAttemptId ?? copy.notReported}
          mono={Boolean(attempt.rootAttemptId)}
        />
        <CompactFact
          label={copy.parentAttempt}
          value={attempt.parentAttemptId ?? copy.notReported}
          mono={Boolean(attempt.parentAttemptId)}
        />
        <CompactFact
          label={copy.shard}
          value={attempt.shardId ?? copy.notReported}
          mono={Boolean(attempt.shardId)}
        />
        <CompactFact
          label={copy.pool}
          value={attempt.poolId ?? copy.notReported}
          mono={Boolean(attempt.poolId)}
        />
        <CompactFact
          label={copy.worker}
          value={attempt.workerId ?? copy.notReported}
          mono={Boolean(attempt.workerId)}
        />
        <CompactFact
          label={copy.route}
          value={attempt.route ?? copy.notReported}
        />
        <CompactFact
          label={copy.model}
          value={attempt.modelRevision ?? copy.notReported}
          mono={Boolean(attempt.modelRevision)}
        />
        <CompactFact
          label={copy.validator}
          value={attempt.validatorStatus ?? copy.notReported}
        />
        <CompactFact
          label={copy.gpu}
          value={formatMeasured(
            locale,
            attempt.gpuSeconds ?? null,
            2,
            copy.notReported,
          )}
        />
        <CompactFact
          label={copy.costSource}
          value={attempt.costSource ?? copy.notReported}
        />
        <CompactFact
          label={copy.billable}
          value={
            attempt.billable === undefined
              ? copy.notReported
              : attempt.billable
                ? copy.yes
                : copy.no
          }
        />
      </dl>
    </li>
  );
}

function Metric({
  label,
  value,
  mono = false,
  tone,
}: {
  readonly label: string;
  readonly value: string;
  readonly mono?: boolean;
  readonly tone?: "verified" | "warning" | "danger";
}) {
  return (
    <div className={styles.metric} data-tone={tone}>
      <dt>{label}</dt>
      <dd className={mono ? styles.mono : undefined}>{value}</dd>
    </div>
  );
}

function CompactFact({
  label,
  value,
  mono = false,
}: {
  readonly label: string;
  readonly value: string;
  readonly mono?: boolean;
}) {
  return (
    <div className={styles.compactFact}>
      <dt>{label}</dt>
      <dd
        className={mono ? styles.mono : undefined}
        title={mono ? value : undefined}
      >
        {value}
      </dd>
    </div>
  );
}

function EmptyState({
  icon,
  text,
  compact = false,
}: {
  readonly icon: ReactNode;
  readonly text: string;
  readonly compact?: boolean;
}) {
  return (
    <div className={styles.emptyState} data-compact={compact}>
      <span aria-hidden="true">{icon}</span>
      <p>{text}</p>
    </div>
  );
}

function StateIcon({ state }: { readonly state: PagePresentationState }) {
  switch (state) {
    case "verified":
    case "authority_verified":
    case "cross_model_verified":
    case "auto_repaired":
      return <ShieldCheck size={20} weight="fill" />;
    case "recovering":
    case "recovered_pending_validation":
      return <Wrench size={20} />;
    case "unresolved":
    case "validation_failed":
      return <Warning size={20} weight="fill" />;
    case "quarantined":
    case "failed":
      return <ShieldWarning size={20} weight="fill" />;
    case "completed_unverified":
      return <Info size={20} weight="fill" />;
    case "planned":
    case "dispatched":
      return <Clock size={20} />;
    case "processing":
    case "validating":
      return <Pulse size={20} />;
  }
}

function ConnectionIcon({ state }: { readonly state: V6ConnectionState }) {
  switch (state) {
    case "complete":
      return <CheckCircle size={18} weight="fill" aria-hidden="true" />;
    case "offline":
      return <Warning size={18} weight="fill" aria-hidden="true" />;
    case "replaying":
      return <ArrowCounterClockwise size={18} aria-hidden="true" />;
    case "live":
      return <Pulse size={18} aria-hidden="true" />;
  }
}

function creditImpactLabel(copy: Copy, impact: CreditImpact): string {
  if (impact.kind === "measured" && impact.value) {
    return `${copy.credit.measured}: ${impact.value}`;
  }
  return copy.credit[impact.kind];
}

function outputEventDetail(event: V6VersionedEvent): string | undefined {
  for (const key of [
    "path",
    "folder_path",
    "directory",
    "note_id",
    "relation_id",
    "export_id",
    "package_manifest_id",
    "document_id",
  ]) {
    const value = event.payload[key];
    if (typeof value === "string" && value.trim().length > 0) return value;
  }
  return event.document_id;
}

function formatInteger(locale: V6ProductLocale, value: number): string {
  return new Intl.NumberFormat(locale === "ko" ? "ko-KR" : "en-US", {
    maximumFractionDigits: 0,
  }).format(value);
}

function formatMeasured(
  locale: V6ProductLocale,
  value: number | null,
  maximumFractionDigits: number,
  fallback: string,
): string {
  if (value === null) return fallback;
  return new Intl.NumberFormat(locale === "ko" ? "ko-KR" : "en-US", {
    maximumFractionDigits,
  }).format(value);
}

function formatDateTime(locale: V6ProductLocale, value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(locale === "ko" ? "ko-KR" : "en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}
