"use client";

import { ArrowRight, FileText, Graph, ListBullets, ShieldCheck } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { apiRequest, recordProductAnalyticsEvent } from "@/lib/api-client";

type Note = {
  id: string;
  document_id: string;
  stable_key: string;
  title: string;
  note_type: string;
  content_origin: string;
  review_status: string;
  evidence_block_ids: string[];
};

type Entity = {
  id: string;
  stable_key: string;
  entity_type: string;
  label: string;
  evidence_block_ids: string[];
};

type Relation = {
  id: string;
  document_id: string;
  subject_id: string;
  predicate: string;
  object_id: string;
  assertion_status: string;
  review_status: string;
  evidence_block_ids: string[];
};

type World = {
  collection_id: string;
  architecture_plan_id: string | null;
  document_ids: string[];
  notes: Note[];
  entities: Entity[];
  relations: Relation[];
  note_count: number;
  entity_count: number;
  relation_count: number;
  ready_for_package: boolean;
  limitations: string[];
};

const LENSES = ["Graph", "Directory", "Ontology", "Evidence", "Versions", "Files"] as const;
type Lens = (typeof LENSES)[number];

export function CollectionWorldStudio({ collectionId }: { collectionId: string }) {
  const [world, setWorld] = useState<World | null>(null);
  const [lens, setLens] = useState<Lens>("Graph");
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let active = true;
    void apiRequest<World>(`/v1/collections/${collectionId}/knowledge`)
      .then((response) => {
        if (!active) return;
        setWorld(response);
        setState("ready");
        void recordProductAnalyticsEvent({ event_type: "world_opened" }).catch(
          () => undefined,
        );
      })
      .catch(() => {
        if (active) setState("unavailable");
      });
    return () => { active = false; };
  }, [collectionId]);

  if (state === "loading") return <div className="collection-world-state">Opening the active World…</div>;
  if (state === "unavailable" || !world) {
    return (
      <div className="collection-world-state">
        <h1>World unavailable</h1>
        <p>The collection projection could not be attested. No sample graph has been substituted.</p>
        <Link href="/intake">Return to Sources</Link>
      </div>
    );
  }

  const predicates = Array.from(new Set(world.relations.map((relation) => relation.predicate))).sort();
  const evidenceIds = Array.from(new Set([
    ...world.notes.flatMap((note) => note.evidence_block_ids),
    ...world.entities.flatMap((entity) => entity.evidence_block_ids),
    ...world.relations.flatMap((relation) => relation.evidence_block_ids),
  ])).sort();

  return (
    <div className="collection-world">
      <header className="collection-world-header">
        <div>
          <p className="workspace-eyebrow">World · collection projection</p>
          <h1>Compiled World</h1>
          <p>{world.document_ids.length} sources · {world.entity_count} entities · {world.relation_count} relations · {evidenceIds.length} evidence blocks</p>
        </div>
        <Link className="button button-primary" href={`/ask?collection=${collectionId}`}>
          Ask this World <ArrowRight size={16} />
        </Link>
      </header>

      <nav className="world-lenses" aria-label="World lenses">
        {LENSES.map((item) => (
          <button key={item} type="button" aria-pressed={lens === item} onClick={() => setLens(item)}>{item}</button>
        ))}
      </nav>

      <section className="collection-world-surface">
        {lens === "Graph" && (
          <div className="world-graph-ledger">
            <div className="world-object-column">
              <h2><Graph size={18} /> Actual objects</h2>
              {world.entities.length === 0 && <p>No verified entities are present.</p>}
              {world.entities.map((entity) => (
                <details
                  key={entity.id}
                  onToggle={(event) => {
                    if (!event.currentTarget.open) return;
                    void recordProductAnalyticsEvent({
                      event_type: "explore_object_opened",
                    }).catch(() => undefined);
                  }}
                >
                  <summary><small>{entity.entity_type}</small><strong>{entity.label}</strong></summary>
                  <code>{entity.stable_key}</code>
                  <span>{entity.evidence_block_ids.length} evidence block(s)</span>
                </details>
              ))}
            </div>
            <div className="world-relation-column">
              <h2><ArrowRight size={18} /> Actual relations</h2>
              {world.relations.length === 0 && <p>No verified relations are present. No edges are inferred.</p>}
              {world.relations.map((relation) => (
                <article key={relation.id}>
                  <code>{relation.subject_id}</code><strong>{relation.predicate}</strong><code>{relation.object_id}</code>
                  <small>{relation.assertion_status} · {relation.evidence_block_ids.length} evidence</small>
                </article>
              ))}
            </div>
          </div>
        )}

        {lens === "Directory" && (
          <div className="world-directory">
            <h2><ListBullets size={18} /> Compiled notes</h2>
            {world.notes.length === 0 && <p>No verified notes are present.</p>}
            {world.notes.map((note) => (
              <article key={note.id}>
                <div><small>{note.note_type}</small><h3>{note.title}</h3></div>
                <span>{note.review_status}</span><code>{note.stable_key}</code>
              </article>
            ))}
          </div>
        )}

        {lens === "Ontology" && (
          <div className="world-ontology">
            <h2>Observed predicates and classes</h2>
            <p>Only types found in the active projection are listed.</p>
            <div>{predicates.map((predicate) => <span key={predicate}>{predicate}</span>)}</div>
            <div>{Array.from(new Set(world.entities.map((entity) => entity.entity_type))).sort().map((type) => <span key={type}>{type}</span>)}</div>
          </div>
        )}

        {lens === "Evidence" && (
          <div className="world-evidence-ledger">
            <h2><ShieldCheck size={18} /> Evidence ledger</h2>
            <p>These IDs are present in the collection projection. Ask opens their authorized page regions when available.</p>
            {evidenceIds.map((id) => <code key={id}>{id}</code>)}
          </div>
        )}

        {lens === "Versions" && (
          <div className="world-version-receipt">
            <h2>Active compile revision</h2>
            {world.architecture_plan_id ? <code>{world.architecture_plan_id}</code> : <p>No compiled architecture plan is present.</p>}
            <p>Historical revisions are not inferred from the active projection.</p>
          </div>
        )}

        {lens === "Files" && (
          <div className="world-files-receipt">
            <h2><FileText size={18} /> Portable files</h2>
            <p>{world.ready_for_package ? "The projection is eligible for packaging. No export is shown until a package receipt exists." : "This projection is not yet eligible for packaging."}</p>
          </div>
        )}
      </section>

      {world.limitations.length > 0 && (
        <details className="world-limitations"><summary>Projection boundaries</summary>{world.limitations.map((item) => <p key={item}>{item}</p>)}</details>
      )}
    </div>
  );
}
