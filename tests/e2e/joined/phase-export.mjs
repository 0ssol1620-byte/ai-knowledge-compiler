/**
 * Joined phase `export` (WO-D20-4): the active World is exported as a signed package, the shipped verifiers check it offline,
 * and the actor revoked in `revoke` is refused. Implements phase-contract.mjs; the summary is fixed enums and counts only.
 *
 *   download   The owner downloads the package. It must be a 200 with bytes within the verifiers' own size limit.
 *   signature  tavonel-verify-export.mjs with the run's trust store must exit 0. (tavonel-verify-package.mjs does not check
 *              the signature - it says so itself - so the signature rules are exercised on the export verifier.)
 *   package    tavonel-verify-package.mjs --require-signature must exit 0 on the same bytes.
 *   binding    The signed manifest inside the package (read from the bytes the verifier accepted) names the manifest digest
 *              of the revision exported and the collection exported - not the previous revision's digest.
 *   tamper     One flipped byte at each of three offsets: the export verifier must reject each (exit 1 with its own failure
 *              line). The package verifier's answer on the same bytes is reported, not required: a flip in an entry that
 *              verifier never parses is legitimately accepted by it, and the signature verifier is the authority.
 *   foreign    The same, untampered package against a well-formed trust store that holds only another key: rejected. (The
 *              package is not re-signed; the verifier's decision is "the signing key is not in the trust store".)
 *   revoked    The revoked actor's download is refused: status in {401,403,404,409}, Cache-Control no-store, body keys within
 *              {code, documentIds}, no collection id, workspace key or caller-supplied leak term anywhere in the body.
 *
 * A verifier that could not run (spawn failure, timeout, an exit code other than 0/1, no failure line on exit 1) is
 * operational: it is thrown, never recorded as a rejection.
 *
 * `state` must carry (a missing or ill-typed key throws PHASE_STATE_INVALID; nothing is defaulted):
 *   ownerToken, collectionId, workspaceKey, workDir (an existing directory the phase may write files into)
 *   expectedManifestDigest, previousManifestDigest - distinct `sha256:<64 hex>`; the revision exported and the one before it
 *   trustStoreJson - the run's export trust store (string, tavonel.export_trust.v2)
 *   leakTerms[], revoked { token }
 *   download(token) -> { status, headers (lower-case keys), bytes (Buffer) } - raw bytes: `app` parses JSON and would lose a zip
 *   runVerifier(script, args) -> { code, stderr } for script in {tavonel-verify-export.mjs, tavonel-verify-package.mjs}; it
 *     resolves for any exit code and rejects only when the process could not run
 */
import { createHash, createPublicKey, generateKeyPairSync } from "node:crypto";
import { rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { inflateRawSync } from "node:zlib";
import { COUNT, PhaseContractError, definePhase } from "./phase-contract.mjs";

export const REFUSAL_STATUSES = Object.freeze([401, 403, 404, 409]);
const ALLOWED_BODY_KEYS = Object.freeze(["code", "documentIds"]);
const ROUTE = ["refused", "not_refused", "bad_body", "no_store_missing", "no_store_unobservable"];
const VERDICT = ["accepted", "rejected"];
const STEP_MS = 120_000;
export const MAX_ARCHIVE_BYTES = 128 * 1024 * 1024;  // the shipped verifiers' own limit
const MAX_REFUSAL_BODY_BYTES = 64 * 1024;
const MAX_MANIFEST_BYTES = 8 * 1024 * 1024;
const MAX_DOCUMENT_IDS = 1000;
const MANIFEST_PATH = "manifest/export-manifest.json";
const DIGEST = /^sha256:[a-f0-9]{64}$/;
const VERIFIERS = Object.freeze({ export: "tavonel-verify-export.mjs", package: "tavonel-verify-package.mjs" });
const FAILURE_LINE = "TAVONEL export verification failed:";

const invalid = key => { throw new PhaseContractError("PHASE_STATE_INVALID", key); };
const text = (value, key) => (typeof value === "string" && value.length > 0 ? value : invalid(key));
const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);
const digest = value => (typeof value === "string" && DIGEST.test(value) ? value : null);

function readState(state) {
  const revoked = isObject(state.revoked) ? state.revoked : invalid("revoked");
  if (!Array.isArray(state.leakTerms) || state.leakTerms.length === 0) invalid("leakTerms");
  if (typeof state.download !== "function") invalid("download");
  if (typeof state.runVerifier !== "function") invalid("runVerifier");
  const expected = digest(state.expectedManifestDigest) ?? invalid("expectedManifestDigest");
  const previous = digest(state.previousManifestDigest) ?? invalid("previousManifestDigest");
  if (expected === previous) invalid("previousManifestDigest");  // a package of the previous revision would pass the binding check
  let trust;
  try { trust = JSON.parse(text(state.trustStoreJson, "trustStoreJson")); } catch { invalid("trustStoreJson"); }
  if (!isObject(trust) || trust.schemaVersion !== "tavonel.export_trust.v2" || !Array.isArray(trust.keys) || trust.keys.length === 0) invalid("trustStoreJson");
  return {
    ownerToken: text(state.ownerToken, "ownerToken"), collectionId: text(state.collectionId, "collectionId"),
    workspaceKey: text(state.workspaceKey, "workspaceKey"), workDir: text(state.workDir, "workDir"),
    leakTerms: state.leakTerms.map((term, index) => text(term, `leakTerms.${index}`)),
    expected, previous, trustStoreJson: state.trustStoreJson, revokedToken: text(revoked.token, "revoked.token"),
    download: state.download, runVerifier: state.runVerifier,
  };
}

/** One entry of a zip, read through the central directory with every size bounded; null when absent or malformed. */
export function readZipEntry(bytes, wanted, maxBytes = MAX_MANIFEST_BYTES) {
  try {
    if (!Buffer.isBuffer(bytes) || bytes.length < 22 || bytes.length > MAX_ARCHIVE_BYTES) return null;
    let eocd = -1;
    for (let at = bytes.length - 22; at >= Math.max(0, bytes.length - 65_557); at -= 1) if (bytes.readUInt32LE(at) === 0x06054b50) { eocd = at; break; }
    if (eocd < 0) return null;
    let at = bytes.readUInt32LE(eocd + 16);
    for (let index = 0; index < bytes.readUInt16LE(eocd + 10); index += 1) {
      if (bytes.readUInt32LE(at) !== 0x02014b50) return null;
      const method = bytes.readUInt16LE(at + 10), packed = bytes.readUInt32LE(at + 20), size = bytes.readUInt32LE(at + 24);
      const nameLength = bytes.readUInt16LE(at + 28), skip = nameLength + bytes.readUInt16LE(at + 30) + bytes.readUInt16LE(at + 32);
      const local = bytes.readUInt32LE(at + 42);
      if (bytes.toString("utf8", at + 46, at + 46 + nameLength) === wanted) {
        if (size > maxBytes || bytes.readUInt32LE(local) !== 0x04034b50) return null;
        const start = local + 30 + bytes.readUInt16LE(local + 26) + bytes.readUInt16LE(local + 28);
        if (start + packed > bytes.length) return null;
        const raw = bytes.subarray(start, start + packed);
        const out = method === 0 ? raw : method === 8 ? inflateRawSync(raw, { maxOutputLength: Math.max(1, size) }) : null;
        return out !== null && out.length === size ? Buffer.from(out) : null;
      }
      at += 46 + skip;
    }
    return null;
  } catch { return null; }
}

/** What the signed manifest in the package names: "matches", "digest_differs", "collection_differs" or "unreadable". Pure. */
export function judgeBinding(bytes, expectedDigest, collectionId) {
  const raw = readZipEntry(bytes, MANIFEST_PATH);
  let manifest = null;
  try { manifest = raw === null ? null : JSON.parse(raw.toString("utf8")); } catch { /* unreadable */ }
  if (!isObject(manifest) || digest(manifest.manifestDigest) === null || typeof manifest.collectionId !== "string") return "unreadable";
  if (manifest.manifestDigest !== expectedDigest) return "digest_differs";
  return manifest.collectionId === collectionId ? "matches" : "collection_differs";
}

/** Why a refusal is not clean, or "refused". Pure; the WO-D15-3 rule set, applied to the download route. */
export function judgeRefusal(result, probes) {
  if (!isObject(result) || !REFUSAL_STATUSES.includes(result.status)) return "not_refused";
  if (!isObject(result.headers)) return "no_store_unobservable";
  const cache = result.headers["cache-control"];
  if (typeof cache !== "string" || !cache.toLowerCase().split(",").map(part => part.trim()).includes("no-store")) return "no_store_missing";
  if (!Buffer.isBuffer(result.bytes) || result.bytes.length > MAX_REFUSAL_BODY_BYTES) return "bad_body";
  const raw = result.bytes.toString("utf8");
  if (raw.length > 0) {
    let body;
    try { body = JSON.parse(raw); } catch { return "bad_body"; }
    if (!isObject(body) || Object.keys(body).some(key => !ALLOWED_BODY_KEYS.includes(key))) return "bad_body";
    if (Object.hasOwn(body, "code") && typeof body.code !== "string") return "bad_body";
    if (Object.hasOwn(body, "documentIds") && !(Array.isArray(body.documentIds) && body.documentIds.length <= MAX_DOCUMENT_IDS
      && body.documentIds.every(id => typeof id === "string"))) return "bad_body";
  }
  return probes.some(probe => raw.toLowerCase().includes(probe.toLowerCase())) ? "bad_body" : "refused";
}

/** A trust store that is well-formed and holds one other key: the same package no longer has its signer in it. */
export function foreignTrustStore(trustStoreJson) {
  const real = JSON.parse(trustStoreJson);
  const spki = createPublicKey(generateKeyPairSync("ed25519").privateKey).export({ format: "der", type: "spki" });
  const [template] = real.keys;
  const keyId = `foreign-${createHash("sha256").update(spki).digest("hex").slice(0, 8)}`;
  return JSON.stringify({
    ...real, activeKeyId: keyId,
    keys: [{ ...template, keyId, keyVersion: 1, status: "active", publicKeySpkiDerBase64: spki.toString("base64"),
      publicKeySpkiSha256: `sha256:${createHash("sha256").update(spki).digest("hex")}` }],
  });
}

/** `accepted` on exit 0, `rejected` on exit 1 with the verifier's own failure output; anything else could not judge: thrown. */
export function verdict(kind, outcome) {
  if (!isObject(outcome) || !Number.isInteger(outcome.code) || typeof outcome.stderr !== "string") throw new PhaseContractError("PHASE_VERIFIER_RESULT_INVALID", kind);
  if (outcome.code === 0) return "accepted";
  const ownFailure = kind === "export" ? outcome.stderr.startsWith(FAILURE_LINE) && !outcome.stderr.includes("usage:")
    : outcome.stderr.includes("ERROR   ") || outcome.stderr.startsWith("TAVONEL package validation failed:");
  if (outcome.code === 1 && ownFailure) return "rejected";
  throw new PhaseContractError("PHASE_VERIFIER_OPERATIONAL", kind);
}

export const exportPhase = definePhase({
  name: "export",
  fields: {
    package_download: ["ok", "failed"],
    package_binding: ["matches", "digest_differs", "collection_differs", "unreadable"],
    signature_verifier: VERDICT, package_verifier: VERDICT,
    tamper_tried: COUNT, tamper_rejected: COUNT, package_verifier_tamper_rejected: COUNT,
    foreign_key: VERDICT, revoked_export: ROUTE,
  },
  async run({ hop, step, state, deadline }) {
    const s = readState(state);
    const probes = [s.collectionId, s.workspaceKey, ...s.leakTerms];
    const within = () => { const left = deadline - Date.now(); if (left <= 0) throw new PhaseContractError("PHASE_DEADLINE_EXCEEDED", "export"); return Math.min(STEP_MS, left); };
    const run = (name, operation) => step(name, within(), operation);
    const file = name => path.join(s.workDir, `joined-export-${name}`);
    const verify = (kind, archive, trust) => run(`verify-${kind}`, async () => verdict(kind, await s.runVerifier(VERIFIERS[kind],
      kind === "export" ? ["--archive", archive, "--trust-store", trust] : ["--package", archive, "--require-signature"])));
    const written = [];
    const put = (name, body) => { const target = file(name); written.push(target); writeFileSync(target, body); return target; };
    const result = { outcome: "failed" };
    hop("export");
    try {
      const got = await run("download", () => s.download(s.ownerToken));
      const ok = isObject(got) && got.status === 200 && Buffer.isBuffer(got.bytes) && got.bytes.length > 0 && got.bytes.length <= MAX_ARCHIVE_BYTES;
      result.package_download = ok ? "ok" : "failed";
      if (!ok) return result;
      const archive = put("control.zip", got.bytes), trust = put("trust.json", s.trustStoreJson);

      result.signature_verifier = await verify("export", archive, trust);
      result.package_verifier = await verify("package", archive, trust);
      result.package_binding = judgeBinding(got.bytes, s.expected, s.collectionId);

      result.tamper_tried = 0; result.tamper_rejected = 0; result.package_verifier_tamper_rejected = 0;
      for (const fraction of [0.25, 0.5, 0.75]) {
        const flipped = Buffer.from(got.bytes);
        flipped[Math.floor(flipped.length * fraction)] ^= 0xff;
        const target = put(`tamper-${result.tamper_tried}.zip`, flipped);
        result.tamper_tried += 1;
        if (await verify("export", target, trust) === "rejected") result.tamper_rejected += 1;
        if (await verify("package", target, trust) === "rejected") result.package_verifier_tamper_rejected += 1;
      }

      result.foreign_key = await verify("export", archive, put("foreign-trust.json", foreignTrustStore(s.trustStoreJson)));

      result.revoked_export = await run("revoked-download", async () => judgeRefusal(await s.download(s.revokedToken), probes));

      const good = result.signature_verifier === "accepted" && result.package_verifier === "accepted" && result.package_binding === "matches"
        && result.tamper_rejected === result.tamper_tried && result.foreign_key === "rejected" && result.revoked_export === "refused";
      result.outcome = good ? "met" : "failed";
      return result;
    } finally {
      for (const target of written) rmSync(target, { force: true });
    }
  },
});
