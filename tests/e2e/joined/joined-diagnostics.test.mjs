/**
 * The bounded-step, ledger-checkpoint and cleanup helpers of joined-e2e.mjs, and deadline-supervisor.mjs, tested with local
 * operations only: first as functions, then against real child processes that hang, block in a synchronous child, refuse
 * to close, lose their ledger write, receive a signal or reject late.
 *
 * The harness refuses to run anywhere but the disposable runner, so it cannot be imported here. This evaluates exactly the
 * block it delimits with `>>> joined-diagnostics helpers` / `<<< joined-diagnostics helpers`, in this process and, written
 * to a scratch module, in the child processes. Every child runs under a hard bound: one still running at its bound has its
 * process tree killed and fails its test. The never-exiting hung-body fixture only ever runs beneath the supervisor.
 *
 *   node --test core/tests/e2e/joined/joined-diagnostics.test.mjs
 */
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { EventEmitter } from "node:events";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { DEADLINE_EXIT_CODE, STOP_BOUND_SECONDS, descendants, isAlive, parseArgs } from "./deadline-supervisor.mjs";

const source = readFileSync(new URL("./joined-e2e.mjs", import.meta.url), "utf8");
const begin = source.indexOf("// >>> joined-diagnostics helpers");
const end = source.indexOf("// <<< joined-diagnostics helpers");
assert.ok(begin >= 0 && end > begin, "joined-e2e.mjs delimits its diagnostics helpers");
const helperNames = ["PROOF_FLAGS", "LEDGER_NOT_WRITTEN_EXIT_CODE", "StageTimeoutError", "LedgerCheckpointError", "withDeadline", "writeFileAtomic",
  "minimalEvidence", "ledgerCheckpointer", "createStepRunner", "installSignalCheckpoint", "recordUnhandledRejections", "runBounded",
  "closeServer", "trackConnections", "abortServer", "killProcessGroup", "runCleanup", "finalVerdict", "concludeRun", "safeConfirmHeaderEvidence", "observeConfirmResponseBodies"];
const moduleText = [
  'import { spawn } from "node:child_process";',
  'import { EventEmitter } from "node:events";',
  'import { renameSync, rmSync, writeFileSync } from "node:fs";',
  source.slice(begin, end),
  `export { ${helperNames.join(", ")} };`,
].join("\n");
const { PROOF_FLAGS, LEDGER_NOT_WRITTEN_EXIT_CODE, StageTimeoutError, LedgerCheckpointError, withDeadline, writeFileAtomic,
  ledgerCheckpointer, createStepRunner, installSignalCheckpoint, finalVerdict, concludeRun, safeConfirmHeaderEvidence, observeConfirmResponseBodies } =
  await import(`data:text/javascript;base64,${Buffer.from(moduleText).toString("base64")}`);

const scratch = mkdtempSync(path.join(tmpdir(), "joined-diagnostics-"));
after(() => rmSync(scratch, { recursive: true, force: true }));
const never = () => new Promise(() => {});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function journeyLedger() {
  return { kind: "tavonel-joined-e2e", success: false, stage: "browser-upload", step: null,
    booleans: { uploadViaUiVerified: false, ocrReal: false, coreCompileReal: false },
    timeline: [{ stage: "browser-upload", startedAt: "2026-10-03T00:00:00.000Z" }] };
}
function recorder(ledger) {
  const snapshots = [];
  return { snapshots, checkpoint: reason => snapshots.push({ reason, ledger: structuredClone(ledger) }) };
}

test("withDeadline settles as the operation does when it finishes in time", async () => {
  assert.equal(await withDeadline("fast", 10_000, async () => 42), 42);
  assert.equal(await withDeadline("ready", 10_000, Promise.resolve("reply")), "reply");
  await assert.rejects(withDeadline("fails", 10_000, async () => { throw new TypeError("boom"); }), TypeError);
});

test("withDeadline rejects a stalled operation with the stage named", async () => {
  await assert.rejects(withDeadline("browser-upload/signed-put", 20, never), error =>
    error instanceof StageTimeoutError && error.name === "StageTimeoutError" && error.stage === "browser-upload/signed-put"
      && error.deadlineMs === 20 && error.message.includes("browser-upload/signed-put"));
});

test("withDeadline refuses a deadline that is not finite and positive", () => {
  for (const deadlineMs of [0, -1, Infinity, Number.NaN, undefined]) assert.throws(() => withDeadline("unbounded", deadlineMs, never), RangeError);
});

test("confirm response diagnostics retain framing headers and completion counts only", async () => {
  assert.deepEqual(safeConfirmHeaderEvidence({
    "content-type": "application/json",
    "content-length": "31",
    "transfer-encoding": "chunked",
    "set-cookie": "must-not-be-kept",
    authorization: "must-not-be-kept",
  }), { "content-type": "application/json", "content-length": "31", "transfer-encoding": "chunked" });
  assert.deepEqual(safeConfirmHeaderEvidence({ "content-type": "x".repeat(129) }), {});

  const upstream = new PassThrough();
  const downstream = new PassThrough();
  const events = [];
  observeConfirmResponseBodies(upstream, downstream, event => events.push(event));
  upstream.pipe(downstream);
  upstream.end(Buffer.from("synthetic body"));
  await new Promise(resolve => downstream.once("finish", resolve));
  assert.deepEqual(events, [
    { side: "upstream", phase: "data", bytes: 14 },
    { side: "upstream", phase: "end", bytes: 14 },
    { side: "gateway", phase: "finish", bytes: 14 },
  ]);

  const stalledUpstream = new PassThrough();
  const stalledDownstream = new PassThrough();
  const stalledEvents = [];
  observeConfirmResponseBodies(stalledUpstream, stalledDownstream, event => stalledEvents.push(event));
  stalledUpstream.pipe(stalledDownstream);
  stalledUpstream.write(Buffer.from("partial"));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(stalledEvents, [{ side: "upstream", phase: "data", bytes: 7 }]);
  stalledUpstream.destroy();
  stalledDownstream.destroy();
});

test("confirm failure diagnostics use fixed fields without dynamic error details", () => {
  const gateway = source.match(/upstream\.on\("error", error => \{([\s\S]*?)\n      \}\);/);
  assert.ok(gateway);
  assert.match(gateway[1], /recordConfirm\(\{ side: "gateway", phase: "upstream-request-error" \}\)/);
  assert.doesNotMatch(gateway[1], /error\.(?:code|message)|errorText/);

  const browser = source.match(/const isBrowserConfirm = request =>([\s\S]*?)await page\.goto/);
  assert.ok(browser);
  const confirmFailure = browser[1].match(/if \(isBrowserConfirm\(request\)\) keep\("([^"]+)"\)/);
  assert.equal(confirmFailure?.[1], "confirm.browser method=POST route=/api/uploads/confirm phase=requestfailed");
});
test("a reply that fails after its deadline does not become an unhandled rejection", async () => {
  const unhandled = [];
  const record = reason => unhandled.push(reason);
  process.on("unhandledRejection", record);
  try {
    const late = () => new Promise((_, reject) => setTimeout(() => reject(new Error("late reply")), 40));
    await assert.rejects(withDeadline("late", 5, late), StageTimeoutError);
    await sleep(80);
    await new Promise(resolve => setImmediate(resolve));
  } finally {
    process.off("unhandledRejection", record);
  }
  assert.deepEqual(unhandled, []);
});

test("a step records its duration and HTTP status in the hop, logs it and checkpoints at both ends", async () => {
  const ledger = journeyLedger();
  const { snapshots, checkpoint } = recorder(ledger);
  const lines = [];
  let clock = 1_000;
  const step = createStepRunner({ ledger, checkpoint, log: line => lines.push(line), now: () => (clock += 250) });
  const reply = { status: () => 200 };
  assert.equal(await step("capability-headers", 90_000, Promise.resolve(reply)), reply);
  const [entry] = ledger.timeline[0].steps;
  assert.deepEqual([entry.step, entry.outcome, entry.httpStatus, entry.deadlineMs, entry.durationMs], ["capability-headers", "ok", 200, 90_000, 250]);
  assert.ok(entry.startedAt && entry.endedAt);
  assert.equal(ledger.step, null);
  assert.deepEqual(snapshots.map(s => s.reason), ["step-start:browser-upload/capability-headers", "step-end:browser-upload/capability-headers"]);
  assert.equal(snapshots[0].ledger.step, "capability-headers", "the checkpoint at the start names the running step");
  assert.equal(lines.length, 1);
  assert.match(lines[0], /browser-upload\/capability-headers ok 200 in 250 ms \(deadline 90000 ms\)/);
});

test("a step past its deadline fails visibly, is checkpointed as a timeout and leaves proof booleans false", async () => {
  const ledger = journeyLedger();
  const { snapshots, checkpoint } = recorder(ledger);
  const lines = [];
  const step = createStepRunner({ ledger, checkpoint, log: line => lines.push(line) });
  await assert.rejects(step("signed-put", 20, never), StageTimeoutError);
  const [entry] = ledger.timeline[0].steps;
  assert.deepEqual([entry.outcome, entry.errorName, entry.deadlineMs], ["timeout", "StageTimeoutError", 20]);
  assert.ok(entry.durationMs >= 0 && entry.endedAt);
  assert.equal(ledger.step, "signed-put", "the failed step stays named for the failure record");
  assert.equal(ledger.success, false);
  assert.ok(Object.values(ledger.booleans).every(value => value === false));
  const last = snapshots.at(-1);
  assert.equal(last.reason, "step-end:browser-upload/signed-put");
  assert.equal(last.ledger.timeline[0].steps[0].outcome, "timeout");
  assert.match(lines[0], /browser-upload\/signed-put timeout in \d+ ms \(deadline 20 ms\)/);
});

test("a step whose operation throws is recorded as an error, not a timeout", async () => {
  const ledger = journeyLedger();
  const step = createStepRunner({ ledger, checkpoint: () => {}, log: () => {} });
  await assert.rejects(step("confirm-body", 15_000, () => Promise.reject(new SyntaxError("not JSON"))), SyntaxError);
  assert.deepEqual([ledger.timeline[0].steps[0].outcome, ledger.timeline[0].steps[0].errorName], ["error", "SyntaxError"]);
});

test("writeFileAtomic replaces the file whole and leaves no temporary behind", () => {
  const dir = mkdtempSync(path.join(scratch, "atomic-"));
  const file = path.join(dir, "ledger.json");
  writeFileAtomic(file, "first");
  writeFileAtomic(file, "second");
  assert.equal(readFileSync(file, "utf8"), "second");
  assert.deepEqual(readdirSync(dir), ["ledger.json"]);
});

test("a failed atomic write reports the error and removes its temporary file", () => {
  const dir = mkdtempSync(path.join(scratch, "atomic-fail-"));
  const blocked = path.join(dir, "ledger.json");
  mkdirSync(blocked); // a non-empty directory cannot be replaced by a file rename
  writeFileSync(path.join(blocked, "keep"), "x");
  assert.throws(() => writeFileAtomic(blocked, "text"));
  assert.deepEqual(readdirSync(dir), ["ledger.json"]);
});

test("a checkpoint writes the redacted ledger; a write that fails is thrown, recorded and reported, never swallowed", () => {
  const dir = mkdtempSync(path.join(scratch, "checkpoint-"));
  const file = path.join(dir, "ledger.json");
  const ledger = { ...journeyLedger(), success: true, note: "bearer super-secret-value" };
  const redact = text => String(text).replaceAll("super-secret-value", "[redacted]");
  const errors = [];
  ledgerCheckpointer({ ledger, file, redact, logError: line => errors.push(line) })("hop:browser-upload");
  const text = readFileSync(file, "utf8");
  assert.equal(text.includes("super-secret-value"), false);
  const written = JSON.parse(text);
  assert.deepEqual([written.note, written.lastCheckpoint.reason, written.success], ["bearer [redacted]", "hop:browser-upload", false],
    "a checkpoint that is not the final write never records success");
  assert.deepEqual(errors, []);

  const reported = [];
  const failing = ledgerCheckpointer({ ledger, file: path.join(dir, "missing", "ledger.json"), redact, logError: line => errors.push(line),
    onFailure: failure => reported.push(failure) });
  assert.throws(() => failing("step-start:x"), error => error instanceof LedgerCheckpointError && error.code === "LEDGER_CHECKPOINT_FAILED"
    && error.reason === "step-start:x" && error.writeErrorCode === "ENOENT");
  assert.equal(errors.length, 1, "the failure reaches stderr");
  assert.match(errors[0], /^\[joined-e2e\] LEDGER NOT WRITTEN, minimal evidence: \{/);
  assert.equal(errors[0].includes("super-secret-value"), false);
  assert.deepEqual(reported.map(failure => [failure.reason, failure.writeErrorCode]), [["step-start:x", "ENOENT"]]);
  assert.deepEqual(ledger.checkpointFailures.map(failure => failure.reason), ["step-start:x"], "the ledger keeps the lost write");
  assert.equal(ledger.lastCheckpoint.reason, "hop:browser-upload", "lastCheckpoint names only a write that reached disk");
  assert.equal(failing.tryWrite("teardown"), false, "tryWrite reports the lost write instead of throwing");
  assert.equal(failing.failures.length, 2, "and still records it");
  assert.equal(finalVerdict(ledger), false, "a run with a lost ledger write is never a success");
});

function fakeProcess() {
  return Object.assign(new EventEmitter(), { pid: 4242, exitCode: undefined, kills: [], kill(pid, signal) { this.kills.push([pid, signal]); } });
}

test("SIGTERM is checkpointed synchronously, recorded as a cancellation and re-raised", () => {
  const ledger = journeyLedger();
  ledger.step = "signed-put";
  const { snapshots, checkpoint } = recorder(ledger);
  const processRef = fakeProcess();
  installSignalCheckpoint({ ledger, checkpoint, processRef, log: () => {} });
  processRef.emit("SIGTERM");
  assert.equal(snapshots.length, 1, "the checkpoint is written before the signal handler returns");
  const written = snapshots[0];
  assert.equal(written.reason, "signal:SIGTERM");
  assert.deepEqual([written.ledger.cancelled.signal, written.ledger.cancelled.stage, written.ledger.cancelled.step], ["SIGTERM", "browser-upload", "signed-put"]);
  assert.deepEqual([written.ledger.success, written.ledger.failure.name, written.ledger.failure.step], [false, "Cancelled", "signed-put"]);
  assert.ok(Object.values(written.ledger.booleans).every(value => value === false));
  assert.equal(processRef.exitCode, 143);
  assert.deepEqual(processRef.kills, [[4242, "SIGTERM"]], "with no other owner the signal is re-raised for default termination");
  assert.equal(processRef.listenerCount("SIGTERM"), 0, "the handler is one-shot");
});

test("a signal another listener owns is checkpointed but not raised a second time, and never reads as success", () => {
  const ledger = { ...journeyLedger(), success: true };
  const { snapshots, checkpoint } = recorder(ledger);
  const processRef = fakeProcess();
  installSignalCheckpoint({ ledger, checkpoint, processRef, log: () => {} });
  let ownerCalls = 0;
  processRef.on("SIGINT", () => { ownerCalls++; }); // e.g. Playwright's own SIGINT handler
  processRef.emit("SIGINT");
  assert.equal(ownerCalls, 1);
  assert.equal(snapshots.at(-1).reason, "signal:SIGINT");
  assert.equal(snapshots.at(-1).ledger.success, false);
  assert.equal(processRef.exitCode, 130);
  assert.deepEqual(processRef.kills, []);
});

test("a step whose start cannot be checkpointed never runs its operation", async () => {
  const ledger = journeyLedger();
  const checkpoint = reason => { throw new LedgerCheckpointError(reason, "ENOSPC", null); };
  const step = createStepRunner({ ledger, checkpoint, log: () => {} });
  let ran = false;
  await assert.rejects(step("signed-put", 1_000, async () => { ran = true; }), LedgerCheckpointError);
  assert.equal(ran, false);
  assert.deepEqual([ledger.timeline[0].steps[0].outcome, ledger.timeline[0].steps[0].errorName], ["not-started", "LedgerCheckpointError"]);
  assert.equal(ledger.step, "signed-put");
});

test("a step that succeeded but whose end cannot be checkpointed fails", async () => {
  const ledger = journeyLedger();
  const checkpoint = reason => { if (reason.startsWith("step-end:")) throw new LedgerCheckpointError(reason, "EIO", null); };
  const step = createStepRunner({ ledger, checkpoint, log: () => {} });
  await assert.rejects(step("capability-headers", 1_000, async () => "reply"), LedgerCheckpointError);
});

test("the verdict refuses success to a cancelled, unclean or partly unwritten run, and concludeRun never exits 0 for one", () => {
  const proven = () => ({ ...journeyLedger(), success: true, cleanup: [{ task: "browser-close", outcome: "ok" }] });
  assert.equal(finalVerdict(proven()), true);
  assert.equal(finalVerdict({ ...proven(), success: "true" }), false);
  assert.equal(finalVerdict({ ...proven(), cancelled: { signal: "SIGTERM" } }), false);
  assert.equal(finalVerdict({ ...proven(), cleanup: [{ task: "browser-close", outcome: "timeout" }] }), false);
  assert.equal(finalVerdict({ ...proven(), checkpointFailures: [{ reason: "hop:compile" }] }), false);

  const dir = mkdtempSync(path.join(scratch, "conclude-"));
  const conclude = (ledger, file, exitCode) => {
    const processRef = { exitCode };
    const written = concludeRun(ledger, ledgerCheckpointer({ ledger, file, redact: String, logError: () => {} }), processRef);
    return { written, exitCode: processRef.exitCode, success: ledger.success };
  };
  const good = path.join(dir, "good.json");
  assert.deepEqual(conclude(proven(), good, undefined), { written: true, exitCode: undefined, success: true });
  assert.deepEqual([JSON.parse(readFileSync(good, "utf8")).success, JSON.parse(readFileSync(good, "utf8")).lastCheckpoint.final], [true, true]);
  const cancelled = path.join(dir, "cancelled.json");
  assert.deepEqual(conclude({ ...proven(), cancelled: { signal: "SIGTERM" } }, cancelled, 143), { written: true, exitCode: 143, success: false });
  assert.equal(JSON.parse(readFileSync(cancelled, "utf8")).success, false);
  assert.deepEqual(conclude({ ...proven(), cleanup: [{ task: "scratch-rm", outcome: "error" }] }, path.join(dir, "unclean.json"), undefined),
    { written: true, exitCode: 1, success: false });
  assert.deepEqual(conclude(proven(), path.join(dir, "missing", "final.json"), undefined),
    { written: false, exitCode: LEDGER_NOT_WRITTEN_EXIT_CODE, success: false });
});

test("the supervisor refuses a stop bound its timeout wrapper was not sized from, and finds descendants outside the group", () => {
  assert.deepEqual(parseArgs(["--deadline-seconds", "10", "--grace-seconds", "2", "--expect-stop-bound-seconds", String(STOP_BOUND_SECONDS), "--", "node", "x"]),
    { deadlineSeconds: 10, graceSeconds: 2, record: null, command: ["node", "x"] });
  assert.throws(() => parseArgs(["--deadline-seconds", "10", "--expect-stop-bound-seconds", String(STOP_BOUND_SECONDS + 1), "--", "node"]), RangeError);
  assert.throws(() => parseArgs(["--deadline-seconds", "0", "--", "node"]), RangeError);
  assert.throws(() => parseArgs(["--deadline-seconds", "5"]), /usage/);
  assert.throws(() => parseArgs(["--deadline", "5", "--", "node"]), /unknown or incomplete option/);
  // Playwright starts Chromium detached, in a group of its own: it is found by parent pid, not by group.
  const table = [{ pid: 10, ppid: 1, pgid: 10 }, { pid: 11, ppid: 10, pgid: 10 }, { pid: 12, ppid: 11, pgid: 12 },
    { pid: 13, ppid: 12, pgid: 12 }, { pid: 20, ppid: 1, pgid: 20 }];
  assert.deepEqual(descendants(10, table).map(row => row.pid), [11, 12, 13]);
});

// ---------------------------------------------------------------------------------------------
// Real child processes. Each one is bounded here; the supervisor and the helpers are what must stop what they own.
// ---------------------------------------------------------------------------------------------
const supervisorFile = fileURLToPath(new URL("./deadline-supervisor.mjs", import.meta.url));
const fixture = name => fileURLToPath(new URL(`./review-fixtures/${name}`, import.meta.url));
const helpersFile = path.join(scratch, "joined-diagnostics-helpers.mjs");
writeFileSync(helpersFile, moduleText);
const childEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => key !== "NODE_TEST_CONTEXT"));
let scripts = 0;
/** A child script with the harness helpers as `h`, its JSON parameters as `params` and `within(promise, ms)` (null on overrun). */
function childScript(body) {
  const file = path.join(scratch, `child-${++scripts}.mjs`);
  writeFileSync(file, [`import * as h from ${JSON.stringify(pathToFileURL(helpersFile).href)};`,
    'const params = JSON.parse(process.argv[2] ?? "{}");',
    "const within = (promise, ms) => Promise.race([promise, new Promise(resolve => setTimeout(() => resolve(null), ms).unref())]);",
    body].join("\n"));
  return file;
}
/** A docker-like child: deaf to SIGTERM, never exits, and writes its pid to argv[1] so the test can check it is gone. */
const stuckChild = "process.on('SIGTERM', () => {}); require('node:fs').writeFileSync(process.argv[1], String(process.pid)); setInterval(() => {}, 1000)";

function killTree(child) {
  if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", timeout: 10_000 });
  else try { process.kill(-child.pid, "SIGKILL"); } catch { /* already gone */ }
}
/**
 * Runs `node ...args` and resolves once it has exited and its output is closed. Still running at `boundMs`, its process tree
 * is killed and the promise rejects: that is the finite bound every test below asserts.
 */
function runNode(args, { boundMs, onStdout } = {}) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const child = spawn(process.execPath, args, { env: childEnv, stdio: ["ignore", "pipe", "pipe"], detached: process.platform !== "win32" });
    let stdout = "", stderr = "";
    child.stdout.setEncoding("utf8").on("data", part => { stdout += part; onStdout?.(stdout, child); });
    child.stderr.setEncoding("utf8").on("data", part => { stderr += part; });
    const timer = setTimeout(() => {
      killTree(child);
      reject(new Error(`child still running after its ${boundMs} ms bound; its tree was killed. stdout: ${stdout.slice(-1000)} stderr: ${stderr.slice(-2000)}`));
    }, boundMs);
    child.once("error", error => { clearTimeout(timer); reject(error); });
    child.once("close", (code, signal) => {
      clearTimeout(timer);
      resolve({ code, signal, stdout, stderr, elapsedMs: Date.now() - started, endedAt: Date.now() });
    });
  });
}
const supervised = (deadlineSeconds, graceSeconds, record, command) => [supervisorFile, "--deadline-seconds", String(deadlineSeconds),
  "--grace-seconds", String(graceSeconds), "--expect-stop-bound-seconds", String(STOP_BOUND_SECONDS), "--record", record, "--", ...command];
/** From the deadline's start to the supervisor's exit at the latest: deadline + grace + STOP_BOUND_SECONDS. */
const supervisorBoundMs = (deadlineSeconds, graceSeconds) => (deadlineSeconds + graceSeconds + STOP_BOUND_SECONDS) * 1000;
function jsonLine(text, marker) {
  const line = text.split(/\r?\n/).find(candidate => candidate.startsWith("{") && candidate.includes(marker));
  assert.ok(line, `a JSON line with ${marker} in: ${text.slice(-2000)}`);
  return JSON.parse(line);
}
async function waitGone(pid, ms) {
  const until = Date.now() + ms;
  while (isAlive(pid)) {
    if (Date.now() > until) return false;
    await sleep(50);
  }
  return true;
}
const readJson = file => JSON.parse(readFileSync(file, "utf8"));
const trueFlags = booleans => Object.entries(booleans).filter(([, value]) => value === true).map(([flag]) => flag);

test("the never-exiting hung-body fixture is stopped by the supervisor after its failure checkpoint reached disk", { timeout: 120_000 }, async () => {
  const record = path.join(scratch, "hung-body", "supervisor.json");
  const [deadline, grace] = [6, 1];
  const run = await runNode(supervised(deadline, grace, record, [process.execPath, fixture("hung-body-cleanup.mjs")]),
    { boundMs: supervisorBoundMs(deadline, grace) + 15_000 });
  assert.equal(run.code, DEADLINE_EXIT_CODE, run.stderr);
  assert.ok(run.elapsedMs < supervisorBoundMs(deadline, grace), `stopped within the supervisor's bound (${run.elapsedMs} ms)`);
  const printed = jsonLine(run.stdout, "checkpoint readable before hung cleanup");
  try {
    const written = readJson(printed.ledger);
    assert.deepEqual([written.success, written.lastCheckpoint.reason, written.failure.name, written.failure.stage, written.failure.step],
      [false, "failure", "StageTimeoutError", "browser-upload", "response-body"]);
    assert.deepEqual(trueFlags(written.booleans), []);
  } finally {
    rmSync(path.dirname(printed.ledger), { recursive: true, force: true });
  }
  const report = readJson(record);
  assert.deepEqual([report.kind, report.outcome, report.exitCode, report.deadlineSeconds, report.graceSeconds],
    ["tavonel-joined-e2e-supervisor", "deadline", DEADLINE_EXIT_CODE, deadline, grace]);
  assert.ok(report.stops.length > 0 && report.endedAt && Number.isInteger(report.childPid));
  assert.equal(JSON.stringify(report).includes("hung-body-cleanup"), false, "the record is structural: no argv");
  assert.ok(await waitGone(report.childPid, 5_000), "the hung fixture process is gone");
});

test("a browser close that never settles is aborted by killing the browser's process group, and the run ends by itself", { timeout: 60_000 }, async () => {
  const script = childScript(`
import { spawn } from "node:child_process";
// A stand-in for Chromium: detached into a process group of its own, as Playwright launches it, and deaf to SIGTERM.
const browser = spawn(process.execPath, ["-e", "process.on('SIGTERM', () => {}); setInterval(() => {}, 1000)"],
  { detached: process.platform !== "win32", stdio: "ignore" });
const browserExit = new Promise(resolve => browser.once("exit", (code, signal) => resolve({ code, signal })));
const ledger = { kind: "tavonel-joined-e2e", success: true, stage: "done", step: null, booleans: {}, timeline: [] };
const checkpoint = h.ledgerCheckpointer({ ledger, file: params.ledgerFile, redact: String });
const clean = await h.runCleanup(ledger, [{ name: "browser-close", deadlineMs: 300, run: () => new Promise(() => {}),
  abort: () => h.killProcessGroup(browser.pid) }], { log: () => {} });
const browserExited = await within(browserExit, 5_000);
h.concludeRun(ledger, checkpoint);
console.log(JSON.stringify({ clean, browserPid: browser.pid, browserExited }));
`);
  const ledgerFile = path.join(scratch, "browser-close-ledger.json");
  const run = await runNode([script, JSON.stringify({ ledgerFile })], { boundMs: 20_000 });
  assert.equal(run.code, 1, `not a success, and not held open by the abandoned close: ${run.stderr}`);
  const result = jsonLine(run.stdout, "browserPid");
  assert.equal(result.clean, false);
  assert.ok(result.browserExited, "the stuck browser was really stopped, not only no longer waited for");
  if (process.platform !== "win32") assert.equal(result.browserExited.signal, "SIGKILL");
  assert.ok(await waitGone(result.browserPid, 5_000));
  const written = readJson(ledgerFile);
  assert.deepEqual([written.success, written.lastCheckpoint.reason], [false, "final"]);
  const [entry] = written.cleanup;
  assert.deepEqual([entry.task, entry.outcome, entry.errorName, entry.aborted], ["browser-close", "timeout", "StageTimeoutError", true]);
});

test("a server close that never settles is aborted by destroying its sockets, and the run ends by itself", { timeout: 60_000 }, async () => {
  const script = childScript(`
import net from "node:net";
// A plain TCP server holding a connection: it has no closeAllConnections, so its close() waits for the client forever.
const server = net.createServer(() => {});
const connections = h.trackConnections(server);
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const accepted = new Promise(resolve => server.once("connection", resolve));
const client = net.connect(server.address().port, "127.0.0.1");
client.on("error", () => {});
await accepted;
const serverClosed = new Promise(resolve => server.once("close", () => resolve(true)));
const ledger = { kind: "tavonel-joined-e2e", success: true, stage: "done", step: null, booleans: {}, timeline: [] };
const checkpoint = h.ledgerCheckpointer({ ledger, file: params.ledgerFile, redact: String });
const clean = await h.runCleanup(ledger, [{ name: "server-close:probe", deadlineMs: 300, run: () => h.closeServer(server),
  abort: () => h.abortServer(server, connections) }], { log: () => {} });
const closed = await within(serverClosed, 5_000);
h.concludeRun(ledger, checkpoint);
console.log(JSON.stringify({ clean, closed, openConnections: connections.size }));
`);
  const ledgerFile = path.join(scratch, "server-close-ledger.json");
  const run = await runNode([script, JSON.stringify({ ledgerFile })], { boundMs: 20_000 });
  assert.equal(run.code, 1, run.stderr);
  assert.deepEqual(jsonLine(run.stdout, "openConnections"), { clean: false, closed: true, openConnections: 0 });
  const written = readJson(ledgerFile);
  assert.deepEqual([written.success, written.lastCheckpoint.reason], [false, "final"]);
  const [entry] = written.cleanup;
  assert.deepEqual([entry.task, entry.outcome, entry.aborted], ["server-close:probe", "timeout", true]);
});

test("runBounded stops a docker-like child that ignores SIGTERM, without ever blocking the event loop", { timeout: 60_000 }, async () => {
  const script = childScript(`
let ticks = 0;
const ticker = setInterval(() => { ticks++; }, 50);
const started = Date.now();
let failure = null;
try {
  await h.runBounded("docker logs", process.execPath, ["-e", ${JSON.stringify(stuckChild)}, params.pidFile], { timeoutMs: params.timeoutMs, graceMs: params.graceMs });
} catch (error) {
  failure = { name: error.name, stage: error.stage, deadlineMs: error.deadlineMs };
}
clearInterval(ticker);
console.log(JSON.stringify({ failure, elapsedMs: Date.now() - started, ticks }));
`);
  const pidFile = path.join(scratch, "docker-like-async.pid");
  const [timeoutMs, graceMs] = [1_500, 300];
  const run = await runNode([script, JSON.stringify({ pidFile, timeoutMs, graceMs })], { boundMs: 20_000 });
  assert.equal(run.code, 0, run.stderr);
  const result = jsonLine(run.stdout, "ticks");
  assert.deepEqual(result.failure, { name: "StageTimeoutError", stage: "docker logs", deadlineMs: timeoutMs });
  assert.ok(result.elapsedMs < timeoutMs + 2 * graceMs + 3_000, `bounded (${result.elapsedMs} ms)`);
  assert.ok(result.ticks >= 10, `the event loop kept running while the child hung (${result.ticks} ticks)`);
  assert.ok(await waitGone(Number(readFileSync(pidFile, "utf8")), 5_000), "the docker-like child is gone");
});

test("a harness blocked in a synchronous docker-like child is stopped, with that child, by the supervisor", { timeout: 120_000 }, async () => {
  const script = childScript(`
import { execFileSync } from "node:child_process";
console.log("blocking in a synchronous child");
execFileSync(process.execPath, ["-e", ${JSON.stringify(stuckChild)}, params.pidFile], { stdio: "ignore" });
console.log("the synchronous child returned");
`);
  const pidFile = path.join(scratch, "docker-like-sync.pid");
  const record = path.join(scratch, "sync-child", "supervisor.json");
  const [deadline, grace] = [3, 1];
  const run = await runNode(supervised(deadline, grace, record, [process.execPath, script, JSON.stringify({ pidFile })]),
    { boundMs: supervisorBoundMs(deadline, grace) + 15_000 });
  assert.equal(run.code, DEADLINE_EXIT_CODE, run.stderr);
  assert.ok(run.elapsedMs < supervisorBoundMs(deadline, grace), `stopped within the supervisor's bound (${run.elapsedMs} ms)`);
  assert.ok(run.stdout.includes("blocking in a synchronous child") && !run.stdout.includes("returned"));
  const report = readJson(record);
  assert.deepEqual([report.outcome, report.exitCode], ["deadline", DEADLINE_EXIT_CODE]);
  if (process.platform !== "win32") {
    assert.ok(report.stops.find(entry => entry.phase === "term")?.processes >= 2, "the term phase saw the harness and its synchronous child");
  }
  assert.ok(await waitGone(report.childPid, 5_000), "the blocked harness is gone");
  assert.ok(await waitGone(Number(readFileSync(pidFile, "utf8")), 5_000), "the SIGTERM-deaf synchronous child is gone too");
});

test("the reviewer's failed-checkpoint reproduction now fails closed: the lost write is thrown, not swallowed", { timeout: 60_000 }, async () => {
  const run = await runNode([fixture("checkpoint-write-failure.mjs")], { boundMs: 20_000 });
  assert.notEqual(run.code, 0, "the reproduction no longer exits as if nothing happened");
  assert.match(run.stderr, /LedgerCheckpointError/);
  assert.match(run.stderr, /ledger checkpoint failure was not written \(ENOENT\)/);
  assert.equal(run.stdout.includes("failed checkpoint is swallowed"), false);
});

test("a run whose final ledger write fails exits LEDGER_NOT_WRITTEN with only structural evidence on stderr", { timeout: 60_000 }, async () => {
  const script = childScript(`
const ledger = { kind: "tavonel-joined-e2e", success: true, stage: "consumers", step: "ask",
  booleans: { ...Object.fromEntries(h.PROOF_FLAGS.map(flag => [flag, false])), uploadViaUiVerified: true, notAProofFlag: true },
  timeline: [], observations: { answer: params.secret },
  failure: { name: "AssertionError", code: params.secret, message: "answer quoted " + params.secret, stage: "consumers", step: "ask" } };
const checkpoint = h.ledgerCheckpointer({ ledger, file: params.ledgerFile, redact: String,
  onFailure: () => { process.exitCode = h.LEDGER_NOT_WRITTEN_EXIT_CODE; } });
const written = h.concludeRun(ledger, checkpoint);
console.log(JSON.stringify({ written, success: ledger.success, failures: checkpoint.failures.length }));
`);
  const secret = "fixture-redaction-sentinel-7f3a";
  const ledgerFile = path.join(scratch, "missing-parent", "final.json");
  const run = await runNode([script, JSON.stringify({ secret, ledgerFile })], { boundMs: 20_000 });
  assert.equal(run.code, LEDGER_NOT_WRITTEN_EXIT_CODE, run.stderr);
  assert.deepEqual(jsonLine(run.stdout, "failures"), { written: false, success: false, failures: 1 });
  assert.equal(existsSync(ledgerFile), false);
  assert.equal(run.stderr.includes(secret), false, "no message, observation or code reaches stderr");
  const marker = "LEDGER NOT WRITTEN, minimal evidence: ";
  const line = run.stderr.split(/\r?\n/).find(candidate => candidate.includes(marker));
  assert.ok(line, run.stderr);
  const evidence = JSON.parse(line.slice(line.indexOf(marker) + marker.length));
  assert.deepEqual(Object.keys(evidence), ["kind", "ledgerWritten", "success", "stage", "step", "failure", "proof", "cancelled", "checkpoint"]);
  assert.deepEqual([evidence.kind, evidence.ledgerWritten, evidence.success, evidence.stage, evidence.step, evidence.cancelled],
    ["tavonel-joined-e2e-minimal-evidence", false, false, "consumers", "ask", null]);
  assert.deepEqual(evidence.failure, { name: "AssertionError", code: "[withheld]", stage: "consumers", step: "ask" });
  assert.deepEqual(Object.keys(evidence.proof), [...PROOF_FLAGS], "exactly the fixed proof flags, nothing else from ledger.booleans");
  assert.deepEqual(trueFlags(evidence.proof), ["uploadViaUiVerified"]);
  assert.deepEqual(evidence.checkpoint, { reason: "final", writeErrorCode: "ENOENT" });
});

const signalScript = () => childScript(`
const ledger = { kind: "tavonel-joined-e2e", success: true, stage: "compile", step: "drive-job",
  booleans: { ...Object.fromEntries(h.PROOF_FLAGS.map(flag => [flag, false])), uploadViaUiVerified: true, ocrReal: true }, timeline: [] };
const checkpoint = h.ledgerCheckpointer({ ledger, file: params.ledgerFile, redact: String });
h.installSignalCheckpoint({ ledger, checkpoint });
setInterval(() => {}, 1000);
console.log("ready");
`);
function assertCancelledLedger(file) {
  const written = readJson(file);
  assert.deepEqual([written.success, written.lastCheckpoint.reason, written.cancelled.signal, written.cancelled.stage, written.cancelled.step, written.failure.name],
    [false, "signal:SIGTERM", "SIGTERM", "compile", "drive-job", "Cancelled"]);
  assert.deepEqual(trueFlags(written.booleans), ["uploadViaUiVerified", "ocrReal"], "only what was proven before the signal is true");
}
const posixOnly = process.platform === "win32" ? "POSIX signal delivery; Windows has no SIGTERM handlers" : false;

test("a real SIGTERM is checkpointed, recorded as a cancellation and re-raised for default termination", { timeout: 60_000, skip: posixOnly }, async () => {
  const ledgerFile = path.join(scratch, "signal-ledger.json");
  let signalledAt = 0;
  const run = await runNode([signalScript(), JSON.stringify({ ledgerFile })], { boundMs: 20_000,
    onStdout: (stdout, child) => { if (!signalledAt && stdout.includes("ready")) { signalledAt = Date.now(); child.kill("SIGTERM"); } } });
  assert.ok(signalledAt > 0, "the child became ready and was signalled");
  assert.deepEqual([run.code, run.signal], [null, "SIGTERM"], "terminated by the signal, which was observed, not swallowed");
  assert.ok(run.endedAt - signalledAt < 5_000);
  assertCancelledLedger(ledgerFile);
});

test("SIGTERM to the supervisor stops the harness tree, which checkpoints the cancellation first", { timeout: 120_000, skip: posixOnly }, async () => {
  const ledgerFile = path.join(scratch, "supervised-signal-ledger.json");
  const record = path.join(scratch, "supervised-signal", "supervisor.json");
  const [deadline, grace] = [60, 2];
  let signalledAt = 0;
  const run = await runNode(supervised(deadline, grace, record, [process.execPath, signalScript(), JSON.stringify({ ledgerFile })]), {
    boundMs: (grace + STOP_BOUND_SECONDS + 20) * 1000,
    onStdout: (stdout, child) => { if (!signalledAt && stdout.includes("ready")) { signalledAt = Date.now(); child.kill("SIGTERM"); } } });
  assert.ok(signalledAt > 0, "the supervised child became ready and the supervisor was signalled");
  assert.equal(run.code, 128 + 15, run.stderr);
  assert.ok(run.endedAt - signalledAt < (grace + STOP_BOUND_SECONDS) * 1000, `bounded (${run.endedAt - signalledAt} ms)`);
  const report = readJson(record);
  assert.deepEqual([report.outcome, report.forwardedSignal, report.exitCode, report.exit.signal], ["signal", "SIGTERM", 143, "SIGTERM"]);
  assert.ok(await waitGone(report.childPid, 5_000));
  assertCancelledLedger(ledgerFile);
});

test("late rejections, a step's and an orphaned waiter's, neither crash the run nor go unrecorded", { timeout: 60_000 }, async () => {
  const script = childScript(`
const ledger = { kind: "tavonel-joined-e2e", success: false, stage: "browser-upload", step: null,
  booleans: Object.fromEntries(h.PROOF_FLAGS.map(flag => [flag, false])), timeline: [{ stage: "browser-upload", startedAt: new Date().toISOString() }] };
const redact = text => String(text).replaceAll(params.secret, "[redacted]");
const checkpoint = h.ledgerCheckpointer({ ledger, file: params.ledgerFile, redact });
h.recordUnhandledRejections({ ledger, redact, log: () => {} });
const step = h.createStepRunner({ ledger, checkpoint, log: () => {} });
let stepError = null;
try {
  await step("capability-body", 50, () => new Promise((_, reject) => setTimeout(() => reject(new Error("late reply " + params.secret)), 300)));
} catch (error) {
  stepError = error.name;
}
// A waiter nobody awaits any more, like a Playwright waitForResponse after its page is gone, rejecting later still.
new Promise((_, reject) => setTimeout(() => reject(new Error("orphaned waiter " + params.secret)), 400));
await new Promise(resolve => setTimeout(resolve, 800));
const written = h.concludeRun(ledger, checkpoint);
console.log(JSON.stringify({ stepError, written }));
`);
  const secret = "late-rejection-secret-0f9e";
  const ledgerFile = path.join(scratch, "late-rejection-ledger.json");
  const run = await runNode([script, JSON.stringify({ secret, ledgerFile })], { boundMs: 20_000 });
  assert.equal(run.code, 1, `a failed run, concluded normally rather than crashed: ${run.stderr}`);
  assert.deepEqual(jsonLine(run.stdout, "stepError"), { stepError: "StageTimeoutError", written: true });
  assert.equal(/Unhandled|triggerUncaughtException/.test(run.stderr), false, run.stderr);
  const written = readJson(ledgerFile);
  assert.deepEqual([written.success, written.lastCheckpoint.reason, written.timeline[0].steps[0].outcome], [false, "final", "timeout"]);
  assert.equal(written.unhandledRejections.length, 1, "the step's late rejection is consumed; the orphaned one is recorded");
  assert.match(written.unhandledRejections[0], /orphaned waiter \[redacted\]/);
  assert.equal(JSON.stringify(written).includes(secret), false);
});
