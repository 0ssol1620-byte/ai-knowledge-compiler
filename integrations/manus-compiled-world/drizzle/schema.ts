import { index, int, mysqlEnum, mysqlTable, text, timestamp, varchar } from "drizzle-orm/mysql-core";

/**
 * Core user table backing auth flow.
 * Extend this file with additional tables as your product grows.
 * Columns use camelCase to match both database fields and generated types.
 */
export const users = mysqlTable("users", {
  /**
   * Surrogate primary key. Auto-incremented numeric value managed by the database.
   * Use this for relations between tables.
   */
  id: int("id").autoincrement().primaryKey(),
  /** Manus OAuth identifier (openId) returned from the OAuth callback. Unique per user. */
  openId: varchar("openId", { length: 64 }).notNull().unique(),
  name: text("name"),
  email: varchar("email", { length: 320 }),
  loginMethod: varchar("loginMethod", { length: 64 }),
  role: mysqlEnum("role", ["user", "admin"]).default("user").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  lastSignedIn: timestamp("lastSignedIn").defaultNow().notNull(),
});

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;

/** A private customer knowledge space. File bytes always live in object storage. */
export const knowledgeProjects = mysqlTable("knowledge_projects", {
  id: int("id").autoincrement().primaryKey(),
  ownerId: int("owner_id").notNull(),
  name: varchar("name", { length: 160 }).notNull(),
  canonicalSourceId: int("canonical_source_id"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().onUpdateNow().notNull(),
}, (table) => [index("knowledge_projects_owner_idx").on(table.ownerId)]);

/** Metadata and S3 reference for one customer-owned source. Never store file bytes in SQL. */
export const knowledgeSources = mysqlTable("knowledge_sources", {
  id: int("id").autoincrement().primaryKey(),
  projectId: int("project_id").notNull(),
  sourceKind: mysqlEnum("source_kind", ["upload", "google_drive", "sharepoint", "file_server", "dropbox", "demo"]).notNull(),
  displayName: varchar("display_name", { length: 255 }).notNull(),
  mimeType: varchar("mime_type", { length: 160 }).notNull(),
  byteSize: int("byte_size").notNull(),
  storageKey: varchar("storage_key", { length: 512 }).notNull(),
  storageUrl: varchar("storage_url", { length: 512 }).notNull(),
  contentHash: varchar("content_hash", { length: 64 }).notNull(),
  duplicateOfId: int("duplicate_of_id"),
  status: mysqlEnum("source_status", ["stored", "queued", "processing", "ready", "failed"]).default("stored").notNull(),
  createdAt: timestamp("created_at").defaultNow().notNull(),
}, (table) => [
  index("knowledge_sources_project_idx").on(table.projectId),
  index("knowledge_sources_hash_idx").on(table.projectId, table.contentHash),
]);

/** A durable record of a single compile request and its evidence-first result. */
export const compileRuns = mysqlTable("compile_runs", {
  id: int("id").autoincrement().primaryKey(),
  projectId: int("project_id").notNull(),
  status: mysqlEnum("compile_status", ["queued", "running", "ready", "failed"]).default("queued").notNull(),
  stage: varchar("stage", { length: 64 }).default("queued").notNull(),
  progress: int("progress").default(0).notNull(),
  resultJson: text("result_json"),
  errorMessage: text("error_message"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  completedAt: timestamp("completed_at"),
}, (table) => [index("compile_runs_project_idx").on(table.projectId)]);

/** Customer-owned connection metadata. OAuth tokens must be encrypted server-side before storage. */
export const sourceConnections = mysqlTable("source_connections", {
  id: int("id").autoincrement().primaryKey(),
  projectId: int("project_id").notNull(),
  provider: mysqlEnum("provider", ["google_drive", "sharepoint", "file_server"]).notNull(),
  status: mysqlEnum("connection_status", ["setup_required", "pending_authorization", "active", "revoked", "error"]).default("setup_required").notNull(),
  scopeSummary: varchar("scope_summary", { length: 255 }).notNull(),
  externalAccountId: varchar("external_account_id", { length: 255 }),
  externalRootId: varchar("external_root_id", { length: 255 }),
  encryptedAccessToken: text("encrypted_access_token"),
  encryptedRefreshToken: text("encrypted_refresh_token"),
  agentEnrollmentHash: varchar("agent_enrollment_hash", { length: 64 }),
  lastSyncedAt: timestamp("last_synced_at"),
  lastError: text("last_error"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().onUpdateNow().notNull(),
}, (table) => [
  index("source_connections_project_idx").on(table.projectId),
  index("source_connections_provider_idx").on(table.projectId, table.provider),
]);

/** A customer-environment agent enrollment. It records no source bytes and never retains the raw enrollment secret. */
export const fileServerAgents = mysqlTable("file_server_agents", {
  id: int("id").autoincrement().primaryKey(),
  projectId: int("project_id").notNull(),
  name: varchar("name", { length: 160 }).notNull(),
  status: mysqlEnum("agent_status", ["pending", "active", "revoked", "error"]).default("pending").notNull(),
  scopedRootsJson: text("scoped_roots_json").notNull(),
  enrollmentSecretHash: varchar("enrollment_secret_hash", { length: 64 }).notNull(),
  lastHeartbeatAt: timestamp("last_heartbeat_at"),
  lastError: text("last_error"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().onUpdateNow().notNull(),
}, (table) => [index("file_server_agents_project_idx").on(table.projectId)]);

/** Immutable, reviewable control-plane events. Heartbeats update the agent timestamp without generating noisy audit rows. */
export const agentAuditEvents = mysqlTable("agent_audit_events", {
  id: int("id").autoincrement().primaryKey(),
  projectId: int("project_id").notNull(),
  agentId: int("agent_id"),
  eventType: varchar("event_type", { length: 80 }).notNull(),
  detailJson: text("detail_json").notNull(),
  createdAt: timestamp("created_at").defaultNow().notNull(),
}, (table) => [index("agent_audit_events_project_idx").on(table.projectId, table.id)]);

export type KnowledgeProject = typeof knowledgeProjects.$inferSelect;
export type KnowledgeSource = typeof knowledgeSources.$inferSelect;
export type CompileRun = typeof compileRuns.$inferSelect;
export type SourceConnection = typeof sourceConnections.$inferSelect;
export type FileServerAgent = typeof fileServerAgents.$inferSelect;
export type AgentAuditEvent = typeof agentAuditEvents.$inferSelect;
