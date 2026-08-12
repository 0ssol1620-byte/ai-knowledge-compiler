export type CollectionReceiptPointer = {
  fileId: string;
  sourceFileId: string;
};

export type CollectionResumeRecord = {
  collectionId: string;
  sourceRootId: string;
  projectId: string;
  sourceFingerprint: string;
  limitations: string[];
  pendingReceipts: CollectionReceiptPointer[];
  browserResumeToken?: string | null;
  updatedAt: string;
};

export type CollectionFileHandleRecord = {
  relativePath: string;
  handle: FileSystemFileHandle;
};

export type CollectionRuntimePointer = {
  collectionId: string;
  startIdempotencyKey: string;
  controlIdempotencyKey?: string | null;
  controlAction?: "pause" | "resume" | null;
  retryIdempotencyKey?: string | null;
  processingResumeToken?: string | null;
  jobId?: string | null;
  architecturePlanId?: string | null;
  status?: string;
  creditsReserved?: string | number;
  creditsConsumed?: string | number;
  creditsRefunded?: string | number;
  creditsReleased?: string | number;
  hardCapCredits?: string | number;
  overagePolicy?: string;
  updatedAt: string;
};

type StoredSession = CollectionResumeRecord & { id: string };
type StoredHandle = CollectionFileHandleRecord & {
  id: string;
  sessionId: string;
};

type RetryPointer = {
  schemaVersion: 2;
  sessionId: string;
};

const DATABASE_NAME = "akc-collection-intake";
const DATABASE_VERSION = 3;
const SESSION_STORE = "sessions";
const HANDLE_STORE = "file-handles";
const RUNTIME_STORE = "collection-runtime";
const memorySessions = new Map<string, StoredSession>();
const memoryHandles = new Map<string, StoredHandle>();
const memoryRuntime = new Map<string, CollectionRuntimePointer>();

export async function loadCollectionRuntimePointer(
  collectionId: string,
): Promise<CollectionRuntimePointer | undefined> {
  const memory = memoryRuntime.get(collectionId);
  if (memory) return memory;
  const database = await openDatabase();
  if (!database) return undefined;
  try {
    const value = await requestResult<CollectionRuntimePointer | undefined>(
      database
        .transaction(RUNTIME_STORE, "readonly")
        .objectStore(RUNTIME_STORE)
        .get(collectionId),
    );
    if (value) memoryRuntime.set(collectionId, value);
    return value;
  } finally {
    database.close();
  }
}

export async function saveCollectionRuntimePointer(
  value: Omit<CollectionRuntimePointer, "updatedAt"> & { updatedAt?: string },
): Promise<CollectionRuntimePointer> {
  const stored: CollectionRuntimePointer = {
    ...value,
    updatedAt: new Date().toISOString(),
  };
  memoryRuntime.set(stored.collectionId, stored);
  const database = await openDatabase();
  if (!database) return stored;
  try {
    const transaction = database.transaction(RUNTIME_STORE, "readwrite");
    transaction.objectStore(RUNTIME_STORE).put(stored);
    await transactionComplete(transaction);
  } finally {
    database.close();
  }
  return stored;
}

export async function loadCollectionResumeRecord(
  pointerKey: string,
): Promise<CollectionResumeRecord | undefined> {
  const pointer = readRetryPointer(pointerKey);
  if (!pointer) return undefined;
  const memory = memorySessions.get(pointer.sessionId);
  if (memory) return stripSessionId(memory);
  const database = await openDatabase();
  if (!database) return undefined;
  try {
    const stored = await requestResult<StoredSession | undefined>(
      database
        .transaction(SESSION_STORE, "readonly")
        .objectStore(SESSION_STORE)
        .get(pointer.sessionId),
    );
    if (!stored || !isResumeRecord(stored)) return undefined;
    memorySessions.set(pointer.sessionId, stored);
    return stripSessionId(stored);
  } finally {
    database.close();
  }
}

export async function saveCollectionResumeRecord(
  pointerKey: string,
  value: Omit<CollectionResumeRecord, "updatedAt"> & {
    updatedAt?: string;
  },
): Promise<string> {
  const sessionId = `collection:${value.collectionId}`;
  const stored: StoredSession = {
    ...value,
    id: sessionId,
    updatedAt: new Date().toISOString(),
  };
  memorySessions.set(sessionId, stored);
  const pointer = { schemaVersion: 2, sessionId } as const;
  writeRetryPointer(pointerKey, pointer);
  writeRetryPointer(latestPointerKey(value.projectId), pointer);
  const database = await openDatabase();
  if (!database) return sessionId;
  try {
    const transaction = database.transaction(SESSION_STORE, "readwrite");
    transaction.objectStore(SESSION_STORE).put(stored);
    await transactionComplete(transaction);
  } finally {
    database.close();
  }
  return sessionId;
}

export async function removeCollectionResumeRecord(
  pointerKey: string,
): Promise<void> {
  const pointer = readRetryPointer(pointerKey);
  removeRetryPointer(pointerKey);
  if (!pointer) return;
  const memory = memorySessions.get(pointer.sessionId);
  if (memory) {
    const latest = readRetryPointer(latestPointerKey(memory.projectId));
    if (latest?.sessionId === pointer.sessionId) {
      removeRetryPointer(latestPointerKey(memory.projectId));
    }
  }
  memorySessions.delete(pointer.sessionId);
  for (const [id, handle] of memoryHandles) {
    if (handle.sessionId === pointer.sessionId) memoryHandles.delete(id);
  }
  const database = await openDatabase();
  if (!database) return;
  try {
    const transaction = database.transaction(
      [SESSION_STORE, HANDLE_STORE],
      "readwrite",
    );
    transaction.objectStore(SESSION_STORE).delete(pointer.sessionId);
    const handleStore = transaction.objectStore(HANDLE_STORE);
    const index = handleStore.index("sessionId");
    const keys = await requestResult<IDBValidKey[]>(
      index.getAllKeys(pointer.sessionId),
    );
    for (const key of keys) handleStore.delete(key);
    await transactionComplete(transaction);
  } finally {
    database.close();
  }
}

export async function loadLatestCollectionSession(
  projectId: string,
): Promise<{ sessionId: string; record: CollectionResumeRecord } | undefined> {
  const pointer = readRetryPointer(latestPointerKey(projectId));
  if (!pointer) return undefined;
  const memory = memorySessions.get(pointer.sessionId);
  if (memory)
    return { sessionId: pointer.sessionId, record: stripSessionId(memory) };
  const database = await openDatabase();
  if (!database) return undefined;
  try {
    const stored = await requestResult<StoredSession | undefined>(
      database
        .transaction(SESSION_STORE, "readonly")
        .objectStore(SESSION_STORE)
        .get(pointer.sessionId),
    );
    if (!stored || !isResumeRecord(stored)) return undefined;
    memorySessions.set(pointer.sessionId, stored);
    return { sessionId: pointer.sessionId, record: stripSessionId(stored) };
  } finally {
    database.close();
  }
}

export async function saveCollectionFileHandles(
  sessionId: string,
  handles: readonly CollectionFileHandleRecord[],
): Promise<void> {
  if (handles.length === 0) return;
  const rows = handles.map<StoredHandle>((item) => ({
    ...item,
    id: `${sessionId}:${item.relativePath}`,
    sessionId,
  }));
  for (const row of rows) memoryHandles.set(row.id, row);
  const database = await openDatabase();
  if (!database) return;
  try {
    const transaction = database.transaction(HANDLE_STORE, "readwrite");
    const store = transaction.objectStore(HANDLE_STORE);
    for (const row of rows) store.put(row);
    await transactionComplete(transaction);
  } catch (error) {
    // Some browsers expose directory selection but reject structured cloning
    // of file handles. The verified server session remains resumable; users are
    // asked to reselect files instead of storing bytes or paths elsewhere.
    if (error instanceof DOMException && error.name === "DataCloneError")
      return;
    throw error;
  } finally {
    database.close();
  }
}

export async function restoreCollectionFiles(
  sessionId: string,
): Promise<File[]> {
  const rows = [...memoryHandles.values()].filter(
    (row) => row.sessionId === sessionId,
  );
  const database = rows.length === 0 ? await openDatabase() : undefined;
  try {
    const stored =
      rows.length > 0
        ? rows
        : database
          ? await requestResult<StoredHandle[]>(
              database
                .transaction(HANDLE_STORE, "readonly")
                .objectStore(HANDLE_STORE)
                .index("sessionId")
                .getAll(sessionId),
            )
          : [];
    const files: File[] = [];
    for (const row of stored) {
      const permission = await queryHandlePermission(row.handle);
      if (permission !== "granted") continue;
      const file = await row.handle.getFile();
      Object.defineProperty(file, "webkitRelativePath", {
        configurable: true,
        value: row.relativePath,
      });
      files.push(file);
    }
    return files;
  } finally {
    database?.close();
  }
}

export function collectionRetryPointerKey(
  projectId: string,
  sourceFingerprint: string,
): string {
  return `akc:collection:pointer:v2:${projectId}:${sourceFingerprint}`;
}

function readRetryPointer(key: string): RetryPointer | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const value = JSON.parse(window.localStorage.getItem(key) ?? "") as unknown;
    if (
      typeof value === "object" &&
      value !== null &&
      "schemaVersion" in value &&
      value.schemaVersion === 2 &&
      "sessionId" in value &&
      typeof value.sessionId === "string"
    ) {
      return { schemaVersion: 2, sessionId: value.sessionId };
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function writeRetryPointer(key: string, value: RetryPointer): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

function removeRetryPointer(key: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(key);
}

function latestPointerKey(projectId: string): string {
  return `akc:collection:latest:v2:${projectId}`;
}

function stripSessionId(value: StoredSession): CollectionResumeRecord {
  const record: Partial<StoredSession> = { ...value };
  delete record.id;
  return record as CollectionResumeRecord;
}

function isResumeRecord(value: unknown): value is StoredSession {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "string" &&
    "collectionId" in value &&
    typeof value.collectionId === "string" &&
    "sourceRootId" in value &&
    typeof value.sourceRootId === "string" &&
    "projectId" in value &&
    typeof value.projectId === "string" &&
    "sourceFingerprint" in value &&
    typeof value.sourceFingerprint === "string" &&
    "limitations" in value &&
    Array.isArray(value.limitations) &&
    value.limitations.every((item) => typeof item === "string") &&
    "pendingReceipts" in value &&
    Array.isArray(value.pendingReceipts)
  );
}

async function queryHandlePermission(
  handle: FileSystemFileHandle,
): Promise<PermissionState> {
  const query = (
    handle as FileSystemFileHandle & {
      queryPermission?: (options: { mode: "read" }) => Promise<PermissionState>;
    }
  ).queryPermission;
  return query ? query.call(handle, { mode: "read" }) : "prompt";
}

function openDatabase(): Promise<IDBDatabase | undefined> {
  if (typeof indexedDB === "undefined") return Promise.resolve(undefined);
  return new Promise((resolve) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(SESSION_STORE)) {
        database.createObjectStore(SESSION_STORE, { keyPath: "id" });
      }
      if (!database.objectStoreNames.contains(HANDLE_STORE)) {
        const store = database.createObjectStore(HANDLE_STORE, {
          keyPath: "id",
        });
        store.createIndex("sessionId", "sessionId", { unique: false });
      }
      if (!database.objectStoreNames.contains(RUNTIME_STORE)) {
        database.createObjectStore(RUNTIME_STORE, { keyPath: "collectionId" });
      }
    };
    request.onerror = () => resolve(undefined);
    request.onblocked = () => resolve(undefined);
    request.onsuccess = () => resolve(request.result);
  });
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(request.error ?? new Error("IndexedDB request failed"));
  });
}

function transactionComplete(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () =>
      reject(transaction.error ?? new Error("IndexedDB transaction failed"));
    transaction.onabort = () =>
      reject(transaction.error ?? new Error("IndexedDB transaction aborted"));
  });
}
