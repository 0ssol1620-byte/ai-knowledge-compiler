"use client";

import {
  ArrowClockwise,
  CheckCircle,
  ClockCounterClockwise,
  FileLock,
  Gavel,
  ShieldCheck,
  Warning,
  Wrench,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { IntegrityDecisionPanel } from "@/components/integrity-decision-panel";
import {
  getCollectionIntegrityDecisions,
  getCollectionIntegrityFindings,
  type CollectionIntegrityDecision,
  type CollectionIntegrityFinding,
} from "@/lib/collection-integrity-client";
import {
  getCollectionEvents,
  getCollectionIntegrity,
  type CollectionEvent,
  type CollectionIntegritySummary,
} from "@/lib/collection-runtime-client";
import { formatLocaleNumber, type StructaraLocale } from "@/lib/locale";

type IntegrityStatus =
  | "verified"
  | "authority_verified"
  | "auto_repaired"
  | "reprocessing"
  | "warning"
  | "unresolved"
  | "quarantined";

type IntegrityItem = {
  id: string;
  status: IntegrityStatus;
  title: string;
  source: string;
  page: number | null;
  category: string;
  summary: string;
  attempts: Array<{
    label: string;
    result: string;
    evidence: string;
  }>;
  finding?: CollectionIntegrityFinding;
};

const STATUS_ORDER: IntegrityStatus[] = [
  "unresolved",
  "quarantined",
  "reprocessing",
  "warning",
  "auto_repaired",
  "authority_verified",
  "verified",
];

const ITEMS: IntegrityItem[] = [
  {
    id: "integrity-unresolved-header",
    status: "unresolved",
    title: "Merged header meaning",
    source: "annual-report.pdf",
    page: 42,
    category: "table_structure",
    summary:
      "Two plausible header spans remain after automatic structure and visual-route comparison.",
    attempts: [
      {
        label: "Source-native structure",
        result: "No complete header tree",
        evidence: "Tagged cells do not cover the second header band.",
      },
      {
        label: "Table boundary recovery",
        result: "Two valid candidates",
        evidence: "Both candidates preserve all numeric cells.",
      },
      {
        label: "Cross-page consistency",
        result: "No decisive match",
        evidence: "Adjacent tables use a different reporting period.",
      },
    ],
  },
  {
    id: "integrity-quarantined-object",
    status: "quarantined",
    title: "Embedded object payload",
    source: "operations-manual.docx",
    page: 18,
    category: "unsafe_embedded_content",
    summary:
      "The embedded object is isolated and excluded from compilation pending an explicit source decision.",
    attempts: [
      {
        label: "Container safety scan",
        result: "Object isolated",
        evidence:
          "The main document remains readable without opening the object.",
      },
      {
        label: "Safe text extraction",
        result: "No trusted text returned",
        evidence: "The isolated payload was not executed.",
      },
    ],
  },
  {
    id: "integrity-reprocessing-table",
    status: "reprocessing",
    title: "Approved table recovery",
    source: "supplier-ledger.pdf",
    page: 74,
    category: "table_structure",
    summary:
      "A bounded approved-engine retry is running while the previous output remains isolated.",
    attempts: [
      {
        label: "Previous candidates exhausted",
        result: "Output remains isolated",
        evidence: "The retry cannot replace any block before verification passes.",
      },
      {
        label: "Approved retry scheduled",
        result: "Reprocessing",
        evidence: "The immutable engine revision and evidence digest are recorded.",
      },
    ],
  },
  {
    id: "integrity-warning-footnote",
    status: "warning",
    title: "Ambiguous footnote anchor",
    source: "research-appendix.pdf",
    page: 9,
    category: "citation_linkage",
    summary:
      "The footnote text is preserved, but its nearest anchor crosses a column boundary.",
    attempts: [
      {
        label: "Reading-order recovery",
        result: "Footnote preserved",
        evidence: "Page geometry links the note to two adjacent claims.",
      },
      {
        label: "Reference pattern check",
        result: "Warning retained",
        evidence: "No unique superscript identifier exists in the source.",
      },
    ],
  },
  {
    id: "integrity-auto-row",
    status: "auto_repaired",
    title: "Continued table row",
    source: "supplier-ledger.pdf",
    page: 73,
    category: "row_omission",
    summary:
      "A row crossing a page boundary was restored automatically and tied to both source regions.",
    attempts: [
      {
        label: "Initial structure pass",
        result: "Continuation detected",
        evidence: "The row begins on page 72 and completes on page 73.",
      },
      {
        label: "Overlap recovery",
        result: "Row restored",
        evidence: "All cells reconcile with the following subtotal.",
      },
      {
        label: "Numeric invariant check",
        result: "Repair accepted",
        evidence: "Source total is unchanged after reconstruction.",
      },
    ],
  },
  {
    id: "integrity-authority-revenue",
    status: "authority_verified",
    title: "FY2025 revenue fact",
    source: "public-filing.html",
    page: 22,
    category: "numeric_fact",
    summary:
      "The extracted value matches the identified public filing fact and retains its authority reference.",
    attempts: [
      {
        label: "Source extraction",
        result: "Value and unit captured",
        evidence: "Original table cell and page region are linked.",
      },
      {
        label: "Authority comparison",
        result: "Exact fact match",
        evidence: "Entity, period, unit, and value agree with the filing fact.",
      },
    ],
  },
  {
    id: "integrity-verified-narrative",
    status: "verified",
    title: "Revenue narrative paragraph",
    source: "public-filing.html",
    page: 23,
    category: "text_fidelity",
    summary:
      "The compiled paragraph is source-linked and no integrity findings remain.",
    attempts: [
      {
        label: "Source extraction",
        result: "Text preserved",
        evidence: "Paragraph boundaries and source region are recorded.",
      },
      {
        label: "Structure validation",
        result: "Verified",
        evidence:
          "No missing text, duplicated lines, or unresolved flags detected.",
      },
    ],
  },
];

const COPY = {
  en: {
    eyebrow: "Integrity Console",
    title:
      "Automatic recovery first. Human decisions only where evidence stops.",
    intro:
      "Completed documents bypass this console. It opens only when the durable integrity ledger has something useful to explain or resolve.",
    sample: "Reference state · no live workspace connected",
    sampleBody:
      "The entries below demonstrate status semantics and interaction behavior. They are not customer results or production evidence.",
    live: "Live collection evidence",
    liveBody: "Counts come from GET /integrity; repair, quarantine, and decision history comes only from the durable collection event ledger.",
    noCollection: "No collection selected",
    noCollectionBody: "Open this console from a collection workspace. Reference data is available only with the explicit reference mode.",
    loading: "Loading authoritative integrity evidence…",
    loadError: "Integrity evidence could not be loaded.",
    refresh: "Retry",
    noFindings: "No repair, quarantine, verification, or customer-decision event is present in the durable ledger.",
    protectedSource: "Protected source reference",
    openFinding: "Open integrity finding",
    isolated: "Safely isolated for an optional customer decision",
    queue: "Integrity ledger",
    queueNote: "Risk and evidence state, not model confidence",
    item: "finding",
    items: "findings",
    selected: "Selected finding",
    source: "Source",
    page: "Page",
    category: "Category",
    status: "State",
    attempts: "Automatic attempt history",
    attemptsNote:
      "Attempts are shown in execution order and remain immutable after a human decision.",
    attempt: "Attempt",
    result: "Result",
    evidence: "Evidence",
    states: {
      verified: "Verified",
      authority_verified: "Authority verified",
      auto_repaired: "Auto-repaired",
      reprocessing: "Reprocessing",
      warning: "Warning",
      unresolved: "Unresolved",
      quarantined: "Quarantined",
    },
  },
  ko: {
    eyebrow: "무결성 콘솔",
    title: "자동 복구를 먼저 수행하고, 근거가 멈춘 곳만 사람이 판단합니다",
    intro:
      "문제가 없는 문서는 이 콘솔을 거치지 않습니다. 영구 무결성 원장에 설명하거나 해결할 항목이 있을 때만 열립니다.",
    sample: "참조 상태 · 실제 워크스페이스 미연결",
    sampleBody:
      "아래 항목은 상태 의미와 상호작용을 보여주는 예시입니다. 고객 결과나 운영 근거가 아닙니다.",
    live: "실제 컬렉션 근거",
    liveBody: "집계는 GET /integrity에서, 복구·격리·사용자 결정 이력은 영구 컬렉션 이벤트 원장에서만 가져옵니다.",
    noCollection: "선택한 컬렉션이 없습니다",
    noCollectionBody: "컬렉션 워크스페이스에서 이 콘솔을 여세요. 참조 데이터는 명시적인 참조 모드에서만 표시됩니다.",
    loading: "권위 있는 무결성 근거를 불러오는 중…",
    loadError: "무결성 근거를 불러오지 못했습니다.",
    refresh: "다시 시도",
    noFindings: "영구 원장에 복구, 격리, 검증 또는 사용자 결정 이벤트가 없습니다.",
    protectedSource: "보호된 출처 참조",
    openFinding: "미해결 무결성 항목",
    isolated: "선택적 고객 결정을 위해 안전하게 격리됨",
    queue: "무결성 원장",
    queueNote: "모델 신뢰도가 아닌 위험·근거 상태",
    item: "항목",
    items: "항목",
    selected: "선택한 항목",
    source: "출처",
    page: "페이지",
    category: "범주",
    status: "상태",
    attempts: "자동 시도 이력",
    attemptsNote:
      "시도는 실행 순서대로 표시되며 사람이 결정한 뒤에도 변경되지 않습니다.",
    attempt: "시도",
    result: "결과",
    evidence: "근거",
    states: {
      verified: "검증됨",
      authority_verified: "권위 출처 검증",
      auto_repaired: "자동 복구됨",
      reprocessing: "재처리 중",
      warning: "경고",
      unresolved: "미해결",
      quarantined: "격리됨",
    },
  },
} as const;

const statusIcon = {
  verified: CheckCircle,
  authority_verified: Gavel,
  auto_repaired: Wrench,
  reprocessing: ArrowClockwise,
  warning: Warning,
  unresolved: ClockCounterClockwise,
  quarantined: FileLock,
} as const;

const EVENT_PRESENTATIONS: Record<
  StructaraLocale,
  Partial<
    Record<CollectionEvent["event_type"], readonly [title: string, category: string]>
  >
> = {
  en: {
    "repair.started.v1": ["Automatic recovery started", "repair"],
    "repair.completed.v1": ["Automatic recovery completed", "repair"],
    "output.quarantined.v1": ["Output safely quarantined", "quarantine"],
    "verification.failed.v1": ["Verification remains unresolved", "verification"],
    "numeric.authority.verified.v1": [
      "Authority value verified",
      "numeric authority",
    ],
    "package.validated.v1": ["Knowledge package validated", "package"],
    "integrity.decision.recorded.v1": ["Customer decision recorded", "decision"],
  },
  ko: {
    "repair.started.v1": ["자동 복구 시작", "복구"],
    "repair.completed.v1": ["자동 복구 완료", "복구"],
    "output.quarantined.v1": ["산출물 안전 격리", "격리"],
    "verification.failed.v1": ["검증 미해결", "검증"],
    "numeric.authority.verified.v1": ["권위 값 검증", "수치 권위"],
    "package.validated.v1": ["지식 패키지 검증", "패키지"],
    "integrity.decision.recorded.v1": ["고객 결정 기록", "결정"],
  },
};

const SAFE_PAYLOAD_EVIDENCE_KEYS = new Set([
  "action",
  "attempt_number",
  "billable_pages",
  "block_count",
  "collection_id",
  "decision_id",
  "error_code",
  "evidence_bound",
  "evidence_reference_kind",
  "manifest_verified",
  "page_number",
  "processing_job_id",
  "reason_code",
  "repair_code",
  "result_status",
  "route",
  "status",
  "table_count",
  "target_type",
  "task_count",
  "unbillable_pages",
  "verified_facts",
]);

export function IntegrityConsole({
  locale,
  collectionId,
  reference = false,
}: {
  locale: StructaraLocale;
  collectionId?: string;
  reference?: boolean;
}) {
  const copy = COPY[locale];
  const live = !reference && Boolean(collectionId);
  const [selectedId, setSelectedId] = useState(reference ? ITEMS[0]!.id : "");
  const [integrity, setIntegrity] = useState<CollectionIntegritySummary>();
  const [events, setEvents] = useState<CollectionEvent[]>([]);
  const [findings, setFindings] = useState<CollectionIntegrityFinding[]>([]);
  const [decisions, setDecisions] = useState<CollectionIntegrityDecision[]>([]);
  const [loading, setLoading] = useState(live);
  const [loadError, setLoadError] = useState<string>();
  const [refreshAttempt, setRefreshAttempt] = useState(0);

  useEffect(() => {
    if (!live || !collectionId) return;
    const activeCollectionId = collectionId;
    const controller = new AbortController();
    let active = true;
    async function refresh(initial: boolean) {
      if (initial) setLoading(true);
      try {
        const [nextIntegrity, nextEvents, nextFindings, nextDecisions] = await Promise.all([
          getCollectionIntegrity(activeCollectionId, controller.signal),
          getCollectionEvents(activeCollectionId, 0, controller.signal),
          getCollectionIntegrityFindings(activeCollectionId, controller.signal),
          getCollectionIntegrityDecisions(activeCollectionId, controller.signal),
        ]);
        if (!active) return;
        setIntegrity(nextIntegrity);
        setEvents(nextEvents.events);
        setFindings(nextFindings.items);
        setDecisions(nextDecisions.items);
        setLoadError(undefined);
      } catch (error) {
        if (!active || controller.signal.aborted) return;
        setLoadError(error instanceof Error ? error.message : copy.loadError);
      } finally {
        if (active) setLoading(false);
      }
    }
    void refresh(true);
    const interval = window.setInterval(() => void refresh(false), 5_000);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(interval);
    };
  }, [collectionId, copy.loadError, live, refreshAttempt]);

  const items = useMemo(
    () =>
      reference
        ? ITEMS
        : [
            ...integrityItemsFromFindings(findings, {
              openFinding: copy.openFinding,
              protectedSource: copy.protectedSource,
              isolated: copy.isolated,
            }),
            ...integrityItemsFromEvents(events, copy.protectedSource, locale),
          ],
    [
      copy.isolated,
      copy.openFinding,
      copy.protectedSource,
      events,
      findings,
      locale,
      reference,
    ],
  );
  const sorted = useMemo(
    () =>
      [...items].sort(
        (left, right) =>
          STATUS_ORDER.indexOf(left.status) -
          STATUS_ORDER.indexOf(right.status),
      ),
    [items],
  );
  const selected = sorted.find((item) => item.id === selectedId) ?? sorted[0];
  const SelectedIcon = selected ? statusIcon[selected.status] : ShieldCheck;
  const counts = useMemo(
    () =>
      reference
        ? Object.fromEntries(
            STATUS_ORDER.map((status) => [
              status,
              ITEMS.filter((item) => item.status === status).length,
            ]),
          ) as Record<IntegrityStatus, number>
        : liveIntegrityCounts(integrity, sorted),
    [integrity, reference, sorted],
  );

  return (
    <div className="integrity-console-page" data-locale={locale}>
      <header className="integrity-console-heading">
        <div>
          <p>{copy.eyebrow}</p>
          <h1>{copy.title}</h1>
          <span>{copy.intro}</span>
        </div>
        <aside>
          <ShieldCheck size={20} weight="duotone" aria-hidden="true" />
          <span>
            <strong>
              {reference ? copy.sample : live ? copy.live : copy.noCollection}
            </strong>
            <small>
              {reference
                ? copy.sampleBody
                : live
                  ? copy.liveBody
                  : copy.noCollectionBody}
            </small>
            {live && integrity && (
              <code title={integrity.integrity_sha256}>
                {integrity.collection_status} · {integrity.integrity_sha256}
              </code>
            )}
          </span>
        </aside>
      </header>

      {loading && (
        <p className="integrity-live-state" role="status">
          {copy.loading}
        </p>
      )}
      {loadError && (
        <div className="integrity-live-state" role="alert">
          <span>{copy.loadError} {loadError}</span>
          <button type="button" onClick={() => setRefreshAttempt((value) => value + 1)}>
            <ArrowClockwise size={15} aria-hidden="true" />
            {copy.refresh}
          </button>
        </div>
      )}

      <section className="integrity-status-register" aria-label={copy.status}>
        {STATUS_ORDER.map((status) => {
          const Icon = statusIcon[status];
          const count = counts[status];
          return (
            <div key={status} data-status={status}>
              <Icon size={18} aria-hidden="true" />
              <span>
                <strong>{copy.states[status]}</strong>
                <code>{status}</code>
              </span>
              <b>{formatLocaleNumber(locale, count)}</b>
            </div>
          );
        })}
      </section>

      <div className="integrity-console-layout">
        <section
          className="integrity-queue"
          aria-labelledby="integrity-queue-title"
        >
          <header>
            <div>
              <h2 id="integrity-queue-title">{copy.queue}</h2>
              <p>{copy.queueNote}</p>
            </div>
            <span>
              {formatLocaleNumber(locale, sorted.length)}{" "}
              {sorted.length === 1 ? copy.item : copy.items}
            </span>
          </header>
          {sorted.length === 0 ? (
            <p className="integrity-live-empty">{copy.noFindings}</p>
          ) : (
            <ul className="integrity-queue-list">
              {sorted.map((item) => {
              const Icon = statusIcon[item.status];
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    data-status={item.status}
                    aria-current={selected?.id === item.id ? "true" : undefined}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <Icon size={18} aria-hidden="true" />
                    <span>
                      <strong>{item.title}</strong>
                      <small>
                        {item.source}
                        {item.page === null ? "" : ` · ${copy.page} ${item.page}`}
                      </small>
                    </span>
                    <em>{copy.states[item.status]}</em>
                  </button>
                </li>
              );
              })}
            </ul>
          )}
        </section>

        <section
          className="integrity-inspector"
          aria-labelledby="integrity-selected-title"
        >
          {selected ? (
            <>
              <header>
                <p>{copy.selected}</p>
                <div>
                  <SelectedIcon size={22} aria-hidden="true" />
                  <h2 id="integrity-selected-title">{selected.title}</h2>
                </div>
                <span data-status={selected.status}>
                  {copy.states[selected.status]}
                </span>
              </header>
              <p className="integrity-summary">{selected.summary}</p>
              <dl className="integrity-finding-meta">
            <div>
              <dt>{copy.source}</dt>
              <dd>{selected.source}</dd>
            </div>
            <div>
              <dt>{copy.page}</dt>
              <dd>
                {selected.page === null
                  ? "—"
                  : formatLocaleNumber(locale, selected.page)}
              </dd>
            </div>
            <div>
              <dt>{copy.category}</dt>
              <dd>
                <code>{selected.category}</code>
              </dd>
            </div>
            <div>
              <dt>{copy.status}</dt>
              <dd>
                <code>{selected.status}</code>
              </dd>
            </div>
              </dl>

              <section
                className="integrity-attempts"
                aria-labelledby="integrity-attempts-title"
              >
            <header>
              <div>
                <h3 id="integrity-attempts-title">{copy.attempts}</h3>
                <p>{copy.attemptsNote}</p>
              </div>
              <ClockCounterClockwise size={20} aria-hidden="true" />
            </header>
            <ol>
              {selected.attempts.map((attempt, index) => (
                <li key={attempt.label}>
                  <span>{formatLocaleNumber(locale, index + 1)}</span>
                  <div>
                    <strong>{attempt.label}</strong>
                    <dl>
                      <div>
                        <dt>{copy.result}</dt>
                        <dd>{attempt.result}</dd>
                      </div>
                      <div>
                        <dt>{copy.evidence}</dt>
                        <dd>{attempt.evidence}</dd>
                      </div>
                    </dl>
                  </div>
                </li>
              ))}
            </ol>
              </section>

              <IntegrityDecisionPanel
                locale={locale}
                collectionId={live ? collectionId : undefined}
                finding={selected.finding}
                decisions={decisions}
                onCommitted={(decision) => {
                  setDecisions((current) => [
                    decision,
                    ...current.filter((item) => item.id !== decision.id),
                  ]);
                  setFindings((current) =>
                    current.filter(
                      (item) =>
                        item.target_type !== decision.target_type ||
                        item.target_id !== decision.target_id,
                    ),
                  );
                  setSelectedId("");
                }}
              />
            </>
          ) : (
            <div className="integrity-inspector-empty">
              <ShieldCheck size={28} aria-hidden="true" />
              <h2 id="integrity-selected-title">{copy.noFindings}</h2>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function integrityItemsFromFindings(
  findings: readonly CollectionIntegrityFinding[],
  copy: {
    openFinding: string;
    protectedSource: string;
    isolated: string;
  },
): IntegrityItem[] {
  return findings.map((finding) => ({
    id: `finding:${finding.target_type}:${finding.target_id}`,
    status:
      finding.target_type === "quarantine_item" ? "quarantined" : "unresolved",
    title: `${copy.openFinding} · ${finding.category}`,
    source: copy.protectedSource,
    page: null,
    category: finding.category,
    summary: `${finding.reason_code} · ${finding.severity}`,
    attempts: [
      {
        label: copy.isolated,
        result: finding.status,
        evidence: `${finding.target_type} · ${finding.reason_code}`,
      },
    ],
    finding,
  }));
}

function integrityItemsFromEvents(
  events: readonly CollectionEvent[],
  protectedSource: string,
  locale: StructaraLocale,
): IntegrityItem[] {
  return events.flatMap((event) => {
    const status = integrityEventStatus(event);
    if (!status) return [];
    const page = firstPayloadNumber(event.payload, ["page_number", "page"]);
    const presentation = eventPresentation(locale, event.event_type);
    return [
      {
        id: event.event_id,
        status,
        title: presentation.title,
        source: protectedSource,
        page,
        category: presentation.category,
        summary: `${presentation.ledger} #${event.sequence} · ${event.timestamp}`,
        attempts: [
          {
            label: event.event_type,
            result: status,
            evidence: safePayloadEvidence(event.payload),
          },
        ],
      },
    ];
  });
}

function integrityEventStatus(event: CollectionEvent): IntegrityStatus | undefined {
  const eventType = event.event_type;
  if (eventType === "repair.completed.v1") return "auto_repaired";
  if (eventType === "repair.started.v1") return "reprocessing";
  if (eventType === "output.quarantined.v1") return "quarantined";
  if (eventType === "verification.failed.v1") return "unresolved";
  if (eventType === "numeric.authority.verified.v1") {
    return "authority_verified";
  }
  if (eventType === "package.validated.v1") return "verified";
  if (
    eventType.startsWith("customer.decision.") ||
    eventType.startsWith("integrity.decision.") ||
    eventType.startsWith("review.decision.")
  ) {
    return event.payload.result_status === "retrying"
      ? "reprocessing"
      : "verified";
  }
  return undefined;
}

function liveIntegrityCounts(
  integrity: CollectionIntegritySummary | undefined,
  items: readonly IntegrityItem[],
): Record<IntegrityStatus, number> {
  const verification = integrity?.verification_status_counts ?? {};
  const authority = integrity?.authority_mapping_status_counts ?? {};
  return {
    verified: verification.verified ?? 0,
    authority_verified:
      (authority.authority_verified ?? 0) +
      (authority.verified ?? 0) +
      (authority.matched ?? 0),
    auto_repaired: items.filter((item) => item.status === "auto_repaired").length,
    reprocessing: items.filter((item) => item.status === "reprocessing").length,
    warning: verification.warning ?? 0,
    unresolved:
      (verification.unresolved ?? 0) + (verification.rejected ?? 0),
    quarantined: verification.quarantined ?? 0,
  };
}

function eventPresentation(
  locale: StructaraLocale,
  eventType: CollectionEvent["event_type"],
): { title: string; category: string; ledger: string } {
  const match = EVENT_PRESENTATIONS[locale][eventType];
  return {
    title: match?.[0] ?? eventType,
    category: match?.[1] ?? eventType.split(".").slice(0, -1).join("."),
    ledger: locale === "ko" ? "영구 원장 이벤트" : "Durable ledger event",
  };
}

function firstPayloadNumber(
  payload: Record<string, unknown>,
  keys: readonly string[],
): number | null {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "number" && Number.isInteger(value) && value >= 0) {
      return value;
    }
  }
  return null;
}

function safePayloadEvidence(payload: Record<string, unknown>): string {
  const safe = Object.fromEntries(
    Object.entries(payload)
      .filter(([key, value]) => {
        return (
          SAFE_PAYLOAD_EVIDENCE_KEYS.has(key) &&
          ["string", "number", "boolean"].includes(typeof value)
        );
      })
      .sort(([left], [right]) => left.localeCompare(right))
      .slice(0, 8),
  );
  return Object.keys(safe).length > 0
    ? JSON.stringify(safe)
    : "No scalar evidence fields were present in this event payload.";
}
