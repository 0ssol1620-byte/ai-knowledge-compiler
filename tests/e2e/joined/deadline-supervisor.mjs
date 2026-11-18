/**
 * Outer deadline for the joined E2E harness, enforced from outside the harness's own event loop.
 *
 *   node deadline-supervisor.mjs --deadline-seconds <n> --grace-seconds <g> [--record <file>]
 *     [--expect-stop-bound-seconds <s>] -- <command> [args...]
 *
 * The command runs as the leader of its own process group. When the deadline passes, or when this process receives
 * SIGINT/SIGTERM (a cancelled workflow), it snapshots the command's whole descendant tree by parent pid, so children that
 * left the group (Playwright launches Chromium detached, in a group of its own) are included, sends SIGTERM to the group
 * and to those outsiders, waits the grace period, then SIGKILLs the group and every process from the snapshot or found
 * since. A harness blocked in a synchronous child process (execFileSync) cannot run its own timers or signal handlers;
 * this process can. On Windows, used only by the local tests, the tree is stopped with `taskkill /T /F`.
 *
 * Nothing here can block this process's own event loop: `ps` and `taskkill` run as asynchronous children that are
 * SIGKILLed and given up on after HELPER_TIMEOUT_MS, signals are plain syscalls, and the record is written asynchronously
 * under RECORD_TIMEOUT_MS. A watchdog that does not depend on any of them ends the stop sequence at
 * grace + STOP_WATCHDOG_SECONDS whatever state it is in. So once the deadline (or a signal) fires, this process exits
 * within grace + STOP_BOUND_SECONDS. The workflow runs it under `timeout --kill-after`, sized from these constants, as the
 * last bound for the case where even this process cannot run.
 *
 * Exit status: the command's own (128 + n if it died by signal n), 124 when the deadline fired, or 128 + n when signal n
 * was forwarded. `--record` writes a small structural report (no argv, no environment, no output) for the artifact, once
 * with outcome "running" as the command starts and again at the end; a final report that cannot be written makes a zero
 * exit non-zero.
 */
import { spawn } from "node:child_process";
import { readFileSync, realpathSync } from "node:fs";
import { mkdir, rename, writeFile } from "node:fs/promises";
import { constants } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const DEADLINE_EXIT_CODE = 124;
/** One `ps` or `taskkill` call; past this it is SIGKILLed and the stop goes on without its answer. */
const HELPER_TIMEOUT_MS = 5_000;
/** How long a leader that SIGKILL did not reap is waited for before it is abandoned. */
const ABANDON_AFTER_KILL_MS = 10_000;
/** After grace, the stop sequence (two process-table reads, the KILL sweep, the abandon wait) is cut off here at the latest. */
export const STOP_WATCHDOG_SECONDS = 20;
const RECORD_TIMEOUT_MS = 4_000;
/**
 * From deadline (or signal) to this process's exit, beyond the grace period: the watchdog (20 s), the final record write
 * (4 s), the last stderr line (1 s), with room to spare. The workflow sizes its `timeout` wrapper from this number.
 */
export const STOP_BOUND_SECONDS = 30;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const signalNumber = signal => constants.signals[signal] ?? 1;

export function parseArgs(argv) {
  const split = argv.indexOf("--");
  if (split < 0 || split === argv.length - 1) {
    throw new Error("usage: deadline-supervisor.mjs --deadline-seconds <n> --grace-seconds <g> [--record <file>] [--expect-stop-bound-seconds <s>] -- <command> [args...]");
  }
  const options = {};
  const flags = argv.slice(0, split);
  for (let i = 0; i < flags.length; i += 2) {
    const [name, value] = [flags[i], flags[i + 1]];
    if (!["--deadline-seconds", "--grace-seconds", "--record", "--expect-stop-bound-seconds"].includes(name) || value === undefined) throw new Error(`unknown or incomplete option ${name}`);
    options[name.slice(2)] = value;
  }
  const deadlineSeconds = Number(options["deadline-seconds"]);
  const graceSeconds = Number(options["grace-seconds"] ?? 30);
  if (!(Number.isFinite(deadlineSeconds) && deadlineSeconds > 0)) throw new RangeError("--deadline-seconds must be a positive number");
  if (!(Number.isFinite(graceSeconds) && graceSeconds >= 0)) throw new RangeError("--grace-seconds must be zero or positive");
  // The workflow sizes its `timeout` wrapper from STOP_BOUND_SECONDS; a caller that sized it from another number is refused
  // before anything runs, so the two bounds cannot drift apart silently.
  if (options["expect-stop-bound-seconds"] !== undefined && Number(options["expect-stop-bound-seconds"]) !== STOP_BOUND_SECONDS) {
    throw new RangeError(`--expect-stop-bound-seconds ${options["expect-stop-bound-seconds"]} does not match this supervisor's stop bound of ${STOP_BOUND_SECONDS} s`);
  }
  return { deadlineSeconds, graceSeconds, record: options.record ?? null, command: argv.slice(split + 1) };
}

/**
 * Runs a short helper (ps, taskkill) as an asynchronous child and resolves within `timeoutMs` whatever it does: on overrun
 * it is SIGKILLed, unref'd and given up on. Never rejects.
 */
function runHelper(command, args, timeoutMs) {
  return new Promise(resolve => {
    let child;
    try {
      child = spawn(command, args, { stdio: ["ignore", "pipe", "ignore"], windowsHide: true });
    } catch {
      resolve({ status: null, stdout: "", timedOut: false });
      return;
    }
    let stdout = "", done = false;
    const finish = result => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      child.stdout?.destroy();
      resolve(result);
    };
    const timer = setTimeout(() => {
      try { child.kill("SIGKILL"); } catch { /* already gone */ }
      child.unref();
      finish({ status: null, stdout: "", timedOut: true });
    }, timeoutMs);
    child.stdout.setEncoding("utf8").on("data", part => { if (stdout.length < 8 * 1024 * 1024) stdout += part; });
    child.once("error", () => finish({ status: null, stdout: "", timedOut: false }));
    child.once("close", status => finish({ status, stdout, timedOut: false }));
  });
}

/** Every process as { pid, ppid, pgid }, from a bounded asynchronous `ps`; empty on Windows or when it gives no answer. */
export async function processTable() {
  if (process.platform === "win32") return [];
  const { stdout } = await runHelper("ps", ["-A", "-o", "pid=", "-o", "ppid=", "-o", "pgid="], HELPER_TIMEOUT_MS);
  return stdout.split("\n").map(line => line.trim().split(/\s+/).map(Number))
    .filter(([pid, ppid, pgid]) => pid > 0 && ppid >= 0 && pgid >= 0).map(([pid, ppid, pgid]) => ({ pid, ppid, pgid }));
}

/** Every descendant of `rootPid` in `table`, found by parent pid regardless of process group. */
export function descendants(rootPid, table) {
  const byParent = new Map();
  for (const row of table) byParent.set(row.ppid, [...(byParent.get(row.ppid) ?? []), row]);
  const found = [], queue = [rootPid], seen = new Set([rootPid]);
  while (queue.length) {
    for (const row of byParent.get(queue.shift()) ?? []) if (!seen.has(row.pid)) { seen.add(row.pid); found.push(row); queue.push(row.pid); }
  }
  return found;
}

/** True while `pid` exists and is not a zombie. */
export function isAlive(pid) {
  try { process.kill(pid, 0); } catch (error) { return error.code === "EPERM"; }
  if (process.platform !== "linux") return true;
  try {
    const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
    return stat.slice(stat.lastIndexOf(")") + 2)[0] !== "Z";
  } catch {
    return false;
  }
}

const send = (target, signal) => { try { process.kill(target, signal); return true; } catch { return false; } };

/**
 * SIGTERM to the tree rooted at `child`, then after `graceMs` SIGKILL to all of it. `note` receives a structural record.
 * Bounded: two process-table reads of at most HELPER_TIMEOUT_MS each, plus the grace period.
 */
export async function stopTree(child, graceMs, note = () => {}) {
  const pid = child.pid;
  if (!pid) return;
  if (process.platform === "win32") {
    const result = await runHelper("taskkill", ["/PID", String(pid), "/T", "/F"], 2 * HELPER_TIMEOUT_MS);
    note({ phase: "taskkill", exitStatus: result.status, timedOut: result.timedOut });
    return;
  }
  const tree = descendants(pid, await processTable());
  // pid -> the process group it had when it was seen as part of this tree. A process that was ours keeps its group when it
  // is reparented (an orphaned Chromium), so a recorded pid whose group has changed by the KILL sweep is a reused pid that
  // belongs to someone else, and is never signalled.
  const known = new Map([[pid, pid], ...tree.map(row => [row.pid, row.pgid])]);
  send(-pid, "SIGTERM");
  let outsideGroup = 0;
  for (const row of tree) if (row.pgid !== pid && send(row.pid, "SIGTERM")) outsideGroup++;
  note({ phase: "term", processes: known.size, outsideGroup });
  const until = Date.now() + graceMs;
  while (Date.now() < until && [...known.keys()].some(isAlive)) await sleep(100);
  const table = await processTable();
  for (const row of descendants(pid, table)) if (!known.has(row.pid)) known.set(row.pid, row.pgid);
  const groupNow = new Map(table.map(row => [row.pid, row.pgid]));
  send(-pid, "SIGKILL");
  let killed = 0, skippedReused = 0;
  for (const [target, pgid] of known) {
    if (!isAlive(target)) continue;
    if (groupNow.has(target) && groupNow.get(target) !== pgid) { skippedReused++; continue; }
    if (send(target, "SIGKILL")) killed++;
  }
  note({ phase: "kill", killed, skippedReused });
}

/** Runs `command` under the deadline and resolves the structural report, including the exit code to use. */
export async function supervise({ deadlineSeconds, graceSeconds, command }, { log = line => console.error(line), onStart = () => {} } = {}) {
  const report = { kind: "tavonel-joined-e2e-supervisor", deadlineSeconds, graceSeconds, stopBoundSeconds: STOP_BOUND_SECONDS,
    startedAt: new Date().toISOString(), childPid: null, outcome: "running", forwardedSignal: null, stops: [], exit: null };
  const child = spawn(command[0], command.slice(1), { stdio: "inherit", detached: process.platform !== "win32" });
  report.childPid = child.pid ?? null;
  onStart(report);
  const exited = new Promise(resolve => {
    child.once("exit", (code, signal) => resolve({ code, signal }));
    child.once("error", error => resolve({ code: 127, signal: null, spawnError: String(error?.code ?? error?.name ?? "Error") }));
  });
  let stopping = null, abandon, watchdog;
  const abandoned = new Promise(resolve => { abandon = resolve; });
  const stop = outcome => {
    if (stopping) return;
    report.outcome = outcome;
    report.stopStartedAt = new Date().toISOString();
    // Independent of stopTree: whatever the process-table reads and kills do, the stop sequence ends here.
    watchdog = setTimeout(() => { report.stopWatchdogFired = true; abandon({ code: null, signal: null, abandoned: true }); },
      graceSeconds * 1000 + STOP_WATCHDOG_SECONDS * 1000);
    stopping = stopTree(child, graceSeconds * 1000, entry => report.stops.push(entry))
      .catch(error => { report.stops.push({ phase: "error", name: String(error?.name ?? "Error") }); });
    stopping.then(() => sleep(ABANDON_AFTER_KILL_MS)).then(() => abandon({ code: null, signal: null, abandoned: true }));
  };
  const timer = setTimeout(() => {
    log(`[deadline-supervisor] ${deadlineSeconds} s deadline reached; stopping the process tree of pid ${child.pid}`);
    stop("deadline");
  }, deadlineSeconds * 1000);
  const handlers = ["SIGINT", "SIGTERM"].map(signal => [signal, () => {
    report.forwardedSignal ??= signal;
    log(`[deadline-supervisor] received ${signal}; stopping the process tree of pid ${child.pid}`);
    stop("signal");
  }]);
  for (const [signal, handler] of handlers) process.on(signal, handler);

  const result = await Promise.race([exited, abandoned]);
  clearTimeout(timer);
  // The command is gone (or abandoned); let an in-flight stop finish its KILL sweep, but never past the watchdog.
  if (stopping) await Promise.race([stopping, abandoned]);
  else if (process.platform !== "win32" && child.pid) report.leftoverGroupKilled = send(-child.pid, "SIGKILL"); // whatever the command left running
  clearTimeout(watchdog);
  for (const [signal, handler] of handlers) process.off(signal, handler);

  report.exit = { code: result.code, signal: result.signal, ...(result.spawnError ? { spawnError: result.spawnError } : {}), ...(result.abandoned ? { abandoned: true } : {}) };
  if (report.outcome === "running") report.outcome = "exited";
  report.exitCode = report.outcome === "deadline" ? DEADLINE_EXIT_CODE
    : report.outcome === "signal" ? 128 + signalNumber(report.forwardedSignal)
      : result.code ?? 128 + signalNumber(result.signal);
  report.endedAt = new Date().toISOString();
  return report;
}

let recordSequence = 0;
async function writeRecord(file, report) {
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.${++recordSequence}.tmp`;
  await writeFile(temporary, `${JSON.stringify(report, null, 2)}\n`);
  await rename(temporary, file);
}
/** Resolves true once the record is on disk, false if the write failed or did not finish within RECORD_TIMEOUT_MS. */
function writeRecordBounded(file, report) {
  return Promise.race([writeRecord(file, report).then(() => true, () => false), sleep(RECORD_TIMEOUT_MS).then(() => false)]);
}

/** Writes the last line, then exits; a stderr that never drains cannot hold this process past one more second. */
function finish(line, exitCode) {
  setTimeout(() => process.exit(exitCode), 1_000);
  try {
    process.stderr.write(`${line}\n`, () => process.exit(exitCode));
  } catch {
    process.exit(exitCode);
  }
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    finish(`[deadline-supervisor] ${error.message}`, 2);
    return;
  }
  let started = Promise.resolve(true);
  const report = await supervise(options, {
    onStart: initial => { if (options.record) started = writeRecordBounded(options.record, structuredClone(initial)); },
  });
  let exitCode = report.exitCode;
  if (options.record) {
    await started; // never overtake the "running" record with the final one
    if (!(await writeRecordBounded(options.record, report))) {
      console.error("[deadline-supervisor] supervisor record NOT written");
      if (exitCode === 0) exitCode = 1;
    }
  }
  finish(`[deadline-supervisor] outcome=${report.outcome} exit=${exitCode} child=${JSON.stringify(report.exit)}`, exitCode);
}

// Imported by joined-diagnostics.test.mjs for its helpers; runs only when it is the entry point.
const invokedDirectly = (() => {
  try {
    const [entry, self] = [realpathSync(process.argv[1]), realpathSync(fileURLToPath(import.meta.url))];
    return process.platform === "win32" ? entry.toLowerCase() === self.toLowerCase() : entry === self;
  } catch {
    return false;
  }
})();
if (invokedDirectly) await main();
