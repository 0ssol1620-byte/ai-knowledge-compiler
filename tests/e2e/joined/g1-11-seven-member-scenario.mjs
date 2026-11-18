/**
 * G1-11 seven-member scenario, connected to the joined end-to-end harness (joined-e2e.mjs) as an optional hop after the
 * original eleven proofs and their failure cases. It drives the harness's own primitives (app, signedPut, deliver, driveJob,
 * listKeys, bucket.get, reservation, verifyCompileReceipt) and Foundation's own intake and compile-authority functions, all
 * passed in by the caller. It reimplements no policy, supplies no response default and invents no identity: every document
 * id, version key, job id and decision below is one a real route, object or function returned.
 *
 * Nothing here runs unless the harness was given TAVONEL_JOINED_G1_11_MANIFEST. With it, an explicit positive
 * TAVONEL_JOINED_G1_11_MAX_CREDITS cap, the run id and both checkout SHAs are required before the manifest is opened, and the
 * manifest's pinned SHA-256 is checked before any callback. Only the members in G1_11_LEGACY_SELECTION (selection intent,
 * never an outcome) are approved, transferred and processed, and only while the quoted maximum fits the cap.
 *
 * The report is structural: codes, statuses, counts, identities and digests. It never holds a token, a capability URL, a
 * plaintext principal or free text. Its verdict is PARTIAL whenever any member lacks an actual observation; the harness
 * turns that into a failed run once the report and the producer sidecar are on disk.
 */
import { createHash } from "node:crypto";
import { closeSync, fstatSync, lstatSync, openSync, readSync, realpathSync } from "node:fs";
import path from "node:path";

/** Where the corrected G1-11 runtime producer is materialized, relative to this directory. Imported only on request. */
export const G1_11_PRODUCER_MODULE = "./g1-11-runtime-producer.mjs";
export const G1_11_RUNTIME_EVIDENCE_KIND = "RUNTIME_RECEIPT";
export const G1_11_MANIFEST_SHA256 = "cb55390d92dacbb236a057416d88140c7ef1e470147bef262375875ebeba9c68";
export const G1_11_MANIFEST_SCHEMA = "tavonel.g1-11.synthetic-fixtures.v1";
export const G1_11_MEMBER_IDS = Object.freeze(["normal", "unsupported", "denied", "duplicate", "unknown", "failed", "excluded"]);
export const G1_11_TOTAL_FIXTURE_BYTES = 4031;
/** Selection intent only: the members explicitly selected for authorized legacy processing. Not an expected outcome. */
export const G1_11_LEGACY_SELECTION = Object.freeze(["normal", "failed"]);
/** The only verdict the harness accepts. Every member observed, nothing missing; still no qualification or admission claim. */
export const G1_11_COMPLETE_VERDICT = "OBSERVED_WITHOUT_GAPS";

/**
 * Why a member is not processed, from the fixture mapping and the current product state, never from an expected result:
 * the unsupported member's qualification is not observed here, the denied member has no second principal or document ACL in
 * the existing fixture, and the triage route answers disabled before any pending or excluded receipt can exist.
 */
const NOT_SELECTED_REASON = Object.freeze({
  unsupported: "UNSUPPORTED_QUALIFICATION_NOT_OBSERVED",
  denied: "AUTHORITY_PRINCIPAL_UNMAPPED_IN_FIXTURE",
  duplicate: "TRIAGE_DISABLED_NO_SERVER_DISPOSITION",
  unknown: "TRIAGE_DISABLED_NO_SERVER_DISPOSITION",
  excluded: "TRIAGE_DISABLED_NO_SERVER_DISPOSITION",
});
/** The browser's own claim for a selected file when the manifest declares none. The harness's signedPut signs only PDF. */
const DECLARED_MIME_BY_EXTENSION = Object.freeze({ ".pdf": "application/pdf" });
const SIGNED_PUT_MIME_TYPE = "application/pdf";
const TRIAGE_DIAGNOSTIC_ROUTE = "/api/v1/uploads/triage/receipt";
const MANIFEST_MAX_BYTES = 64 * 1024;
const RECEIPT_MAX_BYTES = 16 * 1024;
const SANITIZED_MAX_BYTES = 18 * 1024 * 1024;
const OCR_MAX_BYTES = 8 * 1024 * 1024;
const CANDIDATE_MAX_BYTES = 32 * 1024 * 1024;

const CODE = /^[A-Z][A-Z0-9_]{0,63}$/;
const ERROR_NAME = /^[A-Z][A-Za-z]{0,39}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DIGEST = /^sha256:[a-f0-9]{64}$/;
const DIGEST_OR_HEX = /^(?:sha256:)?[a-f0-9]{64}$/;
const HEX64 = /^[a-f0-9]{64}$/;
const HEX40 = /^[a-f0-9]{40}$/;
const FILE_KEY = /^fk_[a-f0-9]{40}$/;
const JOB_ID = /^cjob-[a-f0-9]{32}$/;
const COLLECTION_ID = /^[A-Za-z0-9_-]{1,128}$/;
const RUN_ID = /^[A-Za-z0-9._:-]{1,512}$/;
const WORKSPACE_KEY = /^[A-Za-z0-9_-]{1,128}$/;
const LABEL = /^[A-Za-z0-9_.:-]{1,128}$/;
const STATE = /^[a-z_]{1,32}$/;
const MIME = /^[a-z]+\/[a-z0-9.+-]{1,100}$/;
const TIMESTAMP = /^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:.]{5,20}(?:Z|[+-][0-9]{2}(?::?[0-9]{2})?)?$/;

const only = (pattern, value) => (value == null ? null : typeof value === "string" && pattern.test(value) ? value : "[withheld]");
const statusOf = value => (Number.isInteger(value) ? value : null);
const countOf = value => (Number.isSafeInteger(value) && value >= 0 ? value : null);
const sha256Hex = bytes => createHash("sha256").update(bytes).digest("hex");
const errorShape = error => ({ name: only(ERROR_NAME, String(error?.name ?? "Error")), code: typeof error?.code === "string" ? only(CODE, error.code) : null });
const samePath = (left, right) => (process.platform === "win32" ? left.toLowerCase() === right.toLowerCase() : left === right);

export class SevenMemberScenarioError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "SevenMemberScenarioError";
    this.code = code;
  }
}
const refuse = (code, message) => new SevenMemberScenarioError(code, message);

/**
 * The explicit request, or null. No manifest means no scenario: nothing is imported, called or written. A manifest without
 * an explicit positive integer credit cap or the run id is refused, never defaulted; the cap is an operator input for this
 * synthetic, non-paid fixture run, not a setting or a grant, and nothing derives it from the fixtures.
 */
export function readG1_11Request(env) {
  const manifestPath = env.TAVONEL_JOINED_G1_11_MANIFEST;
  if (manifestPath === undefined || manifestPath === "") return null;
  if (!path.isAbsolute(manifestPath)) throw refuse("G1_11_MANIFEST_PATH_NOT_ABSOLUTE", "TAVONEL_JOINED_G1_11_MANIFEST must be an absolute path");
  const cap = env.TAVONEL_JOINED_G1_11_MAX_CREDITS;
  if (typeof cap !== "string" || !/^[1-9][0-9]{0,8}$/.test(cap)) {
    throw refuse("G1_11_MAX_CREDITS_REQUIRED", "TAVONEL_JOINED_G1_11_MAX_CREDITS must be an explicit positive integer credit cap");
  }
  const runId = env.GITHUB_RUN_ID;
  if (typeof runId !== "string" || !RUN_ID.test(runId)) throw refuse("G1_11_RUN_ID_REQUIRED", "the G1-11 scenario needs the actual GITHUB_RUN_ID");
  return Object.freeze({ manifestPath, maxCredits: Number(cap), runId });
}

/** Reads at most `limit` bytes; a file that is, or grows, larger is refused rather than truncated. */
function readBoundedFile(file, limit) {
  const fd = openSync(file, "r");
  try {
    if (fstatSync(fd).size > limit) throw refuse("G1_11_FILE_OVER_BOUND", "a G1-11 input exceeds its byte bound");
    const buffer = Buffer.alloc(limit + 1);
    let length = 0, read;
    while (length < buffer.length && (read = readSync(fd, buffer, length, buffer.length - length, null)) > 0) length += read;
    if (length > limit) throw refuse("G1_11_FILE_OVER_BOUND", "a G1-11 input exceeds its byte bound");
    return buffer.subarray(0, length);
  } finally {
    closeSync(fd);
  }
}

function relativeSegments(relative) {
  if (typeof relative !== "string" || relative.length < 1 || relative.length > 1024 || relative.includes("\\") || relative.includes(":")
    || relative.includes("\0") || path.posix.isAbsolute(relative) || path.win32.isAbsolute(relative)) {
    throw refuse("G1_11_FIXTURE_PATH_REJECTED", "a fixture path is not a plain relative path");
  }
  const segments = relative.split("/");
  if (segments.some(segment => segment === "" || segment === "." || segment === "..")) throw refuse("G1_11_FIXTURE_PATH_REJECTED", "a fixture path traverses");
  return segments;
}

/**
 * Owner-side verification of one fixture: plain relative path, no link or reparse point on the way, exact size, exact digest.
 * Hashing a member's bytes here is the fixture owner checking its own input; it is not a read by that member's principal.
 * Keys whose name starts with "expected" are never read: they are left out of the producer's owner labels by name alone.
 */
function verifyFixtureMember(base, entry) {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) throw refuse("G1_11_MANIFEST_SHAPE", "a manifest member is not an object");
  const { id, relative_path: relative, sha256, byte_length: bytes, acl_scope: aclScope } = entry;
  if (!G1_11_MEMBER_IDS.includes(id)) throw refuse("G1_11_MANIFEST_MEMBER_ID", "a manifest member id is not one of the seven");
  if (typeof aclScope !== "string" || !LABEL.test(aclScope)) throw refuse("G1_11_MANIFEST_ACL_SCOPE", "a manifest member has no structural acl_scope");
  if (typeof sha256 !== "string" || !DIGEST_OR_HEX.test(sha256) || !Number.isSafeInteger(bytes) || bytes < 1 || bytes > G1_11_TOTAL_FIXTURE_BYTES) {
    throw refuse("G1_11_MANIFEST_SHAPE", "a manifest member has no exact digest or byte count");
  }
  const segments = relativeSegments(relative);
  let cursor = base;
  for (const segment of segments) {
    cursor = path.join(cursor, segment);
    if (lstatSync(cursor).isSymbolicLink()) throw refuse("G1_11_FIXTURE_LINK_REJECTED", "a fixture path crosses a link");
  }
  const stat = lstatSync(cursor);
  if (!stat.isFile() || stat.size !== bytes) throw refuse("G1_11_FIXTURE_SIZE_MISMATCH", "a fixture is not a regular file of its declared size");
  if (!samePath(realpathSync.native(cursor), cursor)) throw refuse("G1_11_FIXTURE_REPARSE_REJECTED", "a fixture resolves elsewhere");
  const content = readBoundedFile(cursor, bytes);
  const digest = sha256.replace(/^sha256:/, "");
  if (content.length !== bytes || sha256Hex(content) !== digest) throw refuse("G1_11_FIXTURE_HASH_MISMATCH", "a fixture's bytes do not match its digest");
  const filename = segments.at(-1);
  const declared = typeof entry.declared_mime_type === "string" && MIME.test(entry.declared_mime_type) ? entry.declared_mime_type : null;
  // Whitelist labels; do not traverse an expected block or provenance free text.
  const ownerLabels = { id, source_id: entry.source_id, source_version: entry.source_version, source_sha256: digest, acl_scope: aclScope };
  return Object.freeze({ id, filename, bytes, sha256Hex: digest, aclScope, content,
    mimeType: declared ?? DECLARED_MIME_BY_EXTENSION[path.extname(filename).toLowerCase()] ?? null, ownerLabels: Object.freeze(ownerLabels) });
}

/** The pinned seven-member manifest. Its SHA-256 is checked on the bytes read, before they are parsed or anything is called. */
export function loadPinnedManifest(manifestPath) {
  if (typeof manifestPath !== "string" || !path.isAbsolute(manifestPath)) throw refuse("G1_11_MANIFEST_PATH_NOT_ABSOLUTE", "the manifest path must be absolute");
  const base = realpathSync.native(path.dirname(path.resolve(manifestPath)));
  const file = path.join(base, path.basename(manifestPath));
  const stat = lstatSync(file);
  if (stat.isSymbolicLink() || !stat.isFile()) throw refuse("G1_11_MANIFEST_NOT_REGULAR_FILE", "the manifest is not a regular file");
  const bytes = readBoundedFile(file, MANIFEST_MAX_BYTES);
  const manifestSha256 = sha256Hex(bytes);
  if (manifestSha256 !== G1_11_MANIFEST_SHA256) throw refuse("G1_11_MANIFEST_HASH_MISMATCH", "the manifest is not the pinned seven-member manifest");
  let parsed;
  try { parsed = JSON.parse(bytes.toString("utf8")); } catch { throw refuse("G1_11_MANIFEST_UNPARSEABLE", "the pinned manifest does not parse"); }
  if (parsed?.schema !== G1_11_MANIFEST_SCHEMA || parsed.purpose !== "OFFLINE_SYNTHETIC_FIXTURE_ONLY" || parsed.runtime_status !== "NOT_RUN"
    || !Array.isArray(parsed.files) || parsed.files.length !== G1_11_MEMBER_IDS.length) {
    throw refuse("G1_11_MANIFEST_SHAPE", "the manifest is not the task-owned synthetic fixture manifest");
  }
  const members = parsed.files.map(entry => verifyFixtureMember(base, entry));
  if (new Set(members.map(member => member.id)).size !== G1_11_MEMBER_IDS.length) throw refuse("G1_11_MANIFEST_MEMBER_ID", "a member id repeats");
  if (members.reduce((sum, member) => sum + member.bytes, 0) !== G1_11_TOTAL_FIXTURE_BYTES) throw refuse("G1_11_MANIFEST_SHAPE", "the fixtures do not total the pinned byte count");
  return Object.freeze({ manifestSha256, members: Object.freeze(members) });
}

/** `state|credits|reason|settled_at` from the harness's reservation(); zero, released and reserved stay distinct, never a charge. */
export function parseReservationRow(text) {
  if (typeof text !== "string" || text === "") return null;
  const fields = text.split("|");
  if (fields.length !== 4) return { parsed: false };
  const [state, credits, reason, settledAt] = fields;
  return { parsed: true, state: only(STATE, state),
    settledCredits: credits === "-" ? null : /^(?:0|[1-9][0-9]{0,9})$/.test(credits) ? Number(credits) : "[withheld]",
    reasonCode: reason === "-" ? null : only(/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/, reason),
    settledAt: settledAt === "-" ? null : only(TIMESTAMP, settledAt) };
}

/** The report the harness observes by reference, so every checkpoint (step end, failure, signal) carries what is known so far. */
export function newSevenMemberReport() {
  return {
    kind: "tavonel.g1-11.joined-seven-member.v1", state: "NOT_STARTED", verdict: "NOT_RUN",
    claims: { customerQualified: "NOT_CLAIMED", runtimeAdmission: "NOT_CLAIMED", perFileEffectMonitor: "ABSENT_IN_HARNESS", negativeEffects: "NOT_OBSERVED" },
    executionBinding: null, manifest: null, selectionIntent: null, budget: null, triageDiagnostic: null,
    members: {}, gaps: [], errors: [],
    producer: { module: G1_11_PRODUCER_MODULE, created: false, calls: [], output: null },
  };
}

const REQUIRED_DEPS = Object.freeze(["app", "signedPut", "deliver", "driveJob", "jobRow", "listKeys", "getObject", "reservation", "verifyCompileReceipt",
  "deriveFileKey", "intakeManifestDigest", "newAttemptKey", "approvedSourceIdempotencyKey", "quoteIntakeManifest", "intakePricingFingerprint",
  "authorizeCompileJobSourceAccess", "ocrCallsFor", "writeSidecar", "checkpointReport"]);

function executionBindingOf(execution) {
  if (!RUN_ID.test(String(execution?.runId ?? "")) || !HEX40.test(String(execution?.coreSha ?? "")) || !HEX40.test(String(execution?.foundationSha ?? ""))) {
    throw refuse("G1_11_EXECUTION_BINDING_REQUIRED", "the actual run id, Core SHA and Foundation SHA are required");
  }
  return Object.freeze({ run_id: execution.runId, foundation_commit: execution.foundationSha, core_commit: execution.coreSha });
}

/** Default off, including lazy imports and callbacks. Invalid requests cannot start product work. */
export async function runOptionalSevenMemberScenario({ env, ...options }) {
  const request = readG1_11Request(env);
  if (!request) return null;
  return runSevenMemberScenario({ ...options, request });
}

/**
 * Actual route/function/object observations only. Owner labels assert a mapping and grant no access.
 * The durable-job RPC derives its actor from immutable rows; this hook does not authenticate that
 * actor independently. Missing decisions stop all worker/cron work; an UNAVAILABLE reply is no denial.
 * A selected pair cannot observe seven dispositions or false effects: PARTIAL is a failed optional hop.
 */
export async function runSevenMemberScenario({ report, request, evidenceKind, createRuntimeProducer, execution, fixture, deps }) {
  if (!report || !Array.isArray(report.gaps)) throw refuse("G1_11_REPORT_REQUIRED", "a structural report is required");
  const gap = (member, code) => { if (!report.gaps.some(row => row.member === member && row.gap === code)) report.gaps.push({ member, gap: code }); };
  report.state = "VALIDATING";
  try {
    if (!Number.isSafeInteger(request?.maxCredits) || request.maxCredits < 1) throw refuse("G1_11_MAX_CREDITS_REQUIRED", "an explicit positive cap is required");
    if (!["RUNTIME_RECEIPT", "SYNTHETIC_CONTRACT_TEST"].includes(evidenceKind)) throw refuse("G1_11_EVIDENCE_KIND_REQUIRED", "use a producer evidence kind");
    if (typeof createRuntimeProducer !== "function") throw refuse("G1_11_PRODUCER_REQUIRED", "the corrected producer is required");
    if (!UUID.test(String(fixture?.owner ?? "")) || !WORKSPACE_KEY.test(String(fixture?.workspace ?? "")) || typeof fixture?.token !== "string" || fixture.token.length < 16) {
      throw refuse("G1_11_FIXTURE_CONTEXT_REQUIRED", "the existing authenticated owner, workspace and session are required");
    }
    if (REQUIRED_DEPS.some(key => typeof deps?.[key] !== "function") || !deps.trust || typeof deps.trust !== "object") {
      throw refuse("G1_11_HARNESS_DEPS_REQUIRED", "a real harness primitive is missing");
    }
    report.executionBinding = executionBindingOf(execution);
    if (request.runId !== execution.runId) throw refuse("G1_11_RUN_BINDING_MISMATCH", "the request and execution run must match");
  } catch (error) {
    report.state = "REFUSED";
    report.errors.push(errorShape(error));
    if (typeof deps?.checkpointReport === "function") await deps.checkpointReport(report);
    throw error;
  }
  const { owner, workspace, token } = fixture;
  const principalRefSha256 = sha256Hex(owner);
  let producer;
  const finalize = async () => {
    report.state = "PRODUCING";
    if (producer) {
      try {
        const output = producer.produce();
        // Only bounded, structural observations were supplied to this producer. Never serialize raw route replies.
        const serialized = JSON.stringify(output);
        report.producer.output = { pairSerializationSha256: sha256Hex(serialized), sidecarSha256: await deps.writeSidecar(serialized),
          structuralStatus: output.runtimeResults.execution.status };
        if (output.runtimeResults.execution.status !== "COMPLETED") gap(null, "PRODUCER_STRUCTURALLY_INCOMPLETE");
      } catch (error) {
        report.producer.produceError = errorShape(error);
        gap(null, "PRODUCER_OUTPUT_NOT_PERSISTED");
      }
    }
    report.verdict = report.gaps.length === 0 ? G1_11_COMPLETE_VERDICT : "PARTIAL";
    report.state = "DONE";
    await deps.checkpointReport(report);
    return report;
  };
  const record = (method, member, payload) => {
    const call = { method, member, outcome: "pending" };
    report.producer.calls.push(call);
    try { producer[method](payload); call.outcome = "returned"; return true; }
    catch (error) { call.outcome = "rejected"; call.error = errorShape(error); gap(member, "PRODUCER_REJECTED_OBSERVATION"); return false; }
  };
  const routeSummary = reply => ({ status: statusOf(reply?.status), code: only(CODE, reply?.body?.code ?? null) });
  const readObject = async (key, limit) => {
    const object = await deps.getObject(key);
    if (!object) return null;
    if (!Number.isSafeInteger(object.size) || object.size < 0 || object.size > limit) throw refuse("G1_11_OBJECT_OVER_BOUND", "stored object exceeds its bound");
    const bytes = Buffer.from(await object.arrayBuffer());
    if (bytes.length !== object.size) throw refuse("G1_11_OBJECT_LENGTH_MISMATCH", "stored object length differs");
    return bytes;
  };
  const readJson = async (key, limit) => {
    const bytes = await readObject(key, limit);
    if (!bytes) return { present: false, value: null };
    try { return { present: true, value: JSON.parse(bytes.toString("utf8")) }; }
    catch { return { present: true, value: null }; }
  };
  let manifest;
  try {
    manifest = loadPinnedManifest(request.manifestPath);
    report.manifest = { sha256: manifest.manifestSha256, schema: G1_11_MANIFEST_SCHEMA,
      verification: "OWNER_SIDE_PATH_LINK_SIZE_DIGEST", handleRace: "NOT_CLAIMED", expectedFields: "NOT_READ",
      members: manifest.members.map(member => ({ id: member.id, bytes: member.bytes, sha256: member.sha256Hex })) };
    report.selectionIntent = { legacyProcessing: [...G1_11_LEGACY_SELECTION], basis: "EXPLICIT_TASK_SELECTION_NOT_OUTCOME" };
    producer = createRuntimeProducer({ evidence_kind: evidenceKind, execution_binding: report.executionBinding,
      members: manifest.members.map(member => ({ ...member.ownerLabels, authority_binding: G1_11_LEGACY_SELECTION.includes(member.id)
        ? { principal_ref_sha256: principalRefSha256, workspace_key: workspace, acl_scope: member.aclScope } : null })) });
    report.producer.created = true;
    for (const member of manifest.members) {
      const selected = G1_11_LEGACY_SELECTION.includes(member.id);
      report.members[member.id] = { id: member.id, aclScope: member.aclScope, selected,
        authorityBinding: selected ? "OWNER_CONTEXT_MAPPING_ASSERTION_NOT_GRANT" : null,
        notProcessedReason: selected ? null : NOT_SELECTED_REASON[member.id], accessDecision: null };
      if (!selected) gap(member.id, NOT_SELECTED_REASON[member.id]);
      gap(member.id, "PER_FILE_COMPLETE_EFFECT_MONITOR_ABSENT");
    }
    report.state = "QUOTING";
    const pricingFingerprint = await deps.intakePricingFingerprint();
    if (!DIGEST.test(pricingFingerprint)) throw refuse("G1_11_PRICING_FINGERPRINT_INVALID", "real pricing fingerprint is unavailable");
    const plans = [];
    for (const id of G1_11_LEGACY_SELECTION) {
      const member = manifest.members.find(member => member.id === id);
      const contentSha256 = `sha256:${member.sha256Hex}`;
      const fileKey = await deps.deriveFileKey({ relativePath: member.filename, contentSha256, byteLength: member.bytes, mimeType: member.mimeType });
      const files = [{ fileKey, originalFilename: member.filename, contentSha256, byteLength: member.bytes, mimeType: member.mimeType, claimedPages: null, claimedBasis: null }];
      const clientManifestDigest = await deps.intakeManifestDigest(files);
      const quoted = deps.quoteIntakeManifest(files.map(file => ({ bytes: file.byteLength, mimeType: file.mimeType, claimedPages: null, claimedBasis: null })));
      const quote = quoted?.quote;
      report.members[id].quote = { fileKey: only(FILE_KEY, fileKey), clientManifestDigest: only(DIGEST, clientManifestDigest),
        pricingFingerprint, ok: quoted?.ok === true, code: only(CODE, quoted?.code ?? null), maximumCredits: countOf(quote?.maximumCredits) };
      if (!FILE_KEY.test(fileKey) || !DIGEST.test(clientManifestDigest) || quoted?.ok !== true || countOf(quote?.maximumCredits) === null) {
        gap(id, "QUOTE_UNAVAILABLE");
        return finalize();
      }
      plans.push({ member, fileKey, files, clientManifestDigest, contentSha256, quoted });
    }
    const quotedMaximumCredits = plans.reduce((sum, plan) => sum + plan.quoted.quote.maximumCredits, 0);
    report.budget = { capCredits: request.maxCredits, quotedMaximumCredits, withinCap: Number.isSafeInteger(quotedMaximumCredits) && quotedMaximumCredits <= request.maxCredits,
      plannedMembers: plans.map(plan => plan.member.id), approvedMaximumCredits: 0 };
    if (!report.budget.withinCap) { gap(null, "QUOTED_MAXIMUM_EXCEEDS_EXPLICIT_CAP"); return finalize(); }
    // Disabled triage is availability evidence only. No server disposition or qualification is inferred.
    try { report.triageDiagnostic = { ...routeSummary(await deps.app(TRIAGE_DIAGNOSTIC_ROUTE, token, {})), use: "DIAGNOSTIC_ONLY_NOT_A_DISPOSITION" }; }
    catch (error) { report.triageDiagnostic = { error: errorShape(error), use: "DIAGNOSTIC_ONLY_NOT_A_DISPOSITION" }; }
    report.state = "PROCESSING";
    for (const [index, plan] of plans.entries()) {
      if (await processMember(plan, pricingFingerprint) === "halt") {
        for (const rest of plans.slice(index + 1)) { report.members[rest.member.id].stopped = "NOT_PROCESSED_AFTER_HALT"; gap(rest.member.id, "NOT_PROCESSED_AFTER_HALT"); }
        break;
      }
    }
  } catch (error) {
    report.errors.push(errorShape(error));
    gap(null, "SCENARIO_SOURCE_OR_CALLBACK_ERROR");
  }
  return finalize();

  async function processMember(plan, pricingFingerprint) {
    const { member, fileKey, files, clientManifestDigest, contentSha256, quoted } = plan;
    const id = member.id, entry = report.members[id];
    const context = Object.freeze({ principalRef: owner, workspaceKey: workspace, aclScope: member.aclScope });
    const observe = (method, payload) => record(method, id, { context, ...payload });
    const held = { attemptKey: null, scopeDigest: null, documentId: null, cancelled: false };
    const readSettlement = async () => {
      const row = parseReservationRow(await deps.reservation(held.documentId));
      entry.settlement = row ?? { parsed: false };
      if (!row?.parsed || row.state === "[withheld]" || row.settledCredits === "[withheld]" || row.reasonCode === "[withheld]" || row.settledAt === "[withheld]") {
        gap(id, "SETTLEMENT_ROW_UNAVAILABLE"); return;
      }
      if (entry.mapping) observe("recordSettlement", { documentId: held.documentId, ...row });
      // Never manufacture a false charge from reserved/released/zero or absence.
      if (row.state !== "settled" || row.settledAt === null) gap(id, "FINAL_SETTLEMENT_NOT_OBSERVED");
    };
    const cancelHeld = async () => {
      if (!held.scopeDigest) return;
      const reply = await deps.app("/api/uploads/approval/cancel", token, { attemptKey: held.attemptKey, scopeDigest: held.scopeDigest, fileKey });
      entry.cancel = routeSummary(reply);
      held.cancelled = reply?.status === 200 && ["INTAKE_SET_CANCELLED", "INTAKE_SET_CANCELLED_RECONCILIATION_REQUIRED"].includes(reply?.body?.code);
      if (!held.cancelled) gap(id, "CANCEL_NOT_CONFIRMED");
      // The summary is kept even if the cancel reply lacks an approval payload; no manufactured row.
    };
    const stop = async (code, halt = false) => {
      entry.stopped = code; gap(id, code);
      if (held.scopeDigest) await cancelHeld();
      if (held.documentId) await readSettlement();
      return halt ? "halt" : "continue";
    };
    try {
      held.attemptKey = deps.newAttemptKey();
      const approvalReply = await deps.app("/api/uploads/approval", token, { attemptKey: held.attemptKey, clientManifestDigest, pricingFingerprint,
        aggregateMaximumCredits: quoted.quote.maximumCredits, files });
      const approval = approvalReply?.body?.approval;
      const approvedFile = Array.isArray(approval?.files) && approval.files.length === 1 ? approval.files[0] : null;
      entry.approval = routeSummary(approvalReply);
      if (approvalReply?.status !== 200 || approvalReply?.body?.code !== "INTAKE_APPROVED") return stop("APPROVAL_NOT_GRANTED");
      if (DIGEST.test(String(approval?.scopeDigest))) held.scopeDigest = approval.scopeDigest;
      if (UUID.test(String(approvedFile?.documentId))) held.documentId = approvedFile.documentId;
      const quoteFile = quoted.quote.files?.[0];
      const approvalBound = held.scopeDigest && held.documentId && UUID.test(String(approval.approvalId)) && approval.state === "approved"
        && approval.attemptKey === held.attemptKey && approval.clientManifestDigest === clientManifestDigest && approval.pricingFingerprint === pricingFingerprint
        && approvedFile.fileKey === fileKey && approvedFile.contentSha256 === contentSha256 && approvedFile.byteLength === member.bytes
        && approvedFile.mimeType === member.mimeType && ["approved", "reserved", "confirmed"].includes(approvedFile.fileState)
        && approvedFile.pageBasis === quoteFile?.pageBasis && approvedFile.approvedMaxPages === quoteFile?.approvedMaxPages
        && approvedFile.approvedReservedCredits === quoteFile?.reservedCredits && approvedFile.approvedMaximumCredits === quoteFile?.maximumCredits
        && approval.aggregateMaximumCredits === quoted.quote.maximumCredits && approval.aggregateReservedCredits === quoted.quote.reservedCredits
        && report.budget.approvedMaximumCredits + approval.aggregateMaximumCredits <= request.maxCredits;
      if (!approvalBound) return stop("APPROVAL_RECEIPT_NOT_BOUND", true);
      const documentId = held.documentId;
      report.budget.approvedMaximumCredits += approval.aggregateMaximumCredits;
      entry.mapping = { fileKey, documentId, contentSha256, principalRefSha256, workspaceKey: workspace, basis: "ACTUAL_APPROVAL_MAPPING_ASSERTION_NOT_GRANT" };
      if (!observe("recordMapping", { id, fileKey, documentId, contentSha256, verified: true, basis: "actual_approval_identity_and_digest" })) return stop("MAPPING_REJECTED", true);
      observe("recordQuote", { fileKeys: [fileKey], result: quoted });
      observe("recordApproval", { phase: "approve", status: approvalReply.status, code: approvalReply.body.code, approval: {
        approvalId: approval.approvalId, state: approval.state, aggregateReservedCredits: approval.aggregateReservedCredits,
        aggregateMaximumCredits: approval.aggregateMaximumCredits, files: [{ fileKey, documentId, fileState: approvedFile.fileState, contentSha256,
          pageBasis: approvedFile.pageBasis, approvedMaxPages: approvedFile.approvedMaxPages, approvedReservedCredits: approvedFile.approvedReservedCredits,
          approvedMaximumCredits: approvedFile.approvedMaximumCredits, reservationState: only(STATE, approvedFile.reservationState ?? null) }] } });
      const objectKey = `quarantine/${workspace}/${documentId}/source`;
      const idempotencyKey = await deps.approvedSourceIdempotencyKey(held.attemptKey, fileKey);
      const capability = await deps.app("/api/uploads/capability", token, { originalFilename: member.filename, declaredMimeType: member.mimeType,
        requestedBytes: member.bytes, attemptKey: held.attemptKey, scopeDigest: held.scopeDigest, pricingFingerprint, fileKey, contentSha256 },
        "POST", { "x-tavonel-source-idempotency-key": idempotencyKey });
      const granted = capability?.body;
      entry.capability = { ...routeSummary(capability), documentIdBound: granted?.documentId === documentId, objectKeyBound: granted?.objectKey === objectKey };
      if (capability?.status !== 200 || granted?.code !== "QUALIFIED") {
        if (capability?.status >= 400 && capability?.status < 500 && CODE.test(String(granted?.code))) {
          observe("recordQualification", { fileKey, documentId, status: capability.status, code: granted.code, outcome: "refused" });
        }
        return stop("CAPABILITY_NOT_QUALIFIED");
      }
      if (granted.documentId !== documentId || granted.objectKey !== objectKey || typeof granted.uploadUrl !== "string"
        || granted.declaredMimeType !== SIGNED_PUT_MIME_TYPE || granted.computeReservation?.maximumCredits !== quoted.quote.maximumCredits) return stop("CAPABILITY_NOT_BOUND", true);
      observe("recordQualification", { fileKey, documentId, status: capability.status, code: granted.code, outcome: "qualified" });
      const putStatus = await deps.signedPut(granted.uploadUrl, member.content);
      entry.put = { status: statusOf(putStatus) };
      if (putStatus !== 200) return stop("SIGNED_PUT_NOT_STORED");
      const stored = await readObject(objectKey, member.bytes);
      entry.put.storedDigestBound = stored?.length === member.bytes && sha256Hex(stored) === member.sha256Hex;
      if (!entry.put.storedDigestBound) return stop("TRANSFER_OBJECT_NOT_BOUND", true);
      observe("recordEffect", { fileKey, effect: "transferred", value: true });
      const confirm = await deps.app("/api/uploads/confirm", token, { documentId, sourceSha256: contentSha256,
        attemptKey: held.attemptKey, scopeDigest: held.scopeDigest, fileKey });
      const confirmed = confirm?.body?.approvedFile;
      entry.confirm = routeSummary(confirm);
      const confirmBound = confirmed?.fileKey === fileKey && confirmed?.documentId === documentId && confirmed?.fileState === "confirmed";
      observe("recordConfirm", { status: confirm.status, code: only(CODE, confirm.body?.code ?? null),
        approvedFile: confirmBound ? { fileKey, documentId, fileState: confirmed.fileState } : null });
      if (confirm?.status !== 200 || confirm.body?.code !== "UPLOAD_CONFIRMED" || !confirmBound) return stop("CONFIRM_REFUSED");
      const enqueued = await deps.app("/api/compile-jobs", token, { documentIds: [documentId] });
      const jobId = enqueued?.body?.jobId;
      entry.compileEnqueue = { ...routeSummary(enqueued), jobId: only(JOB_ID, jobId ?? null) };
      if (enqueued?.status !== 202 || enqueued.body?.code !== "COMPILE_JOB_ACCEPTED" || !JOB_ID.test(String(jobId))) return stop("ACCESS_DECISION_IMPOSSIBLE_WITHOUT_JOB", true);
      const initialJob = await deps.jobRow(jobId);
      entry.jobBeforeSourceRead = structuralJob(jobId, initialJob);
      if (!initialJob || typeof initialJob.state !== "string") return stop("ACTUAL_JOB_ROW_UNAVAILABLE", true);
      const decision = await deps.authorizeCompileJobSourceAccess({ jobId, workspaceKey: workspace, documentIds: [documentId], phase: "before_source_read" });
      const allowed = decision?.ok === true, denied = decision?.ok === false && decision.code === "COMPILE_JOB_AUTHORITY_DENIED";
      entry.accessDecision = { jobId, documentId, workspaceKey: workspace, contextPrincipalRefSha256: principalRefSha256,
        actorBinding: "RPC_DERIVES_ACTOR_FROM_IMMUTABLE_JOB_ROWS_NOT_INDEPENDENTLY_VERIFIED_BY_HOOK",
        decision: allowed ? "allowed" : denied ? "denied" : null, code: only(CODE, decision?.code ?? null) };
      if (!allowed && !denied) return stop("ACCESS_DECISION_UNAVAILABLE", true);
      if (!observe("recordAccessDecision", { fileKey, boundary: "external_authorization", principalRef: owner,
        decision: allowed ? "allowed" : "denied", reasonCode: denied ? decision.code : null, status: null })) return stop("ACCESS_RECORDER_REJECTED", true);
      if (denied) return stop("ACCESS_DENIED", true);
      await deps.checkpointReport(report);
      try { await deps.deliver(objectKey, 1); entry.delivery = { outcome: "returned", attempts: 1 }; }
      catch (error) { entry.delivery = { outcome: "error", attempts: 1, error: errorShape(error) }; gap(id, "DELIVERY_DID_NOT_COMPLETE"); }
      const versionKey = await readCdrOutcome({ entry, documentId, objectKey, member, observe });
      await readSettlement();
      // Only drive the actual authorized job; provider failures remain observations even without a candidate.
      if (entry.delivery.outcome === "returned") await driveCompile({ entry, documentId, jobId, versionKey, observe });
      await deps.checkpointReport(report);
      return "continue";
    } catch (error) {
      entry.error = errorShape(error); gap(id, "MEMBER_CALLBACK_ERROR");
      if (!held.cancelled && held.scopeDigest) {
        try { await cancelHeld(); if (held.documentId && entry.mapping) await readSettlement(); }
        catch (cancelError) { entry.cancelError = errorShape(cancelError); gap(id, "CANCEL_NOT_CONFIRMED"); }
      }
      return "halt";
    }
  }

  function structuralJob(jobId, row) {
    return { jobId, state: only(STATE, row?.state ?? null), collectionId: only(COLLECTION_ID, row?.collectionId || null),
      manifestDigest: only(DIGEST, row?.manifestDigest || null), errorCode: only(CODE, row?.errorCode || null) };
  }
  async function readCdrOutcome({ entry, documentId, objectKey, member, observe }) {
    const id = member.id, prefix = `immutable/${workspace}/${workspace}/${documentId}/`;
    const keys = await deps.listKeys(prefix);
    const sanitizedKeys = keys.filter(key => typeof key === "string" && key.endsWith("/sanitized.pdf"));
    const reject = await readJson(`quarantine/${workspace}/${documentId}/cdr-reject.json`, RECEIPT_MAX_BYTES);
    entry.cdr = { sanitizedVersions: sanitizedKeys.length, rejectReceiptPresent: reject.present, reject: null, sanitized: null };
    if (sanitizedKeys.length > 1 || (sanitizedKeys.length && reject.present)) { gap(id, "CDR_OUTCOME_AMBIGUOUS"); return null; }
    if (reject.present) {
      const r = reject.value;
      const valid = r?.schemaVersion === "tavonel.cdr_reject_receipt.v1" && r.sourceKey === objectKey && CODE.test(String(r.reasonCode))
        && typeof r.provider === "string" && LABEL.test(r.provider) && typeof r.occurredAt === "string" && TIMESTAMP.test(r.occurredAt)
        && Number.isFinite(Date.parse(r.occurredAt)) && [r.observedBytes, r.declaredBytes].every(value => value === null || countOf(value) !== null);
      entry.cdr.reject = { valid, sourceKeyBound: r?.sourceKey === objectKey, reasonCode: only(CODE, r?.reasonCode ?? null),
        observedBytes: countOf(r?.observedBytes), declaredBytes: countOf(r?.declaredBytes), occurredAt: only(TIMESTAMP, r?.occurredAt ?? null) };
      if (valid) {
        observe("recordCdrOcr", { documentId, outcome: "failed", versionKey: null, failureCode: r.reasonCode, cdrStatus: "rejected_receipt", ocr: null });
        // The reject schema has no input digest. A size guard can reject before reading bytes,
        // so it establishes the rejection outcome only, not content-read or compute effects.
      } else gap(id, "CDR_REJECT_RECEIPT_NOT_BOUND");
      return null;
    }
    if (sanitizedKeys.length !== 1) { gap(id, "NO_CDR_OUTCOME_OBJECT"); return null; }
    const sanitizedKey = sanitizedKeys[0], versionKey = sanitizedKey.slice(prefix.length).split("/")[0];
    if (!HEX64.test(versionKey) || sanitizedKey !== `${prefix}${versionKey}/sanitized.pdf`) { gap(id, "SANITIZED_KEY_NOT_VERSIONED"); return null; }
    const bytes = await readObject(sanitizedKey, SANITIZED_MAX_BYTES);
    const r = (await readJson(`${prefix}${versionKey}/cdr-receipt.json`, RECEIPT_MAX_BYTES)).value;
    const bound = Boolean(bytes) && sha256Hex(bytes) === versionKey && r?.schemaVersion === "tavonel.cdr_receipt.v2"
      && r.status === "clean" && r.sourceKey === objectKey && r.immutableKey === sanitizedKey
      && r.inputSha256 === `sha256:${member.sha256Hex}` && r.outputSha256 === `sha256:${versionKey}`;
    entry.cdr.sanitized = { versionKey, digestVerified: Boolean(bytes) && sha256Hex(bytes) === versionKey, receiptBound: bound };
    if (!bound) { gap(id, "CDR_OUTPUT_NOT_BOUND"); return null; }
    const ocr = await readJson(`${prefix}${versionKey}/ocr.json`, OCR_MAX_BYTES);
    const correlated = await deps.ocrCallsFor(`sha256:${versionKey}`);
    const statuses = Array.isArray(correlated) ? correlated.filter(call => call?.inputSha256 === `sha256:${versionKey}`).map(call => statusOf(call.status)) : [];
    const pageCount = countOf(ocr.value?.pageCount);
    const ocrBound = Array.isArray(ocr.value?.regions) && pageCount > 0 && statuses.includes(200)
      && (ocr.value.inputSha256 == null || ocr.value.inputSha256 === `sha256:${versionKey}`);
    entry.ocr = { objectPresent: ocr.present, regionCount: Array.isArray(ocr.value?.regions) ? ocr.value.regions.length : null,
      pageCount, correlatedCallStatuses: statuses, inputBound: ocrBound };
    observe("recordCdrOcr", { documentId, outcome: "sanitized", versionKey, cdrStatus: r.status,
      ocr: ocrBound ? { status: 200, pageCount } : null });
    observe("recordEffect", { fileKey: entry.mapping.fileKey, effect: "content_read", value: true });
    observe("recordEffect", { fileKey: entry.mapping.fileKey, effect: "processed", value: true });
    if (!ocrBound) gap(id, "OCR_NOT_BOUND_TO_VERSION");
    // Correlated non-200 provider statuses stay in the report; no OCR failure code is guessed from absence.
    return versionKey;
  }
  async function driveCompile({ entry, documentId, jobId, versionKey, observe }) {
    const id = entry.id;
    let row;
    try { row = await deps.driveJob(jobId); }
    catch (error) { entry.compile = { error: errorShape(error), job: structuralJob(jobId, await deps.jobRow(jobId)) }; gap(id, "COMPILE_JOB_NOT_TERMINAL"); return; }
    const job = structuralJob(jobId, row);
    entry.compile = { job, candidate: null, verification: null };
    let candidate = null, receiptVerification = null;
    if (["ready", "review_required"].includes(row?.state)) {
      if (!COLLECTION_ID.test(String(row.collectionId)) || !DIGEST.test(String(row.manifestDigest))) gap(id, "CANDIDATE_PATH_UNAVAILABLE");
      else {
        const actual = (await readJson(`immutable/${workspace}/${workspace}/collections/${row.collectionId}/${row.manifestDigest.slice(7)}/candidate-world.json`, CANDIDATE_MAX_BYTES)).value;
        const outputDigest = actual?.coreExecution?.receipt?.outputSha256;
        // CollectionCandidateArtifact and projectProductCoreV2Candidate both return this
        // independent top-level field. Never fill it from the job row or signed payload.
        const candidateDigest = actual?.manifestDigest;
        const candidateDigestObserved = DIGEST.test(String(candidateDigest));
        const candidateSchemaBound = actual?.schemaVersion === "tavonel.collection_candidate.v1" && actual.collectionId === row.collectionId;
        const docs = actual?.sourceDocuments;
        const candidateBound = candidateSchemaBound && versionKey && DIGEST_OR_HEX.test(String(outputDigest)) && Array.isArray(docs) && docs.length === 1
          && docs[0]?.documentId === documentId && docs[0]?.versionKey === versionKey;
        entry.compile.candidate = { sourceDocumentsBound: Boolean(candidateBound), coreOutputSha256: only(DIGEST_OR_HEX, outputDigest ?? null),
          schemaAndCollectionBound: candidateSchemaBound,
          manifestDigest: only(DIGEST, candidateDigest ?? null), manifestDigestObserved: candidateDigestObserved,
          manifestMatchesJob: candidateDigestObserved ? candidateDigest === row.manifestDigest : null };
        if (!candidateDigestObserved) gap(id, "CANDIDATE_MANIFEST_DIGEST_UNOBSERVED");
        else if (candidateDigest !== row.manifestDigest) gap(id, "CANDIDATE_MANIFEST_DIGEST_MISMATCH");
        if (!candidateSchemaBound) gap(id, "CANDIDATE_SCHEMA_OR_COLLECTION_UNBOUND");
        if (!candidateBound) gap(id, "CANDIDATE_NOT_BOUND_TO_JOB_SOURCE");
        if (candidateBound && candidateDigestObserved) {
          candidate = { manifestDigest: candidateDigest, coreOutputSha256: outputDigest, sourceDocuments: [{ documentId, versionKey }] };
        }
        if (actual?.signedReceipt && typeof actual.signedReceipt === "object") {
          const verified = await deps.verifyCompileReceipt(actual.signedReceipt, { tenantId: workspace, workspaceId: workspace }, deps.trust);
          const matches = Boolean(candidateBound) && candidateDigestObserved && candidateDigest === row.manifestDigest
            && verified?.ok === true && verified.payload?.manifestDigest === candidateDigest
            && verified.payload?.coreOutputSha256 === outputDigest;
          entry.compile.verification = { ok: verified?.ok === true, exactDigestsMatch: matches, code: only(CODE, verified?.code ?? null),
            payload: verified?.ok === true ? { manifestDigest: only(DIGEST_OR_HEX, verified.payload?.manifestDigest ?? null),
              coreOutputSha256: only(DIGEST_OR_HEX, verified.payload?.coreOutputSha256 ?? null) } : null };
          if (verified?.ok === true && DIGEST_OR_HEX.test(String(verified.payload?.manifestDigest)) && DIGEST_OR_HEX.test(String(verified.payload?.coreOutputSha256))) {
            receiptVerification = { ok: true, payload: { manifestDigest: verified.payload.manifestDigest, coreOutputSha256: verified.payload.coreOutputSha256 } };
          } else receiptVerification = { ok: false };
          if (!matches) gap(id, "COMPILE_RECEIPT_UNVERIFIED_OR_MISMATCHED");
        } else gap(id, "COMPILE_SIGNED_RECEIPT_UNAVAILABLE");
      }
    }
    if (!["ready", "review_required", "failed", "cancelled"].includes(row?.state)) gap(id, "COMPILE_JOB_NOT_TERMINAL");
    if (Object.values(job).includes("[withheld]")) { gap(id, "COMPILE_JOB_ROW_NOT_STRUCTURAL"); return; }
    observe("recordCompile", { documentIds: [documentId], job: { jobId, state: row.state, collectionId: row.collectionId,
      manifestDigest: row.manifestDigest, errorCode: row.errorCode }, candidate, receiptVerification });
  }
}
