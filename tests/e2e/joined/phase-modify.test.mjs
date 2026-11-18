/**
 * phase-modify.mjs against a stub world: the happy path is `met`, and each fault (pointer advanced on a refused promote,
 * rev 1 served after promote, evidence still bound to rev 1, search or lens reading the wrong World, ...) makes the phase
 * report `not_met` at its own stage. An operational error is rethrown, and the real runPhase/validatePhaseSummary path
 * bounds what comes out.
 */
import assert, { AssertionError } from "node:assert/strict";
import test from "node:test";
import { runPhase, PhaseContractError } from "./phase-contract.mjs";
import { phaseModify, STALE_PROMOTE_CODES } from "./phase-modify.mjs";

const D1 = `sha256:${"1".repeat(64)}`, D2 = `sha256:${"2".repeat(64)}`, DSTALE = `sha256:${"3".repeat(64)}`;
const V1 = "v1key", V2 = "v2key";
const REGION = { pageNumber1: 1, bbox1000: [10, 20, 300, 40] };
const SEARCH = "/api/collections/col1/search", LENS = "/api/v1/world/col1/evidence?limit=1";
/** The three checkpoints where every read surface must be on one World, and the stage each one fails at. */
const WINDOWS = { before: "rev1_served_before_promote", after_compile: "rev1_served_after_compile", after_promote: "rev2_served_after_promote" };

/**
 * A stub Foundation: `faults` flip one behaviour each. `faults.surface = {surface, window, kind}` breaks one read surface
 * (ask on the changed question, search, or the evidence lens) in one window: before rev 2 compiled, after it compiled but
 * before the promote, or after the promote. kind: other_digest | no_digest | refused | bad_status (right body, non-200 status).
 */
function world(faults = {}) {
  const s = { pointer: `${D1}@1`, calls: [], searches: [] };
  const window = () => (s.pointer.startsWith(D2) ? "after_promote" : s.compiled2 ? "after_compile" : "before");
  const served = () => (s.pointer.startsWith(D2) ? D2 : D1);
  const cite = (excerpt, version, region = REGION) => ({ excerpt, ...region,
    ...(faults.versionOnlyInSourceId ? { sourceId: version, sourceVersionId: `${version}-other` } : { sourceId: "doc", sourceVersionId: version }) });
  /** Applies faults.surface to one surface's response; `holder` picks the object that carries manifestDigest. */
  const broken = (surface, response, holder) => {
    const f = faults.surface;
    if (!f || f.surface !== surface || f.window !== window()) return response;
    if (f.kind === "refused") return { status: 503, body: { code: "RETRIEVAL_RUNTIME_UNAVAILABLE" } };
    if (f.kind === "bad_status") return { ...response, status: 500 };
    const body = structuredClone(response.body);
    if (f.kind === "no_digest") delete holder(body).manifestDigest;
    else holder(body).manifestDigest = holder(body).manifestDigest === D2 ? D1 : D2;
    return { ...response, body };
  };
  const askChanged = () => {
    const rev2 = s.pointer.startsWith(D2);
    if (faults.earlyRev2AfterCompile && s.compiled2 && !rev2) return { status: 200, body: { code: "GROUNDED_ANSWER", activeWorld: { manifestDigest: D1 }, answer: "value is NEW", citations: [] } };
    const isNew = rev2 ? !faults.rev1AnswerAfterPromote : Boolean(faults.earlyRev2);
    const digest = faults.askDigestRev2AfterCompile && window() === "after_compile" ? D2 : served();
    return { status: 200, body: { code: "GROUNDED_ANSWER", activeWorld: { manifestDigest: digest },
      answer: isNew ? "value is NEW" : "value is OLD",
      citations: [cite(isNew ? "NEW" : "OLD", isNew && !faults.evidenceRev1 ? (faults.rev2Key ?? V2) : (faults.rev1Key ?? V1))] } };
  };
  const app = async (resource, _token, body) => {
    s.calls.push(resource);
    if (resource === SEARCH) {
      s.searches.push(body);
      const digest = faults.searchEarlyRev2 && window() === "before" ? D2 : served();
      return broken("search", { status: 200, body: { code: "SEARCH_RESULTS", activeWorld: { manifestDigest: digest }, contextPacket: { items: [] } } }, b => b.activeWorld);
    }
    if (resource === LENS) {
      assert.equal(body, undefined, "a lens read is a GET");
      let digest = served();
      if (faults.lensRev2AfterCompile && window() === "after_compile") digest = D2;
      if (faults.lensRev1AfterPromote && window() === "after_promote") digest = D1;
      return broken("lens", { status: 200, body: { code: "OK", world: { id: "col1", manifestDigest: digest, status: "active" }, evidence: [] } }, b => b.world);
    }
    if (resource.endsWith("/ask")) {
      if (body.question === "changed?") return broken("ask", askChanged(), b => b.activeWorld);
      const rev2 = s.pointer.startsWith(D2);
      return { status: faults.unchangedStatus ?? 200, body: { code: "GROUNDED_ANSWER", activeWorld: { manifestDigest: rev2 ? D2 : D1 }, answer: "same",
        citations: [cite("SAME", rev2 ? (faults.rev2Key ?? V2) : (faults.rev1Key ?? V1), faults.regionMoved ? { pageNumber1: 2, bbox1000: [0, 0, 1, 1] } : REGION)] } };
    }
    if (resource.endsWith("/promote")) {
      if (body.manifestDigest === DSTALE) {
        if (faults.pointerAdvancesOnRefusal) s.pointer = `${DSTALE}@2`;
        return faults.staleAccepted ? { status: 200, body: { code: "WORLD_ACTIVE" } }
          : { status: 409, body: { code: faults.uncataloguedCode ?? "SOURCE_VERSION_CHANGED", documentIds: ["x"] } };
      }
      if (faults.rev2Refused) return { status: 409, body: { code: "ACTIVE_WORLD_CONFLICT" } };
      s.pointer = `${D2}@2`;
      return { status: 200, body: { code: "WORLD_ACTIVE" } };
    }
    if (resource.endsWith("/world")) {
      return { status: 200, body: { code: "OK", versions: [
        { manifest_digest: D1, lifecycle_status: faults.historyRewritten ? "active" : "superseded" },
        { manifest_digest: D2, lifecycle_status: "active" }] } };
    }
    throw new Error(`unexpected ${resource}`);
  };
  return { s, app, sql: () => s.pointer };
}

function run(faults, stateOverrides = {}) {
  const w = world(faults);
  const checks = [];
  const check = (name, actual, expected) => { assert.deepEqual(actual, expected, name); checks.push(name); };
  const state = {
    token: "t", workspaceKey: "ws1", collectionId: "col1", activeManifestDigest: D1, activeRevision: 1, revisionCompileEnabled: false,
    rev1VersionKey: faults?.rev1Key ?? V1, changedQuestion: "changed?", unchangedQuestion: "unchanged?", rev1Value: /OLD/, rev2Value: /NEW/,
    unchangedPattern: /SAME/, unchangedRegion: REGION,
    uploadRevision2: async () => ({ versionKey: faults?.rev2Key ?? V2 }),
    compileCandidate: async ({ revision }) => { w.s.compiled2 = revision === 2; return ({ manifestDigest: revision === 1 ? DSTALE : D2, path: "full_compile" }); },
    ...stateOverrides,
  };
  const input = { app: w.app, sql: w.sql, check, hop: () => {}, step: (_n, _ms, op) => op(), state, deadline: Date.now() + 60_000 };
  return { w, checks, done: runPhase(phaseModify, input) };
}

test("the happy path is met, measures ask, search and lens at all three checkpoints, and the summary is bounded", async () => {
  const { done, checks, w } = run();
  assert.deepEqual({ ...await done }, { outcome: "met", revision_compile_flag: "off", stale_refusal_code: "source_version_changed",
    rev2_compile_path: "full_compile", active_revision_after: 2, history_versions: 2, failed_at: "none" });
  assert.equal(checks.length, 10);  // one more than before: rev2_served_after_promote
  assert.deepEqual(checks.filter(name => Object.values(WINDOWS).includes(name.slice("modify/".length))), Object.values(WINDOWS).map(n => `modify/${n}`));
  assert.equal(w.s.calls.filter(r => r === SEARCH).length, 3);
  assert.equal(w.s.calls.filter(r => r === LENS).length, 3);
  assert.deepEqual(w.s.searches, Array(3).fill({ query: "changed?" }));
  assert.equal(w.s.pointer, `${D2}@2`);
});

const cases = [
  ["a pointer that advanced on a refused promote", { pointerAdvancesOnRefusal: true }, "stale_pointer_unchanged"],
  ["a stale candidate that was promoted", { staleAccepted: true }, "stale_promote_refused"],
  ["a refusal code outside the catalogue", { uncataloguedCode: "SOMETHING_ELSE" }, "stale_promote_refused"],
  ["rev 2's answer served before the promote", { earlyRev2: true }, "rev1_served_before_promote"],
  ["an answer from rev 1 after promote", { rev1AnswerAfterPromote: true }, "rev2_value_answered"],
  ["evidence bound to rev 1 for the changed value", { evidenceRev1: true }, "rev2_evidence_bound"],
  ["an unchanged region whose evidence moved", { regionMoved: true }, "unchanged_region_bound"],
  ["the unchanged question answered with a non-200 status", { unchangedStatus: 500 }, "unchanged_region_bound"],
  ["history rewritten (rev 1 not superseded)", { historyRewritten: true }, "history_kept"],
  ["rev 2 served after its candidate compiled but before promote", { earlyRev2AfterCompile: true }, "rev1_served_after_compile"],
  ["rev 2's promote refused", { rev2Refused: true }, "rev2_promoted"],
  // The lead's named search/lens faults, and the digest-only ask fault (answer text unchanged, manifest moved).
  ["search on rev 2's digest before the promote", { searchEarlyRev2: true }, "rev1_served_before_promote"],
  ["lens on rev 2's digest after compile-rev2", { lensRev2AfterCompile: true }, "rev1_served_after_compile"],
  ["lens still on rev 1 after the promote", { lensRev1AfterPromote: true }, "rev2_served_after_promote"],
  ["ask on rev 2's digest (rev 1's text) after compile-rev2", { askDigestRev2AfterCompile: true }, "rev1_served_after_compile"],
];
for (const [name, faults, stage] of cases) {
  test(`${name} is not_met at ${stage}`, async () => {
    const summary = await run(faults).done;
    assert.equal(summary.outcome, "not_met");
    assert.equal(summary.failed_at, stage);
  });
}

// The class: any of the three read surfaces, at any of the three checkpoints, on a World other than the one the pointer
// says, without a digest, refused, or a non-200 status around the right body -- each is not_met at that checkpoint's stage, never met and never a later stage.
test("every read surface x checkpoint x fault kind is not_met at its own checkpoint", async () => {
  for (const surface of ["ask", "search", "lens"]) {
    for (const [window, stage] of Object.entries(WINDOWS)) {
      for (const kind of ["other_digest", "no_digest", "refused", "bad_status"]) {
        const summary = await run({ surface: { surface, window, kind } }).done;
        assert.deepEqual([summary.outcome, summary.failed_at], ["not_met", stage], `${surface}/${window}/${kind}`);
      }
    }
  }
});

// The class: a version is matched by exact equality on sourceVersionId, never by substring, prefix or another field.
test("evidence binding compares the exact sourceVersionId, never a substring or the sourceId", async () => {
  for (const [rev1Key, rev2Key] of [["v", "v2key"], ["v2", "v2key"], ["key", "v2key"], ["v2key", "v2key-b"], ["a1", "a10"], ["undefined", "u2"]]) {
    const summary = await run({ rev1Key, rev2Key }).done;
    assert.deepEqual([summary.outcome, summary.failed_at], ["met", "none"], `${rev1Key} vs ${rev2Key}`);
  }
  const misbound = await run({ versionOnlyInSourceId: true }).done;
  assert.deepEqual([misbound.outcome, misbound.failed_at], ["not_met", "rev2_evidence_bound"]);
});

test("every stale-refusal code in the table is accepted and reported as its own enum", async () => {
  for (const [code, token] of Object.entries(STALE_PROMOTE_CODES)) {
    const summary = await run({ uncataloguedCode: code }).done;
    assert.equal(summary.stale_refusal_code, token);
  }
});

test("an operational error is rethrown, not turned into a verdict", async () => {
  await assert.rejects(run({}, { uploadRevision2: async () => { throw new Error("connection reset"); } }).done, /connection reset/);
});

test("an AssertionError from upload or compile is rethrown, never a verdict (met or not_met)", async () => {
  const boom = () => assert.equal(409, 200);
  await assert.rejects(run({}, { uploadRevision2: async () => { boom(); } }).done, AssertionError);
  await assert.rejects(run({}, { compileCandidate: async ({ revision }) => { if (revision === 2) boom(); return { manifestDigest: DSTALE, path: "full_compile" }; } }).done, AssertionError);
  await assert.rejects(run({}, { compileCandidate: async () => { boom(); } }).done, AssertionError);
});

test("an app that resolves no response (undefined, null, a status that is not an integer) is a thrown TypeError, never a verdict", async () => {
  for (const bad of [undefined, null, {}, { status: "200", body: {} }, { status: Number.NaN, body: {} }]) {
    for (const target of ["/ask", SEARCH, LENS, "/promote", "/world"]) {
      const w = world();
      const app = async (resource, token, body) => (resource.endsWith(target) || resource === target ? bad : w.app(resource, token, body));
      const state = { token: "t", workspaceKey: "ws1", collectionId: "col1", activeManifestDigest: D1, activeRevision: 1, revisionCompileEnabled: false,
        rev1VersionKey: V1, changedQuestion: "changed?", unchangedQuestion: "unchanged?", rev1Value: /OLD/, rev2Value: /NEW/, unchangedPattern: /SAME/,
        unchangedRegion: REGION, uploadRevision2: async () => ({ versionKey: V2 }),
        compileCandidate: async ({ revision }) => { w.s.compiled2 = revision === 2; return { manifestDigest: revision === 1 ? DSTALE : D2, path: "full_compile" }; } };
      const check = (name, actual, expected) => assert.deepEqual(actual, expected, name);
      await assert.rejects(runPhase(phaseModify, { app, sql: w.sql, check, hop: () => {}, step: (_n, _ms, op) => op(), state, deadline: Date.now() + 1e4 }),
        error => error instanceof TypeError && /no response/.test(error.message), `${target} -> ${JSON.stringify(bad)}`);
    }
  }
});

test("a missing or mistyped state entry or helper result is refused, never defaulted", async () => {
  for (const override of [{ token: undefined }, { activeRevision: 0 }, { activeManifestDigest: "sha256:zz" }, { revisionCompileEnabled: "on" },
    { rev2Value: "NEW" }, { workspaceKey: "ws1' or '1'='1" }, { uploadRevision2: async () => ({}) },
    { compileCandidate: async () => ({ manifestDigest: D2, path: "something" }) },
    // A question the ask/search routes would refuse (too short, also after NFKC, too long, a body over 2,048 bytes) is a harness error.
    { changedQuestion: "ab" }, { changedQuestion: "   x   " }, { changedQuestion: "e\u0301e" }, { changedQuestion: "q".repeat(501) }, { unchangedQuestion: "\ud800".repeat(400) },
    // A region a citation could never match honestly (NaN serialises as null; page 0 does not exist).
    { unchangedRegion: { pageNumber1: 1, bbox1000: [Number.NaN, 0, 1, 1] } }, { unchangedRegion: { pageNumber1: 0, bbox1000: [0, 0, 1, 1] } }]) {
    await assert.rejects(run({}, override).done, TypeError);
  }
  // ...and the bound is the routes', not tighter: 500 multi-byte characters (1,265 bytes of JSON) are admitted.
  assert.equal((await run({}, { unchangedQuestion: "é中".repeat(250) }).done).outcome, "met");
});

test("a phase result that leaves its declaration cannot come out of runPhase", async () => {
  const { definePhase } = await import("./phase-contract.mjs");
  const leaky = definePhase({ name: "modify", fields: {}, run: async () => ({ outcome: "met", failed_at: "none" }) });
  await assert.rejects(runPhase(leaky, { app: async () => {}, sql: () => {}, check: () => {}, hop: () => {}, step: () => {}, state: {}, deadline: Date.now() + 1 }),
    error => error instanceof PhaseContractError && error.code === "PHASE_FIELD_NOT_ALLOWED");
  assert.equal(Object.hasOwn(phaseModify.fields, "search_lens"), false);
});
