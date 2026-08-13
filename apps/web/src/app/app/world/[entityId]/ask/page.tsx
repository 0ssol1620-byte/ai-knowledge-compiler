"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { DemoFixtureEventSource } from "@/lib/demo-event-source";
import { continueSchedule } from "@/lib/demo-world-source";
import {
  DEMO_INITIAL_WORLD,
  DEMO_QUESTION,
  buildAskStream,
  type DemoWorldState,
} from "@/lib/demo-workspace";
import { useProductWorld } from "@/lib/product-world-context";
import { scopeKey } from "@/lib/world-projection";
import { askEligible } from "@/lib/world-view-model";

/**
 * ASK — a query scoped to this object, answered from the world state that is
 * active right now.
 *
 * Wired for the objects on the sample narrative's spine (see `askEligible`);
 * everything else honestly says the sample cannot scope an answer to it.
 * The answer is read off `projection.ask`, which `buildAskStream` populates
 * by replaying through the same shared reducer CHANGE and WORLD use — asking
 * again after a CHANGE answers with the *new* term, not a stale one, because
 * `currentWorld` below is read from the live projection, not a constant.
 */
export default function WorldObjectAskPage() {
  const params = useParams<{ entityId: string }>();
  const { projection, attachSource } = useProductWorld();
  const [asking, setAsking] = useState(false);

  if (!askEligible(params.entityId)) {
    return (
      <div className="honest-state compact">
        <p>Ask is not scoped to this object in the sample world.</p>
      </div>
    );
  }

  const currentWorld: DemoWorldState = {
    id: projection.worldState?.id ?? DEMO_INITIAL_WORLD.id,
    revision: projection.worldState?.revision ?? DEMO_INITIAL_WORLD.revision,
    term: projection.sourceRevision?.newValue ?? DEMO_INITIAL_WORLD.term,
    previous: undefined,
  };

  function ask() {
    setAsking(true);
    const schedule = continueSchedule(
      buildAskStream(currentWorld),
      // The fixture stream is always demo-scope (I2 §5) — see world-projection.ts.
      projection.lastSequenceByScope[scopeKey({ kind: "demo" })] ?? 0,
    );
    const speed = 3;
    const source = new DemoFixtureEventSource(schedule, { speed });
    const detach = attachSource(source);
    const lastAtMs = schedule.at(-1)?.atMs ?? 0;
    setTimeout(() => {
      detach();
      setAsking(false);
    }, lastAtMs / speed + 200);
  }

  const askState = projection.ask;

  return (
    <div className="world-ask-panel">
      <p className="world-ask-question">{DEMO_QUESTION}</p>
      {projection.worldState && (
        <p className="world-ask-revision">
          Answering from the current state of this object — world revision{" "}
          {projection.worldState.revision}
        </p>
      )}
      <p className="world-simulated-note">
        This runs a simulated query against the sample world — no live model
        call is made and no real workspace is queried.
      </p>
      <button type="button" onClick={ask} disabled={asking}>
        {asking ? "Resolving…" : "Ask"}
      </button>

      {askState && (
        <div className="world-ask-result">
          {askState.resolved.length > 0 && (
            <ul className="world-ask-sources">
              {askState.resolved.map((source, index) => (
                <li key={`${source.documentLabel}-${index}`}>
                  <span
                    className={`world-temporal-status status-${source.status.toLowerCase()}`}
                  >
                    {source.status}
                  </span>
                  {source.documentLabel}
                </li>
              ))}
            </ul>
          )}
          {askState.answer && (
            <>
              <p className="world-ask-answer">{askState.answer}</p>
              <ul className="world-ask-guarantees">
                {askState.guarantees.map((guarantee) => (
                  <li key={guarantee.label} data-held={guarantee.held}>
                    <strong>{guarantee.label}</strong>
                    <span>{guarantee.because}</span>
                  </li>
                ))}
              </ul>
              <ol className="world-ask-trace">
                {askState.trace.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            </>
          )}
        </div>
      )}
    </div>
  );
}
