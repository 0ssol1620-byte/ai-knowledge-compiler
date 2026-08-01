import { createSHA256 } from "hash-wasm";

type HashRequest = {
  id: string;
  blob: Blob;
  chunkSize: number;
};

type HashResponse =
  | { id: string; kind: "progress"; bytes: number; total: number }
  | { id: string; kind: "complete"; sha256: string }
  | { id: string; kind: "error"; message: string };

const workerScope = self as unknown as {
  onmessage: ((event: MessageEvent<HashRequest>) => void) | null;
  postMessage: (message: HashResponse) => void;
};

workerScope.onmessage = (event) => {
  const request = event.data;
  void hashBlob(request).catch((error: unknown) => {
    workerScope.postMessage({
      id: request.id,
      kind: "error",
      message: error instanceof Error ? error.message : "SHA-256 worker failed",
    });
  });
};

async function hashBlob(request: HashRequest): Promise<void> {
  const chunkSize = Math.max(
    4 * 1024 * 1024,
    Math.min(16 * 1024 * 1024, Math.floor(request.chunkSize)),
  );
  const hasher = await createSHA256();
  hasher.init();
  for (let offset = 0; offset < request.blob.size; offset += chunkSize) {
    const end = Math.min(offset + chunkSize, request.blob.size);
    hasher.update(new Uint8Array(await request.blob.slice(offset, end).arrayBuffer()));
    workerScope.postMessage({
      id: request.id,
      kind: "progress",
      bytes: end,
      total: request.blob.size,
    });
  }
  workerScope.postMessage({
    id: request.id,
    kind: "complete",
    sha256: hasher.digest("hex"),
  });
}

export {};
