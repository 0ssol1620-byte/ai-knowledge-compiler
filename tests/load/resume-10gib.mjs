import { createHash } from "node:crypto";
import {
  chmodSync,
  createReadStream,
  existsSync,
  readFileSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { open } from "node:fs/promises";
import { basename, dirname, isAbsolute, resolve, sep } from "node:path";

const CONFIRMATION = "NONPRODUCTION_LOAD_ONLY";
const GIB = 1024 ** 3;
const TOTAL_BYTES = 10 * GIB;
const INTERRUPT_AFTER_BYTES = 5 * GIB;
const FILE_COUNT = 10;

function fail(message) {
  throw new Error(message);
}

function requireEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) fail(`${name} is required`);
  return value;
}

function parsePhase() {
  const index = process.argv.indexOf("--phase");
  const value = index >= 0 ? process.argv[index + 1] : null;
  if (!new Set(["interrupt", "resume"]).has(value)) {
    fail("--phase must be interrupt or resume");
  }
  return value;
}

function guardedOrigin() {
  if (process.env.AKC_LOAD_CONFIRM !== CONFIRMATION) {
    fail(`AKC_LOAD_CONFIRM=${CONFIRMATION} is required`);
  }
  const origin = requireEnv("AKC_BASE_URL").replace(/\/$/, "");
  const parsed = new URL(origin);
  const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);
  const allowed = new Set(
    (process.env.AKC_ALLOWED_REMOTE_ORIGINS || "")
      .split(",")
      .map((item) => item.trim().replace(/\/$/, ""))
      .filter(Boolean),
  );
  if (
    !localHosts.has(parsed.hostname) &&
    (parsed.protocol !== "https:" ||
      process.env.AKC_ALLOW_REMOTE_SYNTHETIC !== "true" ||
      !allowed.has(origin))
  ) {
    fail(
      "remote resume load requires HTTPS, AKC_ALLOW_REMOTE_SYNTHETIC=true, " +
        "and an exact AKC_ALLOWED_REMOTE_ORIGINS match",
    );
  }
  if (parsed.pathname !== "/" || parsed.search || parsed.hash) {
    fail("AKC_BASE_URL must be an origin without a path, query, or fragment");
  }
  return origin;
}

function sha256Bytes(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

async function sha256File(path) {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(path)) digest.update(chunk);
  return digest.digest("hex");
}

function loadFixtureManifest(path) {
  const absolute = resolve(path);
  const raw = readFileSync(absolute);
  const value = JSON.parse(raw.toString("utf8"));
  if (
    value.schema_version !== "1.0.0" ||
    value.synthetic !== true ||
    value.customer_data !== false ||
    value.files?.length !== FILE_COUNT ||
    value.total_bytes !== TOTAL_BYTES
  ) {
    fail("10 GiB fixture manifest must describe ten synthetic 1 GiB files");
  }
  const root = dirname(absolute);
  const files = value.files.map((entry, index) => {
    if (
      typeof entry.path !== "string" ||
      isAbsolute(entry.path) ||
      entry.path.split(/[\\/]/).includes("..") ||
      typeof entry.relative_path !== "string" ||
      entry.relative_path.startsWith("/") ||
      entry.relative_path.split(/[\\/]/).includes("..") ||
      !entry.relative_path.endsWith(".txt") ||
      entry.size_bytes !== GIB ||
      !/^[0-9a-f]{64}$/.test(entry.sha256 || "") ||
      entry.content_type !== "text/plain"
    ) {
      fail(`fixture file ${index} is not a bounded synthetic 1 GiB entry`);
    }
    const sourcePath = resolve(root, entry.path);
    if (sourcePath !== root && !sourcePath.startsWith(`${root}${sep}`)) {
      fail(`fixture file ${index} escapes the manifest directory`);
    }
    const stats = statSync(sourcePath);
    if (!stats.isFile() || stats.size !== GIB) {
      fail(`fixture file ${index} does not exist at exactly 1 GiB`);
    }
    return { ...entry, source_path: sourcePath };
  });
  if (files.reduce((total, entry) => total + entry.size_bytes, 0) !== TOTAL_BYTES) {
    fail("fixture bytes do not total exactly 10 GiB");
  }
  if (
    new Set(files.map((entry) => entry.sha256)).size !== FILE_COUNT ||
    new Set(files.map((entry) => entry.relative_path.toLowerCase())).size !== FILE_COUNT
  ) {
    fail("10 GiB fixture files require unique digests and relative paths");
  }
  return { value, files, sha256: sha256Bytes(raw) };
}

function safeWriteJson(path, value) {
  const absolute = resolve(path);
  const temporary = `${absolute}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  renameSync(temporary, absolute);
  try {
    chmodSync(absolute, 0o600);
  } catch {
    // Windows ACLs are environment-owned; the file still contains no API token.
  }
}

function loadState(path) {
  if (!existsSync(path)) fail("resume state does not exist");
  const value = JSON.parse(readFileSync(path, "utf8"));
  if (value.schema_version !== "1.0.0") fail("resume state schema is unsupported");
  return value;
}

function absoluteUrl(origin, value) {
  return new URL(value, `${origin}/`).toString();
}

function allowedUploadUrl(origin, value) {
  const target = new URL(value, `${origin}/`);
  const allowed = new Set([
    new URL(origin).origin,
    ...(process.env.AKC_ALLOWED_UPLOAD_ORIGINS || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  ]);
  if (target.protocol !== "https:" && !["localhost", "127.0.0.1", "::1"].includes(target.hostname)) {
    fail("upload target must use HTTPS unless it is loopback");
  }
  if (!allowed.has(target.origin)) {
    fail(`upload target origin is not explicitly allowed: ${target.origin}`);
  }
  return target.toString();
}

function createClient(origin, token, runId) {
  async function json(path, options = {}) {
    const headers = {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(options.idempotency
        ? { "Idempotency-Key": `${runId}-${options.idempotency}` }
        : {}),
      ...(options.headers || {}),
    };
    const response = await fetch(absoluteUrl(origin, path), {
      method: options.method || "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      fail(`${options.method || "GET"} ${path} returned non-JSON HTTP ${response.status}`);
    }
    const payload = await response.json();
    const expected = options.expected || [200];
    if (!expected.includes(response.status)) {
      fail(
        `${options.method || "GET"} ${path} returned HTTP ${response.status}: ` +
          JSON.stringify(payload).slice(0, 1000),
      );
    }
    return payload;
  }
  return { json };
}

async function readPart(path, offset, length) {
  const handle = await open(path, "r");
  try {
    const buffer = Buffer.allocUnsafe(length);
    let consumed = 0;
    while (consumed < length) {
      const result = await handle.read(
        buffer,
        consumed,
        length - consumed,
        offset + consumed,
      );
      if (result.bytesRead === 0) fail("fixture ended before the declared part boundary");
      consumed += result.bytesRead;
    }
    return buffer;
  } finally {
    await handle.close();
  }
}

async function uploadSingle(origin, initiated, file) {
  const headers = {
    ...(initiated.headers || {}),
    "Content-Length": String(file.size_bytes),
  };
  const body = createReadStream(file.source_path);
  const response = await fetch(allowedUploadUrl(origin, initiated.upload_url), {
    method: "PUT",
    headers,
    body,
    duplex: "half",
  });
  if (![200, 201, 204].includes(response.status)) {
    fail(`single upload failed with HTTP ${response.status}`);
  }
  return [];
}

function normalizeEtag(value) {
  return String(value || "").trim().replace(/^"|"$/g, "").toLowerCase();
}

async function uploadMultipart(client, origin, initiated, file) {
  const plan = initiated.multipart;
  if (!plan || !Number.isInteger(plan.part_count) || !Number.isInteger(plan.part_size)) {
    fail("multipart initiation did not return a bounded plan");
  }
  let listed = await client.json(plan.list_parts_url);
  const uploaded = new Map(
    (listed.parts || []).map((part) => [Number(part.part_number), part]),
  );
  const missing = [];
  for (let number = 1; number <= plan.part_count; number += 1) {
    if (!uploaded.has(number)) missing.push(number);
  }
  for (let offset = 0; offset < missing.length; offset += plan.presign_batch_size) {
    const batch = missing.slice(offset, offset + plan.presign_batch_size);
    const signed = await client.json(plan.sign_parts_url, {
      method: "POST",
      body: { part_numbers: batch },
      idempotency: `sign-${initiated.upload_id}-${batch[0]}-${batch.at(-1)}`,
      expected: [200],
    });
    for (const target of signed.parts) {
      const partNumber = Number(target.part_number);
      const partOffset = (partNumber - 1) * plan.part_size;
      const partLength = Math.min(plan.part_size, file.size_bytes - partOffset);
      const body = await readPart(file.source_path, partOffset, partLength);
      const response = await fetch(allowedUploadUrl(origin, target.upload_url), {
        method: "PUT",
        headers: {
          ...(target.headers || {}),
          "Content-Length": String(partLength),
        },
        body,
      });
      if (![200, 201, 204].includes(response.status)) {
        fail(`multipart part ${partNumber} failed with HTTP ${response.status}`);
      }
      const etag = normalizeEtag(response.headers.get("etag"));
      if (!/^[0-9a-f]{32,128}$/.test(etag)) {
        fail(`multipart part ${partNumber} returned an invalid ETag`);
      }
    }
  }
  listed = await client.json(plan.list_parts_url);
  const parts = [...(listed.parts || [])]
    .sort((left, right) => left.part_number - right.part_number)
    .map((part) => ({
      part_number: Number(part.part_number),
      etag: normalizeEtag(part.etag),
    }));
  if (
    parts.length !== plan.part_count ||
    parts.some((part, index) => part.part_number !== index + 1)
  ) {
    fail("multipart resume did not recover a contiguous authoritative part list");
  }
  return parts;
}

async function uploadFile(client, origin, projectId, file, stateEntry, state, statePath) {
  const actualSha = await sha256File(file.source_path);
  if (actualSha !== file.sha256) fail(`fixture digest mismatch: ${file.relative_path}`);
  let initiated;
  if (stateEntry.upload_id) {
    initiated = await client.json(`/v1/uploads/${stateEntry.upload_id}`);
    initiated.upload_id = stateEntry.upload_id;
    if (initiated.status !== "completed" && initiated.method !== "MULTIPART") {
      fail("an interrupted single-PUT session has no reusable signed target");
    }
  } else {
    initiated = await client.json("/v1/uploads/initiate", {
      method: "POST",
      body: {
        project_id: projectId,
        filename: basename(file.relative_path),
        size: file.size_bytes,
        content_type: file.content_type,
        sha256: file.sha256,
      },
      idempotency: `init-${stateEntry.file_id}`,
      expected: [201],
    });
    Object.assign(stateEntry, {
      upload_id: initiated.upload_id,
      document_id: initiated.document_id,
    });
    safeWriteJson(statePath, state);
  }

  if (initiated.status === "completed") {
    if (!stateEntry.source_file_id) {
      fail("completed upload session lacks a persisted source-file receipt");
    }
    return stateEntry.source_file_id;
  }
  const parts =
    initiated.method === "MULTIPART"
      ? await uploadMultipart(client, origin, initiated, file)
      : await uploadSingle(origin, initiated, file);
  const completed = await client.json(`/v1/uploads/${initiated.upload_id}/complete`, {
    method: "POST",
    body: { sha256: file.sha256, parts },
    idempotency: `complete-${stateEntry.file_id}`,
    expected: [200],
  });
  stateEntry.source_file_id = completed.source_file_id;
  stateEntry.completed = true;
  safeWriteJson(statePath, state);
  return completed.source_file_id;
}

async function initialize(client, projectId, runId, fixture, statePath, origin) {
  const collection = await client.json("/v1/collections", {
    method: "POST",
    body: {
      project_id: projectId,
      name: `Synthetic 10 GiB resume ${runId}`,
      description: "Synthetic nonproduction interrupted upload; no customer data.",
      profile: { readiness_profile: "collection_resume_10gib" },
    },
    idempotency: "collection-create",
    expected: [201],
  });
  const source = await client.json(`/v1/collections/${collection.id}/sources/local`, {
    method: "POST",
    body: {
      display_name: "synthetic-10gib-resume",
      source_fingerprint: fixture.sha256.replace("sha256:", ""),
    },
    idempotency: "source-create",
    expected: [201],
  });
  const plan = await client.json(`/v1/collections/${collection.id}/files/plan`, {
    method: "POST",
    body: {
      source_root_id: source.id,
      files: fixture.files.map((file, index) => ({
        relative_path: file.relative_path,
        display_name: basename(file.relative_path),
        size_bytes: file.size_bytes,
        last_modified_ms: index,
        expected_mime: file.content_type,
        sha256: file.sha256,
        quick_fingerprint: `scale-${index}-${file.sha256.slice(0, 16)}`,
      })),
    },
    idempotency: "files-plan",
    expected: [201],
  });
  if (plan.files.length !== FILE_COUNT || plan.upload.total_bytes !== TOTAL_BYTES) {
    fail("server did not admit the exact ten-file 10 GiB collection manifest");
  }
  const state = {
    schema_version: "1.0.0",
    profile: "collection_resume_10gib",
    run_id: runId,
    origin,
    project_id: projectId,
    fixture_manifest_sha256: fixture.sha256,
    collection_id: collection.id,
    source_root_id: source.id,
    browser_resume_token: plan.browser_resume_token,
    phase: "uploading_before_interrupt",
    uploaded_bytes: 0,
    token_rotated: false,
    files: plan.files.map((planned, index) => ({
      file_id: planned.id,
      relative_path: fixture.files[index].relative_path,
      completed: false,
    })),
  };
  safeWriteJson(statePath, state);
  return state;
}

async function run() {
  const phase = parsePhase();
  const origin = guardedOrigin();
  const token = requireEnv("AKC_TEST_TOKEN");
  const projectId = requireEnv("AKC_TEST_PROJECT_ID");
  const runId = requireEnv("AKC_RUN_ID");
  if (!/^[A-Za-z0-9_-]{4,48}$/.test(runId)) fail("AKC_RUN_ID must be a bounded opaque ID");
  requireEnv("AKC_ALLOWED_UPLOAD_ORIGINS");
  if (process.env.AKC_CLEANUP_ON_SUCCESS !== "true") {
    fail("AKC_CLEANUP_ON_SUCCESS=true is required before this mutating profile starts");
  }
  const statePath = resolve(requireEnv("AKC_10GIB_STATE_PATH"));
  const observationPath = resolve(requireEnv("AKC_10GIB_OBSERVATION_PATH"));
  if (!existsSync(dirname(statePath)) || !statSync(dirname(statePath)).isDirectory()) {
    fail("resume state directory is missing");
  }
  if (
    !existsSync(dirname(observationPath)) ||
    !statSync(dirname(observationPath)).isDirectory()
  ) {
    fail("observation output directory is missing");
  }
  const fixture = loadFixtureManifest(requireEnv("AKC_10GIB_FIXTURE_MANIFEST"));
  const client = createClient(origin, token, runId);

  let state;
  if (phase === "interrupt") {
    if (existsSync(statePath)) fail("interrupt phase refuses to overwrite existing resume state");
    state = await initialize(client, projectId, runId, fixture, statePath, origin);
  } else {
    state = loadState(statePath);
    if (
      state.phase !== "interrupted" ||
      state.run_id !== runId ||
      state.origin !== origin ||
      state.project_id !== projectId ||
      state.fixture_manifest_sha256 !== fixture.sha256 ||
      state.uploaded_bytes !== INTERRUPT_AFTER_BYTES
    ) {
      fail("resume state does not bind the requested interrupted 10 GiB run");
    }
    const oldToken = state.browser_resume_token;
    const resumed = await client.json(
      `/v1/collections/${state.collection_id}/upload/control`,
      {
        method: "POST",
        body: { action: "resume", browser_resume_token: oldToken },
        idempotency: "resume-after-restart",
        expected: [200],
      },
    );
    if (
      resumed.collection.status !== "UPLOADING" ||
      !resumed.browser_resume_token ||
      resumed.browser_resume_token === oldToken
    ) {
      fail("browser resume token did not rotate into the uploading state");
    }
    state.browser_resume_token = resumed.browser_resume_token;
    state.token_rotated = true;
    state.phase = "resumed_after_restart";
    safeWriteJson(statePath, state);
  }

  const started = Date.now();
  for (let index = 0; index < fixture.files.length; index += 1) {
    const file = fixture.files[index];
    const stateEntry = state.files[index];
    if (stateEntry.completed) continue;
    const sourceFileId = await uploadFile(
      client,
      origin,
      projectId,
      file,
      stateEntry,
      state,
      statePath,
    );
    stateEntry.source_file_id = sourceFileId;
    state.uploaded_bytes += file.size_bytes;
    safeWriteJson(statePath, state);
    if (phase === "interrupt" && state.uploaded_bytes === INTERRUPT_AFTER_BYTES) {
      const paused = await client.json(
        `/v1/collections/${state.collection_id}/upload/control`,
        {
          method: "POST",
          body: { action: "pause" },
          idempotency: "pause-at-five-gib",
          expected: [200],
        },
      );
      if (paused.collection.status !== "PAUSED") fail("collection did not enter PAUSED");
      state.phase = "interrupted";
      state.interrupted_at = new Date().toISOString();
      safeWriteJson(statePath, state);
      console.log(
        JSON.stringify({
          status: "expected_interruption_complete",
          profile: state.profile,
          uploaded_bytes: state.uploaded_bytes,
          next_command: "node tests/load/resume-10gib.mjs --phase resume",
          production_slo_proven: false,
        }),
      );
      return;
    }
  }

  if (phase !== "resume" || state.uploaded_bytes !== TOTAL_BYTES || !state.token_rotated) {
    fail("resume phase did not complete the exact post-restart 10 GiB sequence");
  }
  const sourceFileIds = state.files.map((entry) => entry.source_file_id);
  if (
    sourceFileIds.some((value) => typeof value !== "string") ||
    new Set(sourceFileIds).size !== FILE_COUNT
  ) {
    fail("completed upload receipts do not bind ten unique source files");
  }
  const completed = await client.json(
    `/v1/collections/${state.collection_id}/upload/complete`,
    {
      method: "POST",
      body: {
        receipts: state.files.map((entry) => ({
          file_id: entry.file_id,
          outcome: "completed",
          source_file_id: entry.source_file_id,
        })),
      },
      idempotency: "collection-upload-complete",
      expected: [200],
    },
  );
  if (
    completed.upload.total_files !== FILE_COUNT ||
    completed.upload.total_bytes !== TOTAL_BYTES ||
    completed.upload.completed_files !== FILE_COUNT ||
    completed.upload.active_files !== 0
  ) {
    fail("server completion receipt does not prove exact 10 GiB recovery");
  }

  const cleanup = await client.json(`/v1/collections/${state.collection_id}`, {
    method: "DELETE",
    idempotency: "collection-cleanup",
    expected: [200, 202],
  });
  const cleanupDigest = sha256Bytes(Buffer.from(JSON.stringify(cleanup)));
  const observation = {
    schema_version: "1.0.0",
    profile: "collection_resume_10gib",
    nonproduction_only: true,
    production_slo_proven: false,
    fixture_manifest_sha256: fixture.sha256,
    total_files: FILE_COUNT,
    interrupted_after_bytes: INTERRUPT_AFTER_BYTES,
    resumed_completed_bytes: state.uploaded_bytes,
    browser_resume_token_rotated: state.token_rotated,
    duration_after_resume_ms: Date.now() - started,
    duplicate_documents: 0,
    cleanup_completed: true,
    cleanup_receipt_sha256: cleanupDigest,
    orphaned_multipart_uploads: "requires_object_store_inventory_evidence",
  };
  safeWriteJson(observationPath, observation);
  unlinkSync(statePath);
  console.log(
    JSON.stringify({
      status: "raw_observation_written",
      path: observationPath,
      production_slo_proven: false,
      release_gate_closed: false,
    }),
  );
}

await run();
