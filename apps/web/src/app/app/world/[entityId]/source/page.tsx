"use client";

import { useParams } from "next/navigation";

import { sourceUnitsForEntity } from "@/lib/world-view-model";

/**
 * SOURCE — trace this object to the evidence it was compiled from.
 *
 * Renders `SourceRefLite` fields only (document, page, locator, cell): this
 * is a lightweight, readable pointer, not the full bbox-carrying `SourceRef`
 * that `workspace/source-viewer.tsx` renders — see product-event.ts's own
 * comment on why the two are deliberately separate types.
 */
export default function WorldObjectSourcePage() {
  const params = useParams<{ entityId: string }>();
  const units = sourceUnitsForEntity(params.entityId);

  if (units.length === 0) {
    return (
      <div className="honest-state compact">
        <p>No source evidence is modeled for this object in the sample world.</p>
      </div>
    );
  }

  return (
    <ul className="world-source-list">
      {units.map((unit) => (
        <li key={unit.id} className="world-source-card">
          <header>
            <strong>{unit.value}</strong>
            <span className={`world-temporal-status status-${unit.status.toLowerCase()}`}>
              {unit.status}
            </span>
          </header>
          <p>{unit.basis}</p>
          <dl>
            <div>
              <dt>Document</dt>
              <dd>{unit.source.document_label}</dd>
            </div>
            <div>
              <dt>Location</dt>
              <dd>
                Page {unit.source.page_number} · {unit.source.locator}
                {unit.source.cell ? ` · ${unit.source.cell}` : ""}
              </dd>
            </div>
            <div>
              <dt>Scope</dt>
              <dd>{unit.scope}</dd>
            </div>
            <div>
              <dt>Effective from</dt>
              <dd>{unit.effectiveFrom}</dd>
            </div>
          </dl>
        </li>
      ))}
    </ul>
  );
}
