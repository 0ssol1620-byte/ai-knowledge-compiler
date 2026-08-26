import crypto from "node:crypto";

export const MAX_PILOT_UPLOAD_BYTES = 5 * 1024 * 1024;
export const COMPILE_STAGES = ["intake", "scan", "dedupe", "graph"] as const;
export type CompileStage = (typeof COMPILE_STAGES)[number];

export function stageProgress(stage: CompileStage) {
  return { intake: 12, scan: 38, dedupe: 68, graph: 100 }[stage];
}

export function decodeUpload(contentBase64: string) {
  const base64 = contentBase64.replace(/^data:[^;]+;base64,/, "");
  const bytes = Buffer.from(base64, "base64");
  if (!bytes.length || bytes.length > MAX_PILOT_UPLOAD_BYTES) {
    throw new Error("Pilot uploads must be between 1 byte and 5 MB.");
  }
  return bytes;
}

export function safeFileName(name: string) {
  return name.replace(/[^a-zA-Z0-9._ -]/g, "_").slice(0, 180) || "source";
}

export function contentHash(bytes: Buffer) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

export function fallbackAnalysis(filename: string) {
  const stem = filename.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ");
  return {
    title: stem || "Untitled source",
    documentKind: "Source document",
    summary: "Stored as a reviewable source. Run the compile pass again after adding a PDF or image to generate AI-assisted structure.",
    entities: [] as string[],
    directory: ["Sources", "Review queue", stem || "Untitled source"],
    flags: ["Manual review recommended"],
    mode: "metadata" as const,
  };
}

export function selectPrimarySource<T extends { id: number; duplicateOfId: number | null }>(sources: T[], canonicalSourceId: number | null) {
  const canonical = canonicalSourceId ? sources.find((source) => source.id === canonicalSourceId && !source.duplicateOfId) : undefined;
  const fallback = sources.find((source) => !source.duplicateOfId) ?? sources[0];
  if (!fallback) throw new Error("Add a source before starting a compile pass.");
  return { source: canonical ?? fallback, selection: canonical ? "review-selected" as const : "automatic" as const };
}
