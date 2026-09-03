"use client";

import { ArrowRight, ChatCenteredText, MagnifyingGlass, ShieldCheck } from "@phosphor-icons/react";
import Link from "next/link";
import { useState } from "react";
import type { FormEvent } from "react";

import { SafeMarkdown } from "@/components/safe-markdown";
import { WorldSourcePreview } from "@/components/workspace/world-source-preview";
import { apiRequest, recordProductAnalyticsEvent } from "@/lib/api-client";

type Citation = {
  evidence_block_id: string;
  document_id: string;
  document_version_id: string;
  page_number: number;
  bbox1000: [number, number, number, number] | null;
};

type RetrievalHit = {
  stable_id: string;
  score: number;
  title: string;
  content_markdown: string;
  citations: Citation[];
  source_hash: string;
};

type RetrievalResponse = {
  query_fingerprint: string;
  hits: RetrievalHit[];
};

export function AskStudio({ collectionId }: { collectionId: string | null }) {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [result, setResult] = useState<RetrievalResponse | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [state, setState] = useState<"idle" | "searching" | "ready" | "unavailable">("idle");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = query.trim();
    if (!collectionId || !normalized) return;
    setState("searching");
    setSelectedCitation(null);
    setSubmittedQuery(normalized);
    void recordProductAnalyticsEvent({ event_type: "ask_started" }).catch(
      () => undefined,
    );
    try {
      const response = await apiRequest<RetrievalResponse>(
        `/v1/collections/${collectionId}/retrieval/search`,
        {
          method: "POST",
          idempotencyKey: crypto.randomUUID(),
          body: JSON.stringify({ query: normalized, candidate_k: 50, top_k: 8 }),
        },
      );
      setResult(response);
      setState("ready");
      if (response.hits.some((hit) => hit.citations.length > 0)) {
        void recordProductAnalyticsEvent({
          event_type: "ask_cited_answer",
        }).catch(() => undefined);
      }
    } catch {
      setResult(null);
      setState("unavailable");
    }
  }

  if (!collectionId) {
    return (
      <div className="ask-studio ask-studio-empty">
        <p className="workspace-eyebrow">Ask</p>
        <h1>Select a World before asking.</h1>
        <p>Ask searches one active, evidence-attested World. It never falls back to a public model.</p>
        <Link className="button button-primary" href="/knowledge-bases">
          Choose a World <ArrowRight size={16} />
        </Link>
      </div>
    );
  }

  return (
    <div className="ask-studio">
      <header className="ask-studio-header">
        <div>
          <p className="workspace-eyebrow">Ask · active World</p>
          <h1>Ask what the evidence can answer.</h1>
          <p>Results are retained compiled notes. Every shown answer has source-bound citations.</p>
        </div>
        <span><ShieldCheck size={17} /> Fail-closed retrieval</span>
      </header>

      <form className="ask-composer" onSubmit={(event) => { void submit(event); }}>
        <ChatCenteredText size={20} aria-hidden="true" />
        <label className="sr-only" htmlFor="world-question">Question for this World</label>
        <input
          id="world-question"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Ask about a policy, obligation, entity, or relationship…"
          maxLength={2000}
        />
        <button type="submit" disabled={!query.trim() || state === "searching"}>
          <MagnifyingGlass size={17} /> {state === "searching" ? "Searching…" : "Search World"}
        </button>
      </form>

      {state === "unavailable" && (
        <section className="ask-abstention" role="status">
          <strong>Answer withheld.</strong>
          <p>The attested retrieval service or its evidence chain is unavailable. No fallback answer was generated.</p>
        </section>
      )}
      {state === "ready" && result?.hits.length === 0 && (
        <section className="ask-abstention" role="status">
          <strong>Not enough evidence to answer “{submittedQuery}”.</strong>
          <p>This World returned no verified notes. Try a narrower question or review the source collection.</p>
        </section>
      )}

      {result && result.hits.length > 0 && (
        <div className="ask-results-layout">
          <section className="ask-results" aria-live="polite">
            <p className="ask-result-count">{result.hits.length} source-grounded results</p>
            {result.hits.map((hit, index) => (
              <article className="ask-answer" key={hit.stable_id}>
                <div className="ask-answer-heading">
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div><h2>{hit.title}</h2><small>Relevance {Math.max(0, hit.score).toFixed(3)}</small></div>
                </div>
                <SafeMarkdown source={hit.content_markdown} />
                <div className="ask-citations" aria-label={`Citations for ${hit.title}`}>
                  {hit.citations.map((citation) => (
                    <button
                      key={citation.evidence_block_id}
                      type="button"
                      onClick={() => {
                        setSelectedCitation(citation);
                        void recordProductAnalyticsEvent({
                          event_type: "evidence_opened",
                        }).catch(() => undefined);
                        void recordProductAnalyticsEvent({
                          event_type: "explore_citation_opened",
                        }).catch(() => undefined);
                      }}
                      aria-pressed={selectedCitation?.evidence_block_id === citation.evidence_block_id}
                    >
                      p.{citation.page_number} · {citation.bbox1000 ? "exact region" : "page source"}
                    </button>
                  ))}
                </div>
                <details className="ask-receipt">
                  <summary>Advanced receipt</summary>
                  <code>{hit.stable_id}</code><code>sha256:{hit.source_hash}</code>
                </details>
              </article>
            ))}
          </section>
          <aside className="ask-source-panel">
            {selectedCitation ? (
              <WorldSourcePreview
                documentVersionId={selectedCitation.document_version_id}
                pageNumber={selectedCitation.page_number}
                bbox1000={selectedCitation.bbox1000 ?? []}
                label="Selected Ask citation"
              />
            ) : (
              <div className="ask-source-empty">
                <p>Choose a citation to inspect its authorized source page.</p>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
