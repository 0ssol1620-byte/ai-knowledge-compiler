export type IntakeFileLike = {
  name: string;
  size: number;
  type?: string;
  lastModified?: number;
  webkitRelativePath?: string;
};

export type IntakeManifestEntry<T extends IntakeFileLike = IntakeFileLike> = {
  file: T;
  relativePath: string;
  extension: string;
  provisionalFingerprint: string;
  duplicateOf?: string;
};

export type IntakeManifest<T extends IntakeFileLike = IntakeFileLike> = {
  accepted: IntakeManifestEntry<T>[];
  rejected: Array<{ file: T; reason: string }>;
  totalBytes: number;
  duplicateCandidates: number;
  uniqueCandidates: number;
  formats: Array<{ extension: string; count: number }>;
};

export const COLLECTION_MAX_FILES = 5_000;
export const COLLECTION_MAX_BYTES = 10 * 1024 * 1024 * 1024;

export type CollectionManifestLimitState = {
  withinLimits: boolean;
  fileLimitExceeded: boolean;
  byteLimitExceeded: boolean;
};

const FALLBACK_EXTENSION = "other";

export function safeRelativePath(file: IntakeFileLike): string | undefined {
  const candidate = (file.webkitRelativePath || file.name)
    .replaceAll("\\", "/")
    .trim();
  if (!candidate || candidate.startsWith("/") || candidate.includes("\0")) {
    return undefined;
  }
  const segments = candidate.split("/");
  if (
    segments.some(
      (segment) =>
        !segment ||
        segment === "." ||
        segment === ".." ||
        /^[a-zA-Z]:$/.test(segment),
    )
  ) {
    return undefined;
  }
  return segments.join("/");
}

function extensionFor(path: string): string {
  const filename = path.split("/").at(-1) ?? path;
  const dot = filename.lastIndexOf(".");
  if (dot <= 0 || dot === filename.length - 1) return FALLBACK_EXTENSION;
  return filename.slice(dot + 1).toLowerCase();
}

function provisionalFingerprint(file: IntakeFileLike): string {
  return [
    file.name.toLocaleLowerCase(),
    file.size,
    file.lastModified ?? 0,
    file.type ?? "",
  ].join(":");
}

export function buildIntakeManifest<T extends IntakeFileLike>(
  files: readonly T[],
): IntakeManifest<T> {
  const accepted: IntakeManifestEntry<T>[] = [];
  const rejected: Array<{ file: T; reason: string }> = [];
  const firstPathByFingerprint = new Map<string, string>();
  const formatCounts = new Map<string, number>();

  for (const file of files) {
    const relativePath = safeRelativePath(file);
    if (!relativePath) {
      rejected.push({ file, reason: "unsafe_relative_path" });
      continue;
    }
    const fingerprint = provisionalFingerprint(file);
    const duplicateOf = firstPathByFingerprint.get(fingerprint);
    if (!duplicateOf) firstPathByFingerprint.set(fingerprint, relativePath);
    const extension = extensionFor(relativePath);
    formatCounts.set(extension, (formatCounts.get(extension) ?? 0) + 1);
    accepted.push({
      file,
      relativePath,
      extension,
      provisionalFingerprint: fingerprint,
      ...(duplicateOf ? { duplicateOf } : {}),
    });
  }

  const duplicateCandidates = accepted.filter(
    (entry) => entry.duplicateOf,
  ).length;
  return {
    accepted,
    rejected,
    totalBytes: accepted.reduce((total, entry) => total + entry.file.size, 0),
    duplicateCandidates,
    uniqueCandidates: accepted.length - duplicateCandidates,
    formats: [...formatCounts.entries()]
      .map(([extension, count]) => ({ extension, count }))
      .sort(
        (left, right) =>
          right.count - left.count ||
          left.extension.localeCompare(right.extension),
      ),
  };
}

export function collectionManifestLimitState(
  manifest: Pick<IntakeManifest, "accepted" | "totalBytes">,
): CollectionManifestLimitState {
  const fileLimitExceeded = manifest.accepted.length > COLLECTION_MAX_FILES;
  const byteLimitExceeded = manifest.totalBytes > COLLECTION_MAX_BYTES;
  return {
    withinLimits: !fileLimitExceeded && !byteLimitExceeded,
    fileLimitExceeded,
    byteLimitExceeded,
  };
}

export function mergeIntakeFiles<T extends IntakeFileLike>(
  current: readonly T[],
  incoming: readonly T[],
): T[] {
  const next = [...current];
  const seen = new Set(
    current.map(
      (file) =>
        `${safeRelativePath(file) ?? "unsafe"}:${provisionalFingerprint(file)}`,
    ),
  );
  for (const file of incoming) {
    const key = `${safeRelativePath(file) ?? "unsafe"}:${provisionalFingerprint(file)}`;
    if (!seen.has(key)) {
      seen.add(key);
      next.push(file);
    }
  }
  return next;
}
