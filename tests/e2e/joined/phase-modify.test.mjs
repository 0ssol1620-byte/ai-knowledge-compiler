/**
 * phase-modify.mjs against a stub world: the happy path is `met`, and each fault (pointer advanced on a refused promote,
 * rev 1 served after promote, evidence still bound to rev 1, ...) makes the phase report `not_met` at its own stage. An
 * operational error is rethrown, and the real runPhase/validatePhaseSummary path bounds what comes out.
 */
import assert, { AssertionError } from "node:assert/strict";
import test from "node:test";
import { runPhase, PhaseContractError } from "./phase-contract.mjs";
import { phaseModify, STALE_PROMOTE_CODES } from "./phase-modify.mjs";

const D1 = `sha256:${"1".repeat(64)}`, D2 = `sha256:${"2".repeat(64)}`, DSTALE = `sha256:${"3".repeat(64)}`;
const V1 = "v1key", V2 = "v2key";
const REGION = { pageNumber1: 1, bbox1000: [10, 20, 300, 40] };

/** A stub Foundation: `faults` flip one behaviour each. */
function world(faults = {}) {
  const s = { pointer: `${D1}@1`, calls: [] };
  const cite = (excerpt, version, region = REGION) => ({ excerpt, sourceId: "doc", sourceVersionId: version, ...region });
  const app = async (resource, _token, body) => {
    s.calls.push(resource);
    if (resource.endsWith("/ask")) {
      const rev2 = s.pointer.startsWith(D2);
      if (body.question === "changed?") {
        if (faults.earlyRev2AfterCompile && s.compiled2 && !rev2) return { status: 200, body: { code: "GROUNDED_ANSWER", activeWorld: { manifestDigest: D1 }, answer: "value is NEW", citations: [] } };
        const isNew = rev2 ? !faults.rev1AnswerAfterPromote : Boolean(faults.earlyRev2);
        return { status: 200, body: { code: "GROUNDED_ANSWER", activeWorld: { manifestDigest: rev2 ? D2 : D1 },
          answer: isNew ? "value is NEW" : "value is OLD",
          citations: [cite(isNew ? "NEW" : "OLD", isNew && !faults.evidenceRev1 ? V2 : V1)] } };
      }
      return { status: 200, body: { code: "GROUNDED_ANSWER", activeWorld: { manifestDigest: rev2 ? D2 : D1 }, answer: "same",
        citations: [cite("SAME", rev2 ? V2 : V1, faults.regionMoved ? { pageNumber1: 2, bbox1000: [0, 0, 1, 1] } : REGION)] } };
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
    rev1VersionKey: V1, changedQuestion: "changed?", unchangedQuestion: "unchanged?", rev1Value: /OLD/, rev2Value: /NEW/,
    unchangedPattern: /SAME/, unchangedRegion: REGION,
    uploadRevision2: async () => ({ versionKey: V2 }),
    compileCandidate: async ({ revision }) => { w.s.compiled2 = revision === 2; return ({ manifestDigest: revision === 1 ? DSTALE : D2, path: "full_compile" }); },
    ...stateOverrides,
  };
  const input = { app: w.app, sql: w.sql, check, hop: () => {}, step: (_n, _ms, op) => op(), state, deadline: Date.now() + 60_000 };
  return { w, checks, done: runPhase(phaseModify, input) };
}

test("the happy path is met and the summary is bounded enums and counts", async () => {
  const { done, checks, w } = run();
  assert.deepEqual({ ...await done }, { outcome: "met", search_lens: "not_exercised", revision_compile_flag: "off", stale_refusal_code: "source_version_changed",
    rev2_compile_path: "full_compile", active_revision_after: 2, history_versions: 2, failed_at: "none" });
  assert.equal(checks.length, 9);
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
  ["history rewritten (rev 1 not superseded)", { historyRewritten: true }, "history_kept"],
  ["rev 2 served after its candidate compiled but before promote", { earlyRev2AfterCompile: true }, "rev1_served_after_compile"],
  ["rev 2's promote refused", { rev2Refused: true }, "rev2_promoted"],
];
for (const [name, faults, stage] of cases) {
  test(`${name} is not_met at ${stage}`, async () => {
    const summary = await run(faults).done;
    assert.equal(summary.outcome, "not_met");
    assert.equal(summary.failed_at, stage);
  });
}

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

test("a missing or mistyped state entry or helper result is refused, never defaulted", async () => {
  for (const override of [{ token: undefined }, { activeRevision: 0 }, { activeManifestDigest: "sha256:zz" }, { revisionCompileEnabled: "on" },
    { rev2Value: "NEW" }, { workspaceKey: "ws1' or '1'='1" }, { uploadRevision2: async () => ({}) },
    { compileCandidate: async () => ({ manifestDigest: D2, path: "something" }) }]) {
    await assert.rejects(run({}, override).done, TypeError);
  }
});

test("a phase result that leaves its declaration cannot come out of runPhase", async () => {
  const { definePhase } = await import("./phase-contract.mjs");
  const leaky = definePhase({ name: "modify", fields: {}, run: async () => ({ outcome: "met", failed_at: "none" }) });
  await assert.rejects(runPhase(leaky, { app: async () => {}, sql: () => {}, check: () => {}, hop: () => {}, step: () => {}, state: {}, deadline: Date.now() + 1 }),
    error => error instanceof PhaseContractError && error.code === "PHASE_FIELD_NOT_ALLOWED");
});
