"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { DemoFixtureEventSource } from "@/lib/demo-event-source";
import { continueSchedule } from "@/lib/demo-world-source";
import {
  DEMO_CHANGE_OPTIONS,
  DEMO_WORLD_STATE_ID,
  buildChangeStream,
  nextWorldState,
  type DemoWorldState,
} from "@/lib/demo-workspace";
import { useProductWorld } from "@/lib/product-world-context";
import { scopeKey } from "@/lib/world-projection";
import {
  appendHistoryEntry,
  changeEligible,
  type ChangeHistoryEntry,
} from "@/lib/world-view-model";

/**
 * CHANGE — revise a source and watch the world recompile.
 *
 * Only wired for the one object the sample fixture's change workflow is
 * actually about (`e_policy_warranty`) — see `changeEligible`. The button
 * plays a real, fresh `DemoFixtureEventSource` scoped to the transition and
 * feeds it into the shared projection via `attachSource`, so the resulting
 * `impact`/`recompile`/`worldState` the WORLD and ASK views read afterward
 * came from the same reducer path as everything else on this page — nothing
 * here is a separately hand-authored "after" state.
 */
export default function WorldObjectChangePage() {
  const params = useParams<{ entityId: string }>();
  const { projection, attachSource } = useProductWorld();
  const [pendingTerm, setPendingTerm] = useState<string>();
  const [history, setHistory] = useState<ChangeHistoryEntry[]>([]);
  const [recordedRevision, setRecordedRevision] = useState<number>();

  const currentTerm = projection.sourceRevision?.newValue ?? "2 years";
  const currentWorld: DemoWorldState = {
    id: projection.worldState?.id ?? DEMO_WORLD_STATE_ID,
    revision: projection.worldState?.revision ?? 1,
    term: currentTerm,
    previous: undefined,
  };

  // Records what this page has actually watched happen — see
  // `appendHistoryEntry`'s comment on why this is observed, not fetched,
  // history. Adjusting state during render (React's documented pattern for
  // "remember something from a changing prop") rather than in an effect, so
  // this commits in the same render the new revision arrives in instead of
  // one render later.
  if (projection.worldState && projection.worldState.revision !== recordedRevision) {
    setRecordedRevision(projection.worldState.revision);
    setHistory((existing) =>
      appendHistoryEntry(existing, projection.worldState, currentTerm),
    );
  }

  if (!changeEligible(params.entityId)) {
    return (
      <div className="honest-state compact">
        <p>No recorded change workflow for this object in the sample world.</p>
      </div>
    );
  }

  function reviseTo(term: string) {
    if (term === currentTerm) return;
    setPendingTerm(term);
    const target = nextWorldState(currentWorld, term);
    const speed = 4;
    const schedule = continueSchedule(
      buildChangeStream(currentWorld, target),
      // The fixture stream is always demo-scope (I2 §5) — see world-projection.ts.
      projection.lastSequenceByScope[scopeKey({ kind: "demo" })] ?? 0,
    );
    const source = new DemoFixtureEventSource(schedule, { speed });
    const detach = attachSource(source);
    // The scripted stream is finite and self-terminating; detach once its
    // last scheduled event (world_state.activated.v1) has fired.
    const lastAtMs = schedule.at(-1)?.atMs ?? 0;
    setTimeout(() => {
      detach();
      setPendingTerm(undefined);
    }, lastAtMs / speed + 200);
  }

  return (
    <div className="world-change-panel">
      <p>
        Current warranty term: <strong>{currentTerm}</strong>
        {projection.worldState && (
          <span className="world-change-revision">
            world revision {projection.worldState.revision}
          </span>
        )}
      </p>
      <p className="world-simulated-note">
        These buttons replay a simulated scenario against the sample world —
        no live document is edited and no real workspace is changed.
      </p>

      <div className="world-change-options" role="group" aria-label="Revise the warranty term">
        {DEMO_CHANGE_OPTIONS.map((option) => (
          <button
            key={option}
            type="button"
            className={option === currentTerm ? "active" : undefined}
            disabled={pendingTerm !== undefined}
            onClick={() => reviseTo(option)}
          >
            {option}
          </button>
        ))}
      </div>

      {pendingTerm && <p className="world-change-pending">Recompiling to {pendingTerm}…</p>}

      {history.length > 0 && (
        <div className="world-change-history">
          <h2>History (this session)</h2>
          <ol>
            {history.map((entry) => (
              <li
                key={entry.revision}
                data-current={entry.revision === currentWorld.revision}
              >
                <span className="world-change-history-revision">
                  Revision {entry.revision}
                </span>
                <span>{entry.term}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {projection.impact && (
        <dl className="world-impact-summary">
          <div>
            <dt>Sources changed</dt>
            <dd>{projection.impact.sourcesChanged}</dd>
          </div>
          <div>
            <dt>Knowledge units affected</dt>
            <dd>{projection.impact.knowledgeUnitsAffected}</dd>
          </div>
          <div>
            <dt>Agent contexts stale</dt>
            <dd>{projection.impact.agentContextsStale}</dd>
          </div>
          <div>
            <dt>Retrieval packages invalidated</dt>
            <dd>{projection.impact.retrievalPackagesInvalidated}</dd>
          </div>
        </dl>
      )}

      {projection.recompile && (
        <p className="world-recompile-progress">
          Recompiled {projection.recompile.recompiled} of{" "}
          {projection.recompile.scheduled} affected units
          {projection.recompile.done ? " — done." : "…"}
        </p>
      )}
    </div>
  );
}
