/**
 * Focused tests for the three parent-review findings on the G1-11 runtime producer:
 *  1. every projection needs an authority binding, a matching observation context and an actual
 *     per-file access decision;
 *  2. a compile candidate must name exactly the job's unique document/version set;
 *  3. the run/commit binding is fixed at construction and cannot be relabelled by produce();
 * plus the monitor-claim correction: a false effect needs a monitoring claim bound to its exact scope
 * with the canonical scope digest as receipt (structural only, never an authenticated monitor).
 * Every object here is SYNTHETIC_CONTRACT_TEST data, including every monitoring receipt. Nothing is read
 * from a fixture manifest and no product, network, DB or filesystem is touched.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRuntimeProducer, monitoringReceiptSha256, ProducerInputError } from "./g1-11-runtime-producer.mjs";

const KIND = "SYNTHETIC_CONTRACT_TEST";
const tag = (label) => `${KIND}-${label}`;
const hex = (label) => createHash("sha256").update(tag(label), "utf8").digest("hex");
const principalSha = (ref) => createHash("sha256").update(ref, "utf8").digest("hex");

const PRINCIPAL = tag("principal-a");
const OTHER_PRINCIPAL = tag("principal-b");
const WORKSPACE = tag("workspace-1");
const SCOPE_A = tag("scope-a");
const SCOPE_B = tag("scope-b");
const RUN = Object.freeze({ run_id: tag("run-1"), foundation_commit: "1".repeat(40), core_commit: "2".repeat(40) });
const NUMBERS = [1, 2, 3, 4, 5, 6, 7];

const scopeOf = (n) => (n === 7 ? SCOPE_B : SCOPE_A);
const memberId = (n) => tag(`m${n}`);
const fileKey = (n) => tag(`file-${n}`);
const doc = (n) => tag(`doc-${n}`);
const versionKey = (n) => hex(`sanitized-${n}`);
const ctx = (n, over = {}) => ({ principalRef: PRINCIPAL, workspaceKey: WORKSPACE, aclScope: scopeOf(n), ...over });

function memberInputs({ unbound = [] } = {}) {
  return NUMBERS.map((n) => ({
    id: memberId(n),
    source_id: tag(`source-${n}`),
    source_version: tag(`source-version-${n}`),
    source_sha256: hex(`content-${n}`),
    acl_scope: scopeOf(n),
    authority_binding: unbound.includes(n) ? null
      : { principal_ref_sha256: principalSha(PRINCIPAL), workspace_key: WORKSPACE, acl_scope: scopeOf(n) },
  }));
}

function producer({ unbound = [], execution_binding = RUN } = {}) {
  return createRuntimeProducer({ evidence_kind: KIND, members: memberInputs({ unbound }), execution_binding });
}

function map(p, n, over = {}) {
  return p.recordMapping({ verified: true, id: memberId(n), fileKey: fileKey(n), contentSha256: hex(`content-${n}`),
    documentId: doc(n), basis: tag("mapping-basis"), context: ctx(n), ...over });
}

function access(p, n, decision, over = {}) {
  return p.recordAccessDecision({ fileKey: fileKey(n), boundary: "external_authorization", decision, principalRef: PRINCIPAL,
    reasonCode: decision === "denied" ? tag("acl-denied") : null, status: decision === "denied" ? 403 : 200,
    context: ctx(n), ...over });
}

function sanitize(p, n) {
  return p.recordCdrOcr({ documentId: doc(n), outcome: "sanitized", versionKey: versionKey(n), cdrStatus: tag("cdr-done"),
    failureCode: null, ocr: null, context: ctx(n) });
}

const sourceDoc = (n, key = versionKey(n)) => ({ documentId: doc(n), versionKey: key });

function compile(p, ns, sourceDocuments = ns.map((n) => sourceDoc(n))) {
  const manifest = hex("manifest");
  const output = hex("core-output");
  return p.recordCompile({
    job: { jobId: tag("job-1"), state: "ready", errorCode: "", collectionId: "", manifestDigest: manifest },
    documentIds: ns.map(doc),
    candidate: { manifestDigest: manifest, coreOutputSha256: output, sourceDocuments },
    receiptVerification: { ok: true, payload: { coreOutputSha256: output, manifestDigest: manifest } },
    context: ctx(ns[0]),
  });
}

const ACTIVE = { content_read: true, transferred: true, processed: true, charged: false };
const QUIET = { content_read: false, transferred: false, processed: false, charged: false };

/** SYNTHETIC_CONTRACT_TEST monitoring scope for member n / effect under RUN and the default context. */
const monitorScope = (n, effect, over = {}) => ({
  ...RUN, id: memberId(n), file_key: fileKey(n), source_id: tag(`source-${n}`), source_version: tag(`source-version-${n}`),
  source_sha256: hex(`content-${n}`), acl_scope: scopeOf(n), principal_ref_sha256: principalSha(PRINCIPAL),
  workspace_key: WORKSPACE, effect, ...over,
});
const monitorOf = (scope) => ({ complete: true, receiptSha256: monitoringReceiptSha256(scope), scope });

function effects(p, n, values) {
  for (const [effect, value] of Object.entries(values)) {
    p.recordEffect({ fileKey: fileKey(n), effect, value,
      monitoring: value ? null : monitorOf(monitorScope(n, effect)), context: ctx(n) });
  }
}

function settleCharge(p, n) {
  return p.recordSettlement({ documentId: doc(n), state: "settled", settledCredits: 1, reasonCode: null,
    settledAt: tag("settled-at"), context: ctx(n) });
}

function triageNeedsReview(p, n) {
  return p.recordTriage({
    scope: { workspaceKey: WORKSPACE, sourceId: tag("triage-source"), sourceKind: "direct_upload",
      inventoryRevision: tag("inventory-1"), aclObservationSha256: null },
    files: [{ fileKey: fileKey(n), revision: null, contentSha256: null, aclObservationSha256: null,
      disposition: "needs_review", reason: tag("needs-review"), exactDuplicateOf: null }],
    context: ctx(n),
  });
}

function refuseQualification(p, n) {
  return p.recordQualification({ fileKey: fileKey(n), status: 403, outcome: "refused", code: tag("qualification-refused"),
    documentId: null, context: ctx(n) });
}

/** m1 reaches a verified output, m2 a pending triage and m3 a qualification refusal; no access decisions. */
function stageThree(p) {
  for (const n of [1, 2, 3]) map(p, n);
  sanitize(p, 1); compile(p, [1]); effects(p, 1, ACTIVE);
  triageNeedsReview(p, 2); effects(p, 2, QUIET);
  refuseQualification(p, 3); effects(p, 3, QUIET);
}

const rejects = (fn, code) => assert.throws(fn, (error) => error instanceof ProducerInputError && error.code === code, code);
const diag = (out, n) => out.sidecar.members.find((m) => m.id === memberId(n));
const record = (out, n) => out.runtimeResults.dispositions.find((r) => r.id === memberId(n)) ?? null;
const executionPair = (out) => {
  const { run_id, foundation_commit, core_commit } = out.runtimeResults.execution;
  return { run_id, foundation_commit, core_commit };
};

// ---- Finding 1: authority binding, context and mandatory per-file access decision ----

test("finding 1: output, pending and qualification-refused members without an access decision stay unprojected", () => {
  const p = producer();
  stageThree(p);
  const out = p.produce();
  assert.equal(out.runtimeResults.execution.status, "PARTIAL");
  assert.deepEqual(out.runtimeResults.dispositions, []);
  for (const [n, result] of [[1, "output"], [2, "pending"], [3, "refused"]]) {
    const d = diag(out, n);
    assert.equal(d.projected, false);
    assert.deepEqual(d.missing, ["external_access_decision"]);
    assert.deepEqual(d.conflicts, []);
    assert.deepEqual(d.result_basis.map((r) => r.result), [result]);
  }
});

test("finding 1: wrong principal, workspace, scope, unbound member or malformed context is rejected atomically", () => {
  const p = producer({ unbound: [6] });
  map(p, 1); map(p, 7);
  const before = p.produce();
  const cases = [
    [() => map(p, 2, { context: ctx(2, { principalRef: OTHER_PRINCIPAL }) }), "CONTEXT_MISMATCH"],
    [() => map(p, 2, { context: ctx(2, { workspaceKey: tag("workspace-2") }) }), "CONTEXT_MISMATCH"],
    [() => map(p, 2, { context: ctx(2, { aclScope: SCOPE_B }) }), "CONTEXT_MISMATCH"],
    [() => map(p, 2, { context: undefined }), "INVALID_OBJECT"],
    [() => map(p, 2, { context: { workspaceKey: WORKSPACE, aclScope: SCOPE_A } }), "INVALID_TEXT"],
    [() => map(p, 6, { context: ctx(6) }), "AUTHORITY_UNBOUND"],
    // One scope-A context cannot carry a request that also touches the scope-B member; m1 must stay untouched.
    [() => p.recordQuote({ fileKeys: [fileKey(1), fileKey(7)], result: { ok: false, code: tag("quote-refused"), index: 0 },
      context: ctx(1) }), "CONTEXT_MISMATCH"],
    [() => access(p, 1, "allowed", { principalRef: OTHER_PRINCIPAL }), "ACCESS_PRINCIPAL_MISMATCH"],
    [() => access(p, 1, "allowed", { principalRef: OTHER_PRINCIPAL, context: ctx(1, { principalRef: OTHER_PRINCIPAL }) }),
      "CONTEXT_MISMATCH"],
    [() => p.recordConfirm({ status: 409, code: tag("confirm-refused"), approvedFile: null,
      context: ctx(1, { principalRef: OTHER_PRINCIPAL }) }), "CONTEXT_NOT_BOUND"],
  ];
  for (const [fn, code] of cases) rejects(fn, code);

  const after = p.produce();
  assert.deepEqual(after.sidecar.journal, before.sidecar.journal);
  assert.deepEqual(after.sidecar.members, before.sidecar.members);
  assert.equal(after.runtimeResults.execution.stage_receipt_sha256, before.runtimeResults.execution.stage_receipt_sha256);
  assert.equal(after.sidecar.rejections.count, cases.length);
  assert.equal(diag(after, 1).facts.quote, null);
  assert.equal(diag(after, 1).facts.access, null);
  assert.equal(diag(after, 2).observed_product_identity.file_key, null);
  assert.ok(diag(after, 6).missing.includes("authority_binding"));

  // Whole-request control: a matching bound context is accepted but never becomes a per-file fact.
  p.recordConfirm({ status: 409, code: tag("confirm-refused"), approvedFile: null, context: ctx(1) });
  const whole = p.produce();
  assert.deepEqual(whole.sidecar.journal.at(-1).member_ids, []);
  assert.equal(diag(whole, 1).facts.access, null);
  assert.deepEqual(whole.runtimeResults.dispositions, []);

  // Constructor: the authority scope must be the exact owner label, the principal digest raw 64hex.
  const wrongScope = memberInputs();
  wrongScope[0].authority_binding.acl_scope = SCOPE_B;
  rejects(() => createRuntimeProducer({ evidence_kind: KIND, members: wrongScope, execution_binding: RUN }), "AUTHORITY_SCOPE_MISMATCH");
  const prefixed = memberInputs();
  prefixed[0].authority_binding.principal_ref_sha256 = `sha256:${principalSha(PRINCIPAL)}`;
  rejects(() => createRuntimeProducer({ evidence_kind: KIND, members: prefixed, execution_binding: RUN }), "INVALID_SHA256");
});

test("finding 1 control: exact allowed decisions project only what the product returned, with hashed contexts", () => {
  const p = producer();
  stageThree(p);
  for (const n of [1, 2, 3]) access(p, n, "allowed");
  const out = p.produce();
  assert.equal(out.runtimeResults.execution.status, "PARTIAL");
  assert.deepEqual(out.runtimeResults.dispositions.map((r) => [r.id, r.disposition]),
    [[memberId(1), "output"], [memberId(2), "pending"], [memberId(3), "refused"]]);
  assert.equal(record(out, 1).reason_code, "ready");
  assert.equal(record(out, 1).acl_scope, SCOPE_A);
  assert.match(record(out, 1).stage_receipt_sha256, /^[a-f0-9]{64}$/);
  assert.equal(record(out, 2).stage_receipt_sha256, null);
  assert.equal(record(out, 3).reason_code, tag("qualification-refused"));
  const hashed = { principal_ref_sha256: principalSha(PRINCIPAL), workspace_key: WORKSPACE, acl_scope: SCOPE_A };
  for (const entry of out.sidecar.journal) assert.deepEqual(entry.context, hashed);
  assert.ok(!JSON.stringify(out).includes(PRINCIPAL));
  assert.equal(out.sidecar.actual_runtime_pass_claimed, false);
  assert.equal(out.sidecar.observations_authenticated, false);
});

test("finding 1 control: denied decisions refuse with monitored false effects, keep true activity negative and conflict with output", () => {
  const p = producer();
  map(p, 1); access(p, 1, "denied"); effects(p, 1, QUIET);
  map(p, 2); access(p, 2, "denied"); effects(p, 2, { ...QUIET, content_read: true });
  map(p, 3); access(p, 3, "denied"); sanitize(p, 3); compile(p, [3]); effects(p, 3, ACTIVE);
  const out = p.produce();

  const refused = record(out, 1);
  assert.deepEqual([refused.disposition, refused.reason_code], ["refused", tag("acl-denied")]);
  assert.deepEqual([refused.content_read, refused.transferred, refused.processed, refused.charged], [false, false, false, false]);
  assert.equal(refused.stage_receipt_sha256, null);

  assert.equal(record(out, 2).disposition, "refused");
  assert.equal(record(out, 2).content_read, true);
  assert.ok(diag(out, 2).notes.includes("activity_observed_for_non_stage_result"));

  assert.equal(record(out, 3), null);
  assert.ok(diag(out, 3).conflicts.includes("multiple_terminal_results"));
});

// ---- Finding 2: exact unique candidate document/version set ----

test("finding 2: duplicate, conflicting, unknown, extra or missing candidate documents are refused before apply", () => {
  const p = producer();
  for (const n of [1, 2]) { map(p, n); access(p, n, "allowed"); sanitize(p, n); effects(p, n, ACTIVE); }
  const before = p.produce();
  const cases = [
    [[1, 2], [sourceDoc(1), sourceDoc(1), sourceDoc(2)], "DUPLICATE_SOURCE_DOCUMENT"],
    [[1, 2], [sourceDoc(1), sourceDoc(1, hex("other-version")), sourceDoc(2)], "CONFLICTING_SOURCE_DOCUMENT_VERSION"],
    [[1, 2], [sourceDoc(1), sourceDoc(2), { documentId: tag("doc-unknown"), versionKey: hex("unknown") }], "CANDIDATE_DOCUMENT_NOT_IN_JOB"],
    [[1], [sourceDoc(1), sourceDoc(2)], "CANDIDATE_DOCUMENT_NOT_IN_JOB"],
    [[1, 2], [sourceDoc(1)], "CANDIDATE_MISSING_JOB_DOCUMENT"],
    [[1, 2], [sourceDoc(1, hex("stale-version")), sourceDoc(2)], "SOURCE_VERSION_MISMATCH"],
  ];
  for (const [ns, docs, code] of cases) rejects(() => compile(p, ns, docs), code);

  const after = p.produce();
  assert.deepEqual(after.sidecar.journal, before.sidecar.journal);
  assert.equal(after.sidecar.rejections.count, cases.length);
  for (const n of [1, 2]) {
    assert.deepEqual(diag(after, n).facts.compiles, []);
    assert.equal(record(after, n), null);
  }

  // Control: the exact unique set (order independent) is accepted and both members project output.
  compile(p, [1, 2], [sourceDoc(2), sourceDoc(1)]);
  const done = p.produce();
  for (const n of [1, 2]) assert.equal(record(done, n).disposition, "output");
  assert.deepEqual(done.sidecar.journal.at(-1).candidate.source_documents,
    [{ document_id: doc(2), version_key: versionKey(2) }, { document_id: doc(1), version_key: versionKey(1) }]);
});

// ---- Finding 3: immutable run/commit binding ----

test("finding 3: produce cannot relabel the journal to another run or commit pair", () => {
  const p = producer();
  map(p, 1);
  rejects(() => p.produce({ ...RUN, run_id: tag("run-2") }), "RUN_BINDING_MISMATCH");
  rejects(() => p.produce({ ...RUN, foundation_commit: "3".repeat(40) }), "RUN_BINDING_MISMATCH");
  rejects(() => p.produce({ ...RUN, core_commit: "3".repeat(40) }), "RUN_BINDING_MISMATCH");
  rejects(() => p.produce({ run_id: RUN.run_id }), "INVALID_COMMIT");
  const restated = p.produce({ ...RUN });
  assert.deepEqual(restated, p.produce());
  assert.deepEqual(executionPair(restated), { ...RUN });
});

test("finding 3: constructor inputs and returned objects are not mutable aliases of the bindings", () => {
  const members = memberInputs();
  const executionBinding = { ...RUN };
  const p = createRuntimeProducer({ evidence_kind: KIND, members, execution_binding: executionBinding });
  map(p, 1);
  const first = p.produce();
  const snapshot = JSON.stringify(first);

  executionBinding.run_id = tag("run-mutated");
  executionBinding.core_commit = "f".repeat(40);
  members[0].acl_scope = SCOPE_B;
  members[0].authority_binding.principal_ref_sha256 = principalSha(OTHER_PRINCIPAL);
  members[0].authority_binding.workspace_key = tag("workspace-mutated");
  first.runtimeResults.execution.run_id = tag("returned-mutated");
  first.sidecar.members[0].owner_labels.authority_binding.workspace_key = tag("returned-mutated");
  first.sidecar.journal[0].context.principal_ref_sha256 = principalSha(OTHER_PRINCIPAL);

  assert.equal(JSON.stringify(p.produce()), snapshot);
  rejects(() => p.produce(executionBinding), "RUN_BINDING_MISMATCH");
  rejects(() => access(p, 1, "allowed", { principalRef: OTHER_PRINCIPAL,
    context: ctx(1, { principalRef: OTHER_PRINCIPAL, workspaceKey: tag("workspace-mutated") }) }), "CONTEXT_MISMATCH");
  access(p, 1, "allowed");
  assert.deepEqual(executionPair(p.produce()), { ...RUN });
});

test("finding 3: identical observations under a different run/commit pair or authority set give different digests", () => {
  const drive = (executionBinding, unbound = []) => {
    const p = createRuntimeProducer({ evidence_kind: KIND, members: memberInputs({ unbound }), execution_binding: executionBinding });
    // Only true effects and a settled charge: a false-effect monitoring scope names the run pair, so it
    // could not be identical across runs.
    map(p, 1); access(p, 1, "allowed"); sanitize(p, 1); compile(p, [1]);
    effects(p, 1, { content_read: true, transferred: true, processed: true }); settleCharge(p, 1);
    return p.produce();
  };
  const stage = (out) => out.runtimeResults.execution.stage_receipt_sha256;
  const base = drive(RUN);
  const repeat = drive({ ...RUN });
  assert.equal(stage(repeat), stage(base));
  assert.equal(record(repeat, 1).stage_receipt_sha256, record(base, 1).stage_receipt_sha256);

  for (const other of [
    drive({ ...RUN, run_id: tag("run-2") }),
    drive({ ...RUN, foundation_commit: "3".repeat(40) }),
    drive({ ...RUN, core_commit: "4".repeat(40) }),
  ]) {
    assert.deepEqual(other.sidecar.journal, base.sidecar.journal);
    assert.notEqual(stage(other), stage(base));
    assert.notEqual(record(other, 1).stage_receipt_sha256, record(base, 1).stage_receipt_sha256);
  }

  // Another member's authority binding is part of the run evidence but not of m1's own stage receipt.
  const otherAuthority = drive(RUN, [5]);
  assert.notEqual(stage(otherAuthority), stage(base));
  assert.equal(record(otherAuthority, 1).stage_receipt_sha256, record(base, 1).stage_receipt_sha256);
});

test("finding 3: an unbound producer refuses every observation; no-observation NOT_RUN control", () => {
  const notRun = (out) => {
    assert.equal(out.runtimeResults.execution.status, "NOT_RUN");
    assert.deepEqual(executionPair(out), { run_id: null, foundation_commit: null, core_commit: null });
    assert.equal(out.runtimeResults.execution.stage_receipt_sha256, null);
    assert.deepEqual(out.runtimeResults.dispositions, []);
    assert.deepEqual(out.sidecar.journal, []);
    assert.deepEqual(out.sidecar.missing_prerequisites, ["runtime_observations"]);
  };
  const absent = createRuntimeProducer({ evidence_kind: KIND, members: memberInputs() });
  const explicit = producer({ execution_binding: null });
  for (const p of [absent, explicit]) {
    notRun(p.produce());
    rejects(() => map(p, 1), "UNBOUND_RUN");
    rejects(() => access(p, 1, "allowed"), "UNBOUND_RUN");
    rejects(() => p.produce(RUN), "RUN_BINDING_MISMATCH");
    const out = p.produce();
    notRun(out);
    assert.equal(out.sidecar.rejections.count, 2);
    assert.equal(diag(out, 1).observed_product_identity.file_key, null);
  }

  // A bound producer without observations is still NOT_RUN with null bindings.
  const bound = producer();
  notRun(bound.produce());
  notRun(bound.produce(RUN));

  rejects(() => producer({ execution_binding: { ...RUN, core_commit: "A".repeat(40) } }), "INVALID_COMMIT");
  rejects(() => producer({ execution_binding: { ...RUN, run_id: "x".repeat(513) } }), "INVALID_TEXT");
});

// ---- Monitor-claim correction: false effects need a scope-bound, canonically digested claim ----

const falseEffect = (p, n, effect, monitoring, context = ctx(n)) =>
  p.recordEffect({ fileKey: fileKey(n), effect, value: false, monitoring, context });
const rejectsAt = (fn, code, field) => assert.throws(fn,
  (error) => error instanceof ProducerInputError && error.code === code && error.field === field, `${code} ${field}`);

test("monitor: a claim for another member, effect, principal or run, a wrong digest or a reused receipt is refused atomically", () => {
  const p = producer();
  for (const n of [1, 2]) { map(p, n); access(p, n, "allowed"); }
  const before = p.produce();
  const own = monitorOf(monitorScope(1, "transferred"));
  const scoped = (over) => monitorOf(monitorScope(1, "transferred", over));
  const cases = [
    // Wrong member: m2's intact, self-consistent claim reused for m1, or m1's scope naming m2's fileKey.
    [() => falseEffect(p, 1, "transferred", monitorOf(monitorScope(2, "transferred"))), "MONITORING_SCOPE_MISMATCH", "monitoring.scope.id"],
    [() => falseEffect(p, 1, "transferred", scoped({ file_key: fileKey(2) })), "MONITORING_SCOPE_MISMATCH", "monitoring.scope.file_key"],
    // Wrong effect.
    [() => falseEffect(p, 1, "content_read", own), "MONITORING_SCOPE_MISMATCH", "monitoring.scope.effect"],
    // Wrong principal or workspace: in the scope only, or in both the scope and the context.
    [() => falseEffect(p, 1, "transferred", scoped({ principal_ref_sha256: principalSha(OTHER_PRINCIPAL) })),
      "MONITORING_SCOPE_MISMATCH", "monitoring.scope.principal_ref_sha256"],
    [() => falseEffect(p, 1, "transferred", scoped({ principal_ref_sha256: principalSha(OTHER_PRINCIPAL) }),
      ctx(1, { principalRef: OTHER_PRINCIPAL })), "CONTEXT_MISMATCH", "context"],
    [() => falseEffect(p, 1, "transferred", scoped({ workspace_key: tag("workspace-2") })), "MONITORING_SCOPE_MISMATCH", "monitoring.scope.workspace_key"],
    // Wrong run pair.
    [() => falseEffect(p, 1, "transferred", scoped({ run_id: tag("run-2") })), "MONITORING_SCOPE_MISMATCH", "monitoring.scope.run_id"],
    [() => falseEffect(p, 1, "transferred", scoped({ core_commit: "3".repeat(40) })), "MONITORING_SCOPE_MISMATCH", "monitoring.scope.core_commit"],
    // Wrong digest, or a valid receipt reused under another, otherwise exact scope.
    [() => falseEffect(p, 1, "transferred", { ...own, receiptSha256: hex("other-receipt") }), "MONITORING_RECEIPT_MISMATCH", "monitoring.receiptSha256"],
    [() => falseEffect(p, 1, "content_read", { ...own, scope: monitorScope(1, "content_read") }), "MONITORING_RECEIPT_MISMATCH", "monitoring.receiptSha256"],
    [() => falseEffect(p, 2, "transferred", { ...monitorOf(monitorScope(2, "transferred")), receiptSha256: own.receiptSha256 }),
      "MONITORING_RECEIPT_MISMATCH", "monitoring.receiptSha256"],
    // The old generic claim (complete plus any 64hex) and incomplete or absent claims are refused.
    [() => falseEffect(p, 1, "transferred", { complete: true, receiptSha256: own.receiptSha256 }), "INVALID_OBJECT", "monitoring.scope"],
    [() => falseEffect(p, 1, "transferred", { ...own, complete: false }), "FALSE_EFFECT_NEEDS_COMPLETE_MONITORING", "monitoring"],
    [() => falseEffect(p, 1, "transferred", null), "FALSE_EFFECT_NEEDS_COMPLETE_MONITORING", "monitoring"],
    [() => p.recordEffect({ fileKey: fileKey(1), effect: "transferred", value: true, monitoring: { ...own, complete: false }, context: ctx(1) }),
      "MONITORING_NOT_COMPLETE", "monitoring.complete"],
  ];
  for (const [fn, code, field] of cases) rejectsAt(fn, code, field);

  const after = p.produce();
  assert.deepEqual(after.sidecar.journal, before.sidecar.journal);
  assert.equal(after.sidecar.rejections.count, cases.length);
  for (const n of [1, 2]) {
    assert.deepEqual(diag(after, n).facts.effects, { content_read: null, transferred: null, processed: null, charged: null });
  }

  // The same original claim is refused by a producer bound to another run; that run's own claim is accepted.
  const run2 = { ...RUN, run_id: tag("run-2") };
  const other = producer({ execution_binding: run2 });
  map(other, 1); access(other, 1, "allowed");
  rejectsAt(() => falseEffect(other, 1, "transferred", own), "MONITORING_SCOPE_MISMATCH", "monitoring.scope.run_id");
  falseEffect(other, 1, "transferred", monitorOf(monitorScope(1, "transferred", run2)));
  assert.equal(other.produce().sidecar.journal.at(-1).monitoring.scope.run_id, run2.run_id);
});

test("monitor control: exact per-member/effect claims are accepted with canonical digests; true effects need none", () => {
  const p = producer();
  map(p, 1); access(p, 1, "denied"); effects(p, 1, QUIET);
  map(p, 2); access(p, 2, "denied"); effects(p, 2, { ...QUIET, content_read: true });
  const out = p.produce();
  const r1 = record(out, 1);
  assert.deepEqual([r1.content_read, r1.transferred, r1.processed, r1.charged], [false, false, false, false]);
  assert.equal(record(out, 2).content_read, true);

  const claims = out.sidecar.journal.filter((entry) => entry.kind === "effect" && entry.monitoring !== null);
  assert.equal(claims.length, 7);
  assert.equal(new Set(claims.map((entry) => entry.monitoring.receipt_sha256)).size, 7);
  for (const entry of claims) {
    const scope = monitorScope(entry.member_ids[0] === memberId(1) ? 1 : 2, entry.effect);
    // Independent recomputation: sha256 of the sorted-key JSON of {complete: true, scope}.
    const sorted = Object.fromEntries(Object.entries(scope).sort(([a], [b]) => (a < b ? -1 : 1)));
    const independent = createHash("sha256").update(JSON.stringify({ complete: true, scope: sorted }), "utf8").digest("hex");
    assert.deepEqual(entry.monitoring, { complete: true, scope, receipt_sha256: independent });
  }
  assert.equal(out.sidecar.journal.find((entry) => entry.kind === "effect" && entry.value === true).monitoring, null);
  // A structural binding of supplied data only: nothing is authenticated or claimed as a runtime pass.
  assert.equal(out.sidecar.observations_authenticated, false);
  assert.equal(out.sidecar.actual_runtime_pass_claimed, false);
  assert.ok(!JSON.stringify(out).includes(PRINCIPAL));
});
