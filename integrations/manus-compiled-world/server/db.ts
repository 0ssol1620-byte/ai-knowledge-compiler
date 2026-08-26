import { and, desc, eq } from "drizzle-orm";
import { drizzle } from "drizzle-orm/mysql2";
import { agentAuditEvents, compileRuns, fileServerAgents, InsertUser, knowledgeProjects, knowledgeSources, sourceConnections, users } from "../drizzle/schema";
import { ENV } from './_core/env';

let _db: ReturnType<typeof drizzle> | null = null;

// Lazily create the drizzle instance so local tooling can run without a DB.
export async function getDb() {
  if (!_db && process.env.DATABASE_URL) {
    try {
      _db = drizzle(process.env.DATABASE_URL);
    } catch (error) {
      console.warn("[Database] Failed to connect:", error);
      _db = null;
    }
  }
  return _db;
}

export async function upsertUser(user: InsertUser): Promise<void> {
  if (!user.openId) {
    throw new Error("User openId is required for upsert");
  }

  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot upsert user: database not available");
    return;
  }

  try {
    const values: InsertUser = {
      openId: user.openId,
    };
    const updateSet: Record<string, unknown> = {};

    const textFields = ["name", "email", "loginMethod"] as const;
    type TextField = (typeof textFields)[number];

    const assignNullable = (field: TextField) => {
      const value = user[field];
      if (value === undefined) return;
      const normalized = value ?? null;
      values[field] = normalized;
      updateSet[field] = normalized;
    };

    textFields.forEach(assignNullable);

    if (user.lastSignedIn !== undefined) {
      values.lastSignedIn = user.lastSignedIn;
      updateSet.lastSignedIn = user.lastSignedIn;
    }
    if (user.role !== undefined) {
      values.role = user.role;
      updateSet.role = user.role;
    } else if (user.openId === ENV.ownerOpenId) {
      values.role = 'admin';
      updateSet.role = 'admin';
    }

    if (!values.lastSignedIn) {
      values.lastSignedIn = new Date();
    }

    if (Object.keys(updateSet).length === 0) {
      updateSet.lastSignedIn = new Date();
    }

    await db.insert(users).values(values).onDuplicateKeyUpdate({
      set: updateSet,
    });
  } catch (error) {
    console.error("[Database] Failed to upsert user:", error);
    throw error;
  }
}

export async function getUserByOpenId(openId: string) {
  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot get user: database not available");
    return undefined;
  }

  const result = await db.select().from(users).where(eq(users.openId, openId)).limit(1);

  return result.length > 0 ? result[0] : undefined;
}

export async function listProjectsForOwner(ownerId: number) {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(knowledgeProjects).where(eq(knowledgeProjects.ownerId, ownerId)).orderBy(desc(knowledgeProjects.id));
}

export async function createProject(ownerId: number, name: string) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  const result = await db.insert(knowledgeProjects).values({ ownerId, name });
  const [project] = await db.select().from(knowledgeProjects).where(eq(knowledgeProjects.id, Number(result[0].insertId))).limit(1);
  return project;
}

export async function getProjectForOwner(ownerId: number, projectId: number) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  const [project] = await db.select().from(knowledgeProjects).where(and(eq(knowledgeProjects.id, projectId), eq(knowledgeProjects.ownerId, ownerId))).limit(1);
  if (!project) throw new Error("Project not found");
  return project;
}

export async function getSourcesForProject(projectId: number) {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(knowledgeSources).where(eq(knowledgeSources.projectId, projectId)).orderBy(desc(knowledgeSources.id));
}

export async function setProjectCanonicalSource(projectId: number, sourceId: number) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  await db.update(knowledgeProjects).set({ canonicalSourceId: sourceId }).where(eq(knowledgeProjects.id, projectId));
  const [project] = await db.select().from(knowledgeProjects).where(eq(knowledgeProjects.id, projectId)).limit(1);
  return project;
}

export async function findDuplicateSource(projectId: number, hash: string) {
  const db = await getDb();
  if (!db) return undefined;
  const [source] = await db.select().from(knowledgeSources).where(and(eq(knowledgeSources.projectId, projectId), eq(knowledgeSources.contentHash, hash))).limit(1);
  return source;
}

export async function createSource(input: {
  projectId: number; displayName: string; mimeType: string; byteSize: number; storageKey: string; storageUrl: string; contentHash: string; duplicateOfId: number | null;
}) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  const result = await db.insert(knowledgeSources).values({ ...input, sourceKind: "upload", duplicateOfId: input.duplicateOfId, status: "queued" });
  const [source] = await db.select().from(knowledgeSources).where(eq(knowledgeSources.id, Number(result[0].insertId))).limit(1);
  return source;
}

export async function startCompileRun(projectId: number) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  const result = await db.insert(compileRuns).values({ projectId, status: "running", stage: "intake", progress: 4 });
  const [run] = await db.select().from(compileRuns).where(eq(compileRuns.id, Number(result[0].insertId))).limit(1);
  return run;
}

export async function getCompileRun(id: number) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  const [run] = await db.select().from(compileRuns).where(eq(compileRuns.id, id)).limit(1);
  if (!run) throw new Error("Compile run not found");
  return run;
}

export async function updateCompileStage(id: number, stage: string, progress: number) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  await db.update(compileRuns).set({ status: "running", stage, progress }).where(eq(compileRuns.id, id));
  return getCompileRun(id);
}

export async function finishCompileRun(id: number, input: { status: "ready" | "failed"; stage: string; progress: number; resultJson?: string; errorMessage?: string }) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  await db.update(compileRuns).set({ ...input, completedAt: new Date() }).where(eq(compileRuns.id, id));
  const [run] = await db.select().from(compileRuns).where(eq(compileRuns.id, id)).limit(1);
  return run;
}

export type ConnectionProvider = "google_drive" | "sharepoint" | "file_server";
export type ConnectionStatus = "setup_required" | "pending_authorization" | "active" | "revoked" | "error";

export async function listConnectionsForProject(projectId: number) {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(sourceConnections).where(eq(sourceConnections.projectId, projectId));
}

export async function getConnectionForProject(projectId: number, provider: ConnectionProvider) {
  const db = await getDb();
  if (!db) return undefined;
  const [connection] = await db.select().from(sourceConnections).where(and(eq(sourceConnections.projectId, projectId), eq(sourceConnections.provider, provider))).limit(1);
  return connection;
}

export async function upsertConnection(input: {
  projectId: number;
  provider: ConnectionProvider;
  status: ConnectionStatus;
  scopeSummary: string;
  externalAccountId?: string | null;
  externalRootId?: string | null;
  encryptedAccessToken?: string | null;
  encryptedRefreshToken?: string | null;
  agentEnrollmentHash?: string | null;
  lastSyncedAt?: Date | null;
  lastError?: string | null;
}) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  const existing = await getConnectionForProject(input.projectId, input.provider);
  if (existing) {
    await db.update(sourceConnections).set(input).where(eq(sourceConnections.id, existing.id));
    const [updated] = await db.select().from(sourceConnections).where(eq(sourceConnections.id, existing.id)).limit(1);
    return updated;
  }
  const result = await db.insert(sourceConnections).values(input);
  const [created] = await db.select().from(sourceConnections).where(eq(sourceConnections.id, Number(result[0].insertId))).limit(1);
  return created;
}

export type FileServerAgentStatus = "pending" | "active" | "revoked" | "error";

export async function createFileServerAgent(input: { projectId: number; name: string; scopedRootsJson: string; enrollmentSecretHash: string }) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  const result = await db.insert(fileServerAgents).values(input);
  const [agent] = await db.select().from(fileServerAgents).where(eq(fileServerAgents.id, Number(result[0].insertId))).limit(1);
  return agent;
}

export async function getFileServerAgent(agentId: number) {
  const db = await getDb();
  if (!db) return undefined;
  const [agent] = await db.select().from(fileServerAgents).where(eq(fileServerAgents.id, agentId)).limit(1);
  return agent;
}

export async function listFileServerAgentsForProject(projectId: number) {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(fileServerAgents).where(eq(fileServerAgents.projectId, projectId)).orderBy(desc(fileServerAgents.id));
}

export async function markFileServerAgentHeartbeat(agentId: number) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  await db.update(fileServerAgents).set({ status: "active", lastHeartbeatAt: new Date(), lastError: null }).where(eq(fileServerAgents.id, agentId));
  return getFileServerAgent(agentId);
}

export async function revokeFileServerAgent(agentId: number) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  await db.update(fileServerAgents).set({ status: "revoked" }).where(eq(fileServerAgents.id, agentId));
  return getFileServerAgent(agentId);
}

export async function recordAgentAuditEvent(input: { projectId: number; agentId?: number | null; eventType: string; detailJson: string }) {
  const db = await getDb();
  if (!db) throw new Error("Database unavailable");
  const result = await db.insert(agentAuditEvents).values({ ...input, agentId: input.agentId ?? null });
  const [event] = await db.select().from(agentAuditEvents).where(eq(agentAuditEvents.id, Number(result[0].insertId))).limit(1);
  return event;
}

export async function listAgentAuditEventsForProject(projectId: number) {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(agentAuditEvents).where(eq(agentAuditEvents.projectId, projectId)).orderBy(desc(agentAuditEvents.id)).limit(12);
}
