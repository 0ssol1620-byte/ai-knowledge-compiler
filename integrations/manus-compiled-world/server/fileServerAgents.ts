import { z } from "zod";
import { createFileServerAgent, getFileServerAgent, getProjectForOwner, listAgentAuditEventsForProject, listFileServerAgentsForProject, recordAgentAuditEvent, revokeFileServerAgent, upsertConnection } from "./db";
import { createEnrollmentSecret, enrollmentCredential, hashEnrollmentSecret, normalizeAgentRoots } from "./fileServerAgentProtocol";
import { protectedProcedure, router } from "./_core/trpc";

const projectInput = z.object({ projectId: z.number().int().positive() });

export const fileServerAgentRouter = router({
  overview: protectedProcedure.input(projectInput).query(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    const [agents, audit] = await Promise.all([listFileServerAgentsForProject(input.projectId), listAgentAuditEventsForProject(input.projectId)]);
    return { agents, audit };
  }),
  issueEnrollment: protectedProcedure.input(projectInput.extend({ name: z.string().trim().min(2).max(160), scopedRoots: z.array(z.string()).min(1).max(8) })).mutation(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    const scopedRoots = normalizeAgentRoots(input.scopedRoots);
    const secret = createEnrollmentSecret();
    const enrollmentSecretHash = hashEnrollmentSecret(secret);
    const scopeSummary = `${scopedRoots.length} customer-selected root${scopedRoots.length === 1 ? "" : "s"} · outbound TLS only · collection disabled until review`;
    await upsertConnection({ projectId: input.projectId, provider: "file_server", status: "pending_authorization", scopeSummary, externalRootId: scopedRoots.join("\n"), agentEnrollmentHash: enrollmentSecretHash, lastError: null });
    const agent = await createFileServerAgent({ projectId: input.projectId, name: input.name, scopedRootsJson: JSON.stringify(scopedRoots), enrollmentSecretHash });
    await recordAgentAuditEvent({ projectId: input.projectId, agentId: agent.id, eventType: "enrollment_issued", detailJson: JSON.stringify({ roots: scopedRoots, mode: "heartbeat_only" }) });
    return { agent: { id: agent.id, name: agent.name, scopedRoots }, enrollmentCode: enrollmentCredential(agent.id, secret), heartbeatPath: "/api/file-server/heartbeat", collectionMode: "heartbeat_only" as const };
  }),
  revoke: protectedProcedure.input(projectInput.extend({ agentId: z.number().int().positive() })).mutation(async ({ ctx, input }) => {
    await getProjectForOwner(ctx.user.id, input.projectId);
    const agent = await getFileServerAgent(input.agentId);
    if (!agent || agent.projectId !== input.projectId) throw new Error("File server agent not found in this project.");
    const revoked = await revokeFileServerAgent(agent.id);
    await upsertConnection({ projectId: input.projectId, provider: "file_server", status: "revoked", scopeSummary: "Enrollment revoked · outbound agent disabled", agentEnrollmentHash: null, lastError: null });
    await recordAgentAuditEvent({ projectId: input.projectId, agentId: agent.id, eventType: "enrollment_revoked", detailJson: JSON.stringify({ by: "project_owner" }) });
    return revoked;
  }),
});
