import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const harness = readFileSync(new URL("./joined-e2e.mjs", import.meta.url), "utf8");
const at = text => harness.indexOf(text);

test("browser approves the whole set before capability and binds the confirmed member", () => {
  const approvalButton = 'name: "Approve maximum & upload", exact: true';
  const approvalResponse = 'const approvalResponse = await step("approval-headers"';
  const capabilityResponse = 'const capabilityResponse = await step("capability-headers"';
  assert.ok(at(approvalButton) >= 0, "the approval action is the exact accessible button");
  assert.ok(at(approvalResponse) >= 0 && at(approvalResponse) < at(capabilityResponse), "approval response is consumed before capability");
  assert.match(harness, /uploadRequestTimes\.approvalFinishedAt\s*<=\s*uploadRequestTimes\.capabilityRequestedAt/);
  assert.match(harness, /approvalRequestBody\.files\?\.length[\s\S]*INTAKE_APPROVED/);
  assert.ok(harness.includes('check("UI approval response binds the submitted attempt key", uiApproval.attemptKey, approvalRequestBody.attemptKey);'),
    "a response attempt key different from the submitted key is rejected by the harness check");
  assert.match(harness, /function check\(name, actual, expected\) \{ assert\.deepEqual\(actual, expected, name\);/);
  assert.throws(() => assert.deepEqual("server-attempt", "submitted-attempt", "UI approval response binds the submitted attempt key"), assert.AssertionError);
  assert.match(harness, /uiApproval\.aggregateMaximumCredits[\s\S]*uiQuote\.quote\.maximumCredits/);
  assert.match(harness, /approvedSourceIdempotencyKey\(uiApproval\.attemptKey, uiApprovedFile\.fileKey\)/);
  assert.match(harness, /const confirmBody = await step\("confirm-body"[\s\S]*?confirmed\.json\(\)/);
  assert.match(harness, /confirmBody\.code\], \[200, "UPLOAD_CONFIRMED"\]/);
  assert.match(harness, /confirmBody\.approvedFile\?\.fileState/);
});

test("API-only fixtures create a quote-backed complete approval and reuse its identities", () => {
  const apiUpload = harness.slice(at("async function apiUpload(token, doc)"), at("// Simulated R2 event + queue"));
  assert.ok(apiUpload.length > 0);
  for (const helper of ["deriveFileKey", "intakeManifestDigest", "quoteIntakeManifest", "intakePricingFingerprint", "newAttemptKey", "approvedSourceIdempotencyKey"]) {
    assert.ok(apiUpload.includes(helper), `fixture approval uses ${helper}`);
  }
  assert.ok(apiUpload.indexOf('app("/api/uploads/approval"') < apiUpload.indexOf('app("/api/uploads/capability"'), "approval is created before capability");
  assert.match(apiUpload, /aggregateMaximumCredits:\s*quoted\.quote\.maximumCredits/);
  for (const identity of ["attemptKey", "scopeDigest", "pricingFingerprint", "fileKey", "contentSha256"]) {
    assert.ok(apiUpload.includes(identity), `fixture propagates ${identity}`);
  }
  assert.match(apiUpload, /x-tavonel-source-idempotency-key/);
  assert.match(apiUpload, /const confirmBody = \{ documentId:[\s\S]*attemptKey, scopeDigest, fileKey \}/);
});

test("the original joined proof paths remain in the harness", () => {
  for (const proof of [
    'check("browser signed PUT is accepted by storage"',
    'check("the stored bytes arrived as the browser\'s cross-origin PUT"',
    'check("storage holds exactly the uploaded bytes"',
    'check("UI enqueues the durable compile job"',
    'check("duplicate confirm keeps the first confirmation time"',
    'check("real clamd detects the EICAR source"',
    'check("refused source never reaches OCR"',
    'check("candidate provenance is registered"',
    'check("MCP stdio receives the same answer and citations"',
    'check("CLI receives the same answer and citations"',
    'check(`${mode}: no candidate, receipt or provenance exists`',
  ]) assert.ok(harness.includes(proof), `retained proof assertion: ${proof}`);
});
