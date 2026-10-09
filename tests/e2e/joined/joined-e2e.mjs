/**
 * TAVONEL joined end-to-end proof, one synthetic pilot workspace on a disposable GitHub runner:
 *
 *   Chromium sign-in (GoTrue) -> workspace upload UI (capability -> signed PUT -> confirm)
 *   -> [simulated R2 event + queue] -> Foundation CDR worker handleQueue -> real CDR image + pinned clamd
 *   -> real CPU raster OCR -> ocr.json -> UI-enqueued compile job -> [simulated Vercel cron]
 *   -> Foundation compile worker -> Core Product Core v2 /v2/compile over HTTPS -> signed compile receipt
 *   -> candidate -> review + activate in the UI -> API key / MCP stdio / CLI answer citing the upload.
 *
 * Plus, in the same run: duplicate confirm / queue redelivery / compile re-enqueue cause no second
 * OCR, Core compile or charge; an EICAR source is refused by the real scanner before OCR; a Core
 * request whose signature fails and a Core reply whose receipt does not verify leave no candidate.
 *
 * Every hop is labelled real | simulated in the ledger (output/joined-e2e-ledger.json). Foundation code
 * is imported or executed from the Foundation checkout, never copied. All keys and secrets are created
 * in this process, live only in owned child environments, and are redacted from everything written.
 *
 * Run (see .github/workflows/joined-e2e.yml) from foundation/quarantine-sidecar/foundation-cdr-worker, under the outer
 * deadline that stops the whole process tree even when this process is blocked in a synchronous child:
 *   timeout --kill-after=<k>s <outer>s node <core>/tests/e2e/joined/deadline-supervisor.mjs --deadline-seconds <n> \
 *     --grace-seconds <g> --expect-stop-bound-seconds <s> --record <core>/output/joined-e2e-supervisor.json \
 *     -- node --import tsx <core>/tests/e2e/joined/joined-e2e.mjs
 * The workflow sizes <n> from the job start, so the always() artifact upload and stack stop keep a fixed reserve.
 *
 * The ledger is the redacted proof record. Every checkpoint before the final one records `success: false`; only the final
 * write carries the verdict, and a run whose ledger could not be written exits LEDGER_NOT_WRITTEN_EXIT_CODE with minimal,
 * structural evidence on stderr. On failure, failure-screenshot.png and failure-trace.zip are written beside the ledger as
 * separate artifacts; they are not redacted and may hold this run's synthetic documents, page contents and its disposable
 * (already dead) credentials.
 */
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { createHash, createPublicKey, generateKeyPairSync, randomBytes, randomUUID } from "node:crypto";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { s3Bucket, signV4 } from "./s3-bucket.mjs";

// >>> joined-diagnostics helpers
// Self-contained: only spawn from node:child_process, renameSync/rmSync/writeFileSync from node:fs, and globals.
// joined-diagnostics.test.mjs and the review fixtures evaluate exactly this block with those imports, so nothing in it may
// refer to anything else declared in this file.

/** The ledger's proof flags, fixed. Minimal evidence reports exactly these from `ledger.booleans` and nothing else. */
const PROOF_FLAGS = Object.freeze(["uploadViaUiVerified", "cdrClamavReal", "ocrReal", "coreCompileReal", "receiptSigned", "reviewActivateViaUi",
  "consumerCitesUploadedDoc", "duplicatesCauseNoSecondOcrCompileOrCharge", "malwareRefusedBeforeOcr", "coreSignatureFailureLeavesNoCandidate",
  "coreReceiptFailureLeavesNoCandidate"]);
/** Exit status of a run whose redacted ledger failed to reach disk at least once: never 0, and distinct from a failed journey (1). */
const LEDGER_NOT_WRITTEN_EXIT_CODE = 3;

class StageTimeoutError extends Error {
  constructor(stage, deadlineMs) {
    super(`${stage} did not finish within its ${deadlineMs} ms deadline`);
    this.name = "StageTimeoutError";
    this.stage = stage;
    this.deadlineMs = deadlineMs;
  }
}

/**
 * Settles as `operation` (a promise, or a function returning one) does, or rejects with StageTimeoutError once
 * `deadlineMs` has passed. The operation is not cancelled; its late settlement is consumed here, so a reply that
 * arrives after the deadline can never surface as an unhandled rejection.
 */
function withDeadline(stage, deadlineMs, operation) {
  if (!(Number.isFinite(deadlineMs) && deadlineMs > 0)) throw new RangeError(`${stage} needs a finite, positive deadline`);
  const work = new Promise(resolve => resolve(typeof operation === "function" ? operation() : operation));
  work.catch(() => {});
  let timer;
  const expired = new Promise((_, reject) => { timer = setTimeout(() => reject(new StageTimeoutError(stage, deadlineMs)), deadlineMs); });
  return Promise.race([work, expired]).finally(() => clearTimeout(timer));
}

/** Replaces `file` with one rename, so neither a reader nor a kill mid-write ever sees half a ledger. */
function writeFileAtomic(file, text) {
  const temporary = `${file}.${process.pid}.tmp`;
  try {
    writeFileSync(temporary, text);
    renameSync(temporary, file);
  } catch (error) {
    try { rmSync(temporary, { force: true }); } catch { /* the write or rename error is the one to report */ }
    throw error;
  }
}

/**
 * The shapes a structural value may take: harness-chosen stage and step names (lower-case, short), error class names
 * (letters only), errno-style codes (upper-case) and checkpoint reasons built from those. None of them can hold a hex
 * secret, a base64 key, a JWT, a URL or free text, so a value that does not match is withheld, never quoted.
 */
const STRUCTURAL = Object.freeze({
  stageOrStep: /^[a-z][a-z0-9-]{0,39}$/,
  errorName: /^[A-Z][A-Za-z]{0,39}$/,
  errorCode: /^[A-Z][A-Z0-9_]{0,47}$/,
  writeErrorCode: /^[A-Z][A-Za-z0-9_]{0,39}$/,
  checkpointReason: /^(?:hop|step-start|step-end|signal|failure|failure-detail|teardown|final|exit-watchdog)(?::(?:SIGINT|SIGTERM|[a-z][a-z0-9-]{0,39}(?:\/[a-z][a-z0-9-]{0,39})?))?$/,
});
const structural = (shape, value) => (value == null ? null : typeof value === "string" && STRUCTURAL[shape].test(value) ? value : "[withheld]");

/**
 * What stderr gets when the ledger cannot be written: a fixed set of keys, each filled from a structural allowlist, so no
 * message, observation, trace, screenshot or service-log content can reach it, whatever the ledger holds. A run whose
 * ledger is not on disk is not a success whatever it had proven, so `success` is always false here; `proof` reports the
 * fixed PROOF_FLAGS (true only where the ledger holds exactly `true`), never any other key of `ledger.booleans`.
 */
function minimalEvidence(ledger, checkpointFailure = null) {
  const { failure, cancelled } = ledger ?? {};
  return {
    kind: "tavonel-joined-e2e-minimal-evidence", ledgerWritten: false, success: false,
    stage: structural("stageOrStep", ledger?.stage), step: structural("stageOrStep", ledger?.step),
    failure: failure ? { name: structural("errorName", failure.name), code: structural("errorCode", failure.code),
      stage: structural("stageOrStep", failure.stage), step: structural("stageOrStep", failure.step) } : null,
    proof: Object.fromEntries(PROOF_FLAGS.map(flag => [flag, ledger?.booleans?.[flag] === true])),
    cancelled: cancelled ? { signal: ["SIGINT", "SIGTERM"].includes(cancelled.signal) ? cancelled.signal : "[withheld]",
      stage: structural("stageOrStep", cancelled.stage), step: structural("stageOrStep", cancelled.step) } : null,
    checkpoint: checkpointFailure ? { reason: structural("checkpointReason", checkpointFailure.reason),
      writeErrorCode: structural("writeErrorCode", checkpointFailure.writeErrorCode) } : null,
  };
}

class LedgerCheckpointError extends Error {
  constructor(reason, writeErrorCode, cause) {
    super(`ledger checkpoint ${reason} was not written (${writeErrorCode})`, { cause });
    this.name = "LedgerCheckpointError";
    this.code = "LEDGER_CHECKPOINT_FAILED";
    this.reason = reason;
    this.writeErrorCode = writeErrorCode;
  }
}

/**
 * A checkpoint writes the redacted ledger as it stands, atomically, and fails closed.
 *
 * Every write except `checkpoint(reason, { final: true })` records `success: false`, so no file on disk claims a success
 * the run can still lose (a cleanup that fails later, a later write that does not land); only the final write carries the
 * verdict. `ledger.lastCheckpoint` only ever names a write that reached disk.
 *
 * When a write fails, the checkpoint records the failure structurally in `ledger.checkpointFailures` and as an error in
 * `checkpoint.failures`, prints the minimal evidence line to stderr, calls `onFailure` (the harness sets
 * LEDGER_NOT_WRITTEN_EXIT_CODE there) and throws LedgerCheckpointError.
 *
 * `checkpoint.tryWrite(reason)` is only for the failure and teardown paths, which must go on stopping services after a
 * lost write: it returns false instead of throwing. The failure is not dropped there: it is already on stderr, stays in
 * `checkpoint.failures` and `ledger.checkpointFailures`, finalVerdict refuses success because of it, and concludeRun turns
 * it into LEDGER_NOT_WRITTEN_EXIT_CODE. Any error other than a lost write still throws.
 */
function ledgerCheckpointer({ ledger, file, redact, logError = console.error, onFailure = () => {} }) {
  const failures = [];
  const checkpoint = (reason, { final = false } = {}) => {
    const attempt = { reason, at: new Date().toISOString(), final };
    try {
      const snapshot = { ...ledger, success: final ? ledger.success === true : false, lastCheckpoint: attempt };
      writeFileAtomic(file, redact(JSON.stringify(snapshot, null, 2)));
    } catch (cause) {
      const failure = { reason: structural("checkpointReason", String(reason)), at: attempt.at,
        writeErrorCode: structural("writeErrorCode", String(cause?.code ?? cause?.name ?? "UNKNOWN")) };
      (ledger.checkpointFailures ??= []).push(failure);
      const error = new LedgerCheckpointError(failure.reason, failure.writeErrorCode, cause);
      failures.push(error);
      try {
        logError(`[joined-e2e] LEDGER NOT WRITTEN, minimal evidence: ${redact(JSON.stringify(minimalEvidence(ledger, failure)))}`);
      } catch { /* the failure is still recorded above and thrown below */ }
      try { onFailure(failure); } catch { /* the failure is still recorded above and thrown below */ }
      throw error;
    }
    ledger.lastCheckpoint = attempt;
    return attempt;
  };
  checkpoint.failures = failures;
  checkpoint.tryWrite = (reason, options) => {
    try {
      checkpoint(reason, options);
      return true;
    } catch (error) {
      if (error instanceof LedgerCheckpointError) return false;
      throw error;
    }
  };
  return checkpoint;
}

/**
 * Runs one bounded step of the current hop. The step's deadline, duration, outcome and (for a Playwright response)
 * HTTP status go into that hop's timeline entry and one CI log line, and the ledger is checkpointed as the step starts
 * and as it ends. A step that fails stays in `ledger.step`, so the failure record names it. A step whose start cannot be
 * checkpointed does not run, and a step that succeeded but cannot be checkpointed at its end fails; when the operation
 * itself failed, its error stays the one thrown and the checkpoint failure is already on stderr and in the ledger.
 */
function createStepRunner({ ledger, checkpoint, log = console.log, now = Date.now }) {
  return async (name, deadlineMs, operation) => {
    const current = ledger.timeline.at(-1);
    const label = `${current.stage}/${name}`;
    const started = now();
    const entry = { step: name, deadlineMs, startedAt: new Date(started).toISOString() };
    (current.steps ??= []).push(entry);
    ledger.step = name;
    try {
      checkpoint(`step-start:${label}`);
    } catch (error) {
      Object.assign(entry, { outcome: "not-started", errorName: String(error?.name ?? "Error"), durationMs: 0 });
      throw error;
    }
    let failed = false;
    try {
      const value = await withDeadline(label, deadlineMs, operation);
      if (typeof value?.status === "function") entry.httpStatus = value.status();
      entry.outcome = "ok";
      ledger.step = null;
      return value;
    } catch (error) {
      failed = true;
      entry.outcome = error instanceof StageTimeoutError ? "timeout" : "error";
      entry.errorName = String(error?.name ?? "Error");
      throw error;
    } finally {
      const ended = now();
      Object.assign(entry, { endedAt: new Date(ended).toISOString(), durationMs: ended - started });
      log(`[joined-e2e ${entry.endedAt}]     ${label} ${entry.outcome}${entry.httpStatus ? ` ${entry.httpStatus}` : ""} in ${entry.durationMs} ms (deadline ${deadlineMs} ms)`);
      if (!failed) checkpoint(`step-end:${label}`);
      else {
        try { checkpoint(`step-end:${label}`); } catch (ledgerError) { if (!(ledgerError instanceof LedgerCheckpointError)) throw ledgerError; }
      }
    }
  };
}

const SIGNAL_NUMBERS = { SIGINT: 2, SIGTERM: 15 };
/**
 * On SIGINT/SIGTERM: record the cancellation, checkpoint synchronously and leave a non-zero exit code. Each handler is
 * one-shot, and when no other listener owns the signal it is re-raised, so the default termination still happens:
 * the signal is observed, never swallowed, and a cancelled run never reads as a success. A checkpoint that cannot be
 * written does not stop the termination: its minimal evidence is already on stderr and the exit code stays non-zero.
 */
function installSignalCheckpoint({ ledger, checkpoint, processRef = process, log = console.error }) {
  for (const [signal, number] of Object.entries(SIGNAL_NUMBERS)) {
    processRef.once(signal, () => {
      ledger.cancelled ??= { signal, at: new Date().toISOString(), stage: ledger.stage ?? null, step: ledger.step ?? null };
      ledger.success = false;
      ledger.failure ??= { name: "Cancelled", code: signal, message: `received ${signal}`, stage: ledger.stage ?? null, step: ledger.step ?? null };
      let written = false;
      try { checkpoint(`signal:${signal}`); written = true; } catch { /* reported by the checkpointer; terminate regardless */ }
      log(`[joined-e2e] received ${signal} at ${ledger.stage ?? "start"}${ledger.step ? `/${ledger.step}` : ""}; ledger ${written ? "checkpointed" : "NOT written"}`);
      processRef.exitCode = 128 + number;
      if (processRef.listenerCount(signal) === 0) processRef.kill(processRef.pid, signal);
    });
  }
}

/** A pending wait that rejects after its owner gave up must not kill the run before the ledger is written; it is recorded. */
function recordUnhandledRejections({ ledger, redact, processRef = process, log = console.error }) {
  ledger.unhandledRejections ??= [];
  processRef.on("unhandledRejection", reason => {
    const text = redact(String(reason?.stack ?? reason)).slice(0, 2000);
    ledger.unhandledRejections.push(text);
    log(`[joined-e2e] unhandled rejection recorded: ${text.split("\n")[0]}`);
  });
}

/**
 * Runs a control-plane command (docker logs, docker rm, rm -rf) as an asynchronous child under a hard deadline: SIGTERM at
 * `timeoutMs`, SIGKILL `graceMs` later, and the promise rejects with StageTimeoutError no later than `timeoutMs + 2 * graceMs`
 * even if the child never goes away (it is then unref'd, so a process that cannot be reaped never holds this one open).
 * Unlike execFileSync it never blocks the event loop, so step deadlines and signal checkpoints keep working while it runs.
 * Resolves `{ stdout, stderr }` on exit 0; otherwise rejects with a CommandFailedError carrying the exit status and the
 * tail of stderr. A caller that wraps it in its own deadline must allow more than `timeoutMs + 2 * graceMs`.
 */
function runBounded(label, command, args, { timeoutMs, graceMs = 2_000, env, cwd, maxBytes = 64 * 1024 * 1024 } = {}) {
  if (!(Number.isFinite(timeoutMs) && timeoutMs > 0)) throw new RangeError(`${label} needs a finite, positive deadline`);
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { env, cwd, stdio: ["ignore", "pipe", "pipe"] });
    const chunks = { stdout: [], stderr: [] };
    const timers = [];
    let kept = 0, timedOut = false, settled = false;
    const settle = (finish, value) => {
      if (settled) return;
      settled = true;
      for (const timer of timers) clearTimeout(timer);
      child.stdout?.destroy();
      child.stderr?.destroy();
      finish(value);
    };
    for (const name of ["stdout", "stderr"]) {
      child[name].on("data", chunk => { if (kept < maxBytes) { chunks[name].push(chunk); kept += chunk.length; } });
    }
    timers.push(setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
      timers.push(setTimeout(() => {
        child.kill("SIGKILL");
        timers.push(setTimeout(() => { child.unref(); settle(reject, new StageTimeoutError(label, timeoutMs)); }, graceMs));
      }, graceMs));
    }, timeoutMs));
    child.once("error", error => settle(reject, error));
    child.once("close", (code, signal) => {
      if (timedOut) { settle(reject, new StageTimeoutError(label, timeoutMs)); return; }
      const stdout = Buffer.concat(chunks.stdout).toString("utf8"), stderr = Buffer.concat(chunks.stderr).toString("utf8");
      if (code === 0) { settle(resolve, { stdout, stderr }); return; }
      settle(reject, Object.assign(new Error(`${label} exited with ${code ?? signal}`), { name: "CommandFailedError", exitCode: code, signal, stderr: stderr.slice(-2000) }));
    });
  });
}

/** Stops accepting connections, drops the open ones and settles once the server has closed. Bound it with a deadline. */
function closeServer(server) {
  return new Promise((resolve, reject) => {
    server.close(error => (error && error.code !== "ERR_SERVER_NOT_RUNNING" ? reject(error) : resolve()));
    server.closeAllConnections?.();
  });
}

/** Keeps every accepted socket of `server`, so a close that overran can destroy what it was waiting for. */
function trackConnections(server) {
  const open = new Set();
  server.on("connection", socket => { open.add(socket); socket.once("close", () => open.delete(socket)); });
  return { get size() { return open.size; }, destroyAll() { for (const socket of open) socket.destroy(); open.clear(); } };
}

/** Keep only ordinary response-framing headers in confirm diagnostics. */
function safeConfirmHeaderEvidence(headers) {
  const evidence = {};
  for (const name of ["content-type", "content-length", "transfer-encoding"]) {
    const value = headers?.[name];
    if (typeof value === "string" && value.length <= 128) evidence[name] = value;
  }
  return evidence;
}

/** Observe only stream lifecycle and byte counts; never retain or log response bytes. */
function observeConfirmResponseBodies(upstream, downstream, record) {
  let bytes = 0;
  upstream.on("data", chunk => { bytes += chunk.length; record({ side: "upstream", phase: "data", bytes }); });
  upstream.once("end", () => record({ side: "upstream", phase: "end", bytes }));
  upstream.once("aborted", () => record({ side: "upstream", phase: "aborted", bytes }));
  upstream.once("error", () => record({ side: "upstream", phase: "error", bytes }));
  downstream.once("finish", () => record({ side: "gateway", phase: "finish", bytes }));
  downstream.once("close", () => record({ side: "gateway", phase: "close", bytes, writableFinished: downstream.writableFinished }));
  downstream.once("error", () => record({ side: "gateway", phase: "error", bytes }));
}

/**
 * The abort of a server close that overran: destroys every socket it still holds, which lets the pending close finish,
 * and unrefs the listener so nothing it holds can keep this process alive.
 */
function abortServer(server, connections) {
  connections.destroyAll();
  server.unref();
  return true;
}

/**
 * SIGKILLs `pid` and, where it leads one (Playwright starts Chromium detached, in a group of its own), its whole process
 * group: renderer, GPU and zygote processes go with it. Returns whether any signal was delivered.
 */
function killProcessGroup(pid) {
  if (!(Number.isInteger(pid) && pid > 0)) return false;
  let delivered = false;
  if (process.platform !== "win32") {
    try { process.kill(-pid, "SIGKILL"); delivered = true; } catch { /* not a group leader, or already gone */ }
  }
  try { process.kill(pid, "SIGKILL"); delivered = true; } catch { /* already gone */ }
  return delivered;
}

/**
 * Runs each cleanup task in order under its own deadline, whatever the others did. A deadline alone stops nothing, so a
 * task that throws or overruns gets its `abort` run at once: that is what actually stops the operation (SIGKILL the
 * browser's process group or a child's tree, destroy a server's sockets), so it can neither keep running nor keep this
 * process alive. The outcome, and whether the abort delivered, go into `ledger.cleanup` and the log. Returns whether every
 * task finished cleanly; it never sets `ledger.success` (finalVerdict reads `ledger.cleanup`).
 */
async function runCleanup(ledger, tasks, { log = console.error, redact = String, now = Date.now } = {}) {
  ledger.cleanup ??= [];
  let clean = true;
  for (const { name, deadlineMs, run, abort } of tasks) {
    const started = now();
    const entry = { task: name, deadlineMs };
    try {
      await withDeadline(`cleanup/${name}`, deadlineMs, run);
      entry.outcome = "ok";
    } catch (error) {
      clean = false;
      entry.outcome = error instanceof StageTimeoutError ? "timeout" : "error";
      entry.errorName = structural("errorName", String(error?.name ?? "Error"));
      if (typeof error?.exitCode === "number") entry.exitCode = error.exitCode;
      if (abort) {
        try { entry.aborted = abort() !== false; } catch (abortError) {
          entry.aborted = false;
          entry.abortError = structural("errorName", String(abortError?.name ?? "Error"));
        }
      }
      log(`[joined-e2e] cleanup ${name} ${entry.outcome}${abort ? ` (abort ${entry.aborted ? "delivered" : "FAILED"})` : ""}: ${redact(String(error?.message ?? error)).slice(0, 400)}`);
    }
    entry.durationMs = now() - started;
    ledger.cleanup.push(entry);
  }
  return clean;
}

/** Only a journey that proved everything, was not cancelled, cleaned up and kept every checkpoint on disk is a success. */
function finalVerdict(ledger) {
  return ledger.success === true && !ledger.cancelled && (ledger.cleanup ?? []).every(entry => entry.outcome === "ok")
    && !((ledger.checkpointFailures ?? []).length > 0);
}

/**
 * The end of a run, fail-closed: the verdict, the one write that may carry it, and the exit code. A lost ledger write at
 * any point of the run (this one included) makes the exit code LEDGER_NOT_WRITTEN_EXIT_CODE; a run that is not a success
 * never exits 0. Returns whether the final ledger reached disk. The caller then lets the process exit on its own.
 */
function concludeRun(ledger, checkpoint, processRef = process) {
  ledger.success = finalVerdict(ledger);
  const written = checkpoint.tryWrite("final", { final: true });
  if (!written) ledger.success = false;
  if (checkpoint.failures.length > 0) processRef.exitCode = LEDGER_NOT_WRITTEN_EXIT_CODE;
  else if (!ledger.success) processRef.exitCode = processRef.exitCode || 1;
  return written;
}
// <<< joined-diagnostics helpers

// ---------------------------------------------------------------------------------------------
// Preconditions: disposable GitHub-hosted Linux runner only.
// ---------------------------------------------------------------------------------------------
assert.equal(process.platform, "linux", "The joined proof runs only on the disposable Linux runner");
assert.equal(process.env.GITHUB_ACTIONS, "true", "The joined proof runs only in GitHub Actions");
assert.equal(process.env.RUNNER_ENVIRONMENT, "github-hosted", "The joined proof runs only on a GitHub-hosted runner");
const required = name => { const value = process.env[name]; assert.ok(value, `${name} is required`); return value; };
const FOUNDATION = realpathSync(required("TAVONEL_JOINED_FOUNDATION_DIR"));
const CORE = path.resolve(import.meta.dirname, "../../..");
const nextRoot = path.join(FOUNDATION, "nextjs");
const runnerTemp = realpathSync(required("RUNNER_TEMP"));
const statusFile = realpathSync(required("TAVONEL_AUTH_STACK_STATUS"));
assert.equal(path.dirname(statusFile), runnerTemp, "Only the workflow-generated local stack status file is accepted");
const corePython = required("TAVONEL_JOINED_CORE_PYTHON");
const ocrPython = required("TAVONEL_JOINED_OCR_PYTHON");
const cdrImage = required("TAVONEL_JOINED_CDR_IMAGE");
const output = path.resolve(CORE, "output/joined-e2e-ledger.json");
mkdirSync(path.dirname(output), { recursive: true });

const fromFoundation = relative => import(pathToFileURL(path.join(FOUNDATION, relative)).href);
const { validateDisposableAuthStack, authGatewayService } = await fromFoundation("nextjs/scripts/journey/real-auth-ci-contract.mjs");
const { withLocalStorage } = await fromFoundation("nextjs/scripts/journey/local-storage-journey.mjs");
const { routeLocalStorageTransport, storageHost } = await fromFoundation("nextjs/scripts/journey/local-next-browser-journey.mjs");
const { stopOwnedChild } = await fromFoundation("nextjs/scripts/journey/stop-owned-child.mjs");
const { evaluateCustomerDataGate } = await fromFoundation("shared/customerDataGate.ts");
const { customerDataPreconditions } = await fromFoundation("shared/uskcEnums.ts");
const { handleQueue } = await fromFoundation("quarantine-sidecar/foundation-cdr-worker/src/index.ts");
const { verifyCompileReceipt } = await fromFoundation("nextjs/lib/compile-receipt-signing.ts");
const { readExportTrustStoreEnv } = await fromFoundation("nextjs/lib/export-signing.ts");
const { deriveFileKey, newAttemptKey, approvedSourceIdempotencyKey, intakeManifestDigest } = await fromFoundation("nextjs/lib/intake-approval.ts");
const { quoteIntakeManifest, intakePricingFingerprint } = await fromFoundation("nextjs/lib/usage-pricing.ts");

const stack = validateDisposableAuthStack(JSON.parse(readFileSync(statusFile, "utf8")), process.env);
// The few synchronous commands left are short and capped with SIGKILL; the outer deadline supervisor stops this process
// tree if one of them still never returns.
const git = dir => execFileSync("git", ["-C", dir, "rev-parse", "HEAD"], { encoding: "utf8", timeout: 30_000, killSignal: "SIGKILL" }).trim();
const sha256 = body => createHash("sha256").update(body).digest("hex");

// ---------------------------------------------------------------------------------------------
// Identity, secrets and the ledger. Secrets never leave process memory and owned child envs.
// ---------------------------------------------------------------------------------------------
const owner = randomUUID();
const workspace = `pilot-${owner.replace(/-/g, "").slice(0, 16)}`;
const email = `joined-e2e-${owner.slice(0, 8)}@journey.invalid`;
const password = randomBytes(32).toString("base64url");
const origin = "https://127.0.0.1:54443", coreOrigin = "https://127.0.0.1:54444", nextPort = 3100;
const secrets = {
  core: randomBytes(32).toString("hex"), worker: randomBytes(32).toString("hex"), settlement: randomBytes(32).toString("hex"),
  cdr: randomBytes(32).toString("hex"), ocr: randomBytes(32).toString("hex"),
};
const coreSha = git(CORE), foundationSha = git(FOUNDATION);
// Synthetic, labelled: bound to this Core checkout, never a released Core image digest.
const coreReleaseDigest = `sha256:${sha256(`tavonel-joined-e2e-synthetic-core-release:${coreSha}`)}`;
const signingPair = generateKeyPairSync("ed25519");
const signingSpki = createPublicKey(signingPair.privateKey).export({ format: "der", type: "spki" });
const signingKeyId = `joined-e2e-${randomBytes(4).toString("hex")}`;
const signingEnv = {
  TAVONEL_EXPORT_SIGNING_KEY_ID: signingKeyId,
  TAVONEL_EXPORT_SIGNING_PRIVATE_KEY_PKCS8_DER_B64: signingPair.privateKey.export({ format: "der", type: "pkcs8" }).toString("base64"),
  TAVONEL_EXPORT_SIGNING_TRUST_STORE_JSON: JSON.stringify({
    schemaVersion: "tavonel.export_trust.v2", minimumSignatureVersion: 2, activeKeyId: signingKeyId,
    keys: [{ keyId: signingKeyId, keyVersion: 1, algorithm: "Ed25519", status: "active",
      notBefore: new Date(Date.now() - 3_600_000).toISOString(), expiresAt: new Date(Date.now() + 6 * 3_600_000).toISOString(),
      publicKeySpkiDerBase64: signingSpki.toString("base64"), publicKeySpkiSha256: `sha256:${sha256(signingSpki)}` }],
  }),
};
let consumerSecret = "", storageSecret = "";
const redact = value => [password, stack.anon, stack.service, storageSecret, consumerSecret, signingEnv.TAVONEL_EXPORT_SIGNING_PRIVATE_KEY_PKCS8_DER_B64, ...Object.values(secrets)]
  .filter(Boolean).reduce((text, secret) => text.replaceAll(secret, "[redacted]"), String(value))
  .replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, "[redacted JWT]").replace(/tvnl_live_[A-Za-z0-9_-]+/g, "[redacted API key]")
  .replace(/(X-Amz-(?:Signature|Credential)=)[^&\s"]+/gi, "$1[redacted]");

const ledger = {
  kind: "tavonel-joined-e2e", success: false, generatedAt: new Date().toISOString(),
  harnessSha256: sha256(readFileSync(import.meta.filename)),
  checkout: { coreSha, foundationSha, foundationRef: process.env.TAVONEL_JOINED_FOUNDATION_REF ?? null,
    workflowRunId: process.env.GITHUB_RUN_ID ?? null, workflowSha: process.env.GITHUB_SHA ?? null },
  booleans: { uploadViaUiVerified: false, cdrClamavReal: false, ocrReal: false, coreCompileReal: false, receiptSigned: false,
    reviewActivateViaUi: false, consumerCitesUploadedDoc: false, duplicatesCauseNoSecondOcrCompileOrCharge: false,
    malwareRefusedBeforeOcr: false, coreSignatureFailureLeavesNoCandidate: false, coreReceiptFailureLeavesNoCandidate: false },
  hops: [
    { hop: "Auth: password sign-in and session", label: "real", detail: "GoTrue from the disposable `supabase start` stack; Chromium holds the session" },
    { hop: "Next application", label: "real", detail: "Foundation `next build` + `next start` (production mode) from the Foundation checkout" },
    { hop: "TLS front door", label: "simulated", detail: "Harness HTTPS gateway 127.0.0.1:54443 (self-signed, NODE_EXTRA_CA_CERTS) in front of Next, GoTrue/PostgREST and S3; Vercel's edge is not exercised" },
    { hop: "Upload UI: triage availability -> legacy approval -> capability -> signed PUT -> confirm", label: "real", detail: "Chromium clicks 'Review sources before processing' and the real Next triage route answers 404 INTAKE_TRIAGE_DISABLED (code-owned rollout off) without any upload; Chromium then explicitly approves the displayed full-scope maximum with the legacy 'Approve maximum & upload'; Next signs the PUT; Chromium uploads the bytes" },
    { hop: "Object storage (R2)", label: "simulated", detail: "SeaweedFS 4.48 S3, checksum-pinned, behind the R2 host name; not Cloudflare R2" },
    { hop: "Storage CORS", label: "simulated", detail: "CORS response headers are added by the harness gateway; they are not SeaweedFS or R2 CORS configuration" },
    { hop: "R2 object-created event + Cloudflare Queue delivery", label: "simulated", detail: "Harness builds the R2 event-notification message after the browser's confirm and calls the exported handleQueue" },
    { hop: "R2 binding of the CDR worker", label: "simulated", detail: "S3-backed get/list/put adapter (tests/e2e/joined/s3-bucket.mjs) against the same SeaweedFS" },
    { hop: "CDR worker logic", label: "real", detail: "Foundation quarantine-sidecar/foundation-cdr-worker/src handleQueue, executed in Node via tsx, not in workerd" },
    { hop: "CDR service + ClamAV", label: "real", detail: "cdr-cloudrun image built from the Foundation checkout; clamd service container pinned by digest" },
    { hop: "OCR", label: "real", detail: "workers/foundation-ocr-cpu-raster on CPU with digest-checked RapidOCR models, HMAC-signed by the worker" },
    { hop: "Compute settlement callback", label: "real", detail: "Worker -> Next /api/internal/billing/settle (HMAC) -> SQL ledger" },
    { hop: "Compile enqueue", label: "real", detail: "The workspace UI posts /api/compile-jobs after the upload" },
    { hop: "Compile worker trigger (Vercel cron)", label: "simulated", detail: "Harness POSTs /api/internal/jobs/run with an ephemeral FOUNDATION_WORKER_SECRET" },
    { hop: "Core /v2/compile", label: "real", detail: "Core Product Core v2 under uvicorn from the Core checkout, HMAC-verified, over HTTPS via harness gateway 127.0.0.1:54444" },
    { hop: "Core customer-data switch", label: "simulated", detail: "tests/e2e/joined/core_synthetic_app.py sets allow_customer_data=True for this synthetic run only; production default unchanged" },
    { hop: "Core release digest", label: "simulated", detail: "sha256 of a label + the Core checkout SHA, not a released image digest" },
    { hop: "Compile receipt signing + audit", label: "real", detail: "Foundation signer with an ephemeral Ed25519 key and trust store; audit row in enterprise_audit_events" },
    { hop: "Customer-data gate + enterprise tenancy", label: "simulated", detail: "Fixture SQL rows in the disposable DB: a 17-precondition gate receipt whose evidence names this fixture, and bootstrap_enterprise_for_user" },
    { hop: "Review + activate", label: "real", detail: "Chromium clicks Accept and Activate reviewed candidate on /workspace/review" },
    { hop: "Consumer reads", label: "real", detail: "Owner session, issued API key, shipped MCP stdio server and shipped CLI from the Foundation checkout, behind a loopback egress guard" },
  ],
  fixtures: [], assertions: [], observations: {},
  notClaimed: ["production R2, Queues, workerd or Vercel", "production identity, keys or customer data", "retrieval quality or OCR accuracy beyond the asserted phrase",
    "a released Core image", "production legal, encryption or operator evidence", "SeaweedFS or R2 CORS configuration"],
};
assert.deepEqual(Object.keys(ledger.booleans), [...PROOF_FLAGS], "minimal evidence reports exactly the ledger's proof flags");
function check(name, actual, expected) { assert.deepEqual(actual, expected, name); ledger.assertions.push(name); }
const observe = (key, value) => { ledger.observations[key] = value; };
ledger.timeline = [];
// Checkpointed atomically at every hop and step boundary, on failure and on SIGINT/SIGTERM, so a run that is killed
// or runs out of time still leaves a redacted ledger that says how far it got. A checkpoint that cannot be written fails
// the run: minimal evidence goes to stderr and the exit code is LEDGER_NOT_WRITTEN_EXIT_CODE.
const checkpoint = ledgerCheckpointer({ ledger, file: output, redact, onFailure: () => { process.exitCode = LEDGER_NOT_WRITTEN_EXIT_CODE; } });
const step = createStepRunner({ ledger, checkpoint });
installSignalCheckpoint({ ledger, checkpoint });
const runStartedMs = Date.parse(ledger.generatedAt);
/** One line per hop in the CI log, and the same timeline in the ledger, so a failure shows how far the run got. */
function hop(stage) {
  const at = new Date().toISOString();
  const previous = ledger.timeline.at(-1);
  if (previous && !previous.endedAt) Object.assign(previous, { endedAt: at, durationMs: Date.parse(at) - Date.parse(previous.startedAt) });
  ledger.stage = stage;
  ledger.step = null;
  if (stage !== "done") ledger.timeline.push({ stage, startedAt: at });
  console.log(`[joined-e2e ${at}] >>> ${stage} (+${Math.round((Date.parse(at) - runStartedMs) / 1000)} s)`);
  checkpoint(`hop:${stage}`);
}
// A pending Playwright wait rejects once the browser closes during cleanup. That must never kill the
// process before the ledger is written; it is recorded instead.
recordUnhandledRejections({ ledger, redact });

// ---------------------------------------------------------------------------------------------
// Small process, SQL and HTTP helpers.
// ---------------------------------------------------------------------------------------------
const allowed = new Set(["PATH", "HOME", "TMP", "TEMP", "LANG", "LC_ALL"]);
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => allowed.has(key.toUpperCase())));
const sql = statement => execFileSync("psql", [stack.db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", statement], { env, encoding: "utf8", timeout: 15_000, killSignal: "SIGKILL" }).trim();
/** pid and parent pid of every process, from /proc (this harness runs only on Linux). */
function processTable() {
  const rows = [];
  for (const name of readdirSync("/proc")) {
    if (!/^\d+$/.test(name)) continue;
    try {
      const stat = readFileSync(`/proc/${name}/stat`, "utf8");
      rows.push({ pid: Number(name), ppid: Number(stat.slice(stat.lastIndexOf(")") + 2).split(" ")[1]) });
    } catch { /* exited while listed */ }
  }
  return rows;
}
const childPidsOf = (parentPid, table = processTable()) => table.filter(row => row.ppid === parentPid).map(row => row.pid);
function descendantPidsOf(rootPid, table = processTable()) {
  const found = [], queue = [rootPid];
  while (queue.length) for (const pid of childPidsOf(queue.shift(), table)) if (!found.includes(pid)) { found.push(pid); queue.push(pid); }
  return found;
}
/** The abort of an owned child that did not stop in time: SIGKILL it and everything it started (read before the kill). */
function killOwnedTree(child) {
  const targets = child.pid ? [child.pid, ...descendantPidsOf(child.pid)] : [];
  let delivered = false;
  for (const pid of targets) { try { process.kill(pid, "SIGKILL"); delivered = true; } catch { /* already gone */ } }
  return delivered;
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitUntil(label, probe, tries = 240, delay = 500) {
  for (let i = 0; i < tries; i++) { try { if (await probe()) return; } catch { /* still starting */ } await sleep(delay); }
  throw new Error(`${label} did not become ready`);
}
async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address(); await new Promise(resolve => server.close(resolve)); return port;
}
const owned = [];
function start(label, command, args, options) {
  const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
  const tail = [];
  for (const stream of [child.stdout, child.stderr]) {
    stream.setEncoding("utf8");
    stream.on("data", chunk => { for (const line of chunk.split("\n")) if (line.trim()) { tail.push(redact(line).slice(0, 400)); if (tail.length > 4000) tail.shift(); } });
  }
  owned.push({ label, child, tail });
  return child;
}
const readBody = stream => new Promise((resolve, reject) => { const chunks = []; stream.on("data", c => chunks.push(c)); stream.on("end", () => resolve(Buffer.concat(chunks))); stream.on("error", reject); });
async function api(resource, body, bearer = stack.service, method = body ? "POST" : "GET") {
  const response = await fetch(`${stack.api}${resource}`, { method, headers: { apikey: stack.anon, authorization: `Bearer ${bearer}`, "content-type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(15_000) });
  return { status: response.status, body: await response.json().catch(() => null) };
}
async function ownerToken() {
  const login = await api("/auth/v1/token?grant_type=password", { email, password }, stack.anon);
  assert.equal(login.status, 200, "GoTrue password login for the fixture owner");
  return login.body.access_token;
}

/** One synthetic, ASCII-only PDF with Helvetica text (no customer content). Same layout as the Foundation CDR fixtures. */
function textPdf(lines) {
  const content = lines.map((line, index) => `BT /F1 28 Tf 72 ${700 - index * 48} Td (${line}) Tj ET`).join("\n");
  return assemblePdf(["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", `<< /Length ${content.length} >>\nstream\n${content}\nendstream`]);
}
/** EICAR (assembled at run time) as an uncompressed embedded file, the shape the pinned clamd is qualified to detect. */
function eicarPdf() {
  const eicar = ["X5O!P%@AP[4\\PZX54(P^)7CC)7}$", "EICAR-STANDARD-ANTIVIRUS-", "TEST-FILE!$H+H*"].join("");
  return assemblePdf(["<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles << /Names [(eicar.txt) 6 0 R] >> >> >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>",
    "<< /Length 8 >>\nstream\n0 0 m S\nendstream", `<< /Type /EmbeddedFile /Length ${eicar.length} >>\nstream\n${eicar}\nendstream`,
    "<< /Type /Filespec /F (eicar.txt) /EF << /F 5 0 R >> >>"]);
}
function assemblePdf(objects) {
  let pdf = "%PDF-1.4\n"; const offsets = [];
  objects.forEach((body, index) => { offsets.push(pdf.length); pdf += `${index + 1} 0 obj\n${body}\nendobj\n`; });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map(o => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(pdf, "latin1");
}

// The phrase the consumer answer must cite. It must not exist in any Foundation fixture this job could have fed in.
const PHRASE = /73\s*days/i;
const docs = {
  ui: { name: "joined-e2e-archive-policy.pdf", bytes: textPdf(["Archive retention is 73 days.", "Joined harness policy record."]) },
  signature: { name: "joined-e2e-escalation.pdf", bytes: textPdf(["Escalation window is 19 hours."]) },
  receipt: { name: "joined-e2e-cadence.pdf", bytes: textPdf(["Review cadence is 11 weeks."]) },
  malware: { name: "joined-e2e-eicar.pdf", bytes: eicarPdf() },
};
const question = "What is the archive retention period?";

const root = mkdtempSync(path.join(tmpdir(), "tavonel-joined-e2e-"));
const browserEvents = [];
const confirmBodyTransport = [];
let browser, context, page, cdrContainer = null;
// Chromium's pids (each leads its own process group) and every listener the harness opens, so teardown can stop them
// for real when a close overruns, rather than only stop waiting for it.
let browserPids = [];
const servers = [];
const ownServer = (name, server) => { servers.push({ name, server, connections: trackConnections(server) }); return server; };
const outputDir = path.dirname(output);
try {
  // Fixture provenance: the asserted phrase is absent from every Foundation journey fixture.
  for (const dir of ["nextjs/scripts/journey/real-auth-fixtures", "nextjs/scripts/journey/receipt-fixtures"]) {
    for (const name of readdirSync(path.join(FOUNDATION, dir))) {
      check(`fixture ${dir}/${name} does not contain the uploaded document's phrase`, PHRASE.test(readFileSync(path.join(FOUNDATION, dir, name), "utf8")), false);
    }
  }
  observe("syntheticDocuments", Object.fromEntries(Object.entries(docs).map(([key, doc]) => [key, { name: doc.name, bytes: doc.bytes.length, sha256: sha256(doc.bytes) }])));

  // -------------------------------------------------------------------------------------------
  // Services: Core v2, CPU OCR, CDR + clamd, each behind an observing proxy.
  // -------------------------------------------------------------------------------------------
  hop("start-core");
  const corePort = await freePort();
  mkdirSync(path.join(root, "core-journal"));
  start("core", corePython, ["-m", "uvicorn", "--factory", "core_synthetic_app:create_synthetic_test_app", "--app-dir", path.join(CORE, "tests/e2e/joined"),
    "--host", "127.0.0.1", "--port", String(corePort), "--no-access-log"], { cwd: CORE, env: { ...env,
    PYTHONPATH: ["packages/cir-python/src", "packages/domain-packs/src", "packages/product-core/src"].map(p => path.join(CORE, p)).join(path.delimiter),
    TAVONEL_JOINED_E2E_SYNTHETIC_ONLY: "1", GITHUB_ACTIONS: process.env.GITHUB_ACTIONS, RUNNER_ENVIRONMENT: process.env.RUNNER_ENVIRONMENT,
    TAVONEL_JOINED_CORE_HMAC: secrets.core, TAVONEL_JOINED_CORE_RELEASE_DIGEST: coreReleaseDigest,
    TAVONEL_JOINED_CORE_JOURNAL: path.join(root, "core-journal/journal.sqlite3") } });
  let coreHealth;
  await waitUntil("Core /health", async () => { const r = await fetch(`http://127.0.0.1:${corePort}/health`); coreHealth = await r.json(); return r.ok; });
  check("Core health names the v2 runtime, the synthetic release and the synthetic-only customer-data switch",
    [coreHealth.runtime, coreHealth.coreReleaseDigest, coreHealth.customerDataEnabled], ["tavonel-python-core-v2", coreReleaseDigest, true]);
  observe("coreHealth", coreHealth);

  hop("start-ocr");
  const ocrPort = await freePort();
  start("ocr", ocrPython, ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(ocrPort), "--no-access-log"],
    { cwd: path.join(FOUNDATION, "workers/foundation-ocr-cpu-raster"), env: { ...env, TAVONEL_OCR_HMAC: secrets.ocr } });
  // /ping is 200 only after the real engines read a rendered known page on CPUExecutionProvider sessions.
  await waitUntil("OCR /ping self-test", async () => (await fetch(`http://127.0.0.1:${ocrPort}/ping`)).status === 200, 600, 1000);
  const ocrHealth = await (await fetch(`http://127.0.0.1:${ocrPort}/health`)).json();
  observe("ocrHealth", ocrHealth);

  hop("start-cdr-clamav");
  const cdrPort = await freePort();
  cdrContainer = `joined-e2e-cdr-${randomBytes(4).toString("hex")}`;
  // The HMAC reaches docker through its environment (`-e NAME`), never argv. Every docker command is an asynchronous,
  // hard-bounded child, so none of them can block the event loop.
  await runBounded("docker run", "docker", ["run", "-d", "--name", cdrContainer, "--network", "host", "-e", "TAVONEL_CDR_HMAC", "-e", "CLAMD_HOST=127.0.0.1", "-e", "CLAMD_PORT=3310",
    "-e", "CLAMD_READ_TIMEOUT_SECONDS=30", "-e", "MALWARE_SCAN_REQUIRED=1", cdrImage, "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(cdrPort), "--no-access-log"],
  { env: { ...env, TAVONEL_CDR_HMAC: secrets.cdr }, timeoutMs: 60_000 });
  // /health is 200 only with the HMAC configured, soffice present and clamd answering PING.
  await waitUntil("CDR /health", async () => (await fetch(`http://127.0.0.1:${cdrPort}/health`)).ok, 120, 1000);
  const cdrImageId = (await runBounded("docker image inspect", "docker", ["image", "inspect", "--format", "{{.Id}}", cdrImage], { env, timeoutMs: 30_000 })).stdout.trim();
  observe("cdr", { imageId: cdrImageId, clamdImage: process.env.TAVONEL_JOINED_CLAMAV_IMAGE ?? null });

  /** Plain HTTP pass-through that records each call. Bodies are not altered. */
  async function observingProxy(upstreamPort, record) {
    const calls = [];
    const server = ownServer(`proxy:${upstreamPort}`, http.createServer(async (request, response) => {
      const body = await readBody(request);
      const upstream = http.request({ hostname: "127.0.0.1", port: upstreamPort, method: request.method, path: request.url, headers: request.headers, agent: false }, async result => {
        const reply = await readBody(result);
        calls.push(record(request, result, reply));
        response.writeHead(result.statusCode, result.headers); response.end(reply);
      });
      upstream.on("error", () => { calls.push({ path: request.url, status: 0 }); response.destroy(); });
      upstream.end(body);
    }));
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    return { url: `http://127.0.0.1:${server.address().port}`, calls, server };
  }
  const ocrProxy = await observingProxy(ocrPort, (request, result, reply) => ({ path: request.url, status: result.statusCode,
    inputSha256: request.headers["x-tavonel-input-sha256"] ?? null, bytes: reply.length }));
  const cdrProxy = await observingProxy(cdrPort, (request, result, reply) => {
    let scan = null, refusal = null;
    try { scan = JSON.parse(result.headers["x-tavonel-malware-scan"] ?? "null"); } catch { /* recorded as null */ }
    if (result.statusCode !== 200) { try { refusal = JSON.parse(reply.toString("utf8")).detail ?? null; } catch { refusal = reply.toString("utf8").slice(0, 300); } }
    return { path: request.url, status: result.statusCode, cdrStatus: result.headers["x-tavonel-cdr-status"] ?? null, malwareScan: scan, refusal };
  });

  // -------------------------------------------------------------------------------------------
  // Disposable identity and fixture rows (all labelled in the ledger).
  // -------------------------------------------------------------------------------------------
  hop("fixtures");
  const created = await api("/auth/v1/admin/users", { id: owner, email, password, email_confirm: true });
  check("GoTrue admin creates the per-run synthetic owner", [created.status, created.body?.id], [200, owner]);
  check("signup trigger provisions the owner's pilot workspace membership",
    sql(`select count(*) from public.foundation_workspace_members where workspace_key='${workspace}' and user_id='${owner}' and state='active'`), "1");
  sql(`insert into public.foundation_account_access_grants(user_id,grant_kind,billing_exempt,trial_exempt) values ('${owner}','owner',true,true)`);
  sql(`insert into public.foundation_billing_accounts(workspace_key,user_id) values ('${workspace}','${owner}') on conflict (workspace_key) do nothing`);
  sql(`select public.bootstrap_enterprise_for_user('${owner}')`);
  const evaluatedAt = new Date(Date.now() - 60_000).toISOString();
  const evidence = customerDataPreconditions.map(precondition => ({ precondition, satisfied: true, checkedAt: evaluatedAt,
    evidence: `fixture:tavonel-joined-e2e:${process.env.GITHUB_RUN_ID ?? "local"}:synthetic-only-not-production-evidence` }));
  const gate = evaluateCustomerDataGate({ tenantId: workspace, workspaceId: workspace, evidence, now: evaluatedAt });
  assert.equal(gate.allowed, true, "the fixture gate evaluates as allowed under Foundation's own evaluator");
  const evidenceJson = JSON.stringify(evidence).replaceAll("'", "''");
  sql(`insert into public.customer_data_gate_receipts(tenant_id,workspace_id,allowed,satisfied_count,receipt_sha256,missing,evidence,evaluated_at)
    values ('${workspace}','${workspace}',true,${customerDataPreconditions.length},'${gate.receiptSha256}','{}','${evidenceJson}'::jsonb,'${evaluatedAt}')`);
  ledger.fixtures.push(
    { table: "auth.users (via GoTrue admin API)", detail: "per-run synthetic owner, email *.invalid" },
    { table: "foundation_account_access_grants", detail: "owner grant, billing_exempt, trial_exempt" },
    { table: "foundation_billing_accounts", detail: "workspace billing account with no provider customer" },
    { table: "enterprise_* (bootstrap_enterprise_for_user)", detail: "organization + workspace for service audit rows" },
    { table: "customer_data_gate_receipts", detail: "17 satisfied preconditions whose evidence string names this fixture; receipt digest from Foundation's evaluator", receiptSha256: gate.receiptSha256 },
  );

  const journeyInStorage = async storage => {
    storageSecret = storage.env.AWS_SECRET_ACCESS_KEY;
    const bucketName = storage.env.S3_BUCKET;
    const bucket = s3Bucket({ endpoint: storage.endpoint, bucket: bucketName, accessKey: storage.env.AWS_ACCESS_KEY_ID, secretKey: storageSecret, signedHost: storageHost });
    const listKeys = async prefix => (await bucket.list({ prefix })).objects.map(item => item.key).sort();

    // Storage allocation/readiness before any browser traffic: the quarantine bucket and a second, distinct synthetic
    // bucket (its own SeaweedFS collection) each take a signed write and read back the exact bytes on this run's local S3.
    hop("storage-readiness");
    const probeBucketName = "tavonel-joined-e2e-allocation-probe";
    const createBucket = name => new Promise((resolve, reject) => {
      const target = new URL(storage.endpoint);
      const amzDate = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
      const payloadSha256 = sha256("");
      const headers = { host: storageHost, "x-amz-content-sha256": payloadSha256, "x-amz-date": amzDate, "content-length": "0" };
      headers.authorization = signV4({ method: "PUT", path: `/${name}`, headers, payloadSha256, accessKey: storage.env.AWS_ACCESS_KEY_ID, secretKey: storageSecret, region: "auto", amzDate });
      const request = http.request({ hostname: target.hostname, port: target.port, method: "PUT", path: `/${name}`, headers, agent: false, timeout: 60_000 },
        result => { result.resume(); result.on("end", () => resolve(result.statusCode)); });
      request.on("timeout", () => request.destroy(new Error("S3 CreateBucket timed out")));
      request.on("error", reject); request.end();
    });
    check(`storage readiness: signed CreateBucket for the second synthetic bucket ${probeBucketName} succeeds`, await createBucket(probeBucketName), 200);
    const probeBucket = s3Bucket({ endpoint: storage.endpoint, bucket: probeBucketName, accessKey: storage.env.AWS_ACCESS_KEY_ID, secretKey: storageSecret, signedHost: storageHost });
    // The storage directory is fresh per run, but the key is run-unique anyway so a probe can never match a stale object.
    const probeKey = `storage-readiness/${randomUUID()}/probe.bin`;
    const probeBytes = Buffer.from(`synthetic joined-e2e storage allocation probe ${randomUUID()}\n`, "utf8");
    const readiness = [];
    for (const [name, client] of [[bucketName, bucket], [probeBucketName, probeBucket]]) {
      check(`storage readiness: signed PUT of the synthetic probe to ${name} is stored`, (await client.put(probeKey, probeBytes))?.size, probeBytes.length);
      const stored = await client.get(probeKey);
      const readBack = stored ? Buffer.from(await stored.arrayBuffer()) : null;
      check(`storage readiness: signed GET from ${name} returns exactly the probe bytes`, readBack, probeBytes);
      check(`storage readiness: probe SHA-256 read back from ${name} equals the written SHA-256`, readBack && sha256(readBack), sha256(probeBytes));
      readiness.push({ bucket: name, key: probeKey, bytes: readBack.length, sha256: sha256(readBack) });
    }
    observe("storageReadiness", readiness);

    // TLS material for the two local HTTPS listeners. Files live only in this run's temp directory.
    execFileSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", path.join(root, "key.pem"), "-out", path.join(root, "cert.pem"), "-days", "1",
      "-subj", "/CN=localhost", "-addext", `subjectAltName=IP:127.0.0.1,DNS:localhost,DNS:${storageHost}`], { env, stdio: "ignore", timeout: 15_000, killSignal: "SIGKILL" });
    const tls = { key: readFileSync(path.join(root, "key.pem")), cert: readFileSync(path.join(root, "cert.pem")) };
    const ca = tls.cert;

    // Front door: S3 / GoTrue+PostgREST / Next by path (Foundation's own routing rule). CORS for the
    // browser's signed PUT is answered here and recorded as simulated.
    const s3Arrivals = [];
    const gateway = ownServer("gateway", https.createServer(tls, async (request, response) => {
      const service = authGatewayService(request.url, bucketName);
      if (service === "s3") {
        const cors = request.headers.origin ? { "access-control-allow-origin": request.headers.origin, "access-control-expose-headers": "etag", vary: "origin" } : {};
        if (request.method === "OPTIONS") { response.writeHead(204, { ...cors, "access-control-allow-methods": "PUT", "access-control-allow-headers": "content-type", "access-control-max-age": "0" }); response.end(); return; }
        const body = await readBody(request);
        const arrival = { method: request.method, path: request.url.split("?")[0], fromBrowserOrigin: request.headers.origin === origin, bytes: body.length, sha256: body.length ? sha256(body) : null };
        const upstream = http.request({ hostname: "127.0.0.1", port: new URL(storage.endpoint).port, method: request.method, path: request.url, headers: { ...request.headers, host: storageHost }, agent: false }, result => {
          arrival.status = result.statusCode; s3Arrivals.push(arrival);
          const headers = Object.fromEntries(Object.entries(result.headers).filter(([name]) => !name.startsWith("access-control-")));
          response.writeHead(result.statusCode, { ...headers, ...cors }); result.pipe(response);
        });
        upstream.on("error", () => { response.writeHead(502); response.end(); });
        upstream.end(body);
        return;
      }
      const target = service === "supabase" ? new URL(stack.api) : new URL(`http://127.0.0.1:${nextPort}`);
      const isConfirm = request.method === "POST" && request.url?.split("?")[0] === "/api/uploads/confirm";
      const confirmStartedAt = Date.now();
      const recordConfirm = event => {
        confirmBodyTransport.push({ atMs: Date.now() - confirmStartedAt, method: "POST", route: "/api/uploads/confirm", ...event });
        if (confirmBodyTransport.length > 100) confirmBodyTransport.shift();
      };
      if (isConfirm) recordConfirm({ side: "gateway", phase: "request" });
      const upstream = http.request({ hostname: target.hostname, port: target.port, path: request.url, method: request.method, headers: request.headers }, result => {
        if (isConfirm) {
          recordConfirm({ side: "upstream", phase: "headers", status: result.statusCode, headers: safeConfirmHeaderEvidence(result.headers) });
          observeConfirmResponseBodies(result, response, recordConfirm);
        }
        response.writeHead(result.statusCode, result.headers);
        result.pipe(response);
      });
      upstream.on("error", error => {
        if (isConfirm) recordConfirm({ side: "gateway", phase: "upstream-request-error" });
        response.writeHead(502); response.end("Owned local upstream unavailable");
      });
      request.pipe(upstream);
    }));
    await new Promise(resolve => gateway.listen(54443, "127.0.0.1", resolve));

    // Core front door: HTTPS, observing, with two explicit failure modes used only by the failure path.
    const core = { mode: "pass", calls: [] };
    const coreGateway = ownServer("core-gateway", https.createServer(tls, async (request, response) => {
      const body = await readBody(request);
      const headers = { ...request.headers, host: `127.0.0.1:${corePort}` };
      const mode = request.url === "/v2/compile" ? core.mode : "pass";
      if (mode === "break-request-signature") {
        const signature = String(headers["x-tavonel-core-signature"] ?? "");
        headers["x-tavonel-core-signature"] = `${signature.slice(0, -1)}${signature.endsWith("0") ? "1" : "0"}`;
      }
      const upstream = http.request({ hostname: "127.0.0.1", port: corePort, method: request.method, path: request.url, headers, agent: false }, async result => {
        let reply = await readBody(result);
        let replyCode = null;
        try { replyCode = JSON.parse(reply.toString("utf8")).code ?? null; } catch { /* non-JSON */ }
        if (request.url === "/v2/compile") {
          let sent = null;
          try { sent = JSON.parse(body.toString("utf8")); } catch { /* recorded as null */ }
          const texts = (sent?.documents ?? []).flatMap(doc => (doc.regions ?? []).map(region => region.text));
          core.calls.push({ mode, status: result.statusCode, code: replyCode, requestId: request.headers["x-tavonel-core-request-id"] ?? null,
            privacyPolicy: sent?.route?.privacyPolicy ?? null, operationClass: sent?.route?.operationClass ?? null,
            documents: (sent?.documents ?? []).map(doc => ({ nativeId: doc.nativeId, contentSha256: doc.contentSha256, regions: doc.regions?.length ?? 0 })),
            phraseInRegions: texts.some(text => PHRASE.test(text)) });
          if (mode === "tamper-response" && result.statusCode === 200) {
            const payload = JSON.parse(reply.toString("utf8"));
            payload.candidate.validation.matchingPolicy = "tampered-by-joined-e2e";
            reply = Buffer.from(JSON.stringify(payload));
          }
        }
        const { "transfer-encoding": _chunked, ...passed } = result.headers;
        const out = { ...passed, "content-length": String(reply.length) };
        response.writeHead(result.statusCode, out); response.end(reply);
      });
      upstream.on("error", () => { response.writeHead(502); response.end(); });
      upstream.end(body);
    }));
    await new Promise(resolve => coreGateway.listen(54444, "127.0.0.1", resolve));

    try {
      // -----------------------------------------------------------------------------------------
      // Production-mode Next with every ephemeral key.
      // -----------------------------------------------------------------------------------------
      hop("next-build-start");
      const preload = path.join(root, "transport.cjs");
      writeFileSync(preload, `const os=require('node:os');const cpus=os.cpus;os.cpus=()=>cpus().slice(0,2);os.availableParallelism=()=>2;const f=globalThis.fetch;globalThis.fetch=(input,init)=>{const s=typeof input==='string'?input:input instanceof URL?input.href:null;if(s){const u=new URL(s);if(u.hostname===${JSON.stringify(storageHost)})return f(${JSON.stringify(origin)}+u.pathname+u.search,init);}return f(input,init);};`);
      const nextEnv = { ...env, NODE_ENV: "production", NEXT_TELEMETRY_DISABLED: "1", NODE_OPTIONS: `--max-old-space-size=3072 --require ${JSON.stringify(preload)}`,
        NODE_EXTRA_CA_CERTS: path.join(root, "cert.pem"), FOUNDATION_PILOT_USER_IDS: owner, NEXT_PUBLIC_SUPABASE_URL: origin,
        NEXT_PUBLIC_SUPABASE_ANON_KEY: stack.anon, SUPABASE_SERVICE_ROLE_KEY: stack.service, R2_ACCOUNT_ID: storageHost.split(".")[0], R2_BUCKET: bucketName,
        R2_ACCESS_KEY_ID: storage.env.AWS_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY: storageSecret, FOUNDATION_CORE_V2_URL: coreOrigin,
        FOUNDATION_CORE_V2_HMAC: secrets.core, FOUNDATION_WORKER_SECRET: secrets.worker, FOUNDATION_BILLING_SETTLEMENT_HMAC: secrets.settlement, ...signingEnv };
      const nextBin = path.join(nextRoot, "node_modules/next/dist/bin/next");
      execFileSync(process.execPath, [nextBin, "build"], { cwd: nextRoot, env: nextEnv, stdio: "inherit", timeout: 900_000, killSignal: "SIGKILL" });
      const next = start("next", process.execPath, [nextBin, "start", "--hostname", "127.0.0.1", "--port", String(nextPort)], { cwd: nextRoot, env: nextEnv });
      await waitUntil("Next /api/status", async () => { if (next.exitCode !== null) throw new Error("Next exited"); return (await fetch(`http://127.0.0.1:${nextPort}/api/status`)).ok; });

      /** JSON over the gateway, trusting only this run's certificate. */
      const app = (resource, bearer, body, method = body === undefined ? "GET" : "POST", extraHeaders = {}) => new Promise((resolve, reject) => {
        const url = new URL(resource, origin);
        const payload = body === undefined ? null : JSON.stringify(body);
        const accept = /^\/api\/(v1|developer)\//.test(url.pathname) ? "application/vnd.tavonel.v1+json" : "application/json";
        const request = https.request(url, { method, ca, timeout: 120_000, headers: { accept, ...(bearer ? { authorization: `Bearer ${bearer}` } : {}), ...extraHeaders,
          ...(payload ? { "content-type": "application/json", "content-length": Buffer.byteLength(payload) } : {}) } }, result => {
          readBody(result).then(raw => { let json = null; try { json = JSON.parse(raw.toString("utf8")); } catch { /* not JSON */ } resolve({ status: result.statusCode, body: json }); }, reject);
        });
        request.on("timeout", () => request.destroy(new Error(`${resource} timed out`))); request.on("error", reject); request.end(payload ?? undefined);
      });
      /** The signed PUT a browser would make, for the API-only uploads of the failure path. */
      const signedPut = (uploadUrl, bytes) => new Promise((resolve, reject) => {
        const signed = new URL(uploadUrl);
        assert.equal(signed.hostname, storageHost, "capability signs a PUT for the R2 host");
        const request = https.request(new URL(`${signed.pathname}${signed.search}`, origin), { method: "PUT", ca,
          headers: { "content-type": "application/pdf", "content-length": bytes.length } }, result => { result.resume(); result.on("end", () => resolve(result.statusCode)); });
        request.on("error", reject); request.end(bytes);
      });
      async function apiUpload(token, doc) {
        const contentSha256 = `sha256:${sha256(doc.bytes)}`;
        const mimeType = "application/pdf";
        const fileKey = await deriveFileKey({ relativePath: doc.name, contentSha256, byteLength: doc.bytes.length, mimeType });
        const files = [{ fileKey, originalFilename: doc.name, contentSha256, byteLength: doc.bytes.length, mimeType, claimedPages: null, claimedBasis: null }];
        const clientManifestDigest = await intakeManifestDigest(files);
        const pricingFingerprint = await intakePricingFingerprint();
        const quoted = quoteIntakeManifest(files.map(file => ({ bytes: file.byteLength, mimeType: file.mimeType, claimedPages: file.claimedPages, claimedBasis: file.claimedBasis })));
        assert.equal(quoted.ok, true, `bounded synthetic maximum quote exists for ${doc.name}`);
        const attemptKey = newAttemptKey();
        const approvalReply = await app("/api/uploads/approval", token, {
          attemptKey, clientManifestDigest, pricingFingerprint, aggregateMaximumCredits: quoted.quote.maximumCredits, files,
        });
        check(`complete one-file manifest approval accepts ${doc.name}`, [approvalReply.status, approvalReply.body?.code], [200, "INTAKE_APPROVED"]);
        const approval = approvalReply.body.approval;
        const approvedFile = approval?.files?.find(file => file.fileKey === fileKey);
        check(`approval binds the exact bounded quote for ${doc.name}`,
          [approval?.attemptKey, approval?.clientManifestDigest, approval?.pricingFingerprint, approval?.aggregateMaximumCredits,
            approvedFile?.contentSha256, approvedFile?.byteLength, approvedFile?.approvedMaximumCredits],
          [attemptKey, clientManifestDigest, pricingFingerprint, quoted.quote.maximumCredits, contentSha256, doc.bytes.length, quoted.quote.maximumCredits]);
        const scopeDigest = approval.scopeDigest;
        const idempotencyKey = await approvedSourceIdempotencyKey(attemptKey, fileKey);
        const capability = await app("/api/uploads/capability", token, {
          originalFilename: doc.name, declaredMimeType: mimeType, requestedBytes: doc.bytes.length,
          attemptKey, scopeDigest, pricingFingerprint, fileKey, contentSha256,
        }, "POST", { "x-tavonel-source-idempotency-key": idempotencyKey });
        check(`capability qualifies ${doc.name}`, [capability.status, capability.body?.code], [200, "QUALIFIED"]);
        check(`capability keeps the approved document identity for ${doc.name}`, capability.body?.documentId, approvedFile.documentId);
        check(`signed PUT stores ${doc.name}`, await signedPut(capability.body.uploadUrl, doc.bytes), 200);
        const confirmBody = { documentId: capability.body.documentId, sourceSha256: contentSha256, attemptKey, scopeDigest, fileKey };
        const confirm = await app("/api/uploads/confirm", token, confirmBody);
        check(`confirm accepts ${doc.name}`, [confirm.status, confirm.body?.code], [200, "UPLOAD_CONFIRMED"]);
        check(`confirm receipt binds the approved file for ${doc.name}`,
          [confirm.body?.approvedFile?.fileKey, confirm.body?.approvedFile?.documentId, confirm.body?.approvedFile?.fileState],
          [fileKey, capability.body.documentId, "confirmed"]);
        return { documentId: capability.body.documentId, objectKey: capability.body.objectKey,
          attemptKey, scopeDigest, pricingFingerprint, fileKey, contentSha256, idempotencyKey };
      }

      // -----------------------------------------------------------------------------------------
      // Simulated R2 event + queue: the R2 event-notification body, delivered to the real handleQueue.
      // -----------------------------------------------------------------------------------------
      const workerEnv = {
        FOUNDATION_QUARANTINE: bucket, FOUNDATION_R2_BUCKET: bucketName,
        TAVONEL_CDR_URL: `${cdrProxy.url}/v1/disarm`, TAVONEL_CDR_HEALTH_URL: `${cdrProxy.url}/health`,
        TAVONEL_CDR_PROVIDER: "ci_joined_e2e_pdfium_clamav", TAVONEL_CDR_HMAC: secrets.cdr,
        FOUNDATION_OCR_URL: `${ocrProxy.url}/v1/ocr`, TAVONEL_OCR_HMAC: secrets.ocr,
        FOUNDATION_BILLING_SETTLEMENT_URL: `http://127.0.0.1:${nextPort}/api/internal/billing/settle`, FOUNDATION_BILLING_SETTLEMENT_HMAC: secrets.settlement,
      };
      const deliveries = [];
      async function deliver(objectKey, attempts) {
        const head = await bucket.get(objectKey);
        assert.ok(head, `quarantine object ${objectKey} exists before its event is delivered`);
        const message = { body: { account: "simulated-joined-e2e", action: "PutObject", bucket: bucketName, eventTime: new Date().toISOString(),
          object: { key: objectKey, size: head.size } }, attempts, acks: 0, retries: [], ack() { this.acks++; }, retry(options) { this.retries.push(options ?? {}); } };
        await handleQueue({ queue: "foundation-quarantine-created", messages: [message] }, workerEnv, fetch);
        const result = { objectKey, attempts, acks: message.acks, retries: message.retries };
        deliveries.push(result);
        check(`queue message for ${objectKey} (attempt ${attempts}) is decided exactly once, by ack`, [message.acks, message.retries.length], [1, 0]);
        return result;
      }
      const reservation = documentId => sql(`select state||'|'||coalesce(settled_credits::text,'-')||'|'||coalesce(reason_code,'-')||'|'||coalesce(settled_at::text,'-') from public.foundation_compute_reservations where document_id='${documentId}'`);
      const jobRow = jobId => { const [state, collectionId, manifestDigest, errorCode] = sql(`select state||'|'||coalesce(collection_id,'')||'|'||coalesce(candidate_manifest_digest,'')||'|'||coalesce(error_code,'') from public.foundation_compile_jobs where job_id='${jobId}'`).split("|"); return { state, collectionId, manifestDigest, errorCode }; };
      const cron = async (secret = secrets.worker) => { const r = await fetch(`http://127.0.0.1:${nextPort}/api/internal/jobs/run`, { method: "POST", headers: { authorization: `Bearer ${secret}` }, signal: AbortSignal.timeout(90_000) }); return { status: r.status, body: await r.json().catch(() => null) }; };
      async function driveJob(jobId) {
        for (let turn = 0; turn < 90; turn++) {
          const result = await cron();
          assert.equal(result.status, 200, `simulated cron is authorized: ${JSON.stringify(result.body)}`);
          const row = jobRow(jobId);
          if (["ready", "review_required", "failed", "cancelled"].includes(row.state)) return row;
          await sleep(2000);
        }
        throw new Error(`compile job ${jobId} did not reach a terminal state: ${JSON.stringify(jobRow(jobId))}`);
      }
      const candidateKeys = async () => (await listKeys(`immutable/${workspace}/${workspace}/collections/`)).filter(key => key.endsWith("/candidate-world.json"));
      const counts = () => ({ ocr: ocrProxy.calls.length, cdr: cdrProxy.calls.length, core: core.calls.length,
        audit: sql(`select count(*) from public.enterprise_audit_events where workspace_key='${workspace}' and action='compile.receipt_signed'`),
        provenance: sql(`select count(*) from public.foundation_collection_artifact_provenance where workspace_key='${workspace}'`),
        jobs: sql(`select count(*) from public.foundation_compile_jobs where workspace_key='${workspace}'`) });

      check("simulated cron without the worker secret is refused", (await cron("not-the-worker-secret-but-long-enough-0000000000")).status, 401);

      // -----------------------------------------------------------------------------------------
      // 1. Browser: sign in, upload through the real workspace UI.
      // -----------------------------------------------------------------------------------------
      hop("browser-sign-in");
      const playwright = await import(pathToFileURL(path.join(nextRoot, "node_modules/@playwright/test/index.mjs")).href);
      const { chromium } = playwright;
      const expect = playwright.expect.configure({ timeout: 60_000 });
      const childrenBeforeBrowser = new Set(childPidsOf(process.pid));
      browser = await chromium.launch({ headless: true });
      // Playwright starts Chromium as a detached child of this process; its pids are what a stuck browser-close aborts.
      browserPids = childPidsOf(process.pid).filter(pid => !childrenBeforeBrowser.has(pid));
      observe("browserProcessGroups", browserPids.length);
      context = await browser.newContext({ ignoreHTTPSErrors: true });
      // Kept only when the run fails, as failure-trace.zip: a separate artifact from the ledger and not redacted. It can
      // hold this run's synthetic documents, page contents and disposable, already-dead credentials.
      await context.tracing.start({ screenshots: true, snapshots: true });
      const blocked = [];
      await routeLocalStorageTransport(context, origin, url => blocked.push(redact(url).slice(0, 200)));
      page = await context.newPage();
      page.setDefaultTimeout(120_000);
      const keep = line => { browserEvents.push(redact(line).slice(0, 400)); if (browserEvents.length > 200) browserEvents.shift(); };
      const uploadRequestTimes = { approvalFinishedAt: null, capabilityRequestedAt: null };
      page.on("request", request => {
        const pathname = new URL(request.url()).pathname;
        if (request.method() === "POST" && pathname === "/api/uploads/capability") uploadRequestTimes.capabilityRequestedAt = Date.now();
      });
      page.on("requestfinished", request => {
        if (request.method() === "POST" && new URL(request.url()).pathname === "/api/uploads/approval") uploadRequestTimes.approvalFinishedAt = Date.now();
      });
      page.on("console", message => { if (["error", "warning"].includes(message.type())) keep(`console.${message.type()}: ${message.text()}`); });
      page.on("pageerror", error => keep(`pageerror: ${error.message}`));
      const isBrowserConfirm = request => request.method() === "POST" && new URL(request.url()).pathname === "/api/uploads/confirm";
      page.on("requestfailed", request => {
        if (isBrowserConfirm(request)) keep("confirm.browser method=POST route=/api/uploads/confirm phase=requestfailed");
        else keep(`requestfailed ${request.method()} ${request.url()}: ${request.failure()?.errorText ?? "?"}`);
      });
      page.on("response", response => {
        const request = response.request();
        if (isBrowserConfirm(request)) keep(`confirm.browser method=POST route=/api/uploads/confirm phase=headers status=${response.status()} framing=${JSON.stringify(safeConfirmHeaderEvidence(response.headers()))}`);
      });
      page.on("requestfinished", request => { if (isBrowserConfirm(request)) keep("confirm.browser method=POST route=/api/uploads/confirm phase=requestfinished"); });

      await page.goto(`${origin}/llms.txt`);
      const login = await page.evaluate(async ({ email, password, anon }) => {
        const r = await fetch("/auth/v1/token?grant_type=password", { method: "POST", headers: { apikey: anon, "content-type": "application/json" }, body: JSON.stringify({ email, password }) });
        return { status: r.status, body: await r.json() };
      }, { email, password, anon: stack.anon });
      check("GoTrue password login through the browser transport", login.status, 200);
      const session = login.body;
      session.expires_at ??= JSON.parse(Buffer.from(session.access_token.split(".")[1], "base64url").toString()).exp;
      await page.evaluate(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: "sb-127-auth-token", value: session });
      await page.goto(`${origin}/auth/callback`);
      await page.waitForURL("**/workspace", { timeout: 60_000 });
      check("the provider session completes the callback into the workspace", new URL(page.url()).pathname, "/workspace");
      await expect(page.locator(".workspace-intake")).toHaveAttribute("data-inventory-state", "ready", { timeout: 60_000 });

      hop("browser-upload");
      // Each step is bounded, so a stalled upload fails here with the step named instead of running into the job
      // timeout. The PUT allowance is sized for this ~1 KB synthetic fixture, not for production uploads.
      const uploadDeadlineMs = { selectFile: 30_000, preflight: 90_000, review: 30_000, legacyAlert: 30_000, submit: 30_000,
        replyHeaders: 90_000, replyBody: 15_000, signedPut: 180_000 };
      // The waiters start before the click so no reply is missed. Their own timeout outlasts every step deadline
      // added together, so it only backstops them: the step deadline is the one that fires and names the step.
      const replyWaitMs = uploadDeadlineMs.selectFile + uploadDeadlineMs.preflight + uploadDeadlineMs.review + uploadDeadlineMs.legacyAlert
        + uploadDeadlineMs.submit + uploadDeadlineMs.signedPut + 4 * (uploadDeadlineMs.replyHeaders + uploadDeadlineMs.replyBody);
      await step("select-file", uploadDeadlineMs.selectFile,
        () => page.locator('input[type="file"][multiple]').first().setInputFiles({ name: docs.ui.name, mimeType: "application/pdf", buffer: docs.ui.bytes }));
      const preflight = page.getByRole("region", { name: "Compile preflight" });
      const triage = preflight.getByRole("region", { name: "Server source triage", exact: true });
      const reviewButton = triage.getByRole("button", { name: "Review sources before processing", exact: true });
      const legacyApproval = triage.getByRole("alert").filter({ hasText: "Full-scope legacy approval" });
      const uploadButton = legacyApproval.getByRole("button", { name: "Approve maximum & upload", exact: true });
      await step("preflight", uploadDeadlineMs.preflight, async () => {
        await expect(preflight).toBeVisible();
        await expect(triage).toBeVisible();
        await expect(reviewButton).toBeEnabled({ timeout: 60_000 });
      });
      const responseOf = (method, matches) => {
        const waiting = page.waitForResponse(response => response.request().method() === method && matches(new URL(response.url()).pathname), { timeout: replyWaitMs });
        waiting.catch(() => {}); // awaited below; a rejection after an earlier failure must not become unhandled
        return waiting;
      };
      // The triage rollout is code-owned off. Reviewing sources is a real availability check that must upload nothing;
      // any other reply fails the run here rather than enabling triage or standing in for it.
      const reviewRequests = [];
      const recordReviewRequest = request => reviewRequests.push({ method: request.method(), pathname: new URL(request.url()).pathname });
      const objectPuts = () => s3Arrivals.filter(arrival => arrival.method === "PUT").length;
      const beforeReview = { ...counts(), objectPuts: objectPuts() };
      page.on("request", recordReviewRequest);
      try {
        const stageReply = responseOf("POST", p => p === "/api/v1/uploads/triage/stage");
        await step("review-sources", uploadDeadlineMs.review, () => reviewButton.click());
        const stageResponse = await step("triage-stage-headers", uploadDeadlineMs.replyHeaders, stageReply);
        const stageBody = await step("triage-stage-body", uploadDeadlineMs.replyBody, () => stageResponse.json());
        const stageRequestBody = stageResponse.request().postDataJSON();
        const stagedFile = stageRequestBody?.files?.[0];
        const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
        check("the triage availability check declares exactly the selected fixture's path, MIME type and byte count, never its bytes",
          [Object.keys(stageRequestBody ?? {}).sort(), uuid.test(stageRequestBody?.batchId), stageRequestBody?.files?.length,
            Object.keys(stagedFile ?? {}).sort(), stagedFile?.relativePath, stagedFile?.declaredMimeType, stagedFile?.requestedBytes, uuid.test(stagedFile?.idempotencyKey)],
          [["batchId", "files"], true, 1, ["declaredMimeType", "idempotencyKey", "relativePath", "requestedBytes"],
            docs.ui.name, "application/pdf", docs.ui.bytes.length, true]);
        check("the real Next triage route reports the code-owned rollout as disabled", [stageResponse.status(), stageBody], [404, { code: "INTAKE_TRIAGE_DISABLED" }]);
        await step("legacy-approval-alert", uploadDeadlineMs.legacyAlert, async () => {
          await expect(legacyApproval).toBeVisible();
          await expect(triage).toContainText("Server triage is disabled.");
          await expect(uploadButton).toBeEnabled();
        });
      } finally {
        page.off("request", recordReviewRequest);
      }
      check("the triage review phase made no approval, capability, object PUT, confirm or compile request",
        reviewRequests.filter(({ method, pathname }) => method === "PUT"
          || (method === "POST" && ["/api/uploads/approval", "/api/uploads/capability", "/api/uploads/confirm", "/api/compile-jobs"].includes(pathname))), []);
      check("the triage review phase made exactly one triage request",
        reviewRequests.filter(({ pathname }) => pathname.startsWith("/api/v1/uploads/triage/")).map(({ method, pathname }) => `${method} ${pathname}`),
        ["POST /api/v1/uploads/triage/stage"]);
      check("the triage review phase changed no OCR, CDR, Core, job, audit, provenance or stored-object count",
        { ...counts(), objectPuts: objectPuts() }, beforeReview);
      const displayedMaximum = Number((await preflight.getByRole("term").filter({ hasText: /^Maximum$/ }).locator("xpath=following-sibling::dd").textContent())
        ?.trim().replace(/^\$/, "").replaceAll(",", ""));
      check("the Compile preflight displays a finite maximum", Number.isFinite(displayedMaximum) && displayedMaximum > 0, true);
      check("the full-scope legacy approval names the displayed maximum and offers no bounded-preflight control",
        [await legacyApproval.count(), (await legacyApproval.textContent())?.includes(`approves the displayed maximum of $${displayedMaximum.toFixed(2)}.`),
          await uploadButton.count(), await reviewButton.count(), await triage.getByRole("button", { name: "Approve bounded source preflight" }).count(),
          await triage.getByRole("list", { name: "Server classified source inventory" }).count()],
        [1, true, 1, 0, 0, 0]);
      const approvalReply = responseOf("POST", p => p === "/api/uploads/approval");
      const capabilityReply = responseOf("POST", p => p === "/api/uploads/capability");
      const putReply = responseOf("PUT", p => p.startsWith(`/${bucketName}/quarantine/`));
      const confirmReply = responseOf("POST", p => p === "/api/uploads/confirm");
      const compileReply = responseOf("POST", p => p === "/api/compile-jobs");
      await step("submit", uploadDeadlineMs.submit, () => uploadButton.click());
      const approvalResponse = await step("approval-headers", uploadDeadlineMs.replyHeaders, approvalReply);
      const approvalBody = await step("approval-body", uploadDeadlineMs.replyBody, () => approvalResponse.json());
      const approvalRequest = approvalResponse.request();
      const approvalRequestBody = approvalRequest.postDataJSON();
      check("UI creates a real complete-set approval before requesting a capability",
        [approvalResponse.status(), approvalBody.code, approvalRequestBody.files?.length,
          uploadRequestTimes.approvalFinishedAt !== null && uploadRequestTimes.capabilityRequestedAt !== null
            && uploadRequestTimes.approvalFinishedAt <= uploadRequestTimes.capabilityRequestedAt],
        [200, "INTAKE_APPROVED", 1, true]);
      const uiManifestDigest = await intakeManifestDigest(approvalRequestBody.files);
      const uiQuote = quoteIntakeManifest(approvalRequestBody.files.map(file => ({ bytes: file.byteLength, mimeType: file.mimeType,
        claimedPages: file.claimedPages, claimedBasis: file.claimedBasis })));
      assert.equal(uiQuote.ok, true, "the selected browser manifest has a bounded shared quote");
      const uiApproval = approvalBody.approval;
      check("UI approval response binds the submitted attempt key", uiApproval.attemptKey, approvalRequestBody.attemptKey);
      check("UI approval matches the canonical manifest and explicit maximum",
        [uiApproval.clientManifestDigest, uiApproval.pricingFingerprint, approvalRequestBody.aggregateMaximumCredits,
          uiApproval.aggregateMaximumCredits, uiApproval.fileCount],
        [uiManifestDigest, await intakePricingFingerprint(), uiQuote.quote.maximumCredits, uiQuote.quote.maximumCredits, approvalRequestBody.files.length]);
      const uiApprovedFile = uiApproval.files.find(file => file.fileKey === approvalRequestBody.files[0].fileKey);
      check("UI approval contains the selected file identity and exact member maximum",
        [Boolean(uiApprovedFile), uiApprovedFile?.contentSha256, uiApprovedFile?.byteLength, uiApprovedFile?.approvedMaxPages,
          uiApprovedFile?.approvedReservedCredits, uiApprovedFile?.approvedMaximumCredits],
        [true, approvalRequestBody.files[0].contentSha256, approvalRequestBody.files[0].byteLength, uiQuote.quote.files[0].approvedMaxPages,
          uiQuote.quote.files[0].reservedCredits, uiQuote.quote.files[0].maximumCredits]);
      const capabilityResponse = await step("capability-headers", uploadDeadlineMs.replyHeaders, capabilityReply);
      const capability = await step("capability-body", uploadDeadlineMs.replyBody, () => capabilityResponse.json());
      check("UI capability request qualifies the synthetic PDF", capability.code, "QUALIFIED");
      const uiCapabilityRequest = capabilityResponse.request();
      const uiCapabilityBody = uiCapabilityRequest.postDataJSON();
      const uiIdempotencyKey = await approvedSourceIdempotencyKey(uiApproval.attemptKey, uiApprovedFile.fileKey);
      check("UI capability carries the approved identities and derived idempotency key",
        [uiCapabilityBody.attemptKey, uiCapabilityBody.scopeDigest, uiCapabilityBody.pricingFingerprint, uiCapabilityBody.fileKey,
          uiCapabilityBody.contentSha256, uiCapabilityRequest.headers()["x-tavonel-source-idempotency-key"]],
        [uiApproval.attemptKey, uiApproval.scopeDigest, uiApproval.pricingFingerprint, uiApprovedFile.fileKey,
          uiApprovedFile.contentSha256, uiIdempotencyKey]);
      check("UI capability names the approved member's document", capability.documentId, uiApprovedFile.documentId);
      const putResponse = await step("signed-put", uploadDeadlineMs.signedPut, putReply);
      check("browser signed PUT is accepted by storage", putResponse.status(), 200);
      const confirmed = await step("confirm-headers", uploadDeadlineMs.replyHeaders, confirmReply);
      const confirmBody = await step("confirm-body", uploadDeadlineMs.replyBody, () => confirmed.json());
      check("UI confirm records the upload", [confirmed.status(), confirmBody.code], [200, "UPLOAD_CONFIRMED"]);
      const uiConfirmBody = confirmed.request().postDataJSON();
      check("UI confirmation retains the approval identities and validated receipt",
        [uiConfirmBody.attemptKey, uiConfirmBody.scopeDigest, uiConfirmBody.fileKey, uiConfirmBody.sourceSha256,
          confirmBody.approvedFile?.fileKey, confirmBody.approvedFile?.fileState],
        [uiApproval.attemptKey, uiApproval.scopeDigest, uiApprovedFile.fileKey, uiApprovedFile.contentSha256, uiApprovedFile.fileKey, "confirmed"]);
      const compileAccepted = await step("compile-enqueue-headers", uploadDeadlineMs.replyHeaders, compileReply);
      const compileJob = await step("compile-enqueue-body", uploadDeadlineMs.replyBody, () => compileAccepted.json());
      check("UI enqueues the durable compile job", [compileAccepted.status(), compileJob.code], [202, "COMPILE_JOB_ACCEPTED"]);
      const docA = { documentId: capability.documentId, objectKey: capability.objectKey, jobId: compileJob.jobId,
        attemptKey: uiApproval.attemptKey, scopeDigest: uiApproval.scopeDigest, pricingFingerprint: uiApproval.pricingFingerprint,
        fileKey: uiApprovedFile.fileKey, contentSha256: uiApprovedFile.contentSha256, idempotencyKey: uiIdempotencyKey };
      check("capability names the quarantine key of the document", docA.objectKey, `quarantine/${workspace}/${docA.documentId}/source`);
      const browserPut = s3Arrivals.find(arrival => arrival.method === "PUT" && arrival.path === `/${bucketName}/${docA.objectKey}`);
      check("the stored bytes arrived as the browser's cross-origin PUT", [browserPut?.fromBrowserOrigin, browserPut?.sha256, browserPut?.status], [true, sha256(docs.ui.bytes), 200]);
      const storedSource = await bucket.get(docA.objectKey);
      check("storage holds exactly the uploaded bytes", sha256(Buffer.from(await storedSource.arrayBuffer())), sha256(docs.ui.bytes));
      // Requests to any other host were aborted by the route before reaching the network; listed, not asserted.
      observe("browserBlockedRequests", blocked.slice(0, 40));
      const confirmedAt = sql(`select confirmed_at from public.foundation_intake_admissions where document_id='${docA.documentId}'`);
      ledger.booleans.uploadViaUiVerified = true;
      observe("uiUpload", { documentId: docA.documentId, jobId: docA.jobId, objectKey: docA.objectKey });
      // Leave the workspace so its live job stream does not also drive the compile; the simulated cron is the only driver.
      await page.goto(`${origin}/llms.txt`);

      // -----------------------------------------------------------------------------------------
      // 2. Simulated event -> real CDR + ClamAV -> real OCR -> settlement.
      // -----------------------------------------------------------------------------------------
      hop("cdr-ocr");
      await deliver(docA.objectKey, 1);
      const docPrefix = `immutable/${workspace}/${workspace}/${docA.documentId}/`;
      const docKeys = await listKeys(docPrefix);
      const sanitizedKey = docKeys.find(key => key.endsWith("/sanitized.pdf"));
      assert.ok(sanitizedKey, `CDR wrote a sanitized PDF under ${docPrefix}: ${JSON.stringify(docKeys)}`);
      docA.versionKey = sanitizedKey.split("/")[4];
      check("CDR wrote sanitized.pdf, its receipt and OCR output beside each other",
        ["cdr-receipt.json", "ocr.json", "sanitized.pdf"].every(name => docKeys.includes(`${docPrefix}${docA.versionKey}/${name}`)), true);
      const cdrCall = cdrProxy.calls.at(-1);
      check("real CDR returned a clean, scanned result", [cdrCall.status, cdrCall.cdrStatus, cdrCall.malwareScan?.verdict], [200, "clean", "clean"]);
      check("the scan verdict names a real engine", typeof cdrCall.malwareScan?.engine === "string" && cdrCall.malwareScan.engine.length > 0, true);
      const sanitized = Buffer.from(await (await bucket.get(sanitizedKey)).arrayBuffer());
      check("sanitized PDF version key is its own digest", sha256(sanitized), docA.versionKey);
      check("CDR output is not the uploaded bytes (rasterized copy)", sha256(sanitized) === sha256(docs.ui.bytes), false);
      const ocr = JSON.parse(Buffer.from(await (await bucket.get(`${docPrefix}${docA.versionKey}/ocr.json`)).arrayBuffer()).toString("utf8"));
      check("OCR was called exactly once, for the sanitized PDF", ocrProxy.calls.map(call => [call.status, call.inputSha256]), [[200, `sha256:${docA.versionKey}`]]);
      check("OCR read the phrase from pixels (raster regions, not a native text layer)",
        [ocr.regions.some(region => PHRASE.test(region.text)), ocr.regions.every(region => !String(region.regionId).startsWith("native-"))], [true, true]);
      check("OCR regions carry page 1 bounding boxes", ocr.regions.every(region => region.pageNumber1 === 1 && Array.isArray(region.bbox1000) && region.bbox1000.length === 4), true);
      observe("ocrResult", { pageCount: ocr.pageCount, regions: ocr.regions.map(region => ({ regionId: region.regionId, text: region.text, bbox1000: region.bbox1000, confidence: region.confidence })) });
      const settledA = reservation(docA.documentId);
      check("settlement closed the upload's compute reservation", settledA.split("|")[0] === "reserved", false);
      observe("reservationAfterOcr", settledA);
      ledger.booleans.ocrReal = true;

      // -----------------------------------------------------------------------------------------
      // 3. Simulated cron -> compile worker -> real Core -> signed receipt -> candidate.
      // -----------------------------------------------------------------------------------------
      hop("compile");
      const compiled = await driveJob(docA.jobId);
      check("compile job reaches a reviewable candidate", ["ready", "review_required"].includes(compiled.state), true);
      check("exactly one Core compile happened", core.calls.map(call => call.status), [200]);
      const coreCall = core.calls[0];
      check("Core received the OCR text of the uploaded document under the customer-data route",
        [coreCall.phraseInRegions, coreCall.privacyPolicy, coreCall.documents.length], [true, "approved_customer_data", 1]);
      const candidateKey = `immutable/${workspace}/${workspace}/collections/${compiled.collectionId}/${compiled.manifestDigest.slice(7)}/candidate-world.json`;
      const candidate = JSON.parse(Buffer.from(await (await bucket.get(candidateKey)).arrayBuffer()).toString("utf8"));
      check("candidate binds the uploaded document and its sanitized version", candidate.sourceDocuments.map(doc => [doc.documentId, doc.versionKey]), [[docA.documentId, docA.versionKey]]);
      check("candidate's Core execution is the call Core answered", [candidate.coreExecution.runtime, candidate.coreExecution.receipt.requestId, candidate.coreExecution.receipt.coreReleaseDigest],
        ["tavonel-python-core-v2", coreCall.requestId, coreReleaseDigest]);
      ledger.booleans.coreCompileReal = true;
      const trust = readExportTrustStoreEnv(signingEnv);
      const verified = verifyCompileReceipt(candidate.signedReceipt, { tenantId: workspace, workspaceId: workspace }, trust);
      check("compile receipt verifies under the ephemeral trust store", verified.ok, true);
      check("signed receipt binds Core's output digest and the admitting gate receipt",
        [verified.payload.coreOutputSha256, verified.payload.customerDataGateReceiptSha256, verified.payload.manifestDigest],
        [candidate.coreExecution.receipt.outputSha256, gate.receiptSha256, compiled.manifestDigest]);
      check("receipt signature is audited", sql(`select count(*) from public.enterprise_audit_events where workspace_key='${workspace}' and action='compile.receipt_signed' and target_id='${candidate.signedReceipt.signature.signedPayloadSha256}'`), "1");
      check("candidate provenance is registered", sql(`select count(*) from public.foundation_collection_artifact_provenance where workspace_key='${workspace}' and manifest_digest='${compiled.manifestDigest}'`), "1");
      ledger.booleans.receiptSigned = true;
      observe("candidate", { collectionId: compiled.collectionId, manifestDigest: compiled.manifestDigest, jobState: compiled.state,
        coreRequestId: coreCall.requestId, coreOutputSha256: candidate.coreExecution.receipt.outputSha256, receiptKeyId: candidate.signedReceipt.signature.keyId });

      // -----------------------------------------------------------------------------------------
      // 4. Failure path, part 1: duplicates do not repeat OCR, Core or the charge.
      // -----------------------------------------------------------------------------------------
      hop("duplicates");
      const token = await ownerToken();
      const before = { ...counts(), reservation: reservation(docA.documentId), keys: await listKeys(docPrefix), candidates: await candidateKeys(), job: jobRow(docA.jobId) };
      const reconfirm = await app("/api/uploads/confirm", token, { documentId: docA.documentId, sourceSha256: docA.contentSha256,
        attemptKey: docA.attemptKey, scopeDigest: docA.scopeDigest, fileKey: docA.fileKey });
      check("duplicate confirm is an idempotent success", [reconfirm.status, reconfirm.body?.code], [200, "UPLOAD_CONFIRMED"]);
      check("duplicate confirm retains the same approved identities",
        [reconfirm.body?.approvedFile?.fileKey, reconfirm.body?.approvedFile?.documentId, reconfirm.body?.approvedFile?.fileState],
        [docA.fileKey, docA.documentId, "confirmed"]);
      check("duplicate confirm keeps the first confirmation time", sql(`select confirmed_at from public.foundation_intake_admissions where document_id='${docA.documentId}'`), confirmedAt);
      await deliver(docA.objectKey, 2);
      const reenqueue = await app("/api/compile-jobs", token, { documentIds: [docA.documentId] });
      check("re-enqueueing the same documents returns the same job", [reenqueue.status < 300, reenqueue.body?.jobId], [true, docA.jobId]);
      for (let turn = 0; turn < 2; turn++) check("simulated cron stays authorized", (await cron()).status, 200);
      const after = { ...counts(), reservation: reservation(docA.documentId), keys: await listKeys(docPrefix), candidates: await candidateKeys(), job: jobRow(docA.jobId) };
      check("no second OCR call", after.ocr, before.ocr);
      check("no second Core compile", after.core, before.core);
      check("no second charge: the reservation row is unchanged", after.reservation, before.reservation);
      check("no new objects for the document", after.keys, before.keys);
      check("no new candidate, receipt, provenance or job", [after.candidates, after.audit, after.provenance, after.jobs, after.job], [before.candidates, before.audit, before.provenance, before.jobs, before.job]);
      observe("duplicateDeliveryCdrCalls", { before: before.cdr, after: after.cdr });
      ledger.booleans.duplicatesCauseNoSecondOcrCompileOrCharge = true;

      // -----------------------------------------------------------------------------------------
      // 5. Review and activate in the UI.
      // -----------------------------------------------------------------------------------------
      hop("review-activate");
      const { acceptEvidenceThroughUi, activateCandidateThroughUi } = await import(pathToFileURL(path.join(nextRoot, "e2e/support/workspace-review-actions.ts")).href);
      const scope = `workspace_key='${workspace}' and collection_id='${compiled.collectionId}'`;
      check("nothing is active before the human review", sql(`select count(*) from public.foundation_active_worlds where ${scope}`), "0");
      await page.goto(`${origin}/workspace/review?collection=${compiled.collectionId}&manifest=${encodeURIComponent(compiled.manifestDigest)}`);
      await expect(page.getByRole("button", { name: "Accept", exact: true })).toBeVisible({ timeout: 60_000 });
      const accepted = await acceptEvidenceThroughUi(page, compiled.collectionId, compiled.manifestDigest);
      check("UI records the evidence acceptance", accepted.status(), 201);
      const activated = await activateCandidateThroughUi(page, { collectionId: compiled.collectionId, manifestDigest: compiled.manifestDigest,
        expectedCurrentManifest: null, expectedCurrentRevision: 0 }, "Reviewed the joined E2E synthetic upload and its OCR evidence.");
      check("UI activates the reviewed candidate", [activated.status(), (await activated.json()).code], [200, "WORLD_ACTIVE"]);
      check("SQL active pointer is the reviewed candidate", sql(`select manifest_digest||'@'||revision from public.foundation_active_worlds where ${scope}`), `${compiled.manifestDigest}@1`);
      ledger.booleans.reviewActivateViaUi = true;

      // -----------------------------------------------------------------------------------------
      // 6. Consumers: owner session, API key, shipped MCP stdio and CLI.
      // -----------------------------------------------------------------------------------------
      hop("consumers");
      const scopes = ["ask:read", "collections:read", "worlds:read"];
      const issued = await app("/api/developer/keys", token, { name: "joined-e2e-consumer-read", scopes, expiresInDays: 1 });
      check("developer key route issues a read-only key", [issued.status, issued.body?.code], [201, "CREATED"]);
      consumerSecret = String(issued.body.token ?? ""); delete issued.body.token;
      const answerOf = body => ({ code: body?.code, retrievalPath: body?.retrievalPath, activeWorld: body?.activeWorld, answer: body?.answer, citations: body?.citations });
      const ask = async bearer => (await app(`/api/v1/collections/${compiled.collectionId}/ask`, bearer, { question })).body;
      const ownerAnswer = answerOf(await ask(token));
      check("owner-session ask is a grounded answer on the activated revision", [ownerAnswer.code, ownerAnswer.activeWorld?.manifestDigest], ["GROUNDED_ANSWER", compiled.manifestDigest]);
      const cited = (ownerAnswer.citations ?? []).filter(citation => PHRASE.test(citation.excerpt ?? ""));
      check("a citation quotes the uploaded document's phrase", cited.length > 0, true);
      check("that citation names page 1 and an in-range bbox", cited.every(c => c.pageNumber1 === 1 && Array.isArray(c.bbox1000) && c.bbox1000.length === 4 && c.bbox1000.every(v => v >= 0 && v <= 1000)), true);
      check("that citation binds this run's uploaded document version", cited.every(c => [c.sourceId, c.sourceVersionId].some(v => String(v).includes(docA.versionKey) || String(v).includes(docA.documentId))), true);
      const keyAnswer = answerOf(await ask(consumerSecret));
      check("API key receives the same answer and citations", keyAnswer, ownerAnswer);

      // Owned consumer children: the key travels only in their environment; fetch is pinned to the local origin.
      const fetchGuard = path.join(root, "consumer-fetch-guard.cjs");
      writeFileSync(fetchGuard, `'use strict';const allowed=${JSON.stringify(origin)};const nativeFetch=globalThis.fetch;
Object.defineProperty(globalThis,'fetch',{value:function fetch(input,init){let t;try{t=new URL(typeof input==='string'||input instanceof URL?input:input.url);}catch{return Promise.reject(new TypeError('consumer fetch guard: unparseable URL'));}
if(t.origin!==allowed)return Promise.reject(new TypeError('consumer fetch guard: blocked non-loopback origin'));return nativeFetch(input,{...init,redirect:'error'});},writable:false,configurable:false});`);
      const consumerEnv = { ...env, TAVONEL_BASE_URL: origin, TAVONEL_API_KEY: consumerSecret, NODE_EXTRA_CA_CERTS: path.join(root, "cert.pem"), NODE_OPTIONS: `--require ${JSON.stringify(fetchGuard)}` };
      const runConsumer = (script, args, input = "") => new Promise((resolve, reject) => {
        const child = spawn(process.execPath, [path.join(nextRoot, "public/developer", script), ...args], { cwd: root, env: consumerEnv, stdio: ["pipe", "pipe", "pipe"] });
        let stdout = "", stderr = "";
        const timer = setTimeout(() => { stopOwnedChild(child); reject(new Error(`${script} timed out`)); }, 90_000);
        child.stdout.setEncoding("utf8").on("data", part => { stdout += part; }); child.stderr.setEncoding("utf8").on("data", part => { stderr += part; });
        child.once("error", reject);
        child.once("close", code => { clearTimeout(timer); code === 0 ? resolve(stdout) : reject(new Error(`${script} exited ${code}: ${redact(stderr).slice(0, 1000)}`)); });
        child.stdin.end(input);
      });
      const frames = [
        { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "tavonel-joined-e2e", version: "1" } } },
        { jsonrpc: "2.0", method: "notifications/initialized" },
        { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "ask_world", arguments: { collectionId: compiled.collectionId, question } } },
      ];
      const replies = new Map((await runConsumer("tavonel-mcp.mjs", [], `${frames.map(frame => JSON.stringify(frame)).join("\n")}\n`)).trim().split("\n").filter(Boolean).map(line => { const frame = JSON.parse(line); return [frame.id, frame]; }));
      const mcpResult = replies.get(2)?.result;
      check("MCP ask_world succeeds", mcpResult?.isError, false);
      check("MCP stdio receives the same answer and citations", answerOf(JSON.parse(mcpResult.content[0].text)), ownerAnswer);
      const cliAnswer = answerOf(JSON.parse(await runConsumer("tavonel-cli.mjs", ["ask_world", compiled.collectionId, question])));
      check("CLI receives the same answer and citations", cliAnswer, ownerAnswer);
      ledger.booleans.consumerCitesUploadedDoc = true;
      observe("consumerAnswer", { code: ownerAnswer.code, retrievalPath: ownerAnswer.retrievalPath,
        citations: cited.map(c => ({ evidenceId: c.evidenceId, sourceId: c.sourceId, sourceVersionId: c.sourceVersionId, pageNumber1: c.pageNumber1, bbox1000: c.bbox1000, excerpt: c.excerpt })),
        transports: ["owner-session-https", "api-key-https", "mcp-stdio", "cli-process"] });
      const activePointer = sql(`select manifest_digest||'@'||revision from public.foundation_active_worlds where ${scope}`);

      // -----------------------------------------------------------------------------------------
      // 7. Failure path, part 2: malware refusal, Core signature failure, Core receipt failure.
      // -----------------------------------------------------------------------------------------
      hop("malware");
      const malware = await apiUpload(token, docs.malware);
      const ocrBeforeMalware = ocrProxy.calls.length;
      await deliver(malware.objectKey, 1);
      check("real clamd detects the EICAR source", [cdrProxy.calls.at(-1).status, cdrProxy.calls.at(-1).refusal?.code], [422, "MALWARE_DETECTED"]);
      check("refused source gets a reject receipt and no immutable copy",
        [(await listKeys(`quarantine/${workspace}/${malware.documentId}/`)).includes(`quarantine/${workspace}/${malware.documentId}/cdr-reject.json`),
          (await listKeys(`immutable/${workspace}/${workspace}/${malware.documentId}/`)).length], [true, 0]);
      check("refused source never reaches OCR", ocrProxy.calls.length, ocrBeforeMalware);
      check("refused source is released, not charged", reservation(malware.documentId).split("|").slice(0, 2), ["released", "0"]);
      ledger.booleans.malwareRefusedBeforeOcr = true;
      ledger.booleans.cdrClamavReal = true;

      for (const [mode, docKey, expectedCode, flag] of [
        ["break-request-signature", "signature", /CORE_SIGNATURE_INVALID|CORE_V2_HTTP_401/, "coreSignatureFailureLeavesNoCandidate"],
        ["tamper-response", "receipt", /CORE_V2_RECEIPT_INVALID/, "coreReceiptFailureLeavesNoCandidate"],
      ]) {
        hop(`core-${mode}`);
        const uploaded = await apiUpload(token, docs[docKey]);
        await deliver(uploaded.objectKey, 1);
        const beforeFailure = { ...counts(), candidates: await candidateKeys() };
        core.mode = mode;
        const enqueued = await app("/api/compile-jobs", token, { documentIds: [uploaded.documentId] });
        check(`compile job for the ${mode} case is accepted`, [enqueued.status, enqueued.body?.code], [202, "COMPILE_JOB_ACCEPTED"]);
        const failed = await driveJob(enqueued.body.jobId);
        core.mode = "pass";
        const attempts = core.calls.slice(beforeFailure.core);
        check(`${mode}: Core was reached`, attempts.length > 0 && attempts.every(call => call.mode === mode), true);
        if (mode === "break-request-signature") check("Core itself refused the bad signature", attempts.every(call => call.status === 401 && call.code === "CORE_SIGNATURE_INVALID"), true);
        else check("Core answered 200 before the reply was altered", attempts.every(call => call.status === 200), true);
        check(`${mode}: the job fails with the integrity code`, [failed.state, expectedCode.test(failed.errorCode)], ["failed", true]);
        const afterFailure = { ...counts(), candidates: await candidateKeys() };
        check(`${mode}: no candidate, receipt or provenance exists`, [afterFailure.candidates, afterFailure.audit, afterFailure.provenance, failed.manifestDigest],
          [beforeFailure.candidates, beforeFailure.audit, beforeFailure.provenance, ""]);
        observe(`failure:${mode}`, { jobId: enqueued.body.jobId, errorCode: failed.errorCode, coreCalls: attempts.map(({ status, code }) => ({ status, code })) });
        ledger.booleans[flag] = true;
      }
      check("failure cases leave the activated World untouched", sql(`select manifest_digest||'@'||revision from public.foundation_active_worlds where ${scope}`), activePointer);
      observe("coreCalls", core.calls);
      observe("cdrCalls", cdrProxy.calls);
      observe("ocrCalls", ocrProxy.calls);
      observe("deliveries", deliveries);
      observe("browserVersion", browser.version());
      ledger.success = true;
      hop("done");
    } catch (error) {
      console.error(`[joined-e2e] FAILED at ${ledger.stage}${ledger.step ? `/${ledger.step}` : ""}: ${redact(error.stack ?? error.message)}`);
      // The failure record is on disk before any best-effort browser capture, which can itself hang or fail.
      ledger.failure = { name: error.name, code: typeof error.code === "string" ? error.code : null, message: redact(error.message).slice(0, 4000),
        stage: ledger.stage, step: ledger.step ?? null, coreCalls: core.calls, cdrCalls: cdrProxy.calls, ocrCalls: ocrProxy.calls, s3Arrivals: s3Arrivals.slice(-40) };
      checkpoint.tryWrite("failure");
      // Best-effort captures, each bounded; one that fails or overruns is named in the ledger, never hidden.
      const captureFailed = name => captureError => { (ledger.failure.captureErrors ??= {})[name] = String(captureError?.name ?? "Error"); };
      if (page) await withDeadline("failure-screenshot", 30_000, () => page.screenshot({ path: path.join(outputDir, "failure-screenshot.png"), fullPage: true })).catch(captureFailed("screenshot"));
      if (context) await withDeadline("failure-trace", 60_000, () => context.tracing.stop({ path: path.join(outputDir, "failure-trace.zip") })).catch(captureFailed("trace"));
      if (page) {
        ledger.failure.pagePath = (() => { try { return new URL(page.url()).pathname; } catch { return "?"; } })();
        ledger.failure.headings = await withDeadline("failure-headings", 15_000, () => page.getByRole("heading").allTextContents()).then(items => items.map(redact))
          .catch(captureError => { captureFailed("headings")(captureError); return []; });
        ledger.failure.liveRegions = await withDeadline("failure-live-regions", 15_000, () => page.locator('[role="status"],[role="alert"]').allTextContents())
          .then(items => items.map(t => redact(t.trim()).slice(0, 400)).filter(Boolean)).catch(captureError => { captureFailed("liveRegions")(captureError); return []; });
      }
      checkpoint.tryWrite("failure-detail");
      throw error;
    }
  };
  // The journey runs inside the local S3 runtime's scope. Once it is over, whichever way, stopping that runtime is a
  // cleanup task like any other: bounded and recorded, so it can never hold the teardown below hostage.
  let storageCallbackSettled;
  const storageCallbackDone = new Promise(resolve => { storageCallbackSettled = resolve; });
  let journeyError = null;
  const storageSettled = withLocalStorage(required("TAVONEL_LOCAL_SEAWEED_EXE"), storage => journeyInStorage(storage).finally(() => storageCallbackSettled()))
    .then(() => {}, error => { journeyError = error; });
  await Promise.race([storageCallbackDone, storageSettled]);
  await runCleanup(ledger, [{ name: "local-storage-stop", deadlineMs: 90_000, run: () => storageSettled }], { redact });
  if (journeyError) throw journeyError;
} catch (error) {
  ledger.failure ??= { name: error.name, code: typeof error.code === "string" ? error.code : null, message: redact(error.message).slice(0, 4000), stage: ledger.stage, step: ledger.step ?? null };
  ledger.failure.confirmBodyTransport = confirmBodyTransport.slice(-40);
  checkpoint.tryWrite("failure");
  console.error("Joined E2E failure:", redact(error.stack ?? error.message));
  process.exitCode = 1;
} finally {
  checkpoint.tryWrite("teardown");
  // Every teardown task is bounded, asynchronous and has an abort that really stops what it waited for: the browser's
  // process groups are SIGKILLed, a server's sockets destroyed, an owned child's tree SIGKILLed. docker and rm run under
  // runBounded, which kills its own child inside the task deadline (60 s + 2 x 2 s grace < 75 s).
  const logsDir = path.join(outputDir, "logs");
  const teardown = [
    ...(browser ? [{ name: "browser-close", deadlineMs: 60_000, run: () => browser.close(),
      abort: () => browserPids.map(pid => killProcessGroup(pid)).some(Boolean) }] : []),
    ...servers.map(({ name, server, connections }) => ({ name: `server-close:${name}`, deadlineMs: 15_000,
      run: () => closeServer(server), abort: () => abortServer(server, connections) })),
    { name: "service-logs", deadlineMs: 30_000, run: () => {
      if (ledger.failure) ledger.failure.browserEvents = browserEvents.slice(-80);
      mkdirSync(logsDir, { recursive: true });
      for (const { label, tail } of owned) writeFileSync(path.join(logsDir, `${label}.log`), `${tail.join("\n")}\n`);
      writeFileSync(path.join(logsDir, "browser-events.log"), `${browserEvents.join("\n")}\n`);
      writeFileSync(path.join(logsDir, "confirm-body-transport.json"), `${JSON.stringify(confirmBodyTransport.slice(-40), null, 2)}\n`);
    } },
  ];
  if (cdrContainer) {
    teardown.push(
      { name: "docker-logs", deadlineMs: 75_000, run: async () => {
        const { stdout, stderr } = await runBounded("docker logs", "docker", ["logs", "--tail", "4000", cdrContainer], { timeoutMs: 60_000, env });
        writeFileSync(path.join(logsDir, "cdr.log"), redact(`${stdout}${stderr}`));
      } },
      { name: "docker-rm", deadlineMs: 75_000, run: () => runBounded("docker rm", "docker", ["rm", "-f", cdrContainer], { timeoutMs: 60_000, env })
        .catch(error => { if (!/No such container/i.test(error.stderr ?? "")) throw error; }) },
    );
  }
  for (const { label, child } of [...owned].reverse()) {
    teardown.push({ name: `stop:${label}`, deadlineMs: 30_000, run: () => stopOwnedChild(child), abort: () => killOwnedTree(child) });
  }
  teardown.push({ name: "scratch-rm", deadlineMs: 75_000, run: () => {
    assert.ok(path.basename(root).startsWith("tavonel-joined-e2e-"));
    return runBounded("scratch rm", "rm", ["-rf", "--", root], { timeoutMs: 60_000, env });
  } });
  await runCleanup(ledger, teardown, { redact });
  ledger.finishedAt = new Date().toISOString();
  const finalWritten = concludeRun(ledger, checkpoint);
  consumerSecret = "";
  if (finalWritten) console.log(`[joined-e2e] ledger ${output} success=${ledger.success} stage=${ledger.stage} booleans=${JSON.stringify(ledger.booleans)}`);
  else console.error("[joined-e2e] LEDGER NOT WRITTEN: the final ledger did not reach disk, so this run is not a success; minimal evidence is above");
  if (checkpoint.failures.length) console.error(`[joined-e2e] ${checkpoint.failures.length} ledger write(s) failed; exit code ${LEDGER_NOT_WRITTEN_EXIT_CODE}`);
  if (ledger.failure) console.log(`[joined-e2e] failure: ${ledger.failure.stage}${ledger.failure.step ? `/${ledger.failure.step}` : ""}: ${String(ledger.failure.message).split("\n")[0]}`);
  const cleanupProblems = (ledger.cleanup ?? []).filter(entry => entry.outcome !== "ok");
  if (cleanupProblems.length) console.log(`[joined-e2e] cleanup problems: ${JSON.stringify(cleanupProblems)}`);
  // No process.exit here: the exit code is set and the process ends once its last handle closes, so nothing pending (a
  // write, a child's exit) is cut short. Every task above aborted what it could not finish, so that is normally at once.
  // If something still holds the process, this unref'd watchdog records it, fails the run and exits; the outer deadline
  // supervisor stops the process tree if even that cannot happen.
  const EXIT_WATCHDOG_MS = 30_000;
  setTimeout(() => {
    const held = process.getActiveResourcesInfo().filter(type => type !== "Timeout");
    ledger.success = false;
    ledger.exitWatchdog = { afterMs: EXIT_WATCHDOG_MS, activeResources: held.slice(0, 40) };
    checkpoint.tryWrite("exit-watchdog", { final: true });
    console.error(`[joined-e2e] still running ${EXIT_WATCHDOG_MS} ms after teardown (held by ${held.join(", ") || "nothing reported"}); exiting as a failure`);
    process.exit(checkpoint.failures.length ? LEDGER_NOT_WRITTEN_EXIT_CODE : process.exitCode || 1);
  }, EXIT_WATCHDOG_MS).unref();
}
