/**
 * G1-11 runtime-results producer (offline source delta, proposed Core path tests/e2e/joined/).
 *
 * Records product-return observations supplied by a future, separately authorized harness hook and
 * projects them into tavonel.g1-11.runtime-results.v1 plus a diagnostic sidecar. It never calls the
 * product and never re-implements quote, admission, compiler, ACL or duplicate policy. Fixture
 * expectations are never read. Supplied observations are unauthenticated data. Importing this module
 * has no side effects: no network, DB, keys, processes or filesystem access.
 *
 * Every observation carries a caller context that must equal the immutable per-member authority
 * binding (a fixture-to-runtime mapping assertion, never an authorization grant), every projection
 * needs an actual per-file access decision, and the run/commit binding is fixed at construction.
 * A false effect needs a complete monitoring claim whose scope names exactly this run pair, member,
 * mapped fileKey, owner labels, context principal/workspace and effect, with the canonical scope
 * digest as its receipt. That is a structural binding of supplied data, not an authenticated monitor.
 */
import { createHash } from "node:crypto";

export const RUNTIME_RESULTS_SCHEMA = "tavonel.g1-11.runtime-results.v1";
export const SIDECAR_SCHEMA = "tavonel.g1-11.runtime-producer-sidecar.v1";
export const EVIDENCE_KINDS = Object.freeze(["RUNTIME_RECEIPT", "SYNTHETIC_CONTRACT_TEST"]);
export const EFFECTS = Object.freeze(["content_read", "transferred", "processed", "charged"]);
/** Whitelisted monitoring scope fields, in comparison order. */
export const MONITORING_SCOPE_FIELDS = Object.freeze(["run_id", "foundation_commit", "core_commit", "id", "file_key",
  "source_id", "source_version", "source_sha256", "acl_scope", "principal_ref_sha256", "workspace_key", "effect"]);

const MEMBER_COUNT = 7;
const MAX_TEXT = 512;
const MAX_LIST = 128;
const MAX_JOURNAL = 1024;
const MAX_LISTED_REJECTIONS = 128;
const HEX64 = /^[a-f0-9]{64}$/;
const HEX40 = /^[a-f0-9]{40}$/;
const PAGE_BASES = ["measured", "declared", "unknown"];
const FILE_STATES = ["approved", "reserved", "confirmed", "cancelled"];
const COMPILE_CANDIDATE_STATES = ["ready", "review_required"];

export class ProducerInputError extends Error {
  /** Messages name only the code and the field path, never the rejected value. */
  constructor(code, field) {
    super(field ? `${code}: ${field}` : code);
    this.name = "ProducerInputError";
    this.code = code;
    this.field = field ?? null;
  }
}

function fail(code, field) {
  throw new ProducerInputError(code, field);
}

function obj(value, field) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail("INVALID_OBJECT", field);
  return value;
}

function text(value, field) {
  if (typeof value !== "string" || value.length < 1 || value.length > MAX_TEXT
    || value.trim() !== value || /[\x00-\x1f\x7f]/.test(value)) fail("INVALID_TEXT", field);
  return value;
}

const optText = (value, field) => (value === null || value === undefined ? null : text(value, field));
/** Harness SQL rows use coalesce(column, '') for null; only the empty string is mapped to null. */
const rowText = (value, field) => (value === "" ? null : optText(value, field));

/** Normalizes `sha256:<64hex>` or `<64hex>` to raw lowercase hex. The prefix is stripped exactly once. */
function sha(value, field) {
  if (typeof value !== "string") fail("INVALID_SHA256", field);
  const raw = value.startsWith("sha256:") ? value.slice(7) : value;
  if (!HEX64.test(raw)) fail("INVALID_SHA256", field);
  return raw;
}

const optSha = (value, field) => (value === null || value === undefined ? null : sha(value, field));
/** Same coalesce(column, '') convention as rowText, for digest columns. */
const rowSha = (value, field) => (value === "" ? null : optSha(value, field));

/** Foundation triage ACL observations are raw 64hex only (intake-triage.ts:165,184). */
function rawHex(value, field) {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" || !HEX64.test(value)) fail("INVALID_SHA256", field);
  return value;
}

function units(value, field) {
  if (!Number.isSafeInteger(value) || value < 0) fail("INVALID_UNITS", field);
  return value;
}

/** A measured page count is a positive integer; absence stays null and zero is never "unknown". */
function pages(value, field) {
  if (value === null || value === undefined) return null;
  if (!Number.isSafeInteger(value) || value < 1) fail("INVALID_PAGE_COUNT", field);
  return value;
}

function httpStatus(value, field) {
  if (!Number.isSafeInteger(value) || value < 100 || value > 599) fail("INVALID_STATUS", field);
  return value;
}

function oneOf(value, allowed, field) {
  if (!allowed.includes(value)) fail("INVALID_ENUM", field);
  return value;
}

function list(value, field, min = 0) {
  if (!Array.isArray(value) || value.length < min || value.length > MAX_LIST) fail("INVALID_LIST", field);
  return value;
}

function distinct(values, field) {
  if (new Set(values).size !== values.length) fail("IDENTITY_COLLAPSE", field);
  return values;
}

const is2xx = (status) => status >= 200 && status < 300;

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

const digestOf = (value) => createHash("sha256").update(canonical(value), "utf8").digest("hex");
const same = (a, b) => canonical(a) === canonical(b);
const copy = (value) => JSON.parse(JSON.stringify(value));
/** Principal references are compared and retained only as sha256 hex of their UTF-8 bytes. */
const principalDigest = (value) => createHash("sha256").update(value, "utf8").digest("hex");

/**
 * Deterministic structural receipt digest: sha256 hex of canonical {complete: true, scope} over exactly
 * MONITORING_SCOPE_FIELDS (strings only). It binds a supplied receipt to one scope; any caller can compute
 * it, so it never authenticates a monitor or proves an effect stayed false.
 */
export function monitoringReceiptSha256(scope) {
  obj(scope, "scope");
  return digestOf({ complete: true,
    scope: Object.fromEntries(MONITORING_SCOPE_FIELDS.map((name) => [name, text(scope[name], `scope.${name}`)])) });
}

/** {run_id, foundation_commit, core_commit}; only these three fields are read and copied. */
function executionBindingOf(value, field) {
  obj(value, field);
  const binding = { run_id: text(value.run_id, `${field}.run_id`) };
  for (const name of ["foundation_commit", "core_commit"]) {
    if (typeof value[name] !== "string" || !HEX40.test(value[name])) fail("INVALID_COMMIT", `${field}.${name}`);
    binding[name] = value[name];
  }
  return Object.freeze(binding);
}

/** null (unbound) or {principal_ref_sha256: raw 64hex, workspace_key, acl_scope: exactly the owner label}. */
function authorityBindingOf(value, aclScope, field) {
  if (value === null || value === undefined) return null;
  obj(value, field);
  if (typeof value.principal_ref_sha256 !== "string" || !HEX64.test(value.principal_ref_sha256)) {
    fail("INVALID_SHA256", `${field}.principal_ref_sha256`);
  }
  const binding = Object.freeze({
    principal_ref_sha256: value.principal_ref_sha256,
    workspace_key: text(value.workspace_key, `${field}.workspace_key`),
    acl_scope: text(value.acl_scope, `${field}.acl_scope`),
  });
  if (binding.acl_scope !== aclScope) fail("AUTHORITY_SCOPE_MISMATCH", `${field}.acl_scope`);
  return binding;
}

/** The observation context, hashed before it is compared or retained; plaintext is never kept. */
function contextOf(value) {
  const context = obj(value, "context");
  return Object.freeze({
    principal_ref_sha256: principalDigest(text(context.principalRef, "context.principalRef")),
    workspace_key: text(context.workspaceKey, "context.workspaceKey"),
    acl_scope: text(context.aclScope, "context.aclScope"),
  });
}

function emptyState() {
  return {
    fileKey: null, mappingBasis: null, documentId: null, versionKey: null,
    quote: null, approval: null, confirms: [], triage: null, qualification: null, access: null,
    cdr: null, cdrReplays: 0, compiles: [], settlement: null,
    effects: { content_read: null, transferred: null, processed: null, charged: null },
  };
}

/**
 * members: exactly seven fixture identity bindings. Only id/source_id/source_version/source_sha256/
 * acl_scope/authority_binding are copied; `expected` or any other field is never read. evidence_kind
 * and execution_binding are fixed here so a SYNTHETIC_CONTRACT_TEST producer can never emit
 * RUNTIME_RECEIPT and a journal can never be relabelled to another run/commit pair. A null or absent
 * execution_binding only permits a no-observation NOT_RUN result.
 */
export function createRuntimeProducer(input) {
  obj(input, "input");
  const evidenceKind = oneOf(input.evidence_kind, EVIDENCE_KINDS, "evidence_kind");
  const executionBinding = input.execution_binding == null ? null : executionBindingOf(input.execution_binding, "execution_binding");
  const rawMembers = list(input.members, "members");
  if (rawMembers.length !== MEMBER_COUNT) fail("MEMBER_COUNT", "members");
  const members = new Map();
  for (const raw of rawMembers) {
    obj(raw, "members[]");
    const labels = {
      id: text(raw.id, "members[].id"),
      source_id: text(raw.source_id, "members[].source_id"),
      source_version: text(raw.source_version, "members[].source_version"),
      source_sha256: sha(raw.source_sha256, "members[].source_sha256"),
      acl_scope: text(raw.acl_scope, "members[].acl_scope"),
    };
    const binding = Object.freeze({
      ...labels,
      authority_binding: authorityBindingOf(raw.authority_binding, labels.acl_scope, "members[].authority_binding"),
    });
    if (members.has(binding.id)) fail("DUPLICATE_MEMBER_ID", "members[].id");
    members.set(binding.id, { binding, state: emptyState() });
  }
  const ownerBindings = Object.freeze([...members.values()].map((m) => m.binding)
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)));

  const byFileKey = new Map();
  const byDocumentId = new Map();
  const journal = [];
  const rejections = [];
  let rejectionCount = 0;

  const st = (id) => members.get(id).state;
  const memberForKey = (fileKey, field) => byFileKey.get(text(fileKey, field)) ?? fail("UNMAPPED_FILE_KEY", field);
  const memberForDocument = (documentId, field) => byDocumentId.get(text(documentId, field)) ?? fail("UNMAPPED_DOCUMENT_ID", field);

  function checkDigest(id, value, field) {
    const raw = sha(value, field);
    if (raw !== members.get(id).binding.source_sha256) fail("DIGEST_MISMATCH", field);
    return raw;
  }

  /**
   * The supplied scope must equal, field by field, the scope derived from the constructor run pair, the
   * member's owner labels and mapped fileKey, the hashed context and the effect; the receipt must be its
   * canonical digest. A receipt for another member, effect, principal or run is therefore refused.
   */
  function monitoringOf(id, effect, context, value) {
    const m = obj(value, "monitoring");
    if (m.complete !== true) fail("MONITORING_NOT_COMPLETE", "monitoring.complete");
    const supplied = obj(m.scope, "monitoring.scope");
    const { binding } = members.get(id);
    const scope = {
      ...executionBinding, id, file_key: st(id).fileKey,
      source_id: binding.source_id, source_version: binding.source_version, source_sha256: binding.source_sha256,
      acl_scope: binding.acl_scope, principal_ref_sha256: context.principal_ref_sha256,
      workspace_key: context.workspace_key, effect,
    };
    for (const name of MONITORING_SCOPE_FIELDS) {
      if (supplied[name] !== scope[name]) fail("MONITORING_SCOPE_MISMATCH", `monitoring.scope.${name}`);
    }
    const receipt = sha(m.receiptSha256, "monitoring.receiptSha256");
    if (receipt !== monitoringReceiptSha256(scope)) fail("MONITORING_RECEIPT_MISMATCH", "monitoring.receiptSha256");
    return { complete: true, scope, receipt_sha256: receipt };
  }

  function checkDocument(id, documentId, field) {
    if (st(id).documentId !== null && st(id).documentId !== documentId) fail("IDENTITY_CHANGED", field);
    if (byDocumentId.has(documentId) && byDocumentId.get(documentId) !== id) fail("IDENTITY_COLLAPSE", field);
  }

  function bindDocument(id, documentId) {
    st(id).documentId = documentId;
    byDocumentId.set(documentId, id);
  }

  // Each parser validates everything before returning; apply() only commits already-checked values.
  const parsers = {
    member_mapping(o) {
      if (o.verified !== true) fail("MAPPING_NOT_VERIFIED", "verified");
      const id = text(o.id, "id");
      if (!members.has(id)) fail("UNKNOWN_MEMBER", "id");
      const fileKey = text(o.fileKey, "fileKey");
      const contentSha256 = checkDigest(id, o.contentSha256, "contentSha256");
      const documentId = optText(o.documentId, "documentId");
      const basis = text(o.basis, "basis");
      if (st(id).fileKey !== null && st(id).fileKey !== fileKey) fail("IDENTITY_CHANGED", "fileKey");
      if (byFileKey.has(fileKey) && byFileKey.get(fileKey) !== id) fail("IDENTITY_COLLAPSE", "fileKey");
      if (documentId !== null) checkDocument(id, documentId, "documentId");
      return {
        ids: [id],
        entry: { id, file_key: fileKey, document_id: documentId, content_sha256: contentSha256, basis },
        apply() {
          st(id).fileKey = fileKey;
          st(id).mappingBasis = basis;
          byFileKey.set(fileKey, id);
          if (documentId !== null) bindDocument(id, documentId);
        },
      };
    },

    quote(o) {
      const fileKeys = list(o.fileKeys, "fileKeys", 1).map((key) => text(key, "fileKeys[]"));
      const ids = distinct(fileKeys.map((key) => memberForKey(key, "fileKeys[]")), "fileKeys");
      const result = obj(o.result, "result");
      let files = null, totals = null, failure = null;
      if (result.ok === true) {
        const quote = obj(result.quote, "result.quote");
        const raw = list(quote.files, "result.quote.files");
        if (raw.length !== fileKeys.length) fail("QUOTE_FILE_COUNT", "result.quote.files");
        files = raw.map((file) => (obj(file, "result.quote.files[]"), {
          page_basis: oneOf(file.pageBasis, PAGE_BASES, "result.quote.files[].pageBasis"),
          approved_max_pages: units(file.approvedMaxPages, "result.quote.files[].approvedMaxPages"),
          reserved_credits: units(file.reservedCredits, "result.quote.files[].reservedCredits"),
          maximum_credits: units(file.maximumCredits, "result.quote.files[].maximumCredits"),
        }));
        totals = {
          maximum_pages: units(quote.maximumPages, "result.quote.maximumPages"),
          reserved_credits: units(quote.reservedCredits, "result.quote.reservedCredits"),
          maximum_credits: units(quote.maximumCredits, "result.quote.maximumCredits"),
        };
      } else if (result.ok === false) {
        failure = { code: text(result.code, "result.code"), index: units(result.index, "result.index") };
        if (failure.index >= fileKeys.length) fail("QUOTE_INDEX", "result.index");
      } else fail("INVALID_ENUM", "result.ok");
      return {
        ids,
        entry: { file_keys: fileKeys, ok: result.ok, files, totals, failure },
        apply() {
          ids.forEach((id, index) => {
            st(id).quote = files ? { ok: true, ...files[index] }
              : { ok: false, code: failure.code, at_failing_index: index === failure.index };
          });
        },
      };
    },

    approval(o) {
      const phase = oneOf(o.phase, ["approve", "cancel"], "phase");
      const status = httpStatus(o.status, "status");
      const code = optText(o.code, "code");
      if (!is2xx(status)) {
        // A whole-request refusal is not a per-file ACL or qualification result.
        const fileKeys = (o.fileKeys == null ? [] : list(o.fileKeys, "fileKeys")).map((key) => text(key, "fileKeys[]"));
        const ids = fileKeys.map((key) => memberForKey(key, "fileKeys[]"));
        return { ids, entry: { phase, status, code, request_level: true, file_keys: fileKeys }, apply() {} };
      }
      const approval = obj(o.approval, "approval");
      const summary = {
        approval_id: text(approval.approvalId, "approval.approvalId"),
        state: oneOf(approval.state, ["approved", "cancelled"], "approval.state"),
        aggregate_reserved_credits: units(approval.aggregateReservedCredits, "approval.aggregateReservedCredits"),
        aggregate_maximum_credits: units(approval.aggregateMaximumCredits, "approval.aggregateMaximumCredits"),
      };
      const files = list(approval.files, "approval.files", 1).map((file) => {
        obj(file, "approval.files[]");
        const id = memberForKey(file.fileKey, "approval.files[].fileKey");
        const documentId = text(file.documentId, "approval.files[].documentId");
        checkDocument(id, documentId, "approval.files[].documentId");
        return {
          id, file_key: file.fileKey, document_id: documentId,
          file_state: oneOf(file.fileState, FILE_STATES, "approval.files[].fileState"),
          content_sha256: checkDigest(id, file.contentSha256, "approval.files[].contentSha256"),
          page_basis: oneOf(file.pageBasis, PAGE_BASES, "approval.files[].pageBasis"),
          approved_max_pages: units(file.approvedMaxPages, "approval.files[].approvedMaxPages"),
          approved_reserved_credits: units(file.approvedReservedCredits, "approval.files[].approvedReservedCredits"),
          approved_maximum_credits: units(file.approvedMaximumCredits, "approval.files[].approvedMaximumCredits"),
          reservation_state: optText(file.reservationState, "approval.files[].reservationState"),
        };
      });
      distinct(files.map((file) => file.id), "approval.files");
      distinct(files.map((file) => file.document_id), "approval.files[].documentId");
      return {
        ids: files.map((file) => file.id),
        entry: { phase, status, code, request_level: false, approval: summary, files },
        apply() {
          for (const file of files) {
            bindDocument(file.id, file.document_id);
            st(file.id).approval = { phase, status, code, ...summary, ...file };
          }
        },
      };
    },

    confirm(o) {
      const status = httpStatus(o.status, "status");
      const code = optText(o.code, "code");
      if (o.approvedFile == null) return { ids: [], entry: { status, code, request_level: true }, apply() {} };
      const file = obj(o.approvedFile, "approvedFile");
      const id = memberForKey(file.fileKey, "approvedFile.fileKey");
      const documentId = text(file.documentId, "approvedFile.documentId");
      checkDocument(id, documentId, "approvedFile.documentId");
      const row = { status, code, file_key: file.fileKey, document_id: documentId,
        file_state: oneOf(file.fileState, FILE_STATES, "approvedFile.fileState") };
      return {
        ids: [id],
        entry: { request_level: false, ...row },
        apply() {
          bindDocument(id, documentId);
          st(id).confirms.push(row);
        },
      };
    },

    triage(o) {
      const scope = obj(o.scope, "scope");
      // The product triage scope's workspace/source identity is retained so a change is rejected, not
      // ignored. It is a product identity, never a fixture label, and never an access decision.
      const triageScope = {
        workspace_key: text(scope.workspaceKey, "scope.workspaceKey"),
        source_id: text(scope.sourceId, "scope.sourceId"),
        source_kind: oneOf(scope.sourceKind, ["direct_upload", "connector"], "scope.sourceKind"),
        inventory_revision: text(scope.inventoryRevision, "scope.inventoryRevision"),
        acl_observation_sha256: rawHex(scope.aclObservationSha256, "scope.aclObservationSha256"),
      };
      const rows = list(o.files, "files", 1).map((file) => {
        obj(file, "files[]");
        const id = memberForKey(file.fileKey, "files[].fileKey");
        const row = {
          id, file_key: file.fileKey,
          revision: optText(file.revision, "files[].revision"),
          content_sha256: file.contentSha256 === null ? null : checkDigest(id, file.contentSha256, "files[].contentSha256"),
          acl_observation_sha256: rawHex(file.aclObservationSha256, "files[].aclObservationSha256"),
          disposition: oneOf(file.disposition, ["include", "exclude", "needs_review"], "files[].disposition"),
          reason: text(file.reason, "files[].reason"),
          exact_duplicate_of: optText(file.exactDuplicateOf, "files[].exactDuplicateOf"),
        };
        const previous = st(id).triage;
        if (previous && !same(previous.scope, triageScope)) fail("SCOPE_CHANGED", "scope");
        if (previous && !same(previous.row, row)) fail("TRIAGE_CHANGED", "files[]");
        return row;
      });
      distinct(rows.map((row) => row.id), "files");
      return {
        ids: rows.map((row) => row.id),
        entry: { scope: triageScope, files: rows },
        apply() { for (const row of rows) st(row.id).triage = { scope: triageScope, row }; },
      };
    },

    qualification(o) {
      const id = memberForKey(o.fileKey, "fileKey");
      const status = httpStatus(o.status, "status");
      const outcome = oneOf(o.outcome, ["qualified", "refused"], "outcome");
      if (outcome === "refused" && !(status >= 400 && status < 500)) fail("REFUSAL_NEEDS_4XX", "status");
      if (outcome === "qualified" && !is2xx(status)) fail("QUALIFIED_NEEDS_2XX", "status");
      const documentId = optText(o.documentId, "documentId");
      if (documentId !== null) checkDocument(id, documentId, "documentId");
      const row = { file_key: o.fileKey, status, code: text(o.code, "code"), outcome, document_id: documentId };
      if (st(id).qualification && !same(st(id).qualification, row)) fail("QUALIFICATION_CHANGED", "outcome");
      return {
        ids: [id], entry: row,
        apply() {
          if (documentId !== null) bindDocument(id, documentId);
          st(id).qualification = row;
        },
      };
    },

    access_decision(o, context) {
      const id = memberForKey(o.fileKey, "fileKey");
      if (o.boundary !== "external_authorization") fail("NOT_EXTERNAL_ACCESS_BOUNDARY", "boundary");
      const decision = oneOf(o.decision, ["allowed", "denied"], "decision");
      // The decision must be about the context principal; authorize() then binds it to the member.
      const principalRefSha256 = principalDigest(text(o.principalRef, "principalRef"));
      if (principalRefSha256 !== context.principal_ref_sha256) fail("ACCESS_PRINCIPAL_MISMATCH", "principalRef");
      const row = {
        file_key: o.fileKey, boundary: o.boundary, decision,
        // The principal reference is retained only as a digest.
        principal_ref_sha256: principalRefSha256,
        reason_code: decision === "denied" ? text(o.reasonCode, "reasonCode") : optText(o.reasonCode, "reasonCode"),
        status: o.status == null ? null : httpStatus(o.status, "status"),
      };
      if (st(id).access && !same(st(id).access, row)) fail("ACCESS_DECISION_CHANGED", "decision");
      return { ids: [id], entry: row, apply() { st(id).access = row; } };
    },

    cdr_ocr(o) {
      const id = memberForDocument(o.documentId, "documentId");
      const outcome = oneOf(o.outcome, ["sanitized", "failed"], "outcome");
      const versionKey = outcome === "sanitized" ? sha(o.versionKey, "versionKey") : optSha(o.versionKey, "versionKey");
      const failureCode = outcome === "failed" ? text(o.failureCode, "failureCode") : null;
      if (outcome === "sanitized" && o.failureCode != null) fail("FAILURE_CODE_ON_SUCCESS", "failureCode");
      const ocr = o.ocr == null ? null : (obj(o.ocr, "ocr"), {
        status: httpStatus(o.ocr.status, "ocr.status"),
        page_count: pages(o.ocr.pageCount, "ocr.pageCount"),
      });
      const row = { document_id: o.documentId, outcome, version_key: versionKey,
        cdr_status: text(o.cdrStatus, "cdrStatus"), failure_code: failureCode, ocr };
      if (versionKey !== null && st(id).versionKey !== null && st(id).versionKey !== versionKey) fail("REVISION_CHANGED", "versionKey");
      if (st(id).cdr && !same(st(id).cdr, row)) fail("CDR_RECEIPT_CHANGED", "outcome");
      return {
        ids: [id], entry: row,
        apply() {
          if (st(id).cdr) st(id).cdrReplays += 1;
          st(id).cdr = row;
          if (versionKey !== null) st(id).versionKey = versionKey;
        },
      };
    },

    compile(o) {
      const job = obj(o.job, "job");
      const documentIds = list(o.documentIds, "documentIds", 1).map((doc) => text(doc, "documentIds[]"));
      const ids = distinct(documentIds.map((doc) => memberForDocument(doc, "documentIds[]")), "documentIds");
      const candidate = o.candidate == null ? null : (obj(o.candidate, "candidate"), {
        manifest_digest: sha(o.candidate.manifestDigest, "candidate.manifestDigest"),
        core_output_sha256: sha(o.candidate.coreOutputSha256, "candidate.coreOutputSha256"),
        source_documents: list(o.candidate.sourceDocuments, "candidate.sourceDocuments", 1).map((doc) => (obj(doc, "candidate.sourceDocuments[]"), {
          document_id: text(doc.documentId, "candidate.sourceDocuments[].documentId"),
          version_key: sha(doc.versionKey, "candidate.sourceDocuments[].versionKey"),
        })),
      });
      if (candidate) {
        // A candidate must name exactly the job's documents, each once with one version; nothing is merged.
        const versions = new Map();
        for (const doc of candidate.source_documents) {
          if (versions.has(doc.document_id)) {
            fail(versions.get(doc.document_id) === doc.version_key ? "DUPLICATE_SOURCE_DOCUMENT" : "CONFLICTING_SOURCE_DOCUMENT_VERSION",
              "candidate.sourceDocuments[].documentId");
          }
          versions.set(doc.document_id, doc.version_key);
          if (!documentIds.includes(doc.document_id)) fail("CANDIDATE_DOCUMENT_NOT_IN_JOB", "candidate.sourceDocuments[].documentId");
          const known = st(byDocumentId.get(doc.document_id)).versionKey;
          if (known !== null && known !== doc.version_key) fail("SOURCE_VERSION_MISMATCH", "candidate.sourceDocuments[].versionKey");
        }
        if (documentIds.some((doc) => !versions.has(doc))) fail("CANDIDATE_MISSING_JOB_DOCUMENT", "candidate.sourceDocuments");
      }
      let verification = null;
      if (o.receiptVerification != null) {
        const verified = obj(o.receiptVerification, "receiptVerification");
        if (typeof verified.ok !== "boolean") fail("INVALID_BOOLEAN", "receiptVerification.ok");
        const payload = verified.ok ? obj(verified.payload, "receiptVerification.payload") : null;
        verification = {
          ok: verified.ok,
          core_output_sha256: payload ? sha(payload.coreOutputSha256, "receiptVerification.payload.coreOutputSha256") : null,
          manifest_digest: payload ? sha(payload.manifestDigest, "receiptVerification.payload.manifestDigest") : null,
        };
      }
      // job.jobId is supplied explicitly by the hook; the other job fields are the raw harness job row.
      // The row's manifestDigest is kept apart from the candidate and the verified payload.
      const row = {
        job_id: text(job.jobId, "job.jobId"),
        state: text(job.state, "job.state"),
        error_code: rowText(job.errorCode, "job.errorCode"),
        collection_id: rowText(job.collectionId, "job.collectionId"),
        manifest_digest: rowSha(job.manifestDigest, "job.manifestDigest"),
        document_ids: documentIds,
        candidate, verification,
      };
      return { ids, entry: row, apply() { for (const id of ids) st(id).compiles.push(row); } };
    },

    settlement(o) {
      const id = memberForDocument(o.documentId, "documentId");
      const row = {
        document_id: o.documentId,
        state: text(o.state, "state"),
        settled_credits: o.settledCredits === null ? null : units(o.settledCredits, "settledCredits"),
        reason_code: optText(o.reasonCode, "reasonCode"),
        settled_at: optText(o.settledAt, "settledAt"),
      };
      const previous = st(id).settlement;
      if (previous && previous.settled_at !== null && !same(previous, row)) fail("SETTLEMENT_CHANGED", "state");
      return { ids: [id], entry: row, apply() { st(id).settlement = row; } };
    },

    effect(o, context) {
      const id = memberForKey(o.fileKey, "fileKey");
      const effect = oneOf(o.effect, EFFECTS, "effect");
      if (typeof o.value !== "boolean") fail("INVALID_BOOLEAN", "value");
      // A charge is only ever derived from an actual final settlement row.
      if (effect === "charged" && o.value) fail("CHARGE_REQUIRES_SETTLEMENT_ROW", "value");
      // Absence of calls is not evidence: false needs a complete monitoring claim bound to this exact scope.
      if (!o.value && o.monitoring?.complete !== true) fail("FALSE_EFFECT_NEEDS_COMPLETE_MONITORING", "monitoring");
      const monitoring = o.monitoring == null ? null : monitoringOf(id, effect, context, o.monitoring);
      const previous = st(id).effects[effect];
      if (previous && previous.value !== o.value) fail("EFFECT_CONFLICT", "value");
      const row = { file_key: o.fileKey, effect, value: o.value, monitoring };
      return { ids: [id], entry: row, apply() { if (!previous) st(id).effects[effect] = row; } };
    },
  };

  /**
   * Every touched member must carry an authority binding equal to the hashed context. A whole-request
   * observation (no member) must still match at least one bound member; it never becomes a per-file fact.
   */
  function authorize(ids, context) {
    if (ids.length === 0) {
      if (!ownerBindings.some((b) => b.authority_binding !== null && same(b.authority_binding, context))) fail("CONTEXT_NOT_BOUND", "context");
      return;
    }
    for (const id of ids) {
      const authority = members.get(id).binding.authority_binding;
      if (authority === null) fail("AUTHORITY_UNBOUND", "context");
      if (!same(authority, context)) fail("CONTEXT_MISMATCH", "context");
    }
  }

  function accept(kind, observation) {
    try {
      if (journal.length >= MAX_JOURNAL) fail("JOURNAL_LIMIT", "journal");
      // Without the immutable run/commit binding no observation can ever become evidence.
      if (executionBinding === null) fail("UNBOUND_RUN", "execution_binding");
      const o = obj(observation, kind);
      const context = contextOf(o.context);
      const { ids, entry, apply } = parsers[kind](o, context);
      authorize(ids, context);
      apply();
      journal.push(copy({ seq: journal.length + 1, kind, member_ids: [...new Set(ids)].sort(), ...entry, context }));
      return { seq: journal.length };
    } catch (error) {
      const known = error instanceof ProducerInputError;
      rejectionCount += 1;
      if (rejections.length < MAX_LISTED_REJECTIONS) {
        rejections.push({ kind, code: known ? error.code : "UNEXPECTED_INPUT_SHAPE", field: known ? error.field : null });
      }
      throw known ? error : new ProducerInputError("UNEXPECTED_INPUT_SHAPE", kind);
    }
  }

  function compileFacts(s, notes) {
    let verified = null, failure = null;
    for (const row of s.compiles) {
      if (COMPILE_CANDIDATE_STATES.includes(row.state)) {
        if (!row.candidate || row.verification?.ok !== true) { notes.push("compile_candidate_without_verified_signed_receipt"); continue; }
        if (row.verification.core_output_sha256 !== row.candidate.core_output_sha256
          || row.verification.manifest_digest !== row.candidate.manifest_digest) { notes.push("compile_receipt_digest_mismatch"); continue; }
        // Job lineage: the observed job row digest must itself equal the candidate (and so the verified payload).
        if (row.manifest_digest === null) { notes.push("compile_job_manifest_digest_unobserved"); continue; }
        if (row.manifest_digest !== row.candidate.manifest_digest) { notes.push("compile_job_manifest_digest_mismatch"); continue; }
        if (s.versionKey === null) { notes.push("compile_member_version_key_unobserved"); continue; }
        // The candidate's document set is exact and unique (checked at record time); this member's entry must match.
        const own = row.candidate.source_documents.find((doc) => doc.document_id === s.documentId);
        if (!own || own.version_key !== s.versionKey) {
          notes.push("compile_candidate_not_bound_to_member_document_version"); continue;
        }
        verified = row;
      } else if (row.state === "failed" && row.error_code !== null) failure = row;
      else notes.push("compile_job_state_not_a_result");
    }
    return { verified, failure };
  }

  function project({ binding, state: s }) {
    const missing = [], conflicts = [], notes = [];
    if (s.fileKey === null) missing.push("verified_member_mapping");
    if (binding.authority_binding === null) missing.push("authority_binding");
    // An actual per-file external access decision is required before any projection, refusals included.
    if (s.access === null) missing.push("external_access_decision");
    const results = [];
    if (s.access?.decision === "denied") results.push(["refused", s.access.reason_code, "external_access_decision"]);
    if (s.qualification?.outcome === "refused") results.push(["refused", s.qualification.code, "qualification_reply"]);
    const triage = s.triage?.row ?? null;
    if (triage?.disposition === "exclude") results.push(["excluded", triage.reason, "triage_exclude"]);
    if (triage?.disposition === "needs_review") results.push(["pending", triage.reason, "triage_needs_review"]);
    if (triage?.disposition === "include") notes.push("triage_include_is_not_output");
    if (s.cdr?.outcome === "failed") results.push(["failed", s.cdr.failure_code, "cdr_failure"]);
    const compiled = compileFacts(s, notes);
    if (compiled.failure) results.push(["failed", compiled.failure.error_code, "compile_job_failed"]);
    if (compiled.verified) results.push(["output", compiled.verified.state, "verified_signed_compile"]);
    if (results.length === 0) missing.push("terminal_product_result");
    else if (new Set(results.map((r) => r[0])).size > 1) conflicts.push("multiple_terminal_results");
    else if (new Set(results.map((r) => r[1])).size > 1) conflicts.push("multiple_reasons_for_result");
    const [disposition, reasonCode] = results.length > 0 ? results[0] : [null, null];

    const effects = Object.fromEntries(EFFECTS.map((name) => [name, s.effects[name]?.value ?? null]));
    const settlement = s.settlement;
    const settledCharge = !!settlement && settlement.state !== "reserved" && settlement.settled_at !== null
      && settlement.settled_credits !== null && settlement.settled_credits > 0;
    if (settledCharge) {
      if (effects.charged === false) conflicts.push("settled_credits_contradict_monitored_no_charge");
      effects.charged = true;
    } else if (settlement) notes.push("settlement_row_is_not_charge_evidence");
    for (const name of EFFECTS) if (effects[name] === null) missing.push(`effect:${name}`);
    if ((disposition === "output" || disposition === "failed") && effects.processed === false) conflicts.push("stage_result_with_processed_false");
    if (disposition && disposition !== "output" && disposition !== "failed" && EFFECTS.some((name) => effects[name] === true)) {
      notes.push("activity_observed_for_non_stage_result");
    }

    let duplicateOf = null;
    if (triage?.exact_duplicate_of) {
      const target = byFileKey.get(triage.exact_duplicate_of);
      if (!target) missing.push("duplicate_target_mapping");
      else if (target === binding.id) conflicts.push("duplicate_of_self");
      else if (members.get(target).binding.source_sha256 !== binding.source_sha256) conflicts.push("duplicate_target_digest_differs");
      else duplicateOf = target;
    }

    const projected = missing.length === 0 && conflicts.length === 0;
    const stage = projected && (disposition === "output" || disposition === "failed")
      ? digestOf({ evidence_kind: evidenceKind, execution_binding: executionBinding, member: binding,
        journal: journal.filter((entry) => entry.member_ids.includes(binding.id)) }) : null;
    const record = projected ? {
      id: binding.id, disposition, reason_code: reasonCode,
      source_id: binding.source_id, source_version: binding.source_version,
      source_sha256: binding.source_sha256, acl_scope: binding.acl_scope,
      content_read: effects.content_read, transferred: effects.transferred,
      processed: effects.processed, charged: effects.charged,
      duplicate_of: duplicateOf,
      page_count: s.cdr?.ocr?.page_count ?? null,
      stage_receipt_sha256: stage,
    } : null;
    const diagnostic = {
      id: binding.id,
      owner_labels: { ...binding },
      observed_product_identity: {
        file_key: s.fileKey, document_id: s.documentId, mapping_basis: s.mappingBasis,
        sanitized_version_key: s.versionKey,
        triage_workspace_key: s.triage ? s.triage.scope.workspace_key : null,
        triage_source_id: s.triage ? s.triage.scope.source_id : null,
        triage_revision: triage ? triage.revision : null,
        triage_acl_observation_sha256: triage ? triage.acl_observation_sha256 : null,
      },
      facts: {
        quote: s.quote, approval: s.approval,
        confirm: { count: s.confirms.length, replay_count: Math.max(0, s.confirms.length - 1), last: s.confirms.at(-1) ?? null },
        triage: s.triage, qualification: s.qualification, access: s.access,
        cdr: s.cdr, cdr_replay_count: s.cdrReplays, compiles: s.compiles, settlement, effects: s.effects,
      },
      result_basis: results.map(([result, reason, basis]) => ({ result, reason, basis })),
      projected, missing, conflicts, notes,
    };
    return { record, diagnostic };
  }

  function produce(bindings) {
    // Supplied bindings may only restate the constructor binding; they never label or relabel a journal.
    if (bindings !== undefined && bindings !== null) {
      const supplied = executionBindingOf(bindings, "bindings");
      if (executionBinding === null || !same(supplied, executionBinding)) fail("RUN_BINDING_MISMATCH", "bindings");
    }
    const observed = journal.length > 0;
    const execution = {
      status: "NOT_RUN", evidence_kind: evidenceKind,
      run_id: null, foundation_commit: null, core_commit: null, stage_receipt_sha256: null,
    };
    const projections = [...members.values()].map(project)
      .sort((a, b) => (a.diagnostic.id < b.diagnostic.id ? -1 : a.diagnostic.id > b.diagnostic.id ? 1 : 0));
    if (observed) {
      // Recorders refuse an unbound run, so an observed journal always has the constructor binding.
      execution.run_id = executionBinding.run_id;
      execution.foundation_commit = executionBinding.foundation_commit;
      execution.core_commit = executionBinding.core_commit;
      execution.stage_receipt_sha256 = digestOf({
        evidence_kind: evidenceKind, execution_binding: executionBinding, members: ownerBindings, journal,
      });
      const complete = rejectionCount === 0 && projections.every((p) => p.record !== null);
      execution.status = complete ? "COMPLETED" : "PARTIAL";
    }
    const runtimeResults = {
      schema: RUNTIME_RESULTS_SCHEMA,
      execution,
      dispositions: observed ? projections.filter((p) => p.record).map((p) => p.record) : [],
    };
    const sidecar = {
      schema: SIDECAR_SCHEMA,
      evidence_kind: evidenceKind,
      contract_only: evidenceKind === "SYNTHETIC_CONTRACT_TEST",
      observations_authenticated: false,
      observation_source: "SUPPLIED_UNAUTHENTICATED_PENDING_RUNTIME_HOOK_REVIEW",
      actual_runtime_pass_claimed: false,
      qualification: "NOT_CUSTOMER_QUALIFIED",
      whole_G1_acceptance: "UNKNOWN",
      expected_case_match: "NOT_EVALUATED_BY_PRODUCER",
      structural_status: execution.status,
      identity_note: "source_id/source_version/acl_scope are fixture owner labels, not product IDs or revisions; observed product identities are listed separately. authority_binding is a caller-supplied fixture-to-runtime mapping assertion, not an authorization grant or proof.",
      missing_prerequisites: observed ? [] : ["runtime_observations"],
      journal_sha256: execution.stage_receipt_sha256,
      journal,
      members: projections.map((p) => p.diagnostic),
      rejections: { count: rejectionCount, listed: rejections, listed_complete: rejections.length === rejectionCount },
    };
    return copy({ runtimeResults, sidecar });
  }

  const recorder = (kind) => (observation) => accept(kind, observation);
  return Object.freeze({
    recordMapping: recorder("member_mapping"),
    recordQuote: recorder("quote"),
    recordApproval: recorder("approval"),
    recordConfirm: recorder("confirm"),
    recordTriage: recorder("triage"),
    recordQualification: recorder("qualification"),
    recordAccessDecision: recorder("access_decision"),
    recordCdrOcr: recorder("cdr_ocr"),
    recordCompile: recorder("compile"),
    recordSettlement: recorder("settlement"),
    recordEffect: recorder("effect"),
    produce,
  });
}
