/**
 * Joined phase `revoke` (WO-D20-3): a member, an API key and a remote MCP grant are revoked after activation, and each
 * one's next call is refused. Implements phase-contract.mjs; the summary is fixed enums and counts only.
 *
 *   control  Before anything is revoked every call must succeed. A refusal afterwards proves nothing if the call was
 *            already broken (control = "broken" fails the phase and nothing is revoked).
 *   member   DELETE /api/workspaces/{ws}/members/{id} by the owner. The member's next ask, search, lens read and export
 *            are each refused: status in {401,403,404,409}, Cache-Control no-store, body keys within {code, documentIds},
 *            and no collection id, workspace key or caller-supplied leak term anywhere in the body.
 *            (A role downgrade admin -> member keeps read access, so it is not a refusal case and is not tested here.)
 *   api key  DELETE /api/developer/keys/{id} by the owner. The shipped CLI and MCP stdio server with that key get 401 on
 *            the next call; the owner session still answers.
 *   remote   POST /api/internal/remote-mcp/revoke-all with the worker secret. Endpoint off (the production default):
 *            reported off_not_exercised. On: the next tools/call is 401 and the seconds to refusal are recorded.
 *   connector  Simulated. No provider account exists, so no provider call is made and nothing is claimed about one.
 *
 * `state` must carry (a missing or ill-typed key throws PHASE_STATE_INVALID; nothing is defaulted):
 *   ownerToken, collectionId, workspaceKey, question, leakTerms[]  - strings / non-empty array of non-empty strings
 *   member { userId, token }, apiKey { id }
 *   runConsumer(script, args, stdin) - the harness's owned-child runner with the API key in its environment
 *   remoteMcp { enabled: boolean, token, workerSecret } - token and workerSecret strings only when enabled
 * `app(resource, bearer, body, method, extraHeaders)` must resolve { status, body, headers } (headers: lower-case keys);
 * a result without `headers` makes the no-store rule unobservable and the phase fails closed on it.
 */
import { COUNT, PhaseContractError, booleanFlagState, definePhase } from "./phase-contract.mjs";

export const REFUSAL_STATUSES = Object.freeze([401, 403, 404, 409]);
const ALLOWED_BODY_KEYS = Object.freeze(["code", "documentIds"]);
const ROUTE = ["refused", "not_refused", "bad_body", "no_store_missing", "no_store_unobservable"];
const CONSUMER = ["refused", "not_refused"];
const STEP_MS = 120_000;
const MAX_DOCUMENT_IDS = 1000;

const invalid = key => { throw new PhaseContractError("PHASE_STATE_INVALID", key); };
const text = (value, key) => (typeof value === "string" && value.length > 0 ? value : invalid(key));
const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);

function readState(state) {
  const member = isObject(state.member) ? state.member : invalid("member");
  const apiKey = isObject(state.apiKey) ? state.apiKey : invalid("apiKey");
  const remote = isObject(state.remoteMcp) ? state.remoteMcp : invalid("remoteMcp");
  const remoteEndpoint = booleanFlagState(remote.enabled, "remote_mcp");
  if (!Array.isArray(state.leakTerms) || state.leakTerms.length === 0) invalid("leakTerms");
  if (typeof state.runConsumer !== "function") invalid("runConsumer");
  return {
    ownerToken: text(state.ownerToken, "ownerToken"), collectionId: text(state.collectionId, "collectionId"),
    workspaceKey: text(state.workspaceKey, "workspaceKey"), question: text(state.question, "question"),
    leakTerms: state.leakTerms.map((term, index) => text(term, `leakTerms.${index}`)),
    member: { userId: text(member.userId, "member.userId"), token: text(member.token, "member.token") },
    apiKeyId: text(apiKey.id, "apiKey.id"), runConsumer: state.runConsumer, remoteEndpoint,
    remoteToken: remoteEndpoint === "on" ? text(remote.token, "remoteMcp.token") : null,
    workerSecret: remoteEndpoint === "on" ? text(remote.workerSecret, "remoteMcp.workerSecret") : null,
  };
}

/** Why a refusal is not clean, or "refused". Pure; the one place the WO-D15-3 rule set lives. */
export function judgeRefusal(result, probes) {
  if (!isObject(result) || !REFUSAL_STATUSES.includes(result.status)) return "not_refused";
  const cache = result.headers?.["cache-control"];
  if (!isObject(result.headers)) return "no_store_unobservable";
  if (typeof cache !== "string" || !cache.toLowerCase().split(",").map(part => part.trim()).includes("no-store")) return "no_store_missing";
  const body = result.body ?? null;
  if (body !== null) {
    if (!isObject(body) || Object.keys(body).some(key => !ALLOWED_BODY_KEYS.includes(key))) return "bad_body";
    if (Object.hasOwn(body, "code") && typeof body.code !== "string") return "bad_body";
    if (Object.hasOwn(body, "documentIds") && !(Array.isArray(body.documentIds) && body.documentIds.length <= MAX_DOCUMENT_IDS
      && body.documentIds.every(id => typeof id === "string"))) return "bad_body";
  }
  const seen = `${JSON.stringify(body)}\n${typeof result.text === "string" ? result.text : ""}`.toLowerCase();
  return probes.some(probe => seen.includes(probe.toLowerCase())) ? "bad_body" : "refused";
}

/** CLI: "ok" answered, "refused" exited 1 with the API's own 401, "other" any other API status. Timeout/spawn failures are operational and rethrown. */
async function cliRefusal(s) {
  try { await s.runConsumer("tavonel-cli.mjs", ["ask_world", s.collectionId, s.question], ""); return "ok"; }
  catch (error) {
    const status = /^tavonel-cli\.mjs exited 1: tavonel: (\d{3}) /.exec(String(error?.message))?.[1];
    if (status === undefined) throw error;
    return status === "401" ? "refused" : "other";
  }
}

/** MCP stdio: the tool failure travels in a result, text starts with API_ERROR_<status>. Same three values as the CLI. */
async function stdioRefusal(s) {
  const frames = [
    { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "tavonel-joined-e2e", version: "1" } } },
    { jsonrpc: "2.0", method: "notifications/initialized" },
    { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "ask_world", arguments: { collectionId: s.collectionId, question: s.question } } },
  ];
  const out = await s.runConsumer("tavonel-mcp.mjs", [], `${frames.map(frame => JSON.stringify(frame)).join("\n")}\n`);
  const reply = out.trim().split("\n").filter(Boolean).map(line => JSON.parse(line)).find(frame => frame.id === 2);
  if (!isObject(reply?.result) || typeof reply.result.isError !== "boolean") throw new Error("MCP stdio gave no tool result");
  if (!reply.result.isError) return "ok";
  return /^API_ERROR_401(:|$)/.test(String(reply.result.content?.[0]?.text)) ? "refused" : "other";
}

const memberCalls = s => ({
  ask: () => ({ resource: `/api/v1/collections/${s.collectionId}/ask`, body: { question: s.question }, method: "POST" }),
  search: () => ({ resource: `/api/v1/collections/${s.collectionId}/search`, body: { query: s.question }, method: "POST" }),
  lens: () => ({ resource: `/api/v1/world/${s.collectionId}/objects`, body: undefined, method: "GET" }),
  export: () => ({ resource: `/api/collections/${s.collectionId}/download`, body: undefined, method: "GET" }),
});
const remoteCall = s => ({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "list_worlds", arguments: { limit: 1 } } });

export const revokePhase = definePhase({
  name: "revoke",
  fields: {
    control: ["held", "broken"],
    member_ask: ROUTE, member_search: ROUTE, member_lens: ROUTE, member_export: ROUTE,
    api_key_cli: CONSUMER, api_key_mcp_stdio: CONSUMER, owner_session: ["unaffected", "affected"],
    remote_mcp: ["refused", "not_refused", "off_not_exercised"], remote_mcp_refusal_seconds: COUNT,
    connector_revoke: ["simulated"],
  },
  async run({ app, check, hop, step, state, deadline }) {
    const s = readState(state);
    const probes = [s.collectionId, s.workspaceKey, ...s.leakTerms];
    const within = () => { const left = deadline - Date.now(); if (left <= 0) throw new PhaseContractError("PHASE_DEADLINE_EXCEEDED", "revoke"); return Math.min(STEP_MS, left); };
    const run = (name, operation) => step(name, within(), operation);
    const calls = memberCalls(s);
    const callAs = (token, spec) => app(spec.resource, token, spec.body, spec.method);
    const remote = token => app("/api/mcp", token, remoteCall(s), "POST");
    const ownerAnswers = async () => (await callAs(s.ownerToken, calls.ask())).status === 200;
    const result = { outcome: "failed", connector_revoke: "simulated" };
    hop("revoke");

    // Control: every call works before it is revoked.
    const control = await run("control", async () => {
      const members = await Promise.all(Object.values(calls).map(async spec => (await callAs(s.member.token, spec())).status === 200));
      const reads = [await cliRefusal(s), await stdioRefusal(s)];
      const remoteOk = s.remoteEndpoint === "off" ? true : (await remote(s.remoteToken)).status === 200;
      return members.every(Boolean) && reads.every(read => read === "ok") && remoteOk && await ownerAnswers();
    });
    result.control = control ? "held" : "broken";
    if (!control) return result;

    // Member revoke.
    const revoked = await run("member-revoke", () => app(`/api/workspaces/${s.workspaceKey}/members/${s.member.userId}`, s.ownerToken, undefined, "DELETE"));
    check("owner revokes the member", [revoked.status, revoked.body?.code], [200, "MEMBER_REVOKED"]);
    for (const [name, spec] of Object.entries(calls)) {
      result[`member_${name}`] = await run(`member-${name}`, async () => judgeRefusal(await callAs(s.member.token, spec()), probes));
    }

    // API key revoke: the owner session is unaffected, the key is refused by both shipped consumers.
    const key = await run("api-key-revoke", () => app(`/api/developer/keys/${s.apiKeyId}`, s.ownerToken, undefined, "DELETE"));
    check("owner revokes the API key", key.status, 204);
    const summary = value => (value === "refused" ? "refused" : "not_refused");  // "ok" and "other" are both not a refusal
    result.api_key_cli = summary(await run("api-key-cli", () => cliRefusal(s)));
    result.api_key_mcp_stdio = summary(await run("api-key-mcp-stdio", () => stdioRefusal(s)));

    // Remote MCP grant: the shipped revoke route, then the next tools/call.
    if (s.remoteEndpoint === "off") result.remote_mcp = "off_not_exercised";
    else {
      const started = Date.now();
      const bulk = await run("remote-mcp-revoke", () => app("/api/internal/remote-mcp/revoke-all", s.workerSecret, {}, "POST"));
      check("the shipped remote MCP revoke route revokes", [bulk.status, bulk.body?.code], [200, "REVOKED"]);
      const after = await run("remote-mcp-next-call", () => remote(s.remoteToken));
      result.remote_mcp = after.status === 401 ? "refused" : "not_refused";
      if (result.remote_mcp === "refused") result.remote_mcp_refusal_seconds = Math.ceil((Date.now() - started) / 1000);
    }

    result.owner_session = await ownerAnswers() ? "unaffected" : "affected";
    const bad = [...Object.entries(result).filter(([key]) => key.startsWith("member_")).map(([, value]) => value !== "refused"),
      result.api_key_cli !== "refused", result.api_key_mcp_stdio !== "refused", result.remote_mcp === "not_refused", result.owner_session !== "unaffected"];
    result.outcome = bad.some(Boolean) ? "failed" : "met";
    return result;
  },
});
