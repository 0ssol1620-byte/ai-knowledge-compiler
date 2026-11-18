/**
 * phase-export.mjs: stub app/verifier cases that must each fail the phase, plus real-path cases - a signed zip built here is
 * read by readZipEntry and checked by the shipped tavonel-verify-export.mjs / tavonel-verify-package.mjs from a Foundation
 * checkout (TAVONEL_FOUNDATION_DIR, default the lane's fnd-int); those tests are reported as skipped when it is absent.
 */
import assert from "node:assert/strict";
import { createHash, createPublicKey, generateKeyPairSync, sign } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { crc32, deflateRawSync } from "node:zlib";
import { PhaseContractError, runPhase } from "./phase-contract.mjs";
import { exportPhase, foreignTrustStore, judgeBinding, judgeRefusal, readZipEntry, verdict } from "./phase-export.mjs";

const FOUNDATION = process.env.TAVONEL_FOUNDATION_DIR ?? "D:/CodexProjects/v34-lanes/fnd-int";
const VERIFIER_DIR = path.join(FOUNDATION, "nextjs/public/developer");
const haveFoundation = existsSync(path.join(VERIFIER_DIR, "tavonel-verify-export.mjs")) && existsSync(path.join(VERIFIER_DIR, "tavonel-verify-package.mjs"));
const D2 = `sha256:${"2".repeat(64)}`, D1 = `sha256:${"1".repeat(64)}`;
const COLLECTION = "col-synthetic-1", WORKSPACE = "pilot-abc123";
const sha = body => `sha256:${createHash("sha256").update(body).digest("hex")}`;
const refusedWith = code => error => error instanceof PhaseContractError && error.code === code;

// ---- a signed export archive, built the way lib/collection-download.ts + lib/export-signing.ts build one -------------------
function zip(entries) {
  const locals = [], centrals = [];
  let offset = 0;
  for (const [name, data] of Object.entries(entries)) {
    const nameBytes = Buffer.from(name), packed = deflateRawSync(data), crc = crc32(data);
    const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(8, 8);
    local.writeUInt32LE(crc, 14); local.writeUInt32LE(packed.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(nameBytes.length, 26);
    const central = Buffer.alloc(46); central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(8, 10);
    central.writeUInt32LE(crc, 16); central.writeUInt32LE(packed.length, 20); central.writeUInt32LE(data.length, 24); central.writeUInt16LE(nameBytes.length, 28); central.writeUInt32LE(offset, 42);
    locals.push(local, nameBytes, packed); centrals.push(central, nameBytes);
    offset += 30 + nameBytes.length + packed.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(Object.keys(entries).length, 8); end.writeUInt16LE(Object.keys(entries).length, 10);
  end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

function keyMaterial(keyId = "joined-e2e-test") {
  const pair = generateKeyPairSync("ed25519");
  const spki = createPublicKey(pair.privateKey).export({ format: "der", type: "spki" });
  const entry = { keyId, keyVersion: 1, algorithm: "Ed25519", status: "active", notBefore: new Date(Date.now() - 3_600_000).toISOString(),
    expiresAt: new Date(Date.now() + 6 * 3_600_000).toISOString(), publicKeySpkiDerBase64: spki.toString("base64"), publicKeySpkiSha256: sha(spki) };
  return { pair, entry, trustStoreJson: JSON.stringify({ schemaVersion: "tavonel.export_trust.v2", minimumSignatureVersion: 2, activeKeyId: keyId, keys: [entry] }) };
}

function signedArchive({ manifestDigest = D2, collectionId = COLLECTION, material = keyMaterial() } = {}) {
  const readme = Buffer.from("# synthetic package\n");
  const manifest = Buffer.from(`${JSON.stringify({ schemaVersion: "tavonel.signed_export_manifest.v1", collectionId, manifestDigest,
    files: [{ path: "README.md", mediaType: "text/markdown", sizeBytes: readme.length, sha256: sha(readme) }] }, null, 2)}\n`);
  const head = { schemaVersion: "tavonel.export_signature.v2", algorithm: "Ed25519", signatureScope: "tavonel.signed_export_manifest.v1", keyId: material.entry.keyId,
    keyVersion: 1, issuedAt: new Date(Date.now() - 60_000).toISOString(), expiresAt: new Date(Date.now() + 3_600_000).toISOString(), signedPayloadSha256: sha(manifest) };
  const signature = sign(null, Buffer.concat([Buffer.from(`${JSON.stringify(head)}\n`), manifest]), material.pair.privateKey);
  const receipt = { ...head, publicKeySpkiDerBase64: material.entry.publicKeySpkiDerBase64, publicKeySpkiSha256: material.entry.publicKeySpkiSha256, signatureBase64: signature.toString("base64") };
  return { bytes: zip({ "README.md": readme, "manifest/export-manifest.json": manifest, "signatures/export-manifest.ed25519.json": Buffer.from(`${JSON.stringify(receipt, null, 2)}\n`) }), material };
}

// ---- stubs ---------------------------------------------------------------------------------------------------------------
const noStore = { "cache-control": "no-store" };
const refusal = (body = { code: "MEMBER_REVOKED" }) => ({ status: 403, headers: noStore, bytes: Buffer.from(JSON.stringify(body)) });
const FAIL_LINE = "TAVONEL export verification failed: x\n";

/** Stub verifiers keyed on the archive's file name: control.zip passes, tamper-* fail, foreign trust fails. */
function stubVerifier(overrides = {}) {
  const calls = [];
  const runVerifier = async (script, args) => {
    calls.push([script, ...args.map(arg => path.basename(arg))]);
    const archive = path.basename(args[1]), trust = path.basename(args[3] ?? "");
    const isExport = script === "tavonel-verify-export.mjs";
    const rejected = isExport ? { code: 1, stderr: FAIL_LINE } : { code: 1, stderr: "  ERROR   X: y\n" };
    const custom = overrides[`${isExport ? "export" : "package"}:${archive.startsWith("joined-export-tamper") ? "tamper" : trust.includes("foreign") ? "foreign" : "control"}`];
    if (custom) return custom;
    if (archive.includes("tamper") || trust.includes("foreign")) return rejected;
    return { code: 0, stderr: "" };
  };
  return { runVerifier, calls };
}

function fixture(overrides = {}) {
  const workDir = mkdtempSync(path.join(tmpdir(), "phase-export-"));
  const material = keyMaterial();
  const archive = signedArchive({ material });
  const verifier = stubVerifier(overrides.verifier);
  const state = {
    ownerToken: "owner-token", collectionId: COLLECTION, workspaceKey: WORKSPACE, workDir, expectedManifestDigest: D2, previousManifestDigest: D1,
    trustStoreJson: material.trustStoreJson, leakTerms: ["Zebra Clause"], revoked: { token: "revoked-token" },
    download: async token => (token === "revoked-token" ? refusal() : { status: 200, headers: {}, bytes: archive.bytes }),
    runVerifier: verifier.runVerifier, ...overrides.state,
  };
  return { state, workDir, calls: verifier.calls, archive, material };
}
const input = (state, extra = {}) => ({ app: () => {}, sql: () => {}, check: () => {}, hop: () => {}, step: (_name, _ms, operation) => operation(), state, deadline: Date.now() + 60_000, ...extra });
const run = async (f, extra) => { try { return await runPhase(exportPhase, input(f.state, extra)); } finally { rmSync(f.workDir, { recursive: true, force: true }); } };

test("every surface answers as required: outcome met, counts derived from the loop that ran", async () => {
  const f = fixture();
  const out = await run(f);
  assert.deepEqual({ ...out }, { outcome: "met", package_download: "ok", package_binding: "matches", signature_verifier: "accepted", package_verifier: "accepted",
    tamper_tried: 3, tamper_rejected: 3, package_verifier_tamper_rejected: 3, foreign_key: "rejected", revoked_export: "refused" });
  assert.equal(f.calls.length, 2 + 3 * 2 + 1, "both verifiers on the control, both on each of 3 flips, the export verifier on the foreign store");
  assert.ok(f.calls.some(call => call[0] === "tavonel-verify-package.mjs" && call.includes("--require-signature")));
});

test("the phase leaves no archive, tampered copy or trust store in the work directory", async () => {
  const g = fixture();
  await runPhase(exportPhase, input(g.state));
  assert.deepEqual(readdirSync(g.workDir), []);
  rmSync(g.workDir, { recursive: true, force: true });
});

test("a download that is not a 200 with bytes fails the phase and nothing after it runs", async () => {
  for (const bad of [{ status: 404, headers: {}, bytes: Buffer.from("{}") }, { status: 200, headers: {}, bytes: Buffer.alloc(0) }, { status: 200, headers: {}, bytes: "zip" }, null]) {
    const f = fixture({ state: { download: async () => bad } });
    const out = await run(f);
    assert.deepEqual({ ...out }, { outcome: "failed", package_download: "failed" });
    assert.equal(f.calls.length, 0);
  }
});

test("a package naming the previous revision, another collection, or no readable manifest fails", async () => {
  for (const [bytes, binding] of [[signedArchive({ manifestDigest: D1 }).bytes, "digest_differs"], [signedArchive({ collectionId: "col-other" }).bytes, "collection_differs"],
    [zip({ "README.md": Buffer.from("x") }), "unreadable"]]) {
    const out = await run(fixture({ state: { download: async () => ({ status: 200, headers: {}, bytes }) } }));
    assert.equal(out.package_binding, binding);
    assert.equal(out.outcome, "failed");
  }
});

test("the signature verifier or the package verifier rejecting the genuine package fails", async () => {
  const a = await run(fixture({ verifier: { "export:control": { code: 1, stderr: FAIL_LINE } } }));
  assert.deepEqual([a.signature_verifier, a.outcome], ["rejected", "failed"]);
  const b = await run(fixture({ verifier: { "package:control": { code: 1, stderr: "  ERROR   X: y\n" } } }));
  assert.deepEqual([b.package_verifier, b.outcome], ["rejected", "failed"]);
});

test("a flipped byte the signature verifier accepts fails the phase; the count is of what was rejected", async () => {
  const out = await run(fixture({ verifier: { "export:tamper": { code: 0, stderr: "" } } }));
  assert.deepEqual([out.tamper_tried, out.tamper_rejected, out.outcome], [3, 0, "failed"]);
});

test("the package verifier accepting a flipped byte is reported, not required", async () => {
  const out = await run(fixture({ verifier: { "package:tamper": { code: 0, stderr: "" } } }));
  assert.deepEqual([out.package_verifier_tamper_rejected, out.tamper_rejected, out.outcome], [0, 3, "met"]);
});

test("a package accepted against a trust store without its signer fails", async () => {
  const out = await run(fixture({ verifier: { "export:foreign": { code: 0, stderr: "" } } }));
  assert.deepEqual([out.foreign_key, out.outcome], ["accepted", "failed"]);
});

test("the foreign trust store handed to the verifier is well-formed, holds another key id and does not contain the signer", async () => {
  const { trustStoreJson, entry } = keyMaterial("signer-key");
  const foreign = JSON.parse(foreignTrustStore(trustStoreJson));
  assert.equal(foreign.schemaVersion, "tavonel.export_trust.v2");
  assert.equal(foreign.keys.length, 1);
  assert.notEqual(foreign.keys[0].keyId, "signer-key");
  assert.notEqual(foreign.keys[0].publicKeySpkiDerBase64, entry.publicKeySpkiDerBase64);
  assert.equal(foreign.keys[0].publicKeySpkiSha256, sha(Buffer.from(foreign.keys[0].publicKeySpkiDerBase64, "base64")));
});

test("the revoked actor's download: 200, wrong status, no-store missing, extra body key, leaked term/id, oversize, non-JSON all fail", async () => {
  const cases = {
    not_refused: [{ status: 200, headers: noStore, bytes: Buffer.from("PK") }, { status: 500, headers: noStore, bytes: Buffer.from("{}") }, { status: 302, headers: noStore, bytes: Buffer.alloc(0) }],
    no_store_missing: [{ status: 403, headers: { "cache-control": "private" }, bytes: Buffer.from("{}") }, { status: 403, headers: {}, bytes: Buffer.from("{}") }],
    no_store_unobservable: [{ status: 403, bytes: Buffer.from("{}") }],
    bad_body: [refusal({ code: "X", title: "t" }), refusal({ code: "X", count: 3 }), refusal({ code: "MEMBER_REVOKED", documentIds: ["a"], note: collectionIdish() }),
      refusal({ code: `no ${COLLECTION}` }), refusal({ code: `no ${WORKSPACE}` }), refusal({ code: "the zebra CLAUSE" }),
      { status: 403, headers: noStore, bytes: Buffer.alloc(64 * 1024 + 1, 0x20) }, { status: 403, headers: noStore, bytes: Buffer.from("<html>") },
      refusal({ code: 5 }), refusal({ documentIds: "a" }), { status: 403, headers: noStore, bytes: Buffer.from("[]") }],
  };
  for (const [expected, list] of Object.entries(cases)) {
    for (const reply of list) {
      const out = await run(fixture({ state: { download: async token => (token === "revoked-token" ? reply : { status: 200, headers: {}, bytes: signedArchive().bytes }) } }));
      assert.equal(out.revoked_export, expected, JSON.stringify(reply).slice(0, 80));
      assert.equal(out.outcome, "failed");
    }
  }
  function collectionIdish() { return COLLECTION; }
});

test("a clean refusal with an empty body, and one with only code and documentIds, is accepted", () => {
  assert.equal(judgeRefusal({ status: 401, headers: noStore, bytes: Buffer.alloc(0) }, ["x"]), "refused");
  assert.equal(judgeRefusal({ status: 409, headers: { "cache-control": "private, No-Store" }, bytes: Buffer.from('{"code":"A","documentIds":["d"]}') }, ["x"]), "refused");
});

test("a verifier that could not run is thrown, never recorded as a rejection", async () => {
  const boom = new Error("spawn failed");
  await assert.rejects(run(fixture({ state: { runVerifier: async () => { throw boom; } } })), error => error === boom);
  for (const odd of [{ code: 2, stderr: FAIL_LINE }, { code: 1, stderr: "" }, { code: 1, stderr: "TAVONEL export verification failed: usage: node x\n" },
    { code: null, stderr: FAIL_LINE }, { code: 1 }, null, { code: "1", stderr: FAIL_LINE }]) {
    await assert.rejects(run(fixture({ state: { runVerifier: async () => odd } })), error => error instanceof PhaseContractError && /^PHASE_VERIFIER_/.test(error.code), JSON.stringify(odd));
  }
  assert.equal(verdict("package", { code: 1, stderr: "TAVONEL package validation failed: unreadable\n" }), "rejected");
  assert.throws(() => verdict("package", { code: 1, stderr: "" }), refusedWith("PHASE_VERIFIER_OPERATIONAL"));
});

test("an error from the harness's own step or from a download is rethrown, not turned into a result", async () => {
  const failing = new Error("harness step failed");
  await assert.rejects(run(fixture(), { step: () => { throw failing; } }), error => error === failing);
  await assert.rejects(run(fixture({ state: { download: async () => { throw failing; } } })), error => error === failing);
});

test("missing or ill-typed state is refused, nothing defaulted", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "phase-export-"));
  const base = fixture().state;
  const bad = {
    ownerToken: "", collectionId: undefined, workspaceKey: 5, workDir: "", leakTerms: [], revoked: null, download: null, runVerifier: "x",
    expectedManifestDigest: "sha256:abc", previousManifestDigest: D2, trustStoreJson: "{",
  };
  for (const [key, value] of Object.entries(bad)) {
    await assert.rejects(runPhase(exportPhase, input({ ...base, [key]: value })), refusedWith("PHASE_STATE_INVALID"), key);
  }
  for (const store of [JSON.stringify({ schemaVersion: "tavonel.export_trust.v1", keys: [{}] }), JSON.stringify({ schemaVersion: "tavonel.export_trust.v2", keys: [] }), "null"]) {
    await assert.rejects(runPhase(exportPhase, input({ ...base, trustStoreJson: store })), refusedWith("PHASE_STATE_INVALID"));
  }
  rmSync(dir, { recursive: true, force: true });
});

test("a past deadline stops the phase", async () => {
  const f = fixture();
  await assert.rejects(run(f, { deadline: Date.now() + 1, step: async (_n, ms, operation) => { await new Promise(resolve => setTimeout(resolve, 5)); return operation(); } }),
    refusedWith("PHASE_DEADLINE_EXCEEDED"));
});

test("readZipEntry: hostile or malformed archives give null, never a throw or an unbounded read", () => {
  const good = zip({ "a.txt": Buffer.from("hello") });
  assert.equal(readZipEntry(good, "a.txt")?.toString(), "hello");
  assert.equal(readZipEntry(good, "missing"), null);
  assert.equal(readZipEntry(good.subarray(0, 20), "a.txt"), null);
  assert.equal(readZipEntry(Buffer.from("not a zip at all, not at all......"), "a.txt"), null);
  assert.equal(readZipEntry("string", "a.txt"), null);
  assert.equal(readZipEntry(good, "a.txt", 2), null, "declared size above the cap");
  const lying = Buffer.from(good); lying.writeUInt32LE(2, lying.indexOf(Buffer.from([0x50, 0x4b, 0x01, 0x02])) + 24);  // declares 2 bytes, inflates to 5
  assert.equal(readZipEntry(lying, "a.txt"), null);
  const farOffset = Buffer.from(good); farOffset.writeUInt32LE(0x7fffffff, farOffset.indexOf(Buffer.from([0x50, 0x4b, 0x01, 0x02])) + 42);
  assert.equal(readZipEntry(farOffset, "a.txt"), null);
  assert.equal(judgeBinding(zip({ "manifest/export-manifest.json": Buffer.from("{not json") }), D2, COLLECTION), "unreadable");
  assert.equal(judgeBinding(zip({ "manifest/export-manifest.json": Buffer.from(JSON.stringify({ manifestDigest: "x", collectionId: COLLECTION })) }), D2, COLLECTION), "unreadable");
});

// ---- real path: the shipped verifiers on a signed archive built here -----------------------------------------------------
const spawnNode = (script, args) => new Promise((resolve, reject) => {
  const child = spawn(process.execPath, [path.join(VERIFIER_DIR, script), ...args], { stdio: ["ignore", "pipe", "pipe"] });
  let stderr = ""; child.stdout.resume(); child.stderr.setEncoding("utf8").on("data", part => { stderr += part; });
  const timer = setTimeout(() => { child.kill("SIGKILL"); reject(new Error(`${script} timed out`)); }, 60_000);
  child.once("error", reject); child.once("close", code => { clearTimeout(timer); resolve({ code, stderr }); });
});

test("real verifiers: the genuine archive passes; flipped bytes, another signer and a package that is no World are rejected", { skip: !haveFoundation && "no Foundation checkout (TAVONEL_FOUNDATION_DIR)" }, async () => {
  const f = fixture({ state: { runVerifier: spawnNode } });
  f.state.download = async token => (token === "revoked-token" ? refusal() : { status: 200, headers: {}, bytes: f.archive.bytes });
  const out = await run(f);
  // The synthetic archive is signed correctly but is not a Compiled World, so the real package verifier rejects it: the phase says so.
  assert.deepEqual({ ...out }, { outcome: "failed", package_download: "ok", package_binding: "matches", signature_verifier: "accepted", package_verifier: "rejected",
    tamper_tried: 3, tamper_rejected: 3, package_verifier_tamper_rejected: 3, foreign_key: "rejected", revoked_export: "refused" });
});

test("real verifiers: with the package verifier answering for a World, the real signature half alone decides met", { skip: !haveFoundation && "no Foundation checkout (TAVONEL_FOUNDATION_DIR)" }, async () => {
  const f = fixture();
  f.state.download = async token => (token === "revoked-token" ? refusal() : { status: 200, headers: {}, bytes: f.archive.bytes });
  f.state.runVerifier = (script, args) => (script === "tavonel-verify-export.mjs" ? spawnNode(script, args) : stubVerifier().runVerifier(script, args));
  const out = await run(f);
  assert.deepEqual([out.outcome, out.signature_verifier, out.tamper_rejected, out.foreign_key, out.package_binding], ["met", "accepted", 3, "rejected", "matches"]);
});

test("real verifiers: an archive naming the previous revision verifies (it is signed) yet the binding fails the phase", { skip: !haveFoundation && "no Foundation checkout (TAVONEL_FOUNDATION_DIR)" }, async () => {
  const material = keyMaterial();
  const old = signedArchive({ manifestDigest: D1, material });
  const f = fixture({ state: { trustStoreJson: material.trustStoreJson, runVerifier: (script, args) => (script === "tavonel-verify-export.mjs" ? spawnNode(script, args) : stubVerifier().runVerifier(script, args)) } });
  f.state.download = async token => (token === "revoked-token" ? refusal() : { status: 200, headers: {}, bytes: old.bytes });
  const out = await run(f);
  assert.deepEqual([out.signature_verifier, out.package_binding, out.outcome], ["accepted", "digest_differs", "failed"]);
});
