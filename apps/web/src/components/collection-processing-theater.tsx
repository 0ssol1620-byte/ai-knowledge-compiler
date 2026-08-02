"use client";

import {
  ArrowClockwise,
  Check,
  Clock,
  Database,
  Pause,
  Play,
  ShieldCheck,
  Warning,
  WifiHigh,
  WifiSlash,
} from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  ParallelProcessingTheater,
  type V6ConnectionState,
} from "@/components/v6";
import {
  CollectionSseUnavailableError,
  controlCollectionProcessing,
  getCollectionEvents,
  restoreCollectionProcessing,
  retryCollectionProcessing,
  streamCollectionEvents,
  type CollectionEvent,
  type CollectionEventSnapshot,
  type CollectionProcessingRun,
  type CollectionState,
} from "@/lib/collection-runtime-client";
import {
  collectionEventStage,
  localizedProcessingStageLabel,
  PROCESSING_EVENT_BATCH_MS,
  PROCESSING_THEATER_STAGES,
  type ProcessingTheaterStageId,
} from "@/lib/processing-theater";
import { formatLocaleNumber, type StructaraLocale } from "@/lib/locale";
import {
  collectionEventsToV6,
  hasV6ParallelEvidence,
  v6ReplayBaseline,
} from "@/lib/v6-collection-events";

type ConnectionState = "connecting" | "live" | "polling" | "reconnecting";
type TheaterMobileTab =
  "progress" | "source" | "result" | "knowledge" | "integrity";

export function CollectionProcessingTheater({
  collectionId,
  locale,
  live = true,
  initialSnapshot,
  initialRun,
  initialEvents = [],
  initialError,
}: {
  collectionId: string;
  locale: StructaraLocale;
  live?: boolean;
  initialSnapshot?: CollectionEventSnapshot;
  initialRun?: CollectionProcessingRun;
  initialEvents?: CollectionEvent[];
  initialError?: string;
}) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [run, setRun] = useState(initialRun);
  const [events, setEvents] = useState<CollectionEvent[]>(initialEvents);
  const [connection, setConnection] = useState<ConnectionState>(
    live ? "connecting" : "polling",
  );
  const [error, setError] = useState<string | undefined>(initialError);
  const [controlling, setControlling] = useState(false);
  const [retryHardCap, setRetryHardCap] = useState("");
  const [mobileTabsActive, setMobileTabsActive] = useState(false);
  const [mobileTab, setMobileTab] = useState<TheaterMobileTab>("progress");
  const eventBuffer = useRef<CollectionEvent[]>([]);
  const sequence = useRef(
    Math.max(
      initialSnapshot?.latest_sequence ?? 0,
      ...initialEvents.map((item) => item.sequence),
    ),
  );
  const terminal = snapshot ? terminalCollectionState(snapshot.status) : false;

  const mergeEvents = useCallback((incoming: readonly CollectionEvent[]) => {
    if (incoming.length === 0) return;
    setEvents((current) => {
      const bySequence = new Map(current.map((item) => [item.sequence, item]));
      for (const event of incoming) bySequence.set(event.sequence, event);
      const ordered = [...bySequence.values()].sort(
        (left, right) => left.sequence - right.sequence,
      );
      return ordered.slice(-1_000);
    });
    const latest = incoming.reduce((left, right) =>
      left.sequence > right.sequence ? left : right,
    );
    sequence.current = Math.max(sequence.current, latest.sequence);
  }, []);

  const reconcile = useCallback(
    async (signal?: AbortSignal) => {
      const response = await getCollectionEvents(
        collectionId,
        sequence.current,
        signal,
      );
      if (response.next_sequence < sequence.current) {
        throw new Error("The collection event cursor moved backwards.");
      }
      setSnapshot(response.snapshot);
      mergeEvents(response.events);
      setError(undefined);
    },
    [collectionId, mergeEvents],
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(max-width: 760px)");
    const update = () => setMobileTabsActive(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      const batch = eventBuffer.current.splice(0);
      mergeEvents(batch);
    }, PROCESSING_EVENT_BATCH_MS);
    return () => window.clearInterval(interval);
  }, [mergeEvents]);

  useEffect(() => {
    if (!live) return;
    const controller = new AbortController();
    void Promise.all([
      reconcile(controller.signal),
      restoreCollectionProcessing(collectionId).then(setRun),
    ]).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      setError(
        reason instanceof Error
          ? reason.message
          : "Processing state could not be loaded.",
      );
    });
    return () => controller.abort();
  }, [collectionId, live, reconcile]);

  useEffect(() => {
    if (!live || terminal) return;
    const controller = new AbortController();
    const interval = window.setInterval(() => {
      void reconcile(controller.signal).catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            reason instanceof Error ? reason.message : "Event replay failed.",
          );
        }
      });
    }, 5_000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [collectionId, live, reconcile, terminal]);

  useEffect(() => {
    if (!live || terminal) return;
    const controller = new AbortController();
    void streamCollectionEvents(
      {
        collectionId,
        afterSequence: sequence.current,
        signal: controller.signal,
      },
      {
        onConnection: setConnection,
        onSnapshot: setSnapshot,
        onEvent(event) {
          eventBuffer.current.push(event);
        },
      },
    ).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      setConnection(
        reason instanceof CollectionSseUnavailableError
          ? "polling"
          : "reconnecting",
      );
    });
    return () => controller.abort();
  }, [collectionId, live, terminal]);

  const copy = COPY[locale];
  const paused = snapshot?.status === "PAUSED" || run?.status === "paused";
  const activeJobId = snapshot?.processing_job_id ?? run?.job_id ?? null;
  const correlatedEvents = useMemo(
    () =>
      events.filter(
        (event) =>
          event.job_id === null ||
          activeJobId === null ||
          event.job_id === activeJobId,
      ),
    [activeJobId, events],
  );
  const v6Events = useMemo(
    () => collectionEventsToV6(correlatedEvents, activeJobId),
    [activeJobId, correlatedEvents],
  );
  const parallelEvidenceAvailable = hasV6ParallelEvidence(v6Events);
  const v6Connection: V6ConnectionState = terminal
    ? "complete"
    : error
      ? "offline"
      : connection === "live"
        ? "live"
        : "replaying";
  const stages = useMemo(
    () => processingStages(snapshot?.status, correlatedEvents),
    [correlatedEvents, snapshot?.status],
  );
  const correlatedJobs = [
    ...new Set(events.flatMap((event) => (event.job_id ? [event.job_id] : []))),
  ];
  const measuredTaskTotal =
    snapshot !== undefined ? snapshot.total_tasks : run?.task_counts.total;
  const pageIntelligenceEvents = useMemo(
    () =>
      correlatedEvents.filter((event) =>
        [
          "preflight.cluster.created.v1",
          "estimate.sample.updated.v1",
          "estimate.final.ready.v1",
          "page.route.selected.v1",
          "region.route.selected.v1",
        ].includes(event.event_type),
      ),
    [correlatedEvents],
  );
  const sourceTransformationEvents = useMemo(
    () =>
      correlatedEvents.filter((event) =>
        [
          "page.route.selected.v1",
          "region.route.selected.v1",
          "block.completed.v1",
          "table.reconstructed.v1",
          "repair.started.v1",
          "repair.completed.v1",
        ].includes(event.event_type),
      ),
    [correlatedEvents],
  );
  const knowledgeFormationEvents = useMemo(
    () =>
      correlatedEvents.filter((event) =>
        [
          "note.created.v1",
          "entity.resolved.v1",
          "relation.created.v1",
          "architecture.plan.created.v1",
          "architecture.folder.created.v1",
          "architecture.moc.created.v1",
          "architecture.plan.compiled.v1",
          "export.started.v1",
          "export.ready.v1",
          "package.validated.v1",
          "package.signed.v1",
        ].includes(event.event_type),
      ),
    [correlatedEvents],
  );
  const integrityEvents = useMemo(
    () =>
      correlatedEvents.filter((event) =>
        [
          "verification.failed.v1",
          "repair.started.v1",
          "repair.completed.v1",
          "output.quarantined.v1",
          "numeric.authority.verified.v1",
          "package.validated.v1",
        ].includes(event.event_type),
      ),
    [correlatedEvents],
  );
  const latestProcessingFailure = [...correlatedEvents]
    .reverse()
    .find((event) => event.event_type === "processing.failed.v1");
  const retryRequiresHigherCap =
    latestProcessingFailure?.payload.error_code === "CREDIT_HARD_CAP_REACHED";
  const retryRequiresCreditTopUp =
    latestProcessingFailure?.payload.error_code ===
    "INSUFFICIENT_CREDITS_FOR_OVERAGE";
  const currentHardCap = Number(
    run?.hard_cap_credits ?? snapshot?.credit_hard_cap ?? 0,
  );
  const proposedHardCap = Number(retryHardCap);
  const retryHardCapValid =
    !retryRequiresHigherCap ||
    (retryHardCap.trim().length > 0 &&
      Number.isFinite(proposedHardCap) &&
      proposedHardCap > currentHardCap);
  const processingControlAvailable =
    (snapshot?.status === "PROCESSING" &&
      snapshot.processing_status === "running") ||
    (snapshot?.status === "PAUSED" &&
      snapshot.processing_status === "paused");

  async function toggleProcessing(): Promise<void> {
    if (!run || controlling) return;
    setControlling(true);
    setError(undefined);
    try {
      const controlled = await controlCollectionProcessing(
        collectionId,
        paused ? "resume" : "pause",
      );
      setRun(controlled);
      await reconcile();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : copy.controlError);
    } finally {
      setControlling(false);
    }
  }

  async function retryProcessing(): Promise<void> {
    if (controlling) return;
    setControlling(true);
    setError(undefined);
    try {
      const recovered = await retryCollectionProcessing(
        collectionId,
        retryRequiresHigherCap ? retryHardCap : undefined,
      );
      setRun(recovered);
      await reconcile();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : copy.retryError);
    } finally {
      setControlling(false);
    }
  }

  function selectMobileTab(
    event: React.KeyboardEvent<HTMLButtonElement>,
    current: TheaterMobileTab,
  ): void {
    const order: TheaterMobileTab[] = [
      "progress",
      "source",
      "result",
      "knowledge",
      "integrity",
    ];
    const currentIndex = order.indexOf(current);
    let nextIndex: number | undefined;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % order.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + order.length) % order.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = order.length - 1;
    }
    if (nextIndex === undefined) return;
    event.preventDefault();
    const next = order[nextIndex]!;
    setMobileTab(next);
    requestAnimationFrame(() => {
      document.getElementById(`collection-mobile-tab-${next}`)?.focus();
    });
  }

  return (
    <div className="collection-theater" data-locale={locale}>
      <header className="collection-theater-header">
        <div>
          <p>{copy.eyebrow}</p>
          <h1>{copy.title}</h1>
          <span>{copy.intro}</span>
        </div>
        <div className="collection-theater-header-actions">
          <span className="collection-connection" data-state={connection}>
            {connection === "live" ? (
              <WifiHigh size={16} weight="fill" aria-hidden="true" />
            ) : (
              <WifiSlash size={16} aria-hidden="true" />
            )}
            {copy.connection[connection]}
          </span>
          <button
            type="button"
            className="secondary-button compact"
            disabled={
              !run || !processingControlAvailable || terminal || controlling
            }
            onClick={() => void toggleProcessing()}
          >
            {paused ? (
              <Play size={16} aria-hidden="true" />
            ) : (
              <Pause size={16} aria-hidden="true" />
            )}
            {controlling ? copy.applying : paused ? copy.resume : copy.pause}
          </button>
        </div>
      </header>

      <section className="collection-theater-summary" aria-live="polite">
        <div>
          <small>{copy.collection}</small>
          <code>{collectionId}</code>
        </div>
        <div>
          <small>{copy.state}</small>
          <strong>{snapshot?.status ?? copy.loading}</strong>
        </div>
        <div>
          <small>{copy.job}</small>
          <strong>
            {run?.job_id ?? correlatedJobs.at(-1) ?? copy.notAssigned}
          </strong>
        </div>
        <div>
          <small>{copy.tasks}</small>
          <strong>
            {measuredTaskTotal !== undefined
              ? formatLocaleNumber(locale, Math.max(0, measuredTaskTotal))
              : copy.notMeasured}
          </strong>
        </div>
      </section>

      {error && (
        <div className="collection-theater-error" role="alert">
          <Warning size={18} weight="fill" aria-hidden="true" />
          <span>{error}</span>
          <button type="button" onClick={() => void reconcile()}>
            <ArrowClockwise size={15} aria-hidden="true" />
            {copy.retry}
          </button>
        </div>
      )}

      {snapshot?.status === "FAILED_RETRYABLE" && (
        <section
          className="collection-recovery-callout"
          aria-labelledby="collection-recovery-title"
        >
          <div>
            <p>{copy.recoveryEyebrow}</p>
            <h2 id="collection-recovery-title">{copy.recoveryTitle}</h2>
            <span>
              {retryRequiresCreditTopUp
                ? copy.creditRecoveryBody
                : copy.recoveryBody}
            </span>
            {retryRequiresCreditTopUp && (
              <Link className="collection-recovery-credit-link" href="/usage">
                {copy.addCredits}
              </Link>
            )}
            {retryRequiresHigherCap && (
              <label
                className="collection-recovery-cap"
                htmlFor="collection-recovery-hard-cap"
              >
                <span>{copy.newHardCap}</span>
                <input
                  id="collection-recovery-hard-cap"
                  type="number"
                  inputMode="decimal"
                  min={Number.isFinite(currentHardCap) ? currentHardCap : 0}
                  step="0.01"
                  value={retryHardCap}
                  aria-label={copy.newHardCap}
                  aria-describedby="collection-recovery-cap-hint"
                  onChange={(event) => setRetryHardCap(event.target.value)}
                />
                <small id="collection-recovery-cap-hint">
                  {copy.hardCapHint(
                    String(run?.hard_cap_credits ?? snapshot.credit_hard_cap),
                  )}
                </small>
              </label>
            )}
          </div>
          <button
            type="button"
            className="primary-button compact"
            disabled={controlling || !retryHardCapValid}
            onClick={() => void retryProcessing()}
          >
            <ArrowClockwise size={16} aria-hidden="true" />
            {controlling
              ? copy.retrying
              : retryRequiresCreditTopUp
                ? copy.retryAfterCredits
                : copy.retryProcessing}
          </button>
        </section>
      )}

      {parallelEvidenceAvailable && (
        <ParallelProcessingTheater
          events={v6Events}
          locale={locale}
          connection={v6Connection}
          baselineSequence={v6ReplayBaseline(v6Events)}
        />
      )}

      <nav
        className="collection-theater-mobile-tabs"
        aria-label={copy.mobileViews}
        aria-hidden={!mobileTabsActive}
        role={mobileTabsActive ? "tablist" : undefined}
      >
        {(
          [
            "progress",
            "source",
            "result",
            "knowledge",
            "integrity",
          ] as TheaterMobileTab[]
        ).map((id) => (
          <button
            key={id}
            id={`collection-mobile-tab-${id}`}
            type="button"
            className={mobileTab === id ? "active" : undefined}
            role={mobileTabsActive ? "tab" : undefined}
            aria-selected={mobileTabsActive ? mobileTab === id : undefined}
            aria-controls={
              mobileTabsActive ? `collection-mobile-panel-${id}` : undefined
            }
            tabIndex={mobileTabsActive && mobileTab !== id ? -1 : 0}
            onKeyDown={(event) => selectMobileTab(event, id)}
            onClick={() => setMobileTab(id)}
          >
            {copy.mobileTabs[id]}
          </button>
        ))}
      </nav>

      <section
        id="collection-mobile-panel-progress"
        className={clsx(
          "collection-theater-stage-panel collection-theater-mobile-panel",
          mobileTab !== "progress" && "collection-theater-mobile-hidden",
        )}
        role={mobileTabsActive ? "tabpanel" : undefined}
        aria-labelledby={
          mobileTabsActive
            ? "collection-mobile-tab-progress"
            : "collection-stage-title"
        }
        hidden={mobileTabsActive && mobileTab !== "progress"}
      >
        <header>
          <div>
            <p>01</p>
            <h2 id="collection-stage-title">{copy.pipeline}</h2>
          </div>
          <span>
            <Clock size={16} aria-hidden="true" />
            {copy.persistedEvents(formatLocaleNumber(locale, events.length))}
          </span>
        </header>
        <ol className="collection-stage-track">
          {stages.map((stage, index) => (
            <li key={stage.id} data-state={stage.state}>
              <span className="collection-stage-marker">
                {stage.state === "complete" ? (
                  <Check size={14} weight="bold" aria-hidden="true" />
                ) : (
                  index + 1
                )}
              </span>
              <span>
                <strong>
                  {localizedProcessingStageLabel(stage.id, locale)}
                </strong>
                <small>{copy.stageState[stage.state]}</small>
              </span>
              <b aria-label={copy.eventCount(stage.eventCount)}>
                {formatLocaleNumber(locale, stage.eventCount)}
              </b>
            </li>
          ))}
        </ol>
      </section>

      <section
        className="collection-evidence-workbench"
        aria-label={copy.workbench}
      >
        <EvidencePanel
          eyebrow="01"
          title={copy.collectionIntelligence}
          description={copy.collectionIntelligenceBody}
          mobileTab="source"
          activeMobileTab={mobileTab}
          mobileTabsActive={mobileTabsActive}
        >
          {snapshot?.upload ? (
            <dl className="collection-evidence-register">
              <EvidenceFact
                label={copy.uploadState}
                value={snapshot.upload.status}
              />
              <EvidenceFact
                label={copy.totalFiles}
                value={snapshot.upload.total_files}
              />
              <EvidenceFact
                label={copy.completedFiles}
                value={snapshot.upload.completed_files}
              />
              <EvidenceFact
                label={copy.duplicateFiles}
                value={snapshot.upload.duplicate_files}
              />
              <EvidenceFact
                label={copy.failedFiles}
                value={snapshot.upload.failed_files}
              />
              <EvidenceFact
                label={copy.manifestHash}
                value={snapshot.upload.source_manifest_hash}
                mono
              />
            </dl>
          ) : (
            <UnavailableEvidence>{copy.unavailable}</UnavailableEvidence>
          )}
          <EvidenceEventList
            events={pageIntelligenceEvents}
            unavailable={copy.pageEvidenceUnavailable}
          />
        </EvidencePanel>

        <EvidencePanel
          eyebrow="02"
          title={copy.sourceTransformation}
          description={copy.sourceTransformationBody}
          mobileTab="result"
          activeMobileTab={mobileTab}
          mobileTabsActive={mobileTabsActive}
        >
          <EvidenceEventList
            events={sourceTransformationEvents}
            unavailable={copy.unavailable}
          />
        </EvidencePanel>

        <EvidencePanel
          eyebrow="03"
          title={copy.knowledgeFormation}
          description={copy.knowledgeFormationBody}
          mobileTab="knowledge"
          activeMobileTab={mobileTab}
          mobileTabsActive={mobileTabsActive}
        >
          <EvidenceEventList
            events={knowledgeFormationEvents}
            unavailable={copy.unavailable}
          />
        </EvidencePanel>
      </section>

      <section
        id="collection-mobile-panel-integrity"
        className={clsx(
          "collection-integrity-preview collection-theater-mobile-panel",
          mobileTab !== "integrity" && "collection-theater-mobile-hidden",
        )}
        role={mobileTabsActive ? "tabpanel" : undefined}
        aria-labelledby={
          mobileTabsActive
            ? "collection-mobile-tab-integrity"
            : "collection-integrity-preview-title"
        }
        hidden={mobileTabsActive && mobileTab !== "integrity"}
      >
        <header>
          <div>
            <p>04</p>
            <h2 id="collection-integrity-preview-title">
              {copy.integrityEvidence}
            </h2>
          </div>
          <Link href={`/integrity?collection=${collectionId}`}>
            {copy.integrity}
          </Link>
        </header>
        <EvidenceEventList
          events={integrityEvents}
          unavailable={copy.unavailable}
        />
      </section>

      <div className="collection-theater-grid">
        <section
          className={clsx(
            "collection-theater-mobile-panel",
            mobileTab !== "progress" && "collection-theater-mobile-hidden",
          )}
          aria-labelledby="collection-credit-title"
        >
          <header>
            <p>02</p>
            <h2 id="collection-credit-title">{copy.credits}</h2>
          </header>
          <dl className="collection-credit-ledger">
            <Credit label={copy.reserved} value={run?.credits_reserved} />
            <Credit label={copy.consumed} value={run?.credits_consumed} />
            <Credit label={copy.refunded} value={run?.credits_refunded} />
            <Credit label={copy.released} value={run?.credits_released} />
            <Credit label={copy.hardCap} value={run?.hard_cap_credits} />
          </dl>
          <p className="collection-policy-note">
            <ShieldCheck size={16} weight="fill" aria-hidden="true" />
            {run?.overage_policy ?? copy.policyPending}
          </p>
        </section>

        <section
          className={clsx(
            "collection-theater-mobile-panel",
            mobileTab !== "integrity" && "collection-theater-mobile-hidden",
          )}
          aria-labelledby="collection-event-title"
        >
          <header>
            <p>03</p>
            <h2 id="collection-event-title">{copy.evidence}</h2>
          </header>
          {events.length === 0 ? (
            <p className="collection-event-empty">{copy.noEvents}</p>
          ) : (
            <ol className="collection-event-ledger">
              {events
                .slice(-20)
                .reverse()
                .map((event) => (
                  <li key={event.event_id}>
                    <Database size={15} aria-hidden="true" />
                    <span>
                      <strong>{event.event_type}</strong>
                      <small>
                        #{event.sequence} ·{" "}
                        {formatTimestamp(event.timestamp, locale)}
                      </small>
                    </span>
                    {event.job_id && <code>{event.job_id}</code>}
                  </li>
                ))}
            </ol>
          )}
        </section>
      </div>

      <footer className="collection-theater-footer">
        <Link href={`/integrity?collection=${collectionId}`}>
          {copy.integrity}
        </Link>
        <Link href={`/knowledge-bases?collection=${collectionId}`}>
          {copy.knowledge}
        </Link>
      </footer>
    </div>
  );
}

function EvidencePanel({
  eyebrow,
  title,
  description,
  mobileTab,
  activeMobileTab,
  mobileTabsActive,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  mobileTab: TheaterMobileTab;
  activeMobileTab: TheaterMobileTab;
  mobileTabsActive: boolean;
  children: ReactNode;
}) {
  return (
    <article
      id={`collection-mobile-panel-${mobileTab}`}
      className={clsx(
        "collection-evidence-panel collection-theater-mobile-panel",
        activeMobileTab !== mobileTab && "collection-theater-mobile-hidden",
      )}
      role={mobileTabsActive ? "tabpanel" : undefined}
      aria-labelledby={
        mobileTabsActive ? `collection-mobile-tab-${mobileTab}` : undefined
      }
      hidden={mobileTabsActive && activeMobileTab !== mobileTab}
    >
      <header>
        <p>{eyebrow}</p>
        <h2>{title}</h2>
        <span>{description}</span>
      </header>
      {children}
    </article>
  );
}

function EvidenceFact({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | number;
  mono?: boolean;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{mono ? <code title={String(value)}>{value}</code> : value}</dd>
    </div>
  );
}

function EvidenceEventList({
  events,
  unavailable,
}: {
  events: readonly CollectionEvent[];
  unavailable: string;
}) {
  if (events.length === 0) {
    return <UnavailableEvidence>{unavailable}</UnavailableEvidence>;
  }
  return (
    <ol className="collection-evidence-event-list">
      {events
        .slice(-8)
        .reverse()
        .map((event) => (
          <li key={event.event_id}>
            <span>
              <strong>{event.event_type}</strong>
              <small>
                #{event.sequence} · {event.timestamp}
              </small>
            </span>
            <code>{safeEventEvidence(event.payload)}</code>
          </li>
        ))}
    </ol>
  );
}

function UnavailableEvidence({ children }: { children: ReactNode }) {
  return <p className="collection-evidence-unavailable">{children}</p>;
}

function safeEventEvidence(payload: Record<string, unknown>): string {
  const safe = Object.fromEntries(
    Object.entries(payload)
      .filter(([key, value]) => {
        const normalized = key.toLowerCase();
        return (
          !normalized.includes("token") &&
          !normalized.includes("secret") &&
          !normalized.includes("password") &&
          ["string", "number", "boolean"].includes(typeof value)
        );
      })
      .sort(([left], [right]) => left.localeCompare(right))
      .slice(0, 7),
  );
  return Object.keys(safe).length > 0
    ? JSON.stringify(safe)
    : "No scalar evidence fields in this persisted event.";
}

function Credit({
  label,
  value,
}: {
  label: string;
  value: string | number | undefined;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value ?? "—"}</dd>
    </div>
  );
}

function processingStages(
  status: CollectionState | undefined,
  events: readonly CollectionEvent[],
): Array<{
  id: ProcessingTheaterStageId;
  state: "waiting" | "active" | "complete";
  eventCount: number;
}> {
  const eventCounts = new Map<ProcessingTheaterStageId, number>();
  let latestEventIndex = -1;
  for (const event of events) {
    const stage = collectionEventStage(event.event_type);
    if (!stage) continue;
    eventCounts.set(stage, (eventCounts.get(stage) ?? 0) + 1);
    latestEventIndex = Math.max(latestEventIndex, stageIndex(stage));
  }
  const stateIndex = status ? collectionStateStageIndex(status) : -1;
  const activeIndex = Math.max(stateIndex, latestEventIndex);
  const completeAll = status === "COMPLETED";
  return PROCESSING_THEATER_STAGES.map(({ id }, index) => ({
    id,
    state: completeAll
      ? "complete"
      : index < activeIndex
        ? "complete"
        : index === activeIndex
          ? "active"
          : "waiting",
    eventCount: eventCounts.get(id) ?? 0,
  }));
}

function stageIndex(stage: ProcessingTheaterStageId): number {
  return PROCESSING_THEATER_STAGES.findIndex((item) => item.id === stage);
}

function collectionStateStageIndex(state: CollectionState): number {
  if (
    [
      "CREATED",
      "DISCOVERING",
      "HASHING",
      "UPLOADING",
      "VERIFYING",
      "SECURITY_SCAN",
      "DEDUPLICATING",
      "INGESTED",
      "PREFLIGHTING",
      "ESTIMATED",
      "AWAITING_APPROVAL",
    ].includes(state)
  ) {
    return 0;
  }
  if (
    state === "PROCESSING" ||
    state === "PAUSED" ||
    state === "FAILED_RETRYABLE"
  )
    return 1;
  if (
    state === "VERIFYING_OUTPUT" ||
    state === "UNRESOLVED" ||
    state === "QUARANTINED"
  )
    return 2;
  if (state === "KNOWLEDGE_COMPILING") return 3;
  if (state === "PACKAGING") return 5;
  if (state === "COMPLETED") return 5;
  return -1;
}

function terminalCollectionState(state: CollectionState): boolean {
  return ["COMPLETED", "CANCELED", "PURGED"].includes(state);
}

function formatTimestamp(value: string, locale: StructaraLocale): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(locale === "ko" ? "ko-KR" : "en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(parsed);
}

const COPY = {
  en: {
    eyebrow: "Processing Theater",
    title: "Watch evidence become usable knowledge",
    intro:
      "Every stage is driven by stored collection events. Missing evidence stays visibly unavailable.",
    collection: "Collection",
    state: "State",
    job: "Correlated job",
    tasks: "Measured tasks",
    loading: "Loading snapshot",
    notAssigned: "Not assigned",
    notMeasured: "Not measured",
    pipeline: "Autonomous knowledge pipeline",
    workbench: "Evidence-backed processing workbench",
    collectionIntelligence: "Collection & Page Intelligence",
    collectionIntelligenceBody:
      "Authoritative upload and manifest state. No thumbnails are synthesized.",
    sourceTransformation: "Source Transformation",
    sourceTransformationBody:
      "Persisted route, block, table, and repair events from the same collection.",
    knowledgeFormation: "Knowledge Formation",
    knowledgeFormationBody:
      "Persisted note, entity, relation, architecture, and package events.",
    integrityEvidence: "Integrity Evidence",
    unavailable:
      "Unavailable — no authoritative persisted evidence exists for this surface yet.",
    pageEvidenceUnavailable:
      "Page-level intelligence is unavailable until a persisted preflight or route event exists.",
    uploadState: "Upload state",
    totalFiles: "Files",
    completedFiles: "Completed",
    duplicateFiles: "Duplicates",
    failedFiles: "Failed",
    manifestHash: "Manifest SHA-256",
    credits: "Credit ledger",
    evidence: "Event evidence",
    reserved: "Reserved",
    consumed: "Consumed",
    refunded: "Refunded",
    released: "Released",
    hardCap: "Hard cap",
    policyPending: "Overage policy pending",
    noEvents: "No persisted collection event is available yet.",
    pause: "Pause processing",
    resume: "Resume processing",
    applying: "Applying…",
    retry: "Retry snapshot",
    retryProcessing: "Retry processing",
    retrying: "Starting recovery…",
    retryError: "The processing recovery request failed.",
    recoveryEyebrow: "Recoverable interruption",
    recoveryTitle: "Resume from the last verified checkpoint",
    recoveryBody:
      "FOLYNTA will create an idempotent retry from durable evidence and keep the approved credit boundary.",
    newHardCap: "New approved hard cap",
    hardCapHint: (current: string) =>
      `Enter a value above the previous ${current}-credit cap. This explicitly approves the new limit.`,
    creditRecoveryBody:
      "The approved overage needs more available credits. Add credits first; the retry remains idempotent and keeps the same evidence boundary.",
    addCredits: "Open credit balance",
    retryAfterCredits: "Retry after adding credits",
    mobileViews: "Mobile processing views",
    mobileTabs: {
      progress: "Progress",
      source: "Source",
      result: "Result",
      knowledge: "Knowledge",
      integrity: "Integrity",
    },
    controlError: "The processing control request failed.",
    integrity: "Open Integrity Console",
    knowledge: "Open Knowledge Studio",
    persistedEvents: (count: string) => `${count} persisted events`,
    eventCount: (count: number) => `${count} events in this stage`,
    stageState: { waiting: "Waiting", active: "Active", complete: "Complete" },
    connection: {
      connecting: "Connecting",
      live: "Live SSE",
      polling: "Cursor replay",
      reconnecting: "Reconnecting",
    },
  },
  ko: {
    eyebrow: "처리 극장",
    title: "근거가 활용 가능한 지식이 되는 과정을 확인하세요",
    intro:
      "모든 단계는 저장된 컬렉션 이벤트로 움직입니다. 근거가 없으면 진행 상태도 표시하지 않습니다.",
    collection: "컬렉션",
    state: "상태",
    job: "연결된 작업",
    tasks: "측정된 작업",
    loading: "스냅샷 불러오는 중",
    notAssigned: "할당되지 않음",
    notMeasured: "측정되지 않음",
    pipeline: "자율 지식 파이프라인",
    workbench: "근거 기반 처리 워크벤치",
    collectionIntelligence: "컬렉션 및 페이지 인텔리전스",
    collectionIntelligenceBody:
      "권위 있는 업로드·매니페스트 상태입니다. 썸네일을 임의로 만들지 않습니다.",
    sourceTransformation: "원문 변환",
    sourceTransformationBody:
      "동일 컬렉션의 저장된 라우팅·블록·표·복구 이벤트입니다.",
    knowledgeFormation: "지식 형성",
    knowledgeFormationBody:
      "저장된 노트·엔터티·관계·아키텍처·패키지 이벤트입니다.",
    integrityEvidence: "무결성 근거",
    unavailable:
      "사용 불가 — 이 화면에 표시할 권위 있는 저장 근거가 아직 없습니다.",
    pageEvidenceUnavailable:
      "저장된 프리플라이트 또는 라우팅 이벤트가 생길 때까지 페이지 수준 인텔리전스는 사용할 수 없습니다.",
    uploadState: "업로드 상태",
    totalFiles: "파일",
    completedFiles: "완료",
    duplicateFiles: "중복",
    failedFiles: "실패",
    manifestHash: "매니페스트 SHA-256",
    credits: "크레딧 원장",
    evidence: "이벤트 근거",
    reserved: "예약",
    consumed: "사용",
    refunded: "환불",
    released: "해제",
    hardCap: "최대 한도",
    policyPending: "초과 정책 대기 중",
    noEvents: "아직 저장된 컬렉션 이벤트가 없습니다.",
    pause: "처리 일시정지",
    resume: "처리 재개",
    applying: "적용 중…",
    retry: "스냅샷 다시 불러오기",
    retryProcessing: "처리 다시 시작",
    retrying: "복구 시작 중…",
    retryError: "처리 복구 요청에 실패했습니다.",
    recoveryEyebrow: "복구 가능한 중단",
    recoveryTitle: "마지막 검증 지점에서 다시 시작",
    recoveryBody:
      "저장된 근거를 기준으로 중복 실행 없이 재시도하며, 승인된 크레딧 한도를 그대로 지킵니다.",
    newHardCap: "새 승인 크레딧 한도",
    hardCapHint: (current: string) =>
      `기존 ${current} 크레딧보다 큰 값을 입력하면 새 한도를 명시적으로 승인합니다.`,
    creditRecoveryBody:
      "승인된 초과 처리를 계속하려면 사용 가능한 크레딧이 더 필요합니다. 먼저 충전한 뒤 같은 근거와 한도 정책으로 안전하게 재시도하세요.",
    addCredits: "크레딧 잔액 확인",
    retryAfterCredits: "충전 후 다시 시작",
    mobileViews: "모바일 처리 화면",
    mobileTabs: {
      progress: "진행",
      source: "원문",
      result: "결과",
      knowledge: "지식",
      integrity: "무결성",
    },
    controlError: "처리 제어 요청에 실패했습니다.",
    integrity: "무결성 콘솔 열기",
    knowledge: "지식 스튜디오 열기",
    persistedEvents: (count: string) => `저장된 이벤트 ${count}개`,
    eventCount: (count: number) => `이 단계의 이벤트 ${count}개`,
    stageState: { waiting: "대기", active: "진행", complete: "완료" },
    connection: {
      connecting: "연결 중",
      live: "실시간 SSE",
      polling: "커서 재생",
      reconnecting: "재연결 중",
    },
  },
} as const;
