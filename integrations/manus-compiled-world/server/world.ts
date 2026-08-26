import { desc, eq } from "drizzle-orm";
import { z } from "zod";
import { compileRuns, knowledgeSources } from "../drizzle/schema";
import { createProject, createSource, findDuplicateSource, finishCompileRun, getCompileRun, getDb, getProjectForOwner, getSourcesForProject, listProjectsForOwner, setProjectCanonicalSource, startCompileRun, updateCompileStage } from "./db";
import { invokeLLM } from "./_core/llm";
import { storageGetSignedUrl, storagePut } from "./storage";
import { protectedProcedure, router } from "./_core/trpc";
import { COMPILE_STAGES, contentHash, decodeUpload, fallbackAnalysis, safeFileName, selectPrimarySource, stageProgress } from "./worldUtils";
import { connectionRouter } from "./connections";

const sourceSchema = z.object({
  title: z.string(),
  documentKind: z.string(),
  summary: z.string(),
  entities: z.array(z.string()),
  directory: z.array(z.string()),
  flags: z.array(z.string()),
});

async function analyzeSource(source: typeof knowledgeSources.$inferSelect) {
  const fallback = fallbackAnalysis(source.displayName);
  const isPdf = source.mimeType === "application/pdf";
  const isImage = source.mimeType.startsWith("image/");
  if (!isPdf && !isImage) return fallback;

  try {
    const signedUrl = await storageGetSignedUrl(source.storageKey);
    const attachment = isPdf
      ? { type: "file_url" as const, file_url: { url: signedUrl, mime_type: "application/pdf" as const } }
      : { type: "image_url" as const, image_url: { url: signedUrl, detail: "auto" as const } };
    const response = await invokeLLM({
      model: "gpt-5-mini",
      messages: [
        {
          role: "system",
          content: "You extract a reviewable document map. Never invent page numbers, financial values, or evidence. If unreadable, put that limitation in flags. Output only the requested JSON.",
        },
        {
          role: "user",
          content: [
            { type: "text", text: "Describe this one customer-provided source. Suggest a compact, human-reviewable directory path and up to six entities." },
            attachment,
          ],
        },
      ],
      response_format: {
        type: "json_schema",
        json_schema: {
          name: "source_map",
          strict: true,
          schema: {
            type: "object",
            properties: {
              title: { type: "string" },
              documentKind: { type: "string" },
              summary: { type: "string" },
              entities: { type: "array", items: { type: "string" } },
              directory: { type: "array", items: { type: "string" } },
              flags: { type: "array", items: { type: "string" } },
            },
            required: ["title", "documentKind", "summary", "entities", "directory", "flags"],
            additionalProperties: false,
          },
        },
      },
    });
    const raw = response.choices[0]?.message.content;
    return { ...sourceSchema.parse(JSON.parse(typeof raw === "string" ? raw : "{}")), mode: "ai-assisted" as const };
  } catch (error) {
    console.warn("[world] AI-assisted source map unavailable", error);
    return { ...fallback, flags: ["AI pass unavailable — source remains queued for review"], mode: "metadata" as const };
  }
}

export const worldRouter = router({
  connections: connectionRouter,
  listProjects: protectedProcedure.query(async ({ ctx }) => listProjectsForOwner(ctx.user.id)),
  createProject: protectedProcedure.input(z.object({ name: z.string().trim().min(2).max(160) })).mutation(async ({ ctx, input }) => {
    return createProject(ctx.user.id, input.name);
  }),
  listSources: protectedProcedure.input(z.object({ projectId: z.number().int().positive() })).query(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    return getSourcesForProject(input.projectId);
  }),
  setCanonicalSource: protectedProcedure.input(z.object({ projectId: z.number().int().positive(), sourceId: z.number().int().positive() })).mutation(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    const source = (await getSourcesForProject(input.projectId)).find((candidate) => candidate.id === input.sourceId);
    if (!source) throw new Error("Source not found in this project.");
    if (source.duplicateOfId) throw new Error("A detected copy cannot be selected as the authority record.");
    await setProjectCanonicalSource(input.projectId, input.sourceId);
    return { projectId: input.projectId, sourceId: input.sourceId };
  }),
  uploadSource: protectedProcedure.input(z.object({
    projectId: z.number().int().positive(),
    fileName: z.string().min(1).max(255),
    mimeType: z.string().min(1).max(160),
    contentBase64: z.string().min(4),
  })).mutation(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    const bytes = decodeUpload(input.contentBase64);
    const hash = contentHash(bytes);
    const duplicate = await findDuplicateSource(input.projectId, hash);
    const cleanedName = safeFileName(input.fileName);
    const { key, url } = await storagePut(`customers/${ctx.user.id}/projects/${input.projectId}/${cleanedName}`, bytes, input.mimeType);
    return createSource({
      projectId: input.projectId,
      displayName: cleanedName,
      mimeType: input.mimeType,
      byteSize: bytes.length,
      storageKey: key,
      storageUrl: url,
      contentHash: hash,
      duplicateOfId: duplicate?.id ?? null,
    });
  }),
  beginCompile: protectedProcedure.input(z.object({ projectId: z.number().int().positive() })).mutation(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    const sources = await getSourcesForProject(input.projectId);
    if (!sources.length) throw new Error("Add a source before starting a compile pass.");
    return startCompileRun(input.projectId);
  }),
  advanceCompile: protectedProcedure.input(z.object({ runId: z.number().int().positive() })).mutation(async ({ ctx, input }) => {
    const run = await getCompileRun(input.runId);
    const project = await getProjectForOwner(ctx.user.id, run.projectId);
    if (run.status === "ready") return run;
    const currentIndex = COMPILE_STAGES.indexOf(run.stage as typeof COMPILE_STAGES[number]);
    if (currentIndex < 0) throw new Error("Compile run has an invalid stage.");
    if (run.stage !== "dedupe") {
      const nextStage = COMPILE_STAGES[currentIndex + 1];
      return updateCompileStage(run.id, nextStage, stageProgress(nextStage));
    }
    const sources = await getSourcesForProject(run.projectId);
    const { source: primarySource, selection } = selectPrimarySource(sources, project.canonicalSourceId);
    const analysis = await analyzeSource(primarySource);
    return finishCompileRun(run.id, {
      status: "ready",
      stage: "graph",
      progress: 100,
      resultJson: JSON.stringify({ sourceId: primarySource.id, sourceName: primarySource.displayName, selection, analysis, duplicateCount: sources.filter((source) => source.duplicateOfId).length }),
    });
  }),
  latestRun: protectedProcedure.input(z.object({ projectId: z.number().int().positive() })).query(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    const db = await getDb();
    if (!db) return undefined;
    const [run] = await db.select().from(compileRuns).where(eq(compileRuns.projectId, input.projectId)).orderBy(desc(compileRuns.id)).limit(1);
    return run;
  }),
});
