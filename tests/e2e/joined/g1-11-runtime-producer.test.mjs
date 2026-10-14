// SYNTHETIC_CONTRACT_TEST only. Every identity, digest, reason and receipt below is invented contract
// data; nothing here is a runtime receipt, a product observation or evidence of an actual pass.
// The authority bindings, observation contexts, explicit allow/deny decisions and monitoring claims are
// synthetic test fixtures for the strengthened producer contract, not runtime facts or grants.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRuntimeProducer, monitoringReceiptSha256, ProducerInputError } from "./g1-11-runtime-producer.mjs";

const SYNTHETIC = "SYNTHETIC_CONTRACT_TEST";
const IDS = ["syn-q", "syn-w", "syn-e", "syn-r", "syn-t", "syn-y", "syn-u"];
const BINDINGS = { run_id: "synthetic-contract-run", foundation_commit: "1".repeat(40), core_commit: "2".repeat(40) };
const PRINCIPAL = "synthetic-principal";
const WORKSPACE = "synthetic-workspace";
const VERSION = "f".repeat(64);
const MANIFEST = `sha256:${"9".repeat(64)}`;
const CORE_OUT = "e".repeat(64);
const hex = (n) => n.toString(16).padStart(4, "0").repeat(16);
const principalSha = (ref) => createHash("sha256").update(ref, "utf8").digest("hex");
const fk = (id) => `synthetic-filekey-${id}`;
const doc = (id) => `synthetic-document-${id}`;
const acl = (id) => `synthetic-acl-${id}`;
const ctx = (id, principalRef = PRINCIPAL) => ({ principalRef, workspaceKey: WORKSPACE, aclScope: acl(id) });

function members(ids = IDS, principalRef = PRINCIPAL) {
  return ids.map((id, i) => ({
    id, source_id: `synthetic-source-${id}`, source_version: "synthetic-rev-1",
    source_sha256: hex(i + 1), acl_scope: acl(id),
    authority_binding: { principal_ref_sha256: principalSha(principalRef), workspace_key: WORKSPACE, acl_scope: acl(id) },
  }));
}

const producer = (ms = members()) => createRuntimeProducer({ evidence_kind: SYNTHETIC, members: ms, execution_binding: BINDINGS });

function map(p, m, documentId = null) {
  p.recordMapping({ id: m.id, fileKey: fk(m.id), contentSha256: `sha256:${m.source_sha256}`, documentId, basis: "synthetic_contract_mapping", verified: true, context: ctx(m.id) });
}

function monitor(m, effect) {
  const scope = { ...BINDINGS, id: m.id, file_key: fk(m.id), source_id: m.source_id, source_version: m.source_version,
    source_sha256: m.source_sha256, acl_scope: m.acl_scope, principal_ref_sha256: principalSha(PRINCIPAL), workspace_key: WORKSPACE, effect };
  return { complete: true, receiptSha256: monitoringReceiptSha256(scope), scope };
}

function monitorFalse(p, m, effects = ["content_read", "transferred", "processed", "charged"]) {
  for (const effect of effects) p.recordEffect({ fileKey: fk(m.id), effect, value: false, monitoring: monitor(m, effect), context: ctx(m.id) });
}

function deny(p, id, reasonCode = "SYNTHETIC_ACCESS_DENIED") {
  p.recordAccessDecision({ fileKey: fk(id), principalRef: PRINCIPAL, boundary: "external_authorization", decision: "denied", reasonCode, status: 403, context: ctx(id) });
}

function allow(p, id) {
  p.recordAccessDecision({ fileKey: fk(id), principalRef: PRINCIPAL, boundary: "external_authorization", decision: "allowed", reasonCode: null, status: 200, context: ctx(id) });
}

const TRIAGE_SCOPE = { workspaceKey: "synthetic-workspace", sourceId: "synthetic-product-source", sourceKind: "direct_upload",
  inventoryRevision: `sha256:${"d".repeat(64)}`, aclObservationSha256: null };

// One context carries one ACL scope, so each call holds the rows of a single member.
function triage(p, rows, scope = {}) {
  p.recordTriage({
    scope: { ...TRIAGE_SCOPE, ...scope },
    files: rows.map((r) => ({ fileKey: fk(r.m.id), revision: r.revision ?? null, contentSha256: `sha256:${r.m.source_sha256}`,
      aclObservationSha256: r.acl ?? null, disposition: r.disposition, reason: r.reason, exactDuplicateOf: r.dup ?? null })),
    context: ctx(rows[0].m.id),
  });
}

function sanitize(p, id, ocrPageCount = null) {
  p.recordCdrOcr({ documentId: doc(id), outcome: "sanitized", versionKey: VERSION, cdrStatus: "clean", failureCode: null, ocr: { status: 200, pageCount: ocrPageCount }, context: ctx(id) });
}

// `job` mirrors the raw harness job row { state, collectionId, manifestDigest, errorCode } plus an explicit jobId.
function compile(p, id, { verification = { ok: true, payload: { coreOutputSha256: CORE_OUT, manifestDigest: MANIFEST } }, versionKey = VERSION, job = {} } = {}) {
  p.recordCompile({
    job: { jobId: "synthetic-job", state: "ready", collectionId: "synthetic-collection", manifestDigest: MANIFEST, errorCode: "", ...job },
    documentIds: [doc(id)],
    candidate: { manifestDigest: MANIFEST, coreOutputSha256: CORE_OUT, sourceDocuments: [{ documentId: doc(id), versionKey }] },
    receiptVerification: verification,
    context: ctx(id),
  });
}

function activity(p, id) {
  for (const effect of ["content_read", "transferred", "processed"]) p.recordEffect({ fileKey: fk(id), effect, value: true, monitoring: null, context: ctx(id) });
}

const settle = (p, id, row) => p.recordSettlement({ documentId: doc(id), reasonCode: null, ...row, context: ctx(id) });
const diag = (result, id) => result.sidecar.members.find((m) => m.id === id);
const disp = (result, id) => result.runtimeResults.dispositions.find((d) => d.id === id);

test("SYNTHETIC_CONTRACT_TEST: no observations -> NOT_RUN with empty dispositions and null bindings", () => {
  const { runtimeResults, sidecar } = producer().produce(BINDINGS);
  assert.deepEqual(Object.keys(runtimeResults), ["schema", "execution", "dispositions"]);
  assert.deepEqual(runtimeResults.execution, { status: "NOT_RUN", evidence_kind: SYNTHETIC, run_id: null, foundation_commit: null, core_commit: null, stage_receipt_sha256: null });
  assert.deepEqual(runtimeResults.dispositions, []);
  assert.deepEqual(sidecar.missing_prerequisites, ["runtime_observations"]);
  assert.equal(sidecar.actual_runtime_pass_claimed, false);
  assert.equal(sidecar.qualification, "NOT_CUSTOMER_QUALIFIED");
  assert.equal(sidecar.whole_G1_acceptance, "UNKNOWN");
});

test("SYNTHETIC_CONTRACT_TEST: incomplete observations -> PARTIAL, only fully observed members projected", () => {
  const ms = members(); const p = producer(ms);
  map(p, ms[0]); deny(p, ms[0].id); monitorFalse(p, ms[0]);
  const result = p.produce(BINDINGS);
  assert.equal(result.runtimeResults.execution.status, "PARTIAL");
  assert.match(result.runtimeResults.execution.stage_receipt_sha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(result.runtimeResults.dispositions.map((d) => d.id), [ms[0].id]);
  assert.deepEqual(Object.keys(result.runtimeResults.dispositions[0]), ["id", "disposition", "reason_code", "source_id", "source_version",
    "source_sha256", "acl_scope", "content_read", "transferred", "processed", "charged", "duplicate_of", "page_count", "stage_receipt_sha256"]);
  assert.equal(disp(result, ms[0].id).stage_receipt_sha256, null);
  assert.ok(diag(result, ms[1].id).missing.includes("verified_member_mapping"));
});

test("SYNTHETIC_CONTRACT_TEST: structural COMPLETED is not an expected-case match or runtime pass", () => {
  const ms = members(); const p = producer(ms);
  for (const m of ms) { map(p, m); deny(p, m.id); monitorFalse(p, m); }
  const result = p.produce({ ...BINDINGS, evidence_kind: "RUNTIME_RECEIPT" });
  assert.equal(result.runtimeResults.execution.status, "COMPLETED");
  assert.equal(result.runtimeResults.execution.evidence_kind, SYNTHETIC);
  assert.ok(result.runtimeResults.dispositions.every((d) => d.disposition === "refused"));
  assert.equal(result.sidecar.contract_only, true);
  assert.equal(result.sidecar.expected_case_match, "NOT_EVALUATED_BY_PRODUCER");
  assert.equal(result.sidecar.actual_runtime_pass_claimed, false);
  assert.equal(result.sidecar.observations_authenticated, false);
});

test("SYNTHETIC_CONTRACT_TEST: expected blocks and extra fields cannot affect results", () => {
  const run = (ms) => { const p = producer(ms); map(p, ms[2]); triage(p, [{ m: ms[2], disposition: "needs_review", reason: "SYNTHETIC_TRIAGE_REASON" }]); monitorFalse(p, ms[2]); return p.produce(BINDINGS); };
  const plain = run(members());
  const withExpected = run(members().map((m, i) => ({ ...m, expected: { disposition: i % 2 ? "output" : "failed", reason_code: "SYNTHETIC_EXPECTED_ONLY", page_count: 0, duplicate_of: IDS[0] }, outcome: "SYNTHETIC_UNKNOWN" })));
  assert.deepEqual(withExpected, plain);
  assert.doesNotMatch(JSON.stringify(withExpected), /SYNTHETIC_EXPECTED_ONLY|SYNTHETIC_UNKNOWN|"expected"/);
});

test("SYNTHETIC_CONTRACT_TEST: member order and arbitrary ids do not change projection", () => {
  const run = (ms, ids) => { const p = producer(ms); for (const id of ids) { const m = ms.find((x) => x.id === id); map(p, m); deny(p, id); monitorFalse(p, m); } return p.produce(BINDINGS); };
  const ms = members();
  assert.deepEqual(run([...ms].reverse(), [ms[3].id]), run(ms, [ms[3].id]));
  const other = members(["zz-1", "aa-2", "mm-3", "k-4", "b-5", "x-6", "c-7"]);
  const shape = (r) => r.runtimeResults.dispositions.map(({ id, source_id, acl_scope, ...rest }) => rest);
  assert.deepEqual(shape(run(other, ["k-4"])), shape(run(ms, [ms[3].id])));
});

test("SYNTHETIC_CONTRACT_TEST: captured observations, members and outputs are not aliased", () => {
  const ms = members(); const p = producer(ms);
  const mapping = { id: ms[0].id, fileKey: fk(ms[0].id), contentSha256: `sha256:${ms[0].source_sha256}`, documentId: null, basis: "synthetic_contract_mapping", verified: true, context: ctx(ms[0].id) };
  p.recordMapping(mapping); deny(p, ms[0].id); monitorFalse(p, ms[0]);
  const before = p.produce(BINDINGS);
  mapping.fileKey = "synthetic-mutated"; ms[0].source_id = "synthetic-mutated"; ms[0].acl_scope = "synthetic-mutated";
  before.runtimeResults.dispositions[0].disposition = "output"; before.sidecar.journal.length = 0;
  const after = p.produce(BINDINGS);
  assert.equal(after.runtimeResults.dispositions[0].source_id, `synthetic-source-${ms[0].id}`);
  assert.equal(after.runtimeResults.dispositions[0].disposition, "refused");
  assert.equal(after.sidecar.journal[0].file_key, fk(ms[0].id));
});

test("SYNTHETIC_CONTRACT_TEST: observations require explicit bindings; evidence kind is fixed", () => {
  const ms = members();
  // Without a constructor run/commit binding no observation is accepted.
  const unbound = createRuntimeProducer({ evidence_kind: SYNTHETIC, members: ms });
  assert.throws(() => map(unbound, ms[0]), /UNBOUND_RUN/);
  const p = producer(ms); map(p, ms[0]);
  assert.throws(() => p.produce({ ...BINDINGS, run_id: "synthetic-other-run" }), /RUN_BINDING_MISMATCH/);
  assert.throws(() => p.produce({ ...BINDINGS, core_commit: "ABC" }), /INVALID_COMMIT/);
  assert.throws(() => p.produce({ ...BINDINGS, run_id: "x".repeat(513) }), /INVALID_TEXT/);
  assert.throws(() => createRuntimeProducer({ evidence_kind: "ACTUAL_PASS", members: ms, execution_binding: BINDINGS }), /INVALID_ENUM/);
  assert.throws(() => createRuntimeProducer({ evidence_kind: SYNTHETIC, members: ms.slice(1), execution_binding: BINDINGS }), /MEMBER_COUNT/);
});

test("SYNTHETIC_CONTRACT_TEST: absent or unmonitored effects stay incomplete, never false", () => {
  const ms = members(); const p = producer(ms);
  map(p, ms[0]); deny(p, ms[0].id);
  assert.throws(() => p.recordEffect({ fileKey: fk(ms[0].id), effect: "transferred", value: false, monitoring: { ...monitor(ms[0], "transferred"), complete: false }, context: ctx(ms[0].id) }), /FALSE_EFFECT_NEEDS_COMPLETE_MONITORING/);
  assert.throws(() => p.recordEffect({ fileKey: fk(ms[0].id), effect: "processed", value: false, monitoring: null, context: ctx(ms[0].id) }), /FALSE_EFFECT_NEEDS_COMPLETE_MONITORING/);
  const result = p.produce(BINDINGS);
  assert.equal(disp(result, ms[0].id), undefined);
  assert.deepEqual(diag(result, ms[0].id).missing, ["effect:content_read", "effect:transferred", "effect:processed", "effect:charged"]);
  assert.equal(result.runtimeResults.execution.status, "PARTIAL");
});

test("SYNTHETIC_CONTRACT_TEST: reserved or released-zero rows are not charges; only final settled credits are", () => {
  const ms = members(); const p = producer(ms);
  for (const m of ms.slice(0, 3)) { map(p, m, doc(m.id)); deny(p, m.id); monitorFalse(p, m, ["content_read", "transferred", "processed"]); }
  settle(p, ms[0].id, { state: "reserved", settledCredits: null, settledAt: null });
  settle(p, ms[1].id, { state: "released", settledCredits: 0, settledAt: "synthetic-settled-at" });
  settle(p, ms[2].id, { state: "settled", settledCredits: 3, settledAt: "synthetic-settled-at" });
  assert.throws(() => p.recordEffect({ fileKey: fk(ms[0].id), effect: "charged", value: true, monitoring: null, context: ctx(ms[0].id) }), /CHARGE_REQUIRES_SETTLEMENT_ROW/);
  assert.throws(() => settle(p, ms[2].id, { state: "settled", settledCredits: 6, settledAt: "synthetic-settled-at" }), /SETTLEMENT_CHANGED/);
  let result = p.produce(BINDINGS);
  assert.ok(diag(result, ms[0].id).missing.includes("effect:charged"));
  assert.ok(diag(result, ms[1].id).missing.includes("effect:charged"));
  assert.equal(disp(result, ms[2].id).charged, true);
  p.recordEffect({ fileKey: fk(ms[2].id), effect: "charged", value: false, monitoring: monitor(ms[2], "charged"), context: ctx(ms[2].id) });
  result = p.produce(BINDINGS);
  assert.ok(diag(result, ms[2].id).conflicts.includes("settled_credits_contradict_monitored_no_charge"));
});

test("SYNTHETIC_CONTRACT_TEST: mismatched source digest, fileKey, document, revision and ACL are rejected", () => {
  const ms = members(); const p = producer(ms);
  assert.throws(() => p.recordMapping({ id: ms[0].id, fileKey: fk(ms[0].id), contentSha256: ms[1].source_sha256, basis: "synthetic", verified: true, context: ctx(ms[0].id) }), /DIGEST_MISMATCH/);
  assert.throws(() => p.recordMapping({ id: ms[0].id, fileKey: fk(ms[0].id), contentSha256: ms[0].source_sha256, basis: "synthetic", verified: false, context: ctx(ms[0].id) }), /MAPPING_NOT_VERIFIED/);
  map(p, ms[0], doc(ms[0].id)); map(p, ms[1]);
  assert.throws(() => p.recordMapping({ id: ms[0].id, fileKey: "synthetic-other-key", contentSha256: ms[0].source_sha256, basis: "synthetic", verified: true, context: ctx(ms[0].id) }), /IDENTITY_CHANGED/);
  assert.throws(() => p.recordMapping({ id: ms[2].id, fileKey: fk(ms[0].id), contentSha256: ms[2].source_sha256, basis: "synthetic", verified: true, context: ctx(ms[2].id) }), /IDENTITY_COLLAPSE/);
  assert.throws(() => p.recordConfirm({ status: 200, code: "SYNTHETIC_OK", approvedFile: { fileKey: fk(ms[1].id), documentId: doc(ms[0].id), fileState: "confirmed" }, context: ctx(ms[1].id) }), /IDENTITY_COLLAPSE/);
  assert.throws(() => p.recordQualification({ fileKey: fk(ms[3].id), status: 200, code: "SYNTHETIC_OK", outcome: "qualified", context: ctx(ms[3].id) }), /UNMAPPED_FILE_KEY/);
  triage(p, [{ m: ms[1], disposition: "needs_review", reason: "SYNTHETIC_R", revision: "synthetic-product-rev-a", acl: "a".repeat(64) }]);
  assert.throws(() => triage(p, [{ m: ms[1], disposition: "needs_review", reason: "SYNTHETIC_R", revision: "synthetic-product-rev-b", acl: "a".repeat(64) }]), /TRIAGE_CHANGED/);
  assert.throws(() => triage(p, [{ m: ms[1], disposition: "needs_review", reason: "SYNTHETIC_R", revision: "synthetic-product-rev-a", acl: "b".repeat(64) }]), /TRIAGE_CHANGED/);
  sanitize(p, ms[0].id);
  assert.throws(() => p.recordCdrOcr({ documentId: doc(ms[0].id), outcome: "sanitized", versionKey: "0".repeat(64), cdrStatus: "clean", ocr: null, context: ctx(ms[0].id) }), /REVISION_CHANGED/);
  const result = p.produce(BINDINGS);
  assert.equal(result.sidecar.rejections.count, 9);
  assert.equal(result.runtimeResults.execution.status, "PARTIAL");
  assert.equal(diag(result, ms[1].id).observed_product_identity.triage_revision, "synthetic-product-rev-a");
  assert.equal(diag(result, ms[0].id).observed_product_identity.sanitized_version_key, VERSION);
  assert.ok(result.sidecar.members.every((m) => m.owner_labels.source_version === "synthetic-rev-1"));
});

test("SYNTHETIC_CONTRACT_TEST: same-digest members keep distinct identities; duplicate target only from mapped triage", () => {
  const ms = members(); ms[1].source_sha256 = ms[0].source_sha256; ms[2].source_sha256 = ms[0].source_sha256;
  const p = producer(ms);
  map(p, ms[0]); map(p, ms[1]); map(p, ms[2]); map(p, ms[3]);
  triage(p, [{ m: ms[1], disposition: "needs_review", reason: "SYNTHETIC_DUP_REASON", dup: fk(ms[0].id) }]);
  triage(p, [{ m: ms[2], disposition: "needs_review", reason: "SYNTHETIC_DUP_REASON", dup: "synthetic-unmapped-key" }]);
  triage(p, [{ m: ms[3], disposition: "needs_review", reason: "SYNTHETIC_DUP_REASON", dup: fk(ms[0].id) }]);
  for (const m of ms.slice(1, 4)) { allow(p, m.id); monitorFalse(p, m); }
  const result = p.produce(BINDINGS);
  assert.notEqual(diag(result, ms[0].id).observed_product_identity.file_key, diag(result, ms[1].id).observed_product_identity.file_key);
  assert.equal(disp(result, ms[1].id).duplicate_of, ms[0].id);
  assert.notEqual(disp(result, ms[1].id).source_id, disp(result, ms[1].id).duplicate_of);
  assert.ok(diag(result, ms[2].id).missing.includes("duplicate_target_mapping"));
  assert.ok(diag(result, ms[3].id).conflicts.includes("duplicate_target_digest_differs"));
  assert.equal(disp(result, ms[0].id), undefined);
});

test("SYNTHETIC_CONTRACT_TEST: activity for denied or excluded members is recorded, not hidden", () => {
  const ms = members(); const p = producer(ms);
  map(p, ms[0]); map(p, ms[1]);
  deny(p, ms[0].id); activity(p, ms[0].id); monitorFalse(p, ms[0], ["charged"]);
  triage(p, [{ m: ms[1], disposition: "exclude", reason: "SYNTHETIC_EXCLUDE_REASON" }]);
  allow(p, ms[1].id);
  p.recordEffect({ fileKey: fk(ms[1].id), effect: "transferred", value: true, monitoring: null, context: ctx(ms[1].id) });
  monitorFalse(p, ms[1], ["content_read", "processed", "charged"]);
  const result = p.produce(BINDINGS);
  assert.deepEqual([disp(result, ms[0].id).content_read, disp(result, ms[0].id).transferred, disp(result, ms[0].id).processed], [true, true, true]);
  assert.equal(disp(result, ms[1].id).disposition, "excluded");
  assert.equal(disp(result, ms[1].id).reason_code, "SYNTHETIC_EXCLUDE_REASON");
  assert.equal(disp(result, ms[1].id).transferred, true);
  assert.ok(diag(result, ms[0].id).notes.includes("activity_observed_for_non_stage_result"));
  assert.throws(() => p.recordEffect({ fileKey: fk(ms[1].id), effect: "transferred", value: false, monitoring: monitor(ms[1], "transferred"), context: ctx(ms[1].id) }), /EFFECT_CONFLICT/);
});

test("SYNTHETIC_CONTRACT_TEST: needs_review is pending (not refused) and include is not output", () => {
  const ms = members(); const p = producer(ms);
  map(p, ms[0]); map(p, ms[1]);
  triage(p, [{ m: ms[0], disposition: "needs_review", reason: "SYNTHETIC_UNSUPPORTED_REVIEW" }]);
  triage(p, [{ m: ms[1], disposition: "include", reason: "SYNTHETIC_CANDIDATE" }]);
  allow(p, ms[0].id); allow(p, ms[1].id);
  monitorFalse(p, ms[0]); monitorFalse(p, ms[1]);
  const result = p.produce(BINDINGS);
  assert.deepEqual([disp(result, ms[0].id).disposition, disp(result, ms[0].id).reason_code], ["pending", "SYNTHETIC_UNSUPPORTED_REVIEW"]);
  assert.equal(disp(result, ms[1].id), undefined);
  assert.ok(diag(result, ms[1].id).notes.includes("triage_include_is_not_output"));
  assert.ok(diag(result, ms[1].id).missing.includes("terminal_product_result"));
});

test("SYNTHETIC_CONTRACT_TEST: only a verified signed compile bound to the member version is output", () => {
  const outcome = (options) => {
    const ms = members(); const p = producer(ms);
    map(p, ms[0], doc(ms[0].id)); allow(p, ms[0].id); sanitize(p, ms[0].id); compile(p, ms[0].id, options);
    activity(p, ms[0].id); settle(p, ms[0].id, { state: "settled", settledCredits: 2, settledAt: "synthetic-settled-at" });
    const result = p.produce(BINDINGS);
    return { record: disp(result, ms[0].id), notes: diag(result, ms[0].id).notes };
  };
  assert.equal(outcome({ verification: null }).record, undefined);
  assert.ok(outcome({ verification: null }).notes.includes("compile_candidate_without_verified_signed_receipt"));
  assert.equal(outcome({ verification: { ok: false } }).record, undefined);
  assert.ok(outcome({ verification: { ok: true, payload: { coreOutputSha256: "0".repeat(64), manifestDigest: MANIFEST } } }).notes.includes("compile_receipt_digest_mismatch"));
  assert.throws(
    () => outcome({ versionKey: "0".repeat(64) }),
    error => error instanceof ProducerInputError && error.code === "SOURCE_VERSION_MISMATCH",
  );
  const { record } = outcome({});
  assert.deepEqual([record.disposition, record.reason_code, record.processed, record.charged], ["output", "ready", true, true]);
  assert.match(record.stage_receipt_sha256, /^[a-f0-9]{64}$/);
});

test("SYNTHETIC_CONTRACT_TEST: output needs the raw job-row manifest digest to equal the candidate and verified payload", () => {
  const outcome = (job) => {
    const ms = members(); const p = producer(ms);
    map(p, ms[0], doc(ms[0].id)); allow(p, ms[0].id); sanitize(p, ms[0].id); compile(p, ms[0].id, { job });
    activity(p, ms[0].id); settle(p, ms[0].id, { state: "settled", settledCredits: 2, settledAt: "synthetic-settled-at" });
    const result = p.produce(BINDINGS);
    return { record: disp(result, ms[0].id), d: diag(result, ms[0].id) };
  };
  for (const [job, note, rowDigest] of [
    [{ manifestDigest: undefined }, "compile_job_manifest_digest_unobserved", null],
    [{ manifestDigest: "" }, "compile_job_manifest_digest_unobserved", null],
    [{ manifestDigest: `sha256:${"8".repeat(64)}` }, "compile_job_manifest_digest_mismatch", "8".repeat(64)],
  ]) {
    const { record, d } = outcome(job);
    assert.equal(record, undefined);
    assert.ok(d.notes.includes(note));
    assert.ok(d.missing.includes("terminal_product_result"));
    // The verified candidate and the effects are still recorded; only the output projection is withheld.
    const [row] = d.facts.compiles;
    assert.deepEqual([row.manifest_digest, row.candidate.manifest_digest, row.verification.ok, row.verification.manifest_digest],
      [rowDigest, "9".repeat(64), true, "9".repeat(64)]);
    assert.deepEqual([d.facts.effects.processed.value, d.facts.settlement.settled_credits], [true, 2]);
  }
  assert.equal(outcome({ manifestDigest: "9".repeat(64) }).record.disposition, "output");
  const failed = outcome({ state: "failed", manifestDigest: "", errorCode: "SYNTHETIC_COMPILE_FAILURE_Q7" }).record;
  assert.deepEqual([failed.disposition, failed.reason_code], ["failed", "SYNTHETIC_COMPILE_FAILURE_Q7"]);
});

test("SYNTHETIC_CONTRACT_TEST: triage scope workspace/source identity is retained; a changed scope is rejected, not ignored", () => {
  const ms = members(); const p = producer(ms);
  map(p, ms[0]);
  const rows = [{ m: ms[0], disposition: "needs_review", reason: "SYNTHETIC_R" }];
  triage(p, rows);
  assert.throws(() => triage(p, rows, { workspaceKey: "synthetic-other-workspace" }), /SCOPE_CHANGED/);
  assert.throws(() => triage(p, rows, { sourceId: "synthetic-other-product-source" }), /SCOPE_CHANGED/);
  assert.throws(() => triage(p, rows, { aclObservationSha256: "a".repeat(64) }), /SCOPE_CHANGED/);
  assert.throws(() => triage(p, rows, { workspaceKey: undefined }), /INVALID_TEXT: scope\.workspaceKey/);
  assert.throws(() => triage(p, rows, { sourceId: null }), /INVALID_TEXT: scope\.sourceId/);
  triage(p, rows);
  monitorFalse(p, ms[0]);
  // The product triage scope grants nothing: without an explicit access decision the member stays unprojected.
  const unprojected = p.produce(BINDINGS);
  assert.equal(disp(unprojected, ms[0].id), undefined);
  assert.equal(diag(unprojected, ms[0].id).facts.access, null);
  assert.ok(diag(unprojected, ms[0].id).missing.includes("external_access_decision"));
  allow(p, ms[0].id);
  const result = p.produce(BINDINGS);
  assert.equal(result.sidecar.rejections.count, 5);
  assert.equal(result.runtimeResults.execution.status, "PARTIAL");
  const d = diag(result, ms[0].id);
  assert.deepEqual([d.observed_product_identity.triage_workspace_key, d.observed_product_identity.triage_source_id],
    ["synthetic-workspace", "synthetic-product-source"]);
  assert.deepEqual([d.facts.triage.scope.workspace_key, d.facts.triage.scope.source_id], ["synthetic-workspace", "synthetic-product-source"]);
  // Fixture owner labels are unchanged by the product scope; the scope grants nothing.
  assert.deepEqual([disp(result, ms[0].id).source_id, disp(result, ms[0].id).acl_scope, disp(result, ms[0].id).disposition],
    [ms[0].source_id, ms[0].acl_scope, "pending"]);
  assert.equal(d.facts.access.decision, "allowed");
});

test("SYNTHETIC_CONTRACT_TEST: unknown pages stay null; quote ceilings are never page counts", () => {
  const ms = members(); const p = producer(ms);
  map(p, ms[0], doc(ms[0].id)); allow(p, ms[0].id);
  p.recordQuote({ fileKeys: [fk(ms[0].id)], result: { ok: true, quote: { files: [{ pageBasis: "unknown", approvedMaxPages: 777, reservedCredits: 777, maximumCredits: 1554 }], maximumPages: 777, reservedCredits: 777, maximumCredits: 1554 } }, context: ctx(ms[0].id) });
  assert.throws(() => sanitize(p, ms[0].id, 0), /INVALID_PAGE_COUNT/);
  sanitize(p, ms[0].id, null); compile(p, ms[0].id); activity(p, ms[0].id);
  settle(p, ms[0].id, { state: "settled", settledCredits: 777, settledAt: "synthetic-settled-at" });
  const result = p.produce(BINDINGS);
  assert.equal(disp(result, ms[0].id).page_count, null);
  assert.equal(diag(result, ms[0].id).facts.quote.approved_max_pages, 777);
  assert.throws(() => p.recordQuote({ fileKeys: [fk(ms[0].id)], result: { ok: true, quote: { files: [{ pageBasis: "unknown", approvedMaxPages: 1.5, reservedCredits: 1, maximumCredits: 1 }], maximumPages: 1, reservedCredits: 1, maximumCredits: 1 } }, context: ctx(ms[0].id) }), /INVALID_UNITS/);
});

test("SYNTHETIC_CONTRACT_TEST: no implicit refusal or failure; failure reason is the actual product code", () => {
  const ms = members(); const p = producer(ms);
  map(p, ms[0]); map(p, ms[1], doc(ms[1].id));
  allow(p, ms[0].id); allow(p, ms[1].id);
  p.recordQuote({ fileKeys: [fk(ms[0].id)], result: { ok: false, code: "SYNTHETIC_QUOTE_CODE", index: 0 }, context: ctx(ms[0].id) });
  p.recordApproval({ phase: "approve", status: 403, code: "SYNTHETIC_WHOLE_REQUEST_FORBIDDEN", fileKeys: [fk(ms[0].id)], context: ctx(ms[0].id) });
  monitorFalse(p, ms[0]);
  p.recordCdrOcr({ documentId: doc(ms[1].id), outcome: "failed", versionKey: null, cdrStatus: "synthetic-status", failureCode: "SYNTHETIC_CDR_FAILURE_Z9", ocr: null, context: ctx(ms[1].id) });
  monitorFalse(p, ms[1], ["content_read", "transferred", "charged"]);
  let result = p.produce(BINDINGS);
  assert.equal(disp(result, ms[0].id), undefined);
  assert.ok(diag(result, ms[0].id).missing.includes("terminal_product_result"));
  assert.ok(diag(result, ms[1].id).missing.includes("effect:processed"));
  p.recordEffect({ fileKey: fk(ms[1].id), effect: "processed", value: true, monitoring: null, context: ctx(ms[1].id) });
  result = p.produce(BINDINGS);
  assert.deepEqual([disp(result, ms[1].id).disposition, disp(result, ms[1].id).reason_code], ["failed", "SYNTHETIC_CDR_FAILURE_Z9"]);
  assert.match(disp(result, ms[1].id).stage_receipt_sha256, /^[a-f0-9]{64}$/);
});

test("SYNTHETIC_CONTRACT_TEST: whole-request 403 is not per-file ACL; confirm replay is not a duplicate result", () => {
  const ms = members(); const p = producer(ms);
  map(p, ms[0]);
  p.recordApproval({ phase: "approve", status: 403, code: "SYNTHETIC_FORBIDDEN", fileKeys: [fk(ms[0].id)], context: ctx(ms[0].id) });
  for (let i = 0; i < 2; i++) p.recordConfirm({ status: 200, code: "SYNTHETIC_CONFIRMED", approvedFile: { fileKey: fk(ms[0].id), documentId: doc(ms[0].id), fileState: "confirmed" }, context: ctx(ms[0].id) });
  assert.throws(() => p.recordAccessDecision({ fileKey: fk(ms[0].id), principalRef: "synthetic", boundary: "triage_acl_observation", decision: "denied", reasonCode: "SYNTHETIC", context: ctx(ms[0].id) }), /NOT_EXTERNAL_ACCESS_BOUNDARY/);
  monitorFalse(p, ms[0]);
  const result = p.produce(BINDINGS);
  assert.equal(disp(result, ms[0].id), undefined);
  assert.equal(diag(result, ms[0].id).facts.confirm.replay_count, 1);
  assert.deepEqual(diag(result, ms[0].id).result_basis, []);
});

test("SYNTHETIC_CONTRACT_TEST: response fields are copied from the observation, prefix normalized once", () => {
  const ms = members(); const p = producer(ms);
  map(p, ms[0]); allow(p, ms[0].id);
  p.recordApproval({ phase: "approve", status: 200, code: "SYNTHETIC_APPROVED_CODE", approval: {
    approvalId: "synthetic-approval", state: "approved", aggregateReservedCredits: 4, aggregateMaximumCredits: 8,
    files: [{ fileKey: fk(ms[0].id), documentId: doc(ms[0].id), fileState: "approved", contentSha256: `sha256:${ms[0].source_sha256}`,
      pageBasis: "declared", approvedMaxPages: 2, approvedReservedCredits: 4, approvedMaximumCredits: 8, reservationState: "synthetic-held" }] }, context: ctx(ms[0].id) });
  p.recordQualification({ fileKey: fk(ms[0].id), status: 422, code: "SYNTHETIC_QUALIFICATION_REFUSAL_K3", outcome: "refused", context: ctx(ms[0].id) });
  monitorFalse(p, ms[0]);
  const result = p.produce(BINDINGS);
  assert.deepEqual([disp(result, ms[0].id).disposition, disp(result, ms[0].id).reason_code], ["refused", "SYNTHETIC_QUALIFICATION_REFUSAL_K3"]);
  assert.deepEqual([diag(result, ms[0].id).facts.approval.document_id, diag(result, ms[0].id).facts.approval.reservation_state], [doc(ms[0].id), "synthetic-held"]);
  assert.equal(diag(result, ms[0].id).facts.approval.content_sha256, ms[0].source_sha256);
  assert.throws(() => p.recordMapping({ id: ms[1].id, fileKey: fk(ms[1].id), contentSha256: `sha256:sha256:${ms[1].source_sha256}`, basis: "synthetic", verified: true, context: ctx(ms[1].id) }), /INVALID_SHA256/);
  assert.throws(() => p.recordMapping({ id: ms[1].id, fileKey: fk(ms[1].id), contentSha256: "A".repeat(64), basis: "synthetic", verified: true, context: ctx(ms[1].id) }), /INVALID_SHA256/);
  assert.throws(() => p.recordQualification({ fileKey: fk(ms[0].id), status: 500, code: "SYNTHETIC", outcome: "refused", context: ctx(ms[0].id) }), /REFUSAL_NEEDS_4XX/);
});

// Accepted text fields (code, reasonCode, basis, fileKey, documentId, run_id, ...) are only length/trim/
// control-character validated and are retained verbatim; they can hold URLs or tokens. No redaction is claimed.
test("SYNTHETIC_CONTRACT_TEST: extra authorization/uploadUrl/documentText fields are ignored, principalRef is hashed and rejection errors omit input values", () => {
  const secret = "Bearer SYNTHETIC-SECRET-DO-NOT-ECHO";
  // This test's synthetic authority bindings and contexts name the secret-bearing principal reference.
  const ms = members(IDS, secret); const p = producer(ms);
  p.recordMapping({ id: ms[0].id, fileKey: fk(ms[0].id), contentSha256: ms[0].source_sha256, basis: "synthetic", verified: true,
    authorization: secret, uploadUrl: `https://synthetic.invalid/?sig=${secret}`, documentText: secret, context: ctx(ms[0].id, secret) });
  p.recordAccessDecision({ fileKey: fk(ms[0].id), principalRef: secret, boundary: "external_authorization", decision: "denied", reasonCode: "SYNTHETIC_DENY", context: ctx(ms[0].id, secret) });
  let error;
  try { p.recordConfirm({ status: 200, code: `${secret}\n`, approvedFile: null, context: ctx(ms[0].id, secret) }); } catch (caught) { error = caught; }
  assert.ok(error instanceof ProducerInputError);
  assert.doesNotMatch(error.message, /SYNTHETIC-SECRET/);
  const serialized = JSON.stringify(p.produce(BINDINGS));
  assert.doesNotMatch(serialized, /SYNTHETIC-SECRET|synthetic\.invalid|uploadUrl|"authorization"|documentText/);
  assert.match(serialized, /principal_ref_sha256/);
});
