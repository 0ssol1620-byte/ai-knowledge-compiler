export interface DisplayDocumentMetadata {
  fileType: string;
  semanticType: string;
  semanticClassificationAvailable: boolean;
}

export function normalizedDocumentVersion(
  primary: number | null | undefined,
  fallback: number | null | undefined,
): number | undefined {
  for (const candidate of [primary, fallback]) {
    if (
      typeof candidate === "number" &&
      Number.isSafeInteger(candidate) &&
      candidate > 0
    ) {
      return candidate;
    }
  }
  return undefined;
}

function nonEmpty(value: string | null | undefined): string | undefined {
  const normalized = value?.trim();
  return normalized ? normalized : undefined;
}

export function displayDocumentMetadata(
  fileType: string | null | undefined,
  semanticType: string | null | undefined,
): DisplayDocumentMetadata {
  const sourceType = nonEmpty(fileType);
  const semantic = nonEmpty(semanticType);
  return {
    fileType: sourceType?.toLocaleUpperCase() ?? "Unknown",
    semanticType: semantic?.replaceAll("_", " ") ?? "Not classified",
    semanticClassificationAvailable: semantic !== undefined,
  };
}
