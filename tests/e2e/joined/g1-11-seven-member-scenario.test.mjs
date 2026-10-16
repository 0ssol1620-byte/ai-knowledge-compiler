/**
 * SYNTHETIC_CONTRACT_TEST ONLY. Real frozen fixture bytes + corrected producer, with explicitly
 * mocked Foundation functions, route replies, storage, ACL, providers and jobs. No full harness
 * import, network, DB, provider, credentials or runtime proof. Coordinator executes this file serially.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRuntimeProducer, EVIDENCE_KINDS } from "./g1-11-runtime-producer.mjs";
import { readG1_11Request, loadPinnedManifest, newSevenMemberReport, runSevenMemberScenario,
  runOptionalSevenMemberScenario, parseReservationRow, G1_11_RUNTIME_EVIDENCE_KIND,
  G1_11_MANIFEST_SHA256, G1_11_MEMBER_IDS } from "./g1-11-seven-member-scenario.mjs";

const manifestPath = process.env.G1_11_FIXTURE_MANIFEST;
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const owner = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", workspace = "synthetic_contract_workspace";
const binding = { runId: "synthetic-contract-run", coreSha: "a".repeat(40), foundationSha: "b".repeat(40) };
const envFor = cap => ({ TAVONEL_JOINED_G1_11_MANIFEST: manifestPath, TAVONEL_JOINED_G1_11_MAX_CREDITS: String(cap), GITHUB_RUN_ID: binding.runId });
const fakeDigest = `sha256:${"c".repeat(64)}`;
const outputDigest = `sha256:${"d".repeat(64)}`;
const documentIds = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"];

// Every function below is a SYNTHETIC MOCK, never a call to a live Foundation/product primitive.
function mockedScenario(options = {}) {
  const calls = [], objects = new Map(), versions = new Map(), jobs = new Map();
  const approvalFiles = new Map();
  const capture = { pair: null, serialized: null, reports: [], writes: [] };
  const putJson = (key, value) => objects.set(key, Buffer.from(JSON.stringify(value)));
  let approvals = 0;
  const deps = {
    trust: { syntheticMock: true },
    deriveFileKey: async input => { calls.push({ kind: "deriveFileKey", filename: input.relativePath }); return `fk_${digest(input.relativePath).slice(0, 40)}`; },
    intakeManifestDigest: async () => fakeDigest,
    newAttemptKey: () => "att_synthetic_mock_attempt_00000001",
    approvedSourceIdempotencyKey: async () => "e".repeat(64),
    intakePricingFingerprint: async () => fakeDigest,
    quoteIntakeManifest: files => ({ ok: true, quote: { files: files.map(() => ({ pageBasis: "unknown", approvedMaxPages: 1,
      reservedCredits: 6, maximumCredits: 6 })), maximumPages: files.length, reservedCredits: files.length * 6, maximumCredits: files.length * 6 } }),
    app: async (route, token, body) => {
      calls.push({ kind: "app", route, fileKey: body?.fileKey, documentIds: body?.documentIds });
      assert.equal(token, "synthetic_mock_session_token");
      if (route.endsWith("/triage/receipt")) return { status: 404, body: { code: "INTAKE_TRIAGE_DISABLED", reason: "SECRET_TEXT_MUST_NOT_SERIALIZE" } };
      if (route === "/api/uploads/approval") {
        if (options.approvalRefused) return { status: 409, body: { code: "CREDITS_UNAVAILABLE", detail: "SECRET_TEXT_MUST_NOT_SERIALIZE" } };
        const file = body.files[0], documentId = documentIds[approvals++];
        const approvedFile = { fileKey: file.fileKey, documentId, contentSha256: file.contentSha256, byteLength: file.byteLength,
          mimeType: file.mimeType, fileState: "approved", pageBasis: "unknown", approvedMaxPages: 1, approvedReservedCredits: 6,
          approvedMaximumCredits: 6, reservationState: "reserved", secretText: "SECRET_TEXT_MUST_NOT_SERIALIZE" };
        if (options.badNativeHash) approvedFile.contentSha256 = `sha256:${"f".repeat(64)}`;
        approvalFiles.set(file.fileKey, approvedFile);
        return { status: 200, body: { code: "INTAKE_APPROVED", approval: { approvalId: "33333333-3333-4333-8333-333333333333",
          state: "approved", attemptKey: body.attemptKey, clientManifestDigest: body.clientManifestDigest, scopeDigest: fakeDigest,
          pricingFingerprint: body.pricingFingerprint, aggregateReservedCredits: 6, aggregateMaximumCredits: 6, files: [approvedFile] } } };
      }
      if (route === "/api/uploads/capability") {
        const file = approvalFiles.get(body.fileKey);
        if (options.capabilityRefused) return { status: 422, body: { code: "SOURCE_FORMAT_REJECTED", detail: "SECRET_TEXT_MUST_NOT_SERIALIZE" } };
        return { status: 200, body: { code: "QUALIFIED", documentId: file.documentId,
          objectKey: `quarantine/${workspace}/${file.documentId}/source`, uploadUrl: `https://synthetic.mock.invalid/${file.documentId}?bearer=SECRET_URL`,
          declaredMimeType: "application/pdf", computeReservation: { maximumCredits: 6 } } };
      }
      if (route === "/api/uploads/confirm") {
        const file = approvalFiles.get(body.fileKey);
        return { status: 200, body: { code: "UPLOAD_CONFIRMED", approvedFile: { ...file, fileState: "confirmed" } } };
      }
      if (route === "/api/compile-jobs") {
        const jobId = `cjob-${String(jobs.size + 1).padStart(32, "0")}`;
        jobs.set(jobId, { documentId: body.documentIds[0], row: { state: "queued", collectionId: "", manifestDigest: "", errorCode: "" } });
        return { status: 202, body: { code: "COMPILE_JOB_ACCEPTED", jobId } };
      }
      if (route === "/api/uploads/approval/cancel") return { status: 200, body: { code: "INTAKE_SET_CANCELLED" } };
      throw new Error("unexpected mock route");
    },
    signedPut: async (url, bytes) => {
      const documentId = new URL(url).pathname.slice(1);
      calls.push({ kind: "PUT", documentId });
      objects.set(`quarantine/${workspace}/${documentId}/source`, Buffer.from(bytes));
      return 200;
    },
    authorizeCompileJobSourceAccess: async input => {
      calls.push({ kind: "ACL", input });
      return options.authority ?? { ok: true };
    },
    deliver: async (key, attempts) => {
      calls.push({ kind: "CDR", key, attempts });
      if (options.deliveryError) { const error = new Error("SECRET_TEXT_MUST_NOT_SERIALIZE"); error.code = "PROVIDER_UNAVAILABLE"; throw error; }
      const documentId = key.split("/")[2];
      if (options.reject) {
        putJson(`quarantine/${workspace}/${documentId}/cdr-reject.json`, { schemaVersion: "tavonel.cdr_reject_receipt.v1",
          sourceKey: options.badRejectSource ? "unrelated/source" : key, reasonCode: "CORRUPT_SOURCE", observedBytes: objects.get(key).length,
          declaredBytes: objects.get(key).length, provider: "synthetic_mock_cdr", occurredAt: "2026-10-10T00:00:00Z", reason: "SECRET_TEXT_MUST_NOT_SERIALIZE" });
        return;
      }
      const bytes = Buffer.from(`synthetic mock sanitized ${documentId}`), versionKey = digest(bytes);
      versions.set(documentId, versionKey);
      const prefix = `immutable/${workspace}/${workspace}/${documentId}/${versionKey}/`;
      objects.set(`${prefix}sanitized.pdf`, bytes);
      putJson(`${prefix}cdr-receipt.json`, { schemaVersion: "tavonel.cdr_receipt.v2", status: "clean", sourceKey: key,
        immutableKey: `${prefix}sanitized.pdf`, inputSha256: `sha256:${digest(objects.get(key))}`, outputSha256: `sha256:${versionKey}` });
      if (!options.ocrFailure) putJson(`${prefix}ocr.json`, { pageCount: 1, regions: [{ text: "SECRET_DOCUMENT_TEXT" }] });
    },
    ocrCallsFor: async inputSha256 => [{ inputSha256: options.uncorrelatedOcr ? `sha256:${"f".repeat(64)}` : inputSha256, status: options.ocrFailure ? 503 : 200 }],
    listKeys: async prefix => [...objects.keys()].filter(key => key.startsWith(prefix)),
    getObject: async key => {
      const bytes = objects.get(key);
      return bytes ? { size: bytes.length, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length) } : null;
    },
    jobRow: async jobId => { calls.push({ kind: "jobRow", jobId }); return jobs.get(jobId).row; },
    driveJob: async jobId => {
      calls.push({ kind: "compile", jobId });
      const job = jobs.get(jobId);
      if (options.reject || options.ocrFailure) {
        job.row = { state: "failed", collectionId: "", manifestDigest: "", errorCode: options.ocrFailure ? "OCR_PROVIDER_UNAVAILABLE" : "SOURCE_NOT_SANITIZED" };
      } else {
        job.row = { state: "ready", collectionId: `synthetic_mock_collection_${jobId}`, manifestDigest: fakeDigest, errorCode: "" };
        putJson(`immutable/${workspace}/${workspace}/collections/${job.row.collectionId}/${fakeDigest.slice(7)}/candidate-world.json`, {
          schemaVersion: "tavonel.collection_candidate.v1", collectionId: job.row.collectionId,
          ...(options.absentCandidateDigest ? {} : { manifestDigest: options.mismatchedCandidateDigest ? `sha256:${"f".repeat(64)}` : fakeDigest }),
          sourceDocuments: [{ documentId: options.badCandidateSource ? "44444444-4444-4444-8444-444444444444" : job.documentId, versionKey: versions.get(job.documentId) }],
          coreExecution: { receipt: { outputSha256: outputDigest } }, signedReceipt: { syntheticMock: true }, documentText: "SECRET_DOCUMENT_TEXT" });
      }
      return job.row;
    },
    verifyCompileReceipt: async () => {
      calls.push({ kind: "verify" });
      return options.unverified ? { ok: false, code: "COMPILE_RECEIPT_SIGNATURE_INVALID" }
        : { ok: true, payload: { manifestDigest: options.mismatchedReceipt ? `sha256:${"f".repeat(64)}` : fakeDigest, coreOutputSha256: outputDigest } };
    },
    reservation: async () => options.reservation ?? "settled|4|ocr_complete|2026-10-10T00:00:00Z",
    writeSidecar: async serialized => { capture.serialized = serialized; capture.pair = JSON.parse(serialized); capture.writes.push("pair"); return digest(serialized); },
    checkpointReport: async report => { capture.reports.push(JSON.parse(JSON.stringify(report))); capture.writes.push("report"); },
  };
  const report = newSevenMemberReport();
  const run = (overrides = {}) => runSevenMemberScenario({ report, request: readG1_11Request(envFor(12)), evidenceKind: "SYNTHETIC_CONTRACT_TEST",
    createRuntimeProducer, execution: binding, fixture: { owner, workspace, token: "synthetic_mock_session_token" }, deps, ...overrides });
  return { calls, capture, deps, report, run };
}
const memberFacts = (pair, id) => pair.sidecar.members.find(member => member.id === id);

// No fixture copy or expected block is read: coordinator supplies the exact frozen manifest path.
test("SYNTHETIC_CONTRACT_TEST: actual frozen manifest schema, path, sizes and digests", () => {
  assert.ok(manifestPath, "coordinator must set G1_11_FIXTURE_MANIFEST to the frozen manifest");
  const actual = loadPinnedManifest(manifestPath);
  assert.equal(actual.manifestSha256, G1_11_MANIFEST_SHA256);
  assert.deepEqual(actual.members.map(member => member.id), G1_11_MEMBER_IDS);
  assert.equal(actual.members.reduce((sum, member) => sum + member.bytes, 0), 4031);
  for (const member of actual.members) {
    assert.equal(digest(member.content), member.sha256Hex);
    assert.ok(!Object.hasOwn(member.ownerLabels, "expected"));
    assert.equal(member.ownerLabels.source_sha256, member.sha256Hex);
  }
  assert.ok(EVIDENCE_KINDS.includes(G1_11_RUNTIME_EVIDENCE_KIND));
});

test("SYNTHETIC_CONTRACT_TEST: default off invokes no dependencies", async () => {
  const mock = mockedScenario();
  assert.equal(await runOptionalSevenMemberScenario({ env: {}, deps: mock.deps }), null);
  assert.deepEqual(mock.calls, []);
  assert.deepEqual(mock.capture.writes, []);
});

test("SYNTHETIC_CONTRACT_TEST: missing budget and run binding cannot make product calls", async () => {
  const mock = mockedScenario();
  await assert.rejects(runOptionalSevenMemberScenario({ env: { TAVONEL_JOINED_G1_11_MANIFEST: manifestPath }, deps: mock.deps }), { code: "G1_11_MAX_CREDITS_REQUIRED" });
  await assert.rejects(mock.run({ execution: { ...binding, coreSha: null } }), { code: "G1_11_EXECUTION_BINDING_REQUIRED" });
  assert.deepEqual(mock.calls, []);
  assert.equal(mock.capture.reports.at(-1).state, "REFUSED");
});

test("SYNTHETIC_CONTRACT_TEST: missing native owner/workspace binding prevents calls", async () => {
  for (const fixture of [{ owner, token: "synthetic_mock_session_token" }, { workspace, token: "synthetic_mock_session_token" }]) {
    const mock = mockedScenario();
    await assert.rejects(mock.run({ fixture }), { code: "G1_11_FIXTURE_CONTEXT_REQUIRED" });
    assert.deepEqual(mock.calls, []);
  }
});

test("SYNTHETIC_CONTRACT_TEST: manifest refusal persists structural partial report before product work", async () => {
  const mock = mockedScenario();
  const report = await mock.run({ request: { manifestPath: `${manifestPath}.not-present`, maxCredits: 12, runId: binding.runId } });
  assert.equal(report.verdict, "PARTIAL");
  assert.equal(report.producer.created, false);
  assert.deepEqual(mock.calls, []);
  assert.equal(mock.capture.reports.at(-1).verdict, "PARTIAL");
  assert.equal(mock.capture.pair, null); // no producer exists; never manufacture an empty runtime receipt
});

test("SYNTHETIC_CONTRACT_TEST: summed quote cap checked before any approval or transfer", async () => {
  const mock = mockedScenario();
  const report = await mock.run({ request: readG1_11Request(envFor(11)) });
  assert.equal(report.budget.quotedMaximumCredits, 12);
  assert.equal(report.budget.withinCap, false);
  assert.ok(!mock.calls.some(call => ["app", "PUT", "CDR", "compile"].includes(call.kind)));
  assert.ok(mock.capture.pair);
  assert.equal(report.verdict, "PARTIAL");
});

test("SYNTHETIC_CONTRACT_TEST: native mapping precedes recorders and context is immutable owner assertion", async () => {
  const mock = mockedScenario();
  const report = await mock.run();
  const journal = mock.capture.pair.sidecar.journal;
  assert.equal(mock.capture.pair.sidecar.rejections.count, 0);
  assert.equal(report.members.normal.mapping.documentId, documentIds[0]);
  assert.equal(report.members.failed.mapping.documentId, documentIds[1]);
  for (const id of ["normal", "failed"]) {
    const rows = journal.filter(row => row.member_ids.includes(id));
    assert.equal(rows[0].kind, "member_mapping");
    for (const row of rows) {
      assert.equal(row.context.principal_ref_sha256, digest(owner));
      assert.equal(row.context.workspace_key, workspace);
      assert.equal(row.context.acl_scope, "fixture-acl:g1-11:shared-synthetic");
    }
  }
  assert.equal(report.verdict, "PARTIAL");
  assert.equal(mock.capture.pair.sidecar.evidence_kind, "SYNTHETIC_CONTRACT_TEST");
  assert.equal(mock.capture.pair.sidecar.actual_runtime_pass_claimed, false);
});

test("SYNTHETIC_CONTRACT_TEST: mismatched native content cannot bind or PUT", async () => {
  const mock = mockedScenario({ badNativeHash: true });
  await mock.run();
  assert.ok(!mock.calls.some(call => ["PUT", "CDR", "compile"].includes(call.kind)));
  assert.ok(!mock.capture.pair.sidecar.journal.some(row => row.kind === "member_mapping"));
});

test("SYNTHETIC_CONTRACT_TEST: UNAVAILABLE is not DENIED; both stop workers and compile", async () => {
  for (const code of ["COMPILE_JOB_AUTHORITY_UNAVAILABLE", "COMPILE_JOB_AUTHORITY_DENIED"]) {
    const mock = mockedScenario({ authority: { ok: false, code } });
    const report = await mock.run();
    assert.equal(report.members.normal.accessDecision.decision, code.endsWith("DENIED") ? "denied" : null);
    assert.equal(report.members.normal.accessDecision.code, code);
    assert.ok(!mock.calls.some(call => ["CDR", "compile"].includes(call.kind)));
    assert.ok(mock.calls.some(call => call.route === "/api/uploads/approval/cancel"));
    assert.equal(mock.capture.pair.sidecar.journal.filter(row => row.kind === "access_decision").length, code.endsWith("DENIED") ? 1 : 0);
    assert.equal(report.members.failed.stopped, "NOT_PROCESSED_AFTER_HALT");
  }
});

test("SYNTHETIC_CONTRACT_TEST: only explicit selected normal/failed get native IDs, PUT and CDR", async () => {
  const mock = mockedScenario();
  await mock.run();
  assert.equal(mock.calls.filter(call => call.kind === "PUT").length, 2);
  assert.equal(mock.calls.filter(call => call.kind === "CDR").length, 2);
  assert.deepEqual(mock.capture.pair.sidecar.journal.filter(row => row.kind === "member_mapping").map(row => row.id), ["normal", "failed"]);
  for (const id of ["unsupported", "denied", "duplicate", "unknown", "excluded"]) {
    const member = memberFacts(mock.capture.pair, id);
    assert.equal(member.owner_labels.authority_binding, null);
    assert.equal(member.observed_product_identity.document_id, null);
    assert.equal(member.facts.triage, null);
  }
  assert.equal(mock.report.triageDiagnostic.code, "INTAKE_TRIAGE_DISABLED");
  assert.equal(mock.capture.pair.sidecar.journal.some(row => row.kind === "triage"), false);
});

test("SYNTHETIC_CONTRACT_TEST: correlated sanitized version differs from source and is not an expectation", async () => {
  const mock = mockedScenario();
  await mock.run();
  assert.notEqual(mock.report.members.normal.cdr.sanitized.versionKey, mock.report.manifest.members.find(member => member.id === "normal").sha256);
  assert.equal(mock.report.members.failed.cdr.sanitized.receiptBound, true); // selected failed can sanitize in a mock: expected outcomes never drive code
  assert.equal(mock.report.members.normal.ocr.inputBound, true);
  const unrelated = mockedScenario({ uncorrelatedOcr: true });
  await unrelated.run();
  assert.equal(unrelated.report.members.normal.ocr.inputBound, false);
  assert.equal(memberFacts(unrelated.capture.pair, "normal").facts.cdr.ocr, null);
});

test("SYNTHETIC_CONTRACT_TEST: exact source-bound reject reason retained; bad source has no invented failure", async () => {
  const mock = mockedScenario({ reject: true });
  await mock.run();
  assert.equal(mock.report.members.normal.cdr.reject.reasonCode, "CORRUPT_SOURCE");
  assert.equal(memberFacts(mock.capture.pair, "normal").facts.cdr.failure_code, "CORRUPT_SOURCE");
  assert.equal(memberFacts(mock.capture.pair, "normal").facts.effects.content_read, null);
  assert.equal(memberFacts(mock.capture.pair, "normal").facts.effects.processed, null);
  assert.ok(!mock.capture.pair.sidecar.journal.some(row => row.kind === "effect" && ["content_read", "processed"].includes(row.effect)));
  assert.equal(mock.report.members.normal.compile.job.errorCode, "SOURCE_NOT_SANITIZED");
  const wrong = mockedScenario({ reject: true, badRejectSource: true });
  await wrong.run();
  assert.equal(memberFacts(wrong.capture.pair, "normal").facts.cdr, null);
});

test("SYNTHETIC_CONTRACT_TEST: unverified and mismatched candidate receipt never projects output", async () => {
  for (const options of [{ unverified: true }, { mismatchedReceipt: true }, { badCandidateSource: true }]) {
    const mock = mockedScenario(options);
    await mock.run();
    assert.ok(!mock.capture.pair.runtimeResults.dispositions.some(row => row.disposition === "output"));
    assert.ok(mock.report.gaps.some(row => ["COMPILE_RECEIPT_UNVERIFIED_OR_MISMATCHED", "CANDIDATE_NOT_BOUND_TO_JOB_SOURCE"].includes(row.gap)));
  }
});

test("SYNTHETIC_CONTRACT_TEST: candidate digest must be independent of job and verified payload", async () => {
  for (const options of [{ absentCandidateDigest: true }, { mismatchedCandidateDigest: true }]) {
    const mock = mockedScenario(options);
    await mock.run();
    assert.equal(mock.report.verdict, "PARTIAL");
    assert.ok(!mock.capture.pair.runtimeResults.dispositions.some(row => row.disposition === "output"));
    const compile = memberFacts(mock.capture.pair, "normal").facts.compiles[0];
    assert.equal(compile.manifest_digest, fakeDigest.slice(7));
    assert.equal(compile.verification.manifest_digest, fakeDigest.slice(7));
    if (options.absentCandidateDigest) {
      assert.equal(compile.candidate, null);
      assert.ok(mock.report.gaps.some(row => row.gap === "CANDIDATE_MANIFEST_DIGEST_UNOBSERVED"));
    } else {
      assert.equal(compile.candidate.manifest_digest, "f".repeat(64));
      assert.ok(mock.report.gaps.some(row => row.gap === "CANDIDATE_MANIFEST_DIGEST_MISMATCH"));
    }
  }
});

test("SYNTHETIC_CONTRACT_TEST: reserved/released zero retain null final time and no false charge proof", async () => {
  for (const state of ["reserved", "released"]) {
    const mock = mockedScenario({ reservation: `${state}|0|-|-` });
    await mock.run();
    const settlement = memberFacts(mock.capture.pair, "normal").facts.settlement;
    assert.equal(settlement.state, state);
    assert.equal(settlement.settled_credits, 0);
    assert.equal(settlement.settled_at, null);
    assert.equal(memberFacts(mock.capture.pair, "normal").facts.effects.charged, null);
    assert.ok(!mock.capture.pair.sidecar.journal.some(row => row.kind === "effect" && row.value === false));
  }
  assert.equal(parseReservationRow("reserved|-|-|-").settledCredits, null);
});

test("SYNTHETIC_CONTRACT_TEST: provider status, delivery errors and actual failed job code retained", async () => {
  const mock = mockedScenario({ ocrFailure: true });
  await mock.run();
  assert.deepEqual(mock.report.members.normal.ocr.correlatedCallStatuses, [503]);
  assert.equal(mock.report.members.normal.compile.job.errorCode, "OCR_PROVIDER_UNAVAILABLE");
  const thrown = mockedScenario({ deliveryError: true });
  await thrown.run();
  assert.equal(thrown.report.members.normal.delivery.error.code, "PROVIDER_UNAVAILABLE");
  assert.equal(memberFacts(thrown.capture.pair, "normal").facts.cdr, null);
});

test("SYNTHETIC_CONTRACT_TEST: actual route refusal status/code remains request observation", async () => {
  const mock = mockedScenario({ capabilityRefused: true });
  await mock.run();
  assert.deepEqual(mock.report.members.normal.capability, { status: 422, code: "SOURCE_FORMAT_REJECTED", documentIdBound: false, objectKeyBound: false });
  assert.equal(memberFacts(mock.capture.pair, "normal").facts.qualification.code, "SOURCE_FORMAT_REJECTED");
  assert.ok(!mock.calls.some(call => call.kind === "PUT"));
});

test("SYNTHETIC_CONTRACT_TEST: partial report/pair saved; no fabricated monitor, secret, URL or document text", async () => {
  const mock = mockedScenario();
  const report = await mock.run();
  assert.equal(report.verdict, "PARTIAL");
  assert.equal(report.producer.output.structuralStatus, "PARTIAL");
  assert.equal(mock.capture.reports.at(-1).verdict, "PARTIAL");
  assert.deepEqual(mock.capture.writes.slice(-2), ["pair", "report"]);
  assert.ok(mock.capture.pair.runtimeResults && mock.capture.pair.sidecar);
  const all = JSON.stringify({ report, pair: mock.capture.pair });
  for (const forbidden of ["synthetic_mock_session_token", "SECRET_TEXT", "SECRET_URL", "SECRET_DOCUMENT_TEXT", "https://", '"complete":true']) assert.ok(!all.includes(forbidden));
  for (const row of mock.capture.pair.sidecar.journal.filter(row => row.kind === "effect")) { assert.equal(row.value, true); assert.equal(row.monitoring, null); }
});

test("SYNTHETIC_CONTRACT_TEST: optional hook exists before success without importing/executing full harness", () => {
  const source = readFileSync(new URL("./joined-e2e.mjs", import.meta.url), "utf8");
  const hook = source.indexOf("// >>> optional G1-11 connection");
  const end = source.indexOf("// <<< optional G1-11 connection", hook);
  const success = source.indexOf("ledger.success = true", end);
  assert.ok(hook > source.indexOf('core.mode = "pass"'));
  assert.ok(end > hook && success > end);
  const block = source.slice(hook, end);
  assert.match(block, /if \(g1_11Request\)/);
  for (const primitive of ["app", "signedPut", "deliver", "driveJob", "jobRow", "bucket.get", "reservation", "verifyCompileReceipt", "authorizeCompileJobSourceAccess", "ocrProxy.calls.filter", "checkpoint", "writeFileAtomic"]) assert.ok(block.includes(primitive));
  assert.ok(block.indexOf("persistReport(report)") < block.indexOf("G1_11_SCENARIO_PARTIAL"));
  assert.ok(source.indexOf("const g1_11Request = readG1_11Request(process.env)") < source.indexOf('generateKeyPairSync("ed25519")'));
  assert.match(block, /structuralStatus !== "COMPLETED"/);
});
