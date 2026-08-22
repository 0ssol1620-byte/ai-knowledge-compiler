export type CompatibilityQuery = Record<
  string,
  string | string[] | undefined
>;

const SAFE_COMPATIBILITY_KEYS = new Set([
  "block",
  "collection",
  "document",
  "filter",
  "focus",
  "job",
  "page",
  "project",
  "reference",
]);

/**
 * Preserve legacy review-route context while moving every user-facing entry
 * point to the v4 Integrity Console. Document identity remains an optional
 * compatibility hint; the console still requires an authoritative collection
 * before it loads live evidence.
 */
export function integrityCompatibilityTarget(
  query: CompatibilityQuery,
  options: { documentId?: string } = {},
): string {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (!SAFE_COMPATIBILITY_KEYS.has(key)) continue;
    if (typeof value === "string") {
      parameters.append(key, value);
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) parameters.append(key, item);
    }
  }
  if (options.documentId) parameters.set("document", options.documentId);
  const encoded = parameters.toString();
  return encoded ? `/integrity?${encoded}` : "/integrity";
}
