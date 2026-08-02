import type { CollectionEvent } from "@/lib/collection-runtime-client";

export type ProcessingConnection =
  "live" | "replaying" | "offline" | "complete";

export type FileCluster = {
  id: string;
  category: string;
  fileCount: number;
  featureRecordCount: number;
  lastSequence: number;
};

export type PageScene = {
  id: string;
  pageNumber1?: number;
  route?: string;
  state:
    | "queued"
    | "routed"
    | "processing"
    | "verification_failed"
    | "repairing"
    | "pending_verification"
    | "authority_verified"
    | "quarantined"
    | "complete";
  regionIds: string[];
  blockIds: string[];
  tableIds: string[];
  proofIds: string[];
  lastSequence: number;
};

export type WorkerLane = {
  id: string;
  route: string;
  pageIds: string[];
  state: "active" | "degraded" | "draining" | "quarantined";
  lastSequence: number;
};

export type Milestone = {
  id: string;
  kind:
    | "estimate-ready"
    | "processing-started"
    | "verification-attention"
    | "knowledge-forming"
    | "package-validated"
    | "package-signed"
    | "processing-complete";
  sequence: number;
  detailRef?: string;
};

export type KnowledgeDelta = {
  id: string;
  count: number;
  sequence: number;
};

export type IntegrityItem = {
  id: string;
  targetId?: string;
  reasonCodes: string[];
  state: "active" | "resolved" | "quarantined";
  sequence: number;
};

export type ProcessingSceneModel = {
  collection: {
    id: string;
    files: number;
    bytes: number;
    uploadState: string;
  };
  clusters: FileCluster[];
  pages: PageScene[];
  selectedPageId?: string;
  workerLanes: WorkerLane[];
  milestones: Milestone[];
  knowledge: {
    folders: KnowledgeDelta[];
    notes: KnowledgeDelta[];
    entities: KnowledgeDelta[];
    relations: KnowledgeDelta[];
    packages: KnowledgeDelta[];
  };
  integrity: {
    active: IntegrityItem[];
    resolved: IntegrityItem[];
    quarantined: IntegrityItem[];
  };
  sequence: number;
  connection: ProcessingConnection;
  sceneHash: string;
};

export type SceneProjectionDiagnostics = {
  duplicateEventIds: string[];
  conflictingSequences: number[];
  unsupportedEventIds: string[];
  pendingSequences: number[];
  gapAfter?: number;
};

export type ProcessingSceneProjection = {
  scene: ProcessingSceneModel;
  diagnostics: SceneProjectionDiagnostics;
};

type MutableScene = Omit<ProcessingSceneModel, "sceneHash">;
type UnknownPayload = Readonly<Record<string, unknown>>;

const terminalEvents = new Set([
  "package.signed.v1",
  "processing.completed.v1",
  "collection.completed.v1",
]);

function stringValue(payload: UnknownPayload, ...keys: string[]) {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return undefined;
}

function numberValue(payload: UnknownPayload, ...keys: string[]) {
  for (const key of keys) {
    const value = payload[key];
    const parsed = typeof value === "number" ? value : Number(value);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
  }
  return undefined;
}

function stringList(payload: UnknownPayload, key: string): string[] {
  const value = payload[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function objectKeys(payload: UnknownPayload, key: string): string[] {
  const value = payload[key];
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? Object.keys(value).sort()
    : [];
}

function addUnique(values: string[], value: string | undefined) {
  if (value && !values.includes(value)) values.push(value);
  values.sort();
}

function upsert<T extends { id: string }>(
  values: T[],
  id: string,
  create: () => T,
): T {
  const current = values.find((value) => value.id === id);
  if (current) return current;
  const next = create();
  values.push(next);
  values.sort((left, right) => left.id.localeCompare(right.id));
  return next;
}

function pageId(event: CollectionEvent): string | undefined {
  return (
    stringValue(event.payload, "page_id") ??
    stringValue(event.payload, "target_page_id")
  );
}

function laneId(event: CollectionEvent, route: string): string {
  return (
    stringValue(event.payload, "worker_lane_id", "pool_id", "worker_id") ??
    `route:${route}`
  );
}

function eventDetailRef(event: CollectionEvent): string | undefined {
  return stringValue(
    event.payload,
    "detail_ref",
    "evidence_ref",
    "package_manifest_id",
    "export_id",
  );
}

function eventTargetId(event: CollectionEvent): string | undefined {
  return (
    pageId(event) ??
    stringValue(
      event.payload,
      "target_id",
      "region_id",
      "block_id",
      "table_id",
      "repair_id",
    )
  );
}

function addMilestone(
  scene: MutableScene,
  event: CollectionEvent,
  kind: Milestone["kind"],
) {
  upsert(scene.milestones, event.event_id, () => ({
    id: event.event_id,
    kind,
    sequence: event.sequence,
    ...(eventDetailRef(event) ? { detailRef: eventDetailRef(event) } : {}),
  }));
}

function addKnowledgeDelta(
  scene: MutableScene,
  event: CollectionEvent,
  bucket: keyof MutableScene["knowledge"],
  countKey: string,
  fallbackId: string,
) {
  const id =
    stringValue(
      event.payload,
      "folder_id",
      "note_id",
      "entity_id",
      "relation_id",
      "package_manifest_id",
    ) ?? `${fallbackId}:${event.sequence}`;
  const count = numberValue(event.payload, countKey) ?? 1;
  upsert(scene.knowledge[bucket], id, () => ({
    id,
    count,
    sequence: event.sequence,
  }));
}

function integrityItem(
  scene: MutableScene,
  event: CollectionEvent,
  state: IntegrityItem["state"],
) {
  const id =
    stringValue(event.payload, "integrity_id", "repair_id", "decision_id") ??
    event.event_id;
  const targetId = eventTargetId(event);
  const reasonCodes = [
    ...stringList(event.payload, "reason_codes"),
    ...(stringValue(event.payload, "reason_code")
      ? [stringValue(event.payload, "reason_code")!]
      : []),
  ].sort();
  const item: IntegrityItem = {
    id,
    ...(targetId ? { targetId } : {}),
    reasonCodes,
    state,
    sequence: event.sequence,
  };
  for (const bucket of [
    scene.integrity.active,
    scene.integrity.resolved,
    scene.integrity.quarantined,
  ]) {
    const index = bucket.findIndex((candidate) => candidate.id === id);
    if (index >= 0) bucket.splice(index, 1);
  }
  const bucket =
    state === "active"
      ? scene.integrity.active
      : state === "resolved"
        ? scene.integrity.resolved
        : scene.integrity.quarantined;
  bucket.push(item);
  bucket.sort((left, right) => left.id.localeCompare(right.id));
}

function routePage(scene: MutableScene, event: CollectionEvent) {
  const id = pageId(event);
  if (!id) return;
  const route =
    stringValue(event.payload, "route", "route_profile", "route_class") ??
    objectKeys(event.payload, "route_counts")[0] ??
    "selected";
  const page = upsert<PageScene>(scene.pages, id, () => ({
    id,
    state: "queued",
    regionIds: [],
    blockIds: [],
    tableIds: [],
    proofIds: [],
    lastSequence: event.sequence,
  }));
  page.route = route;
  page.state = "routed";
  page.pageNumber1 = numberValue(event.payload, "page_number1");
  page.lastSequence = event.sequence;
  scene.selectedPageId = id;
  const lane = upsert<WorkerLane>(
    scene.workerLanes,
    laneId(event, route),
    () => ({
      id: laneId(event, route),
      route,
      pageIds: [],
      state: "active",
      lastSequence: event.sequence,
    }),
  );
  addUnique(lane.pageIds, id);
  lane.lastSequence = event.sequence;
}

function mutatePage(
  scene: MutableScene,
  event: CollectionEvent,
  state?: PageScene["state"],
) {
  const id = pageId(event);
  if (!id) return undefined;
  const page = upsert<PageScene>(scene.pages, id, () => ({
    id,
    state: "queued",
    regionIds: [],
    blockIds: [],
    tableIds: [],
    proofIds: [],
    lastSequence: event.sequence,
  }));
  if (state) page.state = state;
  page.lastSequence = event.sequence;
  scene.selectedPageId = id;
  return page;
}

function applyEvent(scene: MutableScene, event: CollectionEvent) {
  const payload = event.payload as UnknownPayload;
  switch (event.event_type) {
    case "collection.files.planned.v1":
    case "collection.discovery.progress.v1":
      scene.collection.files =
        numberValue(payload, "total_files", "discovered_files") ??
        scene.collection.files;
      scene.collection.bytes =
        numberValue(payload, "total_bytes", "discovered_bytes") ??
        scene.collection.bytes;
      scene.collection.uploadState =
        stringValue(payload, "status") ?? scene.collection.uploadState;
      break;
    case "file.hash.progress.v1":
      scene.collection.uploadState = "hashing";
      break;
    case "file.upload.progress.v1":
      scene.collection.uploadState = "uploading";
      break;
    case "collection.upload.completed.v1":
      scene.collection.uploadState = "verifying";
      break;
    case "collection.ingested.v1":
      scene.collection.uploadState = "ready";
      break;
    case "preflight.cluster.created.v1": {
      const id =
        stringValue(payload, "cluster_id", "preflight_id") ?? event.event_id;
      const category =
        stringValue(payload, "category", "cluster_type") ?? "preflight";
      const cluster = upsert(scene.clusters, id, () => ({
        id,
        category,
        fileCount: 0,
        featureRecordCount: 0,
        lastSequence: event.sequence,
      }));
      cluster.fileCount =
        numberValue(payload, "member_files") ?? cluster.fileCount;
      cluster.featureRecordCount =
        numberValue(payload, "feature_records") ?? cluster.featureRecordCount;
      cluster.lastSequence = event.sequence;
      break;
    }
    case "estimate.final.ready.v1":
      addMilestone(scene, event, "estimate-ready");
      break;
    case "processing.started.v1":
      addMilestone(scene, event, "processing-started");
      break;
    case "page.route.selected.v1":
      routePage(scene, event);
      break;
    case "region.route.selected.v1": {
      const page = mutatePage(scene, event, "processing");
      if (page) addUnique(page.regionIds, stringValue(payload, "region_id"));
      break;
    }
    case "block.completed.v1": {
      const page = mutatePage(scene, event, "processing");
      if (page) addUnique(page.blockIds, stringValue(payload, "block_id"));
      break;
    }
    case "table.reconstructed.v1": {
      const page = mutatePage(scene, event, "processing");
      if (page) addUnique(page.tableIds, stringValue(payload, "table_id"));
      break;
    }
    case "verification.failed.v1":
      mutatePage(scene, event, "verification_failed");
      integrityItem(scene, event, "active");
      addMilestone(scene, event, "verification-attention");
      break;
    case "repair.started.v1":
      mutatePage(scene, event, "repairing");
      integrityItem(scene, event, "active");
      break;
    case "repair.completed.v1":
      mutatePage(scene, event, "pending_verification");
      integrityItem(scene, event, "resolved");
      break;
    case "output.quarantined.v1":
      mutatePage(scene, event, "quarantined");
      integrityItem(scene, event, "quarantined");
      break;
    case "numeric.authority.verified.v1": {
      const page = mutatePage(scene, event, "authority_verified");
      if (page) addUnique(page.proofIds, stringValue(payload, "proof_id"));
      break;
    }
    case "note.created.v1":
      addKnowledgeDelta(scene, event, "notes", "note_count", "note");
      addMilestone(scene, event, "knowledge-forming");
      break;
    case "entity.resolved.v1":
      addKnowledgeDelta(scene, event, "entities", "entity_count", "entity");
      break;
    case "relation.created.v1":
      addKnowledgeDelta(
        scene,
        event,
        "relations",
        "relation_count",
        "relation",
      );
      break;
    case "architecture.folder.created.v1":
      addKnowledgeDelta(scene, event, "folders", "folder_count", "folder");
      break;
    case "architecture.moc.created.v1":
      addKnowledgeDelta(scene, event, "folders", "moc_count", "moc");
      break;
    case "package.validated.v1":
      addKnowledgeDelta(scene, event, "packages", "file_count", "package");
      addMilestone(scene, event, "package-validated");
      break;
    case "package.signed.v1":
      addKnowledgeDelta(scene, event, "packages", "file_count", "package");
      addMilestone(scene, event, "package-signed");
      break;
    case "processing.completed.v1":
    case "collection.completed.v1":
      addMilestone(scene, event, "processing-complete");
      break;
    case "worker.semantic.degraded.v1":
    case "worker.draining.v1":
    case "worker.quarantined.v1": {
      const id =
        stringValue(payload, "pool_id", "worker_id") ??
        `worker:${event.sequence}`;
      const route = stringValue(payload, "route", "route_class") ?? "worker";
      const lane = upsert<WorkerLane>(scene.workerLanes, id, () => ({
        id,
        route,
        pageIds: [],
        state: "active",
        lastSequence: event.sequence,
      }));
      lane.state = event.event_type.includes("quarantined")
        ? "quarantined"
        : event.event_type.includes("draining")
          ? "draining"
          : "degraded";
      lane.lastSequence = event.sequence;
      break;
    }
  }
  scene.sequence = event.sequence;
  if (terminalEvents.has(event.event_type)) scene.connection = "complete";
}

function canonicalScene(scene: MutableScene): string {
  return JSON.stringify(scene);
}

/** Stable non-cryptographic scene identity for replay equality checks. */
export function processingSceneHash(scene: MutableScene): string {
  const input = canonicalScene(scene);
  let hash = 0x811c9dc5;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `fnv1a32:${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

export function emptyProcessingScene(
  collectionId: string,
  connection: ProcessingConnection = "live",
): ProcessingSceneModel {
  const scene: MutableScene = {
    collection: { id: collectionId, files: 0, bytes: 0, uploadState: "queued" },
    clusters: [],
    pages: [],
    workerLanes: [],
    milestones: [],
    knowledge: {
      folders: [],
      notes: [],
      entities: [],
      relations: [],
      packages: [],
    },
    integrity: { active: [], resolved: [], quarantined: [] },
    sequence: 0,
    connection,
  };
  return { ...scene, sceneHash: processingSceneHash(scene) };
}

export function projectProcessingScene(
  collectionId: string,
  input: readonly CollectionEvent[],
  baseline?: ProcessingSceneModel,
): ProcessingSceneProjection {
  const diagnostics: SceneProjectionDiagnostics = {
    duplicateEventIds: [],
    conflictingSequences: [],
    unsupportedEventIds: [],
    pendingSequences: [],
  };
  const scene: MutableScene = baseline
    ? {
        ...structuredClone(baseline),
        collection: { ...baseline.collection },
      }
    : { ...emptyProcessingScene(collectionId), sceneHash: undefined as never };
  delete (scene as MutableScene & { sceneHash?: string }).sceneHash;
  scene.connection = "live";

  const byEventId = new Map<string, CollectionEvent>();
  for (const event of input) {
    if (event.schema_version !== "1.0") {
      diagnostics.unsupportedEventIds.push(event.event_id);
      continue;
    }
    if (byEventId.has(event.event_id)) {
      diagnostics.duplicateEventIds.push(event.event_id);
      continue;
    }
    byEventId.set(event.event_id, event);
  }
  const ordered = [...byEventId.values()].sort(
    (left, right) =>
      left.sequence - right.sequence ||
      left.event_id.localeCompare(right.event_id),
  );
  const bySequence = new Map<number, CollectionEvent>();
  for (const event of ordered) {
    if (bySequence.has(event.sequence)) {
      diagnostics.conflictingSequences.push(event.sequence);
      continue;
    }
    bySequence.set(event.sequence, event);
  }

  let expected = scene.sequence + 1;
  for (const event of bySequence.values()) {
    if (event.sequence <= scene.sequence) continue;
    if (event.sequence !== expected) {
      diagnostics.gapAfter = expected - 1;
      diagnostics.pendingSequences = [...bySequence.keys()].filter(
        (sequence) => sequence >= event.sequence,
      );
      scene.connection = "replaying";
      break;
    }
    applyEvent(scene, event);
    expected = event.sequence + 1;
  }

  diagnostics.duplicateEventIds.sort();
  diagnostics.conflictingSequences.sort((left, right) => left - right);
  diagnostics.unsupportedEventIds.sort();
  return {
    scene: { ...scene, sceneHash: processingSceneHash(scene) },
    diagnostics,
  };
}
