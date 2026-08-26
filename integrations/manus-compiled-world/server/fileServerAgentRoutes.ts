import type { Express } from "express";
import { z } from "zod";
import { getConnectionForProject, getFileServerAgent, markFileServerAgentHeartbeat, recordAgentAuditEvent, upsertConnection } from "./db";
import { enrollmentHashMatches, parseEnrollmentCredential } from "./fileServerAgentProtocol";

const heartbeatBody = z.object({ agentId: z.number().int().positive().optional(), version: z.string().trim().min(1).max(80).optional() });

export function registerFileServerAgentRoutes(app: Express) {
  app.post("/api/file-server/heartbeat", async (req, res) => {
    try {
      const parsed = parseEnrollmentCredential(req.header("authorization")?.replace(/^Bearer\s+/i, ""));
      if (!parsed) return res.status(401).json({ error: "A valid agent enrollment credential is required." });
      const body = heartbeatBody.parse(req.body);
      if (body.agentId && body.agentId !== parsed.agentId) return res.status(401).json({ error: "Agent credential does not match request body." });
      const agent = await getFileServerAgent(parsed.agentId);
      if (!agent || agent.status === "revoked" || !enrollmentHashMatches(parsed.secret, agent.enrollmentSecretHash)) return res.status(401).json({ error: "Agent enrollment is invalid or revoked." });
      const wasPending = agent.status === "pending";
      const updated = await markFileServerAgentHeartbeat(agent.id);
      const connection = await getConnectionForProject(agent.projectId, "file_server");
      if (connection?.status !== "revoked") await upsertConnection({ projectId: agent.projectId, provider: "file_server", status: "active", scopeSummary: connection?.scopeSummary ?? "Customer-selected roots · outbound TLS only · content collection disabled", lastSyncedAt: new Date(), lastError: null });
      if (wasPending) await recordAgentAuditEvent({ projectId: agent.projectId, agentId: agent.id, eventType: "agent_enrolled", detailJson: JSON.stringify({ version: body.version ?? "unspecified", collectionMode: "heartbeat_only" }) });
      return res.status(200).json({ status: updated?.status ?? "active", collectionMode: "heartbeat_only", nextHeartbeatSeconds: 300, instruction: "No file content is accepted by this endpoint." });
    } catch (error) {
      console.error("[file-server-agent] heartbeat rejected", error);
      return res.status(400).json({ error: "Agent heartbeat could not be verified." });
    }
  });
}
