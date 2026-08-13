"use client";

import { Graph, MagnifyingGlass } from "@phosphor-icons/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { useProductWorld } from "@/lib/product-world-context";
import { worldObjects, type WorldObjectSummary } from "@/lib/world-view-model";
import type { EntityKind } from "@/lib/demo-workspace";

const KIND_FILTERS: readonly EntityKind[] = [
  "customer",
  "contract",
  "product",
  "policy",
  "region",
  "document",
];

/**
 * WORLD — browse and search the compiled knowledge graph.
 *
 * A stable exploratory instrument: search text and kind filter live in the
 * URL (`?q=&kind=`), not only in component state, so a link to a filtered
 * view is shareable and the back button behaves. There is no camera, no
 * scripted reveal — the graph is fully compiled before this page renders
 * anything (see lib/demo-world-source.ts), and it stays put while you look
 * at it.
 */
export default function WorldIndexPage() {
  const { projection, mode } = useProductWorld();
  const router = useRouter();
  const searchParams = useSearchParams();
  const query = searchParams.get("q") ?? "";
  const kind = searchParams.get("kind") ?? "";

  const objects = useMemo(
    () => worldObjects(projection, mode),
    [projection, mode],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return objects.filter((object) => {
      if (kind && object.kind !== kind) return false;
      if (q && !object.label.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [objects, query, kind]);

  function updateParams(next: { q?: string; kind?: string }) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(next)) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    const search = params.toString();
    router.replace(search ? `/app/world?${search}` : "/app/world");
  }

  return (
    <div className="world-index">
      <header className="world-index-header">
        <div>
          <p>World</p>
          <h1>Knowledge graph</h1>
        </div>
        <span className="world-object-count">
          {objects.length} object{objects.length === 1 ? "" : "s"} ·{" "}
          {projection.relationIds.length} relation
          {projection.relationIds.length === 1 ? "" : "s"}
        </span>
      </header>

      <div className="world-index-controls">
        <label className="world-search">
          <MagnifyingGlass size={16} aria-hidden="true" />
          <input
            type="search"
            value={query}
            placeholder="Search the world by name"
            onChange={(event) => updateParams({ q: event.target.value })}
            aria-label="Search objects in the world"
          />
        </label>
        <div className="world-kind-filters" role="group" aria-label="Filter by object kind">
          <button
            type="button"
            className={kind === "" ? "active" : undefined}
            onClick={() => updateParams({ kind: "" })}
          >
            All
          </button>
          {KIND_FILTERS.map((k) => (
            <button
              key={k}
              type="button"
              className={kind === k ? "active" : undefined}
              onClick={() => updateParams({ kind: k })}
            >
              {k}
            </button>
          ))}
        </div>
      </div>

      {objects.length === 0 ? (
        <div className="honest-state">
          <Graph size={28} weight="duotone" aria-hidden="true" />
          <div>
            <h2>No world compiled yet</h2>
            <p>
              This view has no compiled objects to show — the sample source
              has not resolved any entities.
            </p>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="honest-state compact">
          <p>No object in the sample world matches this search.</p>
        </div>
      ) : (
        <ul className="world-object-grid">
          {filtered.map((object) => (
            <WorldObjectCard key={object.id} object={object} />
          ))}
        </ul>
      )}
    </div>
  );
}

function WorldObjectCard({ object }: { object: WorldObjectSummary }) {
  return (
    <li>
      <Link href={`/app/world/${object.id}`} className="world-object-card">
        <span className="world-object-kind">{object.kind}</span>
        <strong>{object.label}</strong>
        <span className="world-object-relations">
          {object.relationCount} connection
          {object.relationCount === 1 ? "" : "s"}
        </span>
      </Link>
    </li>
  );
}
