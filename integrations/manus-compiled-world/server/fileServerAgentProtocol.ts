import crypto from "node:crypto";

const ROOT_LIMIT = 8;
const ROOT_LENGTH_LIMIT = 300;

export function normalizeAgentRoots(values: string[]) {
  const roots = values.map(value => value.trim().replace(/\\/g, "/").replace(/\/+$/, "")).filter(Boolean);
  if (!roots.length) throw new Error("Choose at least one customer-approved root before issuing an enrollment code.");
  if (roots.length > ROOT_LIMIT) throw new Error(`An agent may have up to ${ROOT_LIMIT} scoped roots.`);
  if (roots.some(root => root.length > ROOT_LENGTH_LIMIT || /[\u0000-\u001f]/.test(root))) throw new Error("A scoped root is not valid.");
  return Array.from(new Set(roots));
}

export function createEnrollmentSecret() {
  return crypto.randomBytes(24).toString("base64url");
}

export function hashEnrollmentSecret(secret: string) {
  return crypto.createHash("sha256").update(secret).digest("hex");
}

export function enrollmentCredential(agentId: number, secret: string) {
  return `tavonel-agent.${agentId}.${secret}`;
}

export function parseEnrollmentCredential(value: string | undefined) {
  const match = /^tavonel-agent\.(\d+)\.([A-Za-z0-9_-]{20,})$/.exec(value ?? "");
  if (!match) return null;
  return { agentId: Number(match[1]), secret: match[2] };
}

export function enrollmentHashMatches(secret: string, expectedHash: string) {
  const candidate = Buffer.from(hashEnrollmentSecret(secret), "hex");
  const expected = Buffer.from(expectedHash, "hex");
  return candidate.length === expected.length && crypto.timingSafeEqual(candidate, expected);
}
