import {
  DEMO_ENTITIES,
  DEMO_RELATIONS,
  DEMO_UNITS,
  WARRANTY_SUBJECT,
  type DemoEntity,
  type EntityKind,
} from "@/lib/demo-workspace";
import type { WorldProjection } from "@/lib/world-projection";

/**
 * View-model helpers for the WORLD/SOURCE/CHANGE/ASK slice.
 *
 * `WorldProjection` is presentation-neutral by design (see world-projection.ts):
 * it carries ids and counts, never display metadata. Rendering a list of named,
 * positioned objects — the WORLD act needs a label and a kind, not just an id
 * — requires cross-referencing those ids against a metadata source. Today the
 * only metadata source is the sample fixture (`demo-workspace.ts`), so every
 * function here that resolves a label is explicitly demo-only: it returns
 * nothing rather than fabricate a label for a `live` projection that has none.
 * A future live source that publishes real entity metadata would get its own
 * lookup function, not a silent branch inside these ones.
 */

export interface WorldObjectSummary {
  id: string;
  kind: EntityKind;
  label: string;
  relationCount: number;
}

/** Every object the projection has resolved, in sample mode only. */
export function worldObjects(
  projection: WorldProjection,
  mode: "demo" | "live" | "idle",
): WorldObjectSummary[] {
  if (mode !== "demo") return [];
  const present = new Set(projection.entityIds);
  return DEMO_ENTITIES.filter((entity) => present.has(entity.id)).map(
    (entity) => ({
      id: entity.id,
      kind: entity.kind,
      label: entity.label,
      relationCount: DEMO_RELATIONS.filter(
        (relation) => relation.from === entity.id || relation.to === entity.id,
      ).length,
    }),
  );
}

export function findWorldObject(entityId: string): DemoEntity | undefined {
  return DEMO_ENTITIES.find((entity) => entity.id === entityId);
}

export interface RelatedObject {
  relationId: string;
  predicate: string;
  direction: "from" | "to";
  otherId: string;
  otherLabel: string;
}

/** The other objects a given object is directly connected to. */
export function relatedObjects(entityId: string): RelatedObject[] {
  return DEMO_RELATIONS.filter(
    (relation) => relation.from === entityId || relation.to === entityId,
  ).map((relation) => {
    const direction: "from" | "to" =
      relation.from === entityId ? "from" : "to";
    const otherId = direction === "from" ? relation.to : relation.from;
    const other = findWorldObject(otherId);
    return {
      relationId: relation.id,
      predicate: relation.predicate,
      direction,
      otherId,
      otherLabel: other?.label ?? otherId,
    };
  });
}

/**
 * A document-kind entity's id encodes the document id it names, one-to-one,
 * by fixture convention (`e_doc_contract_a` names `d_contract_a`). Derived
 * rather than hardcoded so a fixture edit that breaks the pattern fails the
 * test that pins it, instead of silently returning stale evidence.
 */
function documentIdForEntity(entityId: string): string | undefined {
  const prefix = "e_doc_";
  return entityId.startsWith(prefix)
    ? `d_${entityId.slice(prefix.length)}`
    : undefined;
}

/**
 * Knowledge units this object is evidence for, in the sample world.
 *
 * A document-kind object gets the units sourced from it. The policy entity
 * that is the subject of the sample conflict (`e_policy_warranty`) gets every
 * unit about that subject, since it is what those units are *about*, not
 * where they came from. Every other object honestly has none — the fixture
 * does not model source evidence for a customer, a contract, a product or a
 * region directly.
 */
export function sourceUnitsForEntity(entityId: string) {
  const documentId = documentIdForEntity(entityId);
  if (documentId) {
    return DEMO_UNITS.filter((unit) => unit.source.document_id === documentId);
  }
  if (entityId === "e_policy_warranty") {
    return DEMO_UNITS.filter((unit) => unit.subject === WARRANTY_SUBJECT);
  }
  return [];
}

/**
 * Objects on the relation "spine" the sample narrative walks:
 * Customer A → Contract 182 → Product X → Warranty Policy → Korea.
 * Derived from the `spine: true` relations rather than listed by hand, so
 * the set can never drift from the relations that actually define it.
 */
const SPINE_ENTITY_IDS: readonly string[] = Array.from(
  new Set(
    DEMO_RELATIONS.filter((relation) => relation.spine).flatMap(
      (relation) => [relation.from, relation.to],
    ),
  ),
);

/**
 * Whether the CHANGE view has a real, working workflow for this object.
 *
 * Only the warranty policy entity is the subject of the sample's recorded
 * source revision (`buildChangeStream`). Every other object honestly has no
 * change workflow in this sample world — the CHANGE tab still renders for
 * them, but says so rather than presenting an inert form.
 */
export function changeEligible(entityId: string): boolean {
  return entityId === "e_policy_warranty";
}

/**
 * Whether the ASK view can scope a real answer to this object.
 *
 * `DEMO_QUESTION` ("What is the current warranty?") only resolves against the
 * spine that leads to it. Asking it "about" a region on the far side of the
 * graph that the fixture never wires up would be presenting a scoped answer
 * the sample cannot actually produce.
 */
export function askEligible(entityId: string): boolean {
  return SPINE_ENTITY_IDS.includes(entityId);
}

/** One entry in the CHANGE view's session-local revision history. */
export interface ChangeHistoryEntry {
  revision: number;
  term: string;
}

/**
 * Append a revision to the CHANGE view's history, if it is new.
 *
 * This is deliberately *observed* history, not recorded/fetched history: it
 * only ever grows by watching `projection.worldState` actually change to a
 * revision the caller has not already recorded, one entry per revision, never
 * reordered or backfilled. A world state this component was never mounted to
 * see (a revision reached before the CHANGE tab was opened this session)
 * stays honestly absent instead of being guessed — the list is what happened
 * while someone was watching, not a fabricated full history the sample
 * fixture cannot actually source.
 */
export function appendHistoryEntry(
  history: readonly ChangeHistoryEntry[],
  worldState: { revision: number } | undefined,
  term: string,
): ChangeHistoryEntry[] {
  if (!worldState) return [...history];
  if (history.some((entry) => entry.revision === worldState.revision)) {
    return [...history];
  }
  return [...history, { revision: worldState.revision, term }];
}
