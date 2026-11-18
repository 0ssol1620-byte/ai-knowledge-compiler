/**
 * phase-revoke.mjs against a stub harness: a small fake of the app, the shipped consumers and the revoke routes. Each
 * fault below is one way the product could fail to revoke; the phase must report failed for it, and the clean world must
 * be met. Everything goes through runPhase, the function the journey calls.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { PhaseContractError, runPhase } from "./phase-contract.mjs";
import { judgeRefusal, revokePhase } from "./phase-revoke.mjs";

const COLLECTION = "col_0123456789abcdef", WORKSPACE = "pilot-abcdef0123456789", TITLE = "Quarterly Vendor Contract", PHRASE = "net thirty days";
const NO_STORE = { "cache-control": "no-store" };

/** A world whose revoke works unless `fault` says otherwise. */
function world({ remote = false, fault = "" } = {}) {
  const live = { member: true, key: true, remote: true };
  const calls = [];
  const refusal = (status = 403, body = { code: "AUTH_REQUIRED" }, headers = NO_STORE) => ({ status, body, headers });
  const readable = (headers = NO_STORE) => ({ status: 200, body: { code: "GROUNDED_ANSWER" }, headers });
  const app = async (resource, bearer, body, method = body === undefined ? "GET" : "POST") => {
    calls.push(`${method} ${resource}`);
    if (resource.startsWith("/api/workspaces/")) { if (fault !== "revoke_route_noop") live.member = false; return { status: 200, body: { code: "MEMBER_REVOKED" }, headers: NO_STORE }; }
    if (resource.startsWith("/api/developer/keys/")) { live.key = false; return { status: 204, body: null, headers: NO_STORE }; }
    if (resource === "/api/internal/remote-mcp/revoke-all") { if (fault !== "remote_not_revoked") live.remote = false; return { status: 200, body: { code: "REVOKED" }, headers: NO_STORE }; }
    if (resource === "/api/mcp") return live.remote ? { status: 200, body: { result: {} }, headers: NO_STORE } : { status: 401, body: { error: {} }, headers: NO_STORE };
    if (bearer === "member-token") {
      if (live.member) return readable();
      if (fault === `member_${resource.split("/").pop()}`) return readable();
      if (fault === "refusal_title") return refusal(403, { code: "X", title: TITLE });
      if (fault === "refusal_count") return refusal(403, { code: "X", count: 3 });
      if (fault === "refusal_leaks_collection") return refusal(404, { code: `NOT_FOUND ${COLLECTION}` });
      if (fault === "refusal_cache") return refusal(403, { code: "X" }, { "cache-control": "max-age=60" });
      if (fault === "no_headers") return { status: 403, body: { code: "X" } };
      if (fault === "refusal_status") return refusal(500);
      if (fault === "refusal_ids_not_array") return refusal(409, { code: "X", documentIds: "d1" });
      if (fault === "refusal_text") return { ...refusal(), body: null, text: `no access to ${PHRASE}` };
      return refusal();
    }
    if (bearer === "owner-token") return fault === "owner_refused" && !live.key ? refusal(403) : readable();
    throw new Error(`unexpected bearer for ${resource}`);
  };
  const runConsumer = async (script, args) => {
    if (live.key && fault === "pre_cli_503" && script === "tavonel-cli.mjs") throw new Error("tavonel-cli.mjs exited 1: tavonel: 503 {\"code\":\"CORE_UNAVAILABLE\"}");
    if (live.key && fault === "pre_stdio_503" && script === "tavonel-mcp.mjs") return `${JSON.stringify({ jsonrpc: "2.0", id: 2, result: { isError: true, content: [{ type: "text", text: "API_ERROR_503: CORE_UNAVAILABLE" }] } })}
`;
    if (live.key) return script === "tavonel-cli.mjs" ? "{}" : `${JSON.stringify({ jsonrpc: "2.0", id: 2, result: { isError: false, content: [{ type: "text", text: "{}" }] } })}\n`;
    if (fault === "key_still_works") return script === "tavonel-cli.mjs" ? "{}" : `${JSON.stringify({ jsonrpc: "2.0", id: 2, result: { isError: false, content: [{ type: "text", text: "{}" }] } })}\n`;
    if (script === "tavonel-cli.mjs") throw new Error(`tavonel-cli.mjs exited 1: tavonel: ${fault === "key_500" ? 500 : 401} {"code":"API_KEY_INVALID"}`);
    return `${JSON.stringify({ jsonrpc: "2.0", id: 2, result: { isError: true, content: [{ type: "text", text: `API_ERROR_${fault === "key_500" ? 500 : 401}: API_KEY_INVALID` }] } })}\n`;
  };
  const state = {
    ownerToken: "owner-token", collectionId: COLLECTION, workspaceKey: WORKSPACE, question: "What are the payment terms?", leakTerms: [TITLE, PHRASE],
    member: { userId: "user-1", token: "member-token" }, apiKey: { id: "key-1" }, runConsumer,
    remoteMcp: { enabled: remote, ...(remote ? { token: "mcp-token", workerSecret: "w".repeat(32) } : {}) },
  };
  const checks = [], hops = [], steps = [];
  const input = () => ({ app, sql: () => "", check: (name, actual, expected) => { assert.deepEqual(actual, expected, name); checks.push(name); },
    hop: stage => hops.push(stage), step: async (name, ms, operation) => { steps.push([name, ms]); return operation(); }, state, deadline: Date.now() + 600_000 });
  return { input, calls, checks, hops, steps, state, live };
}

const run = async options => { const w = world(options); return { w, out: await runPhase(revokePhase, w.input()) }; };

test("a clean revoke with the remote endpoint off is met, and the remote step is reported off, not exercised", async () => {
  const { out, w } = await run();
  assert.deepEqual(out, { outcome: "met", control: "held", member_ask: "refused", member_search: "refused", member_lens: "refused", member_export: "refused",
    api_key_cli: "refused", api_key_mcp_stdio: "refused", owner_session: "unaffected", remote_mcp: "off_not_exercised", connector_revoke: "simulated" });
  assert.ok(!w.calls.some(call => call.includes("/api/mcp") || call.includes("remote-mcp")), "no remote call when the endpoint is off");
  assert.deepEqual(w.hops, ["revoke"]);
});

test("a clean revoke with the remote endpoint on records the seconds to refusal", async () => {
  const { out, w } = await run({ remote: true });
  assert.equal(out.outcome, "met");
  assert.equal(out.remote_mcp, "refused");
  assert.ok(Number.isSafeInteger(out.remote_mcp_refusal_seconds) && out.remote_mcp_refusal_seconds >= 0);
  assert.ok(w.calls.includes("POST /api/internal/remote-mcp/revoke-all"));
});

test("connector revoke is only ever the label simulated and makes no call", async () => {
  const { out, w } = await run({ remote: true });
  assert.equal(out.connector_revoke, "simulated");
  assert.ok(!w.calls.some(call => /connector|viewer-links/.test(call)));
});

for (const route of ["ask", "search", "objects", "download"]) {
  test(`a revoked member that still gets 200 on ${route} fails the phase`, async () => {
    const { out } = await run({ fault: `member_${route}` });
    assert.equal(out.outcome, "failed");
    assert.deepEqual(Object.values(out).filter(value => value === "not_refused"), ["not_refused"]);
  });
}

test("the revoke route returning 200 without revoking is caught by the next call, not by its own answer", async () => {
  const { out } = await run({ fault: "revoke_route_noop" });
  assert.equal(out.outcome, "failed");
  assert.equal(out.member_ask, "not_refused");
});

for (const [fault, expected] of [["refusal_title", "bad_body"], ["refusal_count", "bad_body"], ["refusal_leaks_collection", "bad_body"],
  ["refusal_ids_not_array", "bad_body"], ["refusal_text", "bad_body"], ["refusal_cache", "no_store_missing"], ["no_headers", "no_store_unobservable"],
  ["refusal_status", "not_refused"]]) {
  test(`a refusal that breaks the rule set (${fault}) fails the phase as ${expected}`, async () => {
    const { out } = await run({ fault });
    assert.equal(out.outcome, "failed");
    assert.equal(out.member_ask, expected);
  });
}

test("the owner refused after the revokes fails the phase", async () => {
  const { out } = await run({ fault: "owner_refused" });
  assert.equal(out.outcome, "failed");
  assert.equal(out.owner_session, "affected");
});

test("an API key that still works in either shipped consumer fails the phase", async () => {
  const { out } = await run({ fault: "key_still_works" });
  assert.equal(out.outcome, "failed");
  assert.deepEqual([out.api_key_cli, out.api_key_mcp_stdio], ["not_refused", "not_refused"]);
});

test("a key refused with something other than 401 is not a refusal", async () => {
  const { out } = await run({ fault: "key_500" });
  assert.deepEqual([out.outcome, out.api_key_cli, out.api_key_mcp_stdio], ["failed", "not_refused", "not_refused"]);
});

test("a remote MCP call that still works after the revoke route fails the phase and reports no seconds", async () => {
  const { out } = await run({ remote: true, fault: "remote_not_revoked" });
  assert.equal(out.outcome, "failed");
  assert.equal(out.remote_mcp, "not_refused");
  assert.ok(!Object.hasOwn(out, "remote_mcp_refusal_seconds"));
});

for (const fault of ["pre_cli_503", "pre_stdio_503"]) {
  test(`a consumer that fails with 503 before the revoke (${fault}) is a broken control, not a held one`, async () => {
    const w = world({ fault });
    const out = await runPhase(revokePhase, w.input());
    assert.deepEqual(out, { outcome: "failed", control: "broken", connector_revoke: "simulated" });
    assert.ok(!w.calls.some(call => call.startsWith("DELETE")), "nothing was revoked");
  });
}

test("a broken control stops before anything is revoked", async () => {
  const w = world();
  w.live.member = false;  // the member could never read: a later refusal would prove nothing
  const out = await runPhase(revokePhase, w.input());
  assert.deepEqual(out, { outcome: "failed", control: "broken", connector_revoke: "simulated" });
  assert.ok(!w.calls.some(call => call.startsWith("DELETE")), "nothing was revoked");
});

test("an operational failure is thrown, not recorded as a refusal or a violation", async () => {
  const w = world();
  w.state.runConsumer = async () => { throw new Error("tavonel-cli.mjs timed out"); };
  await assert.rejects(runPhase(revokePhase, w.input()), /timed out/);
});

test("missing or ill-typed state is refused, never defaulted", async () => {
  for (const [key, value] of [["ownerToken", ""], ["collectionId", undefined], ["leakTerms", []], ["leakTerms", [""]], ["member", {}], ["apiKey", null],
    ["runConsumer", "x"], ["remoteMcp", { enabled: "yes" }], ["remoteMcp", { enabled: true }]]) {
    const w = world();
    w.state[key] = value;
    await assert.rejects(runPhase(revokePhase, w.input()), error => error instanceof PhaseContractError && /^PHASE_STATE_INVALID|FLAG_NOT_BOOLEAN$/.test(error.code), `${key}=${String(value)}`);
    assert.equal(w.calls.length, 0, "nothing is called on bad state");
  }
});

test("a deadline already passed stops the phase", async () => {
  const w = world();
  await assert.rejects(runPhase(revokePhase, { ...w.input(), deadline: 1 }), error => error.code === "PHASE_DEADLINE_EXCEEDED");
});

test("the class: any refusal that is not a listed status, no-store, a code/documentIds body free of identifiers is not refused", () => {
  const ok = { status: 403, body: { code: "X" }, headers: NO_STORE };
  assert.equal(judgeRefusal(ok, []), "refused");
  assert.equal(judgeRefusal({ ...ok, body: null }, []), "refused");
  for (const status of [200, 201, 204, 400, 422, 500, 503, undefined, "403", null]) assert.equal(judgeRefusal({ ...ok, status }, []), "not_refused", String(status));
  for (const body of [[], "x", 7, { code: 4 }, { code: "X", total: 1 }, { code: "X", sources: [] }, { code: "X", items: [] }, { code: "X", evidence: "t" }, { documentIds: [1] }]) {
    assert.equal(judgeRefusal({ ...ok, body }, []), "bad_body", JSON.stringify(body));
  }
  assert.equal(judgeRefusal({ ...ok, body: { code: "X", documentIds: ["a"] } }, []), "refused");
  assert.equal(judgeRefusal({ ...ok, body: { code: "see COL_0123456789ABCDEF" } }, [COLLECTION]), "bad_body");
  assert.equal(judgeRefusal({ ...ok, headers: { "cache-control": "private, no-store" } }, []), "refused");
  assert.equal(judgeRefusal({ ...ok, headers: { "cache-control": "no-store-ish" } }, []), "no_store_missing");
  assert.equal(judgeRefusal({ ...ok, headers: undefined }, []), "no_store_unobservable");
  assert.equal(judgeRefusal({ ...ok, headers: {} }, []), "no_store_missing");
  assert.equal(judgeRefusal({ ...ok, headers: { "cache-control": 5 } }, []), "no_store_missing");
  assert.equal(judgeRefusal(null, []), "not_refused");
});

test("the summary the phase returns never carries text, ids or a leak term", async () => {
  const { out } = await run({ remote: true });
  const serialized = JSON.stringify(out);
  for (const term of [COLLECTION, WORKSPACE, TITLE, PHRASE, "member-token", "owner-token", "mcp-token"]) assert.ok(!serialized.includes(term), term);
});
