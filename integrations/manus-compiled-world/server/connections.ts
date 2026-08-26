import { z } from "zod";
import { getProjectForOwner, listConnectionsForProject, upsertConnection } from "./db";
import { createConnectionState, authorizationUrl, isProviderConfigured, scopeSummary, type CloudProvider } from "./providerOAuth";
import { protectedProcedure, router } from "./_core/trpc";
import { fileServerAgentRouter } from "./fileServerAgents";

const providerSchema = z.enum(["google_drive", "sharepoint"]);

export const connectionRouter = router({
  agent: fileServerAgentRouter,
  list: protectedProcedure.input(z.object({ projectId: z.number().int().positive() })).query(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    return listConnectionsForProject(input.projectId);
  }),
  start: protectedProcedure.input(z.object({ projectId: z.number().int().positive(), provider: providerSchema })).mutation(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    const provider = input.provider as CloudProvider;
    if (!isProviderConfigured(provider)) {
      await upsertConnection({ projectId: input.projectId, provider, status: "setup_required", scopeSummary: scopeSummary(provider), lastError: "TAVONEL service registration is not configured." });
      return { configured: false as const, authorizationUrl: null };
    }
    await upsertConnection({ projectId: input.projectId, provider, status: "pending_authorization", scopeSummary: scopeSummary(provider), lastError: null });
    return {
      configured: true as const,
      authorizationUrl: authorizationUrl(provider, createConnectionState({ provider, projectId: input.projectId, userId: ctx.user.id })),
    };
  }),
  disconnect: protectedProcedure.input(z.object({ projectId: z.number().int().positive(), provider: providerSchema })).mutation(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    return upsertConnection({ projectId: input.projectId, provider: input.provider, status: "revoked", scopeSummary: scopeSummary(input.provider), encryptedAccessToken: null, encryptedRefreshToken: null, lastError: null });
  }),
});
