export const QUICK_CONVERT_MAX_FILE_BYTES = 50 * 1024 * 1024;
export const QUICK_CONVERT_MAX_FILE_LABEL = "50 MB";
export const QUICK_CONVERT_MAX_FILES = 30;

export function partitionFilesBySize<T extends { size: number }>(
  files: readonly T[],
  maximumBytes = QUICK_CONVERT_MAX_FILE_BYTES,
): { accepted: T[]; rejected: T[] } {
  const accepted: T[] = [];
  const rejected: T[] = [];

  for (const file of files) {
    (file.size <= maximumBytes ? accepted : rejected).push(file);
  }

  return { accepted, rejected };
}
